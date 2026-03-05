#!/usr/bin/env python3
"""
Render a completed video using Remotion and upload to Google Drive.

Usage: python render_video.py "Video Title"
"""

import os
import sys
import json
import subprocess
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from clients.airtable_client import AirtableClient
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
    sfx_status = script.get("SFX Status", "")
    if sfx_status != "Done":
        return []

    sound_map_raw = script.get("Sound Map", "")
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python render_video.py \"Video Title\"")
        print("\nVideos at Done status:")
        airtable = AirtableClient()
        ideas = airtable.get_all_ideas()
        for idea in ideas:
            if idea.get("Status") == "Done":
                print(f"  • {idea.get('Video Title')}")
        return
    
    title = " ".join(sys.argv[1:])
    print(f"\n🎬 RENDERING: {title}")
    print("=" * 60)
    
    # Init clients
    airtable = AirtableClient()
    google = GoogleClient()
    
    # Find the video
    ideas = airtable.get_all_ideas()
    idea = None
    for i in ideas:
        if i.get("Video Title") == title:
            idea = i
            break
    
    if not idea:
        print(f"❌ Video not found: {title}")
        return
    
    if idea.get("Status") != "Done":
        print(f"⚠️ Video status is '{idea.get('Status')}', expected 'Done'")
        print("   Proceeding anyway...")
    
    # Use existing folder from Airtable (where images/voice/SFX were uploaded)
    folder_id = idea.get("Google Drive Folder ID") or idea.get("Drive Folder ID")
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
        scene_images = [img for img in images if img.get("Scene") == scene_number]

        # Build sound_layers from Sound Map JSON (if available)
        sound_layers = _build_sound_layers(script, scene_number, sfx_dir, google)

        # Build per-image data including SFX
        image_props = []
        for img in sorted(scene_images, key=lambda x: x.get("Image Index", 0)):
            img_index = img.get("Image Index", 0)
            img_data: dict = {
                "index": img_index,
                "url": img.get("Image", [{}])[0].get("url", "") if img.get("Image") else "",
            }

            # Extract per-image sound effect from Airtable
            sound_attachment = img.get("Sound Effect")
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
                    img_data["sfxVolume"] = img.get("Sound Volume", 0.15)

            image_props.append(img_data)

        scenes.append({
            "sceneNumber": scene_number,
            "text": script.get("Scene text", ""),
            "voiceUrl": script.get("Voice Over", [{}])[0].get("url", "") if script.get("Voice Over") else "",
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
        props["renderConfig"] = rc_data
        rc_scene_count = len(rc_data.get("scenes", []))
        rc_total = rc_data.get("total_duration_seconds", 0)
        print(f"   renderConfig embedded: {rc_scene_count} images, {rc_total:.1f}s total")
    else:
        print(f"   Warning: render_config.json not found")
        print(f"     Checked: {audio_sync_config}")
        print(f"     Checked: {rc_path}")
        print(f"   Rendering will use fallback timing (no Whisper alignment)")

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
    airtable.update_idea_field(idea["id"], "Final Video", drive_url)
    print(f"✅ Airtable updated with video link")
    
    print("\n" + "=" * 60)
    print(f"🎉 COMPLETE: {title}")
    print(f"   Drive: {drive_url}")
    print("=" * 60)

if __name__ == "__main__":
    main()
