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
import os
import re
import subprocess
import sys
import urllib.request
import uuid
from io import BytesIO

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_BACKEND))
_SKILLS = os.path.join(_REPO, "skills", "video-pipeline")
sys.path.insert(0, _BACKEND)            # backend: database, storage, vault, kie_unified
sys.path.insert(0, _SKILLS)             # skills: storyboard.coverage, shared.*, orchestrator.*

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
from storage import upload_bytes                              # noqa: E402
from vault import get_secret                                  # noqa: E402
from kie_unified import get_text_client_for_tenant            # noqa: E402
from storyboard.coverage import (  # noqa: E402
    run_coverage, resolve_cast_url, generate_coverage_directive,
    parse_coverage, enforce_shot_budget, parse_set_dressing,
)
from shared.clients.image_client import ImageClient           # noqa: E402
from shared.channel_profile import load_profile               # noqa: E402
from orchestrator.pipeline_constants import Models            # noqa: E402

COVERAGE_INDEX_BASE = 100  # existing panels use 1-9; coverage frames live at 100+ (never clobber)
PER_FRAME_USD = 0.05
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


def _resolve_style(image_style_override, visual_style):
    """Turn a video's stored style choice into (profile, style_directive).

    The picture engine locks every frame to the cast sheet's look, so the cast sheet IS the
    style. This carries the creator's pick (image_style_override / visual_style) into the
    director, cast-sheet, and storyboard prompts. Without it, load_profile({}) fell back to a
    neutral 'clean, modern, cinematic' default and every video rendered realistic — even when
    the creator chose 3D Pixar. style_directive is None when no style was picked, so callers
    keep their own sensible default."""
    rec = {}
    iso = (image_style_override or "").strip()
    if iso:
        rec["Image Style Override"] = iso
    vs = (visual_style or "").strip()
    if vs:
        rec["Visual Style"] = vs
    profile = load_profile(rec)
    return profile, (profile.visual_style_directive if rec else None)


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


async def _approved_envs(vid, tenant) -> list[dict]:
    """The creator-approved environment references (the Environments tab).
    Empty for videos that never designed locations."""
    try:
        rows = await fetch_all(
            "SELECT name, description, reference_url FROM video_environments "
            "WHERE video_id=$1 AND tenant_id=$2 AND reference_url IS NOT NULL "
            "ORDER BY sort, created_at", vid, tenant)
        return [dict(r) for r in rows if r.get("name") and r.get("reference_url")]
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
    it always wins; with several and no signal, None (better no lock than the
    wrong location)."""
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
    # Fallback: no environment NAME appears as a phrase — old distinctive-word count.
    best, best_score = None, 0
    for e in envs:
        words = {w for w in re.split(r"[^a-z0-9]+", (e["name"] or "").lower()) if len(w) > 3}
        score = sum(low_text.count(w) for w in words)
        if score > best_score:
            best, best_score = e, score
    return best


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
                "location_id, camera_movement) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'done',$12,$13,$14,'coverage',$15,$16,$17)",
                str(uuid.uuid4()), tenant, vid, scene, idx, idx,
                summary[:500], (fr.get("description") or "")[:1000], fr.get("shot_type") or "",
                title, aspect, url, url, is_master, assigned, location_id,
                fr.get("camera_move"),  # camera engine plan: "move_id|PURPOSE" or "static"
            )
            idx += 1
    return idx - COVERAGE_INDEX_BASE


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
    `reference_url` is carried for the image-anchor step."""
    rows = await fetch_all(
        "SELECT name, description, reference_url FROM video_environments "
        "WHERE video_id=$1 AND tenant_id=$2 ORDER BY sort", vid, tenant)
    envs = [r for r in (rows or []) if (r.get("description") or "").strip()]
    if envs:
        return [{"id": r["name"] or "location", "description": r["description"], "lighting": "",
                 "type": "", "reference_url": r.get("reference_url")} for r in envs]
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
        r = await ic.generate_scene_image_gpt(prompt, None, "16:9")  # GPT Image 2 text-to-image
        url = r.get("url") if isinstance(r, dict) else r
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


