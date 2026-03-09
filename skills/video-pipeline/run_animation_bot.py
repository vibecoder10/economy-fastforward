"""
Run the Animation Bot on an idea marked "Ready For Animation" in Airtable.

Called by: pipeline_control.py (Slack bot)
Commands: animation, run animation
Supports: --scene N --image N to only animate specific clips
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
    print("🎬 RUNNING ANIMATION BOT")
    print("=" * 60)

    pipeline = VideoPipeline()
    pipeline.scene_filter = args.scene
    pipeline.image_filter = args.image

    try:
        result = await pipeline.run_animation_bot()

        if result.get("status") == "failed" or result.get("error"):
            print(f"\n❌ {result.get('error', 'Unknown error')}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ ANIMATION BOT COMPLETE!")
        print("=" * 60)
        print(f"\n🎬 Video: {result.get('video_title')}")
        print(f"🎥 Clips generated: {result.get('clips_generated')}")
        print(f"❌ Clips failed: {result.get('clips_failed', 0)}")
        print(f"💰 Cost: ${result.get('actual_cost', 0):.2f}")
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
