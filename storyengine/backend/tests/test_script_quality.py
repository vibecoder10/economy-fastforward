"""Unit tests for script_quality.py (checklist C46a — generalized critic hook).

Local/no-spend: every Claude call is a fake client. Proves the lift from
originality.grade_script (fail-open shape, same system prompt/user-prompt
builder) plus the two generalizations this chunk adds: rules_text grading
and the DvsU-style bounded same-draft edit loop.
"""

import asyncio

import pytest

import originality
import script_quality as sq


def _scenes(*texts: str) -> list:
    return [{"scene": i + 1, "text": t} for i, t in enumerate(texts)]


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


def _json_pass():
    return '{"verdict": "pass", "score": 88, "failing_gates": [], "rewrite_guidance": ""}'


def _json_revise(gates=("hook speed",), guidance="Open on the stake, not backstory."):
    import json
    return json.dumps({
        "verdict": "revise", "score": 55,
        "failing_gates": list(gates), "rewrite_guidance": guidance,
    })


def _json_regenerate():
    return '{"verdict": "regenerate", "score": 20, "failing_gates": ["hook speed", "causality"], "rewrite_guidance": "Start over from the incident."}'


_CUSTOM_FILM_RULE_IDS = (
    "approved_purpose_grounding",
    "visual_story_readiness",
    "role_structure_quality",
    "story_arc_continuity",
    "shared_film_world_progression",
    "av_screenplay_performance",
)


def _strict_grade(*, failed_rule=None):
    import json

    return json.dumps(
        {
            "verdict": "pass",
            "score": 92,
            "failing_gates": [],
            "rewrite_guidance": "",
            "rule_verdicts": [
                {
                    "rule": rule_id,
                    "passed": rule_id != failed_rule,
                    "note": "needs repair" if rule_id == failed_rule else "",
                }
                for rule_id in _CUSTOM_FILM_RULE_IDS
            ],
        }
    )


# ---------------------------------------------------------------------------
# critique_script — the lifted critic
# ---------------------------------------------------------------------------

def test_critique_script_fails_open_with_no_client():
    result = asyncio.run(sq.critique_script("tenant-1", "video-1", {"script": "hello"}, client=None))
    assert result.verdict == "pass"
    assert result.needs_revision is False


def test_critique_script_fails_open_on_empty_script():
    client = FakeClient([_json_pass()])
    result = asyncio.run(sq.critique_script("tenant-1", "video-1", {"script": "  "}, client=client))
    assert result.verdict == "pass"
    assert client.calls == [], "an empty script must never spend a Claude call"


def test_critique_script_fails_open_on_client_error():
    client = FakeClient([RuntimeError("network blip")])
    result = asyncio.run(sq.critique_script("tenant-1", "video-1", {"script": "A real script."}, client=client))
    assert result.verdict == "pass"
    assert "failed open" in result.failing_gates[0]


def test_critique_script_reuses_originality_system_prompt_verbatim():
    """The lift claim: no re-invented judge prompt, the ORIGINALITY system
    prompt text is reused byte-for-byte as the base."""
    client = FakeClient([_json_pass()])
    asyncio.run(sq.critique_script("tenant-1", "video-1", {"script": "A real script."}, client=client))
    assert client.calls[0]["system_prompt"].startswith(originality._SCRIPT_JUDGE_SYSTEM)


def test_critique_script_parses_pass_and_revise_verdicts():
    client = FakeClient([_json_pass()])
    result = asyncio.run(sq.critique_script("t", "v", {"script": "script text"}, client=client))
    assert result.verdict == "pass" and result.score == 88

    client2 = FakeClient([_json_revise()])
    result2 = asyncio.run(sq.critique_script("t", "v", {"script": "script text"}, client=client2))
    assert result2.verdict == "revise"
    assert result2.needs_revision is True
    assert result2.violations == ["hook speed"]


def test_critique_script_rewrite_guidance_list_is_coerced_to_string():
    import json
    raw = json.dumps({
        "verdict": "revise", "score": 60, "failing_gates": ["payoff"],
        "rewrite_guidance": ["fix the ending", "name the stakes"],
    })
    client = FakeClient([raw])
    result = asyncio.run(sq.critique_script("t", "v", {"script": "x"}, client=client))
    assert result.rewrite_guidance == "fix the ending\nname the stakes"


