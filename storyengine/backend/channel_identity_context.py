"""channel_identity_context.py — THE channel-identity POOL (chat channel-
identity rebuild, checklist P1).

Ryan's ruling: channel identity is a POOL, not five different surfaces each
re-deriving their own idea of "who this channel is". One canonical source;
every surface (chat, MCP, UI, pipeline) drinks from it. This module IS that
pool for the read side. It does not introduce any new learner or writer —
every field below is read from a table/module that already owns it:

  - dna              -> channel_dna._current_identity (channel_profiles.
                         channel_identity, the identity_builder/channel_format/
                         reference_video learners' shared JSONB column).
  - cast              -> projects.character_references + cast_locked, the
                         SAME columns pipeline_executor.run_characters reads
                         for the locked-channel-cast fast path.
  - format            -> channel_format.get_channel_format (visual_format +
                         format_locked, already merged/read-modify-write safe).
  - own_median_minutes -> median runtime of the tenant's OWN videos. Prefers
                         channel_videos.duration_seconds (real YouTube import
                         data); falls back to this tenant's own PIPELINE-
                         PRODUCED videos (scripts.voice_duration_seconds
                         summed per video, terminal statuses only, the same
                         DONE_STATUSES actions.py already defines) when
                         channel_videos is empty; None when neither has data.
                         This is the length anchor chat.py's
                         `_competitor_median_seconds` was NOT — that medians
                         `competitor_videos` (someone else's catalog); this
                         medians the tenant's OWN.
  - title_patterns    -> channel_patterns rows a human has CONFIRMED with
                         polarity='good' (channel_patterns.py) — proven title/
                         performance patterns, not a guess.
  - script_profiles   -> the global shared.profiles.script catalog (same
                         source routes/script_profiles.py's GET reads).
  - script_prompt_summary -> tenant_prompt_defaults's 'script' slot, ONLY
                         when the tenant has actually customized it (a
                         non-customized slot has nothing pool-worthy to say
                         beyond the neutral engine default already baked into
                         every prompt).

Every builder below is independently fail-soft (one section's DB hiccup can
never blow up the whole pool) and returns an empty-safe shape on failure —
matching channel_briefs.py's convention (this module's direct sibling: same
"small async functions returning a piece of a shared prompt", just structured
data instead of prompt-block strings, plus the ONE render function that turns
the structured pool into a prompt block).

`render_identity_brief` is THE canonical prompt block — the compact (~40
line) prose form that enters every chat turn. It opens with a hard precedence
law worded like discovery.py's own "OUR CHANNEL'S LOCKED FORMAT" block
(routes/discovery.py:852-858): our locked identity LEADS; a modeled reference
lends its TOPIC and appeal only, never its format, runtime, or titling.

P1 scope: pool + MCP verb + tests only. Nothing here wires chat (P2) or
touches actions.py's pipeline verbs.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from database import fetch_all, fetch_one

logger = logging.getLogger(__name__)

# Capped so the pool (and the rendered brief) can never grow unboundedly —
# same discipline identity.py's _standing_preferences_block and
# channel_briefs.py's brief builders already use.
_TITLE_PATTERNS_CAP = 8
_TITLE_PATTERNS_IN_BRIEF = 3
_HOOK_EXAMPLES_IN_BRIEF = 2
_SIGNATURE_PHRASES_IN_BRIEF = 3
_SCRIPT_PROMPT_SUMMARY_MAX_CHARS = 400
_STYLE_DESCRIPTION_MAX_CHARS = 320


# ---------------------------------------------------------------------------
# Section builders — each independently fail-soft, empty-safe on any error.
# ---------------------------------------------------------------------------

async def _dna_section(tenant_id) -> dict[str, Any]:
    """The learned channel DNA (voice/cadence/hook/structure/thumbnail/
    visual_format/reference_video_style), stripped of the provenance
    envelope (_sources/_history/_last_run) — this pool's consumers want the
    LEARNED FIELDS, not the write-history bookkeeping. Reuses channel_dna's
    own reader (channel_dna_meta.coerce_identity under the hood) rather than
    re-querying channel_profiles a second way."""
    try:
        from channel_dna import _current_identity
        from channel_dna_meta import ENVELOPE_KEYS

        identity = await _current_identity(tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_identity_context: dna section failed for tenant=%s: %s", tenant_id, e)
        return {}
    if not isinstance(identity, dict):
        return {}
    return {k: v for k, v in identity.items() if k not in ENVELOPE_KEYS}


async def _cast_section(tenant_id) -> list[dict[str, str]]:
    """Locked cast members only (`cast_locked` true, `always` members) — the
    brand-asset cast pipeline_executor.run_characters auto-attaches to every
    queued/autopilot video. An unlocked or empty cast returns []: nothing to
    lead with until the creator locks one."""
    try:
        proj = await fetch_one(
            "SELECT cast_locked, character_references FROM projects "
            "WHERE tenant_id = $1 LIMIT 1",
            tenant_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_identity_context: cast section failed for tenant=%s: %s", tenant_id, e)
        return []
    if not proj or not proj.get("cast_locked"):
        return []
    refs = proj.get("character_references")
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except (ValueError, TypeError):
            refs = []
    if not isinstance(refs, list):
        return []
    out: list[dict[str, str]] = []
    for c in refs:
        if not isinstance(c, dict) or not c.get("always", True):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        out.append({"name": name[:120], "description": (c.get("description") or "").strip()[:300]})
    return out


async def _format_section(tenant_id) -> dict[str, Any]:
    """The locked channel format (style/motion/segmentation/on_camera) —
    reuses channel_format.get_channel_format verbatim, no re-derivation."""
    try:
        from channel_format import get_channel_format

        fmt, locked = await get_channel_format(tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_identity_context: format section failed for tenant=%s: %s", tenant_id, e)
        return {"visual_format": {}, "locked": False}
    return {"visual_format": fmt if isinstance(fmt, dict) else {}, "locked": bool(locked)}


def _median(values: list[float]) -> Optional[float]:
    vals = sorted(v for v in values if v and v > 0)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


async def _own_median_minutes(tenant_id) -> Optional[float]:
    """Median runtime (minutes) of the tenant's OWN videos — the length
    anchor this pool exists to finally compute (no chat surface medians the
    tenant's own catalog today; chat.py's `_competitor_median_seconds`
    medians `competitor_videos`, someone else's catalog, the wrong pool per
    this chunk's brief).

    1. Prefer `channel_videos.duration_seconds` (real YouTube import data —
       migration 041/042, `duration_seconds INTEGER`, verified against the
       exact columns identity_builder.py's `_ranked_videos` already reads).
    2. Fall back to this tenant's own PIPELINE-PRODUCED videos: sum
       `scripts.voice_duration_seconds` per `video_id` (the real per-scene
       narration runtime render_static.py itself sums — see its own
       `total_duration_seconds` cursor), restricted to videos in a terminal
       DONE_STATUSES status (actions.py's own constant, reused rather than
       re-listing "rendered"/"uploaded"/... a second place), median across
       videos.
    3. None when neither source has usable data — never a fabricated 0.
    """
    try:
        row = await fetch_one(
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_seconds) AS med "
            "FROM channel_videos WHERE tenant_id = $1 AND duration_seconds > 0",
            tenant_id,
        )
        med = (row or {}).get("med")
        if med:
            return round(float(med) / 60.0, 1)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_identity_context: own-median (channel_videos) failed for tenant=%s: %s", tenant_id, e)

    try:
        from actions import DONE_STATUSES

        rows = await fetch_all(
            "SELECT SUM(s.voice_duration_seconds) AS total FROM scripts s "
            "JOIN videos v ON v.id = s.video_id AND v.tenant_id = s.tenant_id "
            "WHERE s.tenant_id = $1 AND v.status = ANY($2::text[]) "
            "AND s.voice_duration_seconds IS NOT NULL "
            "GROUP BY s.video_id HAVING SUM(s.voice_duration_seconds) > 0",
            tenant_id, list(DONE_STATUSES),
        )
        totals = [float(r["total"]) for r in (rows or []) if r.get("total")]
        med = _median(totals)
        if med:
            return round(med / 60.0, 1)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_identity_context: own-median (pipeline videos) failed for tenant=%s: %s", tenant_id, e)

    return None


async def own_median_minutes(tenant_id) -> Optional[float]:
    """Public entry point for `_own_median_minutes` (chat channel-identity
    rebuild, checklist P3) — the tenant's OWN median runtime in minutes, for
    callers that want just this one number without paying for the whole
    pool build (chat.py's `_stamp_length_default` length backstop). Thin
    wrapper so P1's existing tests keep pinning the private implementation
    directly while every OTHER caller imports this public name instead of
    reaching across modules for an underscore-prefixed function."""
    return await _own_median_minutes(tenant_id)


async def _title_patterns_section(tenant_id) -> list[dict[str, Any]]:
    """Confirmed, human-verified 'good'-polarity channel_patterns rows —
    proven title/performance patterns, never a proposed/unconfirmed guess.
    Capped, newest first (channel_patterns.list_patterns' own ordering)."""
    try:
        from channel_patterns import list_patterns

        rows = await list_patterns(tenant_id, polarity="good", status="confirmed")
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_identity_context: title patterns failed for tenant=%s: %s", tenant_id, e)
        return []
    out = []
    for r in (rows or [])[:_TITLE_PATTERNS_CAP]:
        pattern = (r.get("pattern") or "").strip()
        if pattern:
            out.append({"pattern": pattern, "evidence": r.get("evidence") or {}})
    return out


async def _script_profiles_section() -> list[dict[str, Any]]:
    """The global editorial-voice catalog (shared.profiles.script) — same
    sys.path-inserted import routes/script_profiles.py's GET already uses.
    Not tenant-scoped (it's a code registry, not tenant data); listed here
    so the pool can name which voices are AVAILABLE, not just the channel's
    current pick."""
    try:
        import sys
        from pathlib import Path

        pipeline_root = Path(__file__).resolve().parent.parent.parent / "skills" / "video-pipeline"
        if str(pipeline_root) not in sys.path:
            sys.path.insert(0, str(pipeline_root))
        from shared.profiles.script import DEFAULT_PROFILE_ID, list_profiles, load_script_profile

        out = []
        for profile_id in list_profiles():
            profile = load_script_profile(profile_id)
            if not profile:
                continue
            meta = profile.template_metadata
            out.append({
                "id": profile.profile_id,
                "display_name": (meta.display_name if meta and meta.display_name else profile.profile_name),
                "description": (meta.description if meta and meta.description else profile.description),
                "is_default": profile.profile_id == DEFAULT_PROFILE_ID,
            })
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_identity_context: script profiles catalog failed: %s", e)
        return []


async def _script_prompt_summary(tenant_id) -> Optional[str]:
    """The tenant's CUSTOM 'script' system-prompt override, truncated — only
    when they've actually customized it (`is_custom`). A non-customized slot
    is just the neutral engine default every prompt already carries, so
    there's nothing pool-worthy to surface. Reuses routes.system_prompts.
    list_prompts (the exact same custom-vs-default resolution GET
    /api/system-prompts and get_system_prompts' MCP tool already use) rather
    than re-querying tenant_prompt_defaults a second way."""
    try:
        from routes.system_prompts import list_prompts

        prompts = await list_prompts(tenant_id=tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_identity_context: script prompt summary failed for tenant=%s: %s", tenant_id, e)
        return None
    for p in prompts or []:
        if p.get("key") == "script" and p.get("is_custom"):
            text = (p.get("prompt") or "").strip()
            if text:
                return text[:_SCRIPT_PROMPT_SUMMARY_MAX_CHARS]
    return None


# ---------------------------------------------------------------------------
# The pool
# ---------------------------------------------------------------------------

async def build_identity_pool(tenant_id) -> dict[str, Any]:
    """Assemble THE channel-identity pool for `tenant_id`. Every field is
    None/empty-safe when missing — no section's absence (or DB hiccup)
    breaks the others, matching channel_briefs.py's fail-soft posture.

    Returns:
      {"dna": dict, "cast": list[{"name","description"}],
       "format": {"visual_format": dict, "locked": bool},
       "own_median_minutes": float | None,
       "title_patterns": list[{"pattern","evidence"}],
       "script_profiles": list[{"id","display_name","description","is_default"}],
       "script_prompt_summary": str | None}
    """
    dna = await _dna_section(tenant_id)
    cast = await _cast_section(tenant_id)
    fmt = await _format_section(tenant_id)
    own_median_minutes = await _own_median_minutes(tenant_id)
    title_patterns = await _title_patterns_section(tenant_id)
    script_profiles = await _script_profiles_section()
    script_prompt_summary = await _script_prompt_summary(tenant_id)

    return {
        "dna": dna,
        "cast": cast,
        "format": fmt,
        "own_median_minutes": own_median_minutes,
        "title_patterns": title_patterns,
        "script_profiles": script_profiles,
        "script_prompt_summary": script_prompt_summary,
    }


# ---------------------------------------------------------------------------
# The canonical prompt block
# ---------------------------------------------------------------------------

def _fmt_minutes(m: float) -> str:
    if m < 1:
        return f"{round(m * 60)} sec"
    whole = int(m)
    frac_sec = round((m - whole) * 60)
    if frac_sec == 0:
        return f"{whole} min"
    return f"{whole} min {frac_sec} sec"


def render_identity_brief(pool: dict[str, Any]) -> str:
    """THE canonical prompt block every surface that talks about the channel
    (starting with chat, P2) injects verbatim. Compact by construction
    (~<=40 lines) — this enters every chat turn, so it summarizes rather than
    dumping raw jsonb. Never raises: a missing/malformed pool renders a
    minimal-but-valid block, same fail-soft posture as every builder above.
    """
    pool = pool if isinstance(pool, dict) else {}
    dna = pool.get("dna") if isinstance(pool.get("dna"), dict) else {}
    cast = pool.get("cast") if isinstance(pool.get("cast"), list) else []
    fmt_section = pool.get("format") if isinstance(pool.get("format"), dict) else {}
    visual_format = fmt_section.get("visual_format") if isinstance(fmt_section.get("visual_format"), dict) else {}
    own_median = pool.get("own_median_minutes")
    title_patterns = pool.get("title_patterns") if isinstance(pool.get("title_patterns"), list) else []
    script_prompt_summary = pool.get("script_prompt_summary")

    law_line = (
        "OUR CHANNEL IDENTITY LEADS (hard law): everything below is OUR locked "
        "channel identity, not optional flavor. When modeling or referencing "
        "another video, that reference contributes its TOPIC and appeal ONLY — "
        "it NEVER changes our format, our runtime, or how we title a video. "
        "Those always come from below."
    )
    # Tracked separately from `lines` so the "nothing learned yet" fallback
    # can tell REAL identity content apart from the law line and the LENGTH
    # line, both of which are always present regardless of what's learned.
    lines: list[str] = []

    voice_bits = [
        dna.get("voice_tone"), dna.get("cadence"), dna.get("hook_style"), dna.get("structure"),
    ]
    voice_bits = [str(b).strip() for b in voice_bits if b and str(b).strip()]
    if voice_bits:
        lines.append("VOICE: " + " | ".join(voice_bits))

    style_desc = (dna.get("style_description") or "").strip()
    if style_desc:
        if len(style_desc) > _STYLE_DESCRIPTION_MAX_CHARS:
            style_desc = style_desc[:_STYLE_DESCRIPTION_MAX_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append("STYLE: " + style_desc)

    if isinstance(visual_format, dict) and visual_format:
        look_bits = [
            visual_format.get("style"), visual_format.get("motion"),
            visual_format.get("segmentation"), visual_format.get("on_camera"),
        ]
        look_bits = [str(b).strip() for b in look_bits if b and str(b).strip()]
        if look_bits:
            locked_tag = " (LOCKED)" if fmt_section.get("locked") else " (detected, not yet locked)"
            lines.append("LOOK/FORMAT" + locked_tag + ": " + " | ".join(look_bits))

    phrases = dna.get("signature_phrases")
    if isinstance(phrases, list) and phrases:
        top = [str(p).strip() for p in phrases[:_SIGNATURE_PHRASES_IN_BRIEF] if str(p).strip()]
        if top:
            lines.append("SIGNATURE PHRASES: " + "; ".join(top))

    hook_examples = dna.get("hook_examples")
    if isinstance(hook_examples, list) and hook_examples:
        for ex in hook_examples[:_HOOK_EXAMPLES_IN_BRIEF]:
            if isinstance(ex, dict) and ex.get("line"):
                lines.append(f'HOOK EXAMPLE: "{str(ex["line"]).strip()[:180]}"')

    if title_patterns:
        for tp in title_patterns[:_TITLE_PATTERNS_IN_BRIEF]:
            pattern = str(tp.get("pattern") or "").strip()
            if pattern:
                lines.append("TITLE PATTERN (confirmed): " + pattern[:220])

    if cast:
        cast_bits = []
        for c in cast:
            name = c.get("name") or "?"
            desc = c.get("description") or ""
            cast_bits.append(f"{name} — {desc}" if desc else name)
        lines.append("LOCKED CAST: " + "; ".join(cast_bits))

    if script_prompt_summary:
        lines.append("SCRIPT VOICE OVERRIDE (custom, in effect): " + script_prompt_summary[:200])

    # `lines` at this point holds ONLY real learned/locked content (voice,
    # style, look, phrases, hooks, title patterns, cast, script override) —
    # the law and LENGTH lines are assembled separately below so an empty
    # channel still gets an honest "nothing learned yet" line instead of a
    # law line followed only by a LENGTH line that reads like content.
    if not lines:
        lines.append(
            "(No channel identity learned yet — this is a fresh channel. Don't invent a voice, look, "
            "or cast; ask, or default to neutral craft until one is learned/locked.)"
        )

    if own_median is not None:
        length_line = (
            f"LENGTH: our videos run ~{_fmt_minutes(float(own_median))} — recommended length comes "
            "from THIS, not from any reference video."
        )
    else:
        length_line = (
            "LENGTH: no runtime history yet for this channel's own videos — don't anchor length on a "
            "reference video's runtime; ask or use a sensible default instead."
        )

    return "\n".join([law_line, *lines, length_line])
