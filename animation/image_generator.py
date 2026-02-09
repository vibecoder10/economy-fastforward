"""Image generation for animation frames via Kie.ai (Seed Dream 4.0 / Nano Banana Pro)."""

import asyncio
import json
import httpx
from typing import Optional

from animation.config import (
    KIE_API_KEY,
    KIE_CREATE_TASK_URL,
    KIE_RECORD_INFO_URL,
    SCENE_IMAGE_MODEL,
)


class AnimationImageGenerator:
    """Generates start and end frame images for animation scenes."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or KIE_API_KEY
        if not self.api_key:
            raise ValueError("KIE_AI_API_KEY not found in environment")

    async def generate_frame(
        self,
        prompt: str,
        aspect_ratio: str = "landscape_16_9",
    ) -> Optional[str]:
        """Generate a single frame image via Seed Dream 4.0.

        Args:
            prompt: Full image generation prompt
            aspect_ratio: Image size parameter for Seed Dream

        Returns:
            URL of generated image, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": SCENE_IMAGE_MODEL,
            "input": {
                "prompt": prompt,
                "image_size": aspect_ratio,
                "image_resolution": "2K",
                "max_images": 1,
            },
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    KIE_CREATE_TASK_URL,
                    headers=headers,
                    json=payload,
                    timeout=60.0,
                )
                if response.status_code != 200:
                    print(f"      \u274c Image API error: {response.status_code} - {response.text}")
                    return None

                task_data = response.json()
                task_id = task_data.get("data", {}).get("taskId")

                if not task_id:
                    print(f"      \u274c No task ID returned: {task_data}")
                    return None

                # Wait before first poll
                await asyncio.sleep(5)

                result_urls = await self._poll_for_completion(task_id)
                if result_urls:
                    return result_urls[0]

                print(f"      \u274c Image generation failed (poll timeout)")
                return None

        except Exception as e:
            print(f"      \u274c Image generation error: {e}")
            return None

    async def generate_frame_pair(
        self,
        start_prompt: str,
        end_prompt: str,
    ) -> tuple[Optional[str], Optional[str]]:
        """Generate start and end frame images for a scene.

        Args:
            start_prompt: Prompt for the start frame
            end_prompt: Prompt for the end frame

        Returns:
            Tuple of (start_image_url, end_image_url). Either may be None on failure.
        """
        print(f"      \U0001f3a8 Generating start frame...")
        start_url = await self.generate_frame(start_prompt)

        if not start_url:
            print(f"      \u274c Start frame generation failed")
            return None, None

        print(f"      \u2705 Start frame ready")
        print(f"      \U0001f3a8 Generating end frame...")
        end_url = await self.generate_frame(end_prompt)

        if not end_url:
            print(f"      \u274c End frame generation failed")
            return start_url, None

        print(f"      \u2705 End frame ready")
        return start_url, end_url

    async def _poll_for_completion(
        self,
        task_id: str,
        max_attempts: int = 60,
        poll_interval: float = 2.0,
    ) -> Optional[list[str]]:
        """Poll Kie.ai for task completion.

        Args:
            task_id: Task ID to poll
            max_attempts: Maximum polling attempts
            poll_interval: Seconds between polls

        Returns:
            List of result URLs, or None if failed
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
                print(f"      \u26a0\ufe0f Task reported failure (State: {task_state}, Status: {task_status})")
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
                    return result_urls

            await asyncio.sleep(poll_interval)

        return None
