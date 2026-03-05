"""Sound Prompt Bot — intelligently selects which images get sound, then generates prompts.

Two-phase approach:
1. Curation: Claude sees all images in a scene and picks which ones benefit from sound
2. Generation: Sound prompts generated only for selected images; skipped images get "SKIP"

Selection bounds are percentage-based (default 25% min, 60% max of images per scene).
"""

import json
import math
from collections import defaultdict
from typing import Optional

from clients.anthropic_client import AnthropicClient
from clients.airtable_client import AirtableClient


SOUND_CURATION_SYSTEM = """\
You are a cinematic sound designer selecting which moments in a documentary scene deserve ambient sound effects. Not every image needs sound — silence is powerful too.

You will receive all images in a single scene. For each, decide: does this moment benefit from a sound layer, or is it stronger with just narration?

ADD SOUND when:
- The visual has a distinct environment (city street, factory floor, ocean, forest)
- There's implied action or motion (crowds moving, machines running, weather)
- Emotional weight that sound reinforces (tension, revelation, grandeur)
- Transitional moments that establish a new setting

SKIP SOUND when:
- Abstract data visualizations or charts with no physical setting
- Consecutive images showing the same environment (avoid repetitive ambience)
- Narration alone carries the emotional weight and sound would distract
- Generic corporate/office visuals with nothing distinctive to hear

Return ONLY a JSON array, one entry per image:
[{"image_index": 1, "sound": true}, {"image_index": 2, "sound": false}]"""


SOUND_PROMPT_SYSTEM = """\
You are a cinematic sound designer. Given the narration text and visual description for one moment in a documentary, generate a single ambient sound effect description (max 450 characters, max 30 words).

Rules:
- Describe 2-3 layered sound elements that match both what's being said AND what's being shown
- This plays underneath narration at low volume — atmosphere only, NOT music
- Be specific: 'distant artillery rumble with crackling fire and faint radio chatter' not 'war sounds'
- Match emotional tone to content
- Output ONLY the sound description, nothing else."""

# Percentage bounds for sound selection per scene
MIN_SOUND_PERCENT = 0.25
MAX_SOUND_PERCENT = 0.60


