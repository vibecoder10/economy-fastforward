"""Scene Expansion (Step 3).

Expands a narration script into ~20-30 production scenes nested within
the 6-act structure. Each scene is a narrative segment with narration
text, duration, visual metadata, and composition directives.

Scene *structure* (narration boundaries, style, composition, ken_burns,
mood) is generated in batches of ~8-10 scenes.  Scene *descriptions*
are then generated one at a time in a sequential pass: each call
receives the narration text for that scene plus the previous 3
descriptions as "DO NOT REPEAT" context, making duplicate descriptions
structurally impossible.

Downstream, the image prompt engine generates multiple images per scene
based on scene duration (~1 image per 8-11 seconds of narration).
"""

import json
import re
from pathlib import Path
from typing import Optional

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "scene_expand.txt"

# Target scene count for unified 6-act → beat sheet structure
DEFAULT_TOTAL_SCENES = 25  # Dynamic: 20-30 total, 3-5 per act

# Batch size: how many scenes to generate per LLM call
BATCH_SIZE = 8

# Available accent colors
ACCENT_COLORS = ["cold_teal", "warm_amber", "muted_crimson"]

# Valid styles
VALID_STYLES = {"dossier", "schema", "echo"}

# Valid composition hints
VALID_COMPOSITIONS = {
    "wide", "medium", "closeup", "environmental",
    "portrait", "overhead", "low_angle",
}

