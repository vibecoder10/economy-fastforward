"""Originality engine — make AI slop structurally impossible.

This is the foundation of StoryEngine's "good by construction" defense against
YouTube's inauthentic-content demonetization policy (the July 2025 rename of the
"repetitious content" rule, enforced hard through 2026). The design rule, set by
Ryan: there are NO user-facing gates, blocks, or warnings. Slop must be
impossible to *produce*, so the creator never has to think about it.

This module does two jobs, both meant to run INSIDE generation:

  1. Diversity input — ``summarize_recent_for_prompt`` turns a channel's recent
     videos into a compact "do not repeat these" block that gets fed into the
     title / hook / script / thumbnail generators. Each new video is then forced
     to diverge from its channel's history by construction, not checked after.

  2. Silent self-check — ``assess_draft`` runs one Claude Sonnet call to judge a
     fresh draft against the channel's recent work: does it genuinely differ,
     and does it carry a real point of view (YouTube's "significant original
     value")? A generation step uses the verdict to decide whether to quietly
     re-roll. The verdict is internal only — never surfaced to the creator.

Two walls and one label (see ../MONETIZATION-SAFETY-PLAN.md):
  - Wall 1 (per-video originality): ``has_point_of_view``.
  - Wall 2 (a genuinely new plot every time): ``distinct_plot``. The channel's
    look, format, and title style MAY stay consistent — that is its brand and is
    fine. Only the PLOT (story, events, arc) must be completely different from
    recent videos.
  - The label (AI disclosure) is handled separately, at the upload stage.

Model: claude-sonnet-4-6 via a direct Anthropic cloud call (the same pattern as
claude_orchestrator.py — ``anthropic.Anthropic()`` reads ANTHROPIC_API_KEY).
This path deliberately does NOT route through the Kie.ai gateway, so it keeps
working even when a tenant's Kie account is unavailable.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Ryan's call: Claude Sonnet, direct cloud. Exact ID, no date suffix.
MODEL = "claude-sonnet-4-6"

# How many recent videos a new one is asked to diverge from. Tunable.
DEFAULT_HISTORY_WINDOW = 10

# Compact truncation lengths for fingerprints (keep prompts cheap).
_TITLE_TRUNC = 120
_HOOK_TRUNC = 240
_SCRIPT_EXCERPT_TRUNC = 600
_THUMB_TRUNC = 220


# ---------------------------------------------------------------------------
# Fingerprints — the compact per-video record other generations diverge from.
# ---------------------------------------------------------------------------

def _truncate(text: Optional[str], limit: int) -> str:
    """Collapse whitespace and cap length for compact prompt inclusion."""
    if not text:
        return ""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def build_fingerprint(video: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact fingerprint from a ``videos`` table row dict.

    Pulls only what the diversity block and the judge need — title, hook, a
    short script excerpt, the thumbnail concept, and the look. Resilient to
    missing columns (a half-built video still produces a usable fingerprint).
    """
    script = video.get("script") or ""
    hook = (
        video.get("executive_hook")
        or video.get("hook_script")
        or script[: _HOOK_TRUNC + 1]
    )
    return {
        "video_id": str(video.get("id") or ""),
        "title": _truncate(video.get("video_title"), _TITLE_TRUNC),
        "hook": _truncate(hook, _HOOK_TRUNC),
        "script_excerpt": _truncate(script, _SCRIPT_EXCERPT_TRUNC),
        "thumbnail": _truncate(video.get("thumbnail_prompt"), _THUMB_TRUNC),
        "visual_style": _truncate(
            video.get("visual_style") or video.get("image_style_override"), 80
        ),
        "created_at": str(video.get("created_at") or ""),
    }


