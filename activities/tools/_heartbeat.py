"""Safe heartbeat helper for Temporal activities.

Silently skips heartbeating when called outside an active Temporal activity
context (e.g., unit tests, scripts).
"""

from __future__ import annotations

from typing import Any

from temporalio import activity


def safe_heartbeat(phase: str, **extra: Any) -> None:
    try:
        info = activity.info()
        activity.heartbeat({"phase": phase, "activity_type": info.activity_type, **extra})
    except RuntimeError:
        pass
