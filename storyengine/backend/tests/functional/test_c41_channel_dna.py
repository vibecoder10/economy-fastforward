"""Tests for channel_dna.py::learn_channel — the unified Channel-DNA
ingestion orchestrator (checklist C41 · P4.1b).

Two layers, matching the module's own split:

  Part 1 — orchestration: the five learner steps are monkeypatched at the
  channel_dna module level (channel_dna._run_import / ._run_identity_builder
  / ._run_script_template / ._run_channel_format / ._run_reference_video),
  proving learn_channel's OWN behavior — call order, per-learner fail-soft
  isolation, the channel-level claim (held/released, incl. on an exception),
  the busy/double-run refusal, and the result contract shape. None of this
  touches the real identity_builder/channel_format/script_templates/
  model_video/niche/onboarding modules.

  Part 2 — two learners exercised for real against a fake DB (no live DB, no
  network): _run_script_template's "replaced vs saved" wording (needs the
  real pre-check query), and _run_reference_video's fold-in through the REAL
  channel_dna_meta.stamp_identity_write (proving the `_sources` provenance
  tag lands on "reference_video_style" as "reference_video" — the exact
  behavior the checklist's [V] calls out by name).

Run:
  cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c41_channel_dna.py -q
"""
import json
import os
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


# channel_dna.py imports `from database import execute, fetch_one` and
# `import generation_claims` (which itself only does `import database`,
# resolved at call time) — a minimal stub is enough for both.
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom, get_pool=_boom)

import channel_dna  # noqa: E402
import generation_claims  # noqa: E402
from channel_dna_meta import coerce_identity, field_provenance, stamp_identity_write  # noqa: E402


def _patch_claims(monkeypatch, acquired=True):
    """Route the channel-level claim to simple AsyncMocks instead of the real
    DB-backed generation_claims.acquire_channel/release_channel (those are
    covered by their own tests in test_c16a_generation_claims.py-style
    fake-pool tests below)."""
    acquire_mock = AsyncMock(return_value=acquired)
    release_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(channel_dna.generation_claims, "acquire_channel", acquire_mock)
    monkeypatch.setattr(channel_dna.generation_claims, "release_channel", release_mock)
    return acquire_mock, release_mock


def _patch_learners(monkeypatch, **overrides):
    """Replace all five _run_* step functions with recording stubs (learned
    by default); `overrides` supplies specific coroutine funcs for the steps
    a test cares about — their result is used, but the call is still
    recorded, so call-order assertions work regardless of which steps are
    overridden."""
    calls = []

    defaults = {
        "import": channel_dna._learner_result("learned", "imported"),
        "identity": (
            channel_dna._learner_result("learned", "identity learned"),
            {"style": "3D", "motion": "animated"},
            ["a", "b"],
        ),
        "script": channel_dna._learner_result("learned", "script learned"),
        "format": channel_dna._learner_result("learned", "format learned"),
        "reference": channel_dna._learner_result("learned", "reference learned"),
        # checklist C46e (OR-6 expanded) — step 6, the import-time pattern-
        # analysis learner. Always runs (no optional-input gate), like format.
        "pattern_analysis": channel_dna._learner_result("learned", "patterns learned"),
    }

    def _make(name):
        override = overrides.get(name)

        async def _fn(*a, **k):
            calls.append(name)
            if override is not None:
                return await override(*a, **k)
            return defaults[name]
        return _fn

    monkeypatch.setattr(channel_dna, "_run_import", _make("import"))
    monkeypatch.setattr(channel_dna, "_run_identity_builder", _make("identity"))
    monkeypatch.setattr(channel_dna, "_run_script_template", _make("script"))
    monkeypatch.setattr(channel_dna, "_run_channel_format", _make("format"))
    monkeypatch.setattr(channel_dna, "_run_reference_video", _make("reference"))
    monkeypatch.setattr(channel_dna, "_run_pattern_analysis", _make("pattern_analysis"))
    return calls


# =============================================================================
# Part 1 — orchestration
# =============================================================================

