import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'skills' / 'video-pipeline'))
from research.agent import ResearchAgent, _parse_research_payload
from error_utils import humanize_error


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def test_valid_research_does_not_repeat_generation():
    client = Client(['{"unit_roster": ["Holland class"]}'])
    result = asyncio.run(ResearchAgent(client).research('Every US Submarine Class Ever Built'))
    assert result['unit_roster'] == ['Holland class']
    assert len(client.calls) == 1


def test_format_repair_reuses_draft_without_search():
    draft = 'Holland class; source https://example.org/history; uncertain date.'
    client = Client([draft, '{"unit_roster": ["Holland class"]}'])
    result = asyncio.run(ResearchAgent(client).research('Every US Submarine Class Ever Built'))
    assert result['unit_roster'] == ['Holland class']
    assert len(client.calls) == 2
    assert draft in client.calls[1]['prompt']
    assert client.calls[1]['tools'] is None
    assert client.calls[1]['temperature'] == 0


def test_repeated_malformed_output_stops_after_one_repair():
    client = Client(['not json', 'still not json'])
    with pytest.raises(RuntimeError, match='after one recovery attempt'):
        asyncio.run(ResearchAgent(client).research('Every US Submarine Class Ever Built'))
    assert len(client.calls) == 2


@pytest.mark.parametrize('text', ['[]', 'null', '42', '"text"', '{}'])
def test_non_object_or_empty_research_is_rejected(text):
    with pytest.raises(json.JSONDecodeError):
        _parse_research_payload(text)


def test_provider_error_is_not_retried_as_formatting():
    client = Client([RuntimeError('provider usage limit')])
    with pytest.raises(RuntimeError, match='provider usage limit'):
        asyncio.run(ResearchAgent(client).research('Every US Submarine Class Ever Built'))
    assert len(client.calls) == 1


def test_live_failure_has_actionable_copy_without_raw_details():
    for error in ['Failed to parse research payload: line 1 column 1 (char 0)',
                  'Research response formatting failed after one recovery attempt']:
        message = humanize_error(error)
        assert 'roster creation stopped' in message
        assert 'Resume' in message
        assert 'char 0' not in message
