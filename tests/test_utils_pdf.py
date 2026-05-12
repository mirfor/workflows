"""Tests for `utils.pdf` — PDF inspection + splitting + rendering."""

from __future__ import annotations

import io

import pypdfium2 as pdfium
import pytest

from utils.pdf import count_pages, is_text_based, render_pages_to_png, split_pdf


def _make_blank_pdf(n_pages: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    try:
        for _ in range(n_pages):
            doc.new_page(595, 842)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    finally:
        doc.close()


def test_count_pages_single() -> None:
    pdf = _make_blank_pdf(1)
    assert count_pages(pdf) == 1


def test_count_pages_multi() -> None:
    pdf = _make_blank_pdf(7)
    assert count_pages(pdf) == 7


def test_split_pdf_evenly_divisible() -> None:
    pdf = _make_blank_pdf(6)
    chunks = split_pdf(pdf, pages_per_chunk=2)
    assert len(chunks) == 3
    for chunk in chunks:
        assert count_pages(chunk) == 2


def test_split_pdf_with_remainder() -> None:
    pdf = _make_blank_pdf(7)
    chunks = split_pdf(pdf, pages_per_chunk=3)
    assert [count_pages(c) for c in chunks] == [3, 3, 1]


def test_split_pdf_single_chunk_when_fits() -> None:
    pdf = _make_blank_pdf(3)
    chunks = split_pdf(pdf, pages_per_chunk=10)
    assert len(chunks) == 1
    assert count_pages(chunks[0]) == 3


def test_split_pdf_invalid_chunk_size() -> None:
    pdf = _make_blank_pdf(2)
    with pytest.raises(ValueError):
        split_pdf(pdf, pages_per_chunk=0)


def test_is_text_based_blank_returns_false() -> None:
    pdf = _make_blank_pdf(2)
    assert is_text_based(pdf) is False


def test_render_pages_to_png_returns_one_per_page() -> None:
    pdf = _make_blank_pdf(3)
    images = render_pages_to_png(pdf, dpi=72)
    assert len(images) == 3
    for img in images:
        assert img.startswith(b"\x89PNG")
