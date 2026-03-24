"""Text Segmentation Engine.

Splits a complete script into segments where each segment maps to exactly
one video clip. Each segment is approximately `words_per_clip` words (±3
word tolerance) and respects sentence boundaries.

The segmentation engine sits between script generation and image/animation
prompt generation in the pipeline.
"""

import re
from typing import Optional

from orchestrator.pipeline_config import VideoConfig, ACT_TEMPLATES
from shared.clients.sentence_utils import split_into_sentences as _split_into_sentences

# Clause-break words for splitting long sentences
_CLAUSE_BREAK_WORDS = {"but", "and", "because", "which", "where", "when", "while", "although", "however", "yet", "so", "then", "since", "unless"}

# Sentence-ending punctuation
_SENTENCE_END_RE = re.compile(r'[.!?](?:\s|$)')

# Scene marker pattern
_SCENE_MARKER_RE = re.compile(r'\*\*Scene\s+(\d+)\*\*', re.IGNORECASE)

# Act marker pattern (matches [ACT N — Title | timestamps | words])
_ACT_MARKER_RE = re.compile(
    r"\[ACT\s+(\d+)\s*[—–\-].*?\]",
    re.IGNORECASE,
)

# High-intensity action verbs
_HIGH_INTENSITY_WORDS = {
    "struck", "crashed", "exploded", "collapsed", "surged", "spiked",
    "shattered", "destroyed", "plummeted", "soared", "seized", "invaded",
    "weaponized", "detonated", "assassinated", "overthrew", "bankrupt",
    "annihilated", "devastated", "obliterated",
}

# Medium-intensity signal phrases
_MEDIUM_SIGNALS = [
    "here's what", "nobody tells you", "the real question",
    "what most people miss", "the hidden", "the pattern",
    "this is where", "consider this", "the framework",
    "compare this to", "in contrast", "the difference",
    "but here's", "the key insight", "what this means",
]



def _split_at_clause(text: str, target_words: int) -> tuple[str, str]:
    """Split a long sentence at the nearest clause boundary to target_words.

    Looks for commas, semicolons, em dashes, or clause-break words near
    the target word count.
    """
    words = text.split()
    if len(words) <= target_words + 3:
        return text, ""

    # Search around the target position for a good break point
    best_pos = None
    best_distance = len(words)

    for i in range(max(0, target_words - 5), min(len(words), target_words + 6)):
        word = words[i]
        # Check for punctuation breaks
        if word.endswith((",", ";", "—", "–")):
            dist = abs(i + 1 - target_words)
            if dist < best_distance:
                best_distance = dist
                best_pos = i + 1
        # Check for clause-break words
        elif word.lower().rstrip(",.;:") in _CLAUSE_BREAK_WORDS:
            dist = abs(i - target_words)
            if dist < best_distance:
                best_distance = dist
                best_pos = i

    if best_pos and best_pos >= 3 and (len(words) - best_pos) >= 3:
        return " ".join(words[:best_pos]), " ".join(words[best_pos:])

    # No good clause break found — split at target position
    return " ".join(words[:target_words]), " ".join(words[target_words:])


def _score_intensity(text: str, is_act_opener: bool) -> str:
    """Score a segment's animation intensity based on narrative content.

    Returns: "low", "medium", or "high"
    """
    if is_act_opener:
        return "high"

    text_lower = text.lower()
    words = set(text_lower.split())

    # Check for high-intensity signals
    if words & _HIGH_INTENSITY_WORDS:
        return "high"

    # Check for dramatic numbers ($200M, 70%, quadrupled, etc.)
    if re.search(r'\$[\d,.]+[BMTbmt]|\d+%|quadrupled|tripled|doubled|billion|trillion', text):
        return "high"

    # Check for medium-intensity signals
    for signal in _MEDIUM_SIGNALS:
        if signal in text_lower:
            return "medium"

    return "low"


def _assign_act(segment_index: int, total_segments: int, config: VideoConfig) -> int:
    """Assign an act number to a segment based on its position and ACT_TEMPLATES percentages."""
    templates = ACT_TEMPLATES.get(config.act_count, ACT_TEMPLATES[6])
    position_pct = segment_index / max(1, total_segments)

    cumulative = 0.0
    for i, tmpl in enumerate(templates):
        cumulative += tmpl["pct"]
        if position_pct < cumulative:
            return i + 1
    return config.act_count


