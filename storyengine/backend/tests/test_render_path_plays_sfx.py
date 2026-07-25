"""Unit tests for status_map.render_path_plays_sfx / render_path_sfx_block_reason.

Pure functions, no DB — status_map.py has no external dependencies, so these
import and run standalone (no monkeypatching needed).

Covers all five of run_render's dispatch branches (pipeline_executor.py's
run_render, def ~line 16190), in the SAME order, so a change to one side
without the other is caught here:

  1. custom_film_plan_id set                          -> SFX dropped
  2. render_mode == 'static_docu'                      -> SFX dropped
  3. dialogue_audio == 'grok_native'                    -> SFX dropped
  4. dialogue_mode == 'character_dialogue'              -> SFX dropped
  5. fallback (legacy Remotion bot)                     -> SFX plays

Also pins the two `or`-defaulting quirks run_render's dispatch relies on:
  - `(video.get("dialogue_audio") or "voice_over")` — a NULL/missing
    dialogue_audio must NOT be treated as grok_native.
  - `(video.get("dialogue_mode") or "")` — a NULL/missing dialogue_mode must
    NOT be treated as character_dialogue.
"""
import status_map as sm


# --- Branch 1: Custom Film -------------------------------------------------

def test_custom_film_plan_id_blocks_sfx():
    video = {"custom_film_plan_id": "11111111-1111-1111-1111-111111111111"}
    assert sm.render_path_plays_sfx(video) is False
    assert "Custom Film" in sm.render_path_sfx_block_reason(video)


def test_custom_film_plan_id_none_does_not_block():
    video = {"custom_film_plan_id": None}
    assert sm.render_path_plays_sfx(video) is True


# --- Branch 2: static_docu ---------------------------------------------------

def test_static_docu_render_mode_blocks_sfx():
    video = {"render_mode": "static_docu"}
    assert sm.render_path_plays_sfx(video) is False
    assert "static-documentary" in sm.render_path_sfx_block_reason(video)


def test_render_mode_none_does_not_block():
    video = {"render_mode": None}
    assert sm.render_path_plays_sfx(video) is True


def test_render_mode_other_value_does_not_block():
    # Only the exact string 'static_docu' blocks — mirrors run_render's
    # `(video.get("render_mode") or "") == "static_docu"` check exactly.
    video = {"render_mode": "coverage"}
    assert sm.render_path_plays_sfx(video) is True


# --- Branch 3: grok_native dialogue_audio -----------------------------------

def test_dialogue_audio_grok_native_blocks_sfx():
    video = {"dialogue_audio": "grok_native"}
    assert sm.render_path_plays_sfx(video) is False
    assert "Grok-native" in sm.render_path_sfx_block_reason(video)


def test_dialogue_audio_none_defaults_to_voice_over_and_does_not_block():
    # run_render's dispatch reads `(video.get("dialogue_audio") or
    # "voice_over")` — a NULL/missing dialogue_audio must default to
    # 'voice_over', NOT be (mis)treated as 'grok_native'.
    video = {"dialogue_audio": None}
    assert sm.render_path_plays_sfx(video) is True


def test_dialogue_audio_missing_key_does_not_block():
    video = {}
    assert sm.render_path_plays_sfx(video) is True


def test_dialogue_audio_voice_over_does_not_block():
    video = {"dialogue_audio": "voice_over"}
    assert sm.render_path_plays_sfx(video) is True


# --- Branch 4: character_dialogue dialogue_mode -----------------------------

def test_dialogue_mode_character_dialogue_blocks_sfx():
    video = {"dialogue_mode": "character_dialogue"}
    assert sm.render_path_plays_sfx(video) is False
    assert "character-dialogue" in sm.render_path_sfx_block_reason(video)


def test_dialogue_mode_none_defaults_to_falsy_and_does_not_block():
    # run_render's dispatch reads `(video.get("dialogue_mode") or "") ==
    # "character_dialogue"` — a NULL/missing dialogue_mode must NOT be
    # (mis)treated as 'character_dialogue'.
    video = {"dialogue_mode": None}
    assert sm.render_path_plays_sfx(video) is True


def test_dialogue_mode_narration_only_does_not_block():
    video = {"dialogue_mode": "narration_only"}
    assert sm.render_path_plays_sfx(video) is True


# --- Branch 5: legacy fallback (the ONE path that plays SFX) --------------

