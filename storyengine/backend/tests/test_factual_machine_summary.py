"""Offline contract tests for the source-grounded machine summary writer."""

import json

import pytest

from factual_machine_summary import (
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
async def test_over_100_words_is_rejected_without_truncation():
    paragraph = "I-49 HMS Argus " + " ".join(["carrier"] * 99)
    quote = paragraph
    draft = _draft(paragraph, [(paragraph, "S1-E1", quote)])
    client = ScriptedClient(draft, draft)

    result = await generate_factual_machine_summary(MACHINE, _package(quote), client)

    assert result["passed"] is False
    assert result["word_count"] == 102
    assert result["paragraph"] == paragraph
    assert any("100-word" in warning for warning in result["warnings"])


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
    assert result["review_context_version"] == 2
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
    assert all("model" not in call for call in client.calls)


@pytest.mark.asyncio
async def test_provider_failure_is_propagated():
    quote = "I-49 HMS Argus entered service in 1918."
    client = ScriptedClient(RuntimeError("provider unavailable"))

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await generate_factual_machine_summary(MACHINE, _package(quote), client)


@pytest.mark.asyncio
async def test_review_uses_full_package_alternatives_then_writer_drops_overclaim():
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
    assert result["review_context_version"] == 2
    assert wiki_quote not in client.calls[0]["prompt"]
    assert wiki_quote in client.calls[1]["prompt"]
    assert hansard_quote in client.calls[1]["prompt"]
    assert "untrusted source text" in client.calls[1]["prompt"].lower()
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
    assert result["review_context_version"] == 2
    assert len(client.calls) == 1
    assert "Independently fact-check" in client.calls[0]["prompt"]
