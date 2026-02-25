"""Scene-by-scene concept expansion.

Takes a single scene's narration text (from the Airtable Script table) and
expands it into 6-10 visual concepts. Each concept pairs an exact substring
of the narration with a filmable visual description.

This replaces the old batch-based system that glued 20 script records into
one big script and re-split them via LLM. The new system processes one
scene at a time — if one fails, only that scene retries.
"""

import json
import re
from pathlib import Path

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "concept_expand.txt"

# Valid styles
VALID_STYLES = {"dossier", "schema", "echo"}

# Valid compositions
VALID_COMPOSITIONS = {
    "wide", "medium", "closeup", "environmental",
    "portrait", "overhead", "low_angle",
}

# Style distribution targets by act number
STYLE_DISTRIBUTION = {
    1: {"dossier": 90, "schema": 10, "echo": 0},
    2: {"dossier": 70, "schema": 30, "echo": 0},
    3: {"dossier": 45, "schema": 20, "echo": 35},
    4: {"dossier": 35, "schema": 20, "echo": 45},
    5: {"dossier": 50, "schema": 35, "echo": 15},
    6: {"dossier": 65, "schema": 35, "echo": 0},
}

# Concept count range by words in scene text
MIN_CONCEPTS = 6
MAX_CONCEPTS = 10
MIN_WORDS_PER_CONCEPT = 12   # ~5s at 2.5 wps — prevents flash images
MAX_WORDS_PER_CONCEPT = 25   # ~10s at 2.5 wps — prevents stall images


