"""Video script step — generates motion prompts for image-to-video conversion.

Reads: Done images from Images table (Image Prompt, Sentence Text, Shot Type)
Writes: Video Prompt field to Images table
Advances: Ready For Video Scripts → Ready For Video Generation
Clients: anthropic, airtable
"""

from orchestrator.pipeline_constants import ImageFields, Statuses, Models
from image_prompts.engine.prompt_builder import CAMERA_MOVEMENTS, detect_camera_movement, validate_video_prompt


async def run(pipeline) -> dict:
    """Generate video motion prompts for images."""
    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_VIDEO_SCRIPTS)
        if not idea:
            return {"error": "No idea at 'Ready For Video Scripts'."}
        pipeline._load_idea(idea)

    target = f"Scene {pipeline.scene_filter}" if pipeline.scene_filter else "all scenes"
    print(f"\n  📝 VIDEO SCRIPT BOT: Generating prompts for {target}...")
    pipeline._log_filters()

    # Get pending images
    existing_images = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
    done_images = [img for img in existing_images if img.get(ImageFields.STATUS) == ImageFields.STATUS_DONE]

    # Apply scene/image filters
    done_images = pipeline._filter_by_scene(done_images)

    # Sort by scene and image index for proper camera history ordering
    done_images = sorted(
        done_images,
        key=lambda x: (x.get(ImageFields.SCENE, 0), x.get(ImageFields.IMAGE_INDEX, 0)),
    )

    prompt_count = 0
    hero_count = 0
    camera_history: list[str] = []

    # Pre-populate camera history from images that already have prompts
    for img_record in done_images:
        existing_prompt = img_record.get(ImageFields.VIDEO_PROMPT, "")
        if existing_prompt:
            camera_history.append(detect_camera_movement(existing_prompt))

    for img_record in done_images:
        scene = img_record.get(ImageFields.SCENE, 0)

        # Check if prompt already exists
        if img_record.get(ImageFields.VIDEO_PROMPT):
            continue

        image_prompt = img_record.get(ImageFields.IMAGE_PROMPT, "")
        if not image_prompt:
            print(f"    ⚠️ No Image Prompt found for Scene {scene}, skipping.")
            continue

        # Get segment data. `or`-defaults, not .get defaults: extraction can
        # insert extra panels whose columns EXIST as NULL (scene 2's 6th slot)
        # — .get(key, default) returns None for those and `None > 6.0` killed
        # the whole prompt run.
        sentence_text = img_record.get(ImageFields.SENTENCE_TEXT) or ""
        shot_type = img_record.get(ImageFields.SHOT_TYPE) or "medium_human_story"
        duration = img_record.get(ImageFields.DURATION) or 6.0

        # Smart hero selection: duration > 6s gets 10s clip
        is_hero = duration > 6.0
        clip_duration = 10 if is_hero else 6

        if is_hero:
            hero_count += 1

        idx = img_record.get(ImageFields.IMAGE_INDEX, "?")
        print(f"    [{idx}] {shot_type} | {duration:.1f}s segment → {clip_duration}s clip {'(HERO)' if is_hero else ''}")

        motion_prompt = await pipeline.anthropic.generate_video_prompt(
            image_prompt=image_prompt,
            sentence_text=sentence_text,
            scene_type=shot_type,
            is_hero_shot=is_hero,
            prev_cameras=camera_history,
            system_prompt_override=getattr(pipeline, "video_motion_system_prompt", None),
        )

        # Validate video prompt quality — regenerate if it fails
        validation = validate_video_prompt(
            motion_prompt, sentence_text,
            prev_cameras=camera_history,
            clip_duration_seconds=clip_duration,
        )
        if not validation["valid"]:
            print(f"    ⚠️ Video prompt failed validation: {validation['issues']}")

            # Build camera-aware regeneration prompt
            camera_block = ""
            if camera_history:
                blocked = camera_history[-1]
                allowed = ", ".join(k for k in CAMERA_MOVEMENTS if k != blocked)
                camera_block = (
                    f"\n\nCAMERA ROTATION: You MUST NOT use '{blocked}'. "
                    f"Pick from: {allowed}"
                )

            regen_prompt = (
                f'This video prompt failed quality validation: {validation["issues"]}\n\n'
                f'Sentence text: "{sentence_text}"\n'
                f'Original prompt: "{motion_prompt}"\n\n'
                "Rewrite the video prompt following the Narrative Beat Method:\n"
                "1. Identify the emotional beats in the sentence\n"
                "2. Assign each beat a specific visual verb\n"
                "3. Sequence motions to mirror the narration timeline\n"
                "4. End with a strong payoff line that lands emotionally\n"
                "5. Zero filler — every motion must serve the story"
                f"{camera_block}"
            )
            motion_prompt = await pipeline.anthropic.generate(
                prompt=regen_prompt,
                system_prompt="You are a cinematographer. Return ONLY the rewritten motion prompt. No explanations.",
                model=Models.CLAUDE_SONNET,
                max_tokens=200,
            )
            motion_prompt = motion_prompt.strip()
            print(f"    ✅ Regenerated video prompt for [{idx}]")

        # Track camera movement for rotation enforcement
        camera_history.append(detect_camera_movement(motion_prompt))

        # Update Airtable with video prompt
        pipeline.airtable.update_image_video_prompt(img_record["id"], motion_prompt)
        prompt_count += 1

    print(f"    ✅ Generated {prompt_count} video prompts ({hero_count} hero shots @ 10s)")

    if pipeline._is_targeted_run:
        print(f"  🎯 Targeted run — status NOT advanced")
        return {"bot": "Video Script Bot", "prompt_count": prompt_count, "targeted": True}

    # Update Status to Ready For Video Generation
    pipeline._update_status(Statuses.READY_VIDEO_GENERATION)
    print(f"  ✅ Status updated to: {Statuses.READY_VIDEO_GENERATION}")

    return {
        "bot": "Video Script Bot",
        "video_title": pipeline.video_title,
        "prompt_count": prompt_count,
        "new_status": Statuses.READY_VIDEO_GENERATION,
    }
