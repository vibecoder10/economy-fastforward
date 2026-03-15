"""Sound design step — generates sound prompts for image rows via Claude Haiku.

Reads: Images table rows (Image Prompt, Sentence Text)
Writes: Sound Prompt field per image row
Advances: Ready For Sound Design → Ready For Sound Effects
Clients: anthropic, airtable
"""

from pipeline_constants import Statuses
from bots.sound_prompt_bot import SoundPromptBot


async def run(pipeline) -> dict:
    """Generate sound prompts for all image rows."""
    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_SOUND_DESIGN)
        if not idea:
            return {"error": "No idea with status 'Ready For Sound Design'"}
        pipeline._load_idea(idea)

    if pipeline.current_idea.get("Status") != Statuses.READY_SOUND_DESIGN:
        return {"error": f"Idea status is '{pipeline.current_idea.get('Status')}', expected 'Ready For Sound Design'"}

    pipeline.slack.notify("🎧 Starting sound design for: " + pipeline.video_title)
    print(f"\n🎧 SOUND PROMPT BOT: Processing '{pipeline.video_title}'")

    bot = SoundPromptBot(anthropic=pipeline.anthropic, airtable=pipeline.airtable)
    result = await bot.process_video(pipeline.video_title)

    if result.get("error"):
        return result

    # Update status
    pipeline._update_status(Statuses.READY_SOUND_EFFECTS)
    print(f"  ✅ Status updated to: {Statuses.READY_SOUND_EFFECTS}")

    pipeline.slack.notify(
        f"✅ Sound prompts complete for *{pipeline.video_title}*: "
        f"{result.get('prompts_generated', 0)}/{result.get('total_images', 0)} images"
    )

    result["new_status"] = Statuses.READY_SOUND_EFFECTS
    return result
