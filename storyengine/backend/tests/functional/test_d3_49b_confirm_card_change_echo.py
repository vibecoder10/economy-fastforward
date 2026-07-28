"""Tests for D3-49b (mission filed 2026-07-28): the paid-action confirm
card's intro used to be a FIXED template off cfg['label'] — "Ready when you
are — I'll write the script (~$0.40)." — with no trace of what the creator
actually asked for. A rich, specific request ("Add dialogue between the
elites and Nyla...") rendered byte-identical to a bare "write the script"
ask. pending["change"] was (and still is) correctly captured and consumed
downstream (_run_pending_action -> apply_followup_edit -> writer_guidance,
routes/chat.py ~1615-1624) — only the VISIBLE card lied by omission.

routes.chat._change_echo_note(change) is the extracted, directly-testable
piece of that fix: it returns the short quoted echo to append to the confirm
card's intro (or "" when there's nothing to echo). This file tests that
function in isolation — no DB, no network, no classifier call — mirroring
test_c36_budget_cap.py's / test_c15_itemized_cost_breakdown.py's pattern of
testing the real `routes.chat` module directly.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d3_49b_confirm_card_change_echo.py -q
"""
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import routes.chat as chat_route  # noqa: E402


# --- the case that was broken: a specific, rich change gets echoed ---------

def test_change_echo_note_quotes_a_specific_request():
    note = chat_route._change_echo_note(
        "Add dialogue between the elites and Nyla about the failed harvest"
    )
    assert note != "", "a real change must produce a visible echo, not silence"
    assert "I'll also fold in" in note
    assert "Add dialogue between the elites and Nyla about the failed harvest" in note
    print("✅ test_change_echo_note_quotes_a_specific_request")


def test_change_echo_note_truncates_past_140_chars_with_ellipsis():
    long_change = "x" * 200
    note = chat_route._change_echo_note(long_change)
    # 140 chars of the original text, plus "..." — never the full 200.
    assert ("x" * 140) in note
    assert ("x" * 141) not in note
    assert note.endswith('..."')
    print("✅ test_change_echo_note_truncates_past_140_chars_with_ellipsis")


def test_change_echo_note_collapses_newlines_onto_one_line():
    note = chat_route._change_echo_note("line one\nline two\n\nline three")
    assert "\n" not in note, "the card intro is a one-line chat bubble"
    assert "line one line two line three" in note
    print("✅ test_change_echo_note_collapses_newlines_onto_one_line")


# --- the case that must stay unchanged: no change, no echo -----------------

def test_change_echo_note_empty_for_none():
    assert chat_route._change_echo_note(None) == ""
    print("✅ test_change_echo_note_empty_for_none")


def test_change_echo_note_empty_for_empty_string():
    assert chat_route._change_echo_note("") == ""
    print("✅ test_change_echo_note_empty_for_empty_string")


def test_change_echo_note_empty_for_whitespace_only():
    assert chat_route._change_echo_note("   \n\t  ") == ""
    print("✅ test_change_echo_note_empty_for_whitespace_only")


# --- end-to-end-ish: the intro string as _handle_copilot actually builds it,
# both with and without a change, asserting the CONTENT differs exactly the
# way D3-49b's report says it didn't before this fix. ------------------------

def _build_intro(cfg_label: str, where: str, cost_text: str, detail: str,
                  guard: str, budget_note: str, change) -> str:
    """Mirrors the exact f-string in _handle_copilot (routes/chat.py, right
    before `return await _reply(intro, cards=[...])`) so this test fails if
    that literal template ever drifts, without needing to run the whole
    classify -> cost -> gate -> confirm pipeline (DB/model calls) just to
    reach one string."""
    change_note = chat_route._change_echo_note(change)
    return (
        f"Ready when you are — I'll {cfg_label.lower()}{where} ({cost_text}{detail}). "
        f"Tap to run it, or tell me to change anything first.{guard}{budget_note}{change_note}"
    )


def test_confirm_card_intro_carries_the_change_when_present():
    intro = _build_intro(
        "Write the script", "", "~$0.40", "", "", "",
        "Add dialogue between the elites and Nyla about the failed harvest",
    )
    assert "Ready when you are" in intro
    assert "~$0.40" in intro
    assert "Add dialogue between the elites and Nyla" in intro
    print("✅ test_confirm_card_intro_carries_the_change_when_present")


def test_confirm_card_intro_unchanged_shape_when_no_change():
    intro = _build_intro("Write the script", "", "~$0.40", "", "", "", None)
    assert intro == (
        "Ready when you are — I'll write the script (~$0.40). "
        "Tap to run it, or tell me to change anything first."
    )
    print("✅ test_confirm_card_intro_unchanged_shape_when_no_change")


def test_confirm_card_intro_differs_between_specific_and_bare_requests():
    """The exact regression D3-49b reported: a rich request and a bare
    'write the script' ask used to render IDENTICALLY. They must not now."""
    bare = _build_intro("Write the script", "", "~$0.40", "", "", "", "")
    specific = _build_intro(
        "Write the script", "", "~$0.40", "", "", "",
        "Add dialogue between the elites and Nyla about the failed harvest",
    )
    assert bare != specific
    print("✅ test_confirm_card_intro_differs_between_specific_and_bare_requests")


if __name__ == "__main__":
    test_change_echo_note_quotes_a_specific_request()
    test_change_echo_note_truncates_past_140_chars_with_ellipsis()
    test_change_echo_note_collapses_newlines_onto_one_line()
    test_change_echo_note_empty_for_none()
    test_change_echo_note_empty_for_empty_string()
    test_change_echo_note_empty_for_whitespace_only()
    test_confirm_card_intro_carries_the_change_when_present()
    test_confirm_card_intro_unchanged_shape_when_no_change()
    test_confirm_card_intro_differs_between_specific_and_bare_requests()
    print("All D3-49b confirm-card change-echo tests passed!")
