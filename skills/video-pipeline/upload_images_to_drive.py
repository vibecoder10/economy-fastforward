#!/usr/bin/env python3
"""Download images from Airtable and upload to Google Drive.

Reads all image records for a video, downloads each attachment,
and uploads to the matching Google Drive folder with Scene_XX_YY.png naming.

Usage:
    python3 upload_images_to_drive.py "Video Title"
"""
import os
import sys
from pathlib import Path

# Load env from VPS path
from dotenv import load_dotenv
load_dotenv(Path("/home/clawd/projects/economy-fastforward/.env"))

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
    print(f"  Found {len(images)} image records")

    # Step 2: Get or create Drive folder
    print("  Step 2: Finding Google Drive folder...")
    folder = google.get_or_create_folder(VIDEO_TITLE)
    folder_id = folder["id"]
    print(f"  Folder: {folder['name']} ({folder_id})")

    # Step 3: Download from Airtable + upload to Drive
    print(f"  Step 3: Uploading {len(images)} images...")
    uploaded = 0
    skipped = 0
    errors = 0

    for img in images:
        scene = img.get("Scene", 0)
        img_index = img.get("Image Index", 0)
        filename = f"Scene_{int(scene):02d}_{int(img_index):02d}.png"

        # Get attachment URL from Airtable
        attachments = img.get("Generated Image", []) or img.get("Image", [])
        if not attachments or not isinstance(attachments, list):
            print(f"    {filename}: ⚠️ no attachment, skipping")
            skipped += 1
            continue

        url = attachments[0].get("url", "")
        if not url:
            print(f"    {filename}: ⚠️ empty URL, skipping")
            skipped += 1
            continue

        # Download from Airtable
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
            uploaded += 1
            print(f"    {filename}: ✅ uploaded ({result['id']})")
        except Exception as e:
            print(f"    {filename}: ❌ upload failed ({e})")
            errors += 1

    print()
    print(f"  ✅ Uploaded: {uploaded}")
    if skipped:
        print(f"  ⚠️ Skipped (no attachment): {skipped}")
    if errors:
        print(f"  ❌ Errors: {errors}")
    print(f"  📂 Drive folder: https://drive.google.com/drive/folders/{folder_id}")


if __name__ == "__main__":
    main()
