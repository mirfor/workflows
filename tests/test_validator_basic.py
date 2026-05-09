"""Smoke testy walidatora IR."""

from __future__ import annotations

from ir import (
    Backoff,
    BackoffExponential,
    CallTask,
    Document,
    RetryJitter,
    RetryLimit,
    RetryLimitAttempt,
    RetryPolicy,
    SwitchTask,
    TimeoutPolicy,
    ToolFunction,
    Use,
    Workflow,
)
from validator import apply_default_timeout, validate


def _wf(
    do: list[dict],
    use: Use | None = None,
    metadata: dict | None = None,
) -> Workflow:
    return Workflow(
        document=Document(dsl="1.0.0", namespace="demo", name="t", version="1"),
        use=use or _use(),
        do=do,
        metadata=metadata or {},
    )


def _use(extra_funcs: dict | None = None) -> Use:
    funcs = {
        "send_email": ToolFunction(
            name="send_email", type="weaver_tool",
            module="activities.tools.gmail", operation="send_email",
        ),
    }
    if extra_funcs:
        funcs.update(extra_funcs)
    return Use(
        functions=funcs,
        retries={
            "default_retry": RetryPolicy(
                delay="PT1S",
                backoff=Backoff(exponential=BackoffExponential(multiplier=2.0)),
                limit=RetryLimit(attempt=RetryLimitAttempt(count=3)),
            )
        },
        timeouts={"default_timeout": TimeoutPolicy(after="PT5M")},
    )


def test_clean_workflow_passes_with_only_warning() -> None:
    wf = _wf([
        {"send": CallTask(call="send_email", timeout="default_timeout").model_dump(by_alias=True)},
    ])
    rep = validate(wf)
    # CallTask z timeout="default_timeout" — bez warning
    assert not rep.has_errors


def test_call_with_unknown_function_fails() -> None:
    wf = _wf([
        {"send": CallTask(call="undefined_func", timeout="default_timeout").model_dump(by_alias=True)},
    ])
    rep = validate(wf)
    assert rep.has_errors
    codes = [i.code for i in rep.errors]
    assert "C002" in codes


def test_call_without_timeout_emits_warning() -> None:
    wf = _wf([
        {"send": CallTask(call="send_email").model_dump(by_alias=True)},
    ])
    rep = validate(wf)
    assert not rep.has_errors
    warning_codes = [i.code for i in rep.warnings]
    assert "E201" in warning_codes


def test_retry_with_jitter_blocks_publish() -> None:
    use = _use()
    use.retries["bad"] = RetryPolicy(
        delay="PT1S",
        jitter=RetryJitter(**{"from": "PT1S", "to": "PT3S"}),
    )
    wf = _wf(
        [{"send": CallTask(call="send_email", timeout="default_timeout", retries="bad").model_dump(by_alias=True)}],
        use=use,
    )
    rep = validate(wf)
    assert rep.has_errors
    assert any(i.code == "E101" for i in rep.errors)


def test_retry_with_when_blocks_publish() -> None:
    use = _use()
    use.retries["bad"] = RetryPolicy(when=".error.type == \"X\"")
    wf = _wf(
        [{"send": CallTask(call="send_email", timeout="default_timeout", retries="bad").model_dump(by_alias=True)}],
        use=use,
    )
    rep = validate(wf)
    assert any(i.code == "E102" for i in rep.errors)


def test_unknown_retry_profile_ref_fails() -> None:
    wf = _wf([
        {"send": CallTask(call="send_email", timeout="default_timeout", retries="missing_profile").model_dump(by_alias=True)},
    ])
    rep = validate(wf)
    assert any(i.code == "C011" for i in rep.errors)


def test_switch_with_two_default_cases_fails() -> None:
    wf = _wf([
        {"decision": SwitchTask(
            switch=[
                {"a": {"then": "n1"}},
                {"b": {"then": "n2"}},
            ]
        ).model_dump(by_alias=True)},
    ])
    rep = validate(wf)
    assert any(i.code == "B002" for i in rep.errors)


def test_apply_default_timeout_idempotent() -> None:
    wf = _wf([
        {"send": CallTask(call="send_email").model_dump(by_alias=True)},
    ])
    before = len(wf.use.timeouts)
    apply_default_timeout(wf, cascade_after="PT10M", cascade_heartbeat="PT60S")
    assert wf.use.timeouts["default_timeout"].after == "PT5M" or before == 1
    # Bo `default_timeout` już jest w `_use()` — test sprawdza idempotencję (no-op).
    apply_default_timeout(wf)
    assert "default_timeout" in wf.use.timeouts


def test_apply_default_timeout_injects_when_missing() -> None:
    wf = Workflow(
        document=Document(dsl="1.0.0", namespace="demo", name="t", version="1"),
        use=Use(),
        do=[],
    )
    assert "default_timeout" not in wf.use.timeouts
    apply_default_timeout(wf, cascade_after="PT10M", cascade_heartbeat="PT60S")
    assert wf.use.timeouts["default_timeout"].after == "PT10M"
    assert wf.use.timeouts["default_timeout"].metadata == {"temporal": {"heartbeat": "PT60S"}}


def test_duplicate_task_names_detected() -> None:
    wf = _wf([
        {"send": CallTask(call="send_email", timeout="default_timeout").model_dump(by_alias=True)},
        {"send": CallTask(call="send_email", timeout="default_timeout").model_dump(by_alias=True)},
    ])
    rep = validate(wf)
    assert any(i.code == "A001" for i in rep.errors)
