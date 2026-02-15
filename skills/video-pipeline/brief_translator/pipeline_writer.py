"""Pipeline Table Write (Step 4).

Maps translated fields from the research brief to the existing pipeline table
schema and writes the scene list to a JSON file for the image prompt engine.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


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
    # Extract first title option
    title_options = brief.get("title_options", "")
    video_title = title_options.split("\n")[0] if title_options else brief.get("headline", "Untitled")

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

    return {
        # Core mapped fields
        "Video Title": video_title,
        "Hook Script": brief.get("executive_hook", ""),
        "Past Context": brief.get("historical_parallels", ""),
        "Present Parallel": brief.get("framework_analysis", ""),
        "Future Prediction": brief.get("narrative_arc", ""),
        "Writer Guidance": build_writer_guidance(brief, accent_color, scene_count),
        "Original DNA": build_original_dna(brief, idea_record_id, accent_color, scene_count),
        "Reference URL": reference_url,
        "Thumbnail Prompt": thumbnail_prompt,
        "Status": "Queued",
        # New fields for the translation layer
        "Script": script,
        "Scene File Path": scene_filepath,
        "Accent Color": accent_color,
        "Video ID": video_id,
        "Scene Count": scene_count,
        "Validation Status": "validated",
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
) -> dict:
    """Full graduation: Ideas Bank -> Pipeline Table + Scene File.

    Args:
        airtable_client: AirtableClient instance
        idea_record_id: Airtable record ID of the source idea
        brief: Research brief dict
        script: Full narration script
        scene_list: Validated scene list
        accent_color: Chosen accent color
        scene_output_dir: Where to save scene JSON (optional)
        slack_client: SlackClient instance for notifications (optional)

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
            "Video Title": pipeline_record["Video Title"],
            "Hook Script": pipeline_record["Hook Script"],
            "Past Context": pipeline_record["Past Context"],
            "Present Parallel": pipeline_record["Present Parallel"],
            "Future Prediction": pipeline_record["Future Prediction"],
            "Writer Guidance": pipeline_record["Writer Guidance"],
            "Original DNA": pipeline_record["Original DNA"],
            "Status": "Queued",
        }
        if pipeline_record.get("Reference URL"):
            core_fields["Reference URL"] = pipeline_record["Reference URL"]
        if pipeline_record.get("Thumbnail Prompt"):
            core_fields["Thumbnail Prompt"] = pipeline_record["Thumbnail Prompt"]

        result = airtable_client.create_idea(core_fields)
        pipeline_record_id = result["id"]
        print(f"  ⚠️ Some new fields not yet in Airtable: {e}")

    # 4. Update Idea Concepts record status
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

    # 5. Notify via Slack
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
