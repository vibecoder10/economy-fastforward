"""Unit tests for clip_asset_claims.py — the in-process per-asset claim
guard chunk C1 (feat/per-card-parallel-clips) adds so several manual clip
runs can be in flight on the same video without ever animating (and
charging for) the same asset twice.

No DB, no asyncio needed — claim()/release() are plain synchronous
functions. Each test uses a UNIQUE (tenant, video) key so state from one
test can never leak into another via the module-level dict.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_clip_asset_claims.py -q
"""
import time

import clip_asset_claims as cac


def test_claim_wins_everything_when_nothing_is_held():
    won = cac.claim("t1", "v1", ["a", "b", "c"])
    assert set(won) == {"a", "b", "c"}
    cac.release("t1", "v1", won)


def test_second_claim_on_same_ids_wins_nothing():
    won1 = cac.claim("t2", "v2", ["a", "b"])
    assert set(won1) == {"a", "b"}
    won2 = cac.claim("t2", "v2", ["a", "b"])
    assert won2 == [], "an already-claimed id must never be claimed a second time"
    cac.release("t2", "v2", won1)


def test_disjoint_claim_wins_its_own_ids_even_while_another_is_held():
    won1 = cac.claim("t3", "v3", ["a"])
    assert won1 == ["a"]
    won2 = cac.claim("t3", "v3", ["b", "c"])
    assert set(won2) == {"b", "c"}, "a disjoint id set must win in full even while another claim is live"
    cac.release("t3", "v3", won1 + won2)


def test_overlapping_claim_wins_only_the_unclaimed_remainder():
    won1 = cac.claim("t4", "v4", ["a", "b"])
    assert set(won1) == {"a", "b"}
    # Second caller wants b + c: b is taken, c is free.
    won2 = cac.claim("t4", "v4", ["b", "c"])
    assert set(won2) == {"c"}, "the overlapping id (b) must be skipped, not claimed twice"
    cac.release("t4", "v4", won1 + won2)


def test_release_frees_ids_for_a_later_claim():
    won1 = cac.claim("t5", "v5", ["a"])
    cac.release("t5", "v5", won1)
    won2 = cac.claim("t5", "v5", ["a"])
    assert won2 == ["a"], "a released id must be claimable again"
    cac.release("t5", "v5", won2)


def test_release_is_idempotent_and_safe_for_ids_never_claimed():
    won = cac.claim("t6", "v6", ["a"])
    cac.release("t6", "v6", won)
    cac.release("t6", "v6", won)  # second release: must not raise
    cac.release("t6", "v6", ["never-claimed"])  # unclaimed id: must not raise


def test_claims_are_scoped_per_tenant_and_video():
    won_a = cac.claim("tenantA", "video-shared-id", ["x"])
    won_b = cac.claim("tenantB", "video-shared-id", ["x"])
    assert won_a == ["x"] and won_b == ["x"], (
        "the same asset id under two DIFFERENT tenants must not collide — "
        "the claim key is (tenant_id, video_id), not video_id alone"
    )
    cac.release("tenantA", "video-shared-id", won_a)
    cac.release("tenantB", "video-shared-id", won_b)


def test_stale_claim_is_swept_and_retaken():
    """The self-heal net: a claim older than STALE_SECONDS is treated as
    abandoned (crashed worker) and silently retaken — proves the feature
    without sleeping STALE_SECONDS by writing directly into the module's
    internal timestamp."""
    won1 = cac.claim("t7", "v7", ["a"])
    assert won1 == ["a"]
    # Backdate the claim past the staleness window.
    cac._claimed[("t7", "v7")]["a"] = time.time() - cac.STALE_SECONDS - 1
    won2 = cac.claim("t7", "v7", ["a"])
    assert won2 == ["a"], "a stale (>10min) claim must be swept and retaken, never wedge an asset forever"
    cac.release("t7", "v7", won2)


def test_claimed_ids_reflects_live_state():
    assert cac.claimed_ids("t8", "v8") == set()
    won = cac.claim("t8", "v8", ["a", "b"])
    assert cac.claimed_ids("t8", "v8") == {"a", "b"}
    cac.release("t8", "v8", ["a"])
    assert cac.claimed_ids("t8", "v8") == {"b"}
    cac.release("t8", "v8", ["b"])
    assert cac.claimed_ids("t8", "v8") == set()


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
