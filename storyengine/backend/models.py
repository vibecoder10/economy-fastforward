"""Pydantic models for API request/response."""

from pydantic import BaseModel
from typing import Optional, List
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
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class VideoDetail(VideoSummary):
    airtable_record_id: Optional[str] = None
    characters_approved_at: Optional[str] = None
    story_locked_at: Optional[str] = None
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


class VideoAdvance(BaseModel):
    """Request to advance video to next stage."""
    pass


class VideoReject(BaseModel):
    """Request to reject/flag a video."""
    reason: Optional[str] = None


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
    title: str
    source_url: Optional[str] = None
    framework_angle: Optional[str] = None
    video_length_minutes: Optional[int] = 10
    writer_guidance: Optional[str] = None
    visual_style: Optional[str] = None
    accent_color: Optional[str] = None


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
