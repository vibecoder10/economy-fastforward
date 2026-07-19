"""Thumbnail generation step — creates matched thumbnail + title pair.

Reads: Idea record (Video Title, Summary, Framework Angle, style overrides)
Writes: Thumbnail attachment + Video Title to Ideas table, PNG to Drive
Advances: Ready For Thumbnail → Ready To Render
Clients: anthropic, image_client, google, airtable, slack
"""

import json
import os

from orchestrator.pipeline_constants import Statuses, IdeaFields, ScriptFields


async def run(pipeline) -> dict:
    """Generate matched thumbnail + title pair for the video."""
    from thumbnail.engine import ThumbnailTitleEngine

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
    # NOTE: the Supabase adapter supplies these keys with None values (unlike
    # Airtable, which omits empty fields), so .get(k, "") can still yield None
    # — coalesce, or downstream .lower() calls crash.
    video_metadata = {
        IdeaFields.VIDEO_TITLE: video_title or "",
        IdeaFields.SUMMARY: video_summary or "",
        "topic": pipeline.current_idea.get(IdeaFields.HEADLINE) or "",
        IdeaFields.FRAMEWORK_ANGLE: pipeline.current_idea.get(IdeaFields.FRAMEWORK_ANGLE) or "",
        IdeaFields.FRAMEWORK: pipeline.current_idea.get(IdeaFields.FRAMEWORK) or "",
        "tags": [],
        # Channel niche (checklist C34c, S10-4) — the fallback signal
        # select_template() uses to decide whether unmatched content still
        # belongs on Template A (a finance/geopolitics channel's home turf)
        # or the niche-neutral Template E default. Exported by
        # pipeline_executor.py's _load_prompt_overrides as CHANNEL_NICHE
        # (mirrors the VISUAL_STYLE_DESCRIPTION seam); empty for the legacy
        # Airtable-only pipeline, where select_template falls through to its
        # keyword-only checks exactly as before.
        "niche": os.environ.get("CHANNEL_NICHE", ""),
        # Gemini creative director context
        "research_payload": research_payload,
        "full_script": full_script_text,
        "ctr_history": ctr_history,
        "drive_folder_id": pipeline.project_folder_id,
    }

    # --- Generate matched title + thumbnail (3 variants + Gemini #4) ---
    override_note = f" (with style override)" if thumbnail_style_override else ""
    pipeline.slack.notify(f"🎨 Generating thumbnail + title for *{pipeline.video_title}*{override_note}...")
    engine = ThumbnailTitleEngine(
        pipeline.anthropic, pipeline.image_client,
        gemini_client=pipeline.gemini, google_client=pipeline.google,
        system_prompt_override=getattr(pipeline, "thumbnail_system_prompt", None),
        # C34d: title generation now gets its OWN resolved prompt (per-video >
        # tenant > the neutral `title` engine template) instead of silently
        # borrowing the thumbnail override above.
        title_system_prompt_override=getattr(pipeline, "title_system_prompt", None),
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
    gemini_result = result.get("gemini_result")
    # Number of Claude-prompted inputs (all URLs before the Gemini one)
    num_input_images = len(thumbnail_urls) - (1 if gemini_result and gemini_result.get("v4_url") else 0)
    print(f"  {len(thumbnail_urls)} thumbnail variant(s) generated ({num_input_images} input + {'1 master' if gemini_result else '0 master'})")

    # --- Upload Claude input variants to Google Drive ---
    # Gemini's thumbnail is already uploaded to Drive by gemini_director.py — skip it.
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

    # Build list of (label, drive_link, drive_file_id) for all thumbnails
    thumbnail_entries = []

    for i in range(num_input_images):
        image_url = thumbnail_urls[i]
        filename = f"{slug}_thumbnail_input_{i + 1}.png"
        label = f"Input Image {i + 1}"
        print(f"  Uploading {label} to Google Drive...")
        try:
            google_file = pipeline.google.upload_file_from_url(
                url=image_url,
                name=filename,
                parent_id=parent_id,
            )
            file_id = google_file.get("id", "")
            link = google_file.get("webViewLink", image_url)
            thumbnail_entries.append({"label": label, "link": link, "file_id": file_id})
            print(f"  Uploaded {label}: {link}")
        except Exception as e:
            print(f"  Failed to upload {label}: {e}")
            thumbnail_entries.append({"label": label, "link": image_url, "file_id": ""})

    # Add Gemini master image (already on Drive from gemini_director.py)
    if gemini_result and gemini_result.get("v4_url"):
        thumbnail_entries.append({
            "label": "Master Image (Gemini Analysis)",
            "link": gemini_result["v4_url"],
            "file_id": gemini_result.get("v4_file_id", ""),
        })

    drive_links = [e["link"] for e in thumbnail_entries]

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

    # --- Build Slack Block Kit message with inline image previews ---
    thumb_text_display = result['line_1'] + (f" / {result['line_2']}" if result['line_2'] else "")
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Thumbnail Options: {pipeline.video_title}"[:150]},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Title:* {result['title']}\n"
                    f"*Template:* {template_info}\n"
                    f"*Text:* {thumb_text_display}"
                ),
            },
        },
        {"type": "divider"},
    ]

    for entry in thumbnail_entries:
        file_id = entry.get("file_id", "")
        # Build a direct-access image URL for Slack previews
        if file_id:
            image_url = f"https://drive.google.com/uc?id={file_id}"
        else:
            # Already a direct URL (e.g. Gemini's public Drive link or raw API URL)
            image_url = entry["link"]

        is_master = "Master" in entry["label"]
        label_prefix = ":star: " if is_master else ""

        block = {
            "type": "image",
            "image_url": image_url,
            "alt_text": entry["label"],
            "title": {"type": "plain_text", "text": f"{label_prefix}{entry['label']}"},
        }
        blocks.append(block)

        # Add Gemini's reasoning below the master image
        if is_master and gemini_result:
            reasoning = gemini_result.get("reasoning", "")[:300]
            metaphor = gemini_result.get("visual_metaphor", "")[:200]
            if reasoning or metaphor:
                blocks.append({
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"*Metaphor:* {metaphor}"},
                        {"type": "mrkdwn", "text": f"*Reasoning:* {reasoning}"},
                    ],
                })

        blocks.append({"type": "divider"})

    # Add Drive links at the bottom for direct access
    link_lines = "\n".join(f"<{e['link']}|{e['label']}>" for e in thumbnail_entries)
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*Drive links:*\n{link_lines}"},
    })

    fallback_text = (
        f"Thumbnail + title complete for {pipeline.video_title}\n"
        f"{len(thumbnail_entries)} options generated — check Slack for image previews"
    )

    pipeline.slack.notify_blocks(fallback_text, blocks)

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
