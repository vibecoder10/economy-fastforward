"""
Run the remaining pipeline: Voice → Image Prompts → Images
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
    print("🎬 RUNNING REMAINING PIPELINE")
    print("   Voice → Image Prompts → Images")
    print("=" * 60)
    
    pipeline = VideoPipeline()
    
    # Set the folder ID from the previous script bot run
    pipeline.project_folder_id = "1dF0p5iMgUa04oArBvAnHswHJKSckacmS"
    pipeline.video_title = "Why AI's \"Fake Bubble\" Will Make You RICH"
    
    try:
        # Step 1: Voice Bot
        print("\n" + "=" * 40)
        print("🗣️  STEP 1: VOICE BOT")
        print("=" * 40)
        voice_result = await pipeline.run_voice_bot()
        print(f"   ✅ Voice overs generated: {voice_result['voice_count']}")
        
        # Step 2: Image Prompt Bot
        print("\n" + "=" * 40)
        print("🌉  STEP 2: IMAGE PROMPT BOT")
        print("=" * 40)
        prompt_result = await pipeline.run_image_prompt_bot()
        print(f"   ✅ Image prompts created: {prompt_result['prompt_count']}")
        
        # Step 3: Image Bot
        print("\n" + "=" * 40)
        print("🖼️  STEP 3: IMAGE BOT")
        print("=" * 40)
        image_result = await pipeline.run_image_bot()
        print(f"   ✅ Images generated: {image_result['image_count']}")
        
        # Done!
        print("\n" + "=" * 60)
        print("🎉 PIPELINE COMPLETE!")
        print("=" * 60)
        print(f"\n📁 Google Drive Folder: https://drive.google.com/drive/folders/{pipeline.project_folder_id}")
        print(f"📄 All assets ready for video editing!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
