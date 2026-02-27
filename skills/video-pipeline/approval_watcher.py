"""
Approval Watcher — Polls Airtable for ideas with 'Approved' status
and auto-triggers deep research.

This provides Path B for auto-triggering research:
  Path A: Slack reaction → discovery bot handles it directly
  Path B: Manual Airtable status change → this watcher detects it

Can run standalone or be integrated into the pipeline bot's polling loop.

Usage (standalone):
    python approval_watcher.py                    # Poll once
    python approval_watcher.py --daemon           # Continuous polling
    python approval_watcher.py --interval 120     # Poll every 2 minutes

Usage (imported):
    from approval_watcher import ApprovalWatcher
    watcher = ApprovalWatcher(anthropic_client, airtable_client, slack_client)
    await watcher.check_and_process()
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Track processed record IDs to prevent duplicate research runs
_processed_ids: set[str] = set()


def _extract_formula_id(idea: dict) -> str:
    """Extract the formula_id for the selected title from original_dna.

    Matches the Video Title against title_options stored in original_dna JSON.
    Returns the matching formula_id, or the first one if no exact match.
    """
    dna_str = idea.get("Original DNA", "")
    if not dna_str:
        return ""
    try:
        dna = json.loads(dna_str)
    except (json.JSONDecodeError, TypeError):
        return ""

    title_options = dna.get("title_options", [])
    if not title_options:
        # Fallback: check formula_ids list
        formula_ids = dna.get("formula_ids", [])
        return formula_ids[0] if formula_ids else ""

    video_title = idea.get("Video Title", "").strip().lower()
    for opt in title_options:
        if opt.get("title", "").strip().lower() == video_title:
            return opt.get("formula_id", "")

    # No exact match — return first formula_id
    return title_options[0].get("formula_id", "")


class ApprovalWatcher:
    """Watches Airtable for approved ideas and triggers deep research.

    Provides idempotent processing — each approved idea is researched
    exactly once, even if the watcher checks multiple times.

    Usage:
        watcher = ApprovalWatcher(anthropic, airtable, slack)
        processed = await watcher.check_and_process()
    """

    def __init__(
        self,
        anthropic_client,
        airtable_client,
        slack_client=None,
        model: str = "claude-sonnet-4-5-20250929",
    ):
        """Initialize the approval watcher.

        Args:
            anthropic_client: AnthropicClient for research LLM calls
            airtable_client: AirtableClient for reading/writing ideas
            slack_client: Optional SlackClient for notifications
            model: Model to use for research (Sonnet 4.5 default)
        """
        self.anthropic = anthropic_client
        self.airtable = airtable_client
        self.slack = slack_client
        self.model = model

    def _notify(self, message: str):
        """Send Slack notification if client is available."""
        if self.slack:
            try:
                self.slack.send_message(message)
            except Exception as e:
                logger.warning(f"Slack notification failed: {e}")
        logger.info(message)

    async def check_and_process(self) -> list[dict]:
        """Check for approved ideas and process them.

        Finds all ideas with status 'Approved', runs deep research
        on each, writes the payload back, and advances status.

        Returns:
            List of processed idea records (with research payloads)
        """
        from research_agent import run_research

        # Find approved ideas
        try:
            approved = self.airtable.get_ideas_by_status("Approved", limit=5)
        except Exception as e:
            logger.error(f"Failed to fetch approved ideas: {e}")
            return []

        if not approved:
            logger.debug("No approved ideas found")
            return []

        processed = []

        for idea in approved:
            record_id = idea.get("id", "")
            title = idea.get("Video Title", "Untitled")

            # Idempotency check — skip if already processed
            if record_id in _processed_ids:
                logger.debug(f"Skipping already-processed: {record_id}")
                continue

            logger.info(f"Processing approved idea: {title} ({record_id})")
            self._notify(
                f"🔬 Auto-researching approved idea: _{title}_"
            )

            # Save Title Formula if not already set (extract from original_dna)
            if not idea.get("Title Formula"):
                formula_id = _extract_formula_id(idea)
                if formula_id:
                    try:
                        self.airtable.update_idea_field(
                            record_id, "Title Formula", formula_id
                        )
                        logger.info(f"Set Title Formula: {formula_id}")
                    except Exception as e:
                        logger.warning(f"Could not write Title Formula: {e}")

            try:
                # Build context from idea fields
                context_parts = []
                if idea.get("Hook Script"):
                    context_parts.append(idea["Hook Script"])
                if idea.get("Writer Guidance"):
                    context_parts.append(idea["Writer Guidance"])
                context = "\n".join(context_parts) if context_parts else None

                # Run deep research
                payload = await run_research(
                    anthropic_client=self.anthropic,
                    topic=title,
                    context=context,
                    model=self.model,
                )

                # Write research payload and rich fields back to the same record
                from research_agent import infer_framework_from_research

                research_json = json.dumps(payload)
                research_fields = {
                    "Research Payload": research_json,
                    "Source URLs": payload.get("source_bibliography", ""),
                    "Executive Hook": payload.get("executive_hook", ""),
                    "Thesis": payload.get("thesis", ""),
                    "Thematic Framework": payload.get("themes", ""),
                    "Headline": payload.get("headline", ""),
                }

                # Set Framework Angle if not already set on the record
                existing_framework = idea.get("Framework Angle")
                if not existing_framework:
                    research_fields["Framework Angle"] = infer_framework_from_research(payload)
                    logger.info(
                        f"Set Framework Angle: {research_fields['Framework Angle']}"
                    )

                try:
                    self.airtable.update_idea_fields(record_id, research_fields)
                except Exception as e:
                    logger.warning(f"Could not write research fields: {e}")
                    # Fallback: try just the research payload
                    try:
                        self.airtable.update_idea_field(
                            record_id, "Research Payload", research_json
                        )
                    except Exception:
                        logger.warning("Could not write Research Payload field either")

                # Always advance status — even if some field writes failed above
                self.airtable.update_idea_status(
                    record_id, "Ready For Scripting"
                )

                self._notify(
                    f"✅ Research complete for: _{title}_\n"
                    f"Headline: {payload.get('headline', title)}\n"
                    f"Status: Ready For Scripting"
                )

                # Mark as processed
                _processed_ids.add(record_id)
                payload["_record_id"] = record_id
                processed.append(payload)

            except Exception as e:
                logger.error(
                    f"Research failed for {title}: {e}", exc_info=True
                )
                # Status stays at Approved — don't advance on failure
                self._notify(
                    f"❌ Research failed for: _{title}_\n"
                    f"Error: {str(e)[:200]}\n"
                    f"Status remains: Approved"
                )

        return processed


async def _poll_loop(
    anthropic_client,
    airtable_client,
    slack_client=None,
    interval: int = 300,
):
    """Continuous polling loop for approved ideas.

    Args:
        anthropic_client: AnthropicClient instance
        airtable_client: AirtableClient instance
        slack_client: Optional SlackClient for notifications
        interval: Polling interval in seconds (default: 5 minutes)
    """
    watcher = ApprovalWatcher(
        anthropic_client, airtable_client, slack_client
    )

    logger.info(
        f"Approval watcher started (polling every {interval}s)"
    )

    while True:
        try:
            processed = await watcher.check_and_process()
            if processed:
                logger.info(
                    f"Processed {len(processed)} approved ideas"
                )
        except Exception as e:
            logger.error(f"Poll cycle error: {e}", exc_info=True)

        await asyncio.sleep(interval)


# === CLI Entry Point ===

async def _cli_main():
    """CLI entry point for standalone approval watcher."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Economy FastForward Approval Watcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python approval_watcher.py                    # Poll once
  python approval_watcher.py --daemon           # Continuous polling
  python approval_watcher.py --interval 120     # Poll every 2 minutes
