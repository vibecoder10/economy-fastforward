"""Static-documentary mode: detection + per-segment image sourcing.

A channel whose extracted identity says the format is static-image documentary
(``channel_profiles.channel_identity.visual_format`` — e.g. Designed vs Used:
archival photos held with slow Ken Burns pans, narration, no animation) gets
``videos.render_mode = 'static_docu'`` at creation. Those videos:

  * skip the animate stages entirely (their stage plan drops video+sound);
  * source THREE realistic complementary images per scene instead of the
    ~36-frame coverage flow — a three-quarter identification view, an elevated
    top-oblique view, and a narration-relevant engineering detail, with two
    verified views as the minimum renderable set;
  * render via render_static.render_static_video (Remotion Ken Burns).
"""

import base64
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

from database import execute, fetch_all, fetch_one
from static_docu_contract import (
    STATIC_VIEW_PLANS,
    STATIC_VIEWS_MINIMUM,
    STATIC_VIEWS_TARGET,
)
from storage import upload_bytes

_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from shared.channel_profile import CLAUDE_MODELS, claude_model_for_direct_client  # noqa: E402

_logger = logging.getLogger(__name__)

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
        "SELECT production_style_id, channel_identity "
        "FROM channel_profiles WHERE tenant_id=$1",
        tenant_id,
    )
    # Migration 121 links the original channel to the same public profile new
    # customers select. That catalog reference is now authoritative; the
    # legacy identity fingerprint remains the compatibility fallback.
    linked_profile = (row or {}).get("production_style_id")
    if linked_profile:
        return linked_profile == "photo_documentary"
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
# the exact machine — restored condition, led by a three-quarter profile and
# supported by an elevated view plus a narration-relevant detail view on a
# seamless white/light-gray background, soft even lighting, with an elegant
# title card (name + operator/service years + grounded specs). To keep the machine
# ACCURATE we first find a REAL, VERIFIED photograph of it (Wikipedia lead
# image / article body / Wikimedia Commons) and run GPT Image 2 image-to-
# image from that reference. FAIL CLOSED: reference-free text-to-image
# generation is not offered — a wrong image is worse than a missing one, so a
# scene with no verified reference is BLOCKED for the operator, never shipped
# from a guess (see the FAIL CLOSED block in _one_scene).

_SUBJECT_HEADER = """You prepare the image plan for a static-image military-history documentary
(three complementary images per narration segment, rotated under one voiceover).

For EACH numbered segment below, identify the segment's PRIMARY machine and
reply with a JSON array only:
[{{"scene": <n>,
   "machine": "<exact full designation, e.g. 'Douglas XB-42 Mixmaster'>",
   "aliases": ["<other designations the SAME or sibling vehicle is known by, "
               "e.g. the MBT-70's German twin 'Kampfpanzer 70', a redesignation, "
               "or the manufacturer name — real names only>"],
   "caption_title": "<display name for the caption>",
   "caption_sub": "<operator> • <service/test years>, e.g. 'USAAF • 1944–1948'>",
   "caption_specs": ["<one short exact sourced spec>", "<optional second exact sourced spec>"],
   "detail_focus": "<one distinctive visible feature explicitly supported by the segment or research>",
   "search_query": "<short Wikimedia Commons search for a real photo of it>"}}, ...]

Rules:
- Use ONLY machines, designations, operators and years that appear in the
  segment text or the research facts below. Never invent a designation.
- caption_sub must contain operator and service/test years joined by ' • '.
- caption_specs must contain one or two concise, audience-readable specs with
  both label and value, e.g. "Wingspan 185 ft" or "Maximum speed 650 mph".
  Every number and unit must appear verbatim in the segment or research facts.
  If only one exact spec is supported, return one. If none is supported, [].
- detail_focus must be a visible engineering feature supported by the supplied
  material. If none is explicit, use "overall airframe geometry" (or the
  equivalent whole-machine form for a ship, tank, or helicopter).
- search_query: designation + vehicle type works best (e.g. "XM2001 Crusader howitzer").

RESEARCH FACTS (source of truth):
{facts}

SEGMENTS:
{segments}"""

# Title text is NOT baked into the image — it renders as one fixed Remotion
# overlay per aircraft (assets.caption), so the Ken Burns move cannot crop it
# and the model cannot invent stencils/markings-as-text.
_STUDIO_PROMPT = (
    "Studio product photograph of the {machine}, THE EXACT SAME machine as in "
    "the verified reference photo. Preserve its real proportions, variant, "
    "configuration, component count, markings, and distinctive details with "
    "museum-catalogue accuracy. {view_direction} "
    "{detail_direction}"
    "Restored museum condition on a seamless PURE WHITE studio background "
    "(clean bright white, never gray, never off-white), soft even lighting, "
    "ultra crisp and photorealistic, with only a subtle soft ground shadow. "
    "ABSOLUTELY NO text, NO lettering, NO labels, NO watermark anywhere in "
    "the image. No people, no display stand, no dramatic environment. Neutral "
    "engineering-documentary presentation, never a toy, illustration, or game render."
)


def _studio_prompt(machine: str, view_plan: dict, detail_focus: str) -> str:
    """Build one historically locked prompt for a deliberate view role."""
    detail_direction = ""
    if view_plan.get("role") == "engineering_detail":
        focus = (detail_focus or "overall machine geometry").strip()
        detail_direction = f"VERIFIED DETAIL FOCUS: {focus}. "
    return _STUDIO_PROMPT.format(
        machine=machine,
        view_direction=view_plan["direction"],
        detail_direction=detail_direction,
    )

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_COMMONS_UA = {"User-Agent": "StoryEngine/1.0 (nativestates.ai; media research)"}

# Wikimedia politeness: ONE throttled gateway for every wikimedia.org request
# (API + file fetches). Bursts of anonymous requests got both the VPS and the
# dev machine 429/403-limited mid-run — pace them and honor Retry-After.
_WM_MIN_INTERVAL = 1.5
_wm_lock: Optional["asyncio.Lock"] = None
_wm_last = 0.0

# --- authenticated Wikimedia session (C5) -------------------------------------
#
# Anonymous datacenter-IP traffic is what got the VPS 429/403-jailed live. A
# classic MediaWiki bot password (Special:BotPasswords) logged in once per
# process gets materially better rate treatment. Read the same way every other
# module in this backend reads env (os.getenv — there is no central
# config.py/settings module in this codebase to route through instead).
WIKIMEDIA_BOT_USER = os.getenv("WIKIMEDIA_BOT_USER")
WIKIMEDIA_BOT_PASSWORD = os.getenv("WIKIMEDIA_BOT_PASSWORD")

# VERIFIED LIVE (scratchpad/wm_login_test.py, 2026-07-22): a bot-password
# login sets a WIKI-SCOPED session cookie (e.g. `commonswikiSession` on
# commons.wikimedia.org), not a shared `.wikimedia.org` CentralAuth cookie —
# logging in on commons.wikimedia.org does NOT authenticate subsequent calls
# to en.wikipedia.org (userinfo came back anonymous with only the commons
# login). So each host this module calls needs its OWN login call — but
# httpx's cookie jar is domain-scoped, so ONE shared AsyncClient can hold
# both hosts' session cookies at once; no need for separate client objects.
_WM_LOGIN_HOSTS = (_COMMONS_API, _WIKIPEDIA_API)

_wm_auth_client: Optional[httpx.AsyncClient] = None
_wm_auth_init_lock: Optional["asyncio.Lock"] = None
_wm_auth_ready = False        # True once every host in _WM_LOGIN_HOSTS is logged in
_wm_auth_init_done = False    # True once we've attempted init at least once


async def _wm_login_host(c: httpx.AsyncClient, api_url: str) -> bool:
    """One MediaWiki bot-password login (token fetch -> action=login) against
    `api_url`'s wiki, using session cookies already carried by `c`. Never
    raises; never logs the password — only the outcome."""
    try:
        r = await c.get(api_url, params={
            "action": "query", "meta": "tokens", "type": "login", "format": "json"})
        token = ((r.json().get("query") or {}).get("tokens") or {}).get("logintoken")
        if not token:
            return False
        r2 = await c.post(api_url, data={
            "action": "login", "lgname": WIKIMEDIA_BOT_USER,
            "lgpassword": WIKIMEDIA_BOT_PASSWORD, "lgtoken": token,
            "format": "json"})
        return ((r2.json().get("login") or {}).get("result") or "") == "Success"
    except Exception:  # noqa: BLE001 — login is best-effort, anonymous fallback covers it
        return False


async def _get_wm_auth_client() -> Optional[httpx.AsyncClient]:
    """Lazily create ONE process-wide authenticated httpx.AsyncClient for
    Wikimedia calls (cookies persist across the process lifetime), logged in
    separately to every host in _WM_LOGIN_HOSTS. Returns None (anonymous
    fallback via the caller's own client) when creds are absent, or when
    login failed — logged ONCE here, never retried on every call so a bad
    password can't turn into a login-endpoint hammering loop."""
    global _wm_auth_client, _wm_auth_init_lock, _wm_auth_ready, _wm_auth_init_done
    if not WIKIMEDIA_BOT_USER or not WIKIMEDIA_BOT_PASSWORD:
        return None
    if _wm_auth_init_done:
        return _wm_auth_client if _wm_auth_ready else None

    import asyncio
    if _wm_auth_init_lock is None:
        _wm_auth_init_lock = asyncio.Lock()
    async with _wm_auth_init_lock:
        if _wm_auth_init_done:  # another task finished init while we waited
            return _wm_auth_client if _wm_auth_ready else None
        client = httpx.AsyncClient(timeout=30.0, headers=_COMMONS_UA)
        oks = [await _wm_login_host(client, host) for host in _WM_LOGIN_HOSTS]
        if all(oks):
            _wm_auth_client = client
            _wm_auth_ready = True
            _logger.info("wikimedia bot session established as %s", WIKIMEDIA_BOT_USER)
        else:
            await client.aclose()
            _wm_auth_ready = False
            _logger.warning(
                "wikimedia bot login failed for one or more Wikimedia hosts "
                "— falling back to anonymous Wikimedia access")
        _wm_auth_init_done = True
        return _wm_auth_client if _wm_auth_ready else None


