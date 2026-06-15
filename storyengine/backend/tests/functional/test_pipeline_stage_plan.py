"""Per-video pipeline plan: the chain rules and the forward-advance reroute.

A creator can run a subset of the pipeline (script only, script+voice, full
video without sound, etc.). normalize_stage_plan cleans their selection into a
valid chain-enforced plan; resolve_planned_status reroutes each forward status
advance to honor that plan — skipping turned-off stages and stopping at 'done'
when the plan is complete. These lock the behavior the whole feature rests on.
Pure-function tests — no DB, no pipeline run.
"""
import pytest

from status_map import normalize_stage_plan, resolve_planned_status, STAGE_ORDER


# --- normalize_stage_plan: clean a raw selection into a valid plan ------------

def test_full_selection_stores_null():
    # Everything on == the historical default == NULL (unchanged behavior).
    assert normalize_stage_plan(list(STAGE_ORDER)) is None
    assert normalize_stage_plan(None) is None
    assert normalize_stage_plan([]) is None


def test_script_is_always_included():
    # Script is the root deliverable; it can never be dropped.
    assert "script" in normalize_stage_plan(["research"])
    assert normalize_stage_plan(["script"]) == ["script"]


def test_script_plus_voice():
    assert normalize_stage_plan(["research", "script", "voice"]) == ["research", "script", "voice"]


def test_enabling_a_late_stage_pulls_in_backbone_prereqs():
    # You can't upload a video you never made — upload forces images/video/render.
    assert normalize_stage_plan(["script", "upload"]) == [
        "script", "images", "video", "render", "upload",
    ]


def test_optional_stage_can_be_dropped_mid_chain():
    # Full video without voice: every step except the optional voice stage.
    no_voice = [s for s in STAGE_ORDER if s != "voice"]
    assert normalize_stage_plan(no_voice) == no_voice


def test_nothing_past_the_furthest_selected_stage():
    # Selecting through render must not silently add upload.
    plan = normalize_stage_plan(["script", "images", "video", "render"])
    assert "upload" not in plan
    assert plan[-1] == "render"


# --- resolve_planned_status: reroute a forward advance to honor the plan ------

def test_no_plan_is_passthrough():
    # NULL plan (existing videos / full runs) is never rerouted.
    assert resolve_planned_status("ready_for_voice", None) == "ready_for_voice"
    assert resolve_planned_status("ready_for_images", []) == "ready_for_images"


def test_script_only_stops_after_script():
    assert resolve_planned_status("ready_for_voice", ["script"]) == "done"


def test_script_plus_voice_runs_then_stops():
    plan = ["research", "script", "voice"]
    assert resolve_planned_status("ready_for_voice", plan) == "ready_for_voice"
    assert resolve_planned_status("ready_for_image_prompts", plan) == "done"


def test_disabled_voice_is_skipped_not_stopped():
    # Voice off but images on → script advances straight past voice to images.
    no_voice = [s for s in STAGE_ORDER if s != "voice"]
    assert resolve_planned_status("ready_for_voice", no_voice) == "ready_for_image_prompts"


def test_disabled_sound_is_skipped_mid_chain():
    plan = ["script", "images", "video", "render"]  # no sound, no thumbnail
    assert resolve_planned_status("ready_for_sound_design", plan) == "ready_for_video_scripts"


def test_no_upload_stops_after_render_but_upload_keeps_draft():
    no_upload = ["script", "images", "video", "render"]
    assert resolve_planned_status("rendered", no_upload) == "done"
    full = ["script", "images", "video", "render", "upload"]
    assert resolve_planned_status("rendered", full) == "rendered"
    assert resolve_planned_status("uploaded_draft", full) == "uploaded_draft"


def test_done_is_terminal():
    assert resolve_planned_status("done", ["script"]) == "done"
