#!/usr/bin/env python3
"""Download images from Airtable and upload to Google Drive.

Reads all image records for a video, downloads each attachment,
and uploads to the matching Google Drive folder with Scene_XX_YY.png naming.

Handles expired Airtable URLs by checking if the image already exists in Drive.
Also updates the Airtable record with the permanent Drive URL.

Usage:
    python3 upload_images_to_drive.py "Video Title"
"""
import os
import sys
from pathlib import Path

# Load env from VPS path first, then local .env as fallback
from dotenv import load_dotenv
vps_env = Path("/home/clawd/projects/economy-fastforward/.env")
if vps_env.exists():
    load_dotenv(vps_env)
else:
    load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Setup imports
PIPELINE_DIR = Path(__file__).parent
sys.path.insert(0, str(PIPELINE_DIR))

import httpx
from clients.airtable_client import AirtableClient
from clients.google_client import GoogleClient


def _get_video_title() -> str:
    """Get video title from CLI args — no hardcoded default."""
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:])
    print("Usage: python3 upload_images_to_drive.py \"Video Title\"")
    sys.exit(1)


VIDEO_TITLE = _get_video_title()


def main():
    print(f"📸 Upload Images to Drive: {VIDEO_TITLE}")
    print("=" * 60)

    # Init clients
    airtable = AirtableClient()
    google = GoogleClient()

    # Step 1: Get all image records
    print("  Step 1: Loading image records from Airtable...")
    images = airtable.get_all_images_for_video(VIDEO_TITLE)
    if not images:
        print("❌ No image records found")
        sys.exit(1)

    done_images = [img for img in images if img.get("Status") == "Done"]
    print(f"  Found {len(images)} image records ({len(done_images)} with status Done)")

    # Step 2: Get or create Drive folder
    print("  Step 2: Finding Google Drive folder...")

    # Try to get folder ID from the idea record first
    idea = airtable.find_idea_by_title(VIDEO_TITLE)
    folder_id = None
    if idea:
        folder_id = idea.get("Google Drive Folder ID") or idea.get("Drive Folder ID")

    if folder_id:
        print(f"  Folder ID from Airtable: {folder_id}")
    else:
        folder = google.get_or_create_folder(VIDEO_TITLE)
        folder_id = folder["id"]
        print(f"  Folder: {folder['name']} ({folder_id})")

    # Step 3: Check what's already in Drive
    print("  Step 3: Checking existing files in Drive...")
    existing_files = google.list_files_in_folder(folder_id)
    existing_names = {f["name"] for f in existing_files}
    print(f"  Found {len(existing_names)} existing files in Drive folder")

    # Step 4: Download from Airtable + upload to Drive
    print(f"  Step 4: Uploading images...")
    uploaded = 0
    skipped = 0
    already_in_drive = 0
    errors = 0

    for img in done_images:
        scene = img.get("Scene", 0)
        img_index = img.get("Image Index", 0)
        record_id = img.get("id")
        filename = f"Scene_{int(scene):02d}_{int(img_index):02d}.png"

        # Skip if already in Drive
        if filename in existing_names:
            already_in_drive += 1
            continue

        # Try multiple URL sources (most reliable first)
        url = None

        # Source 1: Airtable Image attachment (may be expired)
        attachments = img.get("Image", [])
        if attachments and isinstance(attachments, list):
            url = attachments[0].get("url", "")

        if not url:
            print(f"    {filename}: ⚠️ no image URL, skipping")
            skipped += 1
            continue

        # Download image
        try:
            resp = httpx.get(url, timeout=60.0, follow_redirects=True)
            resp.raise_for_status()
            content = resp.content
        except Exception as e:
            print(f"    {filename}: ❌ download failed ({e})")
            errors += 1
            continue

        # Upload to Drive
        try:
            result = google.upload_file(
                content=content,
                name=filename,
                folder_id=folder_id,
                mime_type="image/png",
                check_existing=True,
            )
            drive_url = google.make_file_public(result["id"])

            # Update Airtable with permanent Drive URL
            try:
                airtable.update_image_record(record_id, url, drive_url=drive_url)
            except Exception:
                pass  # Non-critical — image is in Drive regardless

            uploaded += 1
            print(f"    {filename}: ✅ uploaded ({result['id']})")
        except Exception as e:
            print(f"    {filename}: ❌ upload failed ({e})")
            errors += 1

    print()
    print(f"  ✅ Uploaded: {uploaded}")
    if already_in_drive:
        print(f"  📂 Already in Drive: {already_in_drive}")
    if skipped:
        print(f"  ⚠️ Skipped (no URL): {skipped}")
    if errors:
        print(f"  ❌ Errors: {errors}")
    print(f"  📂 Drive folder: https://drive.google.com/drive/folders/{folder_id}")


if __name__ == "__main__":
    main()
