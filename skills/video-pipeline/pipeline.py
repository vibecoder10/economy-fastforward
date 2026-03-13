"""
Video Production Pipeline Orchestrator

STATUS-DRIVEN WORKFLOW:
The pipeline strictly follows Airtable Ideas table status:
1.  Idea Logged              - New idea, waiting to be picked up
2.  Ready For Scripting      - Script Bot will run
3.  Ready For Voice          - Voice Bot will run
4.  Ready For Image Prompts  - Image Prompt Bot will run
5.  Ready For Images         - Image Bot will run
6.  Ready For Video Scripts  - Video Script Bot will run
7.  Ready For Video Generation - Video Gen Bot will run
8.  Ready For Thumbnail      - Thumbnail Bot will run
9.  Ready To Render          - Render Bot will run
10. Done                     - All production assets complete, triggers render
11. Rendered                 - Video rendered, triggers SEO + YouTube upload
12. Uploaded (Draft)         - Unlisted YouTube draft, awaiting manual publish
13. In Que                   - Waiting in queue

RULES:
- Always check Ideas table status FIRST
- Only process ONE video at a time
- Each bot checks for its required status before running
"""

import os
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo
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
from clients.sound_client import SoundClient
from bots.idea_bot import IdeaBot
from bots.trending_idea_bot import TrendingIdeaBot
from bots.sound_prompt_bot import SoundPromptBot
from bots.sound_bot import SoundBot
from bots.prompt_validator import PromptValidator, format_validation_report
from pipeline_config import VideoConfig
from segmentation_engine import enforce_duration_caps, recalculate_durations
from image_prompt_engine.prompt_builder import (
    CAMERA_MOVEMENTS,
    detect_camera_movement,
    validate_video_prompt,
)


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
    STATUS_READY_SOUND_DESIGN = "Ready For Sound Design"
    STATUS_READY_SOUND_EFFECTS = "Ready For Sound Effects"
    STATUS_READY_IMAGE_PROMPTS = "Ready For Image Prompts"
    STATUS_READY_IMAGES = "Ready For Images"
    STATUS_READY_VIDEO_SCRIPTS = "Ready For Video Scripts"
    STATUS_READY_VIDEO_GENERATION = "Ready For Video Generation"
    STATUS_READY_THUMBNAIL = "Ready For Thumbnail"
    STATUS_DONE = "Done"
    STATUS_READY_TO_RENDER = "Ready To Render"
    STATUS_RENDERED = "Rendered"
    STATUS_UPLOADED_DRAFT = "Uploaded (Draft)"
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
        # Sound effect client (optional — may not have API key configured)
        try:
            self.sound_client = SoundClient()
        except ValueError:
            self.sound_client = None
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
        self.video_config: Optional[VideoConfig] = None
        self.visual_style: Optional[str] = None

        # Targeting filters — when set, bots only process matching records
        # and do NOT advance status (partial run for testing)
        self.scene_filter: Optional[int] = None
        self.image_filter: Optional[int] = None
    
    @property
    def _is_targeted_run(self) -> bool:
        """True if scene/image filters are set (partial run, don't advance status)."""
        return self.scene_filter is not None or self.image_filter is not None

    def _log_filters(self):
        """Print active targeting filters."""
        if self.scene_filter is not None and self.image_filter is not None:
            print(f"  🎯 TARGETED RUN: Scene {self.scene_filter}, Image {self.image_filter}")
        elif self.scene_filter is not None:
            print(f"  🎯 TARGETED RUN: Scene {self.scene_filter} (all images)")
        # No filter = process everything (normal behavior)

    def _filter_by_scene(self, records: list, scene_key: str = "Scene") -> list:
        """Filter records by scene_filter and image_filter if set."""
        if self.scene_filter is not None:
            records = [r for r in records if r.get(scene_key) == self.scene_filter]
        if self.image_filter is not None:
            records = [r for r in records if r.get("Image Index") == self.image_filter]
        return records

    def get_idea_by_status(self, status: str) -> Optional[dict]:
        """Get ONE idea with the specified status."""
        ideas = self.airtable.get_ideas_by_status(status, limit=1)
        if ideas:
            return ideas[0]
        return None
    
    def _update_status(self, new_status: str):
        """Update idea status in Airtable AND sync the in-memory cache.

        Every status transition MUST go through this method so that
        chained stages (e.g. prompts → images on the same pipeline
        instance) see the correct status.
        """
        self.airtable.update_idea_status(self.current_idea_id, new_status)
        if self.current_idea:
            self.current_idea["Status"] = new_status

    def _load_idea(self, idea: dict):
        """Load idea data into pipeline state."""
        self.current_idea = idea
        self.current_idea_id = idea.get("id")
        self.video_title = idea.get("Video Title", "Untitled")

        # Restore saved Google Drive folder ID (avoids name-based search issues)
        saved_folder_id = idea.get("Drive Folder ID")
        if saved_folder_id:
            self.project_folder_id = saved_folder_id

        # Extract Core Image URL from the idea/project record
        core_image_attachments = idea.get("Core Image", [])
        if core_image_attachments and isinstance(core_image_attachments, list):
            self.core_image_url = core_image_attachments[0].get("url", "")
        else:
            self.core_image_url = ""

        # Instantiate VideoConfig from Airtable fields (defaults to 10min/10s)
        try:
            self.video_config = VideoConfig.from_airtable_record(idea)
        except (ValueError, TypeError):
            self.video_config = VideoConfig()  # safe defaults

        # Load visual style from Airtable (for visual profile selection)
        from clients.airtable_client import get_visual_style
        self.visual_style = get_visual_style(idea)
        # Set env var so load_profile() picks it up everywhere in the pipeline
        os.environ["VISUAL_PROFILE"] = self.visual_style

        print(f"\n📌 Loaded idea: {self.video_title}")
        print(f"   Status: {idea.get('Status')}")
        print(f"   ID: {self.current_idea_id}")
        print(f"   🎬 {self.video_config.summary().splitlines()[0]}")
        print(f"   🎨 Visual style: {self.visual_style}")
        if self.project_folder_id:
            print(f"   📂 Drive Folder: {self.project_folder_id}")
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
            # All images done — sound design comes next (reads Image Prompt from Images table)
            suggested_status = self.STATUS_READY_SOUND_DESIGN
        
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
    MANUAL_ONLY_VIDEO_GEN = True  # Video prompts + generation run via Slack commands (cost control)
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
                self._update_status(suggested)
                # Restart loop to pick up new status
                return await self.run_next_step()

            return await self._run_step_safe("Brief Translator", self.run_brief_translator)

        # 2. Check for Ready For Voice
        idea = self.get_idea_by_status(self.STATUS_READY_VOICE)
        if idea:
            self._load_idea(idea)
            # CHECK: Has work already been done?
            work_status = self.check_existing_work(self.video_title)
            suggested = work_status["suggested_status"]

            if suggested and suggested != self.STATUS_READY_VOICE:
                print(f"  ⚠️ Found existing work! Fast-forwarding status to: {suggested}")
                self._update_status(suggested)
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
                self._update_status(suggested)
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
                self._update_status(suggested)
                return await self.run_next_step()

            return await self._run_step_safe("Image Bot", self.run_image_bot)

        # 4b. Check for Ready For Sound Design (AFTER images — needs Image Prompt field)
        idea = self.get_idea_by_status(self.STATUS_READY_SOUND_DESIGN)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Sound Prompt Bot", self.run_sound_prompt_bot)

        # 4c. Check for Ready For Sound Effects
        idea = self.get_idea_by_status(self.STATUS_READY_SOUND_EFFECTS)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Sound Bot", self.run_sound_bot)

        # 5. Video Scripts (generates motion prompts, ~$0.10/image)
        idea = self.get_idea_by_status(self.STATUS_READY_VIDEO_SCRIPTS)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Video Script Bot", self.run_video_script_bot)

        # 6. Video Generation (generates clips from motion prompts, ~$0.10/clip)
        idea = self.get_idea_by_status(self.STATUS_READY_VIDEO_GENERATION)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Video Gen Bot", self.run_video_gen_bot)

        # 7. Check for Ready For Thumbnail
        idea = self.get_idea_by_status(self.STATUS_READY_THUMBNAIL)
        if idea:
            self._load_idea(idea)
            # CHECK: Has work already been done?
            work_status = self.check_existing_work(self.video_title)
            suggested = work_status["suggested_status"]

            if suggested and suggested != self.STATUS_READY_THUMBNAIL:
                print(f"  ⚠️ Found existing work! Fast-forwarding status to: {suggested}")
                self._update_status(suggested)
                return await self.run_next_step()

            return await self._run_step_safe("Thumbnail Bot", self.run_thumbnail_bot)

        # 8. Check for Done — transition to Ready To Render for rendering
        idea = self.get_idea_by_status(self.STATUS_DONE)
        if idea:
            self._load_idea(idea)
            print(f"  Video at 'Done', transitioning to 'Ready To Render': {self.video_title}")
            self._update_status(self.STATUS_READY_TO_RENDER)
            return await self.run_next_step()

        # 9. Render Bot — one at a time, cleans assets between renders
        idea = self.get_idea_by_status(self.STATUS_READY_TO_RENDER)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Render Bot", self.run_render_bot)

        # 10. YouTube Upload Bot — generate SEO + upload as unlisted draft
        idea = self.get_idea_by_status(self.STATUS_RENDERED)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("YouTube Upload Bot", self.run_youtube_upload_bot)

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
            self.slack.notify(
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

    async def run_script_bot_legacy(self) -> dict:
        """Write the full script (legacy 20-scene beat-sheet path).

        DEPRECATED: Use run_brief_translator() instead. Kept for reference.

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
        self._log_filters()

        # Get or create project folder in Google Drive (avoid duplicates on re-runs)
        folder = self.google.get_or_create_folder(self.video_title)
        self.project_folder_id = folder["id"]

        # Store Drive folder link and ID in Airtable for all subsequent stages
        folder_url = f"https://drive.google.com/drive/folders/{self.project_folder_id}"
        self.airtable.update_idea_fields(self.current_idea_id, {
            "Drive Folder Link": folder_url,
            "Drive Folder ID": self.project_folder_id,
        })

        # Create Google Doc for script (graceful fallback if API unavailable)
        doc = self.google.create_document(self.video_title, self.project_folder_id)
        self.google_doc_id = doc["id"]  # May be None if unavailable
        docs_available = not doc.get("unavailable", False)
        if not docs_available:
            print("  ⚠️  Google Docs unavailable - scripts will be saved to Airtable only")

        # Generate beat sheet
        beat_sheet = await self.anthropic.generate_beat_sheet(self.current_idea)
        scenes = beat_sheet.get("script_outline", [])

        # Apply scene filter if set
        if self.scene_filter is not None:
            scenes = [s for s in scenes if s.get("scene_number") == self.scene_filter]

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
        
        # UPDATE STATUS (skip if targeted run)
        if self._is_targeted_run:
            print(f"  🎯 Targeted run — status NOT advanced")
            doc_url = self.google.get_document_url(self.google_doc_id)
            return {
                "bot": "Script Bot",
                "video_title": self.video_title,
                "scene_count": len(scenes),
                "targeted": True,
            }

        self._update_status(self.STATUS_READY_VOICE)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VOICE}")

        # Phase 2: Refine title with script content (non-blocking)
        await self._refine_title_post_script()

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
    
    async def _refine_title_post_script(self):
        """Phase 2 title refinement — non-blocking post-script step.

        Reads the actual script content and regenerates title candidates
        using the formula library + specific details from the script.
        Updates Video Title if a better option is found.

        Has a 30-second timeout to prevent pipeline stalls.
        """
        from research_agent import refine_title_post_script

        try:
            result = await asyncio.wait_for(
                refine_title_post_script(
                    anthropic_client=self.anthropic,
                    airtable_client=self.airtable,
                    record_id=self.current_idea_id,
                ),
                timeout=30.0,
            )
            if result.get("should_switch"):
                old_title = result["old_title"]
                new_title = result["new_title"]
                self.video_title = new_title
                print(
                    f"  📝 Title refined: '{old_title}' → '{new_title}' "
                    f"(score: {result.get('score', '?')})"
                )
                try:
                    self.slack.send_message(
                        f"📝 Title refined for *{old_title}*\n"
                        f"→ New title: *{new_title}* (score: {result.get('score', '?')})\n"
                        f"→ Thumbnail: {result.get('thumbnail_text', '')}"
                    )
                except Exception:
                    pass  # Slack notification is non-blocking
            else:
                print(f"  📝 Title refinement: kept current title (no better option found)")
        except Exception as e:
            # Non-blocking — title refinement failure should NOT stop the pipeline
            print(f"  ⚠️ Title refinement failed (non-blocking): {e}")

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
        self._log_filters()

        # Get or create project folder
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]

        # Get scripts for this video
        scripts = self.airtable.get_scripts_by_title(self.video_title)

        if not scripts:
            return {"error": f"No scripts found for: {self.video_title}"}

        # Apply scene filter
        if self.scene_filter is not None:
            scripts = [s for s in scripts if s.get("scene") == self.scene_filter]

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
        
        # UPDATE STATUS (skip if targeted run)
        if self._is_targeted_run:
            print(f"  🎯 Targeted run — status NOT advanced")
            return {"bot": "Voice Bot", "video_title": self.video_title, "voice_count": voice_count, "targeted": True}

        # Sound design runs AFTER images exist (needs Image Prompt + Sentence Text)
        self._update_status(self.STATUS_READY_IMAGE_PROMPTS)
        print(f"  ✅ Status updated to: {self.STATUS_READY_IMAGE_PROMPTS}")

        self.slack.notify_voice_done()

        return {
            "bot": "Voice Bot",
            "video_title": self.video_title,
            "voice_count": voice_count,
            "new_status": self.STATUS_READY_IMAGE_PROMPTS,
        }

    async def run_sound_prompt_bot(self) -> dict:
        """Generate sound prompts for all image rows via Claude Haiku.

        REQUIRES: Ideas status = "Ready For Sound Design"
        UPDATES TO: "Ready For Sound Effects" when complete

        Sound prompts are per-image (not per-scene). Each image in the
        Images table gets one ambient sound description based on its
        narration text and visual description.
        """
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_SOUND_DESIGN)
            if not idea:
                return {"error": "No idea with status 'Ready For Sound Design'"}
            self._load_idea(idea)

        if self.current_idea.get("Status") != self.STATUS_READY_SOUND_DESIGN:
            return {"error": f"Idea status is '{self.current_idea.get('Status')}', expected 'Ready For Sound Design'"}

        self.slack.notify("🎧 Starting sound design for: " + self.video_title)
        print(f"\n🎧 SOUND PROMPT BOT: Processing '{self.video_title}'")

        bot = SoundPromptBot(anthropic=self.anthropic, airtable=self.airtable)
        result = await bot.process_video(self.video_title)

        if result.get("error"):
            return result

        # Update status
        self._update_status(self.STATUS_READY_SOUND_EFFECTS)
        print(f"  ✅ Status updated to: {self.STATUS_READY_SOUND_EFFECTS}")

        self.slack.notify(
            f"✅ Sound prompts complete for *{self.video_title}*: "
            f"{result.get('prompts_generated', 0)}/{result.get('total_images', 0)} images"
        )

        result["new_status"] = self.STATUS_READY_SOUND_EFFECTS
        return result

    async def run_sound_bot(self) -> dict:
        """Generate sound effect audio for all image rows.

        REQUIRES: Ideas status = "Ready For Sound Effects"
        UPDATES TO: "Ready For Image Prompts" when complete

        For each image with a Sound Prompt but no Sound Effect,
        generates an 8-second MP3 and attaches it to the image row.
        """
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_SOUND_EFFECTS)
            if not idea:
                return {"error": "No idea with status 'Ready For Sound Effects'"}
            self._load_idea(idea)

        if self.current_idea.get("Status") != self.STATUS_READY_SOUND_EFFECTS:
            return {"error": f"Idea status is '{self.current_idea.get('Status')}', expected 'Ready For Sound Effects'"}

        self.slack.notify("🔊 Generating sound effects for: " + self.video_title)
        print(f"\n🔊 SOUND BOT: Processing '{self.video_title}'")

        # Get or create project folder
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]

        bot = SoundBot(
            sound_client=self.sound_client or SoundClient(),
            airtable=self.airtable,
            google=self.google,
            slack=self.slack,
        )
        result = await bot.process_video(self.video_title, folder_id=self.project_folder_id)

        if result.get("error"):
            return result

        # Update status — sound is done, move to video prompts
        self._update_status(self.STATUS_READY_VIDEO_SCRIPTS)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VIDEO_SCRIPTS}")

        self.slack.notify(
            f"✅ Generated {result.get('total_generated', 0)} sound effects for *{self.video_title}* "
            f"(~${result.get('estimated_cost', 0):.2f})"
        )

        result["new_status"] = self.STATUS_READY_VIDEO_SCRIPTS
        return result

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
            # YouTube pipeline uses cinematic photorealistic dossier style
            concepts = await self.anthropic.segment_scene_into_concepts(
                scene_text=scene_text,
                target_count=target_images,
                min_count=min_images,
                max_count=max_images,
                words_per_segment=words_per_segment,
                scene_number=scene_number,
                pipeline_type="youtube",
            )

            # Enforce hard duration caps before creating records
            config = self.video_config or VideoConfig.from_airtable_record(self.current_idea or {})
            clip_dur = config.clip_duration_seconds
            pre_count = len(concepts)
            concepts = enforce_duration_caps(concepts, clip_duration_seconds=clip_dur)
            concepts = recalculate_durations(concepts, clip_duration_seconds=clip_dur)
            if len(concepts) != pre_count:
                print(f"    Duration cap: {pre_count} → {len(concepts)} segments (max {clip_dur}s)")

            # Create records with calculated durations (capped at clip_dur range)
            cumulative_start = 0.0
            for i, concept in enumerate(concepts):
                concept_text = concept.get("text", "")
                concept_words = len(concept_text.split())
                concept_duration = concept_words / words_per_second if words_per_second > 0 else 8.0

                # ENFORCE duration range — floor 4s, ceiling = clip_duration
                concept_duration = max(4.0, min(float(clip_dur), concept_duration))

                # Get shot_type from segment (now included in output)
                shot_type = concept.get("shot_type", "medium_human_story")

                # Skip if this exact (scene, index) already exists
                if (scene_number, i + 1) in existing_scene_indices:
                    print(f"      Skipping Scene {scene_number}, Index {i + 1} - already exists")
                    continue

                self.airtable.create_concept_record(
                    scene_number=scene_number,
                    concept_index=i + 1,
                    sentence_text=concept_text,
                    image_prompt=concept.get("image_prompt", ""),
                    composition=shot_type or "medium",
                    video_title=self.video_title,
                )
                cumulative_start += concept_duration
                total_prompts += 1

            print(f"    ✅ Created {len(concepts)} prompts for scene {scene_number}")

            # Slack progress update every 5 scenes
            if scene_number % 5 == 0:
                self.slack.notify(f"📝 Prompt progress: {total_prompts} prompts created (through Scene {scene_number})")

        # Flag hero shots after all prompts are created
        hero_count = await self._flag_hero_shots()
        print(f"  🌟 Flagged {hero_count} hero shots")

        self._update_status(self.STATUS_READY_IMAGES)

        print(f"\n  ✅ Total: {total_prompts} image prompts created")

        # Slack completion
        self.slack.notify(f"✅ Image prompts done: {total_prompts} created for *{self.video_title}*")

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
        self._log_filters()

        # Get or create project folder
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]

        # Run the internal image bot
        result = await self._run_image_bot()

        # Targeted run — don't verify or advance status
        if self._is_targeted_run:
            print(f"  🎯 Targeted run — status NOT advanced")
            return {
                "bot": "Image Bot",
                "video_title": self.video_title,
                "image_count": result.get("image_count", 0),
                "targeted": True,
            }

        # VERIFY all images are actually complete before advancing status
        all_images = self.airtable.get_all_images_for_video(self.video_title)
        pending = [img for img in all_images if img.get("Status") != "Done" and img.get("Image Prompt")]
        total = len([img for img in all_images if img.get("Image Prompt")])

        if not all_images or total == 0:
            error_msg = f"No images found for '{self.video_title}' — cannot advance status"
            print(f"  ❌ {error_msg}")
            self.slack.notify(f"❌ Image Bot STOPPED: {error_msg}")
            return {
                "status": "failed",
                "bot": "Image Bot",
                "video_title": self.video_title,
                "error": error_msg,
            }

        if len(pending) > 0:
            error_msg = f"{len(pending)}/{total} images still pending after all retries for '{self.video_title}'"
            print(f"  ❌ {error_msg}")
            self.slack.notify(
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

        # ALL images verified complete — advance to sound design
        # Sound stages run AFTER images because sound_prompt_bot reads Image Prompt
        # and Sentence Text from the Images table rows.
        self._update_status(self.STATUS_READY_SOUND_DESIGN)
        print(f"  ✅ All {total} images verified complete. Status updated to: {self.STATUS_READY_SOUND_DESIGN}")

        return {
            "bot": "Image Bot",
            "video_title": self.video_title,
            "image_count": result.get("image_count", 0),
            "new_status": self.STATUS_READY_SOUND_DESIGN,
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
            self.slack.notify(f"❌ Visuals Pipeline STOPPED: {error_msg} for *{self.video_title}*")
            return {
                "status": "failed",
                "bot": "Visuals Pipeline",
                "video_title": self.video_title,
                "error": error_msg,
            }

        # ALL images verified complete — advance to sound design
        self._update_status(self.STATUS_READY_SOUND_DESIGN)
        print(f"  ✅ All {total} images verified complete. Status updated to: {self.STATUS_READY_SOUND_DESIGN}")

        return {
            "bot": "Visuals Pipeline",
            "video_title": self.video_title,
            "prompt_count": prompt_result.get("prompt_count", 0),
            "image_count": image_result.get("image_count", 0),
            "new_status": self.STATUS_READY_SOUND_DESIGN,
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

        # Apply scene/image filters
        pending_images = self._filter_by_scene(pending_images)
        total_pending = len(pending_images)

        if done_count > 0:
            print(f"     ♻️ RESUME: {done_count} images already done, {total_pending} remaining")
            self.slack.notify(f"♻️ Resuming: {done_count} images already done, {total_pending} remaining for *{self.video_title}*")
        else:
            print(f"     Found {total_pending} pending images")

        if total_pending == 0:
            print("     ⚠️ No pending images found — nothing to generate.")
            self.slack.notify(f"⚠️ Image Bot: 0 pending images found for *{self.video_title}*. Nothing to generate.")
            return {"image_count": 0, "failed_count": 0}

        # Check for image model override (hot-swap via Slack !model command)
        from clients.image_client import ImageClient
        from clients.airtable_client import get_image_model_override
        model_override = get_image_model_override(self.current_idea)
        if model_override and model_override not in ImageClient.VALID_SCENE_MODELS:
            print(f"     ⚠️ Invalid model override '{model_override}', falling back to default")
            model_override = ""
        if model_override:
            print(f"     🔄 Model override active: {model_override} ({ImageClient.VALID_SCENE_MODELS[model_override]})")

        # YouTube pipeline: Core Image is optional (uses text-to-image without reference)
        # Animation pipeline: Core Image is required (uses Seed Dream 4.5 Edit with reference)
        use_reference = bool(self.core_image_url) and model_override != "z-image"
        if model_override == "z-image":
            print(f"     🎨 Using Z Image model (text-to-image, no reference)")
        elif use_reference:
            print(f"     🖼️ Using Core Image reference (Seed Dream 4.5 Edit)")
        else:
            print(f"     📸 Using text-to-image generation (no Core Image reference)")

        self.slack.notify(f"🖼️ Starting image generation: {total_pending} images for *{self.video_title}*")

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
                    prompt_preview = prompt[:120] + "..." if len(prompt) > 120 else prompt

                    try:
                        # Generate image: route based on model override, then reference availability
                        if model_override == "z-image":
                            result = await self.image_client.generate_scene_image_zimage(prompt, aspect_ratio="16:9")
                        elif use_reference:
                            result = await self.image_client.generate_scene_image(prompt, self.core_image_url)
                        else:
                            result_urls = await self.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                            result = {"url": result_urls[0]} if result_urls and len(result_urls) > 0 else None

                        if result and result.get("url"):
                            image_url = result["url"]

                            # Download image
                            image_content = await self.image_client.download_image(image_url)

                            # Upload to Google Drive
                            filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                            drive_file = self.google.upload_image(image_content, filename, self.project_folder_id)
                            drive_download_url = self.google.make_file_public(drive_file["id"])

                            # CHECKPOINT: Update Airtable immediately (with Drive URL for animation)
                            self.airtable.update_image_record(record_id, image_url, drive_url=drive_download_url)
                            image_count += 1
                            print(f"      ✅ Scene {scene_num}, Image {index} → Done ({image_count}/{total_pending})")

                            # Slack progress update for every image
                            self.slack.notify(f"🖼️ Generating images... {image_count}/{total_pending} complete")

                            # Clear image content from memory
                            del image_content
                            return True
                        else:
                            failed_count += 1
                            print(f"      ❌ Scene {scene_num}, Image {index} → Generation failed (no image URL returned)")
                            print(f"         Record ID: {record_id}")
                            print(f"         Prompt: {prompt_preview}")
                            return False

                    except Exception as e:
                        failed_count += 1
                        print(f"      ❌ Scene {scene_num}, Image {index} → Error: {e}")
                        print(f"         Record ID: {record_id}")
                        print(f"         Prompt: {prompt_preview}")
                        import traceback
                        traceback.print_exc()
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
        self.slack.notify(status_msg)

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
            self.slack.notify(f"🔄 Retry {retry_round + 1}: {len(pending)} pending images for *{self.video_title}*")
            
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
                    
                    prompt_preview = prompt[:120] + "..." if len(prompt) > 120 else prompt
                    try:
                        if model_override == "z-image":
                            result = await self.image_client.generate_scene_image_zimage(prompt, aspect_ratio="16:9")
                        elif use_reference:
                            result = await self.image_client.generate_scene_image(prompt, self.core_image_url)
                        else:
                            result_urls = await self.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                            result = {"url": result_urls[0]} if result_urls and len(result_urls) > 0 else None
                        if result and result.get("url"):
                            image_url = result["url"]

                            # Download and upload to Drive
                            image_content = await self.image_client.download_image(image_url)
                            filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                            drive_file = self.google.upload_image(image_content, filename, self.project_folder_id)
                            drive_download_url = self.google.make_file_public(drive_file["id"])

                            # Update Airtable (with Drive URL for animation)
                            self.airtable.update_image_record(record_id, image_url, drive_url=drive_download_url)
                            retry_count += 1
                            image_count += 1
                            print(f"        ✅ Scene {scene_num}, Image {index} → Done (retry)")
                            del image_content
                        else:
                            print(f"        ❌ Scene {scene_num}, Image {index} → No image returned (retry)")
                            print(f"           Record ID: {record_id}")
                            print(f"           Prompt: {prompt_preview}")
                    except Exception as e:
                        print(f"        ❌ Scene {scene_num}, Image {index} → {e}")
                        print(f"           Record ID: {record_id}")
                        print(f"           Prompt: {prompt_preview}")
                        import traceback
                        traceback.print_exc()
                    
                    await asyncio.sleep(2)  # Rate limit
            
            print(f"    ✅ Retry {retry_round + 1} complete: {retry_count} recovered")
            if retry_count == 0:
                print(f"    ⚠️ No progress made, stopping retries")
                break

        # Final check
        final_images = self.airtable.get_all_images_for_video(self.video_title)
        final_pending = len([img for img in final_images if img.get("Status") != "Done" and img.get("Image Prompt")])
        if final_pending > 0:
            self.slack.notify(f"⚠️ {final_pending} images still pending after retries for *{self.video_title}*")
        else:
            self.slack.notify(f"✅ All {len(final_images)} images complete for *{self.video_title}*")

        return {"image_count": image_count, "failed_count": failed_count}

    async def run_video_script_bot(self) -> dict:
        """Generate video motion prompts for images."""
        target = f"Scene {self.scene_filter}" if self.scene_filter else "all scenes"
        print(f"\n  📝 VIDEO SCRIPT BOT: Generating prompts for {target}...")
        self._log_filters()

        # Get pending images
        existing_images = self.airtable.get_all_images_for_video(self.video_title)
        done_images = [img for img in existing_images if img.get("Status") == "Done"]

        # Apply scene/image filters
        done_images = self._filter_by_scene(done_images)

        # Sort by scene and image index for proper camera history ordering
        done_images = sorted(
            done_images,
            key=lambda x: (x.get("Scene", 0), x.get("Image Index", 0)),
        )

        prompt_count = 0
        hero_count = 0
        camera_history: list[str] = []

        # Pre-populate camera history from images that already have prompts
        for img_record in done_images:
            existing_prompt = img_record.get("Video Prompt", "")
            if existing_prompt:
                camera_history.append(detect_camera_movement(existing_prompt))

        for img_record in done_images:
            scene = img_record.get("Scene", 0)

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
                prev_cameras=camera_history,
            )

            # Validate video prompt quality — regenerate if it fails
            validation = validate_video_prompt(
                motion_prompt, sentence_text,
                prev_cameras=camera_history,
                clip_duration_seconds=clip_duration,
            )
            if not validation["valid"]:
                print(f"    ⚠️ Video prompt failed validation: {validation['issues']}")

                # Build camera-aware regeneration prompt
                camera_block = ""
                if camera_history:
                    blocked = camera_history[-1]
                    allowed = ", ".join(k for k in CAMERA_MOVEMENTS if k != blocked)
                    camera_block = (
                        f"\n\nCAMERA ROTATION: You MUST NOT use '{blocked}'. "
                        f"Pick from: {allowed}"
                    )

                regen_prompt = (
                    f'This video prompt failed quality validation: {validation["issues"]}\n\n'
                    f'Sentence text: "{sentence_text}"\n'
                    f'Original prompt: "{motion_prompt}"\n\n'
                    "Rewrite the video prompt following the Narrative Beat Method:\n"
                    "1. Identify the emotional beats in the sentence\n"
                    "2. Assign each beat a specific visual verb\n"
                    "3. Sequence motions to mirror the narration timeline\n"
                    "4. End with a strong payoff line that lands emotionally\n"
                    "5. Zero filler — every motion must serve the story"
                    f"{camera_block}"
                )
                motion_prompt = await self.anthropic.generate(
                    prompt=regen_prompt,
                    system_prompt="You are a cinematographer. Return ONLY the rewritten motion prompt. No explanations.",
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=200,
                )
                motion_prompt = motion_prompt.strip()
                print(f"    ✅ Regenerated video prompt for [{idx}]")

            # Track camera movement for rotation enforcement
            camera_history.append(detect_camera_movement(motion_prompt))

            # Update Airtable with video prompt
            self.airtable.update_image_video_prompt(img_record["id"], motion_prompt)
            prompt_count += 1

        print(f"    ✅ Generated {prompt_count} video prompts ({hero_count} hero shots @ 10s)")

        if self._is_targeted_run:
            print(f"  🎯 Targeted run — status NOT advanced")
            return {"bot": "Video Script Bot", "prompt_count": prompt_count, "targeted": True}

        # Update Status to Ready For Video Generation
        self._update_status(self.STATUS_READY_VIDEO_GENERATION)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VIDEO_GENERATION}")

        return {"bot": "Video Script Bot", "prompt_count": prompt_count, "new_status": self.STATUS_READY_VIDEO_GENERATION}

    async def run_video_gen_bot(self) -> dict:
        """Generate video clips from images with motion prompts."""
        print(f"\n  🎥 VIDEO GEN BOT: Generating videos...")
        self._log_filters()

        # Get images ready for video generation (with Video Prompt, no Video yet)
        pending_videos = self.airtable.get_images_ready_for_video_generation(self.video_title)

        # Only those with a Video Prompt
        pending_videos = [v for v in pending_videos if v.get("Video Prompt")]

        # Apply scene/image filters
        pending_videos = self._filter_by_scene(pending_videos)
        
        if not pending_videos:
            print("    No pending videos to generate.")
            if not self._is_targeted_run:
                print(f"    All videos done. Moving to Thumbnail.")
                self._update_status(self.STATUS_READY_THUMBNAIL)
            return {"video_count": 0, "new_status": self.STATUS_READY_THUMBNAIL}

        video_count = 0
        failed_count = 0
        total = len(pending_videos)
        print(f"    Found {total} images needing video generation.")

        # Concurrent generation with semaphore-based rate limiting
        MAX_CONCURRENT_VIDEOS = 3
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_VIDEOS)
        print(f"    Concurrency: {MAX_CONCURRENT_VIDEOS} parallel video generations")

        async def generate_single_video(i, img_record):
            """Generate, download, upload, and checkpoint a single video clip."""
            nonlocal video_count, failed_count

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
                return

            # Convert to direct download URL for Grok Imagine
            image_url = self.google.get_direct_drive_url(drive_url)

            # Hero selection: duration > 6s gets 10s clip, otherwise 6s
            segment_duration = img_record.get("Duration (s)", 6.0)
            clip_duration = 10 if segment_duration > 6.0 else 6

            async with semaphore:
                print(f"    [{i}/{total}] Scene {scene}, Image {index} "
                      f"({segment_duration:.1f}s → {clip_duration}s clip"
                      f"{'  HERO' if clip_duration == 10 else ''})")
                print(f"      Motion: {motion_prompt}")

                # Generate video with appropriate duration
                video_url = await self.image_client.generate_video(
                    image_url, motion_prompt, duration=clip_duration
                )

                if video_url:
                    print(f"      [{i}/{total}] Downloading video content...")
                    video_content = await self.image_client.download_image(video_url)

                    filename = f"Scene_{str(scene).zfill(2)}_{str(index).zfill(2)}.mp4"
                    print(f"      [{i}/{total}] Uploading {filename} to Drive...")
                    drive_file = self.google.upload_video(
                        video_content, filename, self.project_folder_id
                    )
                    video_drive_url = self.google.make_file_public(drive_file["id"])

                    # Update Airtable — write persistent Drive URL + animation status
                    self.airtable.update_image_video_url(img_record["id"], video_url)
                    self.airtable.update_image_animation_fields(
                        img_record["id"],
                        video_clip_url=video_drive_url,
                        animation_status="Done",
                        video_duration=clip_duration,
                    )
                    print(f"      ✅ [{i}/{total}] Video saved ({filename})")
                    video_count += 1
                    del video_content
                else:
                    self.airtable.update_image_animation_fields(
                        img_record["id"],
                        animation_status="Failed",
                    )
                    failed_count += 1
                    print(f"      ❌ [{i}/{total}] Video generation failed.")

        # Fire all tasks — semaphore limits to MAX_CONCURRENT_VIDEOS at a time
        await asyncio.gather(
            *[generate_single_video(i, img) for i, img in enumerate(pending_videos, 1)]
        )

        print(f"    ✅ Generated {video_count}/{total} videos"
              f"{f' ({failed_count} failed)' if failed_count else ''}")

        if self._is_targeted_run:
            print(f"  🎯 Targeted run — status NOT advanced")
            return {"bot": "Video Gen Bot", "video_count": video_count, "targeted": True}

        # Check if all videos are done
        remaining = [v for v in self.airtable.get_images_ready_for_video_generation(self.video_title) if v.get("Video Prompt")]
        if not remaining:
            self._update_status(self.STATUS_READY_THUMBNAIL)
            print(f"  ✅ Status updated to: {self.STATUS_READY_THUMBNAIL}")

        return {"bot": "Video Gen Bot", "video_count": video_count}
    
    # ==========================================================================
    # BRIEF TRANSLATOR INTEGRATION — Research Brief → Script + Scenes
    # ==========================================================================

    async def run_brief_translator(self, brief: dict = None) -> dict:
        """Generate a script from a research brief.

        Script generation ONLY — does NOT run scene expansion.
        Scene expansion is a separate pipeline stage.

        Steps:
            1. Create/find Google Drive folder
            2. Generate script (single LLM call)
            3. Save to Airtable Script field + Google Doc
            4. Run editorial validation (advisory)
            5. Write validation + Script table records
            6. Update status to Ready For Voice

        REQUIRES: Ideas status = "Idea Logged" or "Ready For Scripting"
        UPDATES TO: "Ready For Voice" when complete

        Args:
            brief: Research brief dict. If None, builds from current idea fields.
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

        # --- Google Drive folder (same as legacy script bot) ---
        folder = self.google.get_or_create_folder(self.video_title)
        self.project_folder_id = folder["id"]
        folder_url = f"https://drive.google.com/drive/folders/{self.project_folder_id}"
        try:
            self.airtable.update_idea_fields(self.current_idea_id, {
                "Drive Folder Link": folder_url,
                "Drive Folder ID": self.project_folder_id,
            })
        except Exception as e:
            print(f"  ⚠️ Could not save Drive folder to Airtable: {e}")

        # Build brief from Airtable idea fields if not provided
        if brief is None:
            idea = self.current_idea

            # Check for research_payload (from research agent)
            research_payload_raw = idea.get("Research Payload", "")
            if research_payload_raw:
                try:
                    research_payload = json.loads(research_payload_raw)
                    print("  📚 Found research payload — using as primary source material")
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
                        "psychological_angles": research_payload.get("psychological_angles", ""),
                        "_research_enriched": True,
                    }
                    print(f"  🎯 Framework Angle: {framework_angle or '(not set)'}")
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"  ⚠️ Could not parse research payload: {e}")
                    research_payload_raw = ""

            if not research_payload_raw:
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

        result = await translate_brief(
            anthropic_client=self.anthropic,
            airtable_client=self.airtable,
            idea_record_id=self.current_idea_id,
            brief=brief,
            slack_client=self.slack,
            google_client=self.google,
            project_folder_id=self.project_folder_id,
            video_config=self.video_config,
        )

        if result["status"] == "success":
            # Update status to Ready For Voice
            self._update_status(self.STATUS_READY_VOICE)
            print(f"  ✅ Status updated to: {self.STATUS_READY_VOICE}")

            if result.get("doc_url"):
                print(f"  📄 Google Doc: {result['doc_url']}")

            # Phase 2: Refine title with script content (non-blocking)
            await self._refine_title_post_script()

            self.slack.notify(
                f"📜 Script complete: *{self.video_title}*\n"
                f"Status: Ready For Voice"
            )
        else:
            print(f"  ❌ Translation failed: {result.get('error', result['status'])}")

        return {
            "bot": "Brief Translator",
            "video_title": self.video_title,
            "status": result["status"],
            "doc_url": result.get("doc_url"),
            "new_status": self.STATUS_READY_VOICE if result["status"] == "success" else None,
        }

    # ==========================================================================
    # IMAGE PROMPT ENGINE INTEGRATION — Scene List → Styled Prompts
    # ==========================================================================

    def _get_visual_seeds(self) -> str:
        """Extract visual seed concepts from the current idea record.

        Checks the Research Payload JSON first, then falls back to the
        Thumbnail Prompt field.
        """
        if not self.current_idea:
            return ""
        rp_raw = self.current_idea.get("Research Payload", "")
        if rp_raw:
            try:
                rp = json.loads(rp_raw) if isinstance(rp_raw, str) else rp_raw
                vs = rp.get("visual_seeds", "")
                if vs:
                    return vs
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        return self.current_idea.get("Thumbnail Prompt", "")

    async def run_styled_image_prompts(self, scene_filepath: str = None) -> dict:
        """Expand script scenes into visual concepts and generate styled image prompts.

        Two-pass scene-by-scene pipeline:

        Pass 1 — Expand: For each Script table record, expand its narration
        into 6-10 visual concepts via LLM. Each concept's sentence_text is
        validated as an exact substring of the original scene text. Written
        to Airtable Images table immediately after each scene.

        Pass 2 — Prompt: For each Image record missing an Image Prompt,
        build the styled prompt (prefix + description + composition + suffix)
        and write it back.

        Audio sync runs after both passes to populate real durations.

        Returns:
            Dict with prompt generation results.
        """
        from image_prompt_engine.prompt_builder import build_prompt, assign_profile_styles
        from image_prompt_engine.sequencer import assign_styles
        from brief_translator.scene_expander import expand_scene_concepts, expand_scene_concepts_deterministic

        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_IMAGE_PROMPTS)
            if not idea:
                return {"error": "No idea at Ready For Image Prompts"}
            self._load_idea(idea)

        print(f"\n🎨 STYLED IMAGE PROMPTS: Processing '{self.video_title}'")
        self._log_filters()

        # Detect active visual profile for profile-aware sequencing
        try:
            from visual_profiles import load_profile as _load_vp_seq
            _active_profile = _load_vp_seq()
        except Exception:
            _active_profile = None
        _use_profile_sequencer = (
            _active_profile is not None
            and _active_profile.profile_id != "holographic_hud"
            and _active_profile.style_system.substyles
        )
        if _use_profile_sequencer:
            print(f"  🎨 Using profile-aware sequencer: {_active_profile.profile_id}")

        # Read per-video image style override (set via Slack !style command)
        image_style_override = (self.current_idea.get("Image Style Override") or "").strip()
        if image_style_override:
            print(f"  🎨 Image style override active: {image_style_override[:80]}...")

        # ---------------------------------------------------------------
        # Load script records from Airtable (source of truth)
        # ---------------------------------------------------------------
        scripts = self.airtable.get_scripts_by_title(self.video_title)
        if not scripts:
            return {
                "error": f"No script records found for '{self.video_title}'. "
                "Run Script Bot first."
            }

        total_scripts = len(scripts)
        print(f"  Found {total_scripts} script records")

        # Determine accent color: Airtable field first, then topic category map, then default
        from image_prompt_engine import resolve_accent_color
        airtable_color = (self.current_idea.get("Accent Color") or "").replace("_", " ").strip()
        accent_color = resolve_accent_color(
            accent_color=airtable_color or None,
        )
        visual_seeds = self._get_visual_seeds()

        # Check which scenes already have image records (for resume)
        existing_images = self.airtable.get_all_images_for_video(self.video_title)
        existing_scenes: set[int] = set()
        for img in existing_images:
            scene_num = img.get("Scene")
            if scene_num is not None:
                existing_scenes.add(int(scene_num))

        if existing_scenes:
            print(f"  Found existing records for scenes {sorted(existing_scenes)} — will skip")

        # ---------------------------------------------------------------
        # Pre-generate style assignments for all images using sequencer
        # ---------------------------------------------------------------
        # Over-allocate: scenes average 7-8 images but can hit 10.
        # Use 10 per scene so the sequencer covers the worst case.
        estimated_total_images = total_scripts * 10
        style_seed = hash(self.video_title) % (2**32)  # Deterministic seed per video
        print(f"  Generating style assignments for ~{estimated_total_images} images...")

        if _use_profile_sequencer:
            style_assignments = assign_profile_styles(
                total_images=estimated_total_images,
                profile=_active_profile,
                seed=style_seed,
            )
        else:
            style_assignments = assign_styles(
                total_images=estimated_total_images,
                seed=style_seed,
            )
        print(f"  ✓ Style rotation configured: {len(style_assignments)} assignments ready")

        # ---------------------------------------------------------------
        # Generate or load Story Bible for visual consistency
        # ---------------------------------------------------------------
        story_bible = None
        is_mannequin_profile = (
            _active_profile is not None
            and _active_profile.profile_id not in ("holographic_hud",)
            and _active_profile.figure_rules.allow_mannequins
        )

        if is_mannequin_profile:
            # Check if Story Bible already exists in Airtable
            existing_bible_json = (self.current_idea.get("Story Bible") or "").strip()
            if existing_bible_json:
                try:
                    story_bible = json.loads(existing_bible_json)
                    char_count = len(story_bible.get("characters", []))
                    loc_count = len(story_bible.get("locations", []))
                    print(f"  📖 Loaded existing Story Bible: {char_count} characters, {loc_count} locations")
                    self.slack.notify(
                        f"📖 Using existing Story Bible for *{self.video_title}*:\n"
                        f"• {char_count} characters, {loc_count} locations"
                    )
                except json.JSONDecodeError:
                    print(f"  ⚠️ Could not parse existing Story Bible, regenerating...")
                    story_bible = None

            # Generate new Story Bible if not found
            if not story_bible:
                print(f"  📖 Generating Story Bible for visual consistency...")
                try:
                    from bots.story_bible import generate_story_bible

                    # Combine all script text for bible generation
                    full_script_text = "\n\n".join(
                        f"[SCENE {s.get('scene', 0)}]\n{s.get('Scene text', '') or s.get('Script', '')}"
                        for s in scripts
                    )

                    story_bible = await generate_story_bible(
                        anthropic_client=self.anthropic,
                        full_script_text=full_script_text,
                        video_title=self.video_title,
                    )

                    # Store in Airtable for future runs
                    if story_bible:
                        self.airtable.update_idea_fields(
                            self.current_idea_id,
                            {"Story Bible": json.dumps(story_bible, ensure_ascii=False)}
                        )
                        print(f"  📖 Story Bible saved to Airtable")
                        # Notify Slack that Story Bible was generated
                        char_count = len(story_bible.get("characters", []))
                        loc_count = len(story_bible.get("locations", []))
                        arc_count = len(story_bible.get("visual_arc", []))
                        self.slack.notify(
                            f"📖 Story Bible generated for *{self.video_title}*:\n"
                            f"• {char_count} characters\n"
                            f"• {loc_count} locations\n"
                            f"• {arc_count} scene arcs"
                        )
                except Exception as e:
                    print(f"  ⚠️ Story Bible generation failed (non-blocking): {e}")
                    story_bible = {}

        # ---------------------------------------------------------------
        # Expand each script record into visual concepts + styled prompts
        # ---------------------------------------------------------------
        # Apply scene filter if set
        if self.scene_filter is not None:
            scripts = [s for s in scripts if s.get("scene") == self.scene_filter]
            print(f"  🎯 Filtered to scene {self.scene_filter}: {len(scripts)} script(s)")

        print(f"\n  --- Expanding {len(scripts)} scenes into visual concepts + prompts ---")

        total_concepts = 0
        scenes_expanded = 0
        scenes_skipped = 0
        style_counts = {}  # Tracks display_format distribution (e.g. war_table, floating)
        image_index = 0  # Global image index across all scenes for style sequencing

        for script in scripts:
            scene_num = script.get("scene", 0)
            scene_text = script.get("Scene text", "") or script.get("Script", "")

            if not scene_text:
                print(f"  Scene {scene_num}: empty text, skipping")
                continue

            if scene_num in existing_scenes:
                existing_image_count = sum(1 for img in existing_images if img.get("Scene") == scene_num)
                if self.image_filter is not None:
                    # Targeted run: only skip if this SPECIFIC image index exists
                    has_target = any(
                        img.get("Scene") == scene_num and img.get("Image Index") == self.image_filter
                        for img in existing_images
                    )
                    if has_target:
                        image_index += existing_image_count
                        scenes_skipped += 1
                        print(f"  Scene {scene_num}, Image {self.image_filter}: Skipped (already exists)")
                        continue
                    # Target doesn't exist yet — proceed with generation
                    print(f"  Scene {scene_num}: {existing_image_count} images exist, but index {self.image_filter} missing — generating")
                else:
                    # Full run: skip entire scene if it has any images
                    image_index += existing_image_count
                    scenes_skipped += 1
                    print(f"  Scene {scene_num}: Skipped (has {existing_image_count} images), advanced index to {image_index}")
                    continue

            act_number = min(6, (scene_num - 1) * 6 // total_scripts + 1) if total_scripts > 0 else 1

            print(f"  Scene {scene_num} (Act {act_number}): "
                  f"{len(scene_text.split())} words — expanding...")

            # Get voice duration if available for accurate word-per-second calculation
            voice_duration = None
            voice_over = script.get("Voice Over")
            if voice_over and isinstance(voice_over, list) and len(voice_over) > 0:
                # Voice duration will be calculated by audio_sync later
                # For now, estimate from word count as fallback
                pass  # deterministic_splitter will use DEFAULT_WPS if None

            concepts = await expand_scene_concepts_deterministic(
                anthropic_client=self.anthropic,
                scene_number=scene_num,
                scene_text=scene_text,
                visual_seeds=visual_seeds,
                accent_color=accent_color,
                act_number=act_number,
                total_scenes=total_scripts,
                voice_duration=voice_duration,
                story_bible=story_bible,  # Pass Story Bible for character/location consistency
            )

            # Note: deterministic splitter doesn't set needs_new_prompt since it
            # generates visual_description immediately after segmentation.
            # Kept for compatibility if we switch back to LLM-based expansion.
            needs_regen = [c for c in concepts if c.get("needs_new_prompt")]
            if needs_regen:
                print(f"    Regenerating {len(needs_regen)} visual descriptions "
                      f"(duration-adjusted concepts)...")
                # Build profile-driven regen prompt with Story Bible context
                try:
                    from visual_profiles import load_profile as _load_vp
                    _regen_profile = _load_vp()
                except Exception:
                    _regen_profile = None
                _regen_is_holographic = (
                    _regen_profile is None
                    or _regen_profile.profile_id == "holographic_hud"
                )

                # Format Story Bible context for regen
                _regen_bible_context = ""
                if story_bible and not _regen_is_holographic:
                    try:
                        from bots.story_bible import format_bible_for_prompt
                        _regen_bible_context = format_bible_for_prompt(story_bible, scene_num)
                    except ImportError:
                        pass

                for concept in needs_regen:
                    try:
                        if not _regen_is_holographic and _regen_profile and _regen_profile.scene_description.system_prompt:
                            # NO scene type constraints — Claude decides what to write
                            regen_prompt = f"{_regen_profile.scene_description.system_prompt}\n\n"

                            # Add Story Bible context if available
                            if _regen_bible_context:
                                regen_prompt += (
                                    f"{_regen_bible_context}\n\n"
                                    "CRITICAL: If any character or location from the bible appears in this "
                                    "narration, use their EXACT description from the bible above.\n\n"
                                )

                            # Add clothing requirement and instructions
                            regen_prompt += (
                                "CLOTHING RULE: Every mannequin figure MUST have specific clothing described. "
                                "Never describe a mannequin without clothing. If unsure, use 'wearing dark formal suit with white shirt.'\n\n"
                                "Write a 20-35 word visual description for this narration segment. "
                                "You decide whether this moment needs characters, environment, data, or objects.\n\n"
                                "Do NOT start with the style prefix (e.g. '3D rendered faceless mannequin...') — "
                                "that will be added automatically based on what you write.\n"
                                "Return ONLY the description, nothing else.\n\n"
                                f"Narration: \"{concept['sentence_text']}\""
                            )
                        else:
                            regen_prompt = (
                                "You are creating visual descriptions for HOLOGRAPHIC DATA DISPLAYS "
                                "in an intelligence operations center — not camera shots of real events.\n\n"
                                "NEVER describe:\n"
                                "- People (no politicians, officials, reporters, soldiers, analysts, or any human figures)\n"
                                "- Physical rooms or buildings as if a camera is there\n"
                                "- Events as if photographing them\n\n"
                                "ALWAYS describe:\n"
                                "- What DATA, DOCUMENTS, MAPS, or CHARTS would appear on a holographic screen analyzing this topic\n"
                                "- Information visualizations (price charts, treaty text, flow diagrams, network maps, timelines)\n"
                                "- At least one specific number, date, or percentage from the narration\n"
                                "- Data elements must come from THIS segment's text only, not from the broader script context\n\n"
                                "EXAMPLES:\n"
                                "BAD: 'Kremlin hall, Putin and Pezeshkian at long table with treaty document'\n"
                                "GOOD: 'Holographic treaty document floating in space, 47 articles visible with Section 12: Military Cooperation highlighted'\n\n"
                                "BAD: 'White House briefing room, reporters holding phones'\n"
                                "GOOD: 'Bloomberg terminal display showing headline with oil price ticker dropping from $120 to $68'\n\n"
                                "The subject is ALWAYS information/data being displayed, never the physical event itself.\n\n"
                                "Write a 20-35 word description of what DATA DISPLAY would visualize this narration. "
                                "Return ONLY the description, nothing else.\n\n"
                                f"Narration: \"{concept['sentence_text']}\""
                            )
                        new_desc = await self.anthropic.generate(
                            prompt=regen_prompt,
                            model="claude-sonnet-4-5-20250929",
                            max_tokens=200,
                            temperature=0.4,
                        )
                        concept["visual_description"] = new_desc.strip()
                    except Exception as e:
                        print(f"      ⚠️ Regen failed for concept "
                              f"{concept['concept_index']}: {e}")
                    concept.pop("needs_new_prompt", None)

            # If image_filter is set, only generate the specific concept
            if self.image_filter is not None:
                concepts = [c for c in concepts if c["concept_index"] == self.image_filter]
                if not concepts:
                    print(f"    ⚠️ No concept with index {self.image_filter} in scene {scene_num}, skipping")
                    continue
                print(f"    🎯 Filtered to concept {self.image_filter}: {len(concepts)} concept(s)")

            for concept in concepts:
                visual_desc = concept["visual_description"]

                # Get style assignment from sequencer (extend if needed)
                if image_index >= len(style_assignments):
                    # Actual image count exceeded estimate — regenerate with
                    # the real count so rotation constraints stay intact.
                    new_total = image_index + total_scripts * 10
                    print(f"      ↻ Extending style assignments: "
                          f"{len(style_assignments)} → {new_total}")
                    if _use_profile_sequencer:
                        style_assignments = assign_profile_styles(
                            total_images=new_total,
                            profile=_active_profile,
                            seed=style_seed,
                        )
                    else:
                        style_assignments = assign_styles(
                            total_images=new_total, seed=style_seed,
                        )
                style = style_assignments[image_index]
                content_type = style["content_type"]
                display_format = style["display_format"]
                color_mood = style["color_mood"]

                # Build styled prompt using sequencer-assigned styles
                prompt = build_prompt(
                    scene_description=visual_desc,
                    content_type=content_type,
                    display_format=display_format,
                    color_mood=color_mood,
                    image_style_override=image_style_override,
                )

                # Diagnostic: print first 3 assembled prompts for format verification
                if image_index < 3:
                    print(f"\n  📋 PROMPT DIAGNOSTIC [{image_index + 1}/3] "
                          f"(scene {scene_num}, type={display_format}):")
                    print(f"     {prompt}")
                    print()

                # Use camera composition from concept (wide/medium/closeup/etc.)
                # NOT display_format which is the scene type (power_move/lone_figure/etc.)
                camera_composition = concept.get("composition", "medium")

                self.airtable.create_concept_record(
                    scene_number=scene_num,
                    concept_index=concept["concept_index"],
                    sentence_text=concept["sentence_text"],
                    image_prompt=prompt,
                    composition=camera_composition,
                    video_title=self.video_title,
                )

                # Track style distribution for reporting
                style_counts[display_format] = style_counts.get(display_format, 0) + 1
                image_index += 1  # Increment global image counter

            total_concepts += len(concepts)
            scenes_expanded += 1
            print(f"    {len(concepts)} concepts + prompts written to Airtable")

        skip_note = f" ({scenes_skipped} resumed)" if scenes_skipped else ""
        print(f"\n  Done: {scenes_expanded} scenes expanded, "
              f"{total_concepts} concepts created{skip_note}")

        # Report display format distribution
        if style_counts:
            total_styled = sum(style_counts.values())
            print(f"  Display format variety:")
            for fmt, count in sorted(style_counts.items(), key=lambda x: -x[1]):
                pct = count / total_styled * 100
                print(f"    {fmt}: {count} ({pct:.0f}%)")

        # ---------------------------------------------------------------
        # Audio Sync: Whisper-aligned durations
        # ---------------------------------------------------------------
        audio_sync_summary = ""
        if self._is_targeted_run:
            print(f"\n  🎯 Targeted run — skipping audio sync (needs all images)")
        else:
            try:
                print(f"\n  Running audio sync for scene durations...")
                sync_result = await self.run_audio_sync()

                if sync_result.get("error"):
                    print(f"  Audio sync skipped: {sync_result['error']}")
                    audio_sync_summary = f" | Audio sync skipped: {sync_result['error']}"
                else:
                    # run_audio_sync() already wrote per-image durations to
                    # Airtable (at line ~2907) and render_config.json to both
                    # timing/ and remotion-video/public/.  No second write needed.
                    avg_dur = sync_result["total_duration"] / max(sync_result["scene_count"], 1)
                    print(f"  Audio sync: {sync_result['scene_count']} scenes aligned, "
                          f"avg {avg_dur:.1f}s, {sync_result.get('image_count', 0)} records updated")
                    audio_sync_summary = (
                        f" | Audio sync: {sync_result['scene_count']} scenes, "
                        f"avg {avg_dur:.1f}s"
                    )
            except Exception as e:
                print(f"  Audio sync failed (non-blocking): {e}")
                audio_sync_summary = f" | Audio sync error: {e}"

        # ---------------------------------------------------------------
        # Prompt Validation: Check sequencing rules before image generation
        # ---------------------------------------------------------------
        validation_summary = ""
        has_critical_violations = False
        if not self._is_targeted_run:
            try:
                print(f"\n  Running prompt validation...")
                prompts = self.airtable.get_all_images_for_video(self.video_title)

                if prompts:
                    validator = PromptValidator()
                    violations = validator.validate(prompts)

                    if violations:
                        auto_fixed = []
                        needs_regen = []

                        for v in violations:
                            if v.fix == "swap_camera_distance":
                                fix = validator.auto_fix_camera_distance(prompts, v)
                                if fix:
                                    # Write fix to Airtable
                                    self.airtable.update_image_prompt_fields(
                                        record_id=fix["record_id"],
                                        shot_type=fix["new_shot_type"],
                                    )
                                    auto_fixed.append(fix)
                                    print(f"    Auto-fixed: Image {fix['image_index']} camera distance {fix['old_shot_type']} → {fix['new_shot_type']}")
                                else:
                                    needs_regen.append(v)
                            elif v.fix == "add_mannequin_hand_description":
                                fix = validator.auto_fix_mannequin_hands(prompts, v)
                                if fix:
                                    # Write fix to Airtable
                                    self.airtable.update_image_prompt_fields(
                                        record_id=fix["record_id"],
                                        image_prompt=fix["new_prompt"],
                                    )
                                    auto_fixed.append(fix)
                                    print(f"    Auto-fixed: Image {fix['image_index']} added mannequin hand reinforcement")
                                else:
                                    needs_regen.append(v)
                            else:
                                needs_regen.append(v)

                        # Report to Slack
                        report = format_validation_report(
                            video_title=self.video_title,
                            total_prompts=len(prompts),
                            violations=violations,
                            auto_fixed=auto_fixed,
                            needs_regen=needs_regen,
                        )
                        self.slack.notify_prompt_validation(report)

                        # Log to file for debugging
                        try:
                            with open("/tmp/pipeline-validation.log", "a") as f:
                                from datetime import datetime
                                f.write(f"\n{'='*60}\n")
                                f.write(f"[{datetime.now().isoformat()}] {self.video_title}\n")
                                f.write(f"{'='*60}\n")
                                f.write(f"Total prompts: {len(prompts)}\n")
                                f.write(f"Violations: {len(violations)}\n")
                                f.write(f"Auto-fixed: {len(auto_fixed)}\n")
                                f.write(f"Needs regeneration: {len(needs_regen)}\n\n")
                                for v in violations:
                                    f.write(f"  [{v.severity.upper()}] {v.type}: Image {v.image_index} - {v.issue}\n")
                        except Exception as log_err:
                            print(f"    Warning: Could not write to validation log: {log_err}")

                        # Check for critical violations
                        critical = [v for v in needs_regen if v.severity == "critical"]
                        if critical:
                            has_critical_violations = True
                            print(f"  ⚠️ {len(critical)} critical violations need manual review")
                            validation_summary = f" | ⚠️ {len(critical)} critical violations"
                        elif needs_regen:
                            print(f"  ⚠️ {len(needs_regen)} prompts flagged for review")
                            validation_summary = f" | ⚠️ {len(needs_regen)} flagged"
                        else:
                            print(f"  ✅ Validation passed ({len(auto_fixed)} auto-fixed)")
                            validation_summary = f" | ✅ {len(auto_fixed)} auto-fixed"
                    else:
                        print(f"  ✅ Validation passed - no issues found")
                else:
                    print(f"  ⚠️ No prompts found for validation")
            except Exception as e:
                print(f"  Prompt validation failed (non-blocking): {e}")
                validation_summary = f" | Validation error: {e}"

        # If critical violations exist, don't advance status
        if has_critical_violations:
            print(f"\n  ❌ Cannot advance status - critical violations need manual review")
            return {
                "bot": "Styled Image Prompt Engine",
                "video_title": self.video_title,
                "scenes_expanded": scenes_expanded,
                "total_concepts": total_concepts,
                "validation_blocked": True,
                "error": "Critical violations need manual review before image generation",
            }

        # Update status (skip if targeted run)
        if self._is_targeted_run:
            print(f"  🎯 Targeted run — status NOT advanced")
            return {
                "bot": "Styled Image Prompt Engine",
                "video_title": self.video_title,
                "scenes_expanded": scenes_expanded,
                "total_concepts": total_concepts,
                "targeted": True,
            }

        self._update_status(self.STATUS_READY_IMAGES)
        print(f"  Status updated to: {self.STATUS_READY_IMAGES}")

        skip_note = f" ({scenes_skipped} resumed)" if scenes_skipped else ""
        total_styled = sum(style_counts.values()) or 1
        style_summary = " | ".join(
            f"{fmt}: {cnt} ({cnt / total_styled * 100:.0f}%)"
            for fmt, cnt in sorted(style_counts.items(), key=lambda x: -x[1])
        )
        self.slack.notify(
            f"Styled prompts done: {total_concepts} concepts from {scenes_expanded} scenes{skip_note} "
            f"for *{self.video_title}*\n"
            f"{style_summary}"
            f"{audio_sync_summary}"
            f"{validation_summary}"
        )

        return {
            "bot": "Styled Image Prompt Engine",
            "video_title": self.video_title,
            "scenes_expanded": scenes_expanded,
            "scenes_skipped": scenes_skipped,
            "total_concepts": total_concepts,
            "style_distribution": style_counts,
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
        script_result = await self.run_script_bot_legacy()
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
            self._update_status(self.STATUS_READY_SCRIPTING)

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
            "sound_design": self.STATUS_READY_SOUND_DESIGN,
            "sound_effects": self.STATUS_READY_SOUND_EFFECTS,
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
        self._update_status(target_status)

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
        1. Select editorial illustration template (Map/Character/Split/Symbolic)
        2. Generate a title with proven formula patterns
        3. Build a bright editorial thumbnail prompt with bold text overlay
        4. Generate 3 thumbnail variants via Nano Banana Pro for manual selection
        5. Upload all variants to Drive, save first to Airtable, advance pipeline
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

        # Always re-fetch from Airtable to pick up style overrides set after
        # the idea was first loaded (e.g. via Slack !style command between stages)
        try:
            fresh = self.airtable.idea_concepts_table.get(self.current_idea_id)
            if fresh:
                self.current_idea.update(fresh.get("fields", {}))
        except Exception as e:
            print(f"  Could not refresh idea from Airtable: {e}")

        video_title = self.current_idea.get("Video Title", "")
        video_summary = self.current_idea.get("Summary", "")

        # Read per-video thumbnail style override (set via Slack !style command)
        thumbnail_style_override = (self.current_idea.get("Thumbnail Style Override") or "").strip()
        if thumbnail_style_override:
            print(f"  Thumbnail style override active: {thumbnail_style_override[:80]}...")

        # Read independent thumbnail text (yin-yang: different from title)
        thumbnail_text = (self.current_idea.get("Thumbnail Text") or "").strip()
        if thumbnail_text:
            print(f"  Thumbnail Text from Airtable: {thumbnail_text}")
        else:
            print(f"  No Thumbnail Text set — will auto-generate")

        # Read optional palette override from Airtable
        palette_override = (self.current_idea.get("Thumbnail Palette") or "").strip().lower() or None

        # Build metadata for template selection
        video_metadata = {
            "Video Title": video_title,
            "Summary": video_summary,
            "topic": self.current_idea.get("Headline", ""),
            "Framework Angle": self.current_idea.get("Framework Angle", ""),
            "Framework": self.current_idea.get("Framework", ""),
            "tags": [],
        }

        # --- Generate matched title + thumbnail (3 variants) ---
        override_note = f" (with style override)" if thumbnail_style_override else ""
        self.slack.notify(f"🎨 Generating thumbnail + title for *{self.video_title}*{override_note}...")
        engine = ThumbnailTitleEngine(self.anthropic, self.image_client)

        try:
            result = await engine.generate(
                video_metadata,
                thumbnail_style_override=thumbnail_style_override or None,
                thumbnail_text=thumbnail_text or None,
                palette_override=palette_override,
            )
        except Exception as e:
            error_msg = f"Thumbnail/title generation failed for '{self.video_title}': {e}"
            print(f"  {error_msg}")
            self.slack.notify(f"Thumbnail Bot STOPPED: {error_msg}\nStatus NOT advanced. Fix issues and run again.")
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

        # --- Warn Slack if thumbnail text was auto-generated ---
        if result.get("thumbnail_text_auto_generated"):
            auto_text = f"{result['line_1']}" + (f" {result['line_2']}" if result['line_2'] else "")
            self.slack.notify(
                f"No Thumbnail Text set for *{self.video_title}* — auto-generated: *{auto_text}*\n"
                f"Set `Thumbnail Text` field in Airtable to override."
            )

        # --- Check if thumbnail generation succeeded ---
        if result["needs_manual_review"]:
            error_msg = (
                f"Thumbnail generation failed after {result['thumbnail_attempt']} attempts "
                f"for '{self.video_title}'. Flagged for manual review."
            )
            print(f"  {error_msg}")
            self.slack.notify(
                f"Thumbnail Bot needs manual review for *{self.video_title}*\n"
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

        thumbnail_urls = result["thumbnail_urls"]
        print(f"  {len(thumbnail_urls)} thumbnail variant(s) generated")

        # --- Upload all variants to Google Drive ---
        if self.project_folder_id:
            parent_id = self.project_folder_id
        else:
            folder = self.google.search_folder(self.video_title)
            if folder:
                parent_id = folder["id"]
            else:
                print("  Project folder not found, uploading to root.")
                parent_id = None

        slug = video_title.lower().replace(" ", "_").replace("'", "")[:50]
        drive_links = []

        for i, image_url in enumerate(thumbnail_urls, 1):
            filename = f"{slug}_thumbnail_v{i}.png"
            print(f"  Uploading variant {i} to Google Drive...")
            try:
                google_file = self.google.upload_file_from_url(
                    url=image_url,
                    name=filename,
                    parent_id=parent_id,
                )
                link = google_file.get("webViewLink", image_url)
                drive_links.append(link)
                print(f"  Uploaded variant {i}: {link}")
            except Exception as e:
                print(f"  Failed to upload variant {i}: {e}")
                drive_links.append(image_url)  # fallback to raw URL

        # --- Save first thumbnail to Airtable (primary) ---
        self.airtable.update_idea_thumbnail(self.current_idea_id, thumbnail_urls[0])
        print("  Saved primary thumbnail to Airtable")

        # --- Update status ---
        self._update_status(self.STATUS_READY_TO_RENDER)
        print(f"  Status updated to: {self.STATUS_READY_TO_RENDER}")

        template_info = result['template_name']
        if thumbnail_style_override:
            override_mode = "REPLACE" if thumbnail_style_override.upper().startswith("REPLACE:") else "APPEND"
            template_info = f"{result['template_name']} ({override_mode} override active)"

        # Build Slack notification with all variant links
        variant_links = "\n".join(f"  Option {i}: {link}" for i, link in enumerate(drive_links, 1))
        self.slack.notify(
            f"Thumbnail + title complete for *{self.video_title}*\n"
            f"Title: {result['title']}\n"
            f"Template: {template_info}\n"
            f"Text: {result['line_1']}" + (f" / {result['line_2']}" if result['line_2'] else "") + f"\n"
            f"{len(drive_links)} options generated — pick your favorite:\n{variant_links}"
        )

        return {
            "bot": "Thumbnail Bot",
            "video_title": self.video_title,
            "new_status": self.STATUS_READY_TO_RENDER,
            "thumbnail_url": drive_links[0] if drive_links else None,
            "thumbnail_urls": drive_links,
            "generated_title": result["title"],
            "caps_word": result["caps_word"],
            "formula_used": result["formula_used"],
            "template_used": result["template_used"],
            "template_name": result["template_name"],
            "line_1": result["line_1"],
            "line_2": result["line_2"],
            "thumbnail_attempt": result["thumbnail_attempt"],
            "validation": result["validation"],
            "thumbnail_text_auto_generated": result.get("thumbnail_text_auto_generated", False),
        }
    
    def _clean_render_assets(self, label: str = "stale") -> int:
        """Remove all render assets from disk (public/, captions/, out/).

        Called before each render (to start fresh) and after upload
        (to free disk space).  Returns the number of files removed.
        """
        import glob as glob_mod
        from pathlib import Path

        remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"
        public_dir = remotion_dir / "public"
        captions_dir = remotion_dir / "src" / "captions"
        out_dir = remotion_dir / "out"

        to_remove: list[str] = []

        if public_dir.exists():
            to_remove += glob_mod.glob(str(public_dir / "Scene *.mp3"))
            to_remove += glob_mod.glob(str(public_dir / "Scene_*.png"))
            to_remove += glob_mod.glob(str(public_dir / "Scene_*.mp4"))
            to_remove += glob_mod.glob(str(public_dir / "render_config.json"))
            to_remove += glob_mod.glob(str(public_dir / "props.json"))
            to_remove += glob_mod.glob(str(public_dir / "sfx" / "*.mp3"))

        if captions_dir.exists():
            to_remove += glob_mod.glob(str(captions_dir / "Scene *.json"))

        if out_dir.exists():
            to_remove += glob_mod.glob(str(out_dir / "*.mp4"))

        # Also remove props.json at remotion root
        props_file = remotion_dir / "props.json"
        if props_file.exists():
            to_remove.append(str(props_file))

        removed = 0
        for f in to_remove:
            try:
                os.remove(f)
                removed += 1
            except OSError:
                pass

        if removed:
            print(f"  🧹 Cleaned {removed} {label} assets from disk")

        return removed

    async def run_render_bot(self) -> dict:
        """Render video with Remotion and upload to Google Drive.

        REQUIRES: Ideas status = "Ready To Render"
        UPDATES TO: "Done" when complete
        """
        import subprocess
        import re
        from pathlib import Path

        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_TO_RENDER)
            if not idea:
                return {"error": "No idea with status 'Ready To Render'"}
            self._load_idea(idea)

        print(f"\n🎬 RENDER BOT: Processing '{self.video_title}'")
        self.slack.notify(
            f"🎬 *Render starting:* _{self.video_title}_\n"
            f"Running pre-flight checks, downloading assets, then rendering (concurrency=1, ~60-90 min)..."
        )

        # CLEAN ALL RENDER ASSETS — start fresh every render
        remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"
        public_dir = remotion_dir / "public"
        self._clean_render_assets(label="pre-render")

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

        # Use the saved project folder ID if it has Scene files.
        # Only fall back to keyword search if project_folder_id is missing
        # or has zero Scene files. This prevents audio/image contamination
        # from other video folders with similar names.
        asset_folders = []  # list of (folder_id, folder_name)

        if self.project_folder_id:
            files_in = self.google.list_files_in_folder(self.project_folder_id)
            scene_files = [f for f in files_in if f["name"].startswith("Scene")]
            if scene_files:
                asset_folders.append((self.project_folder_id, f"saved ({len(scene_files)} scene files)"))

        # Only search Drive if the saved folder had no Scene files
        if not asset_folders:
            if self.project_folder_id:
                print(f"  ⚠️ Saved folder {self.project_folder_id} has no Scene files, falling back to search")
            scored_folders = self.google.find_folder_by_keywords(self.video_title)
            for cand, score in scored_folders[:10]:
                files_in = self.google.list_files_in_folder(cand["id"])
                scene_files = [f for f in files_in if f["name"].startswith("Scene")]
                if scene_files:
                    asset_folders.append((cand["id"], f"{cand['name']} ({len(scene_files)} scene files, score:{score})"))
                    break  # Use first match only to avoid contamination

        print(f"  📂 Found {len(asset_folders)} Drive folders with assets:")
        for fid, desc in asset_folders:
            print(f"    📁 {desc}")

        # Export props
        props = await self.package_for_remotion()

        props_file = remotion_dir / "props.json"
        public_dir.mkdir(exist_ok=True)

        with open(props_file, "w") as f:
            json.dump(props, f, indent=2)
        print(f"  📦 Props saved to: {props_file}")

        # Use the Whisper-based render_config.json generated by audio_sync.
        # It contains accurate per-image durations, ken_burns, and transition
        # data.  Do NOT regenerate from Airtable — that was the old path that
        # produced corrupted timing (empty ken_burns, lossy durations).
        import shutil
        pipeline_dir = Path(__file__).parent
        video_id = self.current_idea_id or "unknown"
        audio_sync_config = pipeline_dir / "timing" / video_id / "render_config.json"
        rc_path = public_dir / "render_config.json"

        if audio_sync_config.exists():
            shutil.copy2(audio_sync_config, rc_path)
            rc_data = json.loads(rc_path.read_text())
            rc_scene_count = len(rc_data.get("scenes", []))
            rc_total = rc_data.get("total_duration_seconds", 0)
            print(f"  📋 render_config.json (from audio_sync): "
                  f"{rc_scene_count} images, {rc_total:.1f}s total")

            # Embed render_config in props so Remotion reads it via
            # getInputProps() instead of the static JSON import.  The static
            # import gets baked into the webpack bundle and can go stale when
            # Remotion's .remotion/ cache persists across different videos.
            props["renderConfig"] = rc_data
            with open(props_file, "w") as f:
                json.dump(props, f, indent=2)
            print(f"  📦 Props updated with embedded renderConfig")
        else:
            raise RuntimeError(
                f"render_config.json not found at {audio_sync_config}. "
                f"Audio sync must run before rendering. "
                f"Re-run the pipeline from the image prompts stage."
            )

        # Download assets from ALL matching Drive folders to public/
        # First file wins — if Scene 1.mp3 is in folder A, we skip it in folder B
        print(f"  ⬇️ Downloading assets from Google Drive...")

        # First pass: collect all downloadable files and compute totals
        download_queue: list[dict] = []
        seen_local: set[str] = set()
        for folder_id, folder_desc in asset_folders:
            drive_files = self.google.list_files_in_folder(folder_id)
            for df in drive_files:
                fname = df["name"]
                fid = df["id"]

                # Download Scene audio (.mp3), image (.png), and video (.mp4) files
                # Video clips may use any prefix (Scene_, Clip_S, etc.) — we
                # detect all .mp4 files and normalize to Scene_XX_YY.mp4 for Remotion.
                is_audio = fname.startswith("Scene ") and fname.endswith(".mp3")
                is_image = fname.startswith("Scene_") and fname.endswith(".png")
                is_video = fname.endswith(".mp4")
                if not is_audio and not is_image and not is_video:
                    continue

                # Normalize mp4 filenames to Scene_XX_YY.mp4 for Remotion
                local_fname = fname
                if is_video and not fname.startswith("Scene_"):
                    nums = re.findall(r"(\d+)", fname)
                    if len(nums) >= 2:
                        local_fname = f"Scene_{int(nums[0]):02d}_{int(nums[1]):02d}.mp4"
                    else:
                        continue

                dest = public_dir / local_fname
                if dest.exists() or local_fname in seen_local:
                    continue

                seen_local.add(local_fname)
                asset_type = "audio" if is_audio else ("video" if is_video else "image")
                download_queue.append({
                    "fname": fname, "fid": fid,
                    "dest": dest, "type": asset_type,
                })

        total_assets = len(download_queue)
        download_ok = 0
        download_fail = 0
        failed_assets = []
        audio_count = 0
        image_count = 0
        video_clip_count = 0

        import time as _dl_time
        SLACK_UPDATE_INTERVAL = 30  # seconds between Slack progress updates
        last_slack_update = _dl_time.time()

        self.slack.notify(
            f"⬇️ *Downloading assets:* _{self.video_title}_\n"
            f"`░░░░░░░░░░` *0%* — 0/{total_assets} files"
        )

        # Second pass: download with progress tracking
        for item in download_queue:
            try:
                content = self.google.download_file(item["fid"])
                if len(content) < 1000:
                    raise ValueError(f"File too small ({len(content)} bytes)")
                item["dest"].write_bytes(content)
                print(f"    ✅ {item['fname']} ({len(content) // 1024} KB)")
                download_ok += 1
                if item["type"] == "audio":
                    audio_count += 1
                elif item["type"] == "video":
                    video_clip_count += 1
                else:
                    image_count += 1
            except Exception as e:
                print(f"    ❌ {item['fname']} FAILED: {e}")
                failed_assets.append(item["fname"])
                download_fail += 1

            # Send Slack progress update at intervals
            completed = download_ok + download_fail
            now = _dl_time.time()
            if now - last_slack_update >= SLACK_UPDATE_INTERVAL and completed < total_assets:
                pct = (completed / total_assets * 100) if total_assets > 0 else 0
                bar = "█" * int(pct // 10) + "░" * (10 - int(pct // 10))
                self.slack.notify(
                    f"⬇️ *Downloading assets:* _{self.video_title}_\n"
                    f"`{bar}` *{pct:.1f}%* — {completed}/{total_assets} files "
                    f"({audio_count} audio, {image_count} images, {video_clip_count} clips)"
                )
                last_slack_update = now

        # Final download summary to Slack
        if total_assets > 0:
            self.slack.notify(
                f"⬇️ *Downloads complete:* _{self.video_title}_\n"
                f"`██████████` *100%* — {download_ok}/{total_assets} files "
                f"({audio_count} audio, {image_count} images, {video_clip_count} clips)"
                + (f"\n⚠️ {download_fail} failed" if download_fail > 0 else "")
            )

        # Validate downloads — abort if critical assets are missing
        print(f"  📊 Downloads: {download_ok} OK, {download_fail} failed")
        if download_fail > 0:
            fail_list = "\n".join(f"  • {a}" for a in failed_assets[:10])
            extra = f"\n  ... and {len(failed_assets) - 10} more" if len(failed_assets) > 10 else ""
            print(f"  ❌ Failed assets:\n{fail_list}{extra}")

        if download_ok == 0:
            self.slack.notify(
                f"❌ *Render ABORTED:* _{self.video_title}_\n"
                f"No Scene assets found across {len(asset_folders)} Drive folder(s).\n"
                f"Make sure Scene *.mp3 and Scene_*.png files exist in Google Drive."
            )
            return {"error": "No assets in Drive folders", "bot": "Render Bot"}

        if download_fail > download_ok * 0.3:
            fail_list = "\n".join(f"  • {a}" for a in failed_assets[:10])
            extra = f"\n  ... and {len(failed_assets) - 10} more" if len(failed_assets) > 10 else ""
            self.slack.notify(
                f"❌ *Render ABORTED:* _{self.video_title}_\n"
                f"Too many asset downloads failed ({download_fail} of {download_ok + download_fail}).\n"
                f"Failed:\n{fail_list}{extra}"
            )
            return {"error": f"{download_fail} asset downloads failed", "bot": "Render Bot"}

        print(f"  ✅ Assets downloaded: {audio_count} audio, {image_count} images, {video_clip_count} video clips")

        # ── Patch render_config with video clip data ──────────────────
        # The render_config from audio_sync marks all entries as type="image".
        # For any .mp4 files on disk (newly downloaded OR from a previous run),
        # patch the matching render_config entry to type="video" so Remotion
        # uses <OffthreadVideo> instead of <Img>.
        if "renderConfig" in props:
            rc_data = props["renderConfig"]
            import glob as _glob_mod
            downloaded_mp4s = _glob_mod.glob(str(public_dir / "Scene_*.mp4"))
            # Build set of (scene_number, image_index) from downloaded mp4 filenames
            mp4_lookup: dict[tuple[int, int], str] = {}
            for mp4_path in downloaded_mp4s:
                mp4_name = os.path.basename(mp4_path)
                # Parse Scene_XX_YY.mp4
                match = re.match(r"Scene_(\d+)_(\d+)\.mp4", mp4_name)
                if match:
                    mp4_lookup[(int(match.group(1)), int(match.group(2)))] = mp4_name

            patched = 0
            for rc_entry in rc_data.get("scenes", []):
                sn = rc_entry.get("scene_number", 0)
                ii = rc_entry.get("image_index", 0)
                mp4_name = mp4_lookup.get((sn, ii))
                if mp4_name:
                    rc_entry["type"] = "video"
                    rc_entry["video_clip_path"] = mp4_name
                    patched += 1

            if patched:
                # Rewrite render_config.json on disk and re-embed in props
                rc_path = public_dir / "render_config.json"
                with open(rc_path, "w") as f:
                    json.dump(rc_data, f, indent=2)
                props["renderConfig"] = rc_data
                print(f"  🎬 Patched render_config: {patched} entries marked as video clips")

        # Build a map of SFX files already in Drive (sfx_*.mp3)
        # so we can download them directly instead of relying on
        # Airtable CDN URLs which expire after 2 hours.
        drive_sfx_map: dict[str, str] = {}  # filename → Drive file ID
        for folder_id, _desc in asset_folders:
            drive_files = self.google.list_files_in_folder(folder_id)
            for df in drive_files:
                if df["name"].startswith("sfx_") and df["name"].endswith(".mp3"):
                    drive_sfx_map[df["name"]] = df["id"]

        # Download per-image SFX files (4-strategy fallback)
        sfx_dir = public_dir / "sfx"
        sfx_dir.mkdir(exist_ok=True)
        sfx_count = 0
        sfx_total = 0
        for scene in props.get("scenes", []):
            for image in scene.get("images", []):
                sfx_path = image.get("sfx")
                sfx_url = image.pop("sfxUrl", None)  # Remove URL from props (not needed by Remotion)
                if not sfx_path or not sfx_url:
                    continue
                sfx_total += 1
                filename = sfx_path.removeprefix("sfx/")
                dest = sfx_dir / filename
                if dest.exists() and dest.stat().st_size > 100:
                    sfx_count += 1
                    continue

                downloaded = False

                # Strategy 1: Download from Drive file map (most reliable)
                if filename in drive_sfx_map:
                    try:
                        content = self.google.download_file(drive_sfx_map[filename])
                        dest.write_bytes(content)
                        print(f"    ✅ {filename} ({len(content) // 1024} KB) [Drive map]")
                        downloaded = True
                    except Exception as e:
                        print(f"    ⚠️ Drive map download failed for {filename}: {e}")

                # Strategy 2: Search Drive by filename
                if not downloaded and self.project_folder_id:
                    try:
                        result = self.google.search_file(filename, self.project_folder_id)
                        if result:
                            content = self.google.download_file(result["id"])
                            dest.write_bytes(content)
                            print(f"    ✅ {filename} ({len(content) // 1024} KB) [Drive search]")
                            downloaded = True
                    except Exception as e:
                        print(f"    ⚠️ Drive search failed for {filename}: {e}")

                # Strategy 3: Extract Drive file ID from Airtable attachment URL
                if not downloaded and sfx_url:
                    drive_id = None
                    if "/file/d/" in sfx_url:
                        try:
                            drive_id = sfx_url.split("/file/d/")[1].split("/")[0]
                        except (IndexError, AttributeError):
                            pass
                    elif "id=" in sfx_url:
                        try:
                            drive_id = sfx_url.split("id=")[1].split("&")[0]
                        except (IndexError, AttributeError):
                            pass
                    if drive_id:
                        try:
                            content = self.google.download_file(drive_id)
                            dest.write_bytes(content)
                            print(f"    ✅ {filename} ({len(content) // 1024} KB) [Drive ID]")
                            downloaded = True
                        except Exception as e:
                            print(f"    ⚠️ Drive ID download failed for {filename}: {e}")

                # Strategy 4: Direct HTTP from Airtable CDN (may be expired)
                if not downloaded and sfx_url:
                    try:
                        async with _httpx.AsyncClient() as http:
                            resp = await http.get(sfx_url, timeout=60.0, follow_redirects=True)
                            resp.raise_for_status()
                        dest.write_bytes(resp.content)
                        print(f"    ✅ {filename} ({len(resp.content) // 1024} KB) [CDN]")
                        downloaded = True
                    except Exception as e:
                        print(f"    ⚠️ CDN download failed for {filename}: {e}")

                if downloaded:
                    sfx_count += 1
                else:
                    print(f"    ❌ {filename}: all download strategies failed")
                    image.pop("sfx", None)
                    image.pop("sfxVolume", None)
        # Sound diagnostics
        print(f"  🔊 Sound effects: {sfx_count}/{sfx_total} SFX files downloaded")

        # Final SFX verification: remove sfx props for any files that don't
        # actually exist on disk (guards against silent download failures,
        # expired URLs, or corrupt writes).
        sfx_removed = 0
        for scene in props.get("scenes", []):
            for image in scene.get("images", []):
                sfx_path = image.get("sfx")
                if not sfx_path:
                    continue
                full_path = public_dir / sfx_path
                if not full_path.exists() or full_path.stat().st_size < 100:
                    print(f"    ⚠️ SFX missing/empty on disk, removing from props: {sfx_path}")
                    image.pop("sfx", None)
                    image.pop("sfxVolume", None)
                    sfx_removed += 1
        if sfx_removed:
            print(f"  ⚠️ Removed {sfx_removed} SFX references (files not on disk)")

        # Re-save props.json — the SFX download loop may have removed sfxUrl
        # keys and the verification above may have removed sfx props for
        # files that failed to download.  Without this re-save, Remotion reads
        # the stale props.json that still references missing SFX files → 404.
        with open(props_file, "w") as f:
            json.dump(props, f, indent=2)

        # Verify every scene has its audio file (Remotion will 404 without it)
        # Use actual scene numbers from props — NOT sequential range(1, N+1)
        # which breaks when scene numbers have gaps or don't start at 1.
        missing_audio = []
        for scene in props.get("scenes", []):
            scene_num = scene.get("sceneNumber", 0)
            audio_path = public_dir / f"Scene {scene_num}.mp3"
            if not audio_path.exists():
                missing_audio.append(f"Scene {scene_num}.mp3")

        if missing_audio:
            # Fallback: fetch voice files from Airtable Script table attachments
            print(f"  ⚠️ {len(missing_audio)} audio files not found in Drive, trying Airtable fallback...")
            import httpx as _httpx
            scripts = self.airtable.get_scripts_by_title(self.video_title)
            scripts_by_scene = {s.get("scene", 0): s for s in scripts}

            still_missing = []
            for fname in missing_audio:
                # Parse scene number from "Scene N.mp3"
                scene_num = int(fname.split("Scene ")[1].split(".mp3")[0])
                script = scripts_by_scene.get(scene_num)
                if not script:
                    still_missing.append(fname)
                    continue

                voice_over = script.get("Voice Over")
                voice_url = None
                if isinstance(voice_over, list) and voice_over:
                    voice_url = voice_over[0].get("url")
                elif isinstance(voice_over, str):
                    voice_url = voice_over

                if not voice_url:
                    still_missing.append(fname)
                    continue

                try:
                    async with _httpx.AsyncClient() as http:
                        resp = await http.get(voice_url, timeout=60.0, follow_redirects=True)
                        resp.raise_for_status()
                    dest = public_dir / fname
                    dest.write_bytes(resp.content)
                    print(f"    ✅ {fname} (from Airtable, {len(resp.content) // 1024} KB)")
                except Exception as e:
                    print(f"    ❌ {fname} Airtable fallback failed: {e}")
                    still_missing.append(fname)

            missing_audio = still_missing

        if missing_audio:
            missing_list = ", ".join(missing_audio[:10])
            print(f"  ❌ Missing audio files: {missing_list}")
            self.slack.notify(
                f"❌ *Render ABORTED:* _{self.video_title}_\n"
                f"Missing audio: {missing_list}\n"
                f"Searched Drive + Airtable — these files were not found anywhere."
            )
            return {"error": f"Missing audio: {missing_list}", "bot": "Render Bot"}

        scene_count = len(props.get("scenes", []))

        # Video clip status line — count from render_config (includes
        # pre-existing mp4s on disk, not just newly downloaded ones)
        rc_scenes = props.get("renderConfig", {}).get("scenes", [])
        actual_video_count = sum(1 for s in rc_scenes if s.get("type") == "video")
        actual_image_count = sum(1 for s in rc_scenes if s.get("type") != "video")
        if actual_video_count > 0:
            video_info = f"\n🎬 Video clips: {actual_video_count} animated, {actual_image_count} static images"
        elif actual_image_count > 0:
            video_info = f"\n🖼️ {actual_image_count} static images (no video clips)"
        else:
            video_info = ""

        # Sound effects status line
        sound_info = ""
        if sfx_count > 0:
            sound_info = f"\n🔊 Sound effects: {sfx_count}/{sfx_total} SFX files ready"
        elif sfx_total > 0:
            sound_info = f"\n⚠️ {sfx_total} SFX expected but 0 downloaded"
        else:
            sound_info = "\n🔇 No sound effects"
        self.slack.notify(
            f"⬇️ *Assets ready:* _{self.video_title}_\n"
            f"{scene_count} scenes, {audio_count} audio files verified."
            f"{video_info}{sound_info}\n"
            f"Starting Remotion render now..."
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
                self.slack.notify(
                    f"❌ *Render FAILED:* _{self.video_title}_\n"
                    f"`npm install` failed in remotion-video/. Check node/npm on VPS."
                )
                return {"error": "npm install failed", "bot": "Render Bot"}

        # Clear Remotion's webpack bundle cache to guarantee fresh data.
        # The static import of render_config.json gets baked into the cached
        # bundle; without clearing, a previous video's caption text persists.
        remotion_cache = remotion_dir / ".remotion"
        if remotion_cache.exists():
            shutil.rmtree(remotion_cache, ignore_errors=True)
            print(f"  🧹 Cleared Remotion bundle cache")

        # Render (optimized for KVM4: 4 vCPU / 16GB RAM)
        import time as _time
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

        # Stream render output to track progress and send Slack updates
        print(f"  🎯 Render cmd: {' '.join(str(c) for c in render_cmd)}")
        render_start = _time.time()
        last_update_frame = 0  # Track last frame count we reported
        last_update_time = render_start
        FRAME_UPDATE_INTERVAL = 5000  # Send update every N frames
        TIME_UPDATE_INTERVAL = 300   # Or every 5 minutes
        last_error_line = ""

        process = subprocess.Popen(
            render_cmd, cwd=remotion_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            print(f"    {line}")

            # Parse Remotion frame progress: "Rendered 500/28800"
            frame_match = re.search(r'Rendered\s+(\d+)/(\d+)', line)
            if frame_match:
                current_frame = int(frame_match.group(1))
                total_frames = int(frame_match.group(2))
                current_pct = (current_frame / total_frames * 100) if total_frames > 0 else 0
                now = _time.time()
                elapsed = now - render_start
                elapsed_min = int(elapsed / 60)
                frames_since_update = current_frame - last_update_frame
                time_since_update = now - last_update_time

                # Send Slack update every 5000 frames OR every 5 minutes
                if frames_since_update >= FRAME_UPDATE_INTERVAL or time_since_update >= TIME_UPDATE_INTERVAL:
                    # Estimate remaining time
                    if current_pct > 0:
                        total_est = elapsed / (current_pct / 100)
                        remaining_min = int((total_est - elapsed) / 60)
                        eta_str = f"~{remaining_min} min remaining"
                    else:
                        eta_str = "estimating..."

                    progress_bar = "█" * int(current_pct // 10) + "░" * (10 - int(current_pct // 10))
                    self.slack.notify(
                        f"🎬 *Render progress:* _{self.video_title}_\n"
                        f"`{progress_bar}` *{current_pct:.1f}%* — frame {current_frame}/{total_frames} — {elapsed_min} min elapsed, {eta_str}"
                    )
                    last_update_frame = current_frame
                    last_update_time = now

            # Capture error lines for failure reporting
            if "error" in line.lower() or "Error" in line:
                last_error_line = line

        returncode = process.wait()
        total_min = int((_time.time() - render_start) / 60)

        if returncode != 0:
            print(f"  ❌ Render failed")
            error_detail = f"\n`{last_error_line}`" if last_error_line else ""
            self.slack.notify(
                f"❌ *Render FAILED:* _{self.video_title}_\n"
                f"Remotion exited with code {returncode} after {total_min} min.{error_detail}"
            )
            return {"error": "Render failed", "bot": "Render Bot"}

        if not output_file.exists():
            print(f"  ❌ Output not found")
            self.slack.notify(
                f"❌ *Render FAILED:* _{self.video_title}_\n"
                f"Remotion finished but output file not found at {output_file}"
            )
            return {"error": "Output file missing", "bot": "Render Bot"}

        file_size_mb = output_file.stat().st_size / (1024 * 1024)
        print(f"  ✅ Rendered: {output_file} ({file_size_mb:.0f} MB)")

        # Upload to Drive
        print("  ☁️ Uploading to Google Drive...")
        self.slack.notify(
            f"✅ *Render complete:* _{self.video_title}_ ({file_size_mb:.0f} MB, {total_min} min)\n"
            f"Uploading to Google Drive..."
        )
        with open(output_file, "rb") as f:
            video_content = f.read()
        
        drive_file = self.google.upload_video(video_content, f"{safe_name}.mp4", folder_id)
        drive_url = f"https://drive.google.com/file/d/{drive_file['id']}/view"

        # Update Airtable — store in both legacy and new field names
        self.airtable.update_idea_fields(self.current_idea_id, {
            "Final Video": drive_url,
            "Final Video URL": drive_url,
        })
        self._update_status(self.STATUS_RENDERED)

        # Free video content from memory before cleanup
        del video_content

        # CLEAN ALL RENDER ASSETS — video is safely on Drive now
        self._clean_render_assets(label="post-upload")

        print(f"  ✅ Status updated to: {self.STATUS_RENDERED}")
        print(f"  🔗 Video: {drive_url}")

        self.slack.notify(
            f"✅ *Render complete:* _{self.video_title}_\n"
            f"📺 *Drive link:* {drive_url}\n\n"
            f"Generating SEO metadata and uploading to YouTube next..."
        )

        return {
            "bot": "Render Bot",
            "video_title": self.video_title,
            "new_status": self.STATUS_RENDERED,
            "video_url": drive_url
        }

    async def run_audio_sync(self, audio_path: str = None, scene_list: list = None) -> dict:
        """Calculate per-image durations by matching Sentence Text to audio.

        For each scene:
        1. Download Scene N.mp3 from Google Drive
        2. Transcribe with Whisper → word-level timestamps
        3. Walk through each image's Sentence Text sequentially
        4. Duration = how long it takes to say that sentence
        5. Write duration to image's Airtable record immediately
        """
        from pathlib import Path as _Path
        from audio_sync.transcriber import transcribe
        from audio_sync.transition_engine import assign_transitions
        from audio_sync.ken_burns_calculator import assign_ken_burns
        from collections import defaultdict
        import subprocess as _sp

        if not self.current_idea:
            return {"error": "No current idea loaded"}

        print(f"\n🎵 AUDIO SYNC: Processing '{self.video_title}'")

        video_id = self.current_idea_id or "unknown"
        pipeline_dir = _Path(__file__).parent
        timing_dir = pipeline_dir / "timing" / video_id
        timing_dir.mkdir(parents=True, exist_ok=True)
        audio_dir = timing_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        # ── Step 1: Load image records from Airtable ──
        print(f"  Step 1/4: Loading image records from Airtable...")
        image_records = self.airtable.get_all_images_for_video(self.video_title)
        if not image_records:
            return {"error": "No image records found in Airtable", "bot": "Audio Sync"}

        scenes_images: dict[int, list[dict]] = defaultdict(list)
        for img in image_records:
            scene_num = img.get("Scene")
            if scene_num is not None:
                scenes_images[scene_num].append(img)
        for sn in scenes_images:
            scenes_images[sn].sort(key=lambda x: x.get("Image Index", 0))

        scene_numbers = sorted(scenes_images.keys())
        total_images = sum(len(imgs) for imgs in scenes_images.values())
        print(f"  Found {total_images} images across {len(scene_numbers)} scenes")

        # ── Step 2: Download scene audio from Google Drive ──
        print(f"  Step 2/4: Downloading scene audio from Google Drive...")
        scene_audio_paths: dict[int, _Path] = {}

        if self.project_folder_id:
            try:
                drive_files = self.google.list_files_in_folder(self.project_folder_id)
                scene_mp3s = [
                    f for f in drive_files
                    if f["name"].startswith("Scene ") and f["name"].endswith(".mp3")
                ]
                for df in scene_mp3s:
                    local_path = audio_dir / df["name"]
                    if not local_path.exists():
                        content = self.google.download_file(df["id"])
                        if len(content) < 500:
                            continue
                        local_path.write_bytes(content)
                    try:
                        snum = int(df["name"].replace("Scene ", "").replace(".mp3", "").strip())
                        scene_audio_paths[snum] = local_path
                    except ValueError:
                        pass
                print(f"  Downloaded {len(scene_audio_paths)} scene audio files")
            except Exception as e:
                print(f"  ⚠️ Drive download failed ({e}), trying local files...")

        if not scene_audio_paths:
            remotion_dir = pipeline_dir.parent.parent / "remotion-video"
            public_dir = remotion_dir / "public"
            for mp3 in sorted(public_dir.glob("Scene *.mp3")):
                try:
                    snum = int(mp3.name.replace("Scene ", "").replace(".mp3", "").strip())
                    scene_audio_paths[snum] = mp3
                except ValueError:
                    pass
            if scene_audio_paths:
                print(f"  ⚠️ Using {len(scene_audio_paths)} audio files from public/")

        if not scene_audio_paths:
            return {"error": "No scene audio files found. Run voice bot first.", "bot": "Audio Sync"}

        # ── Step 3: Transcribe each scene & match sentence durations ──
        print(f"  Step 3/4: Transcribing scenes & matching sentences...")

        duration_updates = 0
        total_duration = 0.0
        scene_durations: dict[int, float] = {}
        # Cache calculated durations locally so Step 4 can use them
        # (Airtable records in scenes_images are stale after Step 3 writes)
        image_durations: dict[tuple[int, int], float] = {}  # (scene_num, img_index) -> seconds

        for scene_num in scene_numbers:
            images = scenes_images[scene_num]
            audio_file = scene_audio_paths.get(scene_num)

            if not audio_file or not audio_file.exists():
                print(f"    Scene {scene_num}: ⚠️ no audio, skipping")
                continue

            # Transcribe this scene's audio with Whisper
            cache_dir = timing_dir / f"scene_{scene_num}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            try:
                words = transcribe(str(audio_file), cache_dir=cache_dir)
            except Exception as e:
                print(f"    Scene {scene_num}: ⚠️ Whisper failed ({e}), skipping")
                continue

            if not words:
                print(f"    Scene {scene_num}: ⚠️ no words transcribed")
                continue

            # Validate Whisper timestamps against actual audio duration.
            # The Whisper API word-level timestamps can drift significantly
            # from the real audio timeline (sometimes 2x). Use ffprobe as
            # ground truth and scale timestamps when they diverge.
            whisper_dur = words[-1].end
            actual_dur = None
            try:
                probe = _sp.run(
                    ["ffprobe", "-v", "quiet", "-show_entries",
                     "format=duration", "-of",
                     "default=noprint_wrappers=1:nokey=1",
                     str(audio_file)],
                    capture_output=True, text=True, timeout=10,
                )
                if probe.returncode == 0 and probe.stdout.strip():
                    actual_dur = float(probe.stdout.strip())
            except Exception:
                pass

            # Fallback to mutagen if ffprobe unavailable
            if actual_dur is None:
                try:
                    from mutagen.mp3 import MP3
                    actual_dur = MP3(str(audio_file)).info.length
                except Exception:
                    pass

            if actual_dur and whisper_dur > 0:
                drift = abs(actual_dur - whisper_dur) / actual_dur
                if drift > 0.10:
                    scale = actual_dur / whisper_dur
                    print(f"    Scene {scene_num}: ⚠️ Whisper duration drift — "
                          f"audio={actual_dur:.2f}s, whisper={whisper_dur:.2f}s, "
                          f"scaling by {scale:.3f}")
                    for w in words:
                        w.start *= scale
                        w.end *= scale

            scene_audio_dur = words[-1].end
            print(f"    Scene {scene_num}: {len(words)} words, {scene_audio_dur:.1f}s — {len(images)} images")

            # ── Write Remotion caption file ──
            # Remotion's transcripts.ts reads word-level timestamps from
            # src/captions/Scene N.json (compiled into the bundle at render
            # time). Write drift-corrected words so karaoke timing and
            # scene durations are consistent with render_config.
            captions_dir = _Path(__file__).parent.parent.parent / "remotion-video" / "src" / "captions"
            captions_dir.mkdir(parents=True, exist_ok=True)
            caption_path = captions_dir / f"Scene {scene_num}.json"
            caption_data = {
                "text": " ".join(w.word.strip() for w in words),
                "segments": [{
                    "id": 0,
                    "start": words[0].start,
                    "end": words[-1].end,
                    "text": " ".join(w.word.strip() for w in words),
                    "words": [
                        {"word": w.word, "start": round(w.start, 4),
                         "end": round(w.end, 4), "probability": 1.0}
                        for w in words
                    ],
                }],
                "language": "en",
            }
            try:
                with open(caption_path, "w") as _f:
                    json.dump(caption_data, _f, indent=2)
                print(f"    Scene {scene_num}: wrote {len(words)} words to {caption_path.name}")
            except Exception as e:
                print(f"    Scene {scene_num}: ⚠️ caption write failed ({e})")

            # ── Proportional word-count mapping ──
            # Each image's Sentence Text covers a portion of the scene
            # narration. Allocate Whisper words proportionally based on
            # each sentence's word count, then read durations straight
            # from the Whisper timestamps. No fuzzy matching needed —
            # both the sentence texts and Whisper words are in order.
            img_entries = []  # (record, img_index, sentence, word_count)
            total_sentence_words = 0
            for img_idx, img in enumerate(images):
                sentence = img.get("Sentence Text", "") or ""
                img_index = img.get("Image Index", img_idx + 1)
                if not sentence.strip():
                    print(f"      Image {img_index}: (no sentence text, skipping)")
                    continue
                wc = len(sentence.split())
                if wc == 0:
                    continue
                img_entries.append((img, img_index, sentence, wc))
                total_sentence_words += wc

            if not img_entries:
                print(f"    Scene {scene_num}: no images with sentence text")
                continue

            total_whisper = len(words)
            scene_total = 0.0

            # Pass 1: find each image's start index in the Whisper words
            cumulative = 0
            start_indices = []
            for _img, _idx, _sent, wc in img_entries:
                frac = cumulative / total_sentence_words
                w_start = int(round(frac * total_whisper))
                w_start = max(0, min(w_start, total_whisper - 1))
                start_indices.append(w_start)
                cumulative += wc

            # Pass 2: duration = gap between consecutive start times.
            # This naturally includes inter-sentence pauses in the
            # narrator's delivery, giving each image its full display
            # window (speech + following pause).
            scene_raw: list[dict] = []
            for entry_idx, (img, img_index, sentence, wc) in enumerate(img_entries):
                start_time = words[start_indices[entry_idx]].start

                if entry_idx < len(img_entries) - 1:
                    end_time = words[start_indices[entry_idx + 1]].start
                else:
                    end_time = words[-1].end

                dur = round(end_time - start_time, 2)
                dur = max(dur, 1.0)

                scene_raw.append({
                    "record_id": img["id"],
                    "image_index": img_index,
                    "sentence_text": sentence,
                    "duration": dur,
                    "display_start": round(start_time, 4),
                    "display_end": round(end_time, 4),
                    "word_count": wc,
                })

            # Enforce max duration per image — prevents one long sentence
            # from monopolising a scene (e.g. 47s, 60s instead of ~10s).
            from audio_sync.timing_adjuster import enforce_max_image_duration
            scene_raw = enforce_max_image_duration(scene_raw)

            for entry in scene_raw:
                record_id = entry["record_id"]
                img_index = entry["image_index"]
                dur = entry["duration"]
                sentence = entry["sentence_text"]
                wc = entry["word_count"]

                image_durations[(scene_num, img_index)] = dur

                try:
                    self.airtable.images_table.update(
                        record_id, {"Duration (s)": dur}, typecast=True,
                    )
                    duration_updates += 1
                except Exception as e:
                    print(f"      Image {img_index}: ⚠️ Airtable write failed ({e})")

                total_duration += dur
                scene_total += dur
                print(f"      Image {img_index}: {dur:.2f}s ({wc}w) — \"{sentence[:50]}...\"")

            scene_durations[scene_num] = scene_total


        # ── Step 4: Build per-IMAGE render config ──
        # Each image gets its own entry with sentence_text so Remotion can
        # match words to images precisely. Entries are grouped by scene_number.
        print(f"  Step 4/4: Writing per-image render config...")

        from audio_sync.render_config_writer import build_render_config, write_render_config

        running_time = 0.0
        timed_images = []
        for scene_num in scene_numbers:
            images = scenes_images[scene_num]
            for img_idx, img in enumerate(images):
                sentence = img.get("Sentence Text", "") or ""
                img_index = img.get("Image Index", img_idx + 1)

                # Look up the enforced duration calculated in Step 3.
                # The local scenes_images dict is stale (loaded before Step 3),
                # so we use the image_durations cache instead.
                dur = image_durations.get((scene_num, img_index), 0)
                if dur <= 0:
                    # Image was absorbed by duration enforcement (merged with
                    # neighbor) — skip it so render_config.json doesn't include
                    # a phantom entry.
                    continue
                dur = float(dur)

                # Use actual composition from image record (Shot Type)
                composition = img.get("Shot Type", "") or "wide"

                timed_images.append({
                    "scene_number": scene_num,
                    "image_index": img_index,
                    "sentence_text": sentence,
                    "start_time": round(running_time, 4),
                    "end_time": round(running_time + dur, 4),
                    "duration": round(dur, 4),
                    "display_start": round(running_time, 4),
                    "display_end": round(running_time + dur, 4),
                    "display_duration": round(dur, 4),
                    "alignment_method": "sentence_match",
                    "style": "",
                    "composition": composition,
                })
                running_time += dur

        timed_images = assign_transitions(timed_images)
        timed_images = assign_ken_burns(timed_images)

        # Concat scene audio for the full-video audio path
        concat_path = timing_dir / "narration_concat.mp3"
        sorted_audio = sorted(scene_audio_paths.items())
        list_file = timing_dir / "concat_list.txt"
        with open(list_file, "w") as f:
            for _, sa in sorted_audio:
                f.write(f"file '{sa}'\n")
        try:
            _sp.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(list_file), "-c", "copy", str(concat_path)],
                capture_output=True, check=True,
            )
        except Exception:
            concat_path = sorted_audio[0][1] if sorted_audio else _Path("")

        remotion_dir = _Path(__file__).parent.parent.parent / "remotion-video"
        image_dir = str(remotion_dir / "public")

        config = build_render_config(
            video_id=video_id,
            audio_path=str(concat_path),
            scenes=timed_images,
            image_dir=image_dir,
        )

        # Write to timing directory
        write_render_config(config, timing_dir / "render_config.json")

        # Also copy to remotion-video/public/ so Remotion can read it at render time
        remotion_public = remotion_dir / "public"
        remotion_public.mkdir(parents=True, exist_ok=True)
        write_render_config(config, remotion_public / "render_config.json")

        avg_dur = total_duration / max(duration_updates, 1)
        print(f"\n  ✅ {duration_updates} image durations written to Airtable")
        print(f"  Avg image duration: {avg_dur:.1f}s")
        print(f"  Total duration: {total_duration:.1f}s")
        print(f"  Render config: {timing_dir / 'render_config.json'}")
        print(f"  Remotion config: {remotion_public / 'render_config.json'}")
        print(f"  Per-image entries: {len(timed_images)}")

        return {
            "bot": "Audio Sync",
            "video_title": self.video_title,
            "timing_dir": str(timing_dir),
            "render_config_path": str(timing_dir / "render_config.json"),
            "remotion_config_path": str(remotion_public / "render_config.json"),
            "total_duration": total_duration,
            "scene_count": len(scene_numbers),
            "image_count": duration_updates,
            "avg_duration": round(avg_dur, 2),
            "alignment_quality": "sentence_match",
        }

    async def run_youtube_upload_bot(self) -> dict:
        """Generate SEO metadata and upload video to YouTube as unlisted draft.

        REQUIRES: Ideas status = "Rendered"
        UPDATES TO: "Uploaded (Draft)" when complete
        """
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_RENDERED)
            if not idea:
                return {"error": "No idea with status 'Rendered'"}
            self._load_idea(idea)

        print(f"\n📺 YOUTUBE UPLOAD BOT: Processing '{self.video_title}'")
        self.slack.notify(
            f"📺 *YouTube upload starting:* _{self.video_title}_\n"
            f"Generating SEO description and uploading as unlisted draft..."
        )

        # --- STEP 1: Generate SEO metadata ---
        print("  Generating SEO metadata...")
        try:
            from bots.seo_generator import SEOGenerator

            seo = SEOGenerator(self.anthropic)
            scripts = self.airtable.get_scripts_by_title(self.video_title)
            hook = self.current_idea.get("Hook Script", "")

            seo_result = seo.generate(
                title=self.video_title,
                hook=hook,
                scripts=scripts,
            )

            # Store SEO fields in Airtable
            self.airtable.update_idea_fields(self.current_idea_id, {
                "SEO Description": seo_result["description"],
                "SEO Tags": seo_result["tags"],
                "SEO Hashtags": seo_result["hashtags"],
            })
            print(f"  SEO metadata saved to Airtable")
            print(f"    Hook line: {seo_result.get('hook_line', '')[:100]}")
        except Exception as e:
            print(f"  Warning: SEO generation failed: {e}")
            print(f"  Continuing with basic description...")
            # Fallback: use hook as description
            fallback_desc = self.current_idea.get("Hook Script", self.video_title)
            self.airtable.update_idea_field(
                self.current_idea_id, "SEO Description", fallback_desc
            )
            seo_result = {
                "description": fallback_desc,
                "tags": "",
                "hashtags": "",
            }

        # Reload idea to get updated fields
        updated_ideas = self.airtable.get_ideas_by_status(self.STATUS_RENDERED, limit=10)
        idea_fresh = None
        for i in updated_ideas:
            if i["id"] == self.current_idea_id:
                idea_fresh = i
                break
        if not idea_fresh:
            idea_fresh = self.current_idea
            idea_fresh["SEO Description"] = seo_result["description"]
            idea_fresh["SEO Tags"] = seo_result["tags"]

        # --- STEP 2: Upload to YouTube ---
        print("  Uploading to YouTube...")
        try:
            from bots.youtube_uploader import YouTubeUploader

            yt = YouTubeUploader()
            upload_result = yt.upload_from_drive(
                google_client=self.google,
                airtable_client=self.airtable,
                idea=idea_fresh,
            )

            if upload_result.get("error"):
                raise Exception(upload_result["error"])

        except FileNotFoundError as e:
            # YouTube token not configured — skip upload, just save SEO
            print(f"  YouTube credentials not configured: {e}")
            print(f"  SEO metadata saved. Upload skipped (run youtube_auth.py first).")
            self.slack.notify(
                f"⚠️ *YouTube upload skipped:* _{self.video_title}_\n"
                f"YouTube credentials not configured. SEO metadata saved.\n"
                f"Run `python youtube_auth.py` on VPS, then re-run pipeline."
            )
            return {
                "bot": "YouTube Upload Bot",
                "video_title": self.video_title,
                "warning": "YouTube credentials not configured",
                "new_status": self.STATUS_RENDERED,
            }
        except Exception as e:
            error_msg = f"YouTube upload failed: {e}"
            print(f"  {error_msg}")
            self.slack.notify(
                f"❌ *YouTube upload FAILED:* _{self.video_title}_\n"
                f"```{e}```\n"
                f"SEO metadata saved. Fix and re-run."
            )
            return {
                "status": "failed",
                "bot": "YouTube Upload Bot",
                "video_title": self.video_title,
                "error": error_msg,
            }

        # --- STEP 3: Update status and notify ---
        self._update_status(self.STATUS_UPLOADED_DRAFT)

        video_url = upload_result.get("video_url", "")
        folder_id = self.current_idea.get("Drive Folder ID", "")
        folder_url = (
            f"https://drive.google.com/drive/folders/{folder_id}"
            if folder_id else
            self.current_idea.get("Drive Folder Link", "")
        )
        description_preview = seo_result.get("description", "")[:100]

        # Slack notification for draft review (US-006)
        self.slack.notify(
            f"📺 *Video Ready for Review!*\n\n"
            f'"{self.video_title}"\n\n'
            f"🎬 *YouTube Draft:* {video_url}\n"
            f"📁 *Drive Folder:* {folder_url}\n"
            f"📝 *Description preview:* {description_preview}...\n\n"
            f"When ready, open YouTube Studio and set to Public."
        )

        print(f"  Status updated to: {self.STATUS_UPLOADED_DRAFT}")
        print(f"  YouTube: {video_url}")

        return {
            "bot": "YouTube Upload Bot",
            "video_title": self.video_title,
            "new_status": self.STATUS_UPLOADED_DRAFT,
            "video_url": video_url,
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

                # Per-image sound effect (new image-level system)
                sfx_attachment = img.get("Sound Effect")
                if sfx_attachment and isinstance(sfx_attachment, list) and sfx_attachment:
                    sfx_url = sfx_attachment[0].get("url", "")
                    if sfx_url:
                        sfx_filename = f"sfx_{scene_number}_{img.get('Image Index', 0)}.mp3"
                        asset["sfx"] = f"sfx/{sfx_filename}"
                        asset["sfxVolume"] = img.get("Sound Volume", 0.15)
                        asset["sfxUrl"] = sfx_url  # For download during render

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

    # _extract_sound_layers removed — sound effects now live on image rows,
    # not in the Script table's Sound Map JSON.

    def generate_segment_data_ts(self, remotion_dir: Path = None) -> str:
        """DEPRECATED: Use audio_sync.render_config_writer instead.

        This method generated the old segmentData.ts file for Remotion.
        Timing data now comes from render_config.json produced by the
        audio_sync pipeline (Whisper-driven timestamps).

        Kept for backward compatibility but is a no-op.
        """
        import warnings
        warnings.warn(
            "generate_segment_data_ts is deprecated. "
            "Use audio_sync.render_config_writer to produce render_config.json.",
            DeprecationWarning,
            stacklevel=2,
        )
        return ""

    def _generate_segment_data_ts_legacy(self, remotion_dir: Path = None) -> str:
        """Legacy implementation preserved for reference. Do not call directly.

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
                # Escape for TypeScript double-quoted strings:
                # backslashes first, then quotes, then newlines
                escaped_text = (
                    seg["text"]
                    .replace('\\', '\\\\')
                    .replace('"', '\\"')
                    .replace('\n', ' ')
                    .replace('\r', ' ')
                    .replace('`', '\\`')
                    .replace('${', '\\${')
                )
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

                    # Update Airtable (with Drive URL for animation)
                    self.airtable.update_image_record(record_id, image_url, drive_url=drive_url)
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
        print("  --competitors     Scrape competitor channels and generate modeled ideas")
        print("  --discover        Scan headlines for video ideas and save to Airtable")
        print("  --translate       Run brief translator (research brief → script + scenes)")
        print("  --styled-prompts  Run image prompt engine with visual identity system")
        print('  --full "..."      Full pipeline: Idea → Script → Voice → Images → Render')
        print("  --produce [id]    Produce pipeline from a queued idea to completion")
        print("  --from-stage X    Resume pipeline from a specific stage")
        print("  --sync            Sync assets to Google Drive")
        print("  --remotion        Export Remotion props for rendering")
        print('  --regenerate      Regenerate missing images (fixes render failures)')
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
        from clients.anthropic_client import AnthropicClient as _AnthropicClient
        from clients.airtable_client import AirtableClient as _AirtableClient

        anthropic = _AnthropicClient()
        airtable = _AirtableClient()
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

            slack.notify(chr(10).join(msg_lines))
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

    # === COMPETITOR SCRAPER ===
    if len(sys.argv) > 1 and sys.argv[1] == "--competitors":
        from bots.competitor_scraper import CompetitorScraper

        if not pipeline.apify:
            print("ERROR: APIFY_API_KEY not configured. Add it to .env")
            return

        # Parse optional VPH threshold
        vph_threshold = None
        if len(sys.argv) > 2:
            try:
                vph_threshold = float(sys.argv[2])
                print(f"  Using VPH threshold: {vph_threshold}")
            except ValueError:
                pass

        scraper = CompetitorScraper(
            apify_client=pipeline.apify,
            anthropic_client=pipeline.anthropic,
            airtable_client=pipeline.airtable,
            slack_client=pipeline.slack,
        )

        result = await scraper.run(
            vph_threshold=vph_threshold,
            num_ideas=3,
            save_to_airtable=True,
            notify_slack=True,
        )
        return

    # === DISCOVERY SCANNER ===
    if len(sys.argv) > 1 and sys.argv[1] == "--discover":
        from discovery_scanner import run_discovery, format_ideas_for_slack, build_option_map, build_idea_record_from_discovery
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
            idea_data = build_idea_record_from_discovery(idea, idea_number=i)
            title = idea_data.get("viral_title", "Untitled")
            try:
                record = pipeline.airtable.create_idea(idea_data, source="discovery_scanner")
                saved_record_ids.append(record.get("id"))
                print(f"  ✅ Saved idea {i}: {record.get('id')} — {title}")
            except Exception as e:
                saved_record_ids.append(None)
                print(f"  ❌ Failed to save idea {i}: {e}")

        # Post interactive Slack message with emoji reactions for idea selection
        # This lets the user wake up and click to choose an idea
        # Always target production-agent channel — cron runs unattended so we
        # can't rely on SLACK_CHANNEL_ID env var which may point elsewhere.
        production_channel = SlackClient.DEFAULT_CHANNEL_ID
        try:
            slack_msg = (
                "☀️ *Good Morning! Daily Discovery Scan Complete*\n"
                "React with 1️⃣ 2️⃣ or 3️⃣ to approve an idea — I'll auto-research it and queue it for the 8 AM pipeline run.\n\n"
            )
            slack_msg += format_ideas_for_slack(result)

            response = pipeline.slack.send_message(slack_msg, production_channel)
            msg_ts = response["ts"]

            # Build option map: one emoji per title option (idea + title)
            option_map = build_option_map(ideas)
            emoji_names = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
            emojis_to_add = emoji_names[:len(option_map)]

            for emoji in emojis_to_add:
                try:
                    pipeline.slack.add_reaction(emoji, msg_ts, production_channel)
                except Exception as e:
                    print(f"  ⚠️ Failed to add reaction {emoji}: {e}")

            # Persist tracking data so the Slack bot (pipeline_control.py)
            # can handle the reaction when the user clicks
            save_discovery_message(msg_ts, ideas, saved_record_ids)
            print(f"\n✅ Interactive Slack message posted (ts={msg_ts})")
            print(f"   {len(option_map)} options with emoji reactions — waiting for your choice!")

        except Exception as e:
            print(f"\n❌ Slack notification FAILED: {e}")
            # Fallback: try a shorter plain message (no reactions/tracking)
            try:
                # Send a compact version in case the full message was too long
                short_msg = "☀️ *Discovery Scan Complete* — ideas saved to Airtable.\n"
                for i, idea in enumerate(ideas, 1):
                    title_opts = idea.get("title_options", [])
                    title = title_opts[0]["title"] if title_opts else "Untitled"
                    short_msg += f"{i}. {title}\n"
                short_msg += "\nCheck Airtable to approve."
                pipeline.slack.send_message(short_msg, production_channel)
                print("   Sent short fallback message to Slack")
            except Exception as e2:
                print(f"   Fallback also failed: {e2}")
                print("   Ideas were saved to Airtable — check there manually.")

        return

    if len(sys.argv) > 1 and sys.argv[1] == "--sync":
        # Sync assets for a specific video
        # Hardcoded for now or args? User wants specific video.
        title = "The 2030 Currency Collapse: Which Assets Will YOU Still Own?"
        await pipeline.sync_all_assets(title)
        return
        
    if len(sys.argv) > 1 and sys.argv[1] == "--remotion":
        # Export Remotion props for a specific video
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

        # NOTE: segmentData.ts generation removed — timing data now comes from
        # render_config.json produced by the audio_sync pipeline.
        remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"

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
        print("  Script → Voice → Image Prompts → Images → Thumbnail → Render → YouTube Upload")
        print("  Videos at 'Idea Logged' are SKIPPED (awaiting your approval)\n")

        # Notify Slack that the daily pipeline run has started
        try:
            # Show actual Pacific time in the notification
            now_pacific = datetime.now(ZoneInfo("America/Los_Angeles"))
            time_str = now_pacific.strftime("%-I:%M %p PT")

            # Quick scan of what's in the pipeline
            status_summary = []
            for status_name in [
                pipeline.STATUS_READY_SCRIPTING,
                pipeline.STATUS_READY_VOICE,
                pipeline.STATUS_READY_SOUND_DESIGN,
                pipeline.STATUS_READY_SOUND_EFFECTS,
                pipeline.STATUS_READY_IMAGE_PROMPTS,
                pipeline.STATUS_READY_IMAGES,
                pipeline.STATUS_READY_THUMBNAIL,
                pipeline.STATUS_DONE,
                pipeline.STATUS_READY_TO_RENDER,
                pipeline.STATUS_RENDERED,
            ]:
                ideas_at_status = pipeline.airtable.get_ideas_by_status(status_name, limit=10)
                if ideas_at_status:
                    titles = [i.get("Video Title", "Untitled")[:40] for i in ideas_at_status]
                    status_summary.append(f"  • *{status_name}*: {', '.join(titles)}")

            if status_summary:
                pipeline.slack.send_message(
                    f"🔄 *{time_str} Pipeline Run Starting*\n"
                    "Scanning all tables and processing every stage through to YouTube upload.\n\n"
                    "*Work found:*\n" + "\n".join(status_summary)
                )
            else:
                pipeline.slack.send_message(
                    f"🔄 *{time_str} Pipeline Run Starting*\n"
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
