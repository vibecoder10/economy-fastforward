"""Video animation via Veo 3.1 Fast — submits frame pairs and polls for completion."""

import asyncio
import json
import httpx
from typing import Optional

from animation.config import (
    KIE_API_KEY,
    KIE_CREATE_TASK_URL,
    KIE_RECORD_INFO_URL,
    VEO_MODEL,
)


class Animator:
    """Submits frame pairs to Veo 3.1 Fast for animation and polls for results."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or KIE_API_KEY
        if not self.api_key:
            raise ValueError("KIE_AI_API_KEY not found in environment")

    async def animate_scene(
        self,
        start_image_url: str,
        end_image_url: str,
        motion_description: str,
        duration: int = 8,
    ) -> Optional[str]:
        """Submit a frame pair to Veo 3.1 Fast for animation.

        Args:
            start_image_url: URL of the start frame
            end_image_url: URL of the end frame
            motion_description: Text prompt describing the motion between frames
            duration: Clip duration in seconds (default 8)

        Returns:
            URL of the generated video clip, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": VEO_MODEL,
            "input": {
                "image_urls": [start_image_url, end_image_url],
                "prompt": motion_description,
                "duration": str(duration),
            },
        }

        print(f"      \U0001f3ac Submitting to Veo 3.1 Fast (duration: {duration}s)...")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        KIE_CREATE_TASK_URL,
                        headers=headers,
                        json=payload,
                        timeout=60.0,
                    )

                    if response.status_code != 200:
                        print(f"      \u274c Veo API error: {response.status_code} - {response.text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        return None

                    task_data = response.json()
                    data_obj = task_data.get("data")
                    if not data_obj:
                        print(f"      \u274c No 'data' in response: {task_data}")
                        continue

                    task_id = data_obj.get("taskId")
                    if not task_id:
                        print(f"      \u274c No task ID returned: {task_data}")
                        continue

                    print(f"      \U0001f3ac Animation task started: {task_id}")

                    # Wait before polling — video generation is slower than images
                    await asyncio.sleep(15)

                    result_url = await self._poll_for_video(task_id)
                    if result_url:
                        print(f"      \u2705 Animation complete")
                        return result_url

                    print(f"      \u26a0\ufe0f Attempt {attempt + 1} failed. Retrying...")

            except Exception as e:
                print(f"      \u274c Animation error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5 * (attempt + 1))

        print(f"      \u274c All animation retry attempts failed")
        return None

    async def _poll_for_video(
        self,
        task_id: str,
        max_attempts: int = 120,
        poll_interval: float = 5.0,
    ) -> Optional[str]:
        """Poll for video generation completion with exponential backoff.

        Args:
            task_id: Task ID to poll
            max_attempts: Maximum polling attempts
            poll_interval: Base seconds between polls

        Returns:
            Video URL on success, None on failure
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        KIE_RECORD_INFO_URL,
                        headers=headers,
                        params={"taskId": task_id},
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    status = response.json()
            except Exception as e:
                print(f"      \u26a0\ufe0f Poll error: {e}")
                await asyncio.sleep(poll_interval)
                continue

            if not status:
                await asyncio.sleep(poll_interval)
                continue

            data = status.get("data", {})
            task_status = data.get("status")
            task_state = data.get("state")

            # Check for failure
            if (task_status == 3 or
                str(task_status).lower() in ["failed", "failure", "error"] or
                str(task_state).lower() in ["fail", "failed", "failure", "error"]):
                print(f"      \u26a0\ufe0f Veo task reported failure (State: {task_state}, Status: {task_status})")
                return None

            # Check for results
            result_json = data.get("resultJson")
            if result_json:
                if isinstance(result_json, str):
                    result_data = json.loads(result_json)
                else:
                    result_data = result_json

                result_urls = result_data.get("resultUrls", [])
                if result_urls:
                    return result_urls[0]

            await asyncio.sleep(poll_interval)

        print(f"      \u274c Veo polling timed out after {max_attempts} attempts")
        return None
