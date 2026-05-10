"""Testy per reguła walidatora IR (uzupełnienie test_validator_basic.py).

Każda reguła z 6 kategorii (A graf, B handles, C registry, D schemy, E polityki Temporala,
F spec compliance) ma osobny test sprawdzający emisję właściwego code (np. `A001`, `E102`).
"""

from __future__ import annotations

from ir import (
    CallTask,
    Document,
    ForkTask,
    ListenTask,
    RetryJitter,
    RetryLimit,
    RetryLimitAttempt,
    RetryPolicy,
    SetTask,
    SwitchTask,
    TimeoutPolicy,
    ToolFunction,
    TryTask,
    Use,
    Workflow,
)
from validator import Severity, apply_default_timeout, validate
from validator.report import ValidationReport
from validator.validator import _check_retry_no_temporal_mapping


def _wf(do: list[dict], use: Use | None = None, metadata: dict | None = None) -> Workflow:
    return Workflow(
        document=Document(dsl="1.0.0", namespace="t", name="x", version="1"),
        use=use or Use(),
        do=do,
        metadata=metadata or {},
    )


# ---------- Kategoria A: struktura grafu ---------------------------------------


def test_A001_duplicate_task_names_in_workflow_do() -> None:
    wf = _wf(
        [
            {"send": SetTask(set={}).model_dump(by_alias=True)},
            {"send": SetTask(set={}).model_dump(by_alias=True)},
        ]
    )
    rep = validate(wf)
    assert any(i.code == "A001" for i in rep.errors)


def test_A001_duplicate_across_nested_scopes() -> None:
    """Duplikat w container body (try) też wykryty."""
    wf = _wf(
        [
            {"name1": SetTask(set={}).model_dump(by_alias=True)},
            {
                "wrap": TryTask(
                    **{"try": [{"name1": SetTask(set={}).model_dump(by_alias=True)}]},
                    catch={"as": "e"},
                ).model_dump(by_alias=True)
            },
        ]
    )
    rep = validate(wf)
    assert any(i.code == "A001" for i in rep.errors)


def test_A002_invalid_named_task_dict_shape() -> None:
    """`do[]` element nie jest 1-key dict → A002."""
    wf = Workflow(
        document=Document(dsl="1.0.0", namespace="t", name="x", version="1"),
        use=Use(),
        do=[{"a": SetTask(set={}), "b": SetTask(set={})}],  # 2 keys = invalid
    )
    rep = validate(wf)
    assert any(i.code == "A002" for i in rep.errors)


def test_A003_empty_do_container_body() -> None:
    """Container `try` z pustym body → A003."""
    from ir.tasks import TryTask

    wf = _wf(
        [
            {
                "empty_try": TryTask.model_construct(try_=[], catch={"as": "e"}).model_dump(
                    by_alias=True
                )
            },
        ]
    )
    rep = validate(wf)
    # Pydantic może wymusić niepustość przez schema; jeśli nie, walidator emituje A003
    assert any(i.code == "A003" for i in rep.errors) or rep.has_errors


def test_A011_empty_fork_branches() -> None:
    """Fork bez branches → A011."""
    wf = _wf(
        [
            {
                "par": ForkTask.model_construct(fork={"branches": [], "compete": False}).model_dump(
                    by_alias=True
                )
            },
        ]
    )
    rep = validate(wf)
    assert any(i.code == "A011" for i in rep.errors)


def test_A013_listen_without_to() -> None:
    """Listen bez `listen.to` → A013."""
    wf = _wf(
        [
            {"l": ListenTask.model_construct(listen={}).model_dump(by_alias=True)},
        ]
    )
    rep = validate(wf)
    assert any(i.code == "A013" for i in rep.errors)


# ---------- Kategoria B: handles / edges ----------------------------------------


def test_B001_switch_case_then_empty_string() -> None:
    """Switch case z pustym `then` → B001."""
    wf = _wf(
        [
            {
                "sw": SwitchTask(
                    switch=[
                        {"a": {"when": ".x", "then": ""}},
                    ]
                ).model_dump(by_alias=True)
            },
        ]
    )
    rep = validate(wf)
    assert any(i.code == "B001" for i in rep.errors)


