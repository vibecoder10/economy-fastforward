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

# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from shared.channel_profile import CLAUDE_MODELS, claude_model_for_direct_client  # noqa: E402

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
    "side profile on a seamless PURE WHITE studio background (clean bright "
    "white, never gray, never off-white), soft even lighting, ultra crisp "
    "and clean, only a subtle soft ground shadow directly beneath the "
    "machine. "
    "ABSOLUTELY NO text, NO lettering, NO labels, NO watermark anywhere in "
    "the image. No people. Neutral documentary presentation of a static "
    "museum subject."
)

_STUDIO_PROMPT_NOREF = (
    "Studio product photograph of the {machine}, historically accurate "
    "configuration. Restored museum condition, centered full side profile on "
    "a seamless PURE WHITE studio background (clean bright white, never "
    "gray, never off-white), soft even lighting, ultra crisp and clean, "
    "only a subtle soft ground shadow directly beneath the machine. "
    "ABSOLUTELY NO text, NO lettering, NO labels, NO watermark anywhere in "
    "the image. No people. Neutral documentary presentation of a static "
    "museum subject."
)

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_COMMONS_UA = {"User-Agent": "StoryEngine/1.0 (nativestates.ai; media research)"}

# Wikimedia politeness: ONE throttled gateway for every wikimedia.org request
# (API + file fetches). Bursts of anonymous requests got both the VPS and the
# dev machine 429/403-limited mid-run — pace them and honor Retry-After.
_WM_MIN_INTERVAL = 1.5
_wm_lock: Optional["asyncio.Lock"] = None
_wm_last = 0.0


async def _wm_get(c: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    import asyncio
    import time

    global _wm_lock, _wm_last
    if _wm_lock is None:
        _wm_lock = asyncio.Lock()
    for attempt in range(4):
        async with _wm_lock:
            wait = _WM_MIN_INTERVAL - (time.monotonic() - _wm_last)
            if wait > 0:
                await asyncio.sleep(wait)
            _wm_last = time.monotonic()
        r = await c.get(url, **kwargs)
        if r.status_code not in (429, 403):
            return r
        # Honor Wikimedia's own Retry-After. Cap at 90s (not 30) — a real
        # cooldown after a burst lasts minutes, and truncating it just burns
        # attempts inside the block window (seen live on the DvsU micro-test).
        retry_after = min(float(r.headers.get("retry-after") or 10 * (attempt + 1)), 90.0)
        await asyncio.sleep(retry_after)
    return r


def _parse_json_array(text: str) -> Optional[list]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        val = json.loads(m.group(0))
        return val if isinstance(val, list) else None
    except ValueError:
        return None


_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


async def _api_issued_thumb(c: httpx.AsyncClient, raw_url: str) -> Optional[str]:
    """Turn a RAW upload.wikimedia URL into an API-ISSUED /thumb/ URL.

    The raw-file layer 403s cloud IPs; only thumb URLs the API itself has
    issued are reliably served (the request warms the CDN). For originals
    smaller than the requested width the API echoes the raw URL back, so
    re-ask at width-1."""
    try:
        from urllib.parse import unquote
        fname = unquote(raw_url.rsplit("/", 1)[1])
        for width in (1600, None):
            if width is None:
                r0 = await _wm_get(c, _COMMONS_API, params={
                    "action": "query", "titles": f"File:{fname}",
                    "prop": "imageinfo", "iiprop": "size", "format": "json"})
                pages0 = ((r0.json().get("query") or {}).get("pages") or {}).values()
                w0 = 0
                for p0 in pages0:
                    for ii0 in p0.get("imageinfo") or []:
                        w0 = ii0.get("width") or 0
                if w0 <= 501:
                    return None
                width = w0 - 1
            r = await _wm_get(c, _COMMONS_API, params={
                "action": "query", "titles": f"File:{fname}",
                "prop": "imageinfo", "iiprop": "url",
                "iiurlwidth": width, "format": "json"})
            pages = ((r.json().get("query") or {}).get("pages") or {}).values()
            for p in pages:
                for ii in p.get("imageinfo") or []:
                    t = ii.get("thumburl") or ""
                    if t and "/thumb/" in t:
                        return t
        return None
    except Exception:  # noqa: BLE001
        return None


async def find_wikipedia_lead_images(names: list, limit: int = 3) -> list[str]:
    """LAYER 1 reference source: the lead image of the machine's Wikipedia
    article(s). Highest precision available — the article's page image is the
    community-curated canonical photo of exactly that subject, so there is no
    search ambiguity. pithumbsize makes the API ISSUE the thumb URL (the only
    kind Wikimedia's CDN reliably serves to cloud IPs). Tries the designation
    and each alias; best-first, de-duplicated."""
    out: list[dict] = []
    seen: set = set()
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_COMMONS_UA) as c:
            for name in [n for n in names if n][:4]:
                try:
                    # EXACT title first (redirects followed): search ranking is
                    # unstable — the same query returned the T95 article one
                    # hour and a list-article (Sherman lead image) the next.
                    # An exact title hit is deterministic provenance.
                    r = await _wm_get(c, _WIKIPEDIA_API, params={
                        "action": "query", "titles": name, "redirects": 1,
                        "prop": "pageimages", "piprop": "thumbnail",
                        "pithumbsize": 1600, "format": "json"})
                    r.raise_for_status()
                    pages = [p for p in ((r.json().get("query") or {})
                                         .get("pages") or {}).values()
                             if p.get("thumbnail")]
                    if not pages:
                        r = await _wm_get(c, _WIKIPEDIA_API, params={
                            "action": "query", "generator": "search",
                            "gsrsearch": name, "gsrlimit": 2,
                            "prop": "pageimages", "piprop": "thumbnail",
                            "pithumbsize": 1600, "format": "json"})
                        r.raise_for_status()
                        pages = ((r.json().get("query") or {}).get("pages") or {}).values()
                    for p in sorted(pages, key=lambda x: x.get("index") or 9):
                        src = ((p.get("thumbnail") or {}).get("source") or "")
                        if src and "/thumb/" not in src:
                            # Original smaller than pithumbsize → API echoed
                            # the RAW url, which 403s cloud IPs. Get a real
                            # API-issued thumb instead.
                            src = await _api_issued_thumb(c, src) or ""
                        if src and src not in seen:
                            seen.add(src)
                            # PROVENANCE: an image from the article whose title
                            # matches the designation is near-certainly the
                            # right machine — by-sight naming is not required.
                            page_tok = re.sub(r"[^a-z0-9]", "",
                                              (p.get("title") or "").lower())
                            trusted = any(
                                t and t in page_tok
                                for t in (_designation_token(n) for n in names if n))
                            out.append({"url": src, "page": p.get("title") or "",
                                        "trusted": trusted})
                except Exception:  # noqa: BLE001 — try the next name
                    continue
                if len(out) >= limit:
                    break
    except Exception:  # noqa: BLE001
        pass
    return out[:limit]


