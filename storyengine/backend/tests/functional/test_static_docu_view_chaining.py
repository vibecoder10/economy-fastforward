"""Tests for the static-docu CHAINED-VIEW generation fix (2026-08-xx).

Ryan's design change: every view in a static-documentary scene used to be
generated straight from the RAW historical reference photo. That photo's own
camera angle bled into every generation regardless of the requested view
role — live proof: HMS Argus (video d2e37cd6-521a-43aa-a14d-ce096a783c1e)
scene 1, whose side-on reference kept winning against `three_quarter`
across 6 total role-rejected attempts (2026-08-03's role-conformance QA fix
made the rejections visible; it never fixed the root cause).

Fix (`_one_scene` / `_generate_view` in static_docu.py):
- Anchor selection: the scene's ANCHOR is the first available DONE view
  render — either pre-existing (FILL mode: the scene's done rows, preferred
  in STATIC_VIEW_PLANS order) or the first view that completes during THIS
  run. Fixed once set; later views chain off that SAME anchor, never off
  each other (no rolling per-view chain).
- Chained generation: once an anchor exists, `_generate_view` passes the
  ANCHOR's own `image_url` as the image input to `generate_scene_image_gpt`
  instead of the raw historical reference photo, and `_studio_prompt`'s
  `from_anchor=True` swaps the "verified reference photo" noun phrase for
  "verified clean studio render of the SAME machine" — identity-fidelity
  language and the camera-geometry-first prompt structure are unchanged.
- Identity QA (`_render_matches_reference`) is UNCHANGED: it always judges
  the render against the ORIGINAL hosted historical reference (`ref_url`),
  never the anchor, so the chain can never let identity drift.
- No anchor available (a fresh scene's first view, or every prior view this
  run parked) falls back to the reference photo exactly like before.
- Every attempt records which input it used in the row's `image_prompt`
  trail: `[input: reference]` or `[input: anchor <role>]`.

Plumbing note: the anchor is a done row's OWN `image_url`, which was
written via the SAME `storage.upload_bytes()` (and therefore the SAME
Drive-hosted URL shape) as the original self-hosted reference photo
(`_host_reference`). `assets.image_url` is already in the media proxy's
allowlist (`routes/media.py::_ALLOWLIST_SQL`), and `ImageClient`'s
`_kie_fetchable_url()` (called from `generate_thumbnail_gpt2`, which
`generate_scene_image_gpt` delegates to whenever a reference/anchor URL is
passed) already rewrites ANY Drive-hosted URL to the tenant-scoped media
proxy at call time — the exact same mechanism the raw reference has always
used. No new hosting or proxy code was needed; passing the anchor's
`image_url` as the reference argument is enough.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_view_chaining.py -q
"""
import json
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Pre-import for the same reason every other C2f-derived test file does:
# anthropic's _base_client.py subclasses httpx.AsyncClient at MODULE IMPORT
# time, so it must finish loading before any test monkeypatches
# httpx.AsyncClient to a fake callable.
import shared.clients.image_client as image_client_mod  # noqa: E402,F401

from static_docu_contract import STATIC_VIEW_PLANS  # noqa: E402
from test_static_docu_qa_park import REF_HOSTED, REF_SOURCE, _pipeline_env  # noqa: E402

_PLANS = {plan["role"]: plan for plan in STATIC_VIEW_PLANS}
DEFAULT_SCENE_TEXT = "The Boeing XB-15 was the largest bomber of its day."

DONE_SIDE_PROFILE_URL = "https://storage.example/side-profile-done.png"
DONE_TOP_PLANFORM_URL = "https://storage.example/top-planform-done.png"


def _capture_gen_refs(monkeypatch, env, image_client_module):
    """Wraps the fake `generate_scene_image_gpt` `_pipeline_env` already
    installed so it ALSO records the reference/anchor URL each call
    received — `_pipeline_env`'s own `env["gen_prompts"]` only tracks the
    prompt text, never which image was passed as the generation input."""
    env["gen_refs"] = []
    prior = image_client_module.ImageClient.generate_scene_image_gpt

    async def capturing(self, prompt, ref_url, aspect_ratio="16:9",
                        allow_fallback=False, resolution="1K"):
        env["gen_refs"].append(ref_url)
        return await prior(self, prompt, ref_url, aspect_ratio=aspect_ratio,
                           allow_fallback=allow_fallback, resolution=resolution)

    monkeypatch.setattr(image_client_module.ImageClient,
                        "generate_scene_image_gpt", capturing)


