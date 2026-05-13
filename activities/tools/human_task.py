"""Tool Activity: `create_human_task` — block-and-poll until user completes.

1. POST /api/internal/tasks with form_schema / intent / title / assignee.
2. Receive task_id back.
3. Heartbeat + poll /api/tasks/{task_id} until status='completed'.
4. Return form_data (the user's submission) — downstream nodes can read
   `.<this_node_id>.output.<field>` (e.g. `.approval.output.files`).

D-024 (no mocks): the public `/api/tasks/{id}/complete` route persists
status=completed + form_data in DB; this activity reads same row.
"""

import asyncio
import os
from typing import Any

import httpx
from pydantic import BaseModel, Field
from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.fixture import fixturable
from activities.tools._heartbeat import safe_heartbeat


class HumanTaskInput(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    engagement_id: str = Field(..., min_length=1)
    form_id: str = Field(..., min_length=1)
    assignee: str = Field(..., min_length=1)
    sla: str | None = None
    form_schema: dict[str, Any] | None = None
    intent: str | None = None
    title: str | None = None


class HumanTaskOutput(BaseModel):
    task_id: str
    status: str
    decision: str | None = None
    form_data: dict[str, Any] = Field(default_factory=dict)


@activity.defn(name="create_human_task")
@fixturable
async def create_human_task(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = HumanTaskInput.model_validate(payload)

    api_url = os.environ.get("INTERNAL_API_URL", "http://localhost:8500")
    api_key = os.environ.get("INTERNAL_API_KEY", "dev-internal-key")
    poll_interval = float(os.environ.get("HUMAN_TASK_POLL_SECONDS", "2"))

    create_body: dict[str, Any] = {
        "tenant_id": parsed.tenant_id,
        "engagement_id": parsed.engagement_id,
        "form_id": parsed.form_id,
        "assignee": parsed.assignee,
    }
    if parsed.sla is not None:
        create_body["sla"] = parsed.sla
    if parsed.form_schema is not None:
        create_body["form_schema"] = parsed.form_schema
    if parsed.intent is not None:
        create_body["intent"] = parsed.intent
    if parsed.title is not None:
        create_body["title"] = parsed.title

    # 1. Create the task
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{api_url}/api/internal/tasks",
                json=create_body,
                headers={"X-Internal-Key": api_key},
            )
            resp.raise_for_status()
            created = resp.json()
    except httpx.TimeoutException as exc:
        raise ApplicationError("TimeoutError", str(exc), non_retryable=False) from exc
    except httpx.HTTPStatusError as exc:
        non_retryable = exc.response.status_code in (400, 401, 403, 422)
        raise ApplicationError(
            "IntegrationError", str(exc), non_retryable=non_retryable
        ) from exc
    except httpx.RequestError as exc:
        raise ApplicationError("IntegrationError", str(exc), non_retryable=False) from exc

    task_id = created["task_id"]
    safe_heartbeat("created", task_id=task_id)

    # 2. Poll until completed (worker heartbeats keep the activity alive;
    # `default_timeout_profile` should be tuned for human SLA — e.g. 24h).
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            safe_heartbeat("waiting", task_id=task_id)
            try:
                detail = await client.get(
                    f"{api_url}/api/internal/tasks/{task_id}",
                    headers={"X-Internal-Key": api_key},
                )
                if detail.status_code == 404:
                    raise ApplicationError(
                        "ValidationError",
                        f"Task {task_id} disappeared while polling",
                        non_retryable=True,
                    )
                detail.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ApplicationError(
                    "IntegrationError", str(exc), non_retryable=False
                ) from exc
            except httpx.RequestError as exc:
                raise ApplicationError(
                    "IntegrationError", str(exc), non_retryable=False
                ) from exc

            row = detail.json()
            if row.get("status") == "completed":
                return HumanTaskOutput(
                    task_id=task_id,
                    status="completed",
                    decision=row.get("decision"),
                    form_data=row.get("form_data") or {},
                ).model_dump()

            await asyncio.sleep(poll_interval)


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
