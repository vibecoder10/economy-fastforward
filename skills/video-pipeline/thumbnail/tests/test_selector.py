"""Tests for thumbnail/selector.py — template selection, incl. the C34c/S10-4
niche-neutral default fix.

The critical regression this guards against: a brand-new tenant with no
geo/person/split/symbolic content in a video, and no finance/geopolitics
niche, must land on the neutral Template E — never the blind Template A
(Map + Barrier) world-map default. Ryan's original Economy FastForward
channel must still reach Template A, either through its own content
(GEO_KEYWORDS) or its niche (GEO_NICHE_KEYWORDS).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from orchestrator.pipeline_constants import IdeaFields
from thumbnail.selector import select_template


@pytest.fixture(autouse=True)
def _clean_channel_niche_env(monkeypatch):
    """CHANNEL_NICHE is a cross-package env seam (mirrors VISUAL_STYLE_DESCRIPTION).
    Make sure no test leaks it to another and no ambient value from a real
    pipeline run leaks into these tests."""
    monkeypatch.delenv("CHANNEL_NICHE", raising=False)
    yield


def _metadata(title="", summary="", framework_angle="", niche=None):
    md = {
        IdeaFields.VIDEO_TITLE: title,
        IdeaFields.SUMMARY: summary,
        IdeaFields.FRAMEWORK_ANGLE: framework_angle,
        "tags": [],
    }
    if niche is not None:
        md["niche"] = niche
    return md


# ---------------------------------------------------------------------------
# The core C34c/S10-4 fix: unmatched content + unmatched/no niche -> neutral E
# ---------------------------------------------------------------------------

def test_unmatched_content_no_niche_defaults_to_neutral_template_not_map():
    """A brand-new tenant, no channel history, no niche signal, video content
    that isn't geopolitical/person/split/symbolic at all — must NOT get the
    world-map Template A."""
    md = _metadata(
        title="How to Fold a Perfect Croissant",
        summary="A step-by-step guide to laminating butter into dough.",
        niche="",
    )
    assert select_template(md) == "template_e"


def test_cooking_niche_with_unmatched_content_stays_neutral():
    md = _metadata(
        title="5 Ingredient Substitutions Every Baker Should Know",
        summary="Simple swaps for eggs, butter, and flour.",
        niche="cooking and baking tutorials",
    )
    assert select_template(md) == "template_e"


def test_esl_niche_with_unmatched_content_stays_neutral():
    md = _metadata(
        title="Describing Your Weekend in Simple English",
        summary="Practice describing what happened last weekend.",
        niche="beginner ESL / language learning",
    )
    assert select_template(md) == "template_e"


# ---------------------------------------------------------------------------
# Template A stays reachable — content-level geo keywords
# ---------------------------------------------------------------------------

def test_geo_content_keyword_selects_template_a_regardless_of_niche():
    md = _metadata(
        title="Mapping the World's Busiest Trade Routes",
        summary="How shipping lanes and canals decide who profits in global trade.",
        niche="cooking",  # niche says otherwise; the CONTENT still earns Template A
    )
    assert select_template(md) == "template_a"


def test_supply_chain_keyword_selects_template_a():
    md = _metadata(
        title="Why the Global Supply Chain is Under Pressure",
        summary="Reserve currency shifts and what they mean for trade blocs.",
    )
    assert select_template(md) == "template_a"


# ---------------------------------------------------------------------------
# Template A niche-informed fallback — Ryan's legacy channel preservation
# ---------------------------------------------------------------------------

def test_finance_niche_fallback_selects_template_a_when_content_is_ambiguous():
    """No GEO_KEYWORDS hit in the video's own text, but the CHANNEL's niche is
    finance/economics (Ryan's legacy channel) — still Template A."""
    md = _metadata(
        title="Something Strange is Happening With the Numbers",
        summary="A fresh look at a pattern nobody has noticed yet.",
        niche="finance/economics",
    )
    assert select_template(md) == "template_a"


def test_geopolitics_niche_env_var_fallback_selects_template_a():
    """The legacy Airtable-only pipeline doesn't build a 'niche' key at all —
    it relies purely on the CHANNEL_NICHE env var seam pipeline_executor.py
    exports for the StoryEngine path. Confirms the env fallback works when
    video_metadata carries no 'niche' key whatsoever."""
    os.environ["CHANNEL_NICHE"] = "finance/economics"
    try:
        md = _metadata(
            title="Something Strange is Happening With the Numbers",
            summary="A fresh look at a pattern nobody has noticed yet.",
        )
        assert "niche" not in md
        assert select_template(md) == "template_a"
    finally:
        os.environ.pop("CHANNEL_NICHE", None)


def test_ryans_legacy_content_still_lands_on_template_a():
    """Regression: a realistic Economy FastForward-style headline (no niche
    info available at all, exactly the legacy Airtable pipeline's shape)
    must still land on Template A — its own content is inherently
    geopolitical/macro."""
    md = _metadata(
        title="The Empire America Built With Debt",
        summary="How the dollar's reserve currency status shapes global power.",
    )
    assert select_template(md) == "template_a"


# ---------------------------------------------------------------------------
# Existing behavior unchanged — B/C/D keyword priority
# ---------------------------------------------------------------------------

def test_person_keyword_still_wins_over_everything():
    md = _metadata(title="Who is the CEO Behind This?", niche="")
    assert select_template(md) == "template_b"


def test_split_keyword_still_wins_over_geo_default():
    md = _metadata(title="Sanctions: Winner vs Loser", niche="")
    assert select_template(md) == "template_c"


def test_symbolic_keyword_still_wins_over_geo_default():
    md = _metadata(title="The Trap Nobody Sees Coming", niche="")
    assert select_template(md) == "template_d"


def test_preferred_template_override_bypasses_selection(monkeypatch):
    """engine.py's preferred_template short-circuits select_template entirely —
    not exercised here directly (that's engine.py's job), but selector.py
    itself must not raise on any of the five valid keys."""
    from thumbnail.templates import TEMPLATES
    assert set(TEMPLATES.keys()) == {
        "template_a", "template_b", "template_c", "template_d", "template_e",
    }


# ---------------------------------------------------------------------------
# C34d: word-boundary keyword matching — "king" must not match "talking"
# ---------------------------------------------------------------------------

def test_king_substring_inside_talking_does_not_trigger_person_template():
    """The bug: PERSON_KEYWORDS' plain `in` substring check matched "king"
    inside "talking"/"breaking", pushing completely unrelated content onto
    Template B. Neither word appears elsewhere in this text, so pre-fix this
    selected template_b; post-fix it must fall through to the neutral
    default."""
    md = _metadata(
        title="Just Talking About Breaking News in the Kitchen",
        summary="A casual chat about what's cooking today.",
        niche="",
    )
    assert select_template(md) == "template_e"


def test_king_whole_word_still_triggers_person_template():
    """The fix must not throw out the real keyword — a genuine standalone
    "king" mention still earns Template B."""
    md = _metadata(title="The King Who Lost His Empire", niche="")
    assert select_template(md) == "template_b"


def test_multiword_phrase_still_matches_after_word_boundary_fix():
    """Multi-word PERSON_KEYWORDS phrases (e.g. "prime minister") must keep
    matching in full — the word-boundary fix only anchors the START of the
    match, it must not break phrase matching."""
    md = _metadata(
        title="Meet the New Prime Minister",
        summary="A profile of the country's newest leader.",
        niche="",
    )
    assert select_template(md) == "template_b"


def test_word_stem_keyword_still_matches_its_longer_form():
    """Several keywords are intentional stems ("financ", "geopolit",
    "strangl", "weaponiz") meant to match their fuller forms. The
    word-boundary fix anchors only the START of the keyword, so these must
    keep matching as a prefix of a longer word."""
    md = _metadata(
        title="How Financial Markets Strangled a Generation",
        summary="A look at global financing and its consequences.",
        niche="",
    )
    assert select_template(md) == "template_d"  # "strangl" -> "Strangled"


def test_plural_of_single_word_keyword_still_matches():
    """A plain word keyword ("agent") must still match its plural
    ("agents") — the fix only anchors the start of the word, not the end."""
    md = _metadata(title="The Secret Agents Who Ran the Operation", niche="")
    assert select_template(md) == "template_b"


def test_geo_niche_word_stem_still_matches_via_channel_niche_env(monkeypatch):
    """GEO_NICHE_KEYWORDS' stems ("financ", "geopolit") must keep matching a
    longer niche string, not just an exact list entry."""
    md = _metadata(
        title="Something Strange is Happening With the Numbers",
        summary="A fresh look at a pattern nobody has noticed yet.",
        niche="financial news and analysis",
    )
    assert select_template(md) == "template_a"
