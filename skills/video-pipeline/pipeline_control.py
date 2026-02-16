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
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

# Initialize Slack app
app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))

# Get the base directory for running scripts
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Track running process for kill command
current_process = None
current_task_name = None

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
        return returncode, stdout.decode(), stderr.decode()
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
- `run` - Pick up the pipeline where it left off and keep going (script -> voice -> prompts -> images -> thumbnail)

*YouTube Pipeline*
- `script` / `run script` - Run script bot for idea with "Ready For Scripting" status
- `voice` / `run voice` - Run voice bot for idea with "Ready For Voice" status
- `prompts` / `run prompts` - Generate styled image prompts and images
- `images` / `run images` - Generate scene images only (for "Ready For Images" status)
- `end images` / `run end images` - Generate end image prompts and images
- `thumbnail` / `run thumbnail` - Generate thumbnail for idea with "Ready For Thumbnail" status

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
- `help` - Show this message

_All commands are case-insensitive._
"""
    await say(help_text)


@app.message(re.compile(r"stop", re.IGNORECASE))
@app.message(re.compile(r"kill", re.IGNORECASE))
async def handle_stop(message, say):
    """Stop the currently running pipeline."""
    global current_process, current_task_name

    if current_process is None:
        await say(":shrug: No pipeline currently running.")
        return

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


@app.message(re.compile(r"^run$", re.IGNORECASE))
async def handle_run(message, say):
    """Pick up the YouTube pipeline where it left off and keep going."""
    global current_process, current_task_name
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    current_task_name = "run (auto-pipeline)"
    await say(":rocket: Starting auto-pipeline — checking Airtable for next step...")

    try:
        from pipeline import VideoPipeline

        pipeline = VideoPipeline()
        steps_done = 0
        max_steps = 15  # safety cap

        while steps_done < max_steps:
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

    except Exception as e:
        log.error(f"run auto-pipeline error: {e}", exc_info=True)
        await say(f":x: Pipeline error: {e}")
    finally:
        current_task_name = None


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
        returncode, stdout, stderr = await run_script_async("run_prompts_and_images.py", "prompts", say, timeout=600)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Prompts complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Prompts error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Prompts generation timed out after 10 minutes")
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
        returncode, stdout, stderr = await run_script_async("run_end_images.py", "end images", say, timeout=900)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: End images complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: End images error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: End images generation timed out after 15 minutes")
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
        returncode, stdout, stderr = await run_script_async("run_image_bot.py", "images", say, timeout=900)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Image bot complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Image bot error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Image bot timed out after 15 minutes")
    except asyncio.CancelledError:
        await say(":stop_sign: Image bot was stopped")
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
        from discovery_scanner import run_discovery, format_ideas_for_slack

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

            # Add reaction emojis so user can click to approve
            idea_count = len(result.get("ideas", []))
            emojis = ["one", "two", "three"][:idea_count]
            for emoji in emojis:
                try:
                    await client.reactions_add(channel=channel, name=emoji, timestamp=ts)
                except Exception as e:
                    log.error(f"Failed to add reaction {emoji}: {e}")

            log.info(f"Discovery posted: {idea_count} ideas, message_ts={ts}")

    except Exception as e:
        await say(f":x: Discovery scan failed: {e}")


@app.event("reaction_added")
async def handle_reaction_added(event, client):
    """Handle emoji reactions — approve discovery ideas when 1/2/3 is reacted."""
    reaction = event.get("reaction", "")
    user = event.get("user", "")
    item = event.get("item", {})
    item_ts = item.get("ts", "")
    channel = item.get("channel", "")

    # Only handle number reactions on tracked discovery messages
    reaction_map = {"one": 0, "two": 1, "three": 2}
    if reaction not in reaction_map or item_ts not in _discovery_messages:
        return

    idea_index = reaction_map[reaction]
    log.info(
        f"Discovery reaction: {reaction} from {user} "
        f"on {item_ts} -> idea {idea_index + 1}"
    )

    await _handle_discovery_approval(client, channel, item_ts, idea_index)


async def _handle_discovery_approval(client, channel: str, ts: str, idea_index: int):
    """Approve a discovery idea and auto-trigger deep research.

    Writes the chosen idea to Airtable as 'Approved', triggers
    deep research, and updates status to 'Ready For Scripting'.

    Args:
        client: Slack WebClient for posting messages
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


@app.message(re.compile(r"run research", re.IGNORECASE))
@app.message(re.compile(r"research", re.IGNORECASE))
async def handle_research(message, say):
    """Run deep research on a topic or next approved idea."""
    global current_process, current_task_name
    if current_process:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    # Extract topic from message text (preserve original case)
    text = message.get("text", "").strip()
    topic = re.sub(r"^(run\s+)?research\s*", "", text, flags=re.IGNORECASE).strip()

    # Strip surrounding quotes if present
    if (topic.startswith('"') and topic.endswith('"')) or \
       (topic.startswith("'") and topic.endswith("'")):
        topic = topic[1:-1].strip()

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
                # Exit cleanly - systemd will auto-restart with new code
                await asyncio.sleep(1)
                os._exit(0)
        else:
            await say(f":x: Git pull failed:\n```{result.stderr}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Git pull timed out after 60 seconds")
    except Exception as e:
        await say(f":x: Error: {e}")


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
    print("  help                    - Show help")
    print("\nListening for Slack messages...")

    handler = AsyncSocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
