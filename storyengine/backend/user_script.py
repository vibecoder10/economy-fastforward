"""Creator-supplied scripts ("use this script for a video").

Takes the creator's own script text (a dropped PDF, pasted text, a queue item)
and installs it on a video VERBATIM: split into scenes, persisted exactly the
way the modeled-script path persists generated scripts (videos.script + one
scripts row per scene + dialogue tagging), and marked script_source =
'user_supplied' so run_script skips generation and nothing second-guesses
their words — no retention grading, no factual gate. The creator's word is
final.
"""

from __future__ import annotations

import json
import logging
import re

from database import execute, fetch_one

logger = logging.getLogger(__name__)

# Matches the modeled path's per-scene narration size so voice pacing and the
# downstream per-scene machinery see familiar scene lengths (~45-60s spoken).
TARGET_WORDS_PER_SCENE = 120
# Same Kie-roster voice default the modeled path stamps on scripts rows.
DEFAULT_VOICE_ID = "1SM7GgM6IMuvQlz2BwM3"


def split_scenes(text: str) -> list[dict]:
    """[{"scene", "text"}] from raw script text. Honors explicit @@@SCENE n@@@
    markers (same sentinel contract as generated scripts); otherwise groups
    paragraphs into scenes of ~TARGET_WORDS_PER_SCENE words. Also treats
    'SCENE 1' / 'Scene 2:' heading lines as scene breaks."""
    from pipeline_executor import PipelineExecutor

    text = (text or "").strip()
    if not text:
        return []
    if re.search(r"@@@\s*SCENE\s*\d+\s*@@@", text, re.IGNORECASE):
        return PipelineExecutor._parse_modeled_scenes(text)

    # 'SCENE n' heading lines -> convert to sentinel markers and reuse the parser.
    headed = re.sub(
        r"(?mi)^\s*(?:SCENE|ACT)\s+(\d+)\s*[:.\-]?\s*$", r"@@@SCENE \1@@@", text
    )
    if "@@@SCENE" in headed:
        scenes = PipelineExecutor._parse_modeled_scenes(headed)
        if scenes:
            return scenes

    # Paragraph grouping fallback.
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    scenes, cur, cur_words = [], [], 0
    for p in paras:
        cur.append(p)
        cur_words += len(p.split())
        if cur_words >= TARGET_WORDS_PER_SCENE:
            scenes.append({"scene": len(scenes) + 1, "text": "\n\n".join(cur)})
            cur, cur_words = [], 0
    if cur:
        scenes.append({"scene": len(scenes) + 1, "text": "\n\n".join(cur)})
    return scenes


async def set_user_script(tenant_id, video_id: str, text: str) -> dict:
    """Install the creator's script on a video verbatim. Returns
    {"scenes": n, "status": <new video status>}. Raises ValueError on
    unusable input or a missing video."""
    video = await fetch_one(
        "SELECT * FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise ValueError("Video not found")
    scenes = split_scenes(text)
    if not scenes:
        raise ValueError("No usable script text")

    from pipeline_executor import PipelineExecutor

    full_script = "\n\n".join(s["text"].strip() for s in scenes)
    new_status = PipelineExecutor._skip_disabled_next(dict(video), "ready_for_voice")
    await execute(
        """UPDATE videos SET script = $1, script_source = 'user_supplied',
               script_validation = $2, status = $3, updated_at = now()
           WHERE id = $4 AND tenant_id = $5""",
        full_script,
        json.dumps({"passed": True, "checks": [
            {"name": "user_supplied", "passed": True,
             "detail": "Creator-supplied script used verbatim — generation, grading, and factual gates skipped"}]}),
        new_status, video_id, tenant_id,
    )
    await execute("DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2", video_id, tenant_id)
    for i, scene in enumerate(scenes, start=1):
        await execute(
            """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
               VALUES ($1, $2, $3, $4, $5, 'Create', $6)""",
            tenant_id, video_id, i, scene["text"].strip(),
            video.get("video_title"), DEFAULT_VOICE_ID,
        )

    # Same unattended dialogue tagging every script path gets; best-effort.
    try:
        from dialogue_intelligence import tag_video_dialogue
        await tag_video_dialogue(video_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[user_script] dialogue tagging failed for %s: %s", video_id, str(e)[:200])

    return {"scenes": len(scenes), "status": new_status}
