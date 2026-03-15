import os
from dotenv import load_dotenv
from pyairtable.formulas import match, AND
from pyairtable import Table
from pipeline_constants import ImageFields

def verify_prompts(video_title):
    print(f"🔍 VERIFYING PROMPTS FOR: {video_title}")
    
    load_dotenv('../../.env')
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    
    # Connect (using Table class directly for simplicity)
    table = Table(api_key, base_id, "Images")
    
    # Get Scene 1 prompts
    records = table.all(
        formula=AND(
            match({ImageFields.VIDEO_TITLE: video_title}),
            match({ImageFields.SCENE: 1})
        )
    )
    
    if not records:
        print("❌ No prompts found yet for Scene 1.")
        return

    print(f"✅ Found {len(records)} prompts for Scene 1:\n")
    for r in records:
        print(f"--- Prompt {r['fields'].get(ImageFields.IMAGE_INDEX)} ---")
        print(r['fields'].get(ImageFields.IMAGE_PROMPT))
        print()

if __name__ == "__main__":
    title = "The 2030 Currency Collapse: Which Assets Will YOU Still Own?"
    verify_prompts(title)
