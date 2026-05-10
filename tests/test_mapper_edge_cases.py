"""Edge cases mappera RF → IR — branch ownership, multi-catch, container nodes."""

from __future__ import annotations

import pytest

from ir import ForkTask, SwitchTask, TryTask
from mapper import MapperError, map_reactflow_to_cncfsw


def _meta(extra: dict | None = None) -> dict:
    base = {
        "namespace": "demo",
        "name": "edge_test",
        "version": "1",
        "use": {
            "functions": {
                "fn": {"name": "fn", "type": "weaver_tool", "module": "m", "operation": "o"},
            },
            "timeouts": {"default_timeout": {"after": "PT1M"}},
        },
    }
    if extra:
        base.update(extra)
    return base


# ---------- Switch branch ownership --------------------------------------------


def test_switch_owned_branch_nodes_removed_from_top_level() -> None:
    """Nodes osiągalne tylko z konkretnego switch case → są w case.do, NIE w top-level."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "sw", "type": "switch", "data": {
                "cases": [{"id": "vip", "when": ".tier == \"vip\""}],
            }},
            {"id": "vip_path", "type": "set", "data": {"assignments": {"x": 1}}},
            {"id": "vip_emit", "type": "emit", "data": {"event": {"k": "vip"}}},
            {"id": "default_path", "type": "set", "data": {"assignments": {"y": 1}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "sw"},
            {"id": "e2", "source": "sw", "target": "vip_path", "sourceHandle": "case_vip"},
            {"id": "e3", "source": "vip_path", "target": "vip_emit"},
            {"id": "e4", "source": "sw", "target": "default_path", "sourceHandle": "default"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    top_level_names = {list(t.keys())[0] for t in wf.do}
    # Top-level: tylko trigger jest poza do[]; switch zostaje, ale branch nodes NIE w top-level
    assert "sw" in top_level_names
    assert "vip_path" not in top_level_names
    assert "vip_emit" not in top_level_names
    assert "default_path" not in top_level_names


def test_switch_case_do_contains_branch_sequence() -> None:
    """Case.do zawiera topologiczną sekwencję owned nodes."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "sw", "type": "switch", "data": {
                "cases": [{"id": "a", "when": "true"}],
            }},
            {"id": "step1", "type": "set", "data": {"assignments": {"a": 1}}},
            {"id": "step2", "type": "set", "data": {"assignments": {"b": 2}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "sw"},
            {"id": "e2", "source": "sw", "target": "step1", "sourceHandle": "case_a"},
            {"id": "e3", "source": "step1", "target": "step2"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    sw = wf.do[0]["sw"]
    assert isinstance(sw, SwitchTask)
    case_a = sw.switch[0]["a"]
    assert case_a.do is not None
    body_names = [list(t.keys())[0] for t in case_a.do]
    assert body_names == ["step1", "step2"]


def test_switch_with_only_default_no_case() -> None:
    """Switch tylko z default (sourceHandle='default') — brak deklarowanych cases."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "sw", "type": "switch", "data": {"cases": []}},
            {"id": "fallback", "type": "set", "data": {"assignments": {"x": 1}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "sw"},
            {"id": "e2", "source": "sw", "target": "fallback", "sourceHandle": "default"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    sw = wf.do[0]["sw"]
    assert isinstance(sw, SwitchTask)
    case_keys = [list(c.keys())[0] for c in sw.switch]
    assert "default" in case_keys


# ---------- Fork branch ownership ----------------------------------------------


def test_fork_branches_owned_nodes_removed_from_top_level() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "fork", "type": "fork", "data": {"compete": False}},
            {"id": "br_a", "type": "set", "data": {"assignments": {"a": 1}}},
            {"id": "br_b", "type": "set", "data": {"assignments": {"b": 2}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "fork"},
            {"id": "e2", "source": "fork", "target": "br_a", "sourceHandle": "branch_0"},
            {"id": "e3", "source": "fork", "target": "br_b", "sourceHandle": "branch_1"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    top_names = {list(t.keys())[0] for t in wf.do}
    assert "fork" in top_names
    assert "br_a" not in top_names
    assert "br_b" not in top_names


def test_fork_compete_true_propagates() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "fork", "type": "fork", "data": {"compete": True}},
            {"id": "br_a", "type": "set", "data": {"assignments": {"a": 1}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "fork"},
            {"id": "e2", "source": "fork", "target": "br_a", "sourceHandle": "branch_0"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    fork = wf.do[0]["fork"]
    assert isinstance(fork, ForkTask)
    assert fork.fork.compete is True


# ---------- Try / multi-catch --------------------------------------------------


def test_try_with_multi_catch_compiles_to_switch_in_catch_do() -> None:
    """Multi-catch UI (>1 catch block) → mapper kompiluje do single catch z switch w catch.do."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "wrap", "type": "try", "data": {
                "catches": [
                    {"errorType": "ValidationError", "as": "err", "do": ["recover_v"]},
                    {"errorType": "AuthError", "as": "err", "do": ["recover_a"]},
                ],
            }},
            {"id": "risky", "type": "set", "parentNode": "wrap",
             "data": {"assignments": {"x": 1}}},
            {"id": "recover_v", "type": "set",
             "data": {"assignments": {"recovered": "validation"}}},
            {"id": "recover_a", "type": "set",
             "data": {"assignments": {"recovered": "auth"}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "wrap"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    wrap = wf.do[0]["wrap"]
    assert isinstance(wrap, TryTask)
    # Multi-catch → single CNCF SW catch with switch task w catch.do
    assert wrap.catch.do is not None
    # Pierwszy task w catch.do to switch (z synthetic name)
    first_handler = wrap.catch.do[0]
    handler_task = list(first_handler.values())[0]
    assert isinstance(handler_task, SwitchTask) or "switch" in str(type(handler_task)).lower()


def test_try_container_body_is_built_from_parent_node() -> None:
    """`try` ma body z nodes z `parentNode == try_id` (container node)."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "wrap", "type": "try", "data": {
                "catches": [{"errorType": "ValidationError", "do": ["log"]}],
            }},
            {"id": "inner1", "type": "set", "parentNode": "wrap",
             "data": {"assignments": {"a": 1}}},
            {"id": "inner2", "type": "set", "parentNode": "wrap",
             "data": {"assignments": {"b": 2}}},
            {"id": "log", "type": "set", "data": {"assignments": {"logged": True}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "wrap"},
        ],
    }
    wf = map_reactflow_to_cncfsw(rf)
    wrap = wf.do[0]["wrap"]
    assert isinstance(wrap, TryTask)
    body_names = [list(t.keys())[0] for t in wrap.try_]
    assert "inner1" in body_names
    assert "inner2" in body_names


# ---------- Preconditions / errors ---------------------------------------------


def test_unknown_parent_node_rejected() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "n1", "type": "set", "parentNode": "ghost",
             "data": {"assignments": {}}},
        ],
        "edges": [],
    }
    with pytest.raises(MapperError, match="nieznany parentNode"):
        map_reactflow_to_cncfsw(rf)


def test_parent_node_must_be_container_type() -> None:
    """parentNode wskazujący na non-container (np. switch) → MapperError."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "sw", "type": "switch", "data": {"cases": []}},
            {"id": "n1", "type": "set", "parentNode": "sw",
             "data": {"assignments": {}}},
        ],
        "edges": [],
    }
    with pytest.raises(MapperError, match="nie jest container"):
        map_reactflow_to_cncfsw(rf)


