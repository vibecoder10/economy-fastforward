"""
Setup script to create required Airtable fields for semantic segmentation.

Run this once to add the new columns to your Images table:
    python setup_airtable_fields.py

Required fields for semantic segmentation:
- Visual Concept (text): Description of why this is a distinct visual segment
- Start Time (s) (number): Cumulative start time within scene for video stitching
- Duration (s) (number): How long this segment runs (should already exist)
- Sentence Text (long text): The narration text (should already exist)
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Airtable configuration
API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
IMAGES_TABLE_ID = "tbl3luJ0zsWu0MYYz"

# Airtable API endpoint for creating fields
FIELDS_URL = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables/{IMAGES_TABLE_ID}/fields"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# Fields to create for semantic segmentation
FIELDS_TO_CREATE = [
    {
        "name": "Visual Concept",
        "type": "singleLineText",
        "description": "Description of why this is a distinct visual segment (for semantic segmentation)",
    },
    {
        "name": "Start Time (s)",
        "type": "number",
        "options": {
            "precision": 1,  # One decimal place
        },
        "description": "Cumulative start time within scene (seconds) for video stitching",
    },
    {
        "name": "Duration (s)",
        "type": "number",
        "options": {
            "precision": 1,
        },
        "description": "Duration of this segment in seconds (max 10s for AI video generation)",
    },
    {
        "name": "Sentence Text",
        "type": "multilineText",
        "description": "The narration text for this segment (may contain multiple sentences)",
    },
    {
        "name": "Sentence Index",
        "type": "number",
        "options": {
            "precision": 0,  # Integer
        },
        "description": "Position within scene (1-based index)",
    },
]


def create_field(field_config: dict) -> dict:
    """Create a single field in the Images table."""
    response = requests.post(FIELDS_URL, headers=HEADERS, json=field_config)
    return response.status_code, response.json()


def main():
    if not API_KEY:
        print("❌ Error: AIRTABLE_API_KEY not found in environment")
        print("   Make sure you have a .env file with AIRTABLE_API_KEY set")
        return

    print("=" * 60)
    print("🔧 AIRTABLE FIELD SETUP for Semantic Segmentation")
    print("=" * 60)
    print(f"   Base ID: {BASE_ID}")
    print(f"   Table ID: {IMAGES_TABLE_ID}")
    print("=" * 60)

    for field in FIELDS_TO_CREATE:
        field_name = field["name"]
        print(f"\n📝 Creating field: {field_name}...")

        status_code, response = create_field(field)

        if status_code == 200:
            print(f"   ✅ Created successfully")
        elif status_code == 422 and "DUPLICATE_FIELD_NAME" in str(response):
            print(f"   ⏭️  Field already exists (skipping)")
        elif status_code == 422:
            # Field might already exist with different config
            print(f"   ⚠️  Field may already exist: {response.get('error', {}).get('message', 'Unknown error')}")
        else:
            print(f"   ❌ Error ({status_code}): {response}")

    print("\n" + "=" * 60)
    print("✅ Setup complete!")
    print("=" * 60)
    print("\nYour Images table should now have these fields:")
    print("  - Visual Concept (text)")
    print("  - Start Time (s) (number)")
    print("  - Duration (s) (number)")
    print("  - Sentence Text (long text)")
    print("  - Sentence Index (number)")
    print("\nYou can now run the pipeline with IMAGE_MODE=semantic")


if __name__ == "__main__":
    main()
