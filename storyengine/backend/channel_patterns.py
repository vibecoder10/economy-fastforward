"""Per-channel, data-derived pattern store (checklist C46e — OR-6 EXPANDED).

Ryan's 2026-07-19 ruling on OR-6 REJECTED hardcoding MostHated-Warships (or
any style) as a universal anti-pattern — "it might work for another channel
or niche." What ships instead is a CAPABILITY: tag a video/style as an
anti-pattern (or a good-pattern) excluded from style-seed/few-shot sets,
PER CHANNEL, opt-in, nothing tagged by default. The same-day follow-up
ruling expanded this further into a design law: patterns are PROPOSED FROM
THE CHANNEL'S OWN ANALYTICS (never hardcoded, never copied cross-channel),
each proposal carrying its evidence, and a human must CONFIRM before any
tag takes effect.

Three layers, same discipline as ``quality_rules.py``:

  1. **Pure resolver** (``confirmed_anti_video_ids_from_rows``,
     ``score_outlier_patterns``) — no DB, no network. Trivially
     unit-testable; DB-touching callers fetch rows themselves and hand them
     in.

  2. **CRUD** (``list_patterns``, ``create_pattern``, ``bulk_create_patterns``,
     ``update_pattern``, ``confirm_pattern``, ``retire_pattern``,
     ``get_pattern``) — the only code that writes ``channel_patterns`` rows.
     Used by ``routes/channel_patterns.py`` (the tenant-facing CRUD/confirm/
     retire route) and by ``channel_dna.py``'s import-time learner.

  3. **Import-time analysis** (``propose_patterns_from_analytics``,
     ``run_import_pattern_analysis``) — the FIRST of the two convergent
     pattern-learning triggers decisions.md's 2026-07-19 "import caveat"
     entry calls for: bulk analysis of an imported channel's OWN analytics
     history (``channel_videos``), proposing outlier over/under-performers
     as candidate patterns with evidence attached. Writes status='proposed'
     rows directly (unlike quality_rules' parse-then-confirm-then-insert
     flow) — decisions.md's wording ("PROPOSE the channel's initial
     patterns... surfaced in the DNA digest") is DB-row language, and the
     schema's 'proposed' status exists precisely so these rows can be
     listed/reviewed before anyone confirms them. "Nothing takes effect
     until confirmed" (the OR-6 expansion's hard requirement) governs the
     EFFECT (exclusion), never row existence — see (1) above: only
     status='confirmed' AND polarity='anti' rows are ever read by the
     exclusion resolver.

     The SECOND trigger (per-launch incremental proposals from each new
     platform-published video's own analytics) is explicitly P4.2's
     flywheel job — NOT built here. The seam: a future per-launch job needs
     only to call ``create_pattern(..., source="launch_analysis")`` (or a
     launch-scoped sibling of ``score_outlier_patterns`` reading ``videos``
     instead of ``channel_videos``) and everything downstream (confirm,
     retire, exclusion) already works unchanged.

Retirement policy note: a MANUALLY-tagged pattern (source='manual') can be
retired directly (``retire_pattern`` is a plain status transition, no
evidence required by this primitive). A MACHINE-proposed-and-confirmed
pattern being walked back should, per decisions.md, itself be evidence-
backed + confirmed — that policy belongs to the future proposer that
requests the retraction (it would call ``create_pattern`` with a
"retraction" framing pattern, get it confirmed, then call
``retire_pattern`` on the original), not to this primitive, which stays a
simple, honest state transition.
"""

from __future__ import annotations

import json
import logging
import statistics
from typing import Any, Optional

from database import fetch_all, fetch_one

logger = logging.getLogger(__name__)

POLARITIES = {"anti", "good"}
SOURCES = {"import_analysis", "launch_analysis", "manual"}
STATUSES = {"proposed", "confirmed", "retired"}

_SELECT_COLS = (
    "id, tenant_id, pattern, polarity, evidence, source, status, "
    "confirmed_at, confirmed_by, created_at, updated_at"
)


