"""Build a creator's LOCKED channel identity from their OWN top-performing videos.

Source of truth = the videos, not operator input. We rank the channel's imported
videos by real view count (YouTube Data API), pull transcripts + metadata for the
top few via Firecrawl (its own IP, past the YouTube bot-block on our server),
then distill a comprehensive identity:

  - script voice: tone, cadence, hook, structure
  - research_approach: what sourcing/facts the channel relies on + what to look for
  - real_quotes: VERBATIM lines pulled from the actual transcripts (real examples)
  - signature_phrases: recurring framing patterns
  - visual_format: how the videos look (static vs motion, segmentation, on-camera?)
  - thumbnail_style: repeatable thumbnail formula (vision analysis of top thumbnails)
  - style_description: prose guidance the producer injects

Outputs land on channel_profiles (style_description + channel_identity JSONB).
"""

import asyncio
import json
import os
import re
from typing import Any, Optional

import httpx

from database import execute, fetch_all, fetch_one
# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from actions import claude_model_for_direct_client
# Provenance envelope (checklist C40) — every channel_identity writer must
# read-modify-write through this so unrelated fields (another writer's
# visual_format, thumbnail_blueprint, ...) and the _sources/_history
# envelope survive a rebuild instead of being clobbered by a blind overwrite.
from channel_dna_meta import coerce_identity, stamp_identity_write

FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"
_YT_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"

IDENTITY_PROMPT = (
    "You are reverse-engineering a YouTube channel's identity from its OWN top videos so "
    "an AI can produce NEW videos that are indistinguishable from the creator's. The "
    "transcripts below are the ground truth — infer everything from them.\n\n"
    "Return STRICT JSON (nothing outside the JSON) with these keys:\n"
    '  "voice_tone": short phrase for the narration voice,\n'
    '  "cadence": how they pace and deliver,\n'
    '  "hook_style": exactly how they open a video,\n'
    '  "structure": how a typical video is organized start to finish,\n'
    '  "research_approach": {"sources": what kinds of sources/evidence they cite, '
    '"fact_types": the specific fact types they lean on (dates, designations, costs, names...), '
    '"depth": how deep/rigorous, "what_to_look_for": a directive telling a researcher exactly '
    'what to dig up for a new video in this channel},\n'
    '  "real_quotes": [6-10 VERBATIM sentences copied WORD-FOR-WORD from the transcripts — '
    "the most characteristic lines that capture the voice; do NOT paraphrase or use brackets/placeholders],\n"
    '  "signature_phrases": [3-6 recurring framing patterns/devices they actually use],\n'
    '  "visual_format": {"style": overall visual style, "motion": static images vs animation vs '
    'footage, "segmentation": how segments are divided, "on_camera": is there an on-camera host},\n'
    '  "cadence_example": ONE verbatim sentence copied EXACTLY from a transcript that best shows the cadence,\n'
    '  "structure_example": ONE verbatim sentence copied EXACTLY from a transcript that shows a structural '
    "moment (a cold-open fact or a closing verdict),\n"
    '  "style_description": one 150-250 word paragraph of direct guidance for an AI scriptwriter '
    "to reproduce this voice (tone, vocabulary, hook, structure, audience).\n"
)

THUMB_PROMPT = (
    "These are thumbnails from ONE YouTube channel. Extract the repeatable thumbnail FORMULA so "
    "we can generate matching ones. Return STRICT JSON: {\"layout\": composition/where elements sit, "
    "\"subject\": the main visual subject and how it's treated, \"text_style\": title text placement/"
    "size/casing, \"color_palette\": dominant colors, \"mood\": overall feel, \"recurring_elements\": "
    "anything that repeats across them}."
)


def _norm(s: str) -> str:
    """Lowercase, strip quotes/punctuation-ish, collapse whitespace — for matching
    an LLM-quoted example against the real transcript text."""
    return re.sub(r"\s+", " ", re.sub(r"[\"'“”‘’.,;:!?—-]", " ", (s or "").lower())).strip()


def _opening(transcript: str, max_chars: int = 220) -> str:
    """The literal first sentence(s) of a transcript — a provably-real hook example."""
    t = re.sub(r"\s+", " ", transcript or "").strip()
    m = re.match(r"(.{40,%d}?[.!?])(\s|$)" % max_chars, t)
    return (m.group(1) if m else t[:max_chars]).strip()


