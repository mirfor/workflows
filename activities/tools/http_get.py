"""Sample Tool: `http_get` — wykonuje GET request, zwraca status + body.

Drugi sample integration (po `log_message`) — pokazuje realistic external I/O Tool
z timeout/retry profile relevant z manifest.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field
from temporalio import activity
from temporalio.exceptions import ApplicationError


class HttpGetInput(BaseModel):
    url: str = Field(..., min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=10.0, gt=0)


class HttpGetOutput(BaseModel):
    status: int
    body: str
    headers: dict[str, str]


@activity.defn(name="http_get")
async def http_get(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = HttpGetInput.model_validate(payload)
    try:
        async with httpx.AsyncClient(timeout=parsed.timeout_seconds) as client:
            resp = await client.get(parsed.url, headers=parsed.headers)
    except httpx.TimeoutException as exc:
        raise ApplicationError("TimeoutError", str(exc), non_retryable=False) from exc
    except httpx.RequestError as exc:
        raise ApplicationError("IntegrationError", str(exc), non_retryable=False) from exc

    return HttpGetOutput(
        status=resp.status_code,
        body=resp.text,
        headers=dict(resp.headers),
    ).model_dump()


TOOL_MANIFEST: dict[str, Any] = {
    "name": "http_get",
    "operation": "http_get",
    "input_schema": HttpGetInput.model_json_schema(),
    "output_schema": HttpGetOutput.model_json_schema(),
    "errors": [
        {"type": "ValidationError", "is_base": True, "retryable": False},
        {"type": "TimeoutError", "is_base": True, "retryable": True},
        {"type": "IntegrationError", "is_base": True, "retryable": True},
    ],
    "default_retry_profile": "default_retry",
    "default_timeout_profile": "default_timeout",
    "idempotent": True,
}
