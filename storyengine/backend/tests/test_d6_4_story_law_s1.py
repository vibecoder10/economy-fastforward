"""D6-4 — STORY-LAWS S1 (narrate every location change) and the honest S4
partial gate (the script is the source of truth for cast).

Local/no-spend: every Claude call is a fake or never reached; every DB call
is a fake execute/fetch_one/fetch_all dispatched by query text, matching the
pattern tests/test_d6_3_story_law_s3.py already uses.

S5 is NOT covered here with its own tests — see STORY-LAWS.md and
story_laws.py's module docstring: D6-4 found S5 already fully satisfied by
D6-3's own check_scene_location_law/no_location tests
(test_d6_3_story_law_s3.py's test_gate_flags_missing_location_hard and
test_gate_all_null_locations_flags_every_scene ARE S5's tests, whether or
not they were labeled that at the time). No duplicate S5 test file exists.

S2 is NOT covered here either — no deterministic check exists for it, by
design (judgement, not a fact any column or text pattern can verify). See
story_laws.py's module docstring and STORY-LAWS.md's status section for the
admission.

Covers:
  - story_laws.check_location_transit_law (S1 GATE, pure, no I/O): the
    canonical location-change detection, the warn-only transit heuristic,
    NULL-safety, a false-positive hunt (four legal narrated transitions),
    and proof the law still catches a genuinely unnarrated jump.
  - story_laws.check_cast_consistency_law (S4 PARTIAL GATE, pure, no I/O):
    both directions (cast-not-named, speaker-not-in-cast), and the real
    open HANDOFF.md case (description-only cast never matching a sheet
    name) as an intentional, admitted limitation.
  - pipeline_executor.resolve_prompt / _run_modeled_script: S1's PROMPT and
    GATE legs ride alongside S3's, warn-only, never block.
  - routes/videos.py update_scene_text: the S1 repair-leg re-check is
    surfaced under its OWN key (story_law_s1_warnings), separate from S3's
    — this is the stash-proof test (see its own docstring).
  - routes/characters.py update_character: the S4 repair-leg re-check.
"""

import asyncio
import json

import story_laws


# ---------------------------------------------------------------------------
# Pure function — check_location_transit_law (the S1 GATE)
# ---------------------------------------------------------------------------

