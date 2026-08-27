"""The render verb's precondition is format-aware (static-documentary fix).

Live repro (2026-08-04, video d2e37cd6-521a-43aa-a14d-ce096a783c1e, tenant
561b872d): render_mode='static_docu', status ready_for_thumbnail, 23/23
scenes voiced, every scene holding >= 2 verified static views — and the MCP
render verb (routes/mcp.py _call_verb -> actions.blocked_reason, the SAME
shared gate chat.py and agent_brain.py use) refused with "nothing's been
animated yet — I'd animate the scenes first". Static documentaries never
animate: status_map.static_stage_plan drops the 'video' stage entirely and
render_static.py holds verified still views over the narration, so clip
count is the wrong precondition for the format.

The fix: status_map.render_path_needs_clips() (False for static_docu, and
for any stored stage plan whose render excludes the 'video' stage), threaded
through actions.video_summary() as summary['render_needs_clips'] and
consulted by actions.blocked_reason()'s clips gate — which for a clip-free
render gates on the format's REAL prerequisites instead (all scenes voiced +
pictures drawn — the same readiness production_guide's voice/images stages
read; render_static.py stays the authoritative per-scene check).

Non-vacuous: test_static_docu_render_not_blocked_on_clip_count (the exact
live-repro summary) and test_video_summary_carries_render_needs_clips both
FAIL against the pre-fix code — the gate returned NEEDS_REASON['clips'] for
precisely this summary, and video_summary never set the key (whose absence
fails OPEN into the old clip-count gate by design).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_render_verb_static_docu_gate.py -q
"""
import asyncio
import json
import os
import sys
from unittest.mock import patch

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402
import render_static  # noqa: E402
import routes.pipeline as pipeline_routes  # noqa: E402
import status_map  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("imported_count", [1, 2, 3])
async def test_render_route_gate_requires_complete_never_built_handoff(
    monkeypatch, imported_count,
):
    roles = ("three_quarter", "side_profile", "top_planform")

    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{
                "scene": 1, "scene_text": "Paper carrier.",
                "voice_over_url": "voice.mp3", "voice_duration_seconds": 8.0,
            }]
        return [{
            "scene": 1, "image_index": index,
            "image_url": f"https://storage.example/{role}.png"
            if index <= imported_count else None,
            "status": "done" if index <= imported_count
            else "awaiting_chatgpt_generation",
            "generation_method": "static_docu", "hero_shot": index == 1,
            "transition_kind": None,
            "caption": json.dumps({
                "view_role": role,
                "generation_source": "chatgpt_thread"
                if index <= imported_count else None,
                "design_study": True,
                "reconstruction_style": "photorealistic",
            }),
        } for index, role in enumerate(roles, start=1)]

    monkeypatch.setattr(render_static, "fetch_all", fake_fetch_all)
    assert hasattr(pipeline_routes, "_static_render_blocker")
    blocker = await pipeline_routes._static_render_blocker(VIDEO, TENANT)
    if imported_count < 3:
        assert blocker and "awaiting ChatGPT generation" in blocker
    else:
        assert blocker is None


