"""
Configuration constants for the audio sync pipeline.

Timing rules, thresholds, and Ken Burns defaults used across
all audio_sync submodules.

When a visual profile is loaded, Ken Burns config reads from the profile.
Falls back to hardcoded defaults when no profile is available.
"""


# ---------------------------------------------------------------------------
# Profile integration — thin adapter with hardcoded fallbacks
# ---------------------------------------------------------------------------

def _get_profile():
    """Return the active visual profile, or None."""
    try:
        from visual_profiles import load_profile
        return load_profile()
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Timing rules (seconds)
# ---------------------------------------------------------------------------
MIN_DISPLAY_SECONDS: float = 3.0
"""No image shown for less than 3 seconds."""

MAX_DISPLAY_SECONDS: float = 300.0
"""Safety cap only — scene duration comes directly from its audio file."""

PRE_ROLL_SECONDS: float = 0.3
"""Image appears 0.3 s BEFORE its narration starts."""

POST_HOLD_SECONDS: float = 0.5
"""Image stays 0.5 s AFTER its narration ends."""

CROSSFADE_DURATION: float = 0.4
"""Default crossfade transition between images (seconds)."""

STYLE_CHANGE_FADE: float = 0.8
"""Longer fade when visual style changes (e.g. Dossier -> Echo)."""

ACT_TRANSITION_BLACK: float = 1.5
"""Brief dip-to-black between acts."""

# ---------------------------------------------------------------------------
# Alignment thresholds
# ---------------------------------------------------------------------------
MIN_MATCH_RATIO: float = 0.6
"""Minimum fuzzy-match similarity to accept an alignment."""

SEARCH_WINDOW_MULTIPLIER: int = 3
"""When searching for an excerpt in the transcript, search up to
excerpt_word_count * this multiplier positions ahead."""

# ---------------------------------------------------------------------------
# Ken Burns defaults
# ---------------------------------------------------------------------------
KEN_BURNS_BASE_DURATION: float = 11.0
"""The "reference" display duration (seconds) for which the base
zoom speed (1.0x) is calibrated."""

KEN_BURNS_PRESETS: dict[str, dict] = {
    "slow_zoom_in":   {"start_scale": 1.0,  "end_scale": 1.15},
    "slow_zoom_out":  {"start_scale": 1.15, "end_scale": 1.0},
    "slow_pan_right": {"start_x_offset": -40, "end_x_offset": 40},
    "slow_pan_left":  {"start_x_offset": 40,  "end_x_offset": -40},
    "slow_tilt_up":   {"start_y_offset": 30,  "end_y_offset": -30},
}

COMPOSITION_DIRECTION_MAP: dict[str, str] = {
    "wide":          "slow_zoom_in",
    "medium":        "slow_pan_right",
    "closeup":       "slow_zoom_out",
    "environmental": "slow_pan_left",
    "portrait":      "slow_zoom_in",
    "overhead":      "slow_zoom_in",
    "low_angle":     "slow_tilt_up",
}


def get_ken_burns_presets() -> dict[str, dict]:
    """Get Ken Burns presets from active profile or hardcoded default."""
    profile = _get_profile()
    if profile:
        return profile.ken_burns.presets
    return KEN_BURNS_PRESETS


def get_composition_direction_map() -> dict[str, str]:
    """Get composition direction map from active profile or hardcoded default."""
    profile = _get_profile()
    if profile:
        return profile.ken_burns.direction_map
    return COMPOSITION_DIRECTION_MAP


def get_ken_burns_base_duration() -> float:
    """Get Ken Burns base duration from active profile or hardcoded default."""
    profile = _get_profile()
    if profile:
        return profile.ken_burns.base_duration
    return KEN_BURNS_BASE_DURATION


# ---------------------------------------------------------------------------
# Render defaults
# ---------------------------------------------------------------------------
DEFAULT_FPS: int = 24
DEFAULT_WIDTH: int = 1920
DEFAULT_HEIGHT: int = 1080

# ---------------------------------------------------------------------------
# Whisper
# ---------------------------------------------------------------------------
# Transcription uses the OpenAI Whisper API exclusively (model: whisper-1).
# No local model support — requires OPENAI_API_KEY in .env.
