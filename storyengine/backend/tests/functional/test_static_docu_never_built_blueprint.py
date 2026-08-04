"""Tests for the never-built blueprint path (Ryan's decision, 2026-08-04).

Video d2e37cd6-521a-43aa-a14d-ce096a783c1e ("Every British Aircraft Carrier
Class Ever Built") scenes 9 and 13 cover CVA-01, a carrier class CANCELLED
BEFORE CONSTRUCTION — pipeline_executor._roster_entry_never_built already
classifies its roster entry as never_built (zero hulls ever laid down), and
the static-docu reference hunt correctly, fail-closed-ly refuses to invent a
"photograph" for it (status='blocked_no_reference') — which then blocks the
whole video's render gate forever, since no retry will EVER find CVA-01 a
photo.

Ryan's call: never-built machines get an honest BLACK-AND-WHITE TECHNICAL
BLUEPRINT instead of a photo-grounded studio render — "make up an image or
just put a white and black blueprint". Implementation (static_docu.py +
static_docu_contract.py):

1. Never-built detection: `_one_scene` resolves the scene's own machine
   label against the video's locked roster (`_roster_entry_for_scene_machine`
   — the SAME resolution the reference hunt's LAYER 0b already uses) and
   checks the resolved entry's `never_built` flag
   (pipeline_executor._roster_entry_never_built).
2. Blueprint generation: exactly 2 views — side_profile (side elevation) and
   top_planform (top plan), `static_docu_contract.NEVER_BUILT_VIEW_PLANS` —
   never three_quarter. Pure text-to-image (no reference/anchor image input
   at all): `_blueprint_prompt` builds a monochrome black-linework-on-white
   technical-drawing prompt, grounded only in the scene's own vetted
   caption_specs plus the roster entry's role/years/status/built_count facts.
3. QA adaptation: `_blueprint_render_confirms` replaces
   `_render_matches_reference` (there is no reference photo to compare
   against) — checks the render IS a monochrome technical drawing of a
   plausible vehicle type, fails closed on transport errors exactly like
   every other judge in this module. Role-conformance QA
   (`_view_role_confirms`) is UNCHANGED — still checks side-on/top-down
   geometry, which applies to a line drawing exactly as well as a photo.
4. Honest caption: `_caption` stamps `"design_study": True` and prefixes
   `caption_sub` with "Design study — never built" for every blueprint view
   — `render_static.py`'s `_build_render_config` reads `caption_sub` straight
   through to Scene.tsx's `DocumentaryTitleCard`, which renders it verbatim,
   so the prefix alone reaches the screen.
5. Ledger/pricing: unchanged — the same `picture_price_for("gpt-image-2")` /
   `budget_refusal` / `record_ledger_entry` calls the photo path already uses.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_never_built_blueprint.py -q
"""
import json
import os
import sys
import uuid

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Pre-import for the same reason every other C2f-derived test file does:
# anthropic's _base_client.py subclasses httpx.AsyncClient at MODULE IMPORT
# time, so it must finish loading before any test monkeypatches
# httpx.AsyncClient to a fake callable.
import shared.clients.image_client as image_client_mod  # noqa: E402,F401

from static_docu_contract import (  # noqa: E402
    NEVER_BUILT_VIEW_PLANS,
    STATIC_VIEW_PLANS,
    STATIC_VIEWS_MINIMUM,
)
from test_static_docu_c2f_vision_gate_fixes import (  # noqa: E402
    _anthropic_body,
    _FakeResp,
    _install_vision_fakes,
)
from test_static_docu_qa_park import _ClientCM, _FakeDownloadResp  # noqa: E402
from test_static_docu_roster_reference_layer import (  # noqa: E402
    _CVA01_CLASS,
    _CVA01_PREDECESSORS,
    _UNICORN,
    _video_row,
)

CVA01_SCENE_TEXT = (
    "CVA-01 would have been the Royal Navy's first purpose-built "
    "angled-deck fleet carrier, with the island positioned well aft. "
    "The programme was cancelled in February 1966 before any steel was "
    "ever cut."
)


# ---------------------------------------------------------------------------
# Full-pipeline fixture: a video whose locked roster contains the CVA-01
# never-built entry, plus two filler entries (the roster accessor requires
# 3-40 entries). Deliberately NOT reusing test_static_docu_qa_park's
# _pipeline_env (which hardcodes a roster-less video row) — this fixture
# exists specifically to exercise the roster/never_built resolution path
# end to end.
# ---------------------------------------------------------------------------

