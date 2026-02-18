"""
Video Production Pipeline Orchestrator

STATUS-DRIVEN WORKFLOW:
The pipeline strictly follows Airtable Ideas table status:
1. Idea Logged            - New idea, waiting to be picked up
2. Ready For Scripting    - Script Bot will run
3. Ready For Voice        - Voice Bot will run
4. Ready For Image Prompts - Image Prompt Bot will run
5. Ready For Images       - Image Bot will run
6. Ready For Video Scripts - Video Script Bot will run
7. Ready For Video Generation - Video Gen Bot will run
8. Ready For Thumbnail    - Thumbnail Bot will run
9. Done                   - Complete, do NOT process
10. In Que                - Waiting in queue

RULES:
- Always check Ideas table status FIRST
- Only process ONE video at a time
- Each bot checks for its required status before running
"""

import os
import asyncio
import json
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from clients.anthropic_client import AnthropicClient
from clients.airtable_client import AirtableClient
from clients.google_client import GoogleClient
from clients.slack_client import SlackClient
from clients.elevenlabs_client import ElevenLabsClient
from clients.image_client import ImageClient
from clients.gemini_client import GeminiClient
from clients.apify_client import ApifyYouTubeClient
from bots.idea_bot import IdeaBot
from bots.trending_idea_bot import TrendingIdeaBot


