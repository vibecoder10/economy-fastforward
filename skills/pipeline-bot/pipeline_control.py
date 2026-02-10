#!/usr/bin/env python3
"""
Pipeline Control Bot - Lightweight Slack bot for controlling the video pipeline.
No AI, no Anthropic API calls. Just listens for commands and runs bash.

Commands:
  !status    - Show pipeline queue status from Airtable
  !run       - Trigger pipeline immediately
  !animate   - Run animation pipeline (checks animation Airtable, resumes where it left off)
  !kill      - Kill any running pipeline process
  !logs      - Show last 20 lines of pipeline log
  !animlogs  - Show last 20 lines of animation log
  !cron      - Show current cron schedule
  !cron 10m  - Set cron to every 10 minutes
  !cron 1h   - Set cron to every hour
  !cron off  - Disable cron
  !help      - Show available commands
"""

import os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/projects/economy-fastforward/.env"))
import re
import subprocess
import signal
import sys
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
ANIMATION_DIR = os.path.expanduser("~/projects/economy-fastforward")
PIPELINE_LOG = "/tmp/pipeline.log"
ANIMATION_LOG = "/tmp/animation-pipeline.log"
ALLOWED_CHANNEL = os.environ.get("SLACK_CHANNEL", "")  # Empty = respond anywhere

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

    # Check for running main pipeline processes
    ps_result = subprocess.run(
        ["pgrep", "-af", "pipeline.py --run-queue"],
        capture_output=True, text=True,
    )
    if ps_result.stdout.strip():
        lines.append("🔄 MAIN PIPELINE RUNNING:")
        for proc in ps_result.stdout.strip().split("\n"):
            lines.append(f"  {proc}")
    else:
        lines.append("💤 Main pipeline: not running")

    # Check for running animation pipeline
    anim_result = subprocess.run(
        ["pgrep", "-af", "animation.pipeline"],
        capture_output=True, text=True,
    )
    if anim_result.stdout.strip():
        lines.append("🎬 ANIMATION PIPELINE RUNNING:")
        for proc in anim_result.stdout.strip().split("\n"):
            lines.append(f"  {proc}")
    else:
        lines.append("💤 Animation pipeline: not running")

    # Show last few main pipeline log lines
    if os.path.exists(PIPELINE_LOG):
        tail = subprocess.run(
            ["tail", "-5", PIPELINE_LOG],
            capture_output=True, text=True,
        )
        if tail.stdout.strip():
            lines.append("\n📋 Last main pipeline log entries:")
            lines.append(tail.stdout.strip())

    # Show last few animation log lines
    if os.path.exists(ANIMATION_LOG):
        tail = subprocess.run(
            ["tail", "-5", ANIMATION_LOG],
            capture_output=True, text=True,
        )
        if tail.stdout.strip():
            lines.append("\n🎬 Last animation log entries:")
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


def cmd_animate(channel: str):
    """Trigger the animation pipeline — checks the animation Airtable and resumes where it left off."""
    # Check if already running
    ps_result = subprocess.run(
        ["pgrep", "-f", "animation.pipeline"],
        capture_output=True, text=True,
    )
    if ps_result.stdout.strip():
        send_message(channel, "⚠️ Animation pipeline is already running. Use `kill` first if you want to restart.")
        return

    send_message(channel, "🎬 Starting animation pipeline...")
    try:
        # Run in background — uses python -m to run the animation module
        subprocess.Popen(
            ["python3", "-m", "animation.pipeline"],
            cwd=ANIMATION_DIR,
            stdout=open(ANIMATION_LOG, "a"),
            stderr=subprocess.STDOUT,
        )
        send_message(channel, "✅ Animation pipeline started. Use `animlogs` to monitor.")
    except Exception as e:
        send_message(channel, f"❌ Failed to start animation pipeline: {e}")


def cmd_animlogs(channel: str, num_lines: int = 20):
    """Show recent animation pipeline logs."""
    if not os.path.exists(ANIMATION_LOG):
        send_message(channel, "📋 No animation log file found yet. Animation pipeline hasn't run.")
        return

    result = subprocess.run(
        ["tail", f"-{num_lines}", ANIMATION_LOG],
        capture_output=True, text=True,
    )
    output = result.stdout.strip() or "Log file is empty"
    send_message(channel, f"🎬 *Last {num_lines} animation log lines:*\n```\n{output[:2900]}\n```")


