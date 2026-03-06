"""Thumbnail prompt builder for Economy FastForward.

Takes title generation output (line_1, line_2) and video metadata,
then uses Claude to fill template variables and produce the final
Nano Banana Pro prompt from one of the four editorial illustration templates.

Style: BRIGHT editorial illustration — high saturation, bold text,
simple recognizable backgrounds, 3-4 color palettes.

IMPORTANT: This is the THUMBNAIL system. The cinematic photorealistic
style is for SCENE IMAGES ONLY (style_engine.py). Never mix them.
"""

import json
from typing import Optional

from thumbnail_title.templates import (
    TEMPLATES,
    THUMBNAIL_PALETTES,
    detect_palette,
)


# ---------------------------------------------------------------------------
# System prompt for Claude to fill editorial template variables
# ---------------------------------------------------------------------------
VARIABLE_FILL_SYSTEM_PROMPT = """\
You are the visual director for Economy FastForward bright editorial thumbnails.

Your job: Fill in the template variables to produce a HIGH CTR YouTube thumbnail.
The thumbnail must be BRIGHT, BOLD, and INSTANTLY READABLE at phone size (160x90px).

STYLE RULES (MANDATORY — violating any of these kills CTR):
- BRIGHT editorial illustration style. NOT photorealistic. NOT cinematic.
- High saturation, bright lighting, NO shadows, NO atmospheric effects, NO film grain
- Simple, instantly recognizable visuals (maps, symbols, objects)
- Maximum 3-4 dominant colors from the provided palette
- Must tell the story at a glance — one clear visual concept
- 16:9 landscape, 1280x720

ANTI-PATTERNS — NEVER include these words or concepts:
- "cinematic", "photorealistic", "film grain", "shallow depth of field"
- "dark", "moody", "atmospheric", "shadows", "chiaroscuro"
- "Sicario", "Zero Dark Thirty", any film/camera reference
- "ARRI", "RED", "ISO", any camera/film stock reference
- Complex multi-layer compositions with more than 3-4 visual elements
- Any lighting description suggesting darkness or moodiness

TEXT RULES:
- line_1 and line_2 are PROVIDED — use them exactly as given
- Text is YELLOW (#FFD700), bold, black outline, heavy drop shadow
- Text is the SINGLE LARGEST element (60-70% of frame width)

PERSONAL STAKES (build into visuals):
- Dollar amounts, threat imagery, "YOUR" framing
- Power words: CHECKMATE, TRAP, COLLAPSE, BANNED, WEAPONIZED
- The viewer must feel PERSONALLY affected

OUTPUT FORMAT (JSON only, no markdown):
Return a JSON object with ALL required variable names as keys.
Keep descriptions vivid but concise (10-25 words per variable).
"""


