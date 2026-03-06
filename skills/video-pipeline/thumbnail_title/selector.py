"""Template selection logic for thumbnail generation.

Selects one of the four editorial illustration templates based on video metadata
(topic keywords and tags). Falls back to Template A (Map + Barrier) as default
since it has the highest CTR benchmark.

Templates:
  A: Map + Barrier     — geopolitical, oil, trade routes, chokepoints (35%)
  B: Character + Text  — leaders, companies, tech, institutional power (25%)
  C: Split Winner/Loser — sanctions, bans, trade wars, versus stories (20%)
  D: Symbolic Action   — traps, power moves, economic mechanisms (20%)
"""


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


def select_template(video_metadata: dict) -> str:
    """Select thumbnail template based on video content type.

    Args:
        video_metadata: Dict with at least 'topic' (str) and optionally 'tags' (list[str]).
            Also accepts standard Airtable fields: 'Video Title', 'Summary',
            'Framework Angle', etc.

    Returns:
        One of 'template_a', 'template_b', 'template_c', 'template_d'.
    """
    # Build a searchable text blob from all relevant fields
    topic = video_metadata.get("topic", "").lower()
    title = video_metadata.get("Video Title", "").lower()
    summary = video_metadata.get("Summary", "").lower()
    framework = video_metadata.get("Framework Angle", "").lower()
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

    # Template A: Map + Barrier — default (highest CTR benchmark)
    return "template_a"
