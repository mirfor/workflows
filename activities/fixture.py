"""Fixture mode support for activities (post-MVP placeholder).

When `FIXTURE_MODE=true` (or `1`, `yes`), activities decorated with `@fixturable`
return a static JSON response instead of executing real logic. Intended for
mocking LLM calls and side-effects during development and dry-run testing.

Usage:
    @activity.defn(name="my_op")
    @fixturable
    async def my_op(payload: dict[str, Any]) -> dict[str, Any]:
        ...  # not executed when FIXTURE_MODE is set

Fixture file: activities/fixtures/<function_name>.json
See workflows/docs/FIXTURE_MODE.md for how to add a fixture.
"""

from __future__ import annotations

import functools
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def is_fixture_mode() -> bool:
    """Return True when FIXTURE_MODE is set to '1', 'true', or 'yes' (case-insensitive)."""
    return os.environ.get("FIXTURE_MODE", "").lower() in ("1", "true", "yes")


def fixturable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an activity to return a static fixture when FIXTURE_MODE is active.

    Apply as inner decorator (inside @activity.defn):

        @activity.defn(name="my_op")
        @fixturable
        async def my_op(payload: dict[str, Any]) -> dict[str, Any]:
            ...

    Fixture resolved from activities/fixtures/<function_name>.json.
    Raises FileNotFoundError if FIXTURE_MODE is set but the fixture file is absent.
    """

    @functools.wraps(fn)
    async def wrapper(payload: dict[str, Any]) -> dict[str, Any]:
        if is_fixture_mode():
            fixture_path = _FIXTURES_DIR / f"{fn.__name__}.json"
            if not fixture_path.exists():
                raise FileNotFoundError(
                    f"Fixture missing for activity '{fn.__name__}': {fixture_path}. "
                    f"Create this file to enable FIXTURE_MODE for this activity."
                )
            return json.loads(fixture_path.read_text(encoding="utf-8"))  # type: ignore[return-value]
        return await fn(payload)

    return wrapper
