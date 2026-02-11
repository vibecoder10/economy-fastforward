"""Generate end image prompts and end images for all scenes.

Uses Seed Dream v4 Edit with start_image as reference for character consistency.
"""

import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from animation.airtable_client import AnimationAirtableClient
from animation.image_generator import ImagePromptGenerator
from clients.image_client import ImageClient
from clients.google_client import GoogleClient


async def main(force_regenerate: bool = False):
    print("🎬 Generating END image prompts and images...")
    if force_regenerate:
        print("⚠️  FORCE REGENERATE: Clearing existing end prompts and images")

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
    print(f"📁 Project: {project_name}")

    # Get scenes
    scenes = await airtable.get_scenes_for_project(project_name)
    print(f"📋 Found {len(scenes)} scenes")

    # If force regenerate, clear existing end prompts and images
    if force_regenerate:
        print("\n🗑️  Clearing existing end data...")
        for scene in scenes:
            if scene.get("end_image_prompt") or scene.get("end_image"):
                await airtable.update_scene(
                    scene["id"],
                    {"end_image_prompt": "", "end_image": None}
                )
                scene["end_image_prompt"] = None
                scene["end_image"] = None
        print("   Done clearing")

    # Get folder
    folder = google_client.get_or_create_folder(project_name)
    folder_id = folder["id"]

    # Phase 1: Generate END prompts for scenes where "start prompt done" is checked
    # Only generate end prompts when user has approved the start prompt
    scenes_needing_end_prompts = [
        s for s in scenes
        if s.get("start_image_prompt")
        and s.get("start prompt done")  # User approved start prompt
        and not s.get("end_image_prompt")
    ]
    print(f"\n📝 Scenes with approved start prompts needing END prompts: {len(scenes_needing_end_prompts)}")

    for scene in scenes_needing_end_prompts:
        scene_num = scene.get("scene_order", "?")
        start_prompt = scene.get("start_image_prompt")

        print(f"  Scene {scene_num}: Generating END prompt...")

        end_prompt = await prompt_gen.generate_end_image_prompt(scene, start_prompt)

        # Save to Airtable
        await airtable.update_scene(
            scene["id"],
            {"end_image_prompt": end_prompt}
        )
        scene["end_image_prompt"] = end_prompt
        print(f"    ✅ {len(end_prompt.split())} words")

    # Reload scenes to get updated prompts
    scenes = await airtable.get_scenes_for_project(project_name)

    # Phase 2: Generate END images for scenes where "end prompt done" is checked
    # Only generate images when user has approved the end prompt
    scenes_needing_end_images = [
        s for s in scenes
        if s.get("end_image_prompt")
        and s.get("end prompt done")  # User approved end prompt
        and s.get("start_image")
        and not s.get("end_image")
    ]
    print(f"\n🖼️  Scenes with approved end prompts needing END images: {len(scenes_needing_end_images)}")

    cost = 0.0
    images_generated = 0

    for i, scene in enumerate(scenes_needing_end_images, 1):
        scene_num = scene.get("scene_order", "?")
        end_prompt = scene.get("end_image_prompt")

        # Get start image URL for reference
        start_images = scene.get("start_image", [])
        if not start_images:
            print(f"  Scene {scene_num}: No start_image, skipping")
            continue

        # Get the URL from the attachment
        if isinstance(start_images, list) and len(start_images) > 0:
            start_image_url = start_images[0].get("url")
        else:
            start_image_url = None

        if not start_image_url:
            print(f"  Scene {scene_num}: Invalid start_image URL, skipping")
            continue

        print(f"\n  [{i}/{len(scenes_needing_end_images)}] Scene {scene_num}")
        print(f"    Type: {scene.get('scene_type')}")
        print(f"    Camera: {scene.get('camera_direction')}")
        print(f"    Reference: {start_image_url[:60]}...")

        # Generate end image with Seed Dream Edit (uses start image as reference)
        result = await image_client.generate_scene_image_with_reference(
            prompt=end_prompt,
            reference_image_url=start_image_url,
        )

        if result and result.get("url"):
            image_url = result["url"]

            # Download
            print("    Downloading...")
            image_content = await image_client.download_image(image_url)

            # Upload to Drive
            filename = f"Scene_{str(scene_num).zfill(2)}_end.png"
            print(f"    Uploading {filename}...")
            drive_file = google_client.upload_image(image_content, filename, folder_id)
            drive_url = google_client.make_file_public(drive_file["id"])

            # Update Airtable
            await airtable.update_scene(
                scene["id"],
                {"end_image": [{"url": drive_url}]}
            )

            images_generated += 1
            cost += 0.02  # Seed Dream Edit cost
            print(f"    ✅ Done! (${cost:.2f} total)")

        else:
            print(f"    ❌ End image generation failed")

    print(f"\n✅ Generated {images_generated} END images")
    print(f"   Total cost: ${cost:.2f}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--regenerate", action="store_true", help="Force regenerate all end prompts and images")
    args = parser.parse_args()
    asyncio.run(main(force_regenerate=args.regenerate))
