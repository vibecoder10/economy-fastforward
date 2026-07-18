"""Tests for C15b (checklist §1.2, tasks/storyengine-wiring-fix-checklist.md
"Director review loop, part 1" — tasks/storyengine-copilot-ux-map.md): the
copilot can SHOW a scene's actual pictures inline in chat, and the creator can
say "approve scene N" to lock that one scene's assets in.

Two capabilities, three layers:

1. `actions.py::_runner_approve_scene` — the scene-scoped free verb.
   - Tenant + video + scene scoped UPDATE (never another scene's/tenant's rows).
   - No scene named -> a clarifying question, no write attempted.
   - Zero rows touched -> "nothing to approve" (that scene has no pictures).
   - `ACTIONS["approve_scene"]["paid"]` is False (no confirm card needed) and
     `RUNNERS["approve_scene"]` is wired to the runner.

2. `routes.chat._media_proxy_url` — converts a stored Drive link into the
   backend's authorized media-proxy URL; passes non-Drive URLs through
   unchanged (the same precedent pipeline_executor.py's `_proxy_url` and
   routes/characters.py's `_fetch_image_bytes` already establish). Never
   returns a raw `drive.google.com` URL.

3. `routes.chat._handle_show_op` — the "show me scene N's boards" card:
   tenant+video+scene scoped SELECT, capped at `_MAX_SHOW_IMAGES`, every
   image URL proxied (asserted with a `drive.google.com` NEGATIVE check, not
   just a positive shape check), and a graceful no-assets-yet reply (with a
   real cost quote) when the scene has no pictures.

Same stub pattern as test_c15a_plan_cost_quote.py (stub `database`/`vault`
before importing `routes.chat`, since chat.py's `from database import ...`
binds fetch_all/execute as module-level names on `routes.chat` itself that
tests monkeypatch directly — no live DB, no network).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c15b_show_and_approve_scene.py -q
"""
import asyncio
import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("vault", get_secret=_boom)

