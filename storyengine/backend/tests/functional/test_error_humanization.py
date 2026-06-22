"""Functional test: prove humanize_error never leaks raw exception strings.

The leak we're guarding against: a user sees "Kie.ai API error:
HTTPSConnectionPool(host='api.kie.ai', port=443): Max retries exceeded..."
in the UI instead of "We couldn't generate your character image".

This test asserts three properties:

1. humanize_error with a context returns copy that LEADS with the context
   and never contains the raw exception string.
2. Without context, known error patterns (network, timeout, auth, rate-limit,
   5xx) are mapped to friendly copy.
3. The raw error is always logged so devs can still diagnose.

It also does a static check on the customer-facing route files: no call
to HTTPException should pass a raw f-string containing str(e) as detail.
"""
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from error_utils import humanize_error


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_context_never_leaks_raw_exception():
    """A context-mode call must never return the raw exception string."""
    raw = "HTTPSConnectionPool(host='api.kie.ai', port=443): Max retries exceeded"
    try:
        raise RuntimeError(raw)
    except RuntimeError as e:
        out = humanize_error(e, context="We couldn't generate your character image")
    assert "api.kie.ai" not in out
    assert "HTTPSConnectionPool" not in out
    assert "generate your character image" in out
    print("✅ test_context_never_leaks_raw_exception")


def test_network_pattern_mapped():
    out = humanize_error("Connection refused by upstream")
    assert "upstream service" in out.lower() or "reach" in out.lower()
    print("✅ test_network_pattern_mapped")


def test_timeout_pattern_mapped():
    out = humanize_error("Request timed out after 60s")
    assert "too long" in out.lower() or "try again" in out.lower()
    print("✅ test_timeout_pattern_mapped")


def test_auth_pattern_mapped():
    out = humanize_error("HTTP 401 Unauthorized")
    assert "authentication" in out.lower() or "api key" in out.lower()
    print("✅ test_auth_pattern_mapped")


def test_rate_limit_pattern_mapped():
    out = humanize_error("HTTP 429 Too Many Requests")
    assert "rate limit" in out.lower() or "wait" in out.lower()
    print("✅ test_rate_limit_pattern_mapped")


def test_unknown_error_uses_fallback():
    out = humanize_error("some totally unknown error string xyz")
    assert "something went wrong" in out.lower() or "try again" in out.lower()
    print("✅ test_unknown_error_uses_fallback")


def test_raw_error_is_logged(caplog=None):
    """The raw exception string must reach the logs even if not the user."""
    logger = logging.getLogger("error_utils")
    records = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = CaptureHandler(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        humanize_error("SECRET_RAW_ERROR_TOKEN_xyz123", context="something broke")
    finally:
        logger.removeHandler(handler)

    combined = "\n".join(records)
    assert "SECRET_RAW_ERROR_TOKEN_xyz123" in combined, (
        "Raw error string must be logged so devs can still diagnose."
    )
    print("✅ test_raw_error_is_logged")


# --- Static audit: no raw str(e) leaks in HTTPException detail ---

CUSTOMER_FACING_ROUTES = [
    "routes/visual_styles.py",
    "routes/intelligence.py",
    "routes/pipeline.py",
    "routes/system_prompts.py",
    "routes/youtube_channel.py",
    "routes/videos.py",
]


def test_no_raw_str_e_in_http_exception_detail():
    """Audit: customer-facing routes must not pass raw str(e) / {e} in
    HTTPException detail. Acceptable: humanize_error(e, context=...).
    """
    leak_patterns = [
        re.compile(r'HTTPException\([^)]*detail\s*=\s*f?["\'][^"\']*\{e\}', re.DOTALL),
        re.compile(r'HTTPException\([^)]*detail\s*=\s*f?["\'][^"\']*str\(e\)', re.DOTALL),
        re.compile(r'HTTPException\([^)]*detail\s*=\s*str\(e\)', re.DOTALL),
    ]
    leaks = []
    for rel in CUSTOMER_FACING_ROUTES:
        path = BACKEND_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text()
        for pat in leak_patterns:
            for m in pat.finditer(text):
                leaks.append(f"{rel}: {m.group(0)[:120]}")
    assert not leaks, (
        "Raw-exception leaks in HTTPException detail:\n"
        + "\n".join(leaks)
        + "\n\nUse humanize_error(e, context='...') instead."
    )
    print(f"✅ test_no_raw_str_e_in_http_exception_detail ({len(CUSTOMER_FACING_ROUTES)} routes clean)")


def test_log_activity_humanizes_failure_messages():
    """pipeline_executor._log_activity must humanize `message` at the write
    boundary when status=='failed', so /api/activity never returns raw
    str(e) through the bot_activity.message column.
    """
    path = BACKEND_ROOT / "pipeline_executor.py"
    text = path.read_text()
    assert "humanize_error(message)" in text, (
        "pipeline_executor._log_activity is missing humanize_error guard on "
        "failed-status writes. Without it, ~20 'error_msg = str(e)' call "
        "sites in this file leak raw exceptions into bot_activity.message."
    )
    print("✅ test_log_activity_humanizes_failure_messages")


def test_set_task_status_humanizes_failure_errors():
    """Background-task boundary: _set_task_status must humanize error at
    the write boundary so /task-status never returns raw str(e) to the UI.
    """
    import sys as _sys
    import types
    # Stub the auth/database modules so routes.pipeline imports cleanly
    _sys.modules.setdefault("auth", types.SimpleNamespace(get_tenant_id=lambda: "t"))
    if "database" not in _sys.modules:
        dbmod = types.ModuleType("database")
        async def _noop(*a, **kw): return []
        dbmod.fetch_one = _noop
        dbmod.fetch_all = _noop
        dbmod.execute = _noop
        _sys.modules["database"] = dbmod
    if "pipeline_executor" not in _sys.modules:
        pe = types.ModuleType("pipeline_executor")
        class _Stub:
            def __init__(self, *a, **kw): pass
        pe.PipelineExecutor = _Stub
        _sys.modules["pipeline_executor"] = pe
    # status_map is pure (stdlib only) — let routes.pipeline import the real one.
    # The old incomplete stub broke that import and poisoned other tests.

    from routes import pipeline as pipeline_mod

    # Simulate: caller passes raw exception string (typical str(e) pattern)
    raw = "HTTPSConnectionPool(host='api.kie.ai', port=443): Max retries exceeded"
    test_tenant = "11111111-1111-1111-1111-111111111111"
    pipeline_mod._set_task_status("test-vid-999", "failed", raw, tenant_id=test_tenant)

    state = pipeline_mod._running_tasks[(test_tenant, "test-vid-999")]
    assert state["status"] == "failed"
    assert "api.kie.ai" not in (state["error"] or ""), (
        f"Raw upstream URL leaked into _running_tasks['error']: {state['error']!r}"
    )
    assert "HTTPSConnectionPool" not in (state["error"] or "")
    # Cleanup
    pipeline_mod._running_tasks.pop((test_tenant, "test-vid-999"), None)
    print("✅ test_set_task_status_humanizes_failure_errors")


def main():
    test_context_never_leaks_raw_exception()
    test_network_pattern_mapped()
    test_timeout_pattern_mapped()
    test_auth_pattern_mapped()
    test_rate_limit_pattern_mapped()
    test_unknown_error_uses_fallback()
    test_raw_error_is_logged()
    test_no_raw_str_e_in_http_exception_detail()
    test_log_activity_humanizes_failure_messages()
    test_set_task_status_humanizes_failure_errors()
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
