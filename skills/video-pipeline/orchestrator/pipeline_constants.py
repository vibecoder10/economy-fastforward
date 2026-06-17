"""Pipeline Constants — Single Source of Truth

Every shared variable (field names, statuses, model IDs, endpoints, thresholds)
lives here. All other files import from this module. To change a value, edit it
here and everything updates.

NOTE: Module-internal constants (e.g. prompt_validator's LOCATION_MARKERS) stay
in their own files. This module only holds values referenced by 2+ files.
"""

import os


# =============================================================================
# AIRTABLE FIELD NAMES
# =============================================================================
# Every Airtable field used by 2+ files. Typos here fail loudly at import time
# instead of silently dropping Airtable writes.


class IdeaFields:
    """Idea Concepts table field names."""

    STATUS = "Status"
    VIDEO_TITLE = "Video Title"
    HOOK_SCRIPT = "Hook Script"
    PAST_CONTEXT = "Past Context"
    PRESENT_PARALLEL = "Present Parallel"
    FUTURE_PREDICTION = "Future Prediction"
    THUMBNAIL_PROMPT = "Thumbnail Prompt"
    WRITER_GUIDANCE = "Writer Guidance"
    ORIGINAL_DNA = "Original DNA"
    SOURCE = "Source"

    # Research fields
    FRAMEWORK_ANGLE = "Framework Angle"
    HEADLINE = "Headline"
    TIMELINESS_SCORE = "Timeliness Score"
    AUDIENCE_FIT_SCORE = "Audience Fit Score"
    CONTENT_GAP_SCORE = "Content Gap Score"
    SOURCE_URLS = "Source URLs"
    EXECUTIVE_HOOK = "Executive Hook"
    THESIS = "Thesis"
    DATE_SURFACED = "Date Surfaced"
    RESEARCH_PAYLOAD = "Research Payload"
    THEMATIC_FRAMEWORK = "Thematic Framework"

    # Style overrides (set via Slack !style commands)
    IMAGE_STYLE_OVERRIDE = "Image Style Override"
    THUMBNAIL_STYLE_OVERRIDE = "Thumbnail Style Override"
    ACCENT_COLOR = "Accent Color"
    IMAGE_MODEL_OVERRIDE = "Image Model Override"  # Multiple Select!
    VISUAL_STYLE = "Visual Style"  # Single Select

    # Visual consistency
    STORY_BIBLE = "Story Bible"
    CHARACTER_REFERENCE = "Character Reference"  # Attachment — reference image for BYOC

    # Pipeline state
    SCRIPT = "Script"
    SCRIPT_VALIDATION = "Script Validation"
    SCENE_FILE_PATH = "Scene File Path"
    DRIVE_FOLDER_ID = "Drive Folder ID"
    DRIVE_FOLDER_LINK = "Drive Folder Link"
    CORE_IMAGE = "Core Image"
    VIDEO_LENGTH_MIN = "Video Length (min)"

    # Optional / metadata
    REFERENCE_URL = "Reference URL"
    IDEA_REASONING = "Idea Reasoning"
    SOURCE_VIEWS = "Source Views"
    SOURCE_CHANNEL = "Source Channel"
    GOOGLE_DRIVE_FOLDER_ID = "Google Drive Folder ID"
    THUMBNAIL = "Thumbnail"
    PIPELINE_MODE = "Pipeline Mode"
    NOTES = "Notes"

    # Upload / YouTube
    UPLOAD_STATUS = "Upload Status"
    YOUTUBE_VIDEO_ID = "YouTube Video ID"
    YOUTUBE_URL = "YouTube URL"
    UPLOAD_DATE = "Upload Date"
    FINAL_VIDEO = "Final Video"
    FINAL_VIDEO_URL = "Final Video URL"

    # SEO
    SEO_DESCRIPTION = "SEO Description"
    SEO_TAGS = "SEO Tags"
    SEO_HASHTAGS = "SEO Hashtags"

    # Performance (written by performance_tracker.py)
    VIEWS = "Views"
    LIKES = "Likes"
    COMMENTS = "Comments"
    SUBSCRIBERS_GAINED = "Subscribers Gained"
    AVG_VIEW_DURATION = "Avg View Duration (s)"
    AVG_RETENTION = "Avg Retention (%)"
    WATCH_TIME_HOURS = "Watch Time (hours)"
    IMPRESSIONS = "Impressions"
    CTR = "CTR (%)"
    VIEWS_24H = "Views 24h"
    VIEWS_48H = "Views 48h"
    VIEWS_7D = "Views 7d"
    VIEWS_30D = "Views 30d"
    CTR_12H = "CTR 12h (%)"
    CTR_24H = "CTR 24h (%)"
    CTR_48H = "CTR 48h (%)"
    RETENTION_48H = "Retention 48h (%)"
    LAST_ANALYTICS_SYNC = "Last Analytics Sync"

    # Thumbnail
    THUMBNAIL_TEXT = "Thumbnail Text"
    THUMBNAIL_PALETTE = "Thumbnail Palette"
    SUMMARY = "Summary"

    # Computed / formula
    TITLE_FORMULA = "Title Formula"
    FRAMEWORK = "Framework"

    # Script / validation
    SOURCES = "Sources"
    SCENE_COUNT = "Scene Count"
    VALIDATION_STATUS = "Validation Status"
    VIDEO_ID = "Video ID"

    # Osiris
    POST_MORTEM_48H = "Post-Mortem 48h"
    POST_MORTEM_7D = "Post-Mortem 7d"
    PERFORMANCE_VERDICT = "Performance Verdict"

    # Storyboard (mode is on Scripts table, these stay on Ideas)
    STORYBOARD_STATUS = "Storyboard Status"
    STORYBOARD_PREVIEW = "Storyboard Preview"
    STORYBOARD_BEAT_COUNT = "Storyboard Beat Count"
    VIDEO_MODEL = "Video Model"

    # Curiosity Gap (copied from selected Title Test record)
    CURIOSITY_STRUCTURE = "Curiosity Structure"
    STRUCTURE_CONFIDENCE = "Structure Confidence"
    THUMBNAIL_APPROACH = "Thumbnail Approach"
    STRUCTURE_SOURCE = "Structure Source"
    PATTERN_LIBRARY_SNAPSHOT = "Pattern Library Snapshot"
    TITLE_POLL_RESULT = "Title Poll Result"
    POLL_CLOSED = "Poll Closed"
    # THUMBNAIL_TEXT already exists above


