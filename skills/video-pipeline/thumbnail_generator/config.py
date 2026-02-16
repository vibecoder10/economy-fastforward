"""Configuration constants for EFF Thumbnail Generator.

API settings, color palette, and generation parameters for Nano Banana Pro
thumbnail generation via Kie.ai.
"""

# ---------------------------------------------------------------------------
# Nano Banana Pro API (via Kie.ai)
# ---------------------------------------------------------------------------
# Kie.ai uses a task-based API: create task -> poll for result
API_BASE_URL = "https://api.kie.ai/api/v1/jobs"
CREATE_TASK_URL = f"{API_BASE_URL}/createTask"
RECORD_INFO_URL = f"{API_BASE_URL}/recordInfo"
MODEL_NAME = "nano-banana-pro"

ASPECT_RATIO = "16:9"  # NEVER change this — wrong ratio causes black bars
RESOLUTION = "2K"
OUTPUT_FORMAT = "png"
MAX_ATTEMPTS = 3  # Max regenerations before flagging for manual review
COST_PER_IMAGE = 0.09  # USD at 2K resolution

# Polling settings
POLL_INITIAL_WAIT = 5.0  # Seconds before first poll
POLL_INTERVAL = 2.0  # Seconds between polls
POLL_MAX_ATTEMPTS = 45  # Max poll iterations (~90 seconds total)

# ---------------------------------------------------------------------------
# Color palette (for reference/validation — colors are baked into prompts)
# ---------------------------------------------------------------------------
COLORS = {
    "bg_navy": "#0A0F1A",
    "bg_crimson": "#8B1A1A",
    "bg_midnight": "#1A2A4A",
    "accent_gold": "#FFB800",
    "accent_red": "#E63946",
    "accent_green": "#22C55E",
    "text_white": "#FFFFFF",
}
