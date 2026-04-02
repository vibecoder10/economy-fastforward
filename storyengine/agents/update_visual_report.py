#!/usr/bin/env python3
"""Upload QA screenshots to Google Drive and append to the Visual Report Google Doc."""
import json, os, sys

TASK_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"
SUMMARY = sys.argv[2] if len(sys.argv) > 2 else "QA verification"
DOC_ID = "1IxCl--zuK4PeCgrW5RCGZJflIYxTY7XT7lEaAjTeaGE"
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
DRIVE_FOLDER_ID = "1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD"

# Load credentials from production .env
env = {}
env_path = "/home/clawd/projects/economy-fastforward/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k] = v

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("Google API libraries not available — skipping visual report update")
    sys.exit(0)

try:
    creds = Credentials(
        token=None,
        refresh_token=env.get("GOOGLE_REFRESH_TOKEN"),
        client_id=env.get("GOOGLE_CLIENT_ID"),
        client_secret=env.get("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )

    drive = build("drive", "v3", credentials=creds)
    docs = build("docs", "v1", credentials=creds)

    # Upload screenshots to Drive
    image_urls = []
    for suffix in ["before", "after"]:
        filepath = os.path.join(SCREENSHOTS_DIR, f"{TASK_ID}-{suffix}.png")
        if os.path.exists(filepath):
            media = MediaFileUpload(filepath, mimetype="image/png")
            file = drive.files().create(
                body={"name": f"{TASK_ID}-{suffix}.png", "parents": [DRIVE_FOLDER_ID]},
                media_body=media,
                fields="id",
            ).execute()
            drive.permissions().create(
                fileId=file["id"],
                body={"type": "anyone", "role": "reader"},
            ).execute()
            image_urls.append((suffix, f"https://drive.google.com/uc?id={file['id']}"))
            print(f"  Uploaded {suffix}: {filepath}")

    if not image_urls:
        print(f"No screenshots found for {TASK_ID}")
        sys.exit(0)

    # Append to Google Doc (prepend at top so newest is first)
    from datetime import datetime
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    requests = []
    # Insert in reverse order (last item inserted first = appears first)
    requests.append({
        "insertText": {
            "location": {"index": 1},
            "text": f"\n{'='*60}\n\n",
        }
    })

    for suffix, url in reversed(image_urls):
        requests.append({
            "insertInlineImage": {
                "location": {"index": 1},
                "uri": url,
                "objectSize": {
                    "width": {"magnitude": 468, "unit": "PT"},
                },
            }
        })
        requests.append({
            "insertText": {
                "location": {"index": 1},
                "text": f"\n{suffix.upper()}:\n",
            }
        })

    requests.append({
        "insertText": {
            "location": {"index": 1},
            "text": f"\n🔍 {TASK_ID} — {SUMMARY}\n📅 {timestamp}\n",
        }
    })

    docs.documents().batchUpdate(
        documentId=DOC_ID, body={"requests": requests}
    ).execute()
    print(f"Visual report updated: {len(image_urls)} screenshots for {TASK_ID}")

except Exception as e:
    print(f"Visual report update failed (non-blocking): {e}")
    sys.exit(0)  # Never fail the QA run because of this
