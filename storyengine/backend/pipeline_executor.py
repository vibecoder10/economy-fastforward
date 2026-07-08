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
from status_map import to_supabase, to_pipeline, get_bot_name, STAGE_BOT_MAP, is_at_or_past_stage, resolve_planned_status
from vault import get_secret
from extraction import extract_grid
from storage import upload_from_url
import engine_templates
from identity import IdentityContext, build_identity_context

import logging
_logger = logging.getLogger(__name__)


def _unit_display_name(item: Any) -> str:
    """Normalize a research unit_roster entry into a human-readable name."""
    if isinstance(item, dict):
        name = str(item.get("name") or item.get("title") or "").strip()
        designation = str(item.get("designation") or item.get("code") or "").strip()
        if name and designation and designation.lower() not in name.lower():
            return f"{designation} {name}".strip()
        return name or designation
    return str(item or "").strip()


def _unit_code(text: str) -> str:
    """Extract the short machine/unit code that DvsU-style rosters hinge on."""
    import re
    s = str(text or "").upper().replace("–", "-").replace("—", "-")
    # Prefer explicit bomber/aircraft designations, then fall back to compact tokens.
    for pat in (
        r"\b(?:X?Y?B|FB)-?\d{1,3}[A-Z]?\b",  # XB-70, YB-40, B-52H, FB-111A
        r"\b[A-Z]{1,4}-\d{1,4}[A-Z]?\b",
    ):
        m = re.search(pat, s)
        if m:
            return m.group(0).replace(" ", "")
    words = re.findall(r"[A-Z0-9]+", s)
    return " ".join(words[:4])


def _title_needs_complete_roster(title: str) -> bool:
    import re
    t = str(title or "").strip().lower()
    return bool(re.search(r"\b(every|all)\b", t) or "ever built" in t or "complete" in t)


def _title_is_broad_machine_roster(title: str) -> bool:
    """True for titles where a short shortlist is almost certainly wrong."""
    import re
    t = str(title or "").strip().lower()
    machine_terms = (
        "aircraft", "bomber", "fighter", "jet", "plane", "tank", "ship",
        "submarine", "helicopter", "missile", "weapon", "vehicle", "machine",
    )
    broad_terms = ("us ", "u.s.", "american", "soviet", "russian", "british", "german", "strategic")
    return (
        _title_needs_complete_roster(t)
        and any(term in t for term in machine_terms)
        and ("ever built" in t or any(term in t for term in broad_terms) or bool(re.search(r"\bevery\b", t)))
    )


def _payload_blob(payload: Any) -> str:
    import json
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return str(payload or "")


def _roster_validation(title: str, payload: dict, script_units: Optional[list[str]] = None) -> dict:
    """Validate the research/script roster contract without adding DB columns.

    Stored into research_payload/script_validation so the UI can show the same
    truth Ryan just caught manually: a complete-title video cannot silently run
    on a curated shortlist.
    """
    roster_raw = payload.get("unit_roster") if isinstance(payload, dict) else None
    roster = [_unit_display_name(x) for x in (roster_raw or [])]
    roster = [x for x in roster if x]
    roster_codes = [_unit_code(x) for x in roster if _unit_code(x)]
    contract = str((payload or {}).get("roster_contract") or "") if isinstance(payload, dict) else ""
    counter = str((payload or {}).get("counter_arguments") or "") if isinstance(payload, dict) else ""
    audit = payload.get("roster_audit") if isinstance(payload, dict) else None
    if not isinstance(audit, dict):
        audit = {}
    complete_title = _title_needs_complete_roster(title)

    warnings: list[str] = []
    gaps: list[str] = []
    lower = f"{contract}\n{counter}".lower()
    if complete_title and not roster:
        warnings.append("This title promises a complete roster, but research_payload.unit_roster is missing.")
    if complete_title and len(roster) < 3:
        warnings.append(f"Complete-roster title has only {len(roster)} roster item(s); likely incomplete.")
    if _title_is_broad_machine_roster(title) and len(roster) < 15:
        warnings.append(
            f"Broad machine-roster title has only {len(roster)} item(s); likely a shortlist, not the full title promise."
        )
    if any(term in lower for term in ("incomplete", "not included", "isn't included", "missing", "misleading", "should either be narrowed", "research expanded")):
        warnings.append("Research payload admits the roster/title may be incomplete or narrowed.")
    if complete_title:
        queries = audit.get("search_queries_used") or []
        families = audit.get("source_families_crosschecked") or []
        unresolved = audit.get("unresolved_candidates") or []
        confidence = str(audit.get("confidence") or "").strip().lower()
        if not audit:
            warnings.append("Complete-roster research is missing roster_audit proof of exhaustive search.")
        elif len(queries) < 6:
            warnings.append("Complete-roster research used fewer than 6 distinct roster-discovery searches.")
        if audit and len(families) < 3:
            warnings.append("Complete-roster research cross-checked fewer than 3 source families.")
        if audit and unresolved:
            warnings.append(f"Complete-roster research still has {len(unresolved)} unresolved candidate(s).")
        if audit and confidence and confidence != "high":
            warnings.append(f"Complete-roster audit confidence is {confidence}, not high.")
        if isinstance(unresolved, list):
            for item in unresolved:
                name = _unit_display_name(item)
                code = _unit_code(name)
                if code and code not in roster_codes and code not in gaps:
                    gaps.append(code)
    # Pull explicit designations from caveats so the UI can name the likely gaps.
    import re
    for code in re.findall(r"\b(?:X?Y?B|FB)-?\d{1,3}[A-Z]?\b", f"{contract}\n{counter}", flags=re.I):
        norm = code.upper().replace(" ", "")
        if norm not in roster_codes and norm not in gaps:
            gaps.append(norm)

    script_missing: list[str] = []
    script_extra: list[str] = []
    if script_units is not None and roster_codes:
        script_blob = "\n".join(script_units)
        script_codes = [_unit_code(u) for u in script_units if _unit_code(u)]
        for name, code in zip(roster, roster_codes):
            if code and code not in script_blob.upper():
                script_missing.append(name)
        for code in script_codes:
            if code and code not in roster_codes and code not in script_extra:
                script_extra.append(code)
        if script_missing:
            warnings.append(f"Script omitted {len(script_missing)} roster item(s).")
        if script_extra:
            warnings.append(f"Script added {len(script_extra)} item(s) outside the locked roster.")

    return {
        "passed": len(warnings) == 0,
        "complete_title": complete_title,
        "roster_count": len(roster),
        "roster": roster,
        "warnings": warnings,
        "gaps": gaps,
        "script_missing": script_missing,
        "script_extra": script_extra,
    }


