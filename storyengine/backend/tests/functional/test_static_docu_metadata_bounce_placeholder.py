"""Tests for the metadata-gate invisible-bounce fix (G26, live incident
2026-08-04: video d2e37cd6, scene 19 "Nairana class" / HMS Nairana & HMS
Vindex — failed the pictures stage twice with zero visibility into why).

Root cause: when `_one_scene`'s metadata gate ("operator/service years and
at least one sourced spec required") bounced a scene, it `return`ed BEFORE
`_insert_placeholder` ever ran for that scene — leaving it with ZERO asset
rows. Every count/review that reads the assets table (video_summary's
`pics`, the frontend readiness panel, this same function's own `_bounded`
timeout cleanup) treats zero rows identically to "never attempted yet", so
the bounced scene was invisible all night instead of reading as blocked.

Fix (static_docu.py `_one_scene`):
- On a metadata-gate bounce, insert ONE placeholder row via the SAME
  `_insert_placeholder` machinery every real view uses, with
  `status='blocked_missing_metadata'`, `image_url` NULL (the INSERT never
  sets it), and the bounce reason in `image_prompt` (e.g. "[metadata-bounce]
  planner produced no sourced spec for <machine>").
- That status can never be counted done/ready anywhere: `video_summary`
  counts `image_url IS NOT NULL`; `frame_arbiter` and the images-readiness
  check filter `status = 'done'`.
- A stale blocked placeholder is deleted (a) up front on every repeat
  bounce, so "exactly one" holds across N consecutive bounces, and (b)
  unconditionally the moment planning succeeds again, ahead of the FILL-
  vs-full-regenerate branch — because the full-regenerate DELETE further
  down only fires in ITS OWN branch and FILL mode never reaches it.
- `frontend/src/lib/static-docu.ts`'s `BLOCKED_VIEW_STATUSES` now includes
  this status, so the readiness panel shows the scene as "blocked" instead
  of "not_started".

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_metadata_bounce_placeholder.py -q
"""
import json
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Pre-import for the same reason every other static_docu test file does:
# anthropic's _base_client.py subclasses httpx.AsyncClient at MODULE IMPORT
# time, so it must finish loading before any test monkeypatches
# httpx.AsyncClient to a fake callable (via test_static_docu_qa_park's
# _pipeline_env, used below).
import shared.clients.image_client as image_client_mod  # noqa: E402

from test_static_docu_qa_park import _pipeline_env  # noqa: E402


def _install_live_assets_query(monkeypatch, env, docu_module=static_docu):
    """Make the existing-rows SELECT `_one_scene` runs before generating see
    whatever fake_execute has written into env['assets'] SO FAR — needed to
    prove a SECOND run of generate_static_images_for_video sees what the
    FIRST run left behind (a parked blocked_missing_metadata placeholder),
    the same way a real re-run against Postgres would."""
    base_fetch_all = docu_module.fetch_all

    async def fetch_all_live(query, *args):
        if "SELECT id, status, image_url, caption FROM assets" in query:
            return [
                {"id": rid, "status": row.get("status"),
                 "image_url": row.get("image_url"), "caption": row.get("caption")}
                for rid, row in env["assets"].items()
            ]
        return await base_fetch_all(query, *args)

    monkeypatch.setattr(docu_module, "fetch_all", fetch_all_live)


