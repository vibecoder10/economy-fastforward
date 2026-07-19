"""The MCP money gate's confirm token — checklist P2.4b, chunk C27 (tasks/
storyengine-copilot-ux-map.md §7: "paid tools return a quote + confirm_token
first; the agent must call confirm(confirm_token) to spend").

Chat's existing money gate (routes/chat.py's ``pending_action``) works
because a chat conversation is one stateful thing: the quote and the
confirming "yes" are two turns of the SAME conversation row, so the pending
action can live in ``chat_conversations.state`` between them. An MCP client
has no equivalent shared state — the quoting ``tools/call`` and the
confirming ``tools/call`` are two independent HTTP requests, possibly to
different backend processes (uvicorn workers, or the arq worker), so the
binding between "the quote I showed" and "the spend you're confirming" has
to be a real, single-use, DB-durable token — the same reasoning that made
``agent_tokens`` a DB row instead of a stateless JWT (S5-3).

Design (the three properties the checklist calls for):
  - **Single-use**: ``redeem()`` is one atomic ``UPDATE ... WHERE used_at IS
    NULL ... RETURNING`` — the row-count IS the single-use check, no
    read-then-write race (identical pattern to ``agent_tokens.
    revoke_agent_token``'s idempotent revoke).
  - **Short-lived**: 10-minute expiry (``TTL_SECONDS``), checked in the same
    atomic UPDATE (``expires_at > now()``) — an expired token fails the same
    way a used one does, no separate check to get wrong.
  - **Parameter-bound**: the token is minted against a ``params_hash`` of
    the EXACT (verb, scene, change, length_min, target) the quote was
    computed for. The confirming call recomputes the hash from ITS OWN
    arguments and the redeem UPDATE's WHERE clause requires an exact match
    — so a token minted for "animate scene 3" cannot be replayed against
    "animate scene 12", and a bait-and-switch (quote cheap, confirm
    expensive) fails closed rather than silently spending on the wrong
    plan. Video and verb are bound the same way, in the same clause.

Token shape mirrors agent_tokens.py exactly, for the same reason: this
hashes a 256-bit random secret (already all entropy — nothing to
dictionary-guess), so sha256 is the right hash, not a slow KDF.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Optional

from database import execute

TOKEN_PREFIX = "mcpc_"
TTL_SECONDS = 600  # 10 minutes


def _hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def params_hash(verb: str, scene: Optional[int], change: Optional[str],
                 length_min: Optional[float], target: Optional[str]) -> str:
    """Deterministic identity for the quoted call's parameters. Canonical
    JSON (sorted keys, normalized blanks) so the SAME logical call always
    hashes the same regardless of key ordering or an empty-vs-None string,
    while a DIFFERENT scene/change/target hashes differently — that
    difference is exactly what makes a params-mismatched confirm fail."""
    canonical = json.dumps({
        "verb": verb,
        "scene": scene if scene is None else int(scene),
        "change": (change or "").strip(),
        "length_min": length_min,
        "target": target,
    }, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def create(tenant_id, video_id, verb: str, phash: str) -> str:
    """Mint a single-use confirm token bound to (tenant, video, verb,
    phash), expiring in TTL_SECONDS. Returns the plaintext — never stored,
    only its hash is (same non-recoverable pattern as agent_tokens.py)."""
    secret = secrets.token_urlsafe(32)
    plaintext = f"{TOKEN_PREFIX}{secret}"
    token_hash = _hash_token(plaintext)
    await execute(
        """INSERT INTO mcp_confirm_tokens
               (tenant_id, video_id, verb, params_hash, token_hash, expires_at)
           VALUES ($1, $2, $3, $4, $5, now() + make_interval(secs => $6))""",
        tenant_id, video_id, verb, phash, token_hash, TTL_SECONDS,
    )
    return plaintext


async def redeem(tenant_id, video_id, verb: str, phash: str, token: Optional[str]) -> bool:
    """Atomically spend the token: only succeeds if it exists, is unused,
    unexpired, AND bound to this exact (tenant, video, verb, phash). Any
    mismatch (wrong token, wrong tenant/video/verb, wrong params, already
    used, expired) returns False from the SAME query — no branch that could
    disagree with another about which case fired.
    """
    if not token or not token.startswith(TOKEN_PREFIX):
        return False
    token_hash = _hash_token(token)
    result = await execute(
        """UPDATE mcp_confirm_tokens SET used_at = now()
           WHERE token_hash = $1 AND tenant_id = $2 AND video_id = $3
             AND verb = $4 AND params_hash = $5
             AND used_at IS NULL AND expires_at > now()""",
        token_hash, tenant_id, video_id, verb, phash,
    )
    # asyncpg's execute() returns a command tag string like "UPDATE 1".
    return isinstance(result, str) and result.strip().endswith(" 1")
