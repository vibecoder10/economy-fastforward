"""Image prompt generation step — expands script scenes into styled image prompts.

Reads: Script records from Scripts table, Story Bible, visual profile
Writes: Image records to Images table with styled prompts
Advances: Ready For Image Prompts → Ready For Images
Clients: anthropic, airtable, google, slack
"""

import json

from orchestrator.pipeline_constants import Statuses, Models, IdeaFields, ScriptFields, ImageFields


def _get_visual_seeds(idea: dict) -> str:
    """Extract visual seed concepts from the idea record.

    Checks the Research Payload JSON first, then falls back to the
    Thumbnail Prompt field.
    """
    if not idea:
        return ""
    rp_raw = idea.get(IdeaFields.RESEARCH_PAYLOAD, "")
    if rp_raw:
        try:
            rp = json.loads(rp_raw) if isinstance(rp_raw, str) else rp_raw
            vs = rp.get("visual_seeds", "")
            if vs:
                return vs
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    return idea.get(IdeaFields.THUMBNAIL_PROMPT, "")


async def run(pipeline) -> dict:
    """Expand script scenes into visual concepts and generate styled image prompts.

    Two-pass scene-by-scene pipeline:

    Pass 1 — Expand: For each Script table record, expand its narration
    into 6-10 visual concepts via LLM. Each concept's sentence_text is
    validated as an exact substring of the original scene text. Written
    to Airtable Images table immediately after each scene.

    Pass 2 — Prompt: For each Image record missing an Image Prompt,
    build the styled prompt (prefix + description + composition + suffix)
    and write it back.

    Audio sync runs after both passes to populate real durations.
    """
    from image_prompts.engine.prompt_builder import build_prompt, build_prompt_from_block, assign_profile_styles
    from image_prompts.engine.sequencer import assign_styles
    from image_prompts.engine.camera_selector import (
        ShotContext, select_camera_move_async, clear_tiebreak_cache,
    )
    from script.brief_translator.scene_expander import expand_scene_concepts, expand_scene_concepts_deterministic

    if not pipeline.current_idea:
        idea = pipeline.get_idea_by_status(Statuses.READY_IMAGE_PROMPTS)
        if not idea:
            return {"error": "No idea at Ready For Image Prompts"}
        pipeline._load_idea(idea)

    print(f"\n🎨 STYLED IMAGE PROMPTS: Processing '{pipeline.video_title}'")
    pipeline._log_filters()

    # Detect active visual profile for profile-aware sequencing
    try:
        from shared.profiles.visual import load_profile as _load_vp_seq
        _active_profile = _load_vp_seq()
    except Exception:
        _active_profile = None
    _use_profile_sequencer = (
        _active_profile is not None
        and _active_profile.profile_id != "holographic_hud"
        and _active_profile.style_system.substyles
    )
    if _use_profile_sequencer:
        print(f"  🎨 Using profile-aware sequencer: {_active_profile.profile_id}")

    # Read per-video image style override (set via Slack !style command)
    image_style_override = (pipeline.current_idea.get(IdeaFields.IMAGE_STYLE_OVERRIDE) or "").strip()
    if image_style_override:
        print(f"  🎨 Image style override active: {image_style_override[:80]}...")

    # ---------------------------------------------------------------
    # Load script records from Airtable (source of truth)
    # ---------------------------------------------------------------
    scripts = pipeline.airtable.get_scripts_by_title(pipeline.video_title)
    if not scripts:
        return {
            "error": f"No script records found for '{pipeline.video_title}'. "
            "Run Script Bot first."
        }

    total_scripts = len(scripts)
    print(f"  Found {total_scripts} script records")

    # Determine accent color: Airtable field first, then topic category map, then default
    from image_prompt_engine import resolve_accent_color
    airtable_color = (pipeline.current_idea.get(IdeaFields.ACCENT_COLOR) or "").replace("_", " ").strip()
    accent_color = resolve_accent_color(
        accent_color=airtable_color or None,
    )
    visual_seeds = _get_visual_seeds(pipeline.current_idea)

    # Check which scenes already have image records (for resume/update)
    existing_images = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
    existing_images_by_scene: dict[int, list[dict]] = {}
    existing_images_by_scene_and_index: dict[tuple[int, int], dict] = {}
    completed_scenes: set[int] = set()

    for img in existing_images:
        scene_num = img.get(ImageFields.SCENE)
        image_idx = img.get(ImageFields.IMAGE_INDEX)
        if scene_num is None:
            continue

        scene_num = int(scene_num)
        existing_images_by_scene.setdefault(scene_num, []).append(img)

        if image_idx is not None:
            existing_images_by_scene_and_index[(scene_num, int(image_idx))] = img

    for scene_num, scene_images in existing_images_by_scene.items():
        if scene_images and all((img.get(ImageFields.IMAGE_PROMPT) or "").strip() for img in scene_images):
            completed_scenes.add(scene_num)

    if existing_images_by_scene:
        completed = sorted(completed_scenes)
        pending = sorted(scene for scene in existing_images_by_scene if scene not in completed_scenes)
        if completed:
            print(f"  Found completed prompt records for scenes {completed} — will resume past them")
        if pending:
            print(f"  Found existing image rows without prompts for scenes {pending} — will fill them")

    # ---------------------------------------------------------------
    # Pre-generate style assignments for all images using sequencer
    # ---------------------------------------------------------------
    estimated_total_images = total_scripts * 10
    style_seed = hash(pipeline.video_title) % (2**32)
    print(f"  Generating style assignments for ~{estimated_total_images} images...")

    if _use_profile_sequencer:
        style_assignments = assign_profile_styles(
            total_images=estimated_total_images,
            profile=_active_profile,
            seed=style_seed,
        )
    else:
        style_assignments = assign_styles(
            total_images=estimated_total_images,
            seed=style_seed,
        )
    print(f"  ✓ Style rotation configured: {len(style_assignments)} assignments ready")

    # ---------------------------------------------------------------
    # Generate or load Story Bible for visual consistency
    # ---------------------------------------------------------------
    story_bible = None
    uses_story_bible = (
        _active_profile is not None
        and _active_profile.profile_id not in ("holographic_hud",)
    )
    needs_prompt_backfill = any(
        scene not in completed_scenes
        for scene in existing_images_by_scene
    )

    if uses_story_bible:
        story_bible = _load_or_generate_story_bible(pipeline, scripts)
        if story_bible is None and needs_prompt_backfill:
            print("  📖 Skipping Story Bible generation during prompt backfill — filling existing image rows first")
        elif story_bible is None:
            story_bible = await _generate_story_bible(pipeline, scripts)

    # ---------------------------------------------------------------
    # Expand each script record into visual concepts + styled prompts
    # ---------------------------------------------------------------
    if pipeline.scene_filter is not None:
        scripts = [s for s in scripts if s.get("scene") == pipeline.scene_filter]
        print(f"  🎯 Filtered to scene {pipeline.scene_filter}: {len(scripts)} script(s)")

    print(f"\n  --- Expanding {len(scripts)} scenes into visual concepts + prompts ---")

    total_concepts = 0
    scenes_expanded = 0
    scenes_skipped = 0
    style_counts = {}
    image_index = 0

    # ---------------------------------------------------------------
    # Camera Movement Engine — plan the move BEFORE the image is drawn
    # so its image_setup can shape composition (see camera_selector.py).
    # STORYTELLING ONLY: the engine follows the Story Bible marker — data
    # display formats (holographic_hud) keep their existing static-first
    # behavior with no planned moves.
    # ---------------------------------------------------------------
    camera_engine_on = uses_story_bible
    clear_tiebreak_cache()
    camera_plan_ids: list[str] = []      # recent planned move ids (variety)
    camera_plan_keys: list[str] = []     # recent legacy keys (anti-repeat)
    camera_plan_counts: dict[str, int] = {}
    video_model = (pipeline.current_idea.get(IdeaFields.VIDEO_MODEL) or "").strip() \
        if pipeline.current_idea else ""
    if camera_engine_on:
        print("  🎥 Camera Movement Engine: ON (storytelling format)")
    else:
        print("  🎥 Camera Movement Engine: off (non-storytelling format)")

    for script in scripts:
        scene_num = script.get("scene", 0)
        scene_text = script.get(ScriptFields.SCENE_TEXT, "") or script.get(IdeaFields.SCRIPT, "")

        if not scene_text:
            print(f"  Scene {scene_num}: empty text, skipping")
            continue

        scene_existing_images = existing_images_by_scene.get(scene_num, [])
        if scene_num in completed_scenes:
            existing_image_count = len(scene_existing_images)
            if pipeline.image_filter is not None:
                has_target = any(
                    img.get(ImageFields.IMAGE_INDEX) == pipeline.image_filter
                    for img in scene_existing_images
                )
                if has_target:
                    image_index += existing_image_count
                    scenes_skipped += 1
                    print(f"  Scene {scene_num}, Image {pipeline.image_filter}: Skipped (prompt already exists)")
                    continue
                print(f"  Scene {scene_num}: {existing_image_count} images exist, but index {pipeline.image_filter} missing — generating")
            else:
                image_index += existing_image_count
                scenes_skipped += 1
                print(f"  Scene {scene_num}: Skipped (has {existing_image_count} prompted images), advanced index to {image_index}")
                continue

        act_number = min(6, (scene_num - 1) * 6 // total_scripts + 1) if total_scripts > 0 else 1

        print(f"  Scene {scene_num} (Act {act_number}): "
              f"{len(scene_text.split())} words — expanding...")

        # Get voice duration for accurate words-per-second calculation
        voice_duration = None
        voice_over = script.get(ScriptFields.VOICE_OVER)
        if voice_over and isinstance(voice_over, list) and len(voice_over) > 0:
            voice_url = voice_over[0].get("url")
            if voice_url:
                try:
                    from shared.clients.sentence_utils import get_audio_duration
                    voice_duration = get_audio_duration(voice_url)
                    if voice_duration:
                        print(f"    Voice duration: {voice_duration:.1f}s "
                              f"({len(scene_text.split()) / voice_duration:.2f} WPS)")
                except Exception as e:
                    print(f"    ⚠️ Could not get voice duration: {e}")

        concepts = await expand_scene_concepts_deterministic(
            anthropic_client=pipeline.anthropic,
            scene_number=scene_num,
            scene_text=scene_text,
            visual_seeds=visual_seeds,
            accent_color=accent_color,
            act_number=act_number,
            total_scenes=total_scripts,
            voice_duration=voice_duration,
            story_bible=story_bible,
        )

        # Regenerate visual descriptions for duration-adjusted concepts
        needs_regen = [c for c in concepts if c.get("needs_new_prompt")]
        if needs_regen:
            print(f"    Regenerating {len(needs_regen)} visual descriptions "
                  f"(duration-adjusted concepts)...")
            await _regenerate_visual_descriptions(
                pipeline, needs_regen, story_bible, scene_num
            )

        # If image_filter is set, only generate the specific concept
        if pipeline.image_filter is not None:
            concepts = [c for c in concepts if c["concept_index"] == pipeline.image_filter]
            if not concepts:
                print(f"    ⚠️ No concept with index {pipeline.image_filter} in scene {scene_num}, skipping")
                continue
            print(f"    🎯 Filtered to concept {pipeline.image_filter}: {len(concepts)} concept(s)")

        for concept_pos, concept in enumerate(concepts):
            visual_desc = concept["visual_description"]

            # --- Camera Movement Engine: pick the move for this shot ---
            camera_selection = None
            if camera_engine_on:
                try:
                    shot_ctx = ShotContext(
                        sentence_text=concept.get("sentence_text", ""),
                        composition=concept.get("composition", "medium"),
                        intensity="high" if act_number >= 6 else "medium",
                        is_scene_open=(concept_pos == 0),
                        is_scene_final=(concept_pos == len(concepts) - 1),
                        is_video_open=(image_index == 0),
                        video_model=video_model,
                        prev_move_ids=camera_plan_ids,
                        prev_legacy_keys=camera_plan_keys,
                    )
                    camera_selection = await select_camera_move_async(
                        shot_ctx, anthropic_client=pipeline.anthropic,
                    )
                except Exception as e:
                    print(f"      ⚠️ Camera selection failed (non-blocking, shot stays static): {e}")

            if camera_selection and camera_selection.move:
                move = camera_selection.move
                # Two-way contract, image side: compose the still FOR the move
                visual_desc = (
                    f"{visual_desc.rstrip('. ')}. "
                    f"Compose this frame for a {move.name.lower()} camera move: {move.image_setup}"
                )
                concept["visual_description"] = visual_desc
                camera_plan_ids.append(move.id)
                camera_plan_keys.append(move.legacy_key)
                camera_plan_counts[move.id] = camera_plan_counts.get(move.id, 0) + 1
            elif camera_selection:
                camera_plan_keys.append("static")

            # Get style assignment from sequencer (extend if needed)
            if image_index >= len(style_assignments):
                new_total = image_index + total_scripts * 10
                print(f"      ↻ Extending style assignments: "
                      f"{len(style_assignments)} → {new_total}")
                if _use_profile_sequencer:
                    style_assignments = assign_profile_styles(
                        total_images=new_total,
                        profile=_active_profile,
                        seed=style_seed,
                    )
                else:
                    style_assignments = assign_styles(
                        total_images=new_total, seed=style_seed,
                    )
            style = style_assignments[image_index]
            content_type = style["content_type"]
            display_format = style["display_format"]
            color_mood = style["color_mood"]

            # Build styled prompt — use block context if available (V2 Story Bible)
            has_block_context = bool(concept.get("block_location"))
            if has_block_context and story_bible:
                prompt = build_prompt_from_block(
                    concept=concept,
                    story_bible=story_bible,
                    image_style_override=image_style_override,
                    content_type=content_type,
                    display_format=display_format,
                    color_mood=color_mood,
                )
            else:
                prompt = build_prompt(
                    scene_description=visual_desc,
                    content_type=content_type,
                    display_format=display_format,
                    color_mood=color_mood,
                    image_style_override=image_style_override,
                )

            # Diagnostic: print first 3 assembled prompts
            if image_index < 3:
                print(f"\n  📋 PROMPT DIAGNOSTIC [{image_index + 1}/3] "
                      f"(scene {scene_num}, type={display_format}):")
                print(f"     {prompt}")
                print()

            camera_composition = concept.get("composition", "medium")

            # Structured per-panel location (== bible block location id). Lets a
            # storyboard grid resolve its location later and pull the matching
            # environment reference. Empty for the no-bible path → safe null.
            block_location_id = concept.get("block_location_id") or None

            existing_record = existing_images_by_scene_and_index.get((scene_num, concept["concept_index"]))
            if existing_record:
                pipeline.airtable.update_image_prompt_fields(
                    existing_record["id"],
                    image_prompt=prompt,
                    shot_type=camera_composition,
                    location_id=block_location_id,
                )
                record_id = existing_record["id"]
            else:
                created = pipeline.airtable.create_concept_record(
                    scene_number=scene_num,
                    concept_index=concept["concept_index"],
                    sentence_text=concept["sentence_text"],
                    image_prompt=prompt,
                    composition=camera_composition,
                    video_title=pipeline.video_title,
                    location_id=block_location_id,
                )
                record_id = (created or {}).get("id")

            # Persist the planned camera move ("move_id|PURPOSE", or "static")
            # so the video-motion step animates the move this image was
            # composed for. Duck-typed: legacy adapters without the method
            # simply skip persistence and fall back to old behavior.
            _set_cam = getattr(pipeline.airtable, "update_image_camera_movement", None)
            if _set_cam and record_id and camera_selection is not None:
                try:
                    if camera_selection.move:
                        _set_cam(record_id, f"{camera_selection.move.id}|{camera_selection.purpose}")
                    else:
                        _set_cam(record_id, "static")
                except Exception as e:
                    print(f"      ⚠️ Could not persist camera plan (non-blocking): {e}")

            style_counts[display_format] = style_counts.get(display_format, 0) + 1
            image_index += 1

        total_concepts += len(concepts)
        scenes_expanded += 1
        print(f"    {len(concepts)} concepts + prompts written to Airtable")

    skip_note = f" ({scenes_skipped} resumed)" if scenes_skipped else ""
    print(f"\n  Done: {scenes_expanded} scenes expanded, "
          f"{total_concepts} concepts created{skip_note}")

    # Camera Movement Engine summary
    planned_total = sum(camera_plan_counts.values())
    if camera_engine_on and total_concepts:
        print(f"  🎥 Camera plan: {planned_total}/{total_concepts} shots earned a move "
              f"({total_concepts - planned_total} static)")
        for move_id, count in sorted(camera_plan_counts.items(), key=lambda x: -x[1]):
            print(f"      {move_id}: {count}")

    # Report display format distribution
    if style_counts:
        total_styled = sum(style_counts.values())
        print(f"  Display format variety:")
        for fmt, count in sorted(style_counts.items(), key=lambda x: -x[1]):
            pct = count / total_styled * 100
            print(f"    {fmt}: {count} ({pct:.0f}%)")

    # ---------------------------------------------------------------
    # Audio Sync: Whisper-aligned durations
    # ---------------------------------------------------------------
    audio_sync_summary = ""
    if pipeline._is_targeted_run:
        print(f"\n  🎯 Targeted run — skipping audio sync (needs all images)")
    else:
        try:
            print(f"\n  Running audio sync for scene durations...")
            sync_result = await pipeline.run_audio_sync()

            if sync_result.get("error"):
                print(f"  Audio sync skipped: {sync_result['error']}")
                audio_sync_summary = f" | Audio sync skipped: {sync_result['error']}"
            else:
                avg_dur = sync_result["total_duration"] / max(sync_result["scene_count"], 1)
                print(f"  Audio sync: {sync_result['scene_count']} scenes aligned, "
                      f"avg {avg_dur:.1f}s, {sync_result.get('image_count', 0)} records updated")
                audio_sync_summary = (
                    f" | Audio sync: {sync_result['scene_count']} scenes, "
                    f"avg {avg_dur:.1f}s"
                )
        except Exception as e:
            print(f"  Audio sync failed (non-blocking): {e}")
            audio_sync_summary = f" | Audio sync error: {e}"

    # Prompt Validation — DISABLED (sequencer + Story Bible V2 handle it upstream)
    validation_summary = ""

    # Update status (skip if targeted run)
    if pipeline._is_targeted_run:
        print(f"  🎯 Targeted run — status NOT advanced")
        return {
            "bot": "Styled Image Prompt Engine",
            "video_title": pipeline.video_title,
            "scenes_expanded": scenes_expanded,
            "total_concepts": total_concepts,
            "targeted": True,
        }

    # Route based on Storyboard Mode (read from Scripts table)
    # Check first script record for "Story Board On/OFF" field
    storyboard_mode = "off"
    if scripts:
        first_script = scripts[0] if isinstance(scripts[0], dict) else {}
        # Handle both raw dict and {fields: {...}} format
        fields = first_script.get("fields", first_script)
        storyboard_mode = (fields.get(ScriptFields.STORYBOARD_MODE) or "off").lower()

    if storyboard_mode == "on":
        next_status = Statuses.READY_STORYBOARDS
    else:
        next_status = Statuses.READY_IMAGES

    pipeline._update_status(next_status)
    print(f"  Status updated to: {next_status}")

    skip_note = f" ({scenes_skipped} resumed)" if scenes_skipped else ""
    total_styled = sum(style_counts.values()) or 1
    style_summary = " | ".join(
        f"{fmt}: {cnt} ({cnt / total_styled * 100:.0f}%)"
        for fmt, cnt in sorted(style_counts.items(), key=lambda x: -x[1])
    )
    pipeline.slack.notify(
        f"Styled prompts done: {total_concepts} concepts from {scenes_expanded} scenes{skip_note} "
        f"for *{pipeline.video_title}*\n"
        f"{style_summary}"
        f"{audio_sync_summary}"
        f"{validation_summary}"
    )

    return {
        "bot": "Styled Image Prompt Engine",
        "video_title": pipeline.video_title,
        "scenes_expanded": scenes_expanded,
        "scenes_skipped": scenes_skipped,
        "total_concepts": total_concepts,
        "style_distribution": style_counts,
        "new_status": next_status,
    }


def _load_or_generate_story_bible(pipeline, scripts: list) -> dict | None:
    """Load existing Story Bible from Airtable or generate a new one."""
    story_bible = None

    # Check if Story Bible already exists in Airtable
    existing_bible_json = (pipeline.current_idea.get(IdeaFields.STORY_BIBLE) or "").strip()
    if existing_bible_json:
        try:
            from script.story_bible import has_scene_blocks

            story_bible = json.loads(existing_bible_json)
            char_count = len(story_bible.get("characters", []))
            loc_count = len(story_bible.get("locations", []))

            if has_scene_blocks(story_bible):
                block_count = len(story_bible.get("scene_blocks", []))
                total_block_images = sum(
                    len(b.get("images", []))
                    for b in story_bible.get("scene_blocks", [])
                )
                print(f"  📖 Loaded existing Story Bible V2: {char_count} characters, "
                      f"{loc_count} locations, {block_count} blocks ({total_block_images} images)")
                pipeline.slack.notify(
                    f"📖 Using existing Story Bible V2 for *{pipeline.video_title}*:\n"
                    f"• {char_count} characters, {loc_count} locations\n"
                    f"• {block_count} scene blocks ({total_block_images} images)"
                )
            else:
                arc_count = len(story_bible.get("visual_arc", []))
                print(f"  📖 Loaded existing Story Bible V1: {char_count} characters, "
                      f"{loc_count} locations, {arc_count} arcs")
                pipeline.slack.notify(
                    f"📖 Using existing Story Bible for *{pipeline.video_title}*:\n"
                    f"• {char_count} characters, {loc_count} locations"
                )
        except json.JSONDecodeError:
            print(f"  ⚠️ Could not parse existing Story Bible, regenerating...")
            story_bible = None

    # Generate new Story Bible if not found (async not available in sync helper,
    # so this must be called via await in the caller — but since generate_story_bible
    # is async, we return None here and the caller handles generation)
    if not story_bible:
        # Return None — caller will need to generate asynchronously
        return None

    return story_bible


async def _generate_story_bible(pipeline, scripts: list) -> dict | None:
    """Generate a new Story Bible asynchronously."""
    print(f"  📖 Generating Story Bible for visual consistency...")
    try:
        from script.story_bible import generate_story_bible, has_scene_blocks
        from orchestrator.pipeline_config import VideoConfig

        video_length = pipeline.current_idea.get(IdeaFields.VIDEO_LENGTH_MIN, 10)
        try:
            video_config = VideoConfig(int(video_length), 10)
            total_images = video_config.total_clips
        except (ValueError, TypeError):
            total_images = 60

        full_script_text = "\n\n".join(
            f"[SCENE {s.get('scene', 0)}]\n{s.get(ScriptFields.SCENE_TEXT, '') or s.get(IdeaFields.SCRIPT, '')}"
            for s in scripts
        )

        story_bible = await generate_story_bible(
            anthropic_client=pipeline.anthropic,
            full_script_text=full_script_text,
            video_title=pipeline.video_title,
            use_scene_blocks=True,
            total_images=total_images,
            video_duration_minutes=int(video_length),
        )

        if story_bible:
            pipeline.airtable.update_idea_fields(
                pipeline.current_idea_id,
                {IdeaFields.STORY_BIBLE: json.dumps(story_bible, ensure_ascii=False)}
            )
            print(f"  📖 Story Bible saved to Airtable")

            char_count = len(story_bible.get("characters", []))
            loc_count = len(story_bible.get("locations", []))

            if has_scene_blocks(story_bible):
                block_count = len(story_bible.get("scene_blocks", []))
                total_block_images = sum(
                    len(b.get("images", []))
                    for b in story_bible.get("scene_blocks", [])
                )
                pipeline.slack.notify(
                    f"📖 Story Bible V2 generated for *{pipeline.video_title}*:\n"
                    f"• {char_count} characters\n"
                    f"• {loc_count} locations\n"
                    f"• {block_count} scene blocks ({total_block_images} images)"
                )
            else:
                arc_count = len(story_bible.get("visual_arc", []))
                pipeline.slack.notify(
                    f"📖 Story Bible generated for *{pipeline.video_title}*:\n"
                    f"• {char_count} characters\n"
                    f"• {loc_count} locations\n"
                    f"• {arc_count} scene arcs"
                )

        return story_bible
    except Exception as e:
        print(f"  ⚠️ Story Bible generation failed (non-blocking): {e}")
        return {}


async def _regenerate_visual_descriptions(
    pipeline, needs_regen: list, story_bible: dict | None, scene_num: int
):
    """Regenerate visual descriptions for duration-adjusted concepts."""
    try:
        from shared.profiles.visual import load_profile as _load_vp
        _regen_profile = _load_vp()
    except Exception:
        _regen_profile = None
    _regen_is_holographic = (
        _regen_profile is None
        or _regen_profile.profile_id == "holographic_hud"
    )

    # Format Story Bible context for regen
    _regen_bible_context = ""
    if story_bible and not _regen_is_holographic:
        try:
            from script.story_bible import format_bible_for_prompt
            _regen_bible_context = format_bible_for_prompt(story_bible, scene_num)
        except ImportError:
            pass

    for concept in needs_regen:
        try:
            if not _regen_is_holographic and _regen_profile and _regen_profile.scene_description.system_prompt:
                regen_prompt = f"{_regen_profile.scene_description.system_prompt}\n\n"

                if _regen_bible_context:
                    regen_prompt += (
                        f"{_regen_bible_context}\n\n"
                        "CRITICAL: If any character or location from the bible appears in this "
                        "narration, use their EXACT description from the bible above.\n\n"
                    )

                regen_prompt += (
                    "CHARACTER RULE: Every character must have specific clothing and appearance described. "
                    "Use period-appropriate, role-appropriate attire from the Story Bible.\n\n"
                    "Write a 20-35 word visual description for this narration segment. "
                    "You decide whether this moment needs characters, environment, data, or objects.\n\n"
                    "Do NOT start with the style prefix — that will be added automatically based on what you write.\n"
                    "Return ONLY the description, nothing else.\n\n"
                    f"Narration: \"{concept['sentence_text']}\""
                )
            else:
                regen_prompt = (
                    "You are creating visual descriptions for HOLOGRAPHIC DATA DISPLAYS "
                    "in an intelligence operations center — not camera shots of real events.\n\n"
                    "NEVER describe:\n"
                    "- People (no politicians, officials, reporters, soldiers, analysts, or any human figures)\n"
                    "- Physical rooms or buildings as if a camera is there\n"
                    "- Events as if photographing them\n\n"
                    "ALWAYS describe:\n"
                    "- What DATA, DOCUMENTS, MAPS, or CHARTS would appear on a holographic screen analyzing this topic\n"
                    "- Information visualizations (price charts, treaty text, flow diagrams, network maps, timelines)\n"
                    "- At least one specific number, date, or percentage from the narration\n"
                    "- Data elements must come from THIS segment's text only, not from the broader script context\n\n"
                    "EXAMPLES:\n"
                    "BAD: 'Kremlin hall, Putin and Pezeshkian at long table with treaty document'\n"
                    "GOOD: 'Holographic treaty document floating in space, 47 articles visible with Section 12: Military Cooperation highlighted'\n\n"
                    "BAD: 'White House briefing room, reporters holding phones'\n"
                    "GOOD: 'Bloomberg terminal display showing headline with oil price ticker dropping from $120 to $68'\n\n"
                    "The subject is ALWAYS information/data being displayed, never the physical event itself.\n\n"
                    "Write a 20-35 word description of what DATA DISPLAY would visualize this narration. "
                    "Return ONLY the description, nothing else.\n\n"
                    f"Narration: \"{concept['sentence_text']}\""
                )
            new_desc = await pipeline.anthropic.generate(
                prompt=regen_prompt,
                model=Models.CLAUDE_SONNET,
                max_tokens=200,
                temperature=0.4,
            )
            concept["visual_description"] = new_desc.strip()
        except Exception as e:
            print(f"      ⚠️ Regen failed for concept "
                  f"{concept['concept_index']}: {e}")
        concept.pop("needs_new_prompt", None)
