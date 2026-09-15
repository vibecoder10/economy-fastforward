"""Truthful image readiness for a saved static-documentary roster."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from database import fetch_all
from static_docu import _machine_key
from reference_selection import ensure_selection_schema, selection_ready, selection_receipt


def reference_dashboard_state(row: dict | None, latest: dict | None = None, miss: dict | None = None) -> dict:
    """Preserve previews while making the readiness evidence explicit."""
    row = row or {}
    ready = selection_ready(row)
    saved = selection_receipt(row.get("selection_review"))
    review = saved if ready else selection_receipt((latest or {}).get("receipt"))
    result = {"status": "verified" if ready else "missing", "selection_pending": not ready,
              "selection_review": review or None}
    for key in ("hosted_url", "source_url"):
        if row.get(key):
            result[key] = row[key]
    if row.get("reference_kind") == "photo":
        result["kind"] = "photo"
    source_page = (saved.get("selected") or {}).get("source_page")
    if source_page:
        result["source_page_url"] = source_page
    if not ready:
        result["reason_code"] = review.get("reason_code") or (miss or {}).get("reason_code") or "selection_pending"
        result["reason_detail"] = review.get("reason") or (miss or {}).get("reason_detail") or (
            "Photo saved; source identity and view comparison still need review." if row.get("hosted_url")
            else "Gather source-backed photos to compare image choices.")
        result["retryable"] = result["reason_code"] != "never_built"
    return result


def roster_fingerprint(names: list[str]) -> str:
    """Fingerprint the exact ordered display names, never a status receipt."""
    return hashlib.sha256(json.dumps(names, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


async def roster_image_state(video: dict[str, Any], tenant_id: str, *, fetch_rows=fetch_all) -> dict[str, Any]:
    """Read current cache truth for the exact locked roster.

    A cache row is ready only when it is a photo and contains both a hosted
    renderable asset and the source page used to verify it.  Database failures
    deliberately propagate: an unavailable cache cannot prove readiness.
    """
    from pipeline_executor import _machine_documentary_hold_roster_entries

    entries = _machine_documentary_hold_roster_entries(video)
    names = [str(entry.get("name") or "").strip() for entry in entries]
    names = [name for name in names if name]
    fingerprint = roster_fingerprint(names)
    if not names:
        return {"version": 1, "roster_fingerprint": fingerprint, "total": 0,
                "verified": 0, "missing": [], "status": "pending"}
    keys = [_machine_key(name) for name in names]
    await ensure_selection_schema()
    rows = await fetch_rows(
        "SELECT machine_key, hosted_url, source_url, reference_kind, selection_review "
        "FROM static_reference_cache WHERE tenant_id=$1 "
        "AND machine_key = ANY($2::text[]) AND reference_kind='photo'",
        tenant_id, keys,
    )
    valid = {
        str(row.get("machine_key") or "") for row in (rows or [])
        if selection_ready(row)
    }
    missing = [name for name in names if _machine_key(name) not in valid]
    return {"version": 1, "roster_fingerprint": fingerprint, "total": len(names),
            "verified": len(names) - len(missing), "missing": missing,
            "status": "completed" if not missing else "pending"}
