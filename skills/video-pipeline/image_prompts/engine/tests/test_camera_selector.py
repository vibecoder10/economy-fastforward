"""Tests for camera_selector.py's purpose-classification input (C1 classifier
diet) and the earn-the-move gate (resolve_purpose).

Root cause (C1, re-run-proven): classify_camera_purpose() used to keyword-match
against the FULL composed shot description. coverage.py's run_coverage() appends
scene-constant SET-DRESSING/AXIS/STAGING boilerplate to every shot's description
BEFORE plan_camera_moves() runs, and that boilerplate routinely contains "behind"
(e.g. "...cream stove behind Vanessa...") — a REVEAL keyword — so every shot in a
scene classified REVEAL regardless of how calm the actual narrative beat was.

The fix: ShotContext gained a narrow ``narrative_text`` field (moment summary +
spoken line only, never the composed description), and resolve_purpose() feeds
THAT to classify_camera_purpose() instead of ctx.sentence_text.

Run: pytest skills/video-pipeline/image_prompts/engine/tests/test_camera_selector.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_IMAGE_PROMPTS = os.path.dirname(os.path.dirname(_HERE))  # .../image_prompts
_PIPELINE_ROOT = os.path.dirname(_IMAGE_PROMPTS)           # .../video-pipeline
# camera_selector.resolve_purpose() does a bare `import animation_prompt_engine`
# (matches the production import path — see tests/test_coverage.py's comment on
# the same requirement for plan_camera_moves). Needs image_prompts/ itself on
# sys.path, not just the pipeline root pytest auto-inserts for the dotted
# import below.
sys.path.insert(0, _IMAGE_PROMPTS)
sys.path.insert(0, _PIPELINE_ROOT)

from image_prompts.engine.camera_selector import (  # noqa: E402
    ShotContext, resolve_purpose, select_camera_move,
)
from image_prompts.animation_prompt_engine import (  # noqa: E402
    classify_camera_purpose, CAMERA_PURPOSE_REVEAL, CAMERA_PURPOSE_STATIC,
)


# A calm dialogue narrative beat — no reveal/scale/isolation language.
_CALM_NARRATIVE = "Vanessa and Marcus talk quietly over coffee at the kitchen table."

# The SET-DRESSING/AXIS/STAGING boilerplate coverage.py's run_coverage() appends
# to every shot's description (coverage.py ~955-994) BEFORE plan_camera_moves()
# runs. Lifted close to the real production string that triggered the bug:
# "cream stove behind Vanessa" false-triggers the REVEAL keyword list ("behind").
_BOILERPLATE_TAIL = (
    "Set dressing and character blocking, identical in every shot of this scene: "
    "a cream stove behind Vanessa, a wooden table between them, warm afternoon light."
)
_COMPOSED_DESCRIPTION = f"{_CALM_NARRATIVE} {_BOILERPLATE_TAIL}"


class TestClassifierDiet:

    def test_old_behavior_boilerplate_alone_would_classify_reveal(self):
        """Control: proves the boilerplate genuinely contains a REVEAL trigger.
        classify_camera_purpose() on the composed (narrative + boilerplate) text
        — the OLD input shape — misclassifies a calm scene as REVEAL."""
        assert classify_camera_purpose(_COMPOSED_DESCRIPTION) == CAMERA_PURPOSE_REVEAL

    def test_calm_dialogue_classifies_static_despite_boilerplate_in_description(self):
        """The fix: resolve_purpose() reads ctx.narrative_text (the narrow beat),
        not ctx.sentence_text (the boilerplate-laden composed description) — a
        calm dialogue beat classifies STATIC even though sentence_text still
        carries the "behind" boilerplate verbatim."""
        ctx = ShotContext(
            sentence_text=_COMPOSED_DESCRIPTION,   # composed, WITH boilerplate
            narrative_text=_CALM_NARRATIVE + ".",  # narrow beat only
            composition="medium",
            intensity="low",
            is_scene_open=False,
            is_scene_final=False,
        )
        assert resolve_purpose(ctx) == "STATIC"
        sel = select_camera_move(ctx)
        assert sel.move is None
        assert sel.purpose == "STATIC"

    def test_actual_reveal_beat_still_classifies_reveal(self):
        """A genuine reveal beat (the reveal language lives in the NARRATIVE, not
        just the boilerplate) must still classify REVEAL — the diet narrows the
        input, it doesn't blind the classifier to real reveal beats."""
        ctx = ShotContext(
            sentence_text=(
                "Marcus pulls back the curtain to reveal the hidden ledger. "
                + _BOILERPLATE_TAIL
            ),
            narrative_text="Marcus pulls back the curtain to reveal the hidden ledger.",
            composition="medium",
            intensity="medium",
        )
        assert resolve_purpose(ctx) == CAMERA_PURPOSE_REVEAL

    def test_narrative_text_blank_falls_back_to_sentence_text(self):
        """Backward compatibility: a caller/test that never sets narrative_text
        (the dataclass default "") keeps the pre-C1 behavior — classify on
        sentence_text, so nothing outside plan_camera_moves silently changes."""
        ctx = ShotContext(sentence_text=_COMPOSED_DESCRIPTION)
        assert resolve_purpose(ctx) == CAMERA_PURPOSE_REVEAL


if __name__ == "__main__":
    t = TestClassifierDiet()
    t.test_old_behavior_boilerplate_alone_would_classify_reveal()
    t.test_calm_dialogue_classifies_static_despite_boilerplate_in_description()
    t.test_actual_reveal_beat_still_classifies_reveal()
    t.test_narrative_text_blank_falls_back_to_sentence_text()
    print("ok — camera_selector classifier-diet self-checks passed")