async def load_recent_fingerprints(
    tenant_id: str,
    *,
    exclude_video_id: Optional[str] = None,
    limit: int = DEFAULT_HISTORY_WINDOW,
) -> List[Dict[str, Any]]:
    """Load fingerprints for a tenant's most recent (non-deleted) videos.

    Imported lazily so this module can be imported and unit-tested without a DB.
    """
    from database import fetch_all  # local import: keeps the module DB-optional

    rows = await fetch_all(
        """SELECT id, video_title, executive_hook, hook_script, script,
                  thumbnail_prompt, visual_style, image_style_override, created_at
             FROM videos
            WHERE tenant_id = $1
              AND deleted_at IS NULL
              AND ($2::uuid IS NULL OR id <> $2::uuid)
            ORDER BY created_at DESC
            LIMIT $3""",
        tenant_id,
        exclude_video_id,
        limit,
    )
    return [build_fingerprint(r) for r in rows]


# ---------------------------------------------------------------------------
# Diversity input — the block fed INTO generators so they diverge by design.
# ---------------------------------------------------------------------------

def summarize_recent_for_prompt(
    fingerprints: List[Dict[str, Any]],
    *,
    max_items: int = DEFAULT_HISTORY_WINDOW,
) -> str:
    """Render the channel's recent PLOTS as a 'do not reuse any of these' block.

    The channel's look, format, and title style MAY stay consistent — that is
    its brand, and looking similar is fine. What must be completely different
    every time is the PLOT: the story, the events, the arc. Drop this into a
    script or title prompt so the new video is forced onto a genuinely new plot.
    Returns "" when there is no history.
    """
    items = [f for f in (fingerprints or []) if f][:max_items]
    if not items:
        return ""

    lines = [
        "=== PLOTS THIS CHANNEL HAS ALREADY USED — DO NOT REUSE ANY OF THEM ===",
        "",
        "Keep the channel's look, format, and title style consistent — that is "
        "its brand, and looking similar across videos is completely fine. What "
        "must be COMPLETELY DIFFERENT from every entry below is the PLOT: the "
        "story, the events, the arc. YouTube demonetizes channels that recycle "
        "one plot with the nouns swapped. The video you create now must tell a "
        "story that shares nothing essential with any plot below — a genuinely "
        "new plot, not an old one relabeled.",
        "",
        "Plots already used (newest first):",
    ]
    for i, fp in enumerate(items, 1):
        plot = fp.get("script_excerpt") or fp.get("hook") or ""
        title = fp.get("title") or "(untitled)"
        lines.append(f'{i}. "{title}" — {plot}' if plot else f'{i}. "{title}"')
    lines.append("")
    lines.append("=== END USED PLOTS ===")
    return "\n".join(lines)


# Wall 1 — per-video originality. Appended to the script prompt for EVERY
# channel (custom override or neutral template), so a genuine point of view is
# non-negotiable by construction. Applies even to a channel's first video.
POINT_OF_VIEW_MANDATE = (
    "=== NON-NEGOTIABLE: WRITE WITH A REAL POINT OF VIEW ===\n"
    "\n"
    "This script must carry a genuine human angle — an opinion, a stance, a "
    "specific insight, or a personal read on the subject — not flat, neutral, "
    "encyclopedia narration that any template could produce. YouTube demonetizes "
    "'mass-produced' videos that add no original perspective; a real point of "
    "view is what makes this video unmistakably this channel's. Take a position "
    "and back it with specifics. Never just list facts."
)


# Thumbnails: the channel's STYLE may repeat (brand), but a stamped-from-one-mold
# TEMPLATE (same layout/composition every time) is a slop signal. Appended to the
# thumbnail prompt for EVERY video, like the point-of-view mandate is for scripts.
THUMBNAIL_ANTI_TEMPLATE = (
    "=== THUMBNAILS: KEEP THE STYLE, NEVER REUSE A TEMPLATE ===\n"
    "\n"
    "This channel's visual STYLE should stay consistent — the same art style, the "
    "same palette family, the same overall feel is good branding and is fine. But "
    "the thumbnail must NOT be a repeated TEMPLATE: the same layout, the same "
    "composition, the same fixed arrangement of text and subject every time. "
    "YouTube flags channels whose thumbnails look stamped from one mold. Within "
    "the channel's style, make the COMPOSITION genuinely different each time — "
    "vary the layout, the framing, the subject's placement and scale, the angle, "
    "and where (or whether) text sits. Same style, new composition."
)


