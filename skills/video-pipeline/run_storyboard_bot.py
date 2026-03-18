"""
Run the Storyboard Bot — cinematic shot planning and contact sheet generation.

Called by: pipeline_control.py (Slack bot) or manually via CLI.

Modes:
  --directive-only   Generate Claude directives only, print shot plans. Zero image cost.
  --plan             Show cost estimate and beat breakdown only.
  --beat N           Process only beat N.
  --title "..."      Specify video title (otherwise picks first Ready For Storyboards).

Examples:
  python run_storyboard_bot.py --directive-only --title "Why China's Dollar Trap Is Closing"
  python run_storyboard_bot.py --plan --title "Why China's Dollar Trap Is Closing"
  python run_storyboard_bot.py --directive-only --beat 3
"""

import argparse
import asyncio
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from clients.airtable_client import AirtableClient
from pipeline_constants import IdeaFields, Statuses
from storyboard_bot import (
    generate_storyboard_plan,
    run_storyboard_preview,
)


def _find_idea_record(airtable: AirtableClient, title: str = None) -> Optional[dict]:
    """Find an idea record by title or by storyboard-ready status."""
    if title:
        from pyairtable.formulas import match
        records = airtable.ideas_table.all(
            formula=match({IdeaFields.VIDEO_TITLE: title}),
            max_records=1,
        )
        if records:
            return {"id": records[0]["id"], "fields": records[0]["fields"]}
        print(f"❌ No idea found with title: {title}")
        return None

    # Fall back to first Ready For Storyboards
    records = airtable.get_ideas_by_status("Ready For Storyboards")
    if records:
        return records[0]

    # Also check Ready For Images (can storyboard those too)
    records = airtable.get_ideas_by_status(Statuses.READY_IMAGES)
    if records:
        return records[0]

    print("❌ No ideas found in Ready For Storyboards or Ready For Images status")
    return None


async def cmd_plan(idea_record: dict) -> None:
    """Show cost estimate and beat breakdown."""
    plan = await generate_storyboard_plan(idea_record)

    if plan.get("error"):
        print(f"❌ {plan['error']}")
        return

    print("=" * 60)
    print(f"🎬 STORYBOARD PLAN — \"{plan['video_title']}\"")
    print("=" * 60)
    print()
    print(f"📝 Script: {plan['total_words']} words | {plan['scene_count']} scenes")
    print(f"⏱️  Est. length: {plan['video_length_minutes']} min @ {plan['clip_duration_seconds']}s clips")
    print(f"🎞️  Narrative beats: {plan['beat_count']} (each ~40s of narration)")
    print(f"🖼️  Grids: {plan['beat_count']} contact sheets × 9 panels = {plan['total_panels']} frames")
    print()
    print("💰 Cost Estimate:")
    print(f"   Directives (Claude):     {plan['beat_count']} × $0.03  = ${plan['cost_claude']:.2f}")
    print(f"   Contact sheets (NBPro):  {plan['beat_count']} × $0.075 = ${plan['cost_grids']:.2f}")
    print(f"   Upscales (NB2):         {plan['total_panels']} × $0.045 = ${plan['cost_upscale']:.2f}")
    print(f"   {'─' * 40}")
    print(f"   Total:                               ${plan['total_cost']:.2f}")
    print()

    # Beat breakdown
    print("📋 Beat Breakdown:")
    for beat in plan["beats"]:
        print(
            f"  Beat {beat['beat_number']:2d}: "
            f"Scenes {', '.join(str(s) for s in beat['scenes']):>10s} | "
            f"{beat['word_count']:3d} words | "
            f"~{beat['estimated_duration_seconds']:.0f}s"
        )


async def cmd_directive_only(idea_record: dict, single_beat: int = None) -> None:
    """Generate Claude directives and print shot plans."""
    fields = idea_record.get("fields", idea_record)
    video_title = fields.get("Video Title", "")

    print("=" * 60)
    print(f"🎬 DIRECTIVE-ONLY MODE — \"{video_title}\"")
    if single_beat:
        print(f"   Processing beat {single_beat} only")
    print("=" * 60)
    print()

    results = await run_storyboard_preview(
        idea_record=idea_record,
        single_beat=single_beat,
    )

    if not results:
        print("❌ No results generated")
        return

    for result in results:
        # Print the formatted preview
        print(result["preview"])
        print()

        # Print the contact sheet prompt
        directive = result["directive"]
        if directive.get("contact_sheet_prompt"):
            print("📸 Contact Sheet Prompt:")
            print("-" * 40)
            print(directive["contact_sheet_prompt"][:500])
            if len(directive["contact_sheet_prompt"]) > 500:
                print(f"  ... ({len(directive['contact_sheet_prompt'])} chars total)")
            print()

        # Print the full directive for quality validation
        print("📄 Full Directive:")
        print("-" * 40)
        print(directive["full_response"][:2000])
        if len(directive["full_response"]) > 2000:
            print(f"\n  ... ({len(directive['full_response'])} chars total)")
        print()
        print("=" * 60)
        print()

    # Summary
    total_kf = sum(len(r["directive"]["keyframes"]) for r in results)
    total_dur = sum(
        kf["duration_seconds"]
        for r in results
        for kf in r["directive"]["keyframes"]
    )
    print(f"✅ Generated {len(results)} directives with {total_kf} total keyframes")
    print(f"   Total planned duration: {total_dur:.1f}s")
    print(f"   Est. Claude cost: ${len(results) * 0.03:.2f}")


async def main():
    parser = argparse.ArgumentParser(description="Storyboard Bot — Cinematic shot planning")
    parser.add_argument("--title", type=str, help="Video title to process")
    parser.add_argument("--plan", action="store_true", help="Show cost estimate and beat breakdown only")
    parser.add_argument("--directive-only", action="store_true", help="Generate Claude directives only, no images")
    parser.add_argument("--beat", type=int, help="Process only this beat number")
    args = parser.parse_args()

    airtable = AirtableClient()
    idea_record = _find_idea_record(airtable, args.title)
    if not idea_record:
        sys.exit(1)

    if args.plan:
        await cmd_plan(idea_record)
    elif args.directive_only:
        await cmd_directive_only(idea_record, single_beat=args.beat)
    else:
        # Full generation — not implemented yet, will be Phase 2
        print("❌ Full storyboard generation not yet implemented.")
        print("   Use --directive-only to generate shot plans.")
        print("   Use --plan to see cost estimates.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
