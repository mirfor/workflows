"""Tool: `docrepo_download` — fetch a document by id, return base64 bytes."""


import base64
from typing import Any

import httpx
from pydantic import BaseModel, Field
from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.tools._docrepo_common import (
    DOCREPO_BASE,
    auth_headers,
    raise_for_status,
)
from activities.tools._heartbeat import safe_heartbeat


class DocrepoDownloadInput(BaseModel):
    collection_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)


class DocrepoDownloadOutput(BaseModel):
    document_id: str
    mime_type: str
    bytes: int
    data_b64: str


@activity.defn(name="docrepo_download")
async def docrepo_download(payload: dict[str, Any]) -> dict[str, Any]:
    safe_heartbeat("started")
    parsed = DocrepoDownloadInput.model_validate(payload)
    url = (
        f"{DOCREPO_BASE}/collections/{parsed.collection_id}/documents/{parsed.document_id}/download"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=auth_headers())
    except httpx.TimeoutException as exc:
        raise ApplicationError(str(exc), type="TimeoutError", non_retryable=False) from exc
    except httpx.RequestError as exc:
        raise ApplicationError(str(exc), type="IntegrationError", non_retryable=False) from exc

    raise_for_status(resp, "download document")
    data = resp.content
    mime = resp.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()
    safe_heartbeat("completed")
    return DocrepoDownloadOutput(
        document_id=parsed.document_id,
        mime_type=mime,
        bytes=len(data),
        data_b64=base64.b64encode(data).decode("ascii"),
    ).model_dump()


TOOL_MANIFEST: dict[str, Any] = {
    "name": "docrepo_download",
    "operation": "docrepo_download",
    "input_schema": DocrepoDownloadInput.model_json_schema(),
    "output_schema": DocrepoDownloadOutput.model_json_schema(),
    "errors": [
        {"type": "ValidationError", "is_base": True, "retryable": False},
        {"type": "AuthError", "is_base": True, "retryable": False},
        {"type": "NotFoundError", "is_base": True, "retryable": False},
        {"type": "TimeoutError", "is_base": True, "retryable": True},
        {"type": "IntegrationError", "is_base": True, "retryable": True},
    ],
    "default_retry_profile": "default_retry",
    "default_timeout_profile": "default_timeout",
    "idempotent": True,
}
