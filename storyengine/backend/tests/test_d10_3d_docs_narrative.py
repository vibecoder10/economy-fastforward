"""D10-3d — the channel profile document's Story Bible section stops
treating ``videos.story_bible`` as an opaque string.

Before this change, ``_visual_generation_lines`` (channel_profile_documents.py)
truncated the raw ``story_bible`` JSON to 1800 chars with no regard for what
was inside it — so a StoryEngine-native bible's ``narrative`` section
(genre/tone/conflict/stakes — D10-2ab) could get cut off mid-JSON, losing the
most useful narrative facts. This adds a compact 1-2 line human-readable
summary, PREPENDED before the existing truncated raw section, whenever the
bible parses as JSON and carries a non-empty ``narrative`` section.

Covers:
  1. A native bible with a populated ``narrative`` section gets a summary
     (genre, tone, conflict, stakes) prepended before the raw JSON blob.
  2. A legacy bible (no ``narrative`` key) produces output byte-identical to
     pre-D10-3d behavior — the key test.
  3. A freshly-normalized-but-empty ``narrative`` section (every key present,
     every value empty — story_bible_native's own all-empty-input shape)
     also produces byte-identical output.
  4. Unparseable JSON garbage produces byte-identical output — never raises.
  5. Non-dict JSON (e.g. a bare list/string) is treated as absent — never
     raises, no exception escapes to the caller.
  6. The story_bible column as a JSON string (the asyncpg-no-jsonb-codec
     shape every other Story Bible consumer in this codebase tolerates) is
     parsed the same as a native dict.

Local/no-spend: pure-function coverage over ``_visual_generation_lines`` and
``_story_bible_narrative_summary_lines`` directly — no DB, no network, no
API keys. Mirrors the pure-function test style of
tests/test_d10_3b_critique_bible.py's own ``_story_structure_addendum``
coverage.
"""

import json

import channel_profile_documents as cpd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _legacy_bible():
    """A bible generated before D10-2ab — no narrative/relationships/arcs keys."""
    return {
        "characters": [{"id": "hero", "costume": "dark suit"}],
        "locations": [{"id": "office", "description": "an office"}],
        "scene_blocks": [],
    }


def _empty_native_bible():
    """A bible normalize_story_bible has touched, but the model contributed
    nothing to the new sections — every new key present, every value empty."""
    return {
        "characters": [{"id": "hero", "costume": "dark suit"}],
        "locations": [],
        "scene_blocks": [],
        "narrative": {
            "genre": "", "tone": "", "themes": [], "conflict": "",
            "stakes": "", "time_period": "", "world_rules": [],
        },
        "relationships": [],
        "arcs": {},
    }


def _populated_bible():
    return {
        "characters": [{"id": "hero", "costume": "dark suit"}],
        "locations": [],
        "scene_blocks": [],
        "narrative": {
            "genre": "geopolitical thriller",
            "tone": "tense",
            "themes": ["power vacuum"],
            "conflict": "hero must expose the rival before the vote",
            "stakes": "the treaty collapses if hero fails",
            "time_period": "present day",
            "world_rules": ["the vote happens at dawn"],
        },
        "relationships": [],
        "arcs": {},
    }


def _data_with_bible(raw_bible):
    """Minimal ``data`` dict shape _visual_generation_lines expects — a
    seed production video carrying ``story_bible``."""
    return {
        "generated_at": "2026-01-01T00:00:00Z",
        "production_video": {
            "video": {
                "video_title": "Test Video",
                "status": "scripted",
                "story_bible": raw_bible,
            },
            "active_visual_style": {},
            "assets": [],
            "scenes": [],
            "style_characters": [],
        },
    }


def _story_bible_lines(raw_bible):
    """Slice out the doc lines between the "Story Bible / Continuity Notes"
    heading and the next Heading2, so assertions don't depend on unrelated
    sections of the document."""
    lines = cpd._visual_generation_lines(_data_with_bible(raw_bible))
    start = next(
        i for i, (style, text) in enumerate(lines)
        if style == "Heading2" and text == "Story Bible / Continuity Notes"
    )
    end = start + 1
    while end < len(lines) and lines[end][0] != "Heading2":
        end += 1
    return lines[start + 1:end]


# ---------------------------------------------------------------------------
# 1. Populated narrative section — summary appears before the raw blob
# ---------------------------------------------------------------------------

