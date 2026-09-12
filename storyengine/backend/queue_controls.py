"""Durable provider pause for title lists; caller owns the tenant advisory lock."""
from __future__ import annotations

import re

# Credit/auth errors need account repair; ordinary 429/timeouts remain bounded
# transient retries. Keep this expression compatible with PostgreSQL regex.
PROVIDER_ERROR_PATTERN = (
    r"out of credits|insufficient[ _-]*(credits|balance|quota)|credit balance.{0,40}(low|exhaust)|"
    r"not enough credits|quota_exceeded|invalid[ _-]*api[ _-]*key|"
    r"api[ _-]*key.{0,30}(invalid|expired|revoked)|authentication_error|"
    r"invalid_grant|refresh token.{0,40}(expired|revoked|invalid)|"
    r"(no|missing).{0,20}api[ _-]*key"
)


def provider_blocker(error: str) -> dict | None:
    if not re.search(PROVIDER_ERROR_PATTERN, error, re.I):
        return None
    lower = error.lower()
    provider = next((label for markers, label in (
        (("anthropic", "claude"), "Anthropic"),
        (("elevenlabs", "eleven labs"), "ElevenLabs"),
        (("kie",), "Kie"),
        (("youtube", "google", "invalid_grant", "refresh token"), "YouTube"),
        (("openai",), "OpenAI"),
        (("tavily",), "Tavily"),
    ) if any(marker in lower for marker in markers)), "Generation provider")
    credit = bool(re.search(r"credit|balance|quota", lower))
    reason = (f"{provider} needs credits before production can continue. Add credits, then resume this list."
              if credit else
              f"{provider} credentials need attention. Update the connection or API key, then resume this list.")
    return {"provider": provider, "reason": reason}


async def sync_provider_pause(conn, tenant_id) -> dict | None:
    """Project saved failures into persistent control state without provider calls.

    Must run under the same advisory lock used for claims and reconciliation.
    resumed_at prevents an old, already acknowledged failure from re-pausing.
    The pause survives deletion of the failed queue row.
    """
    control = await conn.fetchrow(
        "SELECT * FROM production_queue_controls WHERE tenant_id=$1", tenant_id
    )
    if control and control["paused"]:
        return dict(control)
    failures = await conn.fetch(
        """SELECT id, last_error FROM production_queue
           WHERE tenant_id=$1 AND status='failed'
             AND last_error ~* $2
             AND updated_at > COALESCE($3::timestamptz, 'epoch'::timestamptz)
           ORDER BY updated_at DESC""",
        tenant_id, PROVIDER_ERROR_PATTERN, control["resumed_at"] if control else None,
    )
    for row in failures:
        blocker = provider_blocker(row["last_error"] or "")
        if blocker:
            saved = await conn.fetchrow(
                """INSERT INTO production_queue_controls
                       (tenant_id, paused, provider, reason, blocking_queue_id, paused_at)
                   VALUES ($1, true, $2, $3, $4, now())
                   ON CONFLICT (tenant_id) DO UPDATE SET paused=true,
                       provider=EXCLUDED.provider, reason=EXCLUDED.reason,
                       blocking_queue_id=EXCLUDED.blocking_queue_id,
                       paused_at=now(), updated_at=now()
                   RETURNING *""",
                tenant_id, blocker["provider"], blocker["reason"], row["id"],
            )
            return dict(saved)
    return dict(control) if control else None
