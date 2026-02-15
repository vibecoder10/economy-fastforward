"""
Run the Voice Bot on an idea marked "Ready For Voice" in Airtable.

Called by: pipeline_control.py (Slack bot)
Commands: voice

Generates voiceover audio for all scenes using ElevenLabs,
uploads to Google Drive, and advances status to "Ready For Visuals".
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from pipeline import VideoPipeline


async def main():
    print("=" * 60)
    print("🗣️ RUNNING VOICE BOT")
    print("=" * 60)

    pipeline = VideoPipeline()

    try:
        result = await pipeline.run_voice_bot()

        if result.get("error"):
            print(f"\n❌ {result['error']}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ VOICE BOT COMPLETE!")
        print("=" * 60)
        print(f"\n🎬 Video: {result.get('video_title')}")
        print(f"🗣️ Voices generated: {result.get('voice_count')}")
        print(f"📋 New status: {result.get('new_status')}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
