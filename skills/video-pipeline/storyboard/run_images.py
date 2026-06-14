"""Storyboard image generation step — generates contact sheets from prompts.

Reads: Storyboard Prompts field from Ideas table
Writes: Storyboard 1, Storyboard 2, Storyboard 3 fields (attachments)
Advances: Ready For Storyboard Images → Ready For Storyboard Extraction
Clients: airtable, image_client

This step runs AFTER prompts are generated and reviewed.
"""

from orchestrator.pipeline_constants import Statuses


async def run(pipeline, scene_filter=None, progress_callback=None) -> dict:
    """Generate storyboard contact sheet images (Phase 1B).

    Args:
        scene_filter: If set, only generate images for this scene number.
        progress_callback: Called with (message: str) to report progress.
    """
    from storyboard.bot import run_storyboard_images

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

    # Check if ALL scenes have all their grids — only skip if truly complete
    all_grids_present = True
    any_prompts_exist = False
    for rec in script_records:
        fields = rec.get("fields", rec)
        prompts_text = fields.get("Storyboard Prompts", "") or ""
        if prompts_text.strip():
            any_prompts_exist = True
            # Count beats from prompts
            import re
            beat_matches = re.findall(r"--- BEAT (\d+) ---", prompts_text)
            beat_count = len(beat_matches) if beat_matches else 1
            # Check if each beat has a grid
            for i in range(1, beat_count + 1):
                grid_field = f"Storyboard {i}"
                grid_val = fields.get(grid_field)
                if not grid_val:
                    all_grids_present = False
                    break
        if not all_grids_present:
            break

    if all_grids_present and any_prompts_exist:
        print(f"  ✅ All storyboard grids present — advancing to extraction")
        pipeline._update_status(Statuses.READY_STORYBOARD_EXTRACTION)
        return {
            "bot": "Storyboard Images",
            "video_title": pipeline.video_title,
            "new_status": Statuses.READY_STORYBOARD_EXTRACTION,
            "skipped": True,
        }

    # Check that prompts exist
    first_script = script_records[0].get("fields", script_records[0])
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
        slack_client=pipeline.slack,
        scene_filter=scene_filter,
        progress_callback=progress_callback,
        should_cancel=getattr(pipeline, "should_cancel", None),
        character_reference_urls=getattr(pipeline, "character_reference_urls", None),
        aspect_ratio=getattr(pipeline, "aspect_ratio", "16:9"),
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

    # User pressed Stop — keep completed grids, don't advance status
    if result.get("cancelled"):
        print(f"  🛑 Stopped by user — kept {grids_generated} completed grid(s)")
        pipeline.slack.notify(f"🛑 Storyboard grids stopped by user ({grids_generated}/{beat_count} done) for *{pipeline.video_title}*")
        return {
            "bot": "Storyboard Images",
            "video_title": pipeline.video_title,
            "grids_generated": grids_generated,
            "cancelled": True,
        }

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