# ---------------------------------------------------------------------------
# Pure — exclusion resolver. No DB, no network.
# ---------------------------------------------------------------------------

def _coerce_evidence(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def confirmed_anti_video_ids_from_rows(rows: list[dict]) -> set[str]:
    """The OR-6 expansion's core guarantee, as a pure function: only rows
    that are BOTH status='confirmed' AND polarity='anti' ever exclude
    anything. A 'proposed' row (machine-suggested, not yet reviewed), a
    'good'-polarity row, or a 'retired' row (walked back) never excludes —
    proven directly here rather than trusted to a caller's SQL WHERE clause
    alone (defense in depth, and independently testable)."""
    excluded: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "confirmed" or row.get("polarity") != "anti":
            continue
        evidence = _coerce_evidence(row.get("evidence"))
        for vid in evidence.get("video_ids") or []:
            if vid:
                excluded.add(str(vid))
    return excluded


async def confirmed_anti_video_ids(tenant_id: str) -> set[str]:
    """Async wrapper identity_builder (and any future style-seed picker)
    calls: fetch this tenant's confirmed+anti rows and resolve the
    exclusion set. Fails OPEN (empty set) on any DB error — a broken lookup
    must never crash identity building; it just means nothing is excluded
    this run, identical to every pre-C46e tenant's behavior."""
    try:
        rows = await list_patterns(tenant_id, polarity="anti", status="confirmed")
        return confirmed_anti_video_ids_from_rows(rows)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_patterns: exclusion lookup failed for tenant=%s: %s", tenant_id, e)
        return set()


# ---------------------------------------------------------------------------
# Pure — outlier scoring for the import-time analysis learner.
# ---------------------------------------------------------------------------

MIN_COHORT = 5          # need at least this many videos with a metric to trust a median
OUTLIER_THRESHOLD_PCT = 30.0  # a video +/- this far from the channel median is a candidate

_METRIC_LABELS = {
    "vph": "views-per-hour",
    "ctr": "click-through rate",
    "retention": "average retention",
}


def _metric_value(row: dict, metric: str) -> Optional[float]:
    if metric == "vph":
        v = row.get("_vph")
    elif metric == "ctr":
        v = row.get("ctr_percent")
    elif metric == "retention":
        v = row.get("avg_retention")
    else:
        return None
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def _outlier_candidate(row: dict, metric: str, median: float, value: float, cohort_size: int) -> dict:
    delta_pct = ((value - median) / median) * 100.0 if median else 0.0
    polarity = "anti" if delta_pct < 0 else "good"
    direction = "underperforms" if polarity == "anti" else "outperforms"
    metric_label = _METRIC_LABELS.get(metric, metric)
    title = (row.get("title") or "").strip() or "(untitled)"
    video_id = row.get("video_id")
    pattern = (
        f"\"{title}\" {direction} this channel's median {metric_label} by "
        f"{abs(round(delta_pct))}% (n={cohort_size} videos with {metric_label} data)."
    )
    return {
        "pattern": pattern,
        "polarity": polarity,
        "evidence": {
            "video_ids": [video_id] if video_id else [],
            "metric": metric,
            "channel_median": round(median, 3),
            "video_value": round(value, 3),
            "delta_pct": round(delta_pct, 1),
            "cohort_size": cohort_size,
        },
    }


def score_outlier_patterns(
    video_rows: list[dict],
    *,
    min_cohort: int = MIN_COHORT,
    threshold_pct: float = OUTLIER_THRESHOLD_PCT,
) -> list[dict]:
    """Pure: given channel_videos-shaped rows (``title``, ``video_id``, plus
    whichever of ``_vph`` (precomputed by the caller via
    ``own_vph.compute_own_vph``), ``ctr_percent``, ``avg_retention`` are
    present), flag per-video outliers against the CHANNEL'S OWN median on
    each metric independently — the C30/C33-style "by-style aggregate"
    approach, at video granularity (the exact granularity OR-6's own
    motivating example, MostHated-Warships, used). A metric with fewer than
    ``min_cohort`` non-null values is skipped entirely (too small a sample
    to trust a median) — never raises, never guesses. One video can surface
    on more than one metric (each becomes its own proposal, own evidence);
    never deduplicated here, since they're distinct claims."""
    candidates: list[dict] = []
    for metric in _METRIC_LABELS:
        pairs = [(row, _metric_value(row, metric)) for row in (video_rows or [])]
        pairs = [(row, v) for row, v in pairs if v is not None]
        if len(pairs) < min_cohort:
            continue
        median = statistics.median(v for _, v in pairs)
        if median <= 0:
            continue
        for row, value in pairs:
            delta_pct = ((value - median) / median) * 100.0
            if abs(delta_pct) >= threshold_pct:
                candidates.append(_outlier_candidate(row, metric, median, value, len(pairs)))
    return candidates


async def propose_patterns_from_analytics(tenant_id: str) -> list[dict]:
    """Fetch this tenant's imported ``channel_videos`` rows, compute VPH per
    row (``own_vph.compute_own_vph`` — the same math C33 uses for the
    tenant's own published videos, reused here for imported history), and
    score outliers. Never writes — the caller (``run_import_pattern_
    analysis``) is the only thing that persists candidates."""
    import own_vph

    rows = await fetch_all(
        "SELECT video_id, title, view_count, published_at, ctr_percent, avg_retention "
        "FROM channel_videos WHERE tenant_id = $1 AND video_id IS NOT NULL",
        tenant_id,
    )
    enriched = []
    for row in rows or []:
        row = dict(row)
        row["_vph"] = own_vph.compute_own_vph(row.get("view_count"), row.get("published_at"))
        enriched.append(row)
    return score_outlier_patterns(enriched)


async def run_import_pattern_analysis(tenant_id: str) -> dict:
    """The import-time trigger (decisions.md's "TWO convergent entry
    points" entry, trigger (a)): propose candidates from this tenant's
    imported analytics, persist them as status='proposed' rows (source=
    'import_analysis'), and return a summary shape ``channel_dna.py``'s
    learner can fold into its digest report. Never raises — a scoring or DB
    hiccup here must not abort the rest of ``learn_channel``'s learners."""
    try:
        candidates = await propose_patterns_from_analytics(tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_patterns: import analysis failed for tenant=%s: %s", tenant_id, e)
        return {"proposed": 0, "rows": [], "error": str(e)}
    if not candidates:
        return {"proposed": 0, "rows": []}
    saved = await bulk_create_patterns(tenant_id, candidates, source="import_analysis")
    return {"proposed": len(saved), "rows": saved}


# ---------------------------------------------------------------------------
# CRUD — the only code that writes channel_patterns rows.
# ---------------------------------------------------------------------------

def _decode_row(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    row = dict(row)
    row["evidence"] = _coerce_evidence(row.get("evidence"))
    return row


async def list_patterns(
    tenant_id, *, polarity: Optional[str] = None, status: Optional[str] = None
) -> list[dict]:
    query = f"SELECT {_SELECT_COLS} FROM channel_patterns WHERE tenant_id = $1"
    args: list[Any] = [tenant_id]
    if polarity:
        args.append(polarity)
        query += f" AND polarity = ${len(args)}"
    if status:
        args.append(status)
        query += f" AND status = ${len(args)}"
    query += " ORDER BY created_at DESC"
    rows = await fetch_all(query, *args)
    return [_decode_row(r) for r in (rows or [])]


async def get_pattern(tenant_id, id_: str) -> Optional[dict]:
    row = await fetch_one(
        f"SELECT {_SELECT_COLS} FROM channel_patterns WHERE tenant_id = $1 AND id = $2",
        tenant_id, id_,
    )
    return _decode_row(row)


async def create_pattern(
    tenant_id, *, pattern: str, polarity: str, evidence: Optional[dict] = None,
    source: str, status: str = "proposed",
) -> dict:
    polarity = polarity if polarity in POLARITIES else "anti"
    source = source if source in SOURCES else "manual"
    status = status if status in STATUSES else "proposed"
    row = await fetch_one(
        f"""INSERT INTO channel_patterns (tenant_id, pattern, polarity, evidence, source, status)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            RETURNING {_SELECT_COLS}""",
        tenant_id, str(pattern).strip(), polarity,
        json.dumps(evidence if isinstance(evidence, dict) else {}), source, status,
    )
    return _decode_row(row)


async def bulk_create_patterns(tenant_id, rows: list[dict], *, source: str) -> list[dict]:
    """Used by the import-time learner (and, in principle, a future
    per-launch proposer). Skips any candidate missing a pattern string;
    never raises on a single bad candidate."""
    saved = []
    for r in rows or []:
        pattern = str((r or {}).get("pattern") or "").strip()
        if not pattern:
            continue
        saved.append(await create_pattern(
            tenant_id, pattern=pattern, polarity=(r or {}).get("polarity") or "anti",
            evidence=(r or {}).get("evidence"), source=source, status="proposed",
        ))
    return saved


async def update_pattern(tenant_id, id_: str, updates: dict) -> Optional[dict]:
    """Edit a subset of {pattern, polarity, evidence, status}. Column names
    are a hardcoded whitelist (never built from caller input). Prefer
    ``confirm_pattern``/``retire_pattern`` for status transitions (they also
    stamp confirmed_at/confirmed_by) — this exists for plain text/evidence
    edits on an as-yet-unconfirmed proposal."""
    set_clauses: list[str] = []
    args: list[Any] = []
    idx = 1
    for col in ("pattern", "polarity", "evidence", "status"):
        if col not in updates:
            continue
        if col == "evidence":
            set_clauses.append(f"evidence = ${idx}::jsonb")
            args.append(json.dumps(updates[col] if isinstance(updates[col], dict) else {}))
        else:
            set_clauses.append(f"{col} = ${idx}")
            args.append(updates[col])
        idx += 1
    if not set_clauses:
        return await get_pattern(tenant_id, id_)
    set_clauses.append("updated_at = now()")
    args.extend([tenant_id, id_])
    query = (
        f"UPDATE channel_patterns SET {', '.join(set_clauses)} "
        f"WHERE tenant_id = ${idx} AND id = ${idx + 1} RETURNING {_SELECT_COLS}"
    )
    row = await fetch_one(query, *args)
    return _decode_row(row)


async def confirm_pattern(tenant_id, id_: str, *, confirmed_by: Optional[str] = None) -> Optional[dict]:
    """The ONLY transition that makes a pattern take effect. Works from
    'proposed' (the normal path) or re-confirming an already-confirmed row
    (idempotent, just refreshes the stamp) — never from 'retired' without a
    fresh proposal, since ``get_pattern`` + this function's caller (the
    thin route / chat handler) always looks up the row it's confirming, and
    a UI would never offer "confirm" on an already-retired row."""
    row = await fetch_one(
        f"""UPDATE channel_patterns
            SET status = 'confirmed', confirmed_at = now(), confirmed_by = $3, updated_at = now()
            WHERE tenant_id = $1 AND id = $2
            RETURNING {_SELECT_COLS}""",
        tenant_id, id_, confirmed_by,
    )
    return _decode_row(row)


async def retire_pattern(tenant_id, id_: str, *, confirmed_by: Optional[str] = None) -> Optional[dict]:
    """Reverses a confirmed pattern's effect (or rejects a still-'proposed'
    one outright) — a plain, direct status transition. See this module's
    docstring for the policy nuance (a machine-confirmed pattern's
    retirement SHOULD itself be evidence-backed, per decisions.md) — that
    policy lives in the caller that requests the retraction, not here."""
    row = await fetch_one(
        f"""UPDATE channel_patterns
            SET status = 'retired', confirmed_at = now(), confirmed_by = $3, updated_at = now()
            WHERE tenant_id = $1 AND id = $2
            RETURNING {_SELECT_COLS}""",
        tenant_id, id_, confirmed_by,
    )
    return _decode_row(row)
