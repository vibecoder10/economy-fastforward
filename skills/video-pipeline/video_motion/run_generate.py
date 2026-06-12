"""Video generation step — creates video clips from images with motion prompts.

Reads: Images with Video Prompt + Drive Image URL from Images table
Writes: Video attachment + Video Clip URL + Animation Status to Images table
Advances: Ready For Video Generation → Ready For Thumbnail
Clients: image_client, google, airtable
"""

import asyncio

from orchestrator.pipeline_constants import ImageFields, Statuses


async def run(pipeline) -> dict:
    """Generate video clips from images with motion prompts."""
    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_VIDEO_GENERATION)
        if not idea:
            return {"error": "No idea at 'Ready For Video Generation'."}
        pipeline._load_idea(idea)

    print(f"\n  🎥 VIDEO GEN BOT: Generating videos...")
    pipeline._log_filters()

    # Get images ready for video generation (with Video Prompt, no Video yet)
    pending_videos = pipeline.airtable.get_images_ready_for_video_generation(pipeline.video_title)

    # Only those with a Video Prompt
    pending_videos = [v for v in pending_videos if v.get(ImageFields.VIDEO_PROMPT)]

    # Apply scene/image filters
    pending_videos = pipeline._filter_by_scene(pending_videos)

    if not pending_videos:
        print("    No pending videos to generate.")
        if not pipeline._is_targeted_run:
            print(f"    All videos done. Moving to Thumbnail.")
            pipeline._update_status(Statuses.READY_THUMBNAIL)
        return {
            "bot": "Video Gen Bot",
            "video_title": pipeline.video_title,
            "video_count": 0,
            "new_status": Statuses.READY_THUMBNAIL,
        }

    video_count = 0
    failed_count = 0
    total = len(pending_videos)
    print(f"    Found {total} images needing video generation.")

    # Concurrent generation with semaphore-based rate limiting
    MAX_CONCURRENT_VIDEOS = 3
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VIDEOS)

    _should_cancel = getattr(pipeline, "should_cancel", None)

    async def _cancelled() -> bool:
        """Cooperative Stop check — called before each paid clip generation."""
        try:
            return bool(_should_cancel) and await _should_cancel()
        except Exception:
            return False
    print(f"    Concurrency: {MAX_CONCURRENT_VIDEOS} parallel video generations")

    async def generate_single_video(i, img_record):
        """Generate, download, upload, and checkpoint a single video clip."""
        nonlocal video_count, failed_count

        scene = img_record.get(ImageFields.SCENE, 0)
        index = img_record.get(ImageFields.IMAGE_INDEX, 0)

        # Use permanent Drive URL instead of expiring Airtable attachment
        drive_url = img_record.get(ImageFields.DRIVE_IMAGE_URL)
        if not drive_url:
            # Fallback to attachment URL if Drive URL missing (legacy records)
            image_url_list = img_record.get(ImageFields.IMAGE, [])
            drive_url = image_url_list[0].get("url") if image_url_list else None

        motion_prompt = img_record.get(ImageFields.VIDEO_PROMPT)

        if not drive_url or not motion_prompt:
            return

        # Convert to direct download URL for Grok Imagine
        image_url = pipeline.google.get_direct_drive_url(drive_url)

        # Hero selection: duration > 6s gets 10s clip, otherwise 6s.
        # `or`-default: the column can exist as NULL (extraction's extra panels).
        segment_duration = img_record.get(ImageFields.DURATION) or 6.0
        clip_duration = 10 if segment_duration > 6.0 else 6

        async with semaphore:
            if await _cancelled():
                return  # Stop requested — skip queued clips, keep in-flight ones
            print(f"    [{i}/{total}] Scene {scene}, Image {index} "
                  f"({segment_duration:.1f}s → {clip_duration}s clip"
                  f"{'  HERO' if clip_duration == 10 else ''})")
            print(f"      Motion: {motion_prompt}")

            # Generate video with appropriate duration
            video_url = await pipeline.image_client.generate_video(
                image_url, motion_prompt, duration=clip_duration
            )

            if video_url:
                print(f"      [{i}/{total}] Downloading video content...")
                video_content = await pipeline.image_client.download_image(video_url)

                filename = f"Scene_{str(scene).zfill(2)}_{str(index).zfill(2)}.mp4"
                print(f"      [{i}/{total}] Uploading {filename} to Drive...")
                drive_file = pipeline.google.upload_video(
                    video_content, filename, pipeline.project_folder_id
                )
                video_drive_url = pipeline.google.make_file_public(drive_file["id"])

                # Update Airtable — write persistent Drive URL + animation status
                pipeline.airtable.update_image_video_url(img_record["id"], video_url)
                pipeline.airtable.update_image_animation_fields(
                    img_record["id"],
                    video_clip_url=video_drive_url,
                    animation_status=ImageFields.STATUS_DONE,
                    video_duration=clip_duration,
                )
                print(f"      ✅ [{i}/{total}] Video saved ({filename})")
                video_count += 1
                del video_content
            else:
                pipeline.airtable.update_image_animation_fields(
                    img_record["id"],
                    animation_status="Failed",  # No constant needed — only used here
                )
                failed_count += 1
                print(f"      ❌ [{i}/{total}] Video generation failed.")

    # Fire all tasks — semaphore limits to MAX_CONCURRENT_VIDEOS at a time
    await asyncio.gather(
        *[generate_single_video(i, img) for i, img in enumerate(pending_videos, 1)]
    )

    print(f"    ✅ Generated {video_count}/{total} videos"
          f"{f' ({failed_count} failed)' if failed_count else ''}")

    # User pressed Stop — keep completed clips, don't advance status
    if await _cancelled():
        print(f"  🛑 Stopped by user — kept {video_count} completed clip(s)")
        pipeline.slack.notify(f"🛑 Video generation stopped by user ({video_count}/{total} done)")
        return {
            "bot": "Video Gen Bot",
            "video_title": pipeline.video_title,
            "video_count": video_count,
            "cancelled": True,
        }

    if pipeline._is_targeted_run:
        print(f"  🎯 Targeted run — status NOT advanced")
        return {
            "bot": "Video Gen Bot",
            "video_title": pipeline.video_title,
            "video_count": video_count,
            "targeted": True,
        }

    # Check if all videos are done
    remaining = [v for v in pipeline.airtable.get_images_ready_for_video_generation(pipeline.video_title) if v.get(ImageFields.VIDEO_PROMPT)]
    if not remaining:
        pipeline._update_status(Statuses.READY_THUMBNAIL)
        print(f"  ✅ Status updated to: {Statuses.READY_THUMBNAIL}")

    return {
        "bot": "Video Gen Bot",
        "video_title": pipeline.video_title,
        "video_count": video_count,
        "new_status": Statuses.READY_THUMBNAIL if not remaining else None,
    }
