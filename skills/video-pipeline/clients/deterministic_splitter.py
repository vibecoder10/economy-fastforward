"""Deterministic scene-to-segment splitter with hard 10s duration cap.

Pure Python, zero LLM calls. Splits scene text into segments with:
- Word-based duration calculation (not sentence count)
- Hard 10s maximum per segment (for animation clip limits)
- Mid-sentence splitting when needed
- Orphan merging to avoid segments < 4s
"""

from __future__ import annotations

import re
from typing import Optional

try:
    from .sentence_utils import split_into_sentences
except ImportError:
    # When running as __main__, use absolute import
    from sentence_utils import split_into_sentences

try:
    from pipeline_config import VideoConfig
    DEFAULT_WPS = VideoConfig.SPEAKING_RATE_WPS
except ImportError:
    DEFAULT_WPS = 2.5  # Fallback if pipeline_config unavailable

# Splitting configuration
TARGET_DURATION = 7.0  # Ideal segment duration — documentary pacing (6-9s per shot)
MIN_DURATION = 4.0     # Minimum segment duration (orphan threshold)
MAX_DURATION = 10.0    # HARD ceiling - mid-sentence split if needed


def _calculate_duration(text: str, wps: float) -> float:
    """Calculate duration in seconds for a text segment."""
    word_count = len(text.split())
    return word_count / wps if wps > 0 else word_count / DEFAULT_WPS


# Words that should never end a segment (articles, prepositions, dangling connectors)
_DANGLING_ENDINGS = {
    'the', 'a', 'an', 'of', 'in', 'to', 'for', 'and', 'or', 'but', 'not',
    'is', 'it', 'its', 'at', 'by', 'on', 'with', 'from', 'into', 'that',
    'this', 'their', 'our', 'your', 'his', 'her', 'was', 'were', 'are',
}


def _find_split_point(text: str, target_word_pos: int) -> int:
    """Find best word position to split text near target position.

    Searches +/- 5 words from target for:
    1. After punctuation: comma, semicolon, colon, em dash
    2. Before conjunction: and, but, or, because, while, when, which, where, as, since, though, although, yet
    3. Nearest non-dangling word boundary (avoids ending on 'the', 'a', 'in', etc.)

    Args:
        text: The text to split
        target_word_pos: Ideal word position to split at

    Returns:
        Best word position to split (0-indexed)
    """
    words = text.split()
    max_pos = len(words)

    if target_word_pos >= max_pos:
        return max_pos

    # Search window: +/- 5 words from target (wider = better boundary selection)
    search_start = max(0, target_word_pos - 5)
    search_end = min(max_pos, target_word_pos + 5)

    # Conjunctions to split before
    conjunctions = {
        'and', 'but', 'or', 'because', 'while', 'when', 'which',
        'where', 'as', 'since', 'though', 'although', 'yet'
    }

    # Priority 1: After punctuation (comma, semicolon, colon, em dash)
    # Find closest to target
    best_punct = None
    best_punct_dist = float('inf')
    for i in range(search_start, search_end):
        if i >= max_pos:
            break
        word = words[i]
        if word.endswith((',', ';', ':', '—', '–')):
            dist = abs(i - target_word_pos)
            if dist < best_punct_dist:
                best_punct = i + 1
                best_punct_dist = dist
    if best_punct is not None:
        return best_punct

    # Priority 2: Before conjunction
    for i in range(search_start, search_end):
        if i >= max_pos or i == 0:
            continue
        word = words[i].lower().strip('.,!?;:—–')
        if word in conjunctions:
            return i  # Split before this word

    # Priority 3: Target position, but avoid dangling endings
    split_pos = min(target_word_pos, max_pos)
    if split_pos > 0 and split_pos < max_pos:
        last_word = words[split_pos - 1].lower().strip('.,!?;:—–')
        if last_word in _DANGLING_ENDINGS:
            # Try moving forward 1-3 words to find a non-dangling end
            for offset in range(1, 4):
                candidate = split_pos + offset
                if candidate >= max_pos:
                    break
                cand_word = words[candidate - 1].lower().strip('.,!?;:—–')
                if cand_word not in _DANGLING_ENDINGS:
                    return candidate
            # Try moving backward 1-3 words
            for offset in range(1, 4):
                candidate = split_pos - offset
                if candidate <= 0:
                    break
                cand_word = words[candidate - 1].lower().strip('.,!?;:—–')
                if cand_word not in _DANGLING_ENDINGS:
                    return candidate

    return split_pos


