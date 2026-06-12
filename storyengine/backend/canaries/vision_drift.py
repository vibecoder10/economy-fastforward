"""Synthetic canary — detects when a Kie.ai vision path silently goes blind.

Background: on 2026-06-12 Kie's Claude gateway started turning image
blocks (URL and base64, both tiers) into /mnt-style FILE references the
model cannot see — HTTP 200, plausible prose, no pixels. Three features
degraded invisibly: modeled-video thumbnail style DNA, the storyboard
style-QA loop, and the approve-cast description rewrite. The drift
reverted within the day, which is exactly why only a canary can catch it.

This canary sends a KNOWN image (red circle on blue background, hosted on
Supabase Storage) through every vision path the product uses and asserts
the model actually SAW it:
  1. Kie Gemini 2.5 Flash (primary path in shared.clients.vision_client)
     — content check + prompt_tokens ingestion proof (image ≈ 1000+ tokens)
  2. Kie Claude haiku, URL source — content check + input_tokens >= 600
     (a 768px image is ~786 tokens; the broken state reported ~272)
  3. Kie Claude haiku, base64 — content check only (the gateway re-encodes
     base64 images so the token count is uninformative)

Cost: ~$0.002 per run (3 small vision calls). Hourly ≈ $1.5/month —
cheap insurance for the north-star modeling feature.

Exit codes (validator_drift.py convention):
  0 — all vision paths see the image
  1 — one or more paths are blind or drifted (see stderr)
  2 — infrastructure error (canary image unreachable, no key, network)

Run: `python3 -m canaries.vision_drift` from backend/ (needs ../.env for
the vault DB and the tenant Kie key).
"""
import asyncio
import base64
import json
import os
import sys

import httpx

CANARY_TENANT = os.getenv("VISION_CANARY_TENANT", "ee93e6d1-a9cc-44c3-81e9-84adee8329aa")
CANARY_IMAGE_URL = os.getenv(
    "VISION_CANARY_IMAGE_URL",
    "https://wrromlupsmyzrrcqlucn.supabase.co/storage/v1/object/public/assets/"
    "ee93e6d1-a9cc-44c3-81e9-84adee8329aa/canary/vision_canary.png",
)
KIE_CHAT_API_BASE = os.getenv("KIE_CHAT_API_BASE", "https://api.kie.ai")
KIE_CLAUDE_API_URL = os.getenv("KIE_CLAUDE_API_URL", "https://api.kie.ai/claude/v1/messages")

PROMPT = ("Describe this image in one sentence: name the dominant background "
          "color and the shape in the center.")


def _content_errors(text: str) -> list[str]:
    """The image is a red circle on a blue background. A model that saw it
    cannot miss those three words; a blind model writes a refusal/preamble."""
    low = (text or "").lower()
    errs = []
    if "red" not in low:
        errs.append("reply never says 'red'")
    if "blue" not in low:
        errs.append("reply never says 'blue'")
    if "circle" not in low and "round" not in low:
        errs.append("reply never names the circle")
    return errs


async def check_gemini(client: httpx.AsyncClient, key: str, png: bytes) -> list[str]:
    data_url = f"data:image/png;base64,{base64.b64encode(png).decode()}"
    r = await client.post(
        f"{KIE_CHAT_API_BASE}/gemini-2.5-flash/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gemini-2.5-flash", "stream": False, "max_tokens": 200,
              "messages": [{"role": "user", "content": [
                  {"type": "text", "text": PROMPT},
                  {"type": "image_url", "image_url": {"url": data_url}}]}]},
    )
    body = json.loads(r.text)
    errs = []
    if r.status_code != 200:
        return [f"HTTP {r.status_code}: {r.text[:200]}"]
    choices = body.get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
    errs += _content_errors(text)
    prompt_tokens = (body.get("usage") or {}).get("prompt_tokens") or 0
    if prompt_tokens < 800:  # known-good: 1109 for this exact image+prompt
        errs.append(f"prompt_tokens={prompt_tokens} — image not ingested (expected ~1109)")
    if errs:
        errs.append(f"reply was: {text[:160]!r}")
    return errs


async def _check_claude(client: httpx.AsyncClient, key: str, image_block: dict,
                        min_input_tokens: int | None) -> list[str]:
    r = await client.post(
        KIE_CLAUDE_API_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "claude-haiku-4-5", "stream": False, "max_tokens": 200,
              "messages": [{"role": "user", "content": [
                  image_block, {"type": "text", "text": PROMPT}]}]},
    )
    body = json.loads(r.text)  # Kie omits Content-Type on success
    if r.status_code != 200 or "content" not in body:
        return [f"HTTP {r.status_code}: {str(body.get('msg') or body)[:200]}"]
    text = "\n".join(b.get("text", "") for b in body["content"] if b.get("type") == "text")
    errs = _content_errors(text)
    input_tokens = (body.get("usage") or {}).get("input_tokens") or 0
    if min_input_tokens and input_tokens < min_input_tokens:
        errs.append(f"input_tokens={input_tokens} — image not ingested "
                    f"(expected >= {min_input_tokens}; broken state was ~272)")
    if errs:
        errs.append(f"reply was: {text[:160]!r}")
    return errs


async def main() -> int:
    # Vault needs the backend's env (DATABASE_URL); same loading as prod.
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    try:
        from vault import get_secret
        key = await get_secret("kie_ai_api_key", CANARY_TENANT)
    except Exception as e:
        print(f"INFRA: vault unreachable: {e}", file=sys.stderr)
        return 2
    if not key:
        print("INFRA: no kie_ai_api_key in vault for canary tenant", file=sys.stderr)
        return 2

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        try:
            resp = await client.get(CANARY_IMAGE_URL)
            png = resp.content
            if resp.status_code != 200 or not png.startswith(b"\x89PNG"):
                print(f"INFRA: canary image is not a PNG (HTTP {resp.status_code}) — "
                      f"re-upload it, the providers are not at fault", file=sys.stderr)
                return 2
        except httpx.TransportError as e:
            print(f"INFRA: cannot fetch canary image: {e}", file=sys.stderr)
            return 2

        b64_block = {"type": "image", "source": {
            "type": "base64", "media_type": "image/png",
            "data": base64.b64encode(png).decode()}}
        url_block = {"type": "image", "source": {"type": "url", "url": CANARY_IMAGE_URL}}

        checks = {
            "kie-gemini-2.5-flash": check_gemini(client, key, png),
            "kie-claude-haiku/url": _check_claude(client, key, url_block, min_input_tokens=600),
            "kie-claude-haiku/base64": _check_claude(client, key, b64_block, min_input_tokens=None),
        }
        drifted = False
        for name, coro in checks.items():
            try:
                errs = await coro
            except httpx.TransportError as e:
                print(f"INFRA {name}: transport error: {e}", file=sys.stderr)
                return 2
            except Exception as e:
                errs = [f"unexpected: {e}"]
            if errs:
                drifted = True
                print(f"DRIFT {name}:", file=sys.stderr)
                for e in errs:
                    print(f"  - {e}", file=sys.stderr)
            else:
                print(f"ok {name}")

    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
