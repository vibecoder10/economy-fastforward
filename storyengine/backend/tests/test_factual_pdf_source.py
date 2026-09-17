from pathlib import Path
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import factual_pdf_source as source
import factual_source_search as discovery


def test_requested_pages_default_range_and_strict_fragment_handling():
    assert source.requested_pdf_pages("https://archive.example/report.pdf", 12) == list(range(8))
    assert source.requested_pdf_pages("https://archive.example/report.pdf#page=2-4", 12) == [1, 2, 3]
    assert source.requested_pdf_pages("https://archive.example/report.pdf#page=1-8", 12) == list(range(8))
    for fragment in ("#page=0", "#page=-1", "#page=4-3", "#page=1-9", "#page=13", "#section=page=2"):
        assert source.requested_pdf_pages("https://archive.example/report.pdf" + fragment, 12) == []


def test_pdf_detection_uses_mime_or_url_path_not_query_text():
    assert source.is_pdf_source("https://archive.example/document", "application/pdf; charset=binary")
    assert source.is_pdf_source("https://archive.example/document.PDF?download=1")
    assert not source.is_pdf_source("https://archive.example/download?format=.pdf", "text/html")


class _Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class _Reader:
    def __init__(self, _stream):
        self.pages = [_Page("first\n page"), _Page("second\tpage"), _Page("third page")]


def test_extracts_only_requested_pages_and_normalizes_per_page(monkeypatch):
    monkeypatch.setattr(source, "PdfReader", _Reader)
    assert source.extract_pdf_source(b"fixture", "https://archive.example/report.pdf#page=2-3") == "second page\n\nthird page"
    assert source.extract_pdf_source(b"fixture", "https://archive.example/report.pdf#page=0") == ""


def test_overlong_selected_page_is_rejected(monkeypatch):
    monkeypatch.setattr(source, "PdfReader", lambda _stream: type("R", (), {"pages": [_Page("x" * 60_001)]})())
    assert source.extract_pdf_source(b"fixture", "https://archive.example/report.pdf#page=1") == ""


def test_discovery_preserves_pdf_locator_and_rejects_invalid_or_conflicting_metadata():
    rows = [
        {"title": "valid", "exact_source_url": "https://archive.example/report.pdf?download=1", "pdf_page": 77},
        {"title": "invalid", "exact_source_url": "https://archive.example/other.pdf", "pdf_page": 0},
        {"title": "conflict", "exact_source_url": "https://archive.example/conflict.pdf#page=4", "pdf_page": 5},
        {"title": "preserved", "exact_source_url": "https://archive.example/preserved.pdf#page=6", "pdf_page": 6},
    ]
    response = httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(rows)}}],
        "credits_consumed": 0,
    })
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    leads, _ = asyncio.run(discovery.discover_sources(client, "test-key", "Title", "Machine"))
    assert [lead["url"] for lead in leads] == [
        "https://archive.example/report.pdf?download=1#page=77",
        "https://archive.example/preserved.pdf#page=6",
    ]


def test_captured_holland_page_77_isolated_from_default_pages():
    pdf = Path(__file__).parents[2] / "docs/holland-brief-2026-09-16/congress-1901.pdf"
    if not pdf.exists():
        pytest.skip("captured Holland PDF fixture is not present")
    content = pdf.read_bytes()
    page_77 = source.extract_pdf_source(content, "https://example.gov/congress-1901.pdf#page=77")
    first_pages = source.extract_pdf_source(content, "https://example.gov/congress-1901.pdf")
    assert "harbor" in page_77.lower() or "coast" in page_77.lower()
    assert "coast defense" not in first_pages.lower()
