"""Image generation step — creates scene images from prompts.

Reads: Image Prompt field from Images table (status=Pending)
Writes: Image attachment + Drive Image URL to Images table, PNG to Drive
Advances: Ready For Images → Ready For Sound Design
Clients: image_client, google, airtable, slack
"""

import asyncio
import gc
from collections import defaultdict

from orchestrator.pipeline_constants import Statuses, Models, IdeaFields, ImageFields, ScriptFields


async def run(pipeline) -> dict:
    """Generate images from prompts (outer wrapper with status management)."""
    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_IMAGES)
        if not idea:
            return {"error": "No idea with status 'Ready For Images'", "bot": "Image Bot"}
        pipeline._load_idea(idea)

    if pipeline.current_idea.get(IdeaFields.STATUS) != Statuses.READY_IMAGES:
        return {"error": f"Idea status is '{pipeline.current_idea.get(IdeaFields.STATUS)}', expected 'Ready For Images'", "bot": "Image Bot", "video_title": pipeline.video_title}

    print(f"\n🖼️ IMAGE BOT: Processing '{pipeline.video_title}'")
    pipeline._log_filters()

    # Get or create project folder
    if not pipeline.project_folder_id:
        folder = pipeline.google.get_or_create_folder(pipeline.video_title)
        pipeline.project_folder_id = folder["id"]

    # Run the internal image bot
    result = await _generate_images(pipeline)

    # User pressed Stop — keep completed work, don't verify or advance status
    if result.get("cancelled"):
        print(f"  🛑 Stopped by user — kept {result.get('image_count', 0)} completed image(s)")
        return {
            "bot": "Image Bot",
            "video_title": pipeline.video_title,
            "image_count": result.get("image_count", 0),
            "cancelled": True,
        }

    # Targeted run — don't verify or advance status
    if pipeline._is_targeted_run:
        print(f"  🎯 Targeted run — status NOT advanced")
        return {
            "bot": "Image Bot",
            "video_title": pipeline.video_title,
            "image_count": result.get("image_count", 0),
            "targeted": True,
        }

    # VERIFY all images are actually complete before advancing status
    all_images = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
    pending = [img for img in all_images if img.get(ImageFields.STATUS) != ImageFields.STATUS_DONE and img.get(ImageFields.IMAGE_PROMPT)]
    total = len([img for img in all_images if img.get(ImageFields.IMAGE_PROMPT)])

    if not all_images or total == 0:
        error_msg = f"No images found for '{pipeline.video_title}' — cannot advance status"
        print(f"  ❌ {error_msg}")
        pipeline.slack.notify(f"❌ Image Bot STOPPED: {error_msg}")
        return {
            "status": "failed",
            "bot": "Image Bot",
            "video_title": pipeline.video_title,
            "error": error_msg,
        }

    if len(pending) > 0:
        error_msg = f"{len(pending)}/{total} images still pending after all retries for '{pipeline.video_title}'"
        print(f"  ❌ {error_msg}")
        pipeline.slack.notify(
            f"❌ Image Bot STOPPED: {error_msg}\n"
            f"Status NOT advanced. Fix issues and run again."
        )
        return {
            "status": "failed",
            "bot": "Image Bot",
            "video_title": pipeline.video_title,
            "error": error_msg,
            "images_pending": len(pending),
            "images_total": total,
        }

    # ALL images verified complete — advance to sound design
    pipeline._update_status(Statuses.READY_SOUND_DESIGN)
    print(f"  ✅ All {total} images verified complete. Status updated to: {Statuses.READY_SOUND_DESIGN}")

    return {
        "bot": "Image Bot",
        "video_title": pipeline.video_title,
        "image_count": result.get("image_count", 0),
        "new_status": Statuses.READY_SOUND_DESIGN,
    }


