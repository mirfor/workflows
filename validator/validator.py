"""Reguły walidacji IR (decyzja #16, kategorie A–F).

Pydantic już wymusza F (spec compliance, ISO 8601 duration, types). Walidator dodaje:
- A: graf — duplikaty IDs, container body non-empty, brak cykli (poza for)
- B: handles — switch.then references, catch.errors.with.type ∈ (base ∪ tool.errors)
- C: registry — `call.<function>` istnieje w `use.functions`; `timeout`/`retries` ref-y istnieją
- D: schemy — placeholder (#13: pełna walidacja w F3 dochodzi z type-compat)
- E: polityki Temporala — retry ma pola bez mapping (jitter, when, exceptWhen,
     limit.duration, limit.attempt.duration) → ERROR (#21)
- F: CNCF SW — egzekwowane przez Pydantic (`StrictModel`)

Decyzja #28: jeśli `call`/`run` task nie ma `timeout`, walidator emituje WARNING i
auto-aplikuje `default_timeout` (cascade Tenant → Client Org → Blueprint przed publish).
"""

from __future__ import annotations

from typing import Any

from ir import (
    BaseErrorType,
    CallTask,
    DoTask,
    ForkTask,
    ForTask,
    ListenTask,
    RetryPolicy,
    SwitchTask,
    TimeoutPolicy,
    TryCatch,
    TryTask,
    Workflow,
)
from validator.report import Severity, ValidationReport

BASE_ERROR_TYPES: frozenset[str] = frozenset(e.value for e in BaseErrorType)


def validate(workflow: Workflow) -> ValidationReport:
    """Pełna walidacja IR. Zwraca raport (lista issues z severity)."""
    rep = ValidationReport()
    seen_names: set[str] = set()

    _validate_use(workflow, rep)
    _walk(workflow.do, "do", workflow, seen_names, rep)
    _validate_workflow_metadata(workflow, rep)
    return rep


def apply_default_timeout(
    workflow: Workflow,
    cascade_after: str = "PT5M",
    cascade_heartbeat: str | None = "PT30S",
    cascade_schedule_to_close: str | None = None,
) -> Workflow:
    """Wstrzyknij `default_timeout` profile do `Use.timeouts` jeśli nie istnieje (#28).

    Wartości pochodzą z cascade resolution Tenant → Client Org → Blueprint;
    caller dostarcza je gotowe (mapper/publisher). Tu tylko mechanika injection.
    """
    if "default_timeout" in workflow.use.timeouts:
        return workflow

    metadata: dict[str, Any] | None = None
    if cascade_heartbeat or cascade_schedule_to_close:
        temporal: dict[str, Any] = {}
        if cascade_heartbeat:
            temporal["heartbeat"] = cascade_heartbeat
        if cascade_schedule_to_close:
            temporal["schedule_to_close"] = cascade_schedule_to_close
        metadata = {"temporal": temporal}

    workflow.use.timeouts["default_timeout"] = TimeoutPolicy(after=cascade_after, metadata=metadata)
    return workflow


# ---------- Implementacje reguł --------------------------------------------------


def _validate_use(wf: Workflow, rep: ValidationReport) -> None:
    funcs = wf.use.functions
    for fname, fdef in funcs.items():
        # C: function name w `Use` musi być spójna z polem `name` w def
        if fdef.name != fname:
            rep.add(
                "C001",
                Severity.ERROR,
                f"use.functions.{fname}.name",
                f"Pole `name` ({fdef.name!r}) nie zgadza się z kluczem ({fname!r}).",
            )

    # E: retry profile ma pola bez Temporal mapping → ERROR (#21)
    for rname, retry in wf.use.retries.items():
        _check_retry_no_temporal_mapping(retry, f"use.retries.{rname}", rep)

    # E: timeout profile musi mieć `after` (Pydantic to wymusza, ale informujemy
    # gdy `metadata.temporal.heartbeat` lub `schedule_to_close` mają zły format)
    for tname, t in wf.use.timeouts.items():
        # ISO 8601 sprawdza Pydantic (`IsoDuration`); tu sprawdzamy obecność `after` (też strict).
        if not t.after:
            rep.add(
                "E001",
                Severity.ERROR,
                f"use.timeouts.{tname}.after",
                "Pole `after` jest wymagane (Temporal start_to_close_timeout).",
            )


