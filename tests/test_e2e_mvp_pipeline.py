"""End-to-end smoke for the invoice-batch MVP pipeline.

Exercises the real activities against real local services:
  1. docrepo_upload  — uploads a real PDF, waits for AVAILABLE.
  2. docrepo_download — round-trips the same doc.
  3. invoice_extraction — calls weaver-llm-proxy /api/v1/vision; SKIPS if
     ANTHROPIC_API_KEY (or proxy) is not configured.
  4. write_artifact  — persists JSON + CSV.

Each step is its own test so the suite still passes when some deps are down.
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
from pathlib import Path

import httpx
import pypdfium2 as pdfium
import pytest

from activities.tools import (
    docrepo_download,
    docrepo_upload,
    invoice_extraction,
    write_artifact,
)

DOCREPO_BASE = os.environ.get("DOCREPO_BASE_URL", "http://localhost:8080/api/v1")
LLM_PROXY_BASE = os.environ.get("LLM_PROXY_BASE_URL", "http://localhost:8002")
DOCREPO_JWT_SECRET = "local-dev-secret-change-in-prod"


@pytest.fixture(scope="module")
def docrepo_jwt() -> str:
    if token := os.environ.get("DOCREPO_JWT"):
        return token
    script = (
        Path(__file__).resolve().parents[2]
        / "weaver-root"
        / "weaver-docrepo"
        / "scripts"
        / "generate-dev-token.ts"
    )
    if not script.exists():
        pytest.skip("generate-dev-token.ts not available")
    env = {**os.environ, "TEST_JWT_SECRET": DOCREPO_JWT_SECRET}
    result = subprocess.run(
        ["npx", "tsx", str(script), "--sub", "e2e-test", "--org-id", "demo", "--expires", "1h"],
        capture_output=True,
        text=True,
        env=env,
        cwd=script.parent.parent,
    )
    if result.returncode != 0:
        pytest.skip(f"could not generate dev JWT: {result.stderr}")
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def _env(docrepo_jwt: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCREPO_JWT", docrepo_jwt)
    monkeypatch.setenv(
        "LLM_PROXY_INTERNAL_KEY", os.environ.get("LLM_PROXY_INTERNAL_KEY", "dev-internal-key")
    )


def _is_docrepo_up() -> bool:
    try:
        r = httpx.get(f"{DOCREPO_BASE}/collections", timeout=2.0)
        return r.status_code in (200, 401)
    except (httpx.RequestError, httpx.TimeoutException):
        return False


def _is_proxy_up() -> bool:
    try:
        r = httpx.get(f"{LLM_PROXY_BASE}/health", timeout=2.0)
        return r.status_code == 200
    except (httpx.RequestError, httpx.TimeoutException):
        return False


def _has_provider_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _make_invoice_pdf() -> bytes:
    doc = pdfium.PdfDocument.new()
    try:
        doc.new_page(595, 842)
        doc.new_page(595, 842)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    finally:
        doc.close()


@pytest.mark.skipif(not _is_docrepo_up(), reason="docrepo not running at :8080")
async def test_pipeline_step_1_upload_to_docrepo() -> None:
    pdf_bytes = _make_invoice_pdf()
    out = await docrepo_upload.docrepo_upload(
        {
            "collection_name": "agent-designer-mvp-e2e",
            "file_name": "test-invoice.pdf",
            "mime_type": "application/pdf",
            "data_b64": base64.b64encode(pdf_bytes).decode("ascii"),
        }
    )
    assert out["bytes"] == len(pdf_bytes)
    assert out["document_id"]
    assert out["collection_id"]


@pytest.mark.skipif(not _is_docrepo_up(), reason="docrepo not running at :8080")
async def test_pipeline_step_2_round_trip_through_docrepo() -> None:
    pdf_bytes = _make_invoice_pdf()
    uploaded = await docrepo_upload.docrepo_upload(
        {
            "collection_name": "agent-designer-mvp-e2e",
            "file_name": "round-trip.pdf",
            "mime_type": "application/pdf",
            "data_b64": base64.b64encode(pdf_bytes).decode("ascii"),
        }
    )
    downloaded = await docrepo_download.docrepo_download(
        {
            "collection_id": uploaded["collection_id"],
            "document_id": uploaded["document_id"],
        }
    )
    assert downloaded["bytes"] == len(pdf_bytes)
    assert base64.b64decode(downloaded["data_b64"]) == pdf_bytes
    assert downloaded["mime_type"] in ("application/pdf", "application/octet-stream")


@pytest.mark.skipif(not _is_proxy_up(), reason="llm-proxy not running at :8002")
@pytest.mark.skipif(not _has_provider_key(), reason="no ANTHROPIC/OPENAI key in env")
async def test_pipeline_step_3_extract_with_real_llm() -> None:
    pdf_bytes = _make_invoice_pdf()
    out = await invoice_extraction.invoice_extraction(
        {
            "mime_type": "application/pdf",
            "data_b64": base64.b64encode(pdf_bytes).decode("ascii"),
            "pages_per_chunk": 5,
        }
    )
    assert out["pages_processed"] == 2
    assert isinstance(out["invoice"], dict)
    assert out["usage_total_tokens"] > 0


async def test_pipeline_step_4_write_artifact_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(write_artifact, "_ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(write_artifact, "_PUBLIC_BASE", "file:///art")

    postings = [
        {
            "invoice_number": "FV/2026/001",
            "seller_nip": "1234567890",
            "buyer_nip": "9999999999",
            "net": 100.0,
            "vat": 23.0,
            "gross": 123.0,
            "suggested_account": "200",
        },
        {
            "invoice_number": "FV/2026/002",
            "seller_nip": "5555555555",
            "buyer_nip": "9999999999",
            "net": 50.0,
            "vat": 11.5,
            "gross": 61.5,
            "suggested_account": "201",
        },
    ]

    json_out = await write_artifact.write_artifact(
        {
            "tenant_id": "demo",
            "engagement_id": "eng-e2e",
            "filename": "postings",
            "format": "json",
            "data": postings,
        }
    )
    csv_out = await write_artifact.write_artifact(
        {
            "tenant_id": "demo",
            "engagement_id": "eng-e2e",
            "filename": "postings.csv",
            "format": "csv",
            "data": postings,
        }
    )

    json_path = Path(json_out["absolute_path"])
    csv_path = Path(csv_out["absolute_path"])
    assert json.loads(json_path.read_text()) == postings

    csv_lines = csv_path.read_text().strip().splitlines()
    assert csv_lines[0] == ",".join(postings[0].keys())
    assert len(csv_lines) == 1 + len(postings)
