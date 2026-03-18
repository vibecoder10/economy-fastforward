#!/usr/bin/env python3
"""
Render a completed video using Remotion and upload to Google Drive.

Usage: python render_video.py "Video Title" [--dry-run]

Flags:
    --dry-run   Generate render_config.json and log asset manifest without
                downloading assets or calling Remotion.
"""

from __future__ import annotations

import os
import sys
import json
import subprocess
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from clients.airtable_client import AirtableClient
from pipeline_constants import IdeaFields, ImageFields, ScriptFields, Statuses, Models
from clients.google_client import GoogleClient, get_direct_drive_url

def sanitize_filename(title: str) -> str:
    """Convert title to safe filename."""
    clean = re.sub(r'[^\w\s-]', '', title)
    clean = re.sub(r'[-\s]+', '_', clean)
    return clean[:50]

def _extract_drive_file_id(url: str) -> str | None:
    """Extract Google Drive file ID from various URL formats."""
    if not url:
        return None
    try:
        if "/file/d/" in url:
            return url.split("/file/d/")[1].split("/")[0]
        if "id=" in url:
            return url.split("id=")[1].split("&")[0]
        if "/open?id=" in url:
            return url.split("/open?id=")[1].split("&")[0]
    except (IndexError, AttributeError):
        pass
    return None


def _validate_mp4(path: Path) -> bool:
    """Check that a file is a non-zero valid mp4 using ffprobe."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0",
             str(path)],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0 and "video" in result.stdout
    except Exception:
        return False


def _download_video_clip(
    google: GoogleClient,
    file_id: str,
    local_path: Path,
    label: str,
) -> bool:
    """Download a single video clip with 3 retries + exponential backoff.

    Returns True on success (file downloaded and validated), False otherwise.
    """
    for attempt in range(3):
        try:
            google.download_file_to_local(file_id, str(local_path))
            if _validate_mp4(local_path):
                return True
            print(f"  Warning: {label} failed validation (attempt {attempt + 1})")
            if local_path.exists():
                local_path.unlink()
        except Exception as e:
            print(f"  Warning: {label} download failed (attempt {attempt + 1}): {e}")
        if attempt < 2:
            time.sleep(2 ** (attempt + 1))  # 2s, 4s
    return False


def _get_mp4_duration(path: Path) -> float | None:
    """Get video duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


def _build_sound_layers(
    script: dict,
    scene_number: int,
    sfx_dir: Path,
    google: GoogleClient,
) -> list[dict]:
    """Build sound_layers array from a script's Sound Map JSON.

    Downloads SFX files from Google Drive to the local sfx directory.
    Returns an empty list if no sound map or SFX status is not Done.
    """
    sfx_status = script.get(ScriptFields.SFX_STATUS, "")
    if sfx_status != ImageFields.STATUS_DONE:
        return []

    sound_map_raw = script.get(ScriptFields.SOUND_MAP, "")
    if not sound_map_raw:
        return []

    try:
        sound_map = json.loads(sound_map_raw)
    except (json.JSONDecodeError, TypeError):
        print(f"  Scene {scene_number}: Invalid Sound Map JSON, skipping")
        return []

    sounds = sound_map.get("sounds", [])
    if not sounds:
        return []

    layers = []
    for sound in sounds:
        file_url = sound.get("file_url", "")
        filename = sound.get("filename", "")
        if not file_url or not filename:
            continue

        # Download SFX file to local sfx dir (skip if already exists)
        local_path = sfx_dir / filename
        if not local_path.exists():
            file_id = _extract_drive_file_id(file_url)
            if file_id:
                try:
                    google.download_file_to_local(file_id, str(local_path))
                    print(f"  Downloaded: {filename}")
                except Exception as e:
                    print(f"  Warning: Failed to download {filename}: {e}")
                    continue
            else:
                print(f"  Warning: Cannot extract file ID from {file_url[:60]}")
                continue

        # Map segments array to start/end segment
        segments = sound.get("segments", [])
        if not segments:
            continue

        layers.append({
            "file": f"sfx/{filename}",
            "start_segment": min(segments),
            "end_segment": max(segments),
            "volume": sound.get("volume", 0.1),
            "loop": sound.get("loop", False),
            "fade_in": sound.get("fade_in", 0.5),
            "fade_out": sound.get("fade_out", 0.5),
        })

    if layers:
        print(f"  Scene {scene_number}: {len(layers)} sound layers loaded")

    return layers


