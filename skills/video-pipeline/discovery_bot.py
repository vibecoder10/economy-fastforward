"""
Discovery Bot — Slack integration for the discovery scanner with emoji
reaction approval.

Handles the full flow:
  1. /discover command or "discover" message → runs discovery scanner
  2. Posts results to Slack with 1️⃣ 2️⃣ 3️⃣ prompt
  3. Listens for reaction_added events on those messages
  4. Writes approved idea to Airtable with all rich fields
  5. Auto-triggers the research agent

Requires Slack app configuration:
  Event Subscriptions → Subscribe to bot events:
    - reaction_added
    - message.channels (or message.groups for private channels)

Usage (standalone):
    python discovery_bot.py                    # Start bot
    python discovery_bot.py --port 3000        # Custom port

Usage (imported):
    from discovery_bot import DiscoveryBot
    bot = DiscoveryBot()
    bot.start()
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
from typing import Optional

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env'))

logger = logging.getLogger(__name__)

# Map emoji to idea number
APPROVAL_EMOJIS = {
    "1\ufe0f\u20e3": 1,  # 1️⃣
    "one": 1,
    "2\ufe0f\u20e3": 2,  # 2️⃣
    "two": 2,
    "3\ufe0f\u20e3": 3,  # 3️⃣
    "three": 3,
}


class DiscoveryResultsStore:
    """Thread-safe store for discovery results keyed by Slack message timestamp.

    When discovery results are posted to Slack, the message_ts and ideas are
    stored here. When a reaction comes in, we look up which ideas were in
    that specific message.
    """

    def __init__(self, max_entries: int = 100):
        self._store: dict[str, dict] = {}
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def save(self, message_ts: str, channel: str, discovery_result: dict):
        """Save discovery results for a message."""
        with self._lock:
            self._store[message_ts] = {
                "channel": channel,
                "ideas": discovery_result.get("ideas", []),
                "metadata": discovery_result.get("_metadata", {}),
                "timestamp": time.time(),
            }
            # Evict oldest entries if over limit
            if len(self._store) > self._max_entries:
                oldest_key = min(self._store, key=lambda k: self._store[k]["timestamp"])
                del self._store[oldest_key]

    def get(self, message_ts: str) -> Optional[dict]:
        """Retrieve discovery results for a message."""
        with self._lock:
            return self._store.get(message_ts)

    def remove(self, message_ts: str):
        """Remove a result after it's been processed."""
        with self._lock:
            self._store.pop(message_ts, None)


# Global store instance (shared across the bot)
_results_store = DiscoveryResultsStore()


def get_results_store() -> DiscoveryResultsStore:
    """Get the global discovery results store."""
    return _results_store


