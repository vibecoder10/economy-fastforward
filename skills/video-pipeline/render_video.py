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
from clients.google_client import GoogleClient

def sanitize_filename(title: str) -> str:
    """Convert title to safe filename."""
    clean = re.sub(r'[^\w\s-]', '', title)
    clean = re.sub(r'[-\s]+', '_', clean)
    return clean[:50]

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
    
    # Get/create folder
    folder = google.get_or_create_folder(title)
    folder_id = folder["id"]
    print(f"📂 Drive folder: {folder_id}")
    
    # Export Remotion props
    print("\n📦 Exporting Remotion props...")
    scripts = airtable.get_scripts_by_title(title)
    images = airtable.get_all_images_for_video(title)
    
    scenes = []
    for script in scripts:
        scene_number = script.get("scene", 0)
        scene_images = [img for img in images if img.get("Scene") == scene_number]
        
        scenes.append({
            "sceneNumber": scene_number,
            "text": script.get("Scene text", ""),
            "voiceUrl": script.get("Voice Over", [{}])[0].get("url", "") if script.get("Voice Over") else "",
            "images": [
                {
                    "index": img.get("Image Index", 0),
                    "url": img.get("Image", [{}])[0].get("url", "") if img.get("Image") else "",
                }
                for img in sorted(scene_images, key=lambda x: x.get("Image Index", 0))
            ],
        })
    
    props = {
        "videoTitle": title,
        "folderId": folder_id,
        "scenes": scenes,
    }
    
    # Save props
    remotion_dir = Path(__file__).parent.parent.parent / "remotion-video"
    props_file = remotion_dir / "props.json"
    with open(props_file, "w") as f:
        json.dump(props, f, indent=2)
    print(f"   Saved to: {props_file}")
    
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
        "--concurrency=1",
        "--gl=swangle",
        "--timeout=180000",
        "--offthreadvideo-cache-size-in-bytes=536870912",
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
