"""Webhook server for Airtable button triggers.

Run with: python webhook_server.py
Then add Button fields in Airtable that call these endpoints.
"""

import os
import asyncio
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env'))

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from animation.airtable_client import AnimationAirtableClient
from animation.image_generator import ImagePromptGenerator
from clients.image_client import ImageClient
from clients.google_client import GoogleClient

app = Flask(__name__)

# Initialize clients (reused across requests)
airtable = AnimationAirtableClient()
prompt_gen = ImagePromptGenerator()
image_client = ImageClient()
google_client = GoogleClient()


def run_async(coro):
    """Run async function in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_core_image_url(project_name: str) -> str:
    """Look up the Core Image URL for a project from Airtable."""
    try:
        project = airtable.get_project_by_name(project_name)
        if project:
            attachments = project.get("Core Image", [])
            if attachments and isinstance(attachments, list):
                return attachments[0].get("url", "")
    except Exception:
        pass
    return ""


async def generate_start_image_async(scene_id: str):
    """Generate start image for a scene."""
    # Get scene
    scenes = await airtable.get_scenes_for_project_by_id(scene_id)
    if not scenes:
        return {"error": f"Scene {scene_id} not found"}

    scene = scenes[0]
    scene_num = scene.get("scene_order", "?")
    prompt = scene.get("start_image_prompt")

    if not prompt:
        return {"error": f"Scene {scene_num} has no start_image_prompt"}

    if scene.get("start_image"):
        return {"error": f"Scene {scene_num} already has start_image"}

    print(f"Generating start image for Scene {scene_num}...")

    # Get project folder
    project_name = scene.get("Project Name")
    if isinstance(project_name, list):
        project_name = project_name[0] if project_name else "Unknown"

    # Get Core Image URL for reference
    core_image_url = _get_core_image_url(project_name)
    if not core_image_url:
        return {"error": f"No Core Image found on project '{project_name}'"}

    folder = google_client.get_or_create_folder(project_name)
    folder_id = folder["id"]

    # Generate image using Seed Dream 4.5 Edit with Core Image reference
    result = await image_client.generate_scene_image(prompt, core_image_url)

    if not result or not result.get("url"):
        return {"error": "Image generation failed"}

    # Download and upload
    image_content = await image_client.download_image(result["url"])
    filename = f"Scene_{str(scene_num).zfill(2)}.png"
    drive_file = google_client.upload_image(image_content, filename, folder_id)
    drive_url = google_client.make_file_public(drive_file["id"])

    # Update Airtable
    await airtable.update_scene(
        scene_id,
        {
            "start_image": [{"url": drive_url}],
            "image done": True,
        }
    )

    print(f"  Done! {drive_url}")
    return {"success": True, "scene": scene_num, "url": drive_url}


async def generate_end_image_async(scene_id: str):
    """Generate end image for a scene."""
    # Get scene
    scenes = await airtable.get_scenes_for_project_by_id(scene_id)
    if not scenes:
        return {"error": f"Scene {scene_id} not found"}

    scene = scenes[0]
    scene_num = scene.get("scene_order", "?")
    end_prompt = scene.get("end_image_prompt")
    start_prompt = scene.get("start_image_prompt")

    # Generate end prompt if missing
    if not end_prompt and start_prompt:
        print(f"Generating end prompt for Scene {scene_num}...")
        end_prompt = await prompt_gen.generate_end_image_prompt(scene, start_prompt)
        await airtable.update_scene(scene_id, {"end_image_prompt": end_prompt})

    if not end_prompt:
        return {"error": f"Scene {scene_num} has no end_image_prompt"}

    if scene.get("end_image"):
        return {"error": f"Scene {scene_num} already has end_image"}

    print(f"Generating end image for Scene {scene_num}...")

    # Get project folder
    project_name = scene.get("Project Name")
    if isinstance(project_name, list):
        project_name = project_name[0] if project_name else "Unknown"

    # Get Core Image URL for reference
    core_image_url = _get_core_image_url(project_name)
    if not core_image_url:
        return {"error": f"No Core Image found on project '{project_name}'"}

    folder = google_client.get_or_create_folder(project_name)
    folder_id = folder["id"]

    # Generate end image with Seed Dream 4.5 Edit (Core Image as reference)
    result = await image_client.generate_scene_image(
        prompt=end_prompt,
        reference_image_url=core_image_url,
    )

    if not result or not result.get("url"):
        return {"error": "Image generation failed"}

    # Download and upload
    image_content = await image_client.download_image(result["url"])
    filename = f"Scene_{str(scene_num).zfill(2)}_end.png"
    drive_file = google_client.upload_image(image_content, filename, folder_id)
    drive_url = google_client.make_file_public(drive_file["id"])

    # Update Airtable
    await airtable.update_scene(
        scene_id,
        {"end_image": [{"url": drive_url}]}
    )

    print(f"  Done! {drive_url}")
    return {"success": True, "scene": scene_num, "url": drive_url}


@app.route("/generate/start/<scene_id>", methods=["GET", "POST"])
def generate_start_image(scene_id: str):
    """Endpoint to generate start image for a scene."""
    try:
        result = run_async(generate_start_image_async(scene_id))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/generate/end/<scene_id>", methods=["GET", "POST"])
def generate_end_image(scene_id: str):
    """Endpoint to generate end image for a scene."""
    try:
        result = run_async(generate_end_image_async(scene_id))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print("Starting webhook server on http://localhost:5050")
    print("\nEndpoints:")
    print("  GET/POST /generate/start/<scene_id> - Generate start image")
    print("  GET/POST /generate/end/<scene_id>   - Generate end image")
    print("  GET      /health                    - Health check")
    print("\nFor Airtable buttons, use:")
    print("  http://localhost:5050/generate/start/{record_id}")
    print("  http://localhost:5050/generate/end/{record_id}")
    app.run(host="0.0.0.0", port=5050, debug=True)
