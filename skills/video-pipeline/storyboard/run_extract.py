"""Storyboard extraction step — extracts panels from grids and upscales.

Reads: Storyboard Preview grids from Ideas table
Writes: Extracted panels to Images table (Image attachment)
Advances: Ready For Storyboard Extraction → Ready For Video Scripts
Clients: airtable, image_client, google

This step runs AFTER the user reviews the generated grids.
"""

from orchestrator.pipeline_constants import Statuses


async def run(pipeline) -> dict:
    """Extract panels from storyboard grids (Phase 2)."""
    from storyboard.bot import run_storyboard_extract

    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_STORYBOARD_EXTRACTION)
        if not idea:
            return {"error": "No idea with status 'Ready For Storyboard Extraction'", "bot": "Storyboard Extract"}
        pipeline._load_idea(idea)

    # Check storyboard status and grids from Scripts table
    script_records = pipeline.airtable.get_scripts_by_title(pipeline.video_title)
    if not script_records:
        return {
            "error": f"No script found for '{pipeline.video_title}'",
            "bot": "Storyboard Extract",
            "video_title": pipeline.video_title,
        }

    first_script = script_records[0].get("fields", script_records[0])
    sb_status = first_script.get("Storyboard Status", "none") or "none"

    # If already extracted, skip to next status
    if sb_status == "extracted":
        print(f"  ✅ Storyboards already extracted — advancing status")
        pipeline._update_status(Statuses.READY_VIDEO_SCRIPTS)
        return {
            "bot": "Storyboard Extract",
            "video_title": pipeline.video_title,
            "new_status": Statuses.READY_VIDEO_SCRIPTS,
            "skipped": True,
        }

    # Check that grids exist (Storyboard 1/2/3 in Scripts table)
    has_grids = any(first_script.get(f"Storyboard {i}", []) for i in [1, 2, 3])
    if not has_grids:
        return {
            "error": "No storyboard grids found — run storyboard images first",
            "bot": "Storyboard Extract",
            "video_title": pipeline.video_title,
        }

    print(f"\n🖼️ STORYBOARD EXTRACT: Processing '{pipeline.video_title}'")
    pipeline.slack.notify(f"🖼️ Extracting panels from storyboard grids for: *{pipeline.video_title}*")

    # Get or create project folder
    if not pipeline.project_folder_id:
        folder = pipeline.google.get_or_create_folder(pipeline.video_title)
        pipeline.project_folder_id = folder["id"]

    # Build idea_record in expected format
    idea_record = {
        "id": pipeline.current_idea_id,
        "fields": pipeline.current_idea,
    }

    # Phase 2: Extract panels from grids
    print("  🖼️ Extracting and upscaling panels...")
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
            "bot": "Storyboard Extract",
            "video_title": pipeline.video_title,
        }

    panel_count = extract_result.get("panel_count", 0)
    total_cost = extract_result.get("total_cost", 0)
    print(f"  ✅ Extracted {panel_count} panels")

    # Update status
    pipeline._update_status(Statuses.READY_VIDEO_SCRIPTS)
    print(f"  ✅ Status updated to: {Statuses.READY_VIDEO_SCRIPTS}")

    pipeline.slack.notify(
        f"✅ Storyboard extraction complete for *{pipeline.video_title}*\n"
        f"• {panel_count} panels extracted\n"
        f"• Cost: ~${total_cost:.2f}"
    )

    return {
        "bot": "Storyboard Extract",
        "video_title": pipeline.video_title,
        "panel_count": panel_count,
        "total_cost": total_cost,
        "new_status": Statuses.READY_VIDEO_SCRIPTS,
    }
