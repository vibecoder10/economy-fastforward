"""C3 item 3 (film-grammar rebuild, 2026-07-22): the reaction/insert/
re-establish shot floors (storyboard.coverage's enforce_reaction_insert_floors)
tag added shots inline — "(SETUP C)(REACTION) ..." / "(SETUP E)(INSERT) ...".

_escalate_panel_briefs (scripts/coverage_to_app.py) is the sweep-2 escalation
path — the ONLY caller of _neutralize_risky_props/_neutralize_risky_gestures
that actually REWRITES a scene's saved coverage_directive text (never the
build-time pass). Before this chunk it only ever protected two row shapes
whole-line: a `LINE: <Speaker> | "..."` row (the verbatim spoken script) and
the `[AXIS | ...]` screen-direction contract. A MASTER/ANGLE row carrying a
(REACTION)/(INSERT) tag was NOT protected — nothing currently in
_RISKY_PROP_PATTERNS/_RISKY_GESTURE_PATTERNS collides with those literal
tokens, but the tags are structural bookkeeping (coverage.py's own
_shot_tag()/enforce_reaction_insert_floors re-parse them from this exact
stored text later), not prose — a future pattern careless about word
boundaries could silently eat one and degrade the floor accounting on the
next re-parse. This pins the fix: extend the protected-row check with
_DIRECTIVE_REACTION_INSERT_ROW_RE (reusing coverage.py's own _INLINE_TAG_RE
as the single source of truth for what the tag looks like).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_c3_reaction_insert_tag_protection.py -q
"""
import os
import subprocess
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from scripts.coverage_to_app import (  # noqa: E402
    _escalate_panel_briefs, _DIRECTIVE_REACTION_INSERT_ROW_RE,
)
from storyboard.coverage import _INLINE_TAG_RE, _shot_tag  # noqa: E402

# A directive shaped like a real stored plan: [SET|]/[SETUPS|]/[AXIS|]
# headers, a LINE: row, an untagged ANGLE, and both new tag shapes — with
# risky-prop/gesture language planted in EVERY line so a passing test proves
# the two new rows are truly whole-line protected, not accidentally spared.
DIRECTIVE = """\
[SET | Home Kitchen: wooden island with a chef's knife and a cutting board on it.]
[AXIS | Ryan frame-LEFT looking frame-RIGHT; Vanessa frame-RIGHT looking frame-LEFT; knife on the counter.]
[SETUPS | A: WS two-shot; B: MCU OTS onto Ryan; C: MCU OTS onto Vanessa.]

[MOMENT 1 | Ryan explains the knife technique]
LINE: Ryan | "Do I peel with a knife?"
- MASTER [MCU]: (SETUP B) Ryan gestures at the chef's knife on the cutting board.
- ANGLE [MCU]: (SETUP C)(REACTION) CU on Vanessa, listening to Ryan's line, eyeing the knife warily.
- ANGLE [INSERT]: (SETUP E)(INSERT) Insert on the chef's knife resting beside the cutting board.
"""


def _run():
    return _escalate_panel_briefs(DIRECTIVE)


# ---------------------------------------------------------------------------
# 1. The two PRE-EXISTING protections still hold (regression guard).
# ---------------------------------------------------------------------------

def test_line_row_untouched():
    out, _ = _run()
    assert 'LINE: Ryan | "Do I peel with a knife?"' in out


def test_axis_row_untouched():
    out, _ = _run()
    assert ("[AXIS | Ryan frame-LEFT looking frame-RIGHT; Vanessa frame-RIGHT looking "
            "frame-LEFT; knife on the counter.]") in out


# ---------------------------------------------------------------------------
# 2. NEW: a REACTION/INSERT-tagged row is protected whole-line — the tag AND
#    the risky prop language riding alongside it both survive byte-for-byte.
# ---------------------------------------------------------------------------

def test_reaction_row_untouched_tag_and_prose_both_survive():
    out, _ = _run()
    assert ("- ANGLE [MCU]: (SETUP C)(REACTION) CU on Vanessa, listening to Ryan's line, "
            "eyeing the knife warily.") in out


