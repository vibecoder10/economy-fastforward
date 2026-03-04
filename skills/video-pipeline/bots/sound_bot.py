"""Sound Bot — generates sound effect audio files per image row.

For each image in the Images table that has a Sound Prompt but no Sound Effect,
generates an 8-second MP3 via Kie.ai, uploads to Google Drive, and attaches
to the image row. This replaces the old scene-level Sound Map approach.
"""

import asyncio
from typing import Optional

from clients.sound_client import SoundClient
from clients.airtable_client import AirtableClient
from clients.google_client import GoogleClient
from clients.slack_client import SlackClient


# Safety limit — max generations per video
MAX_GENERATIONS_PER_VIDEO = 200


class SoundBot:
    """Generates sound effect audio files from per-image sound prompts."""

    DEFAULT_DURATION = 8.0
    DEFAULT_VOLUME = 0.15

    def __init__(
        self,
        sound_client: Optional[SoundClient] = None,
        airtable: Optional[AirtableClient] = None,
        google: Optional[GoogleClient] = None,
        slack: Optional[SlackClient] = None,
    ):
        self.sound_client = sound_client or SoundClient()
        self.airtable = airtable or AirtableClient()
        self.google = google or GoogleClient()
        self.slack = slack

    async def process_video(
        self,
        video_title: str,
        folder_id: Optional[str] = None,
        dry_run: bool = False,
        max_concurrent: int = 3,
    ) -> dict:
        """Generate sound effects for all images of a video.

        Args:
            video_title: Title of the video
            folder_id: Google Drive folder for uploads
            dry_run: If True, log prompts without generating audio
            max_concurrent: Max concurrent generations

        Returns:
            Dict with processing results
        """
        print(f"\n  SOUND BOT: Processing '{video_title}' {'[DRY RUN]' if dry_run else ''}")

        images = self.airtable.get_all_images_for_video(video_title)
        if not images:
            return {"error": f"No images found for: {video_title}"}

        # Filter to images with Sound Prompt but no Sound Effect
        needs_generation = [
            img for img in images
            if img.get("Sound Prompt") and not img.get("Sound Effect")
        ]

        if not needs_generation:
            already_done = sum(1 for img in images if img.get("Sound Effect"))
            if already_done > 0:
                return {
                    "bot": "Sound Bot",
                    "video_title": video_title,
                    "total_generated": already_done,
                    "message": f"All {already_done} sound effects already generated",
                }
            return {"error": "No images with Sound Prompt found. Run sound_prompt_bot first."}

        # Get Drive folder
        if not folder_id:
            idea = self.airtable.find_idea_by_title(video_title)
            if idea:
                folder_id = idea.get("Google Drive Folder ID") or idea.get("Drive Folder ID")
            if not folder_id:
                return {"error": f"No Drive folder found for: {video_title}"}

        needs_generation = sorted(
            needs_generation,
            key=lambda i: (i.get("Scene", 0), i.get("Image Index", 0)),
        )

        total_generated = 0
        limit_reached = False

        # Process in batches
        for batch_start in range(0, len(needs_generation), max_concurrent):
            if limit_reached:
                break

            batch = needs_generation[batch_start:batch_start + max_concurrent]
            tasks = [
                self._generate_for_image(img, folder_id, dry_run)
                for img in batch
            ]
            results = await asyncio.gather(*tasks)

            for success in results:
                if success:
                    total_generated += 1

                if self.sound_client.generation_count >= MAX_GENERATIONS_PER_VIDEO:
                    msg = f"Hit {MAX_GENERATIONS_PER_VIDEO} generation limit"
                    print(f"    ⚠️ {msg}")
                    if self.slack:
                        self.slack.notify(f"⚠️ {msg}. Pausing sound generation.")
                    limit_reached = True
                    break

        estimated_cost = self.sound_client.estimated_total_cost

        print(f"\n  Sound effects complete: {total_generated}/{len(needs_generation)} generated")
        print(f"  Estimated cost: ~${estimated_cost:.2f}")

        return {
            "bot": "Sound Bot",
            "video_title": video_title,
            "total_generated": total_generated,
            "total_images": len(needs_generation),
            "estimated_cost": round(estimated_cost, 2),
            "dry_run": dry_run,
            "limit_reached": limit_reached,
        }

    async def _generate_for_image(
        self,
        img: dict,
        folder_id: str,
        dry_run: bool = False,
    ) -> bool:
        """Generate a sound effect for a single image row.

        Returns True if successful.
        """
        record_id = img["id"]
        scene = img.get("Scene", 0)
        idx = img.get("Image Index", 0)
        prompt = img.get("Sound Prompt", "")

        if dry_run:
            print(f"    [DRY RUN] Scene {scene} img {idx}: {prompt[:60]}...")
            return False

        print(f"    Scene {scene} img {idx}: {prompt[:60]}...")

        audio_url = await self.sound_client.generate_sound_effect(
            text=prompt,
            duration_seconds=self.DEFAULT_DURATION,
            loop=False,
        )

        if not audio_url:
            print(f"    ❌ Generation failed for scene {scene} img {idx}")
            return False

        # Download and upload to Google Drive
        filename = f"sfx_{scene}_{idx}.mp3"
        try:
            audio_content = await self.sound_client.download_audio(audio_url)
            drive_file = self.google.upload_audio(audio_content, filename, folder_id)
            drive_url = self.google.make_file_public(drive_file["id"])

            # Attach to image row in Airtable
            self.airtable.update_image_sound_effect(
                record_id=record_id,
                sound_url=drive_url,
                volume=self.DEFAULT_VOLUME,
            )
            print(f"    ✅ {filename} uploaded")
            return True

        except Exception as e:
            print(f"    ❌ Upload/attach failed for {filename}: {e}")
            # Try attaching the raw URL as fallback
            try:
                self.airtable.update_image_sound_effect(
                    record_id=record_id,
                    sound_url=audio_url,
                    volume=self.DEFAULT_VOLUME,
                )
                return True
            except Exception:
                return False