async def _wm_relogin() -> bool:
    """Re-run login on the SAME shared client (session silently expired —
    surfaced via assertuserfailed, see _wm_get). Never tears down/rebuilds
    the client, only re-authenticates it."""
    global _wm_auth_ready
    if _wm_auth_client is None:
        return False
    oks = [await _wm_login_host(_wm_auth_client, host) for host in _WM_LOGIN_HOSTS]
    _wm_auth_ready = all(oks)
    if _wm_auth_ready:
        _logger.info("wikimedia bot session re-established as %s", WIKIMEDIA_BOT_USER)
    else:
        _logger.warning("wikimedia bot re-login failed — falling back to anonymous access")
    return _wm_auth_ready


def _add_assert_user(kwargs: dict, url: str) -> dict:
    """Add assert=user to authenticated MediaWiki API calls only (api.php) —
    raw file fetches (upload.wikimedia.org, /thumb/ URLs) aren't MediaWiki
    actions and don't accept the param."""
    if "api.php" not in url:
        return kwargs
    params = dict(kwargs.get("params") or {})
    params.setdefault("assert", "user")
    new_kwargs = dict(kwargs)
    new_kwargs["params"] = params
    return new_kwargs


def _is_assertuserfailed(r: httpx.Response) -> bool:
    """Did this API response carry the assertuserfailed error code (session
    silently expired mid-process)? Best-effort — never raises on a non-JSON
    response (raw file fetch, or a transport-level error page)."""
    try:
        if "json" not in (r.headers.get("content-type") or ""):
            return False
        return ((r.json().get("error") or {}).get("code")) == "assertuserfailed"
    except Exception:  # noqa: BLE001
        return False


async def _wm_get(c: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """Throttled, retrying GET for any wikimedia.org URL (API or file fetch).

    `c` is the caller's own httpx.AsyncClient, kept for signature stability.
    When WIKIMEDIA_BOT_USER/WIKIMEDIA_BOT_PASSWORD are set and the shared
    authenticated session is live (see _get_wm_auth_client), `c` is IGNORED —
    every call instead routes through the one shared, logged-in client, since
    authenticated requests get materially better rate treatment than
    anonymous datacenter-IP traffic (the anonymous fallback below is exactly
    what got the VPS 429/403-jailed live). Falls back to `c` (anonymous, prior
    behavior unchanged) when creds are absent or the bot login failed
    (logged once by _get_wm_auth_client, not repeated here).

    Keeps the existing 1.5s politeness throttle + Retry-After handling
    unchanged for both paths. When authenticated, api.php calls get
    assert=user so a silently-expired session surfaces as an
    `assertuserfailed` API error instead of quietly degrading to anonymous
    treatment — caught here, triggers ONE re-login + retry before falling
    through to the normal 429/403 handling for that attempt.
    """
    import asyncio
    import time

    global _wm_lock, _wm_last
    if _wm_lock is None:
        _wm_lock = asyncio.Lock()

    auth_client = await _get_wm_auth_client()
    active = auth_client if auth_client is not None else c
    call_kwargs = _add_assert_user(kwargs, url) if auth_client is not None else kwargs

    relogin_used = False
    r = None
    for attempt in range(4):
        async with _wm_lock:
            wait = _WM_MIN_INTERVAL - (time.monotonic() - _wm_last)
            if wait > 0:
                await asyncio.sleep(wait)
            _wm_last = time.monotonic()
        r = await active.get(url, **call_kwargs)
        if auth_client is not None and not relogin_used and _is_assertuserfailed(r):
            relogin_used = True
            if await _wm_relogin():
                continue  # session refreshed — retry this same attempt
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


_THUMB_WIDTH_LADDER = (1600, 1280, 1024, 800, 640)


def _file_title_to_key(title: str) -> str:
    """Canonical match key for a Commons/Wikipedia File: title — strips the
    namespace prefix and normalizes spaces/underscores (MediaWiki treats them
    as equivalent and its API responses commonly echo titles back with
    spaces even when the request used underscores), so a batched imageinfo
    response's ``page['title']`` reliably maps back to the filename a caller
    asked about. Best-effort normalization, not full MediaWiki title-
    normalization (no case-folding beyond what callers already do)."""
    t = title or ""
    if t.lower().startswith("file:"):
        t = t[5:]
    return t.replace(" ", "_")


async def _api_issued_thumbs_batch(c: httpx.AsyncClient, raw_urls: list) -> dict:
    """Batched sibling of _api_issued_thumb (C3b): resolve MANY raw
    upload.wikimedia URLs to API-issued /thumb/ URLs in a handful of calls
    instead of one call per file per width rung. A burst of per-file
    Wikimedia calls mid-generation is exactly what triggered live rate-limit
    cooldowns on the VPS.

    MediaWiki's imageinfo query accepts up to 50 File: titles per request.
    Walks the SAME descending width ladder as the single-file path
    (_THUMB_WIDTH_LADDER), one batched call per rung, but at each rung only
    re-queries the titles STILL unresolved (raw-echoed) at the previous rung
    — so a whole candidate set typically resolves in ladder-length-many
    calls total, not ladder-length * file-count.

    LAST RUNG (dynamic, per file — see _api_issued_thumb's docstring for
    why): the true-size lookup (iiprop=size) is ALSO batched (50 titles per
    call), then files sharing the same computed target width are re-queried
    together.

    Returns ``{raw_url: thumb_url_or_None}``, one entry per input url."""
    from urllib.parse import unquote

    out: dict = {}
    fname_to_urls: dict = {}  # canonical key -> [raw_url, ...]
    for u in raw_urls:
        out.setdefault(u, None)
        try:
            fname = unquote(u.rsplit("/", 1)[1])
        except Exception:  # noqa: BLE001
            continue
        key = _file_title_to_key(fname)
        fname_to_urls.setdefault(key, []).append((u, fname))

    if not fname_to_urls:
        return out

    async def _query_at(keys: list, params_extra: dict) -> dict:
        """One or more batched imageinfo calls (chunks of 50 titles) for
        `keys`. Returns {key: imageinfo_dict} for whichever keys the API
        actually answered.

        DEMUX: a multi-title response's page titles are MediaWiki-NORMALIZED
        (e.g. first-letter capitalization: "File:xb-35_test.jpg" comes back
        as "File:Xb-35 test.jpg"), so matching them back to what WE asked
        for uses the API's own answer key first — every query response
        carries ``query.normalized`` ([{from, to}, ...]) describing exactly
        how each requested title was rewritten, and ``query.redirects``
        the same way when a File: title redirects. Only a page title absent
        from both maps (echoed verbatim) falls back to the
        _file_title_to_key heuristic."""
        resolved: dict = {}
        key_list = list(keys)
        for start in range(0, len(key_list), 50):
            chunk = key_list[start:start + 50]
            req_title_to_key = {
                f"File:{fname_to_urls[k][0][1]}": k for k in chunk}
            titles = "|".join(req_title_to_key.keys())
            r = await _wm_get(c, _COMMONS_API, params={
                "action": "query", "titles": titles,
                "prop": "imageinfo", "format": "json", **params_extra})
            query = (r.json().get("query") or {})
            # MediaWiki's own answer key: requested title -> response title.
            final_title_to_key: dict = {}
            for n in query.get("normalized") or []:
                frm, to = n.get("from"), n.get("to")
                if to and frm in req_title_to_key:
                    final_title_to_key[to] = req_title_to_key[frm]
            for rd in query.get("redirects") or []:
                frm, to = rd.get("from"), rd.get("to")
                if not to:
                    continue
                # A redirect's "from" is either an already-normalized title
                # or (if no normalization applied) the verbatim request.
                if frm in final_title_to_key:
                    final_title_to_key[to] = final_title_to_key[frm]
                elif frm in req_title_to_key:
                    final_title_to_key[to] = req_title_to_key[frm]
            pages = (query.get("pages") or {}).values()
            for p in pages:
                infos = p.get("imageinfo") or []
                if not infos:
                    continue
                # A single-title request always maps unambiguously to that
                # one key, title or no title (some MediaWiki-shaped
                # responses omit "title" on a page object) — this also
                # keeps the single-file caller (_api_issued_thumb) working
                # unchanged. A multi-title request demuxes by title:
                # normalized/redirect map first, verbatim-echo heuristic
                # only as the fallback.
                if len(chunk) == 1:
                    resolved[chunk[0]] = infos[0]
                    continue
                ptitle = p.get("title") or ""
                key = final_title_to_key.get(ptitle)
                if key is None:
                    key = _file_title_to_key(ptitle)
                    if key not in fname_to_urls:
                        continue
                resolved[key] = infos[0]
        return resolved

    pending = set(fname_to_urls.keys())
    for width in _THUMB_WIDTH_LADDER:
        if not pending:
            break
        answers = await _query_at(pending, {"iiprop": "url", "iiurlwidth": width})
        for key, ii in answers.items():
            t = ii.get("thumburl") or ""
            if t and "/thumb/" in t:
                pending.discard(key)
                for u, _fname in fname_to_urls[key]:
                    out[u] = t

    if pending:
        # Every static rung landed in the dead zone for these — batch the
        # true-size lookup, then group by the resulting dynamic target width
        # so files that share a width still resolve together.
        sizes = await _query_at(pending, {"iiprop": "size"})
        by_width: dict = {}
        for key in list(pending):
            w0 = (sizes.get(key) or {}).get("width") or 0
            if w0 <= 0:
                continue
            target = max(320, int(w0 * 0.6))
            by_width.setdefault(target, []).append(key)
        for target, keys in by_width.items():
            answers = await _query_at(keys, {"iiprop": "url", "iiurlwidth": target})
            for key, ii in answers.items():
                t = ii.get("thumburl") or ""
                if t and "/thumb/" in t:
                    pending.discard(key)
                    for u, _fname in fname_to_urls[key]:
                        out[u] = t

    return out


async def _api_issued_thumb(c: httpx.AsyncClient, raw_url: str) -> Optional[str]:
    """Turn a RAW upload.wikimedia URL into an API-ISSUED /thumb/ URL.

    The raw-file layer 403s cloud IPs; only thumb URLs the API itself has
    issued are reliably served (the request warms the CDN). MediaWiki also
    echoes the RAW url back — instead of issuing a /thumb/ — whenever the
    requested width sits close to the original's true width (common for
    archival scans ~1300-2000px wide: proven live on XB-35.jpg (w=1543),
    YB49-2_300.jpg (w=1468) and The_Convair_YB-60.jpg (w=1800), which all
    failed at both 1600 and width-1 but resolved cleanly at 1000). A single
    retry can still land in that dead zone, so walk a descending width
    ladder and take the first width that actually gets a /thumb/ issued.

    LAST RUNG (dynamic): an original ~640-1000px wide — old 1940s archival
    photos come small — can sit in the dead zone at EVERY static rung. If
    the whole ladder fails, ask the API for the file's true size and try
    ONE final width at 60% of the original (floor 320), comfortably below
    the refuse-to-thumb threshold for any original size.

    Single-file convenience wrapper: delegates to _api_issued_thumbs_batch
    (C3b) with a 1-element list so the ladder-walking logic exists in
    exactly one place."""
    try:
        result = await _api_issued_thumbs_batch(c, [raw_url])
        return result.get(raw_url)
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


# Shared across every Commons/article image filter below — a line sketch,
# map or insignia as an img2img reference makes the model invent the body
# (bit us on MBT-70), so drawings/flags/icons never qualify as a "real photo".
_NON_PHOTO_FILE_KEYWORDS = (
    "sketch", "drawing", "diagram", "blueprint", "map", "insignia", "logo",
    "emblem", "patch", "lego", "toy", "flag", "icon", "locator", "roundel",
    "crest", "seal", "coa_", "chart", "graph",
)


async def _resolve_article_title(c: httpx.AsyncClient, name: str) -> Optional[str]:
    """Does this name resolve (following redirects) to a real Wikipedia
    article? Returns the canonical title, or None."""
    try:
        r = await _wm_get(c, _WIKIPEDIA_API, params={
            "action": "query", "titles": name, "redirects": 1, "format": "json"})
        r.raise_for_status()
        pages = ((r.json().get("query") or {}).get("pages") or {}).values()
        for p in pages:
            if p.get("pageid") and "missing" not in p:
                return p.get("title") or name
    except Exception:  # noqa: BLE001
        pass
    return None


async def find_article_images(names: list, limit: int = 5) -> list[dict]:
    """LAYER 1.5 reference source: every real photo embedded in the machine's
    OWN Wikipedia article body — not just its lead image (find_wikipedia_lead_
    images, LAYER 1). A rare prototype's lead image is sometimes a diagram or
    simply missing, but the article usually embeds one or more period
    photographs further down the page. Trusted with the same provenance
    guarantee as LAYER 1: the file appears ON the machine's own article, so
    there's no search ambiguity to resolve. Tries the designation then each
    alias, uses the FIRST name that resolves to a real article, and returns
    every qualifying photo from THAT article (best-effort, single article —
    not a merge across names, so a stale alias article can't smuggle in a
    lookalike's photos)."""
    out: list[dict] = []
    seen: set = set()
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_COMMONS_UA) as c:
            title = None
            for name in [n for n in names if n][:4]:
                title = await _resolve_article_title(c, name)
                if title:
                    break
            if not title:
                return []
            r = await _wm_get(c, _WIKIPEDIA_API, params={
                "action": "query", "titles": title,
                "generator": "images", "gimlimit": 40,
                "prop": "imageinfo", "iiprop": "url|size", "format": "json"})
            r.raise_for_status()
            pages = ((r.json().get("query") or {}).get("pages") or {}).values()
            # First pass: collect every eligible (raw_url, file_title)
            # candidate with the SAME filters as before, but don't resolve
            # thumbs yet — resolving them ALL in one batched call (C3b)
            # instead of one call per file per width rung is the whole
            # point; up to 40 candidates here would otherwise cost up to
            # 40 * len(_THUMB_WIDTH_LADDER) individual requests.
            candidates: list[tuple] = []  # (raw_url, file_title)
            for p in pages:
                ftitle = p.get("title") or ""
                low = ftitle.lower()
                if not low.endswith((".jpg", ".jpeg", ".png")):
                    continue  # drop .svg maps/flags/coats-of-arms outright
                if any(b in low for b in _NON_PHOTO_FILE_KEYWORDS):
                    continue
                for ii in p.get("imageinfo") or []:
                    w, h = ii.get("width") or 0, ii.get("height") or 0
                    if w < 500 or h < 300:
                        continue  # icon/thumbnail-sized, not a real photo
                    raw = ii.get("url") or ""
                    if not raw or raw in seen:
                        continue
                    seen.add(raw)
                    candidates.append((raw, ftitle))
            thumbs = await _api_issued_thumbs_batch(c, [raw for raw, _ in candidates])
            for raw, ftitle in candidates:
                thumb = thumbs.get(raw)
                if not thumb:
                    continue
                out.append({"url": thumb, "page": title, "file_title": ftitle})
                if len(out) >= limit:
                    break
    except Exception:  # noqa: BLE001
        pass
    return out[:limit]


