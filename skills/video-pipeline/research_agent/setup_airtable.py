#!/usr/bin/env python3
"""
Airtable Setup Script for Research Intelligence Agent

This script:
1. Verifies your Airtable API connection
2. Checks if the Ideas Bank table exists
3. Creates it if possible (requires Metadata API access)
4. Creates a test record to verify field schema
5. Optionally deletes the test record

Usage:
    cd /Users/ryanayler/economy-fastforward/skills/video-pipeline
    python -m research_agent.setup_airtable
"""

import os
import sys
import json
import requests
from datetime import date

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))


# ============================================================
# IDEAS BANK TABLE SCHEMA
# ============================================================

IDEAS_BANK_SCHEMA = {
    "name": "Ideas Bank",
    "description": "Research Intelligence Agent - Video topic candidates and deep dive research",
    "fields": [
        # Core identification
        {"name": "Headline", "type": "singleLineText", "description": "One-line topic description"},

        # Scoring fields
        {"name": "Source Category", "type": "singleSelect", "options": {
            "choices": [
                {"name": "breaking_news", "color": "redLight2"},
                {"name": "geopolitical", "color": "blueLight2"},
                {"name": "psychology_trend", "color": "purpleLight2"},
                {"name": "competitor_gap", "color": "orangeLight2"},
                {"name": "economic", "color": "greenLight2"},
                {"name": "ai_tech", "color": "cyanLight2"},
            ]
        }},
        {"name": "Timeliness Score", "type": "number", "options": {"precision": 0}},
        {"name": "Audience Fit Score", "type": "number", "options": {"precision": 0}},
        {"name": "Content Gap Score", "type": "number", "options": {"precision": 0}},

        # Composite Score is a FORMULA - do not include, create manually

        # Framework and analysis
        {"name": "Framework Angle", "type": "singleSelect", "options": {
            "choices": [
                {"name": "Machiavelli", "color": "redLight2"},
                {"name": "48 Laws", "color": "orangeLight2"},
                {"name": "Jung Shadow", "color": "purpleLight2"},
                {"name": "Game Theory", "color": "blueLight2"},
                {"name": "Sun Tzu", "color": "greenLight2"},
                {"name": "Behavioral Econ", "color": "cyanLight2"},
                {"name": "Stoicism", "color": "grayLight2"},
                {"name": "Systems Thinking", "color": "pinkLight2"},
                {"name": "Propaganda", "color": "yellowLight2"},
                {"name": "Evolutionary Psych", "color": "tealLight2"},
            ]
        }},
        {"name": "Competitor Coverage", "type": "multilineText"},
        {"name": "Source URLs", "type": "multilineText"},

        # Status tracking
        {"name": "Status", "type": "singleSelect", "options": {
            "choices": [
                {"name": "candidate", "color": "grayLight2"},
                {"name": "selected", "color": "blueLight2"},
                {"name": "researched", "color": "greenLight2"},
                {"name": "sent_to_pipeline", "color": "purpleLight2"},
                {"name": "backlog", "color": "yellowLight2"},
                {"name": "rejected", "color": "redLight2"},
            ]
        }},

        # Deep dive fields
        {"name": "Executive Hook", "type": "multilineText"},
        {"name": "Thesis", "type": "singleLineText"},
        {"name": "Fact Sheet", "type": "multilineText"},
        {"name": "Historical Parallels", "type": "multilineText"},
        {"name": "Framework Analysis", "type": "multilineText"},
        {"name": "Character Dossier", "type": "multilineText"},
        {"name": "Narrative Arc", "type": "multilineText"},
        {"name": "Counter Arguments", "type": "multilineText"},
        {"name": "Visual Seeds", "type": "multilineText"},
        {"name": "Title Options", "type": "multilineText"},
        {"name": "Thumbnail Concepts", "type": "multilineText"},
        {"name": "Source Bibliography", "type": "multilineText"},

        # Metadata
        {"name": "Date Surfaced", "type": "date"},
        {"name": "Date Deep Dived", "type": "date"},
        {"name": "Evergreen Flag", "type": "checkbox"},
        {"name": "Monetization Risk", "type": "singleSelect", "options": {
            "choices": [
                {"name": "low", "color": "greenLight2"},
                {"name": "medium", "color": "yellowLight2"},
                {"name": "high", "color": "redLight2"},
            ]
        }},
        {"name": "Notes", "type": "multilineText"},
    ]
}


def get_env_vars():
    """Get required environment variables."""
    api_key = os.getenv("AIRTABLE_PAT") or os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
    return api_key, base_id


