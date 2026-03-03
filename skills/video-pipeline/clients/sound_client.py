"""Sound effect generation client using Kie.ai API (ElevenLabs Sound Effect V2)."""

import os
import json
import httpx
from typing import Optional
import asyncio


class SoundClient:
    """Client for sound effect generation via ElevenLabs Sound Effect V2 on Kie.ai."""

    CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
    RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

    MODEL = "elevenlabs/sound-effect-v2"
    DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
    MAX_PROMPT_LENGTH = 450

    # Cost estimate per generation (approximate)
    ESTIMATED_COST_PER_GENERATION = 0.05

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("KIE_AI_API_KEY")
        if not self.api_key:
            raise ValueError("KIE_AI_API_KEY not found in environment")
        self.generation_count = 0
        self.estimated_total_cost = 0.0

    async def generate_sound_effect(
        self,
        text: str,
        duration_seconds: Optional[float] = None,
        loop: bool = False,
        prompt_influence: float = 0.3,
    ) -> Optional[str]:
        """Generate a sound effect and wait for completion.

        Args:
            text: Sound description prompt (max 450 chars)
            duration_seconds: Duration 0.5-22s, omit to let AI decide
            loop: Whether the sound should loop seamlessly
            prompt_influence: How closely to follow the prompt (0-1)

        Returns:
            URL of the generated MP3, or None if failed
        """
        # Validate and truncate prompt
        if len(text) > self.MAX_PROMPT_LENGTH:
            print(f"    Warning: Prompt truncated from {len(text)} to {self.MAX_PROMPT_LENGTH} chars")
            text = text[:self.MAX_PROMPT_LENGTH]

        # Validate duration
        if duration_seconds is not None:
            duration_seconds = max(0.5, min(22.0, duration_seconds))

        prompt_preview = text[:80] + "..." if len(text) > 80 else text
        print(f"    Generating SFX: {prompt_preview}")
        if duration_seconds:
            print(f"    Duration: {duration_seconds}s | Loop: {loop}")

        # Build request payload
        input_data = {
            "text": text,
            "loop": loop,
            "prompt_influence": prompt_influence,
            "output_format": self.DEFAULT_OUTPUT_FORMAT,
        }
        if duration_seconds is not None:
            input_data["duration_seconds"] = duration_seconds

        payload = {
            "model": self.MODEL,
            "input": input_data,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Retry with exponential backoff on server errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.CREATE_TASK_URL,
                        headers=headers,
                        json=payload,
                        timeout=60.0,
                    )

                    if response.status_code in (500, 502, 503, 504):
                        wait = 2 ** (attempt + 1)
                        print(f"    Server error {response.status_code}, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait)
                        continue

                    if response.status_code != 200:
                        print(f"    SFX API error: HTTP {response.status_code}")
                        print(f"    Response: {response.text[:500]}")
                        return None

                    task_data = response.json()
                    task_id = task_data.get("data", {}).get("taskId")

                    if not task_id:
                        api_msg = task_data.get("msg") or task_data.get("message") or "unknown"
                        print(f"    No task ID in response: {api_msg}")
                        return None

                    print(f"    SFX task created: {task_id}")

                    # Poll for completion
                    await asyncio.sleep(3)
                    result_url = await self._poll_for_completion(task_id)

                    if result_url:
                        self.generation_count += 1
                        self.estimated_total_cost += self.ESTIMATED_COST_PER_GENERATION
                        print(f"    SFX complete (total: {self.generation_count}, ~${self.estimated_total_cost:.2f})")
                        return result_url

                    print(f"    SFX generation failed for task {task_id}")
                    return None

            except httpx.TimeoutException:
                wait = 2 ** (attempt + 1)
                print(f"    Timeout, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait)
            except Exception as e:
                print(f"    SFX error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                else:
                    return None

        print("    All SFX retry attempts failed")
        return None

    async def _poll_for_completion(
        self,
        task_id: str,
        max_attempts: int = 40,
        poll_interval: float = 3.0,
    ) -> Optional[str]:
        """Poll for sound effect generation completion.

        Args:
            task_id: Task ID to poll
            max_attempts: Maximum polling attempts (40 * 3s = 120s timeout)
            poll_interval: Seconds between polls

        Returns:
            URL of the generated audio, or None if failed/timeout
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        self.RECORD_INFO_URL,
                        headers=headers,
                        params={"taskId": task_id},
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    data = response.json().get("data", {})

                task_state = data.get("state", "")
                task_status = data.get("status")

                # Check for failure
                if (str(task_state).lower() in ("fail", "failed", "failure", "error") or
                        task_status == 3 or
                        str(task_status).lower() in ("failed", "failure", "error")):
                    error_msg = data.get("errorMessage") or data.get("error") or "Unknown"
                    print(f"    SFX task failed: {error_msg}")
                    return None

                # Check for success — parse resultJson
                result_json = data.get("resultJson")
                if result_json:
                    if isinstance(result_json, str):
                        result_data = json.loads(result_json)
                    else:
                        result_data = result_json

                    result_urls = result_data.get("resultUrls", [])
                    if result_urls:
                        return result_urls[0]

                # Also check for direct state=success with result in response
                if str(task_state).lower() == "success" and not result_json:
                    print(f"    SFX success but no resultJson, checking data...")

                if attempt % 10 == 0 and attempt > 0:
                    print(f"    Still waiting for SFX... (attempt {attempt + 1}/{max_attempts})")

            except Exception as e:
                print(f"    Poll error: {e}")

            await asyncio.sleep(poll_interval)

        print(f"    SFX poll timeout after {max_attempts} attempts")
        return None

    async def download_audio(self, audio_url: str) -> bytes:
        """Download audio file from URL.

        Args:
            audio_url: URL of the audio file

        Returns:
            Audio content as bytes
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(audio_url, timeout=60.0)
            response.raise_for_status()
            return response.content
