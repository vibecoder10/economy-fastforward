"""Check the Idea Concepts pipeline status."""

import os
import sys
import asyncio
import httpx
from dotenv import load_dotenv
from collections import Counter

load_dotenv()

BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
IDEA_CONCEPTS_TABLE_ID = os.getenv("AIRTABLE_IDEA_CONCEPTS_TABLE_ID", "tblrAsJglokZSkC8m")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")

# Pipeline status order for display
STATUS_ORDER = [
    "Idea Logged",
    "Approved",
    "Ready For Scripting",
    "Ready For Voice",
    "Ready For Image Prompts",
    "Ready For Images",
    "Ready For Video Scripts",
    "Ready For Video Generation",
    "Ready For Thumbnail",
    "Ready To Render",
    "In Que",
    "Done",
]


async def get_pipeline_status():
    """Show the current state of the Idea Concepts pipeline."""
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    }

    url = f"https://api.airtable.com/v0/{BASE_ID}/{IDEA_CONCEPTS_TABLE_ID}"

    # Fetch all ideas (limited fields for speed)
    params = {
        "fields[]": ["Video Title", "Status", "Source"],
    }

    all_records = []
    offset = None

    async with httpx.AsyncClient() as client:
        while True:
            if offset:
                params["offset"] = offset
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            all_records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break

    if not all_records:
        print("No ideas found in Idea Concepts table")
        return

    # Count by status
    status_counts = Counter()
    ideas_by_status = {}
    for r in all_records:
        fields = r.get("fields", {})
        status = fields.get("Status", "(no status)")
        title = fields.get("Video Title", "Untitled")
        status_counts[status] += 1
        ideas_by_status.setdefault(status, []).append(title)

    print("=" * 60)
    print("IDEA CONCEPTS PIPELINE STATUS")
    print("=" * 60)
    print(f"\nTotal ideas: {len(all_records)}\n")

    # Show counts in pipeline order
    shown = set()
    for status in STATUS_ORDER:
        count = status_counts.get(status, 0)
        if count > 0:
            print(f"  {status}: {count}")
            shown.add(status)

    # Show any statuses not in the standard order
    for status, count in sorted(status_counts.items()):
        if status not in shown:
            print(f"  {status}: {count}")

    # Show active ideas (non-terminal statuses)
    active_statuses = [s for s in STATUS_ORDER if s not in ("Done", "Idea Logged")]
    print("\n" + "=" * 60)
    print("ACTIVE IDEAS")
    print("=" * 60)

    found_active = False
    for status in active_statuses:
        titles = ideas_by_status.get(status, [])
        if titles:
            found_active = True
            print(f"\n  [{status}]")
            for t in titles:
                print(f"    - {t}")

    if not found_active:
        print("\n  No active ideas in the pipeline.")

    print()


asyncio.run(get_pipeline_status())
