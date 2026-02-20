"""Generate prompts and images for existing scenes."""

import os
import asyncio
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env'))

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from animation.airtable_client import AnimationAirtableClient
from animation.image_generator import ImagePromptGenerator
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
    project = await airtable.get_project_by_status("Create")
    if not project:
        print("❌ No project with 'Create' status")
        return

    project_name = project.get("Project Name")
    creative_direction = project.get("Creative Direction", "")

    # Extract Core Image URL from the project record
    core_image_attachments = project.get("Core Image", [])
    core_image_url = ""
    if core_image_attachments and isinstance(core_image_attachments, list):
        core_image_url = core_image_attachments[0].get("url", "")

    print(f"📁 Project: {project_name}")
    if core_image_url:
        print(f"🖼️  Core Image: {core_image_url[:80]}...")
    else:
        print(f"⚠️  No Core Image found on project — image generation will fail")

    # Get scenes
    scenes = await airtable.get_scenes_for_project(project_name)
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
        await airtable.update_scene(
            scene["id"],
            {"start_image_prompt": prompt}
        )
        scene["start_image_prompt"] = prompt
        print(f"    ✅ {len(prompt.split())} words")

    # Reload scenes to get updated prompts
    scenes = await airtable.get_scenes_for_project(project_name)

    # Phase 2: Generate images for scenes where "start prompt done" is checked
    # Only generate images when user has approved the start prompt
    scenes_needing_images = [
        s for s in scenes
        if s.get("start_image_prompt")
        and s.get("start prompt done")  # User approved the prompt
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

        # Generate image using Seed Dream 4.5 Edit with Core Image reference
        if not core_image_url:
            print(f"    ❌ No Core Image — skipping")
            continue
        result = await image_client.generate_scene_image(prompt, core_image_url)

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
            await airtable.update_scene(
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
