"""Focused regression tests for static-documentary thumbnail packaging."""

import asyncio
import json
import os
import sys


_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe  # noqa: E402
from pipeline_executor import (  # noqa: E402
    PipelineExecutor,
    _select_static_thumbnail_subject,
    _usable_thumbnail_copy,
)


def _asset(scene, title, sub, url, *, specs=None, role="three_quarter", status="done"):
    return {
        "scene": scene,
        "image_index": 1,
        "image_url": url,
        "status": status,
        "generation_method": "static_docu",
        "caption": json.dumps({
            "title": title,
            "sub": sub,
            "specs": specs or [],
            "view_role": role,
        }),
    }


def test_selects_strongest_locked_roster_subject_and_approved_view():
    roster = [
        {"designation": "CV-1", "name": "USS Langley"},
        {"designation": "CVA-62", "name": "USS Independence"},
        {"designation": "CVN-78", "name": "USS Gerald R. Ford"},
    ]
    rows = [
        _asset(1, "CV-1 USS Langley", "Converted • 1 ship • 1922", "https://img/langley.png"),
        _asset(
            18,
            "CVA-62 USS Independence",
            "US Navy • 1959–1998",
            "https://img/independence.png",
            specs=["Scrapping completed at Brownsville in 2018"],
        ),
        _asset(
            24,
            "CVN-78 USS Gerald R. Ford",
            "Production • 1 ship commissioned • 2017",
            "https://img/ford-side.png",
            role="side_profile",
        ),
        _asset(
            24,
            "CVN-78 USS Gerald R. Ford",
            "Production • 1 ship commissioned • 2017",
            "https://img/ford-three-quarter.png",
            role="three_quarter",
        ),
        _asset(
            24,
            "CVN-78 USS Gerald R. Ford",
            "Production • 1 ship commissioned • 2017",
            "https://img/rejected.png",
            status="qa_rejected",
        ),
        _asset(25, "CVA-58 United States", "Never-built design", "https://img/unlocked.png"),
    ]

    chosen = _select_static_thumbnail_subject(rows, roster)

    assert chosen["title"] == "CVN-78 USS Gerald R. Ford"
    assert chosen["image_url"] == "https://img/ford-three-quarter.png"


def test_every_built_series_gets_grammatical_title_condensation():
    title = "Every US Aircraft Carrier Ever Built (2026)"

    expected = "US AIRCRAFT CARRIER EVER BUILT"
    assert _usable_thumbnail_copy(title, "EVERY BUILT") == expected
    assert _usable_thumbnail_copy(title, "EVER BUILT") == expected
    assert _usable_thumbnail_copy(title, title) == expected
    assert _usable_thumbnail_copy(title, "NAVAL GIANTS") == expected


def test_non_series_copy_stays_title_related_instead_of_generic_slogan():
    title = "How the Iowa Class Changed Naval Gunnery"

    assert _usable_thumbnail_copy(
        title, "NAVAL GIANTS"
    ) == "NAVAL GIANTS"
    assert _usable_thumbnail_copy(title, "THE ONE TO BEAT") == "IOWA CLASS NAVAL GUNNERY"


def test_cached_langley_spec_is_rebuilt_for_selected_ford(monkeypatch):
    stale = {
        "text": {"primary_text": {"content": "EVERY"}},
        "scene": {"focal_point": "USS Langley CV-1"},
        "objects": [{"object": "USS Langley CV-1", "description": "early carrier"}],
        "prompt": "Studio thumbnail of USS Langley CV-1 with the word EVERY",
        "negative_prompt": "",
    }
    video = {
        "video_title": "\u2060Every US Aircraft Carrier Ever Built (2026)",
        "thumbnail_prompt": json.dumps(stale),
        "aspect_ratio": "16:9",
        "research_payload": {"unit_roster": [
            {"designation": "CV-1", "name": "USS Langley"},
            {"designation": "CV-66", "name": "USS America"},
            {"designation": "CVN-78", "name": "USS Gerald R. Ford"},
        ]},
    }
    rows = [
        _asset(1, "CV-1 USS Langley", "Converted • 1 ship • 1922", "https://img/langley.png"),
        _asset(
            20, "CV-66 USS America", "U.S. Navy • 1965–1996",
            "https://img/america-three-quarter.png", role="three_quarter",
        ),
        _asset(
            24, "USS Gerald R. Ford (CVN-78)", "U.S. Navy • 2017–present",
            "https://img/ford-three-quarter.png", role="three_quarter",
        ),
    ]
    stored = {}
    generated = {}

    async def fake_fetch_one(query, *args):
        if "FROM channel_videos" in query:
            return {"thumbnail_url": "https://img/channel-top.png"}
        if "thumbnail_blueprint" in query:
            return {"bp": '{"layout":"subject right, headline left"}'}
        if "thumbnail_style" in query:
            return {"ts": {}}
        return None

    async def fake_fetch_all(query, *args):
        return rows if "FROM assets" in query else []

    async def fake_execute(query, *args):
        if "UPDATE videos SET thumbnail_url" in query:
            stored["prompt"] = json.loads(args[1])

    async def fake_transform(creds, blueprint, consensus, hexbg, title, subjects):
        assert "USS Gerald R. Ford (CVN-78)" in subjects
        return None

    class FakeImageClient:
        async def generate_thumbnail_gpt2(self, prompt, refs, **kwargs):
            generated.update({"prompt": prompt, "refs": refs})
            return {"url": "https://img/new-thumb.png"}

    async def fake_creds(_tenant):
        return {"api_key": "test"}

    async def noop(*args, **kwargs):
        return None

    import routes.model_video as model_video
    monkeypatch.setattr(model_video, "_resolve_claude_creds", fake_creds)
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "record_ledger_entry", noop)

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor._pipeline = type("Pipeline", (), {"image_client": FakeImageClient()})()
    executor._measure_channel_thumb_bg = noop
    executor._transform_channel_thumbnail_spec = fake_transform
    executor._log_activity = noop
    executor._persist_url = lambda *args, **kwargs: None

    async def persist(*args, **kwargs):
        return "https://storage/new-thumb.png"

    executor._persist_url = persist
    result = asyncio.run(executor._run_channel_formula_thumbnail("video-1", video))

    assert result["status"] == "completed"
    assert stored["prompt"]["scene"]["focal_point"] == "USS Gerald R. Ford (CVN-78)"
    assert stored["prompt"]["text"]["primary_text"]["content"] == "US AIRCRAFT CARRIER EVER BUILT"
    assert generated["refs"] == ["https://img/ford-three-quarter.png"]
    assert "US AIRCRAFT CARRIER EVER BUILT" in generated["prompt"]
    assert "USS Langley" not in generated["prompt"]
    assert '"EVERY"' not in generated["prompt"]
