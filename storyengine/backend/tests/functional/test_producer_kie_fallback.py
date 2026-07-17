"""Lock: the home Producer works for Kie-only tenants (C04, checklist P0.4).

Before this fix, the home Producer (routes/chat.py: the main intake turn in
chat_turn(), and the onboarding hand-off in _seed_producer()) hard-required
`anthropic_api_key` and told a Kie-only creator to go add one, even though the
in-video co-pilot (_handle_copilot) already had a working fallback: try the
tenant's direct Anthropic key first, else their Kie.ai key
(kie_unified.get_text_client_for_tenant), and only show the friendly "add a
key" message if NEITHER is configured.

This pins:
  1. chat._resolve_producer_client (the shared helper both home entry points
     now call) resolves a KieClaudeClient when only a Kie key is set — no
     raise, no Anthropic-only wall.
  2. It resolves an AnthropicDirectClient when an Anthropic key is set.
  3. It returns None (not a raise) when neither key is configured, which the
     callers turn into the clean "add a key" chat message, never a 500.
  4. producer_prompt.call_producer accepts a resolved `client` (Kie or direct)
     instead of a raw Anthropic api_key, and drives it through the exact same
     `.client.messages.create(...)` call for both provider shapes — proving
     downstream code needs no Anthropic-specific branching.

No network, no DB: heavy runtime deps (database, vault) are stubbed with the
same module-stub pattern used by test_dialogue_alignment.py etc. kie_unified
is imported for real (it's a small, self-contained module) so the KieClaudeClient
/ AnthropicDirectClient types used in the asserts are the genuine ones.
Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_producer_kie_fallback.py -q
"""
import asyncio
import os
import sys
import types
from types import SimpleNamespace

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BACKEND)


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("vault", get_secret=_boom)

import routes.chat as chat  # noqa: E402
from kie_unified import AnthropicDirectClient, KieClaudeClient  # noqa: E402
from producer_prompt import call_producer  # noqa: E402


def _set_get_secret(anthropic_key=None, kie_key=None):
    async def get_secret(slot, tenant_id):
        if slot == "anthropic_api_key":
            return anthropic_key
        if slot == "kie_ai_api_key":
            return kie_key
        return None
    sys.modules["vault"].get_secret = get_secret


def test_resolve_producer_client_falls_back_to_kie():
    """No Anthropic key, Kie key present -> resolves KieClaudeClient, no raise."""
    _set_get_secret(anthropic_key=None, kie_key="fake-kie-key")
    client = asyncio.run(chat._resolve_producer_client("tenant-kie-only"))
    assert isinstance(client, KieClaudeClient), f"expected KieClaudeClient fallback, got {type(client)}"
    assert not isinstance(client, AnthropicDirectClient)
    print("✅ test_resolve_producer_client_falls_back_to_kie")


def test_resolve_producer_client_prefers_anthropic():
    """An Anthropic key, if present, still wins (unchanged existing behavior)."""
    _set_get_secret(anthropic_key="fake-anthropic-key", kie_key="fake-kie-key")
    client = asyncio.run(chat._resolve_producer_client("tenant-both-keys"))
    assert isinstance(client, AnthropicDirectClient), f"expected AnthropicDirectClient, got {type(client)}"
    print("✅ test_resolve_producer_client_prefers_anthropic")


def test_resolve_producer_client_none_when_no_keys():
    """Neither key configured -> None, never a raise (callers turn this into
    the clean 'add a key' chat message, not a 500)."""
    _set_get_secret(anthropic_key=None, kie_key=None)
    client = asyncio.run(chat._resolve_producer_client("tenant-no-keys"))
    assert client is None
    print("✅ test_resolve_producer_client_none_when_no_keys")


def test_home_producer_paths_use_shared_resolver_not_hard_anthropic_gate():
    """Source lock: neither home producer entry point may hard-require
    anthropic_api_key directly anymore -- both must go through the shared
    fallback resolver, exactly like _handle_copilot."""
    src = (open(os.path.join(_BACKEND, "routes", "chat.py")).read())
    assert "await _resolve_producer_client(tenant_id)" in src
    # Both entry points call it: the home intake turn in chat_turn() and the
    # onboarding hand-off in _seed_producer().
    assert src.count("client = await _resolve_producer_client(tenant_id)") >= 2, (
        "expected both _seed_producer and the chat_turn intake turn to resolve "
        "the producer client through the shared fallback helper"
    )
    # The old hard gate must be gone from both producer entry points.
    assert 'api_key = await get_secret("anthropic_api_key", tenant_id)' not in src.split(
        "async def _seed_producer"
    )[1].split("async def")[0], "_seed_producer still hard-gates on anthropic_api_key"
    print("✅ test_home_producer_paths_use_shared_resolver_not_hard_anthropic_gate")


def test_call_producer_drives_resolved_client_not_raw_api_key():
    """call_producer must accept a resolved client (Kie OR Anthropic shape) and
    call it through `.client.messages.create(...)` -- proving no code downstream
    of client resolution assumes an Anthropic-specific object."""
    seen = {}

    class FakeMessages:
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(content=[
                SimpleNamespace(type="text", text='{"assistant_text": "hi there", "phase": "asking"}')
            ])

    class FakeInnerClient:
        messages = FakeMessages()

    class FakeResolvedClient:
        """Mimics the shape both KieClaudeClient and AnthropicDirectClient
        expose: a `.client` attribute with sync `.messages.create(...)`."""
        client = FakeInnerClient()

    data = call_producer(
        [{"role": "user", "content": "make me a video"}], "sys prompt", client=FakeResolvedClient()
    )
    assert data == {"assistant_text": "hi there", "phase": "asking"}
    assert seen["messages"][0]["content"] == "make me a video"
    assert seen["system"] == "sys prompt"
    print("✅ test_call_producer_drives_resolved_client_not_raw_api_key")


def test_call_producer_never_raises_with_nothing_configured():
    """No client, no api_key (the fully-keyless case) -> the soft fallback
    turn, never an unhandled exception / 500."""
    os.environ.pop("ANTHROPIC_API_KEY", None)
    data = call_producer([{"role": "user", "content": "hello"}], "sys prompt")
    assert isinstance(data, dict) and data.get("assistant_text"), (
        "call_producer must fail soft, never raise, even fully keyless"
    )
    print("✅ test_call_producer_never_raises_with_nothing_configured")


if __name__ == "__main__":
    test_resolve_producer_client_falls_back_to_kie()
    test_resolve_producer_client_prefers_anthropic()
    test_resolve_producer_client_none_when_no_keys()
    test_home_producer_paths_use_shared_resolver_not_hard_anthropic_gate()
    test_call_producer_drives_resolved_client_not_raw_api_key()
    test_call_producer_never_raises_with_nothing_configured()
    print("all producer kie-fallback tests passed")
