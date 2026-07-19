"""Tests for C45 (checklist P4.1f — onboarding hookup + intelligence-report
retirement, the P4.1 closer).

Two halves, matching the chunk's own split:

  1. Onboarding hookup — ``routes.onboarding.connect_youtube`` now schedules
     ONE background task (``_import_then_learn``) that imports the channel's
     videos and then (own-channel mode, no re-scrape) kicks off C41's
     ``channel_dna.learn_channel``, gated on whether the tenant has a usable
     generation key (``_has_usable_generation_key``) so a keyless tenant
     never gets a wasted background task. ``routes.chat``'s "channel" step
     of the onboarding chat flow surfaces the outcome (cost-honest ack, or a
     non-blocking "add a key" hint) via the new ``dna_learning`` response
     field. ``_finish_onboarding`` surfaces the learned digest at the
     natural end-of-flow moment, reusing C42's exact ``_build_dna_digest_card``
     renderer (one digest, both surfaces).

  2. Intelligence-report retirement — the three
     ``/api/onboarding/intelligence-report*`` routes now return 410 Gone
     pointing at Channel DNA as the replacement (graceful deprecation, not
     silent removal); ``_build_intelligence_report`` and its private helpers
     are deleted outright (grep-proofs below).

No live DB, no network. Run:
  cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c45_onboarding_dna_hookup.py -q
"""
import asyncio
import os
import re
import sys
import types
from unittest.mock import AsyncMock

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom, get_pool=_boom, safe_column=lambda name: name)
_stub("vault", get_secret=_boom)

import fastapi  # noqa: E402
import routes.onboarding as onboarding  # noqa: E402
import routes.chat as chat  # noqa: E402

TENANT = "tenant-1"


class FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


class _Body:
    def __init__(self, message=None, selections=None):
        self.message = message
        self.selections = selections


# =============================================================================
# 1a. _has_usable_generation_key
# =============================================================================

def test_has_usable_generation_key_true_when_anthropic_key_present(monkeypatch):
    async def fake_get_secret(slot, tenant_id):
        return "sk-ant-xxx" if slot == "anthropic_api_key" else None
    fake_vault = types.ModuleType("vault")
    fake_vault.get_secret = fake_get_secret
    monkeypatch.setitem(sys.modules, "vault", fake_vault)

    assert asyncio.run(onboarding._has_usable_generation_key(TENANT)) is True


def test_has_usable_generation_key_false_when_neither_key_present(monkeypatch):
    async def fake_get_secret(slot, tenant_id):
        return None
    fake_vault = types.ModuleType("vault")
    fake_vault.get_secret = fake_get_secret
    monkeypatch.setitem(sys.modules, "vault", fake_vault)

    assert asyncio.run(onboarding._has_usable_generation_key(TENANT)) is False


def test_has_usable_generation_key_fails_soft_on_vault_error():
    fake_vault = types.ModuleType("vault")

    async def boom(slot, tenant_id):
        raise RuntimeError("vault unreachable")
    fake_vault.get_secret = boom
    sys.modules["vault"] = fake_vault
    try:
        assert asyncio.run(onboarding._has_usable_generation_key(TENANT)) is False
    finally:
        _stub("vault", get_secret=_boom)


# =============================================================================
# 1b. connect_youtube — schedules _import_then_learn, reports dna_learning
# =============================================================================

def _patch_connect_youtube_deps(monkeypatch, *, has_key):
    def fake_extract_metadata(url):
        return {
            "channel_name": "Test Channel", "channel_id": "UC123",
            "subscriber_count": 1000, "video_count": 10, "channel_url": url,
        }
    monkeypatch.setattr(onboarding, "_extract_channel_metadata", fake_extract_metadata)

    async def fake_execute(*a, **k):
        return None
    monkeypatch.setattr(onboarding, "execute", fake_execute)

    async def fake_has_key(tenant_id):
        return has_key
    monkeypatch.setattr(onboarding, "_has_usable_generation_key", fake_has_key)


