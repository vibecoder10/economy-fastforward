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
     platform-published video's own analytics) is ``run_launch_pattern_
     analysis`` below (checklist C56, P4.2-g) — called by
     ``youtube_sync.py::_writeback_matched_videos`` once a platform-launched
     video's analytics mature (same bar ``routes/learning_extraction.py``'s
     ``extract_learnings()`` already established: ``ctr`` populated AND
     ``impressions >= 1000``). It reuses the SAME brain as the import-time
     analyzer (``propose_patterns_from_analytics`` / ``score_outlier_
     patterns``, unchanged) rather than a parallel implementation, narrowed
     to candidates about the newly-matured video(s) and passed through the
     shared dedup gate (``_dedupe_candidates``) added this chunk — see that
     function's docstring for why import-time analysis ALSO gained a dedup
     pass here (it had none before: a second ``learn_channel`` run would
     have re-inserted duplicate 'proposed' rows for an unchanged outlier).

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

from database import execute, fetch_all, fetch_one

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
    hiccup here must not abort the rest of ``learn_channel``'s learners.

    Dedupes against existing patterns (checklist C56 fix — this had NO
    dedup before: re-running ``learn_channel`` on a tenant whose outlier set
    hadn't changed would re-insert a duplicate 'proposed' row every time).
    See ``_dedupe_candidates`` — the SAME dedup gate the per-launch trigger
    (``run_launch_pattern_analysis``) uses, so both triggers converge on one
    dedup brain, not two."""
    try:
        candidates = await propose_patterns_from_analytics(tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_patterns: import analysis failed for tenant=%s: %s", tenant_id, e)
        return {"proposed": 0, "rows": [], "error": str(e)}
    if not candidates:
        return {"proposed": 0, "rows": []}
    candidates = await _dedupe_candidates(tenant_id, candidates)
    if not candidates:
        return {"proposed": 0, "rows": []}
    saved = await bulk_create_patterns(tenant_id, candidates, source="import_analysis")
    return {"proposed": len(saved), "rows": saved}


# ---------------------------------------------------------------------------
# Pure — dedup brain shared by BOTH pattern-proposal triggers (checklist C56,
# the "two convergent entry points" law: ONE analysis brain, not two).
# ---------------------------------------------------------------------------

def _candidate_key(evidence: Any) -> Optional[tuple[str, str]]:
    """The "same claim" key for an outlier candidate: (video_id, metric).
    ``score_outlier_patterns`` produces single-video, single-metric claims
    (its own docstring: "never deduplicated here, since they're distinct
    claims" — i.e. distinct ACROSS metrics, but the SAME claim if re-scored
    again on the same video+metric later). Mirrors the repo's existing
    dedup precedent in ``routes/learning_extraction.py::extract_learnings``
    (keys on ``(category, pattern_name)`` before upserting into
    ``learnings``) — same shape, different table. Returns None when the
    evidence doesn't carry enough to key on (never raises; a candidate that
    can't be keyed is treated as un-dedupable, not silently dropped)."""
    ev = evidence if isinstance(evidence, dict) else {}
    vids = ev.get("video_ids") or []
    metric = ev.get("metric")
    if not vids or not metric:
        return None
    return (str(vids[0]), str(metric))


def _dedupe_candidates_against_rows(candidates: list[dict], existing_rows: list[dict]) -> list[dict]:
    """Pure: given freshly-scored candidates and this tenant's EXISTING
    ``channel_patterns`` rows (any status, any source), return only the
    candidates that are genuinely NEW claims.

    - No existing row shares this candidate's (video_id, metric) key ->
      keep (first time this claim has ever been raised).
    - An existing 'proposed' or 'confirmed' row shares the key -> drop
      (already live or already awaiting review; never re-propose the same
      claim while it's active).
    - Every existing row sharing the key is 'retired' -> keep ONLY if this
      candidate's evidence covers a strictly LARGER cohort
      (``evidence.cohort_size``) than the retired row's. Cohort size only
      grows as the channel accumulates more analytics history, so a larger
      cohort is objectively NEWER evidence — never the same snapshot being
      silently reasserted after a human explicitly walked the pattern back
      (decisions.md: "retirement was a human decision; re-proposing it
      needs NEW evidence").
    - A candidate that can't be keyed (missing video_ids/metric) -> always
      kept; refusing to dedupe a claim we can't identify is safer than
      guessing it's a repeat."""
    by_key: dict[tuple, list[dict]] = {}
    for row in existing_rows or []:
        if not isinstance(row, dict):
            continue
        key = _candidate_key(row.get("evidence"))
        if key:
            by_key.setdefault(key, []).append(row)

    fresh: list[dict] = []
    for c in candidates or []:
        if not isinstance(c, dict):
            continue
        key = _candidate_key(c.get("evidence"))
        if key is None:
            fresh.append(c)
            continue
        matches = by_key.get(key, [])
        if not matches:
            fresh.append(c)
            continue
        if any(m.get("status") in ("proposed", "confirmed") for m in matches):
            continue
        retired_cohorts = [
            int((m.get("evidence") or {}).get("cohort_size") or 0) for m in matches
        ]
        new_cohort = int((c.get("evidence") or {}).get("cohort_size") or 0)
        if new_cohort > max(retired_cohorts, default=0):
            fresh.append(c)
    return fresh


async def _dedupe_candidates(tenant_id, candidates: list[dict]) -> list[dict]:
    """Async wrapper: fetch this tenant's existing patterns (every status,
    every source — a launch-analysis candidate must dedupe against an
    import-analysis row for the same video+metric too, since it's the same
    claim regardless of which trigger raised it first) and delegate to the
    pure resolver above. Fails OPEN (returns candidates UNFILTERED) on a DB
    hiccup — a broken dedup lookup must never silently drop a real
    proposal; worst case with fail-open is a duplicate a human can retire,
    never the reverse (proposals silently lost)."""
    if not candidates:
        return []
    try:
        existing = await list_patterns(tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_patterns: dedup lookup failed for tenant=%s: %s", tenant_id, e)
        return candidates
    return _dedupe_candidates_against_rows(candidates, existing)


# ---------------------------------------------------------------------------
# Per-launch trigger (checklist C56, P4.2-g) — decisions.md's "two
# convergent entry points" trigger (b).
# ---------------------------------------------------------------------------

async def run_launch_pattern_analysis(tenant_id: str, videos: list[dict]) -> dict:
    """Called by ``youtube_sync.py::_writeback_matched_videos`` once one or
    more platform-launched videos' analytics have matured this sync pass
    (``ctr`` populated AND ``impressions >= 1000`` — the SAME bar
    ``routes/learning_extraction.py::extract_learnings`` already uses for
    "matured enough to analyze").

    ``videos``: ``[{"youtube_video_id": <channel_videos.video_id>,
    "internal_video_id": <videos.id>}, ...]`` for every video that just
    crossed the maturity bar this sync. Re-scores the channel's CURRENT
    outlier standing ONCE for the whole batch (``propose_patterns_from_
    analytics`` — the SAME brain the import-time bulk analyzer uses, not a
    parallel implementation) rather than once per video — a channel's FIRST
    sync after this feature ships can have many already-matured platform
    videos cross the marker simultaneously, and re-running the full
    channel-wide outlier scan once per video would be needless repeated
    work for what's the same snapshot of ``channel_videos`` analytics within
    one sync pass. Then narrows to candidates ABOUT one of these videos —
    this trigger's job is reacting to THIS batch's own fresh analytics, not
    recomputing every other video's standing (that's the periodic/import-
    time bulk sweep's job) — dedupes via ``_dedupe_candidates`` (shared with
    the import-time trigger), persists survivors with
    ``source="launch_analysis"``, and drops one ``bot_activity`` row per
    persisted pattern (C52's notify pattern) so it surfaces in the existing
    activity feed. Never raises — a scoring/DB hiccup here must not break
    the analytics sync that calls it."""
    videos = [v for v in (videos or []) if isinstance(v, dict) and v.get("youtube_video_id")]
    if not videos:
        return {"proposed": 0, "rows": []}
    try:
        candidates = await propose_patterns_from_analytics(tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_patterns: launch analysis failed for tenant=%s: %s", tenant_id, e)
        return {"proposed": 0, "rows": [], "error": str(e)}
    if not candidates:
        return {"proposed": 0, "rows": []}

    wanted = {str(v["youtube_video_id"]) for v in videos}
    internal_by_yt = {str(v["youtube_video_id"]): v.get("internal_video_id") for v in videos}
    about_these = [
        c for c in candidates
        if wanted & {str(v) for v in ((c.get("evidence") or {}).get("video_ids") or [])}
    ]
    if not about_these:
        return {"proposed": 0, "rows": []}

    fresh = await _dedupe_candidates(tenant_id, about_these)
    if not fresh:
        return {"proposed": 0, "rows": []}

    saved = await bulk_create_patterns(tenant_id, fresh, source="launch_analysis")
    for row in saved:
        for yt_vid in (row.get("evidence") or {}).get("video_ids") or []:
            await _notify_launch_pattern_proposed(tenant_id, internal_by_yt.get(str(yt_vid)), row)
    return {"proposed": len(saved), "rows": saved}


async def _notify_launch_pattern_proposed(
    tenant_id: str, internal_video_id: Optional[str], pattern_row: dict
) -> None:
    """Best-effort ``bot_activity`` row (C52's notify pattern —
    ``autopilot_proposals.py::_notify_proposal_created`` is the precedent
    copied here) so a per-launch pattern proposal shows up wherever the
    existing activity feed (GET /api/activity, the dashboard's running-bots
    widget) already surfaces background events — reusing that table is the
    entire "notify" mechanism, no new infra. ``internal_video_id`` is the
    real ``videos.id`` FK (unlike the autopilot-proposal notify, this
    trigger always has a real video). Never raises — a notify failure must
    never fail the pattern-proposal write it's reporting on."""
    try:
        await execute(
            """INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message)
               VALUES ($1, $2, $3, $4, $5)""",
            tenant_id, "pattern_learning", internal_video_id, "completed",
            f"New pattern proposed from launch analytics: {pattern_row.get('pattern', '')[:200]}",
        )
    except Exception:
        logger.warning(
            "channel_patterns: bot_activity notify failed for tenant=%s (best-effort)",
            tenant_id, exc_info=True,
        )


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
