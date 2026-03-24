"""Sound effects step — generates audio files from sound prompts.

Reads: Sound Prompt field from Images table
Writes: Sound Effect attachment + Sound Volume to Images table, MP3 to Drive
Advances: Ready For Sound Effects → Ready For Video Scripts
Clients: sound_client, google, airtable, slack
"""

from orchestrator.pipeline_constants import Statuses
from sound.sound_bot import SoundBot
from shared.clients.sound_client import SoundClient


async def run(pipeline) -> dict:
    """Generate sound effect audio for all image rows."""
    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_SOUND_EFFECTS)
        if not idea:
            return {"error": "No idea with status 'Ready For Sound Effects'", "bot": "Sound Bot"}
        pipeline._load_idea(idea)

    if pipeline.current_idea.get("Status") != Statuses.READY_SOUND_EFFECTS:
        return {"error": f"Idea status is '{pipeline.current_idea.get('Status')}', expected 'Ready For Sound Effects'", "bot": "Sound Bot", "video_title": pipeline.video_title}

    pipeline.slack.notify("🔊 Generating sound effects for: " + pipeline.video_title)
    print(f"\n🔊 SOUND BOT: Processing '{pipeline.video_title}'")

    # Get or create project folder
    if not pipeline.project_folder_id:
        folder = pipeline.google.get_or_create_folder(pipeline.video_title)
        pipeline.project_folder_id = folder["id"]

    bot = SoundBot(
        sound_client=pipeline.sound_client or SoundClient(),
        airtable=pipeline.airtable,
        google=pipeline.google,
        slack=pipeline.slack,
    )
    result = await bot.process_video(pipeline.video_title, folder_id=pipeline.project_folder_id)

    if result.get("error"):
        return result

    # Update status — sound is done, move to video prompts
    pipeline._update_status(Statuses.READY_VIDEO_SCRIPTS)
    print(f"  ✅ Status updated to: {Statuses.READY_VIDEO_SCRIPTS}")

    pipeline.slack.notify(
        f"✅ Generated {result.get('total_generated', 0)} sound effects for *{pipeline.video_title}* "
        f"(~${result.get('estimated_cost', 0):.2f})"
    )

    result["new_status"] = Statuses.READY_VIDEO_SCRIPTS
    return result
