"""The shared action layer — one registry for every door (PARITY-PLAN Phase 1).

Everything that can DRIVE a video lives here: the verb registry (what an action
is, what it costs, what must exist first), the honest cost estimator, the compact
video summary they both read, and the two background-step factories (single
action, autobuild chain). Chat (routes/chat.py), the HTTP routes
(routes/pipeline.py), and the future agent brain all call THESE — no door keeps
its own copy of what the pipeline can do.

Extracted verbatim from routes/chat.py (the co-pilot section) so chat, buttons,
and the copilot stay behaviorally identical. Lazy-imports PipelineExecutor and
the routes.pipeline task-status helpers inside the step factories to avoid
circular imports (routes/pipeline.py imports this module at module level).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException

from database import execute, fetch_one
try:
    from database import fetch_all
except ImportError:
    # Several test files stub a bare-bones `database` module in sys.modules
    # (only `execute`/`fetch_one`) before importing actions.py transitively —
    # keep those importable; only the new per-row routed-cost query below
    # actually needs `fetch_all` to be present (and real callers/tests that
    # exercise it monkeypatch this module attribute directly).
    fetch_all = None
from status_map import is_at_or_past_stage

# shared.channel_profile lives in the pipeline package, not the SaaS backend
# (same sys.path pattern as routes/model_registry.py / pipeline_executor.py).
# .resolve() matters here (unlike those two): several lightweight test files
# import actions.py after doing their OWN unresolved
# `os.path.join(os.path.dirname(__file__), "..", "..")` sys.path insert —
# when Python then finds actions.py through THAT sys.path entry, its
# __file__ carries the same un-collapsed ".." segments, and
# Path(__file__).parent×3 on a path like ".../tests/functional/../../actions.py"
# lexically strips segments instead of canceling the ".."s, landing on a
# nonexistent directory instead of the repo root (caught live: C09 broke
# test_autobuild_explicit_research_plan.py / test_producer_kie_fallback.py /
# test_research_skipped_chip.py this way before .resolve() was added).
_PIPELINE_ROOT = Path(__file__).resolve().parent.parent.parent / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

# Single price source (checklist §0.3c / C09): every constant below is a
# straight re-export of shared.channel_profile — the numbers themselves live
# there (next to MODEL_REGISTRY), not here. Kept under these SAME names so
# every existing `from actions import PICTURE_COST` etc. call site (chat.py,
# pipeline_executor.py, scripts/coverage_to_app.py) needs no changes.
from shared.channel_profile import (  # noqa: E402
    CLIP_PRICE_BY_MODEL as CLIP_COST,
    IMAGE_PRICE_BY_MODEL,
    MODEL_REGISTRY,
    PICTURE_PRICE_DEFAULT as PICTURE_COST,
    THUMBNAIL_PRICE as THUMBNAIL_COST,
    VOICE_PRICE_PER_1K_CHARS,
    VOICE_PRICE_FLAT_ESTIMATE as VOICE_COST_ESTIMATE,
    SOUND_PRICE_ESTIMATE as SOUND_COST_ESTIMATE,
    picture_price_for,
    # Single Claude tier source (checklist §3.4 / C35) — same re-export
    # pattern as the cost constants above; the values live in
    # shared.channel_profile, next to MODEL_REGISTRY.
    CLAUDE_MODELS,
    claude_model_for_direct_client,
)
from shared.model_router import resolve_clip_model  # noqa: E402
from image_prompts.engine.camera_moves import get_move  # noqa: E402
from shared.profiles.script import list_profiles as _list_script_profiles  # noqa: E402
from shared.profiles.script import load_script_profile as _load_script_profile  # noqa: E402

logger = logging.getLogger(__name__)

# Same line routes/chat.py's _ALREADY_WORKING_REPLY carries — duplicated here
# (not imported) because actions.py must not import from routes.chat (chat.py
# already imports actions.py at module level; the reverse would be circular).
# Used by C17's draft_pass/finalize runners, which — like the "build" verb —
# acquire their own generation_claims claim explicitly rather than through
# _run_pending_action's generic runner-verb path (which does not).
_ALREADY_WORKING_REPLY = "I'm already working on that — I'll let you know when it's done."

# verb -> how to run it. `calls` = ordered (executor method, passes a scene= kwarg).
# `paid` => hold behind a confirm card in the dock. `needs` = the prerequisite that
# must already exist, or the action is refused politely. `edit` => the verb accepts
# a free-text change applied via apply_followup_edit before the re-run.
ACTIONS: dict[str, dict[str, Any]] = {
    "script":      {"calls": [("run_script", False)], "paid": True, "needs": None, "edit": True,
                    "doing": "writing the script", "label": "Write the script"},
    "characters":  {"calls": [("run_characters", False)], "paid": True, "needs": "scenes",
                    "doing": "designing the cast", "label": "Design the characters"},
    # Unified on the coverage path (GOAL v2 Phase 0): the dock now draws via coverage
    # (the live image generator), not the old 3x3 grid handlers. "storyboards" = the
    # cheap single-sheet preview; "images" = the real per-shot multi-angle pictures.
    "storyboards": {"calls": [("run_storyboard_sheet", True)], "paid": True,
                    "needs": "scenes", "doing": "drawing the storyboards", "label": "Generate storyboards"},
    "images":      {"calls": [("run_coverage_images", True)], "paid": True, "needs": "scenes", "edit": True,
                    "doing": "making the pictures", "label": "Generate the pictures"},
    "voice":       {"calls": [("run_voice", True)], "paid": True, "needs": "scenes",
                    "doing": "recording the voiceover", "label": "Generate the voiceover"},
    "animate":     {"calls": [("run_clip_generation", True)], "paid": True, "needs": "pictures",
                    "doing": "animating", "label": "Animate"},
    # C17 (checklist §1.3 "Draft cheap, finish expensive"): the trust-ladder
    # centerpiece — draft the WHOLE video's clips at the cheapest wired tier
    # in one cheap pass, review, then finalize only the scenes worth it.
    # Both are runner-style (like seo/approve_scene) so each owns its own
    # generation_claims acquire + generation_passes dedup explicitly — see
    # _runner_draft_pass/_runner_finalize.
    "draft_pass":  {"runner": "draft_pass", "paid": True, "needs": "pictures",
                    "doing": "drafting the whole video on the cheap model", "label": "Draft the whole video"},
    "finalize":    {"runner": "finalize", "paid": True, "needs": "pictures",
                    "doing": "finalizing your approved scenes", "label": "Finalize approved scenes"},
    "sound":       {"calls": [("run_sound_prompts", False), ("run_sound_effects", False)], "paid": True,
                    "needs": "pictures", "doing": "designing the sound", "label": "Add sound"},
    "thumbnail":   {"calls": [("run_thumbnail", False)], "paid": True, "needs": None, "edit": True,
                    "doing": "redoing the thumbnail", "label": "Redo the thumbnail"},
    "render":      {"calls": [("run_render", False)], "paid": True, "needs": "clips",
                    "doing": "rendering the final video", "label": "Render the final video"},
    # --- Phase 2 parity verbs: everything a UI button can do, chat can do -----
    "research":    {"calls": [("run_research", False)], "paid": True, "needs": None,
                    "doing": "researching the topic", "label": "Run research"},
    "seo":         {"runner": "seo", "paid": True, "needs": "scenes",
                    "doing": "writing the YouTube SEO", "label": "Write the YouTube SEO"},
    # Free in dollars but it PUBLISHES (unlisted) — paid=True so it always confirms.
    "upload":      {"calls": [("run_upload", False)], "paid": True, "needs": "rendered",
                    "doing": "uploading to YouTube", "label": "Upload to YouTube (unlisted)"},
    "approve_cast": {"runner": "approve_cast", "paid": False, "needs": "cast",
                    "doing": "locking in the cast", "label": "Approve the cast"},
    "approve_environments": {"runner": "approve_environments", "paid": False, "needs": None,
                    "doing": "locking in the locations", "label": "Approve the locations"},
    "skip_environments": {"runner": "skip_environments", "paid": False, "needs": None,
                    "doing": "skipping locations", "label": "Skip locations"},
    "lock":        {"runner": "lock", "paid": False, "needs": None,
                    "doing": "locking the story", "label": "Lock the story"},
    "unlock":      {"runner": "unlock", "paid": False, "needs": None,
                    "doing": "unlocking the story", "label": "Unlock the story"},
    "drive_push":  {"runner": "drive_push", "paid": False, "needs": "scenes",
                    "doing": "sending the script to Google Drive", "label": "Send script to Drive"},
    "drive_sync":  {"runner": "drive_sync", "paid": False, "needs": None,
                    "doing": "pulling the script from Google Drive", "label": "Pull script from Drive"},
    "advance":     {"runner": "advance", "paid": False, "needs": None,
                    "doing": "moving to the next stage", "label": "Skip to the next stage"},
    # C15b (checklist §1.2/UX map director-review loop): approve ONE scene's
    # pictures — scoped to that scene only, unlike approve_cast/approve_environments
    # which gate the whole video. Free (no money moves) and reversible (the status
    # column can always be flipped again), so it never needs a confirm card — the
    # non-paid branch in routes/chat.py runs it straight from the classifier's pick.
    "approve_scene": {"runner": "approve_scene", "paid": False, "needs": "pictures",
                    "doing": "approving this scene", "label": "Approve this scene"},
    # C23 (checklist §2.2, UX map §4): "use a crash zoom on scene 12" — the
    # conversational door onto the SAME assets.camera_preset_id column the
    # Scenes tab's clickable chip/sheet writes (routes/assets.py's PATCH
    # /api/assets/{id}/camera-preset). Free (metadata only, no generation)
    # and reversible (say "auto" to clear it), so — like approve_scene — it
    # runs straight from the classifier's pick, no confirm card.
    "camera_preset": {"runner": "camera_preset", "paid": False, "needs": "pictures",
                    "doing": "setting the camera move", "label": "Set the camera move"},
    # C24 (checklist §2.3, UX map §4): "write it in the investigative style" —
    # the conversational door onto the SAME videos.script_profile column the
    # ScriptVoiceTab's picker writes (PATCH /api/videos/{id}, body
    # {"script_profile": ...}). Free (metadata only — it doesn't itself
    # regenerate the script) and reversible (say "neutral"/"auto" to clear
    # it), so — like camera_preset — it runs straight from the classifier's
    # pick, no confirm card. No `needs` gate: a script voice can be set
    # before OR after the script exists.
    "script_profile": {"runner": "script_profile", "paid": False, "needs": None,
                    "doing": "setting the script voice", "label": "Set the script voice"},
    # meta verb: build auto-runs the pipeline to the next checkpoint — to the pictures
    # if we're before them, else all the way to a finished video. NOT one step.
    "build":       {"calls": None, "paid": True, "needs": None,
                    "doing": "building your video", "label": "Build the video"},
}

# Plain-English reason an action can't run yet (gate keyed by `needs`).
NEEDS_REASON = {
    "scenes":   "the script hasn't been broken into scenes yet — I'd write the script first",
    "pictures": "there are no pictures to work from yet — I'd make the pictures first",
    "clips":    "nothing's been animated yet — I'd animate the scenes first",
    "cast":     "no characters have been designed yet — I'd design the cast first",
    "rendered": "the video hasn't been rendered yet — I'd render it first",
}

# Statuses BEFORE the pictures-review checkpoint — the auto-build keeps advancing
# while the video is in one of these; it stops the moment it reaches
# ready_for_images (pictures generated, awaiting review).
BUILD_TO_PICTURES = {
    "idea_logged", "approved", "ready_for_scripting", "ready_for_voice",
    "ready_for_image_prompts", "ready_for_storyboards",
    "ready_for_storyboard_images", "ready_for_storyboard_extraction",
}
DONE_STATUSES = {"rendered", "uploaded", "uploaded_draft", "done", "published"}
PICTURES_READY_MSG = ("Your pictures are ready — review them, then say “animate it” or “finish it” "
                      "and I'll take it the rest of the way.")

# stage -> (executor methods to re-run in order, the column free-text guidance is
# appended to). Columns are a fixed whitelist, safe to inline in SQL.
FOLLOWUP_STAGES: dict[str, dict[str, Any]] = {
    "script":    {"methods": ["run_script"],                "column": "writer_guidance",      "doing": "rewriting the script"},
    "images":    {"methods": ["run_prompts", "run_images"], "column": "image_style_override", "doing": "remaking the visuals"},
    "thumbnail": {"methods": ["run_thumbnail"],             "column": "thumbnail_prompt",     "doing": "redoing the thumbnail"},
    "render":    {"methods": ["run_render"],                "column": None,                   "doing": "re-rendering the video"},
}


async def apply_followup_edit(tenant_id, video_id, stage: str, edit: dict) -> None:
    """Write the requested change onto the video's stage-guidance column(s) before the
    re-run. Length is structured (video_length_minutes); everything else is appended as
    free-text guidance the stage already reads."""
    cfg = FOLLOWUP_STAGES.get(stage)
    if not cfg:
        return
    mins = edit.get("video_length_minutes")
    if stage == "script" and isinstance(mins, (int, float)) and int(mins) > 0:
        await execute(
            "UPDATE videos SET video_length_minutes = $1, updated_at = now() "
            "WHERE id = $2 AND tenant_id = $3",
            int(mins), video_id, tenant_id,
        )
    col = cfg.get("column")
    note = (edit.get("guidance_append") or "").strip()
    if col and note:
        # col comes from FOLLOWUP_STAGES (our own whitelist), so inlining is safe.
        await execute(
            f"UPDATE videos SET {col} = "
            f"trim(both E'\\n' from coalesce({col}, '') || E'\\n' || $1), updated_at = now() "
            f"WHERE id = $2 AND tenant_id = $3",
            note, video_id, tenant_id,
        )


async def already_uploaded_reply(tenant_id, video_id) -> Optional[str]:
    """C16e (S7-9 follow-up): friendly short-circuit for the "upload" verb when
    the video already has a recorded YouTube id/URL.

    Design choice (mirrors, but deliberately DIFFERS from, C16d's thumbnail
    force-always convention): a chat "upload it"/"publish" turn is much more
    likely to be an accidental double-tap (the same request re-sent, or the
    autobuild finish chain having already uploaded moments earlier) than a
    genuine "make a second draft" intent — unlike "redo the thumbnail", which
    is unambiguous because there is no other way to say "regenerate" in this
    codebase. A duplicate draft is real quota burn (~1,600 of the 10,000/day
    YouTube units) for a mistake that's easy to make and easy to prevent, so
    the safer default is: the explicit verb ALSO skips, same as every other
    caller. `PipelineExecutor.run_upload`'s own `force=` guard (checked again,
    independently, at the executor layer) is the actual money-safety
    backstop; this function only makes the chat reply honest and immediate —
    it fires BEFORE `make_action_step` is even scheduled, so a double-tap
    never even claims the "main" lane or spins up a background task for
    nothing.

    Returns the reply string when the video is already uploaded, else None
    (the caller proceeds with the normal confirm-card/dispatch flow)."""
    row = await fetch_one(
        "SELECT youtube_url, youtube_video_id FROM videos WHERE id=$1 AND tenant_id=$2",
        video_id, tenant_id)
    url = ((row or {}).get("youtube_url") or "").strip()
    yt_id = ((row or {}).get("youtube_video_id") or "").strip()
    if not (url or yt_id):
        return None
    where = f" It's here: {url}" if url else f" (YouTube id {yt_id})."
    return ("This video's already uploaded to YouTube as an unlisted draft." + where +
            " I won't create a second draft from a repeat request — that's the kind "
            "of double-tap that burns real YouTube upload quota. If you genuinely need "
            "a brand-new draft, use the force option on the upload endpoint (not wired "
            "to chat yet — ask your engineer for the ?force=true route).")


async def video_summary(tenant_id, video_id: str) -> Optional[dict[str, Any]]:
    """Compact, current state of the video for the classifier, the gate, the cost
    estimate, and read answers — all from the video row + scripts + assets."""
    v = await fetch_one(
        "SELECT video_title, status, video_length_minutes, video_model, script_validation, render_style "
        "FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not v:
        return None
    sc = await fetch_one(
        "SELECT count(*) FILTER (WHERE scene_text IS NOT NULL) AS scenes, "
        "count(*) FILTER (WHERE storyboard_1_url IS NOT NULL) AS boards, "
        "count(*) FILTER (WHERE voice_over_url IS NOT NULL OR voice_status = 'Done') AS voiced, "
        "max(scene) AS max_scene "
        "FROM scripts WHERE video_id = $1 AND tenant_id = $2 AND scene IS NOT NULL",
        video_id, tenant_id,
    )
    a = await fetch_one(
        "SELECT count(*) FILTER (WHERE image_url IS NOT NULL) AS pics, "
        "count(*) FILTER (WHERE video_clip_url IS NOT NULL) AS clips "
        "FROM assets WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    c = await fetch_one(
        "SELECT count(*) AS n FROM video_characters WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    model = v.get("video_model") or "grok-imagine"
    pics, clips = int(a["pics"] or 0), int(a["clips"] or 0)
    cost = round(pics * PICTURE_COST + clips * CLIP_COST.get(model, 0.10), 2)
    return {
        "title": v.get("video_title") or "Untitled",
        "status": v.get("status") or "unknown",
        "length_min": v.get("video_length_minutes"),
        "model": model,
        "scenes": int(sc["scenes"] or 0),
        "boards": int(sc["boards"] or 0),
        "voiced": int(sc["voiced"] or 0),
        "max_scene": int(sc["max_scene"] or 0),
        "pics": pics,
        "clips": clips,
        "cast": int(c["n"] or 0),
        "spent": cost,
        "validation": str(v.get("script_validation") or "").strip()[:600],
        # C15: the channel-look guardrail state (checklist §1.2/C13b) — additive,
        # read by cost_breakdown/guardrail_note to explain a mixed or single-model
        # routing plan in the copilot's confirm text. None on any pre-C13b video.
        "render_style": v.get("render_style"),
    }


def blocked_reason(verb: str, summary: dict[str, Any]) -> Optional[str]:
    """Return a plain-English reason this action can't run yet, or None if it's allowed."""
    needs = (ACTIONS.get(verb) or {}).get("needs")
    if needs == "scenes" and summary["scenes"] == 0:
        return NEEDS_REASON["scenes"]
    if needs == "pictures" and summary["pics"] == 0:
        return NEEDS_REASON["pictures"]
    if needs == "clips" and summary["clips"] == 0:
        return NEEDS_REASON["clips"]
    if needs == "cast" and summary.get("cast", 0) == 0:
        return NEEDS_REASON["cast"]
    if needs == "rendered" and not is_at_or_past_stage(summary["status"], "rendered"):
        return NEEDS_REASON["rendered"]
    return None


async def _routed_clip_rows(tenant_id, video_id, scene: Optional[int], video_model: str,
                            only_scenes: Optional[list] = None) -> list[dict[str, Any]]:
    """Raw per-row routing data for a video's (or one scene's, or one scene
    LIST's) not-yet-clipped pictures — scene, routed_model, model_override,
    routing_reason. The ONE query ``_routed_clip_costs`` (the money the
    quote sums), ``cost_breakdown`` (C15's itemization of that same sum),
    and C17's draft_pass/finalize estimators all build on, so there is
    exactly one place deciding which rows count and one place reading them —
    no parallel query, no parallel row set.

    Same WHERE clause as the pre-C13 flat count query (image_url IS NOT
    NULL, scoped to `scene` when given) — unchanged by C15. C17 adds
    ``only_scenes`` (mirrors coverage_to_app.generate_coverage_for_video's
    allowlist), used ONLY when `scene` is None — finalize's "just these
    approved scenes" quote."""
    where = "video_id=$1 AND tenant_id=$2 AND image_url IS NOT NULL"
    params = [video_id, tenant_id]
    if scene is not None:
        where += " AND scene=$3"
        params.append(scene)
    elif only_scenes:
        where += " AND scene = ANY($3::int[])"
        params.append(list(only_scenes))
    return await fetch_all(
        f"SELECT scene, routed_model, model_override, routing_reason FROM assets WHERE {where}", *params)


def _resolved_model_id(row: dict[str, Any], video_model: str) -> str:
    """The model_id that will actually generate this row's clip — same
    precedence ``resolve_clip_model`` documents (override > routed > video-
    level default). A tiny wrapper so both money (``_routed_clip_costs``)
    and itemization (``cost_breakdown``) call the identical one-liner."""
    return resolve_clip_model(row.get("routed_model"), video_model, scene_override=row.get("model_override"))


async def _routed_clip_costs(tenant_id, video_id, scene: Optional[int], video_model: str,
                             only_scenes: Optional[list] = None) -> list[float]:
    """Per-row clip prices for a video's (or one scene's, or one scene
    LIST's) not-yet-clipped pictures, resolved through the SAME precedence
    clip generation actually uses (checklist §1.2/C13 money invariant #2 —
    the quote a creator confirms must match what generation will actually
    spend). Each row's price is ``CLIP_PRICE_BY_MODEL[resolve_clip_model(
    routed_model, video_model, scene_override=model_override)]`` — the
    cheapest wired tier for whichever model that row will really run
    through (a C14 manual override winning first, same as generation), not
    one flat video-level price times a count. ``only_scenes`` (C17) is
    finalize's "just these approved scenes" scope."""
    rows = await _routed_clip_rows(tenant_id, video_id, scene, video_model, only_scenes=only_scenes)
    return [
        CLIP_COST.get(_resolved_model_id(r, video_model), CLIP_COST.get(video_model, 0.10))
        for r in rows
    ]


def _premium_reference_price() -> Optional[float]:
    """Cheapest per-clip price among WIRED premium-tier models — the "all
    premium" comparison figure's per-clip rate (checklist §1.2/C15, the
    itemized confirm card's "$4.20 vs $25 all-premium" line). Illustrative
    only: this NEVER prices a real quote (that stays the routed sum above),
    it only answers "what if every shot used the flagship tier instead"."""
    for profile in MODEL_REGISTRY.values():
        if profile.wired and profile.tier == "premium":
            return min(profile.cost_per_clip.values())
    return None


def _draft_tier_model_id() -> Optional[str]:
    """The cheapest WIRED draft-tier model in the registry — data-driven
    (checklist §1.3), the same "cheapest wired X-tier" pattern
    ``_premium_reference_price`` already uses, just returning the model_id
    itself rather than only its price (``draft_pass`` needs to pass this
    into ``run_clip_generation`` as ``force_model_id``). NEVER hardcodes
    "grok-imagine" — if a channel's registry ever adds/removes a
    draft-tier entry, this picks it up automatically. Returns None only if
    NO wired model carries tier="draft" (nothing to draft with)."""
    candidates = [
        (mid, min(profile.cost_per_clip.values()))
        for mid, profile in MODEL_REGISTRY.items()
        if profile.wired and profile.tier == "draft" and profile.cost_per_clip
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[1])[0]


async def _approved_scenes(tenant_id, video_id) -> list[int]:
    """Distinct scene numbers with at least one APPROVED picture (checklist
    §1.2/C15b: `_runner_approve_scene` sets `assets.status='approved'` for
    every row in a scene in one UPDATE, so any approved row in a scene means
    the whole scene is approved). This is `finalize`'s entry set — "regenerate
    ONLY approved scenes' clips"."""
    rows = await fetch_all(
        "SELECT DISTINCT scene FROM assets WHERE video_id=$1 AND tenant_id=$2 "
        "AND status='approved' AND image_url IS NOT NULL AND scene IS NOT NULL ORDER BY scene",
        video_id, tenant_id,
    )
    return [r["scene"] for r in rows]


def _reconcile_rounding(raw: dict[str, float], total: float) -> dict[str, float]:
    """Round each group's raw subtotal to cents, then nudge the largest group
    by any leftover penny so the itemized lines always sum to EXACTLY
    ``total`` (the same number ``estimate_cost`` returns for this quote) —
    independently rounding each group can otherwise drift a cent from
    rounding the whole sum once."""
    rounded = {k: round(v, 2) for k, v in raw.items()}
    drift = round(total - round(sum(rounded.values()), 2), 2)
    if drift and rounded:
        biggest = max(rounded, key=rounded.get)
        rounded[biggest] = round(rounded[biggest] + drift, 2)
    return rounded


def guardrail_note(render_style: Optional[str]) -> str:
    """One sentence naming why the routing plan looks the way it does —
    mirrors ``shared.model_router.route_shot_model``'s own C13b guardrail
    (the channel's declared LOOK gates model choice before scene importance
    does). Reused by the copilot's confirm text (checklist §1.2/C15) so the
    phrasing never drifts from what the router itself is actually doing."""
    style = (render_style or "").strip().lower()
    if style == "animated":
        return "channel is set to Animated, so everything stays on Grok."
    if style == "realistic":
        return "channel is set to Realistic, so shots route across the photoreal lineup."
    if style:
        return f"channel is set to {style.title()}."
    return "no channel look set — using your default model."


async def cost_breakdown(tenant_id, video_id, verb: str, scene: Optional[int],
                          summary: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Per-model/per-tier itemization of an animate/build quote (checklist
    §1.2/C15 — "Scene 12 is your reveal — Veo Quality ($1.25); Grok
    elsewhere. Total $4.20 vs $25 all-premium").

    ONE resolver, no parallel math: groups the EXACT per-row prices
    ``_routed_clip_costs`` already sums for this exact (verb, scene) call —
    same ``_routed_clip_rows`` query, same ``_resolved_model_id`` precedence —
    so ``round(sum(line["subtotal"] for line in lines), 2) == the total
    estimate_cost() returns`` for the identical call, always. Also flags
    which routed rows landed on the premium ("hero") tier, carrying their
    own ``routing_reason`` verbatim (never re-derived) so the copilot can
    name "scene 12, and why" without guessing.

    Returns None when there's nothing real to itemize yet — same guards
    ``estimate_cost``'s animate/build branches use (no shot plan before
    pictures exist; an empty per-scene quote that falls back to a flat
    guess) — callers fall back to the plain cost_text unchanged.

    C17 (checklist §1.3) adds ``draft_pass``/``finalize``, sharing the same
    rows-in/lines-out shape so a single confirm-card renderer (and a single
    "sums to the total" invariant) covers all four verbs:
      - ``draft_pass``: every not-yet-clipped row, priced at the draft-tier
        model REGARDLESS of its routed_model/model_override (the whole
        point of a draft pass) — the itemization will therefore always
        collapse to exactly one line (one model, every row), which is
        itself useful confirm-card information ("14 x Grok Imagine").
      - ``finalize``: ONLY approved-scene rows, each priced at its real
        resolved (override > routed > video-default) tier — the itemization
        looks exactly like an ``animate`` quote, just pre-filtered to the
        approved scene set.
    """
    if verb not in ("animate", "build", "draft_pass", "finalize"):
        return None
    if verb == "build" and (summary["status"] in BUILD_TO_PICTURES or not summary["pics"]):
        return None

    model = summary["model"]
    draft_model = _draft_tier_model_id() if verb == "draft_pass" else None
    if verb == "draft_pass" and not draft_model:
        return None  # no wired draft-tier model — nothing sane to itemize
    if verb == "finalize":
        approved = await _approved_scenes(tenant_id, video_id)
        if not approved:
            return None  # nothing approved yet — estimate_cost's cost=0 branch carries the reply
        rows = await _routed_clip_rows(tenant_id, video_id, None, model, only_scenes=approved)
    else:
        row_scene = scene if verb == "animate" else None
        rows = await _routed_clip_rows(tenant_id, video_id, row_scene, model)
    if not rows:
        return None  # empty-scene guess branch — nothing routed to itemize

    def _resolve(r: dict[str, Any]) -> str:
        # draft_pass forces every row to the draft tier, mirroring
        # run_clip_generation's force_model_id bypass exactly — the quote
        # must price what the run will actually do, not the row's stored
        # (untouched) routed_model/model_override.
        return draft_model if verb == "draft_pass" else _resolved_model_id(r, model)

    raw_subtotal: dict[str, float] = {}
    counts: dict[str, int] = {}
    hero_scenes: list[dict[str, Any]] = []
    raw_prices: list[float] = []
    for r in rows:
        resolved = _resolve(r)
        price = CLIP_COST.get(resolved, CLIP_COST.get(model, 0.10))
        raw_prices.append(price)
        raw_subtotal[resolved] = raw_subtotal.get(resolved, 0.0) + price
        counts[resolved] = counts.get(resolved, 0) + 1
        profile = MODEL_REGISTRY.get(resolved)
        if profile and profile.tier == "premium":
            hero_scenes.append({
                "scene": r.get("scene"),
                "model_id": resolved,
                "display_name": profile.display_name,
                "reason": (r.get("routing_reason") or "").strip() or "routed to the premium tier",
            })

    total = round(sum(raw_prices), 2)  # identical formula to estimate_cost's animate/build branches
    subtotals = _reconcile_rounding(raw_subtotal, total)
    lines = [
        {
            "model_id": mid,
            "display_name": MODEL_REGISTRY[mid].display_name if mid in MODEL_REGISTRY else mid,
            "tier": MODEL_REGISTRY[mid].tier if mid in MODEL_REGISTRY else "standard",
            "count": counts[mid],
            "subtotal": subtotals[mid],
        }
        for mid in raw_subtotal
    ]
    premium_price = _premium_reference_price()
    all_premium_total = round(premium_price * len(rows), 2) if premium_price else None
    # C18 (checklist §1.3 [U]): distinct scene count behind this itemization —
    # GuidedNextStep's "Finalize N approved scenes" / "Draft the whole video"
    # labels and the draft+finalize savings line need N server-computed, never
    # guessed from asset-row counts on the frontend (a scene has multiple rows).
    scene_count = len({r.get("scene") for r in rows if r.get("scene") is not None})

    return {
        "lines": lines,
        "total": total,
        "all_premium_total": all_premium_total,
        "hero_scenes": hero_scenes,
        "scene_count": scene_count,
    }


async def estimate_cost(tenant_id, video_id, verb: str, scene: Optional[int], summary: dict[str, Any]) -> tuple[float, str]:
    """A rough but honest dollar estimate for a paid action, mirroring the page's
    counts. Per-scene actions price just that scene's pictures/clips."""
    model = summary["model"]
    clip = CLIP_COST.get(model, 0.10)
    if verb == "animate":
        costs = await _routed_clip_costs(tenant_id, video_id, scene, model)
        if scene is not None and not costs:
            cost = 4 * clip  # fall back to a small guess — unchanged from pre-C13
        else:
            cost = sum(costs)
    elif verb == "draft_pass":
        # Checklist §1.3: EVERY not-yet-clipped row, priced at the cheapest
        # WIRED draft-tier model — never the row's routed_model/model_override
        # (those recommendations survive a draft pass untouched; see
        # _runner_draft_pass/run_clip_generation's force_model_id). Same
        # rows-in-play as an "animate everything" quote (scene=None), just a
        # uniform price instead of per-row routed prices.
        rows = await _routed_clip_rows(tenant_id, video_id, None, model)
        draft_model = _draft_tier_model_id()
        draft_price = CLIP_COST.get(draft_model, clip) if draft_model else clip
        cost = len(rows) * draft_price
    elif verb == "finalize":
        # Checklist §1.3: ONLY the currently-approved scenes, each at its
        # REAL resolved (override > routed > default) tier — identical money
        # math to an "animate" quote, pre-filtered to the approved set. Zero
        # approved scenes -> "no extra cost" (nothing to finalize yet); the
        # runner replies with a friendly nudge rather than dispatching.
        approved = await _approved_scenes(tenant_id, video_id)
        costs = await _routed_clip_costs(tenant_id, video_id, None, model, only_scenes=approved) if approved else []
        cost = sum(costs)
    elif verb == "images":
        n = summary["pics"] or max(1, summary["scenes"]) * 6  # ~6 shots/scene when none exist yet
        if scene is not None:
            n = 6
        cost = n * PICTURE_COST
    elif verb == "storyboards":
        cost = (1 if scene is not None else max(1, summary["scenes"])) * PICTURE_COST
    elif verb == "voice":
        # Real per-character estimate (ElevenLabs bills per character, not
        # per run — docs/cost-awareness.md) when the script already exists;
        # flat fallback otherwise (e.g. a quote requested before "Write the
        # script" has run). Counts raw scene_text length, not the narrator-
        # only text voice/run.py actually sends (which drops character
        # dialogue lines on a dialogue video) — a defensible slight
        # overestimate for a pre-generation quote, never an underestimate.
        row = await fetch_one(
            "SELECT COALESCE(SUM(length(scene_text)), 0) AS chars FROM scripts "
            "WHERE video_id=$1 AND tenant_id=$2 AND scene_text IS NOT NULL",
            video_id, tenant_id)
        chars = int((row or {}).get("chars") or 0)
        cost = round(chars / 1000 * VOICE_PRICE_PER_1K_CHARS, 2) if chars else VOICE_COST_ESTIMATE
    elif verb == "sound":
        cost = SOUND_COST_ESTIMATE
    elif verb == "thumbnail":
        cost = THUMBNAIL_COST
    elif verb == "script":
        cost = 0.02
    elif verb == "research":
        cost = 0.05
    elif verb == "seo":
        cost = 0.02
    elif verb == "characters":
        # ~$0.03 per 4-view character sheet; use the current cast count or a small default.
        row = await fetch_one(
            "SELECT count(*) AS n FROM video_characters WHERE video_id=$1 AND tenant_id=$2",
            video_id, tenant_id)
        cost = (int((row or {}).get("n") or 0) or 4) * 0.03
    elif verb == "render":
        cost = 0.0
    elif verb == "build":
        # Rough: pictures phase ~= scenes * ~6 shots * PICTURE_COST; finish phase ~= the
        # clips. Scenes unknown on a fresh video -> assume ~5.
        scenes = summary["scenes"] or 5
        if summary["status"] in BUILD_TO_PICTURES:
            cost = scenes * 6 * PICTURE_COST
        elif summary["pics"]:
            # Pictures already exist -> the shot plan (and each row's
            # routed_model) was already computed before those pictures were
            # drawn (storyboard/coverage.py's plan_camera_moves runs BEFORE
            # any frame renders) -> sum the SAME per-row routed prices the
            # "animate" quote above uses, instead of one flat video-level
            # price times a count (checklist §1.2/C13 money invariant #2).
            cost = sum(await _routed_clip_costs(tenant_id, video_id, None, model))
        else:
            # No pictures yet -> no shot plan exists yet -> nothing to route
            # per scene. Money invariant #3: fall back to today's rough
            # flat math rather than invent per-scene numbers that don't
            # exist yet.
            cost = scenes * 6 * clip
    else:
        cost = 0.0
    text = "no extra cost" if cost <= 0 else f"~${cost:.2f}"
    return round(cost, 2), text


async def estimate_plan_cost(video_length_minutes: Optional[float] = None) -> tuple[float, str, int]:
    """The producer's PRE-CREATION quote (checklist C15a — the home Producer's
    "Make it" tap was the one paid path that skipped the quote law: it fires
    ``_handle_approve`` -> ``create_video`` -> an autobuild straight to real
    paid pictures with no cost shown). No video row exists yet at plan time, so
    there's no real ``video_summary()`` to hand ``estimate_cost`` — a shot plan
    only exists after the script is written (same reason ``cost_breakdown``
    returns None pre-plan).

    Orchestrator review (2026-07-18): a flat ~5-scene guess regardless of the
    plan's OWN ``video_length_minutes`` is exactly the shown-price-vs-real-spend
    mismatch this chunk exists to close, in a predictable direction (a 20-30
    min plan would show the same "≈$1.50" a 1-min plan shows, then spend
    several times that). Scene count for a not-yet-scripted video is NOT
    free-form here — it's the SAME formula the live script generator already
    targets, reused verbatim via import (no new ratio invented):
    ``VideoConfig.act_count`` (``skills/video-pipeline/orchestrator/
    pipeline_config.py:53`` — ``max(3, min(6, video_length_minutes // 2)) if
    video_length_minutes >= 3 else 1``). Traced end to end: that same
    ``VideoConfig`` (built from this exact ``video_length_minutes``) is handed
    to ``script_generator.generate_script()``, whose prompt instructs
    "Structure it in {act_count} acts" (``script_generator.py:638/643``);
    ``brief_translator._write_script_records`` then writes exactly ONE row per
    act ("one per act", ``scene_number=act_num``); ``SupabaseAdapter.
    create_script_record`` inserts that row with ``scene=scene_number``
    (``supabase_adapter.py``) — so ``act_count`` IS the real "scenes" number
    ``video_summary()`` later counts and this same ``estimate_cost`` build
    branch prices. (Honest cap: ``act_count`` maxes out at 6 for any video
    >=12 min — a real property of the live formula, not something invented
    here — so a 20-30 min quote scales up to that cap, not further.)

    Hands ``estimate_cost``'s own "build" verb a synthetic summary shaped like
    a fresh, pre-script video (status in ``BUILD_TO_PICTURES``) with
    ``scenes`` set to that derived act count — which routes straight to ITS
    OWN existing pre-pictures math (``cost = scenes * 6 * PICTURE_COST``).
    That is the exact figure the autobuild ``_handle_approve`` kicks off will
    actually be run against once the video exists — no parallel math, no
    hardcoded price. ``tenant_id``/``video_id`` are unused by this branch (no
    DB read happens before pictures exist), so the ``None`` placeholders below
    are safe; ``model`` is unused by this branch too (kept only for
    ``video_summary``-shape parity).

    ``video_length_minutes=None`` (no length picked yet, e.g. a turn before
    the length card resolves) keeps the EXACT pre-existing behavior: a
    ``scenes=0`` synthetic summary, which still routes to ``estimate_cost``'s
    own "scenes or 5" fallback unchanged. Returns ``(cost, cost_text,
    scenes_used)`` — ``scenes_used`` is the actual scene count the estimate
    was based on (the derived act count, or 5 when it fell back), read off
    the SAME ``summary["scenes"] or 5`` expression ``estimate_cost`` itself
    evaluates — so the card text can read "for ~N scenes" without a second,
    independently-computed number."""
    scenes = 0
    if video_length_minutes is not None:
        try:
            from orchestrator.pipeline_config import VideoConfig
            mins = max(1, min(30, int(round(float(video_length_minutes)))))
            scenes = VideoConfig(video_length_minutes=mins).act_count
        except Exception:  # noqa: BLE001 — never block the plan turn over a display quote
            scenes = 0
    summary = {"model": "grok-imagine", "status": "idea_logged", "scenes": scenes, "pics": 0}
    cost, text = await estimate_cost(None, None, "build", None, summary)
    return cost, text, (scenes or 5)


async def ensure_scriptable(tenant_id, video_id) -> None:
    """'Write the script' straight from an idea: skip past research the same
    plan-aware way autobuild does, so the script verb never trips the
    ready_for_scripting status gate on an idea_logged/approved/researching
    video (the creator saying 'no research, just write it' must simply work)."""
    from status_map import parse_stage_plan, resolve_planned_status
    row = await fetch_one(
        "SELECT status, pipeline_stages FROM videos WHERE id=$1 AND tenant_id=$2",
        video_id, tenant_id)
    prev = (row or {}).get("status") or ""
    if prev not in ("idea_logged", "approved", "researching"):
        return
    to_status = resolve_planned_status("ready_for_scripting", parse_stage_plan(row.get("pipeline_stages")))
    await execute("UPDATE videos SET status=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
                  to_status, video_id, tenant_id)
    try:
        await execute(
            "INSERT INTO stage_transitions (video_id, tenant_id, from_status, to_status, triggered_by) "
            "VALUES ($1, $2, $3, $4, 'auto')",
            video_id, tenant_id, prev, to_status)
    except Exception:  # noqa: BLE001
        pass


def make_action_step(tenant_id, video_id: str, calls: list, *, scene: Optional[int] = None,
                     start_msg: str = "On it…", stage: str = "main"):
    """Run an action's executor methods in order, passing scene= to the ones that
    accept it. Same task-status channel as the rest so the page's trackers light
    up. Stops on the first error.

    C16a: `stage` is the generation_claims lane this run's caller already
    acquired (routes/chat.py's _run_pending_action calls
    generation_claims.acquire(tenant_id, video_id, stage_for_verb(verb)) BEFORE
    scheduling this factory's _run — see that call site for the acquire).
    This factory owns the matching release: it happens here, in the SAME
    finally block that already runs on every exit path (success, the
    first-error break, and any raised exception), so the claim can never
    outlive the task body it was taken for.
    """
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status
    import generation_claims

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)
        try:
            if any(name == "run_script" for name, _ in calls):
                try:
                    await ensure_scriptable(tenant_id, video_id)
                except Exception:  # noqa: BLE001
                    pass
            executor = PipelineExecutor(tenant_id)
            result: dict = {}
            for name, takes_scene in calls:
                method = getattr(executor, name, None)
                if method is None:
                    result = {"status": "failed", "error": f"Unknown stage '{name}'"}
                    break
                kwargs = {"scene": scene} if (takes_scene and scene is not None) else {}
                # C16d (S7-3): the "thumbnail" verb (ACTIONS["thumbnail"], label
                # "Redo the thumbnail") is ALWAYS an explicit redo request — never
                # the natural first-time generation — so it must bypass
                # run_thumbnail's skip-if-done guard. Same special-case pattern
                # as the run_script branch above.
                if name == "run_thumbnail":
                    kwargs["force"] = True
                result = await method(video_id, **kwargs) or {}
                if result.get("error"):
                    break
            _set_task_status(video_id, result.get("status", "completed"),
                             result.get("error") or result.get("message"), tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await generation_claims.release(tenant_id, video_id, stage)
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    return _run


def make_autobuild_step(tenant_id, video_id: str, *, target: str = "pictures",
                        start_msg: str = "Building your video…"):
    """Chain the pipeline automatically instead of running one step. target='pictures'
    runs research -> script -> (voice) -> storyboards -> pictures and STOPS at the
    pictures-review checkpoint; target='finish' runs the rest (clips + render) to a
    finished video, auto-passing the review gates. Robust: research failure is
    non-fatal (skips to script), voice is best-effort (no key -> skipped), and the
    loop is hard-capped + stops on no-progress so it can never run away."""
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status
    from status_map import get_next_status_supabase, parse_stage_plan, resolve_planned_status
    import generation_claims

    async def _advance(to_status: str):
        # Honor the video's reduced stage plan: a raw natural-next status here
        # would drag a reduced-plan video into a disabled stage (e.g. a static
        # documentary into sound/animate). Reroute to the next ENABLED stage.
        prow = await fetch_one(
            "SELECT pipeline_stages FROM videos WHERE id=$1 AND tenant_id=$2",
            video_id, tenant_id)
        plan = parse_stage_plan((prow or {}).get("pipeline_stages"))
        to_status = resolve_planned_status(to_status, plan)
        prev = await fetch_one(
            "SELECT status FROM videos WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
        await execute("UPDATE videos SET status=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
                      to_status, video_id, tenant_id)
        # Log a real stage transition so the chat progress card's live SSE updates — a raw
        # status UPDATE alone left the card frozen on an old step while the build moved on.
        try:
            await execute(
                "INSERT INTO stage_transitions (video_id, tenant_id, from_status, to_status, triggered_by) "
                "VALUES ($1, $2, $3, $4, 'auto')",
                video_id, tenant_id, (prev or {}).get("status") or "", to_status)
        except Exception:  # noqa: BLE001
            pass

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)
        try:
            ex = PipelineExecutor(tenant_id)
            # Build-to-pictures skips the voiceover; if we're now finishing, lay it down first
            # (the render needs an audio track). run_voice can nudge the status backwards, so
            # snapshot and restore it. Guarded on missing audio so we never double-charge.
            if target == "finish":
                try:
                    missing = await fetch_one(
                        "SELECT 1 AS x FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
                        "AND voice_over_url IS NULL LIMIT 1", video_id, tenant_id)
                    if missing:
                        snap = await fetch_one(
                            "SELECT status FROM videos WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
                        _set_task_status(video_id, "running", "Recording the voiceover…", tenant_id=tenant_id)
                        await ex.run_voice(video_id)
                        if snap and snap.get("status"):
                            await _advance(snap["status"])
                except Exception:  # noqa: BLE001
                    pass
            last = None
            for _ in range(18):  # hard cap — the pipeline is ~14 stages deep
                video = await ex._get_video(video_id)
                if not video:
                    _set_task_status(video_id, "failed", "Video not found", tenant_id=tenant_id)
                    return
                status = video.get("status")
                if target == "pictures" and status not in BUILD_TO_PICTURES:
                    _set_task_status(video_id, "completed", PICTURES_READY_MSG, tenant_id=tenant_id)
                    return
                if target == "finish" and status in DONE_STATUSES:
                    _set_task_status(video_id, "completed", "Your video is rendered — take a look!", tenant_id=tenant_id)
                    return
                if status == last:  # no progress — never loop forever
                    _set_task_status(video_id, "completed", f"Paused at {status}.", tenant_id=tenant_id)
                    return
                last = status
                # Skip the optional research step — it's slow/flaky (web/YouTube blocks)
                # and the script writes fine from the topic. Go straight to the script;
                # the creator can run research on demand. This was the actual stall.
                # EXCEPTION: static documentaries (client channels built on exact
                # figures) MUST research first — their scripts are written from the
                # verified research payload, and the factual gate depends on it.
                if status in ("idea_logged", "approved"):
                    if (video.get("render_mode") or "") == "static_docu":
                        _set_task_status(video_id, "running",
                                         "Researching the topic (real web search)…",
                                         tenant_id=tenant_id)
                        r = await ex.run_research(video_id) or {}
                        if r.get("status") == "ready_for_scripting":
                            continue
                        # Research failed — a static doc without facts is worse
                        # than no doc; stop instead of writing from thin air.
                        _set_task_status(video_id, "failed",
                                         r.get("error") or "Research failed — can't verify facts for this format.",
                                         tenant_id=tenant_id)
                        return
                    # C06a: an EXPLICIT research request (workflow:"research", or any
                    # custom plan that names "research") must not be silently skipped
                    # by the default-skip below. parse_stage_plan returns None for
                    # "no plan" (the ordinary full pipeline) — that default case keeps
                    # skipping, byte-identical to before. Only a plan that actually
                    # NAMES "research" counts as explicit; a None plan is unrestricted,
                    # not "requested".
                    research_plan = parse_stage_plan(video.get("pipeline_stages"))
                    if research_plan is not None and "research" in research_plan:
                        _set_task_status(video_id, "running",
                                         "Researching the topic (real web search)…",
                                         tenant_id=tenant_id)
                        r = await ex.run_research(video_id) or {}
                        if r.get("status") == "ready_for_scripting":
                            continue
                        # The creator explicitly asked for research — don't fall
                        # through to a from-thin-air script on failure; that would
                        # silently drop the exact thing they asked for.
                        _set_task_status(video_id, "failed",
                                         r.get("error") or "Research failed.",
                                         tenant_id=tenant_id)
                        return
                    # Record the skip so the UI can be honest about it (P0.5 —
                    # users previously had no way to know their video wasn't
                    # researched). Cleared back to FALSE the moment research
                    # actually runs (pipeline_executor.run_research), whether
                    # via the transparency chip's one-tap enable or otherwise.
                    try:
                        await execute(
                            "UPDATE videos SET research_skipped = TRUE WHERE id=$1 AND tenant_id=$2",
                            video_id, tenant_id)
                    except Exception:  # noqa: BLE001 — the build must not fail on this
                        pass
                    await _advance("ready_for_scripting")
                    continue
                # IMAGE PHASE: draw the pictures via the COVERAGE flow — the same path the
                # Scenes-page "pictures" button uses (generate_coverage_for_video). Coverage
                # builds its own cast sheet from the script when no characters are locked
                # (chat auto-builds don't lock a cast), then saves real picture assets.
                # The status-map image stages now also route to coverage (run_coverage_stage,
                # GOAL v2 Phase 0); we call coverage directly here so the chat build controls
                # its own progress updates and stops at the pictures-review checkpoint.
                if status in ("ready_for_image_prompts", "ready_for_storyboards",
                              "ready_for_storyboard_images", "ready_for_storyboard_extraction"):
                    # Satisfy the storyboard gates (env skipped, characters approved) and
                    # write the Story Bible (continuity anchor for the shot directives).
                    await execute(
                        "UPDATE videos SET environments_approved_at = COALESCE(environments_approved_at, now()), "
                        "characters_approved_at = COALESCE(characters_approved_at, now()), "
                        "updated_at = now() WHERE id = $1 AND tenant_id = $2",
                        video_id, tenant_id)
                    # STATIC-DOCU videos take one archival image per segment
                    # (no cast, no story bible, no multi-angle coverage) — the
                    # image is the whole shot, held over the narration.
                    if (video.get("render_mode") or "") == "static_docu":
                        _set_task_status(video_id, "running", "Creating one image per segment…", tenant_id=tenant_id)

                        def _static_progress(m):
                            _set_task_status(video_id, "running", m, tenant_id=tenant_id)

                        from static_docu import generate_static_images_for_video
                        st = await generate_static_images_for_video(
                            video_id, tenant_id, progress=_static_progress) or {}
                        if st.get("status") == "completed":
                            await _advance("ready_for_images")
                            continue
                        _set_task_status(video_id, "failed", st.get("error") or "Couldn't create the images.", tenant_id=tenant_id)
                        return
                    try:
                        await ex.run_story_bible(video_id)
                    except Exception:  # noqa: BLE001
                        pass
                    _set_task_status(video_id, "running", "Drawing the storyboard pictures…", tenant_id=tenant_id)

                    def _cov_progress(m):
                        _set_task_status(video_id, "running", m, tenant_id=tenant_id)

                    from scripts.coverage_to_app import generate_coverage_for_video
                    cov = await generate_coverage_for_video(video_id, tenant_id, progress=_cov_progress) or {}
                    if cov.get("status") == "completed":
                        await _advance("ready_for_images")
                        continue  # next loop: ready_for_images is the stop point
                    _set_task_status(video_id, "failed", cov.get("error") or "Couldn't draw the pictures.", tenant_id=tenant_id)
                    return
                _set_task_status(video_id, "running", "Working on it…", tenant_id=tenant_id)
                result = await ex.run_next_step(video_id) or {}
                rs = result.get("status")
                if rs == "needs_approval":
                    if status == "ready_for_voice":
                        # Voice isn't needed to review the pictures and it's the slowest paid
                        # step, so build-to-pictures skips it and advances. The finish flow lays
                        # the voiceover down before the render (see the finish guard in _run).
                        if target != "pictures":
                            try:
                                await ex.run_voice(video_id)  # best-effort; no voice key -> skip
                            except Exception:  # noqa: BLE001
                                pass
                        nxt = get_next_status_supabase(status)
                        if nxt:
                            await _advance(nxt)
                        continue
                    if target == "finish" and status in ("ready_for_images", "ready_for_thumbnail"):
                        # A "finished" video includes its thumbnail — generate it
                        # before passing the gate (previously the gate was passed
                        # without ever running the thumbnail bot). Best-effort:
                        # a thumbnail failure never blocks the render.
                        if status == "ready_for_thumbnail" and not (video.get("thumbnail_url") or "").strip():
                            _set_task_status(video_id, "running", "Designing the thumbnail…", tenant_id=tenant_id)
                            try:
                                await ex.run_thumbnail(video_id)
                            except Exception:  # noqa: BLE001
                                pass
                        nxt = get_next_status_supabase(status)  # already reviewed -> pass the gate
                        if nxt:
                            await _advance(nxt)
                        continue
                    msg = PICTURES_READY_MSG if status == "ready_for_images" else (result.get("message") or "Paused for your review.")
                    _set_task_status(video_id, "completed", msg, tenant_id=tenant_id)
                    return
                if rs == "failed":
                    if status in ("idea_logged", "approved"):  # research is optional — keep going
                        await _advance("ready_for_scripting")
                        continue
                    _set_task_status(video_id, "failed", result.get("error") or "A step failed.", tenant_id=tenant_id)
                    return
                if rs == "idle":
                    _set_task_status(video_id, "completed", f"Reached {status}.", tenant_id=tenant_id)
                    return
                # completed — the handler advanced the status; loop continues.
            _set_task_status(video_id, "completed", "Build paused — say “keep going” to continue.", tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            # C16a: the caller (routes/chat.py's _handle_approve /
            # _run_pending_action) acquires the "main" claim BEFORE
            # scheduling this factory's _run — release it here, in the same
            # finally block that already runs on every exit path (the
            # target='pictures'/'finish' early returns, the no-progress
            # stop, and any raised exception), so the claim can never
            # outlive the multi-stage chain it was taken for.
            await generation_claims.release(tenant_id, video_id, "main")
            await asyncio.sleep(20)
            _clear_task_status(video_id, tenant_id)

    return _run


# --- Phase 2 runners ----------------------------------------------------------
#
# Verbs that aren't PipelineExecutor methods run through these instead: each
# reuses the SAME route handler (or helper) the UI button calls, catches its
# HTTPException, and returns the chat-facing line. Signature is uniform:
# (tenant_id, video_id, background_tasks, pending) -> str.

async def _runner_seo(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.pipeline import _clear_task_status, _set_task_status

    async def _run():
        _set_task_status(video_id, "running", "Writing the YouTube SEO…", tenant_id=tenant_id)
        try:
            from youtube_publish import generate_and_store_seo
            result = await generate_and_store_seo(video_id, tenant_id) or {}
            if result.get("error"):
                _set_task_status(video_id, "failed", result["error"], tenant_id=tenant_id)
            else:
                _set_task_status(video_id, "completed", "SEO written — it's on the Upload tab.", tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(20)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return ("On it — writing the YouTube title, description, and tags from the video's own "
            "content. They'll be on the Upload tab in a minute.")


async def _runner_approve_cast(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.characters import approve_cast
    try:
        await approve_cast(video_id, background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        return f"I can't approve the cast yet — {e.detail}"
    return ("On it — locking in the cast. I'm rewriting each character's description from "
            "their approved portrait so the pictures stay on-model; storyboards unlock when it's done.")


async def _runner_approve_environments(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.environments import approve_environments
    try:
        await approve_environments(video_id, background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        return f"I can't approve the locations yet — {e.detail}"
    return "On it — locking in the locations. Storyboards unlock when it's done."


async def _runner_skip_environments(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.environments import skip_environments
    try:
        await skip_environments(video_id, tenant_id=tenant_id)
    except HTTPException as e:
        return f"Couldn't skip the locations — {e.detail}"
    return ("Done — marked this video as having no distinct locations, so storyboards are "
            "unlocked. Designing environments later re-opens the approval.")


async def _runner_lock(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import lock_story
    try:
        await lock_story(video_id, tenant_id=tenant_id)
    except HTTPException as e:
        return f"I can't lock the story yet — {e.detail}"
    return "Story locked — the boards are frozen before image spend. Say “unlock the story” to keep iterating."


async def _runner_unlock(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import unlock_story
    try:
        await unlock_story(video_id, tenant_id=tenant_id)
    except HTTPException as e:
        return f"Couldn't unlock the story — {e.detail}"
    return "Story unlocked — edit away. Lock it again before generating pictures."


async def _runner_drive_push(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import push_script_to_drive
    try:
        res = await push_script_to_drive(video_id, tenant_id=tenant_id) or {}
    except HTTPException as e:
        return f"Couldn't send the script to Drive — {e.detail}"
    url = (res.get("doc_url") or "").strip()
    tail = f" It's here: {url}" if url else ""
    return ("Done — the script is a Google Doc in your Drive now." + tail +
            " Edit it there, then say “pull the script from Drive” and I'll bring the changes back.")


async def _runner_drive_sync(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import sync_script_from_drive
    try:
        res = await sync_script_from_drive(video_id, force=False, tenant_id=tenant_id) or {}
    except HTTPException as e:
        return f"Couldn't pull from Drive — {e.detail}"
    if res.get("conflict"):
        return ("Careful — the script changed BOTH here and in the Doc since the last sync. "
                "Pull from the Script tab (it asks before overwriting) or tell me which side should win.")
    if res.get("changed"):
        n = len(res.get("scenes_changed") or [])
        return (f"Pulled your Drive edits — {n} scene{'s' if n != 1 else ''} updated. "
                "Those scenes' voice and pictures were reset so they regenerate to match.")
    return res.get("message") or "Your script already matches the Drive Doc — nothing to pull."


async def _runner_advance(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import advance_video
    try:
        res = await advance_video(video_id, tenant_id=tenant_id) or {}
    except HTTPException as e:
        return f"Couldn't skip ahead — {e.detail}"
    ns = str(res.get("status") or "").replace("_", " ")
    return (f"Done — skipped ahead{f' to {ns}' if ns else ''}. "
            "Say “build it” anytime and I'll take it from here.")


async def _runner_approve_scene(tenant_id, video_id, background_tasks, pending) -> str:
    """C15b: 'approve scene 2' locks in that ONE scene's pictures
    (assets.status='approved') — the same column the /review page's
    approve/batch-approve endpoints already write (routes/assets.py), just
    scoped to a scene instead of one asset id or a hand-picked list. Tenant +
    video + scene scoped in one WHERE clause, so this can never touch another
    scene's, another video's, or another tenant's rows.

    No confirm card: ACTIONS marks this verb paid=False, so routes/chat.py's
    free-action branch runs it straight from the classifier's pick — nothing
    is spent and the status flip is reversible (re-run batch-approve/approve
    on the /review page to change it back), so a tap-to-confirm round-trip
    would only add friction for zero risk."""
    scene = pending.get("scene")
    if scene is None:
        return "Which scene would you like me to approve? e.g. \"approve scene 2\"."
    scene = int(scene)
    result = await execute(
        "UPDATE assets SET status = 'approved', updated_at = now() "
        "WHERE video_id = $1 AND tenant_id = $2 AND scene = $3",
        video_id, tenant_id, scene,
    )
    count = 0
    if result:
        try:
            count = int(str(result).strip().split()[-1])
        except (ValueError, IndexError):
            count = 0
    if count == 0:
        return f"Scene {scene} doesn't have any pictures yet — nothing to approve there."
    return (f"Scene {scene} approved ✓ — {count} shot{'s' if count != 1 else ''} locked in. "
            "This is free and reversible any time (approve it again later to change your mind).")


# C23 (checklist §2.2): plain-English -> camera_moves.py catalog id, for the
# copilot's "use a crash zoom on scene 12". get_move() is tried FIRST (see
# _resolve_camera_preset_text) so a classifier that already learned real
# ids from GET /api/camera-presets still resolves correctly — this alias
# map is the fallback for ordinary phrasing, not the only path.
_CAMERA_PRESET_ALIASES: dict[str, str] = {
    "crash zoom": "crash_zoom_in", "crash-zoom": "crash_zoom_in", "snap zoom": "crash_zoom_in",
    "push in": "dolly_in", "dolly in": "dolly_in", "push-in": "dolly_in",
    "pull back": "dolly_out", "pull out": "dolly_out", "dolly out": "dolly_out", "zoom out": "dolly_out",
    "slow zoom": "slow_zoom_in", "zoom in": "slow_zoom_in",
    "pan right": "pan_right", "pan left": "pan_left", "pan": "pan_right",
    "tilt up": "tilt_up_reveal", "tilt": "tilt_up_reveal",
    "crane up": "crane_up_reveal", "crane": "crane_up_reveal",
    "drone": "drone_orbit", "aerial orbit": "drone_orbit", "orbit": "orbit_right",
    "whip pan": "whip_pan", "whip": "whip_pan",
    "handheld": "handheld_follow", "follow": "handheld_follow",
    "static": "static_locked", "locked off": "static_locked", "no movement": "static_locked",
    "lock the camera": "static_locked",
}
_CAMERA_PRESET_CLEAR_WORDS = frozenset({"auto", "automatic", "clear", "earn the move", "default"})


def _resolve_camera_preset_text(text: str) -> tuple[Optional[str], bool]:
    """Returns (move_id_or_None, is_clear). is_clear=True means "go back to
    Auto" (camera_selector.py's earn-the-move decides again) — distinct from
    "unrecognized" (move_id=None, is_clear=False)."""
    t = (text or "").strip().lower()
    if not t:
        return None, False
    if t in _CAMERA_PRESET_CLEAR_WORDS:
        return None, True
    direct = get_move(t.replace(" ", "_"))
    if direct:
        return direct.id, False
    for phrase, move_id in _CAMERA_PRESET_ALIASES.items():
        if phrase in t:
            return move_id, False
    return None, False


async def _runner_camera_preset(tenant_id, video_id, background_tasks, pending) -> str:
    """C23 (checklist §2.2, UX map §4): "use a crash zoom on scene 12" / "put
    scene 4 back to auto" — writes assets.camera_preset_id for every shot in
    the given scene, the SAME column and the SAME get_move() validation the
    Scenes tab's clickable chip uses (PATCH /api/assets/{id}/camera-preset,
    routes/assets.py) — two doors, one write path. Scene-wide (the
    classifier's pending dict carries a scene number, not a per-shot index
    yet) mirrors how "animate scene N" already treats a whole scene as the
    unit.

    Free and reversible (say "auto" to clear it back to camera_selector.py's
    earn-the-move system) — no confirm card, same as approve_scene."""
    scene = pending.get("scene")
    if scene is None:
        return 'Which scene? e.g. "use a crash zoom on scene 12".'
    scene = int(scene)
    text = (pending.get("change") or "").strip()
    move_id, is_clear = _resolve_camera_preset_text(text)
    if not is_clear and not move_id:
        return (f'I didn\'t recognize "{text}" as a camera move — try something like crash zoom, '
                "push in, pull back, pan, tilt up, crane up, orbit, drone, whip pan, handheld, "
                "or static (no movement).")
    value = None if is_clear else move_id
    result = await execute(
        "UPDATE assets SET camera_preset_id = $1, updated_at = now() "
        "WHERE video_id = $2 AND tenant_id = $3 AND scene = $4",
        value, video_id, tenant_id, scene,
    )
    count = 0
    if result:
        try:
            count = int(str(result).strip().split()[-1])
        except (ValueError, IndexError):
            count = 0
    if count == 0:
        return f"Scene {scene} doesn't have any shots yet — nothing to set the camera move on."
    if value is None:
        return (f"Scene {scene} is back to Auto — {count} shot{'s' if count != 1 else ''} will use the "
                "earn-the-move system again next time you animate.")
    move = get_move(value)
    name = move.name if move else value
    return (f"Scene {scene}: {count} shot{'s' if count != 1 else ''} set to {name} — "
            f're-animate to see it (tap the card, or say "animate scene {scene}").')


async def _runner_draft_pass(tenant_id, video_id, background_tasks, pending) -> str:
    """C17 (checklist §1.3): 'draft the whole video' — route every scene's
    CLIP to the cheapest wired draft-tier model (data-driven,
    ``_draft_tier_model_id``, never a hardcoded "grok-imagine") for one cheap
    full-video pass, so a creator can judge pacing/story before spending on
    the routed/premium tiers. Pictures are untouched by this verb — they're
    already cheap and stage-shared (see ``images``/``needs="pictures"``
    above); "draft" describes CLIP generation, the expensive step this trust
    ladder is actually about. Deliberately does NOT write
    assets.routed_model/model_override — ``run_clip_generation``'s new
    ``force_model_id`` overrides the per-row RESOLUTION for this call only,
    so those columns survive untouched for ``finalize`` to read back later.

    Skip-if-done (unforced): only rows without a clip yet are drafted, same
    default `run_clip_generation` already applies — a video that already has
    (e.g. finalized) clips is left alone rather than downgraded.

    C16a lane: claims "main" — generation_claims.stage_for_verb("draft_pass")
    falls through to "main" (it's not in SIDE_LANES) because this genuinely
    is a whole-video clip-generation run, the same lane 'animate'/'images'/
    'render' already use, and must conflict with any of them in flight.
    Acquired explicitly here (not via _run_pending_action's generic runner
    path, which does not claim) — same pattern as the "build" verb.

    C17 pass-identity: before claiming, checks generation_passes for this
    EXACT (video, "draft_pass", scene-set+draft-model) hash — a repeat of the
    identical draft pass (nothing newly pictured since) is told "already
    drafted", never re-billed. A different scene set (new pictures generated)
    hashes differently and proceeds normally.
    """
    import generation_claims
    import generation_passes
    from routes.pipeline import _clear_task_status, _set_task_status

    draft_model = _draft_tier_model_id()
    if not draft_model:
        return "I don't have a wired draft-tier model to draft with right now — try “animate” instead."

    summary = await video_summary(tenant_id, video_id) or {}
    model = summary.get("model") or "grok-imagine"
    rows = await _routed_clip_rows(tenant_id, video_id, None, model)
    scenes = sorted({r["scene"] for r in rows if r.get("scene") is not None})
    if not scenes:
        return "There's nothing to draft yet — make the pictures first."

    scene_hash = generation_passes.scene_set_hash([(s, draft_model) for s in scenes])
    if await generation_passes.already_done(tenant_id, video_id, "draft_pass", scene_hash):
        return ("Already drafted this exact video on the cheap model — nothing new to draft. "
                "Approve the scenes worth finishing and say “finalize” when ready.")

    # C27: `pending["caller"]` rides in from routes/chat.py's
    # _run_pending_action ("chat" by default, "agent:<name>" for a confirmed
    # MCP tool call) — the same attribution seam every other verb's claim
    # uses, applied here too since draft_pass claims its own lane instead of
    # going through _run_pending_action's generic claim path.
    caller = (pending or {}).get("caller") or "chat"
    if not await generation_claims.acquire(tenant_id, video_id, "main", claimed_by=f"{caller}:draft_pass"):
        return _ALREADY_WORKING_REPLY

    async def _run():
        _set_task_status(video_id, "running",
                         f"Drafting all {len(scenes)} scene(s) on the cheap model…", tenant_id=tenant_id)
        try:
            from pipeline_executor import PipelineExecutor
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_clip_generation(video_id, force_model_id=draft_model) or {}
            if result.get("error"):
                _set_task_status(video_id, "failed", result.get("error"), tenant_id=tenant_id)
            else:
                await generation_passes.mark_done(tenant_id, video_id, "draft_pass", scene_hash)
                _set_task_status(
                    video_id, "completed",
                    "Draft pass done — review the scenes and approve the ones worth finishing, "
                    "then say “finalize”.", tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await generation_claims.release(tenant_id, video_id, "main")
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return (f"On it — drafting all {len(scenes)} scene(s) on the cheap model "
            "so you can judge the story before spending on the real thing.")


async def _runner_finalize(tenant_id, video_id, background_tasks, pending) -> str:
    """C17 (checklist §1.3): 'finalize' — regenerate ONLY the approved
    scenes' clips at their ROUTED (or manually overridden) tier. "Approved" =
    ``_runner_approve_scene``'s ``assets.status='approved'`` (C15b), read via
    ``_approved_scenes``. Passes ``only_scenes=<approved>`` + ``force=True``
    to ``run_clip_generation`` — the WHERE clause scopes the query to exactly
    those scenes (every other scene's rows are never even fetched, so they
    can never be touched), and ``force=True`` makes an already-drafted
    approved scene's clip get OVERWRITTEN with the real tier rather than
    skipped as "already has a clip". No ``force_model_id`` — the normal
    ``resolve_clip_model`` precedence (override > routed > video default)
    resolves each row, same as a manual "Animate" click would.

    C16a lane + C17 pass-identity: identical shape to ``_runner_draft_pass``
    — see that docstring for the "main" lane rationale and the
    generation_passes duplicate-vs-legitimate-second-pass reasoning. Here,
    approving 3 MORE scenes after an earlier finalize changes the approved
    set -> a different scene_set_hash -> a legitimate new pass; re-tapping
    "finalize" with the SAME approved set (nothing new since) hashes
    identically -> told "already finalized", zero re-spend.
    """
    import generation_claims
    import generation_passes
    from routes.pipeline import _clear_task_status, _set_task_status

    summary = await video_summary(tenant_id, video_id) or {}
    model = summary.get("model") or "grok-imagine"
    approved = await _approved_scenes(tenant_id, video_id)
    if not approved:
        return ('Nothing\'s approved yet — say "approve scene 3" (or a few) and I\'ll finalize just those.')

    rows = await _routed_clip_rows(tenant_id, video_id, None, model, only_scenes=approved)
    pairs = [(r["scene"], _resolved_model_id(r, model)) for r in rows if r.get("scene") is not None]
    scene_hash = generation_passes.scene_set_hash(pairs)

    if await generation_passes.already_done(tenant_id, video_id, "finalize", scene_hash):
        n = len(approved)
        return (f"Already finalized these {n} approved scene{'s' if n != 1 else ''} at their routed "
                "quality — nothing's changed since. Approve more scenes and I'll pick up just those.")

    # C27: see _runner_draft_pass's comment just above — same attribution seam.
    caller = (pending or {}).get("caller") or "chat"
    if not await generation_claims.acquire(tenant_id, video_id, "main", claimed_by=f"{caller}:finalize"):
        return _ALREADY_WORKING_REPLY

    async def _run():
        _set_task_status(video_id, "running",
                         f"Finalizing {len(approved)} approved scene(s)…", tenant_id=tenant_id)
        try:
            from pipeline_executor import PipelineExecutor
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_clip_generation(video_id, only_scenes=approved, force=True) or {}
            if result.get("error"):
                _set_task_status(video_id, "failed", result.get("error"), tenant_id=tenant_id)
            else:
                await generation_passes.mark_done(tenant_id, video_id, "finalize", scene_hash)
                n = result.get("clips_generated")
                detail = f"{n} clip(s) across " if isinstance(n, int) else ""
                _set_task_status(
                    video_id, "completed",
                    f"Finalized {detail}{len(approved)} scene(s) at full quality.", tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await generation_claims.release(tenant_id, video_id, "main")
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return f"On it — finalizing {len(approved)} approved scene(s) at their routed quality. I'll update you here."


# C24 (checklist §2.3): plain-English -> shared.profiles.script profile id,
# for the copilot's "write it in the investigative style". A real profile id
# is tried FIRST (see _resolve_script_profile_text) so a classifier that
# already learned real ids from GET /api/script-profiles still resolves
# correctly — this alias map is the fallback for ordinary phrasing. Power
# Doctrine stays opt-in only (never the CLEAR-words target — CLEAR always
# lands on the neutral default, per storyengine/CLAUDE.md's "Power Doctrine
# as a default identity... deleted on purpose, don't resurrect").
_SCRIPT_PROFILE_ALIASES: dict[str, str] = {
    "investigative": "power_doctrine_v2", "investigative reveal": "power_doctrine_v2",
    "power doctrine": "power_doctrine_v2", "follow the money": "power_doctrine_v2",
    "incentive chain": "power_doctrine_v2", "analyst": "power_doctrine_v2",
    "framework explainer": "power_doctrine_v1", "framework": "power_doctrine_v1",
    "documentary": "power_doctrine_v1", "teaching": "power_doctrine_v1",
}
_SCRIPT_PROFILE_CLEAR_WORDS = frozenset({
    "auto", "automatic", "clear", "default", "neutral", "neutral_v1", "normal",
})


def _resolve_script_profile_text(text: str) -> tuple[Optional[str], bool]:
    """Returns (profile_id_or_None, is_clear). is_clear=True means "back to
    neutral" (the profile engine's own default) — distinct from
    "unrecognized" (profile_id=None, is_clear=False)."""
    t = (text or "").strip().lower()
    if not t:
        return None, False
    if t in _SCRIPT_PROFILE_CLEAR_WORDS:
        return None, True
    direct = t.replace(" ", "_")
    if direct in _list_script_profiles():
        return direct, False
    for phrase, profile_id in _SCRIPT_PROFILE_ALIASES.items():
        if phrase in t:
            return profile_id, False
    return None, False


async def _runner_script_profile(tenant_id, video_id, background_tasks, pending) -> str:
    """C24 (checklist §2.3, UX map §4): "write it in the investigative
    style" / "put it back to neutral" — writes videos.script_profile, the
    SAME column and the SAME registry validation the ScriptVoiceTab's
    picker uses (PATCH /api/videos/{id}) — two doors, one write path.

    Free and reversible (say "neutral"/"auto" to clear it back to the
    engine's own default) — no confirm card, same as camera_preset. This
    verb only sets the voice for the NEXT script write; it does not itself
    regenerate an existing script (say "rewrite the script" for that)."""
    text = (pending.get("change") or "").strip()
    profile_id, is_clear = _resolve_script_profile_text(text)
    if not is_clear and not profile_id:
        return (f'I didn\'t recognize "{text}" as a script voice — try "investigative reveal" '
                '(follow-the-money analyst voice), "framework explainer" (documentary teaching '
                'voice), or "neutral"/"auto" for the default.')
    value = None if is_clear else profile_id
    await execute(
        "UPDATE videos SET script_profile = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
        value, video_id, tenant_id,
    )
    if value is None:
        return "Script voice reset to neutral — the next script write uses the default craft voice."
    profile = _load_script_profile(value)
    name = (profile.template_metadata.display_name if profile and profile.template_metadata
            else value)
    return (f"Script voice set to {name} — say \"rewrite the script\" to see it in the next draft "
            "(this doesn't regenerate an existing script on its own).")


RUNNERS = {
    "advance": _runner_advance,
    "seo": _runner_seo,
    "approve_cast": _runner_approve_cast,
    "approve_environments": _runner_approve_environments,
    "skip_environments": _runner_skip_environments,
    "approve_scene": _runner_approve_scene,
    "camera_preset": _runner_camera_preset,
    "script_profile": _runner_script_profile,
    "lock": _runner_lock,
    "unlock": _runner_unlock,
    "drive_push": _runner_drive_push,
    "drive_sync": _runner_drive_sync,
    "draft_pass": _runner_draft_pass,
    "finalize": _runner_finalize,
}