async def find_commons_photos(query: str, limit: int = 3) -> list[dict]:
    """Real photographs of the machine from Wikimedia Commons (keyless API).
    Returns up to `limit` candidates ({"url", "title"}, ~1600px), best first.
    The title is returned (not just the URL) so the caller can check whether
    the file name itself carries the machine's designation token — that
    upgrades an otherwise-untrusted search hit to trusted provenance."""
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_COMMONS_UA) as c:
            r = await _wm_get(c, _COMMONS_API, params={
                "action": "query", "list": "search", "srsearch": query,
                "srnamespace": 6, "srlimit": 8, "format": "json"})
            r.raise_for_status()
            hits = (r.json().get("query") or {}).get("search") or []
            # Photographs / full renderings only — a line sketch as an img2img
            # reference makes the model invent the body (bit us on MBT-70).
            titles = [h["title"] for h in hits
                      if h.get("title", "").lower().endswith((".jpg", ".jpeg", ".png"))
                      and not any(b in h.get("title", "").lower()
                                  for b in _NON_PHOTO_FILE_KEYWORDS)]
            if not titles:
                return []
            r2 = await _wm_get(c, _COMMONS_API, params={
                "action": "query", "titles": "|".join(titles[:6]),
                "prop": "imageinfo", "iiprop": "url|size",
                "iiurlwidth": 1600, "format": "json"})
            r2.raise_for_status()
            pages = ((r2.json().get("query") or {}).get("pages") or {}).values()
            entries: list[dict] = []
            needs_batch: list[str] = []
            for p in pages:
                ptitle = p.get("title") or ""
                for ii in p.get("imageinfo") or []:
                    w, h = ii.get("width") or 0, ii.get("height") or 0
                    if w < 500 or h < 300:
                        continue  # thumbnails/icons — too small to reference
                    url = ii.get("url") or ""
                    thumb = ii.get("thumburl") or ""
                    entries.append({"ptitle": ptitle, "url": url, "thumb": thumb})
                    # ONLY API-issued /thumb/ URLs are servable: the raw-file
                    # layer 403s cloud IPs, and hand-built thumb URLs for
                    # never-rendered sizes 403 too (the API request is what
                    # warms the CDN — proven live). For originals the width
                    # ladder doesn't clear, fall back to the batched resolver
                    # (C3b) — one call for every file still needing this
                    # instead of one call per file.
                    if (not thumb or thumb == url) and ptitle and url:
                        needs_batch.append(url)
            resolved = await _api_issued_thumbs_batch(c, needs_batch) if needs_batch else {}
            out: list[dict] = []
            for entry in entries:
                url, thumb = entry["url"], entry["thumb"]
                if (not thumb or thumb == url) and url:
                    thumb = resolved.get(url) or thumb
                if thumb and thumb != url and "/thumb/" in thumb:
                    out.append({"url": thumb, "title": entry["ptitle"]})
            return out[:limit]
    except Exception:  # noqa: BLE001 — reference lookup is best-effort
        return []


async def _host_reference(url: str, video_id: str, tenant_id: str,
                          tag: str) -> Optional[str]:
    """Fetch the Commons photo OURSELVES (proper User-Agent — Wikimedia 403s
    Kie's fetcher on raw file URLs) and re-host it on our storage. The image
    client rewrites the stored Drive URL to the media proxy, so Kie always
    fetches references from US, never from Wikimedia.

    `tag` is an opaque, storage-path-safe label the caller picks to keep
    candidates distinct (e.g. "S03_1" for scene 3's second candidate at
    generation time, or "roster05_0" for the sixth roster machine's first
    candidate at prefetch time — see prefetch_roster_references).

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
                data, f"{video_id}/static/ref_{tag}.{ext}",
                "image/png" if ext == "png" else "image/jpeg", tenant_id)
        except Exception:  # noqa: BLE001
            if attempt < 2:
                await _asyncio.sleep(4 * (attempt + 1))
    return None


def _url_file_title(url: str) -> str:
    """Best-effort recovery of the real Commons/Wikipedia File: title from a
    Wikimedia URL, so a designation-token check can run against the actual
    filename even for sources (like a Wikipedia lead image) that don't
    otherwise carry a file title. A /thumb/ URL's true filename is the
    second-to-last path segment (``.../thumb/a/b/XB-35.jpg/1024px-XB-35.jpg``
    — the last segment is the WIDTH-prefixed thumb name, not the file); a
    raw (non-thumb) URL's filename is simply the last segment."""
    from urllib.parse import unquote

    try:
        parts = (url or "").rstrip("/").split("/")
        if not parts:
            return ""
        if "/thumb/" in url and len(parts) >= 2:
            return unquote(parts[-2])
        return unquote(parts[-1])
    except Exception:  # noqa: BLE001
        return ""


