"""Storyboard image generation step — generates contact sheets from prompts.

Reads: Storyboard Prompts field from Ideas table
Writes: Storyboard 1, Storyboard 2, Storyboard 3 fields (attachments)
Advances: Ready For Storyboard Images → Ready For Storyboard Extraction
Clients: airtable, image_client

This step runs AFTER prompts are generated and reviewed.
"""

from pipeline_constants import Statuses


async def run(pipeline) -> dict:
    """Generate storyboard contact sheet images (Phase 1B)."""
    from storyboard_bot import run_storyboard_images

    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_STORYBOARD_IMAGES)
        if not idea:
            return {"error": "No idea with status 'Ready For Storyboard Images'", "bot": "Storyboard Images"}
        pipeline._load_idea(idea)

    # Check storyboard status and prompts from Scripts table
    script_records = pipeline.airtable.get_scripts_by_title(pipeline.video_title)
    if not script_records:
        return {
            "error": f"No script found for '{pipeline.video_title}'",
            "bot": "Storyboard Images",
            "video_title": pipeline.video_title,
        }

    first_script = script_records[0].get("fields", script_records[0])
    sb_status = first_script.get("Storyboard Status", "none") or "none"

    # If grids already generated, skip to extraction status
    if sb_status == "grids_generated":
        print(f"  ✅ Storyboard images already generated — advancing to extraction")
        pipeline._update_status(Statuses.READY_STORYBOARD_EXTRACTION)
        return {
            "bot": "Storyboard Images",
            "video_title": pipeline.video_title,
            "new_status": Statuses.READY_STORYBOARD_EXTRACTION,
            "skipped": True,
        }

    # Check that prompts exist
    prompts = first_script.get("Storyboard Prompts", "")
    if not prompts:
        return {
            "error": "No storyboard prompts found — run prompt generation first",
            "bot": "Storyboard Images",
            "video_title": pipeline.video_title,
        }

    print(f"\n🎨 STORYBOARD IMAGES: Generating for '{pipeline.video_title}'")
    pipeline.slack.notify(f"🎨 Generating storyboard images for: *{pipeline.video_title}*")

    # Build idea_record in expected format
    idea_record = {
        "id": pipeline.current_idea_id,
        "fields": pipeline.current_idea,
    }

    # Generate images from prompts
    result = await run_storyboard_images(
        idea_record=idea_record,
        airtable_client=pipeline.airtable,
        image_client=pipeline.image_client,
    )

    if result.get("error"):
        error_msg = result["error"]
        pipeline.slack.notify(f"❌ Storyboard images failed for *{pipeline.video_title}*: {error_msg}")
        return {
            "error": error_msg,
            "bot": "Storyboard Images",
            "video_title": pipeline.video_title,
        }

    beat_count = result.get("beat_count", 0)
    grids_generated = result.get("grids_generated", 0)
    failed_beats = result.get("failed_beats", [])
    total_cost = result.get("total_cost", 0)

    if failed_beats:
        print(f"  ⚠️ Partial: {grids_generated}/{beat_count} grids (failed: {failed_beats})")
    else:
        print(f"  ✅ Generated {grids_generated} grids for {beat_count} beats")

    # Update status to Ready For Storyboard Extraction
    pipeline._update_status(Statuses.READY_STORYBOARD_EXTRACTION)
    print(f"  ✅ Status updated to: {Statuses.READY_STORYBOARD_EXTRACTION}")

    # Notify with results
    status_emoji = "✅" if not failed_beats else "⚠️"
    notify_msg = (
        f"{status_emoji} Storyboard images ready for *{pipeline.video_title}*\n"
        f"• {grids_generated}/{beat_count} grids generated\n"
        f"• Cost: ~${total_cost:.2f}\n"
        f"• *Review grids in Airtable (Storyboard 1/2/3), then run next step to extract panels*"
    )
    if failed_beats:
        notify_msg += f"\n• ⚠️ Failed beats: {failed_beats}"

    pipeline.slack.notify(notify_msg)

    result_dict = {
        "bot": "Storyboard Images",
        "video_title": pipeline.video_title,
        "beat_count": beat_count,
        "grids_generated": grids_generated,
        "total_cost": total_cost,
        "new_status": Statuses.READY_STORYBOARD_EXTRACTION,
    }
    if failed_beats:
        result_dict["failed_beats"] = failed_beats

    return result_dict
