"""Model A Video — turn one reference YouTube link into a new modeled idea + prompt pack.

Higgsfield-inspired flow: one input becomes a complete production brief.
Analyze first, generate second. Style DNA is separated from per-scene prompts,
and every artifact is persisted (DB + optional Drive) BEFORE any generation
credits are spent.

Background task stages (polled via the existing GET /api/pipeline/task/{video_id}):
  1. extract   — yt-dlp metadata + transcript + thumbnail (reuses routes.niche._extract_video_info)
  2. analyze   — style DNA via Claude Haiku (reuses distillation.distiller.distill_full_video_dna)
  3. generate  — NEW modeled idea + prompt pack via Claude Sonnet (a new angle, not a copy)
  4. persist   — videos fields, assets prompt rows, competitor_videos attribution,
                 best-effort Drive brief when the tenant has Drive connected

The video lands at 'ready_for_scripting' (NOT 'idea_logged') — modeling already
produces the research material (research_payload: research_brief, script_guidance,
scene_concepts), so the separate research agent is skipped. Running it would only
waste tokens AND clobber the modeled research_payload. The creator still reviews
the modeled idea before scripting; nothing renders or uploads from here. (If a
clone genuinely needs research, POST /api/pipeline/research/<id> still works.)
"""

import asyncio
import calendar
import json
import logging
import os
import re
import uuid as _uuid
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute, fetch_one
from error_utils import humanize_error, user_facing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/model-video", tags=["model-video"])

# Claude calls go through Kie.ai (the tenant's kie_ai_api_key covers Claude too);
# a tenant-scoped anthropic_api_key is the fallback for direct Anthropic access.
# URLs are overridable so E2E tests can point at a local mock without real spend.
KIE_CLAUDE_API_URL = os.getenv("KIE_CLAUDE_API_URL", "https://api.kie.ai/claude/v1/messages")
ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")

# Model ids per provider/tier. Kie.ai uses undated aliases.
CLAUDE_MODELS = {
    "kie": {"smart": "claude-sonnet-4-5", "fast": "claude-haiku-4-5"},
    "anthropic": {"smart": "claude-sonnet-4-20250514", "fast": "claude-haiku-4-5-20251001"},
}
TRANSCRIPT_PROMPT_CHAR_CAP = 8000
TASK_TYPE = "model_video"

_YT_ID_PATTERNS = [
    r"youtube\.com/watch\?(?:[^#\s]*&)?v=([A-Za-z0-9_-]{11})",
    r"youtu\.be/([A-Za-z0-9_-]{11})",
    r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
    r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    r"youtube\.com/live/([A-Za-z0-9_-]{11})",
]


def _parse_youtube_id(url: str) -> Optional[str]:
    for pattern in _YT_ID_PATTERNS:
        match = re.search(pattern, url or "")
        if match:
            return match.group(1)
    return None


class ModelVideoRequest(BaseModel):
    video_url: str


class ModelVideoResponse(BaseModel):
    video_id: str
    status: str
    message: Optional[str] = None


# --- Claude helpers ---

async def _resolve_claude_creds(tenant_id) -> Optional[dict]:
    """Pick the provider for Claude calls: Kie.ai first (it's the one key every
    tenant configures in onboarding), direct Anthropic as fallback."""
    from vault import get_secret
    kie_key = await get_secret("kie_ai_api_key", str(tenant_id))
    if kie_key:
        return {"provider": "kie", "key": kie_key}
    anthropic_key = await get_secret("anthropic_api_key", str(tenant_id))
    if anthropic_key:
        return {"provider": "anthropic", "key": anthropic_key}
    return None


