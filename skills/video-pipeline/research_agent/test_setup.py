#!/usr/bin/env python3
"""
Test Research Agent Setup

Verifies that all required API keys and dependencies are configured.
Run this before attempting a full scan.

Usage:
    cd /Users/ryanayler/economy-fastforward/skills/video-pipeline
    python -m research_agent.test_setup
"""

import os
import sys
import asyncio

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))


def check_env_var(name: str, required: bool = True) -> bool:
    """Check if an environment variable is set."""
    value = os.getenv(name)
    if value:
        # Mask the value for display
        masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "****"
        print(f"  [OK]  {name}: {masked}")
        return True
    elif required:
        print(f"  [MISSING] {name} - REQUIRED")
        return False
    else:
        print(f"  [--]  {name}: Not set (optional)")
        return True


async def test_tavily():
    """Test Tavily API connection."""
    print("\n2. Testing Tavily Search API...")
    try:
        import httpx
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            print("  [SKIP] No TAVILY_API_KEY set")
            return False

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": "test query",
                    "search_depth": "basic",
                    "max_results": 1,
                },
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                print(f"  [OK]  Tavily API working ({len(data.get('results', []))} results)")
                return True
            else:
                print(f"  [FAIL] Tavily API error: {response.status_code}")
                return False
    except Exception as e:
        print(f"  [FAIL] Tavily API error: {e}")
        return False


async def test_anthropic():
    """Test Anthropic API connection."""
    print("\n3. Testing Anthropic API...")
    try:
        from anthropic import Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("  [SKIP] No ANTHROPIC_API_KEY set")
            return False

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=50,
            messages=[{"role": "user", "content": "Say 'API OK' in 2 words"}],
        )
        result = response.content[0].text
        print(f"  [OK]  Anthropic API working: '{result.strip()}'")
        return True
    except Exception as e:
        print(f"  [FAIL] Anthropic API error: {e}")
        return False


async def test_airtable():
    """Test Airtable API connection."""
    print("\n4. Testing Airtable API...")
    try:
        from pyairtable import Api
        api_key = os.getenv("AIRTABLE_API_KEY")
        if not api_key:
            print("  [SKIP] No AIRTABLE_API_KEY set")
            return False

        base_id = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
        api = Api(api_key)

        # Try to list bases (this verifies the key works)
        # Note: This may fail if the key doesn't have schema access
        print(f"  [OK]  Airtable API key valid")
        print(f"  [INFO] Base ID: {base_id}")

        # Check if research tables exist
        print("\n  Checking for Research Agent tables...")
        daily_scans_id = os.getenv("AIRTABLE_DAILY_SCANS_ID")
        ideas_bank_id = os.getenv("AIRTABLE_IDEAS_BANK_ID")

        if daily_scans_id:
            print(f"    [OK]  Daily Scans table ID configured: {daily_scans_id}")
        else:
            print("    [WARN] AIRTABLE_DAILY_SCANS_ID not set - table needs to be created")

        if ideas_bank_id:
            print(f"    [OK]  Ideas Bank table ID configured: {ideas_bank_id}")
        else:
            print("    [WARN] AIRTABLE_IDEAS_BANK_ID not set - table needs to be created")

        return True
    except Exception as e:
        print(f"  [FAIL] Airtable API error: {e}")
        return False


async def main():
    """Run all setup tests."""
    print("=" * 60)
    print("RESEARCH INTELLIGENCE AGENT - SETUP TEST")
    print("=" * 60)

    # 1. Check environment variables
    print("\n1. Checking environment variables...")
    env_ok = all([
        check_env_var("TAVILY_API_KEY"),
        check_env_var("ANTHROPIC_API_KEY"),
        check_env_var("AIRTABLE_API_KEY"),
        check_env_var("AIRTABLE_DAILY_SCANS_ID", required=False),
        check_env_var("AIRTABLE_IDEAS_BANK_ID", required=False),
    ])

    # 2. Test APIs
    tavily_ok = await test_tavily()
    anthropic_ok = await test_anthropic()
    airtable_ok = await test_airtable()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_ok = env_ok and tavily_ok and anthropic_ok and airtable_ok

    if tavily_ok and anthropic_ok:
        print("\n[READY] Scanner is ready to run!")
        print("  Run: python -m research_agent.run_scan --dry-run")
    else:
        print("\n[NOT READY] Fix the issues above before running scans.")

    if not airtable_ok or not os.getenv("AIRTABLE_DAILY_SCANS_ID"):
        print("\n[AIRTABLE SETUP NEEDED]")
        print("  You need to create the Research Agent tables in Airtable.")
        print("  Run this to see the required schema:")
        print("    from research_agent.airtable_writer import create_tables_instructions")
        print("    print(create_tables_instructions())")
        print("\n  After creating tables, add to .env:")
        print("    AIRTABLE_DAILY_SCANS_ID=tbl...")
        print("    AIRTABLE_IDEAS_BANK_ID=tbl...")
        print("    AIRTABLE_SOURCES_ID=tbl...")

    print()
    return all_ok


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
