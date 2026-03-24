"""
Run the Render Bot on an idea marked "Ready To Render" in Airtable.

Called by: pipeline_control.py (Slack bot)
Commands: render

Renders video with Remotion, uploads to Google Drive,
and advances status to "Done".
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from orchestrator.pipeline import VideoPipeline
from orchestrator.pipeline_constants import IdeaFields


async def main():
    print("=" * 60)
    print("🎬 RUNNING RENDER BOT")
    print("=" * 60)

    pipeline = VideoPipeline()

    # Find all videos ready to render
    ideas = pipeline.airtable.get_ideas_by_status(pipeline.STATUS_READY_TO_RENDER, limit=10)

    if not ideas:
        print("\n❌ No ideas with status 'Ready To Render'")
        sys.exit(1)

    print(f"\n📋 Found {len(ideas)} video(s) to render:")
    for i, idea in enumerate(ideas, 1):
        print(f"   {i}. {idea.get(IdeaFields.VIDEO_TITLE, 'Untitled')}")

    # Process one at a time, sequentially
    for i, idea in enumerate(ideas, 1):
        title = idea.get(IdeaFields.VIDEO_TITLE, "Untitled")
        print(f"\n{'=' * 60}")
        print(f"🎬 RENDERING {i}/{len(ideas)}: {title}")
        print(f"{'=' * 60}")

        try:
            pipeline._load_idea(idea)
            result = await pipeline.run_render_bot()

            if result.get("error"):
                print(f"\n❌ Render failed for '{title}': {result['error']}")
                print(f"   Stopping — fix this video before rendering the rest.")
                sys.exit(1)

            print(f"\n✅ '{title}' rendered and uploaded!")
            print(f"   🔗 {result.get('video_url', 'N/A')}")

        except Exception as e:
            print(f"\n❌ Error rendering '{title}': {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    print("\n" + "=" * 60)
    print(f"✅ ALL {len(ideas)} VIDEO(S) RENDERED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
