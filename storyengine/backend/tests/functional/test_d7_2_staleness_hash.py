"""D7-2 — generalise the staleness hash (STORY-LAWS S6: a real production
video rendered characters from a script that did not yet contain them).

Adds characters_hash / environments_hash on `videos` (migration 145): the
hash of the videos.script text design_characters / run_environments_design_step
actually generated the CURRENT cast/environments from. Every script write
recomputes the CURRENT hash and compares — on a mismatch it flags
video_characters.status / video_environments.status = 'stale' for every row
of that video. FLAG, NEVER DELETE — a wrong deletion costs a real-money
redraw.

Since D7-1/D7-1b, every scene-text writer funnels through ONE choke point,
routes/videos.py's sync_video_script — this is where
_flag_stale_cast_and_environments is hooked, so update_scene_text,
rewrite_scene_text and chat.py's _apply_prompt_draft all get it for free.
Three more paths write videos.script directly (not through
sync_video_script) and each gets its own explicit call: the Drive pull-sync
(routes/videos.py sync_script_from_drive), pipeline_executor's
_save_machine_script_block (the machine-documentary script hold), and
custom_film_production_runner's _script (Custom Film's own section-script
persistence).

Local/no-spend: every DB call is a fake execute/fetch_all/fetch_one
dispatched by query text, same pattern tests/test_d7_1_script_sync.py and
tests/test_d7_1b_chat_script_sync.py already use for the same
sync_video_script chain. Claude/httpx/provider calls are stubbed.

STASH-PROOF: with routes/videos.py's _flag_stale_cast_and_environments call
removed from sync_video_script (or the function itself neutered to a no-op),
test_update_scene_text_flips_both_statuses_to_stale and
test_apply_prompt_draft_flips_both_statuses_to_stale fail real assertions
(status stays 'approved' instead of flipping to 'stale') — not
import/collection-time errors.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d7_2_staleness_hash.py -q
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

VIDEO_PIPELINE = Path(__file__).parents[4] / "skills" / "video-pipeline"
if str(VIDEO_PIPELINE) not in sys.path:
    sys.path.insert(0, str(VIDEO_PIPELINE))

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import routes.videos as rv  # noqa: E402
import routes.chat as chat_route  # noqa: E402
import routes.characters as characters_route  # noqa: E402
import routes.environments as environments_route  # noqa: E402
import pipeline_executor as pe  # noqa: E402
from models import SceneTextUpdate  # noqa: E402

OLD_TEXT = "The old paragraph about a lighthouse keeper."
NEW_TEXT = "A submarine captain named Vasquez discovers the reactor is failing."


def _hash(text: str) -> str:
    return hashlib.sha1(" ".join((text or "").split()).encode()).hexdigest()


def _no_deletes(calls) -> bool:
    return not any(q.strip().upper().startswith("DELETE") for q, _ in calls)


# ---------------------------------------------------------------------------
# Shared fake DB for the routes.videos-level tests: tracks videos.script,
# characters_hash/environments_hash and video_characters/video_environments
# status, same query-text dispatch style as test_d7_1_script_sync.py.
# ---------------------------------------------------------------------------

def _make_fake_db(initial_scene_text: str, initial_videos_script: str, *,
                   characters_hash=None, environments_hash=None):
    state = {
        "scripts": {1: {"scene": 1, "location": "the garage", "scene_text": initial_scene_text}},
        "videos_script": initial_videos_script,
        "characters_hash": characters_hash,
        "environments_hash": environments_hash,
        "video_characters_status": "approved",
        "video_environments_status": "approved",
    }
    calls = []  # every execute() call: (query, args)

    async def fake_execute(query, *args):
        calls.append((query, args))
        q = query.strip()
        if q.startswith("UPDATE scripts SET scene_text"):
            if "COALESCE" in q:
                stored_text, _video_id, scene, _tenant_id, _new_location = args
            else:
                stored_text, _video_id, scene, _tenant_id = args
            row = state["scripts"].get(scene)
            if row is None:
                return "UPDATE 0"
            row["scene_text"] = stored_text
            return "UPDATE 1"
        if q.startswith("UPDATE videos SET script"):
            *_rest, full_text = args
            state["videos_script"] = full_text
            return "UPDATE 1"
        if q.startswith("UPDATE video_characters SET status = 'stale'"):
            state["video_characters_status"] = "stale"
            return "UPDATE 1"
        if q.startswith("UPDATE video_environments SET status = 'stale'"):
            state["video_environments_status"] = "stale"
            return "UPDATE 1"
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        return [dict(r) for r in state["scripts"].values()]

    async def fake_fetch_one(query, *args):
        if "characters_hash, environments_hash FROM videos" in query:
            return {
                "script": state["videos_script"],
                "characters_hash": state["characters_hash"],
                "environments_hash": state["environments_hash"],
            }
        return None

    return state, calls, fake_execute, fake_fetch_all, fake_fetch_one


# ---------------------------------------------------------------------------
# 1. _flag_stale_cast_and_environments — the compare-and-flag core
# ---------------------------------------------------------------------------

def test_flag_stale_flips_both_families_on_mismatch_and_never_deletes(monkeypatch):
    state, calls, fake_execute, _fake_fetch_all, fake_fetch_one = _make_fake_db(
        OLD_TEXT, NEW_TEXT,  # videos.script is NOW the new text
        characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),  # stamped from the OLD text
    )
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)

    asyncio.run(rv._flag_stale_cast_and_environments("video-1", "tenant-1"))

    assert state["video_characters_status"] == "stale"
    assert state["video_environments_status"] == "stale"
    assert _no_deletes(calls), "flagging staleness must never delete video_characters/video_environments rows"


def test_flag_stale_no_op_when_hash_matches(monkeypatch):
    """The script hasn't actually changed (hash matches) — leave both alone."""
    state, calls, fake_execute, _fake_fetch_all, fake_fetch_one = _make_fake_db(
        OLD_TEXT, NEW_TEXT, characters_hash=_hash(NEW_TEXT), environments_hash=_hash(NEW_TEXT),
    )
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)

    asyncio.run(rv._flag_stale_cast_and_environments("video-1", "tenant-1"))

    assert state["video_characters_status"] == "approved"
    assert state["video_environments_status"] == "approved"
    assert not [q for q, _ in calls if "status = 'stale'" in q]


