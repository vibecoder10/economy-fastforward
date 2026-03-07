"""Animation Bot — generates video clips from images using Grok Imagine.

Reads segments from the Images table (each row = one segment with image +
animation prompt + intensity), calls Grok Imagine to animate each image,
uploads the resulting clip to Google Drive, and updates Airtable.

This bot bridges the new configurable pipeline engines:
    segmentation_engine → animation_prompt_engine → Grok Imagine client

Status transition: Ready For Animation → Ready For Thumbnail
"""

import asyncio
from typing import Optional

from pipeline_config import VideoConfig
from animation_prompt_engine import generate_animation_prompt


class AnimationBot:
    """Generates video clips from holographic display images.

    Thin adapter that takes segment metadata + image URLs and calls
    the existing Grok Imagine client (image_client.generate_video).
    Does NOT modify the Grok client code.
    """

    COST_PER_CLIP = 0.10  # Grok Imagine cost

    def __init__(
        self,
        image_client,
        airtable_client,
        google_client,
    ):
        self.image_client = image_client
        self.airtable = airtable_client
        self.google = google_client

    async def run(
        self,
        video_title: str,
        config: VideoConfig,
        project_folder_id: str,
    ) -> dict:
        """Animate all pending images for a video.

        Args:
            video_title: Airtable Video Title to match image records.
            config: VideoConfig with clip_duration_seconds.
            project_folder_id: Google Drive folder for uploads.

        Returns:
            Dict with clips_generated, clips_failed, actual_cost.
        """
        clip_duration = config.clip_duration_seconds

        # Fetch done images that still need animation
        all_images = self.airtable.get_all_images_for_video(video_title)
        done_images = [
            img for img in all_images
            if img.get("Status") == "Done" and not img.get("Video Clip URL")
        ]

        if not done_images:
            print("  ✅ All images already animated (or none ready)")
            return {"clips_generated": 0, "clips_failed": 0, "actual_cost": 0.0}

        # Sort by scene + image index for deterministic order
        done_images.sort(
            key=lambda x: (x.get("Scene", 0), x.get("Image Index", 0))
        )

        total = len(done_images)
        estimated_cost = total * self.COST_PER_CLIP
        print(f"  Images to animate: {total}")
        print(f"  Clip duration: {clip_duration}s")
        print(f"  Estimated cost: ${estimated_cost:.2f}")

        clips_generated = 0
        clips_failed = 0
        actual_cost = 0.0

        for i, img_record in enumerate(done_images, 1):
            scene = img_record.get("Scene", 0)
            index = img_record.get("Image Index", 0)
            record_id = img_record["id"]

            print(f"\n  [{i}/{total}] Scene {scene}, Image {index}")

            # 1. Get image URL (prefer permanent Drive URL)
            image_url = self._get_image_url(img_record)
            if not image_url:
                print("    ⚠️ No image URL, skipping")
                clips_failed += 1
                continue

            # Convert to direct download URL for Grok
            direct_url = self.google.get_direct_drive_url(image_url)

            # 2. Build animation prompt from segment metadata
            animation_prompt = self._build_prompt(img_record, clip_duration)
            print(f"    Prompt: {animation_prompt[:80]}...")

            # 3. Mark as processing
            self.airtable.update_image_animation_fields(
                record_id,
                animation_status="Processing",
                video_duration=clip_duration,
            )

            # 4. Call Grok Imagine via the existing client
            print(f"    Generating {clip_duration}s clip...")
            video_url = await self.image_client.generate_video(
                direct_url,
                animation_prompt,
                duration=clip_duration,
            )

            if video_url:
                # 5. Download and upload to Drive
                print("    Downloading clip...")
                video_content = await self.image_client.download_image(video_url)

                filename = f"Clip_S{str(scene).zfill(2)}_{str(index).zfill(2)}.mp4"
                print(f"    Uploading {filename} to Drive...")
                drive_file = self.google.upload_video(
                    video_content, filename, project_folder_id
                )
                drive_url = self.google.make_file_public(drive_file["id"])

                # 6. Update Airtable
                self.airtable.update_image_animation_fields(
                    record_id,
                    video_clip_url=drive_url,
                    animation_status="Done",
                    video_duration=clip_duration,
                )

                clips_generated += 1
                actual_cost += self.COST_PER_CLIP
                print(f"    ✅ Done (${actual_cost:.2f} total)")
            else:
                self.airtable.update_image_animation_fields(
                    record_id,
                    animation_status="Failed",
                )
                clips_failed += 1
                print("    ❌ Generation failed")

        print(f"\n  ✅ Animation complete: {clips_generated}/{total} clips")
        print(f"     Cost: ${actual_cost:.2f}")

        return {
            "clips_generated": clips_generated,
            "clips_failed": clips_failed,
            "actual_cost": round(actual_cost, 2),
        }

    def _get_image_url(self, img_record: dict) -> Optional[str]:
        """Extract the best image URL from a record (Drive URL preferred)."""
        drive_url = img_record.get("Drive Image URL")
        if drive_url:
            return drive_url

        attachments = img_record.get("Image", [])
        if attachments and isinstance(attachments, list):
            return attachments[0].get("url")

        return None

    def _build_prompt(self, img_record: dict, clip_duration: int) -> str:
        """Build an animation prompt for a single image record.

        Uses the animation_prompt_engine if intensity metadata exists on the
        record. Falls back to the Video Prompt field (legacy) or a default.
        """
        # If there's already a Video Prompt from the old pipeline, use it
        existing_prompt = img_record.get("Video Prompt")
        if existing_prompt:
            return existing_prompt

        # Build from segment metadata via animation_prompt_engine
        intensity = img_record.get("Intensity", "low")
        if isinstance(intensity, str):
            intensity = intensity.lower()
        if intensity not in ("low", "medium", "high"):
            intensity = "low"

        content_type = img_record.get("Content Type", "")

        segment = {"intensity": intensity, "index": img_record.get("Image Index", 0)}
        return generate_animation_prompt(segment, content_type, clip_duration)