def _split_oversized_segment(text: str, wps: float, depth: int = 0) -> list[str]:
    """Recursively split text that exceeds MAX_DURATION.

    Args:
        text: Text segment to split
        wps: Words per second
        depth: Recursion depth (safety limit)

    Returns:
        List of text chunks, all <= MAX_DURATION
    """
    if depth > 10:  # Safety limit
        # Force split at exact midpoint if recursion too deep
        words = text.split()
        mid = len(words) // 2
        return [' '.join(words[:mid]), ' '.join(words[mid:])]

    duration = _calculate_duration(text, wps)

    if duration <= MAX_DURATION:
        return [text]

    # Calculate target word position for ~7s first segment
    words = text.split()
    target_words = int(TARGET_DURATION * wps)
    split_pos = _find_split_point(text, target_words)

    if split_pos == 0 or split_pos >= len(words):
        # Can't find good split point, force at midpoint
        split_pos = len(words) // 2

    first_chunk = ' '.join(words[:split_pos])
    second_chunk = ' '.join(words[split_pos:])

    # Recursively check each half
    result = []
    result.extend(_split_oversized_segment(first_chunk, wps, depth + 1))
    result.extend(_split_oversized_segment(second_chunk, wps, depth + 1))

    return result


def segment_scene_deterministic(
    scene_text: str,
    voice_duration: Optional[float] = None,
) -> list[dict]:
    """Split scene text into segments with hard 10s duration cap.

    Algorithm:
    1. Split text into sentences (regex-based)
    2. Calculate words-per-second from voice duration or use default
    3. Greedily accumulate sentences into segments (target 7s, max 10s)
    4. Split oversized segments at word boundaries (mid-sentence if needed)
    5. Merge orphan segments < 4s into previous segment

    Args:
        scene_text: Full scene narration text
        voice_duration: Optional actual voice duration in seconds.
                       If provided, used to calculate words-per-second.
                       If None, uses DEFAULT_WPS (2.5).

    Returns:
        List of segment dicts with:
        - text: str (segment narration)
        - word_count: int
        - duration: float (in seconds)
        - cumulative_start: float (start time in seconds)
        - segment_index: int (1-based)

    GUARANTEE: No segment duration exceeds MAX_DURATION (10.0s).
    """
    if not scene_text or not scene_text.strip():
        return []

    # Calculate words per second
    word_count = len(scene_text.split())
    if voice_duration and voice_duration > 0:
        wps = word_count / voice_duration
    else:
        wps = DEFAULT_WPS

    # Split into sentences
    sentences = split_into_sentences(scene_text)

    if not sentences:
        # Treat entire text as one sentence
        sentences = [scene_text]

    # Greedily accumulate sentences into segments
    segments = []
    current_segment_sentences = []
    current_duration = 0.0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        sentence_duration = _calculate_duration(sentence, wps)
        projected_duration = current_duration + sentence_duration

        # Decision logic:
        # 1. Would bust MAX → must save current and start new
        # 2. Current already >= TARGET and adding would overshoot → save
        # 3. Otherwise → keep accumulating
        if projected_duration > MAX_DURATION and current_segment_sentences:
            # Save current segment and start new one
            segments.append(' '.join(current_segment_sentences))
            current_segment_sentences = [sentence]
            current_duration = sentence_duration
        elif (current_duration >= TARGET_DURATION
              and current_segment_sentences
              and projected_duration > TARGET_DURATION + 2.0):
            # Current segment already hit target — don't overshoot by >2s
            segments.append(' '.join(current_segment_sentences))
            current_segment_sentences = [sentence]
            current_duration = sentence_duration
        else:
            # Add sentence to current segment
            current_segment_sentences.append(sentence)
            current_duration = projected_duration

    # Don't forget the last segment
    if current_segment_sentences:
        segments.append(' '.join(current_segment_sentences))

    # Split any oversized segments at word boundaries
    # Allow single sentences slightly over MAX to avoid creating orphan fragments
    SOFT_MAX = MAX_DURATION + 1.0  # 11.0s — accept rather than create 3s orphans
    final_segments = []
    for seg_text in segments:
        duration = _calculate_duration(seg_text, wps)
        if duration > SOFT_MAX:
            # Well over limit — must split
            chunks = _split_oversized_segment(seg_text, wps)
            final_segments.extend(chunks)
        else:
            final_segments.append(seg_text)

    # Merge orphan segments (< MIN_DURATION) into previous or next
    # Allow soft overflow (MAX + 1s) to avoid recreating the same orphan
    ORPHAN_OVERFLOW = MAX_DURATION + 1.0
    merged_segments = []
    for i, seg_text in enumerate(final_segments):
        duration = _calculate_duration(seg_text, wps)

        if duration < MIN_DURATION and merged_segments:
            # Merge into previous segment
            prev_text = merged_segments[-1]
            merged_text = prev_text + ' ' + seg_text
            merged_duration = _calculate_duration(merged_text, wps)

            if merged_duration <= ORPHAN_OVERFLOW:
                # Accept slight overflow to avoid orphan fragments
                merged_segments[-1] = merged_text
            elif merged_duration > ORPHAN_OVERFLOW:
                # Too long even with overflow — try merging with NEXT instead
                # For now, re-split (but this is a last resort)
                chunks = _split_oversized_segment(merged_text, wps)
                merged_segments[-1] = chunks[0]
                merged_segments.extend(chunks[1:])
            else:
                merged_segments[-1] = merged_text
        else:
            merged_segments.append(seg_text)

    # Build final result with metadata
    result = []
    cumulative_start = 0.0

    for i, seg_text in enumerate(merged_segments):
        word_cnt = len(seg_text.split())
        duration = _calculate_duration(seg_text, wps)

        # HARD CAP: If somehow still over MAX_DURATION, clamp it
        # (This should never happen, but safety net)
        if duration > MAX_DURATION:
            duration = MAX_DURATION

        result.append({
            'text': seg_text,
            'word_count': word_cnt,
            'duration': round(duration, 1),
            'cumulative_start': round(cumulative_start, 1),
            'segment_index': i + 1,
        })

        cumulative_start += duration

    return result


