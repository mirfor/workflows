"""Smoke testy generatora IR → Python (F3.C.9)."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from generator import GeneratorError, compute_source_hash, generate, update_manifest
from ir import (
    Backoff,
    BackoffExponential,
    CallTask,
    Document,
    RaiseTask,
    RetryLimit,
    RetryLimitAttempt,
    RetryPolicy,
    SetTask,
    SwitchTask,
    TimeoutPolicy,
    ToolFunction,
    TryTask,
    Use,
    WaitTask,
    Workflow,
)

FIXED_TS = datetime(2026, 5, 9, 16, 0, 0, tzinfo=UTC)


def _wf_minimal(do: list[dict] | None = None, *, with_tool: bool = True) -> Workflow:
    funcs = (
        {
            "send_email": ToolFunction(
                name="send_email",
                type="weaver_tool",
                module="activities.tools.gmail",
                operation="send_email",
                errors=[],
            )
        }
        if with_tool
        else {}
    )
    return Workflow(
        document=Document(dsl="1.0.0", namespace="demo", name="hello", version="1"),
        use=Use(
            functions=funcs,
            timeouts={"default_timeout": TimeoutPolicy(after="PT5M")},
            retries={
                "default_retry": RetryPolicy(
                    delay="PT1S",
                    backoff=Backoff(exponential=BackoffExponential(multiplier=2.0)),
                    limit=RetryLimit(attempt=RetryLimitAttempt(count=3)),
                )
            },
        ),
        do=do or [{"x": SetTask(set={"k": "v"})}],
    )


def test_simple_set_workflow_generates_valid_python() -> None:
    gen = generate(_wf_minimal(with_tool=False), generated_at=FIXED_TS)
    assert gen.file_name == "hello__v1.py"
    assert gen.class_name == "Hello_v1"
    assert gen.workflow_temporal_name == "hello"
    assert gen.source_hash and len(gen.source_hash) == 64
    # Walidacja syntaktyczna
    ast.parse(gen.source)
    # Header obecny
    assert "Generated from Blueprint hello v1" in gen.source
    assert "Source hash:" in gen.source
    assert "DO NOT EDIT" in gen.source


def test_call_task_emits_execute_activity_with_policies() -> None:
    wf = _wf_minimal(do=[
        {"send": CallTask(
            call="send_email",
            **{"with": {"to": "x@example.com"}},
            timeout="default_timeout",
            retries="default_retry",
        )}
    ])
    gen = generate(wf, generated_at=FIXED_TS)
    src = gen.source
    assert "workflow.execute_activity(" in src
    assert "activities.tools.gmail.send_email" in src
    assert "start_to_close_timeout=timedelta(minutes=5)" in src
    assert "RetryPolicy(" in src
    assert "backoff_coefficient=2.0" in src
    assert "maximum_attempts=3" in src


def test_wait_emits_workflow_sleep() -> None:
    gen = generate(_wf_minimal(do=[{"pause": WaitTask(wait="PT3S")}], with_tool=False),
                   generated_at=FIXED_TS)
    assert "await workflow.sleep(timedelta(seconds=3.0))" in gen.source


def test_raise_task_emits_application_error() -> None:
    gen = generate(_wf_minimal(do=[{"err": RaiseTask(**{"raise": {"error": "ValidationError"}})}],
                               with_tool=False),
                   generated_at=FIXED_TS)
    assert 'raise ApplicationError("ValidationError"' in gen.source


def test_switch_emits_if_elif_chain() -> None:
    wf = _wf_minimal(do=[
        {"decision": SwitchTask(switch=[
            {"vip": {"when": '.input.tier == "vip"', "then": "branch_a"}},
            {"default": {"then": "branch_b"}},
        ])}
    ], with_tool=False)
    gen = generate(wf, generated_at=FIXED_TS)
    assert "if _eval(" in gen.source
    assert "branch_a" in gen.source
    assert "branch_b" in gen.source


def test_try_emits_python_try_except() -> None:
    wf = _wf_minimal(do=[
        {"wrap": TryTask(
            **{"try": [{"inner_set": SetTask(set={"a": 1})}]},
            catch={"errors": {"with": {"type": "ValidationError"}},
                   "as": "e", "do": [{"recover": SetTask(set={"recovered": True})}]},
        )}
    ], with_tool=False)
    gen = generate(wf, generated_at=FIXED_TS)
    assert "try:" in gen.source
    assert "except ApplicationError as e:" in gen.source
    assert "'recovered': True" in gen.source.replace('"', "'")


def test_source_hash_is_idempotent() -> None:
    wf1 = _wf_minimal(with_tool=False)
    wf2 = _wf_minimal(with_tool=False)
    assert compute_source_hash(wf1) == compute_source_hash(wf2)


def test_generation_is_idempotent_for_same_ir() -> None:
    wf = _wf_minimal(with_tool=False)
    g1 = generate(wf, generated_at=FIXED_TS)
    g2 = generate(wf, generated_at=FIXED_TS)
    assert g1.source == g2.source
    assert g1.source_hash == g2.source_hash


def test_unsupported_task_emits_placeholder() -> None:
    from ir import ListenTask
    wf = _wf_minimal(do=[
        {"listen_evt": ListenTask(listen={"to": {"one": {"source": "x", "event_type": "y"}}})}
    ], with_tool=False)
    gen = generate(wf, generated_at=FIXED_TS)
    assert "not yet implemented in MVP generator" in gen.source


def test_unknown_function_in_call_raises() -> None:
    wf = _wf_minimal(do=[
        {"x": CallTask(call="missing_fn", timeout="default_timeout").model_dump(by_alias=True)}
    ])
    # Pydantic accepts strings; generator must raise
    wf2 = Workflow.model_validate(wf.model_dump(by_alias=True, exclude_none=True))
    # Function "missing_fn" nie istnieje w use.functions:
    with pytest.raises(GeneratorError, match="nieznana funkcja"):
        generate(wf2, generated_at=FIXED_TS)


def test_manifest_update(tmp_path: Path) -> None:
    gen = generate(_wf_minimal(with_tool=False), generated_at=FIXED_TS)
    mf_path = tmp_path / "generated" / "manifest.json"
    m = update_manifest(mf_path, gen, build_id="abc123", generated_at=FIXED_TS.isoformat())

    assert m["blueprints"]["hello"]["active_version"] == "1"
    assert m["blueprints"]["hello"]["versions"]["1"]["build_id"] == "abc123"
    assert m["blueprints"]["hello"]["versions"]["1"]["source_hash"] == gen.source_hash
    # Idempotency: re-call doesn't break
    m2 = update_manifest(mf_path, gen, build_id="abc123", generated_at=FIXED_TS.isoformat())
    assert json.dumps(m, sort_keys=True) == json.dumps(m2, sort_keys=True)
