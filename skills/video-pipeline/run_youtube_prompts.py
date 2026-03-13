"""
Generate image prompts for the YouTube pipeline.

Called by: pipeline_control.py (Slack bot)
Commands: prompts (when used in YouTube pipeline context)
Supports: --scene N to only generate prompts for a specific scene

NOTE: This only generates prompts. Use `images` command (run_image_bot.py)
to generate actual images, or `run` to advance through pipeline steps.
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
    print("🎨 RUNNING YOUTUBE PROMPTS")
    print("=" * 60)

    pipeline = VideoPipeline()
    pipeline.scene_filter = args.scene
    pipeline.image_filter = args.image

    try:
        # Generate image prompts (styled) — resumable: skips scenes with existing prompts
        prompt_result = await pipeline.run_styled_image_prompts()

        if prompt_result.get("error"):
            print(f"\n❌ Prompt generation error: {prompt_result['error']}", file=sys.stderr)
            sys.exit(1)

        skipped = prompt_result.get('scenes_skipped', 0)
        created = prompt_result.get('total_concepts', 0)
        if skipped:
            print(f"\n📝 Image prompts: {created} new, {skipped} already existed (resumed)")
        else:
            print(f"\n📝 Image prompts created: {created}")

        print("\n" + "=" * 60)
        print("✅ YOUTUBE PROMPTS COMPLETE!")
        print("=" * 60)
        print(f"\n🎬 Video: {prompt_result.get('video_title', 'N/A')}")
        print(f"📝 Prompts created: {created}")
        if prompt_result.get("targeted"):
            print("🎯 Targeted run — status not advanced")
        else:
            print(f"📋 New status: {prompt_result.get('new_status', 'N/A')}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
