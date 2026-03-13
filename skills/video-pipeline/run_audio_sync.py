#!/usr/bin/env python3
"""
Audio sync runner — downloads voice-over from Google Drive, transcribes with
Whisper, and writes render_config.json.

Usage:
    python3 run_audio_sync.py "Video Title"

Downloads Scene N.mp3 files from the video's Google Drive folder (permanent URLs),
transcribes with OpenAI Whisper API, and writes render_config.json.
"""
import asyncio
import json
import os
import re
import sys
import subprocess
from collections import defaultdict
from pathlib import Path

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Setup paths
PIPELINE_DIR = Path(__file__).parent
REMOTION_DIR = PIPELINE_DIR.parent.parent / "remotion-video"
PUBLIC_DIR = REMOTION_DIR / "public"

sys.path.insert(0, str(PIPELINE_DIR))

from pyairtable import Api
from pyairtable.formulas import match

from audio_sync.transcriber import transcribe
from audio_sync.transition_engine import assign_transitions
from audio_sync.ken_burns_calculator import assign_ken_burns
from audio_sync.render_config_writer import build_render_config, write_render_config
# Import GoogleClient directly to avoid importing the full clients package
# (which pulls in AnthropicClient with Python 3.10+ type syntax)
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "google_client",
    PIPELINE_DIR / "clients" / "google_client.py"
)
_google_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_google_module)
GoogleClient = _google_module.GoogleClient


def _get_video_title() -> str:
    """Get video title from CLI args or prompt interactively."""
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:])

    # No hardcoded default — force explicit selection to prevent
    # audio contamination between videos (the #1 recurring bug).
    print("Usage: python3 run_audio_sync.py \"Video Title\"")
    print("\nAvailable videos (from Airtable):")
    try:
        api = get_airtable_api()
        table = api.table(AIRTABLE_BASE_ID, AIRTABLE_IDEAS_TABLE_ID)
        records = table.all(sort=["Video Title"])
        for r in records:
            status = r["fields"].get("Status", "")
            title = r["fields"].get("Video Title", "")
            if title and status in ("Ready To Render", "Done", "Rendered"):
                print(f"  • [{status}] {title}")
    except Exception:
        pass
    sys.exit(1)


VIDEO_TITLE = _get_video_title()
DESKTOP_SRC = Path.home() / "Desktop" / VIDEO_TITLE

# Hardcoded Airtable IDs (must match clients/airtable_client.py)
AIRTABLE_BASE_ID = "appCIcC58YSTwK3CE"
AIRTABLE_IMAGES_TABLE_ID = "tbl3luJ0zsWu0MYYz"
AIRTABLE_IDEAS_TABLE_ID = "tblrAsJglokZSkC8m"
AIRTABLE_SCRIPTS_TABLE_ID = "tbluGSepeZNgb0NxG"


def get_airtable_api():
    """Get Airtable API instance."""
    api_key = os.environ.get("AIRTABLE_API_KEY") or os.environ.get("AIRTABLE_PAT")
    if not api_key:
        print("❌ Missing AIRTABLE_API_KEY or AIRTABLE_PAT in .env")
        sys.exit(1)
    return Api(api_key)


def get_images_from_airtable(title: str) -> list[dict]:
    """Pull all image records for this video from Airtable."""
    api = get_airtable_api()
    table = api.table(AIRTABLE_BASE_ID, AIRTABLE_IMAGES_TABLE_ID)
    records = table.all(
        formula=match({"Video Title": title}),
        sort=["Scene", "Image Index"],
    )
    return [{"id": r["id"], **r["fields"]} for r in records]


def get_idea_from_airtable(title: str) -> dict:
    """Find the Idea Concepts record for this video."""
    api = get_airtable_api()
    table = api.table(AIRTABLE_BASE_ID, AIRTABLE_IDEAS_TABLE_ID)
    records = table.all(formula=match({"Video Title": title}))
    if not records:
        print(f"❌ No idea found with title: {title}")
        sys.exit(1)
    r = records[0]
    return {"id": r["id"], **r["fields"]}


