"""ElevenLabs voice synthesis client — calls ElevenLabs API directly."""

import os
import httpx
import tempfile
from typing import Optional

from orchestrator.pipeline_constants import Models


class ElevenLabsClient:
    """Client for voice synthesis.

    Two modes:
    - Direct ElevenLabs API (when ELEVENLABS_API_KEY is configured)
    - Kie.ai gateway (fallback when only KIE_AI_API_KEY exists — "voice uses kie
      as well"): async createTask/recordInfo jobs against the
      elevenlabs/text-to-speech-multilingual-v2 model. Kie only accepts voices
      from its own roster; unknown voice ids fall back to a narration voice.
    """

    # Default voice ID
    DEFAULT_VOICE_ID = Models.VOICE_ID

    # ElevenLabs direct API
    ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"

    # Kie.ai gateway (same job pattern as SoundClient / image generation)
    KIE_CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
    KIE_RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
    KIE_TTS_MODEL = "elevenlabs/text-to-speech-multilingual-v2"
    # "Mark" — natural narration voice from Kie's allowed roster, used when the
    # configured voice id isn't on Kie's list (verified live: off-roster ids are
    # rejected with "This voice is not within the range of allowed options").
    KIE_FALLBACK_VOICE = "1SM7GgM6IMuvQlz2BwM3"

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
    ):
        # Accept either ELEVENLABS_API_KEY or WAVESPEED_API_KEY for backwards compat
        direct_key = (
            api_key
            or os.getenv("ELEVENLABS_API_KEY")
            or os.getenv("WAVESPEED_API_KEY")
        )
        kie_key = os.getenv("KIE_AI_API_KEY")
        self._kie_mode = False
        if direct_key:
            self.api_key = direct_key
        elif kie_key:
            self.api_key = kie_key
            self._kie_mode = True
            print("    Voice routed via Kie.ai gateway (no direct ElevenLabs key)", flush=True)
        else:
            raise ValueError("ELEVENLABS_API_KEY not found in environment")

        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", self.DEFAULT_VOICE_ID)

    async def _generate_via_kie(
        self,
        text: str,
        voice: str,
        stability: float,
        similarity_boost: float,
        style: Optional[float] = None,
        speed: Optional[float] = None,
    ) -> dict:
        """Generate TTS through Kie.ai's async job API; returns audio bytes."""
        import asyncio as _asyncio
        import json as _json

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        tts_input = {
            "text": text[:5000],
            "stability": stability,
            "similarity_boost": similarity_boost,
        }
        # Character-dialogue knobs (verified live on the Kie gateway):
        # style adds acting, speed 1.05 reads younger. Never send
        # language_code on multilingual-v2 — the gateway rejects it.
        if style is not None:
            tts_input["style"] = style
        if speed is not None:
            tts_input["speed"] = speed
        last_error = "unknown"
        for candidate in dict.fromkeys([voice, self.KIE_FALLBACK_VOICE]):
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.KIE_CREATE_TASK_URL,
                    headers=headers,
                    json={
                        "model": self.KIE_TTS_MODEL,
                        "input": {**tts_input, "voice": candidate},
                    },
                    timeout=60.0,
                )
            data = resp.json() if resp.text else {}
            task_id = (data.get("data") or {}).get("taskId")
            if not task_id:
                last_error = str(data.get("msg") or data)[:200]
                if "not within the range" in last_error and candidate != self.KIE_FALLBACK_VOICE:
                    print(f"    Voice '{candidate}' not on Kie roster — falling back to narration voice", flush=True)
                    continue
                raise RuntimeError(f"Kie TTS createTask failed: {last_error}")

            for _attempt in range(60):
                await _asyncio.sleep(3)
                async with httpx.AsyncClient() as client:
                    poll = await client.get(
                        self.KIE_RECORD_INFO_URL,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        params={"taskId": task_id},
                        timeout=30.0,
                    )
                pdata = poll.json().get("data", {}) if poll.text else {}
                state = str(pdata.get("state", "")).lower()
                if state in ("fail", "failed", "failure", "error"):
                    last_error = str(pdata.get("failMsg") or pdata.get("errorMessage") or pdata)[:200]
                    raise RuntimeError(f"Kie TTS task failed: {last_error}")
                result_json = pdata.get("resultJson")
                if result_json:
                    result = _json.loads(result_json) if isinstance(result_json, str) else result_json
                    urls = result.get("resultUrls") or []
                    if urls:
                        async with httpx.AsyncClient() as client:
                            audio = await client.get(urls[0], timeout=120.0)
                            audio.raise_for_status()
                        return {"audio_content": audio.content, "content_type": "audio/mpeg"}
            raise RuntimeError("Kie TTS task timed out after 180s")
        raise RuntimeError(f"Kie TTS failed: {last_error}")

    async def generate_voice(
        self,
        text: str,
        voice_id: Optional[str] = None,
        similarity_boost: float = 0.75,
        stability: float = 0.5,
        style: Optional[float] = None,
        speed: Optional[float] = None,
    ) -> dict:
        """Generate voice audio from text via ElevenLabs API.

        Returns audio bytes directly (no polling needed). style/speed are
        optional character-performance knobs (used for dialogue lines); when
        omitted the request is byte-identical to the pre-dialogue behavior.

        Returns:
            Dict with "audio_content" (bytes) on success, or "error" key on failure.
        """
        target_voice = voice_id or self.voice_id
        if self._kie_mode:
            return await self._generate_via_kie(
                text, target_voice, stability, similarity_boost, style=style, speed=speed
            )
        url = f"{self.ELEVENLABS_API_URL}/{target_voice}"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        voice_settings = {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "use_speaker_boost": True,
        }
        if style is not None:
            voice_settings["style"] = style
        if speed is not None:
            voice_settings["speed"] = speed

        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": voice_settings,
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
