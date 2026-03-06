"""ThumbnailTitleEngine — orchestrates matched title + thumbnail generation.

This is the main entry point for the thumbnail/title system. It:
1. Selects the appropriate editorial template based on video metadata
2. Generates a title using proven formula patterns
3. Builds a bright editorial illustration thumbnail prompt with text overlay
4. Generates 3 thumbnail images via Nano Banana Pro for manual selection
5. Validates the results
6. Returns a complete package ready for pipeline integration

The yin-yang system: when thumbnail_text is provided, the thumbnail overlay is
INDEPENDENT from the title — they complement each other without repeating.
When thumbnail_text is absent, auto-generates a 2-4 word personal-stakes phrase.

IMPORTANT: This is the THUMBNAIL system — bright editorial illustration style.
The SCENE IMAGE system (style_engine.py) stays cinematic photorealistic.
These are completely separate pipelines. Do NOT mix them.

Usage from pipeline.py:
    engine = ThumbnailTitleEngine(anthropic_client, image_client)
    result = await engine.generate(video_metadata, thumbnail_text="IRAN FELL FOR THE TRAP")
"""

from typing import Optional

from thumbnail_title.selector import select_template
from thumbnail_title.title_generator import TitleGenerator
from thumbnail_title.prompt_builder import ThumbnailPromptBuilder
from thumbnail_title.validator import validate_thumbnail, validate_title_thumbnail_pair


# Maximum generation attempts per thumbnail before flagging for manual review
MAX_GENERATION_ATTEMPTS = 3

# Number of thumbnail variants to generate for manual selection
NUM_THUMBNAIL_VARIANTS = 3

# Words that trigger visceral emotional reactions — used to pick the red_word
# when parsing independent thumbnail text. Ordered roughly by impact.
EMOTIONALLY_CHARGED_WORDS = {
    "KILLED", "DEAD", "DEATH", "DYING", "DIE", "MURDER", "PURGE", "PURGED",
    "TRAP", "TRAPPED", "CRUSHED", "WEAPONIZED", "BLACKLISTED", "BANNED",
    "BETRAYED", "RIGGED", "DOOMED", "BROKE", "BROKEN", "SWALLOWED",
    "COLLAPSE", "COLLAPSED", "DESTROYED", "STOLEN", "TOXIC", "FATAL",
    "EXPOSED", "ERASED", "SILENCED", "ENSLAVED", "OWNED", "DEVOURED",
    "CONQUERED", "RUINED", "LOST", "BURNED", "FALLEN", "FAILED",
    "CRASHED", "WIPED", "GUTTED", "BLEEDING", "WAR", "CRISIS",
    "CHAOS", "LIED", "FRAUD", "SCAM", "LIES", "VICTIM", "BURIED",
    "STRANGLED", "LOOTED", "HIJACKED", "BANKRUPT", "WRECKED",
    "CHECKMATE", "CONTROLS", "CUT",
}


