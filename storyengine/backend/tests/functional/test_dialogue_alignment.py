"""Functional tests for the dialogue-line alignment chain (2026-07-02 fix).

The live failure: every spoken line landed ~2 shots early because (a) the
turn splitter merged same-speaker lines across narration, and (b) the line
reconcile ignored the planner's LINE markers and stamped turns positionally.
These tests pin the fixed behavior at every layer: turn splitting, the shot
budget, planner-respecting reconcile, and assigned_dialogue line matching.

No network, no DB: heavy imports are stubbed (module-stub pattern).
Run: python3 tests/functional/test_dialogue_alignment.py  (from backend dir)
"""

import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BACKEND)

# ── Stub coverage_to_app's runtime deps BEFORE importing it ──
def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod

async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")

_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    _coverage_shape,
    _dialogue_turns,
    _reconcile_moment_dialogue,
)
from clip_dialogue import match_assigned  # noqa: E402

# The Marco scene's dialogue skeleton (narration abbreviated).
MARCO_SCENE = """
**Marco:** ¡Espera! ¡Espera!
Marco's running to school. Again. His backpack bouncing, breath short, shoes slapping the pavement. No one's waiting.
**Marco:** Lo siento. Llegué tarde otra vez.
Lo siento means I'm sorry. Marco always says this. Every single morning his friends don't even look up anymore.
Lunchtime. Marco sits by himself. He pulls out his sandwich.
**Sofia:** ¿Por qué siempre llegas tarde, Marco?
Sofia's asking him why do you always arrive late. Por qué means why and siempre means always in Spanish.
**Marco:** No sé. Corro rápido, pero...
I don't know. I run fast but. Corro means I run. But it's never fast enough for him to arrive.
Then one morning, something changes. Marco sprints to school, same as always, but everyone else is running too.
**Marco:** ¿Qué pasa? ¿Por qué corren?
What's happening, why are you all running he asks them all in the street.
**Sofia:** ¡Llegamos tarde! ¡El reloj de la escuela estaba roto!
We're late, the school clock was broken. Marco stops and looks at Sofia and laughs for the first time in weeks.
"""


def _moment(summary, shot="MS", speaker=None, line=None):
    return {"summary": summary, "master": {"shot_type": shot, "description": summary},
            "angles": [], "speaker": speaker, "line": line}


def test_turns_split_across_narration():
    turns = _dialogue_turns(MARCO_SCENE)
    assert [(s, t[:12]) for s, t in turns] == [
        ("Marco", "¡Espera! ¡Es"),
        ("Marco", "Lo siento. L"),
        ("Sofia", "¿Por qué sie"),
        ("Marco", "No sé. Corro"),
        ("Marco", "¿Qué pasa? ¿"),
        ("Sofia", "¡Llegamos ta"),
    ], turns


def test_turns_adjacent_same_speaker_still_merge():
    text = "**Tom:** Hello there.\n**Tom:** It is me.\nNarration between.\n**Tom:** New turn."
    turns = _dialogue_turns(text)
    assert turns == [("Tom", "Hello there. It is me."), ("Tom", "New turn.")], turns


def test_reconcile_respects_planner_markers():
    """The live bug scenario: silent moments first, speaking moments marked."""
    moments = [
        _moment("Silent establishing — Marco sprints down the street", "WS"),
        _moment("Marco calls out racing toward the gate", speaker="Marco",
                line="Espera, espera! (planner paraphrase)"),
        _moment("Silent — Marco slides into his seat", "WS"),
        _moment("Sofia questions Marco at the cafeteria", speaker="Sofia",
                line="Por que siempre llegas tarde"),
        _moment("Marco answers Sofia", speaker="Marco", line="No se, corro rapido"),
        _moment("Sofia reveals the clock was broken", speaker="Sofia",
                line="Llegamos tarde"),
    ]
    turns = [("Marco", '¡Espera! ¡Espera!'), ("Sofia", '¿Por qué siempre llegas tarde, Marco?'),
             ("Marco", 'No sé. Corro rápido, pero...'), ("Sofia", '¡Llegamos tarde!')]
    text = "\n".join(f"{s}: {t}" if i % 2 == 0 else f"narration here\n{s}: {t}"
                     for i, (s, t) in enumerate(turns))
    out = _reconcile_moment_dialogue(moments, text)
    # Silent moments stay silent
    assert out[0]["line"] is None and out[2]["line"] is None
    # Marked moments carry VERBATIM script words, in order
    assert out[1]["line"] == '¡Espera! ¡Espera!' and out[1]["speaker"] == "Marco"
    assert out[3]["line"] == '¿Por qué siempre llegas tarde, Marco?'
    assert out[4]["line"] == 'No sé. Corro rápido, pero...'
    assert out[5]["line"] == '¡Llegamos tarde!'