def test_critique_script_with_rules_text_appends_addendum_and_returns_rule_verdicts():
    import json
    raw = json.dumps({
        "verdict": "revise", "score": 70, "failing_gates": [],
        "rewrite_guidance": "",
        "rule_verdicts": [
            {"rule": "cold open, no greeting", "passed": False, "note": "opens with 'hey everyone'"},
            {"rule": "one CTA at the end", "passed": True, "note": ""},
        ],
    })
    client = FakeClient([raw])
    result = asyncio.run(sq.critique_script(
        "t", "v", {"script": "Hey everyone, welcome back..."},
        rules_text="Always cold-open. Exactly one CTA at the end.", client=client,
    ))
    assert "CHANNEL RULES" in client.calls[0]["system_prompt"]
    assert "Always cold-open" in client.calls[0]["system_prompt"]
    assert result.verdict == "revise"
    assert result.failed_rule_names == ["cold open, no greeting"]
    # violations surfaces the failed RULE name even with no universal failing_gates
    assert result.violations == ["cold open, no greeting"]


def test_critique_script_rule_verdicts_as_bare_strings_are_coerced():
    result = sq.CritiqueResult(verdict="revise", rule_verdicts=["some rule broke"])
    assert result.rule_verdicts[0].rule == "some rule broke"
    assert result.rule_verdicts[0].passed is False


def test_strict_critic_retries_malformed_then_accepts_exact_rule_ids():
    client = FakeClient(['{"verdict":"pass"', _strict_grade()])

    result = asyncio.run(
        sq.critique_script(
            "tenant-1",
            "video-1",
            {"script": "A complete script."},
            rules_text=(
                "approved_purpose_grounding: nested prose\n"
                "visual_story_readiness: visible action"
            ),
            severity_by_rule={
                rule_id: "hard_gate" for rule_id in _CUSTOM_FILM_RULE_IDS
            },
            strict_rule_ids=_CUSTOM_FILM_RULE_IDS,
            critic_max_tokens=1800,
            retry_invalid_critique=True,
            client=client,
        )
    )

    assert result.verdict == "pass"
    assert [item.rule for item in result.rule_verdicts] == list(
        _CUSTOM_FILM_RULE_IDS
    )
    assert len(client.calls) == 2
    assert all(call["max_tokens"] == 1800 for call in client.calls)
    assert (
        "nested explanatory prose"
        in client.calls[0]["system_prompt"]
    )
    assert (
        "RETRY CONTRACT: The prior response was empty, malformed, or truncated"
        in client.calls[1]["system_prompt"]
    )


def test_strict_critic_two_malformed_responses_keep_fail_open_sentinel():
    client = FakeClient(["", "not-json"])

    result = asyncio.run(
        sq.critique_script(
            "tenant-1",
            "video-1",
            {"script": "A complete script."},
            rules_text="approved_purpose_grounding: approved facts only",
            severity_by_rule={
                rule_id: "hard_gate" for rule_id in _CUSTOM_FILM_RULE_IDS
            },
            strict_rule_ids=_CUSTOM_FILM_RULE_IDS,
            critic_max_tokens=1800,
            retry_invalid_critique=True,
            client=client,
        )
    )

    assert len(client.calls) == 2
    assert result.verdict == "pass"
    assert result.failing_gates == ["grade unavailable - failed open"]


def test_strict_critic_rejects_extra_or_missing_rule_ids():
    import json

    extra = json.loads(_strict_grade())
    extra["rule_verdicts"].append(
        {"rule": "nested_arc_prose", "passed": True, "note": ""}
    )
    client = FakeClient([json.dumps(extra), _strict_grade()])

    result = asyncio.run(
        sq.critique_script(
            "tenant-1",
            "video-1",
            {"script": "A complete script."},
            rules_text="story_arc_continuity: nested structural prose",
            strict_rule_ids=_CUSTOM_FILM_RULE_IDS,
            retry_invalid_critique=True,
            client=client,
        )
    )

    assert len(client.calls) == 2
    assert [item.rule for item in result.rule_verdicts] == list(
        _CUSTOM_FILM_RULE_IDS
    )


# ---------------------------------------------------------------------------
# Scene-marker round trip (the edit loop's data shape)
# ---------------------------------------------------------------------------

def test_parse_scene_markers_happy_path():
    raw = "@@@SCENE 1@@@\nFirst scene text.\n@@@SCENE 2@@@\nSecond scene text."
    scenes = sq._parse_scene_markers(raw)
    assert scenes == [
        {"scene": 1, "text": "First scene text."},
        {"scene": 2, "text": "Second scene text."},
    ]


