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
                    # Skip this concept — the others may still be valid
                    continue
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
        if style not in VALID_STYLES:
            concept["visual_style"] = "dossier"

        comp = concept.get("composition", "")
        if comp not in VALID_COMPOSITIONS:
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

    compositions = [
        "wide", "medium", "closeup", "environmental",
        "portrait", "overhead", "low_angle",
    ]
    concepts = []
    for i, chunk in enumerate(chunks):
        concepts.append({
            "concept_index": i + 1,
            "sentence_text": chunk,
            "visual_description": chunk,  # Use narration as placeholder
            "visual_style": "dossier",
            "composition": compositions[i % len(compositions)],
            "mood": "tension",
            "needs_new_prompt": True,
        })

    return _validate_concept_durations(concepts)


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
    # Use the best LLM result we got — it's always better than a
    # mechanical fallback with generic keyword templates.
    if best_concepts:
        print(
            f"    Scene {scene_number}: using best LLM result "
            f"({len(best_concepts)} concepts, issue: {best_error})"
        )
        # Force-fix: ensure every concept has required fields
        compositions = [
            "wide", "medium", "closeup", "environmental",
            "portrait", "overhead", "low_angle",
        ]
        for i, c in enumerate(best_concepts):
            c["concept_index"] = i + 1
            if not c.get("visual_style") or c["visual_style"] not in VALID_STYLES:
                c["visual_style"] = "dossier"
            if not c.get("composition") or c["composition"] not in VALID_COMPOSITIONS:
                c["composition"] = compositions[i % len(compositions)]
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
