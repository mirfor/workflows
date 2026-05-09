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
    blueprint_id: str
    version: str
    file_name: str
    """`<snake_id>__v<n>.py`."""
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


def generate(workflow: Workflow, generated_at: datetime | None = None) -> GeneratedWorkflow:
    """Wygeneruj `.py` source z workflow IR.

    Wynik jest deterministyczny dla danego `workflow` + `generated_at`.
    `generated_at` w headerze; nie wpływa na `source_hash` (hash tylko z IR).
    """
    blueprint_id = workflow.document.name
    version = str(workflow.document.version)
    snake_id = _to_snake(blueprint_id)
    pascal_id = _to_pascal(blueprint_id)
    class_name = f"{pascal_id}_v{version}"
    workflow_name = blueprint_id  # bez suffix; Build ID pinuje wersję
    file_name = f"{snake_id}__v{version}.py"
    src_hash = compute_source_hash(workflow)
    ts = (generated_at or datetime.now(tz=UTC)).isoformat(timespec="seconds")

    module = _build_module(workflow, class_name, workflow_name)
    ast.fix_missing_locations(module)
    body_code = ast.unparse(module)

    header = (
        f"# Generated from Blueprint {blueprint_id} v{version} at {ts}\n"
        f"# Source hash: {src_hash}\n"
        "# DO NOT EDIT — regeneruj przez generator (`scripts/regenerate_*` lub publish flow).\n"
    )
    full_source = header + body_code + "\n"
    formatted = black.format_str(full_source, mode=black.Mode(line_length=100))

    return GeneratedWorkflow(
        source=formatted,
        blueprint_id=blueprint_id,
        version=version,
        file_name=file_name,
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
        ast.parse(
            "from temporalio.common import RetryPolicy"
        ).body[0],
        ast.parse(
            "from temporalio.exceptions import ApplicationError"
        ).body[0],
    ]
    # Imports per Tool function
    seen_modules: set[str] = set()
    for fdef in workflow.use.functions.values():
        if isinstance(fdef, ToolFunction):
            if fdef.module not in seen_modules:
                statements.append(
                    ast.parse(f"import {fdef.module}").body[0]
                )
                seen_modules.add(fdef.module)
        elif isinstance(fdef, SpecializedAgentFunction):
            statements.append(
                ast.parse(
                    "from activities.specialized_agents import call_specialized_agent"
                ).body[0]
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
        "    \"\"\"Wyewaluuj wyrażenie JQ przez kontekst.\n"
        "\n"
        "    Action item (#15): zweryfikować że libjq nie łamie Workflow Sandbox.\n"
        "    Fallback: przenieść do activity (deterministic eval).\n"
        "    \"\"\"\n"
        "    prog = _JQ_CACHE.get(expr)\n"
        "    if prog is None:\n"
        "        prog = jq.compile(expr)\n"
        "        _JQ_CACHE[expr] = prog\n"
        "    return prog.input(ctx).first()\n"
    ).body


