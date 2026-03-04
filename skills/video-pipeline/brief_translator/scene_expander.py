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
MAX_WORDS_PER_CONCEPT = 35   # ~14s at 2.5 wps — allows natural sentence groupings


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

    # Check trailing text — auto-fix small amounts by appending to last concept
    trailing = normalized_source[search_start:].strip()
    if trailing:
        trailing_wc = len(trailing.split())
        if trailing_wc <= 20:
            # Small trailing text — append to last concept instead of failing
            last = concepts[-1]
            last["sentence_text"] = (last.get("sentence_text", "") + " " + trailing).strip()
        elif trailing_wc > 20:
            return False, f"Uncovered trailing text ({trailing_wc} words): '{trailing[:60]}...'"

    # Validate word count and visual fields
    for i, concept in enumerate(concepts):
        text = concept.get("sentence_text", "")
        wc = len(text.split())
        # Allow up to 40 words — only reject truly oversized concepts.
        # _validate_concept_durations() will split anything over MAX_WORDS
        # (35) after validation passes, so 36-40 words get fixed downstream.
        HARD_REJECT_WORDS = 40
        if wc > HARD_REJECT_WORDS:
            return False, (
                f"Concept {i + 1} has {wc} words (max {HARD_REJECT_WORDS}): "
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
    """Fallback: split scene text into concepts at sentence boundaries.

    Used when the LLM fails to produce valid concepts after all retries.
    Groups sentences into chunks of 12-35 words each, never cutting
    mid-sentence. Returns concepts with keyword-matched visual descriptions
    that downstream prompt generation can still work with.
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

    # Group sentences into chunks that respect word count bounds.
    # Accumulate sentences until adding the next one would exceed MAX.
    # If a single sentence exceeds MAX, it becomes its own chunk (no mid-sentence cuts).
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_wc = 0

    for sentence in sentences:
        swc = len(sentence.split())

        # If adding this sentence would exceed MAX and we already have
        # enough words, flush the current chunk first.
        if current_chunk and current_wc + swc > MAX_WORDS_PER_CONCEPT:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_wc = 0

        current_chunk.append(sentence)
        current_wc += swc

    # Flush remaining
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    # Merge any final chunk that's too short with its predecessor
    if len(chunks) > 1 and len(chunks[-1].split()) < MIN_WORDS_PER_CONCEPT:
        chunks[-2] = chunks[-2] + " " + chunks[-1]
        chunks.pop()

    concepts = []
    compositions = ["wide", "medium", "closeup", "environmental", "portrait", "overhead", "low_angle"]

    for i, chunk in enumerate(chunks):
        # Use full scene text for context — the chunk alone may be too
        # abstract (rhetorical questions, etc.) to match keywords, but
        # the surrounding sentences in the scene often contain concrete
        # topics that tell us what kind of visual to generate.
        desc = _fallback_visual_description(chunk, compositions[i % len(compositions)],
                                            scene_context=scene_text)

        concepts.append({
            "concept_index": i + 1,
            "sentence_text": chunk,
            "visual_description": desc,
            "visual_style": "dossier",
            "composition": compositions[i % len(compositions)],
            "mood": "tension",
        })

    return concepts


# ---------------------------------------------------------------------------
# Fallback visual descriptions — used when LLM expansion fails
# ---------------------------------------------------------------------------
# Maps topic keywords to concrete, filmable visual descriptions.
# Each entry is a list so we can rotate through them.

_KEYWORD_VISUALS: list[tuple[list[str], list[str]]] = [
    (
        ["surveillance", "spy", "monitor", "watching", "tracking", "camera"],
        [
            "A dark surveillance room with a wall of glowing monitors showing camera feeds, a lone figure watching from a swivel chair",
            "Security cameras mounted on a concrete wall, red recording lights blinking in the darkness",
            "An operator seated before a curved bank of screens in a dimly lit intelligence center",
        ],
    ),
    (
        ["data", "algorithm", "ai ", "artificial intelligence", "digital", "cyber", "computer"],
        [
            "Server racks stretching into the distance inside a cold data center, blue LEDs reflecting off the polished floor",
            "A wall of monitors displaying scrolling data streams in a dark control room",
            "Rows of server cabinets behind a glass partition, cables snaking across the floor",
        ],
    ),
    (
        ["negotiat", "diplomat", "treaty", "deal", "agreement", "talk"],
        [
            "Two groups of figures seated across a long polished conference table in a dim government chamber",
            "A closed-door meeting room with heavy curtains drawn, documents spread across the table",
            "Officials in dark suits shaking hands across a mahogany desk, flags standing in the background",
        ],
    ),
    (
        ["military", "weapon", "army", "soldier", "drone", "strike", "missile", "war ", "warfare"],
        [
            "A military command center with tactical maps and glowing screens, officers studying a wall display",
            "A row of military vehicles parked in formation on a vast concrete tarmac at dusk",
            "A dimly lit briefing room with a large projected map, uniformed figures seated around it",
        ],
    ),
    (
        ["money", "dollar", "currency", "debt", "loan", "bank", "financial", "fund"],
        [
            "Stacks of currency bundled on a metal table inside an institutional vault with thick steel doors",
            "A trading floor with hundreds of screens showing financial data, traders in shirtsleeves watching the numbers",
            "A bank vault door standing half-open, revealing rows of safety deposit boxes stretching into shadow",
        ],
    ),
    (
        ["government", "congress", "senate", "parliament", "law", "legislation", "constitution"],
        [
            "An imposing government building entrance with marble columns and wide stone steps at dusk",
            "A legislative chamber with rows of dark wooden desks and a single podium illuminated by overhead light",
            "A long institutional corridor with tall windows casting geometric shadows on the stone floor",
        ],
    ),
    (
        ["trade", "tariff", "export", "import", "shipping", "cargo", "supply chain"],
        [
            "A massive container port at twilight, cranes silhouetted against the sky, cargo ships at anchor",
            "Shipping containers stacked high in a port yard, a lone figure walking between the rows",
            "A freight train loaded with containers stretching into the distance across a flat landscape",
        ],
    ),
    (
        ["power", "control", "dominat", "authorit", "regime", "ruler", "king", "empire"],
        [
            "A lone figure standing at the head of a long empty table in a grand hall, light streaming through tall windows",
            "A throne-like chair at the end of a vast marble room, shadows pooling in the corners",
            "A figure silhouetted in the doorway of an imposing building, looking out over a sprawling city",
        ],
    ),
    (
        ["secret", "classified", "hidden", "covert", "leak", "whistleblow"],
        [
            "A hand sliding a sealed manila envelope across a desk under harsh overhead light",
            "A locked filing cabinet in a dim basement archive, folders marked with redacted labels",
            "A figure reading documents in a pool of desk lamp light, the rest of the room in darkness",
        ],
    ),
    (
        ["market", "stock", "invest", "wall street", "trading", "crash", "bubble"],
        [
            "A trading floor at closing bell, screens glowing red and green in a cavernous room",
            "A massive stock ticker board on the side of a financial district building, pedestrians below",
            "An empty trading desk with multiple monitors left on overnight, charts frozen on screen",
        ],
    ),
    (
        ["oil", "energy", "pipeline", "fuel", "gas", "petrol"],
        [
            "An oil refinery at dusk with towers and pipes silhouetted against an orange sky, steam rising",
            "A pipeline stretching across a barren landscape toward the horizon",
            "An offshore oil platform seen from sea level, waves crashing against the steel legs",
        ],
    ),
    (
        ["china", "beijing", "chinese"],
        [
            "A vast government plaza at dusk with monumental buildings and wide empty avenues",
            "A modern skyline with skyscrapers disappearing into smog, construction cranes visible on the horizon",
        ],
    ),
    (
        ["russia", "moscow", "kremlin", "putin"],
        [
            "An imposing stone government building with a long facade, lit by floodlights at night",
            "A grand hall with ornate ceiling and chandeliers, a long table stretching into the distance",
        ],
    ),
]

# Generic fallback descriptions when no keywords match — rotate through these
_GENERIC_VISUALS = [
    "A dimly lit institutional corridor with tall windows, documents stacked on a desk at the far end",
    "An empty conference room with a long table and a single chair pulled back, overhead light casting a pool of white",
    "A figure in a dark suit walking through a marble lobby, briefcase in hand, footsteps echoing",
    "A large wall map with pins and connecting threads in a dim office, papers scattered below",
    "A rain-slicked city street at night, reflections of building lights stretching across the wet asphalt",
    "An archive room with floor-to-ceiling shelving filled with labeled boxes, a single reading lamp on",
    "A rooftop view of a city skyline at dusk, lights beginning to flicker on across the buildings",
]


def _fallback_visual_description(
    sentence_text: str,
    composition: str,
    scene_context: str = "",
) -> str:
    """Generate a filmable visual description from sentence text using keyword matching.

    First scans the sentence chunk for topic keywords. If no keywords match
    (common with rhetorical questions or abstract narration), falls back to
    scanning the full scene context — neighboring sentences often contain
    concrete topics that indicate what kind of visual to generate.

    Falls back to generic documentary scenes when nothing matches.
    """
    # Try the chunk first, then the full scene context
    for text in [sentence_text, scene_context]:
        if not text:
            continue
        text_lower = text.lower()

        best_score = 0
        best_visuals: list[str] | None = None

        for keywords, visuals in _KEYWORD_VISUALS:
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best_visuals = visuals

        if best_visuals:
            # Use hash of sentence (not context) to pick consistently
            idx = hash(sentence_text) % len(best_visuals)
            return best_visuals[idx]

    # No keyword match anywhere — use generic descriptions
    idx = hash(sentence_text) % len(_GENERIC_VISUALS)
    return _GENERIC_VISUALS[idx]


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
