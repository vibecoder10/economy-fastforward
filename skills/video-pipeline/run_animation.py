"""Run the Animation Pipeline for the current Create project.

Called by: pipeline_control.py on VPS (Slack bot)
Commands: animate, animation, run animation
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from animation.pipeline import AnimationPipeline


async def main():
    print("=" * 60)
    print("🎬 RUNNING ANIMATION PIPELINE")
    print("=" * 60)

    pipeline = AnimationPipeline()

    try:
        result = await pipeline.run_full_pipeline(skip_videos=True)

        print("\n" + "=" * 60)
        print("✅ ANIMATION PIPELINE COMPLETE!")
        print("=" * 60)
        print(f"\n📁 Project: {result.get('project')}")
        print(f"🎬 Scenes: {result.get('scenes')}")
        print(f"🖼️  Images generated: {result.get('images_generated')}")
        print(f"💰 Total cost: ${result.get('total_cost', 0):.2f}")

        return result

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


if __name__ == "__main__":
    asyncio.run(main())