def test_api_connection(api_key: str, base_id: str) -> bool:
    """Test basic API connection by listing tables."""
    print("\n1. Testing Airtable API connection...")

    # Try to access the base metadata
    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            tables = response.json().get("tables", [])
            print(f"   [OK] Connected to base {base_id}")
            print(f"   [OK] Found {len(tables)} existing table(s):")
            for t in tables:
                print(f"        - {t['name']} ({t['id']})")
            return True
        elif response.status_code == 403:
            print("   [WARN] Metadata API access denied (normal for standard tokens)")
            print("         Will try direct table access instead...")
            return True  # Continue with direct access test
        elif response.status_code == 401:
            print("   [FAIL] Invalid API key")
            return False
        else:
            print(f"   [FAIL] API error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"   [FAIL] Connection error: {e}")
        return False


def check_ideas_bank_exists(api_key: str, base_id: str) -> bool:
    """Check if Ideas Bank table exists by trying to read from it."""
    print("\n2. Checking for Ideas Bank table...")

    url = f"https://api.airtable.com/v0/{base_id}/Ideas%20Bank"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    params = {"maxRecords": 1}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)

        if response.status_code == 200:
            records = response.json().get("records", [])
            print(f"   [OK] Ideas Bank table exists ({len(records)} record(s) found)")
            return True
        elif response.status_code == 404:
            print("   [NOT FOUND] Ideas Bank table does not exist")
            return False
        else:
            print(f"   [ERROR] {response.status_code}: {response.text}")
            return False

    except Exception as e:
        print(f"   [ERROR] {e}")
        return False


def create_ideas_bank_table(api_key: str, base_id: str) -> bool:
    """Attempt to create the Ideas Bank table using Metadata API."""
    print("\n3. Attempting to create Ideas Bank table...")

    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=IDEAS_BANK_SCHEMA, timeout=30)

        if response.status_code == 200:
            table_data = response.json()
            print(f"   [OK] Created Ideas Bank table: {table_data.get('id')}")
            return True
        elif response.status_code == 403:
            print("   [BLOCKED] Your Airtable token doesn't have Metadata API access")
            print("            This is normal for standard Personal Access Tokens.")
            print("            You'll need to create the table manually (see below).")
            return False
        elif response.status_code == 422:
            error = response.json()
            if "already exists" in str(error).lower():
                print("   [OK] Table already exists")
                return True
            print(f"   [ERROR] Validation error: {error}")
            return False
        else:
            print(f"   [ERROR] {response.status_code}: {response.text}")
            return False

    except Exception as e:
        print(f"   [ERROR] {e}")
        return False


