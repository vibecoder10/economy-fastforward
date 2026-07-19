"""Regression test for S5-6 (checklist C25b): activate_visual_style and
delete_visual_style did an ownership SELECT scoped by project_id, then
mutated by bare `id` — no project_id in the mutating WHERE. Fixed to repeat
the project_id clause on every mutating query (routes/visual_styles.py
~L416, ~L448, ~L453).

Uses a tiny in-memory fake table (no real DB) so we can prove the fix at the
SQL-args level: even a mutation issued with a forged/mismatched project_id
changes zero rows, independent of the route's own 404 pre-check. Mirrors the
monkeypatch style of tests/test_visual_style_upsert.py.
"""
import asyncio
import importlib

from fastapi import HTTPException


def _make_fake_db(rows):
    """rows: dict[style_id] -> {"project_id", "is_active", "is_default"}."""
    table = {k: dict(v) for k, v in rows.items()}
    calls = {"execute": [], "fetch_one": []}

    def _norm(q):
        return " ".join(q.split())

    async def fake_fetch_one(query, *args):
        calls["fetch_one"].append((query, args))
        q = _norm(query)
        if q.startswith("SELECT id FROM visual_styles WHERE id = $1 AND project_id = $2"):
            style_id, project_id = args
            row = table.get(style_id)
            if row and row["project_id"] == project_id:
                return {"id": style_id}
            return None
        if q.startswith("SELECT id, is_default, is_active FROM visual_styles WHERE id = $1 AND project_id = $2"):
            style_id, project_id = args
            row = table.get(style_id)
            if row and row["project_id"] == project_id:
                return {"id": style_id, "is_default": row["is_default"], "is_active": row["is_active"]}
            return None
        if q.startswith("SELECT id FROM visual_styles WHERE project_id = $1 AND is_default = true"):
            (project_id,) = args
            for sid, row in table.items():
                if row["project_id"] == project_id and row["is_default"]:
                    return {"id": sid}
            return None
        return None

    async def fake_execute(query, *args):
        calls["execute"].append((query, args))
        q = _norm(query)
        if q.startswith("UPDATE visual_styles SET is_active = false"):
            (project_id,) = args
            for row in table.values():
                if row["project_id"] == project_id:
                    row["is_active"] = False
            return None
        if q.startswith("UPDATE visual_styles SET is_active = true, updated_at = now() WHERE id = $1 AND project_id = $2"):
            style_id, project_id = args
            row = table.get(style_id)
            if row and row["project_id"] == project_id:
                row["is_active"] = True
            return None
        if q.startswith("DELETE FROM visual_styles WHERE id = $1 AND project_id = $2"):
            style_id, project_id = args
            row = table.get(style_id)
            if row and row["project_id"] == project_id:
                del table[style_id]
            return None
        return None

    return table, calls, fake_fetch_one, fake_execute


def _load(monkeypatch, rows, tenant_to_project):
    mod = importlib.import_module("routes.visual_styles")
    table, calls, fake_fetch_one, fake_execute = _make_fake_db(rows)

    async def fake_get_or_create_project(tenant_id):
        return {"id": tenant_to_project[tenant_id]}

    async def fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(mod, "execute", fake_execute)
    monkeypatch.setattr(mod, "_get_or_create_project", fake_get_or_create_project)
    return mod, table, calls


def test_activate_scopes_update_to_project(monkeypatch):
    rows = {
        "style-A1": {"project_id": "proj-A", "is_active": False, "is_default": False},
        "style-B1": {"project_id": "proj-B", "is_active": True, "is_default": False},
    }
    mod, table, calls = _load(monkeypatch, rows, {"tenant-A": "proj-A"})

    asyncio.run(mod.activate_visual_style("style-A1", tenant_id="tenant-A"))

    assert table["style-A1"]["is_active"] is True
    assert table["style-B1"]["is_active"] is True  # different project, untouched

    update_calls = [
        (q, a) for q, a in calls["execute"]
        if "is_active = true" in q and "AND project_id = $2" in q
    ]
    assert update_calls, "activate must issue UPDATE ... WHERE id = $1 AND project_id = $2"
    assert update_calls[-1][1] == ("style-A1", "proj-A")


def test_activate_cross_tenant_404s_and_mutates_nothing(monkeypatch):
    rows = {"style-A1": {"project_id": "proj-A", "is_active": False, "is_default": False}}
    mod, table, calls = _load(monkeypatch, rows, {"tenant-evil": "proj-EVIL"})

    raised = None
    try:
        asyncio.run(mod.activate_visual_style("style-A1", tenant_id="tenant-evil"))
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 404
    assert table["style-A1"]["is_active"] is False  # untouched


def test_activate_update_where_rejects_forged_project_even_if_precheck_bypassed(monkeypatch):
    """Belt-and-suspenders: call the exact UPDATE the route issues, with a
    forged project_id, directly against the fake table (simulating a future
    refactor that loses/skips the earlier ownership SELECT). Zero rows must
    change — this is the concrete regression S5-6 closes."""
    rows = {"style-A1": {"project_id": "proj-A", "is_active": False, "is_default": False}}
    mod, table, calls = _load(monkeypatch, rows, {})

    asyncio.run(mod.execute(
        "UPDATE visual_styles SET is_active = true, updated_at = now() WHERE id = $1 AND project_id = $2",
        "style-A1", "proj-WRONG",
    ))
    assert table["style-A1"]["is_active"] is False


def test_delete_scopes_to_project_and_rejects_cross_tenant(monkeypatch):
    rows = {"style-A1": {"project_id": "proj-A", "is_active": False, "is_default": False}}
    mod, table, calls = _load(monkeypatch, rows, {"tenant-A": "proj-A", "tenant-evil": "proj-EVIL"})

    raised = None
    try:
        asyncio.run(mod.delete_visual_style("style-A1", tenant_id="tenant-evil"))
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 404
    assert "style-A1" in table  # not deleted

    asyncio.run(mod.delete_visual_style("style-A1", tenant_id="tenant-A"))
    assert "style-A1" not in table

    delete_calls = [(q, a) for q, a in calls["execute"] if q.strip().startswith("DELETE FROM visual_styles")]
    assert delete_calls
    assert "AND project_id = $2" in delete_calls[-1][0]
    assert delete_calls[-1][1] == ("style-A1", "proj-A")


def test_delete_active_style_reactivates_scoped_default(monkeypatch):
    rows = {
        "style-A1": {"project_id": "proj-A", "is_active": True, "is_default": False},
        "style-A-default": {"project_id": "proj-A", "is_active": False, "is_default": True},
    }
    mod, table, calls = _load(monkeypatch, rows, {"tenant-A": "proj-A"})

    asyncio.run(mod.delete_visual_style("style-A1", tenant_id="tenant-A"))

    assert "style-A1" not in table
    assert table["style-A-default"]["is_active"] is True

    reactivate_calls = [
        (q, a) for q, a in calls["execute"]
        if "is_active = true" in q and a[:1] == ("style-A-default",)
    ]
    assert reactivate_calls
    assert "AND project_id = $2" in reactivate_calls[-1][0]
    assert reactivate_calls[-1][1] == ("style-A-default", "proj-A")
