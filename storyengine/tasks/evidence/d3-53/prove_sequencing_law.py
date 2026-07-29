#!/usr/bin/env python3
"""D3-53b evidence: prove the new sequencing/bridge law (rule 4b) is present
in the LIVE storyboard prompt path for both a dialogue scene and a silent
(narration-only) scene, and that rule 5 (dialogue script-turn order) is
untouched.

_coverage_system_prompt(profile, max_moments, angles_min, angles_max) does
NOT take beat_text — it is the SAME text regardless of scene content, so
"dialogue vs silent" is proven at the _coverage_user_prompt() layer instead
(that's where _scene_turns(beat_text) decides whether a DIALOGUE TURNS block
is added). This script shows both layers:

  1. _coverage_system_prompt() output carries rule 4b (causal chain, silent-
     moment event order, mandatory BRIDGE tag) AND still carries rule 5
     (dialogue = one speaker per moment, IN SCRIPT ORDER) unmodified.
  2. _coverage_user_prompt() for a DIALOGUE fixture emits the DIALOGUE TURNS
     block (proves rule 5's ordering machinery is untouched by this change).
  3. _coverage_user_prompt() for a SILENT fixture emits NO dialogue turns
     block (proves the scenes correctly diverge) — the causal-chain rule 4b
     in the system prompt is the ONLY sequencing law that then applies,
     which is exactly the gap the diagnosis identified.

Run: <repo>/storyengine/backend/venv/bin/python3 tasks/evidence/d3-53/prove_sequencing_law.py
(from storyengine/backend/, or anywhere — sys.path is set up below same as
coverage_to_app.py does it). $0 cost: no network calls, no API keys used.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
_SKILLS = os.path.join(_REPO, "skills", "video-pipeline")
sys.path.insert(0, _SKILLS)

from storyboard.coverage import (  # noqa: E402
    _coverage_system_prompt,
    _coverage_user_prompt,
    _scene_turns,
)
from shared.channel_profile import load_profile  # noqa: E402

DIALOGUE_SCENE = """Ryan: I sealed the hatch the second the alarm hit.
Vanessa: Then why is the corridor light still on outside?
Ryan: Because someone's already through it.
"""

SILENT_SCENE = (
    "Inside the sealed pod, Ryan checks the oxygen gauge, hands shaking. He "
    "pushes the hatch open and steps into the harshly lit exterior hallway, "
    "scanning both directions before moving forward."
)


def main():
    profile = load_profile({})
    system_prompt = _coverage_system_prompt(profile, max_moments=8, angles_min=2, angles_max=4)

    print("=" * 78)
    print("1) SYSTEM PROMPT — rule 4b present (causal chain + bridge law)")
    print("=" * 78)
    assert "4b)" in system_prompt, "FAIL: rule 4b missing from system prompt"
    assert "CAUSAL CHAIN" in system_prompt, "FAIL: causal chain language missing"
    assert '"(BRIDGE)"' in system_prompt, "FAIL: BRIDGE tag convention missing"
    assert profile.emotional_arc.beat_1 in system_prompt, "FAIL: EmotionalArc vocabulary not reused"
    assert profile.emotional_arc.beat_4 in system_prompt, "FAIL: EmotionalArc vocabulary not reused"
    rule_4b_start = system_prompt.index("4b)")
    rule_4b_text = system_prompt[rule_4b_start: system_prompt.index("\n5)", rule_4b_start)]
    print(rule_4b_text)
    print()

    print("=" * 78)
    print("2) SYSTEM PROMPT — rule 5 (dialogue order) UNCHANGED, still present")
    print("=" * 78)
    assert "DIALOGUE = ONE SPEAKER PER MOMENT" in system_prompt, "FAIL: rule 5 missing/altered"
    assert "IN SCRIPT ORDER" in system_prompt, "FAIL: rule 5 script-order clause missing"
    rule5_start = system_prompt.index("5) DIALOGUE")
    print(system_prompt[rule5_start: rule5_start + 260] + " ...")
    print()

    print("=" * 78)
    print("3) OUTPUT-FORMAT tail references rule 4b (silent-moment guidance)")
    print("=" * 78)
    tail_start = system_prompt.index("Plan up to")
    print(system_prompt[tail_start: system_prompt.index("Describe every person", tail_start)])
    assert "rule 4b" in system_prompt[tail_start:], "FAIL: output-format tail doesn't cite rule 4b"
    print()

    print("=" * 78)
    print("4) DIALOGUE fixture — _coverage_user_prompt emits DIALOGUE TURNS block")
    print("=" * 78)
    turns = _scene_turns(DIALOGUE_SCENE)
    dialogue_user_prompt = _coverage_user_prompt(
        DIALOGUE_SCENE, "Test Video", None, None, None)
    assert turns, "FAIL: dialogue fixture produced zero turns"
    assert "DIALOGUE TURNS" in dialogue_user_prompt, "FAIL: dialogue turns block missing"
    assert "IN THIS ORDER" in dialogue_user_prompt, "FAIL: script-order instruction missing"
    print(f"Parsed {len(turns)} turns: {turns}")
    dt_start = dialogue_user_prompt.index("DIALOGUE TURNS")
    print(dialogue_user_prompt[dt_start - 3: dt_start + 200] + " ...")
    print()

    print("=" * 78)
    print("5) SILENT fixture — NO dialogue turns block (rule 4b is the only law)")
    print("=" * 78)
    silent_turns = _scene_turns(SILENT_SCENE)
    silent_user_prompt = _coverage_user_prompt(
        SILENT_SCENE, "Test Video", None, None, None)
    assert not silent_turns, f"FAIL: silent fixture unexpectedly parsed turns: {silent_turns}"
    assert "DIALOGUE TURNS" not in silent_user_prompt, "FAIL: silent fixture got a turns block"
    print(f"Parsed {len(silent_turns)} turns (expected 0) — scene narrates a location change "
          f"(pod -> hallway) with no dialogue; rule 4b's BRIDGE requirement in the SYSTEM "
          f"prompt (section 1 above) is the only sequencing guidance that applies to it.")
    print()

    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
