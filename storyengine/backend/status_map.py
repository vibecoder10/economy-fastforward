"""Centralized status mapping between pipeline and Supabase.

SINGLE SOURCE OF TRUTH for all status conversions.
Pipeline uses "Ready For Scripting" format.
Supabase uses "ready_for_scripting" format.

ALL conversions MUST go through this module. No inline conversions anywhere.
"""

from typing import Optional

# Pipeline status → Supabase status
STATUS_MAP: dict[str, str] = {
    # Core pipeline flow
    "Idea Logged": "idea_logged",
    "Approved": "approved",
    "Ready For Scripting": "ready_for_scripting",
    "Ready For Voice": "ready_for_voice",
    "Ready For Image Prompts": "ready_for_image_prompts",
    "Ready For Storyboards": "ready_for_storyboards",
    "Ready For Storyboard Images": "ready_for_storyboard_images",
    "Ready For Storyboard Extraction": "ready_for_storyboard_extraction",
    "Ready For Images": "ready_for_images",
    "Ready For Sound Design": "ready_for_sound_design",
    "Ready For Sound Effects": "ready_for_sound_effects",
    "Ready For Video Scripts": "ready_for_video_scripts",
    "Ready For Video Generation": "ready_for_video_generation",
    "Ready For Thumbnail": "ready_for_thumbnail",
    "Done": "done",
    "Ready To Render": "ready_to_render",
    "Rendered": "rendered",
    "Uploaded (Draft)": "uploaded_draft",
    # Edge cases
    "In Que": "in_queue",
    "Needs Script Review": "needs_script_review",
    "Queued": "queued",
    "sent_to_pipeline": "sent_to_pipeline",
}

# Reverse map: Supabase status → Pipeline status
REVERSE_STATUS_MAP: dict[str, str] = {v: k for k, v in STATUS_MAP.items()}

# Pipeline flow order (for determining next status)
PIPELINE_ORDER: list[str] = [
    "Idea Logged",
    "Approved",
    "Ready For Scripting",
    "Ready For Voice",
    "Ready For Image Prompts",
    "Ready For Storyboards",
    "Ready For Storyboard Images",
    "Ready For Storyboard Extraction",
    "Ready For Images",
    "Ready For Sound Design",
    "Ready For Sound Effects",
    "Ready For Video Scripts",
    "Ready For Video Generation",
    "Ready For Thumbnail",
    "Ready To Render",
    "Rendered",
    "Uploaded (Draft)",
    "Done",
]

def to_supabase(pipeline_status: str) -> str:
    """Convert pipeline status to Supabase format.

    Args:
        pipeline_status: Status in pipeline format (e.g., "Ready For Scripting")

    Returns:
        Status in Supabase format (e.g., "ready_for_scripting")
    """
    if not pipeline_status:
        return ""
    return STATUS_MAP.get(pipeline_status, pipeline_status.lower().replace(" ", "_"))


def to_pipeline(supabase_status: str) -> str:
    """Convert Supabase status to pipeline format.

    Args:
        supabase_status: Status in Supabase format (e.g., "ready_for_scripting")

    Returns:
        Status in pipeline format (e.g., "Ready For Scripting")
    """
    if not supabase_status:
        return ""
    return REVERSE_STATUS_MAP.get(supabase_status, supabase_status)


def get_next_status_pipeline(current: str) -> Optional[str]:
    """Get the next pipeline status in the workflow.

    Args:
        current: Current status in pipeline format

    Returns:
        Next status in pipeline format, or None if at end
    """
    try:
        idx = PIPELINE_ORDER.index(current)
        if idx + 1 < len(PIPELINE_ORDER):
            return PIPELINE_ORDER[idx + 1]
        return None
    except ValueError:
        return None


def get_next_status_supabase(current: str) -> Optional[str]:
    """Get the next Supabase status in the workflow.

    Args:
        current: Current status in Supabase format

    Returns:
        Next status in Supabase format, or None if at end
    """
    pipeline_current = to_pipeline(current)
    next_pipeline = get_next_status_pipeline(pipeline_current)
    if next_pipeline:
        return to_supabase(next_pipeline)
    return None


def is_valid_pipeline_status(status: str) -> bool:
    """Check if a status is valid in pipeline format."""
    return status in STATUS_MAP


def is_valid_supabase_status(status: str) -> bool:
    """Check if a status is valid in Supabase format."""
    return status in REVERSE_STATUS_MAP


# Stage to bot name mapping (for activity logging)
STAGE_BOT_MAP: dict[str, str] = {
    "ready_for_scripting": "Script Bot",
    "ready_for_voice": "Voice Bot",
    "ready_for_image_prompts": "Image Prompt Bot",
    "ready_for_storyboards": "Storyboard Bot",
    "ready_for_storyboard_images": "Storyboard Images Bot",
    "ready_for_storyboard_extraction": "Storyboard Extract Bot",
    "ready_for_images": "Image Bot",
    "ready_for_sound_design": "Sound Design Bot",
    "ready_for_sound_effects": "Sound Effects Bot",
    "ready_for_video_scripts": "Video Script Bot",
    "ready_for_video_generation": "Video Gen Bot",
    "ready_for_thumbnail": "Thumbnail Bot",
    "ready_to_render": "Render Bot",
    "rendered": "YouTube Upload Bot",
}


def get_bot_name(supabase_status: str) -> str:
    """Get the bot name for a given status."""
    return STAGE_BOT_MAP.get(supabase_status, "Pipeline")


# Supabase flow order (must be after to_supabase function)
SUPABASE_ORDER: list[str] = [to_supabase(s) for s in PIPELINE_ORDER]


def is_at_or_past_stage(current_status: str, required_status: str) -> bool:
    """Check if current status is at or past the required stage.

    Used by pipeline routes to allow re-running stages (e.g., regenerating
    a script when the video is already past scripting).

    Returns True for unknown statuses to avoid blocking valid operations
    on videos with custom/edge-case statuses.
    """
    try:
        current_idx = SUPABASE_ORDER.index(current_status)
    except ValueError:
        return True
    try:
        required_idx = SUPABASE_ORDER.index(required_status)
    except ValueError:
        return True
    return current_idx >= required_idx
