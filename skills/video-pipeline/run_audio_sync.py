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
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from pipeline import VideoPipeline


async def main():
    print("=" * 60)
    print("🎵 RUNNING AUDIO SYNC")
    print("=" * 60)

    pipeline = VideoPipeline()

    # Find a video that has image records (Ready For Images or later)
    idea = pipeline.get_idea_by_status(pipeline.STATUS_READY_IMAGES)
    if not idea:
        # Also check if there's a video at the image prompts stage
        idea = pipeline.get_idea_by_status(pipeline.STATUS_READY_IMAGE_PROMPTS)
    if not idea:
        print("❌ No idea found at 'Ready For Images' or 'Ready For Image Prompts'")
        sys.exit(1)

    pipeline._load_idea(idea)
    print(f"🎬 Video: {pipeline.video_title}")

    try:
        sync_result = await pipeline.run_audio_sync()

        if sync_result.get("error"):
            print(f"\n❌ Audio sync error: {sync_result['error']}")
            sys.exit(1)

        # Write durations back to Airtable
        render_config_path = sync_result.get("render_config_path")
        if render_config_path and Path(render_config_path).exists():
            render_config = json.loads(Path(render_config_path).read_text())
            duration_updates = 0
            image_records = pipeline.airtable.get_all_images_for_video(pipeline.video_title)
            record_lookup = {}
            for rec in image_records:
                key = (rec.get("Scene"), rec.get("Image Index"))
                record_lookup[key] = rec["id"]

            for rc_scene in render_config.get("scenes", []):
                scene_num = rc_scene.get("scene_number")
                display_dur = rc_scene.get("display_duration")
                if scene_num is None or display_dur is None:
                    continue
                for (s, idx), rec_id in record_lookup.items():
                    if s == scene_num:
                        pipeline.airtable.images_table.update(
                            rec_id,
                            {"Duration (s)": round(display_dur, 2)},
                            typecast=True,
                        )
                        duration_updates += 1

            avg_dur = sync_result["total_duration"] / max(sync_result["scene_count"], 1)
            print(f"\n✅ Durations written: {duration_updates} Airtable records updated")
            print(f"   Avg duration: {avg_dur:.1f}s")

        print("\n" + "=" * 60)
        print("✅ AUDIO SYNC COMPLETE!")
        print("=" * 60)
        print(f"🎬 Video: {sync_result.get('video_title')}")
        print(f"📊 Scenes aligned: {sync_result.get('scene_count')}")
        print(f"🔤 Words transcribed: {sync_result.get('words_transcribed')}")
        print(f"⏱️  Total duration: {sync_result.get('total_duration', 0):.1f}s")
        print(f"📋 Quality: {sync_result.get('alignment_quality')}")
        print(f"📂 Render config: {sync_result.get('render_config_path')}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
