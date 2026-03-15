"""Style, model, and visual style override handlers.

Extracted from pipeline_control.py for debuggability.
All functions take (message, say) — decorators applied in pipeline_control.py.
"""

import re

from pipeline_constants import IdeaFields


# ---------------------------------------------------------------------------
# !style — per-video style overrides for image prompts and thumbnails
# ---------------------------------------------------------------------------

async def handle_style_image(message, say):
    """Set an image style override for a specific video."""
    match = re.search(r"^!?style\s+image\s+(.+?):\s*(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `style image <video_title>: <instructions>`")
        return

    title = match.group(1).strip()
    instructions = match.group(2).strip()

    try:
        from clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        airtable.update_idea_fields(idea["id"], {"Image Style Override": instructions})
        preview = instructions[:50] + "..." if len(instructions) > 50 else instructions
        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        await say(f":art: Image style override set for *{video_title}*: {preview}")
    except Exception as e:
        await say(f":x: Error setting image style override: {e}")


async def handle_style_thumbnail(message, say):
    """Set a thumbnail style override for a specific video."""
    match = re.search(r"^!?style\s+thumbnail\s+(.+?):\s*(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `style thumbnail <video_title>: <instructions>`")
        return

    title = match.group(1).strip()
    instructions = match.group(2).strip()

    try:
        from clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        airtable.update_idea_fields(idea["id"], {"Thumbnail Style Override": instructions})
        preview = instructions[:50] + "..." if len(instructions) > 50 else instructions
        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        await say(f":art: Thumbnail style override set for *{video_title}*: {preview}")
    except Exception as e:
        await say(f":x: Error setting thumbnail style override: {e}")


async def handle_style_color(message, say):
    """Set an accent color override for a specific video."""
    match = re.search(r"^!?style\s+color\s+(.+?):\s*(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `style color <video_title>: <color>`")
        return

    title = match.group(1).strip()
    color = match.group(2).strip().lower()

    from image_prompt_engine.style_config import VALID_ACCENT_COLORS
    if color not in VALID_ACCENT_COLORS:
        valid = ", ".join(sorted(VALID_ACCENT_COLORS))
        await say(f":x: Invalid accent color *{color}*. Valid values: {valid}")
        return

    try:
        from clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        airtable.update_idea_fields(idea["id"], {"Accent Color": color})
        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        await say(f":art: Accent color set for *{video_title}*: {color}")
    except Exception as e:
        await say(f":x: Error setting accent color: {e}")


async def handle_style_reset(message, say):
    """Clear both style overrides and accent color for a specific video."""
    match = re.search(r"^!?style\s+reset\s+(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `style reset <video_title>`")
        return

    title = match.group(1).strip()

    try:
        from clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        airtable.update_idea_fields(idea["id"], {
            "Image Style Override": "",
            "Thumbnail Style Override": "",
            "Accent Color": "",
            "Image Model Override": [],  # Multiple Select requires array
            "Visual Style": "",  # Single Select clears with empty string
        })
        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        await say(f":white_check_mark: Style overrides cleared for *{video_title}*")
    except Exception as e:
        await say(f":x: Error resetting style overrides: {e}")


# ---------------------------------------------------------------------------
# !model — hot-swap image generation model for a video
# ---------------------------------------------------------------------------

async def handle_model_set(message, say):
    """Set the image generation model override for a specific video."""
    match = re.search(r"^!?model\s+(.+?):\s*(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `model <video_title>: <model_name>`")
        return

    title = match.group(1).strip()
    model_name = match.group(2).strip().lower()

    from clients.image_client import ImageClient
    if model_name not in ImageClient.VALID_SCENE_MODELS:
        valid = "\n".join(f"  • `{k}` — {v}" for k, v in ImageClient.VALID_SCENE_MODELS.items())
        await say(f":x: Invalid model *{model_name}*. Available models:\n{valid}")
        return

    try:
        from clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        airtable.update_idea_fields(idea["id"], {"Image Model Override": [model_name]})  # Multiple Select format
        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        desc = ImageClient.VALID_SCENE_MODELS[model_name]
        await say(f":arrows_counterclockwise: Image model set for *{video_title}*: `{model_name}` ({desc})")
    except Exception as e:
        await say(f":x: Error setting image model: {e}")


