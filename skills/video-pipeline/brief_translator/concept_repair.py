"""Concept validation and text repair utilities for scene expansion.

Handles verbatim text matching, gap absorption, concept merging/splitting,
and last-resort sentence-boundary fallback.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from .expander_config import (
    MIN_CONCEPTS,
    MAX_CONCEPTS,
    MIN_WORDS_PER_CONCEPT,
    MAX_WORDS_PER_CONCEPT,
    get_valid_styles,
    get_valid_compositions,
    get_default_style,
    _pick_composition,
)


def _repair_concept_text(
    concept_text: str,
    scene_text: str,
    search_start: int = 0,
) -> tuple[str | None, int]:
    """Find the closest verbatim substring in scene_text for a non-matching concept.

    Uses difflib.SequenceMatcher to find the longest matching block between
    the concept's (possibly rewritten) text and the original scene text,
    then expands to cover approximately the same word count.

    Args:
        concept_text: The concept's sentence_text (may be rewritten by LLM).
        scene_text: The full scene narration (normalized whitespace).
        search_start: Position in scene_text to start searching from.

    Returns:
        (repaired_text, end_position) if a match is found with >=50% similarity,
        or (None, search_start) if no reasonable match exists.
    """
    if not concept_text or not scene_text:
        return None, search_start

    normalized_concept = " ".join(concept_text.split())
    search_region = scene_text[search_start:]

    # Find longest matching block in the search region
    matcher = SequenceMatcher(None, normalized_concept.lower(), search_region.lower())
    match = matcher.find_longest_match(0, len(normalized_concept), 0, len(search_region))

    if match.size < 10:  # Need at least 10 chars of matching text
        return None, search_start

    # Expand around the matching block to cover ~ the same word count
    target_words = len(normalized_concept.split())
    match_start_in_region = match.b

    # Find word boundaries around the match
    abs_start = search_start + match_start_in_region

    # Walk backwards to a word boundary
    while abs_start > search_start and scene_text[abs_start - 1] != " ":
        abs_start -= 1

    # Extract words from abs_start and take target_words count
    remaining = scene_text[abs_start:]
    words = remaining.split()
    if not words:
        return None, search_start

    # Take the target number of words
    extract_words = words[:target_words]
    candidate = " ".join(extract_words)
    end_pos = abs_start + len(candidate)

    # Verify the repair has reasonable similarity to the original concept
    similarity = SequenceMatcher(
        None, normalized_concept.lower(), candidate.lower()
    ).ratio()

    if similarity < 0.40:
        return None, search_start

    return candidate, end_pos


def _repair_all_concepts(concepts: list[dict], scene_text: str) -> list[dict]:
    """Re-validate and repair all concepts to ensure verbatim text.

    Every concept's sentence_text is checked against the scene_text.
    Non-matching concepts are repaired via fuzzy matching. Concepts that
    can't be repaired are dropped. Gaps in coverage are absorbed.

    Returns a new list of concepts with guaranteed verbatim sentence_text.
    """
    normalized_source = " ".join(scene_text.split())
    repaired: list[dict] = []
    search_start = 0
    repairs_made = 0

    for concept in concepts:
        text = concept.get("sentence_text", "")
        if not text:
            continue

        normalized_text = " ".join(text.split())

        # Check if already verbatim
        pos = normalized_source.find(normalized_text, search_start)
        if pos == -1:
            pos = normalized_source.lower().find(normalized_text.lower(), search_start)

        if pos != -1:
            # Verbatim match — absorb any gap before it
            gap = normalized_source[search_start:pos].strip()
            if gap and repaired:
                repaired[-1]["sentence_text"] = (
                    repaired[-1]["sentence_text"] + " " + gap
                ).strip()
            elif gap:
                concept["sentence_text"] = (gap + " " + normalized_text).strip()
                normalized_text = concept["sentence_text"]
                pos = search_start

            search_start = pos + len(normalized_text)
            repaired.append(dict(concept))
        else:
            # Not verbatim — attempt repair
            fixed_text, end_pos = _repair_concept_text(
                normalized_text, normalized_source, search_start
            )
            if fixed_text:
                # Absorb any gap
                gap = normalized_source[search_start:normalized_source.find(fixed_text, search_start)].strip()
                if gap and repaired:
                    repaired[-1]["sentence_text"] = (
                        repaired[-1]["sentence_text"] + " " + gap
                    ).strip()
                elif gap:
                    fixed_text = gap + " " + fixed_text

                concept_copy = dict(concept)
                concept_copy["sentence_text"] = fixed_text.strip()
                concept_copy["needs_new_prompt"] = True
                repaired.append(concept_copy)
                search_start = end_pos
                repairs_made += 1
                print(f"      Repaired concept: '{text[:50]}...' → '{fixed_text[:50]}...'")
            else:
                # Can't repair — drop this concept, its coverage will be
                # absorbed as a gap by the next concept or trailing handler
                print(f"      Dropped unrepairable concept: '{text[:50]}...'")

    # Absorb any trailing text
    trailing = normalized_source[search_start:].strip()
    if trailing:
        if repaired:
            repaired[-1]["sentence_text"] = (
                repaired[-1]["sentence_text"] + " " + trailing
            ).strip()
        else:
            # No concepts survived — create one covering everything
            repaired.append({
                "concept_index": 1,
                "sentence_text": normalized_source,
                "visual_description": normalized_source,
                "visual_style": get_default_style(),
                "composition": _pick_composition(get_default_style(), 0, []),
                "mood": "tension",
                "needs_new_prompt": True,
            })

    # Re-index
    for i, c in enumerate(repaired):
        c["concept_index"] = i + 1

    if repairs_made:
        print(f"      Verbatim repair: {repairs_made} concept(s) repaired")

    return repaired


def _validate_concepts(
    concepts: list[dict],
    scene_text: str,
    expected_count: int,
    relaxed: bool = False,
) -> tuple[bool, str]:
    """Validate that concepts cover the full narration text exactly.

    Args:
        relaxed: When True, auto-fix minor issues (gaps, word counts) instead
            of rejecting. Used on later retry attempts — a slightly imperfect
            LLM result is far better than a mechanical fallback.

    Returns (is_valid, error_message).
    """
    if not concepts:
        return False, "No concepts returned"

    # Relaxed mode: accept fewer concepts (min 3) — longer image durations
    # are better than wrong/duplicate images from a mechanical fallback.
    min_concepts = 3 if relaxed else MIN_CONCEPTS
    if len(concepts) < min_concepts:
        return False, f"Only {len(concepts)} concepts (minimum {min_concepts})"

    max_allowed = MAX_CONCEPTS + (4 if relaxed else 2)
    if len(concepts) > max_allowed:
        return False, f"Too many concepts: {len(concepts)} (maximum {max_allowed})"

    # Normalize whitespace for comparison
    normalized_source = " ".join(scene_text.split())

    # Check that each concept's sentence_text is a substring in order
    search_start = 0
    # In relaxed mode, allow larger gaps and auto-absorb them
    max_gap_words = 10 if relaxed else 3
    for i, concept in enumerate(concepts):
        text = concept.get("sentence_text", "")
        if not text:
            if relaxed:
                # Drop empty concepts instead of failing
                continue
            return False, f"Concept {i + 1} has empty sentence_text"

        normalized_text = " ".join(text.split())
        pos = normalized_source.find(normalized_text, search_start)
        if pos == -1:
            # Try case-insensitive as a fallback
            pos = normalized_source.lower().find(normalized_text.lower(), search_start)
            if pos == -1:
                if relaxed:
                    # Repair via fuzzy matching instead of dropping
                    fixed_text, end_pos = _repair_concept_text(
                        normalized_text, normalized_source, search_start
                    )
                    if fixed_text:
                        concept["sentence_text"] = fixed_text
                        concept["needs_new_prompt"] = True
                        pos = normalized_source.find(fixed_text, search_start)
                        if pos == -1:
                            pos = search_start
                        print(
                            f"      Repaired concept {i + 1} to verbatim: "
                            f"'{fixed_text[:50]}...'"
                        )
                    else:
                        # Mark for removal — will be absorbed as gap
                        concept["sentence_text"] = ""
                        continue
                else:
                    return False, (
                        f"Concept {i + 1} sentence_text not found in narration "
                        f"(starting from position {search_start}): "
                        f"'{normalized_text[:60]}...'"
                    )

        # Check for gaps — absorb small gaps into preceding concept
        gap = normalized_source[search_start:pos].strip()
        if gap:
            gap_wc = len(gap.split())
            if gap_wc <= max_gap_words:
                # Auto-absorb gap into previous concept (or current if first)
                if i > 0 and concepts[i - 1].get("sentence_text"):
                    concepts[i - 1]["sentence_text"] = (
                        concepts[i - 1]["sentence_text"] + " " + gap
                    ).strip()
                else:
                    concept["sentence_text"] = (gap + " " + concept["sentence_text"]).strip()
            elif not relaxed:
                return False, (
                    f"Gap of {gap_wc} words between concepts {i} and {i + 1}: "
                    f"'{gap[:60]}...'"
                )
            # In relaxed mode with large gaps, absorb into previous anyway
            elif i > 0 and concepts[i - 1].get("sentence_text"):
                concepts[i - 1]["sentence_text"] = (
                    concepts[i - 1]["sentence_text"] + " " + gap
                ).strip()

        search_start = pos + len(normalized_text)

    # Remove concepts that were marked for skipping (empty sentence_text)
    if relaxed:
        concepts[:] = [c for c in concepts if c.get("sentence_text")]
        if not concepts:
            return False, "All concepts had invalid sentence_text"

    # Check trailing text — auto-fix by appending to last concept
    trailing = normalized_source[search_start:].strip()
    if trailing:
        trailing_wc = len(trailing.split())
        # In relaxed mode, always absorb trailing text
        if trailing_wc <= 20 or relaxed:
            last = concepts[-1]
            last["sentence_text"] = (last.get("sentence_text", "") + " " + trailing).strip()
        elif trailing_wc > 20:
            return False, f"Uncovered trailing text ({trailing_wc} words): '{trailing[:60]}...'"

    # Validate word count and visual fields
    # Relaxed mode: accept up to 50 words (downstream split handles it)
    hard_reject_words = 50 if relaxed else 30
    for i, concept in enumerate(concepts):
        text = concept.get("sentence_text", "")
        wc = len(text.split())
        if wc > hard_reject_words:
            return False, (
                f"Concept {i + 1} has {wc} words (max {hard_reject_words}): "
                f"'{text[:60]}...'"
            )

        style = concept.get("visual_style", "")
        if style not in get_valid_styles():
            concept["visual_style"] = get_default_style()

        comp = concept.get("composition", "")
        if comp not in get_valid_compositions():
            concept["composition"] = "medium"

        if not concept.get("visual_description"):
            if relaxed:
                # Use sentence text as a placeholder — marked for regeneration
                concept["visual_description"] = concept.get("sentence_text", "")
                concept["needs_new_prompt"] = True
            else:
                return False, f"Concept {i + 1} has no visual_description"

    return True, ""


def _split_at_clause_boundary(text: str) -> tuple[str, str]:
    """Split text at the nearest clause boundary (period, comma, semicolon, dash) near the midpoint.

    Falls back to midpoint word split if no suitable boundary produces
    two halves that both meet MIN_WORDS_PER_CONCEPT.
    """
    mid_char = len(text) // 2
    boundary_chars = ".,:;—–-"

    # Search outward from midpoint for nearest boundary character
    best_pos = None
    for offset in range(mid_char):
        for delta in [offset, -offset]:
            pos = mid_char + delta
            if 0 < pos < len(text) - 1 and text[pos] in boundary_chars:
                candidate = pos + 1
                part1 = text[:candidate].strip()
                part2 = text[candidate:].strip()
                if (
                    len(part1.split()) >= MIN_WORDS_PER_CONCEPT
                    and len(part2.split()) >= MIN_WORDS_PER_CONCEPT
                ):
                    best_pos = candidate
                    break
        if best_pos is not None:
            break

    if best_pos is not None:
        return text[:best_pos].strip(), text[best_pos:].strip()

    # No good boundary — fall back to midpoint word split
    words = text.split()
    mid = len(words) // 2
    return " ".join(words[:mid]), " ".join(words[mid:])


def _validate_concept_durations(concepts: list[dict]) -> list[dict]:
    """Merge too-short concepts and split too-long ones.

    Runs AFTER the LLM produces concepts and BEFORE image generation.
    This ensures every concept will display for 5-10 seconds when
    audio_sync calculates Whisper timestamps later.

    Concepts that are merged or split get ``needs_new_prompt = True``
    so the caller can regenerate their image prompt if needed.
    """
    validated: list[dict] = []
    i = 0

    while i < len(concepts):
        concept = {k: v for k, v in concepts[i].items()}  # shallow copy
        wc = len(concept.get("sentence_text", "").split())

        # Too short — merge with next concept
        if wc < MIN_WORDS_PER_CONCEPT and i + 1 < len(concepts):
            nxt = concepts[i + 1]
            concept["sentence_text"] = (
                concept["sentence_text"] + " " + nxt.get("sentence_text", "")
            ).strip()
            # Regenerate visual description for the merged concept
            concept["needs_new_prompt"] = True
            i += 2
        # Too long — split at nearest clause boundary
        elif wc > MAX_WORDS_PER_CONCEPT:
            text = concept["sentence_text"]
            part1_text, part2_text = _split_at_clause_boundary(text)

            part1 = dict(concept)
            part1["sentence_text"] = part1_text
            part1["needs_new_prompt"] = True

            part2 = dict(concept)
            part2["sentence_text"] = part2_text
            part2["needs_new_prompt"] = True

            validated.extend([part1, part2])
            i += 1
            continue
        else:
            i += 1

        validated.append(concept)

    # Re-index
    for idx, c in enumerate(validated):
        c["concept_index"] = idx + 1

    return validated


def _sentence_boundary_split(scene_text: str) -> list[dict]:
    """Last-resort split when ALL LLM attempts fail (e.g. network errors).

    Splits at sentence boundaries using the narration text itself as the
    visual description placeholder. Every concept is marked needs_new_prompt
    so downstream prompt generation will create proper descriptions.

    This produces fewer, longer-duration concepts — which is always better
    than generic keyword-matched templates that don't match the narration.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sentence_utils",
        Path(__file__).parent.parent / "clients" / "sentence_utils.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    split_into_sentences = mod.split_into_sentences

    sentences = split_into_sentences(scene_text)
    if not sentences:
        sentences = [scene_text]

    # Group sentences into chunks, allowing up to 40 words per chunk.
    # Longer chunks = longer image durations, which is fine.
    max_chunk_words = 40
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_wc = 0

    for sentence in sentences:
        swc = len(sentence.split())
        if current_chunk and current_wc + swc > max_chunk_words:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_wc = 0
        current_chunk.append(sentence)
        current_wc += swc

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    # Merge any final chunk that's too short with its predecessor
    if len(chunks) > 1 and len(chunks[-1].split()) < MIN_WORDS_PER_CONCEPT:
        chunks[-2] = chunks[-2] + " " + chunks[-1]
        chunks.pop()

    default_style = get_default_style()
    recent_comps: list[str] = []
    concepts = []
    for i, chunk in enumerate(chunks):
        comp = _pick_composition(default_style, i, recent_comps)
        recent_comps.append(comp)
        concepts.append({
            "concept_index": i + 1,
            "sentence_text": chunk,
            "visual_description": chunk,  # Use narration as placeholder
            "visual_style": default_style,
            "composition": comp,
            "mood": "tension",
            "needs_new_prompt": True,
        })

    return _validate_concept_durations(concepts)
