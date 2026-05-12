"""Tool: `docrepo_upload` — upload bytes to weaver-docrepo, wait for AVAILABLE.

Idempotency: collections are resolved by name (created on first use); uploads
are NOT idempotent (each call creates a new doc + scan job).
"""

from __future__ import annotations

import asyncio
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

_POLL_INTERVAL_SECONDS = 1.0
_POLL_MAX_ATTEMPTS = 60


class DocrepoUploadInput(BaseModel):
    collection_name: str = Field(..., min_length=1)
    file_name: str = Field(..., min_length=1)
    mime_type: str = Field(..., min_length=1)
    data_b64: str = Field(..., min_length=1)


class DocrepoUploadOutput(BaseModel):
    collection_id: str
    document_id: str
    upload_id: str
    bytes: int


async def _resolve_collection(client: httpx.AsyncClient, collection_name: str) -> str:
    resp = await client.get(f"{DOCREPO_BASE}/collections", headers=auth_headers())
    raise_for_status(resp, "list collections")
    for item in resp.json().get("items", []):
        if item.get("name") == collection_name:
            cid = item.get("id")
            if isinstance(cid, str):
                return cid
    create = await client.post(
        f"{DOCREPO_BASE}/collections",
        headers={**auth_headers(), "Content-Type": "application/json"},
        json={"name": collection_name, "description": "auto-created by agent-designer"},
    )
    raise_for_status(create, "create collection")
    cid = create.json().get("id")
    if not isinstance(cid, str):
        raise ApplicationError(
            f"docrepo create collection returned no id: {create.text}",
            type="IntegrationError",
            non_retryable=True,
        )
    return cid


async def _wait_available(client: httpx.AsyncClient, upload_id: str) -> None:
    for _ in range(_POLL_MAX_ATTEMPTS):
        safe_heartbeat("scanning", upload_id=upload_id)
        resp = await client.get(
            f"{DOCREPO_BASE}/uploads/{upload_id}/status", headers=auth_headers()
        )
        raise_for_status(resp, "upload status")
        status = resp.json().get("status")
        if status == "AVAILABLE":
            return
        if status in ("REJECTED", "SCAN_ERROR"):
            raise ApplicationError(
                f"upload rejected by scanner: status={status}",
                type="ValidationError",
                non_retryable=True,
            )
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    raise ApplicationError(
        f"upload {upload_id} did not reach AVAILABLE within "
        f"{_POLL_INTERVAL_SECONDS * _POLL_MAX_ATTEMPTS:.0f}s",
        type="TimeoutError",
        non_retryable=False,
    )


@activity.defn(name="docrepo_upload")
async def docrepo_upload(payload: dict[str, Any]) -> dict[str, Any]:
    safe_heartbeat("started")
    parsed = DocrepoUploadInput.model_validate(payload)
    data = base64.b64decode(parsed.data_b64)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            collection_id = await _resolve_collection(client, parsed.collection_name)

            files = {"file": (parsed.file_name, data, parsed.mime_type)}
            resp = await client.post(
                f"{DOCREPO_BASE}/collections/{collection_id}/documents",
                headers=auth_headers(),
                files=files,
            )
            raise_for_status(resp, "upload document")
            body = resp.json()
            doc_id = body.get("documentId") or body.get("document_id") or body.get("id")
            upload_id = body.get("uploadId") or body.get("upload_id")
            if not isinstance(doc_id, str) or not isinstance(upload_id, str):
                raise ApplicationError(
                    f"docrepo upload returned unexpected body: {resp.text}",
                    type="IntegrationError",
                    non_retryable=True,
                )

            await _wait_available(client, upload_id)
    except httpx.TimeoutException as exc:
        raise ApplicationError(str(exc), type="TimeoutError", non_retryable=False) from exc
    except httpx.RequestError as exc:
        raise ApplicationError(str(exc), type="IntegrationError", non_retryable=False) from exc

    safe_heartbeat("completed")
    return DocrepoUploadOutput(
        collection_id=collection_id,
        document_id=doc_id,
        upload_id=upload_id,
        bytes=len(data),
    ).model_dump()


TOOL_MANIFEST: dict[str, Any] = {
    "name": "docrepo_upload",
    "operation": "docrepo_upload",
    "input_schema": DocrepoUploadInput.model_json_schema(),
    "output_schema": DocrepoUploadOutput.model_json_schema(),
    "errors": [
        {"type": "ValidationError", "is_base": True, "retryable": False},
        {"type": "AuthError", "is_base": True, "retryable": False},
        {"type": "NotFoundError", "is_base": True, "retryable": False},
        {"type": "TimeoutError", "is_base": True, "retryable": True},
        {"type": "IntegrationError", "is_base": True, "retryable": True},
    ],
    "default_retry_profile": "default_retry",
    "default_timeout_profile": "default_timeout",
    "idempotent": False,
}
