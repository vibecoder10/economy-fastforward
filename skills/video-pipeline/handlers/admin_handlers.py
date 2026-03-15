"""Admin handlers — env vars, restart, disk, logs.

Extracted from pipeline_control.py for debuggability.
All functions take (message, say) — decorators applied in pipeline_control.py.
"""

import os
import re
import sys
import asyncio
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_env_path() -> str:
    """Return absolute path to the project .env file."""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env"))


def _set_env_var(env_path: str, key: str, value: str) -> None:
    """Set a key=value in the .env file (replace if exists, append if not)."""
    if os.path.exists(env_path):
        content = open(env_path).read()
    else:
        content = ""

    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(f"{key}={value}", content)
    else:
        content = content.rstrip() + f"\n{key}={value}\n"

    with open(env_path, "w") as f:
        f.write(content)

    os.environ[key] = value


def _mask_value(value: str) -> str:
    """Mask a secret value for display."""
    if len(value) <= 8:
        return "***"
    return value[:4] + "..." + value[-4:]


async def handle_set_key(message, say):
    """Set OPENAI_API_KEY in the project .env file from Slack."""
    match = re.search(r"set\s+(?:openai[_\s]*(?:api[_\s]*)?)?key\s+(sk-\S+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `set key sk-proj-...`")
        return
    # Delegate to set env
    fake = {"text": f"set env OPENAI_API_KEY={match.group(1).strip()}", "user": message.get("user", "")}
    await handle_set_env(fake, say)


async def handle_set_env(message, say):
    """Set any environment variable in the project .env file."""
    match = re.search(r"set\s+env\s+(\w+)\s*=\s*(.+)", message["text"], re.IGNORECASE)
    if not match:
        await say(":x: Usage: `set env KEY=VALUE`")
        return

    key = match.group(1).strip()
    value = match.group(2).strip().strip("'").strip('"')

    if not key or not value:
        await say(":x: Usage: `set env KEY=VALUE`")
        return

    env_path = _get_env_path()
    try:
        _set_env_var(env_path, key, value)
        await say(f":white_check_mark: `{key}` set in `{env_path}`\nValue: `{_mask_value(value)}`")
    except Exception as e:
        await say(f":x: Failed to set {key}: {e}")


async def handle_show_env(message, say):
    """Show all env vars from the project .env file (values masked)."""
    env_path = _get_env_path()

    if not os.path.exists(env_path):
        await say(f":x: No `.env` file found at `{env_path}`")
        return

    try:
        lines = []
        for line in open(env_path).read().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if value and not value.startswith("xxxxx"):
                status = ":white_check_mark:"
                display = _mask_value(value)
            else:
                status = ":x:"
                display = "(not set / placeholder)"
            lines.append(f"{status} `{key}` = `{display}`")

        if lines:
            header = f"*Environment variables* (`{env_path}`):\n"
            await say(header + "\n".join(lines))
        else:
            await say(f":shrug: `.env` file is empty at `{env_path}`")
    except Exception as e:
        await say(f":x: Error reading .env: {e}")


async def handle_restart(message, say):
    """Restart the bot process."""
    await say(":arrows_counterclockwise: Restarting bot...")
    try:
        # Use the pipeline_control.py path from the actual BASE_DIR
        pipeline_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bot_script = os.path.join(pipeline_base, "pipeline_control.py")
        new_proc = subprocess.Popen(
            [sys.executable, bot_script],
            cwd=pipeline_base,
            stdout=open("/tmp/pipeline-bot.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        with open("/tmp/pipeline-bot.pid", "w") as f:
            f.write(str(new_proc.pid))
        await say(f":white_check_mark: New bot started (PID: {new_proc.pid}). Shutting down old instance...")
        await asyncio.sleep(2)
        os._exit(0)
    except Exception as e:
        await say(f":x: Restart failed: {e}")


async def handle_disk(message, say):
    """Show disk usage on the VPS."""
    try:
        pipeline_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Overall disk usage
        df_result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=10,
        )
        # Project directory size
        du_result = subprocess.run(
            ["du", "-sh", os.path.abspath(os.path.join(pipeline_base, "..", ".."))],
            capture_output=True, text=True, timeout=30,
        )
        # Tmp/logs size
        tmp_result = subprocess.run(
            ["du", "-sh", "/tmp/pipeline-bot.log",
             "/tmp/pipeline-discover.log",
             "/tmp/pipeline-queue.log"],
            capture_output=True, text=True, timeout=10,
        )

        parts = [":floppy_disk: *Disk Usage*\n"]
        if df_result.returncode == 0:
            parts.append(f"*System:*\n```{df_result.stdout.strip()}```\n")
        if du_result.returncode == 0:
            parts.append(f"*Project:* `{du_result.stdout.strip()}`\n")
        if tmp_result.stdout.strip():
            parts.append(f"*Logs:*\n```{tmp_result.stdout.strip()}```")

        await say("\n".join(parts))
    except Exception as e:
        await say(f":x: Error checking disk: {e}")


async def handle_tail_logs(message, say):
    """Show last N lines of pipeline bot log."""
    text = message.get("text", "")
    # Extract optional line count (default 30)
    num_match = re.search(r"(\d+)", text)
    num_lines = min(int(num_match.group(1)), 100) if num_match else 30

    log_files = {
        "Bot": "/tmp/pipeline-bot.log",
        "Discover": "/tmp/pipeline-discover.log",
        "Queue": "/tmp/pipeline-queue.log",
    }

    found_any = False
    for label, path in log_files.items():
        if not os.path.exists(path):
            continue
        try:
            result = subprocess.run(
                ["tail", f"-{num_lines}", path],
                capture_output=True, text=True, timeout=10,
            )
            if result.stdout.strip():
                found_any = True
                output = result.stdout[-3000:]  # Slack message limit
                await say(f":scroll: *{label} Log* (last {num_lines} lines of `{path}`):\n```{output}```")
        except Exception:
            pass

    if not found_any:
        await say(":shrug: No log files found.")
