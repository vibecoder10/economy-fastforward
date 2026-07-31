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
import math
import re
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
from status_map import is_at_or_past_stage, render_path_plays_sfx, render_path_sfx_block_reason
from static_docu_contract import STATIC_VIEWS_TARGET

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
    SCRIPT_PRICE_ESTIMATE as SCRIPT_COST_ESTIMATE,
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
    # C36 (checklist §3.3 item 3): "cap this video at $15" — the conversational
    # door onto the SAME videos.max_spend column the New Video "Advanced" field
    # and PATCH /api/videos/{id} write. Free (metadata only — setting a number
    # doesn't itself spend) and reversible ("remove the cap"), so — like
    # camera_preset/script_profile — it runs straight from the classifier's
    # pick, no confirm card. No `needs` gate: a cap can be set any time.
    "budget_cap":  {"runner": "budget_cap", "paid": False, "needs": None,
                    "doing": "setting the budget cap", "label": "Set the budget cap"},
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
# C36 (checklist §3.3 item 1): the audit flagged this exact checkpoint —
# build-to-pictures deliberately skips voice (the slowest paid step, not
# needed to review pictures — see the "finish" guard above) and leaves it for
# the finish phase, but the old copy said only "review them", never mentioning
# audio isn't there yet. A creator who then opened the Scenes tab and read a
# stock "Voice Required" gate (see ScenesWorkspaceTab.tsx's hasPictures fix,
# same chunk) had every reason to think something was broken. Set the
# expectation here instead of implying audio exists.
PICTURES_READY_MSG = ("Your pictures are ready — review them (no voice yet, that's next), then say "
                      "“animate it” or “finish it” and I'll add the voice-over and take it the rest "
                      "of the way.")

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
        # C62: this is the one post-create seam that can change a video's
        # length after the create-time gate (routes/videos.py::create_video)
        # already ran — a Starter creator saying "make it 20 minutes" via the
        # copilot's script-redo verb would otherwise bypass the 10-minute cap
        # entirely. Same shared check, same 402 shape; raises here (not
        # caught into a friendly chat line — see routes/chat.py's separate
        # try/except around create_video for that treatment) since this
        # function has no conversational-reply context of its own.
        from routes.billing import enforce_video_length_cap
        await enforce_video_length_cap(tenant_id, mins)
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
    codebase. A duplicate draft consumes another one of the shared project's
    100 daily upload calls for a mistake that's easy to make and prevent, so
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
        "SELECT video_title, status, video_length_minutes, video_model, script_validation, render_style, render_mode, "
        "total_cost, max_spend, custom_film_plan_id, dialogue_audio, dialogue_mode, "
        "characters_approved_at, environments_approved_at "
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
    # Additive (approval-gate mechanism, feat/approval-gates): environment count,
    # alongside the character count `c` above — the anchor gate's "Characters x N /
    # Locations x M" line reads both from here, same as every other copilot read.
    e = await fetch_one(
        "SELECT count(*) AS n FROM video_environments WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    model = v.get("video_model") or "grok-imagine"
    pics, clips = int(a["pics"] or 0), int(a["clips"] or 0)
    cost = round(pics * PICTURE_COST + clips * CLIP_COST.get(model, 0.10), 2)
    return {
        "title": v.get("video_title") or "Untitled",
        "status": v.get("status") or "unknown",
        # C25a-fix13: video_length_minutes is NUMERIC in postgres — asyncpg
        # hands it back as a Decimal, and json.dumps (routes/mcp.py's
        # _text_result, no default=str) chokes on that raw. Cast explicitly,
        # same as total_cost/max_spend just below and the SAME pattern
        # routes/videos.py:689 already uses for this identical column.
        "length_min": float(v["video_length_minutes"]) if v.get("video_length_minutes") is not None else None,
        "model": model,
        "scenes": int(sc["scenes"] or 0),
        "boards": int(sc["boards"] or 0),
        "voiced": int(sc["voiced"] or 0),
        "max_scene": int(sc["max_scene"] or 0),
        "pics": pics,
        "clips": clips,
        "cast": int(c["n"] or 0),
        # Additive (approval-gate mechanism): environment count + whether the
        # cast/locations gate has already been passed. `envs_approved` mirrors
        # `chars_approved` — both timestamps are set together by the anchor
        # gate's own approval (routes/chat.py's approval_gate handshake) or by
        # the existing approve_cast/approve_environments runners, so either
        # one being null means the anchor gate hasn't cleared yet.
        "envs": int(e["n"] or 0),
        "chars_approved": v.get("characters_approved_at") is not None,
        "envs_approved": v.get("environments_approved_at") is not None,
        "spent": cost,
        # C36 (checklist §3.3 item 3): the REAL ledger-rolled-up spend
        # (generation_ledger.record_ledger_entry's SUM(actual_cost) —
        # checklist §0.3/C07-C08), separate from "spent" above (the
        # artifact-count estimate every existing caller of that key already
        # reads — left untouched to avoid regressing legacy videos that
        # accrued real spend before the C07 ledger existed and were never
        # backfilled, which would make total_cost read as $0 for them).
        # total_cost/max_spend exist ONLY to feed budget_check() below — the
        # one new consumer that needs the honest number, not the estimate.
        "total_cost": float(v.get("total_cost") or 0),
        "max_spend": float(v["max_spend"]) if v.get("max_spend") is not None else None,
        "validation": str(v.get("script_validation") or "").strip()[:600],
        # C15: the channel-look guardrail state (checklist §1.2/C13b) — additive,
        # read by cost_breakdown/guardrail_note to explain a mixed or single-model
        # routing plan in the copilot's confirm text. None on any pre-C13b video.
        "render_style": v.get("render_style"),
        "render_mode": v.get("render_mode"),
        # Whether THIS video's render path will ever mix in sound effects
        # (status_map.render_path_plays_sfx — mirrors run_render's dispatch
        # order exactly). Computed here, once, from the raw video row so
        # blocked_reason()/estimate_cost() below and any other reader of this
        # summary answer "will sound effects play?" from the SAME source,
        # never by re-deriving custom_film_plan_id/render_mode/dialogue_audio/
        # dialogue_mode branches themselves.
        "plays_sfx": render_path_plays_sfx(v),
        "sfx_blocked_reason": render_path_sfx_block_reason(v),
    }


def budget_check(summary: dict[str, Any], quote_cost: float) -> Optional[dict[str, Any]]:
    """C36 (checklist §3.3 item 3): would this quote push the video's REAL spend
    (``summary["total_cost"]`` — the generation_ledger rollup, not the
    artifact-count "spent" estimate) past its optional per-video cap
    (``summary["max_spend"]``)?

    Returns None when there's no cap set (the default — every video created
    before migration 103, and every video that never sets one, behaves
    byte-identically to before this function existed) or when the quote fits
    under it. Returns a dict describing the breach otherwise.

    Matches the money-gate philosophy the rest of this module already
    follows (``estimate_cost``/``cost_breakdown``): quote honestly, let the
    human decide with full information. This function NEVER blocks anything
    itself — it only classifies. The two callers decide what "surfaced
    honestly" means for their door: chat.py's confirm card folds the message
    into the same one-tap yes/no card (tapping "yes" IS the explicit
    override — no second confirmation step invented); the autobuild loop
    (``make_autobuild_step``) pauses cleanly instead of silently continuing
    past the cap, the same "stop and say so" pattern it already uses for the
    no-progress and 18-iteration-cap stops."""
    cap = summary.get("max_spend")
    if cap is None:
        return None
    cap = float(cap)
    spent = float(summary.get("total_cost") or 0)
    projected = round(spent + max(quote_cost, 0.0), 2)
    if projected <= cap:
        return None
    return {
        "cap": cap,
        "spent": spent,
        "quote": round(quote_cost, 2),
        "projected": projected,
        "message": (
            f"heads up — this would put you at ${projected:.2f} against your ${cap:.2f} "
            f"cap for this video (${spent:.2f} spent so far + ${quote_cost:.2f} for this). "
            "Tap to run it anyway, or raise the cap first."
        ),
    }


async def budget_refusal(
    tenant_id, video_id: str, quote_cost: float, item_label: str = "this generation",
) -> Optional[str]:
    """Pre-spend cap check, generalized for every paid call site that isn't
    already inside the confirm-card/autobuild machinery (money-safety fix —
    dialogue voice, static-documentary images, panel upscaling, the "fix
    text" card redraw, and any future single-shot paid generation). Same
    two building blocks as everything else in this module — video_summary
    for the live total_cost/max_spend read, budget_check for the
    over-cap classification — just packaged as one awaitable a call site
    can check right before its provider call. Mirrors
    routes/characters.py's ``_budget_refusal`` (the character/environment
    money-safety fix) exactly; that one stays route-local since
    routes/environments.py already imports it, but the underlying pattern
    is this same video_summary + budget_check pair, not a second mechanism.
    Returns a plain-English refusal message, or None if this quote fits
    under the cap (or no cap is set)."""
    summary = await video_summary(tenant_id, video_id)
    if not summary:
        return None
    breach = budget_check(summary, quote_cost)
    if not breach:
        return None
    return (
        f"Paused — this would put you at ${breach['projected']:.2f} against this video's "
        f"${breach['cap']:.2f} spend cap (${breach['spent']:.2f} already spent, "
        f"${breach['quote']:.2f} for {item_label}). Raise the cap in Settings, then run "
        "this again."
    )


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
    # The "sound" verb generates real money (Kie.ai ElevenLabs Sound Effect
    # V2, ~$0.05/effect) that's wasted if this video's render path can never
    # mix it in — see status_map.render_path_plays_sfx / the "plays_sfx" flag
    # video_summary() computes from the SAME helper above.
    #
    # `.get("plays_sfx", True)` fails OPEN (treats a MISSING key as "SFX
    # play, allow it") — deliberate, matching every other legacy-default in
    # this guard (render_path_plays_sfx(None) is also True), so a summary
    # dict from BEFORE this field existed keeps behaving exactly as before.
    # This is only safe because every current caller of blocked_reason()
    # (agent_brain.py's _tool_state, routes/mcp.py's _call_verb, routes/
    # chat.py's classifier dispatch) builds `summary` via video_summary()
    # above, which always sets the key. A future caller that hand-rolls a
    # summary dict WITHOUT going through video_summary() would silently
    # fail this specific check open — but this is the OUTER, UX-polish layer
    # only: run_sound_prompts/run_sound_effects (pipeline_executor.py) check
    # status_map.render_path_plays_sfx directly off the real video row before
    # any paid call, and refuse regardless of what this function decides. If
    # you add a caller that builds `summary` by hand, either route it through
    # video_summary() or set "plays_sfx" yourself — don't just trust this
    # default.
    if verb == "sound" and not summary.get("plays_sfx", True):
        reason = summary.get("sfx_blocked_reason") or "this render path drops sound effects."
        return f"sound effects won't be used for this video — {reason}"
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
        if summary.get("render_mode") == "static_docu":
            # Anton's format always redraws a complete three-view unit set;
            # existing rows do not lower the quote because the scene-scoped
            # generator replaces them idempotently.
            n = STATIC_VIEWS_TARGET * (
                1 if scene is not None else max(1, summary["scenes"])
            )
        else:
            n = summary["pics"] or max(1, summary["scenes"]) * 6
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
        cost = SCRIPT_COST_ESTIMATE
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
            pictures_per_scene = (
                STATIC_VIEWS_TARGET
                if summary.get("render_mode") == "static_docu"
                else 6
            )
            cost = scenes * pictures_per_scene * PICTURE_COST
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
    elif verb == "custom_film_section":
        # M2-3: section-aware Custom Film pricing still goes through this
        # shared estimator.  The deterministic compiler supplies only counts;
        # every dollar constant remains the same shared channel-profile source
        # used by every other chat/button quote above.
        stills = max(0, int(summary.get("still_images") or 0))
        clips = max(0, int(summary.get("animation_clips") or 0))
        voices = max(0, int(summary.get("voice_tracks") or 0))
        cost = (
            stills * PICTURE_COST
            + clips * clip
            + voices * VOICE_COST_ESTIMATE
        )
    else:
        cost = 0.0
    text = "no extra cost" if cost <= 0 else f"~${cost:.2f}"
    return round(cost, 2), text


async def estimate_custom_film_plan(
    normalized_plan: dict[str, Any],
    *,
    total_duration_seconds: int,
    model: str = "grok-imagine",
) -> dict[str, Any]:
    """Compile a deterministic section BOM and price every row via estimate_cost.

    This is deliberately internal/provider-neutral output.  Chat renders only
    the friendly media counts and total; model/provider identifiers stay in the
    quote inputs used for the approval binding.
    """
    duration = max(5, min(24 * 60 * 60, int(total_duration_seconds)))
    sections = normalized_plan.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("Custom Film plan has no sections")
    if duration < len(sections):
        raise ValueError("Custom Film duration is too short for its section count")
    if sum(int(section.get("duration_units") or 0) for section in sections) != 1_000_000:
        raise ValueError("Custom Film section durations are not normalized")

    # Integer-second largest-remainder allocation.  Independent round() calls
    # can drift above/below the approved runtime, especially for 5-second
    # multi-section plans; this guarantees exact reconciliation.
    exact_seconds = [
        duration * max(1, int(section.get("duration_units") or 0)) / 1_000_000
        for section in sections
    ]
    section_seconds = [math.floor(value) for value in exact_seconds]
    remainder = duration - sum(section_seconds)
    ranked = sorted(
        range(len(sections)),
        key=lambda index: (-(exact_seconds[index] - section_seconds[index]), index),
    )
    for index in ranked[:remainder]:
        section_seconds[index] += 1
    for zero_index in (
        index for index, seconds in enumerate(section_seconds) if seconds == 0
    ):
        donor = min(
            (index for index, seconds in enumerate(section_seconds) if seconds > 1),
            key=lambda index: (-section_seconds[index], index),
        )
        section_seconds[zero_index] = 1
        section_seconds[donor] -= 1

    rows: list[dict[str, Any]] = []
    capability_totals = {
        "image_generation": 0,
        "clip_generation": 0,
        "voice_generation": 0,
    }
    total_cost = 0.0
    for section, seconds in zip(sections, section_seconds):
        knobs = section.get("knobs") if isinstance(section.get("knobs"), dict) else {}
        density = knobs.get("image_density") if isinstance(knobs.get("image_density"), dict) else {}
        animation = knobs.get("animation") if isinstance(knobs.get("animation"), dict) else {}
        dubbing = knobs.get("dubbing") if isinstance(knobs.get("dubbing"), dict) else {}

        if density.get("mode") == "per_item":
            stills = max(1, math.ceil(seconds / 60)) * max(1, int(density.get("target") or 1))
        else:
            stills = max(
                1,
                math.ceil(seconds / 60 * max(1, float(density.get("target_per_minute") or 1))),
            )
        clips = stills if bool(animation.get("enabled")) else 0
        voices = 2 if bool(dubbing.get("enabled")) else 1
        summary = {
            "model": model,
            "still_images": stills,
            "animation_clips": clips,
            "voice_tracks": voices,
        }
        row_cost, _ = await estimate_cost(
            None, None, "custom_film_section", None, summary
        )
        row = {
            "section_id": str(section.get("section_id") or ""),
            "order_index": int(section.get("order_index") or 0),
            "duration_seconds": seconds,
            "still_images": stills,
            "animation_clips": clips,
            "voice_tracks": voices,
            "provider_capabilities": {
                "image_generation": stills,
                "clip_generation": clips,
                "voice_generation": voices,
            },
            "estimated_cost": row_cost,
        }
        rows.append(row)
        total_cost += row_cost
        for capability, count in row["provider_capabilities"].items():
            capability_totals[capability] += count

    totals = {
        "duration_seconds": sum(row["duration_seconds"] for row in rows),
        "still_images": sum(row["still_images"] for row in rows),
        "animation_clips": sum(row["animation_clips"] for row in rows),
        "voice_tracks": sum(row["voice_tracks"] for row in rows),
        "provider_capabilities": capability_totals,
        "estimated_cost": round(total_cost, 2),
    }
    return {
        "estimator_version": "shared-actions-v1",
        "model": model,
        "requested_duration_seconds": duration,
        "sections": rows,
        "totals": totals,
    }


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
                     start_msg: str = "On it…", stage: str = "main",
                     force_rewrite: bool = False):
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

    D3-51: `force_rewrite` rides along to run_script only — the caller
    (routes/chat.py's _run_pending_action) sets it True exactly when this
    dispatch just applied a follow-up edit (apply_followup_edit) onto the
    "script" verb, so a confirmed chat change always overrides run_script's
    "supplied script verbatim" shortcut instead of silently getting eaten
    by it (see PipelineExecutor.run_script's own docstring for the full
    story). A no-op for every other verb's calls list.
    """
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status
    import generation_claims

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)

        async def _progress(message: str):
            _set_task_status(video_id, "running", message, tenant_id=tenant_id)

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
                if name in {"run_script", "run_voice"}:
                    kwargs["progress_callback"] = _progress
                if name == "run_script" and force_rewrite:
                    kwargs["force_rewrite"] = True
                result = await method(video_id, **kwargs) or {}
                if result.get("error"):
                    break
            _set_task_status(video_id, result.get("status", "completed"),
                             result.get("error") or result.get("message"), tenant_id=tenant_id)
            # Job 4 (surface plan, 2026-07-28): a needs_review verdict reaches
            # THIS generic runner too — a direct "rewrite the script" tap
            # (outside the "Make it" autobuild chain, which has its own copy
            # of this same post in make_autobuild_step above) also stalls
            # silently for anyone not staring at the stepper banner. Scoped
            # to run_script specifically (`any(name == "run_script"...)`) —
            # needs_review is a run_script-only status today, but this keeps
            # the script-specific card/buttons from firing on some other
            # stage's status string if that ever changed.
            if result.get("status") == "needs_review" and any(
                name == "run_script" for name, _ in calls
            ):
                try:
                    from routes.chat import _post_script_review_message
                    await _post_script_review_message(
                        tenant_id, video_id,
                        result.get("message") or "The script needs another look before I keep going.",
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "script review chat post failed (direct verb)", exc_info=True,
                    )
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await generation_claims.release(tenant_id, video_id, stage)
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    return _run


async def _pause_for_approval_gate(
    tenant_id, video_id: str, gate_kind: str, target: str, wait_message: str,
) -> None:
    """Shared pause action for make_autobuild_step's two checkpoints
    (feat/approval-gates): posts the approval_gate card into the video's
    chat conversation (lazy import — routes.chat imports actions.py at
    module level, so the reverse must stay lazy to avoid a circular
    import, same pattern as every other routes.* import in this file) and
    sets a task status that reads as "waiting on you", never as a stall —
    the exact "chat froze silently, no idea if it was thinking or dead" bug
    this whole mechanism exists to avoid repeating.

    Resuming reuses the untouched "build" verb path in
    routes.chat._run_pending_action: the gate's resume payload is
    `{"verb": "build", "target": target, ...}`, exactly what a normal
    "keep going" turn already sends — approving the gate is not a new way
    to schedule the autobuild chain, it's the SAME one, one tap sooner.
    """
    from routes.pipeline import _set_task_status
    try:
        from routes.chat import _post_approval_gate_for_autobuild
        await _post_approval_gate_for_autobuild(
            tenant_id, video_id, gate_kind,
            {"verb": "build", "target": target, "scene": None, "change": "", "length_min": None},
        )
    except Exception:  # noqa: BLE001 — the pause itself must never crash the build;
        # worst case the chat card doesn't appear but the task-status message
        # (set unconditionally below) still tells the creator to look.
        logger.warning("approval gate post failed (%s)", gate_kind, exc_info=True)
    _set_task_status(video_id, "completed", wait_message, tenant_id=tenant_id)


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

        async def _progress(message: str):
            _set_task_status(video_id, "running", message, tenant_id=tenant_id)

        async def _run_static_docu_roster_research() -> Optional[dict]:
            """G8: run_research's roster-discovery + validation gate can pass while
            the untargeted bulk per-machine hold INSIDE run_research is refused by
            the hallucination-safety gate (pipeline_executor._run_unit_research_hold,
            commit e945c762) because no verified per-machine card exists yet for a
            fresh multi-unit roster. That gate is never bypassed here — it is the
            exact same gate a human satisfies one machine at a time by clicking
            through /machine-research-one/{video_id}. This walks the identical
            locked roster, in the gate's own machine order (its persisted
            unit_research_hold_validation.units — see _full_research_validation),
            through ex.run_one_machine_research (-> _run_unit_research_hold with a
            target_machine, the exact call that REST route makes) so the whole
            roster clears hands-free instead of dead-ending the build.

            Returns None when this isn't that case (roster validation itself
            failed, or research never produced a per-machine breakdown at all —
            e.g. a non-roster or single-machine static_docu video) so the caller
            falls back to its normal research-failed message, byte-identical to
            before this function existed. Otherwise returns
            {"status": "ready_for_scripting"} once every machine passes, or
            {"status": "paused"/"needs_review", "message": ...} when the loop
            stopped early or finished with some machines still failing review.
            """
            import json as _json_roster

            video_row = await ex._get_video(video_id) or {}
            payload = video_row.get("research_payload") or {}
            if isinstance(payload, str):
                try:
                    payload = _json_roster.loads(payload)
                except (ValueError, TypeError):
                    payload = {}
            if not isinstance(payload, dict):
                return None
            roster_check = payload.get("unit_roster_validation")
            if not (isinstance(roster_check, dict) and roster_check.get("passed")):
                return None  # the roster itself is the problem — not this loop's job
            hold_validation = payload.get("unit_research_hold_validation")
            units = hold_validation.get("units") if isinstance(hold_validation, dict) else None
            if not isinstance(units, list) or not units:
                return None  # no locked roster (e.g. single-machine static_docu) — unchanged path
            total = len(units)
            pending = [
                (position, str(unit.get("machine") or ""))
                for position, unit in enumerate(units, start=1)
                if isinstance(unit, dict) and not unit.get("passed") and str(unit.get("machine") or "").strip()
            ]
            if not pending:
                return None  # every machine already reads passed but the gate still
                # refused to advance — a real bug, not something this loop can fix blind.
            done = total - len(pending)
            failures: list[str] = []
            for position, machine in pending:
                # Same cap-check pattern as the rest of this autobuild chain
                # (below, ~"cap = video.get('max_spend')"): re-read fresh so a
                # ledger entry recorded by the PREVIOUS machine in THIS loop is
                # honored before the NEXT machine starts, and a cap raised
                # mid-run is picked up immediately too.
                cap_row = await fetch_one(
                    "SELECT max_spend, total_cost FROM videos WHERE id=$1 AND tenant_id=$2",
                    video_id, tenant_id)
                cap = (cap_row or {}).get("max_spend")
                spent = float((cap_row or {}).get("total_cost") or 0)
                if cap is not None and spent >= float(cap):
                    return {
                        "status": "paused",
                        "message": (
                            f"Paused — {done}/{total} machines researched, "
                            f"${spent:.2f} spent against this video's ${float(cap):.2f} cap. "
                            "Raise the cap (or clear it) and say \"keep going\" to continue."
                        ),
                    }
                _set_task_status(
                    video_id, "running",
                    f"Researching machine {position}/{total}: {machine}",
                    tenant_id=tenant_id)
                result = await ex.run_one_machine_research(video_id, machine) or {}
                if result.get("status") == "completed":
                    done += 1
                    continue
                # needs_review or failed — keep walking the rest of the roster so
                # one bad machine can't hide whether the others are fine too; the
                # park message below then names every machine that needs a look
                # in one pass instead of a fix-one/restart/find-the-next cycle.
                warning = "; ".join(str(w) for w in (result.get("warnings") or [])) \
                    or result.get("error") or "research did not pass review"
                failures.append(f"{machine}: {warning}"[:220])
            if failures:
                return {
                    "status": "needs_review",
                    "message": (
                        f"{done}/{total} machines researched; {len(failures)} still need review: "
                        + "; ".join(failures)
                    )[:1500],
                }
            await _advance("ready_for_scripting")
            return {"status": "ready_for_scripting"}

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
                        # C36 (checklist §3.3 item 3): this pre-loop voice pass
                        # is itself a real paid step, ahead of the per-iteration
                        # cap check below — same "already at/over cap" guard so
                        # a capped video can't spend on voice before the loop
                        # even gets a chance to look.
                        vrow = await fetch_one(
                            "SELECT status, max_spend, total_cost FROM videos WHERE id=$1 AND tenant_id=$2",
                            video_id, tenant_id)
                        cap = (vrow or {}).get("max_spend")
                        spent = float((vrow or {}).get("total_cost") or 0)
                        if cap is not None and spent >= float(cap):
                            _set_task_status(
                                video_id, "completed",
                                f"Paused — you've spent ${spent:.2f} against this video's ${float(cap):.2f} "
                                "cap. Raise the cap (or clear it) and say \"keep going\" to continue.",
                                tenant_id=tenant_id)
                            return
                        _set_task_status(video_id, "running", "Recording the voiceover…", tenant_id=tenant_id)
                        await ex.run_voice(
                            video_id,
                            progress_callback=_progress,
                        )
                        if vrow and vrow.get("status"):
                            await _advance(vrow["status"])
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
                # C36 (checklist §3.3 item 3): the budget ceiling, checked before
                # every remaining paid step in the chain — not just the
                # 18-iteration hard cap above. No per-iteration quote exists here
                # (each iteration can be a script/image/clip/render stage at a
                # different price), so the honest check available at this
                # granularity is "have we already reached or passed the cap" —
                # read fresh off `video` (the SAME row this iteration already
                # fetched, kept live by generation_ledger.record_ledger_entry's
                # rollup after every completed paid unit). None set -> no cap ->
                # byte-identical to every video that existed before migration
                # 103. Pauses cleanly (same "stop and say so" shape as the
                # no-progress/18-cap stops above) — never a silent skip.
                cap = video.get("max_spend")
                if cap is not None:
                    spent = float(video.get("total_cost") or 0)
                    if spent >= float(cap):
                        _set_task_status(
                            video_id, "completed",
                            f"Paused — you've spent ${spent:.2f} against this video's ${float(cap):.2f} "
                            "cap. Raise the cap (or clear it) and say \"keep going\" to continue.",
                            tenant_id=tenant_id)
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
                        # G8: a multi-unit roster can pass discovery/validation
                        # while run_research's own untargeted bulk per-machine
                        # hold is refused by the hallucination-safety gate (no
                        # verified card exists yet for any roster machine).
                        # Walk the SAME locked roster through the safe verified
                        # one-machine path instead of dead-ending the build —
                        # see _run_static_docu_roster_research's own docstring.
                        loop_result = await _run_static_docu_roster_research()
                        if loop_result is not None:
                            if loop_result.get("status") == "ready_for_scripting":
                                continue
                            terminal_status = "completed" if loop_result.get("status") == "paused" else loop_result.get("status")
                            _set_task_status(
                                video_id, terminal_status,
                                loop_result.get("message") or "Roster research paused.",
                                tenant_id=tenant_id)
                            return
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
                if status == "ready_for_scripting":
                    script_result = await ex.run_script(
                        video_id,
                        progress_callback=_progress,
                    ) or {}
                    if script_result.get("status") == "failed":
                        _set_task_status(
                            video_id,
                            "failed",
                            script_result.get("error") or "Script generation failed.",
                            tenant_id=tenant_id,
                        )
                        return
                    # C-frontdoor2 (2026-07-27): a needs_review verdict (the
                    # quality critic still flags the script after its bounded
                    # edit loop — script_quality.run_critique_and_edit) must
                    # STOP the chain here, with the real reason, not fall
                    # through to `continue`. Before this fix, falling through
                    # looped back to the top, re-read the SAME status (video
                    # status never advances on needs_review — see
                    # pipeline_executor.run_script), and only stopped via the
                    # generic "no progress" branch below with a bare "Paused
                    # at ready_for_scripting." — never mentioning that a
                    # script existed and was rejected, or why. That silently
                    # read as a stall, not a decision waiting on the creator.
                    if script_result.get("status") == "needs_review":
                        review_msg = (
                            script_result.get("message")
                            or "The script needs another look before I keep building — "
                            "check the notes and tell me to redo it, or say \"use it anyway\" "
                            "to keep going as-is."
                        )
                        _set_task_status(
                            video_id, "needs_review", review_msg, tenant_id=tenant_id,
                        )
                        # Job 4 (surface plan, 2026-07-28): "the run correctly
                        # stopped... he never saw it. From his seat the app
                        # looked frozen." The task-status write above only
                        # ever reached the live stepper banner (a creator not
                        # looking at it sees nothing) — this ALSO posts the
                        # SAME message as a normal, persisted chat turn with
                        # a real "Rewrite it" / "Use it anyway" choice, same
                        # pattern as _pause_for_approval_gate's chat post
                        # just below in this file. Fail-soft: a chat-post
                        # failure must never fail the build itself.
                        try:
                            from routes.chat import _post_script_review_message
                            await _post_script_review_message(tenant_id, video_id, review_msg)
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "script review chat post failed (autobuild)", exc_info=True,
                            )
                        return
                    # feat/approval-gates checkpoint 1 (script gate): pause here,
                    # BEFORE spending on the cast/locations, the first time this
                    # video reaches this point — same durable signal (cast==0)
                    # routes/chat.py's _pending_gate_kind_for uses for the
                    # conversational "design the characters" turn, so the
                    # automatic chain and a typed request make the identical
                    # decision. Only for target=="pictures": a "finish" chain
                    # runs on a video already well past this checkpoint.
                    # Guarded on static_docu too — that format never designs a
                    # cast at all (see the STATIC-DOCU branch below).
                    if target == "pictures" and (video.get("render_mode") or "") != "static_docu":
                        crow = await fetch_one(
                            "SELECT count(*) AS n FROM video_characters WHERE video_id=$1 AND tenant_id=$2",
                            video_id, tenant_id)
                        if int((crow or {}).get("n") or 0) == 0:
                            await _pause_for_approval_gate(
                                tenant_id, video_id, "script", target,
                                "Script's ready — waiting on you to take a look before I design "
                                "the cast and locations. Say the word (or tap \"Looks good!\" in "
                                "chat) when you're ready.",
                            )
                            return
                    continue
                # feat/approval-gates checkpoint 2 (anchors gate): the cast and
                # locations used to get silently auto-approved right here (the
                # COALESCE stamp just below) the instant the chain reached the
                # image phase — characters/environments were designed IMPLICITLY
                # inside coverage generation, never shown to the creator before
                # the big picture spend. Now: design them explicitly (still
                # cheap — a handful of $0.03-ish reference sheets, not the full
                # ~120-picture coverage pass) and PAUSE for review before that
                # spend, unless this checkpoint already cleared (both approved).
                # Guarded exactly like checkpoint 1 (target=="pictures", not
                # static_docu — that format skips cast/locations entirely).
                if (
                    status in ("ready_for_image_prompts", "ready_for_storyboards",
                               "ready_for_storyboard_images", "ready_for_storyboard_extraction")
                    and target == "pictures"
                    and (video.get("render_mode") or "") != "static_docu"
                ):
                    vrow = await fetch_one(
                        "SELECT characters_approved_at, environments_approved_at FROM videos "
                        "WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
                    both_approved = bool((vrow or {}).get("characters_approved_at")) and bool(
                        (vrow or {}).get("environments_approved_at"))
                    if not both_approved:
                        crow = await fetch_one(
                            "SELECT count(*) AS n FROM video_characters WHERE video_id=$1 AND tenant_id=$2",
                            video_id, tenant_id)
                        erow = await fetch_one(
                            "SELECT count(*) AS n FROM video_environments WHERE video_id=$1 AND tenant_id=$2",
                            video_id, tenant_id)
                        cast_n = int((crow or {}).get("n") or 0)
                        env_n = int((erow or {}).get("n") or 0)
                        # Design each ONLY the first time through this checkpoint.
                        # Neither run_characters nor the environments design step
                        # is skip-if-done — BOTH unconditionally delete and
                        # regenerate every character/location sheet whenever
                        # called (verified by reading pipeline_executor.py's
                        # run_characters and routes/environments.py's
                        # design_environments: each starts with a DELETE ...
                        # WHERE source='generated' AND status='draft' followed
                        # by a fresh generate-per-row loop). Calling either on a
                        # RESUMED pass (cast_n/env_n already > 0, or an
                        # approved-anchors video that looped back here for some
                        # other reason) would silently re-spend on sheets the
                        # creator already reviewed and approved — this count
                        # check is the guard that makes resuming safe.
                        if cast_n == 0:
                            _set_task_status(video_id, "running", "Designing the cast…", tenant_id=tenant_id)
                            char_result = await ex.run_characters(video_id) or {}
                            char_err = (char_result.get("error") or "") if char_result.get("status") == "failed" else ""
                            # Only a hard blocker (no API key — every later paid
                            # step would fail identically) stops the build.
                            # "No recurring characters found" is a legitimate
                            # empty result (a simple/abstract video), not a
                            # failure — continue with cast_n staying 0.
                            if char_err and "api key" in char_err.lower():
                                _set_task_status(video_id, "failed", char_err, tenant_id=tenant_id)
                                return
                        if env_n == 0:
                            _set_task_status(video_id, "running", "Designing the locations…", tenant_id=tenant_id)
                            try:
                                from routes.environments import run_environments_design_step
                                await run_environments_design_step(video, tenant_id)
                            except Exception:  # noqa: BLE001 — locations are optional; never block the build on this
                                logger.warning("environments design step failed", exc_info=True)
                        # Re-count after design — both may still be 0 (a video
                        # with no recurring characters AND no distinct
                        # locations has nothing to gate; skip straight through
                        # rather than showing an empty "Characters x 0,
                        # Locations x 0" review with nothing to look at).
                        crow2 = await fetch_one(
                            "SELECT count(*) AS n FROM video_characters WHERE video_id=$1 AND tenant_id=$2",
                            video_id, tenant_id)
                        erow2 = await fetch_one(
                            "SELECT count(*) AS n FROM video_environments WHERE video_id=$1 AND tenant_id=$2",
                            video_id, tenant_id)
                        if int((crow2 or {}).get("n") or 0) == 0 and int((erow2 or {}).get("n") or 0) == 0:
                            await execute(
                                "UPDATE videos SET characters_approved_at = COALESCE(characters_approved_at, now()), "
                                "environments_approved_at = COALESCE(environments_approved_at, now()), "
                                "updated_at = now() WHERE id = $1 AND tenant_id = $2",
                                video_id, tenant_id)
                        else:
                            await _pause_for_approval_gate(
                                tenant_id, video_id, "anchors", target,
                                "The cast and locations are ready — waiting on you to take a "
                                "look before I draw the storyboards. Say the word (or tap "
                                "\"Looks good!\" in chat) when you're ready.",
                            )
                            return
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
                    # By the time execution reaches here the checkpoint above has already
                    # stamped both columns (via the approval_gate handshake, or the
                    # nothing-to-gate fallback just above) for every target=="pictures",
                    # non-static_docu video — this COALESCE is now a defensive backstop
                    # for every OTHER path that reaches this status (static_docu, and
                    # target=="finish" continuing a video from before this feature),
                    # unchanged from before.
                    await execute(
                        "UPDATE videos SET environments_approved_at = COALESCE(environments_approved_at, now()), "
                        "characters_approved_at = COALESCE(characters_approved_at, now()), "
                        "updated_at = now() WHERE id = $1 AND tenant_id = $2",
                        video_id, tenant_id)
                    # STATIC-DOCU videos take a compact three-view set per
                    # segment (no cast/story bible/full coverage): three-quarter,
                    # top-oblique, and engineering detail under one narration.
                    if (video.get("render_mode") or "") == "static_docu":
                        _set_task_status(
                            video_id, "running",
                            "Creating three complementary views per segment…",
                            tenant_id=tenant_id,
                        )

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
                                await ex.run_voice(
                                    video_id,
                                    progress_callback=_progress,
                                )  # best-effort; no voice key -> skip
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


_DOLLAR_RE = re.compile(r"\$?\s*(\d+(?:\.\d{1,2})?)")
_BUDGET_CLEAR_WORDS = frozenset({"none", "no cap", "no limit", "remove", "clear", "off", "unlimited"})


def _resolve_budget_cap_text(text: str) -> tuple[Optional[float], bool, bool]:
    """Returns (amount_or_None, is_clear, is_valid). C36 (checklist §3.3 item 3):
    plain-English -> videos.max_spend, for the copilot's "cap this video at $15"
    / "remove the cap". is_clear=True means "no cap" (max_spend -> NULL) —
    distinct from "couldn't parse an amount" (amount=None, is_valid=False)."""
    t = (text or "").strip().lower()
    if not t:
        return None, False, False
    if any(word in t for word in _BUDGET_CLEAR_WORDS):
        return None, True, True
    m = _DOLLAR_RE.search(t)
    if not m:
        return None, False, False
    amount = round(float(m.group(1)), 2)
    if amount <= 0:
        return None, False, False
    return amount, False, True


async def _runner_budget_cap(tenant_id, video_id, background_tasks, pending) -> str:
    """C36 (checklist §3.3 item 3): "cap this video at $15" / "remove the
    budget cap" — writes videos.max_spend, the SAME column and the SAME
    validation the New Video Advanced field's PATCH /api/videos/{id} uses —
    all three doors (chat, PATCH, UI field), one write path (migration 103).

    Free and reversible (say "remove the cap" to clear it back to unlimited)
    — no confirm card; setting a NUMBER never spends money by itself, it only
    changes what future paid-verb quotes/autobuild iterations check against."""
    text = (pending.get("change") or "").strip()
    amount, is_clear, is_valid = _resolve_budget_cap_text(text)
    if not is_valid:
        return ('What would you like the cap to be? e.g. "cap this video at $15", or '
                '"remove the cap" for no limit.')
    value = None if is_clear else amount
    await execute(
        "UPDATE videos SET max_spend = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
        value, video_id, tenant_id,
    )
    if value is None:
        return "Budget cap removed — no spending limit on this video."
    return (f"Budget cap set to ${value:.2f} for this video — I'll pause and tell you if a build "
            "would push past it instead of spending on.")


RUNNERS = {
    "advance": _runner_advance,
    "seo": _runner_seo,
    "approve_cast": _runner_approve_cast,
    "approve_environments": _runner_approve_environments,
    "skip_environments": _runner_skip_environments,
    "approve_scene": _runner_approve_scene,
    "camera_preset": _runner_camera_preset,
    "script_profile": _runner_script_profile,
    "budget_cap": _runner_budget_cap,
    "lock": _runner_lock,
    "unlock": _runner_unlock,
    "drive_push": _runner_drive_push,
    "drive_sync": _runner_drive_sync,
    "draft_pass": _runner_draft_pass,
    "finalize": _runner_finalize,
}
