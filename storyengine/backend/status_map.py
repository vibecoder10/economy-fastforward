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


# ---------------------------------------------------------------------------
# Per-video pipeline plan (creator picks which stages run)
# ---------------------------------------------------------------------------
#
# A creator can run a SUBSET of the pipeline (e.g. "script only", "script +
# voice", "full video without sound"). These are the user-facing stages shown
# as on/off switches on the Create Video form, in chain order.
STAGE_ORDER: list[str] = [
    "research",   # fact-find the topic (optional)
    "script",     # write the script        (narrative root)
    "voice",      # AI narration            (optional)
    "images",     # prompts → storyboards → images
    "sound",      # sound design / effects  (optional)
    "video",      # animate the clips
    "thumbnail",  # YouTube thumbnail — can stand alone (just needs the topic)
    "render",     # stitch the final video
    "upload",     # publish to YouTube      (optional)
]

# Each stage's prerequisites — the stages that MUST run before it can. The plan
# logic pulls these in automatically, so a creator picks the OUTPUT they want
# and we add whatever it needs. This is what lets "thumbnail only" work: the
# thumbnail maker only needs the topic/title, so it depends on NOTHING — it can
# run with no script or video behind it. Everything else chains as expected.
STAGE_PREREQS: dict[str, list[str]] = {
    "research": [],            # optional fact-finding; needs nothing
    "script": [],              # the narrative root; needs only the topic
    "voice": ["script"],       # narrates the script
    "images": ["script"],      # illustrates the script
    "sound": ["images"],       # scored to the visual timeline
    "video": ["images"],       # animates the images
    "thumbnail": [],           # made from the topic/title alone — TRUE standalone
    "render": ["video"],       # stitches the clips
    "upload": ["render"],      # publishes the finished video
}

# First Supabase status for each user-facing stage — where a video that BEGINS
# with this stage should start.
STAGE_FIRST_STATUS: dict[str, str] = {
    "research": "idea_logged",
    "script": "ready_for_scripting",
    "voice": "ready_for_voice",
    "images": "ready_for_image_prompts",
    "sound": "ready_for_sound_design",
    "video": "ready_for_video_scripts",
    "thumbnail": "ready_for_thumbnail",
    "render": "ready_to_render",
    "upload": "uploaded_draft",
}

# Map every Supabase status to the user-facing stage whose WORK that status
# represents or triggers. ("rendered" triggers the upload stage; "ready_to_render"
# is the render stage's own work.) Used to honor a video's reduced plan.
STATUS_STAGE: dict[str, str] = {
    "idea_logged": "research",
    "approved": "research",
    "ready_for_scripting": "script",
    "ready_for_voice": "voice",
    "ready_for_image_prompts": "images",
    "ready_for_storyboards": "images",
    "ready_for_storyboard_images": "images",
    "ready_for_storyboard_extraction": "images",
    "ready_for_images": "images",
    "ready_for_sound_design": "sound",
    "ready_for_sound_effects": "sound",
    "ready_for_video_scripts": "video",
    "ready_for_video_generation": "video",
    "ready_for_thumbnail": "thumbnail",
    "ready_to_render": "render",
    "rendered": "upload",
    "uploaded_draft": "upload",
    "done": "done",
}


def _stage_index(stage: str) -> int:
    """Position of a user-facing stage in the chain (unknown → past the end)."""
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return len(STAGE_ORDER)


def _with_prereqs(selected: set) -> set:
    """Expand a set of selected stages to include every prerequisite, so the
    plan always has what each chosen stage needs to run."""
    out = set(selected)
    changed = True
    while changed:
        changed = False
        for stage in list(out):
            for need in STAGE_PREREQS.get(stage, []):
                if need not in out:
                    out.add(need)
                    changed = True
    return out


def normalize_stage_plan(stages: Optional[list[str]]) -> Optional[list[str]]:
    """Clean a raw stage selection into a valid plan.

    Given the stages a creator switched on, return the stages that should
    actually run, or None for "run the full pipeline" (no restriction).

    Rules (prerequisite model):
      * Each selected stage pulls in its prerequisites automatically (voice/
        images need a script; video needs images; render needs video; upload
        needs render). So you pick the OUTPUT and we add what it needs.
      * Stages with no prerequisites — research, script, and THUMBNAIL — can
        stand completely alone. This is what makes "thumbnail only" possible.

    Returns None when the result is the entire pipeline, so full runs and every
    existing video store NULL and keep their historical behavior untouched.
    """
    if not stages:
        return None
    selected = {s for s in stages if s in STAGE_ORDER}
    if not selected:
        return None
    enabled_set = _with_prereqs(selected)

    if len(enabled_set) == len(STAGE_ORDER):
        return None
    # Return in canonical chain order.
    return [s for s in STAGE_ORDER if s in enabled_set]