def test_s1_no_change_same_location_produces_nothing():
    scenes = [
        {"scene": 1, "location": "the kitchen", "scene_text": "She chops onions."},
        {"scene": 2, "location": "the kitchen", "scene_text": "She keeps chopping."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result["location_changes"] == []
    assert result["warnings"] == []


def test_s1_has_no_violations_or_passed_key_ever():
    """Structural guarantee: S1 has no hard leg (Ruling 1), so a caller
    must never be able to synthesize a block from this output."""
    scenes = [
        {"scene": 1, "location": "the pod", "scene_text": "She wakes and sits up."},
        {"scene": 2, "location": "the corridor", "scene_text": "She is up and moving fast."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert "violations" not in result
    assert "passed" not in result


def test_s1_location_change_is_always_recorded_as_a_canonical_fact():
    """The location_changes list is populated whenever the CANONICAL
    columns differ, regardless of whether the transit was narrated (that's
    a separate, warn-only question) — this is the 'may be hard, reliable
    fact' half of the split."""
    scenes = [
        {"scene": 1, "location": "the corridor",
         "scene_text": "She leaves the corridor behind and steps onto the bridge."},
        {"scene": 2, "location": "the bridge", "scene_text": "Wind cuts across the open span."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result["location_changes"] == [{
        "from_scene": 1, "to_scene": 2,
        "from_location": "the corridor", "to_location": "the bridge",
    }]
    assert result["warnings"] == [], "narrated via cross-mention — no warning"


def test_s1_null_location_is_skipped_not_crashed_on():
    """NULL-safety: a pre-migration scene (location=None on both sides)
    produces neither a location_change nor a warning — there is no
    canonical data to compare, so S1 stays honestly silent rather than
    guessing."""
    scenes = [
        {"scene": 1, "location": None, "scene_text": "She wakes up."},
        {"scene": 2, "location": None, "scene_text": "She is in the corridor now."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result == {"location_changes": [], "warnings": []}


def test_s1_null_scene_breaks_the_comparison_chain():
    """scene 1 (kitchen) -> scene 2 (NULL) -> scene 3 (kitchen): scene 2's
    missing location must not be silently skipped OVER — scene 3 must not
    be compared back to scene 1 across the gap, since nothing canonical is
    known about what happened during scene 2."""
    scenes = [
        {"scene": 1, "location": "the kitchen", "scene_text": "She chops onions."},
        {"scene": 2, "location": None, "scene_text": "Time passes."},
        {"scene": 3, "location": "the kitchen", "scene_text": "Still chopping."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result["location_changes"] == [], "no comparison should span the NULL gap"
    assert result["warnings"] == []


def test_s1_unnarrated_jump_is_flagged_but_only_as_a_warning():
    """The real, provenance defect this law exists for (STORY-LAWS.md's S1
    entry): 'then she is up and moving' with no sentence for getting out.
    Must be caught — but only as a warning, never a violation."""
    scenes = [
        {"scene": 1, "location": "the sealed room", "scene_text": "She sits, thinking."},
        {"scene": 2, "location": "the corridor", "scene_text": "Then she is up and moving."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert len(result["location_changes"]) == 1
    assert len(result["warnings"]) == 1
    w = result["warnings"][0]
    assert w["reason"] == "unnarrated_location_change"
    assert w["from_scene"] == 1 and w["to_scene"] == 2
    assert w["scene"] == 2


def test_s1_scene_ordering_is_by_scene_number_not_input_order():
    """Robustness: even if the caller's list isn't sorted, the check must
    compare scenes in STORY order, not list order."""
    scenes = [
        {"scene": 2, "location": "the corridor", "scene_text": "She is up and moving."},
        {"scene": 1, "location": "the sealed room", "scene_text": "She sits, thinking."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result["location_changes"] == [{
        "from_scene": 1, "to_scene": 2,
        "from_location": "the sealed room", "to_location": "the corridor",
    }]


def test_s1_case_insensitive_location_names_are_not_a_change():
    scenes = [
        {"scene": 1, "location": "The Garage", "scene_text": "Tools everywhere."},
        {"scene": 2, "location": "the garage", "scene_text": "Still tools."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result["location_changes"] == []
    assert result["warnings"] == []


# --- false-positive hunt: four LEGAL narrated transitions --------------

def test_false_positive_1_transit_narrated_in_outgoing_scene_via_cross_mention():
    scenes = [
        {"scene": 1, "location": "the bedroom",
         "scene_text": "She climbs through the garage window and hides among the tools."},
        {"scene": 2, "location": "the garage", "scene_text": "Tools line the wall."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result["warnings"] == [], "the outgoing scene names the destination — legal, must not warn"


def test_false_positive_2_transit_narrated_in_incoming_scene_via_keyword():
    scenes = [
        {"scene": 1, "location": "the bedroom", "scene_text": "She grabs her coat."},
        {"scene": 2, "location": "the garage",
         "scene_text": "The door creaks open and she steps inside, flicking on the light."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result["warnings"] == [], "a door/steps-inside beat in the incoming scene is a legal transit"


def test_false_positive_3_transit_via_generic_arrival_phrase():
    scenes = [
        {"scene": 1, "location": "the office", "scene_text": "She locks her desk and heads out."},
        {"scene": 2, "location": "the parking lot",
         "scene_text": "Moments later she arrives at her car, keys already in hand."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    assert result["warnings"] == [], "'moments later ... arrives' is a legal, common transit phrasing"


def test_false_positive_4_same_location_scenes_mentioning_a_third_place_never_warn():
    """Two consecutive scenes share a location (no change at all) even
    though one of them happens to mention a THIRD scene's location — S1
    only ever compares ADJACENT scenes' own location columns, so this must
    never be mistaken for an unnarrated jump between scenes 1 and 2."""
    scenes = [
        {"scene": 1, "location": "the kitchen",
         "scene_text": "She thinks about the attic, how long it's been since she went up there."},
        {"scene": 2, "location": "the kitchen", "scene_text": "She sets the kettle on."},
        {"scene": 3, "location": "the attic", "scene_text": "Dust motes drift in the light."},
    ]
    result = story_laws.check_location_transit_law(scenes)
    # Only the real change (2 -> 3) is even considered; scene 1's mention
    # of "the attic" is irrelevant to the 1->2 pair since there IS no
    # location change there.
    assert all(c["from_scene"] != 1 for c in result["location_changes"])


def test_s4_narration_starting_with_capitalized_word_and_colon_is_not_a_speaker():
    """LIVE-FOUND false positive (read-only run against video 686b4651's
    real scene 3 text): a first cut of the speaker-tag regex only required
    the FIRST word to be capitalized, so 'Then Nyla finds it: a lens
    hidden in her ceiling...' — ordinary narration with a colon in the
    middle — was misread as a speaker named 'Then Nyla finds it'. Fixed by
    requiring EVERY word in the tag to be Title Case; this is the
    regression test."""
    scenes = [{"scene": 3, "scene_text":
               "Then Nyla finds it: a lens hidden in her ceiling, small and patient."}]
    result = story_laws.check_cast_consistency_law(scenes, [{"name": "Nyla"}])
    assert result["warnings"] == [], "must not invent a speaker from mid-sentence narration"


# ---------------------------------------------------------------------------
# Pure function — check_cast_consistency_law (the S4 PARTIAL GATE)
# ---------------------------------------------------------------------------

def test_s4_exact_speaker_match_no_warning():
    scenes = [{"scene": 1, "scene_text": "Mum: Where are you going?\nHe grabs his coat."}]
    cast = [{"name": "Mum"}, {"name": "He"}]
    result = story_laws.check_cast_consistency_law(scenes, cast)
    assert result["warnings"] == []


def test_s4_narration_only_mention_no_warning():
    """A cast name doesn't need a dialogue tag — plain narration naming the
    character is enough to count as 'named in the script'."""
    scenes = [{"scene": 1, "scene_text": "Tom walks into the garage and finds Sara waiting."}]
    cast = [{"name": "Tom"}, {"name": "Sara"}]
    result = story_laws.check_cast_consistency_law(scenes, cast)
    assert result["warnings"] == []


def test_s4_cast_never_named_in_script_flags_warning():
    scenes = [{"scene": 1, "scene_text": "A figure watches from the doorway, saying nothing."}]
    cast = [{"name": "Elder Mara"}]
    result = story_laws.check_cast_consistency_law(scenes, cast)
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["reason"] == "cast_not_named_in_script"
    assert result["warnings"][0]["name"] == "Elder Mara"


def test_s4_speaker_with_no_cast_sheet_flags_warning():
    scenes = [{"scene": 1, "scene_text": "Zeke: We have to go now."}]
    cast = [{"name": "Mara"}]
    result = story_laws.check_cast_consistency_law(scenes, cast)
    reasons = {w["reason"] for w in result["warnings"]}
    assert "speaker_not_in_cast" in reasons
    zeke = [w for w in result["warnings"] if w["name"] == "Zeke"][0]
    assert zeke["reason"] == "speaker_not_in_cast"


def test_s4_open_handoff_case_description_only_cast_flags_but_does_not_resolve():
    """The exact real, still-open case from HANDOFF.md/STORY-LAWS.md: the
    script says 'a woman in gold' and 'an old man', the board cast three
    named navy-suited elders. This function must flag the mismatch (each
    named elder never appears in the script's words) — and must NOT
    contain any verdict about which side is canonical; that's Ryan's call."""
    scenes = [{"scene": 1, "scene_text":
               "A woman in gold steps forward. An old man watches from behind her."}]
    cast = [{"name": "Elder Kessa"}, {"name": "Elder Bram"}, {"name": "Elder Iyo"}]
    result = story_laws.check_cast_consistency_law(scenes, cast)
    flagged_names = {w["name"] for w in result["warnings"]
                      if w["reason"] == "cast_not_named_in_script"}
    assert flagged_names == {"Elder Kessa", "Elder Bram", "Elder Iyo"}
    assert "passed" not in result and "violations" not in result


def test_s4_has_no_violations_or_passed_key_ever():
    result = story_laws.check_cast_consistency_law(
        [{"scene": 1, "scene_text": "Nobody speaks."}], [{"name": "Ghost"}],
    )
    assert "violations" not in result
    assert "passed" not in result


def test_s4_short_two_letter_name_is_still_checked():
    scenes = [{"scene": 1, "scene_text": "Al: Let's move."}]
    cast = [{"name": "Al"}]
    result = story_laws.check_cast_consistency_law(scenes, cast)
    assert result["warnings"] == []


def test_s4_empty_cast_and_script_produce_nothing():
    assert story_laws.check_cast_consistency_law([], []) == {"warnings": []}


# ---------------------------------------------------------------------------
# resolve_prompt / _run_modeled_script — S1 rides along with S3, warn-only
# ---------------------------------------------------------------------------

def test_resolve_prompt_appends_transit_law_alongside_scene_law():
    import pipeline_executor as pe
    from identity import IdentityContext

    identity = IdentityContext(
        channel_name="Test Channel", niche="cooking", target_audience="home cooks",
        voice_style="warm", visual_style="bright", frameworks=[],
    )
    resolved = pe.resolve_prompt(None, None, "script", identity)
    assert story_laws.SCENE_LOCATION_LAW in resolved
    assert story_laws.LOCATION_TRANSIT_LAW in resolved


def test_resolve_prompt_does_not_leak_transit_law_into_other_prompt_keys():
    import pipeline_executor as pe
    from identity import IdentityContext

    identity = IdentityContext(
        channel_name="Test Channel", niche="cooking", target_audience="home cooks",
        voice_style="warm", visual_style="bright", frameworks=[],
    )
    resolved = pe.resolve_prompt(None, None, "thumbnail", identity)
    assert resolved is None or story_laws.LOCATION_TRANSIT_LAW not in resolved


class _FakeAnthropicModeled:
    def __init__(self, raw):
        self.raw = raw
        self.captured_prompts = []

    async def generate(self, **kwargs):
        self.captured_prompts.append(kwargs.get("prompt"))
        return self.raw


def _modeled_video(**overrides):
    video = {
        "id": "video-1", "video_title": "Modeled Video", "status": "ready_for_scripting",
        "source": "modeled", "script_system_prompt": "Write like the reference.",
        "video_length_minutes": 3, "original_dna": None, "writer_guidance": "",
        "research_payload": None,
    }
    video.update(overrides)
    return video


def test_modeled_prompt_includes_transit_law(monkeypatch):
    import pipeline_executor as pe

    fake = _FakeAnthropicModeled(
        "@@@SCENE 1@@@\nLOCATION: the garage\nShe opens the hatch.\n"
        "@@@SCENE 2@@@\nLOCATION: the corridor\nShe runs down the hall.\n"
        "@@@SCENE 3@@@\nLOCATION: the lakeside dock\nThe boat is gone.\n"
    )
    video = _modeled_video()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": fake})()

    async def fake_execute(query, *args):
        return None

    async def fake_log_activity(*_a, **_k):
        return None

    async def fake_log_transition(*_a, **_k):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    executor._log_activity = fake_log_activity
    executor._log_transition = fake_log_transition

    asyncio.run(executor._run_modeled_script("video-1", video))
    assert any(story_laws.LOCATION_TRANSIT_LAW in (p or "") for p in fake.captured_prompts)


def test_run_modeled_script_logs_s1_warning_without_blocking(monkeypatch):
    """A script that passes S3 (every scene has a location) but has an
    unnarrated jump between two of them must still reach 'ready_for_voice'
    — S1 logs an advisory, never a needs_review."""
    import pipeline_executor as pe

    raw = (
        "@@@SCENE 1@@@\nLOCATION: the sealed room\nShe sits, thinking.\n"
        "@@@SCENE 2@@@\nLOCATION: the corridor\nThen she is up and moving.\n"
    )
    video = _modeled_video(video_length_minutes=1)
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (), {"anthropic": _FakeAnthropicModeled(raw)}
    )()

    writes = []
    logs = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_log_activity(_bot, _vid, _status, message):
        logs.append(message)

    async def fake_log_transition(*_a, **_k):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    executor._log_activity = fake_log_activity
    executor._log_transition = fake_log_transition

    result = asyncio.run(executor._run_modeled_script("video-1", video))

    assert result["status"] == "ready_for_voice", "S1 must never block generation"
    assert any("Story law S1 advisory" in m for m in logs)


# ---------------------------------------------------------------------------
# routes/videos.py update_scene_text — S1 repair leg, its OWN response key
# ---------------------------------------------------------------------------

def test_update_scene_text_surfaces_s1_warning_under_its_own_key(monkeypatch):
    """STASH-PROOF: with this D6-4 change reverted (story_laws has no
    check_location_transit_law, routes/videos.py never calls it), this
    exact test fails on an ASSERTION — `result.get("story_law_s1_warnings")`
    is `None` on old code (the key doesn't exist at all), not equal to the
    non-empty list asserted below. This is a real behavioral difference,
    not an import/collection-time failure."""
    import routes.videos as rv
    from models import SceneTextUpdate

    async def fake_execute(query, *args):
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        return [
            {"scene": 1, "location": "the sealed room", "scene_text": "She sits, thinking."},
            {"scene": 2, "location": "the corridor", "scene_text": "Then she is up and moving."},
        ]

    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    # Editing scene 1 (the OUTGOING half of the pair) must still surface
    # the warning — proves the from_scene/to_scene filter, not just "scene".
    result = asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text="She sits, thinking."),
        tenant_id="tenant-1",
    ))

    s1_warnings = result.get("story_law_s1_warnings")
    assert s1_warnings, "expected a non-empty S1 warning list, got: %r" % (s1_warnings,)
    assert "corridor" in s1_warnings[0] or "sealed room" in s1_warnings[0]
    # S3's own key must be unaffected — no behavior change for existing callers.
    assert result["story_law_s3_warnings"] == []


def test_update_scene_text_no_s1_warning_when_narrated(monkeypatch):
    import routes.videos as rv
    from models import SceneTextUpdate

    async def fake_execute(query, *args):
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        return [
            {"scene": 1, "location": "the corridor",
             "scene_text": "She leaves the corridor behind and steps onto the bridge."},
            {"scene": 2, "location": "the bridge", "scene_text": "Wind cuts across the span."},
        ]

    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    result = asyncio.run(rv.update_scene_text(
        "video-1", 1,
        SceneTextUpdate(text="She leaves the corridor behind and steps onto the bridge."),
        tenant_id="tenant-1",
    ))
    assert result["story_law_s1_warnings"] == []


# ---------------------------------------------------------------------------
# routes/characters.py update_character — S4 repair leg
# ---------------------------------------------------------------------------

def test_update_character_surfaces_s4_warning_on_name_edit(monkeypatch):
    import routes.characters as rc
    from routes.characters import CharacterUpdate

    async def fake_fetch_one(query, *args):
        return {
            "id": "char-1", "video_id": "video-1", "tenant_id": "tenant-1",
            "name": "Elder Kessa", "description": None, "reference_url": None,
            "status": "draft", "source": "generated", "identity_tag": None,
        }

    calls = {"n": 0}

    async def fake_fetch_all(query, *args):
        calls["n"] += 1
        if "scripts" in query:
            return [{"scene_text": "A woman in gold steps forward."}]
        return [{"name": "Elder Kessa"}]

    monkeypatch.setattr(rc, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rc, "fetch_all", fake_fetch_all)

    result = asyncio.run(rc.update_character(
        "video-1", "char-1", CharacterUpdate(name="Elder Kessa"), tenant_id="tenant-1",
    ))
    assert result.get("story_law_s4_warnings"), "renamed cast member never named in script must warn"


def test_update_character_no_s4_check_when_name_not_edited(monkeypatch):
    """Only a name edit triggers the re-check — editing description alone
    doesn't change what the consistency check compares, so it's skipped
    (cheap, but not free; no reason to run it on every unrelated edit)."""
    import routes.characters as rc
    from routes.characters import CharacterUpdate

    async def fake_fetch_one(query, *args):
        return {
            "id": "char-1", "video_id": "video-1", "tenant_id": "tenant-1",
            "name": "Elder Kessa", "description": "New description", "reference_url": None,
            "status": "draft", "source": "generated", "identity_tag": None,
        }

    async def boom(*_a, **_k):
        raise AssertionError("fetch_all must not be called when name isn't edited")

    monkeypatch.setattr(rc, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(rc, "fetch_all", boom)

    result = asyncio.run(rc.update_character(
        "video-1", "char-1", CharacterUpdate(description="New description"),
        tenant_id="tenant-1",
    ))
    assert "story_law_s4_warnings" not in result
