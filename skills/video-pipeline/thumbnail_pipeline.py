"""Thumbnail Generator Pipeline for Video Production.

This module orchestrates the automated thumbnail generation process:
1. Analyze reference image (Gemini)
2. Generate image prompt (Anthropic)
3. Create thumbnail (Kie API)
4. Update Airtable

Usage:
    pipeline = ThumbnailPipeline()
    result = await pipeline.run(video_id="rec...")
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from clients.airtable_client import AirtableClient
from clients.gemini_client import GeminiClient
from clients.anthropic_client import AnthropicClient
from clients.image_client import ImageClient
from clients.slack_client import SlackClient


class ThumbnailPipeline:
    """Orchestrates the thumbnail generation pipeline."""

    def __init__(self):
        """Initialize all clients."""
        self.airtable = AirtableClient()
        self.gemini = GeminiClient()
        self.anthropic = AnthropicClient()
        self.image = ImageClient()

        # Optional Slack notifications
        try:
            self.slack = SlackClient()
        except Exception:
            self.slack = None

    async def run(self, video_id: str) -> dict:
        """Run the full thumbnail generation pipeline for a video.

        Args:
            video_id: Airtable record ID for the video idea

        Returns:
            Dict with pipeline results:
            - success: bool
            - thumbnail_url: str (if successful)
            - error: str (if failed)
        """
        print(f"\n{'='*60}")
        print(f"🖼️  THUMBNAIL GENERATOR PIPELINE")
        print(f"{'='*60}")

        try:
            # Step 0: Get video data from Airtable
            print("\n📋 Step 0: Fetching video data from Airtable...")
            idea = self.airtable.get_idea_with_reference_thumbnail(video_id)

            video_title = idea.get("video_title")
            thumbnail_prompt = idea.get("thumbnail_prompt")
            reference_url = idea.get("reference_thumbnail_url")
            video_summary = idea.get("video_summary", thumbnail_prompt)

            print(f"    Video Title: {video_title}")
            print(f"    Thumbnail Prompt: {thumbnail_prompt[:80]}..." if thumbnail_prompt else "    Thumbnail Prompt: (none)")
            print(f"    Reference URL: {reference_url[:60]}..." if reference_url else "    Reference URL: (none)")

            if not video_title:
                return {"success": False, "error": "Video title is required"}

            if not reference_url:
                return {"success": False, "error": "Reference thumbnail URL is required"}

            if not thumbnail_prompt:
                thumbnail_prompt = video_title  # Fallback to title

            # Step 1: Analyze reference image with Gemini
            print("\n🔍 Step 1: Analyzing reference image with Gemini...")
            thumbnail_spec = await self.gemini.analyze_reference_thumbnail(
                image_url=reference_url,
                video_title=video_title,
                video_summary=video_summary,
            )
            print(f"    ✅ THUMBNAIL_SPEC extracted successfully")
            print(f"    Style: {thumbnail_spec.get('style_fingerprint', {}).get('render_style', 'unknown')}")
            print(f"    Has text: {thumbnail_spec.get('has_text', False)}")

            # Step 2: Generate image prompt with Anthropic
            print("\n✍️  Step 2: Generating image prompt with Anthropic...")
            image_prompt = await self.anthropic.generate_thumbnail_prompt(
                video_title=video_title,
                thumbnail_prompt=thumbnail_prompt,
                thumbnail_spec=thumbnail_spec,
            )
            print(f"    ✅ Image prompt generated")
            print(f"    Prompt: {image_prompt[:150]}...")

            # Step 3: Generate thumbnail with Kie API
            print("\n🎨 Step 3: Generating thumbnail with Kie API...")
            thumbnail_url = await self.image.generate_thumbnail(
                prompt=image_prompt,
                aspect_ratio="16:9",
                resolution="2K",
            )

            if not thumbnail_url:
                return {"success": False, "error": "Thumbnail generation failed"}

            print(f"    ✅ Thumbnail generated: {thumbnail_url[:60]}...")

            # Step 4: Update Airtable
            print("\n💾 Step 4: Updating Airtable...")
            updated = self.airtable.update_idea_thumbnail_complete(
                record_id=video_id,
                thumbnail_url=thumbnail_url,
                next_status="Thumbnail Complete",
            )
            print(f"    ✅ Airtable updated")
            print(f"    Status: {updated.get('Status', 'unknown')}")

            # Optional: Send Slack notification
            if self.slack:
                try:
                    self.slack.notify_thumbnail_complete(video_title, thumbnail_url)
                except Exception as e:
                    print(f"    ⚠️ Slack notification failed: {e}")

            print(f"\n{'='*60}")
            print(f"✅ THUMBNAIL PIPELINE COMPLETE")
            print(f"{'='*60}")

            return {
                "success": True,
                "thumbnail_url": thumbnail_url,
                "video_title": video_title,
                "record_id": video_id,
            }

        except Exception as e:
            error_msg = str(e)
            print(f"\n❌ Pipeline error: {error_msg}")

            if self.slack:
                try:
                    self.slack.notify_error("Thumbnail Pipeline", error_msg)
                except Exception:
                    pass

            return {"success": False, "error": error_msg}

    async def run_next(self) -> Optional[dict]:
        """Run thumbnail generation for the next video in queue.

        Finds the next video with status "Ready For Thumbnail" and processes it.

        Returns:
            Pipeline result dict, or None if no videos ready
        """
        print("\n🔎 Looking for videos ready for thumbnail generation...")

        ideas = self.airtable.get_ideas_ready_for_thumbnail(limit=1)

        if not ideas:
            print("    No videos found with status 'Ready For Thumbnail'")
            return None

        idea = ideas[0]
        video_id = idea["id"]
        video_title = idea.get("Video Title", "Unknown")

        print(f"    Found: {video_title} ({video_id})")

        return await self.run(video_id)
