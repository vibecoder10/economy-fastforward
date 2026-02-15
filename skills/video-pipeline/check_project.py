"""Check BOTH pipeline statuses — YouTube + Animation."""

import os
import sys
import asyncio
import httpx
from dotenv import load_dotenv
from collections import Counter

load_dotenv()

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")

# YouTube Pipeline (Idea Concepts)
YOUTUBE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
IDEA_CONCEPTS_TABLE_ID = os.getenv("AIRTABLE_IDEA_CONCEPTS_TABLE_ID", "tblrAsJglokZSkC8m")

# Animation Pipeline
ANIMATION_BASE_ID = "appB9RWwCgywdwYrT"
ANIMATION_PROJECT_TABLE_ID = "tblYiND5DkrZhIlLq"
ANIMATION_SCENES_TABLE_ID = "tblipThhapetdSJdm"

# YouTube pipeline status order
YOUTUBE_STATUS_ORDER = [
    "Idea Logged",
    "Approved",
    "Ready For Scripting",
    "Ready For Voice",
    "Ready For Image Prompts",
    "Ready For Images",
    "Ready For Video Scripts",
    "Ready For Video Generation",
    "Ready For Thumbnail",
    "Ready To Render",
    "In Que",
    "Done",
]

# Mapping from YouTube status to next Slack command
YOUTUBE_NEXT_STEP = {
    "Approved": "research",
    "Ready For Scripting": "script",
    "Ready For Voice": "voice",
    "Ready For Image Prompts": "prompts",
    "Ready For Images": "prompts",
    "Ready For Thumbnail": "thumbnail",
    "Ready To Render": "(manual render)",
    "Done": None,
}


async def get_youtube_status(client: httpx.AsyncClient, headers: dict) -> dict:
    """Fetch YouTube pipeline status from Idea Concepts table."""
    url = f"https://api.airtable.com/v0/{YOUTUBE_BASE_ID}/{IDEA_CONCEPTS_TABLE_ID}"
    params = {"fields[]": ["Video Title", "Status", "Source"]}

    all_records = []
    offset = None

    while True:
        if offset:
            params["offset"] = offset
        response = await client.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        all_records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break

    return all_records


async def get_animation_status(client: httpx.AsyncClient, headers: dict) -> dict:
    """Fetch Animation pipeline status — project + scene counts."""
    # Get projects
    proj_url = f"https://api.airtable.com/v0/{ANIMATION_BASE_ID}/{ANIMATION_PROJECT_TABLE_ID}"
    proj_params = {"fields[]": ["Project Name", "Status"]}

    response = await client.get(proj_url, headers=headers, params=proj_params, timeout=30.0)
    response.raise_for_status()
    projects = response.json().get("records", [])

    # Find active project (status = "Create")
    active_project = None
    for p in projects:
        fields = p.get("fields", {})
        if fields.get("Status") == "Create":
            active_project = {"id": p["id"], **fields}
            break

    scene_total = 0
    scene_complete = 0

    if active_project:
        project_name = active_project.get("Project Name", "")
        scenes_url = f"https://api.airtable.com/v0/{ANIMATION_BASE_ID}/{ANIMATION_SCENES_TABLE_ID}"
        scenes_params = {
            "filterByFormula": f"{{Project Name}}='{project_name}'",
            "fields[]": ["scene_order", "image done"],
        }

        response = await client.get(scenes_url, headers=headers, params=scenes_params, timeout=30.0)
        response.raise_for_status()
        scenes = response.json().get("records", [])
        scene_total = len(scenes)
        scene_complete = sum(1 for s in scenes if s.get("fields", {}).get("image done"))

    return {
        "projects": projects,
        "active_project": active_project,
        "scene_total": scene_total,
        "scene_complete": scene_complete,
    }


async def get_pipeline_status():
    """Show the current state of BOTH pipelines."""
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}

    async with httpx.AsyncClient() as client:
        youtube_records, animation_data = await asyncio.gather(
            get_youtube_status(client, headers),
            get_animation_status(client, headers),
        )

    # ── YouTube Pipeline ──────────────────────────────────────
    print("🎬 YOUTUBE PIPELINE")
    print("=" * 50)

    if not youtube_records:
        print("  No ideas found in Idea Concepts table")
    else:
        # Find the current active idea (most recent non-Done, non-Idea Logged)
        active_statuses = [s for s in YOUTUBE_STATUS_ORDER if s not in ("Done", "Idea Logged")]
        current_idea = None
        current_status = None

        for status in active_statuses:
            for r in youtube_records:
                fields = r.get("fields", {})
                if fields.get("Status") == status:
                    current_idea = fields.get("Video Title", "Untitled")
                    current_status = status
                    break
            if current_idea:
                break

        if current_idea:
            next_step = YOUTUBE_NEXT_STEP.get(current_status, "run")
            print(f"  Current: \"{current_idea}\"")
            print(f"  Status:  {current_status}")
            if next_step:
                print(f"  Next step: {next_step}")
        else:
            print("  No active ideas in the pipeline.")

        # Summary counts
        status_counts = Counter()
        for r in youtube_records:
            status = r.get("fields", {}).get("Status", "(no status)")
            status_counts[status] += 1

        print(f"\n  Total ideas: {len(youtube_records)}")
        shown = set()
        for status in YOUTUBE_STATUS_ORDER:
            count = status_counts.get(status, 0)
            if count > 0:
                print(f"    {status}: {count}")
                shown.add(status)
        for status, count in sorted(status_counts.items()):
            if status not in shown:
                print(f"    {status}: {count}")

    # ── Animation Pipeline ────────────────────────────────────
    print(f"\n🎞️ ANIMATION PIPELINE")
    print("=" * 50)

    active = animation_data.get("active_project")
    if active:
        print(f"  Current: \"{active.get('Project Name', 'Untitled')}\"")
        print(f"  Status:  {active.get('Status', '?')}")
        print(f"  Scenes:  {animation_data['scene_complete']}/{animation_data['scene_total']} complete")
    else:
        all_projects = animation_data.get("projects", [])
        if all_projects:
            print("  No active project (no 'Create' status).")
            print(f"  Total projects: {len(all_projects)}")
        else:
            print("  No projects found in Animation Pipeline table.")

    print()


asyncio.run(get_pipeline_status())
