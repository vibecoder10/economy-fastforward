"""Tests for the 2026-08-03 static-docu view-rotation fix.

Ryan caught this on the live product: the static-documentary pictures stage
generated 3 near-identical images for HMS Argus (video d2e37cd6-521a-43aa-
a14d-ce096a783c1e) — all left-side three-quarter compositions at slightly
different heights, instead of genuinely rotated views ("qtr angle, side
view, top view").

Root cause: every `direction` in the old `STATIC_VIEW_PLANS`
(static_docu_contract.py) asked for a three-quarter view (two of the three
explicitly forbade a side-on profile), and `static_docu.py`'s
`_studio_prompt` led with "THE EXACT SAME machine as in the verified
reference photo" — viewpoint fidelity, not just identity fidelity — so the
single reference photo's own angle dominated weak view language. Vision QA
checked subject identity but never view-role conformance, so nothing pushed
back.

This file covers the three pieces of the fix that
test_static_docu_three_view_contract.py and test_static_docu_qa_park.py
don't already cover:

1. The new contract's `direction` text — side_profile no longer forbids a
   side-on profile (it now demands one), top_planform demands a genuinely
   high camera.
2. `_view_role_confirms` — the new per-view role-conformance vision judge,
   unit-tested the same way the existing arbiter/identity judges are
   (test_static_docu_c2f_vision_gate_fixes.py's `_install_vision_fakes`).
   The retry/park ORCHESTRATION around it lives in
   test_static_docu_qa_park.py alongside the identity-QA retry/park tests
   it mirrors.
3. Skip-if-done resumability in `_one_scene` — a whole-video images run
   must not re-bill a scene whose views already satisfy the CURRENT
   contract, but old-contract rows (the pre-fix three_quarter/top_oblique/
   engineering_detail roster) must NOT satisfy the skip.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_view_rotation_fix.py -q
"""
import json
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402
from static_docu_contract import STATIC_VIEW_PLANS  # noqa: E402

# Pre-import for the same reason every other C2f-derived test file does:
# anthropic's _base_client.py subclasses httpx.AsyncClient at MODULE IMPORT
# time, so it must finish loading before any test monkeypatches
# httpx.AsyncClient to a fake callable.
import shared.clients.image_client as image_client_mod  # noqa: E402,F401

from test_static_docu_c2f_vision_gate_fixes import (  # noqa: E402
    _anthropic_body,
    _FakeResp,
    _install_vision_fakes,
)
from test_static_docu_qa_park import _pipeline_env  # noqa: E402

_PLANS = {plan["role"]: plan for plan in STATIC_VIEW_PLANS}


# ---------------------------------------------------------------------------
# 1. Contract direction text — the three roles must read as three genuinely
#    different camera geometries, not three variations on "three-quarter".
# ---------------------------------------------------------------------------

def test_exactly_three_rotated_roles_replace_the_old_contract():
    """The live defect: three near-identical compositions. The fix names
    three genuinely different camera roles — no `engineering_detail`
    three-quarter-detail role surviving to dilute the rotation."""
    assert set(_PLANS) == {"three_quarter", "side_profile", "top_planform"}
    assert "engineering_detail" not in _PLANS


def test_three_quarter_direction_uses_slightly_elevated_vantage_not_eye_level():
    """2026-08-03 same-day follow-up: live output on HMS Argus (170m
    warship) showed three_quarter generated twice and role-rejected twice
    while side_profile/top_planform passed first try — "at natural
    eye-level height" combined with "BOTH the nose/front and one full side
    visible" is near-geometrically contradictory for a subject that long
    (eye-level foreshortens everything), so the model kept splitting the
    difference. Fixed direction asks for the classic bow-quarter press/
    aerial photo (a SLIGHTLY elevated vantage) instead, and explicitly rules
    eye-level back OUT so the model doesn't default to it."""
    direction = _PLANS["three_quarter"]["direction"].lower()
    assert "three-quarter" in direction
    assert "natural eye-level height" not in direction, (
        "the old eye-level REQUIREMENT must be gone")
    assert "slightly elevated" in direction
    assert "not eye-level" in direction, (
        "eye-level should be explicitly excluded, not just silently dropped")
    assert "bow-quarter" in direction or "bow quarter" in direction
    # Identity geometry unchanged: both bow/front and one side still
    # required, and overall shape/length still has to read cleanly.
    assert "bow/front" in direction or "nose/front" in direction
    assert "one full side" in direction


def test_side_profile_direction_has_no_three_quarter_language():
    direction = _PLANS["side_profile"]["direction"].lower()
    assert "three-quarter" not in direction
    assert "three quarter" not in direction


