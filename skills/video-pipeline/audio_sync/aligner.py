"""
Scene-to-timestamp alignment.

Matches each scene's ``script_excerpt`` to a span of Whisper word
timestamps using sequential fuzzy matching.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .config import MIN_MATCH_RATIO, SEARCH_WINDOW_MULTIPLIER
from .transcriber import WordTimestamp


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Core alignment
# ---------------------------------------------------------------------------

def align_scenes_to_timestamps(
    scenes: list[dict[str, Any]],
    whisper_words: list[WordTimestamp],
    min_match_ratio: float = MIN_MATCH_RATIO,
) -> list[dict[str, Any]]:
    """
    Sequentially align each scene's ``script_excerpt`` to a span of
    Whisper word timestamps.

    Key insight: scenes are **in order**.  Scene 1's text comes before
    scene 2's in the audio so we only need to search forward from the
    last match.

    Returns:
        Copy of *scenes* with ``start_time``, ``end_time``,
        ``alignment_score``, ``alignment_method``, ``word_count``,
        and ``duration`` added.
    """
    word_pointer = 0
    aligned: list[dict[str, Any]] = []

    for scene in scenes:
        excerpt = scene.get("script_excerpt", "") or ""
        excerpt_words = normalize_text(excerpt).split()
        excerpt_len = len(excerpt_words)

        if excerpt_len == 0:
            aligned.append({
                **scene,
                "start_time": None,
                "end_time": None,
                "alignment_method": "no_narration",
            })
            continue

        # Search forward from current pointer
        best_start = word_pointer
        best_score: float = 0.0

        search_limit = min(
            word_pointer + excerpt_len * SEARCH_WINDOW_MULTIPLIER,
            len(whisper_words),
        )

        for i in range(word_pointer, search_limit):
            span = whisper_words[i: i + excerpt_len]
            if len(span) < excerpt_len:
                break

            whisper_text = " ".join(normalize_text(w.word) for w in span)
            excerpt_text = " ".join(excerpt_words)

            score = SequenceMatcher(None, excerpt_text, whisper_text).ratio()

            if score > best_score:
                best_score = score
                best_start = i

        if best_score >= min_match_ratio:
            match_end = min(best_start + excerpt_len - 1, len(whisper_words) - 1)

            aligned.append({
                **scene,
                "start_time": whisper_words[best_start].start,
                "end_time": whisper_words[match_end].end,
                "alignment_score": round(best_score, 4),
                "alignment_method": "fuzzy_match",
                "word_count": excerpt_len,
                "duration": round(
                    whisper_words[match_end].end - whisper_words[best_start].start, 4
                ),
            })
            word_pointer = match_end + 1
        else:
            aligned.append({
                **scene,
                "start_time": None,
                "end_time": None,
                "alignment_score": round(best_score, 4),
                "alignment_method": "failed",
            })

    # Fix failed alignments by interpolation
    aligned = interpolate_failed_alignments(aligned)
    return aligned


# ---------------------------------------------------------------------------
# Interpolation for failed alignments
# ---------------------------------------------------------------------------

def interpolate_failed_alignments(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    For scenes that failed to align, estimate timing by interpolating
    between the nearest successfully aligned neighbours.
    """
    for i, scene in enumerate(scenes):
        if scene.get("start_time") is not None:
            continue
        # Don't overwrite intentional no-narration scenes
        if scene.get("alignment_method") == "no_narration":
            continue

        # Find previous aligned end
        prev_end = 0.0
        for j in range(i - 1, -1, -1):
            if scenes[j].get("end_time") is not None:
                prev_end = scenes[j]["end_time"]
                break

        # Find next aligned start
        next_start = prev_end + 10.0  # fallback
        for j in range(i + 1, len(scenes)):
            if scenes[j].get("start_time") is not None:
                next_start = scenes[j]["start_time"]
                break

        # Count consecutive unaligned scenes in this gap
        gap_count = 0
        for j in range(i, len(scenes)):
            if scenes[j].get("start_time") is not None:
                break
            gap_count += 1

        gap_duration = next_start - prev_end
        segment_duration = gap_duration / max(gap_count, 1)

        position_in_gap = 0
        for j in range(i, i + gap_count):
            scenes[j]["start_time"] = round(prev_end + position_in_gap * segment_duration, 4)
            scenes[j]["end_time"] = round(prev_end + (position_in_gap + 1) * segment_duration, 4)
            scenes[j]["alignment_method"] = "interpolated"
            scenes[j]["duration"] = round(segment_duration, 4)
            position_in_gap += 1

    return scenes


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_alignment(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """Check alignment quality and flag issues."""
    issues: list[str] = []

    # 1. No overlapping timestamps
    for i in range(len(scenes) - 1):
        cur_end = scenes[i].get("end_time")
        nxt_start = scenes[i + 1].get("start_time")
        if cur_end is not None and nxt_start is not None and cur_end > nxt_start + 0.05:
            issues.append(
                f"Scene {scenes[i].get('scene_number')} overlaps with "
                f"scene {scenes[i + 1].get('scene_number')}: "
                f"{cur_end:.2f} > {nxt_start:.2f}"
            )

    # 2. No gaps larger than 3 seconds
    for i in range(len(scenes) - 1):
        cur_end = scenes[i].get("end_time")
        nxt_start = scenes[i + 1].get("start_time")
        if cur_end is not None and nxt_start is not None:
            gap = nxt_start - cur_end
            if gap > 3.0:
                issues.append(
                    f"Gap of {gap:.1f}s between scene "
                    f"{scenes[i].get('scene_number')} and "
                    f"{scenes[i + 1].get('scene_number')}"
                )

    # 3. Alignment score distribution
    scores = [
        s.get("alignment_score", 0)
        for s in scenes
        if s.get("alignment_method") == "fuzzy_match"
    ]
    avg_score = sum(scores) / len(scores) if scores else 0
    low_scores = [s for s in scores if s < 0.7]

    # 4. Alignment method counts
    methods: dict[str, int] = {}
    for s in scenes:
        m = s.get("alignment_method", "unknown")
        methods[m] = methods.get(m, 0) + 1

    # 5. Total duration
    last_end = 0.0
    for s in reversed(scenes):
        if s.get("end_time") is not None:
            last_end = s["end_time"]
            break

    quality = "good"
    if len(issues) > 0 or len(low_scores) >= 5:
        quality = "acceptable" if len(issues) < 5 else "needs_review"

    return {
        "total_scenes": len(scenes),
        "aligned_fuzzy": methods.get("fuzzy_match", 0),
        "aligned_interpolated": methods.get("interpolated", 0),
        "failed": methods.get("failed", 0),
        "no_narration": methods.get("no_narration", 0),
        "avg_alignment_score": round(avg_score, 3),
        "low_confidence_count": len(low_scores),
        "total_duration": round(last_end, 2),
        "overlaps": sum(1 for i in issues if "overlaps" in i),
        "large_gaps": sum(1 for i in issues if "Gap" in i),
        "issues": issues,
        "quality": quality,
    }