class ThumbnailTitleEngine:
    """Orchestrates matched title + thumbnail generation.

    Generates bright editorial illustration thumbnails with bold text overlay.
    Supports yin-yang mode (thumbnail text independent from title) and
    auto-generation of thumbnail text when not provided.
    """

    def __init__(self, anthropic_client, image_client):
        """Initialize with existing pipeline clients.

        Args:
            anthropic_client: An initialized AnthropicClient.
            image_client: An initialized ImageClient (Kie.ai).
        """
        self.anthropic = anthropic_client
        self.title_gen = TitleGenerator(anthropic_client)
        self.prompt_builder = ThumbnailPromptBuilder(anthropic_client)
        self.image_client = image_client

    @staticmethod
    def _parse_thumbnail_text(thumbnail_text: str) -> dict:
        """Parse independent thumbnail text into line_1, line_2, and red_word.

        Splits 2-5 word ALL CAPS text into two display lines and picks the
        most emotionally charged word as the red highlight.

        Args:
            thumbnail_text: 2-5 word ALL CAPS overlay text, e.g. "IRAN FELL FOR THE TRAP"

        Returns:
            Dict with line_1, line_2, caps_word (red_word).
        """
        text = thumbnail_text.strip().upper()
        words = text.split()

        # Pick the red word: first emotionally charged word, or first word
        red_word = words[0]  # default fallback
        for word in words:
            if word in EMOTIONALLY_CHARGED_WORDS:
                red_word = word
                break

        # Split into line_1 / line_2 based on word count
        if len(words) <= 3:
            line_1 = text
            line_2 = ""
        elif len(words) == 4:
            line_1 = " ".join(words[:2])
            line_2 = " ".join(words[2:])
        else:  # 5+ words
            line_1 = " ".join(words[:3])
            line_2 = " ".join(words[3:])

        return {
            "line_1": line_1,
            "line_2": line_2,
            "caps_word": red_word,
        }

    async def _auto_generate_thumbnail_text(
        self, video_title: str, video_summary: str
    ) -> str:
        """Auto-generate thumbnail text when none is provided.

        Extracts the most impactful 2-4 word phrase from the title,
        reframes it as a personal threat or power word.

        Args:
            video_title: The video's working title.
            video_summary: Brief video description.

        Returns:
            2-4 word ALL CAPS thumbnail text string.
        """
        prompt = (
            f"Generate a 2-4 word ALL CAPS thumbnail text for this video. "
            f"The text must:\n"
            f"- Be a personal gut punch (use dollar amounts, 'YOUR', power words)\n"
            f"- Be DIFFERENT from the video title (yin-yang: complement, don't repeat)\n"
            f"- Use words like: TRAP, CHECKMATE, COLLAPSE, WEAPONIZED, BANNED, etc.\n"
            f"- Maximum 4 words, preferably 2-3\n"
            f"- Frame as personal threat to the viewer\n\n"
            f'VIDEO TITLE: "{video_title}"\n'
            f"VIDEO SUMMARY: {video_summary}\n\n"
            f"Return ONLY the 2-4 word text, nothing else. ALL CAPS."
        )

        response = await self.anthropic.generate(
            prompt=prompt,
            system_prompt="You generate punchy YouTube thumbnail text. Return ONLY the text, no quotes, no explanation.",
            model="claude-sonnet-4-5-20250929",
            max_tokens=50,
        )

        # Clean up response
        text = response.strip().strip('"').strip("'").upper()
        # Ensure max 4 words
        words = text.split()
        if len(words) > 4:
            text = " ".join(words[:4])

        return text

    @staticmethod
    def _apply_thumbnail_override(
        override: str,
        template_key: str,
        title_data: dict,
        video_title: str,
        video_summary: str,
    ) -> Optional[str]:
        """Apply a thumbnail style override to the prompt.

        - ``"REPLACE: ..."`` — use as entire prompt, substituting {line_1},
          {line_2} placeholders.
        - ``"APPEND: ..."`` — append to the selected template prompt, then
          substitute placeholders.
        - Otherwise — append to the selected template (additive default).

        Returns the final prompt string, or None if the override is empty.
        """
        from thumbnail_title.templates import TEMPLATES

        stripped = override.strip()
        if not stripped:
            return None

        template_prompt = TEMPLATES[template_key]["prompt"]
        subs = {
            "line_1": title_data["line_1"],
            "line_2": title_data["line_2"],
        }

        if stripped.upper().startswith("REPLACE:"):
            raw = stripped[len("REPLACE:"):].strip()
            print("  REPLACE override active — using custom prompt")
            try:
                result = raw.format(**subs)
                print("  REPLACE override applied (placeholders filled)")
                return result
            except (KeyError, IndexError, ValueError):
                print("  REPLACE override applied (raw, no placeholders)")
                return raw

        if stripped.upper().startswith("APPEND:"):
            addition = stripped[len("APPEND:"):].strip()
            print("  APPEND override active — adding to template")
        elif stripped.startswith("+"):
            addition = stripped[1:].strip()
            print("  '+' override active — adding to template")
        else:
            addition = stripped
            print("  Default override active — appending to template")

        combined = template_prompt + ",\n\n" + addition
        try:
            result = combined.format(**subs)
            print("  Override applied to template prompt")
            return result
        except (KeyError, IndexError, ValueError):
            print("  Thumbnail override couldn't fill template variables, falling back to normal builder")
            return None

    async def generate(
        self,
        video_metadata: dict,
        preferred_formula: Optional[str] = None,
        preferred_template: Optional[str] = None,
        thumbnail_style_override: Optional[str] = None,
        thumbnail_text: Optional[str] = None,
        palette_override: Optional[str] = None,
    ) -> dict:
        """Generate a matched title + thumbnail pair.

        Produces NUM_THUMBNAIL_VARIANTS (3) thumbnail images for manual selection.

        Args:
            video_metadata: Dict with at least:
                - Video Title: str
                - Summary: str
                Optional:
                - tags: list[str]
                - topic: str
                - Framework Angle: str
            preferred_formula: Force a specific title formula (formula_1..formula_6).
            preferred_template: Force a specific template (template_a..template_d).
            thumbnail_style_override: Per-video override from Airtable.
                - "REPLACE: ..." — use as entire prompt.
                - "APPEND: ..." — append to selected template.
                - Otherwise — append to selected template.
            thumbnail_text: Independent thumbnail overlay text (2-5 words, ALL CAPS).
                When provided, used as the thumbnail text instead of extracting
                from the title (yin-yang mode). When None/empty, auto-generates
                a personal-stakes phrase and logs a warning.
            palette_override: Force a color palette (middle_east, finance, tech,
                military, global). If None, auto-detected from topic.

        Returns:
            Dict with:
                title: str — full YouTube title
                caps_word: str — the ALL CAPS word (= red_word)
                formula_used: str — title formula key
                template_used: str — thumbnail template key
                template_name: str — human-readable template name
                thumbnail_prompt: str — complete Nano Banana Pro prompt
                thumbnail_urls: list[str] | None — generated image URLs (up to 3)
                thumbnail_attempt: int — generation attempt number (1-3)
                line_1: str — thumbnail primary text
                line_2: str — thumbnail secondary text
                validation: dict — validation results
                needs_manual_review: bool — True if all attempts failed
                thumbnail_text_auto_generated: bool — True if text was auto-generated
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
        print("  Generating title...")
        title_data = await self.title_gen.generate(
            video_title=video_title,
            video_summary=video_summary,
            tags=tags,
            preferred_formula=preferred_formula,
        )
        print(f"  Title: {title_data['title']}")
        print(f"  CAPS word (from title): {title_data['caps_word']}")

        # Step 2b: Handle thumbnail text (yin-yang mode vs auto-generation)
        thumbnail_text_auto_generated = False
        if thumbnail_text:
            parsed = self._parse_thumbnail_text(thumbnail_text)
            title_data["line_1"] = parsed["line_1"]
            title_data["line_2"] = parsed["line_2"]
            title_data["caps_word"] = parsed["caps_word"]
            print("  Yin-yang mode: using provided thumbnail text")
            print(f"  Thumbnail text: {parsed['line_1']}" + (f" / {parsed['line_2']}" if parsed['line_2'] else ""))
        else:
            # Auto-generate thumbnail text
            print("  No Thumbnail Text set — auto-generating...")
            auto_text = await self._auto_generate_thumbnail_text(
                video_title, video_summary
            )
            parsed = self._parse_thumbnail_text(auto_text)
            title_data["line_1"] = parsed["line_1"]
            title_data["line_2"] = parsed["line_2"]
            title_data["caps_word"] = parsed["caps_word"]
            thumbnail_text_auto_generated = True
            print(f"  Auto-generated thumbnail text: {auto_text}")
            display = parsed['line_1'] + (f" / {parsed['line_2']}" if parsed['line_2'] else "")
            print(f"  Parsed: {display}")

        # Step 3: Validate title-thumbnail pairing
        pair_valid, pair_issues = validate_title_thumbnail_pair(title_data, template_key)
        if not pair_valid:
            for issue in pair_issues:
                print(f"  WARNING: {issue}")

        # Step 4: Build thumbnail prompt (with optional style override)
        print("  Building thumbnail prompt...")
        if thumbnail_style_override:
            thumbnail_prompt = self._apply_thumbnail_override(
                thumbnail_style_override, template_key, title_data,
                video_title, video_summary,
            )
            if thumbnail_prompt is None:
                print("  Override returned None — falling back to normal prompt builder")
                thumbnail_prompt = await self.prompt_builder.build(
                    template_key=template_key,
                    title_data=title_data,
                    video_title=video_title,
                    video_summary=video_summary,
                    palette_override=palette_override,
                )
            else:
                print("  Override applied successfully — skipping normal prompt builder")
        else:
            thumbnail_prompt = await self.prompt_builder.build(
                template_key=template_key,
                title_data=title_data,
                video_title=video_title,
                video_summary=video_summary,
                palette_override=palette_override,
            )
        print(f"  Prompt built ({len(thumbnail_prompt)} chars)")

        # Step 5: Generate 3 thumbnail variants (with retry for each)
        all_thumbnail_urls = []
        total_attempts = 0

        for variant in range(1, NUM_THUMBNAIL_VARIANTS + 1):
            print(f"  Generating thumbnail variant {variant}/{NUM_THUMBNAIL_VARIANTS}...")
            variant_url = None

            for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
                total_attempts += 1
                urls = await self.image_client.generate_thumbnail(thumbnail_prompt)

                if urls:
                    variant_url = urls[0]
                    print(f"    Variant {variant} generated: {variant_url[:60]}...")

                    # Validate
                    try:
                        image_data = await self.image_client.download_image(variant_url)
                        img_valid, img_checks = validate_thumbnail(image_data)
                        if img_valid:
                            print(f"    Variant {variant} validation passed")
                            all_thumbnail_urls.append(variant_url)
                            break
                        else:
                            failed = [k for k, v in img_checks.items() if not v]
                            print(f"    Variant {variant} validation failed: {failed}")
                            if attempt == MAX_GENERATION_ATTEMPTS:
                                # Accept it anyway on last attempt
                                all_thumbnail_urls.append(variant_url)
                                print(f"    Accepting variant {variant} despite validation failure")
                            variant_url = None
                    except Exception as e:
                        print(f"    Validation error: {e}. Accepting image.")
                        all_thumbnail_urls.append(variant_url)
                        break
                else:
                    print(f"    Attempt {attempt}/{MAX_GENERATION_ATTEMPTS} failed")

            if not variant_url and not all_thumbnail_urls:
                print(f"    Variant {variant} failed all attempts")

        needs_manual_review = len(all_thumbnail_urls) == 0

        if needs_manual_review:
            print("  FLAGGED FOR MANUAL REVIEW — all variants failed")
        else:
            print(f"  Generated {len(all_thumbnail_urls)} thumbnail variants")

        return {
            "title": title_data["title"],
            "caps_word": title_data["caps_word"],
            "formula_used": title_data["formula_used"],
            "template_used": template_key,
            "template_name": template_name,
            "thumbnail_prompt": thumbnail_prompt,
            "thumbnail_urls": all_thumbnail_urls if all_thumbnail_urls else None,
            "thumbnail_attempt": total_attempts,
            "line_1": title_data["line_1"],
            "line_2": title_data["line_2"],
            "validation": {
                "pair_valid": pair_valid,
                "pair_issues": pair_issues,
            },
            "needs_manual_review": needs_manual_review,
            "thumbnail_text_auto_generated": thumbnail_text_auto_generated,
        }
