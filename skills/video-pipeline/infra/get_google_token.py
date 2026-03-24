"""
Google OAuth Helper - Generate Refresh Token

Run this script once to get a refresh token for Google Drive/Docs access.
The token will be printed - copy it to your .env file.
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Scopes needed for Drive and Docs
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
]

def get_refresh_token():
    """Run OAuth flow and print the refresh token."""
    
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        print("❌ Error: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
        return
    
    # Create OAuth config
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/"]
        }
    }
    
    # Run the OAuth flow
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    
    print("\n🔐 Opening browser for Google OAuth...")
    print("   Please sign in and authorize access.\n")
    
    credentials = flow.run_local_server(port=8080)
    
    print("\n" + "=" * 60)
    print("✅ SUCCESS! Here's your refresh token:")
    print("=" * 60)
    print(f"\nGOOGLE_REFRESH_TOKEN={credentials.refresh_token}\n")
    print("=" * 60)
    print("\n👆 Copy the line above and paste it into your .env file")
    print("   (Replace the empty GOOGLE_REFRESH_TOKEN= line)\n")
    
    return credentials.refresh_token


if __name__ == "__main__":
    get_refresh_token()
