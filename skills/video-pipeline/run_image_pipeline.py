"""
Run Image Prompts and Images for an idea that's Ready For Image Prompts.

First updates the idea status to 'Ready For Image Prompts' so the Image Prompt Bot can find it.
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from pipeline import VideoPipeline


async def main():
    print("=" * 60)
    print("🎬 RUNNING IMAGE PIPELINE")
    print("   Image Prompts → Images")
    print("=" * 60)

    pipeline = VideoPipeline()

    # First, let's manually set the idea status to "Ready For Image Prompts"
    # Get the idea that's currently at a later stage and set it back
    idea_id = "recREPLACE_WITH_ACTUAL_ID"  # You'll need to set this

    # Or find an existing idea
    print("\n📋 Looking for ideas in Airtable...")

    # Try to find an idea ready for image prompts first
    ideas = pipeline.airtable.get_ideas_ready_for_image_prompts(limit=1)

    if not ideas:
        print("   No ideas found with 'Ready For Image Prompts' status.")
        print("   Checking for ideas with 'Ready For Voice' status to update...")

        # Look for Ready For Voice ideas and update them
        from pyairtable import Api
        api = Api(os.getenv("AIRTABLE_API_KEY"))
        ideas_table = api.table(os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE"), "tblrAsJglokZSkC8m")
        records = ideas_table.all(
            formula='{Status} = "Ready For Voice"',
            max_records=1,
        )

        if records:
            idea = {"id": records[0]["id"], **records[0]["fields"]}
            print(f"   Found: {idea.get('Video Title', 'Untitled')}")
            print("   Updating status to 'Ready For Image Prompts'...")
            pipeline.airtable.update_idea_status(idea["id"], "Ready For Image Prompts")
            ideas = [idea]

    if not ideas:
        print("\n❌ No ideas found to process. Please mark an idea as 'Ready For Image Prompts' in Airtable.")
        return

    idea = ideas[0]
    pipeline.video_title = idea.get("Video Title", "Untitled")
    pipeline.current_idea_id = idea.get("id")
    pipeline.project_folder_id = "1dF0p5iMgUa04oArBvAnHswHJKSckacmS"  # Your existing folder

    print(f"\n✅ Processing: {pipeline.video_title}")
    print(f"   Idea ID: {pipeline.current_idea_id}")

    try:
        # Step 1: Image Prompt Bot
        print("\n" + "=" * 40)
        print("🌉  STEP 1: IMAGE PROMPT BOT")
        print("=" * 40)
        prompt_result = await pipeline._run_image_prompt_bot()
        print(f"   ✅ Image prompts created: {prompt_result['prompt_count']}")

        # Update status to Ready for Images
        pipeline.airtable.update_idea_status(pipeline.current_idea_id, "Ready for Images")

        # Step 2: Image Bot
        print("\n" + "=" * 40)
        print("🖼️  STEP 2: IMAGE BOT")
        print("=" * 40)
        image_result = await pipeline._run_image_bot()
        print(f"   ✅ Images generated: {image_result['image_count']}")

        # Done!
        print("\n" + "=" * 60)
        print("🎉 IMAGE PIPELINE COMPLETE!")
        print("=" * 60)
        print(f"\n📁 Google Drive Folder: https://drive.google.com/drive/folders/{pipeline.project_folder_id}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
