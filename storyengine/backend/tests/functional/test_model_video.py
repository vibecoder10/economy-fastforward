"""Functional tests for the Model A Video flow (routes/model_video.py).

Runs without a DB or network: routes.pipeline / routes.niche / vault /
distillation.distiller are stubbed via sys.modules (same pattern as the
prompt-override wiring tests), and database/Claude helpers are monkeypatched
on the module. Proves the background task's stage progression, persistence
calls, and graceful fallbacks.

Run:  python3 tests/functional/test_model_video.py   (from storyengine/backend)
"""

import asyncio
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── sys.modules stubs (must land before importing the module under test) ──

def _install_stubs():
    statuses = []

    fake_pipeline = types.ModuleType("routes.pipeline")
    def _set_task_status(video_id, status, message=None, error=None, *, tenant_id, task_type="pipeline"):
        # Mimic the REAL funnel: routes/pipeline.py humanizes failure errors
        # at the write boundary. Using the real helper here proves the
        # user_facing() passthrough survives end-to-end.
        if status == "failed" and (error or message):
            from error_utils import humanize_error
            error = humanize_error(error or message)
        statuses.append({"status": status, "message": message, "error": error, "task_type": task_type})
    def _get_task_status(video_id, tenant_id):
        return None
    def _clear_task_status(video_id, tenant_id):
        pass
    fake_pipeline._set_task_status = _set_task_status
    fake_pipeline._get_task_status = _get_task_status
    fake_pipeline._clear_task_status = _clear_task_status
    sys.modules["routes.pipeline"] = fake_pipeline

    fake_niche = types.ModuleType("routes.niche")
    fake_niche._extract_video_info = None  # set per-test
    sys.modules["routes.niche"] = fake_niche

    # Configurable per-test vault: keys present for the tenant
    fake_vault = types.ModuleType("vault")
    fake_vault.SECRETS = {"kie_ai_api_key": "kie-test-key"}
    async def get_secret(name, tenant_id=None):
        return fake_vault.SECRETS.get(name)
    fake_vault.get_secret = get_secret
    sys.modules["vault"] = fake_vault

    # NOTE: distillation.distiller is imported for real (it only needs json/httpx)
    # — model_video uses its FULL_VIDEO_DNA_PROMPT constant but routes the call
    # through its own provider-aware _call_claude, which tests patch.
    return statuses


STATUSES = _install_stubs()

import routes.model_video as mv  # noqa: E402


REF_INFO = {
    "video_id": "dQw4w9WgXcQ",
    "title": "Why The Dollar Empire Is Cracking",
    "channel": "EconWatch",
    "channel_url": "https://youtube.com/@econwatch",
    "views": 1_200_000,
    "likes": 40_000,
    "comment_count": 3_000,
    "channel_subscriber_count": 900_000,
    "like_ratio": 0.033,
    "views_per_sub_ratio": 1.3,
    "published_day_of_week": 2,
    "published_hour": 15,
    "has_chapters": True,
    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "transcript": "The dollar has ruled for 80 years. But three cracks are spreading...",
    "duration_seconds": 900,
    "description": "A deep dive into reserve currency mechanics.",
    "published_at": "2026-05-01",
}

VALID_PACK = {
    "selected_title": "The Quiet Currency War Nobody Is Pricing In",
    "title_options": [f"Option {i}" for i in range(1, 6)],
    "angle_thesis": "A fresh angle on FX power shifts, distinct from the reference.",
    "research_brief": "- Find BIS settlement data\n- Map petroyuan deals",
    "script_guidance": "Open with a mystery hook, then 4 escalating acts.",
    "visual_style_brief": "Dark cinematic macro-finance look, 35mm, teal/amber.",
    "thumbnail_prompt": "Split-lit central banker silhouette before a cracked dollar seal.",
    "image_dna": "Photorealistic macro-finance noir: 35mm, Rembrandt lighting, teal/amber palette, recurring melting-coin motif.",
    "motion_dna": "Slow push-ins and lateral drifts, 5-8s clips, atmospheric particulate, no whip pans.",
    "thumbnail_dna": "High-contrast face-plus-object composition, alarmed expression left third, single bold color block.",
    "negative_prompts": ["no text overlays", "no watermarks"],
    "scene_concepts": [
        {
            "concept": f"Scene {i} beat",
            "image_prompt": f"Cinematic image prompt {i} with subject, environment, camera.",
            "video_prompt": f"Slow push-in with drifting atmosphere, beat {i}.",
        }
        for i in range(1, 9)
    ],
}


