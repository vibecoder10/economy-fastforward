"""Synthetic canary — detects when an upstream provider silently changes
the shape of its 4xx error body.

Background: our `vault.test_api_key()` validators parse structured error
bodies into actionable customer-facing copy ("Anthropic rejected the key
— double-check it starts with `sk-ant-`"). If a provider changes their
error schema, our path walker silently returns None and the validator
falls through to the generic "API error 401" fallback — which is the
dead-end UX we spent Cycles 3, 16, and 19 eliminating.

This canary hits each upstream with a DELIBERATELY invalid key and
asserts the exact JSON paths our parsers depend on still resolve. No
billable usage: invalid keys short-circuit at auth before any paid work.

Exit codes:
  0 — all schemas intact
  1 — one or more provider schemas have drifted (see stderr)
  2 — transport error (unrelated to schema — probably network/DNS)

Run: `python3 -m canaries.validator_drift` from backend/
Cron (designed for VPS): every 6h (slower cadence deliberate — drift is
slow, over-probing wastes nothing here but is noise for alerts).
"""
import asyncio
import json
import sys

import httpx

CANARY_KEY = "sk-fake-canary-drift-probe-do-not-use"


async def _probe(client, method, url, **kwargs):
    resp = await (client.get(url, **kwargs) if method == "GET" else client.post(url, **kwargs))
    try:
        body = resp.json()
    except Exception:
        body = None
    return resp.status_code, body, resp.text[:300]


def _walk(node, path):
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    return node


async def check_anthropic(client):
    status, body, raw = await _probe(
        client, "POST",
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": CANARY_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": "claude-sonnet-4-5", "max_tokens": 1,
              "messages": [{"role": "user", "content": "hi"}]},
    )
    errs = []
    if status != 401:
        errs.append(f"expected 401, got {status}")
    if _walk(body, ("error", "type")) != "authentication_error":
        errs.append(f"error.type != 'authentication_error' (got {_walk(body, ('error', 'type'))!r})")
    if _walk(body, ("error", "message")) is None:
        errs.append("error.message missing")
    return errs, raw


async def check_openai(client):
    status, body, raw = await _probe(
        client, "GET",
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {CANARY_KEY}"},
    )
    errs = []
    if status != 401:
        errs.append(f"expected 401, got {status}")
    if _walk(body, ("error", "code")) != "invalid_api_key":
        errs.append(f"error.code != 'invalid_api_key' (got {_walk(body, ('error', 'code'))!r})")
    if _walk(body, ("error", "message")) is None:
        errs.append("error.message missing")
    return errs, raw


async def check_gemini(client):
    status, body, raw = await _probe(
        client, "GET",
        f"https://generativelanguage.googleapis.com/v1beta/models?key={CANARY_KEY}",
    )
    errs = []
    if status != 400:
        errs.append(f"expected 400, got {status}")
    details = _walk(body, ("error", "details")) or []
    reasons = [d.get("reason") for d in details if isinstance(d, dict)]
    if "API_KEY_INVALID" not in reasons:
        errs.append(f"error.details[].reason missing API_KEY_INVALID (got {reasons!r})")
    if _walk(body, ("error", "message")) is None:
        errs.append("error.message missing")
    return errs, raw


async def check_tavily(client):
    status, body, raw = await _probe(
        client, "POST",
        "https://api.tavily.com/search",
        json={"api_key": CANARY_KEY, "query": "x", "max_results": 1},
    )
    errs = []
    if status != 401:
        errs.append(f"expected 401, got {status}")
    if _walk(body, ("detail", "error")) is None and _walk(body, ("detail",)) is None:
        errs.append(f"detail.error missing (body keys: {list(body.keys()) if isinstance(body, dict) else type(body).__name__})")
    return errs, raw


async def check_elevenlabs(client):
    status, body, raw = await _probe(
        client, "GET",
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": CANARY_KEY},
    )
    errs = []
    if status != 401:
        errs.append(f"expected 401, got {status}")
    # ElevenLabs returns detail as either {"status": ..., "message": ...} or a string
    detail = _walk(body, ("detail",))
    if detail is None:
        errs.append("detail missing")
    elif isinstance(detail, dict):
        if detail.get("status") is None and detail.get("message") is None:
            errs.append(f"detail.status/message both missing (detail={detail!r})")
    return errs, raw


CHECKS = [
    ("anthropic", check_anthropic),
    ("openai", check_openai),
    ("gemini", check_gemini),
    ("tavily", check_tavily),
    ("elevenlabs", check_elevenlabs),
]


async def run():
    drift = []
    transport_errors = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for name, check in CHECKS:
            try:
                errs, raw = await check(client)
                if errs:
                    drift.append((name, errs, raw))
                    print(f"❌ {name}: DRIFT", file=sys.stderr)
                    for e in errs:
                        print(f"   - {e}", file=sys.stderr)
                    print(f"   raw body head: {raw!r}", file=sys.stderr)
                else:
                    print(f"✅ {name}: schema intact")
            except Exception as e:
                transport_errors.append((name, str(e)))
                print(f"⚠️  {name}: transport error — {e}", file=sys.stderr)
    return drift, transport_errors


def main():
    drift, transport_errors = asyncio.run(run())
    if drift:
        print(f"\n🚨 {len(drift)} provider(s) have drifted schema — vault.py error parsers may be falling through to the generic status-code message.", file=sys.stderr)
        sys.exit(1)
    if transport_errors:
        print(f"\n⚠️  {len(transport_errors)} transport error(s) — unrelated to schema, likely network/DNS.", file=sys.stderr)
        sys.exit(2)
    print(f"\n🎉 {len(CHECKS)}/{len(CHECKS)} validator schemas intact")
    sys.exit(0)


if __name__ == "__main__":
    main()