def _blueprint_env(monkeypatch, *, gen_urls, style_verdicts=(), role_verdicts=(),
                   style_reasons=(), role_reasons=(), scene_text=CVA01_SCENE_TEXT,
                   machine="CVA-01", roster=None, scene_number=1,
                   scene_aliases=None, hunt_finds_nothing=False):
    """`roster`/`scene_number`/`scene_aliases`/`hunt_finds_nothing` (G26,
    2026-08-04) let a test drive the POSITIONAL never-built resolution path
    directly, on top of the original single-scene/single-roster shape every
    earlier test in this file still uses via the defaults:
      - `roster`: defaults to the original 3-entry CVA-01 roster. A test can
        pass the REAL "CVA-01 class" vs "Audacious class / Malta class"
        collision pair (imported from test_static_docu_roster_reference_layer)
        to exercise a scene whose name-guess is ambiguous.
      - `scene_number`: which roster POSITION (1-indexed) this scene's script
        row claims to be — `roster_entries[scene_number - 1]` is the
        positional entry _one_scene must now prefer.
      - `hunt_finds_nothing=True`: for a scene that must fall through to the
        ordinary photo-hunt path (never_built resolves False) rather than
        never running it at all — replaces the original tripwire-everything
        behavior with `_gather_reference_candidates` returning [] (so the
        scene ends up correctly `blocked_no_reference`, never a blueprint,
        without needing to fake the whole Wikipedia/Commons chain)."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    roster = roster if roster is not None else (
        [_CVA01_CLASS, {"name": "Boeing XB-15"}, {"name": "Northrop XB-35"}]
    )
    video_row = _video_row(video_id, roster)

    env = {
        "video_id": video_id,
        "tenant_id": tenant_id,
        "assets": {},
        "queries": [],
        "uploads": [],
        "downloads": [],
        "cache_lookups": [],
        "style_qa_calls": [],   # (image_url, facts) per _blueprint_render_confirms
        "role_qa_calls": [],    # (image_url, role) per _view_role_confirms
        "gen_calls": [],        # (prompt, ref_url) per generate_scene_image_gpt
    }

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            env["cache_lookups"].append(args[1] if len(args) > 1 else None)
            return None
        return None

    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{"scene": scene_number, "scene_text": scene_text}]
        if "FROM assets" in query:
            return []
        return []

    async def fake_execute(query, *args):
        env["queries"].append(query)
        if "INSERT INTO assets" in query:
            env["assets"][args[0]] = {
                "status": "generating", "image_url": None,
                "drive_image_url": args[12], "image_prompt": None,
                "image_index": args[4], "shot_type": args[6],
                "caption": args[11],
            }
        elif "UPDATE assets SET drive_image_url" in query:
            env["assets"].setdefault(args[0], {})["drive_image_url"] = args[1]
        elif "UPDATE assets SET status='qa_rejected'" in query:
            row = env["assets"].setdefault(args[0], {})
            row["status"] = "qa_rejected"
            row["image_url"] = None
            row["drive_image_url"] = args[1]
            row["image_prompt"] = args[2]
        elif "UPDATE assets SET status='budget_capped'" in query:
            env["assets"].setdefault(args[0], {})["status"] = "budget_capped"
        elif "UPDATE assets SET image_url=$2" in query:
            row = env["assets"].setdefault(args[0], {})
            row["status"] = "done"
            row["image_url"] = args[1]
            row["drive_image_url"] = args[1]
            row["image_prompt"] = args[2]
        elif "UPDATE assets SET status='blocked_no_reference'" in query:
            row = env["assets"].setdefault(args[0], {})
            row["status"] = "blocked_no_reference"
            row["image_url"] = None
            row["drive_image_url"] = None
        elif "DELETE FROM assets WHERE id=" in query:
            env["assets"].pop(args[0], None)
        return None

    async def fake_get_secret(name, *a, **k):
        return "fake-kie-key-for-test" if name == "kie_ai_api_key" else None

    class _FakeTextClient:
        async def generate(self, **kwargs):
            aliases_json = json.dumps(list(scene_aliases or []))
            return (
                f'[{{"scene": {scene_number}, "machine": "{machine}", '
                f'"aliases": {aliases_json}, '
                '"caption_title": "CVA-01 class", '
                '"caption_sub": "Royal Navy • Designed 1963-1966, cancelled 1966", '
                '"caption_specs": ["Angled flight deck", "Island set well aft"], '
                '"detail_focus": "angled deck and island layout", '
                f'"search_query": "{machine}"}}]'
            )

    async def fake_get_text_client_for_tenant(tid):
        return _FakeTextClient()

    remaining_urls = list(gen_urls)

    async def fake_generate(self, prompt, ref_url, aspect_ratio="16:9",
                            allow_fallback=False, resolution="1K"):
        env["gen_calls"].append((prompt, ref_url))
        u = remaining_urls.pop(0) if remaining_urls else None
        return {"url": u} if u else {}

    remaining_style_verdicts = list(style_verdicts)
    remaining_style_reasons = list(style_reasons)

    async def fake_blueprint_confirms(tid, image_url, m, facts=None, *, reason_out=None):
        env["style_qa_calls"].append((image_url, list(facts or [])))
        verdict = remaining_style_verdicts.pop(0) if remaining_style_verdicts else True
        if reason_out is not None:
            reason_out.append(
                remaining_style_reasons.pop(0) if remaining_style_reasons
                else ("yes, monochrome technical drawing" if verdict
                      else "no, this looks like a color photograph")
            )
        return verdict

    remaining_role_verdicts = list(role_verdicts)
    remaining_role_reasons = list(role_reasons)

    async def fake_view_role_confirms(tid, image_url, m, view_plan, *, reason_out=None):
        env["role_qa_calls"].append((image_url, view_plan.get("role")))
        verdict = remaining_role_verdicts.pop(0) if remaining_role_verdicts else True
        if reason_out is not None:
            reason_out.append(
                remaining_role_reasons.pop(0) if remaining_role_reasons
                else ("yes, correct geometry" if verdict else "no, wrong geometry")
            )
        return verdict

    class _FakeHttp:
        async def get(self, url, **kwargs):
            env["downloads"].append(url)
            return _FakeDownloadResp(b"\x89PNG" + b"x" * 40)

    def _http_factory(*a, **k):
        return _ClientCM(_FakeHttp())

    async def fake_upload_bytes(data, path, mime, tid):
        env["uploads"].append(path)
        return f"https://storage.example/{path.split('/')[-1]}"

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "_blueprint_render_confirms", fake_blueprint_confirms)
    monkeypatch.setattr(static_docu, "_view_role_confirms", fake_view_role_confirms)
    monkeypatch.setattr(static_docu, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(static_docu.httpx, "AsyncClient", _http_factory)

    # Web-hunt / reference-hunt functions must NEVER be called for a
    # never-built scene — wired to raise if they are, the same tripwire
    # test_static_docu_roster_reference_layer.py uses. `_host_reference` and
    # `_vision_confirms` (the per-candidate steps) are unreachable in EITHER
    # mode below (never-built: no hunt at all; hunt_finds_nothing: the
    # candidate list is empty, so the per-candidate loop body never runs) —
    # tripwired unconditionally so a future change that reaches them here
    # fails loudly instead of silently.
    async def _unexpected(*a, **k):
        raise AssertionError(
            "reference-hunt function must not be called for a never-built scene")

    monkeypatch.setattr(static_docu, "_host_reference", _unexpected)
    monkeypatch.setattr(static_docu, "_vision_confirms", _unexpected)
    monkeypatch.setattr(static_docu, "_render_matches_reference", _unexpected)

    if hunt_finds_nothing:
        # G26 (2026-08-04): a scene whose POSITIONAL roster entry is
        # photo-bearing (never_built resolves False) but whose name-guess is
        # ambiguous must still be ALLOWED to run the ordinary photo hunt —
        # unlike the never-built tests above, it must not tripwire. Faking
        # the top-level candidate gatherer to return none is enough to drive
        # the scene to the correctly fail-closed `blocked_no_reference`
        # outcome without hand-rolling the whole Wikipedia/Commons chain.
        env["hunt_calls"] = []

        async def fake_gather_candidates(machine_arg, aliases_arg, search_query):
            env["hunt_calls"].append((machine_arg, aliases_arg, search_query))
            return []

        monkeypatch.setattr(
            static_docu, "_gather_reference_candidates", fake_gather_candidates)
    else:
        monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", _unexpected)
        monkeypatch.setattr(static_docu, "find_article_images", _unexpected)
        monkeypatch.setattr(static_docu, "find_commons_photos", _unexpected)

    import vault
    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    import kie_unified
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant",
                        fake_get_text_client_for_tenant)
    monkeypatch.setattr(image_client_mod.ImageClient, "generate_scene_image_gpt",
                        fake_generate)

    # Same isolation as test_static_docu_qa_park._pipeline_env: actions.py /
    # generation_ledger.py are separate modules with their own DB bindings —
    # never spend-refuse and never touch a real DB in this suite.
    import actions as _actions_mod
    import generation_ledger as _ledger_mod

    env["ledger_calls"] = []

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return None

    async def fake_record_ledger_entry(**kwargs):
        env["ledger_calls"].append(kwargs)

    monkeypatch.setattr(_actions_mod, "budget_refusal", fake_budget_refusal)
    monkeypatch.setattr(_ledger_mod, "record_ledger_entry", fake_record_ledger_entry)

    return env


def _rows_by_role(env):
    return {
        json.loads(row["caption"])["view_role"]: row
        for row in env["assets"].values()
        if row.get("caption")
    }


# ---------------------------------------------------------------------------
# 1. The main end-to-end test: a never-built scene generates exactly 2
#    blueprint views, no reference/anchor image input, prompts carry
#    monochrome/technical-drawing language, both pass QA and land done with
#    design_study captions, and the scene counts as ready.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_never_built_scene_generates_two_blueprint_views_ready(monkeypatch):
    env = _blueprint_env(
        monkeypatch,
        gen_urls=[
            "https://kie.example/side-profile-blueprint.png",
            "https://kie.example/top-planform-blueprint.png",
        ],
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert result["views_generated"] == 2
    assert result["segments_ready"] == result["segments_total"] == 1

    # Exactly the two never-built roles, never three_quarter.
    assert len(env["gen_calls"]) == 2
    generated_roles = {p["role"] for p in NEVER_BUILT_VIEW_PLANS}
    assert generated_roles == {"side_profile", "top_planform"}
    assert "three_quarter" not in generated_roles

    # No reference/anchor image ever passed — pure text-to-image.
    assert [ref for _, ref in env["gen_calls"]] == [None, None]

    prompts = "\n".join(p for p, _ in env["gen_calls"]).lower()
    assert "monochrome" in prompts
    assert "technical drawing" in prompts or "technical engineering drawing" in prompts
    assert "no text" in prompts
    assert "no lettering" in prompts
    assert "reference photo" not in prompts
    assert "anchor" not in prompts
    assert "studio render" not in prompts
    # Grounded in the scene's own vetted facts, nothing invented.
    assert "angled flight deck" in prompts or "island set well aft" in prompts

    # The reference hunt never ran at all (asserted by the AssertionError
    # tripwires in _blueprint_env — if this test reaches here without
    # raising, none of them fired) and static_reference_cache was never
    # even consulted.
    assert env["cache_lookups"] == []

    # Both views pass QA (default verdicts True) and ship done.
    rows = _rows_by_role(env)
    assert set(rows.keys()) == {"side_profile", "top_planform"}
    for role, row in rows.items():
        assert row["status"] == "done"
        assert row["image_url"] is not None
        cap = json.loads(row["caption"])
        assert cap["design_study"] is True
        assert cap["sub"].startswith("Design study — never built")
        assert cap["target_views"] == 2
        assert cap["minimum_views"] == STATIC_VIEWS_MINIMUM == 2
        assert "[never-built: blueprint]" in row["image_prompt"]

    # Ledger charged exactly once per view, same model/cost path as photos.
    assert len(env["ledger_calls"]) == 2
    for call in env["ledger_calls"]:
        assert call["model"] == "gpt-image-2"
        assert call["stage"] == "image"


# ---------------------------------------------------------------------------
# 2. Role-conformance QA still applies: a blueprint view that fails
#    _view_role_confirms gets the SAME one-retry-then-park treatment as a
#    photo view.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blueprint_role_conformance_retry_ships_when_retry_passes(monkeypatch):
    env = _blueprint_env(
        monkeypatch,
        gen_urls=[
            "https://kie.example/side-1.png",
            "https://kie.example/side-2.png",
            "https://kie.example/top-1.png",
        ],
        role_verdicts=[False, True],  # first side_profile attempt fails role QA
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    rows = _rows_by_role(env)
    assert rows["side_profile"]["status"] == "done"
    assert "[qa: role-conformance retry]" in rows["side_profile"]["image_prompt"]
    assert len(env["gen_calls"]) == 3, "side_profile retried once, top_planform once"


@pytest.mark.asyncio
async def test_blueprint_double_style_reject_parks_never_deletes(monkeypatch):
    """The blueprint-style judge (`_blueprint_render_confirms`) rejects a
    view twice -> parked as qa_rejected, never deleted — same rule as a
    double identity-QA reject on the photo path."""
    env = _blueprint_env(
        monkeypatch,
        gen_urls=[
            "https://kie.example/side-1.png",
            "https://kie.example/side-2.png",
            "https://kie.example/top-1.png",
        ],
        style_verdicts=[False, False, True],
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    # side_profile parked (below STATIC_VIEWS_MINIMUM=2 with only top_planform
    # done) -> the scene fails overall, but never deletes the paid render.
    assert result["status"] == "failed"
    assert not any("DELETE FROM assets WHERE id=" in q for q in env["queries"])
    rows = _rows_by_role(env)
    assert rows["side_profile"]["status"] == "qa_rejected"
    assert rows["side_profile"]["image_url"] is None
    assert rows["side_profile"]["drive_image_url"] is not None
    assert "[blueprint-qa-reject attempt 1]" in rows["side_profile"]["image_prompt"]
    assert "[blueprint-qa-reject attempt 2]" in rows["side_profile"]["image_prompt"]


# ---------------------------------------------------------------------------
# 3. QA fail-closed on transport error — unit-level, mirroring how the
#    existing judges (_vision_confirms / _view_role_confirms) are tested.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blueprint_render_confirms_fails_closed_on_transport_error(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [
        _FakeResp({"error": "nope"}, status_code=400),
        _FakeResp({"error": "nope"}, status_code=400),
    ])
    verdict = await static_docu._blueprint_render_confirms(
        "tenant-1", "https://example.com/render.png", "CVA-01 class")
    assert verdict is False
    assert fake_client.calls == 2, "must retry exactly once, then fail closed"


@pytest.mark.asyncio
async def test_blueprint_render_confirms_yes_passes(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, this is a monochrome technical drawing of a carrier"),
    ])
    assert await static_docu._blueprint_render_confirms(
        "tenant-1", "https://example.com/render.png", "CVA-01 class") is True


@pytest.mark.asyncio
async def test_blueprint_render_confirms_no_photo_rejected(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, this is a color photograph, not a line drawing"),
    ])
    assert await static_docu._blueprint_render_confirms(
        "tenant-1", "https://example.com/render.png", "CVA-01 class") is False


@pytest.mark.asyncio
async def test_blueprint_render_confirms_keyless_fails_open(monkeypatch):
    _install_vision_fakes(monkeypatch, [], anthropic_key=None)
    import vault

    async def fake_get_secret(name, *a, **k):
        return None

    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    assert await static_docu._blueprint_render_confirms(
        "tenant-1", "https://example.com/render.png", "CVA-01 class") is True


# ---------------------------------------------------------------------------
# 4. _blueprint_prompt — unit-level wording checks.
# ---------------------------------------------------------------------------

_SIDE_PLAN = next(p for p in STATIC_VIEW_PLANS if p["role"] == "side_profile")
_TOP_PLAN = next(p for p in STATIC_VIEW_PLANS if p["role"] == "top_planform")


def test_blueprint_prompt_side_profile_is_monochrome_no_reference():
    prompt = static_docu._blueprint_prompt(
        "CVA-01 class", _SIDE_PLAN, ["Angled flight deck", "Island set well aft"])
    lowered = prompt.lower()
    assert "monochrome" in lowered
    assert "black" in lowered and "white" in lowered
    assert "no text" in lowered
    assert "no lettering" in lowered
    assert "reference photo" not in lowered
    assert "anchor" not in lowered
    assert "side elevation" in lowered
    assert "angled flight deck" in lowered


def test_blueprint_prompt_top_planform_is_plan_view():
    prompt = static_docu._blueprint_prompt("CVA-01 class", _TOP_PLAN, [])
    lowered = prompt.lower()
    assert "top-down plan" in lowered
    assert "monochrome" in lowered


def test_blueprint_prompt_emphasize_geometry_amplifies_direction():
    prompt = static_docu._blueprint_prompt(
        "CVA-01 class", _SIDE_PLAN, [], emphasize_geometry=True)
    assert "DRAWING GEOMETRY CORRECTION" in prompt


def test_blueprint_prompt_never_invents_facts_not_listed():
    prompt = static_docu._blueprint_prompt("CVA-01 class", _SIDE_PLAN, ["Displacement 53000 tons"])
    lowered = prompt.lower()
    assert "do not invent armament" in lowered
    assert "displacement 53000 tons" in lowered


# ---------------------------------------------------------------------------
# 5. Regression: an ordinary photo-bearing scene (no roster match / no
#    never_built flag) is completely untouched by this feature — still
#    generates the full 3-view photo-grounded set through the existing
#    reference-hunt + _render_matches_reference path.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_photo_bearing_scene_unaffected_regression(monkeypatch):
    from test_static_docu_qa_park import _pipeline_env

    env = _pipeline_env(
        monkeypatch,
        verdicts=[True, True, True],
        gen_urls=[
            "https://kie.example/three-quarter.png",
            "https://kie.example/side-profile.png",
            "https://kie.example/top-planform.png",
        ],
        isolate_single_view=False,
        docu_module=static_docu, image_client_module=image_client_mod,
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert result["views_generated"] == 3
    rows = _rows_by_role(env)
    assert set(rows.keys()) == {"three_quarter", "side_profile", "top_planform"}
    for row in rows.values():
        cap = json.loads(row["caption"])
        assert "design_study" not in cap
        assert not cap["sub"].startswith("Design study")
        assert cap["target_views"] == 3


# ---------------------------------------------------------------------------
# 6. G26 (2026-08-04, live bug): POSITIONAL never-built resolution.
#
# Root cause proven live on video d2e37cd6 scenes 9/13: `_one_scene`
# resolved never-built ONLY via `_roster_entry_for_scene_machine`'s
# alias-aware NAME match, which fails closed (returns None) on any
# collision across two roster entries — exactly the real "CVA-01 class" vs
# "Audacious class / Malta class" collision this suite's own docstring (and
# test_static_docu_roster_reference_layer.py) already document. Both scenes
# stayed permanently `blocked_no_reference` because the ambiguous guess
# left `never_built` False.
#
# Fix: `_research_card_facts_by_scene`'s own module comment already
# established that this render mode's scene numbering is POSITIONAL, not
# name-guessed — scene N's machine IS `roster_entries[N - 1]`. That
# positional entry is now the PRIMARY never-built signal (and the source of
# the blueprint's grounding facts); name-resolution is only the fallback,
# for when the positional entry isn't available at all.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ambiguous_guess_positional_never_built_engages_blueprint(monkeypatch):
    """(a) THE LIVE BUG, reproduced and proven fixed: the scene's guessed
    machine label "CVA-01" is ambiguous against a roster containing BOTH
    "CVA-01 class" (never built) and "Audacious class / Malta class" (its
    photo-bearing predecessor, same designation prefix) —
    `_roster_entry_for_scene_machine` correctly returns None for this exact
    collision (see test_cva01_scenes_stay_ambiguous_never_built_and_
    predecessor_collide in test_static_docu_roster_reference_layer.py).
    Before the fix, that None left `never_built` False and the scene fell
    into the ordinary photo hunt forever — `blocked_no_reference`, since no
    photograph of a never-built machine can ever exist. This scene is
    number 2 of the 3-entry roster below, so its POSITIONAL entry
    (`roster_entries[1]`) is unambiguously the CVA-01 class entry — the fix
    must use that as the primary never-built signal so this scene takes the
    blueprint path instead of blocking forever.

    Stash-proof (verified via a patch-file revert of the static_docu.py
    hunk, not `git stash`): reverting to the bare name-resolved
    `never_built = bool(roster_entry and roster_entry.get("never_built"))`
    makes this test fail — the scene falls into `_blueprint_env`'s
    tripwired photo-hunt path, whose AssertionError is caught by
    `_one_scene`'s own per-scene exception isolation (`_bounded`) and
    surfaces as `result["status"] == "failed"` instead of "completed"."""
    roster = [_CVA01_PREDECESSORS, _CVA01_CLASS, _UNICORN]
    env = _blueprint_env(
        monkeypatch,
        roster=roster,
        scene_number=2,  # roster_entries[1] == CVA-01 class (never_built=True)
        machine="CVA-01",  # ambiguous name-guess: matches BOTH roster entries
        gen_urls=[
            "https://kie.example/side-profile-blueprint.png",
            "https://kie.example/top-planform-blueprint.png",
        ],
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert result["views_generated"] == 2
    rows = _rows_by_role(env)
    assert set(rows.keys()) == {"side_profile", "top_planform"}
    for row in rows.values():
        assert row["status"] == "done"
        assert row["image_url"] is not None
        cap = json.loads(row["caption"])
        assert cap["design_study"] is True
        assert cap["sub"].startswith("Design study — never built")

    # The reference hunt never ran at all — proves the blueprint path
    # engaged rather than the scene falling through to the photo hunt.
    assert env["cache_lookups"] == []

    # The blueprint's grounding facts came from the POSITIONAL entry (CVA-01
    # class's own role/years/status/built_count), not an empty/absent set —
    # confirms facts flowed through, not just the boolean.
    style_facts = [f for _, facts in env["style_qa_calls"] for f in facts]
    assert any("cancelled" in f.lower() or "0 ships built" in f.lower()
              for f in style_facts), style_facts


@pytest.mark.asyncio
async def test_ambiguous_guess_positional_photo_bearing_falls_through(monkeypatch):
    """(b) The collision-safety mirror of (a): SAME ambiguous "CVA-01"
    name-guess, SAME collision roster, but this scene is number 1 — its
    POSITIONAL entry (`roster_entries[0]`, "Audacious class / Malta class")
    is photo-bearing (one hull WAS completed as HMS Eagle), not never-built.
    Positional resolution must never manufacture a false never-built verdict
    for a real machine just because it shares a designation prefix with a
    cancelled one elsewhere in the same roster — this scene must fall
    through to the ordinary photo-hunt path. The hunt here is faked to find
    nothing, so the scene correctly blocks — proving it took the hunt path
    at all (a never-built misclassification would have skipped the hunt
    entirely and produced a blueprint instead)."""
    roster = [_CVA01_PREDECESSORS, _CVA01_CLASS, _UNICORN]
    env = _blueprint_env(
        monkeypatch,
        roster=roster,
        scene_number=1,  # roster_entries[0] == Audacious/Malta (never_built=False)
        machine="CVA-01",  # same ambiguous name-guess as test (a)
        gen_urls=[],
        hunt_finds_nothing=True,
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "failed"
    # No blueprint (or any) view was ever generated for this scene.
    assert env["gen_calls"] == []
    # The ordinary photo hunt DID run (not the never-built tripwired path).
    assert len(env["hunt_calls"]) == 1
    blocked = [row for row in env["assets"].values()
              if row.get("status") == "blocked_no_reference"]
    assert len(blocked) == 1
    assert blocked[0]["image_url"] is None


@pytest.mark.asyncio
async def test_scene_beyond_roster_length_falls_back_to_name_resolution(monkeypatch):
    """(c) Bounds: a scene number past the end of the roster has no
    positional entry at all (`1 <= sc <= len(roster_entries)` is False) —
    never-built detection falls back to name-resolution exactly as it did
    before this fix. Reuses the same default roster/machine as the main
    end-to-end test above (where "CVA-01" name-resolves UNAMBIGUOUSLY to the
    never-built CVA-01 class entry, since the roster's other two entries
    share no aliases with it) but numbers the scene 5 — past the 3-entry
    roster's end — to prove the fallback engages and reaches the identical
    blueprint outcome as before this fix."""
    env = _blueprint_env(
        monkeypatch,
        scene_number=5,  # out of bounds for the default 3-entry roster
        gen_urls=[
            "https://kie.example/side-profile-blueprint.png",
            "https://kie.example/top-planform-blueprint.png",
        ],
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert result["views_generated"] == 2
    rows = _rows_by_role(env)
    assert set(rows.keys()) == {"side_profile", "top_planform"}
    for row in rows.values():
        assert row["status"] == "done"
        cap = json.loads(row["caption"])
        assert cap["design_study"] is True
        assert cap["sub"].startswith("Design study — never built")
    # The reference hunt never ran — same fail-closed proof as the main
    # never-built test.
    assert env["cache_lookups"] == []
