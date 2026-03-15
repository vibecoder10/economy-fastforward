"""Tests for json_utils.parse_json_response."""

import pytest
from json_utils import parse_json_response


class TestDirectParse:
    """Step 1: Direct json.loads."""

    def test_clean_json_object(self):
        assert parse_json_response('{"key": "value"}') == {"key": "value"}

    def test_clean_json_array(self):
        assert parse_json_response('[1, 2, 3]', default=[]) == [1, 2, 3]

    def test_empty_string(self):
        assert parse_json_response("") == {}

    def test_none_default(self):
        assert parse_json_response("not json", default=None) is None


class TestMarkdownFences:
    """Step 2: Strip markdown fences."""

    def test_json_fenced_block(self):
        text = '```json\n{"key": "value"}\n```'
        assert parse_json_response(text) == {"key": "value"}

    def test_plain_fenced_block(self):
        text = '```\n{"key": "value"}\n```'
        assert parse_json_response(text) == {"key": "value"}

    def test_fenced_with_trailing_newline(self):
        text = '```json\n{"a": 1}\n```\n'
        assert parse_json_response(text) == {"a": 1}


class TestJsonExtraction:
    """Step 3: Extract JSON substring from surrounding text."""

    def test_json_with_prose_before(self):
        text = 'Here is the result:\n{"key": "value"}'
        assert parse_json_response(text) == {"key": "value"}

    def test_json_with_prose_after(self):
        text = '{"key": "value"}\nLet me know if you need changes.'
        assert parse_json_response(text) == {"key": "value"}

    def test_array_extraction(self):
        text = "Here are the results:\n[1, 2, 3]"
        assert parse_json_response(text, default=[]) == [1, 2, 3]


class TestTrailingCommaFix:
    """Step 4: Fix common issues like trailing commas."""

    def test_trailing_comma_in_object(self):
        text = '{"a": 1, "b": 2,}'
        assert parse_json_response(text) == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        text = '[1, 2, 3,]'
        assert parse_json_response(text, default=[]) == [1, 2, 3]


class TestDefaultReturn:
    """Fallback behavior on unparseable input."""

    def test_default_empty_dict(self):
        assert parse_json_response("completely unparseable text") == {}

    def test_default_empty_list(self):
        assert parse_json_response("not json", default=[]) == []

    def test_default_none(self):
        assert parse_json_response("not json", default=None) is None

    def test_whitespace_only(self):
        assert parse_json_response("   \n  ") == {}