def resolve_prompt(
    per_video: Optional[str],
    tenant: Optional[str],
    prompt_key: str,
    identity: "IdentityContext",
) -> Optional[str]:
    """Resolve a single system prompt for one pipeline stage. PURE + testable.

    Precedence: per-video override > tenant override > neutral engine template.
    The neutral fallback is `engine_templates.render(prompt_key, identity)` IF
    that key has a template; otherwise None (keys without a template — e.g.
    sound_curation / sound_generation — keep None so the bot's own neutral
    default is used).

    Whatever is chosen (override OR template), the identity placeholders are
    filled via `engine_templates.safe_fill` so the channel's identity is
    injected in every path while foreign braces ({HEADLINE}, {{x}}, …) survive
    verbatim. Phase 1 invariant: a tenant with a custom override still gets
    that override — we only fill identity slots and never overwrite it.

    Returns the resolved prompt string, or None when there's nothing to set
    (so the bot falls back to its built-in default).
    """
    def _nonblank(v):
        # Treat None and whitespace-only strings as "no override" so a blank
        # override falls through to the next source rather than producing an
        # empty prompt (mirrors identity.py's blank-is-missing philosophy).
        return v if (isinstance(v, str) and v.strip()) else None

    neutral = engine_templates.render(prompt_key, identity)  # "" if no template
    chosen = _nonblank(per_video) or _nonblank(tenant) or _nonblank(neutral)
    if chosen:
        return engine_templates.safe_fill(chosen, identity)
    return None


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
            # Narrator voice configuration (not API keys, same vault->env seam).
            # Without these the tenant's configured narrator voice/model is
            # silently ignored and every channel gets the process default —
            # seen live on DvsU 2026-07-07 (fixed voice is part of that brand).
            "elevenlabs_voice_id",
            "elevenlabs_model_id",
            "elevenlabs_voice_style",
            "kie_ai_api_key",
            "openai_api_key",
            "gemini_api_key",
        ]
        # Voice-config keys have a legitimate process-level default in the
        # service .env (legacy single-tenant behavior). Snapshot those before
        # clearing so a tenant WITHOUT a vault override keeps the .env value
        # instead of silently dropping to the hardcoded default voice.
        VOICE_CONFIG_KEYS = ("elevenlabs_voice_id", "elevenlabs_model_id", "elevenlabs_voice_style")
        process_voice_defaults = {
            k.upper(): os.environ[k.upper()]
            for k in VOICE_CONFIG_KEYS
            if k.upper() in os.environ
        }
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

        # Restore process-level voice defaults for keys no tenant override set.
        for env_name, value in process_voice_defaults.items():
            if not os.environ.get(env_name):
                os.environ[env_name] = value
                print(f"[INIT]   ↩ {env_name} restored from process env (no tenant override)", flush=True)

        # Claude runs on DIRECT Anthropic (the tenant's anthropic_api_key loaded
        # above) — it's the reliable path. Kie is ONLY a fallback for Claude when a
        # tenant has no Anthropic key (the Kie gateway 500s/hangs and drops image
        # blocks). Images/video always use Kie. On fallback, AnthropicClient reads
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
            # Point the title→id adapter at THIS exact video so script scene
            # reads/writes can't misroute to a duplicate-titled video (the
            # adapter otherwise resolves by title with LIMIT 1).
            try:
                self._pipeline.airtable.current_video_id = idea.get("id")
            except Exception:
                pass
            # Style-agnostic default; an explicit tenant choice still wins.
            visual_style = idea.get(IdeaFields.VISUAL_STYLE) or "neutral_v1"
            self._pipeline.visual_style = visual_style
            # The skill pipeline resolves the visual profile via this env var
            # (load_profile() reads VISUAL_PROFILE). The backend's _load_idea
            # override never set it before, so every tenant silently got the
            # registry default — set it here so the tenant's chosen profile is
            # honored and an unset tenant gets the neutral engine.
            os.environ["VISUAL_PROFILE"] = visual_style
            # Per-run RESET of the channel look (the neutral profile injects it
            # at build time). Set unconditionally so a previous tenant's value
            # can never leak in. The per-video override is the floor here; the
            # image stages upgrade this to the full identity look (which falls
            # back to the channel's style_description) via _export_visual_style.
            os.environ["VISUAL_STYLE_DESCRIPTION"] = (
                idea.get(IdeaFields.IMAGE_STYLE_OVERRIDE) or ""
            ).strip()
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

    @staticmethod
    def _enabled_stages(video: Optional[dict]) -> Optional[list]:
        """The video's per-video stage plan (list of enabled stage keys), or
        None for 'run the full pipeline'. Reads the pipeline_stages JSONB column,
        tolerating either a parsed list or a JSON string (asyncpg returns JSONB
        as a str unless a codec is set)."""
        if not video:
            return None
        raw = video.get("pipeline_stages")
        if raw is None:
            return None
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except Exception:
                return None
        if isinstance(raw, list) and raw:
            return raw
        return None

    @staticmethod
    def _skip_disabled_next(video: dict, natural_next: str) -> str:
        """Given a stage's natural next status, reroute it to honor this video's
        stage plan: skip stages the creator turned off, and return 'done' once
        the plan has no more enabled work.

        When the video has no explicit plan (pipeline_stages NULL) this falls
        back to the original skip_voice-only behavior, so existing videos are
        unaffected."""
        stages = PipelineExecutor._enabled_stages(video)
        if stages:
            return resolve_planned_status(natural_next, stages)
        if natural_next == "ready_for_voice" and video.get("skip_voice"):
            return "ready_for_image_prompts"
        return natural_next

    def _load_idea_from_video(self, video_id: str):
        """Load idea into pipeline state from Supabase video UUID.

        Uses the SupabaseAdapter which returns Airtable-shaped dicts.
        """
        idea = self._pipeline.airtable.get_idea(video_id)
        if idea:
            self._pipeline._load_idea(idea)
        else:
            print(f"[WARN] Could not load idea for video_id={video_id}", flush=True)

    async def _export_visual_style(self, video: dict) -> None:
        """Export the channel LOOK to the skill image pipeline.

        The neutral default visual profile declares no medium of its own;
        image_prompts/prompt_builder.py reads ``VISUAL_STYLE_DESCRIPTION`` and
        front-loads it into every image prompt (a per-video image_style_override
        still wins). Skills can't import the backend, so this env var is the
        seam — mirroring ``VISUAL_PROFILE``.

        The image stages (run_prompts / run_images / storyboard) do NOT go
        through ``_load_prompt_overrides`` (which is where text stages set this),
        so they call this directly. Set unconditionally so a previous tenant's
        value can never leak into this run.
        """
        try:
            identity = await build_identity_context(self.tenant_id, video)
            os.environ["VISUAL_STYLE_DESCRIPTION"] = identity.visual_style or ""
        except Exception as e:  # never let look resolution break a run
            _logger.warning("export visual style failed; using per-video override: %s", e)
            os.environ["VISUAL_STYLE_DESCRIPTION"] = (
                (video or {}).get("image_style_override") or ""
            ).strip()

    async def _check_voice_exists(self, video_id: str) -> tuple[bool, int, int]:
        """Check if voice has been generated for all scenes.

        A scene is voiced when its narrator track exists (scripts.voice_over_url)
        OR when dialogue-voice finished every spoken line (each dialogue_segments
        entry with text carries its own audio_url). All-dialogue scenes never get
        a narrator track, so voice_over_url alone would reject them forever.

        Returns (all_have_voice, total_scenes, scenes_with_voice).
        """
        from dialogue_voice import _as_segments

        rows = await fetch_all(
            "SELECT voice_over_url, dialogue_segments FROM scripts WHERE video_id = $1",
            video_id,
        )
        total = len(rows)
        with_voice = 0
        for r in rows:
            if r.get("voice_over_url"):
                with_voice += 1
                continue
            segments = _as_segments(r.get("dialogue_segments"))
            if segments and all(
                seg.get("audio_url")
                for seg in segments
                if (seg.get("text") or "").strip()
            ):
                with_voice += 1
        return (total > 0 and with_voice == total), total, with_voice

    async def _update_video_status(self, video_id: str, new_status: str, video: Optional[dict] = None):
        """Update video status in Supabase, honoring the video's stage plan.

        If the creator restricted this video to a subset of stages, a forward
        advance is rerouted to the next enabled stage — or to 'done' when the
        plan has no more enabled work. Videos with no plan (pipeline_stages NULL,
        i.e. every existing video and every full run) are unaffected: the status
        is written exactly as given. This is the single chokepoint every stage
        uses to advance, so the creator's on/off switches are honored everywhere.

        Args:
            video_id: Supabase video UUID
            new_status: New status in Supabase format
            video: Optional already-loaded video row (avoids a re-fetch)
        """
        if new_status != "done":
            v = video if video is not None else await self._get_video(video_id)
            stages = self._enabled_stages(v)
            if stages:
                new_status = resolve_planned_status(new_status, stages)
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

        Priority: per-video override > tenant override > neutral engine template
        (filled with the channel's IdentityContext). Keys without an engine
        template (sound_curation / sound_generation) fall through to None so the
        bot uses its own built-in default.

        Phase 1 invariant: a tenant that already has a custom override still gets
        that override — we only inject identity placeholders into it; we never
        replace it with the neutral template. Behavior only changes where there
        was NO override before (previously None, now a neutral identity-filled
        prompt).

        Sets pipeline attributes like `script_system_prompt`, `thumbnail_system_prompt`,
        etc. that bots read via `getattr(pipeline, '<key>_system_prompt', None)`.

        Args:
            video: Video row dict from Supabase (contains per-video override columns).
        """
        # Mapping: tenant prompt_key -> (video column, pipeline attribute)
        # NOTE: `title` is intentionally left out for now — Phase 3 wires it.
        PROMPT_MAP = {
            "script":           ("script_system_prompt",       "script_system_prompt"),
            "thumbnail":        ("thumbnail_system_prompt",    "thumbnail_system_prompt"),
            "video_motion":     ("video_motion_system_prompt", "video_motion_system_prompt"),
            "sound_curation":   ("sound_system_prompt",        "sound_curation_system_prompt"),
            "sound_generation": ("sound_system_prompt",        "sound_generation_system_prompt"),
            "research":         (None,                         "research_system_prompt"),
        }

        # Build the channel identity once for this run (defensive — never raises).
        self._identity = await build_identity_context(self.tenant_id, video)

        # Export the channel's LOOK to the skill pipeline. The neutral visual
        # profile declares no medium of its own; image_prompts/prompt_builder.py
        # reads VISUAL_STYLE_DESCRIPTION and front-loads it into every image
        # prompt (per-video image_style_override still wins). Skills can't import
        # the backend, so this env var is the seam (mirrors VISUAL_PROFILE).
        os.environ["VISUAL_STYLE_DESCRIPTION"] = self._identity.visual_style or ""

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

        # Resolve each prompt: per-video > tenant > neutral identity template.
        for prompt_key, (video_col, pipeline_attr) in PROMPT_MAP.items():
            # Per-video override (if column exists on the videos table)
            per_video = video.get(video_col) if video_col else None
            # Tenant override
            tenant = tenant_overrides.get(prompt_key)
            resolved = resolve_prompt(per_video, tenant, prompt_key, self._identity)
            setattr(self._pipeline, pipeline_attr, resolved)

        # Channel thumbnail formula: when the identity builder extracted a
        # repeatable thumbnail_style from the channel's own top videos (vision
        # pass, channel_profiles.channel_identity), every generated thumbnail
        # must match that formula — it's the channel's visual brand. Appended
        # (never replacing) so custom overrides keep working.
        try:
            row = await fetch_one(
                "SELECT channel_identity->'thumbnail_style' AS ts "
                "FROM channel_profiles WHERE tenant_id = $1", self.tenant_id)
            ts = (row or {}).get("ts")
            if isinstance(ts, str):
                import json as _json_ts
                ts = _json_ts.loads(ts)
            if isinstance(ts, dict) and ts:
                base = getattr(self._pipeline, "thumbnail_system_prompt", None) or ""
                import json as _json_ts
                formula = _json_ts.dumps(ts, indent=2)
                setattr(
                    self._pipeline, "thumbnail_system_prompt",
                    base + "\n\nCHANNEL THUMBNAIL FORMULA (extracted from this "
                    "channel's own top-performing thumbnails — match its style, "
                    "text treatment, composition and mood; the composition itself "
                    "must still be fresh for this video):\n" + formula,
                )
        except Exception as e:
            _logger.warning("thumbnail formula injection skipped: %s", e)

        # Slop-proofing (anti-demonetization), baked into the prompts:
        #   - SCRIPT: Wall 1 (a real point of view) + Wall 2 (a genuinely NEW
        #     PLOT vs this channel's recent videos), so every video tells a
        #     different story by construction.
        #   - THUMBNAIL: keep the channel's STYLE consistent (that is brand), but
        #     never reuse a TEMPLATE — force a new composition vs recent thumbs.
        # The look/format/title style may repeat; the plot and the thumbnail
        # composition may not. History-aware, invisible to the creator, never a
        # gate. Applies on top of whatever was resolved above (custom override OR
        # neutral template). Fully defensive: any failure leaves prompts as-is,
        # and the always-on mandates (point of view, anti-template) still land
        # even if the history read fails. See backend/originality.py.
        try:
            import originality
            try:
                recent_fps = await originality.load_recent_fingerprints(
                    self.tenant_id,
                    exclude_video_id=str(video["id"]) if video.get("id") else None,
                )
            except Exception as e:
                _logger.warning("recent fingerprints unavailable: %s", e)
                recent_fps = []
            # Hand the recent PLOTS to the skill side (Phase 2 silent re-roll in
            # script/brief_translator) over the same env-var seam used for
            # VISUAL_STYLE_DESCRIPTION. Always set (even "[]") so a previous
            # video's plots never leak into this run.
            try:
                import json as _json
                _slim = [
                    {"title": f.get("title", ""),
                     "plot": f.get("script_excerpt") or f.get("hook") or ""}
                    for f in recent_fps
                ]
                os.environ["RECENT_PLOTS_JSON"] = _json.dumps(_slim)
            except Exception:
                os.environ["RECENT_PLOTS_JSON"] = "[]"
            for kind, attr in (
                ("script", "script_system_prompt"),
                ("thumbnail", "thumbnail_system_prompt"),
            ):
                base = getattr(self._pipeline, attr, None)
                if not base:
                    continue
                extra = originality.build_generation_guardrails(kind, recent_fps)
                if extra:
                    setattr(self._pipeline, attr, base + "\n\n" + extra)
        except Exception as e:
            _logger.warning("originality guardrails skipped: %s", e)

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

    async def _load_environment_refs(self, video_id: str, video: dict):
        """Load approved location references onto the pipeline as a
        {location_id: reference_url} map. Mirrors the character gate: returns an
        error string when environments exist but aren't approved; None otherwise.
        Videos that never designed environments skip it entirely (opt-in)."""
        try:
            rows = await fetch_all(
                "SELECT name, reference_url FROM video_environments "
                "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
                "ORDER BY sort, created_at",
                video_id, self.tenant_id,
            )
        except Exception:
            rows = []
        if not rows:
            self._pipeline.environment_reference_urls = None
            return None
        if not video.get("environments_approved_at"):
            self._pipeline.environment_reference_urls = None
            return user_facing("Your environments are designed but not approved yet — open the "
                               "Environments tab, review them, and hit Approve before generating grids.")
        self._pipeline.environment_reference_urls = {
            r["name"]: r["reference_url"] for r in rows if r.get("name") and r.get("reference_url")
        }
        return None

    async def _environments_ready_gate(self, video_id: str, video: dict) -> Optional[str]:
        """Storyboards require the environments step to be DONE — either
        approved (locations locked) or explicitly skipped ("No locations" stamps
        environments_approved_at with no rows). Returns an error string to block,
        or None to allow. Applies to bulk AND per-scene generation, so the
        creator can't sail past environment design unintentionally."""
        if video.get("environments_approved_at"):
            return None
        try:
            row = await fetch_one(
                "SELECT count(*) AS n FROM video_environments WHERE video_id = $1 AND tenant_id = $2",
                video_id, self.tenant_id,
            )
            n = (row or {}).get("n") or 0
        except Exception:
            n = 0
        if n > 0:
            return user_facing(
                "Approve your environments first — open the Environments tab, review the "
                "locations, and hit Approve before generating storyboards."
            )
        return user_facing(
            "Design your environments first — open the Environments tab and design the "
            "locations (or hit “No locations — skip” if this video has none) before "
            "generating storyboards."
        )

    async def _persist_url(self, source_url: str, storage_path: str) -> str:
        """Re-upload a temporary URL to Google Drive for permanent access.

        Returns the permanent URL, or the original URL if upload fails or URL is already permanent.
        """
        if not source_url:
            return source_url
        if "drive.google.com" in source_url or "supabase.co/storage" in source_url:
            return source_url
        try:
            return await upload_from_url(source_url, storage_path, tenant_id=self.tenant_id)
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

            # Feed the channel's OWN research approach (extracted from its top
            # videos by the identity builder) into the research context, so the
            # agent looks for what this channel's format actually needs (e.g.
            # DVU: program designations, unit costs, cancellation dates).
            research_context = None
            try:
                row = await fetch_one(
                    "SELECT channel_identity->'research_approach' AS ra "
                    "FROM channel_profiles WHERE tenant_id = $1", self.tenant_id)
                ra = (row or {}).get("ra")
                if isinstance(ra, str) and ra.strip().startswith(("{", "[", '"')):
                    import json as _json_ra
                    try:
                        ra = _json_ra.loads(ra)
                    except ValueError:
                        pass
                if ra:
                    research_context = (
                        "THIS CHANNEL'S RESEARCH APPROACH (match it — these are "
                        "the facts its videos are built from):\n"
                        + (ra if isinstance(ra, str) else str(ra))
                    )
            except Exception:  # noqa: BLE001 — context is a bonus, never a blocker
                pass

            # Run research. record_id MUST be this video — without it the
            # adapter creates a brand-new idea row (a stray duplicate video
            # appeared in the workspace, seen live on DVU 2026-07-02).
            payload = await run_research(
                anthropic_client=self._pipeline.anthropic,
                topic=topic,
                context=research_context,
                airtable_client=self._pipeline.airtable,
                record_id=video_id,
                system_prompt_override=getattr(self._pipeline, "research_system_prompt", None),
            )

            if not payload:
                raise Exception("Research returned no results")

            roster_check = _roster_validation(topic, payload)
            payload["unit_roster_validation"] = roster_check
            if not roster_check.get("passed"):
                await self._log_activity(
                    bot_name, video_id, "running",
                    "Roster contract needs review: " + "; ".join(roster_check.get("warnings", []))[:800],
                )

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
            # Capture WHAT was applied so the creator can see it (autopilot scorecard
            # + chat) - transparency, not a black box.
            try:
                import json as _json
                applied = [
                    {
                        "category": l.get("category", ""),
                        "pattern": l.get("pattern", ""),
                        "verdict": ("PROVEN" if float(l.get("confidence", 0)) >= 60
                                    else "AVOID" if float(l.get("confidence", 0)) <= 40 else "TESTING"),
                    }
                    for l in learnings
                ]
                await execute(
                    "UPDATE videos SET applied_intelligence = "
                    "COALESCE(applied_intelligence, '{}'::jsonb) || jsonb_build_object('learnings_used', $1::jsonb) "
                    "WHERE id = $2",
                    _json.dumps(applied), video_id,
                )
            except Exception as _e:
                print(f"[Script] record applied learnings failed: {_e}")
            print(f"[Script] Injected {len(learnings)} learnings into writer_guidance for {video_id[:8]}")

        except Exception as e:
            print(f"[Script] Error injecting learnings: {e}")

    async def _static_unit_roster(self, video: dict) -> list[str]:
        """The machine list a static documentary must cover, in order.

        Source of truth is the research payload: a structured `unit_roster`
        field when research provided one, else a one-shot extraction from the
        fact sheet (cheap, and works for payloads created before the roster
        field existed). Returns [] when nothing reliable is available - the
        script then runs uncontracted rather than with a bad roster."""
        import json as _json_ur

        rp = video.get("research_payload")
        if isinstance(rp, str):
            try:
                rp = _json_ur.loads(rp)
            except (ValueError, TypeError):
                return []
        if not isinstance(rp, dict):
            return []

        roster = rp.get("unit_roster")
        if isinstance(roster, list):
            names = [_unit_display_name(m) for m in roster]
            names = [n for n in names if n]
            if 3 <= len(names) <= 40:
                return names

        fact = rp.get("fact_sheet") or ""
        if not isinstance(fact, str) or len(fact) < 200:
            return []
        try:
            raw = await self._pipeline.anthropic.generate(
                prompt=(
                    "From this research fact sheet, list every distinct MACHINE it covers "
                    "(exact designation and name, e.g. 'Boeing XB-15', 'Convair B-36 Peacemaker'), "
                    "in the order they appear. One per line. No numbering, no commentary, "
                    "no variants that are only mentioned in passing - only machines with their "
                    "own story block.\n\n" + fact[:12000]
                ),
                system_prompt="You extract structured lists. Output only the list, one item per line.",
                max_tokens=800,
                temperature=0.0,
            )
            names = [ln.strip(" -•\t") for ln in (raw or "").splitlines() if ln.strip()]
            names = [n for n in names if 2 <= len(n.split()) <= 8][:32]
            return names if len(names) >= 8 else []
        except Exception as e:  # noqa: BLE001 — roster is an enhancement, never a blocker
            _logger.warning("[unit-roster] extraction failed: %s", str(e)[:150])
            return []

    async def _resplit_static_scenes(self, video_id: str) -> None:
        """Static documentaries: one scene per UNIT PARAGRAPH, not per act.

        The script bot writes one scripts row per ACT (pipeline_control), which
        for a static docu collapses a 24-30 machine video into ~6 scenes = ~6
        held images (seen live on DvsU 2026-07-07). The channel format is one
        machine / one paragraph / one image / one caption, so re-split the
        narration into paragraph scenes. Also strips non-spoken junk (act
        markers, markdown headings, dividers, meta notes) so nothing that is
        not narration can reach TTS. Fail-open: a resplit error keeps the
        act-level rows rather than blocking the stage."""
        try:
            video = await self._get_video(video_id)
            script = (video or {}).get("script") or ""
            if not script.strip():
                return
            units: list[str] = []
            for para in script.split("\n\n"):
                p = para.strip()
                if not p or p.startswith("[ACT") or p.startswith("@@@"):
                    continue
                if p.startswith("#") or p.startswith("---") or p.lower().startswith("**angle"):
                    continue
                # Drop leftover markdown emphasis wrappers on meta lines
                if len(p.split()) < 25:
                    continue  # fragments / stray connectors are not units
                units.append(p)
            if len(units) < 8:
                _logger.warning("[static-resplit] %s: only %d unit paragraphs — keeping act scenes",
                                video_id, len(units))
                return
            rows = await fetch_all(
                "SELECT voice_id FROM scripts WHERE video_id = $1 LIMIT 1", video_id)
            voice_id = (rows[0].get("voice_id") if rows else None) or "1SM7GgM6IMuvQlz2BwM3"
            await execute("DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2",
                          video_id, self.tenant_id)
            for i, text in enumerate(units, start=1):
                await execute(
                    """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
                       VALUES ($1, $2, $3, $4, $5, 'Create', $6)""",
                    self.tenant_id, video_id, i, text,
                    video.get("video_title"), voice_id,
                )
            await self._log_activity("Script Bot", video_id, "completed",
                                     f"Static format: split into {len(units)} unit scenes (one machine per scene)")
            _logger.info("[static-resplit] %s: %d unit scenes", video_id, len(units))
        except Exception as e:  # noqa: BLE001 — never block the stage
            _logger.warning("[static-resplit] failed for %s: %s", video_id, str(e)[:200])

    async def _validate_static_script_roster(self, video_id: str) -> dict:
        """Hard gate: static complete-roster videos must script every locked unit."""
        import json as _json_vr
        video = await self._get_video(video_id)
        rp = (video or {}).get("research_payload") or {}
        if isinstance(rp, str):
            try:
                rp = _json_vr.loads(rp)
            except Exception:
                rp = {}
        rows = await fetch_all(
            "SELECT scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
            video_id, self.tenant_id,
        )
        units = [r.get("scene_text") or "" for r in (rows or [])]
        check = _roster_validation((video or {}).get("video_title") or "", rp if isinstance(rp, dict) else {}, units)
        existing = (video or {}).get("script_validation")
        try:
            validation = _json_vr.loads(existing) if isinstance(existing, str) and existing.strip() else (existing or {})
        except Exception:
            validation = {}
        if not isinstance(validation, dict):
            validation = {}
        validation["unit_roster"] = check
        await execute(
            "UPDATE videos SET script_validation = $1 WHERE id = $2 AND tenant_id = $3",
            _json_vr.dumps(validation), video_id, self.tenant_id,
        )
        if not check.get("passed"):
            await self._log_activity(
                "Script Bot", video_id, "failed",
                "Script roster gate failed: " + "; ".join(check.get("warnings", []))[:800],
            )
        return check

    async def _factual_gate_static(self, video_id: str) -> None:
        """Factual gate for static documentaries: verify every claim in the
        script against the research payload; on flagged claims, regenerate
        ONCE with an explicit only-use-researched-facts directive, then
        re-verify. The final verdict lands in the activity feed either way so
        the operator can see exactly what was flagged. Fail-open on errors —
        a broken checker must not block a build — but a *flagged* script gets
        its one correction pass."""
        try:
            import json as _json_fg
            from script.brief_translator.script_generator import verify_script_claims

            video = await self._get_video(video_id)
            script = (video or {}).get("script") or ""
            rp_raw = (video or {}).get("research_payload")
            if not script.strip() or not rp_raw:
                return
            brief = _json_fg.loads(rp_raw) if isinstance(rp_raw, str) else rp_raw
            client = getattr(self._pipeline, "anthropic", None)
            if client is None or not isinstance(brief, dict):
                return

            flagged = await verify_script_claims(client, script, brief)
            if not (flagged or "").strip():
                await self._log_activity(
                    "Script Bot", video_id, "running",
                    "Fact check passed: every claim traces to the research")
                return

            await self._log_activity(
                "Script Bot", video_id, "running",
                "Fact check flagged claims — rewriting from the research only:\n"
                + flagged[:600])
            existing = (video.get("writer_guidance") or "")
            block = (
                "\n\n--- FACTUAL CORRECTION (auto, internal) ---\n"
                "This channel publishes exact figures; its audience checks them. "
                "Rewrite using ONLY facts present in the research payload. Remove "
                "or replace every flagged claim below — if the research doesn't "
                "state it, the script may not either. Flagged:\n"
                + flagged.strip()
                + "\n--- END FACTUAL CORRECTION ---"
            )
            await execute(
                "UPDATE videos SET writer_guidance = $1 WHERE id = $2",
                existing + block, video_id)
            self._load_idea_from_video(video_id)
            await self._pipeline.run_brief_translator()

            video = await self._get_video(video_id)
            flagged2 = await verify_script_claims(
                client, (video or {}).get("script") or "", brief)
            if (flagged2 or "").strip():
                await self._log_activity(
                    "Script Bot", video_id, "running",
                    "Fact check STILL flags claims after one rewrite — review "
                    "before publishing:\n" + flagged2[:600])
            else:
                await self._log_activity(
                    "Script Bot", video_id, "completed",
                    "Fact check passed after rewrite: claims trace to the research")
        except Exception as e:  # noqa: BLE001
            print(f"[Script] factual gate skipped for {video_id[:8]}: {str(e)[:200]}", flush=True)

    async def _grade_and_maybe_revise_script(self, video_id: str, regenerate=None) -> None:
        """Phase 2 retention gate: grade the freshly generated script against the
        YouTube retention rules (hook speed, but/therefore causality, escalating
        stakes, a delivered payoff, specificity). On a 'revise'/'regenerate'
        verdict, append the grader's concrete guidance to writer_guidance and
        regenerate the script ONCE.

        Mirrors originality.py's philosophy: no user-facing gate, just a silent
        quality nudge. Fail-open and best-effort - any error here leaves the
        already-generated script in place and never blocks the pipeline.
        """
        try:
            import asyncio
            from originality import grade_script, grade_script_with_client

            video = await self._get_video(video_id)
            script = (video or {}).get("script") or ""
            if not script.strip():
                return

            # Niche keeps grading niche-appropriate (a how-to is not punished for
            # lacking a story arc). Resolved defensively; falls back to neutral.
            niche = ""
            try:
                identity = await build_identity_context(self.tenant_id, video)
                niche = identity.niche
            except Exception:
                niche = ""

            draft = {
                "niche": niche,
                "title": video.get("video_title"),
                "hook": video.get("executive_hook") or video.get("hook_script"),
                "script": script,
            }
            # Route through the tenant's AnthropicClient so grading works for
            # EVERY tenant - direct-key tenants AND Kie-gateway tenants (Bearer
            # auth + model aliasing). Fall back to the bare direct client only if
            # the pipeline has no client (edge case).
            client = getattr(self._pipeline, "anthropic", None)
            if client is not None:
                grade = await grade_script_with_client(draft, client)
            else:
                grade = await asyncio.to_thread(grade_script, draft)
            print(f"[Script] retention grade {video_id[:8]}: {grade.verdict} "
                  f"(score {grade.score}) gates={grade.failing_gates}", flush=True)

            regenerating = bool(grade.needs_revision and (grade.rewrite_guidance or "").strip())
            # Capture the grade so the creator can SEE it (autopilot scorecard + chat),
            # whether or not we re-rolled - transparency, not a black box.
            await self._record_applied_retention(video_id, grade, regenerating)
            if not regenerating:
                return

            # Append the grader's guidance and regenerate exactly once. writer_guidance
            # is read by BOTH the documentary brief_translator and the modeled-script
            # prompt, so the re-run picks it up on either pathway.
            existing = (video.get("writer_guidance") or "")
            block = (
                "\n\n--- RETENTION REVISION (auto, internal) ---\n"
                + grade.rewrite_guidance.strip()
                + "\n--- END RETENTION REVISION ---"
            )
            await execute(
                "UPDATE videos SET writer_guidance = $1 WHERE id = $2",
                existing + block, video_id,
            )
            # Modeled videos must re-roll through the MODELED generator, not the
            # documentary brief_translator (which would steamroll their style).
            if regenerate is not None:
                await regenerate()
            else:
                self._load_idea_from_video(video_id)
                await self._pipeline.run_brief_translator()
            print(f"[Script] regenerated {video_id[:8]} once after retention grade", flush=True)
            # ponytail: one re-roll only. If the rewrite is still weak it ships -
            # a silent nudge, not a hard gate; looping would risk stalling a run.
        except Exception as e:
            print(f"[Script] retention grade skipped for {video_id[:8]}: {str(e)[:200]}", flush=True)

    async def _record_applied_retention(self, video_id: str, grade, regenerated: bool) -> None:
        """Persist the retention grade onto videos.applied_intelligence so the creator
        can see what the hook/retention engine did (autopilot scorecard + chat).
        Best-effort; never blocks the pipeline."""
        try:
            import json as _json
            rec = {
                "fired": bool(regenerated),
                "score": getattr(grade, "score", None),
                "verdict": getattr(grade, "verdict", None),
                "failing_gates": list(getattr(grade, "failing_gates", []) or []),
            }
            await execute(
                "UPDATE videos SET applied_intelligence = "
                "COALESCE(applied_intelligence, '{}'::jsonb) || jsonb_build_object('retention_grade', $1::jsonb) "
                "WHERE id = $2",
                _json.dumps(rec), video_id,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[Script] record retention grade failed: {str(e)[:160]}")

    async def _regen_modeled_script(self, video_id: str) -> None:
        """Re-roll a modeled script through the MODELED generator (used by the
        retention grade so a modeled video keeps its replicated style on revision)."""
        v = await self._get_video(video_id)
        if v:
            await self._run_modeled_script(video_id, v)

    @staticmethod
    def _parse_modeled_scenes(raw: str) -> list:
        """Parse modeled-script model output into [{"scene", "text"}].

        Primary format is sentinel markers (@@@SCENE n@@@), which are robust to
        quotes and newlines inside long narration — the old JSON contract broke
        on unescaped quotes in the text. Falls back to the JSON shape for any
        response that still comes back as {"scenes": [...]}. Scenes are
        renumbered sequentially from 1.
        """
        import json as _json
        import re as _re
        text = (raw or "").strip()
        if text.startswith("```"):
            # drop the opening fence line and any trailing closing fence
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        markers = list(_re.finditer(r"@@@\s*SCENE\s*\d+\s*@@@", text, _re.IGNORECASE))
        if markers:
            out: list = []
            for idx, m in enumerate(markers):
                start = m.end()
                end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
                body = text[start:end].strip()
                if body:
                    out.append({"scene": len(out) + 1, "text": body})
            return out

        # Fallback: legacy JSON contract.
        try:
            data = _json.loads(text)
        except Exception:
            return []
        raw_scenes = data.get("scenes") if isinstance(data, dict) else None
        if not isinstance(raw_scenes, list):
            return []
        out = []
        for s in raw_scenes:
            t = (s.get("text") or "").strip() if isinstance(s, dict) else ""
            if t:
                out.append({"scene": len(out) + 1, "text": t})
        return out

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
        minutes = int(video.get("video_length_minutes") or 10)
        # Scene count + word target scale with length so a SHORT (1-2 min) video isn't
        # forced into a long, over-segmented script. 3+ min keep their prior values.
        default_scenes = max(2, min(8, round(minutes * 2.5)))
        target_words = max(120, minutes * 145)
        min_scenes = 3 if minutes >= 3 else 2
        concept_lines = "\n".join(
            f"{i}. {c.get('concept')}" for i, c in enumerate(concepts, start=1)
        ) or f"Structure the story into {default_scenes} natural scenes."

        research = video.get("research_payload")
        if isinstance(research, dict):
            research = _json.dumps(research)
        research_excerpt = (research or "")[:4000]

        prompt = f"""Write the complete spoken script for a video titled "{video.get('video_title')}".

{video.get('writer_guidance') or ''}

SCENE PLAN — follow these story beats in order. SPLIT any beat that moves between locations into
separate scenes, one location each:
{concept_lines}

ONE LOCATION PER SCENE (important) — every scene must take place in a SINGLE physical location.
The moment the action moves somewhere new (e.g. living room -> garage -> lakeside), START A NEW
SCENE with a new @@@SCENE n@@@ marker. A beat that travels through several places becomes several
scenes, one per place. NEVER let one scene span two locations — this keeps each scene's visuals
consistent for the storyboard and the stitched video.

Target length: about {target_words} words total, spread across the scenes.

Background material you may draw from (use only what fits the video's style and audience):
{research_excerpt}

VOICE — write every scene in the EXACT voice, tense, vocabulary and FORMAT your style
instructions above define. If they call for character DIALOGUE, write dialogue (speaker
turns like "Mum: ..." are fine); if narration, write narration; if both, both. Match their
sentence length and reading level. Do NOT default to a third-person narrator unless the
style explicitly says to — the style above wins over any default.

FORMAT — plain text, no JSON, no markdown headings. Start each scene on its own line with
exactly this marker:
@@@SCENE n@@@
where n is the scene number (1, 2, 3, ...). Put that scene's spoken text on the lines right
after its marker — exactly what is heard in that scene. Use the markers and nothing else to
separate scenes."""

        style_system = video.get("script_system_prompt") or ""
        # Long free-text narration used to be returned as one big JSON blob and
        # json.loads choked on unescaped quotes/newlines inside the text
        # (JSONDecodeError ~char 5298). Sentinel markers are immune to that.
        # Retry once with a stricter nudge + lower temperature before giving up.
        scenes: list = []
        for attempt in range(2):
            raw = await self._pipeline.anthropic.generate(
                prompt=prompt if attempt == 0 else (
                    prompt + "\n\nIMPORTANT: separate scenes with ONLY the "
                    "@@@SCENE n@@@ markers. Do not return JSON."
                ),
                system_prompt=style_system,
                max_tokens=16000,
                temperature=0.7 if attempt == 0 else 0.4,
            )
            scenes = self._parse_modeled_scenes(raw)
            if len(scenes) >= min_scenes:
                break
            if attempt == 0:
                await self._log_activity(bot_name, video_id, "started",
                                         "Reformatting script for clean scene breaks")
        if len(scenes) < min_scenes:
            raise Exception("Modeled script came back with too few scenes")

        full_script = "\n\n".join(s["text"].strip() for s in scenes)
        await execute(
            """UPDATE videos SET script = $1, script_validation = $2, status = $3, updated_at = now()
               WHERE id = $4 AND tenant_id = $5""",
            full_script,
            _json.dumps({"passed": True, "checks": [
                {"name": "style_replication", "passed": True,
                 "detail": "Documentary editorial checks skipped — script written in the reference video's style"}]}),
            self._skip_disabled_next(video, "ready_for_voice"),
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

            rp_for_gate = video.get("research_payload")
            import json as _json_gate
            if isinstance(rp_for_gate, str):
                try:
                    rp_for_gate = _json_gate.loads(rp_for_gate)
                except Exception:
                    rp_for_gate = {}
            if isinstance(rp_for_gate, dict):
                roster_gate = rp_for_gate.get("unit_roster_validation") or _roster_validation(
                    video.get("video_title") or video.get("headline") or "", rp_for_gate
                )
                if isinstance(roster_gate, str):
                    try:
                        roster_gate = _json_gate.loads(roster_gate)
                    except Exception:
                        roster_gate = {}
                if roster_gate.get("complete_title") and not roster_gate.get("passed"):
                    msg = "Fix research roster before scripting: " + "; ".join(roster_gate.get("warnings", []))
                    await self._log_activity(bot_name, video_id, "failed", msg[:900])
                    return {"status": "failed", "error": msg}

            # Creator-supplied scripts are used VERBATIM: no generation, no
            # grading, no gates (user_script.set_user_script already persisted
            # the scenes). This guard also makes re-runs and the queue/autopilot
            # step loop pass straight through the script stage.
            if (video.get("script_source") or "generated") == "user_supplied" and (video.get("script") or "").strip():
                eff_status = self._skip_disabled_next(video, "ready_for_voice")
                if not is_at_or_past_stage(current_status, eff_status):
                    await self._update_video_status(video_id, eff_status)
                    await self._log_transition(video_id, current_status, eff_status, "api")
                await self._log_activity(bot_name, video_id, "completed",
                                         "Using your supplied script verbatim")
                return {"status": eff_status, "video_id": video_id}

            # Style-replicated videos get a dedicated script path — the
            # brief_translator's documentary machinery ignores their style.
            # Jarvis: modeled videos still go through the SAME hook/retention loop as
            # every other pathway. Inject learnings first (the modeled prompt reads
            # writer_guidance), generate, then grade + maybe re-roll via the MODELED
            # generator (not the documentary brief_translator).
            if video.get("source") == "modeled" and video.get("script_system_prompt"):
                await self._inject_learnings_into_writer_guidance(video_id)
                video = await self._get_video(video_id)
                result = await self._run_modeled_script(video_id, video)
                await self._grade_and_maybe_revise_script(
                    video_id, regenerate=lambda: self._regen_modeled_script(video_id)
                )
                return result

            await self._log_activity(bot_name, video_id, "started", "Generating script")

            # Inject performance learnings into writer_guidance BEFORE script generation
            await self._inject_learnings_into_writer_guidance(video_id)

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            # Load idea into pipeline state from Supabase
            self._load_idea_from_video(video_id)

            # First-time-right format contract: when this video carries an
            # attached LOCKED cast (source='project'), those characters are
            # the ONLY allowed speakers. The contract is appended at the very
            # END of the writing prompt - after the topic brief - so a brief
            # that describes an instructor/cashier can never out-pull the
            # format (the Senora-Martinez failure), and required closing
            # beats (quiz recap / hook) can't be buried by a long premise.
            # Channels without a locked cast are untouched.
            try:
                cast_rows = await fetch_all(
                    "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2 "
                    "AND source = 'project' ORDER BY sort, created_at",
                    video_id, self.tenant_id,
                )
                cast_names = [r["name"] for r in (cast_rows or []) if (r.get("name") or "").strip()]
            except Exception:  # noqa: BLE001
                cast_names = []
            if cast_names:
                names = ", ".join(cast_names)
                who_narrates = cast_names[0] + (f" or {cast_names[1]}" if len(cast_names) > 1 else "")
                self._pipeline.script_allowed_speakers = cast_names
                self._pipeline.script_format_contract = (
                    "=== FINAL OUTPUT CONTRACT - THIS OVERRIDES EVERYTHING ABOVE, INCLUDING THE TOPIC BRIEF ===\n"
                    f"1. THE ONLY SPEAKERS in this script are: {names}. Write dialogue lines for NO ONE else - "
                    "no instructors, cashiers, relatives, phone voices or crowds, even when the topic brief "
                    "describes such a person. Other people may exist in the story but NEVER speak: "
                    f"{who_narrates} says out loud what they do and reports their words.\n"
                    "2. Every spoken dialogue line is exactly 'Name: spoken words' using ONLY the names above. "
                    "No stage directions, no parentheses, no asterisks, no brackets.\n"
                    "3. HARD LIMIT: no single dialogue line may exceed 30 spoken words. Each line becomes one "
                    "video clip and the clip model cannot speak more than that before the clip ends, cutting "
                    "the character off mid-sentence. Break any longer speech into several consecutive shorter "
                    "lines by the same speaker - each beat of the speech becomes its own line.\n"
                    "4. Follow the system prompt's STORY RULES and OUTPUT CONTRACT to the letter, ESPECIALLY any "
                    "required closing beats (quiz recap, next-episode hook) - a long or exciting topic brief "
                    "never excuses skipping them."
                )
            else:
                self._pipeline.script_allowed_speakers = None
                self._pipeline.script_format_contract = None

            # Static documentaries: the research already SELECTED the machines
            # (curated shortlist). Hand the writer that roster as a locked
            # contract - one 95-120 word paragraph per machine, in order - so
            # the script can never skip, merge, or substitute units. The
            # contract seam is appended LAST in generate_script, which is what
            # makes it stick against the topic brief.
            if (video.get("render_mode") or "") == "static_docu":
                roster = await self._static_unit_roster(video)
                if roster:
                    roster_lines = "\n".join(f"{i}. {m}" for i, m in enumerate(roster, 1))
                    self._pipeline.script_format_contract = (
                        ((self._pipeline.script_format_contract or "") + "\n\n").lstrip()
                        + "=== UNIT ROSTER - NON-NEGOTIABLE (static documentary) ===\n"
                        f"The research selected exactly these {len(roster)} machines. Write EXACTLY ONE "
                        "self-contained unit paragraph of 95-120 words for EACH machine below, in THIS "
                        "order, grouped into your acts. One machine = one paragraph.\n"
                        f"{roster_lines}\n"
                        "Do not skip, merge, add, or substitute machines. Every machine on this list "
                        "appears exactly once; no machine not on this list appears at all."
                    )
                    await self._log_activity(bot_name, video_id, "started",
                                             f"Unit roster locked: {len(roster)} machines from research")

            # Run script generation
            result = await self._pipeline.run_brief_translator()

            if result.get("error"):
                raise Exception(result["error"])

            # Phase 2: silent retention grade + at most one auto-revise.
            # Best-effort; never blocks the stage.
            await self._grade_and_maybe_revise_script(video_id)

            # Static documentaries are exact-figures formats: fact-check the
            # script against the research payload and re-roll once if claims
            # can't be traced. (Advisory-only elsewhere; a GATE here.)
            if (video.get("render_mode") or "") == "static_docu":
                await self._factual_gate_static(video_id)
                # One machine / one paragraph / one image: scene rows must be
                # unit paragraphs, not acts (the bot writes one row per act).
                await self._resplit_static_scenes(video_id)
                roster_check = await self._validate_static_script_roster(video_id)
                if roster_check.get("complete_title") and not roster_check.get("passed"):
                    raise Exception("Script roster gate failed: " + "; ".join(roster_check.get("warnings", [])))

            # Dialogue intelligence runs unattended after EVERY script path —
            # the modeled and user-supplied paths already had this hook, but
            # the brief-translator path (the most common one) was missing it,
            # so dialogue scripts stayed untagged and voice/clips fell back to
            # narrator-only. Best-effort: a tagging hiccup must not fail the
            # stage (manual retro trigger: POST .../script/tag-dialogue).
            try:
                from dialogue_intelligence import tag_video_dialogue, cast_character_voices
                tag_result = await tag_video_dialogue(video_id, self.tenant_id)
                if tag_result.get("dialogue_mode") == "character_dialogue":
                    await cast_character_voices(video_id, self.tenant_id)
                _logger.info("[dialogue] %s: %s", video_id, tag_result)
            except Exception as e:
                _logger.warning("[dialogue] tagging failed for %s: %s", video_id, str(e)[:200])

            new_status = result.get("new_status", "ready_for_voice")
            eff_status = self._skip_disabled_next(video, to_supabase(new_status))

            # Update Supabase
            await self._update_video_status(video_id, eff_status)
            await self._log_transition(video_id, current_status, eff_status, "api")
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

            # The voice bot must know whether this is a dialogue video — the
            # narrator's text drops character lines there (the cast performs
            # them; they must never be read twice).
            self._pipeline.dialogue_mode = video.get("dialogue_mode") or ""

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

    async def _stamp_padded_audio(self, video_id: str, scene: int, line: dict, pad_url: str) -> None:
        """Record a speaking shot's padded performance audio on its segment in
        the dialogue_segments jsonb. Two jobs: bookkeeping, and the media-proxy
        ALLOWLIST — the proxy only serves DB-referenced files, and the talking-
        clip model fetches this audio through it. Best-effort."""
        try:
            import json as _json
            from clip_dialogue import norm as _norm
            row = await fetch_one(
                "SELECT id, dialogue_segments FROM scripts "
                "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3",
                video_id, self.tenant_id, scene)
            raw = (row or {}).get("dialogue_segments")
            if isinstance(raw, str):
                raw = _json.loads(raw)
            if not raw:
                return
            for seg in raw:
                if (seg.get("type") == "dialogue"
                        and _norm(seg.get("speaker")) == _norm(line.get("speaker"))
                        and _norm(seg.get("text")) == _norm(line.get("text"))):
                    seg["padded_audio_url"] = pad_url
                    break
            else:
                return
            await execute(
                "UPDATE scripts SET dialogue_segments=$1, updated_at=now() WHERE id=$2",
                _json.dumps(raw), row["id"])
        except Exception as e:
            print(f"[clips] padded-audio stamp failed ({str(e)[:120]})", flush=True)

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

            # Self-healing sweeps: a transient ElevenLabs/network hiccup no
            # longer strands a half-voiced video for the creator to babysit -
            # failed lines are retried in up to two extra passes (already-
            # voiced lines are skipped, so sweeps are cheap and idempotent).
            sweeps = 1
            while (not result.get("cancelled")
                   and result.get("segments_failed", 0) > 0
                   and sweeps < 3):
                sweeps += 1
                await asyncio.sleep(5)
                if progress_callback:
                    try:
                        await progress_callback(
                            f"Retry pass {sweeps}: finishing {result['segments_failed']} missed line(s)…"
                        )
                    except Exception:  # noqa: BLE001
                        pass
                again = await synthesize_video_segments(
                    video_id,
                    self.tenant_id,
                    tts=self._pipeline.elevenlabs,
                    scene_filter=scene,
                    progress_callback=progress_callback,
                    cancel_check=self._pipeline.should_cancel,
                )
                made_progress = again.get("segments_voiced", 0) > 0
                result = {
                    **again,
                    "segments_voiced": result["segments_voiced"] + again.get("segments_voiced", 0),
                    "segments_skipped": result["segments_skipped"],
                    "warnings": result["warnings"] + again.get("warnings", []),
                }
                if not made_progress and result.get("segments_failed", 0) > 0:
                    break  # hard failure, stop burning retries

            if result.get("cancelled"):
                msg = (f"Stopped — kept {result['segments_voiced']} voiced segment(s). "
                       "Run again to resume.")
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg, **result}

            still_failed = result.get("segments_failed", 0)
            if still_failed:
                msg = (f"Voiced {result['segments_voiced']} segment(s), but {still_failed} "
                       "line(s) couldn't be voiced after retries — run Generate Voice again "
                       "to finish them (voiced lines are kept).")
                await self._log_activity(bot_name, video_id, "failed", msg)
                return {"status": "failed", "video_id": video_id, "error": msg, **result}

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
            wired = {"grok-imagine", "seedance-2-fast", "veo-3.1-fast", "veo-3.1-quality"}
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
                f"video_clip_url, duration_seconds, sentence_text, image_prompt, assigned_dialogue "
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
            from clip_dialogue import (load_dialogue_lines, match_lines, match_assigned,
                                       speaking_prompt, native_speaking_prompt, motion_guard,
                                       duck_audio, download_voice, mux_voice, pad_line_audio,
                                       DIALOGUE_VOICE_LEAD_SECONDS, speech_seconds,
                                       spoken_word_count, pick_clip_duration, clip_cost_for)
            from shared.clients.image_client import CONTENT_POLICY_MARKER
            client = self._pipeline.image_client
            # Grok-imagine takes any duration 6–30s (Kie). Use every tier the
            # model profile declares so a long spoken line isn't cut at 6/10s;
            # the per-clip selector below picks the smallest tier that fits.
            durations = sorted(profile.durations) or [6]

            # Seedance is a drop-in animator with the same call shape as Grok
            # (img, prompt, duration, extra_image_urls). Veo keeps its own branch below.
            _vaspect = (video.get("aspect_ratio") or "16:9")
            _vres = (video.get("video_resolution") or "720p")
            if model_id.startswith("seedance"):
                def animate(img, prompt, duration=6, extra_image_urls=None):
                    return client.generate_video_seedance(
                        img, prompt, duration=duration,
                        extra_image_urls=extra_image_urls, aspect_ratio=_vaspect)
            else:
                # Pass the video's aspect + resolution to Grok — without aspect it
                # crops every clip to vertical (16:9 came out 9:16); resolution is
                # the quality selector (480p / 720p).
                def animate(img, prompt, duration=6, extra_image_urls=None):
                    return client.generate_video(
                        img, prompt, duration=duration,
                        extra_image_urls=extra_image_urls,
                        aspect_ratio=_vaspect, resolution=_vres)

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
            cast_voice_by_name: dict = {}
            if (video.get("dialogue_mode") or "") == "character_dialogue":
                name_rows = await fetch_all(
                    "SELECT name, voice_name FROM video_characters WHERE video_id = $1 ORDER BY sort",
                    video_id)
                cast_names = ", ".join((c["name"] or "").strip() for c in name_rows if c.get("name"))
                cast_voice_by_name = {(c["name"] or "").strip().casefold(): c["voice_name"]
                                      for c in name_rows if c.get("voice_name")}
            # Option A voice lock: grok_native speaking clips get their audio
            # re-rendered in the character's pinned ElevenLabs voice (speech-
            # to-speech keeps timing, so the mouth stays synced). Needs the
            # tenant's direct ElevenLabs key; off without one, or via env.
            xi_key = None
            if native_voices and os.getenv("VOICE_SWAP", "on") != "off":
                from vault import get_secret
                xi_key = await get_secret("elevenlabs_api_key", self.tenant_id)

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
                # Coverage cards keep the moment SUMMARY in sentence_text and
                # the verbatim line in assigned_dialogue, so check both — the
                # summary-only check silently skipped the chain for coverage
                # rows (and the final render needs EVERY segment voiced, so an
                # unvoiced line on any card in the scene triggers it).
                if (video.get("dialogue_audio") or "voice_over") != "grok_native":
                    def _card_lines(r):
                        return (match_lines(r.get("sentence_text"), dialogue_by_scene.get(r["scene"]))
                                or match_assigned(r.get("assigned_dialogue"), dialogue_by_scene.get(r["scene"])))
                    unvoiced_scenes = sorted({
                        r["scene"] for r in todo
                        if any(not l.get("audio_url") for l in _card_lines(r))
                    })
                    for sc in unvoiced_scenes:
                        await _report(f"Creating the voices for scene {sc} first…")
                        await self.run_dialogue_voice(video_id, scene=sc, progress_callback=progress_callback)
                    if unvoiced_scenes:
                        dialogue_by_scene = await load_dialogue_lines(video_id, self.tenant_id)

            done = failed = 0
            cost = 0.0
            total = len(todo)
            # Clips fan out concurrently; CLIP_CONCURRENCY tunes the width
            # (Kie queues server-side — same account the coverage image gens
            # already hit concurrently).
            sem = asyncio.Semaphore(int(os.getenv("CLIP_CONCURRENCY", "6")))
            cancelled = False
            CLIP_DEADLINE = 420  # hard per-clip cap (sem already held): a stuck Grok
            # job frees its slot in ~7 min instead of holding it for the full internal
            # retry budget (~30 min). The clip is counted failed and retried next round.

            async def _gen(coro):
                return await asyncio.wait_for(coro, CLIP_DEADLINE)

            async def _animate_recover(r, image_url, full_prompt, clip_dur):
                """Generate the clip; if Grok's content filter (failCode 430) flags
                the frame, redraw the shot with a safer wholesome framing and retry
                ONCE. Returns (clip_url_or_None, image_url_actually_used)."""
                extra = [_proxy_url(sheet)] if sheet else None
                try:
                    return (await _gen(animate(image_url, full_prompt, duration=clip_dur,
                                               extra_image_urls=extra)), image_url)
                except Exception as e:
                    if CONTENT_POLICY_MARKER not in str(e):
                        raise  # not a content block — let _safe_one count it failed
                    sc, idx = r["scene"], r["image_index"]
                    await _report(f"S{sc}.{idx} was flagged by the video filter — redrawing it safer…")
                    print(f"[clips] S{sc}.{idx} content-policy block — redrawing safer + retrying", flush=True)
                    try:
                        from scripts.coverage_to_app import redraw_asset_image
                        rr = await redraw_asset_image(video_id, self.tenant_id, r["id"], safe_reframe=True)
                    except Exception as re_err:
                        print(f"[clips] S{sc}.{idx} safe-redraw errored: {str(re_err)[:150]}", flush=True)
                        return None, image_url
                    if (rr or {}).get("status") != "completed":
                        return None, image_url
                    nr = await fetch_one(
                        "SELECT image_url, drive_image_url FROM assets WHERE id = $1", r["id"])
                    new_img = _proxy_url((nr or {}).get("drive_image_url")
                                         or (nr or {}).get("image_url") or image_url)
                    try:
                        return (await _gen(animate(new_img, full_prompt, duration=clip_dur,
                                                   extra_image_urls=extra)), new_img)
                    except Exception as e2:
                        if CONTENT_POLICY_MARKER in str(e2):
                            print(f"[clips] S{sc}.{idx} still flagged after safe redraw — giving up",
                                  flush=True)
                            return None, new_img
                        raise

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
                    # In grok_native mode the coverage motion-writer is the SINGLE
                    # source of truth for what a shot says — it embeds the exact
                    # line in video_prompt and Grok voices it. Don't let the older
                    # match_lines path second-guess that: it matched a phrase in the
                    # shot's DESCRIPTION and overrode the embed, making one line play
                    # 3× while others dropped. voice_over (ElevenLabs overlay) still
                    # needs match_lines to find the line to lay over the clip.
                    vp = (r.get("video_prompt") or "").strip()
                    embedded_words = spoken_word_count(vp)
                    # voice_over line lookup: legacy cards carry the words in
                    # sentence_text (match_lines); coverage masters keep only
                    # the moment SUMMARY there — their verbatim line lives in
                    # assigned_dialogue (match_assigned). Without the second
                    # check, coverage speaking masters shipped with NO voice
                    # muxed and were sized/ducked as silent B-roll.
                    lines = ([] if (native_voices and vp) else
                             [l for l in (match_lines(r.get("sentence_text"), dialogue_by_scene.get(sc))
                                          or match_assigned(r.get("assigned_dialogue"), dialogue_by_scene.get(sc)))
                              if native_voices or l.get("audio_url")])
                    # Speaking = a matched line, or (native) an embedded line.
                    is_speaking = bool(lines) or (native_voices and embedded_words > 0)

                    if lines:
                        # Speaking card → Grok animates the FULL SCENE.
                        # Loose sync by design (Ryan's call): scene
                        # continuity beats mouth precision in this format —
                        # see decisions.md 2026-06-12.
                        # DUAL-ANIMATOR ROUTING (Ryan's call, 2026-07-03):
                        # voice_over speaking shots animate via InfiniteTalk —
                        # the mouth is GENERATED FROM the line's waveform, so
                        # lip-sync is structural (Grok speaking was a coin flip:
                        # the live test's second mouth never moved). Silent
                        # shots keep Grok's camera/action motion. Any talking
                        # failure falls back to the Grok+mux path below.
                        clip_url = None
                        clip_cost = 0.0
                        clip_dur = None
                        talked = False
                        talking_model = os.getenv("TALKING_CLIP_MODEL", "infinitalk")
                        if not native_voices and talking_model != "off":
                            try:
                                vbytes = [b for b in [await download_voice(l["audio_url"])
                                                      for l in lines] if b]
                                if vbytes:
                                    padded = await pad_line_audio(
                                        vbytes, head=DIALOGUE_VOICE_LEAD_SECONDS,
                                        tail=float(os.getenv("PERFORM_DIALOGUE_TAIL", "0.25")))
                                    pad_url = await upload_bytes(
                                        padded, f"{video_id}/voice/padded/S{sc:02d}-{idx:02d}.mp3",
                                        "audio/mpeg", tenant_id=self.tenant_id)
                                    # The media proxy serves only DB-referenced
                                    # files — stamp the padded url into the
                                    # first line's segment jsonb (allowlist).
                                    await self._stamp_padded_audio(video_id, sc, lines[0], pad_url)
                                    talk_prompt = (
                                        f"{(lines[0].get('speaker') or 'The character')} speaks "
                                        "naturally with expressive face and small natural "
                                        "gestures, keeping the exact pose, framing and scene "
                                        "shown in the image.")
                                    clip_url = await asyncio.wait_for(
                                        client.generate_talking_video(
                                            img + ".png" if "/api/media/drive/" in img else img,
                                            _proxy_url(pad_url) + ".mp3",
                                            prompt=talk_prompt,
                                            resolution=_vres),
                                        timeout=int(os.getenv("TALKING_CLIP_DEADLINE", "1200")))
                                    if clip_url:
                                        talked = True
                                        audio_len = (DIALOGUE_VOICE_LEAD_SECONDS
                                                     + sum(float(l.get("duration") or 2.0) for l in lines)
                                                     + float(os.getenv("PERFORM_DIALOGUE_TAIL", "0.25")))
                                        clip_dur = round(audio_len, 2)
                                        clip_cost = round(audio_len * float(
                                            os.getenv("INFINITALK_USD_PER_SEC", "0.03")), 3)
                            except Exception as te:
                                print(f"[clips] S{sc}.{idx} talking clip failed "
                                      f"({str(te)[:120]}) — falling back to Grok", flush=True)
                                clip_url = None
                        if not clip_url:
                            # Grok speaking path (grok_native, kill-switched
                            # talking model, or InfiniteTalk failure).
                            # A coverage master already has a WRITTEN motion
                            # prompt with its line embedded — keep that
                            # direction; generic speaking_prompt is the
                            # fallback for legacy cards.
                            if native_voices:
                                core = native_speaking_prompt(lines, r.get("sentence_text"))
                            elif vp and embedded_words > 0:
                                core = vp
                            else:
                                core = speaking_prompt(lines)
                            prompt = _decorate(core)
                            # The whole spoken line has to fit inside the clip,
                            # or Grok cuts it off. native = Grok times its own
                            # speech; voice_over = the synthesized line's
                            # measured length plus its lead-in.
                            if native_voices:
                                need = speech_seconds(spoken_word_count(core))
                            else:
                                need = (sum(float(l.get("duration") or 2.0) for l in lines)
                                        + DIALOGUE_VOICE_LEAD_SECONDS)
                            clip_dur = pick_clip_duration(need, durations)
                            clip_url, img = await _animate_recover(r, img, prompt, clip_dur)
                            clip_cost = clip_cost_for(profile.cost_per_clip, clip_dur)
                    else:
                        # Motion prompt from the video-scripts stage; a tapped
                        # card without one still animates (safe default) instead
                        # of dead-ending. The default is deliberately filler-free
                        # ("gentle/soft/subtle" are banned by the motion rules and
                        # read as screensaver motion) — a single slow push-in plus
                        # a fidelity lock to the frame.
                        prompt = (r.get("video_prompt") or "").strip() or (
                            "Slow push-in on the main subject. Keep the characters, art "
                            "style, and composition exactly as shown, and animate only "
                            "what is already in the frame.")
                        # People rule (Ryan: S1.4's bird close-up grew an
                        # invented toddler — twice): cutaway cards get an
                        # absolute NO PEOPLE, every other narration card gets
                        # nobody-NEW. Decision table lives in motion_guard.
                        prompt = motion_guard(r.get("image_prompt"),
                                              r.get("sentence_text"), cast_names) + prompt
                        # A coverage shot carries its spoken line INSIDE the
                        # motion prompt (<Name> says ...: "line") — size the clip
                        # to exactly how long that line takes to say, so the video
                        # ENDS when the speech does and Grok has no slack to ad-lib
                        # filler (live finding: an over-long clip invents garbage
                        # past the line). A silent shot keeps the base length; a
                        # timed segment still acts as a floor.
                        spoken_secs = speech_seconds(spoken_word_count(prompt))
                        seg_dur = float(r.get("duration_seconds") or 0)
                        clip_dur = pick_clip_duration(max(spoken_secs, seg_dur), durations)
                        if model_id.startswith("veo-3.1"):
                            veo_model = client.VEO_MODEL_QUALITY if model_id.endswith("quality") else client.VEO_MODEL_FAST
                            clip_url = await _gen(client.generate_video_veo(prompt, image_url=img, model=veo_model))
                            clip_dur = profile.durations[0]
                        else:
                            clip_url, img = await _animate_recover(r, img, _decorate(prompt), clip_dur)
                        clip_cost = clip_cost_for(profile.cost_per_clip, clip_dur)

                    if not clip_url:
                        failed += 1
                        # A no-clip return must leave a trail: which client
                        # class ran, what it was fed. (S1.4 failed twice in
                        # ~1.4s with zero journal output — undebuggable.)
                        print(f"[clips] S{sc}.{idx} returned no clip — "
                              f"client={type(client).__module__}.{type(client).__name__} "
                              f"speaking={is_speaking} dur={clip_dur} img={img[:90]}",
                              flush=True)
                        await _report(f"S{sc}.{idx} didn't generate ({done + failed}/{total})")
                        return
                    clip_bytes = await client.download_image(clip_url)
                    # Audio per mode: grok_native keeps Grok's full audio on
                    # speaking cards (its voices + ambience ARE the take);
                    # voice_over lays the ElevenLabs line over a quiet bed.
                    # Narration cards keep quiet ambience either way — the
                    # renderer mixes narration and music over them.
                    try:
                        if native_voices and is_speaking and xi_key:
                            # Option A voice lock: swap Grok's invented voice
                            # for the speaker's pinned ElevenLabs voice. Same
                            # timing, same mouth, consistent identity. A swap
                            # failure ships Grok's original take (never lose
                            # a paid clip over the polish pass).
                            spk = (r.get("assigned_dialogue") or "").split(":", 1)[0].strip()
                            voice_id = cast_voice_by_name.get(spk.casefold())
                            # A Grok take can chain SEVERAL speakers' lines
                            # ("Then" chaining) — converting the whole clip
                            # with one voice puts the tail of a line in the
                            # wrong throat (La Lavandería v2). Split per turn.
                            turn_speakers = {(l.get("speaker") or "").casefold()
                                             for l in (lines or []) if l.get("speaker")}
                            if len(turn_speakers) > 1:
                                try:
                                    from clip_dialogue import swap_voice_turns
                                    clip_bytes = await swap_voice_turns(
                                        clip_bytes,
                                        [{"speaker": l.get("speaker"), "text": l.get("text") or ""}
                                         for l in lines],
                                        cast_voice_by_name, xi_key)
                                    await _report(f"S{sc}.{idx}: voices locked "
                                                  f"({len(turn_speakers)} speakers)")
                                except Exception as se:
                                    print(f"[clips] S{sc}.{idx} multi-voice swap failed "
                                          f"({str(se)[:120]}) — keeping Grok's take", flush=True)
                            elif voice_id:
                                try:
                                    from clip_dialogue import swap_voice
                                    clip_bytes = await swap_voice(clip_bytes, voice_id, xi_key)
                                    await _report(f"S{sc}.{idx}: voice locked ({spk})")
                                except Exception as se:
                                    print(f"[clips] S{sc}.{idx} voice swap failed "
                                          f"({str(se)[:120]}) — keeping Grok's take", flush=True)
                        elif lines and not native_voices and talked:
                            pass  # an InfiniteTalk clip already carries its line
                        elif lines and not native_voices:
                            voice_secs = sum(float(l.get("duration") or 2.0) for l in lines)
                            vbytes = [b for b in [await download_voice(l["audio_url"]) for l in lines] if b]
                            if vbytes:
                                lead = max(0.0, min(DIALOGUE_VOICE_LEAD_SECONDS,
                                                    float(clip_dur) - voice_secs - 0.1))
                                clip_bytes = await mux_voice(clip_bytes, vbytes,
                                                             delay_seconds=lead, bed_gain=0.2)
                            else:
                                clip_bytes = await duck_audio(clip_bytes)
                        elif not is_speaking and getattr(profile, "strip_audio", False):
                            # Only SILENT shots get ducked. Grok sometimes ad-libs
                            # a stray line over a B-roll insert, so we duck these
                            # HARD (to a faint room-tone bed, not dead silence) so
                            # any invented speech is inaudible. A speaking shot
                            # keeps Grok's voice at full volume — the line IS the take.
                            silent_gain = float(os.getenv("SILENT_CLIP_GAIN", "0.06"))
                            clip_bytes = await duck_audio(clip_bytes, gain=silent_gain)
                    except Exception as e:
                        print(f"[clips] S{sc}.{idx} audio mux failed, keeping raw clip: {str(e)[:150]}", flush=True)
                    drive_url = await upload_bytes(
                        clip_bytes, f"{video_id}/clips/S{sc:02d}-{idx:02d}.mp4", "video/mp4", tenant_id=self.tenant_id)
                    await execute(
                        "UPDATE assets SET video_clip_url = $1, video_duration = $2, "
                        "updated_at = now() WHERE id = $3",
                        drive_url, clip_dur, r["id"],
                    )
                    done += 1
                    cost += clip_cost
                    await _report(f"Animated S{sc}.{idx} ({done}/{total} done)")

            async def _safe_one(r):
                # One clip's failure — including a RAISED error (an SSL blip during
                # download, a Drive/DB hiccup, or a per-clip timeout) — must never
                # abort the batch. Count it, log it, move on; the additive re-run +
                # frontend auto-resume retry it next round.
                nonlocal failed
                try:
                    await _one(r)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    failed += 1
                    print(f"[clips] S{r.get('scene')}.{r.get('image_index')} isolated error: "
                          f"{type(e).__name__}: {str(e)[:150]}", flush=True)
                    try:
                        await _report(f"S{r.get('scene')}.{r.get('image_index')} hit an error ({done + failed}/{total})")
                    except Exception:
                        pass

            await asyncio.gather(*[_safe_one(r) for r in todo])

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

            # Auto-stitch the scene(s) this run touched once they're FULLY animated,
            # so the creator can watch the whole scene (and the final render concats
            # these). A single re-animate re-stitches just its scene; a bulk run
            # stitches every now-complete scene. Best-effort — never fails the clip task.
            try:
                if asset_id is not None:
                    arow = await fetch_one("SELECT scene FROM assets WHERE id = $1", asset_id)
                    consider = [arow["scene"]] if arow and arow.get("scene") is not None else []
                elif scene is not None:
                    consider = [scene]
                else:
                    srows = await fetch_all(
                        "SELECT DISTINCT scene FROM assets WHERE video_id = $1 AND tenant_id = $2 "
                        "AND scene IS NOT NULL", video_id, self.tenant_id)
                    consider = [r["scene"] for r in srows]
                if consider:
                    from render_stitch import stitch_video
                    # Dialogue voice_over scenes preview via the performance-
                    # track assembler (segment audio + timed muted shots) so
                    # the preview sounds like the final render; plain stitch
                    # stays the fallback so a preview never dead-ends.
                    use_perform = (
                        (video.get("dialogue_mode") or "") == "character_dialogue"
                        and (video.get("dialogue_audio") or "voice_over") != "grok_native")
                    for sc in consider:
                        comp = await fetch_one(
                            "SELECT COUNT(*) AS pics, COUNT(video_clip_url) AS clips FROM assets "
                            "WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 "
                            "AND (image_url IS NOT NULL OR drive_image_url IS NOT NULL)",
                            video_id, self.tenant_id, sc)
                        if comp and comp["pics"] > 0 and comp["clips"] == comp["pics"]:
                            try:
                                scene_url = None
                                if use_perform:
                                    try:
                                        from render_perform import assemble_scene
                                        pres = await assemble_scene(video_id, self.tenant_id, sc)
                                        scene_url = pres["scene_video_url"]
                                        print(f"[stitch] scene {sc} performance-assembled "
                                              f"({pres['shots']} shots, {pres['duration_seconds']}s)", flush=True)
                                    except Exception as pe:
                                        print(f"[stitch] scene {sc} performance assembly failed "
                                              f"({str(pe)[:150]}) — falling back to plain stitch", flush=True)
                                if not scene_url:
                                    res = await stitch_video(video_id, self.tenant_id, scene=sc)
                                    scene_url = res["final_video_url"]
                                    print(f"[stitch] scene {sc} auto-stitched ({res['clip_count']} clips)", flush=True)
                                await execute(
                                    "UPDATE scripts SET scene_video_url = $1, updated_at = now() "
                                    "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
                                    scene_url, video_id, sc, self.tenant_id)
                            except Exception as se:
                                print(f"[stitch] scene {sc} auto-stitch skipped: {str(se)[:150]}", flush=True)
            except Exception as e:
                print(f"[stitch] auto-stitch scan failed: {str(e)[:150]}", flush=True)

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
            # Static documentaries route their image stage to run_coverage_stage,
            # whose static branch creates one image per segment; the legacy
            # prompt bot must never run for them.
            "ready_for_image_prompts": (
                self.run_coverage_stage
                if (video.get("render_mode") or "") == "static_docu"
                else self.run_prompts),
            # GOAL v2 Phase 0: the image stages now draw via the unified coverage path
            # (run_coverage_stage), not the old 3x3 grid. Coverage does prompts+images in
            # one paid draw and advances to ready_for_images, so all three map to it.
            "ready_for_storyboards": self.run_coverage_stage,
            "ready_for_storyboard_images": self.run_coverage_stage,
            "ready_for_storyboard_extraction": self.run_coverage_stage,
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

    # --- Unified live image path (GOAL v2 Phase 0) ------------------------------
    # The coverage flow (scripts/coverage_to_app.py) is the single live image
    # generator. These thin wrappers let the co-pilot dock reach it through the
    # normal executor dispatch instead of the old 3x3 grid path (run_prompts/
    # run_images, run_storyboard_prompts/run_storyboard_images). They do NOT change
    # video.status (coverage doesn't), so they are safe for one-off co-pilot actions.
    # NOTE: the run_next_step status map above still routes the image STAGES to the
    # old grid handlers; swapping those to coverage needs status-advance handling +
    # a FINISH/autopilot test and is a follow-up (see HANDOFF-REPORT).
    async def run_coverage_images(self, video_id: str, scene: int = None) -> dict:
        """Draw the real per-shot, multi-angle pictures for a scene (or all scenes)
        via coverage — the live image path. Replaces the old grid run_prompts+run_images."""
        from scripts.coverage_to_app import generate_coverage_for_video
        return await generate_coverage_for_video(video_id, self.tenant_id, scene=scene)

    async def run_storyboard_sheet(self, video_id: str, scene: int = None) -> dict:
        """Draw the cheap single-image storyboard SHEET preview for a scene via
        coverage. Replaces the old grid run_storyboard_prompts+run_storyboard_images."""
        from scripts.coverage_to_app import generate_storyboard_sheet_for_scene
        return await generate_storyboard_sheet_for_scene(video_id, self.tenant_id, scene=scene)

    async def run_coverage_stage(self, video_id: str) -> dict:
        """Unified image STAGE (GOAL v2 Phase 0): draw the real per-shot, multi-angle
        pictures via coverage — the single live image path — mirroring the proven chat
        auto-build image phase (routes/chat.py). This is what the autopilot status map
        and the Claude orchestrator now call instead of the old 3x3 grid handlers
        (run_storyboard_prompts/run_storyboard_images), so no entry point produces a
        different result. Satisfies the storyboard gates + writes the Story Bible first
        (same as chat), then stops at ready_for_images (the pictures-review checkpoint)."""
        await self._ensure_initialized()
        bot_name = "Storyboard Bot"
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}
        # STATIC-DOCU videos take one archival image per segment instead of
        # multi-angle coverage (no cast, no story bible) — same branch as the
        # chat auto-build, so every entry point produces the same result.
        if (video.get("render_mode") or "") == "static_docu":
            await self._log_activity(bot_name, video_id, "started",
                                     "Creating one image per segment (static documentary)")
            from static_docu import generate_static_images_for_video
            st = await generate_static_images_for_video(video_id, self.tenant_id) or {}
            if st.get("status") == "completed":
                await execute(
                    "UPDATE videos SET status = 'ready_for_images', updated_at = now() "
                    "WHERE id = $1 AND tenant_id = $2",
                    video_id, self.tenant_id)
                await self._log_activity(bot_name, video_id, "completed",
                                         st.get("message") or "Segment images created")
                return {"status": "ready_for_images", "video_id": video_id}
            err = st.get("error") or "Couldn't create the segment images."
            await self._log_activity(bot_name, video_id, "failed", err)
            return {"status": "failed", "error": err}
        # Satisfy the storyboard gates + write the Story Bible (continuity anchor),
        # exactly as the chat auto-build does before calling coverage.
        await execute(
            "UPDATE videos SET environments_approved_at = COALESCE(environments_approved_at, now()), "
            "characters_approved_at = COALESCE(characters_approved_at, now()), updated_at = now() "
            "WHERE id = $1 AND tenant_id = $2",
            video_id, self.tenant_id)
        try:
            await self.run_story_bible(video_id)
        except Exception:  # noqa: BLE001 — bible is best-effort, coverage still draws
            pass
        await self._log_activity(bot_name, video_id, "started",
                                 "Drawing the storyboard pictures (coverage)")
        from scripts.coverage_to_app import generate_coverage_for_video
        cov = await generate_coverage_for_video(video_id, self.tenant_id) or {}
        if cov.get("status") == "completed":
            await execute(
                "UPDATE videos SET status = 'ready_for_images', updated_at = now() "
                "WHERE id = $1 AND tenant_id = $2",
                video_id, self.tenant_id)
            await self._log_activity(bot_name, video_id, "completed",
                                     "Storyboard pictures drawn (coverage)")
            return {"status": "ready_for_images", "video_id": video_id}
        err = cov.get("error") or "Couldn't draw the pictures."
        await self._log_activity(bot_name, video_id, "failed", err)
        return {"status": "failed", "error": err}

    async def run_characters(self, video_id: str, scene: int = None) -> dict:
        """Design/redesign the cast — the 4-view character reference sheets the storyboard
        anchors on. Reuses the Characters-tab generator (routes.characters helpers) so the
        co-pilot dock ('redesign the cast') produces the same sheets as the tab button."""
        from routes.characters import _extract_cast, _generate_portrait, _persist_portrait_url
        from vault import get_secret
        video = await fetch_one(
            "SELECT * FROM videos WHERE id=$1 AND tenant_id=$2", video_id, self.tenant_id)
        if not video:
            return {"status": "failed", "error": "video not found"}
        video = dict(video)
        video["tenant_id"] = self.tenant_id

        # LOCKED CHANNEL CAST: the creator's own sheets are brand assets — no
        # generation, no approval step. Import the project cast, build the
        # sheet, stamp the approval, done. This is also what lets queued /
        # autopilot videos pass the cast gate autonomously.
        if video.get("project_id"):
            proj = await fetch_one(
                "SELECT cast_locked, character_references FROM projects "
                "WHERE id = $1 AND tenant_id = $2",
                video["project_id"], self.tenant_id,
            )
            refs = (proj or {}).get("character_references")
            if isinstance(refs, str):
                import json as _cast_json
                try:
                    refs = _cast_json.loads(refs)
                except (ValueError, TypeError):
                    refs = []
            refs = [c for c in (refs or [])
                    if isinstance(c, dict) and c.get("reference_url")
                    # `always: false` members are optional extras — imported per
                    # video via the Use Saved Cast picker, never auto-attached.
                    and c.get("always", True)]
            if proj and proj.get("cast_locked") and refs:
                from routes.characters import _build_cast_sheet, _sync_bible_to_cast
                existing = await fetch_all(
                    "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2",
                    video_id, self.tenant_id,
                )
                existing_names = {r["name"] for r in (existing or [])}
                for i, c in enumerate(refs):
                    if (c.get("name") or f"Character {i+1}") in existing_names:
                        continue
                    await execute(
                        "INSERT INTO video_characters (tenant_id, video_id, name, description, "
                        "reference_url, source, status, sort, voice_name) "
                        "VALUES ($1,$2,$3,$4,$5,'project','approved',$6,$7)",
                        self.tenant_id, video_id, (c.get("name") or f"Character {i+1}")[:120],
                        (c.get("description") or "")[:1000], c["reference_url"], i,
                        # Channel voice pin rides the locked cast (Ryan=Adam,
                        # Vanessa=Pamela) — auto-cast only fills BLANK voices,
                        # so a pinned voice survives every future video.
                        c.get("voice_name"),
                    )
                await execute(
                    "UPDATE video_characters SET status = 'approved', updated_at = now() "
                    "WHERE video_id = $1 AND tenant_id = $2",
                    video_id, self.tenant_id,
                )
                cast_rows = await fetch_all(
                    "SELECT name, reference_url FROM video_characters "
                    "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
                    "ORDER BY sort, created_at",
                    video_id, self.tenant_id,
                )
                cast_list = [dict(r) for r in cast_rows]
                sheet_url = await _build_cast_sheet(self.tenant_id, video_id, cast_list)
                await _sync_bible_to_cast(video_id, self.tenant_id, [
                    {**c, "description": c.get("description") or ""} for c in refs
                ])
                await execute(
                    "UPDATE videos SET characters_approved_at = now(), character_reference_url = $1, "
                    "updated_at = now() WHERE id = $2 AND tenant_id = $3",
                    sheet_url or refs[0]["reference_url"], video_id, self.tenant_id,
                )
                return {"status": "completed",
                        "message": f"Using your locked channel cast ({len(cast_list)} characters) — no generation needed."}

        api_key = await get_secret("kie_ai_api_key", str(self.tenant_id))
        if not api_key:
            return {"status": "failed", "error": "Add your Kie.ai API key in Settings → Keys first."}
        style_dna = video.get("image_style_override") or ""
        cast = await _extract_cast(video, api_key)
        if not cast:
            return {"status": "failed", "error": "No recurring characters found in this script."}
        # Replace prior generated drafts; keep uploaded/imported ones. Reset the approval.
        await execute("DELETE FROM video_characters WHERE video_id=$1 AND tenant_id=$2 "
                      "AND source='generated' AND status='draft'", video_id, self.tenant_id)
        await execute("UPDATE videos SET characters_approved_at = NULL WHERE id=$1 AND tenant_id=$2",
                      video_id, self.tenant_id)
        done = 0
        for i, ch in enumerate(cast):
            row = await fetch_one(
                "INSERT INTO video_characters (tenant_id, video_id, name, description, sort) "
                "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                self.tenant_id, video_id, ch["name"][:120], ch.get("description") or "", i)
            char_id = str(row["id"])
            for attempt in range(3):
                try:
                    temp_url = await _generate_portrait(api_key, ch.get("description") or ch["name"], style_dna, name=ch.get("name") or "")
                    url = await _persist_portrait_url(self.tenant_id, video_id, char_id, temp_url)
                    await execute("UPDATE video_characters SET reference_url=$1, updated_at=now() WHERE id=$2",
                                  url, char_id)
                    done += 1
                    break
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(2 * (attempt + 1))
        return {"status": "completed",
                "message": f"Cast designed: {done}/{len(cast)} character sheets ready — review, then approve."}

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

            # Pipeline integrity check: voice must exist before image prompts (full runs only).
            # Skipped when the video opted out of AI voice-over (skip_voice).
            if scene is None and not video.get("skip_voice"):
                all_voiced, total, voiced = await self._check_voice_exists(video_id)
                if not all_voiced:
                    # Fail without touching status: demoting here regressed a
                    # status the voice bot had legitimately advanced, trapping
                    # the video behind the ready_for_voice approval gate.
                    msg = f"Voice generation must complete before image prompts. Missing voice for {total - voiced}/{total} scenes."
                    await self._log_activity(bot_name, video_id, "failed", msg)
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
            # Deliver the channel look to the neutral image profile (per-video
            # override else channel style_description). This stage doesn't go
            # through _load_prompt_overrides, so set it here.
            await self._export_visual_style(video)

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

            # Gate: environments must be designed+approved (or explicitly
            # skipped) before ANY storyboard prompts — bulk or per-scene — so
            # backgrounds get locked instead of silently drifting.
            env_gate = await self._environments_ready_gate(video_id, video)
            if env_gate:
                await self._log_activity(bot_name, video_id, "failed", env_gate)
                return {"status": "failed", "error": env_gate}

            await self._log_activity(bot_name, video_id, "started", f"Generating storyboard prompts{scene_label}")

            self._load_idea_from_video(video_id)
            # Deliver the channel look to the neutral image profile.
            await self._export_visual_style(video)

            # Reconcile the Story Bible's character costumes with the APPROVED
            # cast BEFORE writing prompts. The bible is generated from the script
            # and invents its own outfits (Tom in a hoodie, Dad in glasses) that
            # contradict the approved portraits — and the storyboard prompt text
            # then overrides the cast-sheet image, so characters drift. The
            # approved descriptions (vision pass from the portraits) are the
            # source of truth. Runs every prompt build so re-approvals propagate.
            try:
                cast_rows = await fetch_all(
                    "SELECT name, description FROM video_characters "
                    "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
                    "ORDER BY sort, created_at",
                    video_id, self.tenant_id,
                )
                if cast_rows:
                    from routes.characters import _sync_bible_to_cast
                    await _sync_bible_to_cast(video_id, self.tenant_id, [dict(r) for r in cast_rows])
            except Exception as e:
                _logger.warning("[storyboard] bible<-cast sync skipped: %s", str(e)[:150])

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
            # Deliver the channel look (storyboard keyframe prompts + grids).
            await self._export_visual_style(video)

            # Per-video output shape, chosen at creation. The grid generation
            # request honors it; the model has historically ignored aspect on
            # some paths, so the deterministic backstop (panel normalization)
            # is still owed — see the aspect_ratio handoff. Defaults to 16:9.
            self._pipeline.aspect_ratio = video.get("aspect_ratio") or "16:9"

            gate = await self._load_character_refs(video_id, video)
            if gate and scene is None:
                await self._log_activity(bot_name, video_id, "failed", gate)
                return {"status": "failed", "error": gate}

            # Gate: environments must be done (approved or explicitly skipped)
            # before grids — bulk OR per-scene. After it passes,
            # _load_environment_refs populates the {location: ref} map the bot
            # conditions each grid on (empty when the video was skipped).
            env_gate = await self._environments_ready_gate(video_id, video)
            if env_gate:
                await self._log_activity(bot_name, video_id, "failed", env_gate)
                return {"status": "failed", "error": env_gate}
            await self._load_environment_refs(video_id, video)

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
            # Assets whose picture got replaced under an existing clip —
            # their clips re-animate after extraction (Ryan's answer 2).
            stale_clip_assets = []

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
                            rows=rows, cols=cols, expected_panels=expected,
                        )
                        for p in panels:
                            flags = p.get("flags") or []
                            existing = await fetch_one(
                                """SELECT id, video_clip_url FROM assets
                                   WHERE video_id = $1 AND scene = $2 AND image_index = $3
                                   AND tenant_id = $4""",
                                video_id, scene_num, p["image_index"], self.tenant_id,
                            )
                            if existing:
                                asset_id = existing["id"]
                                if existing.get("video_clip_url"):
                                    stale_clip_assets.append(asset_id)
                                await execute(
                                    """UPDATE assets SET image_url = $1, status = 'done',
                                              generation_method = 'storyboard_extract',
                                              extraction_flags = $2, updated_at = now()
                                       WHERE id = $3""",
                                    p["panel_url"], flags or None, asset_id,
                                )
                            elif slot_total == 0:
                                asset_id = str(uuid.uuid4())
                                await execute(
                                    """INSERT INTO assets
                                       (id, tenant_id, video_id, video_title, scene, image_index,
                                        image_url, status, generation_method, extraction_flags,
                                        created_at, updated_at)
                                       VALUES ($1, $2, $3, $4, $5, $6, $7, 'done',
                                               'storyboard_extract', $8, now(), now())""",
                                    asset_id, self.tenant_id, video_id, video_title,
                                    scene_num, p["image_index"], p["panel_url"], flags or None,
                                )
                            else:
                                # Orphan guard: more crops than story slots means
                                # the grid geometry drifted (the bird video got 12
                                # story-less rows this way — no sentence, no
                                # prompt, un-renderable). Never invent rows the
                                # script doesn't have.
                                print(f"[extract] S{scene_num}.{p['image_index']} has no "
                                      f"story slot (scene has {slot_total}) — skipping "
                                      f"orphan crop", flush=True)
                                scene_errors.append(
                                    f"Scene {scene_num}: crop {p['image_index']} exceeds "
                                    f"the scene's {slot_total} pictures (skipped)")
                                continue
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
                            upscaled_url = await upload_from_url(result["url"], path, tenant_id=self.tenant_id)
                            await execute(
                                "UPDATE assets SET image_url = $1, updated_at = now() WHERE id = $2",
                                upscaled_url, asset_id,
                            )
                            upscaled += 1
                    except Exception as e:
                        _logger.warning("Upscale failed for panel %d: %s — keeping original", idx, e)

                msg += f", {upscaled}/{len(all_panel_records)} upscaled"

            # AUTO RE-ANIMATE (Ryan's answer 2): pictures replaced under an
            # existing clip regenerate that clip — only clips that already
            # existed, ~$0.10 each, no human in the loop.
            if stale_clip_assets:
                await _report(f"Pictures changed — re-animating {len(stale_clip_assets)} stale clip(s)…")
                reanimated = 0
                for aid in stale_clip_assets:
                    res = await self.run_clip_generation(video_id, asset_id=aid, force=True)
                    if res.get("clips_generated"):
                        reanimated += res["clips_generated"]
                msg += f" — re-animated {reanimated}/{len(stale_clip_assets)} stale clip(s)"

            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": to_supabase(new_status), "video_id": video_id, "panels_extracted": total_panels}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_fix_text_card(self, video_id: str, asset_id: str) -> dict:
        """One-tap 'Fix text': redraw a title/word card via GPT Image 2 (best-in-class
        for legible lettering — nano-banana garbles text). Uses the current panel as the
        art-style + layout reference and its image_prompt/narration for the intended
        wording. Scenes stay on nano-banana; only the tapped card is redrawn, replaced in
        place. Any clip made from the old card is cleared so it re-animates."""
        bot_name = "Fix Text"
        try:
            await self._ensure_initialized()
            asset = await fetch_one(
                "SELECT scene, image_index, image_prompt, sentence_text, image_url, "
                "drive_image_url FROM assets WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
                asset_id, video_id, self.tenant_id,
            )
            if not asset:
                return {"status": "failed", "error": "Picture not found"}
            ref_url = asset.get("drive_image_url") or asset.get("image_url")
            if not ref_url:
                return {"status": "failed", "error": "This card has no picture yet to fix"}
            client = getattr(self._pipeline, "image_client", None)
            if not client:
                return {"status": "failed", "error": "Image generator unavailable right now"}

            video = await self._get_video(video_id)
            aspect = (video or {}).get("aspect_ratio") or "16:9"
            style = ((video or {}).get("image_style_override") or "").strip()
            intent = (asset.get("sentence_text") or asset.get("image_prompt") or "").strip()
            # Keep the prompt LEAN — the reference image carries the art style/layout; the
            # model's job is legible text. A long/noisy prompt risks confusing it (and can
            # trip provider errors), so cap the style + wording we append.
            prompt = (
                "Redraw this title/word card keeping the EXACT same art style, colours, and "
                "layout as the reference image, but render all on-card text large, perfectly "
                "legible, correctly spelled, and cleanly typeset. Keep it a clean card — same "
                "scene, no new characters or scenery, no watermarks."
                f"{(' Art style: ' + style[:280] + '.') if style else ''}"
                f"{(' Intended wording/content: ' + intent[:280] + '.') if intent else ''}"
            )
            sc, idx = asset["scene"], asset["image_index"]
            await self._log_activity(bot_name, video_id, "started", f"Fixing text on S{sc}.{idx} (GPT Image 2)…")
            res = await client.generate_thumbnail_gpt2(prompt, [ref_url], aspect_ratio=aspect)
            new_url = (res or {}).get("url")
            if not new_url:
                await self._log_activity(bot_name, video_id, "failed", "GPT Image 2 didn't return a card — try again.")
                return {"status": "failed", "error": "The text fix didn't generate — tap Fix text to try again."}

            durable = await self._persist_url(new_url, f"{video_id}/images/S{sc}-{idx}_text.png")
            await execute(
                "UPDATE assets SET image_url = $1, drive_image_url = $1, video_clip_url = NULL, "
                "updated_at = now() WHERE id = $2 AND tenant_id = $3",
                durable, asset_id, self.tenant_id,
            )
            await self._log_activity(bot_name, video_id, "completed", f"Text fixed on S{sc}.{idx}")
            return {"status": "completed", "video_id": video_id,
                    "message": "Card text redrawn with GPT Image 2 — re-animate it to refresh its clip.",
                    "image_url": durable}
        except Exception as e:
            await self._log_activity(bot_name, video_id, "failed", str(e))
            return {"status": "failed", "error": str(e)}

    async def run_recrop_panel(self, video_id: str, asset_id: str) -> dict:
        """One-tap 'Re-crop this picture' (Ryan's bad-crop rule, answer 4).

        A split crop never comes alone — wrong geometry breaks every panel
        on its grid — so this re-crops the tapped asset's whole BEAT with
        the self-healing layout in extract_grid and refreshes every asset
        the beat covers. Pure PIL, free, replaces Drive content in place
        (same file ids; the md5-ETag proxy busts caches).
        """
        bot_name = "Re-crop"
        try:
            asset = await fetch_one(
                "SELECT scene, image_index FROM assets "
                "WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
                asset_id, video_id, self.tenant_id,
            )
            if not asset:
                return {"status": "failed", "error": "Picture not found"}
            scene_num, image_index = asset["scene"], asset["image_index"]

            sc = await fetch_one(
                "SELECT storyboard_1_url, storyboard_2_url, storyboard_3_url, "
                "storyboard_4_url, storyboard_5_url FROM scripts "
                "WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
                video_id, scene_num, self.tenant_id,
            )
            beat_urls = [(i, sc.get(f"storyboard_{i}_url")) for i in range(1, 6)
                         if sc and sc.get(f"storyboard_{i}_url")]
            if not beat_urls:
                return {"status": "failed", "error": "This scene has no storyboard grids to re-crop from"}

            slot_rows = await fetch_all(
                "SELECT id, image_index FROM assets WHERE video_id = $1 AND scene = $2 "
                "AND tenant_id = $3 AND sentence_text IS NOT NULL ORDER BY image_index",
                video_id, scene_num, self.tenant_id,
            )
            slot_total = len(slot_rows)

            # Same greedy 9-per-beat chunking the grids were built with —
            # find the beat whose index range covers the tapped picture.
            from extraction import extract_grid, grid_layout_for
            offset = 0
            target = None
            for bi, (beat_num, grid_url) in enumerate(beat_urls):
                take = min(9, max(0, slot_total - offset))
                if offset < image_index <= offset + take or (take == 0 and bi == len(beat_urls) - 1):
                    target = (beat_num, grid_url, offset, take)
                    break
                offset += take
            if not target:
                return {"status": "failed", "error": "Couldn't match this picture to a storyboard grid"}

            beat_num, grid_url, panel_offset, expected = target
            rows, cols = grid_layout_for(expected) if expected > 0 else (0, 0)
            await self._log_activity(bot_name, video_id, "started",
                                     f"Re-cropping S{scene_num} beat {beat_num}")
            panels = await extract_grid(grid_url, video_id, scene_num, beat_num,
                                        panel_offset, rows=rows, cols=cols,
                                        expected_panels=expected)
            # Which of the beat's assets already had a clip? Their clips go
            # stale the moment the picture under them changes.
            beat_range = await fetch_all(
                "SELECT id, image_index, video_clip_url FROM assets "
                "WHERE video_id = $1 AND scene = $2 AND tenant_id = $3 "
                "AND image_index > $4 AND image_index <= $5",
                video_id, scene_num, self.tenant_id,
                panel_offset, panel_offset + max(expected, len(panels)),
            )
            had_clip = {r["image_index"]: r["id"] for r in beat_range if r.get("video_clip_url")}

            updated = 0
            stale_clip_assets = []
            for p in panels:
                flags = p.get("flags") or []
                await execute(
                    """UPDATE assets SET image_url = $1, status = 'done',
                              generation_method = 'storyboard_extract',
                              extraction_flags = $2, updated_at = now()
                       WHERE video_id = $3 AND scene = $4 AND image_index = $5
                       AND tenant_id = $6""",
                    p["panel_url"], flags or None, video_id, scene_num,
                    p["image_index"], self.tenant_id,
                )
                updated += 1
                if p["image_index"] in had_clip:
                    stale_clip_assets.append(had_clip[p["image_index"]])

            still_bad = sum(1 for p in panels if p.get("flags"))
            msg = (f"Re-cropped {updated} picture(s) on S{scene_num} beat {beat_num}"
                   + (f" — {still_bad} still flagged" if still_bad else ""))

            # AUTO RE-ANIMATE (Ryan's answer 2): a redone picture regenerates
            # its clip — only clips that already existed, ~$0.10 each, fully
            # unattended (north star: no human in the loop).
            reanimated = 0
            for aid in stale_clip_assets:
                res = await self.run_clip_generation(video_id, asset_id=aid, force=True)
                if res.get("clips_generated"):
                    reanimated += res["clips_generated"]
            if stale_clip_assets:
                msg += f" — re-animated {reanimated}/{len(stale_clip_assets)} stale clip(s) (~${0.10 * reanimated:.2f})"

            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": "completed", "video_id": video_id, "message": msg,
                    "panels": updated, "still_flagged": still_bad,
                    "reanimated": reanimated}

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
                        upscaled_url = await upload_from_url(result["url"], path, tenant_id=self.tenant_id)
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
            # Skipped when the video opted out of AI voice-over (skip_voice).
            if scene is None and not video.get("skip_voice"):
                all_voiced, total, voiced = await self._check_voice_exists(video_id)
                if not all_voiced:
                    # Fail without touching status: demoting here regressed a
                    # status the voice bot had legitimately advanced, trapping
                    # the video behind the ready_for_voice approval gate.
                    msg = f"Voice generation must complete before image generation. Missing voice for {total - voiced}/{total} scenes."
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    return {"status": "failed", "error": msg}

            if scene is not None and index is not None:
                log_msg = f"Generating image for scene {scene} segment {index}"
            elif scene is not None:
                log_msg = f"Generating images for scene {scene}"
            else:
                log_msg = "Generating images"
            await self._log_activity(bot_name, video_id, "started", log_msg)

            self._load_idea_from_video(video_id)
            # Deliver the channel look (drives characters/environments + any
            # prompt rebuilds). This stage doesn't go through _load_prompt_overrides.
            await self._export_visual_style(video)

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

    async def _run_channel_formula_thumbnail(
        self, video_id: str, video: dict
    ) -> Optional[dict]:
        """Own-brand thumbnail modeling: take the channel's OWN top-performing
        thumbnail, extract its structured JSON blueprint (vision pass, cached on
        channel_identity.thumbnail_blueprint), transform it onto THIS video's
        title, and generate. The same proven blueprint machinery as competitor
        modeling — the reference is simply the channel itself.

        Returns the completed result dict, or None to fall through to the
        legacy from-scratch designer (no own thumbnails / no Claude creds)."""
        import json as _json_cf
        from routes.model_video import _resolve_claude_creds, _describe_thumbnail_style

        bot_name = "Thumbnail Bot"
        top = await fetch_one(
            "SELECT thumbnail_url FROM channel_videos "
            "WHERE tenant_id = $1 AND thumbnail_url IS NOT NULL "
            "ORDER BY view_count DESC NULLS LAST LIMIT 1", self.tenant_id)
        if not (top and top.get("thumbnail_url")):
            return None
        creds = await _resolve_claude_creds(self.tenant_id)
        if not creds:
            return None

        # Blueprint: cached on the identity, or extracted now from the top thumb.
        blueprint = None
        row = await fetch_one(
            "SELECT channel_identity->>'thumbnail_blueprint' AS bp "
            "FROM channel_profiles WHERE tenant_id = $1", self.tenant_id)
        if row and (row.get("bp") or "").strip().startswith("{"):
            blueprint = row["bp"]
        if not blueprint:
            await self._log_activity(
                bot_name, video_id, "started",
                "Reading the channel's own top thumbnail formula (vision)")
            blueprint = await _describe_thumbnail_style(creds, top["thumbnail_url"])
            if not (blueprint or "").strip():
                return None
            try:
                await execute(
                    "UPDATE channel_profiles SET channel_identity = "
                    "COALESCE(channel_identity, '{}'::jsonb) || "
                    "jsonb_build_object('thumbnail_blueprint', $2::text) "
                    "WHERE tenant_id = $1", self.tenant_id, blueprint)
            except Exception:  # noqa: BLE001 — cache is a bonus
                pass

        # Channel constants the model must not reinterpret:
        # 1) consensus formula (3-thumbnail extraction) as the style tie-breaker;
        # 2) the REAL background color, MEASURED as the median of a border ring
        #    on the maxres thumbnail (corner-averaging a letterboxed hqdefault
        #    sampled salmon-pink, live on DVU — median ring on maxres is robust).
        consensus = ""
        try:
            row = await fetch_one(
                "SELECT channel_identity->'thumbnail_style' AS ts "
                "FROM channel_profiles WHERE tenant_id = $1", self.tenant_id)
            ts = (row or {}).get("ts")
            if isinstance(ts, str):
                ts = _json_cf.loads(ts)
            if isinstance(ts, dict) and ts:
                consensus = _json_cf.dumps(ts, indent=1)
        except Exception:  # noqa: BLE001
            pass
        hexbg = await self._measure_channel_thumb_bg()

        # This video's REAL subject(s): the machines from the static segments.
        subjects = ""
        seed = None
        try:
            rows = await fetch_all(
                "SELECT image_url, caption FROM assets WHERE video_id=$1 AND tenant_id=$2 "
                "AND image_url IS NOT NULL AND generation_method='static_docu' "
                "ORDER BY scene", video_id, self.tenant_id)
            names = []
            for r in rows:
                cap = r.get("caption")
                if isinstance(cap, str):
                    cap = _json_cf.loads(cap)
                if isinstance(cap, dict) and cap.get("title"):
                    names.append(cap["title"])
            subjects = ", ".join(names[:5])
            if rows:
                seed = rows[0].get("image_url")
        except Exception:  # noqa: BLE001
            pass

        await self._log_activity(
            bot_name, video_id, "started",
            "Modeling the channel's own thumbnail formula onto this video")

        # A creator-edited prompt always wins (Regenerate refines it). It can be
        # the full structured JSON spec (preferred, editable field-by-field) or
        # plain text — both work.
        saved = (video.get("thumbnail_prompt") or "").strip()
        spec = None
        gen_prompt = None
        if saved:
            if saved.startswith("{"):
                try:
                    spec = _json_cf.loads(saved)
                except ValueError:
                    gen_prompt = saved
            else:
                gen_prompt = saved
        if spec is None and gen_prompt is None:
            spec = await self._transform_channel_thumbnail_spec(
                creds, blueprint, consensus, hexbg,
                video.get("video_title") or "", subjects)
        if spec is not None:
            gen_prompt = (spec.get("prompt") or "").strip()
            neg = (spec.get("negative_prompt") or "").strip()
            if neg:
                gen_prompt += f"\n\nAvoid (negative prompt): {neg}"
            bg = ((spec.get("color_palette") or {}).get("background") or "").strip()
            if bg:
                gen_prompt += f"\n\nBACKGROUND (exact, non-negotiable): {bg}."
        if not gen_prompt:
            return None
        # What the creator sees/edits in the UI prompt box: the full spec.
        stored_prompt = (_json_cf.dumps(spec, indent=2) if spec is not None else gen_prompt)

        client = self._pipeline.image_client
        thumb_ar = video.get("aspect_ratio") or "16:9"

        # Subject fidelity: seed with THIS video's own hero segment image when
        # one exists (static docs: the real featured machine in the channel's
        # studio look) so the thumbnail shows our actual subject, not an
        # invented one. Text-to-image is the fallback.
        res = None
        if seed:
            res = await client.generate_thumbnail_gpt2(
                gen_prompt + "\nUse the machine in the reference image as the "
                "thumbnail's subject — same vehicle, same configuration, no "
                "invented markings.",
                [seed], aspect_ratio=thumb_ar)
        if not (res or {}).get("url"):
            res = await client.generate_scene_image_gpt(gen_prompt, None, aspect_ratio=thumb_ar)
        url = (res or {}).get("url")
        if not url:
            await self._log_activity(
                bot_name, video_id, "failed",
                "Channel-formula thumbnail returned no image")
            return {"status": "failed", "error": user_facing(
                "The thumbnail didn't generate this time — tap Regenerate to try again.")}
        durable = await self._persist_url(url, f"{video_id}/thumbnails/thumb.png")
        await execute(
            "UPDATE videos SET thumbnail_url = $1, thumbnail_prompt = $2, "
            "updated_at = now() WHERE id = $3 AND tenant_id = $4",
            durable, stored_prompt, video_id, self.tenant_id)
        await self._log_activity(
            bot_name, video_id, "completed",
            "Thumbnail modeled from the channel's own formula")
        return {"status": "completed", "video_id": video_id,
                "thumbnail_url": durable}

    async def _measure_channel_thumb_bg(self) -> Optional[str]:
        """The channel's real thumbnail background color as an exact hex.

        Median of a border ring sampled on the MAXRES thumbnail of the top
        video (median beats averaging: compression noise and letterbox bars
        can't drag it; near-black letterbox pixels are dropped explicitly).
        Returns None when unmeasurable — callers must treat it as optional."""
        try:
            import io as _io_bg
            import httpx as _httpx_bg
            from PIL import Image as _Image_bg

            top = await fetch_one(
                "SELECT video_id, thumbnail_url FROM channel_videos "
                "WHERE tenant_id = $1 AND thumbnail_url IS NOT NULL "
                "ORDER BY view_count DESC NULLS LAST LIMIT 1", self.tenant_id)
            if not top:
                return None
            urls = []
            if top.get("video_id"):
                urls.append(f"https://i.ytimg.com/vi/{top['video_id']}/maxresdefault.jpg")
            urls.append(top.get("thumbnail_url"))
            data = None
            async with _httpx_bg.AsyncClient(timeout=30.0, follow_redirects=True) as c:
                for u in urls:
                    if not u:
                        continue
                    rr = await c.get(u)
                    if rr.status_code == 200 and len(rr.content) > 5000:
                        data = rr.content
                        break
            if not data:
                return None
            im = _Image_bg.open(_io_bg.BytesIO(data)).convert("RGB")
            w, h = im.size
            inset = max(6, w // 100)
            pts = []
            for i in range(12):
                x = inset + (w - 2 * inset) * i // 11
                pts += [(x, inset), (x, h - 1 - inset)]
            for i in range(6):
                y = inset + (h - 2 * inset) * i // 5
                pts += [(inset, y), (w - 1 - inset, y)]
            cols = [im.getpixel(p) for p in pts]
            lit = [c for c in cols if sum(c) > 60]  # drop letterbox bars
            cols = lit or cols
            med = tuple(sorted(c[i] for c in cols)[len(cols) // 2] for i in range(3))
            return "#%02X%02X%02X" % med
        except Exception:  # noqa: BLE001
            return None

    async def _transform_channel_thumbnail_spec(
        self, creds: dict, blueprint: str, consensus: str,
        hexbg: Optional[str], title: str, subjects: str,
    ) -> Optional[dict]:
        """Blueprint + consensus + measured constants + OUR topic -> the FULL
        structured thumbnail spec (format/style/scene/objects/composition/
        text/color_palette/prompt/negative_prompt). The spec is the editable
        source of truth; the flat generation prompt is derived from it."""
        import json as _json_ts
        from routes.model_video import _call_claude, _strip_code_fences

        brand = ""
        try:
            from routes.model_video import _fetch_channel_brand
            brand = await _fetch_channel_brand(self.tenant_id)
        except Exception:  # noqa: BLE001
            pass

        ask = (
            "You design YouTube thumbnails by MODELING a channel's proven formula "
            "onto a new video — never copying the reference image, always rebuilding "
            "its winning structure with our subject.\n\n"
            f"CHANNEL BLUEPRINT (vision-extracted from its top thumbnail):\n{blueprint}\n\n"
            + (f"CHANNEL CONSENSUS (across its top 3 thumbnails — wins any conflict "
               f"with the blueprint):\n{consensus}\n\n" if consensus else "")
            + (f"MEASURED CONSTANTS (authoritative, pixel-sampled from the channel's "
               f"real thumbnails — override any color words above): background = a "
               f"clean uniform studio backdrop of exactly {hexbg}.\n\n" if hexbg else "")
            + f"OUR VIDEO TITLE: {title}\n"
            + (f"OUR REAL SUBJECT(S): {subjects} — a reference image of the featured "
               "machine is supplied at generation time; the spec must describe THAT "
               "real machine, never an invented design.\n" if subjects else "")
            + (f"CHANNEL BRAND: {brand}\n" if brand else "")
            + "\nReply with ONE JSON object only, with EXACTLY these keys:\n"
            '{"format": "youtube_thumbnail", "aspect_ratio": "16:9",\n'
            ' "style": {"medium","look","lighting","mood"},\n'
            ' "scene": {"setting","main_action","click_moment","focal_point","secondary_focal_point"},\n'
            ' "objects": [{"object","description","position"}],\n'
            ' "composition": {"camera","layout","depth_of_field","thumbnail_rules"},\n'
            ' "text": {"primary_text": {"content","placement","style"},'
            ' "secondary_text": {...}, "small_text": {...}},\n'
            ' "color_palette": {"background","main_object","text_primary","text_secondary","badge","accent"},\n'
            ' "prompt": "<one rich self-contained generation prompt consistent with every field above>",\n'
            ' "negative_prompt": "<thorough>"}\n\n'
            "Rules:\n"
            "- Every field detailed and concrete (positions, sizes as % of frame, exact hexes).\n"
            "- The subject is the REAL machine named above — accurate configuration, and "
            "ABSOLUTELY NO invented text/stencils/markings on the vehicle.\n"
            "- color_palette.background must be the measured hex verbatim when given.\n"
            "- Text uses the channel's split-color treatment from the formula.\n"
            "- The 'prompt' field must restate the background hex and the no-invented-text rule."
        )
        try:
            raw = await _call_claude(ask, creds, tier="smart", max_tokens=4000)
            spec = _json_ts.loads(_strip_code_fences(raw))
            return spec if isinstance(spec, dict) and spec.get("prompt") else None
        except Exception as e:  # noqa: BLE001
            _logger.warning("channel thumbnail spec transform failed: %s", str(e)[:200])
            return None

    async def _build_modeled_thumbnail_prompt(
        self, video_id: str, video: dict, ref_yt: str, has_cast: bool
    ) -> str:
        """JSON-blueprint modeling: turn the reference thumbnail into OUR modeled
        thumbnail prompt — our story + our channel brand, in the reference's proven
        winning formula. Reads the structured blueprint (stored at modeling time, or
        generated on the fly for older videos), transforms it against our title/brand/
        cast via Claude, and returns a single rich generation prompt (negatives baked
        in, content-safety enforced). Falls back to the text-assembly builder if the
        LLM path is unavailable so Regenerate never dead-ends."""
        try:
            from routes.model_video import (
                _resolve_claude_creds, _describe_thumbnail_style,
                _model_thumbnail_prompt, _fetch_channel_brand)
            creds = await _resolve_claude_creds(self.tenant_id)
            if creds:
                blueprint = (video.get("thumbnail_style_override") or "").strip()
                if not blueprint.startswith("{"):
                    # Older video without a stored JSON blueprint — read it now.
                    ref_thumb = f"https://img.youtube.com/vi/{ref_yt}/maxresdefault.jpg"
                    blueprint = (await _describe_thumbnail_style(creds, ref_thumb)) or blueprint
                brand = await _fetch_channel_brand(self.tenant_id)
                names = ""
                try:
                    rows = await fetch_all(
                        "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2 ORDER BY sort",
                        video_id, self.tenant_id)
                    names = ", ".join((r.get("name") or "").strip() for r in rows if r.get("name"))
                except Exception:
                    pass
                modeled = await _model_thumbnail_prompt(
                    creds, blueprint, video.get("video_title") or "", brand, names, has_cast)
                if modeled:
                    return modeled
        except Exception as e:
            await self._log_activity(
                "Thumbnail Bot", video_id, "running",
                f"JSON modeling unavailable, using fallback ({str(e)[:100]})")
        return await self._build_thumbnail_model_prompt(video_id, video, has_cast=has_cast)

    async def _build_thumbnail_model_prompt(
        self, video_id: str, video: dict, has_cast: bool = True
    ) -> str:
        """Modeled thumbnail prompt (MODEL, not copy): design OUR OWN thumbnail of
        OUR video's moment — driven by our title — applying the reference's winning
        FORMULA + STYLE (stored in thumbnail_style_override) and proven thumbnail
        rules. Never traces the reference's image. has_cast=True frames it around the
        cast sheet (character videos, image-to-image); has_cast=False frames a faceless
        EVENT/iconography scene (explainer/documentary, text-to-image). Seeded into
        thumbnail_prompt for in-app refine."""
        names = ""
        try:
            rows = await fetch_all(
                "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2 ORDER BY sort",
                video_id, self.tenant_id)
            names = ", ".join((r.get("name") or "").strip() for r in rows if r.get("name"))
        except Exception:
            pass
        signature = (video.get("thumbnail_style_override") or "").strip()
        text = (video.get("thumbnail_text") or "").strip()
        title = (video.get("video_title") or "").strip()
        ar = video.get("aspect_ratio") or "16:9"
        # Subject is driven by OUR title (drop the "| channel suffix").
        clean_title = title.split("|")[0].strip()

        parts = [
            f"YouTube thumbnail, {ar}. Design a NEW, ORIGINAL thumbnail for OUR video. We are "
            "MODELING a proven competitor's winning thumbnail formula — not copying it: do NOT "
            "reproduce any competitor image, scene, object or composition. Build our own.",
        ]
        if has_cast:
            parts.append(
                "The reference image provided is OUR OFFICIAL CHARACTER CAST SHEET — reproduce these "
                "EXACT characters (same faces, hair, skin tone, ages and clothing) and keep their "
                "rendering style; never invent or substitute anyone.")
            if names:
                parts.append(f"The cast is: {names}.")
            subject = (
                "Stage the single most click-worthy moment this title promises — its surprising "
                "reveal or payoff, caught the instant it happens — as our own original scene with our cast.")
        else:
            parts.append(
                "This is a FACELESS video — there is NO recurring cast. Build our own original scene "
                "or bold iconography; any people are generic and incidental, not a fixed character.")
            subject = (
                "Depict the single most click-worthy MOMENT or visual this title promises — show the "
                "EVENT or the charged subject the instant it lands (not a flat, static object shot). "
                "Use one clear, instantly-readable focal subject plus simple iconography (arrows, "
                "highlights, split-screen, glowing charts) where it sharpens the idea.")
        if clean_title:
            parts.append(f'OUR video is titled "{clean_title}". ' + subject)
        if signature:
            parts.append(
                "Apply this proven winning STYLE and CLICK FORMULA (match the look and the pattern, "
                "but on OUR subject above — never the reference's specific objects): " + signature)
        # Overlay text is part of the MODELED formula: render OUR words in the
        # reference's text TREATMENT and LAYOUT — big and bold, spanning across the
        # screen the same way (same scale, tiers, colors, outline). The text style
        # comes from the signature above; the WORDS are ours.
        if text:
            headline_clause = f'render the headline reading exactly "{text}"'
        else:
            headline_clause = (
                f'render a large, punchy headline that captures OUR title\'s hook (derived from '
                f'"{clean_title}", not a verbatim copy of it)')
        parts.append(
            "MODEL THE TEXT: " + headline_clause + ". Make it BIG and BOLD, spanning across the "
            "screen in the SAME text treatment and layout as the reference described above — match "
            "its scale, number of tiers, color per tier, font weight/case and heavy outline. The "
            "text is a primary element, not a small label.")
        # Proven hard rules (from the YouTube intelligence ruleset).
        parts.append(
            "Follow proven thumbnail rules: ONE clear focal point and at most THREE distinct "
            "elements; exaggerated facial emotion; bright with extreme contrast so it pops in dark "
            "mode; a single 'click-to-unpause' moment; text readable at 120px. No competitor "
            "logos, watermarks or badges.")
        return " ".join(parts)

    async def run_thumbnail(self, video_id: str) -> dict:
        """Generate thumbnail for a video."""
        await self._ensure_initialized()
        bot_name = "Thumbnail Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")

            # ── Modeled mode (model, NOT copy) ────────────────────────
            # When the video was modeled on a reference video (reference_url),
            # design OUR OWN thumbnail of OUR story's moment using the reference's
            # winning FORMULA + STYLE — never tracing the reference's image. Works
            # for ANY video, with or without a cast:
            #   • cast videos    → generate from the CAST SHEET ONLY (it carries our
            #     characters + the modeled look, so the composition stays fresh and
            #     our cast can't be overwritten).
            #   • faceless videos (explainer/documentary, no cast sheet) → build the
            #     scene from text (GPT Image 2 text-to-image); the style signature in
            #     the prompt carries the modeled look.
            # The editable thumbnail_prompt drives refinement: every Regenerate
            # re-runs with whatever prompt is saved. Status stays at ready_for_thumbnail
            # so Regenerate keeps working — the creator clicks Approve & Advance when happy.
            import re as _re_thumb
            _ref = (video.get("reference_url") or "")
            _m = (_re_thumb.search(r"[?&]v=([\w-]{11})", _ref)
                  or _re_thumb.search(r"youtu\.be/([\w-]{11})", _ref)
                  or _re_thumb.search(r"/embed/([\w-]{11})", _ref)
                  or _re_thumb.search(r"/shorts/([\w-]{11})", _ref))
            ref_yt = _m.group(1) if _m else None
            cast_sheet = (video.get("character_reference_url") or "").strip()
            if ref_yt:
                has_cast = bool(cast_sheet)
                await self._log_activity(
                    bot_name, video_id, "started",
                    "Modeling thumbnail on the reference's winning formula"
                    + ("" if has_cast else " (faceless)"))
                prompt = (video.get("thumbnail_prompt") or "").strip()
                if not prompt:
                    prompt = await self._build_modeled_thumbnail_prompt(
                        video_id, video, ref_yt, has_cast)
                client = self._pipeline.image_client
                thumb_ar = video.get("aspect_ratio") or "16:9"
                if has_cast:
                    # CAST SHEET ONLY — the one authoritative seed image (identities +
                    # the modeled look). GPT Image 2 holds character identity best (live
                    # A/B); nano-banana-pro fallback so Regenerate never dead-ends.
                    res = await client.generate_thumbnail_gpt2(
                        prompt, [cast_sheet], aspect_ratio=thumb_ar)
                    if not (res or {}).get("url"):
                        res = await client.generate_with_reference(
                            prompt, [cast_sheet], aspect_ratio=thumb_ar)
                else:
                    # FACELESS — no cast sheet to seed from. Build from text: GPT Image 2
                    # text-to-image. The style signature in the prompt carries the look.
                    res = await client.generate_scene_image_gpt(
                        prompt, None, aspect_ratio=thumb_ar)
                url = (res or {}).get("url")
                if not url:
                    await self._log_activity(bot_name, video_id, "failed",
                                             "Modeled thumbnail returned no image")
                    return {"status": "failed", "error": user_facing(
                        "The thumbnail didn't generate this time — tap Regenerate to try again.")}
                durable = await self._persist_url(url, f"{video_id}/thumbnails/thumb.png")
                await execute(
                    "UPDATE videos SET thumbnail_url = $1, thumbnail_prompt = $2, "
                    "updated_at = now() WHERE id = $3 AND tenant_id = $4",
                    durable, prompt, video_id, self.tenant_id,
                )
                await self._log_activity(bot_name, video_id, "completed",
                                         "Thumbnail modeled from reference")
                return {"status": "completed", "video_id": video_id,
                        "thumbnail_url": durable}

            # ── Channel-formula mode (own-brand modeling) ─────────────
            # No reference video, but the channel HAS its own proven
            # thumbnails (an onboarded existing channel like Designed vs
            # Used): model the channel's own top thumbnail — vision pass →
            # JSON blueprint → transformed onto OUR title — the exact same
            # proven machinery as competitor modeling, pointed at the brand
            # itself. Falls through to the legacy bot on any failure.
            try:
                own = await self._run_channel_formula_thumbnail(video_id, video)
                if own is not None:
                    return own
            except Exception as e:  # noqa: BLE001
                await self._log_activity(
                    bot_name, video_id, "running",
                    f"Channel-formula thumbnail unavailable ({str(e)[:100]}) — using the standard designer")

            # ── From-scratch mode (existing bot) ──────────────────────
            await self._log_activity(bot_name, video_id, "started", "Generating thumbnail")

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            self._load_idea_from_video(video_id)

            # The legacy bot expects the pipeline-format status; override like
            # run_voice does so a regenerate works from any current status.
            if self._pipeline.current_idea:
                self._pipeline.current_idea["Status"] = "Ready For Thumbnail"

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

    async def _run_stitch_render(
        self, video_id: str, video: dict, current_status: str,
        orientation: str = "auto",
    ) -> dict:
        """Fast render for grok_native videos — FFmpeg-stitch the existing
        clips (each already carries Grok's baked-in audio) into the final video.

        Bypasses the Remotion path's two blockers (missing render_config.json;
        Scene.tsx muting clips while playing the narrator). Clips that differ in
        size/orientation are normalized onto one canvas (scale+pad), joined in a
        single encode, and each render works in its own temp dir. orientation:
        'auto'|'portrait'|'landscape'. See render_stitch.py.
        """
        bot_name = "Render Bot"
        await self._log_activity(
            bot_name, video_id, "started", "Stitching clips into final video"
        )

        async def _progress(msg: str) -> None:
            await self._log_activity(bot_name, video_id, "running", msg)

        from render_stitch import stitch_video

        result = await stitch_video(
            video_id,
            self.tenant_id,
            title=video.get("video_title") or "",
            orientation=orientation,
            on_progress=_progress,
        )

        final_url = result["final_video_url"]
        await execute(
            "UPDATE videos SET final_video_url = $1 WHERE id = $2",
            final_url, video_id,
        )
        await self._update_video_status(video_id, to_supabase("rendered"))
        await self._log_transition(video_id, current_status, to_supabase("rendered"), "api")

        duration_min = max(1, round(result.get("duration_seconds", 0) / 60))
        await self._charge_render_minutes(video_id, duration_min)

        await self._log_activity(
            bot_name, video_id, "completed",
            f"Stitched {result['clip_count']} clips "
            f"({result['duration_seconds']:.0f}s, {result.get('resolution', '?')} "
            f"{result.get('orientation', '')}) into final video",
        )
        return {
            "status": to_supabase("rendered"),
            "video_id": video_id,
            "final_video_url": final_url,
            "clip_count": result["clip_count"],
            "duration_seconds": result["duration_seconds"],
            "resolution": result.get("resolution"),
            "orientation": result.get("orientation"),
            "method": result["method"],
        }

    async def _run_perform_render(
        self, video_id: str, video: dict, current_status: str,
        orientation: str = "auto",
    ) -> dict:
        """Final render for character-dialogue voice_over videos — the
        performance-track assembler (render_perform.py): one audio track per
        scene built from the dialogue segments, every shot timed to its
        segment's span, all clips muted."""
        bot_name = "Render Bot"
        await self._log_activity(
            bot_name, video_id, "started",
            "Assembling the performance track and final video"
        )

        async def _progress(msg: str) -> None:
            await self._log_activity(bot_name, video_id, "running", msg)

        from render_perform import render_performance_video

        result = await render_performance_video(
            video_id,
            self.tenant_id,
            title=video.get("video_title") or "",
            orientation=orientation,
            on_progress=_progress,
        )

        final_url = result["final_video_url"]
        await execute(
            "UPDATE videos SET final_video_url = $1 WHERE id = $2",
            final_url, video_id,
        )
        await self._update_video_status(video_id, to_supabase("rendered"))
        await self._log_transition(video_id, current_status, to_supabase("rendered"), "api")

        duration_min = max(1, round(result.get("duration_seconds", 0) / 60))
        await self._charge_render_minutes(video_id, duration_min)

        await self._log_activity(
            bot_name, video_id, "completed",
            f"Assembled {result['clip_count']} timed shots across "
            f"{result['scene_count']} scene(s) "
            f"({result['duration_seconds']:.0f}s, {result.get('resolution', '?')} "
            f"{result.get('orientation', '')}) into the final video",
        )
        return {
            "status": to_supabase("rendered"),
            "video_id": video_id,
            "final_video_url": final_url,
            "clip_count": result["clip_count"],
            "scene_count": result["scene_count"],
            "duration_seconds": result["duration_seconds"],
            "resolution": result.get("resolution"),
            "orientation": result.get("orientation"),
            "method": result["method"],
            "warnings": result.get("warnings") or [],
        }

    async def _run_static_render(
        self, video_id: str, video: dict, current_status: str,
    ) -> dict:
        """Static-documentary render (render_mode='static_docu') — one image
        per narration segment held with a Ken Burns pan over the voiceover,
        rendered with the existing Remotion composition. No animated clips.
        See render_static.py."""
        bot_name = "Render Bot"
        await self._log_activity(
            bot_name, video_id, "started", "Rendering the static documentary"
        )

        async def _progress(msg: str) -> None:
            await self._log_activity(bot_name, video_id, "running", msg)

        from render_static import render_static_video

        result = await render_static_video(
            video_id,
            self.tenant_id,
            title=video.get("video_title") or "",
            on_progress=_progress,
        )

        final_url = result["final_video_url"]
        await execute(
            "UPDATE videos SET final_video_url = $1 WHERE id = $2",
            final_url, video_id,
        )
        await self._update_video_status(video_id, to_supabase("rendered"))
        await self._log_transition(video_id, current_status, to_supabase("rendered"), "api")

        duration_min = max(1, round(result.get("duration_seconds", 0) / 60))
        await self._charge_render_minutes(video_id, duration_min)

        await self._log_activity(
            bot_name, video_id, "completed",
            f"Rendered {result['scene_count']} held segments "
            f"({result['duration_seconds']:.0f}s, {result.get('resolution', '?')}) "
            f"into the final documentary",
        )
        return {
            "status": to_supabase("rendered"),
            "video_id": video_id,
            "final_video_url": final_url,
            "scene_count": result["scene_count"],
            "duration_seconds": result["duration_seconds"],
            "resolution": result.get("resolution"),
            "method": result["method"],
        }

    async def _charge_render_minutes(self, video_id: str, minutes) -> None:
        """Charge render minutes idempotently — only the delta above what this
        video was already charged. Re-renders (edit/retry) of one deliverable
        don't keep eating the customer's monthly allowance. Best-effort:
        billing must never block delivery of a finished render."""
        try:
            from routes.billing import increment_usage
            minutes = max(1, int(round(float(minutes or 0))))
            row = await fetch_one(
                """UPDATE videos AS v
                   SET render_minutes_charged = GREATEST(COALESCE(v.render_minutes_charged, 0), $2)
                   FROM (SELECT COALESCE(render_minutes_charged, 0) AS prev
                         FROM videos WHERE id = $1 AND tenant_id = $3) old
                   WHERE v.id = $1 AND v.tenant_id = $3
                   RETURNING GREATEST(COALESCE(v.render_minutes_charged, 0), $2) - old.prev AS delta""",
                video_id, minutes, self.tenant_id,
            )
            delta = float(row["delta"]) if row and row.get("delta") is not None else 0
            if delta > 0:
                await increment_usage(self.tenant_id, "render_minutes", delta)
        except Exception:
            pass

    async def run_render(self, video_id: str, orientation: str = "auto") -> dict:
        """Render final video."""
        await self._ensure_initialized()
        bot_name = "Render Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")

            # grok_native videos carry Grok's dialogue baked into each clip, so
            # the final video is just the clips stitched in order — no Remotion,
            # no render_config.json/Whisper, no muted-clip+narrator bug. Clips
            # that differ in orientation are normalized onto one canvas. Each
            # render is isolated (own temp dir), so many can run at once.
            # voice_over videos still use the Remotion timeline (narrator) below.
            # static_docu videos (image-per-segment documentaries) render via
            # the Supabase-native Remotion path — checked FIRST since their
            # dialogue_audio is voice_over.
            if (video.get("render_mode") or "") == "static_docu":
                return await self._run_static_render(video_id, video, current_status)
            if (video.get("dialogue_audio") or "voice_over") == "grok_native":
                return await self._run_stitch_render(
                    video_id, video, current_status, orientation)
            # character_dialogue + voice_over: the performance-track assembler
            # lays every segment voice (narrator + character lines) on one
            # per-scene track, times each shot to its segment, and plays the
            # clips muted — see render_perform.py.
            if (video.get("dialogue_mode") or "") == "character_dialogue":
                return await self._run_perform_render(
                    video_id, video, current_status, orientation)

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

            duration = video.get("video_length_minutes") or 10
            await self._charge_render_minutes(video_id, duration)

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

            # Supabase-native, per-tenant path: if the creator has connected their OWN
            # YouTube channel, upload there using the stored SEO (no Airtable, no shared
            # token, no Power Doctrine defaults). Falls back to the legacy bot otherwise.
            cp = await fetch_one(
                "SELECT youtube_refresh_token FROM channel_profiles WHERE tenant_id=$1",
                self.tenant_id)
            if cp and cp.get("youtube_refresh_token"):
                from youtube_publish import generate_and_store_seo, upload_video_to_youtube
                # Only auto-generate when there's no SEO yet — never clobber the
                # creator's edited/saved description+tags.
                if not (video.get("seo_description") or "").strip():
                    seo = await generate_and_store_seo(video_id, self.tenant_id)
                    if seo.get("error"):
                        raise Exception(seo["error"])
                up = await upload_video_to_youtube(video_id, self.tenant_id)
                if up.get("error"):
                    raise Exception(up["error"])
                await self._log_activity(
                    bot_name, video_id, "completed",
                    f"Uploaded to YouTube ({up.get('channel') or 'your channel'}) as an unlisted draft")
                return {"status": "uploaded_draft", "video_id": video_id,
                        "video_url": up.get("youtube_url")}

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
