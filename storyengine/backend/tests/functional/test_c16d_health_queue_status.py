"""Tests for C16d (checklist §S7-7 MED fix, docs/reports/2026-07-17-
storyengine-agent-audit-findings.md §S7): the health endpoints surface
whether the arq/Redis job queue is actually connected.

Before this fix, `main.py`'s lifespan already logged "Redis/arq pool not
available (queue features disabled)" on startup when Redis was unreachable,
and every pipeline stage from that point on silently fell back to in-process
BackgroundTasks (routes/pipeline.py's `_enqueue_or_fallback`) — a fully
supported degraded mode (docs/failure-modes.md), but invisible outside that
one startup log line. Both /api/health and /api/health/detailed now report
`queue: "arq" | "degraded-inprocess"` by reading `app.state.arq` directly
(the same attribute the lifespan sets, and `_enqueue_or_fallback` reads via
`_get_arq_pool`) — no UI banner yet (tracked as a frontend follow-up).

Calls the route functions directly (no TestClient/lifespan) — `main.py`
imports cleanly without a live DB/Redis (every startup step is wrapped in
try/except), but running the real lifespan would also spin up this
process's long-running background tasks (learning extraction, YouTube sync,
etc.), which is unnecessary weight for a one-field assertion. Setting
`main.app.state.arq` directly reproduces exactly what the lifespan does on
success/failure, without any of that.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c16d_health_queue_status.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def test_health_reports_degraded_when_arq_pool_absent():
    """No arq pool connected (Redis unreachable at startup, or never
    attempted) -> queue reads 'degraded-inprocess', not silently missing."""
    main.app.state.arq = None
    result = asyncio.run(main.health())
    assert result["queue"] == "degraded-inprocess"


def test_health_reports_arq_when_pool_connected():
    """A real arq pool on app.state.arq -> queue reads 'arq'."""
    main.app.state.arq = object()  # any truthy pool stand-in
    try:
        result = asyncio.run(main.health())
        assert result["queue"] == "arq"
    finally:
        main.app.state.arq = None


def test_health_detailed_reports_same_queue_field(monkeypatch):
    """/api/health/detailed carries the same field as /api/health, gated by a
    valid HEALTH_TOKEN bearer header (S5-7 — the endpoint fails closed when
    HEALTH_TOKEN is unset, see the dedicated tests below for that gate)."""
    monkeypatch.setenv("HEALTH_TOKEN", "test-token")
    main.app.state.arq = None
    request = SimpleNamespace(headers={"authorization": "Bearer test-token"})
    result = asyncio.run(main.health_detailed(request))
    assert result["queue"] == "degraded-inprocess"

    main.app.state.arq = object()
    try:
        result = asyncio.run(main.health_detailed(request))
        assert result["queue"] == "arq"
    finally:
        main.app.state.arq = None


def test_health_detailed_fails_closed_without_health_token(monkeypatch):
    """S5-7 regression lock: an unset HEALTH_TOKEN must 503, never serve the
    endpoint unauthenticated (the pre-fix `if token and ...` check silently
    skipped auth entirely when the env var was missing)."""
    monkeypatch.delenv("HEALTH_TOKEN", raising=False)
    request = SimpleNamespace(headers={})
    try:
        asyncio.run(main.health_detailed(request))
        raised = None
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 503

    # Even a request that *claims* a bearer token still 503s — there is no
    # correct token to check against when HEALTH_TOKEN isn't configured.
    request_with_header = SimpleNamespace(headers={"authorization": "Bearer whatever"})
    try:
        asyncio.run(main.health_detailed(request_with_header))
        raised = None
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 503


def test_health_detailed_rejects_wrong_token_when_configured(monkeypatch):
    """Sanity check the 401 path still works once HEALTH_TOKEN is set."""
    monkeypatch.setenv("HEALTH_TOKEN", "correct-token")
    request = SimpleNamespace(headers={"authorization": "Bearer wrong-token"})
    try:
        asyncio.run(main.health_detailed(request))
        raised = None
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 401


def test_basic_health_stays_public_with_queue_field(monkeypatch):
    """/api/health (no auth gate at all) must keep working regardless of
    HEALTH_TOKEN — this fix only touches /api/health/detailed."""
    monkeypatch.delenv("HEALTH_TOKEN", raising=False)
    main.app.state.arq = None
    result = asyncio.run(main.health())
    assert result["queue"] == "degraded-inprocess"
    assert "status" in result and "database" in result


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