def _verify_quote(quote: str, corpus_norm: str) -> bool:
    """True if a meaningful chunk of the quote actually appears in the transcripts —
    so we never show an 'example' the model invented."""
    q = _norm(quote)
    if len(q) < 20:
        return False
    return q[:60] in corpus_norm


def _parse_json(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            text = text[s : e + 1]
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return {}


async def _firecrawl_transcript(video_id: str) -> Optional[str]:
    """Scrape a video page via Firecrawl and return the transcript body.

    YouTube 403s Firecrawl's default IP under load, returning an error page (HTTP
    200, no transcript). So we try the cheap default proxy first and escalate to
    Firecrawl's `stealth` proxy (costs more credits, but gets past the 403)."""
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        return None
    url = f"https://www.youtube.com/watch?v={video_id}"
    # waitFor lets YouTube's JS render the transcript panel before we read the page
    # (without it Firecrawl grabs the page too early and the transcript is missing).
    for mode in (None, "stealth"):
        payload: dict[str, Any] = {"url": url, "formats": ["markdown"], "waitFor": 5000}
        if mode:
            payload["proxy"] = mode
        try:
            async with httpx.AsyncClient(timeout=150.0) as c:
                r = await c.post(
                    FIRECRAWL_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                )
            if r.status_code == 200:
                md = (r.json().get("data") or {}).get("markdown") or ""
                parts = re.split(r"##\s*Transcript", md, maxsplit=1, flags=re.I)
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()
        except Exception:  # noqa: BLE001
            pass
    return None


async def _enrich_views(tenant_id: str, video_ids: list[str]) -> None:
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


async def _ranked_videos(tenant_id: str, limit: int) -> list[dict]:
    q = ("SELECT video_id, title, view_count, thumbnail_url, duration_seconds "
         "FROM channel_videos WHERE tenant_id=$1 AND video_id IS NOT NULL")
    rows = await fetch_all(q, tenant_id)
    if not rows:
        return []
    if not any((r.get("view_count") or 0) for r in rows):
        await _enrich_views(tenant_id, [r["video_id"] for r in rows])
        rows = await fetch_all(q, tenant_id)
    rows.sort(key=lambda r: (r.get("view_count") or 0), reverse=True)
    # Checklist C46e (OR-6 expanded): a CONFIRMED 'anti'-polarity
    # channel_patterns row keeps its evidence-linked video(s) out of the
    # style-seed corpus entirely — this is the exclusion half of the
    # capability Ryan ruled for (never a hardcoded blacklist, per-channel,
    # opt-in, nothing excluded until a human confirms it). Fails open (an
    # empty exclusion set) on any lookup error, matching every pre-C46e
    # tenant's behavior.
    from channel_patterns import confirmed_anti_video_ids

    excluded = await confirmed_anti_video_ids(tenant_id)
    if excluded:
        rows = [r for r in rows if str(r.get("video_id")) not in excluded]
    return rows[:limit]


async def _thumbnail_style(tenant_id: str, thumb_urls: list[str]) -> Optional[dict]:
    """Vision pass over the top thumbnails -> a repeatable thumbnail formula (JSON).

    Checklist C43 (thumbnail-formula convergence): this used to hit Kie's
    Claude gateway directly with a raw httpx POST — the exact endpoint
    `shared.clients.vision_client` was built to route AROUND, because that
    gateway has twice silently dropped image blocks (HTTP 200, plausible
    text, no pixels actually seen — see that module's own docstring).
    `routes/model_video.py::_describe_thumbnail_style` (the OTHER thumbnail-
    formula extractor — writes `channel_identity.thumbnail_blueprint`, read
    by `pipeline_executor._run_channel_formula_thumbnail`) already goes
    through `vision_call` for exactly that reason. Converging this learner
    onto the SAME safe primitive closes the drift risk between the two
    thumbnail-formula code paths without merging their two distinct JSON
    schemas (this one aggregates a consensus style across up to 3 thumbnails
    for prompt-injection; the other extracts one detailed blueprint for
    image-generation transformation) — those still serve different
    consumers and stay separate. Skips gracefully if no Kie key or no
    thumbnails; any provider failure (including every provider in the
    vision_call chain failing) returns None exactly as the old bare
    try/except did, so a tenant with no working vision path sees identical
    behavior to before."""
    from vault import get_secret
    from shared.clients.vision_client import vision_call

    key = await get_secret("kie_ai_api_key", tenant_id)
    if not key or not thumb_urls:
        return None
    try:
        # 1400 tokens: the formula JSON alone can exceed 700 and a truncated
        # reply fails json.loads -> the style silently vanished from rebuilt
        # identities (bit DVU 2026-07-01) — preserved from the old call.
        raw = await vision_call(
            THUMB_PROMPT, thumb_urls[:3], kie_key=key, tier="fast", max_tokens=1400,
        )
        return _parse_json(raw) or None
    except Exception:  # noqa: BLE001 — VisionUnavailable or any provider failure
        return None


async def build_channel_identity(tenant_id: str, top_n: int = 3) -> dict[str, Any]:
    """Rank -> Firecrawl transcripts (sequential + retry, extra candidates) -> LLM
    distill + thumbnail vision -> store. Returns a result dict."""
    from kie_unified import get_text_client_for_tenant

    # Pull extra candidates so videos without captions / transient misses don't
    # starve us below top_n.
    candidates = await _ranked_videos(tenant_id, top_n + 4)
    if not candidates:
        return {"ok": False, "error": "no videos imported for this channel yet"}

    analyzed: list[tuple[str, str]] = []
    thumbs: list[str] = []
    for v in candidates:
        if len(analyzed) >= top_n:
            break
        transcript = await _firecrawl_transcript(v["video_id"])
        if not transcript:
            continue
        await execute(
            "UPDATE channel_videos SET transcript=$1, transcript_source='firecrawl', "
            "transcript_fetched_at=now() WHERE tenant_id=$2 AND video_id=$3",
            transcript[:20000], tenant_id, v["video_id"],
        )
        analyzed.append((v.get("title") or "", transcript[:6000]))
        if v.get("thumbnail_url"):
            thumbs.append(v["thumbnail_url"])

    if not analyzed:
        return {"ok": False, "error": "could not fetch transcripts (Firecrawl) for the top videos"}

    client = await get_text_client_for_tenant(tenant_id)  # raises if keyless
    body = "\n\n".join(f"VIDEO: {title}\nTRANSCRIPT:\n{tr}" for title, tr in analyzed)
    kwargs: dict[str, Any] = {"prompt": IDENTITY_PROMPT + "\n\n" + body, "max_tokens": 2200}
    model = claude_model_for_direct_client(client)
    if model:
        kwargs["model"] = model
    raw = await client.generate(**kwargs)
    identity = _parse_json(raw or "")
    if not identity:
        return {"ok": False, "error": "identity model returned an unparseable reply"}

    thumb_style = await _thumbnail_style(tenant_id, thumbs)
    if thumb_style:
        identity["thumbnail_style"] = thumb_style
    identity["_source_videos"] = [t for t, _ in analyzed]

    # Ground the traits in provably-real examples. Hook examples are the literal
    # openings of each analyzed video; model-picked examples are dropped unless they
    # actually appear in the transcripts (so nothing shown is invented).
    corpus_norm = _norm(" ".join(tr for _, tr in analyzed))
    identity["hook_examples"] = [{"video": title, "line": _opening(tr)} for title, tr in analyzed]
    for k in ("cadence_example", "structure_example"):
        if identity.get(k) and not _verify_quote(identity[k], corpus_norm):
            identity.pop(k, None)
    if identity.get("real_quotes"):
        identity["real_quotes"] = [q for q in identity["real_quotes"] if _verify_quote(q, corpus_norm)]

    prose = (identity.get("style_description") or "").strip()

    # Read-modify-write: this rebuild only knows about voice/hook/structure/
    # research/thumbnail fields, but the SAME column may already hold a
    # channel_format.set_channel_format visual_format/format_locked or a
    # pipeline_executor thumbnail_blueprint cache. A blind overwrite here
    # would silently erase those (and any prior provenance envelope) every
    # time the identity is rebuilt — stamp_identity_write merges instead.
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    current = coerce_identity((row or {}).get("channel_identity"))
    merged = stamp_identity_write(current, identity, learner="identity_builder")

    await execute(
        "UPDATE channel_profiles "
        "SET style_description = COALESCE(NULLIF($2, ''), style_description), "
        "    channel_identity = $3::jsonb, updated_at = now() "
        "WHERE tenant_id = $1",
        tenant_id, prose, json.dumps(merged),
    )
    return {"ok": True, "identity": identity, "videos_analyzed": [t for t, _ in analyzed]}
