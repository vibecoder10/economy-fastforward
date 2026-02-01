"""
Run the Script Bot on an idea marked "Ready For Scripting" in Airtable.
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
    print("🎬 RUNNING SCRIPT BOT")
    print("=" * 60)
    
    pipeline = VideoPipeline()
    
    # Run the script bot
    try:
        result = await pipeline.run_script_bot()
        
        print("\n" + "=" * 60)
        print("✅ SCRIPT BOT COMPLETE!")
        print("=" * 60)
        print(f"\n📁 Folder ID: {result['folder_id']}")
        print(f"📄 Doc URL: {result['doc_url']}")
        print(f"📝 Scenes written: {result['scene_count']}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
