"""Tests for C59 (checklist follow-up queue — "tenant-scoped BYOK adapter
for the title-modeling brains"). C49 found title_idea/idea_modeling.py's
generate_modeled_ideas and GapTitleEngine's Claude-calling half both need a
tenant-scoped Anthropic key that doesn't exist as a seam in this codebase —
wrapping them directly as MCP tools would either cross-bill Ryan's own
env-var key for every tenant's call, or require inventing new scoping logic.
This chunk closes that gap and wires the two skipped tools:

  1. generate_modeled_ideas — thin wrap over decompose_title -> extract_
     format -> generate_modeled_ideas (all pre-existing idea_modeling.py
     functions, no new pipeline logic).
  2. generate_gap_titles — thin wrap over GapTitleEngine.generate_titles
     (the Claude-calling half score_title_gap_structures's C49 tool
     deliberately skipped).

Both resolve the tenant's OWN Anthropic key via vault.get_secret(
"anthropic_api_key", tenant_id) — the SAME resolver + error wording
routes/videos.py::rewrite_scene_text (regenerate_scene_text's underlying
route) uses — then construct a tenant-scoped shared.clients.anthropic_
client.AnthropicClient(api_key=...), never the global-env-var
AnthropicClient() the legacy cron pipeline uses. Both are FREE/BYOK
(no confirm_token), matching C49's classification for regenerate_scene_
text/suggest_video_titles.

No live DB, no network, no paid calls — vault.get_secret is patched
directly; the underlying title_idea functions are patched to prove the
SAME callables the legacy pipeline uses are invoked with a tenant-scoped
client (never touching the real Anthropic API).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c59_title_modeling_byok.py -q
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import routes.mcp as mcp_mod  # noqa: E402

_PIPELINE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "skills", "video-pipeline")
)


# =============================================================================
# 1. Tool surface
# =============================================================================

def test_both_tools_present_and_free():
    for name in ("generate_modeled_ideas", "generate_gap_titles"):
        assert name in mcp_mod.TOOL_NAMES, f"missing C59 tool: {name}"
    by_name = {t["name"]: t for t in mcp_mod.TOOLS}
    for name in ("generate_modeled_ideas", "generate_gap_titles"):
        assert "confirm_token" not in by_name[name]["inputSchema"]["properties"], (
            f"{name!r} is FREE/BYOK — must not expose confirm_token"
        )
    assert "generate_modeled_ideas" in mcp_mod._ATOMIC_FREE_HANDLERS
    assert "generate_gap_titles" in mcp_mod._ATOMIC_FREE_HANDLERS
    print("✅ test_both_tools_present_and_free")


def test_no_media_url_fields_in_schema_or_plausible_output_shape():
    """Tenant-scoped inputs only, no media URLs — both tools only take
    text (titles/hook/thesis/facts) and only ever return text (title
    strings, structure metadata), never an image/video/thumbnail URL."""
    by_name = {t["name"]: t for t in mcp_mod.TOOLS}
    for name in ("generate_modeled_ideas", "generate_gap_titles"):
        props = by_name[name]["inputSchema"]["properties"]
        for key in props:
            assert "url" not in key.lower(), f"{name!r} takes a {key!r} arg — unexpected media/URL input"
    print("✅ test_no_media_url_fields_in_schema_or_plausible_output_shape")


# =============================================================================
# 2. Missing tenant key -> the clean Settings error (matches rewrite_scene_text)
# =============================================================================

async def test_generate_modeled_ideas_missing_key_gives_clean_error():
    with patch("vault.get_secret", new=AsyncMock(return_value=None)):
        result = await mcp_mod._call_generate_modeled_ideas(
            "t1", {"seed_titles": ["30 Most Reliable Cars"], "niche_variables": {"topics": ["banks"]}}, "agent",
        )
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Anthropic API key required. Configure it in Settings > API Keys."
    print("✅ test_generate_modeled_ideas_missing_key_gives_clean_error")


async def test_generate_gap_titles_missing_key_gives_clean_error():
    with patch("vault.get_secret", new=AsyncMock(return_value=None)):
        result = await mcp_mod._call_generate_gap_titles(
            "t1", {"hook": "A hook.", "thesis": "A thesis."}, "agent",
        )
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Anthropic API key required. Configure it in Settings > API Keys."
    print("✅ test_generate_gap_titles_missing_key_gives_clean_error")


def test_missing_key_error_matches_rewrite_scene_text_wording():
    """Pin the wording to the SAME string routes/videos.py::rewrite_scene_
    text raises for regenerate_scene_text, so the two BYOK doors give a
    tenant the identical instruction regardless of which tool they hit."""
    src = open(os.path.join(_BACKEND, "routes", "videos.py")).read()
    assert "Anthropic API key required. Configure it in Settings > API Keys." in src
    assert mcp_mod._NO_ANTHROPIC_KEY_ERROR == "Anthropic API key required. Configure it in Settings > API Keys."
    print("✅ test_missing_key_error_matches_rewrite_scene_text_wording")


async def test_key_resolved_via_vault_get_secret_anthropic_api_key_tenant_scoped():
    """Proves the SAME vault.get_secret("anthropic_api_key", tenant_id)
    resolver chat/script BYOK paths use — not a fork, not a new secret
    slot."""
    calls = []

    async def _fake_get_secret(slot, tenant_id):
        calls.append((slot, tenant_id))
        return None  # short-circuit after capturing the call

    with patch("vault.get_secret", new=_fake_get_secret):
        await mcp_mod._call_generate_modeled_ideas(
            "tenant-abc", {"seed_titles": ["X"], "niche_variables": {"a": ["b"]}}, "agent",
        )
    assert calls == [("anthropic_api_key", "tenant-abc")]
    print("✅ test_key_resolved_via_vault_get_secret_anthropic_api_key_tenant_scoped")


# =============================================================================
# 3. Tenant isolation: the client passed into the pipeline functions carries
#    the TENANT's key, never the global-env-var AnthropicClient()
# =============================================================================

async def test_generate_modeled_ideas_uses_tenant_scoped_client_not_global_env():
    sys.path.insert(0, _PIPELINE_ROOT)
    import title_idea.idea_modeling as idea_modeling_mod

    seen_clients = []

    async def _fake_decompose(title, client):
        seen_clients.append(client)
        return {"original_title": title, "variables": {"core_topic": "X"}, "formula": "[X]", "psychological_triggers": []}

    async def _fake_generate(formats, config, client, num_ideas=5):
        seen_clients.append(client)
        return [{"viral_title": "Modeled Title", "based_on_format": "x"}]

    with patch("vault.get_secret", new=AsyncMock(return_value="sk-tenant-key-123")), \
         patch.object(idea_modeling_mod, "decompose_title", new=_fake_decompose), \
         patch.object(idea_modeling_mod, "generate_modeled_ideas", new=_fake_generate):
        result = await mcp_mod._call_generate_modeled_ideas(
            "t1", {"seed_titles": ["30 Most Reliable Cars"], "niche_variables": {"topics": ["banks"]}, "num_ideas": 2}, "agent",
        )

    assert result["isError"] is False
    assert len(seen_clients) == 2
    for client in seen_clients:
        assert client.api_key == "sk-tenant-key-123", "must use the TENANT's key, not the global env-var client"
    import json as _json
    payload = _json.loads(result["content"][0]["text"])
    assert payload["ideas"] == [{"viral_title": "Modeled Title", "based_on_format": "x"}]
    print("✅ test_generate_modeled_ideas_uses_tenant_scoped_client_not_global_env")


async def test_generate_modeled_ideas_calls_the_real_pipeline_functions():
    """Same-callable proof: patches the REAL idea_modeling module functions
    (not a parallel MCP-local reimplementation) and asserts the exact chain
    decompose_title -> extract_format -> generate_modeled_ideas runs."""
    sys.path.insert(0, _PIPELINE_ROOT)
    import title_idea.idea_modeling as idea_modeling_mod

    decompose_calls = []
    generate_calls = []

    async def _fake_decompose(title, client):
        decompose_calls.append(title)
        return {"original_title": title, "variables": {}, "formula": "[F]", "psychological_triggers": []}

    async def _fake_generate(formats, config, client, num_ideas=5):
        generate_calls.append((formats, config, num_ideas))
        return []

    with patch("vault.get_secret", new=AsyncMock(return_value="sk-tenant-key")), \
         patch.object(idea_modeling_mod, "decompose_title", new=_fake_decompose), \
         patch.object(idea_modeling_mod, "generate_modeled_ideas", new=_fake_generate):
        await mcp_mod._call_generate_modeled_ideas(
            "t1", {"seed_titles": ["Title A", "Title B"], "niche_variables": {"topics": ["x"]}, "num_ideas": 3}, "agent",
        )

    assert decompose_calls == ["Title A", "Title B"]
    assert len(generate_calls) == 1
    formats, config, num_ideas = generate_calls[0]
    assert config == {"niche_variables": {"topics": ["x"]}}
    assert num_ideas == 3
    assert formats  # extract_format grouped the two same-formula decomposed titles
    print("✅ test_generate_modeled_ideas_calls_the_real_pipeline_functions")


async def test_generate_modeled_ideas_bad_input_short_circuits_before_any_key_lookup():
    calls = []

    async def _fake_get_secret(slot, tenant_id):
        calls.append(slot)
        return "sk-should-not-be-reached"

    with patch("vault.get_secret", new=_fake_get_secret):
        result = await mcp_mod._call_generate_modeled_ideas("t1", {"seed_titles": [], "niche_variables": {}}, "agent")
    assert result["isError"] is True
    assert calls == [], "must validate inputs before ever resolving a tenant key"
    print("✅ test_generate_modeled_ideas_bad_input_short_circuits_before_any_key_lookup")


async def test_generate_gap_titles_uses_tenant_scoped_client_not_global_env():
    sys.path.insert(0, _PIPELINE_ROOT)

    seen = {}

    class _FakeEngine:
        def __init__(self, client):
            seen["client"] = client

        async def generate_titles(self, story_context, target_count=3):
            seen["story_context"] = story_context
            seen["target_count"] = target_count

            class _T:
                text = "The Truth About X"
                structure = type("S", (), {"value": "hidden_flaw"})()
                structure_confidence = 80
                thumbnail_text = "HIDDEN COST"
                thumbnail_approach = "from_gap"
                reasoning = "financial waste angle"
            return [_T()]

    with patch("vault.get_secret", new=AsyncMock(return_value="sk-tenant-key-456")), \
         patch("title_idea.curiosity_gap.gap_title_engine.GapTitleEngine", _FakeEngine):
        result = await mcp_mod._call_generate_gap_titles(
            "t1", {"hook": "A hidden flaw.", "thesis": "It cost billions.", "facts": ["$100B wasted"], "target_count": 1}, "agent",
        )

    assert result["isError"] is False
    assert seen["client"].api_key == "sk-tenant-key-456"
    assert seen["story_context"] == {"hook": "A hidden flaw.", "thesis": "It cost billions.", "facts": ["$100B wasted"]}
    assert seen["target_count"] == 1
    import json as _json
    payload = _json.loads(result["content"][0]["text"])
    assert payload["titles"][0]["text"] == "The Truth About X"
    assert payload["titles"][0]["structure"] == "hidden_flaw"
    print("✅ test_generate_gap_titles_uses_tenant_scoped_client_not_global_env")


async def test_generate_gap_titles_bad_input_short_circuits_before_any_key_lookup():
    calls = []

    async def _fake_get_secret(slot, tenant_id):
        calls.append(slot)
        return "sk-should-not-be-reached"

    with patch("vault.get_secret", new=_fake_get_secret):
        result = await mcp_mod._call_generate_gap_titles("t1", {"hook": "", "thesis": ""}, "agent")
    assert result["isError"] is True
    assert calls == [], "must validate inputs before ever resolving a tenant key"
    print("✅ test_generate_gap_titles_bad_input_short_circuits_before_any_key_lookup")


# =============================================================================
# 4. score_title_gap_structures still never touches GapTitleEngine (C49
#    invariant) — proves C59's new tools didn't accidentally wire the
#    scoring-only tool to start constructing the engine.
# =============================================================================

async def test_score_title_gap_structures_still_never_constructs_gap_title_engine():
    sys.path.insert(0, _PIPELINE_ROOT)
    import title_idea.curiosity_gap.gap_title_engine as gte_mod

    class _BoomEngine:
        def __init__(self, *a, **k):
            raise AssertionError("score_title_gap_structures must never construct GapTitleEngine")

    with patch.object(gte_mod, "GapTitleEngine", _BoomEngine):
        result = await mcp_mod._call_score_title_gap_structures(
            "t1", {"hook": "A hook", "thesis": "A thesis", "facts": []},
        )
    assert result["isError"] is False
    print("✅ test_score_title_gap_structures_still_never_constructs_gap_title_engine")
