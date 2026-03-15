"""Delete all image records for a video from the Airtable Images table."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from pyairtable import Api
from pyairtable.formulas import match
from pipeline_constants import ImageFields


def reset_visuals(video_title: str):
    print(f"🗑️ RESETTING VISUALS FOR: {video_title}")

    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    if not api_key or not base_id:
        print("❌ Missing AIRTABLE_API_KEY or AIRTABLE_BASE_ID")
        return

    api = Api(api_key)
    table = api.table(base_id, "tbl3luJ0zsWu0MYYz")  # Images table ID

    print("🔍 Searching for records...")
    records = table.all(
        formula=match({ImageFields.VIDEO_TITLE: video_title}),
        sort=[ImageFields.SCENE, ImageFields.IMAGE_INDEX],
    )
    print(f"Found {len(records)} records.")

    if not records:
        print("✅ No records to delete.")
        return

    ids = [r["id"] for r in records]
    print(f"🔥 Deleting {len(ids)} records...")

    batch_size = 10
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        table.batch_delete(batch)
        print(f"   Deleted batch {i + 1}-{i + len(batch)}")

    print("✅ Visuals reset complete!")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        title = " ".join(sys.argv[1:])
    else:
        print("Usage: python3 reset_visuals.py \"Video Title\"")
        sys.exit(1)
    reset_visuals(title)
