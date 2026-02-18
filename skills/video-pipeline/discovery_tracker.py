"""Shared discovery message tracker — persists Slack message → idea mappings.

When the cron job (pipeline.py --discover) posts discovery ideas to Slack,
it saves the message timestamp and idea data here. When the Slack bot
(pipeline_control.py) receives an emoji reaction, it reads from here to
find which ideas correspond to which message.

This bridges the gap between the cron process and the long-running Slack bot.

Storage: /tmp/pipeline-discovery-messages.json
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TRACKER_FILE = "/tmp/pipeline-discovery-messages.json"

# Auto-expire entries older than 48 hours (user should have picked by then)
EXPIRY_SECONDS = 48 * 3600


def _load_tracker() -> dict:
    """Load the tracker file, returning empty dict if missing/corrupt."""
    try:
        if os.path.exists(TRACKER_FILE):
            with open(TRACKER_FILE, "r") as f:
                data = json.load(f)
            # Prune expired entries
            now = time.time()
            pruned = {
                ts: entry for ts, entry in data.items()
                if now - entry.get("created_at", 0) < EXPIRY_SECONDS
            }
            return pruned
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not load tracker file: {e}")
        return {}


def _save_tracker(data: dict):
    """Write tracker data to file."""
    try:
        with open(TRACKER_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.error(f"Could not save tracker file: {e}")


def save_discovery_message(
    message_ts: str,
    ideas: list[dict],
    airtable_record_ids: list[Optional[str]] = None,
):
    """Save a discovery message for later reaction handling.

    Args:
        message_ts: Slack message timestamp (unique ID)
        ideas: List of idea dicts from discovery scanner
        airtable_record_ids: List of Airtable record IDs (parallel to ideas)
    """
    data = _load_tracker()
    data[message_ts] = {
        "ideas": ideas,
        "airtable_record_ids": airtable_record_ids or [],
        "created_at": time.time(),
    }
    _save_tracker(data)
    logger.info(f"Saved discovery message ts={message_ts} with {len(ideas)} ideas")


def get_discovery_message(message_ts: str) -> Optional[dict]:
    """Get a tracked discovery message by its Slack timestamp.

    Args:
        message_ts: Slack message timestamp

    Returns:
        Dict with 'ideas' and 'airtable_record_ids', or None if not found
    """
    data = _load_tracker()
    return data.get(message_ts)


def remove_discovery_message(message_ts: str):
    """Remove a tracked discovery message (after approval).

    Args:
        message_ts: Slack message timestamp
    """
    data = _load_tracker()
    if message_ts in data:
        del data[message_ts]
        _save_tracker(data)
        logger.info(f"Removed discovery message ts={message_ts}")
