"""Pipeline Control Bot - Slack bot for video production commands.

Run with: python pipeline_control.py
Requires: SLACK_BOT_TOKEN, SLACK_APP_TOKEN in environment
"""

import os
import sys
import asyncio
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

# Initialize Slack app
app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))

# Get the base directory for running scripts
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_script(script_name: str, timeout: int = 600) -> tuple[int, str, str]:
    """Run a Python script and return (returncode, stdout, stderr)."""
    script_path = os.path.join(BASE_DIR, script_name)
    result = subprocess.run(
        ["python3", script_path],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


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
- `status` / `check` - Check current project status
- `help` - Show this message
"""
    await say(help_text)


@app.message("script")
@app.message("run script")
async def handle_script(message, say):
    """Run the script bot."""
    await say(":clapper: Starting script bot...")

    try:
        returncode, stdout, stderr = run_script("run_script_bot.py", timeout=300)

        if returncode == 0:
            # Truncate output if too long
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Script bot complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Script bot error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Script bot timed out after 5 minutes")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message("animate")
@app.message("animation")
@app.message("run animation")
async def handle_animate(message, say):
    """Run the animation pipeline."""
    await say(":movie_camera: Starting animation pipeline...")

    try:
        returncode, stdout, stderr = run_script("run_animation.py", timeout=600)

        if returncode == 0:
            # Truncate output if too long
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Animation pipeline complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Animation error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Animation pipeline timed out after 10 minutes")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message("prompts")
@app.message("run prompts")
async def handle_prompts(message, say):
    """Run prompts and start images generation."""
    await say(":art: Starting prompts and images generation...")

    try:
        returncode, stdout, stderr = run_script("run_prompts_and_images.py", timeout=600)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: Prompts complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: Prompts error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: Prompts generation timed out after 10 minutes")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message("end images")
@app.message("run end images")
async def handle_end_images(message, say):
    """Run end images generation."""
    await say(":frame_with_picture: Starting end images generation...")

    try:
        returncode, stdout, stderr = run_script("run_end_images.py", timeout=900)

        if returncode == 0:
            output = stdout[-3000:] if len(stdout) > 3000 else stdout
            await say(f":white_check_mark: End images complete!\n```{output}```")
        else:
            error = stderr[-1500:] if len(stderr) > 1500 else stderr
            await say(f":x: End images error:\n```{error}```")

    except subprocess.TimeoutExpired:
        await say(":warning: End images generation timed out after 15 minutes")
    except Exception as e:
        await say(f":x: Error: {e}")


@app.message("status")
@app.message("check")
async def handle_status(message, say):
    """Check current project status."""
    await say(":mag: Checking project status...")

    try:
        returncode, stdout, stderr = run_script("check_project.py", timeout=30)

        if returncode == 0:
            await say(f"```{stdout}```")
        else:
            await say(f":x: Status check error:\n```{stderr}```")

    except Exception as e:
        await say(f":x: Error: {e}")


async def main():
    """Start the Slack bot."""
    print("=" * 60)
    print(":robot_face: PIPELINE CONTROL BOT")
    print("=" * 60)
    print("\nCommands:")
    print("  script / run script     - Run script bot")
    print("  animate / animation     - Run animation pipeline")
    print("  prompts / run prompts   - Generate prompts and start images")
    print("  end images              - Generate end images")
    print("  status / check          - Check project status")
    print("  help                    - Show help")
    print("\nListening for Slack messages...")

    handler = AsyncSocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