def test_trigger_with_incoming_edges_rejected() -> None:
    """Trigger node MUSI mieć incoming==0 (decyzja #10)."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "n1", "type": "set", "data": {"assignments": {}}},
            {"id": "trg", "type": "manual_trigger", "data": {}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "trg"}],
    }
    with pytest.raises(MapperError, match="incoming edges"):
        map_reactflow_to_cncfsw(rf)


def test_cycle_in_top_level_scope_rejected() -> None:
    """Cykl poza container (for/try) → MapperError z `topological`."""
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "a", "type": "set", "data": {"assignments": {}}},
            {"id": "b", "type": "set", "data": {"assignments": {}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
            {"id": "e3", "source": "b", "target": "a"},  # cycle
        ],
    }
    with pytest.raises(MapperError, match="ykl|niedostępne"):
        map_reactflow_to_cncfsw(rf)


# ---------- Trigger types ------------------------------------------------------


def test_schedule_trigger_persisted_with_cron() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "schedule_trigger",
             "data": {"cron": "0 9 * * 1-5", "timezone": "Europe/Warsaw"}},
            {"id": "n1", "type": "set", "data": {"assignments": {}}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "n1"}],
    }
    wf = map_reactflow_to_cncfsw(rf)
    trg = wf.metadata["weaver"]["trigger"]
    assert trg["type"] == "schedule_trigger"
    assert trg["cron"] == "0 9 * * 1-5"
    assert trg["timezone"] == "Europe/Warsaw"


def test_event_trigger_with_filter() -> None:
    rf = {
        "meta": _meta(),
        "nodes": [
            {"id": "trg", "type": "event_trigger",
             "data": {"source": "stripe", "eventType": "payment.succeeded",
                      "filter": ".amount > 1000"}},
            {"id": "n1", "type": "set", "data": {"assignments": {}}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "n1"}],
    }
    wf = map_reactflow_to_cncfsw(rf)
    trg = wf.metadata["weaver"]["trigger"]
    assert trg["type"] == "event_trigger"
    assert trg["source"] == "stripe"
    assert trg["filter"] == ".amount > 1000"


# ---------- Use registry passthrough ------------------------------------------


def test_meta_use_passes_through_to_workflow() -> None:
    """meta.use → workflow.use (functions, retries, timeouts) bez utraty pól."""
    use_data = {
        "functions": {
            "f": {"name": "f", "type": "weaver_tool", "module": "m", "operation": "o",
                  "errors": [{"type": "ValidationError", "is_base": True, "retryable": False}]},
        },
        "retries": {
            "r1": {"delay": "PT2S",
                   "backoff": {"exponential": {"multiplier": 1.5}},
                   "limit": {"attempt": {"count": 5}}},
        },
        "timeouts": {
            "t1": {"after": "PT3M",
                   "metadata": {"temporal": {"heartbeat": "PT15S"}}},
        },
    }
    rf = {
        "meta": {"namespace": "demo", "name": "p", "version": "1", "use": use_data},
        "nodes": [{"id": "trg", "type": "manual_trigger", "data": {}}],
        "edges": [],
    }
    wf = map_reactflow_to_cncfsw(rf)
    assert "f" in wf.use.functions
    assert wf.use.retries["r1"].delay == "PT2S"
    assert wf.use.timeouts["t1"].after == "PT3M"
    assert wf.use.timeouts["t1"].metadata == {"temporal": {"heartbeat": "PT15S"}}
