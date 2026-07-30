"""Unit tests for story_bible_native.py (checklist D10-2ab).

Pure module tests — no DB, no pipeline_executor, no network. Covers:

  (a) legacy normalizer parity: characters/locations/scene_blocks come out
      with the SAME field defaults as script.story_bible.
      _validate_and_normalize_scene_blocks (skills/video-pipeline/script/
      story_bible.py:467-564) — re-implemented natively in
      story_bible_native.py, not imported (no legacy test suite exists to
      port verbatim, so this test asserts the legacy behavior directly,
      read from source).
  (b) the three NEW sections (narrative, relationships, arcs) are present
      and dangling character-id references are dropped with a warning,
      never a failure.
  (c) the entry point calls the Claude client with the documented contract
      (prompt/system_prompt/max_tokens/temperature) and returns a fully
      normalized bible.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_story_bible_native.py -q
"""
import asyncio
import json
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import story_bible_native as sbn  # noqa: E402


class FakeAnthropic:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeAnthropic ran out of canned responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


# ---------------------------------------------------------------------------
# (a) normalizer parity — characters / locations / scene_blocks
# ---------------------------------------------------------------------------

def test_characters_get_legacy_default_fields():
    raw = {
        "characters": [
            {"id": "russian_leader", "description": "a grey suit"},  # description->costume fallback
            {"id": "eu_official", "costume": "navy suit"},  # already has costume
            {"id": "bare_char"},  # nothing set — every default kicks in
        ],
    }
    bible = sbn.normalize_story_bible(raw, expected_images=0)
    chars = {c["id"]: c for c in bible["characters"]}

    assert chars["russian_leader"]["costume"] == "a grey suit"
    assert chars["eu_official"]["costume"] == "navy suit"
    bare = chars["bare_char"]
    assert bare["costume"] == "dark formal suit with white shirt"
    assert bare["signature_pose"] == "standing with composed posture"
    assert bare["scenes_present"] == []
    assert bare["role"] == "supporting"


def test_locations_get_legacy_default_fields():
    raw = {"locations": [{"id": "kremlin_office"}]}
    bible = sbn.normalize_story_bible(raw, expected_images=0)
    loc = bible["locations"][0]
    assert loc["description"] == "interior setting"
    assert loc["lighting"] == "ambient lighting"
    assert loc["color_temperature"] == "neutral"
    assert loc["type"] == "INTERIOR"


def test_scene_block_first_image_forced_wide():
    raw = {
        "locations": [{"id": "loc_a", "description": "desc a", "lighting": "warm"}],
        "scene_blocks": [
            {
                "location_id": "loc_a",
                "images": [
                    {"camera": "medium"},  # violates "first image = wide" — must be fixed
                    {},  # no camera — defaults to "medium" since not first
                ],
            }
        ],
    }
    bible = sbn.normalize_story_bible(raw, expected_images=2)
    block = bible["scene_blocks"][0]
    assert block["block_id"] == "block_1"
    assert block["act"] == 1
    assert block["location"] == "desc a"
    assert block["lighting"] == "warm"
    assert block["mood"] == "neutral"
    assert block["characters_present"] == []
    assert block["images"][0]["camera"] == "wide", "first image must be forced to wide"
    assert block["images"][1]["camera"] == "medium"
    assert block["images"][0]["action"] == "scene continues"
    assert block["images"][0]["narration_excerpt"] == ""


def test_scene_block_location_lookup_when_omitted():
    raw = {
        "locations": [{"id": "loc_a", "description": "desc a", "lighting": "warm amber"}],
        "scene_blocks": [{"location_id": "loc_a", "images": [{"camera": "wide"}]}],
    }
    bible = sbn.normalize_story_bible(raw, expected_images=1)
    block = bible["scene_blocks"][0]
    assert block["location"] == "desc a"
    assert block["lighting"] == "warm amber"


def test_scene_block_missing_location_id_falls_back_to_first_location():
    raw = {
        "locations": [{"id": "only_loc", "description": "d", "lighting": "l"}],
        "scene_blocks": [{"images": []}],
    }
    bible = sbn.normalize_story_bible(raw, expected_images=0)
    assert bible["scene_blocks"][0]["location_id"] == "only_loc"