def _patch_db_and_claude(pack=VALID_PACK, profile_extra=None):
    executed = []

    async def fake_execute(query, *args):
        executed.append((" ".join(query.split()), args))
        return "UPDATE 1"

    async def fake_fetch_one(query, *args):
        if "channel_profiles" in query:
            row = {
                "channel_name": "Ryan's Channel",
                "niche": "macro economics",
                "target_audience": "curious investors",
                "style_description": "calm, authoritative, story-first",
                "google_drive_refresh_token": None,
                "google_drive_folder_id": None,
            }
            row.update(profile_extra or {})
            return row
        return None

    calls = []

    async def fake_call_claude(prompt, creds, tier="smart", max_tokens=6000):
        calls.append({"provider": creds["provider"], "tier": tier})
        if tier == "fast":  # DNA distillation pass
            return json.dumps({
                "summary": "Reference works via mystery hook + escalating stakes.",
                "hook_dna": {"type": "mystery_question"},
            })
        return json.dumps(pack)

    mv.execute = fake_execute
    mv.fetch_one = fake_fetch_one
    mv._call_claude = fake_call_claude
    return executed, calls


def _run(coro):
    """Run the task with asyncio.sleep neutered (the finally-block waits 45s)."""
    real_sleep = asyncio.sleep
    async def fast_sleep(_seconds):
        await real_sleep(0)
    asyncio.sleep = fast_sleep
    try:
        asyncio.run(coro)
    finally:
        asyncio.sleep = real_sleep


def test_url_parsing():
    cases = {
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=10": "dQw4w9WgXcQ",
        "https://www.youtube.com/watch?list=PL12&v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/abcDEF12345": "abcDEF12345",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://vimeo.com/12345": None,
        "not a url": None,
        "": None,
    }
    for url, want in cases.items():
        got = mv._parse_youtube_id(url)
        assert got == want, f"{url!r}: got {got!r}, want {want!r}"
    print("PASS test_url_parsing")


def test_happy_path_persists_everything():
    STATUSES.clear()
    sys.modules["vault"].SECRETS = {"kie_ai_api_key": "kie-test-key"}
    sys.modules["routes.niche"]._extract_video_info = lambda vid: dict(REF_INFO)
    executed, claude_calls = _patch_db_and_claude()

    _run(mv._run_modeling("tenant-1", "video-1", "dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"))

    final = STATUSES[-1]
    assert final["status"] == "completed", STATUSES
    assert VALID_PACK["selected_title"] in (final["message"] or ""), final
    assert all(s["task_type"] == "model_video" for s in STATUSES)
    # Stage messages progressed
    messages = [s["message"] for s in STATUSES if s["status"] == "running"]
    assert any("Fetching" in (m or "") for m in messages)
    assert any("Analyzing" in (m or "") for m in messages)
    assert any("Creating" in (m or "") for m in messages)

    video_updates = [(q, a) for q, a in executed if q.startswith("UPDATE videos SET video_title")]
    assert len(video_updates) == 1, [q[:60] for q, _ in executed]
    uq, ua = video_updates[0]
    # Modeled DNA must land in the pipeline's steering columns so downstream
    # clicks (script/images/thumbnail/clips) actually generate "modeled" output
    assert "image_style_override" in uq and "thumbnail_style_override" in uq and "video_motion_system_prompt" in uq
    flat = " | ".join(str(x) for x in ua)
    assert "macro-finance noir" in flat, "image_dna not persisted"
    assert "push-ins" in flat, "motion_dna not persisted"
    assert "alarmed expression" in flat, "thumbnail_dna not persisted"
    assert "no text overlays" in flat, "negative prompts not folded into image DNA"
    asset_inserts = [(q, a) for q, a in executed if "INSERT INTO assets" in q]
    assert len(asset_inserts) == 8, len(asset_inserts)
    assert all("'modeled'" in q for q, _ in asset_inserts)
    comp_upserts = [q for q, a in executed if "INSERT INTO competitor_videos" in q]
    assert len(comp_upserts) == 1 and "ON CONFLICT (tenant_id, video_id)" in comp_upserts[0]
    # Retry path clears prior modeled prompt rows first
    assert any(q.startswith("DELETE FROM assets") for q, _ in executed)
    # Kie.ai is the preferred Claude provider: DNA on fast tier, pack on smart tier
    assert {"provider": "kie", "tier": "fast"} in claude_calls, claude_calls
    assert {"provider": "kie", "tier": "smart"} in claude_calls, claude_calls
    print("PASS test_happy_path_persists_everything")


