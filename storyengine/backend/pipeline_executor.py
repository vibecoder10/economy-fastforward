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
import uuid
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
                "upload", "analytics", "title_idea"]:
    bot_path = str(PIPELINE_PATH / bot_dir)
    if bot_path not in sys.path:
        sys.path.append(bot_path)

from database import fetch_one, fetch_all, execute
from error_utils import humanize_error, user_facing
from status_map import to_supabase, to_pipeline, get_bot_name, STAGE_BOT_MAP, is_at_or_past_stage
from vault import get_secret
from extraction import extract_grid
from storage import upload_from_url

import logging
_logger = logging.getLogger(__name__)


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

        # Load API keys from Vault into environment.
        # SECURITY: Clear ALL known pipeline env vars first to prevent cross-tenant
        # contamination. Without this, a previous tenant's keys persist in os.environ
        # and get picked up by downstream pipeline code that reads env vars directly.
        keys_to_load = [
            "anthropic_api_key",
            "airtable_api_key",
            "elevenlabs_api_key",
            "kie_ai_api_key",
            "openai_api_key",
            "gemini_api_key",
        ]
        env_names_to_clear = [k.upper() for k in keys_to_load] + ["WAVESPEED_API_KEY", "ANTHROPIC_BASE_URL"]
        for env_name in env_names_to_clear:
            os.environ.pop(env_name, None)

        for key_name in keys_to_load:
            print(f"[INIT] Loading key: {key_name}...", flush=True)
            try:
                value = await get_secret(key_name, self.tenant_id)
                if value:
                    env_name = key_name.upper()
                    os.environ[env_name] = value
                    # ElevenLabs client looks for WAVESPEED_API_KEY, not ELEVENLABS_API_KEY
                    if key_name == "elevenlabs_api_key":
                        os.environ["WAVESPEED_API_KEY"] = value
                    print(f"[INIT]   ✓ {key_name} loaded", flush=True)
                else:
                    print(f"[INIT]   - {key_name} not found", flush=True)
            except Exception as e:
                print(f"[INIT]   ✗ {key_name} error: {e}", flush=True)

        # Kie.ai covers Claude ("we use kie ai for any claude calls"): when the
        # tenant has no direct Anthropic key, route the pipeline's Claude calls
        # through Kie's Anthropic-compatible gateway. AnthropicClient reads
        # ANTHROPIC_BASE_URL and switches to Bearer auth + undated model aliases.
        if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("KIE_AI_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = os.environ["KIE_AI_API_KEY"]
            os.environ["ANTHROPIC_BASE_URL"] = os.getenv(
                "KIE_CLAUDE_BASE_URL", "https://api.kie.ai/claude"
            )
            print("[INIT] Claude routed via Kie.ai gateway (no direct Anthropic key)", flush=True)

        # Create a lightweight pipeline object that only has what we need.
        # We can't import VideoPipeline directly because it imports ALL clients
        # (Slack, Google, ElevenLabs, etc.) which hang if services are unavailable.
        print("[INIT] Creating lightweight pipeline...", flush=True)

        from supabase_adapter import SupabaseAdapter

        class LightPipeline:
            """Minimal pipeline that only has the clients we need."""

            scene_filter = None
            image_filter = None
            should_cancel = None  # armed per-run by _install_cancel_support
            character_reference_urls = None  # approved cast, loaded per-run

            @property
            def _is_targeted_run(self):
                """True if scene/image filters are set (partial run, don't advance status)."""
                return self.scene_filter is not None or self.image_filter is not None

            def _log_filters(self):
                """Print active targeting filters."""
                if self.scene_filter is not None and self.image_filter is not None:
                    print(f"  🎯 TARGETED RUN: Scene {self.scene_filter}, Image {self.image_filter}")
                elif self.scene_filter is not None:
                    print(f"  🎯 TARGETED RUN: Scene {self.scene_filter} (all images)")

            def _filter_by_scene(self, records, scene_key="Scene"):
                """Filter records by scene_filter and image_filter if set."""
                if self.scene_filter is not None:
                    records = [r for r in records if r.get(scene_key) == self.scene_filter]
                if self.image_filter is not None:
                    from orchestrator.pipeline_constants import ImageFields
                    records = [r for r in records if r.get(ImageFields.IMAGE_INDEX) == self.image_filter]
                return records

            def _update_status(self, new_status):
                """Update idea status in the adapter and in-memory cache."""
                from orchestrator.pipeline_constants import IdeaFields
                if self.current_idea:
                    self.airtable.update_idea_status(self.current_idea_id, new_status)
                    self.current_idea[IdeaFields.STATUS] = new_status

        self._pipeline = LightPipeline()
        self._pipeline.airtable = SupabaseAdapter(tenant_id=self.tenant_id)
        print("[INIT] SupabaseAdapter OK", flush=True)

        # Anthropic client — required for research, script, prompts
        try:
            from shared.clients.anthropic_client import AnthropicClient
            self._pipeline.anthropic = AnthropicClient()
            print("[INIT] AnthropicClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] AnthropicClient skipped: {e}", flush=True)
            self._pipeline.anthropic = None

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

        @property
        def _is_targeted_run(pipe):
            return pipe.scene_filter is not None or pipe.image_filter is not None

        LightPipeline._is_targeted_run = _is_targeted_run

        def _log_filters():
            if self._pipeline.scene_filter is not None:
                print(f"  🎯 Scene filter: {self._pipeline.scene_filter}", flush=True)
            if self._pipeline.image_filter is not None:
                print(f"  🎯 Image filter: {self._pipeline.image_filter}", flush=True)

        self._pipeline._log_filters = _log_filters

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

        async def run_upload_bot():
            from upload.run import run
            return await run(self._pipeline)

        async def run_sound_prompt_bot():
            from sound.run_design import run
            return await run(self._pipeline)

        async def run_sound_bot():
            from sound.run_effects import run
            return await run(self._pipeline)

        async def run_storyboard_prompts(scene_filter=None, progress_callback=None):
            """Run storyboard prompt generation for the pipeline, optionally filtered by scene."""
            from storyboard.run import run
            return await run(self._pipeline, scene_filter=scene_filter, progress_callback=progress_callback)

        async def run_storyboard_images(scene_filter=None, progress_callback=None):
            from storyboard.run_images import run
            return await run(self._pipeline, scene_filter=scene_filter, progress_callback=progress_callback)

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
        self._pipeline.run_upload_bot = run_upload_bot

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
        # Humanize at the write boundary so /api/activity never returns
        # raw str(e) to the UI. ~20 call sites in this file pass
        # error_msg = str(e) → here — one line covers all of them.
        safe_message = message
        if status == "failed" and message:
            safe_message = humanize_error(message)
        try:
            await execute(
                """INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message, cost)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                self.tenant_id, bot_name, video_id, status, safe_message, cost,
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

    async def _check_voice_exists(self, video_id: str) -> tuple[bool, int, int]:
        """Check if voice has been generated for all scenes.

        Returns (all_have_voice, total_scenes, scenes_with_voice).
        """
        rows = await fetch_all(
            "SELECT voice_over_url FROM scripts WHERE video_id = $1",
            video_id,
        )
        total = len(rows)
        with_voice = sum(1 for r in rows if r.get("voice_over_url"))
        return (total > 0 and with_voice == total), total, with_voice

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

    async def _load_prompt_overrides(self, video: dict):
        """Load system prompt overrides onto the pipeline object.

        Priority: per-video override > tenant override > None (bot uses built-in default).

        Sets pipeline attributes like `script_system_prompt`, `thumbnail_system_prompt`, etc.
        that bots read via `getattr(pipeline, '<key>_system_prompt', None)`.

        Args:
            video: Video row dict from Supabase (contains per-video override columns).
        """
        # Mapping: tenant prompt_key -> (video column, pipeline attribute)
        PROMPT_MAP = {
            "script":           ("script_system_prompt",       "script_system_prompt"),
            "thumbnail":        ("thumbnail_system_prompt",    "thumbnail_system_prompt"),
            "video_motion":     ("video_motion_system_prompt", "video_motion_system_prompt"),
            "sound_curation":   ("sound_system_prompt",        "sound_curation_system_prompt"),
            "sound_generation": ("sound_system_prompt",        "sound_generation_system_prompt"),
            "research":         (None,                         "research_system_prompt"),
        }

        # Fetch tenant-level defaults
        tenant_overrides = {}
        try:
            rows = await fetch_all(
                "SELECT prompt_key, prompt_text FROM tenant_prompt_defaults WHERE tenant_id = $1",
                self.tenant_id,
            )
            tenant_overrides = {r["prompt_key"]: r["prompt_text"] for r in rows}
        except Exception as e:
            _logger.warning("Failed to load tenant prompt overrides: %s", e)

        # Resolve each prompt: per-video > tenant > None
        for prompt_key, (video_col, pipeline_attr) in PROMPT_MAP.items():
            # Per-video override (if column exists on the videos table)
            per_video = video.get(video_col) if video_col else None
            # Tenant override
            tenant = tenant_overrides.get(prompt_key)
            # Set on pipeline: per-video wins, then tenant, then None
            resolved = per_video or tenant or None
            setattr(self._pipeline, pipeline_attr, resolved)

    async def _install_cancel_support(self, video_id: str):
        """Arm cooperative cancellation for a paid generation run.

        Clears any stale cancel request first (a Stop from a previous run must
        never kill the resume), then exposes pipeline.should_cancel — an async
        callable the generation loops poll between paid items. Works across
        processes (arq worker) via the background_tasks 'cancelled' marker row.
        """
        # NOTE: stale-cancel cleanup happens at run start in _set_task_status
        # (routes/pipeline.py) — resetting here raced with real Stop requests
        # arriving while the executor was still initializing.
        from cancel_registry import is_cancel_requested
        tenant_id = self.tenant_id

        async def _should_cancel() -> bool:
            try:
                return await is_cancel_requested(tenant_id, video_id)
            except Exception:
                return False

        self._pipeline.should_cancel = _should_cancel

    async def _load_character_refs(self, video_id: str, video: dict):
        """Load the approved cast onto the pipeline for reference-locked
        generation. Returns an error string when characters exist but the cast
        isn't approved yet (the character-design gate); None otherwise.
        Videos with no designed characters skip the step entirely."""
        try:
            rows = await fetch_all(
                "SELECT reference_url FROM video_characters "
                "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
                "ORDER BY sort, created_at",
                video_id, self.tenant_id,
            )
        except Exception:
            rows = []
        if not rows:
            self._pipeline.character_reference_urls = None
            return None
        if not video.get("characters_approved_at"):
            self._pipeline.character_reference_urls = None
            return user_facing("Your cast is designed but not approved yet — open the Characters tab, "
                               "review the portraits, and hit Approve before generating visuals.")
        # ONE labeled cast sheet conditions far better than N competing
        # portraits (live finding: 6 refs at once = inconsistent characters).
        # approve_cast stores the sheet on character_reference_url.
        sheet = video.get("character_reference_url")
        if sheet:
            self._pipeline.character_reference_urls = [sheet]
        else:
            self._pipeline.character_reference_urls = [r["reference_url"] for r in rows][:6]
        return None

    async def _persist_url(self, source_url: str, storage_path: str) -> str:
        """Re-upload a temporary URL to Google Drive for permanent access.

        Returns the permanent URL, or the original URL if upload fails or URL is already permanent.
        """
        if not source_url:
            return source_url
        if "drive.google.com" in source_url or "supabase.co/storage" in source_url:
            return source_url
        try:
            return await upload_from_url(source_url, storage_path)
        except Exception as e:
            _logger.warning("Failed to persist %s: %s", storage_path, e)
            return source_url

    async def _persist_asset_urls(self, video_id: str) -> int:
        """Re-upload all temp asset image_urls for a video to Google Drive.

        Returns the number of URLs persisted.
        """
        assets = await fetch_all(
            """SELECT id, scene, image_index, image_url FROM assets
               WHERE video_id = $1 AND tenant_id = $2 AND image_url IS NOT NULL
               AND image_url NOT LIKE '%drive.google.com%'
               AND image_url NOT LIKE '%supabase.co/storage%'""",
            video_id, self.tenant_id,
        )
        count = 0
        for a in assets:
            path = f"{video_id}/images/S{a['scene']}-{a['image_index']}.png"
            new_url = await self._persist_url(a["image_url"], path)
            if new_url != a["image_url"]:
                await execute(
                    "UPDATE assets SET image_url = $1, updated_at = now() WHERE id = $2",
                    new_url, a["id"],
                )
                count += 1
        return count

    async def _persist_storyboard_urls(self, video_id: str) -> int:
        """Re-upload all temp storyboard grid URLs to Google Drive.

        Returns the number of URLs persisted.
        """
        scenes = await fetch_all(
            """SELECT id, scene, storyboard_1_url, storyboard_2_url,
                      storyboard_3_url, storyboard_4_url, storyboard_5_url
               FROM scripts WHERE video_id = $1 AND tenant_id = $2
               ORDER BY scene""",
            video_id, self.tenant_id,
        )
        count = 0
        for sc in scenes:
            updates = []
            params = []
            idx = 1
            for beat in range(1, 6):
                col = f"storyboard_{beat}_url"
                url = sc.get(col)
                if url and "drive.google.com" not in url and "supabase.co/storage" not in url:
                    path = f"{video_id}/storyboard/S{sc['scene']}-B{beat}.png"
                    new_url = await self._persist_url(url, path)
                    if new_url != url:
                        updates.append(f"{col} = ${idx}")
                        params.append(new_url)
                        idx += 1
                        count += 1
            if updates:
                params.append(sc["id"])
                sql = f"UPDATE scripts SET {', '.join(updates)}, updated_at = now() WHERE id = ${idx}"
                await execute(sql, *params)
        return count

    async def create_idea(
        self,
        topic: str,
        source: str = "storyengine",
    ) -> dict:
        """Create a new video idea.

        Creates a video record in Supabase with status 'idea_logged'.
        Research and scripting are triggered separately from the video detail page.

        Args:
            topic: Topic or headline for the video
            source: Source identifier

        Returns:
            Dict with video_id and status
        """
        # No pipeline initialization needed — just a DB insert
        bot_name = "Idea Bot"
        video_id = None

        try:
            await self._log_activity(bot_name, None, "started", f"Creating idea: {topic}")

            # Resolve project for tenant
            from routes.projects import _get_or_create_project
            project = await _get_or_create_project(self.tenant_id)
            project_id = str(project["id"])

            # Create video record in Supabase
            result = await fetch_one(
                """INSERT INTO videos (tenant_id, project_id, video_title, status, headline, source, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, now())
                   RETURNING id""",
                self.tenant_id, project_id, topic, "idea_logged", topic, source,
            )
            video_id = str(result["id"])

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

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            # Import research agent
            from research.agent import run_research

            # Run research
            payload = await run_research(
                anthropic_client=self._pipeline.anthropic,
                topic=topic,
                airtable_client=self._pipeline.airtable,
                system_prompt_override=getattr(self._pipeline, "research_system_prompt", None),
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

    async def _inject_learnings_into_writer_guidance(self, video_id: str):
        """Inject learned patterns into writer_guidance before script generation.

        This closes the script feedback loop: videos with high/low retention
        have their structural patterns extracted → stored in learnings table →
        injected here as writer guidance → script generator adapts.
        """
        try:
            learnings = await fetch_all(
                """SELECT category, pattern, avg_ctr, avg_retention, sample_size, confidence
                   FROM learnings
                   WHERE tenant_id = $1 AND active = true
                     AND category IN ('script', 'hook', 'framework')
                     AND confidence >= 40
                   ORDER BY confidence DESC, avg_retention DESC NULLS LAST
                   LIMIT 10""",
                self.tenant_id,
            )
            if not learnings:
                return

            guidance_lines = ["\n\n--- PERFORMANCE LEARNINGS (from past videos) ---"]
            for l in learnings:
                cat = l.get("category", "")
                pattern = l.get("pattern", "")
                ret = float(l["avg_retention"]) if l.get("avg_retention") else None
                ctr = float(l["avg_ctr"]) if l.get("avg_ctr") else None
                conf = float(l.get("confidence", 0))
                verdict = "PROVEN" if conf >= 60 else "AVOID" if conf <= 40 else "TESTING"

                metrics = []
                if ret:
                    metrics.append(f"{ret:.0f}% retention")
                if ctr:
                    metrics.append(f"{ctr:.1f}% CTR")
                metric_str = f" ({', '.join(metrics)})" if metrics else ""

                if verdict == "AVOID":
                    guidance_lines.append(f"- AVOID: {pattern}{metric_str}")
                else:
                    guidance_lines.append(f"- USE: {pattern}{metric_str} [{verdict}]")

            guidance_lines.append("--- END LEARNINGS ---")
            learnings_block = "\n".join(guidance_lines)

            # Append to existing writer_guidance
            video = await fetch_one(
                "SELECT writer_guidance FROM videos WHERE id = $1",
                video_id,
            )
            existing = (video or {}).get("writer_guidance") or ""
            updated = existing + learnings_block

            await execute(
                "UPDATE videos SET writer_guidance = $1 WHERE id = $2",
                updated, video_id,
            )
            print(f"[Script] Injected {len(learnings)} learnings into writer_guidance for {video_id[:8]}")

        except Exception as e:
            print(f"[Script] Error injecting learnings: {e}")

    async def _run_modeled_script(self, video_id: str, video: dict) -> dict:
        """Script generation for style-replicated ('Model A Video') videos.

        The brief_translator is hardwired as a documentary writer (power-doctrine
        frameworks, number-density validation) and steamrolls any style override —
        a replicated kids-animation video came out as 'The Hidden Economics of
        Compassion'. Modeled videos instead get a direct generation in the
        reference's style, structured around the modeled scene concepts, and skip
        the documentary-specific editorial validation.
        """
        bot_name = "Script Bot"
        await self._log_activity(bot_name, video_id, "started", "Writing script in the reference's style")
        current_status = video.get("status")

        import json as _json
        original_dna = video.get("original_dna")
        if isinstance(original_dna, str):
            try:
                original_dna = _json.loads(original_dna)
            except Exception:
                original_dna = {}
        pack = (original_dna or {}).get("modeled_pack") or {}
        concepts = pack.get("scene_concepts") or []
        concept_lines = "\n".join(
            f"{i}. {c.get('concept')}" for i, c in enumerate(concepts, start=1)
        ) or "Structure the story into 8 natural scenes."
        minutes = int(video.get("video_length_minutes") or 10)
        target_words = max(300, minutes * 145)

        research = video.get("research_payload")
        if isinstance(research, dict):
            research = _json.dumps(research)
        research_excerpt = (research or "")[:4000]

        prompt = f"""Write the complete narration script for a video titled "{video.get('video_title')}".

{video.get('writer_guidance') or ''}

SCENE PLAN — write one section per scene, in this order:
{concept_lines}

Target length: about {target_words} words total, spread across the scenes.

Background material you may draw from (use only what fits the video's style and audience):
{research_excerpt}

Return ONLY valid JSON, no markdown fences:
{{"scenes": [{{"scene": 1, "text": "narration text for scene 1"}}, ...]}}

The "text" fields are exactly what the narrator will read aloud — no stage
directions, no labels, no headings inside them."""

        style_system = video.get("script_system_prompt") or ""
        raw = await self._pipeline.anthropic.generate(
            prompt=prompt,
            system_prompt=style_system,
            max_tokens=16000,
            temperature=0.7,
        )
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        scenes = _json.loads(text).get("scenes") or []
        scenes = [s for s in scenes if (s.get("text") or "").strip()]
        if len(scenes) < 3:
            raise Exception("Modeled script came back with too few scenes")

        full_script = "\n\n".join(s["text"].strip() for s in scenes)
        await execute(
            """UPDATE videos SET script = $1, script_validation = $2, status = $3, updated_at = now()
               WHERE id = $4 AND tenant_id = $5""",
            full_script,
            _json.dumps({"passed": True, "checks": [
                {"name": "style_replication", "passed": True,
                 "detail": "Documentary editorial checks skipped — script written in the reference video's style"}]}),
            "ready_for_voice",
            video_id, self.tenant_id,
        )
        await execute("DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2", video_id, self.tenant_id)
        for i, scene in enumerate(scenes, start=1):
            await execute(
                """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
                   VALUES ($1, $2, $3, $4, $5, 'Create', $6)""",
                self.tenant_id, video_id, i, scene["text"].strip(),
                # Mark — on Kie's allowed roster. The previous id was
                # off-roster, so every TTS call burned a wasted createTask
                # before the client's fallback (which lands on Mark anyway).
                video.get("video_title"), "1SM7GgM6IMuvQlz2BwM3",
            )

        await self._log_transition(video_id, current_status, "ready_for_voice", "api")

        # Dialogue intelligence runs unattended right after every script —
        # the north-star is full automation, so format detection (performed
        # dialogue vs pure voiceover) can never be a manual step. Best-effort:
        # a tagging hiccup must not fail the script stage (manual retro
        # trigger: POST /api/videos/{id}/script/tag-dialogue).
        try:
            from dialogue_intelligence import tag_video_dialogue
            tag_result = await tag_video_dialogue(video_id, self.tenant_id)
            _logger.info("[dialogue] %s: %s", video_id, tag_result)
        except Exception as e:
            _logger.warning("[dialogue] tagging failed for %s: %s", video_id, str(e)[:200])

        await self._log_activity(bot_name, video_id, "completed",
                                 f"Modeled-style script complete ({len(scenes)} scenes, {len(full_script.split())} words)")
        return {"status": "ready_for_voice", "video_id": video_id, "new_status": "ready_for_voice"}

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

            # Style-replicated videos get a dedicated script path — the
            # brief_translator's documentary machinery ignores their style.
            if video.get("source") == "modeled" and video.get("script_system_prompt"):
                return await self._run_modeled_script(video_id, video)

            await self._log_activity(bot_name, video_id, "started", "Generating script")

            # Inject performance learnings into writer_guidance BEFORE script generation
            await self._inject_learnings_into_writer_guidance(video_id)

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

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

    async def run_voice(self, video_id: str, scene: int = None) -> dict:
        """Generate voice narration for a video.

        Args:
            video_id: Supabase video UUID
            scene: Optional scene number for single-scene generation

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
            if scene is None and not is_at_or_past_stage(current_status, "ready_for_voice"):
                return {"status": "failed", "error": f"Video not ready for voice (status: {current_status})"}

            msg = f"Generating voice (scene {scene})" if scene else "Generating voice"
            await self._log_activity(bot_name, video_id, "started", msg)

            # Load idea into pipeline state from Supabase
            self._load_idea_from_video(video_id)

            # Override status to "Ready For Voice" so the bot's internal check passes.
            if self._pipeline.current_idea:
                self._pipeline.current_idea["Status"] = "Ready For Voice"

            # Set scene filter for targeted generation
            if scene is not None:
                self._pipeline.scene_filter = scene

            # Run voice generation
            await self._install_cancel_support(video_id)
            result = await self._pipeline.run_voice_bot()

            if result.get("cancelled"):
                kept = result.get("voice_count", 0)
                msg = f"Stopped — kept {kept} completed voice track(s). Run Voice again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg)
                self._pipeline.scene_filter = None
                return {"status": "cancelled", "video_id": video_id, "error": msg}

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_image_prompts")

            # Update Supabase
            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Voice generated")

            # Dialogue-mode videos also get their per-segment performance
            # track (narrator + character lines) — silent plumbing, like the
            # tag-dialogue hook: best-effort, never fails the voice stage.
            if scene is None and (video.get("dialogue_mode") or "") == "character_dialogue":
                try:
                    seg_result = await self.run_dialogue_voice(video_id)
                    print(f"[dialogue-voice] {video_id}: {seg_result}", flush=True)
                except Exception as e:
                    print(f"[dialogue-voice] hook failed for {video_id}: {str(e)[:200]}", flush=True)

            return {
                "status": to_supabase(new_status),
                "video_id": video_id,
            }

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_dialogue_voice(self, video_id: str, scene: int = None, progress_callback=None) -> dict:
        """Voice every dialogue_segments entry (per-segment performance track).

        Narration segments use the scene's narrator voice; dialogue lines use
        the character's cast voice (video_characters.voice_name). Additive —
        does not touch scripts.voice_over_url or advance the video status.
        Untagged videos get the dialogue intelligence pass first (unattended
        north-star: no manual prerequisite steps).
        """
        await self._ensure_initialized()
        bot_name = "Dialogue Voice Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            if not self._pipeline.elevenlabs:
                return {"status": "failed", "error": user_facing(
                    "Voice synthesis isn't configured — add a Kie.ai or ElevenLabs key in Settings → Keys.")}

            if not video.get("dialogue_mode"):
                from dialogue_intelligence import tag_video_dialogue, cast_character_voices
                tag_result = await tag_video_dialogue(video_id, self.tenant_id)
                if tag_result.get("dialogue_mode") == "character_dialogue":
                    await cast_character_voices(video_id, self.tenant_id)
                video = await self._get_video(video_id)

            if (video.get("dialogue_mode") or "") != "character_dialogue":
                msg = "Narration-only video — no per-segment voices needed"
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id, "message": msg}

            label = f"Voicing dialogue segments (scene {scene})" if scene else "Voicing dialogue segments"
            await self._log_activity(bot_name, video_id, "started", label)
            await self._install_cancel_support(video_id)

            from dialogue_voice import synthesize_video_segments
            result = await synthesize_video_segments(
                video_id,
                self.tenant_id,
                tts=self._pipeline.elevenlabs,
                scene_filter=scene,
                progress_callback=progress_callback,
                cancel_check=self._pipeline.should_cancel,
            )

            if result.get("cancelled"):
                msg = (f"Stopped — kept {result['segments_voiced']} voiced segment(s). "
                       "Run again to resume.")
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg, **result}

            msg = (f"Voiced {result['segments_voiced']} segment(s) across "
                   f"{result['scenes']} scene(s)"
                   + (f", {result['segments_skipped']} already done" if result["segments_skipped"] else "")
                   + (f" — {len(result['warnings'])} warning(s)" if result["warnings"] else ""))
            for w in result["warnings"]:
                print(f"[dialogue-voice] {video_id}: ⚠ {w}", flush=True)
            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": "completed", "video_id": video_id, "message": msg, **result}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_clip_generation(
        self,
        video_id: str,
        asset_id: str = None,
        scene: int = None,
        force: bool = False,
        progress_callback=None,
    ) -> dict:
        """Generate motion clips from final pictures — one card, one scene, or all.

        All three rungs of the trust ladder land here (tap a card / Animate
        this scene / Animate everything). Honors videos.video_model via
        MODEL_REGISTRY (Grok + Veo wired). Clip result URLs expire ~24h, so
        every clip downloads immediately and persists to Drive {video}/clips/.
        Additive: only a full run that finishes every clip advances status.
        """
        await self._ensure_initialized()
        bot_name = "Clip Bot"
        import re as _re

        async def _report(msg: str):
            if progress_callback:
                try:
                    await progress_callback(msg)
                except Exception:
                    pass

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            from shared.channel_profile import MODEL_REGISTRY, DEFAULT_VIDEO_MODEL
            model_id = (video.get("video_model") or "").strip() or DEFAULT_VIDEO_MODEL
            profile = MODEL_REGISTRY.get(model_id)
            # Only models with a live generation path are selectable — the
            # old dropdown silently ignored the choice and always ran Grok.
            wired = {"grok-imagine", "veo-3.1-fast", "veo-3.1-quality"}
            if not profile or model_id not in wired:
                return {"status": "failed", "error": user_facing(
                    f"'{model_id}' isn't available yet — pick Grok Imagine or Veo 3.1 under Advanced.")}

            where = "video_id = $1 AND tenant_id = $2"
            params = [video_id, self.tenant_id]
            if asset_id:
                where += " AND id = $3"
                params.append(asset_id)
            elif scene is not None:
                where += " AND scene = $3"
                params.append(scene)
            rows = await fetch_all(
                f"SELECT id, scene, image_index, image_url, drive_image_url, video_prompt, "
                f"video_clip_url, duration_seconds, sentence_text, image_prompt "
                f"FROM assets WHERE {where} ORDER BY scene, image_index",
                *params,
            )
            todo = [
                r for r in rows
                if (r.get("image_url") or r.get("drive_image_url"))
                and (force or not r.get("video_clip_url"))
            ]
            if not todo:
                msg = "Nothing to animate — every picture here already has a clip."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id, "message": msg,
                        "clips_generated": 0, "clips_failed": 0, "cost": 0.0}

            label = (f"clip S{todo[0]['scene']}.{todo[0]['image_index']}" if asset_id
                     else f"scene {scene}" if scene is not None else f"{len(todo)} clips")
            await self._log_activity(bot_name, video_id, "started", f"Animating {label} ({model_id})")
            await self._install_cancel_support(video_id)
            should_cancel = self._pipeline.should_cancel

            base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")

            def _proxy_url(url: str) -> str:
                m = _re.search(r"[?&]id=([\w-]+)", url) or _re.search(r"/d/([\w-]+)", url)
                return f"{base}/api/media/drive/{m.group(1)}" if m else url

            from storage import upload_bytes
            from clip_dialogue import (load_dialogue_lines, match_lines, speaking_prompt,
                                       native_speaking_prompt, motion_guard, duck_audio,
                                       download_voice, mux_voice, DIALOGUE_VOICE_LEAD_SECONDS)
            client = self._pipeline.image_client
            durations = [d for d in profile.durations if d in (6, 10)] or [profile.durations[0]]

            # Grok takes up to 7 reference images (@image1, @image2... in the
            # prompt): @image1 = the panel, @image2 = the labeled cast sheet.
            # Same one-sheet conditioning that fixed storyboard character
            # drift; plus the video's style directive goes into every prompt
            # (clips were drifting style on weaker panels).
            sheet = (video.get("character_reference_url") or "").strip()
            style_note = (video.get("image_style_override") or "").strip()[:180]
            # Per-video choice (Ryan: the overlay is OPTIONAL — it "fucked
            # up" this video): grok_native lets Grok voice the exact
            # scripted words itself; voice_over overlays ElevenLabs lines.
            native_voices = (video.get("dialogue_audio") or "voice_over") == "grok_native"
            cast_names = ""
            if (video.get("dialogue_mode") or "") == "character_dialogue":
                name_rows = await fetch_all(
                    "SELECT name FROM video_characters WHERE video_id = $1 ORDER BY sort", video_id)
                cast_names = ", ".join((c["name"] or "").strip() for c in name_rows if c.get("name"))

            def _decorate(core_prompt: str) -> str:
                # @image1 is the GROUND TRUTH for this shot, and the
                # constraints LEAD the prompt (early instructions win — the
                # trailing version still let Grok invent a toddler on a
                # panel that doesn't show Tom). References can only lock
                # characters who are IN the picture; off-screen characters
                # must stay off-screen.
                p = ("Animate @image1 exactly as shown: same characters, same faces, ages,"
                     " heights, proportions and clothing. NEVER introduce a character who"
                     " is not visible in @image1 — if someone is off-screen, only hands or"
                     " feet may enter the frame.")
                if sheet:
                    p += (f" @image2 is the official cast sheet"
                          + (f" ({cast_names})" if cast_names else "")
                          + " — anyone visible in @image1 must match it precisely.")
                if style_note:
                    p += f" Art style: {style_note}"
                p += f" Motion: {core_prompt}"
                return p

            # 💬 cards speak: map this video's tagged dialogue lines to cards.
            # A tap never dead-ends — scenes whose lines aren't voiced yet get
            # their segment voices synthesized first (contract: auto-chain).
            dialogue_by_scene: dict = {}
            if (video.get("dialogue_mode") or "") == "character_dialogue":
                dialogue_by_scene = await load_dialogue_lines(video_id, self.tenant_id)
                # voice_over mode needs the segment voices to exist (auto-
                # chain); grok_native voices the lines itself — no synthesis.
                if (video.get("dialogue_audio") or "voice_over") != "grok_native":
                    unvoiced_scenes = sorted({
                        r["scene"] for r in todo
                        if any(not l.get("audio_url")
                               for l in match_lines(r.get("sentence_text"), dialogue_by_scene.get(r["scene"])))
                    })
                    for sc in unvoiced_scenes:
                        await _report(f"Creating the voices for scene {sc} first…")
                        await self.run_dialogue_voice(video_id, scene=sc, progress_callback=progress_callback)
                    if unvoiced_scenes:
                        dialogue_by_scene = await load_dialogue_lines(video_id, self.tenant_id)

            done = failed = 0
            cost = 0.0
            total = len(todo)
            sem = asyncio.Semaphore(3)
            cancelled = False

            async def _one(r):
                nonlocal done, failed, cost, cancelled
                async with sem:
                    if cancelled:
                        return
                    try:
                        if await should_cancel():
                            cancelled = True
                            return
                    except Exception:
                        pass
                    sc, idx = r["scene"], r["image_index"]
                    img = _proxy_url(r.get("drive_image_url") or r.get("image_url"))
                    lines = [l for l in match_lines(r.get("sentence_text"), dialogue_by_scene.get(sc))
                             if native_voices or l.get("audio_url")]

                    if lines:
                        # Speaking card → Grok animates the FULL SCENE.
                        # Loose sync by design (Ryan's call): scene
                        # continuity beats mouth precision in this format —
                        # see decisions.md 2026-06-12.
                        core = (native_speaking_prompt(lines, r.get("sentence_text"))
                                if native_voices else speaking_prompt(lines))
                        prompt = _decorate(core)
                        voice_secs = sum(float(l.get("duration") or 2.0) for l in lines)
                        # The line (plus its lead) has to fit inside the clip.
                        need = voice_secs + DIALOGUE_VOICE_LEAD_SECONDS
                        clip_dur = (max(durations)
                                    if need > min(durations) - 0.5 and len(durations) > 1
                                    else durations[0])
                        clip_url = await client.generate_video(
                            img, prompt, duration=clip_dur,
                            extra_image_urls=[_proxy_url(sheet)] if sheet else None)
                        clip_cost = profile.cost_per_clip.get(clip_dur, 0.10)
                    else:
                        # Motion prompt from the video-scripts stage; a tapped
                        # card without one still animates (gentle default)
                        # instead of dead-ending.
                        prompt = (r.get("video_prompt") or "").strip() or (
                            "Subtle cinematic motion: gentle camera push-in, soft natural "
                            "movement in the scene. Keep the characters, art style and "
                            "composition exactly as shown.")
                        # People rule (Ryan: S1.4's bird close-up grew an
                        # invented toddler — twice): cutaway cards get an
                        # absolute NO PEOPLE, every other narration card gets
                        # nobody-NEW. Decision table lives in motion_guard.
                        prompt = motion_guard(r.get("image_prompt"),
                                              r.get("sentence_text"), cast_names) + prompt
                        seg_dur = float(r.get("duration_seconds") or 0)
                        clip_dur = max(durations) if seg_dur > 6.0 and len(durations) > 1 else durations[0]
                        if model_id.startswith("veo-3.1"):
                            veo_model = client.VEO_MODEL_QUALITY if model_id.endswith("quality") else client.VEO_MODEL_FAST
                            clip_url = await client.generate_video_veo(prompt, image_url=img, model=veo_model)
                            clip_dur = profile.durations[0]
                        else:
                            clip_url = await client.generate_video(
                                img, _decorate(prompt), duration=clip_dur,
                                extra_image_urls=[_proxy_url(sheet)] if sheet else None)
                        clip_cost = profile.cost_per_clip.get(clip_dur, 0.10)

                    if not clip_url:
                        failed += 1
                        await _report(f"S{sc}.{idx} didn't generate ({done + failed}/{total})")
                        return
                    clip_bytes = await client.download_image(clip_url)
                    # Audio per mode: grok_native keeps Grok's full audio on
                    # speaking cards (its voices + ambience ARE the take);
                    # voice_over lays the ElevenLabs line over a quiet bed.
                    # Narration cards keep quiet ambience either way — the
                    # renderer mixes narration and music over them.
                    try:
                        if lines and not native_voices:
                            vbytes = [b for b in [await download_voice(l["audio_url"]) for l in lines] if b]
                            if vbytes:
                                lead = max(0.0, min(DIALOGUE_VOICE_LEAD_SECONDS,
                                                    float(clip_dur) - voice_secs - 0.1))
                                clip_bytes = await mux_voice(clip_bytes, vbytes,
                                                             delay_seconds=lead, bed_gain=0.2)
                            else:
                                clip_bytes = await duck_audio(clip_bytes)
                        elif not lines and getattr(profile, "strip_audio", False):
                            clip_bytes = await duck_audio(clip_bytes)
                    except Exception as e:
                        print(f"[clips] S{sc}.{idx} audio mux failed, keeping raw clip: {str(e)[:150]}", flush=True)
                    drive_url = await upload_bytes(
                        clip_bytes, f"{video_id}/clips/S{sc:02d}-{idx:02d}.mp4", "video/mp4")
                    await execute(
                        "UPDATE assets SET video_clip_url = $1, video_duration = $2, "
                        "updated_at = now() WHERE id = $3",
                        drive_url, clip_dur, r["id"],
                    )
                    done += 1
                    cost += clip_cost
                    await _report(f"Animated S{sc}.{idx} ({done}/{total} done)")

            await asyncio.gather(*[_one(r) for r in todo])

            if cancelled:
                msg = f"Stopped — kept {done} finished clip(s). Animate again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg, cost=cost)
                return {"status": "cancelled", "video_id": video_id, "error": msg,
                        "clips_generated": done, "clips_failed": failed, "cost": cost}

            # Full untargeted run with everything clipped → stage complete.
            if asset_id is None and scene is None and failed == 0:
                remaining = await fetch_one(
                    "SELECT COUNT(*) AS n FROM assets WHERE video_id = $1 AND tenant_id = $2 "
                    "AND (image_url IS NOT NULL OR drive_image_url IS NOT NULL) AND video_clip_url IS NULL",
                    video_id, self.tenant_id,
                )
                if not (remaining or {}).get("n") and not is_at_or_past_stage(video.get("status"), "ready_for_thumbnail"):
                    await self._update_video_status(video_id, "ready_for_thumbnail")
                    await self._log_transition(video_id, video.get("status"), "ready_for_thumbnail", "api")

            msg = (f"Animated {done} clip(s) (${cost:.2f})"
                   + (f" — {failed} failed, tap them to retry" if failed else ""))
            await self._log_activity(bot_name, video_id, "completed" if not failed else "completed", msg, cost=cost)
            return {"status": "completed" if done or not failed else "failed",
                    "video_id": video_id, "message": msg,
                    "clips_generated": done, "clips_failed": failed, "cost": cost,
                    "error": msg if failed and not done else None}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_split(self, video_id: str) -> dict:
        """Split scene text into timed sentence segments.

        Uses the deterministic splitter with voice duration for accurate WPS.
        Creates asset records with sentence_text, duration, and timing.
        No API calls — pure Python, fast and free.

        Args:
            video_id: Supabase video UUID

        Returns:
            Dict with status, scenes_split, total_segments
        """
        bot_name = "Sentence Splitter"

        try:
            # Import the deterministic splitter
            from shared.clients.deterministic_splitter import segment_scene_deterministic

            # Load scripts with voice for this video
            scripts = await fetch_all(
                "SELECT id, scene, scene_text, voice_over_url, voice_duration_seconds "
                "FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
                "ORDER BY scene",
                video_id, self.tenant_id,
            )

            if not scripts:
                return {"status": "failed", "error": "No scripts found for this video"}

            # Get the video title for asset records
            video = await fetch_one(
                "SELECT video_title FROM videos WHERE id = $1 AND tenant_id = $2",
                video_id, self.tenant_id,
            )
            video_title = video.get("video_title", "") if video else ""

            total_segments = 0
            scenes_split = 0

            for script in scripts:
                scene_num = script.get("scene")
                scene_text = script.get("scene_text")
                voice_duration = script.get("voice_duration_seconds")

                if not scene_text or not scene_text.strip():
                    continue

                # Convert voice_duration to float if present
                if voice_duration is not None:
                    voice_duration = float(voice_duration)

                # Run the deterministic splitter
                segments = segment_scene_deterministic(scene_text, voice_duration)

                if not segments:
                    continue

                # Delete existing assets that don't have images yet (safe re-split)
                # Preserve assets with generated images to avoid data loss
                await execute(
                    "DELETE FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3 "
                    "AND (image_url IS NULL OR image_url = '')",
                    video_id, scene_num, self.tenant_id,
                )
                # Check if scene still has assets with images (skip if so)
                existing = await fetch_one(
                    "SELECT COUNT(*) as cnt FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
                    video_id, scene_num, self.tenant_id,
                )
                if existing and existing.get("cnt", 0) > 0:
                    # Scene has assets with images — skip to avoid duplicates
                    continue

                # Insert new asset records for each segment
                for seg in segments:
                    await execute(
                        """INSERT INTO assets (
                            tenant_id, video_id, video_title, scene,
                            image_index, sentence_index, sentence_text,
                            duration_seconds, status
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                        self.tenant_id, video_id, video_title, scene_num,
                        seg['segment_index'], seg['segment_index'], seg['text'],
                        seg['duration'], 'pending',
                    )

                total_segments += len(segments)
                scenes_split += 1

            await self._log_activity(
                bot_name, video_id, "completed",
                f"Split {total_segments} segments across {scenes_split} scenes",
            )

            return {
                "status": "completed",
                "scenes_split": scenes_split,
                "total_segments": total_segments,
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

    # Statuses that require explicit user approval before running the next stage.
    # "Run Next Step" will NOT auto-advance past these — user must approve in the UI.
    APPROVAL_GATE_STATUSES = {
        "ready_for_voice": "Script & Voice needs approval before proceeding. Generate voice for all scenes, then approve.",
        "ready_for_images": "Visuals need approval before proceeding. Go to the Storyboard & Visuals tab to review and approve.",
        "ready_for_thumbnail": "Thumbnail needs approval before proceeding. Go to the Thumbnail tab to review and approve.",
    }

    async def _run_next_step_status_map(self, video_id: str) -> dict:
        """Original status-driven next step (fallback).

        Runs ONE stage and stops. Respects approval gates — certain statuses
        require explicit user approval before advancing.
        """
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}

        current_status = video.get("status")

        # Check approval gates — block auto-advance at these statuses
        gate_message = self.APPROVAL_GATE_STATUSES.get(current_status)
        if gate_message:
            return {
                "status": "needs_approval",
                "message": gate_message,
            }

        # Map status to handler
        handlers = {
            "idea_logged": self.run_research,
            "approved": self.run_research,
            "ready_for_scripting": self.run_script,
            "ready_for_image_prompts": self.run_prompts,
            "ready_for_storyboards": self.run_storyboard_prompts,
            "ready_for_storyboard_images": self.run_storyboard_images,
            "ready_for_storyboard_extraction": self.run_storyboard_extract,
            "ready_for_sound_design": self.run_sound_prompts,
            "ready_for_sound_effects": self.run_sound_effects,
            "ready_for_video_scripts": self.run_video_scripts,
            "ready_for_video_generation": self.run_video_generation,
            "ready_to_render": self.run_render,
            "rendered": self.run_upload,
        }

        handler = handlers.get(current_status)
        if not handler:
            return {
                "status": "idle",
                "message": f"No action available for status: {current_status}",
            }

        return await handler(video_id)

    async def run_prompts(self, video_id: str, scene: int = None, index: int = None) -> dict:
        """Generate image prompts for a video.

        Args:
            video_id: Supabase video UUID
            scene: Optional scene number for single-scene generation
            index: Optional segment index within a scene for single-segment generation

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()
        bot_name = "Image Prompt Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            # Pipeline integrity check: voice must exist before image prompts (full runs only)
            if scene is None:
                all_voiced, total, voiced = await self._check_voice_exists(video_id)
                if not all_voiced:
                    msg = f"Voice generation must complete before image prompts. Missing voice for {total - voiced}/{total} scenes."
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    await self._update_video_status(video_id, "ready_for_voice")
                    return {"status": "failed", "error": msg}

            current_status = video.get("status")

            # Modeled videos: the Model A Video flow seeds per-scene CONCEPT
            # rows (generation_method='modeled') as inspectable pre-prompts.
            # They carry image_prompt values, so the engine's resume logic sees
            # every scene as "completed" and generates nothing. Clear them on a
            # full run — the pack stays archived in original_dna/research_payload
            # — so the engine builds the real per-scene prompt set (styled via
            # image_style_override, which carries the modeled image DNA).
            if scene is None and video.get("source") == "modeled":
                cleared = await execute(
                    "DELETE FROM assets WHERE video_id = $1 AND tenant_id = $2 "
                    "AND generation_method = 'modeled'",
                    video_id, self.tenant_id,
                )
                print(f"[Prompts] Cleared modeled concept rows before full generation ({cleared})", flush=True)

            if scene is not None and index is not None:
                log_msg = f"Generating prompt for scene {scene} segment {index}"
            elif scene is not None:
                log_msg = f"Generating prompts for scene {scene}"
            else:
                log_msg = "Generating prompts"
            await self._log_activity(bot_name, video_id, "started", log_msg)

            self._load_idea_from_video(video_id)

            # Override status so the bot's internal check passes on re-runs
            if self._pipeline.current_idea:
                self._pipeline.current_idea["Status"] = "Ready For Image Prompts"

            # Set filters for targeted generation
            if scene is not None:
                self._pipeline.scene_filter = scene
            if index is not None:
                self._pipeline.image_filter = index

            result = await self._pipeline.run_styled_image_prompts()

            # Reset filters after run
            self._pipeline.scene_filter = None
            self._pipeline.image_filter = None

            if result.get("error"):
                raise Exception(result["error"])

            # For targeted runs, skip status advancement
            if scene is not None:
                await self._log_activity(bot_name, video_id, "completed", log_msg)
                return {"status": current_status, "video_id": video_id}

            new_status = result.get("new_status", "ready_for_images")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Prompts generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            # Reset filters on error
            self._pipeline.scene_filter = None
            self._pipeline.image_filter = None
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_prompts(self, video_id: str, scene: int = None, progress_callback=None) -> dict:
        """Generate storyboard prompts for a video.

        Args:
            scene: If set, only generate prompts for this scene number.
            progress_callback: Called with (message: str) to report progress.
        """
        await self._ensure_initialized()
        bot_name = "Storyboard Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            scene_label = f" (Scene {scene})" if scene else ""
            await self._log_activity(bot_name, video_id, "started", f"Generating storyboard prompts{scene_label}")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_storyboard_prompts(
                scene_filter=scene,
                progress_callback=progress_callback,
            )

            if result.get("error"):
                raise Exception(result["error"])

            # For per-scene runs, don't advance video status
            if scene is not None:
                await self._log_activity(bot_name, video_id, "completed", f"Scene {scene} prompts generated")
                return {"status": current_status, "video_id": video_id}

            new_status = result.get("new_status", "ready_for_images")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Storyboard director complete — image prompts enriched")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_story_bible(self, video_id: str) -> dict:
        """Generate and persist a Story Bible for a video."""
        await self._ensure_initialized()
        bot_name = "Story Bible Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating Story Bible")

            self._load_idea_from_video(video_id)
            idea = getattr(self._pipeline, "current_idea", None)
            idea_id = getattr(self._pipeline, "current_idea_id", None)
            if not idea or not idea_id:
                raise Exception("Could not load idea for Story Bible generation")

            from storyboard.bot import _generate_story_bible_for_storyboard

            fields = idea.get("fields", idea)
            video_title = fields.get("Video Title", "")
            video_length_min = fields.get("Video Length Min", 10) or 10
            script_records = self._pipeline.airtable.get_scripts_by_title(video_title)
            if not script_records:
                raise Exception(f"No script found for '{video_title}'")

            result = await _generate_story_bible_for_storyboard(
                anthropic_client=self._pipeline.anthropic,
                airtable_client=self._pipeline.airtable,
                idea_id=idea_id,
                video_title=video_title,
                script_records=script_records,
                video_length_min=int(video_length_min),
                slack_client=getattr(self._pipeline, "slack", None),
            )
            if not result:
                raise Exception("Story Bible generation returned empty result")

            await self._log_activity(bot_name, video_id, "completed", "Story Bible generated")
            return {"status": current_status or "ready_for_storyboards", "video_id": video_id}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_images(self, video_id: str, scene: int = None, progress_callback=None) -> dict:
        """Generate storyboard images for a video.

        Args:
            scene: If set, only generate images for this scene number.
            progress_callback: Called with (message: str) to report progress.
        """
        await self._ensure_initialized()
        bot_name = "Storyboard Images Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            scene_label = f" (Scene {scene})" if scene else ""
            await self._log_activity(bot_name, video_id, "started", f"Generating storyboard images{scene_label}")

            self._load_idea_from_video(video_id)

            gate = await self._load_character_refs(video_id, video)
            if gate and scene is None:
                await self._log_activity(bot_name, video_id, "failed", gate)
                return {"status": "failed", "error": gate}

            await self._install_cancel_support(video_id)
            result = await self._pipeline.run_storyboard_images(
                scene_filter=scene,
                progress_callback=progress_callback,
            )

            if result.get("cancelled"):
                kept = result.get("grids_generated", 0)
                msg = f"Stopped — kept {kept} completed grid(s). Run grids again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg}

            if result.get("error"):
                raise Exception(result["error"])

            # Persist temp storyboard grid URLs to Supabase Storage
            persisted = await self._persist_storyboard_urls(video_id)
            if persisted:
                _logger.info("Persisted %d storyboard grid URL(s) to Supabase Storage", persisted)

            # For per-scene runs, don't advance video status
            if scene is not None:
                await self._log_activity(bot_name, video_id, "completed", f"Scene {scene} images generated")
                return {"status": current_status, "video_id": video_id}

            new_status = result.get("new_status", "ready_for_storyboard_extraction")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", f"Storyboard images generated ({persisted} grids persisted)")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_extract(self, video_id: str, progress_callback=None) -> dict:
        """Extract storyboard grid images into individual panels via Supabase Storage.

        Two-pass approach for instant feedback:
        Pass 1 (fast): PIL crop + upload → write to DB immediately (panels appear in UI)
        Pass 2 (slow): AI upscale each panel → update DB with better URL
        """
        await self._ensure_initialized()
        bot_name = "Storyboard Extract Bot"

        async def _report(msg: str):
            if progress_callback:
                try:
                    await progress_callback(msg)
                except Exception:
                    pass

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            # Mandatory storyboard gate: extraction turns approved boards into
            # final images (the paid upscale pass) — locked stories only.
            if not video.get("story_locked_at"):
                msg = user_facing("Lock your story first — review the storyboard grids and hit "
                                  "'Lock story' before extracting panels into final images.")
                await self._log_activity(bot_name, video_id, "failed", msg)
                return {"status": "failed", "error": msg}

            current_status = video.get("status")
            video_title = video.get("video_title", "")
            await self._log_activity(bot_name, video_id, "started", "Extracting storyboard frames")

            scenes = await fetch_all(
                """SELECT id, scene, storyboard_1_url, storyboard_2_url,
                          storyboard_3_url, storyboard_4_url, storyboard_5_url,
                          storyboard_beat_count
                   FROM scripts WHERE video_id = $1 AND tenant_id = $2
                   ORDER BY scene""",
                video_id, self.tenant_id,
            )

            if not scenes:
                raise Exception("No script scenes found for video")

            total_scenes = len([s for s in scenes if any(s.get(f"storyboard_{i}_url") for i in range(1, 6))])
            total_panels = 0
            scene_errors = []
            # Collect panel DB records for upscale pass
            all_panel_records = []  # (asset_id, panel_url, scene, beat, seq)

            # ── Pass 1: Fast crop + upload + write to DB ──
            scenes_done = 0
            for sc in scenes:
                scene_num = sc["scene"]
                beat_urls = []
                for i in range(1, 6):
                    url = sc.get(f"storyboard_{i}_url")
                    if url:
                        beat_urls.append((i, url))

                if not beat_urls:
                    continue

                # Resume: a scene whose every slot already has a final picture
                # is done — re-runs only touch scenes with missing panels.
                slot_rows = await fetch_all(
                    "SELECT image_url FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
                    video_id, scene_num, self.tenant_id,
                )
                if slot_rows and all(r.get("image_url") for r in slot_rows):
                    continue

                # The grids were GENERATED with grid_layout_for(panel_count),
                # slots chunked 9 per beat in order — crop with the same
                # geometry instead of guessing from pixels.
                from extraction import grid_layout_for
                slot_total = len(slot_rows)
                beat_panel_counts = []
                remaining = slot_total
                for _ in beat_urls:
                    take = min(9, remaining) if remaining > 0 else 0
                    beat_panel_counts.append(take)
                    remaining -= take

                scenes_done += 1
                panel_offset = 0
                for bi, (beat_num, grid_url) in enumerate(beat_urls):
                    expected = beat_panel_counts[bi] if bi < len(beat_panel_counts) else 0
                    rows, cols = grid_layout_for(expected) if expected > 0 else (0, 0)
                    try:
                        await _report(f"Extracting Scene {scenes_done}/{total_scenes}, Beat {beat_num}...")
                        # Fast: PIL crop only (no image_client = no upscale)
                        panels = await extract_grid(
                            grid_url, video_id, scene_num, beat_num, panel_offset,
                            rows=rows, cols=cols,
                        )
                        for p in panels:
                            existing = await fetch_one(
                                """SELECT id FROM assets
                                   WHERE video_id = $1 AND scene = $2 AND image_index = $3
                                   AND tenant_id = $4""",
                                video_id, scene_num, p["image_index"], self.tenant_id,
                            )
                            if existing:
                                asset_id = existing["id"]
                                await execute(
                                    """UPDATE assets SET image_url = $1, status = 'done',
                                              generation_method = 'storyboard_extract', updated_at = now()
                                       WHERE id = $2""",
                                    p["panel_url"], asset_id,
                                )
                            else:
                                asset_id = str(uuid.uuid4())
                                await execute(
                                    """INSERT INTO assets
                                       (id, tenant_id, video_id, video_title, scene, image_index,
                                        image_url, status, generation_method, created_at, updated_at)
                                       VALUES ($1, $2, $3, $4, $5, $6, $7, 'done',
                                               'storyboard_extract', now(), now())""",
                                    asset_id, self.tenant_id, video_id, video_title,
                                    scene_num, p["image_index"], p["panel_url"],
                                )
                            total_panels += 1
                            all_panel_records.append((
                                asset_id, p["panel_url"], scene_num, beat_num,
                                p["image_index"],
                            ))
                        panel_offset += len(panels)
                    except Exception as e:
                        scene_errors.append(f"Scene {scene_num} beat {beat_num}: {e}")

            if total_panels == 0 and scene_errors:
                raise Exception(f"All extractions failed: {'; '.join(scene_errors)}")

            # Advance status immediately — panels are visible in UI now
            new_status = "ready_for_images"
            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")

            msg = f"Extracted {total_panels} panels"
            if scene_errors:
                msg += f" ({len(scene_errors)} beat errors skipped)"

            # ── Pass 2: AI upscale (slow, but panels already visible) ──
            # DISABLED by default: nano-banana-2 refuses to regenerate images
            # of children ("Google's Generative AI Prohibited Use policy") —
            # on the bird video ALL 82 upscales were filtered (0 credits, ~40
            # wasted minutes). Until a non-generative upscaler (ESRGAN-class)
            # is wired in, extraction returns the clean crops and the manual
            # "Upscale" action (run_upscale_panels) remains for retries.
            import os as _os
            upscale_enabled = _os.getenv("EXTRACT_AUTO_UPSCALE", "false").lower() == "true"
            image_client = getattr(self._pipeline, "image_client", None) if upscale_enabled else None
            upscaled = 0
            if image_client and all_panel_records:
                await _report(f"Panels extracted! Upscaling {len(all_panel_records)} images...")
                for idx, (asset_id, panel_url, sc_num, bt_num, img_idx) in enumerate(all_panel_records):
                    try:
                        await _report(f"Upscaling Scene {sc_num} Image {img_idx} ({idx + 1}/{len(all_panel_records)})")
                        prompt = (
                            "Upscale this image to high resolution. "
                            "Remove any text labels like [KF1 | LS | 12s], [KF7 | MS | 9s], "
                            "or similar keyframe/shot/duration overlays — cleanly paint over "
                            "them with the surrounding image content. "
                            "Otherwise do NOT alter the image in any way. "
                            "Keep the exact same composition, pose, expression, colors, "
                            "and details. Only increase resolution, clarity, and remove labels."
                        )
                        result = await image_client.generate_scene_image(
                            prompt=prompt,
                            reference_image_url=panel_url,
                        )
                        if result and result.get("url"):
                            path = f"{video_id}/images/S{sc_num}-B{bt_num}-P{img_idx}_hd.png"
                            upscaled_url = await upload_from_url(result["url"], path)
                            await execute(
                                "UPDATE assets SET image_url = $1, updated_at = now() WHERE id = $2",
                                upscaled_url, asset_id,
                            )
                            upscaled += 1
                    except Exception as e:
                        _logger.warning("Upscale failed for panel %d: %s — keeping original", idx, e)

                msg += f", {upscaled}/{len(all_panel_records)} upscaled"

            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": to_supabase(new_status), "video_id": video_id, "panels_extracted": total_panels}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_upscale_panels(self, video_id: str, progress_callback=None) -> dict:
        """Upscale extracted panels that haven't been upscaled yet (no _hd in URL).

        Resumes from where a previous upscale was interrupted.
        """
        await self._ensure_initialized()
        bot_name = "Panel Upscaler"

        async def _report(msg: str):
            if progress_callback:
                try:
                    await progress_callback(msg)
                except Exception:
                    pass

        try:
            image_client = getattr(self._pipeline, "image_client", None)
            if not image_client:
                return {"status": "failed", "error": "No image client available for upscaling"}

            # Find all extracted panels that haven't been upscaled
            raw_panels = await fetch_all(
                """SELECT id, scene, image_index, image_url
                   FROM assets
                   WHERE video_id = $1 AND tenant_id = $2
                   AND generation_method = 'storyboard_extract'
                   AND image_url NOT LIKE '%%_hd.png%%'
                   ORDER BY scene, image_index""",
                video_id, self.tenant_id,
            )

            if not raw_panels:
                return {"status": "completed", "message": "All panels already upscaled"}

            await self._log_activity(bot_name, video_id, "started",
                                     f"Upscaling {len(raw_panels)} panels")
            await _report(f"Upscaling {len(raw_panels)} images — removing KF labels...")

            upscaled = 0
            for idx, panel in enumerate(raw_panels):
                try:
                    await _report(
                        f"Upscaling Scene {panel['scene']} Image {panel['image_index']} "
                        f"({idx + 1}/{len(raw_panels)})"
                    )
                    prompt = (
                        "Upscale this image to high resolution. "
                        "Remove any text labels like [KF1 | LS | 12s], [KF7 | MS | 9s], "
                        "or similar keyframe/shot/duration overlays — cleanly paint over "
                        "them with the surrounding image content. "
                        "Otherwise do NOT alter the image in any way. "
                        "Keep the exact same composition, pose, expression, colors, "
                        "and details. Only increase resolution, clarity, and remove labels."
                    )
                    result = await image_client.generate_scene_image(
                        prompt=prompt,
                        reference_image_url=panel["image_url"],
                    )
                    if result and result.get("url"):
                        path = f"{video_id}/images/S{panel['scene']}-I{panel['image_index']}_hd.png"
                        upscaled_url = await upload_from_url(result["url"], path)
                        await execute(
                            "UPDATE assets SET image_url = $1, updated_at = now() WHERE id = $2",
                            upscaled_url, panel["id"],
                        )
                        upscaled += 1
                except Exception as e:
                    _logger.warning("Upscale failed S%d I%d: %s", panel["scene"], panel["image_index"], e)

            msg = f"Upscaled {upscaled}/{len(raw_panels)} panels"
            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": "completed", "message": msg, "upscaled": upscaled}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_images(self, video_id: str, scene: int = None, index: int = None) -> dict:
        """Generate images for a video.

        Args:
            video_id: Supabase video UUID
            scene: Optional scene number for single-scene generation
            index: Optional segment index within a scene for single-image generation
        """
        await self._ensure_initialized()
        bot_name = "Image Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")

            # Full runs require voice completion; targeted re-runs bypass the stage gate.
            if scene is None:
                all_voiced, total, voiced = await self._check_voice_exists(video_id)
                if not all_voiced:
                    msg = f"Voice generation must complete before image generation. Missing voice for {total - voiced}/{total} scenes."
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    await self._update_video_status(video_id, "ready_for_voice")
                    return {"status": "failed", "error": msg}

            if scene is not None and index is not None:
                log_msg = f"Generating image for scene {scene} segment {index}"
            elif scene is not None:
                log_msg = f"Generating images for scene {scene}"
            else:
                log_msg = "Generating images"
            await self._log_activity(bot_name, video_id, "started", log_msg)

            self._load_idea_from_video(video_id)

            # Override status so the bot's internal check passes on re-runs
            if self._pipeline.current_idea:
                self._pipeline.current_idea["Status"] = "Ready For Images"

            # Targeted re-generation hooks already exist in the underlying pipeline.
            if scene is not None:
                self._pipeline.scene_filter = scene
            if index is not None:
                self._pipeline.image_filter = index

            # For targeted runs, reset matching assets to 'pending' so the image bot picks them up.
            # Assets may be in 'approved' status (from storyboard approval) with no image_url.
            if scene is not None:
                reset_sql = "UPDATE assets SET status = 'pending' WHERE video_id = $1 AND scene = $2 AND image_url IS NULL"
                reset_params = [video_id, scene]
                if index is not None:
                    reset_sql += " AND image_index = $3"
                    reset_params.append(index)
                await execute(reset_sql, *reset_params)

            # Mandatory storyboard gate: image spend only happens on a story
            # the creator reviewed and explicitly locked. Targeted single-image
            # regens bypass (they're post-lock fixes by definition).
            if scene is None and not video.get("story_locked_at"):
                msg = user_facing("Lock your story first — review the storyboard grids and hit "
                                  "'Lock story' on the Storyboard tab before generating images.")
                await self._log_activity(bot_name, video_id, "failed", msg)
                return {"status": "failed", "error": msg}

            gate = await self._load_character_refs(video_id, video)
            if gate and scene is None:
                await self._log_activity(bot_name, video_id, "failed", gate)
                return {"status": "failed", "error": gate}

            await self._install_cancel_support(video_id)
            result = await self._pipeline.run_image_bot()

            # Always reset filters after run
            self._pipeline.scene_filter = None
            self._pipeline.image_filter = None

            if result.get("cancelled"):
                kept = result.get("image_count", 0)
                await self._persist_asset_urls(video_id)
                msg = f"Stopped — kept {kept} completed image(s). Run Images again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg}

            if result.get("error"):
                raise Exception(result["error"])

            # Persist temp image URLs to Supabase Storage
            persisted = await self._persist_asset_urls(video_id)
            if persisted:
                _logger.info("Persisted %d image URL(s) to Supabase Storage", persisted)

            # For targeted runs, keep the current video status stable.
            if scene is not None:
                await self._log_activity(bot_name, video_id, "completed", log_msg)
                return {"status": current_status, "video_id": video_id}

            new_status = result.get("new_status", "ready_for_thumbnail")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", f"Images generated ({persisted} persisted to storage)")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            self._pipeline.scene_filter = None
            self._pipeline.image_filter = None
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_image_variants(self, video_id: str, scene: int, index: int, variants: int = 3) -> dict:
        """Generate image variants for a single scene/index without affecting primary assets."""
        await self._ensure_initialized()
        bot_name = "Image Variant Bot"

        if not self._pipeline.image_client:
            return {"status": "failed", "error": "Image client not available"}

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            asset = await fetch_one(
                """SELECT id, sentence_index, sentence_text, image_prompt, shot_type, hero_shot
                   FROM assets
                   WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 AND image_index = $4
                     AND (generation_method IS NULL OR generation_method <> 'variant_candidate')
                   ORDER BY created_at
                   LIMIT 1""",
                video_id, self.tenant_id, scene, index,
            )
            if not asset:
                return {"status": "failed", "error": f"Base asset not found for scene {scene} image {index}"}

            prompt = asset.get("image_prompt")
            if not prompt:
                return {"status": "failed", "error": "Base asset has no image prompt"}

            await self._log_activity(
                bot_name,
                video_id,
                "started",
                f"Generating {variants} variant(s) for scene {scene} image {index}",
            )

            self._load_idea_from_video(video_id)

            from orchestrator.pipeline_constants import Models
            from shared.clients.image_client import ImageClient
            from shared.clients.airtable_client import get_image_model_override

            model_override = get_image_model_override(self._pipeline.current_idea or {})
            if model_override and model_override not in ImageClient.VALID_SCENE_MODELS:
                model_override = ""

            use_reference = bool(self._pipeline.core_image_url) and model_override != Models.IMAGE_ZIMAGE

            existing = await fetch_one(
                """SELECT COALESCE(MAX(panel_position), 0) AS max_variant
                   FROM assets
                   WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 AND image_index = $4
                     AND generation_method = 'variant_candidate'""",
                video_id, self.tenant_id, scene, index,
            )
            next_variant_position = int(existing.get("max_variant") or 0) + 1
            created = 0

            for offset in range(variants):
                if model_override == Models.IMAGE_ZIMAGE:
                    result = await self._pipeline.image_client.generate_scene_image_zimage(prompt, aspect_ratio="16:9")
                elif use_reference:
                    result = await self._pipeline.image_client.generate_scene_image(prompt, self._pipeline.core_image_url)
                else:
                    result_urls = await self._pipeline.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                    result = {"url": result_urls[0]} if result_urls else None

                if not result or not result.get("url"):
                    continue

                image_url = result["url"]
                # Persist variant to Supabase Storage
                variant_path = f"{video_id}/images/S{scene}-{index}-v{next_variant_position + offset}.png"
                image_url = await self._persist_url(image_url, variant_path)

                drive_download_url = None
                try:
                    image_content = await self._pipeline.image_client.download_image(image_url)
                    filename = (
                        f"Scene_{str(scene).zfill(2)}_{str(index).zfill(2)}"
                        f"_variant_{str(next_variant_position + offset).zfill(2)}.png"
                    )
                    drive_file = self._pipeline.google.upload_image(
                        image_content, filename, self._pipeline.project_folder_id
                    )
                    if drive_file and drive_file.get("id"):
                        drive_download_url = self._pipeline.google.make_file_public(drive_file["id"])
                except Exception as drive_err:
                    print(f"      ⚠️ Variant Drive upload failed: {drive_err}", flush=True)

                await execute(
                    """INSERT INTO assets (
                        id, tenant_id, video_id, video_title, scene, image_index, sentence_index,
                        sentence_text, image_prompt, shot_type, hero_shot, image_url, drive_image_url,
                        status, generation_method, panel_position, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7,
                        $8, $9, $10, $11, $12, $13,
                        $14, $15, $16, now(), now()
                    )""",
                    str(uuid.uuid4()),
                    self.tenant_id,
                    video_id,
                    video.get("video_title"),
                    scene,
                    index,
                    asset.get("sentence_index") or index,
                    asset.get("sentence_text"),
                    prompt,
                    asset.get("shot_type"),
                    asset.get("hero_shot") or False,
                    image_url,
                    drive_download_url,
                    "done",
                    "variant_candidate",
                    next_variant_position + offset,
                )
                created += 1

            if created == 0:
                raise Exception("No image variants were generated successfully")

            await self._log_activity(
                bot_name,
                video_id,
                "completed",
                f"Generated {created} variant(s) for scene {scene} image {index}",
            )
            return {"status": video.get("status"), "video_id": video_id, "variants_created": created}

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

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

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

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

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

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

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

            await self._install_cancel_support(video_id)
            result = await self._pipeline.run_video_gen_bot()

            if result.get("cancelled"):
                kept = result.get("video_count", 0)
                msg = f"Stopped — kept {kept} completed clip(s). Run clip generation again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg}

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

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_thumbnail_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "done")

            # Save thumbnail URL back to videos table (persist to Supabase Storage)
            thumbnail_url = result.get("thumbnail_url")
            if thumbnail_url:
                thumbnail_url = await self._persist_url(
                    thumbnail_url, f"{video_id}/thumbnails/thumb.png"
                )
                await execute(
                    "UPDATE videos SET thumbnail_url = $1, updated_at = now() WHERE id = $2",
                    thumbnail_url, video_id,
                )

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

            try:
                from routes.billing import increment_usage
                duration = video.get("video_length_minutes") or 10
                await increment_usage(self.tenant_id, "render_minutes", duration)
            except Exception:
                pass

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_upload(self, video_id: str) -> dict:
        """Generate SEO metadata and upload video to YouTube as unlisted draft."""
        await self._ensure_initialized()
        bot_name = "YouTube Upload Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Uploading to YouTube")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_upload_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "Uploaded (Draft)")

            # Update with YouTube URL if available
            video_url = result.get("video_url")
            if video_url:
                await execute(
                    "UPDATE videos SET youtube_url = $1 WHERE id = $2",
                    video_url, video_id,
                )

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Video uploaded to YouTube")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}
