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
import re
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Marker for strings that are ALREADY user-facing copy. Background-task funnels
# (e.g. _set_task_status) humanize every failure error at the write boundary,
# which flattens unrecognized strings to the generic fallback — including
# deliberate, actionable messages like "Add your Anthropic key in Settings".
# Wrapping such copy with user_facing() lets it survive the funnel verbatim.
USER_FACING_PREFIX = "[[user-facing]] "


class ResearchProviderBlocked(RuntimeError):
    """Account repair is required; trying another research query cannot help."""

_SAFE_RESEARCH_GATE_MESSAGES = {
    "research gate failed; not advancing to scripting: roster validation failed": (
        "Research found a roster coverage or scope issue, so production stopped "
        "before scripting. Review the research roster, correct the issue, and retry."
    ),
    "research gate failed; not advancing to scripting: unit research-hold failed": (
        "Research for one or more roster entries did not meet the source requirements, "
        "so production stopped before scripting. Review the blocked research entries "
        "and retry."
    ),
}

_FACTUAL_RESEARCH_CORROBORATION_RE = re.compile(
    r"^\s*(?P<machine>[A-Za-z0-9][A-Za-z0-9 .,'’()/&+\-]{0,119}):\s*"
    r"claim_map row \d+ historical record or class construction count lacks independent corroboration\.",
    re.IGNORECASE,
)

_RESEARCH_PROVIDER_STOP_RE = re.compile(
    r"^research response stopped with "
    r"(?P<reason>refusal|context_window_exceeded|model_context_window_exceeded|unknown)\b",
    re.IGNORECASE,
)


def user_facing(message: str) -> str:
    """Mark a message as already-safe user copy (survives humanize_error)."""
    return USER_FACING_PREFIX + message


# Kie is the single upstream for text+image+video+voice; a banned / out-of-credit
# key is terminal (retrying can't recover it). These signals identify it across
# the opaque forms Kie returns it in (a Chinese "user banned" string, an
# insufficient-credit/balance message, or our own marker once raised).
KIE_BLOCK_MARKER = "KIE_ACCOUNT_BLOCKED"
_KIE_BLOCK_SIGNALS = (
    "用户已被封禁", "已被封禁", "封禁", "余额不足",
    "insufficient credit", "insufficient balance", "out of credit",
    "account banned", "account is banned", "account suspended",
    KIE_BLOCK_MARKER.lower(),
)


def is_kie_block(text) -> bool:
    """True if an error string/code signals a banned or out-of-credit Kie key."""
    if not text:
        return False
    raw = str(text)
    low = raw.lower()
    return any(sig in low or sig in raw for sig in _KIE_BLOCK_SIGNALS)


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

    # Explicitly-marked user copy passes through verbatim (no warning log —
    # it isn't a raw error, it's copy a developer wrote for the user).
    if raw.startswith(USER_FACING_PREFIX):
        return raw[len(USER_FACING_PREFIX):]

    if raw:
        logger.warning(
            "[humanize_error] %s | raw: %s",
            context or "(no context)",
            raw[:500],
        )

    if context:
        return f"{context}. Please try again."

    lowered = raw.lower()

    # Continuation failures retain a private draft, but none are safe to retry
    # automatically. Match only internal prefixes and reconstruct all visible
    # copy so provider bodies or checkpoint paths can never leak to the UI.
    if lowered.startswith("research response continuation limit reached"):
        return ("Research stopped after reaching its safe continuation limit. "
                "The draft is saved for review; no additional research was started.")

    if lowered.startswith((
        "research response checkpoint is ",
        "research response checkpoint does not match ",
    )):
        return ("The saved research checkpoint cannot be used safely. "
                "No new research was started; review the saved draft before trying again.")

    provider_stop = _RESEARCH_PROVIDER_STOP_RE.match(raw)
    if provider_stop:
        category = provider_stop.group("reason").lower().replace("_", " ")
        return (f"The research provider stopped before finishing ({category}). "
                "The draft is saved for review; no new research was started.")

    if lowered.startswith("research response stopped with "):
        return ("The research provider stopped before finishing for an unsupported response reason. "
                "The draft is saved for review; no new research was started.")

    if ("failed to parse research payload" in lowered
            or "research response formatting failed after one recovery attempt" in lowered):
        return ("Research returned an unreadable brief, so roster creation stopped. "
                "Your saved work is intact. Resume to retry research.")

    # These two pipeline gates are deliberate quality stops rather than opaque
    # exceptions. Match the complete known string so appended database/provider
    # details can never hitch a ride into customer-visible copy.
    safe_research_gate = _SAFE_RESEARCH_GATE_MESSAGES.get(lowered.strip())
    if safe_research_gate:
        return safe_research_gate

    # Factual machine review failures are deliberate quality stops. Preserve
    # the machine identity and actionable gate type, but reconstruct the copy
    # from this tightly matched prefix so row numbers, stack traces, provider
    # bodies, or arbitrary appended details can never reach the UI or queue.
    corroboration_match = _FACTUAL_RESEARCH_CORROBORATION_RE.match(raw)
    if corroboration_match:
        machine = corroboration_match.group("machine").strip()
        return (
            f"Research for {machine} stopped because a historical record or class "
            "construction count needs independent corroboration. Remove the optional "
            "record/count qualification, or cite a primary or museum record or two "
            "distinct source hosts supporting the same claim, then retry."
        )

    if "tavily" in lowered and ("out of credits" in lowered or "http 432" in lowered or "http 433" in lowered):
        return ("Tavily is out of credits or has reached its search plan limit. "
                "Add credits or raise the Tavily limit, then resume. Completed research is saved.")

    if "you have reached your specified api usage limits" in lowered:
        reset = re.search(r"regain access on (\d{4}-\d{2}-\d{2}) at (\d{2}:\d{2}) UTC", raw)
        message = ("Anthropic has reached its API usage limit. Raise the usage limit in the Anthropic Console, "
                   "then resume. Completed work is saved.")
        if reset:
            message += f" The provider reports a reset on {reset[1]} at {reset[2]} UTC."
        return message

    # Kie.ai account blocked / out of credit. Kie is the single upstream for
    # text+image+video+voice, so a banned or credit-exhausted key kills every
    # generation — and the raw signal is opaque. Map it to one actionable
    # message so the customer fixes their key instead of staring at a stuck
    # pipeline. Checked BEFORE the generic auth/401 branch.
    if is_kie_block(raw):
        return ("Your Kie.ai key looks blocked or out of credit, so generation "
                "can't run. Add or update it in Settings → API Keys.")

    if (
        "anthropic" in lowered
        and (
            "credit balance is too low" in lowered
            or "purchase credits" in lowered
            or "plans & billing" in lowered
            or "insufficient credit" in lowered
            or "insufficient balance" in lowered
        )
    ):
        return ("Your Anthropic/Claude key is out of credits, so script generation "
                "can't run. Add credits or update the key in Settings → API Keys.")

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
