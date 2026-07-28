"""Director surface Task 5.4a/b (DIRECTOR-CHAT-PLAN.md, checklist item "make him
older" resolves to whatever the creator has SELECTED, not a guess): proves the
backend resolves a chat message's target DETERMINISTICALLY off `ui_context`,
not off the classifier's free-text guess.

The whole feature, proven at the layer where it's actually decided:

1. `routes.chat._resolve_prompt_target` — the SAME message/surface/scene/index
   args, two different `ui_context.focusedAssetId` values -> two different
   `asset_id`s in the result. A shot explicitly named in the message (scene/
   index) still wins over an ambient selection.
2. `routes.chat._resolve_character_target` / `_resolve_environment_target` —
   two different `ui_context.selectedEntityId` values (same `selectedEntityType`)
   -> two different `entity_id`s. Wrong `selectedEntityType` (or none) asks
   instead of guessing.
3. `routes.chat._apply_prompt_draft` — applying a character/environment draft
   writes through the SAME free route function the `edit_character`/
   `edit_environment` MCP tools wrap (routes.characters.update_character /
   routes.environments.update_environment), scoped to the resolved entity_id,
   and does NOT queue a paid redraw.
4. `routes.chat._selection_context_note` / `agent_brain._selection_context_note`
   — present only when the corresponding `ui_context` field is set, and name
   the concrete id/type (not just "look at the screen").

Same stub pattern as test_c15b_show_and_approve_scene.py: stub `database`/
`vault` before importing routes.chat (its `from database import ...` binds
fetch_all/fetch_one/execute as module-level names tests monkeypatch directly)
— no live DB, no network, no LLM call anywhere in this file.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_ui_context_selection_routing.py -q
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

import routes.chat as chat  # noqa: E402
import agent_brain  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"

SUMMARY = {"model": "grok-imagine"}

SHOT_A = {
    "id": "asset-AAA",
    "scene": 3,
    "image_index": 1,
    "image_prompt": "shot A prompt",
    "video_prompt": "shot A motion",
    "image_url": "https://cdn.example/a.png",
}
SHOT_B = {
    "id": "asset-BBB",
    "scene": 3,
    "image_index": 2,
    "image_prompt": "shot B prompt",
    "video_prompt": "shot B motion",
    "image_url": "https://cdn.example/b.png",
}

CHAR_MILO = {"id": "char-MILO", "name": "Milo", "description": "A curious dragon."}
CHAR_WAYAN = {"id": "char-WAYAN", "name": "Wayan", "description": "A quiet fisherman."}

ENV_BEDROOM = {"id": "env-BEDROOM", "name": "SF Bedroom", "description": "A small city bedroom."}
ENV_TERRACE = {"id": "env-TERRACE", "name": "Bali Terrace", "description": "An open-air terrace."}


# ---------------------------------------------------------------------------
# 1. _resolve_prompt_target — image/motion, focusedAssetId is DETERMINISTIC
# ---------------------------------------------------------------------------

def test_two_different_focused_shots_resolve_to_two_different_assets(monkeypatch):
    """The core proof: the SAME (surface, scene=None, index=None) call, only
    ui_context.focusedAssetId differs -> a different asset_id comes back.
    Nothing about the message text drives this — it's the selection alone."""
    rows_by_id = {SHOT_A["id"]: SHOT_A, SHOT_B["id"]: SHOT_B}

    async def fake_fetch_one(query, asset_id, video_id, tenant_id):
        assert "FROM assets WHERE id=$1" in query
        assert video_id == VIDEO and tenant_id == TENANT
        row = rows_by_id.get(asset_id)
        return dict(row) if row else None

    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)

    target_a = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "image", None, None, {"focusedAssetId": "asset-AAA"}, SUMMARY,
    ))
    target_b = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "image", None, None, {"focusedAssetId": "asset-BBB"}, SUMMARY,
    ))

    assert target_a["asset_id"] == "asset-AAA"
    assert target_b["asset_id"] == "asset-BBB"
    assert target_a["asset_id"] != target_b["asset_id"]
    assert target_a["current"] == "shot A prompt"
    assert target_b["current"] == "shot B prompt"
    assert target_a["label"] == "scene 3 picture 1"
    assert target_b["label"] == "scene 3 picture 2"


def test_explicit_scene_index_in_the_message_wins_over_the_ambient_focus(monkeypatch):
    """The creator naming a DIFFERENT shot in the message ("redo scene 5 image
    2") must win over whatever happens to be focused on the canvas — the
    selection is a fallback signal, not an override of explicit words."""
    scene_rows = [
        {"id": "asset-CCC", "image_index": 1, "image_prompt": "p1", "video_prompt": "m1", "image_url": "u"},
        {"id": "asset-DDD", "image_index": 2, "image_prompt": "p2", "video_prompt": "m2", "image_url": "u"},
    ]

    async def fake_fetch_all(query, video_id, tenant_id, scene):
        assert scene == 5
        return [dict(r) for r in scene_rows]

    async def fail_fetch_one(*a, **k):
        raise AssertionError("must not do an id-based lookup when scene/index were named explicitly")

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(chat, "fetch_one", fail_fetch_one)

    target = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "image", 5, 2, {"focusedAssetId": "asset-AAA"}, SUMMARY,
    ))
    assert target["asset_id"] == "asset-DDD"
    assert target["scene"] == 5 and target["index"] == 2