def test_anthropic_fallback_when_no_kie_key():
    STATUSES.clear()
    sys.modules["vault"].SECRETS = {"anthropic_api_key": "sk-ant-test"}
    sys.modules["routes.niche"]._extract_video_info = lambda vid: dict(REF_INFO)
    _, claude_calls = _patch_db_and_claude()

    _run(mv._run_modeling("tenant-1", "video-6", "dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"))

    assert STATUSES[-1]["status"] == "completed", STATUSES
    assert all(c["provider"] == "anthropic" for c in claude_calls), claude_calls
    sys.modules["vault"].SECRETS = {"kie_ai_api_key": "kie-test-key"}
    print("PASS test_anthropic_fallback_when_no_kie_key")


def test_no_keys_fails_with_kie_instruction():
    STATUSES.clear()
    sys.modules["vault"].SECRETS = {}
    sys.modules["routes.niche"]._extract_video_info = lambda vid: dict(REF_INFO)
    _patch_db_and_claude()

    _run(mv._run_modeling("tenant-1", "video-7", "dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"))

    final = STATUSES[-1]
    assert final["status"] == "failed", STATUSES
    assert "Kie.ai API key" in (final["error"] or ""), final
    sys.modules["vault"].SECRETS = {"kie_ai_api_key": "kie-test-key"}
    print("PASS test_no_keys_fails_with_kie_instruction")


def test_transcript_missing_falls_back_with_blocker():
    STATUSES.clear()
    info = dict(REF_INFO)
    info["transcript"] = None
    sys.modules["routes.niche"]._extract_video_info = lambda vid: info
    _patch_db_and_claude()

    _run(mv._run_modeling("tenant-1", "video-2", "dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"))

    final = STATUSES[-1]
    assert final["status"] == "completed", STATUSES
    assert "Transcript wasn't available" in (final["message"] or ""), final
    print("PASS test_transcript_missing_falls_back_with_blocker")


def test_unreadable_video_fails_friendly():
    STATUSES.clear()
    sys.modules["routes.niche"]._extract_video_info = lambda vid: None
    async def no_oembed(youtube_id):
        return None
    mv._oembed_fallback = no_oembed
    _patch_db_and_claude()

    _run(mv._run_modeling("tenant-1", "video-3", "dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"))

    final = STATUSES[-1]
    assert final["status"] == "failed", STATUSES
    # Friendly copy must survive the humanize funnel (user_facing passthrough)
    assert "couldn't read that video" in (final["error"] or ""), final
    assert "[[user-facing]]" not in (final["error"] or ""), final
    print("PASS test_unreadable_video_fails_friendly")


def test_bot_blocked_extraction_uses_oembed_fallback():
    STATUSES.clear()
    sys.modules["routes.niche"]._extract_video_info = lambda vid: None  # yt-dlp blocked
    async def fake_oembed(youtube_id):
        return {
            "video_id": youtube_id,
            "title": "Why The Dollar Empire Is Cracking",
            "channel": "EconWatch",
            "channel_url": "https://youtube.com/@econwatch",
            "thumbnail_url": f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg",
            "transcript": None,
            "description": "",
        }
    mv._oembed_fallback = fake_oembed
    executed, _ = _patch_db_and_claude()

    _run(mv._run_modeling("tenant-1", "video-5", "dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"))

    final = STATUSES[-1]
    assert final["status"] == "completed", STATUSES
    assert "limited full video access" in (final["message"] or ""), final
    assert len([q for q, a in executed if "INSERT INTO assets" in q]) == 8
    print("PASS test_bot_blocked_extraction_uses_oembed_fallback")


def test_bad_pack_fails_without_raw_leak():
    STATUSES.clear()
    sys.modules["routes.niche"]._extract_video_info = lambda vid: dict(REF_INFO)
    _patch_db_and_claude(pack={"selected_title": "x"})  # missing required keys

    _run(mv._run_modeling("tenant-1", "video-4", "dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"))

    final = STATUSES[-1]
    assert final["status"] == "failed", STATUSES
    err = final["error"] or ""
    assert "Modeled pack missing keys" not in err, f"raw error leaked: {err}"
    print("PASS test_bad_pack_fails_without_raw_leak")


if __name__ == "__main__":
    test_url_parsing()
    test_happy_path_persists_everything()
    test_transcript_missing_falls_back_with_blocker()
    test_unreadable_video_fails_friendly()
    test_bot_blocked_extraction_uses_oembed_fallback()
    test_bad_pack_fails_without_raw_leak()
    test_anthropic_fallback_when_no_kie_key()
    test_no_keys_fails_with_kie_instruction()
    print("\nALL MODEL-VIDEO TESTS PASSED (8/8)")