""",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously (poll loop)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Polling interval in seconds (default: 300 = 5 minutes)",
    )

    args = parser.parse_args()

    # Load environment
    from dotenv import load_dotenv
    load_dotenv()

    from clients.anthropic_client import AnthropicClient
    from clients.airtable_client import AirtableClient

    anthropic = AnthropicClient()
    airtable = AirtableClient()

    # Optional Slack client
    slack = None
    try:
        from clients.slack_client import SlackClient
        slack = SlackClient()
    except Exception:
        logger.info("Slack client not available — notifications disabled")

    print(f"\n{'=' * 60}")
    print(f"APPROVAL WATCHER — Auto-Research on Approval")
    print(f"{'=' * 60}")
    print(f"Mode: {'Daemon' if args.daemon else 'Single poll'}")
    if args.daemon:
        print(f"Interval: {args.interval}s")
    print(f"{'=' * 60}\n")

    if args.daemon:
        await _poll_loop(anthropic, airtable, slack, args.interval)
    else:
        watcher = ApprovalWatcher(anthropic, airtable, slack)
        processed = await watcher.check_and_process()

        if processed:
            print(f"\nProcessed {len(processed)} ideas:")
            for p in processed:
                print(f"  - {p.get('headline', 'N/A')}")
        else:
            print("\nNo approved ideas to process.")

    print(f"\n{'=' * 60}")
    print("Approval watcher done.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(_cli_main())
