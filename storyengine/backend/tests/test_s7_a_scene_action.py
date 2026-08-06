"""S7-A — the ACTION stage-direction AUTHORING channel, mirroring the
existing LOCATION pattern (D6-3/D6-3b's story_laws.py machinery) exactly.

STASH-PROOF: this file imports ``extract_scene_action``/``parse_scene_action``
directly from ``story_laws`` at module level — neither symbol exists before
this chunk, so ``git stash`` on story_laws.py makes this whole file fail at
COLLECTION (ImportError), the loudest possible "before" failure.

Covers:
  - story_laws.py pure functions: extract_scene_action/parse_scene_action,
    mirroring extract_scene_location/parse_scene_location's own contract
    (byte-for-byte untouched text when absent, header must be within the
    first two non-blank lines, strict whole-line match).
  - LOCATION: and ACTION: coexistence, in EITHER order, as a scene's two
    leading header lines — each parser finds its own header when the other
    precedes it, and strips ONLY its own line.
  - parse_scene_location's behavior for every pre-existing case (no ACTION
    header involved) is UNCHANGED — proven directly here, and by running
    tests/test_d6_3_story_law_s3.py unmodified (see the S7-A report).
  - check_scene_location_law (S3 hard gate) still passes when an ACTION:
    line precedes the LOCATION: line in a scene's raw text.
  - user_script._normalize_external_scenes: explicit "action" field, ACTION:
    fallback, text never rewritten.
  - user_script.accept_external_script / set_user_script: the scripts INSERT
    carries the action column alongside location.
  - routes/videos.py update_scene_text: the edit path extracts BOTH headers
    regardless of order, strips both from stored_text, stores both columns
    (COALESCE-preserving when a header is absent from the edit).
  - routes/mcp.py _SUBMIT_SCRIPT_TOOL: the scenes[].action field exists in
    the raw inputSchema dict, and the tool description carries the ACTION
    contract as a peer of the LOCATION paragraph.
  - originality._SCRIPT_JUDGE_SYSTEM: carries the stage-direction carve-out
    (LOCATION:/ACTION: headers are never judged, never grounds for revise).
  - backend/migrations/154_scene_action.sql exists and is idempotent SQL.

Local/no-spend: every Claude call is a fake client; every DB call is a fake
fetch_one/execute, matching tests/test_c46d_trust_boundaries.py's and
tests/test_d6_3_story_law_s3.py's own conventions.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/test_s7_a_scene_action.py -q
"""

import asyncio
import json
import os

import pytest

from story_laws import (
    extract_scene_action,
    parse_scene_action,
    extract_scene_location,
    parse_scene_location,
    check_scene_location_law,
)


# ---------------------------------------------------------------------------
# Pure functions — extract_scene_action / parse_scene_action
# (mirrors test_d6_3_story_law_s3.py's extract_scene_location test matrix)
# ---------------------------------------------------------------------------

def test_extract_scene_action_header_present():
    text = "ACTION: she jumps on the table and dances\n\nThe room falls silent."
    action, remaining = extract_scene_action(text)
    assert action == "she jumps on the table and dances"
    assert remaining == "The room falls silent."
    assert "ACTION" not in remaining


def test_extract_scene_action_no_header_returns_original_untouched():
    text = "The room falls silent."
    action, remaining = extract_scene_action(text)
    assert action is None
    assert remaining == text  # byte-for-byte, not just equal-looking


def test_extract_scene_action_mid_narration_mention_is_not_the_header():
    # An "action" mention mid-narration (not on a leading line) is NOT the header.
    text = "She waits.\nACTION: she dances\nThen leaves."
    action, remaining = extract_scene_action(text)
    assert action is None
    assert remaining == text


def test_extract_scene_action_skips_leading_blank_lines():
    text = "\n\nACTION: he sprints across the parking lot\n\nHe is out of breath."
    action, remaining = extract_scene_action(text)
    assert action == "he sprints across the parking lot"
    assert remaining == "He is out of breath."


def test_extract_scene_action_empty_text():
    assert extract_scene_action("") == (None, "")
    assert extract_scene_action(None) == (None, "")


