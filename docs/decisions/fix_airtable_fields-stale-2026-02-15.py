#!/usr/bin/env python3
"""Fix Airtable Idea Concepts table: detect missing fields and create them.

Usage:
    AIRTABLE_API_KEY=patXXX python fix_airtable_fields.py

This script:
1. Lists every field the codebase writes to the Idea Concepts table
2. Fetches the actual Airtable schema via the metadata API
3. Creates any fields that exist in code but not in Airtable
4. Runs a test write (then deletes the test record) to confirm 422 errors are gone
"""

import os
import sys
import json
import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_KEY = os.getenv("AIRTABLE_API_KEY", "")
BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
# Idea Concepts table — fall back to legacy Ideas table if env not set
IDEA_CONCEPTS_TABLE_ID = os.getenv(
    "AIRTABLE_IDEA_CONCEPTS_TABLE_ID",
    os.getenv("AIRTABLE_IDEAS_TABLE_ID", "tblrAsJglokZSkC8m"),
)

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------------------------
# 1. Every field the code writes to Idea Concepts
#    (gathered from airtable_client.py, research_agent.py,
#     pipeline_control.py, pipeline_writer.py, trending_idea_bot.py)
# ---------------------------------------------------------------------------
CODE_FIELDS: dict[str, dict] = {
    # --- core fields (create_idea) ---
    "Status":             {"type": "singleSelect"},
    "Video Title":        {"type": "singleLineText"},
    "Hook Script":        {"type": "multilineText"},
    "Past Context":       {"type": "multilineText"},
    "Present Parallel":   {"type": "multilineText"},
    "Future Prediction":  {"type": "multilineText"},
    "Thumbnail Prompt":   {"type": "multilineText"},
    "Writer Guidance":    {"type": "multilineText"},
    "Original DNA":       {"type": "multilineText"},
    "Source":             {"type": "singleLineText"},
    # --- optional fields (create_idea) ---
    "Reference URL":      {"type": "url"},
    "Idea Reasoning":     {"type": "multilineText"},
    "Source Views":       {"type": "number", "options": {"precision": 0}},
    "Source Channel":     {"type": "singleLineText"},
    # --- research_agent.py / pipeline_control.py ---
    "Research Payload":   {"type": "multilineText"},
    "Thematic Framework": {"type": "singleLineText"},
    # --- pipeline_writer.py (graduate_to_pipeline) ---
    "Script":             {"type": "multilineText"},
    "Scene File Path":    {"type": "singleLineText"},
    "Accent Color":       {"type": "singleLineText"},
    "Video ID":           {"type": "singleLineText"},
    "Scene Count":        {"type": "number", "options": {"precision": 0}},
    "Validation Status":  {"type": "singleLineText"},
    # --- update_idea_thumbnail ---
    "Thumbnail":          {"type": "multipleAttachments"},
    "Thumbnail URL":      {"type": "url"},
}

# User-specified type overrides (from the issue)
USER_TYPE_OVERRIDES = {
    "Source":             {"type": "singleLineText"},
    "Research Payload":   {"type": "multilineText"},
    "Thematic Framework": {"type": "singleLineText"},
    "Hook Script":        {"type": "multilineText"},      # "Hook = long text"
}

# Apply overrides
for field_name, spec in USER_TYPE_OVERRIDES.items():
    if field_name in CODE_FIELDS:
        CODE_FIELDS[field_name].update(spec)


def fetch_table_schema(client: httpx.Client) -> dict:
    """Fetch the full base metadata and return the Idea Concepts table info."""
    url = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables"
    resp = client.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    tables = resp.json().get("tables", [])

    for table in tables:
        if table["id"] == IDEA_CONCEPTS_TABLE_ID:
            return table
        # Also match by name in case the env has a different ID
        if table.get("name", "").lower() in ("idea concepts", "ideas"):
            return table

    # If nothing matched by ID or name, dump available tables
    print("Available tables in base:")
    for t in tables:
        print(f"  {t['id']}  {t.get('name', '?')}")
    sys.exit(1)