class SoundPromptBot:
    """Selects which images get sound, then generates prompts for those images."""

    def __init__(
        self,
        anthropic: Optional[AnthropicClient] = None,
        airtable: Optional[AirtableClient] = None,
        min_sound_pct: float = MIN_SOUND_PERCENT,
        max_sound_pct: float = MAX_SOUND_PERCENT,
    ):
        self.anthropic = anthropic or AnthropicClient()
        self.airtable = airtable or AirtableClient()
        self.min_sound_pct = min_sound_pct
        self.max_sound_pct = max_sound_pct

    def _compute_bounds(self, image_count: int) -> tuple[int, int]:
        """Compute min/max sound count for a scene based on percentage bounds.

        Always at least 1 sound per scene.
        """
        min_sounds = max(1, math.ceil(image_count * self.min_sound_pct))
        max_sounds = max(min_sounds, math.floor(image_count * self.max_sound_pct))
        return min_sounds, max_sounds

    async def curate_scene_sounds(
        self,
        scene_images: list[dict],
    ) -> list[dict]:
        """Ask Claude which images in a scene should get sound effects.

        Args:
            scene_images: List of image dicts from Airtable, sorted by index

        Returns:
            List of dicts with image_index and sound (bool) for each image
        """
        image_count = len(scene_images)
        if image_count == 0:
            return []

        min_sounds, max_sounds = self._compute_bounds(image_count)

        # Build the scene context for Claude
        lines = []
        for img in scene_images:
            idx = img.get("Image Index", 0)
            text = img.get("Sentence Text", "").strip()
            visual = img.get("Image Prompt", "").strip()
            shot = img.get("Shot Type", "").strip()
            lines.append(
                f"Image {idx}:\n"
                f"  Narration: {text[:200]}\n"
                f"  Visual: {visual[:200]}\n"
                f"  Shot: {shot}"
            )

        user_prompt = (
            f"Scene with {image_count} images. "
            f"Select between {min_sounds} and {max_sounds} images for sound effects.\n\n"
            + "\n\n".join(lines)
        )

        response = await self.anthropic.generate(
            prompt=user_prompt,
            system_prompt=SOUND_CURATION_SYSTEM,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            temperature=0.4,
        )

        if not response:
            # Fallback: select first min_sounds images
            return self._fallback_selection(scene_images, min_sounds)

        # Parse JSON response
        selections = self._parse_curation_response(response, scene_images)
        if not selections:
            return self._fallback_selection(scene_images, min_sounds)

        # Enforce bounds
        selections = self._enforce_bounds(selections, min_sounds, max_sounds)
        return selections

    def _parse_curation_response(
        self,
        response: str,
        scene_images: list[dict],
    ) -> list[dict]:
        """Parse Claude's curation JSON response."""
        text = response.strip()

        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try extracting JSON array
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                try:
                    parsed = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(parsed, list):
            return []

        # Build index set from actual images
        valid_indices = {img.get("Image Index", 0) for img in scene_images}

        results = []
        for entry in parsed:
            idx = entry.get("image_index")
            sound = entry.get("sound", False)
            if idx in valid_indices:
                results.append({"image_index": idx, "sound": bool(sound)})

        # Fill in any missing indices as sound=False
        found_indices = {r["image_index"] for r in results}
        for idx in valid_indices - found_indices:
            results.append({"image_index": idx, "sound": False})

        results.sort(key=lambda r: r["image_index"])
        return results

    def _enforce_bounds(
        self,
        selections: list[dict],
        min_sounds: int,
        max_sounds: int,
    ) -> list[dict]:
        """Enforce min/max sound counts by toggling selections."""
        selected = [s for s in selections if s["sound"]]
        not_selected = [s for s in selections if not s["sound"]]

        # Too few: promote unselected images (prefer earlier ones for scene establishment)
        while len(selected) < min_sounds and not_selected:
            promoted = not_selected.pop(0)
            promoted["sound"] = True
            selected.append(promoted)

        # Too many: demote excess (prefer removing later ones)
        while len(selected) > max_sounds:
            demoted = selected.pop()
            demoted["sound"] = False
            not_selected.append(demoted)

        all_items = selected + not_selected
        all_items.sort(key=lambda s: s["image_index"])
        return all_items

    def _fallback_selection(
        self,
        scene_images: list[dict],
        min_sounds: int,
    ) -> list[dict]:
        """Fallback: evenly space sound selections across the scene."""
        count = len(scene_images)
        if count == 0:
            return []

        # Space selections evenly
        step = max(1, count / min_sounds)
        selected_positions = set()
        for i in range(min_sounds):
            pos = min(int(i * step), count - 1)
            selected_positions.add(pos)

        results = []
        for i, img in enumerate(scene_images):
            idx = img.get("Image Index", 0)
            results.append({"image_index": idx, "sound": i in selected_positions})

        return results

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
        """Generate sound prompts for a video using intelligent scene-level curation.

        Phase 1: For each scene, Claude selects which images benefit from sound (25-60%)
        Phase 2: Generate prompts only for selected images; mark others as SKIP

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

        # Group images by scene
        scenes: dict[int, list[dict]] = defaultdict(list)
        for img in images:
            scene_num = img.get("Scene", 0)
            scenes[scene_num].append(img)

        total_generated = 0
        total_skipped_by_curation = 0
        already_existed = 0

        for scene_num in sorted(scenes.keys()):
            scene_images = scenes[scene_num]

            # Check if all images in this scene already have prompts
            needs_processing = [
                img for img in scene_images if not img.get("Sound Prompt")
            ]
            already_done = len(scene_images) - len(needs_processing)

            if not needs_processing:
                print(f"  Scene {scene_num}: All {len(scene_images)} images already have prompts")
                already_existed += already_done
                total_generated += already_done
                continue

            if already_done > 0:
                print(f"  Scene {scene_num}: {already_done}/{len(scene_images)} already done, "
                      f"processing {len(needs_processing)} remaining")
                already_existed += already_done
                total_generated += already_done

            # Phase 1: Curate — which images get sound?
            print(f"  Scene {scene_num}: Curating {len(needs_processing)} images...")
            min_s, max_s = self._compute_bounds(len(needs_processing))
            selections = await self.curate_scene_sounds(needs_processing)

            selected_count = sum(1 for s in selections if s["sound"])
            print(f"    Selected {selected_count}/{len(needs_processing)} for sound "
                  f"(bounds: {min_s}-{max_s})")

            # Build lookup: image_index -> should have sound
            sound_map = {s["image_index"]: s["sound"] for s in selections}

            # Phase 2: Generate prompts for selected, SKIP for others
            for img in needs_processing:
                record_id = img["id"]
                idx = img.get("Image Index", 0)
                should_sound = sound_map.get(idx, False)

                if not should_sound:
                    # Mark as SKIP
                    try:
                        self.airtable.update_image_sound_prompt(record_id, "SKIP")
                        total_skipped_by_curation += 1
                        print(f"    Scene {scene_num} img {idx}: SKIP")
                    except Exception as e:
                        print(f"    ❌ Failed to write SKIP: {e}")
                    continue

                sentence_text = img.get("Sentence Text", "")
                image_prompt = img.get("Image Prompt", "")
                shot_type = img.get("Shot Type", "")

                if not sentence_text and not image_prompt:
                    print(f"    Scene {scene_num} img {idx}: No text or prompt, skipping")
                    continue

                print(f"    Scene {scene_num} img {idx}: Generating sound prompt...")

                prompt = await self.generate_sound_prompt(
                    sentence_text=sentence_text,
                    image_prompt=image_prompt,
                    shot_type=shot_type,
                )

                if prompt:
                    try:
                        self.airtable.update_image_sound_prompt(record_id, prompt)
                        total_generated += 1
                        print(f"      ✅ {prompt[:60]}...")
                    except Exception as e:
                        print(f"      ❌ Failed to write Sound Prompt: {e}")
                else:
                    print(f"      ❌ Generation failed for scene {scene_num} img {idx}")

        total_images = len(images)
        print(f"\n  Sound prompts complete: {total_generated}/{total_images} generated, "
              f"{total_skipped_by_curation} skipped by curation "
              f"({already_existed} already existed)")

        return {
            "bot": "Sound Prompt Bot",
            "video_title": video_title,
            "total_images": total_images,
            "prompts_generated": total_generated,
            "skipped_by_curation": total_skipped_by_curation,
            "already_existed": already_existed,
        }
