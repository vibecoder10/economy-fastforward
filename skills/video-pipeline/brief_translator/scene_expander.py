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
from difflib import SequenceMatcher
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
                "visual_style": "dossier",
                "composition": "wide",
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


async def expand_scene_concepts_deterministic(
    anthropic_client,
    scene_number: int,
    scene_text: str,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    total_scenes: int = 14,
    voice_duration: float | None = None,
) -> list[dict]:
    """Expand one scene's narration into visual concepts using deterministic word-duration-aware splitting.

    Replaces LLM-based text segmentation with a deterministic splitter that:
    - Guarantees hard 10s cap per concept (for animation clip limits)
    - Uses word-based duration calculation (not sentence count)
    - Performs mid-sentence splitting at natural boundaries when needed
    - Merges orphan segments < 4s

    Still uses LLM for generating visual_description per segment, but the text
    splitting is deterministic and duration-guaranteed.

    Args:
        anthropic_client: AnthropicClient instance with generate() method
        scene_number: Scene number from the Script table
        scene_text: Exact narration text from the Script table
        visual_seeds: Visual seed concepts from research brief
        accent_color: Accent color for this video (e.g. "cold_teal")
        act_number: Which act this scene belongs to (1-6)
        total_scenes: Total number of scenes in the video
        voice_duration: Optional actual voice duration in seconds (for accurate WPS)

    Returns:
        List of concept dicts, each with:
        - concept_index (int, 1-based)
        - sentence_text (str, exact substring of scene_text)
        - visual_description (str, 20-35 word filmable description)
        - visual_style (str, dossier/schema/echo)
        - composition (str, wide/medium/closeup/etc.)
        - mood (str)
    """
    import sys
    from pathlib import Path

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
            "visual_style": "dossier",
            "composition": "medium",
            "mood": "neutral",
        }]

    # Step 2: Assign visual styles based on act distribution
    dist = STYLE_DISTRIBUTION.get(act_number, STYLE_DISTRIBUTION[1])
    echo_allowed = dist.get("echo", 0) > 0

    styles_pool = []
    # Build pool based on distribution percentages
    styles_pool.extend(["dossier"] * dist["dossier"])
    styles_pool.extend(["schema"] * dist["schema"])
    if echo_allowed:
        styles_pool.extend(["echo"] * dist["echo"])

    # Assign styles in rotation
    import random
    random.seed(scene_number)  # Deterministic based on scene number
    random.shuffle(styles_pool)

    # Step 3: Assign compositions in rotation
    compositions = ["wide", "medium", "closeup", "environmental", "portrait", "overhead", "low_angle"]

    # Step 4: Generate visual_description for each segment using LLM
    concepts = []

    for i, seg in enumerate(segments):
        style_idx = i % len(styles_pool) if styles_pool else 0
        comp_idx = i % len(compositions)

        visual_style = styles_pool[style_idx] if styles_pool else "dossier"
        composition = compositions[comp_idx]

        # Generate visual description via LLM
        try:
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

        concepts.append({
            "concept_index": i + 1,
            "sentence_text": seg['text'],
            "visual_description": visual_description,
            "visual_style": visual_style,
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
