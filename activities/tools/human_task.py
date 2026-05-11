"""Tool Activity: `create_human_task` — tworzy Task w Inbox API.

Wywoływany przez wygenerowany workflow gdy napotka węzeł `core.human_task`.
POSTuje do POST /api/internal/tasks z X-Internal-Key.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from pydantic import BaseModel, Field
from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.fixture import fixturable


class HumanTaskInput(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    engagement_id: str = Field(..., min_length=1)
    form_id: str = Field(..., min_length=1)
    assignee: str = Field(..., min_length=1)
    sla: str | None = None


class HumanTaskOutput(BaseModel):
    task_id: str
    status: str
    created_at: str


@activity.defn(name="create_human_task")
@fixturable
async def create_human_task(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = HumanTaskInput.model_validate(payload)

    api_url = os.environ.get("INTERNAL_API_URL", "http://localhost:8500")
    api_key = os.environ.get("INTERNAL_API_KEY", "dev-internal-key")

    body: dict[str, Any] = {
        "tenant_id": parsed.tenant_id,
        "engagement_id": parsed.engagement_id,
        "form_id": parsed.form_id,
        "assignee": parsed.assignee,
    }
    if parsed.sla is not None:
        body["sla"] = parsed.sla

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{api_url}/api/internal/tasks",
                json=body,
                headers={"X-Internal-Key": api_key},
            )
            resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ApplicationError("TimeoutError", str(exc), non_retryable=False) from exc
    except httpx.HTTPStatusError as exc:
        non_retryable = exc.response.status_code in (400, 401, 403, 422)
        raise ApplicationError("IntegrationError", str(exc), non_retryable=non_retryable) from exc
    except httpx.RequestError as exc:
        raise ApplicationError("IntegrationError", str(exc), non_retryable=False) from exc

    data = resp.json()
    return HumanTaskOutput(
        task_id=data["task_id"],
        status=data["status"],
        created_at=data["created_at"],
    ).model_dump()


TOOL_MANIFEST: dict[str, Any] = {
    "name": "create_human_task",
    "operation": "create_human_task",
    "input_schema": HumanTaskInput.model_json_schema(),
    "output_schema": HumanTaskOutput.model_json_schema(),
    "errors": [
        {"type": "ValidationError", "is_base": True, "retryable": False},
        {"type": "TimeoutError", "is_base": True, "retryable": True},
        {"type": "IntegrationError", "is_base": True, "retryable": True},
    ],
    "default_retry_profile": "default_retry",
    "default_timeout_profile": "default_timeout",
    "idempotent": False,
}
