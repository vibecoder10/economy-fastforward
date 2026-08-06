"""Voice synthesis step — generates narration audio from script scenes.

Reads: Script records from Airtable (Scene text field)
Writes: Voice Over attachment to Airtable Scripts table, MP3 to Google Drive
Advances: Ready For Voice → Ready For Image Prompts
Clients: elevenlabs, google, airtable, slack
"""

import io
import logging
import re

from orchestrator.pipeline_constants import Statuses, IdeaFields, ScriptFields

logger = logging.getLogger(__name__)

# The narrator must never read what isn't narration. Heard live: the scene VO
# spoke the ENTIRE raw scene text — "**Marco:** ¡Espera!" labels, the
# characters' lines (which the cast voices separately and lip-syncs), and the
# markdown asterisks. For character-dialogue videos the speaker lines are
# dropped from the narrator's text; markdown emphasis is stripped for everyone.
_BOLD_SPEAKER_RE = re.compile(
    r"(?m)^(\s*)\*{1,3}\s*([A-Z][A-Za-z .'-]{0,24})\s*(?::\s*\*{1,3}|\*{1,3}\s*:)\s*")
_SPEAKER_LINE_RE = re.compile(r"(?m)^\s*[A-Z][A-Za-z .'-]{0,24}:\s+\S.*$")
_MD_MARKS_RE = re.compile(r"\*{1,3}|^#+\s*|^-{3,}\s*$", re.M)

# S7-C — LOCATION:/ACTION: stage-direction headers must NEVER reach the
# narrator. Recon proved a live bug: on the submit path (S7-A) a leading
# "LOCATION: ..." header survives verbatim into scripts.scene_text (storage
# law — text is never rewritten at storage, see backend/story_laws.py), and
# in narration mode (dialogue_mode != "character_dialogue") nothing
# downstream of storage ever stripped it before this fix — the narrator
# would read "LOCATION: the kitchen" aloud. This is the speech boundary that
# closes it.
#
# This package (skills/video-pipeline) cannot import the backend, so this
# mirrors backend/story_laws.py's _extract_leading_header semantics locally
# (leading lines only, either header, at most one line of tolerance for the
# sibling header, never mid-text prose that happens to contain the word).
# It ALSO tolerates markdown-bold wrapping around the keyword/colon in EVERY
# position _BOLD_SPEAKER_RE itself recognizes for a speaker label — stars
# before the keyword, AND stars on either side of the colon independently
# ("**ACTION:** ...", "**ACTION**: ...", "ACTION**:** ..."), not just the
# one "stars wrap keyword+colon together" shape. Manager review (2026-08-06)
# caught the gap: a first cut only tolerated stars immediately before the
# keyword and immediately after the colon, so "**ACTION**: dance" (colon
# OUTSIDE the bold — the exact second alternative in _BOLD_SPEAKER_RE's own
# `(?::\s*\*{1,3}|\*{1,3}\s*:)`) matched neither header regex, survived this
# strip, got reduced to plain "ACTION: dance" by _BOLD_SPEAKER_RE below, and
# then nothing removed it in narration mode — the exact leak this chunk
# exists to kill. Allowing optional stars on BOTH sides of the colon
# simultaneously (rather than mirroring the alternation literally) is a
# superset that covers every shape without needing two branches, and stays
# safe because the whole match is still anchored to the literal keyword at
# line-start.
_STAR = r"\*{0,3}"
_LOCATION_HEADER_RE = re.compile(
    rf"^\s*{_STAR}\s*LOCATION\s*{_STAR}\s*:\s*{_STAR}\s*(?:.+?)\s*{_STAR}\s*$", re.IGNORECASE)
_ACTION_HEADER_RE = re.compile(
    rf"^\s*{_STAR}\s*ACTION\s*{_STAR}\s*:\s*{_STAR}\s*(?:.+?)\s*{_STAR}\s*$", re.IGNORECASE)


def _strip_leading_stage_headers(text: str) -> str:
    """Remove up to two leading LOCATION:/ACTION: header lines (either
    order, either markdown-bold or plain form) from the START of scene
    text. Never touches mid-text prose that happens to contain either word
    — only the scene's opening non-blank lines are ever examined, exactly
    like story_laws.py's own leading-header scanner."""
    if not text:
        return text or ""
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    removed: set = set()
    for _ in range(2):  # at most: this scene's own header + one tolerated sibling
        if idx >= len(lines):
            break
        line = lines[idx]
        if _LOCATION_HEADER_RE.match(line) or _ACTION_HEADER_RE.match(line):
            removed.add(idx)
            idx += 1
            while idx < len(lines) and not lines[idx].strip():
                idx += 1
        else:
            break
    if not removed:
        return text
    kept = [ln for i, ln in enumerate(lines) if i not in removed]
    return "\n".join(kept).strip()


