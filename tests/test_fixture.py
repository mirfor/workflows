"""Tests for FIXTURE_MODE / @fixturable decorator (P8.4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from temporalio import activity

import activities.fixture as fixture_mod
from activities.fixture import (
    _FIXTURES_DIR,
    fixturable,
    is_fixture_mode,
)

# ---------------------------------------------------------------------------
# is_fixture_mode
# ---------------------------------------------------------------------------


def test_is_fixture_mode_false_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIXTURE_MODE", raising=False)
    assert is_fixture_mode() is False


@pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "YES", "Yes"])
def test_is_fixture_mode_true_for_truthy_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("FIXTURE_MODE", value)
    assert is_fixture_mode() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "nope"])
def test_is_fixture_mode_false_for_other_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("FIXTURE_MODE", value)
    assert is_fixture_mode() is False


# ---------------------------------------------------------------------------
# @fixturable decorator
# ---------------------------------------------------------------------------


async def test_fixturable_calls_original_when_not_in_fixture_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIXTURE_MODE", raising=False)
    called = False

    @fixturable
    async def sample_activity(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"result": "real"}

    result = await sample_activity({"key": "value"})
    assert called is True
    assert result == {"result": "real"}


async def test_fixturable_returns_fixture_when_in_fixture_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FIXTURE_MODE", "true")
    monkeypatch.setattr(fixture_mod, "_FIXTURES_DIR", tmp_path)

    fixture_data = {"result": "fixture_value", "from_fixture": True}
    (tmp_path / "sample_activity.json").write_text(json.dumps(fixture_data))

    @fixturable
    async def sample_activity(payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("Should not be called in fixture mode")

    result = await sample_activity({"key": "value"})
    assert result == fixture_data


async def test_fixturable_raises_when_fixture_file_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FIXTURE_MODE", "true")
    monkeypatch.setattr(fixture_mod, "_FIXTURES_DIR", tmp_path)

    @fixturable
    async def sample_activity(payload: dict[str, Any]) -> dict[str, Any]:
        return {}

    with pytest.raises(FileNotFoundError, match="sample_activity"):
        await sample_activity({})


async def test_fixturable_payload_passed_through_in_normal_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIXTURE_MODE", raising=False)
    received: dict[str, Any] = {}

    @fixturable
    async def sample_activity(payload: dict[str, Any]) -> dict[str, Any]:
        received.update(payload)
        return {}

    await sample_activity({"foo": "bar", "baz": 42})
    assert received == {"foo": "bar", "baz": 42}


def test_fixturable_preserves_function_name() -> None:
    @fixturable
    async def my_special_activity(payload: dict[str, Any]) -> dict[str, Any]:
        return {}

    assert my_special_activity.__name__ == "my_special_activity"


def test_fixturable_compatible_with_activity_defn() -> None:
    """@fixturable (inner) + @activity.defn (outer) — __temporal_activity_definition preserved."""

    @activity.defn(name="test_fixture_op")
    @fixturable
    async def test_fixture_op(payload: dict[str, Any]) -> dict[str, Any]:
        return {}

    assert hasattr(test_fixture_op, "__temporal_activity_definition")


# ---------------------------------------------------------------------------
# Built-in fixture files exist and are valid JSON
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "activity_name",
    [
        "http_get",
        "log_message",
        "create_human_task",
        "record_child_engagement",
        "call_specialized_agent",
    ],
)
def test_built_in_fixtures_exist_and_are_valid_json(activity_name: str) -> None:
    fixture_path = _FIXTURES_DIR / f"{activity_name}.json"
    assert fixture_path.exists(), f"Fixture file missing: {fixture_path}"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_built_in_fixtures_dir_exists() -> None:
    assert _FIXTURES_DIR.is_dir()