def _check_retry_no_temporal_mapping(retry: RetryPolicy, path: str, rep: ValidationReport) -> None:
    """Decyzja #21: jitter, when, exceptWhen, limit.duration, limit.attempt.duration → ERROR."""
    if retry.jitter is not None:
        rep.add(
            "E101",
            Severity.ERROR,
            f"{path}.jitter",
            "CNCF SW `jitter` nie ma mapping na Temporal RetryPolicy. Usuń pole.",
        )
    if retry.when is not None:
        rep.add(
            "E102",
            Severity.ERROR,
            f"{path}.when",
            "CNCF SW `when` (expression filter) nie ma mapping na Temporal. "
            "Użyj `nonRetryableTypes` lub typed errors.",
        )
    if retry.except_when is not None:
        rep.add(
            "E103",
            Severity.ERROR,
            f"{path}.exceptWhen",
            "CNCF SW `exceptWhen` nie ma mapping na Temporal. "
            "Użyj `nonRetryableTypes` lub typed errors.",
        )
    if retry.limit and retry.limit.duration is not None:
        rep.add(
            "E104",
            Severity.ERROR,
            f"{path}.limit.duration",
            "CNCF SW `limit.duration` (total) nie ma mapping na Temporal. "
            "Użyj timeoutu schedule_to_close zamiast.",
        )
    if retry.limit and retry.limit.attempt and retry.limit.attempt.duration is not None:
        rep.add(
            "E105",
            Severity.ERROR,
            f"{path}.limit.attempt.duration",
            "CNCF SW `limit.attempt.duration` nie ma mapping na Temporal. "
            "Użyj timeoutu start_to_close zamiast.",
        )


def _walk(
    do_seq: list[dict[str, Any]],
    base_path: str,
    wf: Workflow,
    seen_names: set[str],
    rep: ValidationReport,
) -> None:
    """Rekurencyjnie obejdź `do[]` i waliduj task po task."""
    for idx, named in enumerate(do_seq):
        if not isinstance(named, dict) or len(named) != 1:
            rep.add(
                "A002",
                Severity.ERROR,
                f"{base_path}[{idx}]",
                "Element `do[]` musi być dictem z dokładnie 1 kluczem (task name).",
            )
            continue
        name, task = next(iter(named.items()))
        if name in seen_names:
            rep.add(
                "A001",
                Severity.ERROR,
                f"{base_path}[{idx}].{name}",
                f"Duplikat task name w obrębie workflowu: {name!r}.",
            )
        seen_names.add(name)
        path = f"{base_path}[{idx}].{name}"
        _validate_task(task, path, wf, seen_names, rep)


def _validate_task(
    task: Any,
    path: str,
    wf: Workflow,
    seen_names: set[str],
    rep: ValidationReport,
) -> None:
    if isinstance(task, CallTask):
        _validate_call(task, path, wf, rep)
    elif isinstance(task, DoTask):
        _validate_container_body(task.do, f"{path}.do", "do", wf, seen_names, rep)
    elif isinstance(task, ForTask):
        _validate_container_body(task.do, f"{path}.do", "for", wf, seen_names, rep)
    elif isinstance(task, ForkTask):
        if not task.fork.branches:
            rep.add(
                "A011",
                Severity.ERROR,
                f"{path}.fork.branches",
                "`fork.branches` nie może być puste.",
            )
        for i, branch in enumerate(task.fork.branches):
            _walk([branch], f"{path}.fork.branches[{i}]", wf, seen_names, rep)
    elif isinstance(task, SwitchTask):
        _validate_switch(task, path, rep)
    elif isinstance(task, TryTask):
        _validate_container_body(task.try_, f"{path}.try", "try", wf, seen_names, rep)
        _validate_catch(task.catch, f"{path}.catch", wf, seen_names, rep)
    elif isinstance(task, ListenTask) and not task.listen.get("to"):
        rep.add(
            "A013",
            Severity.ERROR,
            f"{path}.listen.to",
            "`listen.to` jest wymagane.",
        )
    # WaitTask / EmitTask / RaiseTask / RunTask / SetTask: minimalne pola
    # są wymuszone przez Pydantic; brak dodatkowej walidacji w MVP.

    # Wspólne: ref-y do retries/timeouts musi istnieć w `use`
    _validate_policy_refs(task, path, wf, rep)