def segment_script(script_text: str, config: VideoConfig) -> list[dict]:
    """Split script into segments for video clips.

    Each segment:
    - Is words_per_clip words ±3 word tolerance
    - Does not break mid-sentence (when possible)
    - Does not break mid-clause when possible
    - Maps 1:1 to a video clip

    Args:
        script_text: Full script text (may contain act markers and scene markers).
        config: VideoConfig with target word counts.

    Returns:
        List of segment dicts, each with:
        - index (int, 0-based)
        - text (str)
        - word_count (int)
        - estimated_duration_seconds (float)
        - act (int)
        - scene (int)
        - intensity ("low" | "medium" | "high")
        - warnings (list[str], optional)
    """
    target = config.words_per_clip
    min_words = config.segment_min_words
    max_words = config.segment_max_words

    # Strip act markers (they're metadata, not narration)
    clean_text = _ACT_MARKER_RE.sub("", script_text)

    # Split by scene markers
    scene_splits = _SCENE_MARKER_RE.split(clean_text)

    # Parse into (scene_number, scene_text) pairs
    scenes: list[tuple[int, str]] = []
    if len(scene_splits) <= 1:
        # No scene markers — treat entire text as one scene
        scenes.append((1, clean_text.strip()))
    else:
        # scene_splits alternates: [text_before, scene_num, text, scene_num, text, ...]
        # First element is any text before the first scene marker
        preamble = scene_splits[0].strip()
        if preamble:
            scenes.append((0, preamble))
        for i in range(1, len(scene_splits), 2):
            scene_num = int(scene_splits[i])
            scene_text = scene_splits[i + 1].strip() if i + 1 < len(scene_splits) else ""
            if scene_text:
                scenes.append((scene_num, scene_text))

    segments: list[dict] = []
    warnings: list[str] = []

    for scene_num, scene_text in scenes:
        if not scene_text.strip():
            continue

        sentences = _split_into_sentences(scene_text)
        buffer: list[str] = []
        buffer_wc = 0

        for sentence in sentences:
            sentence_wc = len(sentence.split())

            # If a single sentence exceeds max_words, split it at clause boundary
            if sentence_wc > max_words:
                # Flush current buffer first
                if buffer:
                    segments.append(_make_segment(
                        " ".join(buffer), buffer_wc, scene_num, len(segments),
                    ))
                    buffer = []
                    buffer_wc = 0

                # Split the long sentence into multiple segments
                remaining = sentence
                while remaining:
                    remaining_wc = len(remaining.split())
                    if remaining_wc <= max_words:
                        buffer = [remaining]
                        buffer_wc = remaining_wc
                        break
                    part, remaining = _split_at_clause(remaining, target)
                    segments.append(_make_segment(
                        part, len(part.split()), scene_num, len(segments),
                    ))
                continue

            # Would adding this sentence exceed the max?
            if buffer_wc + sentence_wc > max_words and buffer:
                # Flush the buffer as a segment
                segments.append(_make_segment(
                    " ".join(buffer), buffer_wc, scene_num, len(segments),
                ))
                buffer = [sentence]
                buffer_wc = sentence_wc
            else:
                buffer.append(sentence)
                buffer_wc += sentence_wc

                # If we hit the target window, flush
                if buffer_wc >= min_words:
                    segments.append(_make_segment(
                        " ".join(buffer), buffer_wc, scene_num, len(segments),
                    ))
                    buffer = []
                    buffer_wc = 0

        # Flush remaining buffer
        if buffer:
            # If it's too short and we can merge with previous segment in same scene
            if buffer_wc < min_words and segments and segments[-1]["scene"] == scene_num:
                prev = segments[-1]
                prev["text"] = prev["text"] + " " + " ".join(buffer)
                prev["word_count"] = len(prev["text"].split())
                prev["estimated_duration_seconds"] = prev["word_count"] / config.SPEAKING_RATE_WPS
            else:
                segments.append(_make_segment(
                    " ".join(buffer), buffer_wc, scene_num, len(segments),
                ))

    # Re-index and assign acts + intensity
    total = len(segments)
    act_openers: set[int] = set()

    for i, seg in enumerate(segments):
        seg["index"] = i
        seg["act"] = _assign_act(i, total, config)

        # Track act openers (first segment of each act)
        if seg["act"] not in act_openers:
            act_openers.add(seg["act"])
            is_act_opener = True
        else:
            is_act_opener = False

        seg["intensity"] = _score_intensity(seg["text"], is_act_opener)

    # Check total segment count vs expected
    expected = config.total_clips
    if total < expected * 0.85:
        warnings.append(
            f"Segment count ({total}) is {total - expected} below expected ({expected}). "
            f"Script may be too short."
        )
    elif total > expected * 1.15:
        warnings.append(
            f"Segment count ({total}) is {total - expected} above expected ({expected}). "
            f"Script may be too long."
        )

    if warnings:
        # Attach warnings to the first segment for downstream reporting
        if segments:
            segments[0]["warnings"] = warnings

    return segments


def _make_segment(text: str, word_count: int, scene: int, index: int) -> dict:
    """Create a segment dict with computed fields.

    clip_duration is assigned dynamically based on estimated narration time:
    - <= 6 seconds of narration → 6s clip
    - > 6 seconds of narration → 10s clip
    Remotion trims the clip to fit the actual voiceover duration.
    """
    estimated_duration = word_count / VideoConfig.SPEAKING_RATE_WPS
    clip_duration = 6 if estimated_duration <= 6.0 else 10
    return {
        "index": index,
        "text": text.strip(),
        "word_count": word_count,
        "estimated_duration_seconds": estimated_duration,
        "clip_duration": clip_duration,
        "act": 0,  # assigned later
        "scene": scene,
        "intensity": "low",  # assigned later
    }