async def _gather_reference_candidates(machine: str, aliases: Optional[list],
                                       search_query: Optional[str]) -> list:
    """The SAME layered candidate chain _one_scene has always used, factored
    out so prefetch_roster_references (C3, roster-time prefetch) can run the
    identical lookup without duplicating it: LAYER 1 (find_wikipedia_lead_
    images), LAYER 1.5 (find_article_images — other real photos on that same
    article), LAYER 2 (find_commons_photos, trust-promoted by a designation
    token in the file title).

    C2f fix: the designation-token filename check (_commons_title_matches)
    now applies to EVERY source, not just Commons search hits — a lead image
    or article image whose own FILENAME carries the machine's designation
    (e.g. XB-35.jpg found on the generic "Northrop YB-35" article, whose
    page title alone doesn't name the XB-35 variant) is promoted to trusted
    even when the page-title check misses. The returned list is then sorted
    token-matched-first, then remaining-trusted, then untrusted (stable sort
    — ties keep their original discovery order), so a genuine token match
    (e.g. "File:Boeing_XB-52_in_flight.jpg" for the XB-52) is always tried
    BEFORE a same-family lookalike (a modern B-52H photo) that only earned
    trust from a loose page-title/word overlap.

    Returns ``[(url, trusted), ...]``, de-duplicated by url."""
    names = [machine] + list(aliases or [])
    entries: list[dict] = []  # {"url", "trusted", "token"}
    seen: set = set()

    def _add(url: str, trusted: bool, title_hint: Optional[str] = None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        token = _commons_title_matches(
            machine, aliases, title_hint or _url_file_title(url))
        entries.append({"url": url, "trusted": trusted or token, "token": token})

    wiki = await find_wikipedia_lead_images(names)
    for w in wiki:
        # 'trusted' provenance only holds when the article title names OUR
        # machine — a fuzzy search that landed on a lookalike's article gets
        # demoted to the strict vision check instead of a free pass (unless
        # the file's own name carries the designation token — see _add).
        page_trusted = w["trusted"] and _page_matches(machine, aliases, w.get("page", ""))
        _add(w["url"], page_trusted)

    # LAYER 1.5: other real photos on that same article — trusted for the
    # same reason as the lead image (it's on the machine's own page).
    for a in await find_article_images(names):
        _add(a["url"], True, a.get("file_title"))

    # LAYER 2: Commons search. A hit whose FILE TITLE itself carries the
    # machine's designation token (e.g. "xb35" in "Northrop_XB-35_11-300.jpg")
    # is promoted to trusted — the filename ties it to the machine
    # independent of the vision model's ability to name an obscure prototype
    # by sight.
    if search_query:
        for cp in await find_commons_photos(search_query):
            _add(cp["url"], False, cp.get("title"))
    if not entries and machine:
        for cp in await find_commons_photos(machine):
            _add(cp["url"], False, cp.get("title"))

    entries.sort(key=lambda e: 0 if e["token"] else (1 if e["trusted"] else 2))
    return [(e["url"], e["trusted"]) for e in entries]


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


def _commons_title_matches(machine: str, aliases: Optional[list], title: str) -> bool:
    """Does this Commons file title itself carry the machine's designation
    token? (e.g. 'XB-35' -> 'xb35' inside 'File:Northrop_XB-35_11-300.jpg' ->
    normalized 'xb3511300jpg'.) A hit means the file is almost certainly OUR
    machine, not just a keyword-matched lookalike Commons' fuzzy search
    turned up — that's enough provenance to promote the candidate to
    trusted=True instead of the default untrusted Commons-search bucket.
    Short/no-digit tokens are excluded (>=3 chars) — a bare 2-letter token
    would false-match almost any file name."""
    norm_title = re.sub(r"[^a-z0-9]", "", (title or "").lower())
    if not norm_title:
        return False
    for name in [machine] + list(aliases or []):
        tok = _designation_token(name)
        if tok and len(tok) >= 3 and tok in norm_title:
            return True
    return False


# Hard-reject signals in the model's reply. Matched as WHOLE WORDS (\b...\b)
# — a naive substring check false-matched "person" inside "supersonic" live
# (S19 Convair B-58, which cost S20 XB-70 an extra candidate too), silently
# rejecting a genuinely correct photo.
_FLAT_MEDIA_KEYWORDS = ("drawing", "sketch", "diagram", "blueprint",
                        "scale model", "schematic")
_WRONG_CONTENT_KEYWORDS = ("interior", "cockpit", "person", "portrait", "map",
                          "insignia", "document", "text page")

# C2h render-QA hard rejects: our own render is BY DESIGN a clean studio
# illustration, not a "real photograph" — so unlike _FLAT_MEDIA_KEYWORDS/
# _WRONG_CONTENT_KEYWORDS above (which judge candidate REFERENCE photos),
# _render_matches_reference only hard-rejects a reply saying the render
# itself is missing/not-an-aircraft, never "rendered"/"illustration"/"model".
_RENDER_EMPTY_KEYWORDS = ("empty", "blank", "not an aircraft")


def _has_keyword(text: str, keywords: tuple) -> bool:
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in keywords)


async def _download_image_b64(image_url: str) -> Optional[tuple]:
    """Fetch `image_url` ourselves and return (media_type, base64_data), or
    None on any download/oversize failure — treated by the caller as a
    failed attempt (same fail-closed bucket as a raised exception), never as
    a silent pass. Anthropic's per-image limit is ~5MB; a payload over
    ~4.5MB is rejected here rather than risking a provider-side size error
    (no image-processing deps added).

    C2h: factored out of _vision_confirms (C2g) so _render_matches_reference
    can reuse the exact same self-fetch-then-base64 pattern for BOTH images
    it sends (the reference photo and our own render) instead of duplicating
    it."""
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_COMMONS_UA,
                                     follow_redirects=True) as c:
            r = await c.get(image_url)
    except Exception:  # noqa: BLE001 — network failure downloading the candidate
        _logger.warning("_download_image_b64: download failed for %s", image_url)
        return None
    if r.status_code != 200:
        _logger.warning("_download_image_b64: download HTTP %s for %s",
                        r.status_code, image_url)
        return None
    data = r.content
    if not data:
        return None
    if len(data) > 4_500_000:
        _logger.warning("_download_image_b64: oversize download (%d bytes) for %s",
                        len(data), image_url)
        return None
    media_type = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if media_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        media_type = "image/jpeg"
    return media_type, base64.b64encode(data).decode("ascii")


