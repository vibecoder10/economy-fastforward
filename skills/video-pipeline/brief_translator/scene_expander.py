"""Scene Expansion (Step 3).

Expands a narration script and visual seeds into ~140 individual scene
descriptions with act assignments and style tags, ready for the image
prompt engine.
"""

import json
import re
from pathlib import Path
from typing import Optional

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "scene_expand.txt"

# Default scene count for a 25-minute video at ~11 seconds per image
DEFAULT_TOTAL_IMAGES = 136

# Available accent colors
ACCENT_COLORS = ["cold_teal", "warm_amber", "muted_crimson"]

# Valid styles
VALID_STYLES = {"dossier", "schema", "echo"}

# Valid composition hints
VALID_COMPOSITIONS = {
    "wide", "medium", "closeup", "environmental",
    "portrait", "overhead", "low_angle",
}


def load_scene_expand_prompt() -> str:
    """Load the scene expansion prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text()


def build_scene_expand_prompt(
    script: str,
    visual_seeds: str,
    accent_color: str,
    total_images: int = DEFAULT_TOTAL_IMAGES,
) -> str:
    """Build the scene expansion prompt."""
    template = load_scene_expand_prompt()
    return template.format(
        SCRIPT=script,
        VISUAL_SEEDS=visual_seeds,
        ACCENT_COLOR=accent_color,
        TOTAL_IMAGES=total_images,
    )


def parse_scene_list(response_text: str) -> list[dict]:
    """Parse the JSON scene list from Claude's response.

    Handles potential JSON formatting issues and extracts the array.
    """
    # Try to find JSON array in the response
    # First, try to extract from markdown code block
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", response_text, re.DOTALL)
    if json_match:
        raw_json = json_match.group(1)
    else:
        # Try to find a raw JSON array
        bracket_start = response_text.find("[")
        bracket_end = response_text.rfind("]")
        if bracket_start != -1 and bracket_end != -1:
            raw_json = response_text[bracket_start : bracket_end + 1]
        else:
            raise ValueError("Could not find JSON array in scene expansion response")

    return json.loads(raw_json)


async def expand_scenes(
    anthropic_client,
    script: str,
    visual_seeds: str,
    accent_color: str = "cold_teal",
    total_images: int = DEFAULT_TOTAL_IMAGES,
) -> list[dict]:
    """Expand a script into a full scene list.

    Args:
        anthropic_client: AnthropicClient instance
        script: Full narration script with act markers
        visual_seeds: Visual seed concepts from the research brief
        accent_color: Accent color for this video
        total_images: Target number of scenes

    Returns:
        List of scene dicts with scene_number, act, style, description,
        script_excerpt, and composition_hint.
    """
    prompt = build_scene_expand_prompt(script, visual_seeds, accent_color, total_images)

    response = await anthropic_client.generate(
        prompt=prompt,
        model="claude-sonnet-4-5-20250929",
        max_tokens=16000,
        temperature=0.6,
    )

    try:
        scenes = parse_scene_list(response)
    except (json.JSONDecodeError, ValueError):
        # If full generation truncated or failed to parse, try split approach
        scenes = await _expand_scenes_split(
            anthropic_client, script, visual_seeds, accent_color, total_images
        )

    return scenes


async def _expand_scenes_split(
    anthropic_client,
    script: str,
    visual_seeds: str,
    accent_color: str,
    total_images: int,
) -> list[dict]:
    """Split scene expansion into two calls (Acts 1-3, Acts 4-6) to avoid truncation."""
    from .script_generator import extract_acts

    acts = extract_acts(script)
    half = total_images // 2
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
    first_scenes = parse_scene_list(first_response)
    all_scenes.extend(first_scenes)

    # Acts 4-6
    second_half_script = "\n\n".join(
        f"[ACT {n}]\n{text}" for n, text in acts.items() if n > 3
    )
    remaining = total_images - len(first_scenes)
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
    second_scenes = parse_scene_list(second_response)

    # Re-number second batch to continue from first
    offset = len(first_scenes)
    for scene in second_scenes:
        scene["scene_number"] = offset + second_scenes.index(scene) + 1

    all_scenes.extend(second_scenes)
    return all_scenes
