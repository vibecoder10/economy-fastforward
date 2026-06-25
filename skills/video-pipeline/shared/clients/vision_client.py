"""Provider-chained vision calls through Kie.ai.

Why this exists: Kie's Claude gateway has twice drifted into silently
dropping image blocks — HTTP 200, plausible text, but the model never saw
the pixels (2026-06-12: images arrived as /mnt-style file references;
~272 input tokens instead of ~900+). Every vision feature built directly
on that gateway degrades invisibly when it drifts.

This helper routes vision through Kie's Gemini chat endpoints first,
because their usage reporting makes image ingestion PROVABLE per call
(prompt_tokens jumps by ~1000+ when the image is actually included —
verified live 2026-06-12), then falls back to Kie's Claude gateway, then
to direct Anthropic when a key is available.

All images are downloaded by US and sent inline (data URLs / base64) —
provider-side URL fetching is a second silent-failure class (Drive
interstitials, expiring links).

Monitored by canaries/vision_drift.py (storyengine backend) — if a
provider drifts again, the canary alerts within the hour.
"""

import base64
import logging
import os
from typing import Optional, Union

import httpx

logger = logging.getLogger(__name__)

KIE_CHAT_API_BASE = os.getenv("KIE_CHAT_API_BASE", "https://api.kie.ai")
KIE_CLAUDE_API_URL = os.getenv("KIE_CLAUDE_API_URL", "https://api.kie.ai/claude/v1/messages")
ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")

# Kie's Gemini endpoints embed the model in the path:
#   https://api.kie.ai/gemini-2.5-flash/v1/chat/completions
TIER_MODELS = {
    "fast": {"gemini": "gemini-2.5-flash", "kie_claude": "claude-haiku-4-5",
             "anthropic": "claude-haiku-4-5-20251001"},
    "smart": {"gemini": "gemini-2.5-pro", "kie_claude": "claude-sonnet-4-5",
              "anthropic": "claude-sonnet-4-6"},
}

_MAGIC_TYPES = (
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
    (b"GIF8", "image/gif"),
)


class VisionUnavailable(RuntimeError):
    """Every provider in the chain failed to see the image."""


# A reply that says "I can't see the image" is the gateway's silent-drop
# failure surfacing as prose (HTTP 200, plausible text). Token-count guards
# only cover Gemini; this catches the symptom directly for EVERY provider so a
# refusal is never returned as a successful description. High-precision markers
# — a real character/scene description never contains these phrases.
_REFUSAL_MARKERS = (
    "unable to access", "unable to view", "unable to see",
    "can't access", "cannot access", "can't view", "cannot view",
    "i can't see", "i cannot see", "i'm unable to", "i am unable to",
    "i'm not able to", "i am not able to", "i don't have access",
    "i do not have access", "no file-reading", "tools aren't registered",
    "tools are not registered", "i appreciate you sharing the file",
    "i appreciate you uploading", "would need to view", "would need to see",
    "please provide the image", "please share the image", "no image was",
    "didn't receive an image", "did not receive an image",
)


def _looks_like_refusal(text: str) -> bool:
    """True if the reply reads like the model never saw the image."""
    t = (text or "").lower()
    return any(m in t for m in _REFUSAL_MARKERS)


def _sniff_media_type(data: bytes, fallback: str = "image/png") -> str:
    for magic, mtype in _MAGIC_TYPES:
        if data.startswith(magic):
            return mtype
    return fallback


async def _load_images(images: list, timeout: float) -> list[tuple[bytes, str]]:
    """Resolve each image (URL str or raw bytes) to (bytes, media_type).

    Downloading ourselves removes the provider-can't-fetch failure class.
    An HTML body where an image should be is a Drive interstitial — fail
    loudly instead of sending garbage pixels to a paid model.
    """
    loaded = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for img in images:
            if isinstance(img, (bytes, bytearray)):
                data = bytes(img)
            else:
                resp = await client.get(img)
                resp.raise_for_status()
                data = resp.content
            head = data[:256].lstrip().lower()
            if head.startswith(b"<!doctype") or head.startswith(b"<html"):
                raise VisionUnavailable(f"image URL served HTML, not pixels: {str(img)[:120]}")
            loaded.append((data, _sniff_media_type(data)))
    return loaded