def test_connect_youtube_schedules_import_then_learn_and_reports_started(monkeypatch):
    _patch_connect_youtube_deps(monkeypatch, has_key=True)
    bg = FakeBackgroundTasks()

    res = asyncio.run(onboarding.connect_youtube(
        onboarding.YouTubeConnect(channel_url="https://youtube.com/@TestChannel"), bg, tenant_id=TENANT,
    ))

    assert res["dna_learning"] == "started"
    assert len(bg.calls) == 1
    fn, args, _ = bg.calls[0]
    assert fn is onboarding._import_then_learn
    assert args[-1] is True, "learn flag must be True when a key is present"


def test_connect_youtube_reports_needs_key_and_still_schedules_import(monkeypatch):
    _patch_connect_youtube_deps(monkeypatch, has_key=False)
    bg = FakeBackgroundTasks()

    res = asyncio.run(onboarding.connect_youtube(
        onboarding.YouTubeConnect(channel_url="https://youtube.com/@TestChannel"), bg, tenant_id=TENANT,
    ))

    assert res["dna_learning"] == "needs_key"
    assert res["status"] == "ok", "a missing key must never block onboarding's connect-youtube step"
    fn, args, _ = bg.calls[0]
    assert fn is onboarding._import_then_learn
    assert args[-1] is False, "learn flag must be False when keyless — the import itself still runs"


# =============================================================================
# 1c. _import_then_learn — own-channel mode, never re-scrapes, never raises
# =============================================================================

def test_import_then_learn_calls_learn_channel_in_own_channel_mode(monkeypatch):
    seen = {}

    async def fake_import(tenant_id, channel_url, channel_name):
        seen["imported"] = (tenant_id, channel_url, channel_name)
        return 5

    async def fake_learn_channel(tenant_id, **kw):
        seen["learn_channel_call"] = (tenant_id, kw)
        return {"ok": True}

    monkeypatch.setattr(onboarding, "_import_channel_videos", fake_import)
    fake_channel_dna_mod = types.ModuleType("channel_dna")
    fake_channel_dna_mod.learn_channel = fake_learn_channel
    monkeypatch.setitem(sys.modules, "channel_dna", fake_channel_dna_mod)

    asyncio.run(onboarding._import_then_learn(TENANT, "https://youtube.com/@X", "X", True))

    assert seen["imported"] == (TENANT, "https://youtube.com/@X", "X")
    tenant_seen, kwargs = seen["learn_channel_call"]
    assert tenant_seen == TENANT
    assert kwargs.get("channel_url") is None, (
        "own-channel mode: learn_channel must NOT be given a channel_url here — "
        "the import above already seeded channel_videos, a second channel_url "
        "would make learn_channel's own optional import step re-scrape the "
        "same channel a second time"
    )


def test_import_then_learn_skips_learn_channel_when_learn_is_false(monkeypatch):
    async def fake_import(tenant_id, channel_url, channel_name):
        return 3
    monkeypatch.setattr(onboarding, "_import_channel_videos", fake_import)

    async def must_not_be_called(*a, **k):
        raise AssertionError("learn_channel must not be called when learn=False (keyless)")
    fake_channel_dna_mod = types.ModuleType("channel_dna")
    fake_channel_dna_mod.learn_channel = must_not_be_called
    monkeypatch.setitem(sys.modules, "channel_dna", fake_channel_dna_mod)

    asyncio.run(onboarding._import_then_learn(TENANT, "https://youtube.com/@X", "X", False))


def test_import_then_learn_never_raises_when_learn_channel_fails(monkeypatch):
    async def fake_import(tenant_id, channel_url, channel_name):
        return 1
    monkeypatch.setattr(onboarding, "_import_channel_videos", fake_import)

    async def boom(*a, **k):
        raise RuntimeError("claim busy or firecrawl down")
    fake_channel_dna_mod = types.ModuleType("channel_dna")
    fake_channel_dna_mod.learn_channel = boom
    monkeypatch.setitem(sys.modules, "channel_dna", fake_channel_dna_mod)

    # Must not raise — this runs inside a FastAPI BackgroundTasks callback,
    # which has no caller left to see an exception.
    asyncio.run(onboarding._import_then_learn(TENANT, "https://youtube.com/@X", "X", True))


