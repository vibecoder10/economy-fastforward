"""Scene-by-scene concept expansion.

Takes a single scene's narration text (from the Airtable Script table) and
expands it into 6-10 visual concepts. Each concept pairs an exact substring
of the narration with a filmable visual description.

This replaces the old batch-based system that glued 20 script records into
one big script and re-split them via LLM. The new system processes one
scene at a time — if one fails, only that scene retries.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "concept_expand.txt"


def _get_profile():
    """Return the active visual profile, or None."""
    try:
        from visual_profiles import load_profile
        return load_profile()
    except Exception:
        return None


# Hardcoded fallback valid styles
_DEFAULT_VALID_STYLES = {"dossier", "schema", "echo"}

# Hardcoded fallback compositions
_DEFAULT_COMPOSITIONS = {
    "wide", "medium", "closeup", "environmental",
    "portrait", "overhead", "low_angle",
}

# Hardcoded fallback style distribution
_DEFAULT_STYLE_DISTRIBUTION = {
    1: {"dossier": 90, "schema": 10, "echo": 0},
    2: {"dossier": 70, "schema": 30, "echo": 0},
    3: {"dossier": 45, "schema": 20, "echo": 35},
    4: {"dossier": 35, "schema": 20, "echo": 45},
    5: {"dossier": 50, "schema": 35, "echo": 15},
    6: {"dossier": 65, "schema": 35, "echo": 0},
}


def get_valid_styles() -> set:
    """Get valid visual styles from profile substyles or default."""
    profile = _get_profile()
    if profile and profile.style_system.substyles:
        return set(profile.style_system.substyles.keys())
    return _DEFAULT_VALID_STYLES


# Legacy name — callers should use get_valid_styles()
VALID_STYLES = _DEFAULT_VALID_STYLES


def get_valid_compositions() -> set:
    """Get valid compositions from profile or default."""
    profile = _get_profile()
    if profile and profile.rotation.compositions:
        return set(profile.rotation.compositions)
    return _DEFAULT_COMPOSITIONS


def get_style_distribution() -> dict:
    """Get style distribution by act from profile or default."""
    profile = _get_profile()
    if profile and profile.rotation.scene_expander_style_distribution:
        return profile.rotation.scene_expander_style_distribution
    return _DEFAULT_STYLE_DISTRIBUTION


def get_default_style() -> str:
    """Get the default/fallback visual style name from profile or 'dossier'."""
    profile = _get_profile()
    if profile and profile.style_system.substyles:
        # Return the highest-weight substyle as default
        return max(
            profile.style_system.substyles,
            key=lambda k: profile.style_system.substyles[k].weight,
        )
    return "dossier"


def _pick_composition(visual_style: str, index: int, recent_compositions: list[str]) -> str:
    """Pick a composition using affinity mapping with anti-repetition.

    If the profile has a composition_affinity for the given visual_style,
    prefer those compositions. Fall back to full rotation if preferred
    options would violate the anti-repetition constraint (3+ consecutive).
    """
    all_compositions = list(get_valid_compositions())
    profile = _get_profile()
    affinity = None
    if profile and profile.raw.get("composition_affinity"):
        affinity = profile.raw["composition_affinity"].get(visual_style)

    # Count trailing repetitions
    max_consecutive = 3

    def _would_repeat(comp: str) -> bool:
        if len(recent_compositions) < max_consecutive - 1:
            return False
        return all(c == comp for c in recent_compositions[-(max_consecutive - 1):])

    if affinity:
        # Try preferred compositions in order
        for comp in affinity:
            if not _would_repeat(comp):
                return comp
        # All preferred would repeat — try remaining compositions
        remaining = [c for c in all_compositions if c not in affinity]
        for comp in remaining:
            if not _would_repeat(comp):
                return comp

    # No affinity or all options exhausted — modulo rotation
    comp = all_compositions[index % len(all_compositions)]
    if _would_repeat(comp):
        # Shift to next option
        for offset in range(1, len(all_compositions)):
            alt = all_compositions[(index + offset) % len(all_compositions)]
            if not _would_repeat(alt):
                return alt
    return comp


# Legacy names — callers should use getters above
VALID_COMPOSITIONS = _DEFAULT_COMPOSITIONS
STYLE_DISTRIBUTION = _DEFAULT_STYLE_DISTRIBUTION

# Concept count range by words in scene text
MIN_CONCEPTS = 6
MAX_CONCEPTS = 12
MIN_WORDS_PER_CONCEPT = 10   # ~4s at 2.5 wps — prevents flash images
MAX_WORDS_PER_CONCEPT = 25   # ~10s at 2.5 wps — keeps pacing engaging


def _estimate_concept_count(scene_text: str) -> int:
    """Decide how many concepts a scene should have based on word count.

    Ensures every concept stays within MAX_WORDS_PER_CONCEPT words.
    """
    word_count = len(scene_text.split())
    # Need at least ceil(word_count / MAX_WORDS_PER_CONCEPT) concepts
    min_needed = max(MIN_CONCEPTS, -(-word_count // MAX_WORDS_PER_CONCEPT))
    ideal = max(min_needed, min(MAX_CONCEPTS, round(word_count / 15)))
    return ideal


def _build_style_weights_text(act_number: int) -> str:
    """Build human-readable style weight text for the prompt."""
    style_dist = get_style_distribution()
    dist = style_dist.get(act_number, style_dist.get(1, {}))
    if not dist:
        return "- Single style (no substyle distribution)"
    lines = []
    for style_name, pct in dist.items():
        lines.append(f"- {style_name.title()}: {pct}%")
    if act_number in (1, 2, 6) and dist.get("echo", 0) == 0:
        lines.append("- Echo is NOT allowed in this act")
    return "\n".join(lines)


def _build_prompt(
    scene_number: int,
    scene_text: str,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    concept_count: int,
    total_scenes: int,
) -> str:
    """Build the concept expansion prompt for one scene."""
    template = PROMPT_TEMPLATE_PATH.read_text()
    return template.format(
        SCENE_NUMBER=scene_number,
        SCENE_TEXT=scene_text,
        VISUAL_SEEDS=visual_seeds or "(none provided)",
        ACCENT_COLOR=accent_color.replace("_", " "),
        ACT_NUMBER=act_number,
        CONCEPT_COUNT=concept_count,
        STYLE_WEIGHTS=_build_style_weights_text(act_number),
        TOTAL_SCENES=total_scenes,
    )


def _parse_response(response_text: str) -> dict:
    """Extract JSON from the LLM response."""
    # Try markdown code block first
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    # Try raw JSON
    brace_start = response_text.find("{")
    brace_end = response_text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        return json.loads(response_text[brace_start : brace_end + 1])

    raise ValueError("No JSON found in response")


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


async def _expand_with_scene_blocks(
    anthropic_client,
    scene_number: int,
    scene_text: str,
    story_bible: dict,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
) -> list[dict]:
    """Expand scene using V2 scene_blocks format.

    Scene blocks pre-define image groupings with shared location/lighting.
    This function matches the scene's narration text to images via their
    narration_excerpt field (fuzzy matching), then returns concepts with
    block context already populated.

    Args:
        anthropic_client: AnthropicClient instance (may be used for edge cases)
        scene_number: Scene number from Script table
        scene_text: Exact narration text from Script table
        story_bible: Story Bible dict with scene_blocks
        visual_seeds: Visual seeds for context
        accent_color: Accent color for video
        act_number: Which act this scene belongs to

    Returns:
        List of concept dicts with block context (block_id, block_location, etc.)
    """
    from bots.story_bible import get_all_images_from_blocks

    # Get all images with their block context
    all_images = get_all_images_from_blocks(story_bible)

    if not all_images:
        print(f"      ⚠️ Scene {scene_number}: No images in scene_blocks, falling back")
        return [{
            "concept_index": 1,
            "sentence_text": scene_text,
            "visual_description": "Scene continues",
            "visual_style": get_default_style(),
            "composition": "medium",
            "mood": "neutral",
        }]

    # Match scene_text to images via narration_excerpt overlap
    # The Story Bible's image narration_excerpts should collectively cover the full script
    matched_images = _match_scene_to_images(scene_text, all_images)

    if not matched_images:
        # No matches found - this scene may not have images assigned
        print(f"      ⚠️ Scene {scene_number}: No image matches found for narration")
        return [{
            "concept_index": 1,
            "sentence_text": scene_text,
            "visual_description": "Scene continues",
            "visual_style": get_default_style(),
            "composition": "medium",
            "mood": "neutral",
        }]

    print(f"    Scene {scene_number}: {len(matched_images)} images matched from scene_blocks "
          f"(blocks: {', '.join(set(img['block_id'] for img in matched_images))})")

    # Convert matched images to concept dicts
    concepts = []
    for i, img in enumerate(matched_images):
        # Map camera to composition
        camera = img.get("camera", "medium").lower()
        composition_map = {
            "wide": "wide",
            "medium": "medium",
            "closeup": "closeup",
            "close-up": "closeup",
            "extreme_closeup": "closeup",
            "extreme-closeup": "closeup",
        }
        composition = composition_map.get(camera, "medium")

        # Get the actual narration content (primary visual driver)
        narration_content = img.get("narration_excerpt", "").strip()

        # Get camera/composition direction from Story Bible action field
        # This is NOT story content - it's cinematography guidance
        camera_direction = img.get("action", "").strip()

        concept = {
            "concept_index": i + 1,
            "sentence_text": narration_content,
            # visual_description is now the actual narration content
            # that should drive what appears in the image
            "visual_description": narration_content if narration_content else "Scene continues",
            "visual_style": get_default_style(),
            "composition": composition,
            "mood": img.get("block_mood", "neutral"),
            # Block context for prompt builder
            "block_id": img.get("block_id"),
            "block_location": img.get("block_location", ""),
            "block_lighting": img.get("block_lighting", ""),
            "block_characters": img.get("block_characters", []),
            "block_location_id": img.get("block_location_id", ""),
            "global_image_index": img.get("image_index"),
            # Camera direction is separate from content - used for composition guidance
            "camera_direction": camera_direction,
        }
        concepts.append(concept)

    return concepts


def _match_scene_to_images(scene_text: str, all_images: list[dict]) -> list[dict]:
    """Match a scene's narration text to images via narration_excerpt overlap.

    Uses exact substring matching as primary strategy, with fuzzy matching as
    fallback. Images are matched in ORDER OF APPEARANCE in the scene_text,
    ensuring the first matching image corresponds to the earliest part of the
    narration.

    Key insight: The image's narration_excerpt should be an exact substring of
    the scene_text if the Story Bible was generated correctly. Fuzzy matching
    is only used when small variations exist (whitespace, punctuation).

    Args:
        scene_text: The scene's full narration text
        all_images: All images from scene_blocks with their context (pre-sorted by image_index)

    Returns:
        List of images whose narration_excerpt matches this scene, in the order
        they appear in the scene_text (not by global image_index)
    """
    # Normalize scene text for matching
    scene_text_normalized = " ".join(scene_text.split()).strip()
    scene_text_lower = scene_text_normalized.lower()

    # Track match position in scene_text for ordering
    matched_with_position: list[tuple[int, dict]] = []

    for img in all_images:
        excerpt = img.get("narration_excerpt", "").strip()
        if not excerpt:
            continue

        excerpt_normalized = " ".join(excerpt.split())
        excerpt_lower = excerpt_normalized.lower()

        # Strategy 1: Exact substring match (preferred)
        pos = scene_text_lower.find(excerpt_lower)
        if pos != -1:
            matched_with_position.append((pos, img))
            continue

        # Strategy 2: Case-insensitive match with normalization
        # Handle minor whitespace/punctuation differences
        excerpt_words = excerpt_lower.split()
        if len(excerpt_words) >= 3:
            # Check if first 3 and last 3 words appear in sequence
            first_three = " ".join(excerpt_words[:3])
            last_three = " ".join(excerpt_words[-3:])
            first_pos = scene_text_lower.find(first_three)
            last_pos = scene_text_lower.find(last_three)

            if first_pos != -1 and last_pos != -1 and last_pos > first_pos:
                # Words appear in order - this is a valid match
                matched_with_position.append((first_pos, img))
                continue

        # Strategy 3: High confidence fuzzy match (fallback for edge cases)
        # Only accept if >80% of excerpt words appear consecutively in scene
        excerpt_words_set = set(excerpt_words)
        scene_words = scene_text_lower.split()

        # Find best consecutive match window
        best_overlap = 0
        best_pos = -1
        window_size = len(excerpt_words)

        for i in range(max(1, len(scene_words) - window_size + 1)):
            window = set(scene_words[i:i + window_size])
            overlap = len(excerpt_words_set & window) / max(len(excerpt_words_set), 1)
            if overlap > best_overlap:
                best_overlap = overlap
                best_pos = i

        if best_overlap >= 0.8 and best_pos >= 0:
            # Calculate character position for ordering
            char_pos = len(" ".join(scene_words[:best_pos]))
            matched_with_position.append((char_pos, img))

    # Sort by position in scene_text to maintain narration order
    matched_with_position.sort(key=lambda x: x[0])

    # Return images in scene order (not global image_index order)
    return [img for _pos, img in matched_with_position]


async def expand_scene_concepts_deterministic(
    anthropic_client,
    scene_number: int,
    scene_text: str,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    total_scenes: int = 14,
    voice_duration: Optional[float] = None,
    story_bible: Optional[dict] = None,
) -> list[dict]:
    """Expand one scene's narration into visual concepts using deterministic word-duration-aware splitting.

    Supports two Story Bible formats:
    - V1 (visual_arc): Uses deterministic splitter + LLM for visual descriptions
    - V2 (scene_blocks): Uses pre-defined blocks with shared location/lighting

    For V2 scene_blocks, each image has block context (location, lighting, characters)
    already defined. The scene_number maps to images via narration text overlap.

    Args:
        anthropic_client: AnthropicClient instance with generate() method
        scene_number: Scene number from the Script table
        scene_text: Exact narration text from the Script table
        visual_seeds: Visual seed concepts from research brief
        accent_color: Accent color for this video (e.g. "cold_teal")
        act_number: Which act this scene belongs to (1-6)
        total_scenes: Total number of scenes in the video
        voice_duration: Optional actual voice duration in seconds (for accurate WPS)
        story_bible: Optional Story Bible dict with characters, locations, visual_arc OR scene_blocks

    Returns:
        List of concept dicts, each with:
        - concept_index (int, 1-based)
        - sentence_text (str, exact substring of scene_text)
        - visual_description (str, 20-35 word filmable description)
        - visual_style (str, profile substyle name - DESCRIPTIVE, not prescriptive)
        - composition (str, wide/medium/closeup/etc.)
        - mood (str)
        - For V2 scene_blocks, also includes:
          - block_id, block_location, block_lighting, block_characters
    """
    import sys
    from pathlib import Path

    # Import Story Bible helpers
    try:
        from bots.story_bible import (
            format_bible_for_prompt,
            has_scene_blocks,
            get_all_images_from_blocks,
        )
    except ImportError:
        def format_bible_for_prompt(bible, scene): return ""
        def has_scene_blocks(bible): return False
        def get_all_images_from_blocks(bible): return []

    # Check if Story Bible uses V2 scene_blocks format
    if story_bible and has_scene_blocks(story_bible):
        return await _expand_with_scene_blocks(
            anthropic_client=anthropic_client,
            scene_number=scene_number,
            scene_text=scene_text,
            story_bible=story_bible,
            visual_seeds=visual_seeds,
            accent_color=accent_color,
            act_number=act_number,
        )

    # V1 path: Use deterministic splitter + LLM visual descriptions
    # Import deterministic splitter
    sys.path.insert(0, str(Path(__file__).parent.parent / "clients"))
    from deterministic_splitter import segment_scene_deterministic

    # Step 1: Use deterministic splitter to get text segments with guaranteed durations
    segments = segment_scene_deterministic(scene_text, voice_duration)

    if not segments:
        # Empty scene - return minimal concept
        return [{
            "concept_index": 1,
            "sentence_text": scene_text,
            "visual_description": "Empty scene",
            "visual_style": get_default_style(),
            "composition": _pick_composition(get_default_style(), 0, []),
            "mood": "neutral",
        }]

    # Step 2: Get profile for styling decisions
    profile = _get_profile()
    is_holographic = profile is None or profile.profile_id == "holographic_hud"

    # For non-holographic profiles, we still assign styles for tracking/analytics
    # but they are DESCRIPTIVE (post-hoc classification), not PRESCRIPTIVE
    default_fallback_style = get_default_style()
    recent_comps: list[str] = []

    # Step 3: Format Story Bible context for this scene
    bible_context = ""
    scene_arcs = []  # List of ALL arc entries for this scene
    if story_bible:
        bible_context = format_bible_for_prompt(story_bible, scene_number)
        # Get ALL visual arc entries for this scene (Claude generates multiple per scene)
        try:
            from bots.story_bible import get_scene_arcs
            scene_arcs = get_scene_arcs(story_bible, scene_number)
        except ImportError:
            scene_arcs = []
        # Debug: Show Story Bible state
        total_arc_count = len(story_bible.get("visual_arc", []))
        print(f"      📖 Story Bible: {total_arc_count} total arcs, {len(scene_arcs)} for scene {scene_number}")
        if scene_arcs:
            cameras = [a.get("camera_distance", "?") for a in scene_arcs]
            print(f"      📐 Scene {scene_number} arc cameras: {cameras}")
    else:
        print(f"      ⚠️ No Story Bible passed to scene expander")
    # Map arc camera distance to composition (Airtable Shot Type values)
    arc_composition_map = {
        # Wide shots
        "wide": "wide",
        "extreme-wide": "wide",
        "extreme wide": "wide",
        "establishing": "wide",
        # Medium shots
        "medium": "medium",
        "mid": "medium",
        # Close-up shots
        "close-up": "closeup",
        "close up": "closeup",
        "closeup": "closeup",
        "close": "closeup",
        "extreme-close-up": "closeup",
        "extreme close-up": "closeup",
        "extreme closeup": "closeup",
        # Other compositions
        "overhead": "overhead",
        "low-angle": "low_angle",
        "low angle": "low_angle",
        "portrait": "portrait",
    }

    # Step 4: Generate visual_description for each segment using LLM
    concepts = []

    for i, seg in enumerate(segments):
        # Get the arc entry for THIS concept (cycle through if more concepts than arcs)
        if scene_arcs:
            arc_index = i % len(scene_arcs)
            concept_arc = scene_arcs[arc_index]
            arc_camera = concept_arc.get("camera_distance", "").lower().strip()
        else:
            concept_arc = {}
            arc_camera = ""

        # Use visual arc camera distance if available, otherwise fall back to rotation
        if arc_camera and arc_camera in arc_composition_map:
            composition = arc_composition_map[arc_camera]
            print(f"        Concept {i+1}: arc[{arc_index}] camera='{arc_camera}' → {composition}")
        else:
            composition = _pick_composition(default_fallback_style, i, recent_comps)
            if arc_camera:
                print(f"        Concept {i+1}: ⚠️ Unknown camera '{arc_camera}', fallback={composition}")
            elif not scene_arcs:
                pass  # No arcs at all, silently use rotation
        recent_comps.append(composition)

        # Generate visual description via LLM — NO SCENE TYPE CONSTRAINTS
        try:
            if not is_holographic and profile and profile.scene_description.system_prompt:
                # Build prompt with Story Bible context but NO scene type constraints
                # Claude decides what to write based on narration content
                visual_desc_prompt = (
                    f"{profile.scene_description.system_prompt}\n\n"
                )

                # Add Story Bible context if available
                if bible_context:
                    visual_desc_prompt += f"{bible_context}\n\n"

                # Add specific arc data for THIS concept
                if concept_arc:
                    arc_location = concept_arc.get("location_id", "")
                    arc_chars = concept_arc.get("characters_present", [])
                    arc_mood = concept_arc.get("mood", "")
                    arc_color = concept_arc.get("color_temperature", "")
                    arc_note = concept_arc.get("visual_note", "")
                    visual_desc_prompt += (
                        f"## THIS SHOT'S ARC:\n"
                        f"- Location: {arc_location}\n"
                        f"- Characters: {', '.join(arc_chars) if arc_chars else 'none (environment/data shot)'}\n"
                        f"- Mood: {arc_mood}\n"
                        f"- Color temperature: {arc_color}\n"
                        f"- Camera: {arc_camera}\n"
                        f"- What changes: {arc_note}\n\n"
                    )

                visual_desc_prompt += (
                    "VISUAL APPROACH — Before writing this prompt, identify the PRIMARY VERB in the narration:\n"
                    "- If the verb is an action (launched, struck, surged, collapsed, invaded, signed, declared) → show that action happening in the physical world\n"
                    "- If the verb is internal (realized, calculated, planned, knew) → THEN show a character in a contemplative setting\n"
                    "- If the verb describes data (cost, earned, spent, numbered) → show the physical manifestation of that data (infrastructure, currency, military hardware) OR a data display\n\n"
                    "Ask yourself: \"What would a documentary filmmaker POINT THE CAMERA AT for this line?\" The answer is almost never \"a person sitting at a desk.\" It's the event itself.\n\n"
                    "Examples of good visual verb matching:\n"
                    "- \"launched strikes\" → jets over desert, explosions on bunker complex\n"
                    "- \"oil prices surged\" → oil tankers at sea, pump jacks working, gas station price display changing\n"
                    "- \"signed a treaty\" → two figures at table with document and pens, flags behind them\n"
                    "- \"declared Russia the only winner\" → press conference podium, or newsroom with broadcast on screens\n"
                    "- \"sanctions were working\" → empty factory floor, closed shipping port, currency notes scattered\n"
                    "- \"enriched uranium\" → centrifuge arrays in underground facility, hazmat suited figures\n"
                    "- \"Patriot missiles fired\" → missile defense battery launching at night, streak of light across sky\n"
                    "- \"protests killed thousands\" → empty street with scattered debris, memorial candles, abandoned shoes\n"
                    "- \"oil revenues collapsed\" → rusting idle oil equipment, snow-covered abandoned derricks\n\n"
                    "Examples of BAD visual choices (avoid these):\n"
                    "- \"launched strikes\" → figure at desk reading about strikes ❌\n"
                    "- \"oil prices surged\" → chart on a holographic screen ❌ (save data displays for specific numbers)\n"
                    "- \"declared Russia the winner\" → figure in office watching TV ❌\n"
                    "- \"sanctions were working\" → figure reviewing documents at desk ❌\n\n"
                    "CRITICAL RULES:\n"
                    "1. If a character from the bible appears, use their EXACT costume description. Do not change or omit clothing.\n"
                    "2. If a location from the bible appears, use its EXACT description and signature detail.\n"
                    "3. Match the mood, color temperature, and camera distance from THIS SHOT'S ARC above.\n"
                    "4. If characters_present is 'none', do NOT include character figures — this is a data/environment shot.\n"
                    "5. Include the 'what changes' note — what makes this image DIFFERENT from the previous one.\n\n"
                )

                # Add clothing requirement for characters
                visual_desc_prompt += (
                    "CLOTHING RULE: Every character figure MUST have specific clothing described. "
                    "Never describe a character without clothing. If unsure, use 'wearing dark formal suit with white shirt.'\n\n"
                    "Write a 20-35 word visual description for this narration segment. "
                    "You decide whether this moment needs characters, environment, data, or objects — "
                    "write whatever best tells THIS story moment.\n\n"
                    "Do NOT start with the style prefix (e.g. 'Cinematic animated illustration...') — "
                    "that will be added automatically based on what you write.\n"
                    "End with a camera angle and lighting description that matches the arc.\n"
                    "Return ONLY the description, nothing else.\n\n"
                    f"Narration: \"{seg['text']}\"\n"
                    f"Visual seeds for context: {visual_seeds[:200] if visual_seeds else 'none'}"
                )
            else:
                # Holographic default prompt (unchanged)
                visual_desc_prompt = (
                    "You are creating visual descriptions for HOLOGRAPHIC DATA DISPLAYS "
                    "in an intelligence operations center — not camera shots of real events.\n\n"
                    "NEVER describe:\n"
                    "- People (no politicians, officials, reporters, soldiers, analysts, or any human figures)\n"
                    "- Physical rooms or buildings as if a camera is there\n"
                    "- Events as if photographing them\n\n"
                    "ALWAYS describe:\n"
                    "- What DATA, DOCUMENTS, MAPS, or CHARTS would appear on a holographic screen analyzing this topic\n"
                    "- Information visualizations (price charts, treaty text, flow diagrams, network maps, timelines)\n"
                    "- At least one specific number, date, or percentage from the narration\n"
                    "- Data elements must come from THIS segment's text only, not from the broader script context\n\n"
                    "EXAMPLES:\n"
                    "BAD: 'Kremlin hall, Putin and Pezeshkian at long table with treaty document'\n"
                    "GOOD: 'Holographic treaty document floating in space, 47 articles visible with Section 12: Military Cooperation highlighted'\n\n"
                    "BAD: 'White House briefing room, reporters holding phones'\n"
                    "GOOD: 'Bloomberg terminal display showing headline with oil price ticker dropping from $120 to $68'\n\n"
                    "The subject is ALWAYS information/data being displayed, never the physical event itself.\n\n"
                    "Write a 20-35 word description of what DATA DISPLAY would visualize this narration. "
                    "Return ONLY the description, nothing else.\n\n"
                    f"Narration: \"{seg['text']}\"\n"
                    f"Visual seeds for context: {visual_seeds[:200] if visual_seeds else 'none'}"
                )

            visual_description = await anthropic_client.generate(
                prompt=visual_desc_prompt,
                model="claude-sonnet-4-5-20250929",
                max_tokens=200,
                temperature=0.4,
            )
            visual_description = visual_description.strip()

        except Exception as e:
            print(f"      ⚠️ LLM visual description failed for segment {i+1}: {e}")
            # Fallback: use the narration text as placeholder
            visual_description = seg['text']

        # Scene type is now DESCRIPTIVE — assigned based on what Claude wrote
        # (detected by prompt_builder.py when assembling final prompt)
        concepts.append({
            "concept_index": i + 1,
            "sentence_text": seg['text'],
            "visual_description": visual_description,
            "visual_style": default_fallback_style,  # Default; actual type detected later
            "composition": composition,
            "mood": "tension",  # Default mood, could be enhanced later
        })

    print(f"    Scene {scene_number}: {len(concepts)} concepts from deterministic splitter "
          f"(max duration: {max(s['duration'] for s in segments):.1f}s)")

    return concepts


async def expand_scene_concepts(
    anthropic_client,
    scene_number: int,
    scene_text: str,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    total_scenes: int = 14,
) -> list[dict]:
    """Expand one scene's narration into 6-10 visual concepts.

    This is the core function of the new pipeline. It takes a single scene's
    text directly from the Script table and produces concepts ready to be
    written to the Airtable Images table.

    Uses 5 LLM attempts with progressively relaxed validation. A slightly
    imperfect LLM result (longer image durations, small gaps auto-absorbed)
    is always better than a mechanical fallback with generic templates.

    Args:
        anthropic_client: AnthropicClient instance with generate() method
        scene_number: Scene number from the Script table
        scene_text: Exact narration text from the Script table
        visual_seeds: Visual seed concepts from research brief
        accent_color: Accent color for this video (e.g. "cold_teal")
        act_number: Which act this scene belongs to (1-6)
        total_scenes: Total number of scenes in the video

    Returns:
        List of concept dicts, each with:
        - concept_index (int, 1-based)
        - sentence_text (str, exact substring of scene_text)
        - visual_description (str, 20-35 word filmable description)
        - visual_style (str, profile substyle name)
        - composition (str, wide/medium/closeup/etc.)
        - mood (str)
    """
    import asyncio

    concept_count = _estimate_concept_count(scene_text)

    prompt = _build_prompt(
        scene_number=scene_number,
        scene_text=scene_text,
        visual_seeds=visual_seeds,
        accent_color=accent_color,
        act_number=act_number,
        concept_count=concept_count,
        total_scenes=total_scenes,
    )

    max_attempts = 5
    last_error = ""
    # Track the best LLM result across all attempts so we can use it
    # even if it didn't pass strict validation.
    best_concepts: list[dict] | None = None
    best_error: str = ""

    for attempt in range(1, max_attempts + 1):
        # Use relaxed validation on attempts 4+ — auto-fix minor issues
        # instead of rejecting. A longer-duration image is better than
        # a wrong image.
        use_relaxed = attempt >= 4

        extra = ""
        if attempt == 2:
            extra = (
                "\n\nIMPORTANT: Your previous response had this issue: "
                f"{last_error}\n"
                "Fix this. The sentence_text fields must be EXACT substrings of "
                "the narration — copy-paste them character for character. "
                "Return ONLY valid JSON."
            )
        elif attempt == 3:
            extra = (
                "\n\nCRITICAL: Previous issue: "
                f"{last_error}\n"
                "You MUST copy sentence_text EXACTLY from the narration. "
                "Do not edit, rephrase, or fix anything. Character-for-character copy. "
                "Return ONLY a JSON object, no markdown fences."
            )
        elif attempt == 4:
            extra = (
                "\n\nPrevious issue: "
                f"{last_error}\n"
                "SIMPLIFY: Use FEWER, LONGER concepts if needed. "
                "It is better to have 4-5 longer concepts than to fail. "
                "Each concept can cover up to 40 words. "
                "Copy sentence_text EXACTLY from the narration."
            )
        elif attempt == 5:
            extra = (
                "\n\nFINAL ATTEMPT. Previous issue: "
                f"{last_error}\n"
                "Use as FEW concepts as needed (minimum 3). "
                "Each concept can be long — up to 50 words. "
                "Split at the most obvious sentence boundaries (periods). "
                "Copy sentence_text EXACTLY. Return ONLY JSON."
            )

        try:
            response = await anthropic_client.generate(
                prompt=prompt + extra,
                model="claude-sonnet-4-5-20250929",
                max_tokens=6000,
                temperature=max(0.3, 0.7 - 0.1 * attempt),
            )

            parsed = _parse_response(response)
            concepts = parsed.get("concepts", [])

            # Number the concepts
            for i, c in enumerate(concepts):
                c["concept_index"] = i + 1

            is_valid, error = _validate_concepts(
                concepts, scene_text, concept_count, relaxed=use_relaxed,
            )

            if is_valid:
                concepts = _validate_concept_durations(concepts)
                return concepts

            # Track the best result — prefer the one with more valid concepts
            if concepts and (best_concepts is None or len(concepts) > len(best_concepts)):
                # Deep copy so subsequent relaxed validation doesn't mutate
                best_concepts = [dict(c) for c in concepts]
                best_error = error

            last_error = error
            print(f"    Scene {scene_number} attempt {attempt}/{max_attempts}: {error}")

        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"JSON parse failed: {exc}"
            print(f"    Scene {scene_number} attempt {attempt}/{max_attempts}: {last_error}")
        except Exception as exc:
            last_error = f"LLM error: {exc}"
            print(f"    Scene {scene_number} attempt {attempt}/{max_attempts}: {last_error}")

        if attempt < max_attempts:
            await asyncio.sleep(2)

    # All 5 attempts failed strict+relaxed validation.
    # Use the best LLM result we got — but ONLY after repairing all
    # sentence_text fields to be verbatim substrings of the source.
    if best_concepts:
        print(
            f"    Scene {scene_number}: using best LLM result "
            f"({len(best_concepts)} concepts, issue: {best_error})"
        )
        # Repair all concepts to guarantee verbatim sentence_text
        best_concepts = _repair_all_concepts(best_concepts, scene_text)

        # Force-fix: ensure every concept has required fields
        valid_styles = get_valid_styles()
        fallback_style = get_default_style()
        repair_comps: list[str] = []
        for i, c in enumerate(best_concepts):
            c["concept_index"] = i + 1
            if not c.get("visual_style") or c["visual_style"] not in valid_styles:
                c["visual_style"] = fallback_style
            if not c.get("composition") or c["composition"] not in get_valid_compositions():
                c["composition"] = _pick_composition(c["visual_style"], i, repair_comps)
            repair_comps.append(c["composition"])
            if not c.get("visual_description"):
                c["visual_description"] = c.get("sentence_text", "")
                c["needs_new_prompt"] = True
            if not c.get("mood"):
                c["mood"] = "tension"
        return _validate_concept_durations(best_concepts)

    # Absolute last resort: no LLM response at all (network errors on all
    # 5 attempts). Split at sentence boundaries with the sentence text as
    # the visual description placeholder — downstream prompt generation
    # will create proper descriptions. Never use static keyword templates.
    print(
        f"    Scene {scene_number}: no LLM response after {max_attempts} "
        f"attempts, creating sentence-boundary concepts"
    )
    return _sentence_boundary_split(scene_text)