def test_flag_stale_no_op_when_nothing_generated_yet(monkeypatch):
    """characters_hash/environments_hash are NULL — nothing was ever
    generated (or generated before migration 145), so nothing to compare."""
    state, calls, fake_execute, _fake_fetch_all, fake_fetch_one = _make_fake_db(
        OLD_TEXT, NEW_TEXT, characters_hash=None, environments_hash=None,
    )
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)

    asyncio.run(rv._flag_stale_cast_and_environments("video-1", "tenant-1"))

    assert state["video_characters_status"] == "approved"
    assert state["video_environments_status"] == "approved"


def test_regeneration_heals_the_stale_flag(monkeypatch):
    """The round trip the chunk requires: an edit stales both families, then
    regenerating re-stamps the hash from the (now current) script and the
    family stops being flagged — a legitimate clear, not a bug."""
    state, calls, fake_execute, _fake_fetch_all, fake_fetch_one = _make_fake_db(
        OLD_TEXT, NEW_TEXT, characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),
    )
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)

    # Step 1: script changed underneath the old stamp -> both go stale.
    asyncio.run(rv._flag_stale_cast_and_environments("video-1", "tenant-1"))
    assert state["video_characters_status"] == "stale"
    assert state["video_environments_status"] == "stale"

    # Step 2: regeneration re-stamps the hash from the CURRENT script and
    # (as the real generation code does) resets each row back to 'draft'.
    state["characters_hash"] = _hash(state["videos_script"])
    state["environments_hash"] = _hash(state["videos_script"])
    state["video_characters_status"] = "draft"
    state["video_environments_status"] = "draft"

    # Step 3: some OTHER unrelated script-write path runs the same check
    # again (e.g. a no-op re-sync) — it must NOT re-flag a family whose
    # stamp now matches.
    asyncio.run(rv._flag_stale_cast_and_environments("video-1", "tenant-1"))
    assert state["video_characters_status"] == "draft"
    assert state["video_environments_status"] == "draft"
    assert _no_deletes(calls)


# ---------------------------------------------------------------------------
# 2. Stamp — design_characters / run_environments_design_step
# ---------------------------------------------------------------------------

