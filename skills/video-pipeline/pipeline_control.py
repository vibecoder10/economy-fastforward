"""Pipeline Control Bot - Slack bot for video production commands.

Run with: python pipeline_control.py
Requires: SLACK_BOT_TOKEN, SLACK_APP_TOKEN in environment

All commands are case-insensitive (e.g., "Research", "SCRIPT", "Help" all work).
"""

import os
import sys
import re
import asyncio
import json
import logging
import subprocess
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

# Load .env from project root — walk up to find it
_control_dir = os.path.dirname(os.path.abspath(__file__))
for _i in range(10):
    _env_path = os.path.join(_control_dir, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)
        break
    _parent = os.path.dirname(_control_dir)
    if _parent == _control_dir:
        break
    _control_dir = _parent

# Verify critical API keys are loaded
_openai_key = os.environ.get("OPENAI_API_KEY", "")
if _openai_key and not _openai_key.startswith("sk-xxxxx"):
    print(f"[env] OPENAI_API_KEY loaded ({len(_openai_key)} chars)")
else:
    print("[env] WARNING: OPENAI_API_KEY not found — audio sync will fail")

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

# Initialize Slack app
app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))

# Get the base directory for running scripts
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Track running process for kill command
current_process = None
current_task_name = None

# Stop signal for in-process async tasks (e.g. "run" auto-pipeline, inline research)
# When set, long-running loops should break at the next safe point.
_stop_event = asyncio.Event()

# Track discovery messages for emoji reaction approval
# Maps message_ts -> list of ideas from that discovery scan
_discovery_messages = {}

log = logging.getLogger("pipeline-control-bolt")


