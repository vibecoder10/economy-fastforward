"""Tests for C22 (checklist §2.1 [U], P2.1c — "user-created presets via chat
('make me a new style…')").

Scope decision (see SYSTEM_STATE.md §C22 for the full rationale): a user-
created "style" here is a tenant-owned STYLE DESCRIPTION — a row in the
EXISTING `visual_styles` CRUD table (the profile page's "Visual Styles"
manager, checklist §C20's axis-2) — NOT a new `style_presets` engine row
(those are Python rendering engines; a creator can't author one
conversationally). This chunk adds a conversational door onto that SAME
CRUD, reusing its exact create/activate route handlers — no fourth style
system, no forked write path.

Two new home-producer profile_ops (routes/chat.py's `_apply_profile_ops`,
the SAME dispatch `remember`/`forget`/`add_competitor`/etc. already use):
  - "draft_style"  -> stashes a draft in conversation state; NEVER writes a
    row. A visual_styles row can only ever be created by the deterministic
    turn-2 confirm handler (`_handle_style_draft_confirm`), gated on the
    creator's own "yes" tap on the style_draft preview card — this is the
    hard "confirm-before-save" guarantee the checklist's [V] line asks for,
    not a hope that the LLM behaves.
  - "use_style"    -> resolves a saved style BY NAME and activates it via
    the CRUD's existing `activate_visual_style` (same semantics the profile
    page's "Set active" button already uses).

Layers pinned here, no live DB / no network:
  1. producer_prompt: the draft_style/use_style vocabulary is taught in the
     prompt text AND the JSON schema's profile_ops example (a card the model
     was never told to emit never gets emitted — same lock C21b used for
     look_engine/style_preset_id).
  2. `_apply_profile_ops`'s "draft_style" branch: stashes
     state["pending_style_draft"], returns a confirmation line, and — the
     core guarantee — never calls fetch_one/execute/create_visual_style.
  3. `_apply_profile_ops`'s "use_style" branch: exact-name match, ILIKE
     fallback, not-found friendly reply, activates via
     routes.visual_styles.activate_visual_style with the right style id.
  4. `_style_draft_card` / `_maybe_attach_style_draft_card`: the card is
     attached ONLY when this turn's ops actually included draft_style AND a
     draft is actually pending — never manufactured from the LLM's prose
     alone.
  5. `_handle_style_draft_confirm`: the ONLY place that can create a row.
     - no pending draft -> friendly reply, zero DB/CRUD calls.
     - selections.style_draft != "yes" -> discards the draft, zero writes.
     - "yes" -> calls routes.visual_styles.create_visual_style ONCE with a
       CreateStyleRequest built from the exact drafted name/look.
     - CRUD failure -> fail-soft friendly reply, never raises.
  6. Source-lock: chat_turn's step 3.6 intercepts style_draft selections
     BEFORE the normal intake turn (which would otherwise just hand the
     selection to the LLM as text).
  7. `_visual_styles_brief`: real rows (with the active one tagged), fail-
     soft on DB error and on an empty library (-> "" — unlike
     `_style_presets_brief`, an empty section here is correct, not a
     fallback catalog), and wired into BOTH producer entry points
     (`_seed_producer`, `chat_turn`).

Same stub pattern as test_c21b_style_axis_split.py: no live DB, no network.
Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c22_style_draft.py -q
"""
import asyncio
import inspect
import os
import sys
import types
from dataclasses import dataclass
from typing import Optional

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom, safe_column=lambda name: name)
_stub("vault", get_secret=_boom)

import producer_prompt  # noqa: E402
import routes.chat as chat  # noqa: E402
import routes.visual_styles as visual_styles  # noqa: E402

TENANT = "tenant-1"
PROJECT = "project-1"


# =============================================================================
# 1. producer_prompt vocabulary
# =============================================================================

def test_producer_system_prompt_teaches_draft_style_and_use_style():
    assert "draft_style" in producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert "use_style" in producer_prompt.PRODUCER_SYSTEM_PROMPT
    # The JSON schema's own example list must carry both, mirroring how
    # remember/forget/look_engine are taught (a vocabulary word mentioned only
    # in prose, never in the schema, tends not to get emitted reliably).
    assert '"op": "draft_style"' in producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert '"op": "use_style"' in producer_prompt.PRODUCER_SYSTEM_PROMPT