class ThumbnailPromptBuilder:
    """Builds bright editorial thumbnail prompts from templates + AI-filled variables.

    Uses Claude to fill template variables based on video content,
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
        palette_override: Optional[str] = None,
    ) -> str:
        """Build a complete editorial thumbnail prompt.

        Args:
            template_key: One of 'template_a', 'template_b', 'template_c', 'template_d'.
            title_data: Output from TitleGenerator.generate() containing
                line_1, line_2.
            video_title: The video's working title.
            video_summary: Brief video description.
            palette_override: Optional palette key to force (middle_east, finance,
                tech, military, global). If None, auto-detected from topic.

        Returns:
            Complete prompt string ready for Nano Banana Pro.
        """
        template_info = TEMPLATES[template_key]
        variables_needed = template_info["variables"]

        # Auto-detect or use override for color palette
        palette_key = palette_override or detect_palette(f"{video_title} {video_summary}")
        palette = THUMBNAIL_PALETTES.get(palette_key, THUMBNAIL_PALETTES["global"])
        print(f"  Color palette: {palette_key} — {palette['description']}")

        # Pre-fill the text variables + palette
        prefilled = {
            "line_1": title_data["line_1"],
            "line_2": title_data["line_2"],
            "palette_suffix": palette["prompt_suffix"],
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
                palette_key=palette_key,
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
        palette_key: str,
    ) -> dict:
        """Use Claude to fill remaining template variables.

        Args:
            template_key: Template identifier.
            template_name: Human-readable template name.
            variables: List of variable names to fill.
            video_title: Video title for context.
            video_summary: Video summary for context.
            title_data: Title generation data for context.
            palette_key: Detected/override color palette key.

        Returns:
            Dict mapping variable name -> value.
        """
        var_descriptions = self._get_variable_descriptions(template_key)

        var_guidance = "\n".join([
            f'  "{v}": {var_descriptions.get(v, "Fill based on context")}'
            for v in variables
        ])

        palette = THUMBNAIL_PALETTES.get(palette_key, THUMBNAIL_PALETTES["global"])

        user_prompt = (
            f"Fill the thumbnail template variables for this video:\n\n"
            f'VIDEO TITLE: "{video_title}"\n'
            f'VIDEO SUMMARY: {video_summary}\n'
            f'THUMBNAIL TEXT LINE 1: {title_data["line_1"]}\n'
            f'THUMBNAIL TEXT LINE 2: {title_data["line_2"]}\n'
            f'COLOR PALETTE: {palette_key} — {palette["description"]}\n'
            f'PALETTE COLORS: {palette["prompt_suffix"]}\n\n'
            f'TEMPLATE: {template_name} ({template_key})\n\n'
            f'Fill these variables (return JSON object with these exact keys):\n'
            f'{var_guidance}\n\n'
            f'REMEMBER: Bright editorial illustration style. NO dark/moody/cinematic '
            f'descriptions. Every element should be vivid, colorful, and readable at '
            f'160x90px phone thumbnail size.\n\n'
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
                "region": (
                    "The geographic region shown on the map. Examples: "
                    "'Middle East and Persian Gulf region', 'East Asia and "
                    "South China Sea', 'Eastern Europe and Black Sea region'"
                ),
                "country_labels": (
                    "Small white country labels to place on the map. Examples: "
                    "'small white labels for Iran Iraq Saudi Arabia Kuwait UAE', "
                    "'labels for China Taiwan Japan South Korea Philippines'"
                ),
                "barrier_description": (
                    "The visual barrier or obstruction blocking the route/flow. "
                    "Must be dramatic and immediately recognizable. Examples: "
                    "'the Strait of Hormuz blocked by a massive steel wall with "
                    "red X marks', 'a giant chain stretching across the Taiwan "
                    "Strait with padlocks'"
                ),
                "consequence_elements": (
                    "Visual consequences of the barrier — what's affected. "
                    "Examples: 'oil tankers piled up unable to pass with dollar "
                    "bills and smoke', 'cargo ships backed up with red warning "
                    "lights flashing'"
                ),
            }
        elif template_key == "template_b":
            return {
                "character_description": (
                    "A recognizable figure or symbolic character (NOT a specific "
                    "real person's face). Examples: 'a figure in a sharp suit "
                    "with an American flag pin', 'a young person in a hoodie "
                    "surrounded by screens', 'a shadowy figure on a throne of "
                    "gold bars'"
                ),
                "pose": (
                    "The character's pose — conveys power or action. Examples: "
                    "'confidently with arms crossed', 'pointing forward "
                    "dramatically', 'holding up a glowing object'"
                ),
                "thematic_elements": (
                    "Elements that surround the character telling the story. "
                    "Examples: 'flying money and breaking institutions', "
                    "'crumbling buildings and rising graphs', 'military "
                    "equipment and diplomatic seals'"
                ),
                "brand_elements": (
                    "Recognizable logos, flags, or brand imagery if relevant. "
                    "Examples: 'American and Chinese flags clashing', "
                    "'tech company logos falling like dominoes', "
                    "'oil barrel logos cracking'. Use 'no specific brand elements' "
                    "if not applicable."
                ),
                "floating_elements": (
                    "Items floating around the character for visual energy. "
                    "Examples: 'money and gold coins', 'data streams and "
                    "circuit boards', 'broken chains and documents'"
                ),
                "text_position": (
                    "Where the text sits relative to the character. Options: "
                    "'upper half', 'upper-right', 'center'. Choose based on "
                    "where the character leaves space."
                ),
            }
        elif template_key == "template_c":
            return {
                "loser_element": (
                    "The losing side of the split — visual of damage/loss. "
                    "Examples: 'a crumbling building with red X marks and "
                    "banned stamps', 'a deflating dollar sign with cracks', "
                    "'a broken pipeline leaking oil with danger tape'"
                ),
                "winner_element": (
                    "The winning side of the split — visual of power/success. "
                    "Examples: 'a glowing golden crown with green checkmarks', "
                    "'a rising graph with celebration confetti', 'a fortified "
                    "vault door with gold bars visible'"
                ),
                "connecting_element": (
                    "A power figure or object between the two sides. Examples: "
                    "'a hand pulling a lever', 'a figure pointing from loser "
                    "to winner', 'a giant scissors cutting a rope'"
                ),
                "scattered_elements": (
                    "Items scattered around both sides for visual interest. "
                    "Examples: 'dollar bills and documents', 'sparks and debris', "
                    "'broken chains and falling coins'"
                ),
                "text_position": (
                    "Where the text sits. Options: 'upper half', 'center', "
                    "'upper-right'. Choose based on composition balance."
                ),
            }
        elif template_key == "template_d":
            return {
                "region": (
                    "The geographic region for the map background. Examples: "
                    "'the Middle East', 'East Asia', 'Europe and North Africa'"
                ),
                "highlight_country": (
                    "The key country highlighted on the map. Examples: "
                    "'Iran highlighted in bold red', 'China outlined in "
                    "bright gold', 'Russia highlighted in deep red'"
                ),
                "metaphor_description": (
                    "The dramatic symbolic action — the core visual metaphor. "
                    "Must be INSTANTLY recognizable. Examples: 'A massive red "
                    "fist punching into a giant steel bear trap with sparks "
                    "flying', 'A giant hand turning a valve wheel shut on a "
                    "pipeline with oil backing up', 'A golden cage slamming "
                    "shut around a pile of money'"
                ),
                "consequence_elements": (
                    "Visual fallout from the metaphor action. Examples: "
                    "'sparks and debris and dollar bills flying from the "
                    "impact', 'broken missiles scattered nearby', 'smoke "
                    "and cracking ground spreading outward'"
                ),
                "geographic_labels": (
                    "Small white country labels on the map. Examples: "
                    "'small white labels for Iran Iraq Saudi Arabia Kuwait', "
                    "'labels for Russia Ukraine Poland Germany'"
                ),
            }
        return {}
