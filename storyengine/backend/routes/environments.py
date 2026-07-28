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
from pydantic import BaseModel, field_validator

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one
from error_utils import humanize_error, user_facing
from generation_ledger import record_ledger_entry

# Reuse the character helpers that are pure / table-agnostic (_budget_refusal is
# the SAME per-video spend-cap guard the character routes use — money-safety
# fix, both stages share one implementation instead of a second copy).
from routes.characters import _budget_refusal, _drive_file_id, _parse_json, _persist_portrait_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["environments"])

KIE_CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
PORTRAIT_MODEL = "nano-banana-2"
MAX_ENVIRONMENTS = 12
TASK_TYPE = "environments"
# C4 prop manifest: 6-8 is the target extraction count; 10 is the hard cap
# accepted from a creator edit (routes match the migration's doc comment).
MAX_PROPS = 10


class PropItem(BaseModel):
    """One entry in an environment's canonical prop manifest (migration 115).
    Kept intentionally tiny — a name and where it sits — because this gets
    rendered VERBATIM into prompts (storyboard.bot.render_prop_manifest),
    never re-paraphrased."""
    name: str
    position: str

    @field_validator("name", "position")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must not be empty")
        return v[:200]


class EnvironmentRead(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    reference_url: Optional[str] = None
    status: str = "draft"
    source: str = "generated"
    sort: int = 0
    props: Optional[list[PropItem]] = None


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    props: Optional[list[PropItem]] = None

    @field_validator("props")
    @classmethod
    def _max_props(cls, v):
        if v is not None and len(v) > MAX_PROPS:
            raise ValueError(f"at most {MAX_PROPS} props")
        return v


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _get_video(video_id: str, tenant_id) -> dict:
    video = await fetch_one(
        "SELECT id, video_title, script, image_style_override, original_dna, "
        "       story_bible, aspect_ratio, environments_approved_at, project_id, "
        "       total_cost, max_spend "
        "FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


def _row_to_read(row: dict) -> EnvironmentRead:
    props = _parse_json(row.get("props")) or None
    return EnvironmentRead(
        id=str(row["id"]),
        name=row.get("name") or "",
        description=row.get("description"),
        reference_url=row.get("reference_url"),
        status=row.get("status") or "draft",
        source=row.get("source") or "generated",
        sort=row.get("sort") or 0,
        props=props if isinstance(props, list) else None,
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


async def _extract_locations_from_script(video: dict, api_key: str) -> list[dict]:
    """Recurring locations read straight from the script — the fallback used when
    the Story Bible has no locations yet (it's generated later, at the image step,
    so it's empty during environment design). Mirrors characters._extract_cast's
    script fallback so environments work the same way characters already do.
    Returns [{name, description}] (possibly empty)."""
    script = (video.get("script") or "").strip()
    if not script:
        return []
    from routes.model_video import _call_claude, _resolve_claude_creds  # provider-aware Claude
    creds = await _resolve_claude_creds(video["tenant_id"]) if video.get("tenant_id") else None
    if creds is None:
        creds = {"provider": "kie", "key": api_key}
    prompt = f"""Read this script and list every VISUALLY DISTINCT location shown on screen — one
environment per place that LOOKS different and would need its OWN reference image. Two rooms in
the same building are SEPARATE environments if they look different: a kitchen and a garage are
TWO environments, not one "home"; an indoor room and an outdoor shore are separate. ONLY merge
shots of the literally same room/place (e.g. two angles of the same kitchen). Skip one-off
throwaway mentions. Maximum {MAX_ENVIRONMENTS}.

SCRIPT:
{script[:12000]}

Return ONLY valid JSON:
{{"locations": [{{"name": "short SPECIFIC place name (e.g. 'Kitchen', 'Garage', 'Lake shore' — never a combined 'Home/Garage')", "description": "what the place looks like + its lighting/time of day, written so an image generator draws the SAME place every time (40-80 words). NEVER mention knives, blades, scissors, sharp tools or weapons — describe food as already prepared, utensils as spoons/wooden tools"}}]}}"""
    try:
        text = await _call_claude(prompt, creds, tier="smart", max_tokens=2000)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        locs = (json.loads(text).get("locations") or [])[:MAX_ENVIRONMENTS]
    except Exception as e:
        logger.warning("[environments] script location extraction failed: %s", str(e)[:200])
        return []
    return [
        {"name": (l.get("name") or "").strip(), "description": (l.get("description") or "").strip()}
        for l in locs if isinstance(l, dict) and (l.get("name") or "").strip()
    ]


async def _generate_environment(api_key: str, description: str, style_dna: str, aspect_ratio: str = "16:9") -> dict:
    """One environment reference (wide establishing shot) via Kie (same job
    pattern as the character portrait generation). Rendered at the video's
    aspect ratio so it matches the panel frame. Returns {'url', 'model', 'task_id'}
    — model/task_id (money-safety fix) let the caller ledger this real spend
    against whichever model ACTUALLY generated it, same as _generate_portrait."""
    # Same two style guards the storyboard/cast/director seam (_resolve_style)
    # applies: scrub studio names (they read as IP references to the filter),
    # then make a stylized medium carry an explicit photorealism ban. Without
    # the ban this exact slot drew a near-photoreal 'cooking class kitchen'
    # ref on video cd5d2883 (2026-07-21) that then dragged every nano
    # storyboard panel's background photoreal — the env ref conditions every
    # sheet draw, so its medium IS the boards' medium.
    from scripts.coverage_to_app import _enforce_stylized_media, _neutralize_style_brands
    style = _enforce_stylized_media(_neutralize_style_brands((style_dna or "").strip()))
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
        # knives/blades joined the exclude list 2026-07-21: a knife the model
        # staged by its own liberty on a kitchen env ref rode into EVERY shot
        # of the scene as a reference image and randomly tripped GPT Image 2's
        # output filter all run long (video cd5d2883). The drawn IMAGE is the
        # trigger — no shot-prompt wording can fix it — so the object must
        # never exist in the reference at all.
        "exclude": ("no people, no text, no watermarks, no knives, blades, scissors, "
                    "sharp tools or weapons of any kind — food shown already prepared"),
    }
    prompt = json.dumps(spec, ensure_ascii=False)
    # GPT Image 2 first, intelligent nano-banana-2 fallback (shared ImageClient) — locations
    # have no kid-content obstacle, so they render on GPT Image 2; nano only on a real outage.
    from shared.clients.image_client import ImageClient
    # 1K, not the client's 2K default — an env ref is a style/layout anchor,
    # not a deliverable, and 1K halves its cost (Ryan, 2026-07-21).
    task_ids: list = []
    res = await ImageClient(api_key=api_key).generate_scene_image_gpt(
        prompt, None, aspect_ratio=aspect_ratio or "16:9", resolution="1K", task_id_out=task_ids)
    url = (res or {}).get("url")
    if not url:
        raise RuntimeError("Environment generation failed")
    return {
        "url": url,
        "model": (res or {}).get("model") or "gpt-image-2",
        "task_id": task_ids[-1] if task_ids else None,
    }


async def _extract_env_props(env_name: str, description: str, img_url: str, creds: dict) -> list[dict]:
    """One-time LLM prop-manifest extraction (C4) from an environment's approved
    reference image: 6-8 {name, position} objects, authored ONCE at approval and
    from then on injected VERBATIM everywhere a shot's prompt is built (see
    storyboard.bot.render_prop_manifest) — never re-paraphrased by a fresh LLM
    call per scene, which is the proven drift source (stove/fridge swapped
    within one setup, whole kitchen swapped by shot 125).

    Reuses the SAME vision_call helper (and provider-chain/creds pattern) the
    description-refresh vision pass above already uses — no new client.

    Can raise (network/parse/refusal) — the CALLER must treat this as
    fail-soft: log loudly, leave props NULL, never block approval. This is a
    one-time pennies call per environment; no test in this repo may invoke it
    for real (mock vision_call)."""
    from shared.clients.vision_client import vision_call, _looks_like_refusal
    prompt = (
        "List the 6-8 MOVABLE PROPS visible in this location reference image — the "
        "specific objects a set dresser would place (never walls, floors, built-in "
        "cabinetry, or architecture). For each, give a short name and where it sits "
        f"in the frame. The location is {env_name}: {(description or '').strip()[:300]}\n\n"
        'Return ONLY valid JSON, no preamble: {"props": [{"name": "...", "position": "..."}]}'
    )
    text = await vision_call(
        prompt, [img_url],
        kie_key=creds["key"] if creds["provider"] == "kie" else None,
        anthropic_key=creds["key"] if creds["provider"] == "anthropic" else None,
        tier="fast", max_tokens=500,
    )
    if not text or _looks_like_refusal(text):
        raise RuntimeError(f"no usable prop-extraction reply for {env_name}")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    data = json.loads(text)
    raw = data.get("props") or []
    out = []
    for p in raw[:MAX_PROPS]:
        if not isinstance(p, dict):
            continue
        name = (p.get("name") or "").strip()
        position = (p.get("position") or "").strip()
        if name and position:
            out.append({"name": name[:200], "position": position[:200]})
    if not out:
        raise RuntimeError(f"prop-extraction reply parsed to zero usable props for {env_name}")
    return out[:8]


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


async def run_environments_design_step(
    video: dict, tenant_id, *, progress=None,
) -> dict:
    """The awaitable core of environment design — extracted (feat/approval-
    gates) so actions.make_autobuild_step's anchors checkpoint can run this
    step directly, IN LINE, and know when it's actually finished, rather
    than firing a detached background task the way the route below does.
    Returns {"status": "completed"/"failed", "message"/"error": ...} —
    same shape as PipelineExecutor.run_characters, its sibling call in the
    autobuild chain.

    NOT skip-if-done: always deletes prior generated drafts and regenerates
    every location, exactly like the pre-extraction version of this
    function did (unchanged behavior for the existing route below). Callers
    that must not re-spend on a video that already has locations (the
    autobuild chain's checkpoint) are responsible for checking
    `video_environments` is empty BEFORE calling this — same discipline
    PipelineExecutor.run_characters' callers already need, since neither
    function guards itself.
    """
    video_id = video["id"]
    tenant_id = str(tenant_id)

    async def _progress(message: str) -> None:
        if progress:
            await progress(message)

    from vault import get_secret
    api_key = await get_secret("kie_ai_api_key", tenant_id)
    if not api_key:
        return {"status": "failed", "error": "Add your Kie.ai API key in Settings → Keys first."}

    style_dna = video.get("image_style_override") or ""
    aspect_ratio = video.get("aspect_ratio") or "16:9"

    await _progress("Reading the Story Bible for locations…")
    envs = _extract_environments(video)
    if not envs:
        # Story Bible not built yet (it's generated at the image step) —
        # fall back to reading locations from the script, exactly like
        # character design does. Only truly skip when the script has none.
        await _progress("Reading the script for locations…")
        envs = await _extract_locations_from_script(video, api_key)
    if not envs:
        return {"status": "failed", "error": "No recurring locations found in the script — this video can skip environment design."}

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

    from actions import picture_price_for

    done = 0
    for i, env in enumerate(envs):
        # Money-safety fix (merged from main): re-check the cap before EVERY
        # environment, not just once before the batch — spend accrues across
        # this loop, same reasoning as the character-portrait loop's
        # per-iteration guard. A cap hit here is NOT a "failed" result (the
        # caller, e.g. the autobuild anchors checkpoint, must not treat a
        # capped video as a hard generation error) — "completed" with
        # whatever got done before the cap stopped it.
        refusal = await _budget_refusal(tenant_id, video_id, picture_price_for(None))
        if refusal:
            msg = refusal
            if done:
                msg = f"Environments designed: {done}/{len(envs)} references ready before the cap stopped it. " + refusal
            return {"status": "completed", "message": msg}
        await _progress(f"Designing {env['name']} ({i + 1}/{len(envs)})…")
        row = await fetch_one(
            "INSERT INTO video_environments (tenant_id, video_id, name, description, sort) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            tenant_id, video_id, env["name"][:120], env.get("description") or "", i,
        )
        env_id = str(row["id"])
        # Retry each reference before giving up — a transient blip used to drop
        # the image silently, leaving an empty card that then blocks approve.
        last_err = None
        for attempt in range(3):
            try:
                ref = await _generate_environment(
                    api_key, env.get("description") or env["name"], style_dna, aspect_ratio,
                )
                url = await _persist_portrait_url(tenant_id, video_id, env_id, ref["url"])
                await execute(
                    "UPDATE video_environments SET reference_url = $1, updated_at = now() WHERE id = $2",
                    url, env_id,
                )
                # generation_ledger (money-safety fix, merged from main): this
                # reference already cost real money — same single write path
                # every other metered stage uses, priced by the model that
                # actually generated it.
                cost = picture_price_for(ref["model"])
                await record_ledger_entry(
                    tenant_id=tenant_id, video_id=video_id, stage="environment",
                    model=ref["model"], units=1, unit_cost=cost, actual_cost=cost,
                    kie_task_id=ref.get("task_id"),
                )
                done += 1
                last_err = None
                break
            except Exception as e:
                last_err = e
                await asyncio.sleep(2 * (attempt + 1))
        if last_err is not None:
            logger.warning("[environments] reference failed for %s after 3 tries: %s", env["name"], str(last_err)[:200])

    msg = f"Environments designed: {done}/{len(envs)} references ready — review, tweak, then approve."
    if done < len(envs):
        msg += " Some references failed — hit regenerate on the empty cards."
    return {"status": "completed", "message": msg}


@router.post("/{video_id}/environments/design")
async def design_environments(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    """Read the bible's locations and generate a reference per location
    (background task, progress via the shared /api/pipeline/task poller).
    Thin wrapper (feat/approval-gates extraction) around
    run_environments_design_step — this route owns ONLY the HTTP/background-
    task/lane-claim ceremony; the actual generation logic lives in that one
    shared function so the autobuild chain's checkpoint runs the identical
    code, awaited in line, instead of a second copy."""
    video = await _get_video(video_id, tenant_id)
    video["tenant_id"] = tenant_id

    # Fast-fail synchronously (unchanged from before the extraction above) —
    # the shared step also checks this (defense in depth for the autobuild
    # caller, which has no HTTPException to catch), but THIS route must keep
    # returning an immediate 400, not a 200 that flips to "failed" a moment
    # later, since the Environments tab's button expects the old contract.
    from vault import get_secret
    api_key = await get_secret("kie_ai_api_key", str(tenant_id))
    if not api_key:
        raise HTTPException(status_code=400, detail="Add your Kie.ai API key in Settings → Keys first.")

    from actions import picture_price_for
    refusal = await _budget_refusal(tenant_id, video_id, picture_price_for(None))
    if refusal:
        raise HTTPException(status_code=400, detail=refusal)

    from routes.pipeline import _set_task_status, _clear_task_status, _is_task_active, _lane_begin, _lane_finish
    if await _is_task_active(video_id, tenant_id, lane="environments"):
        raise HTTPException(status_code=409, detail="A task is already running for this video.")
    _lane_begin(video_id, tenant_id, "environments")

    _set_task_status(video_id, "running", "Reading the Story Bible for locations…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)

    async def _run():
        try:
            async def _progress(message: str) -> None:
                _set_task_status(video_id, "running", message, tenant_id=tenant_id, task_type=TASK_TYPE)

            result = await run_environments_design_step(video, tenant_id, progress=_progress)
            if result.get("status") == "failed":
                _set_task_status(video_id, "failed",
                                 error=user_facing(result.get("error") or "Couldn't design the environments"),
                                 tenant_id=tenant_id, task_type=TASK_TYPE)
            else:
                # "completed" covers both a full run and a budget-cap stop
                # mid-run (run_environments_design_step's own per-iteration
                # _budget_refusal check, merged from main) — both are
                # "completed", never "failed", same distinction the pre-
                # existing single-copy version of this loop made.
                _set_task_status(video_id, "completed", result.get("message"),
                                 tenant_id=tenant_id, task_type=TASK_TYPE)
        except Exception as e:
            _set_task_status(video_id, "failed",
                             error=user_facing(humanize_error(e, context="We couldn't design the environments")),
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        finally:
            _lane_finish(video_id, tenant_id, "environments")
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

    from actions import picture_price_for
    refusal = await _budget_refusal(tenant_id, video_id, picture_price_for(None))
    if refusal:
        raise HTTPException(status_code=400, detail=refusal)

    from routes.pipeline import _set_task_status, _clear_task_status, _is_task_active, _lane_begin, _lane_finish
    if await _is_task_active(video_id, tenant_id, lane="environments"):
        raise HTTPException(status_code=409, detail="A task is already running for this video.")
    _lane_begin(video_id, tenant_id, "environments")

    style_dna = video.get("image_style_override") or ""
    aspect_ratio = video.get("aspect_ratio") or "16:9"
    _set_task_status(video_id, "running", f"Redesigning {env['name']}…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)

    async def _run():
        try:
            ref = await _generate_environment(
                api_key, env.get("description") or env["name"], style_dna, aspect_ratio,
            )
            url = await _persist_portrait_url(tenant_id, video_id, env_id, ref["url"])
            await execute(
                "UPDATE video_environments SET reference_url = $1, source = 'generated', "
                "status = 'draft', updated_at = now() WHERE id = $2 AND tenant_id = $3",
                url, env_id, tenant_id,
            )
            cost = picture_price_for(ref["model"])
            await record_ledger_entry(
                tenant_id=tenant_id, video_id=video_id, stage="environment",
                model=ref["model"], units=1, unit_cost=cost, actual_cost=cost,
                kie_task_id=ref.get("task_id"),
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
            _lane_finish(video_id, tenant_id, "environments")
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
    if body.props is not None:
        # Creator-editable manifest (C4): shape + max-count already enforced by
        # PropItem/EnvironmentUpdate's validators above; an empty list clears it
        # back to "no manifest" (every downstream consumer's fallback path).
        props_json = json.dumps([p.model_dump() for p in body.props]) if body.props else None
        params.append(props_json); sets.append(f"props = ${len(params)}")
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
async def approve_environments(video_id: str, background_tasks: BackgroundTasks, tenant_id=Depends(get_tenant_id)):
    """Lock the environments: every location with a reference becomes
    'approved', videos.environments_approved_at is stamped, and storyboards
    unlock.

    The heavy part (a per-location vision pass that rewrites each description
    from its approved reference) runs as a background task with progress — it
    took ~96-111s synchronously for 8 locations, blowing past the frontend's
    fetch timeout ("Our servers hit a snag") even though it actually saved.
    """
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

    from routes.pipeline import _set_task_status, _clear_task_status, _is_task_active, _lane_begin, _lane_finish
    if await _is_task_active(video_id, tenant_id, lane="environments"):
        raise HTTPException(status_code=409, detail="A task is already running for this video.")
    _lane_begin(video_id, tenant_id, "environments")

    _set_task_status(video_id, "running", "Locking in the locations…",
                     tenant_id=tenant_id, task_type=TASK_TYPE)

    async def _run():
        try:
            await execute(
                "UPDATE video_environments SET status = 'approved', updated_at = now() "
                "WHERE video_id = $1 AND tenant_id = $2",
                video_id, tenant_id,
            )
            envs = [dict(r) for r in with_refs]

            # Pixel-accurate descriptions: the references were GENERATED from the
            # bible prose, but image models take liberties — when the saved text
            # disagrees with the approved reference, downstream prompts fight the
            # reference and the setting drifts. Rewrite each description from the
            # actual approved image (vision pass), best-effort per environment.
            try:
                from routes.model_video import _resolve_claude_creds
                from routes.media import mint_media_token
                from shared.clients.vision_client import vision_call, _looks_like_refusal
                creds = await _resolve_claude_creds(tenant_id)
                if creds:
                    base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")
                    for idx, env in enumerate(envs):
                        _set_task_status(
                            video_id, "running",
                            f"Locking in {env['name']} ({idx + 1}/{len(envs)})…",
                            tenant_id=tenant_id, task_type=TASK_TYPE,
                        )
                        fid = _drive_file_id(env.get("reference_url") or "")
                        img_url = (
                            f"{base}/api/media/drive/{fid}?token={mint_media_token(tenant_id)}"
                            if fid else env.get("reference_url")
                        )
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
                            # Never let a refusal / non-answer overwrite the
                            # bible-based description (vision_call already guards
                            # this; belt-and-suspenders against a regression).
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

                        # PROP MANIFEST (C4): one-time extraction, only when this
                        # environment doesn't already have one (re-approving an
                        # env that was already extracted must not re-spend).
                        # FAIL-SOFT BY DESIGN: any failure here (network, parse,
                        # refusal) is logged loudly and props stays NULL —
                        # approval must NEVER block or fail because of this.
                        # This is the ONLY place real extraction ever fires;
                        # every other consumer only ever reads what's already
                        # stored.
                        if not _parse_json(env.get("props")):
                            try:
                                props = await _extract_env_props(
                                    env["name"], env.get("description") or "", img_url, creds)
                                await execute(
                                    "UPDATE video_environments SET props = $1, updated_at = now() "
                                    "WHERE id = $2 AND tenant_id = $3",
                                    json.dumps(props), env["id"], tenant_id,
                                )
                                env["props"] = props
                                logger.info("[environments] prop manifest extracted for %s (%d props)",
                                            env["name"], len(props))
                            except Exception as e:
                                logger.warning(
                                    "[environments] PROP EXTRACTION FAILED for %s — approval "
                                    "continues, props stays NULL (falls back to prose-only "
                                    "prompts): %s", env["name"], str(e)[:200])
            except Exception as e:
                logger.warning("[environments] vision sync skipped: %s", str(e)[:150])

            await _sync_bible_to_locations(video_id, tenant_id, envs)

            await execute(
                "UPDATE videos SET environments_approved_at = now(), updated_at = now() "
                "WHERE id = $1 AND tenant_id = $2",
                video_id, tenant_id,
            )
            _set_task_status(video_id, "completed",
                             f"Environments approved ({len(with_refs)}) — storyboards unlocked.",
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        except Exception as e:
            _set_task_status(video_id, "failed",
                             error=user_facing(humanize_error(e, context="We couldn't approve the environments")),
                             tenant_id=tenant_id, task_type=TASK_TYPE)
        finally:
            _lane_finish(video_id, tenant_id, "environments")
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return {"status": "running", "message": "Approving the locations — locking in each one."}


@router.post("/{video_id}/environments/skip")
async def skip_environments(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Mark this video as having no distinct locations. Stamps
    environments_approved_at (with no rows) so the storyboard gate passes
    without any locked locations — for talking-head / location-less videos.
    Reversible: designing environments later resets approval (design sets
    environments_approved_at = NULL, so you'd re-approve)."""
    await _get_video(video_id, tenant_id)
    await execute(
        "UPDATE videos SET environments_approved_at = now(), updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "skipped"}