def test_design_characters_stamps_characters_hash_from_current_script(monkeypatch):
    script_text = "Rex the red robot squares off against Nia the blue robot."
    video = {
        "id": "video-1", "video_title": "T", "script": script_text,
        "image_style_override": "", "original_dna": None, "story_bible": None,
        "characters_approved_at": None, "project_id": None,
        "total_cost": 0.0, "max_spend": None,
    }

    async def fake_get_video(video_id, tenant_id):
        return video

    async def fake_get_secret(name, tenant_id=None):
        return "fake-kie-key"

    async def fake_is_task_active(*a, **kw):
        return False

    async def fake_extract_cast(video_arg, api_key):
        return [{"name": "Rex", "description": "a red robot"}]

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    async def fake_fetch_one(query, *args):
        if "INSERT INTO video_characters" in query:
            return {"id": "char-1"}
        return None

    async def fake_generate_portrait(api_key, description, style_dna, name=""):
        return {"url": "https://kie.example/tmp.png", "model": "gpt-image-2", "task_id": None}

    async def fake_persist(tenant_id, video_id, char_id, temp_url):
        return "https://storage.example/permanent.png"

    async def fake_record_ledger_entry(**kwargs):
        pass

    import vault as vault_mod
    import routes.pipeline as pipeline_mod
    import actions

    async def fake_video_summary(tenant_id, video_id):
        return None  # no cap set -> _budget_refusal always returns None (never refused)

    monkeypatch.setattr(actions, "video_summary", fake_video_summary)
    monkeypatch.setattr(characters_route, "_get_video", fake_get_video)
    monkeypatch.setattr(vault_mod, "get_secret", fake_get_secret)
    monkeypatch.setattr(pipeline_mod, "_is_task_active", fake_is_task_active)
    monkeypatch.setattr(pipeline_mod, "_set_task_status", lambda *a, **kw: None)
    monkeypatch.setattr(pipeline_mod, "_clear_task_status", lambda *a, **kw: None)
    monkeypatch.setattr(pipeline_mod, "_lane_begin", lambda *a, **kw: None)
    monkeypatch.setattr(pipeline_mod, "_lane_finish", lambda *a, **kw: None)
    _real_sleep = asyncio.sleep  # captured BEFORE patching — asyncio is one shared
    monkeypatch.setattr(                                  # module object, so patching it
        characters_route.asyncio, "sleep",                # and then calling asyncio.sleep
        lambda *a, **kw: _real_sleep(0),                   # inside the replacement recurses
    )
    monkeypatch.setattr(characters_route, "_extract_cast", fake_extract_cast)
    monkeypatch.setattr(characters_route, "execute", fake_execute)
    monkeypatch.setattr(characters_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(characters_route, "_generate_portrait", fake_generate_portrait)
    monkeypatch.setattr(characters_route, "_persist_portrait_url", fake_persist)
    monkeypatch.setattr(characters_route, "record_ledger_entry", fake_record_ledger_entry)

    class _FakeBackgroundTasks:
        def __init__(self):
            self.tasks = []

        def add_task(self, fn, *a, **kw):
            self.tasks.append((fn, a, kw))

    bg = _FakeBackgroundTasks()
    resp = asyncio.run(characters_route.design_characters("video-1", bg, tenant_id="tenant-1"))
    assert resp["status"] == "running"
    asyncio.run(bg.tasks[0][0]())

    stamp_calls = [
        (q, a) for q, a in calls
        if q.strip().startswith("UPDATE videos SET characters_approved_at = NULL, characters_hash")
    ]
    assert len(stamp_calls) == 1, "design_characters must stamp characters_hash exactly once per run"
    stamped_hash = stamp_calls[0][1][2]
    assert stamped_hash == _hash(script_text), (
        "the stamped hash must be the hash of the script _extract_cast actually read"
    )


def test_run_environments_design_step_stamps_environments_hash_from_current_script(monkeypatch):
    script_text = "A kitchen and a garage — two distinct locations shown on screen."
    video = {
        "id": "video-1", "script": script_text, "image_style_override": "",
        "aspect_ratio": "16:9", "story_bible": None,
    }

    async def fake_get_secret(name, tenant_id=None):
        return "fake-kie-key"

    def fake_extract_environments(video_arg):
        return []  # force the script-fallback branch, same as _extract_cast's

    async def fake_extract_locations(video_arg, api_key):
        return [{"name": "Kitchen", "description": "a bright kitchen"},
                {"name": "Garage", "description": "a cluttered garage"}]

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    async def fake_fetch_one(query, *args):
        if "INSERT INTO video_environments" in query:
            return {"id": "env-1"}
        return None

    async def fake_generate_environment(api_key, description, style_dna, aspect_ratio="16:9"):
        return {"url": "https://kie.example/tmp.png", "model": "gpt-image-2", "task_id": None}

    async def fake_persist(tenant_id, video_id, env_id, temp_url):
        return "https://storage.example/permanent.png"

    async def fake_record_ledger_entry(**kwargs):
        pass

    import vault as vault_mod
    import actions

    async def fake_video_summary(tenant_id, video_id):
        return None

    monkeypatch.setattr(actions, "video_summary", fake_video_summary)
    monkeypatch.setattr(vault_mod, "get_secret", fake_get_secret)
    monkeypatch.setattr(environments_route, "_extract_environments", fake_extract_environments)
    monkeypatch.setattr(environments_route, "_extract_locations_from_script", fake_extract_locations)
    monkeypatch.setattr(environments_route, "execute", fake_execute)
    monkeypatch.setattr(environments_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(environments_route, "_generate_environment", fake_generate_environment)
    monkeypatch.setattr(environments_route, "_persist_portrait_url", fake_persist)
    monkeypatch.setattr(environments_route, "record_ledger_entry", fake_record_ledger_entry)

    result = asyncio.run(environments_route.run_environments_design_step(video, "tenant-1"))
    assert result["status"] == "completed"

    stamp_calls = [
        (q, a) for q, a in calls
        if q.strip().startswith("UPDATE videos SET environments_approved_at = NULL, environments_hash")
    ]
    assert len(stamp_calls) == 1, "run_environments_design_step must stamp environments_hash exactly once per run"
    stamped_hash = stamp_calls[0][1][2]
    assert stamped_hash == _hash(script_text)


# ---------------------------------------------------------------------------
# 3. Converging writers through sync_video_script
# ---------------------------------------------------------------------------

def test_update_scene_text_flips_both_statuses_to_stale(monkeypatch):
    state, calls, fake_execute, fake_fetch_all, fake_fetch_one = _make_fake_db(
        OLD_TEXT, OLD_TEXT, characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),
    )
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)

    asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text=NEW_TEXT), tenant_id="tenant-1",
    ))

    assert NEW_TEXT in state["videos_script"]
    assert state["video_characters_status"] == "stale"
    assert state["video_environments_status"] == "stale"
    assert _no_deletes(calls)


