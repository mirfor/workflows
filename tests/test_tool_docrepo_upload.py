"""Tests for `activities.tools.docrepo_upload` — collection resolve + upload + status poll."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from temporalio.exceptions import ApplicationError

from activities.tools import docrepo_upload as du


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCREPO_JWT", "test-token")


def _resp(status: int, json_body: Any | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=json_body if json_body is not None else {})
    r.text = "" if json_body is None else str(json_body)
    return r


def _patch_client(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> AsyncMock:
    queue = list(responses)

    async def _aenter(self: Any) -> Any:
        return self

    async def _aexit(self: Any, *exc: Any) -> None:
        return None

    async def _next_resp(*_a: Any, **_kw: Any) -> Any:
        return queue.pop(0)

    fake_client = MagicMock()
    fake_client.__aenter__ = _aenter
    fake_client.__aexit__ = _aexit
    fake_client.get = AsyncMock(side_effect=_next_resp)
    fake_client.post = AsyncMock(side_effect=_next_resp)

    def _factory(*_a: Any, **_kw: Any) -> Any:
        return fake_client

    monkeypatch.setattr(du.httpx, "AsyncClient", _factory)
    return fake_client


async def test_upload_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        [
            _resp(200, {"items": [{"id": "col-123", "name": "invoices"}]}),
            _resp(200, {"id": "doc-1", "upload_id": "up-1"}),
            _resp(200, {"status": "AVAILABLE"}),
        ],
    )
    out = await du.docrepo_upload(
        {
            "collection_name": "invoices",
            "file_name": "fv-1.pdf",
            "mime_type": "application/pdf",
            "data_b64": base64.b64encode(b"PDF-CONTENT").decode("ascii"),
        }
    )
    assert out["collection_id"] == "col-123"
    assert out["document_id"] == "doc-1"
    assert out["upload_id"] == "up-1"
    assert out["bytes"] == len(b"PDF-CONTENT")


async def test_upload_creates_collection_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        [
            _resp(200, {"items": []}),
            _resp(200, {"id": "new-col", "name": "invoices"}),
            _resp(200, {"id": "doc-2", "upload_id": "up-2"}),
            _resp(200, {"status": "AVAILABLE"}),
        ],
    )
    out = await du.docrepo_upload(
        {
            "collection_name": "invoices",
            "file_name": "a.pdf",
            "mime_type": "application/pdf",
            "data_b64": base64.b64encode(b"x").decode("ascii"),
        }
    )
    assert out["collection_id"] == "new-col"


async def test_upload_rejected_by_scanner_is_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        [
            _resp(200, {"items": [{"id": "col-1", "name": "invoices"}]}),
            _resp(200, {"id": "doc-1", "upload_id": "up-1"}),
            _resp(200, {"status": "REJECTED"}),
        ],
    )
    with pytest.raises(ApplicationError) as exc_info:
        await du.docrepo_upload(
            {
                "collection_name": "invoices",
                "file_name": "a.pdf",
                "mime_type": "application/pdf",
                "data_b64": base64.b64encode(b"x").decode("ascii"),
            }
        )
    assert exc_info.value.type == "ValidationError"


async def test_missing_jwt_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCREPO_JWT", raising=False)
    with pytest.raises(ApplicationError) as exc_info:
        await du.docrepo_upload(
            {
                "collection_name": "invoices",
                "file_name": "a.pdf",
                "mime_type": "application/pdf",
                "data_b64": base64.b64encode(b"x").decode("ascii"),
            }
        )
    assert exc_info.value.type == "AuthError"
