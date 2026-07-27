"""Pydantic models for API request/response."""

from pydantic import BaseModel, model_serializer
from typing import Optional, List, Literal
from datetime import datetime
from decimal import Decimal


# --- Pipeline Stages ---

PIPELINE_STAGES = [
    {"key": "idea_logged", "label": "Idea", "color": "slate", "dot": 1},
    {"key": "ready_for_scripting", "label": "Script", "color": "blue", "dot": 2},
    {"key": "ready_for_voice", "label": "Voice", "color": "cyan", "dot": 3},
    {"key": "ready_for_storyboards", "label": "Storyboard", "color": "amber", "dot": 4},
    {"key": "ready_for_images", "label": "Images", "color": "violet", "dot": 5},
    {"key": "ready_for_thumbnail", "label": "Thumbnail", "color": "orange", "dot": 6},
    {"key": "ready_to_render", "label": "Render", "color": "rose", "dot": 7},
    {"key": "rendered", "label": "Rendered", "color": "emerald", "dot": 8},
    {"key": "uploaded_draft", "label": "Draft", "color": "green", "dot": 9},
    {"key": "done", "label": "Published", "color": "green", "dot": 10},
]

STAGE_ORDER = {s["key"]: s["dot"] for s in PIPELINE_STAGES}


# --- Videos ---