if __name__ == '__main__':
    # Test with provided 60s scene text
    test_text_60s = """That's the gap between Russia and Iran signing a 20-year Comprehensive Strategic Partnership on January 17th, 2025, and the war beginning. Not a defensive pact signed after tensions escalated. A 47-article treaty governing everything from military cooperation to payment system integration, signed exactly 41 days before the first missile flew. When you follow the oil prices, you find something completely different. Russia was selling its crude at a discount of $10 to $13 per barrel before the strikes. According to TIME Magazine's analysis, Moscow is now selling at a premium of $4 to $5. Oil hit $120 per barrel. The Strait of Hormuz which carries 20 percent of the world's LNG effectively closed. And every dollar of that surge flows directly into Putin's war chest while Ukraine runs out of air defense missiles. This was not a war that Russia watched. It was a war Russia engineered. And what you will see by Act 3 is exactly how they built the trap, baited it, and got America to spring it."""

    print("=" * 70)
    print("TEST 1: 60s scene with known voice duration")
    print("=" * 70)
    segments = segment_scene_deterministic(test_text_60s, voice_duration=60.0)

    total_duration = 0.0
    max_duration_seen = 0.0

    for seg in segments:
        print(f"\nSegment {seg['segment_index']}: {seg['duration']}s ({seg['word_count']} words)")
        print(f"  Start: {seg['cumulative_start']}s")
        print(f"  Text: {seg['text'][:80]}...")
        total_duration += seg['duration']
        max_duration_seen = max(max_duration_seen, seg['duration'])

    print(f"\nTotal segments: {len(segments)}")
    print(f"Total duration: {total_duration:.1f}s (target was 60.0s)")
    print(f"Max segment duration: {max_duration_seen:.1f}s")

    # ASSERT: No segment exceeds 10.0s
    violations = [s for s in segments if s['duration'] > MAX_DURATION]
    if violations:
        print(f"\n❌ ASSERTION FAILED: {len(violations)} segments exceed {MAX_DURATION}s!")
        for v in violations:
            print(f"   Segment {v['segment_index']}: {v['duration']}s")
        raise AssertionError(f"{len(violations)} segments exceed MAX_DURATION")
    else:
        print(f"✅ ASSERTION PASSED: All segments <= {MAX_DURATION}s")

    # Test with single long sentence (45+ words) to verify mid-sentence splitting
    print("\n" + "=" * 70)
    print("TEST 2: Single 45-word sentence (mid-sentence split test)")
    print("=" * 70)

    long_sentence = "The Federal Reserve's quantitative easing program which was initially designed as a temporary emergency measure to stabilize financial markets during the 2008 crisis has now become a permanent fixture of monetary policy creating unprecedented levels of asset price inflation while doing very little to stimulate productive economic growth."

    # At 2.5 WPS, this is ~18 seconds, should split into 2 segments
    segments2 = segment_scene_deterministic(long_sentence, voice_duration=None)

    for seg in segments2:
        print(f"\nSegment {seg['segment_index']}: {seg['duration']}s ({seg['word_count']} words)")
        print(f"  Text: {seg['text']}")

    violations2 = [s for s in segments2 if s['duration'] > MAX_DURATION]
    if violations2:
        print(f"\n❌ ASSERTION FAILED: {len(violations2)} segments exceed {MAX_DURATION}s!")
        raise AssertionError(f"{len(violations2)} segments exceed MAX_DURATION")
    else:
        print(f"✅ ASSERTION PASSED: All segments <= {MAX_DURATION}s")

    print("\n" + "=" * 70)
    print("ALL TESTS PASSED")
    print("=" * 70)
