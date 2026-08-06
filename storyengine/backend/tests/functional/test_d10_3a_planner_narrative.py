"""D10-3a — the coverage/board planner learns the video's narrative signal.

D10-2ab (backend/story_bible_native.py) taught videos.story_bible to carry a
StoryEngine-native `narrative` section ({genre, tone, themes[], conflict,
stakes, time_period, world_rules[]}) plus `relationships`/`arcs`, alongside
the legacy characters/locations/scene_blocks keys. Before this chunk, the
coverage/board planner (scripts/coverage_to_app.py -> storyboard/coverage.py's
generate_coverage_directive) had ZERO per-video tone/genre signal — the only
tone hint anywhere in this file is LAW 3 (_write_motion_prompts, a totally
different function: a CHANNEL-wide hint via channel_format.get_channel_tone,
applied to per-shot camera-motion writing, never to board planning).

This chunk threads `narrative` (and, one line each, `relationships`) into the
planner prompt at BOTH scene_aware_bible() call sites — WITHOUT touching
storyboard/coverage.py (skills root, out of scope): the only free-text hook
that reaches the planner's system prompt without editing that file is
generate_coverage_directive's existing `board_rules_text` parameter (today
used only for quality_rules board-scoped text). The new
_board_rules_text_with_narrative() helper composes narrative-first,
quality-rules-second, and both call sites route through it — see BUILD notes
in scripts/coverage_to_app.py for exactly where.

Covers, bottom-up:
  1. _narrative_context_block — pure rendering of a bible's narrative/
     relationships into the delimited <narrative> block.
  2. _board_rules_text_with_narrative — the composition helper both call
     sites use; "" + "" => "" is the byte-identical contract at its root.
  3. _story_bible_narrative_context — the DB read (legacy/unparseable/
     dict-vs-JSON-string column shapes).
  4. scene_aware_bible — end to end: legacy bible unaffected, AND a bible
     with narrative but no characters/locations no longer collapses to None
     (the fixed final gate).
  5. THE KEY BYTE-IDENTICAL PROOF: storyboard.coverage's REAL
     _coverage_system_prompt/_coverage_user_prompt (no mocks, no LLM call —
     both are pure string builders) rendered with a legacy bible, with and
     without this chunk's wrapper, asserted equal.
  6. The narrative block's shape and position inside that SAME real system
     prompt, for a native bible.
  7. Wiring proof at both real call sites (generate_coverage_for_video /
     generate_storyboard_sheet_for_scene): generate_coverage_directive is
     called with a narrative-bearing board_rules_text for a native bible,
     and is either not reached (site 2's fallback branch) or reached with
     board_rules_text unchanged (site 1) for a legacy bible.

STASH-PROOF: _narrative_context_block / _board_rules_text_with_narrative /
_story_bible_narrative_context do not exist before D10-3a — `git stash` (or
`git apply -R` the diff) on this branch makes this whole file fail at
COLLECTION (ImportError), the loudest possible "before" signal.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d10_3a_planner_narrative.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


# Placeholders at import time; every real test overrides via patch(...) or a
# monkeypatched FakeDB, same pattern as the other coverage_to_app.py test files.
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

import scripts.coverage_to_app as coverage_to_app  # noqa: E402
from scripts.coverage_to_app import (  # noqa: E402
    scene_aware_bible,
    _story_bible_narrative_context,
    _narrative_context_block,
    _board_rules_text_with_narrative,
    generate_coverage_for_video,
    generate_storyboard_sheet_for_scene,
)
from storyboard.coverage import _coverage_system_prompt, _coverage_user_prompt  # noqa: E402
from shared.channel_profile import load_profile  # noqa: E402

VIDEO_ID = "22222222-2222-2222-2222-222222222222"
TENANT_ID = "tenant-narrative"

LEGACY_BIBLE = {
    "characters": [{"id": "Ryan", "costume": "black polo, beard", "scenes_present": [1]}],
    "locations": [{"id": "kitchen", "description": "a sunlit kitchen", "lighting": "", "type": ""}],
}

NATIVE_NARRATIVE = {
    "genre": "heist thriller",
    "tone": "tense, wry",
    "themes": ["found family", "cost of loyalty"],
    "conflict": "the crew must pull one last job before the vault reopens",
    "stakes": "everyone they love goes to prison if the job fails",
    "time_period": "present day",
    "world_rules": ["the vault reopens once every 90 seconds"],
}

NATIVE_RELATIONSHIPS = [
    {"characters": ["kai", "vex"], "dynamic": "uneasy allies",
     "tension_source": "vex doesn't trust kai's plan", "evolves_to": "trusted partners"},
]

NATIVE_BIBLE = {
    "characters": [{"id": "kai", "costume": "grey jacket", "scenes_present": [1]}],
    "narrative": NATIVE_NARRATIVE,
    "relationships": NATIVE_RELATIONSHIPS,
}


# =============================================================================
# 1. _narrative_context_block — pure rendering
# =============================================================================

class TestNarrativeContextBlock:
    def test_none_bible_is_empty(self):
        assert _narrative_context_block(None) == ""

    def test_bible_with_no_narrative_key_is_empty(self):
        assert _narrative_context_block(LEGACY_BIBLE) == ""

    def test_bible_with_empty_narrative_dict_is_empty(self):
        assert _narrative_context_block({"characters": [], "narrative": {}}) == ""

    def test_narrative_not_a_dict_is_empty(self):
        assert _narrative_context_block({"narrative": "not a dict"}) == ""

    def test_full_narrative_renders_every_field(self):
        block = _narrative_context_block(NATIVE_BIBLE)
        assert block.startswith("<narrative>\n")
        assert block.rstrip().endswith("</relationships>")  # relationships trail narrative
        assert "Genre: heist thriller" in block
        assert "Tone: tense, wry" in block
        assert "Themes: found family, cost of loyalty" in block
        assert "Conflict: the crew must pull one last job before the vault reopens" in block
        assert "Stakes: everyone they love goes to prison if the job fails" in block
        assert "Time period: present day" in block
        assert "World rules: the vault reopens once every 90 seconds" in block
        assert "</narrative>" in block

    def test_partial_narrative_omits_absent_fields(self):
        bible = {"narrative": {"genre": "explainer", "tone": "clinical"}}
        block = _narrative_context_block(bible)
        assert "Genre: explainer" in block
        assert "Tone: clinical" in block
        assert "Themes:" not in block
        assert "Conflict:" not in block
        assert "Stakes:" not in block
        assert "Time period:" not in block
        assert "World rules:" not in block
        assert "<relationships>" not in block  # no relationships key on this bible

    def test_relationships_only_no_narrative_facts_still_empty(self):
        """The D10-2ab generator never produces relationships without
        narrative facts, but this must still fail safe: no narrative lines
        means the whole block (including relationships) is omitted."""
        bible = {"narrative": {}, "relationships": NATIVE_RELATIONSHIPS}
        assert _narrative_context_block(bible) == ""

    def test_relationships_missing_dynamic_or_wrong_pair_count_skipped(self):
        bible = {
            "narrative": {"genre": "drama"},
            "relationships": [
                {"characters": ["a", "b"], "dynamic": ""},  # blank dynamic
                {"characters": ["a"], "dynamic": "solo"},   # only one character
                {"characters": ["a", "b", "c"], "dynamic": "trio"},  # three characters
                "not a dict",
                {"characters": ["a", "b"], "dynamic": "rivals"},  # the only valid one
            ],
        }
        block = _narrative_context_block(bible)
        assert "<relationships>" in block
        assert "a & b: rivals" in block
        assert block.count("\n") == block.count("\n")  # sanity: no crash
        assert "solo" not in block and "trio" not in block

    def test_themes_and_world_rules_filter_falsy_entries(self):
        bible = {"narrative": {"genre": "g", "themes": ["real", "", None],
                               "world_rules": ["", "a real rule"]}}
        block = _narrative_context_block(bible)
        assert "Themes: real" in block
        assert "World rules: a real rule" in block


# =============================================================================
# 2. _board_rules_text_with_narrative — the shared composition helper
# =============================================================================

class TestBoardRulesTextWithNarrative:
    def test_neither_present_is_empty_string(self):
        assert _board_rules_text_with_narrative("", None) == ""
        assert _board_rules_text_with_narrative("", LEGACY_BIBLE) == ""
        assert _board_rules_text_with_narrative("   ", None) == ""

    def test_board_rules_text_alone_passes_through_unchanged(self):
        assert _board_rules_text_with_narrative("Every hatch is human-sized.", LEGACY_BIBLE) == \
            "Every hatch is human-sized."

    def test_narrative_alone_no_board_rules_text(self):
        result = _board_rules_text_with_narrative("", NATIVE_BIBLE)
        assert result.startswith("<narrative>")
        assert "board_quality_rules" not in result  # this helper never adds that tag itself

    def test_narrative_then_board_rules_text_in_that_order(self):
        result = _board_rules_text_with_narrative("Every hatch is human-sized.", NATIVE_BIBLE)
        narrative_idx = result.index("<narrative>")
        rules_idx = result.index("Every hatch is human-sized.")
        assert narrative_idx < rules_idx


# =============================================================================
# 3. _story_bible_narrative_context — the DB read
# =============================================================================

class _StoryBibleColumnDB:
    def __init__(self, story_bible_value, row_exists=True):
        self.story_bible_value = story_bible_value
        self.row_exists = row_exists
        self.calls = 0

    async def fetch_one(self, query, *args):
        assert "SELECT story_bible FROM videos" in query
        self.calls += 1
        if not self.row_exists:
            return None
        return {"story_bible": self.story_bible_value}


def test_narrative_context_column_null():
    db = _StoryBibleColumnDB(None)
    with patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        narrative, relationships = asyncio.run(_story_bible_narrative_context(VIDEO_ID, TENANT_ID))
    assert narrative == {} and relationships == []


def test_narrative_context_row_missing_entirely():
    db = _StoryBibleColumnDB(None, row_exists=False)
    with patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        narrative, relationships = asyncio.run(_story_bible_narrative_context(VIDEO_ID, TENANT_ID))
    assert narrative == {} and relationships == []


def test_narrative_context_legacy_dict_no_new_keys():
    """A pre-D10-2ab story_bible: characters/locations/scene_blocks only."""
    db = _StoryBibleColumnDB({"characters": [], "locations": [], "scene_blocks": []})
    with patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        narrative, relationships = asyncio.run(_story_bible_narrative_context(VIDEO_ID, TENANT_ID))
    assert narrative == {} and relationships == []


def test_narrative_context_unparseable_json_string():
    db = _StoryBibleColumnDB("{not valid json at all")
    with patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        narrative, relationships = asyncio.run(_story_bible_narrative_context(VIDEO_ID, TENANT_ID))
    assert narrative == {} and relationships == []


def test_narrative_context_non_dict_json_string():
    db = _StoryBibleColumnDB("[1, 2, 3]")  # valid JSON, not an object
    with patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        narrative, relationships = asyncio.run(_story_bible_narrative_context(VIDEO_ID, TENANT_ID))
    assert narrative == {} and relationships == []


def test_narrative_context_dict_column_value_with_narrative():
    """asyncpg often hands JSONB columns back already decoded to a dict —
    the non-string branch must work identically to the JSON-string branch."""
    db = _StoryBibleColumnDB({"characters": [], "narrative": NATIVE_NARRATIVE,
                              "relationships": NATIVE_RELATIONSHIPS})
    with patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        narrative, relationships = asyncio.run(_story_bible_narrative_context(VIDEO_ID, TENANT_ID))
    assert narrative == NATIVE_NARRATIVE
    assert relationships == NATIVE_RELATIONSHIPS


def test_narrative_context_json_string_column_value_with_narrative():
    import json
    db = _StoryBibleColumnDB(json.dumps({"characters": [], "narrative": NATIVE_NARRATIVE,
                                         "relationships": NATIVE_RELATIONSHIPS}))
    with patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        narrative, relationships = asyncio.run(_story_bible_narrative_context(VIDEO_ID, TENANT_ID))
    assert narrative == NATIVE_NARRATIVE
    assert relationships == NATIVE_RELATIONSHIPS


def test_narrative_context_narrative_wrong_type_relationships_wrong_type():
    db = _StoryBibleColumnDB({"narrative": "not a dict", "relationships": {"not": "a list"}})
    with patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        narrative, relationships = asyncio.run(_story_bible_narrative_context(VIDEO_ID, TENANT_ID))
    assert narrative == {} and relationships == []


# =============================================================================
# 4. scene_aware_bible — end to end DB wiring
# =============================================================================

class _SceneAwareBibleDB:
    """Dispatches the exact query shapes scene_aware_bible's call chain issues:
    video_characters (load_character_bible), video_environments (_scene_locations),
    and videos.story_bible (both _story_bible_locations' fallback AND the new
    _story_bible_narrative_context — same column, two separate fetches)."""

    def __init__(self, story_bible=None, characters=None, environments=None):
        self.story_bible = story_bible
        self.characters = characters or []
        self.environments = environments or []
        self.story_bible_fetch_count = 0

    async def fetch_all(self, query, *args):
        if "FROM video_characters" in query:
            return self.characters
        if "FROM video_environments" in query:
            return self.environments
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def fetch_one(self, query, *args):
        if "SELECT story_bible FROM videos" in query:
            self.story_bible_fetch_count += 1
            return {"story_bible": self.story_bible} if self.story_bible is not None else None
        raise AssertionError(f"unexpected fetch_one: {query}")


def _run_scene_aware_bible(db):
    scene_rows = [{"scene": 1, "scene_text": "Ryan smiles at the camera."}]
    with patch("scripts.coverage_to_app.fetch_all", db.fetch_all), \
         patch("scripts.coverage_to_app.fetch_one", db.fetch_one):
        return asyncio.run(scene_aware_bible(VIDEO_ID, TENANT_ID, scene_rows))


def test_scene_aware_bible_legacy_video_carries_no_narrative_key():
    db = _SceneAwareBibleDB(
        story_bible=None,
        characters=[{"name": "Ryan", "identity_tag": "black polo", "description": None}],
        environments=[],
    )
    bible = _run_scene_aware_bible(db)
    assert bible is not None
    assert "narrative" not in bible
    assert "relationships" not in bible
    assert bible["characters"][0]["id"] == "Ryan"


def test_scene_aware_bible_native_video_attaches_narrative_and_relationships():
    sb = {"characters": [], "narrative": NATIVE_NARRATIVE, "relationships": NATIVE_RELATIONSHIPS}
    db = _SceneAwareBibleDB(story_bible=sb, characters=[], environments=[])
    bible = _run_scene_aware_bible(db)
    assert bible is not None
    assert bible["narrative"] == NATIVE_NARRATIVE
    assert bible["relationships"] == NATIVE_RELATIONSHIPS


def test_scene_aware_bible_narrative_only_no_longer_collapses_to_none():
    """THE FIX: before D10-3a, a bible with no locked characters and no
    approved/story-bible locations returned None outright. A video whose
    ONLY signal is narrative (no characters recorded yet, no environments)
    must still surface that narrative to the caller."""
    sb = {"narrative": {"genre": "explainer"}}
    db = _SceneAwareBibleDB(story_bible=sb, characters=[], environments=[])
    bible = _run_scene_aware_bible(db)
    assert bible is not None
    assert bible["narrative"] == {"genre": "explainer"}
    assert bible.get("characters") == []
    assert "locations" not in bible


def test_scene_aware_bible_still_none_when_truly_empty():
    """Control: no characters, no locations, no narrative — still None,
    exactly as before this chunk."""
    db = _SceneAwareBibleDB(story_bible=None, characters=[], environments=[])
    bible = _run_scene_aware_bible(db)
    assert bible is None


def test_scene_aware_bible_unparseable_story_bible_json_string_does_not_crash():
    db = _SceneAwareBibleDB(
        story_bible="{not valid json",
        characters=[{"name": "Ryan", "identity_tag": "black polo", "description": None}],
        environments=[],
    )
    bible = _run_scene_aware_bible(db)
    assert bible is not None
    assert "narrative" not in bible


# =============================================================================
# 5. THE BYTE-IDENTICAL PROOF — real storyboard.coverage prompt builders,
#    no mocks, no LLM call (both are pure string functions).
# =============================================================================

class TestByteIdenticalPromptForLegacyBible:
    """generate_coverage_directive's system/user prompts are pure functions of
    their arguments. Both call sites now pass
    board_rules_text=_board_rules_text_with_narrative(board_rules_text, bible)
    instead of board_rules_text=board_rules_text — this proves that
    substitution is a no-op for every bible shape that exists in production
    today (None, a legacy bible with no narrative key, and a bible whose
    story_bible predates D10-2ab)."""

    PROFILE = load_profile({})

    def _system(self, board_rules_text):
        return _coverage_system_prompt(self.PROFILE, 3, 2, 4, board_rules_text=board_rules_text)

    def _user(self, bible):
        return _coverage_user_prompt("A quiet kitchen scene.", "Test Video", bible, [1], [])

    def test_no_board_rules_no_bible(self):
        before_system = self._system("")
        after_system = self._system(_board_rules_text_with_narrative("", None))
        assert after_system == before_system
        assert "<board_quality_rules>" not in after_system
        assert "<narrative>" not in after_system

        before_user = self._user(None)
        after_user = self._user(None)  # story_bible itself is unchanged by this chunk
        assert after_user == before_user

    def test_board_rules_present_legacy_bible(self):
        board_rules_text = "[BQ-1] Every hatch is human-sized."
        before_system = self._system(board_rules_text)
        after_system = self._system(_board_rules_text_with_narrative(board_rules_text, LEGACY_BIBLE))
        assert after_system == before_system
        assert "<narrative>" not in after_system

    def test_legacy_bible_with_only_characters_and_locations(self):
        before_system = self._system("")
        after_system = self._system(_board_rules_text_with_narrative("", LEGACY_BIBLE))
        assert after_system == before_system

        before_user = self._user(LEGACY_BIBLE)
        after_user = self._user(LEGACY_BIBLE)
        assert after_user == before_user
        assert "VISUAL BIBLE" in after_user  # sanity: the bible is still doing its job

    def test_bible_with_empty_narrative_section(self):
        """A bible that HAS the narrative key but every field is empty (a
        degenerate/partial D10-2ab generation) must still render nothing."""
        bible = {**LEGACY_BIBLE, "narrative": {}}
        before_system = self._system("")
        after_system = self._system(_board_rules_text_with_narrative("", bible))
        assert after_system == before_system


# =============================================================================
# 6. Narrative block shape + position inside the REAL system prompt
# =============================================================================

def test_native_bible_injects_narrative_block_into_real_system_prompt():
    profile = load_profile({})
    system = _coverage_system_prompt(
        profile, 3, 2, 4,
        board_rules_text=_board_rules_text_with_narrative("", NATIVE_BIBLE))
    assert "<narrative>" in system and "</narrative>" in system
    assert "Genre: heist thriller" in system
    assert "Tone: tense, wry" in system
    assert "kai & vex: uneasy allies" in system
    # Position: after <channel_style>, before <rules> — reads naturally with
    # the existing context blocks (the SAME slot board_rules_block already
    # occupies today).
    assert system.index("</channel_style>") < system.index("<narrative>") < system.index("<rules>")


def test_native_bible_plus_board_rules_both_present_narrative_first():
    profile = load_profile({})
    system = _coverage_system_prompt(
        profile, 3, 2, 4,
        board_rules_text=_board_rules_text_with_narrative(
            "[BQ-1] Every hatch is human-sized.", NATIVE_BIBLE))
    assert system.index("<narrative>") < system.index("[BQ-1]")
    assert "Every hatch is human-sized." in system


# =============================================================================
# 7. Wiring proof at both real call sites
# =============================================================================

def _video_row(**over):
    base = {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None, "video_model": "grok-imagine",
        "dialogue_audio": "voice_over",
    }
    base.update(over)
    return base


SCENE_TEXT = "The city lights flicker as rain falls onto empty streets."


class _CallSite2DB:
    """generate_coverage_for_video's DB surface, no saved plan for scene 1
    (directive stays None going into the fallback branch this chunk adds)."""

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive_hash" in query and "FROM scripts" in query:
            return None  # no saved plan
        if "FROM assets" in query and "generation_method='coverage'" in query:
            return {"n": 0}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fetch_all(self, query, *args):
        # S7-B added "location, action" to this SELECT's column list —
        # match the shared WHERE clause tail so this fixture is robust to
        # the exact column list, same precedent test_d15_9_directive_gate.py
        # already set for S6-A's own column addition.
        if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
           "AND scene_text IS NOT NULL ORDER BY scene" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT}]
        if "FROM video_characters" in query:
            return [{"reference_url": "https://cast.png/x.png"}]
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def execute(self, query, *args):
        return "OK"


def _call_site_2_patches(db, bible):
    return [
        patch("scripts.coverage_to_app.fetch_one", db.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", db.fetch_all),
        patch("scripts.coverage_to_app.execute", db.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=bible)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.store_scene", AsyncMock(return_value=2)),
        patch("scripts.coverage_to_app.set_scene_board", AsyncMock(return_value=True)),
        patch("scripts.coverage_to_app._write_motion_prompts", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app.populate_characters", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app._reconcile_moment_dialogue", lambda moments, text: None),
        patch("scripts.coverage_to_app.resolve_cast_url", AsyncMock(return_value="https://cast.png/x.png")),
    ]


def test_call_site_2_native_bible_reaches_generate_coverage_directive_with_narrative():
    db = _CallSite2DB()
    directive_mock = AsyncMock(return_value="")  # empty directive: run_coverage still gets called below
    run_coverage_mock = AsyncMock(return_value={"moments": []})
    patches = _call_site_2_patches(db, NATIVE_BIBLE) + [
        patch("scripts.coverage_to_app.generate_coverage_directive", directive_mock),
        patch("scripts.coverage_to_app.run_coverage", run_coverage_mock),
    ]
    for p in patches:
        p.start()
    try:
        asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()
    directive_mock.assert_awaited_once()
    board_rules_text = directive_mock.await_args.kwargs["board_rules_text"]
    assert "<narrative>" in board_rules_text
    assert "Genre: heist thriller" in board_rules_text
    # The precomputed directive (however empty) must reach run_coverage as
    # directive_text — NOT left None for run_coverage to (narrative-blindly)
    # replan internally.
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] == ""


def test_call_site_2_legacy_bible_never_calls_generate_coverage_directive():
    """Byte-identical CONTROL FLOW proof: for a bible with no narrative,
    _narrative_board_text is "" and the new branch never fires — directive
    stays None and run_coverage plans internally exactly as it did before
    this chunk, at this exact code path."""
    db = _CallSite2DB()
    directive_mock = AsyncMock(return_value="should not be called")
    run_coverage_mock = AsyncMock(return_value={"moments": []})
    patches = _call_site_2_patches(db, LEGACY_BIBLE) + [
        patch("scripts.coverage_to_app.generate_coverage_directive", directive_mock),
        patch("scripts.coverage_to_app.run_coverage", run_coverage_mock),
    ]
    for p in patches:
        p.start()
    try:
        asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()
    directive_mock.assert_not_awaited()
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] is None


def test_call_site_2_no_bible_never_calls_generate_coverage_directive():
    db = _CallSite2DB()
    directive_mock = AsyncMock(return_value="should not be called")
    run_coverage_mock = AsyncMock(return_value={"moments": []})
    patches = _call_site_2_patches(db, None) + [
        patch("scripts.coverage_to_app.generate_coverage_directive", directive_mock),
        patch("scripts.coverage_to_app.run_coverage", run_coverage_mock),
    ]
    for p in patches:
        p.start()
    try:
        asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()
    directive_mock.assert_not_awaited()
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] is None


class _CallSite1DB:
    """generate_storyboard_sheet_for_scene's DB surface. The srow SELECT must
    return a truthy dict (an empty/no-plan scene) so the loop reaches the
    generate_coverage_directive call; returning "" from the mocked directive
    makes plan_moments_deterministic("") return None, so the function
    `continue`s immediately after — the image-drawing machinery (ImageClient,
    _draw_board, storage) is never reached, keeping this a $0 pure-wiring
    test."""

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-row-1", "coverage_directive": None, "coverage_directive_hash": None}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fetch_all(self, query, *args):
        # S6-A added a "location" column to this SELECT's column list
        # (scripts.location, migration 144) — match the shared WHERE
        # clause tail so this fixture is robust to the exact column list.
        if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
           "AND scene_text IS NOT NULL ORDER BY scene" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT, "location": None}]
        if "FROM video_characters" in query:
            return [{"reference_url": "https://cast.png/x.png"}]
        raise AssertionError(f"unexpected fetch_all: {query}")


def _call_site_1_patches(db, bible):
    return [
        patch("scripts.coverage_to_app.fetch_one", db.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", db.fetch_all),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=bible)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
    ]


def test_call_site_1_native_bible_reaches_generate_coverage_directive_with_narrative():
    db = _CallSite1DB()
    directive_mock = AsyncMock(return_value="")  # -> no moments -> continue, no drawing
    patches = _call_site_1_patches(db, NATIVE_BIBLE) + [
        patch("scripts.coverage_to_app.generate_coverage_directive", directive_mock),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()
    directive_mock.assert_awaited_once()
    board_rules_text = directive_mock.await_args.kwargs["board_rules_text"]
    assert "<narrative>" in board_rules_text
    assert "Genre: heist thriller" in board_rules_text
    assert result["status"] in ("completed", "failed")  # ran to completion either way, no crash


def test_call_site_1_legacy_bible_board_rules_text_unchanged():
    """quality_rules is stubbed to fail-soft to "" (the `database` module is
    a _boom stub), so board_rules_text starts "" here regardless — this
    proves the wrapper still passes an EMPTY string through for a legacy
    bible, matching today's exact call shape."""
    db = _CallSite1DB()
    directive_mock = AsyncMock(return_value="")
    patches = _call_site_1_patches(db, LEGACY_BIBLE) + [
        patch("scripts.coverage_to_app.generate_coverage_directive", directive_mock),
    ]
    for p in patches:
        p.start()
    try:
        asyncio.run(generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()
    directive_mock.assert_awaited_once()
    assert directive_mock.await_args.kwargs["board_rules_text"] == ""


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
