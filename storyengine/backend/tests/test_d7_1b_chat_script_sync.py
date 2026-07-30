"""D7-1b — the chat free-text script save must sync videos.script too.

THE GAP (D7-1's sweep, tasks/HANDOFF-D6-boardlaws.md): D7-1 fixed
update_scene_text (routes/videos.py, the plain PATCH .../scenes/{scene}/text
edit) to re-sync videos.script — the ONLY column routes/characters.py
`_extract_cast` reads when a video has no Story Bible yet. rewrite_scene_text
already did this too. But a THIRD writer of scripts.scene_text stayed
ungated: routes/chat.py `_apply_prompt_draft`'s "script" fallthrough branch
(the chat free-text script-save path a creator hits by typing a rewrite in
the Director chat) wrote scripts.scene_text directly with no videos.script
sync at all. A cast regenerated right after a chat-side script save could
still be built from the pre-save text.

Fix (routes/chat.py, in _apply_prompt_draft's "script" branch): after the
scene_text write, call routes.videos.sync_video_script(video_id, tenant_id)
— the same helper update_scene_text/rewrite_scene_text now share (extracted
D7-1b from their identical inline two-statement blocks, since a third
verbatim copy crossed the line into "extract it").

Local/no-spend: fakes execute/fetch_all against a tiny in-memory table, same
pattern tests/test_d7_1_script_sync.py already uses for update_scene_text.
Claude is stubbed for the _extract_cast half. Two module-level `execute`
references need patching (chat.py's own, for the scripts.scene_text write,
and routes.videos's, since sync_video_script is imported and called from
there) — both point at the SAME fake so they share one in-memory state.

STASH-PROOF: with routes/chat.py's sync_video_script call reverted (or
routes/videos.py's sync_video_script helper stashed), test_apply_prompt_
draft_script_save_syncs_videos_script fails a real assertion (the OLD text
is still what's in videos.script, so `NEW_TEXT in state["videos_script"]` is
False) and test_extract_cast_reads_the_edit_chat_script_save_just_synced
fails a real assertion too (the captured Claude prompt still contains
"lighthouse keeper", the pre-save text, instead of "Vasquez") — neither is
an import/collection-time error.
"""
import asyncio

import routes.chat as chat_route
import routes.videos as rv

OLD_TEXT = "The old paragraph about a lighthouse keeper."
NEW_TEXT = "A submarine captain named Vasquez discovers the reactor is failing."


def _make_fake_db(initial_scene_text: str, initial_videos_script: str):
    """In-memory scripts/videos tables good enough to drive
    _apply_prompt_draft's script branch exactly like the real SQL would:
    scripts.scene_text is the row store, videos.script (state["videos_script"])
    is the joined display/export copy _extract_cast reads."""
    state = {
        "scripts": {1: {"scene": 1, "location": "the garage", "scene_text": initial_scene_text}},
        "videos_script": initial_videos_script,
    }

    async def fake_execute(query, *args):
        q = query.strip()
        if q.startswith("UPDATE scripts SET scene_text=$1"):
            # chat.py's write: args = (text, video_id, scene, tenant_id)
            text, _video_id, scene, _tenant_id = args
            row = state["scripts"].get(scene)
            if row is None:
                return "UPDATE 0"
            row["scene_text"] = text
            return "UPDATE 1"
        if q.startswith("UPDATE videos SET script"):
            # sync_video_script's write: args = (video_id, tenant_id, full_text)
            _video_id, _tenant_id, full_text = args
            state["videos_script"] = full_text
            return "UPDATE 1"
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        # sync_video_script's re-fetch — return every tracked scene row.
        return [dict(r) for r in state["scripts"].values()]

    return state, fake_execute, fake_fetch_all


def test_apply_prompt_draft_script_save_syncs_videos_script(monkeypatch):
    """The core D7-1b fix: the chat script-save path must update
    videos.script, not just scripts.scene_text."""
    state, fake_execute, fake_fetch_all = _make_fake_db(OLD_TEXT, OLD_TEXT)
    monkeypatch.setattr(chat_route, "execute", fake_execute)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    draft = {"surface": "script", "draft": NEW_TEXT, "label": "Scene 1", "scene": 1}

    asyncio.run(chat_route._apply_prompt_draft("tenant-1", "video-1", draft, None))

    assert NEW_TEXT in state["videos_script"], (
        "the chat script-save path must sync videos.script — _extract_cast "
        "reads ONLY this column when there's no Story Bible yet"
    )
    assert "lighthouse keeper" not in state["videos_script"], (
        "the OLD text must not linger in videos.script after the chat save"
    )


def test_extract_cast_reads_the_edit_chat_script_save_just_synced(monkeypatch):
    """End-to-end proof: chain the chat script-save write into
    routes.characters._extract_cast's read, exactly as production wiring
    does it (chat script apply -> videos.script -> _get_video's SELECT ->
    _extract_cast's video.get("script"))."""
    state, fake_execute, fake_fetch_all = _make_fake_db(OLD_TEXT, OLD_TEXT)
    monkeypatch.setattr(chat_route, "execute", fake_execute)
    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    draft = {"surface": "script", "draft": NEW_TEXT, "label": "Scene 1", "scene": 1}
    asyncio.run(chat_route._apply_prompt_draft("tenant-1", "video-1", draft, None))

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
        "_extract_cast's script read must contain the edit the chat script "
        "save just made, not stale cached text"
    )
    assert "lighthouse keeper" not in captured["prompt"], (
        "the pre-save text must not still be what _extract_cast reads"
    )
    assert cast[0]["name"] == "Vasquez"
