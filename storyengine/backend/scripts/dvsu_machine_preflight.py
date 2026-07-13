"""No-spend DVsU one-machine readiness audit.

This checks the saved research card and raw source package for one locked
machine using the same deterministic gates as StoryEngine preview readiness.
It does not call providers, write database rows, mutate scripts, or advance
video status.

Examples:
  python3 scripts/dvsu_machine_preflight.py --video-id fc73860c-a9af-444f-95a5-7f86d60503e0 --machine "Boeing XB-15"
  python3 scripts/dvsu_machine_preflight.py --video-json /tmp/video.json --machine "Boeing XB-15" --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
except Exception:
    pass

import pipeline_executor as pe  # noqa: E402


def _json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _source_package_summary(package: Any, machine: str) -> dict[str, Any]:
    if not isinstance(package, dict):
        return {
            "found": False,
            "candidate_excerpt_count": 0,
            "machine_matching_excerpt_count": 0,
            "source_url_count": 0,
            "missing_capture_method_count": 0,
            "missing_source_selection_count": 0,
            "capture_methods": [],
        }
    candidates = [
        item for item in (package.get("candidate_excerpts") or [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    matching = [
        item for item in candidates
        if pe._mentions_machine(str(item.get("text") or ""), machine)
    ] if machine else candidates
    return {
        "found": True,
        "machine": package.get("machine"),
        "machine_key": package.get("machine_key"),
        "passed": package.get("passed"),
        "candidate_excerpt_count": len(candidates),
        "machine_matching_excerpt_count": len(matching),
        "source_url_count": len({
            str(item.get("source_url") or "").strip()
            for item in matching
            if str(item.get("source_url") or "").strip()
        }),
        "missing_capture_method_count": sum(
            1 for item in matching if not str(item.get("source_capture_method") or "").strip()
        ),
        "missing_source_selection_count": sum(
            1 for item in matching if not isinstance(item.get("source_variant_selection"), dict)
        ),
        "capture_methods": sorted({
            str(item.get("source_capture_method") or "").strip()
            for item in matching
            if str(item.get("source_capture_method") or "").strip()
        }),
    }


def build_preflight_report(video: dict[str, Any], machine: str) -> dict[str, Any]:
    payload = _json_field(video.get("research_payload") or {})
    if not isinstance(payload, dict):
        return {
            "status": "failed",
            "ready": False,
            "machine": machine,
            "summary": "Research payload is missing or invalid.",
            "warnings": ["Research payload is missing or invalid."],
            "next_action": "fix_research_payload",
        }
    video_for_gate = dict(video)
    video_for_gate["research_payload"] = payload
    roster = pe._machine_documentary_hold_roster(video_for_gate)
    if not roster:
        return {
            "status": "failed",
            "ready": False,
            "machine": machine,
            "summary": "No locked DVsU static-docu machine roster found.",
            "warnings": ["No locked DVsU static-docu machine roster found."],
            "next_action": "run_or_fix_roster_research",
        }
    matched = pe._locked_roster_item_for_machine(roster, machine)
    if not matched:
        return {
            "status": "failed",
            "ready": False,
            "machine": machine,
            "summary": f"Machine is not in the locked roster: {machine}",
            "warnings": [f"Machine is not in the locked roster: {machine}"],
            "next_action": "select_locked_roster_machine",
            "roster_count": len(roster),
            "first_machine": roster[0] if roster else None,
        }
    card = pe._research_card_for_machine(payload, matched)
    package = pe._verified_source_package_for_machine(payload, matched)
    if card is None:
        warnings = [f"Script-hold requires a saved research card for locked machine: {matched}"]
    else:
        warnings = pe._research_card_contract_warnings(
            matched,
            card,
            package,
            require_source_package=True,
        )
    ready = not warnings
    return {
        "status": "completed" if ready else "needs_review",
        "ready": ready,
        "video_id": video.get("id"),
        "video_title": video.get("video_title") or video.get("headline"),
        "video_status": video.get("status"),
        "render_mode": video.get("render_mode"),
        "machine": matched,
        "scene": roster.index(matched) + 1,
        "roster_count": len(roster),
        "card_found": card is not None,
        "evidence_segment_count": len(card.get("evidence_segments") or []) if isinstance(card, dict) else 0,
        "source_package": _source_package_summary(package, matched),
        "warnings": warnings,
        "summary": (
            "Machine script preview is ready."
            if ready else
            "Machine is blocked before paid script preview: " + "; ".join(warnings)
        ),
        "next_action": (
            "run_no_spend_readiness_then_script_preview"
            if ready else
            "run_one_machine_research_refresh"
        ),
    }


async def _fetch_video(video_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required unless --video-json is used")
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction(readonly=True):
            if tenant_id:
                row = await conn.fetchrow(
                    """SELECT id, tenant_id, video_title, headline, status, render_mode, research_payload
                       FROM videos
                       WHERE id = $1 AND tenant_id = $2""",
                    video_id,
                    tenant_id,
                )
            else:
                row = await conn.fetchrow(
                    """SELECT id, tenant_id, video_title, headline, status, render_mode, research_payload
                       FROM videos
                       WHERE id = $1""",
                    video_id,
                )
            return dict(row) if row else None
    finally:
        await conn.close()


def _print_human(report: dict[str, Any]) -> None:
    print(f"DVsU machine preflight: {report.get('machine')}")
    print(f"Status: {report.get('status')} | ready={report.get('ready')}")
    if report.get("video_id"):
        print(f"Video: {report.get('video_id')} | {report.get('video_title')}")
    if report.get("roster_count"):
        print(f"Roster: {report.get('roster_count')} machine(s), scene {report.get('scene')}")
    source = report.get("source_package") if isinstance(report.get("source_package"), dict) else {}
    if source:
        print(
            "Raw package: "
            f"{source.get('machine_matching_excerpt_count')}/{source.get('candidate_excerpt_count')} matching excerpt(s), "
            f"{source.get('source_url_count')} source URL(s), "
            f"missing capture={source.get('missing_capture_method_count')}, "
            f"missing selection={source.get('missing_source_selection_count')}"
        )
    warnings = report.get("warnings") or []
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    print(f"Next action: {report.get('next_action')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="No-spend DVsU one-machine readiness audit.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--video-id", help="Video UUID to read from Postgres using DATABASE_URL.")
    source.add_argument("--video-json", help="Path to an exported video JSON object.")
    parser.add_argument("--tenant-id", help="Optional tenant UUID filter for --video-id.")
    parser.add_argument("--machine", required=True, help="Locked machine name or UI label, e.g. Boeing XB-15.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--no-fail", action="store_true", help="Exit 0 even when the machine is not preview-ready.")
    args = parser.parse_args(argv)

    if args.video_json:
        video = json.loads(Path(args.video_json).read_text())
    else:
        video = asyncio.run(_fetch_video(args.video_id, args.tenant_id))
        if video is None:
            raise SystemExit(f"Video not found: {args.video_id}")

    report = build_preflight_report(video, args.machine)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return 0 if args.no_fail or report.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
