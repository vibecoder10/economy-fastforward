"""Thumbnail prompt builder for Economy FastForward.

Takes title generation output (caps_word, line_1, line_2) and video metadata,
then uses Claude to fill template variables and produce the final Nano Banana Pro
prompt from one of the two cinematic photorealistic templates.

Optionally injects a Machiavellian visual element (~50% of thumbnails) for
thematic consistency across the channel brand.
"""

import json
import random
from typing import Optional

from thumbnail_title.templates import TEMPLATES
from thumbnail_title.selector import select_template


# ---------------------------------------------------------------------------
# Machiavellian visual elements — injected ~50% of the time
# Updated for cinematic photorealistic style.
# ---------------------------------------------------------------------------
MACHIAVELLIAN_ELEMENTS = [
    "puppet strings descending from darkness above",
    "chess pieces scattered on a polished dark floor",
    "a crown lying discarded in shadow",
    "a dagger embedded in a world map",
    "a cracked golden scale of justice half-hidden in darkness",
    "a single red chess king toppled on black marble",
]


# System prompt for Claude to fill template variables
VARIABLE_FILL_SYSTEM_PROMPT = """\
You are the visual director for Economy FastForward cinematic thumbnails.

Your job: Fill in the template variables to produce a compelling thumbnail that pairs
with the given title. The thumbnail should evoke CINEMATIC TENSION — like a movie poster
frame that makes viewers feel they're about to witness something powerful.

STYLE RULES:
- Cinematic photorealistic, shot on Arri Alexa look
- Deep crushed blacks, single dramatic light source, film grain
- Shallow depth of field, desaturated palette with ONE vivid accent color
- 16:9 landscape, 1280x720
- Maximum 3 colors: dark background, bright accent, white text
- Must be readable at 120x68 (YouTube mobile thumbnail size)

ACCENT COLOR GUIDE (match to topic):
- Teal (#00BFA5) for tech, AI, innovation
- Amber/Gold (#FFB800) for power, money, authority
- Red (#E63946) for military, conflict, crisis
- Green (#22C55E) for economics, growth, markets

TEXT RULES (already in template, but guide your choices):
- line_1 and line_2 are PROVIDED — use them exactly as given
- red_word is PROVIDED — use it exactly as given
- All text ALL CAPS, bold condensed sans-serif, heavy black outline

OUTPUT FORMAT (JSON only, no markdown):
Return a JSON object with ALL required variable names as keys.
"""


