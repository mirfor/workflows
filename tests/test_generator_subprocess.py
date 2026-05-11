"""Tests for core.subprocess code generation (P7.2).

Verifies that RunTask with run.workflow generates:
- start_child_workflow call (both modes)
- record_child_engagement activity call
- execute_child_workflow result await (wait mode)
- fire-and-forget result dict (fire_and_forget mode)
"""

from __future__ import annotations

from generator import generate
from ir import (
    Document,
    ToolFunction,
    Use,
    Workflow,
)


def _wf_with_subprocess(mode: str = "wait", agent_name: str = "support") -> Workflow:
    return Workflow(
        document=Document(dsl="1.0.0", namespace="demo", name="parent_agent", version="1"),
        use=Use(),
        do=[
            {
                "delegate": {
                    "run": {
                        "workflow": {
                            "name": agent_name,
                            "mode": mode,
                        }
                    }
                }
            }
        ],
        metadata={},
    )


def _generate_source(mode: str = "wait", agent_name: str = "support") -> str:
    wf = _wf_with_subprocess(mode=mode, agent_name=agent_name)
    result = generate(wf, tenant_id="test-tenant")
    return result.source


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def test_subprocess_imports_record_child_engagement() -> None:
    src = _generate_source()
    assert "from activities.tools.child_engagement import record_child_engagement" in src


def test_no_subprocess_does_not_import_record_child_engagement() -> None:
    wf = Workflow(
        document=Document(dsl="1.0.0", namespace="demo", name="plain", version="1"),
        use=Use(
            functions={
                "log": ToolFunction(
                    name="log",
                    type="weaver_tool",
                    module="tools.log_message",
                    operation="log_message",
                )
            },
            timeouts={"default_timeout": {"after": "PT5M"}},
        ),
        do=[{"log_step": {"call": "log", "with": {}}}],
        metadata={},
    )
    result = generate(wf, tenant_id="test-tenant")
    assert "record_child_engagement" not in result.source


# ---------------------------------------------------------------------------
# Wait mode
# ---------------------------------------------------------------------------


def test_subprocess_wait_calls_start_child_workflow() -> None:
    src = _generate_source(mode="wait")
    assert "workflow.start_child_workflow" in src
    assert "support" in src


def test_subprocess_wait_calls_record_child_engagement_activity() -> None:
    src = _generate_source(mode="wait")
    assert "record_child_engagement" in src
    assert "workflow.info().namespace" in src
    assert "workflow.info().workflow_id" in src
    assert "agent_id" in src


def test_subprocess_wait_awaits_result() -> None:
    src = _generate_source(mode="wait")
    assert ".result()" in src
    assert 'steps_output["delegate"]' in src


def test_subprocess_wait_uses_dynamic_child_wf_id() -> None:
    src = _generate_source(mode="wait")
    assert "delegate-child-" in src
    assert "workflow.info().workflow_id" in src


# ---------------------------------------------------------------------------
# Fire-and-forget mode
# ---------------------------------------------------------------------------


def test_subprocess_fire_and_forget_calls_start_child_workflow() -> None:
    src = _generate_source(mode="fire_and_forget")
    assert "workflow.start_child_workflow" in src


def test_subprocess_fire_and_forget_does_not_await_result() -> None:
    src = _generate_source(mode="fire_and_forget")
    assert ".result()" not in src


def test_subprocess_fire_and_forget_stores_child_workflow_id() -> None:
    src = _generate_source(mode="fire_and_forget")
    assert "child_workflow_id" in src


def test_subprocess_fire_and_forget_calls_record_child_engagement() -> None:
    src = _generate_source(mode="fire_and_forget")
    assert "record_child_engagement" in src


# ---------------------------------------------------------------------------
# Mapper → Generator integration
# ---------------------------------------------------------------------------


def test_mapper_subprocess_wait_generates_valid_workflow() -> None:
    """Full pipeline: mapper builds RunTask, generator emits correct code."""
    from mapper import map_reactflow_to_cncfsw

    rf = {
        "meta": {
            "namespace": "demo",
            "name": "parent_agent",
            "version": "1",
            "use": {},
        },
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {
                "id": "sub1",
                "type": "core.subprocess",
                "data": {"subAgentId": "support_agent", "mode": "wait"},
            },
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "sub1"}],
    }
    wf = map_reactflow_to_cncfsw(rf)
    result = generate(wf, tenant_id="demo")
    src = result.source
    assert "workflow.start_child_workflow" in src
    assert "support_agent" in src
    assert "record_child_engagement" in src
    assert ".result()" in src


def test_mapper_subprocess_fire_and_forget_generates_valid_workflow() -> None:
    from mapper import map_reactflow_to_cncfsw

    rf = {
        "meta": {
            "namespace": "demo",
            "name": "parent_faf",
            "version": "1",
            "use": {},
        },
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {
                "id": "sub1",
                "type": "core.subprocess",
                "data": {"subAgentId": "analytics_agent", "mode": "fire_and_forget"},
            },
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "sub1"}],
    }
    wf = map_reactflow_to_cncfsw(rf)
    result = generate(wf, tenant_id="demo")
    src = result.source
    assert "workflow.start_child_workflow" in src
    assert "analytics_agent" in src
    assert "child_workflow_id" in src
    assert ".result()" not in src
