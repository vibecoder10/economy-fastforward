"""
Run the Thumbnail Bot on an idea marked "Ready For Thumbnail" in Airtable.

Called by: pipeline_control.py (Slack bot)
Commands: thumbnail

Generates a thumbnail image using house style + optional reference analysis,
uploads to Google Drive, and advances status to "Done".
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
    print("🎨 RUNNING THUMBNAIL BOT")
    print("=" * 60)

    pipeline = VideoPipeline()

    try:
        result = await pipeline.run_thumbnail_bot()

        if result.get("error"):
            print(f"\n❌ {result['error']}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ THUMBNAIL BOT COMPLETE!")
        print("=" * 60)
        print(f"\n🎬 Video: {result.get('video_title')}")
        print(f"🖼️  Thumbnail: {result.get('thumbnail_url')}")
        print(f"📋 New status: {result.get('new_status')}")
        print(f"📸 Used reference: {result.get('used_reference')}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