def _numbered_uploads(monkeypatch, docu_module):
    """Replaces `_pipeline_env`'s fixed-DURABLE fake `upload_bytes` with one
    that returns a DISTINCT url per call, numbered in call order — proves a
    later view chains off the FIRST completed view's render specifically
    (not off whichever view generated most recently), which a shared fixed
    constant can't distinguish."""
    urls = []
    counter = {"n": 0}

    async def fake_upload_bytes(data, path, mime, tid):
        counter["n"] += 1
        url = f"https://storage.example/durable-{counter['n']}.png"
        urls.append(url)
        return url

    monkeypatch.setattr(docu_module, "upload_bytes", fake_upload_bytes)
    return urls


def _rows_by_role(env):
    return {
        json.loads(row["caption"])["view_role"]: row
        for row in env["assets"].values()
        if row.get("caption")
    }


def _seed_done_roles_fetch_all(done_role_urls, scene_text=DEFAULT_SCENE_TEXT):
    """A fake `fetch_all` seeding one 'done' row per (role -> image_url)
    pair, distinct URLs so a test can prove exactly which done role's URL
    got picked as the anchor."""
    async def fake_fetch_all(query, *args):
        if "FROM assets" in query:
            return [
                {"id": f"done-{role}", "status": "done", "image_url": url,
                 "caption": json.dumps({"view_role": role})}
                for role, url in done_role_urls.items()
            ]
        if "FROM scripts" in query:
            return [{"scene": 1, "scene_text": scene_text}]
        return []
    return fake_fetch_all


# ---------------------------------------------------------------------------
# (a) Fresh scene: first view generated with the reference as input, later
#     views chain off the FIRST completed view's own render — not a rolling
#     per-view chain (view 3 must not chain off view 2's own render).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_scene_first_view_uses_reference_later_views_chain_off_anchor(
    monkeypatch,
):
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch,
        verdicts=[True, True, True],
        gen_urls=[
            "https://kie.example/three-quarter.png",
            "https://kie.example/side-profile.png",
            "https://kie.example/top-planform.png",
        ],
        isolate_single_view=False,
        docu_module=static_docu, image_client_module=image_client_module,
    )
    _capture_gen_refs(monkeypatch, env, image_client_module)
    durable_urls = _numbered_uploads(monkeypatch, static_docu)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert len(env["gen_refs"]) == 3

    # View 1 (three_quarter): no anchor yet — the raw historical reference.
    assert env["gen_refs"][0] == REF_HOSTED
    # Views 2 and 3 (side_profile, top_planform) both chain off view 1's OWN
    # durable render, never off each other's — a rolling chain would have
    # view 3 receive view 2's url (durable_urls[1]) instead.
    assert durable_urls[1] != durable_urls[0], "sanity: uploads are distinct per call"
    assert env["gen_refs"][1] == durable_urls[0]
    assert env["gen_refs"][2] == durable_urls[0]

    rows = _rows_by_role(env)
    assert rows["three_quarter"]["image_prompt"].startswith(
        f"[ref: {REF_SOURCE}] [input: reference] ")
    assert rows["side_profile"]["image_prompt"].startswith(
        f"[ref: {REF_SOURCE}] [input: anchor three_quarter] ")
    assert rows["top_planform"]["image_prompt"].startswith(
        f"[ref: {REF_SOURCE}] [input: anchor three_quarter] ")

    # Prompt wording: the first view's prompt still describes a reference
    # PHOTO; later views' prompts describe a studio RENDER of the machine.
    assert "verified reference photo" in rows["three_quarter"]["image_prompt"].lower()
    assert (
        "verified clean studio render of the same machine"
        in rows["side_profile"]["image_prompt"].lower()
    )
    assert (
        "verified clean studio render of the same machine"
        in rows["top_planform"]["image_prompt"].lower()
    )


# ---------------------------------------------------------------------------
# (b) FILL mode with a done side_profile (+ a done top_planform, the exact
#     live HMS Argus state): the missing three_quarter generation receives
#     the ANCHOR input (side_profile — earlier in STATIC_VIEW_PLANS order),
#     and both done rows are left completely untouched.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fill_mode_missing_view_chains_off_earliest_plan_order_done_role(
    monkeypatch,
):
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
        _seed_done_roles_fetch_all({
            "side_profile": DONE_SIDE_PROFILE_URL,
            "top_planform": DONE_TOP_PLANFORM_URL,
        }),
    )
    _capture_gen_refs(monkeypatch, env, image_client_module)

    orig_execute = static_docu.execute
    touched_done_ids = []

    async def wrapped_execute(query, *args):
        if args and args[0] in ("done-side_profile", "done-top_planform"):
            touched_done_ids.append(args[0])
        return await orig_execute(query, *args)

    monkeypatch.setattr(static_docu, "execute", wrapped_execute)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert len(env["gen_refs"]) == 1, "only the missing three_quarter role should generate"
    assert env["gen_refs"] == [DONE_SIDE_PROFILE_URL], (
        "the missing three_quarter view must chain off side_profile — "
        "earlier in STATIC_VIEW_PLANS order than top_planform, even though "
        "both are already done"
    )
    assert touched_done_ids == [], "the two pre-existing done rows must never be written to"

    rows = _rows_by_role(env)
    assert "[input: anchor side_profile]" in rows["three_quarter"]["image_prompt"]


