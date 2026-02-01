"""
Video Production Pipeline Orchestrator

STATUS-DRIVEN WORKFLOW:
The pipeline strictly follows Airtable Ideas table status:
1. Idea Logged       - New idea, waiting to be picked up
2. Ready For Scripting - Script Bot will run
3. Ready For Voice   - Voice Bot will run  
4. Ready For Visuals - Image Prompt Bot + Image Bot will run
5. Ready For Thumbnail - Thumbnail Bot will run
6. Done              - Complete, do NOT process
7. In Que            - Waiting in queue

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


class VideoPipeline:
    """Orchestrates the full video production pipeline based on Airtable status."""
    
    # Valid statuses in workflow order
    STATUS_IDEA_LOGGED = "Idea Logged"
    STATUS_READY_SCRIPTING = "Ready For Scripting"
    STATUS_READY_VOICE = "Ready For Voice"
    STATUS_READY_VISUALS = "Ready For Visuals"
    STATUS_READY_VIDEO_SCRIPTS = "Ready For Video Scripts"
    STATUS_READY_VIDEO_GENERATION = "Ready For Video Generation"
    STATUS_READY_THUMBNAIL = "Ready For Thumbnail"
    STATUS_DONE = "Done"
    STATUS_IN_QUE = "In Que"
    
    def __init__(self):
        """Initialize all API clients."""
        self.anthropic = AnthropicClient()
        self.airtable = AirtableClient()
        self.google = GoogleClient()
        self.slack = SlackClient()
        self.elevenlabs = ElevenLabsClient()
        # Pass google client for proxy logic
        self.image_client = ImageClient(google_client=self.google)
        
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
            # Scripts done, no images yet
            suggested_status = self.STATUS_READY_VISUALS
        elif pending_images:
            # Images exist but some pending
            suggested_status = self.STATUS_READY_VISUALS
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
        
        # 3. Check for Ready For Visuals
        idea = self.get_idea_by_status(self.STATUS_READY_VISUALS)
        if idea:
            self._load_idea(idea)
            return await self.run_visuals_pipeline()
            
        # 4. Check for Ready For Video Scripts
        idea = self.get_idea_by_status(self.STATUS_READY_VIDEO_SCRIPTS)
        if idea:
            self._load_idea(idea)
            return await self.run_video_script_bot()
            
        # 5. Check for Ready For Video Generation
        idea = self.get_idea_by_status(self.STATUS_READY_VIDEO_GENERATION)
        if idea:
            self._load_idea(idea)
            return await self.run_video_gen_bot()
        # 6. Check for Ready For Thumbnail
        idea = self.get_idea_by_status(self.STATUS_READY_THUMBNAIL)
        if idea:
            self._load_idea(idea)
            # No specific check needed here as it's the last step
            return await self.run_thumbnail_bot()
        
        # No work to do
        print("\n✅ No videos ready for processing!")
        print("   To process a video, update its status in the Ideas table.")
        return {"status": "idle", "message": "No videos to process"}
    
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
        UPDATES TO: "Ready For Visuals" when complete
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
        
        # UPDATE STATUS to Ready For Visuals
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_VISUALS)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VISUALS}")
        
        self.slack.notify_voice_done()
        
        return {
            "bot": "Voice Bot",
            "video_title": self.video_title,
            "voice_count": voice_count,
            "new_status": self.STATUS_READY_VISUALS,
        }
    


    async def run_visuals_pipeline(self) -> dict:
        """Generate image prompts AND images for all scenes.
        
        REQUIRES: Ideas status = "Ready For Visuals"
        UPDATES TO: "Ready For Video Scripts" when complete
        """
        # Verify status
        if not self.current_idea:
            idea = self.get_idea_by_status(self.STATUS_READY_VISUALS)
            if not idea:
                return {"error": "No idea with status 'Ready For Visuals'"}
            self._load_idea(idea)
        
        if self.current_idea.get("Status") != self.STATUS_READY_VISUALS:
            return {"error": f"Idea status is '{self.current_idea.get('Status')}', expected 'Ready For Visuals'"}
        
        print(f"\n🖼️ VISUALS PIPELINE: Processing '{self.video_title}'")
        
        # Get or create project folder
        if not self.project_folder_id:
            folder = self.google.get_or_create_folder(self.video_title)
            self.project_folder_id = folder["id"]
        
        # Step 1: Generate Image Prompts
        prompt_result = await self._run_image_prompt_bot()
        
        # Step 2: Generate Images
        image_result = await self._run_image_bot()
        
        # UPDATE STATUS to Ready For Video Scripts
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_READY_VIDEO_SCRIPTS)
        print(f"  ✅ Status updated to: {self.STATUS_READY_VIDEO_SCRIPTS}")
        
        return {
            "bot": "Visuals Pipeline",
            "video_title": self.video_title,
            "prompt_count": prompt_result.get("prompt_count", 0),
            "image_count": image_result.get("image_count", 0),
            "new_status": self.STATUS_READY_VIDEO_SCRIPTS,
        }
    
    async def _run_image_prompt_bot(self) -> dict:
        """Generate image prompts for all scenes (internal method)."""
        self.slack.notify_image_prompts_start()
        print(f"\n  🌉 IMAGE PROMPT BOT: Generating prompts...")
        
        # Get scripts for this video
        scripts = self.airtable.get_scripts_by_title(self.video_title)
        
        if not scripts:
            print(f"    No scripts found for: {self.video_title}")
            return {"prompt_count": 0}
        
        # Get existing image prompts to avoid duplicates
        existing_images = self.airtable.get_all_images_for_video(self.video_title)
        existing_scenes = set(img.get("Scene") for img in existing_images)
        
        prompt_count = 0
        for script in scripts:
            scene_number = script.get("scene", 0)
            
            # CHECK: Do prompts already exist?
            if scene_number in existing_scenes:
                print(f"    Check: Scene {scene_number} prompts already exist, skipping.")
                continue
                
            scene_text = script.get("Scene text", "")
            
            print(f"    Generating prompts for scene {scene_number}...")
            
            # Generate 6 image prompts
            prompts = await self.anthropic.generate_image_prompts(
                scene_number=scene_number,
                scene_text=scene_text,
                video_title=self.video_title,
            )
            
            # Save each prompt to Airtable
            for i, prompt in enumerate(prompts, 1):
                self.airtable.create_image_prompt_record(
                    scene_number=scene_number,
                    image_index=i,
                    image_prompt=prompt,
                    video_title=self.video_title,
                )
                prompt_count += 1
        
        self.slack.notify_image_prompts_done()
        print(f"    ✅ Created {prompt_count} image prompts")
        
        return {"prompt_count": prompt_count}
    
    async def _run_image_bot(self) -> dict:
        """Generate images from prompts (internal method)."""
        self.slack.notify_images_start()
        print(f"\n  🖼️ IMAGE BOT: Generating images...")
        
        # Get pending images for this video
        pending_images = self.airtable.get_pending_images_for_video(self.video_title)
        
        image_count = 0
        for img_record in pending_images:
            prompt = img_record.get("Image Prompt", "")
            aspect_ratio = img_record.get("Aspect Ratio", "16:9")
            scene = img_record.get("Scene", 0)
            index = img_record.get("Image Index", 0)
            
            print(f"    Generating image for scene {scene}, image {index}...")
            
            # Generate image
            image_urls = await self.image_client.generate_and_wait(prompt, aspect_ratio)
            
            if image_urls:
                # Download image
                image_content = await self.image_client.download_image(image_urls[0])
                
                # Upload to Google Drive
                filename = f"Scene_{str(scene).zfill(2)}_{str(index).zfill(2)}.png"
                self.google.upload_image(image_content, filename, self.project_folder_id)
                
                # Update Airtable
                self.airtable.update_image_record(img_record["id"], image_urls[0])
                image_count += 1
        
        self.slack.notify_images_done()
        print(f"    ✅ Generated {image_count} images")
        
        return {"image_count": image_count}

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

            print(f"    Generating motion prompt for Scene {scene}...")
            motion_prompt = await self.anthropic.generate_video_prompt(image_prompt)
            
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
            image_url_list = img_record.get("Image", [])
            image_url = image_url_list[0].get("url") if image_url_list else None
            motion_prompt = img_record.get("Video Prompt")
            
            if not image_url or not motion_prompt:
                continue
                
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
        
        thumbnail_prompt = self.current_idea.get("Thumbnail Prompt", "")
        print(f"  Thumbnail prompt: {thumbnail_prompt[:100]}...")
        
        if not thumbnail_prompt:
             print("  ⚠️ No thumbnail prompt found!")
             return {"error": "No thumbnail prompt"}

        # Generate thumbnail image
        image_urls = await self.image_client.generate_and_wait(thumbnail_prompt, "16:9")
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
        
        # Save to Airtable
        self.airtable.update_idea_thumbnail(self.current_idea_id, drive_link)
        print("  ✅ Saved to Airtable")
        
        # UPDATE STATUS to Done
        self.airtable.update_idea_status(self.current_idea_id, self.STATUS_DONE)
        print(f"  ✅ Status updated to: {self.STATUS_DONE}")
        
        return {
            "bot": "Thumbnail Bot",
            "video_title": self.video_title,
            "new_status": self.STATUS_DONE,
            "thumbnail_url": drive_link
        }
    
    async def package_for_remotion(self) -> dict:
        """Package all assets for Remotion video editing."""
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
            
            scenes.append({
                "sceneNumber": scene_number,
                "text": script.get("Scene text", ""),
                "voiceUrl": script.get("Voice Over", [{}])[0].get("url", "") if script.get("Voice Over") else "",
                "images": [
                    {
                        "index": img.get("Image Index", 0),
                        "url": img.get("Image", [{}])[0].get("url", "") if img.get("Image") else "",
                    }
                    for img in sorted(scene_images, key=lambda x: x.get("Image Index", 0))
                ],
            })
        
        props = {
            "videoTitle": self.video_title,
            "folderId": self.project_folder_id,
            "docId": self.google_doc_id,
            "scenes": scenes,
        }
        
        return props


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
    
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        # Show current status of all ideas
        print("=" * 60)
        print("📋 AIRTABLE IDEAS STATUS")
        print("=" * 60)
        ideas = pipeline.airtable.get_all_ideas()
        for idea in ideas:
            print(f"  {idea.get('Status', 'Unknown'):20} | {idea.get('Video Title', 'Untitled')[:40]}")
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
            
        props = await pipeline.package_for_remotion()
        
        # Write to JSON file in project folder
        output_path = f"/Users/ryanayler/Desktop/Economy Fastforward/remotion_props_{pipeline.video_title[:30].replace(' ', '_')}.json"
        with open(output_path, "w") as f:
            json.dump(props, f, indent=2)
        
        print(f"✅ Remotion props exported to: {output_path}")
        print(f"   Scenes: {len(props.get('scenes', []))}")
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