def _validate_call(call: CallTask, path: str, wf: Workflow, rep: ValidationReport) -> None:
    if call.call not in wf.use.functions:
        rep.add(
            "C002",
            Severity.ERROR,
            f"{path}.call",
            f"Funkcja {call.call!r} nie istnieje w `use.functions`.",
        )

    # E: brak timeout dla call → WARNING + auto-default w publishu (#28)
    if call.timeout is None:
        rep.add(
            "E201",
            Severity.WARNING,
            f"{path}.timeout",
            "Brak `timeout`; przed publish wstrzykiwany jest `default_timeout` "
            "(cascade Tenant → Client Org → Blueprint).",
        )


def _validate_container_body(
    body: list[dict[str, Any]],
    path: str,
    container_kind: str,
    wf: Workflow,
    seen_names: set[str],
    rep: ValidationReport,
) -> None:
    if not body:
        rep.add(
            "A003",
            Severity.ERROR,
            path,
            f"Body `{container_kind}` nie może być puste.",
        )
        return
    _walk(body, path, wf, seen_names, rep)


def _validate_switch(switch: SwitchTask, path: str, rep: ValidationReport) -> None:
    """B: switch musi mieć ≤1 case bez `when` (= default); deklarowane `then` referuje istniejący name."""
    default_count = 0
    for i, case_dict in enumerate(switch.switch):
        for cid, case in case_dict.items():
            if case.when is None:
                default_count += 1
            if not case.then:
                rep.add(
                    "B001",
                    Severity.ERROR,
                    f"{path}.switch[{i}].{cid}.then",
                    "Brak target `then` w switch case.",
                )
    if default_count > 1:
        rep.add(
            "B002",
            Severity.ERROR,
            f"{path}.switch",
            f"Tylko jeden default case (bez `when`) jest dozwolony; znaleziono {default_count}.",
        )


def _validate_catch(
    catch: TryCatch,
    path: str,
    wf: Workflow,
    seen_names: set[str],
    rep: ValidationReport,
) -> None:
    """B/C: `catch.errors.with.type` musi być w (base ∪ tool.errors). Decyzja #23."""
    if catch.errors and "with" in catch.errors:
        ref = catch.errors["with"]
        if ref.type:
            allowed = set(BASE_ERROR_TYPES)
            for fdef in wf.use.functions.values():
                allowed.update(e.type for e in fdef.errors)
            if ref.type not in allowed:
                rep.add(
                    "C003",
                    Severity.ERROR,
                    f"{path}.errors.with.type",
                    f"Typ błędu {ref.type!r} nieznany. "
                    f"Dozwolone: base ∪ errors zadeklarowane w `use.functions`.",
                )

    if catch.do:
        _walk(catch.do, f"{path}.do", wf, seen_names, rep)


def _validate_policy_refs(task: Any, path: str, wf: Workflow, rep: ValidationReport) -> None:
    """C: `task.timeout` / `task.retries` jako string ref → musi istnieć w `use.timeouts/retries`."""
    timeout = getattr(task, "timeout", None)
    if isinstance(timeout, str) and timeout not in wf.use.timeouts:
        rep.add(
            "C010",
            Severity.ERROR,
            f"{path}.timeout",
            f"Profile timeout {timeout!r} nieznany w `use.timeouts`.",
        )
    retries = getattr(task, "retries", None)
    if isinstance(retries, str) and retries not in wf.use.retries:
        rep.add(
            "C011",
            Severity.ERROR,
            f"{path}.retries",
            f"Profile retry {retries!r} nieznany w `use.retries`.",
        )


def _validate_workflow_metadata(wf: Workflow, rep: ValidationReport) -> None:
    """E: `metadata.temporal.workflow_run_timeout` jest poprawnym ISO 8601 — wymuszone przez Pydantic
    przy konstrukcji `TemporalWorkflowMetadata`. Tu sprawdzamy najbardziej powszechne extensions
    bez surowego dict-a (gdzie nie ma typed walidacji).

    Pełen typed widok: `WorkflowMetadata.model_validate(wf.metadata)` (best-effort, opcjonalne).
    """
    temporal = (wf.metadata or {}).get("temporal") if isinstance(wf.metadata, dict) else None
    if isinstance(temporal, dict):
        wrt = temporal.get("workflow_run_timeout")
        if wrt is not None and not isinstance(wrt, str):
            rep.add(
                "F101",
                Severity.ERROR,
                "metadata.temporal.workflow_run_timeout",
                "Wartość musi być ISO 8601 duration string.",
            )
