"""turn_boundaries: split times for multi-speaker voice-locked clips.

The live failure this guards (La Lavandería v2, Ryan's ear): STT tokenizes
"Supermercado" as "Super" + "Mercado", so a word-COUNT boundary lands early
and the tail of Ryan's line converts in Vanessa's voice. Boundaries must
anchor on MATCHED words, fall back to the biggest pause, then to proportion.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from clip_dialogue import turn_boundaries  # noqa: E402


def w(word, start, end):
    return {"word": word, "start": start, "end": end}


def test_supermercado_tokenization_does_not_shift_boundary():
    # Script: RYAN "Supermercado. The supermarket?" / VANESSA "Sí."
    # Heard: "Supermercado" arrives as TWO tokens; "Sí" heard as "See".
    heard = [w("Super", 0.0, 0.5), w("Mercado.", 0.5, 1.0),
             w("The", 1.44, 1.74), w("supermarket?", 1.74, 2.3),
             w("See.", 2.9, 3.32)]
    bounds = turn_boundaries(heard, ["Supermercado. The supermarket?", "Sí."])
    assert len(bounds) == 1
    # Must land in the real pause (2.3 .. 2.9), NOT after heard-word 3 (~1.5s)
    assert 2.3 <= bounds[0] <= 2.9


def test_clean_match_lands_between_turns():
    heard = [w("Do", 0.0, 0.2), w("not", 0.2, 0.4), w("worry.", 0.4, 0.9),
             w("It's", 1.6, 1.8), w("fine.", 1.8, 2.2)]
    bounds = turn_boundaries(heard, ["Do not worry.", "It's fine."])
    assert len(bounds) == 1
    assert 0.9 <= bounds[0] <= 1.6


def test_three_turns_two_ascending_boundaries():
    heard = [w("Hola.", 0.0, 0.5),
             w("Hello.", 1.2, 1.6),
             w("Gracias.", 2.4, 3.0)]
    bounds = turn_boundaries(heard, ["Hola.", "Hello.", "Gracias."])
    assert len(bounds) == 2
    assert bounds[0] < bounds[1]
    assert 0.5 <= bounds[0] <= 1.2
    assert 1.6 <= bounds[1] <= 2.4


def test_garbled_words_fall_back_to_pause():
    # Nothing matches the script; the only signal is the big pause.
    heard = [w("blah", 0.0, 0.4), w("blur", 0.4, 0.8),
             w("blip", 2.0, 2.4), w("blop", 2.4, 2.8)]
    bounds = turn_boundaries(heard, ["Two words here", "and here two"])
    assert len(bounds) == 1
    assert 0.8 <= bounds[0] <= 2.0


def test_no_words_or_single_turn_yield_no_bounds():
    assert turn_boundaries([], ["a", "b"]) == []
    assert turn_boundaries([w("hi", 0, 1)], ["only one turn"]) == []
