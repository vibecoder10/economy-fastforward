"""D7-1 — update_scene_text must sync videos.script, the same column
_extract_cast reads.

THE GAP (tasks/HANDOFF-D6-boardlaws.md "BIG FINDING"): routes/characters.py
`_get_video` selects `videos.script`, and `_extract_cast` reads
`video.get("script")` to build the cast when there's no Story Bible yet.
`rewrite_scene_text` and the Drive pull-sync path both keep `videos.script`
current after they touch `scripts.scene_text`. `update_scene_text` (the
plain PATCH .../scenes/{scene}/text edit) did NOT — it wrote
`scripts.scene_text` only. A cast/character build kicked off right after a
scene edit was therefore still built from the script's PRE-edit text: a real
production video shipped with characters that didn't match a script that
had already been rewritten.

Fix (routes/videos.py, in update_scene_text): after the scene_text write,
re-fetch every scene's text and push the joined result into
`videos.script` — the exact same two-statement sync `rewrite_scene_text`
already performs a little further down in the same file. Mirrors it
verbatim rather than inventing a second mechanism.

Local/no-spend: fakes execute/fetch_all against a tiny in-memory table,
same pattern tests/test_d6_3_story_law_s3.py already uses for this same
function. Claude is stubbed for the _extract_cast half.

STASH-PROOF: with backend/routes/videos.py's D7-1 sync block reverted,
test_update_scene_text_syncs_videos_script fails a real assertion (the OLD
text is still what's in videos.script, so `NEW_TEXT in state["videos_script"]`
is False) and
test_extract_cast_reads_the_edit_update_scene_text_just_synced fails a real
assertion too (the captured Claude prompt still contains "lighthouse
keeper", the pre-edit text, instead of "Vasquez") — neither is an
import/collection-time error.
"""
import asyncio

import routes.videos as rv
from models import SceneTextUpdate

OLD_TEXT = "The old paragraph about a lighthouse keeper."
NEW_TEXT = "A submarine captain named Vasquez discovers the reactor is failing."


def _make_fake_db(initial_scene_text: str, initial_videos_script: str):
    """In-memory scripts/videos tables good enough to drive
    update_scene_text exactly like the real SQL would: scripts.scene_text
    is the row store, videos.script (state["videos_script"]) is the joined
    display/export copy _extract_cast reads."""
    state = {
        "scripts": {1: {"scene": 1, "location": "the garage", "scene_text": initial_scene_text}},
        "videos_script": initial_videos_script,
    }

    async def fake_execute(query, *args):
        q = query.strip()
        if q.startswith("UPDATE scripts SET scene_text"):
            # args: (stored_text, video_id, scene, tenant_id, new_location)
            stored_text, _video_id, scene, _tenant_id, new_location = args
            row = state["scripts"].get(scene)
            if row is None:
                return "UPDATE 0"
            row["scene_text"] = stored_text
            if new_location is not None:
                row["location"] = new_location
            return "UPDATE 1"
        if q.startswith("UPDATE videos SET script"):
            # args: (video_id, tenant_id, full_script_text) — same order
            # rewrite_scene_text's identical sync call uses.
            _video_id, _tenant_id, full_text = args
            state["videos_script"] = full_text
            return "UPDATE 1"
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        # Both the D7-1 sync query and the pre-existing D6-3/D6-4 story-law
        # re-check query select the same {scene, location, scene_text}
        # shape — return every tracked scene row for either.
        return [dict(r) for r in state["scripts"].values()]

    return state, fake_execute, fake_fetch_all


def test_update_scene_text_syncs_videos_script(monkeypatch):
    """The core D7-1 fix: editing a scene must update videos.script, not
    just scripts.scene_text."""
    state, fake_execute, fake_fetch_all = _make_fake_db(OLD_TEXT, OLD_TEXT)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text=NEW_TEXT), tenant_id="tenant-1",
    ))

    assert NEW_TEXT in state["videos_script"], (
        "update_scene_text must sync videos.script with the edit — "
        "_extract_cast reads ONLY this column when there's no Story Bible yet"
    )
    assert "lighthouse keeper" not in state["videos_script"], (
        "the OLD text must not linger in videos.script after the edit"
    )


def test_extract_cast_reads_the_edit_update_scene_text_just_synced(monkeypatch):
    """End-to-end proof: chain update_scene_text's write into
    routes.characters._extract_cast's read, exactly as production wiring
    does it (PATCH .../scenes/{scene}/text -> videos.script -> _get_video's
    SELECT -> _extract_cast's video.get("script"))."""
    state, fake_execute, fake_fetch_all = _make_fake_db(OLD_TEXT, OLD_TEXT)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text=NEW_TEXT), tenant_id="tenant-1",
    ))

    # Simulate _get_video's SELECT re-reading the (now-synced) column.
    video = {"story_bible": None, "script": state["videos_script"], "tenant_id": None}

    import routes.characters as ch
    import routes.model_video as mv

    captured = {}

    async def fake_call_claude(prompt, creds, tier="smart", max_tokens=2000, image_url=None):
        captured["prompt"] = prompt
        return '{"characters": [{"name": "Vasquez", "description": "submarine captain"}]}'

    orig = mv._call_claude
    mv._call_claude = fake_call_claude
    try:
        cast = asyncio.run(ch._extract_cast(video, "key"))
    finally:
        mv._call_claude = orig

    assert "Vasquez" in captured["prompt"], (
        "_extract_cast's script read must contain the edit update_scene_text "
        "just made, not stale cached text"
    )
    assert "lighthouse keeper" not in captured["prompt"], (
        "the pre-edit text must not still be what _extract_cast reads"
    )
    assert cast[0]["name"] == "Vasquez"
