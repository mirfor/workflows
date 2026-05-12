"""Tests for `activities.tools.docrepo_download`."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from temporalio.exceptions import ApplicationError

from activities.tools import docrepo_download as dd


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCREPO_JWT", "test-token")


def _binary_resp(status: int, body: bytes, mime: str = "application/pdf") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.content = body
    r.text = body.decode("utf-8", errors="ignore")
    r.headers = {"content-type": mime}
    return r


def _patch_client(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    async def _aenter(self: Any) -> Any:
        return self

    async def _aexit(self: Any, *exc: Any) -> None:
        return None

    fake_client = MagicMock()
    fake_client.__aenter__ = _aenter
    fake_client.__aexit__ = _aexit
    fake_client.get = AsyncMock(return_value=response)
    monkeypatch.setattr(dd.httpx, "AsyncClient", lambda *_a, **_kw: fake_client)


async def test_download_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, _binary_resp(200, b"%PDF-1.4..."))
    out = await dd.docrepo_download({"collection_id": "col-1", "document_id": "doc-1"})
    assert out["mime_type"] == "application/pdf"
    assert out["bytes"] == len(b"%PDF-1.4...")
    assert base64.b64decode(out["data_b64"]) == b"%PDF-1.4..."


async def test_download_404_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, _binary_resp(404, b'{"error":"not found"}'))
    with pytest.raises(ApplicationError) as exc_info:
        await dd.docrepo_download({"collection_id": "col-1", "document_id": "missing"})
    assert exc_info.value.type == "NotFoundError"
