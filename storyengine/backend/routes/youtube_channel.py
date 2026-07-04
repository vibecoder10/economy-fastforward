"""User's own YouTube channel endpoints.

Distinct from youtube_sync.py (metrics for videos already in our DB) and
niche.py (competitor channel scraping). This file handles fetching the
AUTHENTICATED USER's own channel videos — needed for Flow B onboarding
(detect existing-channel users, learn their voice from top performers).

Endpoints:
    GET /api/youtube/my-videos — user's top-performing videos from their
        connected YouTube channel. Uses their OAuth refresh token. Returns
        title, views, published_at, thumbnail, video_id for up to N videos.

    POST /api/youtube/learn-voice — analyzes the user's top videos
        (titles + descriptions) with Claude to produce a voice/style
        description suitable for feeding into the system-prompt generator.
        Flow B slice 2.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_tenant_id
from database import fetch_one
from error_utils import humanize_error
from youtube_owner_api import (
    refresh_access_token as _refresh_access_token,
    fetch_uploads_playlist_id as _fetch_uploads_playlist_id,
    fetch_playlist_video_ids as _fetch_playlist_video_ids,
    fetch_video_details as _fetch_video_details,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/youtube", tags=["youtube-channel"])


@router.get("/my-videos")
async def my_videos(
    limit: int = Query(10, ge=1, le=50),
    sort: str = Query("views", pattern="^(views|recent)$"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Fetch the authenticated user's own channel videos, ranked.

    Use cases:
        - Onboarding Flow B: detect existing-channel users + show their
          top performers so we can offer to auto-learn their voice.
        - Future: pick videos to analyze for voice / style / performance
          patterns without scraping.

    Returns:
        { videos: [...], channel_id: "...", total_scanned: int }
        Each video: { video_id, title, description, published_at, thumbnail,
                      views, likes, comments }

    Errors:
        404 when the user hasn't connected YouTube (no refresh_token on
            channel_profiles) — frontend should treat as "no existing channel"
            and skip the voice-learn step.
        503 when Google OAuth isn't configured on this environment.
        502 when YouTube API calls fail (quota, auth) — frontend should
            degrade gracefully, not block onboarding.
    """
    row = await fetch_one(
        "SELECT youtube_refresh_token, youtube_channel_id FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    refresh_token = row.get("youtube_refresh_token") if row else None
    if not refresh_token:
        raise HTTPException(status_code=404, detail="YouTube not connected")

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    access_token = await _refresh_access_token(client_id, client_secret, refresh_token)
    if not access_token:
        raise HTTPException(
            status_code=502,
            detail="Could not refresh YouTube access. Reconnect YouTube in Settings.",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        uploads_playlist = await _fetch_uploads_playlist_id(client, access_token)
        if not uploads_playlist:
            raise HTTPException(
                status_code=502, detail="Could not locate your YouTube uploads playlist"
            )

        # Scan up to 50 of the user's most recent uploads, then rank. 50 is a
        # good balance: enough signal to find top performers, cheap in quota.
        video_ids = await _fetch_playlist_video_ids(
            client, access_token, uploads_playlist, max_videos=50
        )
        if not video_ids:
            return {
                "videos": [],
                "channel_id": row.get("youtube_channel_id", "") if row else "",
                "total_scanned": 0,
            }

        videos = await _fetch_video_details(client, access_token, video_ids)

    if sort == "views":
        videos.sort(key=lambda v: v["views"], reverse=True)
    else:  # recent
        videos.sort(key=lambda v: v["published_at"], reverse=True)

    return {
        "videos": videos[:limit],
        "channel_id": row.get("youtube_channel_id", "") if row else "",
        "total_scanned": len(videos),
    }


VOICE_LEARN_PROMPT = """You are analyzing a YouTube creator's own content to infer their unique voice and style. Below are their top-performing videos. When a TRANSCRIPT is provided, treat it as the PRIMARY voice signal — transcripts capture the creator's actual spoken cadence, word choice, and hook style far better than titles or descriptions. Fall back to description only when no transcript is available. Your job: produce a rich, specific style description that will be used to customize AI-generated scripts to match their real voice.

Focus on:
- Voice & tone (e.g. authoritative, conversational, sarcastic, energetic, calm)
- Vocabulary patterns (signature phrases, jargon, slang, reading level)
- Hook/opening style (how they start videos, how they grab attention)
- Structural tendencies (list-based, story-based, analytical, emotional)
- Target audience (inferred from language + topics)
- Any recurring themes or framing devices

Do NOT:
- Quote entire titles back at me
- Use vague adjectives alone ("engaging", "compelling") without specifics
- Exceed 300 words

Output format: a single cohesive paragraph (150-300 words) written as direct style guidance for an AI script writer. Start with the voice/tone, then cover vocabulary + structure + audience. No bullet points, no headers.

CHANNEL NAME: {channel_name}
TOP VIDEOS:
{video_list}

Write the style description now."""

# Cap per-video transcript length so a few long videos don't blow out the
# Claude context budget. 2000 chars ≈ 400 words, enough to capture 2-3 minutes
# of spoken content and still fit 5 videos + prompt + description fallbacks
# well under Sonnet 4's context.
TRANSCRIPT_CHAR_CAP = 2000


async def _fetch_transcripts_for_videos(videos: list[dict]) -> None:
    """Mutate `videos` in-place: attach a `transcript` key (or None) to each.

    Uses the existing `routes.niche._extract_video_info` helper (yt-dlp +
    VTT/JSON3 parsing). Runs all fetches concurrently in the default thread
    pool so a slow yt-dlp call on one video doesn't block the others.

    Failures are silent — a missing transcript falls back to the description.
    The voice summarizer handles mixed transcript/description sets fine.
    """
    from routes.niche import _extract_video_info

    loop = asyncio.get_event_loop()

    async def _one(video: dict) -> None:
        vid = video.get("video_id")
        if not vid:
            video["transcript"] = None
            return
        try:
            info = await loop.run_in_executor(None, _extract_video_info, vid)
        except Exception as e:
            logger.warning("[learn-voice] yt-dlp failed for %s: %s", vid, e)
            video["transcript"] = None
            return
        raw = (info or {}).get("transcript") or ""
        raw = raw.strip()
        if not raw:
            video["transcript"] = None
            return
        if len(raw) > TRANSCRIPT_CHAR_CAP:
            raw = raw[:TRANSCRIPT_CHAR_CAP] + "..."
        video["transcript"] = raw

    await asyncio.gather(*(_one(v) for v in videos))


async def _claude_summarize_voice(
    api_key: str, channel_name: str, videos: list[dict]
) -> str:
    """Send top videos' transcripts (preferred) or descriptions to Claude,
    return a voice/style description.

    Each video dict may carry a `transcript` key (populated by
    `_fetch_transcripts_for_videos`). When present and non-empty it
    replaces the description in the prompt body. When absent, falls back
    to the description trimmed at 400 chars.
    """
    lines = []
    for i, v in enumerate(videos, 1):
        transcript = (v.get("transcript") or "").strip()
        if transcript:
            # Transcript is already capped by _fetch_transcripts_for_videos
            body = f"TRANSCRIPT: {transcript}"
        else:
            desc = (v.get("description") or "").strip()
            # Trim descriptions — the boilerplate (links, hashtags) past the
            # first ~400 chars is usually noise, not voice signal.
            if len(desc) > 400:
                desc = desc[:400] + "..."
            body = f"DESCRIPTION: {desc}" if desc else "(no description)"
        lines.append(
            f"{i}. [{v.get('views', 0):,} views] {v.get('title', '')}\n   {body}"
        )
    video_list = "\n\n".join(lines)

    prompt = VOICE_LEARN_PROMPT.format(
        channel_name=channel_name or "Unknown", video_list=video_list
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1200,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    if resp.status_code != 200:
        logger.error("Claude voice-learn failed %s: %s", resp.status_code, resp.text[:300])
        raise HTTPException(
            status_code=502,
            detail=humanize_error(
                f"Claude {resp.status_code}",
                context="We couldn't analyze your channel's voice",
            ),
        )
    body = resp.json()
    try:
        return body["content"][0]["text"].strip()
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail="Claude returned empty voice analysis")


@router.post("/learn-voice")
async def learn_voice(tenant_id: str = Depends(get_tenant_id)):
    """Infer a voice/style description from the user's top YouTube videos.

    Pulls their top 5 videos (same logic as /my-videos), sends titles +
    descriptions to Claude, returns a ready-to-use `style_description`
    suitable for the /system-prompts/generate endpoint.

    Also persists the result to `channel_profiles.style_description` so
    the Style step of onboarding can pre-fill the field.

    Why no body params: v1 is an opinionated "learn from top 5 by views."
    If we need control later (pick specific videos, pick by recency),
    add a body — but for onboarding UX, zero-config beats choice.

    Errors:
        400 — Anthropic API key not configured
        404 — YouTube not connected OR no videos found on channel
        502 — YouTube or Claude API failure
    """
    row = await fetch_one(
        "SELECT youtube_refresh_token, youtube_channel_id, youtube_channel_name FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    refresh_token = row.get("youtube_refresh_token") if row else None
    if not refresh_token:
        raise HTTPException(status_code=404, detail="YouTube not connected")

    # Get Anthropic API key (same path as system_prompts.generate)
    from vault import get_secret

    api_key = await get_secret("anthropic_api_key", tenant_id)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Anthropic API key required. Configure it in Settings > API Keys.",
        )

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    access_token = await _refresh_access_token(client_id, client_secret, refresh_token)
    if not access_token:
        raise HTTPException(
            status_code=502,
            detail="Could not refresh YouTube access. Reconnect YouTube in Settings.",
        )

    # Fetch top 5 by views — same plumbing as /my-videos
    async with httpx.AsyncClient(timeout=30.0) as client:
        uploads = await _fetch_uploads_playlist_id(client, access_token)
        if not uploads:
            raise HTTPException(status_code=502, detail="Could not locate uploads playlist")
        ids = await _fetch_playlist_video_ids(client, access_token, uploads, max_videos=50)
        if not ids:
            raise HTTPException(status_code=404, detail="No videos found on your channel yet")
        videos = await _fetch_video_details(client, access_token, ids)

    videos.sort(key=lambda v: v["views"], reverse=True)
    top5 = videos[:5]

    # Enrich with transcripts for richer voice extraction. Silent fallback
    # to description if yt-dlp can't pull captions for a given video.
    await _fetch_transcripts_for_videos(top5)

    channel_name = row.get("youtube_channel_name", "") if row else ""
    style_description = await _claude_summarize_voice(api_key, channel_name, top5)

    # Persist to channel_profiles so Style step can pre-fill
    await execute_safely(tenant_id, style_description)

    transcript_count = sum(1 for v in top5 if (v.get("transcript") or "").strip())

    return {
        "status": "learned",
        "style_description": style_description,
        "transcript_count": transcript_count,  # how many of top5 had usable transcripts
        "source_videos": [
            {
                "video_id": v["video_id"],
                "title": v["title"],
                "views": v["views"],
                "has_transcript": bool((v.get("transcript") or "").strip()),
            }
            for v in top5
        ],
    }


async def execute_safely(tenant_id: str, style_description: str) -> None:
    """Persist the learned style_description. Import locally so the
    module stays testable without a DB connection."""
    from database import execute

    await execute(
        "UPDATE channel_profiles SET style_description = $2, updated_at = now() WHERE tenant_id = $1",
        tenant_id,
        style_description,
    )
