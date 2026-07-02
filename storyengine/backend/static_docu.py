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
   "aliases": ["<other designations the SAME or sibling vehicle is known by, "
               "e.g. the MBT-70's German twin 'Kampfpanzer 70', a redesignation, "
               "or the manufacturer name — real names only>"],
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

# Captions are NOT baked into the image — they render as a fixed Remotion
# text overlay (assets.caption), so the Ken Burns pan can't crop them and the
# model can't invent stencils/markings-as-text.
_STUDIO_PROMPT = (
    "Studio product photograph of the {machine}, THE EXACT SAME machine as in "
    "the reference photo — keep its real proportions, configuration and "
    "details precisely accurate. Restored museum condition, centered full "
    "side profile on a seamless white-to-light-gray studio background, soft "
    "even lighting, ultra crisp and clean, subtle ground shadow. "
    "ABSOLUTELY NO text, NO lettering, NO labels, NO watermark anywhere in "
    "the image. No people. Neutral documentary presentation of a static "
    "museum subject."
)

_STUDIO_PROMPT_NOREF = (
    "Studio product photograph of the {machine}, historically accurate "
    "configuration. Restored museum condition, centered full side profile on "
    "a seamless white-to-light-gray studio background, soft even lighting, "
    "ultra crisp and clean, subtle ground shadow. "
    "ABSOLUTELY NO text, NO lettering, NO labels, NO watermark anywhere in "
    "the image. No people. Neutral documentary presentation of a static "
    "museum subject."
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


async def find_commons_photos(query: str, limit: int = 3) -> list[str]:
    """Real photographs of the machine from Wikimedia Commons (keyless API).
    Returns up to `limit` candidate image URLs (~1600px), best first."""
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_COMMONS_UA) as c:
            r = await c.get(_COMMONS_API, params={
                "action": "query", "list": "search", "srsearch": query,
                "srnamespace": 6, "srlimit": 8, "format": "json"})
            r.raise_for_status()
            hits = (r.json().get("query") or {}).get("search") or []
            # Photographs / full renderings only — a line sketch as an img2img
            # reference makes the model invent the body (bit us on MBT-70).
            _bad = ("sketch", "drawing", "diagram", "blueprint", "map",
                    "insignia", "logo", "emblem", "patch", "lego", "toy")
            titles = [h["title"] for h in hits
                      if h.get("title", "").lower().endswith((".jpg", ".jpeg", ".png"))
                      and not any(b in h.get("title", "").lower() for b in _bad)]
            if not titles:
                return []
            r2 = await c.get(_COMMONS_API, params={
                "action": "query", "titles": "|".join(titles[:6]),
                "prop": "imageinfo", "iiprop": "url|size",
                "iiurlwidth": 1600, "format": "json"})
            r2.raise_for_status()
            pages = ((r2.json().get("query") or {}).get("pages") or {}).values()
            out: list[str] = []
            for p in pages:
                for ii in p.get("imageinfo") or []:
                    w, h = ii.get("width") or 0, ii.get("height") or 0
                    if w < 500 or h < 300:
                        continue  # thumbnails/icons — too small to reference
                    url = ii.get("url") or ""
                    thumb = ii.get("thumburl") or ""
                    # ONLY API-issued /thumb/ URLs are servable: the raw-file
                    # layer 403s cloud IPs, and hand-built thumb URLs for
                    # never-rendered sizes 403 too (the API request is what
                    # warms the CDN — proven live). For originals smaller than
                    # the requested width, ask the API for a width-1 thumb.
                    if (not thumb or thumb == url) and p.get("title"):
                        try:
                            r3 = await c.get(_COMMONS_API, params={
                                "action": "query", "titles": p["title"],
                                "prop": "imageinfo", "iiprop": "url",
                                "iiurlwidth": max(500, w - 1), "format": "json"})
                            pp = ((r3.json().get("query") or {}).get("pages") or {}).values()
                            for p3 in pp:
                                for ii3 in p3.get("imageinfo") or []:
                                    t3 = ii3.get("thumburl") or ""
                                    if t3 and t3 != url:
                                        thumb = t3
                        except Exception:  # noqa: BLE001
                            pass
                    if thumb and thumb != url and "/thumb/" in thumb:
                        out.append(thumb)
            return out[:limit]
    except Exception:  # noqa: BLE001 — reference lookup is best-effort
        return []


