"""Unit tests for redraw_asset_claims.py — the in-process per-asset claim
guard chunk C1b (feat/per-card-parallel-clips, image-redraw fan-out) adds
so several manual redraw runs can be in flight on the same video without
ever redrawing (and charging for) the same picture twice. Mirrors
tests/functional/test_clip_asset_claims.py (C1's identical proof for clips)
line-for-line — the two modules' claim()/release()/claimed_ids() behavior
is deliberately identical.

No DB, no asyncio needed — claim()/release() are plain synchronous
functions. Each test uses a UNIQUE (tenant, video) key so state from one
test can never leak into another via the module-level dict.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_redraw_asset_claims.py -q
"""
import time

import redraw_asset_claims as rac


def test_claim_wins_everything_when_nothing_is_held():
    won = rac.claim("t1", "v1", ["a", "b", "c"])
    assert set(won) == {"a", "b", "c"}
    rac.release("t1", "v1", won)


def test_second_claim_on_same_ids_wins_nothing():
    won1 = rac.claim("t2", "v2", ["a", "b"])
    assert set(won1) == {"a", "b"}
    won2 = rac.claim("t2", "v2", ["a", "b"])
    assert won2 == [], "an already-claimed id must never be claimed a second time"
    rac.release("t2", "v2", won1)


def test_disjoint_claim_wins_its_own_ids_even_while_another_is_held():
    won1 = rac.claim("t3", "v3", ["a"])
    assert won1 == ["a"]
    won2 = rac.claim("t3", "v3", ["b", "c"])
    assert set(won2) == {"b", "c"}, "a disjoint id set must win in full even while another claim is live"
    rac.release("t3", "v3", won1 + won2)


def test_overlapping_claim_wins_only_the_unclaimed_remainder():
    won1 = rac.claim("t4", "v4", ["a", "b"])
    assert set(won1) == {"a", "b"}
    # Second caller wants b + c: b is taken, c is free.
    won2 = rac.claim("t4", "v4", ["b", "c"])
    assert set(won2) == {"c"}, "the overlapping id (b) must be skipped, not claimed twice"
    rac.release("t4", "v4", won1 + won2)


def test_release_frees_ids_for_a_later_claim():
    won1 = rac.claim("t5", "v5", ["a"])
    rac.release("t5", "v5", won1)
    won2 = rac.claim("t5", "v5", ["a"])
    assert won2 == ["a"], "a released id must be claimable again"
    rac.release("t5", "v5", won2)


def test_release_is_idempotent_and_safe_for_ids_never_claimed():
    won = rac.claim("t6", "v6", ["a"])
    rac.release("t6", "v6", won)
    rac.release("t6", "v6", won)  # second release: must not raise
    rac.release("t6", "v6", ["never-claimed"])  # unclaimed id: must not raise


def test_claims_are_scoped_per_tenant_and_video():
    won_a = rac.claim("tenantA", "video-shared-id", ["x"])
    won_b = rac.claim("tenantB", "video-shared-id", ["x"])
    assert won_a == ["x"] and won_b == ["x"], (
        "the same asset id under two DIFFERENT tenants must not collide — "
        "the claim key is (tenant_id, video_id), not video_id alone"
    )
    rac.release("tenantA", "video-shared-id", won_a)
    rac.release("tenantB", "video-shared-id", won_b)


def test_stale_claim_is_swept_and_retaken():
    """The self-heal net: a claim older than STALE_SECONDS is treated as
    abandoned (crashed worker) and silently retaken — proves the feature
    without sleeping STALE_SECONDS by writing directly into the module's
    internal timestamp."""
    won1 = rac.claim("t7", "v7", ["a"])
    assert won1 == ["a"]
    rac._claimed[("t7", "v7")]["a"] = time.time() - rac.STALE_SECONDS - 1
    won2 = rac.claim("t7", "v7", ["a"])
    assert won2 == ["a"], "a stale (>10min) claim must be swept and retaken, never wedge an asset forever"
    rac.release("t7", "v7", won2)


def test_claimed_ids_reflects_live_state():
    assert rac.claimed_ids("t8", "v8") == set()
    won = rac.claim("t8", "v8", ["a", "b"])
    assert rac.claimed_ids("t8", "v8") == {"a", "b"}
    rac.release("t8", "v8", ["a"])
    assert rac.claimed_ids("t8", "v8") == {"b"}
    rac.release("t8", "v8", ["b"])
    assert rac.claimed_ids("t8", "v8") == set()


def test_redraw_claims_are_independent_of_clip_claims():
    """The whole reason redraw_asset_claims is a SEPARATE module/dict from
    clip_asset_claims: the same asset id claimed for a CLIP must not be
    seen as claimed from a REDRAW's point of view, and vice versa."""
    import clip_asset_claims as cac

    won_clip = cac.claim("t9", "v9", ["shared-asset"])
    assert won_clip == ["shared-asset"]
    won_redraw = rac.claim("t9", "v9", ["shared-asset"])
    assert won_redraw == ["shared-asset"], (
        "a redraw claim on an asset already claimed for a clip must still win — "
        "the two claim types are independent namespaces"
    )
    cac.release("t9", "v9", won_clip)
    rac.release("t9", "v9", won_redraw)


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