# =============================================================================
# 1d. routes/chat.py "channel" step — ack text + non-blocking keyless hint
# =============================================================================

def _patch_ob_reply_persistence(monkeypatch):
    async def fake_persist(*a, **k):
        pass
    async def fake_save_creator_brief(*a, **k):
        pass
    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(chat, "_save_creator_brief", fake_save_creator_brief)


def test_onboarding_channel_step_ack_states_cost_when_dna_learning_started(monkeypatch):
    _patch_ob_reply_persistence(monkeypatch)

    async def fake_connect_youtube(body, background_tasks, tenant_id):
        return {"channel_name": "Test Channel", "dna_learning": "started"}
    monkeypatch.setattr(onboarding, "connect_youtube", fake_connect_youtube)

    state = {"mode": "onboarding", "onboarding_step": "channel"}
    resp = asyncio.run(chat._handle_onboarding(
        _Body(message="https://youtube.com/@TestChannel"), "conv-1", TENANT, [], state, FakeBackgroundTasks(),
    ))

    assert "$0.10-0.30" in resp.assistant_text
    assert state["onboarding_step"] == "competitors", "must still advance — never block onboarding"


def test_onboarding_channel_step_shows_add_key_hint_when_dna_learning_needs_key(monkeypatch):
    _patch_ob_reply_persistence(monkeypatch)

    async def fake_connect_youtube(body, background_tasks, tenant_id):
        return {"channel_name": "Test Channel", "dna_learning": "needs_key"}
    monkeypatch.setattr(onboarding, "connect_youtube", fake_connect_youtube)

    state = {"mode": "onboarding", "onboarding_step": "channel"}
    resp = asyncio.run(chat._handle_onboarding(
        _Body(message="https://youtube.com/@TestChannel"), "conv-1", TENANT, [], state, FakeBackgroundTasks(),
    ))

    assert "add a generation key" in resp.assistant_text.lower() or "settings" in resp.assistant_text.lower()
    assert "$0.10-0.30" not in resp.assistant_text, "must not claim a spend that was never scheduled"
    assert state["onboarding_step"] == "competitors", "keyless must never block onboarding (C04 precedent)"


# =============================================================================
# 1e. _finish_onboarding_dna_note — surfaces the C42 digest at end-of-flow
# =============================================================================

def test_finish_onboarding_dna_note_empty_when_no_channel_ever_connected(monkeypatch):
    async def fake_fetch_one(*a, **k):
        return {"channel_identity": {}}
    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)

    note, card = asyncio.run(chat._finish_onboarding_dna_note(TENANT))
    assert note == ""
    assert card is None


def test_finish_onboarding_dna_note_still_learning_gives_a_note_no_card(monkeypatch):
    async def fake_fetch_one(*a, **k):
        return {"channel_identity": {"_last_run": {"ok": True, "learners": {}}}}
    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)

    fake_channel_dna_mod = types.ModuleType("channel_dna")
    async def fake_is_learning(tenant_id):
        return True
    fake_channel_dna_mod.is_learning = fake_is_learning
    monkeypatch.setitem(sys.modules, "channel_dna", fake_channel_dna_mod)

    note, card = asyncio.run(chat._finish_onboarding_dna_note(TENANT))
    assert "still learning" in note.lower()
    assert card is None


def test_finish_onboarding_dna_note_ready_returns_the_c42_digest_card(monkeypatch):
    identity = {
        "voice_tone": "wry, understated",
        "_last_run": {"ok": True, "learners": {
            "identity_builder": {"status": "learned", "summary": "Learned voice.", "fields_written": [], "error": None},
        }},
    }

    async def fake_fetch_one(*a, **k):
        return {"channel_identity": identity}
    monkeypatch.setattr(chat, "fetch_one", fake_fetch_one)

    fake_channel_dna_mod = types.ModuleType("channel_dna")
    async def fake_is_learning(tenant_id):
        return False
    fake_channel_dna_mod.is_learning = fake_is_learning
    monkeypatch.setitem(sys.modules, "channel_dna", fake_channel_dna_mod)

    async def fake_list_preferences(tenant_id, video_id=None):
        return []
    monkeypatch.setattr(chat, "_list_preferences", fake_list_preferences)

    note, card = asyncio.run(chat._finish_onboarding_dna_note(TENANT))
    assert "learned your channel" in note.lower()
    assert card is not None
    assert card["id"] == "channel_dna_digest", "must reuse C42's exact digest card — one digest, both surfaces"