def _static_summary(**over):
    """A video_summary()-shaped dict mirroring the live repro video: a
    static documentary at ready_for_thumbnail with every scene voiced,
    two verified views per scene, and — correctly, for this format —
    zero animated clips."""
    base = {
        "title": "DvsU static documentary", "status": "ready_for_thumbnail",
        "length_min": 8, "model": "grok-imagine", "scenes": 23, "boards": 23,
        "voiced": 23, "max_scene": 23, "pics": 46, "clips": 0, "cast": 0,
        "envs": 0, "chars_approved": False, "envs_approved": False,
        "spent": 3.0, "total_cost": 3.0, "max_spend": None, "validation": "",
        "render_style": None, "render_mode": "static_docu",
        "plays_sfx": False, "sfx_blocked_reason": "static",
        "render_needs_clips": False,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. actions.blocked_reason(): the format-aware render gate
# ---------------------------------------------------------------------------

def test_static_docu_render_not_blocked_on_clip_count():
    """THE live repro: a render-ready static documentary (all scenes voiced,
    views drawn, clips=0) must NOT be refused. Pre-fix this returned
    NEEDS_REASON['clips'] ("nothing's been animated yet")."""
    blocked = actions.blocked_reason("render", _static_summary())
    assert blocked is None, f"render-ready static docu was refused: {blocked!r}"
    print("✅ test_static_docu_render_not_blocked_on_clip_count")


def test_animated_render_still_blocked_without_clips():
    """Regression lock: a NORMAL (animated) video with no clips keeps the
    historical refusal, message byte-identical."""
    summary = _static_summary(render_mode=None, render_needs_clips=True)
    assert actions.blocked_reason("render", summary) == actions.NEEDS_REASON["clips"]
    # A summary dict built WITHOUT the key (pre-fix caller) fails OPEN into
    # the same historical clip-count gate.
    legacy = _static_summary(render_mode=None)
    legacy.pop("render_needs_clips")
    assert actions.blocked_reason("render", legacy) == actions.NEEDS_REASON["clips"]
    print("✅ test_animated_render_still_blocked_without_clips")


def test_static_docu_render_gates_on_its_real_prerequisites():
    """A clip-free render is still gated — on narration and pictures, the
    format's actual prerequisites (static_stage_plan's render prereq)."""
    assert (actions.blocked_reason("render", _static_summary(scenes=0, voiced=0, pics=0))
            == actions.NEEDS_REASON["scenes"])
    partial = actions.blocked_reason("render", _static_summary(voiced=12))
    assert partial and "12 of 23" in partial and "voice" in partial
    assert (actions.blocked_reason("render", _static_summary(pics=0))
            == actions.NEEDS_REASON["pictures"])
    print("✅ test_static_docu_render_gates_on_its_real_prerequisites")


# ---------------------------------------------------------------------------
# 2. status_map.render_path_needs_clips(): the format predicate
# ---------------------------------------------------------------------------

def test_render_path_needs_clips_matrix():
    f = status_map.render_path_needs_clips
    assert f({"render_mode": "static_docu"}) is False
    assert f({"render_mode": None}) is True
    assert f({}) is True
    assert f(None) is True
    # The format-generic rule: a stored plan whose render excludes 'video'
    # (today only static_stage_plan writes one — exercised here through
    # parse_stage_plan's JSON-string branch, how asyncpg can hand JSONB back).
    assert f({"pipeline_stages": '["script", "voice", "images", "render"]'}) is False
    assert f({"pipeline_stages": ["script", "voice", "images", "render"]}) is False
    # render + video in plan -> clips consumed; a plan without render at all
    # says nothing about the render path -> historical default.
    assert f({"pipeline_stages": ["script", "images", "video", "render"]}) is True
    assert f({"pipeline_stages": ["script", "images"]}) is True
    # static_stage_plan's own output is always clip-free.
    assert f({"pipeline_stages": status_map.static_stage_plan(None)}) is False
    print("✅ test_render_path_needs_clips_matrix")


# ---------------------------------------------------------------------------
# 3. actions.video_summary(): the wiring (key actually set from the row)
# ---------------------------------------------------------------------------

def test_video_summary_carries_render_needs_clips():
    """blocked_reason's `.get('render_needs_clips', True)` fails OPEN — so if
    video_summary ever stopped setting the key, the static-docu fix would
    silently regress into the old refusal. Pin the wiring end-to-end for
    both formats."""
    def _fake_fetch_one_for(render_mode):
        async def fake_fetch_one(query, *a):
            if "FROM videos" in query:
                return {
                    "video_title": "T", "status": "ready_for_thumbnail",
                    "video_length_minutes": 8, "video_model": "grok-imagine",
                    "script_validation": None, "render_style": None,
                    "render_mode": render_mode, "total_cost": 0, "max_spend": None,
                    "custom_film_plan_id": None, "dialogue_audio": None,
                    "dialogue_mode": None, "pipeline_stages": None,
                    "characters_approved_at": None, "environments_approved_at": None,
                }
            if "FROM scripts" in query:
                return {"scenes": 23, "boards": 23, "voiced": 23, "max_scene": 23}
            if "FROM assets" in query:
                return {"pics": 46, "clips": 0}
            if "FROM video_characters" in query:
                return {"n": 0}
            if "FROM video_environments" in query:
                return {"n": 0}
            raise AssertionError(f"unexpected query: {query}")
        return fake_fetch_one

    with patch.object(actions, "fetch_one", _fake_fetch_one_for("static_docu")):
        summary = asyncio.run(actions.video_summary(TENANT, VIDEO))
    assert summary["render_needs_clips"] is False
    # The full chain the MCP door runs (routes/mcp.py _call_verb):
    # video_summary -> blocked_reason. Pre-fix: the "nothing's been
    # animated" refusal; post-fix: clear to render.
    assert actions.blocked_reason("render", summary) is None

    with patch.object(actions, "fetch_one", _fake_fetch_one_for(None)):
        summary = asyncio.run(actions.video_summary(TENANT, VIDEO))
    assert summary["render_needs_clips"] is True
    assert actions.blocked_reason("render", summary) == actions.NEEDS_REASON["clips"]
    print("✅ test_video_summary_carries_render_needs_clips")


if __name__ == "__main__":
    test_static_docu_render_not_blocked_on_clip_count()
    test_animated_render_still_blocked_without_clips()
    test_static_docu_render_gates_on_its_real_prerequisites()
    test_render_path_needs_clips_matrix()
    test_video_summary_carries_render_needs_clips()
