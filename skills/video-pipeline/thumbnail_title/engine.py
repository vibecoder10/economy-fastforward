"""ThumbnailTitleEngine — orchestrates matched title + thumbnail generation.

This is the main entry point for the thumbnail/title system. It:
1. Selects the appropriate template based on video metadata
2. Generates a title using proven formula patterns
3. Builds a thumbnail prompt with the title's CAPS word as the red highlight
4. Generates the thumbnail image via Nano Banana Pro
5. Validates the result
6. Returns a complete package ready for pipeline integration

Usage from pipeline.py:
    engine = ThumbnailTitleEngine(anthropic_client, image_client)
    result = await engine.generate(video_metadata)
"""

import json
from typing import Optional

from thumbnail_title.selector import select_template
from thumbnail_title.title_generator import TitleGenerator
from thumbnail_title.prompt_builder import ThumbnailPromptBuilder
from thumbnail_title.validator import validate_thumbnail, validate_title_thumbnail_pair


# Maximum generation attempts before flagging for manual review
MAX_GENERATION_ATTEMPTS = 3


class ThumbnailTitleEngine:
    """Orchestrates matched title + thumbnail generation.

    Produces title/thumbnail pairs where the CAPS word in the title
    matches the red_word in the thumbnail, creating a unified visual hook.
    """

    def __init__(self, anthropic_client, image_client):
        """Initialize with existing pipeline clients.

        Args:
            anthropic_client: An initialized AnthropicClient.
            image_client: An initialized ImageClient (Kie.ai).
        """
        self.title_gen = TitleGenerator(anthropic_client)
        self.prompt_builder = ThumbnailPromptBuilder(anthropic_client)
        self.image_client = image_client

    async def generate(
        self,
        video_metadata: dict,
        preferred_formula: Optional[str] = None,
        preferred_template: Optional[str] = None,
    ) -> dict:
        """Generate a matched title + thumbnail pair.

        Args:
            video_metadata: Dict with at least:
                - Video Title: str
                - Summary: str
                Optional:
                - tags: list[str]
                - topic: str
                - Framework Angle: str
            preferred_formula: Force a specific title formula (formula_1..formula_6).
            preferred_template: Force a specific template (template_a..template_c).

        Returns:
            Dict with:
                title: str — full YouTube title
                caps_word: str — the ALL CAPS word (= red_word)
                formula_used: str — title formula key
                template_used: str — thumbnail template key
                template_name: str — human-readable template name
                thumbnail_prompt: str — complete Nano Banana Pro prompt
                thumbnail_urls: list[str] | None — generated image URLs
                thumbnail_attempt: int — generation attempt number (1-3)
                line_1: str — thumbnail primary text
                line_2: str — thumbnail secondary text
                validation: dict — validation results
                needs_manual_review: bool — True if max attempts reached
        """
        video_title = video_metadata.get("Video Title", "")
        video_summary = video_metadata.get("Summary", "")
        tags = video_metadata.get("tags", [])

        # Step 1: Select template
        template_key = preferred_template or select_template(video_metadata)
        from thumbnail_title.templates import TEMPLATES
        template_name = TEMPLATES[template_key]["name"]
        print(f"  Template selected: {template_name} ({template_key})")

        # Step 2: Generate title
        print(f"  Generating title...")
        title_data = await self.title_gen.generate(
            video_title=video_title,
            video_summary=video_summary,
            tags=tags,
            preferred_formula=preferred_formula,
        )
        print(f"  Title: {title_data['title']}")
        print(f"  CAPS word: {title_data['caps_word']}")
        print(f"  Thumbnail text: {title_data['line_1']} / {title_data['line_2']}")

        # Step 3: Validate title-thumbnail pairing
        pair_valid, pair_issues = validate_title_thumbnail_pair(title_data, template_key)
        if not pair_valid:
            for issue in pair_issues:
                print(f"  WARNING: {issue}")

        # Step 4: Build thumbnail prompt
        print(f"  Building thumbnail prompt...")
        thumbnail_prompt = await self.prompt_builder.build(
            template_key=template_key,
            title_data=title_data,
            video_title=video_title,
            video_summary=video_summary,
        )
        print(f"  Prompt built ({len(thumbnail_prompt)} chars)")

        # Step 5: Generate thumbnail image (with retry)
        thumbnail_urls = None
        attempt = 0
        needs_manual_review = False

        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            print(f"  Generating thumbnail (attempt {attempt}/{MAX_GENERATION_ATTEMPTS})...")
            thumbnail_urls = await self.image_client.generate_thumbnail(thumbnail_prompt)

            if thumbnail_urls:
                print(f"  Thumbnail generated: {thumbnail_urls[0][:60]}...")

                # Step 6: Download and validate
                try:
                    image_data = await self.image_client.download_image(thumbnail_urls[0])
                    img_valid, img_checks = validate_thumbnail(image_data)
                    if img_valid:
                        print(f"  Validation passed")
                        break
                    else:
                        failed = [k for k, v in img_checks.items() if not v]
                        print(f"  Validation failed: {failed}. Retrying...")
                        thumbnail_urls = None
                except Exception as e:
                    print(f"  Validation error: {e}. Accepting image.")
                    # Accept the image if we can't validate it
                    break
            else:
                print(f"  Generation failed. {'Retrying...' if attempt < MAX_GENERATION_ATTEMPTS else 'Flagging for manual review.'}")

        if not thumbnail_urls:
            needs_manual_review = True
            print(f"  FLAGGED FOR MANUAL REVIEW after {MAX_GENERATION_ATTEMPTS} attempts")

        return {
            "title": title_data["title"],
            "caps_word": title_data["caps_word"],
            "formula_used": title_data["formula_used"],
            "template_used": template_key,
            "template_name": template_name,
            "thumbnail_prompt": thumbnail_prompt,
            "thumbnail_urls": thumbnail_urls,
            "thumbnail_attempt": attempt,
            "line_1": title_data["line_1"],
            "line_2": title_data["line_2"],
            "validation": {
                "pair_valid": pair_valid,
                "pair_issues": pair_issues,
            },
            "needs_manual_review": needs_manual_review,
        }
