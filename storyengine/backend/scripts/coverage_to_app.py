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
from typing import Optional

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
from storyboard.coverage import (  # noqa: E402
    run_coverage, resolve_cast_url, generate_coverage_directive,
    parse_set_dressing, parse_axis_line, parse_setups_line, panels_per_sheet_for,
    sheet_chunk_sizes, _STYLE_LOCK, _STYLE_LOCK_HYGIENE, _INLINE_TAG_RE,
    plan_moments_deterministic,
    # C8 fix (a): the SAME ratios enforce_reaction_insert_floors uses to decide
    # how many reaction/insert/re-establish shots a scene needs — imported
    # (never re-guessed) so _coverage_shape's pure-dialogue headroom always
    # matches what the floor validator will actually go looking for.
    _REACTION_TURNS_PER_SHOT, _INSERT_SHOTS_PER_ONE, _REESTABLISH_SHOTS_PER_ONE,
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
    """Turn a video's stored style choice into (profile, style_directive).

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
    every downstream consumer's existing no-manifest fallback."""
    try:
        rows = await fetch_all(
            "SELECT name, description, reference_url, props FROM video_environments "
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
         here, unlike (2)."""
    if not envs:
        return None
    if len(envs) == 1:
        return envs[0]
    low_text = f" {_norm_env_text(text)} "

    def _phrase_count(phrase: str) -> int:
        p = _norm_env_text(phrase)
        return low_text.count(f" {p} ") if p else 0

    best, best_score = None, 0
    for e in envs:
        name = e["name"] or ""
        head = re.split(r"[—:\-]", name)[0].strip()
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
                "duration_seconds) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'done',$12,$13,$14,'coverage',"
                "$15,$16,$17,$18,$19,$20,$21)",
                str(uuid.uuid4()), tenant, vid, scene, idx, idx,
                summary[:500], (fr.get("description") or "")[:1000], fr.get("shot_type") or "",
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
    image model paints whatever the description says, so the description must be locked too."""
    rows = await fetch_all(
        "SELECT name, description FROM video_characters WHERE video_id=$1 AND tenant_id=$2 "
        "AND description IS NOT NULL ORDER BY sort", vid, tenant)
    chars = [{"id": r["name"], "costume": r["description"], "scenes_present": []} for r in rows]
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
    only ever handed empty scenes_present, so every character leaked into every scene."""
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
    return bible if (bible.get("characters") or bible.get("locations")) else None


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
    chars = await extract_characters(claude, script_text, model=claude_model)
    n = 0
    for i, ch in enumerate(chars):
        row = await fetch_one(
            "INSERT INTO video_characters (tenant_id, video_id, name, description, "
            "status, source, sort) VALUES ($1,$2,$3,$4,'approved','generated',$5) RETURNING id",
            tenant, vid, ch["name"], ch["description"], i)
        char_id = str(row["id"])
        for attempt in range(3):
            try:
                temp_url = await _generate_portrait(ic.api_key, ch.get("description") or ch["name"], style or "", name=ch.get("name") or "")
                ref = await _persist_portrait_url(tenant, vid, char_id, temp_url)
                await execute("UPDATE video_characters SET reference_url=$1, updated_at=now() WHERE id=$2",
                              ref, char_id)
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
    n = 0
    for r in rows:
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
        url, _model_used = await generate_scene_image_for_model(ic, model_override, prompt, aspect_ratio="16:9")
        if not url:
            print(f"  {r['name']}: 4-view sheet generation FAILED — keeping old"); continue
        stable = await _stable_url(url, f"{vid}/characters/{r['name'].replace(' ', '_')}_sheet.png", tenant)
        await execute("UPDATE video_characters SET description=$1, reference_url=$2, updated_at=now() "
                      "WHERE id=$3", desc, stable, r["id"])
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
                   variant: str = "primary") -> str:
    """The fixed instruction paragraph opening one storyboard sheet prompt —
    kept SEPARATE from _plan_sheet_prompts's panel-body construction so a
    failed sheet draw can retry with a DIFFERENT header on the SAME body (see
    the fallback-header retry in generate_storyboard_sheet_for_scene).

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
    if variant == "fallback":
        return (
            f"Storyboard sheet {chunk_index} of {total_chunks}: {panel_count} panels in a "
            "3-column grid on a light grey page, each panel a wide 16:9 frame. Style: "
            f"{style_line}. Match each character's appearance to the attached reference "
            "images throughout. A small strip below each panel shows only its number and "
            "shot type. No captions, dialogue, subtitles or lettering of any kind inside "
            "or under the panels."
        )
    return (
        f"This is storyboard sheet {chunk_index} of {total_chunks} for an animated scene: a "
        f"grid of {panel_count} panels arranged in 3 columns on a plain light grey page. Each "
        "panel is a wide 16:9 cinematic frame, never square or tall. Every panel uses the "
        f"same art style, {style_line}, with matching lighting and color grading throughout. "
        "Draw every character consistently across every panel, matching their appearance to "
        "the attached reference images. A small plain strip below each panel shows only its "
        "panel number and shot type. The panel artwork carries no lettering, signs, speech "
        "bubbles, captions, dialogue or written words of any kind — keep every panel free of "
        "readable text except the small panel-number label."
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


def _plan_sheet_prompts(moments: list, style_dir: str, panels_per_sheet: int = 9,
                        set_line: str = "", axis_line: str = "",
                        setups_line: str = "", header_variant: str = "primary") -> list[str]:
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
    image — so briefs stay tight and captions carry the spoken line."""
    def _trunc(s, n):
        # Word-boundary cut with an ellipsis. A hard slice amputates mid-word
        # ("Why didn'", "cream stove at ba") and the sheet drawer renders that
        # fragment verbatim into the caption strip.
        s = (s or "").strip()
        if len(s) <= n:
            return s
        return s[:n].rsplit(" ", 1)[0].rstrip(" ,;:.") + " …"

    panels: list[str] = []
    for m in moments:
        n = m.get("moment_number")
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
        panels.append(f"[{len(panels) + 1}] M{n} {master.get('shot_type', 'MS')} — "
                      f"{_trunc(master_desc, 300)}")
        for a in (m.get("angles") or []):
            angle_desc = _neutralize_risky_props(a.get("description"))
            panels.append(f"[{len(panels) + 1}] M{n} ANGLE {a.get('shot_type', 'CU')} — "
                          f"{_trunc(angle_desc, 300)}")
    style_line = (style_dir or "").strip() or "Photorealistic, cinematic film still"
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
    setups_block = (f"\nCAMERA KIT — the actors are PLANTED on the set and never move; the "
                    f"whole scene is covered by these repeated setups: "
                    f"{_neutralize_risky_props(setups_line)} Panels "
                    "whose brief carries the same SETUP letter are the SAME camera position "
                    "and the SAME frozen staging repeated EXACTLY — copy the framing, body "
                    "positions, distance and orientation from the first panel with that "
                    "letter; only faces, gestures and the caption change between them.\n"
                    if (setups_line or "").strip() else "")
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
        prompts.append(
            _sheet_header(ci, len(chunks), len(chunk), style_line, variant=header_variant)
            + f"{set_block}{axis_block}{setups_block}"
            "Draw these panels IN ORDER:\n"
            + listed +
            "\nCONSTRAINTS: never swap which side of the frame a character occupies; never "
            "mirror or flip a panel; one action per panel; a panel may break the "
            "screen-direction lock only if its brief says NEUTRAL.")
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
        "COALESCE(dialogue_audio,'voice_over') AS dialogue_audio "
        "FROM videos WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not v:
        return {"status": "failed", "error": "video not found"}
    vid, tenant, title, aspect = str(v["id"]), str(v["tenant_id"]), v["video_title"], v["aspect"]
    dialogue_audio = v["dialogue_audio"]  # channel pacing mode for _coverage_shape
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
    kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
    ic = ImageClient(api_key=kie_key, tenant_id=tenant)
    # Scene-aware bible so each scene's storyboard names ONLY its characters + the
    # locked environments (per-scene character lock + the prose background lock).
    bible = await scene_aware_bible(vid, tenant, scenes, claude, claude_model)
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
    for s in targets:
        sc = s["scene"]
        srow = await fetch_one(
            "SELECT id, coverage_directive, coverage_directive_hash FROM scripts "
            "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3", vid, tenant, sc)
        if not srow:
            continue
        _mm, _amin, _amax, _mframes = _coverage_shape(s["scene_text"] or "", dialogue_audio)
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
                anthropic_client=claude, model=claude_model)
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

        _sheet_kwargs = dict(
            panels_per_sheet=panels_per_sheet_for(directive or ""),
            set_line=parse_set_dressing(directive or "") or "",
            axis_line=parse_axis_line(directive or "") or "",
            setups_line=parse_setups_line(directive or "") or "")
        # Computed ONCE here and reused below (never re-derived) so sheet
        # chunking (_plan_sheet_prompts, via _sheet_kwargs), the per-board
        # panel counts and the progress messages can never diverge. _sizes is
        # the SAME balanced per-board split _plan_sheet_prompts chunks with
        # (shot_count == len(its panels list): one panel per master + angle).
        _cap = _sheet_kwargs["panels_per_sheet"]
        _sizes = sheet_chunk_sizes(shot_count, _cap)
        _previewed = sum(_sizes[:5])  # panels on the (at most 5) boards actually drawn
        prompts = _plan_sheet_prompts(moments, style_dir, **_sheet_kwargs)[:5]
        # C25a-fix8: the same panels, header-swapped — held ready so a board
        # that trips OpenAI's content filter on the primary header can retry
        # ONCE against the identical body with a sparser fallback header (see
        # _sheet_header's docstring). Cheap (pure string formatting, no LLM),
        # computed once here rather than per-failure.
        prompts_fallback = _plan_sheet_prompts(
            moments, style_dir, header_variant="fallback", **_sheet_kwargs)[:5]
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

        env = _match_scene_env((directive or "") + " " + (s["scene_text"] or ""), envs)
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
                        _sheet_kwargs = dict(
                            panels_per_sheet=panels_per_sheet_for(directive or ""),
                            set_line=parse_set_dressing(directive or "") or "",
                            axis_line=parse_axis_line(directive or "") or "",
                            setups_line=parse_setups_line(directive or "") or "")
                        prompts = _plan_sheet_prompts(moments, style_dir, **_sheet_kwargs)[:5]
                        prompts_fallback = _plan_sheet_prompts(
                            moments, style_dir, header_variant="fallback", **_sheet_kwargs)[:5]
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
        "SELECT a.id, a.scene, a.image_index, a.image_prompt, "
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

    kie_key = await get_secret("kie_ai_api_key", tenant_id) or os.getenv("KIE_AI_API_KEY")
    ic = ImageClient(api_key=kie_key, tenant_id=tenant_id)
    crows = await fetch_all(
        "SELECT reference_url FROM video_characters WHERE video_id=$1 AND tenant_id=$2 "
        "AND reference_url IS NOT NULL ORDER BY sort", video_id, tenant_id)
    cast_refs = [r["reference_url"] for r in crows]

    # LOCKED LOCATION on redraws too (2026-07-21): the batch pictures run
    # conditions every frame on the scene's approved environment ref, but this
    # path used to attach ONLY cast refs — so a redrawn frame re-invented its
    # background and visibly drifted from its still-original neighbors (seen
    # live on cd5d2883's scene-1 redraws). Same matcher as the batch path;
    # fail-soft, a redraw without an env match just draws like before.
    env_refs, env_note = [], ""
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
    except Exception as env_err:  # noqa: BLE001 — the redraw itself must never die on this
        _p(f"  (no location lock for this redraw: {str(env_err)[:80]})")

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
    url, model_used = await generate_scene_image_for_model(
        ic, model_override, style_prefix + prompt + _style_block + env_note,
        reference_urls=cast_refs + env_refs,
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
    return {"status": "completed", "message": f"Picture S{a['scene']}.{a['image_index']} redrawn"}


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


def _coverage_shape(scene_text: str, dialogue_audio: str = "voice_over"):
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
    turns = _dialogue_turn_count(scene_text)
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


async def _write_motion_prompts(vid, tenant, scene, claude, model=None) -> int:
    """One Claude call writes the per-shot CAMERA MOTION for the scene's coverage
    frames; the spoken line was already assigned by the coverage planner (stored on
    assets.assigned_dialogue), so we append it deterministically — no LLM re-mapping
    that drops/duplicates/reorders lines. Stores video_prompt = motion + line.
    Best-effort — leaves video_prompt NULL on failure (the clip gen has a default)."""
    rows = await fetch_all(
        "SELECT id, shot_type, image_prompt, sentence_text, assigned_dialogue, camera_movement "
        "FROM assets "
        "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 AND generation_method='coverage' "
        "ORDER BY image_index", vid, tenant, scene)
    if not rows:
        return 0
    srow = await fetch_one(
        "SELECT scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene=$3", vid, tenant, scene)
    narration = ((srow or {}).get("scene_text") or "").strip()

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
    user = (f"SCENE NARRATION (context):\n{narration[:2000]}\n\n"
            f"SHOTS (write ONE camera-motion line per shot, numbered, in order):\n{shots}")
    kwargs = dict(prompt=user, system_prompt=_MOTION_SYSTEM, max_tokens=1800, temperature=0.6)
    if model:
        kwargs["model"] = model
    text = (await claude.generate(**kwargs)) or ""
    motions = _parse_numbered(text, len(rows))
    written = 0
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
                logger.warning(
                    "motion-prompt gate: scene %s shot %s asset %s fell back to camera-lock "
                    "template — original: %r (%s); repair: %r (%s)",
                    scene, i + 1, r["id"], motion, violation, retry, retry_violation)
                motion = _camera_lock_fallback_text(r.get("camera_movement"), r.get("image_prompt"))
        spk, txt = _split_assigned(r.get("assigned_dialogue"))
        # "once, quickly ... then silence": Grok's 6s minimum stretched a
        # 1.5s line into slow-motion mouthing across the whole clip — the
        # renderer shows only the line's window, cutting mid-flap (found
        # live). Front-load the speech so mouth and track line up and the
        # tail of the clip is safely trimmable/loopable.
        prompt = (f'{motion}. {spk} says once, quickly and clearly: "{txt}" — then '
                  f'closes their mouth and holds the moment in silence.'
                  if (spk and txt) else motion)
        await execute("UPDATE assets SET video_prompt=$1, updated_at=now() WHERE id=$2", prompt, r["id"])
        written += 1
    return written


async def generate_coverage_for_video(video_id, tenant_id, scene=None, progress=None, only_scenes=None):
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
        "COALESCE(dialogue_audio,'voice_over') AS dialogue_audio "
        "FROM videos WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not v:
        return {"status": "failed", "error": "video not found"}
    vid, tenant, title, aspect = str(v["id"]), str(v["tenant_id"]), v["video_title"], v["aspect"]
    dialogue_audio = v["dialogue_audio"]  # channel pacing mode for _coverage_shape
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
    kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
    ic = ImageClient(api_key=kie_key, tenant_id=tenant)
    # Carry the creator's chosen visual style (e.g. 3D Pixar) into the cast sheet + director so the
    # whole video renders in that style — not the realistic default.
    profile, style_dir = _resolve_style(v["image_style_override"], v["visual_style"])
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
    if not cast_refs:
        cu = await resolve_cast_url(None, ic, story_bible=bible, profile=profile, aspect=aspect,
                                    outdir=base_dir, model_override=model_override)
        cast_refs = [cu] if cu else []
    if not cast_refs:
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
    if not cast_refs:
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
        _mm, _amin, _amax, _mframes = _coverage_shape(s["scene_text"] or "", dialogue_audio)
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
        env = _match_scene_env((directive or "") + " " + (s["scene_text"] or ""), envs)
        if env:
            _p(f"Scene {sc}: locked to {env['name']}")
        try:
            out = await run_coverage(
                beat_text=s["scene_text"] or "", image_client=ic, outdir=outdir, cast_url=cast_refs,
                video_title=title, profile=profile, beat_scenes=[sc], story_bible=bible,
                anthropic_client=claude, directive_model=claude_model, directive_text=directive,
                max_moments=_mm, angles_min=_amin, angles_max=_amax, max_frames=_mframes,
                aspect=aspect, env_url=(env or {}).get("reference_url"),
                board_urls=board_urls or None, board_panel_total=board_panel_total,
                model_override=model_override,
                render_style=render_style, video_model_id=video_model_id,
                # C4: the matched environment's canonical prop manifest, if it
                # has one — run_coverage appends it verbatim to every shot's
                # draw prompt. None (no match, or the env has no manifest yet)
                # is the existing behavior, unchanged.
                props=(env or {}).get("props"))
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
    try:
        full_script = "\n\n".join((s["scene_text"] or "") for s in scenes)
        _p("Filling the Characters tab from the cast…")
        await populate_characters(vid, tenant, claude, claude_model, ic, base_dir, full_script,
                                  style=style_dir)
    except Exception as e:  # noqa: BLE001
        _p(f"(couldn't fill the Characters tab: {e})")

    processed = len(targets) - skipped
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
        kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
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
        kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
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
        kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
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
