"""Script generation step — translates research brief into a 6-act script.

Reads: Idea record from Airtable (Research Payload, Framework Angle, etc.)
Writes: Script records to Scripts table, Google Doc, Airtable Script field
Advances: Ready For Scripting → Ready For Voice
Clients: anthropic, airtable, google, slack
"""

import asyncio
import json

from orchestrator.pipeline_constants import IdeaFields, Statuses


async def run(pipeline, brief: dict = None) -> dict:
    """Generate a script from a research brief."""
    from script.brief_translator import translate_brief

    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_SCRIPTING)
        if not idea:
            return {"error": "No idea at 'Ready For Scripting'. Set an idea's status to 'Ready For Scripting' first."}
        pipeline._load_idea(idea)

    # === CHECK: Video Length must be set before script generation ===
    if not getattr(pipeline, '_duration_was_set', True):
        error_msg = (
            f"⚠️ *No video length set for '{pipeline.video_title}'*\n"
            f"Set 'Video Length (min)' in Airtable before generating script.\n"
            f"Currently defaulting to 10 minutes — script word count will be wrong."
        )
        print(f"\n❌ {error_msg}")
        try:
            pipeline.slack.send_message(error_msg)
        except Exception:
            pass
        return {
            "error": "Video Length (min) not set in Airtable",
            "status": "blocked",
            "video_title": pipeline.video_title,
        }

    print(f"\n📜 BRIEF TRANSLATOR: Processing '{pipeline.video_title}'")

    # --- Google Drive folder (same as legacy script bot) ---
    folder = pipeline.google.get_or_create_folder(pipeline.video_title)
    pipeline.project_folder_id = folder["id"]
    folder_url = f"https://drive.google.com/drive/folders/{pipeline.project_folder_id}"
    try:
        pipeline.airtable.update_idea_fields(pipeline.current_idea_id, {
            IdeaFields.DRIVE_FOLDER_LINK: folder_url,
            IdeaFields.DRIVE_FOLDER_ID: pipeline.project_folder_id,
        })
    except Exception as e:
        print(f"  ⚠️ Could not save Drive folder to Airtable: {e}")

    # Build brief from Airtable idea fields if not provided
    if brief is None:
        idea = pipeline.current_idea

        # Check for research_payload (from research agent)
        research_payload_raw = idea.get(IdeaFields.RESEARCH_PAYLOAD, "")
        if research_payload_raw:
            try:
                research_payload = json.loads(research_payload_raw)
                print("  📚 Found research payload — using as primary source material")
                framework_angle = idea.get(IdeaFields.FRAMEWORK_ANGLE, "") or research_payload.get("themes", "")
                brief = {
                    # Canonical title from Airtable — always use this
                    "video_title": idea.get(IdeaFields.VIDEO_TITLE, ""),
                    "headline": research_payload.get("headline", idea.get(IdeaFields.VIDEO_TITLE, "")),
                    "thesis": research_payload.get("thesis", ""),
                    "executive_hook": research_payload.get("executive_hook", idea.get(IdeaFields.HOOK_SCRIPT, "")),
                    "fact_sheet": research_payload.get("fact_sheet", ""),
                    "historical_parallels": research_payload.get("historical_parallels", ""),
                    "framework_analysis": research_payload.get("framework_analysis", ""),
                    "character_dossier": research_payload.get("character_dossier", ""),
                    "narrative_arc": research_payload.get("narrative_arc", ""),
                    "counter_arguments": research_payload.get("counter_arguments", ""),
                    "visual_seeds": research_payload.get("visual_seeds", ""),
                    "source_bibliography": research_payload.get("source_bibliography", ""),
                    "framework_angle": framework_angle,
                    "title_options": research_payload.get("title_options", idea.get(IdeaFields.VIDEO_TITLE, "")),
                    "thumbnail_concepts": research_payload.get("thumbnail_concepts", ""),
                    "source_urls": idea.get("Source URLs", "") or research_payload.get("source_bibliography", ""),
                    "psychological_angles": research_payload.get("psychological_angles", ""),
                    "_research_enriched": True,
                }
                print(f"  🎯 Framework Angle: {framework_angle or '(not set)'}")

                # Inject Writer Guidance if present on the idea record
                writer_guidance = idea.get(IdeaFields.WRITER_GUIDANCE, "")
                if writer_guidance:
                    brief["writer_guidance"] = writer_guidance
                    print(f"  📝 Writer Guidance injected")
            except (json.JSONDecodeError, TypeError) as e:
                print(f"  ⚠️ Could not parse research payload: {e}")
                research_payload_raw = ""

        if not research_payload_raw:
            framework_angle = idea.get(IdeaFields.FRAMEWORK_ANGLE, "")
            brief = {
                # Canonical title from Airtable — always use this
                "video_title": idea.get(IdeaFields.VIDEO_TITLE, ""),
                "headline": idea.get(IdeaFields.VIDEO_TITLE, ""),
                "thesis": idea.get(IdeaFields.THESIS, "") or idea.get(IdeaFields.FUTURE_PREDICTION, ""),
                "executive_hook": idea.get(IdeaFields.EXECUTIVE_HOOK, "") or idea.get(IdeaFields.HOOK_SCRIPT, ""),
                "fact_sheet": idea.get(IdeaFields.WRITER_GUIDANCE, ""),
                "historical_parallels": idea.get(IdeaFields.PAST_CONTEXT, ""),
                "framework_analysis": idea.get(IdeaFields.PRESENT_PARALLEL, ""),
                "character_dossier": "",
                "narrative_arc": idea.get(IdeaFields.FUTURE_PREDICTION, ""),
                "counter_arguments": "",
                "visual_seeds": idea.get(IdeaFields.THUMBNAIL_PROMPT, ""),
                "source_bibliography": idea.get(IdeaFields.REFERENCE_URL, ""),
                "framework_angle": framework_angle,
                "title_options": idea.get(IdeaFields.VIDEO_TITLE, ""),
                "thumbnail_concepts": idea.get(IdeaFields.THUMBNAIL_PROMPT, ""),
                "source_urls": idea.get("Source URLs", "") or idea.get(IdeaFields.REFERENCE_URL, ""),
            }
            print(f"  🎯 Framework Angle: {framework_angle or '(not set — legacy idea)'}")

    result = await translate_brief(
        anthropic_client=pipeline.anthropic,
        airtable_client=pipeline.airtable,
        idea_record_id=pipeline.current_idea_id,
        brief=brief,
        slack_client=pipeline.slack,
        google_client=pipeline.google,
        project_folder_id=pipeline.project_folder_id,
        video_config=pipeline.video_config,
        script_system_prompt_override=getattr(pipeline, "script_system_prompt", None),
        format_contract=getattr(pipeline, "script_format_contract", None),
        allowed_speakers=getattr(pipeline, "script_allowed_speakers", None),
    )

    if result["status"] == "success":
        # Update status to Ready For Voice
        pipeline._update_status(Statuses.READY_VOICE)
        print(f"  ✅ Status updated to: {Statuses.READY_VOICE}")

        if result.get("doc_url"):
            print(f"  📄 Google Doc: {result['doc_url']}")

        # Phase 2: Title refinement DISABLED — user wants to keep their chosen title
        # Previously called: await _refine_title_post_script(pipeline)

        pipeline.slack.notify(
            f"📜 Script complete: *{pipeline.video_title}*\n"
            f"Status: Ready For Voice"
        )
    else:
        print(f"  ❌ Translation failed: {result.get('error', result['status'])}")

    return {
        "bot": "Brief Translator",
        "video_title": pipeline.video_title,
        "status": result["status"],
        "doc_url": result.get("doc_url"),
        "new_status": Statuses.READY_VOICE if result["status"] == "success" else None,
    }


async def _refine_title_post_script(pipeline):
    """Phase 2 title refinement — non-blocking post-script step."""
    from research.agent import refine_title_post_script

    try:
        result = await asyncio.wait_for(
            refine_title_post_script(
                anthropic_client=pipeline.anthropic,
                airtable_client=pipeline.airtable,
                record_id=pipeline.current_idea_id,
            ),
            timeout=30.0,
        )
        if result.get("should_switch"):
            old_title = result["old_title"]
            new_title = result["new_title"]
            pipeline.video_title = new_title
            print(
                f"  📝 Title refined: '{old_title}' → '{new_title}' "
                f"(score: {result.get('score', '?')})"
            )
            try:
                pipeline.slack.send_message(
                    f"📝 Title refined for *{old_title}*\n"
                    f"→ New title: *{new_title}* (score: {result.get('score', '?')})\n"
                    f"→ Thumbnail: {result.get('thumbnail_text', '')}"
                )
            except Exception:
                pass  # Slack notification is non-blocking
        else:
            print(f"  📝 Title refinement: kept current title (no better option found)")
    except Exception as e:
        # Non-blocking — title refinement failure should NOT stop the pipeline
        print(f"  ⚠️ Title refinement failed (non-blocking): {e}")
