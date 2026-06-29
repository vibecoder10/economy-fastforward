"""Per-video character design — the character-consistency step.

Spec: docs/superpowers/specs/2026-06-10-creator-control-run.md (phase 2).

Flow: after the script exists, the creator opens the Characters tab →
"Design characters" extracts the cast (Story Bible characters when present,
otherwise Claude reads the script) and generates one portrait per character
in the video's visual style (~$0.025 each via the tenant's Kie key). Each
card can be regenerated, edited, or replaced with an upload. "Approve cast"
stamps videos.characters_approved_at and points
videos.character_reference_url at the primary character so the storyboard
bot's existing reference plumbing kicks in; ALL approved refs flow to grid
generation via pipeline.character_reference_urls.

Characters can be saved to the project (projects.character_references JSONB)
and imported into the next video — same family across a series.
"""

import asyncio
import io
import json
import logging
import os
import re
import uuid as _uuid
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one
from error_utils import humanize_error, user_facing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["characters"])

KIE_CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
PORTRAIT_MODEL = "nano-banana-2"
MAX_CHARACTERS = 8
TASK_TYPE = "characters"


class CharacterRead(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    reference_url: Optional[str] = None
    status: str = "draft"
    source: str = "generated"
    sort: int = 0


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ImportCastRequest(BaseModel):
    # When given, import only saved characters with these names; when omitted
    # (legacy callers), import all saved characters.
    names: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _get_video(video_id: str, tenant_id) -> dict:
    video = await fetch_one(
        "SELECT id, video_title, script, image_style_override, original_dna, "
        "       story_bible, characters_approved_at, project_id "
        "FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


def _row_to_read(row: dict) -> CharacterRead:
    return CharacterRead(
        id=str(row["id"]),
        name=row.get("name") or "",
        description=row.get("description"),
        reference_url=row.get("reference_url"),
        status=row.get("status") or "draft",
        source=row.get("source") or "generated",
        sort=row.get("sort") or 0,
    )


def _parse_json(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return None


async def _extract_cast(video: dict, api_key: str) -> list[dict]:
    """Cast list for this video: Story Bible characters when present,
    otherwise Claude reads the script. Returns [{name, description}]."""
    bible = _parse_json(video.get("story_bible"))
    if bible and isinstance(bible.get("characters"), list) and bible["characters"]:
        cast = []
        for ch in bible["characters"][:MAX_CHARACTERS]:
            name = (ch.get("name") or "").strip()
            if not name:
                continue
            desc_bits = [ch.get("description"), ch.get("costume"), ch.get("appearance")]
            cast.append({
                "name": name,
                "description": ". ".join(b.strip() for b in desc_bits if b)[:600],
            })
        if cast:
            return cast

    script = (video.get("script") or "").strip()
    if not script:
        raise ValueError(user_facing(
            "Write the script first — characters are designed from the cast that appears in it."
        ))

    from routes.model_video import _call_claude, _resolve_claude_creds  # provider-aware Claude
    creds = await _resolve_claude_creds(video["tenant_id"]) if video.get("tenant_id") else None
    if creds is None:
        creds = {"provider": "kie", "key": api_key}
    prompt = f"""Read this video narration script and list the RECURRING VISIBLE CHARACTERS
(people or creatures that appear on screen in more than one scene). Skip the narrator
unless they appear on camera. Maximum {MAX_CHARACTERS}.

SCRIPT:
{script[:12000]}

Return ONLY valid JSON:
{{"characters": [{{"name": "short name", "description": "physical appearance + exact outfit, written so an image generator draws the SAME character every time (40-80 words)"}}]}}"""
    text = await _call_claude(prompt, creds, tier="smart", max_tokens=2000)
    cast = (json.loads(text).get("characters") or [])[:MAX_CHARACTERS]
    return [c for c in cast if (c.get("name") or "").strip()]


async def _generate_portrait(api_key: str, description: str, style_dna: str, name: str = "") -> str:
    """One character MODEL SHEET via Kie (nano-banana-2). A polished animation-studio
    reference sheet — TURNAROUND (5 views) + EXPRESSIONS + POSE STUDIES + a left info
    panel — so every storyboard panel, clip and thumbnail can lock the character's full
    look, angles and emotions. The art_style leads so the cast and the locations share
    one medium (no 2D-vs-3D drift). Returns the image URL."""
    style = (style_dna or "").strip()
    art = style or "polished, colorful family-animation style"
    who = (name or "the character").strip()
    prompt = (
        f"Create a clean, professional CHARACTER MODEL SHEET (one single image) for {who}, an "
        f"original kid-friendly character, rendered in {art}. The character: {description.strip()}. "
        f"Render {who} IDENTICALLY in every view, expression and pose — same face, hair, body "
        "proportions, outfit, colors and accessories. Lay it out like a polished animation studio "
        "model sheet on a clean light lavender-gray studio background, with bold blue uppercase "
        "section headers, small readable labels, clean spacing and thin blue divider lines:\n"
        "• TURNAROUND across the top — a full-body row, five views left-to-right labeled FRONT, "
        "3/4 FRONT, SIDE, 3/4 BACK, BACK.\n"
        "• EXPRESSIONS in the middle — head-and-shoulders close-ups labeled SHOCKED, SAD, HAPPY, "
        "CONFUSED, ANGRY, EXCITED.\n"
        "• POSE STUDIES at the bottom — dynamic full-body action poses labeled REACHING FORWARD, "
        "KNEELING, POINTING, HANDS ON CHEEKS.\n"
        f"• A LEFT INFO PANEL with '{who.upper()}' as a large bold blue title, a one-word role, a few "
        "short personality keyword tags, and a color-palette swatch row. Keep ALL panel text minimal, "
        "large and correctly spelled — no long sentences or paragraphs of tiny text.\n"
        "Bright soft studio lighting, expressive faces, rounded clean shapes, sharp and uncluttered, "
        "consistent design in every cell. Avoid: realistic photography, real brand logos, extra "
        "unrelated characters, scene backgrounds, watermarks, distorted faces, mismatched outfits or "
        "proportions, malformed hands, paragraphs of tiny gibberish text, misspelled or blurry labels."
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
        create_resp = await client.post(
            KIE_CREATE_TASK_URL,
            json={"model": PORTRAIT_MODEL,
                  "input": {"prompt": prompt[:2400], "aspect_ratio": "4:3", "output_format": "png"}},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        if create_resp.status_code != 200:
            raise RuntimeError(f"Kie.ai {create_resp.status_code}: {create_resp.text[:200]}")
        data = create_resp.json().get("data") or {}
        task_id = data.get("task_id") or data.get("taskId")
        if not task_id:
            raise RuntimeError(f"No task id from Kie: {create_resp.text[:200]}")

        for _ in range(60):
            await asyncio.sleep(5)
            poll = await client.get(
                KIE_RECORD_INFO_URL,
                params={"taskId": task_id},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if poll.status_code != 200:
                continue
            pdata = poll.json().get("data") or {}
            state = str(pdata.get("state", "")).lower()
            if (pdata.get("status") == 3 or state in ("fail", "failed", "failure", "error")):
                raise RuntimeError(pdata.get("errorMessage") or pdata.get("failMsg") or "generation failed")
            result_json = pdata.get("resultJson")
            if result_json:
                if isinstance(result_json, str):
                    result_json = json.loads(result_json)
                urls = result_json.get("resultUrls") or []
                if urls:
                    return urls[0]
    raise RuntimeError("Portrait generation timed out")


async def _persist_portrait_url(tenant_id, video_id: str, char_id: str, temp_url: str) -> str:
    """Kie tempfile URLs expire — re-upload to permanent storage, best-effort."""
    try:
        from storage import upload_from_url
        return await upload_from_url(temp_url, f"{video_id}/characters/{char_id}.png",
                                     "image/png", str(tenant_id))
    except Exception as e:
        logger.warning("[characters] portrait persist failed (keeping temp URL): %s", str(e)[:200])
        return temp_url


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@router.get("/{video_id}/characters")
async def list_characters(video_id: str, tenant_id=Depends(get_tenant_id)):
    video = await _get_video(video_id, tenant_id)
    rows = await fetch_all(
        "SELECT * FROM video_characters WHERE video_id = $1 AND tenant_id = $2 "
        "ORDER BY sort, created_at",
        video_id, tenant_id,
    )
    return {
        "characters": [_row_to_read(r).model_dump() for r in (rows or [])],
        "approved_at": str(video["characters_approved_at"]) if video.get("characters_approved_at") else None,
    }


@router.post("/{video_id}/characters/generate")
async def design_characters(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    """Extract the cast and generate a portrait per character (background task,
    progress via the shared /api/pipeline/task poller)."""
    video = await _get_video(video_id, tenant_id)
    video["tenant_id"] = tenant_id

    from vault import get_secret
    api_key = await get_secret("kie_ai_api_key", str(tenant_id))
    if not api_key:
        raise HTTPException(status_code=400, detail="Add your Kie.ai API key in Settings → Keys first.")

    from routes.pipeline import _get_task_status, _set_task_status, _clear_task_status
    task = _get_task_status(video_id, tenant_id)
    if task and task.get("status") == "running":
        raise HTTPException(status_code=409, detail="A task is already running for this video.")

    style_dna = video.get("image_style_override") or ""

    _set_task_status(video_id, "running", "Reading the script for the cast…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)

    async def _run():
        try:
            cast = await _extract_cast(video, api_key)
            if not cast:
                _set_task_status(video_id, "failed",
                                 error=user_facing("No recurring characters found in this script — this video can skip character design."),
                                 tenant_id=tenant_id, task_type=TASK_TYPE)
                return

            # Replace prior generated drafts; keep uploaded/imported ones
            await execute(
                "DELETE FROM video_characters WHERE video_id = $1 AND tenant_id = $2 "
                "AND source = 'generated' AND status = 'draft'",
                video_id, tenant_id,
            )
            await execute(
                "UPDATE videos SET characters_approved_at = NULL WHERE id = $1 AND tenant_id = $2",
                video_id, tenant_id,
            )

            done = 0
            for i, ch in enumerate(cast):
                _set_task_status(video_id, "running",
                                 f"Designing {ch['name']} ({i + 1}/{len(cast)})…",
                                 tenant_id=tenant_id, task_type=TASK_TYPE)
                row = await fetch_one(
                    "INSERT INTO video_characters (tenant_id, video_id, name, description, sort) "
                    "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                    tenant_id, video_id, ch["name"][:120], ch.get("description") or "", i,
                )
                char_id = str(row["id"])
                # Retry each portrait before giving up — one transient blip (a Kie
                # hiccup, an SSL error, a vision refusal) used to silently drop the
                # portrait, leaving an empty card that then BLOCKS approve ("Maria has
                # no image yet"). 3 tries means a flake no longer stalls the whole cast.
                last_err = None
                for attempt in range(3):
                    try:
                        temp_url = await _generate_portrait(api_key, ch.get("description") or ch["name"], style_dna, name=ch.get("name") or "")
                        url = await _persist_portrait_url(tenant_id, video_id, char_id, temp_url)
                        await execute(
                            "UPDATE video_characters SET reference_url = $1, updated_at = now() WHERE id = $2",
                            url, char_id,
                        )
                        done += 1
                        last_err = None
                        break
                    except Exception as e:
                        last_err = e
                        await asyncio.sleep(2 * (attempt + 1))
                if last_err is not None:
                    logger.warning("[characters] portrait failed for %s after 3 tries: %s", ch["name"], str(last_err)[:200])

            msg = f"Cast designed: {done}/{len(cast)} portraits ready — review, tweak, then approve."
            if done < len(cast):
                msg += " Some portraits failed — hit regenerate on the empty cards."
            _set_task_status(video_id, "completed", msg, tenant_id=tenant_id, task_type=TASK_TYPE)
        except Exception as e:
            _set_task_status(video_id, "failed",
                             error=user_facing(humanize_error(e, context="We couldn't design the characters")),
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return {"status": "running", "message": "Designing your cast — portraits take a minute."}


@router.post("/{video_id}/characters/{char_id}/regenerate")
async def regenerate_character(
    video_id: str,
    char_id: str,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    video = await _get_video(video_id, tenant_id)
    char = await fetch_one(
        "SELECT * FROM video_characters WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        char_id, video_id, tenant_id,
    )
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")

    from vault import get_secret
    api_key = await get_secret("kie_ai_api_key", str(tenant_id))
    if not api_key:
        raise HTTPException(status_code=400, detail="Add your Kie.ai API key in Settings → Keys first.")

    from routes.pipeline import _get_task_status, _set_task_status, _clear_task_status
    task = _get_task_status(video_id, tenant_id)
    if task and task.get("status") == "running":
        raise HTTPException(status_code=409, detail="A task is already running for this video.")

    style_dna = video.get("image_style_override") or ""
    _set_task_status(video_id, "running", f"Redesigning {char['name']}…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)

    async def _run():
        try:
            temp_url = await _generate_portrait(api_key, char.get("description") or char["name"], style_dna, name=char.get("name") or "")
            url = await _persist_portrait_url(tenant_id, video_id, char_id, temp_url)
            await execute(
                "UPDATE video_characters SET reference_url = $1, source = 'generated', "
                "status = 'draft', updated_at = now() WHERE id = $2 AND tenant_id = $3",
                url, char_id, tenant_id,
            )
            await execute(
                "UPDATE videos SET characters_approved_at = NULL WHERE id = $1 AND tenant_id = $2",
                video_id, tenant_id,
            )
            _set_task_status(video_id, "completed", f"{char['name']} redesigned — take a look.",
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        except Exception as e:
            _set_task_status(video_id, "failed",
                             error=user_facing(humanize_error(e, context=f"We couldn't redesign {char['name']}")),
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return {"status": "running", "message": f"Redesigning {char['name']}…"}


@router.patch("/{video_id}/characters/{char_id}")
async def update_character(
    video_id: str,
    char_id: str,
    body: CharacterUpdate,
    tenant_id=Depends(get_tenant_id),
):
    await _get_video(video_id, tenant_id)
    sets, params = [], []
    if body.name is not None:
        params.append(body.name.strip()[:120]); sets.append(f"name = ${len(params)}")
    if body.description is not None:
        params.append(body.description.strip()[:1000]); sets.append(f"description = ${len(params)}")
    if not sets:
        return {"status": "unchanged"}
    params += [char_id, video_id, tenant_id]
    row = await fetch_one(
        f"UPDATE video_characters SET {', '.join(sets)}, updated_at = now() "
        f"WHERE id = ${len(params) - 2} AND video_id = ${len(params) - 1} AND tenant_id = ${len(params)} "
        "RETURNING *",
        *params,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")
    return _row_to_read(row).model_dump()


@router.post("/{video_id}/characters/{char_id}/upload")
async def upload_character_image(
    video_id: str,
    char_id: str,
    file: UploadFile = File(...),
    tenant_id=Depends(get_tenant_id),
):
    """Replace a character's reference with the creator's own image."""
    await _get_video(video_id, tenant_id)
    char = await fetch_one(
        "SELECT id FROM video_characters WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        char_id, video_id, tenant_id,
    )
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 15 MB).")

    from storage import upload_bytes
    ext = (file.filename or "image.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"
    url = await upload_bytes(
        content, f"{video_id}/characters/{char_id}.{ext}",
        file.content_type or "image/png", str(tenant_id),
    )

    await execute(
        "UPDATE video_characters SET reference_url = $1, source = 'uploaded', "
        "status = 'draft', updated_at = now() WHERE id = $2 AND tenant_id = $3",
        url, char_id, tenant_id,
    )
    await execute(
        "UPDATE videos SET characters_approved_at = NULL WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "ok", "reference_url": url}


@router.delete("/{video_id}/characters/{char_id}")
async def delete_character(video_id: str, char_id: str, tenant_id=Depends(get_tenant_id)):
    await _get_video(video_id, tenant_id)
    await execute(
        "DELETE FROM video_characters WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        char_id, video_id, tenant_id,
    )
    return {"status": "deleted"}


def _drive_file_id(url: str):
    m = re.search(r"[?&]id=([\w-]+)", url or "") or re.search(r"/drive/([\w-]+)", url or "")
    return m.group(1) if m else None


async def _fetch_image_bytes(url: str) -> bytes:
    """Portrait bytes for cast-sheet composition.

    Drive files are fetched through the PUBLIC media proxy (plain HTTP), not the
    authorized Drive API: the backend process has no Google OAuth creds, so the
    API path raised "Google OAuth credentials not found" and _build_cast_sheet
    silently returned None — every video then fell back to a SINGLE-character
    reference (the first portrait), so only one character locked and the rest
    drifted (live: a white cast rendered as a different family). The proxy is the
    same URL Kie fetches for generation, so it is known-good and needs no creds.
    """
    fid = _drive_file_id(url)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        if fid and "drive.google.com" in url:
            base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")
            r = await client.get(f"{base}/api/media/drive/{fid}")
        else:
            r = await client.get(url)
        r.raise_for_status()
        return r.content


async def _build_cast_sheet(tenant_id, video_id: str, cast: list[dict]) -> Optional[str]:
    """ONE labeled reference image beats N competing portraits: compose the
    approved cast into a single sheet (portrait + name under each) so the
    image model can map names in the prompt to faces in the reference.
    Returns the stored URL, or None on failure (callers degrade gracefully)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        tiles = []
        for ch in cast[:8]:
            raw = await _fetch_image_bytes(ch["reference_url"])
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            img.thumbnail((512, 512))
            tile = Image.new("RGB", (512, 572), (245, 245, 245))
            tile.paste(img, ((512 - img.width) // 2, (512 - img.height) // 2))
            draw = ImageDraw.Draw(tile)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
            except Exception:
                font = ImageFont.load_default()
            name = ch["name"][:24]
            bbox = draw.textbbox((0, 0), name, font=font)
            draw.text(((512 - (bbox[2] - bbox[0])) // 2, 522), name, fill=(10, 10, 10), font=font)
            tiles.append(tile)
        if not tiles:
            return None
        sheet = Image.new("RGB", (512 * len(tiles), 572), (245, 245, 245))
        for i, t in enumerate(tiles):
            sheet.paste(t, (512 * i, 0))
        buf = io.BytesIO()
        sheet.save(buf, format="PNG")
        from storage import upload_bytes
        return await upload_bytes(buf.getvalue(), f"{video_id}/characters/cast-sheet.png",
                                  "image/png", str(tenant_id))
    except Exception as e:
        logger.warning("[characters] cast sheet build failed: %s", str(e)[:200])
        return None


async def _sync_bible_to_cast(video_id: str, tenant_id, cast: list[dict]) -> None:
    """The storyboard prompts are written from the Story Bible — if its
    character descriptions disagree with the approved portraits, text and
    reference image fight each other and consistency dies. Overwrite bible
    descriptions with the approved cast's."""
    try:
        video = await fetch_one(
            "SELECT story_bible FROM videos WHERE id = $1 AND tenant_id = $2",
            video_id, tenant_id,
        )
        bible = _parse_json((video or {}).get("story_bible"))
        if not bible or not isinstance(bible.get("characters"), list):
            return
        by_name = {c["name"].strip().lower(): c for c in cast if c.get("name")}
        changed = False
        for ch in bible["characters"]:
            # Bible characters key on `id` ("tom"), NOT `name` — matching only on
            # `name` silently failed, so the bible kept its invented costumes
            # (Tom in a hoodie, Dad in glasses) and fought the approved cast.
            key = (ch.get("name") or ch.get("id") or "").strip().lower()
            match = by_name.get(key)
            if match and match.get("description"):
                ch["description"] = match["description"]
                ch["costume"] = match["description"]
                changed = True
        if changed:
            await execute(
                "UPDATE videos SET story_bible = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
                json.dumps(bible), video_id, tenant_id,
            )
    except Exception as e:
        logger.warning("[characters] bible sync failed: %s", str(e)[:200])


@router.post("/{video_id}/characters/approve")
async def approve_cast(video_id: str, background_tasks: BackgroundTasks, tenant_id=Depends(get_tenant_id)):
    """Lock the cast: every character with a reference becomes 'approved',
    the primary ref lands on videos.character_reference_url (the storyboard
    bot's existing input), and storyboards unlock.

    The heavy part (a per-character vision pass that rewrites each description
    from its approved portrait, then the cast-sheet build) runs as a background
    task with progress, so the UI shows "Locking in Tom (1/4)…" instead of a
    silent multi-minute spinner that looked hung.
    """
    await _get_video(video_id, tenant_id)
    rows = await fetch_all(
        "SELECT * FROM video_characters WHERE video_id = $1 AND tenant_id = $2 ORDER BY sort, created_at",
        video_id, tenant_id,
    )
    with_refs = [r for r in (rows or []) if r.get("reference_url")]
    if not with_refs:
        raise HTTPException(status_code=400, detail="No character references yet — design or upload at least one.")
    missing = [r["name"] for r in (rows or []) if not r.get("reference_url")]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"These characters have no image yet: {', '.join(missing[:4])}. Regenerate, upload, or delete them.",
        )

    from routes.pipeline import _get_task_status, _set_task_status, _clear_task_status
    task = _get_task_status(video_id, tenant_id)
    if task and task.get("status") == "running":
        raise HTTPException(status_code=409, detail="A task is already running for this video.")

    _set_task_status(video_id, "running", "Locking in the cast…", tenant_id=tenant_id, task_type=TASK_TYPE)

    async def _run():
        try:
            await execute(
                "UPDATE video_characters SET status = 'approved', updated_at = now() "
                "WHERE video_id = $1 AND tenant_id = $2",
                video_id, tenant_id,
            )
            cast = [dict(r) for r in with_refs]

            # Pixel-accurate descriptions: the portraits were GENERATED from the
            # text, but image models take liberties — when the saved text says
            # "light blue tee" and the approved portrait shows red, downstream
            # prompts fight the reference sheet and costumes drift. Rewrite each
            # description from the actual approved image (vision pass),
            # best-effort per character.
            try:
                from routes.model_video import _resolve_claude_creds
                from shared.clients.vision_client import vision_call, _looks_like_refusal
                creds = await _resolve_claude_creds(tenant_id)
                if creds:
                    base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")
                    for idx, ch in enumerate(cast):
                        _set_task_status(
                            video_id, "running",
                            f"Locking in {ch['name']} ({idx + 1}/{len(cast)})…",
                            tenant_id=tenant_id, task_type=TASK_TYPE,
                        )
                        fid = _drive_file_id(ch.get("reference_url") or "")
                        img_url = f"{base}/api/media/drive/{fid}" if fid else ch.get("reference_url")
                        try:
                            desc = await vision_call(
                                f"Describe EXACTLY how this character looks so an image generator can redraw the SAME character: "
                                f"hair (style + color), face/age, and every clothing item WITH ITS COLOR. "
                                f"40-60 words, no preamble. The character's name is {ch['name']}.",
                                [img_url],
                                kie_key=creds["key"] if creds["provider"] == "kie" else None,
                                anthropic_key=creds["key"] if creds["provider"] == "anthropic" else None,
                                tier="fast", max_tokens=300,
                            )
                            # Never let a refusal / non-answer overwrite the
                            # script-based description (vision_call already guards
                            # this; belt-and-suspenders so a regression can't
                            # reintroduce garbage anchors).
                            if desc and len(desc) > 20 and not _looks_like_refusal(desc):
                                ch["description"] = desc.strip()[:1000]
                                await execute(
                                    "UPDATE video_characters SET description = $1, updated_at = now() "
                                    "WHERE id = $2 AND tenant_id = $3",
                                    ch["description"], ch["id"], tenant_id,
                                )
                            elif desc:
                                logger.warning("[characters] kept original description for %s "
                                               "(vision reply looked invalid)", ch["name"])
                        except Exception as e:
                            logger.warning("[characters] vision description failed for %s: %s", ch["name"], str(e)[:150])
            except Exception as e:
                logger.warning("[characters] vision sync skipped: %s", str(e)[:150])

            _set_task_status(video_id, "running", "Building the cast sheet…",
                             tenant_id=tenant_id, task_type=TASK_TYPE)
            sheet_url = await _build_cast_sheet(tenant_id, video_id, cast)
            await _sync_bible_to_cast(video_id, tenant_id, cast)

            await execute(
                "UPDATE videos SET characters_approved_at = now(), character_reference_url = $1, "
                "updated_at = now() WHERE id = $2 AND tenant_id = $3",
                sheet_url or with_refs[0]["reference_url"], video_id, tenant_id,
            )
            _set_task_status(video_id, "completed",
                             f"Cast approved ({len(with_refs)}) — storyboards unlocked.",
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        except Exception as e:
            _set_task_status(video_id, "failed",
                             error=user_facing(humanize_error(e, context="We couldn't approve the cast")),
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return {"status": "running", "message": "Approving the cast — locking in each face."}


@router.post("/{video_id}/characters/save-to-project")
async def save_cast_to_project(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Keep this cast for the series: copies into projects.character_references."""
    video = await _get_video(video_id, tenant_id)
    if not video.get("project_id"):
        raise HTTPException(status_code=400, detail="Video has no project.")
    rows = await fetch_all(
        "SELECT name, description, reference_url FROM video_characters "
        "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
        "ORDER BY sort, created_at",
        video_id, tenant_id,
    )
    if not rows:
        raise HTTPException(status_code=400, detail="No characters with images to save.")

    project = await fetch_one(
        "SELECT character_references FROM projects WHERE id = $1 AND tenant_id = $2",
        video["project_id"], tenant_id,
    )
    existing = _parse_json((project or {}).get("character_references")) or []
    by_name = {c.get("name"): c for c in existing if isinstance(c, dict)}
    for r in rows:
        by_name[r["name"]] = {
            "name": r["name"],
            "description": r.get("description") or "",
            "reference_url": r["reference_url"],
        }
    await execute(
        "UPDATE projects SET character_references = $1, updated_at = now() "
        "WHERE id = $2 AND tenant_id = $3",
        json.dumps(list(by_name.values())), video["project_id"], tenant_id,
    )
    return {"status": "saved", "count": len(rows)}


@router.get("/{video_id}/characters/project-cast")
async def list_project_cast(video_id: str, tenant_id=Depends(get_tenant_id)):
    """The project's saved cast, for the "Use Saved Cast" picker. Flags which
    are already in this video so the picker can pre-skip them."""
    video = await _get_video(video_id, tenant_id)
    if not video.get("project_id"):
        return {"characters": [], "has_project": False}
    project = await fetch_one(
        "SELECT character_references FROM projects WHERE id = $1 AND tenant_id = $2",
        video["project_id"], tenant_id,
    )
    saved = _parse_json((project or {}).get("character_references")) or []
    existing = await fetch_all(
        "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    existing_names = {r["name"] for r in (existing or [])}
    out = []
    for c in saved:
        if not (isinstance(c, dict) and c.get("reference_url")):
            continue
        name = c.get("name") or "Character"
        out.append({
            "name": name,
            "description": (c.get("description") or "")[:400],
            "reference_url": c["reference_url"],
            "already_in_video": name in existing_names,
        })
    return {"characters": out, "has_project": True}


@router.post("/{video_id}/characters/import-from-project")
async def import_cast_from_project(
    video_id: str,
    body: Optional[ImportCastRequest] = None,
    tenant_id=Depends(get_tenant_id),
):
    """Use the project's saved cast (series consistency) for this video. When
    `names` is given, only those are imported (the picker); otherwise all
    saved characters are imported (legacy)."""
    video = await _get_video(video_id, tenant_id)
    if not video.get("project_id"):
        raise HTTPException(status_code=400, detail="Video has no project.")
    project = await fetch_one(
        "SELECT character_references FROM projects WHERE id = $1 AND tenant_id = $2",
        video["project_id"], tenant_id,
    )
    saved = _parse_json((project or {}).get("character_references")) or []
    saved = [c for c in saved if isinstance(c, dict) and c.get("reference_url")]
    if not saved:
        raise HTTPException(status_code=400, detail="No saved characters on this project yet.")

    selected = {n for n in (body.names or [])} if (body and body.names) else None

    existing = await fetch_all(
        "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    existing_names = {r["name"] for r in (existing or [])}
    imported = 0
    for i, c in enumerate(saved[:MAX_CHARACTERS]):
        name = c.get("name")
        if selected is not None and name not in selected:
            continue
        if name in existing_names:
            continue
        await execute(
            "INSERT INTO video_characters (tenant_id, video_id, name, description, reference_url, source, sort) "
            "VALUES ($1, $2, $3, $4, $5, 'project', $6)",
            tenant_id, video_id, (name or "Character")[:120],
            (c.get("description") or "")[:1000], c["reference_url"], 100 + i,
        )
        imported += 1
    return {"status": "imported", "count": imported}
