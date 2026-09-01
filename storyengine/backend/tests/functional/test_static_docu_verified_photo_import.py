"""Machine documentaries reuse their already-verified roster photographs."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import static_docu  # noqa: E402


@pytest.mark.asyncio
async def test_complete_verified_roster_imports_one_real_photo_per_scene(monkeypatch):
    scenes = [{"scene": 1, "scene_text": "one"}, {"scene": 2, "scene_text": "two"}]
    roster = [{"name": "CV-1 USS Langley"}, {"name": "CV-2 USS Lexington"}]
    writes = []

    async def fake_fetch_one(query, *args):
        assert "static_reference_cache" in query
        key = args[1]
        return {
            "hosted_url": f"https://media.example/{key}.jpg",
            "source_url": f"https://source.example/{key}",
        }

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "OK"

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)

    result = await static_docu._import_verified_roster_photos(
        "video-1", "tenant-1", "Carrier Video", "16:9", scenes, roster
    )

    assert result == {"status": "completed", "views_generated": 2, "segments_ready": 2}
    assert "DELETE FROM assets" in writes[0][0]
    inserts = [entry for entry in writes if "INSERT INTO assets" in entry[0]]
    assert len(inserts) == 2
    captions = [json.loads(entry[1][-1]) for entry in inserts]
    assert [c["title"] for c in captions] == ["CV-1 USS Langley", "CV-2 USS Lexington"]
    assert all(c["historical_reference"] is True for c in captions)
    assert all(c["target_views"] == 1 and c["minimum_views"] == 1 for c in captions)


@pytest.mark.asyncio
async def test_partial_verified_roster_does_not_mutate_assets(monkeypatch):
    scenes = [{"scene": 1, "scene_text": "one"}, {"scene": 2, "scene_text": "two"}]
    roster = [{"name": "CV-1 USS Langley"}, {"name": "CV-2 USS Lexington"}]
    writes = []

    async def fake_fetch_one(_query, *args):
        if args[1] == static_docu._machine_key("CV-1 USS Langley"):
            return {"hosted_url": "https://media.example/langley.jpg", "source_url": "source"}
        return None

    async def fake_execute(query, *args):
        writes.append((query, args))

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)

    result = await static_docu._import_verified_roster_photos(
        "video-1", "tenant-1", "Carrier Video", "16:9", scenes, roster
    )

    assert result is None
    assert writes == []