async def _vision_confirms(tenant_id: str, image_url: str, machine: str,
                           aliases: Optional[list] = None,
                           trusted_source: bool = False) -> bool:
    """Vision sanity check: is this image consistent with being `machine` — a
    real photograph (or full-scale rendering) of that SPECIFIC designation/
    variant, not a sketch, diagram, blueprint, scale model, or a different
    (even closely related) variant of the same family?

    SUPPLIES the machine name/aliases and asks a direct YES/NO instead of the
    old bar of the model spontaneously NAMING the machine unprompted — nobody
    can name an obscure never-built prototype by sight, so that old bar
    rejected every genuine Commons photo of XB-35/YB-49/YB-35/YB-60.

    TRUSTED candidates (provenance: the photo appears on the machine's own
    Wikipedia article, or its own filename carries the designation token —
    see _gather_reference_candidates) do NOT need the model to confirm
    identification at all — provenance outranks a weak model's guess (a
    haiku-tier vision model misidentified genuine XB-15/B-21 lead-image
    photos as "a B-17"/"a B-2" live). Hard rejections (interiors, people/
    portraits, maps, flat/non-photo media) still apply to trusted candidates
    — provenance only excuses not being able to name it by sight, never a
    wrong-media or clearly-wrong-content image. UNTRUSTED candidates still
    require an explicit YES, and the question is deliberately strict about
    VARIANT — a modern B-52H photo must NOT pass as the prototype XB-52.

    FAILS CLOSED on transport failure: a request that raises or comes back
    with no usable reply text is retried ONCE, then treated as REJECTED (not
    verified) — an HTTP-level failure (23/23 URL-source calls 400'd live)
    must never silently become "verified".

    C2g fix: this used to hand the model a URL-source image block built from
    `_kie_fetchable_url(image_url)` — called WITHOUT tenant_id, so it minted
    no auth token and the media proxy 401'd; even a correctly-signed proxy
    URL still 404s here because a freshly `_host_reference`d candidate only
    exists in storage (and later static_reference_cache), neither of which
    routes/media.py's `_ALLOWLIST_SQL` matches. Anthropic returned a 400
    ("Unable to download the file"), which `_ask_once` couldn't distinguish
    from an empty reply, so EVERY first-time hosted candidate silently
    failed closed. Fixed by downloading the image bytes OURSELVES and
    inlining them as base64 — the same self-fetch pattern `_host_reference`
    already uses to avoid depending on a third party (or our own proxy)
    being fetchable. Confirmed live: the Kie-gateway Claude endpoint
    (api.kie.ai/claude/v1/messages) already accepts this same base64 block
    shape elsewhere (shared/clients/vision_client.py's `_claude_blocks`), so
    both branches below share one content list."""
    from vault import get_secret

    alias_txt = ""
    if aliases:
        alias_txt = " (also known as " + ", ".join(str(a) for a in aliases if a) + ")"
    source_hint = (
        "This photo comes from the machine's own Wikipedia article, which is "
        "strong provenance that it depicts this exact machine. "
        if trusted_source else
        "This photo was found via general keyword search and needs "
        "independent confirmation. "
    )

    prompt_text = (
        f"We believe this image shows the {machine}{alias_txt}. "
        f"{source_hint}"
        "Answer on one line: first word YES or NO, then one short "
        "reason. YES only if the image is consistent with being a real "
        "photograph (or full-scale museum/factory rendering) of THIS "
        "SPECIFIC designation/variant. A DIFFERENT variant of the same "
        "aircraft/vehicle family counts as NO — for example, a later "
        "production model is NOT the same as an earlier experimental "
        "prototype designation, unless that variant is explicitly one of "
        "the aliases listed above. NO if it shows a different variant, an "
        "unrelated vehicle, is not a real photo (a drawing/sketch/diagram/"
        "blueprint/schematic/scale model), or primarily shows an interior, "
        "cockpit, a person or portrait, a map, insignia, or a document/"
        "text page."
    )

    async def _ask_once() -> Optional[str]:
        """One round-trip: download the candidate image fresh, then ask the
        vision model. Returns the lowercased reply text (possibly empty —
        including when the download itself failed, which the retry loop
        treats identically to a transport exception), or None specifically
        when NO provider key is configured at all — a workspace config gap,
        not a transport symptom, so the caller treats it differently
        (unchanged fail-open, since there's no live evidence this ever fires
        in practice and retrying can't help a missing key)."""
        img = await _download_image_b64(image_url)
        if img is None:
            return ""  # download/size failure this attempt — caller retries
        media_type, b64_data = img
        content = [
            {"type": "text", "text": prompt_text},
            {"type": "image", "source": {"type": "base64",
             "media_type": media_type, "data": b64_data}},
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
                    json={"model": CLAUDE_MODELS["anthropic"]["smart"], "max_tokens": 80,
                          "messages": [{"role": "user", "content": content}]},
                )
            else:
                key = await get_secret("kie_ai_api_key", tenant_id)
                if not key:
                    return None
                import os
                kie_claude_url = os.getenv(
                    "KIE_CLAUDE_BASE_URL", "https://api.kie.ai/claude"
                ).rstrip("/") + "/v1/messages"
                r = await c.post(
                    kie_claude_url,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json={"model": CLAUDE_MODELS["kie"]["smart"], "max_tokens": 80,
                          "messages": [{"role": "user", "content": content}]},
                )
        if r.status_code != 200:
            # A non-200 model-API response is a failed attempt, never parsed
            # as if it were an empty-but-successful answer (the C2f bug this
            # continues to guard against — 23/23 URL-source calls 400'd and
            # were silently read as "no reply text").
            _logger.warning("_vision_confirms: model API HTTP %s", r.status_code)
            return ""
        body = r.json()
        return " ".join(b.get("text", "") for b in body.get("content", [])
                        if b.get("type") == "text").strip().lower()

    txt: Optional[str] = None
    no_key = False
    for attempt in range(2):
        try:
            result = await _ask_once()
        except Exception:  # noqa: BLE001 — transport failure: retry once, then fail closed
            result = ""
        if result is None:
            no_key = True
            txt = None
            break
        txt = result
        if txt:
            break
        # empty reply — loop again for the one allowed retry

    if no_key:
        return True  # config gap, not a transport failure — unchanged behavior
    if not txt:
        # Every attempt raised, failed to download, or came back empty —
        # FAIL CLOSED: this candidate is treated as unverified/rejected (the
        # caller tries the next candidate; worst case the scene blocks,
        # which is visible and recoverable), never silently promoted to
        # "verified".
        return False

    # Hard rejections (word-boundary matched) apply UNIFORMLY to trusted and
    # untrusted candidates — provenance never excuses a flat/non-photo image
    # or clearly wrong content, it only excuses not being able to name the
    # machine by sight.
    is_flat = _has_keyword(txt, _FLAT_MEDIA_KEYWORDS)
    wrong = _has_keyword(txt, _WRONG_CONTENT_KEYWORDS)
    if trusted_source:
        return not is_flat and not wrong
    said_yes = bool(re.match(r"^\W*yes\b", txt))
    return said_yes and not is_flat and not wrong


async def _render_matches_reference(tenant_id: str, render_url: str, ref_url: str,
                                    machine: str, aliases: Optional[list] = None) -> bool:
    """C2h post-generation render-QA: does OUR OWN studio render still show
    the SAME machine as the verified reference photo it was image-to-image'd
    from? This is a DIFFERENT question from `_vision_confirms` (which judges
    whether a candidate REFERENCE photo is a real, correctly-identified photo
    of the machine) — `_vision_confirms`'s wording demands "a real photograph"
    and hard-rejects "scale model"/flat-media replies, which is right for a
    candidate reference but wrong for OUR render: `generate_static_images_
    for_video`'s `_STUDIO_PROMPT` deliberately asks for a clean white-studio
    product illustration, which is not, and was never meant to be, "a real
    photograph". Feeding that render through `_vision_confirms` reads as
    CGI/render/model to the vision model -> NO -> hard-reject on every single
    generation (PROVEN live: 6 scenes, 12 generations, both attempts each
    rejected, 100% of renders failed).

    Sends TWO images in one message — the verified reference photo FIRST,
    then our render SECOND — and asks only whether they show the SAME
    aircraft type/configuration (shape, wing form, engine count/type, tail
    configuration); livery/markings/background/style differences, and the
    render simply LOOKING like a clean render, are explicitly told to be
    fine. Only a hard-reject if the reply says the render itself is empty/
    blank/not an aircraft (`_RENDER_EMPTY_KEYWORDS`) — no flat-media/scale-
    model rejects here, since the render IS a render by design.

    FAILS CLOSED on transport failure exactly like `_vision_confirms`: one
    retry, then treated as REJECTED (not verified) — never silently promoted
    to "matches" on a network/API failure. Keyless carve-out unchanged (no
    provider key configured on the tenant is a config gap, not a transport
    symptom, so it fails OPEN like `_vision_confirms` does)."""
    from vault import get_secret

    alias_txt = ""
    if aliases:
        alias_txt = " (also known as " + ", ".join(str(a) for a in aliases if a) + ")"

    prompt_text = (
        f"Image 1 is a verified real photograph of the {machine}{alias_txt}. "
        "Image 2 is our own clean studio illustration of the same machine, "
        "prepared for a documentary. "
        "Answer on one line: first word YES or NO, then one short reason. "
        "YES if image 2 depicts the SAME aircraft type/configuration as "
        "image 1 — same overall shape, wing form, engine count/type, and "
        "tail configuration (small liveries/markings/background/style "
        "differences are fine; it is EXPECTED that image 2 looks like a "
        "clean render, that is not a flaw). NO if image 2 shows a different "
        "aircraft type/variant or the wrong configuration, or if image 2 is "
        "empty, blank, or not an aircraft at all."
    )

    async def _ask_once() -> Optional[str]:
        """One round-trip: download BOTH images fresh (reference, then
        render), then ask the vision model. Returns the lowercased reply
        text (possibly empty — including when either download failed, which
        the retry loop treats identically to a transport exception), or None
        specifically when NO provider key is configured at all (unchanged
        fail-open, same reasoning as `_vision_confirms`)."""
        ref_img = await _download_image_b64(ref_url)
        render_img = await _download_image_b64(render_url)
        if ref_img is None or render_img is None:
            return ""  # download failure this attempt — caller retries
        ref_type, ref_b64 = ref_img
        render_type, render_b64 = render_img
        content = [
            {"type": "text", "text": prompt_text},
            {"type": "image", "source": {"type": "base64",
             "media_type": ref_type, "data": ref_b64}},
            {"type": "image", "source": {"type": "base64",
             "media_type": render_type, "data": render_b64}},
        ]

        # DIRECT Anthropic first — same reasoning as _vision_confirms (the
        # Kie gateway injects tool configuration that derails the reply).
        akey = await get_secret("anthropic_api_key", tenant_id)
        async with httpx.AsyncClient(timeout=60.0) as c:
            if akey:
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": akey,
                             "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                    json={"model": CLAUDE_MODELS["anthropic"]["smart"], "max_tokens": 80,
                          "messages": [{"role": "user", "content": content}]},
                )
            else:
                key = await get_secret("kie_ai_api_key", tenant_id)
                if not key:
                    return None
                kie_claude_url = os.getenv(
                    "KIE_CLAUDE_BASE_URL", "https://api.kie.ai/claude"
                ).rstrip("/") + "/v1/messages"
                r = await c.post(
                    kie_claude_url,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json={"model": CLAUDE_MODELS["kie"]["smart"], "max_tokens": 80,
                          "messages": [{"role": "user", "content": content}]},
                )
        if r.status_code != 200:
            # A non-200 model-API response is a failed attempt, never parsed
            # as if it were an empty-but-successful answer (same C2f/C2g
            # guard _vision_confirms applies).
            _logger.warning("_render_matches_reference: model API HTTP %s", r.status_code)
            return ""
        body = r.json()
        return " ".join(b.get("text", "") for b in body.get("content", [])
                        if b.get("type") == "text").strip().lower()

    txt: Optional[str] = None
    no_key = False
    for attempt in range(2):
        try:
            result = await _ask_once()
        except Exception:  # noqa: BLE001 — transport failure: retry once, then fail closed
            result = ""
        if result is None:
            no_key = True
            txt = None
            break
        txt = result
        if txt:
            break
        # empty reply — loop again for the one allowed retry

    if no_key:
        return True  # config gap, not a transport failure — unchanged behavior
    if not txt:
        # Every attempt raised, failed to download, or came back empty —
        # FAIL CLOSED: this render is treated as unverified/rejected (the
        # caller's own retry-with-a-stricter-prompt loop in _one_scene picks
        # up from there), never silently promoted to "matches".
        return False

    is_empty = _has_keyword(txt, _RENDER_EMPTY_KEYWORDS)
    said_yes = bool(re.match(r"^\W*yes\b", txt))
    return said_yes and not is_empty