def test_no_selection_and_no_named_scene_asks_instead_of_guessing(monkeypatch):
    async def fail_any(*a, **k):
        raise AssertionError("must not query anything with no scene/index/selection")

    monkeypatch.setattr(chat, "fetch_one", fail_any)
    monkeypatch.setattr(chat, "fetch_all", fail_any)

    target = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "image", None, None, {}, SUMMARY,
    ))
    assert "error" in target
    assert "which scene" in target["error"].lower()


# ---------------------------------------------------------------------------
# 2. _resolve_character_target / _resolve_environment_target
# ---------------------------------------------------------------------------

def test_two_different_selected_characters_resolve_to_two_different_entities(monkeypatch):
    rows_by_id = {CHAR_MILO["id"]: CHAR_MILO, CHAR_WAYAN["id"]: CHAR_WAYAN}

    async def fake_fetch_one(query, char_id, video_id, tenant_id):
        assert "FROM video_characters WHERE id=$1" in query
        assert video_id == VIDEO and tenant_id == TENANT
        row = rows_by_id.get(char_id)
        return dict(row) if row else None

    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)

    target_milo = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "character", None, None,
        {"selectedEntityId": "char-MILO", "selectedEntityType": "character"}, SUMMARY,
    ))
    target_wayan = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "character", None, None,
        {"selectedEntityId": "char-WAYAN", "selectedEntityType": "character"}, SUMMARY,
    ))

    assert target_milo["entity_id"] == "char-MILO"
    assert target_wayan["entity_id"] == "char-WAYAN"
    assert target_milo["entity_id"] != target_wayan["entity_id"]
    assert target_milo["current"] == "A curious dragon."
    assert target_wayan["current"] == "A quiet fisherman."
    assert target_milo["apply_cost"] == 0.0, "a description edit is free — no portrait redraw queued"


def test_two_different_selected_environments_resolve_to_two_different_entities(monkeypatch):
    rows_by_id = {ENV_BEDROOM["id"]: ENV_BEDROOM, ENV_TERRACE["id"]: ENV_TERRACE}

    async def fake_fetch_one(query, env_id, video_id, tenant_id):
        assert "FROM video_environments WHERE id=$1" in query
        row = rows_by_id.get(env_id)
        return dict(row) if row else None

    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)

    target_bedroom = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "environment", None, None,
        {"selectedEntityId": "env-BEDROOM", "selectedEntityType": "environment"}, SUMMARY,
    ))
    target_terrace = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "environment", None, None,
        {"selectedEntityId": "env-TERRACE", "selectedEntityType": "environment"}, SUMMARY,
    ))

    assert target_bedroom["entity_id"] == "env-BEDROOM"
    assert target_terrace["entity_id"] == "env-TERRACE"
    assert target_bedroom["entity_id"] != target_terrace["entity_id"]


def test_same_message_two_selections_end_to_end_through_handle_prompt_op_target(monkeypatch):
    """The verification bar, literally: ONE message ("make him older"), TWO
    different selections, resolved through the same code path
    _handle_prompt_op uses (_resolve_prompt_target) — two different
    entity_ids come back. The classifier's job here is only to have already
    decided kind=prompt/surface=character (see _selection_context_note below
    for how it's told to do that); id resolution never touches the LLM."""
    rows_by_id = {CHAR_MILO["id"]: CHAR_MILO, CHAR_WAYAN["id"]: CHAR_WAYAN}

    async def fake_fetch_one(query, char_id, video_id, tenant_id):
        row = rows_by_id.get(char_id)
        return dict(row) if row else None

    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)

    message = "make him older"  # noqa: F841 — documents what's constant across both calls
    ui_milo = {"selectedEntityId": "char-MILO", "selectedEntityType": "character"}
    ui_wayan = {"selectedEntityId": "char-WAYAN", "selectedEntityType": "character"}

    target_for_milo = asyncio.run(
        chat._resolve_prompt_target(TENANT, VIDEO, "character", None, None, ui_milo, SUMMARY)
    )
    target_for_wayan = asyncio.run(
        chat._resolve_prompt_target(TENANT, VIDEO, "character", None, None, ui_wayan, SUMMARY)
    )

    assert target_for_milo["entity_id"] != target_for_wayan["entity_id"]
    assert target_for_milo["label"] == "the character Milo"
    assert target_for_wayan["label"] == "the character Wayan"


