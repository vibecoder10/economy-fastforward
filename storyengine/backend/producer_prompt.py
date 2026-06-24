"""Creative-producer intake brain for the chat-first experience.

ONE Claude call per chat turn. Claude behaves like a creative producer: reads the
creator's idea, asks ONLY what's missing, prefers selector cards over open
questions, and ends with a production plan the creator approves. It returns ONE
JSON object per turn so the frontend can render cards / the plan deterministically.

Direct Anthropic call (NOT the Kie gateway) so a Kie outage never blocks intake —
same pattern as originality.py:355-399. Fails soft: a malformed turn returns a
gentle "say that again" without crashing the conversation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# The proven current Sonnet id (what originality.py uses in prod). The
# orchestrator's dated id was never actually exercised and 404s on the live API.
MODEL = "claude-sonnet-4-6"

# Always hit Anthropic directly — never inherit a Kie gateway base_url that a
# prior pipeline_executor run may have left in the process env.
ANTHROPIC_DIRECT_BASE_URL = "https://api.anthropic.com"

# Canonical visual-style presets — MUST mirror frontend/src/lib/visual-presets.ts
# (the New Video flow uses the same ids + preview images at /style-icons/<id>.png,
# so the chat LOOK card shows identical thumbnails). The producer offers these
# exact `value`s; chat.py maps the chosen id -> `look` for image_style_override.
VISUAL_PRESETS: dict[str, dict[str, str]] = {
    "pixar_3d":   {"label": "Pixar 3D",   "look": "Soft 3D Pixar-style CG, rounded forms, warm cinematic light, subsurface skin, shallow depth of field"},
    "flat_2d":    {"label": "2D flat",    "look": "Clean 2D flat vector animation, bold flat colors, simple shapes, crisp outlines, minimal shading"},
    "realistic":  {"label": "Realistic",  "look": "Photorealistic cinematic photography, natural lighting, real textures, shallow depth of field"},
    "anime":      {"label": "Anime",      "look": "Modern anime cel-shaded illustration, expressive faces, clean linework, soft gradient shading"},
    "watercolor": {"label": "Watercolor", "look": "Warm hand-painted watercolor storybook art, soft edges, textured paper, gentle palette"},
    "comic":      {"label": "Comic",      "look": "Bold graphic-novel illustration, inked outlines, halftone shading, dynamic high-contrast color"},
}

PRODUCER_SYSTEM_PROMPT = """You are the creative producer inside a YouTube video studio called StoryEngine. You talk to a creator like a warm, sharp producer — never like software. The creator describes a video they want to make; your job is to get them to a production plan they're excited to approve, asking as little as possible.

