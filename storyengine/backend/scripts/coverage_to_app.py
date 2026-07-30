"""Generate COVERAGE frames for a video and store them IN THE APP (additive).

Runs the coverage generator (skills/video-pipeline/storyboard/coverage.py) for one or all
scenes of a video using the tenant's own Claude + Kie keys, uploads each frame to the app's
storage (Drive), and INSERTs it as a new `assets` row tagged generation_method='coverage'.

Purely additive + idempotent: coverage frames go in at a high image_index (existing panels
use 1-9), and a re-run first deletes only this scene's prior coverage rows — original panels
are never touched.

  python3 scripts/coverage_to_app.py --video <id-prefix|title> [--scene N] [--moments 3] [--dry-run]

--dry-run: resolve the video + print the plan and cost estimate, generate/write NOTHING.
"""
from __future__ import annotations

import argparse
import asyncio
import html as _html
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_BACKEND))
_SKILLS = os.path.join(_REPO, "skills", "video-pipeline")
sys.path.insert(0, _BACKEND)            # backend: database, storage, vault, kie_unified
sys.path.insert(0, _SKILLS)             # skills: storyboard.coverage, shared.*, orchestrator.*
# C8 fix (c): mirrors pipeline_executor.py's server-boot bootstrap exactly. Each
# bot folder has its own internal bare imports (e.g. camera_selector.py's
# `from animation_prompt_engine import ...`, which only resolves when
# image_prompts/ itself — not just skills/video-pipeline/ — is on sys.path).
# The live server adds these at boot; this standalone CLI script didn't, so
# plan_camera_moves()'s camera-engine import silently failed here and every
# shot quietly degraded to static/freeform with no error (the broad except in
# plan_camera_moves swallowed it — now also fixed to log loudly). Bootstrap
# identically so running this file directly behaves like the server, not a
# degraded twin of it.
for _bot_dir in ["script", "voice", "image_prompts", "images", "video_motion",
                 "thumbnail", "render", "sound", "storyboard", "research",
                 "upload", "analytics", "title_idea"]:
    _bot_path = os.path.join(_SKILLS, _bot_dir)
    if _bot_path not in sys.path:
        sys.path.append(_bot_path)

# main.py loads .env for the server; this standalone script must do it itself, BEFORE
# importing database/storage (they read DATABASE_URL / storage creds from env).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_BACKEND, ".env"))
except Exception:
    pass

# The backend process has no Google OAuth creds (it fetches Drive via the public media
# proxy), so a standalone script cannot upload to Drive. Supabase Storage uses the
# service-role key (present in .env) and works headless — default to it. Must be set
# BEFORE importing storage (it reads STORAGE_BACKEND at import).
os.environ.setdefault("STORAGE_BACKEND", "supabase")

from database import fetch_one, fetch_all, execute            # noqa: E402  (asyncpg helpers)
from generation_ledger import record_ledger_entry             # noqa: E402
from storage import upload_bytes                              # noqa: E402
from vault import get_secret                                  # noqa: E402
from kie_unified import get_text_client_for_tenant            # noqa: E402
# C1b (feat/per-card-parallel-clips): the per-asset claim guard for
# redraw_asset_images' concurrent fan-out below — the image-redraw sibling
# of pipeline_executor.py's clip_asset_claims. See redraw_asset_claims.py's
# module docstring for why this is a SEPARATE module/dict from
# clip_asset_claims, not a shared one.
import redraw_asset_claims                                    # noqa: E402
from storyboard.coverage import (  # noqa: E402
    run_coverage, resolve_cast_url, generate_coverage_directive,
    parse_set_dressing, parse_axis_line, parse_setups_line, panels_per_sheet_for,
    sheet_chunk_sizes, _STYLE_LOCK, _STYLE_LOCK_HYGIENE, _INLINE_TAG_RE,
    plan_moments_deterministic,
    # BOARD LAWS (storyengine/BOARD-LAWS.md): multi-location/material-map
    # directive parsing (L3/L20) and the shared motion detector (L4) — the
    # SAME functions run_coverage's own repair-leg locks call, so the sheet
    # PREVIEW and the PICTURES draw prompt can never silently disagree on
    # which locations exist or whether this scene reads as motion.
    parse_location_sets, parse_material_map, scene_has_motion,
    # D3-65: the SAME "this is the master's moment, different camera" guard
    # generate_coverage_frames appends to every ANGLE prompt alongside the
    # master frame's own url as a reference — see redraw_asset_image below
    # for why a redraw needs this too (never re-authored, the proven text).
    _SAME_SUBJECT,
    # C8 fix (a): the SAME ratios enforce_reaction_insert_floors uses to decide
    # how many reaction/insert/re-establish shots a scene needs — imported
    # (never re-guessed) so _coverage_shape's pure-dialogue headroom always
    # matches what the floor validator will actually go looking for.
    _REACTION_TURNS_PER_SHOT, _INSERT_SHOTS_PER_ONE, _REESTABLISH_SHOTS_PER_ONE,
    # D6-2 (L16/L22, migration 143): the SAME setup-id extraction and
    # reverse-pair parser run_coverage's build-time repair legs use —
    # imported (never re-guessed) so redraw_asset_image's fresh
    # re-derivation can never silently diverge from what was computed at
    # build time.
    _setup_id, _setup_base_id, parse_reverse_setup_pairs,
)


async def _require_tenant_kie_key(tenant_id: str) -> str:
    """Resolve only this tenant's Kie key before constructing legacy clients."""
    key = await get_secret("kie_ai_api_key", tenant_id)
    if key:
        return key
    raise RuntimeError(
        "Add your Kie.ai key in Settings → API Keys before generating. "
        "StoryEngine does not use a shared provider key."
    )
# C4 prop manifest: the ONE renderer every consumer (beat prompt, real draw
# prompt, redraw/repair prompt) uses, so the wording is byte-identical
# everywhere — never a fresh LLM restatement. Lives in storyboard.bot (not
# coverage.py) because bot.py is the module coverage.py itself already
# imports FROM (see coverage.py's own `from storyboard.bot import ...`) —
# putting it here avoids a circular import.
from storyboard.bot import render_prop_manifest                # noqa: E402
from shared.clients.image_client import ImageClient           # noqa: E402
from shared.clients.image_model_router import generate_scene_image_for_model  # noqa: E402
from shared.channel_profile import (  # noqa: E402
    load_profile,
    claude_model_for_direct_client,
)

logger = logging.getLogger(__name__)

COVERAGE_INDEX_BASE = 100  # existing panels use 1-9; coverage frames live at 100+ (never clobber)
PER_FRAME_USD = 0.05
# Approval-bound coverage may spend only on the stills counted in its BOM.
# This exact law is supplied by the Custom Film seam and rejected on mutation.
CUSTOM_FILM_AUXILIARY_IMAGE_POLICY = {
    "auto_cast_generation": "forbidden",
    "auto_character_population": "forbidden",
}
# C25a-fix7 (2026-07-20) capped storyboard sheet reference images at 2
# (SHEET_REF_CAP), blaming a 3rd input_urls entry for 400s on video
# cd5d2883. C25a-fix8 (2026-07-20) re-derived that against the real filter
# and found it confounded: the ALL-CAPS "PRODUCTION STORYBOARD SHEET" header
# 400s on its own regardless of ref count, and a 3-ref probe (2 cast + env)
# on a clean body SUCCEEDED once that header was fixed (taskId
# 829cfea1f9c95b4f27935375ea5a95a5). SHEET_REF_CAP removed — see
# _sheet_header()'s docstring below for the full evidence trail and the
# header rewrite that actually fixed it.
# D1 shot budget: the per-scene MOMENT ceiling for dialogue scenes (see
# _coverage_shape). Raised 12 → 18 with angles back on (Ryan 2026-07-02:
# quantity guardrails off — 9 shots on a 2:19 scene was a slideshow); this is
# the runaway-planner brake, not a pacing dial.
SCENE_FRAME_BUDGET = int(os.getenv("SCENE_FRAME_BUDGET", "18"))


async def resolve_video(ident: str):
    return await fetch_one(
        "SELECT id, tenant_id, video_title, COALESCE(aspect_ratio, '16:9') AS aspect, "
        "image_style_override, visual_style "
        "FROM videos WHERE (id::text LIKE $1 OR video_title ILIKE $2) AND deleted_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        ident + "%", "%" + ident + "%",
    )


# A trademarked studio/brand name in a STYLE prompt reads as an IP/policy
# reference to image models — GPT Image 2 returns "content could not be
# processed" (failCode 400, 0 credits) when the style names a studio. Proven on
# PocoAPoco 'El Mercado' 2026-07-20: a storyboard board that reliably 400'd
# drew clean on the primary header the moment the studio name came out of the
# style, nothing else changed. So we describe the LOOK (medium + form + light),
# never the studio, and scrub any studio name out of style text before it can
# reach an image prompt — the style stays neutral craft language, always.
#
# Scope: only the human-readable style DESCRIPTION is scrubbed. The classifier
# IDS (channel_format 'pixar_3d' etc.) are the internal keys the whole app maps
# on and NEVER reach an image model, so they are deliberately untouched.
# The separator before an optional -style/-like/-esque/-grade/-inspired suffix
# is bound TO the suffix, so a bare studio name keeps the space that separates
# it from the next word ("Ghibli watercolor" -> "hand-drawn animated
# watercolor", not "...animatedwatercolor") while "<studio>-style CG" still
# collapses to "3D animated CG".
_BRAND_SUFFIX = r"(?:[\s/-]+(?:style|like|esque|grade|inspired))?"
_STYLE_BRAND_PATTERNS: list[tuple] = [
    # 3D / CG studios -> "3D animated"
    (re.compile(rf"\b(?:walt\s+)?disney(?:[\s/-]*pixar)?{_BRAND_SUFFIX}\b", re.IGNORECASE), "3D animated"),
    (re.compile(rf"\bpixar(?:[\s/-]*disney)?{_BRAND_SUFFIX}\b", re.IGNORECASE), "3D animated"),
    (re.compile(rf"\bdreamworks{_BRAND_SUFFIX}\b", re.IGNORECASE), "3D animated"),
    (re.compile(rf"\billumination{_BRAND_SUFFIX}\b", re.IGNORECASE), "3D animated"),
    (re.compile(r"\bsony\s+(?:pictures\s+)?animation\b", re.IGNORECASE), "3D animated"),
    # Stop-motion studios
    (re.compile(rf"\blaika{_BRAND_SUFFIX}\b", re.IGNORECASE), "stop-motion animated"),
    (re.compile(rf"\baardman{_BRAND_SUFFIX}\b", re.IGNORECASE), "stop-motion animated"),
    # 2D / hand-drawn studios
    (re.compile(rf"\b(?:studio\s+)?ghibli{_BRAND_SUFFIX}\b", re.IGNORECASE), "hand-drawn animated"),
]


def _neutralize_style_brands(text):
    """Scrub trademarked studio/brand names out of a style DESCRIPTION, leaving
    neutral craft language (see _STYLE_BRAND_PATTERNS). None/empty pass through
    unchanged. After the swap, collapse any duplicate adjacent word it can
    introduce ("3D 3D" -> "3D") and tidy whitespace, so "Soft 3D Pixar-style CG"
    reads "Soft 3D animated CG", not "Soft 3D 3D animated CG"."""
    if not text:
        return text
    out = text
    for pattern, replacement in _STYLE_BRAND_PATTERNS:
        out = pattern.sub(replacement, out)
    out = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", out, flags=re.IGNORECASE)  # "3D 3D" -> "3D"
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


# Stylized-medium markers for _enforce_stylized_media. Substring matches on the
# lowercased style text — "animat" catches animated/animation, "illustrat"
# catches illustrated/illustration.
_STYLIZED_MEDIUM_MARKERS = (
    "animat", "cartoon", "anime", "cel-shaded", "cel shaded", "illustrat",
    "watercolor", "hand-drawn", "hand drawn", "stop-motion", "claymation",
    "comic", "graphic-novel", "graphic novel", "vector", "storybook",
    "painterly", "pixel art",
)


def _enforce_stylized_media(style):
    """Append an explicit anti-photoreal clause to a style that names a
    stylized medium but never says NOT to render it as a photograph.

    Why (proven live 2026-07-21, video cd5d2883 'Spanish Class'): the weak
    'Soft 3D CG, subsurface skin, shallow depth of field' style produced
    storyboard sheets that drifted fully live-action on nano-banana-2 — the
    model follows the strongest realism signal in the request (here, a
    photoreal environment reference image) unless the prompt explicitly bans
    photorealism. El Mercado's style, identical pipeline but carrying 'NOT
    photorealistic, NOT live-action', held the 3D-cartoon look on every panel.
    So: a stylized style keeps its author's wording and gains the ban only
    when it is missing; a style that already bans photorealism (or never
    names a stylized medium — e.g. the 'realistic' preset, or no style at
    all) passes through untouched."""
    if not style or not style.strip():
        return style
    low = style.lower()
    if "not photoreal" in low or "no photoreal" in low:
        return style
    if not any(marker in low for marker in _STYLIZED_MEDIUM_MARKERS):
        return style
    return (style.rstrip().rstrip(".") +
            ". Every element is rendered in this exact stylized medium - "
            "characters, sets, props and food alike. NOT photorealistic, "
            "NOT live-action, NOT a real photograph.")


def _resolve_style(image_style_override, visual_style):
    """Turn a video's stored style choice into (profile, style_directive) —
    the ONE resolved style string every image-prompt path (director, cast
    sheet, storyboard sheet composer) must state exactly once (BOARD-LAWS
    L29). This function IS the precedence contract; it was unwritten before
    D6-1, which is how the sheet composer ended up stating two contradictory
    styles in one prompt (see _sheet_header's L29 fix).

    PRECEDENCE CONTRACT (videos carries EIGHT style-related columns; this is
    the only function in the codebase that resolves board/cast-sheet style,
    and it consults exactly two of them, in this order):
      1. image_style_override — wins outright when set. The creator's most
         specific, most recent style choice.
      2. visual_style — used only when (1) is empty. The channel/video's
         general style pick.
      3. Neither set => style_directive is None; every caller defaults to
         its own neutral fallback ("Photorealistic, cinematic film still"
         in the sheet composer, "a PHOTOREAL live-action / 3D-CG style" in
         build_cast_prompt) — ONE default, stated ONE place per caller,
         never a second independent guess layered on top.
      The other SIX videos.* style columns are DELIBERATELY NOT consulted
      here, because they answer different questions, not "what does the
      image look like":
        - render_style, video_model — the VIDEO/clip model + its declared
          look for animate/routing (route_shot_model), not the image-prompt
          style text.
        - production_style_snapshot — pacing/density knobs (_production_
          density_mode: how many panels, not what they look like).
        - style_preset_id, production_style_id — preset IDs that resolve
          through a COMPLETELY SEPARATE mechanism this function does not
          touch: pipeline_executor._resolve_visual_profile_id reads
          style_preset_id and sets the VISUAL_PROFILE env var, which a
          DIFFERENT load_profile (shared.profiles.visual, not shared.
          channel_profile's load_profile imported here) uses to pick one of
          5 Python profile engines for the MAIN pictures pipeline. That
          path is real but genuinely separate — verified by reading both
          call sites (2026-07-30) rather than assumed. NOTED GAP, not fixed
          in D6-1: a video whose creator picked a style_preset_id with no
          image_style_override/visual_style text also set gets the sheet
          COMPOSER's neutral photoreal default while the real PICTURES path
          renders in the chosen preset engine — the sheet preview and the
          real draw can disagree on style for that specific configuration.
          Fixing it means either mirroring _resolve_visual_profile_id's
          precedence here or unifying the two resolvers; out of this
          chunk's scope (composer verbatim insertion), filed for a
          follow-up rather than silently left undocumented.
        - thumbnail_style_override — scoped to the YouTube thumbnail only,
          a different artifact with its own audience and constraints.
      A caller that finds itself wanting one of those six for a BOARD or
      CAST-SHEET prompt has the wrong requirement — style-for-drawing always
      resolves through this function and only ever prints ONE line.

    The picture engine locks every frame to the cast sheet's look, so the cast sheet IS the
    style. This carries the creator's pick (image_style_override / visual_style) into the
    director, cast-sheet, and storyboard prompts. Without it, load_profile({}) fell back to a
    neutral 'clean, modern, cinematic' default and every video rendered realistic — even when
    the creator chose a 3D-animated look. style_directive is None when no style was picked, so
    callers keep their own sensible default.

    Every style string is run through _neutralize_style_brands here — the ONE seam all three
    image paths (director, cast sheet, storyboard) draw their style from — so a studio name can
    never reach an image prompt no matter how it got into the stored style (creator entry,
    producer-LLM elaboration, or a legacy preset). The resolved directive then runs through
    _enforce_stylized_media so an animated/stylized look always reaches the image models with
    an explicit photorealism ban (see that helper's docstring for the live evidence)."""
    rec = {}
    iso = _neutralize_style_brands((image_style_override or "").strip())
    if iso:
        rec["Image Style Override"] = iso
    vs = _neutralize_style_brands((visual_style or "").strip())
    if vs:
        rec["Visual Style"] = vs
    profile = load_profile(rec)
    return profile, _enforce_stylized_media(
        _neutralize_style_brands(profile.visual_style_directive if rec else None))


async def build_cast_prompt(claude, script_text: str, model=None, style: str | None = None) -> str:
    """Ask the tenant's Claude for ONE cast-sheet prompt covering the whole script, rendered in
    the creator's chosen visual style. Falls back to photoreal cinematic only when none is set."""
    style_line = style.strip() if (style and style.strip()) else "a PHOTOREAL live-action / 3D-CG style"
    system = (
        "You write prompts for a cinematic video. Given a script, output ONE image "
        "prompt for a character/cast reference sheet: a clean sheet on a neutral grey background "
        "showing each named character (and any key creature or vehicle) full-body, labeled with "
        "its name, with identical lighting and this EXACT rendering style across all of them: "
        f"{style_line}. Restate each character's exact look (wardrobe with colors, hair, age, build). "
        "Output ONLY the prompt, no preamble.")
    kwargs = dict(prompt=f"Script:\n{script_text[:6000]}\n\nWrite the cast sheet prompt in that exact style.",
                  system_prompt=system, max_tokens=600, temperature=0.5)
    if model:
        kwargs["model"] = model
    text = await claude.generate(**kwargs)
    return (text or "").strip()


def _parse_props(val) -> list[dict] | None:
    """video_environments.props (migration 115) comes back from asyncpg as a
    raw JSON string (no jsonb codec registered — same reason routes/
    characters.py has its own _parse_json). None/'' /'[]' all normalize to
    None, the single falsy value every consumer treats as "no manifest"."""
    if val is None:
        return None
    if isinstance(val, list):
        return val or None
    try:
        parsed = json.loads(val)
    except Exception:  # noqa: BLE001
        return None
    return parsed or None if isinstance(parsed, list) else None


async def _approved_envs(vid, tenant) -> list[dict]:
    """The creator-approved environment references (the Environments tab).
    Empty for videos that never designed locations. `props` (C4, when
    present) is the environment's canonical prop manifest, parsed to a
    list[dict] ready for render_prop_manifest — absent/NULL stays None,
    every downstream consumer's existing no-manifest fallback. `material_map`
    (D6-1, migration 142, L20) is the location's canonical solid/transparent
    boundary text — NULL means no canonical map yet, and callers fall back
    to the planner LLM's own [MATERIAL|...] line (see _canonical_material_line)."""
    try:
        rows = await fetch_all(
            "SELECT name, description, reference_url, props, material_map "
            "FROM video_environments "
            "WHERE video_id=$1 AND tenant_id=$2 AND reference_url IS NOT NULL "
            "ORDER BY sort, created_at", vid, tenant)
        out = []
        for r in rows:
            if not (r.get("name") and r.get("reference_url")):
                continue
            d = dict(r)
            d["props"] = _parse_props(d.get("props"))
            out.append(d)
        return out
    except Exception:  # noqa: BLE001
        return []


def _norm_env_text(s: str) -> str:
    """Lowercase and collapse punctuation/dashes to single spaces, so
    'Home kitchen — cram session' matches 'home kitchen - cram session'."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _canonical_material_line(envs: list[dict], location_sets: dict,
                             matched_env: Optional[dict]) -> str:
    """D6-1 (L20 — MATERIAL MAP): the CODE-RENDERED, canonical material map,
    sourced from video_environments.material_map (migration 142) — this
    WINS over the planner LLM's own [MATERIAL | ...] line (storyboard.
    coverage.parse_material_map) whenever a canonical entry exists, never a
    paraphrase of it. Returns "" (never invents) when no canonical entry
    exists anywhere relevant, so the caller's existing parse_material_map
    fallback is unchanged for any video/environment that hasn't authored
    one yet — byte-compatible with every video before this migration.

    Multi-location scene (location_sets non-empty): one verbatim clause per
    LOCSET name that has a matching approved environment with a
    material_map. A location with no canonical entry is simply omitted from
    this string — KNOWN GAP, stated honestly rather than silently: a
    multi-location scene where only SOME locations have an authored
    material_map gets a canonical clause for those and nothing for the rest
    (not a fallback to the LLM line per missing location — mixing a
    canonical clause and an LLM clause for two locations in the SAME block
    would itself violate 'once, from one source of truth'). Closing that
    gap needs per-location fallback plumbing through _plan_sheet_prompts'
    single material_block slot; out of scope for this chunk.

    D6-6e fix: _find's per-LOCSET-name lookup used to require EXACT
    normalized equality against an approved environment's name — a LOCSET
    key the planner phrased with a leading article or extra prose (e.g.
    "The Elite Viewing Hall", the SAME stylistic drift D6-6b already found
    in this video's [SET|] header, but here inside a [LOCSET|] key on a
    genuinely multi-location scene) silently failed to match "Elite Viewing
    Hall", so that location's real material clause dropped out of the
    combined string entirely while a plainer-named sibling location (e.g.
    "Pod") matched exactly and appeared alone — reproducing the reported
    "pulled in the wrong location's material" symptom even with the correct
    approved environment on file. Fixed by matching the SAME way
    _env_named_in_header_opening (above) already resolves a declared
    location: the approved name must appear as a whole, space-bounded
    phrase WITHIN the LOCSET key's normalized text, not require the two to
    be identical — "elite viewing hall" now matches inside "the elite
    viewing hall". A LOCSET key that names a location with NO approved
    environment at all (whole word, not a substring hit) still correctly
    finds nothing, unchanged.

    Single-location scene (location_sets empty): the scene's ONE matched
    environment's material_map, or "" if it has none or nothing matched."""
    def _find(name: str) -> str:
        padded = f" {_norm_env_text(name)} "
        for e in envs:
            n = _norm_env_text(e.get("name") or "")
            if n and f" {n} " in padded:
                return (e.get("material_map") or "").strip()
        return ""

    if location_sets:
        parts = []
        for loc in location_sets:
            mm = _find(loc)
            if mm:
                parts.append(f"{loc.upper()}: {mm}")
        return " ".join(parts)
    if matched_env:
        return (matched_env.get("material_map") or "").strip()
    return ""


# The planner's own [SET | LocationName: description...] header names this
# scene's fixed location as the FIRST thing inside the brackets, before the
# first colon (parse_set_dressing, skills/video-pipeline/storyboard/
# coverage.py, returns the whole bracket body; this pulls just the name).
# When this matches an approved environment's name exactly, it settles the
# match outright — see _match_scene_env's bug note below for why this
# structural signal beats generic phrase-counting over the whole text.
_SET_HEADER_ENV_RE = re.compile(r"\[SET\s*\|\s*([^:\]]{1,80}):", re.IGNORECASE)

# How far into a [SET|]/[LOCSET|] header body (in NORMALIZED characters, i.e.
# after _norm_env_text collapses punctuation) an approved environment's name
# may start and still count as "this header is declaring that location".
# A header names its own location up front — "The Elite Viewing Hall, a
# private theatre high above the warren. Black ornamental walls…" puts it at
# index 4. Anything deeper than this is description, not declaration, and
# description is exactly where a passing mention of ANOTHER location lives
# ("…the screen currently displaying a live feed of the underground
# bubble-pod warren", ~330 chars into 686b4651 scene 2's own header). 120 is
# wide enough for a leading article plus a long location name, and far too
# narrow to reach a nested-frame mention buried in the set description.
_HEADER_NAME_WINDOW = 120


def _env_named_in_header_opening(text: str, envs: list[dict]) -> dict | None:
    """The approved environment this scene's own [SET|]/[LOCSET|] header
    DECLARES, or None when no header names an approved one.

    Structural, not statistical: unlike phrase-counting over the whole scene
    text, this only ever reads the planner's own location-declaring headers,
    and only their opening _HEADER_NAME_WINDOW characters — the slot where a
    header states which room the camera is standing in. It is deliberately
    blind to the rest of the text, so no amount of legitimate in-scene
    mention of a DIFFERENT location (a screen showing somewhere else) can
    reach it.

    Tolerates the two header shapes the planner actually emits, which is the
    whole point of this pass over the exact-match check above it:
      * "[SET | Elite Viewing Hall: black ornamental walls…]" — name, colon,
        description (what _SET_HEADER_ENV_RE handles).
      * "[SET | The Elite Viewing Hall, a private theatre high above the
        warren. Black ornamental walls…]" — a leading article, then the name,
        then comma-joined prose with no name/description colon at all. Live
        on video 8d90df90 scene 4. _SET_HEADER_ENV_RE cannot see this one:
        its `[^:\\]]{1,80}` can only reach a colon within 80 chars, and this
        header's first colon is ~800 chars in ("…a permanent feature of this
        set: a single curved screen…"), so it returned no match whatsoever
        and the whole header signal was silently skipped.

    Earliest start wins (ties broken by the longer name): a header opens with
    its own location, so the first approved name to appear in that opening
    window is the declared one."""
    heads = []
    set_body = parse_set_dressing(text or "")
    if set_body:
        heads.append(set_body)
    # L3 multi-location plans declare each location as a [LOCSET | <name> |
    # <text>] KEY. Those keys are the same kind of structural declaration as
    # a [SET|] opening, so read them the same way — a scene that names its
    # locations outright should never be handed to phrase-counting. The
    # FIRST key that resolves to an approved environment wins (dict order is
    # the order they appear in the plan — parse_location_sets preserves it).
    heads.extend(parse_location_sets(text or "").keys())

    for head in heads:
        padded = f" {_norm_env_text(head)} "
        best, best_at = None, None
        for e in envs:
            n = _norm_env_text(e.get("name") or "")
            if not n:
                continue
            at = padded.find(f" {n} ")
            if at < 0 or at > _HEADER_NAME_WINDOW:
                continue
            if best_at is None or at < best_at or (at == best_at and len(n) > len(
                    _norm_env_text(best.get("name") or ""))):
                best, best_at = e, at
        if best:
            return best
    return None


def _match_scene_env(text: str, envs: list[dict]) -> dict | None:
    """Pick the ONE approved environment this scene lives in.

    NAME-AS-PHRASE first: the coverage plan names its location verbatim from
    the bible ('Home kitchen — cram session. Ryan — ...' heads every shot), so
    count occurrences of each environment's full name, then its head segment
    (before any dash/colon). Single-WORD counting is a trap — scene 1's
    DIALOGUE says 'cooking class' over and over ('I have one hour to survive a
    cooking class'), which locked the home cram-session scene to the class
    kitchen (caught live 2026-07-07). Word counting survives only as the
    fallback when no name phrase appears at all. With one approved environment
    it always wins; with several and no signal, the fallback chain below picks.

    C8 fix (b): the word-count fallback used to hand the match to whichever
    environment had the HIGHEST word score with no floor at all — a SINGLE
    stray word was enough to win outright. Found live on video cd5d2883,
    Spanish Class scene 2 (the home cram-session scene: "Now the actions...
    peel... cut... fry"): neither environment's name appears as a phrase in
    the raw scene text (no directive/SET-line exists yet on a fresh plan —
    this function only ever sees scene_text at that point), and "Community
    cooking class kitchen"'s word set hits exactly ONE word ONE time ("class",
    from Vanessa's aside "In the class, you use a knife") while "Home kitchen
    — cram session"'s words hit zero times — a 1-0 score handed the whole
    scene to the wrong kitchen on that single coincidental word. The scene's
    own planner-generated [SET|] line independently, correctly describes the
    home kitchen (yellow fridge, sage cabinetry, copper pans) — this mislock
    happens before that text exists, so it silently misdirects the image
    reference anchor at picture-draw time.

    Now the word fallback requires MEANINGFULLY stronger evidence than one
    stray word before it decides anything: either >=2 DISTINCT words hit (not
    the same word repeated), or a >=2x score margin over the runner-up (with
    the runner-up at 0, that means a score of >=2). A lone word matched once,
    with nothing else backing it, no longer wins by default — the fallback
    chain below decides instead.

    That chain (in order), traced against what's actually available:
      1. story_bible scene->location mapping — doesn't exist. scene_aware_bible
         and _story_bible_locations (this same module) both deliberately
         refuse to guess one ("keyword scene->location matching proved
         unreliable (road vs street)"), so there is nothing to read here.
      2. previous scene's matched environment (continuity) — considered and
         REJECTED: this exact video's scenes alternate locations (scene 1 is
         genuinely the class kitchen per the check above, scene 2 is genuinely
         the home kitchen), so blindly inheriting the prior scene's match would
         silently reproduce this exact mislock one scene later, on a video
         that happens to be the very proof case for this fix.
      3. the first APPROVED environment (`envs[0]`, `_approved_envs`'s own
         `ORDER BY sort, created_at` — the creator's own primary/first-added
         location). Verified against real data: video cd5d2883 has "Home
         kitchen — cram session" at sort=0 and "Community cooking class
         kitchen" at sort=1, and scene 2 genuinely is the home kitchen — so
         this is both the deterministic AND the empirically correct choice
         here, unlike (2).

    D6-6b: a scene's OWN declared location now settles the match even when
    the header doesn't spell it in the one exact shape _SET_HEADER_ENV_RE
    can read — see _env_named_in_header_opening above. The third instance of
    the same bug class, found live 2026-07-30 on video 8d90df90 scene 4
    (envs: Pod, Corridor, Elite Viewing Hall). That scene's own header says
    "[SET | The Elite Viewing Hall, a private theatre high above the
    warren…]" and its ONE INSERT shot correctly describes what is ON the
    hall's screen — "one lit pod holding Nyla… the curve of her pod" (a
    BOARD-LAWS L11 nested frame: normal, expected, correct content). Phrase
    counting has no concept of "this mention is inside a nested frame, not
    the scene's own physical location", so "Pod" scored 2*3=6 against "Elite
    Viewing Hall"'s 1*3=3 and the scene was matched to the POD. The
    consequence is not cosmetic: video_environments.material_map for the
    WRONG environment got stamped into the emitted board-sheet prompt (the
    MATERIAL MAP block read the pod's clear-glass/white-shell text on a
    scene set in a solid-walled hall), and generate_coverage_for_video
    derives its matched_env from this same call, so the real per-shot
    pictures path inherits the same wrong lock.

    Note the two prior fixes did NOT cover this: the 686b4651 hyphen fix
    closed one specific way a passing mention's score got INFLATED, and the
    exact-header check only fires when the header names an approved
    environment verbatim before a colon. Here the score was never inflated
    (two honest "pod" mentions genuinely outnumber one "Elite Viewing Hall")
    and the header check never fired at all. The general lesson, now
    encoded: when the planner has DECLARED this scene's location, that
    declaration wins outright — phrase-counting the body text is only ever
    the guess we fall back to when nothing was declared.

    KNOWN LIMIT, stated rather than papered over: when a header exists but
    names a location with no approved video_environments row (the planner
    invented a name, or the creator renamed the environment after
    planning), there is nothing to return and the match still falls through
    to phrase scoring — with the same nested-frame blind spot. Closing that
    needs fuzzy name reconciliation between planner prose and approved rows,
    which is its own chunk."""
    if not envs:
        return None
    if len(envs) == 1:
        return envs[0]
    # STRONGEST signal, checked first: the planner's own [SET | Name: ...]
    # header (see _SET_HEADER_ENV_RE above) states this scene's location
    # directly and unambiguously — trust it outright when it names an
    # approved environment exactly, before falling through to phrase-scoring
    # the whole text. Bug found live on video 686b4651, scene 2: the SET
    # header correctly said "[SET | Elite Viewing Hall: ...]", but that same
    # scene's SET line ALSO mentions, in passing, that its screen "displays a
    # live feed of the underground bubble-pod warren" (a different, real
    # environment shown ON the screen, not the scene's own location) — a
    # coincidental hyphen-splitting bug (see the head-fragment comment below,
    # now fixed) inflated that passing mention's score to a TIE with the
    # scene's genuine "Elite viewing hall" match, and ties silently resolved
    # to whichever environment iterates first. Checking the header FIRST
    # sidesteps the whole tie question: the planner already told us the
    # answer, in a place a passing in-scene mention of another location can
    # never reach.
    header_match = _SET_HEADER_ENV_RE.search(text or "")
    if header_match:
        declared = _norm_env_text(header_match.group(1))
        for e in envs:
            if declared and _norm_env_text(e["name"] or "") == declared:
                return e
    # SAME structural signal, one step looser: the header declares this
    # scene's location but not in that one exact "Name: description" shape —
    # a leading article, or comma-joined prose with no name/description
    # colon at all. Still a DECLARATION, so it still beats phrase-counting
    # the body text (D6-6b, video 8d90df90 scene 4 — see the docstring).
    declared_env = _env_named_in_header_opening(text or "", envs)
    if declared_env:
        return declared_env
    low_text = f" {_norm_env_text(text)} "

    def _phrase_count(phrase: str) -> int:
        p = _norm_env_text(phrase)
        return low_text.count(f" {p} ") if p else 0

    best, best_score = None, 0
    for e in envs:
        name = e["name"] or ""
        # Bug found live on video 686b4651 (C-next): this used to split on
        # ANY bare hyphen (r"[—:\-]"), which also fires inside a compound
        # word that happens to be part of the environment's own name — e.g.
        # "Underground bubble-pod warren" split into head "Underground
        # bubble" at the hyphen in "bubble-pod", a meaningless fragment with
        # no relation to the location. That fragment then phrase-matched an
        # UNRELATED scene's SET line — scene 2 ("Elite Viewing Hall") merely
        # mentions in passing that its screen "displays a live feed of the
        # underground bubble-pod warren" — inflating "Underground bubble-pod
        # warren"'s score (3 name + 2 head = 5) above the scene's own,
        # correct "Elite viewing hall" (3, no head bonus — its name has no
        # separator), so the LOCKED LOCATION block locked scene 2's storyboard
        # prompt to the WRONG location, contradicting the prompt's own scene
        # description and tripping the image provider's content filter (the
        # prompt named two different, contradictory locations). Only split on
        # an em-dash/colon, or a hyphen with SPACES on both sides (the
        # "Title - Subtitle" separator pattern, same shape as the em-dash
        # case) — never a hyphen glued inside a single word like "bubble-pod".
        head = re.split(r"[—:]| - ", name)[0].strip()
        score = _phrase_count(name) * 3
        if head and _norm_env_text(head) != _norm_env_text(name) and len(head) >= 8:
            score += _phrase_count(head) * 2
        if score > best_score:
            best, best_score = e, score
    if best:
        return best
    # No environment NAME appears as a phrase — distinctive-word evidence,
    # but require it to be MEANINGFULLY stronger than a single stray word
    # (see docstring): >=2 distinct words hit, or a >=2x margin over the
    # runner-up (score >=2 when the runner-up is 0).
    scored = []
    for e in envs:
        words = {w for w in re.split(r"[^a-z0-9]+", (e["name"] or "").lower()) if len(w) > 3}
        hit_words = [w for w in words if low_text.count(w) > 0]
        score = sum(low_text.count(w) for w in words)
        scored.append((e, score, len(hit_words)))
    scored.sort(key=lambda t: t[1], reverse=True)
    top_e, top_score, top_distinct = scored[0]
    runner_score = scored[1][1] if len(scored) > 1 else 0
    strong = top_score > 0 and (
        top_distinct >= 2
        or (runner_score == 0 and top_score >= 2)
        or (runner_score > 0 and top_score >= 2 * runner_score)
    )
    if strong:
        return top_e
    # Evidence too weak to trust — fall back to the first approved environment
    # (see docstring for why this beats scene continuity here).
    return envs[0]


