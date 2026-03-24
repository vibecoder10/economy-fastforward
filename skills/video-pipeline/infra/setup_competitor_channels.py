"""
Setup Competitor Channels Table in Airtable.

Creates the Competitor Channels table with the required fields for
competitor video scraping integration with the discovery scanner.

Required fields:
  - Channel Name (Single Line Text) - Name of the competitor channel
  - Channel URL (URL) - YouTube channel URL
  - Category (Single Select) - Channel category (e.g., Geopolitics, Finance, Economy)
  - Active (Checkbox) - Include in discovery scraping
  - Last Scraped (Date) - Auto-updated when channel is scraped
  - Notes (Long Text) - Optional notes about the channel

Usage:
    1. Create the table manually in Airtable with name "Competitor Channels"
    2. Add the table ID to .env as AIRTABLE_COMPETITOR_CHANNELS_TABLE_ID
    3. Run this script to verify the setup

    python setup_competitor_channels.py

Or just verify manually that your table has these columns.

Example competitor channels to add:
  - CaspianReport (https://www.youtube.com/@CaspianReport) - Geopolitics
  - AiTelly (https://www.youtube.com/@AiTelly) - Geopolitics/Finance
  - PolyMatter (https://www.youtube.com/@PolyMatter) - Economics
  - Economics Explained (https://www.youtube.com/@EconomicsExplained) - Economics
  - TLDR News (https://www.youtube.com/@TLDRNews) - Current Events
"""

import os
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()


def verify_setup():
    """Verify Competitor Channels table is set up correctly."""
    from clients.airtable_client import AirtableClient

    print("=" * 60)
    print("COMPETITOR CHANNELS TABLE SETUP")
    print("=" * 60)

    # Check env var
    table_id = os.getenv("AIRTABLE_COMPETITOR_CHANNELS_TABLE_ID")
    if not table_id or table_id == "tblXXXXXXXXXXXXXX":
        print("\n  ERROR: AIRTABLE_COMPETITOR_CHANNELS_TABLE_ID not set in .env")
        print("\n  To fix:")
        print("    1. Create a table called 'Competitor Channels' in your Airtable base")
        print("    2. Copy the table ID from the URL (starts with 'tbl')")
        print("    3. Add to .env: AIRTABLE_COMPETITOR_CHANNELS_TABLE_ID=tblYOUR_TABLE_ID")
        print("\n  Required columns:")
        print("    - Channel Name (Single Line Text)")
        print("    - Channel URL (URL)")
        print("    - Category (Single Select: Geopolitics, Finance, Economy, Tech)")
        print("    - Active (Checkbox)")
        print("    - Last Scraped (Date)")
        print("    - Notes (Long Text)")
        return False

    print(f"\n  Table ID: {table_id}")

    try:
        airtable = AirtableClient()

        # Try to fetch channels
        channels = airtable.get_active_competitor_channels()
        print(f"\n  Found {len(channels)} active competitor channels")

        if channels:
            print("\n  Active channels:")
            for ch in channels:
                name = ch.get("Channel Name", "?")
                url = ch.get("Channel URL", "?")
                category = ch.get("Category", "?")
                last_scraped = ch.get("Last Scraped", "Never")
                print(f"    - {name} ({category}) - Last scraped: {last_scraped}")
                print(f"      {url}")
        else:
            print("\n  No active channels found. Add some channels to get started:")
            print("    1. Go to your Competitor Channels table in Airtable")
            print("    2. Add competitor channel URLs")
            print("    3. Check the 'Active' checkbox for channels to include")

        # Try to update Last Scraped (tests write access)
        if channels:
            test_record = channels[0]
            print(f"\n  Testing write access with '{test_record.get('Channel Name')}'...")
            try:
                airtable.update_channel_last_scraped(test_record["id"])
                print("    Write access: OK")
            except Exception as e:
                print(f"    Write access: FAILED - {e}")

        print("\n  SETUP VERIFIED")
        return True

    except Exception as e:
        print(f"\n  ERROR: {e}")
        print("\n  Make sure:")
        print("    1. The table exists in your Airtable base")
        print("    2. The table ID is correct")
        print("    3. All required fields are created")
        return False


def add_sample_channels():
    """Add sample competitor channels (for testing)."""
    from clients.airtable_client import AirtableClient

    sample_channels = [
        {
            "Channel Name": "CaspianReport",
            "Channel URL": "https://www.youtube.com/@CaspianReport",
            "Category": "Geopolitics",
            "Active": True,
            "Notes": "1.8M subs, documentary-style geopolitical analysis",
        },
        {
            "Channel Name": "AiTelly",
            "Channel URL": "https://www.youtube.com/@AiTelly",
            "Category": "Geopolitics",
            "Active": True,
            "Notes": "2M subs, military/geopolitical analysis",
        },
        {
            "Channel Name": "Economics Explained",
            "Channel URL": "https://www.youtube.com/@EconomicsExplained",
            "Category": "Economy",
            "Active": True,
            "Notes": "2.5M subs, economics explainers",
        },
        {
            "Channel Name": "PolyMatter",
            "Channel URL": "https://www.youtube.com/@PolyMatter",
            "Category": "Economy",
            "Active": True,
            "Notes": "2M subs, business/economics analysis",
        },
        {
            "Channel Name": "TLDR News Global",
            "Channel URL": "https://www.youtube.com/@TLDRNewsGlobal",
            "Category": "Geopolitics",
            "Active": True,
            "Notes": "1.5M subs, current events explainers",
        },
    ]

    print("\n  Adding sample competitor channels...")

    airtable = AirtableClient()

    for channel in sample_channels:
        try:
            airtable.competitor_channels_table.create(channel, typecast=True)
            print(f"    Added: {channel['Channel Name']}")
        except Exception as e:
            if "DUPLICATE_VALUE" in str(e) or "already exists" in str(e).lower():
                print(f"    Skipped (exists): {channel['Channel Name']}")
            else:
                print(f"    Failed: {channel['Channel Name']} - {e}")

    print("\n  Done adding sample channels")


if __name__ == "__main__":
    if "--add-samples" in sys.argv:
        add_sample_channels()
    else:
        success = verify_setup()

        if not success:
            sys.exit(1)

        if len(sys.argv) > 1 and sys.argv[1] == "--verbose":
            print("\n" + "=" * 60)
            print("COLUMN REFERENCE")
            print("=" * 60)
            print("""
  Channel Name     | Single Line Text | Name of the channel
  Channel URL      | URL              | YouTube channel URL
  Category         | Single Select    | Geopolitics, Finance, Economy, Tech
  Active           | Checkbox         | Include in discovery scraping
  Last Scraped     | Date             | Auto-updated when scraped
  Notes            | Long Text        | Optional notes
            """)