async def find_commons_photos(query: str, limit: int = 3) -> list[str]:
    """Real photographs of the machine from Wikimedia Commons (keyless API).
    Returns up to `limit` candidate image URLs (~1600px), best first."""
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_COMMONS_UA) as c:
            r = await _wm_get(c, _COMMONS_API, params={
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
            r2 = await _wm_get(c, _COMMONS_API, params={
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
                            r3 = await _wm_get(c, _COMMONS_API, params={
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
    fetches references from US, never from Wikimedia.

    Wikimedia rate-limits bursts (429, seen live on the DvsU micro-test) —
    retry with backoff before giving up, because losing the reference is what
    pushes generation onto the inaccurate no-reference path."""
    import asyncio as _asyncio

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=60.0, headers=_COMMONS_UA,
                                         follow_redirects=True) as c:
                r = await (_wm_get(c, url) if "wikimedia.org" in url else c.get(url))
                if r.status_code == 429 and attempt < 2:
                    await _asyncio.sleep(4 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.content
            if len(data) < 10_000:
                return None
            ext = "png" if url.lower().endswith(".png") else "jpg"
            return await upload_bytes(
                data, f"{video_id}/static/ref_S{scene:02d}_{idx}.{ext}",
                "image/png" if ext == "png" else "image/jpeg", tenant_id)
        except Exception:  # noqa: BLE001
            if attempt < 2:
                await _asyncio.sleep(4 * (attempt + 1))
    return None


def _machine_key(machine: str) -> str:
    """Stable cache key for a machine name (case/punctuation-insensitive)."""
    return re.sub(r"[^a-z0-9]", "", (machine or "").lower())[:80]


async def _ensure_ref_cache_schema() -> None:
    """Verified-reference cache: one Wikimedia lookup per machine, ever.
    Defensive CREATE (same pattern as channel_profile_documents) so the
    feature works without waiting on a migration run."""
    await execute(
        """CREATE TABLE IF NOT EXISTS static_reference_cache (
            tenant_id UUID NOT NULL,
            machine_key TEXT NOT NULL,
            machine TEXT,
            hosted_url TEXT NOT NULL,
            source_url TEXT,
            verified_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (tenant_id, machine_key)
        )""")


def _page_matches(machine: str, aliases: Optional[list], page: str) -> bool:
    """Does the Wikipedia article title actually name this machine?

    A lead image is only 'trusted' because it belongs to the machine's OWN
    article — but the title search is fuzzy and can land on a similar
    machine's article (seen live: the 'Covenanter' search returned the
    Crusader tank's lead image). If the page title doesn't share the
    machine's designation token or a significant name word, the provenance
    guarantee is void and the candidate must pass the strict vision check."""
    _GENERIC = {"tank", "tanks", "aircraft", "airplane", "plane", "ship",
                "boat", "submarine", "helicopter", "carrier", "battleship",
                "destroyer", "cruiser", "frigate", "bomber", "fighter",
                "class", "type", "mark", "light", "heavy", "medium", "main",
                "battle", "vehicle", "gun", "self", "propelled", "united",
                "states", "british", "soviet", "german", "american", "army",
                "navy", "royal"}
    norm_page = re.sub(r"[^a-z0-9 ]", "", (page or "").lower())
    if not norm_page:
        return False
    compact_page = norm_page.replace(" ", "")
    page_words = set(norm_page.split())
    for name in [machine] + list(aliases or []):
        tok = _designation_token(name)
        if tok and tok in compact_page:
            return True
        for word in re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).split():
            if len(word) >= 4 and word not in _GENERIC and word in page_words:
                return True
    return False


def _designation_token(machine: str) -> str:
    """The machine's designation as a matchable token: the first word with a
    digit, alphanumerics only, lowercased (e.g. 'MBT-70' -> 'mbt70',
    'XM2001 Crusader' -> 'xm2001', 'T95 medium tank' -> 't95')."""
    for word in (machine or "").split():
        if any(ch.isdigit() for ch in word):
            return re.sub(r"[^a-z0-9]", "", word.lower())
    return re.sub(r"[^a-z0-9]", "", (machine or "").lower())[:12]


async def _vision_confirms(tenant_id: str, image_url: str, machine: str,
                           aliases: Optional[list] = None,
                           trusted_source: bool = False) -> bool:
    """Vision sanity check: does this image actually show the machine, as a
    photograph/full rendering (not a sketch or scale model)?

    Framed as neutral IDENTIFICATION — a yes/no 'verify this military
    hardware' framing made the model refuse outright (seen live), and a
    refusal is neither yes nor no. We ask what the image shows and match the
    designation in the answer. Fail-open on transport errors only."""
    from vault import get_secret

    try:
        from shared.clients.image_client import _kie_fetchable_url
        content = [
            {"type": "text", "text":
             "One line: what vehicle/machine does this image "
             "primarily show (designation if identifiable), and "
             "is the image a photograph, a drawing/sketch/diagram, "
             "or a scale model?"},
            {"type": "image", "source": {"type": "url",
             "url": _kie_fetchable_url(image_url)}},
        ]
        # DIRECT Anthropic first — the Kie gateway injects tool configuration
        # that derails the reply into meta-talk about tools (seen live).
        akey = await get_secret("anthropic_api_key", tenant_id)
        async with httpx.AsyncClient(timeout=60.0) as c:
            if akey:
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": akey,
                             "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                    json={"model": CLAUDE_MODELS["anthropic"]["fast"], "max_tokens": 80,
                          "messages": [{"role": "user", "content": content}]},
                )
            else:
                key = await get_secret("kie_ai_api_key", tenant_id)
                if not key:
                    return True
                import os
                kie_claude_url = os.getenv(
                    "KIE_CLAUDE_BASE_URL", "https://api.kie.ai/claude"
                ).rstrip("/") + "/v1/messages"
                r = await c.post(
                    kie_claude_url,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json={"model": CLAUDE_MODELS["kie"]["fast"], "max_tokens": 80,
                          "messages": [{"role": "user", "content": content}]},
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
        if trusted_source:
            # Provenance already ties this image to the machine (it is the
            # lead image of the machine's own article) — nobody can "name" an
            # obscure prototype by sight, so only reject flat media and
            # obviously-wrong content (interiors, people, maps).
            wrong = any(k in txt for k in ("interior", "cockpit", "person",
                                           "portrait", "map", "insignia",
                                           "document", "text page"))
            return not is_flat and not wrong
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
    model = claude_model_for_direct_client(client)
    if model:
        kwargs["model"] = model
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
    ic = ImageClient(api_key=kie_key, tenant_id=tenant_id)
    await _ensure_ref_cache_schema()

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
        #    LAYER 0: the tenant's own verified-reference cache — series reuse
        #    the same machines across videos, so each machine costs ONE
        #    Wikimedia conversation ever (and rate limits stop mattering).
        #    LAYER 1: the machine's Wikipedia article lead image — curated,
        #    unambiguous, and API-issued. LAYER 2: Commons search for extra
        #    candidates/angles.
        ref_url = None
        ref_src = None
        mkey = _machine_key(machine)
        cached = await fetch_one(
            "SELECT hosted_url, source_url FROM static_reference_cache "
            "WHERE tenant_id=$1 AND machine_key=$2", tenant_id, mkey)
        if cached:
            ref_url, ref_src = cached["hosted_url"], cached["source_url"]
            await execute(
                "UPDATE assets SET drive_image_url=$2 WHERE id=$1", row_id, ref_url)
            _p(f"Segment {sc}: using the cached verified photo of the {machine}")
        if not ref_url:
            _p(f"Segment {sc}: finding a real photo of the {machine}…")
            wiki = await find_wikipedia_lead_images(
                [machine] + list(sub.get("aliases") or []))
            # 'trusted' provenance only holds when the article title names OUR
            # machine — a fuzzy search that landed on a lookalike's article gets
            # demoted to the strict vision check instead of a free pass.
            candidates = [
                (w["url"],
                 w["trusted"] and _page_matches(machine, sub.get("aliases"), w.get("page", "")))
                for w in wiki
            ]
            have = {u for u, _ in candidates}
            if sub.get("search_query"):
                candidates += [(c, False) for c in await find_commons_photos(sub["search_query"])
                               if c not in have]
            if not candidates and machine:
                candidates = [(c, False) for c in await find_commons_photos(machine)]
            for idx, (cand, trusted) in enumerate(candidates):
                hosted = await _host_reference(cand, video_id, tenant_id, sc, idx)
                if not hosted:
                    continue
                await execute(
                    "UPDATE assets SET drive_image_url=$2 WHERE id=$1", row_id, hosted)
                if await _vision_confirms(tenant_id, hosted, machine,
                                          sub.get("aliases"), trusted_source=trusted):
                    ref_url, ref_src = hosted, cand
                    await execute(
                        """INSERT INTO static_reference_cache
                               (tenant_id, machine_key, machine, hosted_url, source_url)
                           VALUES ($1,$2,$3,$4,$5)
                           ON CONFLICT (tenant_id, machine_key)
                           DO UPDATE SET machine=$3, hosted_url=$4, source_url=$5,
                                         verified_at=now()""",
                        tenant_id, mkey, machine[:200], hosted, cand)
                    break
                _p(f"Segment {sc}: candidate photo rejected (not the {machine})")

        # 2) Clean crisp studio render — image-to-image from the real photo
        #    when we have one, text-to-image only as the fallback.
        template = _STUDIO_PROMPT if ref_url else _STUDIO_PROMPT_NOREF
        prompt = template.format(machine=machine)
        _p(f"Segment {sc}/{len(scenes)}: rendering the studio image"
           + (" (from real reference)" if ref_url else " (no verified reference)") + "…")
        # Accuracy policy ("a wrong image is worse than a missing one" — the
        # static-docu channels' own standard): GPT Image 2 ONLY, never the
        # nano fallback; a scene that can't produce a verified image FAILS
        # for review instead of shipping a lookalike. Re-running the stage
        # regenerates only the failed scenes (idempotent per scene).
        # 1K resolution: the held Ken Burns frame doesn't need more, and 1K is
        # ~3 cents per image vs the 2K price — the channel runs on volume.
        res = await ic.generate_scene_image_gpt(
            prompt, ref_url, aspect_ratio=v["aspect"], allow_fallback=False,
            resolution="1K")
        url = (res or {}).get("url")
        if not url:
            _p(f"Segment {sc}: image generation failed — scene marked for re-run")
            await execute("DELETE FROM assets WHERE id=$1", row_id)
            failed.append(str(sc))
            continue

        # Post-generation accuracy check: does the OUTPUT actually look like
        # the machine? One bounded retry, then FAIL the scene — never ship an
        # unverified machine on an audience that knows every rivet.
        if not await _vision_confirms(tenant_id, url, machine, sub.get("aliases")):
            _p(f"Segment {sc}: render doesn't match the {machine} — one retry…")
            retry_prompt = prompt + (
                " Reproduce the machine in the reference image EXACTLY — same "
                "hull, turret, wheels and proportions." if ref_url else
                " Render the historically documented configuration of this "
                "exact machine with precise accuracy.")
            res = await ic.generate_scene_image_gpt(
                retry_prompt, ref_url, aspect_ratio=v["aspect"], allow_fallback=False,
                resolution="1K")
            url2 = (res or {}).get("url")
            if url2 and await _vision_confirms(tenant_id, url2, machine, sub.get("aliases")):
                url = url2
            elif ref_url:
                # We HAVE proof of what this machine looks like and the render
                # doesn't match it — fail the scene rather than ship it.
                _p(f"Segment {sc}: could not verify the render shows the real "
                   f"{machine} — scene failed for review (not shipped)")
                await execute("DELETE FROM assets WHERE id=$1", row_id)
                failed.append(str(sc))
                continue
            else:
                # No reference exists (e.g. never-built prototype) — vision
                # can't reasonably NAME an obscure machine from a render, so
                # ship it flagged; the operator judges it at the images gate.
                url = url2 or url
                _p(f"Segment {sc}: WARNING — no reference photo exists for the "
                   f"{machine}; review this render at the images gate")

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
