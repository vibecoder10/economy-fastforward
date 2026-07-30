"""D7-3 — a manual scene edit must invalidate the same things a Drive-pulled
edit always has: voice, images/clips, AND (new) the scene's stored board
plan.

THE GAP: `_clear_scene_downstream` (routes/videos.py) has always nulled a
scene's voice_over_url/voice_status/voice_duration_seconds and its assets'
image_url/drive_image_url/video_url/video_clip_url/video_duration — but only
the Drive pull-sync path (`sync_script_from_drive`) ever called it.
`update_scene_text` (the plain PATCH .../scenes/{scene}/text edit) called it
NEVER. `rewrite_scene_text` (the AI single-scene rewrite) nulled voice
inline but never touched images/clips. Either way, an edited scene's stored
`coverage_directive` (its board plan) kept passing the coverage gate's
hash check (scripts/coverage_to_app.py:4404-4452 — reuse the saved directive
only while `coverage_directive_hash` matches the CURRENT scene text) purely
by accident of the hash naturally going stale — nothing forced it, and the
scene's already-drawn board images/clips were never marked stale at all.

Fix (routes/videos.py):
  1. `_clear_scene_downstream` also nulls `coverage_directive_hash` (never
     `coverage_directive` itself — the text stays, just the pointer that
     gates its reuse) — same flag/clear-never-delete contract as
     `_flag_stale_cast_and_environments`.
  2. Both `update_scene_text` and `rewrite_scene_text` now call it, wrapped
     in the same advisory try/except every other post-write check in these
     two endpoints already uses — a failure here must never fail the save.

Local/no-spend: fakes execute/fetch_all (and, for rewrite, fetch_one/
get_secret/httpx) against a tiny in-memory scripts+assets table, same
query-text-dispatch pattern tests/functional/test_d7_2_staleness_hash.py and
tests/test_d7_1_script_sync.py already use for these same two endpoints.

STASH-PROOF: with `coverage_directive_hash = NULL` reverted out of
`_clear_scene_downstream`'s UPDATE (or the two new `_clear_scene_downstream`
call sites removed from update_scene_text/rewrite_scene_text),
test_update_scene_text_clears_only_the_edited_scenes_hash_and_media and
test_rewrite_scene_text_clears_only_the_edited_scenes_hash_and_media fail
real assertions (the edited scene's coverage_directive_hash/image_url/
video_url stay at their OLD values instead of going to None) — not
import/collection-time errors.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d7_3_scene_edit_invalidation.py -q
"""
import asyncio

import routes.videos as rv
from models import SceneTextUpdate

OLD_TEXT = "The old paragraph about a lighthouse keeper."
NEW_TEXT = "A submarine captain named Vasquez discovers the reactor is failing."


def _scene_row(text, *, hash_="hash-old-scene"):
    return {
        "scene_text": text,
        "location": "the garage",
        "voice_over_url": "https://old.example/voice.mp3",
        "voice_status": "done",
        "voice_duration_seconds": 12.5,
        "coverage_directive_hash": hash_,
    }


def _asset_row():
    return {
        "image_url": "https://old.example/image.png",
        "drive_image_url": "https://drive.example/image.png",
        "video_url": "https://old.example/clip.mp4",
        "video_clip_url": "https://old.example/clip-alt.mp4",
        "video_duration": 4.2,
    }


