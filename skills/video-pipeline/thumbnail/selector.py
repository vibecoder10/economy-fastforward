"""Template selection logic for thumbnail generation.

Selects one of the five editorial illustration templates based on video
metadata (topic keywords and tags). Template A (Map + Barrier) is a
geopolitical/finance visual — it is Ryan's original Economy FastForward
channel's proven highest-CTR template, but it is WRONG for a cooking, ESL, or
story channel with no geopolitics content. Checklist C34c / audit finding
S10-4: `select_template` used to fall back to Template A unconditionally for
ANY unmatched content, which meant a brand-new tenant with no channel
thumbnail history (reachable via pipeline_executor.py's from-scratch bot
fallback) could ship a world-map thumbnail on a video about nothing
geopolitical at all.

The fix: Template A is now reached two ways — (1) explicit geo/finance
keywords in the video's own content (GEO_KEYWORDS, same domain as its
"best_for" in templates.py), or (2) as a niche-informed fallback when the
tenant's OWN niche (channel_profiles.niche, exported by
pipeline_executor.py's `_load_prompt_overrides` as the CHANNEL_NICHE env var
seam — mirrors the existing VISUAL_STYLE_DESCRIPTION seam) is itself
geopolitics/finance shaped. Ryan's legacy channel keeps landing on Template A
either way — his content is inherently geopolitical AND his niche says so.
Everyone else, with nothing to match, gets Template E (Subject Focus) — a
niche-neutral template with no map/geo assumption baked in.

Templates:
  A: Map + Barrier     — geopolitical, oil, trade routes, chokepoints (35%)
  B: Character + Text  — leaders, companies, tech, institutional power (25%)
  C: Split Winner/Loser — sanctions, bans, trade wars, versus stories (20%)
  D: Symbolic Action   — traps, power moves, economic mechanisms (20%)
  E: Subject Focus     — niche-neutral default when nothing above matches (0%,
                          fallback only — not part of the weighted rotation)
"""

import os

from orchestrator.pipeline_constants import IdeaFields


# Keywords that trigger Template B: Character + Bold Text (person/entity-focused)
PERSON_KEYWORDS = [
    "assassin", "assassination", "murder", "killed",
    "leader", "leaders", "leadership",
    "ceo", "founder", "executive",
    "president", "prime minister", "chancellor",
    "dictator", "tyrant", "authoritarian",
    "commander", "general", "admiral", "military leader",
    "king", "queen", "emperor", "monarch", "dynasty",
    "oligarch", "billionaire", "tycoon", "mogul",
    "spy", "agent", "defector",
    "warlord", "rebel leader", "coup",
    "who is", "the man who", "the woman who",
    "his plan", "her plan", "his secret", "her secret",
    "elon", "bezos", "zuckerberg", "altman",
]

# Keywords that trigger Template C: Split Winner/Loser
SPLIT_KEYWORDS = [
    "vs", "versus", "against",
    "ban", "banned", "banning",
    "sanction", "sanctions", "sanctioned",
    "winner", "loser", "wins", "loses",
    "before", "after",
    "left behind", "replaced",
    "kicked out", "expelled",
    "trade war", "tariff", "embargo",
    "rivalry", "competition",
]

# Keywords that trigger Template D: Symbolic Action
SYMBOLIC_KEYWORDS = [
    "trap", "trapped", "trapping",
    "squeeze", "strangl", "choke",
    "valve", "pipeline", "flow",
    "cage", "locked", "hostage",
    "weapon", "weaponiz",
    "mechanism", "machine", "system",
    "lever", "trigger", "switch",
    "checkmate", "gambit", "play",
    "debt trap", "ponzi",
]

