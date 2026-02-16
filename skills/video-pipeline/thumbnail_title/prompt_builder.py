"""Thumbnail prompt builder for Economy FastForward.

Takes title generation output (caps_word, line_1, line_2) and video metadata,
then uses Claude to fill template variables and produce the final Nano Banana Pro
prompt from one of the three templates.
"""

import json
from typing import Optional

from thumbnail_title.templates import TEMPLATES, TEMPLATE_A_CFH_SPLIT, TEMPLATE_B_MINDPLICIT_BANNER, TEMPLATE_C_POWER_DYNAMIC
from thumbnail_title.selector import select_template


# System prompt for Claude to fill template variables
VARIABLE_FILL_SYSTEM_PROMPT = """\
You are the visual director for Economy FastForward thumbnail illustrations.

Your job: Fill in the template variables to produce a compelling thumbnail that pairs
with the given title. The thumbnail should show the HUMAN COST visually while the
title explains the system or cause verbally.

STYLE RULES:
- Editorial comic illustration, bold graphic novel style
- Dark navy background (#0A0F1A) with dramatic amber/golden lighting
- Bold black outlines, high color saturation
- 16:9 landscape, 1280x720
- Maximum 3 colors: dark background, bright accent, white text
- Face must be readable at 160x90 (YouTube search size)

TEXT RULES (already in template, but guide your choices):
- line_1 and line_2 are PROVIDED — use them exactly as given
- red_word is PROVIDED — use it exactly as given
- All text ALL CAPS, bold condensed sans-serif, heavy black outline

EMOTION GUIDE:
- Match the emotion to the caps_word:
  TRAP/CRISIS/COLLAPSE → panicked, shocked
  DEATH/DYING → worried, fearful
  WEAPON/SWALLOWED → angry, frustrated
  LIES/MISTAKE → frustrated, betrayed
  STRONGER/RICHER/WEAKER → determined, defiant

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
            template_key: One of 'template_a', 'template_b', 'template_c'.
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

        return prompt

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
                "nationality": "Country/region context (e.g., American, European, Chinese)",
                "worker_type": "Character archetype (e.g., blue-collar worker, businessman, citizen)",
                "emotion": "Primary facial emotion (e.g., panicked, shocked, frustrated, angry)",
                "cultural_signifier": "Instant recognition prop (e.g., hard hat, Uncle Sam hat, business suit)",
                "mouth_expression": "Reinforces emotion (e.g., open in shock, gritted in anger)",
                "secondary_element": "Right-side visual that contrasts with figure (e.g., sleek robot in golden glow, crumbling bank building)",
            }
        elif template_key == "template_b":
            return {
                "power_scene": "Central dramatic scene (e.g., worker looking up at massive robot shadow, figure at chess board)",
                "ground_detail": "Floor-level context detail (e.g., scattered tools and fallen hard hat, cracked floor tiles)",
            }
        elif template_key == "template_c":
            return {
                "victim_type": "Displaced figure (e.g., panicked blue-collar worker, shocked small business owner)",
                "emotion": "Victim's emotion (e.g., shock, panic, fear, anger)",
                "cultural_signifier": "Flying prop (e.g., hard hat, briefcase, apron, glasses)",
                "power_figure": "Controller figure (e.g., calm man in dark suit sitting in leather chair with fingers steepled)",
                "instrument": "Tool of power (e.g., golden glowing robot, stack of contracts, money printer)",
                "relationship": "Arrow label suggesting dynamics (e.g., REPLACEMENT, EXTRACTION, CONTROL)",
            }
        return {}
