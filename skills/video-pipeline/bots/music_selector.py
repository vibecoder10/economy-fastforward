"""Music Selector — Per-act mood classification and track selection.

Classifies each act's mood using Claude Haiku and selects a random track
from the appropriate mood folder in Google Drive.
"""

from __future__ import annotations

import random
from typing import Optional

from pipeline_constants import Models


# Google Drive folder containing background music tracks
MUSIC_FOLDER_ID = "17FF7IanYzbgfLrIwXIjKwNlqRSkefS9i"

# Valid moods for classification
VALID_MOODS = {"tension", "strategic", "revelation"}

# Default volume for background music
DEFAULT_VOLUME = 0.08

# Keywords for fallback mood classification
MOOD_KEYWORDS = {
    "tension": [
        "crisis", "conflict", "danger", "threat", "war", "sanctions",
        "military", "attack", "strike", "missiles", "nuclear", "invasion",
    ],
    "strategic": [
        "analysis", "power", "calculated", "geopolitical", "chess", "trade",
        "alliance", "operation", "strategy", "move", "position",
    ],
    "revelation": [
        "personal", "hidden", "exposed", "financial", "consequences",
        "stakes", "collapse", "systemic", "failure", "truth", "secret",
    ],
}

# System prompt for mood classification
MOOD_SYSTEM_PROMPT = """You are a music director for a geopolitical documentary channel.

Your job is to classify the emotional mood of a script segment to select appropriate background music.

Respond with EXACTLY ONE of these moods:
- tension: For scenes about crisis, conflict, danger, threats, war, military action
- strategic: For scenes about analysis, power plays, geopolitical chess, trade, alliances
- revelation: For scenes about hidden truths, personal stories, financial exposure, consequences

Respond with only the mood word, nothing else."""


async def classify_act_mood(
    anthropic_client,
    act_number: int,
    act_text: str,
) -> str:
    """Classify the mood of an act using Claude Haiku.

    Args:
        anthropic_client: AnthropicClient instance
        act_number: The act number (1-6)
        act_text: The narration text of the act

    Returns:
        One of: tension, strategic, revelation
    """
    # Truncate to first 500 words
    words = act_text.split()
    truncated_text = " ".join(words[:500])

    prompt = f"""Classify the mood of this Act {act_number} from a geopolitical documentary:

{truncated_text}

Respond with only: tension, strategic, or revelation"""

    try:
        response = await anthropic_client.generate(
            prompt=prompt,
            system_prompt=MOOD_SYSTEM_PROMPT,
            model=Models.CLAUDE_HAIKU,
            max_tokens=20,
            temperature=0.0,
        )

        # Normalize: strip whitespace and lowercase
        mood = response.strip().lower()

        # Validate the mood
        if mood in VALID_MOODS:
            return mood

        # If invalid, fall back to keyword matching
        return _classify_by_keywords(act_text)

    except Exception:
        # Fall back to keyword matching on any error
        return _classify_by_keywords(act_text)


def _classify_by_keywords(text: str) -> str:
    """Classify mood by counting keyword matches.

    Args:
        text: The text to analyze

    Returns:
        The mood with the most keyword matches, or 'strategic' as default
    """
    text_lower = text.lower()

    mood_scores = {}
    for mood, keywords in MOOD_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        mood_scores[mood] = score

    # Find mood with highest score
    best_mood = max(mood_scores, key=lambda m: mood_scores[m])

    # If no matches, default to strategic
    if mood_scores[best_mood] == 0:
        return "strategic"

    return best_mood


def select_track_for_mood(
    mood: str,
    available_tracks: list[dict],
) -> Optional[dict]:
    """Select a random track matching the mood prefix.

    Args:
        mood: One of tension, strategic, revelation
        available_tracks: List of dicts with 'name' and 'id' keys

    Returns:
        A track dict or None if no match
    """
    if not available_tracks:
        return None

    # Filter tracks by prefix
    prefix = f"{mood}_"
    matching = [t for t in available_tracks if t["name"].startswith(prefix)]

    if not matching:
        return None

    return random.choice(matching)


def _list_music_tracks() -> list[dict]:
    """List all music tracks from Google Drive folder.

    Returns:
        List of dicts with 'name' and 'id' keys
    """
    from clients.google_client import GoogleClient

    client = GoogleClient()
    files = client.list_files_in_folder(MUSIC_FOLDER_ID)

    # Filter to only audio files
    audio_extensions = {".mp3", ".wav", ".m4a", ".ogg"}
    tracks = []
    for f in files:
        name = f.get("name", "")
        if any(name.lower().endswith(ext) for ext in audio_extensions):
            tracks.append({
                "name": name,
                "id": f.get("id"),
            })

    return tracks


async def select_music_for_script(
    anthropic_client,
    script_acts: dict[int, str],
) -> list[dict]:
    """Select background music for each act in a script.

    Args:
        anthropic_client: AnthropicClient instance
        script_acts: Dict mapping act number to act text

    Returns:
        List of dicts with: act, file, file_id, mood, volume
    """
    # Get available tracks
    available_tracks = _list_music_tracks()

    results = []

    # Process acts in order
    for act_num in sorted(script_acts.keys()):
        act_text = script_acts[act_num]

        # Classify mood
        mood = await classify_act_mood(anthropic_client, act_num, act_text)

        # Select track
        track = select_track_for_mood(mood, available_tracks)

        results.append({
            "act": act_num,
            "file": track['name'] if track else None,
            "file_id": track["id"] if track else None,
            "mood": mood,
            "volume": DEFAULT_VOLUME,
        })

    return results
