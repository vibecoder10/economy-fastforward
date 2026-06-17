"""Thumbnail prompt builder.

Takes title generation output (line_1, line_2) and video metadata,
then uses Claude to fill template variables and produce the final
Nano Banana Pro prompt from one of the four thumbnail templates.

Style: high-CTR thumbnail craft — bright, bold, instantly readable at phone
size, one clear visual concept, a tight 3-4 color palette, big readable text.
The look is driven by the channel's own visual style and the video's subject,
not a fixed house style.

IMPORTANT: This is the THUMBNAIL system, separate from the scene-image style
(style_engine.py). Never mix them.
"""

import json
from typing import Optional

from thumbnail.templates import (
    TEMPLATES,
    THUMBNAIL_PALETTES,
    detect_palette,
)
from orchestrator.pipeline_constants import Models
from shared.json_utils import parse_json_response


# ---------------------------------------------------------------------------
# System prompt for Claude to fill editorial template variables
# ---------------------------------------------------------------------------
VARIABLE_FILL_SYSTEM_PROMPT = """\
You are the visual director for a YouTube channel's thumbnails.

Your job: Fill in the template variables to produce a HIGH CTR YouTube thumbnail.
The thumbnail must be BRIGHT, BOLD, and INSTANTLY READABLE at phone size (160x90px).
A viewer scrolling their feed should grasp it in under a second.

STYLE RULES (MANDATORY — violating any of these kills CTR):
- ONE clear visual concept — the image tells a single story at a glance
- High contrast and a clear focal point that pops from its background
- A tight palette: maximum 3-4 dominant colors from the provided palette
- Keep it simple and instantly recognizable — no fussy detail that dissolves
  when shrunk to thumbnail size
- Match the channel's own visual style and the video's subject; don't impose a
  fixed house look
- 16:9 landscape, 1280x720

ANTI-PATTERNS — these reliably hurt CTR, avoid them:
- Cluttered, multi-layer compositions with more than 3-4 visual elements
- Low contrast, muddy color, or detail too fine to read at 160x90px
- Anything the eye has to hunt through to understand

TEXT RULES:
- line_1 and line_2 are PROVIDED — use them exactly as given
- Text must be bold and high-contrast (heavy weight, outline, or backing) so it
  stays sharp at small size; use a color that reads against the background
- Text is one of the LARGEST elements in the frame (about 60-70% of frame width)

VISUAL METAPHOR:
- Each of the 3 thumbnail concepts you help build uses a COMPLETELY DIFFERENT
  visual idea — a different subject, composition, or metaphor — so the channel
  has a real choice, not three near-copies.
- Draw the metaphor from THIS video's actual subject and the channel's niche —
  a cooking video reaches for ingredients, heat, and the finished dish; a
  language or story video for faces, places, and everyday moments. Pick what
  fits the topic naturally, never a fixed stock list.

Name SPECIFIC OBJECTS with relationships, not generic elements.
BAD: "a scene related to the topic"
GOOD: "a single golden croissant breaking open, steam rising, on a deep-blue
plate filling two thirds of the frame"

OUTPUT FORMAT (JSON only, no markdown):
Return a JSON object with ALL required variable names as keys.
Keep descriptions vivid but concise (10-25 words per variable).
"""


