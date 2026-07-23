"""No-network contract tests for application-level deployment drain mode."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys

import pytest


BACKEND = Path(__file__).resolve().parents[2]
STORYENGINE = BACKEND.parent
sys.path.insert(0, str(BACKEND))

import drain_mode
import generation_claims


class _AsyncContext:
    def __init__(self, value=None):
        self.value = value or self

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _Connection:
    def __init__(self, mode="normal", fail=False):
        self.mode = mode
        self.fail = fail
        self.calls: list[tuple[str, str, tuple]] = []
        self.generation_inserted = False

    def transaction(self):
        return _AsyncContext()

    async def execute(self, query, *args):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append(("execute", query, args))
        return "OK"

    async def fetch(self, query, *args):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append(("fetch", query, args))
        return []

    async def fetchrow(self, query, *args):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append(("fetchrow", query, args))
        if "FROM application_drain_state" in query:
            return {
                "mode": self.mode,
                "reason": "deploying" if self.mode == "draining" else None,
                "owner": "test",
                "changed_at": None,
            }
        if "INSERT INTO application_drain_state" in query:
            self.mode = args[0]
            return {
                "mode": self.mode,
                "reason": args[1],
                "owner": args[2],
                "changed_at": None,
            }
        if "INSERT INTO generation_claims" in query:
            self.generation_inserted = True
            return {"stage": args[2]}
        if "AS background_tasks" in query:
            return {"background_tasks": 0, "generation_claims": 0}
        raise AssertionError(f"unexpected fetchrow: {query}")


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AsyncContext(self.conn)


@contextmanager
def _pool(monkeypatch, conn):
    async def get_pool():
        return _Pool(conn)

    monkeypatch.setattr(drain_mode.database, "get_pool", get_pool)
    monkeypatch.setattr(generation_claims.database, "get_pool", get_pool)
    yield conn


@pytest.mark.asyncio
async def test_drain_transition_takes_global_lock_before_state_write(monkeypatch):
    conn = _Connection()
    with _pool(monkeypatch, conn):
        state = await drain_mode.set_draining(reason="safe deploy", owner="codex")

    assert state.draining is True
    lock_index = next(i for i, call in enumerate(conn.calls) if "pg_advisory_xact_lock" in call[1])
    write_index = next(i for i, call in enumerate(conn.calls) if "INSERT INTO application_drain_state" in call[1])
    assert lock_index < write_index


@pytest.mark.asyncio
async def test_drain_rejection_is_retryable_and_machine_readable(monkeypatch):
    conn = _Connection(mode="draining")
    with _pool(monkeypatch, conn):
        with pytest.raises(drain_mode.DrainModeActive) as raised:
            await drain_mode.assert_accepting_new_work()

    body = raised.value.response_body()
    assert body["code"] == "system_draining"
    assert body["retryable"] is True
    assert body["drain"]["draining"] is True
    assert "retry shortly" in body["message"]


@pytest.mark.asyncio
async def test_claim_cannot_cross_drain_boundary(monkeypatch):
    conn = _Connection(mode="draining")
    with _pool(monkeypatch, conn):
        with pytest.raises(drain_mode.DrainModeActive):
            await generation_claims.acquire("tenant", "video", "main")

    assert conn.generation_inserted is False
    assert any("pg_advisory_xact_lock" in call[1] for call in conn.calls)


@pytest.mark.asyncio
async def test_new_work_guard_fails_closed_when_control_db_is_unavailable(monkeypatch):
    conn = _Connection(fail=True)
    with _pool(monkeypatch, conn):
        with pytest.raises(drain_mode.DrainModeActive) as raised:
            await drain_mode.assert_accepting_new_work()

    assert raised.value.state.known is False
    assert raised.value.state.draining is True


def test_request_classifier_blocks_generation_but_keeps_reads_and_reviews():
    blocked = [
        ("POST", "/api/pipeline/images/video-1"),
        ("POST", "/api/pipeline/actions/video-1/finalize"),
        ("POST", "/api/chat/video-1"),
        ("POST", "/api/youtube/sync"),
        ("POST", "/api/videos/video-1/characters/generate"),
        ("POST", "/api/queue/item-1/launch"),
    ]
    allowed = [
        ("GET", "/api/pipeline/status/video-1"),
        ("GET", "/api/videos/video-1"),
        ("POST", "/api/pipeline/cancel/video-1"),
        ("POST", "/api/pipeline/static-qa-approve/asset-1"),
        ("POST", "/api/pipeline/actions/video-1/approve-scene"),
        ("PATCH", "/api/videos/video-1"),
        ("POST", "/api/review/assets/asset-1/approve"),
    ]
    assert all(drain_mode.mutation_starts_work(*request) for request in blocked)
    assert not any(drain_mode.mutation_starts_work(*request) for request in allowed)


def test_migration_and_deploy_wrapper_pin_the_safety_order():
    migration = (BACKEND / "migrations" / "120_application_drain_mode.sql").read_text()
    deploy = (STORYENGINE / "scripts" / "vps-deploy.sh").read_text()

    assert "application_drain_state" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert deploy.index('"$PYTHON" "$DRAIN" drain') < deploy.index('"$PYTHON" "$DRAIN" wait')
    assert deploy.index('"$PYTHON" "$DRAIN" wait') < deploy.index("git pull --ff-only")
    assert '"$PYTHON" "$DRAIN" undrain' in deploy
    assert "trap cleanup EXIT INT TERM" in deploy
    assert "--force NEVER bypasses" in deploy
    assert "'\"draining\":true'" in deploy


def test_frontend_polls_banner_and_disables_shared_generation_actions():
    frontend = STORYENGINE / "frontend" / "src"
    provider = (frontend / "components" / "system" / "DrainModeProvider.tsx").read_text()
    action_button = (frontend / "components" / "ui" / "ActionButton.tsx").read_text()
    api = (frontend / "lib" / "api.ts").read_text()

    assert 'refetchInterval: 5_000' in provider
    assert "New generation is briefly paused for a safe update." in provider
    assert "startsGeneration && draining" in action_button
    assert 'DRAIN_MODE_EVENT = "storyengine:drain-mode"' in api
    assert 'parsedBody?.code === "system_draining"' in api

    production_files = (
        "CharactersTab.tsx",
        "EnvironmentsTab.tsx",
        "ResearchTab.tsx",
        "ScriptVoiceTab.tsx",
        "SoundTab.tsx",
        "ThumbnailTab.tsx",
        "RenderTab.tsx",
    )
    marked = sum(
        (frontend / "components" / "production" / filename)
        .read_text()
        .count("startsGeneration")
        for filename in production_files
    )
    assert marked >= 13