def test_parse_scene_action_never_touches_text():
    text = "ACTION: she dances\n\nThe room falls silent."
    assert parse_scene_action(text) == "she dances"


# ---------------------------------------------------------------------------
# parse_scene_location UNCHANGED for every pre-existing (no-ACTION) case —
# the S7-A pin's explicit requirement that D6-3's parser behavior never
# regresses. Mirrors test_d6_3_story_law_s3.py's own assertions verbatim.
# ---------------------------------------------------------------------------

def test_extract_scene_location_still_works_with_no_action_present():
    text = "LOCATION: the garage\n\nShe wakes up and reaches for the light."
    location, remaining = extract_scene_location(text)
    assert location == "the garage"
    assert remaining == "She wakes up and reaches for the light."


def test_extract_scene_location_still_returns_none_with_no_header_at_all():
    text = "She wakes up and reaches for the light."
    location, remaining = extract_scene_location(text)
    assert location is None
    assert remaining == text


def test_extract_scene_location_still_requires_header_within_first_two_lines():
    # A LOCATION mention on the THIRD line (two lines deep, neither of which
    # is an ACTION: header) is still never mistaken for the header.
    text = "She wakes up.\nShe stretches.\nLOCATION: the garage\nAnd runs."
    location, remaining = extract_scene_location(text)
    assert location is None
    assert remaining == text


# ---------------------------------------------------------------------------
# Coexistence — LOCATION: and ACTION: as the two leading header lines, in
# EITHER order. Each parser finds its own header and strips ONLY its own
# line, leaving the sibling header (and body) untouched.
# ---------------------------------------------------------------------------

def test_location_then_action_each_parser_finds_its_own():
    text = "LOCATION: the garage\nACTION: she dances on the workbench\n\nMusic plays."
    location, after_location = extract_scene_location(text)
    assert location == "the garage"
    assert after_location == "ACTION: she dances on the workbench\n\nMusic plays."

    action, after_action = extract_scene_action(text)
    assert action == "she dances on the workbench"
    assert after_action == "LOCATION: the garage\n\nMusic plays."


def test_action_then_location_each_parser_finds_its_own():
    text = "ACTION: she dances on the workbench\nLOCATION: the garage\n\nMusic plays."
    location, after_location = extract_scene_location(text)
    assert location == "the garage"
    assert after_location == "ACTION: she dances on the workbench\n\nMusic plays."

    action, after_action = extract_scene_action(text)
    assert action == "she dances on the workbench"
    assert after_action == "LOCATION: the garage\n\nMusic plays."


def test_chained_extraction_strips_both_headers_regardless_of_order():
    """The real call-site pattern (routes/videos.py update_scene_text):
    extract_scene_location first, then extract_scene_action on what's left.
    Proves the chain strips BOTH headers and leaves only the body, in both
    orders."""
    for text in (
        "LOCATION: the garage\nACTION: she dances\n\nBody text here.",
        "ACTION: she dances\nLOCATION: the garage\n\nBody text here.",
    ):
        location, after_location = extract_scene_location(text)
        action, stored_text = extract_scene_action(after_location)
        assert location == "the garage"
        assert action == "she dances"
        assert stored_text == "Body text here."
        assert "LOCATION" not in stored_text
        assert "ACTION" not in stored_text


def test_only_one_line_of_tolerance_not_two():
    """Tolerance is exactly one leading sibling-header line — a THIRD line
    (neither header, sitting between the sibling header and this scene's
    own) must not be skipped over."""
    text = "ACTION: she dances\nSome narration line.\nLOCATION: the garage\n\nBody."
    location, _ = extract_scene_location(text)
    assert location is None  # the narration line broke the tolerance window


def test_action_only_no_location_present():
    text = "ACTION: he sprints across the parking lot\n\nHe is out of breath."
    location, after_location = extract_scene_location(text)
    assert location is None
    assert after_location == text  # untouched — no LOCATION anywhere
    action, stored = extract_scene_action(after_location)
    assert action == "he sprints across the parking lot"
    assert stored == "He is out of breath."


def test_location_only_no_action_present():
    text = "LOCATION: the garage\n\nShe wakes up."
    location, after_location = extract_scene_location(text)
    assert location == "the garage"
    action, stored = extract_scene_action(after_location)
    assert action is None
    assert stored == "She wakes up."