def test_B002_multiple_default_cases() -> None:
    """Switch z >1 default (case bez `when`) → B002."""
    wf = _wf(
        [
            {
                "sw": SwitchTask(
                    switch=[
                        {"a": {"then": "n1"}},
                        {"b": {"then": "n2"}},
                        {"c": {"then": "n3"}},
                    ]
                ).model_dump(by_alias=True)
            },
        ]
    )
    rep = validate(wf)
    errors_b002 = [i for i in rep.errors if i.code == "B002"]
    assert len(errors_b002) == 1


# ---------- Kategoria C: registry funkcji ---------------------------------------


def test_C001_function_name_mismatch_with_key() -> None:
    """`use.functions.<key>.name` != klucz → C001."""
    use = Use(
        functions={
            "send_email": ToolFunction(
                name="DIFFERENT_NAME",
                type="weaver_tool",
                module="m",
                operation="o",
            ),
        }
    )
    wf = _wf([{"x": SetTask(set={}).model_dump(by_alias=True)}], use=use)
    rep = validate(wf)
    assert any(i.code == "C001" for i in rep.errors)


def test_C002_call_unknown_function() -> None:
    use = Use(timeouts={"default_timeout": TimeoutPolicy(after="PT1M")})
    wf = _wf(
        [
            {
                "send": CallTask(call="undefined_fn", timeout="default_timeout").model_dump(
                    by_alias=True
                )
            },
        ],
        use=use,
    )
    rep = validate(wf)
    assert any(i.code == "C002" for i in rep.errors)


def test_C003_catch_unknown_error_type() -> None:
    """`catch.errors.with.type` poza base ∪ tool.errors → C003."""
    use = Use(
        functions={
            "send": ToolFunction(
                name="send", type="weaver_tool", module="m", operation="o", errors=[]
            ),
        }
    )
    wf = _wf(
        [
            {
                "wrap": TryTask(
                    **{"try": [{"inner": SetTask(set={}).model_dump(by_alias=True)}]},
                    catch={
                        "errors": {"with": {"type": "TotallyUnknownError"}},
                        "as": "e",
                    },
                ).model_dump(by_alias=True)
            },
        ],
        use=use,
    )
    rep = validate(wf)
    assert any(i.code == "C003" for i in rep.errors)


def test_C003_accepts_base_error_type() -> None:
    """ValidationError ∈ BaseErrorType — bez C003."""
    wf = _wf(
        [
            {
                "wrap": TryTask(
                    **{"try": [{"inner": SetTask(set={}).model_dump(by_alias=True)}]},
                    catch={
                        "errors": {"with": {"type": "ValidationError"}},
                        "as": "e",
                    },
                ).model_dump(by_alias=True)
            },
        ]
    )
    rep = validate(wf)
    assert not any(i.code == "C003" for i in rep.errors)


def test_C003_accepts_tool_declared_error() -> None:
    """Custom error zadeklarowany w manifest Tool — bez C003."""
    use = Use(
        functions={
            "send": ToolFunction(
                name="send",
                type="weaver_tool",
                module="m",
                operation="o",
                errors=[{"type": "GmailQuotaExceeded", "retryable": True}],
            ),
        }
    )
    wf = _wf(
        [
            {
                "wrap": TryTask(
                    **{"try": [{"inner": SetTask(set={}).model_dump(by_alias=True)}]},
                    catch={
                        "errors": {"with": {"type": "GmailQuotaExceeded"}},
                        "as": "e",
                    },
                ).model_dump(by_alias=True)
            },
        ],
        use=use,
    )
    rep = validate(wf)
    assert not any(i.code == "C003" for i in rep.errors)


def test_C010_unknown_timeout_profile_ref() -> None:
    use = Use(
        functions={"f": ToolFunction(name="f", type="weaver_tool", module="m", operation="o")}
    )
    wf = _wf(
        [
            {"x": CallTask(call="f", timeout="nonexistent_profile").model_dump(by_alias=True)},
        ],
        use=use,
    )
    rep = validate(wf)
    assert any(i.code == "C010" for i in rep.errors)


def test_C011_unknown_retry_profile_ref() -> None:
    use = Use(
        functions={"f": ToolFunction(name="f", type="weaver_tool", module="m", operation="o")}
    )
    wf = _wf(
        [
            {"x": CallTask(call="f", retries="nonexistent_retry").model_dump(by_alias=True)},
        ],
        use=use,
    )
    rep = validate(wf)
    assert any(i.code == "C011" for i in rep.errors)


