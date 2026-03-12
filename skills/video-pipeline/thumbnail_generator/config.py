"""Configuration constants for EFF Thumbnail Generator.

API settings, color palette, and generation parameters for Nano Banana Pro
thumbnail generation via Kie.ai.

When a visual profile is loaded, model/cost/color settings read from the
profile. Falls back to hardcoded defaults when no profile is available.
"""


# ---------------------------------------------------------------------------
# Profile integration
# ---------------------------------------------------------------------------

def _get_profile():
    """Return the active visual profile, or None."""
    try:
        from visual_profiles import load_profile
        return load_profile()
    except Exception:
        return None


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


def get_thumbnail_model() -> str:
    """Get thumbnail model from profile or default."""
    profile = _get_profile()
    if profile:
        return profile.image_gen.thumbnail_model
    return MODEL_NAME


def get_thumbnail_cost() -> float:
    """Get thumbnail cost per image from profile or default."""
    profile = _get_profile()
    if profile:
        return profile.image_gen.thumbnail_cost_per_image
    return COST_PER_IMAGE


def get_thumbnail_model_params() -> dict:
    """Get thumbnail model params from profile or defaults."""
    profile = _get_profile()
    if profile and profile.image_gen.thumbnail_model_params:
        return profile.image_gen.thumbnail_model_params
    return {"aspect_ratio": ASPECT_RATIO, "resolution": RESOLUTION, "output_format": OUTPUT_FORMAT}


def get_thumbnail_figure_rules() -> str:
    """Get thumbnail figure rules from profile or default."""
    profile = _get_profile()
    if profile and profile.thumbnail.thumbnail_figure_rules:
        return profile.thumbnail.thumbnail_figure_rules
    return "Generic building/hand, no named political figures"


def get_thumbnail_color_presets() -> dict:
    """Get thumbnail color presets from profile or empty dict."""
    profile = _get_profile()
    if profile and profile.thumbnail.thumbnail_color_presets:
        return profile.thumbnail.thumbnail_color_presets
    return {}


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
