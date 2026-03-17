"""Thumbnail generation step — creates matched thumbnail + title pair.

Reads: Idea record (Video Title, Summary, Framework Angle, style overrides)
Writes: Thumbnail attachment + Video Title to Ideas table, PNG to Drive
Advances: Ready For Thumbnail → Ready To Render
Clients: anthropic, image_client, google, airtable, slack
"""

import json

from pipeline_constants import Statuses, IdeaFields, ScriptFields


async def run(pipeline) -> dict:
    """Generate matched thumbnail + title pair for the video."""
    from thumbnail_title.engine import ThumbnailTitleEngine

    # Verify status
    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_THUMBNAIL)
        if not idea:
            return {"error": "No idea with status 'Ready For Thumbnail'"}
        pipeline._load_idea(idea)

    if pipeline.current_idea.get(IdeaFields.STATUS) != Statuses.READY_THUMBNAIL:
        return {"error": f"Idea status is '{pipeline.current_idea.get(IdeaFields.STATUS)}', expected 'Ready For Thumbnail'"}

    print(f"\n🎨 THUMBNAIL BOT: Processing '{pipeline.video_title}'")

    # Re-fetch from Airtable to pick up style overrides set after initial load
    try:
        fresh = pipeline.airtable.idea_concepts_table.get(pipeline.current_idea_id)
        if fresh:
            pipeline.current_idea.update(fresh.get("fields", {}))
    except Exception as e:
        print(f"  Could not refresh idea from Airtable: {e}")

    video_title = pipeline.current_idea.get(IdeaFields.VIDEO_TITLE, "")
    video_summary = pipeline.current_idea.get(IdeaFields.SUMMARY, "")

    # Read per-video thumbnail style override
    thumbnail_style_override = (pipeline.current_idea.get(IdeaFields.THUMBNAIL_STYLE_OVERRIDE) or "").strip()
    if thumbnail_style_override:
        print(f"  Thumbnail style override active: {thumbnail_style_override[:80]}...")

    # Read independent thumbnail text
    thumbnail_text = (pipeline.current_idea.get(IdeaFields.THUMBNAIL_TEXT) or "").strip()
    if thumbnail_text:
        print(f"  Thumbnail Text from Airtable: {thumbnail_text}")
    else:
        print(f"  No Thumbnail Text set — will auto-generate")

    # Read optional palette override
    palette_override = (pipeline.current_idea.get(IdeaFields.THUMBNAIL_PALETTE) or "").strip().lower() or None

    # --- Gather full context for Gemini creative director ---
    # Full script text (all acts)
    full_script_text = ""
    try:
        scripts = pipeline.airtable.get_scripts_by_title(pipeline.video_title)
        full_script_text = "\n\n".join(
            f"[Scene {s.get('scene', 0)}]\n{s.get(ScriptFields.SCENE_TEXT, '')}"
            for s in sorted(scripts, key=lambda x: x.get('scene', 0))
        )
    except Exception as e:
        print(f"  Could not fetch scripts for Gemini context: {e}")

    # Recent CTR history (top 5 by views)
    ctr_history = []
    try:
        all_ideas = pipeline.airtable.get_all_ideas()
        for idea in all_ideas:
            ctr = idea.get(IdeaFields.CTR)
            if ctr:
                ctr_history.append({
                    "title": idea.get(IdeaFields.VIDEO_TITLE, "")[:60],
                    "ctr": ctr,
                    "views": idea.get(IdeaFields.VIEWS, 0),
                    "thumbnail_text": idea.get(IdeaFields.THUMBNAIL_TEXT, ""),
                })
        ctr_history = sorted(ctr_history, key=lambda x: x.get("views", 0), reverse=True)[:5]
    except Exception:
        pass

    # Parse research payload
    research_payload = {}
    rp_raw = pipeline.current_idea.get(IdeaFields.RESEARCH_PAYLOAD, "")
    if rp_raw:
        try:
            research_payload = json.loads(rp_raw) if isinstance(rp_raw, str) else rp_raw
        except (json.JSONDecodeError, TypeError):
            pass

    # Build metadata for template selection + Gemini context
    video_metadata = {
        IdeaFields.VIDEO_TITLE: video_title,
        IdeaFields.SUMMARY: video_summary,
        "topic": pipeline.current_idea.get(IdeaFields.HEADLINE, ""),
        IdeaFields.FRAMEWORK_ANGLE: pipeline.current_idea.get(IdeaFields.FRAMEWORK_ANGLE, ""),
        IdeaFields.FRAMEWORK: pipeline.current_idea.get(IdeaFields.FRAMEWORK, ""),
        "tags": [],
        # Gemini creative director context
        "research_payload": research_payload,
        "full_script": full_script_text,
        "ctr_history": ctr_history,
    }

    # --- Generate matched title + thumbnail (3 variants + Gemini #4) ---
    override_note = f" (with style override)" if thumbnail_style_override else ""
    pipeline.slack.notify(f"🎨 Generating thumbnail + title for *{pipeline.video_title}*{override_note}...")
    engine = ThumbnailTitleEngine(
        pipeline.anthropic, pipeline.image_client,
        gemini_client=pipeline.gemini, google_client=pipeline.google,
    )

    try:
        result = await engine.generate(
            video_metadata,
            thumbnail_style_override=thumbnail_style_override or None,
            thumbnail_text=thumbnail_text or None,
            palette_override=palette_override,
        )
    except Exception as e:
        error_msg = f"Thumbnail/title generation failed for '{pipeline.video_title}': {e}"
        print(f"  {error_msg}")
        pipeline.slack.notify(f"Thumbnail Bot STOPPED: {error_msg}\nStatus NOT advanced.")
        return {
            "status": "failed",
            "bot": "Thumbnail Bot",
            "video_title": pipeline.video_title,
            "error": error_msg,
        }

    # --- Save generated prompt and title metadata to Airtable ---
    pipeline.airtable.update_idea_field(pipeline.current_idea_id, IdeaFields.THUMBNAIL_PROMPT, result["thumbnail_prompt"])
    if result.get("title"):
        pipeline.airtable.update_idea_field(pipeline.current_idea_id, IdeaFields.VIDEO_TITLE, result["title"])

    # --- Warn Slack if thumbnail text was auto-generated ---
    if result.get("thumbnail_text_auto_generated"):
        auto_text = f"{result['line_1']}" + (f" {result['line_2']}" if result['line_2'] else "")
        pipeline.slack.notify(
            f"No Thumbnail Text set for *{pipeline.video_title}* — auto-generated: *{auto_text}*\n"
            f"Set `Thumbnail Text` field in Airtable to override."
        )

    # --- Check if thumbnail generation succeeded ---
    if result["needs_manual_review"]:
        error_msg = (
            f"Thumbnail generation failed after {result['thumbnail_attempt']} attempts "
            f"for '{pipeline.video_title}'. Flagged for manual review."
        )
        print(f"  {error_msg}")
        pipeline.slack.notify(
            f"Thumbnail Bot needs manual review for *{pipeline.video_title}*\n"
            f"Template: {result['template_name']}\n"
            f"Title: {result['title']}\n"
            f"Status NOT advanced."
        )
        return {
            "status": "manual_review",
            "bot": "Thumbnail Bot",
            "video_title": pipeline.video_title,
            "generated_title": result["title"],
            "template_used": result["template_used"],
            "error": error_msg,
        }

    thumbnail_urls = result["thumbnail_urls"]
    print(f"  {len(thumbnail_urls)} thumbnail variant(s) generated")

    # --- Upload all variants to Google Drive ---
    if pipeline.project_folder_id:
        parent_id = pipeline.project_folder_id
    else:
        folder = pipeline.google.search_folder(pipeline.video_title)
        if folder:
            parent_id = folder["id"]
        else:
            print("  Project folder not found, uploading to root.")
            parent_id = None

    slug = video_title.lower().replace(" ", "_").replace("'", "")[:50]
    drive_links = []

    for i, image_url in enumerate(thumbnail_urls, 1):
        filename = f"{slug}_thumbnail_v{i}.png"
        print(f"  Uploading variant {i} to Google Drive...")
        try:
            google_file = pipeline.google.upload_file_from_url(
                url=image_url,
                name=filename,
                parent_id=parent_id,
            )
            link = google_file.get("webViewLink", image_url)
            drive_links.append(link)
            print(f"  Uploaded variant {i}: {link}")
        except Exception as e:
            print(f"  Failed to upload variant {i}: {e}")
            drive_links.append(image_url)

    # --- Save first thumbnail to Airtable (primary) ---
    pipeline.airtable.update_idea_thumbnail(pipeline.current_idea_id, thumbnail_urls[0])
    print("  Saved primary thumbnail to Airtable")

    # --- Update status ---
    pipeline._update_status(Statuses.READY_TO_RENDER)
    print(f"  Status updated to: {Statuses.READY_TO_RENDER}")

    template_info = result['template_name']
    if thumbnail_style_override:
        override_mode = "REPLACE" if thumbnail_style_override.upper().startswith("REPLACE:") else "APPEND"
        template_info = f"{result['template_name']} ({override_mode} override active)"

    variant_links_parts = []
    for i, link in enumerate(drive_links, 1):
        if i == len(drive_links) and result.get("gemini_result"):
            reasoning = result["gemini_result"].get("reasoning", "")[:200]
            variant_links_parts.append(
                f"  ⭐ Option {i} (Gemini Director): {link}\n"
                f"     💡 {reasoning}"
            )
        else:
            variant_links_parts.append(f"  Option {i}: {link}")
    variant_links = "\n".join(variant_links_parts)
    pipeline.slack.notify(
        f"Thumbnail + title complete for *{pipeline.video_title}*\n"
        f"Title: {result['title']}\n"
        f"Template: {template_info}\n"
        f"Text: {result['line_1']}" + (f" / {result['line_2']}" if result['line_2'] else "") + f"\n"
        f"{len(drive_links)} options generated — pick your favorite:\n{variant_links}"
    )

    return {
        "bot": "Thumbnail Bot",
        "video_title": pipeline.video_title,
        "new_status": Statuses.READY_TO_RENDER,
        "thumbnail_url": drive_links[0] if drive_links else None,
        "thumbnail_urls": drive_links,
        "generated_title": result["title"],
        "caps_word": result["caps_word"],
        "formula_used": result["formula_used"],
        "template_used": result["template_used"],
        "template_name": result["template_name"],
        "line_1": result["line_1"],
        "line_2": result["line_2"],
        "thumbnail_attempt": result["thumbnail_attempt"],
        "validation": result["validation"],
        "thumbnail_text_auto_generated": result.get("thumbnail_text_auto_generated", False),
    }
