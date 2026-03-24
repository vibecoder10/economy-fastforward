"""Remotion packaging step — builds props.json for video rendering.

Assembles all scene data (scripts, images, video clips, sound effects)
into a single props structure that Remotion reads at render time.

Prefers video clips over static images when available.
Priority for each image slot:
1. Video Clip URL (animated) from Google Drive
2. Drive Image URL (static) from Google Drive
3. NEVER use Airtable attachment URLs (they expire)

Reads: Scripts table, Images table (attachments, durations, sound effects)
Writes: props.json
Clients: airtable
"""

from pipeline_constants import ImageFields, ScriptFields


async def run(pipeline) -> dict:
    """Package all assets for Remotion video editing."""
    # Get all scripts for current video
    scripts = pipeline.airtable.get_scripts_by_title(pipeline.video_title)

    # Get all images for current video
    images = pipeline.airtable.get_all_images_for_video(pipeline.video_title)

    # Build Remotion props structure
    scenes = []
    for script in scripts:
        scene_number = script.get("scene", 0)
        scene_images = [
            img for img in images
            if img.get(ImageFields.SCENE) == scene_number
        ]

        # Sort images by index
        sorted_images = sorted(scene_images, key=lambda x: x.get(ImageFields.IMAGE_INDEX, 0))

        processed_images = []
        for img in sorted_images:
            # Check for video clip first (animation pipeline output)
            video_clip_url = img.get(ImageFields.VIDEO_CLIP_URL)
            video_attachments = img.get(ImageFields.VIDEO, [])

            # Prefer video clip over static image
            if video_clip_url:
                media_url = video_clip_url
                media_type = "video"
            elif video_attachments:
                media_url = video_attachments[0].get("url", "") if video_attachments else ""
                media_type = "video"
            else:
                media_url = img.get(ImageFields.DRIVE_IMAGE_URL) or (
                    img.get(ImageFields.IMAGE, [{}])[0].get("url", "") if img.get(ImageFields.IMAGE) else ""
                )
                media_type = "image"

            # Build base asset
            asset = {
                "index": img.get(ImageFields.IMAGE_INDEX, 0),
                "url": media_url,
                "type": media_type,
                "segmentText": img.get(ImageFields.SENTENCE_TEXT, ""),
                "duration": img.get(ImageFields.DURATION, 8.0),
                "isHeroShot": img.get(ImageFields.HERO_SHOT, False),
                "videoDuration": img.get(ImageFields.VIDEO_DURATION, 6),
            }

            # =============================================================
            # TIMING RECONCILIATION LAYER
            # Handles mismatch between voiceover duration and clip duration
            # =============================================================
            voiceover_duration = asset["duration"]
            clip_duration = asset["videoDuration"] if media_type == "video" else None

            if clip_duration is None:
                asset["renderDuration"] = voiceover_duration
                asset["playbackRate"] = 1.0
            elif abs(voiceover_duration - clip_duration) <= 1.5:
                asset["renderDuration"] = voiceover_duration
                asset["playbackRate"] = clip_duration / voiceover_duration if voiceover_duration > 0 else 1.0
            elif voiceover_duration > clip_duration + 1.5:
                asset["renderDuration"] = voiceover_duration
                asset["playbackRate"] = 1.0
                asset["holdLastFrame"] = voiceover_duration - clip_duration
            else:
                asset["renderDuration"] = voiceover_duration
                asset["playbackRate"] = 1.0
                asset["trimEnd"] = clip_duration - voiceover_duration

            # Per-image sound effect
            sfx_attachment = img.get(ImageFields.SOUND_EFFECT)
            if sfx_attachment and isinstance(sfx_attachment, list) and sfx_attachment:
                sfx_url = sfx_attachment[0].get("url", "")
                if sfx_url:
                    sfx_filename = f"sfx_{scene_number}_{img.get(ImageFields.IMAGE_INDEX, 0)}.mp3"
                    asset["sfx"] = f"sfx/{sfx_filename}"
                    asset["sfxVolume"] = img.get(ImageFields.SOUND_VOLUME, 0.15)
                    asset["sfxUrl"] = sfx_url

            processed_images.append(asset)

        scenes.append({
            "sceneNumber": scene_number,
            "text": script.get(ScriptFields.SCENE_TEXT, ""),
            "voiceUrl": script.get(ScriptFields.VOICE_OVER, [{}])[0].get("url", "") if script.get(ScriptFields.VOICE_OVER) else "",
            "images": processed_images,
        })

    props = {
        "videoTitle": pipeline.video_title,
        "folderId": pipeline.project_folder_id,
        "docId": pipeline.google_doc_id,
        "scenes": scenes,
    }

    return props