def download_audio_from_drive(folder_id: str) -> dict[int, Path]:
    """Download Scene N.mp3 voice-over files from Google Drive.

    Clears any existing Scene*.mp3 files first to prevent audio contamination
    between videos (the #1 recurring bug in this pipeline).

    Args:
        folder_id: Google Drive folder ID for this video

    Returns:
        Dict mapping scene number -> local file path
    """
    # Clear existing audio files to prevent contamination
    existing = list(PUBLIC_DIR.glob("Scene *.mp3"))
    if existing:
        print(f"  Clearing {len(existing)} old audio files...")
        for f in existing:
            f.unlink()

    # Initialize Google Drive client
    google = GoogleClient()

    # List files in the video's Drive folder
    print(f"  Listing files in Drive folder {folder_id}...")
    files = google.list_files_in_folder(folder_id)

    # Find Scene N.mp3 files
    audio_files: dict[int, Path] = {}
    scene_pattern = re.compile(r'^Scene (\d+)\.mp3$')

    mp3_files = [f for f in files if f['name'].endswith('.mp3') and 'Scene' in f['name']]
    print(f"  Found {len(mp3_files)} Scene*.mp3 files in Drive")

    for drive_file in sorted(mp3_files, key=lambda x: x['name']):
        name = drive_file['name']
        match = scene_pattern.match(name)
        if not match:
            continue

        scene_num = int(match.group(1))
        file_id = drive_file['id']
        output_path = PUBLIC_DIR / name

        try:
            google.download_file_to_local(file_id, str(output_path))
            size_kb = output_path.stat().st_size // 1024
            audio_files[scene_num] = output_path
            print(f"    Scene {scene_num}: ✅ {size_kb}KB")
        except Exception as e:
            print(f"    Scene {scene_num}: ❌ Download failed: {e}")

    return audio_files


def find_audio_files(idea: dict) -> dict[int, Path]:
    """Download audio from Google Drive, or fall back to local files.

    Priority:
    1. Download fresh from Google Drive (clears old files to prevent contamination)
    2. Fall back to Desktop source folder if Drive fails

    Args:
        idea: Idea record from Airtable (must have 'Google Drive Folder ID')
    """
    # Get the Google Drive folder ID
    folder_id = idea.get("Google Drive Folder ID") or idea.get("Drive Folder ID")

    if folder_id:
        print("  Downloading audio from Google Drive...")
        audio = download_audio_from_drive(folder_id)

        if audio:
            print(f"  Downloaded {len(audio)} audio files from Google Drive")
            return audio
        else:
            print("  ⚠️ No audio files found in Drive folder")

    # Fall back to Desktop source (local development only)
    audio: dict[int, Path] = {}
    if DESKTOP_SRC.exists():
        for mp3 in sorted(DESKTOP_SRC.glob("Scene *.mp3")):
            try:
                snum = int(mp3.name.replace("Scene ", "").replace(".mp3", "").strip())
                audio[snum] = mp3
            except ValueError:
                pass
        if audio:
            print(f"  Found {len(audio)} audio files in Desktop folder")
            return audio

    print("❌ No audio files found.")
    print(f"   Check 'Google Drive Folder ID' field in Airtable for: {VIDEO_TITLE}")
    sys.exit(1)


