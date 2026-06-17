"""Unit tests for upsert_active_visual_style (no real DB — the asyncpg layer is
stubbed). Mirrors the monkeypatch style of test_identity_context.py."""
import asyncio
import json
import importlib


def _load(monkeypatch, existing_row):
    """Import the module and stub its DB calls; return (module, calls)."""
    mod = importlib.import_module("routes.visual_styles")
    calls = {"execute": [], "fetch_one": []}

    async def fake_fetch_one(query, *args):
        calls["fetch_one"].append((query, args))
        if "SELECT id FROM visual_styles" in query and "name" in query:
            return existing_row  # None = no match, dict = match
        return None

    async def fake_execute(query, *args):
        calls["execute"].append((query, args))
        return None

    monkeypatch.setattr(mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(mod, "execute", fake_execute)
    return mod, calls


def test_inserts_and_activates_when_absent(monkeypatch):
    mod, calls = _load(monkeypatch, existing_row=None)
    asyncio.run(mod.upsert_active_visual_style("proj-1", "Pixar 3D", "soft 3D Pixar CG"))
    qs = " ".join(q for q, _ in calls["execute"])
    assert "is_active = false" in qs
    assert "INSERT INTO visual_styles" in qs
    insert_args = [a for q, a in calls["execute"] if "INSERT" in q][0]
    assert any("soft 3D Pixar CG" in json.dumps(a) for a in insert_args)


def test_updates_existing_same_name(monkeypatch):
    mod, calls = _load(monkeypatch, existing_row={"id": "style-9"})
    asyncio.run(mod.upsert_active_visual_style("proj-1", "Pixar 3D", "new look"))
    qs = " ".join(q for q, _ in calls["execute"])
    assert "is_active = false" in qs
    assert "UPDATE visual_styles" in qs
    assert "INSERT INTO visual_styles" not in qs


def test_blank_look_is_noop(monkeypatch):
    mod, calls = _load(monkeypatch, existing_row=None)
    asyncio.run(mod.upsert_active_visual_style("proj-1", "X", "   "))
    assert calls["execute"] == []
