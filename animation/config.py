"""Configuration constants and environment variable loading for the animation module."""

import os
from dotenv import load_dotenv

load_dotenv()

# ==================== AIRTABLE (R50 | Cinematic Adverts System) ====================
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_ANIMATION_BASE_ID = os.getenv("AIRTABLE_ANIMATION_BASE_ID", "appB9RWwCgywdwYrT")
AIRTABLE_PROJECT_TABLE_ID = os.getenv("AIRTABLE_PROJECT_TABLE", "tblYiND5DkrZhIlLq")
AIRTABLE_SCENES_TABLE_ID = os.getenv("AIRTABLE_SCENES_TABLE", "tblipThhapetdSJdm")

# ==================== API KEYS ====================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
KIE_API_KEY = os.getenv("KIE_AI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0A9U1X8NSW")

# ==================== MODELS ====================
SCENE_PLANNER_MODEL = "claude-sonnet-4-5-20250929"
QC_MODEL = "claude-haiku-4-5-20241022"

# ==================== IMAGE GENERATION ====================
SCENE_IMAGE_MODEL = "bytedance/seedream-v4-text-to-image"
THUMBNAIL_IMAGE_MODEL = "nano-banana-pro"

# ==================== VIDEO GENERATION ====================
VEO_MODEL = "google/veo-3.1-fast"
VEO_COST_PER_CLIP = 0.30  # $0.30 per 8s clip
IMAGE_COST_PER_IMAGE = 0.025  # $0.025 per image

# ==================== BUDGET ====================
ANIMATION_BUDGET_DEFAULT = float(os.getenv("ANIMATION_BUDGET_DEFAULT", "20"))
MAX_REGEN_ATTEMPTS = int(os.getenv("MAX_REGEN_ATTEMPTS", "2"))
BUDGET_ALERT_THRESHOLD = 0.80  # Alert at 80% of budget

# ==================== KIE.AI API ====================
KIE_CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

# ==================== PROTAGONIST ====================
PROTAGONIST_PROMPT_FRAGMENT = (
    "3D clay render humanoid figure with average slim normal human proportions, "
    "matte gray body, warm gold amber glow emanating from chest through subtle "
    "cracks in clay surface, faint golden light traces along joints and eye sockets, "
    "the amber glow casts warm light on nearby surfaces"
)

BACKGROUND_CHARACTER_FRAGMENT = (
    "neutral gray matte droid figures with no glow, "
    "uniform featureless clay surface, no light emanation"
)

NEGATIVE_PROMPT_DEFAULT = (
    "no photorealistic, no flat 2D, no realistic skin, no anime, no cartoon"
)

# ==================== SCENE TYPES ====================
SCENE_TYPES = ["animated", "ken_burns", "static"]
CAMERA_DIRECTIONS = [
    "push_in", "pull_back", "pan_lr", "pan_rl",
    "overhead", "eye_level", "low_angle", "static",
]
GLOW_BEHAVIORS = ["steady", "flickering", "dimming", "pulsing", "surging", "off"]
COLOR_TEMPERATURES = ["warm", "neutral", "cool", "cold"]
TRANSITIONS = ["hard_cut", "crossfade", "match_cut", "fade_to_black"]

# ==================== PIPELINE STATUS ====================
PROJECT_STATUS_CREATE = "Create"
PROJECT_STATUS_PLANNING = "Planning Scenes"
PROJECT_STATUS_GENERATING_FRAMES = "Generating Frames"
PROJECT_STATUS_ANIMATING = "Animating"
PROJECT_STATUS_QC = "Quality Check"
PROJECT_STATUS_DONE = "Done"
PROJECT_STATUS_FAILED = "Failed"
PROJECT_STATUS_BUDGET_EXCEEDED = "Budget Exceeded"
