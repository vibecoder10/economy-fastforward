"""Kie source discovery returns leads only; fetched pages own the evidence."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import socket
from urllib.parse import urlsplit, urlunsplit

from error_utils import user_facing

MODEL = "gpt-5-2"
ENDPOINT = "https://api.kie.ai/gpt-5-2/v1/chat/completions"
USD_PER_CREDIT = 0.005  # Same configured conversion as the existing Kie adapters.


class SourceDiscoveryError(RuntimeError):
    """Stop the research chain without entering the legacy card-repair loop."""


def public_source_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value.strip())
        host = (url.hostname or "").lower()
        if url.scheme not in {"https", "http"} or url.username or url.password or url.port not in {None, 80, 443}:
            return None
        if "." not in host or host.endswith((".local", ".localhost", ".internal")):
            return None
        if host == "grokipedia.com" or host.endswith(".grokipedia.com"):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value.strip()
    except ValueError:
        return None


async def guard_public_request(request) -> None:
    """Check every fetch and redirect, including hostnames resolving internally."""
    url = public_source_url(str(request.url))
    if not url:
        raise ValueError("Source URL is not public")
    parts = urlsplit(url)
    addresses = await asyncio.get_running_loop().getaddrinfo(
        parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM,
    )
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("Source host does not resolve to a public address")


async def discover_sources(client, api_key: str, title: str, machine: str, *, subject: str | None = None,
                           attempted_urls: list[str] | None = None,
                           excluded_hosts: list[str] | None = None,
                           missing_fields: list[str] | None = None) -> tuple[list[dict], dict]:
    subject = str(subject or machine).strip()
    prior = list(dict.fromkeys(str(url).strip() for url in (attempted_urls or []) if str(url).strip()))
    blocked = list(dict.fromkeys(str(host).strip() for host in (excluded_hosts or []) if str(host).strip()))
    prompt = (
        f"Use web search to find 6 real source pages specifically about the subject {subject!r} "
        f"(locked roster identity: {machine!r}) "
        f"for a factual documentary titled {title!r}. Prefer official government, manufacturer, "
        "museum and archive history/fact-sheet pages. Specifically find the original intended role or problem, "
        "distinctive engineering decisions, actual operational/training/testing use, and fate or lasting consequence. "
        "Prioritize exact-machine service histories over designer biographies and repeated component lists. "
        "A launch or commissioning date alone does not establish actual use. Seek evidence of the designed-versus-used "
        "relationship without assuming there was a reversal. Include supported production and memorable details where available. "
        "Match the exact aircraft variant or named vessel; do not substitute "
        "a related model. Prefer substantive article pages over photo-gallery listings. "
        "Return only a compact JSON array of objects with title and exact_source_url, plus optional pdf_page "
        "when the source is a PDF and its relevant page is known. pdf_page must be a positive page number. "
        "Use original source URLs, never invented URLs or AI encyclopedias. No prose or excerpts."
        + (" Missing research fields to prioritize: " + ", ".join(field for field in missing_fields
            if field in {"intended_role", "design", "actual_use", "outcome"}) + "." if missing_fields else "")
    )
    if prior:
        prompt += " Do not repeat these already attempted URLs: " + ", ".join(prior[:24]) + "."
    if blocked:
        prompt += " Avoid these hosts because they produced no readable capture: " + ", ".join(blocked[:12]) + "."
    try:
        response = await client.post(ENDPOINT, headers={"Authorization": "Bearer " + api_key}, json={
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "function", "function": {"name": "web_search"}}],
            "stream": False,
        }, timeout=120)
        data = response.json()
    except Exception as exc:
        raise SourceDiscoveryError(user_facing(
            "Kie source search did not return a confirmed result. Completed research is saved; retry to resume."
        )) from exc
    code = data.get("code") if isinstance(data, dict) else None
    if response.status_code >= 400 or code not in {None, 200}:
        raw = str(data.get("msg") or "").lower() if isinstance(data, dict) else ""
        if response.status_code in {401, 403} or code in {401, 403}:
            detail = "Kie API key needs attention. Update it in Settings, then resume; completed research is saved."
        elif response.status_code == 402 or code == 402 or any(word in raw for word in ("credit", "balance", "insufficient")):
            detail = "Kie is out of credits. Add credits, then resume; completed research is saved."
        else:
            detail = "Kie source search is temporarily unavailable. Completed research is saved; retry to resume."
        raise SourceDiscoveryError(user_facing(detail))
    try:
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        rows = json.loads(content)
        if not isinstance(rows, list):
            raise ValueError("Expected source list")
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise SourceDiscoveryError(user_facing(
            "Kie source search returned no usable source list. Completed research is saved; retry to resume."
        )) from exc
    leads = []
    seen = set()
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        url = public_source_url(row.get("exact_source_url"))
        supplied_page = row.get("pdf_page")
        if supplied_page is not None:
            if isinstance(supplied_page, bool) or not isinstance(supplied_page, int) or not 0 < supplied_page <= 10_000:
                continue
            parts = urlsplit(url) if url else None
            existing = parts.fragment if parts else ""
            expected = f"page={supplied_page}"
            if existing and existing != expected:
                continue
            if url and not existing:
                url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, expected))
        if url and url not in seen:
            seen.add(url)
            leads.append({"url": url, "title": str(row.get("title") or url)[:300], "_query": prompt})
        if len(leads) >= 6:
            break
    if not leads:
        raise SourceDiscoveryError(user_facing(
            "Kie source search returned no public source links. Completed research is saved; retry to resume."
        ))
    credits = data.get("credits_consumed")
    try:
        credits = float(credits) if credits is not None else None
        if credits is not None and (not math.isfinite(credits) or credits < 0):
            credits = None
    except (TypeError, ValueError):
        credits = None
    return leads, {
        "provider": "kie", "model": MODEL, "request_id": data.get("id"),
        "credits_consumed": credits, "usage": data.get("usage"),
        "lead_count": len(leads), "search_tool": "web_search", "subject": subject,
    }
