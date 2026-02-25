"""Setup script to create YouTube performance tracking fields on the Idea Concepts table.

Adds fields needed for the daily performance tracker (performance_tracker.py):
  - Lifetime stats: Views, Likes, Comments, Subscribers Gained
  - Analytics: Impressions, CTR, Avg View Duration, Avg Retention, Watch Time
  - Time-bucketed snapshots: Views 24h/48h/7d/30d, CTR 48h, Retention 48h
  - Metadata: Last Analytics Sync, Upload Date

Checks for existing fields first -- safe to run multiple times.

Usage:
    python setup_performance_fields.py
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
TABLE_ID = os.getenv(
    "AIRTABLE_IDEA_CONCEPTS_TABLE_ID",
    "tblrAsJglokZSkC8m",
)

HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json",
}

# Performance tracking fields to add to the Idea Concepts table
PERFORMANCE_FIELDS = [
    # --- Lifetime stats (updated daily) ---
    {"name": "Views", "type": "number", "options": {"precision": 0}},
    {"name": "Likes", "type": "number", "options": {"precision": 0}},
    {"name": "Comments", "type": "number", "options": {"precision": 0}},
    {"name": "Subscribers Gained", "type": "number", "options": {"precision": 0}},

    # --- Analytics (updated daily, requires YouTube Analytics API) ---
    {"name": "Impressions", "type": "number", "options": {"precision": 0}},
    {"name": "CTR (%)", "type": "number", "options": {"precision": 2}},
    {"name": "Avg View Duration (s)", "type": "number", "options": {"precision": 1}},
    {"name": "Avg Retention (%)", "type": "number", "options": {"precision": 1}},
    {"name": "Watch Time (hours)", "type": "number", "options": {"precision": 2}},

    # --- Time-bucketed snapshots (written once at each milestone) ---
    {"name": "Views 24h", "type": "number", "options": {"precision": 0}},
    {"name": "Views 48h", "type": "number", "options": {"precision": 0}},
    {"name": "Views 7d", "type": "number", "options": {"precision": 0}},
    {"name": "Views 30d", "type": "number", "options": {"precision": 0}},
    {"name": "CTR 48h (%)", "type": "number", "options": {"precision": 2}},
    {"name": "Retention 48h (%)", "type": "number", "options": {"precision": 1}},

    # --- Metadata ---
    {"name": "Last Analytics Sync", "type": "dateTime", "options": {"timeZone": "utc", "dateFormat": {"name": "iso"}}},
    {"name": "Upload Date", "type": "dateTime", "options": {"timeZone": "utc", "dateFormat": {"name": "iso"}}},
]


def get_existing_fields(table_id: str = TABLE_ID) -> set[str]:
    """Fetch all existing field names on a table."""
    url = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()

    for table in resp.json().get("tables", []):
        if table["id"] == table_id or table["name"] == table_id:
            return {f["name"] for f in table.get("fields", [])}

    print(f"Table {table_id} not found in base {BASE_ID}")
    sys.exit(1)


def create_field(field_def: dict, table_id: str = TABLE_ID) -> bool:
    """Create a single field on a table. Returns True on success."""
    url = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables/{table_id}/fields"
    resp = requests.post(url, headers=HEADERS, json=field_def)

    if resp.status_code == 200:
        print(f"  + Created: {field_def['name']} ({field_def['type']})")
        return True
    else:
        print(f"  ! Failed to create {field_def['name']}: {resp.status_code} {resp.text}")
        return False


def main():
    if not AIRTABLE_API_KEY:
        print("AIRTABLE_API_KEY not set. Add it to .env and re-run.")
        sys.exit(1)

    print(f"Base: {BASE_ID}")
    print(f"\n{'=' * 50}")
    print(f"Table: Idea Concepts ({TABLE_ID})")
    print("Adding YouTube Performance Tracking Fields")
    print(f"{'=' * 50}")

    existing = get_existing_fields(TABLE_ID)
    print(f"Existing fields ({len(existing)}): {sorted(existing)}\n")

    created = 0
    skipped = 0
    failed = 0

    for field_def in PERFORMANCE_FIELDS:
        if field_def["name"] in existing:
            print(f"  = Exists: {field_def['name']}")
            skipped += 1
        else:
            if create_field(field_def, TABLE_ID):
                created += 1
            else:
                failed += 1

    print(f"\n  Result: {created} created, {skipped} existed, {failed} failed")
    print(f"\n{'=' * 50}")
    print("Performance tracking fields configured.")
    print("Run performance_tracker.py to start collecting data.")


if __name__ == "__main__":
    main()