def _make_fake_db(scene_texts: dict):
    """scripts + assets, two independent scenes by default, so a test can
    prove invalidation is SCOPED to the edited scene only."""
    state = {
        "scripts": {n: _scene_row(t) for n, t in scene_texts.items()},
        "assets": {n: _asset_row() for n in scene_texts},
        "videos_script": " ".join(scene_texts.values()),
    }
    calls = []  # every execute() call: (query, args)

    async def fake_execute(query, *args):
        calls.append((query, args))
        q = query.strip()
        if q.startswith("UPDATE scripts SET scene_text = $4"):
            # rewrite_scene_text's OWN write: (video_id, tenant_id, scene,
            # new_text, new_location) — nulls voice inline, same as today.
            _video_id, _tenant_id, scene, new_text, _new_location = args
            row = state["scripts"].get(scene)
            if row is not None:
                row["scene_text"] = new_text
                row["voice_over_url"] = None
                row["voice_duration_seconds"] = None
                row["voice_status"] = None
            return "UPDATE 1"
        if q.startswith("UPDATE scripts SET scene_text"):
            # update_scene_text's write: (stored_text, video_id, scene,
            # tenant_id, new_location)
            stored_text, _video_id, scene, _tenant_id, new_location = args
            row = state["scripts"].get(scene)
            if row is None:
                return "UPDATE 0"
            row["scene_text"] = stored_text
            if new_location is not None:
                row["location"] = new_location
            return "UPDATE 1"
        if q.startswith("UPDATE scripts SET voice_over_url = NULL"):
            # D7-3: _clear_scene_downstream's scripts clear. Only actually
            # null coverage_directive_hash if the REAL SQL text names that
            # column — a fake that always cleared it regardless of the SQL
            # would pass even against the pre-D7-3 3-field clear, defeating
            # the whole point of the drive-sync proof below.
            _video_id, scene, _tenant_id = args
            row = state["scripts"].get(scene)
            if row is not None:
                row["voice_over_url"] = None
                row["voice_status"] = None
                row["voice_duration_seconds"] = None
                if "coverage_directive_hash" in q:
                    row["coverage_directive_hash"] = None
            return "UPDATE 1"
        if q.startswith("UPDATE assets SET image_url = NULL"):
            # D7-3: _clear_scene_downstream's assets clear.
            _video_id, scene, _tenant_id = args
            row = state["assets"].get(scene)
            if row is not None:
                row["image_url"] = None
                row["drive_image_url"] = None
                row["video_url"] = None
                row["video_clip_url"] = None
                row["video_duration"] = None
            return "UPDATE 1"
        if q.startswith("UPDATE videos SET script"):
            *_rest, full_text = args
            state["videos_script"] = full_text
            return "UPDATE 1"
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        return [
            {"scene": n, "location": row["location"], "scene_text": row["scene_text"]}
            for n, row in state["scripts"].items()
        ]

    return state, calls, fake_execute, fake_fetch_all


# ---------------------------------------------------------------------------
# 1. update_scene_text — clears the edited scene's hash + media, ONLY that scene
# ---------------------------------------------------------------------------

def test_update_scene_text_clears_only_the_edited_scenes_hash_and_media(monkeypatch):
    state, calls, fake_execute, fake_fetch_all = _make_fake_db({1: OLD_TEXT, 2: "Scene two, untouched."})
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    result = asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text=NEW_TEXT), tenant_id="tenant-1",
    ))

    assert result["status"] == "updated"

    edited = state["scripts"][1]
    assert edited["scene_text"] == NEW_TEXT
    assert edited["coverage_directive_hash"] is None, (
        "an edited scene's stored board plan is stale by definition — its "
        "directive hash must be cleared so the coverage gate re-plans it"
    )
    assert edited["voice_over_url"] is None
    assert edited["voice_status"] is None
    assert edited["voice_duration_seconds"] is None
    edited_asset = state["assets"][1]
    assert edited_asset["image_url"] is None
    assert edited_asset["drive_image_url"] is None
    assert edited_asset["video_url"] is None
    assert edited_asset["video_clip_url"] is None
    assert edited_asset["video_duration"] is None

    # Scoped: scene 2 was never touched — a scoped re-plan must not force a
    # full-video replan (that would re-bill every OTHER scene's paid planner
    # call for no reason).
    untouched = state["scripts"][2]
    assert untouched["coverage_directive_hash"] == "hash-old-scene"
    assert untouched["voice_over_url"] == "https://old.example/voice.mp3"
    untouched_asset = state["assets"][2]
    assert untouched_asset["image_url"] == "https://old.example/image.png"
    assert untouched_asset["video_url"] == "https://old.example/clip.mp4"

    # No DELETEs anywhere — flag/clear pointers, never delete a paid artifact.
    assert not any(q.strip().upper().startswith("DELETE") for q, _ in calls)


