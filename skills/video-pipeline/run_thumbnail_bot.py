"""
Run the Thumbnail Bot on an idea marked "Ready For Thumbnail" in Airtable.

Called by: pipeline_control.py (Slack bot)
Commands: thumbnail

Generates a matched thumbnail + title pair using the ThumbnailTitleEngine:
- Selects template (CFH Split / Mindplicit Banner / Power Dynamic)
- Generates title from proven formula patterns
- Builds thumbnail prompt with CAPS word as red highlight
- Generates image via Nano Banana Pro (up to 3 attempts)
- Uploads to Google Drive and advances status to "Ready To Render"
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
    print("RUNNING THUMBNAIL + TITLE BOT")
    print("=" * 60)

    pipeline = VideoPipeline()

    try:
        result = await pipeline.run_thumbnail_bot()

        if result.get("error"):
            print(f"\n{result['error']}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("THUMBNAIL + TITLE BOT COMPLETE!")
        print("=" * 60)
        print(f"\n  Video: {result.get('video_title')}")
        print(f"  Title: {result.get('generated_title')}")
        print(f"  CAPS word: {result.get('caps_word')}")
        print(f"  Formula: {result.get('formula_used')}")
        print(f"  Template: {result.get('template_name')} ({result.get('template_used')})")
        print(f"  Thumbnail text: {result.get('line_1')} / {result.get('line_2')}")
        print(f"  Thumbnail: {result.get('thumbnail_url')}")
        print(f"  Attempt: {result.get('thumbnail_attempt')}")
        print(f"  New status: {result.get('new_status')}")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
