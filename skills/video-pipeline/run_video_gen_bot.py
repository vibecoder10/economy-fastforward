"""
Run the Video Gen Bot on an idea marked "Ready For Video Generation" in Airtable.

Called by: pipeline_control.py (Slack bot)
Commands: video generate, run video generate

Generates video clips from images with motion prompts using Grok Imagine,
uploads to Google Drive, and advances status to "Ready For Thumbnail".
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
    print("🎥 RUNNING VIDEO GEN BOT (Video Generation)")
    print("=" * 60)

    pipeline = VideoPipeline()

    # Find idea at correct status
    idea = pipeline.get_idea_by_status(pipeline.STATUS_READY_VIDEO_GENERATION)
    if not idea:
        print("\n⚠️ No ideas with 'Ready For Video Generation' status found.")
        sys.exit(0)

    pipeline._load_idea(idea)
    print(f"\n🎬 Video: {pipeline.video_title}")

    try:
        result = await pipeline.run_video_gen_bot()

        if result.get("status") == "failed" or result.get("error"):
            print(f"\n❌ {result.get('error', 'Unknown error')}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ VIDEO GEN BOT COMPLETE!")
        print("=" * 60)
        print(f"\n🎥 Videos generated: {result.get('video_count', 0)}")
        print(f"📋 New status: {result.get('new_status', 'Ready For Thumbnail')}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