async def run():
    print(f"🎵 Audio Sync: {VIDEO_TITLE}")
    print("=" * 60)

    # Step 1: Load image records and idea from Airtable
    print("  Step 1/4: Loading image records from Airtable...")
    image_records = get_images_from_airtable(VIDEO_TITLE)
    if not image_records:
        print("❌ No image records found")
        sys.exit(1)

    idea = get_idea_from_airtable(VIDEO_TITLE)
    video_id = idea["id"]

    scenes_images: dict[int, list[dict]] = defaultdict(list)
    for img in image_records:
        scene_num = img.get("Scene")
        if scene_num is not None:
            scenes_images[scene_num].append(img)
    for sn in scenes_images:
        scenes_images[sn].sort(key=lambda x: x.get("Image Index", 0))

    scene_numbers = sorted(scenes_images.keys())
    total_images = sum(len(imgs) for imgs in scenes_images.values())
    print(f"  Found {total_images} images across {len(scene_numbers)} scenes")

    # Step 2: Download audio files from Google Drive
    print("  Step 2/4: Locating audio files...")
    scene_audio_paths = find_audio_files(idea)

    # Setup timing directory
    timing_dir = PIPELINE_DIR / "timing" / video_id
    timing_dir.mkdir(parents=True, exist_ok=True)

    # Step 3: Transcribe & match
    print("  Step 3/4: Transcribing scenes & matching sentences...")
    duration_updates = 0
    total_duration = 0.0
    image_durations: dict[tuple[int, int], float] = {}

    # Airtable table for writing durations
    api = get_airtable_api()
    images_table = api.table(AIRTABLE_BASE_ID, AIRTABLE_IMAGES_TABLE_ID)

    for scene_num in scene_numbers:
        images = scenes_images[scene_num]
        audio_file = scene_audio_paths.get(scene_num)

        if not audio_file or not audio_file.exists():
            print(f"    Scene {scene_num}: ⚠️ no audio, skipping")
            continue

        # Transcribe
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

        # Validate timestamps against actual duration
        whisper_dur = words[-1].end
        actual_dur = None
        try:
            probe = subprocess.run(
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

        if not actual_dur:
            try:
                result = subprocess.run(
                    ["afinfo", str(audio_file)],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.splitlines():
                    if "estimated duration" in line:
                        actual_dur = float(line.split(":")[1].strip().replace(" sec", ""))
                        break
            except Exception:
                pass

        if actual_dur and whisper_dur > 0:
            drift = abs(actual_dur - whisper_dur) / actual_dur
            if drift > 0.10:
                scale = actual_dur / whisper_dur
                print(f"    Scene {scene_num}: ⚠️ Whisper drift — "
                      f"audio={actual_dur:.2f}s, whisper={whisper_dur:.2f}s, "
                      f"scaling by {scale:.3f}")
                for w in words:
                    w.start *= scale
                    w.end *= scale

        scene_audio_dur = words[-1].end
        print(f"    Scene {scene_num}: {len(words)} words, {scene_audio_dur:.1f}s — {len(images)} images")

        # Write caption file
        captions_dir = REMOTION_DIR / "src" / "captions"
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
            with open(caption_path, "w") as f:
                json.dump(caption_data, f, indent=2)
        except Exception as e:
            print(f"    Scene {scene_num}: ⚠️ caption write failed ({e})")

        # Proportional word-count mapping
        img_entries = []
        total_sentence_words = 0
        for img_idx, img in enumerate(images):
            sentence = img.get("Sentence Text", "") or ""
            img_index = img.get("Image Index", img_idx + 1)
            if not sentence.strip():
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

        scene_raw = []
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

        # Enforce max duration per image — prevents one long sentence
        # from monopolising a scene (e.g. 47s, 60s instead of ~10s).
        from audio_sync.timing_adjuster import enforce_max_image_duration
        scene_raw = enforce_max_image_duration(scene_raw)

        for entry in scene_raw:
            record_id = entry["record_id"]
            img_index = entry["image_index"]
            dur = entry["duration"]
            sentence = entry["sentence_text"]
            wc = entry["word_count"]

            image_durations[(scene_num, img_index)] = dur

            try:
                images_table.update(record_id, {"Duration (s)": dur}, typecast=True)
                duration_updates += 1
            except Exception as e:
                print(f"      Image {img_index}: ⚠️ Airtable write failed ({e})")

            total_duration += dur
            scene_total += dur
            print(f"      Image {img_index}: {dur:.2f}s ({wc}w) — \"{sentence[:50]}...\"")

    # Step 4: Build render config
    print("  Step 4/4: Writing per-image render config...")

    running_time = 0.0
    timed_images = []
    for scene_num in scene_numbers:
        images = scenes_images[scene_num]
        for img_idx, img in enumerate(images):
            sentence = img.get("Sentence Text", "") or ""
            img_index = img.get("Image Index", img_idx + 1)
            dur = image_durations.get((scene_num, img_index), 0)
            if dur <= 0:
                continue
            dur = float(dur)
            composition = img.get("Shot Type", "") or "wide"

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

    # Concat audio
    concat_path = timing_dir / "narration_concat.mp3"
    sorted_audio = sorted(scene_audio_paths.items())
    list_file = timing_dir / "concat_list.txt"
    with open(list_file, "w") as f:
        for _, sa in sorted_audio:
            f.write(f"file '{sa}'\n")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(list_file), "-c", "copy", str(concat_path)],
            capture_output=True, check=True,
        )
    except Exception:
        concat_path = sorted_audio[0][1] if sorted_audio else Path("")

    image_dir = str(PUBLIC_DIR)
    config = build_render_config(
        video_id=video_id,
        audio_path=str(concat_path),
        scenes=timed_images,
        image_dir=image_dir,
    )

    # Write to timing/
    write_render_config(config, timing_dir / "render_config.json")

    # Write to remotion-video/public/
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    write_render_config(config, PUBLIC_DIR / "render_config.json")

    avg_dur = total_duration / max(duration_updates, 1)
    print(f"\n  ✅ {duration_updates} image durations written to Airtable")
    print(f"  Avg image duration: {avg_dur:.1f}s")
    print(f"  Total duration: {total_duration:.1f}s")
    print(f"  Render config: {timing_dir / 'render_config.json'}")
    print(f"  Remotion config: {PUBLIC_DIR / 'render_config.json'}")
    print(f"  Per-image entries: {len(timed_images)}")


if __name__ == "__main__":
    asyncio.run(run())