def _plan_sheet_prompts(moments: list, style_dir: str, panels_per_sheet: int = 12,
                        set_line: str = "") -> list[str]:
    """Deterministic storyboard-sheet image prompts FROM the coverage plan —
    one numbered panel per planned SHOT (masters and angles alike), chunked
    ≤panels_per_sheet per sheet so panels stay readable. The preview shows
    exactly what the pictures step will draw: same shots, same order, same
    spoken lines. No LLM in between to drift.

    set_line is the plan's [SET | ...] geography/props line. It MUST ride on
    the sheet prompt itself: per-panel briefs are truncated and always open
    with verbatim wardrobe (bible rule), so the blocking language never
    survived the cut — the 2026-07-07 sheets drew a perfect plan as centered
    alternating mugshots in an empty-opener room because the sheet drawer
    never saw the staging."""
    panels: list[str] = []
    for m in moments:
        n = m.get("moment_number")
        speak = (f' SPEAKING {m["speaker"]}: "{(m["line"] or "")[:70]}"'
                 if m.get("speaker") and m.get("line") else "")
        master = m.get("master") or {}
        panels.append(f"[{len(panels) + 1}] M{n} {master.get('shot_type', 'MS')} — "
                      f"{(master.get('description') or '')[:300]}{speak}")
        for a in (m.get("angles") or []):
            panels.append(f"[{len(panels) + 1}] M{n} ANGLE {a.get('shot_type', 'CU')} — "
                          f"{(a.get('description') or '')[:300]}")
    style_line = (style_dir or "").strip() or "Photorealistic, cinematic film still"
    set_block = (
        f"\nFIXED SET & BLOCKING — identical in EVERY panel that shows the location: {set_line} "
        "Characters ALWAYS occupy their declared positions and face their declared directions; "
        "when a panel frames one character, keep them on THEIR side of the frame with their "
        "eyeline across the frame toward their partner — never centered staring into the camera. "
        "In dialogue panels the partner stays ANCHORED in frame: near shoulder and back of head "
        "soft in the foreground (over-the-shoulder) or a profile at the frame edge — a "
        "conversation panel showing only one visible person is WRONG unless its brief explicitly "
        "says the partner is out of frame. A panel described with both characters MUST show both.\n"
        if (set_line or "").strip() else "")
    prompts = []
    chunks = [panels[i:i + panels_per_sheet] for i in range(0, len(panels), panels_per_sheet)]
    for ci, chunk in enumerate(chunks, start=1):
        listed = "\n".join(chunk)
        prompts.append(
            f"A professional storyboard SHEET (sheet {ci} of {len(chunks)}): a clean grid of "
            f"{len(chunk)} numbered panels, 3 columns, each panel a WIDE 16:9 widescreen cinematic "
            "frame (never square or tall), with a small caption strip under each panel showing its "
            "number, shot type and one short action line. Render EVERY panel in this EXACT art "
            f"style, held identically across all panels: {style_line}. Consistent lighting and "
            "grade. Use the EXACT characters from the cast reference wherever they appear — never "
            "invent people or change their look. INSIDE the panels draw NO text of any kind — no "
            "speech bubbles, no dialogue balloons, no captions; spoken lines live only in the "
            f"caption strip BELOW each panel.{set_block}Draw these panels IN ORDER:\n" + listed)
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
        "image_style_override, visual_style, "
        "COALESCE(dialogue_audio,'voice_over') AS dialogue_audio "
        "FROM videos WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not v:
        return {"status": "failed", "error": "video not found"}
    vid, tenant, title, aspect = str(v["id"]), str(v["tenant_id"]), v["video_title"], v["aspect"]
    dialogue_audio = v["dialogue_audio"]  # channel pacing mode for _coverage_shape
    profile, style_dir = _resolve_style(v["image_style_override"], v["visual_style"])
    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
        "AND scene IS NOT NULL AND scene_text IS NOT NULL ORDER BY scene", vid, tenant)
    targets = [s for s in scenes if scene is None or s["scene"] == scene]
    if not targets:
        return {"status": "failed", "error": "no scenes with text"}

    claude = await get_text_client_for_tenant(tenant)
    claude_model = "claude-sonnet-4-6" if type(claude).__name__ == "AnthropicDirectClient" else None
    kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
    ic = ImageClient(api_key=kie_key)
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
        moments = parse_coverage(directive or "")
        if not moments:
            _p(f"Scene {sc}: the planner returned no shots"); continue
        moments = enforce_shot_budget(moments, _mm, _amax, max_frames=_mframes)
        # Verbatim line placement NOW, so the preview shows exactly which shot
        # speaks which line — the same reconcile runs again at draw time and,
        # being deterministic, lands identically.
        _reconcile_moment_dialogue(moments, s["scene_text"] or "")
        shot_count = sum(1 + len(m.get("angles") or []) for m in moments)

        prompts = _plan_sheet_prompts(moments, style_dir,
                                      set_line=parse_set_dressing(directive or "") or "")[:5]
        if beat is not None and not (1 <= beat <= len(prompts)):
            return {"status": "failed",
                    "error": f"Scene {sc} has {len(prompts)} board(s) — board {beat} doesn't exist."}
        if beat is None:
            # STREAMING CONTRACT (Ryan, 2026-07-07): persist the plan and the
            # board COUNT the moment planning finishes — the UI shows one
            # placeholder slot per coming board immediately, and each board
            # drops into its slot the moment it lands (per-slot UPDATE below),
            # not in one batch at the end.
            blocks = "\n\n".join(f"--- BEAT {i} ---\n{p}" for i, p in enumerate(prompts, start=1))
            await execute(
                "UPDATE scripts SET coverage_directive=$1, coverage_directive_hash=$2, "
                "storyboard_prompts=$3, storyboard_beat_count=$4, storyboard_1_url=NULL, "
                "storyboard_2_url=NULL, storyboard_3_url=NULL, storyboard_4_url=NULL, "
                "storyboard_5_url=NULL, updated_at=now() WHERE id=$5",
                directive, _scene_text_hash(s["scene_text"] or ""), blocks, len(prompts), srow["id"])
            if plan_only:
                # PLAN GATE (Ryan, 2026-07-07): stop here — the creator reads
                # the shot plan in the app, then draws boards one at a time.
                done += 1
                total_shots += shot_count
                _p(f"Scene {sc}: plan ready — {shot_count} shots on {len(prompts)} board(s), "
                   "nothing drawn yet")
                continue

        env = _match_scene_env((directive or "") + " " + (s["scene_text"] or ""), envs)
        env_block = ""
        sheet_refs = list(cast_refs)
        if env:
            env_block = (
                f"\nLOCKED LOCATION — {env['name']}: every panel's background is this EXACT "
                "location as shown in the FINAL reference image (after the cast sheets): "
                f"{(env.get('description') or '')[:220]}. Keep the location's layout, colors and "
                "props IDENTICAL across all panels; never invent a different room or set."
            )
            sheet_refs.append(env["reference_url"])
        lock_note = f", locked to {env['name']}" if env else ""
        todo = [(beat, prompts[beat - 1])] if beat is not None else list(enumerate(prompts, start=1))
        ok = 0
        for bi, sp in todo:
            # Panels ON THIS SHEET, not the scene's total — "(27 shots)" on a
            # single-board draw read as "everything is generating" (Ryan hit
            # Stop on a correct one-board run, 2026-07-07).
            on_sheet = min(12, shot_count - 12 * (bi - 1))
            _p(f"Scene {sc}: drawing {'ONLY board' if beat is not None else 'board'} "
               f"{bi} of {len(prompts)} — one sheet, {on_sheet} panels{lock_note}…")
            res = (await ic.generate_thumbnail_gpt2(sp + env_block, sheet_refs, aspect) if sheet_refs
                   else await ic.generate_scene_image_gpt(sp + env_block, None, aspect))
            url = res.get("url") if isinstance(res, dict) else res
            if url:
                stable = await _stable_url(url, f"{vid}/storyboard/S{sc}-B{bi}.png", tenant)
                # bi is 1-5 by construction (prompts capped, beat validated).
                await execute(
                    f"UPDATE scripts SET storyboard_{bi}_url=$1, updated_at=now() WHERE id=$2",
                    stable, srow["id"])
                ok += 1
                _p(f"Scene {sc}: board {bi} is up")
        if not ok:
            _p(f"Scene {sc}: storyboard image failed"); continue
        done += 1
        total_shots += shot_count
        _p(f"Scene {sc}: storyboard ready — {shot_count} shots on {ok} board(s)")
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
    cast sheets so the characters stay consistent. Clears the now-stale clip. GPT Image 2.

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
        "COALESCE(v.aspect_ratio,'16:9') AS aspect "
        "FROM assets a JOIN videos v ON v.id = a.video_id "
        "WHERE a.id=$1 AND a.video_id=$2 AND a.tenant_id=$3", asset_id, video_id, tenant_id)
    if not a:
        return {"status": "failed", "error": "picture not found"}
    prompt = (a["image_prompt"] or "").strip()
    if not prompt:
        return {"status": "failed", "error": "this picture has no image prompt to redraw from"}
    if safe_reframe:
        prompt = SAFE_REFRAME_PREFIX + prompt

    kie_key = await get_secret("kie_ai_api_key", tenant_id) or os.getenv("KIE_AI_API_KEY")
    ic = ImageClient(api_key=kie_key)
    crows = await fetch_all(
        "SELECT reference_url FROM video_characters WHERE video_id=$1 AND tenant_id=$2 "
        "AND reference_url IS NOT NULL ORDER BY sort", video_id, tenant_id)
    cast_refs = [r["reference_url"] for r in crows]

    _p(f"Redrawing S{a['scene']}.{a['image_index']} (GPT Image 2)…")
    res = (await ic.generate_thumbnail_gpt2(prompt, cast_refs, a["aspect"]) if cast_refs
           else await ic.generate_scene_image_gpt(prompt, None, a["aspect"]))
    url = res.get("url") if isinstance(res, dict) else res
    if not url:
        return {"status": "failed", "error": "image generation failed"}
    stable = await _stable_url(url, f"{video_id}/coverage/S{a['scene']}_i{a['image_index']}.png", tenant_id)
    # New picture → the old clip is stale: clear it so the scene re-animates clean.
    await execute(
        "UPDATE assets SET image_url=$1, drive_image_url=$1, video_clip_url=NULL, "
        "video_status=NULL, updated_at=now() WHERE id=$2 AND tenant_id=$3",
        stable, asset_id, tenant_id)
    return {"status": "completed", "message": f"Picture S{a['scene']}.{a['image_index']} redrawn"}


