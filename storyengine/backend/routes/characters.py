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
import json
import logging
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


async def _generate_portrait(api_key: str, description: str, style_dna: str) -> str:
    """One character reference portrait via Kie (same job pattern as
    visual_styles character generation). Returns the image URL."""
    style = (style_dna or "").strip()
    prompt = (
        f"Character reference sheet portrait: {description.strip()}. "
        f"{('Visual style: ' + style + '. ') if style else ''}"
        "Full body, facing camera, neutral plain background, even lighting, "
        "the character fills the frame. No text, no watermarks."
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
        create_resp = await client.post(
            KIE_CREATE_TASK_URL,
            json={"model": PORTRAIT_MODEL,
                  "input": {"prompt": prompt[:1800], "aspect_ratio": "1:1", "output_format": "png"}},
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
                try:
                    temp_url = await _generate_portrait(api_key, ch.get("description") or ch["name"], style_dna)
                    url = await _persist_portrait_url(tenant_id, video_id, char_id, temp_url)
                    await execute(
                        "UPDATE video_characters SET reference_url = $1, updated_at = now() WHERE id = $2",
                        url, char_id,
                    )
                    done += 1
                except Exception as e:
                    logger.warning("[characters] portrait failed for %s: %s", ch["name"], str(e)[:200])

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
            temp_url = await _generate_portrait(api_key, char.get("description") or char["name"], style_dna)
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


@router.post("/{video_id}/characters/approve")
async def approve_cast(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Lock the cast: every character with a reference becomes 'approved',
    the primary ref lands on videos.character_reference_url (the storyboard
    bot's existing input), and storyboards unlock."""
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

    await execute(
        "UPDATE video_characters SET status = 'approved', updated_at = now() "
        "WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    await execute(
        "UPDATE videos SET characters_approved_at = now(), character_reference_url = $1, "
        "updated_at = now() WHERE id = $2 AND tenant_id = $3",
        with_refs[0]["reference_url"], video_id, tenant_id,
    )
    return {"status": "approved", "count": len(with_refs)}


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


@router.post("/{video_id}/characters/import-from-project")
async def import_cast_from_project(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Use the project's saved cast (series consistency) for this video."""
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

    existing = await fetch_all(
        "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    existing_names = {r["name"] for r in (existing or [])}
    imported = 0
    for i, c in enumerate(saved[:MAX_CHARACTERS]):
        if c.get("name") in existing_names:
            continue
        await execute(
            "INSERT INTO video_characters (tenant_id, video_id, name, description, reference_url, source, sort) "
            "VALUES ($1, $2, $3, $4, $5, 'project', $6)",
            tenant_id, video_id, (c.get("name") or "Character")[:120],
            (c.get("description") or "")[:1000], c["reference_url"], 100 + i,
        )
        imported += 1
    return {"status": "imported", "count": imported}
