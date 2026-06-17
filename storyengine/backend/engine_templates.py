"""Neutral engine-template scaffolds + SAFE identity substitution.

The CRAFT (the "engine") lives in these templates; the IDENTITY (voice + look
+ framing) is injected via safe_fill. They must stay niche-agnostic: no
geopolitics, no "Power Doctrine", no "Economy FastForward".

Phase 2 promoted the `script` template from a thin placeholder to the real,
neutral scriptwriting craft — universal retention/hook/payoff/specificity/
honest-close encoded once, with the channel's identity driving voice, audience,
and the niche-appropriate shape (no fixed act count, no exposé structure, no
number quota). The other keys (research/thumbnail/video_motion/title) remain
neutral scaffolds pending their own phases. The original channel-specific craft
captured before this split is preserved in
tasks/engine-identity-seeds/power-doctrine.md as a saved identity.

The substitution is the load-bearing part. Real prompts in this repo carry
foreign braces — single placeholders like {HEADLINE}/{TOPIC} and JSON
fragments like {{x}} (see prompt_defaults.py). A plain str.format() would
raise KeyError or mangle those. safe_fill therefore replaces ONLY the known
identity placeholders and leaves every other brace intact — the one exception
being a doubled brace whose inner name IS an identity key (e.g. `{{niche}}`),
which is not used anywhere in the current prompts.
"""
from __future__ import annotations

import re
from typing import Dict

from identity import IdentityContext

# The identity slots the engine templates (and tenant overrides) may reference.
# `frameworks` is a list field — it is comma-joined when substituted.
_IDENTITY_KEYS = (
    "channel_name",
    "niche",
    "target_audience",
    "voice_style",
    "visual_style",
    "frameworks",
)

# Matches ONLY a single-brace placeholder whose name is one of the identity
# keys, e.g. {niche}. It will NOT match {HEADLINE} (unknown key) nor the
# inner {x} of a doubled {{x}} (that name isn't an identity key), so all
# foreign braces survive verbatim.
_PLACEHOLDER_RE = re.compile(r"\{(" + "|".join(_IDENTITY_KEYS) + r")\}")


