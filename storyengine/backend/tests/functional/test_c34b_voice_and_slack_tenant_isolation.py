"""Tests for C34b (checklist S10-2 + S10-3, docs/reports/2026-07-17-
storyengine-agent-audit-findings.md §S10):

S10-2 — default ElevenLabs voice was Ryan's own cloned voice
(`pipeline_constants.py` `Models.VOICE_ID` = G17SuINrv2H9FC6nvetn). Worse, a
tenant with no vault-configured `elevenlabs_voice_id` got whatever
ELEVENLABS_VOICE_ID happened to sit in THIS SHARED PROCESS'S env — restored
on purpose in `PipelineExecutor._ensure_initialized` by a prior fix (DvsU,
2026-07-07) that meant to preserve Ryan's legacy single-tenant .env default
for any tenant that skipped the voice step. That "restore" is the real bug:
Ryan's own cloned voice narrates for every SaaS tenant who doesn't set their
own voice.

Fix pinned here:
  A. `elevenlabs_voice_id` removed from `VOICE_CONFIG_KEYS` (the process-env
     restore-eligible set) in `pipeline_executor.py` — only
     `elevenlabs_model_id` / `elevenlabs_voice_style` (non-identity engine
     tuning) still restore from a process default.
  B. `ElevenLabsClient` construction in `_ensure_initialized` now passes
     `voice_id` EXPLICITLY, resolved fresh per tenant from THIS tenant's own
     env state (vault-loaded, or absent) with a literal tenant-neutral stock
     fallback (`STOCK_NARRATOR_VOICE_ID` = ElevenLabs premade "Rachel",
     21m00Tcm4TlvDq8ikWAM) — never `ElevenLabsClient.DEFAULT_VOICE_ID`
     (frozen at first import in this shared process).
  C. `Models.VOICE_ID`'s hardcoded literal fallback (pipeline_constants.py)
     changed from Ryan's clone id to the same stock voice — covers Ryan's own
     legacy single-tenant cron pipeline (separate process/env) if IT ever
     runs with no ELEVENLABS_VOICE_ID set either.

S10-3 — `SlackClient` posted tenant content (thumbnails/titles/URLs) into
Ryan's now-retired prototype Slack channel (C0A9U1X8NSW) from SaaS-reachable
legacy bot code, whenever a bot token happened to be present in that shared
process's env — no per-tenant scoping existed at all. Per Ryan's decision
(tasks/decisions.md 2026-07-19, "I don't use ... the Slack channel anymore"):
notifications are now OPT-IN via `SLACK_NOTIFICATIONS_ENABLED` (default
"false") in ADDITION to a bot token — closes the class of bug for any future
legacy stage reachable from SaaS, not just the two flagged call sites.

No live DB/network: pipeline_executor's `vault.get_secret` and `database.*`
are monkeypatched; SlackClient's own WebClient is never exercised beyond
construction (no real HTTP).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c34b_voice_and_slack_tenant_isolation.py -q
"""
import asyncio
import inspect
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

# Simulates whatever was sitting in this shared process's env BEFORE a
# tenant-scoped run — e.g. Ryan's own legacy single-tenant .env default that
# used to leak. Deliberately NOT the real clone id (no need to reference it).
_SIMULATED_LEAKED_IDENTITY_VOICE = "G17SuINrv2H9FC6nvetn"

