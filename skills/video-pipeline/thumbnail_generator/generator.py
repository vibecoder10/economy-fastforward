"""Main entry point for EFF Thumbnail & Title Generator.

Generates thumbnails via Nano Banana Pro (Kie.ai) and pairs them with
matched titles using proven formula patterns.

Usage:
    from thumbnail_generator.generator import produce_thumbnail_and_title

    result = produce_thumbnail_and_title(
        topic="China's $140 Billion Dollar Trap",
        tags=["china", "dollar", "trap"],
        template_vars={...},
        title_formula="country_dollar",
        title_vars={...},
    )
"""

import json
import os
import time

import requests
from pathlib import Path

from .templates import TEMPLATE_A, TEMPLATE_B, TEMPLATE_C, select_template
from .titles import TITLE_FORMULAS, generate_title
from .validator import validate_thumbnail
from .config import (
    CREATE_TASK_URL,
    RECORD_INFO_URL,
    MODEL_NAME,
    ASPECT_RATIO,
    OUTPUT_FORMAT,
    MAX_ATTEMPTS,
    COST_PER_IMAGE,
    POLL_INITIAL_WAIT,
    POLL_INTERVAL,
    POLL_MAX_ATTEMPTS,
)


def _get_api_key(api_key: str = None) -> str:
    """Resolve API key from argument, then environment.

    Checks KIE_API_KEY first (spec convention), then KIE_AI_API_KEY
    (existing pipeline convention).
    """
    key = api_key or os.environ.get("KIE_API_KEY") or os.environ.get("KIE_AI_API_KEY")
    if not key:
        raise ValueError(
            "API key not set. Provide api_key argument or set "
            "KIE_API_KEY / KIE_AI_API_KEY environment variable."
        )
    return key


def generate_thumbnail(
    prompt: str,
    output_path: str,
    api_key: str = None,
) -> dict:
    """Call Nano Banana Pro API and save the result.

    Uses Kie.ai's task-based API: create task -> poll for completion ->
    download result image.

    Args:
        prompt: The full image generation prompt.
        output_path: Local file path to save the PNG thumbnail.
        api_key: Optional API key override.

    Returns:
        Dict with 'path', 'prompt', 'cost' keys.

    Raises:
        ValueError: If API key is not available.
        requests.HTTPError: If API call fails.
        TimeoutError: If polling exceeds max attempts.
    """
    key = _get_api_key(api_key)

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    # Step 1: Create the generation task
    payload = {
        "model": MODEL_NAME,
        "input": {
            "prompt": prompt,
            "aspect_ratio": ASPECT_RATIO,  # Always "16:9"
            "output_format": OUTPUT_FORMAT,  # Always "png"
        },
    }

    response = requests.post(CREATE_TASK_URL, json=payload, headers=headers, timeout=60)
    response.raise_for_status()

    task_data = response.json()
    task_id = task_data.get("data", {}).get("taskId")
    if not task_id:
        raise ValueError(f"No task ID returned from API: {task_data}")

    # Step 2: Poll for completion
    time.sleep(POLL_INITIAL_WAIT)
    image_url = _poll_for_result(task_id, key)

    # Step 3: Download and save the image
    if image_url:
        img_response = requests.get(image_url, timeout=60)
        img_response.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(img_response.content)

    return {
        "path": output_path,
        "prompt": prompt,
        "cost": COST_PER_IMAGE,
    }


def _poll_for_result(task_id: str, api_key: str) -> str:
    """Poll Kie.ai for task completion and return the image URL.

    Args:
        task_id: The task ID from create_image.
        api_key: API key for authentication.

    Returns:
        Image URL string.

    Raises:
        TimeoutError: If polling exceeds max attempts.
        RuntimeError: If the task reports failure.
    """
    headers = {"Authorization": f"Bearer {api_key}"}

    for attempt in range(POLL_MAX_ATTEMPTS):
        response = requests.get(
            RECORD_INFO_URL,
            headers=headers,
            params={"taskId": task_id},
            timeout=30,
        )
        response.raise_for_status()

        data = response.json().get("data", {})
        task_status = data.get("status")
        task_state = data.get("state")

        # Status codes: 0=Queue, 1=Running, 2=Success, 3=Failed
        if task_status == 3 or str(task_state).lower() in ("fail", "failed", "failure", "error"):
            raise RuntimeError(f"Image generation failed (state={task_state}, status={task_status})")

        result_json = data.get("resultJson")
        if result_json:
            if isinstance(result_json, str):
                result_data = json.loads(result_json)
            else:
                result_data = result_json

            result_urls = result_data.get("resultUrls", [])
            if result_urls:
                return result_urls[0]

        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Polling timed out after {POLL_MAX_ATTEMPTS} attempts for task {task_id}")


def produce_thumbnail_and_title(
    topic: str,
    tags: list[str] = None,
    template_vars: dict = None,
    title_formula: str = None,
    title_vars: dict = None,
    output_dir: str = "./thumbnails",
    api_key: str = None,
) -> dict:
    """Full pipeline: select template, fill variables, generate image, validate.

    Args:
        topic: Video topic string.
        tags: Optional list of tags for template selection.
        template_vars: Dict of variables to fill the selected template.
        title_formula: Key from TITLE_FORMULAS (e.g. "trap", "slow_death").
        title_vars: Dict of variables to fill the title formula.
        output_dir: Where to save the thumbnail.
        api_key: Optional API key override.

    Returns:
        Dict with title, thumbnail_path, template_used, prompt,
        attempts, passed_validation, total_cost, and optionally
        needs_manual_review.
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1. Select template
    template_key = select_template(topic, tags)

    # 2. Fill prompt template
    templates = {
        "template_a": TEMPLATE_A,
        "template_b": TEMPLATE_B,
        "template_c": TEMPLATE_C,
    }
    prompt = templates[template_key].format(**(template_vars or {}))

    # 3. Generate title
    title = None
    if title_formula and title_vars:
        title = generate_title(title_formula, title_vars)

    # 4. Generate thumbnail with retry and validation
    slug = topic.lower().replace(" ", "-")[:30]
    passed = False
    checks = {}
    result = {}
    attempt = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        output_path = os.path.join(output_dir, f"{slug}_thumbnail_v{attempt}.png")
        try:
            result = generate_thumbnail(prompt, output_path, api_key=api_key)
            passed, checks = validate_thumbnail(output_path)
            if passed:
                break
        except Exception as e:
            result = {"path": output_path, "prompt": prompt, "cost": COST_PER_IMAGE, "error": str(e)}
            passed = False

    output = {
        "title": title,
        "thumbnail_path": result.get("path", ""),
        "template_used": template_key,
        "prompt": prompt,
        "attempts": attempt,
        "passed_validation": passed,
        "validation_checks": checks,
        "total_cost": attempt * COST_PER_IMAGE,
    }

    if not passed:
        output["needs_manual_review"] = True

    return output
