"""D6-3 — STORY-LAWS S3 (one scene is one location and one continuous beat).

Local/no-spend: every Claude call is a fake or never reached; every DB call
is a fake execute/fetch_one/fetch_all dispatched by query text, matching the
pattern tests/test_c46a_quality_critic_wiring.py and
tests/test_machine_documentary_hold.py already use.

Covers:
  - story_laws.py pure functions (extract/parse/check) — no DB, no LLM.
  - resolve_prompt appends SCENE_LOCATION_LAW for "script" only, riding on
    top of any override the same way standing_preferences does.
  - supabase_adapter.create_script_record extracts + strips the header
    (path a's DB choke point).
  - user_script.py: set_user_script is READ-ONLY + WARN-ONLY (verbatim text
    is never altered, a violation never blocks); accept_external_script
    HARD-REJECTS a missing/cross-contaminated location before the paid
    critic call, and accepts an explicit structured "location" field.
  - pipeline_executor._run_modeled_script: the S3 gate rejects BEFORE any
    DB write on violation, and a passing script's INSERT carries location.
  - routes/videos.py update_scene_text / rewrite_scene_text: an edit or a
    regenerate never drops the scene's existing location.
"""

import asyncio
import json

import story_laws


# ---------------------------------------------------------------------------
# Pure functions — extract_scene_location / parse_scene_location
# ---------------------------------------------------------------------------

def test_extract_scene_location_header_present():
    text = "LOCATION: the garage\n\nShe wakes up and reaches for the light."
    location, remaining = story_laws.extract_scene_location(text)
    assert location == "the garage"
    assert remaining == "She wakes up and reaches for the light."
    assert "LOCATION" not in remaining


def test_extract_scene_location_no_header_returns_original_untouched():
    text = "She wakes up and reaches for the light."
    location, remaining = story_laws.extract_scene_location(text)
    assert location is None
    assert remaining == text  # byte-for-byte, not just equal-looking


def test_extract_scene_location_header_must_be_first_nonblank_line():
    # A "LOCATION:" mention mid-narration is NOT the header.
    text = "She wakes up.\nLOCATION: the garage\nAnd runs."
    location, remaining = story_laws.extract_scene_location(text)
    assert location is None
    assert remaining == text


def test_extract_scene_location_skips_leading_blank_lines():
    text = "\n\nLOCATION: the lakeside dock\n\nThe boat is gone."
    location, remaining = story_laws.extract_scene_location(text)
    assert location == "the lakeside dock"
    assert remaining == "The boat is gone."


def test_extract_scene_location_empty_text():
    assert story_laws.extract_scene_location("") == (None, "")
    assert story_laws.extract_scene_location(None) == (None, "")


def test_parse_scene_location_never_touches_text():
    text = "LOCATION: the garage\n\nShe wakes up."
    assert story_laws.parse_scene_location(text) == "the garage"
    # parse_scene_location has no second return value — nothing to mutate.


# ---------------------------------------------------------------------------
# Pure function — check_scene_location_law (the GATE)
#
# D6-3b ruling (independent verifier, live-tested): the declared `location`
# is a COLUMN — canonical — so `no_location` MAY be hard (goes in
# `violations`, `passed=False`). `cross_location_text` compares PROSE to
# PROSE — never canonical — so it WARNS ONLY, permanently, and NEVER affects
# `passed`. This resolves a real conflict with S1 (NARRATE EVERY LOCATION
# CHANGE), which requires an outgoing scene's text to name the destination.
# ---------------------------------------------------------------------------

