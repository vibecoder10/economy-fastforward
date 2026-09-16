from roster_selection import selection_settings, selection_validation, selection_fingerprint


def payload(rows):
    return {'unit_roster': rows,
            'recommended_final_roster': [' '.join(filter(None, [r.get('designation'), r['name']])) for r in rows],
            'roster_selection': {'version': 1, 'settings': selection_settings(len(rows))}}


def test_named_member_passes_and_class_range_fails():
    named = payload([{'name': 'USS Tang', 'designation': 'SS-563', 'class_name': 'Tang class'}])
    assert selection_validation('US Submarine Classes', named)['passed']
    legacy = payload([{'name': 'Tang class', 'designation': 'SS-563 through SS-568'}])
    assert not selection_validation('US Submarine Classes', legacy)['passed']


def test_two_members_of_same_class_fail():
    rows = [{'name': 'USS Tang', 'designation': 'SS-563', 'class_name': 'Tang class'},
            {'name': 'USS Gudgeon', 'designation': 'SS-567', 'class_name': 'Tang-class'}]
    result = selection_validation('US Submarine Classes', payload(rows))
    assert not result['passed']
    assert any('only one machine per class' in warning for warning in result['warnings'])


def test_missing_class_and_multi_designation_fail():
    for designation in ('SS-563 through SS-568', 'SS-563 to SS-568', 'SS-563–568', 'SS-563, SS-567', 'SS-563+'):
        assert not selection_validation('Submarine classes', payload([{'name': 'USS Tang', 'designation': designation, 'class_name': 'Tang'}]))['passed']
    assert not selection_validation('Submarine classes', payload([{'name': 'USS Tang', 'designation': 'SS-563'}]))['passed']


def test_non_class_selection_and_singleton_preserved():
    assert selection_validation('Experimental aircraft', payload([{'name': 'Example', 'designation': 'X-1'}]))['passed']
    assert selection_validation('Submarine classes', payload([{'name': 'USS Nautilus', 'designation': 'SSN-571', 'class_name': 'Nautilus'}]))['passed']


def test_representative_identity_changes_audit_fingerprint():
    p = payload([{'name': 'USS Tang', 'designation': 'SS-563', 'class_name': 'Tang'}])
    before = selection_fingerprint('Submarine classes', p)
    p['unit_roster'][0].update(name='USS Gudgeon', designation='SS-567')
    assert before != selection_fingerprint('Submarine classes', p)


def test_selection_prompt_requires_one_member_and_preserves_target():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"))
    from research.agent import _build_selection_prompt
    prompt = _build_selection_prompt('Every US Submarine Class Ever Built', selection_settings(20), None)
    assert 'Select exactly 20' in prompt
    assert 'Any source-verified member is acceptable' in prompt
    assert 'class_name' in prompt
    assert 'Do not select two machines from the same class' in prompt