async def store_scene(vid, tenant, title, aspect, scene, frames_by_moment, location_id=None) -> int:
    """Delete this scene's prior coverage rows, then insert the new frames. Each
    item is (summary, frames, speaker, line); the moment's spoken line (assigned
    by the coverage planner) is stored on its MASTER frame as assigned_dialogue
    so it carries to the clip exactly. location_id (the approved environment
    name) rides every frame so downstream steps can re-resolve the scene's
    locked location. Returns count."""
    # Coverage is now this scene's plan of record: clear prior coverage rows AND
    # any pictureless leftovers from the earlier sentence-segmentation plan —
    # stale 'pending' rows inflate the picture totals (139/203 with nothing
    # actually missing) and mislead the Scenes page. Rows holding a paid image
    # or clip are never deleted.
    await execute(
        "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
        "AND (generation_method='coverage' "
        "OR (image_url IS NULL AND video_clip_url IS NULL))", vid, tenant, scene)
    from clip_dialogue import split_line_to_cap, MAX_SPOKEN_WORDS_PER_CLIP
    idx = COVERAGE_INDEX_BASE
    models_used: set[str] = set()
    for summary, frames, speaker, line in frames_by_moment:
        # THE CLIP-LENGTH RULE: a line longer than the clip model can speak in
        # its top duration tier gets split at sentence ends and spread across
        # this moment's frames (master speaks first, angles continue) — the
        # frames stitch in order, so the speech plays whole instead of being
        # cut mid-sentence at the duration cap. Overflow beyond the frame
        # count folds into the last frame (still shorter than the original).
        chunks = split_line_to_cap(line) if (speaker and line) else []
        usable = [fr for fr in frames if fr.get("_path") and os.path.exists(fr["_path"])]
        if len(chunks) > 1:
            # More chunks than frames: fold the tail into the final frame's
            # chunk — still far shorter than the unsplit original.
            if len(chunks) > len(usable) and usable:
                chunks = chunks[:len(usable) - 1] + [" ".join(chunks[len(usable) - 1:])]
            print(f"  [scene {scene}] split a {len((line or '').split())}-word "
                  f"{speaker} line across {len(chunks)} shots "
                  f"(cap {MAX_SPOKEN_WORDS_PER_CLIP} words/clip)", flush=True)
        for fi, fr in enumerate(usable):
            with open(fr["_path"], "rb") as f:
                data = f.read()
            url = await upload_bytes(data, f"{vid}/coverage/S{scene}_i{idx}.png", "image/png", tenant)
            is_master = fr.get("role") == "master"
            # The line lives on the speaking (master) frame; angles are
            # cutaways UNLESS they carry an overflow chunk of a long line
            # (frames stitch in order, so the speech plays whole).
            assigned = f'{speaker}: "{chunks[fi]}"' if fi < len(chunks) else None
            await execute(
                "INSERT INTO assets (id, tenant_id, video_id, scene, image_index, sentence_index, "
                "sentence_text, image_prompt, shot_type, video_title, aspect_ratio, status, "
                "image_url, drive_image_url, hero_shot, generation_method, assigned_dialogue, "
                "location_id, camera_movement, image_model, routed_model, routing_reason, "
                "duration_seconds, shot_location, group_arrangement, purpose_kind, shot_purpose, "
                "transition_kind, continuity_bridge, caused_by) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'done',$12,$13,$14,'coverage',"
                "$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28)",
                str(uuid.uuid4()), tenant, vid, scene, idx, idx,
                # D3-62: image_prompt used to be hard-sliced to 1000 chars here —
                # a copy-paste of the short-bio [:1000] convention used elsewhere
                # in this codebase (character/environment description fields),
                # applied to the WRONG kind of text. Those are short human-authored
                # bios; this is the full per-shot draw prompt with every SET/AXIS/
                # STAGING/SEQUENCE/FACING lock tail appended (coverage.py) — often
                # well over 1000 chars, and the cut landed mid-word INSIDE a lock's
                # tail on live rows (S-01.107-109, video 686b4651: all three exactly
                # 1000 chars, cut mid-word). assets.image_prompt is documented
                # (coverage.py's SEQUENCE LOCK comment) as the VERBATIM base prompt
                # a later manual redraw reuses — a silently truncated lock tail is a
                # verbatim-storage bug, not a size limit: the assets.image_prompt
                # column is unbounded TEXT (migrations/000_baseline_schema.sql), so
                # there was never a DB constraint requiring this slice. Store the
                # full prompt.
                summary[:500], fr.get("description") or "", fr.get("shot_type") or "",
                title, aspect, url, url, is_master, assigned, location_id,
                fr.get("camera_move"),  # camera engine plan: "move_id|PURPOSE" or "static"
                fr.get("image_model"),  # WHICH model actually drew this frame (image_model_router)
                fr.get("routed_model"),  # C12 (checklist §1.2): recommended video model, plan-time
                fr.get("routing_reason"),  # human-readable "why" for the pick above
                # C3 item 4: coverage.py's stamp_shot_durations' per-shot-type
                # target (SILENT shots only — None for a speaking master, which
                # sizes from measured speech instead; render_perform.py reads
                # this column as a pro-rata WEIGHT when splitting a narration
                # block, falling back to word-count when it's NULL — legacy
                # rows and non-coverage assets are unaffected).
                fr.get("duration_seconds"),
                # D6-2 (migration 143): the per-shot location/computed group
                # arrangement (coverage.py's run_coverage persist + L17/L22
                # repair-leg blocks, threaded through generate_coverage_
                # frames' frame dicts). None for the overwhelming majority
                # of shots (no group/location signal) — unchanged from
                # before this migration.
                fr.get("shot_location"), fr.get("group_arrangement"),
                # D9-1 (migration 147): the per-shot narrative-purpose signal
                # (coverage.py's parse_coverage, threaded through generate_
                # coverage_frames' frame dicts) — None for the overwhelming
                # majority of shots (planner didn't tag this one, or it's a
                # code-synthesized floor shot), unchanged from before this
                # migration.
                fr.get("purpose_kind"), fr.get("shot_purpose"),
                # D9-6/D9-7 (migration 148): the per-shot transition/causality
                # signals (coverage.py's parse_coverage, threaded through
                # generate_coverage_frames' frame dicts) — None for the
                # overwhelming majority of shots (planner didn't tag this
                # one, or it's a code-synthesized floor shot), unchanged
                # from before this migration.
                fr.get("transition_kind"), fr.get("continuity_bridge"), fr.get("caused_by"),
                # model_used (C13) stays NULL here — no INSERT column for it — until
                # clip generation records which model actually ran this shot.
            )
            if fr.get("image_model"):
                models_used.add(fr["image_model"])
            idx += 1
    n = idx - COVERAGE_INDEX_BASE
    if n > 0:
        # generation_ledger (checklist §0.3b/C08, priced per-model in
        # §0.3c/C09): one row per store_scene() call — the natural per-batch
        # unit (one scene's coverage frames land in a single call), not one
        # row per frame. model_label is the single real model when every
        # frame in the batch used the same one — price with that model's
        # real rate; a mixed/unknown batch falls back to the blended
        # default inside picture_price_for().
        from actions import picture_price_for
        model_label = (sorted(models_used)[0] if len(models_used) == 1
                       else (", ".join(sorted(models_used)) if models_used else None))
        picture_cost = picture_price_for(model_label)
        await record_ledger_entry(
            tenant_id=tenant, video_id=vid, stage="image", model=model_label,
            units=n, unit_cost=picture_cost, actual_cost=round(n * picture_cost, 2),
        )
    return n


def load_existing(outdir):
    """Reuse already-generated frames: read coverage.json + the PNGs on disk so we can
    upload+insert without regenerating (and re-spending). Returns moments or None."""
    p = os.path.join(outdir, "coverage.json")
    if not os.path.exists(p):
        return None
    moments = (json.load(open(p)) or {}).get("moments") or []
    for m in moments:
        for fr in m.get("frames", []):
            fr["_path"] = os.path.join(outdir, fr["file"]) if fr.get("file") else None
    return moments or None


async def load_character_bible(vid, tenant):
    """Build a BINDING visual bible from the locked cast so the writer uses the SAME character
    appearance in every shot. The cast-sheet image alone does not lock the writer's words — the
    image model paints whatever the description says, so the description must be locked too.

    D6-1 (L6 — IDENTITY ONCE): prefers the canonical identity_tag (migration
    142, video_characters.identity_tag) over description as the bible's
    "costume" field — identity_tag is a short, AUTHORED-ONCE locked tag;
    description is long free prose meant for the cast-sheet portrait prompt,
    which _character_identity_line was previously truncating to 60 chars as
    a stand-in for a real tag (an arbitrary mid-thought cut, not an authored
    fact). NULL identity_tag falls back to description, byte-identical to
    before this column existed."""
    rows = await fetch_all(
        "SELECT name, identity_tag, description FROM video_characters WHERE video_id=$1 "
        "AND tenant_id=$2 AND (identity_tag IS NOT NULL OR description IS NOT NULL) "
        "ORDER BY sort", vid, tenant)
    chars = []
    for r in rows:
        tag = (r.get("identity_tag") or "").strip()
        costume = tag if tag else (r.get("description") or "")
        chars.append({"id": r["name"], "costume": costume, "scenes_present": []})
    return {"characters": chars} if chars else None


_NAME_STOPWORDS = {"the", "mr", "mrs", "ms", "dr", "miss", "aunt", "uncle", "sir", "lady", "a", "an"}


def _scenes_present_for(name: str, scene_rows) -> list:
    """Scene numbers a character appears in — word-boundary match of the character's
    distinctive name token(s) in each scene's text (titles like 'Mr.' are skipped so
    'Mr. Brown' matches on 'Brown'). Empty list => the bible formatter treats them as
    'present everywhere' (its existing fallback)."""
    toks = [t for t in re.split(r"[\s.]+", (name or "").strip())
            if len(t) >= 3 and t.lower() not in _NAME_STOPWORDS]
    if not toks:
        toks = [(name or "").strip()]
    pats = [re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE) for t in toks if t]
    out = []
    for s in scene_rows:
        txt = s.get("scene_text") or ""
        if s.get("scene") is not None and any(p.search(txt) for p in pats):
            out.append(s["scene"])
    return out


async def scene_aware_bible(vid, tenant, scene_rows, claude=None, model=None):
    """A character bible with per-scene PRESENCE filled in, so coverage's existing
    _format_story_bible_for_beat injects ONLY each scene's actual characters — the
    1-character-per-scene lock (a scene that genuinely has two keeps both). Uses the
    locked video_characters if present, else extracts the cast from the script. This
    ADAPTS machinery that already exists (the formatter + presence filter): it was
    only ever handed empty scenes_present, so every character leaked into every scene.

    D10-3a: also attaches `narrative` (and `relationships`, when present) straight off
    videos.story_bible when this video's bible is StoryEngine-native (D10-2ab,
    backend/story_bible_native.py) — the coverage/board planner had ZERO per-video
    tone/genre signal before this (LAW 3, above in this file, wires only a
    CHANNEL-wide tone hint into the motion writer, a different function entirely). A
    legacy/absent/unparseable story_bible attaches neither key, so every video's bible
    from before today is unchanged — see _board_rules_text_with_narrative below for
    where these two keys actually reach the planner prompt."""
    bible = await load_character_bible(vid, tenant)
    if not bible and claude is not None:
        full = "\n\n".join((s.get("scene_text") or "") for s in scene_rows)
        cast = await extract_characters(claude, full, model=model)
        if cast:
            bible = {"characters": [{"id": c["name"], "costume": c["description"],
                                     "scenes_present": []} for c in cast]}
    if not bible:
        bible = {"characters": []}
    for ch in bible.get("characters", []):
        ch["scenes_present"] = _scenes_present_for(ch.get("id", ""), scene_rows)
    # Locked locations (the prose scene lock): prefer the creator-APPROVED video_environments
    # (the reviewed set, each with a reference image), else the story bible. Unscoped on purpose —
    # keyword scene->location matching proved unreliable (road vs street), so the director sees the
    # full LOCKED set and picks the one that fits each shot + reuses it identically, NEVER inventing
    # a location outside this set (the 'kitchen that wasn't an environment' bug).
    locs = await _scene_locations(vid, tenant)
    if locs:
        bible["locations"] = locs
    # D10-3a: a SEPARATE read of the same story_bible column (never routed through
    # _scene_locations' story-bible fallback above, which only fires when this video
    # has no approved video_environments rows) — narrative signal must reach the
    # planner regardless of whether the video has approved environments.
    narrative, relationships = await _story_bible_narrative_context(vid, tenant)
    if narrative:
        bible["narrative"] = narrative
    if relationships:
        bible["relationships"] = relationships
    return bible if (bible.get("characters") or bible.get("locations")
                     or bible.get("narrative")) else None


async def _scene_locations(vid, tenant) -> list:
    """The locked locations to feed the director: the creator-APPROVED video_environments first
    (reviewed, each with a reference image), else the story bible's locations. Shaped for
    _format_story_bible_for_beat; scenes_present omitted so the director picks the right one per shot.
    `reference_url` is carried for the image-anchor step. `props` (C4, when the environment has
    one) is the canonical prop manifest — _format_story_bible_for_beat renders it verbatim; absent
    means no manifest and the formatter's prior prose-only behavior is unchanged."""
    rows = await fetch_all(
        "SELECT name, description, reference_url, props FROM video_environments "
        "WHERE video_id=$1 AND tenant_id=$2 ORDER BY sort", vid, tenant)
    envs = [r for r in (rows or []) if (r.get("description") or "").strip()]
    if envs:
        return [{"id": r["name"] or "location", "description": r["description"], "lighting": "",
                 "type": "", "reference_url": r.get("reference_url"),
                 "props": _parse_props(r.get("props"))} for r in envs]
    return await _story_bible_locations(vid, tenant)


async def _story_bible_locations(vid, tenant) -> list:
    """Locked locations from videos.story_bible, shaped for _format_story_bible_for_beat.
    scenes_present is omitted (=> the formatter shows them in every scene) so the director
    chooses; we don't force a guessed scene->location mapping."""
    row = await fetch_one("SELECT story_bible FROM videos WHERE id=$1 AND tenant_id=$2", vid, tenant)
    sb = (row or {}).get("story_bible")
    if isinstance(sb, str):
        try:
            sb = json.loads(sb)
        except Exception:  # noqa: BLE001
            return []
    if not isinstance(sb, dict):
        return []
    out = []
    for loc in (sb.get("locations") or []):
        if loc.get("description"):
            out.append({"id": loc.get("id", "location"), "description": loc.get("description"),
                        "lighting": loc.get("lighting", ""), "type": loc.get("type", "")})
    return out


async def _story_bible_narrative_context(vid, tenant) -> tuple[dict, list]:
    """D10-3a: the video's StoryEngine-native story_bible `narrative` section
    (D10-2ab, backend/story_bible_native.py — genre/tone/themes/conflict/stakes/
    time_period/world_rules) plus its `relationships` list (character-pair dynamics),
    read straight off videos.story_bible. A SEPARATE fetch from _story_bible_locations
    above (same column) because that one only runs when this video has no approved
    video_environments rows — this signal must reach scene_aware_bible's caller
    regardless of environment state.

    Returns ({}, []) when the column is NULL, unparseable JSON, or predates D10-2ab
    (every video's bible before today) — scene_aware_bible then attaches neither key
    to the bible dict, so the planner prompt _board_rules_text_with_narrative builds
    below is BYTE-IDENTICAL to before this feature existed."""
    row = await fetch_one("SELECT story_bible FROM videos WHERE id=$1 AND tenant_id=$2", vid, tenant)
    sb = (row or {}).get("story_bible")
    if isinstance(sb, str):
        try:
            sb = json.loads(sb)
        except Exception:  # noqa: BLE001
            return {}, []
    if not isinstance(sb, dict):
        return {}, []
    narrative = sb.get("narrative")
    narrative = narrative if isinstance(narrative, dict) else {}
    relationships = sb.get("relationships")
    relationships = relationships if isinstance(relationships, list) else []
    return narrative, relationships


def _narrative_context_block(bible: Optional[dict]) -> str:
    """D10-3a: render the bible's `narrative` (and `relationships`) section — attached
    by scene_aware_bible above, straight off videos.story_bible — as one clearly
    delimited <narrative> block for the coverage/board planner prompt.

    "" when `bible` is absent or carries no non-empty `narrative` dict (every video's
    bible today, and any bible whose story_bible predates D10-2ab or has an empty
    {} narrative section) — the caller (_board_rules_text_with_narrative) then
    composes an empty addition, so the assembled planner prompt is BYTE-IDENTICAL to
    before this feature existed.

    Narrative fields are whole-video facts (genre/tone/themes/...), not per-scene —
    unlike visual_arc/scene_blocks (_format_story_bible_for_beat, storyboard/bot.py),
    this block is never filtered by beat_scenes; the same block applies to every
    scene of the video. relationships lines are appended ONLY when the narrative
    block itself is non-empty (relationships alone, with no narrative facts, is not
    a shape the D10-2ab generator produces — it always writes both sections
    together)."""
    narrative = (bible or {}).get("narrative")
    if not isinstance(narrative, dict):
        narrative = {}
    lines = []
    if narrative.get("genre"):
        lines.append(f"Genre: {narrative['genre']}")
    if narrative.get("tone"):
        lines.append(f"Tone: {narrative['tone']}")
    themes = [str(t) for t in (narrative.get("themes") or []) if t]
    if themes:
        lines.append(f"Themes: {', '.join(themes)}")
    if narrative.get("conflict"):
        lines.append(f"Conflict: {narrative['conflict']}")
    if narrative.get("stakes"):
        lines.append(f"Stakes: {narrative['stakes']}")
    if narrative.get("time_period"):
        lines.append(f"Time period: {narrative['time_period']}")
    world_rules = [str(w) for w in (narrative.get("world_rules") or []) if w]
    if world_rules:
        lines.append(f"World rules: {'; '.join(world_rules)}")
    if not lines:
        return ""
    block = "<narrative>\n" + "\n".join(lines) + "\n</narrative>"
    rel_lines = []
    for r in ((bible or {}).get("relationships") or []):
        if not isinstance(r, dict):
            continue
        chars = r.get("characters") or []
        dynamic = (r.get("dynamic") or "").strip()
        if len(chars) == 2 and dynamic:
            rel_lines.append(f"{chars[0]} & {chars[1]}: {dynamic}")
    if rel_lines:
        block += "\n<relationships>\n" + "\n".join(rel_lines) + "\n</relationships>"
    return block


def _board_rules_text_with_narrative(board_rules_text: str, bible: Optional[dict]) -> str:
    """D10-3a: the final board_rules_text passed to generate_coverage_directive at
    both of its coverage_to_app.py call sites (generate_storyboard_sheet_for_scene
    and generate_coverage_for_video's directive-planning fallback, below) — the
    narrative block (if any) FIRST, since scene-setting story context belongs before
    the procedural quality-rule list that follows it, then whatever board-scoped
    quality_rules text this call already composed.

    generate_coverage_directive's own docstring calls board_rules_text "pre-composed
    ... text ... this module stays DB-free and takes the already-fetched text as
    plain data, same pattern as `profile`/`story_bible`" — this is that same
    caller-composed free-text hook, the only one that reaches the planner's system
    prompt (storyboard/coverage.py::_coverage_system_prompt) without editing
    storyboard/coverage.py itself (out of scope for this chunk).

    "" + "" => "" — when neither a narrative block nor board-scoped quality rules
    exist (every video's bible today), the composed text is empty and
    generate_coverage_directive's <board_quality_rules> block is omitted entirely,
    exactly as it is today."""
    parts = [p for p in (_narrative_context_block(bible), (board_rules_text or "").strip()) if p]
    return "\n\n".join(parts)


def compose_grid(paths, cols=4):
    """Compose coverage frames into one contact-sheet grid (bytes) for the storyboard
    'Board' slot. Fills left-to-right, ~16:9 cells. Returns None if no frames."""
    from PIL import Image
    imgs = [Image.open(p).convert("RGB") for p in paths if p and os.path.exists(p)]
    if not imgs:
        return None
    cw, ch, pad = 640, 360, 8
    rows = (len(imgs) + cols - 1) // cols
    W, H = cols * cw + (cols + 1) * pad, rows * ch + (rows + 1) * pad
    canvas = Image.new("RGB", (W, H), (16, 16, 20))
    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        canvas.paste(im.resize((cw, ch)), (pad + c * (cw + pad), pad + r * (ch + pad)))
    buf = BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue()


async def extract_characters(claude, script_text, model=None):
    """Ask Claude for the distinct on-screen characters: NAME :: description :: portrait prompt."""
    system = (
        "From the script, list the distinct on-screen characters and key creatures (max 4). "
        "Output one line per character, EXACTLY in the form: NAME :: one-line visual description "
        ":: a short portrait prompt (subject only, no art-style words). No preamble, no numbering, "
        "one character per line.")
    kwargs = dict(prompt=f"Script:\n{script_text[:6000]}", system_prompt=system,
                  max_tokens=700, temperature=0.4)
    if model:
        kwargs["model"] = model
    text = await claude.generate(**kwargs)
    chars = []
    for line in (text or "").splitlines():
        if "::" not in line:
            continue
        parts = [p.strip() for p in line.split("::")]
        if len(parts) >= 3 and parts[0]:
            name = parts[0].lstrip("-*0123456789. ").strip()
            if name:
                chars.append({"name": name[:80], "description": parts[1][:500], "portrait": parts[2]})
    return chars[:4]


async def _stable_url(maybe_url, dest_path, tenant):
    """Re-host a (possibly temporary) image URL into Supabase so the app has a permanent URL."""
    if not maybe_url:
        return None
    try:
        req = urllib.request.Request(maybe_url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=120).read()
        return await upload_bytes(data, dest_path, "image/png", tenant)
    except Exception:
        return maybe_url


async def populate_characters(vid, tenant, claude, claude_model, ic, base_dir, script_text, style=None):
    """Write video_characters rows (the Characters tab) from the cast. Skips if any exist.
    Generates a portrait per character anchored on the on-disk cast sheet, in the creator's
    chosen style (so a 3D Pixar video gets Pixar character art, not realistic)."""
    existing = await fetch_one(
        "SELECT count(*) AS n FROM video_characters WHERE video_id=$1 AND tenant_id=$2", vid, tenant)
    if existing and existing["n"]:
        print(f"  characters: {existing['n']} already present — skipping")
        return existing["n"]
    cast_local = os.path.join(base_dir, "0_cast_sheet.png")
    cast_url = None
    if os.path.exists(cast_local):
        with open(cast_local, "rb") as f:
            cast_url = await upload_bytes(f.read(), f"{vid}/characters/_cast.png", "image/png", tenant)
    style_clause = (
        f" Render in this EXACT style, matching the attached cast reference's look: {style.strip()}."
        if style and style.strip()
        else " Photoreal and realistic, matching the attached cast reference's exact look and "
             "rendering style; never 2D illustration or cartoon.")
    # Use the SAME multi-angle generator the Characters tab / "Redesign Cast" uses, so the
    # auto-build produces a proper 4-view reference SHEET per character (the 360 consistency
    # anchor) and ALWAYS persists it — with retry. The old path only made an image when an
    # on-disk cast sheet happened to be present, and used a single-view prompt, which left
    # reference_url NULL and the Characters tab empty.
    from routes.characters import _generate_portrait, _persist_portrait_url
    from actions import budget_check, picture_price_for, video_summary
    from generation_ledger import record_ledger_entry
    chars = await extract_characters(claude, script_text, model=claude_model)
    n = 0
    for i, ch in enumerate(chars):
        # Money-safety fix: this content-engine cast build spent real GPT
        # Image 2 calls with no ledger write and no cap check, same hole as
        # the Characters tab. Checked fresh every character since spend
        # accrues across the loop.
        summary = await video_summary(tenant, vid)
        breach = budget_check(summary, picture_price_for(None)) if summary else None
        if breach:
            print(f"  characters: stopped at {n}/{len(chars)} — would put this video at "
                  f"${breach['projected']:.2f} against its ${breach['cap']:.2f} cap")
            break
        row = await fetch_one(
            "INSERT INTO video_characters (tenant_id, video_id, name, description, "
            "status, source, sort) VALUES ($1,$2,$3,$4,'approved','generated',$5) RETURNING id",
            tenant, vid, ch["name"], ch["description"], i)
        char_id = str(row["id"])
        for attempt in range(3):
            try:
                portrait = await _generate_portrait(ic.api_key, ch.get("description") or ch["name"], style or "", name=ch.get("name") or "")
                ref = await _persist_portrait_url(tenant, vid, char_id, portrait["url"])
                await execute("UPDATE video_characters SET reference_url=$1, updated_at=now() WHERE id=$2",
                              ref, char_id)
                cost = picture_price_for(portrait["model"])
                await record_ledger_entry(
                    tenant_id=tenant, video_id=vid, stage="character_sheet",
                    model=portrait["model"], units=1, unit_cost=cost, actual_cost=cost,
                    kie_task_id=portrait.get("task_id"),
                )
                break
            except Exception as e:  # noqa: BLE001
                print(f"  character {ch['name']} sheet attempt {attempt+1} failed: {str(e)[:120]}")
                await asyncio.sleep(2 * (attempt + 1))
        n += 1
        print(f"  character: {ch['name']}")
    return n


# Shot-on-screen seconds by shot type → drives the storyboard timecodes (content-engine pacing).
_CUT = {"WS": 3.5, "ELS": 3.5, "WIDE": 3.5, "MS": 2.5, "MCU": 2.5, "MEDIUM": 2.5,
        "CU": 2.0, "OTS": 2.0, "INSERT": 1.5, "ECU": 1.5}
_BOARD_CSS = (
    "body{margin:0;background:#0d0d10;font-family:'DejaVu Sans',sans-serif;padding:26px}"
    ".card{background:#f3f1ec;border-radius:18px;padding:24px}"
    "h1{font-size:19px;margin:0 0 2px;color:#1a1a1a}.sub{color:#7a756c;font-size:12px;margin-bottom:18px}"
    ".grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}"
    ".panel{background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}"
    ".iw{position:relative;aspect-ratio:16/9;background:#222}.iw img{width:100%;height:100%;object-fit:cover;display:block}"
    ".num{position:absolute;top:7px;left:7px;background:rgba(15,15,18,.85);color:#fff;font-weight:700;font-size:12px;padding:3px 9px;border-radius:6px}"
    ".tc{position:absolute;top:7px;right:7px;background:rgba(15,15,18,.7);color:#fff;font-size:11px;padding:3px 8px;border-radius:6px}"
    ".cap{padding:10px 12px 13px}.lbl{font-size:10px;font-weight:700;letter-spacing:.5px;color:#b06a2c;text-transform:uppercase;margin-bottom:5px}"
    ".desc{font-size:12px;line-height:1.42;color:#33312e}")


def _burger_cells(moments):
    """Flatten moments into numbered, timecoded panel cells with LEAN captions —
    speaker + spoken line for a speaking moment, else the planner's one-line
    moment summary. The full image prompt stays in the app (prompt expander);
    the board is a shot list, not a spec sheet."""
    import base64
    from PIL import Image

    def tc(s):
        return f"{int(s) // 60}:{int(s) % 60:02d}"

    cells, t, n = [], 0.0, 0
    for m in moments:
        speaker, line = (m.get("speaker") or "").strip(), (m.get("line") or "").strip()
        if speaker and line:
            cap = f'SPEAKING {speaker}: “{line}”'
        else:
            cap = (m.get("summary") or "").strip()
        for fr in m["frames"]:
            p = fr.get("_path")
            if not p or not os.path.exists(p):
                continue
            try:
                im = Image.open(p).convert("RGB")
                im = im.resize((720, int(im.height * 720 / im.width)))
                buf = BytesIO()
                im.save(buf, "JPEG", quality=85)
                uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception:
                continue
            n += 1
            st = (fr.get("shot_type") or "").split()[0].upper()
            lbl = _html.escape((fr.get("shot_type") or "").upper()) + f" &middot; Moment {m['moment_number']}"
            desc = _html.escape((cap or (fr.get("description") or ""))[:130])
            cells.append(
                f'<div class="panel"><div class="iw"><img src="{uri}">'
                f'<span class="num">{n}</span><span class="tc">{tc(t)}</span></div>'
                f'<div class="cap"><div class="lbl">{lbl}</div><div class="desc">{desc}</div></div></div>')
            t += _CUT.get(st, 2.0)
    return cells


