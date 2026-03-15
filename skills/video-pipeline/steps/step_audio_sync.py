"""Audio sync step — matches sentence text to voiceover timing.

For each scene:
1. Download Scene N.mp3 from Google Drive
2. Transcribe with Whisper → word-level timestamps
3. Walk through each image's Sentence Text sequentially
4. Duration = how long it takes to say that sentence
5. Write duration to image's Airtable record immediately

Reads: Images table (Sentence Text), Scene audio from Drive
Writes: Duration (s) to Images table, render_config.json, caption JSONs
Clients: airtable, google
"""

import json
import subprocess as _sp
from collections import defaultdict
from pathlib import Path

from pipeline_constants import ImageFields

from audio_sync.transcriber import transcribe
from audio_sync.transition_engine import assign_transitions
from audio_sync.ken_burns_calculator import assign_ken_burns


async def run(pipeline, audio_path: str = None, scene_list: list = None) -> dict:
    """Calculate per-image durations by matching Sentence Text to audio."""
    if not pipeline.current_idea:
        return {"error": "No current idea loaded"}

    print(f"\n🎵 AUDIO SYNC: Processing '{pipeline.video_title}'")

    video_id = pipeline.current_idea_id or "unknown"
    pipeline_dir = Path(__file__).parent.parent
    timing_dir = pipeline_dir / "timing" / video_id
    timing_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = timing_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Load image records from Airtable ──
    print(f"  Step 1/4: Loading image records from Airtable...")
    image_records = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
    if not image_records:
        return {"error": "No image records found in Airtable", "bot": "Audio Sync"}

    scenes_images: dict[int, list[dict]] = defaultdict(list)
    for img in image_records:
        scene_num = img.get(ImageFields.SCENE)
        if scene_num is not None:
            scenes_images[scene_num].append(img)
    for sn in scenes_images:
        scenes_images[sn].sort(key=lambda x: x.get(ImageFields.IMAGE_INDEX, 0))

    scene_numbers = sorted(scenes_images.keys())
    total_images = sum(len(imgs) for imgs in scenes_images.values())
    print(f"  Found {total_images} images across {len(scene_numbers)} scenes")

    # ── Step 2: Download scene audio from Google Drive ──
    print(f"  Step 2/4: Downloading scene audio from Google Drive...")
    scene_audio_paths: dict[int, Path] = {}

    if pipeline.project_folder_id:
        try:
            drive_files = pipeline.google.list_files_in_folder(pipeline.project_folder_id)
            scene_mp3s = [
                f for f in drive_files
                if f["name"].startswith("Scene ") and f["name"].endswith(".mp3")
            ]
            for df in scene_mp3s:
                local_path = audio_dir / df["name"]
                if not local_path.exists():
                    content = pipeline.google.download_file(df["id"])
                    if len(content) < 500:
                        continue
                    local_path.write_bytes(content)
                try:
                    snum = int(df["name"].replace("Scene ", "").replace(".mp3", "").strip())
                    scene_audio_paths[snum] = local_path
                except ValueError:
                    pass
            print(f"  Downloaded {len(scene_audio_paths)} scene audio files")
        except Exception as e:
            print(f"  ⚠️ Drive download failed ({e}), trying local files...")

    if not scene_audio_paths:
        remotion_dir = pipeline_dir.parent.parent / "remotion-video"
        public_dir = remotion_dir / "public"
        for mp3 in sorted(public_dir.glob("Scene *.mp3")):
            try:
                snum = int(mp3.name.replace("Scene ", "").replace(".mp3", "").strip())
                scene_audio_paths[snum] = mp3
            except ValueError:
                pass
        if scene_audio_paths:
            print(f"  ⚠️ Using {len(scene_audio_paths)} audio files from public/")

    if not scene_audio_paths:
        return {"error": "No scene audio files found. Run voice bot first.", "bot": "Audio Sync"}

    # ── Step 3: Transcribe each scene & match sentence durations ──
    print(f"  Step 3/4: Transcribing scenes & matching sentences...")

    duration_updates = 0
    total_duration = 0.0
    scene_durations: dict[int, float] = {}
    image_durations: dict[tuple[int, int], float] = {}

    for scene_num in scene_numbers:
        images = scenes_images[scene_num]
        audio_file = scene_audio_paths.get(scene_num)

        if not audio_file or not audio_file.exists():
            print(f"    Scene {scene_num}: ⚠️ no audio, skipping")
            continue

        # Transcribe this scene's audio with Whisper
        cache_dir = timing_dir / f"scene_{scene_num}"
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            words = transcribe(str(audio_file), cache_dir=cache_dir)
        except Exception as e:
            print(f"    Scene {scene_num}: ⚠️ Whisper failed ({e}), skipping")
            continue

        if not words:
            print(f"    Scene {scene_num}: ⚠️ no words transcribed")
            continue

        # Validate Whisper timestamps against actual audio duration
        whisper_dur = words[-1].end
        actual_dur = None
        try:
            probe = _sp.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "format=duration", "-of",
                 "default=noprint_wrappers=1:nokey=1",
                 str(audio_file)],
                capture_output=True, text=True, timeout=10,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                actual_dur = float(probe.stdout.strip())
        except Exception:
            pass

        # Fallback to mutagen if ffprobe unavailable
        if actual_dur is None:
            try:
                from mutagen.mp3 import MP3
                actual_dur = MP3(str(audio_file)).info.length
            except Exception:
                pass

        if actual_dur and whisper_dur > 0:
            drift = abs(actual_dur - whisper_dur) / actual_dur
            if drift > 0.10:
                scale = actual_dur / whisper_dur
                print(f"    Scene {scene_num}: ⚠️ Whisper duration drift — "
                      f"audio={actual_dur:.2f}s, whisper={whisper_dur:.2f}s, "
                      f"scaling by {scale:.3f}")
                for w in words:
                    w.start *= scale
                    w.end *= scale

        scene_audio_dur = words[-1].end
        print(f"    Scene {scene_num}: {len(words)} words, {scene_audio_dur:.1f}s — {len(images)} images")

        # ── Write Remotion caption file ──
        captions_dir = Path(__file__).parent.parent.parent.parent / "remotion-video" / "src" / "captions"
        captions_dir.mkdir(parents=True, exist_ok=True)
        caption_path = captions_dir / f"Scene {scene_num}.json"
        caption_data = {
            "text": " ".join(w.word.strip() for w in words),
            "segments": [{
                "id": 0,
                "start": words[0].start,
                "end": words[-1].end,
                "text": " ".join(w.word.strip() for w in words),
                "words": [
                    {"word": w.word, "start": round(w.start, 4),
                     "end": round(w.end, 4), "probability": 1.0}
                    for w in words
                ],
            }],
            "language": "en",
        }
        try:
            with open(caption_path, "w") as _f:
                json.dump(caption_data, _f, indent=2)
            print(f"    Scene {scene_num}: wrote {len(words)} words to {caption_path.name}")
        except Exception as e:
            print(f"    Scene {scene_num}: ⚠️ caption write failed ({e})")

        # ── Proportional word-count mapping ──
        img_entries = []
        total_sentence_words = 0
        for img_idx, img in enumerate(images):
            sentence = img.get(ImageFields.SENTENCE_TEXT, "") or ""
            img_index = img.get(ImageFields.IMAGE_INDEX, img_idx + 1)
            if not sentence.strip():
                print(f"      Image {img_index}: (no sentence text, skipping)")
                continue
            wc = len(sentence.split())
            if wc == 0:
                continue
            img_entries.append((img, img_index, sentence, wc))
            total_sentence_words += wc

        if not img_entries:
            print(f"    Scene {scene_num}: no images with sentence text")
            continue

        total_whisper = len(words)
        scene_total = 0.0

        cumulative = 0
        start_indices = []
        for _img, _idx, _sent, wc in img_entries:
            frac = cumulative / total_sentence_words
            w_start = int(round(frac * total_whisper))
            w_start = max(0, min(w_start, total_whisper - 1))
            start_indices.append(w_start)
            cumulative += wc

        from audio_sync.timing_adjuster import enforce_max_image_duration

        scene_raw: list[dict] = []
        for entry_idx, (img, img_index, sentence, wc) in enumerate(img_entries):
            start_time = words[start_indices[entry_idx]].start

            if entry_idx < len(img_entries) - 1:
                end_time = words[start_indices[entry_idx + 1]].start
            else:
                end_time = words[-1].end

            dur = round(end_time - start_time, 2)
            dur = max(dur, 1.0)

            scene_raw.append({
                "record_id": img["id"],
                "image_index": img_index,
                "sentence_text": sentence,
                "duration": dur,
                "display_start": round(start_time, 4),
                "display_end": round(end_time, 4),
                "word_count": wc,
            })

        scene_raw = enforce_max_image_duration(scene_raw)

        for entry in scene_raw:
            record_id = entry["record_id"]
            img_index = entry["image_index"]
            dur = entry["duration"]
            sentence = entry["sentence_text"]
            wc = entry["word_count"]

            image_durations[(scene_num, img_index)] = dur

            try:
                pipeline.airtable.images_table.update(
                    record_id, {"Duration (s)": dur}, typecast=True,
                )
                duration_updates += 1
            except Exception as e:
                print(f"      Image {img_index}: ⚠️ Airtable write failed ({e})")

            total_duration += dur
            scene_total += dur
            print(f"      Image {img_index}: {dur:.2f}s ({wc}w) — \"{sentence[:50]}...\"")

        scene_durations[scene_num] = scene_total

    # ── Step 4: Build per-IMAGE render config ──
    print(f"  Step 4/4: Writing per-image render config...")

    from audio_sync.render_config_writer import build_render_config, write_render_config

    running_time = 0.0
    timed_images = []
    for scene_num in scene_numbers:
        images = scenes_images[scene_num]
        for img_idx, img in enumerate(images):
            sentence = img.get(ImageFields.SENTENCE_TEXT, "") or ""
            img_index = img.get(ImageFields.IMAGE_INDEX, img_idx + 1)

            dur = image_durations.get((scene_num, img_index), 0)
            if dur <= 0:
                continue
            dur = float(dur)

            composition = img.get(ImageFields.SHOT_TYPE, "") or "wide"

            timed_images.append({
                "scene_number": scene_num,
                "image_index": img_index,
                "sentence_text": sentence,
                "start_time": round(running_time, 4),
                "end_time": round(running_time + dur, 4),
                "duration": round(dur, 4),
                "display_start": round(running_time, 4),
                "display_end": round(running_time + dur, 4),
                "display_duration": round(dur, 4),
                "alignment_method": "sentence_match",
                "style": "",
                "composition": composition,
            })
            running_time += dur

    timed_images = assign_transitions(timed_images)
    timed_images = assign_ken_burns(timed_images)

    # Concat scene audio for the full-video audio path
    concat_path = timing_dir / "narration_concat.mp3"
    sorted_audio = sorted(scene_audio_paths.items())
    list_file = timing_dir / "concat_list.txt"
    with open(list_file, "w") as f:
        for _, sa in sorted_audio:
            f.write(f"file '{sa}'\n")
    try:
        _sp.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(list_file), "-c", "copy", str(concat_path)],
            capture_output=True, check=True,
        )
    except Exception:
        concat_path = sorted_audio[0][1] if sorted_audio else Path("")

    remotion_dir = Path(__file__).parent.parent.parent.parent / "remotion-video"
    image_dir = str(remotion_dir / "public")

    config = build_render_config(
        video_id=video_id,
        audio_path=str(concat_path),
        scenes=timed_images,
        image_dir=image_dir,
    )

    # Write to timing directory
    write_render_config(config, timing_dir / "render_config.json")

    # Also copy to remotion-video/public/ so Remotion can read it at render time
    remotion_public = remotion_dir / "public"
    remotion_public.mkdir(parents=True, exist_ok=True)
    write_render_config(config, remotion_public / "render_config.json")

    avg_dur = total_duration / max(duration_updates, 1)
    print(f"\n  ✅ {duration_updates} image durations written to Airtable")
    print(f"  Avg image duration: {avg_dur:.1f}s")
    print(f"  Total duration: {total_duration:.1f}s")
    print(f"  Render config: {timing_dir / 'render_config.json'}")
    print(f"  Remotion config: {remotion_public / 'render_config.json'}")
    print(f"  Per-image entries: {len(timed_images)}")

    return {
        "bot": "Audio Sync",
        "video_title": pipeline.video_title,
        "timing_dir": str(timing_dir),
        "render_config_path": str(timing_dir / "render_config.json"),
        "remotion_config_path": str(remotion_public / "render_config.json"),
        "total_duration": total_duration,
        "scene_count": len(scene_numbers),
        "image_count": duration_updates,
        "avg_duration": round(avg_dur, 2),
        "alignment_quality": "sentence_match",
    }
