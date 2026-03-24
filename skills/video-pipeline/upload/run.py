"""YouTube upload step — generates SEO metadata and uploads as unlisted draft.

Reads: Idea record (Video Title, Hook Script, scripts), Final Video from Drive
Writes: SEO metadata to Ideas table, video to YouTube
Advances: Rendered → Uploaded (Draft)
Clients: anthropic, airtable, google, slack
"""

from orchestrator.pipeline_constants import IdeaFields, Statuses


async def run(pipeline) -> dict:
    """Generate SEO metadata and upload video to YouTube as unlisted draft."""
    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.RENDERED)
        if not idea:
            return {"error": "No idea with status 'Rendered'"}
        pipeline._load_idea(idea)

    print(f"\n📺 YOUTUBE UPLOAD BOT: Processing '{pipeline.video_title}'")
    pipeline.slack.notify(
        f"📺 *YouTube upload starting:* _{pipeline.video_title}_\n"
        f"Generating SEO description and uploading as unlisted draft..."
    )

    # --- STEP 1: Generate SEO metadata ---
    print("  Generating SEO metadata...")
    try:
        from upload.seo_generator import SEOGenerator

        seo = SEOGenerator(pipeline.anthropic)
        scripts = pipeline.airtable.get_scripts_by_title(pipeline.video_title)
        hook = pipeline.current_idea.get(IdeaFields.HOOK_SCRIPT, "")

        seo_result = seo.generate(
            title=pipeline.video_title,
            hook=hook,
            scripts=scripts,
        )

        # Store SEO fields in Airtable
        pipeline.airtable.update_idea_fields(pipeline.current_idea_id, {
            IdeaFields.SEO_DESCRIPTION: seo_result["description"],
            IdeaFields.SEO_TAGS: seo_result["tags"],
            IdeaFields.SEO_HASHTAGS: seo_result["hashtags"],
        })
        print(f"  SEO metadata saved to Airtable")
        print(f"    Hook line: {seo_result.get('hook_line', '')[:100]}")
    except Exception as e:
        print(f"  Warning: SEO generation failed: {e}")
        print(f"  Continuing with basic description...")
        fallback_desc = pipeline.current_idea.get(IdeaFields.HOOK_SCRIPT, pipeline.video_title)
        pipeline.airtable.update_idea_field(
            pipeline.current_idea_id, IdeaFields.SEO_DESCRIPTION, fallback_desc
        )
        seo_result = {
            "description": fallback_desc,
            "tags": "",
            "hashtags": "",
        }

    # Reload idea to get updated fields
    updated_ideas = pipeline.airtable.get_ideas_by_status(Statuses.RENDERED, limit=10)
    idea_fresh = None
    for i in updated_ideas:
        if i["id"] == pipeline.current_idea_id:
            idea_fresh = i
            break
    if not idea_fresh:
        idea_fresh = pipeline.current_idea
        idea_fresh[IdeaFields.SEO_DESCRIPTION] = seo_result["description"]
        idea_fresh[IdeaFields.SEO_TAGS] = seo_result["tags"]

    # --- STEP 2: Upload to YouTube ---
    print("  Uploading to YouTube...")
    try:
        from upload.youtube_uploader import YouTubeUploader

        yt = YouTubeUploader()
        upload_result = yt.upload_from_drive(
            google_client=pipeline.google,
            airtable_client=pipeline.airtable,
            idea=idea_fresh,
        )

        if upload_result.get("error"):
            raise Exception(upload_result["error"])

    except FileNotFoundError as e:
        print(f"  YouTube credentials not configured: {e}")
        print(f"  SEO metadata saved. Upload skipped (run youtube_auth.py first).")
        pipeline.slack.notify(
            f"⚠️ *YouTube upload skipped:* _{pipeline.video_title}_\n"
            f"YouTube credentials not configured. SEO metadata saved.\n"
            f"Run `python youtube_auth.py` on VPS, then re-run pipeline."
        )
        return {
            "bot": "YouTube Upload Bot",
            "video_title": pipeline.video_title,
            "warning": "YouTube credentials not configured",
            "new_status": Statuses.RENDERED,
        }
    except Exception as e:
        error_msg = f"YouTube upload failed: {e}"
        print(f"  {error_msg}")
        pipeline.slack.notify(
            f"❌ *YouTube upload FAILED:* _{pipeline.video_title}_\n"
            f"```{e}```\n"
            f"SEO metadata saved. Fix and re-run."
        )
        return {
            "status": "failed",
            "bot": "YouTube Upload Bot",
            "video_title": pipeline.video_title,
            "error": error_msg,
        }

    # --- STEP 3: Update status and notify ---
    pipeline._update_status(Statuses.UPLOADED_DRAFT)

    video_url = upload_result.get("video_url", "")
    folder_id = pipeline.current_idea.get(IdeaFields.DRIVE_FOLDER_ID, "")
    folder_url = (
        f"https://drive.google.com/drive/folders/{folder_id}"
        if folder_id else
        pipeline.current_idea.get(IdeaFields.DRIVE_FOLDER_LINK, "")
    )
    description_preview = seo_result.get("description", "")[:100]

    pipeline.slack.notify(
        f"📺 *Video Ready for Review!*\n\n"
        f'"{pipeline.video_title}"\n\n'
        f"🎬 *YouTube Draft:* {video_url}\n"
        f"📁 *Drive Folder:* {folder_url}\n"
        f"📝 *Description preview:* {description_preview}...\n\n"
        f"When ready, open YouTube Studio and set to Public."
    )

    print(f"  Status updated to: {Statuses.UPLOADED_DRAFT}")
    print(f"  YouTube: {video_url}")

    return {
        "bot": "YouTube Upload Bot",
        "video_title": pipeline.video_title,
        "new_status": Statuses.UPLOADED_DRAFT,
        "video_url": video_url,
    }