def test_side_profile_direction_no_longer_forbids_a_side_on_profile():
    """The old contract's side-ish role explicitly said 'Never use a pure
    side-on profile'. The fixed contract's side_profile role must contain
    no such prohibition — it demands a true side-on shot instead."""
    direction = _PLANS["side_profile"]["direction"].lower()
    assert "never" not in direction
    assert "side-on" in direction
    # Explicit affirmative instruction, not just the absence of a ban.
    assert "true" in direction or "is meant to be" in direction


def test_top_planform_direction_demands_a_genuinely_high_camera():
    direction = _PLANS["top_planform"]["direction"].lower()
    assert "high" in direction
    assert "steeply down" in direction or "steeply" in direction
    assert "planform" in direction
    # Distinguished from the old (and the new three_quarter's) modest
    # elevation — must not read as just another three-quarter angle.
    assert "three-quarter" not in direction or "not a" in direction


def test_studio_prompt_leads_with_camera_geometry_not_reference_fidelity():
    """(2) Prompt ordering: the view geometry must come FIRST and read as
    the primary instruction; reference fidelity is phrased as identity
    fidelity only, and the camera angle is explicitly allowed to differ
    from the reference photo's own angle."""
    prompt = static_docu._studio_prompt(
        "Boeing XB-15", _PLANS["side_profile"], "wing structure")
    assert prompt.startswith(_PLANS["side_profile"]["direction"])
    lowered = prompt.lower()
    assert "exact same machine as in the verified reference photo" not in lowered, (
        "the old viewpoint-fidelity framing must not reappear")
    assert "identity" in lowered
    assert "differs from" in lowered or "even when it differs" in lowered


def test_studio_prompt_emphasize_geometry_amplifies_the_camera_instruction():
    """The role-conformance retry's stronger wording repeats and amplifies
    the camera instruction instead of silently reusing the same prompt."""
    base = static_docu._studio_prompt(
        "Boeing XB-15", _PLANS["top_planform"], "wing structure")
    emphasized = static_docu._studio_prompt(
        "Boeing XB-15", _PLANS["top_planform"], "wing structure",
        emphasize_geometry=True)
    assert base != emphasized
    assert "CAMERA ANGLE CORRECTION" in emphasized
    assert _PLANS["top_planform"]["direction"] in emphasized


# ---------------------------------------------------------------------------
# 2. _view_role_confirms — unit tests via the same scripted vision fakes the
#    C2f/C2h/arbiter suites use. Retry/park ORCHESTRATION around this judge
#    is covered in test_static_docu_qa_park.py's "1b" section.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_role_confirms_yes_returns_true(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, the camera is directly to the side, a flat "
                        "profile silhouette"),
    ])
    assert await static_docu._view_role_confirms(
        "tenant-1", "https://example.com/render.png", "Boeing XB-15",
        _PLANS["side_profile"]) is True


@pytest.mark.asyncio
async def test_role_confirms_no_returns_false(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, this is a three-quarter angle, not a side "
                        "profile"),
    ])
    assert await static_docu._view_role_confirms(
        "tenant-1", "https://example.com/render.png", "Boeing XB-15",
        _PLANS["side_profile"]) is False


@pytest.mark.asyncio
async def test_role_confirms_top_planform_no_when_only_modestly_elevated(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, this is a modestly elevated three-quarter "
                        "angle, not a high top-down view"),
    ])
    assert await static_docu._view_role_confirms(
        "tenant-1", "https://example.com/render.png", "Boeing XB-15",
        _PLANS["top_planform"]) is False


@pytest.mark.asyncio
async def test_role_confirms_transport_failure_fails_closed(monkeypatch):
    """Non-200 from the model API, twice: FAIL CLOSED — a role-conformance
    check that can't run must never silently pass as YES."""
    fake_client = _install_vision_fakes(monkeypatch, [
        _FakeResp({"error": "nope"}, status_code=400),
        _FakeResp({"error": "nope"}, status_code=400),
    ])
    assert await static_docu._view_role_confirms(
        "tenant-1", "https://example.com/render.png", "Boeing XB-15",
        _PLANS["side_profile"]) is False
    assert fake_client.calls == 2, "must retry exactly once, then fail closed"


@pytest.mark.asyncio
async def test_role_confirms_keyless_fails_open(monkeypatch):
    """No provider key at all is a config gap, not a transport symptom —
    same fail-open contract as `_vision_confirms`/`_render_matches_reference`
    (unlike the arbiter, which fails closed even keyless)."""
    _install_vision_fakes(monkeypatch, [], anthropic_key=None)

    import vault

    async def fake_get_secret(name, *a, **k):
        return None

    monkeypatch.setattr(vault, "get_secret", fake_get_secret)

    assert await static_docu._view_role_confirms(
        "tenant-1", "https://example.com/render.png", "Boeing XB-15",
        _PLANS["side_profile"]) is True


