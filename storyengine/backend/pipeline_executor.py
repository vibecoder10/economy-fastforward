"""Pipeline Executor - Wraps existing pipeline skills for StoryEngine.

This module bridges StoryEngine and the video production pipeline.
It imports the pipeline skills directly and executes them with proper
error handling, activity logging, and dual-writes to Supabase.

Usage:
    from pipeline_executor import PipelineExecutor

    executor = PipelineExecutor(tenant_id="...")
    result = await executor.run_research(video_id)
"""

import os
import sys
import asyncio
from datetime import datetime, timezone
from typing import Optional, Any
from pathlib import Path

# Add pipeline to path BEFORE any pipeline imports
PIPELINE_PATH = Path(__file__).parent.parent.parent / "skills" / "video-pipeline"
if str(PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PATH))

# Each bot folder has internal imports (e.g., script/run.py imports brief_translator).
# Add bot subdirectories to sys.path so these resolve correctly.
for bot_dir in ["script", "voice", "image_prompts", "images", "video_motion",
                "thumbnail", "render", "sound", "storyboard", "research",
                "upload", "analytics"]:
    bot_path = str(PIPELINE_PATH / bot_dir)
    if bot_path not in sys.path:
        sys.path.append(bot_path)

from database import fetch_one, execute
from status_map import to_supabase, to_pipeline, get_bot_name, STAGE_BOT_MAP, is_at_or_past_stage
from vault import get_secret


