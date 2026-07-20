"""Feature board — "suggest a feature" + upvotes + a status ladder (checklist
C65, tasks/decisions.md 2026-07-20 "Feature board" entry).

CRITICAL architectural note (from the ruling): this is the platform's FIRST
deliberately CROSS-TENANT surface. Every customer sees the SAME board —
`GET /api/feature-board` reads `feature_requests`/`feature_request_votes`
with NO tenant_id filter at all, on purpose. Do NOT copy the tenant-isolation
idiom (`Depends(get_tenant_id)`) here; every route below depends on
`auth.verify_token` (the USER-scoped dependency, same as routes/workspaces.py)
so it works identically regardless of which tenant/workspace is active.

Attribution is per ACCOUNT, not tenant: `accounts.id` IS the same UUID as
`AuthUser.id` (see routes/workspaces.py's `_is_operator(user_id)`, which
already keys straight off `accounts.id` this way) — so `account_id` columns
below are simply `user.id`, no membership join needed.

Writes stay validated even though reads are open:
  - one vote per (request, account) — enforced by the DB itself
    (feature_request_votes' composite PRIMARY KEY, migration 112), the vote
    endpoint just does ON CONFLICT DO NOTHING against it.
  - a user can only edit/delete their own suggestion — not built in this
    pass (the spec only asks for create/list/vote/status), left for a later
    chunk if Ryan wants edit/delete.
  - only Ryan's operator account can change status — reuses the SAME
    `accounts.is_operator` idiom `_get_tenant_plan_and_operator`
    (routes/billing.py) and `_is_operator` (routes/workspaces.py) already
    check, via workspaces._is_operator (no new helper, no duplicate query).

Rate limit: a simple persisted COUNT(*) query (max 5 submissions/account/
day), NOT rate_limit.py's in-memory per-minute bucket — that module limits
requests-per-minute-per-plan for abuse protection and resets on restart;
this needs a slow, correct, restart-safe per-account/per-day ceiling, which
an in-memory bucket can't give (see rate_limit.py's own docstring: "state
resets on server restart, which is acceptable since rate limits are
protective (not billing-critical)" — a feature-board submission cap is a
product policy, not that kind of protective throttle).

Customer text is displayed to other customers: title/body/channel_archetype
are returned VERBATIM (no server-side HTML rendering, no markdown-to-HTML
conversion) — React escapes on the way out. See
tests/test_c65_feature_board.py's raw-text pin.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import AuthUser, verify_token
from database import execute, fetch_all, fetch_one
from routes.workspaces import _is_operator

router = APIRouter(prefix="/api/feature-board", tags=["feature-board"])

STATUSES = ("under_review", "planned", "building", "in_beta", "shipped", "declined")

_MAX_SUBMISSIONS_PER_DAY = 5


class FeatureRequestOut(BaseModel):
    id: str
    account_id: str
    title: str
    body: Optional[str] = None
    channel_archetype: Optional[str] = None
    status: str
    declined_reason: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    vote_count: int = 0
    voted_by_me: bool = False
    is_mine: bool = False


class FeatureBoardResponse(BaseModel):
    requests: list[FeatureRequestOut] = []


class CreateFeatureRequestBody(BaseModel):
    title: str = Field(..., max_length=120)
    body: Optional[str] = Field(None, max_length=2000)
    channel_archetype: Optional[str] = None


class StatusUpdateBody(BaseModel):
    status: str
    declined_reason: Optional[str] = None


async def account_id_for_tenant(tenant_id) -> Optional[str]:
    """Resolve a representative account for a tenant (owner preferred, else
    any member) — used ONLY by the MCP door (routes/mcp.py), which
    authenticates by tenant (agent token), not by user. Every HTTP route in
    this file uses the real caller's user.id directly instead; this exists
    because an MCP agent token has no user identity of its own to attribute
    a suggestion/vote to."""
    row = await fetch_one(
        """SELECT a.id FROM accounts a
           JOIN memberships m ON m.user_id = a.id
           WHERE m.tenant_id = $1
           ORDER BY (m.role = 'owner') DESC, a.id
           LIMIT 1""",
        tenant_id,
    )
    return str(row["id"]) if row else None


def _row_to_out(row: dict, account_id: str) -> FeatureRequestOut:
    return FeatureRequestOut(
        id=str(row["id"]),
        account_id=str(row["account_id"]),
        title=row["title"],
        body=row.get("body"),
        channel_archetype=row.get("channel_archetype"),
        status=row["status"],
        declined_reason=row.get("declined_reason"),
        created_at=row["created_at"].isoformat() if row.get("created_at") else None,
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else None,
        vote_count=int(row.get("vote_count") or 0),
        voted_by_me=bool(row.get("voted_by_me")),
        is_mine=str(row["account_id"]) == str(account_id),
    )


@router.get("", response_model=FeatureBoardResponse)
async def list_feature_board(
    status: Optional[str] = None,
    user: AuthUser = Depends(verify_token),
):
    """Every suggestion on the board — CROSS-TENANT by design, no tenant_id
    filter. Sort: status-group (ladder order) then votes desc. One query,
    one LEFT JOIN for vote_count + whether THIS caller voted."""
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {STATUSES}")
    rows = await fetch_all(
        """SELECT fr.id, fr.account_id, fr.title, fr.body, fr.channel_archetype,
                  fr.status, fr.declined_reason, fr.created_at, fr.updated_at,
                  COUNT(v.account_id) AS vote_count,
                  COALESCE(BOOL_OR(v.account_id = $2), false) AS voted_by_me
           FROM feature_requests fr
           LEFT JOIN feature_request_votes v ON v.request_id = fr.id
           WHERE ($1::text IS NULL OR fr.status = $1)
           GROUP BY fr.id
           ORDER BY CASE fr.status
                      WHEN 'under_review' THEN 0
                      WHEN 'planned' THEN 1
                      WHEN 'building' THEN 2
                      WHEN 'in_beta' THEN 3
                      WHEN 'shipped' THEN 4
                      WHEN 'declined' THEN 5
                      ELSE 6
                    END,
                    vote_count DESC,
                    fr.created_at ASC
           LIMIT 100""",
        status, user.id,
    )
    return FeatureBoardResponse(requests=[_row_to_out(r, user.id) for r in rows])


@router.post("", response_model=FeatureRequestOut)
async def create_feature_request(
    body: CreateFeatureRequestBody,
    user: AuthUser = Depends(verify_token),
):
    """Suggest a feature. Length caps are enforced twice — the Pydantic
    model (400 on a bad request shape) AND the DB CHECK constraint
    (migration 112) as the real backstop — and a light per-account/day rate
    limit (see module docstring for why this is a plain COUNT query, not
    rate_limit.py's in-memory bucket)."""
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if len(title) > 120:
        raise HTTPException(status_code=400, detail="title must be 120 characters or fewer")
    text = (body.body or "").strip() or None
    if text and len(text) > 2000:
        raise HTTPException(status_code=400, detail="body must be 2000 characters or fewer")

    count_row = await fetch_one(
        """SELECT COUNT(*) AS c FROM feature_requests
           WHERE account_id = $1 AND created_at > now() - interval '1 day'""",
        user.id,
    )
    if count_row and int(count_row["c"]) >= _MAX_SUBMISSIONS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"You can suggest up to {_MAX_SUBMISSIONS_PER_DAY} features per day — try again tomorrow.",
        )

    row = await fetch_one(
        """INSERT INTO feature_requests (account_id, title, body, channel_archetype)
           VALUES ($1, $2, $3, $4)
           RETURNING id, account_id, title, body, channel_archetype, status,
                     declined_reason, created_at, updated_at""",
        user.id, title, text, (body.channel_archetype or None),
    )
    out = _row_to_out(row, user.id)
    out.vote_count = 0
    out.voted_by_me = False
    return out