# =============================================================================
# 2. _apply_profile_ops — "draft_style": stash only, NEVER a DB write
# =============================================================================

def test_draft_style_stashes_pending_draft_and_touches_no_database(monkeypatch):
    # fetch_one/fetch_all/execute all still bound to the module-level _boom
    # stubs (never monkeypatched in this test) — if the op tried to write
    # anything, this test would fail loudly via the AssertionError in _boom.
    state = {}
    ops = [{"op": "draft_style", "value": {"name": "Ghibli Dream", "look": "Soft watercolor summer light, pastel palette, hand-painted texture."}}]
    results = asyncio.run(chat._apply_profile_ops(TENANT, ops, state, None))

    assert state["pending_style_draft"] == {
        "name": "Ghibli Dream",
        "look": "Soft watercolor summer light, pastel palette, hand-painted texture.",
    }
    assert any("Ghibli Dream" in r for r in results)


def test_draft_style_without_a_look_asks_for_more_and_stashes_nothing():
    state = {}
    ops = [{"op": "draft_style", "value": {"name": "Ghibli Dream", "look": ""}}]
    results = asyncio.run(chat._apply_profile_ops(TENANT, ops, state, None))
    assert "pending_style_draft" not in state
    assert results and "describe" in results[0].lower()


def test_draft_style_defaults_a_missing_name():
    state = {}
    ops = [{"op": "draft_style", "value": {"look": "Neon cyberpunk alley, rain-slicked streets."}}]
    asyncio.run(chat._apply_profile_ops(TENANT, ops, state, None))
    assert state["pending_style_draft"]["name"] == "Custom style"


# =============================================================================
# 3. _apply_profile_ops — "use_style": name resolution + activate
# =============================================================================

def test_use_style_exact_match_activates_via_the_crud(monkeypatch):
    seen = {}

    async def fake_get_project_id(tenant_id):
        assert tenant_id == TENANT
        return PROJECT

    async def fake_fetch_one(query, *args):
        assert "visual_styles" in query
        assert args == (PROJECT, "Ghibli Dream")
        return {"id": "style-123", "name": "Ghibli Dream"}

    async def fake_activate(style_id, tenant_id=None):
        seen["style_id"] = style_id
        seen["tenant_id"] = tenant_id
        return []

    monkeypatch.setattr(visual_styles, "_get_project_id", fake_get_project_id)
    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(visual_styles, "activate_visual_style", fake_activate)

    state = {}
    ops = [{"op": "use_style", "value": "Ghibli Dream"}]
    results = asyncio.run(chat._apply_profile_ops(TENANT, ops, state, None))

    assert seen == {"style_id": "style-123", "tenant_id": TENANT}
    assert any("Ghibli Dream" in r for r in results)


def test_use_style_falls_back_to_fuzzy_ilike_match(monkeypatch):
    calls = []

    async def fake_get_project_id(tenant_id):
        return PROJECT

    async def fake_fetch_one(query, *args):
        calls.append((query, args))
        if len(calls) == 1:
            return None  # exact match misses
        assert "ILIKE" in query
        assert args == (PROJECT, "%ghibli%")
        return {"id": "style-456", "name": "Ghibli Dream V2"}

    async def fake_activate(style_id, tenant_id=None):
        return []

    monkeypatch.setattr(visual_styles, "_get_project_id", fake_get_project_id)
    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(visual_styles, "activate_visual_style", fake_activate)

    results = asyncio.run(chat._apply_profile_ops(TENANT, [{"op": "use_style", "value": "ghibli"}], {}, None))
    assert len(calls) == 2
    assert any("Ghibli Dream V2" in r for r in results)


def test_use_style_not_found_is_a_friendly_reply_not_a_crash(monkeypatch):
    async def fake_get_project_id(tenant_id):
        return PROJECT

    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(visual_styles, "_get_project_id", fake_get_project_id)
    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)

    results = asyncio.run(chat._apply_profile_ops(TENANT, [{"op": "use_style", "value": "Nonexistent"}], {}, None))
    assert any("couldn't find" in r.lower() for r in results)