def test_image_count_mismatch_warns_but_does_not_fail(capsys):
    raw = {
        "locations": [{"id": "loc_a", "description": "d", "lighting": "l"}],
        "scene_blocks": [{"location_id": "loc_a", "images": [{"camera": "wide"}]}],
    }
    bible = sbn.normalize_story_bible(raw, expected_images=99)
    out = capsys.readouterr().out
    assert "expected 99" in out
    assert bible["scene_blocks"]  # still returned, generation not aborted


def test_consecutive_same_location_blocks_warn(capsys):
    raw = {
        "locations": [{"id": "loc_a", "description": "d", "lighting": "l"}],
        "scene_blocks": [
            {"block_id": "block_1", "location_id": "loc_a", "images": [{"camera": "wide"}]},
            {"block_id": "block_2", "location_id": "loc_a", "images": [{"camera": "wide"}]},
        ],
    }
    sbn.normalize_story_bible(raw, expected_images=2)
    out = capsys.readouterr().out
    assert "block_1" in out and "block_2" in out and "share location" in out


# ---------------------------------------------------------------------------
# (b) new sections — narrative / relationships / arcs
# ---------------------------------------------------------------------------

def test_narrative_gets_defaults_for_missing_fields():
    bible = sbn.normalize_story_bible({}, expected_images=0)
    narrative = bible["narrative"]
    assert narrative == {
        "genre": "", "tone": "", "themes": [], "conflict": "", "stakes": "",
        "time_period": "", "world_rules": [],
    }


def test_relationships_keep_valid_pairs_and_drop_dangling_refs(capsys):
    raw = {
        "characters": [{"id": "a"}, {"id": "b"}],
        "relationships": [
            {"characters": ["a", "b"], "dynamic": "allies", "tension_source": "trust",
             "evolves_to": "rivals"},
            {"characters": ["a", "ghost"], "dynamic": "unknown"},  # dangling -> dropped
        ],
    }
    bible = sbn.normalize_story_bible(raw, expected_images=0)
    assert bible["relationships"] == [
        {"characters": ["a", "b"], "dynamic": "allies", "tension_source": "trust",
         "evolves_to": "rivals"},
    ]
    out = capsys.readouterr().out
    assert "dangling character id" in out


def test_relationships_malformed_pair_dropped():
    raw = {
        "characters": [{"id": "a"}],
        "relationships": [{"characters": ["a"]}, {"characters": "not-a-list"}],
    }
    bible = sbn.normalize_story_bible(raw, expected_images=0)
    assert bible["relationships"] == []


def test_arcs_keep_valid_ids_and_drop_dangling_refs(capsys):
    raw = {
        "characters": [{"id": "a"}],
        "arcs": {
            "a": {"start_state": "confident", "end_state": "cornered",
                  "turning_scenes": [2, "5", "not-a-number"]},
            "ghost": {"start_state": "x", "end_state": "y"},  # dangling -> dropped
        },
    }
    bible = sbn.normalize_story_bible(raw, expected_images=0)
    assert bible["arcs"] == {
        "a": {"start_state": "confident", "end_state": "cornered", "turning_scenes": [2, 5]},
    }
    out = capsys.readouterr().out
    assert "dangling character id" in out


def test_dangling_refs_never_raise():
    # Every field wrong-shaped — normalize_story_bible must still return a dict.
    raw = {
        "characters": "not-a-list",
        "locations": None,
        "scene_blocks": {"not": "a list"},
        "narrative": "not-a-dict",
        "relationships": "not-a-list",
        "arcs": ["not", "a", "dict"],
    }
    bible = sbn.normalize_story_bible(raw, expected_images=0)
    assert bible["characters"] == []
    assert bible["locations"] == []
    assert bible["scene_blocks"] == []
    assert bible["relationships"] == []
    assert bible["arcs"] == {}


# ---------------------------------------------------------------------------
# (c) entry point — Claude call contract + full normalization
# ---------------------------------------------------------------------------