class VideoPipeline:
    """Orchestrates the full video production pipeline based on Airtable status."""
    
    # Image generation mode:
    # - "semantic": Smart segmentation by visual concept (max 10s per segment for AI video)
    # - "sentence": One image per sentence (deprecated)
    # - "scene": Old mode with hardcoded 6 images per scene (deprecated)
    IMAGE_MODE = os.getenv("IMAGE_MODE", "semantic")
    
    # Valid statuses in workflow order
    STATUS_IDEA_LOGGED = "Idea Logged"
    STATUS_READY_SCRIPTING = "Ready For Scripting"
    STATUS_READY_VOICE = "Ready For Voice"
    STATUS_READY_IMAGE_PROMPTS = "Ready For Image Prompts"
    STATUS_READY_IMAGES = "Ready For Images"
    STATUS_READY_VIDEO_SCRIPTS = "Ready For Video Scripts"
    STATUS_READY_VIDEO_GENERATION = "Ready For Video Generation"
    STATUS_READY_THUMBNAIL = "Ready For Thumbnail"
    STATUS_DONE = "Done"
    STATUS_READY_TO_RENDER = "Ready To Render"
    STATUS_IN_QUE = "In Que"
    
    def __init__(self):
        """Initialize all API clients."""
        self.anthropic = AnthropicClient()
        self.airtable = AirtableClient()
        self.google = GoogleClient()
        self.slack = SlackClient()
        self.elevenlabs = ElevenLabsClient()
        self.gemini = GeminiClient()
        # Pass google client for proxy logic
        self.image_client = ImageClient(google_client=self.google)
        # Apify for YouTube scraping (optional - may not have API key)
        try:
            self.apify = ApifyYouTubeClient()
        except ValueError:
            self.apify = None  # No API key configured
        
        # Pipeline state - ALWAYS set from Ideas table
        self.project_folder_id: Optional[str] = None
        self.google_doc_id: Optional[str] = None
        self.video_title: Optional[str] = None
        self.current_idea_id: Optional[str] = None
        self.current_idea: Optional[dict] = None
        self.core_image_url: Optional[str] = None
    
    def get_idea_by_status(self, status: str) -> Optional[dict]:
        """Get ONE idea with the specified status."""
        ideas = self.airtable.get_ideas_by_status(status, limit=1)
        if ideas:
            return ideas[0]
        return None
    
    def _load_idea(self, idea: dict):
        """Load idea data into pipeline state."""
        self.current_idea = idea
        self.current_idea_id = idea.get("id")
        self.video_title = idea.get("Video Title", "Untitled")

        # Extract Core Image URL from the idea/project record
        core_image_attachments = idea.get("Core Image", [])
        if core_image_attachments and isinstance(core_image_attachments, list):
            self.core_image_url = core_image_attachments[0].get("url", "")
        else:
            self.core_image_url = ""

        print(f"\n📌 Loaded idea: {self.video_title}")
        print(f"   Status: {idea.get('Status')}")
        print(f"   ID: {self.current_idea_id}")
        if self.core_image_url:
            print(f"   🖼️ Core Image: {self.core_image_url[:80]}...")
        else:
            print(f"   ℹ️ No Core Image — YouTube pipeline uses text-to-image (no reference needed)")

    def _extract_youtube_thumbnail(self, url: str) -> Optional[str]:
        """Extract thumbnail image URL from a YouTube video URL.

        Args:
            url: YouTube video URL (various formats supported)

        Returns:
            Direct URL to the thumbnail image, or None if not a YouTube URL
        """
        import re

        # Patterns to extract video ID from various YouTube URL formats
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/v/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        ]

        video_id = None
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break

        if not video_id:
            return None

        # Return maxresdefault thumbnail (highest quality)
        # Falls back gracefully if not available
        return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

    def check_existing_work(self, video_title: str) -> dict:
        """Check what work has already been done for this video.
        
        Returns dict with:
            - scripts_exist: bool
            - script_count: int
            - scripts_finished: int (with voice)
            - scripts_to_voice: list (scripts needing voice)
            - images_exist: bool
            - image_count: int
            - images_pending: int
            - suggested_status: what status the idea SHOULD be at
        """
        # Check scripts
        scripts = self.airtable.get_scripts_by_title(video_title)
        scripts_finished = [s for s in scripts if s.get("Script Status") == "Finished"]
        scripts_to_voice = [s for s in scripts if s.get("Script Status") == "Create"]
        
        # Check images
        all_images = self.airtable.get_all_images_for_video(video_title)
        pending_images = [img for img in all_images if img.get("Status") == "Pending"]
        done_images = [img for img in all_images if img.get("Status") == "Done"]
        
        # Check videos (images with Video) - CONSTRAINT: Scene 1 only for now
        # We define "Video Work" as done based on Scene 1 completeness
        scene_1_images = [img for img in done_images if img.get("Scene") == 1]
        scene_1_prompts = [img for img in scene_1_images if img.get("Video Prompt")]
        # Check 'Video' field (list of attachments)
        scene_1_videos = [img for img in scene_1_images if img.get("Video")]
        
        # Determine what status this video should be at
        suggested_status = None
        if not scripts:
            suggested_status = self.STATUS_READY_SCRIPTING
        elif scripts_to_voice:
            # Some scripts still need voice
            suggested_status = self.STATUS_READY_VOICE
        elif not all_images:
            # Scripts done, no images yet - need to generate prompts first
            suggested_status = self.STATUS_READY_IMAGE_PROMPTS
        elif pending_images:
            # Image prompts exist but images pending
            suggested_status = self.STATUS_READY_IMAGES
        elif len(scene_1_images) > 0 and len(scene_1_prompts) < len(scene_1_images):
            # Images done, but Scene 1 prompts missing
            suggested_status = self.STATUS_READY_VIDEO_SCRIPTS
        elif len(scene_1_prompts) > 0 and len(scene_1_videos) < len(scene_1_prompts):
            # Prompts done, but Scene 1 videos missing
            suggested_status = self.STATUS_READY_VIDEO_GENERATION
        elif all_images and not pending_images:
            # All images done (and video steps satisfied for Scene 1)
            suggested_status = self.STATUS_READY_THUMBNAIL
        
        return {
            "scripts_exist": len(scripts) > 0,
            "script_count": len(scripts),
            "scripts_finished": len(scripts_finished),
            "scripts_to_voice": scripts_to_voice,
            "images_exist": len(all_images) > 0,
            "image_count": len(all_images),
            "images_pending": len(pending_images),
            "images_done": len(done_images),
            "suggested_status": suggested_status,
        }

    # ==========================================================================
    # ANIMATION PIPELINE - Hero shot detection and cost estimation
    # ==========================================================================

    # Animation pipeline configuration
    MANUAL_ONLY_VIDEO_GEN = True  # Requires explicit --animate command (cost control)
    COST_PER_VIDEO_CLIP = 0.10    # $0.10 per clip via Kie.ai

    def identify_hero_shots(self, images: list[dict], max_heroes: int = 3) -> list[str]:
        """Identify which images should be hero shots (10s animated clips).

        Hero shots are high-impact moments that receive longer video treatment.

        Rules:
        1. Maximum 3 hero shots per video (if everything is special, nothing is)
        2. Never consecutive (minimum 2 images gap for pacing contrast)
        3. Priority selection:
           - Scene 1 opener (hook moment)
           - Key data reveals (keywords: collapse, crash, billion, prediction)
           - Final scene reveal (ending with impact)

        Args:
            images: List of image records from Airtable
            max_heroes: Maximum number of hero shots allowed

        Returns:
            List of image record IDs that should be hero shots
        """
        hero_ids = []

        # Sort by scene and index
        sorted_images = sorted(
            images,
            key=lambda x: (x.get("Scene", 0), x.get("Image Index", 0))
        )

        if not sorted_images:
            return []

        def get_image_position(img_id):
            """Get the position of an image in the sorted list."""
            for i, img in enumerate(sorted_images):
                if img["id"] == img_id:
                    return i
            return -1

        def is_consecutive_with_existing(img_id):
            """Check if adding this hero would violate the consecutive rule."""
            if not hero_ids:
                return False
            curr_pos = get_image_position(img_id)
            for hero_id in hero_ids:
                hero_pos = get_image_position(hero_id)
                if abs(curr_pos - hero_pos) < 3:  # Need 2+ images gap
                    return True
            return False

        # Rule 1: First image of Scene 1 (opening hook)
        scene_1_images = [img for img in sorted_images if img.get("Scene") == 1]
        if scene_1_images:
            hero_ids.append(scene_1_images[0]["id"])

        # Rule 2: Key data reveals (keywords indicate high-impact moments)
        data_keywords = ["collapse", "crash", "billion", "trillion", "percent", "2030", "prediction", "warning"]
        for img in sorted_images:
            if len(hero_ids) >= max_heroes:
                break
            segment_text = img.get("Sentence Text", "").lower()
            if any(kw in segment_text for kw in data_keywords):
                if not is_consecutive_with_existing(img["id"]) and img["id"] not in hero_ids:
                    hero_ids.append(img["id"])

        # Rule 3: Final reveal (last image of final scene)
        if len(hero_ids) < max_heroes:
            last_scene = max((img.get("Scene", 0) for img in sorted_images), default=0)
            final_images = [img for img in sorted_images if img.get("Scene") == last_scene]
            if final_images:
                final_img = final_images[-1]
                if not is_consecutive_with_existing(final_img["id"]) and final_img["id"] not in hero_ids:
                    hero_ids.append(final_img["id"])

        return hero_ids[:max_heroes]

    def estimate_video_generation_cost(self, video_title: str = None) -> dict:
        """Estimate the cost of video generation for a video.

        Args:
            video_title: Title of video to estimate (uses current if None)

        Returns:
            Dict with cost breakdown:
            - total_images: int
            - hero_shots: int
            - standard_shots: int
            - total_cost: float
        """
        title = video_title or self.video_title
        if not title:
            return {"error": "No video title specified"}

        images = self.airtable.get_all_images_for_video(title)
        done_images = [img for img in images if img.get("Status") == "Done"]

        # Identify hero shots
        hero_ids = self.identify_hero_shots(done_images)

        hero_count = len(hero_ids)
        standard_count = len(done_images) - hero_count

        # Cost calculation (same rate for 6s and 10s via Kie.ai)
        total_cost = len(done_images) * self.COST_PER_VIDEO_CLIP

        return {
            "video_title": title,
            "total_images": len(done_images),
            "hero_shots": hero_count,
            "standard_shots": standard_count,
            "total_cost": round(total_cost, 2),
            "hero_duration": "10s each",
            "standard_duration": "6s each",
            "hero_ids": hero_ids,
        }

    async def run_video_animation_pipeline(
        self,
        scene_filter: int = None,
        heroes_only: bool = False,
    ) -> dict:
        """Generate video clips for images with full animation workflow.

        This unified method handles:
        1. Identifying hero shots (10s duration vs 6s standard)
        2. Generating shot-type-aware video prompts
        3. Generating video clips via Grok Imagine
        4. Uploading to Google Drive
        5. Updating Airtable with results

        Args:
            scene_filter: If set, only process this scene number
            heroes_only: If True, only generate hero shot videos (max 3, cost-effective testing)

        Returns:
            Dict with generation results
        """
        from clients.style_engine import SceneType, get_scene_type_for_segment

        print(f"\n🎬 VIDEO ANIMATION PIPELINE: Processing '{self.video_title}'")

        # Get all done images
        all_images = self.airtable.get_all_images_for_video(self.video_title)
        done_images = [img for img in all_images if img.get("Status") == "Done"]

        # Apply scene filter
        if scene_filter:
            done_images = [img for img in done_images if img.get("Scene") == scene_filter]
            print(f"  Filtered to Scene {scene_filter}: {len(done_images)} images")

        # Identify hero shots
        hero_ids = self.identify_hero_shots(done_images)
        print(f"  Hero shots identified: {len(hero_ids)}")

        # Filter to heroes only if requested
        if heroes_only:
            done_images = [img for img in done_images if img["id"] in hero_ids]
            print(f"  Heroes-only mode: {len(done_images)} images")

        # Skip images that already have video clips
        images_to_process = [img for img in done_images if not img.get("Video")]
        print(f"  Images needing video: {len(images_to_process)}")

        if not images_to_process:
            print("  ✅ All images already have videos")
            return {"videos_generated": 0, "actual_cost": 0, "status": "complete"}

        # Ensure project folder exists
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]

        videos_generated = 0
        actual_cost = 0.0

        for i, img_record in enumerate(images_to_process, 1):
            scene = img_record.get("Scene", 0)
            index = img_record.get("Image Index", 0)
            is_hero = img_record["id"] in hero_ids
            duration = 10 if is_hero else 6

            hero_marker = " (HERO 10s)" if is_hero else " (6s)"
            print(f"\n  [{i}/{len(images_to_process)}] Scene {scene}, Image {index}{hero_marker}")

            # Get image URL - prefer Drive URL (permanent)
            drive_url = img_record.get("Drive Image URL")
            if not drive_url:
                image_attachments = img_record.get("Image", [])
                drive_url = image_attachments[0].get("url") if image_attachments else None

            if not drive_url:
                print("    ⚠️ No image URL found, skipping")
                continue

            # Convert to direct download URL for Grok Imagine
            direct_url = self.google.get_direct_drive_url(drive_url)

            # Determine shot type from segment position
            scene_images = [im for im in done_images if im.get("Scene") == scene]
            total_in_scene = len(scene_images)
            try:
                scene_type, camera_role = get_scene_type_for_segment(
                    index - 1,  # 0-based
                    total_in_scene,
                    None
                )
                scene_type_str = scene_type.value
            except Exception:
                scene_type_str = None
                camera_role = None

            # Generate video prompt if not exists
            video_prompt = img_record.get("Video Prompt")
            if not video_prompt:
                print("    Generating video prompt...")
                image_prompt = img_record.get("Image Prompt", "")
                sentence_text = img_record.get("Sentence Text", "")

                video_prompt = await self.anthropic.generate_video_prompt(
                    image_prompt=image_prompt,
                    sentence_text=sentence_text,
                    scene_type=scene_type_str,
                    is_hero_shot=is_hero,
                )

                # Save prompt to Airtable
                self.airtable.update_image_video_prompt(img_record["id"], video_prompt)

            print(f"    Motion: {video_prompt[:60]}...")
            print(f"    Generating {duration}s video...")

            # Update status to processing
            self.airtable.update_image_animation_fields(
                img_record["id"],
                shot_type=scene_type_str.upper() if scene_type_str else None,
                is_hero_shot=is_hero,
                animation_status="Processing",
                video_duration=duration,
            )

            # Generate video via Grok Imagine
            video_url = await self.image_client.generate_video(
                direct_url,
                video_prompt,
                duration=duration,
            )

            if video_url:
                # Download and upload to Drive
                print("    Downloading video...")
                video_content = await self.image_client.download_image(video_url)

                filename = f"Scene_{str(scene).zfill(2)}_{str(index).zfill(2)}.mp4"
                print(f"    Uploading {filename} to Drive...")
                drive_file = self.google.upload_video(video_content, filename, self.project_folder_id)
                video_drive_url = self.google.make_file_public(drive_file["id"])

                # Update Airtable
                self.airtable.update_image_video_url(img_record["id"], video_url)
                self.airtable.update_image_animation_fields(
                    img_record["id"],
                    video_clip_url=video_drive_url,
                    animation_status="Done",
                )

                videos_generated += 1
                actual_cost += self.COST_PER_VIDEO_CLIP
                print("    ✅ Video saved!")
            else:
                self.airtable.update_image_animation_fields(
                    img_record["id"],
                    animation_status="Failed",
                )
                print("    ❌ Video generation failed")

        print(f"\n✅ Generated {videos_generated} videos")
        print(f"   Actual cost: ${actual_cost:.2f}")

        return {
            "videos_generated": videos_generated,
            "actual_cost": round(actual_cost, 2),
            "total_attempted": len(images_to_process),
            "status": "complete",
        }

    async def run_next_step(self) -> dict:
        """Run the next step based on what's in the Ideas table.

        This is the MAIN entry point. It checks which video needs processing
        and runs the appropriate bot.

        Returns dict with:
            - On success: bot, video_title, new_status, etc.
            - On failure: status="failed", error=<message>
            - On idle: status="idle"
        """
        # Check each status in workflow order

        # 1. Check for Ready For Scripting
        idea = self.get_idea_by_status(self.STATUS_READY_SCRIPTING)
        if idea:
            self._load_idea(idea)
            # CHECK: Has work already been done?
            work_status = self.check_existing_work(self.video_title)
            suggested = work_status["suggested_status"]

            if suggested and suggested != self.STATUS_READY_SCRIPTING:
                print(f"  ⚠️ Found existing work! Fast-forwarding status to: {suggested}")
                self.airtable.update_idea_status(self.current_idea_id, suggested)
                # Restart loop to pick up new status
                return await self.run_next_step()

            return await self._run_step_safe("Script Bot", self.run_script_bot)

        # 2. Check for Ready For Voice
        idea = self.get_idea_by_status(self.STATUS_READY_VOICE)
        if idea:
            self._load_idea(idea)
            # CHECK: Has work already been done?
            work_status = self.check_existing_work(self.video_title)
            suggested = work_status["suggested_status"]

            if suggested and suggested != self.STATUS_READY_VOICE:
                print(f"  ⚠️ Found existing work! Fast-forwarding status to: {suggested}")
                self.airtable.update_idea_status(self.current_idea_id, suggested)
                return await self.run_next_step()

            return await self._run_step_safe("Voice Bot", self.run_voice_bot)

        # 3. Check for Ready For Image Prompts (use styled prompts as primary path)
        idea = self.get_idea_by_status(self.STATUS_READY_IMAGE_PROMPTS)
        if idea:
            self._load_idea(idea)
            # CHECK: Has work already been done?
            work_status = self.check_existing_work(self.video_title)
            suggested = work_status["suggested_status"]

            if suggested and suggested != self.STATUS_READY_IMAGE_PROMPTS:
                print(f"  ⚠️ Found existing work! Fast-forwarding status to: {suggested}")
                self.airtable.update_idea_status(self.current_idea_id, suggested)
                return await self.run_next_step()

            return await self._run_step_safe("Image Prompt Bot", self.run_styled_image_prompts)

        # 4. Check for Ready For Images
        idea = self.get_idea_by_status(self.STATUS_READY_IMAGES)
        if idea:
            self._load_idea(idea)
            # CHECK: Has work already been done?
            work_status = self.check_existing_work(self.video_title)
            suggested = work_status["suggested_status"]

            if suggested and suggested != self.STATUS_READY_IMAGES:
                print(f"  ⚠️ Found existing work! Fast-forwarding status to: {suggested}")
                self.airtable.update_idea_status(self.current_idea_id, suggested)
                return await self.run_next_step()

            return await self._run_step_safe("Image Bot", self.run_image_bot)

        # 5. SKIPPED - Video Scripts (manual only, costly at $0.10/image)
        # idea = self.get_idea_by_status(self.STATUS_READY_VIDEO_SCRIPTS)
        # if idea:
        #     self._load_idea(idea)
        #     return await self.run_video_script_bot()

        # 6. SKIPPED - Video Generation (manual only, costly at $0.10/image)
        # idea = self.get_idea_by_status(self.STATUS_READY_VIDEO_GENERATION)
        # if idea:
        #     self._load_idea(idea)
        #     return await self.run_video_gen_bot()
        # 7. Check for Ready For Thumbnail
        idea = self.get_idea_by_status(self.STATUS_READY_THUMBNAIL)
        if idea:
            self._load_idea(idea)
            # CHECK: Has work already been done?
            work_status = self.check_existing_work(self.video_title)
            suggested = work_status["suggested_status"]

            if suggested and suggested != self.STATUS_READY_THUMBNAIL:
                print(f"  ⚠️ Found existing work! Fast-forwarding status to: {suggested}")
                self.airtable.update_idea_status(self.current_idea_id, suggested)
                return await self.run_next_step()

            return await self._run_step_safe("Thumbnail Bot", self.run_thumbnail_bot)

        # 8. Render Bot — one at a time, cleans assets between renders
        idea = self.get_idea_by_status(self.STATUS_READY_TO_RENDER)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Render Bot", self.run_render_bot)

        # No work to do
        print("\n✅ No videos ready for processing!")
        print("   To process a video, update its status in the Ideas table.")
        return {"status": "idle", "message": "No videos to process"}

    async def _run_step_safe(self, bot_name: str, step_fn) -> dict:
        """Run a pipeline step with error handling.

        Catches any unhandled exception and returns a failure dict
        instead of crashing the pipeline.
        """
        try:
            result = await step_fn()
            # Check if the bot itself reported failure
            if result.get("error") and not result.get("status"):
                result["status"] = "failed"
                result.setdefault("bot", bot_name)
                result.setdefault("video_title", self.video_title)
            return result
        except Exception as e:
            error_msg = f"{bot_name} crashed: {e}"
            print(f"\n❌ {error_msg}")
            self.slack.send_message(
                f"❌ *{bot_name} CRASHED* for *{self.video_title}*\n"
                f"```{e}```\n"
                f"Status NOT advanced. Fix and re-run."
            )
            return {
                "status": "failed",
                "bot": bot_name,
                "video_title": self.video_title,
                "error": error_msg,
            }

    async def run_idea_bot(self, input_text: str) -> dict:
        """Generate video ideas from a YouTube URL or concept.

        This is the FIRST step in the pipeline - generates 3 video concepts.

        Args:
            input_text: Either a YouTube URL or a topic/concept description

        Returns:
            Dict with generated ideas and their Airtable IDs
        """
        print("\n" + "=" * 60)
        print("💡 IDEA BOT - Generating Video Concepts")
        print("=" * 60)

        idea_bot = IdeaBot(
            anthropic_client=self.anthropic,
            airtable_client=self.airtable,
            gemini_client=self.gemini,
            slack_client=self.slack,
        )

        ideas = await idea_bot.generate_ideas(
            input_text=input_text,
            save_to_airtable=True,
            notify_slack=True,
        )

        print("\n" + "=" * 60)
        print("✅ IDEA BOT COMPLETE")
        print("=" * 60)
        print(f"Generated {len(ideas)} ideas:")
        for i, idea in enumerate(ideas, 1):
            print(f"  {i}. {idea.get('viral_title', 'Untitled')}")
        print("\nNext steps:")
        print("  1. Review ideas in Airtable")
        print("  2. Set your chosen idea's status to 'Ready For Scripting'")
        print("  3. Run: python pipeline.py")

        return {
            "status": "ideas_generated",
            "count": len(ideas),
            "ideas": [idea.get("viral_title") for idea in ideas],
        }

    async def run_trending_idea_bot(
        self,
        search_queries: Optional[list[str]] = None,
        num_ideas: int = 3,
    ) -> dict:
        """Generate video ideas by analyzing trending YouTube content.

        This scrapes trending videos in the finance/economy niche,
        analyzes title patterns, and generates modeled concepts.

        Args:
            search_queries: Custom search terms (or use defaults)
            num_ideas: Number of ideas to generate

        Returns:
            Dict with trending analysis and generated ideas
        """
        if not self.apify:
            return {"error": "Apify API key not configured. Add APIFY_API_KEY to .env"}

        trending_bot = TrendingIdeaBot(
            apify_client=self.apify,
            anthropic_client=self.anthropic,
            airtable_client=self.airtable,
            gemini_client=self.gemini,
            slack_client=self.slack,
        )

        result = await trending_bot.generate_from_trending(
            search_queries=search_queries,
            num_ideas=num_ideas,
            save_to_airtable=True,
            notify_slack=True,
        )

        return {
            "status": "trending_ideas_generated",
            "videos_analyzed": len(result.get("trending_data", {}).get("videos", [])),
            "ideas": [idea.get("viral_title") for idea in result.get("ideas", [])],
        }

    async def run_script_bot(self) -> dict:
        """Write the full script (legacy 20-scene path).
        
        REQUIRES: Ideas status = "Ready For Scripting"
        UPDATES TO: "Ready For Voice" when complete
        """
        # Verify status
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_SCRIPTING)
            if not idea:
                return {"error": "No idea with status 'Ready For Scripting'"}
            self._load_idea(idea)
        
        if self.current_idea.get("Status") != self.STATUS_READY_SCRIPTING:
            return {"error": f"Idea status is '{self.current_idea.get('Status')}', expected 'Ready For Scripting'"}
        
        self.slack.notify_script_start()
        print(f"\n📝 SCRIPT BOT: Processing '{self.video_title}'")
        
        # Create project folder in Google Drive
        folder = self.google.create_folder(self.video_title)
        self.project_folder_id = folder["id"]

        # Create Google Doc for script (graceful fallback if API unavailable)
        doc = self.google.create_document(self.video_title, self.project_folder_id)
        self.google_doc_id = doc["id"]  # May be None if unavailable
        docs_available = not doc.get("unavailable", False)
        if not docs_available:
            print("  ⚠️  Google Docs unavailable - scripts will be saved to Airtable only")
        
        # Generate beat sheet
        beat_sheet = await self.anthropic.generate_beat_sheet(self.current_idea)
        scenes = beat_sheet.get("script_outline", [])
        
        # Get existing scripts for this video
        existing_scripts = self.airtable.get_scripts_by_title(self.video_title)
        existing_scenes = {s.get("scene"): s for s in existing_scripts}
        
        # Write each scene
        for scene in scenes:
            scene_number = scene.get("scene_number", 0)
            scene_beat = scene.get("beat", "")
            
            # CHECK: Does script already exist?
            if scene_number in existing_scenes:
                print(f"  Check: Scene {scene_number} already exists, skipping generation.")
                # We still need to append to the doc if we're rebuilding it, 
                # but let's assume the doc usually exists if the script does.
                # If we really wanted to be robust, we'd check if it's in the doc.
                # For now, just skip the generation step.
                continue
            
            print(f"  Writing scene {scene_number}...")
            
            # Generate scene narration
            scene_text = await self.anthropic.write_scene(
                scene_number=scene_number,
                scene_beat=scene_beat,
                video_title=self.video_title,
            )
            
            # Save to Airtable
            self.airtable.create_script_record(
                scene_number=scene_number,
                scene_text=scene_text,
                title=self.video_title,
            )
            
            # Append to Google Doc
            self.google.append_to_document(
                self.google_doc_id,
                f"**Scene {scene_number}**\n\n{scene_text}",
            )
        
        # UPDATE STATUS to Ready For Voice
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_VOICE)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VOICE}")

        doc_url = self.google.get_document_url(self.google_doc_id)
        self.slack.notify_script_done(doc_url)

        result = {
            "bot": "Script Bot",
            "video_title": self.video_title,
            "folder_id": self.project_folder_id,
            "doc_id": self.google_doc_id,
            "doc_url": doc_url,
            "scene_count": len(scenes),
            "new_status": self.STATUS_READY_VOICE,
        }
        if not docs_available:
            result["warning"] = "Google Docs API unavailable - scripts saved to Airtable only"
        return result
    
    async def run_voice_bot(self) -> dict:
        """Generate voice overs for all scenes.

        REQUIRES: Ideas status = "Ready For Voice"
        UPDATES TO: "Ready For Image Prompts" when complete
        """
        # Verify status
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_VOICE)
            if not idea:
                return {"error": "No idea with status 'Ready For Voice'"}
            self._load_idea(idea)
        
        if self.current_idea.get("Status") != self.STATUS_READY_VOICE:
            return {"error": f"Idea status is '{self.current_idea.get('Status')}', expected 'Ready For Voice'"}
        
        self.slack.notify_voice_start()
        print(f"\n🗣️ VOICE BOT: Processing '{self.video_title}'")
        
        # Get or create project folder
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]
        
        # Get scripts for this video
        scripts = self.airtable.get_scripts_by_title(self.video_title)
        
        if not scripts:
            return {"error": f"No scripts found for: {self.video_title}"}
        
        voice_count = 0
        for script in scripts:
            scene_number = script.get("scene", 0)
            
            # CHECK: Is voice already done?
            if script.get("Script Status") == "Finished":
                print(f"  Check: Scene {scene_number} voice already done, skipping.")
                continue
                
            scene_text = script.get("Scene text", "")
            
            print(f"  Generating voice for scene {scene_number}...")
            
            # Generate voice
            audio_url = await self.elevenlabs.generate_and_wait(scene_text)
            
            if audio_url:
                # Download audio
                audio_content = await self.elevenlabs.download_audio(audio_url)
                
                # Upload to Google Drive
                filename = f"Scene {scene_number}.mp3"
                self.google.upload_audio(audio_content, filename, self.project_folder_id)
                
                # Update Airtable
                self.airtable.mark_script_finished(script["id"], audio_url)
                voice_count += 1
        
        # UPDATE STATUS to Ready For Image Prompts
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_IMAGE_PROMPTS)
        print(f"  ✅ Status updated to: {self.STATUS_READY_IMAGE_PROMPTS}")
        
        self.slack.notify_voice_done()
        
        return {
            "bot": "Voice Bot",
            "video_title": self.video_title,
            "voice_count": voice_count,
            "new_status": self.STATUS_READY_IMAGE_PROMPTS,
        }

    async def run_image_prompt_bot_legacy(self) -> dict:
        """Generate image prompts based on voiceover duration (LEGACY PATH).

        Deprecated: Use run_styled_image_prompts() instead, which uses the
        Visual Identity System (Dossier/Schema/Echo) with the unified scene format.

        Rule: ONE image per 6-10 seconds of voiceover.

        REQUIRES: Ideas status = "Ready For Image Prompts"
        UPDATES TO: "Ready For Images" when complete
        """
        from clients.sentence_utils import get_audio_duration

        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_IMAGE_PROMPTS)
            if not idea:
                return {"status": "idle", "message": "No videos at Ready For Image Prompts"}
            self._load_idea(idea)

        if self.current_idea.get("Status") != self.STATUS_READY_IMAGE_PROMPTS:
            return {"error": f"Status mismatch"}

        print(f"\n🌉 IMAGE PROMPT BOT: Processing '{self.video_title}'")

        scenes = self.airtable.get_scripts_by_title(self.video_title)
        if not scenes:
            return {"error": "No scenes found"}

        print(f"  Found {len(scenes)} scenes")

        # Check for existing image prompts to avoid duplicates
        existing_images = self.airtable.get_all_images_for_video(self.video_title)
        existing_scene_indices = set()
        for img in existing_images:
            key = (img.get("Scene"), img.get("Image Index"))
            existing_scene_indices.add(key)
        
        if existing_images:
            print(f"  Found {len(existing_images)} existing prompts - will skip completed scenes")

        total_prompts = 0

        for scene in scenes:
            scene_number = scene.get("scene") or scene.get("Scene") or 1
            
            # Check if this scene already has prompts
            scene_prompts = [img for img in existing_images if img.get("Scene") == scene_number]
            if scene_prompts:
                print(f"  Scene {scene_number}: Already has {len(scene_prompts)} prompts, skipping...")
                continue
            scene_text = scene.get("Scene text") or scene.get("Script") or ""
            voice_over = scene.get("Voice Over")

            # Get duration from audio file
            voice_duration = None
            if voice_over and isinstance(voice_over, list) and len(voice_over) > 0:
                voice_url = voice_over[0].get("url")
                if voice_url:
                    print(f"  Scene {scene_number}: Fetching audio duration...")
                    voice_duration = get_audio_duration(voice_url)

            # Fallback to word count estimate
            if not voice_duration:
                word_count = len(scene_text.split())
                voice_duration = word_count / 2.5

            # Calculate words per second for this scene
            word_count = len(scene_text.split())
            words_per_second = word_count / voice_duration if voice_duration > 0 else 2.5

            # Target 8 seconds per image (range 6-10)
            target_images = max(1, round(voice_duration / 8))
            min_images = max(1, int(voice_duration / 10))
            max_images = max(1, int(voice_duration / 6))

            # Calculate target words per segment (for 8s at current speaking rate)
            words_per_segment = int(word_count / target_images) if target_images > 0 else word_count

            print(f"  Scene {scene_number}: {voice_duration:.0f}s → {target_images} images (~{words_per_segment} words each)")

            # Call Anthropic to segment into concepts
            # YouTube pipeline uses cinematic dossier style (NOT mannequin)
            concepts = await self.anthropic.segment_scene_into_concepts(
                scene_text=scene_text,
                target_count=target_images,
                min_count=min_images,
                max_count=max_images,
                words_per_segment=words_per_segment,
                scene_number=scene_number,
                pipeline_type="youtube",
            )

            # Create records with calculated durations (capped at 6-10s range)
            cumulative_start = 0.0
            for i, concept in enumerate(concepts):
                concept_text = concept.get("text", "")
                concept_words = len(concept_text.split())
                concept_duration = concept_words / words_per_second if words_per_second > 0 else 8.0

                # ENFORCE 6-10s range - cap at 10s max, floor at 6s min
                concept_duration = max(6.0, min(10.0, concept_duration))

                # Get shot_type from segment (now included in output)
                shot_type = concept.get("shot_type", "medium_human_story")

                # Skip if this exact (scene, index) already exists
                if (scene_number, i + 1) in existing_scene_indices:
                    print(f"      Skipping Scene {scene_number}, Index {i + 1} - already exists")
                    continue

                self.airtable.create_sentence_image_record(
                    scene_number=scene_number,
                    sentence_index=i + 1,
                    sentence_text=concept_text,
                    duration_seconds=round(concept_duration, 1),
                    image_prompt=concept.get("image_prompt", ""),
                    video_title=self.video_title,
                    cumulative_start=round(cumulative_start, 1),
                    aspect_ratio="16:9",
                    shot_type=shot_type,
                )
                cumulative_start += concept_duration
                total_prompts += 1

            print(f"    ✅ Created {len(concepts)} prompts for scene {scene_number}")

            # Slack progress update every 5 scenes
            if scene_number % 5 == 0:
                self.slack.send_message(f"📝 Prompt progress: {total_prompts} prompts created (through Scene {scene_number})")

        # Flag hero shots after all prompts are created
        hero_count = await self._flag_hero_shots()
        print(f"  🌟 Flagged {hero_count} hero shots")

        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_IMAGES)

        print(f"\n  ✅ Total: {total_prompts} image prompts created")

        # Slack completion
        self.slack.send_message(f"✅ Image prompts done: {total_prompts} created for *{self.video_title}*")

        return {
            "bot": "Image Prompt Bot",
            "video_title": self.video_title,
            "prompt_count": total_prompts,
            "hero_count": hero_count,
            "new_status": self.STATUS_READY_IMAGES
        }

    async def _flag_hero_shots(self, max_heroes: int = 3) -> int:
        """Flag 2-3 images per video as hero shots for 10s animation.

        Criteria (flag if ANY match):
        - Shot type is 'pull_back_reveal'
        - Shot type is 'isometric_diorama' (complex detail worth lingering on)
        - Last image in the video sequence

        Constraints:
        - Maximum 3 hero shots per video
        - Never flag consecutive images

        Returns:
            Number of hero shots flagged
        """
        # Get all images for this video (just created)
        all_images = self.airtable.get_all_images_for_video(self.video_title)

        if not all_images:
            return 0

        # Sort by scene and index for proper ordering
        sorted_images = sorted(
            all_images,
            key=lambda x: (x.get("Scene", 0), x.get("Image Index", 0))
        )

        hero_shot_types = ["pull_back_reveal", "isometric_diorama"]
        hero_count = 0
        last_was_hero = False
        total_images = len(sorted_images)

        for i, img in enumerate(sorted_images):
            shot_type = (img.get("Shot Type") or "").lower().strip()
            is_last = (i == total_images - 1)

            should_flag = (
                shot_type in hero_shot_types
                or is_last
            )

            if should_flag and not last_was_hero and hero_count < max_heroes:
                # Flag as hero shot
                self.airtable.update_image_animation_fields(
                    img["id"],
                    is_hero_shot=True,
                )
                hero_count += 1
                last_was_hero = True
                print(f"    🌟 Hero shot: Scene {img.get('Scene')}, Image {img.get('Image Index')} ({shot_type or 'last image'})")
            else:
                # Ensure not flagged
                self.airtable.update_image_animation_fields(
                    img["id"],
                    is_hero_shot=False,
                )
                last_was_hero = False

        return hero_count

    async def run_image_bot(self) -> dict:
        """Generate images from prompts.

        REQUIRES: Ideas status = "Ready For Images"
        UPDATES TO: "Ready For Thumbnail" when ALL images complete
        STOPS pipeline if any images fail or none were generated
        """
        # Verify status
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_IMAGES)
            if not idea:
                return {"error": "No idea with status 'Ready For Images'"}
            self._load_idea(idea)

        if self.current_idea.get("Status") != self.STATUS_READY_IMAGES:
            return {"error": f"Idea status is '{self.current_idea.get('Status')}', expected 'Ready For Images'"}

        print(f"\n🖼️ IMAGE BOT: Processing '{self.video_title}'")

        # Get or create project folder
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]

        # Run the internal image bot
        result = await self._run_image_bot()

        # VERIFY all images are actually complete before advancing status
        all_images = self.airtable.get_all_images_for_video(self.video_title)
        pending = [img for img in all_images if img.get("Status") != "Done" and img.get("Image Prompt")]
        total = len([img for img in all_images if img.get("Image Prompt")])

        if not all_images or total == 0:
            error_msg = f"No images found for '{self.video_title}' — cannot advance status"
            print(f"  ❌ {error_msg}")
            self.slack.send_message(f"❌ Image Bot STOPPED: {error_msg}")
            return {
                "status": "failed",
                "bot": "Image Bot",
                "video_title": self.video_title,
                "error": error_msg,
            }

        if len(pending) > 0:
            error_msg = f"{len(pending)}/{total} images still pending after all retries for '{self.video_title}'"
            print(f"  ❌ {error_msg}")
            self.slack.send_message(
                f"❌ Image Bot STOPPED: {error_msg}\n"
                f"Status NOT advanced. Fix issues and run again."
            )
            return {
                "status": "failed",
                "bot": "Image Bot",
                "video_title": self.video_title,
                "error": error_msg,
                "images_pending": len(pending),
                "images_total": total,
            }

        # ALL images verified complete — safe to advance status
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_THUMBNAIL)
        print(f"  ✅ All {total} images verified complete. Status updated to: {self.STATUS_READY_THUMBNAIL}")

        return {
            "bot": "Image Bot",
            "video_title": self.video_title,
            "image_count": result.get("image_count", 0),
            "new_status": self.STATUS_READY_THUMBNAIL,
        }

    async def run_visuals_pipeline(self) -> dict:
        """Generate image prompts AND images for all scenes (combined pipeline).

        REQUIRES: Ideas status = "Ready For Image Prompts"
        UPDATES TO: "Ready For Video Scripts" when complete

        Note: This is a combined pipeline. For granular control, use
        run_styled_image_prompts() and run_image_bot() separately.
        """
        # Verify status
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_IMAGE_PROMPTS)
            if not idea:
                return {"error": "No idea with status 'Ready For Image Prompts'"}
            self._load_idea(idea)

        if self.current_idea.get("Status") != self.STATUS_READY_IMAGE_PROMPTS:
            return {"error": f"Idea status is '{self.current_idea.get('Status')}', expected 'Ready For Image Prompts'"}

        print(f"\n🖼️ VISUALS PIPELINE: Processing '{self.video_title}'")

        # Get or create project folder
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]

        # Step 1: Generate Styled Image Prompts (Visual Identity System)
        prompt_result = await self.run_styled_image_prompts()

        # Step 2: Generate Images
        image_result = await self._run_image_bot()

        # VERIFY all images are actually complete before advancing status
        all_images = self.airtable.get_all_images_for_video(self.video_title)
        pending = [img for img in all_images if img.get("Status") != "Done" and img.get("Image Prompt")]
        total = len([img for img in all_images if img.get("Image Prompt")])

        if len(pending) > 0:
            error_msg = f"{len(pending)}/{total} images still pending after all retries"
            print(f"  ❌ {error_msg}")
            self.slack.send_message(f"❌ Visuals Pipeline STOPPED: {error_msg} for *{self.video_title}*")
            return {
                "status": "failed",
                "bot": "Visuals Pipeline",
                "video_title": self.video_title,
                "error": error_msg,
            }

        # ALL images verified complete — safe to advance status
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_THUMBNAIL)
        print(f"  ✅ All {total} images verified complete. Status updated to: {self.STATUS_READY_THUMBNAIL}")

        return {
            "bot": "Visuals Pipeline",
            "video_title": self.video_title,
            "prompt_count": prompt_result.get("prompt_count", 0),
            "image_count": image_result.get("image_count", 0),
            "new_status": self.STATUS_READY_THUMBNAIL,
        }
    
    async def _run_image_bot(self) -> dict:
        """Generate images from prompts (internal method).

        Uses semaphore-based rate limiting to prevent OOM.
        Checkpoints progress after each image for crash recovery.
        Sends Slack progress updates as each image completes.
        """
        import gc

        # Rate limiting configuration
        MAX_CONCURRENT = 3  # Max concurrent image generations
        DELAY_BETWEEN_SCENES = 2.0  # Seconds to wait between scenes for memory cleanup

        self.slack.notify_images_start()
        print(f"\n  🖼️ IMAGE BOT: Generating images...")
        print(f"     Rate limit: {MAX_CONCURRENT} concurrent generations")

        # RESUME LOGIC: Get only pending images — already-completed images are skipped
        all_images = self.airtable.get_all_images_for_video(self.video_title)
        done_count = len([img for img in all_images if img.get("Status") == "Done"])
        pending_images = [img for img in all_images if img.get("Status") == "Pending" and img.get("Image Prompt")]
        total_pending = len(pending_images)

        if done_count > 0:
            print(f"     ♻️ RESUME: {done_count} images already done, {total_pending} remaining")
            self.slack.send_message(f"♻️ Resuming: {done_count} images already done, {total_pending} remaining for *{self.video_title}*")
        else:
            print(f"     Found {total_pending} pending images")

        if total_pending == 0:
            print("     ⚠️ No pending images found — nothing to generate.")
            self.slack.send_message(f"⚠️ Image Bot: 0 pending images found for *{self.video_title}*. Nothing to generate.")
            return {"image_count": 0, "failed_count": 0}

        # YouTube pipeline: Core Image is optional (uses text-to-image without reference)
        # Animation pipeline: Core Image is required (uses Seed Dream 4.5 Edit with reference)
        use_reference = bool(self.core_image_url)
        if use_reference:
            print(f"     🖼️ Using Core Image reference (Seed Dream 4.5 Edit)")
        else:
            print(f"     📸 Using text-to-image generation (no Core Image reference)")

        self.slack.send_message(f"🖼️ Starting image generation: {total_pending} images for *{self.video_title}*")

        # Group images by scene for organized processing
        scenes = {}
        for img in pending_images:
            scene_num = img.get("Scene", 0)
            if scene_num not in scenes:
                scenes[scene_num] = []
            scenes[scene_num].append(img)

        image_count = 0
        failed_count = 0
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        for scene_idx, scene_num in enumerate(sorted(scenes.keys())):
            scene_images = scenes[scene_num]
            scene_total = len(scene_images)
            print(f"\n    Scene {scene_num} ({scene_idx + 1}/{len(scenes)}): {scene_total} images")

            async def generate_and_save(img_record):
                """Generate single image with rate limiting and immediate checkpoint."""
                nonlocal image_count, failed_count

                async with semaphore:
                    prompt = img_record.get("Image Prompt", "")
                    index = img_record.get("Image Index", 0)
                    record_id = img_record["id"]

                    try:
                        # Generate image: use Core Image reference if available,
                        # otherwise use text-to-image (YouTube pipeline path)
                        if use_reference:
                            result = await self.image_client.generate_scene_image(prompt, self.core_image_url)
                        else:
                            result_urls = await self.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                            result = {"url": result_urls[0]} if result_urls else None

                        if result and result.get("url"):
                            image_url = result["url"]
                            seed_value = result.get("seed")

                            # Download image
                            image_content = await self.image_client.download_image(image_url)

                            # Upload to Google Drive
                            filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                            drive_file = self.google.upload_image(image_content, filename, self.project_folder_id)
                            drive_url = self.google.make_file_public(drive_file["id"])

                            # CHECKPOINT: Update Airtable immediately
                            self.airtable.update_image_record(record_id, image_url)
                            image_count += 1
                            print(f"      ✅ Scene {scene_num}, Image {index} → Done ({image_count}/{total_pending})")

                            # Slack progress update for every image
                            self.slack.send_message(f"🖼️ Generating images... {image_count}/{total_pending} complete")

                            # Clear image content from memory
                            del image_content
                            return True
                        else:
                            failed_count += 1
                            print(f"      ❌ Scene {scene_num}, Image {index} → Generation failed")
                            return False

                    except Exception as e:
                        failed_count += 1
                        print(f"      ❌ Scene {scene_num}, Image {index} → Error: {e}")
                        return False

            # Process all images in this scene with rate limiting
            await asyncio.gather(*[generate_and_save(img) for img in scene_images])

            # Memory cleanup between scenes
            gc.collect()

            # Progress update
            print(f"    ✅ Scene {scene_num} complete | Total progress: {image_count}/{total_pending}")

            # Delay between scenes to prevent memory buildup
            if scene_idx < len(scenes) - 1:
                await asyncio.sleep(DELAY_BETWEEN_SCENES)

        self.slack.notify_images_done()
        print(f"\n    🎉 IMAGE BOT COMPLETE")
        print(f"       Generated: {image_count}/{total_pending}")
        if failed_count > 0:
            print(f"       Failed: {failed_count}")

        # Slack completion with stats
        status_msg = f"✅ Images done: {image_count}/{total_pending} for *{self.video_title}*"
        if failed_count > 0:
            status_msg += f" ({failed_count} failed)"
        self.slack.send_message(status_msg)

        # === RETRY PHASE: Check for any missed/pending images ===
        max_retries = 3
        for retry_round in range(max_retries):
            # Check Airtable for pending images
            all_images = self.airtable.get_all_images_for_video(self.video_title)
            pending = [img for img in all_images if img.get("Status") != "Done" and img.get("Image Prompt")]
            
            if not pending:
                print(f"    ✅ All images verified complete")
                break
                
            print(f"    🔄 RETRY {retry_round + 1}/{max_retries}: Found {len(pending)} pending images")
            self.slack.send_message(f"🔄 Retry {retry_round + 1}: {len(pending)} pending images for *{self.video_title}*")
            
            # Group by scene
            from collections import defaultdict
            retry_scenes = defaultdict(list)
            for img in pending:
                retry_scenes[img.get("Scene", 0)].append(img)
            
            retry_count = 0
            for scene_num in sorted(retry_scenes.keys()):
                scene_images = retry_scenes[scene_num]
                print(f"      Scene {scene_num}: {len(scene_images)} pending")
                
                for img_record in scene_images:
                    record_id = img_record["id"]
                    prompt = img_record.get("Image Prompt", "")
                    index = img_record.get("Image Index", 0)
                    
                    try:
                        if use_reference:
                            result = await self.image_client.generate_scene_image(prompt, self.core_image_url)
                        else:
                            result_urls = await self.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                            result = {"url": result_urls[0]} if result_urls else None
                        if result and result.get("url"):
                            image_url = result["url"]
                            
                            # Download and upload to Drive
                            image_content = await self.image_client.download_image(image_url)
                            filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                            drive_file = self.google.upload_image(image_content, filename, self.project_folder_id)
                            
                            # Update Airtable
                            self.airtable.update_image_record(record_id, image_url)
                            retry_count += 1
                            image_count += 1
                            print(f"        ✅ Scene {scene_num}, Image {index} → Done (retry)")
                            del image_content
                        else:
                            print(f"        ❌ Scene {scene_num}, Image {index} → No image returned")
                    except Exception as e:
                        print(f"        ❌ Scene {scene_num}, Image {index} → {e}")
                    
                    await asyncio.sleep(2)  # Rate limit
            
            print(f"    ✅ Retry {retry_round + 1} complete: {retry_count} recovered")
            if retry_count == 0:
                print(f"    ⚠️ No progress made, stopping retries")
                break

        # Final check
        final_images = self.airtable.get_all_images_for_video(self.video_title)
        final_pending = len([img for img in final_images if img.get("Status") != "Done" and img.get("Image Prompt")])
        if final_pending > 0:
            self.slack.send_message(f"⚠️ {final_pending} images still pending after retries for *{self.video_title}*")
        else:
            self.slack.send_message(f"✅ All {len(final_images)} images complete for *{self.video_title}*")

        return {"image_count": image_count, "failed_count": failed_count}

    async def run_video_script_bot(self) -> dict:
        """Generate video prompts for Scene 1 only (Constraint)."""
        print(f"\n  📝 VIDEO SCRIPT BOT: Generating prompts for Scene 1...")

        # Get pending images
        existing_images = self.airtable.get_all_images_for_video(self.video_title)
        done_images = [img for img in existing_images if img.get("Status") == "Done"]

        prompt_count = 0
        hero_count = 0
        for img_record in done_images:
            scene = img_record.get("Scene", 0)

            # CONSTRAINT: Only Scene 1
            if scene != 1:
                continue

            # Check if prompt already exists
            if img_record.get("Video Prompt"):
                continue

            image_prompt = img_record.get("Image Prompt", "")
            if not image_prompt:
                print(f"    ⚠️ No Image Prompt found for Scene {scene}, skipping.")
                continue

            # Get segment data
            sentence_text = img_record.get("Sentence Text", "")
            shot_type = img_record.get("Shot Type", "medium_human_story")
            duration = img_record.get("Duration (s)", 6.0)

            # Smart hero selection: duration > 6s gets 10s clip
            is_hero = duration > 6.0
            clip_duration = 10 if is_hero else 6

            if is_hero:
                hero_count += 1

            idx = img_record.get("Image Index", "?")
            print(f"    [{idx}] {shot_type} | {duration:.1f}s segment → {clip_duration}s clip {'(HERO)' if is_hero else ''}")

            motion_prompt = await self.anthropic.generate_video_prompt(
                image_prompt=image_prompt,
                sentence_text=sentence_text,
                scene_type=shot_type,
                is_hero_shot=is_hero,
            )

            # Update Airtable with video prompt
            self.airtable.update_image_video_prompt(img_record["id"], motion_prompt)
            prompt_count += 1

        print(f"    ✅ Generated {prompt_count} video prompts ({hero_count} hero shots @ 10s)")
        
        # Update Status to Ready For Video Generation
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_VIDEO_GENERATION)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VIDEO_GENERATION}")
        
        return {"bot": "Video Script Bot", "prompt_count": prompt_count, "new_status": self.STATUS_READY_VIDEO_GENERATION}

    async def run_video_gen_bot(self) -> dict:
        """Generate videos logic."""
        print(f"\n  🎥 VIDEO GEN BOT: Generating videos...")
        
        # Get images ready for video (Done (implicit), Video Pending (field check handled internally))
        # Note: get_images_ready_for_video_generation filters for missing Video field
        pending_videos = self.airtable.get_images_ready_for_video_generation(self.video_title)
        
        # We also only want those with a Video Prompt!
        pending_videos = [v for v in pending_videos if v.get("Video Prompt")]
        
        # CONSTRAINT: Only Scene 1 (Implicit via prompt generation, but double check)
        pending_videos = [v for v in pending_videos if v.get("Scene") == 1]
        
        if not pending_videos:
            print("    No pending videos to generate.")
            # If we are here but no videos pending, maybe we are done?
            # Update status to Thumbnail
            print(f"    All Scene 1 videos done. Moving to Thumbnail.")
            self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_THUMBNAIL)
            return {"video_count": 0, "new_status": self.STATUS_READY_THUMBNAIL}

        video_count = 0
        total = len(pending_videos)
        print(f"    Found {total} Scene 1 images needing video generation.")
        
        for i, img_record in enumerate(pending_videos, 1):
            scene = img_record.get("Scene", 0)
            index = img_record.get("Image Index", 0)
            
            # Use permanent Drive URL instead of expiring Airtable attachment
            drive_url = img_record.get("Drive Image URL")
            if not drive_url:
                # Fallback to attachment URL if Drive URL missing (legacy records)
                image_url_list = img_record.get("Image", [])
                drive_url = image_url_list[0].get("url") if image_url_list else None
            
            motion_prompt = img_record.get("Video Prompt")

            if not drive_url or not motion_prompt:
                continue

            # Convert to direct download URL for Grok Imagine
            image_url = self.google.get_direct_drive_url(drive_url)
                
            print(f"    [{i}/{total}] Generating video for scene {scene}, image {index}...")
            print(f"      Motion: {motion_prompt}")
            
            # Generate video (default 10s)
            video_url = await self.image_client.generate_video(image_url, motion_prompt, duration=10)
            
            if video_url:
                print("      Downloading video content...")
                video_content = await self.image_client.download_image(video_url)
                
                filename = f"Scene_{str(scene).zfill(2)}_{str(index).zfill(2)}.mp4"
                print(f"      Uploading {filename} to Drive...")
                self.google.upload_video(video_content, filename, self.project_folder_id)
                
                # Update Airtable
                self.airtable.update_image_video_url(img_record["id"], video_url)
                print("      ✅ Video saved and synced!")
                video_count += 1
            else:
                print("      ❌ Video generation failed.")
                
        print(f"    ✅ Generated {video_count} videos")
        
        # Check if really done (loop again or just return active status to let next run catch it)
        # We'll return active status, let next run move to Thumbnail if empty.
        # Or check here.
        remaining = [v for v in self.airtable.get_images_ready_for_video_generation(self.video_title) if v.get("Video Prompt") and v.get("Scene") == 1]
        if not remaining:
             self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_THUMBNAIL)
             print(f"  ✅ Status updated to: {self.STATUS_READY_THUMBNAIL}")
             
        return {"video_count": video_count}
    
    # ==========================================================================
    # BRIEF TRANSLATOR INTEGRATION — Research Brief → Script + Scenes
    # ==========================================================================

    async def run_brief_translator(self, brief: dict = None) -> dict:
        """Translate a research brief into a production-ready script and scene list.

        This is the NEW pipeline path for research-backed videos. It replaces
        the beat-sheet approach with a validated, 6-act narration script and
        ~140 scene descriptions tagged with visual identity metadata.

        If no brief is provided, reads the current idea's fields as the brief.

        REQUIRES: Ideas status = "Idea Logged" or "Ready For Scripting"
        UPDATES TO: "Ready For Voice" when complete (script + scenes saved)

        Args:
            brief: Research brief dict. If None, builds from current idea fields.

        Returns:
            Dict with translation results including scene_filepath and video_id.
        """
        from brief_translator import translate_brief

        if not self.current_idea:
            idea = (
                self.get_idea_by_status(self.STATUS_READY_SCRIPTING)
                or self.get_idea_by_status(self.STATUS_IDEA_LOGGED)
            )
            if not idea:
                return {"error": "No idea available for brief translation"}
            self._load_idea(idea)

        print(f"\n📜 BRIEF TRANSLATOR: Processing '{self.video_title}'")

        # Build brief from Airtable idea fields if not provided
        if brief is None:
            idea = self.current_idea

            # Check for research_payload (from research agent)
            research_payload_raw = idea.get("Research Payload", "")
            if research_payload_raw:
                try:
                    research_payload = json.loads(research_payload_raw)
                    print("  📚 Found research payload — using as primary source material")
                    # Read Framework Angle from Airtable record (set by research agent
                    # or discovery scanner). Falls back to themes if not set.
                    framework_angle = idea.get("Framework Angle", "") or research_payload.get("themes", "")
                    brief = {
                        "headline": research_payload.get("headline", idea.get("Video Title", "")),
                        "thesis": research_payload.get("thesis", ""),
                        "executive_hook": research_payload.get("executive_hook", idea.get("Hook Script", "")),
                        "fact_sheet": research_payload.get("fact_sheet", ""),
                        "historical_parallels": research_payload.get("historical_parallels", ""),
                        "framework_analysis": research_payload.get("framework_analysis", ""),
                        "character_dossier": research_payload.get("character_dossier", ""),
                        "narrative_arc": research_payload.get("narrative_arc", ""),
                        "counter_arguments": research_payload.get("counter_arguments", ""),
                        "visual_seeds": research_payload.get("visual_seeds", ""),
                        "source_bibliography": research_payload.get("source_bibliography", ""),
                        "framework_angle": framework_angle,
                        "title_options": research_payload.get("title_options", idea.get("Video Title", "")),
                        "thumbnail_concepts": research_payload.get("thumbnail_concepts", ""),
                        "source_urls": idea.get("Source URLs", "") or research_payload.get("source_bibliography", ""),
                        # Pass through research enrichment flag
                        "_research_enriched": True,
                    }
                    print(f"  🎯 Framework Angle: {framework_angle or '(not set)'}")
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"  ⚠️ Could not parse research payload: {e}")
                    research_payload_raw = ""  # Fall through to legacy path

            if not research_payload_raw:
                # Legacy path: build brief from standard idea fields
                framework_angle = idea.get("Framework Angle", "")
                brief = {
                    "headline": idea.get("Video Title", ""),
                    "thesis": idea.get("Thesis", "") or idea.get("Future Prediction", ""),
                    "executive_hook": idea.get("Executive Hook", "") or idea.get("Hook Script", ""),
                    "fact_sheet": idea.get("Writer Guidance", ""),
                    "historical_parallels": idea.get("Past Context", ""),
                    "framework_analysis": idea.get("Present Parallel", ""),
                    "character_dossier": "",
                    "narrative_arc": idea.get("Future Prediction", ""),
                    "counter_arguments": "",
                    "visual_seeds": idea.get("Thumbnail Prompt", ""),
                    "source_bibliography": idea.get("Reference URL", ""),
                    "framework_angle": framework_angle,
                    "title_options": idea.get("Video Title", ""),
                    "thumbnail_concepts": idea.get("Thumbnail Prompt", ""),
                    "source_urls": idea.get("Source URLs", "") or idea.get("Reference URL", ""),
                }
                print(f"  🎯 Framework Angle: {framework_angle or '(not set — legacy idea)'}")

        # Scene output directory (project-relative)
        scene_output_dir = str(Path(__file__).parent / "scenes")

        result = await translate_brief(
            anthropic_client=self.anthropic,
            airtable_client=self.airtable,
            idea_record_id=self.current_idea_id,
            brief=brief,
            slack_client=self.slack,
            scene_output_dir=scene_output_dir,
        )

        if result["status"] == "success":
            # Store scene filepath for downstream use
            self._scene_filepath = result.get("scene_filepath")
            self._video_id = result.get("video_id")

            # Update status to Ready For Voice
            self.airtable.update_idea_status(
                self.current_idea_id, self.STATUS_READY_VOICE
            )
            print(f"  ✅ Status updated to: {self.STATUS_READY_VOICE}")
            print(f"  📂 Scene file: {self._scene_filepath}")

            self.slack.send_message(
                f"📜 Brief translated: *{self.video_title}*\n"
                f"Scenes: {result.get('scene_validation', {}).get('stats', {}).get('total_scenes', '?')}"
            )
        else:
            print(f"  ❌ Translation failed: {result.get('error', result['status'])}")

        return {
            "bot": "Brief Translator",
            "video_title": self.video_title,
            "status": result["status"],
            "scene_filepath": result.get("scene_filepath"),
            "video_id": result.get("video_id"),
            "new_status": self.STATUS_READY_VOICE if result["status"] == "success" else None,
        }

    # ==========================================================================
    # IMAGE PROMPT ENGINE INTEGRATION — Scene List → Styled Prompts
    # ==========================================================================

    async def run_styled_image_prompts(self, scene_filepath: str = None) -> dict:
        """Generate styled image prompts using the Visual Identity System.

        Reads a scene list JSON (from brief_translator) and runs it through
        the image_prompt_engine to produce Dossier/Schema/Echo styled prompts
        with Ken Burns directions and composition directives.

        This is the NEW path that replaces generic Claude prompt generation
        with the full visual identity system.

        Args:
            scene_filepath: Path to scene list JSON. If None, searches the
                scenes/ directory for the current video.

        Returns:
            Dict with prompt generation results.
        """
        from image_prompt_engine import generate_prompts, resolve_accent_color

        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_IMAGE_PROMPTS)
            if not idea:
                return {"error": "No idea at Ready For Image Prompts"}
            self._load_idea(idea)

        print(f"\n🎨 STYLED IMAGE PROMPTS: Processing '{self.video_title}'")

        # Locate scene file
        if scene_filepath is None:
            scene_filepath = getattr(self, "_scene_filepath", None)

        # Check idea record for scene file path
        if scene_filepath is None and self.current_idea:
            scene_filepath = self.current_idea.get("Scene File Path")

        if scene_filepath is None:
            # Search scenes/ directory for matching file
            scene_dir = Path(__file__).parent / "scenes"
            if scene_dir.exists():
                for f in sorted(scene_dir.glob("*_scenes.json"), reverse=True):
                    scene_filepath = str(f)
                    break

        # Load scenes from file or build from Airtable Script records
        raw_scenes = None

        # Source 1: Scene JSON file (from Brief Translator)
        if scene_filepath and Path(scene_filepath).exists():
            raw_scenes = json.loads(Path(scene_filepath).read_text())
            print(f"  Loaded {len(raw_scenes)} scenes from {Path(scene_filepath).name}")

        # Source 2: Airtable Script table records (from Script Bot)
        if not raw_scenes:
            scripts = self.airtable.get_scripts_by_title(self.video_title)
            if scripts:
                print(f"  📋 Building {len(scripts)} scenes from Airtable Script table")
                raw_scenes = []
                total_scripts = len(scripts)
                for script in scripts:
                    scene_text = script.get("Scene text", "") or script.get("Script", "")
                    word_count = len(scene_text.split()) if scene_text else 0
                    duration = word_count / 2.5 if word_count > 0 else 60
                    scene_num = script.get("scene", len(raw_scenes) + 1)
                    act = min(6, (scene_num - 1) * 6 // total_scripts + 1) if total_scripts > 0 else 1
                    raw_scenes.append({
                        "scene_number": scene_num,
                        "scene_description": scene_text,
                        "duration_seconds": round(duration, 1),
                        "act": act,
                    })

        # Source 3: Idea record's own Script field (from Brief Translator pipeline record)
        if not raw_scenes and self.current_idea:
            idea_script = self.current_idea.get("Script", "")
            if idea_script and len(idea_script) > 100:
                print(f"  📋 Building scenes from idea's Script field ({len(idea_script)} chars)")
                # Split script into paragraphs as scenes
                paragraphs = [p.strip() for p in idea_script.split("\n\n") if p.strip() and len(p.strip()) > 20]
                if paragraphs:
                    raw_scenes = []
                    total_paras = len(paragraphs)
                    for i, para in enumerate(paragraphs):
                        word_count = len(para.split())
                        duration = word_count / 2.5 if word_count > 0 else 30
                        act = min(6, i * 6 // total_paras + 1) if total_paras > 0 else 1
                        raw_scenes.append({
                            "scene_number": i + 1,
                            "scene_description": para,
                            "duration_seconds": round(duration, 1),
                            "act": act,
                        })

        if not raw_scenes:
            print(f"  ❌ Searched for scenes in: scene files, Script table, idea Script field")
            print(f"     Video title: '{self.video_title}'")
            return {
                "error": f"No scenes found for '{self.video_title}'. "
                "Checked: scene JSON files, Script table (Title + Video Title fields), "
                "idea Script field. Ensure scripts exist and the video title matches."
            }

        # Expand scenes for image generation: each scene with duration_seconds
        # produces multiple image slots (~1 image per 8-11 seconds of narration)
        IMAGE_INTERVAL_SECONDS = 9  # ~1 image per 9 seconds
        expanded_scenes = []
        for scene in raw_scenes:
            duration = scene.get("duration_seconds", 60)
            image_count = max(1, round(duration / IMAGE_INTERVAL_SECONDS))
            for img_idx in range(image_count):
                expanded = dict(scene)
                expanded["_source_scene_number"] = scene.get("scene_number", 1)
                expanded["_image_index"] = img_idx + 1
                expanded["_images_in_scene"] = image_count
                expanded_scenes.append(expanded)

        print(f"  Expanded to {len(expanded_scenes)} image slots from {len(raw_scenes)} scenes")

        # RESUME LOGIC: Check for existing prompts and skip scenes that already have them
        existing_images = self.airtable.get_all_images_for_video(self.video_title)
        existing_keys = {
            (img.get("Scene"), img.get("Image Index"))
            for img in existing_images
            if img.get("Image Prompt")  # Only count scenes with populated Image Prompt
        }

        if existing_keys:
            print(f"  ♻️ RESUME: Found {len(existing_keys)} scenes with existing Image Prompts — skipping them")

        # Filter expanded scenes to only those that need prompts
        scenes_needing_prompts = []
        scenes_needing_prompts_indices = []
        for i, scene in enumerate(expanded_scenes):
            scene_num = scene.get("_source_scene_number", scene.get("scene_number", i + 1))
            segment_index = scene.get("_image_index", 1)
            if (scene_num, segment_index) not in existing_keys:
                scenes_needing_prompts.append(scene)
                scenes_needing_prompts_indices.append(i)

        if not scenes_needing_prompts:
            print(f"  ✅ All {len(expanded_scenes)} image prompts already exist — nothing to generate")
            # Still update status in case it wasn't set
            self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_IMAGES)
            return {
                "bot": "Styled Image Prompt Engine",
                "video_title": self.video_title,
                "prompt_count": 0,
                "total_styled": len(expanded_scenes),
                "skipped": len(existing_keys),
                "new_status": self.STATUS_READY_IMAGES,
            }

        print(f"  Generating prompts for {len(scenes_needing_prompts)}/{len(expanded_scenes)} scenes (skipping {len(existing_keys)} existing)")

        # Determine accent color from idea or default
        accent_color = self.current_idea.get("Accent Color") or "cold teal"
        # Resolve underscored to spaced form for the engine
        accent_color = accent_color.replace("_", " ")

        # Generate styled prompts only for scenes that need them
        styled_prompts = generate_prompts(
            scenes_needing_prompts,
            accent_color=accent_color,
        )

        print(f"  Generated {len(styled_prompts)} styled prompts")

        # Write prompts to Airtable Images table
        created = 0
        for sp in styled_prompts:
            prompt_index = sp["index"]
            # Map back to original expanded_scenes index for scene data
            original_index = scenes_needing_prompts_indices[prompt_index] if prompt_index < len(scenes_needing_prompts_indices) else prompt_index
            scene_data = expanded_scenes[original_index] if original_index < len(expanded_scenes) else {}

            # Use source scene number and image index for unique keying
            scene_num = scene_data.get("_source_scene_number", scene_data.get("scene_number", original_index + 1))
            segment_index = scene_data.get("_image_index", 1)

            # Scene description from the scene list
            scene_desc = scene_data.get("scene_description", scene_data.get("description", ""))

            self.airtable.create_sentence_image_record(
                scene_number=scene_num,
                sentence_index=segment_index,
                sentence_text=scene_desc,
                duration_seconds=IMAGE_INTERVAL_SECONDS,
                image_prompt=sp["prompt"],
                video_title=self.video_title,
                shot_type=sp.get("composition", "wide"),
            )
            created += 1

        print(f"  ✅ Created {created} styled image prompts ({len(existing_keys)} previously existed)")

        # Log style distribution
        styles = [sp["style"] for sp in styled_prompts]
        dossier_pct = styles.count("dossier") / len(styles) * 100
        schema_pct = styles.count("schema") / len(styles) * 100
        echo_pct = styles.count("echo") / len(styles) * 100
        print(f"  Style mix: Dossier {dossier_pct:.0f}% | Schema {schema_pct:.0f}% | Echo {echo_pct:.0f}%")

        # Update status
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_IMAGES)
        print(f"  ✅ Status updated to: {self.STATUS_READY_IMAGES}")

        self.slack.send_message(
            f"🎨 Styled prompts done: {created} new, {len(existing_keys)} existing for *{self.video_title}*\n"
            f"D:{dossier_pct:.0f}% S:{schema_pct:.0f}% E:{echo_pct:.0f}%"
        )

        return {
            "bot": "Styled Image Prompt Engine",
            "video_title": self.video_title,
            "prompt_count": created,
            "total_styled": len(styled_prompts),
            "skipped": len(existing_keys),
            "style_distribution": {
                "dossier": styles.count("dossier"),
                "schema": styles.count("schema"),
                "echo": styles.count("echo"),
            },
            "new_status": self.STATUS_READY_IMAGES,
        }

    # ==========================================================================
    # ORCHESTRATOR EXECUTION MODES
    # ==========================================================================

    async def run_full_pipeline(self, input_text: str) -> dict:
        """Run the FULL pipeline: Idea → Script → Voice → Images → Render.

        Execution mode: full
        """
        print("=" * 60)
        print("🚀 FULL PIPELINE MODE")
        print("=" * 60)

        steps_completed = []

        # Step 1: Generate ideas
        idea_result = await self.run_idea_bot(input_text)
        steps_completed.append(("Idea Bot", idea_result))

        # At this point the user must pick an idea in Airtable.
        # For automated mode, pick the first idea and set it to Ready For Scripting.
        print("\n⏳ Auto-selecting first idea for full pipeline run...")
        ideas = self.airtable.get_ideas_by_status(self.STATUS_IDEA_LOGGED, limit=3)
        if not ideas:
            return {"error": "No ideas generated", "steps": steps_completed}

        first_idea = ideas[0]
        self.airtable.update_idea_status(first_idea["id"], self.STATUS_READY_SCRIPTING)
        self._load_idea(first_idea)

        # Step 2: Script
        script_result = await self.run_script_bot()
        steps_completed.append(("Script Bot", script_result))

        # Step 3: Voice
        voice_result = await self.run_voice_bot()
        steps_completed.append(("Voice Bot", voice_result))

        # Step 4: Image Prompts (Visual Identity System)
        prompt_result = await self.run_styled_image_prompts()
        steps_completed.append(("Styled Image Prompts", prompt_result))

        # Step 5: Images
        image_result = await self.run_image_bot()
        steps_completed.append(("Image Bot", image_result))

        # Step 6: Thumbnail
        thumbnail_result = await self.run_thumbnail_bot()
        steps_completed.append(("Thumbnail Bot", thumbnail_result))

        print("\n" + "=" * 60)
        print("✅ FULL PIPELINE COMPLETE")
        for name, res in steps_completed:
            status = res.get("new_status", res.get("status", "?"))
            print(f"  {name}: {status}")
        print("=" * 60)

        return {"mode": "full", "steps": len(steps_completed)}

    async def run_produce_pipeline(self, idea_record_id: str = None) -> dict:
        """Pick a researched idea and produce it through to render.

        Execution mode: produce
        Starts from an idea already in the Ideas Bank and runs:
        Script → Voice → Images → Thumbnail → (optional Render)
        """
        print("=" * 60)
        print("🎬 PRODUCE MODE — From Idea to Video")
        print("=" * 60)

        # Find an idea ready for production
        if idea_record_id:
            # Load specific idea
            all_ideas = self.airtable.get_all_ideas()
            idea = next((i for i in all_ideas if i["id"] == idea_record_id), None)
            if not idea:
                return {"error": f"Idea {idea_record_id} not found"}
        else:
            idea = (
                self.get_idea_by_status(self.STATUS_READY_SCRIPTING)
                or self.get_idea_by_status(self.STATUS_IN_QUE)
            )

        if not idea:
            return {"error": "No idea ready for production"}

        self._load_idea(idea)

        # Ensure status is at least Ready For Scripting
        current_status = idea.get("Status")
        if current_status in [self.STATUS_IDEA_LOGGED, self.STATUS_IN_QUE]:
            self.airtable.update_idea_status(
                self.current_idea_id, self.STATUS_READY_SCRIPTING
            )

        # Run through pipeline using status-driven loop
        max_steps = 20
        for step in range(max_steps):
            result = await self.run_next_step()
            if result.get("status") == "idle":
                break
            print(f"  Step {step + 1}: {result.get('bot', '?')} → {result.get('new_status', '?')}")

        print(f"\n✅ PRODUCE complete for: {self.video_title}")
        return {"mode": "produce", "video_title": self.video_title}

    async def run_from_stage(self, stage: str) -> dict:
        """Resume the pipeline from a specific stage.

        Execution mode: from_stage

        Args:
            stage: One of: scripting, voice, image_prompts, images,
                   video_scripts, video_gen, thumbnail, render

        Returns:
            Pipeline execution result.
        """
        stage_to_status = {
            "scripting": self.STATUS_READY_SCRIPTING,
            "voice": self.STATUS_READY_VOICE,
            "image_prompts": self.STATUS_READY_IMAGE_PROMPTS,
            "images": self.STATUS_READY_IMAGES,
            "video_scripts": self.STATUS_READY_VIDEO_SCRIPTS,
            "video_gen": self.STATUS_READY_VIDEO_GENERATION,
            "thumbnail": self.STATUS_READY_THUMBNAIL,
            "render": self.STATUS_READY_TO_RENDER,
        }

        target_status = stage_to_status.get(stage)
        if not target_status:
            valid = ", ".join(stage_to_status.keys())
            return {"error": f"Unknown stage '{stage}'. Valid: {valid}"}

        print(f"=" * 60)
        print(f"🔄 FROM-STAGE MODE — Resuming from: {stage}")
        print(f"   Setting status to: {target_status}")
        print(f"=" * 60)

        if not self.current_idea:
            # Find the first idea that's in or past this stage
            all_ideas = self.airtable.get_all_ideas()
            for idea in all_ideas:
                if idea.get("Status") != self.STATUS_DONE:
                    self._load_idea(idea)
                    break
            if not self.current_idea:
                return {"error": "No active idea found"}

        # Force the status
        self.airtable.update_idea_status(self.current_idea_id, target_status)

        # Run from there
        max_steps = 20
        for step in range(max_steps):
            result = await self.run_next_step()
            if result.get("status") == "idle":
                break
            print(f"  Step {step + 1}: {result.get('bot', '?')} → {result.get('new_status', '?')}")

        return {"mode": "from_stage", "start_stage": stage, "video_title": self.video_title}

    async def run_thumbnail_bot(self) -> dict:
        """Generate matched thumbnail + title pair for the video.

        REQUIRES: Ideas status = "Ready For Thumbnail"
        UPDATES TO: "Ready To Render" when complete (or stays if flagged for manual review)

        Uses the ThumbnailTitleEngine to:
        1. Select template (CFH Split / Mindplicit Banner / Power Dynamic)
        2. Generate a title with proven formula patterns
        3. Build a thumbnail prompt with the title's CAPS word as the red highlight
        4. Generate the thumbnail via Nano Banana Pro (up to 3 attempts)
        5. Validate, upload to Drive, and advance the pipeline
        """
        from thumbnail_title.engine import ThumbnailTitleEngine

        # Verify status
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_THUMBNAIL)
            if not idea:
                return {"error": "No idea with status 'Ready For Thumbnail'"}
            self._load_idea(idea)

        if self.current_idea.get("Status") != self.STATUS_READY_THUMBNAIL:
            return {"error": f"Idea status is '{self.current_idea.get('Status')}', expected 'Ready For Thumbnail'"}

        print(f"\n🎨 THUMBNAIL BOT: Processing '{self.video_title}'")

        video_title = self.current_idea.get("Video Title", "")
        video_summary = self.current_idea.get("Summary", "")

        # Build metadata for template selection
        video_metadata = {
            "Video Title": video_title,
            "Summary": video_summary,
            "topic": self.current_idea.get("Headline", ""),
            "Framework Angle": self.current_idea.get("Framework Angle", ""),
            "tags": [],
        }

        # --- Generate matched title + thumbnail ---
        self.slack.send_message(f"🎨 Generating thumbnail + title for *{self.video_title}*...")
        engine = ThumbnailTitleEngine(self.anthropic, self.image_client)

        try:
            result = await engine.generate(video_metadata)
        except Exception as e:
            error_msg = f"Thumbnail/title generation failed for '{self.video_title}': {e}"
            print(f"  ❌ {error_msg}")
            self.slack.send_message(f"❌ Thumbnail Bot STOPPED: {error_msg}\nStatus NOT advanced. Fix issues and run again.")
            return {
                "status": "failed",
                "bot": "Thumbnail Bot",
                "video_title": self.video_title,
                "error": error_msg,
            }

        # --- Save generated prompt and title metadata to Airtable ---
        self.airtable.update_idea_field(self.current_idea_id, "Thumbnail Prompt", result["thumbnail_prompt"])
        # Save title to Video Title field if it was generated fresh
        if result.get("title"):
            self.airtable.update_idea_field(self.current_idea_id, "Video Title", result["title"])

        # --- Check if thumbnail generation succeeded ---
        if result["needs_manual_review"]:
            error_msg = (
                f"Thumbnail generation failed after {result['thumbnail_attempt']} attempts "
                f"for '{self.video_title}'. Flagged for manual review."
            )
            print(f"  ❌ {error_msg}")
            self.slack.send_message(
                f"⚠️ Thumbnail Bot needs manual review for *{self.video_title}*\n"
                f"Template: {result['template_name']}\n"
                f"Title: {result['title']}\n"
                f"Status NOT advanced. Fix issues and run again."
            )
            return {
                "status": "manual_review",
                "bot": "Thumbnail Bot",
                "video_title": self.video_title,
                "generated_title": result["title"],
                "template_used": result["template_used"],
                "error": error_msg,
            }

        image_url = result["thumbnail_urls"][0]
        print(f"  ✅ Thumbnail generated: {image_url[:50]}...")

        # --- Upload to Google Drive ---
        if self.project_folder_id:
            parent_id = self.project_folder_id
        else:
            folder = self.google.search_folder(self.video_title)
            if folder:
                parent_id = folder["id"]
            else:
                print("  ⚠️ Project folder not found, uploading to root.")
                parent_id = None

        # Filename: {slug}_thumbnail_v{attempt}.png
        slug = video_title.lower().replace(" ", "_").replace("'", "")[:50]
        filename = f"{slug}_thumbnail_v{result['thumbnail_attempt']}.png"

        print("  ☁️ Uploading to Google Drive...")
        google_file = self.google.upload_file_from_url(
            url=image_url,
            name=filename,
            parent_id=parent_id,
        )
        drive_link = google_file.get("webViewLink")
        print(f"  ✅ Uploaded to Drive: {drive_link}")

        # --- Save to Airtable ---
        self.airtable.update_idea_thumbnail(self.current_idea_id, image_url)
        print("  ✅ Saved to Airtable")

        # --- Update status ---
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_TO_RENDER)
        print(f"  ✅ Status updated to: {self.STATUS_READY_TO_RENDER}")

        self.slack.send_message(
            f"✅ Thumbnail + title complete for *{self.video_title}*\n"
            f"📝 Title: {result['title']}\n"
            f"🎨 Template: {result['template_name']}\n"
            f"🔴 Red word: {result['caps_word']}\n"
            f"📎 {drive_link}"
        )

        return {
            "bot": "Thumbnail Bot",
            "video_title": self.video_title,
            "new_status": self.STATUS_READY_TO_RENDER,
            "thumbnail_url": drive_link,
            "generated_title": result["title"],
            "caps_word": result["caps_word"],
            "formula_used": result["formula_used"],
            "template_used": result["template_used"],
            "template_name": result["template_name"],
            "line_1": result["line_1"],
            "line_2": result["line_2"],
            "thumbnail_attempt": result["thumbnail_attempt"],
            "validation": result["validation"],
        }
    
    async def run_render_bot(self) -> dict:
        """Render video with Remotion and upload to Google Drive.

        REQUIRES: Ideas status = "Ready To Render"
        UPDATES TO: "Done" when complete
        """
        import subprocess
        import re
        import httpx
        from pathlib import Path

        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_TO_RENDER)
            if not idea:
                return {"error": "No idea with status 'Ready To Render'"}
            self._load_idea(idea)

        print(f"\n🎬 RENDER BOT: Processing '{self.video_title}'")
        self.slack.send_message(
            f"🎬 *Render starting:* _{self.video_title}_\n"
            f"Running pre-flight checks, downloading assets, then rendering (concurrency=1, ~60-90 min)..."
        )

        # CLEAN PUBLIC/ DIR — prevents asset contamination between renders
        # Each video needs its own Scene_XX_XX.png files; stale files from
        # a previous render would produce wrong visuals.
        remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"
        public_dir = remotion_dir / "public"
        if public_dir.exists():
            import glob as glob_mod
            stale_audio = glob_mod.glob(str(public_dir / "Scene *.mp3"))
            stale_images = glob_mod.glob(str(public_dir / "Scene_*.png"))
            stale_videos = glob_mod.glob(str(public_dir / "Scene_*.mp4"))
            removed = 0
            for f in stale_audio + stale_images + stale_videos:
                os.remove(f)
                removed += 1
            if removed:
                print(f"  🧹 Cleaned {removed} stale assets from public/")

        # PRE-FLIGHT CHECK: Regenerate any missing/pending images before render
        # This prevents render failures due to missing image files
        print(f"\n  🔍 Pre-flight check: Looking for missing images...")
        all_images = self.airtable.get_all_images_for_video(self.video_title)
        pending_images = [img for img in all_images if img.get("Status") == "Pending"]
        missing_images = [img for img in all_images if not img.get("Image")]

        if pending_images or missing_images:
            count = len(pending_images) + len(missing_images)
            print(f"  ⚠️ Found {count} images needing regeneration!")
            regen_result = await self.regenerate_images()
            if regen_result.get("regenerated", 0) > 0:
                print(f"  ✅ Regenerated {regen_result['regenerated']} images before render")
            else:
                print(f"  ❌ Failed to regenerate images - render may fail!")
        else:
            print(f"  ✅ All {len(all_images)} images present - ready to render")

        # Get project folder
        folder = self.google.get_or_create_folder(self.video_title)
        folder_id = folder["id"]

        # Export props
        props = await self.package_for_remotion()

        props_file = remotion_dir / "props.json"
        public_dir.mkdir(exist_ok=True)

        import json
        with open(props_file, "w") as f:
            json.dump(props, f, indent=2)
        print(f"  📦 Props saved to: {props_file}")

        # Generate segmentData.ts for word-synced image display
        print(f"  📝 Generating segmentData.ts...")
        self.generate_segment_data_ts(remotion_dir)

        # Download assets to public/ folder for Remotion
        print(f"  ⬇️ Downloading assets to public/...")
        async with httpx.AsyncClient(timeout=60.0) as client:
            for scene in props.get("scenes", []):
                scene_num = scene.get("sceneNumber", 0)

                # Download audio
                voice_url = scene.get("voiceUrl")
                if voice_url:
                    audio_file = public_dir / f"Scene {scene_num}.mp3"
                    if not audio_file.exists():
                        try:
                            resp = await client.get(voice_url)
                            resp.raise_for_status()
                            audio_file.write_bytes(resp.content)
                            print(f"    ✅ Scene {scene_num} audio")
                        except Exception as e:
                            print(f"    ❌ Scene {scene_num} audio failed: {e}")

                # Download images
                for img in scene.get("images", []):
                    img_url = img.get("url")
                    img_index = img.get("index", 0)
                    if img_url:
                        img_file = public_dir / f"Scene_{str(scene_num).zfill(2)}_{str(img_index).zfill(2)}.png"
                        if not img_file.exists():
                            try:
                                resp = await client.get(img_url)
                                resp.raise_for_status()
                                img_file.write_bytes(resp.content)
                                print(f"    ✅ Scene {scene_num} image {img_index}")
                            except Exception as e:
                                print(f"    ❌ Scene {scene_num} image {img_index} failed: {e}")

        print(f"  ✅ Assets downloaded")

        scene_count = len(props.get("scenes", []))
        self.slack.send_message(
            f"⬇️ *Assets ready:* _{self.video_title}_\n"
            f"{scene_count} scenes downloaded. Starting Remotion render now..."
        )

        # Sanitize filename
        def sanitize(title):
            clean = re.sub(r'[^\w\s-]', '', title)
            return re.sub(r'[-\s]+', '_', clean)[:50]
        
        safe_name = sanitize(self.video_title)
        output_file = remotion_dir / "out" / f"{safe_name}.mp4"
        output_file.parent.mkdir(exist_ok=True)
        
        # Ensure node_modules are installed
        if not (remotion_dir / "node_modules").exists():
            print(f"  📦 Installing Remotion dependencies...")
            install = subprocess.run(["npm", "install"], cwd=remotion_dir, capture_output=False)
            if install.returncode != 0:
                print(f"  ❌ npm install failed")
                self.slack.send_message(
                    f"❌ *Render FAILED:* _{self.video_title}_\n"
                    f"`npm install` failed in remotion-video/. Check node/npm on VPS."
                )
                return {"error": "npm install failed", "bot": "Render Bot"}

        # Render (optimized for KVM4: 4 vCPU / 16GB RAM)
        print(f"  🎥 Rendering video (concurrency=3, estimated 45-60 minutes)...")
        render_cmd = [
            "npx", "remotion", "render",
            "Main", str(output_file),
            "--props", str(props_file),
            "--concurrency=3",
            "--gl=swangle",
            "--timeout=180000",
            "--offthreadvideo-cache-size-in-bytes=1073741824",
        ]

        result = subprocess.run(render_cmd, cwd=remotion_dir)
        
        if result.returncode != 0:
            print(f"  ❌ Render failed")
            self.slack.send_message(
                f"❌ *Render FAILED:* _{self.video_title}_\n"
                f"Remotion exited with code {result.returncode}. Check logs on VPS."
            )
            return {"error": "Render failed", "bot": "Render Bot"}

        if not output_file.exists():
            print(f"  ❌ Output not found")
            self.slack.send_message(
                f"❌ *Render FAILED:* _{self.video_title}_\n"
                f"Remotion finished but output file not found at {output_file}"
            )
            return {"error": "Output file missing", "bot": "Render Bot"}

        file_size_mb = output_file.stat().st_size / (1024 * 1024)
        print(f"  ✅ Rendered: {output_file} ({file_size_mb:.0f} MB)")

        # Upload to Drive
        print("  ☁️ Uploading to Google Drive...")
        self.slack.send_message(
            f"✅ *Render complete:* _{self.video_title}_ ({file_size_mb:.0f} MB)\n"
            f"Uploading to Google Drive..."
        )
        with open(output_file, "rb") as f:
            video_content = f.read()
        
        drive_file = self.google.upload_video(video_content, f"{safe_name}.mp4", folder_id)
        drive_url = f"https://drive.google.com/file/d/{drive_file['id']}/view"
        
        # Update Airtable
        self.airtable.update_idea_field(self.current_idea_id, "Final Video", drive_url)
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_DONE)
        
        print(f"  ✅ Status updated to: {self.STATUS_DONE}")
        print(f"  🔗 Video: {drive_url}")
        
        self.slack.send_message(
            f"🎉 *Video ready for review!*\n"
            f"*{self.video_title}*\n\n"
            f"📺 *Watch here:* {drive_url}\n\n"
            f"Status updated to *Done*."
        )
        
        return {
            "bot": "Render Bot",
            "video_title": self.video_title,
            "new_status": self.STATUS_DONE,
            "video_url": drive_url
        }
    
    async def package_for_remotion(self) -> dict:
        """Package all assets for Remotion video editing.

        Includes segment data (text + duration) for word-synced image display.
        Prefers video clips over static images when available.

        Priority for each image slot:
        1. Video Clip URL (animated) from Google Drive
        2. Drive Image URL (static) from Google Drive
        3. NEVER use Airtable attachment URLs (they expire)
        """
        # Get all scripts for current video
        scripts = self.airtable.get_scripts_by_title(self.video_title)

        # Get all images for current video
        images = self.airtable.get_all_images_for_video(self.video_title)

        # Build Remotion props structure
        scenes = []
        for script in scripts:
            scene_number = script.get("scene", 0)
            scene_images = [
                img for img in images
                if img.get("Scene") == scene_number
            ]

            # Sort images by index
            sorted_images = sorted(scene_images, key=lambda x: x.get("Image Index", 0))

            processed_images = []
            for img in sorted_images:
                # Check for video clip first (animation pipeline output)
                video_clip_url = img.get("Video Clip URL")  # Direct Drive URL for video
                video_attachments = img.get("Video", [])

                # Prefer video clip over static image
                if video_clip_url:
                    media_url = video_clip_url
                    media_type = "video"
                elif video_attachments:
                    # Fallback to Video attachment field
                    media_url = video_attachments[0].get("url", "") if video_attachments else ""
                    media_type = "video"
                else:
                    # Fallback to static image (Drive URL preferred)
                    media_url = img.get("Drive Image URL") or (
                        img.get("Image", [{}])[0].get("url", "") if img.get("Image") else ""
                    )
                    media_type = "image"

                # Build base asset
                asset = {
                    "index": img.get("Image Index", 0),
                    "url": media_url,
                    "type": media_type,  # "image" or "video"
                    "segmentText": img.get("Sentence Text", ""),
                    "duration": img.get("Duration (s)", 8.0),
                    "isHeroShot": img.get("Hero Shot", False),
                    "videoDuration": img.get("Video Duration", 6),
                }

                # =============================================================
                # TIMING RECONCILIATION LAYER
                # Handles mismatch between voiceover duration and clip duration
                # =============================================================
                voiceover_duration = asset["duration"]  # from audio timing
                clip_duration = asset["videoDuration"] if media_type == "video" else None

                if clip_duration is None:
                    # Static image — use voiceover duration directly (existing behavior)
                    asset["renderDuration"] = voiceover_duration
                    asset["playbackRate"] = 1.0
                elif abs(voiceover_duration - clip_duration) <= 1.5:
                    # Close enough — adjust playback speed slightly
                    asset["renderDuration"] = voiceover_duration
                    asset["playbackRate"] = clip_duration / voiceover_duration if voiceover_duration > 0 else 1.0
                elif voiceover_duration > clip_duration + 1.5:
                    # Big gap — hold last frame (or flag for hero shot upgrade)
                    asset["renderDuration"] = voiceover_duration
                    asset["playbackRate"] = 1.0
                    asset["holdLastFrame"] = voiceover_duration - clip_duration
                else:
                    # Clip is longer than needed — trim end
                    asset["renderDuration"] = voiceover_duration
                    asset["playbackRate"] = 1.0
                    asset["trimEnd"] = clip_duration - voiceover_duration

                processed_images.append(asset)

            scenes.append({
                "sceneNumber": scene_number,
                "text": script.get("Scene text", ""),
                "voiceUrl": script.get("Voice Over", [{}])[0].get("url", "") if script.get("Voice Over") else "",
                "images": processed_images,
            })

        props = {
            "videoTitle": self.video_title,
            "folderId": self.project_folder_id,
            "docId": self.google_doc_id,
            "scenes": scenes,
        }

        return props

    def generate_segment_data_ts(self, remotion_dir: Path = None) -> str:
        """Generate segmentData.ts file for Remotion word-synced image display.

        Reads segment data from Airtable Images table and creates the TypeScript file
        that Remotion uses to align images with spoken words.

        Args:
            remotion_dir: Path to remotion-video directory. If None, uses default.

        Returns:
            Path to generated file
        """
        if remotion_dir is None:
            remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"

        # Get all images for current video
        images = self.airtable.get_all_images_for_video(self.video_title)

        # Group images by scene
        scenes_data: dict[int, list] = {}
        for img in images:
            scene_num = img.get("Scene", 0)
            if scene_num not in scenes_data:
                scenes_data[scene_num] = []

            segment_text = img.get("Sentence Text", "")
            duration = img.get("Duration (s)", 8.0)

            if segment_text:  # Only include if we have segment text
                scenes_data[scene_num].append({
                    "text": segment_text,
                    "duration": float(duration) if duration else 8.0,
                    "index": img.get("Image Index", 0),
                })

        # Sort segments within each scene by index
        for scene_num in scenes_data:
            scenes_data[scene_num] = sorted(scenes_data[scene_num], key=lambda x: x["index"])

        # Generate TypeScript content
        ts_lines = [
            "// Auto-generated segment data from Airtable",
            f"// Video: {self.video_title}",
            "// Generated for word-to-image alignment in Remotion",
            "",
            "export interface SegmentText {",
            "    text: string;",
            "    duration: number;",
            "}",
            "",
            "export const sceneSegmentData: Record<number, SegmentText[]> = {",
        ]

        # Add each scene's segments
        for scene_num in sorted(scenes_data.keys()):
            segments = scenes_data[scene_num]
            ts_lines.append(f"    {scene_num}: [")
            for seg in segments:
                # Escape quotes in text
                escaped_text = seg["text"].replace('"', '\\"').replace('\n', ' ')
                ts_lines.append(f'        {{ text: "{escaped_text}", duration: {seg["duration"]} }},')
            ts_lines.append("    ],")

        ts_lines.append("};")
        ts_lines.append("")

        # Write to file
        output_path = remotion_dir / "src" / "segmentData.ts"
        output_path.write_text("\n".join(ts_lines))

        print(f"  ✅ Generated segmentData.ts with {len(scenes_data)} scenes")
        return str(output_path)


    async def regenerate_images(self, scene_list: list[int] = None, image_indices: list[tuple[int, int]] = None) -> dict:
        """Regenerate specific missing images for the current video.

        Use this when render fails due to missing images. Can target:
        1. All images in specific scenes (scene_list)
        2. Specific scene/index pairs (image_indices)
        3. All images with empty "Image" field (if no args)

        Args:
            scene_list: List of scene numbers to regenerate all images for
            image_indices: List of (scene, index) tuples for specific images

        Returns:
            Dict with regeneration results
        """
        if not self.current_idea:
            # Try to find a video with images to regenerate
            idea = self.get_idea_by_status(self.STATUS_READY_TO_RENDER)
            if not idea:
                idea = self.get_idea_by_status(self.STATUS_READY_THUMBNAIL)
            if not idea:
                idea = self.get_idea_by_status(self.STATUS_READY_IMAGES)
            if not idea:
                return {"error": "No video found to regenerate images for"}
            self._load_idea(idea)

        print(f"\n🔄 REGENERATE IMAGES: Processing '{self.video_title}'")

        # Get or create project folder
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]

        # Get all images for this video
        all_images = self.airtable.get_all_images_for_video(self.video_title)

        # Filter to images needing regeneration
        images_to_regen = []

        if image_indices:
            # Specific scene/index pairs
            for scene_num, img_index in image_indices:
                for img in all_images:
                    if img.get("Scene") == scene_num and img.get("Image Index") == img_index:
                        images_to_regen.append(img)
                        break
        elif scene_list:
            # All images in specified scenes
            for img in all_images:
                if img.get("Scene") in scene_list:
                    images_to_regen.append(img)
        else:
            # All images with no "Image" attachment (missing)
            for img in all_images:
                img_attachments = img.get("Image", [])
                if not img_attachments:
                    images_to_regen.append(img)

        if not images_to_regen:
            print("  ✅ No images need regeneration")
            return {"status": "ok", "regenerated": 0}

        print(f"  Found {len(images_to_regen)} images to regenerate")

        # Group by scene for parallel processing
        scenes = {}
        for img in images_to_regen:
            scene_num = img.get("Scene", 0)
            if scene_num not in scenes:
                scenes[scene_num] = []
            scenes[scene_num].append(img)

        regenerated = 0

        for scene_num in sorted(scenes.keys()):
            scene_images = scenes[scene_num]
            print(f"  Scene {scene_num}: Regenerating {len(scene_images)} images...")

            async def generate_single(img_record):
                prompt = img_record.get("Image Prompt", "")
                index = img_record.get("Image Index", 0)

                if not prompt:
                    return (img_record, None, index, "No prompt")

                try:
                    # Use Core Image reference if available, otherwise text-to-image
                    if self.core_image_url:
                        result = await self.image_client.generate_scene_image(prompt, self.core_image_url)
                    else:
                        result_urls = await self.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                        result = {"url": result_urls[0]} if result_urls else None
                    return (img_record, result, index, None)
                except Exception as e:
                    return (img_record, None, index, str(e))

            # Generate in parallel
            results = await asyncio.gather(*[generate_single(img) for img in scene_images])

            # Upload to Drive and update Airtable
            for img_record, result, index, error in results:
                if error:
                    print(f"    ❌ Scene {scene_num}, Image {index}: {error}")
                    continue

                if result and result.get("url"):
                    image_url = result["url"]
                    seed_value = result.get("seed")

                    # Download image
                    image_content = await self.image_client.download_image(image_url)

                    # Upload to Google Drive
                    filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                    drive_file = self.google.upload_image(image_content, filename, self.project_folder_id)
                    drive_url = self.google.make_file_public(drive_file["id"])

                    # Update Airtable (include seed for reproducibility)
                    self.airtable.update_image_record(record_id, image_url)
                    regenerated += 1
                    print(f"    ✅ Scene {scene_num}, Image {index} → regenerated")

        print(f"\n  ✅ Regenerated {regenerated} images")
        return {"status": "ok", "regenerated": regenerated, "total_requested": len(images_to_regen)}

    async def sync_all_assets(self, video_title: str):
        """Syncs all audio and images for a video to Google Drive."""
        print(f"\n🔄 SYNC: Checking assets for '{video_title}'...")
        
        # Get Folder
        folder = self.google.get_or_create_folder(video_title)
        folder_id = folder["id"]
        print(f"  📂 Target Folder: {video_title} ({folder_id})")
        
        # 1. Sync Audio
        scripts = self.airtable.get_scripts_by_title(video_title)
        print(f"  Found {len(scripts)} script records.")
        
        for script in scripts:
            scene = script.get("scene", 0)
            # Audio field in airtable script table is named 'Voice Over'
            audio_attachments = script.get("Voice Over", [])
            audio_url = None
            if isinstance(audio_attachments, list) and audio_attachments:
                audio_url = audio_attachments[0].get("url")
            elif isinstance(audio_attachments, str):
                audio_url = audio_attachments
            
            if not audio_url:
                continue
                
            filename = f"Scene {scene}.mp3"
            
            # Check exist (Optimized to avoid download if exists)
            if self.google.search_file(filename, folder_id):
                print(f"  ✅ Audio (Scene {scene}) exists.")
                continue
                
            print(f"  ⬇️  Downloading Audio (Scene {scene})...")
            try:
                # Use ImageClient's download (generic http) or ElevenLabs? 
                # Better use generic or duplicate implementation. 
                # ElevenLabs client has download_audio
                content = await self.elevenlabs.download_audio(audio_url)
                self.google.upload_audio(content, filename, folder_id)
                print(f"  ✅ Uploaded Audio {filename}")
            except Exception as e:
                print(f"  ❌ Failed Audio {filename}: {e}")
            
        # 2. Sync Images
        images = self.airtable.get_all_images_for_video(video_title)
        print(f"  Found {len(images)} image records.")
        
        for img in images:
            scene = img.get("Scene", 0)
            index = img.get("Image Index", 0)
            img_list = img.get("Image", [])
            img_url = img_list[0].get("url") if img_list else None
            
            if not img_url:
                continue
                
            filename = f"Scene_{str(scene).zfill(2)}_{str(index).zfill(2)}.png"
            
            if self.google.search_file(filename, folder_id):
                print(f"  ✅ Image (Scene {scene}-{index}) exists.")
                continue
            
            print(f"  ⬇️  Downloading Image ({filename})...")
            try:
                content = await self.image_client.download_image(img_url)
                self.google.upload_image(content, filename, folder_id)
                print(f"  ✅ Uploaded Image {filename}")
            except Exception as e:
                print(f"  ❌ Failed Image {filename}: {e}")
                
        print("\n✅ Sync Complete!")
        return {"status": "synced"}

    async def sync_scripts_to_google_doc(self, video_title: str) -> dict:
        """Create Google Doc from existing Airtable scripts.

        Use this to recover when Google Docs API was unavailable during script generation.
        Scripts are already saved to Airtable, this just creates the Doc.

        Args:
            video_title: The video title to sync

        Returns:
            Dict with doc_id and doc_url if successful
        """
        print(f"\n📄 SYNC SCRIPTS TO GOOGLE DOC: '{video_title}'")

        # Get scripts from Airtable
        scripts = self.airtable.get_scripts_by_title(video_title)
        if not scripts:
            return {"error": f"No scripts found for '{video_title}'"}

        print(f"  Found {len(scripts)} scenes in Airtable")

        # Get or create folder
        folder = self.google.get_or_create_folder(video_title)
        folder_id = folder["id"]

        # Create Google Doc
        doc = self.google.create_document(video_title, folder_id)
        if doc.get("unavailable"):
            return {"error": "Google Docs API still unavailable"}

        doc_id = doc["id"]
        print(f"  Created Google Doc: {doc_id}")

        # Append all scenes
        for script in scripts:
            scene_num = script.get("scene", 0)
            scene_text = script.get("Scene text", "")
            if scene_text:
                success = self.google.append_to_document(
                    doc_id,
                    f"**Scene {scene_num}**\n\n{scene_text}",
                )
                if success:
                    print(f"  ✅ Added Scene {scene_num}")
                else:
                    print(f"  ⚠️  Failed to add Scene {scene_num}")

        doc_url = self.google.get_document_url(doc_id)
        print(f"\n✅ Google Doc created: {doc_url}")

        return {
            "doc_id": doc_id,
            "doc_url": doc_url,
            "scenes_synced": len(scripts),
        }


