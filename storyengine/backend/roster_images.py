"""Truthful image readiness for a saved static-documentary roster."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from database import fetch_all
from static_docu import _machine_key


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
    rows = await fetch_rows(
        "SELECT machine_key, hosted_url, source_url, reference_kind "
        "FROM static_reference_cache WHERE tenant_id=$1 "
        "AND machine_key = ANY($2::text[]) AND reference_kind='photo'",
        tenant_id, keys,
    )
    valid = {
        str(row.get("machine_key") or "") for row in (rows or [])
        if str(row.get("reference_kind") or "") == "photo"
        and str(row.get("hosted_url") or "").strip()
        and str(row.get("source_url") or "").strip()
    }
    missing = [name for name in names if _machine_key(name) not in valid]
    return {"version": 1, "roster_fingerprint": fingerprint, "total": len(names),
            "verified": len(names) - len(missing), "missing": missing,
            "status": "completed" if not missing else "pending"}
