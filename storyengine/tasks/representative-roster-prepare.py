#!/usr/bin/env python3
"""Prepare the one authorized video for a named-machine roster rerun.

This tool only archives and clears stale, roster-derived research.  It never
calls a provider or starts the roster endpoint.  Database work is available
only behind ``--apply`` so importing and offline testing remain side-effect
free.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


VIDEO_ID = "44dbf2b2-a27a-47ea-a608-4c31c906be9a"
TENANT_ID = "561b872d-7b73-45e3-9c44-7f30c3566eda"
CLAIM_OWNER = "representative-roster-rerun"
ARCHIVE_MARKER = "representative-roster-rerun-20260916"
DERIVED_FIELDS = {
    "unit_research_cards",
    "machine_research_cards",
    "research_cards",
    "unit_research_hold_validation",
    "machine_raw_source_packages",
    "machine_story_plans",
    "machine_script_briefs",
    "machine_script_previews",
    "roster_images",
    "_dropped_failed_research_card_validations",
    "roster_loop_attempts",
    "roster_surgical_repair_attempts",
}


def _json_safe(value: Any) -> Any:
    """Return a deep JSON-compatible copy, including asyncpg datetime values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    # UUID and asyncpg scalar types have stable string representations.
    if value is None or isinstance(value, (str, int, float, bool)):
        return copy.deepcopy(value)
    return str(value)


def _archive_marker_exists(payload: dict) -> bool:
    return any(
        isinstance(item, dict) and item.get("marker") == ARCHIVE_MARKER
        for item in (payload.get("roster_selection_history") or [])
    )


def prepare_payload(payload: dict, compact_rows: list[dict], timestamp: Any) -> dict:
    """Purely archive current evidence and make the saved roster selectable again.

    The old roster stays active as the source-candidate list consumed by the
    normal Roster stage; only derived detailed-research state is removed.
    """
    if not isinstance(payload, dict):
        raise ValueError("research_payload must be an object")
    if _archive_marker_exists(payload):
        raise ValueError("representative roster archive marker already exists")

    result = copy.deepcopy(payload)
    history = result.get("roster_selection_history")
    if history is None:
        history = []
    if not isinstance(history, list):
        raise ValueError("roster_selection_history must be a list when present")

    archived_payload = copy.deepcopy(payload)
    archived_payload.pop("roster_selection_history", None)
    history.append({
        "marker": ARCHIVE_MARKER,
        "saved_at": _json_safe(timestamp),
        "payload": _json_safe(archived_payload),
        "compact_machine_research_cards": _json_safe(compact_rows),
    })
    result["roster_selection_history"] = history

    for field in DERIVED_FIELDS:
        result.pop(field, None)
    result.pop("independent_selection_audit", None)
    selection = copy.deepcopy(result.get("roster_selection"))
    if not isinstance(selection, dict):
        selection = {}
    selection.pop("independent_audit", None)
    selection.update({
        "status": "needs_review",
        "reason": "Explicit user-authorized representative roster rerun after one_named_machine_per_class_v1",
    })
    result["roster_selection"] = selection
    result["research_phase"] = "roster_selection"
    result["unit_roster_validation"] = {
        "passed": False,
        "hard_warnings": ["Explicit user-authorized representative roster rerun requires a fresh independent selection audit"],
        "warnings": ["Explicit user-authorized representative roster rerun requires a fresh independent selection audit"],
        "complete_title": True,
    }
    return result


def _display_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("title") or item.get("designation") or "").strip()
    return str(item or "").strip()