async def main():
    """CLI entry point - runs the next available step."""
    import sys

    pipeline = VideoPipeline()

    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h"]:
        print("=" * 60)
        print("🎬 VIDEO PIPELINE - CLI Options")
        print("=" * 60)
        print("\nUsage: python pipeline.py [option]")
        print("\nOptions:")
        print("  (no args)         Run the next pipeline step based on Airtable status")
        print("  --status          Show status of all ideas in Airtable")
        print("  --more-ideas      Generate ideas from saved format library (no scraping)")
        print('  --idea "..."      Generate 3 video ideas from URL or concept')
        print('  --research "..."  Run deep research on a topic (saves to Idea Concepts)')
        print("  --trending        Generate ideas from trending YouTube videos (Apify)")
        print("  --discover        Scan headlines for video ideas and save to Airtable")
        print("  --translate       Run brief translator (research brief → script + scenes)")
        print("  --styled-prompts  Run image prompt engine with visual identity system")
        print('  --full "..."      Full pipeline: Idea → Script → Voice → Images → Render')
        print("  --produce [id]    Produce pipeline from a queued idea to completion")
        print("  --from-stage X    Resume pipeline from a specific stage")
        print("  --sync            Sync assets to Google Drive")
        print("  --remotion        Export Remotion props for rendering")
        print('  --regenerate      Regenerate missing images (fixes render failures)')
        print('  --animate         Generate video clips from images (Grok Imagine)')
        print("  --render          Render only — skip other stages, process one at a time")
        print("  --run-queue       Process all videos until queue is empty")
        print("  --help, -h        Show this help message")
        print("\nExamples:")
        print("  python pipeline.py")
        print("  python pipeline.py --status")
        print('  python pipeline.py --idea "https://youtu.be/VIDEO_ID"')
        print('  python pipeline.py --idea "Breaking news about AI regulation"')
        print("  python pipeline.py --trending")
        print('  python pipeline.py --trending "crypto crash,bitcoin ETF"')
        print('  python pipeline.py --regenerate "Video Title" --images 3:4,4:7')
        print('  python pipeline.py --animate "Video Title" --estimate')
        print('  python pipeline.py --animate "Video Title" --heroes-only')
        print("  python pipeline.py --render")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        # Show current status of all ideas
        print("=" * 60)
        print("📋 AIRTABLE IDEAS STATUS")
        print("=" * 60)
        ideas = pipeline.airtable.get_all_ideas()
        for idea in ideas:
            print(f"  {idea.get('Status', 'Unknown'):20} | {idea.get('Video Title', 'Untitled')[:40]}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--idea":
        # Generate ideas from URL or concept
        if len(sys.argv) < 3:
            print("=" * 60)
            print("💡 IDEA BOT - Generate Video Concepts")
            print("=" * 60)
            print("\nUsage:")
            print('  python pipeline.py --idea "https://youtube.com/watch?v=VIDEO_ID"')
            print('  python pipeline.py --idea "Your concept or news topic here"')
            print("\nExamples:")
            print('  python pipeline.py --idea "https://youtu.be/dQw4w9WgXcQ"')
            print('  python pipeline.py --idea "The Federal Reserve just announced rate cuts"')
            print('  python pipeline.py --idea "AI is replacing software developers"')
            return

        input_text = " ".join(sys.argv[2:])  # Join all args after --idea
        result = await pipeline.run_idea_bot(input_text)
        return

    # === DEEP RESEARCH ===
    if len(sys.argv) > 1 and sys.argv[1] == "--research":
        from research_agent import run_research

        if len(sys.argv) < 3:
            print("=" * 60)
            print("🔬 RESEARCH AGENT - Deep Topic Research")
            print("=" * 60)
            print("\nUsage:")
            print('  python pipeline.py --research "Topic to research"')
            print("\nExamples:")
            print('  python pipeline.py --research "Why the US Dollar Could Collapse by 2030"')
            print('  python pipeline.py --research "AI is eliminating white-collar jobs"')
            print("\nThe research payload will be saved to the Idea Concepts table")
            print("with source='research_agent' and status='Idea Logged'.")
            return

        topic = " ".join(sys.argv[2:])
        print(f"\n🔬 RESEARCH AGENT: Researching '{topic}'...")
        payload = await run_research(
            anthropic_client=pipeline.anthropic,
            topic=topic,
            airtable_client=pipeline.airtable,
        )

        print(f"\n✅ Research complete!")
        print(f"   Headline: {payload.get('headline', 'N/A')}")
        print(f"   Record ID: {payload.get('_airtable_record_id', 'N/A')}")
        print(f"   Fields: {len(payload)}")
        print(f"\nNext: Review in Airtable and set status to 'Ready For Scripting'")
        return

    # === MORE IDEAS FROM FORMAT LIBRARY ===
    if len(sys.argv) > 1 and sys.argv[1] == "--more-ideas":
        import json
        import os as os_mod
        from bots.idea_modeling import generate_modeled_ideas
        
        config_path = os_mod.path.join(os_mod.path.dirname(__file__), "config", "idea_modeling_config.json")
        
        if not os_mod.path.exists(config_path):
            print("No format library found. Run --trending first to build it.")
            sys.exit(1)
        
        with open(config_path, "r") as f:
            config = json.load(f)
        
        format_library = config.get("format_library", [])
        
        if not format_library:
            print("Format library is empty. Run --trending first to populate it.")
            sys.exit(1)
        
        format_library.sort(key=lambda x: x.get("times_seen", 0), reverse=True)
        top_formats = format_library[:5]
        
        print("")
        print("=" * 50)
        print("IDEA ENGINE v2 - Generate from Format Library")
        print("=" * 50)
        print(f"Using top {len(top_formats)} formats from library of {len(format_library)}:")
        for fmt in top_formats:
            formula_display = fmt["formula"][:50] + "..." if len(fmt["formula"]) > 50 else fmt["formula"]
            seen = fmt.get("times_seen", 1)
            print(f"  - {formula_display} (seen {seen}x)")
        
        load_dotenv()
        from clients.anthropic_client import AnthropicClient
        from clients.airtable_client import AirtableClient
        from clients.slack_client import SlackClient

        anthropic = AnthropicClient()
        airtable = AirtableClient()
        slack = SlackClient()

        async def run_more_ideas():
            ideas = await generate_modeled_ideas(top_formats, config, anthropic, num_ideas=3)

            print(f"Generated {len(ideas)} ideas:")
            for i, idea in enumerate(ideas, 1):
                title = idea.get("viral_title", "Untitled")
                fmt_id = idea.get("based_on_format", "unknown")
                print(f"  {i}. {title}")
                print(f"     Format: {fmt_id}")

            # Save to Airtable (Idea Concepts table)
            print("  Saving to Airtable (Idea Concepts)...")
            for i, idea in enumerate(ideas, 1):
                try:
                    idea["original_dna"] = f"Idea Engine v2: format_library"
                    record = airtable.create_idea(idea, source="format_library")
                    print(f"    ✅ Saved idea {i}: {record.get('id')}")
                except Exception as e:
                    print(f"    ❌ Failed to save idea {i}: {e}")

            msg_lines = ["IDEA ENGINE v2 - From Format Library", "-" * 40]
            for i, idea in enumerate(ideas, 1):
                msg_lines.append(f"{i}. {idea.get('viral_title', 'Untitled')}")
                msg_lines.append(f"   Format: {idea.get('based_on_format', '')}")

            slack.send_message(chr(10).join(msg_lines))
            print("Sent to Slack!")

            return ideas

        import asyncio
        asyncio.run(run_more_ideas())
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--trending":
        # Generate ideas from trending YouTube videos
        search_queries = None
        if len(sys.argv) > 2:
            # Parse custom search queries (comma-separated)
            queries_str = " ".join(sys.argv[2:])
            search_queries = [q.strip() for q in queries_str.split(",") if q.strip()]
            print(f"Using custom queries: {search_queries}")

        result = await pipeline.run_trending_idea_bot(
            search_queries=search_queries,
            num_ideas=3,
        )
        return

    # === DISCOVERY SCANNER ===
    if len(sys.argv) > 1 and sys.argv[1] == "--discover":
        from discovery_scanner import run_discovery, format_ideas_for_slack, build_option_map
        from discovery_tracker import save_discovery_message

        focus = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else None
        focus_msg = f" (focus: {focus})" if focus else ""

        print("=" * 60)
        print(f"🔍 DISCOVERY SCANNER — Scanning headlines{focus_msg}")
        print("=" * 60)

        try:
            result = await run_discovery(
                anthropic_client=pipeline.anthropic,
                focus=focus,
            )
        except Exception as e:
            error_msg = f"Discovery scanner crashed: {e}"
            print(f"\n❌ {error_msg}")
            try:
                pipeline.slack.send_message(
                    f"❌ *5 AM Discovery Scan FAILED*\n"
                    f"```{error_msg}```\n"
                    f"No ideas were generated. Run `discover` manually to retry."
                )
            except Exception:
                pass
            return

        ideas = result.get("ideas", [])
        if not ideas:
            print("\n⚠️ No ideas found. Try with a different focus keyword.")
            try:
                pipeline.slack.send_message(
                    "🔍 *Daily Discovery Scan* ran at 5 AM but found no strong ideas today.\n"
                    "Try running `discover [focus]` manually with a specific topic."
                )
            except Exception:
                pass
            return

        print(f"\nFound {len(ideas)} ideas:\n")
        for i, idea in enumerate(ideas, 1):
            title_opts = idea.get("title_options", [])
            title = title_opts[0]["title"] if title_opts else "Untitled"
            appeal = idea.get("estimated_appeal", "?")
            print(f"  {i}. {title} (appeal: {appeal}/10)")
            hook = idea.get("hook", "")
            if hook:
                print(f"     Hook: {hook[:120]}")
            print()

        # Save to Airtable
        print("Saving to Airtable (Idea Concepts)...")
        saved_record_ids = []
        for i, idea in enumerate(ideas, 1):
            title_opts = idea.get("title_options", [])
            title = title_opts[0]["title"] if title_opts else "Untitled"
            idea_data = {
                "viral_title": title,
                "hook_script": idea.get("hook", ""),
                "narrative_logic": {
                    "past_context": idea.get("historical_parallel_hint", ""),
                    "present_parallel": idea.get("our_angle", ""),
                    "future_prediction": "",
                },
                "writer_guidance": idea.get("our_angle", ""),
                "original_dna": json.dumps({
                    "source": "discovery_scanner",
                    "headline_source": idea.get("headline_source", ""),
                    "estimated_appeal": idea.get("estimated_appeal", 0),
                }),
            }
            try:
                record = pipeline.airtable.create_idea(idea_data, source="discovery_scanner")
                saved_record_ids.append(record.get("id"))
                print(f"  ✅ Saved idea {i}: {record.get('id')} — {title}")
            except Exception as e:
                saved_record_ids.append(None)
                print(f"  ❌ Failed to save idea {i}: {e}")

        # Post interactive Slack message with emoji reactions for idea selection
        # This lets the user wake up and click to choose an idea
        try:
            from slack_sdk import WebClient
            slack_token = os.getenv("SLACK_BOT_TOKEN")
            slack_channel = os.getenv("SLACK_CHANNEL_ID", "C0A9U1X8NSW")
            slack_web = WebClient(token=slack_token)

            slack_msg = (
                "☀️ *Good Morning! Daily Discovery Scan Complete*\n"
                "React with 1️⃣ 2️⃣ or 3️⃣ to approve an idea — I'll auto-research it and queue it for the 8 AM pipeline run.\n\n"
            )
            slack_msg += format_ideas_for_slack(result)

            response = slack_web.chat_postMessage(
                channel=slack_channel,
                text=slack_msg,
            )
            msg_ts = response.get("ts", "")

            if msg_ts:
                # Build option map: one emoji per title option (idea + title)
                option_map = build_option_map(ideas)
                emoji_names = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
                emojis_to_add = emoji_names[:len(option_map)]

                for emoji in emojis_to_add:
                    try:
                        slack_web.reactions_add(
                            channel=slack_channel,
                            name=emoji,
                            timestamp=msg_ts,
                        )
                    except Exception as e:
                        print(f"  ⚠️ Failed to add reaction {emoji}: {e}")

                # Persist tracking data so the Slack bot (pipeline_control.py)
                # can handle the reaction when the user clicks
                save_discovery_message(msg_ts, ideas, saved_record_ids)
                print(f"\n✅ Interactive Slack message posted (ts={msg_ts})")
                print(f"   {len(option_map)} options with emoji reactions — waiting for your choice!")
            else:
                print("\n⚠️ Slack message posted but couldn't get timestamp for reactions")

        except Exception as e:
            print(f"\n⚠️ Could not send interactive Slack notification: {e}")
            # Fallback: send plain message
            try:
                pipeline.slack.send_message(format_ideas_for_slack(result))
                print("   Sent plain Slack message as fallback")
            except Exception:
                pass

        return

    if len(sys.argv) > 1 and sys.argv[1] == "--sync":
        # Sync assets for a specific video
        # Hardcoded for now or args? User wants specific video.
        title = "The 2030 Currency Collapse: Which Assets Will YOU Still Own?"
        await pipeline.sync_all_assets(title)
        return
        
    if len(sys.argv) > 1 and sys.argv[1] == "--remotion":
        # Export Remotion props for a specific video
        import json
        from pathlib import Path

        # Get title from args or use default
        if len(sys.argv) > 2:
            title = " ".join(sys.argv[2:])
        else:
            title = "The 2030 Currency Collapse: Which Assets Will YOU Still Own?"

        print(f"\n📦 REMOTION EXPORT: Packaging '{title}'...")

        # Load the idea to set video_title
        ideas = pipeline.airtable.get_all_ideas()
        for idea in ideas:
            if idea.get("Video Title") == title:
                pipeline._load_idea(idea)
                break

        if not pipeline.video_title:
            print(f"❌ Error: Could not find video '{title}'")
            return

        # Generate segment data for word-synced image display
        remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"
        print(f"\n📝 Generating segmentData.ts...")
        pipeline.generate_segment_data_ts(remotion_dir)

        # Package props
        props = await pipeline.package_for_remotion()

        # Write to JSON file in remotion folder
        output_path = remotion_dir / "props.json"
        with open(output_path, "w") as f:
            json.dump(props, f, indent=2)

        print(f"\n✅ Remotion export complete!")
        print(f"   Props: {output_path}")
        print(f"   Scenes: {len(props.get('scenes', []))}")

        # Count segments with data
        total_segments = sum(
            len([img for img in scene.get("images", []) if img.get("segmentText")])
            for scene in props.get("scenes", [])
        )
        print(f"   Segments with text: {total_segments}")
        return
    
    if len(sys.argv) > 1 and sys.argv[1] == "--regenerate":
        # Regenerate missing or specific images
        print("=" * 60)
        print("🔄 REGENERATE IMAGES")
        print("=" * 60)

        # Get video title (required)
        if len(sys.argv) < 3:
            print("\nUsage:")
            print('  python pipeline.py --regenerate "Video Title"')
            print('  python pipeline.py --regenerate "Video Title" --scenes 3,4')
            print('  python pipeline.py --regenerate "Video Title" --images 3:4,4:7')
            print("\nExamples:")
            print('  # Regenerate all missing images')
            print('  python pipeline.py --regenerate "The 2030 Currency Collapse"')
            print('  # Regenerate all images in scenes 3 and 4')
            print('  python pipeline.py --regenerate "Title" --scenes 3,4')
            print('  # Regenerate specific images (Scene_03_04.png and Scene_04_07.png)')
            print('  python pipeline.py --regenerate "Title" --images 3:4,4:7')
            return

        title = sys.argv[2]
        scene_list = None
        image_indices = None

        # Parse optional args
        if "--scenes" in sys.argv:
            idx = sys.argv.index("--scenes")
            if idx + 1 < len(sys.argv):
                scene_list = [int(s) for s in sys.argv[idx + 1].split(",")]
                print(f"  Targeting scenes: {scene_list}")

        if "--images" in sys.argv:
            idx = sys.argv.index("--images")
            if idx + 1 < len(sys.argv):
                pairs = sys.argv[idx + 1].split(",")
                image_indices = []
                for pair in pairs:
                    scene, index = pair.split(":")
                    image_indices.append((int(scene), int(index)))
                print(f"  Targeting images: {image_indices}")

        # Load the video
        ideas = pipeline.airtable.get_all_ideas()
        for idea in ideas:
            if idea.get("Video Title") == title:
                pipeline._load_idea(idea)
                break

        if not pipeline.video_title:
            print(f"❌ Error: Could not find video '{title}'")
            return

        result = await pipeline.regenerate_images(scene_list=scene_list, image_indices=image_indices)
        print(f"\n✅ Regeneration complete: {result.get('regenerated', 0)} images")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--animate":
        # Generate video clips from images using Grok Imagine
        print("=" * 60)
        print("🎬 ANIMATION PIPELINE - Video Generation")
        print("=" * 60)

        if len(sys.argv) < 3:
            print("\nUsage:")
            print('  python pipeline.py --animate "Video Title"')
            print('  python pipeline.py --animate "Video Title" --estimate')
            print('  python pipeline.py --animate "Video Title" --scene 1')
            print('  python pipeline.py --animate "Video Title" --heroes-only')
            print("\nOptions:")
            print("  --estimate     Show cost estimate only (no generation)")
            print("  --scene N      Only process images from scene N")
            print("  --heroes-only  Only generate hero shots (max 3, 10s each)")
            print("\nExamples:")
            print('  python pipeline.py --animate "The 2030 Currency Collapse"')
            print('  python pipeline.py --animate "Title" --estimate')
            print('  python pipeline.py --animate "Title" --heroes-only')
            return

        title = sys.argv[2]

        # Find and load the video
        ideas = pipeline.airtable.get_all_ideas()
        for idea in ideas:
            if idea.get("Video Title") == title:
                pipeline._load_idea(idea)
                break

        if not pipeline.video_title:
            print(f"❌ Video not found: {title}")
            return

        # Cost estimation
        estimate = pipeline.estimate_video_generation_cost()
        print(f"\n📊 Cost Estimate for '{title}':")
        print(f"   Total images: {estimate['total_images']}")
        print(f"   Hero shots (10s): {estimate['hero_shots']}")
        print(f"   Standard shots (6s): {estimate['standard_shots']}")
        print(f"   ─────────────────────")
        print(f"   TOTAL COST: ${estimate['total_cost']:.2f}")

        if "--estimate" in sys.argv:
            print("\n   (Estimate only - no generation performed)")
            if estimate.get('hero_ids'):
                print(f"\n   Hero shot IDs: {estimate['hero_ids']}")
            return

        # Confirmation for high cost
        if estimate['total_cost'] > 5.0:
            print(f"\n⚠️ Cost exceeds $5. Type 'yes' to proceed:")
            confirm = input("   > ").strip().lower()
            if confirm != "yes":
                print("   Cancelled.")
                return

        # Parse filter options
        scene_filter = None
        heroes_only = "--heroes-only" in sys.argv

        if "--scene" in sys.argv:
            idx = sys.argv.index("--scene")
            if idx + 1 < len(sys.argv):
                scene_filter = int(sys.argv[idx + 1])
                print(f"\n   Scene filter: {scene_filter}")

        # Run video generation
        print(f"\n🎬 Starting video generation...")
        result = await pipeline.run_video_animation_pipeline(
            scene_filter=scene_filter,
            heroes_only=heroes_only,
        )

        print(f"\n✅ Generated {result.get('videos_generated', 0)} video clips")
        print(f"   Actual cost: ${result.get('actual_cost', 0):.2f}")
        return

    # === BRIEF TRANSLATOR ===
    if len(sys.argv) > 1 and sys.argv[1] == "--translate":
        # Run brief translator on the current idea
        print("=" * 60)
        print("📜 BRIEF TRANSLATOR - Research Brief → Script + Scenes")
        print("=" * 60)
        result = await pipeline.run_brief_translator()
        print(f"\nResult: {result.get('status', 'unknown')}")
        if result.get("scene_filepath"):
            print(f"Scene file: {result['scene_filepath']}")
        return

    # === STYLED IMAGE PROMPTS ===
    if len(sys.argv) > 1 and sys.argv[1] == "--styled-prompts":
        # Run image prompt engine with visual identity system
        scene_file = sys.argv[2] if len(sys.argv) > 2 else None
        result = await pipeline.run_styled_image_prompts(scene_filepath=scene_file)
        return

    # === FULL PIPELINE ===
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        if len(sys.argv) < 3:
            print('Usage: python pipeline.py --full "YouTube URL or concept"')
            return
        input_text = " ".join(sys.argv[2:])
        result = await pipeline.run_full_pipeline(input_text)
        return

    # === PRODUCE MODE ===
    if len(sys.argv) > 1 and sys.argv[1] == "--produce":
        idea_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = await pipeline.run_produce_pipeline(idea_record_id=idea_id)
        return

    # === FROM-STAGE MODE ===
    if len(sys.argv) > 1 and sys.argv[1] == "--from-stage":
        if len(sys.argv) < 3:
            print("Usage: python pipeline.py --from-stage <stage>")
            print("Stages: scripting, voice, image_prompts, images, video_scripts, video_gen, thumbnail, render")
            return
        stage = sys.argv[2]
        result = await pipeline.run_from_stage(stage)
        return

    # === RENDER ONLY ===
    if len(sys.argv) > 1 and sys.argv[1] == "--render":
        print("=" * 60)
        print("🎬 RENDER MODE - Render Only (skips other stages)")
        print("=" * 60)

        ideas = pipeline.airtable.get_ideas_by_status(
            pipeline.STATUS_READY_TO_RENDER, limit=10
        )

        if not ideas:
            print("\n❌ No ideas with status 'Ready To Render'")
            return

        print(f"\n📋 Found {len(ideas)} video(s) to render:")
        for i, idea in enumerate(ideas, 1):
            print(f"   {i}. {idea.get('Video Title', 'Untitled')}")

        rendered = 0
        for i, idea in enumerate(ideas, 1):
            title = idea.get("Video Title", "Untitled")
            print(f"\n{'=' * 60}")
            print(f"🎬 RENDERING {i}/{len(ideas)}: {title}")
            print(f"{'=' * 60}")

            pipeline._load_idea(idea)
            result = await pipeline._run_step_safe("Render Bot", pipeline.run_render_bot)

            if result.get("status") == "failed" or result.get("error"):
                print(f"\n❌ Render failed for '{title}': {result.get('error')}")
                print(f"   Stopping — fix this video before rendering the rest.")
                break

            rendered += 1
            print(f"\n✅ '{title}' rendered and uploaded!")
            print(f"   🔗 {result.get('video_url', 'N/A')}")

        print(f"\n{'=' * 60}")
        print(f"📋 RENDER COMPLETE: {rendered}/{len(ideas)} video(s) rendered")
        print("=" * 60)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--run-queue":
        # Process ALL videos in pipeline until nothing left to do
        # Scans all Airtable tables and processes every stage:
        # Ready For Scripting → Script → Voice → Image Prompts → Images → Thumbnail → Ready To Render
        # STOPS on any error — never silently advances past failures
        print("=" * 60)
        print("🔄 PIPELINE QUEUE MODE - Processing All Stages To Render")
        print("=" * 60)

        # PRE-FLIGHT: Process any ideas stuck at "Approved" status
        # This catches ideas approved via Airtable or emoji reactions where
        # research hasn't been triggered yet
        print("\n🔍 Pre-flight: Checking for ideas needing research...")
        try:
            from approval_watcher import ApprovalWatcher
            watcher = ApprovalWatcher(
                anthropic_client=pipeline.anthropic,
                airtable_client=pipeline.airtable,
                slack_client=pipeline.slack,
            )
            approved_results = await watcher.check_and_process()
            if approved_results:
                print(f"  ✅ Researched {len(approved_results)} approved idea(s)")
                for r in approved_results:
                    print(f"     → {r.get('headline', 'N/A')}")
            else:
                print("  No pending approvals found")
        except Exception as e:
            print(f"  ⚠️ Approval pre-flight failed: {e}")
            # Non-fatal — continue with pipeline

        print("\nScanning all tables for work. Processing stages:")
        print("  Script → Voice → Image Prompts → Images → Thumbnail → Render → Done")
        print("  Videos at 'Idea Logged' are SKIPPED (awaiting your approval)\n")

        # Notify Slack that the daily pipeline run has started
        try:
            # Quick scan of what's in the pipeline
            status_summary = []
            for status_name in [
                pipeline.STATUS_READY_SCRIPTING,
                pipeline.STATUS_READY_VOICE,
                pipeline.STATUS_READY_IMAGE_PROMPTS,
                pipeline.STATUS_READY_IMAGES,
                pipeline.STATUS_READY_THUMBNAIL,
                pipeline.STATUS_READY_TO_RENDER,
            ]:
                ideas_at_status = pipeline.airtable.get_ideas_by_status(status_name, limit=10)
                if ideas_at_status:
                    titles = [i.get("Video Title", "Untitled")[:40] for i in ideas_at_status]
                    status_summary.append(f"  • *{status_name}*: {', '.join(titles)}")

            if status_summary:
                pipeline.slack.send_message(
                    "🔄 *8 AM Pipeline Run Starting*\n"
                    "Scanning all tables and processing every stage through to Done (including render).\n\n"
                    "*Work found:*\n" + "\n".join(status_summary)
                )
            else:
                pipeline.slack.send_message(
                    "🔄 *8 AM Pipeline Run Starting*\n"
                    "Scanning tables... no videos currently queued for processing."
                )
        except Exception:
            pass

        processed = 0
        steps_log = []  # Track what was done for the summary
        max_iterations = 100  # Safety limit

        while processed < max_iterations:
            try:
                result = await pipeline.run_next_step()
            except Exception as e:
                # Uncaught exception — stop pipeline and report
                error_msg = f"Pipeline crashed: {e}"
                print(f"\n❌ {error_msg}")
                try:
                    pipeline.slack.send_message(f"❌ *Pipeline STOPPED* after {processed} steps\n```{error_msg}```")
                except Exception:
                    pass
                break

            if result.get("status") == "idle":
                print("\n✅ Queue empty! All approved videos processed.")
                try:
                    if processed > 0:
                        summary_lines = "\n".join(f"  • {s}" for s in steps_log[-10:])
                        pipeline.slack.send_message(
                            f"✅ *Pipeline queue complete!* {processed} steps processed.\n\n"
                            f"*Steps completed:*\n{summary_lines}\n\n"
                            f"All videos have been processed through to their next stage."
                        )
                    else:
                        pipeline.slack.send_message(
                            "✅ *Pipeline queue complete* — nothing to process. "
                            "All videos are either at Idea Logged (awaiting approval) or already Done."
                        )
                except Exception:
                    pass
                break

            # CHECK FOR ERRORS — stop pipeline if any step failed
            if result.get("status") == "failed" or result.get("error"):
                error_msg = result.get("error", "Unknown error")
                bot_name = result.get("bot", "Unknown")
                video_title = result.get("video_title", "Unknown")
                print(f"\n❌ PIPELINE STOPPED — {bot_name} failed for '{video_title}'")
                print(f"   Error: {error_msg}")
                print(f"   Steps completed before failure: {processed}")
                print(f"\n   Fix the issue and run again. Status was NOT advanced.")
                try:
                    pipeline.slack.send_message(
                        f"❌ *Pipeline STOPPED* — {bot_name} failed\n"
                        f"Video: *{video_title}*\n"
                        f"Error: {error_msg}\n"
                        f"Steps completed: {processed}\n"
                        f"Status was NOT advanced. Fix and re-run."
                    )
                except Exception:
                    pass
                break

            processed += 1
            bot_name = result.get('bot', 'Unknown')
            video_title = result.get('video_title', 'Unknown')
            new_status = result.get('new_status', 'Unknown')
            steps_log.append(f"{bot_name}: _{video_title}_ → {new_status}")

            print(f"\n--- Completed step {processed} ---")
            print(f"    Video: {video_title}")
            print(f"    Bot: {bot_name}")
            print(f"    New Status: {new_status}")

            # Small delay between steps to avoid rate limits
            await asyncio.sleep(2)

        print("\n" + "=" * 60)
        print(f"📋 QUEUE COMPLETE: {processed} steps processed")
        print("=" * 60)
        return

    print("=" * 60)
    print("🎬 VIDEO PIPELINE - Running Next Step")
    print("=" * 60)
    
    result = await pipeline.run_next_step()
    
    print("\n" + "=" * 60)
    print("📋 RESULT:")
    for key, value in result.items():
        print(f"   {key}: {value}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