# Env vars pipeline_executor._ensure_initialized reads/writes; snapshot and
# restore around every test so leakage between tests (and into the rest of
# the suite) is impossible.
_TOUCHED_ENV_VARS = (
    "ANTHROPIC_API_KEY", "AIRTABLE_API_KEY", "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "ELEVENLABS_VOICE_STYLE",
    "KIE_AI_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "WAVESPEED_API_KEY", "ANTHROPIC_BASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_env():
    snapshot = {k: os.environ.get(k) for k in _TOUCHED_ENV_VARS}
    yield
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _make_executor(tenant_id: str, vault_values: dict):
    """A fresh, un-initialized PipelineExecutor whose vault reads are
    monkeypatch-free (patched directly on the module) and controlled by
    `vault_values` (secret name -> value, only for THIS tenant)."""
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = tenant_id
    executor._initialized = False
    executor._pipeline = None

    async def fake_get_secret(name, tid):
        assert tid == tenant_id, "must only ever ask the vault for THIS tenant's secrets"
        return vault_values.get(name)

    return executor, fake_get_secret


# ---------------------------------------------------------------------------
# A. Voice fallback chain — the cross-tenant leak fix
# ---------------------------------------------------------------------------

def test_no_vault_voice_and_no_leaked_process_env_gets_stock_default(monkeypatch):
    """Tenant with nothing configured anywhere: must get the literal stock
    voice, never a guess."""
    for k in _TOUCHED_ENV_VARS:
        os.environ.pop(k, None)

    executor, fake_get_secret = _make_executor(TENANT_A, {
        "elevenlabs_api_key": "fake-key-for-test",
    })
    monkeypatch.setattr(pe_mod, "get_secret", fake_get_secret)

    asyncio.run(executor._ensure_initialized())

    assert executor._pipeline.elevenlabs is not None, "ElevenLabsClient must have constructed"
    assert executor._pipeline.elevenlabs.voice_id == pe_mod.STOCK_NARRATOR_VOICE_ID
    assert executor._pipeline.elevenlabs.voice_id == "21m00Tcm4TlvDq8ikWAM"


def test_tenant_with_own_vault_voice_gets_theirs(monkeypatch):
    executor, fake_get_secret = _make_executor(TENANT_A, {
        "elevenlabs_api_key": "fake-key-for-test",
        "elevenlabs_voice_id": "tenant-a-own-voice-999",
    })
    monkeypatch.setattr(pe_mod, "get_secret", fake_get_secret)

    asyncio.run(executor._ensure_initialized())

    assert executor._pipeline.elevenlabs.voice_id == "tenant-a-own-voice-999"


def test_cross_tenant_leak_regression_pin(monkeypatch):
    """THE bug: before this fix, whatever ELEVENLABS_VOICE_ID happened to
    already be sitting in this shared process's env (another identity's
    value — e.g. Ryan's own legacy .env default) got restored and handed to
    a tenant who never configured a voice. Simulate that pre-existing env
    state and prove tenant B never receives it."""
    os.environ["ELEVENLABS_VOICE_ID"] = _SIMULATED_LEAKED_IDENTITY_VOICE

    executor, fake_get_secret = _make_executor(TENANT_B, {
        "elevenlabs_api_key": "fake-key-for-test",
        # Tenant B deliberately sets NO elevenlabs_voice_id.
    })
    monkeypatch.setattr(pe_mod, "get_secret", fake_get_secret)

    asyncio.run(executor._ensure_initialized())

    resolved = executor._pipeline.elevenlabs.voice_id
    assert resolved != _SIMULATED_LEAKED_IDENTITY_VOICE, (
        "cross-tenant leak: tenant with no vault voice received another "
        "identity's process-env voice id instead of the stock default"
    )
    assert resolved == pe_mod.STOCK_NARRATOR_VOICE_ID
    # The env var itself must not have been silently restored either —
    # proves the leak is closed at the source, not just masked at read time.
    assert os.environ.get("ELEVENLABS_VOICE_ID") is None


def test_model_and_style_tuning_keys_still_restore_from_process_default(monkeypatch):
    """Non-identity engine tuning (model_id/style) intentionally keeps the
    pre-C34b restore-from-process-default behavior — only voice_id (the
    identity leak) was removed from the restore set."""
    os.environ["ELEVENLABS_MODEL_ID"] = "eleven_multilingual_v2"
    os.environ["ELEVENLABS_VOICE_STYLE"] = "0.4"

    executor, fake_get_secret = _make_executor(TENANT_A, {
        "elevenlabs_api_key": "fake-key-for-test",
    })
    monkeypatch.setattr(pe_mod, "get_secret", fake_get_secret)

    asyncio.run(executor._ensure_initialized())

    assert os.environ.get("ELEVENLABS_MODEL_ID") == "eleven_multilingual_v2"
    assert os.environ.get("ELEVENLABS_VOICE_STYLE") == "0.4"


def test_voice_config_keys_excludes_voice_id_in_source():
    """Static pin on the actual restore-eligible tuple, so a future edit that
    re-adds elevenlabs_voice_id to VOICE_CONFIG_KEYS is caught even if the
    runtime tests above are skipped for some reason."""
    src = inspect.getsource(pe_mod.PipelineExecutor._ensure_initialized)
    assert 'VOICE_CONFIG_KEYS = ("elevenlabs_model_id", "elevenlabs_voice_style")' in src
    # elevenlabs_voice_id must still be LOADED from vault (so a tenant's own
    # choice reaches env) — just not process-default-restored.
    assert '"elevenlabs_voice_id"' in src


def test_stock_narrator_voice_constant_is_not_a_clone_id():
    assert pe_mod.STOCK_NARRATOR_VOICE_ID == "21m00Tcm4TlvDq8ikWAM"
    assert pe_mod.STOCK_NARRATOR_VOICE_ID != "G17SuINrv2H9FC6nvetn"


def test_pipeline_constants_default_voice_is_no_longer_the_clone():
    """Source-level check (not import-time, since Models.VOICE_ID bakes in
    whatever ELEVENLABS_VOICE_ID happens to be set at first import in THIS
    process) — the hardcoded literal fallback itself must not be the clone."""
    legacy_pipeline_dir = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
    src = open(os.path.join(legacy_pipeline_dir, "orchestrator", "pipeline_constants.py")).read()
    assert 'os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")' in src
    # The clone id may still appear in an explanatory comment (history) — the
    # thing that must be gone is the CODE using it as the actual fallback.
    assert 'os.getenv("ELEVENLABS_VOICE_ID", "G17SuINrv2H9FC6nvetn")' not in src


# ---------------------------------------------------------------------------
# B. SlackClient — silent by default for SaaS-reachable legacy stages
# ---------------------------------------------------------------------------

from shared.clients.slack_client import SlackClient  # noqa: E402


def test_slack_disabled_by_default_even_with_a_bot_token_present(monkeypatch):
    """The exact SaaS-reachable scenario: a bot token sits in the shared
    process's env (as it would on the storyengine backend if one were ever
    set), but SLACK_NOTIFICATIONS_ENABLED is unset. Must be silent."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake-token")
    monkeypatch.delenv("SLACK_NOTIFICATIONS_ENABLED", raising=False)

    client = SlackClient()

    assert client.enabled is False
    assert client.client is None

    result = client.send_message("tenant content that must never post")
    assert result is None  # no HTTP attempted — self.client is None, never touched


def test_slack_disabled_when_neither_token_nor_flag_set(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_NOTIFICATIONS_ENABLED", raising=False)

    client = SlackClient()
    assert client.enabled is False
    assert client.client is None


def test_slack_enabled_only_with_explicit_flag_and_token(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake-token")
    monkeypatch.setenv("SLACK_NOTIFICATIONS_ENABLED", "true")

    client = SlackClient()
    assert client.enabled is True
    assert client.client is not None


def test_slack_flag_alone_without_a_token_stays_disabled(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_NOTIFICATIONS_ENABLED", "true")

    client = SlackClient()
    assert client.enabled is False
    assert client.client is None


def test_notify_is_a_true_no_op_when_disabled(monkeypatch):
    """notify() is the fire-and-forget helper legacy bot code actually calls
    (e.g. voice/run.py's notify_voice_start/done) — must not raise and must
    not touch the network when disabled."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake-token")
    monkeypatch.delenv("SLACK_NOTIFICATIONS_ENABLED", raising=False)

    client = SlackClient()
    client.notify("this must be silently dropped")  # must not raise


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
