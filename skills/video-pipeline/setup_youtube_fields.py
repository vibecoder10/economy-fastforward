"""Setup script to create YouTube pipeline fields on the Idea Concepts table.

Adds fields needed for the YouTube auto-upload pipeline:
  - Drive Folder Link/ID (set during script creation)
  - Final Video URL (set after render)
  - SEO Description, Tags, Hashtags (set before upload)
  - YouTube Video ID, URL, Upload Status (set after upload)

Also adds new Status values: Ready to Render, Rendered, Uploaded (Draft).

Checks for existing fields first -- safe to run multiple times.

Usage:
    python setup_youtube_fields.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env'))

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

# YouTube pipeline fields to add to the Idea Concepts table
YOUTUBE_FIELDS = [
    {
        "name": "Drive Folder Link",
        "type": "url",
    },
    {
        "name": "Drive Folder ID",
        "type": "singleLineText",
    },
    {
        "name": "Final Video URL",
        "type": "url",
    },
    {
        "name": "SEO Description",
        "type": "multilineText",
    },
    {
        "name": "SEO Tags",
        "type": "multilineText",
    },
    {
        "name": "SEO Hashtags",
        "type": "multilineText",
    },
    {
        "name": "YouTube Video ID",
        "type": "singleLineText",
    },
    {
        "name": "YouTube URL",
        "type": "url",
    },
    {
        "name": "Upload Status",
        "type": "singleSelect",
        "options": {
            "choices": [
                {"name": "pending"},
                {"name": "uploading"},
                {"name": "uploaded"},
                {"name": "failed"},
            ]
        },
    },
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


def add_status_choices(table_id: str = TABLE_ID):
    """Add new Status choices (Ready to Render, Rendered, Uploaded (Draft)).

    The Status field already exists as a singleSelect. We fetch the current
    choices and add any missing ones.
    """
    print("\nAdding new Status choices...")

    # Get current table schema to find the Status field
    url = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()

    status_field = None
    for table in resp.json().get("tables", []):
        if table["id"] == table_id or table["name"] == table_id:
            for field in table.get("fields", []):
                if field["name"] == "Status":
                    status_field = field
                    break
            break

    if not status_field:
        print("  ! Status field not found -- cannot add choices")
        return

    existing_choices = {
        c["name"] for c in status_field.get("options", {}).get("choices", [])
    }
    new_statuses = ["Ready to Render", "Rendered", "Uploaded (Draft)"]
    to_add = [s for s in new_statuses if s not in existing_choices]

    if not to_add:
        print("  = All status choices already exist")
        return

    # Build full choices list (existing + new)
    all_choices = list(status_field.get("options", {}).get("choices", []))
    for status_name in to_add:
        all_choices.append({"name": status_name})

    # Update the field
    field_id = status_field["id"]
    update_url = (
        f"https://api.airtable.com/v0/meta/bases/{BASE_ID}"
        f"/tables/{table_id}/fields/{field_id}"
    )
    payload = {
        "name": "Status",
        "options": {"choices": all_choices},
    }
    resp = requests.patch(update_url, headers=HEADERS, json=payload)
    if resp.status_code == 200:
        for s in to_add:
            print(f"  + Added status choice: {s}")
    else:
        print(f"  ! Failed to update Status choices: {resp.status_code} {resp.text}")


def main():
    if not AIRTABLE_API_KEY:
        print("AIRTABLE_API_KEY not set. Add it to .env and re-run.")
        sys.exit(1)

    print(f"Base: {BASE_ID}")
    print(f"\n{'=' * 50}")
    print(f"Table: Idea Concepts ({TABLE_ID})")
    print(f"{'=' * 50}")

    existing = get_existing_fields(TABLE_ID)
    print(f"Existing fields ({len(existing)}): {sorted(existing)}\n")

    created = 0
    skipped = 0
    failed = 0

    for field_def in YOUTUBE_FIELDS:
        if field_def["name"] in existing:
            print(f"  = Exists: {field_def['name']}")
            skipped += 1
        else:
            if create_field(field_def, TABLE_ID):
                created += 1
            else:
                failed += 1

    print(f"\n  Result: {created} created, {skipped} existed, {failed} failed")

    # Add new status choices
    add_status_choices(TABLE_ID)

    print(f"\n{'=' * 50}")
    print("YouTube pipeline fields configured.")


if __name__ == "__main__":
    main()