def test_legacy_fallback_with_everything_unset_plays_sfx():
    """The historical default: every field NULL/missing (44/71 prod videos as
    of 2026-07-24) must fall through to the legacy Remotion bot and keep
    sound effects exactly as before this guard existed."""
    video = {
        "custom_film_plan_id": None,
        "render_mode": None,
        "dialogue_audio": None,
        "dialogue_mode": None,
    }
    assert sm.render_path_plays_sfx(video) is True
    assert sm.render_path_sfx_block_reason(video) is None


def test_empty_dict_plays_sfx():
    assert sm.render_path_plays_sfx({}) is True
    assert sm.render_path_sfx_block_reason({}) is None


def test_none_video_plays_sfx():
    # Defensive — _get_video can return None upstream; the helper must not
    # blow up on a missing row.
    assert sm.render_path_plays_sfx(None) is True
    assert sm.render_path_sfx_block_reason(None) is None


# --- Branch precedence (mirrors run_render's dispatch ORDER) ---------------

def test_custom_film_takes_precedence_over_every_other_branch():
    video = {
        "custom_film_plan_id": "11111111-1111-1111-1111-111111111111",
        "render_mode": "coverage",
        "dialogue_audio": "voice_over",
        "dialogue_mode": "narration_only",
    }
    assert sm.render_path_plays_sfx(video) is False
    assert "Custom Film" in sm.render_path_sfx_block_reason(video)


def test_static_docu_checked_before_dialogue_audio_and_mode():
    video = {
        "render_mode": "static_docu",
        "dialogue_audio": "voice_over",
        "dialogue_mode": "narration_only",
    }
    assert sm.render_path_plays_sfx(video) is False
    assert "static-documentary" in sm.render_path_sfx_block_reason(video)


def test_grok_native_checked_before_dialogue_mode():
    video = {"dialogue_audio": "grok_native", "dialogue_mode": "narration_only"}
    assert sm.render_path_plays_sfx(video) is False
    assert "Grok-native" in sm.render_path_sfx_block_reason(video)


# --- render_path_plays_sfx and render_path_sfx_block_reason never disagree -

def test_plays_sfx_and_block_reason_agree_across_all_combinations():
    """The two public functions are thin wrappers over the SAME internal
    branch logic — they can never disagree. Sweep the branch-relevant field
    combinations and assert plays_sfx == (block_reason is None)."""
    import itertools

    custom_film_values = [None, "some-plan-id"]
    render_mode_values = [None, "static_docu", "coverage"]
    dialogue_audio_values = [None, "voice_over", "grok_native"]
    dialogue_mode_values = [None, "narration_only", "character_dialogue"]

    for cf, rm, da, dm in itertools.product(
        custom_film_values, render_mode_values, dialogue_audio_values, dialogue_mode_values
    ):
        video = {
            "custom_film_plan_id": cf,
            "render_mode": rm,
            "dialogue_audio": da,
            "dialogue_mode": dm,
        }
        plays = sm.render_path_plays_sfx(video)
        reason = sm.render_path_sfx_block_reason(video)
        assert plays == (reason is None), (video, plays, reason)


# =============================================================================
# stages_excluding_blocked_sound — the shared list-filter (coordinator review
# gap 3): the mechanical "drop 'sound' from a stage list" step lives in ONE
# place, shared by pipeline_executor.PipelineExecutor._enabled_stages and
# production_guide.get_production_guide, so it can't drift between them.
# =============================================================================

def test_stages_excluding_blocked_sound_returns_unchanged_when_sfx_plays():
    video = {}  # legacy default — plays fine
    assert sm.stages_excluding_blocked_sound(None, video) is None
    plan = ["script", "sound", "render"]
    assert sm.stages_excluding_blocked_sound(plan, video) == plan


def test_stages_excluding_blocked_sound_builds_full_list_minus_sound_when_none():
    video = {"dialogue_mode": "character_dialogue"}
    result = sm.stages_excluding_blocked_sound(None, video)
    assert result is not None
    assert "sound" not in result
    assert set(result) == set(sm.STAGE_ORDER) - {"sound"}


def test_stages_excluding_blocked_sound_drops_sound_from_explicit_list():
    video = {"dialogue_mode": "character_dialogue"}
    plan = ["script", "voice", "images", "sound", "video", "render"]
    result = sm.stages_excluding_blocked_sound(plan, video)
    assert "sound" not in result
    assert set(result) == {"script", "voice", "images", "video", "render"}


def test_stages_excluding_blocked_sound_no_op_when_sound_already_absent():
    video = {"dialogue_mode": "character_dialogue"}
    plan = ["script", "voice", "render"]  # sound never was in this plan
    result = sm.stages_excluding_blocked_sound(plan, video)
    assert result == plan
