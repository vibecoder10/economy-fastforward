"""Agent LLM relay - the store behind "the MCP agent answers the pipeline's model calls".

A workspace opted in to the relay can run the real pipeline with no working Anthropic key: each model call the
stage code makes is parked as a `pending` row in `agent_llm_requests`, the connected MCP
agent (Claude, on the user's own subscription) reads it with `list_pending_llm_requests`,
does the work, and hands the text back with `answer_llm_request`. The waiting stage then
resumes exactly as if the provider had returned that text. Design + rationale:
docs/agent-llm-relay-2026-09-21/DESIGN.md. The blocking client lives in
agent_relay_client.py (it needs the pipeline's AnthropicClient; this module does not, so
the MCP route can import it without touching sys.path).

Every function takes tenant_id and puts it in the SQL - a request id from another
workspace is simply not found.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

from database import execute, fetch_all, fetch_one

# Answers are stored data, never executed. A real research packet is a few KB; this cap
# only stops an accidental paste of something enormous.
MAX_RESPONSE_CHARS = 200_000
TENANT_SCOPE = "tenant"

_LIST_LIMIT_DEFAULT = 10
_LIST_LIMIT_MAX = 50

_COLUMNS = (
    "id, video_id, stage, status, model, system_prompt, prompt, tools, max_tokens, "
    "temperature, response_text, answer_count, answered_at, created_at"
)


def poll_seconds() -> float:
    return float(os.getenv("AGENT_RELAY_POLL_SECONDS", "2"))


def timeout_seconds() -> float:
    return float(os.getenv("AGENT_RELAY_TIMEOUT_SECONDS", str(30 * 60)))


def scope_for(video_id: Optional[str]) -> str:
    return str(video_id) if video_id else TENANT_SCOPE


async def relay_enabled(tenant_id) -> bool:
    """True when this workspace opted in to the relay. False on any lookup problem
    (including the column not existing yet) - the normal key path then applies."""
    try:
        row = await fetch_one("SELECT agent_llm_relay FROM tenants WHERE id = $1", tenant_id)
    except Exception:  # noqa: BLE001 - never let a flag lookup break executor init
        return False
    return bool(row and row.get("agent_llm_relay"))


async def relay_active(tenant_id) -> bool:
    """Who answers the model calls right now: the relay only when the workspace opted in AND has no
    Anthropic key installed. One rule everywhere (Ryan, 2026-09-21): key installed -> use it (paid, quoted),
    no key -> the MCP agent (free). Putting a key back therefore switches the whole pipeline to automatic
    without touching the flag; deleting it hands the work back to the agent."""
    if not await relay_enabled(tenant_id):
        return False
    from vault import get_secret
    return not str(await get_secret("anthropic_api_key", tenant_id) or "").strip()


def _clean(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    out = dict(row)
    tools = out.get("tools")
    if isinstance(tools, str):
        try:
            out["tools"] = json.loads(tools)
        except ValueError:
            pass
    for key in ("id", "video_id"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    return out


async def get_or_create_request(
    tenant_id, video_id: Optional[str], *, fingerprint: str, stage: Optional[str],
    model: str, system_prompt: str, prompt: str, tools: Any, max_tokens: int,
    temperature: float,
) -> dict:
    """Return the row for this exact request, creating a `pending` one the first time.

    (tenant, video-or-'tenant', fingerprint) is unique: the same request asked twice is
    the same row, so a retry, a re-run or a restart never asks the agent again.
    """
    scope = scope_for(video_id)
    await execute(
        """INSERT INTO agent_llm_requests
             (tenant_id, video_id, scope, fingerprint, stage, model, system_prompt, prompt,
              tools, max_tokens, temperature)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
           ON CONFLICT (tenant_id, scope, fingerprint) DO NOTHING""",
        tenant_id, str(video_id) if video_id else None, scope, fingerprint, stage, model,
        system_prompt or "", prompt, json.dumps(tools, default=str) if tools else None,
        max_tokens, temperature,
    )
    row = await fetch_one(
        f"SELECT {_COLUMNS} FROM agent_llm_requests "
        "WHERE tenant_id = $1 AND scope = $2 AND fingerprint = $3",
        tenant_id, scope, fingerprint,
    )
    return _clean(row)


async def get_request(tenant_id, request_id: str) -> Optional[dict]:
    return _clean(await fetch_one(
        f"SELECT {_COLUMNS} FROM agent_llm_requests WHERE tenant_id = $1 AND id = $2",
        tenant_id, request_id,
    ))


async def list_requests(
    tenant_id, *, video_id: Optional[str] = None, status: str = "pending",
    limit: int = _LIST_LIMIT_DEFAULT,
) -> list[dict]:
    limit = max(1, min(int(limit or _LIST_LIMIT_DEFAULT), _LIST_LIMIT_MAX))
    clauses, args = ["tenant_id = $1"], [tenant_id]
    if status in ("pending", "answered"):
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    if video_id:
        args.append(str(video_id))
        clauses.append(f"video_id = ${len(args)}")
    args.append(limit)
    rows = await fetch_all(
        f"SELECT {_COLUMNS}, EXTRACT(EPOCH FROM (now() - created_at)) AS age_seconds "
        f"FROM agent_llm_requests WHERE {' AND '.join(clauses)} "
        f"ORDER BY created_at LIMIT ${len(args)}",
        *args,
    )
    return [_clean(r) for r in rows]


async def pending_count(tenant_id, video_id: Optional[str] = None) -> int:
    if video_id:
        row = await fetch_one(
            "SELECT count(*) AS n FROM agent_llm_requests "
            "WHERE tenant_id = $1 AND status = 'pending' AND video_id = $2",
            tenant_id, str(video_id),
        )
    else:
        row = await fetch_one(
            "SELECT count(*) AS n FROM agent_llm_requests WHERE tenant_id = $1 AND status = 'pending'",
            tenant_id,
        )
    return int((row or {}).get("n") or 0)


class AnswerError(ValueError):
    """The answer was refused; the message says why (shown to the agent verbatim)."""


async def answer_request(tenant_id, request_id: str, response: Any) -> dict:
    """Store `response` as the model's answer. Answering an already-answered request
    replaces it (how an agent fixes an answer the pipeline's parser rejected - the next
    run of the stage replays the corrected text)."""
    try:
        request_id = str(uuid.UUID(str(request_id)))
    except ValueError:
        raise AnswerError(f"{request_id!r} is not a request id") from None
    if not isinstance(response, str) or not response.strip():
        raise AnswerError("response must be the model's answer as a non-empty string")
    if len(response) > MAX_RESPONSE_CHARS:
        raise AnswerError(f"response is {len(response)} characters; the limit is {MAX_RESPONSE_CHARS}")
    row = await fetch_one(
        """UPDATE agent_llm_requests
              SET status = 'answered', response_text = $3, answer_count = answer_count + 1,
                  answered_at = now(), updated_at = now()
            WHERE tenant_id = $1 AND id = $2
        RETURNING id, video_id, stage, answer_count""",
        tenant_id, request_id, response,
    )
    if row is None:
        raise AnswerError(f"No LLM request {request_id} found for this workspace")
    return {
        "request_id": str(row["id"]), "video_id": str(row["video_id"]) if row.get("video_id") else None,
        "stage": row.get("stage"), "replaced_previous_answer": int(row["answer_count"]) > 1,
    }
