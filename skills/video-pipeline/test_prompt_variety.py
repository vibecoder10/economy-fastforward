#!/usr/bin/env python3
"""Test script to verify image prompt variety after sequencer integration.

Checks that prompts:
1. Don't all start with "Overhead angled view of a holographic war table"
2. Have at least 3 different display formats
3. Have at least 3 different content types
4. Respect rotation constraints (max 2 consecutive same format)
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from clients.airtable_client import AirtableClient


async def test_prompt_variety(video_title: str):
    """Test prompt variety for a specific video."""
    client = AirtableClient()

    print(f"\n{'='*70}")
    print(f"IMAGE PROMPT VARIETY TEST: {video_title}")
    print(f"{'='*70}\n")

    # Get all image records for this video
    images = client.get_all_images_for_video(video_title)

    if not images:
        print(f"❌ No image records found for '{video_title}'")
        return False

    print(f"Found {len(images)} image records\n")

    # Extract prompts
    prompts = []
    for img in images:
        prompt = img.get("Image Prompt", "")
        if prompt:
            prompts.append(prompt)

    if not prompts:
        print(f"❌ No prompts found in image records")
        return False

    print(f"Analyzing {len(prompts)} prompts...\n")

    # Test 1: Check for variety in opening phrases
    war_table_count = sum(1 for p in prompts if p.startswith("Overhead angled view of a holographic war table"))
    wall_display_count = sum(1 for p in prompts if p.startswith("Front-facing view of a massive holographic wall display"))
    floating_count = sum(1 for p in prompts if p.startswith("Eye-level view of holographic objects floating"))
    multi_panel_count = sum(1 for p in prompts if p.startswith("Wide angle view of multiple holographic display panels"))
    close_up_count = sum(1 for p in prompts if p.startswith("Extreme close-up of a holographic display detail"))

    print("DISPLAY FORMAT DISTRIBUTION:")
    print(f"  War Table: {war_table_count} ({war_table_count/len(prompts)*100:.0f}%)")
    print(f"  Wall Display: {wall_display_count} ({wall_display_count/len(prompts)*100:.0f}%)")
    print(f"  Floating: {floating_count} ({floating_count/len(prompts)*100:.0f}%)")
    print(f"  Multi-Panel: {multi_panel_count} ({multi_panel_count/len(prompts)*100:.0f}%)")
    print(f"  Close-Up: {close_up_count} ({close_up_count/len(prompts)*100:.0f}%)\n")

    # Count unique display formats
    unique_formats = sum(1 for count in [war_table_count, wall_display_count, floating_count, multi_panel_count, close_up_count] if count > 0)

    # Test results
    tests_passed = 0
    tests_total = 4

    # Test 1: Not all war table
    if war_table_count < len(prompts):
        print(f"✅ TEST 1 PASS: Not all prompts are war_table ({war_table_count}/{len(prompts)})")
        tests_passed += 1
    else:
        print(f"❌ TEST 1 FAIL: All prompts are war_table (bug still present)")

    # Test 2: At least 3 different formats
    if unique_formats >= 3:
        print(f"✅ TEST 2 PASS: At least 3 different display formats ({unique_formats})")
        tests_passed += 1
    else:
        print(f"❌ TEST 2 FAIL: Only {unique_formats} display formats (need 3+)")

    # Test 3: Check for consecutive repetition
    # Extract format type from each prompt
    format_sequence = []
    for p in prompts:
        if p.startswith("Overhead angled"):
            format_sequence.append("war_table")
        elif p.startswith("Front-facing"):
            format_sequence.append("wall_display")
        elif p.startswith("Eye-level"):
            format_sequence.append("floating")
        elif p.startswith("Wide angle"):
            format_sequence.append("multi_panel")
        elif p.startswith("Extreme close-up"):
            format_sequence.append("close_up")
        else:
            format_sequence.append("unknown")

    max_consecutive = 0
    current_consecutive = 1
    for i in range(1, len(format_sequence)):
        if format_sequence[i] == format_sequence[i-1]:
            current_consecutive += 1
            max_consecutive = max(max_consecutive, current_consecutive)
        else:
            current_consecutive = 1

    if max_consecutive <= 2:
        print(f"✅ TEST 3 PASS: Max consecutive same format is {max_consecutive} (≤2)")
        tests_passed += 1
    else:
        print(f"❌ TEST 3 FAIL: Max consecutive same format is {max_consecutive} (should be ≤2)")

    # Test 4: Variety in content (check if different content types appear in prompts)
    # Simple heuristic: check for content-specific keywords
    content_keywords = {
        "map": ["country", "border", "territory", "route", "coastline"],
        "chart": ["chart", "candlestick", "ticker", "percentage", "graph"],
        "object": ["wireframe", "comparison", "scale", "floating objects"],
        "document": ["document", "treaty", "contract", "clause", "stamp"],
        "network": ["nodes", "connections", "flow lines", "network"],
        "timeline": ["timeline", "historical", "before/after", "era"],
    }

    content_type_hits = {k: 0 for k in content_keywords.keys()}
    for prompt in prompts:
        prompt_lower = prompt.lower()
        for content_type, keywords in content_keywords.items():
            if any(kw in prompt_lower for kw in keywords):
                content_type_hits[content_type] += 1
                break

    unique_content_types = sum(1 for hits in content_type_hits.values() if hits > 0)

    print(f"\nCONTENT TYPE VARIETY (detected via keywords):")
    for content_type, hits in content_type_hits.items():
        if hits > 0:
            print(f"  {content_type}: {hits} prompts")

    if unique_content_types >= 3:
        print(f"\n✅ TEST 4 PASS: At least 3 different content types detected ({unique_content_types})")
        tests_passed += 1
    else:
        print(f"\n❌ TEST 4 FAIL: Only {unique_content_types} content types detected (need 3+)")

    # Final summary
    print(f"\n{'='*70}")
    print(f"RESULTS: {tests_passed}/{tests_total} tests passed")
    print(f"{'='*70}\n")

    if tests_passed == tests_total:
        print("🎉 ALL TESTS PASSED - Prompt variety is working correctly!\n")
        return True
    else:
        print("⚠️  SOME TESTS FAILED - Review the results above\n")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_prompt_variety.py <video_title>")
        print("\nExample:")
        print('  python test_prompt_variety.py "Why The Strait Of Hormuz Is More Valuable Than You Think"')
        sys.exit(1)

    video_title = sys.argv[1]
    success = asyncio.run(test_prompt_variety(video_title))
    sys.exit(0 if success else 1)