class ScriptFields:
    """Scripts table field names."""

    SCENE = "scene"  # Airtable uses lowercase
    SCENE_TEXT = "Scene text"
    TITLE = "Title"
    VOICE_ID = "Voice ID"
    SCRIPT_STATUS = "Script Status"
    VOICE_STATUS = "Voice Status"
    VOICE_OVER = "Voice Over"
    SOURCES = "Sources"
    PSYCH_ANGLE = "Psych Angle"
    SFX_STATUS = "SFX Status"
    SOUND_MAP = "Sound Map"

    # Storyboard fields - for visual consistency planning
    STORYBOARD_MODE = "Story Board On/OFF"  # Single Select - "On" or "Off"
    STORYBOARD_PROMPTS = "Storyboard Prompts"  # Long Text - prompts for all grids (copy to Gemini)
    STORYBOARD_1 = "Storyboard 1"  # Attachment - first 3x3 grid
    STORYBOARD_2 = "Storyboard 2"  # Attachment - second 3x3 grid
    STORYBOARD_3 = "Storyboard 3"  # Attachment - third 3x3 grid (if 19+ sentences)

    # Script Status values
    STATUS_CREATE = "Create"
    STATUS_FINISHED = "Finished"


class ImageFields:
    """Images table field names."""

    SCENE = "Scene"
    IMAGE_INDEX = "Image Index"
    SENTENCE_INDEX = "Sentence Index"  # Same as Image Index
    SENTENCE_TEXT = "Sentence Text"
    IMAGE_PROMPT = "Image Prompt"
    ORIGINAL_IMAGE_PROMPT = "Original Image Prompt"
    SHOT_TYPE = "Shot Type"
    VIDEO_TITLE = "Video Title"
    ASPECT_RATIO = "Aspect Ratio"
    STATUS = "Status"
    DURATION = "Duration (s)"

    # Image/Video attachments
    IMAGE = "Image"
    VIDEO = "Video"
    VIDEO_PROMPT = "Video Prompt"
    VIDEO_STATUS = "Video Status"
    DRIVE_IMAGE_URL = "Drive Image URL"

    # Animation
    HERO_SHOT = "Hero Shot"
    VIDEO_CLIP_URL = "Video Clip URL"
    ANIMATION_STATUS = "Animation Status"
    VIDEO_DURATION = "Video Duration"

    # Sound
    SOUND_PROMPT = "Sound Prompt"
    SOUND_EFFECT = "Sound Effect"
    SOUND_VOLUME = "Sound Volume"

    # Storyboard
    STORYBOARD_GRID_URL = "Storyboard Grid URL"
    PANEL_POSITION = "Panel Position"
    GENERATION_METHOD = "Generation Method"
    CLIP_DURATION = "Clip Duration"
    CAMERA_MOVEMENT = "Camera Movement"
    ASSIGNED_VIDEO_DURATION = "Assigned Video Duration"
    ESTIMATED_CLIP_COST = "Estimated Clip Cost"

    # Status values
    STATUS_PENDING = "Pending"
    STATUS_DONE = "Done"