def test_update_scene_text_invalidation_failure_never_fails_the_edit(monkeypatch):
    """The advisory-wrapper contract: if _clear_scene_downstream blows up
    (DB hiccup, whatever), the scene_text save must still succeed."""
    state, calls, fake_execute_base, fake_fetch_all = _make_fake_db({1: OLD_TEXT})

    async def flaky_execute(query, *args):
        q = query.strip()
        if q.startswith("UPDATE scripts SET voice_over_url = NULL"):
            raise RuntimeError("simulated DB failure inside D7-3 invalidation")
        return await fake_execute_base(query, *args)

    monkeypatch.setattr(rv, "execute", flaky_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    result = asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text=NEW_TEXT), tenant_id="tenant-1",
    ))

    assert result["status"] == "updated", (
        "a failure inside the D7-3 invalidation call must never surface as "
        "a failed scene-text save"
    )
    assert state["scripts"][1]["scene_text"] == NEW_TEXT, (
        "the scene_text write itself must have gone through untouched by "
        "the downstream invalidation blowing up"
    )


# ---------------------------------------------------------------------------
# 2. rewrite_scene_text — same scoped clear, now also covering images/clips
#    (which rewrite never touched before D7-3)
# ---------------------------------------------------------------------------

def _wire_rewrite_fakes(monkeypatch, state, fake_execute, fake_fetch_all, rewritten_text):
    async def fake_fetch_one(query, *args):
        if "video_title, render_mode, research_payload FROM videos" in query:
            return {"id": "video-1", "video_title": "T", "render_mode": None, "research_payload": None}
        if "scene_text FROM scripts WHERE video_id" in query and "AND scene = " in query:
            return {"scene_text": OLD_TEXT}
        if "prompt_text FROM tenant_prompt_defaults" in query:
            return None
        return None

    async def fake_get_secret(name, tenant_id=None):
        return "fake-anthropic-key"

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"content": [{"text": rewritten_text}]}

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _FakeResp()

    import httpx as real_httpx
    import vault as vault_mod

    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(vault_mod, "get_secret", fake_get_secret)
    monkeypatch.setattr(real_httpx, "AsyncClient", _FakeAsyncClient)


def test_rewrite_scene_text_clears_only_the_edited_scenes_hash_and_media(monkeypatch):
    rewritten = (
        "A submarine captain named Vasquez discovers the reactor is failing "
        "and orders the crew to seal every compartment before the pressure "
        "hull gives way under the rising strain of the flooding corridor. "
        "She counts every second against the depth gauge, knowing the whole "
        "boat depends on a decision made in the next few breaths alone."
    )  # >= 40 spoken words — rewrite_scene_text rejects a shorter result

    state, calls, fake_execute, fake_fetch_all = _make_fake_db({1: OLD_TEXT, 2: "Scene two, untouched."})
    _wire_rewrite_fakes(monkeypatch, state, fake_execute, fake_fetch_all, rewritten)

    result = asyncio.run(rv.rewrite_scene_text("video-1", 1, tenant_id="tenant-1"))

    assert result["text"] == rewritten

    edited = state["scripts"][1]
    assert edited["scene_text"] == rewritten
    assert edited["coverage_directive_hash"] is None, (
        "a rewrite invalidates the stored board plan same as a manual edit"
    )
    assert edited["voice_over_url"] is None
    edited_asset = state["assets"][1]
    assert edited_asset["image_url"] is None, (
        "before D7-3, rewrite_scene_text nulled voice but never images/clips "
        "— a rewritten scene kept showing storyboard frames drawn from the "
        "pre-rewrite paragraph"
    )
    assert edited_asset["video_url"] is None

    untouched = state["scripts"][2]
    assert untouched["coverage_directive_hash"] == "hash-old-scene"
    untouched_asset = state["assets"][2]
    assert untouched_asset["image_url"] == "https://old.example/image.png"

    assert not any(q.strip().upper().startswith("DELETE") for q, _ in calls)