HOW YOU WORK, in order:
1. Read their idea. Infer everything you reasonably can — genre, tone, the likely audience. Do not ask for what you can sensibly assume.
2. Identify what you genuinely still NEED to make it well. Ask only those things, the fewest possible. One or two short questions beats a wall of them.
3. For anything with a small set of good answers (the look/style, the length, who it's for, how far to take it), offer SELECTOR CARDS instead of an open question.
4. Once you have enough, propose a production plan: a 2-3 sentence story concept, 3 punchy title options, 1-2 thumbnail concepts, and the workflow that fits.
5. Be decisive. Recommend, don't interrogate. Make confident producer choices and invite them to tweak.

NEVER mention internal machinery. Never say: pipeline, stage, status, render, storyboard, extraction, executor, model, token, Kie, or any technical step. Say "I'll write the script", "I'll create the visuals", "I'll put the whole video together".

THE WORKFLOWS for "how far to take it" — pick the one that fits and use these exact values in spec.workflow:
- "full"          -> a finished, ready-to-review video
- "research"      -> just research the topic
- "script"        -> just write the script
- "script_assets" -> the script plus the visuals, no final video
- "custom"        -> the creator wants to choose the steps

OUTPUT FORMAT — every turn, reply with ONE JSON object and NOTHING else. No prose outside the JSON, no code fences. Schema:

{
  "assistant_text": "<what you say to the creator this turn — warm, plain English>",
  "phase": "asking" | "plan",
  "cards": [
    {
      "id": "style" | "length" | "audience" | "workflow" | "<your own id>",
      "label": "<short label, e.g. 'Look'>",
      "type": "single" | "multi",
      "options": [ {"value": "<machine value>", "label": "<what they see>", "hint": "<optional one-liner>"} ]
    }
  ],
  "plan": {
    "story_concept": "<2-3 sentences>",
    "recommended_titles": ["<t1>", "<t2>", "<t3>"],
    "thumbnail_concepts": ["<c1>", "<c2>"],
    "spec": {
      "title": "<the chosen working title>",
      "framework_angle": "<the angle / take, or null>",
      "writer_guidance": "<any specific guidance for the script, or null>",
      "video_length_minutes": <whole number of minutes>,
      "workflow": "full" | "research" | "script" | "script_assets" | "custom",
      "custom_stages": ["script", "images"],
      "visual_style_label": "<friendly look name, e.g. 'Pixar 3D'>",
      "image_style_override": "<one sentence describing the look for the artist>",
      "aspect_ratio": "16:9" | "9:16",
      "lock_in_identity": false
    }
  }
}

Include "cards" ONLY when you're offering choices. Include "plan" ONLY when phase == "plan", and then include every spec field (use null where it doesn't apply; include "custom_stages" only when workflow == "custom").

CARD GUIDANCE:
- LOOK: when the visual style isn't already decided, offer a card with "id":"style", "type":"single", and ALL SIX of these options, using these EXACT `value`s (the UI shows a preview image per value, so it must match): {"value":"pixar_3d","label":"Disney / Pixar 3D"}, {"value":"flat_2d","label":"2D flat"}, {"value":"realistic","label":"Realistic"}, {"value":"anime","label":"Anime"}, {"value":"watercolor","label":"Storybook (watercolor)"}, {"value":"comic","label":"Comic"}. Don't invent other style values — these are the looks the studio can render.
- LENGTH: offer a card with "id":"length" and "type":"slider" (no options array needed — the UI shows a slider from 5 seconds to 30 minutes, in 5-second steps). The creator's chosen length is captured by the slider; just reflect it naturally in the plan. Default video_length_minutes to 1 in the spec when unsure.
- WORKFLOW ("how far should I take it"): offer cards using the values above.
- Only show a card for something you still need. If you already know it, skip it. You may show several cards in one turn.

When you have the look, the length, and how far to take it, move to phase "plan". Keep momentum — don't drag out the questions. If the creator is vague, make strong producer choices and tell them they can change anything."""


def build_system_prompt(channel_brief: str = "") -> str:
    """The producer system prompt, with an optional channel brief appended.

    The channel brief (Phase 4) is a compact summary of the connected channel's
    proven titles/hooks/look so the producer's suggestions match what already
    wins. Empty brief -> the generic producer behavior.
    """
    brief = (channel_brief or "").strip()
    if brief:
        return f"{PRODUCER_SYSTEM_PROMPT}\n\n--- THIS CREATOR'S CHANNEL ---\n{brief}"
    return PRODUCER_SYSTEM_PROMPT


def _extract_json(text: str) -> str:
    """Pull a JSON object out of a model response (handles ``` fences).

    Copied from originality._extract_json (originality.py:340) — same need.
    """
    if not text:
        return "{}"
    t = text.strip()
    if "```" in t:
        block = t.split("```", 2)[1]
        if block.startswith("json"):
            block = block[4:]
        t = block.strip()
    start, end = t.find("{"), t.rfind("}")
    return t[start : end + 1] if start != -1 and end != -1 else t


