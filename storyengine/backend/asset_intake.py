"""Parse files dropped into the chat (the "drop it in the chat" intake layer).

Pure functions, no I/O beyond the bytes handed in: detect what a file is, pull
the useful content out of it (CSV rows, PDF text), and produce a one-line
summary the chat producer can read. Every parser is fail-soft — a file we can't
read still becomes a stored asset with an honest "couldn't read it" summary,
never an exception out of the upload endpoint.

Destinations (later phases) decide what to DO with an asset; this module only
answers "what is this and what's in it".
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Caps: keep chat_assets rows chat-sized, not data-warehouse-sized.
MAX_CSV_ROWS = 200
MAX_TEXT_CHARS = 60_000

_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
_TEXT_EXTS = {"txt", "md", "text"}
# Header names that smell like a video-title column, best first.
_TITLE_HEADER_RE = re.compile(r"title|video|topic|idea|name", re.I)


def _ext(filename: Optional[str]) -> str:
    return (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""


def detect_kind(filename: Optional[str], content_type: Optional[str]) -> str:
    """'csv' | 'pdf' | 'image' | 'text' — extension first (browsers lie less
    about names than MIME types for drag-dropped files), MIME as backstop."""
    ext = _ext(filename)
    ct = (content_type or "").lower()
    if ext == "csv" or "csv" in ct:
        return "csv"
    if ext == "pdf" or ct == "application/pdf":
        return "pdf"
    if ext in _IMAGE_EXTS or ct.startswith("image/"):
        return "image"
    if ext in _TEXT_EXTS or ct.startswith("text/"):
        return "text"
    # Unknown: treat as text if it decodes cleanly, else image-ish blob -> text
    return "text"


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return ""


def parse_csv(data: bytes) -> dict[str, Any]:
    """{headers, rows, n_rows, title_column, ambiguous}. `rows` is a list of
    dicts (header -> value) capped at MAX_CSV_ROWS; `title_column` is our best
    guess at which column holds video titles; `ambiguous` means a filing op
    must ask the creator which column to use rather than guessing."""
    text = _decode(data)
    if not text.strip():
        return {"headers": [], "rows": [], "n_rows": 0, "title_column": None, "ambiguous": False}
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        has_header = True
    raw = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not raw:
        return {"headers": [], "rows": [], "n_rows": 0, "title_column": None, "ambiguous": False}

    n_cols = max(len(r) for r in raw)
    if has_header and len(raw) > 1:
        headers = [(h.strip() or f"column_{i + 1}") for i, h in enumerate(raw[0])]
        body = raw[1:]
    else:
        headers = [f"column_{i + 1}" for i in range(n_cols)]
        body = raw
    rows = [
        {headers[i]: (r[i].strip() if i < len(r) else "") for i in range(len(headers))}
        for r in body[:MAX_CSV_ROWS]
    ]

    # Title-column guess: a single column IS the list; otherwise match headers.
    title_column, ambiguous = None, False
    if len(headers) == 1:
        title_column = headers[0]
    else:
        matches = [h for h in headers if _TITLE_HEADER_RE.search(h)]
        if len(matches) == 1:
            title_column = matches[0]
        else:
            title_column = matches[0] if matches else None
            ambiguous = True  # multiple candidates or none — ask, don't guess

    return {
        "headers": headers,
        "rows": rows,
        "n_rows": len(body),
        "title_column": title_column,
        "ambiguous": ambiguous,
    }


def parse_pdf(data: bytes) -> str:
    """Extract text from a PDF, '' on any failure (scanned/design-heavy PDFs
    legitimately yield nothing — the caller words the summary honestly)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 — one bad page shouldn't kill the doc
                pages.append("")
        return "\n\n".join(pages).strip()[:MAX_TEXT_CHARS]
    except Exception as e:  # noqa: BLE001
        logger.warning("asset_intake: pdf extraction failed: %s", e)
        return ""


def parse_text(data: bytes) -> str:
    return _decode(data).strip()[:MAX_TEXT_CHARS]


def summarize_asset(
    kind: str,
    filename: Optional[str],
    parsed: Optional[dict[str, Any]],
    parsed_text: Optional[str],
) -> str:
    """Deterministic one-liner for the producer brief (no model call)."""
    name = filename or "file"
    if kind == "csv":
        p = parsed or {}
        n, headers = p.get("n_rows", 0), p.get("headers", [])
        if not n:
            return f'"{name}" — a CSV I couldn\'t read any rows from.'
        cols = ", ".join(headers[:6]) + ("…" if len(headers) > 6 else "")
        rows = p.get("rows") or []
        col = p.get("title_column")
        first = (rows[0].get(col) or next(iter(rows[0].values()), "")) if rows else ""
        looks = f'; looks like a list of video titles (e.g. "{first}")' if col and first else ""
        return f'"{name}" — a CSV with {n} rows, columns: {cols}{looks}.'
    if kind in ("pdf", "text"):
        text = (parsed_text or "").strip()
        if not text:
            return (
                f'"{name}" — a {kind.upper()} I couldn\'t pull readable text out of '
                "(might be scanned or image-based); ask the creator to paste the text."
            )
        words = len(text.split())
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:120]
        return f'"{name}" — a {kind} document, ~{words:,} words, starts: "{first_line}…"'
    if kind == "image":
        return f'"{name}" — an image the creator uploaded.'
    return f'"{name}" — an uploaded file.'