async def _call_claude(prompt: str, creds: dict, tier: str = "smart", max_tokens: int = 6000) -> Optional[str]:
    """Call Claude via the resolved provider; return raw text (fences stripped).

    Text-only on purpose: Kie's Claude gateway silently drops image blocks
    when it drifts (2026-06-12). Anything that needs to SEE pixels goes
    through shared.clients.vision_client.vision_call (provider-chained,
    ingestion-verified) and feeds the observation in as text.

    Retries transient upstream failures (5xx, timeouts, connection drops) —
    Kie.ai returned a raw 500 mid-run in production and a single blip
    shouldn't fail a 90-second modeling task.
    """
    model = CLAUDE_MODELS[creds["provider"]][tier]
    content = prompt
    if creds["provider"] == "kie":
        url = KIE_CLAUDE_API_URL
        headers = {
            "Authorization": f"Bearer {creds['key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "stream": False,  # Kie.ai defaults to streaming — must opt out
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
    else:
        url = ANTHROPIC_API_URL
        headers = {
            "x-api-key": creds["key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }

    data = None
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                # Kie.ai omits the Content-Type header on success — parse text directly.
                data = json.loads(response.text)
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            transient = isinstance(e, httpx.TransportError) or e.response.status_code >= 500
            if not transient or attempt == 2:
                raise
            last_err = e
            logger.warning("[model_video] transient Claude error (attempt %d): %s", attempt + 1, str(e)[:200])
            await asyncio.sleep(2 * (attempt + 1))
    if data is None:
        raise last_err or RuntimeError("Claude call failed")

    # Kie.ai returns HTTP 200 with {"code": 401, "msg": ...} on auth/quota
    # failures — HTTP status alone is a lie for this provider.
    if "content" not in data:
        raise RuntimeError(f"Claude call via {creds['provider']} failed: {str(data.get('msg') or data)[:200]}")

    # Join ALL text blocks — vision replies arrive as multiple content
    # blocks and content[0] alone truncated them to the preamble sentence
    # (live finding: bbox replies ended at "Let me analyze...").
    text = "\n".join(
        b.get("text", "") for b in data["content"] if b.get("type") == "text"
    ).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return text


def _format_dna_prompt(info: dict, transcript: str) -> str:
    """Format the shared DNA-extraction prompt (mirrors distiller.distill_full_video_dna,
    which is hardwired to direct Anthropic — we route through the provider-aware caller)."""
    from distillation.distiller import FULL_VIDEO_DNA_PROMPT
    words = (transcript or "").split()
    if len(words) > 5000:
        transcript = " ".join(words[:5000])
    day_idx = info.get("published_day_of_week")
    like_ratio = info.get("like_ratio") or 0
    vps = info.get("views_per_sub_ratio") or 0
    return FULL_VIDEO_DNA_PROMPT.format(
        title=info.get("title") or "Unknown",
        channel=info.get("channel") or "Unknown",
        views=info.get("views") or 0,
        vph=0,
        duration_seconds=info.get("duration_seconds") or 0,
        likes=info.get("likes") or 0,
        comment_count=info.get("comment_count") or 0,
        channel_subs=info.get("channel_subscriber_count") or 0,
        like_ratio=f"{like_ratio:.4f}" if like_ratio else "N/A",
        views_per_sub_ratio=f"{vps:.2f}" if vps else "N/A",
        published_day=calendar.day_name[day_idx] if isinstance(day_idx, int) and 0 <= day_idx <= 6 else "Unknown",
        published_hour=info.get("published_hour") or 0,
        has_chapters=bool(info.get("has_chapters")),
        description=(info.get("description") or "")[:500],
        tags="None",
        transcript=transcript or "",
    )


async def _distill_dna(creds: dict, info: dict, transcript: str) -> Optional[dict]:
    """Style-DNA extraction via the provider-aware caller (fast tier).
    One retry on malformed JSON — LLM output isn't deterministic."""
    prompt = _format_dna_prompt(info, transcript)
    last_err: Optional[Exception] = None
    for _attempt in range(2):
        try:
            text = await _call_claude(prompt, creds, tier="fast", max_tokens=2048)
            if not text:
                return None
            metadata = json.loads(text)
            summary = metadata.pop("summary", "")
            return {"summary": summary, "structured_metadata": metadata}
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
    raise last_err


MODELED_PACK_PROMPT = """You are a video replication director.

A creator dropped in a REFERENCE video. Design a NEW video that could be the very
next upload on the SAME channel — same topic domain, same audience, same format,
same visual style, same script style. It must feel like a sibling episode of the
reference, NOT an adaptation to a different niche or genre. Ignore everything you
might assume about the creator; the reference IS the brief.

Stay inside the reference's world:
- Same genre and format (if it's a beginner-English animated listening story, make
  another beginner-English animated listening story; if it's a finance documentary,
  make another finance documentary)
- Same audience, tone, and language level
- Same title formula (emoji usage, punctuation, structure, suffix pattern)
- Same visual style — the THUMBNAIL OBSERVATION below is what the reference's
  thumbnail actually looks like (described by a vision pass); replicate exactly
  that art style, palette, and character design
- NEW but adjacent subject matter: a sibling story/topic the same channel would
  publish next. Never copy the reference's exact story, characters, or script lines.

REFERENCE VIDEO:
- Title: {ref_title}
- Channel: {ref_channel}
- Views: {ref_views}
- Duration: {ref_duration}s
- Description (excerpt): {ref_description}

THUMBNAIL OBSERVATION (the reference thumbnail as seen by a vision pass):
{thumbnail_observation}

STYLE DNA ANALYSIS (extracted by a prior pass; may be partial):
{dna_json}

TRANSCRIPT EXCERPT (may be empty if unavailable):
{transcript_excerpt}

Return ONLY valid JSON with exactly this shape:
{{
  "selected_title": "the single best title for the sibling video, using the reference's exact title formula",
  "title_options": ["5 alternative titles, all using the reference's title formula"],
  "angle_thesis": "2-3 sentences: what this sibling video is about and why the reference's audience would watch it next",
  "research_brief": "markdown bullet list: what content/material to gather for THIS kind of video (for story/educational formats: story beats, vocabulary, facts; for documentary formats: stats and sources) (100-200 words)",
  "script_guidance": "markdown: replicate the reference's script approach — hook style, structure, pacing, segment pattern (150-250 words)",
  "script_dna": "direct instructions to the scriptwriter to replicate the reference's script STYLE: narration vs dialogue, language level, sentence length, tone, recurring segment patterns (e.g. comprehension questions, recaps) (60-120 words)",
  "visual_style_brief": "markdown: the reference's visual style as observed (art style, palette, character design, composition), to be replicated across all visuals (100-200 words)",
  "thumbnail_prompt": "one self-contained image-generation prompt for the sibling video's thumbnail in the reference's exact thumbnail style (40-70 words)",
  "image_dna": "style directives for EVERY still image: art style, palette, character design, lighting, recurring motifs — matching the reference's observed visual style (60-100 words)",
  "motion_dna": "directives for EVERY video clip prompt: camera movement, pacing, subject motion matching the reference's format (40-80 words)",
  "thumbnail_dna": "style directives for thumbnail generation matching the reference's thumbnail approach: composition, characters/faces, color blocking, text treatment (40-80 words)",
  "negative_prompts": ["3-6 short style constraints to avoid (styles that would break consistency with the reference, plus 'no watermarks')"],
  "scene_concepts": [
    {{
      "concept": "one sentence: what this scene shows in the sibling video's story/narrative",
      "image_prompt": "self-contained image-generation prompt in the reference's visual style: subject + environment + composition (40-70 words)",
      "video_prompt": "motion direction for animating that image into a 5-8s clip: camera movement, subject motion, atmosphere (20-40 words)"
    }}
  ]
}}

Rules:
- scene_concepts must contain exactly 8 entries covering the sibling video's story arc in order.
- Every image prompt must explicitly carry the reference's OBSERVED art style and rendering medium — whatever it actually is (photorealistic live-action, 3D Pixar-style animation, 2D illustration, anime, etc.) — so an image generator seeing one prompt in isolation still produces the right style. Never substitute a generic animated/illustrated look for a realistic or live-action reference.
- All prompts are about the NEW sibling video's content, in the REFERENCE's style."""


def _build_pack_prompt(info: dict, dna: Optional[dict], transcript: Optional[str],
                       thumbnail_observation: Optional[str] = None) -> str:
    dna_payload = "Not available — rely on the metadata, transcript, and attached thumbnail."
    if dna:
        dna_payload = json.dumps(
            {"summary": dna.get("summary"), **(dna.get("structured_metadata") or {})},
            ensure_ascii=False,
        )[:6000]
    excerpt = (transcript or "")[:TRANSCRIPT_PROMPT_CHAR_CAP] or "(transcript unavailable)"
    return MODELED_PACK_PROMPT.format(
        ref_title=info.get("title") or "Unknown",
        ref_channel=info.get("channel") or "Unknown",
        ref_views=info.get("views") or 0,
        ref_duration=info.get("duration_seconds") or 0,
        ref_description=(info.get("description") or "")[:500],
        thumbnail_observation=thumbnail_observation
        or "Not available — infer the visual style from the metadata and transcript.",
        dna_json=dna_payload,
        transcript_excerpt=excerpt,
    )


_THUMBNAIL_OBSERVATION_PROMPT = (
    "This is a YouTube thumbnail. Describe its visual style so an artist could "
    "replicate it without seeing it. START with one line — `MEDIUM: <the exact "
    "rendering medium>` — naming the single best fit precisely: photorealistic "
    "live-action, 3D CG / Pixar-style animation, 2D / flat illustration, anime, "
    "stop-motion, mixed-media, etc. Do NOT default to an animated or illustrated "
    "medium: if the thumbnail is a real photo or live-action footage, say "
    "photorealistic live-action. Then describe color palette, character/subject "
    "design (age, species, proportions), composition, text treatment if any, and "
    "overall mood. 60-120 words, no preamble."
)


async def _describe_thumbnail_style(creds: dict, thumbnail_url: Optional[str]) -> Optional[str]:
    """Vision pass over the reference thumbnail — the only visual ground truth
    we have (transcripts are bot-blocked, frames unavailable). Goes through
    the provider-chained vision helper, NOT the Claude gateway directly: the
    gateway silently drops image blocks when it drifts, and a blind pack
    invents a wrong visual style for every downstream image."""
    if not thumbnail_url:
        return None
    from shared.clients.vision_client import vision_call
    last_err: Optional[Exception] = None
    # The style classification is the whole basis for "generate any style faithfully",
    # so don't let one transient blip drop it to a text guess — retry before giving up.
    for attempt in range(3):
        try:
            obs = await vision_call(
                _THUMBNAIL_OBSERVATION_PROMPT, [thumbnail_url],
                kie_key=creds["key"] if creds["provider"] == "kie" else None,
                anthropic_key=creds["key"] if creds["provider"] == "anthropic" else None,
                tier="fast", max_tokens=400,
            )
            if obs and obs.strip():
                return obs.strip()
            last_err = ValueError("empty observation")
        except Exception as e:
            last_err = e
        await asyncio.sleep(2 * (attempt + 1))
    logger.warning("[model_video] thumbnail vision pass failed after 3 tries (pack will be text-only): %s", str(last_err)[:200])
    return None


_REQUIRED_PACK_KEYS = (
    "selected_title", "title_options", "angle_thesis", "research_brief",
    "script_guidance", "visual_style_brief", "thumbnail_prompt", "scene_concepts",
)


async def _generate_modeled_pack(creds: dict, info: dict, dna: Optional[dict],
                                 transcript: Optional[str], blockers: Optional[list] = None) -> dict:
    # Vision and generation are split on purpose: the vision helper proves the
    # image was ingested (style fidelity), and the pack generation stays a pure
    # text call — immune to the gateway's image-block drift.
    observation = await _describe_thumbnail_style(creds, info.get("thumbnail_url"))
    # The thumbnail vision pass is the ONLY visual ground truth — it must run so the
    # pipeline locks to the reference's TRUE medium (photoreal, anime, 2D, 3D…), not
    # a text guess that skews animated. If it couldn't classify the style, NEVER fail
    # silently: surface a blocker so the creator can re-model or set the style.
    if blockers is not None and not observation:
        if info.get("thumbnail_url"):
            blockers.append(
                "Couldn't read the reference's visual style from its thumbnail — the style "
                "was inferred from text and may not match (especially for realistic / "
                "live-action sources). Re-run modeling, or set the image style manually "
                "before generating."
            )
        else:
            blockers.append(
                "No reference thumbnail was available, so the visual style was inferred "
                "from text only — verify the style before generating."
            )
    prompt = _build_pack_prompt(info, dna, transcript, thumbnail_observation=observation)
    last_err: Optional[Exception] = None
    for _attempt in range(3):
        try:
            text = await _call_claude(prompt, creds, tier="smart")
            if not text:
                raise ValueError("Claude returned an empty modeled pack")
            pack = json.loads(text)
            missing = [k for k in _REQUIRED_PACK_KEYS if not pack.get(k)]
            if missing:
                raise ValueError(f"Modeled pack missing keys: {missing}")
            if not isinstance(pack["scene_concepts"], list) or len(pack["scene_concepts"]) < 4:
                raise ValueError("Modeled pack has too few scene concepts")
            return pack
        except (json.JSONDecodeError, ValueError, RuntimeError) as e:
            last_err = e
    raise last_err


# --- Persistence ---

async def _persist_pack(tenant_id, video_id: str, reference_url: str, youtube_id: str,
                        info: dict, dna: Optional[dict], pack: dict, blockers: list[str]) -> None:
    title = str(pack["selected_title"]).strip()[:300]
    # "Super similar" includes length: match the reference's duration when we
    # have it (yt-dlp path); fall back to 10 min (oEmbed path has no duration).
    # Required: script generation refuses to run without a video length.
    duration = info.get("duration_seconds") or 0
    video_length_minutes = min(30, max(3, round(duration / 60))) if duration else 10
    research_payload = {
        "type": "modeled_idea",
        "reference": {
            "url": reference_url,
            "youtube_id": youtube_id,
            "title": info.get("title"),
            "channel": info.get("channel"),
            "views": info.get("views"),
            "duration_seconds": info.get("duration_seconds"),
            "thumbnail_url": info.get("thumbnail_url"),
            "published_at": info.get("published_at"),
        },
        "research_brief": pack.get("research_brief"),
        "script_guidance": pack.get("script_guidance"),
        "visual_style_brief": pack.get("visual_style_brief"),
        "thumbnail_prompt": pack.get("thumbnail_prompt"),
        "negative_prompts": pack.get("negative_prompts") or [],
        "title_options": pack.get("title_options") or [],
        "scene_concepts": pack.get("scene_concepts") or [],
        "dna_summary": (dna or {}).get("summary"),
        "blockers": blockers,
    }
    # original_dna is never touched by pipeline stages (research overwrites
    # research_payload), so it keeps the full modeled pack permanently.
    original_dna = {
        "summary": (dna or {}).get("summary") or "DNA analysis unavailable — modeled from metadata only.",
        **((dna or {}).get("structured_metadata") or {}),
        "modeled_pack": research_payload,
    }

    # Steering text for downstream stages. The pipeline already consumes these
    # channels: writer_guidance (script brief), image_style_override (image
    # prompt engine), thumbnail_style_override (thumbnail engine, APPEND mode),
    # video_motion_system_prompt (clip-prompt bot via per-video override).
    visual_brief = str(pack.get("visual_style_brief") or "")
    negatives = pack.get("negative_prompts") or []
    avoid_line = ("\nAvoid: " + "; ".join(str(n) for n in negatives)) if negatives else ""
    image_dna = (str(pack.get("image_dna") or "") or visual_brief) + avoid_line
    thumbnail_dna = str(pack.get("thumbnail_dna") or "") or visual_brief
    motion_dna = str(pack.get("motion_dna") or "") or visual_brief
    motion_override = (
        "Modeled motion DNA from a reference video the creator wants to emulate. "
        "Apply this shot language to every video clip prompt you write:\n\n" + motion_dna
    ) if motion_dna.strip() else None
    script_dna = str(pack.get("script_dna") or "")
    script_override = (
        "You are writing a video that replicates the style of a reference video the "
        "creator dropped in. Follow these style instructions exactly — they override "
        "any other voice or genre conventions:\n\n" + script_dna
    ) if script_dna.strip() else None

    await execute(
        """UPDATE videos SET
           video_title = $1, headline = $1, thesis = $2, idea_reasoning = $3,
           writer_guidance = $4, title_candidates = $5, thumbnail_prompt = $6,
           source_views = $7, source_channel = $8,
           original_dna = $9, research_payload = $10,
           image_style_override = $11, thumbnail_style_override = $12,
           video_motion_system_prompt = $13,
           video_length_minutes = COALESCE(video_length_minutes, $14),
           script_system_prompt = $15,
           script = NULL, script_validation = NULL, status = 'ready_for_scripting',
           updated_at = now()
           WHERE id = $16 AND tenant_id = $17""",
        title,
        str(pack.get("angle_thesis") or ""),
        f"Modeled from reference: {info.get('title') or reference_url}",
        str(pack.get("script_guidance") or ""),
        json.dumps(pack.get("title_options") or []),
        str(pack.get("thumbnail_prompt") or ""),
        info.get("views"),
        info.get("channel"),
        json.dumps(original_dna),
        json.dumps(research_payload),
        image_dna.strip() or None,
        thumbnail_dna.strip() or None,
        motion_override,
        video_length_minutes,
        script_override,
        video_id, tenant_id,
    )

    # Re-modeling supersedes prior generated artifacts: stale scene rows from an
    # earlier direction would otherwise feed voice/images with the wrong content.
    await execute(
        "DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )

    # Replace any prior modeled prompt rows (retry path), then insert the pack.
    await execute(
        "DELETE FROM assets WHERE video_id = $1 AND tenant_id = $2 AND generation_method = 'modeled'",
        video_id, tenant_id,
    )
    for i, scene in enumerate(pack["scene_concepts"], start=1):
        await execute(
            """INSERT INTO assets (tenant_id, video_id, video_title, scene, image_index,
                                   sentence_text, image_prompt, video_prompt,
                                   status, content_type, generation_method)
               VALUES ($1, $2, $3, $4, 1, $5, $6, $7, 'pending', 'image', 'modeled')""",
            tenant_id, video_id, title, i,
            str(scene.get("concept") or ""),
            str(scene.get("image_prompt") or ""),
            str(scene.get("video_prompt") or ""),
        )

    # Attribution: link the reference in competitor_videos (also feeds intelligence).
    await execute(
        """INSERT INTO competitor_videos
               (tenant_id, video_id, title, url, channel, channel_url, views, likes,
                thumbnail_url, transcript, duration_seconds, description,
                modeled_by_us, modeled_at, our_video_id, scrape_date)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, true, now(), $13, CURRENT_DATE)
           ON CONFLICT (tenant_id, video_id) DO UPDATE SET
               modeled_by_us = true, modeled_at = now(), our_video_id = $13,
               transcript = COALESCE(EXCLUDED.transcript, competitor_videos.transcript),
               thumbnail_url = COALESCE(EXCLUDED.thumbnail_url, competitor_videos.thumbnail_url),
               updated_at = now()""",
        tenant_id, youtube_id,
        info.get("title"), reference_url, info.get("channel"), info.get("channel_url"),
        info.get("views"), info.get("likes"),
        info.get("thumbnail_url"), info.get("transcript"),
        info.get("duration_seconds"), (info.get("description") or "")[:2000],
        video_id,
    )


def _brief_markdown(pack: dict, info: dict, reference_url: str, blockers: list[str]) -> str:
    lines = [
        f"# Modeled Brief — {pack.get('selected_title')}",
        "",
        f"**Reference:** [{info.get('title') or reference_url}]({reference_url}) "
        f"by {info.get('channel') or 'unknown'} ({info.get('views') or 0:,} views)",
        "",
        "## Angle / Thesis", str(pack.get("angle_thesis") or ""),
        "", "## Title Options",
        *[f"- {t}" for t in (pack.get("title_options") or [])],
        "", "## Research Brief", str(pack.get("research_brief") or ""),
        "", "## Script Guidance", str(pack.get("script_guidance") or ""),
        "", "## Script Style DNA", str(pack.get("script_dna") or "(see script guidance)"),
        "", "## Visual Style Brief", str(pack.get("visual_style_brief") or ""),
        "", "## Image Creation DNA", str(pack.get("image_dna") or "(see visual style brief)"),
        "", "## Video Motion DNA", str(pack.get("motion_dna") or "(see visual style brief)"),
        "", "## Thumbnail DNA", str(pack.get("thumbnail_dna") or "(see visual style brief)"),
        "", "## Thumbnail Prompt", str(pack.get("thumbnail_prompt") or ""),
        "", "## Negative Prompts / Constraints",
        *[f"- {n}" for n in (pack.get("negative_prompts") or [])],
        "", "## Scene Prompt Pack",
    ]
    for i, scene in enumerate(pack.get("scene_concepts") or [], start=1):
        lines += [
            f"### Scene {i}: {scene.get('concept')}",
            f"- **Image prompt:** {scene.get('image_prompt')}",
            f"- **Video prompt:** {scene.get('video_prompt')}",
            "",
        ]
    if blockers:
        lines += ["## Notes", *[f"- {b}" for b in blockers]]
    return "\n".join(lines)


async def _maybe_upload_brief_to_drive(tenant_id, title: str, markdown: str) -> Optional[str]:
    """Best-effort: upload the brief to the tenant's connected Drive folder.

    Returns the Drive file URL, or None when Drive isn't connected or the
    upload fails. Never raises — DB is the source of truth for the pipeline.
    """
    try:
        row = await fetch_one(
            "SELECT google_drive_refresh_token, google_drive_folder_id "
            "FROM channel_profiles WHERE tenant_id = $1",
            tenant_id,
        )
        if not row or not row.get("google_drive_refresh_token"):
            return None
        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
        if not client_id or not client_secret:
            return None

        async with httpx.AsyncClient(timeout=30.0) as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": row["google_drive_refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            if token_resp.status_code != 200:
                return None
            access_token = token_resp.json()["access_token"]

            metadata = {"name": f"Modeled Brief — {title}.md", "mimeType": "text/markdown"}
            if row.get("google_drive_folder_id"):
                metadata["parents"] = [row["google_drive_folder_id"]]
            boundary = f"se-brief-{_uuid.uuid4().hex}"
            body = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{json.dumps(metadata)}\r\n"
                f"--{boundary}\r\nContent-Type: text/markdown\r\n\r\n"
                f"{markdown}\r\n--{boundary}--"
            ).encode("utf-8")
            upload_resp = await client.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                },
                content=body,
            )
            if upload_resp.status_code not in (200, 201):
                return None
            file_id = upload_resp.json().get("id")
            return f"https://drive.google.com/file/d/{file_id}/view" if file_id else None
    except Exception:
        return None


async def _oembed_fallback(youtube_id: str) -> Optional[dict]:
    """Minimal reference metadata when yt-dlp is blocked (YouTube bot checks,
    datacenter-IP rate limits). oEmbed needs no auth and isn't bot-gated, so we
    can still model from title + channel + thumbnail."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": f"https://www.youtube.com/watch?v={youtube_id}", "format": "json"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
        if not data.get("title"):
            return None
        return {
            "video_id": youtube_id,
            "title": data.get("title"),
            "channel": data.get("author_name"),
            "channel_url": data.get("author_url"),
            "thumbnail_url": data.get("thumbnail_url") or f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg",
            "transcript": None,
            "description": "",
        }
    except Exception:
        return None


# --- The background task ---

async def _run_modeling(tenant_id, video_id: str, youtube_id: str, reference_url: str) -> None:
    from routes.pipeline import _clear_task_status, _set_task_status

    def _set(status: str, message: Optional[str] = None, error: Optional[str] = None):
        _set_task_status(video_id, status, message, error,
                         tenant_id=tenant_id, task_type=TASK_TYPE)

    blockers: list[str] = []
    try:
        # 1. Extract
        _set("running", "Fetching the reference video…")
        from routes.niche import _extract_video_info
        info = await asyncio.to_thread(_extract_video_info, youtube_id)
        if not info or not info.get("title"):
            info = await _oembed_fallback(youtube_id)
            if info:
                blockers.append(
                    "YouTube limited full video access from our servers — modeled from the title, channel, and thumbnail only."
                )
        if not info or not info.get("title"):
            _set("failed", error=user_facing(
                "We couldn't read that video. Check that the link is a public YouTube video and try again."
            ))
            return
        transcript = info.get("transcript")
        if transcript is None and not blockers:
            blockers.append("Transcript wasn't available — modeled from the title, thumbnail, and metadata instead.")

        creds = await _resolve_claude_creds(tenant_id)
        if not creds:
            _set("failed", error=user_facing(
                "Add your Kie.ai API key in Settings → Keys, then retry."
            ))
            return

        # 2. Analyze (style DNA — degrades gracefully)
        _set("running", "Analyzing what makes it work…")
        dna = None
        try:
            dna = await _distill_dna(
                creds, info,
                transcript or (info.get("description") or info.get("title") or ""),
            )
        except Exception as e:
            logger.warning("[model_video] DNA distillation failed for %s: %s", youtube_id, str(e)[:300])
            blockers.append("Deep style analysis was unavailable — modeled from raw metadata.")

        # 3. Generate the sibling video + prompt pack (reference-only — the
        #    channel profile is deliberately NOT injected: the feature replicates
        #    the dropped-in video, it doesn't adapt it to the creator's niche)
        _set("running", "Creating your modeled idea…")
        pack = await _generate_modeled_pack(creds, info, dna, transcript, blockers)

        # 4. Persist everything before any generation credits are spent
        _set("running", "Writing your prompt pack…")
        await _persist_pack(tenant_id, video_id, reference_url, youtube_id, info, dna, pack, blockers)

        title = str(pack["selected_title"]).strip()[:300]
        drive_url = await _maybe_upload_brief_to_drive(
            tenant_id, title, _brief_markdown(pack, info, reference_url, blockers)
        )
        if drive_url:
            await execute(
                """UPDATE videos SET research_payload = jsonb_set(research_payload, '{drive_brief_url}', to_jsonb($1::text))
                   WHERE id = $2 AND tenant_id = $3""",
                drive_url, video_id, tenant_id,
            )

        message = f"Modeled idea ready: “{title}” — review it in your pipeline."
        if blockers:
            message += " Note: " + " ".join(blockers)
        _set("completed", message)
    except Exception as e:
        _set("failed", error=user_facing(humanize_error(e, context="We couldn't finish modeling that video")))
    finally:
        await asyncio.sleep(45)
        _clear_task_status(video_id, tenant_id)


# --- Endpoints ---

@router.post("", response_model=ModelVideoResponse)
async def model_video(
    request: ModelVideoRequest,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    """Create a new modeled video idea from a reference YouTube URL.

    Creates the video row immediately (so the UI has an id to poll), then
    extracts/analyzes/generates in the background.
    """
    url = (request.video_url or "").strip()
    youtube_id = _parse_youtube_id(url)
    if not youtube_id:
        raise HTTPException(
            status_code=400,
            detail="That doesn't look like a YouTube video link. Paste a youtube.com or youtu.be URL.",
        )

    from routes.billing import check_plan_limits, increment_usage
    await check_plan_limits(tenant_id, "video")

    from routes.pipeline import _set_task_status
    from routes.projects import _get_or_create_project
    project = await _get_or_create_project(tenant_id)

    row = await fetch_one(
        """INSERT INTO videos (tenant_id, project_id, video_title, status, headline, source, reference_url)
           VALUES ($1, $2, $3, 'idea_logged', $3, 'modeled', $4)
           RETURNING id""",
        tenant_id, str(project["id"]), "Modeling a reference video…", url,
    )
    video_id = str(row["id"])
    await increment_usage(tenant_id, "videos_created")

    _set_task_status(video_id, "running", "Queued for modeling…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)
    background_tasks.add_task(_run_modeling, tenant_id, video_id, youtube_id, url)

    return ModelVideoResponse(video_id=video_id, status="running",
                              message="Modeling started — this takes a minute or two.")


@router.post("/{video_id}/retry", response_model=ModelVideoResponse)
async def retry_model_video(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    """Re-run modeling for a video created via Model A Video (e.g. after a failure)."""
    video = await fetch_one(
        "SELECT id, reference_url, source FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.get("source") != "modeled" or not video.get("reference_url"):
        raise HTTPException(status_code=400, detail="This video wasn't created from a reference link.")

    youtube_id = _parse_youtube_id(video["reference_url"])
    if not youtube_id:
        raise HTTPException(status_code=400, detail="The saved reference link is invalid.")

    from routes.pipeline import _get_task_status, _set_task_status
    task = _get_task_status(video_id, tenant_id)
    if task and task.get("status") == "running":
        raise HTTPException(status_code=409, detail="Modeling is already running for this video.")

    _set_task_status(video_id, "running", "Retrying modeling…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)
    background_tasks.add_task(_run_modeling, tenant_id, video_id, youtube_id, video["reference_url"])

    return ModelVideoResponse(video_id=video_id, status="running", message="Modeling restarted.")