async def _try_gemini(client: httpx.AsyncClient, key: str, model: str, prompt: str,
                      loaded: list[tuple[bytes, str]], max_tokens: int) -> str:
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {
            "url": f"data:{mtype};base64,{base64.b64encode(data).decode()}"}}
        for data, mtype in loaded
    ]
    r = await client.post(
        f"{KIE_CHAT_API_BASE}/{model}/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "stream": False, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": content}]},
    )
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    if not text:
        raise RuntimeError(f"empty reply: {str(data)[:200]}")
    # Ingestion proof: with the image included, prompt_tokens must exceed the
    # text alone by a wide margin (any real image is 250+ tokens; ours are
    # 768px+ ≈ 1000+). A text-only count means the gateway dropped the image.
    prompt_tokens = (data.get("usage") or {}).get("prompt_tokens") or 0
    text_estimate = len(prompt) // 4 + 50
    if prompt_tokens < text_estimate + 150 * len(loaded):
        raise RuntimeError(
            f"image not ingested: prompt_tokens={prompt_tokens} "
            f"≈ text-only estimate {text_estimate} for {len(loaded)} image(s)")
    return text


def _claude_blocks(prompt: str, loaded: list[tuple[bytes, str]]) -> list[dict]:
    return [
        {"type": "image", "source": {"type": "base64", "media_type": mtype,
                                     "data": base64.b64encode(data).decode()}}
        for data, mtype in loaded
    ] + [{"type": "text", "text": prompt}]


def _join_text_blocks(data: dict) -> str:
    # Join ALL text blocks — content[0] alone truncates multi-block replies
    return "\n".join(
        b.get("text", "") for b in (data.get("content") or []) if b.get("type") == "text"
    ).strip()


async def _try_kie_claude(client: httpx.AsyncClient, key: str, model: str, prompt: str,
                          loaded: list[tuple[bytes, str]], max_tokens: int) -> str:
    r = await client.post(
        KIE_CLAUDE_API_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "stream": False, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": _claude_blocks(prompt, loaded)}]},
    )
    r.raise_for_status()
    import json as _json
    data = _json.loads(r.text)  # Kie omits Content-Type on success
    if "content" not in data:  # HTTP 200 with {"code", "msg"} on auth/quota errors
        raise RuntimeError(f"gateway error: {str(data.get('msg') or data)[:200]}")
    text = _join_text_blocks(data)
    if not text:
        raise RuntimeError("empty reply")
    # No token-based ingestion check here: the gateway re-encodes base64
    # images to unpredictable sizes (a 768px PNG counted only ~200 tokens
    # while working). The hourly canary owns Claude-vision health instead.
    return text


async def _try_anthropic(client: httpx.AsyncClient, key: str, model: str, prompt: str,
                         loaded: list[tuple[bytes, str]], max_tokens: int) -> str:
    r = await client.post(
        ANTHROPIC_API_URL,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": _claude_blocks(prompt, loaded)}]},
    )
    r.raise_for_status()
    text = _join_text_blocks(r.json())
    if not text:
        raise RuntimeError("empty reply")
    return text


async def vision_call(
    prompt: str,
    images: list[Union[str, bytes]],
    *,
    kie_key: Optional[str] = None,
    anthropic_key: Optional[str] = None,
    tier: str = "fast",
    max_tokens: int = 500,
    timeout: float = 180.0,
) -> str:
    """Ask a vision model about one or more images; return its text reply.

    images: URLs (downloaded here) and/or raw bytes, in display order.
    Provider chain: direct Anthropic → Kie Gemini → Kie Claude (key-gated).
    Anthropic goes FIRST when its key is present — the Kie gateway 500s/hangs and
    silently drops image blocks, so analysis ("seeing") runs on the reliable path;
    Kie stays as the fallback. (Image/video GENERATION still uses Kie elsewhere.)

    Raises VisionUnavailable when no provider produced a usable reply.
    """
    if not images:
        raise ValueError("vision_call requires at least one image")
    models = TIER_MODELS[tier]
    loaded = await _load_images(images, timeout)

    attempts = []
    if anthropic_key:
        attempts.append(("anthropic", _try_anthropic, anthropic_key, models["anthropic"]))
    if kie_key:
        attempts.append(("kie-gemini", _try_gemini, kie_key, models["gemini"]))
        attempts.append(("kie-claude", _try_kie_claude, kie_key, models["kie_claude"]))
    if not attempts:
        raise VisionUnavailable("no API key for any vision provider")

    errors = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for name, fn, key, model in attempts:
            try:
                text = await fn(client, key, model, prompt, loaded, max_tokens)
                if _looks_like_refusal(text):
                    # The gateway dropped the image; the model is saying so in
                    # prose. Treat as a failure and fall through to the next
                    # provider rather than returning a non-answer as the result.
                    raise RuntimeError(f"refused / image not seen: {text[:120]}")
                return text
            except Exception as e:
                errors.append(f"{name}/{model}: {str(e)[:200]}")
                logger.warning("vision provider %s failed, trying next: %s", name, str(e)[:200])
    raise VisionUnavailable("all vision providers failed — " + " | ".join(errors))