class VideoSummary(BaseModel):
    id: str
    video_title: Optional[str] = None
    status: Optional[str] = None
    thumbnail_url: Optional[str] = None
    accent_color: str = "#00D4AA"
    total_cost: float = 0
    views: int = 0
    ctr: Optional[float] = None
    # Early-warning launch classifier (checklist C58): 'ok' | 'watch' |
    # 'underperforming', NULL until the video's ctr_48h milestone lands and
    # the channel has enough history to classify it. On VideoSummary (not
    # just VideoDetail) so a list-view badge can slot in without a second
    # fetch. See backend/early_warning.py.
    early_signal: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class VideoDetail(VideoSummary):
    airtable_record_id: Optional[str] = None
    characters_approved_at: Optional[str] = None
    story_locked_at: Optional[str] = None
    dialogue_audio: Optional[str] = None
    # NULL = normal (clip stitch / narrator). 'static_docu' = static-image
    # documentary: images held over narration, no animate stage.
    render_mode: Optional[str] = None
    # 'character_dialogue' | 'narration_only' | None (unanalyzed). Exposed
    # only so the frontend can show WHY sound_effects_supported is false —
    # nothing reads this for its own sake yet.
    dialogue_mode: Optional[str] = None
    # Whether run_render (backend/pipeline_executor.py) will mix this video's
    # assets.sound_effect_url into the final render — computed by
    # status_map.render_path_plays_sfx, the single source of truth every
    # backend guard (routes/pipeline.py's sound endpoints, actions.py's
    # "sound" verb, pipeline_executor.py's auto-advance skip) already reads.
    # True (the historical default) for every video with no custom_film_plan_id/
    # static_docu render_mode/grok_native dialogue_audio/character_dialogue
    # dialogue_mode — i.e. every existing video before this field existed.
    sound_effects_supported: bool = True
    # Human-readable reason sound_effects_supported is False, or None when
    # it's True. Same computation as sound_effects_supported (status_map.
    # render_path_sfx_block_reason) — never re-derive this text elsewhere.
    sound_effects_unsupported_reason: Optional[str] = None
    # Channel-style routing guardrail (migration 089/C13b): 'animated' |
    # 'realistic' | None (undeclared — the router's money-safe default,
    # never upgrading tiers until a channel opts in). C14 surfaces this as
    # the Scenes workspace's "Channel look" control.
    render_style: Optional[str] = None
    # Optional per-video spend ceiling (migration 103, checklist §3.3/C36).
    # NULL = no cap (default). The money gate (backend actions.budget_check)
    # reads total_cost against this before every paid verb.
    max_spend: Optional[float] = None
    # Per-video pipeline plan: which stages this video runs (None = full
    # pipeline). The UI hides the tabs for stages that are turned off.
    skip_voice: bool = False
    pipeline_stages: Optional[list] = None
    # True when the default autobuild chain skipped the optional research
    # stage for this video (script wrote straight from the topic). Drives the
    # "Research: skipped — Run research" transparency chip (checklist P0.5).
    # Cleared back to False once research actually runs for the video.
    research_skipped: bool = False
    headline: Optional[str] = None
    source: Optional[str] = None
    framework_angle: Optional[str] = None
    thematic_framework: Optional[str] = None
    hook_script: Optional[str] = None
    past_context: Optional[str] = None
    present_parallel: Optional[str] = None
    future_prediction: Optional[str] = None
    writer_guidance: Optional[str] = None
    thesis: Optional[str] = None
    executive_hook: Optional[str] = None
    research_payload: Optional[dict] = None
    original_dna: Optional[dict] = None
    script: Optional[str] = None
    script_validation: Optional[str] = None
    story_bible: Optional[str] = None
    thumbnail_prompt: Optional[str] = None
    thumbnail_style_override: Optional[str] = None
    visual_style: Optional[str] = None
    image_style_override: Optional[str] = None
    style_preset_id: Optional[str] = None
    # High-level production shape (migration 121). Distinct from the visual
    # style/look fields above. The snapshot is the immutable contract used by
    # every downstream surface and runtime path.
    production_style_id: Optional[str] = None
    production_style_version: Optional[int] = None
    production_style_snapshot: Optional[dict] = None
    # Custom Film is an optional, immutable per-video plan revision. The
    # serializer omits this whole additive group when no plan exists so legacy
    # and ordinary single-profile response payloads keep their prior key set.
    custom_film_plan_id: Optional[str] = None
    custom_film_plan_revision: Optional[int] = None
    custom_film_plan_hash: Optional[str] = None
    custom_film_quote_inputs_hash: Optional[str] = None
    custom_film_approval_hash: Optional[str] = None
    custom_film_approved_at: Optional[str] = None
    custom_film_plan: Optional[dict] = None
    # Editorial-voice engine pick (checklist §2.3, C24) — a
    # shared.profiles.script profile id (e.g. "power_doctrine_v2"). NULL =
    # no explicit pick; the executor's SCRIPT_PROFILE seam falls back to
    # "neutral_v1" (see pipeline_executor.py's _resolve_script_profile_id).
    script_profile: Optional[str] = None
    image_model_override: Optional[str] = None
    video_model: Optional[str] = None
    video_length_minutes: Optional[float] = None
    youtube_url: Optional[str] = None
    final_video_url: Optional[str] = None
    avg_retention: Optional[float] = None
    impressions: int = 0
    likes: int = 0
    comments: int = 0
    performance_verdict: Optional[str] = None
    source_views: Optional[int] = None
    source_channel: Optional[str] = None
    source_urls: Optional[str] = None
    views_24h: Optional[int] = None
    views_48h: Optional[int] = None
    views_7d: Optional[int] = None
    views_30d: Optional[int] = None
    ctr_12h: Optional[float] = None
    ctr_24h: Optional[float] = None
    ctr_48h: Optional[float] = None
    retention_48h: Optional[float] = None
    # C58: the evidence + timestamp behind `early_signal` (declared on
    # VideoSummary above). Evidence only needed on the detail view.
    early_signal_evidence: Optional[dict] = None
    early_signal_at: Optional[str] = None
    post_mortem_48h: Optional[str] = None
    post_mortem_7d: Optional[str] = None
    agent_paper_trail: Optional[dict] = None
    agent_hook_score: Optional[float] = None
    agent_body_score: Optional[float] = None
    agent_tier: Optional[str] = None
    agent_cost: Optional[float] = None
    suggested_thumbnail_prompt: Optional[str] = None
    suggested_thumbnail_urls: Optional[list] = None
    suggested_script: Optional[str] = None
    suggested_title: Optional[str] = None
    suggestion_source: Optional[str] = None
    suggestion_scores: Optional[dict] = None
    suggestion_status: Optional[str] = None
    # Editable system prompts
    video_motion_system_prompt: Optional[str] = None
    script_system_prompt: Optional[str] = None
    thumbnail_system_prompt: Optional[str] = None
    sound_system_prompt: Optional[str] = None

    @model_serializer(mode="wrap")
    def _serialize_without_empty_custom_film(self, handler):
        payload = handler(self)
        if self.custom_film_plan_id is None:
            for key in (
                "custom_film_plan_id",
                "custom_film_plan_revision",
                "custom_film_plan_hash",
                "custom_film_quote_inputs_hash",
                "custom_film_approval_hash",
                "custom_film_approved_at",
                "custom_film_plan",
            ):
                payload.pop(key, None)
        return payload


class VideoAdvance(BaseModel):
    """Request to advance video to next stage."""
    pass


class VideoReject(BaseModel):
    """Request to reject/flag a video."""
    reason: Optional[str] = None


# --- Cost ledger (checklist §0.3d / C10) ---
# Read-only receipts backing videos.total_cost — see generation_ledger.py for
# the single write path. This is the ONLY read shape the ledger drawer and
# the copilot's "how much has this cost?" answer use; never hand-roll a
# second SUM(actual_cost) query elsewhere.

class LedgerRow(BaseModel):
    stage: str
    model: Optional[str] = None
    units: float = 0
    unit_cost: float = 0
    actual_cost: float = 0
    kie_task_id: Optional[str] = None
    created_at: Optional[str] = None