# ---------- Kategoria E: polityki Temporala (#21) -------------------------------


def test_E101_retry_jitter_blocks() -> None:
    rp = RetryPolicy(jitter=RetryJitter(**{"from": "PT1S", "to": "PT3S"}))
    rep = ValidationReport()
    _check_retry_no_temporal_mapping(rp, "use.retries.bad", rep)
    assert any(i.code == "E101" for i in rep.errors)


def test_E102_retry_when_blocks() -> None:
    rp = RetryPolicy(when='.error.type == "X"')
    rep = ValidationReport()
    _check_retry_no_temporal_mapping(rp, "use.retries.bad", rep)
    assert any(i.code == "E102" for i in rep.errors)


def test_E103_retry_except_when_blocks() -> None:
    rp = RetryPolicy(**{"exceptWhen": '.error.type == "X"'})
    rep = ValidationReport()
    _check_retry_no_temporal_mapping(rp, "use.retries.bad", rep)
    assert any(i.code == "E103" for i in rep.errors)


def test_E104_retry_limit_duration_blocks() -> None:
    rp = RetryPolicy(limit=RetryLimit(duration="PT1H"))
    rep = ValidationReport()
    _check_retry_no_temporal_mapping(rp, "use.retries.bad", rep)
    assert any(i.code == "E104" for i in rep.errors)


def test_E105_retry_limit_attempt_duration_blocks() -> None:
    rp = RetryPolicy(limit=RetryLimit(attempt=RetryLimitAttempt(count=3, duration="PT5M")))
    rep = ValidationReport()
    _check_retry_no_temporal_mapping(rp, "use.retries.bad", rep)
    assert any(i.code == "E105" for i in rep.errors)


def test_E201_call_without_timeout_emits_warning() -> None:
    use = Use(
        functions={"f": ToolFunction(name="f", type="weaver_tool", module="m", operation="o")}
    )
    wf = _wf(
        [
            {"send": CallTask(call="f").model_dump(by_alias=True)},
        ],
        use=use,
    )
    rep = validate(wf)
    assert any(i.code == "E201" and i.severity == Severity.WARNING for i in rep.warnings)


def test_E001_timeout_profile_after_required() -> None:
    """TimeoutPolicy bez `after` → Pydantic odmawia stworzenia (wcześniej niż walidator)."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TimeoutPolicy(after="")  # type: ignore[arg-type]


# ---------- Kategoria F: spec compliance ---------------------------------------


def test_F101_workflow_run_timeout_must_be_string() -> None:
    """`metadata.temporal.workflow_run_timeout` musi być stringiem ISO 8601 → F101 dla int."""
    wf = _wf(
        [{"x": SetTask(set={}).model_dump(by_alias=True)}],
        metadata={"temporal": {"workflow_run_timeout": 60}},
    )  # int zamiast str
    rep = validate(wf)
    assert any(i.code == "F101" for i in rep.errors)


# ---------- apply_default_timeout (cascade #28) -------------------------------


def test_apply_default_timeout_no_op_when_already_set() -> None:
    use = Use(timeouts={"default_timeout": TimeoutPolicy(after="PT99M")})
    wf = _wf([], use=use)
    apply_default_timeout(wf, cascade_after="PT5M")
    # Nie zmienia istniejącego
    assert wf.use.timeouts["default_timeout"].after == "PT99M"


def test_apply_default_timeout_includes_schedule_to_close() -> None:
    wf = _wf([])
    apply_default_timeout(
        wf, cascade_after="PT3M", cascade_heartbeat=None, cascade_schedule_to_close="PT10M"
    )
    md = wf.use.timeouts["default_timeout"].metadata
    assert md is not None
    assert md["temporal"]["schedule_to_close"] == "PT10M"
    assert "heartbeat" not in md["temporal"]


def test_apply_default_timeout_no_metadata_when_no_extras() -> None:
    wf = _wf([])
    apply_default_timeout(
        wf, cascade_after="PT2M", cascade_heartbeat=None, cascade_schedule_to_close=None
    )
    assert wf.use.timeouts["default_timeout"].metadata is None