def narration_text(scene_text: str, dialogue_mode: str = "") -> str:
    """What the NARRATOR actually reads: stage-direction-free (S7-C —
    LOCATION:/ACTION: headers are storage metadata, never speech),
    markdown-free, and (for dialogue videos) without the character lines —
    those are performed by the cast."""
    text = _strip_leading_stage_headers(scene_text or "")
    text = _BOLD_SPEAKER_RE.sub(r"\1\2: ", text)
    if (dialogue_mode or "") == "character_dialogue":
        text = _SPEAKER_LINE_RE.sub("", text)
    text = _MD_MARKS_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def mp3_duration_seconds(data: bytes) -> "float | None":
    """Real duration read straight from the MP3 header (mutagen — already a
    pinned dependency, used the same way in dialogue_voice.py's per-segment
    timing). Returns None (after logging a warning) if the bytes can't be
    parsed for any reason — a scene's narration MP3 must still upload and
    voice_over_url must still get written even when duration can't be
    determined. Rounded to 2 decimals."""
    try:
        from mutagen.mp3 import MP3
        length = float(MP3(io.BytesIO(data)).info.length)
        if length > 0:
            return round(length, 2)
        logger.warning("voice duration: mutagen returned a non-positive length")
    except Exception as e:
        logger.warning("voice duration: failed to read MP3 duration (%s)", e)
    return None