def test_insert_row_untouched_tag_and_prose_both_survive():
    out, _ = _run()
    assert ("- ANGLE [INSERT]: (SETUP E)(INSERT) Insert on the chef's knife resting beside "
            "the cutting board.") in out


def test_re_parsing_the_escalated_directive_still_finds_both_tags():
    """The point of protecting the row: a downstream re-parse (coverage.py's
    own _shot_tag, via parse_coverage) must still see the tags after this
    text has been through a sweep-2 escalation."""
    out, _ = _run()
    tags_found = [m.group(1).upper() for m in _INLINE_TAG_RE.finditer(out)]
    assert sorted(tags_found) == ["INSERT", "REACTION"]


# ---------------------------------------------------------------------------
# 3. Everywhere else builder-authored (untagged): still neutralized exactly
#    as before — the new protection doesn't leak into rows it shouldn't.
# ---------------------------------------------------------------------------

def test_untagged_rows_still_get_neutralized():
    out, _ = _run()
    # [SET|], [SETUPS|], and the untagged MASTER row all had "knife"/"cutting
    # board" — none of those rows carry the new tag, so all three still run
    # through _neutralize_risky_props.
    set_line = next(l for l in out.splitlines() if l.startswith("[SET"))
    setups_line = next(l for l in out.splitlines() if l.startswith("[SETUPS"))
    master_line = next(l for l in out.splitlines() if l.startswith("- MASTER"))
    for line in (set_line, setups_line, master_line):
        assert "knife" not in line.lower(), line
    assert "the utensils" in set_line
    assert "the prep board" in set_line
    assert "the utensils" in master_line


def test_reworded_pairs_exclude_the_protected_rows():
    """The (old, new) reworded log only reflects the untagged rows — nothing
    from the LINE/AXIS/tagged rows should appear as a rewording, since those
    three row shapes are never even handed to the pattern loop."""
    _, reworded = _run()
    old_terms = {old.lower() for old, _new in reworded}
    # "knife" WAS reworded (from [SET|]/[SETUPS|]/the untagged MASTER), but
    # never as a byproduct of touching the LINE row or a tagged row's prose —
    # confirmed by the untouched-content assertions above; here we just pin
    # that reworded pairs exist at all (the neutralization pass DID run).
    assert any("knife" in t for t in old_terms), reworded


# ---------------------------------------------------------------------------
# 4. Regex identity: the protection reuses coverage.py's _INLINE_TAG_RE
#    directly (single source of truth), not a re-typed copy.
# ---------------------------------------------------------------------------

def test_protected_row_regex_is_the_same_object_as_coverage_pys_inline_tag_re():
    assert _DIRECTIVE_REACTION_INSERT_ROW_RE is _INLINE_TAG_RE


def test_protected_row_regex_does_not_match_a_plain_setup_row():
    assert not _DIRECTIVE_REACTION_INSERT_ROW_RE.search(
        "- MASTER [MCU]: (SETUP B) Ryan gestures at the utensils.")


# ---------------------------------------------------------------------------
# 5. py_compile guard.
# ---------------------------------------------------------------------------

def test_coverage_to_app_compiles():
    target = os.path.abspath(os.path.join(_BACKEND, "scripts", "coverage_to_app.py"))
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", target], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    test_line_row_untouched()
    test_axis_row_untouched()
    test_reaction_row_untouched_tag_and_prose_both_survive()
    test_insert_row_untouched_tag_and_prose_both_survive()
    test_re_parsing_the_escalated_directive_still_finds_both_tags()
    test_untagged_rows_still_get_neutralized()
    test_reworded_pairs_exclude_the_protected_rows()
    test_protected_row_regex_is_the_same_object_as_coverage_pys_inline_tag_re()
    test_protected_row_regex_does_not_match_a_plain_setup_row()
    test_coverage_to_app_compiles()
    print("\nAll C3 reaction/insert tag-protection tests passed.")