async def test_full_sequence_happy_path_calls_every_learner_in_order(monkeypatch):
    calls = _patch_learners(monkeypatch)
    _patch_claims(monkeypatch)
    monkeypatch.setattr(channel_dna, "_current_identity", AsyncMock(return_value={"voice_tone": "x"}))

    result = await channel_dna.learn_channel(
        "tenant-1",
        channel_url="https://youtube.com/@someone",
        example_script_text="a real example script " * 10,
        reference_video_url="https://youtu.be/abc12345678",
    )

    assert calls == ["import", "identity", "script", "format", "reference", "pattern_analysis"], (
        "learners must run in the documented order: import -> identity_builder -> "
        "script_template -> channel_format -> reference_video -> pattern_analysis"
    )
    assert result["ok"] is True
    assert result["busy"] is False
    assert result["error"] is None
    assert set(result["learners"].keys()) == {
        "import_channel_videos", "identity_builder", "script_template", "channel_format", "reference_video",
        "pattern_analysis",
    }
    for learner in result["learners"].values():
        assert learner["status"] == "learned"
    assert result["identity"] == {"voice_tone": "x"}
    print("✅ test_full_sequence_happy_path_calls_every_learner_in_order")


async def test_optional_inputs_omitted_are_marked_skipped_not_called(monkeypatch):
    calls = _patch_learners(monkeypatch)
    _patch_claims(monkeypatch)
    monkeypatch.setattr(channel_dna, "_current_identity", AsyncMock(return_value={}))

    result = await channel_dna.learn_channel("tenant-1")  # no url, no script, no reference

    # channel_format and pattern_analysis always run (gated by their own
    # internal signals, not by which optional inputs the caller passed) —
    # only import/script/reference are gated by the optional-input flags.
    assert calls == ["identity", "format", "pattern_analysis"]
    assert result["learners"]["import_channel_videos"]["status"] == "skipped"
    assert result["learners"]["script_template"]["status"] == "skipped"
    assert result["learners"]["reference_video"]["status"] == "skipped"
    print("✅ test_optional_inputs_omitted_are_marked_skipped_not_called")


async def test_per_learner_failure_does_not_abort_the_others(monkeypatch):
    async def _failing_script(*a, **k):
        return channel_dna._learner_result("failed", "boom", error="simulated failure")

    calls = _patch_learners(monkeypatch, script=_failing_script)
    _patch_claims(monkeypatch)
    monkeypatch.setattr(channel_dna, "_current_identity", AsyncMock(return_value={}))

    result = await channel_dna.learn_channel(
        "tenant-1", channel_url="https://youtube.com/@someone", example_script_text="x" * 200,
    )

    assert calls == ["import", "identity", "script", "format", "pattern_analysis"]  # reference skipped (no url), but everything ran
    assert result["learners"]["script_template"]["status"] == "failed"
    assert result["learners"]["script_template"]["error"] == "simulated failure"
    # the OTHER learners still report "learned" — one failure doesn't cascade
    assert result["learners"]["identity_builder"]["status"] == "learned"
    assert result["learners"]["channel_format"]["status"] == "learned"
    assert result["ok"] is True  # at least one learner succeeded
    print("✅ test_per_learner_failure_does_not_abort_the_others")


async def test_not_my_channel_path_imports_first(monkeypatch):
    """A channel_url is given -> _run_import runs before identity_builder,
    whether or not it's the tenant's own channel (import is idempotent)."""
    calls = _patch_learners(monkeypatch)
    _patch_claims(monkeypatch)
    monkeypatch.setattr(channel_dna, "_current_identity", AsyncMock(return_value={}))

    result = await channel_dna.learn_channel("tenant-1", channel_url="https://youtube.com/@not-my-channel")

    assert calls[0] == "import", "import must run before identity_builder when a channel_url is supplied"
    assert result["learners"]["import_channel_videos"]["status"] == "learned"
    print("✅ test_not_my_channel_path_imports_first")


async def test_claim_acquired_and_released_on_success(monkeypatch):
    _patch_learners(monkeypatch)
    acquire_mock, release_mock = _patch_claims(monkeypatch)
    monkeypatch.setattr(channel_dna, "_current_identity", AsyncMock(return_value={}))

    await channel_dna.learn_channel("tenant-1")

    acquire_mock.assert_awaited_once_with("tenant-1", channel_dna.CLAIM_STAGE, claimed_by=channel_dna.CLAIMED_BY)
    release_mock.assert_awaited_once_with("tenant-1", channel_dna.CLAIM_STAGE)
    print("✅ test_claim_acquired_and_released_on_success")