_PIPELINE_ROOT = os.path.abspath(os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline"))
sys.path.insert(0, _PIPELINE_ROOT)

import actions  # noqa: E402
import routes.chat as chat  # noqa: E402

TENANT = "tenant-1"
OTHER_TENANT = "tenant-2"
VIDEO = "video-1"


def _summary(**over):
    base = {
        "title": "T", "status": "ready_for_video_generation", "length_min": 5,
        "model": "grok-imagine", "scenes": 3, "boards": 3, "voiced": 3,
        "max_scene": 3, "pics": 6, "clips": 0, "cast": 0, "spent": 0.0,
        "render_style": None,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. actions.py — approve_scene registry + runner
# ---------------------------------------------------------------------------

def test_approve_scene_registered_free_no_confirm_needed():
    cfg = actions.ACTIONS["approve_scene"]
    assert cfg["paid"] is False, "approve_scene must never hold behind a paid confirm card"
    assert cfg["runner"] == "approve_scene"
    assert actions.RUNNERS["approve_scene"] is actions._runner_approve_scene


def test_approve_scene_no_scene_named_asks_instead_of_writing(monkeypatch):
    async def fake_execute(*a, **k):
        raise AssertionError("must not write when no scene was named")
    monkeypatch.setattr(actions, "execute", fake_execute)

    result = asyncio.run(actions._runner_approve_scene(TENANT, VIDEO, None, {"scene": None}))
    assert "which scene" in result.lower()


def test_approve_scene_scopes_update_to_tenant_video_and_scene(monkeypatch):
    """The single hard requirement: this can NEVER touch another scene's,
    another video's, or another tenant's assets. Assert both the WHERE
    clause names all three columns and the bound params are exactly
    (video_id, tenant_id, scene) in that order."""
    seen = {}

    async def fake_execute(query, *args):
        seen["query"] = query
        seen["args"] = args
        return "UPDATE 3"

    monkeypatch.setattr(actions, "execute", fake_execute)

    result = asyncio.run(actions._runner_approve_scene(TENANT, VIDEO, None, {"scene": 2}))

    assert "video_id = $1" in seen["query"] and "tenant_id = $2" in seen["query"] and "scene = $3" in seen["query"]
    assert seen["args"] == (VIDEO, TENANT, 2)
    assert "status = 'approved'" in seen["query"]
    assert "scene 2 approved" in result.lower()
    assert "3 shot" in result


def test_approve_scene_different_tenant_gets_its_own_scoped_call(monkeypatch):
    """Same scene number, different tenant -> the tenant param actually
    changes (proves there's no hardcoded/leaked tenant_id anywhere in the
    runner)."""
    seen = {}

    async def fake_execute(query, *args):
        seen["args"] = args
        return "UPDATE 1"

    monkeypatch.setattr(actions, "execute", fake_execute)
    asyncio.run(actions._runner_approve_scene(OTHER_TENANT, VIDEO, None, {"scene": 2}))
    assert seen["args"] == (VIDEO, OTHER_TENANT, 2)


def test_approve_scene_zero_rows_says_nothing_to_approve(monkeypatch):
    async def fake_execute(*a, **k):
        return "UPDATE 0"
    monkeypatch.setattr(actions, "execute", fake_execute)

    result = asyncio.run(actions._runner_approve_scene(TENANT, VIDEO, None, {"scene": 9}))
    assert "nothing to approve" in result.lower()


def test_approve_scene_singular_plural_shot_wording(monkeypatch):
    async def fake_execute(*a, **k):
        return "UPDATE 1"
    monkeypatch.setattr(actions, "execute", fake_execute)
    result = asyncio.run(actions._runner_approve_scene(TENANT, VIDEO, None, {"scene": 4}))
    assert "1 shot locked in" in result
    assert "1 shots" not in result


# ---------------------------------------------------------------------------
# 2. routes.chat._media_proxy_url — never leaks a raw Drive URL
# ---------------------------------------------------------------------------

def test_media_proxy_url_converts_query_style_drive_link():
    url = "https://drive.google.com/uc?export=download&id=ABC123xyz-_"
    out = chat._media_proxy_url(url)
    assert out is not None
    assert "drive.google.com" not in out, "must never leak the raw Drive URL"
    assert out.endswith("/api/media/drive/ABC123xyz-_")


def test_media_proxy_url_converts_share_link_style():
    url = "https://drive.google.com/file/d/XYZ987/view?usp=sharing"
    out = chat._media_proxy_url(url)
    assert "drive.google.com" not in out
    assert out.endswith("/api/media/drive/XYZ987")


def test_media_proxy_url_passes_through_non_drive_url_unchanged():
    """A URL that was never a Drive link (e.g. the Supabase storage backend's
    own public URL) isn't a Drive link to convert -- matches the existing
    precedent (pipeline_executor.py's _proxy_url) exactly."""
    url = "https://supabase.example.com/storage/v1/object/public/assets/foo.png"
    assert chat._media_proxy_url(url) == url


def test_media_proxy_url_none_in_none_out():
    assert chat._media_proxy_url(None) is None
    assert chat._media_proxy_url("") is None


# ---------------------------------------------------------------------------
# 3. routes.chat._handle_show_op — the inline scene-boards card
# ---------------------------------------------------------------------------

def _rows_for(n, tenant="tenant-1-drive"):
    return [
        {"id": f"asset-{i}", "image_index": i,
         "image_url": f"https://drive.google.com/uc?export=download&id=FILE{i}",
         "drive_image_url": None}
        for i in range(1, n + 1)
    ]


async def _collect_reply(coro):
    replies = []

    async def _reply(text, cards=None):
        replies.append((text, cards))
        return {"text": text, "cards": cards}

    await coro(_reply)
    return replies[-1]


def test_show_op_no_scene_named_asks_a_clarifying_question(monkeypatch):
    async def fake_fetch_all(*a, **k):
        raise AssertionError("must not query when no scene is known")
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)

    async def run(_reply):
        return await chat._handle_show_op(TENANT, VIDEO, _summary(), {"scene": None}, {}, _reply)

    text, cards = asyncio.run(_collect_reply(run))
    assert "which scene" in text.lower()
    assert cards is None


def test_show_op_uses_ui_context_scene_when_not_named(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["args"] = args
        return _rows_for(2)

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)

    async def run(_reply):
        return await chat._handle_show_op(TENANT, VIDEO, _summary(), {"scene": None}, {"scene": 4}, _reply)

    asyncio.run(_collect_reply(run))
    # video_id, tenant_id, scene, limit
    assert seen["args"][:3] == (VIDEO, TENANT, 4)


def test_show_op_scopes_query_to_tenant_video_scene_and_caps_count(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["query"] = query
        seen["args"] = args
        return _rows_for(8)  # more than the cap — proves the cap is enforced, not coincidental

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)

    async def run(_reply):
        return await chat._handle_show_op(TENANT, VIDEO, _summary(), {"scene": 3}, {}, _reply)

    text, cards = asyncio.run(_collect_reply(run))

    assert "video_id=$1" in seen["query"] and "tenant_id=$2" in seen["query"] and "scene=$3" in seen["query"]
    assert seen["args"] == (VIDEO, TENANT, 3, chat._MAX_SHOW_IMAGES)
    assert chat._MAX_SHOW_IMAGES == 6

    assert cards is not None and len(cards) == 1
    card = cards[0]
    assert card["images"], "card must carry the images list"
    assert len(card["images"]) <= chat._MAX_SHOW_IMAGES


def test_show_op_images_are_all_proxied_never_raw_drive_links(monkeypatch):
    async def fake_fetch_all(*a, **k):
        return _rows_for(3)
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)

    async def run(_reply):
        return await chat._handle_show_op(TENANT, VIDEO, _summary(), {"scene": 2}, {}, _reply)

    _text, cards = asyncio.run(_collect_reply(run))
    images = cards[0]["images"]
    assert len(images) == 3
    for img in images:
        assert "drive.google.com" not in img["url"], "leaked a raw Drive URL into the chat payload"
        assert "/api/media/drive/" in img["url"]
        assert img["scene"] == 2
        assert img["asset_id"]
        assert img["label"]