class PipelineExecutor:
    """Executes pipeline stages with StoryEngine integration.

    Wraps the existing pipeline skills and:
    - Loads API keys from Vault (fallback to .env)
    - Logs activity to bot_activity table
    - Updates video status in Supabase after each stage
    - Handles errors gracefully
    """

    def __init__(self, tenant_id: str):
        """Initialize the executor.

        Args:
            tenant_id: Supabase tenant ID for activity logging
        """
        self.tenant_id = tenant_id
        self._pipeline = None
        self._initialized = False

    async def _ensure_initialized(self):
        """Lazily initialize pipeline clients."""
        if self._initialized:
            return

        import sys
        print("[INIT] Starting pipeline initialization...", flush=True)

        # Load API keys from Vault into environment
        keys_to_load = [
            "anthropic_api_key",
            "airtable_api_key",
            "elevenlabs_api_key",
            "kie_ai_api_key",
            "openai_api_key",
            "gemini_api_key",
        ]

        for key_name in keys_to_load:
            print(f"[INIT] Loading key: {key_name}...", flush=True)
            try:
                value = await get_secret(key_name, self.tenant_id)
                if value:
                    env_name = key_name.upper()
                    os.environ[env_name] = value
                    print(f"[INIT]   ✓ {key_name} loaded", flush=True)
                else:
                    print(f"[INIT]   - {key_name} not found", flush=True)
            except Exception as e:
                print(f"[INIT]   ✗ {key_name} error: {e}", flush=True)

        # Create a lightweight pipeline object that only has what we need.
        # We can't import VideoPipeline directly because it imports ALL clients
        # (Slack, Google, ElevenLabs, etc.) which hang if services are unavailable.
        print("[INIT] Creating lightweight pipeline...", flush=True)

        from supabase_adapter import SupabaseAdapter
        from shared.clients.anthropic_client import AnthropicClient

        class LightPipeline:
            """Minimal pipeline that only has the clients we need."""
            pass

        self._pipeline = LightPipeline()
        self._pipeline.airtable = SupabaseAdapter(tenant_id=self.tenant_id)
        self._pipeline.anthropic = AnthropicClient()
        print("[INIT] SupabaseAdapter + AnthropicClient OK", flush=True)

        # Try to load optional clients (non-blocking)
        try:
            from shared.clients.google_client import GoogleClient
            self._pipeline.google = GoogleClient()
            print("[INIT] GoogleClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] GoogleClient skipped: {e}", flush=True)
            # No-op google client that returns safe defaults
            class NoOpGoogle:
                def get_or_create_folder(self, *a, **kw):
                    return {"id": "no-google-drive"}
                def __getattr__(self, name):
                    return lambda *a, **kw: None
            self._pipeline.google = NoOpGoogle()

        try:
            from shared.clients.slack_client import SlackClient
            self._pipeline.slack = SlackClient()
            print("[INIT] SlackClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] SlackClient skipped: {e}", flush=True)
            # Create a no-op slack client
            class NoOpSlack:
                def __getattr__(self, name):
                    """Return a no-op for any method call."""
                    return lambda *a, **kw: None
            self._pipeline.slack = NoOpSlack()

        try:
            from shared.clients.image_client import ImageClient
            self._pipeline.image_client = ImageClient(google_client=self._pipeline.google)
            print("[INIT] ImageClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] ImageClient skipped: {e}", flush=True)
            self._pipeline.image_client = None

        try:
            from shared.clients.elevenlabs_client import ElevenLabsClient
            self._pipeline.elevenlabs = ElevenLabsClient()
            print("[INIT] ElevenLabsClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] ElevenLabsClient skipped: {e}", flush=True)
            self._pipeline.elevenlabs = None

        try:
            from shared.clients.gemini_client import GeminiClient
            self._pipeline.gemini = GeminiClient()
            print("[INIT] GeminiClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] GeminiClient skipped: {e}", flush=True)
            self._pipeline.gemini = None

        # Pipeline state properties (set by _load_idea)
        self._pipeline.current_idea = None
        self._pipeline.current_idea_id = None
        self._pipeline.video_title = None
        self._pipeline.visual_style = None
        self._pipeline.project_folder_id = None
        self._pipeline.google_doc_id = None
        self._pipeline.core_image_url = None
        self._pipeline.video_config = None
        self._pipeline._duration_was_set = True

        # Import pipeline helper methods we need
        from orchestrator.pipeline_config import VideoConfig
        from orchestrator.pipeline_constants import IdeaFields, Statuses

        def _load_idea(idea):
            """Load an idea record into pipeline state."""
            self._pipeline.current_idea = idea
            self._pipeline.current_idea_id = idea.get("id")
            self._pipeline.video_title = idea.get(IdeaFields.VIDEO_TITLE, "")
            self._pipeline.visual_style = idea.get(IdeaFields.VISUAL_STYLE, "cinematic_illustration")
            self._pipeline.project_folder_id = idea.get(IdeaFields.DRIVE_FOLDER_ID, "")
            # Video config
            video_length = idea.get(IdeaFields.VIDEO_LENGTH_MIN)
            if video_length:
                self._pipeline._duration_was_set = True
                self._pipeline.video_config = VideoConfig(video_length_minutes=int(float(video_length)))
            else:
                self._pipeline._duration_was_set = False
                self._pipeline.video_config = VideoConfig(video_length_minutes=10)
            # Core image
            core_img = idea.get(IdeaFields.CORE_IMAGE)
            if isinstance(core_img, list) and core_img:
                self._pipeline.core_image_url = core_img[0].get("url")

        self._pipeline._load_idea = _load_idea

        def _update_status(new_status):
            """Update status via adapter (pipeline skills call this)."""
            if self._pipeline.current_idea_id:
                self._pipeline.airtable.update_idea_status(
                    self._pipeline.current_idea_id, new_status
                )

        self._pipeline._update_status = _update_status

        def get_idea_by_status(status):
            ideas = self._pipeline.airtable.get_ideas_by_status(status, limit=1)
            return ideas[0] if ideas else None

        self._pipeline.get_idea_by_status = get_idea_by_status

        # Pipeline filter properties (used by some bot stages)
        self._pipeline.image_filter = None
        self._pipeline.scene_filter = None
        self._pipeline.channel_profile = None

        # Import pipeline stage runners (lazy — they import their own deps)
        async def run_brief_translator():
            from script.run import run
            return await run(self._pipeline)

        async def run_voice_bot():
            from voice.run import run
            return await run(self._pipeline)

        async def run_styled_image_prompts():
            from image_prompts.run import run
            return await run(self._pipeline)

        async def run_image_bot():
            from images.run import run
            return await run(self._pipeline)

        async def run_video_script_bot():
            from video_motion.run_scripts import run
            return await run(self._pipeline)

        async def run_video_gen_bot():
            from video_motion.run_generate import run
            return await run(self._pipeline)

        async def run_thumbnail_bot():
            from thumbnail.run import run
            return await run(self._pipeline)

        async def run_render_bot():
            from render.run import run
            return await run(self._pipeline)

        async def run_sound_prompt_bot():
            from sound.run_design import run
            return await run(self._pipeline)

        async def run_sound_bot():
            from sound.run_effects import run
            return await run(self._pipeline)

        async def run_storyboard_prompts():
            from storyboard.run import run
            return await run(self._pipeline)

        async def run_storyboard_images():
            from storyboard.run_images import run
            return await run(self._pipeline)

        async def run_storyboard_extract():
            from storyboard.run_extract import run
            return await run(self._pipeline)

        self._pipeline.run_brief_translator = run_brief_translator
        self._pipeline.run_voice_bot = run_voice_bot
        self._pipeline.run_styled_image_prompts = run_styled_image_prompts
        self._pipeline.run_image_bot = run_image_bot
        self._pipeline.run_video_script_bot = run_video_script_bot
        self._pipeline.run_video_gen_bot = run_video_gen_bot
        self._pipeline.run_thumbnail_bot = run_thumbnail_bot
        self._pipeline.run_render_bot = run_render_bot
        self._pipeline.run_sound_prompt_bot = run_sound_prompt_bot
        self._pipeline.run_sound_bot = run_sound_bot
        self._pipeline.run_storyboard_prompts = run_storyboard_prompts
        self._pipeline.run_storyboard_images = run_storyboard_images
        self._pipeline.run_storyboard_extract = run_storyboard_extract

        print("[INIT] Pipeline ready!", flush=True)

        self._initialized = True

    async def _log_activity(
        self,
        bot_name: str,
        video_id: Optional[str],
        status: str,
        message: Optional[str] = None,
        cost: float = 0,
    ):
        """Log activity to bot_activity table.

        Args:
            bot_name: Name of the bot (e.g., "Research Agent")
            video_id: Supabase video UUID
            status: One of: started, running, completed, failed
            message: Optional status message
            cost: Cost in USD
        """
        try:
            await execute(
                """INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message, cost)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                self.tenant_id, bot_name, video_id, status, message, cost,
            )
        except Exception as e:
            print(f"Failed to log activity: {e}")

    async def _get_video(self, video_id: str) -> Optional[dict]:
        """Get video from Supabase by ID."""
        return await fetch_one(
            "SELECT * FROM videos WHERE id = $1 AND tenant_id = $2",
            video_id, self.tenant_id,
        )

    def _load_idea_from_video(self, video_id: str):
        """Load idea into pipeline state from Supabase video UUID.

        Uses the SupabaseAdapter which returns Airtable-shaped dicts.
        """
        idea = self._pipeline.airtable.get_idea(video_id)
        if idea:
            self._pipeline._load_idea(idea)
        else:
            print(f"[WARN] Could not load idea for video_id={video_id}", flush=True)

    async def _update_video_status(self, video_id: str, new_status: str):
        """Update video status in Supabase.

        Args:
            video_id: Supabase video UUID
            new_status: New status in Supabase format
        """
        await execute(
            "UPDATE videos SET status = $1, updated_at = now() WHERE id = $2",
            new_status, video_id,
        )

    async def _log_transition(
        self,
        video_id: str,
        from_status: str,
        to_status: str,
        triggered_by: str = "api",
        cost: float = 0,
        error_message: Optional[str] = None,
    ):
        """Log status transition."""
        await execute(
            """INSERT INTO stage_transitions
               (video_id, tenant_id, from_status, to_status, triggered_by, cost, error_message)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            video_id, self.tenant_id, from_status, to_status, triggered_by, cost, error_message,
        )

    async def create_idea(
        self,
        topic: str,
        source: str = "storyengine",
    ) -> dict:
        """Create a new video idea.

        Args:
            topic: Topic or headline for the video
            source: Source identifier

        Returns:
            Dict with video_id and status
        """
        await self._ensure_initialized()
        bot_name = "Idea Bot"
        video_id = None

        try:
            await self._log_activity(bot_name, None, "started", f"Creating idea: {topic}")

            # Create in Supabase first
            result = await fetch_one(
                """INSERT INTO videos (tenant_id, video_title, status, headline, source, created_at)
                   VALUES ($1, $2, $3, $4, $5, now())
                   RETURNING id""",
                self.tenant_id, topic, "idea_logged", topic, source,
            )
            video_id = str(result["id"])

            # Also create in Airtable via pipeline
            # The pipeline's idea_bot expects input_text
            idea_result = await self._pipeline.run_idea_bot(topic)

            if idea_result.get("error"):
                raise Exception(idea_result["error"])

            await self._log_activity(bot_name, video_id, "completed", "Idea created")

            return {
                "video_id": video_id,
                "status": "idea_logged",
                "message": "Idea created successfully",
            }

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {
                "video_id": video_id,
                "status": "failed",
                "error": error_msg,
            }

    async def run_research(self, video_id: str) -> dict:
        """Run research agent on a video idea.

        Args:
            video_id: Supabase video UUID

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()
        bot_name = "Research Agent"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            topic = video.get("video_title") or video.get("headline")

            if not topic:
                return {"status": "failed", "error": "No topic found for video"}

            await self._log_activity(bot_name, video_id, "started", f"Researching: {topic}")

            # Import research agent
            from research.agent import run_research

            # Run research
            payload = await run_research(
                anthropic_client=self._pipeline.anthropic,
                topic=topic,
                airtable_client=self._pipeline.airtable,
            )

            if not payload:
                raise Exception("Research returned no results")

            # Update Supabase with research payload
            import json
            await execute(
                """UPDATE videos SET
                   research_payload = $1,
                   thesis = $2,
                   executive_hook = $3,
                   status = $4,
                   updated_at = now()
                   WHERE id = $5""",
                json.dumps(payload),
                payload.get("thesis", ""),
                payload.get("executive_hook", ""),
                "ready_for_scripting",
                video_id,
            )

            await self._log_transition(video_id, current_status, "ready_for_scripting", "api")
            await self._log_activity(bot_name, video_id, "completed", "Research complete")

            return {
                "status": "ready_for_scripting",
                "video_id": video_id,
                "headline": payload.get("headline"),
            }

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_script(self, video_id: str) -> dict:
        """Generate script for a video.

        Args:
            video_id: Supabase video UUID

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()
        bot_name = "Script Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            if not is_at_or_past_stage(current_status, "ready_for_scripting"):
                return {"status": "failed", "error": f"Video not ready for scripting (status: {current_status})"}

            await self._log_activity(bot_name, video_id, "started", "Generating script")

            # Load idea into pipeline state from Supabase
            self._load_idea_from_video(video_id)

            # Run script generation
            result = await self._pipeline.run_brief_translator()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_voice")

            # Update Supabase
            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Script generated")

            return {
                "status": to_supabase(new_status),
                "video_id": video_id,
            }

        except Exception as e:
            import traceback
            error_msg = str(e)
            tb = traceback.format_exc()
            print(f"\n{'='*60}\nPIPELINE ERROR in run_script:\n{tb}\n{'='*60}\n", flush=True)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_voice(self, video_id: str) -> dict:
        """Generate voice narration for a video.

        Args:
            video_id: Supabase video UUID

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()
        bot_name = "Voice Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            if not is_at_or_past_stage(current_status, "ready_for_voice"):
                return {"status": "failed", "error": f"Video not ready for voice (status: {current_status})"}

            await self._log_activity(bot_name, video_id, "started", "Generating voice")

            # Load idea into pipeline state from Supabase
            self._load_idea_from_video(video_id)

            # Run voice generation
            result = await self._pipeline.run_voice_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_image_prompts")

            # Update Supabase
            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Voice generated")

            return {
                "status": to_supabase(new_status),
                "video_id": video_id,
            }

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_next_step(self, video_id: str, user_intent: str = None) -> dict:
        """Run the next pipeline step for a video.

        If CLAUDE_ORCHESTRATION is enabled for this tenant, uses Claude to
        decide which skill to invoke. Otherwise falls back to the status map.

        Args:
            video_id: Supabase video UUID
            user_intent: Optional natural language from user

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()

        # Feature flag: Claude orchestration
        use_claude = await self._is_claude_orchestration_enabled()

        if use_claude:
            return await self._run_next_step_claude(video_id, user_intent)
        else:
            return await self._run_next_step_status_map(video_id)

    async def _is_claude_orchestration_enabled(self) -> bool:
        """Check if Claude orchestration is enabled for this tenant."""
        try:
            from vault import get_secret
            flag = await get_secret("claude_orchestration", self.tenant_id)
            return flag and flag.lower() in ("true", "1", "yes", "on")
        except Exception:
            return False

    async def _run_next_step_claude(self, video_id: str, user_intent: str = None) -> dict:
        """Claude-driven next step decision."""
        try:
            from claude_orchestrator import ClaudeOrchestrator

            orchestrator = ClaudeOrchestrator(self.tenant_id)
            decision = await orchestrator.decide(video_id, user_intent=user_intent)

            if decision.confidence < ClaudeOrchestrator.CONFIDENCE_THRESHOLD:
                return {
                    "status": "needs_input",
                    "decision": decision.model_dump(),
                    "message": f"Low confidence ({decision.confidence:.0%}). {decision.reasoning}",
                    "alternatives": decision.alternatives,
                }

            result = await orchestrator.execute(decision, video_id, executor=self)
            return {
                "status": "completed" if result.success else "failed",
                "decision": decision.model_dump(),
                "result": result.execution_result,
                "error": result.error,
            }
        except Exception as e:
            # Fallback to status map on any failure
            print(f"[orchestrator] Claude orchestration failed: {e}, falling back to status map")
            return await self._run_next_step_status_map(video_id)

    async def _run_next_step_status_map(self, video_id: str) -> dict:
        """Original status-driven next step (fallback)."""
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}

        current_status = video.get("status")

        # Map status to handler
        handlers = {
            "idea_logged": self.run_research,
            "approved": self.run_research,
            "ready_for_scripting": self.run_script,
            "ready_for_voice": self.run_voice,
            "ready_for_image_prompts": self.run_prompts,
            "ready_for_storyboards": self.run_storyboard_prompts,
            "ready_for_storyboard_images": self.run_storyboard_images,
            "ready_for_storyboard_extraction": self.run_storyboard_extract,
            "ready_for_images": self.run_images,
            "ready_for_sound_design": self.run_sound_prompts,
            "ready_for_sound_effects": self.run_sound_effects,
            "ready_for_video_scripts": self.run_video_scripts,
            "ready_for_video_generation": self.run_video_generation,
            "ready_for_thumbnail": self.run_thumbnail,
            "ready_to_render": self.run_render,
        }

        handler = handlers.get(current_status)
        if not handler:
            return {
                "status": "idle",
                "message": f"No action available for status: {current_status}",
            }

        return await handler(video_id)

    async def run_prompts(self, video_id: str) -> dict:
        """Generate image prompts for a video."""
        await self._ensure_initialized()
        bot_name = "Image Prompt Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating prompts")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_styled_image_prompts()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_images")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Prompts generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_prompts(self, video_id: str) -> dict:
        """Generate storyboard prompts for a video."""
        await self._ensure_initialized()
        bot_name = "Storyboard Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating storyboard prompts")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_storyboard_prompts()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_storyboard_images")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Storyboard prompts generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_images(self, video_id: str) -> dict:
        """Generate storyboard images for a video."""
        await self._ensure_initialized()
        bot_name = "Storyboard Images Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating storyboard images")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_storyboard_images()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_storyboard_extraction")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Storyboard images generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_extract(self, video_id: str) -> dict:
        """Extract storyboard frames for a video."""
        await self._ensure_initialized()
        bot_name = "Storyboard Extract Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Extracting storyboard frames")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_storyboard_extract()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_images")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Storyboard frames extracted")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_images(self, video_id: str) -> dict:
        """Generate images for a video."""
        await self._ensure_initialized()
        bot_name = "Image Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating images")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_image_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_thumbnail")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Images generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_sound_prompts(self, video_id: str) -> dict:
        """Generate sound design prompts for a video."""
        await self._ensure_initialized()
        bot_name = "Sound Design Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating sound prompts")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_sound_prompt_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_sound_effects")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Sound prompts generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_sound_effects(self, video_id: str) -> dict:
        """Generate sound effects for a video."""
        await self._ensure_initialized()
        bot_name = "Sound Effects Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating sound effects")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_sound_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_video_scripts")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Sound effects generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_video_scripts(self, video_id: str) -> dict:
        """Generate video motion scripts for a video."""
        await self._ensure_initialized()
        bot_name = "Video Script Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating video scripts")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_video_script_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_video_generation")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Video scripts generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_video_generation(self, video_id: str) -> dict:
        """Generate video clips for a video."""
        await self._ensure_initialized()
        bot_name = "Video Gen Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating video clips")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_video_gen_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_thumbnail")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Video clips generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_thumbnail(self, video_id: str) -> dict:
        """Generate thumbnail for a video."""
        await self._ensure_initialized()
        bot_name = "Thumbnail Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating thumbnail")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_thumbnail_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "done")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Thumbnail generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_render(self, video_id: str) -> dict:
        """Render final video."""
        await self._ensure_initialized()
        bot_name = "Render Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Rendering video")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_render_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "rendered")

            # Update with video URL if available
            video_url = result.get("video_url")
            if video_url:
                await execute(
                    "UPDATE videos SET final_video_url = $1 WHERE id = $2",
                    video_url, video_id,
                )

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Video rendered")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}