def create_test_record(api_key: str, base_id: str) -> str:
    """Create a test record to verify field schema."""
    print("\n4. Creating test record to verify schema...")

    url = f"https://api.airtable.com/v0/{base_id}/Ideas%20Bank"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    test_record = {
        "records": [{
            "fields": {
                "Headline": "[TEST] Delete this record - Research Agent setup verification",
                "Source Category": "breaking_news",
                "Timeliness Score": 5,
                "Audience Fit Score": 5,
                "Content Gap Score": 5,
                "Framework Angle": "48 Laws",
                "Status": "candidate",
                "Date Surfaced": date.today().isoformat(),
                "Monetization Risk": "low",
                "Evergreen Flag": False,
                "Notes": "This is a test record created by setup_airtable.py. Safe to delete.",
            }
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=test_record, timeout=10)

        if response.status_code == 200:
            record = response.json()["records"][0]
            record_id = record["id"]
            print(f"   [OK] Test record created: {record_id}")
            print("        All core fields validated successfully!")
            return record_id
        elif response.status_code == 422:
            error = response.json()
            print(f"   [FAIL] Field validation error:")
            print(f"          {json.dumps(error, indent=2)}")
            print("\n   This usually means a field is missing or misconfigured.")
            print("   Check the field names match exactly (case-sensitive).")
            return None
        elif response.status_code == 404:
            print("   [FAIL] Ideas Bank table not found")
            return None
        else:
            print(f"   [FAIL] {response.status_code}: {response.text}")
            return None

    except Exception as e:
        print(f"   [FAIL] {e}")
        return None


def delete_test_record(api_key: str, base_id: str, record_id: str) -> bool:
    """Delete the test record."""
    url = f"https://api.airtable.com/v0/{base_id}/Ideas%20Bank/{record_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.delete(url, headers=headers, timeout=10)
        if response.status_code == 200:
            print(f"   [OK] Test record deleted")
            return True
        else:
            print(f"   [WARN] Could not delete test record: {response.status_code}")
            return False
    except Exception as e:
        print(f"   [WARN] Could not delete test record: {e}")
        return False


def print_manual_creation_instructions():
    """Print instructions for manually creating the Ideas Bank table."""
    print("""
================================================================================
MANUAL TABLE CREATION INSTRUCTIONS
================================================================================

Your Airtable token doesn't have Metadata API access (this is normal).
Please create the "Ideas Bank" table manually in your Airtable base.

STEP 1: Open your Airtable base
   https://airtable.com/appCIcC58YSTwK3CE

STEP 2: Click "+ Add or import" → "Create blank table"

STEP 3: Name it exactly: Ideas Bank

STEP 4: Add these fields (click + to add each field):

   FIELD NAME              TYPE              OPTIONS
   ─────────────────────────────────────────────────────────────────────
   Headline                Single line text  (default, just rename)
   Source Category         Single select     Options: breaking_news, geopolitical,
                                             psychology_trend, competitor_gap,
                                             economic, ai_tech
   Timeliness Score        Number            Integer
   Audience Fit Score      Number            Integer
   Content Gap Score       Number            Integer
   Composite Score         Formula           (Timeliness Score * 0.3) +
                                             (Audience Fit Score * 0.4) +
                                             (Content Gap Score * 0.3)
   Framework Angle         Single select     Options: Machiavelli, 48 Laws,
                                             Jung Shadow, Game Theory, Sun Tzu,
                                             Behavioral Econ, Stoicism,
                                             Systems Thinking, Propaganda,
                                             Evolutionary Psych
   Competitor Coverage     Long text
   Source URLs             Long text
   Status                  Single select     Options: candidate, selected,
                                             researched, sent_to_pipeline,
                                             backlog, rejected
   Executive Hook          Long text
   Thesis                  Single line text
   Fact Sheet              Long text
   Historical Parallels    Long text
   Framework Analysis      Long text
   Character Dossier       Long text
   Narrative Arc           Long text
   Counter Arguments       Long text
   Visual Seeds            Long text
   Title Options           Long text
   Thumbnail Concepts      Long text
   Source Bibliography     Long text
   Date Surfaced           Date
   Date Deep Dived         Date
   Evergreen Flag          Checkbox
   Monetization Risk       Single select     Options: low, medium, high
   Notes                   Long text

STEP 5: After creating the table, run this script again to verify:
   python -m research_agent.setup_airtable

================================================================================
""")


def main():
    """Main setup flow."""
    print("=" * 70)
    print("RESEARCH INTELLIGENCE AGENT - AIRTABLE SETUP")
    print("=" * 70)

    # Get API credentials
    api_key, base_id = get_env_vars()

    if not api_key:
        print("\n[ERROR] No Airtable API key found!")
        print("\nAdd one of these to your .env file:")
        print("   AIRTABLE_PAT=pat_xxxxxxxxxxxx")
        print("   AIRTABLE_API_KEY=pat_xxxxxxxxxxxx")
        print("\nGet a token at: https://airtable.com/create/tokens")
        print("Required scopes: data.records:read, data.records:write")
        print("               + schema.bases:read (optional, for table creation)")
        return False

    print(f"\nUsing base ID: {base_id}")
    print(f"API key: {api_key[:10]}...{api_key[-4:]}")

    # Test connection
    if not test_api_connection(api_key, base_id):
        return False

    # Check if Ideas Bank exists
    table_exists = check_ideas_bank_exists(api_key, base_id)

    if not table_exists:
        # Try to create it
        created = create_ideas_bank_table(api_key, base_id)

        if not created:
            print_manual_creation_instructions()
            return False

    # Verify schema with test record
    test_record_id = create_test_record(api_key, base_id)

    if test_record_id:
        # Ask to delete test record
        print("\n5. Cleanup...")
        delete_test_record(api_key, base_id, test_record_id)

        print("\n" + "=" * 70)
        print("[SUCCESS] Ideas Bank table is configured correctly!")
        print("=" * 70)
        print("\nYou can now run the research scanner:")
        print("   python -m research_agent.run_scan --dry-run")
        return True
    else:
        print("\n" + "=" * 70)
        print("[INCOMPLETE] Table exists but schema verification failed")
        print("=" * 70)
        print("\nCheck that all field names match exactly (case-sensitive).")
        print("See the MANUAL TABLE CREATION INSTRUCTIONS above for the schema.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
