"""Static-documentary mode: detection + per-segment image sourcing.

A channel whose extracted identity says the format is static-image documentary
(``channel_profiles.channel_identity.visual_format`` — e.g. Designed vs Used:
archival photos held with slow Ken Burns pans, narration, no animation) gets
``videos.render_mode = 'static_docu'`` at creation. Those videos:

  * skip the animate stages entirely (their stage plan drops video+sound);
  * source THREE realistic complementary images per scene instead of the
    ~36-frame coverage flow — genuinely ROTATED camera angles: a front
    three-quarter identification view, a true side profile, and a high
    top-down planform view, with two verified views as the minimum
    renderable set;
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
    NEVER_BUILT_VIEW_PLANS,
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
# the exact machine — restored condition, led by a three-quarter identification
# profile and supported by a true side-profile view plus a high top-down
# planform view, genuinely rotated camera angles (not three near-identical
# three-quarter crops), on a seamless white/light-gray background, soft even
# lighting, with an elegant title card (name + operator/service years +
# grounded specs). To keep the machine
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
#
# View-geometry-first ordering (2026-08-03 fix): the camera instruction now
# leads the prompt and reads as the PRIMARY instruction, with reference
# fidelity phrased as IDENTITY fidelity only (what the machine is), never
# viewpoint fidelity (what angle it's shot from). The old ordering opened
# with "THE EXACT SAME machine as in the verified reference photo" before
# the view direction ever appeared — strong enough that the reference
# photo's own angle dominated every generation regardless of which of the
# three view roles was requested (live proof: HMS Argus, video d2e37cd6,
# three near-identical three-quarter crops). The prompt now says outright
# that the camera angle should differ from the reference photo whenever the
# requested view role demands it.
# Chained-view generation (2026-08-xx fix): a scene's FIRST view is still
# generated from the raw historical reference photo, but every SUBSEQUENT
# view chains off the scene's own first verified render (the "anchor")
# instead — the reference photo's own camera angle otherwise bleeds into
# every generation regardless of the requested view role (live: HMS Argus
# side_profile winning against three_quarter across 6 role-rejected
# attempts, video d2e37cd6 scene 1). `_studio_prompt`'s `from_anchor` flag
# swaps this one noun phrase everywhere it appears — identity-fidelity
# language and the camera-geometry-first structure are otherwise identical
# for both inputs.
_REFERENCE_INPUT_LABEL = "verified reference photo"
_ANCHOR_INPUT_LABEL = "verified clean studio render of the SAME machine"

_STUDIO_PROMPT = (
    "{view_direction} "
    "Studio product photograph of the {machine}. Use the {input_label} "
    "ONLY to lock its identity — real proportions, variant, "
    "configuration, component count, markings, and distinctive details, with "
    "museum-catalogue accuracy for WHAT the machine is. The camera VIEWPOINT "
    "above is independent of the {input_label}'s own angle: match the "
    "camera position instructed above even when it differs from how the "
    "{input_label} happens to be framed — do not default back to the "
    "{input_label}'s own angle. "
    "{detail_direction}"
    "Restored museum condition on a seamless PURE WHITE studio background "
    "(clean bright white, never gray, never off-white), soft even lighting, "
    "ultra crisp and photorealistic, with only a subtle soft ground shadow. "
    "ABSOLUTELY NO text, NO lettering, NO labels, NO watermark anywhere in "
    "the image. No people, no display stand, no dramatic environment. Neutral "
    "engineering-documentary presentation, never a toy, illustration, or game render."
)


def _studio_prompt(machine: str, view_plan: dict, detail_focus: str, *,
                   emphasize_geometry: bool = False,
                   from_anchor: bool = False) -> str:
    """Build one historically locked prompt for a deliberate view role.

    `emphasize_geometry` is the role-conformance QA retry's stronger wording
    (`_generate_view` below): the first attempt already leads with the
    camera instruction (see `_STUDIO_PROMPT`'s ordering), but a generation
    that still drifted back toward the input image's own angle gets an
    explicit correction that repeats and amplifies the camera instruction
    instead of quietly relying on the same wording twice.

    `from_anchor` (chained-view fix): True when the supplied image input is
    a previously-verified render from THIS scene (see `_one_scene`'s anchor
    selection) rather than the raw historical reference photo — swaps
    `_REFERENCE_INPUT_LABEL` for `_ANCHOR_INPUT_LABEL` everywhere the prompt
    describes the input image, so the model is told accurately what kind of
    picture it's looking at. Identity-fidelity language and the camera-
    geometry-first structure are unchanged either way.

    `engineering_detail` is no longer one of `STATIC_VIEW_PLANS`'s roles
    (see the contract comment in static_docu_contract.py), so this branch is
    currently dead in production — left in place because `detail_focus`
    still flows from subject planning and a future 4th view could reuse it."""
    input_label = _ANCHOR_INPUT_LABEL if from_anchor else _REFERENCE_INPUT_LABEL
    detail_direction = ""
    if view_plan.get("role") == "engineering_detail":
        focus = (detail_focus or "overall machine geometry").strip()
        detail_direction = f"VERIFIED DETAIL FOCUS: {focus}. "
    view_direction = view_plan["direction"]
    if emphasize_geometry:
        view_direction = (
            "CAMERA ANGLE CORRECTION — the previous attempt did not deliver "
            "the required camera geometry. " + view_direction + " This "
            "camera position is not optional and must be used even if it "
            f"differs sharply from the {input_label}'s own angle."
        )
    return _STUDIO_PROMPT.format(
        machine=machine,
        view_direction=view_direction,
        detail_direction=detail_direction,
        input_label=input_label,
    )


# --- never-built blueprint path (Ryan's decision, 2026-08-04) --------------
#
# A roster entry pipeline_executor._roster_entry_never_built classifies as a
# cancelled programme with zero physical hulls ever completed (CVA-01
# class: cancelled February 1966 before construction) structurally can
# NEVER have a reference photograph. The fail-closed reference-hunt gate
# below is correct to refuse a photo-grounded render for it — but it also
# permanently blocks the scene's render gate for a machine everyone already
# knows was never built. Ryan's call: ship an HONEST monochrome technical
# blueprint instead of inventing a fake "photograph" of a machine that
# never existed.
#
# Style choice: black linework on white, not an aged blue-and-white
# "cyanotype" blueprint look. Reasoning: the caption overlay already
# stamps "Design study — never built" onto the warm cream title card
# (`_caption` below, rendered verbatim by `DocumentaryTitleCard` in
# remotion-video/src/Scene.tsx) — a stark line-drawing recognition plate
# reads as a deliberate, confident documentary device against that card,
# where a colored cyanotype would look like a rendering glitch or a
# missing photo. Black-on-white also gives the image model one fewer thing
# to get wrong: a cyanotype's blue has to land exactly right or it reads as
# "broken image", where plain black-and-white linework does not.
_BLUEPRINT_STYLE_NOTE = (
    "Style: a monochrome naval/aeronautical technical drawing — precise "
    "black linework on a clean white background, orthographic projection, "
    "in the manner of a Jane's Fighting Ships recognition plate or a "
    "shipyard general-arrangement drawing. Pure line art: no color, no "
    "photographic rendering, no 3D shading or gradients, never a "
    "photograph — this is an engineering illustration, not a photo. "
    "ABSOLUTELY NO text, NO lettering, NO numerals, NO dimension lines or "
    "callouts, NO title block, NO watermark anywhere in the image — the "
    "drawing must be pure linework with no writing of any kind."
)

# Caption marker (Ryan's decision, 2026-08-04): every blueprint view's
# caption_sub is prefixed with this so the honest "never built" fact
# survives all the way to the rendered video, not just the operator-facing
# DB row — see `_caption` in `_one_scene` for exactly how it's applied, and
# the module note above for how it reaches the screen.
_NEVER_BUILT_CAPTION_PREFIX = "Design study — never built"

_BLUEPRINT_VIEW_DIRECTIONS = {
    "side_profile": (
        "Draw a true orthographic SIDE ELEVATION: the complete outline "
        "viewed directly from the side at a 90-degree angle to the "
        "machine's long axis, full length framed edge to edge, silhouette "
        "and major structural lines only — like a museum recognition-chart "
        "profile rendered as a line drawing."
    ),
    "top_planform": (
        "Draw a true orthographic TOP-DOWN PLAN VIEW: looking straight "
        "down from directly above, showing the outline and major surface "
        "layout exactly as seen from the top, with no perspective "
        "foreshortening."
    ),
}


def _blueprint_prompt(machine: str, view_plan: dict, facts: Optional[list] = None, *,
                      emphasize_geometry: bool = False) -> str:
    """One never-built-machine prompt: a monochrome technical drawing, not a
    photo-grounded studio render (see the module note above for the style
    rationale). Grounded ONLY in `facts` — the scene's own vetted
    caption_specs plus the resolved roster entry's role/years/status/
    built_count text, never an invented detail. No reference or anchor
    image is ever passed for this path (see `_generate_blueprint_view`) —
    there is no photograph to lock identity against, so the prompt is the
    only source of truth for what the machine looked like.

    `emphasize_geometry` mirrors `_studio_prompt`'s role-conformance retry
    wording: unchanged style/grounding, just a stronger, repeated push on
    the requested drawing geometry when the first attempt didn't deliver
    it."""
    direction = _BLUEPRINT_VIEW_DIRECTIONS.get(
        view_plan.get("role"), view_plan.get("direction", ""))
    if emphasize_geometry:
        direction = (
            "DRAWING GEOMETRY CORRECTION — the previous attempt did not "
            "deliver the required view. " + direction + " This viewpoint "
            "is not optional."
        )
    fact_bits = [str(f).strip() for f in (facts or []) if str(f).strip()]
    facts_line = (
        "Known factual details to depict accurately, and ONLY these — do "
        "not invent armament, equipment, or features not listed here: "
        + "; ".join(fact_bits) + ". "
    ) if fact_bits else ""
    return (
        f"{direction} Subject: the {machine} — a design that was never "
        "actually built (a paper project or a programme cancelled before "
        "construction), so this is an illustrative engineering design "
        "study of what it would have looked like, not a photograph of a "
        f"real object. {facts_line}"
        f"{_BLUEPRINT_STYLE_NOTE}"
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
                            # C36 fix: this used to be its own raw, unfloored
                            # `tok in page_tok` substring test — the SAME
                            # weakness as _page_matches, duplicated here one
                            # call earlier, so fixing only _page_matches left
                            # this upstream trust computation still forging
                            # false matches (e.g. '91' matching 'No. 91
                            # Squadron RAF'). Now routed through the one
                            # shared, floored, boundary-anchored helper.
                            page_title = p.get("title") or ""
                            trusted = any(
                                _designation_token_in_title(
                                    _designation_token(n), page_title)
                                for n in names if n)
                            out.append({"url": src, "page": page_title,
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
    # C8 (2026-07-29): WHY a machine missed, scoped per-VIDEO rather than
    # per (tenant, machine_key) like static_reference_cache above — the same
    # machine can miss for one video (a bad alias, a transient fetch error)
    # and verify cleanly for another, or on a later re-check of the same
    # video once an alias/prompt fix lands. A row here is a "still open"
    # marker, not history: it is deleted the instant the machine clears
    # (see _clear_reference_miss), so its mere presence already means
    # "unresolved as of checked_at" without needing a status column.
    # Defensive CREATE, same reasoning as static_reference_cache above — this
    # is additive/read-mostly and not worth blocking on a migration deploy.
    await execute(
        """CREATE TABLE IF NOT EXISTS static_reference_misses (
            tenant_id UUID NOT NULL,
            video_id UUID NOT NULL,
            machine_key TEXT NOT NULL,
            machine TEXT,
            reason_code TEXT NOT NULL,
            reason_detail TEXT,
            checked_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (tenant_id, video_id, machine_key)
        )""")


# Reason vocabulary for static_reference_misses.reason_code (C8). Three of
# these map to the three genuinely different failure modes named in the
# 2026-07-27 incident write-up; a 4th ("error") covers an exception raised
# mid-lookup (network blip, etc) so no miss is EVER left unexplained. A 5th
# ("never_built") is produced by prefetch_roster_references (C5,
# 2026-07-29) for a roster entry pipeline_executor._roster_entry_never_built
# classifies as structurally unable to ever have a photograph (a cancelled
# programme with no physical unit ever completed) — recorded BEFORE any
# lookup is attempted, so it is the one reason that costs zero real spend.
REASON_NO_CANDIDATES = "no_candidates"      # search found nothing to check
REASON_FETCH_FAILED = "fetch_failed"        # candidates found, none could be hosted
REASON_VISION_REJECTED = "vision_rejected"  # hosted candidate(s), vision confirmed none
REASON_ERROR = "error"                      # exception mid-lookup
REASON_NEVER_BUILT = "never_built"          # C5: classified pre-lookup, no spend incurred

_MISS_REASON_LABELS = {
    REASON_NO_CANDIDATES: "No candidate photo could be found for this machine — "
                           "the search returned nothing to check. Worth retrying "
                           "once aliases or search terms improve.",
    REASON_FETCH_FAILED: "A candidate photo was found but couldn't be downloaded "
                          "or hosted — likely a dead link or a blocked host. "
                          "Worth retrying.",
    REASON_VISION_REJECTED: "A candidate photo was found and hosted, but it didn't "
                             "look like this specific machine to the vision check. "
                             "Worth retrying with a different photo, or pasting one "
                             "yourself.",
    REASON_ERROR: "Something went wrong while checking this machine (a network or "
                  "lookup error). Worth retrying.",
    REASON_NEVER_BUILT: "This machine was never actually built — no photo can ever "
                        "exist for it.",
}


async def _record_reference_miss(tenant_id: str, video_id: str, machine: str,
                                  reason_code: str, detail: Optional[str] = None) -> None:
    """Persist (or refresh) why ONE roster machine missed on THIS video.
    Best-effort: a failure here must never surface to the sweep — recording
    the reason is diagnostic sugar, not a gate."""
    try:
        await _ensure_ref_cache_schema()
        mkey = _machine_key(machine)
        await execute(
            """INSERT INTO static_reference_misses
                   (tenant_id, video_id, machine_key, machine, reason_code,
                    reason_detail, checked_at)
               VALUES ($1,$2,$3,$4,$5,$6,now())
               ON CONFLICT (tenant_id, video_id, machine_key)
               DO UPDATE SET machine=$4, reason_code=$5, reason_detail=$6,
                             checked_at=now()""",
            tenant_id, video_id, mkey, machine[:200], reason_code,
            detail or _MISS_REASON_LABELS.get(reason_code, ""))
    except Exception:  # noqa: BLE001 — diagnostic only, never fails the sweep
        _logger.warning(
            "[prefetch-roster-ref] could not persist miss reason for "
            "video=%s machine=%r", video_id, machine, exc_info=True)


async def _clear_reference_miss(tenant_id: str, video_id: str, machine: str) -> None:
    """A machine that just verified (prefetch, re-check, or manual seed) can
    no longer be an open miss for this video — delete the row so the panel
    stops showing a stale reason for a machine that's fixed. No-op if there
    was never a miss row (DELETE of a missing key is cheap and harmless)."""
    try:
        mkey = _machine_key(machine)
        await execute(
            "DELETE FROM static_reference_misses "
            "WHERE tenant_id=$1 AND video_id=$2 AND machine_key=$3",
            tenant_id, video_id, mkey)
    except Exception:  # noqa: BLE001 — diagnostic only
        _logger.debug(
            "[prefetch-roster-ref] could not clear miss reason for "
            "video=%s machine=%r", video_id, machine, exc_info=True)


def _page_matches(machine: str, aliases: Optional[list], page: str) -> bool:
    """Does the Wikipedia article title actually name this machine?

    A lead image is only 'trusted' because it belongs to the machine's OWN
    article — but the title search is fuzzy and can land on a similar
    machine's article (seen live: the 'Covenanter' search returned the
    Crusader tank's lead image). If the page title doesn't share the
    machine's designation token or a significant name word, the provenance
    guarantee is void and the candidate must pass the strict vision check.

    C36 fix: the designation-token half of this check used to be a raw,
    unfloored substring test (`tok in compact_page`, compact_page being the
    page title with ALL spaces stripped) — verified live to let a roster
    machine's short digit token ("91" from "HMS Ark Royal (91)") false-match
    the unrelated Wikipedia article "No. 91 Squadron RAF" (a WWII RAF fighter
    squadron with its own aircraft photo), because the compacted-title
    substring test has no length floor and no boundary. Now routed through
    _designation_token_in_title, shared with find_wikipedia_lead_images so
    the two checks can't drift apart again."""
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
    page_words = set(norm_page.split())
    for name in [machine] + list(aliases or []):
        tok = _designation_token(name)
        if _designation_token_in_title(tok, page):
            return True
        for word in re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).split():
            if len(word) >= 4 and word not in _GENERIC and word in page_words:
                return True
    return False