# Keywords that trigger Template A: Map + Barrier — the video's OWN content is
# explicitly geopolitical/macro-economic (matches templates.py's Template A
# "best_for": geopolitical, oil, trade routes, chokepoints, sanctions). This
# is the CONTENT-level signal; GEO_NICHE_KEYWORDS below is the CHANNEL-level
# signal used only when no keyword list (this one included) matches anything.
GEO_KEYWORDS = [
    "map", "border", "borders", "territory", "territories",
    "chokepoint", "trade route", "shipping lane", "strait", "canal",
    "geopolit", "world power", "superpower", "empire", "colony", "colonial",
    "continent", "hemisphere",
    "global economy", "world economy", "gdp", "currency", "reserve currency",
    "supply chain", "oil field", "opec", "trade bloc", "hegemony",
    "annex", "invasion", "occupied", "occupation",
]

# Niche-level fallback signal (checklist C34c, S10-4): consulted ONLY when
# nothing above matched the video's own content. A tenant whose channel niche
# is itself finance/geopolitics/business (Ryan's original Economy FastForward
# channel) still lands on Template A even on a video whose own text happens
# not to trip GEO_KEYWORDS; a cooking or ESL channel's niche never matches
# this list, so it falls through to the neutral Template E instead.
GEO_NICHE_KEYWORDS = [
    "finance", "financ", "economic", "economy", "geopolit", "politic",
    "world affairs", "global affairs", "international relations",
    "business news", "macroeconomic",
]


def select_template(video_metadata: dict) -> str:
    """Select thumbnail template based on video content type.

    Args:
        video_metadata: Dict with at least 'topic' (str) and optionally 'tags' (list[str]).
            Also accepts standard Airtable fields: 'Video Title', 'Summary',
            'Framework Angle', etc. An optional 'niche' key (channel niche,
            e.g. "finance/economics" or "cooking") is consulted ONLY as the
            final fallback signal, mirroring resolve_prompt's per-video >
            tenant precedence — falls back to the CHANNEL_NICHE env var (the
            same cross-package seam VISUAL_STYLE_DESCRIPTION uses) when the
            caller doesn't pass one explicitly.

    Returns:
        One of 'template_a', 'template_b', 'template_c', 'template_d',
        'template_e'.
    """
    # Build a searchable text blob from all relevant fields
    topic = video_metadata.get("topic", "").lower()
    title = video_metadata.get(IdeaFields.VIDEO_TITLE, "").lower()
    summary = video_metadata.get(IdeaFields.SUMMARY, "").lower()
    framework = video_metadata.get(IdeaFields.FRAMEWORK_ANGLE, "").lower()
    tags = [t.lower() for t in video_metadata.get("tags", [])]

    searchable = f"{topic} {title} {summary} {framework} {' '.join(tags)}"

    # Template B: Character + Bold Text — person-focused stories
    if any(kw in searchable for kw in PERSON_KEYWORDS):
        return "template_b"

    # Template C: Split Winner/Loser — comparison/versus stories
    if any(kw in searchable for kw in SPLIT_KEYWORDS):
        return "template_c"

    # Template D: Symbolic Action — mechanism/trap/metaphor stories
    if any(kw in searchable for kw in SYMBOLIC_KEYWORDS):
        return "template_d"

    # Template A: Map + Barrier — the video's OWN content is explicitly
    # geopolitical/macro-economic (Ryan's legacy channel's proven template).
    if any(kw in searchable for kw in GEO_KEYWORDS):
        return "template_a"

    # Template A, niche-informed fallback (C34c, S10-4): nothing in THIS
    # video's own text matched, but the CHANNEL itself is a finance/
    # geopolitics/business niche — still Template A's home turf. Any other
    # niche (or no niche info at all) falls through to the neutral default.
    niche = (video_metadata.get("niche") or os.environ.get("CHANNEL_NICHE") or "").lower()
    if any(kw in niche for kw in GEO_NICHE_KEYWORDS):
        return "template_a"

    # Template E: Subject Focus — the niche-neutral default. Nothing above
    # matched: this is NOT a geo/political/person/split/symbolic story, so
    # don't force a world map onto it (the bug this fix closes).
    return "template_e"