async def _arbiter_confirms_render(tenant_id: str, render_url: str, ref_url: str,
                                   machine: str,
                                   aliases: Optional[list] = None) -> bool:
    """Automated tie-breaker for a DOUBLE `_render_matches_reference` reject.
    The pipeline runs unattended — no operator is in the loop to review a
    parked render — and the primary QA judge has a PROVEN systematic failure
    mode: on 2026-07-22 one prompt-wording bug rejected 12 correct paid
    renders in a row. A wording bug in ONE prompt won't correlate with a
    DIFFERENTLY-worded second judge, so this asks the same-machine question
    independently: its own framing (an audit second opinion, not a QA check)
    and its own answer vocabulary (MATCH/MISMATCH, not YES/NO — a parser or
    prompt bug around "yes" can't infect it).

    True = the rejection is overruled and the render ships (the caller marks
    it arbiter-approved in image_prompt for the audit trail). False = the
    rejection STANDS and the render is parked as qa_rejected.

    Deliberately DUPLICATES the two-image transport of
    `_render_matches_reference` rather than sharing it via refactor — same
    C2h precedent as `_vision_confirms` vs `_render_matches_reference`: each
    judgment owns its full path, so a change to one can never silently
    change the other's behavior.

    FAILS CLOSED everywhere, including the keyless case: an arbiter that
    can't actually look at the images must never overrule a rejection — the
    worst outcome of False is a parked render (recoverable), the worst
    outcome of a false True is a wrong machine SHIPPED in a video. (The
    keyless case is unreachable in practice anyway: with no provider key the
    primary judge already failed open, so a double-reject can't occur.)"""
    from vault import get_secret

    alias_txt = ""
    if aliases:
        alias_txt = " (also known as " + ", ".join(str(a) for a in aliases if a) + ")"

    prompt_text = (
        "You are auditing an automated documentary image pipeline. "
        f"Image 1 is a verified real photograph of the {machine}{alias_txt}. "
        "Image 2 is a clean studio illustration that an earlier automated "
        "check flagged as possibly showing the wrong machine — that check is "
        "sometimes wrong, so give a fresh, independent second opinion. "
        "Answer on one line: first word MATCH or MISMATCH, then one short "
        "reason. MATCH if image 2 shows the same machine type as image 1 — "
        "same overall shape, wing form, engine count and placement, and tail "
        "configuration. Style, background, livery, markings, and image 2 "
        "looking like a rendered illustration are all EXPECTED and must not "
        "count against it. MISMATCH only if image 2 shows a different "
        "machine type or variant, or is empty, blank, or shows no machine "
        "at all."
    )

    async def _ask_once() -> Optional[str]:
        ref_img = await _download_image_b64(ref_url)
        render_img = await _download_image_b64(render_url)
        if ref_img is None or render_img is None:
            return ""  # download failure this attempt — caller retries
        ref_type, ref_b64 = ref_img
        render_type, render_b64 = render_img
        content = [
            {"type": "text", "text": prompt_text},
            {"type": "image", "source": {"type": "base64",
             "media_type": ref_type, "data": ref_b64}},
            {"type": "image", "source": {"type": "base64",
             "media_type": render_type, "data": render_b64}},
        ]

        # DIRECT Anthropic first — same reasoning as _vision_confirms (the
        # Kie gateway injects tool configuration that derails the reply).
        akey = await get_secret("anthropic_api_key", tenant_id)
        async with httpx.AsyncClient(timeout=60.0) as c:
            if akey:
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": akey,
                             "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                    json={"model": CLAUDE_MODELS["anthropic"]["smart"], "max_tokens": 80,
                          "messages": [{"role": "user", "content": content}]},
                )
            else:
                key = await get_secret("kie_ai_api_key", tenant_id)
                if not key:
                    return None
                kie_claude_url = os.getenv(
                    "KIE_CLAUDE_BASE_URL", "https://api.kie.ai/claude"
                ).rstrip("/") + "/v1/messages"
                r = await c.post(
                    kie_claude_url,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json={"model": CLAUDE_MODELS["kie"]["smart"], "max_tokens": 80,
                          "messages": [{"role": "user", "content": content}]},
                )
        if r.status_code != 200:
            _logger.warning("_arbiter_confirms_render: model API HTTP %s", r.status_code)
            return ""
        body = r.json()
        return " ".join(b.get("text", "") for b in body.get("content", [])
                        if b.get("type") == "text").strip().lower()

    txt: Optional[str] = None
    for attempt in range(2):
        try:
            result = await _ask_once()
        except Exception:  # noqa: BLE001 — transport failure: retry once, then fail closed
            result = ""
        if result is None:
            # No provider key: fail CLOSED (see docstring — unlike the
            # primary judges, an arbiter that can't see must never overrule).
            return False
        txt = result
        if txt:
            break
        # empty reply — loop again for the one allowed retry

    if not txt:
        # Every attempt raised, failed to download, or came back empty —
        # FAIL CLOSED: the rejection stands and the render parks, never a
        # silent overrule on a network/API failure.
        return False

    is_empty = _has_keyword(txt, _RENDER_EMPTY_KEYWORDS)
    said_match = bool(re.match(r"^\W*match\b", txt))
    return said_match and not is_empty