class CompetitorChannelFields:
    """Competitor Channels table field names."""

    CHANNEL_NAME = "Channel Name"
    CHANNEL_URL = "Channel URL"
    CATEGORY = "Category"
    ACTIVE = "Active"
    LAST_SCRAPED = "Last Scraped"
    NOTES = "Notes"


class CompetitorVideoFields:
    """Competitor Videos table field names."""

    VIDEO_ID = "Video ID"
    TITLE = "Title"
    URL = "URL"
    CHANNEL = "Channel"
    CHANNEL_URL = "Channel URL"
    VIEWS = "Views"
    VPH = "VPH"
    HOURS_OLD = "Hours Old"
    PUBLISHED_DATE = "Published Date"
    SCRAPE_DATE = "Scrape Date"
    MODELED = "Modeled"
    OUR_VIDEO = "Our Video"
    TOPIC_CLUSTER = "Topic Cluster"

    # Curiosity Gap fields (added 2026-03-20)
    CURIOSITY_STRUCTURE = "Curiosity Structure"
    STRUCTURE_CONFIDENCE = "Structure Confidence"
    THUMBNAIL_STYLE_JSON = "Thumbnail Style JSON"
    YIN_YANG_APPROACH = "Yin Yang Approach"
    YIN_YANG_TEXT = "Yin Yang Text"
    ANALYSIS_DATE = "Analysis Date"
    MODELED_BY_US = "Modeled By Us"
    OUR_CTR_RESULT = "Our CTR Result"


class OsirisLearningFields:
    """Osiris Learnings table field names."""

    CATEGORY = "Category"
    PATTERN = "Pattern"
    CONFIDENCE = "Confidence"
    SAMPLE_SIZE = "Sample Size"
    AVG_CTR = "Avg CTR"
    AVG_RETENTION = "Avg Retention"
    SOURCE_VIDEOS = "Source Videos"
    CREATED = "Created"
    LAST_UPDATED = "Last Updated"
    ACTIVE = "Active"


class TitleInsightFields:
    """Title Insights table field names (competitor title pattern analysis)."""

    ANALYSIS_DATE = "Analysis Date"
    PATTERN_TYPE = "Pattern Type"  # Single Select: structural, semantic
    PATTERN_NAME = "Pattern Name"
    DESCRIPTION = "Description"
    EXAMPLE_TITLES = "Example Titles"  # JSON array
    AVG_VPH = "Avg VPH"
    COUNT = "Count"
    CONFIDENCE = "Confidence"
    VIDEOS_ANALYZED = "Videos Analyzed"
    VPH_THRESHOLD = "VPH Threshold"


class TitleTestFields:
    """Title Tests table field names (curiosity gap A/B testing)."""

    IDEA = "Idea"  # Ideas record ID
    TITLE_TEXT = "Title Text"
    STRUCTURE = "Structure"  # Single Select: hidden_flaw, asymmetric_dg, time_bomb, paradigm_shift, illusion_control, other
    STRUCTURE_CONFIDENCE = "Structure Confidence"
    THUMBNAIL_TEXT = "Thumbnail Text"
    THUMBNAIL_APPROACH = "Thumbnail Approach"  # Single Select: from_hook, from_gap
    SOURCE_PATTERNS = "Source Patterns"  # JSON: competitor + our record IDs
    PATTERN_LIBRARY_SNAPSHOT = "Pattern Library Snapshot"  # JSON: pattern state at generation
    POLL_RESULT = "Poll Result"  # Single Select: human_selected, auto_selected
    POLL_CLOSED = "Poll Closed"
    CTR_12H = "CTR 12h"
    CTR_24H = "CTR 24h"
    CTR_48H = "CTR 48h"
    SELECTED = "Selected"
    VIDEO_TITLE = "Video Title"  # String match to Ideas table


