"""Tests for C33's own-video VPH (checklist §3.4, docs/reports/2026-07-17-
storyengine-agent-audit-findings.md Sweep 3 finding #5): "VPH computed for
competitors only, never for own videos — scorecards compare apples to
oranges."

own_vph.compute_own_vph() wraps routes.niche._calculate_vph (the SAME math
the competitor side already uses) rather than reimplementing it — these
tests pin the wrapper's own contract on top of that reuse: unpublished ->
None (not 0.0), a just-published/clock-skew instant -> None (zero-hours
guard), and a known (views, published_at) fixture -> the expected VPH.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c33_own_vph.py -q
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from own_vph import compute_own_vph  # noqa: E402


def test_unpublished_video_returns_none_not_zero():
    """A video with no publish timestamp yet has no honest velocity answer —
    None, never a misleading 0.0."""
    assert compute_own_vph(0, None) is None
    assert compute_own_vph(12345, None) is None


def test_zero_hours_guard_returns_none():
    """Published this same instant (or a future/clock-skew timestamp) ->
    hours_since <= 0 -> None, not a divide-by-(near)zero blowup or a
    misleading 0.0/huge number."""
    now = datetime.now(timezone.utc)
    assert compute_own_vph(500, now) is None
    future = now + timedelta(hours=1)
    assert compute_own_vph(500, future) is None


def test_known_fixture_computes_expected_vph_from_a_datetime():
    """1,200 views exactly 24 hours after publish -> 50.0 VPH, matching the
    checklist's own worked example ("50 VPH = 1,200 views in first 24
    hours")."""
    published = datetime.now(timezone.utc) - timedelta(hours=24)
    vph = compute_own_vph(1200, published)
    assert vph is not None
    assert abs(vph - 50.0) < 0.5  # small tolerance for the few ms test runtime adds


def test_known_fixture_computes_expected_vph_from_an_iso_string():
    """Same math, but published_at arrives as an ISO string — the shape
    channel_videos.published_at/videos.upload_date can take before asyncpg
    parses it, and what routes.niche._calculate_vph natively expects."""
    published_iso = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    vph = compute_own_vph(500, published_iso)
    assert vph is not None
    assert abs(vph - 50.0) < 1.0  # 500 views / 10 hours = 50/hr


def test_zero_views_is_zero_vph_not_none():
    """Zero views with a real publish date IS an honest answer (0.0), unlike
    the unpublished/zero-hours cases above which have NO honest answer."""
    published = datetime.now(timezone.utc) - timedelta(hours=48)
    assert compute_own_vph(0, published) == 0.0


def test_result_matches_the_shared_competitor_side_calculator_directly():
    """Cross-check against routes.niche._calculate_vph itself — proves this
    is a thin wrapper (reuse), not a parallel reimplementation that could
    quietly drift from the competitor-side math."""
    from routes.niche import _calculate_vph

    published = datetime.now(timezone.utc) - timedelta(hours=36)
    now = datetime.now(timezone.utc)
    expected_vph, hours = _calculate_vph(900, published.isoformat(), now)
    assert hours > 0

    got = compute_own_vph(900, published)
    assert got is not None
    assert abs(got - round(expected_vph, 2)) < 0.05
