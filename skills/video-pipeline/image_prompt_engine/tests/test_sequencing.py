"""
Tests for the sequencing engine.

Verifies that all global sequencing rules from the PRD are enforced across
a full video's worth of style assignments.
"""

import sys
import os

import pytest

# Ensure the package is importable when running tests from this directory.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from image_prompt_engine.sequencer import assign_styles
from image_prompt_engine.style_config import DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assignments(seed: int = 42, total: int = 136) -> list[dict]:
    """Generate a deterministic full-video assignment sequence."""
    return assign_styles(total, seed=seed)


def _get_act(entry: dict) -> str:
    return entry["act"]


def _consecutive_runs(assignments: list[dict]) -> list[tuple[str, int]]:
    """Return a list of (style, run_length) for consecutive same-style runs."""
    if not assignments:
        return []
    runs = []
    current_style = assignments[0]["style"]
    count = 1
    for entry in assignments[1:]:
        if entry["style"] == current_style:
            count += 1
        else:
            runs.append((current_style, count))
            current_style = entry["style"]
            count = 1
    runs.append((current_style, count))
    return runs


# ---------------------------------------------------------------------------
# Rule 1: No more than 4 consecutive same style
# ---------------------------------------------------------------------------

class TestMaxConsecutive:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_no_more_than_4_consecutive(self, seed):
        """No style appears more than 4 times in a row."""
        assignments = _make_assignments(seed=seed)
        max_allowed = DEFAULT_CONFIG["max_consecutive_same_style"]
        for style, run_len in _consecutive_runs(assignments):
            assert run_len <= max_allowed, (
                f"Style '{style}' has {run_len} consecutive images "
                f"(max {max_allowed}), seed={seed}"
            )


# ---------------------------------------------------------------------------
# Rule 2: No Echo in restricted acts
# ---------------------------------------------------------------------------

class TestEchoRestriction:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_no_echo_in_restricted_acts(self, seed):
        """Echo never appears in Acts 1, 2, or 6."""
        assignments = _make_assignments(seed=seed)
        restricted = {"act1", "act2", "act6"}
        for entry in assignments:
            if entry["act"] in restricted:
                assert entry["style"] != "echo", (
                    f"Echo found in {entry['act']} at index {entry['index']}, seed={seed}"
                )


# ---------------------------------------------------------------------------
# Rule 3: Echo clusters minimum 2
# ---------------------------------------------------------------------------

class TestEchoClusters:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_echo_clusters_minimum_2(self, seed):
        """Echo images never appear as isolated singles."""
        assignments = _make_assignments(seed=seed)
        runs = _consecutive_runs(assignments)
        for style, run_len in runs:
            if style == "echo":
                assert run_len >= DEFAULT_CONFIG["echo_cluster_min"], (
                    f"Isolated echo (cluster size {run_len}), seed={seed}"
                )

    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_echo_clusters_maximum_3(self, seed):
        """Echo clusters are at most 3 images long."""
        assignments = _make_assignments(seed=seed)
        runs = _consecutive_runs(assignments)
        for style, run_len in runs:
            if style == "echo":
                assert run_len <= DEFAULT_CONFIG["echo_cluster_max"], (
                    f"Echo cluster too long ({run_len}), seed={seed}"
                )


# ---------------------------------------------------------------------------
# Rule 4: Echo cluster followed by Dossier
# ---------------------------------------------------------------------------

class TestEchoFollowedByDossier:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_echo_followed_by_dossier(self, seed):
        """Every Echo cluster is followed by a Dossier image."""
        assignments = _make_assignments(seed=seed)
        runs = _consecutive_runs(assignments)
        for i, (style, _run_len) in enumerate(runs):
            if style == "echo" and i + 1 < len(runs):
                next_style = runs[i + 1][0]
                assert next_style == "dossier", (
                    f"Echo cluster followed by '{next_style}' instead of 'dossier', seed={seed}"
                )


# ---------------------------------------------------------------------------
# Rule 5: Schema rarely clusters
# ---------------------------------------------------------------------------

class TestSchemaCluster:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_schema_rarely_clusters(self, seed):
        """Schema appears max 1 consecutive outside Act 5, max 2 in Act 5."""
        assignments = _make_assignments(seed=seed)
        for i, entry in enumerate(assignments):
            if entry["style"] != "schema":
                continue
            # Count consecutive schema starting from this position.
            run = 1
            j = i + 1
            while j < len(assignments) and assignments[j]["style"] == "schema":
                run += 1
                j += 1
            # Determine the act for this run (use the first image's act).
            act = entry["act"]
            max_allowed = (
                DEFAULT_CONFIG["schema_cluster_max_act5"]
                if act == "act5"
                else DEFAULT_CONFIG["schema_cluster_max_default"]
            )
            assert run <= max_allowed, (
                f"Schema cluster of {run} in {act} at index {i} "
                f"(max {max_allowed}), seed={seed}"
            )


