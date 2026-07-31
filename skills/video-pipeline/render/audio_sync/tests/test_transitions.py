"""Tests for audio_sync.transition_engine — transition type selection."""

import pytest

from render.audio_sync.transition_engine import (
    determine_transition,
    assign_transitions,
    TRANSITION_KIND_TREATMENTS,
)
from render.audio_sync.config import (
    CROSSFADE_DURATION,
    STYLE_CHANGE_FADE,
    ACT_TRANSITION_BLACK,
    HARD_CUT_DURATION,
    LOCATION_CUT_FADE,
    MONTAGE_FADE,
    MEMORY_DISSOLVE,
)


class TestDetermineTransition:
    def test_same_style_same_act_crossfade(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1}
        t = determine_transition(cur, nxt)
        assert t["type"] == "crossfade"
        assert t["duration"] == CROSSFADE_DURATION

    def test_style_change_longer_crossfade(self):
        cur = {"style": "dossier", "act": 2}
        nxt = {"style": "echo", "act": 2}
        t = determine_transition(cur, nxt)
        assert t["type"] == "crossfade"
        assert t["duration"] == STYLE_CHANGE_FADE

    def test_act_change_dip_to_black(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 2}
        t = determine_transition(cur, nxt)
        assert t["type"] == "dip_to_black"
        assert t["duration"] == ACT_TRANSITION_BLACK

    def test_last_scene_fade_to_black(self):
        cur = {"style": "dossier", "act": 6}
        t = determine_transition(cur, None)
        assert t["type"] == "fade_to_black"

    def test_visual_style_field_supported(self):
        """The pipeline may use 'visual_style' instead of 'style'."""
        cur = {"visual_style": "schema", "parent_act": 3}
        nxt = {"visual_style": "echo", "parent_act": 3}
        t = determine_transition(cur, nxt)
        assert t["type"] == "crossfade"
        assert t["duration"] == STYLE_CHANGE_FADE


class TestTransitionKindTreatments:
    """D12-2: per-shot transition_kind (migration 148, assets.transition_kind)
    drives a distinct render treatment, but only where today's act/style
    rules would otherwise fall through to the generic quick crossfade."""

    def test_continuous_is_hard_cut(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "continuous"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "cut", "duration": HARD_CUT_DURATION}

    def test_time_cut_is_hard_cut(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "time_cut"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "cut", "duration": HARD_CUT_DURATION}

    def test_location_cut_is_quick_crossfade(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "location_cut"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "crossfade", "duration": LOCATION_CUT_FADE}

    def test_montage_is_short_crossfade(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "montage"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "crossfade", "duration": MONTAGE_FADE}
        assert MONTAGE_FADE < LOCATION_CUT_FADE  # "short" is shorter than "quick"

    def test_memory_is_long_dissolve(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "memory"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "dissolve", "duration": MEMORY_DISSOLVE}
        # "long" — the longest of the five kind treatments (ties allowed
        # against unrelated constants like STYLE_CHANGE_FADE, just not
        # shorter than any of them).
        assert MEMORY_DISSOLVE > LOCATION_CUT_FADE
        assert MEMORY_DISSOLVE > MONTAGE_FADE
        assert MEMORY_DISSOLVE > HARD_CUT_DURATION

    def test_kind_is_case_insensitive_and_whitespace_tolerant(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "  MEMORY  "}
        t = determine_transition(cur, nxt)
        assert t == {"type": "dissolve", "duration": MEMORY_DISSOLVE}

    def test_opening_kind_falls_through_to_generic_crossfade(self):
        """'opening' has no dedicated treatment — assign_transitions never
        routes the first scene's transition_in through determine_transition
        at all (it's hardcoded to fade_from_black), so nothing needs to
        special-case it here; a stray "opening" reaching this function
        anyway must fall through unchanged, same as no kind."""
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "opening"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "crossfade", "duration": CROSSFADE_DURATION}

    def test_unrecognized_kind_falls_through_to_generic_crossfade(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "some_future_kind"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "crossfade", "duration": CROSSFADE_DURATION}

    def test_absent_kind_is_byte_identical_to_pre_d12_2_behavior(self):
        """The decisive backward-compat test: no transition_kind key at all
        (every asset row before migration 148, and every non-flagship render
        path) must produce EXACTLY what determine_transition returned before
        this chunk existed."""
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1}
        assert "transition_kind" not in nxt
        t = determine_transition(cur, nxt)
        assert t == {"type": "crossfade", "duration": CROSSFADE_DURATION}

    def test_null_kind_is_byte_identical_to_absent_kind(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": None}
        t = determine_transition(cur, nxt)
        assert t == {"type": "crossfade", "duration": CROSSFADE_DURATION}

    def test_act_change_wins_over_kind(self):
        """Act-boundary dip-to-black is proven editorial intent — it wins
        even when the incoming shot also carries a transition_kind that
        would otherwise pick a different treatment."""
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 2, "transition_kind": "memory"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "dip_to_black", "duration": ACT_TRANSITION_BLACK}

    def test_style_change_wins_over_kind(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "echo", "act": 1, "transition_kind": "continuous"}
        t = determine_transition(cur, nxt)
        assert t == {"type": "crossfade", "duration": STYLE_CHANGE_FADE}

    def test_kind_map_returns_a_copy_not_the_shared_dict(self):
        """A caller mutating the returned dict must never corrupt the shared
        TRANSITION_KIND_TREATMENTS map for the next boundary."""
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1, "transition_kind": "memory"}
        t = determine_transition(cur, nxt)
        t["duration"] = 999.0
        assert TRANSITION_KIND_TREATMENTS["memory"]["duration"] == MEMORY_DISSOLVE

    def test_kinds_get_their_mapped_treatment_and_only_share_by_design(self):
        """The build's core claim: recognized kinds get DISTINCT render
        treatments — except continuous/time_cut, which are intentionally the
        same "hard cut" treatment (the spec draws no render-level distinction
        between them). Every other pair of kinds must differ."""
        treatments: dict[str, tuple] = {}
        for kind, expected in TRANSITION_KIND_TREATMENTS.items():
            cur = {"style": "dossier", "act": 1}
            nxt = {"style": "dossier", "act": 1, "transition_kind": kind}
            t = determine_transition(cur, nxt)
            assert t == expected
            treatments[kind] = (t["type"], t["duration"])

        assert treatments["continuous"] == treatments["time_cut"]
        non_cut_shapes = [
            shape for kind, shape in treatments.items()
            if kind not in ("continuous", "time_cut")
        ]
        assert len(non_cut_shapes) == len(set(non_cut_shapes)), (
            "two non-hard-cut transition_kind values produced the identical "
            "treatment"
        )
        assert treatments["location_cut"] not in (
            treatments["continuous"], treatments["montage"], treatments["memory"],
        )


