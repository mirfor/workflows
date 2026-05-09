"""Smoke testy activity registry + sample tools (F4)."""

from __future__ import annotations

from activities import ALL_ACTIVITIES, call_specialized_agent
from activities.registry import _discover_tool_activities


def test_registry_discovers_sample_tools() -> None:
    activities = _discover_tool_activities()
    names = {a.__name__ for a in activities}
    assert "log_message" in names
    assert "http_get" in names


def test_all_activities_includes_dispatcher() -> None:
    assert call_specialized_agent in ALL_ACTIVITIES


def test_all_activities_unique() -> None:
    assert len(ALL_ACTIVITIES) == len({id(a) for a in ALL_ACTIVITIES})


async def test_log_message_activity_runs() -> None:
    from activities.tools.log_message import log_message

    # Activity functions w temporalio są wrapowane; bezpośrednie wywołanie OK
    # bo akceptujemy sam payload (bez Temporal context).
    result = await log_message({"message": "hello", "level": "INFO"})
    assert result == {"logged": True, "level": "INFO"}