def test_show_op_empty_scene_offers_to_generate_with_a_real_quote(monkeypatch):
    async def fake_fetch_all(*a, **k):
        return []
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)

    async def fake_estimate(tenant_id, video_id, verb, scene, summary):
        assert verb == "images" and scene == 5
        return 0.30, "~$0.30"

    monkeypatch.setattr(chat, "_estimate_cost", fake_estimate)

    async def run(_reply):
        return await chat._handle_show_op(TENANT, VIDEO, _summary(pics=0), {"scene": 5}, {}, _reply)

    text, cards = asyncio.run(_collect_reply(run))
    assert "scene 5" in text.lower()
    assert "doesn't have any pictures yet" in text.lower()
    assert "$0.30" in text
    assert cards is None


def test_show_op_reply_mentions_approve_verb_as_the_next_step(monkeypatch):
    """Loose coupling check: the show reply should nudge toward the new
    approve_scene verb (the two capabilities are meant to chain), not just
    dump images with no next step."""
    async def fake_fetch_all(*a, **k):
        return _rows_for(1)
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)

    async def run(_reply):
        return await chat._handle_show_op(TENANT, VIDEO, _summary(), {"scene": 7}, {}, _reply)

    text, _cards = asyncio.run(_collect_reply(run))
    assert "approve scene 7" in text.lower()


# ---------------------------------------------------------------------------
# 4. Kind/verb vocabulary additions are present in both decision schemas
# ---------------------------------------------------------------------------

def test_agent_brain_decision_schema_includes_show_and_approve_scene():
    import agent_brain
    schema = agent_brain._decision_schema()
    # C15c extended the kind enum with |remember|forget — check the "show"
    # value is present in the enum rather than an exact-suffix match so this
    # doesn't break every time a future chunk adds another kind.
    assert '"kind":"read|action|prompt|show|remember|forget"' in schema
    assert "approve_scene" in schema


def test_fallback_classifier_prompt_source_includes_show_and_approve_scene():
    """The one-shot fallback classifier prompt (chat.py, used when the agent
    brain fails) must offer the same new vocabulary — checked against the
    module source since the prompt is built inline inside _handle_copilot."""
    import inspect
    src = inspect.getsource(chat._handle_copilot)
    assert '"kind":"read|action|prompt|show|remember|forget"' in src
    assert "approve_scene" in src
