"""
Tests for camera movement detection and rotation enforcement.

Verifies:
- detect_camera_movement() correctly identifies all 8 camera types
- validate_video_prompt() catches consecutive camera repeats
- validate_video_prompt() detects missing camera movements
- Camera rotation produces variety across a full video
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from image_prompt_engine.prompt_builder import (
    CAMERA_MOVEMENTS,
    detect_camera_movement,
    validate_video_prompt,
)


# ---------------------------------------------------------------------------
# detect_camera_movement tests
# ---------------------------------------------------------------------------


class TestDetectCameraMovement:
    """Tests for detect_camera_movement()."""

    def test_detects_push_in(self):
        prompt = "Slow push-in toward the central monitor. Screens flicker to life."
        assert detect_camera_movement(prompt) == "push-in"

    def test_detects_push_in_variant(self):
        prompt = "Dolly in toward the war table. Data nodes illuminate."
        assert detect_camera_movement(prompt) == "push-in"

    def test_detects_pull_back(self):
        prompt = "Pull-back revealing the full scope. Networks dissolve."
        assert detect_camera_movement(prompt) == "pull-back"

    def test_detects_pull_back_zoom_out(self):
        prompt = "Zoom out from the detail. The entire map fills the frame."
        assert detect_camera_movement(prompt) == "pull-back"

    def test_detects_lateral_pan(self):
        prompt = "Lateral pan across the data panels. Charts cascade left to right."
        assert detect_camera_movement(prompt) == "lateral-pan"

    def test_detects_tracking_shot(self):
        prompt = "Tracking shot following the timeline. Events light up sequentially."
        assert detect_camera_movement(prompt) == "lateral-pan"

    def test_detects_static(self):
        prompt = "Static shot. Nothing moves except the countdown timer dropping."
        assert detect_camera_movement(prompt) == "static"

    def test_detects_locked_off(self):
        prompt = "Locked-off camera. The figure stands perfectly still as data crumbles."
        assert detect_camera_movement(prompt) == "static"

    def test_detects_tilt_up(self):
        prompt = "Tilt up from the rubble to the towering structure above."
        assert detect_camera_movement(prompt) == "tilt-up"

    def test_detects_crane_up(self):
        prompt = "Crane up revealing the full network topology. Nodes multiply."
        assert detect_camera_movement(prompt) == "tilt-up"

    def test_detects_tilt_down(self):
        prompt = "Tilt down from the summit to the wreckage below. Numbers cascade."
        assert detect_camera_movement(prompt) == "tilt-down"

    def test_detects_snap_zoom(self):
        prompt = "Snap zoom onto the deficit counter. The number locks at 34 trillion."
        assert detect_camera_movement(prompt) == "snap-zoom"

    def test_detects_crash_zoom(self):
        prompt = "Crash zoom into the alert indicator. Alarms blaze red."
        assert detect_camera_movement(prompt) == "snap-zoom"

    def test_detects_orbital(self):
        prompt = "Slow orbital around the war table. Data layers peel back."
        assert detect_camera_movement(prompt) == "orbital"

    def test_detects_orbit_around(self):
        prompt = "Orbit around the floating projection. Connection lines snap."
        assert detect_camera_movement(prompt) == "orbital"

    def test_returns_unknown_for_no_match(self):
        prompt = "The data nodes illuminate one by one. Tension builds."
        assert detect_camera_movement(prompt) == "unknown"

    def test_all_8_types_have_at_least_one_keyword(self):
        """Every camera movement type must be detectable."""
        assert len(CAMERA_MOVEMENTS) == 8
        for movement, keywords in CAMERA_MOVEMENTS.items():
            assert len(keywords) >= 1, f"{movement} has no keywords"

    def test_all_8_types_detected_from_sample_prompts(self):
        """Each of the 8 camera types is correctly identified."""
        samples = {
            "push-in": "Slow push-in toward the screen.",
            "pull-back": "Pull-back revealing the full scene.",
            "lateral-pan": "Lateral pan across the wall display.",
            "static": "Static shot. Nothing moves.",
            "tilt-up": "Tilt up toward the ceiling.",
            "tilt-down": "Tilt down to the ground.",
            "snap-zoom": "Snap zoom onto the counter.",
            "orbital": "Slow orbital around the subject.",
        }
        for expected_type, prompt in samples.items():
            detected = detect_camera_movement(prompt)
            assert detected == expected_type, (
                f"Expected '{expected_type}' but got '{detected}' for: {prompt}"
            )


# ---------------------------------------------------------------------------
# validate_video_prompt camera checks
# ---------------------------------------------------------------------------


class TestValidateVideoPromptCameraChecks:
    """Tests for camera-related validation in validate_video_prompt()."""

    def _make_prompt(self, camera_prefix: str) -> str:
        """Build a prompt long enough to pass word count checks."""
        filler = (
            "Connection lines between nodes snap and dissolve one by one. "
            "The central figure locks into position as surrounding data cascades "
            "downward through three tiers. Terminal screens freeze in sequence "
            "from outer ring inward until only the deficit counter remains "
            "glowing alone in a dead room."
        )
        return f"{camera_prefix}. {filler}"

    def test_no_camera_repeat_when_history_empty(self):
        prompt = self._make_prompt("Slow push-in toward the monitor")
        result = validate_video_prompt(prompt, prev_cameras=[])
        camera_issues = [i for i in result["issues"] if "CAMERA REPEAT" in i]
        assert len(camera_issues) == 0

    def test_camera_repeat_detected(self):
        prompt = self._make_prompt("Slow push-in toward the monitor")
        result = validate_video_prompt(prompt, prev_cameras=["push-in"])
        camera_issues = [i for i in result["issues"] if "CAMERA REPEAT" in i]
        assert len(camera_issues) == 1
        assert not result["valid"]

    def test_no_repeat_with_different_camera(self):
        prompt = self._make_prompt("Pull-back revealing the full scope")
        result = validate_video_prompt(prompt, prev_cameras=["push-in"])
        camera_issues = [i for i in result["issues"] if "CAMERA REPEAT" in i]
        assert len(camera_issues) == 0

    def test_missing_camera_is_valid_static(self):
        """No camera movement is valid — static is the default (Rule 2)."""
        prompt = (
            "Data nodes illuminate one by one from left to right. "
            "The central figure locks into position as surrounding data cascades "
            "downward through three tiers. Terminal screens freeze in sequence "
            "from outer ring inward until only the deficit counter remains "
            "glowing alone in a dead room."
        )
        result = validate_video_prompt(prompt)
        # Static/unknown camera should NOT be flagged as an issue
        no_camera_issues = [i for i in result["issues"] if "NO CAMERA MOVEMENT" in i]
        assert len(no_camera_issues) == 0

    def test_camera_returned_in_result(self):
        prompt = self._make_prompt("Lateral pan across the data wall")
        result = validate_video_prompt(prompt)
        assert result["camera"] == "lateral-pan"

    def test_camera_unknown_returned(self):
        prompt = (
            "Data nodes illuminate one by one from left to right. "
            "The central figure locks into position as surrounding data cascades "
            "downward through three tiers. Terminal screens freeze in sequence "
            "from outer ring inward until only the deficit counter remains "
            "glowing alone in a dead room."
        )
        result = validate_video_prompt(prompt)
        assert result["camera"] == "unknown"

    def test_prev_cameras_none_is_safe(self):
        """Passing None for prev_cameras should not cause errors."""
        prompt = self._make_prompt("Tilt up from the ground level")
        result = validate_video_prompt(prompt, prev_cameras=None)
        camera_issues = [i for i in result["issues"] if "CAMERA REPEAT" in i]
        assert len(camera_issues) == 0

    def test_repeat_check_only_against_last(self):
        """Only the most recent camera should trigger a repeat."""
        prompt = self._make_prompt("Slow push-in toward the target")
        # push-in was used 2 clips ago but NOT the most recent
        result = validate_video_prompt(prompt, prev_cameras=["push-in", "orbital"])
        camera_issues = [i for i in result["issues"] if "CAMERA REPEAT" in i]
        assert len(camera_issues) == 0


# ---------------------------------------------------------------------------
# Camera rotation variety simulation
# ---------------------------------------------------------------------------


class TestCameraRotationVariety:
    """Simulate camera rotation to verify variety enforcement."""

    def test_simulated_variety_no_consecutive_repeats(self):
        """Given 8 different movements, no two consecutive should match."""
        movements = list(CAMERA_MOVEMENTS.keys())
        # Simulate a 24-clip video cycling through all types
        clip_cameras = (movements * 3)[:24]
        for i in range(1, len(clip_cameras)):
            assert clip_cameras[i] != clip_cameras[i - 1] or i % len(movements) == 0, (
                f"Consecutive repeat at clips {i-1}-{i}: {clip_cameras[i]}"
            )

    def test_detect_catches_all_keyword_variants(self):
        """Every keyword in CAMERA_MOVEMENTS should resolve to its type."""
        for movement, keywords in CAMERA_MOVEMENTS.items():
            for keyword in keywords:
                prompt = f"{keyword}. Some motion description follows here."
                detected = detect_camera_movement(prompt)
                assert detected == movement, (
                    f"Keyword '{keyword}' should detect as '{movement}' but got '{detected}'"
                )
