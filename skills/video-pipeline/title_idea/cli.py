#!/usr/bin/env python3
"""Run curiosity gap title generation.

Usage:
    python run_gap_titles.py "China's dollar reserves are declining"
    python run_gap_titles.py --record rec123  # Regenerate for existing idea
    python run_gap_titles.py --dry-run "topic"  # Preview only
"""

import os
import sys
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine
from autopilot.learning.pattern_library import PatternLibrary
from shared.clients.anthropic_client import AnthropicClient
from shared.clients.airtable_client import AirtableClient
from orchestrator.pipeline_constants import CURIOSITY_GAP_ENABLED


async def generate_titles_for_topic(topic: str, dry_run: bool = False) -> None:
    """Generate titles for a topic description."""
    print(f"\n🎯 Generating curiosity gap titles for: {topic}\n")

    if not CURIOSITY_GAP_ENABLED:
        print("❌ CURIOSITY_GAP_ENABLED is False. Enable in pipeline_constants.py")
        return

    engine = GapTitleEngine(AnthropicClient())
    pattern_library = PatternLibrary()

    story_context = {
        "hook": topic,
        "thesis": topic,
        "facts": [],
    }

    titles = await engine.generate_titles(
        story_context,
        pattern_library=pattern_library,
        target_count=3,
    )

    if not titles:
        print("❌ No titles generated (all structures below confidence floor)")
        return

    print("Generated titles:\n")
    for i, title in enumerate(titles, 1):
        print(f"{i}. {title.text}")
        print(f"   Structure: {title.structure.value} ({title.structure_confidence}%)")
        print(f"   Thumbnail: {title.thumbnail_text} ({title.thumbnail_approach})")
        print(f"   Reasoning: {title.reasoning}")
        print()


async def regenerate_for_record(record_id: str, dry_run: bool = False) -> None:
    """Regenerate titles for an existing Airtable idea record."""
    print(f"\n🔄 Regenerating titles for record: {record_id}\n")

    airtable = AirtableClient()
    record = airtable.get_idea(record_id)

    if not record:
        print(f"❌ Record not found: {record_id}")
        return

    fields = record.get("fields", {})
    title = fields.get("Video Title", "")
    hook = fields.get("Hook Script", "")
    thesis = fields.get("Thesis", "")

    print(f"Current title: {title}")
    print(f"Hook: {hook[:100]}..." if len(hook) > 100 else f"Hook: {hook}")

    engine = GapTitleEngine(AnthropicClient())
    pattern_library = PatternLibrary()

    story_context = {
        "hook": hook or title,
        "thesis": thesis or title,
        "facts": [],
    }

    titles = await engine.generate_titles(
        story_context,
        pattern_library=pattern_library,
        target_count=3,
    )

    if not titles:
        print("❌ No titles generated")
        return

    print("\nGenerated alternatives:\n")
    for i, t in enumerate(titles, 1):
        print(f"{i}. {t.text}")
        print(f"   Structure: {t.structure.value} ({t.structure_confidence}%)")
        print()

    if dry_run:
        print("(dry run - not saving)")
        return

    # Update with best title
    best = titles[0]
    print(f"\nSaving best title: {best.text}")

    airtable.update_idea_curiosity_structure(
        record_id=record_id,
        structure=best.structure.value,
        confidence=best.structure_confidence,
        thumbnail_text=best.thumbnail_text,
        thumbnail_approach=best.thumbnail_approach,
    )

    # Also update the title itself
    airtable.idea_concepts_table.update(record_id, {"Video Title": best.text})

    print("✅ Saved")


async def main():
    parser = argparse.ArgumentParser(description="Generate curiosity gap titles")
    parser.add_argument("topic", nargs="?", help="Topic to generate titles for")
    parser.add_argument("--record", help="Airtable record ID to regenerate")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")

    args = parser.parse_args()

    if args.record:
        await regenerate_for_record(args.record, args.dry_run)
    elif args.topic:
        await generate_titles_for_topic(args.topic, args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
