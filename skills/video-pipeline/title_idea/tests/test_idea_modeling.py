"""Tests for idea_modeling.py's Claude-calling functions (C59 — the tenant-
scoped BYOK adapter for the title-modeling brains).

BUG THIS PINS: before C59, decompose_title/generate_modeled_ideas called
``anthropic_client.messages.create(...)`` — the raw anthropic.AsyncAnthropic
SDK shape. Every REAL caller in this codebase (TrendingIdeaBot.self.anthropic,
orchestrator/pipeline.py's --more-ideas path, and now the tenant-scoped MCP
path in storyengine/backend/routes/mcp.py) instead passes a
shared.clients.anthropic_client.AnthropicClient instance, whose ONLY
Claude-calling method is .generate() — it has no .messages attribute at all.
So every real call silently failed (AttributeError swallowed by the broad
``except Exception``, returning None/[]) even though the client was already
correctly threaded through as a parameter — the wiring was fine, the
*contract* on the other end was wrong. Fixed to call the wrapper's
.generate(), the same interface GapTitleEngine._call_claude_for_titles
already used successfully — so no NEW optional parameter was needed on
either function; the pre-existing ``anthropic_client`` parameter already was
the injection point once its contract matched what callers pass.

Uses a minimal FakeAnthropicClient (no .messages attribute, matching the
real wrapper exactly) instead of importing the real AnthropicClient class,
so this test doesn't depend on shared.clients.__init__'s heavier optional
dependency chain (google_client etc.) — keeps this unit test hermetic.

Run: cd skills/video-pipeline && python -m pytest title_idea/tests/test_idea_modeling.py -q
"""
import asyncio
import json

from title_idea.idea_modeling import decompose_title, generate_modeled_ideas, extract_format


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeAnthropicClient:
    """Stand-in for shared.clients.anthropic_client.AnthropicClient's public
    contract: an async .generate(prompt, system_prompt="", model=...,
    max_tokens=...) -> str method, and nothing else. Deliberately has NO
    .messages attribute — the real wrapper doesn't either — so a test
    against this fake catches the exact same bug a real AnthropicClient()
    instance would."""

    def __init__(self, response_text):
        self.response_text = response_text
        self.calls = []

    async def generate(self, prompt, system_prompt="", model=None, max_tokens=4096, temperature=1.0, tools=None):
        self.calls.append({
            "prompt": prompt, "system_prompt": system_prompt,
            "model": model, "max_tokens": max_tokens,
        })
        return self.response_text


class TestDecomposeTitleUsesGenerateContract:
    def test_returns_parsed_dict_not_none(self):
        """Non-vacuous: on pre-C59 code this returns None (AttributeError on
        .messages, swallowed by `except Exception`) for ANY real caller's
        client — this is the exact silent-failure bug."""
        fake = FakeAnthropicClient(json.dumps({
            "variables": {"core_topic": "Cars", "number": "30"},
            "formula": "[Number] + [Core Topic]",
            "psychological_triggers": ["scale", "practical_value"],
        }))

        result = run_async(decompose_title("30 Most Reliable Cars", fake))

        assert result is not None, (
            "decompose_title silently returned None — it's not calling "
            "the client's .generate() contract"
        )
        assert result["original_title"] == "30 Most Reliable Cars"
        assert result["variables"]["core_topic"] == "Cars"
        assert result["formula"] == "[Number] + [Core Topic]"
        assert result["psychological_triggers"] == ["scale", "practical_value"]

    def test_calls_generate_with_title_as_prompt_and_system_prompt(self):
        fake = FakeAnthropicClient(json.dumps({"variables": {}, "formula": "", "psychological_triggers": []}))

        run_async(decompose_title("How China Engineered the Crisis", fake))

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["prompt"] == "How China Engineered the Crisis"
        assert "decompose it into typed variables" in call["system_prompt"]
        assert call["max_tokens"] == 1024


class TestGenerateModeledIdeasUsesGenerateContract:
    def test_returns_parsed_list_not_empty(self):
        """Non-vacuous: pre-C59 code returns [] (AttributeError swallowed)
        for ANY real caller's client — same silent-failure bug."""
        formats = [{"format_id": "fmt1", "formula": "[X]", "example_titles": ["a"], "times_seen": 1}]
        config = {"niche_variables": {"topics": ["dollar collapse"]}}
        fake = FakeAnthropicClient(json.dumps([
            {"viral_title": "How China Engineered the Reserve Collapse", "based_on_format": "fmt1"},
        ]))

        ideas = run_async(generate_modeled_ideas(formats, config, fake, num_ideas=1))

        assert ideas == [{"viral_title": "How China Engineered the Reserve Collapse", "based_on_format": "fmt1"}]

    def test_calls_generate_with_niche_variables_in_prompt(self):
        formats = [{"format_id": "fmt1", "formula": "[X]", "example_titles": ["a"], "times_seen": 1}]
        config = {"niche_variables": {"topics": ["dollar collapse"]}}
        fake = FakeAnthropicClient(json.dumps([]))

        run_async(generate_modeled_ideas(formats, config, fake, num_ideas=3))

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert "dollar collapse" in call["prompt"]
        assert call["max_tokens"] == 2048
        # generate_modeled_ideas has never taken a system_prompt (single
        # combined user prompt) — confirm that's still the case, unchanged.
        assert call["system_prompt"] == ""

    def test_empty_formats_short_circuits_without_calling_client(self):
        """Pre-existing behavior, unchanged by C59: no API call when there's
        nothing to model from."""
        fake = FakeAnthropicClient(json.dumps([]))
        ideas = run_async(generate_modeled_ideas([], {"niche_variables": {}}, fake))
        assert ideas == []
        assert fake.calls == []


class TestFullDecomposeExtractGenerateChain:
    """The chain the new MCP generate_modeled_ideas tool (routes/mcp.py)
    actually drives: decompose_title (per seed title) -> extract_format ->
    generate_modeled_ideas. Proves the three EXISTING functions compose
    without any new pipeline logic — a thin wrap, not new capability."""

    def test_seed_titles_to_ideas(self):
        fake = FakeAnthropicClient("")  # overridden per-call below

        responses = iter([
            json.dumps({"variables": {"core_topic": "Cars"}, "formula": "[Core Topic]", "psychological_triggers": []}),
            json.dumps({"variables": {"core_topic": "Banks"}, "formula": "[Core Topic]", "psychological_triggers": []}),
            json.dumps([{"viral_title": "The Truth About Banks", "based_on_format": "core_topic"}]),
        ])

        async def fake_generate(prompt, system_prompt="", model=None, max_tokens=4096, temperature=1.0, tools=None):
            return next(responses)

        fake.generate = fake_generate

        async def chain():
            decomposed = [
                await decompose_title("The Truth About Cars", fake),
                await decompose_title("The Truth About Banks", fake),
            ]
            formats = extract_format(decomposed)
            return await generate_modeled_ideas(formats, {"niche_variables": {"topics": ["banks"]}}, fake, num_ideas=1)

        ideas = run_async(chain())
        assert ideas == [{"viral_title": "The Truth About Banks", "based_on_format": "core_topic"}]