# ---------------------------------------------------------------------------
# Post-segmentation duration cap enforcement
# ---------------------------------------------------------------------------

_DURATION_FLOOR_SECONDS = 4.0
_MIN_SEGMENT_WORDS = int(_DURATION_FLOOR_SECONDS * VideoConfig.SPEAKING_RATE_WPS)  # 10


def enforce_duration_caps(
    segments: list[dict],
    clip_duration_seconds: int = 10,
) -> list[dict]:
    """Split any segment that exceeds the clip duration ceiling.

    This is a **post-segmentation safety net** that runs after Claude returns
    concept segments and before Airtable records are created.

    Args:
        segments: List of segment dicts (must have "text" key, may have "concept"
            or "image_prompt" — those are carried forward to the first sub-segment).
        clip_duration_seconds: Maximum clip duration (6 or 10).

    Returns:
        New list of segments where every segment is ≤ max_words and ≥ min_words.
        Total word count is preserved (no words lost or added).
    """
    max_words = int(clip_duration_seconds * VideoConfig.SPEAKING_RATE_WPS)
    min_words = _MIN_SEGMENT_WORDS

    validated: list[dict] = []

    for seg in segments:
        text = seg.get("text", "")
        word_count = len(text.split())

        if word_count <= max_words:
            validated.append(seg)
            continue

        # Over ceiling — split at sentence boundaries first
        sentences = _split_into_sentences(text)
        current_chunk: list[str] = []
        current_words = 0

        for sentence in sentences:
            sentence_words = len(sentence.split())

            # Single sentence exceeds max — split at clause boundary
            if sentence_words > max_words:
                # Flush current buffer first
                if current_chunk and current_words >= min_words:
                    validated.append(_make_cap_segment(
                        " ".join(current_chunk), seg,
                    ))
                    current_chunk = []
                    current_words = 0
                elif current_chunk:
                    # Buffer too small to flush alone — prepend to long sentence
                    sentence = " ".join(current_chunk) + " " + sentence
                    sentence_words = len(sentence.split())
                    current_chunk = []
                    current_words = 0

                # Repeatedly split at clause boundary until under ceiling
                remaining = sentence
                while remaining:
                    remaining_wc = len(remaining.split())
                    if remaining_wc <= max_words:
                        current_chunk = [remaining]
                        current_words = remaining_wc
                        break
                    part, leftover = _split_at_clause(remaining, max_words)
                    if not leftover:
                        # _split_at_clause refused to split (within its tolerance) —
                        # force a hard word-boundary split at max_words
                        words = remaining.split()
                        part = " ".join(words[:max_words])
                        leftover = " ".join(words[max_words:])
                    validated.append(_make_cap_segment(part, seg))
                    remaining = leftover
                continue

            # Would adding this sentence exceed the max?
            if current_words + sentence_words > max_words and current_chunk:
                # Flush current buffer — even if short, hard cap takes priority
                validated.append(_make_cap_segment(
                    " ".join(current_chunk), seg,
                ))
                current_chunk = [sentence]
                current_words = sentence_words
            else:
                current_chunk.append(sentence)
                current_words += sentence_words

        # Flush remainder
        if current_chunk:
            prev_wc = len(validated[-1]["text"].split()) if validated else 0
            if current_words < min_words and validated and prev_wc + current_words <= max_words:
                # Merge short remainder with previous segment only if it won't breach the cap
                prev = validated[-1]
                prev["text"] = prev["text"] + " " + " ".join(current_chunk)
            else:
                validated.append(_make_cap_segment(
                    " ".join(current_chunk), seg,
                ))

    return validated


def _make_cap_segment(text: str, source_seg: dict) -> dict:
    """Create a new segment dict from split text, carrying forward metadata."""
    return {
        "text": text.strip(),
        "concept": source_seg.get("concept", "continued"),
        "image_prompt": source_seg.get("image_prompt", ""),
        "shot_type": source_seg.get("shot_type", ""),
    }


def recalculate_durations(
    segments: list[dict],
    clip_duration_seconds: int = 10,
) -> list[dict]:
    """Recalculate and clamp estimated_duration for each segment.

    Call this after enforce_duration_caps() to ensure all duration values
    are consistent with the word counts and within the valid range.

    Args:
        segments: List of segment dicts (must have "text" key).
        clip_duration_seconds: Maximum clip duration for clamping.

    Returns:
        Same list with updated word_count and estimated_duration fields.
    """
    floor = _DURATION_FLOOR_SECONDS

    for seg in segments:
        wc = len(seg.get("text", "").split())
        seg["word_count"] = wc
        raw_duration = wc / VideoConfig.SPEAKING_RATE_WPS
        seg["estimated_duration"] = max(floor, min(float(clip_duration_seconds), raw_duration))

    return segments
