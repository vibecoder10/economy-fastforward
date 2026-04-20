"""Backend error humanization — mirror of frontend src/lib/errors.ts.

Raw exception strings (stack traces, API error bodies, "Kie.ai API error:
HTTPSConnectionPool(host='api.kie.ai'...") must NEVER reach a user. This
module provides one helper to convert exceptions into user-friendly copy
while preserving raw-error logging for devs.

Usage:
    from error_utils import humanize_error

    try:
        ...
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=humanize_error(e, context="We couldn't generate your character"),
        )

The raw exception is always logged at WARNING with a stable prefix
`[humanize_error]` so devs can grep for it when a customer reports an error.
"""
import logging
from typing import Optional, Union

logger = logging.getLogger(__name__)


def humanize_error(
    err: Union[Exception, str, None],
    context: Optional[str] = None,
    fallback: str = "Something went wrong. Please try again.",
) -> str:
    """Convert a raw exception/string into copy safe to show users.

    - If `context` is provided, it's used as the lead — e.g. "We couldn't
      generate your character. Please try again." The raw error is logged
      to WARNING but never returned to the user.
    - Otherwise, we inspect the raw string for known patterns (network,
      timeout, auth, rate-limit, 5xx) and return matching friendly copy.
    - Falls back to `fallback` if nothing matches.
    """
    raw = str(err) if err is not None else ""

    if raw:
        logger.warning(
            "[humanize_error] %s | raw: %s",
            context or "(no context)",
            raw[:500],
        )

    if context:
        return f"{context}. Please try again."

    lowered = raw.lower()

    if (
        "connection refused" in lowered
        or "connection reset" in lowered
        or "name resolution" in lowered
        or "network is unreachable" in lowered
        or "failed to connect" in lowered
        or "nodename nor servname" in lowered
    ):
        return "We couldn't reach an upstream service. Try again in a moment."

    if "timeout" in lowered or "timed out" in lowered:
        return "The request took too long. Please try again."

    if (
        "unauthorized" in lowered
        or " 401" in raw
        or "invalid api key" in lowered
        or "invalid_api_key" in lowered
    ):
        return "Authentication failed with an upstream service. Check your API keys in Settings."

    if (
        "rate limit" in lowered
        or " 429" in raw
        or "too many requests" in lowered
    ):
        return "Hit a rate limit on an upstream service. Wait a moment and try again."

    if " 500" in raw or " 502" in raw or " 503" in raw or " 504" in raw:
        return "An upstream service hit a snag. Give it a moment and try again."

    return fallback
