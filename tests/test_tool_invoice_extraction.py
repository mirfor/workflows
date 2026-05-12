"""Tests for `activities.tools.invoice_extraction` — merge logic + chunking."""

from __future__ import annotations

import base64
import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pypdfium2 as pdfium
import pytest
from temporalio.exceptions import ApplicationError

from activities.tools import invoice_extraction as ie


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROXY_INTERNAL_KEY", "test-key")


def _make_pdf(n_pages: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    try:
        for _ in range(n_pages):
            doc.new_page(595, 842)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    finally:
        doc.close()


def _mock_resp(
    parsed: dict[str, Any] | None, tokens: int = 100, model: str = "anthropic/claude-sonnet-4-5"
) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json = MagicMock(
        return_value={
            "parsed_json": parsed,
            "content": "...",
            "model": model,
            "usage": {"prompt_tokens": tokens, "completion_tokens": tokens, "total_tokens": tokens},
        }
    )
    r.text = ""
    return r


def _patch_client(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> AsyncMock:
    queue = list(responses)

    async def _aenter(self: Any) -> Any:
        return self

    async def _aexit(self: Any, *exc: Any) -> None:
        return None

    async def _next(*_a: Any, **_kw: Any) -> Any:
        return queue.pop(0)

    fake = MagicMock()
    fake.__aenter__ = _aenter
    fake.__aexit__ = _aexit
    post_mock = AsyncMock(side_effect=_next)
    fake.post = post_mock
    monkeypatch.setattr(ie.httpx, "AsyncClient", lambda *_a, **_kw: fake)
    return post_mock


async def test_image_extraction_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    post_mock = _patch_client(
        monkeypatch,
        [
            _mock_resp(
                {
                    "invoice_number": "FV/2026/001",
                    "seller": {"name": "ACME", "nip": "1234567890", "address": "PL"},
                    "buyer": {"name": "BUYER", "nip": "9999999999", "address": "PL"},
                    "totals": {"net": 100.0, "vat": 23.0, "gross": 123.0},
                    "line_items": [
                        {
                            "description": "Service",
                            "quantity": 1,
                            "unit_price_net": 100.0,
                            "vat_rate": 23,
                            "net": 100.0,
                            "vat": 23.0,
                            "gross": 123.0,
                        }
                    ],
                    "issue_date": "2026-05-01",
                    "due_date": "2026-05-15",
                    "sale_date": "2026-05-01",
                    "currency": "PLN",
                }
            ),
        ],
    )
    out = await ie.invoice_extraction(
        {
            "mime_type": "image/png",
            "data_b64": base64.b64encode(b"\x89PNG...").decode("ascii"),
        }
    )
    assert out["pages_processed"] == 1
    assert out["chunks_processed"] == 1
    assert out["invoice"]["invoice_number"] == "FV/2026/001"
    assert out["invoice"]["totals"]["gross"] == 123.0
    assert out["usage_total_tokens"] == 100
    assert post_mock.await_count == 1


async def test_pdf_extraction_splits_and_merges(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _make_pdf(7)
    post_mock = _patch_client(
        monkeypatch,
        [
            _mock_resp(
                {
                    "invoice_number": "FV/2026/002",
                    "seller": {"name": "S1", "nip": None, "address": None},
                    "buyer": None,
                    "totals": None,
                    "line_items": [
                        {
                            "description": "A",
                            "quantity": 1,
                            "unit_price_net": 10.0,
                            "vat_rate": 23,
                            "net": 10.0,
                            "vat": 2.3,
                            "gross": 12.3,
                        }
                    ],
                    "issue_date": None,
                    "due_date": None,
                    "sale_date": None,
                    "currency": None,
                }
            ),
            _mock_resp(
                {
                    "invoice_number": None,
                    "seller": None,
                    "buyer": {"name": "B1", "nip": "1111111111", "address": "PL"},
                    "totals": {"net": 30.0, "vat": 6.9, "gross": 36.9},
                    "line_items": [
                        {
                            "description": "B",
                            "quantity": 1,
                            "unit_price_net": 20.0,
                            "vat_rate": 23,
                            "net": 20.0,
                            "vat": 4.6,
                            "gross": 24.6,
                        }
                    ],
                    "issue_date": None,
                    "due_date": None,
                    "sale_date": None,
                    "currency": "PLN",
                }
            ),
        ],
    )
    out = await ie.invoice_extraction(
        {
            "mime_type": "application/pdf",
            "data_b64": base64.b64encode(pdf).decode("ascii"),
            "pages_per_chunk": 5,
        }
    )
    assert out["pages_processed"] == 7
    assert out["chunks_processed"] == 2
    inv = out["invoice"]
    assert inv["invoice_number"] == "FV/2026/002"  # chunk 1
    assert inv["buyer"]["nip"] == "1111111111"  # chunk 2
    assert inv["totals"]["gross"] == 36.9  # chunk 2
    assert inv["currency"] == "PLN"  # chunk 2
    assert len(inv["line_items"]) == 2
    assert out["usage_total_tokens"] == 200
    assert post_mock.await_count == 2


async def test_unsupported_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ApplicationError) as exc_info:
        await ie.invoice_extraction({"mime_type": "application/zip", "data_b64": "AAA"})
    assert exc_info.value.type == "ValidationError"


async def test_missing_proxy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROXY_INTERNAL_KEY", raising=False)
    with pytest.raises(ApplicationError) as exc_info:
        await ie.invoice_extraction(
            {"mime_type": "image/png", "data_b64": base64.b64encode(b"x").decode("ascii")}
        )
    assert exc_info.value.type == "AuthError"
