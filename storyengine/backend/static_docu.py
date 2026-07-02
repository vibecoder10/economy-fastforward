"""Static-documentary mode: detection + per-segment image sourcing.

A channel whose extracted identity says the format is static-image documentary
(``channel_profiles.channel_identity.visual_format`` — e.g. Designed vs Used:
archival photos held with slow Ken Burns pans, narration, no animation) gets
``videos.render_mode = 'static_docu'`` at creation. Those videos:

  * skip the animate stages entirely (their stage plan drops video+sound);
  * source ONE realistic representative image per scene instead of the
    ~36-frame coverage flow — never-built prototypes have no real footage, so
    the image is GENERATED from the segment's script (cheap: one image per
    vehicle/segment);
  * render via render_static.render_static_video (Remotion Ken Burns).
"""

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

from database import execute, fetch_all, fetch_one
from storage import upload_bytes

_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

STATIC_RENDER_MODE = "static_docu"

# Fingerprints of a static-image documentary format in the extracted identity's
# free text. Deliberately conservative: only flip a channel to static mode when
# its own videos clearly are (a wrong yes silently disables animation).
_STATIC_MARKERS = ("static", "ken burns", "ken-burns", "still image", "photograph")
_MOTION_VETOES = ("animation", "animated", "3d render", "motion graphics heavy")


def is_static_visual_format(visual_format: Optional[dict]) -> bool:
    """Does this channel_identity.visual_format describe a static-image docu?"""
    if not isinstance(visual_format, dict):
        return False
    text = " ".join(
        str(visual_format.get(k) or "") for k in ("motion", "style", "segmentation")
    ).lower()
    if not any(m in text for m in _STATIC_MARKERS):
        return False
    motion = str(visual_format.get("motion") or "").lower()
    return not any(v in motion for v in _MOTION_VETOES)


async def static_mode_for_tenant(tenant_id: str) -> bool:
    """Should new videos for this tenant render as static documentaries?"""
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id=$1", tenant_id)
    ci = (row or {}).get("channel_identity")
    if isinstance(ci, str):
        try:
            ci = json.loads(ci)
        except (ValueError, TypeError):
            return False
    if not isinstance(ci, dict):
        return False
    return is_static_visual_format(ci.get("visual_format"))


# --- image sourcing -----------------------------------------------------------
#
# The channel's real look (see @DesignedUsed): a clean, crisp STUDIO render of
# the exact machine — restored condition, centered side/three-quarter profile
# on a seamless white/light-gray background, soft even lighting, with an
# elegant caption (name + "type • operator • years"). To keep the machine
# ACCURATE we first find a REAL photograph of it (Wikimedia Commons, public
# archive) and run GPT Image 2 image-to-image from that reference; pure
# text-to-image is only the fallback for genuinely never-photographed designs.

_SUBJECT_HEADER = """You prepare the image plan for a static-image military-history documentary
(one image per narration segment, held on screen).

For EACH numbered segment below, identify the segment's PRIMARY machine and
reply with a JSON array only:
[{{"scene": <n>,
   "machine": "<exact full designation, e.g. 'Douglas XB-42 Mixmaster'>",
   "caption_title": "<display name for the caption>",
   "caption_sub": "<type> • <operator> • <years>, e.g. 'Pusher-propeller bomber • USAAF • 1944–1948'>",
   "search_query": "<short Wikimedia Commons search for a real photo of it>"}}, ...]

Rules:
- Use ONLY machines, designations, operators and years that appear in the
  segment text or the research facts below. Never invent a designation.
- caption_sub must be three parts joined by ' • '.
- search_query: designation + vehicle type works best (e.g. "XM2001 Crusader howitzer").

RESEARCH FACTS (source of truth):
{facts}

SEGMENTS:
{segments}"""

_STUDIO_PROMPT = (
    "Studio product photograph of the {machine}, THE EXACT SAME machine as in "
    "the reference photo — keep its real proportions, configuration and "
    "details precisely accurate. Restored museum condition, centered full "
    "side profile on a seamless white-to-light-gray studio background, soft "
    "even lighting, ultra crisp and clean, subtle ground shadow. "
    "In the lower right, elegant thin serif caption text: '{caption_title}' "
    "in large light-gray letters, and below it smaller: '{caption_sub}'. "
    "No other text, no watermark, no people. Neutral documentary presentation "
    "of a static museum subject."
)

