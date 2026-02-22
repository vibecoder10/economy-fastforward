"""
Run audio sync (Whisper alignment) for the current pipeline video.

Called by: pipeline_control.py (Slack bot)
Commands: sync, timing

Transcribes the voiceover audio with Whisper, aligns each scene's
narration to word timestamps, and writes per-scene durations back to
Airtable image records.  Also saves render_config.json for Remotion.

Can be run independently of the prompts stage — works as long as voice
audio and Airtable scene/image records exist for the video.
"""

import json
import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

# Find .env by walking up from this file
_dir = Path(__file__).resolve().parent
for _i in range(10):
    _env = _dir / ".env"
    if _env.exists():
        load_dotenv(_env, override=True)
        break
    if _dir.parent == _dir:
        break
    _dir = _dir.parent

from pipeline import VideoPipeline


async def main():
    print("=" * 60)
    print("🎵 RUNNING AUDIO SYNC")
    print("=" * 60)

    pipeline = VideoPipeline()

    # Find a video that has voice audio — audio sync can run at any stage
    # after voice generation (Ready For Image Prompts and later)
    idea = None
    for status in [
        pipeline.STATUS_READY_IMAGES,
        pipeline.STATUS_READY_IMAGE_PROMPTS,
        pipeline.STATUS_READY_THUMBNAIL,
        pipeline.STATUS_READY_VIDEO_SCRIPTS,
        pipeline.STATUS_READY_VIDEO_GENERATION,
        pipeline.STATUS_READY_TO_RENDER,
    ]:
        idea = pipeline.get_idea_by_status(status)
        if idea:
            break

    if not idea:
        print("❌ No idea found at any stage after voice generation")
        sys.exit(1)

    pipeline._load_idea(idea)
    print(f"🎬 Video: {pipeline.video_title}")

    try:
        sync_result = await pipeline.run_audio_sync()

        if sync_result.get("error"):
            print(f"\n❌ Audio sync error: {sync_result['error']}")
            sys.exit(1)

        # Durations are now written to Airtable inside run_audio_sync()
        print("\n" + "=" * 60)
        print("✅ AUDIO SYNC COMPLETE!")
        print("=" * 60)
        print(f"🎬 Video: {sync_result.get('video_title')}")
        print(f"📊 Scenes: {sync_result.get('scene_count')} | Images: {sync_result.get('image_count', 0)}")
        print(f"⏱️  Total duration: {sync_result.get('total_duration', 0):.1f}s")
        print(f"📏 Avg image duration: {sync_result.get('avg_duration', 0):.1f}s")
        print(f"📂 Render config: {sync_result.get('render_config_path')}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