class VideoLedgerResponse(BaseModel):
    video_id: str
    total_cost: float = 0
    by_stage: dict[str, float] = {}
    rows: List[LedgerRow] = []


# --- Assets ---

class AssetSummary(BaseModel):
    id: str
    video_id: Optional[str] = None
    video_title: Optional[str] = None
    scene: Optional[int] = None
    image_index: Optional[int] = None
    image_url: Optional[str] = None
    image_prompt: Optional[str] = None
    status: Optional[str] = None
    shot_type: Optional[str] = None
    hero_shot: bool = False
    created_at: Optional[str] = None


class AssetApproval(BaseModel):
    status: str  # 'approved' or 'rejected'


class BatchApproval(BaseModel):
    asset_ids: List[str]
    status: str  # 'approved' or 'rejected'


class SceneTextUpdate(BaseModel):
    text: str


class SceneToneUpdate(BaseModel):
    tone: str  # serious | conversational | urgent | concise


class SegmentUpdate(BaseModel):
    segments: list[dict]  # [{image_index: int, sentence_text: str}, ...]


class StoryboardModeUpdate(BaseModel):
    enabled: bool


class CreateVideoRequest(BaseModel):
    # Optional ONLY when reference_url is set (checklist C38 — create-surface
    # convergence): an omitted/blank title + a reference_url is Model A Video's
    # "I have no topic yet, derive one from this reference" shape. Every other
    # caller (New Video form, chat producer, MCP) always sends a real title;
    # routes.videos.create_video 400s if both title and reference_url are
    # missing.
    title: Optional[str] = None
    source_url: Optional[str] = None
    framework_angle: Optional[str] = None
    video_length_minutes: Optional[int] = 10
    writer_guidance: Optional[str] = None
    visual_style: Optional[str] = None
    # Free-text per-video scene LOOK (preset look sentence or the creator's own
    # words). Front-loaded into every image prompt; wins over channel/neutral.
    # Omitted for the clone ("use this video's style") and "none" choices.
    image_style_override: Optional[str] = None
    # Optional catalog pick from the 5 rich Python visual-profile engines
    # (checklist §2.1, C20) — a style_presets.id, e.g. "holographic_hud".
    # Validated against the table at create time; wins over the legacy
    # `visual_style` text field for the VISUAL_PROFILE executor seam. A
    # DIFFERENT axis from visual_style/image_style_override above (see
    # style_presets's schema.sql comment for the reconciliation note).
    style_preset_id: Optional[str] = None
    # When true, also save+activate this look as the channel's library identity
    # so future (non-cloned) videos inherit it.
    lock_in_identity: bool = False
    # Friendly name for the locked-in library entry ("Pixar 3D", "Custom", …).
    visual_style_label: Optional[str] = None
    accent_color: Optional[str] = None
    # Output shape, chosen up front; flows through image/clip gen + render.
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    # Clip quality, chosen up front; passed to the clip generator. 720p is
    # YouTube-ready; 480p is the cheaper/faster option.
    video_resolution: Literal["480p", "720p"] = "720p"
    # Research is the default first step for typed topics. Creators of
    # fiction/story formats can skip it — the video lands straight at
    # 'ready_for_scripting' and the script bot writes from the title +
    # writer_guidance + framework_angle alone (script/run.py handles a
    # missing research_payload). Mirrors how clones skip research.
    skip_research: bool = False
    # AI voice-over is optional. grok_native (clip) videos carry their own
    # baked-in audio, so the narration stage is generated-but-unused for them.
    # When true, the voice stage is skipped: image-prompt/image gates are
    # satisfied without narration and a finished script advances straight to
    # ready_for_image_prompts. (Leave on for documentary/Ken-Burns videos —
    # there the narration IS the audio track.)
    skip_voice: bool = False
    # How far to take this video: the set of enabled user-facing stages, in
    # chain order (research, script, voice, images, sound, video, thumbnail,
    # render, upload). Lets a creator make script-only, script+voice, full-video,
    # etc. None / omitted = run the full pipeline (the default). The server
    # re-normalizes this (chain rules) and derives skip_research / skip_voice
    # from it, so the plan is the single source of truth when provided.
    pipeline_stages: Optional[list[str]] = None
    # Optional reference video to COPY THE STYLE OF. When set (a YouTube link),
    # the video is created in "modeled" mode: the creator's own topic/title is
    # kept, and the reference's style is copied onto it — but ONLY for the
    # switched-on stages (pipeline_stages). voice & sound are never copied.
    reference_url: Optional[str] = None
    # Optional editorial-voice engine pick from shared.profiles.script
    # (checklist §2.3, C24) — a profile id, e.g. "power_doctrine_v2".
    # Validated against the real profile registry at create time (mirrors
    # style_preset_id's validation just above). Opt-in only: omitted /
    # None keeps the neutral default.
    script_profile: Optional[str] = None
    # Required by first-party creation surfaces after Milestone 1. Kept
    # optional at the API boundary for legacy/MCP/chat callers until they are
    # upgraded; when supplied it must name an active public profile and is
    # snapshotted onto the video.
    production_style_id: Optional[str] = None
    # Whether this creation should silently inherit the tenant's LOCKED
    # channel identity (house script format, locked cast, locked visual
    # format) — the three fail-soft background steps just below the INSERT
    # in create_video. None/True = existing behavior (every caller that
    # doesn't set this — New Video form, MCP, chat producer, queue,
    # autopilot, the clone/model path — keeps inheriting exactly as before).
    # False = explicit opt-out: a creator describing something brand-new in
    # free text (DirectorHome's single-prompt entry box) should NOT silently
    # come out looking/sounding like an unrelated existing channel. Root
    # cause: a video about "a dystopian world... bugs" inherited PocoAPoco's
    # locked Ryan/Vanessa cast + two-hander dialogue script format + 3D
    # Pixar-cartoon visual format, unconditionally, because these three
    # steps never checked WHY the video was being created.
    apply_channel_identity: Optional[bool] = None
    # Optional per-video spend ceiling, settable AT creation time (the same
    # videos.max_spend column PATCH /api/videos/{id} and the copilot's
    # "cap this video at $X" both write — migration 103, checklist §3.3/C36).
    # Added so a cap typed IN the creation sentence ("...cap the spend at
    # $1") can actually land instead of being silently dropped (it used to
    # have no creation-time home at all: CreateVideoRequest never carried
    # it, so DirectorHome's entry box had nowhere to put a parsed cap).
    # None = no cap (default, unchanged). Same validation as the PATCH path:
    # must be > 0.
    max_spend: Optional[float] = None


