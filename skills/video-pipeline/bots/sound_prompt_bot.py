"""Sound Prompt Bot — generates one sound prompt per image row using Claude.

Reads image rows from the Images table and generates a single ambient sound
description for each, based on the narration text and visual description.
This replaces the old scene-level Sound Map approach.
"""

from typing import Optional

from clients.anthropic_client import AnthropicClient
from clients.airtable_client import AirtableClient


SOUND_PROMPT_SYSTEM = """\
You are a cinematic sound designer. Given the narration text and visual description for one moment in a documentary, generate a single ambient sound effect description (max 450 characters, max 30 words).

Rules:
- Describe 2-3 layered sound elements that match both what's being said AND what's being shown
- This plays underneath narration at low volume — atmosphere only, NOT music
- Be specific: 'distant artillery rumble with crackling fire and faint radio chatter' not 'war sounds'
- Match emotional tone to content
- Output ONLY the sound description, nothing else."""


class SoundPromptBot:
    """Generates one sound prompt per image row in the Images table."""

    def __init__(
        self,
        anthropic: Optional[AnthropicClient] = None,
        airtable: Optional[AirtableClient] = None,
    ):
        self.anthropic = anthropic or AnthropicClient()
        self.airtable = airtable or AirtableClient()

    async def generate_sound_prompt(
        self,
        sentence_text: str,
        image_prompt: str,
        shot_type: str = "",
    ) -> Optional[str]:
        """Generate a single sound prompt for one image.

        Args:
            sentence_text: What the narrator is saying during this image
            image_prompt: What's visually on screen
            shot_type: Composition context (e.g., wide, closeup)

        Returns:
            Sound description string, or None if generation failed
        """
        user_prompt = (
            f"Narration: {sentence_text}\n"
            f"Visual: {image_prompt}\n"
            f"Shot type: {shot_type}"
        )

        response = await self.anthropic.generate(
            prompt=user_prompt,
            system_prompt=SOUND_PROMPT_SYSTEM,
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            temperature=0.7,
        )

        if not response or len(response.strip()) < 10:
            return None

        # Clean up — strip quotes, markdown, ensure under 450 chars
        prompt = response.strip().strip('"').strip("'")
        if prompt.startswith("```"):
            prompt = prompt.strip("`").strip()
        if len(prompt) > 450:
            prompt = prompt[:450]

        return prompt

    async def process_video(self, video_title: str) -> dict:
        """Generate sound prompts for all images of a video.

        Reads image rows from the Images table, generates a sound prompt
        for each one, and writes it back to the "Sound Prompt" field.

        Args:
            video_title: Title of the video to process

        Returns:
            Dict with processing results
        """
        print(f"\n  SOUND PROMPT BOT: Processing '{video_title}'")

        images = self.airtable.get_all_images_for_video(video_title)
        if not images:
            return {"error": f"No images found for: {video_title}"}

        # Sort by scene then image index
        images = sorted(
            images,
            key=lambda i: (i.get("Scene", 0), i.get("Image Index", 0)),
        )

        total_generated = 0
        skipped = 0

        for img in images:
            record_id = img["id"]
            scene = img.get("Scene", "?")
            idx = img.get("Image Index", "?")

            # Skip if sound prompt already exists
            existing = img.get("Sound Prompt")
            if existing:
                print(f"  Scene {scene} img {idx}: Sound prompt exists, skipping")
                skipped += 1
                total_generated += 1
                continue

            sentence_text = img.get("Sentence Text", "")
            image_prompt = img.get("Image Prompt", "")
            shot_type = img.get("Shot Type", "")

            if not sentence_text and not image_prompt:
                print(f"  Scene {scene} img {idx}: No text or prompt, skipping")
                continue

            print(f"  Scene {scene} img {idx}: Generating sound prompt...")

            prompt = await self.generate_sound_prompt(
                sentence_text=sentence_text,
                image_prompt=image_prompt,
                shot_type=shot_type,
            )

            if prompt:
                # Write to Airtable
                try:
                    self.airtable.update_image_sound_prompt(record_id, prompt)
                    total_generated += 1
                    print(f"    ✅ {prompt[:60]}...")
                except Exception as e:
                    print(f"    ❌ Failed to write Sound Prompt: {e}")
            else:
                print(f"    ❌ Generation failed for scene {scene} img {idx}")

        print(f"\n  Sound prompts complete: {total_generated}/{len(images)} images "
              f"({skipped} already existed)")

        return {
            "bot": "Sound Prompt Bot",
            "video_title": video_title,
            "total_images": len(images),
            "prompts_generated": total_generated,
            "skipped": skipped,
        }
