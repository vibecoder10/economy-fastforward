"""One-time OAuth2 authorization for YouTube Data API v3.

Run this script once on the VPS to complete the OAuth flow.
It opens a browser for Google sign-in and saves the token to
.youtube-token.json for all future uploads.

Prerequisites:
    1. Create a Google Cloud project
    2. Enable YouTube Data API v3
    3. Create OAuth2 Desktop credentials
    4. Download credentials JSON and save as:
       skills/video-pipeline/.youtube-credentials.json

Usage:
    python youtube_auth.py

    # On a headless VPS, use --no-browser and paste the URL manually:
    python youtube_auth.py --no-browser
"""

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly"
]

PIPELINE_DIR = Path(__file__).parent
CREDENTIALS_FILE = PIPELINE_DIR / ".youtube-credentials.json"
TOKEN_FILE = PIPELINE_DIR / ".youtube-token.json"


def main():
    if not CREDENTIALS_FILE.exists():
        print(f"Credentials file not found: {CREDENTIALS_FILE}")
        print()
        print("To set up:")
        print("  1. Go to https://console.cloud.google.com/apis/credentials")
        print("  2. Create OAuth 2.0 Client ID (Desktop application)")
        print("  3. Download the JSON file")
        print(f"  4. Save it as: {CREDENTIALS_FILE}")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
    )

    if "--no-browser" in sys.argv:
        # For headless VPS: prints URL to paste in browser
        creds = flow.run_console()
    else:
        # Opens browser for OAuth flow
        creds = flow.run_local_server(port=8080)

    # Save token
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
    }

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\nToken saved to: {TOKEN_FILE}")
    print("YouTube uploads are now authorized.")
    print("\nIMPORTANT: Never commit this file to git!")


if __name__ == "__main__":
    main()
