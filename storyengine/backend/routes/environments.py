"""Per-video environment design — the location-consistency step.

Mirror of routes/characters.py, but for LOCATIONS. Each video gets a designed
reference image per Story Bible location (sunny_garden, vet_examination_room,
…), reviewed + approved before storyboards. At grid time, the storyboard grid
generation passes the location's reference image as a 2nd image_input (alongside
the cast sheet) so the setting stays consistent across panels.

Flow: after the Story Bible exists, the creator opens the Environments tab →
"Design environments" reads the bible's locations[] directly (the prose is
already there — no Claude call needed) and generates one wide establishing shot
per location in the video's visual style (~$0.025 each via the tenant's Kie key,
rendered at the video's aspect ratio so it matches the panel frame). Each card
can be regenerated, edited, or replaced with an upload. "Approve environments"
stamps videos.environments_approved_at and refines each description from its
actual generated image (vision pass) so downstream prompts agree with the refs.

CONTRACT (the pipeline executor consumes this): after design+approve,
  SELECT name, reference_url FROM video_environments
  WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL
returns the approved locations keyed by location id, and
videos.environments_approved_at is non-null.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one
from error_utils import humanize_error, user_facing

# Reuse the character helpers that are pure / table-agnostic.
from routes.characters import _drive_file_id, _parse_json, _persist_portrait_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["environments"])

KIE_CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
PORTRAIT_MODEL = "nano-banana-2"
MAX_ENVIRONMENTS = 12
TASK_TYPE = "environments"


class EnvironmentRead(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    reference_url: Optional[str] = None
    status: str = "draft"
    source: str = "generated"
    sort: int = 0


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _get_video(video_id: str, tenant_id) -> dict:
    video = await fetch_one(
        "SELECT id, video_title, script, image_style_override, original_dna, "
        "       story_bible, aspect_ratio, environments_approved_at, project_id "
        "FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


def _row_to_read(row: dict) -> EnvironmentRead:
    return EnvironmentRead(
        id=str(row["id"]),
        name=row.get("name") or "",
        description=row.get("description"),
        reference_url=row.get("reference_url"),
        status=row.get("status") or "draft",
        source=row.get("source") or "generated",
        sort=row.get("sort") or 0,
    )


def _extract_environments(video: dict) -> list[dict]:
    """Environment list for this video, read straight from the Story Bible's
    locations[] — each location is {id, type, lighting, description,
    color_temperature}. No Claude call needed (the bible already has the
    prose). Returns [{name, description}] keyed by location id, or [] if the
    bible has no locations (caller reports the video can skip this step)."""
    bible = _parse_json(video.get("story_bible"))
    if not bible or not isinstance(bible.get("locations"), list):
        return []
    envs = []
    for loc in bible["locations"][:MAX_ENVIRONMENTS]:
        if not isinstance(loc, dict):
            continue
        loc_id = (loc.get("id") or "").strip()
        if not loc_id:
            continue
        description = (loc.get("description", "") + ". Lighting: " + loc.get("lighting", "")).strip()
        envs.append({"name": loc_id, "description": description})
    return envs


async def _generate_environment(api_key: str, description: str, style_dna: str, aspect_ratio: str = "16:9") -> str:
    """One environment reference (wide establishing shot) via Kie (same job
    pattern as the character portrait generation). Rendered at the video's
    aspect ratio so it matches the panel frame. Returns the image URL."""
    style = (style_dna or "").strip()
    # Structured prompt with explicit slots so the art style can't get buried
    # behind the scene description (the drift cause). art_style + render_medium are
    # the SAME leading slots the character portraits use, so locations lock to the
    # exact medium the cast is drawn in.
    spec = {
        "art_style": style or "consistent illustrated style",
        "render_medium": (
            "render in the exact medium named in art_style and keep it identical for "
            "every image — do NOT switch to photorealism or flat 2D illustration unless "
            "art_style explicitly calls for it"
        ),
        "shot": "wide establishing shot, the location fills the frame",
        "scene": description.strip(),
        "people": "none — empty location, no characters present",
        "lighting": "clear, consistent time of day",
        "exclude": "no people, no text, no watermarks",
    }
    prompt = json.dumps(spec, ensure_ascii=False)
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
        create_resp = await client.post(
            KIE_CREATE_TASK_URL,
            json={"model": PORTRAIT_MODEL,
                  "input": {"prompt": prompt[:1800], "aspect_ratio": aspect_ratio or "16:9", "output_format": "png"}},
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
    raise RuntimeError("Environment generation timed out")


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@router.get("/{video_id}/environments")
async def list_environments(video_id: str, tenant_id=Depends(get_tenant_id)):
    video = await _get_video(video_id, tenant_id)
    rows = await fetch_all(
        "SELECT * FROM video_environments WHERE video_id = $1 AND tenant_id = $2 "
        "ORDER BY sort, created_at",
        video_id, tenant_id,
    )
    return {
        "environments": [_row_to_read(r).model_dump() for r in (rows or [])],
        "approved_at": str(video["environments_approved_at"]) if video.get("environments_approved_at") else None,
    }


@router.post("/{video_id}/environments/design")
async def design_environments(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    """Read the bible's locations and generate a reference per location
    (background task, progress via the shared /api/pipeline/task poller)."""
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
    aspect_ratio = video.get("aspect_ratio") or "16:9"

    _set_task_status(video_id, "running", "Reading the Story Bible for locations…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)

    async def _run():
        try:
            envs = _extract_environments(video)
            if not envs:
                _set_task_status(video_id, "failed",
                                 error=user_facing("No locations found in the Story Bible — this video can skip environment design."),
                                 tenant_id=tenant_id, task_type=TASK_TYPE)
                return

            # Replace prior generated drafts; keep uploaded/imported ones
            await execute(
                "DELETE FROM video_environments WHERE video_id = $1 AND tenant_id = $2 "
                "AND source = 'generated' AND status = 'draft'",
                video_id, tenant_id,
            )
            await execute(
                "UPDATE videos SET environments_approved_at = NULL WHERE id = $1 AND tenant_id = $2",
                video_id, tenant_id,
            )

            done = 0
            for i, env in enumerate(envs):
                _set_task_status(video_id, "running",
                                 f"Designing {env['name']} ({i + 1}/{len(envs)})…",
                                 tenant_id=tenant_id, task_type=TASK_TYPE)
                row = await fetch_one(
                    "INSERT INTO video_environments (tenant_id, video_id, name, description, sort) "
                    "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                    tenant_id, video_id, env["name"][:120], env.get("description") or "", i,
                )
                env_id = str(row["id"])
                try:
                    temp_url = await _generate_environment(
                        api_key, env.get("description") or env["name"], style_dna, aspect_ratio,
                    )
                    url = await _persist_portrait_url(tenant_id, video_id, env_id, temp_url)
                    await execute(
                        "UPDATE video_environments SET reference_url = $1, updated_at = now() WHERE id = $2",
                        url, env_id,
                    )
                    done += 1
                except Exception as e:
                    logger.warning("[environments] reference failed for %s: %s", env["name"], str(e)[:200])

            msg = f"Environments designed: {done}/{len(envs)} references ready — review, tweak, then approve."
            if done < len(envs):
                msg += " Some references failed — hit regenerate on the empty cards."
            _set_task_status(video_id, "completed", msg, tenant_id=tenant_id, task_type=TASK_TYPE)
        except Exception as e:
            _set_task_status(video_id, "failed",
                             error=user_facing(humanize_error(e, context="We couldn't design the environments")),
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return {"status": "running", "message": "Designing your environments — references take a minute."}


@router.post("/{video_id}/environments/{env_id}/regenerate")
async def regenerate_environment(
    video_id: str,
    env_id: str,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    video = await _get_video(video_id, tenant_id)
    env = await fetch_one(
        "SELECT * FROM video_environments WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        env_id, video_id, tenant_id,
    )
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    from vault import get_secret
    api_key = await get_secret("kie_ai_api_key", str(tenant_id))
    if not api_key:
        raise HTTPException(status_code=400, detail="Add your Kie.ai API key in Settings → Keys first.")

    from routes.pipeline import _get_task_status, _set_task_status, _clear_task_status
    task = _get_task_status(video_id, tenant_id)
    if task and task.get("status") == "running":
        raise HTTPException(status_code=409, detail="A task is already running for this video.")

    style_dna = video.get("image_style_override") or ""
    aspect_ratio = video.get("aspect_ratio") or "16:9"
    _set_task_status(video_id, "running", f"Redesigning {env['name']}…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)

    async def _run():
        try:
            temp_url = await _generate_environment(
                api_key, env.get("description") or env["name"], style_dna, aspect_ratio,
            )
            url = await _persist_portrait_url(tenant_id, video_id, env_id, temp_url)
            await execute(
                "UPDATE video_environments SET reference_url = $1, source = 'generated', "
                "status = 'draft', updated_at = now() WHERE id = $2 AND tenant_id = $3",
                url, env_id, tenant_id,
            )
            await execute(
                "UPDATE videos SET environments_approved_at = NULL WHERE id = $1 AND tenant_id = $2",
                video_id, tenant_id,
            )
            _set_task_status(video_id, "completed", f"{env['name']} redesigned — take a look.",
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        except Exception as e:
            _set_task_status(video_id, "failed",
                             error=user_facing(humanize_error(e, context=f"We couldn't redesign {env['name']}")),
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return {"status": "running", "message": f"Redesigning {env['name']}…"}


@router.patch("/{video_id}/environments/{env_id}")
async def update_environment(
    video_id: str,
    env_id: str,
    body: EnvironmentUpdate,
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
    params += [env_id, video_id, tenant_id]
    row = await fetch_one(
        f"UPDATE video_environments SET {', '.join(sets)}, updated_at = now() "
        f"WHERE id = ${len(params) - 2} AND video_id = ${len(params) - 1} AND tenant_id = ${len(params)} "
        "RETURNING *",
        *params,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Environment not found")
    return _row_to_read(row).model_dump()


@router.post("/{video_id}/environments/{env_id}/upload")
async def upload_environment_image(
    video_id: str,
    env_id: str,
    file: UploadFile = File(...),
    tenant_id=Depends(get_tenant_id),
):
    """Replace an environment's reference with the creator's own image."""
    await _get_video(video_id, tenant_id)
    env = await fetch_one(
        "SELECT id FROM video_environments WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        env_id, video_id, tenant_id,
    )
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 15 MB).")

    from storage import upload_bytes
    ext = (file.filename or "image.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"
    url = await upload_bytes(
        content, f"{video_id}/environments/{env_id}.{ext}",
        file.content_type or "image/png", str(tenant_id),
    )

    await execute(
        "UPDATE video_environments SET reference_url = $1, source = 'uploaded', "
        "status = 'draft', updated_at = now() WHERE id = $2 AND tenant_id = $3",
        url, env_id, tenant_id,
    )
    await execute(
        "UPDATE videos SET environments_approved_at = NULL WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "ok", "reference_url": url}


@router.delete("/{video_id}/environments/{env_id}")
async def delete_environment(video_id: str, env_id: str, tenant_id=Depends(get_tenant_id)):
    await _get_video(video_id, tenant_id)
    await execute(
        "DELETE FROM video_environments WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        env_id, video_id, tenant_id,
    )
    return {"status": "deleted"}


async def _sync_bible_to_locations(video_id: str, tenant_id, envs: list[dict]) -> None:
    """The storyboard prompts are written from the Story Bible — if its
    location descriptions disagree with the approved references, text and
    reference image fight each other and consistency dies. Overwrite bible
    location descriptions with the approved environments' (match by
    loc["id"] == env["name"])."""
    try:
        video = await fetch_one(
            "SELECT story_bible FROM videos WHERE id = $1 AND tenant_id = $2",
            video_id, tenant_id,
        )
        bible = _parse_json((video or {}).get("story_bible"))
        if not bible or not isinstance(bible.get("locations"), list):
            return
        by_id = {e["name"].strip(): e for e in envs if e.get("name")}
        changed = False
        for loc in bible["locations"]:
            if not isinstance(loc, dict):
                continue
            match = by_id.get((loc.get("id") or "").strip())
            if match and match.get("description"):
                loc["description"] = match["description"]
                changed = True
        if changed:
            await execute(
                "UPDATE videos SET story_bible = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
                json.dumps(bible), video_id, tenant_id,
            )
    except Exception as e:
        logger.warning("[environments] bible sync failed: %s", str(e)[:200])


@router.post("/{video_id}/environments/approve")
async def approve_environments(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Lock the environments: every location with a reference becomes
    'approved', videos.environments_approved_at is stamped, and storyboards
    unlock."""
    await _get_video(video_id, tenant_id)
    rows = await fetch_all(
        "SELECT * FROM video_environments WHERE video_id = $1 AND tenant_id = $2 ORDER BY sort, created_at",
        video_id, tenant_id,
    )
    with_refs = [r for r in (rows or []) if r.get("reference_url")]
    if not with_refs:
        raise HTTPException(status_code=400, detail="No environment references yet — design or upload at least one.")
    missing = [r["name"] for r in (rows or []) if not r.get("reference_url")]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"These environments have no image yet: {', '.join(missing[:4])}. Regenerate, upload, or delete them.",
        )

    await execute(
        "UPDATE video_environments SET status = 'approved', updated_at = now() "
        "WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )

    envs = [dict(r) for r in with_refs]

    # Pixel-accurate descriptions: the references were GENERATED from the bible
    # prose, but image models take liberties — when the saved text disagrees
    # with the approved reference, downstream prompts fight the reference and
    # the setting drifts. Rewrite each description from the actual approved
    # image (vision pass), best-effort per environment.
    try:
        from routes.model_video import _resolve_claude_creds
        from shared.clients.vision_client import vision_call, _looks_like_refusal
        creds = await _resolve_claude_creds(tenant_id)
        if creds:
            base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")
            for env in envs:
                fid = _drive_file_id(env.get("reference_url") or "")
                img_url = f"{base}/api/media/drive/{fid}" if fid else env.get("reference_url")
                try:
                    desc = await vision_call(
                        "Describe this location/setting EXACTLY so an image generator can redraw the SAME place: "
                        "architecture, props, lighting, and time of day. 40-60 words, no preamble. "
                        f"The location's name is {env['name']}.",
                        [img_url],
                        kie_key=creds["key"] if creds["provider"] == "kie" else None,
                        anthropic_key=creds["key"] if creds["provider"] == "anthropic" else None,
                        tier="fast", max_tokens=300,
                    )
                    # Never let a refusal / non-answer overwrite the bible-based
                    # description (vision_call already guards this; belt-and-
                    # suspenders so a regression can't reintroduce garbage anchors).
                    if desc and len(desc) > 20 and not _looks_like_refusal(desc):
                        env["description"] = desc.strip()[:1000]
                        await execute(
                            "UPDATE video_environments SET description = $1, updated_at = now() "
                            "WHERE id = $2 AND tenant_id = $3",
                            env["description"], env["id"], tenant_id,
                        )
                    elif desc:
                        logger.warning("[environments] kept original description for %s "
                                       "(vision reply looked invalid)", env["name"])
                except Exception as e:
                    logger.warning("[environments] vision description failed for %s: %s", env["name"], str(e)[:150])
    except Exception as e:
        logger.warning("[environments] vision sync skipped: %s", str(e)[:150])

    await _sync_bible_to_locations(video_id, tenant_id, envs)

    await execute(
        "UPDATE videos SET environments_approved_at = now(), updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "approved", "count": len(with_refs)}