def _roster_entry_for_scene_machine(entries: list, machine: str,
                                    aliases: Optional[list]) -> Optional[dict]:
    """Resolve a SCENE's own LLM-derived machine label (+ its own LLM-
    derived aliases, from ``_scene_subjects``) to exactly one entry of the
    video's LOCKED machine roster (``pipeline_executor.
    _machine_documentary_hold_roster_entries`` shape: {"name", "aliases",
    "never_built", "facts"}), or None when no entry — or more than one —
    matches.

    G24 (2026-08-03): a roster machine can already have a verified photo in
    static_reference_cache (written at roster-lock time by
    prefetch_roster_references, keyed on `_machine_key(entry["name"])`), yet
    a scene about that exact same machine still misses LAYER 0's direct
    cache lookup above — because `_scene_subjects` derives its "machine"
    label independently from the scene's narration text (it never sees the
    roster), so a short natural guess ("HMS Eagle") essentially never
    equals a roster entry's compound bookkeeping display name ("HMS Eagle
    (1918) Eagle"), let alone a ship-class entry's genuinely unsearchable
    glued string ("Lend-Lease escort carriers Ruler class (US-built)" — see
    _unit_roster_aliases's own docstring for why that shape exists at all).
    This is that second, alias-aware lookup: does THIS scene's machine
    label plausibly name one specific roster entry?

    Deliberately reuses `_page_matches` — the SAME word-overlap/designation-
    token check the reference hunt already trusts to decide whether a
    Wikipedia article or Commons file title belongs to a machine — applied
    against each roster entry's own name+aliases blob instead of a web
    page's title. No new normalizer: matching a scene guess to a roster
    entry is the same kind of "does this loose text name that machine"
    question _page_matches already answers, just with the roster entry
    playing the "page" role instead of a search-engine hit.

    G21b/G22-safety: two DISTINCT roster entries can legitimately share
    generic bookkeeping words (the live collision: "Lend-Lease escort
    carriers Attacker class (US-built)" and "...Ruler class (US-built)" —
    same designation prefix, different class name) or even the same
    _normalized_unit_code (the live "CVA-01 class" vs "Audacious class /
    Malta class" collision, both normalizing to CVA01). A match is only
    ACCEPTED when it resolves to EXACTLY ONE roster entry — zero or
    multiple hits return None, the same fail-closed rule
    _locked_roster_item_for_machine/_roster_index_for_identity already use
    for this exact collision shape (pipeline_executor.py). This is what
    keeps the CVA-01 scenes (never built — no photo can exist) correctly
    unresolved rather than guessing between two candidate entries: neither
    "CVA-01" alone matches only one of them unambiguously.

    Never a final answer by itself — the caller still runs the resolved
    entry's cached photo through `_vision_confirms` before ever accepting
    it as this scene's reference, exactly like every other candidate the
    reference hunt considers."""
    hits = []
    for entry in entries or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not name:
            continue
        haystack = " | ".join([name] + list(entry.get("aliases") or []))
        if _page_matches(machine, aliases, haystack):
            hits.append(entry)
    return hits[0] if len(hits) == 1 else None


def _designation_token(machine: str) -> str:
    """The machine's designation as a matchable token: the first word with a
    digit, alphanumerics only, lowercased (e.g. 'MBT-70' -> 'mbt70',
    'XM2001 Crusader' -> 'xm2001', 'T95 medium tank' -> 't95')."""
    for word in (machine or "").split():
        if any(ch.isdigit() for ch in word):
            return re.sub(r"[^a-z0-9]", "", word.lower())
    return re.sub(r"[^a-z0-9]", "", (machine or "").lower())[:12]


def _designation_token_in_title(tok: str, title: str) -> bool:
    """Boundary-anchored, length-floored check: does `_designation_token`
    output `tok` appear as a standalone alphanumeric unit inside a Wikipedia
    ARTICLE TITLE `title`? Shared by _page_matches and
    find_wikipedia_lead_images — the two used to each carry their own raw
    `tok in compact_title` substring test, and letting them drift apart is
    exactly how this bug (C36) existed twice over. Deliberately distinct from
    _commons_title_matches (which judges Commons FILE names, a different
    string shape — designations glued directly to serial numbers with no
    natural boundary, e.g. 'XB-35_11-300.jpg' — so it stays a plain substring
    test with only the length floor).

    Two guards, for two different real collisions:

    1. LENGTH FLOOR (>=3, matching _commons_title_matches): a 2-character
       digit token ('91' from 'HMS Ark Royal (91)', '95' from 'HMS Hermes
       (95)') is common enough to appear in almost any page title by chance.
       Verified live: 'No. 91 Squadron RAF' — a real WWII RAF fighter
       squadron article with its own aircraft photo — contains '91' as a
       standalone word, so the roster machine 'HMS Ark Royal (91)' could
       mark that squadron's photo as trusted.

    2. WORD-BOUNDARY ANCHOR: a floor alone still isn't enough — pennant-
       number tokens that clear it ('d48' from 'HMS Campania (D48)', 'f61'
       from an Ark Royal-class carrier) are exactly the numbers the Royal
       Navy has reused across different eras and ship classes, and a raw
       substring test also lets a short token match embedded inside a longer
       unrelated alphanumeric run once the title's spaces are stripped for
       comparison (no boundary survives that compaction). Anchoring with
       \\b...\\b requires the token to sit at an actual word edge in the
       title, so it can never match as a fragment glued inside a bigger,
       unrelated word/number run. It does NOT guarantee two different ships
       can never share the exact same short pennant number in Wikipedia's own
       title text — that residual ambiguity is inherent to a token-only
       check and is left to the vision-model confirmation layer."""
    if not tok or len(tok) < 3:
        return False
    norm_title = re.sub(r"[^a-z0-9 ]", "", (title or "").lower())
    if not norm_title:
        return False
    return re.search(r"\b" + re.escape(tok) + r"\b", norm_title) is not None


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


