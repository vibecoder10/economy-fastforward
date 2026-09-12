"""Offline contract tests for the source-grounded machine summary writer."""

import json

import pytest

from factual_machine_summary import (
    REVIEW_CONTEXT_VERSION,
    generate_factual_machine_summary,
    review_existing_factual_summary,
)


MACHINE = "I-49 HMS Argus"
URL = "https://www.naval-history.example/hms-argus"


def _candidate(excerpt_id: str, text: str) -> dict:
    return {
        "excerpt_id": excerpt_id,
        "source_id": "S1",
        "source_title": "Naval history record",
        "source_tier": 2,
        "source_url": URL,
        "locator": excerpt_id,
        "text": text,
        "source_capture_method": "fetched_page",
    }


def _package(*texts: str) -> dict:
    candidates = [_candidate(f"S1-E{index}", text) for index, text in enumerate(texts, start=1)]
    return {
        "passed": True,
        "machine": MACHINE,
        "machine_key": "I49",
        "sources": [{"source_id": "S1", "title": "Naval history record", "url": URL}],
        "candidate_excerpts": candidates,
    }


def _draft(paragraph: str, sentence_quotes: list[tuple[str, str, str]]) -> str:
    return json.dumps({
        "paragraph": paragraph,
        "claim_map": [
            {
                "sentence": sentence,
                "citations": [{"excerpt_id": excerpt_id, "quote": quote}],
            }
            for sentence, excerpt_id, quote in sentence_quotes
        ],
    })


class ScriptedClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_wrong_machine_claim_is_rejected_by_independent_review():
    quote = (
        "I-49 HMS Argus remained in service, while HMS Glorious was sunk in 1940 "
        "after service as an aircraft carrier."
    )
    paragraph = "I-49 HMS Argus was sunk in 1940."
    draft = _draft(paragraph, [(paragraph, "S1-E1", quote)])
    review = json.dumps({
        "passed": False,
        "issues": ["The cited excerpt says HMS Glorious, not I-49 HMS Argus, was sunk in 1940."],
    })
    client = ScriptedClient(draft, review, draft, review)

    result = await generate_factual_machine_summary(MACHINE, _package(quote), client)

    assert result["passed"] is False
    assert any("Glorious" in warning for warning in result["warnings"])
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_invented_numeric_claim_is_rejected_without_review_call():
    quote = "I-49 HMS Argus could carry 15 aircraft in its hangar."
    paragraph = "I-49 HMS Argus could carry 18 aircraft."
    draft = _draft(paragraph, [(paragraph, "S1-E1", quote)])
    client = ScriptedClient(draft, draft)

    result = await generate_factual_machine_summary(MACHINE, _package(quote), client)

    assert result["passed"] is False
    assert any("unsupported numerical" in warning for warning in result["warnings"])
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_bad_citation_quote_is_rejected():
    source_quote = "I-49 HMS Argus entered service in 1918."
    paragraph = "I-49 HMS Argus entered service in 1918."
    draft = _draft(paragraph, [(paragraph, "S1-E1", "Argus entered service during the First World War.")])
    client = ScriptedClient(draft, draft)

    result = await generate_factual_machine_summary(MACHINE, _package(source_quote), client)

    assert result["passed"] is False
    assert any("exact substring" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_single_sentence_over_110_words_is_rejected_without_truncation():
    paragraph = "I-49 HMS Argus " + " ".join(["carrier"] * 109)
    quote = paragraph
    draft = _draft(paragraph, [(paragraph, "S1-E1", quote)])
    client = ScriptedClient(draft, draft)

    result = await generate_factual_machine_summary(MACHINE, _package(quote), client)

    assert result["passed"] is False
    assert result["word_count"] == 112
    assert result["paragraph"] == paragraph
    assert any("110-word" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_valid_plain_factual_summary_passes_without_dramatic_twist():
    quote = "I-49 HMS Argus entered service in 1918 and later served as a training carrier."
    sentence_one = "I-49 HMS Argus entered service in 1918."
    sentence_two = "It later served as a training carrier."
    paragraph = f"{sentence_one} {sentence_two}"
    draft = _draft(
        paragraph,
        [(sentence_one, "S1-E1", quote), (sentence_two, "S1-E1", quote)],
    )
    review = json.dumps({"passed": True, "issues": []})
    client = ScriptedClient(draft, review)

    package = _package(quote)
    # The legacy package flag can be false only because Anton's retired
    # four-beat/six-excerpt gate failed. It is not part of this contract.
    package["passed"] = False
    package["errors"] = ["missing Anton slots: tradeoff, reality"]

    result = await generate_factual_machine_summary(MACHINE, package, client)

    assert result["passed"] is True
    assert result["review_context_version"] == REVIEW_CONTEXT_VERSION
    assert result["paragraph"] == paragraph
    assert result["word_count"] == 14
    assert result["warnings"] == []
    assert result["sources"] == [{
        "excerpt_id": "S1-E1",
        "source_id": "S1",
        "source_title": "Naval history record",
        "source_url": URL,
        "locator": "S1-E1",
        "quote": quote,
        "source_capture_method": "fetched_page",
    }]
    assert len(result["claim_map"]) == 2
    assert len(client.calls) == 2
    assert "opus" in client.calls[0]["model"]
    assert "opus" in client.calls[1]["model"]


@pytest.mark.asyncio
async def test_provider_failure_is_propagated():
    quote = "I-49 HMS Argus entered service in 1918."
    client = ScriptedClient(RuntimeError("provider unavailable"))

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await generate_factual_machine_summary(MACHINE, _package(quote), client)


@pytest.mark.asyncio
async def test_writer_and_review_see_source_disagreement_before_selecting_claims():
    machine = "HMS Ark Royal"
    groki_quote = (
        "HMS Ark Royal's cost exceeded £3 million, making her the most expensive "
        "Royal Navy ship at the time."
    )
    wiki_quote = (
        "HMS Ark Royal was the most expensive non-battleship ordered by the Royal Navy."
    )
    hansard_quote = (
        "The reported cost of HMS Ark Royal was £3 million; HMS Nelson had already cost £7.5 million."
    )
    rows = [("G-E1", "G", "https://grokipedia.example/ark", groki_quote)]
    for index in range(11):
        rows.append((
            f"F{index}-E1",
            f"F{index}",
            f"https://filler{index}.example/ark",
            f"HMS Ark Royal was a Royal Navy ship described in cost records as project number {100 + index}.",
        ))
    # These relevant alternatives deliberately sit beyond the writer's first
    # 12 candidates. Review context must search the full fetched package.
    rows.extend([
        ("W-E1", "W", "https://en.wikipedia.org/wiki/HMS_Ark_Royal", wiki_quote),
        ("H-E1", "H", "https://api.parliament.uk/historic-hansard/ark-royal", hansard_quote),
    ])
    package = {
        "machine": machine,
        "candidate_excerpts": [
            {
                "excerpt_id": excerpt_id,
                "source_id": source_id,
                "source_title": source_id,
                "source_tier": 2,
                "source_url": url,
                "locator": excerpt_id,
                "text": text,
                "source_capture_method": "fetched_page",
            }
            for excerpt_id, source_id, url, text in rows
        ],
        "sources": [
            {"source_id": source_id, "title": source_id, "url": url}
            for _excerpt_id, source_id, url, _text in rows
        ],
    }
    overclaim = "HMS Ark Royal cost more than £3 million and was the most expensive Royal Navy ship at the time."
    corrected = "HMS Ark Royal cost more than £3 million."
    first_draft = _draft(overclaim, [(overclaim, "G-E1", groki_quote)])
    second_draft = _draft(corrected, [(corrected, "G-E1", groki_quote)])
    reject = json.dumps({
        "passed": False,
        "issues": [
            "Other exact-machine sources qualify the record as non-battleship and report HMS Nelson at £7.5 million."
        ],
    })
    accept = json.dumps({"passed": True, "issues": []})
    client = ScriptedClient(first_draft, reject, second_draft, accept)

    result = await generate_factual_machine_summary(machine, package, client)

    assert result["passed"] is True
    assert result["paragraph"] == corrected
    assert result["review_context_version"] == REVIEW_CONTEXT_VERSION
    assert wiki_quote in client.calls[0]["prompt"]
    assert wiki_quote in client.calls[1]["prompt"]
    assert hansard_quote in client.calls[1]["prompt"]
    assert "untrusted source text" in client.calls[1]["prompt"].lower()
    assert "Previous draft to repair" in client.calls[2]["prompt"]
    assert overclaim in client.calls[2]["prompt"]
    assert "do not introduce replacement dates" in client.calls[2]["prompt"]
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_existing_summary_gets_one_version_two_review_without_draft_call():
    quote = "I-49 HMS Argus entered service in 1918 and later served as a training carrier."
    sentence = "I-49 HMS Argus entered service in 1918."
    saved = json.loads(_draft(sentence, [(sentence, "S1-E1", quote)]))
    client = ScriptedClient(json.dumps({"passed": True, "issues": []}))

    result = await review_existing_factual_summary(MACHINE, _package(quote), client, saved)

    assert result["passed"] is True
    assert result["paragraph"] == sentence
    assert result["review_context_version"] == REVIEW_CONTEXT_VERSION
    assert len(client.calls) == 1
    assert "Independently fact-check" in client.calls[0]["prompt"]

@pytest.mark.asyncio
async def test_disputed_sentence_removed_then_independently_reviewed():
    good = 'I-49 HMS Argus served as a training ship.'
    disputed = 'I-49 HMS Argus was the largest carrier.'
    summary = json.loads(_draft(good + ' ' + disputed, [(good, 'S1-E1', good), (disputed, 'S1-E2', disputed)]))
    client = ScriptedClient(json.dumps({'passed': False, 'issues': ['Size record is disputed.'], 'rejected_sentences': [disputed]}), json.dumps({'passed': True, 'issues': []}))
    result = await review_existing_factual_summary(MACHINE, _package(good, disputed), client, summary, allow_sentence_removal=True)
    assert result['passed'] is True
    assert result['paragraph'] == good
    assert len(result['claim_map']) == len(result['sources']) == 1
    assert len(client.calls) == 2
    assert result['removed_disputed_sentences'] == [disputed]


@pytest.mark.asyncio
@pytest.mark.parametrize('rejected', [['unknown sentence'], ['I-49 HMS Argus served as a training ship.']])
async def test_pruning_does_not_accept_unknown_or_empty_draft(rejected):
    sentence = 'I-49 HMS Argus served as a training ship.'
    summary = json.loads(_draft(sentence, [(sentence, 'S1-E1', sentence)]))
    client = ScriptedClient(json.dumps({'passed': False, 'issues': ['Disputed.'], 'rejected_sentences': rejected}))
    result = await review_existing_factual_summary(MACHINE, _package(sentence), client, summary, allow_sentence_removal=True)
    assert result['passed'] is False
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_pruning_cannot_bypass_second_review_failure():
    good = 'I-49 HMS Argus served as a training ship.'
    disputed = 'I-49 HMS Argus was the largest carrier.'
    summary = json.loads(_draft(good + ' ' + disputed, [(good, 'S1-E1', good), (disputed, 'S1-E2', disputed)]))
    client = ScriptedClient(json.dumps({'passed': False, 'issues': ['Record disputed.'], 'rejected_sentences': [disputed]}), json.dumps({'passed': False, 'issues': ['Remaining claim disputed.'], 'rejected_sentences': [good]}))
    result = await review_existing_factual_summary(MACHINE, _package(good, disputed), client, summary, allow_sentence_removal=True)
    assert result['passed'] is False
    assert len(client.calls) == 2

@pytest.mark.asyncio
async def test_excerpt_id_only_citation_attaches_original_source_text():
    sentence = 'I-49 HMS Argus served as a training ship.'
    summary = {'paragraph': sentence, 'claim_map': [{'sentence': sentence, 'citations': [{'excerpt_id': 'S1-E1'}]}]}
    client = ScriptedClient(json.dumps({'passed': True, 'issues': []}))
    result = await review_existing_factual_summary(MACHINE, _package(sentence), client, summary)
    assert result['passed']
    assert result['sources'][0]['quote'] == sentence
    assert result['sources'][0]['source_url'] == URL
    assert 'opus' in client.calls[0]['model']

@pytest.mark.asyncio
async def test_video_subject_reaches_writer_and_review_for_namesake_disambiguation():
    sentence = 'I-49 HMS Argus served as a training carrier.'
    draft = {'paragraph': sentence, 'claim_map': [{'sentence': sentence, 'citations': [{'excerpt_id': 'S1-E1'}]}]}
    client = ScriptedClient(json.dumps(draft), json.dumps({'passed': True, 'issues': []}))
    context = 'Every British Aircraft Carrier Class Ever Built'
    result = await generate_factual_machine_summary(MACHINE, _package(sentence), client, subject_context=context)
    assert result['passed']
    assert all(context in call['prompt'] for call in client.calls)

@pytest.mark.asyncio
async def test_word_cap_drops_whole_sentence_and_still_requires_factual_review():
    first = 'I-49 HMS Argus served as a training ship.'
    last = 'I-49 HMS Argus ' + ' '.join(['carrier'] * 109) + '.'
    draft = _draft(first + ' ' + last, [(first, 'S1-E1', first), (last, 'S1-E2', last)])
    client = ScriptedClient(json.dumps({'passed': False, 'issues': ['Remaining sentence is unsupported.']}))
    result = await review_existing_factual_summary(MACHINE, _package(first, last), client, draft)
    assert result['paragraph'] == first
    assert result['word_count'] <= 100
    assert not result['passed']
    assert len(result['sources']) == 1
    assert len(client.calls) == 1
    assert 'Remaining sentence' in result['warnings'][0]

@pytest.mark.asyncio
@pytest.mark.parametrize('words', [101, 105, 110])
async def test_ten_percent_tolerance_preserves_supported_paragraph(words):
    paragraph = 'I-49 HMS Argus ' + ' '.join(['carrier'] * (words - 3))
    draft = _draft(paragraph, [(paragraph, 'S1-E1', paragraph)])
    client = ScriptedClient(json.dumps({'passed': True, 'issues': []}))
    result = await review_existing_factual_summary(MACHINE, _package(paragraph), client, draft)
    assert result['passed']
    assert result['word_count'] == words
    assert result['paragraph'] == paragraph
    assert len(client.calls) == 1

@pytest.mark.asyncio
async def test_carrier_title_rejects_real_but_wrong_majestic_battleship_namesake():
    machine = 'Majestic class'
    wrong = 'The Majestic-class battleship was a pre-dreadnought battleship of the Royal Navy.'
    right = 'The Majestic class aircraft carriers were part of the 1942 Design Light Fleet Carrier programme.'
    package = {'machine': machine, 'machine_key': 'MAJESTICCLASS', 'candidate_excerpts': [
        {**_candidate('W1', wrong), 'source_url': 'https://en.wikipedia.org/wiki/Majestic-class_battleship'},
        {**_candidate('C1', right), 'source_url': 'https://naval-encyclopedia.com/cold-war/uk/majestic-class-aircraft-carriers.php'}]}
    draft = _draft(wrong, [(wrong, 'W1', wrong)])
    client = ScriptedClient()
    result = await review_existing_factual_summary(machine, package, client, draft, subject_context='Every British Aircraft Carrier Class Ever Built')
    assert not result['passed']
    assert any('wrong-machine' in warning or 'carrier role' in warning for warning in result['warnings'])
    assert not client.calls
    good_client = ScriptedClient(json.dumps({'passed': True, 'issues': []}))
    good = await review_existing_factual_summary(machine, package, good_client, _draft(right, [(right, 'C1', right)]), subject_context='Every British Aircraft Carrier Class Ever Built')
    assert good['passed']
    assert good['review_context_version'] == REVIEW_CONTEXT_VERSION
    assert good['subject_context'] == 'Every British Aircraft Carrier Class Ever Built'

@pytest.mark.asyncio
async def test_wrong_subject_repair_discards_namesake_instead_of_preserving_its_facts():
    sentence = 'I-49 HMS Argus served as a training carrier.'
    draft = _draft(sentence, [(sentence, 'S1-E1', sentence)])
    client = ScriptedClient(draft, json.dumps({'passed': True, 'issues': []}))
    result = await generate_factual_machine_summary(MACHINE, _package(sentence), client,
        subject_context='British aircraft carriers',
        previous_summary={'passed': False, 'paragraph': 'A namesake was a battleship.', 'warnings': ['The paragraph must identify this machine in its aircraft-carrier role; a namesake is insufficient.']})
    assert result['passed']
    assert 'Discard that draft' in client.calls[0]['prompt']
    assert 'Keep only uncontested facts already in the previous draft' not in client.calls[0]['prompt']


@pytest.mark.asyncio
async def test_cached_ai_encyclopedia_cannot_validate_historical_record():
    machine = "91 Ark Royal (1938)"
    bad = "HMS Ark Royal was the first purpose-built aircraft carrier for the Royal Navy."
    good = "HMS Ark Royal was an aircraft carrier commissioned in 1938."
    package = _package(bad, good)
    package["machine"] = machine
    package["sources"] = []
    package["candidate_excerpts"][0]["source_url"] = "https://grokipedia.com/page/HMS_Ark_Royal_(91)"
    draft = _draft(bad, [(bad, "S1-E1", bad)])
    client = ScriptedClient()
    result = await review_existing_factual_summary(machine, package, client, draft,
        subject_context="Every British Aircraft Carrier Class Ever Built (2026)")
    assert result["passed"] is False
    assert any("unknown or wrong-machine excerpt" in warning for warning in result["warnings"])
    assert not client.calls


@pytest.mark.asyncio
async def test_repair_uses_historical_sources_without_ai_encyclopedia():
    machine = "91 Ark Royal (1938)"
    bad = "HMS Ark Royal was the first purpose-built aircraft carrier for the Royal Navy."
    good = "HMS Ark Royal was an aircraft carrier commissioned in 1938."
    package = _package(bad, good)
    package["machine"] = machine
    package["sources"] = []
    package["candidate_excerpts"][0]["source_url"] = "https://www.grokipedia.com/page/HMS_Ark_Royal_(91)"
    draft = _draft(good, [(good, "S1-E2", good)])
    client = ScriptedClient(draft, {"passed": True, "issues": []})
    result = await generate_factual_machine_summary(machine, package, client,
        subject_context="Every British Aircraft Carrier Class Ever Built (2026)")
    assert result["passed"] is True
    assert bad not in client.calls[0]["prompt"]
    assert result["sources"][0]["source_url"] == URL


@pytest.mark.asyncio
@pytest.mark.parametrize("claim", [
    "I-49 HMS Argus was the first purpose-built aircraft carrier.",
    "Four ships were laid down as part of the I-49 HMS Argus class.",
    "Only four ships of the I-49 HMS Argus class were completed before the war ended.",
    "I-49 HMS Argus was the largest aircraft carrier in the world.",
])
async def test_derivative_record_or_construction_count_needs_corroboration(claim):
    package = _package(claim)
    package["candidate_excerpts"][0]["source_tier"] = 3
    client = ScriptedClient()
    result = await review_existing_factual_summary(MACHINE, package, client,
        _draft(claim, [(claim, "S1-E1", claim)]))
    assert result["passed"] is False
    assert any("lacks independent corroboration" in w for w in result["warnings"])
    assert not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("second_url,passed", [("https://independent.example/argus", True),
    ("https://www.naval-history.example/another-page", False)])
async def test_record_corroboration_requires_distinct_hosts_then_factual_review(second_url, passed):
    claim = "I-49 HMS Argus was the largest aircraft carrier in the world."
    package = _package(claim, claim)
    package["sources"] = []
    for row in package["candidate_excerpts"]:row["source_tier"] = 3
    package["candidate_excerpts"][1]["source_url"] = second_url
    draft = {"paragraph": claim, "claim_map": [{"sentence":claim,
        "citations":[{"excerpt_id":"S1-E1"},{"excerpt_id":"S1-E2"}]}]}
    client = ScriptedClient({"passed":True,"issues":[]})
    result = await review_existing_factual_summary(MACHINE,package,client,draft)
    assert result["passed"] is passed
    assert len(client.calls) == int(passed)


@pytest.mark.asyncio
async def test_time_period_is_not_a_historical_record():
    claim = "I-49 HMS Argus spent the first nine months of the war training pilots."
    package = _package(claim)
    package["candidate_excerpts"][0]["source_tier"] = 3
    client = ScriptedClient({"passed":True,"issues":[]})
    result = await review_existing_factual_summary(MACHINE,package,client,
        _draft(claim,[(claim,"S1-E1",claim)]))
    assert result["passed"] is True

@pytest.mark.asyncio
async def test_uncorroborated_record_repair_keeps_room_for_ordinary_sourced_facts():
    good = 'I-49 HMS Argus served as a training aircraft carrier.'
    previous = {'passed':False, 'paragraph':'I-49 HMS Argus was the largest carrier.',
        'warnings':['claim_map row 1 historical record or class construction count lacks independent corroboration.']}
    client = ScriptedClient(_draft(good,[(good,'S1-E1',good)]),{'passed':True,'issues':[]})
    result = await generate_factual_machine_summary(MACHINE,_package(good),client,previous_summary=previous)
    assert result['passed'] is True
    assert 'You may add other ordinary facts from EVIDENCE' in client.calls[0]['prompt']
    assert 'Do not replace a disputed record/count with another record/count' in client.calls[0]['prompt']