def _build_workflow_class(
    workflow: Workflow, class_name: str, workflow_name: str
) -> ast.ClassDef:
    """Zbuduj `@workflow.defn(name=...)`-owaną klasę z `run()` async method."""
    decorator = ast.Call(
        func=ast.Attribute(value=ast.Name("workflow", ast.Load()), attr="defn", ctx=ast.Load()),
        args=[],
        keywords=[ast.keyword(arg="name", value=ast.Constant(value=workflow_name))],
    )

    run_body: list[ast.stmt] = []

    # `steps_output: dict[str, Any] = {}`
    run_body.append(
        ast.parse('steps_output: dict[str, Any] = {}').body[0]
    )
    # `ctx: dict[str, Any] = {"input": input, "steps": steps_output}`
    run_body.append(
        ast.parse(
            'ctx: dict[str, Any] = {"input": input, "steps": steps_output}'
        ).body[0]
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
    if isinstance(task, (ForTask, ForkTask, ListenTask, RunTask)):
        # MVP: placeholder, walidator ostrzega
        return ast.parse(
            f'raise ApplicationError("Task type \'{type(task).__name__}\' '
            f'not yet implemented in MVP generator", non_retryable=True)'
        ).body

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
        call_expr = ast.parse(
            f"await workflow.execute_activity({target}, {_repr(with_arg)}, "
            f"{', '.join(timeout_kwargs + retry_kwarg)})"
        ).body[0].value
    else:  # SpecializedAgentFunction
        agent_call = {
            "agent": func.name,
            "endpoint_url": func.endpoint_url,
            "operation": func.operation,
            "with": task.with_ or {},
        }
        call_expr = ast.parse(
            f"await workflow.execute_activity(call_specialized_agent, "
            f"{_repr(agent_call)}, "
            f"{', '.join(timeout_kwargs + retry_kwarg)})"
        ).body[0].value

    assign = ast.Assign(
        targets=[ast.Name(name, ast.Store())],
        value=call_expr,
        type_comment=None,
    )
    export = ast.Assign(
        targets=[ast.Subscript(
            value=ast.Name(steps_var, ast.Load()),
            slice=ast.Constant(name),
            ctx=ast.Store(),
        )],
        value=ast.Name(name, ast.Load()),
    )
    # Optional: explicit `export.as` (#12)
    if task.export and task.export.as_:
        # ctx[steps][name] = _eval(<as>, ctx)
        export = ast.Assign(
            targets=[ast.Subscript(
                value=ast.Name(steps_var, ast.Load()),
                slice=ast.Constant(name),
                ctx=ast.Store(),
            )],
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
        non_retryable = list(rp.non_retryable_types) + list(meta.get("non_retryable_error_types", []))
        if non_retryable:
            kwargs.append(f"non_retryable_error_types={non_retryable!r}")
        if kwargs:
            retry_kwarg.append(f"retry_policy=RetryPolicy({', '.join(kwargs)})")

    return timeout_kwargs, retry_kwarg


def _build_do(
    task: DoTask, workflow: Workflow, ctx_var: str, steps_var: str
) -> list[ast.stmt]:
    stmts: list[ast.stmt] = []
    for named in task.do:
        stmts.extend(_build_task_stmts(named, workflow, ctx_var, steps_var))
    return stmts


def _build_wait(name: str, task: WaitTask, steps_var: str) -> list[ast.stmt]:
    delta = _iso_to_timedelta(task.wait)
    sleep = ast.parse(f"await workflow.sleep({delta})").body
    export = ast.parse(f'{steps_var}[{name!r}] = None').body
    return sleep + export


def _build_set(
    name: str, task: SetTask, ctx_var: str, steps_var: str
) -> list[ast.stmt]:
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
    return ast.parse(
        f"raise ApplicationError({err_type!r}, non_retryable=True)"
    ).body


def _build_switch(
    name: str, task: SwitchTask, ctx_var: str, steps_var: str, workflow: Workflow
) -> list[ast.stmt]:
    """Switch → if/elif/else."""
    # Każdy case: { case_id: { when, then } }; default = brak `when`
    branches: list[tuple[str | None, str]] = []
    for case_dict in task.switch:
        for case in case_dict.values():
            branches.append((case.when, case.then))

    if not branches:
        return []

    # Buduj if/elif/else
    if_stmt: ast.If | None = None
    current: ast.If | None = None
    for when, then in branches:
        body = ast.parse(f'{steps_var}[{name!r}] = {then!r}').body
        if when is None:  # default
            if current is None:
                # Brak żadnego if — emit goto bezwarunkowo
                return body
            current.orelse = body
            break
        new_if = ast.If(
            test=ast.parse(f'_eval({when!r}, {ctx_var})', mode="eval").body,
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


# ---------- Helpers -------------------------------------------------------------


_ISO_RE = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)


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