# ---------------------------------------------------------------------------
# (c) Identity QA still judges against the ORIGINAL hosted reference, never
#     the anchor, even though generation itself used the anchor as its
#     image input — the chain must never be able to drift identity.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_identity_qa_still_checks_original_reference_not_the_anchor(monkeypatch):
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
        _seed_done_roles_fetch_all({
            "side_profile": DONE_SIDE_PROFILE_URL,
            "top_planform": DONE_TOP_PLANFORM_URL,
        }),
    )
    _capture_gen_refs(monkeypatch, env, image_client_module)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert env["gen_refs"] == [DONE_SIDE_PROFILE_URL], (
        "sanity check: generation used the anchor, not the reference")
    assert env["qa_calls"] == [
        ("https://kie.example/three-quarter-fill.png", REF_HOSTED)
    ], (
        "_render_matches_reference must still be called with the ORIGINAL "
        "hosted reference (REF_HOSTED), never the anchor, even though "
        "generation chained off the anchor"
    )


# ---------------------------------------------------------------------------
# (d) No anchor available (every prior view this run parked): falls back to
#     the reference input, exactly like a scene with no anchor at all.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_anchor_available_falls_back_to_reference_input(monkeypatch):
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch,
        # view 1 (three_quarter): initial + retry both fail identity QA and
        # the arbiter (default False) -> parks, never becomes an anchor.
        # view 2 (side_profile): passes on the first try.
        verdicts=[False, False, True],
        gen_urls=[
            "https://kie.example/three-quarter-1.png",
            "https://kie.example/three-quarter-2.png",
            "https://kie.example/side-profile.png",
        ],
        isolate_single_view=False,
        docu_module=static_docu, image_client_module=image_client_module,
    )
    # Isolate to exactly two views so view 2 is unambiguously "the next view
    # after every prior view parked" (a 3rd view would instead chain off
    # view 2's own successful render, which is a DIFFERENT case).
    monkeypatch.setattr(
        static_docu, "STATIC_VIEW_PLANS", static_docu.STATIC_VIEW_PLANS[:2])
    _capture_gen_refs(monkeypatch, env, image_client_module)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    # Below STATIC_VIEWS_MINIMUM (three_quarter parked, only side_profile
    # done) — the scene fails overall, but that's orthogonal to this test.
    assert result["status"] == "failed"

    assert env["gen_refs"] == [REF_HOSTED, REF_HOSTED, REF_HOSTED], (
        "with no anchor ever established this run, every attempt — both of "
        "view 1's and view 2's — must fall back to the raw reference photo"
    )

    rows = _rows_by_role(env)
    assert rows["three_quarter"]["status"] == "qa_rejected"
    assert "[input: reference]" in rows["three_quarter"]["image_prompt"]
    assert rows["side_profile"]["status"] == "done"
    assert "[input: reference]" in rows["side_profile"]["image_prompt"]


# ---------------------------------------------------------------------------
# _studio_prompt(from_anchor=...) — unit-level wording checks, mirroring
# test_static_docu_view_rotation_fix.py's direct-call style.
# ---------------------------------------------------------------------------

def test_studio_prompt_default_still_describes_a_reference_photo():
    prompt = static_docu._studio_prompt(
        "Boeing XB-15", _PLANS["side_profile"], "wing structure")
    lowered = prompt.lower()
    assert "verified reference photo" in lowered
    assert "studio render" not in lowered


def test_studio_prompt_from_anchor_describes_a_studio_render_not_a_photo():
    prompt = static_docu._studio_prompt(
        "Boeing XB-15", _PLANS["side_profile"], "wing structure",
        from_anchor=True)
    lowered = prompt.lower()
    assert "verified clean studio render of the same machine" in lowered
    assert "verified reference photo" not in lowered
    # Camera-geometry-first structure and identity-fidelity language are
    # otherwise unchanged from the reference-photo prompt.
    assert prompt.startswith(_PLANS["side_profile"]["direction"])
    assert "identity" in lowered


def test_studio_prompt_emphasize_geometry_from_anchor_still_amplifies_camera(
):
    """The role-conformance retry's stronger wording works the same way for
    a chained (anchor) view as it does for a reference-photo view."""
    prompt = static_docu._studio_prompt(
        "Boeing XB-15", _PLANS["top_planform"], "wing structure",
        emphasize_geometry=True, from_anchor=True)
    assert "CAMERA ANGLE CORRECTION" in prompt
    assert _PLANS["top_planform"]["direction"] in prompt
    assert "verified clean studio render of the same machine" in prompt.lower()