def test_gate_passes_clean_single_location_scenes():
    scenes = [
        {"scene": 1, "location": "the garage", "scene_text": "She opens the hatch."},
        {"scene": 2, "location": "the corridor", "scene_text": "She runs down the hall."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result == {"passed": True, "violations": [], "warnings": []}


def test_gate_flags_missing_location_hard():
    scenes = [{"scene": 1, "location": None, "scene_text": "She wakes up."}]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is False
    assert result["violations"] == [{
        "scene": 1, "reason": "no_location",
        "detail": "Scene has no LOCATION header — cannot verify it holds a single location.",
    }]
    assert result["warnings"] == []


def test_gate_flags_blank_string_location_same_as_missing():
    scenes = [{"scene": 1, "location": "   ", "scene_text": "She wakes up."}]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is False
    assert result["violations"][0]["reason"] == "no_location"


def test_gate_all_null_locations_flags_every_scene():
    """The exact shape of a pre-migration video: every row has location=NULL.
    This is the decisive proof against video 686b4651 — see the D6-3 report
    for the real read-only run against that video's actual scene 1 text."""
    scenes = [
        {"scene": i, "location": None, "scene_text": f"scene {i} text"}
        for i in range(1, 7)
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is False
    assert len(result["violations"]) == 6
    assert result["violations"][0]["scene"] == 1
    assert result["violations"][0]["reason"] == "no_location"


def test_gate_short_location_names_not_used_for_cross_match():
    # "a", "in" etc are too short/generic to match on safely (len < 3 skip).
    scenes = [
        {"scene": 1, "location": "in", "scene_text": "Nothing unusual happens in here."},
        {"scene": 2, "location": "the attic", "scene_text": "Dust everywhere."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    # scene 1 has a location (not flagged as no_location) and "in" is too
    # short to search for as a cross-contamination signal.
    assert result["passed"] is True
    assert result["warnings"] == []


# --- cross_location_text: WARN-ONLY, never blocks (still gets caught) ------

def test_gate_still_catches_a_genuinely_oversized_two_location_scene_as_warning():
    """The failure mode of the warn-only ruling is defanging the law
    entirely. Prove it: a real two-location scene (both declared, one
    scene's text genuinely naming the OTHER scene's place) still shows up
    in `warnings` — detected, visible, just not blocking."""
    scenes = [
        {"scene": 1, "location": "the bedroom",
         "scene_text": "She wakes up, hesitates, then climbs through the garage window and hides among the tools."},
        {"scene": 2, "location": "the garage", "scene_text": "Tools line the wall."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is True  # never blocks
    assert result["violations"] == []
    assert result["warnings"] == [{
        "scene": 1, "reason": "cross_location_text",
        "detail": (
            "Scene declares 'the bedroom' and its text also names the garage — "
            "another scene's location. This is advisory only: mentioning, "
            "remembering, or narrating a move to another place is legal (and "
            "S1 requires it for an outgoing scene) — review, don't assume a "
            "violation."
        ),
    }]


# --- the five live false-positive inputs from the independent verifier -----

def test_false_positive_1_dialogue_naming_elsewhere_never_blocks():
    scenes = [
        {"scene": 1, "location": "the rooftop",
         "scene_text": '"I grew up in the corridor," she says, staring at the skyline.'},
        {"scene": 2, "location": "the corridor", "scene_text": "Pipes hiss along the ceiling."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is True
    assert result["violations"] == []
    assert any(w["scene"] == 1 for w in result["warnings"])  # caught, not blocked


def test_false_positive_2_memory_naming_elsewhere_never_blocks():
    scenes = [
        {"scene": 1, "location": "the rooftop",
         "scene_text": "She thinks about the surface, how far below it always felt."},
        {"scene": 2, "location": "the surface", "scene_text": "Rain hits the concrete."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is True
    assert result["violations"] == []


def test_false_positive_3_looking_through_window_never_blocks():
    """Legal per BOARD-LAWS L11 (establish through a window/POV)."""
    scenes = [
        {"scene": 1, "location": "the rooftop",
         "scene_text": "Through the glass she can see the corridor below, lit and empty."},
        {"scene": 2, "location": "the corridor", "scene_text": "Pipes hiss along the ceiling."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is True
    assert result["violations"] == []


def test_false_positive_4_substring_collision_pod_bay_never_flags():
    """"the pod bay" (this scene's OWN longer location) must not trip on a
    sibling's shorter "the pod" — the fixed matcher must not flag this at
    all, not merely downgrade it to a warning."""
    scenes = [
        {"scene": 1, "location": "the pod bay", "scene_text": "Rows of pods line the bay walls."},
        {"scene": 2, "location": "the pod", "scene_text": "She wakes inside."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is True
    assert result["violations"] == []
    assert result["warnings"] == [], "own longer location name must not be shadowed by a sibling's shorter prefix"


def test_false_positive_4b_substring_collision_diner_parking_lot_never_flags():
    scenes = [
        {"scene": 1, "location": "Diner Parking Lot", "scene_text": "She leans on the hood of the car."},
        {"scene": 2, "location": "Diner", "scene_text": "The bell over the door rings."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is True
    assert result["warnings"] == []


def test_false_positive_5_s1_s3_tension_never_blocks():
    """The decisive case: S1 REQUIRES this exact sentence (narrate the
    location change). It legitimately names the destination scene's
    location. Must warn, never block — resolves the S1/S3 conflict in
    S1's favor."""
    scenes = [
        {"scene": 1, "location": "the corridor",
         "scene_text": "She leaves the corridor behind and steps onto the bridge."},
        {"scene": 2, "location": "the bridge", "scene_text": "Wind cuts across the open span."},
    ]
    result = story_laws.check_scene_location_law(scenes)
    assert result["passed"] is True
    assert result["violations"] == []
    assert any(w["scene"] == 1 and "bridge" in w["detail"] for w in result["warnings"])


# ---------------------------------------------------------------------------
# resolve_prompt — S3 rides along every resolved "script" prompt
# ---------------------------------------------------------------------------

def test_resolve_prompt_appends_law_for_script_key_neutral():
    import pipeline_executor as pe
    from identity import IdentityContext

    identity = IdentityContext(
        channel_name="Test Channel", niche="cooking", target_audience="home cooks",
        voice_style="warm", visual_style="bright", frameworks=[],
    )
    resolved = pe.resolve_prompt(None, None, "script", identity)
    assert story_laws.SCENE_LOCATION_LAW in resolved


def test_resolve_prompt_appends_law_even_with_tenant_and_per_video_override():
    """The Phase-1 invariant is a tenant override still wins outright — but
    S3 must ride on top of it the same way standing_preferences does, or a
    customized channel silently opts out of the law."""
    import pipeline_executor as pe
    from identity import IdentityContext

    identity = IdentityContext(
        channel_name="Test Channel", niche="cooking", target_audience="home cooks",
        voice_style="warm", visual_style="bright", frameworks=[],
    )
    per_video = "Write exactly like a 1990s cooking show host."
    resolved = pe.resolve_prompt(per_video, "some tenant override", "script", identity)
    assert resolved.startswith(per_video)
    assert story_laws.SCENE_LOCATION_LAW in resolved


def test_resolve_prompt_does_not_leak_law_into_other_prompt_keys():
    import pipeline_executor as pe
    from identity import IdentityContext

    identity = IdentityContext(
        channel_name="Test Channel", niche="cooking", target_audience="home cooks",
        voice_style="warm", visual_style="bright", frameworks=[],
    )
    resolved = pe.resolve_prompt(None, None, "thumbnail", identity)
    assert resolved is None or story_laws.SCENE_LOCATION_LAW not in resolved


# ---------------------------------------------------------------------------
# supabase_adapter.create_script_record — path (a) DB choke point
# ---------------------------------------------------------------------------

def test_create_script_record_extracts_and_strips_location(monkeypatch):
    import supabase_adapter as sa

    captured = {}

    def fake_fetch_one(query, params):
        return {"id": "video-1", "tenant_id": "tenant-1"}

    def fake_execute(query, params):
        captured["query"] = query
        captured["params"] = params

    monkeypatch.setattr(sa, "_fetch_one", fake_fetch_one)
    monkeypatch.setattr(sa, "_execute", fake_execute)

    adapter = sa.SupabaseAdapter.__new__(sa.SupabaseAdapter)
    adapter.tenant_id = "tenant-1"
    adapter.current_video_id = "video-1"
    adapter._tw = lambda *_a, **_k: ("", [])

    result = adapter.create_script_record(
        scene_number=1,
        scene_text="LOCATION: the garage\n\nShe opens the hatch.",
        title="Test Video",
    )

    assert "location" in captured["query"]
    # params: (script_id, tenant_id, video_id, scene_number, stored_text, location, title, ...)
    assert captured["params"][4] == "She opens the hatch."
    assert captured["params"][5] == "the garage"
    assert result["Scene text"] == "She opens the hatch."


def test_create_script_record_no_header_is_a_clean_noop(monkeypatch):
    import supabase_adapter as sa

    captured = {}

    def fake_fetch_one(query, params):
        return {"id": "video-1", "tenant_id": "tenant-1"}

    def fake_execute(query, params):
        captured["params"] = params

    monkeypatch.setattr(sa, "_fetch_one", fake_fetch_one)
    monkeypatch.setattr(sa, "_execute", fake_execute)

    adapter = sa.SupabaseAdapter.__new__(sa.SupabaseAdapter)
    adapter.tenant_id = "tenant-1"
    adapter.current_video_id = "video-1"
    adapter._tw = lambda *_a, **_k: ("", [])

    adapter.create_script_record(scene_number=1, scene_text="Plain narration, no header.", title="T")
    assert captured["params"][4] == "Plain narration, no header."
    assert captured["params"][5] is None


# ---------------------------------------------------------------------------
# user_script.py — SUBMIT path (creator-verbatim vs agent-submitted)
# ---------------------------------------------------------------------------

def test_set_user_script_never_alters_text_even_with_header(monkeypatch):
    import user_script

    writes = []

    async def fake_fetch_one(query, *args):
        return {"id": "video-1", "tenant_id": "tenant-1", "video_title": "T", "status": "ready_for_scripting"}

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_tag(*_a, **_k):
        return {}

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr("dialogue_intelligence.tag_video_dialogue", fake_tag, raising=False)

    # A creator's script that HAPPENS to include the header — verbatim
    # contract means it must survive completely unchanged in scene_text.
    creator_text = "LOCATION: the garage\n\nThis is my own story, word for word."
    result = asyncio.run(user_script.set_user_script("tenant-1", "video-1", creator_text))

    assert result["scenes"] == 1
    inserts = [w for w in writes if "INSERT INTO scripts" in w[0]]
    assert len(inserts) == 1
    # scene_text param position: (tenant_id, video_id, i, text, location, title, voice_id)
    stored_text = inserts[0][1][3]
    assert stored_text == creator_text.strip(), "verbatim text must be byte-for-byte unchanged"
    stored_location = inserts[0][1][4]
    assert stored_location == "the garage"


def test_set_user_script_never_blocks_on_missing_location(monkeypatch):
    """WARN-ONLY: a creator's plain prose (no header, most common case) has
    location=None on every scene — the gate would fail S3, but this path
    must still succeed (creator's word is final)."""
    import user_script

    async def fake_fetch_one(query, *args):
        return {"id": "video-1", "tenant_id": "tenant-1", "video_title": "T", "status": "ready_for_scripting"}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_tag(*_a, **_k):
        return {}

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr("dialogue_intelligence.tag_video_dialogue", fake_tag, raising=False)

    result = asyncio.run(user_script.set_user_script(
        "tenant-1", "video-1",
        "Just an ordinary creator paragraph with no machine headers in it at all, "
        "long enough to form its own scene on the paragraph splitter.",
    ))
    assert result["scenes"] >= 1  # succeeded, not raised/blocked

    validation_writes = [w for w in writes if "script_validation" in w[0]]
    saved = json.loads(validation_writes[0][1][1])
    assert saved["passed"] is True, "S3 violations are advisory — must never flip passed"
    assert saved["story_law_s3"]["passed"] is False
    assert saved["story_law_s3"]["advisory"] is True


def test_accept_external_script_rejects_missing_location(monkeypatch):
    import user_script

    async def fake_fetch_one(query, *args):
        return {"id": "video-1", "tenant_id": "tenant-1", "video_title": "T"}

    async def boom(*_a, **_k):
        raise AssertionError("the paid critic must never be called after an S3 reject")

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    import script_quality
    monkeypatch.setattr(script_quality, "critique_script", boom)

    result = asyncio.run(user_script.accept_external_script(
        "tenant-1", "video-1", [{"text": "No location field and no header either."}],
        source="agent_submitted",
    ))
    assert result["accepted"] is False
    assert result["verdict"] == "story_law_s3_violation"
    assert "scene 1" in result["violations"][0]


def test_accept_external_script_accepts_explicit_location_field(monkeypatch):
    import user_script

    async def fake_fetch_one(query, *args):
        return {"id": "video-1", "tenant_id": "tenant-1", "video_title": "T",
                "executive_hook": None, "hook_script": None}

    class _Grade:
        needs_revision = False
        verdict = "pass"
        score = 90
        failing_gates = []
        violations = []
        rule_verdicts = []

    async def fake_critique(*_a, **_k):
        return _Grade()

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_tag(*_a, **_k):
        return {}

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    import script_quality
    monkeypatch.setattr(script_quality, "critique_script", fake_critique)
    monkeypatch.setattr("dialogue_intelligence.tag_video_dialogue", fake_tag, raising=False)
    monkeypatch.setattr("kie_unified.get_text_client_for_tenant", fake_tag, raising=False)
    monkeypatch.setattr("identity.build_identity_context",
                         lambda *_a, **_k: asyncio.sleep(0, result=type("I", (), {"niche": ""})()),
                         raising=False)
    import quality_rules
    monkeypatch.setattr(quality_rules, "list_all_rules", fake_tag, raising=False)

    result = asyncio.run(user_script.accept_external_script(
        "tenant-1", "video-1",
        [{"text": "She opens the hatch and climbs through.", "location": "the garage"}],
        source="agent_submitted",
    ))
    assert result["accepted"] is True
    inserts = [w for w in writes if "INSERT INTO scripts" in w[0]]
    assert len(inserts) == 1
    # params: (tenant_id, video_id, scene, text, location, title, voice_id)
    assert inserts[0][1][4] == "the garage"


# ---------------------------------------------------------------------------
# pipeline_executor._run_modeled_script — path (b), gate before any write
# ---------------------------------------------------------------------------

class _FakeAnthropicModeled:
    def __init__(self, raw):
        self.raw = raw

    async def generate(self, **_kwargs):
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


def test_run_modeled_script_rejects_before_any_write_on_violation(monkeypatch):
    import pipeline_executor as pe

    raw = (
        "@@@SCENE 1@@@\nNo location header here at all, just narration text.\n"
        "@@@SCENE 2@@@\nNor here either, still just narration text.\n"
    )
    video = _modeled_video(video_length_minutes=1)
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": _FakeAnthropicModeled(raw)})()

    writes = []

    async def fake_execute(query, *args):
        writes.append(query)
        return None

    async def fake_log_activity(*_a, **_k):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    executor._log_activity = fake_log_activity

    result = asyncio.run(executor._run_modeled_script("video-1", video))

    assert result["status"] == "needs_review"
    assert not writes, "a failing S3 gate must write NOTHING — no UPDATE, no INSERT, no DELETE"


def test_run_modeled_script_passing_scenes_insert_location(monkeypatch):
    import pipeline_executor as pe

    raw = (
        "@@@SCENE 1@@@\nLOCATION: the garage\nShe opens the hatch.\n"
        "@@@SCENE 2@@@\nLOCATION: the corridor\nShe runs down the hall.\n"
        "@@@SCENE 3@@@\nLOCATION: the lakeside dock\nThe boat is gone.\n"
    )
    video = _modeled_video()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": _FakeAnthropicModeled(raw)})()

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    async def fake_log_activity(*_a, **_k):
        return None

    async def fake_log_transition(*_a, **_k):
        return None

    monkeypatch.setattr(pe, "execute", fake_execute)
    executor._log_activity = fake_log_activity
    executor._log_transition = fake_log_transition

    result = asyncio.run(executor._run_modeled_script("video-1", video))

    assert result["status"] == "ready_for_voice"
    inserts = [w for w in writes if "INSERT INTO scripts" in w[0]]
    assert len(inserts) == 3
    # params: (tenant_id, video_id, i, text, location, title, voice_id)
    assert inserts[0][1][4] == "the garage"
    assert "LOCATION" not in inserts[0][1][3], "the header must never reach spoken scene_text"
    assert inserts[1][1][4] == "the corridor"
    assert inserts[2][1][4] == "the lakeside dock"


# ---------------------------------------------------------------------------
# routes/videos.py — repair leg: edits/regenerations must not drop location
# ---------------------------------------------------------------------------

def test_update_scene_text_preserves_existing_location_when_no_new_header(monkeypatch):
    import routes.videos as rv
    from models import SceneTextUpdate

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        return [{"scene": 1, "location": "the kitchen", "scene_text": "Just an edited paragraph, no header."}]

    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    result = asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text="Just an edited paragraph, no header."),
        tenant_id="tenant-1",
    ))

    # D7-1 added a second execute() call (the videos.script sync) — pick out
    # the scripts.scene_text write specifically rather than assuming it's
    # the only (or last) call.
    scene_write = next(query_args for query_args in calls if "COALESCE" in query_args[0])
    assert "COALESCE" in scene_write[0]
    # args: (stored_text, video_id, scene, tenant_id, new_location)
    assert scene_write[1][4] is None, "no new header -> COALESCE keeps the existing column untouched"
    assert result["story_law_s3_warnings"] == []
    # D7-1: the sync write must ALSO have happened — videos.script kept
    # current with the edit, not just scripts.scene_text.
    sync_write = next(query_args for query_args in calls if "UPDATE videos SET script" in query_args[0])
    assert "Just an edited paragraph, no header." in sync_write[1][2]


def test_update_scene_text_adopts_fresh_header_and_strips_it(monkeypatch):
    import routes.videos as rv
    from models import SceneTextUpdate

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        return [{"scene": 1, "location": "the kitchen", "scene_text": "She chops onions."}]

    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text="LOCATION: the kitchen\n\nShe chops onions."),
        tenant_id="tenant-1",
    ))

    # D7-1 added a second execute() call (the videos.script sync) — pick out
    # the scripts.scene_text write specifically rather than assuming it's
    # the only call.
    scene_write = next(query_args for query_args in calls if "COALESCE" in query_args[0])
    assert scene_write[1][0] == "She chops onions."
    assert scene_write[1][4] == "the kitchen"


def test_update_scene_text_re_check_surfaces_reintroduced_violation_as_warning(monkeypatch):
    """D6-3b: the repair leg must RE-CHECK after the write, not just carry
    the column forward blindly. A scene whose location was carried forward
    but whose NEW text now names another scene's location must surface a
    warning (never block — the edit itself always succeeds)."""
    import routes.videos as rv
    from models import SceneTextUpdate

    async def fake_execute(query, *args):
        return "UPDATE 1"

    async def fake_fetch_all(query, *args):
        return [
            {"scene": 1, "location": "the bedroom",
             "scene_text": "She climbs through the garage window now."},
            {"scene": 2, "location": "the garage", "scene_text": "Tools line the wall."},
        ]

    monkeypatch.setattr(rv, "execute", fake_execute)
    monkeypatch.setattr(rv, "fetch_all", fake_fetch_all)

    result = asyncio.run(rv.update_scene_text(
        "video-1", 1, SceneTextUpdate(text="She climbs through the garage window now."),
        tenant_id="tenant-1",
    ))

    assert result["story_law_s3_warnings"], "a reintroduced cross-location mention must be surfaced"
    assert "garage" in result["story_law_s3_warnings"][0]


# ---------------------------------------------------------------------------
# worker.py arq path — needs_review must surface as non-completed
# ---------------------------------------------------------------------------

def test_arq_needs_review_persists_as_failed_with_violation_text(monkeypatch):
    """D6-3b (systemic fix, THE big one): worker.py's _run_stage only
    special-cased 'cancelled'/'failed' — every other status, including
    needs_review, fell through to db_persist_task(..., 'completed', ...),
    silently discarding the violation and leaving the video stuck with no
    visible reason. Proves the arq path specifically (not the in-process
    routes/pipeline.py path, which already worked)."""
    import asyncio as _asyncio
    import worker

    persisted = []

    async def fake_db_persist_task(tenant_id, video_id, task_type, status, **kwargs):
        persisted.append((status, kwargs.get("message"), kwargs.get("error")))

    class _FakeExecutor:
        def __init__(self, _tenant_id):
            pass

        async def run_script(self, video_id, **_kwargs):
            return {
                "status": "needs_review",
                "video_id": video_id,
                "violations": ["scene 1: Scene has no LOCATION header."],
                "message": "The script needs another look — scene 1 has no location.",
            }

    monkeypatch.setattr("task_store.db_persist_task", fake_db_persist_task)
    monkeypatch.setattr("pipeline_executor.PipelineExecutor", _FakeExecutor)

    ctx = {"job_try": 1}
    result = _asyncio.run(worker.arq_run_script(ctx, "video-1", "tenant-1", attempt=1))

    assert result["status"] == "needs_review"  # the raw result is untouched
    # exactly one persisted call reaches a terminal state (skip the initial "running")
    terminal_calls = [p for p in persisted if p[0] != "running"]
    assert len(terminal_calls) == 1
    status, message, error = terminal_calls[0]
    assert status != "completed", "a needs_review result must NEVER persist as completed"
    assert status == "failed"
    assert "location" in (error or "").lower()
