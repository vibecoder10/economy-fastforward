"""Exact, one-attempt storyboard execution for Scene Control.

The HTTP seam only reserves five immutable operations. Provider creation is
performed later by the worker and each operation can cross createTask once.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

import httpx

import custom_film_scene_control as control
from custom_film_contract import canonical_hash, canonical_json

EXECUTION_NAMESPACE = UUID("f7689263-c41f-4c88-a370-af8bf350b84a")
EXECUTION_VERSION = 1
MODEL = "gpt-image-2"
PROVIDER_MODEL = "gpt-image-2-text-to-image"
UNIT_CENTS = 5
SHOT_COUNT = 5
MAX_CENTS = 25
STAGE = "scene_storyboards"
CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"
RECORD_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"


class StoryboardExecutionError(control.SceneControlError):
    pass


class AmbiguousCreate(StoryboardExecutionError):
    pass


def execution_enabled() -> bool:
    return os.getenv("CUSTOM_FILM_SCENE_STORYBOARD_EXECUTION_V1", "").lower() in {
        "1", "true", "yes", "on",
    }


def validate_approval(card: Mapping[str, Any], *, amount_cents: int, card_hash: str) -> None:
    if not execution_enabled():
        raise StoryboardExecutionError("Scene storyboard execution is disabled")
    expected = {
        "operation_type": "storyboard_images",
        "approval_status": "not_approved",
        "initial_calls": SHOT_COUNT,
        "max_repair_calls": 0,
        "unit_max_cents": UNIT_CENTS,
        "exact_incremental_max_cents": MAX_CENTS,
    }
    if any(card.get(key) != value for key, value in expected.items()):
        raise StoryboardExecutionError("The exact five-shot storyboard card changed")
    if len(card.get("shot_ids") or []) != SHOT_COUNT:
        raise StoryboardExecutionError("Storyboard approval requires exactly five shots")
    if amount_cents != card.get("new_exact_cumulative_ceiling_cents"):
        raise StoryboardExecutionError("Approved cumulative amount does not match")
    if card_hash != card.get("approval_card_hash"):
        raise StoryboardExecutionError("Storyboard approval card hash does not match")


async def approve_storyboards(
    conn: Any, *, tenant_id: str, video_id: str, scene_id: str,
    expected_revision_hash: str, approval_card_hash: str,
    exact_cumulative_amount_cents: int,
) -> dict[str, Any]:
    """Reserve one immutable schedule; never call or queue a provider."""
    card = await control.quote_scene_operation(
        conn, tenant_id=tenant_id, video_id=video_id, scene_id=scene_id,
        expected_revision_hash=expected_revision_hash,
        operation_type="storyboard_images",
    )
    validate_approval(
        card, amount_cents=exact_cumulative_amount_cents,
        card_hash=approval_card_hash,
    )
    # Serialize approval/replay against scene revision and drain mode.
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"scene-storyboards:{tenant_id}:{scene_id}",
    )
    drain = await conn.fetchrow(
        "SELECT mode, reason FROM application_drain_state WHERE singleton = TRUE"
    )
    if not drain or str(drain.get("mode") or "") != "normal":
        raise StoryboardExecutionError(
            "StoryEngine is pausing new generation for a safe deployment"
        )
    scene = await conn.fetchrow(
        """SELECT revision_hash, state FROM custom_film_scene_controls
           WHERE tenant_id=$1 AND video_id=$2 AND id=$3 FOR UPDATE""",
        tenant_id, video_id, scene_id,
    )
    if not scene or scene["revision_hash"] != expected_revision_hash:
        raise StoryboardExecutionError("Scene revision changed; reload before approving")
    if scene["state"] != "plan_approved":
        raise StoryboardExecutionError("Storyboards require scene state plan_approved")
    schedule_id = str(uuid5(EXECUTION_NAMESPACE, approval_card_hash))
    approval = {
        "version": EXECUTION_VERSION,
        "tenant_id": tenant_id,
        "video_id": video_id,
        "scene_id": scene_id,
        "scene_revision_hash": expected_revision_hash,
        "approval_card_hash": approval_card_hash,
        "exact_cumulative_amount_cents": exact_cumulative_amount_cents,
    }
    row = await conn.fetchrow(
        """INSERT INTO custom_film_scene_storyboard_runs
             (id, tenant_id, video_id, scene_id, scene_revision_hash,
              approval_card, approval_card_hash, exact_cumulative_amount_cents,
              state)
           VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,'approved')
           ON CONFLICT (tenant_id, scene_id, scene_revision_hash)
           DO UPDATE SET updated_at=custom_film_scene_storyboard_runs.updated_at
           RETURNING id, state""",
        schedule_id, tenant_id, video_id, scene_id, expected_revision_hash,
        canonical_json(card), approval_card_hash, exact_cumulative_amount_cents,
    )
    for index, (shot_id, prompt) in enumerate(
        await _ordered_shots(conn, tenant_id, scene_id), start=1
    ):
        operation_id = str(uuid5(EXECUTION_NAMESPACE, f"{schedule_id}:{shot_id}"))
        request = {
            "model": PROVIDER_MODEL,
            "input": {"prompt": prompt, "aspect_ratio": "16:9", "resolution": "2K"},
        }
        await conn.execute(
            """INSERT INTO custom_film_scene_storyboard_operations
                 (id, run_id, tenant_id, video_id, scene_id, shot_id, order_index,
                  provider, model, prompt, request, request_hash, state)
               VALUES ($1,$2,$3,$4,$5,$6,$7,'kie',$8,$9,$10::jsonb,$11,'prepared')
               ON CONFLICT (run_id, shot_id) DO NOTHING""",
            operation_id, schedule_id, tenant_id, video_id, scene_id, shot_id,
            index, MODEL, prompt, canonical_json(request), canonical_hash(request),
        )
    return {"schedule_id": str(row["id"]), "state": str(row["state"]), "card": card}


async def _ordered_shots(conn: Any, tenant_id: str, scene_id: str) -> list[tuple[str, str]]:
    rows = await conn.fetch(
        """SELECT s.shot_id, s.shot_contract
           FROM custom_film_scene_controls c
           JOIN custom_film_shots s
             ON s.tenant_id=c.tenant_id
            AND s.director_contract_id=c.director_contract_id
            AND s.shot_id=ANY(
              ARRAY(SELECT jsonb_array_elements_text(c.scene_contract->'shot_ids'))::uuid[]
            )
           WHERE c.tenant_id=$1 AND c.id=$2
           ORDER BY array_position(
             ARRAY(SELECT jsonb_array_elements_text(c.scene_contract->'shot_ids'))::uuid[],
             s.shot_id
           )""",
        tenant_id, scene_id,
    )
    result = []
    for row in rows:
        contract = control._json_value(row["shot_contract"], "shot contract")
        prompt = str(
            contract.get("storyboard_prompt")
            or contract.get("storyboard_composition")
            or ""
        ).strip()
        if not prompt:
            raise StoryboardExecutionError("Every storyboard shot needs an exact prompt")
        result.append((str(row["shot_id"]), prompt))
    if len(result) != SHOT_COUNT:
        raise StoryboardExecutionError("Storyboard approval requires exactly five shots")
    return result


async def read_storyboard_execution(conn: Any, *, tenant_id: str, scene_id: str) -> dict[str, Any] | None:
    run = await conn.fetchrow(
        """SELECT id, scene_revision_hash, approval_card_hash,
                  exact_cumulative_amount_cents, state, approved_at, updated_at
           FROM custom_film_scene_storyboard_runs
           WHERE tenant_id=$1 AND scene_id=$2
           ORDER BY approved_at DESC LIMIT 1""",
        tenant_id, scene_id,
    )
    if not run:
        return None
    operations = await conn.fetch(
        """SELECT shot_id, order_index, model, state, provider_task_id,
                  result, error, completed_at
           FROM custom_film_scene_storyboard_operations
           WHERE tenant_id=$1 AND run_id=$2 ORDER BY order_index""",
        tenant_id, run["id"],
    )
    return {
        "schedule_id": str(run["id"]),
        "scene_revision_hash": str(run["scene_revision_hash"]),
        "approval_card_hash": str(run["approval_card_hash"]),
        "exact_cumulative_amount_cents": int(run["exact_cumulative_amount_cents"]),
        "state": str(run["state"]),
        "approved_at": str(run["approved_at"]),
        "updated_at": str(run["updated_at"]),
        "operations": [
            {
                "shot_id": str(row["shot_id"]),
                "order_index": int(row["order_index"]),
                "model": str(row["model"]),
                "state": str(row["state"]),
                "provider_task_id": row.get("provider_task_id"),
                "result": control._json_value(row.get("result") or {}, "storyboard result"),
                "error": row.get("error"),
                "completed_at": str(row["completed_at"]) if row.get("completed_at") else None,
            }
            for row in operations
        ],
    }


class Provider(Protocol):
    async def create(self, request: Mapping[str, Any]) -> str: ...
    async def poll(self, task_id: str) -> str: ...


def replay_action(state: str, provider_task_id: str | None) -> str:
    """Decide replay behavior without ever authorizing a second create."""
    if state == "completed":
        return "skip"
    if provider_task_id:
        return "poll"
    if state == "prepared":
        return "create_once"
    return "stop"


class KieSingleAttemptStoryboardProvider:
    def __init__(self, api_key: str):
        if not api_key:
            raise StoryboardExecutionError("A tenant Kie.ai key is required")
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def create(self, request: Mapping[str, Any]) -> str:
        """Exactly one POST. Missing identity is ambiguous and never retried."""
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(CREATE_URL, headers=self.headers, json=request)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise AmbiguousCreate(f"Storyboard create outcome is ambiguous: {exc}") from exc
        task_id = str(((body.get("data") or {}).get("taskId") or "")).strip()
        if body.get("code") != 200 or not task_id:
            raise AmbiguousCreate("Storyboard create returned no durable task identity")
        return task_id

    async def poll(self, task_id: str) -> str:
        for _ in range(180):
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(RECORD_URL, headers=self.headers, params={"taskId": task_id})
            response.raise_for_status()
            body = response.json()
            data = body.get("data") or {}
            state = str(data.get("state") or "").lower()
            if state == "success":
                raw = data.get("resultJson") or "{}"
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                urls = parsed.get("resultUrls") or parsed.get("result_urls") or []
                if urls:
                    return str(urls[0])
                raise StoryboardExecutionError("Completed storyboard has no image URL")
            if state in {"fail", "failed", "error"}:
                raise StoryboardExecutionError(
                    f"Storyboard provider failed: {data.get('failMsg') or state}"
                )
            await asyncio.sleep(5)
        raise StoryboardExecutionError("Storyboard provider polling timed out")


async def execute_run(schedule_id: str, *, provider: Provider | None = None) -> dict[str, Any]:
    """Execute prepared operations once; replay only polls persisted task IDs."""
    import database
    import generation_claims
    from vault import get_required_tenant_secret

    pool = await database.get_pool()
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            """SELECT tenant_id, video_id, scene_id, state
               FROM custom_film_scene_storyboard_runs WHERE id=$1""", schedule_id
        )
    if not run:
        raise StoryboardExecutionError("Storyboard schedule was not found")
    tenant_id, video_id = str(run["tenant_id"]), str(run["video_id"])
    claimed = await generation_claims.acquire(
        tenant_id, video_id, "main", claimed_by=f"scene-storyboards:{schedule_id}"
    )
    if not claimed:
        raise StoryboardExecutionError("This video already has generation work in flight")
    try:
        if provider is None:
            key = await get_required_tenant_secret(
                "kie_ai_api_key", tenant_id, provider_label="Kie.ai"
            )
            provider = KieSingleAttemptStoryboardProvider(key)
        async with pool.acquire() as conn:
            operations = await conn.fetch(
                """SELECT id, request, state, provider_task_id, result
                   FROM custom_film_scene_storyboard_operations
                   WHERE run_id=$1 ORDER BY order_index""", schedule_id
            )
        for operation in operations:
            state = str(operation["state"])
            task_id = operation.get("provider_task_id")
            action = replay_action(state, str(task_id) if task_id else None)
            if action == "skip":
                continue
            if action == "stop":
                break
            if action == "create_once":
                try:
                    task_id = await provider.create(
                        control._json_value(operation["request"], "storyboard request")
                    )
                except AmbiguousCreate as exc:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """UPDATE custom_film_scene_storyboard_operations
                               SET state='reconciliation_required',
                                   error=$2, updated_at=now()
                               WHERE id=$1 AND state='prepared'""",
                            operation["id"], str(exc),
                        )
                    break
                async with pool.acquire() as conn:
                    updated = await conn.fetchrow(
                        """UPDATE custom_film_scene_storyboard_operations
                           SET provider_task_id=$2, state='submitted', updated_at=now()
                           WHERE id=$1 AND state='prepared' AND provider_task_id IS NULL
                           RETURNING provider_task_id""",
                        operation["id"], task_id,
                    )
                if not updated:
                    raise StoryboardExecutionError("Provider task identity could not be persisted")
            url = await provider.poll(str(task_id))
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    """UPDATE custom_film_scene_storyboard_operations
                       SET state='completed', result=$2::jsonb, completed_at=now(),
                           updated_at=now()
                       WHERE id=$1 AND state='submitted'""",
                    operation["id"], canonical_json({"url": url}),
                )
                await conn.execute(
                    """INSERT INTO generation_ledger
                         (tenant_id,video_id,stage,model,units,unit_cost,actual_cost,kie_task_id)
                       VALUES ($1,$2,$3,$4,1,0.05,0.05,$5)
                       ON CONFLICT (video_id,stage,kie_task_id)
                         WHERE kie_task_id IS NOT NULL DO NOTHING""",
                    tenant_id, video_id, STAGE, MODEL, str(task_id),
                )
                await conn.execute(
                    """UPDATE videos SET total_cost=(
                         SELECT COALESCE(SUM(actual_cost),0)
                         FROM generation_ledger WHERE video_id=$1
                       ) WHERE id=$1""", video_id,
                )
        async with pool.acquire() as conn:
            counts = await conn.fetchrow(
                """SELECT count(*) FILTER (WHERE state='completed') completed,
                          count(*) FILTER (WHERE state='reconciliation_required') ambiguous
                   FROM custom_film_scene_storyboard_operations WHERE run_id=$1""",
                schedule_id,
            )
            final = "completed" if int(counts["completed"]) == SHOT_COUNT else (
                "reconciliation_required" if int(counts["ambiguous"]) else "stopped"
            )
            await conn.execute(
                "UPDATE custom_film_scene_storyboard_runs SET state=$2, updated_at=now() WHERE id=$1",
                schedule_id, final,
            )
        return {"schedule_id": schedule_id, "state": final, "completed": int(counts["completed"])}
    finally:
        await generation_claims.release_owned(
            tenant_id, video_id, "main", claimed_by=f"scene-storyboards:{schedule_id}"
        )


def compile_below_the_forecast_fixture(path: Path) -> dict[str, Any]:
    """Compile the locked treatment into six locks and one five-shot scene."""
    text = path.read_text()
    prompts = re.findall(r"\*\*Storyboard prompt:\*\* (.+?)(?=\n\n###|\Z)", text, re.S)
    if len(prompts) != SHOT_COUNT:
        raise StoryboardExecutionError("Below the Forecast must contain five storyboard prompts")
    shot_ids = [
        str(uuid5(EXECUTION_NAMESPACE, f"below-the-forecast:shot:{i}"))
        for i in range(1, 6)
    ]
    logline = re.search(r"\*\*Logline:\*\* (.+)", text)
    story_law = re.search(r"\*\*Story law:\*\* (.+)", text)
    return {
        "title": "Below the Forecast",
        "source_sha256": canonical_hash({"markdown": text}),
        "locks": {
            "story": {"logline": logline.group(1), "story_law": story_law.group(1)},
            "dialogue": {"mode": "visual_storytelling", "narrator": None},
            "style": {"visual_law": re.search(r"\*\*Visual law:\*\* (.+)", text).group(1)},
            "cast": {
                "nia_vale": re.search(r"\*\*Nia Vale:\*\* (.+)", text).group(1),
                "lio_arden": re.search(r"\*\*Lio Arden:\*\* (.+)", text).group(1),
            },
            "environments": {"arcology_seven": re.search(r"\*\*Arcology Seven:\*\* (.+)", text).group(1)},
            "techniques": {"allowed": ["cinematic_photoreal_storyboard"], "aspect_ratio": "16:9"},
        },
        "scene": {
            "scene_number": 1,
            "purpose": "Compress the complete class-boundary reversal into five ordered storyboard beats.",
            "target_duration_frames": 600,
            "story_time": "one escalating storm spectacle and its immediate aftermath",
            "opening_state": "Nia and the climate workers are separated from luxury residents by storm glass.",
            "state_change": "Nia reverses the forecast and meets Lio with no glass between them.",
            "character_ids": ["nia_vale", "lio_arden"],
            "environment_id": "arcology_seven",
            "active_prop_ids": ["conductor_hook", "brass_route_model", "inversion_wheel"],
            "continuity_in": "Amber privilege remains inside; cyan danger remains outside.",
            "continuity_out": "The weather is calm, the doors are open, and the class boundary is physically crossed.",
            "dialogue_turns": [],
            "silent_action_beats": ["weather skin", "handprint", "spectacle", "engine reveal", "forecast reversal"],
            "shot_ids": shot_ids,
        },
        "shots": [
            {"shot_id": shot_id, "order_index": index, "storyboard_prompt": prompt.strip()}
            for index, (shot_id, prompt) in enumerate(zip(shot_ids, prompts))
        ],
    }