def test_role_with_no_geometry_requirement_trivially_passes():
    """A role absent from `_ROLE_GEOMETRY_REQUIREMENTS` (nothing today —
    reserved for a role added later with no geometry contract yet) has
    nothing to check, so the async judge should never even need to ask."""
    assert "made_up_future_role" not in static_docu._ROLE_GEOMETRY_REQUIREMENTS
    import asyncio
    result = asyncio.run(static_docu._view_role_confirms(
        "tenant-1", "https://example.com/render.png", "Boeing XB-15",
        {"role": "made_up_future_role"}))
    assert result is True


# ---------------------------------------------------------------------------
# 3. Skip-if-done / FILL resumability — a whole-video images run must not
#    re-bill an already-approved scene, a superseded contract's rows must
#    not satisfy the skip, and (2026-08-03 same-day extension) a scene
#    sitting at >= STATIC_VIEWS_MINIMUM done current-role views plus one
#    parked/missing role must FILL only the missing role rather than being
#    permanently stuck (the live HMS Argus state: side_profile +
#    top_planform done, three_quarter parked qa_rejected, no force flag or
#    redraw endpoint could ever regenerate it before this fix).
# ---------------------------------------------------------------------------

_CURRENT_ROLES = ["three_quarter", "side_profile", "top_planform"]
_OLD_ARGUS_ROLES = ["three_quarter", "top_oblique", "engineering_detail"]


def _seed_existing_assets_fetch_all(done_roles=(), parked_roles=(), scene_text=(
        "The Boeing XB-15 was the largest bomber of its day.")):
    """Builds a fake `fetch_all` that answers the scene-roster query the
    same way `_pipeline_env` already does, PLUS the skip-if-done/FILL
    `SELECT id, status, image_url, caption FROM assets ...` query with
    `done_roles` worth of pre-existing 'done' rows and `parked_roles` worth
    of pre-existing 'qa_rejected' rows. Row ids are deterministic
    (`done-<role>` / `parked-<role>`) so tests can assert on exactly which
    row got touched (or didn't)."""
    async def fake_fetch_all(query, *args):
        if "FROM assets" in query:
            rows = [
                {"id": f"done-{role}", "status": "done",
                 "image_url": "https://storage.example/existing.png",
                 "caption": json.dumps({"view_role": role})}
                for role in done_roles
            ]
            rows += [
                {"id": f"parked-{role}", "status": "qa_rejected",
                 "image_url": None,
                 "caption": json.dumps({"view_role": role})}
                for role in parked_roles
            ]
            return rows
        if "FROM scripts" in query:
            return [{"scene": 1, "scene_text": scene_text}]
        return []
    return fake_fetch_all


