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
        print(f"\n📌 Loaded idea: {self.video_title}")
        print(f"   Status: {idea.get('Status')}")
        print(f"   ID: {self.current_idea_id}")

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
    
    async def run_next_step(self) -> dict:
        """Run the next step based on what's in the Ideas table.
        
        This is the MAIN entry point. It checks which video needs processing
        and runs the appropriate bot.
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
                
            return await self.run_script_bot()
        
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
                
            return await self.run_voice_bot()
        
        # 3. Check for Ready For Image Prompts
        idea = self.get_idea_by_status(self.STATUS_READY_IMAGE_PROMPTS)
        if idea:
            self._load_idea(idea)
            return await self.run_image_prompt_bot()

        # 4. Check for Ready For Images
        idea = self.get_idea_by_status(self.STATUS_READY_IMAGES)
        if idea:
            self._load_idea(idea)
            return await self.run_image_bot()

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
            return await self.run_thumbnail_bot()
        
        # 8. Check for Ready To Render
        idea = self.get_idea_by_status(self.STATUS_READY_TO_RENDER)
        if idea:
            self._load_idea(idea)
            return await self.run_render_bot()
        
        # No work to do
        print("\n✅ No videos ready for processing!")
        print("   To process a video, update its status in the Ideas table.")
        return {"status": "idle", "message": "No videos to process"}

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
        """Write the full 20-scene script.
        
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
        
        # Create Google Doc for script
        doc = self.google.create_document(self.video_title, self.project_folder_id)
        self.google_doc_id = doc["id"]
        
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
        
        return {
            "bot": "Script Bot",
            "video_title": self.video_title,
            "folder_id": self.project_folder_id,
            "doc_id": self.google_doc_id,
            "doc_url": doc_url,
            "scene_count": len(scenes),
            "new_status": self.STATUS_READY_VOICE,
        }
    
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

    async def run_image_prompt_bot(self) -> dict:
        """Generate image prompts based on voiceover duration.

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
            concepts = await self.anthropic.segment_scene_into_concepts(
                scene_text=scene_text,
                target_count=target_images,
                min_count=min_images,
                max_count=max_images,
                words_per_segment=words_per_segment
            )

            # Create records with calculated durations (capped at 6-10s range)
            cumulative_start = 0.0
            for i, concept in enumerate(concepts):
                concept_text = concept.get("text", "")
                concept_words = len(concept_text.split())
                concept_duration = concept_words / words_per_second if words_per_second > 0 else 8.0

                # ENFORCE 6-10s range - cap at 10s max, floor at 6s min
                concept_duration = max(6.0, min(10.0, concept_duration))

                self.airtable.create_sentence_image_record(
                    scene_number=scene_number,
                    sentence_index=i + 1,
                    sentence_text=concept_text,
                    duration_seconds=round(concept_duration, 1),
                    image_prompt=concept.get("image_prompt", ""),
                    video_title=self.video_title,
                    cumulative_start=round(cumulative_start, 1),
                    aspect_ratio="16:9"
                )
                cumulative_start += concept_duration
                total_prompts += 1

            print(f"    ✅ Created {len(concepts)} prompts for scene {scene_number}")

        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_IMAGES)

        print(f"\n  ✅ Total: {total_prompts} image prompts created")

        return {
            "bot": "Image Prompt Bot",
            "video_title": self.video_title,
            "prompt_count": total_prompts,
            "new_status": self.STATUS_READY_IMAGES
        }

    async def run_image_bot(self) -> dict:
        """Generate images from prompts.

        REQUIRES: Ideas status = "Ready For Images"
        UPDATES TO: "Ready For Video Scripts" when complete
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

        # UPDATE STATUS to Ready For Video Scripts
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_THUMBNAIL)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VIDEO_SCRIPTS}")

        return {
            "bot": "Image Bot",
            "video_title": self.video_title,
            "image_count": result.get("image_count", 0),
            "new_status": self.STATUS_READY_VIDEO_SCRIPTS,
        }

    async def run_visuals_pipeline(self) -> dict:
        """Generate image prompts AND images for all scenes (combined pipeline).

        REQUIRES: Ideas status = "Ready For Image Prompts"
        UPDATES TO: "Ready For Video Scripts" when complete

        Note: This is a combined pipeline. For granular control, use
        run_image_prompt_bot() and run_image_bot() separately.
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
        
        # Step 1: Generate Image Prompts (uses new duration-based logic)
        prompt_result = await self.run_image_prompt_bot()

        # Step 2: Generate Images
        image_result = await self._run_image_bot()
        
        # UPDATE STATUS to Ready For Video Scripts
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_THUMBNAIL)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VIDEO_SCRIPTS}")
        
        return {
            "bot": "Visuals Pipeline",
            "video_title": self.video_title,
            "prompt_count": prompt_result.get("prompt_count", 0),
            "image_count": image_result.get("image_count", 0),
            "new_status": self.STATUS_READY_VIDEO_SCRIPTS,
        }
    
    async def _run_image_bot(self) -> dict:
        """Generate images from prompts (internal method).

        Processes images in PARALLEL per scene for faster generation.
        """
        self.slack.notify_images_start()
        print(f"\n  🖼️ IMAGE BOT: Generating images...")

        # Get pending images for this video
        pending_images = self.airtable.get_pending_images_for_video(self.video_title)

        # Group images by scene for parallel processing
        scenes = {}
        for img in pending_images:
            scene_num = img.get("Scene", 0)
            if scene_num not in scenes:
                scenes[scene_num] = []
            scenes[scene_num].append(img)

        image_count = 0

        for scene_num in sorted(scenes.keys()):
            scene_images = scenes[scene_num]
            print(f"    Scene {scene_num}: Generating {len(scene_images)} images in parallel...")

            # Generate all images for this scene in parallel
            async def generate_single(img_record):
                prompt = img_record.get("Image Prompt", "")
                aspect_ratio = img_record.get("Aspect Ratio", "16:9")
                index = img_record.get("Image Index", 0)

                image_urls = await self.image_client.generate_and_wait(prompt, aspect_ratio)
                return (img_record, image_urls, index)

            # Launch all generations concurrently
            results = await asyncio.gather(*[generate_single(img) for img in scene_images])

            # Process results and upload to Drive
            for img_record, image_urls, index in results:
                if image_urls:
                    # Download image
                    image_content = await self.image_client.download_image(image_urls[0])

                    # Upload to Google Drive
                    filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                    drive_file = self.google.upload_image(image_content, filename, self.project_folder_id)
                    drive_url = self.google.make_file_public(drive_file["id"])

                    # Update Airtable
                    self.airtable.update_image_record(img_record["id"], image_urls[0], drive_url=drive_url)
                    image_count += 1
                    print(f"      ✅ Scene {scene_num}, Image {index} → Drive")

            print(f"    ✅ Scene {scene_num} complete ({len([r for r in results if r[1]])} images)")

        self.slack.notify_images_done()
        print(f"    ✅ Generated {image_count} total images")

        return {"image_count": image_count}

    async def run_video_script_bot(self) -> dict:
        """Generate video prompts for Scene 1 only (Constraint)."""
        print(f"\n  📝 VIDEO SCRIPT BOT: Generating prompts for Scene 1...")
        
        # Get pending images
        existing_images = self.airtable.get_all_images_for_video(self.video_title)
        done_images = [img for img in existing_images if img.get("Status") == "Done"]
        
        prompt_count = 0
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

            # Get sentence text for better motion alignment
            sentence_text = img_record.get("Sentence Text", "")

            print(f"    Generating motion prompt for Scene {scene}...")
            motion_prompt = await self.anthropic.generate_video_prompt(
                image_prompt=image_prompt,
                sentence_text=sentence_text,
            )
            
            self.airtable.update_image_video_prompt(img_record["id"], motion_prompt)
            prompt_count += 1
            
        print(f"    ✅ Generated {prompt_count} video prompts")
        
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
            
            image_url = drive_url  # Use Drive URL for generation
                
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
    
    async def run_thumbnail_bot(self) -> dict:
        """Generate thumbnail for the video.
        
        REQUIRES: Ideas status = "Ready For Thumbnail"
        UPDATES TO: "Done" when complete
        """
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
        reference_url = self.current_idea.get("Video URL")  # YouTube video URL
        basic_prompt = self.current_idea.get("Thumbnail Prompt", "")

        # Extract YouTube thumbnail URL from video URL
        thumbnail_image_url = None
        if reference_url:
            thumbnail_image_url = self._extract_youtube_thumbnail(reference_url)
            if thumbnail_image_url:
                print(f"  Extracted thumbnail: {thumbnail_image_url}")
            else:
                print(f"  ⚠️ Could not extract thumbnail from: {reference_url}")

        # Two-stage generation if thumbnail image AND Gemini is available
        if thumbnail_image_url and self.gemini.api_key:
            print(f"  Analyzing reference thumbnail via Gemini...")
            thumbnail_spec = await self.gemini.generate_thumbnail_spec(
                reference_image_url=thumbnail_image_url,
                video_title=video_title,
                video_summary=video_summary,
            )

            print(f"  Generating detailed prompt via Anthropic...")
            thumbnail_prompt = await self.anthropic.generate_thumbnail_prompt(
                thumbnail_spec_json=thumbnail_spec,
                video_title=video_title,
                thumbnail_concept=basic_prompt,
            )
            print(f"  Generated prompt: {thumbnail_prompt[:100]}...")

            # Save enhanced prompt to Airtable for debugging
            self.airtable.update_idea_field(self.current_idea_id, "Thumbnail Prompt", thumbnail_prompt)
            print(f"  ✅ Enhanced prompt saved to Airtable")
        else:
            if thumbnail_image_url and not self.gemini.api_key:
                print(f"  ⚠️ Gemini API key missing, skipping reference analysis.")
            print(f"  Using basic prompt.")
            thumbnail_prompt = basic_prompt

        if not thumbnail_prompt:
             print("  ⚠️ No thumbnail prompt found!")
             return {"error": "No thumbnail prompt"}

        # Generate thumbnail image (use Pro model for higher quality)
        image_urls = await self.image_client.generate_and_wait(
            thumbnail_prompt, "16:9", model="nano-banana-pro"
        )
        if not image_urls:
             print("  ⚠️ Failed to generate thumbnail.")
             return {"error": "Thumbnail generation failed"}
            
        print(f"  ✅ Thumbnail generated: {image_urls[0][:50]}...")
        
        # Upload to Google Drive
        if self.project_folder_id:
            parent_id = self.project_folder_id
        else:
            # Try to find folder
            folder = self.google.search_folder(self.video_title)
            if folder:
                parent_id = folder["id"]
            else:
                print("  ⚠️ Project folder not found, uploading to root.")
                parent_id = None
                
        print("  Uploading to Google Drive...")
        google_file = self.google.upload_file_from_url(
            url=image_urls[0],
            name="Thumbnail.png",
            parent_id=parent_id
        )
        drive_link = google_file.get("webViewLink")
        print(f"  ✅ Uploaded to Drive: {drive_link}")

        # Save to Airtable - use the original image URL (Airtable will download and host it)
        # Don't use drive_link as that's an HTML page, not a direct image
        self.airtable.update_idea_thumbnail(self.current_idea_id, image_urls[0])
        print("  ✅ Saved to Airtable")
        
        # UPDATE STATUS to Done
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_TO_RENDER)
        print(f"  ✅ Status updated to: {self.STATUS_READY_TO_RENDER}")
        
        return {
            "bot": "Thumbnail Bot",
            "video_title": self.video_title,
            "new_status": self.STATUS_READY_TO_RENDER,
            "thumbnail_url": drive_link
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

        # Get project folder
        folder = self.google.get_or_create_folder(self.video_title)
        folder_id = folder["id"]

        # Export props
        props = await self.package_for_remotion()

        remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"
        props_file = remotion_dir / "props.json"
        public_dir = remotion_dir / "public"
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
        
        # Sanitize filename
        def sanitize(title):
            clean = re.sub(r'[^\w\s-]', '', title)
            return re.sub(r'[-\s]+', '_', clean)[:50]
        
        safe_name = sanitize(self.video_title)
        output_file = remotion_dir / "out" / f"{safe_name}.mp4"
        output_file.parent.mkdir(exist_ok=True)
        
        # Render
        print(f"  🎥 Rendering video (this may take 30-60 minutes)...")
        render_cmd = [
            "npx", "remotion", "render",
            "Main", str(output_file),
            "--props", str(props_file)
        ]
        
        result = subprocess.run(render_cmd, cwd=remotion_dir)
        
        if result.returncode != 0:
            print(f"  ❌ Render failed")
            return {"error": "Render failed", "bot": "Render Bot"}
        
        if not output_file.exists():
            print(f"  ❌ Output not found")
            return {"error": "Output file missing", "bot": "Render Bot"}
        
        print(f"  ✅ Rendered: {output_file}")
        
        # Upload to Drive
        print("  ☁️ Uploading to Google Drive...")
        with open(output_file, "rb") as f:
            video_content = f.read()
        
        drive_file = self.google.upload_video(video_content, f"{safe_name}.mp4", folder_id)
        drive_url = f"https://drive.google.com/file/d/{drive_file['id']}/view"
        
        # Update Airtable
        self.airtable.update_idea_field(self.current_idea_id, "Final Video", drive_url)
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_DONE)
        
        print(f"  ✅ Status updated to: {self.STATUS_DONE}")
        print(f"  🔗 Video: {drive_url}")
        
        self.slack.send_message(f"🎬 Video rendered and uploaded!\n*{self.video_title}*\n{drive_url}")
        
        return {
            "bot": "Render Bot",
            "video_title": self.video_title,
            "new_status": self.STATUS_DONE,
            "video_url": drive_url
        }
    
    async def package_for_remotion(self) -> dict:
        """Package all assets for Remotion video editing.

        Includes segment data (text + duration) for word-synced image display.
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

            scenes.append({
                "sceneNumber": scene_number,
                "text": script.get("Scene text", ""),
                "voiceUrl": script.get("Voice Over", [{}])[0].get("url", "") if script.get("Voice Over") else "",
                "images": [
                    {
                        "index": img.get("Image Index", 0),
                        # Use permanent Drive URL instead of expiring Airtable attachment
                        "url": img.get("Drive Image URL") or (img.get("Image", [{}])[0].get("url", "") if img.get("Image") else ""),
                        # Include segment data for word-synced image display
                        "segmentText": img.get("Sentence Text", ""),
                        "duration": img.get("Duration (s)", 8.0),
                    }
                    for img in sorted_images
                ],
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
                aspect_ratio = img_record.get("Aspect Ratio", "16:9")
                index = img_record.get("Image Index", 0)

                if not prompt:
                    return (img_record, None, index, "No prompt")

                try:
                    image_urls = await self.image_client.generate_and_wait(prompt, aspect_ratio)
                    return (img_record, image_urls, index, None)
                except Exception as e:
                    return (img_record, None, index, str(e))

            # Generate in parallel
            results = await asyncio.gather(*[generate_single(img) for img in scene_images])

            # Upload to Drive and update Airtable
            for img_record, image_urls, index, error in results:
                if error:
                    print(f"    ❌ Scene {scene_num}, Image {index}: {error}")
                    continue

                if image_urls:
                    # Download image
                    image_content = await self.image_client.download_image(image_urls[0])

                    # Upload to Google Drive
                    filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                    drive_file = self.google.upload_image(image_content, filename, self.project_folder_id)
                    drive_url = self.google.make_file_public(drive_file["id"])

                    # Update Airtable
                    self.airtable.update_image_record(img_record["id"], image_urls[0], drive_url=drive_url)
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
        print("  (no args)     Run the next pipeline step based on Airtable status")
        print("  --status      Show status of all ideas in Airtable")
        print('  --idea "..."  Generate 3 video ideas from URL or concept')
        print("  --trending    Generate ideas from trending YouTube videos (Apify)")
        print("  --sync        Sync assets to Google Drive")
        print("  --remotion    Export Remotion props for rendering")
        print('  --regenerate  Regenerate missing images (fixes render failures)')
        print("  --run-queue   Process all videos until queue is empty")
        print("  --help, -h    Show this help message")
        print("\nExamples:")
        print("  python pipeline.py")
        print("  python pipeline.py --status")
        print('  python pipeline.py --idea "https://youtu.be/VIDEO_ID"')
        print('  python pipeline.py --idea "Breaking news about AI regulation"')
        print("  python pipeline.py --trending")
        print('  python pipeline.py --trending "crypto crash,bitcoin ETF"')
        print('  python pipeline.py --regenerate "Video Title" --images 3:4,4:7')
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

    if len(sys.argv) > 1 and sys.argv[1] == "--more-ideas":
        # Generate more ideas from recent trending data (quick refresh)
        print("=" * 60)
        print("💡 MORE IDEAS - Quick Generation from Recent Trends")
        print("=" * 60)
        
        num = 3  # default
        if len(sys.argv) > 2:
            try:
                num = int(sys.argv[2])
            except ValueError:
                pass
        
        result = await pipeline.run_trending_idea_bot(
            search_queries=None,  # Use defaults
            num_ideas=num,
        )
        
        print(f"\n✅ Generated {len(result.get('ideas', []))} new ideas")
        print("Check Airtable or Slack for the new ideas.")
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

    if len(sys.argv) > 1 and sys.argv[1] == "--run-queue":
        # Process ALL videos in pipeline until nothing left to do
        # Respects Ryan's gate: only processes videos at "Ready For Scripting" or beyond
        print("=" * 60)
        print("🔄 PIPELINE QUEUE MODE - Processing Until Empty")
        print("=" * 60)
        print("\nThis will process all videos from 'Ready For Scripting' → 'Done'")
        print("Videos at 'Idea Logged' are SKIPPED (awaiting your approval)\n")
        
        processed = 0
        max_iterations = 100  # Safety limit
        
        while processed < max_iterations:
            result = await pipeline.run_next_step()
            
            if result.get("status") == "idle":
                print("\n✅ Queue empty! All approved videos processed.")
                break
            
            processed += 1
            print(f"\n--- Completed step {processed} ---")
            print(f"    Video: {result.get('video_title', 'Unknown')}")
            print(f"    Bot: {result.get('bot', 'Unknown')}")
            print(f"    New Status: {result.get('new_status', 'Unknown')}")
            
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
