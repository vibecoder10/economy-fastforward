"""Production guide — single source for the MCP co-pilot's canonical stage
map (checklist C66; tasks/decisions.md 2026-07-21 "MCP co-pilot must be
PROCESS-AWARE": Ryan's live-driving pain was that the connected agent
skipped environment design and a character-presence check because nothing
taught it the canonical stage order or the current video's gaps).

Feeds TWO things from the ONE ``GUIDE_STAGES`` list below — never
duplicated by hand:
  1. ``build_process_instructions()`` — folded into routes/mcp.py's
     ``initialize`` response instructions (computed fresh on every call, not
     baked into a module constant, so mutating ``GUIDE_STAGES`` changes what
     a NEW session sees without a restart — see that call site's comment).
  2. ``get_production_guide(tenant_id, video_id)`` — the ``get_production_
     guide`` MCP tool's real query logic: per-stage done/in-progress/
     not-started/skipped-by-format state for ONE video, concrete gaps
     (characters missing sheets, environments missing approval, scenes
     missing storyboard grids), and a ``next_step`` recommendation.

Order + format-driven skip derive from status_map.py (the REAL status
machine every pipeline stage advance reads/writes) and pipeline_executor.py
(the REAL character/environment enforcement) — not a hand-typed duplicate:
  - status_map.STAGE_ORDER is the backbone (research/script/voice/images/
    sound/video/thumbnail/render/upload) — the SAME creator-facing stage
    list the Create Video form's on/off switches and status_map.
    normalize_stage_plan/resolve_planned_status use to route status
    advances.
  - "characters" and "environments" are inserted between voice and images
    below. Neither has a ``videos.status`` value of its own (no top-level
    STAGE_ORDER entry) — the REAL enforcement lives in pipeline_executor.py:
    ``_load_character_refs`` (~L7614) and ``_load_environment_refs``
    (~L7645) load the approved refs for generation, and
    ``_environments_ready_gate`` (~L7671, called by every bulk AND
    per-scene storyboard/coverage generation path) HARD-blocks storyboard
    generation until a video's environments are either designed-and-
    approved or explicitly skipped (routes/environments.py's POST /skip).
    Characters are a SOFTER gate: a video with zero designed characters
    skips the check entirely (``_load_character_refs`` returns None), it
    only blocks once a cast exists but isn't approved yet. This exact
    ordering (characters before storyboards, environments hard-gating
    storyboards) is also what frontend/src/lib/next-action.ts's own
    getNextAction walks (its step 4 "design/finish/approve characters"
    before step 6 "storyboard-prompts") — the two independent sources
    agree, which is the cross-check this chunk's tests pin against.
  - "storyboards" and "images" both fold under STAGE_ORDER's single
    "images" bucket for format/plan skip purposes (status_map.STATUS_STAGE
    maps every ready_for_storyboards*/ready_for_images status to "images")
    — a creator/format that disables "images" disables both, and
    characters/environments too (they only exist to feed that bucket).
  - Format-driven skip for a SPECIFIC video: status_map.static_stage_plan
    (render_mode='static_docu' drops video+sound, always returns an
    explicit list) and status_map.parse_stage_plan (a creator's own
    pipeline_stages toggle, or None = full pipeline) are the SAME functions
    routes/videos.py and pipeline_executor.py call to decide what actually
    runs for THIS video — reused verbatim here, never re-derived.

Gap detection reads ONLY already-stored data (video_characters/video_
environments rows, videos.story_bible, scripts.storyboard_*_url,
background_tasks) — no new Claude/API calls, so this tool stays fast/cheap
per the chunk brief. Where a gap would need un-stored computation (e.g.
whether the script prose references a character not yet named in the Story
Bible, before the bible exists), the gap is reported as UNAVAILABLE with a
reason instead of computed.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from database import fetch_all, fetch_one
from actions import video_summary
import status_map

logger = logging.getLogger(__name__)


def _parse_json(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# THE single source: stage order + which STAGE_ORDER "bucket" each guide
# stage belongs to for format/plan skip purposes. Every consumer (the
# instructions text AND the guide tool) reads this list — nothing else.
# ---------------------------------------------------------------------------
GUIDE_STAGES: list[dict[str, str]] = [
    {"key": "research", "label": "Research", "format_bucket": "research"},
    {"key": "script", "label": "Script", "format_bucket": "script"},
    {"key": "voice", "label": "Voice / narration", "format_bucket": "voice"},
    {"key": "characters", "label": "Characters (presence check + sheets)", "format_bucket": "images"},
    {"key": "environments", "label": "Environments (design + approve)", "format_bucket": "images"},
    {"key": "storyboards", "label": "Storyboard grids", "format_bucket": "images"},
    {"key": "images", "label": "Final coverage pictures", "format_bucket": "images"},
    {"key": "sound", "label": "Sound design + effects", "format_bucket": "sound"},
    {"key": "video", "label": "Clips (animate)", "format_bucket": "video"},
    {"key": "thumbnail", "label": "Thumbnail", "format_bucket": "thumbnail"},
    {"key": "render", "label": "Render", "format_bucket": "render"},
    {"key": "upload", "label": "Upload to YouTube", "format_bucket": "upload"},
]
GUIDE_STAGE_KEYS: list[str] = [s["key"] for s in GUIDE_STAGES]


def build_process_instructions() -> str:
    """The process paragraph folded into the MCP ``initialize`` response's
    instructions (routes/mcp.py's ``_dispatch``) — built from
    ``GUIDE_STAGES`` every time it's called, never hand-typed twice. A test
    that monkeypatches ``GUIDE_STAGES`` and re-calls this proves the
    single-source claim (routes/mcp.py's initialize handler must call this
    live, not bake the result into a module constant, for that to hold)."""
    order = " -> ".join(s["label"] for s in GUIDE_STAGES)
    return (
        "Canonical production order (derived from status_map.py's real status "
        "machine plus pipeline_executor.py's character/environment gates — "
        "not a guess): " + order + ". Call get_production_guide(video_id) "
        "BEFORE acting on any video and again after each stage completes — "
        "it reads the video's REAL stage state (done / in_progress / "
        "not_started / skipped_by_format, honoring this video's actual "
        "format and stage plan) plus concrete gaps read from real data "
        "(missing character sheets, unapproved environments — a HARD gate "
        "on storyboard generation, scenes with no storyboard grid yet), and "
        "a next_step recommendation. This is what stops a silent step like "
        "environment design or a character-presence check from getting "
        "skipped the way a driving session skipped them before. Call "
        "get_workspace_info first in a new session to confirm which "
        "channel/tenant you're operating on. Pictures, character sheets, "
        "and environment references come from the get_scene_boards / "
        "get_character_sheets / get_environment_images / get_thumbnail_"
        "image media tools (signed, short-lived URLs) — never invent or "
        "guess a media URL."
    )


def _stage_snapshot(
    key: str, *, video: dict[str, Any], summary: dict[str, Any],
    cast_rows: list[dict[str, Any]], env_rows: list[dict[str, Any]],
    missing_board_scenes: list[int], bible_characters: list[str],
    bible_locations: list[str], bible_present: bool,
    active_task_types: set[str],
) -> tuple[str, str, list[str]]:
    """(state, detail, gaps) for ONE guide stage of ONE video. state is one
    of done / in_progress / not_started (skipped_by_format is decided by the
    caller, before this is even reached, since it doesn't need per-video
    data — see get_production_guide)."""
    scenes = int(summary.get("scenes") or 0)

    if key == "research":
        if video.get("research_payload"):
            return "done", "Research brief exists.", []
        if "research" in active_task_types:
            return "in_progress", "Research is running now.", []
        return "not_started", "No research yet.", []

    if key == "script":
        if scenes > 0:
            return "done", f"{scenes} scene(s) written.", []
        return "not_started", "Script not written yet.", []

    if key == "voice":
        if video.get("skip_voice"):
            return "done", "Voice explicitly skipped for this video.", []
        voiced = int(summary.get("voiced") or 0)
        if scenes > 0 and voiced >= scenes:
            return "done", f"All {scenes} scene(s) voiced.", []
        if voiced > 0:
            return "in_progress", f"{voiced}/{scenes} scene(s) voiced.", []
        if "voice" in active_task_types:
            return "in_progress", "Voice is generating now.", []
        return "not_started", "No narration yet.", []

    if key == "characters":
        gaps: list[str] = []
        if bible_present and bible_characters:
            designed = {(c.get("name") or "").strip().lower() for c in cast_rows}
            missing = [n for n in bible_characters if n.lower() not in designed]
            if missing:
                gaps.append(
                    f"Story Bible names {len(missing)} character(s) with no design yet: "
                    + ", ".join(missing[:5]) + "."
                )
        elif not bible_present:
            gaps.append(
                "Story-bible cross-check unavailable — the bible is built at the "
                "images stage and doesn't exist yet for this video."
            )
        if not cast_rows:
            return "not_started", "No characters designed yet.", gaps
        incomplete = [c for c in cast_rows if not c.get("reference_url")]
        if incomplete:
            gaps.append(f"{len(incomplete)}/{len(cast_rows)} designed character(s) have no portrait yet.")
            return ("in_progress",
                    f"{len(cast_rows) - len(incomplete)}/{len(cast_rows)} character(s) have a portrait.",
                    gaps)
        if not video.get("characters_approved_at"):
            gaps.append(
                f"{len(cast_rows)} character(s) designed but not approved — "
                "pipeline_executor's cast gate blocks visual generation until you approve."
            )
            return "in_progress", "Cast designed, awaiting approval.", gaps
        return "done", f"{len(cast_rows)} character(s) approved.", gaps

    if key == "environments":
        gaps = []
        if bible_present and bible_locations:
            designed = {(e.get("name") or "").strip().lower() for e in env_rows}
            missing = [n for n in bible_locations if n.lower() not in designed]
            if missing:
                gaps.append(
                    f"Story Bible names {len(missing)} location(s) with no design yet: "
                    + ", ".join(missing[:5]) + "."
                )
        elif not bible_present:
            gaps.append(
                "Story-bible cross-check unavailable — the bible is built at the "
                "images stage and doesn't exist yet for this video."
            )
        if not env_rows:
            if video.get("environments_approved_at"):
                return "done", "Explicitly skipped — no distinct locations for this video.", gaps
            gaps.append(
                "No environments designed or skipped yet — pipeline_executor's "
                "_environments_ready_gate BLOCKS storyboard generation until you "
                "design-or-skip AND approve environments."
            )
            return "not_started", "No environments designed yet.", gaps
        incomplete = [e for e in env_rows if not e.get("reference_url")]
        if incomplete:
            gaps.append(f"{len(incomplete)}/{len(env_rows)} designed environment(s) have no reference image yet.")
            return ("in_progress",
                    f"{len(env_rows) - len(incomplete)}/{len(env_rows)} environment(s) have a reference image.",
                    gaps)
        if not video.get("environments_approved_at"):
            gaps.append(
                f"{len(env_rows)} environment(s) designed but not approved — "
                "storyboards are HARD-blocked until you approve them."
            )
            return "in_progress", "Environments designed, awaiting approval.", gaps
        return "done", f"{len(env_rows)} environment(s) approved.", gaps

    if key == "storyboards":
        gaps = []
        if scenes == 0:
            return "not_started", "No scenes yet.", gaps
        boards = int(summary.get("boards") or 0)
        if missing_board_scenes:
            gaps.append(
                f"{len(missing_board_scenes)} scene(s) have no storyboard grid: "
                + ", ".join(str(s) for s in missing_board_scenes[:10]) + "."
            )
        if boards >= scenes and boards > 0 and not missing_board_scenes:
            return "done", f"All {scenes} scene(s) have a storyboard grid.", gaps
        if boards > 0:
            return "in_progress", f"{boards}/{scenes} scene(s) have a storyboard grid.", gaps
        return "not_started", "No storyboard grids yet.", gaps

    if key == "images":
        pics = int(summary.get("pics") or 0)
        if scenes == 0:
            return "not_started", "No scenes yet.", []
        if pics == 0:
            return "not_started", "No final pictures yet.", []
        status_ = video.get("status") or ""
        if status_ in ("ready_for_storyboard_extraction", "ready_for_images"):
            return "in_progress", f"{pics} picture(s) drawn so far.", []
        return "done", f"{pics} picture(s) drawn.", []

    if key == "sound":
        st = video.get("status") or ""
        if status_map.is_at_or_past_stage(st, "ready_for_video_scripts"):
            return "done", "Past the sound stage.", []
        if st == "ready_for_sound_effects":
            return "in_progress", "Sound-effects stage reached.", []
        if "sound" in active_task_types:
            return "in_progress", "Sound design running now.", []
        return "not_started", "Sound stage not reached yet.", []

    if key == "video":
        clips = int(summary.get("clips") or 0)
        pics = int(summary.get("pics") or 0)
        if pics == 0:
            return "not_started", "No pictures to animate yet.", []
        if clips >= pics:
            return "done", f"All {pics} picture(s) animated.", []
        if clips > 0:
            return "in_progress", f"{clips}/{pics} picture(s) animated.", []
        return "not_started", "No clips yet.", []

    if key == "thumbnail":
        if video.get("thumbnail_url"):
            return "done", "Thumbnail set.", []
        if "thumbnail" in active_task_types:
            return "in_progress", "Thumbnail generating now.", []
        return "not_started", "No thumbnail yet.", []

    if key == "render":
        st = video.get("status") or ""
        if st in ("rendered", "uploaded_draft", "uploaded", "published", "done"):
            return "done", "Render complete.", []
        if st == "rendering":
            return "in_progress", "Rendering now.", []
        return "not_started", "Not rendered yet.", []

    if key == "upload":
        if video.get("youtube_url") or video.get("youtube_video_id"):
            return "done", "Uploaded to YouTube.", []
        return "not_started", "Not uploaded yet.", []

    return "not_started", "", []  # pragma: no cover — every GUIDE_STAGES key is handled above


def _recommend_next_step(stages: list[dict[str, Any]]) -> dict[str, Any]:
    """Walk the SAME ordered/stated stages list top to bottom and recommend
    the first thing that isn't done — the same "what's the one next thing"
    question frontend/src/lib/next-action.ts's getNextAction answers for the
    UI banner, derived here from the SAME per-stage state this tool already
    computed (no second, independently-guessed answer)."""
    for s in stages:
        if s["state"] == "skipped_by_format":
            continue
        if s["state"] == "in_progress":
            return {"stage": s["key"], "action": "wait", "reason": f"{s['label']} is in progress: {s['detail']}"}
        if s["state"] == "not_started":
            return {"stage": s["key"], "action": "start", "reason": f"{s['label']} hasn't started: {s['detail']}"}
    return {"stage": "done", "action": "celebrate", "reason": "Every stage in this video's plan is done."}


async def get_production_guide(tenant_id, video_id: str) -> Optional[dict[str, Any]]:
    """Full ordered stage checklist for ONE video, tenant-scoped. Returns
    None when the video doesn't exist for this tenant (caller turns that
    into the tool's error result)."""
    video = await fetch_one(
        "SELECT video_title, status, render_mode, pipeline_stages, skip_voice, "
        "story_locked_at, characters_approved_at, environments_approved_at, "
        "thumbnail_url, youtube_url, youtube_video_id, story_bible, research_payload "
        "FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        return None

    summary = await video_summary(tenant_id, video_id) or {
        "scenes": 0, "boards": 0, "voiced": 0, "pics": 0, "clips": 0, "cast": 0,
    }

    is_static = (video.get("render_mode") or "") == "static_docu"
    plan_raw = status_map.parse_stage_plan(video.get("pipeline_stages"))
    enabled = status_map.static_stage_plan(plan_raw) if is_static else plan_raw  # None = full pipeline

    def bucket_enabled(bucket: str) -> bool:
        return enabled is None or bucket in enabled

    cast_rows = await fetch_all(
        "SELECT id, name, reference_url FROM video_characters "
        "WHERE video_id = $1 AND tenant_id = $2 ORDER BY sort, created_at",
        video_id, tenant_id,
    ) or []
    env_rows = await fetch_all(
        "SELECT id, name, reference_url FROM video_environments "
        "WHERE video_id = $1 AND tenant_id = $2 ORDER BY sort, created_at",
        video_id, tenant_id,
    ) or []
    board_rows = await fetch_all(
        "SELECT scene, storyboard_1_url, storyboard_2_url, storyboard_3_url FROM scripts "
        "WHERE video_id = $1 AND tenant_id = $2 AND scene IS NOT NULL ORDER BY scene",
        video_id, tenant_id,
    ) or []
    active_rows = await fetch_all(
        "SELECT DISTINCT task_type FROM background_tasks WHERE video_id = $1 AND tenant_id = $2 "
        "AND status IN ('pending', 'running')",
        video_id, tenant_id,
    ) or []
    active_task_types = {r["task_type"] for r in active_rows if r.get("task_type")}

    bible = _parse_json(video.get("story_bible")) or {}
    bible_present = bool(bible)
    bible_characters = [
        (c.get("name") or "").strip() for c in (bible.get("characters") or [])
        if isinstance(c, dict) and (c.get("name") or "").strip()
    ]
    bible_locations = [
        (loc.get("id") or "").strip() for loc in (bible.get("locations") or [])
        if isinstance(loc, dict) and (loc.get("id") or "").strip()
    ]
    missing_board_scenes = [
        r["scene"] for r in board_rows
        if not (r.get("storyboard_1_url") or r.get("storyboard_2_url") or r.get("storyboard_3_url"))
    ]

    stages: list[dict[str, Any]] = []
    warnings: list[str] = []
    for spec in GUIDE_STAGES:
        key, bucket = spec["key"], spec["format_bucket"]
        if not bucket_enabled(bucket):
            stages.append({
                "key": key, "label": spec["label"], "state": "skipped_by_format",
                "detail": (
                    "Not part of this video's plan ("
                    + ("static-documentary render — no motion/sound" if is_static else "reduced stage plan")
                    + ")."
                ),
            })
            continue
        state, detail, gaps = _stage_snapshot(
            key, video=video, summary=summary, cast_rows=cast_rows, env_rows=env_rows,
            missing_board_scenes=missing_board_scenes, bible_characters=bible_characters,
            bible_locations=bible_locations, bible_present=bible_present,
            active_task_types=active_task_types,
        )
        entry: dict[str, Any] = {"key": key, "label": spec["label"], "state": state, "detail": detail}
        if gaps:
            entry["gaps"] = gaps
            if state != "done":
                warnings.extend(gaps)
        stages.append(entry)

    return {
        "video_id": str(video_id),
        "title": video.get("video_title"),
        "status": video.get("status"),
        "format": "static_docu" if is_static else "animated",
        "plan": enabled,
        "stages": stages,
        "warnings": warnings,
        "next_step": _recommend_next_step(stages),
    }
