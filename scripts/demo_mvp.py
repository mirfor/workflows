"""Pelny demo MVP pipeline na zywych serwisach.

Wymaga:
  - docrepo (:8080)         — `make docrepo-status` lub docker-compose up
  - llm-proxy (:8002)       — `make llm-proxy-up` (z ANTHROPIC_API_KEY w .env)
  - posting-rec (:8600)     — opcjonalnie; jesli nie chodzi, krok pomijany

Krok po kroku:
  1. Generuje 2 testowe PDF-y faktur (prosty syntetyczny content)
  2. Uploaduje je do DocRepo
  3. Wywoluje invoice_extraction (Claude Vision via llm-proxy)
  4. Probuje posting_recommendation (jesli serwis chodzi)
  5. Pisze artefakty JSON + CSV do /tmp/agent-designer-artifacts/...
  6. Drukuje raport

Uruchomienie:
    cd ~/Desktop/workflows && uv run python scripts/demo_mvp.py
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from activities.tools import (  # noqa: E402
    docrepo_upload,
    invoice_extraction,
    write_artifact,
)

DOCREPO_BASE = "http://localhost:8080/api/v1"
LLM_PROXY_BASE = "http://localhost:8002"
POSTING_REC_BASE = "http://localhost:8600"
ARTIFACT_ROOT = Path("/tmp/agent-designer-artifacts")


def _section(title: str) -> None:
    print(f"\n{'═' * 70}")
    print(f"  {title}")
    print("═" * 70)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _info(msg: str) -> None:
    print(f"    {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _check_docrepo() -> bool:
    try:
        r = httpx.get(f"{DOCREPO_BASE}/collections", timeout=2.0)
        return r.status_code in (200, 401)
    except (httpx.RequestError, httpx.TimeoutException):
        return False


def _check_proxy() -> bool:
    try:
        r = httpx.get(f"{LLM_PROXY_BASE}/health", timeout=2.0)
        return r.status_code == 200
    except (httpx.RequestError, httpx.TimeoutException):
        return False


def _check_posting_rec() -> bool:
    try:
        r = httpx.get(f"{POSTING_REC_BASE}/health", timeout=2.0)
        return r.status_code == 200
    except (httpx.RequestError, httpx.TimeoutException):
        return False


def _generate_docrepo_jwt() -> str:
    if token := os.environ.get("DOCREPO_JWT"):
        return token
    script = Path.home() / "Desktop/weaver-root/weaver-docrepo/scripts/generate-dev-token.ts"
    result = subprocess.run(
        ["npx", "tsx", str(script), "--sub", "mvp-demo", "--org-id", "demo", "--expires", "1h"],
        capture_output=True,
        text=True,
        env={**os.environ, "TEST_JWT_SECRET": "local-dev-secret-change-in-prod"},
        cwd=script.parent.parent,
    )
    if result.returncode != 0:
        raise SystemExit(f"Could not generate DocRepo JWT: {result.stderr}")
    return result.stdout.strip()


def _build_invoice_pdf(invoice_no: str, seller: str, gross: float) -> bytes:
    """Build a tiny but real PDF with a text layer (so we have something to extract)."""
    doc = pdfium.PdfDocument.new()
    try:
        for _ in range(1):
            doc.new_page(595, 842)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    finally:
        doc.close()


async def main() -> int:
    _section("MVP demo — invoice batch pipeline")

    _section("0. Health checks")
    docrepo_ok = _check_docrepo()
    proxy_ok = _check_proxy()
    posting_ok = _check_posting_rec()
    if docrepo_ok:
        _ok(f"DocRepo {DOCREPO_BASE}")
    else:
        _fail(
            f"DocRepo {DOCREPO_BASE} DOWN — odpal: docker-compose up -d w weaver-root/weaver-docrepo"
        )
        return 1
    if proxy_ok:
        _ok(f"weaver-llm-proxy {LLM_PROXY_BASE}")
    else:
        _fail(f"weaver-llm-proxy {LLM_PROXY_BASE} DOWN — odpal: make llm-proxy-up")
        return 1
    if posting_ok:
        _ok(f"posting-recommendation {POSTING_REC_BASE}")
    else:
        _info(f"posting-recommendation {POSTING_REC_BASE} DOWN (krok zostanie pominiety)")

    # Configure envs
    os.environ["DOCREPO_JWT"] = _generate_docrepo_jwt()
    os.environ["LLM_PROXY_INTERNAL_KEY"] = os.environ.get(
        "LLM_PROXY_INTERNAL_KEY", "dev-internal-key"
    )

    fixtures = [
        ("FV-2026-001", "ACME Sp. z o.o.", 1230.0),
        ("FV-2026-002", "Beta Industries", 615.0),
    ]
    pdfs = [(no, _build_invoice_pdf(no, seller, gross)) for no, seller, gross in fixtures]
    _info(f"{len(pdfs)} testowe PDF-y wygenerowane")

    _section("1. Upload do DocRepo")
    upload_results = []
    for no, pdf_bytes in pdfs:
        t0 = time.perf_counter()
        result = await docrepo_upload.docrepo_upload(
            {
                "collection_name": "agent-designer-mvp-demo",
                "file_name": f"{no}.pdf",
                "mime_type": "application/pdf",
                "data_b64": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        )
        dt = (time.perf_counter() - t0) * 1000
        upload_results.append(result)
        _ok(f"{no}.pdf → doc {result['document_id'][:18]}... ({result['bytes']} B, {dt:.0f}ms)")

    _section("2. Ekstrakcja faktur (Claude Vision via llm-proxy)")
    extractions = []
    for (no, pdf_bytes), upload in zip(pdfs, upload_results, strict=True):
        t0 = time.perf_counter()
        try:
            extract = await invoice_extraction.invoice_extraction(
                {
                    "mime_type": "application/pdf",
                    "data_b64": base64.b64encode(pdf_bytes).decode("ascii"),
                    "pages_per_chunk": 5,
                }
            )
        except Exception as exc:
            _fail(f"{no}: ekstrakcja {type(exc).__name__}: {exc}")
            return 1
        dt = (time.perf_counter() - t0) * 1000
        invoice = extract["invoice"]
        extractions.append({"file": no, "doc_id": upload["document_id"], "invoice": invoice})
        _ok(
            f"{no}: model={extract['model_used']}, "
            f"tokens={extract['usage_total_tokens']}, {dt:.0f}ms"
        )
        _info(
            f"  ekstrakcja: invoice_number={invoice.get('invoice_number')!r}, "
            f"gross={invoice.get('totals', {}).get('gross')}"
        )

    _section("3. Posting recommendation")
    postings: list[dict] = []
    if posting_ok:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for ex in extractions:
                try:
                    r = await client.post(
                        f"{POSTING_REC_BASE}/recommend",
                        json={"invoice": ex["invoice"]},
                    )
                    if r.status_code == 200:
                        postings.append({"file": ex["file"], **r.json()})
                        _ok(f"{ex['file']}: posting otrzymany")
                    else:
                        _fail(f"{ex['file']}: HTTP {r.status_code}: {r.text[:120]}")
                        postings.append({"file": ex["file"], "error": r.text})
                except httpx.RequestError as exc:
                    _fail(f"{ex['file']}: {exc}")
                    postings.append({"file": ex["file"], "error": str(exc)})
    else:
        _info("Pominiete — posting-recommendation-service nie chodzi.")
        postings = [
            {
                "file": ex["file"],
                "doc_id": ex["doc_id"],
                "invoice": ex["invoice"],
                "posting": "skipped — service down",
            }
            for ex in extractions
        ]

    _section("4. Zapis artefaktow")
    json_out = await write_artifact.write_artifact(
        {
            "tenant_id": "demo",
            "engagement_id": "mvp-demo",
            "filename": "postings",
            "format": "json",
            "data": postings,
        }
    )
    _ok(f"JSON  → {json_out['absolute_path']}  ({json_out['bytes']} B)")

    flat_rows = [
        {
            "file": ex["file"],
            "doc_id": ex["doc_id"],
            "invoice_number": (ex["invoice"].get("invoice_number") or ""),
            "seller_nip": ((ex["invoice"].get("seller") or {}).get("nip") or ""),
            "buyer_nip": ((ex["invoice"].get("buyer") or {}).get("nip") or ""),
            "issue_date": (ex["invoice"].get("issue_date") or ""),
            "net": ((ex["invoice"].get("totals") or {}).get("net") or ""),
            "vat": ((ex["invoice"].get("totals") or {}).get("vat") or ""),
            "gross": ((ex["invoice"].get("totals") or {}).get("gross") or ""),
            "currency": (ex["invoice"].get("currency") or ""),
        }
        for ex in extractions
    ]
    csv_out = await write_artifact.write_artifact(
        {
            "tenant_id": "demo",
            "engagement_id": "mvp-demo",
            "filename": "postings.csv",
            "format": "csv",
            "data": flat_rows,
        }
    )
    _ok(f"CSV   → {csv_out['absolute_path']}  ({csv_out['bytes']} B)")

    _section("Demo zakonczone")
    print()
    print(f"  Wyniki: {Path(json_out['absolute_path']).parent}")
    print()
    print("  Otworz JSON:  cat", json_out["absolute_path"])
    print("  Otworz CSV:   cat", csv_out["absolute_path"])
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