class DiscoveryBot:
    """Slack bot that runs discovery scans and handles emoji reaction approvals.

    Usage:
        bot = DiscoveryBot()
        bot.start()  # Starts the Slack socket mode listener
    """

    def __init__(
        self,
        slack_bot_token: Optional[str] = None,
        slack_app_token: Optional[str] = None,
    ):
        """Initialize the discovery bot.

        Args:
            slack_bot_token: Bot User OAuth Token (xoxb-...)
            slack_app_token: App-Level Token for Socket Mode (xapp-...)
        """
        self.bot_token = slack_bot_token or os.getenv("SLACK_BOT_TOKEN")
        self.app_token = slack_app_token or os.getenv("SLACK_APP_TOKEN")

        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN not found in environment")

        self.store = get_results_store()

        # Lazy-init API clients
        self._anthropic = None
        self._airtable = None
        self._slack = None

    @property
    def anthropic(self):
        if self._anthropic is None:
            from clients.anthropic_client import AnthropicClient
            self._anthropic = AnthropicClient()
        return self._anthropic

    @property
    def airtable(self):
        if self._airtable is None:
            from clients.airtable_client import AirtableClient
            self._airtable = AirtableClient()
        return self._airtable

    @property
    def slack(self):
        if self._slack is None:
            from clients.slack_client import SlackClient
            self._slack = SlackClient()
        return self._slack

    async def run_discovery(
        self,
        channel_id: str,
        focus: Optional[str] = None,
    ) -> Optional[str]:
        """Run the discovery scanner and post results to Slack.

        Returns:
            Message timestamp if successful, None if failed.
        """
        from discovery_scanner import run_discovery, format_ideas_for_slack

        logger.info(f"Running discovery scan (focus={focus})")

        try:
            result = await run_discovery(
                anthropic_client=self.anthropic,
                focus=focus,
            )
        except Exception as e:
            logger.error(f"Discovery scan failed: {e}")
            self.slack.send_message(
                f"❌ Discovery scan failed: {str(e)[:200]}", channel_id
            )
            return None

        ideas = result.get("ideas", [])
        if not ideas:
            self.slack.send_message("No ideas found. Try a different focus.", channel_id)
            return None

        # Format and post results
        message_text = format_ideas_for_slack(result)
        response = self.slack.send_message(message_text, channel_id)

        if not response.get("ok"):
            logger.error(f"Failed to post discovery results: {response}")
            return None

        message_ts = response["ts"]

        # Store results keyed by message timestamp
        self.store.save(message_ts, channel_id, result)
        logger.info(
            f"Discovery results posted (ts={message_ts}, {len(ideas)} ideas)"
        )

        return message_ts

    async def handle_reaction(
        self,
        emoji_name: str,
        message_ts: str,
        channel_id: str,
        user_id: str,
    ) -> bool:
        """Handle a reaction_added event.

        Checks if the reaction is an approval emoji on a discovery results
        message, and if so, approves the idea.

        Args:
            emoji_name: The emoji name (e.g., "one", "1️⃣")
            message_ts: Timestamp of the message reacted to
            channel_id: Channel where the reaction was added
            user_id: User who added the reaction

        Returns:
            True if the reaction was handled, False if not relevant.
        """
        # Check if this is an approval emoji
        idea_number = APPROVAL_EMOJIS.get(emoji_name)
        if idea_number is None:
            return False

        # Look up the discovery results for this message
        stored = self.store.get(message_ts)
        if stored is None:
            logger.debug(f"No discovery results for message {message_ts}")
            return False

        ideas = stored.get("ideas", [])
        if idea_number > len(ideas):
            self.slack.send_message(
                f"⚠️ Idea {idea_number} doesn't exist (only {len(ideas)} ideas).",
                channel_id,
            )
            return True

        idea = ideas[idea_number - 1]
        title_options = idea.get("title_options", [])
        best_title = ""
        if title_options:
            best_title = title_options[0].get("title", "")

        logger.info(f"Approving idea {idea_number}: {best_title}")
        self.slack.send_message(
            f"✅ Idea {idea_number} approved. Starting deep research on: "
            f"_{best_title or idea.get('our_angle', 'Unknown')[:80]}_...",
            channel_id,
        )

        # Write to Airtable with all rich fields
        try:
            record = await self._approve_idea_to_airtable(idea, idea_number)
            record_id = record.get("id", "")

            # Auto-trigger research
            await self._trigger_research(record_id, best_title, idea, channel_id)

            # Prevent double-processing
            self.store.remove(message_ts)

        except Exception as e:
            logger.error(f"Approval failed: {e}", exc_info=True)
            self.slack.send_message(
                f"❌ Approval failed: {str(e)[:200]}",
                channel_id,
            )

        return True

    async def _approve_idea_to_airtable(self, idea: dict, idea_number: int) -> dict:
        """Write an approved discovery idea to Airtable with all rich fields."""
        from discovery_scanner import build_idea_record_from_discovery

        idea_record = build_idea_record_from_discovery(idea, idea_number)

        # Override status to "Approved" (will trigger research)
        record = self.airtable.create_idea(idea_record, source="discovery_scanner")

        # Update status to Approved
        self.airtable.update_idea_status(record["id"], "Approved")

        logger.info(f"Airtable record created: {record['id']}")
        return record

    async def _trigger_research(
        self,
        record_id: str,
        title: str,
        idea: dict,
        channel_id: str,
    ):
        """Auto-trigger deep research on an approved idea."""
        from research_agent import run_research, infer_framework_from_research

        context_parts = [idea.get("our_angle", ""), idea.get("hook", "")]
        if idea.get("historical_parallel_hint"):
            context_parts.append(f"Historical parallel: {idea['historical_parallel_hint']}")
        context = "\n".join(p for p in context_parts if p)

        # Collect seed URLs from headline_source
        seed_urls = []
        headline_source = idea.get("headline_source", "")
        if "http" in headline_source:
            import re
            urls = re.findall(r'https?://[^\s\)>\]"\']+', headline_source)
            seed_urls.extend(urls)

        try:
            payload = await run_research(
                anthropic_client=self.anthropic,
                topic=title or idea.get("our_angle", ""),
                seed_urls=seed_urls or None,
                context=context,
            )

            # Write research back to the same record
            import json
            research_fields = {
                "Research Payload": json.dumps(payload),
                "Source URLs": payload.get("source_bibliography", ""),
                "Executive Hook": payload.get("executive_hook", ""),
                "Thesis": payload.get("thesis", ""),
                "Thematic Framework": payload.get("themes", ""),
                "Headline": payload.get("headline", ""),
            }

            # Set Framework Angle from research
            framework_angle = infer_framework_from_research(payload)
            research_fields["Framework Angle"] = framework_angle

            try:
                self.airtable.update_idea_fields(record_id, research_fields)
            except Exception as e:
                logger.warning(f"Could not write all research fields: {e}")

            # Always advance status — even if some field writes failed above
            self.airtable.update_idea_status(record_id, "Ready For Scripting")

            self.slack.send_message(
                f"✅ Research complete: _{payload.get('headline', title)}_\n"
                f"Framework: {framework_angle}\n"
                f"Status: Ready For Scripting",
                channel_id,
            )

        except Exception as e:
            logger.error(f"Research failed: {e}", exc_info=True)
            self.slack.send_message(
                f"⚠️ Research failed for _{title}_: {str(e)[:200]}\n"
                f"Status remains: Approved (retry manually or via approval_watcher)",
                channel_id,
            )