def test_neither_header_present_text_fully_untouched():
    text = "Just plain narration, no headers at all."
    location, after_location = extract_scene_location(text)
    action, stored = extract_scene_action(after_location)
    assert location is None
    assert action is None
    assert stored == text


# ---------------------------------------------------------------------------
# S3 hard gate (check_scene_location_law) still passes when an ACTION: line
# precedes the LOCATION: line — the location extracted from the raw text is
# a real value, so the gate's no_location check never fires.
# ---------------------------------------------------------------------------

def test_s3_gate_passes_when_action_precedes_location_header():
    text = "ACTION: she sprints across the lot\nLOCATION: the parking lot\n\nShe runs fast."
    location, _ = extract_scene_location(text)
    assert location == "the parking lot"  # sanity: the header was actually found

    scenes = [{"scene": 1, "location": location, "scene_text": text}]
    result = check_scene_location_law(scenes)
    assert result["passed"] is True
    assert result["violations"] == []


def test_s3_gate_still_hard_fails_when_location_genuinely_absent_action_present():
    """Control: an ACTION: header alone (no LOCATION: anywhere) must still
    trip the S3 no_location violation — S7-A does not weaken S3."""
    text = "ACTION: she sprints across the lot\n\nShe runs fast."
    location, _ = extract_scene_location(text)
    assert location is None

    scenes = [{"scene": 1, "location": location, "scene_text": text}]
    result = check_scene_location_law(scenes)
    assert result["passed"] is False
    assert result["violations"][0]["reason"] == "no_location"


# ---------------------------------------------------------------------------
# user_script._normalize_external_scenes — explicit "action" field + ACTION:
# fallback, text never rewritten.
# ---------------------------------------------------------------------------

def test_normalize_external_scenes_explicit_action_field():
    import user_script

    out = user_script._normalize_external_scenes([
        {"text": "She opens the hatch.", "location": "the garage", "action": "she leaps onto the crate"},
    ])
    assert out[0]["action"] == "she leaps onto the crate"
    assert out[0]["text"] == "She opens the hatch."  # untouched


def test_normalize_external_scenes_action_fallback_from_header_never_rewrites_text():
    import user_script

    raw_text = "ACTION: she leaps onto the crate\n\nShe opens the hatch."
    out = user_script._normalize_external_scenes([
        {"text": raw_text, "location": "the garage"},
    ])
    assert out[0]["action"] == "she leaps onto the crate"
    assert out[0]["text"] == raw_text, "external-submission text is never rewritten, header stays in place"


def test_normalize_external_scenes_blank_action_string_becomes_none():
    import user_script

    out = user_script._normalize_external_scenes([
        {"text": "Plain scene.", "location": "the garage", "action": "   "},
    ])
    assert out[0]["action"] is None


def test_normalize_external_scenes_no_action_anywhere_is_none():
    import user_script

    out = user_script._normalize_external_scenes([
        {"text": "Plain scene, no header, no field.", "location": "the garage"},
    ])
    assert out[0]["action"] is None


def test_normalize_external_scenes_both_headers_coexisting_in_either_order():
    import user_script

    for raw_text in (
        "LOCATION: the garage\nACTION: she leaps onto the crate\n\nBody prose.",
        "ACTION: she leaps onto the crate\nLOCATION: the garage\n\nBody prose.",
    ):
        out = user_script._normalize_external_scenes([{"text": raw_text}])
        assert out[0]["location"] == "the garage"
        assert out[0]["action"] == "she leaps onto the crate"
        assert out[0]["text"] == raw_text, "never rewritten, regardless of header order"


# ---------------------------------------------------------------------------
# user_script.accept_external_script — the scripts INSERT carries action
# ---------------------------------------------------------------------------

class _FakeGrade:
    needs_revision = False
    verdict = "pass"
    score = 90
    failing_gates = []
    violations = []
    rule_verdicts = []


