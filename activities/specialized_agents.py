"""Generic dispatcher dla Specialized Agents (decyzja #18).

Wszystkie wywołania CNCF SW `call` z `function.type = weaver_specialized_agent`
przechodzą przez tę pojedynczą activity. Dispatcher routuje do właściwego
endpoint URL (z manifest) i serializuje request/response per OpenAPI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.fixture import fixturable
from activities.tools._heartbeat import safe_heartbeat


@dataclass(frozen=True, slots=True)
class AgentCall:
    """Wszystkie pola wymagane do wywołania Specialized Agent."""

    agent: str
    """Nazwa Agent-a w manifest (`activities/manifest.json` → `specialized_agents[*].name`)."""
    endpoint_url: str
    operation: str
    """OperationId z OpenAPI lub HTTP method+path identyfikator."""
    payload: dict[str, Any]
    """Body wysyłane jako JSON do Agent endpoint-u."""
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class AgentResult:
    status: int
    body: dict[str, Any]


@activity.defn(name="call_specialized_agent")
@fixturable
async def call_specialized_agent(call: dict[str, Any]) -> dict[str, Any]:
    """Wywołaj Specialized Agent przez HTTP POST <endpoint_url>/<operation>.

    Mapping błędów na base error types (decyzja #23):
    - 4xx (poza 401/403/404/429) → `ValidationError` (non-retryable)
    - 401/403 → `AuthError` (non-retryable)
    - 404 → `NotFoundError` (non-retryable)
    - 429 → `RateLimitError` (retryable)
    - timeout → `TimeoutError` (retryable)
    - 5xx / connection error → `IntegrationError` (retryable)
    """
    safe_heartbeat("started")
    parsed = AgentCall(**call)
    url = f"{parsed.endpoint_url.rstrip('/')}/{parsed.operation.lstrip('/')}"

    try:
        async with httpx.AsyncClient(timeout=parsed.timeout_seconds) as client:
            resp = await client.post(url, json=parsed.payload)
    except httpx.TimeoutException as exc:
        raise ApplicationError("TimeoutError", str(exc), non_retryable=False) from exc
    except httpx.RequestError as exc:
        raise ApplicationError("IntegrationError", str(exc), non_retryable=False) from exc

    if resp.status_code in (401, 403):
        raise ApplicationError("AuthError", resp.text, non_retryable=True)
    if resp.status_code == 404:
        raise ApplicationError("NotFoundError", resp.text, non_retryable=True)
    if resp.status_code == 429:
        raise ApplicationError("RateLimitError", resp.text, non_retryable=False)
    if 400 <= resp.status_code < 500:
        raise ApplicationError("ValidationError", resp.text, non_retryable=True)
    if resp.status_code >= 500:
        raise ApplicationError("IntegrationError", resp.text, non_retryable=False)

    try:
        body = resp.json()
    except json.JSONDecodeError as exc:
        raise ApplicationError(
            "IntegrationError",
            f"Niepoprawny JSON w odpowiedzi Agent {parsed.agent!r}: {exc}",
            non_retryable=True,
        ) from exc

    safe_heartbeat("completed")
    return AgentResult(status=resp.status_code, body=body).__dict__