def create_field(client: httpx.Client, table_id: str, name: str, spec: dict) -> dict:
    """Create a single field via the Airtable Fields API."""
    url = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables/{table_id}/fields"
    payload = {"name": name, "type": spec["type"]}
    if "options" in spec:
        payload["options"] = spec["options"]
    resp = client.post(url, headers=HEADERS, json=payload, timeout=30)
    if resp.status_code == 422:
        # Field might already exist with different casing or type conflict
        print(f"    422 creating '{name}': {resp.text}")
        return {}
    resp.raise_for_status()
    return resp.json()


def test_write(client: httpx.Client, table_id: str) -> str | None:
    """Write a test record and return its ID (or None on failure)."""
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_id}"
    test_fields = {
        "Video Title": "__TEST_RECORD_DELETE_ME__",
        "Hook Script": "Test hook script",
        "Source": "url_analysis",
        "Status": "Idea Logged",
        "Past Context": "test",
        "Present Parallel": "test",
        "Future Prediction": "test",
        "Thumbnail Prompt": "test",
        "Writer Guidance": "test",
        "Original DNA": "test",
        "Reference URL": "https://example.com",
        "Idea Reasoning": "test reasoning",
        "Research Payload": '{"test": true}',
        "Thematic Framework": "test framework",
        "Source Channel": "test_channel",
    }
    resp = client.post(
        url,
        headers=HEADERS,
        json={"fields": test_fields, "typecast": True},
        timeout=30,
    )
    if resp.status_code in (200, 201):
        record_id = resp.json()["id"]
        print(f"  Test record created: {record_id}")
        return record_id
    else:
        print(f"  Test write FAILED ({resp.status_code}): {resp.text}")
        return None


def delete_record(client: httpx.Client, table_id: str, record_id: str):
    """Delete a record by ID."""
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_id}/{record_id}"
    resp = client.delete(url, headers=HEADERS, timeout=30)
    if resp.status_code == 200:
        print(f"  Test record deleted: {record_id}")
    else:
        print(f"  Could not delete test record: {resp.status_code} {resp.text}")


def main():
    if not API_KEY:
        print("ERROR: Set AIRTABLE_API_KEY environment variable")
        sys.exit(1)

    print("=" * 60)
    print("Airtable Idea Concepts — Field Alignment Fix")
    print("=" * 60)

    with httpx.Client() as client:
        # --- Step 1: Fetch schema ---
        print("\n[1/4] Fetching Idea Concepts table schema ...")
        table = fetch_table_schema(client)
        table_id = table["id"]
        table_name = table.get("name", "?")
        existing_fields = {f["name"]: f for f in table.get("fields", [])}

        print(f"  Table: {table_name} ({table_id})")
        print(f"  Existing fields ({len(existing_fields)}):")
        for name in sorted(existing_fields):
            ftype = existing_fields[name].get("type", "?")
            print(f"    - {name}  ({ftype})")

        # --- Step 2: Compare ---
        print(f"\n[2/4] Fields the code writes ({len(CODE_FIELDS)}):")
        missing = {}
        present = {}
        for name, spec in sorted(CODE_FIELDS.items()):
            if name in existing_fields:
                present[name] = spec
                print(f"    OK   {name}")
            else:
                missing[name] = spec
                print(f"    MISS {name}  (need: {spec['type']})")

        if not missing:
            print("\n  All fields already exist — nothing to create.")
        else:
            print(f"\n  {len(missing)} field(s) missing from Airtable.")

        # --- Step 3: Create missing fields ---
        if missing:
            print(f"\n[3/4] Creating {len(missing)} missing field(s) ...")
            for name, spec in sorted(missing.items()):
                print(f"  Creating '{name}' ({spec['type']}) ...", end=" ")
                result = create_field(client, table_id, name, spec)
                if result:
                    print(f"OK  (id={result.get('id', '?')})")
                else:
                    print("FAILED (see above)")
        else:
            print("\n[3/4] No fields to create.")

        # --- Step 4: Test write ---
        print("\n[4/4] Running test write ...")
        record_id = test_write(client, table_id)
        if record_id:
            print("  SUCCESS — no 422 errors on write")
            delete_record(client, table_id, record_id)
        else:
            print("  FAILED — check error above")

    print("\nDone.")


if __name__ == "__main__":
    main()
