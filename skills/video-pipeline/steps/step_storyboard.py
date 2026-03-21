"""Storyboard generation step — generates contact sheet GRIDS only.

Reads: Script records, Story Bible from Airtable
Writes: Storyboard grids to Ideas table (Storyboard Preview, Storyboard Prompts)
Advances: Ready For Storyboards → Ready For Storyboard Extraction
Clients: anthropic, airtable, image_client

NOTE: This step ONLY generates grids. Extraction happens in step_storyboard_extract.py
after the user reviews the grids and triggers the next step.
"""

from pipeline_constants import Statuses


async def run(pipeline) -> dict:
    """Generate storyboard contact sheet grids (Phase 1 only)."""
    from storyboard_bot import run_storyboard_grids

    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_STORYBOARDS)
        if not idea:
            return {"error": "No idea with status 'Ready For Storyboards'", "bot": "Storyboard Bot"}
        pipeline._load_idea(idea)

    fields = pipeline.current_idea.get("fields", pipeline.current_idea)
    sb_status = fields.get("Storyboard Status", "none")

    # If grids already generated, skip to extraction status
    if sb_status == "grids_generated":
        print(f"  ✅ Storyboard grids already generated — advancing to extraction")
        pipeline._update_status(Statuses.READY_STORYBOARD_EXTRACTION)
        return {
            "bot": "Storyboard Bot",
            "video_title": pipeline.video_title,
            "new_status": Statuses.READY_STORYBOARD_EXTRACTION,
            "skipped": True,
        }

    print(f"\n🎬 STORYBOARD BOT: Generating grids for '{pipeline.video_title}'")
    pipeline.slack.notify(f"🎬 Starting storyboard grid generation for: *{pipeline.video_title}*")

    # Get or create project folder
    if not pipeline.project_folder_id:
        folder = pipeline.google.get_or_create_folder(pipeline.video_title)
        pipeline.project_folder_id = folder["id"]

    # Build idea_record in expected format
    idea_record = {
        "id": pipeline.current_idea_id,
        "fields": pipeline.current_idea,
    }

    # Phase 1 ONLY: Generate contact sheet grids
    print("  📐 Generating contact sheet grids...")
    grid_result = await run_storyboard_grids(
        idea_record=idea_record,
        airtable_client=pipeline.airtable,
        anthropic_client=pipeline.anthropic,
        image_client=pipeline.image_client,
    )

    if grid_result.get("error"):
        error_msg = grid_result["error"]
        pipeline.slack.notify(f"❌ Storyboard grids failed for *{pipeline.video_title}*: {error_msg}")
        return {
            "error": error_msg,
            "bot": "Storyboard Bot",
            "video_title": pipeline.video_title,
        }

    beat_count = grid_result.get("beat_count", 0)
    grid_urls = grid_result.get("grid_urls", [])
    grids_generated = grid_result.get("grids_generated", len(grid_urls))
    failed_beats = grid_result.get("failed_beats", [])
    total_cost = grid_result.get("total_cost", 0)

    if failed_beats:
        print(f"  ⚠️ Partial: {grids_generated}/{beat_count} grids (failed: {failed_beats})")
    else:
        print(f"  ✅ Complete: {beat_count} beats, {len(grid_urls)} grids generated")

    # Update status to Ready For Storyboard Extraction
    pipeline._update_status(Statuses.READY_STORYBOARD_EXTRACTION)
    print(f"  ✅ Status updated to: {Statuses.READY_STORYBOARD_EXTRACTION}")

    # Notify with results
    status_emoji = "✅" if not failed_beats else "⚠️"
    notify_msg = (
        f"{status_emoji} Storyboard grids ready for *{pipeline.video_title}*\n"
        f"• {beat_count} beats, {len(grid_urls)} grids generated\n"
        f"• Cost: ~${total_cost:.2f}\n"
        f"• *Review grids in Airtable, then run next step to extract panels*"
    )
    if failed_beats:
        notify_msg += f"\n• ⚠️ Failed beats: {failed_beats}"

    pipeline.slack.notify(notify_msg)

    result = {
        "bot": "Storyboard Bot",
        "video_title": pipeline.video_title,
        "beat_count": beat_count,
        "grid_count": len(grid_urls),
        "total_cost": total_cost,
        "new_status": Statuses.READY_STORYBOARD_EXTRACTION,
    }
    if failed_beats:
        result["failed_beats"] = failed_beats

    return result
