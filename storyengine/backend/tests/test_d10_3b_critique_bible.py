"""D10-3b — the script quality critic ALSO checks a script against this
video's own StoryEngine-native Story Bible (D10-2ab: ``narrative``,
``relationships``, ``arcs``), when one exists and carries them.

Covers:
  1. Byte-identical prompt: a legacy bible (no narrative/relationships/arcs
     keys at all), a freshly-normalized native bible whose new sections are
     present but empty, and no bible row at all — all three must produce a
     ``system_prompt`` byte-identical to pre-D10-3b behavior (no rules_text:
     exactly ``originality._SCRIPT_JUDGE_SYSTEM``).
  2. A populated bible (narrative + relationships + arcs) appends a
     "STORY STRUCTURE TO HONOR" section naming the genre/conflict/stakes,
     each character's arc, and each relationship's dynamic — and coexists
     with an existing rules_text addendum rather than replacing it.
  3. A judge-flagged arc contradiction flows through the EXISTING
     violation/edit machinery (failing_gates -> CritiqueResult.violations ->
     edit_draft_with_violations' @@@SCENE n@@@ round trip) — no parallel
     channel.
  4. Fail-open is scoped to the addendum only: a bible fetch/parse error
     (DB unreachable, malformed JSON) must never skip the grading call
     itself — the critic still runs and returns the judge's real verdict,
     not the "grade unavailable" sentinel reserved for an actual client
     failure.
  5. Scope: a strict_rule_ids caller (Custom Film's per-section quality
     pass — a different, role/purpose-grounded production style that never
     populates a Story Bible narrative/arcs/relationships) never triggers
     the bible fetch at all, preserving its proven "total critic failure
     touches no DB" contract.

Local/no-spend: every Claude call is a fake client; ``script_quality.fetch_one``
is monkeypatched per test (same convention tests/test_c46a_quality_critic_wiring.py
uses for pipeline_executor's own fetch_one/fetch_all). No real DB, no network.
"""

import asyncio
import json

import originality
import script_quality as sq


