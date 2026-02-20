"""Setup script to create required fields on the Idea Concepts table.

Run this once to add rich schema fields that match the Ideas Bank.
Checks for existing fields first — safe to run multiple times.

Usage:
    python setup_airtable_fields.py
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

# Fields to add to the Idea Concepts table
REQUIRED_FIELDS = [
    {
        "name": "Framework Angle",
        "type": "singleSelect",
        "options": {
            "choices": [
                {"name": "48 Laws"},
                {"name": "Machiavelli"},
                {"name": "Sun Tzu"},
                {"name": "Game Theory"},
                {"name": "Jung Shadow"},
                {"name": "Behavioral Econ"},
                {"name": "Stoicism"},
                {"name": "Propaganda"},
                {"name": "Systems Thinking"},
                {"name": "Evolutionary Psych"},
            ]
        },
    },
    {
        "name": "Headline",
        "type": "singleLineText",
    },
    {
        "name": "Timeliness Score",
        "type": "number",
        "options": {"precision": 0},
    },
    {
        "name": "Audience Fit Score",
        "type": "number",
        "options": {"precision": 0},
    },
    {
        "name": "Content Gap Score",
        "type": "number",
        "options": {"precision": 0},
    },
    {
        "name": "Monetization Risk",
        "type": "singleSelect",
        "options": {
            "choices": [
                {"name": "low"},
                {"name": "medium"},
                {"name": "high"},
            ]
        },
    },
    {
        "name": "Source URLs",
        "type": "multilineText",
    },
    {
        "name": "Executive Hook",
        "type": "multilineText",
    },
    {
        "name": "Thesis",
        "type": "multilineText",
    },
    {
        "name": "Date Surfaced",
        "type": "date",
        "options": {"dateFormat": {"name": "iso"}},
    },
    # Additional fields the pipeline needs
    {
        "name": "Research Payload",
        "type": "multilineText",
    },
    {
        "name": "Thematic Framework",
        "type": "multilineText",
    },
]

# Fields to add to the Script table
SCRIPT_TABLE_ID = os.getenv("AIRTABLE_SCRIPT_TABLE_ID", "tbluGSepeZNgb0NxG")
SCRIPT_REQUIRED_FIELDS = [
    {
        "name": "Sources",
        "type": "multilineText",
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


def setup_table(table_id: str, table_name: str, fields: list[dict]):
    """Set up fields on a single table."""
    print(f"\n{'=' * 50}")
    print(f"Table: {table_name} ({table_id})")
    print(f"{'=' * 50}")

    existing = get_existing_fields(table_id)
    print(f"Existing fields ({len(existing)}): {sorted(existing)}\n")

    created = 0
    skipped = 0
    failed = 0

    for field_def in fields:
        if field_def["name"] in existing:
            print(f"  = Exists: {field_def['name']}")
            skipped += 1
        else:
            if create_field(field_def, table_id):
                created += 1
            else:
                failed += 1

    print(f"\n  Result: {created} created, {skipped} existed, {failed} failed")
    return created, skipped, failed


def main():
    if not AIRTABLE_API_KEY:
        print("AIRTABLE_API_KEY not set. Add it to .env and re-run.")
        sys.exit(1)

    print(f"Base: {BASE_ID}")

    # Setup Idea Concepts table
    setup_table(TABLE_ID, "Idea Concepts", REQUIRED_FIELDS)

    # Setup Script table (Sources field)
    setup_table(SCRIPT_TABLE_ID, "Script", SCRIPT_REQUIRED_FIELDS)

    print(f"\n{'=' * 50}")
    print("All tables configured.")


if __name__ == "__main__":
    main()
