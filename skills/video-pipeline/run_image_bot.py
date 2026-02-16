"""
Run the Image Bot on an idea marked "Ready For Images" in Airtable.

Called by: pipeline_control.py (Slack bot)
Commands: images, run images

Generates all scene images using Seed Dream 4.5 Edit with Core Image reference,
uploads to Google Drive, and advances status to "Ready For Thumbnail" only when
ALL images are verified complete.
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
    print("🖼️ RUNNING IMAGE BOT")
    print("=" * 60)

    pipeline = VideoPipeline()

    try:
        result = await pipeline.run_image_bot()

        if result.get("status") == "failed" or result.get("error"):
            print(f"\n❌ {result.get('error', 'Unknown error')}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ IMAGE BOT COMPLETE!")
        print("=" * 60)
        print(f"\n🎬 Video: {result.get('video_title')}")
        print(f"🖼️  Images generated: {result.get('image_count')}")
        print(f"📋 New status: {result.get('new_status')}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