@pytest.mark.asyncio
async def test_skip_if_done_spends_nothing_when_current_contract_already_approved(monkeypatch):
    """(b) A scene that already has ALL target current-contract roles 'done'
    must be returned as done WITHOUT any new generation call and WITHOUT
    touching the existing rows at all — the original instant-skip, still
    intact as the no-missing-roles case of FILL mode."""
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch, verdicts=[], gen_urls=[], isolate_single_view=False,
        docu_module=static_docu, image_client_module=image_client_module,
    )
    monkeypatch.setattr(
        static_docu, "fetch_all",
        _seed_existing_assets_fetch_all(done_roles=_CURRENT_ROLES),
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert result["views_generated"] == 3
    assert result["segments_ready"] == result["segments_total"] == 1
    assert env["gen_prompts"] == [], (
        "all target roles done must not spend on any new generation")
    assert not any("assets" in q.lower() for q in env["queries"]), (
        "all target roles done must not touch the assets table at all — no "
        "delete, no placeholder insert (the schema-bootstrap CREATE TABLE "
        "calls for static_reference_cache/static_reference_misses are the "
        "only queries expected here)"
    )
    assert env["assets"] == {}


@pytest.mark.asyncio
async def test_skip_if_done_ignores_a_partial_current_contract_match(monkeypatch):
    """Only ONE current-contract role present (below STATIC_VIEWS_MINIMUM,
    which is 2) — FILL mode must not trigger either, and the unchanged
    full-regenerate path runs (delete everything, generate all 3 fresh)."""
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch,
        verdicts=[True, True],
        gen_urls=[
            "https://kie.example/three-quarter.png",
            "https://kie.example/side-profile.png",
            None,
        ],
        isolate_single_view=False,
        docu_module=static_docu, image_client_module=image_client_module,
    )
    monkeypatch.setattr(
        static_docu, "fetch_all",
        _seed_existing_assets_fetch_all(done_roles=["three_quarter"]),
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert len(env["gen_prompts"]) == 3, "one matching role is not enough to skip or fill"


@pytest.mark.asyncio
async def test_skip_if_done_regenerates_the_pre_fix_argus_roster(monkeypatch):
    """The exact scenario Ryan reported: a scene already carries the
    PRE-FIX roster (three_quarter/top_oblique/engineering_detail). Only
    `three_quarter` survives as a role NAME in the new contract, so only 1
    of 3 rows matches — below STATIC_VIEWS_MINIMUM (2) — so neither skip nor
    fill fires and the scene regenerates under the new (genuinely rotated)
    contract, wiping the stale rows first."""
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch,
        verdicts=[True, True],
        gen_urls=[
            "https://kie.example/three-quarter.png",
            "https://kie.example/side-profile.png",
            None,
        ],
        isolate_single_view=False,
        docu_module=static_docu, image_client_module=image_client_module,
    )
    monkeypatch.setattr(
        static_docu, "fetch_all",
        _seed_existing_assets_fetch_all(done_roles=_OLD_ARGUS_ROLES),
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert len(env["gen_prompts"]) == 3, "old-contract rows must not satisfy the skip"
    assert any(
        "DELETE FROM assets WHERE video_id=" in q and "generation_method=" in q
        for q in env["queries"]
    ), "the stale pre-fix roster must be wiped before regenerating"
    rows = sorted(env["assets"].values(), key=lambda row: row["image_index"])
    captions = [json.loads(row["caption"]) for row in rows]
    assert [cap["view_role"] for cap in captions] == ["three_quarter", "side_profile"]


@pytest.mark.asyncio
async def test_fill_mode_generates_only_the_missing_role_and_leaves_done_rows_untouched(
    monkeypatch,
):
    """(a) The live HMS Argus state: side_profile + top_planform 'done',
    three_quarter parked 'qa_rejected'. FILL mode must generate EXACTLY the
    missing role (one generation call, not three), leave the two done rows
    completely untouched (no delete, no update targeting them), and delete
    the stale parked row only as its replacement attempt starts.

    Stash-proof: revert the fill-mode fix and this scene has 2 'done' rows
    matching the current contract (>= STATIC_VIEWS_MINIMUM) — the OLD
    skip-if-done hard-skips on that count alone with ZERO generation calls,
    so `len(env["gen_prompts"]) == 1` fails against the old code (it would
    be 0) and only passes against the fill-mode fix."""
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch,
        verdicts=[True],
        gen_urls=["https://kie.example/three-quarter-fill.png"],
        isolate_single_view=False,
        docu_module=static_docu, image_client_module=image_client_module,
    )
    monkeypatch.setattr(
        static_docu, "fetch_all",
        _seed_existing_assets_fetch_all(
            done_roles=["side_profile", "top_planform"],
            parked_roles=["three_quarter"],
        ),
    )

    orig_execute = static_docu.execute
    delete_ids = []

    async def wrapped_execute(query, *args):
        if query == "DELETE FROM assets WHERE id=$1":
            delete_ids.append(args[0])
        return await orig_execute(query, *args)

    monkeypatch.setattr(static_docu, "execute", wrapped_execute)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert len(env["gen_prompts"]) == 1, (
        "only the missing three_quarter role should generate — the two "
        "already-done roles must not regenerate"
    )
    assert [role for (_, role) in env["role_qa_calls"]] == ["three_quarter"]
    assert result["views_generated"] == 3, (
        "2 untouched done roles + 1 newly filled role == 3 total"
    )
    assert delete_ids == ["parked-three_quarter"], (
        "the stale parked row for the role being retried must be deleted "
        "exactly once its replacement attempt starts, and the done rows' "
        "ids must never be passed to a delete"
    )
    assert not any(
        "DELETE FROM assets WHERE video_id=" in q for q in env["queries"]
    ), "fill mode must never run the whole-scene wipe"


@pytest.mark.asyncio
async def test_fill_mode_skips_entirely_when_all_target_roles_already_done(monkeypatch):
    """(b, restated for FILL mode explicitly) All three current-contract
    roles already 'done': `missing_plans` is empty, so this is exactly the
    original instant-skip path — zero generation calls, zero writes beyond
    the SELECT."""
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch, verdicts=[], gen_urls=[], isolate_single_view=False,
        docu_module=static_docu, image_client_module=image_client_module,
    )
    monkeypatch.setattr(
        static_docu, "fetch_all",
        _seed_existing_assets_fetch_all(
            done_roles=["three_quarter", "side_profile", "top_planform"],
        ),
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert result["views_generated"] == 3
    assert env["gen_prompts"] == []
    assert not any("assets" in q.lower() for q in env["queries"]), (
        "all target roles done must keep the original instant-skip: no "
        "delete, no placeholder insert, no update — just the SELECT"
    )
