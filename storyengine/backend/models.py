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
    title: str
    status: str
    thumbnail_url: Optional[str] = None
    accent_color: str = "#00D4AA"
    total_cost: float = 0
    views: int = 0
    ctr: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class VideoDetail(VideoSummary):
    airtable_record_id: Optional[str] = None
    framework_angle: Optional[str] = None
    research_payload: Optional[dict] = None
    script: Optional[str] = None
    story_bible: Optional[str] = None
    thumbnail_prompt: Optional[str] = None
    visual_style: str = "holographic_hud"
    video_length_minutes: int = 10
    youtube_url: Optional[str] = None
    avg_retention: Optional[float] = None


class VideoAdvance(BaseModel):
    """Request to advance video to next stage."""
    pass


class VideoReject(BaseModel):
    """Request to reject/flag a video."""
    reason: Optional[str] = None


# --- Assets ---

class AssetSummary(BaseModel):
    id: str
    video_id: str
    asset_type: str
    scene_number: Optional[int] = None
    image_index: Optional[int] = None
    url: str
    prompt: Optional[str] = None
    status: str = "pending"
    metadata: Optional[dict] = None
    created_at: Optional[str] = None


class AssetApproval(BaseModel):
    status: str  # 'approved' or 'rejected'


class BatchApproval(BaseModel):
    asset_ids: List[str]
    status: str  # 'approved' or 'rejected'


# --- Scripts ---

class ScriptScene(BaseModel):
    id: str
    video_id: str
    scene_number: int
    scene_text: str
    voice_url: Optional[str] = None
    voice_status: str = "pending"
    sources: Optional[str] = None


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


# --- Review ---

class PendingReview(BaseModel):
    scripts: List[dict] = []
    storyboards: List[dict] = []
    thumbnails: List[dict] = []
    images: List[dict] = []
