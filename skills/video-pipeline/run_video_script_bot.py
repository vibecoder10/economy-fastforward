"""
Run the Video Script Bot — generates motion prompts for images.

Called by: pipeline_control.py (Slack bot)
Commands: video prompts, run video prompts
Supports: --scene N --image N to only generate specific prompts
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
    parser.add_argument("--image", type=int, default=None, help="Only process this image index")
    args = parser.parse_args()

    print("=" * 60)
    print("📝 RUNNING VIDEO SCRIPT BOT (Video Prompts)")
    print("=" * 60)

    pipeline = VideoPipeline()
    pipeline.scene_filter = args.scene
    pipeline.image_filter = args.image

    # Find idea at correct status
    idea = pipeline.get_idea_by_status(pipeline.STATUS_READY_VIDEO_SCRIPTS)
    if not idea:
        print("\n⚠️ No ideas with 'Ready For Video Scripts' status found.")
        sys.exit(0)

    pipeline._load_idea(idea)
    print(f"\n🎬 Video: {pipeline.video_title}")

    try:
        result = await pipeline.run_video_script_bot()

        if result.get("status") == "failed" or result.get("error"):
            print(f"\n❌ {result.get('error', 'Unknown error')}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ VIDEO SCRIPT BOT COMPLETE!")
        print("=" * 60)
        print(f"\n📝 Prompts generated: {result.get('prompt_count', 0)}")
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
