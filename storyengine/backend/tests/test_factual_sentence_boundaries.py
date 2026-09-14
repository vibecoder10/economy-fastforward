"""Regression for sourced aircraft paragraphs rejected at abbreviation periods."""
import pytest
from factual_machine_summary import _sentences, _validate_draft

@pytest.mark.parametrize('sentence', [
    'The AJ Savage was a U.S. Navy carrier-based bomber.',
    'The B-52 has been the backbone of U.S. Air Force strategic deterrence.',
    'The SeaMaster was built by the Glenn L. Martin Company.',
    'The B-2 served the U.S. Air Force.',
])
def test_aircraft_abbreviations_preserve_exact_sentence(sentence):
    assert _sentences(sentence + ' It entered service later.') == [sentence, 'It entered service later.']

@pytest.mark.parametrize('paragraph,expected', [
    ('It served the U.S. It later retired.', ['It served the U.S.', 'It later retired.']),
    ('It used model B. It later changed.', ['It used model B.', 'It later changed.']),
    ('It flew at Mach 0.8. It later landed!', ['It flew at Mach 0.8.', 'It later landed!']),
])
def test_real_sentence_endings_are_retained(paragraph, expected):
    assert _sentences(paragraph) == expected

@pytest.mark.parametrize('mapped', [
    ['The B-2 served the U.S. Air Force.'],
    ['The B-2 served the U.S. Air Force.', 'The B-2 served the U.S. Air Force.', 'It later retired.'],
    ['The B-2 served the U.S. Air Force. It later retired.'],
])
def test_missing_duplicate_or_combined_sentence_mapping_still_fails(mapped):
    _, warnings, _ = _validate_draft('B-2', {
        'paragraph': 'The B-2 served the U.S. Air Force. It later retired.',
        'claim_map': [{'sentence': s, 'citations': []} for s in mapped],
    }, {})
    assert 'claim_map must cover every paragraph sentence exactly once.' in warnings
