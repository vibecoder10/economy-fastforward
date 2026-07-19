"""Pure-module + CRUD unit tests for channel_patterns.py (checklist C46e,
OR-6 EXPANDED).

Covers the parts that need no DB and no live Claude call:
  - confirmed_anti_video_ids_from_rows: the OR-6 expansion's core guarantee
    — only status='confirmed' AND polarity='anti' rows ever exclude
    anything; proposed/good/retired rows never do.
  - score_outlier_patterns: the import-time analysis' pure scoring function
    — outlier detection against the channel's OWN median, per metric,
    min-cohort gated, never guessing on too-small a sample.
  - CRUD functions (fake DB via monkeypatched module-level fetch_*), same
    convention as tests/test_quality_rules.py.
"""

import asyncio

import channel_patterns as cp


# ---------------------------------------------------------------------------
# confirmed_anti_video_ids_from_rows — the exclusion resolver.
# ---------------------------------------------------------------------------

def _row(status, polarity, video_ids=None, evidence=None):
    ev = evidence if evidence is not None else {"video_ids": video_ids or []}
    return {"id": "row-1", "status": status, "polarity": polarity, "evidence": ev}


def test_confirmed_anti_row_excludes_its_video_ids():
    rows = [_row("confirmed", "anti", ["yt-1", "yt-2"])]
    assert cp.confirmed_anti_video_ids_from_rows(rows) == {"yt-1", "yt-2"}


def test_proposed_row_never_excludes_anything():
    rows = [_row("proposed", "anti", ["yt-1"])]
    assert cp.confirmed_anti_video_ids_from_rows(rows) == set()


def test_confirmed_good_polarity_row_never_excludes_anything():
    rows = [_row("confirmed", "good", ["yt-1"])]
    assert cp.confirmed_anti_video_ids_from_rows(rows) == set()


def test_retired_row_never_excludes_anything():
    rows = [_row("retired", "anti", ["yt-1"])]
    assert cp.confirmed_anti_video_ids_from_rows(rows) == set()


def test_mixed_rows_only_confirmed_anti_contributes():
    rows = [
        _row("confirmed", "anti", ["yt-1"]),
        _row("proposed", "anti", ["yt-2"]),
        _row("confirmed", "good", ["yt-3"]),
        _row("retired", "anti", ["yt-4"]),
    ]
    assert cp.confirmed_anti_video_ids_from_rows(rows) == {"yt-1"}


def test_evidence_as_json_string_is_coerced():
    rows = [{"id": "r1", "status": "confirmed", "polarity": "anti",
             "evidence": '{"video_ids": ["yt-9"]}'}]
    assert cp.confirmed_anti_video_ids_from_rows(rows) == {"yt-9"}


def test_evidence_without_video_ids_key_excludes_nothing():
    rows = [_row("confirmed", "anti", evidence={"metric": "vph"})]
    assert cp.confirmed_anti_video_ids_from_rows(rows) == set()


def test_garbage_rows_never_raise():
    assert cp.confirmed_anti_video_ids_from_rows([None, "not a dict", {}]) == set()
    assert cp.confirmed_anti_video_ids_from_rows([]) == set()
    assert cp.confirmed_anti_video_ids_from_rows(None) == set()