class ThumbnailPromptBuilder:
    """Builds bright editorial thumbnail prompts from templates + AI-filled variables.

    Uses Claude to fill template variables based on video content,
    then formats the final prompt for Nano Banana Pro image generation.
    """

    def __init__(self, anthropic_client, system_prompt_override: Optional[str] = None):
        """Initialize with an existing AnthropicClient instance.

        Args:
            anthropic_client: An initialized AnthropicClient from the pipeline.
            system_prompt_override: Optional tenant system prompt that replaces
                VARIABLE_FILL_SYSTEM_PROMPT at the Claude call site.
        """
        self.anthropic = anthropic_client
        self.system_prompt_override = system_prompt_override

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
            system_prompt=self.system_prompt_override or VARIABLE_FILL_SYSTEM_PROMPT,
            model=Models.CLAUDE_SONNET,
            max_tokens=800,
        )

        result = parse_json_response(response, default=None)
        if result is None:
            raise ValueError("Failed to parse variable fill response as JSON")

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
                    "The setting or backdrop shown behind the subject. Choose "
                    "whatever fits the video's actual topic — a kitchen counter, "
                    "a classroom, a map, a workshop, a stage. Keep it simple and "
                    "instantly readable."
                ),
                "country_labels": (
                    "Short, optional labels placed on the backdrop to orient the "
                    "viewer (a place name, a step number, a key word). Keep them "
                    "small and few; use 'no labels' if the image reads without "
                    "them."
                ),
                "barrier_description": (
                    "The central visual element that creates the tension or "
                    "contrast in the image. Must be dramatic and immediately "
                    "recognizable, drawn from the video's own subject — e.g. a "
                    "cracked egg mid-break, a split screen, a bold X over one "
                    "option, a single object spotlighted."
                ),
                "consequence_elements": (
                    "The supporting visuals that show the result or stakes of "
                    "the central element. Examples drawn from the topic — e.g. "
                    "ingredients scattering, a tidy 'after' beside a messy "
                    "'before', a rising line, a checkmark."
                ),
            }
        elif template_key == "template_b":
            return {
                "character_description": (
                    "A recognizable figure or symbolic character (NOT a specific "
                    "real person's face). Pick what fits the niche — e.g. a cook "
                    "in an apron, a confident learner mid-sentence, a maker at a "
                    "workbench, a friendly host gesturing to the subject."
                ),
                "pose": (
                    "The character's pose — conveys energy or focus. Examples: "
                    "'leaning in with a big smile', 'pointing toward the subject', "
                    "'holding up the finished result'"
                ),
                "thematic_elements": (
                    "Elements that surround the character and tell the story, "
                    "drawn from the video's topic. Examples: 'fresh ingredients "
                    "and steam', 'speech bubbles and everyday objects', 'tools "
                    "and a half-finished build'"
                ),
                "brand_elements": (
                    "Recognizable logos or imagery if genuinely relevant to the "
                    "topic. Examples: 'a familiar app icon', 'a cookbook cover'. "
                    "Use 'no specific brand elements' if not applicable."
                ),
                "floating_elements": (
                    "Items floating around the character for visual energy, from "
                    "the topic. Examples: 'herbs and droplets', 'letters and "
                    "small icons', 'sparks and tools'"
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
                    "The 'before' or weaker side of the split — the problem, the "
                    "mistake, the messy version. Examples from the topic: 'a "
                    "collapsed cake', 'a confusing tangle of words', 'a jammed, "
                    "half-built contraption'"
                ),
                "winner_element": (
                    "The 'after' or stronger side of the split — the success, the "
                    "fix, the polished version. Examples: 'a perfect golden "
                    "loaf', 'a clear confident phrase', 'a clean finished build'"
                ),
                "connecting_element": (
                    "A figure or object between the two sides that links them. "
                    "Examples: 'a hand flipping a switch', 'an arrow from before "
                    "to after', 'a host pointing from one side to the other'"
                ),
                "scattered_elements": (
                    "Items scattered around both sides for visual interest, from "
                    "the topic. Examples: 'flour and crumbs', 'small icons and "
                    "sparks', 'screws and shavings'"
                ),
                "text_position": (
                    "Where the text sits. Options: 'upper half', 'center', "
                    "'upper-right'. Choose based on composition balance."
                ),
            }
        elif template_key == "template_d":
            return {
                "region": (
                    "The backdrop or setting for the image. Pick what fits the "
                    "topic — e.g. 'a warm kitchen', 'a bright study desk', 'a "
                    "workshop bench', or a simple map if the video is about a "
                    "place."
                ),
                "highlight_country": (
                    "The single key subject to spotlight against the backdrop. "
                    "Examples: 'the finished dish glowing in the center', 'one "
                    "highlighted word', 'the hero object outlined in bright "
                    "color'"
                ),
                "metaphor_description": (
                    "The dramatic symbolic action — the core visual metaphor. "
                    "Must be INSTANTLY recognizable and drawn from the video's "
                    "subject. Examples: 'a single croissant breaking open with "
                    "steam rising', 'a hand flipping a giant switch from OFF to "
                    "ON', 'a lightbulb snapping on over a notebook'"
                ),
                "consequence_elements": (
                    "Visual fallout or result from the metaphor action, from the "
                    "topic. Examples: 'steam and crumbs flying outward', 'sparks "
                    "and confetti', 'a spreading glow'"
                ),
                "geographic_labels": (
                    "Short, optional labels on the backdrop to orient the viewer "
                    "(a name, a step, a key word). Keep them small and few; use "
                    "'no labels' if the image reads without them."
                ),
            }
        return {}