def _estimate_concept_count(scene_text: str) -> int:
    """Decide how many concepts a scene should have based on word count.

    Ensures every concept stays within MAX_WORDS_PER_CONCEPT words.
    """
    word_count = len(scene_text.split())
    # Need at least ceil(word_count / MAX_WORDS_PER_CONCEPT) concepts
    min_needed = max(MIN_CONCEPTS, -(-word_count // MAX_WORDS_PER_CONCEPT))
    ideal = max(min_needed, min(MAX_CONCEPTS, round(word_count / 20)))
    return ideal


def _build_style_weights_text(act_number: int) -> str:
    """Build human-readable style weight text for the prompt."""
    dist = STYLE_DISTRIBUTION.get(act_number, STYLE_DISTRIBUTION[1])
    lines = []
    lines.append(f"- Dossier: {dist['dossier']}%")
    lines.append(f"- Schema: {dist['schema']}%")
    lines.append(f"- Echo: {dist['echo']}%")
    if act_number in (1, 2, 6):
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


def _validate_concepts(
    concepts: list[dict],
    scene_text: str,
    expected_count: int,
) -> tuple[bool, str]:
    """Validate that concepts cover the full narration text exactly.

    Returns (is_valid, error_message).
    """
    if not concepts:
        return False, "No concepts returned"

    if len(concepts) < MIN_CONCEPTS:
        return False, f"Only {len(concepts)} concepts (minimum {MIN_CONCEPTS})"

    if len(concepts) > MAX_CONCEPTS + 2:
        return False, f"Too many concepts: {len(concepts)} (maximum {MAX_CONCEPTS})"

    # Normalize whitespace for comparison
    normalized_source = " ".join(scene_text.split())

    # Check that each concept's sentence_text is a substring in order
    search_start = 0
    for i, concept in enumerate(concepts):
        text = concept.get("sentence_text", "")
        if not text:
            return False, f"Concept {i + 1} has empty sentence_text"

        normalized_text = " ".join(text.split())
        pos = normalized_source.find(normalized_text, search_start)
        if pos == -1:
            # Try case-insensitive as a fallback
            pos = normalized_source.lower().find(normalized_text.lower(), search_start)
            if pos == -1:
                return False, (
                    f"Concept {i + 1} sentence_text not found in narration "
                    f"(starting from position {search_start}): "
                    f"'{normalized_text[:60]}...'"
                )

        # Check for gaps — there shouldn't be large unaccounted text
        gap = normalized_source[search_start:pos].strip()
        if gap and len(gap.split()) > 3:
            return False, (
                f"Gap of {len(gap.split())} words between concepts {i} and {i + 1}: "
                f"'{gap[:60]}...'"
            )

        search_start = pos + len(normalized_text)

    # Check trailing text
    trailing = normalized_source[search_start:].strip()
    if trailing and len(trailing.split()) > 3:
        return False, f"Uncovered trailing text ({len(trailing.split())} words): '{trailing[:60]}...'"

    # Validate word count and visual fields
    for i, concept in enumerate(concepts):
        text = concept.get("sentence_text", "")
        wc = len(text.split())
        if wc > MAX_WORDS_PER_CONCEPT:
            return False, (
                f"Concept {i + 1} has {wc} words (max {MAX_WORDS_PER_CONCEPT}): "
                f"'{text[:60]}...'"
            )

        style = concept.get("visual_style", "")
        if style not in VALID_STYLES:
            concept["visual_style"] = "dossier"

        comp = concept.get("composition", "")
        if comp not in VALID_COMPOSITIONS:
            concept["composition"] = "medium"

        if not concept.get("visual_description"):
            return False, f"Concept {i + 1} has no visual_description"

    return True, ""


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
        # Too long — split into two
        elif wc > MAX_WORDS_PER_CONCEPT:
            words = concept["sentence_text"].split()
            mid = len(words) // 2

            part1 = dict(concept)
            part1["sentence_text"] = " ".join(words[:mid])
            part1["needs_new_prompt"] = True

            part2 = dict(concept)
            part2["sentence_text"] = " ".join(words[mid:])
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


def _mechanical_split(scene_text: str, target_count: int) -> list[dict]:
    """Fallback: split scene text mechanically into concepts.

    Used when the LLM fails to produce valid concepts after all retries.
    Returns concepts with generic visual descriptions that downstream
    prompt generation can still work with.  Respects MAX_WORDS_PER_CONCEPT.
    """
    from clients.sentence_utils import split_into_sentences

    sentences = split_into_sentences(scene_text)
    if not sentences:
        sentences = [scene_text]

    # Group sentences into target_count chunks, then re-split any that exceed the word limit
    chunks: list[str] = []
    if len(sentences) <= target_count:
        chunks = list(sentences)
    else:
        base = len(sentences) // target_count
        remainder = len(sentences) % target_count
        idx = 0
        for i in range(target_count):
            count = base + (1 if i < remainder else 0)
            chunks.append(" ".join(sentences[idx:idx + count]))
            idx += count

    # Re-split any chunks that exceed the word limit
    final_chunks: list[str] = []
    for chunk in chunks:
        words = chunk.split()
        if len(words) <= MAX_WORDS_PER_CONCEPT:
            final_chunks.append(chunk)
        else:
            for i in range(0, len(words), MAX_WORDS_PER_CONCEPT):
                final_chunks.append(" ".join(words[i:i + MAX_WORDS_PER_CONCEPT]))
    chunks = final_chunks

    concepts = []
    compositions = ["wide", "medium", "closeup", "environmental", "portrait", "overhead", "low_angle"]

    for i, chunk in enumerate(chunks):
        # Build a simple description from key words
        words = chunk.split()
        key_words = [w for w in words[:15] if len(w) > 3]
        desc = f"Documentary scene depicting {' '.join(key_words[:8])}"

        concepts.append({
            "concept_index": i + 1,
            "sentence_text": chunk,
            "visual_description": desc[:150],
            "visual_style": "dossier",
            "composition": compositions[i % len(compositions)],
            "mood": "tension",
        })

    return concepts


async def expand_scene_concepts(
    anthropic_client,
    scene_number: int,
    scene_text: str,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    total_scenes: int = 20,
) -> list[dict]:
    """Expand one scene's narration into 6-10 visual concepts.

    This is the core function of the new pipeline. It takes a single scene's
    text directly from the Script table and produces concepts ready to be
    written to the Airtable Images table.

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
        - visual_style (str, dossier/schema/echo)
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

    max_attempts = 3
    last_error = ""

    for attempt in range(1, max_attempts + 1):
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
                "\n\nCRITICAL — LAST ATTEMPT. Previous issue: "
                f"{last_error}\n"
                "You MUST copy sentence_text EXACTLY from the narration. "
                "Do not edit, rephrase, or fix anything. Character-for-character copy. "
                "Return ONLY a JSON object, no markdown fences."
            )

        try:
            response = await anthropic_client.generate(
                prompt=prompt + extra,
                model="claude-sonnet-4-5-20250929",
                max_tokens=6000,
                temperature=max(0.3, 0.6 - 0.1 * attempt),
            )

            parsed = _parse_response(response)
            concepts = parsed.get("concepts", [])

            # Number the concepts
            for i, c in enumerate(concepts):
                c["concept_index"] = i + 1

            is_valid, error = _validate_concepts(concepts, scene_text, concept_count)

            if is_valid:
                concepts = _validate_concept_durations(concepts)
                return concepts

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

    # All attempts failed — use mechanical fallback
    print(f"    Scene {scene_number}: LLM failed after {max_attempts} attempts, "
          f"using mechanical split")
    return _mechanical_split(scene_text, concept_count)