# =============================================================================
# CURIOSITY GAP SYSTEM
# =============================================================================

# Kill switch - set to False to instantly disable curiosity gap system
CURIOSITY_GAP_ENABLED = True

# Title Tests table ID
AIRTABLE_TITLE_TESTS_TABLE_ID = "tbln8CPbNaMvERVn9"


# =============================================================================
# PIPELINE STATUSES
# =============================================================================


class Statuses:
    """Pipeline status values — Airtable Ideas table 'Status' field."""

    IDEA_LOGGED = "Idea Logged"
    APPROVED = "Approved"
    READY_SCRIPTING = "Ready For Scripting"
    READY_VOICE = "Ready For Voice"
    READY_SOUND_DESIGN = "Ready For Sound Design"
    READY_SOUND_EFFECTS = "Ready For Sound Effects"
    READY_IMAGE_PROMPTS = "Ready For Image Prompts"
    READY_STORYBOARDS = "Ready For Storyboards"
    READY_STORYBOARD_IMAGES = "Ready For Storyboard Images"
    READY_STORYBOARD_EXTRACTION = "Ready For Storyboard Extraction"
    READY_IMAGES = "Ready For Images"
    READY_VIDEO_SCRIPTS = "Ready For Video Scripts"
    READY_VIDEO_GENERATION = "Ready For Video Generation"
    READY_THUMBNAIL = "Ready For Thumbnail"
    DONE = "Done"
    READY_TO_RENDER = "Ready To Render"
    RENDERED = "Rendered"
    UPLOADED_DRAFT = "Uploaded (Draft)"
    IN_QUE = "In Que"
    NEEDS_SCRIPT_REVIEW = "Needs Script Review"
    QUEUED = "Queued"
    SENT_TO_PIPELINE = "sent_to_pipeline"

    # Ordered list for pipeline flow
    WORKFLOW_ORDER = [
        IDEA_LOGGED,
        APPROVED,
        READY_SCRIPTING,
        READY_VOICE,
        READY_IMAGE_PROMPTS,
        READY_IMAGES,
        READY_SOUND_DESIGN,
        READY_SOUND_EFFECTS,
        READY_VIDEO_SCRIPTS,
        READY_VIDEO_GENERATION,
        READY_THUMBNAIL,
        DONE,
        READY_TO_RENDER,
        RENDERED,
        UPLOADED_DRAFT,
    ]


# =============================================================================
# MODEL IDs
# =============================================================================
# Env-overridable so VPS can pin versions without code changes.


class Models:
    """AI model identifiers."""

    # Claude
    CLAUDE_SONNET = os.getenv("CLAUDE_SONNET_MODEL", "claude-sonnet-4-5-20250929")
    CLAUDE_OPUS = os.getenv("CLAUDE_OPUS_MODEL", "claude-opus-4-5-20251101")
    CLAUDE_HAIKU = os.getenv("CLAUDE_HAIKU_MODEL", "claude-haiku-4-5-20251001")

    # Image generation (Kie.ai)
    IMAGE_SCENE = os.getenv("IMAGE_SCENE_MODEL", "nano-banana-2")
    IMAGE_ZIMAGE = "z-image"
    IMAGE_THUMBNAIL = os.getenv("IMAGE_THUMBNAIL_MODEL", "nano-banana-pro")

    # Video generation (Kie.ai)
    ANIMATION_GROK = "grok-imagine/image-to-video"
    VEO_FAST = "veo3_fast"
    VEO_QUALITY = "veo3"

    # Sound effects (Kie.ai → ElevenLabs)
    SOUND_EFFECT = "elevenlabs/sound-effect-v2"

    # Voice
    VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "G17SuINrv2H9FC6nvetn")

    # Airtable model name mapping (display name → API name)
    AIRTABLE_MODEL_MAP = {
        "z-image": "z-image",
        "Nano Banana": "nano-banana-2",
    }

    # Valid visual styles for Airtable Single Select
    VALID_VISUAL_STYLES = {
        "neutral_v1",
        "cinematic_illustration",
        "holographic_hud",
        "cinematic_dossier",
        "clay_mannequin",
    }
    DEFAULT_VISUAL_STYLE = "neutral_v1"


# =============================================================================
# API ENDPOINTS
# =============================================================================