class TestAssignTransitions:
    def test_first_scene_fades_from_black(self):
        scenes = [
            {"scene_number": 1, "style": "dossier", "act": 1},
            {"scene_number": 2, "style": "dossier", "act": 1},
        ]
        result = assign_transitions(scenes)
        assert result[0]["transition_in"]["type"] == "fade_from_black"

    def test_all_scenes_get_both_transitions(self):
        scenes = [
            {"scene_number": 1, "style": "dossier", "act": 1},
            {"scene_number": 2, "style": "dossier", "act": 1},
            {"scene_number": 3, "style": "echo", "act": 2},
        ]
        result = assign_transitions(scenes)
        for s in result:
            assert "transition_in" in s
            assert "transition_out" in s

    def test_transition_in_mirrors_previous_out(self):
        scenes = [
            {"scene_number": 1, "style": "dossier", "act": 1},
            {"scene_number": 2, "style": "dossier", "act": 2},
        ]
        result = assign_transitions(scenes)
        assert result[1]["transition_in"]["type"] == result[0]["transition_out"]["type"]

    def test_kind_on_incoming_scene_governs_the_boundary_out_of_the_previous_one(self):
        """The kind lives on the shot being cut TO (mirrors ShotDraft's
        transition_from_previous), so a kind on scene 2 governs scene 1's
        transition_out (and, mirrored, scene 2's transition_in) — not
        scene 2's own transition_out."""
        scenes = [
            {"scene_number": 1, "style": "dossier", "act": 1},
            {"scene_number": 2, "style": "dossier", "act": 1,
             "transition_kind": "memory"},
            {"scene_number": 3, "style": "dossier", "act": 1},
        ]
        result = assign_transitions(scenes)
        assert result[0]["transition_out"] == {"type": "dissolve", "duration": MEMORY_DISSOLVE}
        assert result[1]["transition_in"] == {"type": "dissolve", "duration": MEMORY_DISSOLVE}
        # scene 2 -> scene 3 has no kind on scene 3, so it's the generic default
        assert result[1]["transition_out"] == {"type": "crossfade", "duration": CROSSFADE_DURATION}

    def test_full_scene_list_byte_identical_with_and_without_kind_key_present_but_null(self):
        """Backward-compat at the assign_transitions level, not just
        determine_transition in isolation: a scene list where every scene
        explicitly carries transition_kind=None (as a real DB row with a
        NULL column would round-trip) must produce the exact same plan as
        the same list with the key omitted entirely."""
        without_key = [
            {"scene_number": 1, "style": "dossier", "act": 1},
            {"scene_number": 2, "style": "dossier", "act": 1},
            {"scene_number": 3, "style": "echo", "act": 2},
            {"scene_number": 4, "style": "echo", "act": 2},
        ]
        with_null_key = [dict(s, transition_kind=None) for s in without_key]

        result_without = assign_transitions([dict(s) for s in without_key])
        result_with = assign_transitions(with_null_key)

        for a, b in zip(result_without, result_with):
            assert a["transition_in"] == b["transition_in"]
            assert a["transition_out"] == b["transition_out"]