def test_apply_prompt_draft_flips_both_statuses_to_stale(monkeypatch):
    state, calls, fake_execute, fake_fetch_all, fake_fetch_one = _make_fake_db(
        OLD_TEXT, OLD_TEXT, characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),
    )
    monkeypatch.setattr(chat_route, "execute", fake_execute)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)

    draft = {"surface": "script", "draft": NEW_TEXT, "label": "Scene 1", "scene": 1}
    asyncio.run(chat_route._apply_prompt_draft("tenant-1", "video-1", draft, None))

    assert NEW_TEXT in state["videos_script"]
    assert state["video_characters_status"] == "stale"
    assert state["video_environments_status"] == "stale"
    assert _no_deletes(calls)


def test_rewrite_scene_text_flips_both_statuses_to_stale(monkeypatch):
    state, calls, fake_execute_base, fake_fetch_all, fake_fetch_one_base = _make_fake_db(
        OLD_TEXT, OLD_TEXT, characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),
    )

    async def fake_execute(query, *args):
        q = query.strip()
        if q.startswith("UPDATE scripts SET scene_text = $4"):
            # rewrite_scene_text's OWN arg order — (video_id, tenant_id,
            # scene, new_text, new_location) — different from
            # update_scene_text's ($1=stored_text first), so it needs its
            # own branch rather than the shared _make_fake_db handler.
            calls.append((query, args))
            _video_id, _tenant_id, scene, new_text, _new_location = args
            row = state["scripts"].get(scene)
            if row is not None:
                row["scene_text"] = new_text
            return "UPDATE 1"
        return await fake_execute_base(query, *args)

    async def fake_fetch_one(query, *args):
        if "video_title, render_mode, research_payload FROM videos" in query:
            return {"id": "video-1", "video_title": "T", "render_mode": None, "research_payload": None}
        if "scene_text FROM scripts WHERE video_id" in query and "AND scene = " in query:
            return {"scene_text": OLD_TEXT}
        if "prompt_text FROM tenant_prompt_defaults" in query:
            return None
        return await fake_fetch_one_base(query, *args)

    async def fake_get_secret(name, tenant_id=None):
        return "fake-anthropic-key"

    rewritten = (
        "A submarine captain named Vasquez discovers the reactor is failing "
        "and orders the crew to seal every compartment before the pressure "
        "hull gives way under the rising strain of the flooding corridor. "
        "She counts every second against the depth gauge, knowing the whole "
        "boat depends on a decision made in the next few breaths alone."
    )  # >= 40 spoken words — routes/videos.py rewrite_scene_text rejects a shorter result

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"content": [{"text": rewritten}]}

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

    asyncio.run(rv.rewrite_scene_text("video-1", 1, tenant_id="tenant-1"))

    assert rewritten in state["videos_script"]
    assert state["video_characters_status"] == "stale"
    assert state["video_environments_status"] == "stale"
    assert _no_deletes(calls)