def test_reconcile_folds_missing_moment_onto_same_speaker():
    """Planner made ONE Marco moment but the script has two Marco turns."""
    moments = [
        _moment("Silent wide", "WS"),
        _moment("Marco speaks", speaker="Marco", line="something"),
        _moment("Sofia replies", speaker="Sofia", line="reply"),
    ]
    text = "Marco: First line here.\nnarration\nMarco: Second line too.\nnarration\nSofia: Reply words."
    out = _reconcile_moment_dialogue(moments, text)
    assert out[0]["line"] is None
    assert out[1]["line"] == "First line here. Second line too."  # folded, no loss
    assert out[2]["line"] == "Reply words."


def test_reconcile_kills_hallucinated_line():
    """A planner LINE for a speaker who never talks in the script goes silent."""
    moments = [
        _moment("Marco speaks", speaker="Marco", line="real"),
        _moment("Ghost speaks", speaker="Narrator", line="I do not exist in the script"),
    ]
    out = _reconcile_moment_dialogue(moments, "Marco: Hola amigo.")
    assert out[0]["line"] == "Hola amigo."
    assert out[1]["line"] is None and out[1]["speaker"] is None


def test_reconcile_legacy_fallback_skips_silent_summaries():
    """No LINE rows at all → positional stamp, but never onto 'Silent —' moments."""
    moments = [
        _moment("Silent establishing — street"),
        _moment("Marco shouts at the gate"),
        _moment("Sofia answers him"),
    ]
    out = _reconcile_moment_dialogue(
        moments, "Marco: Hola.\nnarration\nSofia: Adiós.")
    assert out[0]["line"] is None
    assert out[1]["line"] == "Hola." and out[1]["speaker"] == "Marco"
    assert out[2]["line"] == "Adiós."


def test_reconcile_replays_the_real_marco_plan():
    """The EXACT plan the planner produced live (cached coverage.json,
    2026-07-02) — made under the old 4-turn merged checklist — replayed with
    the new 6-turn splitter. Text-cover matching must land every line on the
    moment the planner built for it: merged-turn masters share, silents stay
    silent, nothing drifts."""
    moments = [
        _moment("Silent establishing — Marco sprints down the school street", "WS"),
        _moment("Marco calls out as he races toward the school gate",
                speaker="Marco", line="¡Espera! ¡Espera! Lo siento. Llegué tarde otra vez."),
        _moment("Silent — Marco slides into his seat alone; the Teacher nods", "WS"),
        _moment("Sofia questions Marco at the cafeteria lunch table",
                speaker="Sofia", line="¿Por qué siempre llegas tarde, Marco?"),
        _moment("Marco answers Sofia, then reacts to everyone running in",
                speaker="Marco", line="No sé. Corro rápido, pero... ¿Qué pasa? ¿Por qué corren?"),
        _moment("Sofia reveals the clock was broken — Marco laughs",
                speaker="Sofia", line="¡Llegamos tarde! ¡El reloj de la escuela estaba roto!"),
    ]
    out = _reconcile_moment_dialogue(moments, MARCO_SCENE)
    assert out[0]["line"] is None and out[2]["line"] is None       # silents stay silent
    assert out[1]["line"] == "¡Espera! ¡Espera! Lo siento. Llegué tarde otra vez."
    assert out[3]["line"] == "¿Por qué siempre llegas tarde, Marco?"
    assert out[4]["line"] == "No sé. Corro rápido, pero... ¿Qué pasa? ¿Por qué corren?"
    assert out[5]["line"] == "¡Llegamos tarde! ¡El reloj de la escuela estaba roto!"
    assert out[1]["speaker"] == "Marco" and out[3]["speaker"] == "Sofia"


def test_shape_echo_paces_to_runtime():
    """voice_over echo channels: one moment per ~8s of speech, angles 0-2 and
    EARNED, total frames capped at 2× the paced count (≤40). Ryan's rule."""
    mm, amin, amax, mframes = _coverage_shape(MARCO_SCENE, "voice_over")
    assert (amin, amax) == (0, 2)
    est_seconds = len(MARCO_SCENE.split()) / 2.5
    expected = max(6 + 2, round(est_seconds / 8))
    assert mm == expected, (mm, expected)
    assert mframes == min(2 * expected, 40), mframes
    # A long scene rides the 40-frame ceiling, never beyond
    heavy = MARCO_SCENE + ("\nThe narrator keeps teaching lots of extra words. " * 60)
    assert _coverage_shape(heavy, "voice_over")[3] == 40
    # Tiny pure-dialogue scene → masters-only branch (turns + establishing)
    assert _coverage_shape("Tom: Hi.\nLisa: Hey.", "voice_over")[0] == 3