def test_rewrite_scene_text_invalidation_failure_never_fails_the_rewrite(monkeypatch):
    rewritten = (
        "A submarine captain named Vasquez discovers the reactor is failing "
        "and orders the crew to seal every compartment before the pressure "
        "hull gives way under the rising strain of the flooding corridor. "
        "She counts every second against the depth gauge, knowing the whole "
        "boat depends on a decision made in the next few breaths alone."
    )

    state, calls, fake_execute_base, fake_fetch_all = _make_fake_db({1: OLD_TEXT})

    async def flaky_execute(query, *args):
        q = query.strip()
        if q.startswith("UPDATE assets SET image_url = NULL"):
            raise RuntimeError("simulated DB failure inside D7-3 invalidation")
        return await fake_execute_base(query, *args)

    _wire_rewrite_fakes(monkeypatch, state, flaky_execute, fake_fetch_all, rewritten)

    result = asyncio.run(rv.rewrite_scene_text("video-1", 1, tenant_id="tenant-1"))

    assert result["text"] == rewritten, (
        "a failure inside the D7-3 invalidation call must never surface as "
        "a failed rewrite"
    )
    assert state["scripts"][1]["scene_text"] == rewritten


# ---------------------------------------------------------------------------
# 3. Drive pull-sync path — unaffected in shape, but now gets the hash clear
#    for free through the SAME _clear_scene_downstream it always called.
# ---------------------------------------------------------------------------

def test_drive_sync_also_clears_coverage_directive_hash_for_free(monkeypatch):
    """The chunk's whole point: extend _clear_scene_downstream, don't fork
    it. Prove the Drive pull-sync path (which has always called it) now
    clears coverage_directive_hash too, with ZERO changes to that path's own
    code — the extension alone is what does it."""
    state, calls, fake_execute_base, _fake_fetch_all = _make_fake_db({1: OLD_TEXT})

    async def fake_fetch_one(query, *args):
        if "drive_script_doc_id, drive_script_synced_at" in query:
            return {"id": "video-1", "drive_script_doc_id": "doc-1",
                    "drive_script_synced_at": None, "drive_script_doc_modified_at": None}
        if "google_drive_refresh_token FROM channel_profiles" in query:
            return {"google_drive_refresh_token": "fake-refresh-token"}
        return None

    async def fake_fetch_all(query, *args):
        q = query.strip()
        if q.startswith("SELECT id, scene, scene_text FROM scripts"):
            return [{"id": "row-1", "scene": 1, "scene_text": OLD_TEXT}]
        if q.startswith("SELECT scene_text FROM scripts"):
            return [{"scene_text": NEW_TEXT}]
        return []

    async def fake_execute(query, *args):
        q = query.strip()
        if q.startswith("UPDATE scripts SET scene_text = $1"):
            calls.append((query, args))
            return "UPDATE 1"
        if q.startswith("UPDATE videos SET script = $1, updated_at"):
            calls.append((query, args))
            state["videos_script"] = args[0]
            return "UPDATE 1"
        return await fake_execute_base(query, *args)

    async def fake_to_thread(fn, *a, **kw):
        return "2026-01-01T00:00:00Z", "unused — _parse_script_doc is mocked"

    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rv, "_parse_script_doc", lambda text: {1: NEW_TEXT})
    monkeypatch.setattr(rv.asyncio, "to_thread", fake_to_thread)

    result = asyncio.run(rv.sync_script_from_drive("video-1", force=True, tenant_id="tenant-1"))

    assert result["changed"] is True
    assert state["scripts"][1]["coverage_directive_hash"] is None
    assert state["scripts"][1]["voice_over_url"] is None
    assert state["assets"][1]["image_url"] is None