async def _scene_subjects(tenant_id: str, scenes: list[dict],
                          research_payload: Optional[dict]) -> dict[int, dict]:
    """One Claude call -> grounded subject, title-card, and detail metadata."""
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
                "caption_specs": [
                    str(spec).strip()
                    for spec in (item.get("caption_specs") or [])
                    if str(spec).strip()
                ][:2],
                "detail_focus": str(
                    item.get("detail_focus") or "overall machine geometry"
                ).strip(),
                "search_query": str(item.get("search_query") or "").strip(),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def generate_static_images_for_video(video_id: str, tenant_id: str,
                                           progress=None,
                                           only_scenes: Optional[set] = None,
                                           section_contract: Optional[dict] = None) -> dict:
    """Create the static-documentary view set for every narration segment.

    The static analogue of generate_coverage_for_video: reads scripts, writes
    three ordered assets per scene (three-quarter, top-oblique, detail), all
    grounded in one verified reference and independently QA checked. A scene
    is render-ready with at least two approved views. Idempotent per scene —
    re-running replaces only that scene's static-documentary assets.
    """
    if section_contract is not None:
        density = section_contract.get("image_density")
        camera = section_contract.get("camera")
        animation = section_contract.get("animation")
        if (
            section_contract.get("render_mode") != "static_docu"
            or section_contract.get("image_source") != "generate"
            or not isinstance(density, dict)
            or density.get("mode") != "per_item"
            or density.get("target") != STATIC_VIEWS_TARGET
            or section_contract.get("expected_still_images") != STATIC_VIEWS_TARGET
            or section_contract.get("expected_animation_clips") != 0
            or not isinstance(camera, dict)
            or camera.get("mode") != "three_complementary_views"
            or not isinstance(animation, dict)
            or animation.get("enabled") is not False
            or animation.get("mode") != "ken_burns"
            or type(section_contract.get("exact_seconds")) is not int
            or section_contract["exact_seconds"] < 1
        ):
            raise ValueError("Unsupported static section production contract")

    def _p(msg):
        if progress:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001
                pass

    from shared.clients.image_client import ImageClient
    from vault import get_required_tenant_secret

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

    try:
        kie_key = await get_required_tenant_secret(
            "kie_ai_api_key",
            tenant_id,
            provider_label="Kie.ai",
        )
    except RuntimeError as exc:
        return {"status": "failed", "error": str(exc)}
    ic = ImageClient(api_key=kie_key, tenant_id=tenant_id)
    await _ensure_ref_cache_schema()

    import asyncio
    sem = asyncio.Semaphore(6)

    async def _one_scene(s):
        sc = s["scene"]
        sub = subjects.get(sc) or {}
        machine = sub.get("machine") or (s["scene_text"] or "")[:80]
        caption_title = sub.get("caption_title") or machine
        caption_sub = sub.get("caption_sub") or ""
        caption_specs = [
            str(spec).strip() for spec in (sub.get("caption_specs") or [])
            if str(spec).strip()
        ][:2]
        detail_focus = sub.get("detail_focus") or "overall machine geometry"

        # The feedback requires operator/years + at least one key spec. Stop
        # before the paid image door if the grounded metadata planner could
        # not supply those fields; never fill a title card with invented facts.
        if not caption_sub or "•" not in caption_sub or not caption_specs:
            _p(
                f"Segment {sc}: title-card metadata is incomplete for {machine} "
                "(operator/service years and at least one sourced spec required) "
                "— no images generated."
            )
            return {"scene": sc, "done": 0, "reason": "missing_title_metadata"}

        def _caption(view_plan: dict) -> dict:
            return {
                "title": caption_title,
                "sub": caption_sub,
                "specs": caption_specs,
                "view_role": view_plan["role"],
                "view_label": view_plan["label"],
                "target_views": STATIC_VIEWS_TARGET,
                "minimum_views": STATIC_VIEWS_MINIMUM,
            }

        async def _insert_placeholder(view_index: int, view_plan: dict,
                                      reference_url: Optional[str] = None) -> str:
            new_id = str(uuid.uuid4())
            await execute(
                "INSERT INTO assets (id, tenant_id, video_id, scene, image_index, "
                "sentence_index, sentence_text, shot_type, video_title, aspect_ratio, "
                "status, hero_shot, generation_method, caption, drive_image_url) "
                "VALUES ($1,$2,$3,$4,$5,$5,$6,$7,$8,$9,'generating',$10,$11,$12,$13)",
                new_id, tenant_id, video_id, sc, view_index,
                (s["scene_text"] or "")[:500], view_plan["shot_type"],
                v["video_title"], v["aspect"], view_index == 1,
                STATIC_RENDER_MODE, json.dumps(_caption(view_plan)), reference_url,
            )
            return new_id

        # Placeholder row FIRST: the media proxy only serves file ids present
        # in allowlisted DB columns, and the self-hosted reference must be
        # proxy-fetchable during generation. image_url stays NULL until the
        # real image exists, so a concurrent render can't pick up the raw ref.
        await execute(
            "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
            "AND generation_method=$4", video_id, tenant_id, sc, STATIC_RENDER_MODE)
        row_id = await _insert_placeholder(1, STATIC_VIEW_PLANS[0])

        # 1) Find a REAL photo, SELF-HOST it (Wikimedia 403s Kie's fetcher),
        #    and vision-check it actually shows this machine (designation
        #    collisions like the Russian T-95 vs the US T95).
        #    LAYER 0: the tenant's own verified-reference cache — series reuse
        #    the same machines across videos, so each machine costs ONE
        #    Wikimedia conversation ever (and rate limits stop mattering).
        #    LAYER 1: the machine's Wikipedia article lead image — curated,
        #    unambiguous, and API-issued. LAYER 1.5: every other real photo
        #    embedded in that SAME article (find_article_images) — the lead
        #    image is sometimes a diagram or missing entirely for an obscure
        #    prototype, but the article body usually carries a period photo
        #    further down. LAYER 2: Commons search for extra candidates/angles.
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
            candidates = await _gather_reference_candidates(
                machine, sub.get("aliases"), sub.get("search_query"))
            for idx, (cand, trusted) in enumerate(candidates):
                hosted = await _host_reference(cand, video_id, tenant_id, f"S{sc:02d}_{idx}")
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

        # FAIL CLOSED — the law: no verified reference means NO generation.
        # A wrong image is worse than a missing one (the static-docu channels'
        # own standard), so a scene with zero verified candidates is BLOCKED
        # for the operator to seed manually, never shipped from a text-to-
        # image guess. Clear the stray drive_image_url a rejected candidate
        # may have left behind (written per-candidate above, before its own
        # vision check, and never cleared if every candidate got rejected).
        if not ref_url:
            _p(f"Segment {sc}: no verified reference photo found for the "
               f"{machine} — scene BLOCKED (no image generated). Seed "
               f"static_reference_cache (tenant_id, machine_key, machine, "
               f"hosted_url, source_url) and re-run this scene.")
            await execute(
                "UPDATE assets SET status='blocked_no_reference', "
                "image_url=NULL, drive_image_url=NULL WHERE id=$1", row_id)
            return {"scene": sc, "done": 0, "reason": "blocked_no_reference"}

        # 2) Generate the three deliberate views sequentially for this scene.
        # Scene concurrency remains six, but a single aircraft never opens
        # three provider calls at once. Every view keeps the same verified
        # reference/variant lock and passes the same two-judge QA path.
        row_ids = [row_id]
        for view_index, view_plan in enumerate(STATIC_VIEW_PLANS[1:], start=2):
            row_ids.append(
                await _insert_placeholder(view_index, view_plan, reference_url=ref_url)
            )

        async def _generate_view(view_index: int, view_plan: dict,
                                 view_row_id: str) -> bool:
            await execute(
                "UPDATE assets SET drive_image_url=$2 WHERE id=$1",
                view_row_id, ref_url,
            )
            prompt = _studio_prompt(machine, view_plan, detail_focus)
            _p(
                f"Segment {sc}/{len(scenes)}, view {view_index}/"
                f"{STATIC_VIEWS_TARGET}: {view_plan['label']}…"
            )

            # Money-safety fix: this stage spent real GPT Image 2 calls (2-3
            # views per scene, each with an optional QA retry — a SECOND real
            # generation) with NO generation_ledger write and NO cap check at
            # all. Checked fresh before EVERY provider call — scenes run
            # concurrently (Semaphore(6) above), so this is the same
            # per-call re-check pattern every other paid image site in this
            # codebase now uses (actions.budget_refusal), not a one-time
            # up-front gate a concurrent batch could slip past.
            from actions import budget_refusal, picture_price_for
            from generation_ledger import record_ledger_entry
            quote = picture_price_for("gpt-image-2")
            refusal = await budget_refusal(tenant_id, video_id, quote, "this view")
            if refusal:
                _p(f"Segment {sc}, view {view_index}: {refusal}")
                await execute(
                    "UPDATE assets SET status='budget_capped', image_url=NULL WHERE id=$1",
                    view_row_id,
                )
                return False

            # GPT Image 2 only, reference required, 1K. No fallback model can
            # silently trade historical accuracy for completion.
            res = await ic.generate_scene_image_gpt(
                prompt, ref_url, aspect_ratio=v["aspect"], allow_fallback=False,
                resolution="1K",
            )
            url = (res or {}).get("url")
            if not url:
                await execute("DELETE FROM assets WHERE id=$1", view_row_id)
                return False
            # This view's picture already cost real money the moment `url`
            # came back — meter it now, before the QA retry decision below
            # (which may spend a SECOND time on the same view).
            await record_ledger_entry(
                tenant_id=tenant_id, video_id=video_id, stage="image",
                model="gpt-image-2", units=1, unit_cost=quote, actual_cost=quote,
            )

            qa_note = ""
            if not await _render_matches_reference(
                tenant_id, url, ref_url, machine, sub.get("aliases")
            ):
                _p(
                    f"Segment {sc}, view {view_index}: render does not match "
                    f"the {machine} — one retry…"
                )
                retry_prompt = (
                    "Reproduce the machine in the verified reference EXACTLY: "
                    "same airframe or hull form, component count and placement, "
                    "proportions, variant, and distinctive engineering features. "
                    "Change only the requested camera viewpoint. "
                    + prompt
                )
                retry_refusal = await budget_refusal(
                    tenant_id, video_id, quote, "this view's QA retry")
                if retry_refusal:
                    _p(f"Segment {sc}, view {view_index}: {retry_refusal} — "
                       "keeping the first render unretried.")
                    url2 = None
                else:
                    res = await ic.generate_scene_image_gpt(
                        retry_prompt, ref_url, aspect_ratio=v["aspect"],
                        allow_fallback=False, resolution="1K",
                    )
                    url2 = (res or {}).get("url")
                    if url2:
                        await record_ledger_entry(
                            tenant_id=tenant_id, video_id=video_id, stage="image",
                            model="gpt-image-2", units=1, unit_cost=quote,
                            actual_cost=quote,
                        )
                if url2 and await _render_matches_reference(
                    tenant_id, url2, ref_url, machine, sub.get("aliases")
                ):
                    url = url2
                else:
                    candidate = url2 or url
                    if await _arbiter_confirms_render(
                        tenant_id, candidate, ref_url, machine, sub.get("aliases")
                    ):
                        _p(
                            f"Segment {sc}, view {view_index}: second-opinion "
                            "arbiter overruled the QA rejection"
                        )
                        url = candidate
                        qa_note = "[qa: arbiter-approved after double reject] "
                    else:
                        # The render is paid for, so park it for per-view human
                        # approval instead of deleting it. It does not count
                        # toward the minimum-two render gate while parked.
                        parked_url = candidate
                        parked_prompt = retry_prompt if url2 else prompt
                        try:
                            async with httpx.AsyncClient(timeout=120.0) as c:
                                r = await c.get(parked_url, follow_redirects=True)
                                r.raise_for_status()
                                data = r.content
                            parked_url = await upload_bytes(
                                data,
                                (
                                    f"{video_id}/static/S{sc:02d}_"
                                    f"{view_index:02d}_qa_rejected.png"
                                ),
                                "image/png", tenant_id,
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        await execute(
                            "UPDATE assets SET status='qa_rejected', image_url=NULL, "
                            "drive_image_url=$2, image_prompt=$3 WHERE id=$1",
                            view_row_id, parked_url,
                            (
                                (f"[ref: {ref_src}] " if ref_src else "")
                                + parked_prompt[:900]
                            ),
                        )
                        return False

            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.get(url, follow_redirects=True)
                r.raise_for_status()
                data = r.content
            durable = await upload_bytes(
                data,
                f"{video_id}/static/S{sc:02d}_{view_index:02d}.png",
                "image/png", tenant_id,
            )
            await execute(
                "UPDATE assets SET image_url=$2, drive_image_url=$2, status='done', "
                "image_prompt=$3, image_model='gpt-image-2' WHERE id=$1",
                view_row_id, durable,
                (
                    (f"[ref: {ref_src}] " if ref_src else "")
                    + qa_note + prompt[:900]
                ),
            )
            return True

        approved = 0
        for view_index, (view_plan, view_row_id) in enumerate(
            zip(STATIC_VIEW_PLANS, row_ids), start=1
        ):
            if await _generate_view(view_index, view_plan, view_row_id):
                approved += 1

        if approved < STATIC_VIEWS_MINIMUM:
            _p(
                f"Segment {sc}: only {approved}/{STATIC_VIEWS_TARGET} verified "
                f"views — needs at least {STATIC_VIEWS_MINIMUM}."
            )
        return {
            "scene": sc,
            "done": approved,
            "reason": None if approved >= STATIC_VIEWS_MINIMUM else "insufficient_views",
        }

    async def _bounded(s):
        async with sem:
            try:
                # Three sequential view generations plus bounded QA retries
                # need more room than the former single-image five-minute
                # ceiling. A hung provider still fails this ONE scene instead
                # of freezing the whole batch.
                return await asyncio.wait_for(_one_scene(s), timeout=900)
            except Exception:  # noqa: BLE001 — timeout or any error: isolate this scene
                try:
                    # Never sweep up a row _one_scene deliberately parked for
                    # the operator (qa_rejected / blocked_no_reference) — both
                    # carry image_url NULL by design, and a timeout cancelling
                    # _one_scene right after it parked would otherwise delete
                    # the parked render here.
                    await execute(
                        "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 "
                        "AND scene=$3 AND generation_method=$4 AND image_url IS NULL "
                        "AND status NOT IN ('qa_rejected','blocked_no_reference')",
                        video_id, tenant_id, s["scene"], STATIC_RENDER_MODE)
                except Exception:  # noqa: BLE001
                    pass
                return {"scene": s["scene"], "done": 0, "reason": "exception"}

    outcomes = await asyncio.gather(*[_bounded(s) for s in scenes])
    ready = [
        o for o in outcomes
        if int((o or {}).get("done") or 0) >= STATIC_VIEWS_MINIMUM
    ]
    failed = [
        str((o or {}).get("scene"))
        for o in outcomes
        if int((o or {}).get("done") or 0) < STATIC_VIEWS_MINIMUM
    ]
    view_count = sum(int((o or {}).get("done") or 0) for o in outcomes)
    if (
        section_contract is not None
        and view_count != section_contract["expected_still_images"]
    ):
        return {
            "status": "failed",
            "error": (
                "verified static view count did not match the approved section "
                f"BOM: expected {section_contract['expected_still_images']}, "
                f"got {view_count}"
            ),
        }
    if not ready:
        return {
            "status": "failed",
            "error": (
                f"no segment reached {STATIC_VIEWS_MINIMUM} verified views "
                f"(scenes failed: {', '.join(failed)})"
            ),
        }
    msg = (
        f"Generated {view_count} verified views across "
        f"{len(ready)}/{len(scenes)} segments"
    )
    if failed:
        msg += f" (failed: {', '.join(failed)})"
    return {
        "status": "completed",
        "message": msg,
        "views_generated": view_count,
        "segments_ready": len(ready),
        "segments_total": len(scenes),
    }


# --- roster-time reference prefetch (C3) --------------------------------------
#
# Problem: generate_static_images_for_video above discovers a machine's
# reference photo (or the lack of one) at IMAGE GENERATION time — after
# script and voice money is already spent — and a burst of per-machine
# Wikimedia lookups mid-generation is exactly what triggered live rate-limit
# cooldowns on the VPS. Fix: the instant a static-docu video's machine roster
# is LOCKED (research completion — see dispatch_roster_prefetch), prefetch,
# verify, self-host and cache a reference for EVERY roster machine, so
# generation later always hits a warm static_reference_cache row and the
# fail-closed gate in _one_scene becomes a backstop, not the discovery
# mechanism.


async def _prefetch_one_machine(tenant_id: str, video_id: str, machine: str,
                                roster_index: int) -> bool:
    """Verify + self-host + cache ONE roster machine's reference photo, using
    the SAME candidate chain _one_scene uses (_gather_reference_candidates).
    Returns True once a verified candidate is cached, False if the whole
    chain exhausts with nothing passing (a miss — not an exception; the
    caller records it and moves on to the next machine). No aliases are
    available this early (the roster is a flat list of designation strings
    — see pipeline_executor._machine_documentary_hold_roster), so the
    machine's own name doubles as the Commons search query, exactly like
    _one_scene's own fallback branch does when no explicit search_query is
    supplied."""
    candidates = await _gather_reference_candidates(machine, None, machine)
    mkey = _machine_key(machine)
    for idx, (cand, trusted) in enumerate(candidates):
        hosted = await _host_reference(cand, video_id, tenant_id, f"roster{roster_index:02d}_{idx}")
        if not hosted:
            continue
        if await _vision_confirms(tenant_id, hosted, machine, None, trusted_source=trusted):
            await execute(
                """INSERT INTO static_reference_cache
                       (tenant_id, machine_key, machine, hosted_url, source_url)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (tenant_id, machine_key)
                   DO UPDATE SET machine=$3, hosted_url=$4, source_url=$5,
                                 verified_at=now()""",
                tenant_id, mkey, machine[:200], hosted, cand)
            return True
    return False


async def seed_reference_from_url(video_id: str, tenant_id: str, machine: str,
                                  url: str) -> dict:
    """Operator-supplied reference photo for ONE roster machine (C3c Roster
    stage panel's "Add photo" control — the fix for a machine prefetch
    couldn't find anything for). Reuses the SAME _host_reference (self-host
    so Kie always fetches from us, never a third party) + _vision_confirms
    (machine-consistency check) + static_reference_cache upsert that
    _prefetch_one_machine already uses — no separate verification path for a
    manually-supplied photo just because a human picked it.

    An operator-pasted URL carries no Wikipedia/Commons provenance signal,
    so it always runs the FULL untrusted vision bar (trusted_source=False) —
    never a free pass just because a person supplied it.

    Never raises for a bad candidate (unreachable URL, wrong machine): both
    are reported as {"status": "rejected", "reason": ...} for the route to
    hand back as a normal response, not an exception. Returns
    {"status": "verified", "hosted_url", "source_url"} on pass."""
    await _ensure_ref_cache_schema()
    mkey = _machine_key(machine)
    hosted = await _host_reference(url, video_id, tenant_id, f"seed_{mkey}")
    if not hosted:
        return {
            "status": "rejected",
            "reason": "Couldn't fetch that URL — it may be unreachable, blocked, or too small to be a real photo.",
        }
    if not await _vision_confirms(tenant_id, hosted, machine, None, trusted_source=False):
        return {
            "status": "rejected",
            "reason": "That photo doesn't look consistent with this machine — try a clearer or more specific photo.",
        }
    await execute(
        """INSERT INTO static_reference_cache
               (tenant_id, machine_key, machine, hosted_url, source_url)
           VALUES ($1,$2,$3,$4,$5)
           ON CONFLICT (tenant_id, machine_key)
           DO UPDATE SET machine=$3, hosted_url=$4, source_url=$5,
                         verified_at=now()""",
        tenant_id, mkey, machine[:200], hosted, url)
    return {"status": "verified", "hosted_url": hosted, "source_url": url}


async def prefetch_roster_references(video_id: str, tenant_id: str) -> dict:
    """Roster-time reference prefetch (C3). Reads the video's LOCKED machine
    roster (pipeline_executor._machine_documentary_hold_roster — the same
    roster the orchestrator/dashboard/repair endpoints already use) and, for
    every machine not already in static_reference_cache, runs the full
    lookup+verify+host+cache chain. Serial per machine, on purpose: _wm_get's
    politeness throttle is a single process-global gate regardless of how
    many machines call it concurrently, so parallelizing here would only
    interleave log lines, not buy real concurrency. One machine's exception
    is caught and logged here — it can never abort the sweep for the rest
    of the roster. Never raises; every outcome is reported in the return
    dict for the caller (or a future roster-dashboard reference-status read)
    to inspect."""
    # Lazy import: static_docu <-> pipeline_executor is a two-way relationship
    # (pipeline_executor already imports static_docu lazily, e.g. at its own
    # generate_static_images_for_video call site) — importing at module top
    # either direction would risk a circular import given pipeline_executor's
    # size and reach.
    from pipeline_executor import _machine_documentary_hold_roster

    video = await fetch_one(
        "SELECT id, render_mode, research_payload FROM videos "
        "WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not video:
        return {"status": "failed", "error": "video not found"}
    roster = _machine_documentary_hold_roster(video)
    if not roster:
        return {"status": "skipped", "message": "no locked static-docu machine roster"}

    await _ensure_ref_cache_schema()

    verified, missed = 0, 0
    for i, machine in enumerate(roster):
        mkey = _machine_key(machine)
        try:
            cached = await fetch_one(
                "SELECT hosted_url FROM static_reference_cache "
                "WHERE tenant_id=$1 AND machine_key=$2", tenant_id, mkey)
            if cached:
                verified += 1
                continue
            if await _prefetch_one_machine(tenant_id, video_id, machine, i):
                verified += 1
            else:
                missed += 1
                _logger.info(
                    "[prefetch-roster-ref] video=%s machine=%r no verified "
                    "reference found (will fail-closed at generation time "
                    "unless seeded manually)", video_id, machine)
        except Exception:  # noqa: BLE001 — one machine's failure must never kill the sweep
            missed += 1
            _logger.warning(
                "[prefetch-roster-ref] video=%s machine=%r prefetch failed",
                video_id, machine, exc_info=True)

    _logger.info(
        "[prefetch-roster-ref] video=%s roster=%d verified=%d missed=%d",
        video_id, len(roster), verified, missed)
    return {"status": "completed", "roster_count": len(roster),
            "verified": verified, "missed": missed}


def dispatch_roster_prefetch(video: Optional[dict], video_id: str, tenant_id: str) -> bool:
    """Fire-and-forget hook: schedule prefetch_roster_references as a
    background task the instant research lands for a static-docu video.
    Called from BOTH research-completion seams — the paid `research` verb
    (pipeline_executor.PipelineExecutor.run_research) and the free
    `submit_research` MCP ingest (research_ingest.accept_submitted_research)
    — right before their own success return, so a single line at each call
    site is all either seam needs.

    Uses the repo's existing fire-and-forget pattern (asyncio.create_task —
    see autopilot_launch.py, routes/queue.py, main.py's startup tasks) rather
    than FastAPI's BackgroundTasks, since neither call site is guaranteed to
    be inside a request handler that owns a BackgroundTasks instance.

    Never blocks or fails the research flow that calls it: dispatch itself
    is wrapped so even a scheduling failure only logs a warning. Returns
    True if a prefetch task was actually scheduled (render_mode ==
    'static_docu'), False otherwise (nothing to prefetch for this video)."""
    if (video or {}).get("render_mode") != "static_docu":
        return False
    try:
        import asyncio
        asyncio.create_task(prefetch_roster_references(video_id, tenant_id))
        return True
    except Exception:  # noqa: BLE001 — a dispatch failure must never fail research
        _logger.warning(
            "[prefetch-roster-ref] dispatch failed for video=%s", video_id, exc_info=True)
        return False