# --- Scripts ---

class ScriptScene(BaseModel):
    id: str
    video_id: Optional[str] = None
    scene: Optional[int] = None
    scene_text: Optional[str] = None
    voice_over_url: Optional[str] = None
    voice_status: Optional[str] = None
    script_status: Optional[str] = None
    sources: Optional[str] = None
    storyboard_on_off: Optional[str] = None


# --- Activity ---

class ActivityEntry(BaseModel):
    id: str
    bot_name: str
    video_id: Optional[str] = None
    video_title: Optional[str] = None
    status: str
    message: Optional[str] = None
    cost: float = 0
    created_at: Optional[str] = None


class ActivityStats(BaseModel):
    bots_running: int = 0
    errors_today: int = 0
    cost_today: float = 0


# --- Dashboard ---

class DashboardSummary(BaseModel):
    active_bots: int = 0
    pending_review: int = 0
    pipeline_distribution: dict = {}
    cost_today: float = 0
    cost_week: List[float] = []
    errors: int = 0
    latest_video: Optional[VideoSummary] = None
    total_videos: int = 0
    avg_ctr: Optional[float] = None
    total_views: int = 0
    videos_this_week: int = 0
    recent_videos: List[VideoSummary] = []


# --- Review ---

class PendingReview(BaseModel):
    scripts: List[dict] = []
    storyboards: List[dict] = []
    thumbnails: List[dict] = []
    images: List[dict] = []


# --- Profile ---

class ProfileRead(BaseModel):
    id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    plan: str = "free"
    created_at: Optional[str] = None


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None


# --- Style/model performance (checklist §3.1 / C30) ---
# One aggregation, two callers: routes/analytics.py's GET /api/analytics/by-style
# and channel_briefs.py's copilot brief (analytics_by_style.get_style_performance)
# — see that module's header for the videos-vs-channel_videos linkage reasoning.

class StyleChoiceAggregate(BaseModel):
    dimension: str  # 'by_style_preset' | 'by_render_style' | 'by_script_profile' | 'by_clip_model'
    choice: str
    video_count: int = 0
    synced_count: int = 0  # subset of video_count with real synced YouTube analytics
    avg_ctr: Optional[float] = None
    avg_retention: Optional[float] = None
    avg_vph: Optional[float] = None  # C33: views-per-hour, derived at read time
    total_views: int = 0
    total_spend: float = 0.0


class StylePerformanceResponse(BaseModel):
    by_style_preset: List[StyleChoiceAggregate] = []
    by_render_style: List[StyleChoiceAggregate] = []
    by_script_profile: List[StyleChoiceAggregate] = []
    by_clip_model: List[StyleChoiceAggregate] = []
