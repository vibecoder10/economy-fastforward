"""Pipeline Control Bot - Slack bot for video production commands.

Run with: python pipeline_control.py
Requires: SLACK_BOT_TOKEN, SLACK_APP_TOKEN in environment
"""

import os
import re
import sys
import asyncio
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
REPO_ROOT = os.path.join(BASE_DIR, '..', '..')

# Track running process for kill command
current_process = None
current_task_name = None


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


@app.message("hello")
async def handle_hello(message, say):
    """Respond to hello messages."""
    await say(f"Hey there <@{message['user']}>! Pipeline bot is ready.")


@app.message("help")
async def handle_help(message, say):
    """Show available commands."""
    help_text = """*Pipeline Commands:*
- `script` / `run script` - Run script bot for idea with "Ready For Scripting" status
- `animate` / `animation` / `run animation` - Run animation pipeline for project with "Create" status
- `prompts` / `run prompts` - Generate start image prompts and images
- `end images` / `run end images` - Generate end image prompts and images
- `stop` / `kill` - Stop the currently running pipeline
- `logs` / `animlogs` - Check if a pipeline is running
- `status` / `check` - Check current project status
- `update` - Pull latest code from GitHub (auto-restarts if changes)

*Animation Control:*
- `animstatus` - Show scene prompt approval status
- `approve <num>` - Approve prompts for a specific scene
- `approve all` - Approve all scene prompts
- `regen <num>` - Regenerate prompts for a specific scene

- `help` - Show this message
"""
    await say(help_text)


@app.message("stop")
@app.message("kill")
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


@app.message("script")
@app.message("run script")
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


@app.message("animate")
@app.message("animation")
@app.message("run animation")
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


@app.message("prompts")
@app.message("run prompts")
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


@app.message("end images")
@app.message("run end images")
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


@app.message("status")
@app.message("check")
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


@app.message("animlogs")
@app.message("logs")
async def handle_animlogs(message, say):
    """Show recent animation pipeline logs."""
    if current_process is None:
        await say(":shrug: No pipeline currently running.")
        return

    await say(f":scroll: Currently running: `{current_task_name}`\n_Output will appear when complete or use `stop` to cancel._")


@app.message("update")
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


# ==================== ANIMATION CONTROL COMMANDS ====================

@app.message("animstatus")
async def handle_animstatus(message, say):
    """Show which scenes need prompt approval."""
    try:
        result = subprocess.run(
            ["python3", "-m", "animation.status"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        await say(f"```{output[:2900]}```")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message("approve all")
async def handle_approveall(message, say):
    """Approve all prompts for all scenes."""
    try:
        result = subprocess.run(
            ["python3", "-m", "animation.approve", "all"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        await say(f"```{output[:2900]}```")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"^approve (\d+)$"))
async def handle_approve(message, say, context):
    """Approve prompts for a specific scene."""
    scene_num = context["matches"][0]
    try:
        result = subprocess.run(
            ["python3", "-m", "animation.approve", scene_num],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        await say(f"```{output[:2900]}```")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message(re.compile(r"^regen (\d+)$"))
async def handle_regen(message, say, context):
    """Regenerate prompts for a specific scene."""
    scene_num = context["matches"][0]
    await say(f":arrows_counterclockwise: Regenerating prompts for scene {scene_num}...")
    try:
        result = subprocess.run(
            ["python3", "-m", "animation.regen", scene_num],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip() or result.stderr.strip() or "No output"
        await say(f"```{output[:2900]}```")
    except Exception as e:
        await say(f":x: Error: {e}")


async def main():
    """Start the Slack bot."""
    print("=" * 60)
    print("PIPELINE CONTROL BOT")
    print("=" * 60)
    print("\nCommands:")
    print("  script / run script     - Run script bot")
    print("  animate / animation     - Run animation pipeline")
    print("  prompts / run prompts   - Generate prompts and start images")
    print("  end images              - Generate end images")
    print("  animstatus              - Show scene prompt approval status")
    print("  approve <num|all>       - Approve scene prompts")
    print("  regen <num>             - Regenerate scene prompts")
    print("  stop / kill             - Stop running pipeline")
    print("  logs / animlogs         - Check if pipeline running")
    print("  status / check          - Check project status")
    print("  update                  - Pull latest code (auto-restart)")
    print("  help                    - Show help")
    print("\nListening for Slack messages...")

    handler = AsyncSocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