def first_status_for_plan(plan: Optional[list[str]]) -> str:
    """The Supabase status a video on this plan should START at — the first
    enabled stage's status. None (full pipeline) starts at the very beginning."""
    if not plan:
        return "idea_logged"
    for stage in STAGE_ORDER:
        if stage in plan:
            return STAGE_FIRST_STATUS.get(stage, "idea_logged")
    return "idea_logged"


def resolve_planned_status(natural_next: str, enabled_stages: Optional[list[str]]) -> str:
    """Reroute a forward status advance to honor a video's reduced stage plan.

    Given the status the pipeline would naturally advance to, return the status
    it should ACTUALLY advance to: the next enabled stage's status, or 'done'
    when the plan has no more enabled work.

    A None/empty plan means "run everything" and returns natural_next unchanged
    (the historical behavior — so videos with no plan are never affected).
    """
    if not enabled_stages:
        return natural_next
    if natural_next == "done" or natural_next not in SUPABASE_ORDER:
        return natural_next

    stop = max(_stage_index(s) for s in enabled_stages)
    start = SUPABASE_ORDER.index(natural_next)
    for status in SUPABASE_ORDER[start:]:
        stage = STATUS_STAGE.get(status, "")
        if _stage_index(stage) > stop:
            return "done"
        if stage in enabled_stages:
            return status
    return "done"


def parse_stage_plan(val) -> Optional[list[str]]:
    """Normalize a raw pipeline_stages value into a plan list, or None.

    The column is JSONB; asyncpg may hand it back as a Python list or as a JSON
    string depending on codecs, and an empty list means "full pipeline" just
    like NULL. None is returned for "no plan" (run everything) so callers can
    treat falsy as unrestricted.
    """
    if val is None:
        return None
    if isinstance(val, str):
        import json
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return None
    if isinstance(val, list) and val:
        return [s for s in val if isinstance(s, str)] or None
    return None


def stage_enabled_in_plan(stage: str, plan_value) -> bool:
    """Whether a user-facing stage should run for a video.

    A None/empty plan means the full pipeline — every stage is on (this is the
    historical default and every existing video). When a creator restricts the
    plan, only the switched-on stages may run. Used to refuse a direct call to a
    stage the creator turned off at creation time (creation-time toggles are
    permanent for a video), behind the UI which already hides that stage's tab.
    """
    plan = parse_stage_plan(plan_value)
    if not plan:
        return True
    return stage in plan


# ---------------------------------------------------------------------------
# Friendly progress states (chat-first UI)
# ---------------------------------------------------------------------------
#
# The chat experience hides the technical status chain behind 5 plain-English
# states. A status reads as the work it represents being DONE or about to start:
# e.g. ready_for_scripting still reads "Story Approved" (the script hasn't been
# written yet); the video flips to "Script Ready" once it reaches ready_for_voice
# / ready_for_image_prompts (script done, moving on). Keeps the label honest.
FRIENDLY_STATE: dict[str, str] = {
    "idea_logged":                     "Story Approved",
    "approved":                        "Story Approved",
    "ready_for_scripting":             "Story Approved",
    "ready_for_voice":                 "Script Ready",
    "ready_for_image_prompts":         "Script Ready",
    "ready_for_storyboards":           "Visuals Creating",
    "ready_for_storyboard_images":     "Visuals Creating",
    "ready_for_storyboard_extraction": "Visuals Creating",
    "ready_for_images":                "Visuals Creating",
    "ready_for_sound_design":          "Visuals Creating",
    "ready_for_sound_effects":         "Visuals Creating",
    "ready_for_video_scripts":         "Video Rendering",
    "ready_for_video_generation":      "Video Rendering",
    "ready_for_thumbnail":             "Video Rendering",
    "ready_to_render":                 "Video Rendering",
    "rendered":                        "Ready for Review",
    "uploaded_draft":                  "Ready for Review",
    "done":                            "Ready for Review",
}

# The 5 states in order — for rendering a progress tracker.
FRIENDLY_STATE_ORDER: list[str] = [
    "Story Approved",
    "Script Ready",
    "Visuals Creating",
    "Video Rendering",
    "Ready for Review",
]


def friendly_state(supabase_status: str) -> str:
    """Map a technical Supabase status to one of the 5 chat-UI states.

    Unknown statuses fall back to 'Story Approved' (the start of the journey).
    """
    return FRIENDLY_STATE.get(supabase_status, "Story Approved")
