"""
Run the Brief Translator (script generation) on an idea marked "Ready For Scripting".

Called by: pipeline_control.py (Slack bot)
Commands: script, run script

This is the production script generation path. It uses the brief translator
with ScriptProfile-driven validation, editorial checks, and retry logic.
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from orchestrator.pipeline import VideoPipeline


async def main():
    print("=" * 60)
    print("📜 RUNNING BRIEF TRANSLATOR (Script Generation)")
    print("=" * 60)

    pipeline = VideoPipeline()

    try:
        result = await pipeline.run_brief_translator()

        status = result.get("status", "unknown")
        if status == "error" or result.get("error"):
            print(f"\n❌ {result.get('error', status)}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ SCRIPT GENERATION COMPLETE!")
        print("=" * 60)
        print(f"\n📝 Status: {status}")
        if result.get("scene_filepath"):
            print(f"📂 Scene file: {result['scene_filepath']}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
