"""Image regeneration step — regenerates specific missing images.

Use when render fails due to missing images. Can target:
1. All images in specific scenes (scene_list)
2. Specific scene/index pairs (image_indices)
3. All images with empty "Image" field (if no args)

Reads: Image Prompt from Images table
Writes: Image attachment + Drive Image URL to Images table
Clients: image_client, google, airtable
"""

import asyncio

from pipeline_constants import Statuses, ImageFields


async def run(
    pipeline,
    scene_list: list[int] = None,
    image_indices: list[tuple[int, int]] = None,
) -> dict:
    """Regenerate specific missing images for the current video."""
    if not pipeline.current_idea:
        # Try to find a video with images to regenerate
        idea = pipeline.get_idea_by_status(Statuses.READY_TO_RENDER)
        if not idea:
            idea = pipeline.get_idea_by_status(Statuses.READY_THUMBNAIL)
        if not idea:
            idea = pipeline.get_idea_by_status(Statuses.READY_IMAGES)
        if not idea:
            return {"error": "No video found to regenerate images for"}
        pipeline._load_idea(idea)

    print(f"\n🔄 REGENERATE IMAGES: Processing '{pipeline.video_title}'")

    # Get or create project folder
    if not pipeline.project_folder_id:
        folder = pipeline.google.get_or_create_folder(pipeline.video_title)
        pipeline.project_folder_id = folder["id"]

    # Get all images for this video
    all_images = pipeline.airtable.get_all_images_for_video(pipeline.video_title)

    # Filter to images needing regeneration
    images_to_regen = []

    if image_indices:
        # Specific scene/index pairs
        for scene_num, img_index in image_indices:
            for img in all_images:
                if img.get(ImageFields.SCENE) == scene_num and img.get(ImageFields.IMAGE_INDEX) == img_index:
                    images_to_regen.append(img)
                    break
    elif scene_list:
        # All images in specified scenes
        for img in all_images:
            if img.get(ImageFields.SCENE) in scene_list:
                images_to_regen.append(img)
    else:
        # All images with no "Image" attachment (missing)
        for img in all_images:
            img_attachments = img.get(ImageFields.IMAGE, [])
            if not img_attachments:
                images_to_regen.append(img)

    if not images_to_regen:
        print("  ✅ No images need regeneration")
        return {"status": "ok", "regenerated": 0}

    print(f"  Found {len(images_to_regen)} images to regenerate")

    # Group by scene for parallel processing
    scenes = {}
    for img in images_to_regen:
        scene_num = img.get(ImageFields.SCENE, 0)
        if scene_num not in scenes:
            scenes[scene_num] = []
        scenes[scene_num].append(img)

    regenerated = 0

    for scene_num in sorted(scenes.keys()):
        scene_images = scenes[scene_num]
        print(f"  Scene {scene_num}: Regenerating {len(scene_images)} images...")

        async def generate_single(img_record):
            prompt = img_record.get(ImageFields.IMAGE_PROMPT, "")
            index = img_record.get(ImageFields.IMAGE_INDEX, 0)

            if not prompt:
                return (img_record, None, index, "No prompt")

            try:
                # Use Core Image reference if available, otherwise text-to-image
                if pipeline.core_image_url:
                    result = await pipeline.image_client.generate_scene_image(prompt, pipeline.core_image_url)
                else:
                    result_urls = await pipeline.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                    result = {"url": result_urls[0]} if result_urls else None
                return (img_record, result, index, None)
            except Exception as e:
                return (img_record, None, index, str(e))

        # Generate in parallel
        results = await asyncio.gather(*[generate_single(img) for img in scene_images])

        # Upload to Drive and update Airtable
        for img_record, result, index, error in results:
            if error:
                print(f"    ❌ Scene {scene_num}, Image {index}: {error}")
                continue

            if result and result.get("url"):
                image_url = result["url"]

                # Download image
                image_content = await pipeline.image_client.download_image(image_url)

                # Upload to Google Drive (non-blocking)
                filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                drive_url = None
                try:
                    drive_file = pipeline.google.upload_image(image_content, filename, pipeline.project_folder_id)
                    drive_url = pipeline.google.make_file_public(drive_file["id"])
                except Exception as drive_err:
                    print(f"    ⚠️ Scene {scene_num}, Image {index} → Drive upload failed: {drive_err}")

                # Update Airtable (with Drive URL if available)
                pipeline.airtable.update_image_record(img_record["id"], image_url, drive_url=drive_url)
                regenerated += 1
                drive_status = "" if drive_url else " (⚠️ no Drive)"
                print(f"    ✅ Scene {scene_num}, Image {index} → regenerated{drive_status}")

    print(f"\n  ✅ Regenerated {regenerated} images")
    return {"status": "ok", "regenerated": regenerated, "total_requested": len(images_to_regen)}