def _summarize_recent_thumbnails(
    fingerprints: List[Dict[str, Any]],
    *,
    max_items: int = DEFAULT_HISTORY_WINDOW,
) -> str:
    """List recent thumbnail COMPOSITIONS so the new one avoids reusing a layout."""
    items = [f for f in (fingerprints or []) if f.get("thumbnail")][:max_items]
    if not items:
        return ""
    lines = [
        "Thumbnail compositions already used — keep the style, but do NOT repeat "
        "any of these layouts/compositions:",
    ]
    for i, fp in enumerate(items, 1):
        lines.append(f'{i}. {fp["thumbnail"]}')
    return "\n".join(lines)


def build_generation_guardrails(
    kind: str,
    fingerprints: List[Dict[str, Any]],
    *,
    max_items: int = DEFAULT_HISTORY_WINDOW,
) -> str:
    """Return slop-proofing text to APPEND to a generator's system prompt.

    This is the prevention layer: it bakes Wall 1 (point of view) and Wall 2 (a
    genuinely new PLOT, distinct from recent videos) into the prompt so the
    generator produces an original draft by construction — no gate, no re-roll
    needed in the common case. The channel's look/format may stay consistent;
    only the plot must differ. Returns "" when there is nothing to add.

    ``kind`` is "script", "title", or "thumbnail". For script/title the rule is a
    genuinely new PLOT; for thumbnail the rule is a new COMPOSITION within a
    consistent style (never a repeated template). Appending the result to a
    resolved system prompt is always safe (it adds text, never reformats).
    """
    parts: List[str] = []
    if kind == "script":
        parts.append(POINT_OF_VIEW_MANDATE)  # Wall 1, always
        recent_block = summarize_recent_for_prompt(fingerprints, max_items=max_items)
        if recent_block:
            parts.append(recent_block)       # Wall 2 (new plot), when history
    elif kind == "title":
        recent_block = summarize_recent_for_prompt(fingerprints, max_items=max_items)
        if recent_block:
            parts.append(recent_block)
    elif kind == "thumbnail":
        parts.append(THUMBNAIL_ANTI_TEMPLATE)  # style stays, composition varies
        thumbs = _summarize_recent_thumbnails(fingerprints, max_items=max_items)
        if thumbs:
            parts.append(thumbs)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Silent self-check — the internal re-roll signal (never user-facing).
# ---------------------------------------------------------------------------

class OriginalityVerdict(BaseModel):
    """Internal-only assessment of a fresh draft against channel history.

    ``verdict`` is the single dial a generation step reads: ``red`` means the
    draft is a near-duplicate, generic, or has no point of view — quietly
    re-roll it (feeding ``divergence_suggestion`` back in). ``yellow`` is
    borderline (ship it, optionally log). ``green`` ships. NONE of this is shown
    to the creator.
    """

    distinct_plot: bool = True          # Wall 2 — a genuinely new plot vs recent
    has_point_of_view: bool = True      # Wall 1 — carries a real angle/insight
    is_generic: bool = False            # reads as templated AI slop
    verdict: str = "green"              # green | yellow | red  (internal only)
    reasons: List[str] = Field(default_factory=list)
    divergence_suggestion: str = ""     # how to make a re-roll genuinely differ

    @property
    def needs_reroll(self) -> bool:
        return (self.verdict or "").strip().lower() == "red"