def _wire_accept(monkeypatch, video):
    writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query and args[0] == video["id"] and args[1] == video["tenant_id"]:
            return dict(video)
        return None

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_critique(*_a, **_k):
        return _FakeGrade()

    async def fake_noop(*_a, **_k):
        return None

    async def fake_get_client(_tenant_id):
        raise RuntimeError("no client needed — critique_script is faked directly")

    import user_script
    import script_quality
    import quality_rules
    import dialogue_intelligence

    monkeypatch.setattr(user_script, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(user_script, "execute", fake_execute)
    monkeypatch.setattr(script_quality, "critique_script", fake_critique)
    monkeypatch.setattr(quality_rules, "list_all_rules", fake_noop)
    monkeypatch.setattr(dialogue_intelligence, "tag_video_dialogue", fake_noop)
    monkeypatch.setattr("kie_unified.get_text_client_for_tenant", fake_get_client, raising=False)
    monkeypatch.setattr(
        "identity.build_identity_context",
        lambda *_a, **_k: asyncio.sleep(0, result=type("I", (), {"niche": ""})()),
        raising=False,
    )
    return writes


def test_accept_external_script_insert_carries_action(monkeypatch):
    import user_script

    video = {"id": "video-1", "tenant_id": "tenant-1", "video_title": "T",
             "executive_hook": None, "hook_script": None}
    writes = _wire_accept(monkeypatch, video)

    result = asyncio.run(user_script.accept_external_script(
        "tenant-1", "video-1",
        [{"text": "She opens the hatch and climbs through.",
          "location": "the garage", "action": "she leaps onto the crate"}],
        source="agent_submitted",
    ))
    assert result["accepted"] is True

    inserts = [w for w in writes if "INSERT INTO scripts" in w[0]]
    assert len(inserts) == 1
    assert "action" in inserts[0][0]
    # params: (tenant_id, video_id, scene, text, location, action, title, voice_id)
    assert inserts[0][1][4] == "the garage"
    assert inserts[0][1][5] == "she leaps onto the crate"


def test_accept_external_script_insert_action_none_when_absent(monkeypatch):
    import user_script

    video = {"id": "video-1", "tenant_id": "tenant-1", "video_title": "T",
             "executive_hook": None, "hook_script": None}
    writes = _wire_accept(monkeypatch, video)

    asyncio.run(user_script.accept_external_script(
        "tenant-1", "video-1",
        [{"text": "She opens the hatch and climbs through.", "location": "the garage"}],
        source="agent_submitted",
    ))
    inserts = [w for w in writes if "INSERT INTO scripts" in w[0]]
    assert inserts[0][1][5] is None


# ---------------------------------------------------------------------------
# user_script.set_user_script — INSERT carries action too (consistency
# sweep alongside location, creator-verbatim / read-only extraction).
# ---------------------------------------------------------------------------

def test_set_user_script_insert_carries_action_read_only(monkeypatch):
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

    creator_text = "LOCATION: the garage\nACTION: she leaps onto the crate\n\nThis is my own story, word for word."
    result = asyncio.run(user_script.set_user_script("tenant-1", "video-1", creator_text))
    assert result["scenes"] == 1

    inserts = [w for w in writes if "INSERT INTO scripts" in w[0]]
    assert len(inserts) == 1
    stored_text = inserts[0][1][3]
    # Creator-verbatim: text is NEVER altered, even though it contains BOTH headers.
    assert stored_text == creator_text.strip()
    assert inserts[0][1][4] == "the garage"
    assert inserts[0][1][5] == "she leaps onto the crate"


# ---------------------------------------------------------------------------
# routes/videos.py update_scene_text — edit path extracts BOTH headers
# regardless of order, strips both, stores both columns.
# ---------------------------------------------------------------------------

def test_update_scene_text_extracts_both_headers_location_then_action(monkeypatch):
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
        "video-1", 1,
        SceneTextUpdate(text="LOCATION: the kitchen\nACTION: she dances\n\nShe chops onions."),
        tenant_id="tenant-1",
    ))

    scene_write = next(qa for qa in calls if "COALESCE" in qa[0])
    assert "action" in scene_write[0]
    # args: (stored_text, video_id, scene, tenant_id, new_location, new_action)
    assert scene_write[1][0] == "She chops onions."
    assert scene_write[1][4] == "the kitchen"
    assert scene_write[1][5] == "she dances"


