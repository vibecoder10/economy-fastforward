"""Kie.ai-backed generation clients for StoryEngine.

This module lets the app treat Kie.ai as the required generation key while
still supporting direct provider keys as optional overrides.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from types import SimpleNamespace
from typing import Any, Optional

import httpx

from error_utils import is_kie_block as _kie_block, KIE_BLOCK_MARKER as _KIE_BLOCK_MARKER


logger = logging.getLogger(__name__)

KIE_API_BASE_URL = os.getenv("KIE_API_BASE_URL", "https://api.kie.ai").rstrip("/")
KIE_CLAUDE_MODEL = os.getenv("KIE_CLAUDE_MODEL", "claude-sonnet-4-6")
KIE_CLAUDE_MAX_TOKENS = int(os.getenv("KIE_CLAUDE_MAX_TOKENS", "8192"))
KIE_CLAUDE_TIMEOUT_SECONDS = float(os.getenv("KIE_CLAUDE_TIMEOUT_SECONDS", "300"))
KIE_TTS_MODEL = os.getenv(
    "KIE_TTS_MODEL",
    "elevenlabs/text-to-speech-multilingual-v2",
)

CLAUDE_MODEL_ALIASES = {
    # Haiku 4.5 is supported natively by kie.ai — keep it as Haiku (≈3x cheaper
    # and ≈3.5x faster than Sonnet) instead of upgrading it to the default model.
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
    "claude-haiku-4-5": "claude-haiku-4-5",
    "claude-sonnet-4-20250514": KIE_CLAUDE_MODEL,
    "claude-3-7-sonnet-20250219": KIE_CLAUDE_MODEL,
    "claude-3-5-sonnet-20241022": KIE_CLAUDE_MODEL,
    "claude-3-5-sonnet-latest": KIE_CLAUDE_MODEL,
    "claude-sonnet-4-5-20250929": KIE_CLAUDE_MODEL,
    "claude-sonnet-4-5": KIE_CLAUDE_MODEL,
    "claude-sonnet-4-6": "claude-sonnet-4-6",
}


class MissingGenerationKeyError(RuntimeError):
    """Raised when neither Kie.ai nor a direct provider key is available."""


def _text_blocks(text: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(type="text", text=text)]


def _extract_text_value(value: Any, depth: int = 0) -> str:
    """Extract text from common Anthropic, OpenAI, and Kie wrapper shapes."""
    if depth > 6 or value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_extract_text_value(item, depth + 1) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "completion", "output_text", "result", "response"):
            text = _extract_text_value(value.get(key), depth + 1)
            if text:
                return text
        for key in ("message", "delta", "data", "output"):
            text = _extract_text_value(value.get(key), depth + 1)
            if text:
                return text
        choices = value.get("choices")
        if choices:
            text = _extract_text_value(choices, depth + 1)
            if text:
                return text
        return ""

    for attr in ("text", "content", "message", "completion", "output_text"):
        if hasattr(value, attr):
            text = _extract_text_value(getattr(value, attr, None), depth + 1)
            if text:
                return text
    return ""


def _extract_text(response: Any) -> str:
    """Extract assistant text from Anthropic-compatible response shapes."""
    return _extract_text_value(response).strip()


def _response_debug(response: Any) -> str:
    if not isinstance(response, dict):
        return type(response).__name__
    details = {"keys": list(response.keys())}
    for key in ("type", "role", "model", "stop_reason", "finish_reason", "code", "msg", "message"):
        if key in response:
            details[key] = response.get(key)
    data = response.get("data")
    if isinstance(data, dict):
        details["data_keys"] = list(data.keys())
        for key in ("type", "role", "model", "stop_reason", "finish_reason", "code", "msg", "message"):
            if key in data:
                details[f"data_{key}"] = data.get(key)
    return json.dumps(details, default=str)[:1000]


class _KieMessagesCompat:
    """Sync compatibility shim for code that calls client.messages.create."""

    def __init__(self, owner: "KieClaudeClient"):
        self._owner = owner

    def create(self, **kwargs: Any) -> SimpleNamespace:
        response = self._owner.create_message_sync(**kwargs)
        text = _extract_text(response)
        return SimpleNamespace(content=_text_blocks(text), raw=response)


class _KieClientCompat:
    def __init__(self, owner: "KieClaudeClient"):
        self.messages = _KieMessagesCompat(owner)


class KieClaudeClient:
    """Claude-compatible text client using Kie.ai's Claude market endpoint."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("KIE_AI_API_KEY") or os.getenv("KIE_API_KEY")
        if not self.api_key:
            raise ValueError("KIE_AI_API_KEY not found in environment")
        self.base_url = KIE_API_BASE_URL
        self.client = _KieClientCompat(self)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = KIE_CLAUDE_MODEL,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        base_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "system": system_prompt or None,
            "tools": tools,
        }
        attempts: list[dict[str, Any]] = [base_kwargs]
        if tools:
            attempts.append({**base_kwargs, "tools": None})
        attempts.append({
            **base_kwargs,
            "tools": None,
            "temperature": min(float(temperature or 0.7), 0.3),
        })

        last_debug = ""
        for index, kwargs in enumerate(attempts, start=1):
            try:
                response = await self.create_message_async(**kwargs)
            except httpx.HTTPError as exc:
                body = getattr(getattr(exc, "response", None), "text", "") or ""
                last_debug = f"{type(exc).__name__}: {exc} {body}"
                # A banned / out-of-credit Kie account is terminal — stop
                # retrying and surface an actionable, marked error.
                if _kie_block(last_debug):
                    raise RuntimeError(f"{_KIE_BLOCK_MARKER}: Kie.ai account blocked or out of credit")
                logger.warning("Kie.ai Claude request failed on attempt %d: %s", index, last_debug)
                await asyncio.sleep(0.9 * index)
                continue
            text = _extract_text(response)
            if text:
                if index > 1:
                    logger.info("Kie.ai Claude returned content after retry %d", index)
                return text
            last_debug = _response_debug(response)
            if _kie_block(last_debug):
                raise RuntimeError(f"{_KIE_BLOCK_MARKER}: Kie.ai account blocked or out of credit")
            logger.warning("Kie.ai Claude returned empty content on attempt %d: %s", index, last_debug)
            await asyncio.sleep(0.7 * index)

        raise RuntimeError(f"Kie.ai Claude returned empty content after retries: {last_debug}")

    async def create_message_async(self, **kwargs: Any) -> dict[str, Any]:
        payload = self._build_payload(kwargs)
        async with httpx.AsyncClient(timeout=KIE_CLAUDE_TIMEOUT_SECONDS) as client:
            return await self._post_messages_async(client, payload)

    def create_message_sync(self, **kwargs: Any) -> dict[str, Any]:
        payload = self._build_payload(kwargs)
        with httpx.Client(timeout=KIE_CLAUDE_TIMEOUT_SECONDS) as client:
            return self._post_messages_sync(client, payload)

    def _build_payload(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        model = kwargs.get("model") or KIE_CLAUDE_MODEL
        requested_max_tokens = int(kwargs.get("max_tokens", 4096) or 4096)
        payload: dict[str, Any] = {
            "model": CLAUDE_MODEL_ALIASES.get(model, model),
            "messages": kwargs.get("messages") or [],
            "stream": False,
            "max_tokens": min(requested_max_tokens, KIE_CLAUDE_MAX_TOKENS),
        }
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]
        if kwargs.get("system"):
            payload["system"] = kwargs["system"]
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        if os.getenv("KIE_CLAUDE_THINKING", "").lower() in {"1", "true", "yes"}:
            payload["thinkingFlag"] = True
        return payload

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_messages_async(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = await client.post(
                f"{self.base_url}/claude/v1/messages",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            if payload.get("tools"):
                retry_payload = dict(payload)
                retry_payload.pop("tools", None)
                response = await client.post(
                    f"{self.base_url}/claude/v1/messages",
                    headers=self._headers,
                    json=retry_payload,
                )
                response.raise_for_status()
                return response.json()
            raise

    def _post_messages_sync(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = client.post(
                f"{self.base_url}/claude/v1/messages",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            if payload.get("tools"):
                retry_payload = dict(payload)
                retry_payload.pop("tools", None)
                response = client.post(
                    f"{self.base_url}/claude/v1/messages",
                    headers=self._headers,
                    json=retry_payload,
                )
                response.raise_for_status()
                return response.json()
            raise


class AnthropicDirectClient:
    """Small async wrapper matching the pipeline AnthropicClient interface."""

    def __init__(self, api_key: str):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools

        response = await asyncio.to_thread(self.client.messages.create, **kwargs)
        text = _extract_text(response)
        if not text:
            raise RuntimeError("Anthropic returned empty content")
        return text


class KieElevenLabsTTSClient:
    """ElevenLabs-style TTS client backed by Kie.ai market jobs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_name: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("KIE_AI_API_KEY") or os.getenv("KIE_API_KEY")
        if not self.api_key:
            raise ValueError("KIE_AI_API_KEY not found in environment")
        self.base_url = KIE_API_BASE_URL
        self.model = model or KIE_TTS_MODEL
        self.voice_name = (
            voice_name
            or os.getenv("KIE_ELEVENLABS_VOICE")
            or os.getenv("ELEVENLABS_VOICE_NAME")
            or "Rachel"
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate_voice(
        self,
        text: str,
        voice_id: Optional[str] = None,
        similarity_boost: float = 0.75,
        stability: float = 0.5,
    ) -> dict[str, Any]:
        audio_url = await self.generate_and_wait(
            text,
            voice_id=voice_id,
            similarity_boost=similarity_boost,
            stability=stability,
        )
        if not audio_url:
            return {"error": "Kie.ai voice generation did not return an audio URL"}
        audio_content = await self.download_audio(audio_url)
        return {"audio_content": audio_content, "content_type": "audio/mpeg"}

    async def generate_and_wait(
        self,
        text: str,
        voice_id: Optional[str] = None,
        similarity_boost: float = 0.75,
        stability: float = 0.5,
    ) -> Optional[str]:
        task_id = await self._create_task(
            text=text,
            voice=voice_id or self.voice_name,
            similarity_boost=similarity_boost,
            stability=stability,
        )
        return await self._poll_for_result(task_id)

    async def download_audio(self, audio_path: str) -> bytes:
        if audio_path.startswith("/") or audio_path.startswith("file://"):
            path = audio_path.replace("file://", "")
            with open(path, "rb") as f:
                content = f.read()
            try:
                os.unlink(path)
            except OSError:
                pass
            return content

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(audio_path)
            response.raise_for_status()
            return response.content

    async def _create_task(
        self,
        text: str,
        voice: str,
        similarity_boost: float,
        stability: float,
    ) -> str:
        payload = {
            "model": self.model,
            "input": {
                "text": text,
                "voice": voice,
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": 0,
                "speed": 1,
                "timestamps": False,
                "previous_text": "",
                "next_text": "",
                "language_code": "",
            },
        }
        callback_url = os.getenv("KIE_CALLBACK_URL")
        if callback_url:
            payload["callBackUrl"] = callback_url

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/jobs/createTask",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        task_id = ((body.get("data") or {}).get("taskId") or body.get("taskId"))
        if not task_id:
            raise RuntimeError(f"Kie.ai TTS task missing taskId: {body}")
        return str(task_id)

    async def _poll_for_result(self, task_id: str) -> Optional[str]:
        deadline = asyncio.get_running_loop().time() + float(
            os.getenv("KIE_TTS_TIMEOUT_SECONDS", "900")
        )
        delay = 2.0
        async with httpx.AsyncClient(timeout=60.0) as client:
            while asyncio.get_running_loop().time() < deadline:
                response = await client.get(
                    f"{self.base_url}/api/v1/jobs/recordInfo",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    params={"taskId": task_id},
                )
                response.raise_for_status()
                body = response.json()
                data = body.get("data") or {}
                state = str(data.get("state") or data.get("status") or "").lower()

                if state == "success":
                    return self._extract_result_url(data)
                if state in {"fail", "failed", "error"}:
                    message = data.get("failMsg") or data.get("error") or body.get("msg")
                    raise RuntimeError(f"Kie.ai TTS failed: {message or state}")

                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 10.0)
        raise TimeoutError(f"Kie.ai TTS timed out for task {task_id}")

    def _extract_result_url(self, data: dict[str, Any]) -> Optional[str]:
        for key in ("resultJson", "response", "responseJson"):
            value = data.get(key)
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = value
                url = self._find_url(parsed)
                if url:
                    return url

        return self._find_url(data)

    def _find_url(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            if value.startswith("http://") or value.startswith("https://"):
                return value
            return None
        if isinstance(value, list):
            for item in value:
                url = self._find_url(item)
                if url:
                    return url
            return None
        if isinstance(value, dict):
            preferred = [
                "audioUrl",
                "audio_url",
                "url",
                "resultUrl",
                "result_url",
                "downloadUrl",
                "download_url",
            ]
            for key in preferred:
                url = self._find_url(value.get(key))
                if url:
                    return url
            for item in value.values():
                url = self._find_url(item)
                if url:
                    return url
        return None


async def get_text_client_for_tenant(tenant_id: str) -> Any:
    """Return a Claude-like client using direct Anthropic or Kie.ai."""
    from vault import get_secret

    anthropic_key = await get_secret("anthropic_api_key", tenant_id)
    if anthropic_key:
        return AnthropicDirectClient(anthropic_key)

    kie_key = await get_secret("kie_ai_api_key", tenant_id)
    if kie_key:
        return KieClaudeClient(kie_key)

    raise MissingGenerationKeyError(
        "Add your AI key to get started — the setup chat on the home page walks you "
        "through it in about 2 minutes (or add it in Settings → API Keys)."
    )


def write_temp_audio(audio_content: bytes, suffix: str = ".mp3") -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(audio_content)
    tmp.close()
    return tmp.name