def cmd_kill(channel: str):
    """Kill any running pipeline process (main pipeline and animation)."""
    killed = []

    # Kill main pipeline
    result = subprocess.run(
        ["pkill", "-f", "pipeline.py --run-queue"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        killed.append("main pipeline")

    # Kill animation pipeline
    result = subprocess.run(
        ["pkill", "-f", "animation.pipeline"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        killed.append("animation pipeline")

    if killed:
        send_message(channel, f"🛑 Killed: {', '.join(killed)}")
    else:
        send_message(channel, "💤 No pipeline processes were running.")


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
    """Update crontab with new pipeline schedule."""
    pipeline_cmd = f"cd {PIPELINE_DIR} && python3 pipeline.py --run-queue >> {PIPELINE_LOG} 2>&1"

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


def cmd_help(channel: str):
    """Show available commands."""
    help_text = """🤖 *Pipeline Control Bot*

*Commands:*
• `status` — Pipeline queue status & running processes
• `run` — Trigger main video pipeline immediately
• `animate` — Run animation pipeline (checks animation Airtable, resumes where left off)
• `kill` — Kill all running pipeline processes
• `logs` — Last 20 main pipeline log lines (`logs 50` for more)
• `animlogs` — Last 20 animation log lines (`animlogs 50` for more)
• `cron` — Show current schedule
• `cron 10m` — Set to every 10 min
• `cron 1h` — Set to every hour
• `cron off` — Disable auto-run
• `help` — This message"""
    send_message(channel, help_text)


# ── Command Router ─────────────────────────────────────────────────────────

COMMANDS = {
    "status": lambda ch, _: cmd_status(ch),
    "run": lambda ch, _: cmd_run(ch),
    "animate": lambda ch, _: cmd_animate(ch),
    "run animation": lambda ch, _: cmd_animate(ch),
    "kill": lambda ch, _: cmd_kill(ch),
    "stop": lambda ch, _: cmd_kill(ch),
    "animlogs": lambda ch, args: cmd_animlogs(ch, int(args[0]) if args else 20),
    "logs": lambda ch, args: cmd_logs(ch, int(args[0]) if args else 20),
    "cron": lambda ch, args: cmd_cron(ch, args[0] if args else None),
    "help": lambda ch, _: cmd_help(ch),
}


def handle_message(text: str, channel: str, user: str):
    """Route incoming message to command handler."""
    # Ignore bot's own messages
    if user == bot_user_id:
        return

    text = text.strip().lower()

    # Check if it's a command
    for cmd, handler in COMMANDS.items():
        if text.startswith(cmd):
            args = text[len(cmd):].strip().split() if len(text) > len(cmd) else []
            log.info(f"Command: {cmd} from user {user} in {channel}")
            try:
                handler(channel, args)
            except Exception as e:
                log.error(f"Command error: {e}")
                send_message(channel, f"❌ Error: {e}")
            return


# ── Cron Failure Monitor ───────────────────────────────────────────────────

class LogMonitor:
    """Watch pipeline logs for errors and notify Slack."""

    def __init__(self, notify_channel: str):
        self.notify_channel = notify_channel
        self.last_sizes = {PIPELINE_LOG: 0, ANIMATION_LOG: 0}

    def check(self):
        """Check for new errors in all log files."""
        self._check_log(PIPELINE_LOG, "Pipeline")
        self._check_log(ANIMATION_LOG, "Animation Pipeline")

    def _check_log(self, log_path: str, label: str):
        """Check a single log file for new errors."""
        if not os.path.exists(log_path):
            return

        current_size = os.path.getsize(log_path)
        if current_size <= self.last_sizes.get(log_path, 0):
            return

        try:
            with open(log_path, "r") as f:
                f.seek(self.last_sizes.get(log_path, 0))
                new_content = f.read()
            self.last_sizes[log_path] = current_size

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
                        f"🚨 *{label} Error Detected*\n```\n{context[:2900]}\n```",
                    )
                    break  # Only notify once per check
        except Exception as e:
            log.error(f"Log monitor error ({label}): {e}")


# ── Socket Mode Handler ───────────────────────────────────────────────────

def process_event(client: SocketModeClient, req: SocketModeRequest):
    """Handle incoming Slack events."""
    # Acknowledge immediately
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

    if req.type == "events_api":
        event = req.payload.get("event", {})

        if event.get("type") == "message" and "subtype" not in event:
            text = event.get("text", "")
            channel = event.get("channel", "")
            user = event.get("user", "")

            # Filter to allowed channel if set
            if ALLOWED_CHANNEL and channel != ALLOWED_CHANNEL:
                return

            handle_message(text, channel, user)


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