def _client(api_key: str | None = None):
    import anthropic  # local import: keeps the module importable without the SDK

    # The tenant's direct Anthropic key (from Vault) is passed in. ponytail: we
    # don't route intake through the Kie gateway — Kie is the banned single point
    # of failure, and a direct key is the supported path. Force the direct base
    # URL so a leaked ANTHROPIC_BASE_URL in the process env can't redirect us.
    # Env fallback for the self-test / local dev when no explicit key is given.
    if api_key:
        return anthropic.Anthropic(api_key=api_key, base_url=ANTHROPIC_DIRECT_BASE_URL)
    return anthropic.Anthropic()


_FALLBACK = {
    "assistant_text": "Sorry — I lost the thread there for a second. Could you say that again?",
    "phase": "asking",
}


def call_producer(
    transcript: list[dict[str, Any]],
    system_prompt: str,
    *,
    api_key: str | None = None,
    model: str = MODEL,
    max_tokens: int = 1500,
) -> dict[str, Any]:
    """Run one producer turn. ``transcript`` is the alternating user/assistant
    message list (assistant turns carry the raw JSON the model emitted last time).
    ``api_key`` is the tenant's direct Anthropic key (from Vault).

    Returns the parsed turn dict ({assistant_text, phase, cards?, plan?}). Fails
    soft: any error or malformed JSON returns a gentle re-prompt so the
    conversation never crashes.
    """
    # Two attempts: a single transient hiccup (a network blip or a stray non-JSON token) used
    # to surface to the creator as "I lost the thread". Retry once, nudging harder for clean
    # JSON, before falling back — so a one-off doesn't break the very first turn.
    last_err = None
    for attempt in range(2):
        try:
            client = _client(api_key)
            sys_prompt = system_prompt if attempt == 0 else (
                system_prompt + "\n\nIMPORTANT: Reply with ONE valid JSON object and nothing else.")
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=sys_prompt,
                messages=transcript,
            )
            text = "".join(
                getattr(block, "text", "")
                for block in resp.content
                if getattr(block, "type", "") == "text"
            )
            data = json.loads(_extract_json(text))
            if not isinstance(data, dict) or not data.get("assistant_text"):
                logger.warning("producer returned unusable JSON (attempt %d): %.300s", attempt + 1, text)
                last_err = "unusable JSON"
                continue
            return data
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            logger.warning("producer turn failed (attempt %d): %s", attempt + 1, last_err)
    # Never crash the conversation — fall back gently after the retry.
    logger.warning("producer falling back after retries: %s", last_err)
    return dict(_FALLBACK)


# ---------------------------------------------------------------------------
# Self-test — proves the live producer call returns the JSON contract.
#   python3 producer_prompt.py     (loads ANTHROPIC_API_KEY from ../.env / ../../.env)
# Skips the live call (and passes) if no key is present, so it never blocks CI.
# ---------------------------------------------------------------------------

def _load_key_for_selftest() -> bool:
    import os
    from pathlib import Path

    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    for rel in ("../.env", "../../.env"):
        p = Path(__file__).resolve().parent / rel
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY=") and "=" in line:
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        os.environ["ANTHROPIC_API_KEY"] = val
                        return True
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


if __name__ == "__main__":
    # Offline: prompt-build sanity (no network).
    assert "creative producer" in build_system_prompt().lower()
    assert "MY CHANNEL".lower() in build_system_prompt("Niche: cooking").lower()
    assert _extract_json('```json\n{"a":1}\n```') == '{"a":1}'
    print("offline checks passed")

    if not _load_key_for_selftest():
        print("no ANTHROPIC_API_KEY — skipping live producer call (offline checks passed)")
    else:
        turn = call_producer(
            [{"role": "user", "content": "make me a video about a dragon who finds a lonely owner and they go on an adventure"}],
            build_system_prompt(),
        )
        assert isinstance(turn, dict) and turn.get("assistant_text"), turn
        assert turn.get("phase") in ("asking", "plan"), turn
        print("LIVE producer turn OK")
        print(json.dumps(turn, indent=2)[:1200])