def test_use_style_empty_value_asks_which_one():
    results = asyncio.run(chat._apply_profile_ops(TENANT, [{"op": "use_style", "value": ""}], {}, None))
    assert any("which" in r.lower() for r in results)


def test_use_style_fails_soft_on_db_error(monkeypatch):
    async def fake_get_project_id(tenant_id):
        raise RuntimeError("db is down")

    monkeypatch.setattr(visual_styles, "_get_project_id", fake_get_project_id)
    results = asyncio.run(chat._apply_profile_ops(TENANT, [{"op": "use_style", "value": "Ghibli"}], {}, None))
    assert results  # a friendly "hit a snag" line, not a raised exception
    assert "snag" in results[0].lower()


# =============================================================================
# 4. _style_draft_card / _maybe_attach_style_draft_card
# =============================================================================

def test_style_draft_card_shape():
    card = chat._style_draft_card({"name": "Ghibli Dream", "look": "Soft pastel watercolor."})
    assert card["id"] == "style_draft"
    assert card["label"] == "Ghibli Dream"
    assert card["body"] == "Soft pastel watercolor."
    values = {o["value"] for o in card["options"]}
    assert values == {"yes", "no"}


def test_attach_card_only_when_turn_actually_drafted_and_state_has_pending():
    data = {"assistant_text": "Here's a draft.", "profile_ops": [{"op": "draft_style", "value": {}}]}
    state = {"pending_style_draft": {"name": "Ghibli Dream", "look": "Soft pastel."}}
    chat._maybe_attach_style_draft_card(data, state)
    assert data["cards"] and data["cards"][0]["id"] == "style_draft"


def test_no_card_when_ops_lack_draft_style():
    data = {"assistant_text": "ok", "profile_ops": [{"op": "set_niche", "value": "cats"}]}
    state = {"pending_style_draft": {"name": "x", "look": "y"}}
    chat._maybe_attach_style_draft_card(data, state)
    assert "cards" not in data


def test_no_card_when_no_pending_draft_even_if_op_present():
    data = {"assistant_text": "ok", "profile_ops": [{"op": "draft_style", "value": {}}]}
    state = {}
    chat._maybe_attach_style_draft_card(data, state)
    assert "cards" not in data


def test_attach_appends_without_clobbering_existing_cards():
    data = {"assistant_text": "ok", "cards": [{"id": "length", "label": "Length", "type": "slider", "options": []}],
            "profile_ops": [{"op": "draft_style", "value": {}}]}
    state = {"pending_style_draft": {"name": "N", "look": "L"}}
    chat._maybe_attach_style_draft_card(data, state)
    assert [c["id"] for c in data["cards"]] == ["length", "style_draft"]


# =============================================================================
# 5. _handle_style_draft_confirm — the ONLY place a row can be created
# =============================================================================

def test_confirm_with_no_pending_draft_touches_no_crud_and_no_persist(monkeypatch):
    async def fake_persist(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)

    state = {}
    resp = asyncio.run(chat._handle_style_draft_confirm({"style_draft": "yes"}, "conv-1", TENANT, [], state))
    assert "waiting" in resp.assistant_text.lower()


def test_confirm_no_discards_draft_without_any_write(monkeypatch):
    async def fake_persist(*a, **k):
        pass

    async def boom_create(*a, **k):
        raise AssertionError("must not create a row on 'no'")

    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(visual_styles, "create_visual_style", boom_create)

    state = {"pending_style_draft": {"name": "Ghibli Dream", "look": "Soft pastel."}}
    resp = asyncio.run(chat._handle_style_draft_confirm({"style_draft": "no"}, "conv-1", TENANT, [], state))
    assert "didn't save" in resp.assistant_text.lower()
    assert "pending_style_draft" not in state  # cleared either way — no stale re-confirm