def _assert_video_is_eligible(video: dict) -> dict:
    if not isinstance(video, dict):
        raise RuntimeError("target video was not found")
    if video.get("deleted_at") is not None:
        raise RuntimeError("target video is deleted")
    if video.get("render_mode") != "static_docu":
        raise RuntimeError("target video is not static_docu")
    if video.get("status") not in {"idea_logged", "approved"}:
        raise RuntimeError("target video is already at a later pipeline status")
    payload = video.get("research_payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise RuntimeError("target video has no object research payload")
    roster = payload.get("unit_roster")
    recommended = payload.get("recommended_final_roster")
    if not isinstance(roster, list) or len(roster) != 20:
        raise RuntimeError("target video does not have the required 20-entry roster")
    if not isinstance(recommended, list) or len(recommended) != 20:
        raise RuntimeError("target video does not have the required 20-entry recommended roster")
    identities = [
        " ".join(str(row.get(key) or "").strip() for key in ("designation", "name"))
        if isinstance(row, dict) else _display_name(row)
        for row in roster
    ]
    if any(not identity.strip() for identity in identities):
        raise RuntimeError("target video roster contains a blank identity")
    range_pattern = re.compile(r"\b(?:through|to)\b|\d\s*[-–—]\s*(?:[A-Za-z]+-?)?\d", re.I)
    if not any(
        isinstance(row, dict) and range_pattern.search(str(row.get("designation") or ""))
        for row in roster
    ):
        raise RuntimeError("target video is not the expected legacy range roster")
    if _archive_marker_exists(payload):
        raise RuntimeError("representative roster archive marker already exists")
    return payload


def _affected_count(tag: Any) -> int:
    try:
        return int(str(tag).split()[-1])
    except (TypeError, ValueError, IndexError) as exc:
        raise RuntimeError(f"unreadable database write result: {tag!r}") from exc


async def apply() -> dict:
    """Run the one transactional archive operation.  Does not rerun Roster."""
    # The deployed service reads this project-level file.  Loading it only in
    # the explicit production path keeps the pure helper and offline tests
    # independent of credentials and provider configuration.
    from dotenv import load_dotenv
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    backend_path = str(project_root / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    import database
    import generation_claims

    claimed = False
    pool = await database.get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                claimed = await generation_claims.acquire_conn(
                    conn, TENANT_ID, VIDEO_ID, "main", CLAIM_OWNER
                )
                if not claimed:
                    raise RuntimeError("target video has active claimed work")
                active = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM background_tasks WHERE tenant_id=$1 AND video_id=$2 "
                    "AND status IN ('pending','running'))", TENANT_ID, VIDEO_ID,
                )
                if active:
                    raise RuntimeError("target video has active pending or running work")
                has_scripts = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM scripts WHERE tenant_id=$1 AND video_id=$2)",
                    TENANT_ID, VIDEO_ID,
                )
                if has_scripts:
                    raise RuntimeError("target video has saved scripts")
                video = await conn.fetchrow(
                    "SELECT id, tenant_id, status, render_mode, deleted_at, research_payload "
                    "FROM videos WHERE id=$1 AND tenant_id=$2 FOR UPDATE", VIDEO_ID, TENANT_ID,
                )
                payload = _assert_video_is_eligible(dict(video) if video else None)
                compact_rows = [dict(row) for row in await conn.fetch(
                    "SELECT * "
                    "FROM machine_research_cards WHERE tenant_id=$1 AND video_id=$2 ORDER BY roster_index",
                    TENANT_ID, VIDEO_ID,
                )]
                prepared = prepare_payload(payload, compact_rows, datetime.now(timezone.utc))
                updated = await conn.execute(
                    "UPDATE videos SET research_payload=$1::jsonb, updated_at=now() WHERE id=$2 AND tenant_id=$3",
                    json.dumps(prepared), VIDEO_ID, TENANT_ID,
                )
                if _affected_count(updated) != 1:
                    raise RuntimeError("archive update did not affect exactly one video")
                deleted = await conn.execute(
                    "DELETE FROM machine_research_cards WHERE tenant_id=$1 AND video_id=$2",
                    TENANT_ID, VIDEO_ID,
                )
                if _affected_count(deleted) != len(compact_rows):
                    raise RuntimeError("compact research archive delete count did not match snapshot")
                readback = await conn.fetchrow(
                    "SELECT research_payload FROM videos WHERE id=$1 AND tenant_id=$2", VIDEO_ID, TENANT_ID,
                )
                readback_payload = (dict(readback).get("research_payload") if readback else None)
                if isinstance(readback_payload, str):
                    readback_payload = json.loads(readback_payload)
                if not isinstance(readback_payload, dict) or not _archive_marker_exists(readback_payload):
                    raise RuntimeError("archive readback did not contain the representative marker")
                archive = readback_payload["roster_selection_history"][-1]
                expected_archived_payload = copy.deepcopy(payload)
                expected_archived_payload.pop("roster_selection_history", None)
                if archive.get("payload") != _json_safe(expected_archived_payload):
                    raise RuntimeError("archive readback payload differs from the pre-update payload")
                if archive.get("compact_machine_research_cards") != _json_safe(compact_rows):
                    raise RuntimeError("archive readback compact rows differ from snapshot")
        return {"video_id": VIDEO_ID, "archived_compact_rows": len(compact_rows), "status": "prepared"}
    finally:
        if claimed:
            # release_owned is harmless after a rolled-back transaction and cannot
            # delete a replacement claim owned by another operation.
            await generation_claims.release_owned(TENANT_ID, VIDEO_ID, "main", CLAIM_OWNER)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the exact production archive transaction")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"status": "dry_run_only", "message": "Pass --apply to run the prepared archive transaction."}))
        return 0
    receipt = asyncio.run(apply())
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
