"""Scene Expansion (Step 3).

Expands a narration script into ~20-30 production scenes nested within
the 6-act structure. Each scene is a narrative segment with narration
text, duration, visual metadata, and composition directives.

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

        new_desc = await anthropic_client.generate(
            prompt=prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=200,
            temperature=0.8,
        )
        new_desc = new_desc.strip().strip('"').strip()

        scene["description"] = new_desc
        scene["scene_description"] = new_desc

    return scenes


async def expand_scenes(
    anthropic_client,
    script: str,
    visual_seeds: str,
    accent_color: str = "cold_teal",
    total_scenes: int = DEFAULT_TOTAL_SCENES,
) -> list[dict]:
    """Expand a script into a nested scene list.

    Args:
        anthropic_client: AnthropicClient instance
        script: Full narration script with act markers
        visual_seeds: Visual seed concepts from the research brief
        accent_color: Accent color for this video
        total_scenes: Target number of scenes (20-30)

    Returns:
        List of scene dicts (flattened from nested structure) with:
        scene_number, parent_act, act_marker, narration_text,
        duration_seconds, visual_style, composition, ken_burns, mood,
        description, and backward-compat aliases.
    """
    prompt = build_scene_expand_prompt(script, visual_seeds, accent_color, total_scenes)

    response = await anthropic_client.generate(
        prompt=prompt,
        model="claude-sonnet-4-5-20250929",
        max_tokens=16000,
        temperature=0.6,
    )

    try:
        structure = parse_scene_response(response)
        scenes = flatten_scenes(structure)
    except (json.JSONDecodeError, ValueError):
        # If full generation truncated or failed to parse, try split approach
        scenes = await _expand_scenes_split(
            anthropic_client, script, visual_seeds, accent_color, total_scenes
        )

    # Post-generation diversity check: flag and regenerate duplicate scenes
    if scenes:
        flagged = check_scene_diversity(scenes)
        if flagged:
            print(f"  ⚠️ {len(flagged)} consecutive duplicate scenes detected — regenerating")
            scenes = await regenerate_duplicate_scenes(
                anthropic_client, scenes, flagged,
            )
            # Second pass: check if any duplicates remain after regeneration
            still_flagged = check_scene_diversity(scenes)
            if still_flagged:
                print(f"  ⚠️ {len(still_flagged)} duplicates remain after regeneration (logged)")

    return scenes


async def _expand_scenes_split(
    anthropic_client,
    script: str,
    visual_seeds: str,
    accent_color: str,
    total_scenes: int,
) -> list[dict]:
    """Split scene expansion into two calls (Acts 1-3, Acts 4-6) to avoid truncation."""
    from .script_generator import extract_acts

    acts = extract_acts(script)
    half = total_scenes // 2
    all_scenes = []

    # Acts 1-3
    first_half_script = "\n\n".join(
        f"[ACT {n}]\n{text}" for n, text in acts.items() if n <= 3
    )
    first_prompt = build_scene_expand_prompt(
        first_half_script, visual_seeds, accent_color, half
    )
    first_prompt += (
        f"\n\nIMPORTANT: Generate scenes only for Acts 1-3. "
        f"Start at scene_number 1. Generate approximately {half} scenes."
    )

    first_response = await anthropic_client.generate(
        prompt=first_prompt,
        model="claude-sonnet-4-5-20250929",
        max_tokens=10000,
        temperature=0.6,
    )

    try:
        first_structure = parse_scene_response(first_response)
        first_scenes = flatten_scenes(first_structure)
    except (json.JSONDecodeError, ValueError):
        first_scenes = []

    all_scenes.extend(first_scenes)

    # Acts 4-6
    second_half_script = "\n\n".join(
        f"[ACT {n}]\n{text}" for n, text in acts.items() if n > 3
    )
    remaining = total_scenes - len(first_scenes)
    second_prompt = build_scene_expand_prompt(
        second_half_script, visual_seeds, accent_color, remaining
    )
    second_prompt += (
        f"\n\nIMPORTANT: Generate scenes only for Acts 4-6. "
        f"Start at scene_number {len(first_scenes) + 1}. "
        f"Generate approximately {remaining} scenes."
    )

    second_response = await anthropic_client.generate(
        prompt=second_prompt,
        model="claude-sonnet-4-5-20250929",
        max_tokens=10000,
        temperature=0.6,
    )

    try:
        second_structure = parse_scene_response(second_response)
        second_scenes = flatten_scenes(second_structure)
    except (json.JSONDecodeError, ValueError):
        second_scenes = []

    # Re-number second batch to continue from first.
    # Use the max scene_number (not count) in case the LLM produced
    # non-contiguous numbers or gaps in the first batch.
    last_scene_num = max(
        (s.get("scene_number", 0) for s in first_scenes), default=0
    )
    for i, scene in enumerate(second_scenes):
        scene["scene_number"] = last_scene_num + i + 1

    all_scenes.extend(second_scenes)
    return all_scenes


# Backward compatibility aliases
DEFAULT_TOTAL_IMAGES = DEFAULT_TOTAL_SCENES