# Valid ken burns directions
VALID_KEN_BURNS = {
    "slow zoom in", "slow zoom out", "slow pan left",
    "slow pan right", "slow drift up", "slow drift down",
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


def load_scene_expand_prompt() -> str:
    """Load the scene expansion prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text()


def build_scene_expand_prompt(
    script: str,
    visual_seeds: str,
    accent_color: str,
    total_scenes: int = DEFAULT_TOTAL_SCENES,
) -> str:
    """Build the scene expansion prompt."""
    template = load_scene_expand_prompt()
    return template.format(
        SCRIPT=script,
        VISUAL_SEEDS=visual_seeds,
        ACCENT_COLOR=accent_color,
        TOTAL_SCENES=total_scenes,
    )


def parse_scene_response(response_text: str) -> dict:
    """Parse the nested act/scene JSON from Claude's response.

    Returns the full structure: {"total_acts": 6, "total_scenes": N, "acts": [...]}
    """
    # Try to extract from markdown code block
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if json_match:
        raw_json = json_match.group(1)
    else:
        # Try to find a raw JSON object
        brace_start = response_text.find("{")
        brace_end = response_text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            raw_json = response_text[brace_start : brace_end + 1]
        else:
            raise ValueError("Could not find JSON object in scene expansion response")

    return json.loads(raw_json)


def flatten_scenes(scene_structure: dict) -> list[dict]:
    """Flatten the nested act/scene structure into a flat scene list.

    This is needed for backward compatibility with downstream systems
    that expect a flat list of scenes.

    Also provides compatibility fields:
    - 'act' (alias for 'parent_act')
    - 'style' (alias for 'visual_style')
    - 'script_excerpt' (alias for 'narration_text')
    - 'composition_hint' (alias for 'composition')
    - 'scene_description' (alias for 'description')
    """
    flat = []
    for act in scene_structure.get("acts", []):
        for scene in act.get("scenes", []):
            # Add backward-compatibility fields
            compat = dict(scene)
            compat["act"] = scene.get("parent_act", act.get("act_number"))
            compat["style"] = scene.get("visual_style", "dossier")
            compat["script_excerpt"] = scene.get("narration_text", "")
            compat["composition_hint"] = scene.get("composition", "medium")
            compat["scene_description"] = scene.get("description", "")
            flat.append(compat)
    return flat


def check_scene_diversity(scenes: list[dict]) -> list[int]:
    """Find consecutive scenes with overly similar descriptions.

    Compares the first 8 content words (lowercased) of each pair of
    consecutive scene descriptions.  If more than 60 % of those words
    overlap the scene is flagged for regeneration.

    Returns:
        List of scene *indices* (into *scenes*) that need new descriptions.
    """
    flagged: list[int] = []
    for i in range(1, len(scenes)):
        prev_desc = scenes[i - 1].get("description", scenes[i - 1].get("scene_description", "")).lower().split()[:8]
        curr_desc = scenes[i].get("description", scenes[i].get("scene_description", "")).lower().split()[:8]

        if len(prev_desc) >= 6 and len(curr_desc) >= 6:
            overlap = len(set(prev_desc) & set(curr_desc))
            overlap_ratio = overlap / max(len(set(prev_desc)), 1)
            if overlap_ratio > 0.6:
                flagged.append(i)

    return flagged


async def regenerate_duplicate_scenes(
    anthropic_client,
    scenes: list[dict],
    flagged_indices: list[int],
) -> list[dict]:
    """Re-generate descriptions for scenes flagged as duplicates.

    For each flagged index, asks the LLM for a visually distinct
    replacement that differs from both the previous and next scene.
    """
    for idx in flagged_indices:
        scene = scenes[idx]
        prev_scene = scenes[idx - 1]
        next_scene = scenes[idx + 1] if idx + 1 < len(scenes) else None

        narration = scene.get("narration_text", scene.get("script_excerpt", ""))
        prev_desc = prev_scene.get("description", prev_scene.get("scene_description", ""))
        next_desc = next_scene.get("description", next_scene.get("scene_description", "")) if next_scene else None

        prompt = (
            "Generate a NEW scene description for this narration line.\n\n"
            f"The narration text: \"{narration}\"\n"
            f"Act: {scene.get('act', scene.get('parent_act', ''))}\n"
            f"Style: {scene.get('style', scene.get('visual_style', 'dossier'))}\n"
            f"Composition: {scene.get('composition_hint', scene.get('composition', 'medium'))}\n\n"
            f"The PREVIOUS scene already shows: \"{prev_desc}\"\n"
        )
        if next_desc:
            prompt += f"The NEXT scene shows: \"{next_desc}\"\n"

        prompt += (
            "\nYour description MUST be visually COMPLETELY DIFFERENT from the "
            "previous and next scenes. Different setting, different subject, "
            "different objects. 20-35 words. Describe only CONTENT — no style "
            "or lighting language.\n\n"
            "Return ONLY the scene description, nothing else."
        )

        try:
            new_desc = await anthropic_client.generate(
                prompt=prompt,
                model="claude-sonnet-4-5-20250929",
                max_tokens=200,
                temperature=0.8,
            )
            if not new_desc:
                new_desc = _fallback_description(narration)
            else:
                new_desc = new_desc.strip().strip('"').strip()
        except Exception as exc:
            print(f"    ⚠️ Regeneration failed ({exc}), using fallback")
            new_desc = _fallback_description(narration)

        scene["description"] = new_desc
        scene["scene_description"] = new_desc

    return scenes


def _fallback_description(narration: str) -> str:
    """Build a simple fallback description from narration text.

    Extracts key nouns/phrases and constructs a generic but concrete
    scene description.  Used when the LLM call fails entirely.
    """
    # Strip common filler words to get content-bearing tokens
    filler = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "and",
        "but", "or", "nor", "not", "so", "yet", "both", "either",
        "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "than", "too", "very",
        "just", "about", "above", "also", "that", "this", "these",
        "those", "it", "its", "they", "them", "their", "we", "our",
        "you", "your", "he", "she", "his", "her", "i", "me", "my",
    }
    words = [w for w in narration.split() if w.lower().strip(".,;:!?\"'") not in filler]
    key_phrase = " ".join(words[:12])
    return f"A scene depicting {key_phrase}"


async def _generate_description_for_scene(
    anthropic_client,
    scene: dict,
    previous_descriptions: list[str],
) -> str:
    """Generate a single scene description with context from recent scenes.

    Args:
        anthropic_client: AnthropicClient instance
        scene: Scene dict with narration_text, act/parent_act, style/visual_style,
               composition/composition_hint fields already populated.
        previous_descriptions: Up to 3 most recent scene descriptions (newest last).

    Returns:
        A 20-35 word scene description string.
    """
    narration = scene.get("narration_text", scene.get("script_excerpt", ""))
    act_number = scene.get("act", scene.get("parent_act", ""))
    style = scene.get("style", scene.get("visual_style", "dossier"))
    composition = scene.get("composition_hint", scene.get("composition", "medium"))

    prompt = (
        f"Given this narration line: '{narration}'\n"
        f"Act: {act_number} | Style: {style} | Composition: {composition}\n"
    )

    if previous_descriptions:
        prompt += "\nThe viewer has JUST seen these images (DO NOT repeat any of these):\n"
        labels = ["Previous", "Before that", "Before that"]
        for i, desc in enumerate(reversed(previous_descriptions)):
            prompt += f"- {labels[min(i, len(labels) - 1)]}: {desc}\n"

    prompt += (
        "\nWrite ONE scene description, 20-35 words. "
        "Describe a specific, concrete, filmable scene. "
        "Only describe CONTENT — no lighting, camera, or style language. "
        "Must be visually different from all previous descriptions above.\n\n"
        "Return ONLY the scene description, nothing else."
    )

    import asyncio

    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = await anthropic_client.generate(
                prompt=prompt,
                model="claude-sonnet-4-5-20250929",
                max_tokens=200,
                temperature=0.7,
            )
            if not response:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                return _fallback_description(narration)

            result = response.strip().strip('"').strip()
            if result:
                return result

            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
        except Exception as exc:
            print(f"    ⚠️ LLM call failed ({exc}), attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue

    return _fallback_description(narration)


async def _generate_all_descriptions(
    anthropic_client,
    scenes: list[dict],
) -> list[dict]:
    """Generate descriptions for all scenes sequentially, one at a time.

    Each scene receives the previous 3 descriptions as "DO NOT REPEAT"
    context, making duplicate descriptions structurally impossible.

    Includes a 0.4s delay between calls to avoid rate limiting across
    ~170 sequential requests.

    Overwrites the ``description`` and ``scene_description`` fields
    on each scene dict in-place and returns the modified list.
    """
    import asyncio

    descriptions: list[str] = []

    for i, scene in enumerate(scenes):
        # Provide up to 3 most recent descriptions as context
        recent = descriptions[-3:] if descriptions else []

        new_desc = await _generate_description_for_scene(
            anthropic_client, scene, recent,
        )

        scene["description"] = new_desc
        scene["scene_description"] = new_desc
        descriptions.append(new_desc)

        if (i + 1) % 10 == 0 or i + 1 == len(scenes):
            print(f"  Descriptions: {i + 1}/{len(scenes)} scenes")

        # Small delay between calls to avoid rate limiting
        if i < len(scenes) - 1:
            await asyncio.sleep(0.4)

    return scenes


def _plan_batches(acts: dict[int, str], total_scenes: int) -> list[dict]:
    """Group acts into batches targeting ~BATCH_SIZE scenes each.

    Allocates scenes to acts proportionally by word count (clamped 3-5
    per act when there are multiple acts).  When only a single act is
    present (fallback case where the entire script was treated as one
    act), the full ``total_scenes`` target is used instead of the 3-5
    clamp, split across multiple batches of ~BATCH_SIZE.

    A trailing batch with fewer than 4 scenes is merged into the
    previous batch to avoid tiny final calls.

    Returns:
        List of batch dicts, each with:
        - acts: list of {"act_number", "text", "target_scenes"}
        - target_scenes: total scene target for the batch
    """
    act_nums = sorted(acts.keys())
    act_words = {n: len(acts[n].split()) for n in act_nums}
    total_words = sum(act_words.values()) or 1

    targets: dict[int, int] = {}

    if len(act_nums) == 1:
        # Single act (fallback): assign all target scenes to it.
        # Do NOT clamp to 3-5 — the caller expects total_scenes output.
        targets[act_nums[0]] = total_scenes
    else:
        # Multiple acts: proportional allocation clamped to 3-5 per act
        for n in act_nums:
            proportion = act_words[n] / total_words
            targets[n] = max(3, min(5, round(proportion * total_scenes)))

        # Adjust to hit total_scenes exactly (may need multiple passes)
        diff = total_scenes - sum(targets.values())
        while diff != 0:
            adjusted = False
            for n in sorted(act_nums, key=lambda x: act_words[x], reverse=True):
                if diff == 0:
                    break
                if diff > 0 and targets[n] < 5:
                    targets[n] += 1
                    diff -= 1
                    adjusted = True
                elif diff < 0 and targets[n] > 3:
                    targets[n] -= 1
                    diff += 1
                    adjusted = True
            if not adjusted:
                break  # Can't reach exact total within 3-5 clamp

    # Group acts into batches
    batches: list[dict] = []
    current: dict = {"acts": [], "target_scenes": 0}
    for n in act_nums:
        current["acts"].append({
            "act_number": n,
            "text": acts[n],
            "target_scenes": targets[n],
        })
        current["target_scenes"] += targets[n]
        if current["target_scenes"] >= BATCH_SIZE:
            batches.append(current)
            current = {"acts": [], "target_scenes": 0}

    if current["acts"]:
        # Merge small trailing batch into previous to avoid tiny calls
        if batches and current["target_scenes"] < 4:
            batches[-1]["acts"].extend(current["acts"])
            batches[-1]["target_scenes"] += current["target_scenes"]
        else:
            batches.append(current)

    return batches


async def _expand_batch(
    anthropic_client,
    batch: dict,
    visual_seeds: str,
    accent_color: str,
    start_scene_num: int,
    recent_descriptions: list[str],
    recent_compositions: list[str],
    last_ken_burns: Optional[str],
) -> list[dict]:
    """Expand a single batch of acts into scenes via one LLM call.

    Uses the full scene_expand.txt template for quality rules, then
    appends batch-specific instructions: starting scene number,
    ALREADY SHOWN context, style distribution for these acts, and
    composition/ken_burns continuity state.
    """
    # Build the batch script text (only the acts in this batch)
    batch_script = "\n\n".join(
        f"[ACT {a['act_number']}]\n{a['text']}" for a in batch["acts"]
    )
    act_nums = [a["act_number"] for a in batch["acts"]]
    target = batch["target_scenes"]

    # Build prompt using the main template for quality rules
    prompt = build_scene_expand_prompt(
        batch_script, visual_seeds, accent_color, target
    )

    # Append batch-specific instructions that override template defaults
    batch_ctx = f"\n\n--- BATCH INSTRUCTIONS (override any conflicting rules above) ---\n"
    batch_ctx += f"Generate scenes ONLY for Act(s) {', '.join(str(n) for n in act_nums)}.\n"
    batch_ctx += f"Start scene_number at {start_scene_num}.\n"
    batch_ctx += f"Generate exactly {target} scenes.\n"

    if recent_descriptions:
        batch_ctx += "\n--- ALREADY SHOWN (previous batch) ---\n"
        batch_ctx += (
            "The viewer has ALREADY seen these images in the previous scenes. "
            "Your scenes MUST be visually DIFFERENT from all of them:\n"
        )
        for i, desc in enumerate(recent_descriptions):
            batch_ctx += f"  {i + 1}. \"{desc}\"\n"
        batch_ctx += (
            "Do NOT repeat similar settings, subjects, or compositions. "
            "Your first scene must show something the viewer has NOT just seen.\n"
        )

    if recent_compositions:
        batch_ctx += (
            f"\nRecent compositions used: {', '.join(recent_compositions)}. "
            f"Start this batch with a different composition.\n"
        )

    if last_ken_burns:
        batch_ctx += (
            f"\nThe previous scene used ken_burns: \"{last_ken_burns}\". "
            f"Your first scene MUST use a DIFFERENT ken_burns direction.\n"
        )

    # Style distribution for the specific acts in this batch
    batch_ctx += "\nStyle distribution targets for this batch:\n"
    for a in batch["acts"]:
        n = a["act_number"]
        dist = STYLE_DISTRIBUTION.get(n, {"dossier": 60, "schema": 20, "echo": 20})
        batch_ctx += (
            f"- Act {n}: {dist['dossier']}% Dossier, "
            f"{dist['schema']}% Schema, {dist['echo']}% Echo\n"
        )

    # First and last scene rules for boundary batches
    if start_scene_num == 1:
        batch_ctx += "\nThe FIRST scene of the video must be dossier style.\n"
    if act_nums[-1] == 6:
        batch_ctx += "\nThe LAST scene of the video must be dossier style.\n"

    prompt += batch_ctx

    response = await anthropic_client.generate(
        prompt=prompt,
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        temperature=0.6,
    )

    try:
        structure = parse_scene_response(response)
        scenes = flatten_scenes(structure)
    except (json.JSONDecodeError, ValueError):
        # Single retry on parse failure
        response = await anthropic_client.generate(
            prompt=prompt + "\n\nPrevious attempt failed to parse. Return ONLY valid JSON.",
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            temperature=0.5,
        )
        try:
            structure = parse_scene_response(response)
            scenes = flatten_scenes(structure)
        except (json.JSONDecodeError, ValueError):
            scenes = []

    return scenes


async def expand_scenes(
    anthropic_client,
    script: str,
    visual_seeds: str,
    accent_color: str = "cold_teal",
    total_scenes: int = DEFAULT_TOTAL_SCENES,
) -> list[dict]:
    """Expand a script into scenes using batched structure + per-scene descriptions.

    Phase 1 — Structure (batched):
        Splits the script into batches of ~8-10 scenes each.  Each batch
        generates scene *structure*: narration boundaries, style,
        composition, ken_burns, mood.  Batch descriptions are discarded.

    Phase 2 — Descriptions (sequential, one scene at a time):
        Iterates through every scene and generates ONE description per
        LLM call.  Each call receives the narration text for that scene
        plus the previous 3 descriptions as "DO NOT REPEAT" context.
        This makes duplicate descriptions structurally impossible.

    Args:
        anthropic_client: AnthropicClient instance
        script: Full narration script with act markers
        visual_seeds: Visual seed concepts from the research brief
        accent_color: Accent color for this video
        total_scenes: Target number of scenes (20-30)

    Returns:
        List of scene dicts (flattened) with scene_number, parent_act,
        act_marker, narration_text, duration_seconds, visual_style,
        composition, ken_burns, mood, description, and backward-compat
        aliases.
    """
    from .script_generator import extract_acts

    acts = extract_acts(script)
    print(f"  [expand_scenes] extract_acts found {len(acts)} acts: {sorted(acts.keys()) if acts else '(none)'}")
    print(f"  [expand_scenes] script length: {len(script)} chars, {len(script.split())} words")
    if not acts:
        # Fallback: treat entire script as a single act
        print(f"  [expand_scenes] ⚠️ No act markers found — treating entire script as 1 act")
        acts = {1: script}

    # --- Phase 1: Batch structure generation ---
    batches = _plan_batches(acts, total_scenes)
    all_scenes: list[dict] = []

    for batch_idx, batch in enumerate(batches):
        # Build context from previous batch (for composition/ken_burns continuity)
        recent_descriptions = [
            s.get("description", s.get("scene_description", ""))
            for s in all_scenes[-3:]
        ]
        recent_compositions = [
            s.get("composition", s.get("composition_hint", ""))
            for s in all_scenes[-3:]
        ]
        last_ken_burns = all_scenes[-1].get("ken_burns") if all_scenes else None

        start_scene_num = max(
            (s.get("scene_number", 0) for s in all_scenes), default=0
        ) + 1

        act_nums = [a["act_number"] for a in batch["acts"]]
        act_label = ", ".join(str(n) for n in act_nums)

        batch_scenes = await _expand_batch(
            anthropic_client=anthropic_client,
            batch=batch,
            visual_seeds=visual_seeds,
            accent_color=accent_color,
            start_scene_num=start_scene_num,
            recent_descriptions=recent_descriptions,
            recent_compositions=recent_compositions,
            last_ken_burns=last_ken_burns,
        )

        # Re-number to ensure continuity across batches
        for i, scene in enumerate(batch_scenes):
            scene["scene_number"] = start_scene_num + i

        all_scenes.extend(batch_scenes)
        print(
            f"  Batch {batch_idx + 1}/{len(batches)}: "
            f"{len(batch_scenes)} scenes (Acts {act_label})"
        )

    # --- Phase 2: Sequential per-scene description generation ---
    if all_scenes:
        print(f"  Generating descriptions one-at-a-time for {len(all_scenes)} scenes...")
        all_scenes = await _generate_all_descriptions(
            anthropic_client, all_scenes,
        )

    return all_scenes


# Backward compatibility aliases
DEFAULT_TOTAL_IMAGES = DEFAULT_TOTAL_SCENES
