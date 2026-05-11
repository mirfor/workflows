"""Generator IR → Python Temporal Workflow (`.py` plik per Blueprint × wersja).

Decyzje:
- #14: layout `generated/workflows/<snake_id>__v<n>.py`; header (Generated from / Source hash / DO NOT EDIT); `black` formatter.
- #15: Python `ast` module; mapping 12 task types; typed locals + `steps_output` dict + `_eval()` z compiled JQ cache.
- #17: source hash (SHA256 normalized JSON) → idempotency; `<PascalCaseId>_v<n>` class name.
- #28: cascade `default_timeout` (Tenant → Client Org → Blueprint) wstrzykiwany **przed** generacją (przez walidator/publisher).

MVP wspiera: `call`, `do`, `switch`, `try`, `wait`, `set`, `raise`, `emit`. Pozostałe (`for`, `fork`,
`listen`, `run`) emitują warning + placeholder `raise NotImplementedError(...)` w generated code.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import black

from ir import (
    CallTask,
    DoTask,
    EmitTask,
    ForkTask,
    ForTask,
    ListenTask,
    RaiseTask,
    RunTask,
    SetTask,
    SpecializedAgentFunction,
    SwitchTask,
    ToolFunction,
    TryTask,
    WaitTask,
    Workflow,
)


class GeneratorError(ValueError):
    """Błąd generatora — niezgodność IR ze spec lub task niewspierany w MVP."""


@dataclass(frozen=True, slots=True)
class GeneratedWorkflow:
    """Wynik generacji: `.py` jako string + metadane do manifestu."""

    source: str
    """Pełna zawartość pliku `.py` po formatowaniu `black`."""
    tenant_id: str
    """Decyzja #4 — fizyczna izolacja per Tenant; ścieżki per Tenant."""
    blueprint_id: str
    version: str
    file_name: str
    """`<snake_id>__v<n>.py`."""
    relative_path: str
    """Względna ścieżka od repo root: `generated/<tenant_id>/workflows/<file_name>`."""
    class_name: str
    """`<PascalCaseId>_v<n>` (suffix kosmetyczny, decyzja #17)."""
    workflow_temporal_name: str
    """Bez suffixu — Worker Versioning Build ID pinuje wersję (decyzja #14)."""
    source_hash: str
    """SHA256 z normalizowanego CNCF SW IR JSON (decyzja #17)."""


# ---------- Source hash (idempotency, decyzja #17) -------------------------------


