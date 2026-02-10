"""Check the active project details."""

import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

ANIMATION_BASE_ID = "appB9RWwCgywdwYrT"
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")

async def get_project_details():
    """Get full details of the 'Create' status project."""
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    }

    # Get project with Create status
    url = f"https://api.airtable.com/v0/{ANIMATION_BASE_ID}/tblYiND5DkrZhIlLq"
    params = {"filterByFormula": "{Status}='Create'"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        projects = response.json().get("records", [])

    if not projects:
        print("No projects with 'Create' status found")
        return

    project = projects[0]
    fields = project.get("fields", {})
    project_id = project.get("id")

    print("=" * 60)
    print(f"📁 PROJECT: {fields.get('Project Name', 'Untitled')}")
    print("=" * 60)

    for key, value in sorted(fields.items()):
        if isinstance(value, str) and len(value) > 100:
            print(f"  {key}: {value[:100]}...")
        else:
            print(f"  {key}: {value}")

    # Get scenes linked to this project
    print("\n" + "=" * 60)
    print("🎬 SCENES FOR THIS PROJECT")
    print("=" * 60)

    # Scenes are linked by Project Name field
    project_name = fields.get("Project Name", "")
    url = f"https://api.airtable.com/v0/{ANIMATION_BASE_ID}/tblipThhapetdSJdm"
    params = {"filterByFormula": f"{{Project Name}}='{project_name}'"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        scenes = response.json().get("records", [])

    print(f"\nFound {len(scenes)} scenes")

    for scene in sorted(scenes, key=lambda s: s.get("fields", {}).get("scene_order", s.get("fields", {}).get("scene", 999))):
        sf = scene.get("fields", {})
        scene_num = sf.get("scene_order") or sf.get("scene", "?")
        print(f"\n  Scene {scene_num}:")
        print(f"    Type: {sf.get('scene_type', 'N/A')}")
        print(f"    Camera: {sf.get('camera_direction', 'N/A')}")
        print(f"    Glow: {sf.get('glow_state', 'N/A')} ({sf.get('glow_behavior', 'N/A')})")
        if sf.get("voiceover_text"):
            print(f"    VO: {sf.get('voiceover_text', '')[:80]}...")
        if sf.get("start_image_prompt"):
            print(f"    Start prompt: {sf.get('start_image_prompt', '')[:80]}...")


asyncio.run(get_project_details())