def _fixture_response(total_images=6):
    """A small, internally-consistent bible: 2 characters, 2 locations,
    2 scene_blocks (3 images each = 6, matches total_images=6 for a
    1-minute video: max(6, 60*1//10) == 6)."""
    return json.dumps({
        "characters": [
            {"id": "hero", "costume": "worn field jacket", "role": "protagonist"},
            {"id": "rival", "costume": "sharp grey suit", "role": "antagonist"},
        ],
        "locations": [
            {"id": "loc_a", "description": "desert outpost", "lighting": "harsh noon sun",
             "color_temperature": "warm", "type": "EXTERIOR"},
            {"id": "loc_b", "description": "war room", "lighting": "cold fluorescent",
             "color_temperature": "cold", "type": "DATA_SETTING"},
        ],
        "scene_blocks": [
            {
                "block_id": "block_1", "act": 1, "location_id": "loc_a",
                "location": "desert outpost", "lighting": "harsh noon sun", "mood": "tense",
                "characters_present": ["hero"],
                "images": [
                    {"image_index": 1, "camera": "wide", "action": "hero arrives",
                     "narration_excerpt": "excerpt one"},
                    {"image_index": 2, "camera": "medium", "action": "hero scans horizon",
                     "narration_excerpt": "excerpt two"},
                    {"image_index": 3, "camera": "closeup", "action": "hero grips rifle",
                     "narration_excerpt": "excerpt three"},
                ],
            },
            {
                "block_id": "block_2", "act": 1, "location_id": "loc_b",
                "location": "war room", "lighting": "cold fluorescent", "mood": "clinical",
                "characters_present": ["rival"],
                "images": [
                    {"image_index": 4, "camera": "wide", "action": "rival briefs staff",
                     "narration_excerpt": "excerpt four"},
                    {"image_index": 5, "camera": "medium", "action": "rival points at map",
                     "narration_excerpt": "excerpt five"},
                    {"image_index": 6, "camera": "closeup", "action": "rival's cold stare",
                     "narration_excerpt": "excerpt six"},
                ],
            },
        ],
        "narrative": {
            "genre": "thriller", "tone": "tense", "themes": ["power", "betrayal"],
            "conflict": "hero vs rival", "stakes": "the outpost falls",
            "time_period": "present day", "world_rules": ["water is scarce"],
        },
        "relationships": [
            {"characters": ["hero", "rival"], "dynamic": "adversaries",
             "tension_source": "competing claims", "evolves_to": "open conflict"},
        ],
        "arcs": {
            "hero": {"start_state": "uncertain", "end_state": "resolute",
                     "turning_scenes": [3]},
            "rival": {"start_state": "confident", "end_state": "exposed",
                      "turning_scenes": [5, 6]},
        },
    })


def test_generate_calls_client_with_documented_contract():
    anthropic = FakeAnthropic([_fixture_response()])
    bible = asyncio.run(sbn.generate_story_bible_native(
        anthropic_client=anthropic,
        full_script_text="[SCENE 1]\n" + ("word " * 40),
        video_title="Test Video",
        video_length_minutes=1,
    ))

    assert len(anthropic.calls) == 1
    call = anthropic.calls[0]
    assert "prompt" in call and "full_script_text" not in call  # formatted, not passed raw
    assert isinstance(call["prompt"], str) and "TOTAL IMAGES REQUIRED: 6" in call["prompt"]
    assert call["system_prompt"] == sbn.NATIVE_STORY_BIBLE_SYSTEM_PROMPT
    assert call["max_tokens"] == 16000
    assert call["temperature"] == 0.3

    # Full parity: all six top-level sections present.
    for key in ("characters", "locations", "scene_blocks", "narrative", "relationships", "arcs"):
        assert key in bible

    assert len(bible["characters"]) == 2
    assert len(bible["locations"]) == 2
    assert len(bible["scene_blocks"]) == 2
    assert sum(len(b["images"]) for b in bible["scene_blocks"]) == 6
    assert bible["narrative"]["genre"] == "thriller"
    assert bible["relationships"][0]["characters"] == ["hero", "rival"]
    assert bible["arcs"]["hero"]["turning_scenes"] == [3]


def test_generate_raises_on_too_short_script():
    anthropic = FakeAnthropic([])
    try:
        asyncio.run(sbn.generate_story_bible_native(
            anthropic_client=anthropic,
            full_script_text="too short",
            video_title="Test",
            video_length_minutes=10,
        ))
        raise AssertionError("expected ValueError for too-short script")
    except ValueError:
        pass
    assert anthropic.calls == [], "must not call Claude for an unusable script"


def test_generate_raises_on_unparseable_response():
    anthropic = FakeAnthropic(["not json at all, no braces"])
    try:
        asyncio.run(sbn.generate_story_bible_native(
            anthropic_client=anthropic,
            full_script_text="[SCENE 1]\n" + ("word " * 40),
            video_title="Test",
            video_length_minutes=1,
        ))
        raise AssertionError("expected ValueError for unparseable response")
    except ValueError:
        pass
