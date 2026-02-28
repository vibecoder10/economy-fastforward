"""Upload a rendered video to Google Drive using chunked resumable upload.

Usage:
    python tasks/upload_video_drive.py <file_path> <folder_id>

Example:
    python tasks/upload_video_drive.py \
        /home/clawd/projects/economy-fastforward/remotion-video/out/final.mp4 \
        1fsFx4mT0JnmFvJcMkMmk69lIopD_voY9
"""

import os
import sys

# Add video-pipeline to path for client imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "video-pipeline"))

from dotenv import load_dotenv

load_dotenv()

from clients.google_client import GoogleClient


def main():
    if len(sys.argv) < 3:
        print("Usage: python tasks/upload_video_drive.py <file_path> <folder_id>")
        sys.exit(1)

    file_path = sys.argv[1]
    folder_id = sys.argv[2]

    if not os.path.isfile(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    file_name = os.path.basename(file_path)
    client = GoogleClient()
    result = client.upload_large_file(
        file_path=file_path,
        name=file_name,
        folder_id=folder_id,
        mime_type="video/mp4",
    )

    file_id = result["id"]
    client.make_file_public(file_id)
    drive_link = f"https://drive.google.com/file/d/{file_id}/view"
    print(f"\n    Drive link: {drive_link}")


if __name__ == "__main__":
    main()