def test_confirm_yes_creates_through_the_same_crud_write_exactly_once(monkeypatch):
    calls = []

    async def fake_persist(*a, **k):
        pass

    async def fake_create(req, tenant_id=None):
        calls.append((req, tenant_id))
        return types.SimpleNamespace(name="Ghibli Dream")

    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(visual_styles, "create_visual_style", fake_create)

    state = {"pending_style_draft": {"name": "Ghibli Dream", "look": "Soft pastel watercolor summer light."}}
    resp = asyncio.run(chat._handle_style_draft_confirm({"style_draft": "yes"}, "conv-1", TENANT, [], state))

    assert len(calls) == 1
    req, tenant_id = calls[0]
    assert tenant_id == TENANT
    assert req.name == "Ghibli Dream"
    assert req.style_profile == {"prompt_prefix": "Soft pastel watercolor summer light."}
    assert "Ghibli Dream" in resp.assistant_text
    assert "pending_style_draft" not in state


def test_confirm_yes_fails_soft_when_the_crud_raises(monkeypatch):
    async def fake_persist(*a, **k):
        pass

    async def boom_create(*a, **k):
        raise RuntimeError("db is down")

    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(visual_styles, "create_visual_style", boom_create)

    state = {"pending_style_draft": {"name": "Ghibli Dream", "look": "Soft pastel."}}
    resp = asyncio.run(chat._handle_style_draft_confirm({"style_draft": "yes"}, "conv-1", TENANT, [], state))
    assert "snag" in resp.assistant_text.lower()


# =============================================================================
# 6. Source-lock: chat_turn intercepts style_draft BEFORE the normal intake
#    turn hands the selection to the LLM
# =============================================================================

def test_chat_turn_source_intercepts_style_draft_before_intake():
    src = inspect.getsource(chat.chat_turn)
    assert '"style_draft" in body.selections' in src
    assert 'state.get("pending_style_draft")' in src
    assert "_handle_style_draft_confirm(" in src
    # The intercept must appear textually before the normal intake turn's
    # "user_parts" assembly (step 4) — proves it short-circuits, not just
    # that both exist somewhere in the function.
    assert src.index('_handle_style_draft_confirm(') < src.index("user_parts: list[str] = []")


# =============================================================================
# 7. _visual_styles_brief — real rows, fail-soft, wired into both entry points
# =============================================================================

def test_visual_styles_brief_real_rows_tags_the_active_one(monkeypatch):
    async def fake_get_project_id(tenant_id):
        return PROJECT

    async def fake_fetch_all(query, *args):
        assert "visual_styles" in query
        assert args == (PROJECT,)
        return [
            {"name": "Ghibli Dream", "style_profile": {"prompt_prefix": "Soft pastel watercolor."}, "is_active": True},
            {"name": "Neon Noir", "style_profile": {"prompt_prefix": "High-contrast neon rain."}, "is_active": False},
        ]

    monkeypatch.setattr(visual_styles, "_get_project_id", fake_get_project_id)
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)

    brief = asyncio.run(chat._visual_styles_brief(TENANT))
    assert "YOUR SAVED STYLES" in brief
    assert '"Ghibli Dream" (their current default): Soft pastel watercolor.' in brief
    assert '"Neon Noir": High-contrast neon rain.' in brief


def test_visual_styles_brief_empty_library_is_blank_not_a_fallback(monkeypatch):
    async def fake_get_project_id(tenant_id):
        return PROJECT

    async def fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(visual_styles, "_get_project_id", fake_get_project_id)
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    assert asyncio.run(chat._visual_styles_brief(TENANT)) == ""


def test_visual_styles_brief_fails_soft_on_db_error(monkeypatch):
    async def fake_get_project_id(tenant_id):
        raise RuntimeError("db is down")

    monkeypatch.setattr(visual_styles, "_get_project_id", fake_get_project_id)
    assert asyncio.run(chat._visual_styles_brief(TENANT)) == ""


def test_visual_styles_brief_wired_into_both_producer_entry_points():
    assert "_visual_styles_brief(tenant_id)" in inspect.getsource(chat._seed_producer)
    assert "_visual_styles_brief(tenant_id)" in inspect.getsource(chat.chat_turn)
