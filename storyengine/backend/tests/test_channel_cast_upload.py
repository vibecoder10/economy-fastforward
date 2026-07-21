"""Tests for POST /api/projects/current/cast/upload — add a saved-cast
character by uploading the creator's own image (drag-and-drop or
click-to-pick in Settings' Channel cast card). Sibling to the AI-generated
`/current/cast/generate` endpoint in routes/projects.py, minus the Kie call.

TestClient + dependency_overrides + monkeypatched module-level fetch_one/
execute, same convention as tests/test_autopilot_dial_route.py.

Run:  cd storyengine/backend && ./venv/bin/python -m pytest tests/test_channel_cast_upload.py -q
"""
import json
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_tenant_id
import routes.projects as rp
import storage

TENANT = "tenant-cast-upload"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # not a real PNG, just non-empty bytes


class FakeProjectDB:
    """Minimal fake for the two queries the upload endpoint touches:
    the project lookup (_get_or_create_project) and the cast refs
    read/write around it."""

    def __init__(self, initial_refs=None):
        self.project_id = "proj-1"
        self.refs = initial_refs or []

    async def fetch_one(self, query, *args):
        if "FROM projects WHERE tenant_id" in query:
            return {"id": self.project_id}
        if "SELECT character_references FROM projects WHERE id" in query:
            return {"character_references": json.dumps(self.refs)}
        return None

    async def execute(self, query, *args):
        if "UPDATE projects SET character_references" in query:
            self.refs = json.loads(args[0])
        return None


def _build_client(monkeypatch, db: FakeProjectDB, *, upload_error=None):
    monkeypatch.setattr(rp, "fetch_one", db.fetch_one)
    monkeypatch.setattr(rp, "execute", db.execute)

    async def fake_upload_bytes(data, path, content_type, tenant_id):
        if upload_error:
            raise upload_error
        return f"https://drive.google.com/uc?id=fake-{path.rsplit('/', 1)[-1]}"

    monkeypatch.setattr(storage, "upload_bytes", fake_upload_bytes)

    app = FastAPI()
    app.include_router(rp.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_upload_adds_new_cast_member(monkeypatch):
    db = FakeProjectDB()
    client = _build_client(monkeypatch, db)

    resp = client.post(
        "/api/projects/current/cast/upload",
        files={"file": ("abuela.png", PNG_BYTES, "image/png")},
        data={"name": "Abuela Rosa"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "added"
    names = [c["name"] for c in body["characters"]]
    assert names == ["Abuela Rosa"]
    added = body["characters"][0]
    assert added["reference_url"].startswith("https://drive.google.com/uc?id=")
    assert added["always"] is True
    # persisted into the fake project row too, not just the response
    assert db.refs == body["characters"]


def test_upload_defaults_name_when_omitted(monkeypatch):
    db = FakeProjectDB()
    client = _build_client(monkeypatch, db)

    resp = client.post(
        "/api/projects/current/cast/upload",
        files={"file": ("sheet.jpg", PNG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    names = [c["name"] for c in resp.json()["characters"]]
    assert names == ["New Character"]


def test_upload_rejects_non_image_content_type(monkeypatch):
    db = FakeProjectDB()
    client = _build_client(monkeypatch, db)

    resp = client.post(
        "/api/projects/current/cast/upload",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        data={"name": "Not An Image"},
    )
    assert resp.status_code == 400
    assert "image" in resp.json()["detail"].lower()
    assert db.refs == []  # nothing written


def test_upload_rejects_oversized_file(monkeypatch):
    db = FakeProjectDB()
    client = _build_client(monkeypatch, db)

    oversized = b"\x00" * (15 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/projects/current/cast/upload",
        files={"file": ("huge.png", oversized, "image/png")},
        data={"name": "Too Big"},
    )
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()
    assert db.refs == []


def test_upload_replaces_existing_member_with_same_name(monkeypatch):
    db = FakeProjectDB(initial_refs=[
        {"name": "Abuela Rosa", "description": "old", "reference_url": "https://old", "always": False},
    ])
    client = _build_client(monkeypatch, db)

    resp = client.post(
        "/api/projects/current/cast/upload",
        files={"file": ("abuela2.png", PNG_BYTES, "image/png")},
        data={"name": "Abuela Rosa"},
    )
    assert resp.status_code == 200, resp.text
    chars = resp.json()["characters"]
    assert len(chars) == 1
    assert chars[0]["name"] == "Abuela Rosa"
    assert chars[0]["reference_url"] != "https://old"


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
