"""Skill-side silent originality re-roll for the script stage (Phase 2).

If a freshly generated script reuses a plot the channel already made, this
quietly regenerates it with a "write a completely different plot" nudge — before
the script is ever saved, shown, or split into scenes. Invisible to the creator,
capped, and fails open (any error just keeps the original draft).

Why this lives on the skill side: skills cannot import the backend, so the
backend (backend/originality.py) hands the channel's recent plots over the same
env-var seam it uses for VISUAL_STYLE_DESCRIPTION — here, RECENT_PLOTS_JSON. The
judge uses a DIRECT Anthropic Sonnet call (anthropic.Anthropic(), reading
ANTHROPIC_API_KEY), NOT the pipeline's client, so it keeps working even when the
tenant's Kie.ai gateway is down — which is the whole point of doing this here.

Design rule (Ryan): the look/format/title style may stay consistent (brand);
only the PLOT must be different every time.

Env:
  RECENT_PLOTS_JSON      JSON list of {"title": str, "plot": str} (set by backend)
  ORIGINALITY_MAX_REROLLS  max regenerations on a recycled plot (default 1)
"""

import json
import os

MODEL = "claude-sonnet-4-6"  # direct Sonnet; matches backend/originality.py

_JUDGE_SYSTEM = (
    "You are an internal check inside a video engine; your output is read by code, "
    "never shown to a human. A consistent LOOK, FORMAT, and TITLE STYLE across a "
    "channel is fine branding — do NOT penalize it. The ONLY thing that must be "
    "different from the channel's recent videos is the PLOT: the story, events, "
    "and arc. A new topic poured into the same story template is NOT a new plot.\n"
    "\n"
    "Given the recent plots and a NEW script, decide if the new script's plot is "
    "genuinely different from all recent ones. Return ONLY a JSON object:\n"
    "{\"distinct_plot\": bool, \"verdict\": \"green|red\", "
    "\"divergence_suggestion\": string}\n"
    "verdict is red if the plot reuses/recycles a recent plot or a repeated "
    "template; green if it is a genuinely new plot. If red, divergence_suggestion "
    "is one or two sentences proposing a COMPLETELY different plot/story (never "
    "about the look or title)."
)


def _recent_plots():
    raw = os.getenv("RECENT_PLOTS_JSON") or ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _extract_json(text):
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


def _judge(title, script, recent):
    """One direct Sonnet call. Returns a verdict dict. Raises on failure."""
    import anthropic

    client = anthropic.Anthropic()  # DIRECT — not the Kie-routed pipeline client
    plots = "\n".join(
        f'{i}. "{p.get("title", "")}" — {p.get("plot", "")}'
        for i, p in enumerate(recent, 1)
    )
    user = (
        f"RECENT PLOTS (do not reuse any of these):\n{plots}\n\n"
        f'NEW SCRIPT title: "{title}"\n'
        f"NEW SCRIPT:\n{(script or '')[:6000]}"
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(
        getattr(b, "text", "") for b in resp.content
        if getattr(b, "type", "") == "text"
    )
    return json.loads(_extract_json(text))


async def maybe_reroll_for_plot(*, title, script, script_result, regenerate, base_system_prompt):
    """Quietly re-roll the script if its plot recycles a recent one.

    ``regenerate(system_prompt_override)`` is an async callable that returns a
    fresh ``script_result`` dict (same shape as generate_script's, with a
    "script" key). Returns the final ``(script, script_result)``. Fails open.
    """
    recent = _recent_plots()
    if not recent:
        return script, script_result  # no history -> nothing to diverge from

    try:
        max_rerolls = int(os.getenv("ORIGINALITY_MAX_REROLLS", "1") or "1")
    except ValueError:
        max_rerolls = 1

    base = base_system_prompt or ""
    for _ in range(max(0, max_rerolls)):
        try:
            verdict = _judge(title, script, recent)
        except Exception as e:
            print(f"[originality] judge unavailable, keeping draft: {e}", flush=True)
            return script, script_result  # fail open
        if str(verdict.get("verdict", "green")).strip().lower() != "red":
            break  # plot is distinct enough
        suggestion = (verdict.get("divergence_suggestion") or "").strip()
        print("[originality] recycled plot detected — silently re-rolling the script", flush=True)
        spo = (
            base
            + "\n\n=== RE-ROLL: YOUR PREVIOUS DRAFT REUSED AN EXISTING PLOT ===\n"
            + "The script you just wrote recycles a plot this channel has already "
            + "made. Write a COMPLETELY DIFFERENT plot — a genuinely new story, not "
            + "the old one relabeled. The look, format, and title style may stay the "
            + "same; only the plot must change."
            + (("\nDirection: " + suggestion) if suggestion else "")
        ).strip()
        try:
            new_result = await regenerate(spo)
        except Exception as e:
            print(f"[originality] re-roll regenerate failed, keeping draft: {e}", flush=True)
            return script, script_result  # fail open
        if not new_result or not new_result.get("script"):
            return script, script_result
        script, script_result = new_result["script"], new_result

    return script, script_result