async def handle_model_reset(message, say):
    """Clear the image model override for a specific video (revert to default)."""
    match = re.search(r"^!?model\s+reset\s+(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `model reset <video_title>`")
        return

    title = match.group(1).strip()

    try:
        from clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        airtable.update_idea_fields(idea["id"], {"Image Model Override": []})  # Multiple Select clears with empty array
        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        await say(f":white_check_mark: Image model reset to default for *{video_title}*")
    except Exception as e:
        await say(f":x: Error resetting image model: {e}")


async def handle_model_list(message, say):
    """List all available image generation models."""
    from clients.image_client import ImageClient
    lines = [":camera: *Available Image Generation Models:*\n"]
    for model_id, desc in ImageClient.VALID_SCENE_MODELS.items():
        default = " _(default)_" if model_id == ImageClient.SCENE_MODEL else ""
        lines.append(f"  • `{model_id}` — {desc}{default}")
    lines.append("\n_Use `model <title>: <model>` to set, `model reset <title>` to revert._")
    await say("\n".join(lines))


# ---------------------------------------------------------------------------
# !visualstyle — set visual profile for a video
# ---------------------------------------------------------------------------

async def handle_visualstyle_set(message, say):
    """Set the visual style/profile for a specific video."""
    match = re.search(r"^!?visualstyle\s+(.+?):\s*(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `visualstyle <video_title>: <style_name>`")
        return

    title = match.group(1).strip()
    style_name = match.group(2).strip().lower().replace(" ", "_")

    from clients.airtable_client import VALID_VISUAL_STYLES
    if style_name not in VALID_VISUAL_STYLES:
        valid = "\n".join(f"  • `{s}`" for s in sorted(VALID_VISUAL_STYLES))
        await say(f":x: Invalid style *{style_name}*. Available styles:\n{valid}")
        return

    try:
        from clients.airtable_client import AirtableClient
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        airtable.update_idea_fields(idea["id"], {"Visual Style": style_name})
        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        await say(f":art: Visual style set for *{video_title}*: `{style_name}`")
    except Exception as e:
        await say(f":x: Error setting visual style: {e}")


async def handle_visualstyle_reset(message, say):
    """Clear the visual style override for a specific video (revert to default)."""
    match = re.search(r"^!?visualstyle\s+reset\s+(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `visualstyle reset <video_title>`")
        return

    title = match.group(1).strip()

    try:
        from clients.airtable_client import AirtableClient
        from clients.airtable_client import DEFAULT_VISUAL_STYLE
        airtable = AirtableClient()
        idea = airtable.find_idea_by_title(title)
        if not idea:
            await say(f":x: No video found matching *{title}*")
            return

        airtable.update_idea_fields(idea["id"], {"Visual Style": ""})
        video_title = idea.get(IdeaFields.VIDEO_TITLE, title)
        await say(f":white_check_mark: Visual style reset to default (`{DEFAULT_VISUAL_STYLE}`) for *{video_title}*")
    except Exception as e:
        await say(f":x: Error resetting visual style: {e}")


async def handle_visualstyle_list(message, say):
    """List all available visual styles."""
    from clients.airtable_client import VALID_VISUAL_STYLES, DEFAULT_VISUAL_STYLE
    lines = [":art: *Available Visual Styles:*\n"]
    for style in sorted(VALID_VISUAL_STYLES):
        default = " _(default)_" if style == DEFAULT_VISUAL_STYLE else ""
        lines.append(f"  • `{style}`{default}")
    lines.append("\n_Use `visualstyle <title>: <style>` to set, `visualstyle reset <title>` to revert._")
    await say("\n".join(lines))