def test_populated_bible_prepends_narrative_summary_before_raw_blob():
    section = _story_bible_lines(_populated_bible())
    assert len(section) >= 2, "expected at least one summary line + the raw JSON line"
    styles = [style for style, _ in section]
    assert all(style == "Normal" for style in styles)

    summary_text = " ".join(text for _, text in section[:-1])
    assert "Genre: geopolitical thriller" in summary_text
    assert "Tone: tense" in summary_text
    assert "Conflict: hero must expose the rival before the vote" in summary_text
    assert "Stakes: the treaty collapses if hero fails" in summary_text

    # The raw truncated JSON blob is still the LAST line, unchanged in kind.
    raw_line = section[-1][1]
    assert raw_line.startswith("{")

    # Compact: 1-2 summary lines, not a sprawling multi-paragraph dump.
    assert len(section) <= 3


def test_summary_helper_returns_at_most_two_lines_directly():
    out = cpd._story_bible_narrative_summary_lines(_populated_bible())
    assert isinstance(out, list)
    assert 1 <= len(out) <= 2
    joined = " ".join(out)
    assert "Genre: geopolitical thriller" in joined
    assert "Stakes: the treaty collapses if hero fails" in joined


def test_story_bible_column_as_json_string_is_parsed():
    """asyncpg can return JSONB as a str without a registered codec — the
    same shape every other Story Bible consumer in this codebase tolerates."""
    out = cpd._story_bible_narrative_summary_lines(json.dumps(_populated_bible()))
    assert any("geopolitical thriller" in line for line in out)


# ---------------------------------------------------------------------------
# 2-4. Byte-identical output — the key tests
# ---------------------------------------------------------------------------

def test_legacy_bible_string_produces_byte_identical_section():
    """A legacy bible stored as the raw JSON string (no narrative key at
    all) must produce EXACTLY today's single-line truncated-JSON section —
    no summary line prepended."""
    raw = json.dumps(_legacy_bible())
    section = _story_bible_lines(raw)
    assert section == [("Normal", cpd._shorten(raw, 1800))]


def test_empty_narrative_bible_produces_byte_identical_section():
    """Every new key present, every value empty — must not add a summary
    line either; still exactly the one truncated-raw-JSON line."""
    raw = json.dumps(_empty_native_bible())
    section = _story_bible_lines(raw)
    assert section == [("Normal", cpd._shorten(raw, 1800))]


def test_unparseable_garbage_produces_byte_identical_section():
    raw = "{not valid json at all"
    section = _story_bible_lines(raw)
    assert section == [("Normal", cpd._shorten(raw, 1800))]


def test_non_dict_json_treated_as_absent_no_summary():
    """A bare JSON list/string is valid JSON but not a bible object — must
    be treated as absent, never raise, never add a summary line."""
    raw = json.dumps(["not", "a", "dict"])
    section = _story_bible_lines(raw)
    assert section == [("Normal", cpd._shorten(raw, 1800))]


def test_legacy_bible_as_native_dict_produces_byte_identical_section():
    """Some call sites hand a dict (not a JSON string) straight through —
    same byte-identical contract must hold."""
    bible = _legacy_bible()
    section = _story_bible_lines(bible)
    assert section == [("Normal", cpd._shorten(bible, 1800))]


# ---------------------------------------------------------------------------
# 5. Never raises, on any input shape
# ---------------------------------------------------------------------------

def test_helper_never_raises_on_wild_inputs():
    wild_inputs = [
        None,
        123,
        3.14,
        True,
        [],
        {},
        "",
        "   ",
        "null",
        "[1, 2, 3]",
        {"narrative": None},
        {"narrative": "not a dict"},
        {"narrative": []},
        {"narrative": {"genre": None, "tone": 42, "conflict": ["x"], "stakes": {}}},
        object(),
    ]
    for value in wild_inputs:
        out = cpd._story_bible_narrative_summary_lines(value)
        assert isinstance(out, list), f"failed for input: {value!r}"


def test_visual_generation_lines_never_raises_with_garbage_story_bible():
    for raw in ["{not json", "[]", "null", 42, object(), {"narrative": {"genre": 1}}]:
        # Must not raise.
        cpd._visual_generation_lines(_data_with_bible(raw))


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
