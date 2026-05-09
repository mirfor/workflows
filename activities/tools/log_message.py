"""Sample Tool: `log_message` — zapisuje wiadomość do logu workera.

Demonstruje wymagany kontrakt Tool integration:
- Pydantic models dla input / output (decyzja #13 — JSON Schema auto-eksport)
- `@activity.defn` activity (Temporal)
- `TOOL_MANIFEST: dict` agregowany do `activities/manifest.json`
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from temporalio import activity

logger = logging.getLogger(__name__)


class LogMessageInput(BaseModel):
    message: str = Field(..., min_length=1)
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")


class LogMessageOutput(BaseModel):
    logged: bool
    level: str


@activity.defn(name="log_message")
async def log_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Activity entrypoint — przyjmuje dict, zwraca dict (kompatybilność z Temporal serialization)."""
    parsed = LogMessageInput.model_validate(payload)
    level_num = getattr(logging, parsed.level)
    logger.log(level_num, "[log_message activity] %s", parsed.message)
    return LogMessageOutput(logged=True, level=parsed.level).model_dump()


TOOL_MANIFEST: dict[str, Any] = {
    "name": "log_message",
    "operation": "log_message",
    "input_schema": LogMessageInput.model_json_schema(),
    "output_schema": LogMessageOutput.model_json_schema(),
    "errors": [
        {"type": "ValidationError", "is_base": True, "retryable": False},
    ],
    "default_retry_profile": None,
    "default_timeout_profile": "default_timeout",
    "idempotent": True,
}
