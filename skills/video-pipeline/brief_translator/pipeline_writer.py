"""Pipeline Table Write (Step 4).

Maps translated fields from the research brief to the existing pipeline table
schema and writes the scene list to a JSON file for the image prompt engine.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from pipeline_constants import IdeaFields


# Default scene output directory (project-relative fallback)
DEFAULT_SCENE_DIR = str(Path(__file__).parent.parent / "scenes")


def build_writer_guidance(brief: dict, accent_color: str, scene_count: int) -> str:
    """Construct the Writer Guidance field from brief metadata."""
    counter_args = brief.get("counter_arguments", "")
    if len(counter_args) > 200:
        counter_args = counter_args[:200] + "..."

    return (
        f"Framework: {brief.get('framework_angle', 'N/A')}\n"
        f"Thesis: {brief.get('thesis', 'N/A')}\n"
        f"Accent Color: {accent_color}\n"
        f"Total Scenes: {scene_count}\n"
        f"Style Distribution: ~60% Dossier, ~22% Schema, ~18% Echo\n"
        f"\nKey Visual Direction:\n"
        f"- Dossier: Cinematic photorealism, Rembrandt lighting, {accent_color} accent\n"
        f"- Schema: Glowing data overlays on dark backgrounds\n"
        f"- Echo: Candlelit historical scenes with painterly texture\n"
        f"\nCounter-argument to address: {counter_args}"
    )


def build_original_dna(brief: dict, idea_record_id: str, accent_color: str, scene_count: int) -> str:
    """Build the Original DNA JSON string linking back to the research brief."""
    return json.dumps({
        "meta_data": {
            "title": brief.get("headline", ""),
            "thesis": brief.get("thesis", ""),
            "framework": brief.get("framework_angle", ""),
            "accent_color": accent_color,
            "source_idea_id": idea_record_id,
            "scene_count": scene_count,
            "research_date": brief.get("date_deep_dived", ""),
            "translated_at": datetime.now().isoformat(),
        }
    })


def select_video_title(brief: dict) -> str:
    """Select the best video title using the priority order.

    Priority:
    1. title_options from research_payload / discovery scanner (best one)
    2. Headline field from Airtable record
    3. headline from research brief
    4. Generate from title_patterns.json (if available)
    5. Fallback to "Untitled"

    NEVER outputs a generic journalism headline. The title must match
    Economy FastForward channel voice: Machiavellian, dark power dynamics,
    pattern/cycle framing.
    """
    # Priority 1: title_options (from discovery scanner or research agent)
    title_options = brief.get("title_options", "")
    if title_options:
        # title_options can be a string (newline-separated) or already parsed
        if isinstance(title_options, list):
            # List of dicts with "title" key (from discovery scanner)
            for opt in title_options:
                if isinstance(opt, dict) and opt.get("title"):
                    return opt["title"]
                elif isinstance(opt, str) and opt.strip():
                    return opt.strip()
        elif isinstance(title_options, str):
            # Try to parse as JSON first (may be a serialized list)
            try:
                parsed = json.loads(title_options)
                if isinstance(parsed, list):
                    for opt in parsed:
                        if isinstance(opt, dict) and opt.get("title"):
                            return opt["title"]
                        elif isinstance(opt, str) and opt.strip():
                            return opt.strip()
            except (json.JSONDecodeError, TypeError):
                pass

            # Newline-separated titles (from research agent)
            first_line = title_options.strip().split("\n")[0].strip()
            # Strip numbering like "1. " or "- " prefixes
            first_line = re.sub(r'^[\d]+[\.\)]\s*', '', first_line)
            first_line = first_line.lstrip("- •*").strip()
            if first_line:
                return first_line

    # Priority 2: Headline field (set by discovery scanner)
    headline_field = brief.get(IdeaFields.HEADLINE, "")
    if headline_field and len(headline_field) > 10:
        return headline_field

    # Priority 3: headline from research brief
    headline = brief.get("headline", "")
    if headline and len(headline) > 10:
        return headline

    return "Untitled"


def build_sources_list(brief: dict) -> str:
    """Build a formatted source list for YouTube show notes / video description.

    Combines source_urls and source_bibliography into a clean list.
    """
    sources = set()

    # Collect from all source fields
    for field in ["source_urls", "source_bibliography"]:
        text = brief.get(field, "")
        if not text:
            continue
        # Extract URLs
        urls = re.findall(r'https?://[^\s\)>\]"\']+', text)
        sources.update(urls)
        # Also add non-URL source lines (e.g., "Reuters, January 2026")
        for line in text.strip().split("\n"):
            line = line.strip().lstrip("- •*")
            if line and not line.startswith("http"):
                sources.add(line)

    if not sources:
        return ""

    # Format as a clean list
    lines = sorted(sources)
    return "\n".join(f"- {line}" for line in lines)


def build_pipeline_record(
    brief: dict,
    script: str,
    scene_list: list[dict],
    accent_color: str,
    idea_record_id: str,
    scene_filepath: str,
    video_id: str,
) -> dict:
    """Build the pipeline table record from translated data.

    Maps Ideas Bank fields to Pipeline Table fields per the field mapping spec.
    """
    # Title selection priority:
    # 1. title_options from research_payload / discovery scanner
    # 2. Headline field from Airtable record
    # 3. headline from research brief
    # 4. Fallback to "Untitled"
    video_title = select_video_title(brief)

    # Extract first source URL
    source_urls = brief.get("source_urls", brief.get("source_bibliography", ""))
    reference_url = ""
    if source_urls:
        # Try to extract the first URL from the text
        lines = source_urls.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("http"):
                reference_url = line
                break
            # Check for URL in parentheses or brackets
            import re
            url_match = re.search(r'https?://[^\s\)>\]]+', line)
            if url_match:
                reference_url = url_match.group(0)
                break

    # Extract first thumbnail concept
    thumbnail_concepts = brief.get("thumbnail_concepts", "")
    thumbnail_prompt = thumbnail_concepts.split("\n")[0] if thumbnail_concepts else ""

    scene_count = len(scene_list)

    # Build full source list for YouTube show notes / video description
    sources_text = build_sources_list(brief)

    return {
        # Core mapped fields
        IdeaFields.VIDEO_TITLE: video_title,
        IdeaFields.HOOK_SCRIPT: brief.get("executive_hook", ""),
        IdeaFields.PAST_CONTEXT: brief.get("historical_parallels", ""),
        IdeaFields.PRESENT_PARALLEL: brief.get("framework_analysis", ""),
        IdeaFields.FUTURE_PREDICTION: brief.get("narrative_arc", ""),
        IdeaFields.WRITER_GUIDANCE: build_writer_guidance(brief, accent_color, scene_count),
        IdeaFields.ORIGINAL_DNA: build_original_dna(brief, idea_record_id, accent_color, scene_count),
        IdeaFields.REFERENCE_URL: reference_url,
        IdeaFields.THUMBNAIL_PROMPT: thumbnail_prompt,
        "Status": "Queued",
        # New fields for the translation layer
        "Script": script,
        IdeaFields.SCENE_FILE_PATH: scene_filepath,
        IdeaFields.ACCENT_COLOR: accent_color,
        "Video ID": video_id,
        "Scene Count": scene_count,
        "Validation Status": "validated",
        # Source list for YouTube description / show notes
        "Sources": sources_text,
        # Framework fields for downstream stages (thumbnail selection, performance analysis)
        IdeaFields.FRAMEWORK_ANGLE: brief.get("_selected_framework", "") or brief.get("framework_angle", ""),
        IdeaFields.THEMATIC_FRAMEWORK: brief.get("themes", ""),
    }


def save_scene_list(
    video_id: str,
    scenes: list[dict],
    output_dir: Optional[str] = None,
) -> str:
    """Save scene list as JSON file for the image prompt engine.

    Args:
        video_id: Unique video identifier
        scenes: List of scene dicts
        output_dir: Directory to save to (defaults to VPS pipeline dir)

    Returns:
        Filepath of the saved JSON file
    """
    scene_dir = Path(output_dir or DEFAULT_SCENE_DIR)
    scene_dir.mkdir(parents=True, exist_ok=True)

    filepath = scene_dir / f"{video_id}_scenes.json"
    filepath.write_text(json.dumps(scenes, indent=2))

    return str(filepath)


def generate_video_id() -> str:
    """Generate a unique video ID based on timestamp."""
    return f"vid_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


async def graduate_to_pipeline(
    airtable_client,
    idea_record_id: str,
    brief: dict,
    script: str,
    scene_list: list[dict],
    accent_color: str,
    scene_output_dir: Optional[str] = None,
    slack_client=None,
    acts: Optional[dict] = None,
    psych_assignments: Optional[list[dict]] = None,
    unverified_claims: str = "",
    editorial_validation: str = "",
) -> dict:
    """Full graduation: Ideas Bank -> Pipeline Table + Scene File + Script Records.

    Args:
        airtable_client: AirtableClient instance
        idea_record_id: Airtable record ID of the source idea
        brief: Research brief dict
        script: Full narration script
        scene_list: Validated scene list
        accent_color: Chosen accent color
        scene_output_dir: Where to save scene JSON (optional)
        slack_client: SlackClient instance for notifications (optional)
        acts: Dict mapping act number to act text (for Script table records)
        psych_assignments: List of {"scene": N, "angle": str} (from psych_angle_assigner)
        unverified_claims: Flagged claims from claim verification (written to scene 1)
        editorial_validation: Editorial voice validation summary (written to scene 1)

    Returns:
        {
            "pipeline_record_id": str,
            "scene_filepath": str,
            "video_id": str,
        }
    """
    video_id = generate_video_id()

    # 1. Save scene list to disk
    scene_filepath = save_scene_list(video_id, scene_list, scene_output_dir)

    # 2. Build pipeline record
    pipeline_record = build_pipeline_record(
        brief=brief,
        script=script,
        scene_list=scene_list,
        accent_color=accent_color,
        idea_record_id=idea_record_id,
        scene_filepath=scene_filepath,
        video_id=video_id,
    )

    # 3. Create pipeline table record
    try:
        result = airtable_client.create_idea(pipeline_record)
        pipeline_record_id = result["id"]
    except Exception as e:
        # If some fields don't exist yet, try with core fields only
        core_fields = {
            IdeaFields.VIDEO_TITLE: pipeline_record[IdeaFields.VIDEO_TITLE],
            IdeaFields.HOOK_SCRIPT: pipeline_record[IdeaFields.HOOK_SCRIPT],
            IdeaFields.PAST_CONTEXT: pipeline_record[IdeaFields.PAST_CONTEXT],
            IdeaFields.PRESENT_PARALLEL: pipeline_record[IdeaFields.PRESENT_PARALLEL],
            IdeaFields.FUTURE_PREDICTION: pipeline_record[IdeaFields.FUTURE_PREDICTION],
            IdeaFields.WRITER_GUIDANCE: pipeline_record[IdeaFields.WRITER_GUIDANCE],
            IdeaFields.ORIGINAL_DNA: pipeline_record[IdeaFields.ORIGINAL_DNA],
            "Status": "Queued",
        }
        if pipeline_record.get(IdeaFields.REFERENCE_URL):
            core_fields[IdeaFields.REFERENCE_URL] = pipeline_record[IdeaFields.REFERENCE_URL]
        if pipeline_record.get(IdeaFields.THUMBNAIL_PROMPT):
            core_fields[IdeaFields.THUMBNAIL_PROMPT] = pipeline_record[IdeaFields.THUMBNAIL_PROMPT]

        result = airtable_client.create_idea(core_fields)
        pipeline_record_id = result["id"]
        print(f"  ⚠️ Some new fields not yet in Airtable: {e}")
        if slack_client:
            try:
                slack_client.send_message(
                    f"⚠️ Pipeline record created with core fields only "
                    f"(some fields dropped): {e}"
                )
            except Exception:
                pass

    # 4. Script table records are now written progressively by
    #    BriefTranslator._write_script_records() BEFORE scene expansion.
    #    This ensures records exist even if expansion fails or times out.

    # 5. Update Idea Concepts record status
    try:
        airtable_client.update_idea_status(idea_record_id, "sent_to_pipeline")
    except Exception as e:
        # If "sent_to_pipeline" is not a valid status option, try with typecast
        try:
            airtable_client.idea_concepts_table.update(
                idea_record_id,
                {"Status": "sent_to_pipeline"},
                typecast=True,
            )
        except Exception:
            print(f"  ⚠️ Could not update Idea Concepts status: {e}")
            if slack_client:
                try:
                    slack_client.send_message(
                        f"⚠️ Airtable status update FAILED for {idea_record_id}: {e}"
                    )
                except Exception:
                    pass

    # 6. Notify via Slack
    if slack_client:
        try:
            slack_client.send_message(
                f"🎬 New video queued: {brief.get('headline', 'Untitled')}\n"
                f"Accent: {accent_color} | Scenes: {len(scene_list)} | "
                f"Script: {len(script.split())} words\n"
                f"Pipeline record: {pipeline_record_id}"
            )
        except Exception:
            pass  # Don't fail graduation on notification error

    return {
        "pipeline_record_id": pipeline_record_id,
        "scene_filepath": scene_filepath,
        "video_id": video_id,
    }
