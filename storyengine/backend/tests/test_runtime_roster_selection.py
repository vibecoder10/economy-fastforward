import math
import asyncio

import pytest

from roster_selection import selection_settings, selection_target, selection_validation


def _payload(count=20, *, duration=20, minutes=1):
    return {
        "unit_roster": [{"name": f"Machine {index}", "status": "production"} for index in range(count)],
        "recommended_final_roster": [f"Machine {index}" for index in range(count)],
        "roster_selection": {"version": 1, "settings": selection_settings(duration, minutes)},
    }


def test_runtime_selection_exact_default_and_custom_pacing():
    assert selection_target(20, 1) == 20
    assert selection_target(20, 2) == 10
    assert selection_validation("Every Example Ever Built", _payload(20))["passed"] is True
    assert selection_validation("Every Example Ever Built", _payload(10, minutes=2))["passed"] is True


@pytest.mark.parametrize("duration,pacing", [(0, 1), (20, 0), (math.inf, 1), (20, math.nan), ("bad", 1)])
def test_runtime_selection_rejects_invalid_inputs(duration, pacing):
    with pytest.raises(ValueError):
        selection_target(duration, pacing)


def test_every_title_does_not_override_runtime_count():
    result = selection_validation("Every Machine Ever Built", _payload(20, duration=20, minutes=1))
    assert result["passed"] is True
    assert result["target_count"] == 20


def test_selection_rejects_padding_duplicates_and_unbuilt_rows():
    duplicate = _payload()
    duplicate["unit_roster"][1]["name"] = "Machine 0"
    assert selection_validation("Every Machine", duplicate)["passed"] is False
    unbuilt = _payload()
    unbuilt["unit_roster"][1].update({"status": "cancelled", "built_count": "0 units built"})
    import pipeline_executor as pe
    assert pe._roster_validation("Every Machine Ever Built", unbuilt)["passed"] is False


def test_selection_agent_uses_dedicated_non_exhaustive_system_prompt():
    from research.agent import ResearchAgent, SELECTION_ONLY_SYSTEM_PROMPT

    class Client:
        def __init__(self):
            self.kwargs = None

        async def generate(self, **kwargs):
            self.kwargs = kwargs
            return '{"headline":"x","thesis":"deferred","executive_hook":"deferred","fact_sheet":"x","source_bibliography":"x"}'

    client = Client()
    asyncio.run(ResearchAgent(client, selection_settings=selection_settings(20, 1)).research("Every Test Ever Built"))
    assert client.kwargs["system_prompt"] == SELECTION_ONLY_SYSTEM_PROMPT
    assert "COMPLETE-ROSTER TITLES" not in client.kwargs["system_prompt"]


def test_fresh_runtime_selection_is_visible_to_static_docu_hold_without_old_marker():
    import pipeline_executor as pe
    payload = _payload()
    video = {"render_mode": "static_docu", "research_payload": payload}
    assert len(pe._machine_documentary_hold_roster(video)) == 20


def test_selection_subject_retains_eligibility_without_quantity_and_reuses_only_evidence():
    from roster_selection import selection_subject, selection_source_data, bound_selection_candidates
    from research.agent import _build_selection_prompt
    title='Every US Submarine Class Ever Built (2026)'
    assert selection_subject(title)=='US Submarine Class Ever Built (2026)'
    assert selection_subject('All British Aircraft Carriers Ever Built')=='British Aircraft Carriers Ever Built'
    source=selection_source_data({'unit_roster':[{'name':'Example'}],'fact_sheet':'must cover all 58', 'roster_contract':'exhaustive'})
    assert 'must cover all' not in str(source)
    prompt=_build_selection_prompt(title, selection_settings(20,1),str(source))
    assert title not in prompt
    assert '55 eligible entries and target 20 means select 20' in prompt
    draft=_payload(21); bounded=bound_selection_candidates(draft,20)
    assert len(bounded['unit_roster'])==20 and len(draft['unit_roster'])==21
    assert len(bounded['roster_candidate_overflow'])==1
    assert selection_validation(title,bounded)['passed']
    assert len(bound_selection_candidates(_payload(19),20)['unit_roster'])==19


def test_independent_review_receives_eligibility_subject_and_keeps_factual_failures():
    import json
    from roster_coverage import audit_roster_selection
    class Client:
        async def generate(self, **kwargs):
            self.request=kwargs
            return json.dumps({'passed':False,'sources':[{'url':'https://history.navy.mil/a','supports':'class history'}, {'url':'https://archives.gov/b','supports':'commission record'}], 'findings':[{'candidate':'Machine 0','problem':'unbuilt','required_action':'replace','source_url':'https://archives.gov/b'}], 'summary':'One selected entry was unbuilt'})
    client=Client()
    result=asyncio.run(audit_roster_selection(client,'Every US Submarine Class Ever Built (2026)',_payload()))
    assert 'ELIGIBILITY SUBJECT: US Submarine Class Ever Built (2026)' in client.request['prompt']
    assert 'Every US' not in client.request['prompt']
    assert result['passed'] is False
    assert result['findings'][0]['problem']=='unbuilt'