class Endpoints:
    """External service URLs."""

    # Kie.ai (images, video, sound)
    KIE_CREATE_TASK = "https://api.kie.ai/api/v1/jobs/createTask"
    KIE_RECORD_INFO = "https://api.kie.ai/api/v1/jobs/recordInfo"

    # Kie.ai (Veo video generation)
    VEO_GENERATE = "https://api.kie.ai/api/v1/veo/generate"
    VEO_RECORD_INFO = "https://api.kie.ai/api/v1/veo/record-info"
    VEO_1080P = "https://api.kie.ai/api/v1/veo/get-1080p-video"

    # ElevenLabs via Wavespeed
    WAVESPEED_API = "https://api.wavespeed.ai/api/v3/elevenlabs/turbo-v2.5"

    # Google Gemini
    GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


# =============================================================================
# TUNING CONSTANTS
# =============================================================================
# Timing, word counts, thresholds used across multiple modules.


class Tuning:
    """Pipeline-wide tuning parameters."""

    # Narration timing
    SPEAKING_RATE_WPS = 2.5  # words per second

    # Segment duration (deterministic_splitter + audio_sync)
    TARGET_SEGMENT_DURATION = 7.0
    MIN_SEGMENT_DURATION = 4.0
    MAX_SEGMENT_DURATION = 10.0

    # Display timing (audio_sync/config.py)
    MIN_DISPLAY_SECONDS = 3.0
    MAX_DISPLAY_SECONDS = 300.0
    MAX_IMAGE_DISPLAY_SECONDS = 10.0
    PRE_ROLL_SECONDS = 0.3
    POST_HOLD_SECONDS = 0.5
    CROSSFADE_DURATION = 0.4
    STYLE_CHANGE_FADE = 0.8
    ACT_TRANSITION_BLACK = 1.5

    # Audio alignment
    FUZZY_MATCH_THRESHOLD = 0.6
    ANCHOR_THRESHOLD = 0.55
    ANCHOR_SIZE = 6

    # Script generation
    SCRIPT_MIN_WORDS = 2200
    SCRIPT_MAX_WORDS = 3200
    SCRIPT_TARGET_WORDS = 2800

    # Scene expansion
    MIN_CONCEPTS_PER_SCENE = 6
    MAX_CONCEPTS_PER_SCENE = 12
    MIN_WORDS_PER_CONCEPT = 10
    MAX_WORDS_PER_CONCEPT = 25

    # Prompt word counts
    PROMPT_MIN_WORDS = 60
    PROMPT_MAX_WORDS = 150

    # Polling (image generation)
    IMAGE_POLL_INITIAL_WAIT = 5.0
    IMAGE_POLL_INTERVAL = 2.0
    IMAGE_POLL_MAX_ATTEMPTS = 45

    # Polling (voice generation)
    VOICE_POLL_MAX_ATTEMPTS = 30
    VOICE_POLL_INTERVAL = 5.0

    # Polling (video generation)
    VIDEO_POLL_INITIAL_WAIT = 10.0
    VIDEO_POLL_INTERVAL = 5.0
    VIDEO_POLL_MAX_ATTEMPTS = 120

    # Concurrency
    MAX_CONCURRENT_IMAGES = 3
    MAX_CONCURRENT_VIDEOS = 3

    # Sound design
    SOUND_MIN_PERCENT = 0.25
    SOUND_MAX_PERCENT = 0.60
    SOUND_DEFAULT_DURATION = 8.0
    SOUND_DEFAULT_VOLUME = 0.15
    SOUND_MAX_GENERATIONS = 200
    SOUND_MAX_PROMPT_LENGTH = 450

    # Visual style sequencing
    MAX_CONSECUTIVE_CONTENT_TYPE = 2
    MAX_CONSECUTIVE_FORMAT = 2
    MAX_CONSECUTIVE_PALETTE = 3
    MAX_CONSECUTIVE_CLOSE_UP = 1

    # Ken Burns
    KEN_BURNS_BASE_DURATION = 11.0

    # Competitor/discovery scanning
    COMPETITOR_VPH_THRESHOLD = 50
    COMPETITOR_MAX_AGE_HOURS = 168  # 7 days

    # Cost tracking (USD)
    COST_IMAGE = 0.025
    COST_VIDEO_CLIP = 0.10
    COST_THUMBNAIL = 0.09
    COST_SOUND_EFFECT = 0.05

    # HTTP timeouts
    HTTP_TIMEOUT_DEFAULT = 60.0
    HTTP_TIMEOUT_POLL = 30.0

    # Google API retry
    GOOGLE_MAX_RETRIES = 3
    GOOGLE_INITIAL_BACKOFF = 1.0