def _install_live_delete_simulation(monkeypatch, env, docu_module=static_docu):
    """test_static_docu_qa_park's fake `execute()` only simulates a single-id
    delete ('DELETE FROM assets WHERE id=...'); it has no branch for the
    scene-scoped deletes this fix adds (the blocked-row dedup delete before
    a fresh bounce placeholder, the post-gate stale-blocked cleanup, and the
    pre-existing full-regenerate delete) — those calls were previously only
    ever LOGGED (env['queries']), never actually applied to env['assets'].
    That's harmless for a single generate_static_images_for_video() call
    (nothing exists yet to delete), but a test that calls it TWICE needs
    these to actually remove rows, the way a real re-run against Postgres
    would. This fixture is always exactly one scene/video/tenant, so every
    row in env['assets'] already belongs to that one scope — filtering by
    the delete's own shape (status-scoped vs. blanket) is enough to model it
    faithfully here."""
    base_execute = docu_module.execute

    async def execute_live(query, *args):
        if query.startswith("DELETE FROM assets WHERE video_id=") and "status=$5" in query:
            status = args[-1]
            for rid, row in list(env["assets"].items()):
                if row.get("status") == status:
                    env["assets"].pop(rid, None)
            env["queries"].append(query)
            return None
        if (query.startswith("DELETE FROM assets WHERE video_id=")
                and "generation_method=$4" in query and "status" not in query):
            env["assets"].clear()  # full-regenerate: every row for this scene
            env["queries"].append(query)
            return None
        return await base_execute(query, *args)

    monkeypatch.setattr(docu_module, "execute", execute_live)


def _counts_as_ready(row: dict) -> bool:
    """Mirrors the ONE predicate every counting path actually uses
    (video_summary's `image_url IS NOT NULL`; frame_arbiter and the images
    readiness check's `status = 'done'`) — both are satisfied together only
    by a real shipped render."""
    return row.get("status") == "done" and row.get("image_url") is not None


class _EmptyCaptionClient:
    """Parses fine, but never supplies operator/years or a sourced spec —
    the "planner replied but the metadata just isn't there" bounce mode
    (`missing_title_metadata`)."""

    async def generate(self, **kwargs):
        return json.dumps([{
            "scene": 1, "machine": "Nairana class", "aliases": [],
            "caption_title": "Nairana class", "caption_sub": "",
            "caption_specs": [], "detail_focus": "overall machine geometry",
            "search_query": "Nairana class escort carrier",
        }])


class _UnparseableClient:
    """Never returns anything JSON-shaped, on either the first attempt or
    the one retry — the truncation/garbage-reply bounce mode
    (`subject_planning_unparseable`)."""

    async def generate(self, **kwargs):
        return "Sorry, I can't help with that — no JSON here."


class _WorkingClient:
    """A normal, fully-grounded reply — used to prove a LATER run replaces
    a stale blocked placeholder once planning actually succeeds."""

    async def generate(self, **kwargs):
        return json.dumps([{
            "scene": 1, "machine": "Nairana class", "aliases": [],
            "caption_title": "Nairana class", "caption_sub": "Royal Navy • 1942-1948",
            "caption_specs": ["2 ships converted"], "detail_focus": "flight deck and lift",
            "search_query": "Nairana class escort carrier",
        }])


def _install_client(monkeypatch, client):
    import kie_unified

    async def fake_get_text_client_for_tenant(tenant_id):
        return client

    monkeypatch.setattr(
        kie_unified, "get_text_client_for_tenant", fake_get_text_client_for_tenant)


# ---------------------------------------------------------------------------
# (b) Metadata bounce -> exactly one blocked_missing_metadata row with a
# reason, not counted ready.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_spec_bounce_inserts_one_blocked_row_with_reason(monkeypatch):
    env = _pipeline_env(monkeypatch, verdicts=[], gen_urls=[],
                        image_client_module=image_client_mod, docu_module=static_docu)
    _install_client(monkeypatch, _EmptyCaptionClient())

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "failed"
    assert len(env["assets"]) == 1, (
        f"expected exactly one placeholder row, got {env['assets']}")
    row = next(iter(env["assets"].values()))
    assert row["status"] == "blocked_missing_metadata"
    assert row["image_url"] is None
    assert "[metadata-bounce]" in row["image_prompt"]
    assert "Nairana class" in row["image_prompt"]
    assert not _counts_as_ready(row)
    # No paid image door was ever opened.
    assert env["gen_prompts"] == []
    assert not any(q.startswith("DELETE FROM assets WHERE id=") for q in env["queries"])