def _qa_reason_text(txt: str, limit: int = 200) -> str:
    """Extract the reason clause from a QA judge's 'YES/NO, <reason>' reply
    (the shape `_view_role_confirms` and `_render_matches_reference` both
    use). Observability fix (2026-08-03): a rejected render used to have its
    verdict text thrown away along with the pixels — nobody could tell
    whether the GENERATOR or the JUDGE was wrong on a repeat reject. Strips
    the leading yes/no token so the park-row marker reads as a reason, not a
    repeat of the verdict; falls back to the raw reply if stripping leaves
    nothing. Truncated — this only feeds a human-readable park-row note,
    never a decision."""
    reason = re.sub(r"^\s*\W*\b(yes|no)\b[\s,:;.\-]*", "", txt, flags=re.I).strip()
    return (reason or txt).strip()[:limit]


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
                           trusted_source: bool = False,
                           facts: Optional[dict] = None,
                           source_label: Optional[str] = None) -> bool:
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
    see _gather_reference_candidates) do NOT need the model to volunteer a
    leading YES to confirm identification — provenance excuses a weak
    model's failure to POSITIVELY name an obscure machine (a haiku-tier
    vision model misidentified genuine XB-15/B-21 lead-image photos as "a
    B-17"/"a B-2" live, yet those really were the right machine). Hard
    rejections (interiors, people/portraits, maps, flat/non-photo media)
    still apply to trusted candidates — provenance only excuses not being
    able to name it by sight, never a wrong-media or clearly-wrong-content
    image.

    C36 fix: provenance is NOT allowed to override an explicit NEGATIVE
    identification. The old rule ignored the model's YES/NO entirely for
    trusted candidates and looked ONLY at the hard-reject keyword lists —
    which meant a reply like "NO, this is a Supermarine Spitfire fighter
    aircraft, not a ship" contains none of _WRONG_CONTENT_KEYWORDS and was
    silently treated as a PASS (verified live: this is exactly how a
    misrouted "No. 91 Squadron RAF" photo would have been hosted and cached
    forever as "HMS Ark Royal"). A trusted candidate is now rejected when the
    model's answer explicitly opens with NO, in addition to the existing
    hard-reject keywords — an ambiguous or uncertain reply that doesn't
    volunteer a leading NO can still pass (preserving the original intent:
    provenance excuses a weak/uncertain identification), but an active "NO,
    this is a different machine" always loses. This does NOT fully close the
    door on a reused-designation collision the model itself fails to catch
    (nothing at the text layer can), but it stops discarding a correct
    negative identification the model DID give us.

    UNTRUSTED candidates still require an explicit YES, and the question is
    deliberately strict about VARIANT — a modern B-52H photo must NOT pass as
    the prototype XB-52.

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
    both branches below share one content list.

    VIS-1 (2026-07-30): `facts` (the roster entry's own role/years/status/
    built_count) and `source_label` (the candidate's filename/title text)
    joined the question. Audited live on video d2e37cd6: the old
    name-only question "verified" 4 of 5 alias-found candidates WRONG —
    Courageous in her pre-conversion battlecruiser configuration, HMS Glory
    (a Colossus-class ship) as "Majestic class", Pretoria Castle as her
    post-war liner reconversion, and USS Guadalcanal (a US Navy
    Casablanca-class CVE) as the RN "Ruler class". Pixels alone genuinely
    cannot split sister classes (Glory vs Majestic are near-identical), but
    the candidate's own filename usually names the unit — so the filename is
    given to the model as text and a filename naming a unit outside this
    entry's members/aliases is an explicit NO. Era/configuration mismatches
    (battlecruiser-era Courageous, liner-era Pretoria Castle) ARE visible in
    pixels once the question states the role and era, so the facts lines and
    the conversion rule below hand the model exactly that. Both parameters
    default to None: every pre-existing caller keeps the old (weaker)
    question until it opts in."""
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
    facts_txt = ""
    if facts:
        fact_lines = [
            f"- {label}: {facts[key]}"
            for key, label in (
                ("role", "Role"),
                ("years", "Years/era"),
                ("status", "Status"),
                ("built_count", "Built"),
            )
            if facts.get(key)
        ]
        if fact_lines:
            facts_txt = (
                "Known facts about this machine from the locked research "
                "roster:\n" + "\n".join(fact_lines) + "\n"
                "The photo must be consistent with this role and era. If "
                "this machine was a conversion, a photo of the same hull in "
                "its PRE-conversion or later RE-converted configuration "
                "(for example a gun-armed warship before a flight deck was "
                "fitted, or a civilian ship after the flight deck was "
                "removed) counts as NO. "
            )
    source_label_txt = ""
    if source_label:
        source_label_txt = (
            f"The photo's source filename/title is: {str(source_label)[:300]}. "
            "If that filename or title names a specific unit, ship, or "
            "aircraft that is NOT this machine or one of its listed names "
            "above, answer NO — a lookalike from a different class, a "
            "sister design, or another country's forces is NOT this "
            "machine. "
        )

    prompt_text = (
        f"We believe this image shows the {machine}{alias_txt}. "
        f"{source_hint}"
        f"{facts_txt}"
        f"{source_label_txt}"
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
        # C36 fix: provenance may still excuse the ABSENCE of a leading YES
        # (a weak model failing to positively name an obscure machine), but
        # it must never override an explicit leading NO — that's the model
        # actively telling us this is a different machine, and discarding
        # that signal is what let a misrouted trusted candidate ("NO, this
        # is a Supermarine Spitfire ... not a ship") pass silently before.
        said_no = bool(re.match(r"^\W*no\b", txt))
        return not said_no and not is_flat and not wrong
    said_yes = bool(re.match(r"^\W*yes\b", txt))
    return said_yes and not is_flat and not wrong


async def _render_matches_reference(tenant_id: str, render_url: str, ref_url: str,
                                    machine: str, aliases: Optional[list] = None, *,
                                    reason_out: Optional[list] = None) -> bool:
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
    symptom, so it fails OPEN like `_vision_confirms` does).

    `reason_out` (2026-08-03 observability fix, keyword-only so every
    existing positional caller is untouched): when given a list, this
    function appends exactly one entry — the judge's reason text (or a
    placeholder describing a transport failure / config gap) — regardless of
    verdict. Lets a caller that's about to park a rejected render also record
    WHY, without changing this function's bool return contract."""
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
        if reason_out is not None:
            reason_out.append("(no provider key configured — QA skipped)")
        return True  # config gap, not a transport failure — unchanged behavior
    if not txt:
        # Every attempt raised, failed to download, or came back empty —
        # FAIL CLOSED: this render is treated as unverified/rejected (the
        # caller's own retry-with-a-stricter-prompt loop in _one_scene picks
        # up from there), never silently promoted to "matches".
        if reason_out is not None:
            reason_out.append("(no response from QA judge — transport failure)")
        return False

    is_empty = _has_keyword(txt, _RENDER_EMPTY_KEYWORDS)
    said_yes = bool(re.match(r"^\W*yes\b", txt))
    verdict = said_yes and not is_empty
    if reason_out is not None:
        reason_out.append(_qa_reason_text(txt))
    return verdict


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


# View-role geometry requirement, one line per STATIC_VIEW_PLANS role — used
# ONLY by `_view_role_confirms` below to ask whether a generated image
# actually delivers its role's camera geometry, not whether it's the right
# machine (that's `_render_matches_reference`'s job, untouched by this fix).
# A role with no entry here (e.g. a future reintroduced `engineering_detail`)
# is treated as having no geometry contract to check — see the function's
# fallback.
_ROLE_GEOMETRY_REQUIREMENTS = {
    # bow-vs-stern is NOT decisive here (2026-08-03 fix): the judge rejected
    # correctly-elevated quarter views twice on video d2e37cd6 scene 1 over
    # which end faced the camera, while the preserved rejected frame was a
    # textbook identification quarter view. Either end + one full side,
    # slightly elevated, satisfies the role — see static_docu_contract.py's
    # STATIC_VIEW_PLANS comment for the full rationale.
    "three_quarter": (
        "a front three-quarter view: the camera from a slightly elevated "
        "vantage point (the classic bow-quarter or stern-quarter "
        "press/aerial photo — either end is acceptable, not eye-level and "
        "not a steep overhead angle), with BOTH one end of the machine "
        "(bow or stern) and one full side visible together in the same "
        "frame and the overall shape and length clearly readable (not a "
        "flat side-on profile, and not a steep top-down angle)"
    ),
    "side_profile": (
        "a TRUE side-on profile view: the camera positioned directly to "
        "the side, at roughly a 90-degree angle from the machine's "
        "longitudinal axis, so the full silhouette reads as a flat side "
        "elevation with little to no front-on or top-down surface visible "
        "(not a three-quarter angle)"
    ),
    "top_planform": (
        "a genuinely HIGH top-down planform view: the camera positioned "
        "well above the machine looking steeply down, so the upper "
        "surfaces/planform dominate the frame (not a modestly elevated "
        "three-quarter angle, and not a side-on profile)"
    ),
}


async def _view_role_confirms(tenant_id: str, image_url: str, machine: str,
                              view_plan: dict, *,
                              reason_out: Optional[list] = None) -> bool:
    """Role-conformance QA (2026-08-03 fix): does this generated image
    actually deliver the camera GEOMETRY its view role promises, not just
    the right machine? `_render_matches_reference` only judges identity
    (same aircraft type/configuration) — it happily passes three
    near-identical three-quarter crops as long as each one is recognizably
    the right machine, which is exactly the live defect (HMS Argus, video
    d2e37cd6: three near-identical left-side three-quarter compositions).
    This is a SEPARATE, single-image question asked in addition to identity
    QA, never a replacement for it.

    Single-image judge (only the render, no reference photo needed — the
    question is about the render's own camera angle, not about matching
    anything). Modeled on `_vision_confirms`'s YES/NO shape and
    `_download_image_b64`'s self-fetch pattern for the same reasons those
    functions use them (a URL-source image block 400's through the Kie
    gateway; self-fetching avoids that entirely).

    Roles with no entry in `_ROLE_GEOMETRY_REQUIREMENTS` (nothing today —
    reserved for a role added later with no geometry contract yet) always
    pass: nothing to check.

    FAILS OPEN on a config gap (no provider key at all) like the other
    per-view judges — unreachable in practice since a keyless tenant never
    got this far. FAILS CLOSED on a transport failure (one retry, then
    rejected) — the caller's own one-bounded-retry loop treats a rejection
    here exactly like a geometry mismatch, never a silent pass.

    `reason_out` (2026-08-03 observability fix, keyword-only so every
    existing positional caller — including every direct-call unit test —
    is untouched): when given a list, this function appends exactly one
    entry — the judge's reason text (or a placeholder describing a
    transport failure / config gap) — regardless of verdict. Lets a caller
    that's about to park a rejected view also record WHY, without changing
    this function's bool return contract."""
    requirement = _ROLE_GEOMETRY_REQUIREMENTS.get(view_plan.get("role"))
    if not requirement:
        if reason_out is not None:
            reason_out.append("(no geometry requirement defined for this role)")
        return True

    from vault import get_secret

    prompt_text = (
        f"This image is supposed to show the {machine} shot from "
        f"{requirement}. Answer on one line: first word YES or NO, then one "
        "short reason naming the actual camera angle you see. YES only if "
        "the camera viewpoint genuinely matches that description."
    )

    async def _ask_once() -> Optional[str]:
        img = await _download_image_b64(image_url)
        if img is None:
            return ""  # download failure this attempt — caller retries
        media_type, b64_data = img
        content = [
            {"type": "text", "text": prompt_text},
            {"type": "image", "source": {"type": "base64",
             "media_type": media_type, "data": b64_data}},
        ]

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
            _logger.warning("_view_role_confirms: model API HTTP %s", r.status_code)
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
        if reason_out is not None:
            reason_out.append("(no provider key configured — QA skipped)")
        return True  # config gap, not a transport failure — unchanged behavior
    if not txt:
        if reason_out is not None:
            reason_out.append("(no response from QA judge — transport failure)")
        return False  # FAIL CLOSED — see docstring

    verdict = bool(re.match(r"^\W*yes\b", txt))
    if reason_out is not None:
        reason_out.append(_qa_reason_text(txt))
    return verdict


async def _blueprint_render_confirms(tenant_id: str, image_url: str, machine: str,
                                     facts: Optional[list] = None, *,
                                     reason_out: Optional[list] = None) -> bool:
    """Never-built-machine identity QA (Ryan's decision, 2026-08-04):
    `_render_matches_reference` cannot run for this path — by definition
    there is no reference photograph to compare the render against. This is
    the replacement question: is this image actually a monochrome
    TECHNICAL DRAWING (not a photograph, not a color render) of a
    plausible `machine`, broadly consistent with its own known facts, with
    no readable text anywhere in the frame? Role-conformance QA
    (`_view_role_confirms`) is UNCHANGED and still runs on top of this —
    that check is purely about camera/drawing geometry (does a side
    elevation read side-on?) and needs no reference image either way.

    Single-image judge, same self-fetch-then-base64 pattern as
    `_vision_confirms`/`_view_role_confirms` (a URL-source image block
    400s through the Kie gateway, so every image is downloaded and inlined
    as base64 instead).

    FAILS CLOSED on transport failure: one retry, then treated as REJECTED
    — the caller's own bounded-retry-then-park loop treats a rejection here
    exactly like every other QA judge in this module, never silently
    promoted to "passes". FAILS OPEN on a config gap (no provider key at
    all configured for the tenant) — same carve-out as every other judge
    here, since there is nothing this check can do without a vision model.

    `reason_out`, when given a list, gets exactly one entry — the judge's
    reason text (or a placeholder for a transport failure / config gap) —
    regardless of verdict, matching every other judge's `reason_out`
    contract in this module."""
    from vault import get_secret

    fact_bits = [str(f).strip() for f in (facts or []) if str(f).strip()]
    facts_txt = (
        "Known facts about this machine: " + "; ".join(fact_bits) + ". "
    ) if fact_bits else ""

    prompt_text = (
        f"This image is supposed to be a monochrome technical engineering "
        f"drawing of the {machine} — a machine that was designed but "
        "never actually built, so this is meant to be an illustrative "
        f"design study, not a photograph of a real object. {facts_txt}"
        "Answer on one line: first word YES or NO, then one short reason. "
        "YES only if the image is a black-and-white/monochrome line-art "
        "technical drawing (NOT a color photograph, NOT a photorealistic "
        "3D render) that plausibly depicts the type of vehicle named "
        "above, broadly consistent with the known facts, and contains NO "
        "readable text, lettering, numerals, or dimension labels anywhere "
        "in the image. NO if it is a color photograph or photorealistic "
        "render, if it clearly shows the wrong type of vehicle, or if it "
        "contains any readable text or lettering."
    )

    async def _ask_once() -> Optional[str]:
        img = await _download_image_b64(image_url)
        if img is None:
            return ""  # download/size failure this attempt — caller retries
        media_type, b64_data = img
        content = [
            {"type": "text", "text": prompt_text},
            {"type": "image", "source": {"type": "base64",
             "media_type": media_type, "data": b64_data}},
        ]

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
            _logger.warning("_blueprint_render_confirms: model API HTTP %s", r.status_code)
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
        if reason_out is not None:
            reason_out.append("(no provider key configured — QA skipped)")
        return True  # config gap, not a transport failure — unchanged behavior
    if not txt:
        if reason_out is not None:
            reason_out.append("(no response from QA judge — transport failure)")
        return False  # FAIL CLOSED — see docstring

    verdict = bool(re.match(r"^\W*yes\b", txt))
    if reason_out is not None:
        reason_out.append(_qa_reason_text(txt))
    return verdict


# --- subject planning batching -------------------------------------------
#
# Root cause (live, 2026-08-03): _scene_subjects used to plan the WHOLE
# roster in ONE Claude call at a flat max_tokens=1800. Each scene's JSON
# item runs roughly 150-200 tokens, so a 23-scene roster needs ~3,500-4,500
# output tokens — the reply truncated mid-array. _parse_json_array is
# deliberately strict (one `re.search(r"\[.*\]")` then `json.loads`, no
# salvage of a truncated array), so the truncated reply parsed to None,
# _scene_subjects returned {} for EVERY scene, and every scene then bounced
# on the metadata gate in _one_scene below. The pipeline reported the
# misleading aggregate "no segment reached N verified views" even though
# zero images were ever attempted. A 5-scene video fit comfortably under
# 1800 tokens, which is why past live tests of this stage passed.
#
# Fix: plan in chunks small enough that a worst-case chunk reply comfortably
# fits its own max_tokens budget, and merge the per-chunk dicts. A chunk
# whose reply still fails to parse gets ONE retry; scenes still unparseable
# after the retry are returned by scene number so the caller can report a
# truthful planning-failure error instead of blaming "verified views".
_SUBJECTS_CHUNK_SIZE = 6
_SUBJECTS_TOKENS_PER_SCENE = 300
_SUBJECTS_TOKENS_FLOOR = 900


def _subjects_chunk_max_tokens(chunk_len: int) -> int:
    """Output budget for one planning call covering ``chunk_len`` scenes."""
    return max(_SUBJECTS_TOKENS_FLOOR, chunk_len * _SUBJECTS_TOKENS_PER_SCENE)


# --- G25 (2026-08-04): per-machine research-card facts for the planner ------
#
# Root cause (live, video d2e37cd6, scene 19 "Nairana class" / HMS Nairana &
# HMS Vindex): the `facts` block above is built ONLY from research_payload's
# `fact_sheet`/`character_dossier`/`headline` keys. The machine-documentary
# (DVsU/Anton) format never populates those — its real, sourced research
# lives per-machine in `machine_research_cards` (mirrored into
# research_payload.unit_research_cards by pipeline_executor.py's
# _load_machine_research_cards). Scene 19's own narration text carries zero
# numeric specs, so with no research facts to fall back on either, the
# planner had nothing to build `caption_specs` from, returned [], and the
# metadata gate in `_one_scene` bounced the scene forever.
#
# Fix: hand the planner each segment's OWN machine's sourced facts, inline
# with that segment's text (never as one shared blob — six different
# machines share a chunk, and blending their facts risks the model citing
# machine A's spec for machine B's scene). Scene -> machine is resolved
# POSITIONALLY, not by name-matching: a locked machine-documentary roster's
# scene numbering is 1:1 with roster order (pipeline_executor.py's
# _run_static_script_hold saves every machine's paragraph at
# `scene = roster.index(machine) + 1` — the ONLY script-writing path for
# this render mode), so scene N's machine is simply `roster_entries[N-1]`.
# This has to run BEFORE the planner call produces its own "machine" guess
# (that's this function's whole job), so the alias-aware, LLM-guess-driven
# `_roster_entry_for_scene_machine` used later in `_one_scene` cannot apply
# here — there is no guess yet to match against.
#
# Cards are read straight from `machine_research_cards` (tenant_id, video_id,
# roster_index) rather than the video's persisted research_payload — the
# same source of truth pipeline_executor.py's _load_machine_research_cards
# rehydrates that field from at script-hold time (migration 153's
# roster_index identity). Live proof this matters: on d2e37cd6,
# research_payload.unit_research_cards carries only 21 of the roster's 23
# cards; the table has all 23 (including scene 19's).
_CARD_NUMERIC_CLAIM_LIMIT = 4
_CARD_FACTS_MAX_CHARS = 700


def _machine_facts_for_planner(entry: Optional[dict], card: Optional[dict]) -> str:
    """Compact, sourced-fact digest for ONE roster machine, trimmed to a
    bounded length so a multi-machine chunk prompt stays bounded.

    Two sources, both already trusted elsewhere in this file for grounding
    an image prompt in real facts rather than an invention:
      - `entry["facts"]` (role/years/status/built_count) — the SAME coarse
        roster-item facts `_generate_blueprint_view` already grounds a
        never-built blueprint prompt with (see that function below). Always
        available for a locked roster entry; no lookup required.
      - `card` (this machine's own `machine_research_cards` row) —
        `timeframe` and `visual_identity` are the schema's own image-brief/
        on-screen fields (pipeline_executor.py's card-generation prompt:
        "visual_identity is Producer File/image-brief basis only"), and any
        `evidence_segments[].claim` whose `numeric_tokens` is non-empty is
        the schema's own marker for a sourced number ("numeric_tokens must
        list every number-like token used by claim ... present in claim or
        source_excerpt" — never invented). `card` may be None (no card yet,
        or this roster slot's card failed to persist) — degrades gracefully
        to roster-entry facts only.
    """
    parts: list[str] = []
    if isinstance(entry, dict):
        entry_facts = entry.get("facts") or {}
        for key in ("role", "years", "status", "built_count"):
            value = str(entry_facts.get(key) or "").strip()
            if value:
                parts.append(f"{key.replace('_', ' ')}: {value}")
    if isinstance(card, dict):
        timeframe = str(card.get("timeframe") or "").strip()
        if timeframe:
            parts.append(f"timeframe: {timeframe}")
        visual_identity = str(card.get("visual_identity") or "").strip()
        if visual_identity:
            parts.append(f"visual identity: {visual_identity}")
        numeric_claims = []
        for segment in card.get("evidence_segments") or []:
            if not isinstance(segment, dict):
                continue
            tokens = segment.get("numeric_tokens")
            claim = str(segment.get("claim") or "").strip()
            if claim and isinstance(tokens, list) and tokens:
                numeric_claims.append(claim)
        if numeric_claims:
            parts.append(
                "sourced numeric claims: "
                + " | ".join(numeric_claims[:_CARD_NUMERIC_CLAIM_LIMIT])
            )
    return " ; ".join(parts)[:_CARD_FACTS_MAX_CHARS]


async def _machine_research_cards_by_scene(
    tenant_id: str, video_id: str, scenes: list[dict], roster_entries: list[dict],
) -> dict[int, dict]:
    """Scene number -> that scene's own raw `machine_research_cards` row
    (`roster_index == scene`, the same positional resolution
    `_research_card_facts_by_scene` below uses — see its docstring). The
    ONE query against this table for the whole scene set; every other
    reader of a scene's research card (the planner's fact-text builder
    below, and `_one_scene`'s `blueprint_override` check — G27,
    2026-08-04) goes through this function's result rather than opening a
    second query path. Empty dict when there is no locked machine roster
    or no scene numbers fall inside it."""
    if not roster_entries:
        return {}
    indices = sorted({
        sc for s in scenes
        if isinstance((sc := s.get("scene")), int) and 1 <= sc <= len(roster_entries)
    })
    if not indices:
        return {}
    rows = await fetch_all(
        "SELECT roster_index, card FROM machine_research_cards "
        "WHERE tenant_id=$1 AND video_id=$2 AND roster_index = ANY($3::int[])",
        tenant_id, video_id, indices,
    )
    cards_by_index: dict[int, dict] = {}
    for row in rows or []:
        card = row.get("card")
        if isinstance(card, str):
            try:
                card = json.loads(card)
            except (ValueError, TypeError):
                card = None
        if isinstance(card, dict):
            cards_by_index[row.get("roster_index")] = card
    return cards_by_index


async def _research_card_facts_by_scene(
    tenant_id: str, video_id: str, scenes: list[dict], roster_entries: list[dict],
    cards_by_scene: Optional[dict[int, dict]] = None,
) -> dict[int, str]:
    """Scene number -> "<machine name> — <sourced facts>" for every scene
    whose positional roster entry (`roster_entries[scene - 1]`) has usable
    facts (see the module comment above `_machine_facts_for_planner`).
    Empty dict when there is no locked machine roster — the ordinary
    non-machine static-docu path is completely unaffected.

    ``cards_by_scene``, when supplied, is used as-is instead of issuing a
    fresh query — the caller already fetched it once via
    `_machine_research_cards_by_scene` for this same video/scene set."""
    if not roster_entries:
        return {}
    indices = sorted({
        sc for s in scenes
        if isinstance((sc := s.get("scene")), int) and 1 <= sc <= len(roster_entries)
    })
    if not indices:
        return {}
    cards_by_index = (
        cards_by_scene if cards_by_scene is not None
        else await _machine_research_cards_by_scene(
            tenant_id, video_id, scenes, roster_entries)
    )

    out: dict[int, str] = {}
    for sc in indices:
        entry = roster_entries[sc - 1]
        text = _machine_facts_for_planner(entry, cards_by_index.get(sc))
        if text:
            out[sc] = f"{entry.get('name') or ''} — {text}"
    return out


async def _scene_subjects_chunk(client: Any, model: Optional[str], facts: str,
                                chunk: list[dict],
                                card_facts_by_scene: Optional[dict[int, str]] = None,
                                ) -> Optional[dict[int, dict]]:
    """One planning call for a chunk of scenes.

    Returns None when the reply could not be parsed as a JSON array at all
    (the truncation failure mode) — the caller retries once, then gives up
    on just this chunk rather than the whole roster.
    """
    listing_items = []
    for s in chunk:
        line = f"[{s['scene']}] {(s['scene_text'] or '')[:800]}"
        scene_card_facts = (card_facts_by_scene or {}).get(s["scene"])
        if scene_card_facts:
            # Attached to THIS segment only (never pooled with the chunk's
            # other machines) so the model can never cite one segment's
            # machine using another segment's sourced numbers.
            line += f"\nSOURCED RESEARCH FOR THIS SEGMENT'S MACHINE: {scene_card_facts}"
        listing_items.append(line)
    listing = "\n\n".join(listing_items)
    kwargs: dict[str, Any] = {
        "prompt": _SUBJECT_HEADER.format(facts=facts or "(none)", segments=listing),
        "max_tokens": _subjects_chunk_max_tokens(len(chunk)),
    }
    if model:
        kwargs["model"] = model
    raw = await client.generate(**kwargs)
    items = _parse_json_array(raw or "")
    if items is None:
        return None
    out: dict[int, dict] = {}
    for item in items:
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


async def _scene_subjects(
    tenant_id: str, scenes: list[dict], research_payload: Optional[dict],
    video_id: Optional[str] = None, roster_entries: Optional[list[dict]] = None,
    cards_by_scene: Optional[dict[int, dict]] = None,
) -> tuple[dict[int, dict], list[int]]:
    """Grounded subject, title-card, and detail metadata for every scene,
    planned in chunks of _SUBJECTS_CHUNK_SIZE scenes per Claude call (see the
    module comment above for why one call per whole roster used to truncate
    on large videos).

    ``video_id``/``roster_entries`` are additive (both optional, default to
    no per-machine facts): when the video is on the locked machine-
    documentary roster path, they let each chunk carry that segment's own
    sourced research-card facts (see the G25 module comment above
    `_machine_facts_for_planner`) — without them this degrades to the
    original fact_sheet/dossier/headline-only behavior. ``cards_by_scene``
    is additive too: when the caller already fetched raw research cards via
    `_machine_research_cards_by_scene` (e.g. to also check `_one_scene`'s
    `blueprint_override`, G27), pass them here so this function's own card
    lookup reuses that fetch instead of re-querying.

    Returns (subjects, unparseable_scenes). unparseable_scenes lists the
    scene numbers whose chunk never produced a parseable reply even after
    one retry — a genuine planning failure, distinct from the ordinary
    per-scene case where the model replied but didn't supply a sourced spec.
    """
    from kie_unified import get_text_client_for_tenant

    facts = ""
    if isinstance(research_payload, dict):
        facts = "\n".join(
            f"[{k}] {str(research_payload.get(k) or '')[:1200]}"
            for k in ("fact_sheet", "character_dossier", "headline")
            if research_payload.get(k))
    card_facts_by_scene: dict[int, str] = {}
    if video_id and roster_entries:
        card_facts_by_scene = await _research_card_facts_by_scene(
            tenant_id, video_id, scenes, roster_entries,
            cards_by_scene=cards_by_scene)
    client = await get_text_client_for_tenant(tenant_id)
    model = claude_model_for_direct_client(client)

    out: dict[int, dict] = {}
    unparseable: list[int] = []
    for i in range(0, len(scenes), _SUBJECTS_CHUNK_SIZE):
        chunk = scenes[i:i + _SUBJECTS_CHUNK_SIZE]
        result = None
        for _attempt in range(2):  # one retry on an unparseable/truncated reply
            result = await _scene_subjects_chunk(
                client, model, facts, chunk, card_facts_by_scene)
            if result is not None:
                break
        if result is None:
            unparseable.extend(s["scene"] for s in chunk)
            continue
        out.update(result)
    return out, unparseable


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
        "render_mode, research_payload FROM videos "
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

    # Roster reference layer (G24): the video's own LOCKED machine roster,
    # with each entry's name/aliases/facts — see _roster_entry_for_scene_
    # machine below for why this is needed even though every roster machine
    # with a verified photo already sits in static_reference_cache (the
    # SAME table LAYER 0 above already checks). Lazy import: static_docu <->
    # pipeline_executor is a two-way relationship (pipeline_executor already
    # imports static_docu lazily), so importing at module top would risk a
    # circular import — same reasoning as prefetch_roster_references/
    # seed_reference_from_url's own lazy imports of this function.
    from pipeline_executor import _machine_documentary_hold_roster_entries
    roster_entries = _machine_documentary_hold_roster_entries(v)

    # Fetched once, shared by the planner's card-facts grounding (G25) and
    # `_one_scene`'s `blueprint_override` operator-metadata check (G27,
    # 2026-08-04) — see `_machine_research_cards_by_scene`'s docstring for
    # why no other call site may open a second query against this table.
    cards_by_scene = await _machine_research_cards_by_scene(
        tenant_id, video_id, scenes, roster_entries)

    _p("Identifying each segment's machine…")
    subjects, unparseable_scenes = await _scene_subjects(
        tenant_id, scenes, rp, video_id=video_id, roster_entries=roster_entries,
        cards_by_scene=cards_by_scene)
    unparseable_scene_set = set(unparseable_scenes)

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

        # Never-built detection (Ryan's decision, 2026-08-04): resolve this
        # scene's machine against the video's own locked roster — the SAME
        # resolution the reference hunt's LAYER 0b re-uses below (computed
        # once here so it's never done twice) — and check whether
        # pipeline_executor already classified that roster entry as never
        # built: a cancelled programme with zero physical hulls/airframes
        # ever completed (_roster_entry_never_built). That machine can
        # never have a reference photograph, so this scene takes the
        # blueprint path (2 monochrome technical-drawing views, no
        # reference/anchor image) below instead of the photo-grounded
        # reference hunt, which would otherwise correctly — but
        # permanently and unhelpfully — block it forever.
        #
        # G26 (2026-08-04, live bug on video d2e37cd6 scenes 9/13): this
        # name-resolution is alias-aware but fails CLOSED (returns None) on
        # any designation collision across two roster entries — exactly the
        # live "CVA-01" collision the docstring above already documents
        # (both "CVA-01 class" and "Audacious class / Malta class" normalize
        # to the same token). When the collision's never-built entry is the
        # one that actually IS this scene's machine, name-resolution alone
        # leaves `roster_entry` None, `never_built` False, and the scene
        # falls into the ordinary photo-hunt path forever — a permanent
        # `blocked_no_reference` for a machine that can never have a photo.
        # `_research_card_facts_by_scene`'s own module comment (above)
        # already established the fix for this exact render mode: scene
        # numbering for a locked machine-documentary roster is POSITIONAL,
        # not name-guessed — `pipeline_executor._run_static_script_hold`
        # writes `scene = roster.index(machine) + 1`, so scene sc's machine
        # IS `roster_entries[sc - 1]`, unambiguously, with no alias matching
        # or collision risk at all. That positional entry is the PRIMARY
        # source for never-built detection and the blueprint's grounding
        # facts; name-resolution (`roster_entry`) is only the fallback, for
        # when the positional entry isn't available (no locked roster, or a
        # roster shorter than this scene number — non-machine-documentary
        # static-docu formats, which never populate `roster_entries`, hit
        # this fallback and see no behavior change at all).
        #
        # LAYER 0b's reference-photo lookup below is deliberately UNTOUCHED
        # — it keeps using the name-resolved `roster_entry`, because a
        # false-positive positional match there would risk reusing the
        # WRONG machine's cached photo for this scene. Never-built detection
        # has no such risk (a never-built entry never has a cached photo to
        # misapply), so the positional entry is safe to trust as primary
        # there.
        roster_entry = (
            _roster_entry_for_scene_machine(roster_entries, machine, sub.get("aliases"))
            if roster_entries else None
        )
        positional_roster_entry = (
            roster_entries[sc - 1]
            if roster_entries and 1 <= sc <= len(roster_entries)
            else None
        )
        never_built_entry = (
            positional_roster_entry
            if positional_roster_entry is not None
            else roster_entry
        )
        never_built = bool(never_built_entry and never_built_entry.get("never_built"))

        # Operator override (G27, 2026-08-04, Ryan's call on video d2e37cd6
        # scene 9): the CVA-01 cancellation story sits on the "Audacious
        # class / Malta class" roster slot, which is correctly VETOED from
        # never-built detection above (Eagle R05 was completed for that
        # class — see the docstring on pipeline_executor.
        # _roster_entry_never_built). A photo of the real Eagle under a
        # CVA-01 caption would be dishonest, so an operator can mark THIS
        # scene's research card (`machine_research_cards`, `roster_index ==
        # sc` — the SAME positional resolution as everything else on this
        # page, sourced from `cards_by_scene`/`_machine_research_cards_by_
        # scene` computed once above, never a second query) with
        # `blueprint_override: true` to force the blueprint path exactly as
        # if `never_built` were true. Grounding is unaffected by this flag:
        # the card's own facts already flow into `caption_specs` via the
        # G25 planner-grounding path above, and `_generate_blueprint_view`
        # below still reads `never_built_entry` (the positional roster
        # entry) for its role/years/status/built_count block, so a blueprint
        # view is grounded in card facts + positional entry either way.
        # Strict `is True` — a stringy "true" or any other truthy JSON value
        # must never engage this — because this is operator metadata, not a
        # fact claim: it must never alter never-built DETECTION for any
        # other scene, and it never touches the photo path, the roster
        # gate, or the card referee, all of which are untouched above/below.
        scene_card = (cards_by_scene or {}).get(sc)
        blueprint_override = bool(scene_card) and scene_card.get("blueprint_override") is True
        never_built = never_built or blueprint_override

        view_plans_for_scene = NEVER_BUILT_VIEW_PLANS if never_built else STATIC_VIEW_PLANS

        # Skip-if-done / FILL resumability (2026-08-03, extended same day): a
        # whole-video images run must not re-bill scenes whose views were
        # already generated and approved under the CURRENT view contract —
        # the unconditional DELETE further down used to wipe and re-spend
        # every scene on every re-run. A role counts as done when it has a
        # 'done' row (image_url set) whose stored caption.view_role is one
        # of THIS contract's current roles; a role counts as PARKED when its
        # row is 'qa_rejected' instead (a paid render that failed QA and is
        # waiting on either a human approval or a fresh attempt here). Rows
        # from a superseded contract (e.g. the pre-fix three_quarter/
        # top_oblique/engineering_detail roster) do NOT match the current
        # role set and so land in neither bucket.
        #
        # Below STATIC_VIEWS_MINIMUM done roles: unchanged full-regenerate
        # behavior (delete everything for this scene, generate all roles
        # fresh) — see the DELETE further down.
        #
        # At or above STATIC_VIEWS_MINIMUM done roles: FILL mode. Before this
        # fix a scene sitting at 2/3 done + 1 parked (HMS Argus's actual
        # live state) could NEVER regenerate its missing role through any
        # door — no force flag or redraw endpoint bypasses this skip. FILL
        # mode keeps the done rows completely untouched (no delete, no
        # regeneration) and attempts generation ONLY for roles that still
        # lack a 'done' row. A stale parked row for a role being retried
        # here is deleted only once its replacement attempt actually starts
        # (right when the new placeholder row for that role is created
        # below) — never up front — so a fresh failure re-parks under a new
        # row instead of losing the trail if this run never gets that far.
        # A scene with ALL target roles already done has an empty
        # `missing_plans` and keeps the original instant-skip behavior (no
        # queries beyond this SELECT).
        current_roles = {plan["role"] for plan in view_plans_for_scene}
        role_view_index = {
            plan["role"]: idx for idx, plan in enumerate(view_plans_for_scene, start=1)
        }
        existing_rows = await fetch_all(
            "SELECT id, status, image_url, caption FROM assets WHERE "
            "video_id=$1 AND tenant_id=$2 AND scene=$3 AND generation_method=$4",
            video_id, tenant_id, sc, STATIC_RENDER_MODE,
        )
        # G26: whether a PRIOR run already parked a blocked_missing_metadata
        # placeholder for this scene — computed straight off existing_rows
        # (not the loop below, since that loop skips any row whose role
        # isn't one of THIS contract's view roles, and
        # "blocked_missing_metadata" deliberately never is one). Used below
        # to make both cleanup deletes conditional: a scene that has never
        # bounced must never emit an extra no-op DELETE query.
        has_stale_blocked_metadata_row = any(
            (row or {}).get("status") == "blocked_missing_metadata"
            for row in existing_rows or []
        )

        done_role_ids: dict = {}
        done_role_urls: dict = {}
        parked_role_ids: dict = {}
        for row in existing_rows or []:
            cap = row.get("caption")
            if isinstance(cap, str):
                try:
                    cap = json.loads(cap)
                except (ValueError, TypeError):
                    cap = None
            if not isinstance(cap, dict):
                continue
            role = cap.get("view_role")
            if role not in current_roles:
                continue
            status = row.get("status")
            if status == "done" and row.get("image_url"):
                done_role_ids[role] = row.get("id")
                done_role_urls[role] = row.get("image_url")
            elif status == "qa_rejected":
                parked_role_ids[role] = row.get("id")

        # Anchor selection (chained-view fix): the scene's later views chain
        # off its OWN first verified render rather than the raw historical
        # reference photo (see `_studio_prompt`'s `from_anchor` docstring for
        # why). `anchor_url`/`anchor_role` start unset — FILL mode below is
        # the only branch that can seed them from a PRE-EXISTING done row;
        # full-regenerate mode (below STATIC_VIEWS_MINIMUM done roles) starts
        # every scene from scratch, so its first generated view still has no
        # anchor and uses the reference photo, exactly like today. Preferring
        # STATIC_VIEW_PLANS order (not row/creation order) makes the choice
        # deterministic when more than one role is already done — this is
        # the live Argus case: side_profile + top_planform both done,
        # three_quarter missing, side_profile wins because it is earlier in
        # STATIC_VIEW_PLANS.
        anchor_url: Optional[str] = None
        anchor_role: Optional[str] = None

        missing_plans: Optional[list] = None  # None == full regenerate, below
        if len(done_role_ids) >= STATIC_VIEWS_MINIMUM:
            missing_plans = [
                plan for plan in view_plans_for_scene
                if plan["role"] not in done_role_ids
            ]
            if not missing_plans:
                _p(
                    f"Segment {sc}: {len(done_role_ids)} approved views "
                    "already match the current view contract — skipping "
                    "(no regeneration, no spend)."
                )
                return {"scene": sc, "done": len(done_role_ids), "reason": None}
            for plan in view_plans_for_scene:
                url = done_role_urls.get(plan["role"])
                if url:
                    anchor_url, anchor_role = url, plan["role"]
                    break
            _p(
                f"Segment {sc}: {len(done_role_ids)} approved views already "
                "match the current view contract — filling "
                f"{len(missing_plans)} missing view(s) "
                f"({', '.join(p['role'] for p in missing_plans)}); existing "
                "views left untouched"
                + (
                    f", chained off the existing {anchor_role} render."
                    if anchor_role else "."
                )
            )

        caption_title = sub.get("caption_title") or machine
        caption_sub = sub.get("caption_sub") or ""
        caption_specs = [
            str(spec).strip() for spec in (sub.get("caption_specs") or [])
            if str(spec).strip()
        ][:2]
        detail_focus = sub.get("detail_focus") or "overall machine geometry"

        def _caption(view_plan: dict) -> dict:
            cap = {
                "title": caption_title,
                "sub": caption_sub,
                "specs": caption_specs,
                "view_role": view_plan["role"],
                "view_label": view_plan["label"],
                # len(view_plans_for_scene) == STATIC_VIEWS_TARGET (3) for an
                # ordinary photo-bearing scene — unchanged value, just no
                # longer a separate hardcoded constant — and 2 for a
                # never-built scene, so the frontend readiness panel
                # (frontend/src/lib/static-docu.ts) shows "2/2", never a
                # permanently-unreachable "2/3".
                "target_views": len(view_plans_for_scene),
                "minimum_views": STATIC_VIEWS_MINIMUM,
            }
            if never_built:
                # Honest-caption requirement (Ryan's decision, 2026-08-04):
                # a blueprint view must never be mistaken for a real photo.
                # render_static.py's _build_render_config reads caption_sub
                # STRAIGHT from this dict and Scene.tsx's DocumentaryTitleCard
                # renders it verbatim, so prefixing it here is sufficient —
                # no Remotion-side change needed. design_study=True is the
                # machine-readable marker for the same fact.
                cap["design_study"] = True
                cap["sub"] = f"{_NEVER_BUILT_CAPTION_PREFIX} • {caption_sub}"
            return cap

        async def _insert_placeholder(view_index: int, view_plan: dict,
                                      reference_url: Optional[str] = None,
                                      status: str = "generating",
                                      image_prompt: Optional[str] = None) -> str:
            new_id = str(uuid.uuid4())
            await execute(
                "INSERT INTO assets (id, tenant_id, video_id, scene, image_index, "
                "sentence_index, sentence_text, shot_type, video_title, aspect_ratio, "
                "status, hero_shot, generation_method, caption, drive_image_url, "
                "image_prompt) "
                "VALUES ($1,$2,$3,$4,$5,$5,$6,$7,$8,$9,$14,$10,$11,$12,$13,$15)",
                new_id, tenant_id, video_id, sc, view_index,
                (s["scene_text"] or "")[:500], view_plan["shot_type"],
                v["video_title"], v["aspect"], view_index == 1,
                STATIC_RENDER_MODE, json.dumps(_caption(view_plan)), reference_url,
                status, image_prompt,
            )
            return new_id

        # G26 (2026-08-04, live: video d2e37cd6 scene 19 "Nairana class"):
        # the metadata gate below used to `return` the moment title-card
        # metadata was incomplete — BEFORE `_insert_placeholder` ever ran for
        # this scene. That left the scene with ZERO asset rows: invisible to
        # every count/review that reads the assets table (video_summary's
        # `pics`, the frontend readiness panel, this same function's own
        # `_bounded` timeout cleanup), not merely "blocked" like a failed
        # reference hunt (`blocked_no_reference`, later in this function,
        # which at least reuses an already-inserted row). A scene stuck here
        # looked identical to a scene that was simply never attempted yet.
        #
        # Fix: insert ONE placeholder row carrying the reason, using the SAME
        # `_insert_placeholder` machinery every real view uses — just with a
        # dedicated status and the bounce reason in image_prompt instead of a
        # real generation. image_url stays NULL (the INSERT never sets it),
        # so this can never be counted as done/ready anywhere: video_summary
        # counts `image_url IS NOT NULL`; frame_arbiter and the images
        # readiness check filter `status = 'done'`; the frontend's
        # BLOCKED_VIEW_STATUSES set (frontend/src/lib/static-docu.ts) now
        # includes this status so the unit reads "blocked", not "not
        # started". The synthetic view_plan's role ("blocked_missing_
        # metadata") is deliberately outside `view_plans_for_scene`'s real
        # roles, so it can never satisfy `current_roles` on a later run —
        # meaning a later run always treats this scene as 0/N done and takes
        # the full-regenerate branch below, whose blanket DELETE (scoped to
        # this scene's own generation_method rows) sweeps this placeholder
        # away before writing real views. A repeat bounce (still missing
        # metadata) never reaches that DELETE — it returns from this same
        # gate again — so the row is deleted here first, up front, to keep
        # "exactly one" true across repeated bounces too.
        if not caption_sub or "•" not in caption_sub or not caption_specs:
            if sc in unparseable_scene_set:
                reason = "subject_planning_unparseable"
                bounce_detail = (
                    f"[metadata-bounce] subject planning failed for this segment "
                    f"(the model's reply for its batch could not be parsed as JSON, "
                    f"even after a retry) for {machine}"
                )
                _p(
                    f"Segment {sc}: subject planning failed for this scene "
                    "(the model's reply for its batch could not be parsed as "
                    "JSON, even after a retry) — no images generated."
                )
            else:
                reason = "missing_title_metadata"
                bounce_detail = (
                    f"[metadata-bounce] planner produced no sourced spec for {machine}"
                )
                _p(
                    f"Segment {sc}: title-card metadata is incomplete for {machine} "
                    "(operator/service years and at least one sourced spec required) "
                    "— no images generated."
                )
            if has_stale_blocked_metadata_row:
                # A repeat bounce — remove the PREVIOUS attempt's placeholder
                # first so "exactly one" holds across N consecutive bounces.
                # A fresh scene (no stale row) skips this no-op query.
                await execute(
                    "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
                    "AND generation_method=$4 AND status=$5",
                    video_id, tenant_id, sc, STATIC_RENDER_MODE, "blocked_missing_metadata")
            await _insert_placeholder(
                0,
                {"role": "blocked_missing_metadata",
                 "label": "Blocked — missing metadata", "shot_type": None},
                status="blocked_missing_metadata", image_prompt=bounce_detail,
            )
            return {"scene": sc, "done": 0, "reason": reason}

        # Subject planning succeeded this run — clear a stale
        # `blocked_missing_metadata` placeholder a PRIOR run's bounce parked
        # for this scene (see the gate above), ahead of the FILL-vs-full-
        # regenerate branch below: the full-regenerate DELETE a few lines
        # down only fires in ITS branch and FILL mode never reaches it, so
        # without this a stale bounce row surviving into a FILL-mode scene
        # (already >= STATIC_VIEWS_MINIMUM done from an earlier run) would
        # never get swept once planning starts succeeding again. Gated on
        # has_stale_blocked_metadata_row so an ordinary scene that never
        # bounced (the overwhelming common case) never emits this query.
        if has_stale_blocked_metadata_row:
            await execute(
                "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
                "AND generation_method=$4 AND status=$5",
                video_id, tenant_id, sc, STATIC_RENDER_MODE, "blocked_missing_metadata")

        # Placeholder row FIRST: the media proxy only serves file ids present
        # in allowlisted DB columns, and the self-hosted reference must be
        # proxy-fetchable during generation. image_url stays NULL until the
        # real image exists, so a concurrent render can't pick up the raw ref.
        #
        # FILL mode (missing_plans set above) must NOT run this blanket
        # DELETE — it would destroy the done rows just decided to keep
        # untouched. Full-regenerate mode (missing_plans is None, below
        # STATIC_VIEWS_MINIMUM done roles) keeps the original wipe-everything
        # behavior and generates all roles fresh.
        if missing_plans is None:
            await execute(
                "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
                "AND generation_method=$4", video_id, tenant_id, sc, STATIC_RENDER_MODE)
            plans_to_generate = list(view_plans_for_scene)
        else:
            plans_to_generate = missing_plans

        first_plan = plans_to_generate[0]
        row_id = await _insert_placeholder(role_view_index[first_plan["role"]], first_plan)
        stale_parked_id = parked_role_ids.get(first_plan["role"])
        if stale_parked_id:
            # This role's replacement attempt just started (the new
            # placeholder row above) — drop the old parked row now so a
            # fresh failure re-parks under the NEW row instead of leaving
            # two rows behind for the same role.
            await execute("DELETE FROM assets WHERE id=$1", stale_parked_id)

        # 1) Find a REAL photo, SELF-HOST it (Wikimedia 403s Kie's fetcher),
        #    and vision-check it actually shows this machine (designation
        #    collisions like the Russian T-95 vs the US T95).
        #    LAYER 0: the tenant's own verified-reference cache — series reuse
        #    the same machines across videos, so each machine costs ONE
        #    Wikimedia conversation ever (and rate limits stop mattering).
        #    LAYER 0b: THIS VIDEO's own locked roster reference photo,
        #    resolved by matching this scene's guessed machine label against
        #    the roster's own name/aliases (_roster_entry_for_scene_machine)
        #    — catches a roster machine the tenant cache already verified
        #    weeks ago under its own compound display name (G24).
        #    LAYER 1: the machine's Wikipedia article lead image — curated,
        #    unambiguous, and API-issued. LAYER 1.5: every other real photo
        #    embedded in that SAME article (find_article_images) — the lead
        #    image is sometimes a diagram or missing entirely for an obscure
        #    prototype, but the article body usually carries a period photo
        #    further down. LAYER 2: Commons search for extra candidates/angles.
        #
        #    Never-built machines (Ryan's decision, 2026-08-04) skip this
        #    ENTIRE reference hunt — and the FAIL CLOSED gate below it —
        #    outright: no photo can ever exist, so ref_url simply stays
        #    unset and the blueprint path (_generate_blueprint_view below)
        #    never uses it.
        ref_url = None
        ref_src = None
        mkey = _machine_key(machine)
        if never_built:
            _p(f"Segment {sc}: {machine} was never built — generating a "
               "monochrome technical blueprint instead of a photo-grounded "
               "render.")
        else:
            cached = await fetch_one(
                "SELECT hosted_url, source_url FROM static_reference_cache "
                "WHERE tenant_id=$1 AND machine_key=$2", tenant_id, mkey)
            if cached:
                ref_url, ref_src = cached["hosted_url"], cached["source_url"]
                await execute(
                    "UPDATE assets SET drive_image_url=$2 WHERE id=$1", row_id, ref_url)
                _p(f"Segment {sc}: using the cached verified photo of the {machine}")

            # LAYER 0b (G24): the video's OWN verified roster reference photo.
            # LAYER 0 above misses whenever this scene's own guessed "machine"
            # label doesn't normalize to the SAME cache key as the roster
            # entry's compound display name (see _roster_entry_for_scene_machine
            # for why that's the common case, not the exception, for ship-class
            # roster entries) — even though the roster already holds a verified
            # photo for the exact machine this scene is about, written by
            # prefetch_roster_references weeks before script/voice money was
            # ever spent. Only tried when LAYER 0 missed, and only ACCEPTED
            # after the resolved candidate passes the SAME _vision_confirms
            # identity check every other candidate must clear — the alias
            # resolution is a lead, never a blind reuse. trusted_source=True is
            # honest here: nothing reaches static_reference_cache without
            # already having cleared _vision_confirms once, at roster-prefetch
            # or manual-seed time (_prefetch_one_machine / seed_reference_from_
            # url both gate their INSERT on that same call), so this candidate
            # carries the same "already vision-confirmed once" provenance a
            # Wikipedia lead image carries — never an unverified guess.
            #
            # `roster_entry` is the SAME resolution already computed once at
            # the top of _one_scene for never-built detection — reused here
            # rather than calling _roster_entry_for_scene_machine a second
            # time for the exact same (roster_entries, machine, aliases).
            if not ref_url and roster_entry:
                roster_mkey = _machine_key(roster_entry["name"])
                roster_cached = await fetch_one(
                    "SELECT hosted_url, source_url FROM static_reference_cache "
                    "WHERE tenant_id=$1 AND machine_key=$2", tenant_id, roster_mkey)
                if roster_cached:
                    roster_hosted = roster_cached["hosted_url"]
                    await execute(
                        "UPDATE assets SET drive_image_url=$2 WHERE id=$1",
                        row_id, roster_hosted)
                    if await _vision_confirms(
                        tenant_id, roster_hosted, machine, sub.get("aliases"),
                        trusted_source=True, facts=roster_entry.get("facts"),
                        source_label=roster_entry["name"],
                    ):
                        ref_url, ref_src = roster_hosted, roster_cached["source_url"]
                        await execute(
                            """INSERT INTO static_reference_cache
                                   (tenant_id, machine_key, machine, hosted_url, source_url)
                               VALUES ($1,$2,$3,$4,$5)
                               ON CONFLICT (tenant_id, machine_key)
                               DO UPDATE SET machine=$3, hosted_url=$4, source_url=$5,
                                             verified_at=now()""",
                            tenant_id, mkey, machine[:200], roster_hosted,
                            roster_cached["source_url"])
                        _p(f"Segment {sc}: using the video's own verified "
                           f"roster photo for the {machine} (roster entry: "
                           f"{roster_entry['name']})")
                    else:
                        _p(f"Segment {sc}: the roster's photo for "
                           f"{roster_entry['name']} didn't pass identity "
                           f"check for the {machine} — falling back to a "
                           f"fresh search")

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
            # Never reached for a never-built scene (see the branch above).
            if not ref_url:
                _p(f"Segment {sc}: no verified reference photo found for the "
                   f"{machine} — scene BLOCKED (no image generated). Seed "
                   f"static_reference_cache (tenant_id, machine_key, machine, "
                   f"hosted_url, source_url) and re-run this scene.")
                await execute(
                    "UPDATE assets SET status='blocked_no_reference', "
                    "image_url=NULL, drive_image_url=NULL WHERE id=$1", row_id)
                return {"scene": sc, "done": 0, "reason": "blocked_no_reference"}

        # 2) Generate the remaining planned views sequentially for this
        # scene (all three roles in full-regenerate mode, only the missing
        # roles in FILL mode). Scene concurrency remains six, but a single
        # aircraft never opens more than one provider call at once. Every
        # view keeps the same verified reference/variant lock and passes the
        # same two-judge QA path.
        row_ids = [row_id]
        for view_plan in plans_to_generate[1:]:
            new_row_id = await _insert_placeholder(
                role_view_index[view_plan["role"]], view_plan, reference_url=ref_url
            )
            stale_parked_id = parked_role_ids.get(view_plan["role"])
            if stale_parked_id:
                await execute("DELETE FROM assets WHERE id=$1", stale_parked_id)
            row_ids.append(new_row_id)

        async def _generate_blueprint_view(view_index: int, view_plan: dict,
                                           view_row_id: str) -> bool:
            """Never-built machine (Ryan's decision, 2026-08-04): no
            reference photo exists or ever will, so this view is a
            monochrome technical-drawing design study instead of a
            photo-grounded studio render. Pure text-to-image
            (reference_image_url=None passed to generate_scene_image_gpt)
            — no reference or anchor input at all, since chained/identity
            QA against a photo makes no sense when there is no photo.
            Role-conformance QA (`_view_role_confirms`) is UNCHANGED and
            still applies: a "side elevation" must still read side-on.
            Same budget-check/ledger/park/retry SHAPE as the photo path's
            `_generate_view` below — deliberately a separate function
            rather than threading `never_built` branches through that
            250-line function, so the (unchanged, load-bearing) photo path
            stays exactly as it was before this feature."""
            grounding_facts = list(caption_specs)
            for key in ("role", "years", "status", "built_count"):
                # `never_built_entry` (positional-first, see the comment at
                # this scene's never-built detection above) — the same
                # entry that decided this scene takes the blueprint path in
                # the first place, so its facts are the ones that actually
                # describe this scene's machine.
                value = (never_built_entry or {}).get("facts", {}).get(key)
                if value:
                    grounding_facts.append(f"{key.replace('_', ' ')}: {value}")

            prompt = _blueprint_prompt(machine, view_plan, grounding_facts)
            _p(
                f"Segment {sc}/{len(scenes)}, view {view_index}/"
                f"{len(view_plans_for_scene)}: {view_plan['label']} "
                "(never built — monochrome blueprint design study)…"
            )

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

            async def _park_blueprint(candidate_url: str, prompt_used: str, *,
                                      qa_events: Optional[list] = None) -> None:
                """Mirrors `_park` below (paid renders are parked for human
                review, never deleted) minus the reference/input-marker
                bookkeeping that doesn't apply here — there is no reference
                or anchor image for a blueprint view."""
                parked_url = candidate_url
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
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "static_docu._park_blueprint: failed to re-host "
                        "rejected render for scene %s view %s (%s) — "
                        "parking with the ephemeral provider URL instead",
                        sc, view_index, exc,
                    )
                reason_block = ""
                if qa_events:
                    attempt_counts: dict = {}
                    marker_parts = []
                    for kind, reason in qa_events:
                        if not reason:
                            continue
                        attempt_counts[kind] = attempt_counts.get(kind, 0) + 1
                        marker_parts.append(
                            f"[{kind}-qa-reject attempt {attempt_counts[kind]}] "
                            f"{reason}"
                        )
                    reason_block = " ".join(marker_parts)[:400]
                await execute(
                    "UPDATE assets SET status='qa_rejected', image_url=NULL, "
                    "drive_image_url=$2, image_prompt=$3 WHERE id=$1",
                    view_row_id, parked_url,
                    (
                        "[never-built: blueprint] " + prompt_used[:900]
                        + (f" {reason_block}" if reason_block else "")
                    ),
                )

            res = await ic.generate_scene_image_gpt(
                prompt, None, aspect_ratio=v["aspect"], allow_fallback=False,
                resolution="1K",
            )
            url = (res or {}).get("url")
            if not url:
                await execute("DELETE FROM assets WHERE id=$1", view_row_id)
                return False
            await record_ledger_entry(
                tenant_id=tenant_id, video_id=video_id, stage="image",
                model="gpt-image-2", units=1, unit_cost=quote, actual_cost=quote,
            )

            qa_note = ""
            style_qa_events: list = []
            first_style_reason: list = []
            if not await _blueprint_render_confirms(
                tenant_id, url, machine, grounding_facts,
                reason_out=first_style_reason,
            ):
                if first_style_reason:
                    style_qa_events.append(("blueprint", first_style_reason[0]))
                _p(
                    f"Segment {sc}, view {view_index}: render is not a "
                    f"valid monochrome technical drawing of the {machine} "
                    "— one retry…"
                )
                retry_refusal = await budget_refusal(
                    tenant_id, video_id, quote, "this view's QA retry")
                url2 = None
                if retry_refusal:
                    _p(f"Segment {sc}, view {view_index}: {retry_refusal} — "
                       "keeping the first render unretried.")
                else:
                    res = await ic.generate_scene_image_gpt(
                        prompt, None, aspect_ratio=v["aspect"],
                        allow_fallback=False, resolution="1K",
                    )
                    url2 = (res or {}).get("url")
                    if url2:
                        await record_ledger_entry(
                            tenant_id=tenant_id, video_id=video_id, stage="image",
                            model="gpt-image-2", units=1, unit_cost=quote,
                            actual_cost=quote,
                        )
                second_style_reason: list = []
                if url2 and await _blueprint_render_confirms(
                    tenant_id, url2, machine, grounding_facts,
                    reason_out=second_style_reason,
                ):
                    url = url2
                else:
                    if url2 and second_style_reason:
                        style_qa_events.append(("blueprint", second_style_reason[0]))
                    await _park_blueprint(url2 or url, prompt, qa_events=style_qa_events)
                    return False

            # Role-conformance QA (unchanged): side elevation reads side-on;
            # plan reads top-down. Same judge, same retry shape as the photo
            # path — geometry is geometry whether the pixels are a photo or
            # a line drawing.
            role_qa_events: list = []
            first_role_reason: list = []
            if not await _view_role_confirms(
                tenant_id, url, machine, view_plan, reason_out=first_role_reason
            ):
                if first_role_reason:
                    role_qa_events.append(("role", first_role_reason[0]))
                _p(
                    f"Segment {sc}, view {view_index}: view does not match "
                    f"its {view_plan['label']} role — one retry with "
                    "stronger geometry wording…"
                )
                geometry_prompt = _blueprint_prompt(
                    machine, view_plan, grounding_facts, emphasize_geometry=True)
                geometry_refusal = await budget_refusal(
                    tenant_id, video_id, quote, "this view's role-conformance retry")
                role_retry_url = None
                if geometry_refusal:
                    _p(f"Segment {sc}, view {view_index}: {geometry_refusal} — "
                       "keeping the first render unretried.")
                else:
                    res = await ic.generate_scene_image_gpt(
                        geometry_prompt, None, aspect_ratio=v["aspect"],
                        allow_fallback=False, resolution="1K",
                    )
                    role_retry_url = (res or {}).get("url")
                    if role_retry_url:
                        await record_ledger_entry(
                            tenant_id=tenant_id, video_id=video_id, stage="image",
                            model="gpt-image-2", units=1, unit_cost=quote,
                            actual_cost=quote,
                        )
                second_role_reason: list = []
                role_retry_ok = False
                if role_retry_url:
                    role_retry_ok = await _view_role_confirms(
                        tenant_id, role_retry_url, machine, view_plan,
                        reason_out=second_role_reason,
                    )
                    if not role_retry_ok and second_role_reason:
                        role_qa_events.append(("role", second_role_reason[0]))
                style_retry_reason: list = []
                style_retry_ok = role_retry_ok and await _blueprint_render_confirms(
                    tenant_id, role_retry_url, machine, grounding_facts,
                    reason_out=style_retry_reason,
                )
                if role_retry_ok and not style_retry_ok and style_retry_reason:
                    role_qa_events.append(("blueprint", style_retry_reason[0]))
                if role_retry_url and role_retry_ok and style_retry_ok:
                    url = role_retry_url
                    prompt = geometry_prompt
                    qa_note += "[qa: role-conformance retry] "
                else:
                    await _park_blueprint(
                        role_retry_url or url,
                        geometry_prompt if role_retry_url else prompt,
                        qa_events=role_qa_events,
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
                "[never-built: blueprint] " + qa_note + prompt[:900],
            )
            return True

        async def _generate_view(view_index: int, view_plan: dict,
                                 view_row_id: str) -> bool:
            nonlocal anchor_url, anchor_role

            if never_built:
                return await _generate_blueprint_view(view_index, view_plan, view_row_id)

            # Chained generation: once this scene has ANY verified render
            # (from a prior run via FILL mode, or from an earlier view in
            # THIS run — set at the bottom of this function), every
            # subsequent view is generated from THAT render instead of the
            # raw historical reference photo. Fixed once set — later views
            # never re-chain off each other, only off the scene's first
            # verified render — so the choice stays deterministic and
            # traceable to one image. No anchor yet (fresh scene, first
            # view, or every prior view this run parked) falls back to the
            # reference photo exactly like before this fix.
            use_anchor = anchor_url is not None
            gen_input_url = anchor_url if use_anchor else ref_url
            input_marker = (
                f"[input: anchor {anchor_role}] " if use_anchor
                else "[input: reference] "
            )

            await execute(
                "UPDATE assets SET drive_image_url=$2 WHERE id=$1",
                view_row_id, gen_input_url,
            )
            prompt = _studio_prompt(
                machine, view_plan, detail_focus, from_anchor=use_anchor)
            _p(
                f"Segment {sc}/{len(scenes)}, view {view_index}/"
                f"{STATIC_VIEWS_TARGET}: {view_plan['label']}"
                f"{' (chained off ' + anchor_role + ')' if use_anchor else ''}…"
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

            async def _park(candidate_url: str, prompt_used: str, *,
                            qa_events: Optional[list] = None) -> None:
                """Park a paid-for render for per-view human review instead
                of deleting it — the 2026-07-22 QA-park fix's rule, shared
                by BOTH reject paths below (double identity-QA reject, and
                the new double role-conformance reject): a wrong-machine or
                wrong-angle render is still a paid render, never destroyed
                on a QA judge's word alone. Does not count toward the
                minimum-views render gate while parked.

                `qa_events` (2026-08-03 observability fix): an ordered list
                of (kind, reason_text) pairs — 'identity' or 'role' — one
                per failing judge call that led to this park. Rendered into
                image_prompt as '[<kind>-qa-reject attempt N] <reason>'
                markers (N counts per kind) so an operator can see WHAT the
                judge objected to without re-spending to regenerate and
                re-inspect it (live cost: HMS Argus video d2e37cd6 scene 1,
                4 role rejects across 2 runs with the verdict text thrown
                away every time). Best-effort observability only — never
                changes whether or how a row parks."""
                parked_url = candidate_url
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
                except Exception as exc:  # noqa: BLE001
                    # Best-effort re-hosting only: losing durability beats
                    # losing the render (and the row) entirely, so this must
                    # never crash or change the park outcome below — but it
                    # must not fail SILENTLY either, or an operator staring
                    # at an expired provider-URL thumbnail has no idea why.
                    _logger.warning(
                        "static_docu._park: failed to re-host rejected render "
                        "for scene %s view %s (%s) — parking with the "
                        "ephemeral provider URL instead", sc, view_index, exc,
                    )
                reason_block = ""
                if qa_events:
                    attempt_counts: dict = {}
                    marker_parts = []
                    for kind, reason in qa_events:
                        if not reason:
                            continue
                        attempt_counts[kind] = attempt_counts.get(kind, 0) + 1
                        marker_parts.append(
                            f"[{kind}-qa-reject attempt {attempt_counts[kind]}] "
                            f"{reason}"
                        )
                    reason_block = " ".join(marker_parts)[:400]
                await execute(
                    "UPDATE assets SET status='qa_rejected', image_url=NULL, "
                    "drive_image_url=$2, image_prompt=$3 WHERE id=$1",
                    view_row_id, parked_url,
                    (
                        (f"[ref: {ref_src}] " if ref_src else "")
                        + input_marker
                        + prompt_used[:900]
                        + (f" {reason_block}" if reason_block else "")
                    ),
                )

            # GPT Image 2 only, image input required, 1K. No fallback model
            # can silently trade historical accuracy for completion.
            # `gen_input_url` is the anchor when this view is chained, the
            # raw reference photo otherwise (see `use_anchor` above).
            res = await ic.generate_scene_image_gpt(
                prompt, gen_input_url, aspect_ratio=v["aspect"], allow_fallback=False,
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
            # Reason capture for observability (2026-08-03 fix): collected
            # from every identity-QA call that actually runs below and
            # handed to _park if this view ends up parked, so the marker
            # only ever reflects checks that ran against THIS view's own
            # attempts — never a stale reason from an earlier, since-
            # overruled reject.
            identity_qa_events: list = []
            first_identity_reason: list = []
            if not await _render_matches_reference(
                tenant_id, url, ref_url, machine, sub.get("aliases"),
                reason_out=first_identity_reason,
            ):
                if first_identity_reason:
                    identity_qa_events.append(("identity", first_identity_reason[0]))
                _p(
                    f"Segment {sc}, view {view_index}: render does not match "
                    f"the {machine} — one retry…"
                )
                identity_reproduce_desc = (
                    "supplied studio render" if use_anchor else "verified reference"
                )
                retry_prompt = (
                    f"Reproduce the machine in the {identity_reproduce_desc} "
                    "EXACTLY: same airframe or hull form, component count and "
                    "placement, proportions, variant, and distinctive "
                    "engineering features. Change only the requested camera "
                    "viewpoint. " + prompt
                )
                retry_refusal = await budget_refusal(
                    tenant_id, video_id, quote, "this view's QA retry")
                if retry_refusal:
                    _p(f"Segment {sc}, view {view_index}: {retry_refusal} — "
                       "keeping the first render unretried.")
                    url2 = None
                else:
                    res = await ic.generate_scene_image_gpt(
                        retry_prompt, gen_input_url, aspect_ratio=v["aspect"],
                        allow_fallback=False, resolution="1K",
                    )
                    url2 = (res or {}).get("url")
                    if url2:
                        await record_ledger_entry(
                            tenant_id=tenant_id, video_id=video_id, stage="image",
                            model="gpt-image-2", units=1, unit_cost=quote,
                            actual_cost=quote,
                        )
                second_identity_reason: list = []
                if url2 and await _render_matches_reference(
                    tenant_id, url2, ref_url, machine, sub.get("aliases"),
                    reason_out=second_identity_reason,
                ):
                    url = url2
                else:
                    if url2 and second_identity_reason:
                        identity_qa_events.append(
                            ("identity", second_identity_reason[0]))
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
                        await _park(candidate, retry_prompt if url2 else prompt,
                                    qa_events=identity_qa_events)
                        return False

            # Role-conformance QA (2026-08-03 fix): identity QA above only
            # confirms this is the right MACHINE — it says nothing about
            # camera angle, which is exactly how three near-identical
            # three-quarter crops shipped as "three complementary views"
            # live (HMS Argus, video d2e37cd6). Checked only once identity
            # QA has already passed. ONE bounded retry with stronger
            # camera-geometry wording on mismatch; a view that still fails
            # role-conformance after the retry does not count toward
            # `approved` — parked exactly like a double identity-QA reject,
            # never deleted (it's still a paid render).
            role_qa_events: list = []
            first_role_reason: list = []
            if not await _view_role_confirms(
                tenant_id, url, machine, view_plan, reason_out=first_role_reason
            ):
                if first_role_reason:
                    role_qa_events.append(("role", first_role_reason[0]))
                _p(
                    f"Segment {sc}, view {view_index}: view does not match "
                    f"its {view_plan['label']} role — one retry with "
                    "stronger camera-geometry wording…"
                )
                geometry_prompt = _studio_prompt(
                    machine, view_plan, detail_focus, emphasize_geometry=True,
                    from_anchor=use_anchor,
                )
                geometry_refusal = await budget_refusal(
                    tenant_id, video_id, quote, "this view's role-conformance retry")
                role_retry_url = None
                if geometry_refusal:
                    _p(f"Segment {sc}, view {view_index}: {geometry_refusal} — "
                       "keeping the first render unretried.")
                else:
                    res = await ic.generate_scene_image_gpt(
                        geometry_prompt, gen_input_url, aspect_ratio=v["aspect"],
                        allow_fallback=False, resolution="1K",
                    )
                    role_retry_url = (res or {}).get("url")
                    if role_retry_url:
                        await record_ledger_entry(
                            tenant_id=tenant_id, video_id=video_id, stage="image",
                            model="gpt-image-2", units=1, unit_cost=quote,
                            actual_cost=quote,
                        )
                # Rewritten from the original chained-`and` expression to
                # capture each check's reason without changing which calls
                # actually run — role QA only fires when role_retry_url
                # exists, and identity QA only re-fires when the role retry
                # itself passed, exactly like the short-circuited `and` did.
                second_role_reason: list = []
                role_retry_ok = False
                if role_retry_url:
                    role_retry_ok = await _view_role_confirms(
                        tenant_id, role_retry_url, machine, view_plan,
                        reason_out=second_role_reason,
                    )
                    if not role_retry_ok and second_role_reason:
                        role_qa_events.append(("role", second_role_reason[0]))
                identity_retry_reason: list = []
                identity_retry_ok = role_retry_ok and await _render_matches_reference(
                    tenant_id, role_retry_url, ref_url, machine, sub.get("aliases"),
                    reason_out=identity_retry_reason,
                )
                if role_retry_ok and not identity_retry_ok and identity_retry_reason:
                    role_qa_events.append(("identity", identity_retry_reason[0]))
                if role_retry_url and role_retry_ok and identity_retry_ok:
                    # The retry's OWN prompt actually produced the shipped
                    # pixels, so it — not the original — is what the final
                    # image_prompt record below should reflect.
                    url = role_retry_url
                    prompt = geometry_prompt
                    qa_note += "[qa: role-conformance retry] "
                else:
                    await _park(
                        role_retry_url or url,
                        geometry_prompt if role_retry_url else prompt,
                        qa_events=role_qa_events,
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
                    + input_marker
                    + qa_note + prompt[:900]
                ),
            )
            # This is now the scene's anchor for every SUBSEQUENT view this
            # run generates, unless one was already set (a prior run's FILL-
            # mode anchor, or an earlier view in this same run) — the anchor
            # is fixed to the FIRST verified render, never a rolling chain
            # off each new view.
            if anchor_url is None:
                anchor_url, anchor_role = durable, view_plan["role"]
            return True

        approved = 0
        for view_plan, view_row_id in zip(plans_to_generate, row_ids):
            view_index = role_view_index[view_plan["role"]]
            if await _generate_view(view_index, view_plan, view_row_id):
                approved += 1

        # FILL mode's total includes the untouched done roles kept above;
        # full-regenerate mode has none surviving (they were wiped), so
        # `approved` alone is the total there.
        total_done = approved if missing_plans is None else len(done_role_ids) + approved

        if total_done < STATIC_VIEWS_MINIMUM:
            _p(
                f"Segment {sc}: only {total_done}/{len(view_plans_for_scene)} "
                f"verified views — needs at least {STATIC_VIEWS_MINIMUM}."
            )
        return {
            "scene": sc,
            "done": total_done,
            "reason": None if total_done >= STATIC_VIEWS_MINIMUM else "insufficient_views",
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
                    # the operator (qa_rejected / blocked_no_reference /
                    # blocked_missing_metadata) — all three carry image_url
                    # NULL by design, and a timeout cancelling _one_scene
                    # right after it parked would otherwise delete the
                    # parked row here.
                    await execute(
                        "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 "
                        "AND scene=$3 AND generation_method=$4 AND image_url IS NULL "
                        "AND status NOT IN "
                        "('qa_rejected','blocked_no_reference','blocked_missing_metadata')",
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
        # Tell planning failures apart from genuine QA/verified-view
        # failures — a scene that never got title-card metadata (chunk
        # unparseable even after retry) never reached image generation at
        # all, so "no segment reached N verified views" is misleading for it.
        planning_failed = [
            str((o or {}).get("scene"))
            for o in outcomes
            if (o or {}).get("reason") == "subject_planning_unparseable"
        ]
        if planning_failed:
            error = (
                "subject planning produced no title-card metadata for "
                f"scenes {', '.join(planning_failed)} — model reply "
                "unparseable/truncated, even after a retry."
            )
            other_failed = [s for s in failed if s not in planning_failed]
            if other_failed:
                error += f" Also failed for other reasons: {', '.join(other_failed)}."
        else:
            error = (
                f"no segment reached {STATIC_VIEWS_MINIMUM} verified views "
                f"(scenes failed: {', '.join(failed)})"
            )
        return {"status": "failed", "error": error}
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
                                roster_index: int,
                                aliases: Optional[list] = None,
                                facts: Optional[dict] = None) -> bool:
    """Verify + self-host + cache ONE roster machine's reference photo, using
    the SAME candidate chain _one_scene uses (_gather_reference_candidates).
    Returns True once a verified candidate is cached, False if the whole
    chain exhausts with nothing passing (a miss — not an exception; the
    caller records it and moves on to the next machine).

    `aliases` (added 2026-07-29): the roster's display name is a flat string
    (see pipeline_executor._machine_documentary_hold_roster) that, for a
    ship-class entry, is often an unsearchable glue of a designation-shaped
    field holding a category/member-ship list plus the class name (e.g.
    "Lend-Lease escort carriers Attacker class (US-built)"). The CALLER
    (static_docu.prefetch_roster_references) now derives real aliases from
    the structured roster entry
    (pipeline_executor._machine_documentary_hold_roster_entries) — the bare
    name, the bare designation, and each comma/slash-split member — and
    passes them through here so _gather_reference_candidates and
    _vision_confirms can use them for lookup and identification the same
    way _one_scene's live per-scene path already does. Defaults to None
    (the pre-alias behavior) so any other caller is unaffected.

    C8 (2026-07-29): a False return used to be a bare absence — three
    genuinely different problems (no candidate found at all, a candidate
    found but never hosted, a candidate hosted but vision-rejected) looked
    identical to every caller and to the human staring at the roster panel.
    This now classifies which of those happened and persists it via
    _record_reference_miss (see static_reference_misses) before returning
    False, and clears any prior miss the instant a machine verifies."""
    candidates = await _gather_reference_candidates(machine, aliases, machine)
    mkey = _machine_key(machine)
    if not candidates:
        await _record_reference_miss(tenant_id, video_id, machine, REASON_NO_CANDIDATES)
        return False
    hosted_any = False
    for idx, (cand, trusted) in enumerate(candidates):
        hosted = await _host_reference(cand, video_id, tenant_id, f"roster{roster_index:02d}_{idx}")
        if not hosted:
            continue
        hosted_any = True
        # VIS-1: the candidate URL's own filename is handed to the vision
        # check as text — a Commons filename usually names the actual unit
        # photographed ("HMS_Glory_...", "USS_Guadalcanal_..."), which is
        # how a sister-class lookalike gets caught when pixels can't.
        cand_label = str(cand).rsplit("/", 1)[-1] if cand else None
        if await _vision_confirms(tenant_id, hosted, machine, aliases,
                                  trusted_source=trusted, facts=facts,
                                  source_label=cand_label):
            await execute(
                """INSERT INTO static_reference_cache
                       (tenant_id, machine_key, machine, hosted_url, source_url)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (tenant_id, machine_key)
                   DO UPDATE SET machine=$3, hosted_url=$4, source_url=$5,
                                 verified_at=now()""",
                tenant_id, mkey, machine[:200], hosted, cand)
            await _clear_reference_miss(tenant_id, video_id, machine)
            return True
    await _record_reference_miss(
        tenant_id, video_id, machine,
        REASON_VISION_REJECTED if hosted_any else REASON_FETCH_FAILED)
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
    # VIS-1: an operator-pasted URL gets the same strengthened question the
    # sweep asks — the entry's own role/era facts plus the pasted filename.
    # A human picking the photo does not exempt it from the era/configuration
    # check (the live wrong-photo audit included exactly the kind of
    # right-name-wrong-era candidates a well-meaning human paste could hit).
    facts, aliases = None, None
    try:
        from pipeline_executor import _machine_documentary_hold_roster_entries
        video = await fetch_one(
            "SELECT id, render_mode, research_payload FROM videos "
            "WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
        target_key = _machine_key(machine)
        for entry in (_machine_documentary_hold_roster_entries(video) if video else []):
            if _machine_key(entry["name"]) == target_key:
                facts = entry.get("facts") or None
                aliases = entry.get("aliases") or None
                break
    except Exception:  # noqa: BLE001 — enrichment must never break seeding
        facts, aliases = None, None
    if not await _vision_confirms(tenant_id, hosted, machine, aliases,
                                  trusted_source=False, facts=facts,
                                  source_label=str(url).rsplit("/", 1)[-1]):
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
    # C8: a manually-seeded photo resolves this video's open miss (if any)
    # exactly like an automated prefetch success does — same clear helper,
    # so the panel stops attributing a reason to a machine that's now fine.
    await _clear_reference_miss(tenant_id, video_id, machine)
    return {"status": "verified", "hosted_url": hosted, "source_url": url}


async def prefetch_roster_references(video_id: str, tenant_id: str) -> dict:
    """Roster-time reference prefetch (C3). Reads the video's LOCKED machine
    roster — via pipeline_executor._machine_documentary_hold_roster_entries,
    which gates on the exact same conditions as
    _machine_documentary_hold_roster (the flat-string accessor the
    orchestrator/dashboard/repair endpoints use) but keeps each entry's
    derived aliases alongside its UNCHANGED display name (see
    pipeline_executor._unit_roster_aliases) — and, for every machine not
    already in static_reference_cache, runs the full lookup+verify+host+
    cache chain WITH those aliases. Serial per machine, on purpose: _wm_get's
    politeness throttle is a single process-global gate regardless of how
    many machines call it concurrently, so parallelizing here would only
    interleave log lines, not buy real concurrency. One machine's exception
    is caught and logged here — it can never abort the sweep for the rest
    of the roster. Never raises; every outcome is reported in the return
    dict for the caller (or a future roster-dashboard reference-status read)
    to inspect.

    C5 (2026-07-29): an entry pipeline_executor classifies as `never_built`
    (see _roster_entry_never_built — a cancelled programme with no physical
    unit ever completed, e.g. "CVA-01 class") is never handed to
    _prefetch_one_machine at all. There is nothing a Wikimedia search or a
    paid vision check could ever find for it, so classification happens
    BEFORE any lookup is attempted: REASON_NEVER_BUILT is recorded directly
    and the machine is skipped, which also means this is the ONE miss
    reason that costs zero real spend to produce — every other reason is
    discovered only after the full candidate-gather + vision chain runs."""
    # Lazy import: static_docu <-> pipeline_executor is a two-way relationship
    # (pipeline_executor already imports static_docu lazily, e.g. at its own
    # generate_static_images_for_video call site) — importing at module top
    # either direction would risk a circular import given pipeline_executor's
    # size and reach.
    from pipeline_executor import _machine_documentary_hold_roster_entries

    video = await fetch_one(
        "SELECT id, render_mode, research_payload FROM videos "
        "WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not video:
        return {"status": "failed", "error": "video not found"}
    entries = _machine_documentary_hold_roster_entries(video)
    if not entries:
        return {"status": "skipped", "message": "no locked static-docu machine roster"}

    await _ensure_ref_cache_schema()

    verified, missed, never_built = 0, 0, 0
    for i, entry in enumerate(entries):
        machine = entry["name"]
        aliases = entry.get("aliases") or []
        mkey = _machine_key(machine)
        try:
            cached = await fetch_one(
                "SELECT hosted_url FROM static_reference_cache "
                "WHERE tenant_id=$1 AND machine_key=$2", tenant_id, mkey)
            if cached:
                verified += 1
                # C8: this machine already carries a tenant-global verified
                # reference (perhaps seeded/prefetched via a different
                # video) — any stale miss reason recorded against THIS
                # video no longer applies.
                await _clear_reference_miss(tenant_id, video_id, machine)
                continue
            if entry.get("never_built"):
                # C5: structurally can never have a photograph — skip the
                # ENTIRE candidate-gather + host + vision chain (real
                # Wikimedia lookups and a paid vision call per candidate)
                # rather than let it run and fail. Checked AFTER the cache
                # lookup above so a manually-seeded/prefetched-elsewhere
                # photo (proof the classification was wrong for this
                # tenant) always wins over the classifier.
                never_built += 1
                await _record_reference_miss(tenant_id, video_id, machine, REASON_NEVER_BUILT)
                _logger.info(
                    "[prefetch-roster-ref] video=%s machine=%r classified "
                    "never-built (cancelled, no unit ever completed) — "
                    "skipping lookup entirely, no spend incurred",
                    video_id, machine)
                continue
            if await _prefetch_one_machine(tenant_id, video_id, machine, i,
                                           aliases=aliases,
                                           facts=entry.get("facts") or None):
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
            # C8: _prefetch_one_machine records its OWN reason for a clean
            # miss, but an exception can escape it (or the cache-lookup
            # above) before that ever happens — record one here too so no
            # miss is ever silently unexplained.
            await _record_reference_miss(tenant_id, video_id, machine, REASON_ERROR)

    _logger.info(
        "[prefetch-roster-ref] video=%s roster=%d verified=%d missed=%d never_built=%d",
        video_id, len(entries), verified, missed, never_built)
    return {"status": "completed", "roster_count": len(entries),
            "verified": verified, "missed": missed, "never_built": never_built}


# --- C12: durable registration so a restart mid-sweep is recoverable ------
#
# Problem (found by a 2026-07-29 audit): dispatch_roster_prefetch below used
# to call a bare asyncio.create_task(prefetch_roster_references(...)) with
# NO row in the background_tasks table. The repo's own reapers —
# routes/pipeline.py's recover_stale_tasks (API startup) and
# reap_stale_running_tasks (periodic timer) — operate purely by SQL over
# background_tasks and are task-type-agnostic: they cannot see, retry, or
# even know about a task that never wrote a row there. A restart or
# redeploy mid-sweep silently dropped the fetch with zero record — a
# 23-machine sweep takes ~10 minutes, and deploys are more frequent than
# that. This reproduced the exact 2026-07-27 incident (roster saved, photos
# never arrive, a human has to notice) via a deploy race instead of the
# gate-ordering bug C1+C2 already fixed.
#
# Fix: register the sweep under its own task_type ('roster_prefetch') in
# background_tasks before running it, and close the row out on completion —
# the same table/columns/lifecycle main.py's custom_film_runtime/
# custom_film_director outbox rows already use (see main.py's
# _dispatch_pending_custom_film_runtime/_director), just with no arq job_id
# since this task type has no worker.py handler — it always runs in-process
# via asyncio.create_task, on both the original dispatch and a resume.
#
# Deliberately NOT reusing routes/pipeline.py's _db_persist_task/
# _set_task_status: those key their "already running?" check off
# (tenant_id, video_id) ALONE, no task_type filter, and drive the
# in-memory _running_tasks dict that both _is_task_active's "main" lane
# exclusivity gate and the roster-recheck endpoint's live task-status
# polling (commit f615772a) depend on. Writing into that same slot from
# here — fired from deep inside run_research/accept_submitted_research, not
# a request handler — would race whatever status those flows are ALSO
# reporting for this exact video_id (e.g. clobbering "research complete"
# with "sweeping references", or vice versa) and could wedge the main-lane
# busy gate. A dedicated task_type + a direct INSERT/UPDATE against
# background_tasks sidesteps that: visible to the task-type-agnostic
# reapers (all durability needs), invisible to the in-memory main-lane gate
# and the recheck endpoint's polling (so f615772a's UX is untouched).
#
# Recovery needs no bespoke bookkeeping: recover_stale_tasks() already flips
# any 'running' row to 'failed' with error_message='Server restarted — task
# interrupted' at every API startup, task-type-agnostic. This module's
# resume_interrupted_roster_prefetches() (called from main.py's lifespan,
# mirroring _dispatch_pending_custom_film_runtime) scans for exactly that
# marker under task_type='roster_prefetch' and re-dispatches — cheaply and
# safely, because prefetch_roster_references already skips any machine
# already in static_reference_cache, so a resumed sweep only redoes the
# machines still outstanding when the restart hit.

_ROSTER_PREFETCH_TASK_TYPE = "roster_prefetch"
_ROSTER_PREFETCH_RESTART_MESSAGE = "Server restarted — task interrupted"
_ROSTER_PREFETCH_MAX_RESUME_ATTEMPTS = 5


# --- UX-2 (2026-07-30): live progress for the AUTOMATIC sweep -----------------
#
# Bug (fresh-eyes audit, post-4031bc02): the manual "Re-check missing" button
# (routes/pipeline.py's recheck_roster_references, UX-1) republishes an honest
# "N/Y verified so far" onto its task-status message every ~5s, so
# RosterStagePanel.tsx can show a climbing count + spinner instead of a
# frozen panel. dispatch_roster_prefetch's AUTOMATIC sweep — the one fired
# from run_research/accept_submitted_research, i.e. the path that actually
# matters — never wrote anything past its one static opening message
# ("Sweeping roster reference photos"), so a user watching an auto sweep saw
# exactly the frozen "missing + paste a URL" panel for the full ~10-minute
# sweep that the original incident was about.
#
# Fix: give _run_tracked_roster_prefetch the SAME kind of progress side-car,
# updating the SAME background_tasks row it already owns (by task_id) —
# never through _set_task_status/_db_persist_task, for the exact reason the
# C12 note above forbids reusing those from here (main-lane clobbering risk).
# A direct, task_id-scoped UPDATE has none of that risk: it only ever touches
# the one row this sweep itself inserted.
async def _report_tracked_prefetch_progress(video_id: str, tenant_id: str, task_id: str) -> None:
    """Best-effort progress side-car for _run_tracked_roster_prefetch. Every
    ~5s, counts how many of this video's roster machines are already in
    static_reference_cache and republishes "Sweeping machine references —
    N/Y verified so far" onto the background_tasks row `task_id` — the same
    "reference"-carrying phrasing recheck_roster_references' own side-car
    uses (routes/pipeline.py, UX-1), so the frontend's substring fallback
    (RosterStagePanel.tsx's bridgeIsRosterSweep) still matches even without
    the structured task_type field. Cancelled by the caller once the sweep
    itself finishes. Never allowed to affect the sweep: every failure mode
    here is swallowed, exactly like recheck's own side-car."""
    import asyncio
    try:
        from pipeline_executor import _machine_documentary_hold_roster

        video = await fetch_one(
            "SELECT id, render_mode, research_payload FROM videos "
            "WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
        roster = _machine_documentary_hold_roster(video) if video else []
        mkeys = [_machine_key(m) for m in (roster or [])]
        total = len(mkeys)
        if not total:
            return
        while True:
            await asyncio.sleep(5)
            rows = await fetch_all(
                "SELECT machine_key FROM static_reference_cache "
                "WHERE tenant_id = $1 AND machine_key = ANY($2)",
                tenant_id, mkeys,
            )
            verified_now = len(rows or [])
            await execute(
                """UPDATE background_tasks SET message=$1
                   WHERE id=$2 AND status='running'""",
                f"Sweeping machine references — {verified_now}/{total} verified so far",
                task_id,
            )
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001 — a progress-reporting bug must never affect the sweep
        _logger.debug(
            "[prefetch-roster-ref] progress side-car stopped early for video=%s",
            video_id, exc_info=True)


async def _run_tracked_roster_prefetch(video_id: str, tenant_id: str, *, attempt: int = 1) -> None:
    """Runs prefetch_roster_references wrapped in a background_tasks row
    (task_type='roster_prefetch') so an interrupted sweep is detectable and
    resumable — see the C12 note above. This is the ONE coroutine
    dispatch_roster_prefetch and resume_interrupted_roster_prefetches both
    schedule via asyncio.create_task; never raises out of itself since it
    always runs detached (an escaped exception here would only ever surface
    as an "exception was never retrieved" log line, never to a caller)."""
    import asyncio
    task_id = None
    try:
        row = await fetch_one(
            """INSERT INTO background_tasks
                   (tenant_id, video_id, task_type, status, message, started_at, attempt)
               VALUES ($1, $2, $3, 'running', $4, now(), $5)
               RETURNING id""",
            tenant_id, video_id, _ROSTER_PREFETCH_TASK_TYPE,
            "Sweeping roster reference photos", attempt,
        )
        task_id = row.get("id") if row else None
    except Exception:  # noqa: BLE001 — registration failure must not block the sweep
        _logger.warning(
            "[prefetch-roster-ref] could not register background_tasks row "
            "for video=%s (sweep still runs, just undurably this time)",
            video_id, exc_info=True)

    # UX-2: mirrors recheck_roster_references' own progress side-car, just
    # updating THIS row directly instead of going through _set_task_status.
    progress_task = None
    if task_id:
        try:
            progress_task = asyncio.create_task(
                _report_tracked_prefetch_progress(video_id, tenant_id, task_id))
        except RuntimeError:
            progress_task = None

    result_status, message = "completed", None
    try:
        result = await prefetch_roster_references(video_id, tenant_id)
        result_status = result.get("status") or "completed"
        if result_status == "completed":
            message = f"{result.get('verified', 0)} verified, {result.get('missed', 0)} missed"
        elif result_status == "skipped":
            message = result.get("message") or "Nothing to prefetch for this video"
        else:  # prefetch_roster_references' own "failed" (e.g. video not found)
            message = result.get("error") or "Roster prefetch failed"
    except Exception as exc:  # noqa: BLE001 — never let the tracking wrapper blow up
        result_status = "failed"
        message = str(exc)
        _logger.warning(
            "[prefetch-roster-ref] tracked sweep failed for video=%s",
            video_id, exc_info=True)
    finally:
        if progress_task:
            progress_task.cancel()

    if task_id:
        # background_tasks.status CHECK only allows pending/running/
        # completed/failed/cancelled — "skipped" collapses into
        # "completed" (it did finish, just with nothing to do), same
        # normalization routes/pipeline.py's _set_task_status applies.
        db_status = "failed" if result_status == "failed" else "completed"
        try:
            await execute(
                """UPDATE background_tasks
                       SET status=$1, message=$2, completed_at=now()
                   WHERE id=$3""",
                db_status, message, task_id,
            )
        except Exception:  # noqa: BLE001 — best-effort close-out
            _logger.debug(
                "[prefetch-roster-ref] could not close out background_tasks "
                "row for video=%s", video_id, exc_info=True)


async def resume_interrupted_roster_prefetches() -> int:
    """Called once at API startup (see main.py's lifespan, right after
    routes.pipeline.recover_stale_tasks flips every stale 'running' row to
    'failed') — finds roster-prefetch rows THIS SAME startup pass just
    interrupted and re-dispatches them. prefetch_roster_references is
    naturally idempotent (skips any machine already cached), so replaying
    the whole roster is cheap, not a full re-sweep — no per-machine resume
    bookkeeping needed, exactly per the C12 design note.

    Scoped to rows completed in the last 10 minutes (same window main.py's
    custom_film stale-task recovery uses) so a long-dead row from a much
    earlier crash isn't silently resurrected on every future restart.
    Capped at _ROSTER_PREFETCH_MAX_RESUME_ATTEMPTS so a roster that keeps
    genuinely failing (not just being interrupted) stops auto-retrying
    instead of looping across restarts forever. Never raises — startup must
    never block on this. Returns the number of sweeps resumed."""
    resumed = 0
    try:
        rows = await fetch_all(
            """SELECT tenant_id, video_id, COALESCE(attempt, 1) AS attempt
               FROM background_tasks
               WHERE task_type = $1 AND status = 'failed'
                 AND error_message = $2
                 AND completed_at >= now() - interval '10 minutes'""",
            _ROSTER_PREFETCH_TASK_TYPE, _ROSTER_PREFETCH_RESTART_MESSAGE,
        )
    except Exception:  # noqa: BLE001 — startup must never block on this scan
        _logger.warning(
            "[prefetch-roster-ref] resume scan failed (non-blocking)", exc_info=True)
        return 0

    import asyncio
    for row in rows or []:
        attempt = int(row.get("attempt") or 1)
        video_id = str(row.get("video_id") or "")
        tenant_id = str(row.get("tenant_id") or "")
        if not video_id or not tenant_id:
            continue
        if attempt >= _ROSTER_PREFETCH_MAX_RESUME_ATTEMPTS:
            _logger.warning(
                "[prefetch-roster-ref] not resuming video=%s — already at "
                "%d resume attempts", video_id, attempt)
            continue
        try:
            asyncio.create_task(
                _run_tracked_roster_prefetch(video_id, tenant_id, attempt=attempt + 1))
            resumed += 1
            _logger.info(
                "[prefetch-roster-ref] resumed interrupted sweep for "
                "video=%s (attempt %d)", video_id, attempt + 1)
        except Exception:  # noqa: BLE001 — one video's resume must never block others
            _logger.warning(
                "[prefetch-roster-ref] could not resume sweep for video=%s",
                video_id, exc_info=True)
    return resumed


def dispatch_roster_prefetch(video: Optional[dict], video_id: str, tenant_id: str) -> bool:
    """Fire-and-forget hook: schedule a durable, trackable reference-photo
    sweep the instant research lands for a static-docu video. Called from
    BOTH research-completion seams — the paid `research` verb
    (pipeline_executor.PipelineExecutor.run_research) and the free
    `submit_research` MCP ingest (research_ingest.accept_submitted_research)
    — right before their own success return, so a single line at each call
    site is all either seam needs.

    Schedules _run_tracked_roster_prefetch (C12), not bare
    prefetch_roster_references, so the sweep registers a background_tasks
    row the repo's existing reapers/startup-recovery can see (see that
    function's docstring for the full durability design). Uses the repo's
    existing fire-and-forget pattern (asyncio.create_task — see
    autopilot_launch.py, routes/queue.py, main.py's startup tasks) rather
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
        asyncio.create_task(_run_tracked_roster_prefetch(video_id, tenant_id))
        return True
    except Exception:  # noqa: BLE001 — a dispatch failure must never fail research
        _logger.warning(
            "[prefetch-roster-ref] dispatch failed for video=%s", video_id, exc_info=True)
        return False
