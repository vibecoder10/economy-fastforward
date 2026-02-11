"""Run the Animation Pipeline for the current Create project.

Called by: pipeline_control.py on VPS (Slack bot)
Commands: animate, animation, run animation

Uses the canonical /animation/ module at the repo root.
"""

import os
import sys
import asyncio

# Add repo root to path for animation module
REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, REPO_ROOT)

# Add video-pipeline dir for clients module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(REPO_ROOT, '.env'))

from animation.pipeline import AnimationPipeline


async def main():
    print("=" * 60)
    print("🎬 RUNNING ANIMATION PIPELINE")
    print("=" * 60)

    pipeline = AnimationPipeline()

    try:
        result = await pipeline.run()

        print("\n" + "=" * 60)
        print("✅ ANIMATION PIPELINE COMPLETE!")
        print("=" * 60)

        if result:
            print(f"\n📁 Project: {result.get('project_name')}")
            print(f"🎬 Scenes: {result.get('total_scenes')}")
            print(f"✅ Complete: {result.get('scenes_complete')}")
            print(f"💰 Total cost: ${result.get('total_spend', 0):.2f}")

        return result

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


if __name__ == "__main__":
    asyncio.run(main())
