"""Tool Activity: `record_child_engagement` — rejestruje child Engagement w API.

Wywoływany przez wygenerowany workflow po uruchomieniu child workflow przez
`start_child_workflow`. POSTuje do POST /api/internal/engagements z X-Internal-Key.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from pydantic import BaseModel, Field
from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.fixture import fixturable


class ChildEngagementInput(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1)
    workflow_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    parent_workflow_id: str = Field(..., min_length=1)


class ChildEngagementOutput(BaseModel):
    engagement_id: str
    workflow_id: str
    status: str


@activity.defn(name="record_child_engagement")
@fixturable
async def record_child_engagement(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = ChildEngagementInput.model_validate(payload)

    api_url = os.environ.get("INTERNAL_API_URL", "http://localhost:8500")
    api_key = os.environ.get("INTERNAL_API_KEY", "dev-internal-key")

    body: dict[str, Any] = {
        "tenant_id": parsed.tenant_id,
        "agent_id": parsed.agent_id,
        "workflow_id": parsed.workflow_id,
        "run_id": parsed.run_id,
        "parent_workflow_id": parsed.parent_workflow_id,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{api_url}/api/internal/engagements",
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
    return ChildEngagementOutput(
        engagement_id=data["engagement_id"],
        workflow_id=data["workflow_id"],
        status=data["status"],
    ).model_dump()


TOOL_MANIFEST: dict[str, Any] = {
    "name": "record_child_engagement",
    "operation": "record_child_engagement",
    "input_schema": ChildEngagementInput.model_json_schema(),
    "output_schema": ChildEngagementOutput.model_json_schema(),
    "errors": [
        {"type": "ValidationError", "is_base": True, "retryable": False},
        {"type": "TimeoutError", "is_base": True, "retryable": True},
        {"type": "IntegrationError", "is_base": True, "retryable": True},
    ],
    "default_retry_profile": "default_retry",
    "default_timeout_profile": "default_timeout",
    "idempotent": True,
}