_STUDIO_PROMPT_NOREF = (
    "Studio product photograph of the {machine}, historically accurate "
    "configuration. Restored museum condition, centered full side profile on "
    "a seamless white-to-light-gray studio background, soft even lighting, "
    "ultra crisp and clean, subtle ground shadow. "
    "In the lower right, elegant thin serif caption text: '{caption_title}' "
    "in large light-gray letters, and below it smaller: '{caption_sub}'. "
    "No other text, no watermark, no people. Neutral documentary presentation "
    "of a static museum subject."
)

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_COMMONS_UA = {"User-Agent": "StoryEngine/1.0 (nativestates.ai; media research)"}


def _parse_json_array(text: str) -> Optional[list]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        val = json.loads(m.group(0))
        return val if isinstance(val, list) else None
    except ValueError:
        return None


async def find_commons_photo(query: str) -> Optional[str]:
    """A real photograph of the machine from Wikimedia Commons (keyless API).
    Returns a ~1600px-wide image URL, or None. Skips non-photo formats."""
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_COMMONS_UA) as c:
            r = await c.get(_COMMONS_API, params={
                "action": "query", "list": "search", "srsearch": query,
                "srnamespace": 6, "srlimit": 8, "format": "json"})
            r.raise_for_status()
            hits = (r.json().get("query") or {}).get("search") or []
            titles = [h["title"] for h in hits
                      if h.get("title", "").lower().endswith((".jpg", ".jpeg", ".png"))]
            if not titles:
                return None
            r2 = await c.get(_COMMONS_API, params={
                "action": "query", "titles": "|".join(titles[:4]),
                "prop": "imageinfo", "iiprop": "url|size",
                "iiurlwidth": 1600, "format": "json"})
            r2.raise_for_status()
            pages = ((r2.json().get("query") or {}).get("pages") or {}).values()
            best = None
            for p in pages:
                for ii in p.get("imageinfo") or []:
                    w, h = ii.get("width") or 0, ii.get("height") or 0
                    if w < 500 or h < 300:
                        continue  # thumbnails/icons — too small to reference
                    url = ii.get("thumburl") or ii.get("url")
                    if url and best is None:
                        best = url
            return best
    except Exception:  # noqa: BLE001 — reference lookup is best-effort
        return None


