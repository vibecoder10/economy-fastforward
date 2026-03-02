"""Template selection logic for thumbnail generation.

Selects one of the two cinematic thumbnail templates based on video metadata
(topic keywords and tags). Falls back to Template A (Cinematic Scene) as default.

Template B (Cinematic Close-Up) triggers on person-focused stories:
assassinations, leaders, CEOs, presidents, dictators, commanders, generals,
and other individual power figures.
"""


# Keywords that trigger Template B: Cinematic Close-Up (person-focused)
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
]


def select_template(video_metadata: dict) -> str:
    """Select thumbnail template based on video content type.

    Args:
        video_metadata: Dict with at least 'topic' (str) and optionally 'tags' (list[str]).
            Also accepts standard Airtable fields: 'Video Title', 'Summary',
            'Framework Angle', etc.

    Returns:
        One of 'template_a', 'template_b'.
    """
    # Build a searchable text blob from all relevant fields
    topic = video_metadata.get("topic", "").lower()
    title = video_metadata.get("Video Title", "").lower()
    summary = video_metadata.get("Summary", "").lower()
    framework = video_metadata.get("Framework Angle", "").lower()
    tags = [t.lower() for t in video_metadata.get("tags", [])]

    searchable = f"{topic} {title} {summary} {framework} {' '.join(tags)}"

    # Template B: Cinematic Close-Up — person-focused stories
    if any(kw in searchable for kw in PERSON_KEYWORDS):
        return "template_b"

    # Template A: Cinematic Scene — default for systems, countries, markets, institutions
    return "template_a"