@pytest.mark.asyncio
async def test_unparseable_planning_bounce_inserts_one_blocked_row_with_reason(
    monkeypatch,
):
    env = _pipeline_env(monkeypatch, verdicts=[], gen_urls=[],
                        image_client_module=image_client_mod, docu_module=static_docu)
    _install_client(monkeypatch, _UnparseableClient())

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "failed"
    assert len(env["assets"]) == 1
    row = next(iter(env["assets"].values()))
    assert row["status"] == "blocked_missing_metadata"
    assert row["image_url"] is None
    assert "[metadata-bounce]" in row["image_prompt"]
    assert "unparseable" in row["image_prompt"] or "could not be parsed" in row["image_prompt"]
    assert not _counts_as_ready(row)
    assert env["gen_prompts"] == []


@pytest.mark.asyncio
async def test_repeated_bounce_never_accumulates_duplicate_blocked_rows(monkeypatch):
    """An operator re-running pictures on a scene whose planner STILL fails
    must never end up with two blocked rows for the same scene."""
    env = _pipeline_env(monkeypatch, verdicts=[], gen_urls=[],
                        image_client_module=image_client_mod, docu_module=static_docu)
    _install_client(monkeypatch, _EmptyCaptionClient())
    _install_live_assets_query(monkeypatch, env)
    _install_live_delete_simulation(monkeypatch, env)

    result1 = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])
    assert result1["status"] == "failed"
    assert len(env["assets"]) == 1
    first_row_id = next(iter(env["assets"].keys()))

    result2 = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])
    assert result2["status"] == "failed"
    assert len(env["assets"]) == 1, (
        f"a second bounce must replace, not duplicate, the blocked row: "
        f"{env['assets']}")
    row = next(iter(env["assets"].values()))
    assert row["status"] == "blocked_missing_metadata"
    # A fresh row was written for the second attempt — the first attempt's
    # row id is gone, not merely overwritten in place.
    assert first_row_id not in env["assets"]


# ---------------------------------------------------------------------------
# Replaced on a later successful run: the full-regenerate path (0 done roles
# when the bounce happened, single-view-isolated here). The SEPARATE FILL-
# mode case (a stray blocked row surviving alongside enough already-done
# roles that a later run takes the FILL branch instead, which never reaches
# the blanket full-regenerate DELETE) is covered by the dedicated test
# below, since it needs the real 3-role view contract to be reachable at all.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_rerun_replaces_blocked_placeholder(monkeypatch):
    env = _pipeline_env(monkeypatch, verdicts=[], gen_urls=[],
                        image_client_module=image_client_mod, docu_module=static_docu)
    _install_client(monkeypatch, _EmptyCaptionClient())
    _install_live_assets_query(monkeypatch, env)
    _install_live_delete_simulation(monkeypatch, env)

    result1 = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])
    assert result1["status"] == "failed"
    assert len(env["assets"]) == 1
    blocked_row = next(iter(env["assets"].values()))
    assert blocked_row["status"] == "blocked_missing_metadata"

    # Planning now succeeds (e.g. the research card was filled in since).
    # _pipeline_env's generate/QA fakes captured their verdict/url queues by
    # closure at setup time (both empty, since run 1 never reached them) —
    # install fresh ones for run 2 rather than trying to feed the exhausted
    # originals.
    _install_client(monkeypatch, _WorkingClient())

    async def fake_generate(self, prompt, ref_url, aspect_ratio="16:9",
                            allow_fallback=False, resolution="1K"):
        env["gen_prompts"].append(prompt)
        return {"url": "https://kie.example/render_success.png"}

    async def fake_render_matches(tid, render_url, ref_url, machine, aliases=None,
                                  *, reason_out=None):
        if reason_out is not None:
            reason_out.append("yes, same aircraft type")
        return True

    monkeypatch.setattr(
        image_client_mod.ImageClient, "generate_scene_image_gpt", fake_generate)
    monkeypatch.setattr(static_docu, "_render_matches_reference", fake_render_matches)

    result2 = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result2["status"] == "completed"
    assert len(env["assets"]) == 1, (
        f"the stale blocked placeholder must be replaced, not kept alongside "
        f"the new done row: {env['assets']}")
    row = next(iter(env["assets"].values()))
    assert row["status"] == "done"
    assert row["image_url"] is not None
    assert _counts_as_ready(row)