_JUDGE_SYSTEM = (
    "You are an internal originality check inside an AI video engine. Your output "
    "is consumed by code, never shown to a human. Your job is to protect the "
    "channel from YouTube's inauthentic-content demonetization policy, which "
    "punishes channels that recycle the same PLOT across uploads, or that add no "
    "genuine human point of view.\n"
    "\n"
    "IMPORTANT: a consistent LOOK, FORMAT, and TITLE STYLE across a channel's "
    "videos is normal branding and is completely fine — do NOT penalize it. The "
    "ONLY cross-video thing that matters is the PLOT: the story, the events, the "
    "arc. Two videos that look identical but tell genuinely different stories are "
    "good. Two videos that look different but tell the same story (the same plot "
    "with the nouns swapped, or the same template — e.g. a 'facts about X' "
    "listicle redone for a new X) are the problem.\n"
    "\n"
    "Judge the NEW DRAFT on two things:\n"
    "1. distinct_plot — Is its PLOT completely different from every recent video "
    "below? A new topic poured into the same story template is NOT a distinct "
    "plot. A genuinely new story is.\n"
    "2. has_point_of_view — Does it carry a genuine angle, opinion, or insight (a "
    "real human perspective), not flat encyclopedia narration any template could "
    "produce?\n"
    "Also set is_generic = true if the draft reads like mass-produced AI slop "
    "regardless of the channel history.\n"
    "\n"
    "Decide verdict:\n"
    "- red: the plot reuses/recycles a recent plot or a repeated template, OR the "
    "draft is generic slop, OR it has no real point of view. Must be re-rolled.\n"
    "- yellow: borderline — ships, but the plot is noticeably close to a recent "
    "one.\n"
    "- green: a genuinely new plot AND a real point of view (a consistent look or "
    "title style does NOT lower this).\n"
    "\n"
    "If verdict is red or yellow, write divergence_suggestion: one or two concrete "
    "sentences proposing a genuinely DIFFERENT plot/story for the next attempt — "
    "never just 'change the topic', and never about the look or title format.\n"
    "\n"
    "Return ONLY a JSON object with these keys, no markdown, no prose:\n"
    "{\"distinct_plot\": bool, \"has_point_of_view\": bool, "
    "\"is_generic\": bool, \"verdict\": \"green|yellow|red\", "
    "\"reasons\": [string, ...], \"divergence_suggestion\": string}"
)


def _build_judge_user_prompt(
    kind: str,
    draft: Dict[str, Any],
    recent: List[Dict[str, Any]],
) -> str:
    recent_block = summarize_recent_for_prompt(recent) or (
        "(No recent videos — this is among the channel's first. Judge only on "
        "whether the draft is generic slop and whether it has a point of view.)"
    )
    draft_lines = [f"NEW DRAFT (kind: {kind}):"]
    for key in ("title", "hook", "script", "script_excerpt", "thumbnail"):
        val = draft.get(key)
        if val:
            draft_lines.append(f"- {key}: {_truncate(val, 1500)}")
    return f"{recent_block}\n\n" + "\n".join(draft_lines)


def _extract_json(text: str) -> str:
    """Pull a JSON object out of a model response (handles ``` fences)."""
    if not text:
        return "{}"
    t = text.strip()
    if "```" in t:
        # take the content of the first fenced block
        block = t.split("```", 2)[1]
        if block.startswith("json"):
            block = block[4:]
        t = block.strip()
    start, end = t.find("{"), t.rfind("}")
    return t[start : end + 1] if start != -1 and end != -1 else t


def _client():
    import anthropic  # local import: keeps the module importable without the SDK

    return anthropic.Anthropic()


