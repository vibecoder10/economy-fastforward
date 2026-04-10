#!/usr/bin/env python3
"""Upload new screenshots to Google Drive and append to the Visual Report Google Doc.

Usage:
  python3 update_visual_report.py                          # Upload all new screenshots
  python3 update_visual_report.py T9-003 "Task summary"    # Upload specific task screenshots
  python3 update_visual_report.py --skip-regression         # Skip reg* regression screenshots
"""
import glob, json, os, sys
from datetime import datetime

DOC_ID = "1IxCl--zuK4PeCgrW5RCGZJflIYxTY7XT7lEaAjTeaGE"
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
DRIVE_FOLDER_ID = "1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD"
UPLOADED_FILE = os.path.join(SCREENSHOTS_DIR, ".uploaded.json")

SKIP_REGRESSION = '--skip-regression' in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith('--')]
TASK_ID = args[0] if len(args) > 0 else None
SUMMARY = args[1] if len(args) > 1 else ""

# Track what's already been uploaded
uploaded = set()
if os.path.exists(UPLOADED_FILE):
    try:
        uploaded = set(json.load(open(UPLOADED_FILE)))
    except:
        pass

# Load credentials
env = {}
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
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
    print("Google API libraries not available — skipping")
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

    # Find screenshots to upload
    if TASK_ID:
        # Specific task — look for TASKID*.png
        patterns = [
            os.path.join(SCREENSHOTS_DIR, f"{TASK_ID}*.png"),
            os.path.join(SCREENSHOTS_DIR, f"{TASK_ID}*.jpg"),
        ]
    else:
        # All new screenshots
        patterns = [
            os.path.join(SCREENSHOTS_DIR, "*.png"),
            os.path.join(SCREENSHOTS_DIR, "*.jpg"),
        ]

    files_to_upload = []
    for pattern in patterns:
        for filepath in sorted(glob.glob(pattern)):
            filename = os.path.basename(filepath)
            if filename.startswith("."):
                continue
            if filename in uploaded:
                continue
            if SKIP_REGRESSION and filename.startswith("reg"):
                continue
            files_to_upload.append(filepath)

    if not files_to_upload:
        print("No new screenshots to upload")
        sys.exit(0)

    # Upload each to Drive
    image_entries = []
    for filepath in files_to_upload:
        filename = os.path.basename(filepath)
        print(f"  Uploading: {filename}")
        media = MediaFileUpload(filepath, mimetype="image/png")
        f = drive.files().create(
            body={"name": filename, "parents": [DRIVE_FOLDER_ID]},
            media_body=media,
            fields="id",
        ).execute()
        drive.permissions().create(
            fileId=f["id"], body={"type": "anyone", "role": "reader"}
        ).execute()
        url = f"https://drive.google.com/uc?id={f['id']}"
        image_entries.append((filename, url))
        uploaded.add(filename)

    # Write to Google Doc (newest at top)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    sep = "=" * 60

    requests = []
    requests.append({
        "insertText": {"location": {"index": 1}, "text": f"\n{sep}\n\n"}
    })

    for filename, url in reversed(image_entries):
        # Add label for each screenshot
        label = filename.replace(".png", "").replace(".jpg", "").replace("-", " ").replace("_", " ").title()
        requests.append({
            "insertInlineImage": {
                "location": {"index": 1},
                "uri": url,
                "objectSize": {"width": {"magnitude": 468, "unit": "PT"}},
            }
        })
        requests.append({
            "insertText": {"location": {"index": 1}, "text": f"\n{label}:\n"}
        })

    header = SUMMARY if SUMMARY else f"{len(image_entries)} screenshots"
    title = TASK_ID if TASK_ID else "Agent Update"
    requests.append({
        "insertText": {
            "location": {"index": 1},
            "text": f"\n{'🔍' if TASK_ID else '📸'} {title} — {header}\n{'📅'} {timestamp}\n",
        }
    })

    docs.documents().batchUpdate(
        documentId=DOC_ID, body={"requests": requests}
    ).execute()
    print(f"Google Doc updated: {len(image_entries)} screenshots")

    # Save uploaded list
    json.dump(list(uploaded), open(UPLOADED_FILE, "w"))

except Exception as e:
    print(f"Visual report update failed (non-blocking): {e}")
    sys.exit(0)
