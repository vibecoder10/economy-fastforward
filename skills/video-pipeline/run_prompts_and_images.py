"""Generate prompts and images for existing scenes.

Uses the canonical /animation/ module for Airtable client and prompt generation,
and the local clients/ module for image generation and Google Drive upload.
"""

import os
import asyncio
from dotenv import load_dotenv

# Add repo root to path for animation module
REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')

load_dotenv(os.path.join(REPO_ROOT, '.env'))

import sys
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from animation.airtable import AnimationAirtableClient
from animation.prompt_generator import ImagePromptGenerator
from clients.image_client import ImageClient
from clients.google_client import GoogleClient


async def main():
    print("🎨 Generating prompts and images for existing scenes...")

    # Initialize clients
    airtable = AnimationAirtableClient()
    prompt_gen = ImagePromptGenerator()
    image_client = ImageClient()
    google_client = GoogleClient()

    # Get project
    projects = airtable.get_projects_by_status("Create", limit=1)
    if not projects:
        print("❌ No project with 'Create' status")
        return

    project = projects[0]
    project_name = project.get("Project Name")
    creative_direction = project.get("Creative Direction", "")
    print(f"📁 Project: {project_name}")

    # Get scenes
    scenes = airtable.get_scenes_for_project(project_name)
    print(f"📋 Found {len(scenes)} scenes")

    # Get or create folder
    folder = google_client.get_or_create_folder(project_name)
    folder_id = folder["id"]
    print(f"📂 Folder ID: {folder_id}")

    # Phase 1: Generate prompts for scenes without them
    scenes_needing_prompts = [s for s in scenes if not s.get("start_image_prompt")]
    print(f"\n📝 Scenes needing prompts: {len(scenes_needing_prompts)}")

    for scene in scenes_needing_prompts:
        scene_num = scene.get("scene_order", "?")
        print(f"  Scene {scene_num}: Generating prompt...")

        prompt = await prompt_gen.generate_image_prompt(scene, creative_direction)

        # Save to Airtable
        airtable.update_scene(scene["id"], {"start_image_prompt": prompt})
        scene["start_image_prompt"] = prompt
        print(f"    ✅ {len(prompt.split())} words")

    # Reload scenes to get updated prompts
    scenes = airtable.get_scenes_for_project(project_name)

    # Phase 2: Generate images for scenes where "start prompt done" is checked
    scenes_needing_images = [
        s for s in scenes
        if s.get("start_image_prompt")
        and s.get("start prompt done")
        and not s.get("start_image")
    ]
    print(f"\n🖼️  Scenes with approved prompts needing images: {len(scenes_needing_images)}")

    cost = 0.0
    images_generated = 0

    for i, scene in enumerate(scenes_needing_images, 1):
        scene_num = scene.get("scene_order", "?")
        prompt = scene.get("start_image_prompt")

        print(f"\n  [{i}/{len(scenes_needing_images)}] Scene {scene_num}")
        print(f"    Type: {scene.get('scene_type')}")
        print(f"    Glow: {scene.get('glow_state')} ({scene.get('glow_behavior')})")

        # Generate image
        result = await image_client.generate_scene_image(prompt)

        if result and result.get("url"):
            image_url = result["url"]

            # Download
            print("    Downloading...")
            image_content = await image_client.download_image(image_url)

            # Upload to Drive
            filename = f"Scene_{str(scene_num).zfill(2)}.png"
            print(f"    Uploading {filename}...")
            drive_file = google_client.upload_image(image_content, filename, folder_id)
            drive_url = google_client.make_file_public(drive_file["id"])

            # Update Airtable
            airtable.update_scene(
                scene["id"],
                {
                    "start_image": [{"url": drive_url}],
                    "image done": True,
                }
            )

            images_generated += 1
            cost += 0.025
            print(f"    ✅ Done! (${cost:.2f} total)")

        else:
            print(f"    ❌ Image generation failed")

    print(f"\n✅ Generated {images_generated} images")
    print(f"   Total cost: ${cost:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