@router.post("/{request_id}/vote", response_model=FeatureRequestOut)
async def vote_feature_request(
    request_id: str,
    user: AuthUser = Depends(verify_token),
):
    """Upvote — idempotent via the unique (composite PK) constraint on
    feature_request_votes: a second vote from the same account is a no-op,
    not an error."""
    existing = await fetch_one("SELECT id FROM feature_requests WHERE id = $1", request_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Feature request not found")
    await execute(
        """INSERT INTO feature_request_votes (request_id, account_id)
           VALUES ($1, $2)
           ON CONFLICT (request_id, account_id) DO NOTHING""",
        request_id, user.id,
    )
    return await _get_one_with_votes(request_id, user.id)


@router.delete("/{request_id}/vote", response_model=FeatureRequestOut)
async def unvote_feature_request(
    request_id: str,
    user: AuthUser = Depends(verify_token),
):
    """Remove your upvote. Idempotent — deleting a vote that isn't there is
    a no-op, not an error."""
    existing = await fetch_one("SELECT id FROM feature_requests WHERE id = $1", request_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Feature request not found")
    await execute(
        "DELETE FROM feature_request_votes WHERE request_id = $1 AND account_id = $2",
        request_id, user.id,
    )
    return await _get_one_with_votes(request_id, user.id)


async def _get_one_with_votes(request_id: str, caller_account_id: str) -> FeatureRequestOut:
    row = await fetch_one(
        """SELECT fr.id, fr.account_id, fr.title, fr.body, fr.channel_archetype,
                  fr.status, fr.declined_reason, fr.created_at, fr.updated_at,
                  COUNT(v.account_id) AS vote_count,
                  COALESCE(BOOL_OR(v.account_id = $2), false) AS voted_by_me
           FROM feature_requests fr
           LEFT JOIN feature_request_votes v ON v.request_id = fr.id
           WHERE fr.id = $1
           GROUP BY fr.id""",
        request_id, caller_account_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Feature request not found")
    return _row_to_out(row, caller_account_id)


@router.patch("/{request_id}/status", response_model=FeatureRequestOut)
async def update_feature_request_status(
    request_id: str,
    body: StatusUpdateBody,
    user: AuthUser = Depends(verify_token),
):
    """Move a suggestion along the ladder — operator-only (Ryan). Reuses the
    SAME accounts.is_operator idiom routes/workspaces.py's create/remove
    workspace routes already check (`_is_operator`), no new gate invented."""
    if not await _is_operator(user.id):
        raise HTTPException(status_code=403, detail="Not authorized to change feature status")
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {STATUSES}")
    existing = await fetch_one("SELECT id FROM feature_requests WHERE id = $1", request_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Feature request not found")
    declined_reason = body.declined_reason if body.status == "declined" else None
    await execute(
        """UPDATE feature_requests
           SET status = $2, declined_reason = $3, updated_at = now()
           WHERE id = $1""",
        request_id, body.status, declined_reason,
    )
    return await _get_one_with_votes(request_id, user.id)
