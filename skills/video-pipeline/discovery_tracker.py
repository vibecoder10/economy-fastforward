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


# === Reaction deduplication ===
# Prevents double-clicking an emoji from triggering duplicate research

REACTION_LOG_FILE = "/tmp/pipeline-processed-reactions.json"


def _load_reaction_log() -> dict:
    """Load the processed reactions log."""
    try:
        if os.path.exists(REACTION_LOG_FILE):
            with open(REACTION_LOG_FILE, "r") as f:
                data = json.load(f)
            # Prune entries older than 48 hours
            now = time.time()
            pruned = {
                k: v for k, v in data.items()
                if now - v.get("processed_at", 0) < EXPIRY_SECONDS
            }
            return pruned
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_reaction_log(data: dict):
    """Write reaction log to file."""
    try:
        with open(REACTION_LOG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.error(f"Could not save reaction log: {e}")


def is_reaction_processed(message_ts: str, reaction: str) -> bool:
    """Check if a reaction on a message has already been processed.

    Args:
        message_ts: Slack message timestamp
        reaction: Emoji name (e.g., "one", "two")

    Returns:
        True if this reaction was already handled (duplicate click)
    """
    key = f"{message_ts}:{reaction}"
    log = _load_reaction_log()
    return key in log


def mark_reaction_processed(message_ts: str, reaction: str, title: str = ""):
    """Record that a reaction has been processed (for deduplication).

    Args:
        message_ts: Slack message timestamp
        reaction: Emoji name
        title: Title of the approved idea (for logging)
    """
    key = f"{message_ts}:{reaction}"
    log = _load_reaction_log()
    log[key] = {
        "processed_at": time.time(),
        "title": title,
    }
    _save_reaction_log(log)
    logger.info(f"Marked reaction as processed: {key} ({title})")