def _render_board_png(cells, title, scene, page, pages):
    """Render one board page (a list of panel cells) to PNG via headless chromium.
    Frames are embedded as base64 (snap chromium can't read /tmp) and the HTML +
    output live under $HOME (the only tree the snap's home interface allows).
    Returns PNG bytes or None."""
    n = len(cells)
    rows = (n + 3) // 4
    page_note = f" &middot; board {page}/{pages}" if pages > 1 else ""
    body = (f'<div class="card"><h1>{_html.escape(title)} — Scene {scene}</h1>'
            f'<div class="sub">Cinematic shot list{page_note} &middot; {n} shots &middot; coverage built in '
            f'(master + matched angles per moment)</div><div class="grid">{"".join(cells)}</div></div>')
    html_str = (f'<!doctype html><html><head><meta charset="utf-8"><style>{_BOARD_CSS}</style></head>'
                f'<body>{body}</body></html>')

    rdir = os.path.expanduser("~/coverage_render")
    os.makedirs(rdir, exist_ok=True)
    hp = os.path.join(rdir, f"board_s{scene}_p{page}.html")
    pp = os.path.join(rdir, f"board_s{scene}_p{page}.png")
    with open(hp, "w") as f:
        f.write(html_str)
    if os.path.exists(pp):
        os.remove(pp)
    height = 180 + rows * 360
    for binname in ("chromium-browser", "chromium", "google-chrome"):
        try:
            subprocess.run(
                [binname, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                 f"--screenshot={pp}", f"--window-size=1640,{height}",
                 "--force-device-scale-factor=2", f"file://{hp}"],
                check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(pp) and os.path.getsize(pp) > 2000:
                with open(pp, "rb") as f:
                    return f.read()
        except Exception:
            continue
    return None


# Panels per rendered board page. 12 (3 rows of 4) keeps each board readable
# at the workspace card size; a long scene pages across the 5 board slots.
_BOARD_PAGE_SIZE = 12


def render_burger_boards(moments, title, scene, workdir=None):
    """Render the scene's coverage frames as burger-style board PAGES (numbered,
    timecoded, lean captions), ~12 panels each, capped at the 5 board slots.
    Returns a list of PNG bytes (possibly empty)."""
    cells = _burger_cells(moments)
    if not cells:
        return []
    pages = [cells[i:i + _BOARD_PAGE_SIZE] for i in range(0, len(cells), _BOARD_PAGE_SIZE)][:5]
    out = []
    for pi, page_cells in enumerate(pages, start=1):
        png = _render_board_png(page_cells, title, scene, pi, len(pages))
        if png:
            out.append(png)
    return out


# Canonical CHARACTER-CREATION prompt (Ryan's locked 4-view reference-sheet template). Each
# character gets a clean photoreal 4-view sheet — the strongest consistency anchor (far better
# than one combined cast image). See ~/Desktop/character-creation-prompt.md.
CHARACTER_SHEET_STYLE = (
    "PHOTOREALISTIC — a real PHOTOGRAPH / live-action film still of a real subject. Real skin pores, "
    "real metal, real fabric, real scale/fur texture, true cinematic lighting, shot on a cinema camera, "
    "ultra-detailed, indistinguishable from live action. It is NOT a painting, drawing, illustration, "
    "concept art, sketch, render-that-looks-painted, or anime — a real photograph only.")
CHARACTER_SHEET_TEMPLATE = (
    "Professional character reference sheet. {style}\n\n"
    "Character: {desc}\n\n"
    "Layout: the SAME character in four views on a plain neutral grey studio background — "
    "Full Body Front (slight three-quarter front, head to toe); Full Body Back (straight rear, full "
    "body); Front Portrait (head-and-shoulders front, facial features + hair + upper clothing); "
    "Side Portrait (head-and-shoulders left profile, 90-degree side view).\n\n"
    "Keep the same face, body proportions, hairstyle, outfit, colours and accessories across all four "
    "views; preserve exact costume details and identity in every angle; clean balanced studio "
    "lighting, soft shadows, realistic material textures; sharp high detail. Neutral grey background "
    "only; no text, labels, logos, watermarks, props, or extra characters; symmetrical layout with "
    "equal spacing between the views.")


async def redo_characters(vid, tenant, claude, claude_model, ic, script_text, only=None):
    """Rebuild each character as a precise, PHOTOREAL 4-VIEW reference sheet (the locked
    character-creation prompt), and tighten its description so the writer-bible matches. Generated
    FRESH text-to-image (no anchor) so a prior painterly sheet can't leak back in. Updates
    video_characters.description + reference_url. Does NOT touch scenes. `only` = one name."""
    rows = await fetch_all("SELECT id, name, description FROM video_characters "
                           "WHERE video_id=$1 AND tenant_id=$2 ORDER BY sort", vid, tenant)
    rows = [r for r in rows if not only or r["name"].lower() == only.lower()]
    if not rows:
        print("No characters to redo."); return 0
    v = await fetch_one("SELECT image_model_override FROM videos WHERE id=$1 AND tenant_id=$2", vid, tenant)
    model_override = (v or {}).get("image_model_override")
    # Money-safety fix: this CLI-only rebuild is a real image spend (nano-banana-2
    # or GPT Image 2 depending on model_override) with NO generation_ledger write
    # and NO cap check — same per-iteration pattern every other character/image
    # generation loop in this codebase now uses (actions.budget_refusal). Not
    # reachable from the app today (CLI-only), but it duplicates a feature
    # (character-sheet generation) that IS metered elsewhere in the app
    # (routes/characters.py), so it's fixed the same way here rather than left
    # as a second, silent way to spend on the same video.
    from actions import budget_refusal, picture_price_for
    n = 0
    for r in rows:
        refusal = await budget_refusal(tenant, vid, picture_price_for(model_override), "this character sheet")
        if refusal:
            print(f"  Stopped — {refusal}")
            break
        desc = (r["description"] or "").strip()
        # tighten only if it isn't already a precise locked description
        if len(desc) < 200:
            sys_p = ("Expand the character into a precise PHOTOREAL visual description for a reference "
                     "sheet, 60-90 words. Specify age, build, face, hair (style + colour), exact "
                     "wardrobe/armour WITH COLOURS and accessories; for a creature give scale colour, "
                     "horns, wings, eyes and size. Concrete and specific so an image model renders the "
                     "SAME character every time. Output ONLY the description, no preamble.")
            kw = dict(prompt=f"{r['name']}: {desc}\n\nStory context:\n{script_text[:2500]}",
                      system_prompt=sys_p, max_tokens=400, temperature=0.4)
            if claude_model:
                kw["model"] = claude_model
            desc = ((await claude.generate(**kw)) or "").strip() or r["description"]
        prompt = CHARACTER_SHEET_TEMPLATE.format(style=CHARACTER_SHEET_STYLE, desc=desc)
        # No reference image — the 4-view sheet IS the identity anchor being (re)built.
        url, model_used = await generate_scene_image_for_model(ic, model_override, prompt, aspect_ratio="16:9")
        if not url:
            print(f"  {r['name']}: 4-view sheet generation FAILED — keeping old"); continue
        stable = await _stable_url(url, f"{vid}/characters/{r['name'].replace(' ', '_')}_sheet.png", tenant)
        await execute("UPDATE video_characters SET description=$1, reference_url=$2, updated_at=now() "
                      "WHERE id=$3", desc, stable, r["id"])
        sheet_cost = picture_price_for(model_used)
        await record_ledger_entry(
            tenant_id=tenant, video_id=vid, stage="character_sheet", model=model_used,
            units=1, unit_cost=sheet_cost, actual_cost=sheet_cost,
        )
        n += 1
        print(f"  {r['name']}: PHOTOREAL 4-view sheet set")
    return n


async def set_scene_board(vid, tenant, scene, outdir, title="Storyboard"):
    """FALLBACK boards: render the scene's coverage frames into burger-style
    board PAGES (contact sheets of the real frames) and fill ALL the board
    slots, clearing leftovers. Callers must NOT invoke this when the frames
    were drawn anchored to approved gate sheets — those boards are the
    creator's scene lock and stay put (Ryan's board-anchored workflow,
    2026-07-06). Used when the gate never ran, the scene re-planned (stale
    sheets), or --complete rebuilds a video from frames on disk. Falls back
    to a plain grid if chromium fails."""
    moments = load_existing(outdir)
    if not moments:
        return False
    pngs = render_burger_boards(moments, title, scene, outdir)
    if not pngs:
        print(f"    (chromium render failed for scene {scene} — falling back to plain grid)")
        paths = [fr["_path"] for m in moments for fr in m["frames"] if fr.get("_path")]
        png = compose_grid(paths, cols=4)
        pngs = [png] if png else []
    if not pngs:
        return False
    srow = await fetch_one("SELECT id FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene=$3",
                           vid, tenant, scene)
    if not srow:
        return False
    urls = []
    for bi, png in enumerate(pngs[:5], start=1):
        urls.append(await upload_bytes(png, f"{vid}/storyboard/S{scene}-B{bi}.png", "image/png", tenant))
    slots = (urls + [None] * 5)[:5]
    await execute(
        "UPDATE scripts SET storyboard_1_url=$1, storyboard_2_url=$2, storyboard_3_url=$3, "
        "storyboard_4_url=$4, storyboard_5_url=$5, updated_at=now() WHERE id=$6",
        *slots, srow["id"])
    return True


def _storyboard_sheet_system(style: str | None = None) -> str:
    """Storyboard-sheet writer instructions, rendered in the creator's chosen style. Defaults to
    photoreal cinematic only when no style was picked (was hardcoded 'Photorealistic')."""
    style_line = style.strip() if (style and style.strip()) else "Photorealistic, cinematic film still"
    return (
        "You are an expert Hollywood storyboard artist and AI prompt engineer. Produce ONE continuous "
        "image-generation prompt for GPT Image 2 that renders a SINGLE professional storyboard SHEET for "
        "the scene below — numbered panels laid out in an EVEN SQUARE GRID (4 panels as 2x2, or 6-9 panels "
        "as 3x3) so that EACH PANEL IS A WIDE 16:9 WIDESCREEN CINEMATIC FRAME matching the film's format; "
        "panels must be widescreen, NEVER square or tall. Each panel is a distinct cinematic shot of the "
        "scene's story IN ORDER, with a small caption label under each panel (shot type + one short line of "
        "action). Mix shot types naturally (wide / medium / close-up / over-the-shoulder / insert). "
        "Render EVERY panel in this EXACT art style, stated up front in the prompt and held identically "
        f"across all panels: {style_line}. Keep lighting and grade consistent across all panels. Use the "
        "EXACT characters from the cast — restate each character's locked appearance verbatim wherever they "
        "appear; NEVER invent new characters or change their look. Clean neutral storyboard presentation, "
        "numbered frames, small timecodes. Output ONLY the image prompt, no preamble.")


def _scene_text_hash(text: str) -> str:
    """Pins a saved coverage plan to the scene text it was planned from."""
    import hashlib
    return hashlib.sha1(" ".join((text or "").split()).encode()).hexdigest()


def _expected_coverage_frame_count(directive_text: str, max_moments: int, angles_max: int,
                                   max_frames) -> int:
    """C16b (S7-2): the frame count THIS SAME saved directive would produce if drawn
    again right now — plan_moments_deterministic() (parse -> budget -> floors -> variety,
    C7 fix (a)) is the EXACT pipeline run_coverage() runs when handed a saved
    directive_text (see run_coverage() below), given today's per-scene shape params
    (_coverage_shape, deterministic from scene_text + dialogue_audio). Used as the
    "how many frames SHOULD exist" side of the skip-if-done completeness check — never
    a guess, the same planner math the paid draw itself uses. Before C7, this only ran
    parse+budget (no floors), which under-counted any scene whose floors add shots —
    a false-positive "already drawn" skip that would strand a scene that actually
    still needs more frames drawn."""
    moments = plan_moments_deterministic(directive_text or "", max_moments, angles_max,
                                         max_frames=max_frames)
    if not moments:
        return 0
    return sum(1 + len(m.get("angles") or []) for m in moments)


def _sheet_header(chunk_index: int, total_chunks: int, panel_count: int, style_line: str,
                   variant: str = "primary", has_cast_refs: bool = False) -> str:
    """The fixed instruction paragraph opening one storyboard sheet prompt —
    kept SEPARATE from _plan_sheet_prompts's panel-body construction so a
    failed sheet draw can retry with a DIFFERENT header on the SAME body (see
    the fallback-header retry in generate_storyboard_sheet_for_scene).

    D6-1 fixed TWO live law violations here, both found on a real proof run
    (2026-07-30):

    L29 (DECLARE ONE STYLE, ONCE) — the 'primary' variant used to open with
    "...for an animated scene", an UNCONDITIONAL second style claim
    completely independent of style_line (the ONE resolved style, from
    _resolve_style's precedence contract). Whenever style_line resolved to
    something else — e.g. the default "Photorealistic, cinematic film
    still" — the emitted prompt asserted "animated" and "Photorealistic"
    in the same sheet, and the model resolved the contradiction toward
    photorealism (BOARD-LAWS.md L29's own provenance, same failure shape).
    Fixed by deleting the standalone claim outright: style_line is already
    stated exactly once, later in this same header ("Every panel uses the
    same art style, {style_line}..."), and that is now the ONLY place a
    style word appears. See _assert_single_style_declaration for the gate
    that gave this a mechanical, not just prose, guarantee.

    L28 (NEVER ASSERT AN INPUT THAT IS NOT ATTACHED) — BOTH variants used
    to unconditionally claim "matching their appearance to the attached
    reference images" / "Match each character's appearance to the attached
    reference images throughout", regardless of whether any character
    actually has video_characters.reference_url set. cast_refs is [] on
    every unapproved-sheet call (coverage_to_app.py's cast_refs list), so
    this fired constantly and — per L28's provenance — LICENSES confident
    invention rather than merely failing to constrain it. has_cast_refs
    (the caller's honest bool(cast_refs)) now gates the clause: when refs
    are genuinely attached, the original wording holds; when they are not,
    the sentence instead points the drawer at the CHARACTER block (L6's
    locked identity tags, when present) as the thing to match instead of
    a claimed image. Never both, never neither silently — see
    _assert_no_unattached_claims for the gate.

    C25a-fix8 (2026-07-20): the old ALL-CAPS "Professional animation
    PRODUCTION STORYBOARD SHEET" header started 400ing on
    gpt-image-2-image-to-image ("Sorry, but the image we created may violate
    OpenAI's content policies" / "The current content could not be
    processed...", failCode 400, creditsConsumed 0.0) on real prod prompts
    (video cd5d2883-427e-4bfb-854d-8849d025d444). Pre-flight bisection against
    the REAL Kie/OpenAI filter (not a guess) proved the OLD header ALONE
    reproduced the 400 (taskId cdb23fdc2df9c230fb0acb481b5d5c4c), and this
    plain-sentence rewrite — modeled on the June-era sheet prompt's phrasing
    (scripts.storyboard_prompts, video f32ed182, pre-dates this all-caps
    "PRODUCTION STORYBOARD SHEET" structure and never tripped the filter) —
    reproducibly PASSES standalone at the same ref count (taskId
    bcc59eacc1b858543d101fe89b402fb7).

    Known gap, found by the SAME bisection: the SET+AXIS+SETUPS+panel-briefs
    BODY can independently trip the filter on some scenes regardless of
    header wording at all (an empty-header + full-body probe still 400'd,
    taskId 6fae54729526675a18d7d6855248f687) — a body-composition issue this
    header fix does not and structurally cannot reach. The 'fallback' variant
    below and the retry in generate_storyboard_sheet_for_scene exist for the
    header-driven failures; a body-driven failure will still 400 on both
    variants, and that is expected, not a bug in this fix.

    'fallback': a second, sparser phrasing tried ONCE if 'primary' still
    400s with the documented signature. Built on the same plain-sentence,
    minimal-caps principle as 'primary' but not independently pre-flight-
    tested to the same depth — best-effort (a 400 on this variant costs
    nothing to attempt, so it is safe to try even unproven)."""
    # L27 (INSTRUCTIONS ARE NOT CAPTIONS): both variants below state exactly
    # what the caption strip may contain (number + shot type) AND that
    # nothing else ever appears there — a panel brief's own text (an
    # arrangement note, a labelled directive) has no business in that strip
    # and must never end up there. Proven live: an arrangement fact written
    # as a labelled "WORD WORD: ..." heading inside a panel's own brief
    # printed itself verbatim onto that panel's caption strip.
    if variant == "fallback":
        ref_clause = (
            "Match each character's appearance to the attached reference images throughout. "
            if has_cast_refs else
            "Draw each character exactly as stated in the CHARACTER block above (when one is "
            "present), identically in every panel. "
        )
        return (
            f"Storyboard sheet {chunk_index} of {total_chunks}: {panel_count} panels in a "
            "3-column grid on a light grey page, each panel a wide 16:9 frame. Style: "
            f"{style_line}. {ref_clause}"
            "A small strip below each panel shows ONLY its number and "
            "shot type, and NOTHING else — no captions, dialogue, subtitles or lettering of "
            "any kind, ever, inside or under the panels, however a panel's own brief is worded."
        )
    ref_clause = (
        "Draw every character consistently across every panel, matching their appearance to "
        "the attached reference images. "
        if has_cast_refs else
        "Draw every character consistently across every panel, exactly as stated in the "
        "CHARACTER block above (when one is present) — never inventing or varying their look. "
    )
    return (
        f"This is storyboard sheet {chunk_index} of {total_chunks}: a "
        f"grid of {panel_count} panels arranged in 3 columns on a plain light grey page. Each "
        "panel is a wide 16:9 cinematic frame, never square or tall. Every panel uses the "
        f"same art style, {style_line}, with matching lighting and color grading throughout. "
        f"{ref_clause}"
        "A small plain strip below each panel shows ONLY its "
        "panel number and shot type — NOTHING else ever appears in that strip, no matter how "
        "a panel's own brief is worded below. The panel artwork carries no lettering, signs, "
        "speech bubbles, captions, dialogue or written words of any kind — keep every panel "
        "free of readable text except the small panel-number label."
    )


# C7 fix (a), layer 2 — legacy-sheet guard: both _sheet_header variants embed
# "N panels" once per board ("...a grid of {panel_count} panels..." / "...:
# {panel_count} panels in a 3-column grid..."), and generate_storyboard_sheet_for_scene
# persists every board's full header+body into scripts.storyboard_prompts (the
# SAME UPDATE that writes storyboard_1_url.._5_url — see its "STREAMING CONTRACT"
# comment). That makes storyboard_prompts the one piece of bookkeeping that
# survives a code change: it records the panel count the boards ACTUALLY drew
# with, at the time they were drawn, regardless of what today's planner would
# produce from the same directive_text.
_SHEET_PANEL_COUNT_RE = re.compile(r"\b(\d+)\s+panels\b", re.IGNORECASE)


def _stored_sheet_panel_total(storyboard_prompts: Optional[str]) -> Optional[int]:
    """Sum of every board's "N panels" count embedded in the persisted
    storyboard_prompts blob — the TRUE total panel count the approved sheets
    in board_urls were planned with. None when the column is empty (no prior
    gate ran) or nothing matches (unparseable/legacy shape) — callers must
    treat None as "unknown, can't compare" rather than a 0-panel mismatch."""
    text = storyboard_prompts or ""
    if not text.strip():
        return None
    counts = [int(m) for m in _SHEET_PANEL_COUNT_RE.findall(text)]
    return sum(counts) if counts else None


def _sheet_filter_reject(fail_info: Optional[dict]) -> bool:
    """True if fail_info matches a KNOWN zero-cost content-filter rejection
    class C25a-fix8 targets: ~0 credits consumed (Kie/OpenAI reject before
    real generation starts, so nothing is spent) plus a recognized failCode +
    failMsg pairing. Two classes are known so far, both from prod evidence,
    never from a guess:
      - failCode "400" with one of the failMsg strings from the 2026-07-20
        bisection on video cd5d2883 — "The current content could not be
        processed..." or "...may violate OpenAI's content policies."
      - failCode "422" with a "flagged as sensitive" / generic "sensitive"
        failMsg, e.g. "CONTENT_POLICY_BLOCKED: The input or output was
        flagged as sensitive...", creditsConsumed 0.0 (taskId
        9b5af734f2455c8cbf39422142396051, 2026-07-20 prod sweep) — Kie's other
        zero-cost moderation rejection, previously getting no fallback-header
        retry and no free re-rolls.
    Used to gate the ONE free fallback-header retry (and the free re-roll
    loop) so they fire only on this specific, deterministic, zero-cost
    rejection class — never on a real (credit-consuming) failure, where
    retrying would just burn money on the same doomed prompt. The 0-credit
    guard is mandatory and must never be loosened: it is the entire reason
    this gate is safe to retry for free."""
    if not fail_info:
        return False
    code = str(fail_info.get("failCode") or "").strip()
    if code not in ("400", "422"):
        return False
    credits = fail_info.get("creditsConsumed")
    if credits not in (0, 0.0, None):
        return False
    msg = (fail_info.get("failMsg") or "").lower()
    return (
        ("could not be processed" in msg)
        or ("content polic" in msg)
        or ("violat" in msg)
        or ("flagged as sensitive" in msg)
        or ("sensitive" in msg)
    )


def _sheet_transient_kie_error(fail_info: Optional[dict]) -> bool:
    """True for Kie's TRANSIENT infra-failure signature — failCode "500" with
    "internal error" in the failMsg and ~0 credits consumed (None counts as
    0, exactly as in _sheet_filter_reject). Live example: failCode "500",
    failMsg "Internal Error, Please try again later.", creditsConsumed 0.0,
    costTime 0 — taskId a6136814f87ff94972011a80dc1e2ce8, 2026-07-21 (Kie's
    Seedance-launch-day instability; 4 of the last 7 sheet-draw failures that
    day carried this exact signature).

    This is Kie's own server falling over, NOT content moderation — the
    prompt is fine and the identical call typically succeeds moments later.
    So it joins the free RE-ROLL ladder (with a short pause first, to give
    Kie's infra a beat) but NEVER the fallback-header retry: a 500 has
    nothing to do with prompt wording, so swapping headers for it would be
    noise. The ~0-credit guard is as mandatory here as in
    _sheet_filter_reject and must never be loosened — retrying is only free
    because Kie charged nothing for the failure."""
    if not fail_info:
        return False
    if str(fail_info.get("failCode") or "").strip() != "500":
        return False
    if fail_info.get("creditsConsumed") not in (0, 0.0, None):
        return False
    return "internal error" in (fail_info.get("failMsg") or "").lower()


def _sheet_ref_fetch_error(fail_info: Optional[dict]) -> bool:
    """True for Kie failing to DOWNLOAD one of our reference images — failCode
    "400" with "image fetch failed" in the failMsg and the same mandatory
    ~0-credit guard (None counts as 0). Live signature: failCode "400",
    failMsg "image fetch failed. Check access settings or use our File Upload
    API instead.", creditsConsumed 0, attempts 1 — video cd5d2883 scene 1
    beat 1, ~16:59Z 2026-07-21, surfaced by storyboard_errors as class
    "unknown" before this predicate existed.

    Discovered 2026-07-21 under parallel load: our media proxy (the thing
    serving those reference URLs) runs inside the SAME backend process that
    was rendering another channel's segments at the time, so Kie's fetch of a
    ref intermittently times out when the box is busy. Transient infra, free
    to retry — NOT moderation and NOT prompt-related, so it joins the free
    RE-ROLL ladder only (with the same 15s pause as the transient-500 class,
    to give the proxy a beat to breathe) and the fallback-header retry must
    NEVER fire for it: prompt wording is irrelevant to a fetch failure.
    Despite sharing failCode "400" with the moderation class, the message
    sets are disjoint — _sheet_filter_reject never claims this signature.
    The ~0-credit guard is as mandatory here as everywhere else in the
    ladder and must never be loosened."""
    if not fail_info:
        return False
    if str(fail_info.get("failCode") or "").strip() != "400":
        return False
    if fail_info.get("creditsConsumed") not in (0, 0.0, None):
        return False
    return "image fetch failed" in (fail_info.get("failMsg") or "").lower()


# Human labels for scripts.storyboard_errors[<beat>]["class"] (migration 113)
# — reused by the scene-summary _p() line below AND documented in the
# migration header, so the wording a creator sees never drifts from what the
# column actually stores. The frontend chip (ScenesWorkspaceTab.tsx) keeps
# its OWN capitalized copies for the badge UI — that's a presentation choice
# for a different surface, not a second source of truth for the class enum
# itself (still exactly these 5 strings).
_SHEET_FAIL_LABELS = {
    "moderation": "blocked by OpenAI moderation",
    "sensitive": "flagged as sensitive",
    "kie_transient": "Kie server error (transient)",
    "ref_fetch": "Reference image fetch failed (transient)",
    "unknown": "failed",
}


def _sheet_fail_class(fail_info: Optional[dict]) -> str:
    """Classify a board's LAST failure for scripts.storyboard_errors, reusing
    the SAME two predicates the retry/re-roll ladder above already gates on
    (never a second, divergent read of fail_info) so the persisted class can
    never disagree with what the ladder actually did with this failure:
      - _sheet_filter_reject (OpenAI's zero-cost content filter) — split by
        the failCode it already inspects: "400" is generic moderation,
        "422" is Kie's distinct "flagged as sensitive" signature (see that
        function's docstring for both live signatures).
      - _sheet_transient_kie_error (Kie's own infra falling over — 500
        "Internal Error") — nothing to do with prompt content.
      - _sheet_ref_fetch_error (Kie couldn't download a reference image —
        400 "image fetch failed", our media proxy busy under parallel load,
        2026-07-21) — also transient infra, also nothing to do with content.
      - Anything else — a real, credit-consuming failure, or no fail_info at
        all (every attempt died before Kie ever reported a code) — is
        "unknown" rather than guessed at."""
    if _sheet_filter_reject(fail_info):
        code = str((fail_info or {}).get("failCode") or "").strip()
        return "sensitive" if code == "422" else "moderation"
    if _sheet_transient_kie_error(fail_info):
        return "kie_transient"
    if _sheet_ref_fetch_error(fail_info):
        return "ref_fetch"
    return "unknown"


def _sheet_fail_entry(fail_info: Optional[dict], attempts: int) -> dict:
    """Build ONE scripts.storyboard_errors[<beat>] entry (shape documented in
    migration 113's header) for a board that exhausted the full retry/re-roll
    ladder without landing. `attempts` is the count of real
    generate_scene_image_for_model calls made for this board — primary +
    the fallback-header retry (if it fired) + re-rolls — NOT a credit or Kie
    task count."""
    return {
        "code": str((fail_info or {}).get("failCode") or "").strip() or None,
        "class": _sheet_fail_class(fail_info),
        "msg": (str((fail_info or {}).get("failMsg") or "").strip()[:200]) or None,
        "attempts": attempts,
        "at": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# Filter-safety: single-naming pass for builder-authored sheet-prompt text
# =============================================================================
# C25a-fix9b (2026-07-20, Ryan's ruling: "fix the damn prompting structure,
# stop putting bandaids on everything" — tasks/decisions.md 2026-07-20 "NO
# nano-banana fallback"): OpenAI's content filter scores ACCUMULATED risky-
# prop density across the whole sheet prompt, not any single mention. Live
# bisection on video cd5d2883 proved it: sheet 1 passed naming the chef's
# knife ONCE (in FIXED SET); sheet 2 400'd on both fix8 header variants
# because the SAME prop got renamed again in CAMERA KIT's insert setup
# ("cutting board, knife") and again in nearly every panel brief ("knife",
# "chopping motion", "cutting board") — our own boilerplate repetition, not
# the creator's spoken lines, is what tipped the density over the filter's
# line.
#
# THE BOUNDARY (do not blur this — it is the whole point of the fix):
#   - FIXED SET (set_line / set_block): originally the ONE place a risky prop
#     was left named plainly (the "single canonical naming slot"), reasoned
#     for the PICTURES path's philosophy — name the real prop once, draw it
#     once. UPDATED 2026-07-21: for SHEET PREVIEWS ONLY (this file's
#     _plan_sheet_prompts — a cheap, throwaway preview that never feeds final
#     art) that exemption is gone. Staging a risky prop in FIXED SET means the
#     drawer paints it into EVERY panel that shows the location, not once —
#     proven live the same night: a staged kitchen knife in FIXED SET got
#     drawn into 30+ panels and the output-stage filter ground the whole scene
#     down (15 "knife" mentions across the plan). set_line (and the sheet's
#     LOCKED LOCATION env description, generate_storyboard_sheet_for_scene's
#     env_block) now run through this pass like everything else below. The
#     PICTURES path (run_coverage, storyboard/coverage.py) is UNTOUCHED — the
#     real set keeps its true, single-named props; only the sheet preview's
#     copy of that text is neutralized.
#   - CAPTION text (the verbatim spoken script) never reaches this pass — and
#     as of C25a-fix14 (Ryan, 2026-07-20) it is no longer rendered into the
#     sheet image at ALL. fix9b removed 100% of the BUILDER's density, but a
#     sheet could still 400 on caption density alone (protected dialogue we
#     can't reword — fix9b's open gap). Since the sheet is a preview and the
#     spoken lines live in the saved coverage_directive plan (they drive the
#     real pictures + voice), _plan_sheet_prompts below now emits panels with
#     NO dialogue text — only the number, shot type, and neutralized brief.
#   - AXIS/SCREEN-DIRECTION lines, panel numbering/order, SETUP letters, and
#     character names/wardrobe are never touched (they don't carry prop
#     nouns and are excluded from every call site of this pass).
#   - Every OTHER builder-authored segment — CAMERA KIT (setups_line) and
#     every panel brief's shot description (master + angles) — IS run
#     through this pass, so a risky prop is referred to neutrally there.
#
# Add new risky terms to _RISKY_PROP_PATTERNS below, nowhere else. Longer,
# more specific phrases must sort before their substrings (checked in
# list order — a compiled regex list, not a dict) or the shorter pattern
# would eat the longer one first (e.g. "knife" matching inside "chef's
# knife" before the multi-word pattern gets a chance).
#
# NOUN-PHRASE replacements ("the utensils", "the prep board") swallow an
# optional leading article ("the "/"a "/"an ") in the PATTERN itself so the
# replacement's own "the" is never doubled ("the knife" -> "the utensils",
# never "the the utensils"). Verb-form replacements (prep/prepping/prepped/
# preps) carry no article and need no such prefix.
_ART = r"(?:the\s+|a\s+|an\s+)?"
_RISKY_PROP_PATTERNS: list[tuple] = [
    (re.compile(rf"\b{_ART}chef'?s?\s+knives\b", re.IGNORECASE), "the utensils"),
    (re.compile(rf"\b{_ART}chef'?s?\s+knife\b", re.IGNORECASE), "the utensils"),
    (re.compile(rf"\b{_ART}kitchen\s+knives\b", re.IGNORECASE), "the utensils"),
    (re.compile(rf"\b{_ART}kitchen\s+knife\b", re.IGNORECASE), "the utensils"),
    (re.compile(rf"\b{_ART}cutting\s+boards?\b", re.IGNORECASE), "the prep board"),
    (re.compile(rf"\b{_ART}chopping\s+boards?\b", re.IGNORECASE), "the prep board"),
    # Descriptions commonly wrap the noun in an adjective ("a slow chopping
    # motion" — seen verbatim in prod, video cd5d2883 scene 2); swallow up to
    # one adjective between the article and the noun so the replacement's own
    # "a" is never doubled ("a slow chopping motion" -> "a slicing-prep
    # gesture", not "a slow a slicing-prep gesture").
    (re.compile(rf"\b{_ART}(?:slow\s+|quick\s+|brief\s+|gentle\s+|small\s+)?"
                r"cutting\s+motions?\b", re.IGNORECASE), "a slicing-prep gesture"),
    (re.compile(rf"\b{_ART}(?:slow\s+|quick\s+|brief\s+|gentle\s+|small\s+)?"
                r"chopping\s+motions?\b", re.IGNORECASE), "a slicing-prep gesture"),
    (re.compile(rf"\b{_ART}knives\b", re.IGNORECASE), "the utensils"),
    (re.compile(rf"\b{_ART}knife\b", re.IGNORECASE), "the utensils"),
    (re.compile(rf"\b{_ART}blades?\b", re.IGNORECASE), "the utensils"),
    (re.compile(r"\bchopped\b", re.IGNORECASE), "prepped"),
    (re.compile(r"\bchopping\b", re.IGNORECASE), "prepping"),
    (re.compile(r"\bchops\b", re.IGNORECASE), "preps"),
    (re.compile(r"\bchop\b", re.IGNORECASE), "prep"),
]


def _neutralize_risky_props(text: Optional[str]) -> Optional[str]:
    """Single-naming rule enforcement (C25a-fix9b): swaps risky/sharp-prop
    language for neutral culinary phrasing in ONE builder-authored segment.
    Callers must NEVER hand this CAPTION text (the verbatim spoken script) —
    see the boundary docstring above _RISKY_PROP_PATTERNS. FIXED SET text
    (set_line) and the sheet's LOCKED LOCATION env description ARE now
    passed through this function (2026-07-21, sheet-preview callers only —
    see the boundary docstring's FIXED SET bullet); the PICTURES path's own
    set/env text is a different call site (storyboard/coverage.py's
    run_coverage) and is never routed through here. None/empty input passes
    through unchanged."""
    if not text:
        return text
    out = text
    for pattern, replacement in _RISKY_PROP_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


# =============================================================================
# Filter-safety: gesture neutralization (BUILD 2's sweep-2 escalation only)
# =============================================================================
# 2026-07-21 (same night as the knife-scene sheet-preview fix above, proven
# twice live on PocoAPoco 'El Mercado'): the SAME accumulated-density
# mechanism fix9b fixed for risky PROPS also fires on risky GESTURES — a
# haggling market scene kept staging pointed fingers, thumbs up/down,
# handshakes and fist pumps across nearly every panel brief, and the manual
# playbook that fixed it reworded that gesture language the same way fix9b
# reworded props.
#
# Kept as its OWN list, never merged into _RISKY_PROP_PATTERNS, so a caller
# can choose props-only (the unconditional sheet-build pass above) or
# props+gestures together (the sweep-2 escalation ladder in
# generate_storyboard_sheet_for_scene, via _escalate_panel_briefs) —
# independently and on purpose. Gesture neutralization is NEVER applied at
# build time: creative wording stays by default; this dictionary exists
# solely for that escalation, the last rung of the auto-sweeper.
#
# Same house rules as _RISKY_PROP_PATTERNS: longer/more-specific phrases
# before their substrings, and every noun-phrase pattern swallows its own
# optional leading article via _ART so the replacement is never doubled.
# Every replacement reuses ONE of the five neutral open-hand phrases proven
# on El Mercado — no new wording invented here.
_RISKY_GESTURE_PATTERNS: list[tuple] = [
    # Pointed finger(s) — "fingers pointed", "a pointed finger", "pointing a finger"
    (re.compile(rf"\bpointing\s+(?:the\s+|a\s+|an\s+|his\s+|her\s+|their\s+)?finger[s]?\b",
                re.IGNORECASE), "an open palm gestured"),
    (re.compile(rf"\b{_ART}finger[s]?\s+point(?:ed|ing)\b", re.IGNORECASE), "an open palm gestured"),
    (re.compile(rf"\b{_ART}pointed\s+finger[s]?\b", re.IGNORECASE), "an open palm gestured"),
    # Raised finger(s)
    (re.compile(rf"\b{_ART}finger[s]?\s+raised\b", re.IGNORECASE),
     "hand raised in a friendly open wave"),
    (re.compile(rf"\b{_ART}raised\s+finger[s]?\b", re.IGNORECASE),
     "hand raised in a friendly open wave"),
    # Tapping finger(s)
    (re.compile(rf"\b{_ART}finger[s]?\s+tapping\b", re.IGNORECASE), "a confident open-hand gesture"),
    (re.compile(rf"\b{_ART}tapping\s+finger[s]?\b", re.IGNORECASE), "a confident open-hand gesture"),
    # Thumbs up / down
    (re.compile(rf"\b{_ART}thumbs?\s+up\b", re.IGNORECASE), "a confident open-hand gesture"),
    (re.compile(rf"\b{_ART}thumbs?\s+down\b", re.IGNORECASE), "an open palm gestured"),
    # Pinched fingers
    (re.compile(rf"\b{_ART}pinched\s+finger[s]?\b", re.IGNORECASE), "an open palm gestured"),
    (re.compile(rf"\b{_ART}finger[s]?\s+pinched\b", re.IGNORECASE), "an open palm gestured"),
    # Handshake
    (re.compile(rf"\b{_ART}handshake[s]?\b", re.IGNORECASE), "extending an open hand warmly"),
    (re.compile(r"\bshaking\s+hands\b", re.IGNORECASE), "extending an open hand warmly"),
    # Fist(s): pump / raised / clenched
    (re.compile(rf"\b{_ART}fist[s]?\s+pump(?:ed|ing)?\b", re.IGNORECASE),
     "both hands raised in easy celebration"),
    (re.compile(rf"\b{_ART}raised\s+fist[s]?\b", re.IGNORECASE),
     "hand raised in a friendly open wave"),
    (re.compile(rf"\b{_ART}fist[s]?\s+raised\b", re.IGNORECASE),
     "hand raised in a friendly open wave"),
    (re.compile(rf"\b{_ART}clenched\s+fist[s]?\b", re.IGNORECASE), "an open palm gestured"),
    (re.compile(rf"\b{_ART}fist[s]?\s+clenched\b", re.IGNORECASE), "an open palm gestured"),
]


def _neutralize_risky_gestures(text: Optional[str]) -> Optional[str]:
    """Same shape as _neutralize_risky_props, over _RISKY_GESTURE_PATTERNS.
    Only ever called from the sweep-2 escalation path (_escalate_panel_briefs)
    — never at build time. None/empty input passes through unchanged."""
    if not text:
        return text
    out = text
    for pattern, replacement in _RISKY_GESTURE_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


# A raw coverage_directive's `LINE: <Speaker> | "<exact words>"` row (the
# verbatim spoken script, storyboard.coverage's own _LINE_RE shape) and its
# `[AXIS | ...]` screen-direction contract — the two things sweep-2
# escalation must NEVER reword, matched line-by-line on the raw stored text.
_DIRECTIVE_LINE_ROW_RE = re.compile(r"^\s*\*{0,2}\s*LINE\s*:", re.IGNORECASE)
_DIRECTIVE_AXIS_ROW_RE = re.compile(r"^\s*\[AXIS\b", re.IGNORECASE)
# C3 item 3: a MASTER/ANGLE row carrying storyboard.coverage's "(REACTION)"
# or "(INSERT)" inline tag (rule 5f) is ALSO protected whole-line, same as
# the two above. Reuses coverage.py's own _INLINE_TAG_RE (imported above) as
# the single source of truth for what that tag looks like — if that regex
# ever changes shape, this protection changes with it instead of drifting.
# Without this, a sweep-2 escalation (this is the ONLY caller of
# _neutralize_risky_props/_neutralize_risky_gestures that rewrites text —
# never the build-time pass) could rewrite the shot's prose around the tag;
# more importantly, a FUTURE pattern added to either dictionary that isn't
# careful about word boundaries could eat the tag's own text, silently
# dropping the reaction/insert floor bookkeeping (coverage.py's
# enforce_reaction_insert_floors / _shot_tag) the next time this directive
# is re-parsed. Not anchored to line-start (unlike the two above) — the tag
# sits after "- MASTER [CU]:" or "- ANGLE [CU]:", never at column 0.
_DIRECTIVE_REACTION_INSERT_ROW_RE = _INLINE_TAG_RE


def _escalate_panel_briefs(directive_text: str) -> tuple[str, list[tuple[str, str]]]:
    """BUILD 2's sweep-2 escalation (2026-07-21): apply BOTH
    _RISKY_PROP_PATTERNS and _RISKY_GESTURE_PATTERNS to a scene's saved
    coverage_directive — the [SET|]/[SETUPS|] lines and every MASTER/ANGLE
    panel brief — for a scene that keeps landing on OpenAI's moderation
    filter after a plain re-roll already had a fair shot (sweep 1). Mirrors
    the manual playbook proven twice tonight on live scenes.

    Applied line-by-line so the protected rows are never touched: a
    `LINE: <Speaker> | "..."` row (the verbatim spoken script — protected
    dialogue this fix must never reword, same law as the build-time pass),
    the `[AXIS | ...]` screen-direction contract (never carries prop/
    gesture nouns; touching it is an explicit product rule), and (C3 item 3)
    a MASTER/ANGLE row carrying a "(REACTION)"/"(INSERT)" inline tag (rule
    5f) — those tags are structural bookkeeping for coverage.py's reaction/
    insert floors, not prose, and must survive a re-parse byte-for-byte.
    Every other line — [SET|], [SETUPS|], MOMENT headers, untagged MASTER/
    ANGLE briefs — passes through both dictionaries.

    Returns (rewritten_directive_text, reworded) where `reworded` is every
    (old, new) phrase actually swapped, in order — the sweep log prints
    each pair. Empty `reworded` means neither dictionary matched anything in
    this directive; callers must treat that as a no-op (nothing to persist
    or rebuild from)."""
    reworded: list[tuple[str, str]] = []
    out_lines = []
    for line in (directive_text or "").splitlines():
        if (_DIRECTIVE_LINE_ROW_RE.match(line) or _DIRECTIVE_AXIS_ROW_RE.match(line)
                or _DIRECTIVE_REACTION_INSERT_ROW_RE.search(line)):
            out_lines.append(line)
            continue
        new_line = line
        for pattern, replacement in _RISKY_PROP_PATTERNS + _RISKY_GESTURE_PATTERNS:
            for m in pattern.finditer(new_line):
                reworded.append((m.group(0), replacement))
            new_line = pattern.sub(replacement, new_line)
        out_lines.append(new_line)
    return "\n".join(out_lines), reworded


def _character_identity_line(bible: Optional[dict], scene_number) -> str:
    """L6 (IDENTITY ONCE): a short "Name (locked words)" tag per character
    present in THIS scene, joined into one line — the sheet-preview's own
    CHARACTER block (_plan_sheet_prompts' character_line). Filters bible['
    characters'] to whoever's scenes_present includes this scene number (an
    empty/missing scenes_present is treated as "present" rather than hidden
    — the conservative default scene_aware_bible's callers already rely on
    elsewhere). Truncates each costume/description to a short tag (rule 2's
    own "2-4 bible words" convention) so this never grows into the long
    wardrobe-paragraph shape rule 2 explicitly forbids. Returns "" when
    there's no bible or no characters resolve for this scene — the caller
    treats that as "omit the CHARACTER block", matching today's behavior."""
    if not bible or not bible.get("characters"):
        return ""

    def _short(s, n=60):
        s = (s or "").strip()
        if len(s) <= n:
            return s
        return s[:n].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"

    tags = []
    for ch in bible["characters"]:
        present = ch.get("scenes_present")
        if present and scene_number not in present:
            continue
        name = (ch.get("id") or "").strip()
        if not name:
            continue
        costume = _short(ch.get("costume") or ch.get("description") or "")
        tags.append(f"{name} ({costume})" if costume else name)
    return "; ".join(tags)


# =============================================================================
# D6-1 hard gates (BOARD-LAWS L3, L28, L29) — the "GATE" leg of the contract
# triangle for these three laws. Unlike the check_* functions in storyboard.
# coverage.py (warning-only, print a note and continue), these RAISE: a
# prompt that fails one of them must never reach the paid image-generation
# call, so the gate has to actually stop the draw, not just log it. Called
# from _plan_sheet_prompts (L29/L28-cast/L3) and from _draw_board's entry
# point in generate_storyboard_sheet_for_scene (L28-location, once env_block
# is known) — see each call site's comment for why it lives there.
# =============================================================================

class SheetPromptContractViolation(Exception):
    """Raised when an assembled board-sheet prompt violates a law that has a
    deterministic, mechanical check (L3/L28/L29). Callers catch this PER
    SCENE (generate_storyboard_sheet_for_scene) and fail that scene's boards
    loudly via the progress callback — never silently, and never by sending
    the bad prompt to a paid model anyway."""


# L29: style-indicating words that must appear ONLY inside the one resolved
# style_line, nowhere else in the assembled prompt. Deliberately broader
# than a single hardcoded phrase (the fix for the specific "for an animated
# scene" bug already removes ITS text) — this keeps catching ANY future
# second, independently-worded style claim that names a rendering medium,
# which is exactly the general shape L29's provenance describes ("an
# ANIMATED scene" + "Photorealistic... film still", two different words,
# same violation).
_STYLE_KEYWORDS = (
    "animated", "animation", "photoreal", "live-action", "live action",
    "cartoon", "anime", "stylized", "claymation", "3d-cg", "3d cg", "cgi",
    "watercolor", "pencil sketch", "oil painting",
)


def _assert_single_style_declaration(full_text: str, style_line: str) -> None:
    """L29 gate. For every style keyword, the number of times it appears in
    the WHOLE assembled prompt must equal the number of times it appears
    inside style_line alone — any surplus means a second, independently
    worded style claim slipped in outside the one sanctioned insertion
    point. Reproduces the live bug exactly: header text "for an animated
    scene" (style_line not containing "animated") scores total=1,
    within_style=0 -> 1 > 0 -> raises. A style_line that itself legitimately
    says e.g. "animated 2D style" scores total==within_style -> passes,
    because it is still stated exactly once, in the right place."""
    style_low = (style_line or "").strip().lower()
    full_low = (full_text or "").lower()
    for kw in _STYLE_KEYWORDS:
        total = full_low.count(kw)
        within_style = style_low.count(kw)
        if total > within_style:
            raise SheetPromptContractViolation(
                f"L29 (DECLARE ONE STYLE, ONCE): style keyword {kw!r} appears {total} "
                f"time(s) in the assembled prompt but only {within_style} time(s) inside "
                f"the single resolved style declaration ({style_line!r}) — a second, "
                "independent style claim is present.")


# L28: phrases that claim a specific attached input. Each maps to the name
# of the boolean the caller must pass proving that input is genuinely in
# the call. Add a new entry here whenever a new "attached X" claim is
# written anywhere in the sheet prompt — this is the audit point BOARD-
# LAWS L28 asks for ("the same applies to any claimed input").
_ATTACHED_CLAIM_PATTERNS = (
    (re.compile(r"attached reference imag", re.IGNORECASE), "cast_refs"),
    (re.compile(r"FINAL reference image", re.IGNORECASE), "env_ref"),
    (re.compile(r"LAST attached reference image", re.IGNORECASE), "env_ref"),
)


def _assert_no_unattached_claims(full_text: str, **attached: bool) -> None:
    """L28 gate. Raises if the text claims an input named in
    _ATTACHED_CLAIM_PATTERNS whose corresponding `attached[...]` kwarg is
    falsy or was never passed (missing == not attached, the safe default —
    a caller that forgets to prove an input is attached must not get a free
    pass). Reproduces the live bug: has_cast_refs=False text still
    containing "matching their appearance to the attached reference
    images" raises; the fixed conditional text (which switches to the
    CHARACTER-block sentence when refs are absent) does not."""
    for pattern, key in _ATTACHED_CLAIM_PATTERNS:
        if pattern.search(full_text or "") and not attached.get(key, False):
            raise SheetPromptContractViolation(
                f"L28 (NEVER ASSERT AN INPUT THAT IS NOT ATTACHED): prompt claims an "
                f"attached {key.replace('_', ' ')} but none is attached to this call.")


def _plan_sheet_prompts(moments: list, style_dir: str, panels_per_sheet: int = 9,
                        set_line: str = "", axis_line: str = "",
                        setups_line: str = "", header_variant: str = "primary",
                        character_line: str = "", location_sets: Optional[dict] = None,
                        material_line: str = "", motion_scene: bool = False,
                        incoming: Optional[dict] = None, outgoing: Optional[dict] = None,
                        has_cast_refs: bool = False,
                        canonical_envs: Optional[list] = None) -> list[str]:
    """Deterministic storyboard-sheet image prompts FROM the coverage plan —
    one numbered panel per planned SHOT (masters and angles alike), chunked
    into BALANCED sheets of ≤panels_per_sheet via sheet_chunk_sizes (pass
    panels_per_sheet_for(directive) so legacy 12-panel plans redraw true).
    The preview shows exactly what the pictures step will draw: same shots,
    same order, same spoken lines. No LLM in between to drift.

    Structure follows the researched winning shape (2026-07-07): a short
    invariant block (identity = the cast reference, the [SET|] line, the
    [AXIS|] screen-direction contract), then ONE compact line per panel
    already resolved into screen space by the planner, dialogue in the
    caption bars, and the hard constraints in a final slot. Long per-panel
    wardrobe prose is the documented failure mode — it fights the reference
    image — so briefs stay tight and captions carry the spoken line.

    BOARD LAWS additions (storyengine/BOARD-LAWS.md), all optional/additive —
    every new parameter defaults to empty/False/None, so a caller that never
    passes them (none did before this chunk) gets byte-identical output:
      character_line (L6): a short "Name (2-4 locked words)" identity line
        rendered ONCE as a CHARACTER block, mirroring the acceptance target's
        shape — this sheet composer never had one before; identity used to
        live ONLY in the attached reference image plus the directive-stage
        LLM's own rule 2, never restated in the actual draw prompt's text.
      location_sets (L3): {location_name: set_text} from
        storyboard.coverage.parse_location_sets. When non-empty, REPLACES the
        single FIXED SET block with one per-location block (each carrying an
        explicit cross-contamination prohibition) and tags every panel whose
        moment names a location with that location, e.g. "M5 · CORRIDOR WS".
        Falls back to the single set_block for any moment with no location
        tag (a planner slip) or when moments carry no location data at all.
      material_line (L20): stamped as its own MATERIAL MAP block when present.
      motion_scene (L4): selects motion-capable CAMERA KIT phrasing instead
        of the unconditional (and, for a scene with a moving/location-
        changing beat, WRONG) "the actors are PLANTED... and never move" —
        see storyboard.coverage.scene_has_motion, the single shared detector
        this and run_coverage's STAGING LOCK repair tail both call.
      incoming/outgoing (L23-L26): optional scene-boundary blocks in the
        exact shape storyboard.coverage.format_boundary_blocks renders —
        incoming is placed on the FIRST sheet only (it constrains this
        scene's first panel), outgoing on the LAST sheet only.
      has_cast_refs (L28, D6-1): the caller's honest bool(cast_refs) — the
        ONLY thing that decides whether _sheet_header's reference-image
        clause is written. Defaults to False (never claim unless proven),
        which is the safe direction for L28.
      canonical_envs (L3, D6-1b): the video's approved video_environments
        rows (same shape _approved_envs returns — needs a "name" key at
        minimum). Used ONLY by the L3 location gate below to upgrade a
        prose-vs-prose mismatch into a prose-vs-canonical match before
        deciding whether to raise. Defaults to None/[] — a caller that
        never passes it gets the D6-1 behavior unchanged (LOCSET-only
        matching), which is still correct for legacy callers that have no
        approved environments to check against.

    D6-1b (independent-verifier fix): the L3 gate no longer HARD-RAISES on
    a bare LOCSET-name mismatch, because both sides of that comparison
    (a moment's `location` and a [LOCSET|name|...] key) are free prose
    written independently by the SAME planner LLM — "Diner Interior" vs
    "The Diner" is a paraphrase, not a real scoping gap, and a hard raise
    on paraphrase would block real boards. The gate now checks THREE tiers
    for each location a panel references, in order: (1) an exact-enough
    LOCSET key match (unchanged, the common case); (2) a match against a
    CANONICAL video_environments.name in canonical_envs (this chunk's
    whole point — turn a prose-vs-prose comparison into a prose-vs-
    canonical one, matched with the same _norm_env_text normalizer
    _match_scene_env already uses); only when NEITHER matches is (3) a
    genuine gap with nothing canonical to fall back on — and even then
    this is a LOUD WARNING (printed), never a hard raise, because a gate is
    only allowed to be hard when the thing it compares against is
    canonical, and prose-vs-prose is not that. L28/L29 stay hard raises
    below — they compare against a boolean the caller PROVED true/false,
    not against another free-text guess."""
    if location_sets:
        _loc_keys_norm = {_norm_env_text(k) for k in location_sets}
        _env_names_norm = {_norm_env_text(e.get("name") or "") for e in (canonical_envs or [])
                           if e.get("name")}
        _referenced = {m.get("location") for m in moments if m.get("location")}
        _unmatched_locset = sorted(loc for loc in _referenced if _norm_env_text(loc) not in _loc_keys_norm)
        _no_canonical_either = sorted(loc for loc in _unmatched_locset
                                      if _norm_env_text(loc) not in _env_names_norm)
        if _no_canonical_either:
            print(f"  ⚠️ L3 (LOCATION SCOPING): panel(s) reference location(s) "
                  f"{_no_canonical_either} with no matching LOCSET entry among "
                  f"{sorted(location_sets)} AND no matching canonical video_environments "
                  "record — nothing canonical to verify against, so this is a warning, not "
                  "a block. Consider approving an environment for this location.", flush=True)
    def _trunc(s, n):
        # Word-boundary cut with an ellipsis. A hard slice amputates mid-word
        # ("Why didn'", "cream stove at ba") and the sheet drawer renders that
        # fragment verbatim into the caption strip.
        s = (s or "").strip()
        if len(s) <= n:
            return s
        return s[:n].rsplit(" ", 1)[0].rstrip(" ,;:.") + " …"

    location_sets = location_sets or {}
    panels: list[str] = []
    for m in moments:
        n = m.get("moment_number")
        loc = m.get("location") if location_sets else None
        loc_tag = f" · {loc.upper()}" if loc else ""
        # C25a-fix14 (Ryan, 2026-07-20): the verbatim spoken line is NO LONGER
        # baked into the sheet image. fix9b left one open gap — a sheet could
        # still 400 on OpenAI's content filter from CAPTION density alone (the
        # Spanish lesson's dialogue vocabulary — "cuchillo"/"cortar"/haggling
        # phrases — repeated across most panels), and captions are protected
        # spoken script we can't reword. The sheet is a PREVIEW only: the lines
        # live in the saved coverage_directive plan and drive the real pictures
        # and voice, never this throwaway image. So panels now carry ONLY their
        # number + shot type + the (neutralized) visual brief — no dialogue text
        # the model must spell, so nothing dialogue-side can push the prompt
        # over the filter's density line.
        master = m.get("master") or {}
        # Panel-brief visual description IS builder-authored text (C25a-fix9b):
        # neutralize risky-prop density before truncating.
        master_desc = _neutralize_risky_props(master.get("description"))
        panels.append(f"[{len(panels) + 1}] M{n}{loc_tag} {master.get('shot_type', 'MS')} — "
                      f"{_trunc(master_desc, 300)}")
        for a in (m.get("angles") or []):
            angle_desc = _neutralize_risky_props(a.get("description"))
            panels.append(f"[{len(panels) + 1}] M{n}{loc_tag} ANGLE {a.get('shot_type', 'CU')} — "
                          f"{_trunc(angle_desc, 300)}")
    style_line = (style_dir or "").strip() or "Photorealistic, cinematic film still"
    # CHARACTER block (L6): stated once, mirrors the acceptance target's
    # "CHARACTER — stated once, drawn identically in every panel: ..." line.
    # character_line is caller-supplied plain prose (a short locked identity
    # tag per cast member) — never risky-prop-neutralized (it's wardrobe/
    # appearance text, not a prop/gesture list, and running it through that
    # pass would be a no-op at best and a confusing substitution at worst).
    character_block = (f"\nCHARACTER — stated once, drawn identically in every panel: "
                       f"{character_line.strip()}\n"
                       if (character_line or "").strip() else "")
    # L3 (LOCATION SCOPING): a multi-location scene gets one FIXED SET block
    # PER LOCATION instead of the single scene-wide block below — each with
    # an explicit cross-contamination prohibition, so this sheet-preview
    # prompt stops reproducing the exact bug L3's provenance describes (one
    # "identical in every shot of this scene" lock drawing a corridor panel
    # with bedroom furniture). Falls back to the single-location set_block
    # when location_sets is empty (every scene before this law, and every
    # single-location scene going forward) — byte-identical in that case.
    if location_sets:
        loc_lines = []
        for name, text in location_sets.items():
            others = [n for n in location_sets if n != name]
            # Guarantee the cross-contamination prohibition even when the
            # planner forgot it (defense in depth, same reasoning as every
            # other REPAIR-leg stamp in this file) — but SKIP auto-appending
            # a SECOND one when the planner's own LOCSET text already reads
            # as a prohibition sentence, so a compliant planner's output
            # isn't followed by a near-duplicate sentence saying the same
            # thing twice.
            already_stated = bool(re.search(r"\bonly\b.*\bpanels?\b", text, re.IGNORECASE))
            prohibition = (f" These props appear ONLY in {name} panels; never in "
                           f"{' or '.join(others)} panels."
                           if others and not already_stated else "")
            loc_lines.append(f"{name.upper()} SET — applies ONLY to panels marked "
                             f"{name.upper()}: {_neutralize_risky_props(text)}.{prohibition}")
        set_block = "\n" + "\n".join(loc_lines) + "\n"
    else:
        # SHEET PREVIEWS ONLY (2026-07-21, knife-scene evidence — see the
        # boundary block above _neutralize_risky_props): set_line now runs
        # through _neutralize_risky_props before it goes into FIXED SET. A risky
        # prop staged here gets drawn into EVERY panel that shows the location,
        # not named once — fix9b's original single-naming exemption for FIXED
        # SET was reasoned for the PICTURES path, not this throwaway preview.
        # The PICTURES path (run_coverage) builds its own set text separately
        # and is NOT touched by this change.
        set_block = (f"\nFIXED SET — identical in EVERY panel that shows the location: "
                     f"{_neutralize_risky_props(set_line)}\n"
                     if (set_line or "").strip() else "")
    # MATERIAL MAP block (L20).
    material_block = (f"\nMATERIAL MAP — fixed for this whole set: {material_line.strip()}\n"
                      if (material_line or "").strip() else "")
    # AXIS/SCREEN-DIRECTION lines never carry prop nouns and must never be
    # touched (explicit product rule) — axis_line is NEVER neutralized.
    axis_block = (f"\nSCREEN-DIRECTION LOCK — holds in EVERY panel of this sheet: {axis_line} "
                  "Each character stays on their own side of the frame looking their fixed "
                  "direction in every panel, even when they are only a soft foreground "
                  "shoulder.\n"
                  if (axis_line or "").strip() else "")
    # CAMERA KIT is builder-authored text that historically re-named the same
    # risky prop set_line already named once (C25a-fix9b root cause) —
    # neutralized here, every time.
    #
    # L4 (MOTION IS LEGAL) fix: this used to say "the actors are PLANTED on
    # the set and never move" UNCONDITIONALLY, on every scene regardless of
    # content — a direct contradiction of a motion/location-changing scene
    # (proven live: a static-tableau board convention applied to a scene
    # where a character wakes, crosses a room and runs down a corridor
    # silently dropped the exit). motion_scene (storyboard.coverage.
    # scene_has_motion) selects motion-capable phrasing instead; a purely
    # planted scene's text is unchanged from before this law.
    if (setups_line or "").strip() and motion_scene:
        setups_block = (f"\nCAMERA KIT — setups covering a planted moment hold the actors "
                        f"still; a setup covering a moving beat (an exit, a run, a location "
                        f"change) is MOTION-CAPABLE and describes the move directly (holds "
                        f"while the subject exits frame, travels alongside, moves toward the "
                        f"lens) rather than freezing it into planted staging. The scene is "
                        f"covered by these repeated setups: {_neutralize_risky_props(setups_line)} "
                        "Panels sharing a SETUP letter keep that same camera position, height "
                        "and distance; only the action, expression and the moment advance.\n")
    else:
        setups_block = (f"\nCAMERA KIT — the actors are PLANTED on the set and never move; the "
                        f"whole scene is covered by these repeated setups: "
                        f"{_neutralize_risky_props(setups_line)} Panels "
                        "whose brief carries the same SETUP letter are the SAME camera position "
                        "and the SAME frozen staging repeated EXACTLY — copy the framing, body "
                        "positions, distance and orientation from the first panel with that "
                        "letter; only faces, gestures and the caption change between them.\n"
                        if (setups_line or "").strip() else "")
    # L23-L26 (scene boundaries): rendered by storyboard.coverage's own
    # formatter so the wording is identical to what the directive-planning
    # LLM prompt uses — see that function's docstring for why this chunk
    # builds only the RENDERING half, not the film-level boundary pass
    # itself. Placed on the FIRST sheet (incoming) / LAST sheet (outgoing)
    # only, since those are the only sheets whose first/last panel the
    # boundary actually constrains.
    if incoming or outgoing:
        from storyboard.coverage import format_boundary_blocks
    prompts = []
    # BALANCED chunking (Ryan, 2026-07-21): sizes come from sheet_chunk_sizes
    # — the shared single source of truth with the board-anchor math in
    # storyboard/coverage.py — instead of a fixed stride, so the last board is
    # never a runt (15 panels draw 5+5+5, not 6+6+3) and chunking can never
    # disagree with picture anchoring on which sheet a panel lives on.
    # Global panel numbering (the [k] labels baked in above) is unchanged.
    chunks, _start = [], 0
    for _size in sheet_chunk_sizes(len(panels), panels_per_sheet):
        chunks.append(panels[_start:_start + _size])
        _start += _size
    for ci, chunk in enumerate(chunks, start=1):
        listed = "\n".join(chunk)
        this_boundary = ""
        if incoming and ci == 1:
            this_boundary += f"\n{format_boundary_blocks(incoming, None).strip()}\n"
        if outgoing and ci == len(chunks):
            this_boundary += f"\n{format_boundary_blocks(None, outgoing).strip()}\n"
        header_text = _sheet_header(ci, len(chunks), len(chunk), style_line, variant=header_variant,
                                    has_cast_refs=has_cast_refs)
        constraints_text = (
            "\nCONSTRAINTS: never swap which side of the frame a character occupies; never "
            "mirror or flip a panel; one action per panel; a panel may break the "
            "screen-direction lock only if its brief says NEUTRAL; never repeat an earlier "
            "panel of this sheet identically — escalate closer or wider instead; write every "
            "panel brief as ordinary prose, never as a labelled heading or a \"WORD: ...\" "
            "directive line — the caption strip below each panel shows ONLY its number and "
            "shot type, and nothing else ever appears there.")
        chunk_prompt = (
            header_text
            + f"{character_block}{set_block}{material_block}{axis_block}{setups_block}{this_boundary}"
            "Draw these panels IN ORDER:\n"
            + listed
            + constraints_text)
        # D6-1b hard gates (L29/L28-cast) — see this function's docstring.
        # Raise here, before the prompt is even returned to the caller, so a
        # violation can never reach the paid draw call downstream.
        #
        # L29 SCOPE FIX (D6-1b, independent-verifier finding): the style-
        # keyword count runs ONLY over text the composer itself writes and
        # fully controls — the header (style_line lives here), the
        # CHARACTER/SET/MATERIAL blocks, and the CONSTRAINTS tail.
        # Deliberately EXCLUDES axis_block, setups_block, this_boundary, and
        # `listed` (the panel master/angle bodies) — all free English
        # written by the planner LLM describing what a shot actually shows:
        # "her face is animated with delight" (ordinary usage), "the CGI
        # warning hologram flickers" / "an oil painting hangs above the
        # fireplace" (legal set dressing), or L11's own required nested-
        # screen content ("watches a cartoon... animated characters" — L11
        # MANDATES describing a screen's content, so flagging that content
        # as a style violation would make L11 and L29 contradict each
        # other). A genuine second style claim always lands in composer-
        # written text, because scene content is not framing language — the
        # composer is the only thing that writes style/medium words on
        # purpose.
        _style_gate_text = header_text + character_block + set_block + material_block + constraints_text
        _assert_single_style_declaration(_style_gate_text, style_line)
        _assert_no_unattached_claims(chunk_prompt, cast_refs=has_cast_refs)
        prompts.append(chunk_prompt)
    return prompts


async def generate_storyboard_sheet_for_scene(video_id, tenant_id, scene=None, beat=None,
                                              plan_only=False, progress=None):
    """The STORYBOARD GATE (Ryan's design): run the REAL coverage planner for
    the scene — channel-paced shot count, earned angles, verbatim line
    placement — persist that plan, and draw cheap sheet image(s) previewing
    EVERY planned shot as a numbered panel. The creator reviews the whole
    shot list for pennies; 'Generate pictures' then executes THIS EXACT saved
    plan (generate_coverage_for_video reuses it via coverage_directive), so
    what you approved is what you pay to draw."""
    def _p(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    v = await fetch_one(
        "SELECT id, tenant_id, video_title, COALESCE(aspect_ratio,'16:9') AS aspect, "
        "image_style_override, visual_style, render_style, video_model, "
        "COALESCE(dialogue_audio,'voice_over') AS dialogue_audio, "
        "production_style_snapshot "
        "FROM videos WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not v:
        return {"status": "failed", "error": "video not found"}
    vid, tenant, title, aspect = str(v["id"]), str(v["tenant_id"]), v["video_title"], v["aspect"]
    dialogue_audio = v["dialogue_audio"]  # channel pacing mode for _coverage_shape
    production_style_snapshot = v.get("production_style_snapshot")
    # NOTE: videos.image_model_override is deliberately NOT selected here.
    # C25a-fix-nano-sheets (Ryan's ruling, 2026-07-21 — "previews move OFF
    # the filtered endpoint entirely"): every sheet board below draws on the
    # LITERAL model "nano-banana-2", unconditionally — the video's own image
    # model choice no longer has any say over sheet previews (it still fully
    # governs the real per-shot PICTURES path: run_coverage / redraw_asset_
    # image / run_image_variants). See _draw_board's docstring below.
    #
    # C13b: the channel-style routing guardrail's two inputs, threaded down
    # through run_coverage -> plan_camera_moves -> route_shot_model. Distinct
    # from the IMAGE model discussion above — this is the video's declared
    # LOOK + its own clip model, unrelated to which model paints a preview.
    render_style = v["render_style"]
    video_model_id = v["video_model"]
    profile, style_dir = _resolve_style(v["image_style_override"], v["visual_style"])
    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
        "AND scene IS NOT NULL AND scene_text IS NOT NULL ORDER BY scene", vid, tenant)
    targets = [s for s in scenes if scene is None or s["scene"] == scene]
    if not targets:
        return {"status": "failed", "error": "no scenes with text"}

    claude = await get_text_client_for_tenant(tenant)
    claude_model = claude_model_for_direct_client(claude)
    kie_key = await _require_tenant_kie_key(tenant)
    ic = ImageClient(api_key=kie_key, tenant_id=tenant)
    # Scene-aware bible so each scene's storyboard names ONLY its characters + the
    # locked environments (per-scene character lock + the prose character lock).
    bible = await scene_aware_bible(vid, tenant, scenes, claude, claude_model)
    # quality_rules board scope (BOARD-LAWS.md "Runtime-editable rules"):
    # this tenant's active board-scoped rules, composed ONCE per call (not
    # per-scene — the same text applies to every scene this call plans) and
    # read into the planner's <board_quality_rules> prompt block below. "" for
    # any tenant with none configured — identical to before this feature
    # existed. quality_rules is a top-level backend module (like status_map,
    # database) — imported locally so this DB-free-by-convention scripts/
    # module only pulls it in on the one path that actually needs it.
    #
    # FAIL OPEN, deliberately: this is an OPTIONAL enhancement read (a
    # tenant with no board-scoped rules configured — every tenant today —
    # gets "" either way), never a hard dependency of board planning. A
    # quality_rules read hiccup (a schema issue, a transient DB error) must
    # never block the real, paid coverage-planning call that follows —
    # same fail-soft discipline as resolve_dvsu_overrides' per-key parsing.
    board_rules_text = ""
    try:
        import quality_rules as _quality_rules
        board_rules_text, _ = _quality_rules.compose_rules_text(
            await _quality_rules.active_board_rules(tenant))
    except Exception as _qr_exc:  # noqa: BLE001
        print(f"  ⚠️ quality_rules board-scope fetch failed ({_qr_exc}) — continuing with "
              "no board-scoped rules text", flush=True)
    crows = await fetch_all(
        "SELECT reference_url FROM video_characters WHERE video_id=$1 AND tenant_id=$2 "
        "AND reference_url IS NOT NULL ORDER BY sort", vid, tenant)
    cast_refs = [r["reference_url"] for r in crows]
    # SCENE LOCK: the approved environment reference conditions every sheet so
    # panel backgrounds match the designed location instead of drifting (the
    # engine supported env refs; this caller never passed them).
    envs = await _approved_envs(vid, tenant)

    # SHEETS DRAW ON GPT IMAGE 2, NANO BANNED (Ryan's ruling 2026-07-21
    # evening, REVERSING the same morning's C25a-fix-nano-sheets ruling after
    # seeing a full video of nano boards: "I actually really hate all of these
    # nano banana boards... none of them are consistent with their characters.
    # we will stick to gpt image 2"). Nano dodged OpenAI's filter but lost the
    # thing boards exist for — character identity (one board invented an
    # entirely different cast even with clean cast refs attached). GPT holds
    # identity; its filter risk is handled at the SOURCE instead: coverage.py
    # rule 7 keeps weapons/blades/violence out of every plan, the env
    # generator excludes them from location refs, and the free retry ladder
    # below (fallback header + re-rolls) absorbs the residual random output
    # blocks. A board that still exhausts the ladder FAILS CLEAN (error chip +
    # per-board redo) — never a nano draw (no_nano_fallback=True on every
    # draw call below).
    SHEET_DRAW_MODEL = "gpt-image-2"

    async def _draw_board(sc, srow, bi, sp, prompts_fallback_list, env_block, sheet_refs):
        """Draw ONE storyboard-sheet board through the full retry/re-roll ladder
        (primary draw -> C25a-fix8's fallback-header retry on a zero-cost
        content-filter reject -> up to 3 free re-rolls for a moderation/
        transient-Kie/ref-fetch failure), persist the result (the board's URL
        on success, a classified storyboard_errors entry on exhaustion —
        migration 113), and return (landed, entry). Closes over vid, tenant,
        ic, aspect, SHEET_DRAW_MODEL — constant for the whole video, set above.

        Every draw below passes model=SHEET_DRAW_MODEL ("gpt-image-2",
        literal — see the constant's comment) and no_nano_fallback=True. The
        router's GPT path normally falls back to nano-banana-2 on exhaustion
        (shared.clients.image_model_router._gpt_default) — for sheets that
        would silently hand a board to the model Ryan banned for character
        drift (his 2026-07-21 evening ruling). no_nano_fallback=True keeps a
        failed GPT attempt failed, so THIS ladder is what handles it: the
        fallback-header retry and free re-rolls absorb OpenAI's random
        output-stage blocks (which are back in scope now that sheets are on
        GPT again), the transient classes cover Kie 500s/ref-fetch flakes,
        and true exhaustion lands a classified error chip + per-board redo —
        never a nano draw.

        Shared by the scene's normal per-board pass AND the BUILD 2 sweep
        passes (2026-07-21) so a swept board draws through the IDENTICAL
        ladder — never a second, looser retry policy just because it's a
        re-attempt."""
        # D6-1 (L28) hard gate, defense-in-depth: _plan_sheet_prompts already
        # validated `sp` alone for the cast-ref claim, but env_block (the
        # "FINAL reference image" / LOCKED LOCATION claim) is concatenated
        # AFTER that check, here, right before the actual draw call — so it
        # gets its own check on the FULL text the model receives. env_block
        # is only ever non-empty when env matched with a real reference_url
        # (structurally guaranteed by _approved_envs' own WHERE clause), so
        # this should never fire in practice; caught (not raised through) so
        # a future regression fails THIS BOARD loudly — a classified error
        # chip the creator can see — rather than crashing the whole batch.
        try:
            _assert_no_unattached_claims(sp + env_block, cast_refs=bool(cast_refs),
                                         env_ref=bool(env_block))
        except SheetPromptContractViolation as _contract_exc:
            print(f"      ❌ Storyboard sheet: board {bi} failed the L28 hard gate — "
                  f"{_contract_exc}", flush=True)
            entry = {"code": None, "class": "unknown", "msg": str(_contract_exc)[:200],
                     "attempts": 0, "at": datetime.now(timezone.utc).isoformat()}
            await execute(
                "UPDATE scripts SET storyboard_errors = "
                "COALESCE(storyboard_errors, '{}'::jsonb) || $1::jsonb, updated_at=now() "
                "WHERE id=$2",
                json.dumps({str(bi): entry}), srow["id"])
            return False, entry
        fail_box: list = []
        url, _model_used = await generate_scene_image_for_model(
            ic, SHEET_DRAW_MODEL, sp + env_block, reference_urls=sheet_refs, aspect_ratio=aspect,
            fail_info_out=fail_box, no_nano_fallback=True)
        # C25a-fix8: ONE free retry with the sparser fallback header when the
        # primary header trips OpenAI's content filter (the exact, zero-cost,
        # deterministic signature — see _sheet_filter_reject's docstring).
        # Never retries a real (credit-consuming) failure — that would just
        # burn money re-drawing the same doomed prompt.
        retry_box: list = []
        fallback_attempted = False
        if not url and _sheet_filter_reject(fail_box[-1] if fail_box else None) \
                and bi - 1 < len(prompts_fallback_list):
            fallback_attempted = True
            info = fail_box[-1]
            print(f"      ⚠️ Storyboard sheet: board {bi} tripped OpenAI's content filter "
                  f"(failCode={info.get('failCode')}, creditsConsumed={info.get('creditsConsumed')}) "
                  "— retrying ONCE with the sparser fallback header (C25a-fix8)…")
            url, _model_used = await generate_scene_image_for_model(
                ic, SHEET_DRAW_MODEL, prompts_fallback_list[bi - 1] + env_block,
                reference_urls=sheet_refs, aspect_ratio=aspect, fail_info_out=retry_box,
                no_nano_fallback=True)
            if url:
                print(f"      ✅ Storyboard sheet: board {bi} succeeded on the fallback-header retry.")
            else:
                print(f"      ❌ Storyboard sheet: board {bi} failed again on the fallback header "
                      f"({(retry_box[-1] if retry_box else {}).get('failMsg') or 'no fail info'}).")
        # C25a-fix14: if BOTH header variants still hit the exact zero-cost
        # filter signature, RE-ROLL the primary a few more times — OpenAI's
        # image filter is NON-DETERMINISTIC near its threshold and a
        # rejection costs 0 credits, so re-rolling a coin-flip prompt is
        # FREE. Transient Kie 500s and reference-fetch failures join this
        # ladder too (infra flakes, zero-cost, nothing to do with prompt
        # wording) with a 15s pause first; filter re-rolls fire immediately.
        last_fail = retry_box[-1] if retry_box else (fail_box[-1] if fail_box else None)
        reroll = 0
        while not url and (_sheet_filter_reject(last_fail)
                           or _sheet_transient_kie_error(last_fail)
                           or _sheet_ref_fetch_error(last_fail)) and reroll < 3:
            reroll += 1
            if _sheet_ref_fetch_error(last_fail):
                print(f"      ⟳ Storyboard sheet: board {bi} retrying after reference fetch "
                      f"failure (free attempt {reroll}/3)…")
                await asyncio.sleep(15)
            elif _sheet_transient_kie_error(last_fail):
                print(f"      ⟳ Storyboard sheet: board {bi} retrying transient Kie 500 "
                      f"(free attempt {reroll}/3)…")
                await asyncio.sleep(15)
            else:
                print(f"      ⟳ Storyboard sheet: board {bi} re-rolling the flaky content "
                      f"filter (free attempt {reroll}/3)…")
            rr_box: list = []
            url, _model_used = await generate_scene_image_for_model(
                ic, SHEET_DRAW_MODEL, sp + env_block, reference_urls=sheet_refs,
                aspect_ratio=aspect, fail_info_out=rr_box, no_nano_fallback=True)
            last_fail = rr_box[-1] if rr_box else None
            if url:
                print(f"      ✅ Storyboard sheet: board {bi} landed on re-roll {reroll}.")
        if url:
            stable = await _stable_url(url, f"{vid}/storyboard/S{sc}-B{bi}.png", tenant)
            # bi is 1-5 by construction (prompts capped, beat validated).
            # Clear any PRIOR failure entry for this beat in the SAME
            # statement (migration 113's jsonb minus) — a board that
            # lands after previously exhausting the ladder (a manual
            # per-board redo, or a BUILD 2 sweep) must not leave a stale
            # error chip on a slot that now has an image.
            await execute(
                f"UPDATE scripts SET storyboard_{bi}_url=$1, "
                "storyboard_errors = storyboard_errors - $2, updated_at=now() WHERE id=$3",
                stable, str(bi), srow["id"])
            return True, None
        # Ladder fully exhausted for this board — classify the LAST failure
        # it hit (same predicates the ladder itself gated retries on, via
        # _sheet_fail_class) and persist it so the creator can see WHY, not
        # just an empty slot (migration 113).
        attempts = 1 + (1 if fallback_attempted else 0) + reroll
        entry = _sheet_fail_entry(last_fail, attempts)
        await execute(
            "UPDATE scripts SET storyboard_errors = "
            "COALESCE(storyboard_errors, '{}'::jsonb) || $1::jsonb, updated_at=now() "
            "WHERE id=$2",
            json.dumps({str(bi): entry}), srow["id"])
        print(f"      ❌ Storyboard sheet: board {bi} exhausted the retry ladder after "
              f"{attempts} attempt(s) — {entry['class']}: {entry['msg'] or 'no message'}")
        return False, entry

    done = 0
    total_shots = 0
    # D6-1b (independent-verifier finding #3 — "a raised gate reports
    # success with zero boards drawn"): a SheetPromptContractViolation
    # caught below used to just `continue` — no board attempt, no
    # storyboard_errors entry, no `done` increment, and NOTHING recorded —
    # so a scene blocked by a real L3/L28/L29 violation silently vanished
    # from the final message, and routes/pipeline.py's _set_task_status
    # reads status straight off this function's return value, so the UI
    # showed COMPLETED with zero boards drawn. Tracked here so the final
    # return can tell the truth: ALL scenes blocked -> "failed" with the
    # violation text; SOME blocked -> "completed" but the message says so
    # explicitly, never a bare "Storyboard ready for N scene(s)" that
    # quietly undercounts.
    blocked_scenes: list[tuple] = []
    for s in targets:
        sc = s["scene"]
        srow = await fetch_one(
            "SELECT id, coverage_directive, coverage_directive_hash FROM scripts "
            "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3", vid, tenant, sc)
        if not srow:
            continue
        _mm, _amin, _amax, _mframes = _coverage_shape(
            s["scene_text"] or "",
            dialogue_audio,
            production_style_snapshot,
        )
        if beat is not None:
            # PER-BOARD REDO: redraw ONE sheet from the SAVED plan — never
            # re-plan (that would silently change the other boards' panels).
            if not (srow.get("coverage_directive") or "").strip() or \
                    srow.get("coverage_directive_hash") != _scene_text_hash(s["scene_text"] or ""):
                return {"status": "failed",
                        "error": f"Scene {sc} has no current plan — generate the scene's "
                                 "storyboard first, then redo boards one at a time."}
            directive = srow["coverage_directive"]
            _p(f"Scene {sc}: redrawing board {beat} from the saved plan…")
        else:
            _p(f"Scene {sc}: planning the shots…")
            directive = await generate_coverage_directive(
                s["scene_text"] or "", title, profile, bible, [sc], [],
                max_moments=_mm, angles_min=_amin, angles_max=_amax,
                anthropic_client=claude, model=claude_model,
                # D10-3a: narrative block first (if this video's bible carries one),
                # then this call's own board-scoped quality rules — see
                # _board_rules_text_with_narrative's docstring for why this is the
                # one hook available without editing storyboard/coverage.py.
                board_rules_text=_board_rules_text_with_narrative(board_rules_text, bible))
        # C7 fix (a): parse -> budget -> floors -> variety, the SAME deterministic
        # pipeline (and order) run_coverage() runs on this exact directive_text at
        # picture-draw time — the sheet preview built below from `moments` and the
        # picture step's board-anchor panel numbering can no longer disagree on the
        # scene's final shot sequence.
        moments = plan_moments_deterministic(directive or "", _mm, _amax, max_frames=_mframes)
        if not moments:
            _p(f"Scene {sc}: the planner returned no shots"); continue
        # Verbatim line placement NOW, so the preview shows exactly which shot
        # speaks which line — the same reconcile runs again at draw time and,
        # being deterministic, lands identically.
        _reconcile_moment_dialogue(moments, s["scene_text"] or "")
        shot_count = sum(1 + len(m.get("angles") or []) for m in moments)

        # D6-1: env matched HERE (moved up from just before the draw loop)
        # so the canonical per-location material map (L20) can be resolved
        # BEFORE _sheet_kwargs is built — env_block/sheet_refs below reuse
        # this SAME match rather than recomputing it.
        location_sets = parse_location_sets(directive or "")
        env = _match_scene_env((directive or "") + " " + (s["scene_text"] or ""), envs)
        # D6-1 (L20): the canonical, code-rendered material map WINS over the
        # planner LLM's own [MATERIAL|...] line when one is authored
        # (video_environments.material_map, migration 142) — never a
        # paraphrase of it. Falls back to the LLM's line, byte-identical to
        # before this migration, when no canonical entry exists yet.
        _canonical_material = _canonical_material_line(envs, location_sets, env)
        material_line = _canonical_material or (parse_material_map(directive or "") or "")
        _sheet_kwargs = dict(
            panels_per_sheet=panels_per_sheet_for(directive or ""),
            set_line=parse_set_dressing(directive or "") or "",
            axis_line=parse_axis_line(directive or "") or "",
            setups_line=parse_setups_line(directive or "") or "",
            # BOARD LAWS additions (L3/L4/L6/L20) — see _plan_sheet_prompts'
            # own docstring for what each does; all fall back to today's
            # behavior when the directive carries none of this law's markup.
            character_line=_character_identity_line(bible, sc),
            location_sets=location_sets,
            material_line=material_line,
            motion_scene=scene_has_motion(moments, location_sets),
            # D6-1 (L28): the honest truth about whether any character
            # reference actually reaches this scene's draw call — decides
            # _sheet_header's reference-image clause, never a guess.
            has_cast_refs=bool(cast_refs),
            # D6-1b (L3): the video's approved environments, so the location
            # gate can upgrade a LOCSET-name paraphrase into a canonical
            # match instead of blocking on prose-vs-prose disagreement.
            canonical_envs=envs)
        # Computed ONCE here and reused below (never re-derived) so sheet
        # chunking (_plan_sheet_prompts, via _sheet_kwargs), the per-board
        # panel counts and the progress messages can never diverge. _sizes is
        # the SAME balanced per-board split _plan_sheet_prompts chunks with
        # (shot_count == len(its panels list): one panel per master + angle).
        _cap = _sheet_kwargs["panels_per_sheet"]
        _sizes = sheet_chunk_sizes(shot_count, _cap)
        _previewed = sum(_sizes[:5])  # panels on the (at most 5) boards actually drawn
        # D6-1 hard gates (L3/L28/L29): _plan_sheet_prompts raises
        # SheetPromptContractViolation before returning any text that would
        # violate one of these laws — caught here so ONE scene's bad plan
        # fails loudly and skips to the next scene, instead of crashing the
        # whole batch or (worse) silently sending a bad prompt to the paid
        # draw call below.
        try:
            prompts = _plan_sheet_prompts(moments, style_dir, **_sheet_kwargs)[:5]
            # C25a-fix8: the same panels, header-swapped — held ready so a board
            # that trips OpenAI's content filter on the primary header can retry
            # ONCE against the identical body with a sparser fallback header (see
            # _sheet_header's docstring). Cheap (pure string formatting, no LLM),
            # computed once here rather than per-failure.
            prompts_fallback = _plan_sheet_prompts(
                moments, style_dir, header_variant="fallback", **_sheet_kwargs)[:5]
        except SheetPromptContractViolation as _contract_exc:
            _p(f"Scene {sc}: board prompt failed a hard gate — {_contract_exc}")
            blocked_scenes.append((sc, str(_contract_exc)))
            continue
        if beat is not None and not (1 <= beat <= len(prompts)):
            return {"status": "failed",
                    "error": f"Scene {sc} has {len(prompts)} board(s) — board {beat} doesn't exist."}
        if beat is None:
            # STREAMING CONTRACT (Ryan, 2026-07-07): persist the plan and the
            # board COUNT the moment planning finishes — the UI shows one
            # placeholder slot per coming board immediately, and each board
            # drops into its slot the moment it lands (per-slot UPDATE below),
            # not in one batch at the end. storyboard_errors=NULL (migration
            # 113) resets alongside the URLs — a full replan can shrink the
            # board count, and without this a stale failure entry for a beat
            # PAST the new plan's count would survive invisibly and could
            # resurface if the plan later grows back to that beat number.
            #
            # D3-59 (2026-07-28): this write is SKIPPED ENTIRELY when
            # plan_only — it nulls storyboard_1_url..storyboard_5_url and
            # storyboard_errors unconditionally, which would blow away
            # already-drawn, already-paid-for board images on a call meant
            # to be a zero-spend dry run. plan_only now persists NOTHING;
            # the plan is returned in the response only. This is safe: the
            # real draw call (plan_only=False) always recomputes and
            # persists its own directive/hash/prompts/beat_count from
            # scratch before it draws anything, so it never depends on a
            # plan_only call having run first.
            if not plan_only:
                blocks = "\n\n".join(f"--- BEAT {i} ---\n{p}" for i, p in enumerate(prompts, start=1))
                await execute(
                    "UPDATE scripts SET coverage_directive=$1, coverage_directive_hash=$2, "
                    "storyboard_prompts=$3, storyboard_beat_count=$4, storyboard_1_url=NULL, "
                    "storyboard_2_url=NULL, storyboard_3_url=NULL, storyboard_4_url=NULL, "
                    "storyboard_5_url=NULL, storyboard_errors=NULL, updated_at=now() WHERE id=$5",
                    directive, _scene_text_hash(s["scene_text"] or ""), blocks, len(prompts), srow["id"])
            if plan_only:
                # PLAN GATE (Ryan, 2026-07-07): stop here — the creator reads
                # the shot plan in the app, then draws boards one at a time.
                done += 1
                total_shots += shot_count
                # A scene over 5 boards' worth of panels (prompts is sliced to
                # [:5]) previews only its FIRST sum(_sizes[:5]) shots — say so
                # plainly instead of implying every shot got a preview panel.
                # The pictures step still draws every planned shot from the
                # full text plan regardless; only the SHEET PREVIEW truncates.
                if shot_count > _previewed:
                    _p(f"Scene {sc}: plan ready — {shot_count} shots — previewing the "
                       f"first {_previewed} on {len(prompts)} board(s), nothing drawn yet")
                else:
                    _p(f"Scene {sc}: plan ready — {shot_count} shots on {len(prompts)} board(s), "
                       "nothing drawn yet")
                continue

        # env already matched above (moved up for the L20 canonical material
        # resolution) — reused here, never recomputed.
        env_block = ""
        # C25a-fix7 capped sheet reference images at 2 (SHEET_REF_CAP), blaming
        # a 3rd input_urls entry for the 400s seen on video cd5d2883. C25a-fix8
        # (2026-07-20) re-derived that conviction against the REAL filter: the
        # exact failing prompt's header spliced onto a body proven clean at 2
        # refs was re-probed at 3 refs (2 cast + the env ref) and SUCCEEDED
        # (taskId 829cfea1f9c95b4f27935375ea5a95a5) — the ref count was never
        # the cause; fix7's evidence was confounded by the convicted header
        # riding along on every 3-ref call in prod that day. Cap REVERTED —
        # every cast ref plus the env ref goes in, same as pre-fix7.
        sheet_refs = list(cast_refs)
        if env:
            # SHEET PREVIEWS ONLY (2026-07-21, same knife-scene evidence as
            # set_line above): the LOCKED LOCATION description is builder-
            # authored sheet-prompt text too, so it runs through
            # _neutralize_risky_props before truncation — a risky prop named
            # here gets drawn into every panel showing the location, same
            # failure mode as an unneutralized FIXED SET line.
            env_desc = _neutralize_risky_props(env.get("description") or "")[:220]
            env_block = (
                f"\nLOCKED LOCATION — {env['name']}: every panel's background is this EXACT "
                "location as shown in the FINAL reference image (after the cast sheets): "
                f"{env_desc}. Keep the location's layout, colors and "
                "props IDENTICAL across all panels; never invent a different room or set."
            )
            sheet_refs.append(env["reference_url"])
        lock_note = f", locked to {env['name']}" if env else ""
        todo = [(beat, prompts[beat - 1])] if beat is not None else list(enumerate(prompts, start=1))
        ok = 0
        # Beats that exhausted the whole retry ladder this pass, as (bi,
        # class) — feeds BOTH the storyboard_errors write below and the
        # scene-summary _p() line after the loop, so the two can never
        # disagree about which boards failed or why.
        scene_failures: list = []
        for bi, sp in todo:
            # Panels ON THIS SHEET, not the scene's total — "(27 shots)" on a
            # single-board draw read as "everything is generating" (Ryan hit
            # Stop on a correct one-board run, 2026-07-07). Read from the SAME
            # balanced _sizes list computed once above — never re-derived
            # min/stride math, so this can't diverge from the chunking
            # _plan_sheet_prompts actually used.
            on_sheet = _sizes[bi - 1]
            _p(f"Scene {sc}: drawing {'ONLY board' if beat is not None else 'board'} "
               f"{bi} of {len(prompts)} — one sheet, {on_sheet} panels{lock_note}…")
            # Storyboard SHEETS are a preview, not an asset row — no image_model to persist here.
            landed, entry = await _draw_board(sc, srow, bi, sp, prompts_fallback, env_block, sheet_refs)
            if landed:
                ok += 1
                _p(f"Scene {sc}: board {bi} is up")
            else:
                scene_failures.append((bi, entry["class"]))

        # =====================================================================
        # BUILD 2 (2026-07-21): auto-sweeper + escalation. After the scene's
        # normal pass, redraw ONLY the boards still missing, up to 2 more
        # in-process passes — mirrors the manual playbook proven twice
        # tonight (a flaky moderation coin flip often lands clean on a plain
        # re-roll after a pause). Per-beat redraws (beat is not None) ARE the
        # manual retry already, so they never sweep; plan_only never reaches
        # this code at all (it `continue`s above, before the board loop).
        # Every sweep draw runs through the SAME _draw_board ladder — no new
        # spend class: a failure is still free, a landed board still costs
        # the same ~$0.05 a manual retry would.
        # =====================================================================
        sweeps_run = 0
        if beat is None and scene_failures:
            last_class = {fbi: cls for fbi, cls in scene_failures}
            while scene_failures and sweeps_run < 2:
                sweeps_run += 1
                missing = [fbi for fbi, _cls in scene_failures]
                _p(f"Scene {sc}: Sweep {sweeps_run}: retrying {len(missing)} missing board(s)…")
                await asyncio.sleep(90)  # time-decorrelates the moderation coin flip
                if sweeps_run == 2 and any(last_class.get(fbi) in ("moderation", "sensitive")
                                           for fbi in missing):
                    # ESCALATION (sweep 2 only): a board that ALSO failed
                    # sweep 1 on the moderation class gets the full
                    # treatment — both dictionaries applied to the scene's
                    # OWN coverage_directive, persisted, then the whole
                    # sheet plan rebuilt from the reworded text before
                    # redrawing. "moderation"/"sensitive" are the SAME
                    # zero-cost content-filter rejection (_sheet_filter_reject),
                    # split only by failCode 400 vs 422 (_sheet_fail_class) —
                    # both qualify, since both are the density-scoring coin
                    # flip this escalation exists to break. kie_transient/
                    # ref_fetch/unknown are real infra or unclassified
                    # failures with nothing to do with wording — never
                    # escalated. coverage_directive is ONE shared column per
                    # scene, so this escalates every still-missing board
                    # together — there is no way to reword only one board's
                    # share of a single stored text.
                    new_directive, reworded_pairs = _escalate_panel_briefs(directive)
                    if reworded_pairs:
                        directive = new_directive
                        await execute(
                            "UPDATE scripts SET coverage_directive=$1, updated_at=now() WHERE id=$2",
                            directive, srow["id"])
                        for old, new in reworded_pairs:
                            print(f"      🔧 Sweep {sweeps_run} escalation: reworded "
                                  f"'{old}' -> '{new}'")
                        # C7 fix (a): same shared deterministic pipeline as the initial
                        # plan above — the escalation only reworks wording (never adds/
                        # removes shots), but re-running the full pipeline here (not just
                        # parse+budget) keeps this re-plan byte-identical to what the
                        # picture step will recompute from the same (reworded) directive.
                        # Falls back to [] (never None) on a parse failure — practically
                        # unreachable (the reworded text keeps every MOMENT/shot line,
                        # only prop/gesture nouns change) but matches the old
                        # parse_coverage()-returns-[] behavior instead of crashing
                        # downstream on a bare None.
                        moments = plan_moments_deterministic(
                            directive or "", _mm, _amax, max_frames=_mframes) or []
                        _reconcile_moment_dialogue(moments, s["scene_text"] or "")
                        # D6-1: same canonical-material precedence (L20) as the
                        # initial plan above — env/envs are unchanged by an
                        # escalation (only panel-brief wording is reworded), so
                        # the same `env` match is reused, never recomputed.
                        _sweep_location_sets = parse_location_sets(directive or "")
                        _sweep_material = (
                            _canonical_material_line(envs, _sweep_location_sets, env)
                            or (parse_material_map(directive or "") or ""))
                        _sheet_kwargs = dict(
                            panels_per_sheet=panels_per_sheet_for(directive or ""),
                            set_line=parse_set_dressing(directive or "") or "",
                            axis_line=parse_axis_line(directive or "") or "",
                            setups_line=parse_setups_line(directive or "") or "",
                            character_line=_character_identity_line(bible, sc),
                            location_sets=_sweep_location_sets,
                            material_line=_sweep_material,
                            motion_scene=scene_has_motion(moments, _sweep_location_sets),
                            has_cast_refs=bool(cast_refs),
                            canonical_envs=envs)
                        try:
                            prompts = _plan_sheet_prompts(moments, style_dir, **_sheet_kwargs)[:5]
                            prompts_fallback = _plan_sheet_prompts(
                                moments, style_dir, header_variant="fallback", **_sheet_kwargs)[:5]
                        except SheetPromptContractViolation as _contract_exc:
                            _p(f"Scene {sc}: sweep {sweeps_run} board prompt failed a hard "
                               f"gate — {_contract_exc}")
                            continue
                still_failing = []
                for fbi in missing:
                    on_sheet = _sizes[fbi - 1]
                    _p(f"Scene {sc}: sweep {sweeps_run} — redrawing board {fbi} of "
                       f"{len(prompts)}, {on_sheet} panels{lock_note}…")
                    landed, entry = await _draw_board(
                        sc, srow, fbi, prompts[fbi - 1], prompts_fallback, env_block, sheet_refs)
                    if landed:
                        ok += 1
                    else:
                        last_class[fbi] = entry["class"]
                        still_failing.append((fbi, entry["class"]))
                scene_failures = still_failing

        sweep_note = f" after {sweeps_run} sweep{'s' if sweeps_run != 1 else ''}" if sweeps_run else ""
        fail_note = ""
        if scene_failures:
            fail_note = " — " + "; ".join(
                f"b{fbi}: {_SHEET_FAIL_LABELS.get(cls, 'failed')}" for fbi, cls in scene_failures)
        if not ok:
            _p(f"Scene {sc}: 0 of {len(todo)} board(s) drawn{fail_note}{sweep_note}" if scene_failures
               else f"Scene {sc}: storyboard image failed{sweep_note}")
            continue
        # generation_ledger (script/storyboard ledger-gap fix): every board
        # `ok` counts here just drew a real GPT Image 2 sheet (_draw_board's
        # SHEET_DRAW_MODEL, unconditional per the C25a-fix-nano-sheets
        # ruling above) — this whole function had NO write path into
        # generation_ledger before this fix (found live on video f00ea79a:
        # 3 sheets landed on scene 1, ledger empty, total_cost stuck at 0).
        # One row per scene pass — same "one row per batch, not per frame"
        # convention store_scene()'s "image" stage write uses — priced with
        # the SAME PICTURE_COST(gpt-image-2) number actions.py's
        # pre-generation "storyboards" verb quote already charges per board.
        from actions import picture_price_for
        sheet_price = picture_price_for(SHEET_DRAW_MODEL)
        await record_ledger_entry(
            tenant_id=tenant, video_id=vid, stage="storyboard", model=SHEET_DRAW_MODEL,
            units=ok, unit_cost=sheet_price, actual_cost=round(ok * sheet_price, 2),
        )
        done += 1
        total_shots += shot_count
        # Failures present: switch to the "N of M board(s) drawn" shape so a
        # partial scene never reads as fully ready — enumerate every failed
        # board's class right in the same line (Ryan's ask: surface WHY, not
        # just an empty slot). No failures: unchanged from before this
        # migration, same truncation honesty as the plan-only message above
        # (a scene over 5 boards' worth of panels only ever got a SHEET
        # PREVIEW for its first sum(_sizes[:5]) shots — say so, never imply
        # every shot got a preview).
        if scene_failures:
            _p(f"Scene {sc}: {ok} of {len(todo)} board(s) drawn{fail_note}{sweep_note}")
        elif shot_count > _previewed:
            _p(f"Scene {sc}: storyboard ready — {shot_count} shots — previewed the "
               f"first {_previewed} on {ok} board(s){sweep_note}")
        else:
            _p(f"Scene {sc}: storyboard ready — {shot_count} shots on {ok} board(s){sweep_note}")
    # D6-1b: honest status/message when one or more scenes were blocked by a
    # hard gate (SheetPromptContractViolation) before any board was even
    # attempted for them — see blocked_scenes' own comment above. Same
    # three-way shape redraw_asset_images already uses for partial success
    # (line ~3120: "completed" if redrawn or not failed else "failed").
    if blocked_scenes:
        _blocked_detail = "; ".join(f"scene {n}: {msg}" for n, msg in blocked_scenes)
        if done == 0:
            # ALL scenes blocked — nothing was drawn or even planned. This
            # must not read as "completed": routes/pipeline.py's
            # _set_task_status takes its status straight from this dict, and
            # a "completed" here would show the creator a green checkmark
            # over zero boards.
            return {"status": "failed",
                    "error": f"{len(blocked_scenes)} scene(s) blocked by a hard gate, "
                             f"no boards drawn — {_blocked_detail}",
                    "message": f"{len(blocked_scenes)} scene(s) blocked by a hard gate, "
                               f"no boards drawn — {_blocked_detail}"}
        # PARTIAL success: some scenes genuinely drew, others were blocked.
        # Say so explicitly rather than a bare "Storyboard ready for N
        # scene(s)" that would silently undercount without explaining why.
        base = (f"Shot plan ready for {done} scene(s) — {total_shots} shot(s), nothing drawn. "
               "Review the plan, then draw boards one at a time." if plan_only else
               f"Storyboard ready for {done} scene(s) — {total_shots} planned shot(s). "
               "Review the sheets; 'Generate pictures' draws exactly this plan.")
        return {"status": "completed",
                "message": f"{base} {len(blocked_scenes)} scene(s) blocked by a hard gate and "
                           f"got NO boards — {_blocked_detail}"}
    if plan_only:
        return {"status": "completed",
                "message": (f"Shot plan ready for {done} scene(s) — {total_shots} shot(s), "
                            "nothing drawn. Review the plan, then draw boards one at a time.")}
    return {"status": "completed",
            "message": (f"Storyboard ready for {done} scene(s) — {total_shots} planned shot(s). "
                        "Review the sheets; 'Generate pictures' draws exactly this plan.")}


# When grok's content filter flags a frame (usually a tight over-the-shoulder or
# low/ambiguous angle of a child), redraw it as a clean, bright, front-facing
# medium shot of the same moment — same character, wardrobe, setting and action,
# just an unambiguous wholesome framing the filter accepts.
SAFE_REFRAME_PREFIX = (
    "Clear, bright, front-facing MEDIUM shot. The character is fully clothed, "
    "eyes open, face well-lit and unobscured, in a wholesome children's-storybook "
    "style. Keep the same character, wardrobe, setting and action, but use a plain "
    "respectful medium framing — not an over-the-shoulder, close, low or ambiguous "
    "angle. "
)


async def redraw_asset_image(video_id, tenant_id, asset_id, progress=None, safe_reframe=False):
    """Redraw ONE picture from its (possibly edited) image_prompt, anchored on the LOCKED
    cast sheets so the characters stay consistent. Clears the now-stale clip. Honors the
    video's image_model_override (GPT Image 2 stays the default + the content-policy
    fallback — see shared.clients.image_model_router, the ONE resolver this and the
    legacy pipeline_executor.py variant path both use).

    safe_reframe: prepend a wholesome medium-shot directive so a frame that grok's
    content filter rejected gets redrawn into a framing the filter accepts."""
    def _p(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    a = await fetch_one(
        "SELECT a.id, a.scene, a.image_index, a.image_prompt, a.hero_shot, "
        "a.generation_method, a.group_arrangement, "
        "COALESCE(v.aspect_ratio,'16:9') AS aspect, v.image_model_override, "
        "v.image_style_override, v.visual_style "
        "FROM assets a JOIN videos v ON v.id = a.video_id "
        "WHERE a.id=$1 AND a.video_id=$2 AND a.tenant_id=$3", asset_id, video_id, tenant_id)
    if not a:
        return {"status": "failed", "error": "picture not found"}
    prompt = (a["image_prompt"] or "").strip()
    if not prompt:
        return {"status": "failed", "error": "this picture has no image prompt to redraw from"}
    if safe_reframe:
        prompt = SAFE_REFRAME_PREFIX + prompt

    # SAME TREATMENT AS THE BATCH DRAW (Ryan, 2026-07-21: "the redraw should
    # get the same treatment as the draw... telling it the style upfront so
    # its weighted accordingly"). assets.image_prompt stores only the shot's
    # COMPOSITION text — the batch path wraps it at draw time in the channel
    # style (prefix) and _STYLE_LOCK (suffix), so a redraw from the bare
    # stored prompt carried NO style pressure at all beyond the small cast
    # refs, and drifted semi-realistic (proven live on cd5d2883's scene-1
    # redraws, 2026-07-21). Style goes FIRST so it outweighs everything after.
    _profile, _style_dir = _resolve_style(a.get("image_style_override"), a.get("visual_style"))
    style_prefix = (
        f"ART STYLE — the single most important instruction, every element of this frame is "
        f"rendered in it: {_style_dir} " if _style_dir else "")

    kie_key = await _require_tenant_kie_key(tenant_id)
    ic = ImageClient(api_key=kie_key, tenant_id=tenant_id)
    crows = await fetch_all(
        "SELECT name, identity_tag, reference_url FROM video_characters WHERE video_id=$1 "
        "AND tenant_id=$2 AND reference_url IS NOT NULL ORDER BY sort", video_id, tenant_id)
    cast_refs = [r["reference_url"] for r in crows]
    # D6-1 (L6 — IDENTITY ONCE) REPAIR LEG: the SAME canonical short tag the
    # sheet composer's CHARACTER block uses (video_characters.identity_tag,
    # migration 142), re-read FRESH here rather than baked into the stored
    # image_prompt — the FRESH route (see this function's module-level
    # comment on redraw_asset_image being the repair leg's home) so a
    # creator's later correction to identity_tag heals every future redraw
    # of an old shot, not just new ones. "" when no character has a
    # canonical tag — no claim, byte-identical to before this migration.
    cast_identity_note = ""
    _tags = [f"{r['name']} ({(r.get('identity_tag') or '').strip()})"
             for r in crows if (r.get("identity_tag") or "").strip()]
    if _tags:
        cast_identity_note = " CHARACTER — stated once, drawn identically: " + "; ".join(_tags) + "."

    # LOCKED LOCATION on redraws too (2026-07-21): the batch pictures run
    # conditions every frame on the scene's approved environment ref, but this
    # path used to attach ONLY cast refs — so a redrawn frame re-invented its
    # background and visibly drifted from its still-original neighbors (seen
    # live on cd5d2883's scene-1 redraws). Same matcher as the batch path;
    # fail-soft, a redraw without an env match just draws like before.
    env_refs, env_note, srow = [], "", None
    try:
        srow = await fetch_one(
            "SELECT coverage_directive, scene_text FROM scripts "
            "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3", video_id, tenant_id, a["scene"])
        envs = await _approved_envs(video_id, tenant_id)
        env = _match_scene_env(((srow or {}).get("coverage_directive") or "") + " " +
                               ((srow or {}).get("scene_text") or ""), envs) if envs else None
        if env and env.get("reference_url"):
            env_refs = [env["reference_url"]]
            env_note = (
                f" The LAST attached reference image is the LOCKED LOCATION — {env['name']}: "
                "this frame's background is this EXACT location; keep its layout, colors and "
                "props IDENTICAL to that reference."
            )
            # C4 contract-triangle repair leg: the SAME verbatim manifest the
            # build prompt used (render_prop_manifest — build-time callers are
            # storyboard.bot._format_story_bible_for_beat and storyboard.
            # coverage.run_coverage), so a repair/redraw can't drift the props
            # even when the batch draw already applied the manifest once.
            manifest = render_prop_manifest(env.get("props"))
            if manifest:
                env_note += f" {manifest}"
            # D6-1 (L20 — MATERIAL MAP) REPAIR LEG: same fresh-re-derivation
            # pattern as the prop manifest just above — reads video_
            # environments.material_map at REDRAW time rather than trusting
            # anything baked into the stored image_prompt, so a corrected
            # canonical material map heals an old shot's next redraw instead
            # of the redraw quietly reverting to whatever the planner LLM
            # invented for THAT scene's [MATERIAL|...] line when it was
            # first drawn.
            material_map = (env.get("material_map") or "").strip()
            if material_map:
                env_note += f" Material map, fixed for this whole set: {material_map}."
    except Exception as env_err:  # noqa: BLE001 — the redraw itself must never die on this
        _p(f"  (no location lock for this redraw: {str(env_err)[:80]})")

    # D6-2 (L16 + L22, migration 143) REPAIR LEG: FRESH re-derivation at
    # redraw time — the D6-1-preferred pattern (fresh beats baked: a later
    # fix to parse_reverse_setup_pairs/compute_reverse_arrangement heals an
    # OLD shot's next redraw without regenerating the scene). Reconstructs
    # THIS shot's own SETUP id from its stored image_prompt (the same
    # "(SETUP X)" tag the drawer wrote at build time — coverage.py's
    # _setup_id), then re-parses THIS SCENE's own coverage_directive (the
    # same immutable per-scene record the build-time lock read) for the
    # reverse-setup pairing and, if this shot IS itself a reverse partner,
    # re-derives the same computed anti-carryover tail apply_reverse_
    # background_lock would have stamped at build time. Reuses `srow` (the
    # SAME scripts row the env-lock block above fetched — never a second
    # query) so this repair works whether or not an approved environment
    # matched. A blank/legacy directive, or a shot with no SETUP tag,
    # repairs nothing — fail-soft, exactly like every other redraw
    # amendment here.
    l16_l22_note = ""
    try:
        this_sid = _setup_id({"description": prompt})
        if this_sid:
            directive = (srow or {}).get("coverage_directive") or ""
            reverse_pairs = parse_reverse_setup_pairs(parse_setups_line(directive))
            partner = (reverse_pairs.get(this_sid)
                       or reverse_pairs.get(_setup_base_id(this_sid))) if reverse_pairs else None
            # Never double-stamp: the build-time repair leg (apply_reverse_
            # background_lock) may already have baked this exact reminder in.
            if partner and f"matched reverse of SETUP {partner}" not in prompt:
                l16_l22_note += (
                    f" Reverse-angle background lock (computed, re-derived at redraw): this "
                    f"camera SETUP {this_sid} is the matched reverse of SETUP {partner}. "
                    f"Whatever sits behind the subject in SETUP {partner} must NOT reappear "
                    f"behind them here — state what genuinely sits behind the subject from "
                    f"THIS camera position; a front light source there is now BEHIND THIS "
                    f"camera instead.")
        # assets.group_arrangement (migration 143) IS the canonical per-shot
        # signal — re-attach it if the stored prompt doesn't already carry
        # it verbatim (it usually does, from the build-time stamp; this
        # only matters if the column were ever corrected after the fact,
        # the exact "corrected canonical record heals old shots" pattern
        # D6-1 established for identity_tag/material_map).
        garr = (a.get("group_arrangement") or "").strip()
        if garr and garr not in prompt:
            l16_l22_note += f" Group arrangement (canonical): {garr}."
    except Exception as l16_err:  # noqa: BLE001 — the redraw itself must never die on this
        _p(f"  (no reverse-angle/arrangement repair for this redraw: {str(l16_err)[:80]})")

    # MOMENT-MASTER ANCHOR (D3-65): the fix for "the redraw repair path draws
    # the wrong picture, systematically". generate_coverage_frames NEVER draws
    # an angle on cast+env alone — every angle's reference list is
    # `cast_refs + [master_url] + env_refs` (angle_base, coverage.py) PLUS
    # _SAME_SUBJECT stamped into its prompt ("this is the SAME moment from a
    # different camera... match the staging and setting of the attached
    # reference exactly"). redraw_asset_image only ever sent cast_refs +
    # env_refs — no photo anchoring a non-master shot to ITS OWN moment's
    # composition/location, just a photo of the character(s) and ONE generic
    # per-scene environment reference (the same env photo for every shot in
    # the scene, master or angle, correct location or not — see
    # _match_scene_env above). Proven live on 686b4651 scene 1: all four
    # failed redraws (S-01.101/102/108/109) were non-master angles (hero_shot
    # =false); the untouched masters (100/103/107) were never redrawn and
    # stayed correct. Without the master photo, a non-master redraw had
    # nothing pulling it toward its own moment's specific staging — it
    # regressed toward the one generic reference photo it DID have (the
    # scene's single env shot, sometimes the wrong location entirely for a
    # multi-location scene, e.g. 108/109's corridor moment vs. the scene's
    # only approved env being the pod interior) and drew a generic, wrong
    # composition even though its own stored prompt was full-length and
    # correct. Reconstructing the master: coverage rows are inserted
    # master-then-its-angles per moment in ascending image_index order
    # (store_scene), so the nearest EARLIER hero_shot row in this same scene
    # IS this shot's moment's master — the exact frame angle_base anchors on
    # at draw time. hero_shot is scoped to generation_method='coverage' since
    # that master/angle block ordering is a coverage-path invariant, not a
    # promise other generation methods make for the column.
    master_refs, master_note = [], ""
    if not a.get("hero_shot"):
        try:
            mrow = await fetch_one(
                "SELECT image_url FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
                "AND generation_method='coverage' AND hero_shot=true AND image_index<$4 "
                "AND image_url IS NOT NULL ORDER BY image_index DESC LIMIT 1",
                video_id, tenant_id, a["scene"], a["image_index"])
            if mrow and mrow.get("image_url"):
                master_refs = [mrow["image_url"]]
                master_note = _SAME_SUBJECT
        except Exception as master_err:  # noqa: BLE001 — redraw must never die on this
            _p(f"  (no moment-master anchor for this redraw: {str(master_err)[:80]})")

    model_override = a.get("image_model_override")
    _p(f"Redrawing S{a['scene']}.{a['image_index']} ({model_override or 'GPT Image 2'})…")
    # Fresh box per call (checklist C16c) — this is a single-image redraw,
    # one ledger row per call, so the real Kie task id can thread straight
    # into record_ledger_entry's dedup key below.
    task_id_box: list = []
    # With a stated style leading the prompt, the match-the-refs STYLE LOCK
    # would contradict it — use the hygiene-only block (same split the batch
    # path uses in storyboard.coverage.generate_coverage_frames).
    _style_block = _STYLE_LOCK_HYGIENE if style_prefix else _STYLE_LOCK
    # Reference + prompt ORDER now mirrors generate_coverage_frames' angle_base
    # + prompt assembly exactly: cast_refs + [master_url] + env_refs, and
    # style_prefix + composition + _SAME_SUBJECT + style_block + env_note.
    url, model_used = await generate_scene_image_for_model(
        ic, model_override,
        style_prefix + cast_identity_note + prompt + master_note + _style_block + env_note
        + l16_l22_note,
        reference_urls=cast_refs + master_refs + env_refs,
        aspect_ratio=a["aspect"], task_id_out=task_id_box)
    if not url:
        return {"status": "failed", "error": "image generation failed"}
    stable = await _stable_url(url, f"{video_id}/coverage/S{a['scene']}_i{a['image_index']}.png", tenant_id)
    # New picture → the old clip is stale: clear it so the scene re-animates clean.
    # image_model records WHICH model actually drew it (may differ from the override
    # if a content-policy/failure fallback fired) — the truth the badge shows.
    await execute(
        "UPDATE assets SET image_url=$1, drive_image_url=$1, video_clip_url=NULL, "
        "video_status=NULL, image_model=$2, updated_at=now() WHERE id=$3 AND tenant_id=$4",
        stable, model_used, asset_id, tenant_id)
    # generation_ledger (checklist §0.3b/C08, priced per-model in §0.3c/C09):
    # one row per redrawn picture. model_used is always a single, known
    # model here (no batch ambiguity) — price with its real rate.
    # kie_task_id (C16c): box[0] is the first task id created across any
    # retries/fallback attempts inside generate_scene_image_for_model — same
    # convention the clip path uses (task_id_box[0], pipeline_executor.py
    # ~L12383) — giving the dedup index (migration 093) real teeth here.
    from actions import picture_price_for
    picture_cost = picture_price_for(model_used)
    await record_ledger_entry(
        tenant_id=tenant_id, video_id=video_id, stage="image", model=model_used,
        units=1, unit_cost=picture_cost, actual_cost=picture_cost,
        kie_task_id=(task_id_box[0] if task_id_box else None),
    )
    # `cost` (C1b, feat/per-card-parallel-clips): additive field so
    # redraw_asset_images' fan-out below can sum a real total for its own
    # completion message, same way run_clip_generation totals `cost` across
    # its per-clip results — existing callers only ever read `status`/
    # `message`/`error` (test_redraw_style_parity.py, routes/pipeline.py,
    # routes/chat.py, pipeline_executor.py's content-policy retry), so this
    # is a pure addition, never a behavior change for any of them.
    return {"status": "completed", "message": f"Picture S{a['scene']}.{a['image_index']} redrawn",
            "cost": picture_cost}


# --- C1b (feat/per-card-parallel-clips): concurrent multi-picture redraw ----
# fan-out. Mirrors pipeline_executor.run_clip_generation's asset-level claim
# + Semaphore(CONCURRENCY) + asyncio.gather pattern (chunk C1), applied to
# redraw_asset_image instead of clip generation. routes/pipeline.py's
# "redraw_manual" lane (mirroring "clip_manual") is what lets several of
# these run concurrently on one video without 409-ing each other; THIS
# function is what stops two overlapping runs from both redrawing (and
# double-charging for) the SAME picture — see redraw_asset_claims.py's
# module docstring for the full reasoning.
IMAGE_CONCURRENCY_DEFAULT = 6


async def redraw_asset_images(video_id, tenant_id, asset_ids, progress=None):
    """Redraw one OR several pictures — the manual-run entry point every
    caller (route) uses regardless of how many ids were requested, so the
    claim guard below applies UNCONDITIONALLY (mirrors
    ``run_clip_generation``: the clip-side claim always runs whether the
    caller passed a singular ``asset_id`` or a multi-id ``asset_ids``, never
    only for 2+). Every id is scoped to THIS (video_id, tenant_id) via
    ``id = ANY($3::uuid[])`` (never trusts a caller-supplied id list
    blindly — same scoping ``run_clip_generation``'s candidate query uses),
    claimed via ``redraw_asset_claims`` before any paid call, and each row
    calls the UNCHANGED single-asset ``redraw_asset_image`` — no redraw
    logic is duplicated here, only the claim/fan-out/aggregate wrapper
    around it.

    A single requested id that clears the claim is a direct passthrough:
    calls ``redraw_asset_image`` once and returns its result UNCHANGED (no
    aggregate wrapping), so a lone Redraw tap gets the exact same
    status/message/error/cost shape it always has — the claim step is the
    ONLY new thing in that path. 2+ ids fan out concurrently under an
    ``IMAGE_CONCURRENCY`` semaphore (default 6, same default value as
    clips' ``CLIP_CONCURRENCY`` — Kie queues server-side on the same
    account) and return an aggregate result.

    One asset already claimed by another in-flight redraw (this call or a
    different overlapping one) is silently skipped, never redrawn twice —
    reported back as ``in_progress_elsewhere``, not as a failure. A genuine
    per-picture error (bad prompt, generation failure) is caught so it
    never aborts the other pictures in the same batch — reported as
    ``failed``, same shape ``run_clip_generation`` uses for its own
    per-clip failures.
    """
    def _p(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    ids = list(dict.fromkeys(a for a in (asset_ids or []) if a))
    if not ids:
        return {"status": "failed", "error": "no picture ids given to redraw"}

    rows = await fetch_all(
        "SELECT id, scene, image_index FROM assets WHERE video_id=$1 AND tenant_id=$2 "
        "AND id = ANY($3::uuid[])", video_id, tenant_id, ids)
    if not rows:
        return {"status": "failed",
                "error": ("picture not found" if len(ids) == 1
                           else "no matching pictures found for the requested ids")}

    # --- asset-level claim guard (redraw_asset_claims) ----------------------
    # Claimed synchronously, before any paid call — the window where two
    # overlapping calls could both believe they own the same id is zero
    # (see redraw_asset_claims.py's module docstring for why this needs no
    # lock inside one process). Applies even for a single id: two SEPARATE
    # lone-card taps racing on the SAME asset must not both redraw it, now
    # that the route's "redraw_manual" lane no longer 409s a second manual
    # redraw against the first.
    candidate_ids = [r["id"] for r in rows]
    won_ids = set(redraw_asset_claims.claim(tenant_id, video_id, candidate_ids))
    already = [r for r in rows if r["id"] not in won_ids]
    todo = [r for r in rows if r["id"] in won_ids]
    if already:
        already_labels = ", ".join(f"S{r['scene']}.{r['image_index']}" for r in already)
        _p(f"Skipping {len(already)} picture(s) already redrawing in another run: {already_labels}")
    if not todo:
        msg = ("This picture is already being redrawn by another in-flight run."
               if len(ids) == 1 else
               "Already redrawing — every requested picture here is already being "
               "generated by another in-flight run.")
        return {"status": "completed", "message": msg, "redrawn": 0, "failed": 0,
                "cost": 0.0, "in_progress_elsewhere": len(already)}

    if len(ids) == 1 and len(todo) == 1:
        # Single-target passthrough — see docstring. Still went through the
        # claim step above; only the RESULT SHAPE is byte-identical to the
        # pre-C1b solo redraw, not the safety story (which is now guarded).
        only = todo[0]
        try:
            return await redraw_asset_image(video_id, tenant_id, only["id"], progress=progress)
        finally:
            redraw_asset_claims.release(tenant_id, video_id, [only["id"]])

    sem = asyncio.Semaphore(int(os.getenv("IMAGE_CONCURRENCY", str(IMAGE_CONCURRENCY_DEFAULT))))
    redrawn = 0
    failed = 0
    cost_total = 0.0
    errors: list = []

    async def _one(r):
        nonlocal redrawn, failed, cost_total
        try:
            async with sem:
                res = await redraw_asset_image(video_id, tenant_id, r["id"], progress=progress)
            if res.get("status") == "completed":
                redrawn += 1
                cost_total += res.get("cost") or 0.0
            else:
                failed += 1
                errors.append(f"S{r['scene']}.{r['image_index']}: {res.get('error') or 'redraw failed'}")
        except Exception as e:  # noqa: BLE001 — one bad row must never abort the batch
            failed += 1
            errors.append(f"S{r['scene']}.{r['image_index']}: {e}")
        finally:
            # Release THIS row's claim the instant its own work finishes
            # (success, failure, or exception) — not at the end of the
            # whole batch — so an overlapping run can pick it up again as
            # soon as possible. Idempotent; the batch-level release below
            # is a no-op backstop in the normal case.
            redraw_asset_claims.release(tenant_id, video_id, [r["id"]])

    try:
        await asyncio.gather(*[_one(r) for r in todo])
    finally:
        # Backstop: every row above already released its own claim; this
        # only matters if something aborts the gather itself before every
        # _one() runs (e.g. a cancellation).
        redraw_asset_claims.release(tenant_id, video_id, won_ids)

    msg = (f"Redrew {redrawn} picture(s) (${cost_total:.2f})"
           + (f" — {failed} failed: {'; '.join(errors)[:400]}" if failed else "")
           + (f" — {len(already)} already redrawing in another run" if already else ""))
    return {"status": "completed" if redrawn or not failed else "failed",
            "message": msg, "redrawn": redrawn, "failed": failed, "cost": cost_total,
            "in_progress_elsewhere": len(already),
            "error": msg if failed and not redrawn else None}


_MOTION_SYSTEM = (
    "You are a film director writing the CAMERA MOTION for grok-imagine image-to-video. Each shot "
    "already has a finished still, and its spoken line (if any) is assigned elsewhere — your ONLY job "
    "is to direct how the camera and the subject MOVE. Write ONE vivid, specific instruction per shot, "
    "precise enough that there is no guesswork.\n"
    "1) CAMERA: an UNTAGGED shot (no CAMERA LOCKED marker and no CAMERA: static marker) defaults to a "
    "Fixed lens — hold the camera static and let the subject carry the motion; do NOT invent a camera "
    "move for it. Only a shot tagged (CAMERA LOCKED: ...) gets a camera move (see rule 4) — when you "
    "write one, say where it starts and where it ends — push-in / dolly-in, pull-back, pan left/right, "
    "tilt up/down, tracking, orbit/arc, dolly-zoom, slow zoom, or handheld sway — and vary the move shot "
    "to shot; never repeat the same move twice in a row. Add 'Unfixed lens' when the camera moves, "
    "'Fixed lens' when it holds.\n"
    "2) KEEP THE SUBJECT IN FRAME: the main character stays visible for the WHOLE shot. If the move "
    "reveals something (a window, the water, an object), keep the character in frame while it does — "
    "never pan or tilt away onto an empty detail and lose them. Name the character and the SPECIFIC, "
    "physical thing they do: an expression change, a gesture, a head turn, eyes lifting, a breath — "
    "real and watchable, not a mood. ANY character described in the shot is ALREADY in the room — the "
    "still was drawn with them there. This applies even on a SILENT/ESTABLISH beat 'before anyone "
    "speaks': that phrase describes the TIMING of dialogue, not who is in the frame. NEVER write a "
    "character as absent, arriving, or about to enter (no 'empty sofa where X will sit', no 'before X "
    "arrives', no 'no one is here yet') — the camera may only move; it may never change who is in the "
    "room. Characters in the frame must be VISIBLE FROM THE FIRST FRAME TO THE LAST: never write a "
    "move that arrives at, reveals, or settles on a character (no 'sweeping past the decor before "
    "settling on X') — a camera path that starts on scenery and travels toward a character makes the "
    "video model stage the start without them and pop them in mid-shot.\n"
    "3) A shot tagged (SPEAKING: <Name>) shows that character delivering their line — frame their face "
    "or upper body and give a small, natural speaking gesture. DO NOT write the words; the line is added "
    "automatically. A shot with NO tag is silent — camera move + ONE small motion, NO people added.\n"
    "4) A shot tagged (CAMERA LOCKED: ...) had its still image COMPOSED for exactly that camera move — "
    "open your line with that move verbatim (you may add where it starts and ends), and NEVER substitute "
    "a different move. A shot tagged (CAMERA: static) holds a Fixed lens — subject motion only.\n"
    "Write like a director calling the shot: concrete blocking, plain language. BANNED: the words gentle/"
    "soft/subtle/faint/slight, mood words (cinematic/dramatic/emotional), negatives ('no ...', 'avoid "
    "...'), repainting the static scene already in the frame, and ANY quoted dialogue. Under 50 words "
    "each.\n"
    "Output ONLY the numbered camera-motion lines, one per shot, in order — nothing else.")


def _parse_numbered(text: str, count: int) -> list:
    """Pull 'N. <line>' motion lines out of the model's reply, padded/truncated to count."""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*\d+[\.\):]\s*(.+)$", line.strip())
        if m:
            out.append(m.group(1).strip())
    return (out + [""] * count)[:count]


# A clip lip-syncs ONE character, so every dialogue turn (each speaker change)
# needs its OWN shot. Count the turns in a scene's narration so coverage draws
# at least one moment per turn — otherwise the motion-writer runs out of shots
# and crams two speakers onto one (which Grok can't voice).
_SPEAKER_RE = re.compile(r"(?m)^\s*([A-Z][A-Za-z .'-]{0,24}):\s+\S")


# A shot's pre-assigned dialogue is stored as `Speaker: "line"`. The writer's
# camera-motion output should carry no dialogue, but strip any it adds anyway
# before we append the authoritative assigned line.
_EMBED_SAYS_RE = re.compile(r'\b[A-Z][A-Za-z .\'-]{0,24}\s+says\b', re.IGNORECASE)
_ASSIGNED_RE = re.compile(r'^\s*([^:"\n]+?)\s*:\s*"(.+)"\s*$', re.DOTALL)


def _strip_embedded_line(prompt: str) -> str:
    """Camera-motion text with any stray `<Name> says …: "line"` the writer added
    cut off (the real line is appended from the coverage-assigned dialogue)."""
    m = _EMBED_SAYS_RE.search(prompt or "")
    base = (prompt or "")[:m.start()] if m else (prompt or "")
    return base.strip().rstrip(".").strip()


def _split_assigned(assigned: str):
    """(speaker, text) from a stored `Speaker: "line"`, or (None, None)."""
    m = _ASSIGNED_RE.match(assigned or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else (None, None)


# Script writers emit markdown-bold speaker labels (`**Marco:** ¡Espera!`) —
# normalize to plain `Marco:` before parsing, or a dialogue scene reads as
# ZERO turns and storyboards as narration (no lip-synced shot per line).
# Covers **Name:** / **Name**: / *Name:* variants.
_BOLD_SPEAKER_RE = re.compile(
    r"(?m)^(\s*)\*{1,3}\s*([A-Z][A-Za-z .'-]{0,24})\s*(?::\s*\*{1,3}|\*{1,3}\s*:)\s*")


def _normalize_speaker_lines(text: str) -> str:
    return _BOLD_SPEAKER_RE.sub(r"\1\2: ", text or "")


def _dialogue_turns(scene_text: str):
    """Ordered [(speaker, text), ...] dialogue turns. Empty for a scene with no
    tagged dialogue. DELEGATES to the planner-checklist splitter
    (storyboard.coverage._scene_turns) so the checklist the planner receives,
    the shot budget, and the line reconcile all count the SAME turns — two
    diverging copies of this logic is exactly how lines ended up on the wrong
    shots (2026-07-02). Same-speaker lines separated by narration are separate
    turns; only adjacent lines merge."""
    av_turns = [
        (match.group("speaker").strip(), match.group("text").strip())
        for match in re.finditer(
            r"(?m)^DIALOGUE (?P<speaker>[A-Za-z][A-Za-z .'-]{0,40}) "
            r"\[[a-z]{2,8}(?: \| pair=[A-Za-z0-9_-]+)?\]: "
            r"(?P<text>\S.*)$",
            scene_text or "",
        )
    ]
    if av_turns:
        return av_turns
    from storyboard.coverage import _scene_turns
    return _scene_turns(scene_text or "")


def _dialogue_turn_count(scene_text: str) -> int:
    """Number of speaker TURNS in a scene. 0 for pure narration/visual."""
    return len(_dialogue_turns(scene_text))


def _reconcile_moment_dialogue(moments, scene_text):
    """Guarantee every script turn is voiced exactly once, in order, VERBATIM —
    while RESPECTING which moments the planner built to speak.

    The planner marks each speaking moment with a `LINE:` row (parse_coverage
    puts it on moment.speaker/.line) and frames that moment's master on the
    speaker. The old backstop ignored those markers and stamped turns onto the
    first N non-INSERT masters BY POSITION — a scene opening with two silent
    moments pushed every line ~2 shots early (found live 2026-07-02: Sofia's
    line on a Marco gate shot, lines on "Silent" moments, the shots built to
    speak left empty).

    Now: walk the script turns in order; each goes to the planner-marked
    speaking moment with the SAME speaker whose PLANNED LINE TEXT covers the
    turn's words (the planner declared which words that shot performs — trust
    the text, not just the order, so a checklist/turn-count mismatch can't
    drift lines onto later moments). Order is the fallback when text doesn't
    settle it, monotonic so audio and visual order can't cross. The moment's
    line text is replaced with the turn's verbatim script words (the planner
    may paraphrase). Two turns whose planned text points at the same master
    share it (the planner planned that master to speak both). A turn with no
    home folds onto the previous placement for its speaker (or the last
    placement overall) so no line is ever lost; planner-marked moments that
    get no turn go SILENT (a hallucinated LINE never survives); moments the
    planner left silent STAY silent. If the planner marked nothing at all,
    fall back to the old positional stamp — minus moments whose summary says
    they're silent."""
    turns = _dialogue_turns(scene_text)
    for m in moments:
        m["_planned_speaker"] = (m.get("speaker") or "").strip()
        m["_planned_line"] = (m.get("line") or "").strip()
        m["speaker"], m["line"] = None, None
    if not turns:
        for m in moments:
            m.pop("_planned_speaker", None), m.pop("_planned_line", None)
        return moments

    def _is_insert(m):
        return (m.get("master", {}).get("shot_type") or "").upper() == "INSERT"

    marked = [i for i, m in enumerate(moments)
              if m["_planned_speaker"] and m["_planned_line"] and not _is_insert(m)]

    placements: dict[int, tuple[str, list]] = {}  # moment idx -> (speaker, [texts])

    def _place(idx, spk, txt):
        cur = placements.get(idx)
        placements[idx] = (cur[0] if cur else spk, (cur[1] if cur else []) + [txt])

    if marked:
        from clip_dialogue import norm as _tnorm

        def _planned_covers(i, txt):
            """Does moment i's planner-declared line contain this turn's words?
            Same containment semantics as the clip/render matchers."""
            planned = _tnorm(moments[i]["_planned_line"])
            t = _tnorm(txt)
            if not planned or not t:
                return False
            if t in planned or planned in t:
                return True
            for sent in re.split(r"[.!?…]+", txt):
                ns = _tnorm(sent)
                if ns and len(ns.split()) >= 3 and ns in planned:
                    return True
            return False

        last_idx = -1
        last_for_speaker: dict = {}
        for spk, txt in turns:
            same = [i for i in marked
                    if moments[i]["_planned_speaker"].lower() == spk.lower()]
            # Free for this turn = unplaced, or already placed with the SAME
            # speaker (a master the planner gave two adjacent turns).
            def _free(i):
                return i not in placements or placements[i][0].lower() == spk.lower()
            # 1) The planner's own text says which shot performs these words.
            cand = next((i for i in same if i >= last_idx
                         and _planned_covers(i, txt) and _free(i)), None)
            if cand is None:
                cand = next((i for i in same
                             if _planned_covers(i, txt) and _free(i)), None)
            # 2) Text didn't settle it — next unplaced same-speaker moment, in order.
            if cand is None:
                cand = next((i for i in same if i not in placements and i > last_idx), None)
            if cand is None:
                cand = next((i for i in same if i not in placements), None)
            if cand is not None:
                last_idx = max(last_idx, cand)
                last_for_speaker[spk.lower()] = cand
                _place(cand, spk, txt)
            else:
                # No planner moment for this turn — fold, never lose a line:
                # onto this speaker's previous shot, else the last placed shot,
                # else the first marked moment.
                fold = last_for_speaker.get(spk.lower())
                if fold is None:
                    fold = max(placements) if placements else marked[0]
                _place(fold, spk, txt)
    else:
        # Legacy plans with no LINE rows: positional stamp over masters that
        # are not INSERTs and whose summary doesn't declare itself silent.
        eligible = [i for i, m in enumerate(moments) if not _is_insert(m)
                    and not (m.get("summary") or "").lower().lstrip(" -—*").startswith("silent")]
        for k, (spk, txt) in enumerate(turns):
            if k < len(eligible):
                _place(eligible[k], spk, txt)
            elif eligible:
                _place(eligible[-1], spk, txt)

    for idx, (spk, texts) in placements.items():
        moments[idx]["speaker"] = spk
        moments[idx]["line"] = " ".join(texts).strip()
    for m in moments:
        m.pop("_planned_speaker", None), m.pop("_planned_line", None)
    return moments


def _visual_cue_count(scene_text: str) -> int:
    """Count meaningful sentence/cue units, folding trivial fragments.

    Investigative narration often uses punchy one- or two-word fragments.
    Treating every fragment as a paid picture makes the edit choppy; attach
    fragments under five words to a neighboring cue while retaining normal
    sentences and semicolon-separated visual turns as their own units.
    """
    pieces = re.split(r"(?<=[.!?;])\s+|\n+", (scene_text or "").strip())
    count = 0
    leading_fragment_words = 0
    for piece in pieces:
        words = re.findall(r"\b[\w'-]+\b", piece)
        if not words:
            continue
        if len(words) < 5:
            if count == 0:
                leading_fragment_words += len(words)
            continue
        count += 1
        leading_fragment_words = 0
    return max(1, count if count else (1 if leading_fragment_words else 0))


def _production_density_mode(production_style_snapshot) -> str:
    """Read the persisted knob value from JSONB dict/string shapes."""
    value = production_style_snapshot
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return ""
    if not isinstance(value, dict):
        return ""
    knobs = value.get("knobs")
    if not isinstance(knobs, dict):
        return ""
    density = knobs.get("image_density")
    return str(density.get("mode") or "") if isinstance(density, dict) else ""


def _coverage_shape(
    scene_text: str,
    dialogue_audio: str = "voice_over",
    production_style_snapshot=None,
    section_contract=None,
):
    """(max_moments, angles_min, angles_max, max_frames) — THE per-scene shot
    budget (D1). Every image pathway funnels through here, so this one
    function is the pacing policy AND the cost ceiling. Two channel modes
    (Ryan's rule, 2026-07-02):

    ECHO / voice_over dialogue (e.g. the bilingual teaching channel, where
    the direction is already rich and hard to steer): shot count is paced to
    the scene's RUNTIME — one moment per ~8s of speech (COVERAGE_PACING_
    SECONDS), never fewer than one master per speaker turn. Angles 0–2 and
    EARNED (the planner's motivated-angle rule fires on angles_min=0):
    reactions, reveals, location bridges — not variety padding. Total frames
    hard-capped at 2× the paced count, ceiling COVERAGE_MAX_FRAMES (40).
    A 2:19 scene ⇒ ~18 moments, ≤36 frames, ~4-8s per shot.

    GROK-NATIVE dialogue (the pure-English speaking channels): the full
    cinematic multi-angle coverage — Pixar-grade cutting needs the extra
    angles. One master per turn + narration-scaled inserts, 1–2 angles per
    moment, SCENE_FRAME_BUDGET (18) as the runaway-planner brake.

    Non-dialogue scene → the classic 3-moment coverage, 2–3 matched angles.
    Lines are never lost regardless of caps — _reconcile_moment_dialogue
    folds overflow turns onto that speaker's shot."""
    if section_contract is not None:
        expected = section_contract.get("expected_still_images")
        density = section_contract.get("image_density")
        if (
            type(expected) is not int
            or expected < 1
            or not isinstance(density, dict)
            or density.get("mode") not in {"dialogue_shape", "visual_cue"}
            or not isinstance(density.get("target_per_minute"), (int, float))
            or isinstance(density.get("target_per_minute"), bool)
            or density["target_per_minute"] <= 0
        ):
            raise ValueError("Invalid exact Custom Film coverage count")
        # The approved BOM is the hard provider ceiling and floor. Density
        # materially changes this value upstream; one master per planned cue
        # makes the shared coverage planner target exactly that many frames.
        return expected, 0, 0, expected
    turns = _dialogue_turn_count(scene_text)
    if _production_density_mode(production_style_snapshot) == "visual_cue":
        cues = max(_visual_cue_count(scene_text), turns + (1 if turns else 0))
        # One master and no cosmetic angles per meaningful cue: one planned
        # frame becomes one image and one animated clip.
        return cues, 0, 0, cues
    if turns < 2:
        return 3, 2, 3, None  # visual/narration scene — ≤12 frames (3 × master+3)
    narration_words = sum(
        len(line.split())
        for line in _normalize_speaker_lines(scene_text or "").splitlines()
        if line.strip() and not re.match(r"^\s*[A-Z][A-Za-z .'-]{0,24}:\s+\S", line)
    )
    # PURE-DIALOGUE scene (the couple format: every line a turn, no narrator):
    # one establishing + one master per line, nothing else — in BOTH modes.
    # voice_over: silent angles have zero clock in the timeline (Short #1
    # gate: 12 of 35 frames unplaceable). grok_native: the stitch plays
    # EVERY clip, so each extra frame ADDS runtime — 35 frames turned a 55s
    # short into 2+ minutes, and 18 moments under 24 turns folded two lines
    # into one mouth (EP2 gate). The rich multi-angle shape below is for
    # narration-driven scenes, not wall-to-wall dialogue.
    if narration_words < 15:
        masters = turns + 1  # one establishing + one master per line
        # C8 fix (a): max_frames used to equal `masters` exactly (zero
        # headroom). enforce_reaction_insert_floors then found the scene
        # ALREADY at its frame cap with angles_max=0 — i.e. no angle-role
        # shot anywhere to convert (_find_convertible_angle only ever
        # repurposes an ANGLE, never a master) — so every reaction/insert/
        # re-establish floor came back "at the cap with no safe shot to
        # convert" and went unmet. Live proof: Spanish Class scene 2 dry run
        # (35 turns, 36 masters) wanted 8 reactions + 5 inserts, placed 0
        # reactions + 2 inserts. The floor validator's ADD path (append a
        # new angle to a moment) only fires when max_frames leaves headroom
        # ABOVE the master count — fund that headroom here, derived from the
        # SAME per-shot ratios the validator itself applies (never a fresh
        # magic number): ~1 reaction per _REACTION_TURNS_PER_SHOT turns, ~1
        # insert per _INSERT_SHOTS_PER_ONE shots, ~1 re-establish per
        # _REESTABLISH_SHOTS_PER_ONE shots. max_moments (element 0, below)
        # is UNCHANGED — masters still one per line, nothing added there;
        # only max_frames (element 3) grows so floors can ADD instead of
        # being forced into a conversion that can never succeed.
        headroom = (
            max(1, turns // _REACTION_TURNS_PER_SHOT)
            + max(0, masters // _INSERT_SHOTS_PER_ONE)
            + max(0, masters // _REESTABLISH_SHOTS_PER_ONE)
        )
        # Safety valve: COVERAGE_MAX_FRAMES is the echo/voice_over branch's
        # own runaway-planner ceiling (below), but that branch's shot count
        # is PACED TO RUNTIME (typically well under 40) — pure-dialogue's
        # one-master-per-turn law can already sit close to (or past) that
        # ceiling on masters ALONE (this scene: 36 of 40), so reusing it as
        # a hard cap on TOTAL frames here would starve the very floors this
        # fix funds. Instead cap the EXTRA headroom on its own dial
        # (COVERAGE_FLOOR_HEADROOM_CAP, default 20 — comfortably covers this
        # scene's real ~11-shot need with room to spare) so a pathological
        # scene (hundreds of turns) still can't make the floor validator add
        # an unbounded number of shots.
        headroom = min(headroom, int(os.getenv("COVERAGE_FLOOR_HEADROOM_CAP", "20")))
        return masters, 0, 0, masters + headroom
    if (dialogue_audio or "voice_over") == "grok_native":
        inserts = max(2, narration_words // 20)
        return min(turns + inserts, SCENE_FRAME_BUDGET), 1, 2, None
    # voice_over echo format: pace to runtime. The frame ceiling never cuts
    # below one shot per TURN — a line is the lip-sync unit, and folding two
    # lines onto one shot puts a mouth on the wrong voice (the couple-dialogue
    # format alternates ~48 short turns in 2 minutes, above the default 40).
    pacing = float(os.getenv("COVERAGE_PACING_SECONDS", "8"))
    est_seconds = len((scene_text or "").split()) / 2.5  # ~2.5 spoken words/sec
    base = max(turns + 2, round(est_seconds / pacing))
    ceiling = max(int(os.getenv("COVERAGE_MAX_FRAMES", "40")), turns + 2)
    max_frames = min(2 * base, ceiling)
    return min(base, max_frames), 0, 2, max_frames


# --- Motion-prompt presence gate (contract-triangle GATE half of the
# SILENT/ESTABLISH absence bug, 2026-07-22 — found live: a beat's still shows
# two characters already seated, but the LLM motion writer described the
# shot ending "on the empty sofa where Ryan and Vanessa will sit"; Grok
# followed the TEXT over the picture and rendered an empty room, wasting a
# paid clip). _MOTION_SYSTEM (rule 2, above) already instructs against this;
# this is the deterministic backstop for when the model ignores it anyway.
# Pure Python, no LLM call — cheap enough to run on every shot, every time.

# Words that read as Title Case in normal motion-prompt prose but are NOT
# character names: camera vocabulary, connectives, pronouns, common set
# dressing. Kept short on purpose — the verb-whitelist in the "unknown name"
# check below is the real conservatism guard, not this list.
_MOTION_NAME_STOPWORDS = {
    "the", "a", "an", "and", "but", "or", "with", "without", "as", "at", "in",
    "on", "of", "to", "for", "from", "by", "then", "while", "before", "after",
    "during", "once", "now", "this", "that", "these", "those", "she", "he",
    "they", "we", "you", "it", "i", "camera", "fixed", "unfixed", "lens",
    "push", "pull", "slow", "slowly", "static", "dolly", "pan", "tilt",
    "track", "tracking", "orbit", "handheld", "zoom", "crane", "scene",
    "shot", "wide", "close", "medium", "master", "angle", "moment",
    "speaking", "silent", "interior", "exterior", "int", "ext", "nothing",
    "nobody", "no", "one", "room", "sofa", "couch", "chair", "table",
    "bench", "seat", "bed", "window", "door", "kitchen", "sky", "ocean",
    "coffee", "cup", "holds", "frame", "background", "foreground", "unfixed",
    "everyone", "everything", "every",
}
_MOTION_NAME_RE = re.compile(r"\b([A-Z][a-z]{2,14})\b")

# Furniture/location words a camera can "land on" — an (empty|vacant|
# unoccupied) hit near one of these describes the DESTINATION of the shot as
# absent of anyone, which is exactly the "empty sofa" bug. A bare prop
# ("empty coffee cup") is deliberately NOT in this list, so it passes.
_MOTION_DEST_WORDS = (
    "sofa", "couch", "chair", "room", "table", "bench", "seat", "bed",
    "space", "doorway", "hallway",
)
_MOTION_FURNITURE_EMPTY_RE = re.compile(
    r"\b(empty|vacant|unoccupied)\b[^.]{0,25}\b(" + "|".join(_MOTION_DEST_WORDS) + r")\b"
    r"|\b(" + "|".join(_MOTION_DEST_WORDS) + r")\b[^.]{0,25}\b(?:is|sits?|stands?)\b"
    r"[^.]{0,15}\b(empty|vacant|unoccupied)\b",
    re.IGNORECASE)
# "no one"/"nobody" claims the frame is peopleless — EXCEPT when followed by a
# change-of-state verb ("no one enters or exits", "no one leaves"): that's a
# presence-PRESERVING clause (the class-(d) safe fallback text uses it
# verbatim) and must never trip the gate.
_MOTION_NO_ONE_RE = re.compile(
    r"\b(no\s*one|nobody)\b"
    r"(?!\s+(?:else\b|new\b|enters?\b|exits?\b|leaves?\b|arrives?\b|joins?\b|"
    r"steps?\b|comes?\b|walks?\b|is\s+added\b))",
    re.IGNORECASE)
_MOTION_ANTICIPATION_VERB = r"(?:sits?|sit down|arrives?|enters?|walks? in|joins?)"
_MOTION_ACTING_VERBS = (
    "says", "turns", "looks", "smiles", "sits", "walks", "enters", "waves",
    "leans", "nods", "glances", "steps",
)

# Class (d) — reveal-traverse / delayed entrance (found live on prod real
# frames, 2026-07-22): shot 1's gate-corrected prompt read "Camera trucks
# right... sweeping past the balloons and party decor before settling on
# Ryan and Vanessa already standing at the coffee table." Grok (image+text
# conditioned) staged the camera-start portion WITHOUT the characters and
# popped them in ghost-style when the camera arrived. Lesson: when the still
# shows characters, ANY camera path whose START is scenery and whose END is
# a character is a reveal, and it will ghost — the characters must be
# visible from frame 1. Conservative trigger = BOTH halves present:
# traverse-start language AND an arrival phrase targeting a PRESENT
# character. A traverse over a scenery-only shot (no characters in
# image_prompt), or a drift with no arrival phrase, passes untouched.
_MOTION_TRAVERSE_START_RE = re.compile(
    r"\b(?:sweep(?:s|ing)?\s+(?:past|across|over)|pan(?:s|ning)?\s+across|"
    r"track(?:s|ing)?\s+across|truck(?:s|ing)?\s+(?:left|right)|"
    r"start(?:s|ing)?\s+(?:on|from|at)|begin(?:s|ning)?\s+(?:on|from|at)|"
    r"open(?:s|ing)?\s+on|glid(?:es|ing)\s+(?:past|across|over)|"
    r"drift(?:s|ing)?\s+(?:past|across)|mov(?:es|ing)\s+(?:past|across))\b",
    re.IGNORECASE)
_MOTION_ARRIVAL_PHRASE = (
    r"(?:(?:before\s+)?settl(?:es?|ing)\s+(?:on|upon)|end(?:s|ing)\s+on|"
    r"land(?:s|ing)\s+on|arriv(?:es?|ing)\s+(?:at|on)|to\s+reveal|"
    r"reveal(?:s|ing)?|toward)"
)


def _reveal_arrival(vp: str, image_names: set):
    """(name, matched_text) when the motion text's camera path ARRIVES on a
    character the image already shows — 'before settling on Ryan', 'ending
    on Vanessa', 'revealing Marco', 'toward Priya'. None when every arrival
    target is scenery/props (arriving on an object is legal): the gap between
    the arrival phrase and the name must not cross a clause boundary (as/
    while/when/where), so 'settling on the cake as Ryan ... stays in frame'
    keeps the CAKE as the target and passes."""
    # No sentence-end and no clause-boundary word between the arrival phrase
    # and the character name — the name must be the arrival's own target.
    gap = r"(?:(?!\b(?:as|while|when|where)\b)[^.;,]){0,40}"
    for name in image_names:
        pat = re.compile(
            rf"\b{_MOTION_ARRIVAL_PHRASE}\b\s{gap}\b{re.escape(name)}\b",
            re.IGNORECASE)
        m = pat.search(vp)
        if m:
            return name, m.group(0)
    return None


def _motion_names(text: str) -> set:
    """Candidate character names (Title Case tokens minus common camera/
    scene vocabulary) found in a prompt."""
    return {m.group(1) for m in _MOTION_NAME_RE.finditer(text or "")
            if m.group(1).lower() not in _MOTION_NAME_STOPWORDS}


# REACTION-shot subject-swap (found live by a parallel audit, 2026-07-22,
# 4/4 occurrences on the audited scene): storyboard.coverage's REACTION
# placement (skills/video-pipeline/storyboard/coverage.py ~L1160) writes
# `"(SETUP {fam})(REACTION) CU on {listener}, listening to {speaker}'s line,
# same instant."` — the shot is a CU framed on the LISTENER (the reactor),
# with the speaker off-frame. _write_motion_prompts's `_shot()` builder falls
# back to this truncated image_prompt snippet whenever sentence_text is null
# (true for REACTION rows), and the motion-writer LLM misreads "listening to
# Vanessa's line" as an instruction to describe Vanessa — writing her hands/
# gesture into a shot that is actually framed on Ryan.
_REACTION_DESC_RE = re.compile(
    r"\bCU on\s+([A-Za-z][A-Za-z .'-]{1,30}?),\s*listening to\s+"
    r"([A-Za-z][A-Za-z .'-]{1,30}?)'s line\b", re.IGNORECASE)
_REACTION_ACTION_VERBS = (
    "press(?:es)?", "clasp(?:s)?", "reach(?:es)?", "grip(?:s)?", "tap(?:s)?",
    "drum(?:s)?", "raise(?:s)?", "lower(?:s)?", "move(?:s)?", "gesture(?:s)?",
    "wave(?:s)?", "lean(?:s)?", "shift(?:s)?", "curl(?:s)?", "tighten(?:s)?",
    "flatten(?:s)?", "rest(?:s)?", "fold(?:s)?", "clench(?:es)?", "drop(?:s)?",
    "run(?:s)?", "brush(?:es)?", "fidget(?:s)?", "grab(?:s)?", "squeeze(?:s)?",
)


def _reaction_pair(image_prompt: str):
    """(reactor, speaker) from a "CU on X, listening to Y's line" REACTION-
    shot description, or None if image_prompt isn't a reaction shot."""
    m = _REACTION_DESC_RE.search(image_prompt or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def _is_gesture_actor(text: str, name: str) -> bool:
    """True if `name` (or "name's <noun>") is the grammatical SUBJECT of a
    physical gesture verb in `text` — e.g. "Vanessa's hands press flat on
    the table" or "Vanessa reaches across". Naming someone as the OBJECT of
    a gaze ("eyes locked on Vanessa") never matches — gaze verbs aren't in
    the action-verb list, so watching the speaker stays legal."""
    esc = re.escape(name)
    verbs = "|".join(_REACTION_ACTION_VERBS)
    return bool(re.search(rf"\b{esc}(?:'s\s+\w+)?\s+(?:{verbs})\b", text or "", re.IGNORECASE))


def gate_motion_prompt(video_prompt: str, image_prompt: str) -> str | None:
    """Deterministic check: does `video_prompt` contradict a character the
    shot's `image_prompt` already shows in the frame? Returns a short
    violation reason on a CLEAR contradiction, else None.

    Conservative by design (task law: flag clear contradictions, don't
    over-block legitimate text) — a prop mention ("empty coffee cup") or
    plain camera-only language must always pass:
      (a) absence/anticipation language tied to a character who is present
          in image_prompt — "empty/vacant/unoccupied <furniture/room>",
          "no one"/"nobody" (only when the image has people to contradict),
          or a present character described as "will sit/arrive/enter",
          "before <Name> arrives", "about to enter".
      (b) video_prompt names a character not present in image_prompt at
          all AND writes them acting (a verb like "turns"/"enters"/"says") —
          the writer inventing a person the still never drew.
      (c) REACTION-shot subject swap — image_prompt is a "CU on X, listening
          to Y's line" reaction shot (X is framed, Y is off-frame), and
          video_prompt makes Y the grammatical actor of a physical gesture
          while X never acts at all. X may still be named as the gaze target
          ("eyes locked on Y") — only Y acting instead of X is a violation.
      (d) reveal-traverse / delayed entrance — image_prompt has characters,
          and video_prompt writes a camera path that STARTS on scenery
          (sweeping past / panning across / starting on ...) and ARRIVES on
          a present character (before settling on / ending on / revealing /
          toward <char>). Grok ghosts the characters in mid-shot. Both
          halves must be present to trigger; a traverse over a
          scenery-only shot, or arrival on an object, always passes.
    """
    vp = (video_prompt or "").strip()
    if not vp:
        return None
    image_names = _motion_names(image_prompt or "")

    pair = _reaction_pair(image_prompt or "")
    if pair:
        reactor, speaker = pair
        if _is_gesture_actor(vp, speaker) and not _is_gesture_actor(vp, reactor):
            return (f"REACTION shot framed on {reactor}, but the motion text describes "
                     f"{speaker} (off-frame) acting instead")

    if image_names and _MOTION_TRAVERSE_START_RE.search(vp):
        hit = _reveal_arrival(vp, image_names)
        if hit:
            return (f"reveal-traverse: camera starts on scenery and arrives on {hit[0]} "
                     f"({hit[1]!r}) — characters in the still must be visible from the "
                     f"very first frame, never revealed by the move")

    m = _MOTION_FURNITURE_EMPTY_RE.search(vp)
    if m and image_names:
        return (f"describes an empty/vacant destination ({m.group(0)!r}) while the image "
                 f"already shows {', '.join(sorted(image_names))} present")

    if image_names and _MOTION_NO_ONE_RE.search(vp):
        return (f"says {_MOTION_NO_ONE_RE.search(vp).group(0)!r} is present while the image "
                 f"already shows {', '.join(sorted(image_names))}")

    for name in image_names:
        esc = re.escape(name)
        pat = re.compile(
            rf"\b{esc}\b[^.]{{0,60}}\bwill\s+{_MOTION_ANTICIPATION_VERB}\b"
            rf"|\bwill\s+{_MOTION_ANTICIPATION_VERB}\b[^.]{{0,60}}\b{esc}\b"
            rf"|\bbefore\s+{esc}\b[^.]{{0,20}}\b(?:arrives?|enters?|sits?|walks? in|joins?)\b"
            rf"|\babout to\s+{_MOTION_ANTICIPATION_VERB}\b[^.]{{0,60}}\b{esc}\b"
            rf"|\b{esc}\b[^.]{{0,60}}\babout to\s+{_MOTION_ANTICIPATION_VERB}\b",
            re.IGNORECASE)
        m2 = pat.search(vp)
        if m2:
            return (f"describes {name} as not-yet-arrived ({m2.group(0)!r}) while the image "
                     f"already shows them present")

    unknown = _motion_names(vp) - image_names
    for name in unknown:
        verb_pat = re.compile(rf"\b{re.escape(name)}\b\s+(?:{'|'.join(_MOTION_ACTING_VERBS)})\b",
                               re.IGNORECASE)
        if verb_pat.search(vp):
            return f"names {name!r} acting in the shot, but the image_prompt has no {name}"
    return None


# Class-(d) safe fallback for shots whose still has CHARACTERS: an explicit
# first-frame-visibility clause, never a traverse. The truck_right camera-lock
# template's own "pan across the scene" wording is what SEEDED the live
# ghost-entrance failure — a traverse template must never be handed to a shot
# with people in it.
_CHARACTER_SAFE_FALLBACK = (
    "Camera holds nearly still with the slightest drift. Everyone in the still is "
    "fully visible from the very first frame and remains in frame for the entire "
    "shot; no one enters or exits the frame. Subject motion only."
)


def _camera_lock_fallback_text(camera_movement: str, image_prompt: str = "") -> str:
    """REPAIR fallback (contract-triangle third leg): when a motion line still
    fails gate_motion_prompt after one repair retry, fall back to text that
    can never claim who is/isn't in the room.

    Shot WITH characters in image_prompt: a static-hold/drift line carrying an
    explicit "fully visible from the very first frame, no one enters or exits"
    clause — NEVER the camera engine's traverse template (class (d): the
    truck_right template's "pan across the scene" phrasing ghosted the
    characters on prod real frames, 2026-07-22).

    Scenery-only shot: the camera engine's own planned move (if this shot was
    composed for one — same lookup _camera_tag() trusts for CAMERA LOCKED
    shots) or a neutral static hold."""
    if _motion_names(image_prompt or ""):
        return _CHARACTER_SAFE_FALLBACK
    raw = (camera_movement or "").strip()
    if raw and raw != "static" and "|" in raw:
        try:
            from image_prompts.engine.camera_moves import get_move
            move = get_move(raw.partition("|")[0])
            if move:
                return move.motion_prompt.rstrip(".") + ", subject motion only."
        except Exception:  # noqa: BLE001 — lookup must never break the fallback path
            pass
    return "Camera holds steady on the frame exactly as composed, subject motion only."


async def _retry_motion_prompt(claude, model, shot_line: str, violation: str) -> str:
    """REPAIR: one corrective LLM call for a SINGLE shot whose line failed the
    presence gate. Cheap (one shot, not the whole scene) and scoped tight —
    the violation reason is handed back verbatim so the model can see exactly
    what it got wrong."""
    correction = (
        "Your camera-motion line for this shot was REJECTED: "
        f"{violation}. Every character described in the shot below is ALREADY in the room — the "
        "still was drawn with them there. Rewrite ONE corrected camera-motion line for this shot "
        "only. Never describe a character as absent, arriving, or about to enter, and never write "
        "a camera path that travels toward, reveals, or settles on a character — they must be "
        "fully visible from the very first frame to the last. The camera may move, but it may "
        "never change who is in the room. Under 50 words. Output ONLY the "
        "corrected line, numbered '1.'.\n\nSHOT:\n" + shot_line
    )
    kwargs = dict(prompt=correction, system_prompt=_MOTION_SYSTEM, max_tokens=200, temperature=0.4)
    if model:
        kwargs["model"] = model
    try:
        text = (await claude.generate(**kwargs)) or ""
    except Exception as e:  # noqa: BLE001 — repair call failing must fall through to the template
        logger.warning("motion-prompt repair call failed: %s", e)
        return ""
    lines = _parse_numbered(text, 1)
    return _strip_embedded_line(lines[0]) if lines else ""


async def _write_motion_prompts(
    vid,
    tenant,
    scene,
    claude,
    model=None,
    section_contract=None,
    asset_ids=None,
) -> int | dict[str, Any]:
    """One Claude call writes the per-shot CAMERA MOTION for the scene's coverage
    frames; the spoken line was already assigned by the coverage planner (stored on
    assets.assigned_dialogue), so we append it deterministically — no LLM re-mapping
    that drops/duplicates/reorders lines. Stores video_prompt = motion + line.

    FAIL CLOSED (2026-07-22): a shot whose line still contradicts its still
    after the one corrective repair retry (gate_motion_prompt) is BLOCKED,
    not downgraded — video_prompt is left NULL, assets.motion_gate_status is
    set to 'blocked', and a bot_activity row names the reason. Clip
    generation (pipeline_executor.py run_clip_generation) must skip a
    blocked/promptless row rather than spend on it. Best-effort otherwise —
    a Claude-call failure for the whole scene still leaves rows' video_prompt
    NULL, same as before."""
    camera_mode = ""
    exact_seconds = None
    if section_contract is not None:
        animation = section_contract.get("animation")
        camera = section_contract.get("camera")
        if (
            section_contract.get("render_mode") != "coverage"
            or not isinstance(animation, dict)
            or animation.get("enabled") is not True
            or animation.get("mode") != "grok_native"
            or not isinstance(camera, dict)
            or camera.get("mode")
            not in {"dialogue_coverage", "investigative_coverage"}
            or type(section_contract.get("exact_seconds")) is not int
            or section_contract["exact_seconds"] < 1
        ):
            raise ValueError("Unsupported animated section motion contract")
        camera_mode = str(camera["mode"])
        exact_seconds = int(section_contract["exact_seconds"])

    if asset_ids is not None and (
        not isinstance(asset_ids, list)
        or not asset_ids
        or len(set(asset_ids)) != len(asset_ids)
    ):
        raise ValueError("Invalid Custom Film motion asset allowlist")
    rows = await fetch_all(
        "SELECT id, shot_type, image_prompt, sentence_text, assigned_dialogue, camera_movement "
        "FROM assets "
        "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 AND generation_method='coverage' "
        + ("AND id = ANY($4::uuid[]) " if asset_ids is not None else "")
        + "ORDER BY image_index",
        vid,
        tenant,
        scene,
        *([asset_ids] if asset_ids is not None else []),
    )
    if not rows:
        return 0
    srow = await fetch_one(
        "SELECT scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene=$3", vid, tenant, scene)
    narration = ((srow or {}).get("scene_text") or "").strip()

    # LAW 3 (video f00ea79a scene 1): zero tone/genre data reached the
    # motion-writer before this — read the one-line tone hint (if the
    # channel has been learned and carries one) and pass it through
    # verbatim. Absent tone = no-op, never invented here.
    from channel_format import get_channel_tone
    channel_tone = await get_channel_tone(tenant)

    # Camera engine plans ("move_id|PURPOSE" or "static", stamped at compose
    # time): translate to a per-shot directive tag so the writer executes the
    # exact move the still was composed for. Unknown/legacy values = freeform.
    def _camera_tag(r):
        raw = (r.get("camera_movement") or "").strip()
        if raw == "static":
            return "(CAMERA: static) "
        if raw and "|" in raw:
            try:
                from image_prompts.engine.camera_moves import get_move
                move = get_move(raw.partition("|")[0])
                if move:
                    return f"(CAMERA LOCKED: {move.motion_prompt}) "
            except Exception:  # noqa: BLE001 — plan lookup must never break motion writing
                pass
        return ""

    # Tag each shot that speaks (so the writer frames the face) — but the writer
    # only writes camera MOTION; the words are appended from assigned_dialogue.
    def _shot(i, r):
        spk, _txt = _split_assigned(r.get("assigned_dialogue"))
        tag = f"(SPEAKING: {spk}) " if spk else ""
        desc = r.get("sentence_text") or ""
        if not desc:
            # sentence_text is null on REACTION rows (root cause, 2026-07-22):
            # falling back to the raw truncated image_prompt snippet handed
            # the writer "CU on Ryan, listening to Vanessa's line" and it
            # misread that as "describe Vanessa" — an explicit structured hint
            # instead of the raw snippet stops the misread at the source.
            pair = _reaction_pair(r.get("image_prompt") or "")
            if pair:
                reactor, speaker = pair
                desc = (f"REACTION shot. SUBJECT ON CAMERA: {reactor} — describe {reactor}'s "
                        f"face/body reacting. {speaker} is off-frame context only; you may say "
                        f"{reactor} looks/glances toward {speaker}, but {speaker} must never be "
                        f"the one doing anything.")
            else:
                desc = r.get("image_prompt") or ""
        return f"{i+1}. [{(r['shot_type'] or 'MS')}] {tag}{_camera_tag(r)}{desc[:260]}"
    shots = "\n".join(_shot(i, r) for i, r in enumerate(rows))
    # LAW 3: appended only when a tone is on file — byte-identical to today
    # when absent.
    tone_line = (f"\n\nCHANNEL TONE: {channel_tone} — all performance and delivery "
                 f"directions must match this tone." if channel_tone else "")
    user = (f"SCENE NARRATION (context):\n{narration[:2000]}\n\n"
            f"SHOTS (write ONE camera-motion line per shot, numbered, in order):\n{shots}"
            + (
                f"\n\nAPPROVED SECTION CAMERA: {camera_mode}; exact section "
                f"runtime: {exact_seconds} seconds. Every move must obey this "
                "camera grammar and fit inside that section runtime."
                if camera_mode
                else ""
            )
            + tone_line)
    kwargs = dict(prompt=user, system_prompt=_MOTION_SYSTEM, max_tokens=1800, temperature=0.6)
    if model:
        kwargs["model"] = model
    text = (await claude.generate(**kwargs)) or ""
    motions = _parse_numbered(text, len(rows))
    written = 0
    written_artifacts = []
    for i, (r, motion) in enumerate(zip(rows, motions)):
        motion = _strip_embedded_line(motion) or "Slow push-in on the main subject, keeping it in frame."
        # GATE + REPAIR (contract-triangle 2nd/3rd legs): a motion line that
        # narrates a character in image_prompt as absent/arriving must never
        # be stored — Grok follows the text over the picture and renders an
        # empty room (found live: "ending on the empty sofa where Ryan and
        # Vanessa will sit" over a still that already shows them seated).
        violation = gate_motion_prompt(motion, r.get("image_prompt"))
        if violation:
            retry = await _retry_motion_prompt(claude, model, _shot(i, r), violation)
            retry_violation = gate_motion_prompt(retry, r.get("image_prompt")) if retry else "repair returned nothing"
            if retry and not retry_violation:
                motion = retry
            else:
                # FAIL CLOSED (code law, 2026-07-22 — "the prompt is the
                # prompt; we can't be downgrading prompts under automation"):
                # a line that STILL contradicts the still after one
                # corrective retry must never be auto-substituted with
                # fallback text and shipped to Grok. Block the shot instead
                # of storing anything: video_prompt stays NULL and
                # motion_gate_status='blocked' so run_clip_generation
                # (pipeline_executor.py) skips it and spends nothing, and a
                # visible bot_activity row tells a human which shot needs a
                # hand-written line. _camera_lock_fallback_text/
                # _CHARACTER_SAFE_FALLBACK stay in the codebase — they're
                # just no longer reachable from this automated writer; a
                # manual repair path may still call them explicitly.
                reason = retry_violation or violation
                logger.warning(
                    "motion-prompt gate: scene %s shot %s asset %s BLOCKED (no fallback "
                    "stored) — original: %r (%s); repair: %r (%s)",
                    scene, i + 1, r["id"], motion, violation, retry, retry_violation)
                await execute(
                    "UPDATE assets SET video_prompt=NULL, motion_gate_status='blocked', "
                    "updated_at=now() WHERE id=$1",
                    r["id"],
                )
                await execute(
                    "INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    tenant, "Motion Bot", vid, "failed",
                    (f"Motion prompt blocked by gate — needs human edit: {reason}")[:900],
                )
                continue
        spk, txt = _split_assigned(r.get("assigned_dialogue"))
        # "once, quickly ... then silence": Grok's 6s minimum stretched a
        # 1.5s line into slow-motion mouthing across the whole clip — the
        # renderer shows only the line's window, cutting mid-flap (found
        # live). Front-load the speech so mouth and track line up and the
        # tail of the clip is safely trimmable/loopable.
        prompt = (f'{motion}. {spk} says once, quickly and clearly: "{txt}" — then '
                  f'closes their mouth and holds the moment in silence.'
                  if (spk and txt) else motion)
        # motion_gate_status=NULL: a clean write on a re-run (redo/regenerate)
        # must clear any stale 'blocked' marker a prior pass left on this row.
        await execute(
            "UPDATE assets SET video_prompt=$1, motion_gate_status=NULL, updated_at=now() "
            "WHERE id=$2",
            prompt, r["id"],
        )
        written += 1
        written_artifacts.append({"asset_id": str(r["id"]), "video_prompt": prompt})
    if section_contract is not None:
        return {
            "written": written,
            "asset_ids": [row["asset_id"] for row in written_artifacts],
            "artifacts": written_artifacts,
        }
    return written


async def generate_coverage_for_video(
    video_id,
    tenant_id,
    scene=None,
    progress=None,
    only_scenes=None,
    section_contract=None,
):
    """Backend stage entry point: generate the burger-style COVERAGE for a video's scene(s) and
    store it in the app (frames as assets + the storyboard board), anchored on the LOCKED character
    sheets. THIS is the live path the Scenes-page "Generate all pictures" button and the chat
    auto-build both call (stage 'coverage-images' -> routes/pipeline.py::run_coverage_images, and
    actions.py's autobuild loop). Honors videos.image_model_override end to end via
    shared.clients.image_model_router — GPT Image 2 stays the default and the content-policy/
    failure fallback. Returns {status, message}. `progress(msg)` streams status to the task poller.

    scene: existing single-scene filter/redo — when set, ALSO forces that one scene to
    (re)draw regardless of skip-if-done (this is the per-scene "regenerate scene N" button's
    verb, routes/pipeline.py::run_coverage_images; an explicit ask must still work even if
    the scene already looks done under an unchanged script).

    only_scenes (C16b, list[int]|None): the scene-allowlist entry point finalize will use
    ("regenerate ONLY approved scenes") — when set, ONLY these scenes are (re)generated,
    ALSO forced regardless of skip-if-done (an explicit allowlist means "redo these"), and
    every other scene is never even considered. `None` = today's all-scenes behavior plus
    the new skip-if-done guard below.

    Default (scene=None, only_scenes=None — the "Generate all pictures" button and the chat
    autobuild path): skip-if-done — a scene whose directive hash is unchanged AND whose
    coverage frames are already fully drawn is left alone, so re-invoking (autobuild resume,
    a second click) costs $0 instead of re-billing every scene (S7-2)."""
    def _p(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    v = await fetch_one(
        "SELECT id, tenant_id, video_title, COALESCE(aspect_ratio,'16:9') AS aspect, "
        "image_style_override, visual_style, image_model_override, render_style, video_model, "
        "COALESCE(dialogue_audio,'voice_over') AS dialogue_audio, "
        "production_style_snapshot "
        "FROM videos WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not v:
        return {"status": "failed", "error": "video not found"}
    vid, tenant, title, aspect = str(v["id"]), str(v["tenant_id"]), v["video_title"], v["aspect"]
    dialogue_audio = v["dialogue_audio"]  # channel pacing mode for _coverage_shape
    production_style_snapshot = v.get("production_style_snapshot")
    visual_profile_override = None
    camera_mode_override = None
    allow_auto_cast_generation = True
    if section_contract is not None:
        density = section_contract.get("image_density")
        animation = section_contract.get("animation")
        camera = section_contract.get("camera")
        auxiliary_image_policy = section_contract.get("auxiliary_image_policy")
        if (
            section_contract.get("render_mode") != "coverage"
            or section_contract.get("image_source") != "generate"
            or not isinstance(density, dict)
            or density.get("mode") not in {"dialogue_shape", "visual_cue"}
            or not isinstance(density.get("target_per_minute"), (int, float))
            or isinstance(density.get("target_per_minute"), bool)
            or density["target_per_minute"] <= 0
            or type(section_contract.get("expected_still_images")) is not int
            or section_contract["expected_still_images"] < 1
            or section_contract.get("expected_animation_clips")
            != section_contract["expected_still_images"]
            or not isinstance(animation, dict)
            or animation.get("enabled") is not True
            or animation.get("mode") != "grok_native"
            or not isinstance(camera, dict)
            or camera.get("mode")
            not in {"dialogue_coverage", "investigative_coverage"}
            or not str(section_contract.get("visual_profile") or "").strip()
            or type(section_contract.get("exact_seconds")) is not int
            or section_contract["exact_seconds"] < 1
            or auxiliary_image_policy != CUSTOM_FILM_AUXILIARY_IMAGE_POLICY
        ):
            raise ValueError("Unsupported coverage section production contract")
        production_style_snapshot = {"knobs": {"image_density": density}}
        visual_profile_override = str(section_contract["visual_profile"])
        camera_mode_override = str(camera["mode"])
        allow_auto_cast_generation = False
    model_override = v["image_model_override"]
    # C13b: threaded through to run_coverage -> plan_camera_moves -> route_shot_model
    # (mirrors generate_storyboard_sheet_for_scene's identical SELECT+assign above it in
    # this file). Incidental fix found while building C16b: this call path has raised a
    # NameError on every real invocation since C13b (8f923f3) — render_style/video_model_id
    # were referenced at the run_coverage() call below, but `v`'s SELECT never fetched
    # those two columns, so the ONE paid image stage crashed as soon as it reached the
    # first scene's draw. No test caught it because every existing test exercises
    # sub-functions (parse_coverage/generate_coverage_frames/plan_camera_moves), never
    # this function end-to-end.
    render_style = v["render_style"]
    video_model_id = v["video_model"]

    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
        "AND scene IS NOT NULL AND scene_text IS NOT NULL ORDER BY scene", vid, tenant)
    targets = [s for s in scenes
               if (scene is None or s["scene"] == scene)
               and (only_scenes is None or s["scene"] in only_scenes)]
    if not targets:
        return {"status": "failed", "error": "no scenes with text to cover"}

    claude = await get_text_client_for_tenant(tenant)
    claude_model = claude_model_for_direct_client(claude)
    kie_key = await _require_tenant_kie_key(tenant)
    ic = ImageClient(api_key=kie_key, tenant_id=tenant)
    # Carry the creator's chosen visual style (e.g. 3D Pixar) into the cast sheet + director so the
    # whole video renders in that style — not the realistic default.
    profile, style_dir = (
        _resolve_style(None, visual_profile_override)
        if visual_profile_override
        else _resolve_style(v["image_style_override"], v["visual_style"])
    )
    # Scene-aware bible: each scene's directive gets ONLY the characters in that scene
    # (the 1-character-per-scene lock), via the existing _format_story_bible_for_beat.
    bible = await scene_aware_bible(vid, tenant, scenes, claude, claude_model)
    base_dir = f"/tmp/coverage_app/{vid[:8]}"

    # Anchor every frame on the LOCKED character 4-view sheets (best cast lock); fall back to an
    # auto-built combined cast only if no characters are locked.
    crows = await fetch_all(
        "SELECT reference_url FROM video_characters WHERE video_id=$1 AND tenant_id=$2 "
        "AND reference_url IS NOT NULL ORDER BY sort", vid, tenant)
    cast_refs = [r["reference_url"] for r in crows]
    if not cast_refs and allow_auto_cast_generation:
        cu = await resolve_cast_url(None, ic, story_bible=bible, profile=profile, aspect=aspect,
                                    outdir=base_dir, model_override=model_override)
        cast_refs = [cu] if cu else []
    if not cast_refs and allow_auto_cast_generation:
        # No locked characters AND no character bible to build from — the common case for chat
        # auto-builds, which stamp the characters gate but never write video_characters rows.
        # Build a cast sheet straight from the script (the same proven path the CLI uses below)
        # so coverage always has an anchor instead of dead-ending on "lock characters first".
        _p("Building the cast from the script…")
        try:
            cast_text = "\n\n".join((s["scene_text"] or "") for s in targets)
            cast_prompt = await build_cast_prompt(claude, cast_text, model=claude_model, style=style_dir)
            cu = await resolve_cast_url(None, ic, cast_prompt=cast_prompt, profile=profile,
                                        aspect=aspect, outdir=base_dir, model_override=model_override)
            cast_refs = [cu] if cu else []
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": f"couldn't build a cast from the script: {e}"}
    if not cast_refs and allow_auto_cast_generation:
        return {"status": "failed", "error": "no cast to anchor on — lock characters first"}

    # SCENE LOCK: same approved-environment conditioning for the real frames.
    envs = await _approved_envs(vid, tenant)

    total = 0
    skipped = 0
    for s in targets:
        sc = s["scene"]
        outdir = f"{base_dir}/scene{sc}"
        # Size coverage to the dialogue + the channel's pacing policy (see
        # _coverage_shape): echo/voice_over paces to runtime with earned
        # angles; grok_native keeps the rich cinematic multi-angle coverage.
        _mm, _amin, _amax, _mframes = _coverage_shape(
            s["scene_text"] or "",
            dialogue_audio,
            production_style_snapshot,
            section_contract,
        )
        # An explicit ask for THIS scene (the per-scene "regenerate scene N"
        # button, or this scene named in only_scenes) always redraws — an
        # explicit request means "redo this scene" regardless of skip-if-done.
        force_this_scene = (scene is not None) or (only_scenes is not None and sc in only_scenes)
        # THE GATE: if the storyboard step planned this scene and the script
        # hasn't changed since, draw THAT exact plan — the sheets the creator
        # reviewed are binding. An edited script invalidates the preview.
        directive = None
        board_urls: list = []
        board_panel_total = None
        saved = await fetch_one(
            "SELECT coverage_directive, coverage_directive_hash, storyboard_prompts, "
            "storyboard_1_url, storyboard_2_url, storyboard_3_url, "
            "storyboard_4_url, storyboard_5_url FROM scripts "
            "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3", vid, tenant, sc)
        if saved and (saved.get("coverage_directive") or "").strip():
            if saved.get("coverage_directive_hash") == _scene_text_hash(s["scene_text"] or ""):
                directive = saved["coverage_directive"]
                # SKIP-IF-DONE (C16b/S7-2 — the default, unless forced above):
                # this scene's directive is unchanged; if its coverage frames
                # are ALREADY fully drawn under this exact plan, re-running
                # would re-bill the paid draw for pixels that would come out
                # as the identical prompts. "Complete" is judged against the
                # frame count plan_moments_deterministic() (C7 fix (a)) would
                # actually produce from THIS saved directive under today's
                # shape params (_expected_coverage_frame_count) — not merely
                # "> 0 rows exist" — so a crash or content-policy skip
                # mid-scene (store_scene only inserts a row per frame that
                # actually drew — see its `usable` filter over frames with a
                # real local file) leaves the row count under the expected
                # count and correctly reads as incomplete, never a false
                # "done" that would strand a half-drawn scene.
                if not force_this_scene:
                    expected_n = _expected_coverage_frame_count(directive, _mm, _amax, _mframes)
                    drawn_row = await fetch_one(
                        "SELECT COUNT(*) AS n FROM assets WHERE video_id=$1 AND tenant_id=$2 "
                        "AND scene=$3 AND generation_method='coverage' AND image_url IS NOT NULL "
                        "AND drive_image_url IS NOT NULL", vid, tenant, sc)
                    drawn_n = (drawn_row or {}).get("n") or 0
                    if expected_n > 0 and drawn_n >= expected_n:
                        skipped += 1
                        _p(f"Scene {sc}: already drawn ({drawn_n} frames, unchanged script) — skipping")
                        continue
                # BOARD ANCHOR: these sheets were drawn FROM this exact directive
                # (the gate stores both together), so each shot can be pinned to
                # its approved panel — same framing, same character placement.
                board_urls = [saved.get(f"storyboard_{i}_url") for i in range(1, 6)]
                while board_urls and not board_urls[-1]:
                    board_urls.pop()
                # C7 fix (a), layer 2: the TRUE panel count those sheets were
                # planned with (never re-derived from moments) — the legacy-
                # sheet guard run_coverage's board-anchor block checks its
                # own recompute against. storyboard_prompts is set in the
                # SAME UPDATE as the board URLs (the gate's one write), so
                # it's present whenever board_urls is; None only for a row
                # this fix predates or that isn't parseable.
                board_panel_total = (_stored_sheet_panel_total(saved.get("storyboard_prompts"))
                                     if board_urls else None)
                anchored = " — matching the approved boards" if any(board_urls) else ""
                _p(f"Scene {sc}: drawing the storyboarded plan ({model_override or 'GPT Image 2'}){anchored}…")
            else:
                _p(f"Scene {sc}: script changed since the storyboard — re-planning…")
        if directive is None:
            _p(f"Scene {sc}: planning + drawing coverage ({model_override or 'GPT Image 2'})…")
            # D10-3a: this scene has no saved plan to reuse (the sheet-preview step
            # was skipped for it), so run_coverage below would plan its OWN directive
            # internally — but run_coverage has no board_rules_text parameter at all,
            # so a narrative block passed only via `bible` would never reach that
            # internal call. When this video's bible carries narrative signal, plan
            # HERE instead, through the same generate_coverage_directive call site 1
            # (generate_storyboard_sheet_for_scene) already uses, so the two call
            # sites stay consistent. Absent narrative: _narrative_board_text is "",
            # directive stays None, and run_coverage plans exactly as it does today
            # — byte-identical.
            _narrative_board_text = _board_rules_text_with_narrative("", bible)
            if _narrative_board_text:
                directive = await generate_coverage_directive(
                    s["scene_text"] or "", title, profile, bible, [sc], [],
                    max_moments=_mm, angles_min=_amin, angles_max=_amax,
                    anthropic_client=claude, model=claude_model,
                    board_rules_text=_narrative_board_text)
        env = _match_scene_env((directive or "") + " " + (s["scene_text"] or ""), envs)
        if env:
            _p(f"Scene {sc}: locked to {env['name']}")
        try:
            coverage_kwargs = {}
            if section_contract is not None:
                coverage_kwargs["allow_auto_cast_generation"] = False
            out = await run_coverage(
                beat_text=s["scene_text"] or "", image_client=ic, outdir=outdir, cast_url=cast_refs,
                video_title=title, profile=profile, beat_scenes=[sc], story_bible=bible,
                anthropic_client=claude, directive_model=claude_model, directive_text=directive,
                max_moments=_mm, angles_min=_amin, angles_max=_amax, max_frames=_mframes,
                aspect=aspect, env_url=(env or {}).get("reference_url"),
                board_urls=board_urls or None, board_panel_total=board_panel_total,
                model_override=model_override,
                render_style=render_style, video_model_id=video_model_id,
                camera_mode=camera_mode_override,
                # C4: the matched environment's canonical prop manifest, if it
                # has one — run_coverage appends it verbatim to every shot's
                # draw prompt. None (no match, or the env has no manifest yet)
                # is the existing behavior, unchanged.
                props=(env or {}).get("props"),
                # D6-1c (L20): the SAME approved-environment list and single
                # scene-matched env this call already resolved above (envs,
                # env) — reused, never re-queried, so run_coverage's MATERIAL
                # MAP LOCK can prefer video_environments.material_map over
                # the planner's own [MATERIAL|] line, same precedence the
                # $0.05 sheet PREVIEW already gives it (_canonical_material_
                # line, above in this file). Both fall through to "" (no
                # canonical row) exactly as before for every video today.
                canonical_envs=envs,
                matched_env=env,
                progress_callback=_p,
                **coverage_kwargs)
        except Exception as e:  # noqa: BLE001 — one scene's crash must not stop the rest
            _p(f"Scene {sc}: errored ({str(e)[:150]}) — moving on to the next scene")
            continue
        if out.get("error"):
            _p(f"Scene {sc}: skipped ({out['error']})")
            continue
        for m in out["moments"]:
            for fr in m["frames"]:
                fr["_path"] = os.path.join(outdir, fr.get("file", "")) if fr.get("file") else None
        # Backstop: make line placement exact regardless of the planner's adherence.
        _reconcile_moment_dialogue(out["moments"], s["scene_text"] or "")
        frames_by_moment = [(m["summary"], m["frames"], m.get("speaker"), m.get("line"))
                            for m in out["moments"]]
        n = await store_scene(vid, tenant, title, aspect, sc, frames_by_moment,
                              location_id=(env or {}).get("name"))
        # Boards are the creator's approved SCENE LOCK — when the frames were
        # drawn anchored to them, never touch them. Burger boards (contact
        # sheets of the real frames) only fill in when there was no valid
        # approved board: the gate never ran, or the script changed and the
        # scene re-planned (stale sheets would silently lie about the frames).
        if not board_urls:
            await set_scene_board(vid, tenant, sc, outdir, title=title)
        # Write a real per-shot grok-imagine MOTION prompt onto each frame, so the clip
        # generator animates with intent instead of falling back to a hardcoded push-in.
        if section_contract is None:
            try:
                _p(f"Scene {sc}: writing camera motion…")
                await _write_motion_prompts(vid, tenant, sc, claude, claude_model)
            except Exception as e:  # noqa: BLE001
                _p(f"(motion prompts skipped: {e})")
        total += n
        _p(f"Scene {sc}: {n} coverage frames + board done")

    # Surface the cast in the Characters tab so the creator can see/lock it. The fast auto-build
    # stamps the characters gate but never writes rows, leaving the tab empty; fill it from the
    # cast sheet we just built (in the chosen style). Idempotent — skips if rows already exist.
    if section_contract is None:
        try:
            full_script = "\n\n".join((s["scene_text"] or "") for s in scenes)
            _p("Filling the Characters tab from the cast…")
            await populate_characters(vid, tenant, claude, claude_model, ic, base_dir, full_script,
                                      style=style_dir)
        except Exception as e:  # noqa: BLE001
            _p(f"(couldn't fill the Characters tab: {e})")

    processed = len(targets) - skipped
    if section_contract is not None and total != section_contract["expected_still_images"]:
        return {
            "status": "failed",
            "error": (
                "coverage frame count did not match the approved section BOM: "
                f"expected {section_contract['expected_still_images']}, got {total}"
            ),
        }
    msg = f"Coverage done: {total} frames across {processed} scene(s)"
    if skipped:
        msg += f" ({skipped} scene(s) already done, skipped)"
    return {"status": "completed", "message": msg}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="video id prefix or title substring")
    ap.add_argument("--scene", type=int, default=None, help="single scene number (default: all)")
    ap.add_argument("--moments", type=int, default=3, help="max moments per scene")
    ap.add_argument("--reuse", action="store_true",
                    help="reuse frames already on disk (upload+insert only, no regeneration)")
    ap.add_argument("--complete", action="store_true",
                    help="populate the Characters tab + storyboard board from frames already on disk")
    ap.add_argument("--redo-characters", action="store_true",
                    help="rebuild each character as a photoreal 4-view reference sheet (no scenes)")
    ap.add_argument("--character", default=None, help="with --redo-characters: only this character name")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    v = await resolve_video(args.video)
    if not v:
        print(f"No video matched '{args.video}'"); return
    vid, tenant = str(v["id"]), str(v["tenant_id"])
    title, aspect = v["video_title"], v["aspect"]
    _, style_dir = _resolve_style(v["image_style_override"], v["visual_style"])
    print(f"Video: {title}\n  id={vid} tenant={tenant} aspect={aspect}"
          + (f"\n  style: {style_dir[:80]}" if style_dir else "\n  style: (none set — photoreal default)"))

    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
        "AND scene IS NOT NULL AND scene_text IS NOT NULL ORDER BY scene", vid, tenant)
    targets = [s for s in scenes if args.scene is None or s["scene"] == args.scene]
    if not targets:
        print("No matching scenes with text."); return

    est = len(targets) * args.moments * 4 + 1  # +1 cast sheet
    print(f"Plan: {len(targets)} scene(s) {[s['scene'] for s in targets]}, "
          f"~{args.moments} moments each → ~{est} image gens (~${est * PER_FRAME_USD:.2f})")
    if args.dry_run:
        print("DRY RUN — nothing generated or written."); return

    base_dir = f"/tmp/coverage_app/{vid[:8]}"

    # --complete: make the video read as a normal finished video — write the cast into the
    # Characters tab and fill each scene's storyboard board from the coverage frames on disk.
    if args.complete:
        claude = await get_text_client_for_tenant(tenant)
        claude_model = claude_model_for_direct_client(claude)
        kie_key = await _require_tenant_kie_key(tenant)
        ic = ImageClient(api_key=kie_key, tenant_id=tenant)
        full_script = "\n\n".join((s["scene_text"] or "") for s in scenes)
        nchar = await populate_characters(vid, tenant, claude, claude_model, ic, base_dir, full_script,
                                          style=style_dir)
        nboard = 0
        for s in targets:
            if await set_scene_board(vid, tenant, s["scene"], f"{base_dir}/scene{s['scene']}", title=title):
                nboard += 1
                print(f"  scene {s['scene']}: storyboard board set")
        print(f"\nDONE — {nchar} characters + {nboard} storyboard board(s) set for '{title}'. "
              f"Refresh the video in the app.")
        return

    # --redo-characters: rebuild each character as a photoreal 4-view reference sheet (the locked
    # character-creation prompt) + tighten its description. The consistency foundation; no scenes.
    if args.redo_characters:
        claude = await get_text_client_for_tenant(tenant)
        claude_model = claude_model_for_direct_client(claude)
        kie_key = await _require_tenant_kie_key(tenant)
        ic = ImageClient(api_key=kie_key, tenant_id=tenant)
        full_script = "\n\n".join((s["scene_text"] or "") for s in scenes)
        n = await redo_characters(vid, tenant, claude, claude_model, ic, full_script, only=args.character)
        print(f"\nDONE — rebuilt {n} character 4-view reference sheet(s) for '{title}'. "
              f"Refresh the Characters tab. Scenes NOT touched — regenerate them next, once you confirm the lock.")
        return

    # Generation needs Claude + Kie + a cast; reuse mode skips all of that and just
    # uploads+inserts frames already on disk.
    claude = ic = profile = cast_url = claude_model = bible = None
    if not args.reuse:
        claude = await get_text_client_for_tenant(tenant)
        # A direct Anthropic client's built-in default model id can be stale (we hit a 404
        # on it); pass a current one. The Kie-routed client uses its own market model (None).
        claude_model = claude_model_for_direct_client(claude)
        kie_key = await _require_tenant_kie_key(tenant)
        ic = ImageClient(api_key=kie_key, tenant_id=tenant)
        profile, _ = _resolve_style(v["image_style_override"], v["visual_style"])
        # ONE cast for the whole video so characters match ACROSS scenes: reuse the on-disk cast
        # sheet a prior run made; only build it once. (A fresh cast per scene would drift the look.)
        cast_local = os.path.join(base_dir, "0_cast_sheet.png")
        if os.path.exists(cast_local):
            with open(cast_local, "rb") as f:
                cast_url = await upload_bytes(f.read(), f"{vid}/characters/_castsheet.png", "image/png", tenant)
            print(f"Reusing existing cast sheet for cross-scene consistency: {cast_url}")
        else:
            full_script = "\n\n".join((s["scene_text"] or "") for s in scenes)
            cast_prompt = await build_cast_prompt(claude, full_script, model=claude_model, style=style_dir)
            print(f"Cast prompt: {cast_prompt[:140]}...")
            cast_url = await resolve_cast_url(None, ic, cast_prompt=cast_prompt, profile=profile,
                                              aspect=aspect, outdir=base_dir)
        if not cast_url:
            print("Cast sheet failed — aborting."); return
        print(f"cast_url: {cast_url}")
        # Binding character bible — locks the writer's words to the cast so the look can't drift.
        bible = await load_character_bible(vid, tenant)
        if bible:
            print(f"Character bible (binding): {', '.join(c['id'] for c in bible['characters'])}")

    total = 0
    for s in targets:
        scene = s["scene"]
        outdir = f"{base_dir}/scene{scene}"
        if args.reuse:
            moments = load_existing(outdir)
            if not moments:
                print(f"  scene {scene}: no frames on disk to reuse — run without --reuse first"); continue
            frames_by_moment = [(m["summary"], m["frames"]) for m in moments]
            print(f"  scene {scene}: reusing {sum(len(m['frames']) for m in moments)} frames on disk")
        else:
            out = await run_coverage(
                beat_text=s["scene_text"] or "", image_client=ic, outdir=outdir, cast_url=cast_url,
                video_title=title, profile=profile, beat_scenes=[scene], story_bible=bible,
                anthropic_client=claude, directive_model=claude_model,
                max_moments=args.moments, aspect=aspect)
            if out.get("error"):
                print(f"  scene {scene}: SKIPPED ({out['error']})"); continue
            frames_by_moment = []
            for m in out["moments"]:
                for fr in m["frames"]:
                    fr["_path"] = os.path.join(outdir, fr.get("file", "")) if fr.get("file") else None
                frames_by_moment.append((m["summary"], m["frames"]))
        n = await store_scene(vid, tenant, title, aspect, scene, frames_by_moment)
        total += n
        print(f"  scene {scene}: {n} coverage frames stored")
        if await set_scene_board(vid, tenant, scene, outdir, title=title):
            print(f"  scene {scene}: storyboard board set")

    print(f"\nDONE — {total} coverage frames added to '{title}'. "
          f"Open the video in the app's images view to see them (grouped by scene, "
          f"shot-type badges, master starred).")


if __name__ == "__main__":
    asyncio.run(main())