def test_character_surface_with_no_selection_asks_instead_of_guessing(monkeypatch):
    async def fail_any(*a, **k):
        raise AssertionError("must not query with no selection")

    monkeypatch.setattr(chat, "fetch_one", fail_any)

    target = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "character", None, None, {}, SUMMARY,
    ))
    assert "error" in target
    assert "which character" in target["error"].lower()


def test_character_surface_ignores_a_selected_environment_id():
    """selectedEntityType must gate which table gets queried — a stray
    environment id under a character surface is not silently accepted."""
    target = asyncio.run(chat._resolve_prompt_target(
        TENANT, VIDEO, "character", None, None,
        {"selectedEntityId": "env-BEDROOM", "selectedEntityType": "environment"}, SUMMARY,
    ))
    assert "error" in target


# ---------------------------------------------------------------------------
# 3. _apply_prompt_draft — character/environment apply is free, writes
#    through the real route function, never queues a redraw.
# ---------------------------------------------------------------------------

def test_apply_character_draft_writes_through_update_character_and_queues_no_redraw(monkeypatch):
    import routes.characters as characters_routes

    seen = {}

    async def fake_update_character(video_id, char_id, body, tenant_id=None):
        seen["video_id"] = video_id
        seen["char_id"] = char_id
        seen["description"] = body.description
        seen["tenant_id"] = tenant_id
        return {"id": char_id, "description": body.description}

    monkeypatch.setattr(characters_routes, "update_character", fake_update_character)

    class BoomBackgroundTasks:
        def add_task(self, *a, **k):
            raise AssertionError("a free description edit must never queue a paid redraw")

    draft = {
        "surface": "character",
        "entity_id": "char-MILO",
        "label": "the character Milo",
        "draft": "A curious, now much older dragon.",
    }
    line = asyncio.run(chat._apply_prompt_draft(TENANT, VIDEO, draft, BoomBackgroundTasks()))

    assert seen == {
        "video_id": VIDEO,
        "char_id": "char-MILO",
        "description": "A curious, now much older dragon.",
        "tenant_id": TENANT,
    }
    assert "Milo" in line


def test_apply_environment_draft_writes_through_update_environment(monkeypatch):
    import routes.environments as environments_routes

    seen = {}

    async def fake_update_environment(video_id, env_id, body, tenant_id=None):
        seen["video_id"] = video_id
        seen["env_id"] = env_id
        seen["description"] = body.description
        seen["tenant_id"] = tenant_id
        return {"id": env_id, "description": body.description}

    monkeypatch.setattr(environments_routes, "update_environment", fake_update_environment)

    class BoomBackgroundTasks:
        def add_task(self, *a, **k):
            raise AssertionError("a free description edit must never queue a paid redraw")

    draft = {
        "surface": "environment",
        "entity_id": "env-BEDROOM",
        "label": "the location SF Bedroom",
        "draft": "A small city bedroom, now lit by rain against the window.",
    }
    line = asyncio.run(chat._apply_prompt_draft(TENANT, VIDEO, draft, BoomBackgroundTasks()))

    assert seen["env_id"] == "env-BEDROOM"
    assert seen["description"] == "A small city bedroom, now lit by rain against the window."
    assert "SF Bedroom" in line


def test_prompt_apply_card_character_and_environment_are_free_save_not_redraw():
    target = {"surface": "character", "label": "the character Milo", "apply_cost": 0.0}
    card = chat._prompt_apply_card(target, "new description")
    yes = next(o for o in card["options"] if o["value"] == "yes")
    assert yes["label"] == "Save it"


# ---------------------------------------------------------------------------
# 4. _selection_context_note (chat.py and agent_brain.py) — tells the
#    classifier what's selected, present only when the field is actually set.
# ---------------------------------------------------------------------------

def test_selection_note_empty_with_no_selection():
    assert chat._selection_context_note({}) == ""
    assert agent_brain._selection_context_note({}) == ""


def test_selection_note_names_the_focused_asset_id():
    note = chat._selection_context_note({"focusedAssetId": "asset-AAA"})
    assert "asset-AAA" in note
    assert "surface=image" in note


def test_selection_note_names_the_selected_character():
    note = chat._selection_context_note({"selectedEntityType": "character"})
    assert "character" in note
    assert "surface=character" in note


def test_selection_note_names_the_selected_environment():
    note = chat._selection_context_note({"selectedEntityType": "environment"})
    assert "environment" in note
    assert "surface=environment" in note


def test_chat_and_agent_brain_selection_notes_agree():
    """The two copies (duplicated, not shared, to dodge a circular import —
    see both docstrings) must not silently drift into disagreement."""
    for ui in (
        {"focusedAssetId": "asset-AAA"},
        {"selectedEntityType": "character"},
        {"selectedEntityType": "environment"},
        {"focusedAssetId": "asset-AAA", "selectedEntityType": "character"},
    ):
        assert chat._selection_context_note(ui) == agent_brain._selection_context_note(ui)
