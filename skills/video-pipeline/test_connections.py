"""
Test all API connections before running the full pipeline.
"""

import os
import sys
import asyncio

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

async def test_anthropic():
    """Test Anthropic Claude API."""
    print("\n1️⃣  Testing Anthropic (Claude)...")
    try:
        from clients.anthropic_client import AnthropicClient
        client = AnthropicClient()
        response = await client.generate(
            prompt="Say 'API connection successful!' in exactly 4 words.",
            max_tokens=50,
        )
        print(f"   ✅ Anthropic: {response.strip()}")
        return True
    except Exception as e:
        print(f"   ❌ Anthropic failed: {e}")
        return False

async def test_airtable():
    """Test Airtable API."""
    print("\n2️⃣  Testing Airtable...")
    try:
        from clients.airtable_client import AirtableClient
        client = AirtableClient()
        # Just try to access the ideas table
        records = client.ideas_table.all(max_records=1)
        print(f"   ✅ Airtable: Connected to Ideas table ({len(records)} record(s) found)")
        return True
    except Exception as e:
        print(f"   ❌ Airtable failed: {e}")
        return False

async def test_google():
    """Test Google Drive API."""
    print("\n3️⃣  Testing Google Drive...")
    try:
        from clients.google_client import GoogleClient
        client = GoogleClient()
        # Search for any folder
        results = client.drive_service.files().list(
            q="mimeType = 'application/vnd.google-apps.folder'",
            pageSize=1,
            fields="files(id, name)",
        ).execute()
        files = results.get('files', [])
        if files:
            print(f"   ✅ Google Drive: Connected (found folder: {files[0]['name']})")
        else:
            print(f"   ✅ Google Drive: Connected (no folders found, but API works)")
        return True
    except Exception as e:
        print(f"   ❌ Google Drive failed: {e}")
        return False

async def test_slack():
    """Test Slack API."""
    print("\n4️⃣  Testing Slack...")
    try:
        from clients.slack_client import SlackClient
        client = SlackClient()
        # Test by getting bot info
        response = client.client.auth_test()
        print(f"   ✅ Slack: Connected as @{response['user']}")
        return True
    except Exception as e:
        print(f"   ❌ Slack failed: {e}")
        return False

async def test_wavespeed():
    """Test Wavespeed/ElevenLabs API."""
    print("\n5️⃣  Testing Wavespeed (Voice)...")
    try:
        from clients.elevenlabs_client import ElevenLabsClient
        client = ElevenLabsClient()
        # Just verify the client initializes (don't actually generate voice)
        print(f"   ✅ Wavespeed: Client initialized (API key set, voice ID: {client.voice_id})")
        return True
    except Exception as e:
        print(f"   ❌ Wavespeed failed: {e}")
        return False

async def test_kieai():
    """Test Kie.ai Image API."""
    print("\n6️⃣  Testing Kie.ai (Images)...")
    try:
        from clients.image_client import ImageClient
        client = ImageClient()
        # Just verify the client initializes
        print(f"   ✅ Kie.ai: Client initialized (API key set)")
        return True
    except Exception as e:
        print(f"   ❌ Kie.ai failed: {e}")
        return False


async def main():
    print("=" * 60)
    print("🧪 VIDEO PIPELINE - API CONNECTION TEST")
    print("=" * 60)
    
    results = []
    
    results.append(await test_anthropic())
    results.append(await test_airtable())
    results.append(await test_google())
    results.append(await test_slack())
    results.append(await test_wavespeed())
    results.append(await test_kieai())
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"🎉 ALL TESTS PASSED ({passed}/{total})")
        print("=" * 60)
        print("\n✅ Ready to run the full pipeline!")
        print("   python pipeline.py 'https://youtube.com/watch?v=VIDEO_ID'")
    else:
        print(f"⚠️  SOME TESTS FAILED ({passed}/{total})")
        print("=" * 60)
        print("\nPlease fix the failing APIs before running the pipeline.")
    
    return passed == total


if __name__ == "__main__":
    asyncio.run(main())
