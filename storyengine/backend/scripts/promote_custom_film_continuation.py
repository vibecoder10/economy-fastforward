"""Promote verified Custom Film screenplays into a fresh paid runtime.

This is a fail-closed operator recovery for a terminal legacy runtime whose
provider operation cannot be reconciled.  It never calls a provider.  The
default mode is a read-only dry run; ``--commit`` performs one atomic database
transaction that:

* preserves the old plan, task, and provider journal;
* creates a new immutable plan revision and scripts-first runtime identity;
* records the cumulative approval and unresolved-exposure reserve;
* copies the five verified screenplay assignments;
* rebinds their validation to the new runtime;
* journals the screenplay stages as promoted, completed work; and
* inserts one pending runtime starting at the first voice stage.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from custom_film_contract import (  # noqa: E402
    CustomFilmContractError,
    approval_binding_hash,
    canonical_hash,
)
from custom_film_production_runner import (  # noqa: E402
    CustomFilmProductionRunner,
    _validate_custom_film_av_arc,
)
from custom_film_runtime import compile_runtime_plan  # noqa: E402
from custom_film_section_runtime import (  # noqa: E402
    _operation_id,
    compile_stage_adapters,
    validate_runtime_envelope,
)
from database import get_pool  # noqa: E402


OLD_PLAN_ID = "cca740e2-45b3-4151-8d0e-03392551c90c"
OLD_RUNTIME_HASH = "34c9a32c913c7e76d5b95a34d0fd480aed36fe330a3225e7696b86e9e5e5073a"
OLD_JOB_ID = f"custom-film-runtime:{OLD_RUNTIME_HASH}"
EXPECTED_SCORES = (78, 78, 88, 78, 78)
EXPECTED_SECONDS = (54, 66, 66, 66, 48)
PROMOTION_VERSION = "verified-screenplay-promotion-v1"


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise CustomFilmContractError(f"{label} is not an object")
    return copy.deepcopy(dict(value))


def _money(value: Decimal | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def _build(args: argparse.Namespace) -> dict[str, Any]:
    cumulative = _money(args.approved_cumulative_cap)
    reserve = _money(args.prior_unresolved_allowance)
    new_cap = cumulative - reserve
    if cumulative != Decimal("8.57") or reserve != Decimal("0.05"):
        raise CustomFilmContractError(
            "This recovery is bound to cumulative $8.57 and reserve $0.05"
        )
    if new_cap != Decimal("8.52"):
        raise CustomFilmContractError("New-work cap must equal $8.52")
    new_plan_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{OLD_PLAN_ID}:{PROMOTION_VERSION}:8.57:0.05",
        )
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Dry-run performs no writes, but still takes the same row locks as the
        # commit path so its proof covers the exact atomic preconditions.
        async with conn.transaction(isolation="serializable"):
            video = await conn.fetchrow(
                """SELECT id::text, tenant_id::text, status, total_cost,
                          max_spend, custom_film_plan_id::text,
                          custom_film_plan_revision, custom_film_plan_hash,
                          custom_film_quote_inputs_hash,
                          custom_film_approval_hash, final_video_url
                   FROM videos
                   WHERE tenant_id = $1::uuid AND id = $2::uuid
                     AND deleted_at IS NULL
                   FOR UPDATE""",
                args.tenant_id,
                args.video_id,
            )
            if not video:
                raise CustomFilmContractError("Exact video was not found")
            if (
                str(video["custom_film_plan_id"]) not in {OLD_PLAN_ID, new_plan_id}
                or _money(video["max_spend"]) != new_cap
                or _money(video["total_cost"] or 0) != Decimal("0.00")
                or video.get("custom_film_approval_hash") is not None
                or video.get("final_video_url")
            ):
                raise CustomFilmContractError(
                    "Video identity, approval, spend, or output state drifted"
                )

            old_task = await conn.fetchrow(
                """SELECT status, attempt, runtime_progress
                   FROM background_tasks
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND job_id = $3
                   FOR UPDATE""",
                args.tenant_id,
                args.video_id,
                OLD_JOB_ID,
            )
            old_progress = _json_object(
                old_task["runtime_progress"] if old_task else None,
                "old runtime progress",
            )
            if (
                not old_task
                or old_task["status"] != "failed"
                or int(old_task["attempt"]) != 2
                or old_progress.get("runtime_hash") != OLD_RUNTIME_HASH
                or not isinstance(old_progress.get("in_flight"), Mapping)
                or not str(old_progress["in_flight"].get("stage_key") or "").endswith(
                    ":pictures"
                )
            ):
                raise CustomFilmContractError(
                    "Terminal legacy runtime evidence changed"
                )
            unresolved = await conn.fetchval(
                """SELECT count(*)
                   FROM custom_film_provider_operations
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND runtime_job_id = $3
                     AND state = 'reconciliation_required'
                     AND provider_operation_id IS NULL AND result IS NULL""",
                args.tenant_id,
                args.video_id,
                OLD_JOB_ID,
            )
            assets = await conn.fetchval(
                """SELECT count(*) FROM assets
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid""",
                args.tenant_id,
                args.video_id,
            )
            ledger = await conn.fetchrow(
                """SELECT count(*) AS rows,
                          COALESCE(sum(actual_cost), 0) AS cost
                   FROM generation_ledger
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid""",
                args.tenant_id,
                args.video_id,
            )
            if (
                int(unresolved or 0) != 1
                or int(assets or 0) != 0
                or int(ledger["rows"] or 0) != 0
                or _money(ledger["cost"] or 0) != Decimal("0.00")
            ):
                raise CustomFilmContractError(
                    "Legacy exposure, asset, or ledger evidence changed"
                )

            plan_row = await conn.fetchrow(
                """SELECT revision, compatibility_version, plan, plan_hash,
                          quote_inputs, quote_inputs_hash
                   FROM custom_film_plans
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND id = $3::uuid
                   FOR UPDATE""",
                args.tenant_id,
                args.video_id,
                OLD_PLAN_ID,
            )
            if not plan_row:
                raise CustomFilmContractError("Source plan was not found")
            plan = _json_object(plan_row["plan"], "plan")
            quote = _json_object(plan_row["quote_inputs"], "quote")
            if (
                str(video["custom_film_plan_hash"]) != str(plan_row["plan_hash"])
                or str(video["custom_film_quote_inputs_hash"])
                != str(plan_row["quote_inputs_hash"])
                or _money(quote.get("max_spend")) != new_cap
                or _money(quote.get("totals", {}).get("estimated_cost")) != new_cap
            ):
                raise CustomFilmContractError("Current plan or quote drifted")

            screenplay_rows = await conn.fetch(
                """SELECT css.section_id::text, css.script_id::text,
                          css.scene_order, s.scene, s.scene_text,
                          s.script_validation, s.voice_status,
                          s.voice_over_url, s.voice_duration_seconds
                   FROM custom_film_section_scenes css
                   JOIN scripts s
                     ON s.id = css.script_id
                    AND s.tenant_id = css.tenant_id
                    AND s.video_id = css.video_id
                   WHERE css.tenant_id = $1::uuid
                     AND css.video_id = $2::uuid
                     AND css.plan_id = $3::uuid
                   ORDER BY s.scene""",
                args.tenant_id,
                args.video_id,
                OLD_PLAN_ID,
            )
            if len(screenplay_rows) != 5:
                raise CustomFilmContractError("Exactly five screenplays are required")
            parsed_arc: list[Mapping[str, Any]] = []
            validations: list[dict[str, Any]] = []
            for index, row in enumerate(screenplay_rows):
                validation = _json_object(
                    row["script_validation"], "script validation"
                )
                custom = _json_object(validation.get("custom_film"), "custom film")
                preflight = _json_object(custom.get("preflight"), "preflight")
                shared = _json_object(
                    validation.get("shared_validation"), "shared validation"
                )
                parsed = shared.get("parsed")
                promotion = custom.get("promotion")
                source_identity_valid = (
                    custom.get("runtime_hash") == OLD_RUNTIME_HASH
                    or (
                        isinstance(promotion, Mapping)
                        and promotion.get("old_runtime_hash") == OLD_RUNTIME_HASH
                    )
                )
                if (
                    not source_identity_valid
                    or custom.get("section_id") != row["section_id"]
                    or int(custom.get("exact_seconds") or 0)
                    != EXPECTED_SECONDS[index]
                    or preflight.get("verdict") != "pass"
                    or int(preflight.get("score") or 0) != EXPECTED_SCORES[index]
                    or shared.get("valid") is not True
                    or not isinstance(parsed, Mapping)
                    or row.get("voice_status") is not None
                    or row.get("voice_over_url") is not None
                    or row.get("voice_duration_seconds") is not None
                ):
                    raise CustomFilmContractError(
                        f"Verified screenplay {index + 1} drifted"
                    )
                parsed_arc.append(parsed)
                validations.append(validation)
            arc_issues = _validate_custom_film_av_arc(parsed_arc)
            if arc_issues:
                raise CustomFilmContractError(
                    "Whole-film screenplay continuity drifted: "
                    + "; ".join(arc_issues)
                )

            new_revision = int(plan_row["revision"]) + 1
            approval_hash = approval_binding_hash(str(plan_row["plan_hash"]), quote)
            runtime = compile_runtime_plan(
                video_id=args.video_id,
                plan_id=new_plan_id,
                normalized_plan=plan,
                quote_inputs=quote,
                expected_plan_hash=str(plan_row["plan_hash"]),
                expected_quote_inputs_hash=str(plan_row["quote_inputs_hash"]),
                expected_approval_hash=approval_hash,
                max_spend=float(new_cap),
            )
            envelope = runtime.envelope()
            envelope["spend_authority"] = {
                "authority_version": "custom-film-cumulative-authority-v1",
                "approval_source": "creator_exact_cumulative_approval",
                "approved_cumulative_cap": float(cumulative),
                "prior_unresolved_allowance": float(reserve),
                "max_new_provider_spend": float(new_cap),
                "old_terminal_runtime_job_id": OLD_JOB_ID,
                "upload_authorized": False,
                "publication_authorized": False,
            }
            envelope_base = dict(envelope)
            envelope_base.pop("runtime_hash")
            envelope["runtime_hash"] = canonical_hash(envelope_base)
            validate_runtime_envelope(envelope)
            runtime_hash = str(envelope["runtime_hash"])
            job_id = f"custom-film-runtime:{runtime_hash}"
            adapters = compile_stage_adapters(envelope)
            script_adapters = [a for a in adapters if a.stage == "script"]
            if len(script_adapters) != 5 or list(adapters[:5]) != script_adapters:
                raise CustomFilmContractError(
                    "Fresh runtime is not an exact scripts-first schedule"
                )
            completed_keys = [adapter.stage_key for adapter in script_adapters]
            progress = {
                "runtime_hash": runtime_hash,
                "completed_stage_keys": completed_keys,
                "last_stage_key": completed_keys[-1],
                "in_flight": None,
            }

            existing_job = await conn.fetchrow(
                """SELECT job_id, runtime_envelope, runtime_progress, status
                   FROM background_tasks WHERE job_id = $1""",
                job_id,
            )
            if existing_job:
                if (
                    _json_object(existing_job["runtime_envelope"], "envelope")
                    != envelope
                    or _json_object(existing_job["runtime_progress"], "progress")
                    != progress
                ):
                    raise CustomFilmContractError(
                        "Existing promoted runtime identity is inconsistent"
                    )
                if args.commit:
                    if existing_job["status"] not in {"pending", "failed"}:
                        raise CustomFilmContractError(
                            "Promoted runtime already started; clone repair is blocked"
                        )
                    non_script_ops = await conn.fetchval(
                        """SELECT count(*)
                           FROM custom_film_provider_operations
                           WHERE runtime_job_id = $1
                             AND stage_key NOT LIKE '%:script'""",
                        job_id,
                    )
                    if int(non_script_ops or 0) != 0:
                        raise CustomFilmContractError(
                            "Promoted runtime crossed the provider boundary"
                        )
                    script_columns = [
                        str(row["column_name"])
                        for row in await conn.fetch(
                            """SELECT column_name
                               FROM information_schema.columns
                               WHERE table_schema = 'public'
                                 AND table_name = 'scripts'
                               ORDER BY ordinal_position"""
                        )
                    ]
                    if "id" not in script_columns or "script_validation" not in script_columns:
                        raise CustomFilmContractError("Scripts schema is incomplete")
                    new_assignments: list[tuple[str, str, int]] = []
                    for adapter, row, validation in zip(
                        script_adapters, screenplay_rows, validations, strict=True
                    ):
                        old_validation = copy.deepcopy(validation)
                        old_validation["custom_film"]["runtime_hash"] = OLD_RUNTIME_HASH
                        old_validation["custom_film"].pop("promotion", None)
                        promoted_validation = copy.deepcopy(old_validation)
                        promoted_validation["custom_film"]["runtime_hash"] = runtime_hash
                        clone_id = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"{runtime_hash}:{row['script_id']}:promoted-screenplay",
                            )
                        )
                        scene_hash = canonical_hash(
                            {
                                "scene_id": clone_id,
                                "scene_text": row["scene_text"],
                            }
                        )
                        promoted_validation["custom_film"]["promotion"] = {
                            "version": PROMOTION_VERSION,
                            "old_runtime_hash": OLD_RUNTIME_HASH,
                            "source_script_id": row["script_id"],
                            "scene_text_hash": scene_hash,
                            "promoted_without_provider_call": True,
                        }
                        select_values = []
                        bind_values: list[Any] = [
                            clone_id,
                            json.dumps(promoted_validation, sort_keys=True),
                            row["script_id"],
                            args.tenant_id,
                            args.video_id,
                            1000 + int(row["scene"]),
                        ]
                        for column in script_columns:
                            if column == "id":
                                select_values.append("$1::uuid")
                            elif column == "script_validation":
                                select_values.append("$2::jsonb")
                            elif column == "scene":
                                # Assignments, not the legacy scene integer,
                                # own section ordering for Custom Film.
                                select_values.append("$6")
                            elif column in {"voice_status", "voice_over_url", "voice_duration_seconds"}:
                                select_values.append("NULL")
                            elif column in {"created_at", "updated_at"}:
                                select_values.append("now()")
                            else:
                                select_values.append(f's."{column}"')
                        quoted_columns = ", ".join(f'"{c}"' for c in script_columns)
                        await conn.execute(
                            f"""INSERT INTO scripts ({quoted_columns})
                                SELECT {", ".join(select_values)}
                                FROM scripts s
                                WHERE s.id = $3::uuid
                                  AND s.tenant_id = $4::uuid
                                  AND s.video_id = $5::uuid
                                ON CONFLICT (id) DO NOTHING""",
                            *bind_values,
                        )
                        await conn.execute(
                            """UPDATE scripts
                               SET script_validation = $4::jsonb
                               WHERE id = $1::uuid AND tenant_id = $2::uuid
                                 AND video_id = $3::uuid""",
                            row["script_id"],
                            args.tenant_id,
                            args.video_id,
                            json.dumps(old_validation, sort_keys=True),
                        )
                        new_assignments.append(
                            (str(row["section_id"]), clone_id, int(row["scene_order"]))
                        )
                    await conn.execute(
                        """DELETE FROM custom_film_section_scenes
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND plan_id = $3::uuid""",
                        args.tenant_id,
                        args.video_id,
                        new_plan_id,
                    )
                    await conn.executemany(
                        """INSERT INTO custom_film_section_scenes
                             (tenant_id, plan_id, video_id, section_id,
                              script_id, scene_order)
                           VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid,
                                   $5::uuid, $6)""",
                        [
                            (
                                args.tenant_id,
                                new_plan_id,
                                args.video_id,
                                section_id,
                                clone_id,
                                scene_order,
                            )
                            for section_id, clone_id, scene_order in new_assignments
                        ],
                    )
                    await conn.execute(
                        """UPDATE background_tasks
                           SET status = 'pending', attempt = 2,
                               message = 'Verified screenplay clones promoted; awaiting voice',
                               error_message = NULL, completed_at = NULL
                           WHERE job_id = $1""",
                        job_id,
                    )
                return {
                    "mode": "already_promoted",
                    "job_id": job_id,
                    "runtime_hash": runtime_hash,
                    "status": existing_job["status"],
                    "clone_repair": bool(args.commit),
                }

            summary = {
                "mode": "commit" if args.commit else "dry_run",
                "new_plan_id": new_plan_id,
                "new_plan_revision": new_revision,
                "approval_hash": approval_hash,
                "runtime_hash": runtime_hash,
                "job_id": job_id,
                "completed_script_stage_keys": completed_keys,
                "next_stage_key": adapters[5].stage_key,
                "spend_authority": envelope["spend_authority"],
                "scores": list(EXPECTED_SCORES),
                "seconds": list(EXPECTED_SECONDS),
            }
            if not args.commit:
                return summary

            await conn.execute(
                """INSERT INTO custom_film_plans
                     (id, tenant_id, video_id, revision, compatibility_version,
                      plan, plan_hash, quote_inputs, quote_inputs_hash,
                      approval_hash, approved_at)
                   VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6::jsonb,
                           $7, $8::jsonb, $9, NULL, NULL)""",
                new_plan_id,
                args.tenant_id,
                args.video_id,
                new_revision,
                plan_row["compatibility_version"],
                json.dumps(plan, sort_keys=True),
                plan_row["plan_hash"],
                json.dumps(quote, sort_keys=True),
                plan_row["quote_inputs_hash"],
            )
            await conn.execute(
                """INSERT INTO custom_film_sections
                     (tenant_id, plan_id, video_id, section_id, order_index,
                      role, purpose, duration_units, knobs, provenance,
                      estimated_media)
                   SELECT tenant_id, $4::uuid, video_id, section_id, order_index,
                          role, purpose, duration_units, knobs, provenance,
                          estimated_media
                   FROM custom_film_sections
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND plan_id = $3::uuid""",
                args.tenant_id,
                args.video_id,
                OLD_PLAN_ID,
                new_plan_id,
            )
            await conn.execute(
                """INSERT INTO custom_film_section_scenes
                     (tenant_id, plan_id, video_id, section_id, script_id,
                      scene_order)
                   SELECT tenant_id, $4::uuid, video_id, section_id, script_id,
                          scene_order
                   FROM custom_film_section_scenes
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND plan_id = $3::uuid""",
                args.tenant_id,
                args.video_id,
                OLD_PLAN_ID,
                new_plan_id,
            )

            # The operation journal has a composite foreign key to its durable
            # runtime task.  Insert the fully checkpointed task first inside
            # this same transaction; no dispatcher can observe it until every
            # promoted journal row and validation rebind has committed.
            await conn.execute(
                """INSERT INTO background_tasks
                     (tenant_id, video_id, task_type, status, message, job_id,
                      attempt, started_at, runtime_envelope, runtime_progress)
                   VALUES ($1::uuid, $2::uuid, 'custom_film_runtime', 'pending',
                           'Verified screenplays promoted; awaiting voice',
                           $3, 1, now(), $4::jsonb, $5::jsonb)""",
                args.tenant_id,
                args.video_id,
                job_id,
                json.dumps(envelope, sort_keys=True),
                json.dumps(progress, sort_keys=True),
            )

            runner = CustomFilmProductionRunner(args.tenant_id)
            for adapter, row, validation in zip(
                script_adapters, screenplay_rows, validations, strict=True
            ):
                operation_id = _operation_id(args.tenant_id, job_id, adapter)
                spec = runner.operation_spec(adapter, (), operation_id)
                scene_hash = canonical_hash(
                    {
                        "scene_id": row["script_id"],
                        "scene_text": row["scene_text"],
                    }
                )
                result = {
                    "promotion_version": PROMOTION_VERSION,
                    "promoted_without_provider_call": True,
                    "scene_ids": [row["script_id"]],
                    "scene_text_hashes": [
                        {
                            "scene_id": row["script_id"],
                            "scene_text_hash": scene_hash,
                        }
                    ],
                    "exact_seconds": adapter.duration_seconds,
                    "script_profile": adapter.script_profile,
                    "role": adapter.role,
                    "purpose": adapter.purpose,
                    "quality_verdict": "pass",
                    "quality_score": validation["custom_film"]["preflight"]["score"],
                }
                await conn.execute(
                    """INSERT INTO custom_film_provider_operations
                         (tenant_id, video_id, runtime_job_id, runtime_hash,
                          stage_key, operation_id, provider, request_hash,
                          reconciliation_mode, state, result, completed_at)
                       VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8,
                               $9, 'completed', $10::jsonb, now())""",
                    args.tenant_id,
                    args.video_id,
                    job_id,
                    runtime_hash,
                    adapter.stage_key,
                    operation_id,
                    spec.provider,
                    spec.request_hash,
                    spec.reconciliation_mode,
                    json.dumps(result, sort_keys=True),
                )
                validation["custom_film"]["runtime_hash"] = runtime_hash
                validation["custom_film"]["promotion"] = {
                    "version": PROMOTION_VERSION,
                    "old_runtime_hash": OLD_RUNTIME_HASH,
                    "scene_text_hash": scene_hash,
                    "promoted_without_provider_call": True,
                }
                await conn.execute(
                    """UPDATE scripts
                       SET script_validation = $4::jsonb, updated_at = now()
                       WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                         AND id = $3::uuid""",
                    args.tenant_id,
                    args.video_id,
                    row["script_id"],
                    json.dumps(validation, sort_keys=True),
                )

            await conn.execute(
                """UPDATE videos
                   SET custom_film_plan_id = $3::uuid,
                       custom_film_plan_revision = $4,
                       custom_film_plan_hash = $5,
                       custom_film_quote_inputs_hash = $6,
                       custom_film_approval_hash = NULL,
                       custom_film_approved_at = NULL,
                       max_spend = $7,
                       status = 'ready_for_scripting',
                       updated_at = now()
                   WHERE tenant_id = $1::uuid AND id = $2::uuid""",
                args.tenant_id,
                args.video_id,
                new_plan_id,
                new_revision,
                plan_row["plan_hash"],
                plan_row["quote_inputs_hash"],
                new_cap,
            )
            return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--approved-cumulative-cap", required=True)
    parser.add_argument("--prior-unresolved-allowance", required=True)
    parser.add_argument("--commit", action="store_true")
    return parser


if __name__ == "__main__":
    result = asyncio.run(_build(_parser().parse_args()))
    print(json.dumps(result, indent=2, sort_keys=True))
