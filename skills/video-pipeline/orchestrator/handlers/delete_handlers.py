"""Delete/redo handlers — wipe scripts or image prompts for re-generation.

Extracted from pipeline_control.py for debuggability.
All functions take (message, say) — decorators applied in pipeline_control.py.
"""

import re

from orchestrator.pipeline_constants import IdeaFields, Statuses


async def handle_delete_scripts(message, say):
    """Delete all script records for a video so they can be regenerated."""
    match = re.search(r"^!?delete\s+[\"']?(.+?)[\"']?\s+scripts?$", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `delete <video_title> scripts`")
        return

    title = match.group(1).strip()

    try:
        from shared.clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        count = airtable.delete_scripts_for_video(video_title)
        if count == 0:
            await say(f":warning: No script records found for *{video_title}*")
            return

        # Reset status so scripts can be regenerated
        airtable.update_idea_fields(idea["id"], {"Status": Statuses.READY_SCRIPTING})
        await say(
            f":wastebasket: Deleted *{count}* script records for *{video_title}*\n"
            f"Status reset to *Ready For Scripting* — run `script` to regenerate"
        )
    except Exception as e:
        await say(f":x: Error deleting scripts: {e}")


async def handle_delete_images(message, say):
    """Delete all image prompt/concept records for a video so they can be regenerated."""
    match = re.search(
        r"^!?delete\s+[\"']?(.+?)[\"']?\s+(?:prompts?|images?)$",
        message["text"],
        re.IGNORECASE,
    )
    if not match:
        await say(":x: Usage: `delete <video_title> prompts` or `delete <video_title> images`")
        return

    title = match.group(1).strip()

    try:
        from shared.clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        count = airtable.delete_images_for_video(video_title)
        if count == 0:
            await say(f":warning: No image records found for *{video_title}*")
            return

        # Reset status so image prompts can be regenerated
        airtable.update_idea_fields(idea["id"], {"Status": Statuses.READY_IMAGE_PROMPTS})
        await say(
            f":wastebasket: Deleted *{count}* image records for *{video_title}*\n"
            f"Status reset to *Ready For Image Prompts* — run `prompts` to regenerate"
        )
    except Exception as e:
        await say(f":x: Error deleting images: {e}")
