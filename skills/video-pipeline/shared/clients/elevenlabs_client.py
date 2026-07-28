"""ElevenLabs voice synthesis client — calls ElevenLabs API directly."""

import asyncio
import os
import httpx
import tempfile
import inspect
from typing import Optional

from orchestrator.pipeline_constants import Models


def _is_transient_kie_tts_failure(fail_info: Optional[dict]) -> bool:
    """True for Kie's own TRANSIENT infra-failure signature on the TTS
    gateway — failCode "500" with "internal error" in failMsg and ~0 credits
    consumed (None counts as 0). Same signature already proven safe to retry
    on the image side: storyengine/backend/scripts/coverage_to_app.py's
    _sheet_transient_kie_error (live example there: failCode "500", failMsg
    "Internal Error, Please try again later.", creditsConsumed 0.0). Voice
    hit the identical signature live (video 686b4651, 2026-07-23, all 6
    scenes: "Kie TTS task failed: internal error" between 23:20:39 and
    23:31:47) with no retry at all.

    This is Kie's own server falling over, NOT a content/auth problem — so
    it's the ONLY case safe to retry for free. A real (credit-consuming)
    failure, or any other failCode, must never be retried here: that would
    just resend the same doomed request, or worse, risk billing twice for
    something that actually charged. The ~0-credit guard is mandatory and
    must never be loosened, exactly as on the image side."""
    if not fail_info:
        return False
    if str(fail_info.get("failCode") or "").strip() != "500":
        return False
    if fail_info.get("creditsConsumed") not in (0, 0.0, None):
        return False
    return "internal error" in str(fail_info.get("failMsg") or "").lower()


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

    # Transient-infra retry (voicefix): same 3-attempts/5s-pause shape already
    # proven on the dialogue-voice path (storyengine/backend/dialogue_voice.py
    # SEGMENT_ATTEMPTS/RETRY_DELAY_SECONDS) — reused here rather than
    # inventing a new retry design, but scoped to fire ONLY on Kie's specific
    # zero-cost transient signature (see _is_transient_kie_tts_failure),
    # never on a real content/auth error.
    KIE_TRANSIENT_RETRY_ATTEMPTS = 3
    KIE_TRANSIENT_RETRY_DELAY_SECONDS = 5

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

    async def query_task(self, task_id: str, fail_info_out: Optional[list] = None) -> dict:
        """Query and finish one already-created Kie TTS task.

        Direct ElevenLabs responses have no task identity and never enter this
        path.  Custom Film uses it only after the Kie task ID has been durably
        journaled, so worker recovery never creates a second paid task.

        fail_info_out: optional list the caller passes in to receive Kie's
        raw failure detail (failCode/failMsg/creditsConsumed) on a failed
        task — same convention as image_client.py's fail_info_out, used by
        _generate_via_kie to decide whether a failure is safe to retry.
        """
        if not self._kie_mode:
            raise RuntimeError("Direct ElevenLabs voice has no queryable task")
        import asyncio as _asyncio
        import json as _json

        task_id = str(task_id or "").strip()
        if not task_id:
            raise RuntimeError("Kie TTS task identity is missing")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for _attempt in range(60):
            await _asyncio.sleep(3)
            async with httpx.AsyncClient() as client:
                poll = await client.get(
                    self.KIE_RECORD_INFO_URL,
                    headers=headers,
                    params={"taskId": task_id},
                    timeout=30.0,
                )
            pdata = poll.json().get("data", {}) if poll.text else {}
            state = str(pdata.get("state", "")).lower()
            if state in ("fail", "failed", "failure", "error"):
                fail_msg = str(pdata.get("failMsg") or pdata.get("errorMessage") or "")
                message = (fail_msg or str(pdata))[:200]
                if fail_info_out is not None:
                    fail_info_out.append({
                        "failCode": str(pdata.get("failCode") or "").strip(),
                        "failMsg": fail_msg,
                        "creditsConsumed": pdata.get("creditsConsumed"),
                    })
                raise RuntimeError(f"Kie TTS task failed: {message}")
            result_json = pdata.get("resultJson")
            if result_json:
                result = (
                    _json.loads(result_json)
                    if isinstance(result_json, str)
                    else result_json
                )
                urls = result.get("resultUrls") or []
                if urls:
                    async with httpx.AsyncClient() as client:
                        audio = await client.get(urls[0], timeout=120.0)
                        audio.raise_for_status()
                    return {
                        "audio_content": audio.content,
                        "content_type": "audio/mpeg",
                    }
        raise RuntimeError(f"Kie.ai TTS timed out for task {task_id}")

    async def _generate_via_kie(
        self,
        text: str,
        voice: str,
        stability: float,
        similarity_boost: float,
        style: Optional[float] = None,
        speed: Optional[float] = None,
        task_id_callback=None,
        fail_info_out: Optional[list] = None,
    ) -> dict:
        """Generate TTS through Kie.ai's async job API; returns audio bytes.

        fail_info_out: optional list the caller passes in to receive Kie's
        raw failure detail (failCode/failMsg/creditsConsumed) if generation
        ultimately fails — same fail_info_out convention as image_client.py.

        Transient-infra retry (voicefix root cause #2): Kie's own server
        occasionally 500s with a zero-cost "internal error" on an otherwise
        healthy request (confirmed live, see _is_transient_kie_tts_failure's
        docstring). That specific signature gets up to
        KIE_TRANSIENT_RETRY_ATTEMPTS attempts, KIE_TRANSIENT_RETRY_DELAY_SECONDS
        apart — the exact shape already proven on the dialogue-voice path.
        Each retry creates a BRAND NEW Kie task (a fresh createTask call);
        that's safe, never a double-charge, because the failed task consumed
        0 credits. Anything else (a real content/auth error, or the same
        transient signature after every attempt is exhausted) raises
        immediately — no blind retry-on-any-exception here.
        """
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
            for attempt in range(1, self.KIE_TRANSIENT_RETRY_ATTEMPTS + 1):
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
                        break  # try the next candidate voice; no point retrying the same rejection
                    raise RuntimeError(f"Kie TTS createTask failed: {last_error}")
                if task_id_callback is not None:
                    callback_result = task_id_callback(str(task_id))
                    if inspect.isawaitable(callback_result):
                        await callback_result
                attempt_fail: list = []
                try:
                    return await self.query_task(str(task_id), fail_info_out=attempt_fail)
                except Exception as e:
                    last_error = str(e)[:200]
                    info = attempt_fail[-1] if attempt_fail else None
                    if _is_transient_kie_tts_failure(info) and attempt < self.KIE_TRANSIENT_RETRY_ATTEMPTS:
                        print(
                            f"    Kie TTS transient infra failure (attempt {attempt}/"
                            f"{self.KIE_TRANSIENT_RETRY_ATTEMPTS}): {last_error} — "
                            f"retrying in {self.KIE_TRANSIENT_RETRY_DELAY_SECONDS}s",
                            flush=True,
                        )
                        await asyncio.sleep(self.KIE_TRANSIENT_RETRY_DELAY_SECONDS)
                        continue
                    # Not transient, or retries exhausted — never a blind retry.
                    # Only report the failure once it's FINAL (a caller
                    # should never see a "failure" for an attempt a retry
                    # went on to recover from).
                    if fail_info_out is not None and info is not None:
                        fail_info_out.append(info)
                    raise
        raise RuntimeError(f"Kie TTS failed: {last_error}")

    async def generate_voice(
        self,
        text: str,
        voice_id: Optional[str] = None,
        similarity_boost: float = 0.75,
        stability: float = 0.5,
        style: Optional[float] = None,
        speed: Optional[float] = None,
        task_id_callback=None,
        fail_info_out: Optional[list] = None,
    ) -> dict:
        """Generate voice audio from text via ElevenLabs API.

        Returns audio bytes directly (no polling needed). style/speed are
        optional character-performance knobs (used for dialogue lines); when
        omitted the request is byte-identical to the pre-dialogue behavior.

        fail_info_out: optional list the caller passes in to receive Kie's
        raw failure detail on the Kie-gateway path (ignored for direct
        ElevenLabs, which has no task/fail-code concept).

        Returns:
            Dict with "audio_content" (bytes) on success, or "error" key on failure.
        """
        target_voice = voice_id or self.voice_id
        # Tenant narrator style (vault -> env seam, see pipeline_executor).
        # Applies only when the caller passed no explicit style, so dialogue
        # lines that set their own performance knobs are untouched.
        if style is None:
            env_style = os.getenv("ELEVENLABS_VOICE_STYLE", "").strip()
            if env_style:
                try:
                    style = float(env_style)
                except ValueError:
                    pass
        if self._kie_mode:
            return await self._generate_via_kie(
                text,
                target_voice,
                stability,
                similarity_boost,
                style=style,
                speed=speed,
                task_id_callback=task_id_callback,
                fail_info_out=fail_info_out,
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
            # Tenant-pinned TTS model (vault -> env seam). Long-form documentary
            # channels pin eleven_multilingual_v2; default stays turbo so
            # existing tenants are byte-identical.
            "model_id": os.getenv("ELEVENLABS_MODEL_ID", "").strip() or "eleven_turbo_v2_5",
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
        task_id_callback=None,
        fail_info_out: Optional[list] = None,
    ) -> Optional[str]:
        """Generate voice audio and return a temporary file URL.

        The ElevenLabs direct API returns audio immediately (no polling).
        We save to a temp file and return the path as a file:// URL so the
        voice bot's download_audio() can read it back.

        fail_info_out: optional list the caller passes in (voicefix). On
        failure, one dict is appended with at least a "failMsg" key so the
        caller can report WHY the scene failed instead of a silent None —
        this is what closes root cause #1 (a swallowed failure that still
        let the run advance status). Existing callers that don't pass this
        keep the exact same None-on-failure contract.

        Returns:
            File path to the generated audio, or None if failed.
        """
        try:
            result = await self.generate_voice(
                text,
                voice_id,
                task_id_callback=task_id_callback,
                fail_info_out=fail_info_out,
            )
            audio_content = result.get("audio_content")
            if not audio_content:
                if fail_info_out is not None and not fail_info_out:
                    fail_info_out.append({"failMsg": "no audio content returned"})
                return None

            # Save to temp file — the caller (voice bot) will download and upload to Drive
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(audio_content)
            tmp.close()
            return tmp.name
        except Exception as e:
            print(f"  ❌ ElevenLabs voice generation failed: {e}", flush=True)
            if fail_info_out is not None and not fail_info_out:
                fail_info_out.append({"failMsg": str(e)})
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
