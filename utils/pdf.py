"""PDF utilities for the invoice-extraction flow.

Functions:
- `count_pages(pdf_bytes) -> int`
- `is_text_based(pdf_bytes) -> bool` — heuristic for `text-extractable vs raster scan`
- `split_pdf(pdf_bytes, pages_per_chunk) -> list[bytes]`
- `render_pages_to_png(pdf_bytes, dpi) -> list[bytes]`

`pypdfium2` is the only hard dep (handles parse + render). `pypdf` is used only
when present for text extraction (optional, MVP works without it — `is_text_based`
falls back to a layout-only heuristic).
"""

from __future__ import annotations

import io
from typing import Any

import pypdfium2 as pdfium

_MIN_TEXT_CHARS_PER_PAGE = 20


def count_pages(pdf_bytes: bytes) -> int:
    doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        return len(doc)
    finally:
        doc.close()


def is_text_based(pdf_bytes: bytes) -> bool:
    """Return True when the PDF has an extractable text layer (electronic invoice),
    False when it looks like a raster scan (needs vision OCR)."""
    doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        for i in range(len(doc)):
            page = doc[i]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range()
                finally:
                    textpage.close()
            finally:
                page.close()
            if len(text.strip()) >= _MIN_TEXT_CHARS_PER_PAGE:
                return True
        return False
    finally:
        doc.close()


def split_pdf(pdf_bytes: bytes, pages_per_chunk: int) -> list[bytes]:
    """Split a multi-page PDF into chunks. Each chunk has up to `pages_per_chunk`
    pages and is returned as a fresh PDF byte string."""
    if pages_per_chunk < 1:
        raise ValueError("pages_per_chunk must be >= 1")

    src = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        total = len(src)
        chunks: list[bytes] = []
        for start in range(0, total, pages_per_chunk):
            end = min(start + pages_per_chunk, total)
            dest = pdfium.PdfDocument.new()
            try:
                dest.import_pages(src, list(range(start, end)))
                buf = io.BytesIO()
                dest.save(buf)
                chunks.append(buf.getvalue())
            finally:
                dest.close()
        return chunks
    finally:
        src.close()


def render_pages_to_png(pdf_bytes: bytes, dpi: int = 200) -> list[bytes]:
    """Render every page to a PNG byte string at the requested DPI."""
    scale = dpi / 72.0
    doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        images: list[bytes] = []
        for i in range(len(doc)):
            page = doc[i]
            try:
                bitmap = page.render(scale=scale)
                try:
                    pil = bitmap.to_pil()
                    buf = io.BytesIO()
                    pil.save(buf, format="PNG")
                    images.append(buf.getvalue())
                finally:
                    bitmap.close()
            finally:
                page.close()
        return images
    finally:
        doc.close()


def _ensure_pypdfium_available() -> Any:
    return pdfium