async def run(pipeline) -> dict:
    """Generate voice overs for all scenes."""
    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_VOICE)
        if not idea:
            return {"error": "No idea with status 'Ready For Voice'", "bot": "Voice Bot"}
        pipeline._load_idea(idea)

    if pipeline.current_idea.get(IdeaFields.STATUS) != Statuses.READY_VOICE:
        return {"error": f"Idea status is '{pipeline.current_idea.get(IdeaFields.STATUS)}', expected 'Ready For Voice'", "bot": "Voice Bot", "video_title": pipeline.video_title}

    pipeline.slack.notify_voice_start()
    print(f"\n🗣️ VOICE BOT: Processing '{pipeline.video_title}'")
    pipeline._log_filters()

    # Get or create project folder
    if not pipeline.project_folder_id:
        folder = pipeline.google.get_or_create_folder(pipeline.video_title)
        pipeline.project_folder_id = folder["id"]

    # Get scripts for this video
    scripts = pipeline.airtable.get_scripts_by_title(pipeline.video_title)

    if not scripts:
        return {"error": f"No scripts found for: {pipeline.video_title}", "bot": "Voice Bot", "video_title": pipeline.video_title}

    # Apply scene filter
    if pipeline.scene_filter is not None:
        scripts = [s for s in scripts if s.get("scene") == pipeline.scene_filter]

    _should_cancel = getattr(pipeline, "should_cancel", None)

    async def _cancelled() -> bool:
        try:
            return bool(_should_cancel) and await _should_cancel()
        except Exception:
            return False

    voice_count = 0
    # Real spend is per-character (ElevenLabs bills that way, not per run —
    # docs/cost-awareness.md ~$0.30/1000 chars). Track exactly what got sent
    # to the synth call for THIS run so the caller can ledger the actual
    # character count instead of a flat per-run guess (checklist §0.3c/C09).
    total_chars = 0
    cancelled = False
    # A scene that needed narration but never got audio is a FAILURE, not a
    # silent skip — before this fix, a provider error (e.g. Kie TTS's own
    # "internal error, please try again later") returned None from
    # generate_and_wait, the scene was quietly dropped, and the run below
    # still advanced status as if every scene were voiced (confirmed on
    # video 146242df: 3/3 scenes with voice_over_url NULL, status advanced
    # three stages past voice, $1.50 of image spend logged afterward).
    # Partial-success rule: ANY missing scene stops the run and reports
    # exactly which scenes failed and why, rather than silently rendering a
    # film with gaps. Already-voiced scenes stay marked finished (this stage
    # is already resumable — see docs/failure-modes.md's per-scene "already
    # done" check above), so re-running after a fix only retries the
    # failures, it does not re-pay for scenes that already succeeded.
    failures: list[dict] = []
    for script in scripts:
        if await _cancelled():
            print("  🛑 Stop requested — halting voice generation")
            cancelled = True
            break
        scene_number = script.get("scene", 0)

        # CHECK: Is voice already done?
        if script.get(ScriptFields.SCRIPT_STATUS) == ScriptFields.STATUS_FINISHED:
            print(f"  Check: Scene {scene_number} voice already done, skipping.")
            continue

        scene_text = narration_text(
            script.get(ScriptFields.SCENE_TEXT, ""),
            getattr(pipeline, "dialogue_mode", "") or "",
        )
        if not scene_text:
            print(f"  Scene {scene_number}: nothing for the narrator (all dialogue) — skipping.")
            continue

        print(f"  Generating voice for scene {scene_number}...")

        # Generate voice. fail_info_out captures WHY it failed (Kie's
        # failCode/failMsg/creditsConsumed, or the direct-API exception
        # text) so a real failure is reported instead of silently skipped.
        fail_info: list = []
        audio_url = await pipeline.elevenlabs.generate_and_wait(scene_text, fail_info_out=fail_info)

        if audio_url:
            # Download audio (reads temp file or URL)
            audio_content = await pipeline.elevenlabs.download_audio(audio_url)

            # Real duration from the MP3 bytes we already have in memory —
            # never lets a duration-parsing failure fail the scene; None
            # just means the column stays NULL like it did before this fix.
            voice_duration = mp3_duration_seconds(audio_content)

            # Upload to Google Drive
            filename = f"Scene {scene_number}.mp3"
            drive_result = pipeline.google.upload_audio(audio_content, filename, pipeline.project_folder_id)

            # Use Drive URL for persistent storage (temp file paths expire)
            if drive_result and drive_result.get("id"):
                persistent_url = f"https://drive.google.com/uc?id={drive_result['id']}&export=download"
            else:
                persistent_url = audio_url  # fallback to original URL

            # Update Supabase with persistent Drive URL + real duration —
            # same call, same DB update (adapter writes both columns together).
            pipeline.airtable.mark_script_finished(
                script["id"], persistent_url, voice_duration_seconds=voice_duration)
            voice_count += 1
            total_chars += len(scene_text)
        else:
            reason = ((fail_info[-1] or {}).get("failMsg") if fail_info else None) or "voice synthesis failed"
            print(f"  ❌ Scene {scene_number}: {reason}")
            failures.append({"scene": scene_number, "error": reason})

    # UPDATE STATUS (skip if targeted run)
    if cancelled:
        print(f"  🛑 Stopped by user — kept {voice_count} completed voice track(s)")
        result = {"bot": "Voice Bot", "video_title": pipeline.video_title, "voice_count": voice_count,
                  "total_chars": total_chars, "cancelled": True}
        if failures:
            result["failed_scenes"] = [f["scene"] for f in failures]
        return result

    if pipeline._is_targeted_run:
        print(f"  🎯 Targeted run — status NOT advanced")
        result = {"bot": "Voice Bot", "video_title": pipeline.video_title, "voice_count": voice_count,
                  "total_chars": total_chars, "targeted": True}
        # A targeted (single-scene) regeneration that itself failed must
        # never be reported as a quiet no-op — the caller needs to know the
        # retry didn't take.
        if failures:
            result["error"] = "; ".join(f"scene {f['scene']}: {f['error']}" for f in failures)
            result["failed_scenes"] = [f["scene"] for f in failures]
        return result

    if failures:
        # Zero-tolerance gate: a full run that left even one scene unvoiced
        # must NOT advance status — advancing here is exactly what let
        # image/sound spend happen on a video with no narration. Scenes that
        # DID succeed above are already marked finished in Supabase, so a
        # re-run of Voice only retries what's in `failures`.
        scenes_failed = ", ".join(str(f["scene"]) for f in failures)
        reasons = "; ".join(f"scene {f['scene']}: {f['error']}" for f in failures)
        error_msg = (
            f"Voice generation failed for {len(failures)} of {voice_count + len(failures)} "
            f"scene(s) ({scenes_failed}) — status NOT advanced. {reasons}"
        )
        print(f"  ❌ {error_msg}")
        return {"bot": "Voice Bot", "video_title": pipeline.video_title, "voice_count": voice_count,
                "total_chars": total_chars, "error": error_msg,
                "failed_scenes": [f["scene"] for f in failures]}

    # Sound design runs AFTER images exist (needs Image Prompt + Sentence Text)
    pipeline._update_status(Statuses.READY_IMAGE_PROMPTS)
    print(f"  ✅ Status updated to: {Statuses.READY_IMAGE_PROMPTS}")

    pipeline.slack.notify_voice_done()

    return {
        "bot": "Voice Bot",
        "video_title": pipeline.video_title,
        "voice_count": voice_count,
        "total_chars": total_chars,
        "new_status": Statuses.READY_IMAGE_PROMPTS,
    }
