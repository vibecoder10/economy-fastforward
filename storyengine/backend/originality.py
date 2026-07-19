"""Originality engine — make AI slop structurally impossible.

This is the foundation of StoryEngine's "good by construction" defense against
YouTube's inauthentic-content demonetization policy (the July 2025 rename of the
"repetitious content" rule, enforced hard through 2026). The design rule, set by
Ryan: there are NO user-facing gates, blocks, or warnings. Slop must be
impossible to *produce*, so the creator never has to think about it.

This module does two jobs, both meant to run INSIDE generation:

  1. Diversity input — ``build_generation_guardrails`` /
     ``summarize_recent_for_prompt`` turn a channel's recent videos into a
     compact "do not repeat these plots" block (plus a point-of-view mandate and
     an anti-template rule) that gets appended to the title / script / thumbnail
     generators' system prompts. Each new video is then forced to diverge from
     its channel's history by construction, not checked after. This is the active
     slop defense; the generation that consumes it routes through the tenant's
     own Claude client, so it protects every tenant.

  2. Retention grade — ``grade_script`` / ``grade_script_with_client`` run one
     Claude call to score a freshly generated script against YouTube retention
     rules (hook speed, but/therefore causality, escalating stakes, payoff,
     specificity) and tell the pipeline whether to quietly revise it. Internal
     only — never surfaced to the creator.

The two walls (see ../MONETIZATION-SAFETY-PLAN.md) are enforced by the guardrails
in job 1: Wall 1 = a real point of view per video; Wall 2 = a genuinely new PLOT
every time (the channel's look, format, and title style MAY stay consistent —
that is its brand; only the plot must differ). AI disclosure (the label) is
handled separately, at the upload stage.

Model: claude-sonnet-4-6. ``grade_script_with_client`` routes through the
pipeline's AnthropicClient, so it works for direct-key AND Kie-gateway tenants;
the bare ``grade_script`` / ``_client`` path hits Anthropic directly and is used
for standalone/self-test only.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# Ryan's call: Claude Sonnet, direct cloud, "smart" tier. Single Claude tier
# source (checklist §3.4 / C35) — value lives in shared.channel_profile,
# next to MODEL_REGISTRY, not duplicated here.
from actions import CLAUDE_MODELS
MODEL = CLAUDE_MODELS["anthropic"]["smart"]

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
# Shared LLM helpers (used by the retention grade below).
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Retention grade (Phase 2) — the script quality gate.
#
# The guardrails above protect ORIGINALITY (a genuinely new plot with a point of
# view, injected into the generation prompt). grade_script protects RETENTION
# (does the script actually hold a viewer): hook speed, but/therefore causality,
# escalating stakes, a delivered payoff, and specificity. It runs right after a
# script is generated; a "revise"
# verdict tells the pipeline to feed rewrite_guidance back to the writer and
# regenerate once. Like the rest of this module: internal only, fails open, and
# is niche-safe (a how-to is graded as a how-to, not punished for lacking a
# story arc).
# ---------------------------------------------------------------------------

class ScriptGrade(BaseModel):
    """Internal-only retention grade of a freshly generated script.

    ``verdict`` is the dial the pipeline reads: ``revise`` (the common case for a
    weak script) or ``regenerate`` both mean "append rewrite_guidance to
    writer_guidance and run the writer once more"; ``pass`` ships as-is. Never
    surfaced to the creator.
    """

    verdict: str = "pass"                 # pass | revise | regenerate (internal)
    score: int = 100                      # 0-100 overall retention score
    failing_gates: List[str] = Field(default_factory=list)
    rewrite_guidance: str = ""            # concrete, actionable fixes for a re-roll

    @field_validator("rewrite_guidance", mode="before")
    @classmethod
    def _coerce_guidance(cls, v):
        # The judge sometimes returns guidance as a JSON array (one item per
        # failing gate) instead of one string - join it rather than fail the
        # whole grade (a strict str field would reject the list and fall open).
        if isinstance(v, list):
            return "\n".join(str(x).strip() for x in v if str(x).strip())
        return "" if v is None else v

    @property
    def needs_revision(self) -> bool:
        return (self.verdict or "").strip().lower() in ("revise", "regenerate")


_SCRIPT_JUDGE_SYSTEM = (
    "You are an internal retention check inside an AI video engine. Your output "
    "is consumed by code, never shown to a human. You grade a freshly written "
    "video SCRIPT against the rules that decide whether a YouTube video holds its "
    "audience. Be strict but fair.\n"
    "\n"
    "This channel may be ANY niche: a story channel, a how-to, an explainer, a "
    "cooking or language channel. Adapt every rule to the niche. Do NOT punish a "
    "how-to for lacking a story arc, or an explainer for lacking a named "
    "protagonist. The gates below are universal craft; apply them in the form the "
    "niche calls for.\n"
    "\n"
    "Grade these gates:\n"
    "1. HOOK SPEED: the opening gives a concrete, specific reason to keep watching "
    "within the first ~15 seconds (a stake, a question, a surprising fact, a "
    "promise). FAIL if it opens with a greeting ('hey', 'welcome back'), a channel "
    "intro, 'in this video / today we'll talk about', or buries the point under "
    "backstory.\n"
    "2. CAUSALITY: beats connect with 'but' (a complication) or 'therefore' (a "
    "consequence), driving momentum. FAIL if it is a flat list strung together "
    "with 'and then' / 'also' / 'next' with no causal pull. For a how-to, each "
    "step should unlock or depend on the last, not just be a sequence.\n"
    "3. ESCALATION: the value, tension, or stakes RISE across the script; it does "
    "not plateau or sag in the middle.\n"
    "4. PAYOFF: one clear through-line is set up at the open and delivered at the "
    "end. FAIL if the opening promise is never paid off, or the ending just "
    "stops.\n"
    "5. SPECIFICITY: concrete details (names, numbers, exact examples) over generic "
    "filler ('significant', 'a lot', 'various', 'a person'). FAIL if it reads as "
    "generic, templated AI narration.\n"
    "\n"
    "Score 0-100, weighted roughly: hook 25, causality 25, escalation 20, payoff "
    "20, specificity 10.\n"
    "\n"
    "Decide verdict:\n"
    "- pass: clears the gates well enough to ship. Minor weaknesses are fine. Use "
    "pass for score 70+.\n"
    "- revise: one or more gates clearly fail but a targeted rewrite fixes it. The "
    "common case for a weak script. Use for score 50-69.\n"
    "- regenerate: broadly weak across multiple gates, needs a fresh pass. Use for "
    "score under 50.\n"
    "\n"
    "If verdict is revise or regenerate, write rewrite_guidance: 2 to 5 concrete, "
    "specific instructions the writer can act on. Name the exact problem and the "
    "fix; quote the weak opening if relevant. Never vague ('make it better'); "
    "always actionable (e.g. 'the script opens with 30 seconds of background "
    "before any stake. Open instead on the flooded bridge already in paragraph 4, "
    "and state what is at risk in the first sentence.').\n"
    "\n"
    "Return ONLY a JSON object, no markdown, no prose:\n"
    "{\"verdict\": \"pass|revise|regenerate\", \"score\": int, "
    "\"failing_gates\": [string, ...], \"rewrite_guidance\": string}"
)


def _build_script_judge_user_prompt(draft: Dict[str, Any]) -> str:
    """Assemble the grader's user message. Long scripts are sent head + tail so
    the ending (which carries the payoff) survives truncation while the prompt
    stays cheap."""
    niche = _truncate(draft.get("niche"), 80) or "(unspecified)"
    title = _truncate(draft.get("title"), _TITLE_TRUNC) or "(untitled)"
    hook = _truncate(draft.get("hook"), _HOOK_TRUNC)
    script = " ".join(str(draft.get("script") or "").split())
    if len(script) > 6000:
        script = script[:5000].rstrip() + " […] " + script[-1000:].lstrip()

    lines = [
        f"NICHE: {niche}",
        f"TITLE: {title}",
    ]
    if hook:
        lines.append(f"HOOK: {hook}")
    lines.append("")
    lines.append("SCRIPT:")
    lines.append(script)
    return "\n".join(lines)


def grade_script(
    draft: Dict[str, Any],
    *,
    model: str = MODEL,
    max_tokens: int = 700,
) -> ScriptGrade:
    """Grade a freshly generated script for retention (one Sonnet call).

    ``draft`` is a dict with at least ``script``, optionally ``title``, ``hook``,
    and ``niche`` (the niche keeps grading niche-appropriate).

    Fails OPEN: on any error this returns a ``pass`` verdict so a transient model
    or network problem never blocks the pipeline. The already-generated script
    stands.
    """
    if not str(draft.get("script") or "").strip():
        return ScriptGrade(verdict="pass", failing_gates=[], rewrite_guidance="")
    try:
        client = _client()
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_SCRIPT_JUDGE_SYSTEM,
            messages=[
                {"role": "user", "content": _build_script_judge_user_prompt(draft)}
            ],
        )
        text = "".join(
            getattr(block, "text", "") for block in resp.content
            if getattr(block, "type", "") == "text"
        )
        return ScriptGrade(**json.loads(_extract_json(text)))
    except Exception:
        return ScriptGrade(verdict="pass", failing_gates=["grade unavailable - failed open"])


async def grade_script_with_client(
    draft: Dict[str, Any],
    anthropic_client: Any,
    *,
    max_tokens: int = 700,
) -> ScriptGrade:
    """Async grade that routes the call through the pipeline's AnthropicClient.

    This is what lets the gate protect EVERY tenant, not just those with a direct
    Anthropic key. The plain ``grade_script`` above builds a bare
    ``anthropic.Anthropic()`` (direct api.anthropic.com, x-api-key auth); for a
    Kie-only tenant that hits the Kie gateway URL with the wrong auth header and
    silently falls open. ``AnthropicClient`` already handles the gateway (Bearer
    auth, model aliasing, streaming), so passing it here makes grading work the
    same way script generation already does for that tenant.

    ``anthropic_client`` is any object with an async
    ``generate(prompt, system_prompt, max_tokens, temperature) -> str`` method
    (so originality.py stays decoupled from the skills package). Fails OPEN: a
    missing client, empty script, or any error returns a ``pass`` verdict.
    """
    if anthropic_client is None or not str(draft.get("script") or "").strip():
        return ScriptGrade()
    try:
        text = await anthropic_client.generate(
            prompt=_build_script_judge_user_prompt(draft),
            system_prompt=_SCRIPT_JUDGE_SYSTEM,
            max_tokens=max_tokens,
            temperature=0.3,  # low, for stable gate decisions
        )
        return ScriptGrade(**json.loads(_extract_json(text)))
    except Exception:
        return ScriptGrade(verdict="pass", failing_gates=["grade unavailable - failed open"])


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

    print(f"Model: {MODEL}\n")
    print("--- plot-divergence block fed into generators (look stays consistent) ---")
    print(summarize_recent_for_prompt(recent_fps)[:600], "...\n")

    # --- Phase 2: retention grade discrimination ---------------------------
    # A flat "and then" list with a slow open (expect revise/regenerate).
    weak = {
        "niche": "history",
        "title": "The Story of the Bridge",
        "script": "Hey everyone, welcome back to the channel. Today we're going to "
                  "talk about a bridge. The bridge was built a long time ago. And "
                  "then people used it for many years. And then it got old. And then "
                  "one day it was significant that some repairs happened. A lot of "
                  "things changed over time. Thanks for watching.",
    }
    # A fast hook with causal momentum, escalation, and a delivered payoff (expect pass).
    strong = {
        "niche": "history",
        "title": "The Night the Bridge Nearly Fell",
        "script": "At 2:14 a.m. a night watchman felt the deck under his boots drop "
                  "two inches, and he had eleven minutes to stop the 3:00 freight. "
                  "But the telegraph line to the next station was already dead, "
                  "therefore his only option was the warning lamp - which had no "
                  "oil. He sprinted back for the spare can, but the storm had jammed "
                  "the shed door, so he broke the window with his own lantern, and "
                  "in the dark he finally swung the red light just as the engine's "
                  "headlamp rounded the bend. The brakes caught forty feet from the "
                  "cracked span. By morning the town that never knew his name was "
                  "still standing because of him.",
    }
    print("\n--- weak script: slow open + 'and then' list (expect revise/regenerate) ---")
    g1 = grade_script(weak)
    print(json.dumps(g1.model_dump() if hasattr(g1, "model_dump") else g1.dict(), indent=2))
    print(f"needs_revision = {g1.needs_revision}")
    assert g1.needs_revision, "weak script should not pass the retention grade"

    print("\n--- strong script: fast hook + but/therefore + payoff (expect pass) ---")
    g2 = grade_script(strong)
    print(json.dumps(g2.model_dump() if hasattr(g2, "model_dump") else g2.dict(), indent=2))
    print(f"needs_revision = {g2.needs_revision}")
    assert not g2.needs_revision, "strong script should pass the retention grade"
    print("\nretention-grade self-test OK")


if __name__ == "__main__":
    _selftest()
