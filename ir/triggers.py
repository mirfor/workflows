"""Trigger jako pierwszy node grafu (#10) — extension Weaver, nie spec CNCF SW.

W IR JSON trigger leży w `document.metadata.weaver.trigger` (nie w `do[]`).
Mapper RF wykrywa trigger node (`incoming edges == 0`) i odkłada go do metadata.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, Tag

from ir._base import JqExpression, StrictModel


class _TriggerBase(StrictModel):
    type: str
    metadata: dict[str, Any] | None = None


class ManualTrigger(_TriggerBase):
    type: Literal["manual_trigger"] = "manual_trigger"
    input_schema_ref: str | None = None


class WebhookTrigger(_TriggerBase):
    type: Literal["webhook_trigger"] = "webhook_trigger"
    path: str = Field(..., min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    auth_ref: str | None = None
    """Referencja do `Use.authentications.<name>`."""


class ScheduleTrigger(_TriggerBase):
    type: Literal["schedule_trigger"] = "schedule_trigger"
    cron: str | None = None
    """Cron wyrażenie (Temporal Schedule)."""
    every: str | None = None
    """ISO 8601 duration (alternatywa do cron)."""
    start_at: str | None = None
    end_at: str | None = None
    timezone: str | None = None


class EventTrigger(_TriggerBase):
    type: Literal["event_trigger"] = "event_trigger"
    source: str
    event_type: str = Field(..., alias="eventType")
    filter: JqExpression | None = None


def _trigger_discriminator(v: Any) -> str | None:
    if isinstance(v, dict):
        return v.get("type")
    return getattr(v, "type", None)


Trigger = Annotated[
    Annotated[ManualTrigger, Tag("manual_trigger")]
    | Annotated[WebhookTrigger, Tag("webhook_trigger")]
    | Annotated[ScheduleTrigger, Tag("schedule_trigger")]
    | Annotated[EventTrigger, Tag("event_trigger")],
    Discriminator(_trigger_discriminator),
]