def register_reaction_handler(app):
    """Register the reaction_added event handler on a Slack Bolt app.

    This is for integration with an existing Slack Bolt application.
    Call this during app setup.

    Args:
        app: slack_bolt.App instance
    """
    bot = DiscoveryBot()

    @app.event("reaction_added")
    def handle_reaction_added(event, say):
        """Handle reaction_added events from Slack."""
        emoji = event.get("reaction", "")
        item = event.get("item", {})
        message_ts = item.get("ts", "")
        channel = item.get("channel", "")
        user = event.get("user", "")

        # Run async handler in sync context
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                bot.handle_reaction(emoji, message_ts, channel, user)
            )
        finally:
            loop.close()

    logger.info("Reaction handler registered on Slack Bolt app")
    return bot


# === CLI Entry Point (Socket Mode) ===

def _start_socket_mode():
    """Start the bot using Slack Socket Mode.

    Requires SLACK_APP_TOKEN (xapp-...) in addition to SLACK_BOT_TOKEN.
    """
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        print("Install slack_bolt: pip install slack-bolt")
        sys.exit(1)

    bot_token = os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")

    if not app_token:
        print(
            "SLACK_APP_TOKEN not set. Socket Mode requires an app-level token.\n"
            "Create one at: https://api.slack.com/apps → Basic Information → App-Level Tokens\n"
            "Add scope: connections:write"
        )
        sys.exit(1)

    app = App(token=bot_token)
    bot = register_reaction_handler(app)

    # Handle "discover" messages
    @app.message("discover")
    def handle_discover_message(message, say):
        """Handle 'discover' or 'discover <focus>' messages."""
        text = message.get("text", "").strip()
        channel = message.get("channel", "")

        # Extract focus keyword if present
        focus = None
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            focus = parts[1].strip()

        say(f"🔍 Running discovery scan{f' (focus: {focus})' if focus else ''}...")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot.run_discovery(channel, focus))
        finally:
            loop.close()

    print(f"\n{'=' * 60}")
    print("DISCOVERY BOT — Slack Integration")
    print(f"{'=' * 60}")
    print("Listening for:")
    print("  - 'discover' messages → runs headline scan")
    print("  - 1️⃣ 2️⃣ 3️⃣ reactions → approves ideas")
    print(f"{'=' * 60}\n")

    handler = SocketModeHandler(app, app_token)
    handler.start()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    import argparse
    parser = argparse.ArgumentParser(description="Discovery Bot — Slack Integration")
    parser.add_argument("--port", type=int, default=3000, help="Port (unused in Socket Mode)")
    args = parser.parse_args()

    _start_socket_mode()
