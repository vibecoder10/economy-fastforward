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
import sys
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Ensure the pipeline root (skills/video-pipeline/) is on sys.path
_pipeline_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pipeline_root not in sys.path:
    sys.path.insert(0, _pipeline_root)

# Load environment variables
load_dotenv()

from shared.clients.anthropic_client import AnthropicClient
from shared.clients.airtable_client import AirtableClient
from shared.clients.google_client import GoogleClient
from shared.clients.slack_client import SlackClient
from shared.clients.elevenlabs_client import ElevenLabsClient
from shared.clients.image_client import ImageClient
from shared.clients.gemini_client import GeminiClient
from shared.clients.apify_client import ApifyYouTubeClient
from shared.clients.sound_client import SoundClient
from shared.channels import load_channel
from title_idea.idea_bot import IdeaBot
from title_idea.trending_idea_bot import TrendingIdeaBot
from sound.sound_prompt_bot import SoundPromptBot
from sound.sound_bot import SoundBot
from orchestrator.pipeline_config import VideoConfig
from orchestrator.pipeline_constants import Models, Statuses, IdeaFields, ScriptFields, ImageFields


class VideoPipeline:
    """Orchestrates the full video production pipeline based on Airtable status."""
    
    # Image generation mode:
    # - "semantic": Smart segmentation by visual concept (max 10s per segment for AI video)
    # - "sentence": One image per sentence (deprecated)
    # - "scene": Old mode with hardcoded 6 images per scene (deprecated)
    IMAGE_MODE = os.getenv("IMAGE_MODE", "semantic")
    
    # Valid statuses — single source of truth in pipeline_constants.Statuses
    STATUS_IDEA_LOGGED = Statuses.IDEA_LOGGED
    STATUS_READY_SCRIPTING = Statuses.READY_SCRIPTING
    STATUS_READY_VOICE = Statuses.READY_VOICE
    STATUS_READY_SOUND_DESIGN = Statuses.READY_SOUND_DESIGN
    STATUS_READY_SOUND_EFFECTS = Statuses.READY_SOUND_EFFECTS
    STATUS_READY_IMAGE_PROMPTS = Statuses.READY_IMAGE_PROMPTS
    STATUS_READY_IMAGES = Statuses.READY_IMAGES
    STATUS_READY_VIDEO_SCRIPTS = Statuses.READY_VIDEO_SCRIPTS
    STATUS_READY_VIDEO_GENERATION = Statuses.READY_VIDEO_GENERATION
    STATUS_READY_THUMBNAIL = Statuses.READY_THUMBNAIL
    STATUS_DONE = Statuses.DONE
    STATUS_READY_TO_RENDER = Statuses.READY_TO_RENDER
    STATUS_RENDERED = Statuses.RENDERED
    STATUS_UPLOADED_DRAFT = Statuses.UPLOADED_DRAFT
    STATUS_IN_QUE = Statuses.IN_QUE
    
    def __init__(self, channel: Optional[str] = None):
        """Initialize all API clients for a given channel (tenant)."""
        self.channel_config = load_channel(channel)
        cfg = self.channel_config
        self.channel = cfg.channel_id
        # Per-channel profile selection flows to sub-bots via env (they read these)
        if cfg.script_profile:
            os.environ["SCRIPT_PROFILE"] = cfg.script_profile
        if cfg.visual_profile:
            os.environ["VISUAL_PROFILE"] = cfg.visual_profile
        self.anthropic = AnthropicClient()
        self.airtable = AirtableClient(base_id=cfg.airtable_base_id)
        self.google = GoogleClient(refresh_token=cfg.drive_refresh_token or None)
        if cfg.drive_folder_id:
            self.google.parent_folder_id = cfg.drive_folder_id
        self.slack = SlackClient()
        self.elevenlabs = ElevenLabsClient(voice_id=cfg.voice_id)
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
            records = [r for r in records if r.get(ImageFields.IMAGE_INDEX) == self.image_filter]
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
            self.current_idea[IdeaFields.STATUS] = new_status

    def _load_idea(self, idea: dict):
        """Load idea data into pipeline state."""
        self.current_idea = idea
        self.current_idea_id = idea.get("id")
        self.video_title = idea.get(IdeaFields.VIDEO_TITLE, "Untitled")

        # Restore saved Google Drive folder ID (avoids name-based search issues)
        saved_folder_id = idea.get(IdeaFields.DRIVE_FOLDER_ID)
        if saved_folder_id:
            self.project_folder_id = saved_folder_id

        # Extract Core Image URL from the idea/project record
        core_image_attachments = idea.get(IdeaFields.CORE_IMAGE, [])
        if core_image_attachments and isinstance(core_image_attachments, list):
            self.core_image_url = core_image_attachments[0].get("url", "")
        else:
            self.core_image_url = ""

        # Instantiate VideoConfig from Airtable fields (defaults to 10min/10s)
        try:
            self.video_config, duration_was_set = VideoConfig.from_airtable_record(idea)
            self._duration_was_set = duration_was_set
        except (ValueError, TypeError):
            self.video_config = VideoConfig()  # safe defaults
            self._duration_was_set = False

        # Load visual style from Airtable (for visual profile selection)
        from shared.clients.airtable_client import get_visual_style
        self.visual_style = get_visual_style(idea)
        # Set env var so load_profile() picks it up everywhere in the pipeline
        os.environ["VISUAL_PROFILE"] = self.visual_style

        print(f"\n📌 Loaded idea: {self.video_title}")
        print(f"   Status: {idea.get(IdeaFields.STATUS)}")
        print(f"   ID: {self.current_idea_id}")
        print(f"   🎬 {self.video_config.summary().splitlines()[0]}")
        print(f"   🎨 Visual style: {self.visual_style}")
        if self.project_folder_id:
            print(f"   📂 Drive Folder: {self.project_folder_id}")
        if self.core_image_url:
            print(f"   🖼️ Core Image: {self.core_image_url[:80]}...")
        else:
            print(f"   ℹ️ No Core Image — YouTube pipeline uses text-to-image (no reference needed)")

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
        scripts_finished = [s for s in scripts if s.get(ScriptFields.SCRIPT_STATUS) == ScriptFields.STATUS_FINISHED]
        scripts_to_voice = [s for s in scripts if s.get(ScriptFields.SCRIPT_STATUS) == ScriptFields.STATUS_CREATE]
        
        # Check images
        all_images = self.airtable.get_all_images_for_video(video_title)
        pending_images = [img for img in all_images if img.get(ImageFields.STATUS) == ImageFields.STATUS_PENDING]
        done_images = [img for img in all_images if img.get(ImageFields.STATUS) == ImageFields.STATUS_DONE]
        
        # Check videos (images with Video) - CONSTRAINT: Scene 1 only for now
        # We define "Video Work" as done based on Scene 1 completeness
        scene_1_images = [img for img in done_images if img.get(ImageFields.SCENE) == 1]
        scene_1_prompts = [img for img in scene_1_images if img.get(ImageFields.VIDEO_PROMPT)]
        # Check 'Video' field (list of attachments)
        scene_1_videos = [img for img in scene_1_images if img.get(ImageFields.VIDEO)]
        
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
            key=lambda x: (x.get(ImageFields.SCENE, 0), x.get(ImageFields.IMAGE_INDEX, 0))
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
        scene_1_images = [img for img in sorted_images if img.get(ImageFields.SCENE) == 1]
        if scene_1_images:
            hero_ids.append(scene_1_images[0]["id"])

        # Rule 2: Key data reveals (keywords indicate high-impact moments)
        data_keywords = ["collapse", "crash", "billion", "trillion", "percent", "2030", "prediction", "warning"]
        for img in sorted_images:
            if len(hero_ids) >= max_heroes:
                break
            segment_text = img.get(ImageFields.SENTENCE_TEXT, "").lower()
            if any(kw in segment_text for kw in data_keywords):
                if not is_consecutive_with_existing(img["id"]) and img["id"] not in hero_ids:
                    hero_ids.append(img["id"])

        # Rule 3: Final reveal (last image of final scene)
        if len(hero_ids) < max_heroes:
            last_scene = max((img.get(ImageFields.SCENE, 0) for img in sorted_images), default=0)
            final_images = [img for img in sorted_images if img.get(ImageFields.SCENE) == last_scene]
            if final_images:
                final_img = final_images[-1]
                if not is_consecutive_with_existing(final_img["id"]) and final_img["id"] not in hero_ids:
                    hero_ids.append(final_img["id"])

        return hero_ids[:max_heroes]

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

        # 3b. Check for Ready For Storyboards (prompt generation via Claude)
        idea = self.get_idea_by_status(Statuses.READY_STORYBOARDS)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Storyboard Prompts", self.run_storyboard_prompts)

        # 3c. Check for Ready For Storyboard Images (image generation from prompts)
        idea = self.get_idea_by_status(Statuses.READY_STORYBOARD_IMAGES)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Storyboard Images", self.run_storyboard_images)

        # 3d. Check for Ready For Storyboard Extraction (panel extraction after review)
        idea = self.get_idea_by_status(Statuses.READY_STORYBOARD_EXTRACTION)
        if idea:
            self._load_idea(idea)
            return await self._run_step_safe("Storyboard Extract", self.run_storyboard_extract)

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

        # 10. YouTube Upload Bot — REMOVED (C34a, S10-1 audit finding; operator
        # confirmed 2026-07-19 this Power Doctrine cron pipeline and its Slack
        # channel are retired). skills/video-pipeline/upload/run.py,
        # seo_generator.py, and youtube_uploader.py are deleted — that package
        # hardcoded @Power_Doctrine SEO and uploaded through the shared VPS
        # OAuth token onto Ryan's own channel, the exact path StoryEngine's
        # per-tenant upload had to be walled off from (see
        # storyengine/backend/pipeline_executor.py's run_upload docstring).
        # A Rendered idea now simply falls through to "No work to do" below
        # instead of crashing on the deleted import — upload to YouTube is a
        # manual step (YouTube Studio) for this pipeline until/unless a
        # replacement is wired.

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
        """Generate video ideas from a YouTube URL or concept."""
        from title_idea.run import run_idea as _step_run
        return await _step_run(self, input_text)

    async def run_trending_idea_bot(
        self, search_queries: list[str] = None, num_ideas: int = 3
    ) -> dict:
        """Generate ideas from trending YouTube videos."""
        from title_idea.run import run_trending as _step_run
        return await _step_run(self, search_queries, num_ideas)

    
    async def _refine_title_post_script(self):
        """Phase 2 title refinement — non-blocking post-script step.

        Reads the actual script content and regenerates title candidates
        using the formula library + specific details from the script.
        Updates Video Title if a better option is found.

        Has a 30-second timeout to prevent pipeline stalls.
        """
        from research.agent import refine_title_post_script

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
        """Generate voiceovers for script scenes."""
        from voice.run import run as _step_run
        return await _step_run(self)

    async def run_sound_prompt_bot(self) -> dict:
        """Generate sound design prompts from image descriptions."""
        from sound.run_design import run as _step_run
        return await _step_run(self)

    async def run_sound_bot(self) -> dict:
        """Generate sound effects from prompts."""
        from sound.run_effects import run as _step_run
        return await _step_run(self)

    async def run_image_bot(self) -> dict:
        """Generate images from prompts (outer wrapper with status management)."""
        from images.run import run as _step_run
        return await _step_run(self)

    async def run_video_script_bot(self) -> dict:
        """Generate video motion prompts for images."""
        from video_motion.run_scripts import run as _step_run
        return await _step_run(self)

    async def run_video_gen_bot(self) -> dict:
        """Generate video clips from images with motion prompts."""
        from video_motion.run_generate import run as _step_run
        return await _step_run(self)

    async def run_brief_translator(self, brief: dict = None) -> dict:
        """Generate a script from a research brief."""
        from script.run import run as _step_run
        return await _step_run(self, brief=brief)

    def _get_visual_seeds(self) -> str:
        """Extract visual seed concepts from the current idea record.

        Checks the Research Payload JSON first, then falls back to the
        Thumbnail Prompt field.
        """
        if not self.current_idea:
            return ""
        rp_raw = self.current_idea.get(IdeaFields.RESEARCH_PAYLOAD, "")
        if rp_raw:
            try:
                rp = json.loads(rp_raw) if isinstance(rp_raw, str) else rp_raw
                vs = rp.get("visual_seeds", "")
                if vs:
                    return vs
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        return self.current_idea.get(IdeaFields.THUMBNAIL_PROMPT, "")

    async def run_styled_image_prompts(self, scene_filepath: str = None) -> dict:
        """Expand script scenes into visual concepts and generate styled image prompts."""
        from image_prompts.run import run as _step_run
        return await _step_run(self)

    async def run_storyboard_prompts(self) -> dict:
        """Generate storyboard prompts via Claude (Phase 1A)."""
        from storyboard.run import run as _step_run
        return await _step_run(self)

    async def run_storyboard_images(self) -> dict:
        """Generate storyboard contact sheets from prompts (Phase 1B)."""
        from storyboard.run_images import run as _step_run
        return await _step_run(self)

    async def run_storyboard_extract(self) -> dict:
        """Extract panels from storyboard grids (Phase 2, after review)."""
        from storyboard.run_extract import run as _step_run
        return await _step_run(self)

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
        script_result = await self.run_brief_translator()
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
        current_status = idea.get(IdeaFields.STATUS)
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
                if idea.get(IdeaFields.STATUS) != self.STATUS_DONE:
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
        """Generate matched thumbnail + title pair for the video."""
        from thumbnail.run import run as _step_run
        return await _step_run(self)
    
    def _clean_render_assets(self, label: str = "stale") -> int:
        """Remove all render assets from disk (public/, captions/, out/)."""
        from render.run import _clean_render_assets
        return _clean_render_assets(label)

    async def run_render_bot(self) -> dict:
        """Render video with Remotion and upload to Google Drive."""
        from render.run import run as _step_run
        return await _step_run(self)

    async def run_audio_sync(self, audio_path: str = None, scene_list: list = None) -> dict:
        """Calculate per-image durations by matching Sentence Text to audio."""
        from render.run_audio_sync import run as _step_run
        return await _step_run(self, audio_path, scene_list)

    async def run_youtube_upload_bot(self) -> dict:
        """REMOVED (C34a, S10-1 audit finding). The implementation this called
        (skills/video-pipeline/upload/run.py, seo_generator.py,
        youtube_uploader.py) is deleted — it hardcoded @Power_Doctrine SEO
        onto whatever idea was current and uploaded through the shared VPS
        OAuth token files onto Ryan's own YouTube channel, bypassing
        StoryEngine's per-tenant upload path and its quota guard entirely.
        Operator confirmed (2026-07-19) this cron pipeline's Slack channel
        and Power Doctrine branding are retired. Kept as a soft-fail stub
        (not deleted outright) only because orchestrator/pipeline_control.py's
        Slack `upload` command still calls it — this way that command gets a
        clear error instead of an AttributeError/ImportError crash.
        """
        return {
            "status": "failed",
            "bot": "YouTube Upload Bot",
            "error": "YouTube upload bot removed (C34a) — the Power Doctrine "
                     "cron upload path is retired. Use StoryEngine's "
                     "per-tenant YouTube upload instead.",
        }

    async def package_for_remotion(self) -> dict:
        """Package all assets for Remotion video editing."""
        from upload.run_package import run as _step_run
        return await _step_run(self)

    async def regenerate_images(self, scene_list: list[int] = None, image_indices: list[tuple[int, int]] = None) -> dict:
        """Regenerate specific missing images for the current video."""
        from render.run import run as _step_run
        return await _step_run(self, scene_list, image_indices)