def assess_draft(
    kind: str,
    draft: Dict[str, Any],
    recent: List[Dict[str, Any]],
    *,
    model: str = MODEL,
    max_tokens: int = 900,
) -> OriginalityVerdict:
    """Assess a fresh draft against the channel's recent work (one Sonnet call).

    ``kind`` is a label like "title", "hook", "script", or "thumbnail".
    ``draft`` is a dict of the relevant fields (e.g. {"title", "hook", "script"}).
    ``recent`` is a list of fingerprints from ``load_recent_fingerprints``.

    Fails OPEN: on any error this returns a green verdict so a transient model or
    network problem never blocks generation. (Prevention via diversity-forced
    prompts is the primary defense; this check is the backstop.)
    """
    try:
        client = _client()
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_JUDGE_SYSTEM,
            messages=[
                {"role": "user", "content": _build_judge_user_prompt(kind, draft, recent)}
            ],
        )
        text = "".join(
            getattr(block, "text", "") for block in resp.content
            if getattr(block, "type", "") == "text"
        )
        data = json.loads(_extract_json(text))
        return OriginalityVerdict(**data)
    except Exception:
        return OriginalityVerdict(
            verdict="green",
            reasons=["originality check unavailable — failed open"],
        )


# ---------------------------------------------------------------------------
# Self-test — proves the live Sonnet cloud call + the judge's discrimination.
#   python3 originality.py            (loads ANTHROPIC_API_KEY from ../../.env)
# ---------------------------------------------------------------------------

def _load_key_for_selftest() -> None:
    import os
    from pathlib import Path

    if os.getenv("ANTHROPIC_API_KEY"):
        return
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return


def _selftest() -> None:
    _load_key_for_selftest()

    # Three videos with a CONSISTENT look + title style (the channel's brand),
    # each a DIFFERENT plot. A consistent look is fine — only the plot matters.
    recent = [
        {
            "id": "1", "video_title": "The Day the Lighthouse Went Dark",
            "script": "A keeper on a storm-battered island realizes the lamp has "
                      "failed on the worst night of the year, and rows out to warn "
                      "a fishing boat heading for the rocks.",
            "visual_style": "warm painterly 3D, soft light",
        },
        {
            "id": "2", "video_title": "The Day the Bakery Caught Fire",
            "script": "A baker discovers her oven is faulty minutes before the "
                      "morning rush and must choose between saving the shop or the "
                      "stray cat trapped in the back room.",
            "visual_style": "warm painterly 3D, soft light",
        },
        {
            "id": "3", "video_title": "The Day the Train Never Came",
            "script": "A boy waits at a rural station for a grandfather who never "
                      "arrives, and pieces together what happened from the "
                      "stationmaster's reluctant clues.",
            "visual_style": "warm painterly 3D, soft light",
        },
    ]
    recent_fps = [build_fingerprint(v) for v in recent]

    # SAME look + SAME title style, but RECYCLES recent #1's plot. Expect RED.
    bad = {
        "title": "The Day the Beacon Failed",
        "script": "A lighthouse keeper on a remote island finds the lamp has gone "
                  "out during a terrible storm and rows out to warn a boat headed "
                  "straight for the rocks.",
    }
    # SAME look + SAME title style, a COMPLETELY NEW plot + a real POV. Expect GREEN.
    good = {
        "title": "The Day the River Took the Bridge",
        "script": "When the floodwater rises faster than anyone planned for, a "
                  "twelve-year-old everyone treats as too small to matter is the "
                  "only one who remembers the old footpath — and I think the whole "
                  "town owes her an apology it will never quite say out loud.",
    }

    print(f"Model: {MODEL}\n")
    print("--- plot-divergence block fed into generators (look stays consistent) ---")
    print(summarize_recent_for_prompt(recent_fps)[:600], "...\n")

    print("--- same look + title style, RECYCLED plot (expect RED) ---")
    v1 = assess_draft("title+script", bad, recent_fps)
    print(json.dumps(v1.model_dump() if hasattr(v1, "model_dump") else v1.dict(), indent=2))
    print(f"needs_reroll = {v1.needs_reroll}\n")

    print("--- same look + title style, NEW plot + a real POV (expect GREEN) ---")
    v2 = assess_draft("title+script", good, recent_fps)
    print(json.dumps(v2.model_dump() if hasattr(v2, "model_dump") else v2.dict(), indent=2))
    print(f"needs_reroll = {v2.needs_reroll}")


if __name__ == "__main__":
    _selftest()