def test_shape_pure_dialogue_plans_masters_only():
    """Couple format: no narrator → no clock for silent angles. One
    establishing + one master per line, nothing the renderer must drop."""
    text = "\n".join(f"{'Ryan' if i % 2 else 'Vanessa'}: line {i} palabra." for i in range(24))
    mm, amin, amax, mf = _coverage_shape(text, "voice_over")
    assert (mm, amin, amax, mf) == (25, 0, 0, 25), (mm, amin, amax, mf)


def test_shape_grok_native_keeps_cinematic_coverage():
    mm, amin, amax, mframes = _coverage_shape(MARCO_SCENE, "grok_native")
    assert (amin, amax) == (1, 2)  # the Pixar-grade multi-angle path
    assert mframes is None
    assert mm >= 10, mm
    # Pure narration keeps classic coverage in both modes
    assert _coverage_shape("Just narration, no speakers at all.") == (3, 2, 3, None)


def test_enforce_budget_frame_ceiling_strips_angles_first():
    from storyboard.coverage import enforce_shot_budget
    moments = [{"moment_number": i + 1, "summary": f"m{i+1}",
                "master": {"shot_type": "MS", "description": "d"},
                "angles": [{"shot_type": "CU", "description": "a1"},
                           {"shot_type": "OTS", "description": "a2"}]}
               for i in range(10)]  # 30 frames planned
    out = enforce_shot_budget(moments, 10, 2, max_frames=18)
    frames = sum(1 + len(m["angles"]) for m in out)
    assert frames == 18, frames
    assert len(out) == 10  # every master survives — angles paid the bill
    # stripping starts at the tail: the earliest moments keep their angles
    assert all(len(m["angles"]) == 2 for m in out[:4])
    assert all(len(m["angles"]) == 0 for m in out[5:])
    # Masters alone above the ceiling → tail moments drop, never crash
    out2 = enforce_shot_budget([dict(m, angles=[]) for m in moments], 10, 2, max_frames=4)
    assert len(out2) == 4


def test_match_assigned():
    lines = [
        {"speaker": "Marco", "text": "¡Espera! ¡Espera!", "audio_url": "u1"},
        {"speaker": "Marco", "text": "Lo siento. Llegué tarde otra vez.", "audio_url": "u2"},
        {"speaker": "Sofia", "text": "¿Por qué siempre llegas tarde, Marco?", "audio_url": "u3"},
    ]
    # exact single turn
    got = match_assigned('Marco: "¡Espera! ¡Espera!"', lines)
    assert [l["audio_url"] for l in got] == ["u1"], got
    # folded master carrying two Marco turns → both, in order
    got = match_assigned('Marco: "¡Espera! ¡Espera! Lo siento. Llegué tarde otra vez."', lines)
    assert [l["audio_url"] for l in got] == ["u1", "u2"], got
    # speaker must match — Sofia's words on a Marco label match nothing
    assert match_assigned('Marco: "¿Por qué siempre llegas tarde, Marco?"', lines[:2]) == []
    # no assigned / junk assigned
    assert match_assigned(None, lines) == []
    assert match_assigned("not a line", lines) == []


def test_sheet_prompts_preview_the_whole_plan():
    from scripts.coverage_to_app import _plan_sheet_prompts, _scene_text_hash
    moments = []
    for i in range(9):  # 9 moments, every 3rd speaks, every 2nd has an angle
        m = _moment(f"moment {i+1} action", speaker="Marco" if i % 3 == 0 else None,
                    line=f"linea {i+1}" if i % 3 == 0 else None)
        m["moment_number"] = i + 1
        if i % 2 == 0:
            m["angles"] = [{"shot_type": "CU", "description": f"angle of {i+1}"}]
        moments.append(m)
    prompts = _plan_sheet_prompts(moments, "Pixar 3D", panels_per_sheet=12)
    total_panels = 9 + 5  # masters + angles
    assert len(prompts) == 2, len(prompts)  # 12 + 2
    joined = "\n".join(prompts)
    for k in range(1, total_panels + 1):
        assert f"[{k}]" in joined, f"panel {k} missing"
    assert 'SPEAKING Marco: "linea 1"' in prompts[0]
    assert "Pixar 3D" in prompts[0] and "Pixar 3D" in prompts[1]
    assert "sheet 1 of 2" in prompts[0] and "sheet 2 of 2" in prompts[1]
    # hash pins the plan to the text, whitespace-insensitively
    assert _scene_text_hash("a  b\nc") == _scene_text_hash("a b c")
    assert _scene_text_hash("a b c") != _scene_text_hash("a b d")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} dialogue-alignment tests passed")