_MOTION_SYSTEM = (
    "You are a film director writing the CAMERA MOTION for grok-imagine image-to-video. Each shot "
    "already has a finished still, and its spoken line (if any) is assigned elsewhere — your ONLY job "
    "is to direct how the camera and the subject MOVE. Write ONE vivid, specific instruction per shot, "
    "precise enough that there is no guesswork.\n"
    "1) CAMERA: open with ONE definite move and say where it starts and where it ends — push-in / "
    "dolly-in, pull-back, pan left/right, tilt up/down, tracking, orbit/arc, dolly-zoom, slow zoom, or "
    "handheld sway. Add 'Unfixed lens' when the camera moves, 'Fixed lens' when it holds. Vary the move "
    "shot to shot; never repeat the same move twice in a row.\n"
    "2) KEEP THE SUBJECT IN FRAME: the main character stays visible for the WHOLE shot. If the move "
    "reveals something (a window, the water, an object), keep the character in frame while it does — "
    "never pan or tilt away onto an empty detail and lose them. Name the character and the SPECIFIC, "
    "physical thing they do: an expression change, a gesture, a head turn, eyes lifting, a breath — "
    "real and watchable, not a mood.\n"
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
        return turns + 1, 0, 0, turns + 1
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
        return (f"{i+1}. [{(r['shot_type'] or 'MS')}] {tag}{_camera_tag(r)}"
                f"{(r['sentence_text'] or r['image_prompt'] or '')[:200]}")
    shots = "\n".join(_shot(i, r) for i, r in enumerate(rows))
    user = (f"SCENE NARRATION (context):\n{narration[:2000]}\n\n"
            f"SHOTS (write ONE camera-motion line per shot, numbered, in order):\n{shots}")
    kwargs = dict(prompt=user, system_prompt=_MOTION_SYSTEM, max_tokens=1800, temperature=0.6)
    if model:
        kwargs["model"] = model
    text = (await claude.generate(**kwargs)) or ""
    motions = _parse_numbered(text, len(rows))
    written = 0
    for r, motion in zip(rows, motions):
        motion = _strip_embedded_line(motion) or "Slow push-in on the main subject, keeping it in frame."
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


async def generate_coverage_for_video(video_id, tenant_id, scene=None, progress=None):
    """Backend stage entry point: generate the burger-style COVERAGE for a video's scene(s) and
    store it in the app (frames as assets + the storyboard board), anchored on the LOCKED character
    sheets, drawn with GPT Image 2. Called by the pipeline route so the UI 'Generate' button runs
    coverage. Returns {status, message}. `progress(msg)` streams status to the task poller."""
    def _p(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    v = await fetch_one(
        "SELECT id, tenant_id, video_title, COALESCE(aspect_ratio,'16:9') AS aspect, "
        "image_style_override, visual_style, "
        "COALESCE(dialogue_audio,'voice_over') AS dialogue_audio "
        "FROM videos WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not v:
        return {"status": "failed", "error": "video not found"}
    vid, tenant, title, aspect = str(v["id"]), str(v["tenant_id"]), v["video_title"], v["aspect"]
    dialogue_audio = v["dialogue_audio"]  # channel pacing mode for _coverage_shape

    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
        "AND scene IS NOT NULL AND scene_text IS NOT NULL ORDER BY scene", vid, tenant)
    targets = [s for s in scenes if scene is None or s["scene"] == scene]
    if not targets:
        return {"status": "failed", "error": "no scenes with text to cover"}

    claude = await get_text_client_for_tenant(tenant)
    claude_model = "claude-sonnet-4-6" if type(claude).__name__ == "AnthropicDirectClient" else None
    kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
    ic = ImageClient(api_key=kie_key)
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
        cu = await resolve_cast_url(None, ic, story_bible=bible, profile=profile, aspect=aspect, outdir=base_dir)
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
                                        aspect=aspect, outdir=base_dir)
            cast_refs = [cu] if cu else []
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": f"couldn't build a cast from the script: {e}"}
    if not cast_refs:
        return {"status": "failed", "error": "no cast to anchor on — lock characters first"}

    # SCENE LOCK: same approved-environment conditioning for the real frames.
    envs = await _approved_envs(vid, tenant)

    total = 0
    for s in targets:
        sc = s["scene"]
        outdir = f"{base_dir}/scene{sc}"
        # Size coverage to the dialogue + the channel's pacing policy (see
        # _coverage_shape): echo/voice_over paces to runtime with earned
        # angles; grok_native keeps the rich cinematic multi-angle coverage.
        _mm, _amin, _amax, _mframes = _coverage_shape(s["scene_text"] or "", dialogue_audio)
        # THE GATE: if the storyboard step planned this scene and the script
        # hasn't changed since, draw THAT exact plan — the sheets the creator
        # reviewed are binding. An edited script invalidates the preview.
        directive = None
        board_urls: list = []
        saved = await fetch_one(
            "SELECT coverage_directive, coverage_directive_hash, "
            "storyboard_1_url, storyboard_2_url, storyboard_3_url, "
            "storyboard_4_url, storyboard_5_url FROM scripts "
            "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3", vid, tenant, sc)
        if saved and (saved.get("coverage_directive") or "").strip():
            if saved.get("coverage_directive_hash") == _scene_text_hash(s["scene_text"] or ""):
                directive = saved["coverage_directive"]
                # BOARD ANCHOR: these sheets were drawn FROM this exact directive
                # (the gate stores both together), so each shot can be pinned to
                # its approved panel — same framing, same character placement.
                board_urls = [saved.get(f"storyboard_{i}_url") for i in range(1, 6)]
                while board_urls and not board_urls[-1]:
                    board_urls.pop()
                anchored = " — matching the approved boards" if any(board_urls) else ""
                _p(f"Scene {sc}: drawing the storyboarded plan (GPT Image 2){anchored}…")
            else:
                _p(f"Scene {sc}: script changed since the storyboard — re-planning…")
        if directive is None:
            _p(f"Scene {sc}: planning + drawing coverage (GPT Image 2)…")
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
                board_urls=board_urls or None)
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

    return {"status": "completed", "message": f"Coverage done: {total} frames across {len(targets)} scene(s)"}


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
        claude_model = "claude-sonnet-4-6" if type(claude).__name__ == "AnthropicDirectClient" else None
        kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
        ic = ImageClient(api_key=kie_key)
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
        claude_model = "claude-sonnet-4-6" if type(claude).__name__ == "AnthropicDirectClient" else None
        kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
        ic = ImageClient(api_key=kie_key)
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
        claude_model = "claude-sonnet-4-6" if type(claude).__name__ == "AnthropicDirectClient" else None
        kie_key = await get_secret("kie_ai_api_key", tenant) or os.getenv("KIE_AI_API_KEY")
        ic = ImageClient(api_key=kie_key)
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
