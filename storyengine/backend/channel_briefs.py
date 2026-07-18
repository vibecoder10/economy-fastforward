"""Shared, tenant-scoped data briefs for "what should I make next / how's my
channel doing" (C15d: one director voice + data reach).

These three builders used to live only in routes/chat.py, reachable solely
from the HOME producer's prompt (via _loop_brief). The in-video copilot's
tool-using brain (agent_brain.py) had no way to answer the same questions
from inside a video. Moved here — a module with no dependency on chat.py or
agent_brain.py — so BOTH can import the SAME implementation with no risk of
a circular import (agent_brain.py needs these; chat.py already imports
agent_brain lazily inside a function, so a module-level import of chat.py
from agent_brain.py would be fragile to load order — this avoids that
entirely).

Each function is tenant-scoped (WHERE tenant_id = $1, never cross-tenant) and
fail-soft: any DB error is logged and swallowed, returning '' so a broken
brief never crashes a chat turn (home OR in-video).
"""

from __future__ import annotations

import logging

from database import fetch_all

logger = logging.getLogger(__name__)


async def _next_to_make_brief(tenant_id) -> str:
    """The strongest UNMODELED competitor winners to make next, scored the same way
    Autopilot scores candidates (view velocity + freshness + a small DNA boost). Lets
    the chat answer 'what should I make next?' with ranked, scored picks the creator
    can build on the spot. Top 5 by score. Fail-soft -> ''."""
    try:
        from routes.autopilot import calculate_confidence_with_breakdown
        rows = await fetch_all(
            "SELECT title, channel, url, vph, hours_old, views, distilled_at "
            "FROM competitor_videos WHERE tenant_id = $1 AND views > 0 AND removed_at IS NULL "
            "AND (modeled = false OR modeled IS NULL) ORDER BY vph DESC NULLS LAST LIMIT 12",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_briefs: next-to-make brief failed: %s", e)
        return ""
    if not rows:
        return ""
    scored: list[tuple[float, dict]] = []
    for r in rows:
        vph = float(r.get("vph") or 0)
        h = r.get("hours_old")
        hours = float(h) if h is not None else 9999.0
        try:
            bd = calculate_confidence_with_breakdown(vph, hours, {"has_dna": r.get("distilled_at") is not None})
            score = float(bd.total_score)
        except Exception:  # noqa: BLE001
            score = 0.0
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    lines = []
    for score, r in scored[:5]:
        title = (r.get("title") or "").strip()
        ch = r.get("channel") or "?"
        days = round((float(r.get("hours_old")) / 24)) if r.get("hours_old") is not None else None
        age = f"{days}d" if days else "new"
        url = r.get("url") or ""
        lines.append(f'[{score:.0f}/100] "{title}" - {ch} ({int(r.get("views") or 0):,} views, {age}) {url}')
    return ("\nWHAT TO MAKE NEXT (the creator's strongest UNMODELED competitor winners, scored 0-100 on "
            "view velocity + freshness; when they ask what to make or pick one, propose it and set "
            "spec.reference_url to that video's link so it gets modeled on real data):\n- "
            + "\n- ".join(lines))


async def _own_performance_brief(tenant_id) -> str:
    """The creator's OWN recently-published videos with REAL synced YouTube analytics
    (views, CTR, retention). Lets the chat answer 'how did my videos do?' and diagnose
    weak spots. Top 5 most-recently-synced. Fail-soft -> ''."""
    try:
        rows = await fetch_all(
            "SELECT video_title, views, ctr, impressions, avg_retention "
            "FROM videos WHERE tenant_id = $1 AND last_analytics_sync IS NOT NULL "
            "ORDER BY last_analytics_sync DESC LIMIT 5",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_briefs: own performance brief failed: %s", e)
        return ""
    if not rows:
        return ""
    lines = []
    for r in rows:
        t = (r.get("video_title") or "Untitled").strip()
        parts = [f"{int(r.get('views') or 0):,} views"]
        ctr = r.get("ctr")
        parts.append(f"{float(ctr):.1f}% CTR" if ctr is not None else "CTR n/a")
        ret = r.get("avg_retention")
        if ret is not None:
            parts.append(f"{float(ret):.0f}% retention")
        imp = r.get("impressions")
        if imp:
            parts.append(f"{int(imp):,} impressions")
        lines.append(f'"{t}" - ' + ", ".join(parts))
    return ("\nYOUR OWN PUBLISHED VIDEOS (real YouTube analytics; use to answer how the channel is doing "
            "and to DIAGNOSE - low impressions = title/SEO/topic, low CTR = title+thumbnail, low "
            "retention = hook/pacing):\n- " + "\n- ".join(lines))


async def _learnings_brief(tenant_id) -> str:
    """Proven patterns this channel has LEARNED (title/hook/script patterns that
    correlate with higher CTR, mined from its own results). Lets the chat cite 'what
    works for you' with evidence. Top 6 by confidence. Fail-soft -> ''."""
    try:
        rows = await fetch_all(
            "SELECT category, pattern, confidence, sample_size, avg_ctr FROM learnings "
            "WHERE tenant_id = $1 AND active = true ORDER BY confidence DESC LIMIT 6",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_briefs: learnings brief failed: %s", e)
        return ""
    if not rows:
        return ""
    lines = []
    for r in rows:
        cat = r.get("category") or "general"
        pat = (r.get("pattern") or "").strip()
        ctr = r.get("avg_ctr")
        ctr_s = f", ~{float(ctr):.1f}% CTR" if ctr else ""
        n = int(r.get("sample_size") or 0)
        lines.append(f"[{cat}] {pat}{ctr_s} (n={n})")
    return ("\nWHAT THIS CHANNEL HAS LEARNED (proven patterns from its own results - lean on these and "
            "cite them when advising):\n- " + "\n- ".join(lines))