class FakeClient:
    """Queues canned responses; records every call's kwargs for assertions."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeClient ran out of canned responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _scenes(*texts):
    return [{"scene": i + 1, "text": t} for i, t in enumerate(texts)]


def _json_pass():
    return '{"verdict": "pass", "score": 88, "failing_gates": [], "rewrite_guidance": ""}'


def _row(bible):
    """Shape a fake `videos` row the way database.fetch_one would return one."""
    return {"story_bible": bible}


def _legacy_bible():
    """A bible generated before D10-2ab — no narrative/relationships/arcs keys."""
    return {
        "characters": [{"id": "hero", "costume": "dark suit"}],
        "locations": [{"id": "office", "description": "an office"}],
        "scene_blocks": [],
    }


def _empty_native_bible():
    """A bible normalize_story_bible has touched, but the model contributed
    nothing to the new sections — every new key present, every value empty
    (story_bible_native._normalize_narrative/_relationships/_arcs's own
    all-empty-input shape)."""
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
        "characters": [
            {"id": "hero", "costume": "dark suit"},
            {"id": "rival", "costume": "grey coat"},
        ],
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
        "relationships": [
            {
                "characters": ["hero", "rival"],
                "dynamic": "uneasy allies",
                "tension_source": "rival hides the real vote count",
                "evolves_to": "open adversaries",
            },
        ],
        "arcs": {
            "hero": {
                "start_state": "confident, in control",
                "end_state": "isolated, cornered",
                "turning_scenes": [3],
            },
        },
    }


# ---------------------------------------------------------------------------
# 1. Byte-identical prompt — the key test
# ---------------------------------------------------------------------------

def test_legacy_bible_produces_byte_identical_prompt(monkeypatch):
    async def fake_fetch_one(query, *args):
        return _row(_legacy_bible())

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))
    assert client.calls[0]["system_prompt"] == originality._SCRIPT_JUDGE_SYSTEM


def test_empty_native_bible_produces_byte_identical_prompt(monkeypatch):
    async def fake_fetch_one(query, *args):
        return _row(_empty_native_bible())

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))
    assert client.calls[0]["system_prompt"] == originality._SCRIPT_JUDGE_SYSTEM


def test_no_bible_row_produces_byte_identical_prompt(monkeypatch):
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))
    assert client.calls[0]["system_prompt"] == originality._SCRIPT_JUDGE_SYSTEM


def test_no_database_reachable_produces_byte_identical_prompt(monkeypatch):
    """The real-world default for every test in this suite and every video
    today: no DATABASE_URL, so database.get_pool() raises RuntimeError. This
    proves the module's OWN unmocked fetch_one degrades to the exact same
    legacy prompt, not just the mocked-None case above."""
    client = FakeClient([_json_pass()])
    asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))
    assert client.calls[0]["system_prompt"] == originality._SCRIPT_JUDGE_SYSTEM


# ---------------------------------------------------------------------------
# 2. Story-structure section present with a populated bible
# ---------------------------------------------------------------------------

def test_populated_bible_appends_story_structure_section(monkeypatch):
    async def fake_fetch_one(query, *args):
        return _row(_populated_bible())

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))
    prompt = client.calls[0]["system_prompt"]
    assert prompt != originality._SCRIPT_JUDGE_SYSTEM
    assert prompt.startswith(originality._SCRIPT_JUDGE_SYSTEM), "additive, never a replacement"
    assert "STORY STRUCTURE TO HONOR" in prompt
    assert "geopolitical thriller" in prompt
    assert "hero must expose the rival before the vote" in prompt
    assert "confident, in control" in prompt and "isolated, cornered" in prompt
    assert "turns at scene 3" in prompt
    assert "uneasy allies" in prompt
    assert "hero <-> rival" in prompt


def test_story_bible_column_as_json_string_is_parsed(monkeypatch):
    """asyncpg returns JSONB as a str without a registered codec — matches
    the isinstance(sb, str) handling scripts/coverage_to_app.py and
    routes/characters.py already use for this exact column."""
    async def fake_fetch_one(query, *args):
        return _row(json.dumps(_populated_bible()))

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))
    assert "STORY STRUCTURE TO HONOR" in client.calls[0]["system_prompt"]


def test_story_structure_coexists_with_rules_text_addendum(monkeypatch):
    async def fake_fetch_one(query, *args):
        return _row(_populated_bible())

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    asyncio.run(sq.critique_script(
        "t", "v", {"script": "A real script."},
        rules_text="Always cold-open.", client=client,
    ))
    prompt = client.calls[0]["system_prompt"]
    assert "CHANNEL RULES" in prompt
    assert "Always cold-open" in prompt
    assert "STORY STRUCTURE TO HONOR" in prompt
    # Order: base prompt, then rules addendum, then story structure.
    assert prompt.index("CHANNEL RULES") < prompt.index("STORY STRUCTURE TO HONOR")


# ---------------------------------------------------------------------------
# 3. A planted arc contradiction flows through the EXISTING edit machinery
# ---------------------------------------------------------------------------

def test_arc_contradiction_flows_through_existing_violation_edit_loop(monkeypatch):
    async def fake_fetch_one(query, *args):
        return _row(_populated_bible())

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)

    contradiction_grade = json.dumps({
        "verdict": "revise", "score": 55,
        "failing_gates": ["scene 1 has hero triumphant, contradicting the stated arc turn to isolated and cornered"],
        "rewrite_guidance": "",
    })
    edited_raw = "@@@SCENE 1@@@\nHero stands alone, cornered by the vote."
    client = FakeClient([contradiction_grade, edited_raw, _json_pass()])

    outcome = asyncio.run(sq.run_critique_and_edit(
        "t", "v", _scenes("Hero celebrates a clean victory."), client=client,
    ))

    # (a) the judge that flagged the contradiction actually SAW the arc data —
    # proves the signal reached the prompt, not just a coincidental verdict.
    assert "isolated, cornered" in client.calls[0]["system_prompt"]
    # (b) the violation named in failing_gates is exactly what
    # CritiqueResult.violations surfaces...
    assert outcome["critique"].verdict == "pass"
    assert outcome["edit_rounds"] == 1
    # (c) ...and it reached the SAME @@@SCENE n@@@ edit prompt every other
    # violation (hook/causality/channel-rule) already uses — no parallel
    # channel, no separate story-structure edit call.
    edit_prompt = client.calls[1]["prompt"]
    assert "EDIT THIS SCRIPT MINIMALLY" in edit_prompt
    assert "contradicting the stated arc turn to isolated and cornered" in edit_prompt
    assert outcome["changed"] is True
    assert outcome["scenes"][0]["text"] == "Hero stands alone, cornered by the vote."


def test_strict_mode_never_fetches_the_story_bible_or_touches_the_db(monkeypatch):
    """A strict_rule_ids caller (Custom Film's per-section quality pass) is a
    role/purpose-grounded production style that never populates a Story
    Bible narrative/arcs/relationships — a different, documentary-style
    concept — and already carries its OWN exhaustive hard-gate rules via
    rules_text/severity_by_rule. It also has a proven "total critic failure
    must touch no DB at all" contract
    (tests/functional/test_m7_4f_av_screenplay_adversarial.py's
    test_two_malformed_strict_critic_responses_fail_before_persistence).
    D10-3b's bible fetch must never run for a strict caller — proven here by
    a fetch_one that raises AssertionError the instant it's called."""
    async def forbidden_fetch_one(query, *args):
        raise AssertionError("strict_rule_ids critique must never touch the DB")

    monkeypatch.setattr(sq, "fetch_one", forbidden_fetch_one)

    strict_ids = ("role_structure_quality",)
    raw = json.dumps({
        "verdict": "pass", "score": 90,
        "failing_gates": [],
        "rewrite_guidance": "",
        "rule_verdicts": [{"rule": "role_structure_quality", "passed": True, "note": ""}],
    })
    client = FakeClient([raw])

    result = asyncio.run(sq.critique_script(
        "t", "v", {"script": "A real script."},
        rules_text="role_structure_quality: require dependent actions",
        strict_rule_ids=strict_ids,
        client=client,
    ))
    assert [rv.rule for rv in result.rule_verdicts] == list(strict_ids)
    assert "STORY STRUCTURE TO HONOR" not in client.calls[0]["system_prompt"]


# ---------------------------------------------------------------------------
# 4. Fail-open is scoped to the addendum only
# ---------------------------------------------------------------------------

def test_bible_fetch_error_fails_open_on_addendum_only_not_the_critique(monkeypatch):
    async def fake_fetch_one(query, *args):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    result = asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))

    # The grading call still happened — this is NOT the outer
    # "grade unavailable - failed open" sentinel.
    assert len(client.calls) == 1
    assert client.calls[0]["system_prompt"] == originality._SCRIPT_JUDGE_SYSTEM
    assert result.verdict == "pass"
    assert result.score == 88
    assert result.failing_gates == []


