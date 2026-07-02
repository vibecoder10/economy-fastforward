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


def split_scenes_explicit(text: str) -> list[dict]:
    """Scenes the CREATOR marked: @@@SCENE n@@@ sentinels or 'SCENE 1' / 'ACT 2'
    heading lines. Empty list when the script carries no explicit breaks —
    explicit marks always win over any automatic splitting."""
    from pipeline_executor import PipelineExecutor

    text = (text or "").strip()
    if not text:
        return []
    if re.search(r"@@@\s*SCENE\s*\d+\s*@@@", text, re.IGNORECASE):
        return PipelineExecutor._parse_modeled_scenes(text)
    headed = re.sub(
        r"(?mi)^\s*(?:SCENE|ACT)\s+(\d+)\s*[:.\-]?\s*$", r"@@@SCENE \1@@@", text
    )
    if "@@@SCENE" in headed:
        return PipelineExecutor._parse_modeled_scenes(headed)
    return []


def split_scenes_paragraphs(text: str) -> list[dict]:
    """The dumb-but-safe fallback: group paragraphs into scenes of
    ~TARGET_WORDS_PER_SCENE words."""
    text = (text or "").strip()
    if not text:
        return []
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


def split_scenes(text: str) -> list[dict]:
    """Synchronous split: explicit creator marks, else paragraph grouping.
    (set_user_script additionally tries the semantic model split in between.)"""
    return split_scenes_explicit(text) or split_scenes_paragraphs(text)


# Semantic split only echoes the script back with markers, so cap the size it
# attempts (longer scripts fall back to paragraph grouping).
SEMANTIC_MAX_CHARS = 24_000


async def semantic_split(tenant_id, text: str) -> Optional[list[dict]]:
    """One model call inserts @@@SCENE n@@@ markers at natural beat boundaries
    (one machine / one story beat / one location per scene), guided by the
    channel's locked segmentation when there is one.

    VERBATIM-GUARDED: the script text after splitting must equal the original
    word for word (markers aside). If the model changed, dropped, or added
    ANYTHING, return None and let the caller fall back — an automatic split is
    never allowed to rewrite the creator's script."""
    text = (text or "").strip()
    if not text or len(text) > SEMANTIC_MAX_CHARS:
        return None
    try:
        from kie_unified import get_text_client_for_tenant
        client = await get_text_client_for_tenant(tenant_id)
    except Exception as e:  # noqa: BLE001 — no key/client -> fallback splitter
        logger.warning("[user_script] semantic split unavailable: %s", str(e)[:150])
        return None

    hint = ""
    try:
        from channel_format import get_channel_format
        fmt, _locked = await get_channel_format(tenant_id)
        seg = (fmt or {}).get("segmentation")
        if seg:
            hint = f"\n- This channel's episodes are structured as: {seg}. Break scenes to match."
    except Exception:  # noqa: BLE001
        pass

    prompt = (
        "Insert scene markers into this video script for production. Rules:\n"
        "- Reproduce the script EXACTLY as given — do not add, remove, or change a single word.\n"
        "- Put a line containing only @@@SCENE 1@@@ at the VERY START, then a @@@SCENE n@@@ "
        "line before each new scene (n = 2, 3, ...).\n"
        "- A scene is ONE coherent beat: one subject, machine, product, location, or story "
        "moment. When the script moves to a new subject (the next machine in a review, a new "
        "story beat), start a new scene.\n"
        "- Aim for scenes a narrator reads in 30–90 seconds (~75–220 words); split an "
        "over-long beat at its most natural pause."
        + hint +
        "\n- Output ONLY the marked-up script, nothing else.\n\nSCRIPT:\n" + text
    )
    kwargs = {"model": "claude-sonnet-4-6"} if type(client).__name__ == "AnthropicDirectClient" else {}
    try:
        raw = await client.generate(prompt=prompt, max_tokens=16000, temperature=0.2, **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.warning("[user_script] semantic split call failed: %s", str(e)[:200])
        return None

    from pipeline_executor import PipelineExecutor
    scenes = PipelineExecutor._parse_modeled_scenes(raw or "")
    if not scenes:
        return None

    def _norm(s: str) -> str:
        return re.sub(r"\W+", "", s).lower()

    if _norm("".join(s["text"] for s in scenes)) != _norm(text):
        logger.warning("[user_script] semantic split altered the words — using fallback splitter")
        return None
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
    # Split priority: the creator's own marks always win; unmarked scripts get
    # the semantic model split (one beat per scene, verbatim-guarded); the
    # word-count paragraph splitter is the fail-soft floor.
    scenes = split_scenes_explicit(text)
    if not scenes:
        scenes = await semantic_split(tenant_id, text)
    if not scenes:
        scenes = split_scenes_paragraphs(text)
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