def test_parse_scene_markers_no_markers_returns_empty():
    assert sq._parse_scene_markers("just plain prose, no markers") == []


def test_scene_marker_block_round_trips():
    scenes = _scenes("First.", "Second.")
    block = sq._scene_marker_block(scenes)
    assert sq._parse_scene_markers(block) == scenes


# ---------------------------------------------------------------------------
# edit_draft_with_violations — DvsU's same-draft targeted edit, generalized
# ---------------------------------------------------------------------------

def test_edit_draft_with_violations_returns_none_on_empty_inputs():
    client = FakeClient([])
    assert asyncio.run(sq.edit_draft_with_violations([], ["x"], client=client)) is None
    assert asyncio.run(sq.edit_draft_with_violations(_scenes("a"), [], client=client)) is None
    assert asyncio.run(sq.edit_draft_with_violations(_scenes("a"), ["x"], client=None)) is None
    assert client.calls == []


def test_edit_draft_with_violations_prompts_same_draft_not_a_reroll():
    original = _scenes("Hey everyone, welcome back.", "The rest of the story.")
    edited_raw = "@@@SCENE 1@@@\nAt 2am the alarm went off.\n@@@SCENE 2@@@\nThe rest of the story."
    client = FakeClient([edited_raw])
    result = asyncio.run(sq.edit_draft_with_violations(
        original, ["opens with a greeting, no stake"], client=client,
    ))
    assert result == [
        {"scene": 1, "text": "At 2am the alarm went off."},
        {"scene": 2, "text": "The rest of the story."},
    ]
    prompt = client.calls[0]["prompt"]
    assert "EDIT THIS SCRIPT MINIMALLY" in prompt
    assert "opens with a greeting, no stake" in prompt
    assert "CURRENT SCRIPT (by scene):" in prompt
    assert "Hey everyone, welcome back." in prompt, "the SAME draft must ride along, not a blank slate"


def test_edit_draft_with_violations_returns_none_on_scene_count_mismatch():
    original = _scenes("one", "two", "three")
    edited_raw = "@@@SCENE 1@@@\nonly one scene came back"
    client = FakeClient([edited_raw])
    result = asyncio.run(sq.edit_draft_with_violations(original, ["x"], client=client))
    assert result is None


def test_edit_draft_with_violations_fails_open_on_client_error():
    client = FakeClient([RuntimeError("boom")])
    result = asyncio.run(sq.edit_draft_with_violations(_scenes("a"), ["x"], client=client))
    assert result is None


# ---------------------------------------------------------------------------
# run_critique_and_edit — the orchestrator (verdict matrix)
# ---------------------------------------------------------------------------

def test_orchestrator_pass_verdict_ships_as_is_one_call_only():
    client = FakeClient([_json_pass()])
    outcome = asyncio.run(sq.run_critique_and_edit(
        "t", "v", _scenes("Great script."), client=client,
    ))
    assert outcome["critique"].verdict == "pass"
    assert outcome["needs_review"] is False
    assert outcome["edit_rounds"] == 0
    assert outcome["regenerated"] is False
    assert outcome["changed"] is False
    assert len(client.calls) == 1, "a passing script must cost exactly one grading call"


def test_orchestrator_revise_verdict_converges_within_edit_rounds():
    scenes = _scenes("Hey everyone, welcome back.", "The rest.")
    edited_raw = "@@@SCENE 1@@@\nAt 2am the alarm went off.\n@@@SCENE 2@@@\nThe rest."
    client = FakeClient([_json_revise(), edited_raw, _json_pass()])
    outcome = asyncio.run(sq.run_critique_and_edit(
        "t",
        "v",
        scenes,
        client=client,
        edit_constraints=["Keep the approved subject and 100-120 word band."],
    ))
    assert outcome["critique"].verdict == "pass"
    assert outcome["needs_review"] is False
    assert outcome["edit_rounds"] == 1
    assert outcome["regenerated"] is False
    assert outcome["changed"] is True
    assert outcome["scenes"][0]["text"] == "At 2am the alarm went off."
    assert len(client.calls) == 3, "grade, edit, re-grade — never a fresh re-roll for 'revise'"
    assert "Keep the approved subject and 100-120 word band." in (
        client.calls[1]["prompt"]
    )