async def run_script_async(script_name: str, task_name: str, say, timeout: int = 600) -> tuple[int, str, str]:
    """Run a Python script asynchronously and return (returncode, stdout, stderr)."""
    global current_process, current_task_name

    script_path = os.path.join(BASE_DIR, script_name)
    current_task_name = task_name

    current_process = await asyncio.create_subprocess_exec(
        "python3", script_path,
        cwd=BASE_DIR,
        env=os.environ.copy(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            current_process.communicate(),
            timeout=timeout
        )
        returncode = current_process.returncode
        current_process = None
        current_task_name = None
        stdout_str = stdout.decode()
        stderr_str = stderr.decode()
        # If the process failed but stderr is empty, the error was
        # printed to stdout (e.g. pipeline returning error dicts).
        # Promote stdout to stderr so callers always have an error msg.
        if returncode and returncode != 0 and not stderr_str.strip():
            stderr_str = stdout_str
        return returncode, stdout_str, stderr_str
    except asyncio.TimeoutError:
        current_process.kill()
        current_process = None
        current_task_name = None
        raise subprocess.TimeoutExpired(script_name, timeout)
    except asyncio.CancelledError:
        current_process.kill()
        current_process = None
        current_task_name = None
        raise


@app.message(re.compile(r"hello", re.IGNORECASE))
async def handle_hello(message, say):
    """Respond to hello messages."""
    await say(f"Hey there <@{message['user']}>! Pipeline bot is ready.")


@app.message(re.compile(r"help", re.IGNORECASE))
async def handle_help(message, say):
    """Show available commands."""
    help_text = """*Pipeline Commands:*

*Auto-run*
- `run` - Pick up the pipeline where it left off and keep going (one step at a time)

*YouTube Pipeline*
- `script` / `run script` - Run script bot for idea with "Ready For Scripting" status
- `voice` / `run voice` - Run voice bot for idea with "Ready For Voice" status
- `prompts` / `run prompts` - Generate styled image prompts and images
- `images` / `run images` - Generate scene images only (for "Ready For Images" status)
- `sync` / `timing` - Run audio sync (Whisper alignment) to calculate scene durations
- `end images` / `run end images` - Generate end image prompts and images
- `thumbnail` / `run thumbnail` - Generate thumbnail for idea with "Ready For Thumbnail" status
- `render` / `run render` - Render videos only (skips other stages, one at a time)

*Animation Pipeline*
- `animate` / `animation` / `run animation` - Run animation pipeline for project with "Create" status

*Discovery & Research*
- `discover` / `scan` - Scan headlines and present 2-3 video ideas
- `discover [focus]` - Scan with focus keyword (e.g., `discover BRICS`)
- React 1️⃣ 2️⃣ 3️⃣ on discovery results to approve + auto-research
- `research` / `run research` - Run deep research on next approved idea
- `research "topic"` - Run deep research on a specific topic

*System*
- `stop` / `kill` - Stop the currently running pipeline
- `logs` / `animlogs` - Check if a pipeline is running
- `status` / `check` - Check current project status (both pipelines)
- `update` - Pull latest code from GitHub (auto-restarts if changes)
- `cron on` / `cron off` / `cron status` - Manage cron jobs (5 AM discover, 8 AM pipeline, health check, approvals)
- `help` - Show this message

_All commands are case-insensitive._
"""
    await say(help_text)


@app.message(re.compile(r"stop", re.IGNORECASE))
@app.message(re.compile(r"kill", re.IGNORECASE))
async def handle_stop(message, say):
    """Stop the currently running pipeline."""
    global current_process, current_task_name

    # Case 1: A subprocess is running (script, voice, images, etc.)
    if current_process is not None:
        task = current_task_name or "unknown task"
        try:
            current_process.terminate()
            await asyncio.sleep(0.5)
            if current_process and current_process.returncode is None:
                current_process.kill()
            current_process = None
            current_task_name = None
            await say(f":stop_sign: Killed `{task}`")
        except Exception as e:
            await say(f":x: Error stopping process: {e}")
        return

    # Case 2: An in-process async task is running (e.g. "run" auto-pipeline,
    # inline research). Signal it to stop at the next safe point.
    if current_task_name is not None:
        task = current_task_name
        _stop_event.set()
        await say(f":stop_sign: Stopping `{task}` — will halt after current step finishes.")
        return

    await say(":shrug: No pipeline currently running.")


@app.message(re.compile(r"^run$", re.IGNORECASE))
async def handle_run(message, say):
    """Pick up the YouTube pipeline where it left off and keep going."""
    global current_process, current_task_name
    if current_process or current_task_name:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    current_task_name = "run (auto-pipeline)"
    _stop_event.clear()  # reset stop signal for this run
    await say(":rocket: Starting auto-pipeline — checking Airtable for next step...")

    try:
        from pipeline import VideoPipeline

        pipeline = VideoPipeline()
        steps_done = 0
        max_steps = 15  # safety cap

        while steps_done < max_steps:
            # Check if user asked to stop between steps
            if _stop_event.is_set():
                await say(
                    f":stop_sign: Pipeline stopped by user after {steps_done} step(s)."
                )
                break

            result = await pipeline.run_next_step()

            if result.get("status") == "idle":
                if steps_done == 0:
                    await say(":zzz: Nothing to do — no ideas with an actionable status in the pipeline.")
                else:
                    await say(f":white_check_mark: Pipeline idle after {steps_done} step(s). All caught up!")
                break

            # STOP on errors — don't silently advance
            if result.get("status") == "failed" or result.get("error"):
                error_msg = result.get("error", "Unknown error")
                bot_name = result.get("bot", "Unknown")
                await say(
                    f":x: *Pipeline STOPPED* — {bot_name} failed\n"
                    f"Error: {error_msg}\n"
                    f"Steps completed: {steps_done}\n"
                    f"Status was NOT advanced. Fix the issue and `run` again."
                )
                break

            bot_name = result.get("bot", "step")
            new_status = result.get("new_status", "?")
            steps_done += 1
            await say(f":gear: Step {steps_done}: *{bot_name}* done — status now `{new_status}`")

        if steps_done >= max_steps:
            await say(f":warning: Stopped after {max_steps} steps (safety cap).")

    except asyncio.CancelledError:
        await say(f":stop_sign: Pipeline cancelled after {steps_done} step(s).")
    except Exception as e:
        log.error(f"run auto-pipeline error: {e}", exc_info=True)
        await say(f":x: Pipeline error: {e}")
    finally:
        current_task_name = None
        _stop_event.clear()


@app.message(re.compile(r"run script", re.IGNORECASE))
@app.message(re.compile(r"script", re.IGNORECASE))
async def handle_script(message, say):
    """Run the script bot."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":clapper: Starting script bot...")

    try:
        returncode, stdout, stderr = await run_script_async("run_script_bot.py", "script", say, timeout=300)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Script bot complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Script bot error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Script bot timed out after 5 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: Script bot was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run animation", re.IGNORECASE))
@app.message(re.compile(r"animation", re.IGNORECASE))
@app.message(re.compile(r"animate", re.IGNORECASE))
async def handle_animate(message, say):
    """Run the animation pipeline."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":movie_camera: Starting animation pipeline...")

    try:
        returncode, stdout, stderr = await run_script_async("run_animation.py", "animation", say, timeout=600)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Animation pipeline complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Animation error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Animation pipeline timed out after 10 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: Animation pipeline was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run prompts", re.IGNORECASE))
@app.message(re.compile(r"prompts", re.IGNORECASE))
async def handle_prompts(message, say):
    """Run prompts and start images generation."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":art: Starting prompts and images generation...")

    try:
        returncode, stdout, stderr = await run_script_async("run_youtube_prompts.py", "prompts", say, timeout=3600)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Prompts complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Prompts error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Prompts generation timed out after 60 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: Prompts generation was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run end images", re.IGNORECASE))
@app.message(re.compile(r"end images", re.IGNORECASE))
async def handle_end_images(message, say):
    """Run end images generation."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":frame_with_picture: Starting end images generation...")

    try:
        returncode, stdout, stderr = await run_script_async("run_end_images.py", "end images", say, timeout=1800)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: End images complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: End images error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: End images generation timed out after 30 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: End images generation was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run images", re.IGNORECASE))
@app.message(re.compile(r"^images$", re.IGNORECASE))
async def handle_images(message, say):
    """Run the image bot only (generates scene images for 'Ready For Images' idea)."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":frame_with_picture: Starting image bot... This will take several minutes.")

    try:
        returncode, stdout, stderr = await run_script_async("run_image_bot.py", "images", say, timeout=1800)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Image bot complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Image bot error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Image bot timed out after 30 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: Image bot was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run sync", re.IGNORECASE))
@app.message(re.compile(r"sync", re.IGNORECASE))
@app.message(re.compile(r"timing", re.IGNORECASE))
async def handle_audio_sync(message, say):
    """Run audio sync (Whisper alignment) to calculate scene durations."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":musical_note: Starting audio sync (Whisper alignment)...")

    try:
        returncode, stdout, stderr = await run_script_async("run_audio_sync.py", "audio sync", say, timeout=1800)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Audio sync complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Audio sync error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Audio sync timed out after 30 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: Audio sync was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run voice", re.IGNORECASE))
@app.message(re.compile(r"voice", re.IGNORECASE))
async def handle_voice(message, say):
    """Run the voice bot."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":studio_microphone: Starting voice bot...")

    try:
        returncode, stdout, stderr = await run_script_async("run_voice_bot.py", "voice", say, timeout=600)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Voice bot complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Voice bot error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Voice bot timed out after 10 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: Voice bot was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run thumbnail", re.IGNORECASE))
@app.message(re.compile(r"thumbnail", re.IGNORECASE))
async def handle_thumbnail(message, say):
    """Run the thumbnail bot."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":frame_with_picture: Starting thumbnail bot...")

    try:
        returncode, stdout, stderr = await run_script_async("run_thumbnail_bot.py", "thumbnail", say, timeout=300)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Thumbnail bot complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Thumbnail bot error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Thumbnail bot timed out after 5 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: Thumbnail bot was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run render", re.IGNORECASE))
@app.message(re.compile(r"^render$", re.IGNORECASE))
async def handle_render(message, say):
    """Render all videos at 'Ready To Render' one at a time."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    await say(":clapper: Starting render bot — will process videos one at a time...")

    try:
        # Render can take 60-90 min per video, set timeout to 4 hours
        returncode, stdout, stderr = await run_script_async(
            "run_render_bot.py", "render", say, timeout=14400
        )

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Render bot complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Render bot error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Render bot timed out after 4 hours")
    except asyncio.CancelledError:
        await say(":stop_sign: Render bot was stopped")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"run discover", re.IGNORECASE))
@app.message(re.compile(r"discover", re.IGNORECASE))
@app.message(re.compile(r"scan", re.IGNORECASE))
async def handle_discover(message, say, client):
    """Scan headlines and present 2-3 video ideas."""
    global current_process
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    # Extract optional focus keyword from message text
    text = message.get("text", "").strip()
    focus = re.sub(r"^(run\s+)?(?:discover|scan)\s*", "", text, flags=re.IGNORECASE).strip()
    channel = message.get("channel", "")

    focus_msg = f" (focus: {focus})" if focus else ""
    await say(f":mag: Scanning headlines{focus_msg}... This may take a moment.")

    try:
        from clients.anthropic_client import AnthropicClient
        from discovery_scanner import run_discovery, format_ideas_for_slack, build_option_map

        anthropic = AnthropicClient()

        result = await run_discovery(
            anthropic_client=anthropic,
            focus=focus or None,
        )

        slack_msg = format_ideas_for_slack(result)

        # Post via client to capture message timestamp for reaction tracking
        response = await client.chat_postMessage(channel=channel, text=slack_msg)
        ts = response.get("ts", "")

        if ts:
            # Track this message for emoji reaction approval
            _discovery_messages[ts] = result.get("ideas", [])

            # Add one reaction emoji per title option (not per idea)
            option_map = build_option_map(result.get("ideas", []))
            emoji_names = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
            emojis_to_add = emoji_names[:len(option_map)]
            for emoji in emojis_to_add:
                try:
                    await client.reactions_add(channel=channel, name=emoji, timestamp=ts)
                except Exception as e:
                    log.error(f"Failed to add reaction {emoji}: {e}")

            log.info(f"Discovery posted: {len(option_map)} options across {len(result.get('ideas', []))} ideas, message_ts={ts}")

    except Exception as e:
        await say(f":x: Discovery scan failed: {e}")


@app.event("reaction_added")
async def handle_reaction_added(event, client):
    """Handle emoji reactions — approve discovery ideas when a number is reacted.

    Each number maps to a specific idea + title combination via build_option_map.
    Checks both in-memory tracking (from Slack bot discover command) and
    the shared tracker file (from cron job --discover runs).
    """
    from discovery_scanner import build_option_map
    from discovery_tracker import (
        get_discovery_message, remove_discovery_message,
        is_reaction_processed, mark_reaction_processed,
    )

    reaction = event.get("reaction", "")
    user = event.get("user", "")
    item = event.get("item", {})
    item_ts = item.get("ts", "")
    channel = item.get("channel", "")

    # Map reaction emoji names to 0-based option index
    reaction_to_index = {
        "one": 0, "two": 1, "three": 2,
        "four": 3, "five": 4, "six": 5,
        "seven": 6, "eight": 7, "nine": 8,
    }
    if reaction not in reaction_to_index:
        return

    # Duplicate click protection — check if this reaction was already handled
    if is_reaction_processed(item_ts, reaction):
        log.info(f"Ignoring duplicate reaction: {reaction} on {item_ts}")
        return

    option_index = reaction_to_index[reaction]

    # Check in-memory tracking first (from Slack bot discover command)
    if item_ts in _discovery_messages:
        ideas = _discovery_messages[item_ts]
        option_map = build_option_map(ideas)
        if option_index >= len(option_map):
            return
        selected = option_map[option_index]
        log.info(
            f"Discovery reaction (in-memory): {reaction} from {user} "
            f"on {item_ts} -> idea {selected['idea_index'] + 1}, title: {selected['title']}"
        )
        # Mark as processed BEFORE starting work (prevents race with double-click)
        mark_reaction_processed(item_ts, reaction, selected["title"])
        await _handle_discovery_approval(
            client, channel, item_ts,
            selected["idea_index"],
            selected_title=selected["title"],
        )
        return

    # Check shared tracker file (from cron job --discover runs)
    tracked = get_discovery_message(item_ts)
    if tracked:
        ideas = tracked.get("ideas", [])
        airtable_ids = tracked.get("airtable_record_ids", [])
        option_map = build_option_map(ideas)
        if option_index >= len(option_map):
            return
        selected = option_map[option_index]
        log.info(
            f"Discovery reaction (cron-tracked): {reaction} from {user} "
            f"on {item_ts} -> idea {selected['idea_index'] + 1}, title: {selected['title']}"
        )
        # Mark as processed BEFORE starting work
        mark_reaction_processed(item_ts, reaction, selected["title"])
        await _handle_cron_discovery_approval(
            client, channel, item_ts,
            selected["idea_index"], ideas, airtable_ids,
            selected_title=selected["title"],
        )
        remove_discovery_message(item_ts)
        return


async def _handle_discovery_approval(
    client, channel: str, ts: str, idea_index: int,
    selected_title: str = None,
):
    """Approve a discovery idea and auto-trigger deep research.

    Writes the chosen idea to Airtable as 'Approved', triggers
    deep research, and updates status to 'Ready For Scripting'.

    Args:
        client: Slack WebClient for posting messages
        channel: Slack channel ID
        ts: Message timestamp of the discovery results
        idea_index: 0-based index of the chosen idea
        selected_title: Specific title chosen by user (if None, uses first title)
    """
    ideas = _discovery_messages.get(ts, [])
    if not ideas or idea_index >= len(ideas):
        log.warning(f"No ideas found for message ts={ts} index={idea_index}")
        return

    idea = ideas[idea_index]
    # Use the selected title, or fall back to first title option
    title_options = idea.get("title_options", [])
    title = selected_title or (title_options[0]["title"] if title_options else "Untitled")

    await client.chat_postMessage(
        channel=channel,
        text=(
            f":white_check_mark: Idea {idea_index + 1} approved: _{title}_\n"
            f"Writing to Airtable and starting deep research..."
        ),
    )

    try:
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

        # Set status to Approved
        airtable.update_idea_status(record_id, "Approved")
        log.info(f"Idea written to Airtable: {record_id} — {title}")

        # Auto-trigger deep research
        await client.chat_postMessage(
            channel=channel,
            text=f":microscope: Starting deep research for: _{title}_",
        )

        payload = await run_research(
            anthropic_client=anthropic,
            topic=title,
            context=idea.get("hook", "") + "\n" + idea.get("our_angle", ""),
            airtable_client=None,  # Don't create a duplicate record
        )

        # Write research payload back to the same record
        research_json = json.dumps(payload)
        try:
            airtable.update_idea_field(record_id, "Research Payload", research_json)
        except Exception as e:
            if "UNKNOWN_FIELD_NAME" in str(e):
                log.info("Research Payload field not yet in Airtable — skipping")
            else:
                log.warning(f"Could not write Research Payload: {e}")

        # Advance status to Ready For Scripting
        airtable.update_idea_status(record_id, "Ready For Scripting")

        await client.chat_postMessage(
            channel=channel,
            text=(
                f":white_check_mark: Research complete for: _{title}_\n"
                f"Headline: {payload.get('headline', title)}\n"
                f"Status: Ready For Scripting\n"
                f"Use `run` to start the full pipeline."
            ),
        )

        # Clean up tracking
        del _discovery_messages[ts]

    except Exception as e:
        log.error(f"Approval/research error: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel,
            text=f":x: Error processing approval: {e}",
        )


async def _handle_cron_discovery_approval(
    client, channel: str, ts: str, idea_index: int,
    ideas: list[dict], airtable_record_ids: list,
    selected_title: str = None,
):
    """Approve a discovery idea from the cron job's tracked messages.

    Unlike _handle_discovery_approval (which creates a new Airtable record),
    this uses the record already created by the cron --discover run and
    just updates its status + triggers research.

    Args:
        client: Slack WebClient for posting messages
        channel: Slack channel ID
        ts: Message timestamp of the discovery results
        idea_index: 0-based index of the chosen idea
        ideas: List of idea dicts from discovery scanner
        airtable_record_ids: List of Airtable record IDs (parallel to ideas)
        selected_title: Specific title chosen by user (if None, uses first title)
    """
    if not ideas or idea_index >= len(ideas):
        log.warning(f"No ideas found for cron message ts={ts} index={idea_index}")
        return

    idea = ideas[idea_index]
    title_options = idea.get("title_options", [])
    title = selected_title or (title_options[0]["title"] if title_options else "Untitled")

    # Get the existing Airtable record ID (already created by cron --discover)
    record_id = None
    if airtable_record_ids and idea_index < len(airtable_record_ids):
        record_id = airtable_record_ids[idea_index]

    await client.chat_postMessage(
        channel=channel,
        text=(
            f":white_check_mark: Idea {idea_index + 1} approved: _{title}_\n"
            f"Starting deep research..."
        ),
    )

    try:
        from clients.anthropic_client import AnthropicClient
        from clients.airtable_client import AirtableClient
        from research_agent import run_research

        anthropic = AnthropicClient()
        airtable = AirtableClient()

        # If we have an existing record, update it; otherwise create new
        if record_id:
            airtable.update_idea_status(record_id, "Approved")
            # Update Video Title to the user's chosen title
            if selected_title:
                try:
                    airtable.update_idea_field(record_id, "Video Title", selected_title)
                except Exception as e:
                    log.warning(f"Could not update Video Title: {e}")
            log.info(f"Updated existing Airtable record: {record_id} — {title}")
        else:
            # Fallback: create a new record (shouldn't normally happen)
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
            airtable.update_idea_status(record_id, "Approved")

        # Auto-trigger deep research
        await client.chat_postMessage(
            channel=channel,
            text=f":microscope: Running deep research for: _{title}_",
        )

        payload = await run_research(
            anthropic_client=anthropic,
            topic=title,
            context=idea.get("hook", "") + "\n" + idea.get("our_angle", ""),
            airtable_client=None,
        )

        # Write research payload back to the record
        research_json = json.dumps(payload)
        try:
            airtable.update_idea_field(record_id, "Research Payload", research_json)
        except Exception as e:
            if "UNKNOWN_FIELD_NAME" in str(e):
                log.info("Research Payload field not yet in Airtable — skipping")
            else:
                log.warning(f"Could not write Research Payload: {e}")

        # Advance status to Ready For Scripting (will be picked up by 8 AM pipeline)
        airtable.update_idea_status(record_id, "Ready For Scripting")

        await client.chat_postMessage(
            channel=channel,
            text=(
                f":white_check_mark: Research complete for: _{title}_\n"
                f"Headline: {payload.get('headline', title)}\n"
                f"Status: *Ready For Scripting*\n"
                f"The 8 AM pipeline run will pick this up automatically, or use `run` to start now."
            ),
        )

    except Exception as e:
        log.error(f"Cron discovery approval error: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel,
            text=f":x: Error processing approval: {e}",
        )


@app.message(re.compile(r"run research", re.IGNORECASE))
@app.message(re.compile(r"research", re.IGNORECASE))
async def handle_research(message, say):
    """Run deep research on a topic or next approved idea."""
    global current_process, current_task_name
    if current_process or current_task_name:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    # Extract topic from message text (preserve original case)
    text = message.get("text", "").strip()
    topic = re.sub(r"^(run\s+)?research\s*", "", text, flags=re.IGNORECASE).strip()

    # Strip surrounding quotes if present
    if (topic.startswith('"') and topic.endswith('"')) or \
       (topic.startswith("'") and topic.endswith("'")):
        topic = topic[1:-1].strip()

    _stop_event.clear()  # reset stop signal for this run

    try:
        from clients.anthropic_client import AnthropicClient
        from clients.airtable_client import AirtableClient
        from research_agent import run_research

        anthropic = AnthropicClient()
        airtable = AirtableClient()

        # ------------------------------------------------------------------
        # Case 1: No topic — find next approved idea, research it, and
        # update the SAME record (don't create a duplicate).
        # ------------------------------------------------------------------
        if not topic:
            await say(":microscope: Starting research on next approved idea...")

            approved = airtable.get_ideas_by_status("Approved", limit=1)
            if not approved:
                await say(
                    ":zzz: No approved ideas in queue. "
                    "Use `research \"topic\"` for a specific topic."
                )
                return

            idea = approved[0]
            record_id = idea["id"]
            title = idea.get("Video Title", "Untitled")
            current_task_name = f"research: {title}"

            await say(f":microscope: Researching approved idea: _{title}_")

            # Run research inline (don't create a new record)
            payload = await run_research(
                anthropic_client=anthropic,
                topic=title,
                context=idea.get("Hook Script", ""),
                airtable_client=None,  # Don't create a duplicate record
            )

            # Write research payload back to the SAME record
            research_json = json.dumps(payload)
            try:
                from research_agent import infer_framework_from_research
                research_fields = {
                    "Research Payload": research_json,
                    "Source URLs": payload.get("source_bibliography", ""),
                    "Executive Hook": payload.get("executive_hook", ""),
                    "Thesis": payload.get("thesis", ""),
                }
                if not idea.get("Framework Angle"):
                    research_fields["Framework Angle"] = infer_framework_from_research(payload)
                airtable.update_idea_fields(record_id, research_fields)
            except Exception as e:
                log.warning(f"Could not write research fields: {e}")
                try:
                    airtable.update_idea_field(record_id, "Research Payload", research_json)
                except Exception:
                    log.warning("Could not write Research Payload field either")

            # Advance status to Ready For Scripting
            airtable.update_idea_status(record_id, "Ready For Scripting")

            current_task_name = None
            await say(
                f":white_check_mark: Research complete for: _{title}_\n"
                f"Headline: {payload.get('headline', title)}\n"
                f"Status: Ready For Scripting"
            )
            return

        # ------------------------------------------------------------------
        # Case 2: Explicit topic — run as subprocess, create new record.
        # ------------------------------------------------------------------
        await say(f":microscope: Starting deep research on: _{topic}_")
        current_task_name = f"research: {topic}"

        current_process = await asyncio.create_subprocess_exec(
            "python3", "research_agent.py", "--topic", topic, "--save",
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                current_process.communicate(),
                timeout=600
            )
            returncode = current_process.returncode
            current_process = None
            current_task_name = None

            if returncode == 0:
                output = stdout.decode()[-3000:]
                await say(f":white_check_mark: Research complete for: _{topic}_\n```{output}```")
            else:
                error = stderr.decode()[-1500:]
                await say(f":x: Research error:\n```{error}```")

        except asyncio.TimeoutError:
            current_process.kill()
            current_process = None
            current_task_name = None
            await say(":warning: Research timed out after 10 minutes")
        except asyncio.CancelledError:
            current_process.kill()
            current_process = None
            current_task_name = None
            await say(":stop_sign: Research was stopped")

    except Exception as e:
        current_process = None
        current_task_name = None
        await say(f":x: Research error: {e}")


@app.message(re.compile(r"status", re.IGNORECASE))
@app.message(re.compile(r"check", re.IGNORECASE))
async def handle_status(message, say):
    """Check current project status."""
    await say(":mag: Checking project status...")

    try:
        script_path = os.path.join(BASE_DIR, "check_project.py")
        result = subprocess.run(
            ["python3", script_path],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            await say(f"```{result.stdout}```")
        else:
            await say(f":x: Status check error:\n```{result.stderr}```")

    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"animlogs", re.IGNORECASE))
@app.message(re.compile(r"logs", re.IGNORECASE))
async def handle_animlogs(message, say):
    """Show recent animation pipeline logs."""
    if current_process is None:
        await say(":shrug: No pipeline currently running.")
        return

    await say(f":scroll: Currently running: `{current_task_name}`\n_Output will appear when complete or use `stop` to cancel._")


@app.message(re.compile(r"update", re.IGNORECASE))
async def handle_update(message, say):
    """Pull latest code from GitHub and restart."""
    await say(":arrows_counterclockwise: Pulling latest code from GitHub...")

    try:
        # Run git pull
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            output = result.stdout.strip() or "Already up to date."
            await say(f":white_check_mark: Update complete!\n```{output}```")

            # Check if there were actual changes
            if "Already up to date" not in output:
                await say(":rocket: Restarting bot to apply changes...")
                # Spawn new bot process before exiting so there's no downtime
                # (previously relied on cron health check — up to 15 min wait)
                bot_script = os.path.join(BASE_DIR, "pipeline_control.py")
                new_proc = subprocess.Popen(
                    [sys.executable, bot_script],
                    cwd=BASE_DIR,
                    stdout=open("/tmp/pipeline-bot.log", "w"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                # Update PID file so health check tracks the new process
                with open("/tmp/pipeline-bot.pid", "w") as f:
                    f.write(str(new_proc.pid))
                await asyncio.sleep(2)
                os._exit(0)
        else:
            await say(f":x: Git pull failed:\n```{result.stderr}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Git pull timed out after 60 seconds")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"^cron", re.IGNORECASE))
async def handle_cron(message, say):
    """Manage pipeline cron jobs."""
    text = message.get("text", "").strip().lower()

    REPO_DIR = os.path.dirname(os.path.dirname(BASE_DIR))
    PYTHON3 = "python3"

    # Cron entry templates
    DISCOVER_ENTRY = (
        f"0 5 * * * cd {REPO_DIR} && git pull origin main --ff-only >> /tmp/pipeline-discover.log 2>&1; "
        f"cd {BASE_DIR} && timeout 600 {PYTHON3} pipeline.py --discover >> /tmp/pipeline-discover.log 2>&1"
    )
    QUEUE_ENTRY = (
        f"0 8 * * * cd {REPO_DIR} && git pull origin main --ff-only >> /tmp/pipeline-queue.log 2>&1; "
        f"cd {BASE_DIR} && timeout 14400 {PYTHON3} pipeline.py --run-queue >> /tmp/pipeline-queue.log 2>&1"
    )
    HEALTHCHECK_ENTRY = (
        f"*/15 * * * * cd {BASE_DIR} && bash bot_healthcheck.sh >> /tmp/pipeline-bot-health.log 2>&1"
    )
    APPROVAL_ENTRY = (
        f"*/30 * * * * cd {BASE_DIR} && timeout 600 {PYTHON3} approval_watcher.py >> /tmp/pipeline-approval.log 2>&1"
    )

    GREP_PATTERN = "pipeline-discover\\|pipeline-queue\\|pipeline-bot-health\\|pipeline-approval\\|Pipeline Cron\\|Daily idea\\|Daily pipeline\\|bot_healthcheck\\|approval_watcher"

    if "off" in text:
        # Remove all pipeline cron jobs
        try:
            result = subprocess.run(
                ["bash", "-c", f"crontab -l 2>/dev/null | grep -v '{GREP_PATTERN}' | crontab -"],
                capture_output=True, text=True, timeout=10,
            )
            await say(":stop_sign: All pipeline cron jobs removed (discover, pipeline, health check, approval watcher).")
        except Exception as e:
            await say(f":x: Could not remove cron jobs: {e}")
        return

    if "on" in text or "setup" in text:
        # Install all cron jobs (CRON_TZ ensures times are Pacific, not UTC)
        try:
            all_entries = f"CRON_TZ=America/Los_Angeles\\n{DISCOVER_ENTRY}\\n{QUEUE_ENTRY}\\n{HEALTHCHECK_ENTRY}\\n{APPROVAL_ENTRY}"
            result = subprocess.run(
                ["bash", "-c", f'(crontab -l 2>/dev/null | grep -v "{GREP_PATTERN}"; echo -e "{all_entries}") | crontab -'],
                capture_output=True, text=True, timeout=10,
            )
            await say(
                ":clock5: Pipeline cron jobs installed! (All times in Pacific)\n"
                "• *5:00 AM PT daily* → `--discover` (scan headlines, post ideas to Slack)\n"
                "• *8:00 AM PT daily* → `--run-queue` (process all stages through to Ready To Render)\n"
                "• *Every 15 min* → Bot health check (auto-restart if Slack bot dies)\n"
                "• *Every 30 min* → Approval watcher (catch manual Airtable approvals)\n"
                "_Discovery: 10 min timeout. Pipeline: 4 hour timeout._"
            )
        except Exception as e:
            await say(f":x: Could not install cron jobs: {e}")
        return

    if "status" in text:
        # Show current cron jobs
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                await say(f":clock3: Current cron jobs:\n```{result.stdout.strip()}```")
            else:
                await say(":zzz: No cron jobs installed. Use `cron on` to set up.")
        except Exception as e:
            await say(f":x: Could not check cron: {e}")
        return

    # Default: show help
    await say(
        "*Cron Commands:*\n"
        "• `cron on` / `cron setup` — Install all 4 cron jobs (discover, pipeline, health check, approvals)\n"
        "• `cron off` — Remove all pipeline cron jobs\n"
        "• `cron status` — Show current cron schedule"
    )


async def main():
    """Start the Slack bot."""
    print("=" * 60)
    print("PIPELINE CONTROL BOT")
    print("=" * 60)
    print("\nCommands (case-insensitive):")
    print("  run                     - Auto-continue pipeline from current status")
    print("  script / run script     - Run script bot")
    print("  voice / run voice       - Run voice bot")
    print("  prompts / run prompts   - Generate prompts and start images")
    print("  images / run images     - Generate scene images only")
    print("  end images              - Generate end images")
    print("  thumbnail               - Generate thumbnail")
    print("  animate / animation     - Run animation pipeline")
    print("  discover / scan         - Scan headlines for video ideas")
    print("  research / run research - Run deep research on approved idea")
    print('  research "topic"        - Run deep research on specific topic')
    print("  stop / kill             - Stop running pipeline")
    print("  logs / animlogs         - Check if pipeline running")
    print("  status / check          - Check project status (both pipelines)")
    print("  update                  - Pull latest code (auto-restart)")
    print("  cron on/off/status      - Manage scheduled cron jobs")
    print("  help                    - Show help")
    print("\nListening for Slack messages...")

    handler = AsyncSocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
