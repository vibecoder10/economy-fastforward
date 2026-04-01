"""Storyboard prompt generation step — generates prompts via Claude.

Reads: Script records, Story Bible from Airtable
Writes: Storyboard Prompts field (Long Text)
Advances: Ready For Storyboards → Ready For Storyboard Images
Clients: anthropic, airtable

NOTE: This step ONLY generates prompts. Image generation is step_storyboard_images.py.
"""

from orchestrator.pipeline_constants import Statuses


async def run(pipeline, scene_filter=None, progress_callback=None) -> dict:
    """Generate storyboard prompts via Claude (Phase 1A).

    Args:
        scene_filter: If set, only generate prompts for this scene number.
        progress_callback: Called with (message: str) to report progress.
    """
    from storyboard.bot import run_storyboard_prompts

    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_STORYBOARDS)
        if not idea:
            return {"error": "No idea with status 'Ready For Storyboards'", "bot": "Storyboard Prompts"}
        pipeline._load_idea(idea)

    # Check storyboard status from Scripts table
    script_records = pipeline.airtable.get_scripts_by_title(pipeline.video_title)
    sb_status = "none"
    if script_records:
        first_script = script_records[0].get("fields", script_records[0])
        sb_status = first_script.get("Storyboard Status", "none") or "none"

    # If prompts already generated, skip to images status
    if sb_status == "prompts_ready":
        print(f"  ✅ Storyboard prompts already generated — advancing to images")
        pipeline._update_status(Statuses.READY_STORYBOARD_IMAGES)
        return {
            "bot": "Storyboard Prompts",
            "video_title": pipeline.video_title,
            "new_status": Statuses.READY_STORYBOARD_IMAGES,
            "skipped": True,
        }

    # Guard: image prompts must exist before storyboard prompts can be generated.
    # Without per-segment image prompts, storyboard beat prompts lack visual specificity
    # and produce overlapping/repetitive grids.
    image_records = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
    if image_records:
        prompts_present = sum(
            1 for r in image_records
            if (r.get("fields", r).get("Image Prompt") or "").strip()
        )
        total_images = len(image_records)
        if prompts_present < total_images * 0.5:
            error_msg = (
                f"Image prompts missing: only {prompts_present}/{total_images} segments "
                f"have prompts. Generate image prompts first — storyboard grids built "
                f"without them produce repetitive visuals."
            )
            print(f"  ❌ {error_msg}")
            pipeline.slack.notify(f"⚠️ Storyboard blocked for *{pipeline.video_title}*: {error_msg}")
            return {
                "error": error_msg,
                "bot": "Storyboard Prompts",
                "video_title": pipeline.video_title,
            }

    print(f"\n📝 STORYBOARD PROMPTS: Generating for '{pipeline.video_title}'")
    pipeline.slack.notify(f"📝 Generating storyboard prompts for: *{pipeline.video_title}*")

    # Build idea_record in expected format
    idea_record = {
        "id": pipeline.current_idea_id,
        "fields": pipeline.current_idea,
    }

    # Generate prompts via Claude
    result = await run_storyboard_prompts(
        idea_record=idea_record,
        airtable_client=pipeline.airtable,
        anthropic_client=pipeline.anthropic,
        slack_client=pipeline.slack,
        scene_filter=scene_filter,
        progress_callback=progress_callback,
    )

    if result.get("error"):
        error_msg = result["error"]
        pipeline.slack.notify(f"❌ Storyboard prompts failed for *{pipeline.video_title}*: {error_msg}")
        return {
            "error": error_msg,
            "bot": "Storyboard Prompts",
            "video_title": pipeline.video_title,
        }

    beat_count = result.get("beat_count", 0)
    prompts_generated = result.get("prompts_generated", 0)
    total_cost = result.get("total_cost", 0)

    print(f"  ✅ Generated {prompts_generated} prompts for {beat_count} beats")

    # Update status to Ready For Storyboard Images
    pipeline._update_status(Statuses.READY_STORYBOARD_IMAGES)
    print(f"  ✅ Status updated to: {Statuses.READY_STORYBOARD_IMAGES}")

    pipeline.slack.notify(
        f"✅ Storyboard prompts ready for *{pipeline.video_title}*\n"
        f"• {beat_count} beats, {prompts_generated} prompts generated\n"
        f"• Cost: ~${total_cost:.2f}\n"
        f"• *Review prompts in Airtable, then run next step to generate images*"
    )

    return {
        "bot": "Storyboard Prompts",
        "video_title": pipeline.video_title,
        "beat_count": beat_count,
        "prompts_generated": prompts_generated,
        "total_cost": total_cost,
        "new_status": Statuses.READY_STORYBOARD_IMAGES,
    }