async def test_claim_released_even_when_a_learner_step_raises(monkeypatch):
    """The per-learner _run_* wrappers already catch their own exceptions in
    real code, but this proves the orchestrator's OWN safety net: even if a
    step somehow raises past that, release_channel still fires via finally."""
    async def _explodes(*a, **k):
        raise RuntimeError("unexpected crash")

    _patch_learners(monkeypatch, identity=_explodes)
    acquire_mock, release_mock = _patch_claims(monkeypatch)
    monkeypatch.setattr(channel_dna, "_current_identity", AsyncMock(return_value={}))

    try:
        await channel_dna.learn_channel("tenant-1")
        raised = False
    except RuntimeError:
        raised = True

    assert raised is True
    release_mock.assert_awaited_once_with("tenant-1", channel_dna.CLAIM_STAGE)
    print("✅ test_claim_released_even_when_a_learner_step_raises")


async def test_double_run_is_refused_as_busy_and_runs_no_learners(monkeypatch):
    calls = _patch_learners(monkeypatch)
    acquire_mock, release_mock = _patch_claims(monkeypatch, acquired=False)
    monkeypatch.setattr(channel_dna, "_current_identity", AsyncMock(return_value={"voice_tone": "already there"}))

    result = await channel_dna.learn_channel("tenant-1", channel_url="https://youtube.com/@x")

    assert calls == [], "no learner may run when the channel-level claim is denied"
    assert result["ok"] is False
    assert result["busy"] is True
    assert result["learners"] == {}
    assert result["identity"] == {"voice_tone": "already there"}
    release_mock.assert_not_awaited(), "a denied claim must never be released — it was never acquired"
    print("✅ test_double_run_is_refused_as_busy_and_runs_no_learners")


# =============================================================================
# Part 1b — _run_pattern_analysis (checklist C46e, OR-6 EXPANDED step 6)
# =============================================================================

async def test_run_pattern_analysis_learned_summary_reports_proposed_count(monkeypatch):
    fake_mod = types.ModuleType("channel_patterns")
    fake_mod.run_import_pattern_analysis = AsyncMock(return_value={"proposed": 3, "rows": []})
    monkeypatch.setitem(sys.modules, "channel_patterns", fake_mod)

    result = await channel_dna._run_pattern_analysis("tenant-1")

    assert result["status"] == "learned"
    assert "3 pattern" in result["summary"]
    assert result["fields_written"] == ["channel_patterns"]
    print("✅ test_run_pattern_analysis_learned_summary_reports_proposed_count")


async def test_run_pattern_analysis_zero_proposed_is_skipped_not_failed(monkeypatch):
    fake_mod = types.ModuleType("channel_patterns")
    fake_mod.run_import_pattern_analysis = AsyncMock(return_value={"proposed": 0, "rows": []})
    monkeypatch.setitem(sys.modules, "channel_patterns", fake_mod)

    result = await channel_dna._run_pattern_analysis("tenant-1")

    assert result["status"] == "skipped"
    print("✅ test_run_pattern_analysis_zero_proposed_is_skipped_not_failed")


async def test_run_pattern_analysis_fails_soft_on_crash(monkeypatch):
    fake_mod = types.ModuleType("channel_patterns")

    async def boom(tenant_id):
        raise RuntimeError("channel_videos query failed")

    fake_mod.run_import_pattern_analysis = boom
    monkeypatch.setitem(sys.modules, "channel_patterns", fake_mod)

    result = await channel_dna._run_pattern_analysis("tenant-1")

    assert result["status"] == "failed"
    assert result["error"] == "channel_videos query failed"
    print("✅ test_run_pattern_analysis_fails_soft_on_crash")


# =============================================================================
# Part 2 — two learners exercised for real (fake DB, no live DB/network)
# =============================================================================

def _fake_row_db(script_templates_exists: bool, channel_identity_initial=None):
    """Fakes for both fetch_one (script_templates precheck + channel_identity
    reads) and execute (channel_identity writes) that channel_dna.py itself
    calls at module level."""
    state = {"channel_identity": channel_identity_initial}

    async def fake_fetch_one(query, *args):
        q = " ".join(query.split())
        if "FROM script_templates" in q:
            return {"id": "existing-id"} if script_templates_exists else None
        if "FROM channel_profiles" in q:
            return {"channel_identity": state["channel_identity"]}
        return None

    async def fake_execute(query, *args):
        if "channel_identity" in query:
            state["channel_identity"] = args[-1]
        return None

    return state, fake_fetch_one, fake_execute


