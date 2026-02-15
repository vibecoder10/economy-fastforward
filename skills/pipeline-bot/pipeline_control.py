#!/usr/bin/env python3
"""
Pipeline Control Bot - Lightweight Slack bot for controlling the video pipeline.
No AI, no Anthropic API calls. Just listens for commands and runs bash.

Commands:
  !status   - Show pipeline queue status from Airtable
  !run      - Trigger pipeline immediately
  !kill     - Kill any running pipeline process
  !logs     - Show last 20 lines of pipeline log
  !cron     - Show current cron schedule
  !cron 10m - Set cron to every 10 minutes
  !cron 1h  - Set cron to every hour
  !cron off - Disable cron
  !update   - Pull latest code from GitHub
  !discover / scan - Scan headlines and present 2-3 video ideas
  !research / run research - Run deep research on approved idea
  !research "topic" - Run deep research on specific topic
  !help     - Show available commands
"""

import os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/projects/economy-fastforward/.env"))
import asyncio
import re
import subprocess
import signal
import sys
import threading
import time
import json
import logging
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

# ── Config ──────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
PIPELINE_DIR = os.path.expanduser("~/projects/economy-fastforward/skills/video-pipeline")
REPO_DIR = os.path.expanduser("~/projects/economy-fastforward")
PIPELINE_LOG = "/tmp/pipeline.log"
DISCOVERY_LOG = "/tmp/discovery.log"
ALLOWED_CHANNEL = os.environ.get("SLACK_CHANNEL", "")  # Empty = respond anywhere

# Track discovery messages for emoji reaction approval
# Maps message_ts -> list of ideas from that discovery scan
_discovery_messages = {}

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/tmp/pipeline-bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("pipeline-bot")

# ── Slack Client ────────────────────────────────────────────────────────────
web_client = WebClient(token=BOT_TOKEN)
bot_user_id = None


def get_bot_user_id():
    """Get the bot's own user ID so we can ignore our own messages."""
    global bot_user_id
    try:
        result = web_client.auth_test()
        bot_user_id = result["user_id"]
        log.info(f"Bot user ID: {bot_user_id}")
    except Exception as e:
        log.error(f"Failed to get bot user ID: {e}")


def send_message(channel: str, text: str):
    """Send a message to Slack."""
    try:
        web_client.chat_postMessage(channel=channel, text=text)
    except Exception as e:
        log.error(f"Failed to send Slack message: {e}")


# ── Command Handlers ───────────────────────────────────────────────────────

