"""
Scene-to-timestamp alignment.

Matches each scene's ``script_excerpt`` to a span of Whisper word
timestamps using sequential fuzzy matching, with a first-words anchor
fallback when full-excerpt matching fails.
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

def _find_best_match(
    excerpt_words: list[str],
    whisper_words: list[WordTimestamp],
    word_pointer: int,
    search_limit: int,
) -> tuple[int, float]:
    """Slide a window of len(excerpt_words) across whisper_words[word_pointer:search_limit]
    and return (best_start_index, best_score)."""
    excerpt_len = len(excerpt_words)
    excerpt_text = " ".join(excerpt_words)
    best_start = word_pointer
    best_score: float = 0.0

    for i in range(word_pointer, search_limit):
        span = whisper_words[i: i + excerpt_len]
        if len(span) < excerpt_len:
            break
        whisper_text = " ".join(normalize_text(w.word) for w in span)
        score = SequenceMatcher(None, excerpt_text, whisper_text).ratio()
        if score > best_score:
            best_score = score
            best_start = i

    return best_start, best_score


def _find_anchor_match(
    excerpt_words: list[str],
    whisper_words: list[WordTimestamp],
    word_pointer: int,
    search_limit: int,
    anchor_size: int = 6,
    anchor_threshold: float = 0.55,
) -> tuple[int, float]:
    """Fallback: match just the first N words of the excerpt to find
    the approximate location, then score the full excerpt from there.

    This handles cases where Whisper rephrases middle/end of a sentence
    but gets the opening words roughly right.
    """
    if len(excerpt_words) < anchor_size:
        return word_pointer, 0.0

    anchor_words = excerpt_words[:anchor_size]
    anchor_text = " ".join(anchor_words)
    excerpt_text = " ".join(excerpt_words)
    excerpt_len = len(excerpt_words)

    best_start = word_pointer
    best_score: float = 0.0

    for i in range(word_pointer, min(search_limit, len(whisper_words) - anchor_size + 1)):
        span = whisper_words[i: i + anchor_size]
        whisper_text = " ".join(normalize_text(w.word) for w in span)
        score = SequenceMatcher(None, anchor_text, whisper_text).ratio()

        if score >= anchor_threshold:
            # Found a plausible anchor — now score the full excerpt from here
            full_span = whisper_words[i: i + excerpt_len]
            if len(full_span) >= excerpt_len // 2:  # at least half the words
                full_text = " ".join(normalize_text(w.word) for w in full_span)
                full_score = SequenceMatcher(None, excerpt_text, full_text).ratio()
                if full_score > best_score:
                    best_score = full_score
                    best_start = i

    return best_start, best_score


def align_scenes_to_timestamps(
    scenes: list[dict[str, Any]],
    whisper_words: list[WordTimestamp],
    min_match_ratio: float = MIN_MATCH_RATIO,
) -> list[dict[str, Any]]:
    """
    Sequentially align each scene's ``script_excerpt`` to a span of
    Whisper word timestamps.

    Strategy:
    1. Slide a window of excerpt_len words across the transcript within
       a generous search window.
    2. If the best score >= min_match_ratio, accept it.
    3. If not, try a first-words anchor match as a fallback.
    4. If still no match, estimate position proportionally and try there.

    Returns:
        Copy of *scenes* with ``start_time``, ``end_time``,
        ``alignment_score``, ``alignment_method``, ``word_count``,
        and ``duration`` added.
    """
    word_pointer = 0
    aligned: list[dict[str, Any]] = []
    total_words = len(whisper_words)
    num_scenes = len(scenes)

    # Compute proportional step: expected words per scene
    words_per_scene = total_words / max(num_scenes, 1)

    for scene_idx, scene in enumerate(scenes):
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

        # Generous search window: max of 3x excerpt, 2x proportional chunk,
        # or at least 500 words — ensures we don't miss due to narrow windows
        search_ahead = max(
            excerpt_len * SEARCH_WINDOW_MULTIPLIER,
            int(words_per_scene * 2),
            500,
        )
        search_limit = min(word_pointer + search_ahead, total_words)

        # --- Strategy 1: Full-excerpt sliding window ---
        best_start, best_score = _find_best_match(
            excerpt_words, whisper_words, word_pointer, search_limit,
        )

        # --- Strategy 2: First-words anchor (if full match failed) ---
        if best_score < min_match_ratio:
            anchor_start, anchor_score = _find_anchor_match(
                excerpt_words, whisper_words, word_pointer, search_limit,
            )
            if anchor_score > best_score:
                best_start = anchor_start
                best_score = anchor_score

        # --- Strategy 3: Proportional estimate (last resort before failing) ---
        if best_score < min_match_ratio:
            # Estimate where this scene SHOULD be based on position
            estimated_pos = int(scene_idx * words_per_scene)
            est_search_start = max(0, estimated_pos - int(words_per_scene))
            est_search_end = min(total_words, estimated_pos + int(words_per_scene * 2))

            est_start, est_score = _find_best_match(
                excerpt_words, whisper_words, est_search_start, est_search_end,
            )
            if est_score > best_score:
                best_start = est_start
                best_score = est_score

            # Also try anchor at estimated position
            if est_score < min_match_ratio:
                anc_start, anc_score = _find_anchor_match(
                    excerpt_words, whisper_words, est_search_start, est_search_end,
                )
                if anc_score > best_score:
                    best_start = anc_start
                    best_score = anc_score

        # Determine match span length — use excerpt_len but don't exceed transcript
        match_span = min(excerpt_len, total_words - best_start)
        match_end = min(best_start + match_span - 1, total_words - 1)

        if best_score >= min_match_ratio:
            method = "fuzzy_match"
            aligned.append({
                **scene,
                "start_time": whisper_words[best_start].start,
                "end_time": whisper_words[match_end].end,
                "alignment_score": round(best_score, 4),
                "alignment_method": method,
                "word_count": excerpt_len,
                "duration": round(
                    whisper_words[match_end].end - whisper_words[best_start].start, 4
                ),
            })
            word_pointer = match_end + 1
        elif best_score >= min_match_ratio * 0.7:
            # Marginal match — accept with lower confidence rather than
            # falling to interpolation (which loses all timing info)
            aligned.append({
                **scene,
                "start_time": whisper_words[best_start].start,
                "end_time": whisper_words[match_end].end,
                "alignment_score": round(best_score, 4),
                "alignment_method": "low_confidence",
                "word_count": excerpt_len,
                "duration": round(
                    whisper_words[match_end].end - whisper_words[best_start].start, 4
                ),
            })
            word_pointer = match_end + 1
        else:
            print(
                f"    [align] Scene {scene.get('scene_number', '?')} FAILED "
                f"(best_score={best_score:.3f}, excerpt_len={excerpt_len}, "
                f"pointer={word_pointer}/{total_words})"
            )
            # Show first 10 words of excerpt vs transcript for debugging
            e_preview = " ".join(excerpt_words[:10])
            w_preview = " ".join(
                normalize_text(w.word) for w in whisper_words[word_pointer:word_pointer + 10]
            ) if word_pointer < total_words else "(past end)"
            print(f"           excerpt: '{e_preview}...'")
            print(f"           whisper: '{w_preview}...'")

            aligned.append({
                **scene,
                "start_time": None,
                "end_time": None,
                "alignment_score": round(best_score, 4),
                "alignment_method": "failed",
            })
            # Still advance the pointer proportionally so later scenes
            # search in roughly the right region
            word_pointer = min(
                word_pointer + int(words_per_scene),
                total_words,
            )

    # Fix failed alignments by interpolation
    aligned = interpolate_failed_alignments(aligned, whisper_words)
    return aligned


# ---------------------------------------------------------------------------
# Interpolation for failed alignments
# ---------------------------------------------------------------------------

def interpolate_failed_alignments(
    scenes: list[dict[str, Any]],
    whisper_words: list[WordTimestamp] | None = None,
) -> list[dict[str, Any]]:
    """
    For scenes that failed to align, estimate timing by interpolating
    between the nearest successfully aligned neighbours.

    If ALL scenes failed and whisper_words is provided, distributes
    them evenly across the full audio duration instead of using a
    tiny fallback.
    """
    # Determine the full audio duration for the fallback case
    audio_end = 0.0
    if whisper_words:
        audio_end = whisper_words[-1].end if whisper_words else 0.0

    # Check if any scene was successfully aligned
    any_aligned = any(
        s.get("start_time") is not None and s.get("alignment_method") != "no_narration"
        for s in scenes
    )

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
        next_start = None
        for j in range(i + 1, len(scenes)):
            if scenes[j].get("start_time") is not None:
                next_start = scenes[j]["start_time"]
                break

        if next_start is None:
            # No subsequent aligned scene — use audio end if available,
            # otherwise a proportional fallback
            if audio_end > prev_end:
                next_start = audio_end
            else:
                next_start = prev_end + 10.0  # last resort

        # Count consecutive unaligned scenes in this gap
        gap_count = 0
        for j in range(i, len(scenes)):
            if scenes[j].get("start_time") is not None:
                break
            if scenes[j].get("alignment_method") == "no_narration":
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

    # 6. Quality assessment
    total_active = len(scenes) - methods.get("no_narration", 0)
    fuzzy_count = methods.get("fuzzy_match", 0)
    interpolated_count = methods.get("interpolated", 0)
    low_conf_count = methods.get("low_confidence", 0)

    if total_active > 0 and fuzzy_count == 0 and low_conf_count == 0:
        # ALL scenes interpolated — alignment completely failed
        quality = "failed"
        issues.insert(0, f"All {interpolated_count} scenes interpolated — no text matched the transcript")
    elif total_active > 0 and (fuzzy_count + low_conf_count) < total_active * 0.3:
        quality = "needs_review"
    elif len(issues) > 0 or len(low_scores) >= 5:
        quality = "acceptable" if len(issues) < 5 else "needs_review"
    else:
        quality = "good"

    return {
        "total_scenes": len(scenes),
        "aligned_fuzzy": fuzzy_count,
        "aligned_low_confidence": low_conf_count,
        "aligned_interpolated": interpolated_count,
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