def test_update_scene_text_extracts_both_headers_action_then_location(monkeypatch):
    """Order-independence: ACTION: preceding LOCATION: must extract exactly
    the same way as the reverse order."""
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
        "video-1", 1,
        SceneTextUpdate(text="ACTION: she dances\nLOCATION: the kitchen\n\nShe chops onions."),
        tenant_id="tenant-1",
    ))

    scene_write = next(qa for qa in calls if "COALESCE" in qa[0])
    assert scene_write[1][0] == "She chops onions."
    assert scene_write[1][4] == "the kitchen"
    assert scene_write[1][5] == "she dances"


def test_update_scene_text_no_action_header_coalesces_existing_column(monkeypatch):
    """No new ACTION signal at all -> COALESCE($6, action) must leave the
    existing column untouched, exactly like location's own contract."""
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

    scene_write = next(qa for qa in calls if "COALESCE" in qa[0])
    assert scene_write[1][4] is None  # location: no new header
    assert scene_write[1][5] is None  # action: no new header
    assert result["story_law_s3_warnings"] == []


# ---------------------------------------------------------------------------
# routes/mcp.py _SUBMIT_SCRIPT_TOOL — scenes[].action in the raw inputSchema,
# description carries the ACTION contract.
# ---------------------------------------------------------------------------

def test_submit_script_tool_schema_has_action_field():
    from routes.mcp import _SUBMIT_SCRIPT_TOOL

    item_props = _SUBMIT_SCRIPT_TOOL["inputSchema"]["properties"]["scenes"]["items"]["properties"]
    assert "action" in item_props
    assert item_props["action"]["type"] == "string"
    # location stays REQUIRED-in-spirit (S3); action must NOT be required.
    required = _SUBMIT_SCRIPT_TOOL["inputSchema"]["properties"]["scenes"]["items"].get("required", [])
    assert "action" not in required


def test_submit_script_tool_description_states_action_contract():
    from routes.mcp import _SUBMIT_SCRIPT_TOOL

    description = _SUBMIT_SCRIPT_TOOL["description"]
    assert "ACTION" in description
    assert "S7-A" in description
    assert "never" in description.lower() and ("spoken" in description.lower() or "voiced" in description.lower())


# ---------------------------------------------------------------------------
# originality._SCRIPT_JUDGE_SYSTEM — the stage-direction carve-out
# ---------------------------------------------------------------------------

def test_judge_system_prompt_carries_stage_direction_carveout():
    import originality

    prompt = originality._SCRIPT_JUDGE_SYSTEM
    assert "LOCATION" in prompt
    assert "ACTION" in prompt
    assert "STAGE DIRECTION" in prompt.upper()
    assert "never spoken" in prompt.lower() or "not narration" in prompt.lower()


def test_judge_system_prompt_carveout_is_single_shared_instance():
    """Critique_script (accept_external_script's own judge) reuses THIS
    exact constant, imported, not re-typed — one place, not scattered."""
    import script_quality

    assert script_quality._SCRIPT_JUDGE_SYSTEM is __import__("originality")._SCRIPT_JUDGE_SYSTEM


# ---------------------------------------------------------------------------
# Migration 154 — exists, idempotent SQL, mirrors 144's shape
# ---------------------------------------------------------------------------

def test_migration_154_scene_action_exists_and_is_idempotent():
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.join(backend_dir, "migrations", "154_scene_action.sql")
    assert os.path.isfile(path), f"expected migration file at {path}"
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    assert "ALTER TABLE scripts" in sql
    assert "ADD COLUMN IF NOT EXISTS action TEXT" in sql
    # Nullable, no default (mirrors 144_scene_location.sql) — no NOT NULL,
    # no DEFAULT keyword attached to this column's definition.
    assert "action TEXT NOT NULL" not in sql
    assert "action TEXT DEFAULT" not in sql


def test_migration_154_is_next_free_number():
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    migrations_dir = os.path.join(backend_dir, "migrations")
    numbers = sorted(
        int(name.split("_", 1)[0])
        for name in os.listdir(migrations_dir)
        if name[:3].isdigit() and name.endswith(".sql")
    )
    assert 154 in numbers
    assert max(n for n in numbers if n != 154) == 153, "154 must be the next free number after 153"
