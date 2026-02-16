"""Template selection logic for thumbnail generation.

Selects one of the three thumbnail templates based on video metadata
(topic keywords and tags). Falls back to Template A (CFH Split) as default.
"""


# Keywords that trigger Template C: Power Dynamic
POWER_KEYWORDS = [
    "robot", "ai replace", "monopoly", "inequality",
    "corporate", "billionaire", "oligarch", "who owns",
    "who controls", "who profits",
]

# Keywords that trigger Template B: Mindplicit Banner
STRATEGY_KEYWORDS = [
    "machiavelli", "strategy", "hidden", "secret",
    "never do", "warning", "dark", "manipulation",
    "power play", "puppet",
]


def select_template(video_metadata: dict) -> str:
    """Select thumbnail template based on video content type.

    Args:
        video_metadata: Dict with at least 'topic' (str) and optionally 'tags' (list[str]).
            Also accepts standard Airtable fields: 'Video Title', 'Summary',
            'Framework Angle', etc.

    Returns:
        One of 'template_a', 'template_b', 'template_c'.
    """
    # Build a searchable text blob from all relevant fields
    topic = video_metadata.get("topic", "").lower()
    title = video_metadata.get("Video Title", "").lower()
    summary = video_metadata.get("Summary", "").lower()
    framework = video_metadata.get("Framework Angle", "").lower()
    tags = [t.lower() for t in video_metadata.get("tags", [])]

    searchable = f"{topic} {title} {summary} {framework} {' '.join(tags)}"

    # Template C: Power Dynamic — winners vs losers narratives
    if any(kw in searchable for kw in POWER_KEYWORDS):
        return "template_c"

    # Template B: Mindplicit Banner — strategy/warning content
    if any(kw in searchable for kw in STRATEGY_KEYWORDS):
        return "template_b"

    # Template A: CFH Split — default for everything else
    return "template_a"
