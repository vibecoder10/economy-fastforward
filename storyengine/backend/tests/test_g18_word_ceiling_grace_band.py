"""G18: word-ceiling grace band - near-misses advise, overshoots block.

Ryan's ruling (2026-08-01, verbatim): "7 words over isnt bad, i call that
nit picky and wouldnt worry about it". Real case: video d2e37cd6's HMS Argus
static-docu script preview came back 177 words against the 170-word hard
ceiling; the validator's ONLY hard failure was the word-count message
"word count 177 over the 170-word hard ceiling - split or cut the entry" -
everything else was already advisory. The 177-word paragraph fixture below
is pulled verbatim from that video's live research_payload.machine_script_
previews via `scripts/se.sh db` (read-only) - not invented.

These tests are local/no-spend (no Anthropic/API calls; pure functions).
"""

import json
import os

import pipeline_executor as pe


# ---------------------------------------------------------------------------
# Real fixture: video d2e37cd6 ("Every British Aircraft Carrier Class Ever
# Built"), machine "HMS Argus (I49) Argus", pulled via `scripts/se.sh db`
# from research_payload->'machine_script_previews'. word_count = 177,
# checked live against `_ANTON_PARAGRAPH_HARD_MAX_WORDS = 170`.
# ---------------------------------------------------------------------------
ARGUS = "HMS Argus (I49) Argus"
ARGUS_PARAGRAPH_177 = (
    "Early trials with platforms jutting from battleship superstructures confirmed that "
    "turbulence made even light aircraft like the Sopwith Pup nearly impossible to land "
    "safely, forcing the Royal Navy to pursue a radical solution: a completely unobstructed "
    "flight deck from bow to stern. The incomplete Italian liner Conte Rosso became HMS "
    "Argus, fitted with a flush deck, furnace smoke vented through horizontal ducts, hinged "
    "wireless masts that folded flat, and retractable wind screens, and by December she had "
    "logged roughly thirty-six successful landings with Sopwith Pups and one-and-a-half "
    "Strutters. Argus was a conversion born of wartime urgency, a compromise hull that any "
    "observer by the late about 1930s would recognize as hopelessly outclassed by "
    "purpose-built fleet carriers. She missed the Armistice entirely, spent the interwar "
    "years as an experimental platform, then returned to service around 1938 not as a "
    "strike carrier but as a ferry hauling fighters to Malta and screening convoys until "
    "she was scrapped in 1946. The pioneering carrier proved the concept, then spent a "
    "second war doing everything but the mission she was built for."
)


def test_argus_fixture_is_really_177_words_over_a_170_ceiling():
    """Sanity: the fixture is the real payload, not a rounded approximation."""
    assert pe._spoken_word_count(ARGUS_PARAGRAPH_177) == 177
    assert pe._ANTON_PARAGRAPH_HARD_MAX_WORDS == 170


# ---------------------------------------------------------------------------
# Fixture builders for the grace-band boundary tests. `_validate_static_unit_
# paragraph` also screens for other things (locked designation, meta text,
# digits) that are irrelevant to the word-count law - these paragraphs stay
# clean of all of that so the only warning in play is the word-count one.
# ---------------------------------------------------------------------------

def _padded_paragraph(machine_mention: str, target_words: int) -> str:
    """A clean natural-language paragraph naming `machine_mention` once,
    padded with filler words (no digits, no production cues) to exactly
    `target_words` spoken words as counted by `_spoken_word_count`."""
    opener = f"{machine_mention} sailed on and the crew kept careful watch through every long grey morning."
    words = opener.split()
    filler_cycle = ["steady", "careful", "quiet", "distant", "familiar", "patient", "watchful", "faithful"]
    i = 0
    while len(words) < target_words:
        words.append(filler_cycle[i % len(filler_cycle)])
        i += 1
    words = words[:target_words]
    # keep it grammatical-ish and terminate with a period
    text = " ".join(words)
    if not text.endswith("."):
        text += "."
    return text


def test_padded_paragraph_builder_hits_exact_word_targets():
    for n in (72, 79, 80, 120, 170, 177, 187, 188, 200):
        paragraph = _padded_paragraph(ARGUS, n)
        assert pe._spoken_word_count(paragraph) == n, n


# ---------------------------------------------------------------------------
# Ceiling: 170 in-band, 171-187 advisory near-miss, 188+ still hard-blocks.
# ---------------------------------------------------------------------------

def test_real_177_word_argus_paragraph_is_advisory_only_not_blocking():
    """The exact real-world regression case: 177 words over a 170 ceiling
    (a 7-word/4% overshoot) must not produce a blocking warning."""
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, ARGUS_PARAGRAPH_177)
    assert not pe._blocking_warnings(warnings), warnings
    assert any(
        w.startswith("advisory: ") and "177" in w and "170-word target" in w
        for w in warnings
    ), warnings


def test_170_word_paragraph_in_band_produces_no_word_count_warning():
    paragraph = _padded_paragraph(ARGUS, 170)
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    assert not any("word count" in w or "words, over" in w or "words, under" in w for w in warnings), warnings


def test_120_word_paragraph_mid_band_produces_no_word_count_warning():
    paragraph = _padded_paragraph(ARGUS, 120)
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    assert not any("word count" in w or "words, over" in w or "words, under" in w for w in warnings), warnings


def test_187_words_ceiling_grace_edge_is_still_advisory():
    """170 * 1.10 = 187 exactly - the top edge of the grace band, inclusive."""
    paragraph = _padded_paragraph(ARGUS, 187)
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    assert not pe._blocking_warnings(warnings), warnings
    assert any(w.startswith("advisory: ") and "187" in w for w in warnings), warnings