async def _host_reference(url: str, video_id: str, tenant_id: str,
                          scene: int, idx: int) -> Optional[str]:
    """Fetch the Commons photo OURSELVES (proper User-Agent — Wikimedia 403s
    Kie's fetcher on raw file URLs) and re-host it on our storage. The image
    client rewrites the stored Drive URL to the media proxy, so Kie always
    fetches references from US, never from Wikimedia."""
    try:
        async with httpx.AsyncClient(timeout=60.0, headers=_COMMONS_UA,
                                     follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            data = r.content
        if len(data) < 10_000:
            return None
        ext = "png" if url.lower().endswith(".png") else "jpg"
        return await upload_bytes(
            data, f"{video_id}/static/ref_S{scene:02d}_{idx}.{ext}",
            "image/png" if ext == "png" else "image/jpeg", tenant_id)
    except Exception:  # noqa: BLE001
        return None


def _designation_token(machine: str) -> str:
    """The machine's designation as a matchable token: the first word with a
    digit, alphanumerics only, lowercased (e.g. 'MBT-70' -> 'mbt70',
    'XM2001 Crusader' -> 'xm2001', 'T95 medium tank' -> 't95')."""
    for word in (machine or "").split():
        if any(ch.isdigit() for ch in word):
            return re.sub(r"[^a-z0-9]", "", word.lower())
    return re.sub(r"[^a-z0-9]", "", (machine or "").lower())[:12]


async def _vision_confirms(tenant_id: str, image_url: str, machine: str,
                           aliases: Optional[list] = None) -> bool:
    """Vision sanity check: does this image actually show the machine, as a
    photograph/full rendering (not a sketch or scale model)?

    Framed as neutral IDENTIFICATION — a yes/no 'verify this military
    hardware' framing made the model refuse outright (seen live), and a
    refusal is neither yes nor no. We ask what the image shows and match the
    designation in the answer. Fail-open on transport errors only."""
    from vault import get_secret
    from identity_builder import _KIE_CLAUDE_URL

    try:
        key = await get_secret("kie_ai_api_key", tenant_id)
        if not key:
            return True
        from shared.clients.image_client import _kie_fetchable_url
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                _KIE_CLAUDE_URL,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": "claude-haiku-4-5", "max_tokens": 80,
                      "messages": [{"role": "user", "content": [
                          {"type": "text", "text":
                           "One line: what vehicle/machine does this image "
                           "primarily show (designation if identifiable), and "
                           "is the image a photograph, a drawing/sketch/diagram, "
                           "or a scale model?"},
                          {"type": "image", "source": {"type": "url",
                           "url": _kie_fetchable_url(image_url)}},
                      ]}]},
            )
        body = r.json()
        txt = " ".join(b.get("text", "") for b in body.get("content", [])
                       if b.get("type") == "text").strip().lower()
        if not txt:
            return True
        norm = re.sub(r"[^a-z0-9 ]", "", txt).replace(" ", "")
        tokens = [_designation_token(n) for n in [machine] + list(aliases or [])]
        named = any(t and t in norm for t in tokens)
        is_flat = any(k in txt for k in ("drawing", "sketch", "diagram",
                                         "blueprint", "scale model", "schematic"))
        return named and not is_flat
    except Exception:  # noqa: BLE001
        return True


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
                "aliases": [str(a).strip() for a in (item.get("aliases") or [])
                            if str(a).strip()][:4],
                "caption_title": str(item.get("caption_title") or "").strip(),
                "caption_sub": str(item.get("caption_sub") or "").strip(),
                "search_query": str(item.get("search_query") or "").strip(),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def generate_static_images_for_video(video_id: str, tenant_id: str,
                                           progress=None,
                                           only_scenes: Optional[set] = None) -> dict:
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
    if only_scenes:
        scenes = [s for s in scenes if s["scene"] in only_scenes]
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

        # Placeholder row FIRST: the media proxy only serves file ids present
        # in allowlisted DB columns, and the self-hosted reference must be
        # proxy-fetchable during generation. image_url stays NULL until the
        # real image exists, so a concurrent render can't pick up the raw ref.
        row_id = str(uuid.uuid4())
        await execute(
            "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
            "AND generation_method=$4", video_id, tenant_id, sc, STATIC_RENDER_MODE)
        await execute(
            "INSERT INTO assets (id, tenant_id, video_id, scene, image_index, "
            "sentence_index, sentence_text, shot_type, video_title, aspect_ratio, "
            "status, hero_shot, generation_method, caption) "
            "VALUES ($1,$2,$3,$4,1,1,$5,'wide',$6,$7,'generating',true,$8,$9)",
            row_id, tenant_id, video_id, sc, (s["scene_text"] or "")[:500],
            v["video_title"], v["aspect"], STATIC_RENDER_MODE,
            json.dumps({"title": caption_title, "sub": caption_sub}),
        )

        # 1) Find a REAL photo, SELF-HOST it (Wikimedia 403s Kie's fetcher),
        #    and vision-check it actually shows this machine (designation
        #    collisions like the Russian T-95 vs the US T95).
        ref_url = None
        ref_src = None
        candidates = []
        if sub.get("search_query"):
            _p(f"Segment {sc}: finding a real photo of the {machine}…")
            candidates = await find_commons_photos(sub["search_query"])
        if not candidates and machine:
            candidates = await find_commons_photos(machine)
        for idx, cand in enumerate(candidates):
            hosted = await _host_reference(cand, video_id, tenant_id, sc, idx)
            if not hosted:
                continue
            await execute(
                "UPDATE assets SET drive_image_url=$2 WHERE id=$1", row_id, hosted)
            if await _vision_confirms(tenant_id, hosted, machine, sub.get("aliases")):
                ref_url, ref_src = hosted, cand
                break
            _p(f"Segment {sc}: candidate photo rejected (not the {machine})")

        # 2) Clean crisp studio render — image-to-image from the real photo
        #    when we have one, text-to-image only as the fallback.
        template = _STUDIO_PROMPT if ref_url else _STUDIO_PROMPT_NOREF
        prompt = template.format(machine=machine)
        _p(f"Segment {sc}/{len(scenes)}: rendering the studio image"
           + (" (from real reference)" if ref_url else " (no verified reference)") + "…")
        res = await ic.generate_scene_image_gpt(
            prompt, ref_url, aspect_ratio=v["aspect"])
        url = (res or {}).get("url")
        if not url and ref_url:
            # Reference path failed (fetch/policy) — retry without it.
            res = await ic.generate_scene_image_gpt(
                _STUDIO_PROMPT_NOREF.format(machine=machine),
                None, aspect_ratio=v["aspect"])
            url = (res or {}).get("url")
        if not url:
            await execute("DELETE FROM assets WHERE id=$1", row_id)
            failed.append(str(sc))
            continue

        # Post-generation accuracy check: does the OUTPUT actually look like
        # the machine? One bounded retry with a match-the-reference
        # reinforcement; a still-failing image ships with a warning (the
        # operator sees it in the progress feed) rather than blocking.
        if not await _vision_confirms(tenant_id, url, machine, sub.get("aliases")):
            if ref_url:
                _p(f"Segment {sc}: render doesn't match the {machine} — retrying against the reference…")
                res = await ic.generate_scene_image_gpt(
                    prompt + " Reproduce the machine in the reference image "
                    "EXACTLY — same hull, turret, wheels and proportions.",
                    ref_url, aspect_ratio=v["aspect"])
                url2 = (res or {}).get("url")
                if url2 and await _vision_confirms(tenant_id, url2, machine, sub.get("aliases")):
                    url = url2
                else:
                    url = url2 or url
                    _p(f"Segment {sc}: WARNING — image may not match the real {machine}; review it")
            else:
                _p(f"Segment {sc}: WARNING — no reference photo found and the "
                   f"render may not match the real {machine}; review it")

        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.get(url, follow_redirects=True)
            r.raise_for_status()
            data = r.content
        durable = await upload_bytes(
            data, f"{video_id}/static/S{sc:02d}.png", "image/png", tenant_id)
        await execute(
            "UPDATE assets SET image_url=$2, drive_image_url=$2, status='done', "
            "image_prompt=$3 WHERE id=$1",
            row_id, durable,
            (f"[ref: {ref_src}] " if ref_src else "") + prompt[:900],
        )
        done += 1
    if not done:
        return {"status": "failed",
                "error": f"no images generated (scenes failed: {', '.join(failed)})"}
    msg = f"Generated {done}/{len(scenes)} segment images"
    if failed:
        msg += f" (failed: {', '.join(failed)})"
    return {"status": "completed", "message": msg}