async def test_example_script_path_surfaces_replacement_warning(monkeypatch):
    state, fake_fetch_one, fake_execute = _fake_row_db(script_templates_exists=True)
    monkeypatch.setattr(channel_dna, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(channel_dna, "execute", fake_execute)

    fake_analyze = AsyncMock(return_value={"id": "tpl-1", "name": "House format"})
    fake_script_templates_mod = types.ModuleType("routes.script_templates")
    fake_script_templates_mod.analyze_and_save_template = fake_analyze
    monkeypatch.setitem(sys.modules, "routes.script_templates", fake_script_templates_mod)

    result = await channel_dna._run_script_template("tenant-1", "a real example script " * 10)

    assert result["status"] == "learned"
    assert "replaced" in result["summary"].lower()
    fake_analyze.assert_awaited_once()
    print("✅ test_example_script_path_surfaces_replacement_warning")


async def test_example_script_path_first_save_does_not_say_replaced(monkeypatch):
    state, fake_fetch_one, fake_execute = _fake_row_db(script_templates_exists=False)
    monkeypatch.setattr(channel_dna, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(channel_dna, "execute", fake_execute)

    fake_analyze = AsyncMock(return_value={"id": "tpl-1", "name": "House format"})
    fake_script_templates_mod = types.ModuleType("routes.script_templates")
    fake_script_templates_mod.analyze_and_save_template = fake_analyze
    monkeypatch.setitem(sys.modules, "routes.script_templates", fake_script_templates_mod)

    result = await channel_dna._run_script_template("tenant-1", "a real example script " * 10)

    assert result["status"] == "learned"
    assert "replaced" not in result["summary"].lower()
    assert "saved" in result["summary"].lower()
    print("✅ test_example_script_path_first_save_does_not_say_replaced")


async def test_reference_video_findings_stamped_into_identity_via_c40_helper(monkeypatch):
    """The exact behavior the checklist's [V] names: reference_video's
    findings must be folded into channel_identity through the REAL
    channel_dna_meta.stamp_identity_write, tagged learner="reference_video"."""
    prior = stamp_identity_write({}, {"voice_tone": "confident"}, learner="identity_builder")
    state, fake_fetch_one, fake_execute = _fake_row_db(script_templates_exists=False, channel_identity_initial=json.dumps(prior))
    monkeypatch.setattr(channel_dna, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(channel_dna, "execute", fake_execute)

    fake_creds = {"provider": "anthropic", "key": "sk-test"}
    fake_info = {"title": "Reference Vid", "description": "desc", "transcript": "hello world"}
    fake_dna = {"summary": "punchy, cold-open documentary", "structured_metadata": {"pace": "fast"}}

    fake_model_video_mod = types.ModuleType("routes.model_video")
    fake_model_video_mod._parse_youtube_id = lambda url: "abc12345678"
    fake_model_video_mod._resolve_claude_creds = AsyncMock(return_value=fake_creds)
    fake_model_video_mod._oembed_fallback = AsyncMock(return_value=None)
    fake_model_video_mod._fetch_transcript_supadata = AsyncMock(return_value=None)
    fake_model_video_mod._distill_dna = AsyncMock(return_value=fake_dna)
    monkeypatch.setitem(sys.modules, "routes.model_video", fake_model_video_mod)

    fake_niche_mod = types.ModuleType("routes.niche")
    fake_niche_mod._extract_video_info = lambda video_id: fake_info
    monkeypatch.setitem(sys.modules, "routes.niche", fake_niche_mod)

    result = await channel_dna._run_reference_video("tenant-1", "https://youtu.be/abc12345678")

    assert result["status"] == "learned"
    assert result["fields_written"] == ["reference_video_style"]

    final = coerce_identity(state["channel_identity"])
    assert final["reference_video_style"]["summary"] == fake_dna["summary"]
    assert final["reference_video_style"]["source_url"] == "https://youtu.be/abc12345678"
    prov = field_provenance(final, "reference_video_style")
    assert prov is not None and prov["learner"] == "reference_video"
    # the PRIOR identity_builder field/provenance survives untouched
    assert final["voice_tone"] == "confident"
    assert field_provenance(final, "voice_tone")["learner"] == "identity_builder"
    print("✅ test_reference_video_findings_stamped_into_identity_via_c40_helper")


async def test_reference_video_no_credentials_fails_soft(monkeypatch):
    fake_model_video_mod = types.ModuleType("routes.model_video")
    fake_model_video_mod._parse_youtube_id = lambda url: "abc12345678"
    fake_model_video_mod._resolve_claude_creds = AsyncMock(return_value=None)
    fake_model_video_mod._oembed_fallback = AsyncMock(return_value=None)
    fake_model_video_mod._fetch_transcript_supadata = AsyncMock(return_value=None)
    fake_model_video_mod._distill_dna = AsyncMock(return_value=None)
    monkeypatch.setitem(sys.modules, "routes.model_video", fake_model_video_mod)
    fake_niche_mod = types.ModuleType("routes.niche")
    fake_niche_mod._extract_video_info = lambda video_id: None
    monkeypatch.setitem(sys.modules, "routes.niche", fake_niche_mod)

    result = await channel_dna._run_reference_video("tenant-1", "https://youtu.be/abc12345678")

    assert result["status"] == "failed"
    assert result["error"] == "no credentials"
    print("✅ test_reference_video_no_credentials_fails_soft")


# =============================================================================
# Part 3 — generation_claims.acquire_channel/release_channel (fake pool)
# =============================================================================

class _FakeChannelConn:
    def __init__(self, store: dict, should_fail: bool = False):
        self.store = store  # (tenant_id, stage) -> claimed_at epoch seconds
        self.should_fail = should_fail

    def transaction(self):
        return _NullAsyncCtx()

    async def execute(self, query, *args):
        if self.should_fail:
            raise RuntimeError("simulated DB outage")
        if "pg_advisory_xact_lock" in query:
            return None
        if "claimed_at < now()" in query:  # acquire_channel()'s stale sweep
            import time as _time
            tenant_id, stage = args
            cutoff = _time.time() - generation_claims.STALE_HOURS * 3600
            key = (tenant_id, stage)
            if key in self.store and self.store[key] < cutoff:
                del self.store[key]
            return "DELETE 0"
        if "video_id IS NULL AND stage = $2" in query:  # release_channel()
            tenant_id, stage = args
            self.store.pop((tenant_id, stage), None)
            return "DELETE 1"
        raise AssertionError(f"unexpected execute() query: {query!r}")

    async def fetchrow(self, query, *args):
        if self.should_fail:
            raise RuntimeError("simulated DB outage")
        import time as _time
        tenant_id, stage, claimed_by = args
        key = (tenant_id, stage)
        if key in self.store:  # ON CONFLICT ... DO NOTHING -> no row back
            return None
        self.store[key] = _time.time()
        return {"stage": stage}


class _NullAsyncCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePoolCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakeChannelPool:
    def __init__(self, store, should_fail=False):
        self._store = store
        self._should_fail = should_fail

    def acquire(self):
        return _FakePoolCtx(_FakeChannelConn(self._store, self._should_fail))


def _patch_channel_pool(monkeypatch, store: dict, should_fail: bool = False):
    fake_pool = _FakeChannelPool(store, should_fail)

    async def _fake_get_pool():
        return fake_pool

    monkeypatch.setattr(generation_claims.database, "get_pool", _fake_get_pool)


async def test_acquire_channel_then_deny_then_release_then_reacquire(monkeypatch):
    store: dict = {}
    _patch_channel_pool(monkeypatch, store)

    first = await generation_claims.acquire_channel("t1", "dna", claimed_by="test")
    assert first is True

    second = await generation_claims.acquire_channel("t1", "dna", claimed_by="test-retry")
    assert second is False, "a second acquire_channel for the same (tenant, stage) while held must be denied"

    await generation_claims.release_channel("t1", "dna")

    third = await generation_claims.acquire_channel("t1", "dna", claimed_by="test-again")
    assert third is True
    print("✅ test_acquire_channel_then_deny_then_release_then_reacquire")


async def test_acquire_channel_fails_closed_on_db_error(monkeypatch):
    store: dict = {}
    _patch_channel_pool(monkeypatch, store, should_fail=True)

    result = await generation_claims.acquire_channel("t1", "dna", claimed_by="test")
    assert result is False
    print("✅ test_acquire_channel_fails_closed_on_db_error")


async def test_release_channel_fails_soft_on_db_error_never_raises(monkeypatch):
    store: dict = {("t1", "dna"): True}
    _patch_channel_pool(monkeypatch, store, should_fail=True)

    await generation_claims.release_channel("t1", "dna")  # must not raise
    print("✅ test_release_channel_fails_soft_on_db_error_never_raises")