def cmd_status(channel: str):
    """Show pipeline status - what's in the queue."""
    try:
        result = subprocess.run(
            ["python3", "pipeline.py", "--status"],
            cwd=PIPELINE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        # If --status flag doesn't exist, fall back to checking Airtable directly
        if "unrecognized arguments" in output or "error" in output.lower():
            output = _get_status_fallback()
        send_message(channel, f"📊 *Pipeline Status*\n```\n{output[:2900]}\n```")
    except subprocess.TimeoutExpired:
        send_message(channel, "⏱️ Status check timed out (30s)")
    except Exception as e:
        send_message(channel, f"❌ Error getting status: {e}")


def _get_status_fallback():
    """Fallback status check - look for running processes and log tail."""
    lines = []

    # Check for running pipeline processes
    ps_result = subprocess.run(
        ["pgrep", "-af", "pipeline.py"],
        capture_output=True, text=True,
    )
    if ps_result.stdout.strip():
        lines.append("🔄 RUNNING:")
        for proc in ps_result.stdout.strip().split("\n"):
            lines.append(f"  {proc}")
    else:
        lines.append("💤 No pipeline process running")

    # Show last few log lines
    if os.path.exists(PIPELINE_LOG):
        tail = subprocess.run(
            ["tail", "-5", PIPELINE_LOG],
            capture_output=True, text=True,
        )
        if tail.stdout.strip():
            lines.append("\n📋 Last log entries:")
            lines.append(tail.stdout.strip())

    # Show cron status
    cron_result = subprocess.run(
        ["crontab", "-l"],
        capture_output=True, text=True,
    )
    cron_lines = [l for l in cron_result.stdout.split("\n") if l.strip() and not l.startswith("#")]
    if cron_lines:
        lines.append(f"\n⏰ Cron: {cron_lines[0]}")
    else:
        lines.append("\n⏰ Cron: OFF")

    return "\n".join(lines)


def cmd_run(channel: str):
    """Trigger pipeline immediately."""
    # Check if already running
    ps_result = subprocess.run(
        ["pgrep", "-f", "pipeline.py --run-queue"],
        capture_output=True, text=True,
    )
    if ps_result.stdout.strip():
        send_message(channel, "⚠️ Pipeline is already running. Use `kill` first if you want to restart.")
        return

    send_message(channel, "🚀 Starting pipeline...")
    try:
        # Run in background
        subprocess.Popen(
            ["python3", "pipeline.py", "--run-queue"],
            cwd=PIPELINE_DIR,
            stdout=open(PIPELINE_LOG, "a"),
            stderr=subprocess.STDOUT,
        )
        send_message(channel, "✅ Pipeline started. Use `logs` to monitor.")
    except Exception as e:
        send_message(channel, f"❌ Failed to start pipeline: {e}")


def cmd_kill(channel: str):
    """Kill any running pipeline process."""
    result = subprocess.run(
        ["pkill", "-f", "pipeline.py"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        send_message(channel, "🛑 Pipeline process killed.")
    else:
        send_message(channel, "💤 No pipeline process was running.")


def cmd_logs(channel: str, num_lines: int = 20):
    """Show recent pipeline logs."""
    if not os.path.exists(PIPELINE_LOG):
        send_message(channel, "📋 No log file found yet. Pipeline hasn't run.")
        return

    result = subprocess.run(
        ["tail", f"-{num_lines}", PIPELINE_LOG],
        capture_output=True, text=True,
    )
    output = result.stdout.strip() or "Log file is empty"
    send_message(channel, f"📋 *Last {num_lines} log lines:*\n```\n{output[:2900]}\n```")


def cmd_update(channel: str):
    """Pull latest code from GitHub."""
    send_message(channel, "🔄 Pulling latest code from GitHub...")
    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main", "--ff-only"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode == 0:
            if "Already up to date" in output:
                send_message(channel, "✅ Already up to date. No new changes.")
            else:
                # Show what changed
                log_result = subprocess.run(
                    ["git", "log", "--oneline", "-5"],
                    cwd=REPO_DIR,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                recent = log_result.stdout.strip()
                send_message(
                    channel,
                    f"✅ *Code updated successfully!*\n```\n{output[:1500]}\n```\n"
                    f"📋 *Recent commits:*\n```\n{recent[:1000]}\n```",
                )
        else:
            # ff-only failed — likely merge conflict or diverged history
            send_message(
                channel,
                f"⚠️ *Update failed* (fast-forward only). May need manual merge.\n```\n{stderr[:2000]}\n```",
            )
    except subprocess.TimeoutExpired:
        send_message(channel, "⏱️ Git pull timed out (60s). Check network connectivity.")
    except Exception as e:
        send_message(channel, f"❌ Update error: {e}")


def cmd_cron(channel: str, schedule: str = None):
    """View or change cron schedule."""
    if schedule is None:
        # Just show current cron
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        cron_lines = [l for l in result.stdout.split("\n") if l.strip() and not l.startswith("#")]
        if cron_lines:
            send_message(channel, f"⏰ *Current cron:*\n```\n{chr(10).join(cron_lines)}\n```")
        else:
            send_message(channel, "⏰ Cron is OFF (no active jobs)")
        return

    # Parse schedule shorthand
    cron_expr = None
    if schedule == "off":
        _update_cron(None)
        send_message(channel, "⏰ Cron disabled. Pipeline won't auto-run.")
        return
    elif schedule in ("5m", "5min"):
        cron_expr = "*/5 * * * *"
    elif schedule in ("10m", "10min"):
        cron_expr = "*/10 * * * *"
    elif schedule in ("15m", "15min"):
        cron_expr = "*/15 * * * *"
    elif schedule in ("30m", "30min"):
        cron_expr = "*/30 * * * *"
    elif schedule in ("1h", "1hr", "hour", "hourly"):
        cron_expr = "0 * * * *"
    elif schedule in ("2h", "2hr"):
        cron_expr = "0 */2 * * *"
    elif schedule in ("4h", "4hr"):
        cron_expr = "0 */4 * * *"
    else:
        send_message(channel, f"❓ Unknown schedule `{schedule}`. Try: `5m`, `10m`, `15m`, `30m`, `1h`, `2h`, `4h`, or `off`")
        return

    _update_cron(cron_expr)
    send_message(channel, f"⏰ Cron updated to `{cron_expr}`\nPipeline will auto-run on this schedule.")


def _update_cron(cron_expr: str = None):
    """Update crontab with new pipeline schedule.

    The cron command always pulls the latest code from GitHub before running
    the pipeline, so changes made via Claude Code (phone) take effect immediately.
    Uses --ff-only to avoid merge conflicts blocking the pipeline.
    """
    pipeline_cmd = (
        f"cd {REPO_DIR} && git pull origin main --ff-only >> {PIPELINE_LOG} 2>&1; "
        f"cd {PIPELINE_DIR} && python3 pipeline.py --run-queue >> {PIPELINE_LOG} 2>&1"
    )

    # Get existing crontab (minus our pipeline line)
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing_lines = result.stdout.split("\n") if result.returncode == 0 else []

    # Filter out any existing pipeline cron lines
    filtered = [l for l in existing_lines if "pipeline.py" not in l]

    # Add new line if not disabling
    if cron_expr:
        filtered.append(f"{cron_expr} {pipeline_cmd}")

    # Write new crontab
    new_crontab = "\n".join(filtered).strip() + "\n"
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    proc.communicate(input=new_crontab)


def send_message_with_ts(channel: str, text: str) -> str:
    """Send a message and return its timestamp (for reaction tracking)."""
    try:
        response = web_client.chat_postMessage(channel=channel, text=text)
        return response["ts"]
    except Exception as e:
        log.error(f"Failed to send Slack message: {e}")
        return ""


def add_reactions(channel: str, ts: str, emojis: list[str]):
    """Add emoji reactions to a message."""
    for emoji in emojis:
        try:
            web_client.reactions_add(channel=channel, name=emoji, timestamp=ts)
        except Exception as e:
            log.error(f"Failed to add reaction {emoji}: {e}")


# ── Discovery Scanner & Research Commands ──────────────────────────────────

def _run_async(coro):
    """Run an async function from sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def cmd_discover(channel: str, args: list = None):
    """Scan headlines and present 2-3 video ideas."""
    focus = " ".join(args) if args else None
    focus_msg = f" (focus: {focus})" if focus else ""
    send_message(channel, f"🔍 Scanning headlines{focus_msg}... This may take a moment.")

    try:
        # Import and run discovery scanner
        sys.path.insert(0, PIPELINE_DIR)
        from clients.anthropic_client import AnthropicClient
        from discovery_scanner import run_discovery, format_ideas_for_slack

        anthropic = AnthropicClient()
        result = _run_async(run_discovery(
            anthropic_client=anthropic,
            focus=focus,
        ))

        # Format and send to Slack
        slack_msg = format_ideas_for_slack(result)
        ts = send_message_with_ts(channel, slack_msg)

        if ts:
            # Track this message for emoji reaction approval
            _discovery_messages[ts] = result.get("ideas", [])

            # Add reaction emojis for approval
            idea_count = len(result.get("ideas", []))
            emojis = ["one", "two", "three"][:idea_count]
            add_reactions(channel, ts, emojis)

            log.info(
                f"Discovery posted: {idea_count} ideas, "
                f"message_ts={ts}"
            )

    except Exception as e:
        log.error(f"Discovery error: {e}", exc_info=True)
        send_message(channel, f"❌ Discovery scan failed: {e}")
    finally:
        # Clean up sys.path
        if PIPELINE_DIR in sys.path:
            sys.path.remove(PIPELINE_DIR)


def cmd_research(channel: str, args: list = None):
    """Run deep research on a topic or approved idea.

    Usage:
        research             — Research next approved idea from Airtable
        research "topic"     — Research a specific topic
        run research         — Same as research
    """
    # Check if topic was provided (quoted or unquoted)
    topic = None
    if args:
        raw = " ".join(args)
        # Strip surrounding quotes if present
        if (raw.startswith('"') and raw.endswith('"')) or \
           (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        topic = raw.strip()

    if topic:
        send_message(channel, f"🔬 Starting deep research on: _{topic}_")
    else:
        send_message(channel, "🔬 Looking for approved idea to research...")

    try:
        sys.path.insert(0, PIPELINE_DIR)
        from clients.anthropic_client import AnthropicClient
        from clients.airtable_client import AirtableClient
        from research_agent import run_research

        anthropic = AnthropicClient()
        airtable = AirtableClient()

        if not topic:
            # Find next approved idea
            approved = airtable.get_ideas_by_status("Approved", limit=1)
            if not approved:
                send_message(
                    channel,
                    "💤 No approved ideas in queue. "
                    "Use `discover` to find ideas, or `research \"topic\"` "
                    "for a specific topic."
                )
                return

            idea = approved[0]
            topic = idea.get("Video Title", "")
            record_id = idea.get("id", "")
            send_message(
                channel,
                f"🔬 Researching approved idea: _{topic}_"
            )

            # Run research with Airtable write-back
            payload = _run_async(run_research(
                anthropic_client=anthropic,
                topic=topic,
                context=idea.get("Hook Script", ""),
                airtable_client=airtable,
            ))

            # Update status to Ready For Scripting
            if record_id:
                try:
                    airtable.update_idea_status(record_id, "Ready For Scripting")
                except Exception as e:
                    log.warning(f"Could not update status: {e}")

            send_message(
                channel,
                f"✅ Research complete for: _{topic}_\n"
                f"Headline: {payload.get('headline', 'N/A')}\n"
                f"Status: Ready For Scripting"
            )
        else:
            # Direct topic research — save to Airtable
            payload = _run_async(run_research(
                anthropic_client=anthropic,
                topic=topic,
                airtable_client=airtable,
            ))

            send_message(
                channel,
                f"✅ Research complete for: _{topic}_\n"
                f"Headline: {payload.get('headline', 'N/A')}\n"
                f"Saved to Idea Concepts table."
            )

    except Exception as e:
        log.error(f"Research error: {e}", exc_info=True)
        send_message(channel, f"❌ Research failed: {e}")
    finally:
        if PIPELINE_DIR in sys.path:
            sys.path.remove(PIPELINE_DIR)


def handle_discovery_reaction(channel: str, ts: str, idea_index: int):
    """Handle emoji reaction on a discovery message — approve an idea.

    Writes the chosen idea to Airtable as 'Approved' and triggers
    deep research automatically.

    Args:
        channel: Slack channel ID
        ts: Message timestamp of the discovery results
        idea_index: 0-based index of the chosen idea
    """
    ideas = _discovery_messages.get(ts, [])
    if not ideas or idea_index >= len(ideas):
        log.warning(f"No ideas found for message ts={ts} index={idea_index}")
        return

    idea = ideas[idea_index]
    # Use first title option as the video title
    title_options = idea.get("title_options", [])
    title = title_options[0]["title"] if title_options else "Untitled"

    send_message(
        channel,
        f"✅ Idea approved: _{title}_\n"
        f"Writing to Airtable and starting research..."
    )

    try:
        sys.path.insert(0, PIPELINE_DIR)
        from clients.anthropic_client import AnthropicClient
        from clients.airtable_client import AirtableClient
        from research_agent import run_research

        anthropic = AnthropicClient()
        airtable = AirtableClient()

        # Write idea to Airtable as Approved
        idea_data = {
            "viral_title": title,
            "hook_script": idea.get("hook", ""),
            "narrative_logic": {
                "past_context": idea.get("historical_parallel_hint", ""),
                "present_parallel": idea.get("our_angle", ""),
                "future_prediction": "",
            },
            "writer_guidance": idea.get("our_angle", ""),
            "original_dna": json.dumps({
                "source": "discovery_scanner",
                "headline_source": idea.get("headline_source", ""),
                "formula_ids": [
                    t.get("formula_id", "") for t in title_options
                ],
                "estimated_appeal": idea.get("estimated_appeal", 0),
            }),
        }

        record = airtable.create_idea(idea_data, source="discovery_scanner")
        record_id = record["id"]

        # Set status to Approved (skip Idea Logged since Ryan just chose it)
        airtable.update_idea_status(record_id, "Approved")

        log.info(f"Idea written to Airtable: {record_id} — {title}")

        # Auto-trigger deep research
        send_message(channel, f"🔬 Auto-triggering deep research for: _{title}_")

        payload = _run_async(run_research(
            anthropic_client=anthropic,
            topic=title,
            context=idea.get("hook", "") + "\n" + idea.get("our_angle", ""),
            airtable_client=None,  # Don't create a duplicate record
        ))

        # Write research payload back to the same record
        research_json = json.dumps(payload)
        try:
            airtable.update_idea_field(record_id, "Research Payload", research_json)
        except Exception as e:
            if "UNKNOWN_FIELD_NAME" in str(e):
                log.info("Research Payload field not yet in Airtable")
            else:
                log.warning(f"Could not write Research Payload: {e}")

        # Advance status to Ready For Scripting
        airtable.update_idea_status(record_id, "Ready For Scripting")

        send_message(
            channel,
            f"✅ Research complete for: _{title}_\n"
            f"Headline: {payload.get('headline', title)}\n"
            f"Status: Ready For Scripting\n"
            f"Use `run` to start the full pipeline."
        )

        # Clean up tracking
        del _discovery_messages[ts]

    except Exception as e:
        log.error(f"Approval/research error: {e}", exc_info=True)
        send_message(channel, f"❌ Error processing approval: {e}")
    finally:
        if PIPELINE_DIR in sys.path:
            sys.path.remove(PIPELINE_DIR)


def cmd_help(channel: str):
    """Show available commands."""
    help_text = """🤖 *Pipeline Control Bot*

*Pipeline Commands:*
• `status` — Pipeline queue status & running processes
• `run` — Trigger pipeline immediately
• `kill` — Kill running pipeline process
• `logs` — Last 20 log lines (`logs 50` for more)

*Discovery & Research:*
• `discover` / `scan` — Scan headlines and present 2-3 video ideas
• `discover [focus]` — Scan with focus keyword (e.g., `discover BRICS`)
• `research` / `run research` — Run deep research on next approved idea
• `research "topic"` — Run deep research on a specific topic

*Scheduling & Admin:*
• `cron` — Show current schedule
• `cron 10m` — Set to every 10 min
• `cron 1h` — Set to every hour
• `cron off` — Disable auto-run
• `update` — Pull latest code from GitHub

*Animation:*
• `animstatus` — Show animation pipeline status
• `regen [N]` — Regenerate prompts for scene N
• `approve [N]` / `approve all` — Approve animation prompts

• `help` — This message"""
    send_message(channel, help_text)


# ── Command Router ─────────────────────────────────────────────────────────

COMMANDS = {
    "status": lambda ch, _: cmd_status(ch),
    "run research": lambda ch, args: cmd_research(ch, args),
    "run discover": lambda ch, args: cmd_discover(ch, args),
    "run": lambda ch, _: cmd_run(ch),
    "kill": lambda ch, _: cmd_kill(ch),
    "stop": lambda ch, _: cmd_kill(ch),
    "logs": lambda ch, args: cmd_logs(ch, int(args[0]) if args else 20),
    "cron": lambda ch, args: cmd_cron(ch, args[0] if args else None),
    "update": lambda ch, _: cmd_update(ch),
    "discover": lambda ch, args: cmd_discover(ch, args),
    "scan": lambda ch, args: cmd_discover(ch, args),
    "research": lambda ch, args: cmd_research(ch, args),
    "animstatus": lambda ch, _: cmd_animstatus(ch),
    "regen": lambda ch, args: cmd_regen(ch, int(args[0])) if args else None,
    "approve all": lambda ch, _: cmd_approveall(ch),
    "approve": lambda ch, args: cmd_approve(ch, int(args[0])) if args else None,
    "help": lambda ch, _: cmd_help(ch),
}


# Commands that run LLM calls and should execute in a background thread
_ASYNC_COMMANDS = {"discover", "scan", "research", "run discover", "run research"}


def handle_message(text: str, channel: str, user: str):
    """Route incoming message to command handler."""
    # Ignore bot's own messages
    if user == bot_user_id:
        return

    # Preserve original case for research topic parsing
    original_text = text.strip()
    text = original_text.lower()

    # Check if it's a command
    for cmd, handler in COMMANDS.items():
        if text.startswith(cmd):
            # For research command, use original case for topic
            if cmd in ("research",):
                args_text = original_text[len(cmd):].strip()
            else:
                args_text = text[len(cmd):].strip()
            args = args_text.split() if args_text else []
            log.info(f"Command: {cmd} from user {user} in {channel}")
            try:
                # Run LLM-calling commands in a thread
                if cmd in _ASYNC_COMMANDS:
                    thread = threading.Thread(
                        target=handler,
                        args=(channel, args),
                        daemon=True,
                    )
                    thread.start()
                else:
                    handler(channel, args)
            except Exception as e:
                log.error(f"Command error: {e}")
                send_message(channel, f"❌ Error: {e}")
            return


# ── Cron Failure Monitor ───────────────────────────────────────────────────

class LogMonitor:
    """Watch pipeline log for errors and notify Slack."""

    def __init__(self, notify_channel: str):
        self.notify_channel = notify_channel
        self.last_size = 0
        self.last_check = 0

    def check(self):
        """Check for new errors in the log file."""
        if not os.path.exists(PIPELINE_LOG):
            return

        current_size = os.path.getsize(PIPELINE_LOG)
        if current_size <= self.last_size:
            return

        try:
            with open(PIPELINE_LOG, "r") as f:
                f.seek(self.last_size)
                new_content = f.read()
            self.last_size = current_size

            # Check for errors
            error_patterns = ["Traceback", "Error:", "FAILED", "Exception"]
            for line in new_content.split("\n"):
                if any(p in line for p in error_patterns):
                    # Get surrounding context
                    lines = new_content.split("\n")
                    error_idx = next(i for i, l in enumerate(lines) if any(p in l for p in error_patterns))
                    context = "\n".join(lines[max(0, error_idx - 2):error_idx + 5])
                    send_message(
                        self.notify_channel,
                        f"🚨 *Pipeline Error Detected*\n```\n{context[:2900]}\n```",
                    )
                    break  # Only notify once per check
        except Exception as e:
            log.error(f"Log monitor error: {e}")


# ── Socket Mode Handler ───────────────────────────────────────────────────

def process_event(client: SocketModeClient, req: SocketModeRequest):
    """Handle incoming Slack events (messages and emoji reactions)."""
    # Acknowledge immediately
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

    if req.type == "events_api":
        event = req.payload.get("event", {})

        # Handle text messages
        if event.get("type") == "message" and "subtype" not in event:
            text = event.get("text", "")
            channel = event.get("channel", "")
            user = event.get("user", "")

            # Filter to allowed channel if set
            if ALLOWED_CHANNEL and channel != ALLOWED_CHANNEL:
                return

            handle_message(text, channel, user)

        # Handle emoji reactions on discovery messages
        elif event.get("type") == "reaction_added":
            reaction = event.get("reaction", "")
            user = event.get("user", "")
            item = event.get("item", {})
            item_ts = item.get("ts", "")
            channel = item.get("channel", "")

            # Ignore bot's own reactions
            if user == bot_user_id:
                return

            # Map number emoji to idea index
            reaction_map = {"one": 0, "two": 1, "three": 2}
            if reaction in reaction_map and item_ts in _discovery_messages:
                idea_index = reaction_map[reaction]
                log.info(
                    f"Discovery reaction: {reaction} from {user} "
                    f"on {item_ts} -> idea {idea_index + 1}"
                )
                # Run in a thread to avoid blocking the event loop
                thread = threading.Thread(
                    target=handle_discovery_reaction,
                    args=(channel, item_ts, idea_index),
                    daemon=True,
                )
                thread.start()


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    log.info("🤖 Pipeline Control Bot starting...")

    get_bot_user_id()

    # Find the notification channel (first channel bot is in)
    notify_channel = ALLOWED_CHANNEL
    if not notify_channel:
        try:
            result = web_client.conversations_list(types="public_channel,private_channel", limit=100)
            for ch in result["channels"]:
                if ch.get("is_member"):
                    notify_channel = ch["id"]
                    log.info(f"Notification channel: #{ch['name']} ({ch['id']})")
                    break
        except Exception as e:
            log.warning(f"Could not find notification channel: {e}")

    # Start log monitor
    monitor = LogMonitor(notify_channel) if notify_channel else None

    # Connect via Socket Mode
    socket_client = SocketModeClient(
        app_token=APP_TOKEN,
        web_client=web_client,
    )
    socket_client.socket_mode_request_listeners.append(process_event)
    socket_client.connect()
    log.info("✅ Connected to Slack. Listening for commands...")

    # Send startup message
    if notify_channel:
        send_message(notify_channel, "🤖 Pipeline Control Bot is online. Type `help` for commands.")

    # Keep alive + periodic log monitoring
    try:
        while True:
            time.sleep(30)
            if monitor:
                monitor.check()
    except KeyboardInterrupt:
        log.info("Bot shutting down...")
        if notify_channel:
            send_message(notify_channel, "🤖 Pipeline Control Bot is going offline.")


if __name__ == "__main__":
    main()


# ==================== ANIMATION CONTROL COMMANDS ====================

def cmd_animstatus(channel: str):
    """Show which scenes need prompt approval."""
    try:
        result = subprocess.run(
            ["python3", "-m", "animation.status"],
            cwd=ANIMATION_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        send_message(channel, f"```\n{output[:2900]}\n```")
    except Exception as e:
        send_message(channel, f"❌ Error: {e}")


def cmd_regen(channel: str, scene_num: int):
    """Regenerate prompts for a specific scene."""
    send_message(channel, f"🔄 Regenerating prompts for scene {scene_num}...")
    try:
        result = subprocess.run(
            ["python3", "-m", "animation.regen", str(scene_num)],
            cwd=ANIMATION_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        send_message(channel, f"```\n{output[:2900]}\n```")
    except Exception as e:
        send_message(channel, f"❌ Error: {e}")


def cmd_approve(channel: str, scene_num: int):
    """Approve prompts for a specific scene."""
    try:
        result = subprocess.run(
            ["python3", "-m", "animation.approve", str(scene_num)],
            cwd=ANIMATION_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        send_message(channel, f"```\n{output[:2900]}\n```")
    except Exception as e:
        send_message(channel, f"❌ Error: {e}")


def cmd_approveall(channel: str):
    """Approve all prompts for all scenes."""
    try:
        result = subprocess.run(
            ["python3", "-m", "animation.approve", "all"],
            cwd=ANIMATION_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        send_message(channel, f"```\n{output[:2900]}\n```")
    except Exception as e:
        send_message(channel, f"❌ Error: {e}")
