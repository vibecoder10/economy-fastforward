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
    "anthropic": {"smart": "claude-sonnet-4-6", "fast": "claude-haiku-4-5-20251001"},
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
    """Pick the provider for Claude calls: direct Anthropic FIRST (reliable), Kie.ai
    only as a fallback when the tenant has no Anthropic key. The Kie Claude gateway
    500s and hangs (it stalled a modeling run in prod) and silently drops image
    blocks, so Claude should never depend on it when a real Anthropic key exists.
    Images/video stay on Kie. This matches get_text_client_for_tenant (Anthropic-first)."""
    from vault import get_secret
    anthropic_key = await get_secret("anthropic_api_key", str(tenant_id))
    if anthropic_key:
        return {"provider": "anthropic", "key": anthropic_key}
    kie_key = await get_secret("kie_ai_api_key", str(tenant_id))
    if kie_key:
        return {"provider": "kie", "key": kie_key}
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
- Same visual style — the SCENE OBSERVATION below is the reference's ACTUAL in-video
  look (described from real frames); replicate exactly that art style, palette, and
  character design across all video images. The thumbnail is a separate, punched-up
  click asset — use the THUMBNAIL OBSERVATION ONLY for the thumbnail, never for scenes
- NEW but adjacent subject matter: a sibling story/topic the same channel would
  publish next. Never copy the reference's exact story, characters, or script lines.

REFERENCE VIDEO:
- Title: {ref_title}
- Channel: {ref_channel}
- Views: {ref_views}
- Duration: {ref_duration}s
- Description (excerpt): {ref_description}

SCENE OBSERVATION (real frames from the MIDDLE of the reference video — its TRUE in-video visual style; use for visual_style_brief, image_dna, and every scene image_prompt):
{scene_observation}

THUMBNAIL OBSERVATION (the reference THUMBNAIL only — a punched-up click asset, NOT the scene style; use ONLY for thumbnail_prompt and thumbnail_dna):
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
  "visual_style_brief": "markdown: the reference's IN-VIDEO visual style from the SCENE OBSERVATION (art style, palette, character design, composition), to be replicated across all video images (100-200 words)",
  "thumbnail_prompt": "a self-contained image prompt for OUR video's OWN thumbnail. MODEL the reference, do NOT copy it: depict the single most click-worthy moment THIS video's own title + scene_concepts promise (its surprising reveal/payoff), staged as our own fresh scene — never reproduce the reference's specific objects, scene or composition. Apply the reference's CLICK FORMULA and visual STYLE from the THUMBNAIL OBSERVATION (medium, palette, lighting, text treatment). Obey: ONE focal point, <=3 elements, exaggerated facial emotion, extreme contrast, bright. MODEL THE TEXT: render a big, bold headline that captures OUR title's hook (not a verbatim copy), spanning across the screen in the SAME text treatment and layout as the reference (its scale, tiers, color per tier, weight/case and heavy outline) — text is a primary element, not a small label. 60-90 words",
  "image_dna": "style directives for EVERY still image, matching the SCENE OBSERVATION (the real in-video look, NOT the thumbnail): art style/medium, palette, character design, lighting, recurring motifs (60-100 words)",
  "motion_dna": "directives for EVERY video clip prompt: camera movement, pacing, subject motion matching the reference's format (40-80 words)",
  "thumbnail_dna": "reusable directives for regenerating OUR thumbnail by MODELING the reference (not copying): the medium, color palette, lighting and text treatment to match, plus the abstracted CLICK FORMULA to re-apply to our own scene. Style + pattern only, never the reference's specific objects (40-80 words)",
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
                       thumbnail_observation: Optional[str] = None,
                       scene_observation: Optional[str] = None) -> str:
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
        scene_observation=scene_observation
        or "Not available — infer the in-video style from the thumbnail, metadata, and transcript.",
        thumbnail_observation=thumbnail_observation
        or "Not available — infer the thumbnail style from the metadata and transcript.",
        dna_json=dna_payload,
        transcript_excerpt=excerpt,
    )


