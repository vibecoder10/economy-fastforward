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


def test_shape_scales_inserts_with_narration():
    mm, amin, amax = _coverage_shape(MARCO_SCENE)
    # Guardrails off (Ryan 2026-07-02): dialogue moments get 1-2 angles again
    assert (amin, amax) == (1, 2)
    assert mm == 13, mm  # 6 turns + 7 inserts (this fixture's ~140 narration words)
    # Heavy narration caps at the moment budget (the runaway-planner brake)
    heavy = MARCO_SCENE + ("\nThe narrator keeps teaching lots of extra words. " * 40)
    assert _coverage_shape(heavy)[0] == 18
    # Tiny dialogue scene keeps the establishing+cutaway floor
    mm2, _, _ = _coverage_shape("Tom: Hi.\nLisa: Hey.")
    assert mm2 == 4, mm2  # 2 turns + floor 2
    # Pure narration keeps cinematic coverage
    assert _coverage_shape("Just narration, no speakers at all.") == (3, 2, 3)


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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} dialogue-alignment tests passed")