async def _scene_subjects(tenant_id: str, scenes: list[dict],
                          research_payload: Optional[dict]) -> dict[int, dict]:
    """One Claude call -> {scene: {machine, caption_title, caption_sub,
    search_query}}, grounded in the research payload."""
    from kie_unified import get_text_client_for_tenant

    facts = ""
    if isinstance(research_payload, dict):
        facts = "\n".join(
            f"[{k}] {str(research_payload.get(k) or '')[:1200]}"
            for k in ("fact_sheet", "character_dossier", "headline")
            if research_payload.get(k))
    listing = "\n\n".join(
        f"[{s['scene']}] {(s['scene_text'] or '')[:800]}" for s in scenes)
    client = await get_text_client_for_tenant(tenant_id)
    kwargs: dict[str, Any] = {
        "prompt": _SUBJECT_HEADER.format(facts=facts or "(none)", segments=listing),
        "max_tokens": 1800,
    }
    if type(client).__name__ == "AnthropicDirectClient":
        kwargs["model"] = "claude-sonnet-4-6"
    raw = await client.generate(**kwargs)
    out: dict[int, dict] = {}
    for item in _parse_json_array(raw or "") or []:
        try:
            out[int(item["scene"])] = {
                "machine": str(item.get("machine") or "").strip(),
                "caption_title": str(item.get("caption_title") or "").strip(),
                "caption_sub": str(item.get("caption_sub") or "").strip(),
                "search_query": str(item.get("search_query") or "").strip(),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def generate_static_images_for_video(video_id: str, tenant_id: str,
                                           progress=None) -> dict:
    """One realistic archival image per scene, stored as the scene's asset.

    The static analogue of generate_coverage_for_video: reads scripts, writes
    assets rows (generation_method='static_docu', image_index=1, hero_shot).
    Idempotent per scene — re-running replaces that scene's static image.
    """
    def _p(msg):
        if progress:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001
                pass

    from shared.clients.image_client import ImageClient
    from vault import get_secret
    import os as _os

    v = await fetch_one(
        "SELECT id, video_title, COALESCE(aspect_ratio,'16:9') AS aspect, "
        "research_payload FROM videos "
        "WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not v:
        return {"status": "failed", "error": "video not found"}
    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
        "AND scene IS NOT NULL AND scene_text IS NOT NULL ORDER BY scene",
        video_id, tenant_id)
    if not scenes:
        return {"status": "failed", "error": "no scenes with text yet — write the script first"}

    rp = v.get("research_payload")
    if isinstance(rp, str):
        try:
            rp = json.loads(rp)
        except (ValueError, TypeError):
            rp = None

    _p("Identifying each segment's machine…")
    subjects = await _scene_subjects(tenant_id, scenes, rp)

    kie_key = await get_secret("kie_ai_api_key", tenant_id) or _os.getenv("KIE_AI_API_KEY")
    if not kie_key:
        return {"status": "failed", "error": "no image key on this workspace"}
    ic = ImageClient(api_key=kie_key)

    done, failed = 0, []
    for s in scenes:
        sc = s["scene"]
        sub = subjects.get(sc) or {}
        machine = sub.get("machine") or (s["scene_text"] or "")[:80]
        caption_title = sub.get("caption_title") or machine
        caption_sub = sub.get("caption_sub") or "Prototype • US Army • canceled"

        # 1) Find a REAL photo of the machine so the render is accurate.
        ref_url = None
        if sub.get("search_query"):
            _p(f"Segment {sc}: finding a real photo of the {machine}…")
            ref_url = await find_commons_photo(sub["search_query"])
            if not ref_url and machine:
                ref_url = await find_commons_photo(machine)

        # 2) Clean crisp studio render — image-to-image from the real photo
        #    when we have one, text-to-image only as the fallback.
        template = _STUDIO_PROMPT if ref_url else _STUDIO_PROMPT_NOREF
        prompt = template.format(
            machine=machine, caption_title=caption_title, caption_sub=caption_sub)
        _p(f"Segment {sc}/{len(scenes)}: rendering the studio image"
           + (" (from real reference)" if ref_url else " (no reference found)") + "…")
        res = await ic.generate_scene_image_gpt(
            prompt, ref_url, aspect_ratio=v["aspect"])
        url = (res or {}).get("url")
        if not url and ref_url:
            # Reference path failed (fetch/policy) — retry without it.
            res = await ic.generate_scene_image_gpt(
                _STUDIO_PROMPT_NOREF.format(
                    machine=machine, caption_title=caption_title,
                    caption_sub=caption_sub),
                None, aspect_ratio=v["aspect"])
            url = (res or {}).get("url")
        if not url:
            failed.append(str(sc))
            continue
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.get(url, follow_redirects=True)
            r.raise_for_status()
            data = r.content
        durable = await upload_bytes(
            data, f"{video_id}/static/S{sc:02d}.png", "image/png", tenant_id)
        await execute(
            "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
            "AND generation_method=$4", video_id, tenant_id, sc, STATIC_RENDER_MODE)
        await execute(
            "INSERT INTO assets (id, tenant_id, video_id, scene, image_index, "
            "sentence_index, sentence_text, image_prompt, shot_type, video_title, "
            "aspect_ratio, status, image_url, drive_image_url, hero_shot, "
            "generation_method) "
            "VALUES ($1,$2,$3,$4,1,1,$5,$6,'wide',$7,$8,'done',$9,$9,true,$10)",
            str(uuid.uuid4()), tenant_id, video_id, sc,
            (s["scene_text"] or "")[:500],
            (f"[ref: {ref_url}] " if ref_url else "") + prompt[:900],
            v["video_title"], v["aspect"], durable, STATIC_RENDER_MODE,
        )
        done += 1
    if not done:
        return {"status": "failed",
                "error": f"no images generated (scenes failed: {', '.join(failed)})"}
    msg = f"Generated {done}/{len(scenes)} segment images"
    if failed:
        msg += f" (failed: {', '.join(failed)})"
    return {"status": "completed", "message": msg}