def test_188_words_just_past_grace_edge_hard_blocks():
    paragraph = _padded_paragraph(ARGUS, 188)
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    blocking = pe._blocking_warnings(warnings)
    assert any("hard ceiling - split or cut the entry" in w for w in blocking), warnings


def test_200_word_paragraph_still_hard_fails():
    """A real overshoot (30 words / 18% over) must still block - the grace
    band protects near-misses, not genuinely rambling paragraphs."""
    paragraph = _padded_paragraph(ARGUS, 200)
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    blocking = pe._blocking_warnings(warnings)
    assert any("word count 200 over the 170-word hard ceiling - split or cut the entry" == w for w in blocking), warnings


# ---------------------------------------------------------------------------
# Floor symmetry: 80 in-band (existing 80-95 warn band already advisory),
# 72-79 is the NEW grace-band advisory, below 72 still hard-blocks.
# ---------------------------------------------------------------------------

def test_80_word_paragraph_at_floor_is_in_the_existing_warn_band_not_new_grace():
    paragraph = _padded_paragraph(ARGUS, 80)
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    assert not pe._blocking_warnings(warnings), warnings
    # Existing pre-G18 warn-band message (80-95), unrelated to the new grace band.
    assert any("warn band - confirm the entry is terse on purpose" in w for w in warnings), warnings


def test_72_words_floor_grace_edge_is_advisory_not_blocking():
    """80 * 0.90 = 72 exactly - the bottom edge of the new floor grace band."""
    paragraph = _padded_paragraph(ARGUS, 72)
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    assert not pe._blocking_warnings(warnings), warnings
    assert any(w.startswith("advisory: ") and "72" in w and "80-word target" in w for w in warnings), warnings


def test_71_words_just_under_floor_grace_edge_hard_blocks():
    paragraph = _padded_paragraph(ARGUS, 71)
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    blocking = pe._blocking_warnings(warnings)
    assert any("word count 71 under the 80-word hard floor - thicken or fold the entry" == w for w in blocking), warnings


# ---------------------------------------------------------------------------
# Shared-helper contract: one classifier, reused by both enforcement sites.
# ---------------------------------------------------------------------------

def test_shared_word_band_helper_boundaries():
    verdict = pe._paragraph_word_band_verdict
    assert verdict(170, 80, 170)["status"] == "ok"
    assert verdict(80, 80, 170)["status"] == "ok"
    assert verdict(187, 80, 170) == {
        "status": "near_ceiling", "blocking": False,
        "message": "187 words, over the 170-word target - trim when convenient",
    }
    assert verdict(188, 80, 170)["status"] == "over_ceiling"
    assert verdict(188, 80, 170)["blocking"] is True
    assert verdict(72, 80, 170)["status"] == "near_floor"
    assert verdict(72, 80, 170)["blocking"] is False
    assert verdict(71, 80, 170)["status"] == "under_floor"
    assert verdict(71, 80, 170)["blocking"] is True


def test_preview_quality_audit_word_range_check_uses_the_same_helper_and_passes_argus_case():
    """The second enforcement site (the preview quality-audit checklist, the
    other place the task calls out) must independently pass the real Argus
    177-word case: word_range advisory, not blocking, overall passed=True
    when nothing else is blocking."""
    plan = {"contract": {"narrative_weight": {"target_words": "110-150"}}, "slots": []}
    bundle = {"claim_map": [], "formula_sentences": [ARGUS_PARAGRAPH_177], "twist": {"type": "role_change"}}
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, ARGUS_PARAGRAPH_177)
    audit = pe._anton_preview_quality_audit(ARGUS, plan, bundle, ARGUS_PARAGRAPH_177, warnings)
    word_range_check = next(c for c in audit["checks"] if c["name"] == "word_range")
    assert word_range_check["passed"] is True
    assert word_range_check.get("advisory") is True
    assert "177" in word_range_check["detail"]
    assert audit["passed"] is True, audit


def test_preview_quality_audit_word_range_check_still_fails_hard_for_a_real_overshoot():
    plan = {"contract": {"narrative_weight": {"target_words": "110-150"}}, "slots": []}
    paragraph = _padded_paragraph(ARGUS, 200)
    bundle = {"claim_map": [], "formula_sentences": [paragraph], "twist": {"type": "role_change"}}
    warnings = pe.PipelineExecutor._validate_static_unit_paragraph(ARGUS, paragraph)
    audit = pe._anton_preview_quality_audit(ARGUS, plan, bundle, paragraph, warnings)
    word_range_check = next(c for c in audit["checks"] if c["name"] == "word_range")
    assert word_range_check["passed"] is False
    assert not word_range_check.get("advisory")
    assert audit["passed"] is False


# ---------------------------------------------------------------------------
# Writer prompts still state the plain 80/170 WORD LAW (only the checker
# gets the grace - the writer should still aim inside the hard band).
# ---------------------------------------------------------------------------

def test_writer_prompts_still_state_the_original_hard_band_not_the_grace_expanded_one():
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(backend_root, "pipeline_executor.py"), encoding="utf-8") as f:
        source = f.read()
    # The WORD LAW prompt strings must still name 170 (via the constant), and
    # nowhere does a prompt string get built from the grace-expanded ceiling.
    assert "hard ceiling {_ANTON_PARAGRAPH_HARD_MAX_WORDS}" in source
    assert "hard floor {_ANTON_PARAGRAPH_HARD_MIN_WORDS}" in source
    assert "_ANTON_PARAGRAPH_HARD_MAX_WORDS * (1" not in source.replace(" ", "")