def test_malformed_story_bible_json_fails_open_on_addendum_only(monkeypatch):
    async def fake_fetch_one(query, *args):
        return _row("{not valid json")

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    result = asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))

    assert len(client.calls) == 1
    assert client.calls[0]["system_prompt"] == originality._SCRIPT_JUDGE_SYSTEM
    assert result.verdict == "pass"
    assert result.score == 88


def test_wrong_shaped_story_bible_fails_open_on_addendum_only(monkeypatch):
    """story_bible is a JSON value but not an object (e.g. a bare list) —
    must be treated as absent, not raise."""
    async def fake_fetch_one(query, *args):
        return _row(["not", "a", "dict"])

    monkeypatch.setattr(sq, "fetch_one", fake_fetch_one)
    client = FakeClient([_json_pass()])
    result = asyncio.run(sq.critique_script("t", "v", {"script": "A real script."}, client=client))

    assert client.calls[0]["system_prompt"] == originality._SCRIPT_JUDGE_SYSTEM
    assert result.verdict == "pass"


# ---------------------------------------------------------------------------
# Pure-function unit coverage — _story_structure_addendum
# ---------------------------------------------------------------------------

def test_story_structure_addendum_empty_for_legacy_shape():
    assert sq._story_structure_addendum(_legacy_bible()) == ""


def test_story_structure_addendum_empty_for_normalized_but_empty_sections():
    assert sq._story_structure_addendum(_empty_native_bible()) == ""


def test_story_structure_addendum_nonempty_for_populated_bible():
    out = sq._story_structure_addendum(_populated_bible())
    assert out.startswith("\n\n")
    assert "STORY STRUCTURE TO HONOR" in out
    assert "END STORY STRUCTURE" in out
    assert "hero <-> rival" in out
    assert "tension: rival hides the real vote count" in out
    assert "evolves to: open adversaries" in out


def test_story_structure_addendum_drops_dangling_or_malformed_relationship():
    bible = _populated_bible()
    bible["relationships"].append({"characters": ["only_one"], "dynamic": "x"})
    bible["relationships"].append("not a dict")
    out = sq._story_structure_addendum(bible)
    # still renders the one good relationship, ignores the malformed ones
    assert out.count("<->") == 1


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