_THUMBNAIL_BLUEPRINT_PROMPT = (
    "Analyse this successful YouTube thumbnail and break it into a DETAILED JSON blueprint so we "
    "can MODEL its winning formula on a different video (we will never copy its subjects, only its "
    "look + pattern). Return ONLY valid JSON (no preamble, no code fences) with EXACTLY these keys: "
    "format, aspect_ratio, style{medium, look, lighting, mood}, "
    "scene{setting, main_action, focal_point, secondary_focal_point}, "
    "characters (array of {role, description, emotion, pose}), "
    "objects (array of {object, description, position}), "
    "composition{camera, layout, depth_of_field, thumbnail_rules}, "
    "text{primary_text{content, placement, style}, secondary_text{content, placement, style}, "
    "small_text{content, placement, style}}, "
    "color_palette (object of role:color), "
    "prompt (a full natural-language image prompt that would recreate THIS thumbnail), "
    "negative_prompt. Capture the exact text tiers, colors, outlines and placement precisely. "
    "For `medium`, name it exactly (photorealistic live-action, 3D CG / Pixar-style animation, 2D "
    "illustration, anime, etc.); never default to animated if it is a real photo."
)


def _strip_code_fences(t: Optional[str]) -> str:
    """Strip ```json ... ``` fences an LLM may wrap around JSON output."""
    t = (t or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    return t


async def _describe_thumbnail_style(creds: dict, thumbnail_url: Optional[str]) -> Optional[str]:
    """Vision pass over the reference thumbnail → a structured JSON BLUEPRINT (style,
    scene, characters, objects, composition, exact text tiers, palette). This is the
    ground truth we MODEL from. Goes through the provider-chained vision helper, NOT the
    Claude gateway directly: the gateway silently drops image blocks when it drifts."""
    if not thumbnail_url:
        return None
    from shared.clients.vision_client import vision_call
    last_err: Optional[Exception] = None
    # The blueprint is the whole basis for modeling, so don't let one transient blip
    # drop it — retry before giving up.
    for attempt in range(3):
        try:
            obs = await vision_call(
                _THUMBNAIL_BLUEPRINT_PROMPT, [thumbnail_url],
                kie_key=creds["key"] if creds["provider"] == "kie" else None,
                anthropic_key=creds["key"] if creds["provider"] == "anthropic" else None,
                tier="fast", max_tokens=1600,
            )
            if obs and obs.strip():
                return _strip_code_fences(obs)
            last_err = ValueError("empty observation")
        except Exception as e:
            last_err = e
        await asyncio.sleep(2 * (attempt + 1))
    logger.warning("[model_video] thumbnail vision pass failed after 3 tries (pack will be text-only): %s", str(last_err)[:200])
    return None


async def _fetch_channel_brand(tenant_id) -> str:
    """The creator's OWN channel name — used as the thumbnail's brand text line so we
    model the reference's text FORMAT with OUR brand, not the competitor's words."""
    try:
        row = await fetch_one(
            "SELECT channel_name FROM channel_profiles WHERE tenant_id = $1", tenant_id)
        return ((row or {}).get("channel_name") or "").strip()
    except Exception:
        return ""


def _thumbnail_transform_prompt(blueprint_json: str, title: str, brand: str,
                                cast_names: str, has_cast: bool) -> str:
    """Claude prompt: turn the reference blueprint into OUR modeled thumbnail JSON
    (our story + our brand, the reference's winning formula), with hard content-safety
    rules so the image generator doesn't reject distressed-child imagery."""
    clean_title = (title or "").split("|")[0].strip()
    brand_line = (f'primary_text.content = OUR channel brand "{brand}"'
                  if brand else "primary_text.content = OUR channel brand")
    if has_cast and cast_names:
        cast_rule = (
            f"- characters: our recurring cast is [{cast_names}] — describe each one's look, light "
            "comic emotion and pose for THIS scene (their exact identities come from a provided "
            "cast-sheet image, so keep names/descriptions consistent).\n")
    elif has_cast:
        cast_rule = "- characters: describe OUR story's characters with light comic emotion and clear poses.\n"
    else:
        cast_rule = ("- characters: use an EMPTY array — this is a FACELESS video; depict an event or "
                     "bold iconography (a single charged object, charts, arrows) instead of people.\n")
    return (
        "You are a world-class YouTube thumbnail director. Below is a JSON blueprint of a PROVEN "
        "competitor thumbnail that performs well in this niche:\n\n" + blueprint_json + "\n\n"
        f'MODEL it (do NOT copy) for OUR brand-new video titled "{clean_title}". Produce a NEW JSON '
        "with the SAME schema that KEEPS the proven style, lighting, mood, composition, text "
        "treatment/layout, color palette, badge and overall format — but REPLACES the scene, "
        "main_action, focal_point, characters, objects and all story-specific TEXT CONTENT so it "
        "tells OUR title's story. Match the reference's RICHNESS — it is detailed and premium, so "
        "yours must be too. Rules:\n"
        f"- {brand_line} (keep the reference's big bold style, color and placement), NOT the "
        "competitor's brand words.\n"
        "- secondary_text.content = a short, punchy FIRST-PERSON exclamation hook from OUR story, "
        "MIRRORING the reference secondary text's voice and grammar (e.g. if the reference says 'MY "
        "LIMITED CARD FELL!', ours is 'MY RARE CAR BROKE!') — <=5 words, the surprising payoff, keep "
        "its color and outline.\n"
        "- ALWAYS include small_text (the reference's '... for beginners'-style subtitle) and the "
        "level/label badge, in the reference's style (generic level text, e.g. 'A1-A2 LEVEL'). All "
        "THREE text tiers must appear.\n"
        + cast_rule +
        "- objects: include the hero object AND a supporting prop that sells the stakes with a "
        "FICTIONAL label (like the reference's badge/box) — no real brands or trademarks. Add "
        "premium detailing (gold accents, sparkle, a clear already-happened accident state) where it "
        "fits.\n"
        "- Obey thumbnail rules: ONE clear focal point, <=3 main elements, extreme contrast, "
        "instantly readable at 120px.\n"
        "- CONTENT SAFETY (critical — image generators reject distressed-child imagery): emotions are "
        "ONLY light comic surprise — 'jaw-dropped uh-oh', 'wide-eyed oops', 'playful panic', "
        "'sheepish grin'. The accident has ALREADY happened on its own; NO character causes harm, "
        "hits, or holds any tool/weapon (a guilty character just stands sheepishly). BANNED words you "
        "must NOT use anywhere: horror, terror, devastation, devastated, crying, tears, teary, "
        "glistening/watery eyes, sobbing, screaming, fear, scared, pain, hurt, injury, blood, hammer, "
        "smashing, hitting, weapon. Keep it wholesome, funny and light. Put 'crying, tears, sad, "
        "distress, fear, injury, violence' in the negative_prompt.\n"
        "- NO competitor logos/brand words, no real trademarks/logos/real-person likenesses.\n"
        "- The 'prompt' must be ONE self-contained, DETAILED natural-language image-generation prompt "
        "that fully describes the final thumbnail: scene, every character (look + comic emotion + "
        "pose), the hero object and supporting prop, composition, the EXACT text to render for ALL "
        "THREE tiers with each tier's color/outline/placement, the badge, and the color palette.\n"
        "Design the thumbnail through the full schema above in your reasoning, then return ONLY valid "
        "JSON with EXACTLY two keys and nothing else: {\"prompt\": \"<the full detailed image "
        "prompt>\", \"negative_prompt\": \"<thorough negatives>\"}. No other keys, no preamble, no "
        "code fences. Keep it valid JSON — escape any quotes inside the strings."
    )


async def _model_thumbnail_prompt(creds: dict, blueprint_json: str, title: str, brand: str,
                                  cast_names: str, has_cast: bool) -> Optional[str]:
    """Transform the reference blueprint into OUR modeled thumbnail and return a single
    generation prompt (the modeled `prompt` with the negative baked in). Returns None on
    failure so callers can fall back to the text-assembly builder."""
    if not (blueprint_json or "").strip():
        return None
    try:
        raw = await _call_claude(
            _thumbnail_transform_prompt(blueprint_json, title, brand, cast_names, has_cast),
            creds, tier="smart", max_tokens=3500)
        modeled = json.loads(_strip_code_fences(raw))
        prompt = (modeled.get("prompt") or "").strip()
        neg = (modeled.get("negative_prompt") or "").strip()
        if not prompt:
            return None
        return prompt + (f"\n\nAvoid (negative prompt): {neg}" if neg else "")
    except Exception as e:
        logger.warning("[model_video] thumbnail transform failed: %s", str(e)[:200])
        return None


_SCENE_OBSERVATION_PROMPT = (
    "These are real frames sampled from the MIDDLE of a video — its actual on-screen "
    "content. Describe the video's true SCENE visual style so an artist could replicate "
    "it. IGNORE any subtitle/caption text burned into the frames. START with one line — "
    "`MEDIUM: <the exact rendering medium>` — naming the single best fit precisely: "
    "photorealistic live-action, 3D CG / Pixar-style animation, 2D / flat illustration, "
    "anime, stop-motion, mixed-media, etc. Do NOT default to an animated or illustrated "
    "medium: if the frames are real footage, say photorealistic live-action. Then describe "
    "color palette, character/subject design (age, species, proportions), lighting, "
    "composition, and recurring motifs. 60-120 words, no preamble."
)


def _scene_frame_urls(youtube_id: str) -> list:
    """Real in-video frames YouTube auto-extracts at ~25/50/75% of the runtime.
    Served from the same CDN as thumbnails, so they sidestep the yt-dlp bot-check —
    THIS, not the thumbnail, is the reference's true scene look."""
    return [f"https://i.ytimg.com/vi/{youtube_id}/hq{n}.jpg" for n in (1, 2, 3)]


async def _describe_scene_style(creds: dict, frame_urls: list) -> Optional[str]:
    """Vision pass over real mid-video frames — the SCENE-style ground truth for
    every generated still (image_dna). The thumbnail is a punched-up click asset and
    a bad proxy for the in-video look, so scene style must come from actual frames.
    Retried so a transient blip doesn't drop us to a text/thumbnail guess."""
    if not frame_urls:
        return None
    from shared.clients.vision_client import vision_call
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            obs = await vision_call(
                _SCENE_OBSERVATION_PROMPT, frame_urls,
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
    logger.warning("[model_video] scene-frame vision pass failed after 3 tries: %s", str(last_err)[:200])
    return None


_REQUIRED_PACK_KEYS = (
    "selected_title", "title_options", "angle_thesis", "research_brief",
    "script_guidance", "visual_style_brief", "thumbnail_prompt", "scene_concepts",
)


async def _generate_modeled_pack(creds: dict, info: dict, dna: Optional[dict],
                                 transcript: Optional[str], blockers: Optional[list] = None,
                                 youtube_id: Optional[str] = None) -> dict:
    # Vision and generation are split on purpose: the vision helper proves the image
    # was ingested (style fidelity), and pack generation stays a pure text call —
    # immune to the gateway's image-block drift.
    #
    # TWO separate ground truths, on purpose:
    #   • SCENE style     ← real mid-video frames → drives image_dna / every still.
    #   • THUMBNAIL style ← the thumbnail         → drives thumbnail_dna ONLY.
    # A YouTube thumbnail is a punched-up click asset (split-screens, big text,
    # exaggerated faces) — a bad proxy for the actual scenes — so the in-video look
    # MUST come from frames, not the thumbnail.
    thumb_obs = await _describe_thumbnail_style(creds, info.get("thumbnail_url"))
    scene_obs = await _describe_scene_style(creds, _scene_frame_urls(youtube_id)) if youtube_id else None
    # Scene style is the basis for "reproduce ANY style faithfully" — if it couldn't be
    # read from real frames, NEVER fail silently: flag it (falling back to the thumbnail
    # at best) so the creator can re-model or set the style.
    if blockers is not None and not scene_obs:
        if thumb_obs:
            blockers.append(
                "Couldn't read the reference's in-video scene style from real frames — fell "
                "back to its thumbnail, which is a punched-up click asset and may not match "
                "the actual scenes. Re-run modeling, or set the image style manually."
            )
        else:
            blockers.append(
                "Couldn't read the reference's visual style from frames or thumbnail — the "
                "style was inferred from text only. Set the image style before generating."
            )
    prompt = _build_pack_prompt(
        info, dna, transcript,
        scene_observation=scene_obs or thumb_obs,
        thumbnail_observation=thumb_obs,
    )
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
            # Carry the RAW thumbnail observation (ground truth from the real
            # reference thumbnail) so persistence can use it as the thumbnail
            # style recipe instead of Claude's lossy thumbnail_dna rewrite.
            pack["_thumb_obs"] = thumb_obs
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
        "thumbnail_observation": str(pack.get("_thumb_obs") or "").strip() or None,
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
    # Raw vision observation of the real reference thumbnail = ground truth. Prefer
    # it over Claude's thumbnail_dna (which can drift to the wrong story) as the
    # style recipe the thumbnail generator reads from thumbnail_style_override.
    thumb_obs = str(pack.get("_thumb_obs") or "").strip()
    thumbnail_style = thumb_obs or thumbnail_dna.strip()
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
           -- Respect an explicit creator look: only apply the reference's detected
           -- style when they didn't pick one (else their choice wins).
           image_style_override = COALESCE(NULLIF(image_style_override, ''), $11), thumbnail_style_override = $12,
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
        None,  # thumbnail_prompt: generator computes the JSON-modeled prompt from the blueprint
        info.get("views"),
        info.get("channel"),
        json.dumps(original_dna),
        json.dumps(research_payload),
        image_dna.strip() or None,
        thumbnail_style or None,
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
               views = CASE WHEN COALESCE(EXCLUDED.views, 0) > 0
                           THEN EXCLUDED.views ELSE competitor_videos.views END,
               duration_seconds = COALESCE(NULLIF(EXCLUDED.duration_seconds, 0),
                                           competitor_videos.duration_seconds),
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


# User-facing stages whose STYLE this flow copies from a reference. voice &
# sound are intentionally absent — they're always generated fresh (Ryan's call).
_MODELABLE_STAGES = {"script", "images", "thumbnail", "video"}


async def _persist_style_overrides(
    tenant_id, video_id: str, reference_url: str, youtube_id: str,
    info: dict, dna: Optional[dict], pack: dict, blockers: list[str],
    enabled_stages: Optional[list],
    lock_in_identity: bool = False,
) -> None:
    """Apply ONLY the reference's STYLE to a video the creator already defined
    (their own topic + title). Unlike _persist_pack, this never touches the
    topic/title/thesis and never inserts the reference's scene concepts — it
    just sets the per-stage style overrides for the stages the creator switched
    ON. voice & sound are never styled. enabled_stages None = full pipeline."""
    on = set(enabled_stages) if enabled_stages else set(_MODELABLE_STAGES)

    visual_brief = str(pack.get("visual_style_brief") or "")
    negatives = pack.get("negative_prompts") or []
    avoid_line = ("\nAvoid: " + "; ".join(str(n) for n in negatives)) if negatives else ""
    image_dna = ((str(pack.get("image_dna") or "") or visual_brief) + avoid_line).strip()
    thumbnail_dna = (str(pack.get("thumbnail_dna") or "") or visual_brief).strip()
    # Raw vision observation of the real reference thumbnail = ground truth; prefer
    # it over Claude's thumbnail_dna as the thumbnail style recipe (see _persist_pack).
    thumb_obs = str(pack.get("_thumb_obs") or "").strip()
    thumbnail_style = thumb_obs or thumbnail_dna
    motion_dna = (str(pack.get("motion_dna") or "") or visual_brief).strip()
    script_dna = str(pack.get("script_dna") or "").strip()

    script_override = (
        "You are writing a video that replicates the SCRIPT STYLE of a reference "
        "video the creator dropped in — but on the creator's OWN topic. Copy the "
        "reference's voice, structure, pacing and hook patterns; keep the subject "
        "matter from the creator's brief. Style instructions:\n\n" + script_dna
    ) if script_dna else None
    motion_override = (
        "Modeled motion DNA from a reference video the creator wants to emulate. "
        "Apply this shot language to every video clip prompt:\n\n" + motion_dna
    ) if motion_dna else None

    # Only the switched-on stages get an override; the rest stay NULL (fresh).
    img_val = (image_dna or None) if "images" in on else None
    thumb_val = (thumbnail_style or None) if "thumbnail" in on else None
    motion_val = motion_override if "video" in on else None
    script_val = script_override if "script" in on else None

    duration = info.get("duration_seconds") or 0
    ref_length = min(30, max(3, round(duration / 60))) if duration else None

    original_dna = {
        "summary": (dna or {}).get("summary") or "Modeled (style only) from a reference.",
        **((dna or {}).get("structured_metadata") or {}),
        "modeled_style": {
            "reference": {"url": reference_url, "youtube_id": youtube_id,
                          "title": info.get("title"), "channel": info.get("channel")},
            "scope": sorted(on),
            "script_dna": script_dna, "image_dna": image_dna,
            "thumbnail_dna": thumbnail_dna, "thumbnail_observation": thumb_obs,
            "motion_dna": motion_dna,
            "blockers": blockers,
        },
    }

    await execute(
        """UPDATE videos SET
           idea_reasoning = $1, source_views = $2, source_channel = $3,
           original_dna = $4,
           -- Respect an explicit creator look (see above): pick wins over detected.
           image_style_override = COALESCE(NULLIF(image_style_override, ''), $5), thumbnail_style_override = $6,
           video_motion_system_prompt = $7, script_system_prompt = $8,
           video_length_minutes = COALESCE(video_length_minutes, $9),
           updated_at = now()
           WHERE id = $10 AND tenant_id = $11""",
        f"Style modeled from reference: {info.get('title') or reference_url}",
        info.get("views"), info.get("channel"),
        json.dumps(original_dna),
        img_val, thumb_val, motion_val, script_val,
        ref_length, video_id, tenant_id,
    )

    if lock_in_identity and (img_val or "").strip():
        try:
            from routes.visual_styles import upsert_active_visual_style
            vrow = await fetch_one(
                "SELECT project_id, video_title FROM videos WHERE id = $1", video_id,
            )
            if vrow and vrow.get("project_id"):
                name = f"Cloned from {vrow.get('video_title') or 'video'}".strip()
                await upsert_active_visual_style(str(vrow["project_id"]), name, img_val.strip())
        except Exception as e:
            logger.warning("clone lock-in failed: %s", e)

    # Attribution (same as the full flow) — feeds the intelligence layer.
    await execute(
        """INSERT INTO competitor_videos
               (tenant_id, video_id, title, url, channel, channel_url, views, likes,
                thumbnail_url, transcript, duration_seconds, description,
                modeled_by_us, modeled_at, our_video_id, scrape_date)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, true, now(), $13, CURRENT_DATE)
           ON CONFLICT (tenant_id, video_id) DO UPDATE SET
               modeled_by_us = true, modeled_at = now(), our_video_id = $13,
               views = CASE WHEN COALESCE(EXCLUDED.views, 0) > 0
                           THEN EXCLUDED.views ELSE competitor_videos.views END,
               duration_seconds = COALESCE(NULLIF(EXCLUDED.duration_seconds, 0),
                                           competitor_videos.duration_seconds),
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


# Supadata transcript API — used ONLY when yt-dlp is bot-blocked from our servers.
# The thumbnail + in-video frames come free off YouTube's public image CDN; the
# transcript is the one piece behind the bot wall, so we fetch it here. Free tier
# (~100/mo); set SUPADATA_API_KEY to enable. Endpoint/contract:
#   GET https://api.supadata.ai/v1/transcript?url=<watch_url>   header: x-api-key
#   -> {"lang": "en", "content": [{"text","offset","duration","lang"}, ...]}
#   (auto-Whisper for uncaptioned videos; long videos may return an async job,
#    which we treat as unavailable here.)
_SUPADATA_TRANSCRIPT_URL = "https://api.supadata.ai/v1/transcript"


async def _fetch_transcript_supadata(youtube_id: str) -> Optional[str]:
    """Fetch a YouTube transcript as plain text via Supadata. Returns None when
    no key is set, the call fails, or the words aren't available (never raises)."""
    key = os.environ.get("SUPADATA_API_KEY", "").strip()
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                _SUPADATA_TRANSCRIPT_URL,
                params={"url": f"https://www.youtube.com/watch?v={youtube_id}"},
                headers={"x-api-key": key},
            )
        if resp.status_code != 200:
            logger.warning("[model_video] Supadata transcript %s: HTTP %s %s",
                           youtube_id, resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        content = data.get("content")
        if isinstance(content, list):
            text = " ".join(
                seg.get("text", "").strip()
                for seg in content
                if isinstance(seg, dict) and seg.get("text")
            ).strip()
            return text or None
        if isinstance(content, str) and content.strip():
            return content.strip()
        # e.g. an async {"jobId": ...} for very long videos — treat as unavailable.
        logger.warning("[model_video] Supadata transcript %s: no usable content (keys=%s)",
                       youtube_id, list(data)[:6])
        return None
    except Exception as e:
        logger.warning("[model_video] Supadata transcript fetch failed for %s: %s",
                       youtube_id, str(e)[:200])
        return None


# --- The background task ---

async def _run_modeling(tenant_id, video_id: str, youtube_id: str, reference_url: str,
                        pipeline_stages: Optional[list] = None,
                        preserve_topic: bool = False,
                        lock_in_identity: bool = False) -> None:
    """Extract a reference video's style and apply it.

    Default (preserve_topic=False): the standalone "Model A Video" flow — builds
    a NEW sibling-topic idea and copies the whole style.

    preserve_topic=True (the Create-form "copy a video" path): the creator
    already typed their OWN topic and flipped the stage switches; this copies
    ONLY the style of the switched-on stages onto that topic, leaving the
    title/topic alone. pipeline_stages scopes which stages get styled."""
    from routes.pipeline import _clear_task_status, _set_task_status

    def _set(status: str, message: Optional[str] = None, error: Optional[str] = None):
        _set_task_status(video_id, status, message, error,
                         tenant_id=tenant_id, task_type=TASK_TYPE)

    blockers: list[str] = []
    try:
        # 1. Extract. Prefer the official YouTube Data API (real views/duration, not
        # bot-blocked on datacenter IPs) so we never model from zeros. Fall back to
        # yt-dlp (often blocked here) then oEmbed (title/thumbnail only).
        _set("running", "Fetching the reference video…")
        info = None
        api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        if api_key:
            try:
                from youtube_data_api import fetch_single_video
                info = await fetch_single_video(youtube_id, api_key)
            except Exception as e:  # noqa: BLE001
                print(f"[model_video] YouTube Data API fetch failed for {youtube_id}: {e}")
                info = None
        if not info or not info.get("title"):
            from routes.niche import _extract_video_info
            info = await asyncio.to_thread(_extract_video_info, youtube_id)
        used_oembed = False
        if not info or not info.get("title"):
            info = await _oembed_fallback(youtube_id)
            used_oembed = bool(info)
        if not api_key and (used_oembed or not (info or {}).get("views")):
            # No API key + a blocked/zero source = no real numbers. Say so loudly
            # so the "based on real data" promise isn't silently faked.
            blockers.append(
                "No YouTube Data API key set, so real view/duration numbers weren't "
                "available for this reference — add YOUTUBE_API_KEY to ground the modeling in real data."
            )
        if not info or not info.get("title"):
            _set("failed", error=user_facing(
                "We couldn't read that video. Check that the link is a public YouTube video and try again."
            ))
            return
        # The transcript is the only piece of a reference that isn't on a public
        # CDN (the thumbnail + in-video frames are). When full extraction is
        # blocked, fetch the words from Supadata so the SCRIPT side has the real
        # source material — not just the title/thumbnail. No-ops without a key.
        if not info.get("transcript"):
            sd_transcript = await _fetch_transcript_supadata(youtube_id)
            if sd_transcript:
                info["transcript"] = sd_transcript
        transcript = info.get("transcript")
        if used_oembed:
            blockers.append(
                "YouTube limited some metadata from our servers — modeled from the title, "
                "thumbnail, in-video frames" + (", and the transcript." if transcript else " (transcript unavailable).")
            )
        if transcript is None and not used_oembed:
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
        pack = await _generate_modeled_pack(creds, info, dna, transcript, blockers, youtube_id)

        # 4. Persist everything before any generation credits are spent
        if preserve_topic:
            # Create-form path: copy ONLY the switched-on stages' style onto the
            # creator's own topic — never overwrite their title/brief.
            _set("running", "Copying the video's style…")
            await _persist_style_overrides(
                tenant_id, video_id, reference_url, youtube_id, info, dna, pack,
                blockers, pipeline_stages, lock_in_identity,
            )
            # Style is in place — open the pipeline at this plan's first step
            # (e.g. ready_for_thumbnail for a thumbnail-only modeled video).
            from status_map import first_status_for_plan
            await execute(
                "UPDATE videos SET status = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
                first_status_for_plan(pipeline_stages), video_id, tenant_id,
            )
            msg = "Style copied from the reference — your video is ready to build."
            if blockers:
                msg += " Note: " + " ".join(blockers)
            _set("completed", msg)
            return

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