# ---------------------------------------------------------------------------
# 4. Inline-sync writers that do NOT go through sync_video_script
# ---------------------------------------------------------------------------

def test_drive_sync_flips_both_statuses_to_stale(monkeypatch):
    state, calls, fake_execute_base, _fake_fetch_all, fake_fetch_one_base = _make_fake_db(
        OLD_TEXT, OLD_TEXT, characters_hash=_hash(OLD_TEXT), environments_hash=_hash(OLD_TEXT),
    )

    async def fake_fetch_one(query, *args):
        if "drive_script_doc_id, drive_script_synced_at" in query:
            return {"id": "video-1", "drive_script_doc_id": "doc-1",
                    "drive_script_synced_at": None, "drive_script_doc_modified_at": None}
        if "google_drive_refresh_token FROM channel_profiles" in query:
            return {"google_drive_refresh_token": "fake-refresh-token"}
        return await fake_fetch_one_base(query, *args)

    async def fake_fetch_all(query, *args):
        q = query.strip()
        # Two distinct SELECTs against scripts: the pre-write read (id +
        # scene + scene_text, used to map the Doc's scenes onto rows) and
        # the post-write rebuild (scene_text only, used to recompute
        # videos.script) — must return the UPDATED text for the second one
        # or the sync would silently un-write what it just wrote.
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
            # The Drive pull-sync's OWN inline sync — a different parameter
            # order ($1=full text) than sync_video_script's ($3=full text),
            # so it needs its own branch rather than falling through to the
            # shared _make_fake_db handler below (which assumes the latter).
            calls.append((query, args))
            state["videos_script"] = args[0]
            return "UPDATE 1"
        return await fake_execute_base(query, *args)

    async def fake_to_thread(fn, *a, **kw):
        # Bypass the real Google Drive read entirely — return
        # (modified_time, doc_text). _parse_script_doc is mocked below, so
        # the actual text content here is unused.
        return "2026-01-01T00:00:00Z", "unused — _parse_script_doc is mocked"

    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(rv, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rv, "_parse_script_doc", lambda text: {1: NEW_TEXT})
    monkeypatch.setattr(rv.asyncio, "to_thread", fake_to_thread)

    result = asyncio.run(rv.sync_script_from_drive("video-1", force=True, tenant_id="tenant-1"))

    assert result["changed"] is True
    assert NEW_TEXT in state["videos_script"]
    assert state["video_characters_status"] == "stale"
    assert state["video_environments_status"] == "stale"
    assert _no_deletes(calls)


