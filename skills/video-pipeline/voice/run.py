"""Voice synthesis step — generates narration audio from script scenes.

Reads: Script records from Airtable (Scene text field)
Writes: Voice Over attachment to Airtable Scripts table, MP3 to Google Drive
Advances: Ready For Voice → Ready For Image Prompts
Clients: elevenlabs, google, airtable, slack
"""

import re

from orchestrator.pipeline_constants import Statuses, IdeaFields, ScriptFields

# The narrator must never read what isn't narration. Heard live: the scene VO
# spoke the ENTIRE raw scene text — "**Marco:** ¡Espera!" labels, the
# characters' lines (which the cast voices separately and lip-syncs), and the
# markdown asterisks. For character-dialogue videos the speaker lines are
# dropped from the narrator's text; markdown emphasis is stripped for everyone.
_BOLD_SPEAKER_RE = re.compile(
    r"(?m)^(\s*)\*{1,3}\s*([A-Z][A-Za-z .'-]{0,24})\s*(?::\s*\*{1,3}|\*{1,3}\s*:)\s*")
_SPEAKER_LINE_RE = re.compile(r"(?m)^\s*[A-Z][A-Za-z .'-]{0,24}:\s+\S.*$")
_MD_MARKS_RE = re.compile(r"\*{1,3}|^#+\s*|^-{3,}\s*$", re.M)


def narration_text(scene_text: str, dialogue_mode: str = "") -> str:
    """What the NARRATOR actually reads: markdown-free, and (for dialogue
    videos) without the character lines — those are performed by the cast."""
    text = _BOLD_SPEAKER_RE.sub(r"\1\2: ", scene_text or "")
    if (dialogue_mode or "") == "character_dialogue":
        text = _SPEAKER_LINE_RE.sub("", text)
    text = _MD_MARKS_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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

        # Generate voice
        audio_url = await pipeline.elevenlabs.generate_and_wait(scene_text)

        if audio_url:
            # Download audio (reads temp file or URL)
            audio_content = await pipeline.elevenlabs.download_audio(audio_url)

            # Upload to Google Drive
            filename = f"Scene {scene_number}.mp3"
            drive_result = pipeline.google.upload_audio(audio_content, filename, pipeline.project_folder_id)

            # Use Drive URL for persistent storage (temp file paths expire)
            if drive_result and drive_result.get("id"):
                persistent_url = f"https://drive.google.com/uc?id={drive_result['id']}&export=download"
            else:
                persistent_url = audio_url  # fallback to original URL

            # Update Supabase with persistent Drive URL
            pipeline.airtable.mark_script_finished(script["id"], persistent_url)
            voice_count += 1
            total_chars += len(scene_text)

    # UPDATE STATUS (skip if targeted run)
    if cancelled:
        print(f"  🛑 Stopped by user — kept {voice_count} completed voice track(s)")
        return {"bot": "Voice Bot", "video_title": pipeline.video_title, "voice_count": voice_count,
                "total_chars": total_chars, "cancelled": True}

    if pipeline._is_targeted_run:
        print(f"  🎯 Targeted run — status NOT advanced")
        return {"bot": "Voice Bot", "video_title": pipeline.video_title, "voice_count": voice_count,
                "total_chars": total_chars, "targeted": True}

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
