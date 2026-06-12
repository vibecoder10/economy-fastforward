"""Per-segment voice synthesis — the performance soundtrack for dialogue videos.

dialogue_intelligence tags each scene with an ordered narrator/character
timeline (scripts.dialogue_segments). This module gives every segment its own
voice: the scene's narrator voice for narration entries, the character's cast
voice (video_characters.voice_name, a Kie/ElevenLabs roster ID) for dialogue
lines. One MP3 per segment lands in Drive at {video}/voice/S{n}-seg{i}.mp3 and
audio_url + duration are written back into the jsonb — the timeline the
animatic rehearsal, the Grok dialogue clips, and the final render all play.

Resume-safe: segments that already carry audio_url + duration are skipped, and
the jsonb is persisted after every segment so a crash or Stop keeps paid work.
"""

import asyncio
import io
import json
import logging
from typing import Optional

from database import fetch_all, execute
from storage import upload_bytes

logger = logging.getLogger(__name__)

# Kie TTS throws transient "internal error, please try again later" on
# individual tasks (seen live 2026-06-12) — one flake must not kill a
# 158-segment run. Retries are per segment; completed work is already
# persisted, so a final failure resumes from the failed segment.
SEGMENT_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5

# Character lines read best slightly livelier and faster than narration
# (calibrated live on the Kie ElevenLabs gateway: speed 1.05 reads younger,
# style 0.2 adds acting without wobble).
DIALOGUE_VOICE_SETTINGS = {"stability": 0.45, "style": 0.2, "speed": 1.05}


def _mp3_duration_seconds(data: bytes, text: str) -> float:
    """Real duration from the MP3 header; word-count estimate as fallback."""
    try:
        from mutagen.mp3 import MP3
        length = float(MP3(io.BytesIO(data)).info.length)
        if length > 0:
            return round(length, 2)
    except Exception:
        pass
    return round(max(0.5, len(text.split()) / 2.5), 2)  # ~2.5 words/sec


def _as_segments(raw) -> Optional[list]:
    """dialogue_segments comes back from asyncpg as a JSON string."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, list) and raw else None


async def synthesize_video_segments(
    video_id: str,
    tenant_id,
    tts,
    scene_filter: Optional[int] = None,
    progress_callback=None,
    cancel_check=None,
) -> dict:
    """Voice every untouched dialogue_segments entry for a video.

    tts is a shared.clients ElevenLabsClient (Kie gateway or direct).
    Returns counts + warnings, with cancelled=True when stopped mid-run.
    """

    async def _report(msg: str):
        if progress_callback:
            try:
                await progress_callback(msg)
            except Exception:
                pass

    async def _cancelled() -> bool:
        try:
            return bool(cancel_check) and await cancel_check()
        except Exception:
            return False

    cast_rows = await fetch_all(
        "SELECT name, voice_name FROM video_characters WHERE video_id = $1",
        video_id,
    )
    cast_voices = {
        (r["name"] or "").strip().casefold(): r["voice_name"]
        for r in cast_rows
        if r.get("voice_name")
    }

    scenes = await fetch_all(
        "SELECT id, scene, voice_id, dialogue_segments FROM scripts "
        "WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
        video_id, tenant_id,
    )

    voiced = skipped = 0
    scenes_touched = 0
    warnings: list[str] = []
    cancelled = False

    for sc in scenes:
        scene_num = sc.get("scene")
        if scene_filter is not None and scene_num != scene_filter:
            continue
        segments = _as_segments(sc.get("dialogue_segments"))
        if not segments:
            continue

        # The Kie gateway rejects off-roster narrator ids and falls back to
        # its narration voice inside the client — no pre-validation needed.
        narrator_voice = (sc.get("voice_id") or "").strip() or None
        total = len(segments)
        scene_changed = False

        for i, seg in enumerate(segments, start=1):
            if seg.get("audio_url") and seg.get("duration"):
                skipped += 1
                continue
            if await _cancelled():
                cancelled = True
                break

            text = (seg.get("text") or "").strip()
            if not text:
                continue

            is_dialogue = seg.get("type") == "dialogue"
            speaker = (seg.get("speaker") or "").strip()
            if is_dialogue:
                voice = cast_voices.get(speaker.casefold())
                if not voice:
                    warnings.append(
                        f"S{scene_num} seg{i}: no cast voice for '{speaker}' — narrator voice used"
                    )
                    voice = narrator_voice
                settings = DIALOGUE_VOICE_SETTINGS
            else:
                voice = narrator_voice
                settings = {}

            who = speaker if is_dialogue else "narrator"
            await _report(f"Scene {scene_num}: voicing line {i}/{total} ({who})")

            audio = None
            last_err = None
            for attempt in range(1, SEGMENT_ATTEMPTS + 1):
                try:
                    result = await tts.generate_voice(text, voice_id=voice, **settings)
                    audio = (result or {}).get("audio_content")
                    if audio:
                        break
                    last_err = "no audio returned"
                except Exception as e:
                    last_err = str(e)[:200]
                if attempt < SEGMENT_ATTEMPTS:
                    logger.warning(
                        "dialogue-voice S%s seg%s attempt %s failed (%s) — retrying",
                        scene_num, i, attempt, last_err,
                    )
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
            if not audio:
                raise RuntimeError(
                    f"Voice synthesis failed for scene {scene_num} segment {i} "
                    f"after {SEGMENT_ATTEMPTS} attempts: {last_err}"
                )

            url = await upload_bytes(
                audio, f"{video_id}/voice/S{scene_num}-seg{i}.mp3", "audio/mpeg"
            )
            seg["audio_url"] = url
            seg["duration"] = _mp3_duration_seconds(audio, text)
            if is_dialogue and voice:
                seg["voice_name"] = voice

            # Persist after EVERY segment: a crash or Stop keeps paid work.
            await execute(
                "UPDATE scripts SET dialogue_segments = $1, updated_at = now() WHERE id = $2",
                json.dumps(segments), sc["id"],
            )
            voiced += 1
            scene_changed = True

        if scene_changed or any(s.get("audio_url") for s in segments):
            scenes_touched += 1
        if cancelled:
            break

    return {
        "segments_voiced": voiced,
        "segments_skipped": skipped,
        "scenes": scenes_touched,
        "warnings": warnings,
        "cancelled": cancelled,
    }
