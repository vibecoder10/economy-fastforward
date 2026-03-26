"""ElevenLabs voice synthesis client — calls ElevenLabs API directly."""

import os
import httpx
import tempfile
from typing import Optional

from orchestrator.pipeline_constants import Models


class ElevenLabsClient:
    """Client for voice synthesis via ElevenLabs API (direct, no proxy)."""

    # Default voice ID
    DEFAULT_VOICE_ID = Models.VOICE_ID

    # ElevenLabs direct API
    ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
    ):
        # Accept either ELEVENLABS_API_KEY or WAVESPEED_API_KEY for backwards compat
        self.api_key = (
            api_key
            or os.getenv("ELEVENLABS_API_KEY")
            or os.getenv("WAVESPEED_API_KEY")
        )
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY not found in environment")

        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", self.DEFAULT_VOICE_ID)

    async def generate_voice(
        self,
        text: str,
        voice_id: Optional[str] = None,
        similarity_boost: float = 0.75,
        stability: float = 0.5,
    ) -> dict:
        """Generate voice audio from text via ElevenLabs API.

        Returns audio bytes directly (no polling needed).

        Returns:
            Dict with "audio_content" (bytes) on success, or "error" key on failure.
        """
        target_voice = voice_id or self.voice_id
        url = f"{self.ELEVENLABS_API_URL}/{target_voice}"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "use_speaker_boost": True,
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()

            # ElevenLabs returns raw audio bytes
            return {"audio_content": response.content, "content_type": response.headers.get("content-type", "audio/mpeg")}

    async def generate_and_wait(
        self,
        text: str,
        voice_id: Optional[str] = None,
    ) -> Optional[str]:
        """Generate voice audio and return a temporary file URL.

        The ElevenLabs direct API returns audio immediately (no polling).
        We save to a temp file and return the path as a file:// URL so the
        voice bot's download_audio() can read it back.

        Returns:
            File path to the generated audio, or None if failed.
        """
        try:
            result = await self.generate_voice(text, voice_id)
            audio_content = result.get("audio_content")
            if not audio_content:
                return None

            # Save to temp file — the caller (voice bot) will download and upload to Drive
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(audio_content)
            tmp.close()
            return tmp.name
        except Exception as e:
            print(f"  ❌ ElevenLabs voice generation failed: {e}", flush=True)
            return None

    async def download_audio(self, audio_path: str) -> bytes:
        """Read audio from a file path or download from URL.

        Args:
            audio_path: Local file path (from generate_and_wait) or HTTP URL

        Returns:
            Audio content as bytes
        """
        # If it's a local file (from generate_and_wait), read it directly
        if audio_path.startswith("/") or audio_path.startswith("file://"):
            path = audio_path.replace("file://", "")
            with open(path, "rb") as f:
                content = f.read()
            # Clean up temp file
            try:
                os.unlink(path)
            except OSError:
                pass
            return content

        # Otherwise it's a URL — download it
        async with httpx.AsyncClient() as client:
            response = await client.get(audio_path, timeout=60.0)
            response.raise_for_status()
            return response.content