async def main():
    """CLI entry point - runs the next available step."""
    import sys

    # --channel <slug> selects the tenant; default resolves to economy_fastforward.
    channel = None
    if "--channel" in sys.argv:
        _i = sys.argv.index("--channel")
        if _i + 1 < len(sys.argv):
            channel = sys.argv[_i + 1]
            del sys.argv[_i:_i + 2]
    pipeline = VideoPipeline(channel=channel)

    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h"]:
        print("=" * 60)
        print("VIDEO PIPELINE - CLI Options")
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
        print("  --translate       Run brief translator (research brief -> script + scenes)")
        print("  --styled-prompts  Run image prompt engine with visual identity system")
        print('  --full "..."      Full pipeline: Idea -> Script -> Voice -> Images -> Render')
        print("  --produce [id]    Produce pipeline from a queued idea to completion")
        print("  --from-stage X    Resume pipeline from a specific stage")
        print("  --remotion        Export Remotion props for rendering")
        print('  --regenerate      Regenerate missing images (fixes render failures)')
        print("  --render          Render only - skip other stages, process one at a time")
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
        print("AIRTABLE IDEAS STATUS")
        print("=" * 60)
        ideas = pipeline.airtable.get_all_ideas()
        for idea in ideas:
            print(f"  {idea.get(IdeaFields.STATUS, 'Unknown'):20} | {idea.get(IdeaFields.VIDEO_TITLE, 'Untitled')[:40]}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--idea":
        # Generate ideas from URL or concept
        if len(sys.argv) < 3:
            print("=" * 60)
            print("IDEA BOT - Generate Video Concepts")
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
        from research.agent import run_research

        if len(sys.argv) < 3:
            print("=" * 60)
            print("RESEARCH AGENT - Deep Topic Research")
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
        print(f"\nRESEARCH AGENT: Researching '{topic}'...")
        payload = await run_research(
            anthropic_client=pipeline.anthropic,
            topic=topic,
            airtable_client=pipeline.airtable,
        )

        print(f"\nResearch complete!")
        print(f"   Headline: {payload.get('headline', 'N/A')}")
        print(f"   Record ID: {payload.get('_airtable_record_id', 'N/A')}")
        print(f"   Fields: {len(payload)}")
        print(f"\nNext: Review in Airtable and set status to 'Ready For Scripting'")
        return

    # === MORE IDEAS FROM FORMAT LIBRARY ===
    if len(sys.argv) > 1 and sys.argv[1] == "--more-ideas":
        import os as os_mod
        from title_idea.idea_modeling import generate_modeled_ideas

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
        from shared.clients.anthropic_client import AnthropicClient as _AnthropicClient
        from shared.clients.airtable_client import AirtableClient as _AirtableClient

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
                    print(f"    Saved idea {i}: {record.get('id')}")
                except Exception as e:
                    print(f"    Failed to save idea {i}: {e}")

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
        from title_idea.competitor_scraper import CompetitorScraper

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

    # === DISCOVERY SCANNER (News + Competitors) ===
    if len(sys.argv) > 1 and sys.argv[1] == "--discover":
        from discovery.scanner import run_discovery, format_ideas_for_slack, build_option_map, build_idea_record_from_discovery
        from discovery_tracker import save_discovery_message

        focus = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else None
        focus_msg = f" (focus: {focus})" if focus else ""

        print("=" * 60)
        print(f"DISCOVERY SCANNER - Headlines + Competitors{focus_msg}")
        print("=" * 60)

        try:
            result = await run_discovery(
                anthropic_client=pipeline.anthropic,
                apify_client=pipeline.apify,
                airtable_client=pipeline.airtable,
                focus=focus,
                include_competitors=True,
            )
        except Exception as e:
            error_msg = f"Discovery scanner crashed: {e}"
            print(f"\n{error_msg}")
            try:
                pipeline.slack.send_message(
                    f"*9 AM Discovery Scan FAILED*\n"
                    f"```{error_msg}```\n"
                    f"No ideas were generated. Run `discover` manually to retry."
                )
            except Exception:
                pass
            return

        news_ideas = result.get("ideas", [])
        competitor_ideas = result.get("competitor_ideas", [])
        all_ideas = news_ideas + competitor_ideas

        if not all_ideas:
            print("\nNo ideas found. Try with a different focus keyword.")
            try:
                pipeline.slack.send_message(
                    "*Daily Discovery Scan* ran at 9 AM but found no strong ideas today.\n"
                    "Try running `discover [focus]` manually with a specific topic."
                )
            except Exception:
                pass
            return

        # Print summary
        print(f"\nFound {len(news_ideas)} news ideas + {len(competitor_ideas)} competitor ideas:\n")

        if news_ideas:
            print("NEWS IDEAS:")
            for i, idea in enumerate(news_ideas, 1):
                title_opts = idea.get("title_options", [])
                title = title_opts[0]["title"] if title_opts else "Untitled"
                appeal = idea.get("estimated_appeal", "?")
                print(f"  {i}. {title} (appeal: {appeal}/10)")

        if competitor_ideas:
            print("\nCOMPETITOR IDEAS:")
            for i, idea in enumerate(competitor_ideas, 1):
                title_opts = idea.get("title_options", [])
                title = title_opts[0]["title"] if title_opts else "Untitled"
                comp_title = idea.get("competitor_title", "?")[:50]
                comp_vph = idea.get("competitor_vph", 0)
                print(f"  {i}. {title}")
                print(f"     From: \"{comp_title}...\" ({comp_vph:.0f} VPH)")

        # Save ALL ideas to Airtable (both news and competitor)
        print("\nSaving to Airtable (Idea Concepts)...")
        saved_record_ids = []

        # Save news ideas
        for i, idea in enumerate(news_ideas, 1):
            idea_data = build_idea_record_from_discovery(idea, idea_number=i, source_type="news")
            title = idea_data.get("viral_title", "Untitled")
            try:
                record = pipeline.airtable.create_idea(idea_data, source="discovery_scanner")
                saved_record_ids.append({"id": record.get("id"), "type": "news"})
                print(f"  [News {i}] {record.get('id')} - {title}")
            except Exception as e:
                saved_record_ids.append(None)
                print(f"  [News {i}] Failed: {e}")

        # Save competitor ideas
        for i, idea in enumerate(competitor_ideas, 1):
            idea_data = build_idea_record_from_discovery(idea, idea_number=i, source_type="competitor")
            title = idea_data.get("viral_title", "Untitled")
            try:
                record = pipeline.airtable.create_idea(idea_data, source="competitor_scanner")
                saved_record_ids.append({"id": record.get("id"), "type": "competitor"})
                print(f"  [Competitor {i}] {record.get('id')} - {title}")
            except Exception as e:
                saved_record_ids.append(None)
                print(f"  [Competitor {i}] Failed: {e}")

        # Post interactive Slack message with letter emoji reactions
        production_channel = SlackClient.DEFAULT_CHANNEL_ID
        try:
            slack_msg = (
                "*Good Morning! Daily Discovery Scan Complete*\n"
                "Type a number (1-9) or letter (a-t) to approve an idea - "
                "I'll auto-research it and queue it for the 12 PM pipeline run.\n\n"
            )
            slack_msg += format_ideas_for_slack(result)

            response = pipeline.slack.send_message(slack_msg, production_channel)
            msg_ts = response["ts"]

            # Build option map: one letter per title option (news + competitor)
            option_map = build_option_map(result)

            # Regional indicator letters A-T for emoji reactions
            letter_emojis = [
                "regional_indicator_a", "regional_indicator_b", "regional_indicator_c",
                "regional_indicator_d", "regional_indicator_e", "regional_indicator_f",
                "regional_indicator_g", "regional_indicator_h", "regional_indicator_i",
                "regional_indicator_j", "regional_indicator_k", "regional_indicator_l",
                "regional_indicator_m", "regional_indicator_n", "regional_indicator_o",
                "regional_indicator_p", "regional_indicator_q", "regional_indicator_r",
                "regional_indicator_s", "regional_indicator_t",
            ]
            emojis_to_add = letter_emojis[:len(option_map)]

            for emoji in emojis_to_add:
                try:
                    pipeline.slack.add_reaction(emoji, msg_ts, production_channel)
                except Exception as e:
                    print(f"  Failed to add reaction {emoji}: {e}")

            # Persist tracking data for the Slack bot to handle reactions
            save_discovery_message(msg_ts, all_ideas, [r.get("id") if r else None for r in saved_record_ids])
            print(f"\nInteractive Slack message posted (ts={msg_ts})")
            print(f"   {len(option_map)} options with letter reactions - waiting for your choice!")

        except Exception as e:
            print(f"\nSlack notification FAILED: {e}")
            try:
                short_msg = f"*Discovery Scan Complete* - {len(news_ideas)} news + {len(competitor_ideas)} competitor ideas saved to Airtable.\n"
                short_msg += "\nCheck Airtable to approve."
                pipeline.slack.send_message(short_msg, production_channel)
                print("   Sent short fallback message to Slack")
            except Exception as e2:
                print(f"   Fallback also failed: {e2}")
                print("   Ideas were saved to Airtable - check there manually.")

        return

    if len(sys.argv) > 1 and sys.argv[1] == "--remotion":
        # Export Remotion props for a specific video
        from pathlib import Path

        # Get title from args or use default
        if len(sys.argv) > 2:
            title = " ".join(sys.argv[2:])
        else:
            title = "The 2030 Currency Collapse: Which Assets Will YOU Still Own?"

        print(f"\nREMOTION EXPORT: Packaging '{title}'...")

        # Load the idea to set video_title
        ideas = pipeline.airtable.get_all_ideas()
        for idea in ideas:
            if idea.get(IdeaFields.VIDEO_TITLE) == title:
                pipeline._load_idea(idea)
                break

        if not pipeline.video_title:
            print(f"Error: Could not find video '{title}'")
            return

        remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"

        # Package props
        props = await pipeline.package_for_remotion()

        # Write to JSON file in remotion folder
        output_path = remotion_dir / "props.json"
        with open(output_path, "w") as f:
            json.dump(props, f, indent=2)

        print(f"\nRemotion export complete!")
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
        print("REGENERATE IMAGES")
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
            if idea.get(IdeaFields.VIDEO_TITLE) == title:
                pipeline._load_idea(idea)
                break

        if not pipeline.video_title:
            print(f"Error: Could not find video '{title}'")
            return

        result = await pipeline.regenerate_images(scene_list=scene_list, image_indices=image_indices)
        print(f"\nRegeneration complete: {result.get('regenerated', 0)} images")
        return

    # === BRIEF TRANSLATOR ===
    if len(sys.argv) > 1 and sys.argv[1] == "--translate":
        # Run brief translator on the current idea
        print("=" * 60)
        print("BRIEF TRANSLATOR - Research Brief -> Script + Scenes")
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
        print("RENDER MODE - Render Only (skips other stages)")
        print("=" * 60)

        ideas = pipeline.airtable.get_ideas_by_status(
            pipeline.STATUS_READY_TO_RENDER, limit=10
        )

        if not ideas:
            print("\nNo ideas with status 'Ready To Render'")
            return

        print(f"\nFound {len(ideas)} video(s) to render:")
        for i, idea in enumerate(ideas, 1):
            print(f"   {i}. {idea.get(IdeaFields.VIDEO_TITLE, 'Untitled')}")

        rendered = 0
        for i, idea in enumerate(ideas, 1):
            title = idea.get(IdeaFields.VIDEO_TITLE, "Untitled")
            print(f"\n{'=' * 60}")
            print(f"RENDERING {i}/{len(ideas)}: {title}")
            print(f"{'=' * 60}")

            pipeline._load_idea(idea)
            result = await pipeline._run_step_safe("Render Bot", pipeline.run_render_bot)

            if result.get("status") == "failed" or result.get("error"):
                print(f"\nRender failed for '{title}': {result.get('error')}")
                print(f"   Stopping - fix this video before rendering the rest.")
                break

            rendered += 1
            print(f"\n'{title}' rendered and uploaded!")
            print(f"   {result.get('video_url', 'N/A')}")

        print(f"\n{'=' * 60}")
        print(f"RENDER COMPLETE: {rendered}/{len(ideas)} video(s) rendered")
        print("=" * 60)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--run-queue":
        # Process ALL videos in pipeline until nothing left to do
        print("=" * 60)
        print("PIPELINE QUEUE MODE - Processing All Stages To Render")
        print("=" * 60)

        # PRE-FLIGHT: Process any ideas stuck at "Approved" status
        print("\nPre-flight: Checking for ideas needing research...")
        try:
            from orchestrator.approval_watcher import ApprovalWatcher
            watcher = ApprovalWatcher(
                anthropic_client=pipeline.anthropic,
                airtable_client=pipeline.airtable,
                slack_client=pipeline.slack,
            )
            approved_results = await watcher.check_and_process()
            if approved_results:
                print(f"  Researched {len(approved_results)} approved idea(s)")
                for r in approved_results:
                    print(f"     -> {r.get('headline', 'N/A')}")
            else:
                print("  No pending approvals found")
        except Exception as e:
            print(f"  Approval pre-flight failed: {e}")

        print("\nScanning all tables for work. Processing stages:")
        print("  Script -> Voice -> Image Prompts -> Images -> Thumbnail -> Render -> YouTube Upload")
        print("  Videos at 'Idea Logged' are SKIPPED (awaiting your approval)\n")

        # Notify Slack that the daily pipeline run has started
        try:
            now_pacific = datetime.now(ZoneInfo("America/Los_Angeles"))
            time_str = now_pacific.strftime("%-I:%M %p PT")

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
                    titles = [i.get(IdeaFields.VIDEO_TITLE, "Untitled")[:40] for i in ideas_at_status]
                    status_summary.append(f"  *{status_name}*: {', '.join(titles)}")

            if status_summary:
                pipeline.slack.send_message(
                    f"*{time_str} Pipeline Run Starting*\n"
                    "Scanning all tables and processing every stage through to YouTube upload.\n\n"
                    "*Work found:*\n" + "\n".join(status_summary)
                )
            else:
                pipeline.slack.send_message(
                    f"*{time_str} Pipeline Run Starting*\n"
                    "Scanning tables... no videos currently queued for processing."
                )
        except Exception:
            pass

        processed = 0
        steps_log = []
        max_iterations = 100

        while processed < max_iterations:
            try:
                result = await pipeline.run_next_step()
            except Exception as e:
                error_msg = f"Pipeline crashed: {e}"
                print(f"\n{error_msg}")
                try:
                    pipeline.slack.send_message(f"*Pipeline STOPPED* after {processed} steps\n```{error_msg}```")
                except Exception:
                    pass
                break

            if result.get("status") == "idle":
                print("\nQueue empty! All approved videos processed.")
                try:
                    if processed > 0:
                        summary_lines = "\n".join(f"  {s}" for s in steps_log[-10:])
                        pipeline.slack.send_message(
                            f"*Pipeline queue complete!* {processed} steps processed.\n\n"
                            f"*Steps completed:*\n{summary_lines}\n\n"
                            f"All videos have been processed through to their next stage."
                        )
                    else:
                        pipeline.slack.send_message(
                            "*Pipeline queue complete* - nothing to process. "
                            "All videos are either at Idea Logged (awaiting approval) or already Done."
                        )
                except Exception:
                    pass
                break

            if result.get("status") == "failed" or result.get("error"):
                error_msg = result.get("error", "Unknown error")
                bot_name = result.get("bot", "Unknown")
                video_title = result.get("video_title", "Unknown")
                print(f"\nPIPELINE STOPPED - {bot_name} failed for '{video_title}'")
                print(f"   Error: {error_msg}")
                print(f"   Steps completed before failure: {processed}")
                print(f"\n   Fix the issue and run again. Status was NOT advanced.")
                try:
                    pipeline.slack.send_message(
                        f"*Pipeline STOPPED* - {bot_name} failed\n"
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
            steps_log.append(f"{bot_name}: _{video_title}_ -> {new_status}")

            print(f"\n--- Completed step {processed} ---")
            print(f"    Video: {video_title}")
            print(f"    Bot: {bot_name}")
            print(f"    New Status: {new_status}")

            # Small delay between steps to avoid rate limits
            await asyncio.sleep(2)

        print("\n" + "=" * 60)
        print(f"QUEUE COMPLETE: {processed} steps processed")
        print("=" * 60)
        return

    print("=" * 60)
    print("VIDEO PIPELINE - Running Next Step")
    print("=" * 60)

    result = await pipeline.run_next_step()

    print("\n" + "=" * 60)
    print("RESULT:")
    for key, value in result.items():
        print(f"   {key}: {value}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