async def _select_and_download_music(
    title: str,
    scripts: list[dict],
    music_dir: Path,
    google: GoogleClient,
    dry_run: bool = False,
) -> list[dict]:
    """Select music for each act and download tracks.

    Args:
        title: Video title
        scripts: List of script records from Airtable
        music_dir: Local directory to download tracks to
        google: GoogleClient instance
        dry_run: If True, skip downloads

    Returns:
        music_beds array for render_config.json
    """
    from bots.music_selector import select_music_for_script
    from brief_translator.script_generator import extract_acts
    from clients.anthropic_client import AnthropicClient

    # Reassemble full script from Airtable records
    full_script = ""
    for script in sorted(scripts, key=lambda s: s.get("scene", 0)):
        scene_text = script.get("Scene text", "")
        scene_num = script.get("scene", 0)
        full_script += f"\n\n[ACT {scene_num}]\n{scene_text}"

    # Extract acts from script
    acts = extract_acts(full_script)
    if not acts:
        print("  Warning: Could not extract acts from script, skipping music")
        return []

    print(f"  Extracted {len(acts)} acts from script")

    # Select music for each act
    anthropic = AnthropicClient()
    music_beds = await select_music_for_script(anthropic, acts)

    if not music_beds:
        print("  Warning: No music selected, skipping")
        return []

    print(f"  Selected {len(music_beds)} music tracks")

    # Download tracks (skip if already exist)
    for bed in music_beds:
        if not bed.get("file"):
            continue
        local_path = music_dir / Path(bed["file"]).name

        if local_path.exists():
            print(f"  Music cached: {local_path.name}")
            continue

        if dry_run:
            print(f"  [DRY RUN] Would download: {bed['file']}")
            continue

        try:
            google.download_file_to_local(bed["file_id"], str(local_path))
            print(f"  Downloaded: {local_path.name}")
        except Exception as e:
            print(f"  Warning: Failed to download {bed['file']}: {e}")

    # Remove file_id from output (not needed in render_config)
    return [
        {
            "act": b["act"],
            "file": b["file"],
            "mood": b["mood"],
            "volume": b["volume"],
        }
        for b in music_beds
        if b.get("file")
    ]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv

    if not args:
        print("Usage: python render_video.py \"Video Title\" [--dry-run]")
        print("\nVideos at Done status:")
        airtable = AirtableClient()
        ideas = airtable.get_all_ideas()
        for idea in ideas:
            if idea.get("Status") == Statuses.DONE:
                print(f"  • {idea.get(IdeaFields.VIDEO_TITLE)}")
        return

    title = " ".join(args)
    if dry_run:
        print("\n[DRY RUN] — will generate config and log manifest only")
    print(f"\n🎬 RENDERING: {title}")
    print("=" * 60)
    
    # Init clients
    airtable = AirtableClient()
    google = GoogleClient()
    
    # Find the video
    ideas = airtable.get_all_ideas()
    idea = None
    for i in ideas:
        if i.get(IdeaFields.VIDEO_TITLE) == title:
            idea = i
            break
    
    if not idea:
        print(f"❌ Video not found: {title}")
        return
    
    if idea.get("Status") != Statuses.DONE:
        print(f"⚠️ Video status is '{idea.get('Status')}', expected 'Done'")
        print("   Proceeding anyway...")
    
    # Use existing folder from Airtable (where images/voice/SFX were uploaded)
    folder_id = idea.get(IdeaFields.GOOGLE_DRIVE_FOLDER_ID) or idea.get(IdeaFields.DRIVE_FOLDER_ID)
    if not folder_id:
        # Fallback: search for existing folder, never create a new one
        folder = google.search_folder(title)
        if folder:
            folder_id = folder["id"]
        else:
            print(f"❌ No Google Drive folder found for this video.")
            print(f"   Check 'Google Drive Folder ID' field in Airtable.")
            return
    print(f"📂 Drive folder: {folder_id}")
    
    # Export Remotion props
    print("\n📦 Exporting Remotion props...")
    scripts = airtable.get_scripts_by_title(title)
    images = airtable.get_all_images_for_video(title)
    
    # Ensure SFX directory exists for sound layer downloads
    remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"
    sfx_dir = remotion_dir / "public" / "sfx"
    sfx_dir.mkdir(parents=True, exist_ok=True)

    # Ensure music directory exists
    music_dir = remotion_dir / "public" / "music"
    music_dir.mkdir(parents=True, exist_ok=True)

    # Pre-load all files in the Drive folder (paginated) so we can look up
    # SFX files by name without per-file API calls.  The folder can have 200+
    # items so we need the full paginated listing.
    print("  Loading Drive folder contents...")
    drive_files_list = google.list_files_in_folder(folder_id)
    drive_file_map: dict[str, str] = {}  # filename -> file_id
    for df in drive_files_list:
        drive_file_map[df["name"]] = df["id"]
    sfx_in_drive = {k: v for k, v in drive_file_map.items() if k.startswith("sfx_")}
    print(f"  Drive folder: {len(drive_files_list)} files total, {len(sfx_in_drive)} SFX files")

    scenes = []
    for script in scripts:
        scene_number = script.get("scene", 0)
        scene_images = [img for img in images if img.get(ImageFields.SCENE) == scene_number]

        # Build sound_layers from Sound Map JSON (if available)
        sound_layers = _build_sound_layers(script, scene_number, sfx_dir, google)

        # Build per-image data including SFX
        image_props = []
        for img in sorted(scene_images, key=lambda x: x.get(ImageFields.IMAGE_INDEX, 0)):
            img_index = img.get(ImageFields.IMAGE_INDEX, 0)
            img_data: dict = {
                "index": img_index,
                "url": img.get("Image", [{}])[0].get("url", "") if img.get("Image") else "",
            }

            # Extract per-image sound effect from Airtable
            sound_attachment = img.get(ImageFields.SOUND_EFFECT)
            if sound_attachment and isinstance(sound_attachment, list) and len(sound_attachment) > 0:
                sfx_filename = f"sfx_{scene_number}_{img_index}.mp3"
                local_sfx = sfx_dir / sfx_filename

                if not local_sfx.exists():
                    downloaded = False

                    # Strategy 1: Use pre-loaded Drive file map (no extra API calls)
                    if sfx_filename in drive_file_map:
                        try:
                            google.download_file_to_local(drive_file_map[sfx_filename], str(local_sfx))
                            print(f"  Downloaded SFX: {sfx_filename}")
                            downloaded = True
                        except Exception as e:
                            print(f"  Warning: Drive download failed for {sfx_filename}: {e}")

                    # Strategy 2: Direct Drive API search (in case filename differs)
                    if not downloaded:
                        try:
                            drive_result = google.search_file(sfx_filename, folder_id)
                            if drive_result:
                                google.download_file_to_local(drive_result["id"], str(local_sfx))
                                print(f"  Downloaded SFX (search): {sfx_filename}")
                                downloaded = True
                        except Exception as e:
                            print(f"  Warning: Drive search failed for {sfx_filename}: {e}")

                    # Strategy 3: Extract Drive file ID from Airtable attachment URL
                    if not downloaded:
                        sound_url = sound_attachment[0].get("url", "")
                        file_id = _extract_drive_file_id(sound_url)
                        if file_id:
                            try:
                                google.download_file_to_local(file_id, str(local_sfx))
                                print(f"  Downloaded SFX (ID): {sfx_filename}")
                                downloaded = True
                            except Exception as e:
                                print(f"  Warning: Drive ID download failed for {sfx_filename}: {e}")

                    # Strategy 4: Direct HTTP from Airtable CDN (may expire after 2h)
                    if not downloaded:
                        sound_url = sound_attachment[0].get("url", "")
                        if sound_url:
                            try:
                                import httpx
                                resp = httpx.get(sound_url, follow_redirects=True, timeout=30)
                                resp.raise_for_status()
                                local_sfx.write_bytes(resp.content)
                                print(f"  Downloaded SFX (CDN): {sfx_filename}")
                                downloaded = True
                            except Exception as e:
                                print(f"  Warning: CDN download failed for {sfx_filename}: {e}")

                    if not downloaded:
                        print(f"  ❌ Could not download {sfx_filename} via any method")

                if local_sfx.exists():
                    img_data["sfx"] = f"sfx/{sfx_filename}"
                    img_data["sfxVolume"] = img.get(ImageFields.SOUND_VOLUME, 0.15)

            image_props.append(img_data)

        scenes.append({
            "sceneNumber": scene_number,
            "text": script.get(ScriptFields.SCENE_TEXT, ""),
            "voiceUrl": script.get(ScriptFields.VOICE_OVER, [{}])[0].get("url", "") if script.get(ScriptFields.VOICE_OVER) else "",
            "images": image_props,
            "sound_layers": sound_layers,
        })
    
    props = {
        "videoTitle": title,
        "folderId": folder_id,
        "scenes": scenes,
    }

    # Embed renderConfig from audio_sync timing directory.
    # Without this, Remotion's renderConfig.ts returns null for all timing
    # functions and scenes fall back to even distribution.
    pipeline_dir = Path(__file__).parent
    video_id = idea.get("id", "unknown")
    audio_sync_config = pipeline_dir / "timing" / video_id / "render_config.json"
    public_dir = remotion_dir / "public"
    public_dir.mkdir(parents=True, exist_ok=True)

    # Check timing dir first, then fall back to public/ (may already be there)
    rc_path = public_dir / "render_config.json"
    if audio_sync_config.exists():
        import shutil
        shutil.copy2(audio_sync_config, rc_path)
        print(f"   renderConfig copied from timing/{video_id}/")
    elif rc_path.exists():
        print(f"   renderConfig found in public/ (using existing)")

    if rc_path.exists():
        rc_data = json.loads(rc_path.read_text())
        rc_scene_count = len(rc_data.get("scenes", []))
        rc_total = rc_data.get("total_duration_seconds", 0)
        print(f"   renderConfig loaded: {rc_scene_count} images, {rc_total:.1f}s total")
    else:
        rc_data = None
        print(f"   Warning: render_config.json not found")
        print(f"     Checked: {audio_sync_config}")
        print(f"     Checked: {rc_path}")
        print(f"   Rendering will use fallback timing (no Whisper alignment)")

    # ── Music selection and download ──────────────────────────────────
    print("\n🎵 Selecting background music...")
    import asyncio

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        music_beds = loop.run_until_complete(
            _select_and_download_music(
                title=title,
                scripts=scripts,
                music_dir=music_dir,
                google=google,
                dry_run=dry_run,
            )
        )
        loop.close()
    except Exception as e:
        print(f"  Warning: Music selection failed: {e}")
        music_beds = []

    # Add music_beds to render_config
    if music_beds and rc_data:
        rc_data["music_beds"] = music_beds
        print(f"  Added {len(music_beds)} music beds to render_config")

    # ── Video clip downloads ──────────────────────────────────────────
    # For each image record with a completed video clip, download the mp4
    # and patch the render_config entry to type=video.
    clip_stats = {"mp4": 0, "image": 0, "atempo": 0, "atempo_ratios": []}
    video_clip_dir = public_dir  # mp4s go alongside PNGs in public/

    # Build lookup: (scene_number, image_index) -> image record
    image_lookup: dict[tuple[int, int], dict] = {}
    for img in images:
        key = (img.get(ImageFields.SCENE, 0), img.get(ImageFields.IMAGE_INDEX, 0))
        image_lookup[key] = img

    # Collect clips to download
    clips_to_download: list[dict] = []
    for img in images:
        clip_url = img.get(ImageFields.VIDEO_CLIP_URL, "")
        anim_status = img.get(ImageFields.ANIMATION_STATUS, "")
        if clip_url and anim_status == ImageFields.STATUS_DONE:
            scene_num = img.get(ImageFields.SCENE, 0)
            img_idx = img.get(ImageFields.IMAGE_INDEX, 0)
            file_id = _extract_drive_file_id(clip_url)
            if file_id:
                mp4_name = f"Scene_{scene_num:02d}_{img_idx:02d}.mp4"
                clips_to_download.append({
                    "file_id": file_id,
                    "mp4_name": mp4_name,
                    "local_path": video_clip_dir / mp4_name,
                    "scene_number": scene_num,
                    "image_index": img_idx,
                    "video_duration": img.get(ImageFields.VIDEO_DURATION),
                    "label": f"Scene {scene_num} img {img_idx}",
                })

    if clips_to_download:
        print(f"\n   Downloading {len(clips_to_download)} video clips...")
        # Track which clips succeeded: (scene_number, image_index) -> local path
        successful_clips: dict[tuple[int, int], dict] = {}

        if dry_run:
            for clip in clips_to_download:
                key = (clip["scene_number"], clip["image_index"])
                successful_clips[key] = clip
                print(f"  [DRY RUN] Would download: {clip['mp4_name']}")
        else:
            # Concurrent downloads (up to 6 at a time to not overwhelm Drive)
            def _do_download(clip: dict) -> tuple[dict, bool]:
                ok = _download_video_clip(
                    google, clip["file_id"], clip["local_path"], clip["label"],
                )
                return clip, ok

            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = {pool.submit(_do_download, c): c for c in clips_to_download}
                for future in as_completed(futures):
                    clip, ok = future.result()
                    key = (clip["scene_number"], clip["image_index"])
                    if ok:
                        successful_clips[key] = clip
                        print(f"  Downloaded: {clip['mp4_name']}")
                    else:
                        print(f"  Falling back to PNG: {clip['label']}")

        # ── Patch render_config entries with video clip data ──────────
        if rc_data and successful_clips:
            for rc_entry in rc_data.get("scenes", []):
                sn = rc_entry.get("scene_number", 0)
                ii = rc_entry.get("image_index", 0)
                clip_info = successful_clips.get((sn, ii))
                if not clip_info:
                    clip_stats["image"] += 1
                    continue

                mp4_name = clip_info["mp4_name"]
                rc_entry["type"] = "video"
                rc_entry["video_clip_path"] = mp4_name

                # ── Voice duration matching ───────────────────────
                # If the video clip has a fixed duration, check against
                # the Whisper-calculated display_duration.
                clip_dur = clip_info.get("video_duration")
                if clip_dur and not dry_run:
                    # Also check actual mp4 duration via ffprobe
                    actual_dur = _get_mp4_duration(clip_info["local_path"])
                    if actual_dur:
                        clip_dur = actual_dur
                voice_dur = rc_entry.get("display_duration", 0)

                if clip_dur and voice_dur and voice_dur > clip_dur:
                    ratio = voice_dur / clip_dur
                    if ratio <= 1.25:
                        # Speed up is acceptable
                        clip_stats["atempo"] += 1
                        clip_stats["atempo_ratios"].append(ratio)
                        if ratio > 1.15:
                            print(f"  ⚠️ {mp4_name}: voice {voice_dur:.1f}s > clip {clip_dur:.1f}s (atempo={ratio:.2f}, flagged for review)")
                    else:
                        # Ratio too extreme — let voice overflow
                        print(f"  ⚠️ {mp4_name}: voice {voice_dur:.1f}s >> clip {clip_dur:.1f}s (ratio {ratio:.2f} > 1.25, voice will overflow)")
                        clip_stats["atempo_ratios"].append(ratio)
                        clip_stats["atempo"] += 1

                    # Use clip duration as display_duration for video entries
                    rc_entry["display_duration"] = round(clip_dur, 4)
                    rc_entry["display_end"] = round(
                        rc_entry.get("display_start", 0) + clip_dur, 4
                    )
                elif clip_dur:
                    # Voice fits within clip — use clip duration
                    rc_entry["display_duration"] = round(clip_dur, 4)
                    rc_entry["display_end"] = round(
                        rc_entry.get("display_start", 0) + clip_dur, 4
                    )

                clip_stats["mp4"] += 1

            # Recompute total duration after patching
            all_scenes = rc_data.get("scenes", [])
            if all_scenes:
                rc_data["total_duration_seconds"] = round(
                    max(s.get("display_end", 0) for s in all_scenes), 4
                )

            # Write updated render_config back to disk
            if not dry_run:
                with open(rc_path, "w") as f:
                    json.dump(rc_data, f, indent=2)
                print(f"   renderConfig updated with {clip_stats['mp4']} video clips")
        else:
            # No clips or no render_config — count all as image
            clip_stats["image"] = rc_scene_count if rc_data else 0
    else:
        clip_stats["image"] = len(rc_data.get("scenes", [])) if rc_data else 0
        print(f"\n   No video clips found in Airtable (all entries are static images)")

    # Embed (potentially updated) render_config into props
    if rc_data:
        props["renderConfig"] = rc_data

    # ── Video render summary ──────────────────────────────────────────
    avg_ratio = (
        sum(clip_stats["atempo_ratios"]) / len(clip_stats["atempo_ratios"])
        if clip_stats["atempo_ratios"] else 0
    )
    print(f"\n   Video render: {clip_stats['mp4']} clips as mp4, "
          f"{clip_stats['image']} clips as static image"
          + (f", {clip_stats['atempo']} voice segments adjusted "
             f"(avg ratio: {avg_ratio:.2f}x)" if clip_stats["atempo"] else ""))

    # Print sound layer diagnostics
    scenes_with_sl = sum(1 for s in scenes if s.get("sound_layers"))
    total_layers = sum(len(s.get("sound_layers", [])) for s in scenes)
    sfx_files = set()
    for s in scenes:
        for layer in s.get("sound_layers", []):
            sfx_files.add(layer.get("file", ""))
    print(f"\n   Sound design diagnostics:")
    print(f"     Scenes with sound_layers: {scenes_with_sl}/{len(scenes)}")
    print(f"     Total sound layer entries: {total_layers}")
    print(f"     Unique SFX files referenced: {len(sfx_files)}")

    # Verify SFX files exist on disk
    missing_sfx = []
    for f in sfx_files:
        sfx_path = remotion_dir / "public" / f
        if not sfx_path.exists():
            missing_sfx.append(f)
    if missing_sfx:
        print(f"     Missing SFX files: {len(missing_sfx)}")
        for f in missing_sfx[:5]:
            print(f"       - {f}")
        if len(missing_sfx) > 5:
            print(f"       ... and {len(missing_sfx) - 5} more")
    else:
        print(f"     All SFX files present on disk")

    # Per-image SFX diagnostics
    per_image_sfx_count = 0
    per_image_sfx_files = set()
    for s in scenes:
        for img in s.get("images", []):
            if img.get("sfx"):
                per_image_sfx_count += 1
                per_image_sfx_files.add(img["sfx"])
    total_images = sum(len(s.get("images", [])) for s in scenes)
    print(f"\n   Per-image SFX diagnostics:")
    print(f"     Images with SFX: {per_image_sfx_count}/{total_images}")
    print(f"     Unique per-image SFX files: {len(per_image_sfx_files)}")

    # Verify per-image SFX files exist on disk
    missing_per_image = []
    for f in per_image_sfx_files:
        if not (remotion_dir / "public" / f).exists():
            missing_per_image.append(f)
    if missing_per_image:
        print(f"     ⚠️ Missing per-image SFX: {len(missing_per_image)}")
        for f in missing_per_image[:5]:
            print(f"       - {f}")
    else:
        print(f"     All per-image SFX files present on disk")

    # Save props
    props_file = remotion_dir / "props.json"
    with open(props_file, "w") as f:
        json.dump(props, f, indent=2)
    print(f"   Saved to: {props_file}")

    if dry_run:
        print("\n[DRY RUN] Asset manifest and render_config.json generated.")
        print(f"   Props: {props_file}")
        if rc_path.exists():
            print(f"   Config: {rc_path}")
        print("   Skipping Remotion render and upload.")
        return

    # Ensure node_modules are installed
    if not (remotion_dir / "node_modules").exists():
        print("\n📦 Installing Remotion dependencies...")
        install = subprocess.run(["npm", "install"], cwd=remotion_dir, capture_output=False)
        if install.returncode != 0:
            print("❌ npm install failed")
            return

    # Render video
    print("\n🎥 Rendering video (this may take 30-60 minutes)...")
    safe_name = sanitize_filename(title)
    output_file = remotion_dir / "out" / f"{safe_name}.mp4"
    output_file.parent.mkdir(exist_ok=True)

    render_cmd = [
        "npx", "remotion", "render",
        "Main",
        str(output_file),
        "--props", str(props_file),
        "--concurrency=3",
        "--gl=swangle",
        "--timeout=180000",
        "--offthreadvideo-cache-size-in-bytes=1073741824",
    ]

    result = subprocess.run(render_cmd, cwd=remotion_dir, capture_output=False)
    
    if result.returncode != 0:
        print(f"❌ Render failed with code {result.returncode}")
        return
    
    if not output_file.exists():
        print(f"❌ Output file not found: {output_file}")
        return
    
    print(f"✅ Rendered: {output_file}")
    
    # Upload to Drive
    print("\n☁️ Uploading to Google Drive...")
    with open(output_file, "rb") as f:
        video_content = f.read()
    
    drive_file = google.upload_video(video_content, f"{safe_name}.mp4", folder_id)
    print(f"✅ Uploaded to Drive!")
    
    # Update Airtable with video link
    drive_url = f"https://drive.google.com/file/d/{drive_file['id']}/view"
    airtable.update_idea_field(idea["id"], IdeaFields.FINAL_VIDEO, drive_url)
    print(f"✅ Airtable updated with video link")
    
    print("\n" + "=" * 60)
    print(f"🎉 COMPLETE: {title}")
    print(f"   Drive: {drive_url}")
    print("=" * 60)

if __name__ == "__main__":
    main()