def test_strict_hard_rule_failure_drives_edit_then_exact_regrade():
    scenes = _scenes("A magic button resolves everything.")
    edited_raw = (
        "@@@SCENE 1@@@\n"
        "A staged sequence visibly confirms each dependent action."
    )
    client = FakeClient(
        [
            _strict_grade(failed_rule="role_structure_quality"),
            edited_raw,
            _strict_grade(),
        ]
    )

    outcome = asyncio.run(
        sq.run_critique_and_edit(
            "tenant-1",
            "video-1",
            scenes,
            client=client,
            rules_text="role_structure_quality: require dependent actions",
            severity_by_rule={
                rule_id: "hard_gate" for rule_id in _CUSTOM_FILM_RULE_IDS
            },
            strict_rule_ids=_CUSTOM_FILM_RULE_IDS,
            critic_max_tokens=1800,
            retry_invalid_critique=True,
        )
    )

    assert outcome["critique"].verdict == "pass"
    assert outcome["edit_rounds"] == 1
    assert outcome["changed"] is True
    assert "role_structure_quality" in client.calls[1]["prompt"]
    assert client.calls[0]["max_tokens"] == 1800
    assert client.calls[2]["max_tokens"] == 1800


def test_orchestrator_revise_verdict_still_failing_after_bound_is_needs_review():
    scenes = _scenes("weak scene one", "weak scene two")
    edited_raw = "@@@SCENE 1@@@\nstill weak one\n@@@SCENE 2@@@\nstill weak two"
    # grade(revise) -> edit round 1 -> grade(revise) -> edit round 2 -> grade(revise)
    client = FakeClient([
        _json_revise(), edited_raw, _json_revise(), edited_raw, _json_revise(),
    ])
    outcome = asyncio.run(sq.run_critique_and_edit(
        "t", "v", scenes, client=client, max_edit_rounds=2,
    ))
    assert outcome["needs_review"] is True
    assert outcome["edit_rounds"] == sq.MAX_EDIT_ROUNDS == 2, "bounded at DvsU's proven 2 rounds"
    assert outcome["critique"].verdict == "revise"


def test_orchestrator_edit_parse_failure_stops_the_loop_early():
    scenes = _scenes("weak scene one", "weak scene two")
    unparseable = "no scene markers came back at all"
    client = FakeClient([_json_revise(), unparseable])
    outcome = asyncio.run(sq.run_critique_and_edit("t", "v", scenes, client=client, max_edit_rounds=2))
    assert outcome["needs_review"] is True
    assert outcome["edit_rounds"] == 1, "a broken parse must stop the loop, not retry blindly"
    assert outcome["changed"] is False


def test_orchestrator_regenerate_verdict_uses_one_fresh_reroll_not_the_edit_loop():
    scenes = _scenes("broadly weak script")
    fresh_scenes = _scenes("A completely rewritten script.")
    reroll_calls = []

    async def regenerate():
        reroll_calls.append(1)
        return fresh_scenes

    client = FakeClient([_json_regenerate(), _json_pass()])
    outcome = asyncio.run(sq.run_critique_and_edit(
        "t", "v", scenes, client=client, regenerate=regenerate,
    ))
    assert len(reroll_calls) == 1
    assert outcome["regenerated"] is True
    assert outcome["edit_rounds"] == 0, "'regenerate' never enters the same-draft edit loop"
    assert outcome["needs_review"] is False
    assert outcome["scenes"] == fresh_scenes
    assert len(client.calls) == 2, "grade, re-grade after the ONE reroll — no extra grading calls"


def test_orchestrator_regenerate_verdict_without_a_regenerate_hook_is_needs_review():
    scenes = _scenes("broadly weak script")
    client = FakeClient([_json_regenerate()])
    outcome = asyncio.run(sq.run_critique_and_edit("t", "v", scenes, client=client, regenerate=None))
    assert outcome["regenerated"] is False
    assert outcome["needs_review"] is True
    assert outcome["changed"] is False
    assert len(client.calls) == 1


def test_orchestrator_regenerate_returning_falsy_keeps_prior_scenes_and_grade():
    scenes = _scenes("broadly weak script")

    async def regenerate():
        return None  # reroll produced nothing usable

    client = FakeClient([_json_regenerate()])
    outcome = asyncio.run(sq.run_critique_and_edit("t", "v", scenes, client=client, regenerate=regenerate))
    assert outcome["regenerated"] is True
    assert outcome["scenes"] == scenes
    assert outcome["needs_review"] is True
    assert len(client.calls) == 1, "no re-grade call when the reroll gave back nothing"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