async def _generate_images(pipeline) -> dict:
    """Generate images from prompts (internal implementation).

    Uses semaphore-based rate limiting to prevent OOM.
    Checkpoints progress after each image for crash recovery.
    """
    MAX_CONCURRENT = 3
    DELAY_BETWEEN_SCENES = 2.0

    _should_cancel = getattr(pipeline, "should_cancel", None)

    async def _cancelled() -> bool:
        """Cooperative Stop check — called between paid generations."""
        try:
            return bool(_should_cancel) and await _should_cancel()
        except Exception:
            return False

    pipeline.slack.notify_images_start()
    print(f"\n  🖼️ IMAGE BOT: Generating images...")
    print(f"     Rate limit: {MAX_CONCURRENT} concurrent generations")

    # Scene images live in the video folder's images/ subfolder
    # (Drive layout: Storyengine/<video title>/images/).
    try:
        images_folder = pipeline.google.get_or_create_folder(
            "images", parent_id=pipeline.project_folder_id
        )
        images_folder_id = images_folder["id"] if isinstance(images_folder, dict) else pipeline.project_folder_id
    except Exception:
        images_folder_id = pipeline.project_folder_id

    # RESUME LOGIC: Get only pending images
    all_images = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
    done_count = len([img for img in all_images if img.get(ImageFields.STATUS) == ImageFields.STATUS_DONE])
    pending_images = [img for img in all_images if img.get(ImageFields.STATUS) == ImageFields.STATUS_PENDING and img.get(ImageFields.IMAGE_PROMPT)]

    # Apply scene/image filters
    pending_images = pipeline._filter_by_scene(pending_images)
    total_pending = len(pending_images)

    if done_count > 0:
        print(f"     ♻️ RESUME: {done_count} images already done, {total_pending} remaining")
        pipeline.slack.notify(f"♻️ Resuming: {done_count} images already done, {total_pending} remaining for *{pipeline.video_title}*")
    else:
        print(f"     Found {total_pending} pending images")

    if total_pending == 0:
        print("     ⚠️ No pending images found — nothing to generate.")
        pipeline.slack.notify(f"⚠️ Image Bot: 0 pending images found for *{pipeline.video_title}*. Nothing to generate.")
        return {"image_count": 0, "failed_count": 0}

    # Check for image model override (hot-swap via Slack !model command)
    from shared.clients.image_client import ImageClient
    from shared.clients.airtable_client import get_image_model_override
    model_override = get_image_model_override(pipeline.current_idea)
    if model_override and model_override not in ImageClient.VALID_SCENE_MODELS:
        print(f"     ⚠️ Invalid model override '{model_override}', falling back to default")
        model_override = ""
    if model_override:
        print(f"     🔄 Model override active: {model_override} ({ImageClient.VALID_SCENE_MODELS[model_override]})")

    use_reference = bool(pipeline.core_image_url) and model_override != Models.IMAGE_ZIMAGE
    if model_override == Models.IMAGE_ZIMAGE:
        print(f"     🎨 Using Z Image model (text-to-image, no reference)")
    elif use_reference:
        print(f"     🖼️ Using Core Image reference (Seed Dream 4.5 Edit)")
    else:
        print(f"     📸 Using text-to-image generation (no Core Image reference)")

    pipeline.slack.notify(f"🖼️ Starting image generation: {total_pending} images for *{pipeline.video_title}*")

    # Group images by scene
    scenes = {}
    for img in pending_images:
        scene_num = img.get(ImageFields.SCENE, 0)
        if scene_num not in scenes:
            scenes[scene_num] = []
        scenes[scene_num].append(img)

    image_count = 0
    failed_count = 0
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    for scene_idx, scene_num in enumerate(sorted(scenes.keys())):
        if await _cancelled():
            print(f"    🛑 Stop requested — halting before scene {scene_num}")
            pipeline.slack.notify(f"🛑 Image generation stopped by user ({image_count}/{total_pending} done)")
            return {"image_count": image_count, "failed_count": failed_count, "cancelled": True}
        scene_images = scenes[scene_num]
        scene_total = len(scene_images)
        print(f"\n    Scene {scene_num} ({scene_idx + 1}/{len(scenes)}): {scene_total} images")

        async def generate_and_save(img_record):
            nonlocal image_count, failed_count

            async with semaphore:
                if await _cancelled():
                    return None  # Stop requested — skip queued images, keep in-flight ones
                prompt = img_record.get(ImageFields.IMAGE_PROMPT, "")
                index = img_record.get(ImageFields.IMAGE_INDEX, 0)
                record_id = img_record["id"]
                prompt_preview = prompt[:120] + "..." if len(prompt) > 120 else prompt

                try:
                    if model_override == Models.IMAGE_ZIMAGE:
                        result = await pipeline.image_client.generate_scene_image_zimage(prompt, aspect_ratio="16:9")
                    elif use_reference:
                        result = await pipeline.image_client.generate_scene_image(prompt, pipeline.core_image_url)
                    else:
                        result_urls = await pipeline.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                        result = {"url": result_urls[0]} if result_urls and len(result_urls) > 0 else None

                    if result and result.get("url"):
                        image_url = result["url"]
                        image_content = await pipeline.image_client.download_image(image_url)

                        drive_download_url = None
                        filename = f"Scene_{str(scene_num).zfill(2)}_{str(index).zfill(2)}.png"
                        try:
                            drive_file = pipeline.google.upload_image(image_content, filename, images_folder_id)
                            drive_download_url = pipeline.google.make_file_public(drive_file["id"])
                        except Exception as drive_err:
                            print(f"      ⚠️ Scene {scene_num}, Image {index} → Drive upload failed: {drive_err}")

                        pipeline.airtable.update_image_record(record_id, image_url, drive_url=drive_download_url)
                        image_count += 1
                        drive_status = "" if drive_download_url else " (⚠️ no Drive)"
                        print(f"      ✅ Scene {scene_num}, Image {index} → Done{drive_status} ({image_count}/{total_pending})")
                        pipeline.slack.notify(f"🖼️ Generating images... {image_count}/{total_pending} complete")
                        del image_content
                        return True
                    else:
                        failed_count += 1
                        print(f"      ❌ Scene {scene_num}, Image {index} → Generation failed")
                        return False

                except Exception as e:
                    # A blocked / out-of-credit Kie account is terminal — abort
                    # the whole run instead of burning every remaining image (and
                    # then 3 retry rounds) against a key that can never succeed.
                    # gather() propagates this and cancels the sibling tasks; the
                    # stage fails with an actionable "fix your Kie key" message.
                    if "KIE_ACCOUNT_BLOCKED" in str(e):
                        raise
                    failed_count += 1
                    print(f"      ❌ Scene {scene_num}, Image {index} → Error: {e}")
                    import traceback
                    traceback.print_exc()
                    return False

        await asyncio.gather(*[generate_and_save(img) for img in scene_images])
        gc.collect()
        print(f"    ✅ Scene {scene_num} complete | Total progress: {image_count}/{total_pending}")

        if scene_idx < len(scenes) - 1:
            await asyncio.sleep(DELAY_BETWEEN_SCENES)

    pipeline.slack.notify_images_done()
    print(f"\n    🎉 IMAGE BOT COMPLETE: {image_count}/{total_pending}")
    if failed_count > 0:
        print(f"       Failed: {failed_count}")

    status_msg = f"✅ Images done: {image_count}/{total_pending} for *{pipeline.video_title}*"
    if failed_count > 0:
        status_msg += f" ({failed_count} failed)"
    pipeline.slack.notify(status_msg)

    # === RETRY PHASE ===
    # Skip retries on targeted runs — only the targeted image should be generated
    if pipeline._is_targeted_run:
        return {"image_count": image_count, "failed_count": failed_count}

    max_retries = 3
    for retry_round in range(max_retries):
        if await _cancelled():
            print("    🛑 Stop requested — skipping retry rounds")
            return {"image_count": image_count, "failed_count": failed_count, "cancelled": True}
        all_images = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
        pending = [img for img in all_images if img.get(ImageFields.STATUS) != ImageFields.STATUS_DONE and img.get(ImageFields.IMAGE_PROMPT)]

        if not pending:
            print(f"    ✅ All images verified complete")
            break

        print(f"    🔄 RETRY {retry_round + 1}/{max_retries}: Found {len(pending)} pending images")
        pipeline.slack.notify(f"🔄 Retry {retry_round + 1}: {len(pending)} pending images for *{pipeline.video_title}*")

        retry_scenes = defaultdict(list)
        for img in pending:
            retry_scenes[img.get(ImageFields.SCENE, 0)].append(img)

        retry_count = 0
        for s_num in sorted(retry_scenes.keys()):
            s_images = retry_scenes[s_num]
            print(f"      Scene {s_num}: {len(s_images)} pending")

            for img_record in s_images:
                record_id = img_record["id"]
                prompt = img_record.get(ImageFields.IMAGE_PROMPT, "")
                index = img_record.get(ImageFields.IMAGE_INDEX, 0)

                try:
                    if model_override == Models.IMAGE_ZIMAGE:
                        result = await pipeline.image_client.generate_scene_image_zimage(prompt, aspect_ratio="16:9")
                    elif use_reference:
                        result = await pipeline.image_client.generate_scene_image(prompt, pipeline.core_image_url)
                    else:
                        result_urls = await pipeline.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                        result = {"url": result_urls[0]} if result_urls and len(result_urls) > 0 else None
                    if result and result.get("url"):
                        image_url = result["url"]
                        image_content = await pipeline.image_client.download_image(image_url)
                        filename = f"Scene_{str(s_num).zfill(2)}_{str(index).zfill(2)}.png"
                        drive_download_url = None
                        try:
                            drive_file = pipeline.google.upload_image(image_content, filename, images_folder_id)
                            drive_download_url = pipeline.google.make_file_public(drive_file["id"])
                        except Exception:
                            pass
                        pipeline.airtable.update_image_record(record_id, image_url, drive_url=drive_download_url)
                        retry_count += 1
                        image_count += 1
                        print(f"        ✅ Scene {s_num}, Image {index} → Done (retry)")
                        del image_content
                    else:
                        print(f"        ❌ Scene {s_num}, Image {index} → No image returned (retry)")
                except Exception as e:
                    print(f"        ❌ Scene {s_num}, Image {index} → {e}")

                await asyncio.sleep(2)

        print(f"    ✅ Retry {retry_round + 1} complete: {retry_count} recovered")
        if retry_count == 0:
            print(f"    ⚠️ No progress made, stopping retries")
            break

    # Final check
    final_images = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
    final_pending = len([img for img in final_images if img.get(ImageFields.STATUS) != ImageFields.STATUS_DONE and img.get(ImageFields.IMAGE_PROMPT)])
    if final_pending > 0:
        pipeline.slack.notify(f"⚠️ {final_pending} images still pending after retries for *{pipeline.video_title}*")
    else:
        pipeline.slack.notify(f"✅ All {len(final_images)} images complete for *{pipeline.video_title}*")

    return {"image_count": image_count, "failed_count": failed_count}
