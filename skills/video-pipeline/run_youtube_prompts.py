"""
Generate image prompts and images for the YouTube pipeline.

Called by: pipeline_control.py (Slack bot)
Commands: prompts (when used in YouTube pipeline context)
Supports: --scene N to only generate prompts/images for a specific scene
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
    print("🎨 RUNNING YOUTUBE PROMPTS & IMAGES")
    print("=" * 60)

    pipeline = VideoPipeline()
    pipeline.scene_filter = args.scene
    pipeline.image_filter = args.image

    try:
        # First generate image prompts (styled) — resumable: skips scenes with existing prompts
        prompt_result = await pipeline.run_styled_image_prompts()

        if prompt_result.get("error"):
            # If prompts already completed (idea at "Ready For Images"), skip to image generation
            if "No idea" in prompt_result["error"]:
                print(f"\n♻️ Prompts already done — resuming with image generation...")
                prompt_result = {"prompt_count": 0, "skipped": "all"}
            else:
                print(f"\n❌ Prompt generation error: {prompt_result['error']}", file=sys.stderr)
                sys.exit(1)

        skipped = prompt_result.get('skipped', 0)
        created = prompt_result.get('prompt_count', 0)
        if skipped:
            print(f"\n📝 Image prompts: {created} new, {skipped} already existed (resumed)")
        else:
            print(f"\n📝 Image prompts created: {created}")

        # Then generate actual images — resumable: skips images with Status="Done"
        image_result = await pipeline.run_image_bot()

        if image_result.get("error"):
            print(f"\n⚠️ Image generation error: {image_result['error']}")
            # Don't exit — prompts were still created successfully

        print("\n" + "=" * 60)
        print("✅ YOUTUBE PROMPTS & IMAGES COMPLETE!")
        print("=" * 60)
        print(f"\n🎬 Video: {prompt_result.get('video_title', image_result.get('video_title'))}")
        print(f"📝 Prompts created: {created}")
        print(f"🖼️  Images generated: {image_result.get('image_count', 0)}")
        if prompt_result.get("targeted") or image_result.get("targeted"):
            print("🎯 Targeted run — status not advanced")
        else:
            print(f"📋 New status: {image_result.get('new_status', prompt_result.get('new_status'))}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