def compute_source_hash(workflow: Workflow) -> str:
    """SHA256 z deterministycznie znormalizowanego IR (sorted keys, no whitespace)."""
    normalized = json.dumps(
        workflow.model_dump(by_alias=True, exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------- Public API ----------------------------------------------------------


def generate(
    workflow: Workflow,
    *,
    tenant_id: str,
    generated_at: datetime | None = None,
) -> GeneratedWorkflow:
    """Wygeneruj `.py` source z workflow IR.

    `tenant_id` (decyzja #4) — namespace Tenanta; wpływa na `relative_path` i manifest.
    Wynik jest deterministyczny dla danego `workflow` + `generated_at`.
    `generated_at` w headerze; nie wpływa na `source_hash` (hash tylko z IR).
    """
    if not tenant_id or not tenant_id.strip():
        raise GeneratorError("`tenant_id` jest wymagany (decyzja #4 — fizyczna izolacja).")
    blueprint_id = workflow.document.name
    version = str(workflow.document.version)
    snake_id = _to_snake(blueprint_id)
    pascal_id = _to_pascal(blueprint_id)
    class_name = f"{pascal_id}_v{version}"
    workflow_name = blueprint_id  # bez suffix; Build ID pinuje wersję
    file_name = f"{snake_id}__v{version}.py"
    relative_path = f"generated/{tenant_id}/workflows/{file_name}"
    src_hash = compute_source_hash(workflow)
    ts = (generated_at or datetime.now(tz=UTC)).isoformat(timespec="seconds")

    module = _build_module(workflow, class_name, workflow_name)
    ast.fix_missing_locations(module)
    body_code = ast.unparse(module)

    header = (
        f"# Generated from Blueprint {tenant_id}/{blueprint_id} v{version} at {ts}\n"
        f"# Source hash: {src_hash}\n"
        "# DO NOT EDIT — regeneruj przez generator (`scripts/regenerate_*` lub publish flow).\n"
    )
    full_source = header + body_code + "\n"
    formatted = black.format_str(full_source, mode=black.Mode(line_length=100))

    return GeneratedWorkflow(
        source=formatted,
        tenant_id=tenant_id,
        blueprint_id=blueprint_id,
        version=version,
        file_name=file_name,
        relative_path=relative_path,
        class_name=class_name,
        workflow_temporal_name=workflow_name,
        source_hash=src_hash,
    )


# ---------- AST construction ----------------------------------------------------


def _build_module(workflow: Workflow, class_name: str, workflow_name: str) -> ast.Module:
    body: list[ast.stmt] = []

    # Imports
    body.extend(_build_imports(workflow))

    # _eval helper z compiled JQ cache (decyzja #15)
    body.extend(_build_eval_helper())

    # Workflow class
    body.append(_build_workflow_class(workflow, class_name, workflow_name))

    return ast.Module(body=body, type_ignores=[])


def _build_imports(workflow: Workflow) -> list[ast.stmt]:
    statements: list[ast.stmt] = [
        ast.parse("from __future__ import annotations").body[0],
        ast.parse("import asyncio").body[0],
        ast.parse("from datetime import timedelta").body[0],
        ast.parse("from typing import Any").body[0],
        ast.parse("import jq").body[0],
        ast.parse("from temporalio import workflow").body[0],
        ast.parse("from temporalio.common import RetryPolicy").body[0],
        ast.parse("from temporalio.exceptions import ApplicationError").body[0],
    ]
    # Imports per Tool function
    seen_modules: set[str] = set()
    for fdef in workflow.use.functions.values():
        if isinstance(fdef, ToolFunction):
            if fdef.module not in seen_modules:
                statements.append(ast.parse(f"import {fdef.module}").body[0])
                seen_modules.add(fdef.module)
        elif isinstance(fdef, SpecializedAgentFunction):
            statements.append(
                ast.parse("from activities.specialized_agents import call_specialized_agent").body[
                    0
                ]
            )
    # Import record_child_engagement if any subprocess task is used
    if _uses_child_workflow(workflow.do):
        statements.append(
            ast.parse("from activities.tools.child_engagement import record_child_engagement").body[
                0
            ]
        )
    # Dedupe (defensywnie: powtarzalne specialized_agents import)
    deduped: list[ast.stmt] = []
    seen_text: set[str] = set()
    for stmt in statements:
        text = ast.unparse(stmt)
        if text not in seen_text:
            seen_text.add(text)
            deduped.append(stmt)
    return deduped


def _build_eval_helper() -> list[ast.stmt]:
    """Cache compiled JQ programs i helper `_eval`."""
    return ast.parse(
        "_JQ_CACHE: dict[str, Any] = {}\n"
        "\n"
        "def _eval(expr: str, ctx: dict[str, Any]) -> Any:\n"
        '    """Wyewaluuj wyrażenie JQ przez kontekst.\n'
        "\n"
        "    Action item (#15): zweryfikować że libjq nie łamie Workflow Sandbox.\n"
        "    Fallback: przenieść do activity (deterministic eval).\n"
        '    """\n'
        "    prog = _JQ_CACHE.get(expr)\n"
        "    if prog is None:\n"
        "        prog = jq.compile(expr)\n"
        "        _JQ_CACHE[expr] = prog\n"
        "    return prog.input(ctx).first()\n"
    ).body


def _build_workflow_class(workflow: Workflow, class_name: str, workflow_name: str) -> ast.ClassDef:
    """Zbuduj `@workflow.defn(name=...)`-owaną klasę z `run()` async method."""
    decorator = ast.Call(
        func=ast.Attribute(value=ast.Name("workflow", ast.Load()), attr="defn", ctx=ast.Load()),
        args=[],
        keywords=[ast.keyword(arg="name", value=ast.Constant(value=workflow_name))],
    )

    run_body: list[ast.stmt] = []

    # `steps_output: dict[str, Any] = {}`
    run_body.append(ast.parse("steps_output: dict[str, Any] = {}").body[0])
    # `ctx: dict[str, Any] = {"input": input, "steps": steps_output}`
    run_body.append(
        ast.parse('ctx: dict[str, Any] = {"input": input, "steps": steps_output}').body[0]
    )

    # Sekwencja zadań z workflow.do[]
    for named in workflow.do:
        run_body.extend(_build_task_stmts(named, workflow, ctx_var="ctx", steps_var="steps_output"))

    # Default return
    run_body.append(ast.Return(value=ast.Name("steps_output", ast.Load())))

    run_method = ast.AsyncFunctionDef(
        name="run",
        args=ast.arguments(
            posonlyargs=[],
            args=[
                ast.arg(arg="self"),
                ast.arg(arg="input", annotation=ast.parse("dict[str, Any]", mode="eval").body),
            ],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=run_body,
        decorator_list=[
            ast.Attribute(value=ast.Name("workflow", ast.Load()), attr="run", ctx=ast.Load())
        ],
        returns=ast.parse("dict[str, Any]", mode="eval").body,
    )

    return ast.ClassDef(
        name=class_name,
        bases=[],
        keywords=[],
        body=[run_method],
        decorator_list=[decorator],
    )


# ---------- Task → AST mapping (decyzja #15, tabela L10) -------------------------


def _build_task_stmts(
    named: dict[str, Any],
    workflow: Workflow,
    ctx_var: str,
    steps_var: str,
) -> list[ast.stmt]:
    name, task = next(iter(named.items()))

    if isinstance(task, CallTask):
        return _build_call(name, task, workflow, ctx_var, steps_var)
    if isinstance(task, DoTask):
        return _build_do(task, workflow, ctx_var, steps_var)
    if isinstance(task, WaitTask):
        return _build_wait(name, task, steps_var)
    if isinstance(task, SetTask):
        return _build_set(name, task, ctx_var, steps_var)
    if isinstance(task, EmitTask):
        return _build_emit(name, task, steps_var)
    if isinstance(task, RaiseTask):
        return _build_raise(name, task)
    if isinstance(task, SwitchTask):
        return _build_switch(name, task, ctx_var, steps_var, workflow)
    if isinstance(task, TryTask):
        return _build_try(name, task, workflow, ctx_var, steps_var)
    if isinstance(task, ForTask):
        return _build_for(name, task, workflow, ctx_var, steps_var)
    if isinstance(task, ForkTask):
        return _build_fork(name, task, workflow, ctx_var, steps_var)
    if isinstance(task, ListenTask):
        return _build_listen(name, task, ctx_var, steps_var)
    if isinstance(task, RunTask):
        return _build_run(name, task, ctx_var, steps_var)

    raise GeneratorError(f"Niewspierany task type: {type(task).__name__} dla {name!r}.")


def _build_call(
    name: str, task: CallTask, workflow: Workflow, ctx_var: str, steps_var: str
) -> list[ast.stmt]:
    func = workflow.use.functions.get(task.call)
    if func is None:
        raise GeneratorError(f"call.{name}: nieznana funkcja {task.call!r}.")

    timeout_kwargs, retry_kwarg = _resolve_policies(task.timeout, task.retries, workflow)

    if isinstance(func, ToolFunction):
        target = f"{func.module}.{func.operation}"
        with_arg = task.with_ if task.with_ is not None else {}
        # Activity arguments: pojedynczy dict (zakładamy, że Tools przyjmują dict / Pydantic input)
        call_expr = (
            ast.parse(
                f"await workflow.execute_activity({target}, {_repr(with_arg)}, "
                f"{', '.join(timeout_kwargs + retry_kwarg)})"
            )
            .body[0]
            .value
        )
    else:  # SpecializedAgentFunction
        agent_call = {
            "agent": func.name,
            "endpoint_url": func.endpoint_url,
            "operation": func.operation,
            "with": task.with_ or {},
        }
        call_expr = (
            ast.parse(
                f"await workflow.execute_activity(call_specialized_agent, "
                f"{_repr(agent_call)}, "
                f"{', '.join(timeout_kwargs + retry_kwarg)})"
            )
            .body[0]
            .value
        )

    assign = ast.Assign(
        targets=[ast.Name(name, ast.Store())],
        value=call_expr,
        type_comment=None,
    )
    export = ast.Assign(
        targets=[
            ast.Subscript(
                value=ast.Name(steps_var, ast.Load()),
                slice=ast.Constant(name),
                ctx=ast.Store(),
            )
        ],
        value=ast.Name(name, ast.Load()),
    )
    # Optional: explicit `export.as` (#12)
    if task.export and task.export.as_:
        # ctx[steps][name] = _eval(<as>, ctx)
        export = ast.Assign(
            targets=[
                ast.Subscript(
                    value=ast.Name(steps_var, ast.Load()),
                    slice=ast.Constant(name),
                    ctx=ast.Store(),
                )
            ],
            value=ast.parse(f"_eval({task.export.as_!r}, {ctx_var})").body[0].value,
        )
    return [assign, export]


def _resolve_policies(
    timeout: Any,
    retries: Any,
    workflow: Workflow,
) -> tuple[list[str], list[str]]:
    """Zamień policy ref / inline na kwargi `start_to_close_timeout=...`, `retry_policy=...`."""
    timeout_kwargs: list[str] = []
    if isinstance(timeout, str):
        tp = workflow.use.timeouts.get(timeout)
        if tp is None:
            raise GeneratorError(f"Timeout profile {timeout!r} nieznany w `use.timeouts`.")
    else:
        tp = timeout
    if tp is not None:
        timeout_kwargs.append(f"start_to_close_timeout={_iso_to_timedelta(tp.after)}")
        meta = (tp.metadata or {}).get("temporal", {})
        if meta.get("heartbeat"):
            timeout_kwargs.append(f"heartbeat_timeout={_iso_to_timedelta(meta['heartbeat'])}")
        if meta.get("schedule_to_close"):
            timeout_kwargs.append(
                f"schedule_to_close_timeout={_iso_to_timedelta(meta['schedule_to_close'])}"
            )

    retry_kwarg: list[str] = []
    if isinstance(retries, str):
        rp = workflow.use.retries.get(retries)
        if rp is None:
            raise GeneratorError(f"Retry profile {retries!r} nieznany w `use.retries`.")
    else:
        rp = retries
    if rp is not None:
        kwargs: list[str] = []
        if rp.delay:
            kwargs.append(f"initial_interval={_iso_to_timedelta(rp.delay)}")
        if rp.backoff and rp.backoff.exponential:
            kwargs.append(f"backoff_coefficient={rp.backoff.exponential.multiplier}")
        if rp.limit and rp.limit.attempt and rp.limit.attempt.count:
            kwargs.append(f"maximum_attempts={rp.limit.attempt.count}")
        # Temporal extensions
        meta = (rp.metadata or {}).get("temporal", {}) if rp.metadata else {}
        if meta.get("maximum_interval"):
            kwargs.append(f"maximum_interval={_iso_to_timedelta(meta['maximum_interval'])}")
        # non_retryable: merge manifest defaults (poza scope generatora — caller wstrzykuje) + profile
        non_retryable = list(rp.non_retryable_types) + list(
            meta.get("non_retryable_error_types", [])
        )
        if non_retryable:
            kwargs.append(f"non_retryable_error_types={non_retryable!r}")
        if kwargs:
            retry_kwarg.append(f"retry_policy=RetryPolicy({', '.join(kwargs)})")

    return timeout_kwargs, retry_kwarg


def _build_do(task: DoTask, workflow: Workflow, ctx_var: str, steps_var: str) -> list[ast.stmt]:
    stmts: list[ast.stmt] = []
    for named in task.do:
        stmts.extend(_build_task_stmts(named, workflow, ctx_var, steps_var))
    return stmts


def _build_wait(name: str, task: WaitTask, steps_var: str) -> list[ast.stmt]:
    delta = _iso_to_timedelta(task.wait)
    sleep = ast.parse(f"await workflow.sleep({delta})").body
    export = ast.parse(f"{steps_var}[{name!r}] = None").body
    return sleep + export


def _build_set(name: str, task: SetTask, ctx_var: str, steps_var: str) -> list[ast.stmt]:
    return ast.parse(f"{steps_var}[{name!r}] = {_repr(task.set)}").body


def _build_emit(name: str, task: EmitTask, steps_var: str) -> list[ast.stmt]:
    payload = task.emit.event.get("with", {})
    return ast.parse(
        f"workflow.logger.info({{'event': {_repr(payload)}}})\n"
        f"{steps_var}[{name!r}] = {_repr(payload)}"
    ).body


def _build_raise(name: str, task: RaiseTask) -> list[ast.stmt]:
    err = task.raise_.error
    if isinstance(err, str):
        return ast.parse(f"raise ApplicationError({err!r}, non_retryable=True)").body
    err_type = err.type or "InternalError"
    return ast.parse(f"raise ApplicationError({err_type!r}, non_retryable=True)").body


def _build_switch(
    name: str, task: SwitchTask, ctx_var: str, steps_var: str, workflow: Workflow
) -> list[ast.stmt]:
    """Switch → if/elif/else.

    F3.E.1: jeśli case ma `do` (mapper rebuild branches), emit branch body inline jako
    body if/elif/else. Fallback do `steps_output[name]=then` (jump reference) tylko
    gdy `do` brak (legacy / cross-branch jump).
    """
    branches: list[tuple[str | None, str, list]] = []
    for case_dict in task.switch:
        for case in case_dict.values():
            branches.append((case.when, case.then, case.do or []))

    if not branches:
        return []

    def _branch_body(then: str, do_seq: list) -> list[ast.stmt]:
        """Body branch: tracking decision + branch tasks (jeśli mapper rebuilduje case.do)."""
        body: list[ast.stmt] = ast.parse(f"{steps_var}[{name!r}] = {then!r}").body
        for named in do_seq:
            body.extend(_build_task_stmts(named, workflow, ctx_var, steps_var))
        return body

    if_stmt: ast.If | None = None
    current: ast.If | None = None
    for when, then, do_seq in branches:
        body = _branch_body(then, do_seq)
        if when is None:  # default
            if current is None:
                return body
            current.orelse = body
            break
        new_if = ast.If(
            test=ast.parse(f"_eval({when!r}, {ctx_var})", mode="eval").body,
            body=body,
            orelse=[],
        )
        if if_stmt is None:
            if_stmt = new_if
        else:
            assert current is not None
            current.orelse = [new_if]
        current = new_if

    return [if_stmt] if if_stmt else []


def _build_try(
    name: str, task: TryTask, workflow: Workflow, ctx_var: str, steps_var: str
) -> list[ast.stmt]:
    try_body: list[ast.stmt] = []
    for named in task.try_:
        try_body.extend(_build_task_stmts(named, workflow, ctx_var, steps_var))

    catch_body: list[ast.stmt] = []
    if task.catch.do:
        for named in task.catch.do:
            catch_body.extend(_build_task_stmts(named, workflow, ctx_var, steps_var))
    if not catch_body:
        catch_body = [ast.Pass()]

    handler = ast.ExceptHandler(
        type=ast.Name("ApplicationError", ast.Load()),
        name=task.catch.as_ or "_e",
        body=catch_body,
    )
    return [ast.Try(body=try_body or [ast.Pass()], handlers=[handler], orelse=[], finalbody=[])]


def _build_for(
    name: str, task: ForTask, workflow: Workflow, ctx_var: str, steps_var: str
) -> list[ast.stmt]:
    """For loop: `for <each> in _eval(<in>, ctx): <do body>`. Decyzja #6 / #15."""
    each = task.for_.each
    in_expr = task.for_.in_

    # Body wrapped: aktualizuj ctx[each] żeby JQ w body mógł odwołać się do bieżącego elementu
    body: list[ast.stmt] = ast.parse(f"{ctx_var}[{each!r}] = {each}").body
    for named in task.do:
        body.extend(_build_task_stmts(named, workflow, ctx_var, steps_var))

    init = ast.parse(f"{steps_var}[{name!r}] = []").body
    for_stmt = ast.For(
        target=ast.Name(each, ast.Store()),
        iter=ast.parse(f"_eval({in_expr!r}, {ctx_var})", mode="eval").body,
        body=body,
        orelse=[],
    )
    # Append iteration result do listy steps_output[name]
    body.append(ast.parse(f"{steps_var}[{name!r}].append({each})").body[0])
    return init + [for_stmt]


def _build_fork(
    name: str, task: ForkTask, workflow: Workflow, ctx_var: str, steps_var: str
) -> list[ast.stmt]:
    """Fork: równoległe wykonanie branches via `asyncio.gather`/`asyncio.wait`.

    Każdy branch = pojedynczy NamedTask. Generator emituje async helper functions,
    potem wywołuje je równolegle. `compete=True` → FIRST_COMPLETED + cancel reszty.
    """
    branches = task.fork.branches
    compete = task.fork.compete

    fn_defs: list[ast.stmt] = []
    fn_calls: list[str] = []
    for i, branch_dict in enumerate(branches):
        b_name, _b_task = next(iter(branch_dict.items()))
        b_body = _build_task_stmts(branch_dict, workflow, ctx_var, steps_var)
        fn_name = f"_branch_{name}_{i}"
        fn = ast.AsyncFunctionDef(
            name=fn_name,
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=b_body or [ast.Pass()],
            decorator_list=[],
            returns=None,
            type_comment=None,
        )
        fn_defs.append(fn)
        fn_calls.append(f"{fn_name}()")

    if compete:
        await_stmt = ast.parse(
            "await asyncio.wait(\n"
            f"    [asyncio.create_task(c) for c in [{', '.join(fn_calls)}]],\n"
            "    return_when=asyncio.FIRST_COMPLETED,\n"
            ")"
        ).body
    else:
        await_stmt = ast.parse(f"await asyncio.gather({', '.join(fn_calls)})").body

    set_stmt = ast.parse(f'{steps_var}[{name!r}] = "completed"').body
    return fn_defs + await_stmt + set_stmt


def _build_listen(name: str, task: ListenTask, ctx_var: str, steps_var: str) -> list[ast.stmt]:
    """Listen: subskrypcja eventów. MVP: minimal — workflow.wait_condition na flagę
    sygnałową (nazwa = `name`). Pełna obsługa signal handlers zarejestrowanych przez
    `@workflow.signal` decorator wymaga rozszerzenia generatora w F5+ (post-MVP).

    W MVP emit informacyjny placeholder + steps_output[name] = "listened".
    """
    # MVP: workflow.wait_condition zawsze przejdzie (lambda: True) → no-op listener
    return ast.parse(
        f'await workflow.wait_condition(lambda: True)\n{steps_var}[{name!r}] = "listened"'
    ).body


def _build_run(name: str, task: RunTask, ctx_var: str, steps_var: str) -> list[ast.stmt]:
    """Run: child workflow / script / shell / container.

    `run.workflow.mode == "wait"` → execute_child_workflow (await result).
    `run.workflow.mode == "fire_and_forget"` → start_child_workflow (don't await).
    Both modes register a child Engagement via `record_child_engagement` activity.
    Pozostałe (script/shell/container) emitują marker `run_external_skipped_in_mvp`.
    """
    spec = task.run
    if spec.workflow is not None:
        wf_ref = spec.workflow.name
        wf_input = spec.workflow.input or {}
        mode = spec.workflow.mode  # "wait" | "fire_and_forget"
        handle_var = f"_{name}_child_handle"

        # _name_child_wf_id = f"name-child-{workflow.info().workflow_id}"
        id_code = (
            f"{handle_var[1:].replace('_child_handle', '_child_wf_id')}"
            f' = f"{name}-child-{{workflow.info().workflow_id}}"'
        )
        child_id_var = f"_{name}_child_wf_id"

        # start_child_workflow (both modes — gives us run_id before awaiting)
        start_code = (
            f"{handle_var} = await workflow.start_child_workflow(\n"
            f"    {wf_ref!r}, {_repr(wf_input)}, id={child_id_var}\n"
            f")"
        )

        # record_child_engagement activity call
        record_code = (
            f"await workflow.execute_activity(\n"
            f"    record_child_engagement,\n"
            f"    {{\n"
            f'        "tenant_id": workflow.info().namespace,\n'
            f'        "agent_id": {wf_ref!r},\n'
            f'        "workflow_id": {handle_var}.id,\n'
            f'        "run_id": {handle_var}.first_run_id,\n'
            f'        "parent_workflow_id": workflow.info().workflow_id,\n'
            f"    }},\n"
            f"    start_to_close_timeout=timedelta(seconds=30),\n"
            f")"
        )

        if mode == "fire_and_forget":
            result_code = f'{steps_var}[{name!r}] = {{"child_workflow_id": {handle_var}.id}}'
        else:
            result_code = (
                f"{name}_result = await {handle_var}.result()\n"
                f"{steps_var}[{name!r}] = {name}_result"
            )

        full_code = "\n".join([id_code, start_code, record_code, result_code])
        return ast.parse(full_code).body

    kind = next(
        (k for k in ("script", "shell", "container") if getattr(spec, k) is not None),
        "unknown",
    )
    return ast.parse(
        f'{steps_var}[{name!r}] = {{"_marker": "run_external_skipped_in_mvp", "kind": {kind!r}}}'
    ).body


# ---------- Helpers -------------------------------------------------------------


def _uses_child_workflow(tasks: list[Any]) -> bool:
    """True jeśli jakikolwiek task (rekurencyjnie) to RunTask z run.workflow."""
    for named in tasks:
        _, task = next(iter(named.items()))
        if isinstance(task, RunTask) and task.run.workflow is not None:
            return True
        if isinstance(task, DoTask) and _uses_child_workflow(task.do):
            return True
        if isinstance(task, ForTask) and _uses_child_workflow(task.do):
            return True
        if isinstance(task, TryTask) and (
            _uses_child_workflow(task.try_)
            or (task.catch.do and _uses_child_workflow(task.catch.do))
        ):
            return True
        if isinstance(task, ForkTask) and any(
            _uses_child_workflow([b]) for b in task.fork.branches
        ):
            return True
        if isinstance(task, SwitchTask):
            for case_dict in task.switch:
                for case in case_dict.values():
                    if case.do and _uses_child_workflow(case.do):
                        return True
    return False


_ISO_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")


def _iso_to_timedelta(iso: str) -> str:
    """Konwersja prostego ISO 8601 duration na konstruktor `timedelta(...)` jako string."""
    m = _ISO_RE.match(iso)
    if not m:
        raise GeneratorError(f"Niewspierany ISO 8601 duration w generatorze: {iso!r}")
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = float(m.group(4) or 0)
    args = []
    if days:
        args.append(f"days={days}")
    if hours:
        args.append(f"hours={hours}")
    if minutes:
        args.append(f"minutes={minutes}")
    if seconds:
        args.append(f"seconds={seconds}")
    return f"timedelta({', '.join(args) or 'seconds=0'})"


def _to_snake(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()


def _to_pascal(s: str) -> str:
    return "".join(p.capitalize() for p in re.split(r"[^a-zA-Z0-9]+", s) if p)


def _repr(obj: Any) -> str:
    """Stabilny Python-repr dla dict/list/literal (sortowane klucze).

    NIE używa `json.dumps` (różne bool/None formatowanie) — buduje rekurencyjnie repr Pythona.
    """
    if isinstance(obj, dict):
        items = ", ".join(f"{k!r}: {_repr(v)}" for k, v in sorted(obj.items()))
        return "{" + items + "}"
    if isinstance(obj, list):
        return "[" + ", ".join(_repr(v) for v in obj) + "]"
    return repr(obj)
