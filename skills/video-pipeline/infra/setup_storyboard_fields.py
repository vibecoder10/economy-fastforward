"""Setup script to create storyboard fields on the Scripts table.

Run this once to add storyboard mode and related fields.
Checks for existing fields first — safe to run multiple times.

Usage:
    python setup_storyboard_fields.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
SCRIPT_TABLE_ID = os.getenv("AIRTABLE_SCRIPT_TABLE_ID", "tbluGSepeZNgb0NxG")

HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json",
}

# Storyboard fields to add to the Scripts table
STORYBOARD_FIELDS = [
    {
        "name": "Story Board On/OFF",
        "type": "singleSelect",
        "options": {
            "choices": [
                {"name": "On"},
                {"name": "Off"},
            ]
        },
    },
    {
        "name": "Storyboard Prompts",
        "type": "multilineText",
    },
    {
        "name": "Storyboard 1",
        "type": "multipleAttachments",
    },
    {
        "name": "Storyboard 2",
        "type": "multipleAttachments",
    },
    {
        "name": "Storyboard 3",
        "type": "multipleAttachments",
    },
]


def get_existing_fields(table_id: str) -> set[str]:
    """Fetch all existing field names on a table."""
    url = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()

    for table in resp.json().get("tables", []):
        if table["id"] == table_id or table["name"] == table_id:
            return {f["name"] for f in table.get("fields", [])}

    print(f"Table {table_id} not found in base {BASE_ID}")
    sys.exit(1)


def create_field(field_def: dict, table_id: str) -> bool:
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
    print(f"Scripts Table: {SCRIPT_TABLE_ID}")
    print("=" * 50)

    existing = get_existing_fields(SCRIPT_TABLE_ID)
    print(f"Existing fields ({len(existing)}): {sorted(existing)}\n")

    created = 0
    skipped = 0
    failed = 0

    for field_def in STORYBOARD_FIELDS:
        if field_def["name"] in existing:
            print(f"  = Exists: {field_def['name']}")
            skipped += 1
        else:
            if create_field(field_def, SCRIPT_TABLE_ID):
                created += 1
            else:
                failed += 1

    print(f"\n{'=' * 50}")
    print(f"Result: {created} created, {skipped} existed, {failed} failed")
    print("=" * 50)


if __name__ == "__main__":
    main()
