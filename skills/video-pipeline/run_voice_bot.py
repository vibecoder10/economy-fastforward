"""
Run the Voice Bot on an idea marked "Ready For Voice" in Airtable.

Called by: pipeline_control.py (Slack bot)
Commands: voice, run voice
Supports: --scene N to only generate voice for a specific scene
"""

import os
import sys
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from pipeline import VideoPipeline


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=int, default=None, help="Only process this scene number")
    args = parser.parse_args()

    print("=" * 60)
    print("🗣️ RUNNING VOICE BOT")
    print("=" * 60)

    pipeline = VideoPipeline()
    pipeline.scene_filter = args.scene

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
        if result.get("targeted"):
            print("🎯 Targeted run — status not advanced")
        else:
            print(f"📋 New status: {result.get('new_status')}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
