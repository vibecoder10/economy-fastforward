"""Unified Channel-DNA ingestion orchestrator (checklist C41 · P4.1b).

Ryan's "learn this channel" ask (tasks/decisions.md 2026-07-19 "Phase 4
Pillar 1"): point the system at a channel and have it run EVERY learner that
already exists, instead of the operator having to know that voice/hooks/
structure live in identity_builder, house-script format lives in
script_templates, the visual "kind of video" lives in channel_format, and a
one-off reference video's style has never persisted anywhere. This module is
the single sequencing entry point C42 (the chat front door + confirmable
digest card) calls — it does NOT introduce any new learner logic; every step
below just calls the existing learner and reshapes its result into one
digest-ready contract.

Learners run, in order:
  1. (optional) import — ``routes.onboarding._import_channel_videos``, reused
     as-is (now returns a saved-count instead of None — see that module),
     when a ``channel_url`` is given. Without one, learning proceeds against
     whatever the tenant already has in ``channel_videos``.
  2. identity_builder.build_channel_identity — the heavyweight learner:
     voice/cadence/hook/structure/research_approach/thumbnail_style, straight
     from the tenant's own top videos' transcripts. Already writes through
     channel_dna_meta.stamp_identity_write (checklist C40), so its result is
     already persisted+provenance-stamped by the time this function returns.
  3. (optional) script_templates.analyze_and_save_template, when the caller
     supplies an example script — DELETE-then-INSERT single-slot semantics,
     surfaced explicitly ("replaced" vs "saved").
  4. channel_format.set_channel_format — locks the visual_format
     identity_builder detected, but ONLY when confident (see
     ``_format_confident``); otherwise surfaces the detection without
     locking, so a single ambiguous video can't wedge every future bare-title
     build into the wrong format (channel_format.apply_format_defaults reads
     the lock unconditionally).
  5. (optional) a reference video, when the caller supplies one — reuses
     routes.model_video's extraction fallback chain (YouTube Data API/yt-dlp
     -> oEmbed) and its ``_distill_dna`` Claude call, then folds the result
     into channel_identity under a NEW field (``reference_video_style``) via
     the SAME stamp_identity_write helper, tagged ``learner="reference_video"``
     — closing the audit finding that Model A Video's DNA never persisted
     past the one video it was modeling.

Concurrency: the whole run is wrapped in a channel-level (video-less) claim —
``generation_claims.acquire_channel(tenant_id, "dna")`` (added this chunk,
migration 104) — so two ``learn_channel`` calls for the same tenant, or a
learn racing an identity-editing chat op sharing the "dna" stage, can't
interleave their read-modify-write onto the same ``channel_identity`` column
(the exact race C40's decisions.md note flagged as future work for this
chunk). Released in a ``finally`` — never wedges past the acquire() call's
own 2h stale sweep even if a learner raises.

Fail-soft per learner (checklist requirement): a transcript-fetch failure,
missing API key, or bad LLM JSON for ONE learner never aborts the others —
each returns its own ``{status, summary, fields_written, error}`` and the
sequence continues. The only fail-CLOSED path is the claim itself (busy ->
the whole call is refused before any learner runs, mirroring
generation_claims' existing money-safety discipline for video-scoped work).

Cost per run (tenant's own key — BYOK, no new paid integration): identity_
builder is the expensive one — up to (top_n + 4) Firecrawl scrape attempts
(2 modes each) to land top_n=3 transcripts, one Claude distill call
(~2200 max_tokens) and, if any thumbnails were found, one Claude vision call
(~1400 max_tokens) — call it 1-2 Claude calls plus Firecrawl credits
(external, not in docs/cost-awareness.md's table). script_template (only
with an example) adds one Claude call (~1200 max_tokens). reference_video
(only with a reference URL) adds up to two Claude calls (~2048 max_tokens,
one retry on malformed JSON). Worst case (all three optional inputs given):
~4-5 Claude calls, roughly $0.05-$0.30 per cost-awareness.md's "~$0.01-0.05/
call" Sonnet/Haiku figures, plus Firecrawl scrape credits. channel_format and
the import step make no LLM calls at all.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

import generation_claims
from channel_dna_meta import ENVELOPE_KEYS, coerce_identity, stamp_identity_write
from database import execute, fetch_one

logger = logging.getLogger(__name__)

CLAIM_STAGE = "dna"
CLAIMED_BY = "channel_dna:learn_channel"


def _learner_result(
    status: str, summary: str, fields_written: Optional[list] = None, error: Optional[str] = None
) -> dict[str, Any]:
    return {
        "status": status,  # "learned" | "skipped" | "failed"
        "summary": summary,
        "fields_written": fields_written or [],
        "error": error,
    }


async def _current_identity(tenant_id: str) -> dict:
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    return coerce_identity((row or {}).get("channel_identity"))


async def _write_field(tenant_id: str, fields: dict[str, Any], learner: str) -> dict:
    """Small standalone writer for learners (today only reference_video) that
    aren't one of the three pre-existing channel_identity writers — goes
    through the exact same read-modify-write + stamp as every other writer
    (channel_dna_meta's whole point), scoped to just the fields it's adding."""
    current = await _current_identity(tenant_id)
    merged = stamp_identity_write(current, fields, learner=learner)
    await execute(
        """INSERT INTO channel_profiles (tenant_id, channel_identity)
           VALUES ($1, $2::jsonb)
           ON CONFLICT (tenant_id) DO UPDATE SET channel_identity = $2::jsonb,
               updated_at = now()""",
        tenant_id, json.dumps(merged),
    )
    return merged


# ---------------------------------------------------------------------------
# Step 1 — optional import of a channel that isn't the tenant's own yet
# ---------------------------------------------------------------------------

async def _run_import(tenant_id: str, channel_url: str) -> dict:
    from routes.onboarding import _extract_channel_id_from_url, _import_channel_videos

    identifier = _extract_channel_id_from_url(channel_url)
    if not identifier:
        return _learner_result(
            "failed",
            "Couldn't parse that as a YouTube channel URL — use a format like youtube.com/@ChannelName.",
            error="unparseable channel URL",
        )
    try:
        saved = await _import_channel_videos(tenant_id, channel_url, identifier)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_dna: import failed for %s (tenant=%s): %s", channel_url, tenant_id, e)
        return _learner_result("failed", "Couldn't import that channel's videos.", error=str(e))
    if not saved:
        return _learner_result(
            "failed",
            "Couldn't find any videos for that channel — it may be private, or YouTube blocked the request "
            "from our server (see docs/env-vars.md YTDLP_COOKIES_FILE/YTDLP_PROXY).",
            error="zero videos imported",
        )
    return _learner_result(
        "learned", f"Imported {saved} video(s) from the channel.", fields_written=["channel_videos"]
    )


# ---------------------------------------------------------------------------
# Step 2 — identity_builder (the heavyweight learner)
# ---------------------------------------------------------------------------

async def _run_identity_builder(tenant_id: str) -> tuple[dict, Optional[dict], list]:
    """Returns (learner_result, visual_format_or_None, videos_analyzed) — the
    latter two feed step 4's lock-confidence decision."""
    from identity_builder import build_channel_identity

    try:
        result = await build_channel_identity(tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_dna: identity_builder crashed for tenant=%s: %s", tenant_id, e)
        return (
            _learner_result(
                "failed", "Couldn't learn your channel's voice, hooks, or structure this pass.", error=str(e)
            ),
            None,
            [],
        )
    if not result.get("ok"):
        err = result.get("error") or "unknown error"
        return (
            _learner_result(
                "failed",
                f"Couldn't fetch transcripts — {err}. Here's what I could still learn from the other steps.",
                error=err,
            ),
            None,
            [],
        )
    identity = result.get("identity") or {}
    videos_analyzed = result.get("videos_analyzed") or []
    fields_written = sorted(k for k in identity.keys() if k not in ENVELOPE_KEYS)
    summary = (
        f"Learned voice, cadence, hooks, and structure"
        + (", plus a thumbnail formula" if identity.get("thumbnail_style") else "")
        + f" from {len(videos_analyzed)} of your top video(s)."
    )
    return (
        _learner_result("learned", summary, fields_written=fields_written),
        identity.get("visual_format") if isinstance(identity.get("visual_format"), dict) else None,
        videos_analyzed,
    )


# ---------------------------------------------------------------------------
# Step 3 — optional example-script house format
# ---------------------------------------------------------------------------

async def _run_script_template(tenant_id: str, example_script_text: str) -> dict:
    from routes.script_templates import analyze_and_save_template

    existing = await fetch_one("SELECT id FROM script_templates WHERE tenant_id = $1 LIMIT 1", tenant_id)
    try:
        await analyze_and_save_template(tenant_id, example_script_text, name="House format")
    except ValueError as e:
        return _learner_result("failed", str(e), error=str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_dna: script template analysis failed for tenant=%s: %s", tenant_id, e)
        return _learner_result(
            "failed", "Couldn't distill a script format from that example.", error=str(e)
        )
    fields_written = ["structure", "example_excerpt"]
    if existing:
        return _learner_result(
            "learned",
            "Replaced your existing house script template with this new example (single-slot: only "
            "one house template is kept at a time).",
            fields_written=fields_written,
        )
    return _learner_result(
        "learned", "Saved your house script template from this example.", fields_written=fields_written
    )


# ---------------------------------------------------------------------------
# Step 4 — channel format lock (confidence-gated)
# ---------------------------------------------------------------------------

def _format_confident(visual_format: Optional[dict], videos_analyzed: list) -> bool:
    """Lock the channel format only when identity_builder both detected the
    two load-bearing fields (style, motion) AND saw at least 2 corroborating
    videos. This is the "lock only if confident" gate the checklist calls
    for: channel_format.apply_format_defaults reads format_locked
    unconditionally on every future bare-title build (queue/autopilot/chat),
    so a single ambiguous video committing the whole channel to the wrong
    format would be a worse outcome than just surfacing the detection
    unlocked for the creator to confirm."""
    if not isinstance(visual_format, dict):
        return False
    return bool(visual_format.get("style")) and bool(visual_format.get("motion")) and len(videos_analyzed) >= 2


async def _run_channel_format(tenant_id: str, visual_format: Optional[dict], videos_analyzed: list) -> dict:
    from channel_format import FORMAT_FIELDS, set_channel_format

    if not visual_format:
        return _learner_result(
            "skipped", "No visual format detected to lock (identity learning found nothing usable)."
        )
    if not _format_confident(visual_format, videos_analyzed):
        style = visual_format.get("style") or "an unclear style"
        return _learner_result(
            "skipped",
            f"Detected a possible format ({style}) but not confidently enough across enough videos to "
            "lock it in — confirm it in chat if it looks right.",
        )
    fields = {k: visual_format.get(k) for k in FORMAT_FIELDS}
    try:
        locked = await set_channel_format(tenant_id, fields)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_dna: channel_format lock failed for tenant=%s: %s", tenant_id, e)
        return _learner_result("failed", "Couldn't lock the detected channel format.", error=str(e))
    return _learner_result(
        "learned",
        f"Locked your channel format: {locked.get('style') or '?'} / {locked.get('motion') or '?'}.",
        fields_written=["visual_format", "format_locked"],
    )


# ---------------------------------------------------------------------------
# Step 5 — optional reference-video style fold-in
# ---------------------------------------------------------------------------

async def _run_reference_video(tenant_id: str, reference_video_url: str) -> dict:
    import asyncio

    from routes.model_video import (
        _distill_dna,
        _fetch_transcript_supadata,
        _oembed_fallback,
        _parse_youtube_id,
        _resolve_claude_creds,
    )
    from routes.niche import _extract_video_info

    youtube_id = _parse_youtube_id(reference_video_url)
    if not youtube_id:
        return _learner_result(
            "failed", "Couldn't parse that as a YouTube video URL.", error="unparseable video URL"
        )

    creds = await _resolve_claude_creds(tenant_id)
    if not creds:
        return _learner_result(
            "failed",
            "No Claude-capable API key configured — add an Anthropic or Kie.ai key in Settings -> Keys.",
            error="no credentials",
        )

    info = await asyncio.to_thread(_extract_video_info, youtube_id)
    if not info or not info.get("title"):
        info = await _oembed_fallback(youtube_id)
    if not info or not info.get("title"):
        return _learner_result("failed", "Couldn't fetch that reference video.", error="extraction failed")

    transcript = info.get("transcript")
    if not transcript:
        transcript = await _fetch_transcript_supadata(youtube_id)

    try:
        dna = await _distill_dna(
            creds, info, transcript or info.get("description") or info.get("title") or ""
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "channel_dna: reference-video distill failed for %s (tenant=%s): %s",
            reference_video_url, tenant_id, e,
        )
        return _learner_result(
            "failed", "Style analysis of the reference video was unavailable.", error=str(e)
        )
    if not dna:
        return _learner_result(
            "failed", "Style analysis of the reference video returned nothing usable.", error="empty distill result"
        )

    fields = {
        "reference_video_style": {
            "source_url": reference_video_url,
            "source_title": info.get("title"),
            "summary": dna.get("summary"),
            "metadata": dna.get("structured_metadata"),
        }
    }
    await _write_field(tenant_id, fields, learner="reference_video")
    return _learner_result(
        "learned",
        f"Folded style notes from the reference video (\"{info.get('title')}\") into your channel DNA.",
        fields_written=["reference_video_style"],
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def learn_channel(
    tenant_id: str,
    *,
    channel_url: Optional[str] = None,
    example_script_text: Optional[str] = None,
    reference_video_url: Optional[str] = None,
    progress_cb: Optional[Callable[[str], Any]] = None,
) -> dict[str, Any]:
    """Run every existing channel-DNA learner in sequence for ``tenant_id``.

    - ``channel_url=None`` learns from whatever's already in this tenant's
      ``channel_videos`` (their own imported channel). A URL — whether it's
      their own or someone else's — is imported first (idempotent: see
      ``routes.onboarding._import_channel_videos``'s ON CONFLICT upsert), so
      a not-my-channel URL always has fresh video rows for identity_builder
      to rank before it runs.
    - ``example_script_text`` and ``reference_video_url`` are both optional;
      omitting either just marks that learner "skipped" in the result.
    - ``progress_cb`` is called (sync or async both fine) with a short
      human-readable string before each learner step — for C42's ack-now
      background-task UX. Never allowed to raise into the orchestrator.

    Returns the digest-ready contract C42 renders as a confirmable card:
    ``{"ok": bool, "busy": bool, "error": str|None,
       "learners": {name: {"status", "summary", "fields_written", "error"}},
       "identity": <current channel_identity dict, with _sources/_history>}``.
    """

    async def _progress(message: str) -> None:
        if not progress_cb:
            return
        try:
            maybe_awaitable = progress_cb(message)
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable
        except Exception:  # noqa: BLE001
            logger.warning("channel_dna: progress_cb raised, ignoring", exc_info=True)

    acquired = await generation_claims.acquire_channel(tenant_id, CLAIM_STAGE, claimed_by=CLAIMED_BY)
    if not acquired:
        return {
            "ok": False,
            "busy": True,
            "error": "Already learning this channel's DNA — try again in a moment.",
            "learners": {},
            "identity": await _current_identity(tenant_id),
        }

    learners: dict[str, dict] = {}
    try:
        if channel_url:
            await _progress("Importing channel videos…")
            learners["import_channel_videos"] = await _run_import(tenant_id, channel_url)
        else:
            learners["import_channel_videos"] = _learner_result(
                "skipped", "Learning from your already-imported channel videos."
            )

        await _progress("Learning voice, hooks, and structure…")
        identity_learner, visual_format, videos_analyzed = await _run_identity_builder(tenant_id)
        learners["identity_builder"] = identity_learner

        if example_script_text:
            await _progress("Distilling your example script's format…")
            learners["script_template"] = await _run_script_template(tenant_id, example_script_text)
        else:
            learners["script_template"] = _learner_result("skipped", "No example script provided.")

        await _progress("Checking the detected channel format…")
        learners["channel_format"] = await _run_channel_format(tenant_id, visual_format, videos_analyzed)

        if reference_video_url:
            await _progress("Distilling the reference video's style…")
            learners["reference_video"] = await _run_reference_video(tenant_id, reference_video_url)
        else:
            learners["reference_video"] = _learner_result("skipped", "No reference video provided.")

        identity = await _current_identity(tenant_id)
        ok = any(l["status"] == "learned" for l in learners.values())
        return {"ok": ok, "busy": False, "error": None, "learners": learners, "identity": identity}
    finally:
        await generation_claims.release_channel(tenant_id, CLAIM_STAGE)
