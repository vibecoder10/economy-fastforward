#!/usr/bin/env python3
"""Setup script for Curiosity Gap Airtable fields.

Run this script to verify all required fields exist in the Ideas table.
Fields that don't exist will be listed for manual creation.

Usage:
    python setup_curiosity_gap_fields.py --check
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from pyairtable import Api

# Required fields for curiosity gap learning
REQUIRED_FIELDS = {
    # Single Select fields
    "Curiosity Structure": {
        "type": "singleSelect",
        "options": ["hidden_flaw", "asymmetric_dg", "time_bomb", "paradigm_shift", "illusion_control", "other"],
    },
    "Thumbnail Approach": {
        "type": "singleSelect",
        "options": ["from_hook", "from_gap"],
    },
    "Title Poll Result": {
        "type": "singleSelect",
        "options": ["human_selected", "auto_selected"],
    },

    # Number fields
    "Structure Confidence": {"type": "number"},
    "CTR 12h (%)": {"type": "number"},
    "CTR 24h (%)": {"type": "number"},
    "CTR 48h (%)": {"type": "number"},

    # Text fields
    "Thumbnail Text": {"type": "singleLineText"},
    "Structure Source": {"type": "multilineText"},
    "Pattern Library Snapshot": {"type": "multilineText"},

    # Checkbox
    "Poll Closed": {"type": "checkbox"},
}


def check_fields():
    """Check which fields exist in Ideas table."""
    api = Api(os.environ["AIRTABLE_API_KEY"])
    base = api.base(os.environ["AIRTABLE_BASE_ID"])
    table = base.table(os.environ.get("AIRTABLE_IDEAS_TABLE_ID", "Ideas"))

    print("Checking Ideas table fields...\n")

    # Try to read one record to get field names
    records = table.all(max_records=1)
    if records:
        existing_fields = set(records[0].get("fields", {}).keys())
    else:
        existing_fields = set()

    missing = []
    found = []

    for field_name, field_spec in REQUIRED_FIELDS.items():
        if field_name in existing_fields:
            found.append(field_name)
        else:
            missing.append((field_name, field_spec))

    print(f"Found {len(found)} fields:")
    for f in found:
        print(f"  [x] {f}")

    if missing:
        print(f"\nMissing {len(missing)} fields:")
        for name, spec in missing:
            print(f"  [ ] {name} ({spec['type']})")
            if spec.get("options"):
                print(f"      Options: {', '.join(spec['options'])}")

        print("\nPlease create these fields in Airtable before proceeding.")
        return False

    print("\nAll required fields exist!")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Setup Curiosity Gap Airtable fields")
    parser.add_argument("--check", action="store_true", help="Check which fields exist")
    args = parser.parse_args()

    if args.check:
        success = check_fields()
        sys.exit(0 if success else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