def test_save_machine_script_block_calls_staleness_flag(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    async def fake_fetch_all(query, *args):
        return [{"scene": 1, "scene_text": "Existing XB-15 paragraph."}]

    async def fake_execute(query, *args):
        return None

    async def fake_transition(video_id, old_status, new_status, source):
        return None

    def fake_skip(_video, status):
        return status

    flag_calls = []

    async def fake_flag(video_id, tenant_id):
        flag_calls.append((video_id, tenant_id))

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(executor, "_log_transition", fake_transition)
    monkeypatch.setattr(executor, "_skip_disabled_next", fake_skip)
    monkeypatch.setattr(rv, "_flag_stale_cast_and_environments", fake_flag)

    result = asyncio.run(
        executor._save_machine_script_block(
            video_id="video-test",
            video={"status": "ready_for_scripting", "script_validation": {}},
            roster=["Boeing XB-15", "Douglas XB-19"],
            script_block={
                "machine": "Douglas XB-19", "scene": 2,
                "paragraph": "Saved XB-19 paragraph.", "word_count": 101,
                "research_source": "compact_editorial_brief", "passed": True, "warnings": [],
            },
            title="Every US Strategic Bomber Ever Built",
            voice_id="voice-test",
        )
    )

    assert result["saved"] is True
    assert flag_calls == [("video-test", "tenant-test")], (
        "_save_machine_script_block writes videos.script directly (not "
        "through sync_video_script) so it must call the D7-2 staleness "
        "flag itself"
    )


class _AsyncContext:
    """Mirrors tests/functional/test_custom_film_production_runner.py's
    helper of the same name — kept local rather than imported cross-file so
    this test doesn't depend on that file's module surviving conftest.py's
    per-file sys.modules isolation into test-execution time."""

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AsyncContext(self.conn)


def _custom_film_script_adapter():
    """Minimal valid SectionStageAdapter for a "script" stage section —
    mirrors tests/functional/test_custom_film_production_runner.py's
    `_adapter("script", section_id="section-b", seconds=19,
    profile="power_doctrine_v2", language_mode="bilingual", dubbing=True)`
    combination, the exact one that test file proves passes `_request`'s
    contract checks AND the deterministic script-timing/grounding gate
    below (19s -> a ~48-word ACT marker — the generate() stub below must
    match it exactly, or the seam's own preflight rejects the "generated"
    script before ever reaching the D7-2 hook this test is proving)."""
    from custom_film_section_runtime import SectionStageAdapter

    return SectionStageAdapter(
        runtime_hash="a" * 64, plan_id="plan-1", video_id="video-1",
        section_id="section-b", order_index=1, stage="script",
        duration_seconds=19, role="explanation", purpose="Explain why the mechanism matters",
        render_mode="coverage", script_profile="power_doctrine_v2", visual_profile="neutral_v1",
        dialogue_audio="voice_over",
        image_density={"mode": "visual_cue", "target_per_minute": 8},
        language={"mode": "bilingual"},
        dubbing={"enabled": True, "mode": "speech_to_speech"},
        animation={"enabled": True, "mode": "grok_native"},
        segmentation={"mode": "speaker_turn"},
        camera={"mode": "investigative_coverage"},
        quality_laws=("source_grounding", "visual_cue_fidelity"),
        image_source="generate",
        provenance={"script_profile": ["power_doctrine_v2"]},
        estimated_media={"still_images": 1, "animation_clips": 1, "voice_tracks": 2},
    )


def test_custom_film_script_calls_staleness_flag(monkeypatch):
    import custom_film_production_runner as production

    request = production._request(
        _custom_film_script_adapter(), (), "custom-film-op:" + "f" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")

    class Executor:
        def __init__(self):
            self._pipeline = SimpleNamespace(anthropic=object())

        async def _ensure_initialized(self):
            return None

        async def _get_video(self, video_id):
            return {
                "video_title": "A film",
                "research_payload": {"fact_sheet": "Sourced facts"},
            }

    async def generate(client, brief, **kwargs):
        return {
            "script": (
                "[ACT 1 — EXPLANATION | 0:00 - 0:19 | ~48 words]\n"
                "The sourced mechanism appears on screen as a marked diagram. "
                "A hand traces the connection while the bilingual explanation "
                "names what changes and why it matters. The camera moves closer "
                "to the decisive link, then returns to the full system so the "
                "audience can see the result."
            ),
            "validation": {"valid": True},
        }

    async def pass_quality(*_args, **kwargs):
        return {
            "scenes": copy.deepcopy(_args[2]),
            "critique": SimpleNamespace(
                verdict="pass", score=98, failing_gates=[], violations=[],
                rule_verdicts=[], needs_revision=False,
            ),
            "needs_review": False, "edit_rounds": 0, "regenerated": False, "changed": False,
        }

    class Connection:
        async def fetchrow(self, sql, *args):
            assert "INSERT INTO scripts" in sql
            return {"id": args[0]}

        async def execute(self, sql, *args):
            assert "UPDATE videos" in sql
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    flag_calls = []

    async def fake_flag(video_id, tenant_id):
        flag_calls.append((video_id, tenant_id))

    seams._executor = Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script", generate,
    )
    monkeypatch.setattr(
        "script.brief_translator.script_generator.validate_script",
        lambda *_args, **_kwargs: {"valid": True, "issues": []},
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", pass_quality)
    monkeypatch.setattr(
        "shared.profiles.script.load_script_profile",
        lambda profile_id: object(),
    )
    monkeypatch.setattr("database.get_pool", get_pool)
    monkeypatch.setattr(rv, "_flag_stale_cast_and_environments", fake_flag)

    result = asyncio.run(seams._script(request))

    assert result["scene_ids"]
    assert flag_calls == [(request.video_id, "tenant-1")], (
        "Custom Film's own script-persistence seam writes videos.script "
        "directly and must call the D7-2 staleness flag itself, same as "
        "every other inline script-sync path"
    )