@pytest.mark.asyncio
async def test_fill_mode_rerun_clears_stale_blocked_row_via_delete_query(monkeypatch):
    """FILL mode (>= STATIC_VIEWS_MINIMUM done roles from a prior run) never
    reaches the full-regenerate blanket DELETE below it — so without the
    dedicated unconditional cleanup this fix adds right after the metadata
    gate passes, a stale blocked_missing_metadata row left by an earlier
    PARTIAL bounce (2 of 3 roles already done, the 3rd role's attempt is
    what bounced) would survive forever even once planning starts
    succeeding again. Uses the real 3-role STATIC_VIEW_PLANS (not the
    single-view isolation default) so this FILL state is reachable at all."""
    role_plans = list(static_docu.STATIC_VIEW_PLANS)
    done_roles = [p["role"] for p in role_plans[:2]]
    missing_role_plan = role_plans[2]

    existing_rows = [
        {"id": f"done-{i}", "status": "done",
         "image_url": f"https://done{i}.example/x.png",
         "caption": json.dumps({"view_role": role})}
        for i, role in enumerate(done_roles)
    ] + [
        {"id": "stale-blocked", "status": "blocked_missing_metadata", "image_url": None,
         "caption": json.dumps({"view_role": "blocked_missing_metadata"})},
    ]

    env = _pipeline_env(
        monkeypatch, verdicts=[True], gen_urls=["https://kie.example/fill_render.png"],
        image_client_module=image_client_mod, docu_module=static_docu,
        isolate_single_view=False,
        existing_asset_rows=existing_rows,
    )
    _install_client(monkeypatch, _WorkingClient())

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    # Exactly ONE new generation — the two done roles stayed untouched (FILL
    # mode), and it targeted the one role that was actually still missing.
    assert len(env["gen_prompts"]) == 1
    assert env["role_qa_calls"] == [
        ("https://kie.example/fill_render.png", missing_role_plan["role"])
    ]

    cleanup_deletes = [
        q for q in env["queries"]
        if q.startswith("DELETE FROM assets WHERE video_id=") and "status=$5" in q
    ]
    assert cleanup_deletes, (
        "FILL mode must still clear a stale blocked_missing_metadata row once "
        "planning succeeds again, not only the full-regenerate branch")


# ---------------------------------------------------------------------------
# Regression: the ordinary happy path (planner supplies everything on the
# first call) is completely unaffected — no blocked row ever appears.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ordinary_scene_with_full_metadata_never_gets_a_blocked_row(monkeypatch):
    env = _pipeline_env(monkeypatch, verdicts=[True],
                        gen_urls=["https://kie.example/render1.png"],
                        image_client_module=image_client_mod, docu_module=static_docu)
    # _pipeline_env's own default text client already returns full metadata
    # (see test_static_docu_qa_park._pipeline_env's _FakeTextClient) — no
    # override needed.

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    assert len(env["assets"]) == 1
    row = next(iter(env["assets"].values()))
    assert row["status"] == "done"
    assert row["status"] != "blocked_missing_metadata"


# ---------------------------------------------------------------------------
# Frontend readiness contract: BLOCKED_VIEW_STATUSES enumerates the new
# status, so the readiness panel reads "blocked" instead of "not_started".
# ---------------------------------------------------------------------------

def test_frontend_blocked_view_statuses_includes_metadata_bounce():
    src_path = os.path.join(
        os.path.abspath(_BACKEND), "..", "frontend", "src", "lib", "static-docu.ts")
    with open(src_path) as f:
        src = f.read()
    assert '"blocked_missing_metadata"' in src, (
        "BLOCKED_VIEW_STATUSES must include blocked_missing_metadata or the "
        "readiness panel shows a bounced scene as not_started, indistinguishable "
        "from never having been touched")