# ---------------------------------------------------------------------------
# Rule 6: First and last images are Dossier
# ---------------------------------------------------------------------------

class TestFirstAndLast:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_first_and_last_are_dossier(self, seed):
        """First and last images are always Dossier style."""
        assignments = _make_assignments(seed=seed)
        assert assignments[0]["style"] == "dossier", (
            f"First image is '{assignments[0]['style']}', expected 'dossier', seed={seed}"
        )
        assert assignments[-1]["style"] == "dossier", (
            f"Last image is '{assignments[-1]['style']}', expected 'dossier', seed={seed}"
        )


# ---------------------------------------------------------------------------
# Distribution within tolerance
# ---------------------------------------------------------------------------

class TestDistribution:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_distribution_within_tolerance(self, seed):
        """Overall distribution is within 10% of targets (60/22/18)."""
        assignments = _make_assignments(seed=seed)
        total = len(assignments)
        counts = {"dossier": 0, "schema": 0, "echo": 0}
        for entry in assignments:
            counts[entry["style"]] += 1

        targets = DEFAULT_CONFIG["target_distribution"]
        tolerance = 0.10  # 10 percentage points

        for style, target in targets.items():
            actual = counts[style] / total
            assert abs(actual - target) <= tolerance, (
                f"Style '{style}': actual {actual:.2%} vs target {target:.0%} "
                f"(tolerance {tolerance:.0%}), seed={seed}"
            )


# ---------------------------------------------------------------------------
# Composition variety
# ---------------------------------------------------------------------------

class TestCompositionVariety:
    def test_compositions_cycle_within_dossier(self):
        """Consecutive Dossier images should not all use the same composition."""
        assignments = _make_assignments(seed=42)
        runs = _consecutive_runs(assignments)
        idx = 0
        for style, run_len in runs:
            if style == "dossier" and run_len >= 3:
                comps = [assignments[idx + k]["composition"] for k in range(run_len)]
                assert len(set(comps)) > 1, (
                    f"Dossier run of {run_len} all use composition '{comps[0]}'"
                )
            idx += run_len


# ---------------------------------------------------------------------------
# Ken Burns directions
# ---------------------------------------------------------------------------

class TestKenBurns:
    def test_all_assignments_have_ken_burns(self):
        """Every assignment includes a ken_burns direction."""
        assignments = _make_assignments(seed=42)
        for entry in assignments:
            assert "ken_burns" in entry
            assert entry["ken_burns"] is not None

    def test_pan_directions_alternate(self):
        """Pan-based Ken Burns directions alternate for same composition."""
        assignments = _make_assignments(seed=42)
        # Find medium-composition entries (default pan direction).
        mediums = [a for a in assignments if a["composition"] == "medium"]
        if len(mediums) >= 2:
            # Should alternate between pan_right and pan_left.
            directions = [m["ken_burns"] for m in mediums]
            # At least some alternation should occur.
            assert len(set(directions)) > 1, "Medium compositions never alternate pan direction"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_small_video(self):
        """A video with only 5 images doesn't crash."""
        assignments = assign_styles(5, seed=42)
        assert len(assignments) == 5
        assert assignments[0]["style"] == "dossier"
        assert assignments[-1]["style"] == "dossier"

    def test_single_image(self):
        """A video with 1 image returns Dossier."""
        assignments = assign_styles(1, seed=42)
        assert len(assignments) == 1
        assert assignments[0]["style"] == "dossier"

    def test_large_video(self):
        """A 300-image video runs without error and obeys rules."""
        assignments = assign_styles(300, seed=42)
        assert len(assignments) == 300
        assert assignments[0]["style"] == "dossier"
        assert assignments[-1]["style"] == "dossier"
        # Check no more than 4 consecutive.
        for _style, run_len in _consecutive_runs(assignments):
            assert run_len <= DEFAULT_CONFIG["max_consecutive_same_style"]

    def test_reproducible_with_seed(self):
        """Same seed produces identical output."""
        a = assign_styles(136, seed=12345)
        b = assign_styles(136, seed=12345)
        assert a == b

    def test_different_seeds_differ(self):
        """Different seeds produce different sequences (with high probability)."""
        a = assign_styles(136, seed=1)
        b = assign_styles(136, seed=2)
        styles_a = [x["style"] for x in a]
        styles_b = [x["style"] for x in b]
        assert styles_a != styles_b