def test_confirmed_anti_video_ids_async_wrapper_fails_open_on_error(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("no channel_patterns table yet")

    monkeypatch.setattr(cp, "list_patterns", boom)
    result = asyncio.run(cp.confirmed_anti_video_ids("tenant-1"))
    assert result == set()


def test_confirmed_anti_video_ids_async_wrapper_filters_via_list_patterns(monkeypatch):
    captured = {}

    async def fake_list_patterns(tenant_id, *, polarity=None, status=None):
        captured["args"] = (tenant_id, polarity, status)
        return [_row("confirmed", "anti", ["yt-1"])]

    monkeypatch.setattr(cp, "list_patterns", fake_list_patterns)
    result = asyncio.run(cp.confirmed_anti_video_ids("tenant-1"))
    assert result == {"yt-1"}
    assert captured["args"] == ("tenant-1", "anti", "confirmed")


# ---------------------------------------------------------------------------
# score_outlier_patterns — pure import-time analysis scoring.
# ---------------------------------------------------------------------------

def _video_row(video_id, title, vph=None, ctr=None, retention=None):
    return {"video_id": video_id, "title": title, "_vph": vph, "ctr_percent": ctr, "avg_retention": retention}


def test_outlier_scoring_flags_underperformer_below_threshold():
    rows = [_video_row(f"v{i}", f"Normal {i}", vph=10.0) for i in range(5)]
    rows.append(_video_row("weak", "Weak One", vph=5.0))  # 50% below median of 10
    candidates = cp.score_outlier_patterns(rows, min_cohort=5, threshold_pct=30.0)
    weak_candidates = [c for c in candidates if c["evidence"]["video_ids"] == ["weak"]]
    assert len(weak_candidates) == 1
    assert weak_candidates[0]["polarity"] == "anti"
    assert weak_candidates[0]["evidence"]["metric"] == "vph"
    assert weak_candidates[0]["evidence"]["cohort_size"] == 6
    assert "Weak One" in weak_candidates[0]["pattern"]
    assert "underperforms" in weak_candidates[0]["pattern"]


def test_outlier_scoring_flags_overperformer_as_good_polarity():
    rows = [_video_row(f"v{i}", f"Normal {i}", vph=10.0) for i in range(5)]
    rows.append(_video_row("strong", "Strong One", vph=20.0))  # +100%
    candidates = cp.score_outlier_patterns(rows, min_cohort=5, threshold_pct=30.0)
    strong = [c for c in candidates if c["evidence"]["video_ids"] == ["strong"]]
    assert len(strong) == 1
    assert strong[0]["polarity"] == "good"
    assert "outperforms" in strong[0]["pattern"]


def test_outlier_scoring_skips_metric_below_min_cohort():
    rows = [_video_row(f"v{i}", f"Video {i}", vph=10.0) for i in range(3)]
    rows.append(_video_row("outlier", "Outlier", vph=1.0))
    candidates = cp.score_outlier_patterns(rows, min_cohort=5, threshold_pct=30.0)
    assert candidates == []  # only 4 videos with vph data, below min_cohort=5


def test_outlier_scoring_ignores_null_metric_values():
    rows = [_video_row(f"v{i}", f"Video {i}", vph=10.0) for i in range(5)]
    rows.append(_video_row("no-data", "No Data", vph=None))
    candidates = cp.score_outlier_patterns(rows, min_cohort=5, threshold_pct=30.0)
    assert all(c["evidence"]["video_ids"] != ["no-data"] for c in candidates)


def test_outlier_scoring_never_flags_within_threshold():
    rows = [_video_row(f"v{i}", f"Video {i}", vph=10.0) for i in range(6)]
    rows.append(_video_row("close", "Close Enough", vph=11.0))  # +10%, within 30%
    candidates = cp.score_outlier_patterns(rows, min_cohort=5, threshold_pct=30.0)
    assert candidates == []


def test_outlier_scoring_can_flag_same_video_on_multiple_metrics():
    rows = []
    for i in range(5):
        rows.append(_video_row(f"v{i}", f"Video {i}", vph=10.0, ctr=5.0))
    rows.append(_video_row("both-weak", "Both Weak", vph=5.0, ctr=2.0))
    candidates = cp.score_outlier_patterns(rows, min_cohort=5, threshold_pct=30.0)
    metrics_flagged = {c["evidence"]["metric"] for c in candidates if c["evidence"]["video_ids"] == ["both-weak"]}
    assert metrics_flagged == {"vph", "ctr"}


def test_outlier_scoring_empty_input_returns_empty():
    assert cp.score_outlier_patterns([]) == []
    assert cp.score_outlier_patterns(None) == []


# ---------------------------------------------------------------------------
# CRUD — tenant-scoped (fake DB via monkeypatched module-level fetch_*)
# ---------------------------------------------------------------------------

def test_list_patterns_is_tenant_scoped(monkeypatch):
    captured = {}

    async def fake_fetch_all(query, *args):
        captured["query"] = query
        captured["args"] = args
        return [{"id": "1", "tenant_id": "tenant-xyz", "pattern": "x", "polarity": "anti",
                  "evidence": '{"video_ids": ["yt-1"]}', "source": "import_analysis",
                  "status": "proposed", "confirmed_at": None, "confirmed_by": None,
                  "created_at": None, "updated_at": None}]

    monkeypatch.setattr(cp, "fetch_all", fake_fetch_all)
    rows = asyncio.run(cp.list_patterns("tenant-xyz"))
    assert captured["args"] == ("tenant-xyz",)
    assert "WHERE tenant_id = $1" in captured["query"]
    assert rows[0]["evidence"] == {"video_ids": ["yt-1"]}  # decoded from string


def test_list_patterns_filters_by_polarity_and_status(monkeypatch):
    captured = {}

    async def fake_fetch_all(query, *args):
        captured["query"] = query
        captured["args"] = args
        return []

    monkeypatch.setattr(cp, "fetch_all", fake_fetch_all)
    asyncio.run(cp.list_patterns("tenant-xyz", polarity="anti", status="confirmed"))
    assert captured["args"] == ("tenant-xyz", "anti", "confirmed")
    assert "AND polarity = $2" in captured["query"]
    assert "AND status = $3" in captured["query"]


def test_create_pattern_defaults_to_proposed_status(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, *args):
        captured["query"] = query
        captured["args"] = args
        return {"id": "1", "tenant_id": args[0], "pattern": args[1], "polarity": args[2],
                 "evidence": args[3], "source": args[4], "status": args[5],
                 "confirmed_at": None, "confirmed_by": None, "created_at": None, "updated_at": None}

    monkeypatch.setattr(cp, "fetch_one", fake_fetch_one)
    row = asyncio.run(cp.create_pattern(
        "tenant-xyz", pattern="Weak openers", polarity="anti", source="import_analysis",
    ))
    assert row["status"] == "proposed"
    assert row["polarity"] == "anti"


def test_bulk_create_patterns_skips_rows_without_a_pattern(monkeypatch):
    inserted = []

    async def fake_fetch_one(query, *args):
        inserted.append(args)
        return {"id": str(len(inserted)), "tenant_id": args[0], "pattern": args[1],
                 "polarity": args[2], "evidence": args[3], "source": args[4], "status": args[5],
                 "confirmed_at": None, "confirmed_by": None, "created_at": None, "updated_at": None}

    monkeypatch.setattr(cp, "fetch_one", fake_fetch_one)
    saved = asyncio.run(cp.bulk_create_patterns(
        "tenant-xyz",
        [{"pattern": "Real pattern", "polarity": "anti"}, {"pattern": "  ", "polarity": "anti"}, {}],
        source="import_analysis",
    ))
    assert len(saved) == 1
    assert len(inserted) == 1


def test_confirm_pattern_stamps_status_and_confirmed_by(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, *args):
        captured["query"] = query
        captured["args"] = args
        return {"id": args[1], "tenant_id": args[0], "pattern": "x", "polarity": "anti",
                 "evidence": "{}", "source": "import_analysis", "status": "confirmed",
                 "confirmed_at": "now", "confirmed_by": args[2], "created_at": None, "updated_at": None}

    monkeypatch.setattr(cp, "fetch_one", fake_fetch_one)
    row = asyncio.run(cp.confirm_pattern("tenant-xyz", "row-1", confirmed_by="chat"))
    assert "status = 'confirmed'" in captured["query"]
    assert row["status"] == "confirmed"
    assert row["confirmed_by"] == "chat"


def test_retire_pattern_stamps_status(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, *args):
        captured["query"] = query
        return {"id": args[1], "tenant_id": args[0], "pattern": "x", "polarity": "anti",
                 "evidence": "{}", "source": "manual", "status": "retired",
                 "confirmed_at": "now", "confirmed_by": args[2], "created_at": None, "updated_at": None}

    monkeypatch.setattr(cp, "fetch_one", fake_fetch_one)
    row = asyncio.run(cp.retire_pattern("tenant-xyz", "row-1", confirmed_by="chat"))
    assert "status = 'retired'" in captured["query"]
    assert row["status"] == "retired"


def test_confirm_pattern_returns_none_when_not_found(monkeypatch):
    async def fake_fetch_one(*_a, **_k):
        return None

    monkeypatch.setattr(cp, "fetch_one", fake_fetch_one)
    row = asyncio.run(cp.confirm_pattern("tenant-xyz", "missing-id"))
    assert row is None


def test_update_pattern_only_sets_provided_fields(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, *args):
        captured["query"] = query
        captured["args"] = args
        return {"id": "1", "tenant_id": "tenant-xyz", "pattern": "edited", "polarity": "anti",
                 "evidence": "{}", "source": "manual", "status": "proposed",
                 "confirmed_at": None, "confirmed_by": None, "created_at": None, "updated_at": None}

    monkeypatch.setattr(cp, "fetch_one", fake_fetch_one)
    row = asyncio.run(cp.update_pattern("tenant-xyz", "row-1", {"pattern": "edited"}))
    assert "pattern = $1" in captured["query"]
    assert "polarity = " not in captured["query"]
    assert captured["args"][-2:] == ("tenant-xyz", "row-1")
    assert row["pattern"] == "edited"


# ---------------------------------------------------------------------------
# propose_patterns_from_analytics / run_import_pattern_analysis — the
# import-time trigger's DB-touching wrapper.
# ---------------------------------------------------------------------------

def test_propose_patterns_from_analytics_computes_vph_per_row(monkeypatch):
    import own_vph

    async def fake_fetch_all(query, *args):
        return [
            {"video_id": f"yt-{i}", "title": f"Video {i}", "view_count": 1000,
             "published_at": "2026-01-01T00:00:00+00:00", "ctr_percent": None, "avg_retention": None}
            for i in range(5)
        ] + [
            {"video_id": "yt-weak", "title": "Weak Video", "view_count": 10,
             "published_at": "2026-01-01T00:00:00+00:00", "ctr_percent": None, "avg_retention": None}
        ]

    monkeypatch.setattr(cp, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(own_vph, "compute_own_vph", lambda views, published_at: float(views))
    candidates = asyncio.run(cp.propose_patterns_from_analytics("tenant-xyz"))
    assert any(c["evidence"]["video_ids"] == ["yt-weak"] for c in candidates)


def test_run_import_pattern_analysis_persists_proposed_rows(monkeypatch):
    async def fake_propose(tenant_id):
        return [{"pattern": "Weak openers underperform", "polarity": "anti", "evidence": {"video_ids": ["yt-1"]}}]

    saved_rows = []

    async def fake_bulk_create(tenant_id, rows, *, source):
        for r in rows:
            saved_rows.append(r)
        return [{"id": "1", **r, "source": source, "status": "proposed"} for r in rows]

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", fake_propose)
    monkeypatch.setattr(cp, "bulk_create_patterns", fake_bulk_create)
    result = asyncio.run(cp.run_import_pattern_analysis("tenant-xyz"))
    assert result["proposed"] == 1
    assert saved_rows[0]["pattern"] == "Weak openers underperform"


def test_run_import_pattern_analysis_no_candidates_is_zero_not_error(monkeypatch):
    async def fake_propose(tenant_id):
        return []

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", fake_propose)
    result = asyncio.run(cp.run_import_pattern_analysis("tenant-xyz"))
    assert result == {"proposed": 0, "rows": []}


def test_run_import_pattern_analysis_fails_soft_on_error(monkeypatch):
    async def boom(tenant_id):
        raise RuntimeError("channel_videos query failed")

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", boom)
    result = asyncio.run(cp.run_import_pattern_analysis("tenant-xyz"))
    assert result["proposed"] == 0
    assert "error" in result


# ---------------------------------------------------------------------------
# checklist C56 (P4.2-g) — per-launch pattern flywheel, the second of
# decisions.md's "two convergent entry points" for channel_patterns.
# ---------------------------------------------------------------------------

def _candidate(video_id, metric, cohort_size=6, polarity="anti"):
    return {
        "pattern": f"\"{video_id}\" underperforms on {metric}.",
        "polarity": polarity,
        "evidence": {"video_ids": [video_id], "metric": metric, "cohort_size": cohort_size},
    }


def _existing_row(video_id, metric, status, cohort_size=6):
    return {
        "id": f"row-{video_id}-{metric}-{status}",
        "status": status,
        "polarity": "anti",
        "evidence": {"video_ids": [video_id], "metric": metric, "cohort_size": cohort_size},
    }


# --- _dedupe_candidates_against_rows (pure) ---------------------------------

def test_dedupe_keeps_candidate_with_no_existing_match():
    candidates = [_candidate("yt-1", "vph")]
    assert cp._dedupe_candidates_against_rows(candidates, []) == candidates


def test_dedupe_drops_candidate_matching_a_proposed_row():
    candidates = [_candidate("yt-1", "vph")]
    existing = [_existing_row("yt-1", "vph", "proposed")]
    assert cp._dedupe_candidates_against_rows(candidates, existing) == []


def test_dedupe_drops_candidate_matching_a_confirmed_row():
    candidates = [_candidate("yt-1", "vph")]
    existing = [_existing_row("yt-1", "vph", "confirmed")]
    assert cp._dedupe_candidates_against_rows(candidates, existing) == []


def test_dedupe_drops_candidate_matching_retired_row_with_equal_or_smaller_cohort():
    candidates = [_candidate("yt-1", "vph", cohort_size=6)]
    existing = [_existing_row("yt-1", "vph", "retired", cohort_size=6)]
    assert cp._dedupe_candidates_against_rows(candidates, existing) == []

    smaller = [_candidate("yt-1", "vph", cohort_size=5)]
    existing_bigger = [_existing_row("yt-1", "vph", "retired", cohort_size=8)]
    assert cp._dedupe_candidates_against_rows(smaller, existing_bigger) == []


def test_dedupe_keeps_candidate_matching_retired_row_with_larger_cohort():
    """Larger cohort_size == genuinely newer evidence (more channel history
    collected since the human retired it) — decisions.md's "re-proposing
    needs NEW evidence" bar."""
    candidates = [_candidate("yt-1", "vph", cohort_size=12)]
    existing = [_existing_row("yt-1", "vph", "retired", cohort_size=6)]
    assert cp._dedupe_candidates_against_rows(candidates, existing) == candidates


def test_dedupe_different_metric_same_video_is_not_deduped():
    candidates = [_candidate("yt-1", "ctr")]
    existing = [_existing_row("yt-1", "vph", "proposed")]  # different metric -> different key
    assert cp._dedupe_candidates_against_rows(candidates, existing) == candidates


def test_dedupe_different_video_same_metric_is_not_deduped():
    candidates = [_candidate("yt-2", "vph")]
    existing = [_existing_row("yt-1", "vph", "proposed")]
    assert cp._dedupe_candidates_against_rows(candidates, existing) == candidates


def test_dedupe_candidate_without_a_key_is_always_kept():
    unkeyable = {"pattern": "no evidence shape", "polarity": "anti", "evidence": {}}
    existing = [_existing_row("yt-1", "vph", "proposed")]
    assert cp._dedupe_candidates_against_rows([unkeyable], existing) == [unkeyable]


def test_dedupe_never_raises_on_garbage_existing_rows():
    candidates = [_candidate("yt-1", "vph")]
    assert cp._dedupe_candidates_against_rows(candidates, [None, "garbage", {}]) == candidates


# --- _dedupe_candidates (async wrapper) -------------------------------------

def test_dedupe_candidates_async_fetches_all_statuses_and_sources(monkeypatch):
    captured = {}

    async def fake_list_patterns(tenant_id, *, polarity=None, status=None):
        captured["args"] = (tenant_id, polarity, status)
        return [_existing_row("yt-1", "vph", "proposed")]

    monkeypatch.setattr(cp, "list_patterns", fake_list_patterns)
    result = asyncio.run(cp._dedupe_candidates("tenant-xyz", [_candidate("yt-1", "vph")]))
    assert result == []
    assert captured["args"] == ("tenant-xyz", None, None)  # every status, every source


def test_dedupe_candidates_async_empty_input_never_queries(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("should not query for an empty candidate list")

    monkeypatch.setattr(cp, "list_patterns", boom)
    assert asyncio.run(cp._dedupe_candidates("tenant-xyz", [])) == []


def test_dedupe_candidates_async_fails_open_on_lookup_error(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("no channel_patterns table yet")

    monkeypatch.setattr(cp, "list_patterns", boom)
    candidates = [_candidate("yt-1", "vph")]
    result = asyncio.run(cp._dedupe_candidates("tenant-xyz", candidates))
    assert result == candidates  # fails OPEN: never silently drops a real proposal


# --- run_import_pattern_analysis now dedupes (checklist C56 fix) -----------

def test_run_import_pattern_analysis_dedupes_before_persisting(monkeypatch):
    async def fake_propose(tenant_id):
        return [_candidate("yt-1", "vph"), _candidate("yt-2", "vph")]

    async def fake_dedupe(tenant_id, candidates):
        return [c for c in candidates if c["evidence"]["video_ids"] != ["yt-1"]]

    saved_rows = []

    async def fake_bulk_create(tenant_id, rows, *, source):
        saved_rows.extend(rows)
        return [{"id": str(i), **r, "source": source, "status": "proposed"} for i, r in enumerate(rows)]

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", fake_propose)
    monkeypatch.setattr(cp, "_dedupe_candidates", fake_dedupe)
    monkeypatch.setattr(cp, "bulk_create_patterns", fake_bulk_create)
    result = asyncio.run(cp.run_import_pattern_analysis("tenant-xyz"))
    assert result["proposed"] == 1
    assert saved_rows[0]["evidence"]["video_ids"] == ["yt-2"]


# --- run_launch_pattern_analysis --------------------------------------------

def test_run_launch_pattern_analysis_narrows_to_the_given_videos(monkeypatch):
    async def fake_propose(tenant_id):
        return [_candidate("yt-launched", "vph"), _candidate("yt-unrelated", "vph")]

    async def fake_dedupe(tenant_id, candidates):
        return candidates  # nothing existing

    saved_rows = []

    async def fake_bulk_create(tenant_id, rows, *, source):
        saved_rows.extend(rows)
        assert source == "launch_analysis"
        return [{"id": str(i), **r, "source": source, "status": "proposed"} for i, r in enumerate(rows)]

    notified = []

    async def fake_notify(tenant_id, internal_video_id, pattern_row):
        notified.append((tenant_id, internal_video_id, pattern_row))

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", fake_propose)
    monkeypatch.setattr(cp, "_dedupe_candidates", fake_dedupe)
    monkeypatch.setattr(cp, "bulk_create_patterns", fake_bulk_create)
    monkeypatch.setattr(cp, "_notify_launch_pattern_proposed", fake_notify)

    result = asyncio.run(cp.run_launch_pattern_analysis(
        "tenant-xyz", [{"youtube_video_id": "yt-launched", "internal_video_id": "internal-1"}],
    ))
    assert result["proposed"] == 1
    # the "unrelated" video's candidate (a different video that happens to
    # also be an outlier this run) must NEVER be proposed by this trigger —
    # that's the periodic/import-time bulk sweep's job, not per-launch's.
    assert saved_rows == [_candidate("yt-launched", "vph")]
    assert len(notified) == 1
    notify_tenant, notify_internal_id, notify_row = notified[0]
    assert notify_tenant == "tenant-xyz"
    assert notify_internal_id == "internal-1"  # correctly mapped from youtube_video_id
    assert notify_row["evidence"]["video_ids"] == ["yt-launched"]


def test_run_launch_pattern_analysis_no_matching_video_proposes_nothing(monkeypatch):
    async def fake_propose(tenant_id):
        return [_candidate("yt-other", "vph")]

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", fake_propose)
    result = asyncio.run(cp.run_launch_pattern_analysis(
        "tenant-xyz", [{"youtube_video_id": "yt-launched", "internal_video_id": "internal-1"}],
    ))
    assert result == {"proposed": 0, "rows": []}


def test_run_launch_pattern_analysis_empty_video_list_never_scores(monkeypatch):
    async def boom(tenant_id):
        raise AssertionError("should not score when no videos are given")

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", boom)
    result = asyncio.run(cp.run_launch_pattern_analysis("tenant-xyz", []))
    assert result == {"proposed": 0, "rows": []}


def test_run_launch_pattern_analysis_fails_soft_on_scoring_error(monkeypatch):
    async def boom(tenant_id):
        raise RuntimeError("channel_videos query failed")

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", boom)
    result = asyncio.run(cp.run_launch_pattern_analysis(
        "tenant-xyz", [{"youtube_video_id": "yt-1", "internal_video_id": "internal-1"}],
    ))
    assert result["proposed"] == 0
    assert "error" in result


def test_run_launch_pattern_analysis_dedupes_like_import_trigger(monkeypatch):
    """Same dedup gate as the import-time trigger — a pattern already
    'proposed' for this video+metric (regardless of which trigger raised it
    first) never gets a second row."""
    async def fake_propose(tenant_id):
        return [_candidate("yt-launched", "vph")]

    async def fake_list_patterns(tenant_id, *, polarity=None, status=None):
        return [_existing_row("yt-launched", "vph", "proposed")]

    created = []

    async def fake_bulk_create(tenant_id, rows, *, source):
        created.extend(rows)
        return []

    monkeypatch.setattr(cp, "propose_patterns_from_analytics", fake_propose)
    monkeypatch.setattr(cp, "list_patterns", fake_list_patterns)
    monkeypatch.setattr(cp, "bulk_create_patterns", fake_bulk_create)
    result = asyncio.run(cp.run_launch_pattern_analysis(
        "tenant-xyz", [{"youtube_video_id": "yt-launched", "internal_video_id": "internal-1"}],
    ))
    assert result == {"proposed": 0, "rows": []}
    assert created == []


# --- _notify_launch_pattern_proposed ----------------------------------------

def test_notify_launch_pattern_proposed_inserts_bot_activity_with_video_id(monkeypatch):
    captured = {}

    async def fake_execute(query, *args):
        captured["query"] = query
        captured["args"] = args

    monkeypatch.setattr(cp, "execute", fake_execute)
    asyncio.run(cp._notify_launch_pattern_proposed(
        "tenant-xyz", "internal-1", {"pattern": "Weak openers underperform"},
    ))
    assert "INSERT INTO bot_activity" in captured["query"]
    assert captured["args"][0] == "tenant-xyz"
    assert captured["args"][2] == "internal-1"  # video_id, unlike autopilot proposals' NULL
    assert "Weak openers underperform" in captured["args"][4]


def test_notify_launch_pattern_proposed_failure_never_raises(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(cp, "execute", boom)
    asyncio.run(cp._notify_launch_pattern_proposed("tenant-xyz", "internal-1", {"pattern": "x"}))
    # no assertion needed beyond "didn't raise"