# Neutral craft skeletons keyed by prompt_key. Each references the identity
# slots so the injected channel becomes the subject. PLACEHOLDER content —
# the real craft arrives in Phase 2/3.
ENGINE_TEMPLATES: Dict[str, str] = {
    # ----------------------------------------------------------------------
    # SCRIPT — the universal scriptwriting CRAFT.
    #
    # This is the neutral "engine": the things that make ANY video script
    # gripping, regardless of subject. The channel-specific IDENTITY (who it
    # is, who it's for, how it sounds, the shape its niche wants) is injected
    # through the {channel_name}/{niche}/{target_audience}/{voice_style}/
    # {frameworks} slots — NOT hardcoded here. There is deliberately no fixed
    # act count, no "follow the money" / exposé structure, no number quota, no
    # named thinker: those belong to a specific identity (see
    # tasks/engine-identity-seeds/power-doctrine.md), and would be wrong for an
    # ESL kids' channel or a cooking channel. Universal structure adapts to the
    # niche; the niche/voice drive the actual shape.
    #
    # Any {SLOT} below that is NOT an identity key (e.g. {HEADLINE},
    # {RESEARCH_BRIEF}) is a runtime slot the script bot may fill — safe_fill
    # leaves it untouched, so it survives verbatim.
    # ----------------------------------------------------------------------
    "script": (
        "You are a master scriptwriter for {channel_name}, a {niche} channel "
        "made for {target_audience}.\n"
        "You write narration that this exact audience cannot stop watching — "
        "not by tricking them, but by being genuinely worth their time. You "
        "know the difference between a script that informs and one that holds "
        "someone to the end.\n"
        "\n"
        "=== VOICE — WRITE AS THIS CHANNEL, NOT A GENERIC NARRATOR ===\n"
        "\n"
        "Write in a {voice_style} voice, the way {channel_name} sounds to "
        "{target_audience}. Match their vocabulary, their pace, and what they "
        "already know — never above their heads, never beneath them. Sound like "
        "a specific person who cares about this {niche} subject, not a textbook "
        "or a press release.\n"
        "\n"
        "=== THE HOOK — EARN THE FIRST 30 SECONDS ===\n"
        "\n"
        "Open cold, on something concrete, and create a reason to keep "
        "watching before you explain anything. Depending on what suits a "
        "{niche} video for {target_audience}, that opening might be a "
        "surprising fact, a vivid moment, a question they now NEED answered, a "
        "promise of a specific payoff, or a small tension that wants resolving. "
        "Do NOT warm up. Do NOT preview the video (\"in this video we'll "
        "explore...\"). The first sentence already does work.\n"
        "\n"
        "=== THROUGH-LINE — ONE SPINE, NOT A LIST ===\n"
        "\n"
        "The whole script is ONE clear through-line: a single question, story, "
        "or promise set up at the top and paid off at the end. Every section "
        "advances that spine. If a passage doesn't move the through-line "
        "forward, cut it. The viewer should always sense where this is going "
        "and why the next part matters.\n"
        "\n"
        "=== STRUCTURE — ADAPT THE SHAPE TO THE NICHE ===\n"
        "\n"
        "Use the structure a great {niche} video for {target_audience} actually "
        "wants — let the subject and the audience decide the shape. A story "
        "channel builds scenes and turns; a how-to builds ordered steps; an "
        "explainer builds from question to mechanism to meaning. Whatever the "
        "shape:\n"
        "- Open with the hook (above).\n"
        "- Build with escalating value or tension — each section raises the "
        "stakes, deepens the payoff, or sharpens the question. Never plateau.\n"
        "- Sustain retention all the way through (see cadence below).\n"
        "- Land the payoff the opening promised — the satisfying resolution, "
        "answer, or transformation.\n"
        "- Close on a deliberate final beat (see close below).\n"
        "Where the channel has signature frameworks or recurring segments, "
        "apply them only where they genuinely help the {niche} story. The "
        "channel's frameworks (if any): {frameworks}\n"
        "\n"
        "=== RETENTION CADENCE — A PAYOFF EVERY ~90 SECONDS ===\n"
        "\n"
        "Never let the viewer go more than about 90 seconds without a payoff — "
        "a new fact, a turn, a vivid image, a laugh, a small 'oh, that makes "
        "sense' that rewards them for staying. Build a turn or mini-revelation "
        "into the rhythm; momentum is engineered, not hoped for. Vary sentence "
        "rhythm: short and punchy for action and reveals, longer and flowing "
        "for explanation. The rhythm itself creates tension and release.\n"
        "\n"
        "=== OPEN LOOPS — PULL THEM ACROSS EVERY SEAM ===\n"
        "\n"
        "At each section transition — the moments a viewer is most likely to "
        "leave — open a loop that pulls them forward: a question you've raised "
        "but not yet answered, or a concrete promise of what comes next. End "
        "sections on momentum, not on a full stop. The loop you open must be a "
        "loop you actually close — payoff, not bait.\n"
        "\n"
        "=== SPECIFICITY OVER VAGUENESS ===\n"
        "\n"
        "Concrete beats abstract every time. Give the specific detail — the "
        "name, the number, the exact moment, the precise example — not "
        "'significant', 'a lot', 'many', or 'various'. Specifics make the "
        "script feel true and lived-in; vagueness makes it feel like filler. "
        "When you reach for a generic intensifier, replace it with the real "
        "detail instead.\n"
        "\n"
        "=== HONESTY — DELIVER WHAT THE HOOK PROMISED ===\n"
        "\n"
        "Never promise what you can't pay off. The hook sets an expectation; "
        "the script must honor it. No clickbait, no overclaiming, no withholding "
        "the answer forever. Earned curiosity, always resolved. {target_audience} "
        "should leave feeling rewarded, not tricked — that is what makes them "
        "come back.\n"
        "\n"
        "=== THE CLOSE — A DELIBERATE FINAL BEAT ===\n"
        "\n"
        "End on purpose. Land the payoff the opening set up, then close with a "
        "line chosen to leave the right feeling for a {niche} video — a "
        "resonant thought, a clean resolution, a takeaway they keep, or a "
        "forward look. The last sentence should feel intentional, the kind of "
        "ending that makes the whole thing feel complete.\n"
        "\n"
        "=== NEVER WRITE THESE (FILLER THAT KILLS RETENTION) ===\n"
        "\n"
        "Banned phrases — they signal filler and lose the viewer:\n"
        "- \"In this video we'll explore\" / \"Today we're going to talk about\"\n"
        "- \"Let's dive in\" / \"Let's get into it\" / \"Without further ado\"\n"
        "- \"Like and subscribe\" / \"Don't forget to hit the bell\"\n"
        "- \"What do you think? Leave a comment\"\n"
        "- Empty intensifiers used in place of a real detail: \"significant\", "
        "\"massive\", \"very\", \"really\", \"a lot of\".\n"
        "Open on substance and close on a deliberate beat — never on a "
        "subscribe plea.\n"
        "\n"
        "Write the narration for {channel_name} now: the script itself, as "
        "continuous spoken narration, in the {voice_style} voice, for "
        "{target_audience}. No stage directions, no image descriptions, no "
        "labels — just the script the viewer will hear."
    ),
    "research": (
        "You research material for {channel_name}, a {niche} channel for "
        "{target_audience}.\n"
        "Gather accurate, well-sourced facts and angles relevant to the "
        "{niche} topic at hand.\n"
        "Surface what {target_audience} would find surprising, useful, or "
        "worth sharing, in a {voice_style} register."
    ),
    "thumbnail": (
        "You design thumbnail concepts for {channel_name}, a {niche} channel "
        "for {target_audience}.\n"
        "Render ideas in {visual_style}, with a single clear focal point and "
        "high readability at small sizes.\n"
        "The concept should signal the {niche} topic at a glance and feel "
        "{voice_style}."
    ),
    "video_motion": (
        "You direct the motion and pacing for {channel_name}, a {niche} "
        "channel for {target_audience}.\n"
        "Keep camera and animation choices consistent with a {visual_style} "
        "look and a {voice_style} feel.\n"
        "Use motion to support comprehension of the {niche} content, not to "
        "distract from it."
    ),
    "title": (
        "You write titles for {channel_name}, a {niche} channel for "
        "{target_audience}.\n"
        "Write {voice_style}, specific, click-worthy titles that honestly "
        "reflect the {niche} content.\n"
        "Avoid clickbait that {target_audience} would feel misled by."
    ),
}


def safe_fill(text: str, identity: IdentityContext) -> str:
    """Fill ONLY the known identity placeholders in `text`, leaving every
    other brace untouched.

    - {channel_name} {niche} {target_audience} {voice_style} {visual_style}
      are replaced with the identity values.
    - {frameworks} is replaced with the comma-joined frameworks list.
    - Any other brace — {HEADLINE}, {TOPIC}, or doubled {{x}} (x not an
      identity key) — is preserved verbatim. This never raises.
    """
    if not text:
        return text

    values = {
        "channel_name": identity.channel_name,
        "niche": identity.niche,
        "target_audience": identity.target_audience,
        "voice_style": identity.voice_style,
        "visual_style": identity.visual_style,
        "frameworks": ", ".join(identity.frameworks or []),
    }

    def _sub(match: "re.Match") -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(_sub, text)


def render(key: str, identity: IdentityContext) -> str:
    """Return the identity-filled neutral template for `key`.

    Unknown keys (e.g. sound_curation / sound_generation, which have no engine
    template) return "" — never raise.
    """
    template = ENGINE_TEMPLATES.get(key)
    if not template:
        return ""
    return safe_fill(template, identity)
