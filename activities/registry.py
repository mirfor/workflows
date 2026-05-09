"""Re-eksport `ALL_ACTIVITIES` dla worker startup.

Auto-discovery: iteruje `activities/tools/*.py`, importuje moduły, zbiera funkcje
oznaczone `@activity.defn`. Plus generic dispatcher z `activities.specialized_agents`.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

from activities import tools as _tools_pkg
from activities.specialized_agents import call_specialized_agent


def _discover_tool_activities() -> list[Callable[..., Any]]:
    activities: list[Callable[..., Any]] = []
    for info in pkgutil.iter_modules(_tools_pkg.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{_tools_pkg.__name__}.{info.name}")
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            # Temporal activity functions mają atrybut `__temporal_activity_definition`.
            if callable(obj) and hasattr(obj, "__temporal_activity_definition"):
                activities.append(obj)
    return activities


ALL_ACTIVITIES: list[Callable[..., Any]] = [
    *_discover_tool_activities(),
    call_specialized_agent,
]
"""Pełna lista activity functions ładowanych przez Temporal Worker (`worker.py`)."""
