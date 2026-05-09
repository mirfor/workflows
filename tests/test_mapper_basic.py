"""Smoke testy dla mapper RF → CNCF SW IR (F3.A.4).

Golden file pattern: dla każdego scenariusza jeden RF JSON in i sprawdzenie kluczowych
pól wynikowego Workflow. Pełny golden-file repo (RF JSON ↔ IR JSON) wraz z replay
testami dochodzi w fazach F3.C/F5.
"""

from __future__ import annotations

import pytest

from ir import CallTask, SwitchTask, TryTask
from mapper import MapperError, map_reactflow_to_cncfsw


def _meta(extra: dict | None = None) -> dict:
    base = {
        "namespace": "demo",
        "name": "test_wf",
        "version": "1",
        "use": {
            "functions": {
                "send_email": {
                    "name": "send_email",
                    "type": "weaver_tool",
                    "module": "activities.tools.gmail",
                    "operation": "send_email",
                    "errors": [],
                }
            },
            "retries": {
                "default_retry": {
                    "delay": "PT1S",
                    "backoff": {"exponential": {"multiplier": 2.0}},
                    "limit": {"attempt": {"count": 3}},
                }
            },
            "timeouts": {"default_timeout": {"after": "PT5M"}},
        },
    }
    if extra:
        base.update(extra)
    return base


def test_linear_sequence_with_manual_trigger() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "data": {}},
            {"id": "n1", "type": "call", "data": {
                "function": "send_email",
                "with": {"to": ".input.email"},
                "timeout": "default_timeout",
                "retries": "default_retry",
            }},
            {"id": "n2", "type": "wait", "data": {"duration": "PT5S"}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "n1"},
            {"id": "e2", "source": "n1", "target": "n2"},
        ],
    }

    wf = map_reactflow_to_cncfsw(rf)

    assert wf.document.name == "test_wf"
    assert wf.document.version == "1"
    assert [list(t.keys())[0] for t in wf.do] == ["n1", "n2"]
    assert isinstance(wf.do[0]["n1"], CallTask)
    assert wf.do[0]["n1"].call == "send_email"
    trigger = wf.metadata["weaver"]["trigger"]
    assert trigger["type"] == "manual_trigger"


def test_trigger_persists_correctly() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trigger", "type": "webhook_trigger",
             "data": {"path": "/hooks/welcome", "method": "POST"}},
            {"id": "n1", "type": "set", "data": {"assignments": {"foo": "bar"}}},
        ],
        "edges": [{"id": "e1", "source": "trigger", "target": "n1"}],
    }
    wf = map_reactflow_to_cncfsw(rf)
    assert wf.metadata["weaver"]["trigger"]["type"] == "webhook_trigger"
    assert wf.metadata["weaver"]["trigger"]["path"] == "/hooks/welcome"


def test_switch_with_two_cases_and_default() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "data": {}},
            {"id": "decision", "type": "switch", "data": {
                "cases": [
                    {"id": "vip", "when": ".input.tier == \"vip\""},
                    {"id": "regular", "when": ".input.tier == \"regular\""},
                ]
            }},
            {"id": "vip_path", "type": "set", "data": {"assignments": {"path": "vip"}}},
            {"id": "regular_path", "type": "set", "data": {"assignments": {"path": "regular"}}},
            {"id": "default_path", "type": "set", "data": {"assignments": {"path": "default"}}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "decision"},
            {"id": "e2", "source": "decision", "target": "vip_path", "sourceHandle": "case_vip"},
            {"id": "e3", "source": "decision", "target": "regular_path", "sourceHandle": "case_regular"},
            {"id": "e4", "source": "decision", "target": "default_path", "sourceHandle": "default"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    decision = wf.do[0]["decision"]
    assert isinstance(decision, SwitchTask)
    case_ids = [list(c.keys())[0] for c in decision.switch]
    assert "vip" in case_ids
    assert "regular" in case_ids
    assert "default" in case_ids


def test_try_with_single_catch_block() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "data": {}},
            {"id": "wrap", "type": "try", "data": {
                "catches": [
                    {"errorType": "ValidationError", "as": "err",
                     "do": ["log_err"]}
                ]
            }},
            {"id": "risky_call", "type": "call",
             "parentNode": "wrap",
             "data": {"function": "send_email"}},
            {"id": "log_err", "type": "set",
             "data": {"assignments": {"logged": True}}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "wrap"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    wrap = wf.do[0]["wrap"]
    assert isinstance(wrap, TryTask)
    assert len(wrap.try_) == 1
    assert wrap.catch.errors is not None
    assert wrap.catch.errors["with"].type == "ValidationError"


def test_multiple_triggers_rejected() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "t1", "type": "manual_trigger", "data": {}},
            {"id": "t2", "type": "manual_trigger", "data": {}},
        ],
        "edges": [],
    }
    with pytest.raises(MapperError, match="Więcej niż jeden trigger"):
        map_reactflow_to_cncfsw(rf)


def test_missing_meta_name_rejected() -> None:
    rf = {
        "meta": {"namespace": "demo"},
        "nodes": [],
        "edges": [],
    }
    with pytest.raises(MapperError, match="meta.name"):
        map_reactflow_to_cncfsw(rf)


def test_unknown_edge_target_rejected() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [{"id": "n1", "type": "set", "data": {"assignments": {}}}],
        "edges": [{"id": "e1", "source": "n1", "target": "nonexistent"}],
    }
    with pytest.raises(MapperError, match="nieznany target"):
        map_reactflow_to_cncfsw(rf)


def test_round_trip_via_pydantic_dump() -> None:
    """Mapper -> dump CNCF SW JSON powinien się sparsować z powrotem do Workflow."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "data": {}},
            {"id": "n1", "type": "call",
             "data": {"function": "send_email", "with": {"to": "x@example.com"}}},
        ],
        "edges": [{"id": "e1", "source": "trigger", "target": "n1"}],
    }
    wf = map_reactflow_to_cncfsw(rf)
    dumped = wf.model_dump(by_alias=True, exclude_none=True)

    from ir import Workflow

    re_parsed = Workflow.model_validate(dumped)
    assert re_parsed.document.name == wf.document.name
    assert len(re_parsed.do) == len(wf.do)
