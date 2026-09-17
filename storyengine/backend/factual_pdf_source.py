"""Extract bounded, page-specific text from factual PDF sources."""
from __future__ import annotations

from io import BytesIO
import re
from urllib.parse import urlsplit

from pypdf import PdfReader


_PAGE_FRAGMENT = re.compile(r"^page=(\d+)(?:-(\d+))?$")
_MAX_SELECTED_PAGES = 8
_MAX_PAGE_CHARACTERS = 60_000


def requested_pdf_pages(url: str, total: int) -> list[int]:
    """Return requested zero-indexed PDF pages, or an empty list when invalid."""
    if not isinstance(total, int) or total <= 0:
        return []
    fragment = urlsplit(str(url)).fragment
    if not fragment:
        return list(range(min(total, _MAX_SELECTED_PAGES)))
    match = _PAGE_FRAGMENT.fullmatch(fragment)
    if not match:
        return []
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if start <= 0 or end < start or end > total or end - start + 1 > _MAX_SELECTED_PAGES:
        return []
    return list(range(start - 1, end))


def is_pdf_source(url: str, content_type: str | None = None) -> bool:
    """Identify a PDF from its response MIME type or URL path."""
    mime = str(content_type or "").lower()
    return "application/pdf" in mime or urlsplit(str(url)).path.lower().endswith(".pdf")


def extract_pdf_source(content: bytes, url: str) -> str:
    """Return normalized selected-page text; malformed or unsafe captures fail closed."""
    if not isinstance(content, (bytes, bytearray)):
        return ""
    try:
        reader = PdfReader(BytesIO(content))
        pages = requested_pdf_pages(url, len(reader.pages))
        if not pages:
            return ""
        extracted = []
        for index in pages:
            page_text = reader.pages[index].extract_text() or ""
            if len(page_text) > _MAX_PAGE_CHARACTERS:
                return ""
            normalized = re.sub(r"\s+", " ", page_text).strip()
            if len(normalized) > _MAX_PAGE_CHARACTERS:
                return ""
            if normalized:
                extracted.append(normalized)
        return "\n\n".join(extracted)
    except Exception:
        return ""