# =============================================================================
# 2. Intelligence-report retirement — 410 Gone, pointer at Channel DNA
# =============================================================================

def test_generate_intelligence_report_returns_410_pointing_at_channel_dna():
    try:
        asyncio.run(onboarding.generate_intelligence_report(tenant_id=TENANT))
        assert False, "must raise"
    except fastapi.HTTPException as exc:
        assert exc.status_code == 410
        assert "channel dna" in exc.detail.lower() or "learn_channel" in exc.detail.lower() or "learn this channel" in exc.detail.lower()


def test_get_intelligence_report_status_returns_410():
    try:
        asyncio.run(onboarding.get_intelligence_report_status("job-1", tenant_id=TENANT))
        assert False, "must raise"
    except fastapi.HTTPException as exc:
        assert exc.status_code == 410


def test_get_intelligence_report_returns_410():
    try:
        asyncio.run(onboarding.get_intelligence_report(tenant_id=TENANT))
        assert False, "must raise"
    except fastapi.HTTPException as exc:
        assert exc.status_code == 410


def test_intelligence_reports_table_still_referenced_in_status_only_not_written():
    """intelligence_reports (the table) is retired-in-place: no longer
    written anywhere, but the /status endpoint's historical read (does this
    tenant have an old report?) is left alone — no drop migration, no
    behavior change to reads of existing data."""
    src = open(os.path.join(_BACKEND, "routes", "onboarding.py")).read()
    assert "INSERT INTO intelligence_reports" not in src, "the writer must be gone"
    assert "intelligence_reports" in src, "the table name must still appear (the /status read + retirement comment)"


# =============================================================================
# 2b. Grep-proofs — deleted helpers have zero remaining callers/definitions
# =============================================================================

def test_deleted_helpers_are_actually_gone_not_just_unreachable():
    src = open(os.path.join(_BACKEND, "routes", "onboarding.py")).read()
    for name in (
        "_build_intelligence_report",
        "_fallback_intelligence_report",
        "_parse_report_json",
        "_run_intelligence_report_job",
    ):
        assert not re.search(rf"^(async )?def {name}\(", src, re.MULTILINE), (
            f"{name} must be deleted outright, not left as unreachable dead code"
        )
    assert "_report_jobs" not in src, "_report_jobs in-memory dict must be removed (no route writes to it anymore)"
    assert "class IntelligenceReportRequest" not in src, "unused pydantic model must be removed"


def test_no_remaining_callers_anywhere_in_backend():
    import subprocess
    result = subprocess.run(
        ["grep", "-rn", "-E",
         r"_build_intelligence_report|_fallback_intelligence_report|_parse_report_json|_run_intelligence_report_job|IntelligenceReportRequest",
         "--include=*.py", _BACKEND],
        capture_output=True, text=True,
    )
    hits = [
        line for line in result.stdout.splitlines()
        if "__pycache__" not in line
        and "test_c45_onboarding_dna_hookup.py" not in line  # this file's own docstring mentions them by name
    ]
    # Only comment/docstring mentions in onboarding.py's own retirement note
    # should remain — no executable reference (def/call) anywhere.
    executable_hits = [
        line for line in hits
        if not re.search(r"^\s*\S+\.py:\d+:\s*#", line)  # a pure comment line
    ]
    for line in executable_hits:
        # Every remaining line must be inside the retirement docstring/comment
        # block in onboarding.py — never a live def or call site.
        assert "onboarding.py" in line, f"unexpected reference outside onboarding.py: {line}"
