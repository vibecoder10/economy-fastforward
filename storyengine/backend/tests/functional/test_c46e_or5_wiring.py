"""Wiring tests for checklist C46e item 1 (OR-5 ruled — "Most Hated" named
DvsU mode with its own rule-table overrides).

Covers what tests/test_quality_rules.py (pure resolver unit tests) and
tests/test_machine_documentary_hold.py (direct _machine_story_plan unit
tests) can't:

  1. ``pipeline_executor._dvsu_mode_value_for_video`` — the video-level
     opt-in read that scope-matches a seeded QL-7-MH/QL-9-MH row.
  2. ``PipelineExecutor._load_dvsu_rule_overrides`` threading that value
     through to ``quality_rules.active_rules_for_video`` as
     ``dvsu_mode_value`` — a rule scoped ``{"dvsu_mode": "most_hated"}``
     must only ever match a video that explicitly opted in, never a video
     whose title merely LOOKS like a "most hated" video (never inferred).
  3. ``pipeline_executor._dvsu_thumbnail_series_warning`` (QL-66, OR-9
     ruled) — the five locked-phrase series + the open rule for everything
     else, proven against real title/text pairs (this is the FIRST test
     coverage for QL-66 anywhere in the suite — no prior code implemented
     this law at all, see the module-level comment above
     ``_DVSU_LOCKED_THUMBNAIL_SERIES`` in pipeline_executor.py).

Local/no-spend: every DB call is a fake fetch_all, matching
tests/functional/test_c46c_dvsu_deltas_wiring.py's established conventions.
"""

import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe  # noqa: E402


def _make_executor(tenant_id="tenant-test"):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = tenant_id
    return executor


def _video(**overrides):
    video = {
        "id": "video-1",
        "render_mode": "static_docu",
        "render_style": None,
        "research_skipped": False,
        "pipeline_stages": None,
        "research_payload": {},
    }
    video.update(overrides)
    return video


# ---------------------------------------------------------------------------
# _dvsu_mode_value_for_video — the video-level opt-in read.
# ---------------------------------------------------------------------------

def test_dvsu_mode_value_reads_dict_research_payload():
    video = _video(research_payload={"dvsu_mode": "Most-Hated"})
    assert pe._dvsu_mode_value_for_video(video) == "most_hated"


def test_dvsu_mode_value_reads_json_string_research_payload():
    video = _video(research_payload='{"dvsu_mode": "most_hated"}')
    assert pe._dvsu_mode_value_for_video(video) == "most_hated"


def test_dvsu_mode_value_none_when_absent():
    assert pe._dvsu_mode_value_for_video(_video(research_payload={})) is None


def test_dvsu_mode_value_none_on_bad_json():
    assert pe._dvsu_mode_value_for_video(_video(research_payload="not json")) is None


def test_dvsu_mode_value_none_for_non_dict_video():
    assert pe._dvsu_mode_value_for_video(None) is None


# ---------------------------------------------------------------------------
# _load_dvsu_rule_overrides — dvsu_mode_value threaded through scope match.
# ---------------------------------------------------------------------------

def test_load_overrides_scopes_most_hated_row_to_opted_in_video(monkeypatch):
    async def fake_fetch_all(query, *args):
        return [
            {"rule_id": "QL-7-MH",
             "law": "Most Hated mode: cap bare name-openers at about 20% (near-zero); "
                    "open on testimony, symptom, or bridge instead.",
             "evidence": None, "severity": "warn", "applies_to": '{"dvsu_mode": "most_hated"}'},
        ]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    executor = _make_executor()

    opted_in = asyncio.run(executor._load_dvsu_rule_overrides(
        _video(research_payload={"dvsu_mode": "most_hated"})
    ))
    assert opted_in["opener_budget"] == {"value": 0.2, "severity": "warn"}

    not_opted_in = asyncio.run(executor._load_dvsu_rule_overrides(_video(research_payload={})))
    assert not_opted_in == {}


def test_load_overrides_never_infers_most_hated_from_title(monkeypatch):
    """The mode is an explicit opt-in field, never a title-pattern guess —
    a video whose title says "Most Hated" but never set dvsu_mode must NOT
    pick up the QL-7-MH/QL-9-MH overrides."""
    async def fake_fetch_all(query, *args):
        return [
            {"rule_id": "QL-9-MH",
             "law": "Most Hated mode: the memorable fact must come from crew testimony "
                    "— a named or attributed complaint, nickname, or incident, not a "
                    "spec-sheet stat.",
             "evidence": None, "severity": "warn", "applies_to": '{"dvsu_mode": "most_hated"}'},
        ]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    executor = _make_executor()

    overrides = asyncio.run(executor._load_dvsu_rule_overrides(
        _video(video_title="Most Hated Warships Ever", research_payload={})
    ))
    assert overrides == {}


# ---------------------------------------------------------------------------
# QL-66 (OR-9 ruled) — the five locked thumbnail-text series + open rule.
# ---------------------------------------------------------------------------

def test_ql66_locked_series_requires_exact_phrase():
    assert pe._dvsu_thumbnail_series_warning("Every US Battleship Ever Built", "EVER BUILT") is None
    warning = pe._dvsu_thumbnail_series_warning("Every US Battleship Ever Built", "ALL BUILT")
    assert warning is not None
    assert "EVER BUILT" in warning


def test_ql66_locked_series_case_insensitive_match_passes():
    assert pe._dvsu_thumbnail_series_warning("Every British Carrier Ever Built", "ever built") is None


def test_ql66_all_five_locked_series_recognized():
    cases = [
        ("Every US Battleship Ever Built", "EVER BUILT"),
        ("The Never-Built Bomber We Nearly Got", "NEVER BUILT"),
        ("Most Hated Warships Ever", "MOST HATED"),
        ("Most Underrated Submarines", "UNDERRATED"),
        ("Aircraft Carriers Sunk in Combat", "SUNK IN COMBAT"),
    ]
    for title, locked_phrase in cases:
        assert pe._dvsu_thumbnail_series_warning(title, locked_phrase) is None
        assert pe._dvsu_thumbnail_series_warning(title, "WRONG TEXT") is not None


def test_ql66_new_type_without_a_series_is_unconstrained():
    """OR-9 ruled: "BY PILOTS"/"BY CREWS" (and anything else new) stay under
    the open 2-4-word rule until they prove out as a series — never flagged."""
    assert pe._dvsu_thumbnail_series_warning("Flown by the Best Pilots", "BY PILOTS") is None
    assert pe._dvsu_thumbnail_series_warning("Flown by the Best Pilots", "ANYTHING GOES") is None


def test_ql66_non_vacuous_module_constant_has_exactly_five_locked_phrases():
    phrases = {phrase for _, phrase in pe._DVSU_LOCKED_THUMBNAIL_SERIES}
    assert phrases == {"EVER BUILT", "NEVER BUILT", "MOST HATED", "UNDERRATED", "SUNK IN COMBAT"}
