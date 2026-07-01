"""Build a creator's channel identity from their OWN top-performing videos.

The source of truth is the videos, not the operator's words. We rank the channel's
imported videos by real view count (YouTube Data API), pull the transcripts +
metadata of the top few via Firecrawl (which scrapes from its own IP, past the
YouTube bot-block that hits our server), then distill a voice/cadence/format
profile with the tenant's text model.

Outputs land on channel_profiles:
  - style_description  : prose voice guidance the producer already injects
  - channel_identity   : the full structured JSON profile (queryable, re-buildable)
And each analyzed transcript is cached back onto channel_videos so we don't re-scrape.
"""

import json
import os
import re
from typing import Any, Optional

import httpx

from database import execute, fetch_all

FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"
_YT_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"

IDENTITY_PROMPT = (
    "You are analyzing a YouTube creator's OWN top-performing videos to extract the "
    "channel's identity, so an AI can write NEW scripts and design thumbnails that match "
    "their real voice and format. The transcripts below ARE the ground truth — infer "
    "everything from them, not from assumptions.\n\n"
    "Return STRICT JSON (no prose outside the JSON) with these keys:\n"
    '  "voice_tone": short phrase,\n'
    '  "cadence": how they pace/deliver,\n'
    '  "hook_style": how they open,\n'
    '  "research_depth": how deep/what kind of sourcing,\n'
    '  "structure": how a typical video is organized,\n'
    '  "signature_phrases": array of 3-6 recurring phrases/framing devices actually seen,\n'
    '  "inferred_format": one line on the format (length, static vs dynamic, segmentation),\n'
    '  "style_description": a single 150-250 word paragraph of direct guidance for an AI '
    "scriptwriter to reproduce this voice (tone, vocabulary, hook, structure, audience).\n"
)


def _parse_identity(raw: str) -> dict[str, Any]:
    """Pull the JSON object out of an LLM reply, tolerating ```json fences / preamble."""
    if not raw:
        return {}
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001 — a malformed reply shouldn't crash onboarding
        return {}


async def _firecrawl_transcript(video_id: str) -> Optional[str]:
    """Scrape a video's page via Firecrawl and return the transcript body, if present."""
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(
                FIRECRAWL_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"url": f"https://www.youtube.com/watch?v={video_id}", "formats": ["markdown"]},
            )
        if r.status_code != 200:
            return None
        md = (r.json().get("data") or {}).get("markdown") or ""
    except Exception:  # noqa: BLE001
        return None
    parts = re.split(r"##\s*Transcript", md, maxsplit=1, flags=re.I)
    if len(parts) < 2:
        return None
    body = parts[1].strip()
    return body or None


async def _enrich_views(tenant_id: str, video_ids: list[str]) -> None:
    """Backfill real view counts from the YouTube Data API (not IP-blocked)."""
    key = os.getenv("YOUTUBE_API_KEY")
    if not key or not video_ids:
        return
    async with httpx.AsyncClient(timeout=30.0) as c:
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            r = await c.get(_YT_VIDEOS_API, params={"part": "statistics", "id": ",".join(batch), "key": key})
            if r.status_code != 200:
                continue
            for it in r.json().get("items", []):
                vc = int((it.get("statistics") or {}).get("viewCount", 0) or 0)
                await execute(
                    "UPDATE channel_videos SET view_count=$1, updated_at=now() WHERE tenant_id=$2 AND video_id=$3",
                    vc, tenant_id, it.get("id"),
                )


async def _top_videos(tenant_id: str, n: int) -> list[dict]:
    q = ("SELECT video_id, title, view_count, thumbnail_url, duration_seconds "
         "FROM channel_videos WHERE tenant_id=$1 AND video_id IS NOT NULL")
    rows = await fetch_all(q, tenant_id)
    if not rows:
        return []
    if not any((r.get("view_count") or 0) for r in rows):
        await _enrich_views(tenant_id, [r["video_id"] for r in rows])
        rows = await fetch_all(q, tenant_id)
    rows.sort(key=lambda r: (r.get("view_count") or 0), reverse=True)
    return rows[:n]


async def build_channel_identity(tenant_id: str, top_n: int = 3) -> dict[str, Any]:
    """Rank -> Firecrawl transcripts -> LLM distill -> store. Returns a result dict."""
    from kie_unified import get_text_client_for_tenant

    top = await _top_videos(tenant_id, top_n)
    if not top:
        return {"ok": False, "error": "No videos imported for this channel yet."}

    analyzed: list[tuple[str, str]] = []
    for v in top:
        transcript = await _firecrawl_transcript(v["video_id"])
        if not transcript:
            continue
        await execute(
            "UPDATE channel_videos SET transcript=$1, transcript_source='firecrawl', "
            "transcript_fetched_at=now() WHERE tenant_id=$2 AND video_id=$3",
            transcript[:20000], tenant_id, v["video_id"],
        )
        analyzed.append((v.get("title") or "", transcript[:6000]))

    if not analyzed:
        return {"ok": False, "error": "Could not fetch transcripts (Firecrawl) for the top videos."}

    client = await get_text_client_for_tenant(tenant_id)  # raises MissingGenerationKeyError if keyless
    body = "\n\n".join(f"VIDEO: {title}\nTRANSCRIPT:\n{tr}" for title, tr in analyzed)
    # AnthropicDirect needs an explicit current model id; the Kie client keeps a valid default.
    kwargs: dict[str, Any] = {"prompt": IDENTITY_PROMPT + "\n\n" + body, "max_tokens": 1400}
    if type(client).__name__ == "AnthropicDirectClient":
        kwargs["model"] = "claude-sonnet-4-6"
    raw = await client.generate(**kwargs)
    identity = _parse_identity(raw or "")
    if not identity:
        return {"ok": False, "error": "Identity model returned an unparseable reply."}

    identity["_source_videos"] = [t for t, _ in analyzed]
    prose = (identity.get("style_description") or "").strip()
    await execute(
        "UPDATE channel_profiles "
        "SET style_description = COALESCE(NULLIF($2, ''), style_description), "
        "    channel_identity = $3, updated_at = now() "
        "WHERE tenant_id = $1",
        tenant_id, prose, json.dumps(identity),
    )
    return {"ok": True, "identity": identity, "videos_analyzed": [t for t, _ in analyzed]}