class ThumbnailPromptBuilder:
    """Builds thumbnail generation prompts from templates + AI-filled variables.

    Uses Claude to intelligently fill template variables based on video content,
    then formats the final prompt for Nano Banana Pro image generation.
    """

    def __init__(self, anthropic_client):
        """Initialize with an existing AnthropicClient instance.

        Args:
            anthropic_client: An initialized AnthropicClient from the pipeline.
        """
        self.anthropic = anthropic_client

    async def build(
        self,
        template_key: str,
        title_data: dict,
        video_title: str,
        video_summary: str,
    ) -> str:
        """Build a complete thumbnail prompt.

        Args:
            template_key: One of 'template_a', 'template_b'.
            title_data: Output from TitleGenerator.generate() containing
                caps_word, line_1, line_2.
            video_title: The video's working title.
            video_summary: Brief video description.

        Returns:
            Complete prompt string ready for Nano Banana Pro.
        """
        template_info = TEMPLATES[template_key]
        variables_needed = template_info["variables"]

        # Pre-fill the text variables from title_data
        prefilled = {
            "line_1": title_data["line_1"],
            "line_2": title_data["line_2"],
            "red_word": title_data["caps_word"],
        }

        # Determine which variables still need to be filled by Claude
        remaining = [v for v in variables_needed if v not in prefilled]

        if remaining:
            filled = await self._fill_variables(
                template_key=template_key,
                template_name=template_info["name"],
                variables=remaining,
                video_title=video_title,
                video_summary=video_summary,
                title_data=title_data,
            )
            prefilled.update(filled)

        # Format the template with all variables
        template_str = template_info["prompt"]
        try:
            prompt = template_str.format(**prefilled)
        except KeyError as e:
            raise ValueError(
                f"Template '{template_key}' missing variable {e}. "
                f"Filled: {list(prefilled.keys())}, "
                f"Required: {variables_needed}"
            )

        # Inject a Machiavellian visual element ~50% of the time
        prompt = self._maybe_inject_machiavellian_element(prompt)

        return prompt

    @staticmethod
    def _maybe_inject_machiavellian_element(prompt: str) -> str:
        """Inject a Machiavellian visual element with ~50% probability.

        Inserts a thematic detail sentence before the final style description
        line (the last paragraph) to reinforce the channel's power-dynamics brand.
        """
        if random.random() > 0.5:
            return prompt

        element = random.choice(MACHIAVELLIAN_ELEMENTS)
        # Insert before the last paragraph (the style footer)
        last_break = prompt.rfind("\n\n")
        if last_break == -1:
            return prompt
        return (
            prompt[:last_break]
            + f",\n\n{element.capitalize()},\n"
            + prompt[last_break:]
        )

    async def _fill_variables(
        self,
        template_key: str,
        template_name: str,
        variables: list[str],
        video_title: str,
        video_summary: str,
        title_data: dict,
    ) -> dict:
        """Use Claude to fill remaining template variables.

        Args:
            template_key: Template identifier.
            template_name: Human-readable template name.
            variables: List of variable names to fill.
            video_title: Video title for context.
            video_summary: Video summary for context.
            title_data: Title generation data for context.

        Returns:
            Dict mapping variable name -> value.
        """
        # Build variable descriptions based on template
        var_descriptions = self._get_variable_descriptions(template_key)

        var_guidance = "\n".join([
            f'  "{v}": {var_descriptions.get(v, "Fill based on context")}'
            for v in variables
        ])

        user_prompt = (
            f"Fill the thumbnail template variables for this video:\n\n"
            f'VIDEO TITLE: "{video_title}"\n'
            f'VIDEO SUMMARY: {video_summary}\n'
            f'YOUTUBE TITLE: "{title_data["title"]}"\n'
            f'CAPS WORD: {title_data["caps_word"]}\n'
            f'THUMBNAIL TEXT LINE 1: {title_data["line_1"]}\n'
            f'THUMBNAIL TEXT LINE 2: {title_data["line_2"]}\n\n'
            f'TEMPLATE: {template_name} ({template_key})\n\n'
            f'Fill these variables (return JSON object with these exact keys):\n'
            f'{var_guidance}\n\n'
            f'Return JSON only.'
        )

        response = await self.anthropic.generate(
            prompt=user_prompt,
            system_prompt=VARIABLE_FILL_SYSTEM_PROMPT,
            model="claude-sonnet-4-5-20250929",
            max_tokens=800,
        )

        clean = response.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)

        # Validate all requested variables are present
        missing = [v for v in variables if v not in result]
        if missing:
            raise ValueError(
                f"Claude did not fill all variables. Missing: {missing}"
            )

        return result

    @staticmethod
    def _get_variable_descriptions(template_key: str) -> dict:
        """Return human-readable descriptions for each template's variables."""
        if template_key == "template_a":
            return {
                "scene_description": (
                    "A dramatic cinematic environment that tells the story visually. "
                    "Must feel like a movie poster frame — epic scale, single focal "
                    "point, storytelling through setting. Examples: 'military command "
                    "bunker with glowing screens and a single empty chair under a "
                    "spotlight', 'massive oil tanker in dark ocean with a single red "
                    "warning light', 'Wall Street trading floor frozen mid-crash with "
                    "papers suspended in air'"
                ),
                "accent_color": (
                    "The single vivid accent color matching the topic. Use: teal for "
                    "tech/AI, amber/gold for power/money, red for military/conflict, "
                    "green for economics. Return just the color name (e.g., 'amber')."
                ),
            }
        elif template_key == "template_b":
            return {
                "close_up_subject": (
                    "An extreme close-up of an object or detail that represents the "
                    "person or power figure. NOT a face — use symbolic objects instead. "
                    "Examples: 'a weathered hand gripping a nuclear launch key', "
                    "'a cracked military medal on a dark wooden desk', 'classified "
                    "documents stamped TOP SECRET under harsh desk lamp light'"
                ),
                "emotion_detail": (
                    "Textural detail that conveys emotion through the close-up subject. "
                    "Examples: 'sweat visible, tension in every detail', 'dust and "
                    "scratches showing age and use', 'the weight of consequence visible "
                    "in every texture'"
                ),
                "background_element": (
                    "A subtle element visible in the bokeh background that adds context. "
                    "Examples: 'a blurred war room map', 'out-of-focus city skyline at "
                    "night', 'soft glow of multiple monitor screens'"
                ),
                "accent_color": (
                    "The single vivid accent color matching the topic. Use: teal for "
                    "tech/AI, amber/gold for power/money, red for military/conflict, "
                    "green for economics. Return just the color name (e.g., 'red')."
                ),
            }
        return {}
