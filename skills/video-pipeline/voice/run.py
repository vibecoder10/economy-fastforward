"""Voice synthesis step — generates narration audio from script scenes.

Reads: Script records from Airtable (Scene text field)
Writes: Voice Over attachment to Airtable Scripts table, MP3 to Google Drive
Advances: Ready For Voice → Ready For Image Prompts
Clients: elevenlabs, google, airtable, slack
"""

from orchestrator.pipeline_constants import Statuses, IdeaFields, ScriptFields


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

        scene_text = script.get(ScriptFields.SCENE_TEXT, "")

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

    # UPDATE STATUS (skip if targeted run)
    if cancelled:
        print(f"  🛑 Stopped by user — kept {voice_count} completed voice track(s)")
        return {"bot": "Voice Bot", "video_title": pipeline.video_title, "voice_count": voice_count, "cancelled": True}

    if pipeline._is_targeted_run:
        print(f"  🎯 Targeted run — status NOT advanced")
        return {"bot": "Voice Bot", "video_title": pipeline.video_title, "voice_count": voice_count, "targeted": True}

    # Sound design runs AFTER images exist (needs Image Prompt + Sentence Text)
    pipeline._update_status(Statuses.READY_IMAGE_PROMPTS)
    print(f"  ✅ Status updated to: {Statuses.READY_IMAGE_PROMPTS}")

    pipeline.slack.notify_voice_done()

    return {
        "bot": "Voice Bot",
        "video_title": pipeline.video_title,
        "voice_count": voice_count,
        "new_status": Statuses.READY_IMAGE_PROMPTS,
    }
