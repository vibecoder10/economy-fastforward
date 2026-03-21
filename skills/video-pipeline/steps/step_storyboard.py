"""Storyboard generation step — generates contact sheets and extracts panels.

Reads: Script records, Story Bible from Airtable
Writes: Storyboard grids to Ideas table, extracted panels to Images table
Advances: Ready For Storyboards → Ready For Video Scripts
Clients: anthropic, airtable, image_client, google
"""

from pipeline_constants import Statuses, IdeaFields


async def run(pipeline) -> dict:
    """Generate storyboards: Phase 1 (grids) + Phase 2 (extract panels)."""
    from storyboard_bot import run_storyboard_grids, run_storyboard_extract

    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_STORYBOARDS)
        if not idea:
            return {"error": "No idea with status 'Ready For Storyboards'", "bot": "Storyboard Bot"}
        pipeline._load_idea(idea)

    fields = pipeline.current_idea.get("fields", pipeline.current_idea)
    sb_status = fields.get("Storyboard Status", "none")

    # If already extracted, skip to next status
    if sb_status == "extracted":
        print(f"  ✅ Storyboards already extracted — advancing status")
        pipeline._update_status(Statuses.READY_VIDEO_SCRIPTS)
        return {
            "bot": "Storyboard Bot",
            "video_title": pipeline.video_title,
            "new_status": Statuses.READY_VIDEO_SCRIPTS,
            "skipped": True,
        }

    print(f"\n🎬 STORYBOARD BOT: Processing '{pipeline.video_title}'")
    pipeline.slack.notify(f"🎬 Starting storyboard generation for: *{pipeline.video_title}*")

    # Get or create project folder
    if not pipeline.project_folder_id:
        folder = pipeline.google.get_or_create_folder(pipeline.video_title)
        pipeline.project_folder_id = folder["id"]

    # Build idea_record in expected format
    idea_record = {
        "id": pipeline.current_idea_id,
        "fields": pipeline.current_idea,
    }

    # Phase 1: Generate contact sheet grids
    print("  📐 Phase 1: Generating contact sheet grids...")
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
    print(f"  ✅ Phase 1 complete: {beat_count} beats, {len(grid_urls)} grids generated")

    # Refresh idea record to get updated Storyboard Preview field
    updated_idea = pipeline.airtable.get_idea(pipeline.current_idea_id)
    if updated_idea:
        idea_record = {
            "id": pipeline.current_idea_id,
            "fields": updated_idea.get("fields", updated_idea),
        }

    # Phase 2: Extract panels from grids
    print("  🖼️ Phase 2: Extracting and upscaling panels...")
    extract_result = await run_storyboard_extract(
        idea_record=idea_record,
        airtable_client=pipeline.airtable,
        image_client=pipeline.image_client,
        google_client=pipeline.google,
    )

    if extract_result.get("error"):
        error_msg = extract_result["error"]
        pipeline.slack.notify(f"❌ Storyboard extraction failed for *{pipeline.video_title}*: {error_msg}")
        return {
            "error": error_msg,
            "bot": "Storyboard Bot",
            "video_title": pipeline.video_title,
        }

    panel_count = extract_result.get("panel_count", 0)
    total_cost = extract_result.get("total_cost", 0)
    print(f"  ✅ Phase 2 complete: {panel_count} panels extracted")

    # Update status
    pipeline._update_status(Statuses.READY_VIDEO_SCRIPTS)
    print(f"  ✅ Status updated to: {Statuses.READY_VIDEO_SCRIPTS}")

    pipeline.slack.notify(
        f"✅ Storyboard complete for *{pipeline.video_title}*\n"
        f"• {beat_count} beats, {len(grid_urls)} grids\n"
        f"• {panel_count} panels extracted\n"
        f"• Cost: ~${total_cost:.2f}"
    )

    return {
        "bot": "Storyboard Bot",
        "video_title": pipeline.video_title,
        "beat_count": beat_count,
        "grid_count": len(grid_urls),
        "panel_count": panel_count,
        "total_cost": total_cost,
        "new_status": Statuses.READY_VIDEO_SCRIPTS,
    }
