"""Tool: `invoice_extraction` — turn a base64 PDF/image into structured invoice JSON.

Pipeline:
1. Receive base64 PDF or image.
2. If PDF and >`pages_per_chunk` pages, split into chunks (pypdfium2).
3. Send each chunk to `weaver-llm-proxy /api/v1/vision` with a fixed system prompt
   and a JSON schema describing a Polish invoice.
4. Merge per-chunk results (concatenate line_items, dedupe header fields).

The resulting JSON matches the input contract expected by `posting-recommendation-service`.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from pydantic import BaseModel, Field
from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.tools._heartbeat import safe_heartbeat
from utils.pdf import count_pages, render_pages_to_png

_LLM_PROXY_BASE = os.environ.get("LLM_PROXY_BASE_URL", "http://localhost:8002")
_LLM_PROXY_KEY_ENV = "LLM_PROXY_INTERNAL_KEY"
_DEFAULT_PAGES_PER_CHUNK = 5
_TIMEOUT_SECONDS = 120.0

_SYSTEM_PROMPT = (
    "Jestes ekstraktorem danych z polskich faktur VAT. "
    "Zwracaj tylko obiekt JSON zgodny ze schema. "
    "Liczby - bez separatorow tysiecy, kropka jako separator dziesietny. "
    "Daty w formacie ISO 8601 (YYYY-MM-DD). "
    "NIP bez kresek (10 cyfr). "
    "Gdy pole nie jest widoczne na fakturze, ustaw je na null."
)

_INVOICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": ["string", "null"]},
        "issue_date": {"type": ["string", "null"], "description": "ISO 8601 YYYY-MM-DD"},
        "due_date": {"type": ["string", "null"], "description": "ISO 8601 YYYY-MM-DD"},
        "sale_date": {"type": ["string", "null"], "description": "ISO 8601 YYYY-MM-DD"},
        "currency": {"type": ["string", "null"], "description": "ISO 4217, e.g. PLN, EUR"},
        "seller": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "nip": {"type": ["string", "null"], "description": "10 digits, no dashes"},
                "address": {"type": ["string", "null"]},
            },
            "required": ["name", "nip", "address"],
            "additionalProperties": False,
        },
        "buyer": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "nip": {"type": ["string", "null"], "description": "10 digits, no dashes"},
                "address": {"type": ["string", "null"]},
            },
            "required": ["name", "nip", "address"],
            "additionalProperties": False,
        },
        "totals": {
            "type": "object",
            "properties": {
                "net": {"type": ["number", "null"]},
                "vat": {"type": ["number", "null"]},
                "gross": {"type": ["number", "null"]},
            },
            "required": ["net", "vat", "gross"],
            "additionalProperties": False,
        },
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price_net": {"type": ["number", "null"]},
                    "vat_rate": {"type": ["number", "null"], "description": "percentage, e.g. 23"},
                    "net": {"type": ["number", "null"]},
                    "vat": {"type": ["number", "null"]},
                    "gross": {"type": ["number", "null"]},
                },
                "required": [
                    "description",
                    "quantity",
                    "unit_price_net",
                    "vat_rate",
                    "net",
                    "vat",
                    "gross",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "invoice_number",
        "issue_date",
        "due_date",
        "sale_date",
        "currency",
        "seller",
        "buyer",
        "totals",
        "line_items",
    ],
    "additionalProperties": False,
}


class InvoiceExtractionInput(BaseModel):
    mime_type: str = Field(..., description="application/pdf | image/png | image/jpeg | image/webp")
    data_b64: str = Field(..., min_length=1)
    pages_per_chunk: int = Field(default=_DEFAULT_PAGES_PER_CHUNK, ge=1, le=20)
    model: str | None = None


class InvoiceExtractionOutput(BaseModel):
    invoice: dict[str, Any]
    pages_processed: int
    chunks_processed: int
    usage_total_tokens: int
    model_used: str


def _proxy_key() -> str:
    key = os.environ.get(_LLM_PROXY_KEY_ENV)
    if not key:
        raise ApplicationError(
            f"Missing {_LLM_PROXY_KEY_ENV} env var",
            type="AuthError",
            non_retryable=True,
        )
    return key


async def _call_vision(
    client: httpx.AsyncClient,
    attachments: list[dict[str, str]],
    model: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "system_prompt": _SYSTEM_PROMPT,
        "user_prompt": "Wyodrebnij dane faktury zgodnie ze schema.",
        "attachments": attachments,
        "response_schema": _INVOICE_SCHEMA,
        "temperature": 0.0,
        "max_tokens": 4096,
    }
    if model:
        body["model"] = model

    resp = await client.post(
        f"{_LLM_PROXY_BASE}/api/v1/vision",
        headers={"X-Internal-Key": _proxy_key(), "Content-Type": "application/json"},
        json=body,
    )
    if resp.status_code in (401, 403):
        raise ApplicationError(resp.text, type="AuthError", non_retryable=True)
    if 400 <= resp.status_code < 500:
        raise ApplicationError(resp.text, type="ValidationError", non_retryable=True)
    if resp.status_code >= 500:
        raise ApplicationError(resp.text, type="IntegrationError", non_retryable=False)
    return resp.json()


def _merge_invoices(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """First non-null wins for header fields; line_items are concatenated."""
    if not parts:
        return {}
    merged: dict[str, Any] = {}
    header_keys = {
        "invoice_number",
        "issue_date",
        "due_date",
        "sale_date",
        "currency",
        "seller",
        "buyer",
        "totals",
    }
    for key in header_keys:
        for p in parts:
            value = p.get(key)
            if value not in (None, "", {}):
                merged[key] = value
                break
        merged.setdefault(key, parts[0].get(key))
    line_items: list[Any] = []
    for p in parts:
        items = p.get("line_items")
        if isinstance(items, list):
            line_items.extend(items)
    merged["line_items"] = line_items
    return merged


@activity.defn(name="invoice_extraction")
async def invoice_extraction(payload: dict[str, Any]) -> dict[str, Any]:
    safe_heartbeat("started")
    parsed = InvoiceExtractionInput.model_validate(payload)

    if parsed.mime_type == "application/pdf":
        # Anthropic vision via LiteLLM/OpenAI-compat accepts only image/* —
        # render each PDF page to PNG and ship as image attachments.
        pdf_bytes = base64.b64decode(parsed.data_b64)
        page_count = count_pages(pdf_bytes)
        page_pngs = render_pages_to_png(pdf_bytes, dpi=150)
        # Chunk pages into requests of `pages_per_chunk` images each.
        attachments_per_chunk: list[list[dict[str, str]]] = []
        for start in range(0, len(page_pngs), parsed.pages_per_chunk):
            chunk = page_pngs[start : start + parsed.pages_per_chunk]
            attachments_per_chunk.append(
                [
                    {"type": "image/png", "data_b64": base64.b64encode(png).decode("ascii")}
                    for png in chunk
                ]
            )
    elif parsed.mime_type in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        page_count = 1
        attachments_per_chunk = [[{"type": parsed.mime_type, "data_b64": parsed.data_b64}]]
    else:
        raise ApplicationError(
            f"unsupported mime_type: {parsed.mime_type}",
            type="ValidationError",
            non_retryable=True,
        )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            responses: list[dict[str, Any]] = []
            for chunk_idx, attachment_chunk in enumerate(attachments_per_chunk):
                safe_heartbeat("processing_chunk", chunk=chunk_idx)
                responses.append(await _call_vision(client, attachment_chunk, parsed.model))
    except httpx.TimeoutException as exc:
        raise ApplicationError(str(exc), type="TimeoutError", non_retryable=False) from exc
    except httpx.RequestError as exc:
        raise ApplicationError(str(exc), type="IntegrationError", non_retryable=False) from exc

    chunk_invoices = [r.get("parsed_json") or {} for r in responses]
    if not all(isinstance(ci, dict) for ci in chunk_invoices):
        raise ApplicationError(
            "llm-proxy returned non-object parsed_json for one of the chunks",
            type="IntegrationError",
            non_retryable=False,
        )
    merged = _merge_invoices(chunk_invoices)

    total_tokens = sum(int(r.get("usage", {}).get("total_tokens", 0)) for r in responses)
    model_used = responses[0].get("model", "unknown") if responses else "unknown"

    safe_heartbeat("completed")
    return InvoiceExtractionOutput(
        invoice=merged,
        pages_processed=page_count,
        chunks_processed=len(attachments_per_chunk),
        usage_total_tokens=total_tokens,
        model_used=model_used,
    ).model_dump()


TOOL_MANIFEST: dict[str, Any] = {
    "name": "invoice_extraction",
    "operation": "invoice_extraction",
    "input_schema": InvoiceExtractionInput.model_json_schema(),
    "output_schema": InvoiceExtractionOutput.model_json_schema(),
    "errors": [
        {"type": "ValidationError", "is_base": True, "retryable": False},
        {"type": "AuthError", "is_base": True, "retryable": False},
        {"type": "TimeoutError", "is_base": True, "retryable": True},
        {"type": "IntegrationError", "is_base": True, "retryable": True},
    ],
    "default_retry_profile": "default_retry",
    "default_timeout_profile": "default_timeout",
    "idempotent": True,
}
