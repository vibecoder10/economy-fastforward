"""Functional test for Stage 6.5: DiscoveryStatus.error must be populated
when the last refresh attempt failed, and null when it succeeded or never ran.

Pre-fix, the frontend TypeScript DiscoveryStatus interface was missing the
`error` field entirely. The backend has always set it on `_refresh_tasks[...]`
after a failed generation, but the frontend never rendered it — users saw
"Generating..." flip back to an empty state with no indication anything went
wrong. This test pins the backend contract so a future refactor can't drop
the field.
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Stub heavy imports so this runs standalone without a DB.
for stub_mod in ("database", "auth"):
    if stub_mod not in sys.modules:
        m = types.ModuleType(stub_mod)
        if stub_mod == "database":
            async def _noop(*a, **kw):
                return None
            m.fetch_one = _noop
            m.fetch_all = _noop
            m.execute = _noop
        if stub_mod == "auth":
            async def _get_tenant_id(*a, **kw):
                return "stub"
            m.get_tenant_id = _get_tenant_id
        sys.modules[stub_mod] = m


from routes import discovery as discovery_mod


TENANT = "tenant-test"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reset():
    discovery_mod._refresh_tasks.clear()


def test_discovery_status_has_error_field():
    """The Pydantic model must expose `error` as an optional string field.
    If someone removes the field from the model, every serialization downstream
    breaks silently — this test fails loudly at CI time."""
    import typing
    fields = discovery_mod.DiscoveryStatus.model_fields
    assert "error" in fields, "DiscoveryStatus.error field missing from model"
    # Must accept None (nullable). Works for Optional[str] and str | None.
    ann = fields["error"].annotation
    args = typing.get_args(ann)
    assert type(None) in args and str in args, (
        f"DiscoveryStatus.error must be Optional[str] / str | None, got {ann!r}"
    )
    print("✅ test_discovery_status_has_error_field")


def test_discovery_status_error_none_when_no_refresh_ever():
    """Clean state: a tenant that has never clicked refresh → error = None."""
    _reset()
    result = _run(discovery_mod.get_discovery_status(tenant_id=TENANT))
    assert result.error is None, f"expected error=None on clean state, got {result.error!r}"
    print("✅ test_discovery_status_error_none_when_no_refresh_ever")


def test_discovery_status_error_populated_on_failure():
    """After a failed refresh, the error message must surface in status.error."""
    _reset()
    discovery_mod._refresh_tasks[TENANT] = {
        "running": False,
        "error": "No Anthropic API key configured",
    }
    result = _run(discovery_mod.get_discovery_status(tenant_id=TENANT))
    assert result.is_refreshing is False
    assert result.error == "No Anthropic API key configured", (
        f"error field did not propagate: got {result.error!r}"
    )
    print("✅ test_discovery_status_error_populated_on_failure")


def test_discovery_status_error_hidden_while_refreshing():
    """If a refresh is currently running, we do NOT surface stale error text.
    (Lines 211-214 of discovery.py gate on `not is_refreshing`.) This prevents
    a flicker where the spinner AND a red error banner render at the same time."""
    _reset()
    discovery_mod._refresh_tasks[TENANT] = {
        "running": True,
        "error": "stale error from prior run",
    }
    result = _run(discovery_mod.get_discovery_status(tenant_id=TENANT))
    assert result.is_refreshing is True
    assert result.error is None, (
        f"error leaked through while refresh was running: {result.error!r}"
    )
    print("✅ test_discovery_status_error_hidden_while_refreshing")


def test_discovery_status_error_none_on_success():
    """A successful refresh clears the error to None."""
    _reset()
    discovery_mod._refresh_tasks[TENANT] = {
        "running": False,
        "ideas_generated": 8,
        "batch_id": "abc12345",
        "learnings_applied": 3,
        # No "error" key at all → .get("error") returns None.
    }
    result = _run(discovery_mod.get_discovery_status(tenant_id=TENANT))
    assert result.is_refreshing is False
    assert result.error is None, f"expected error=None on success, got {result.error!r}"
    assert result.learnings_applied == 3
    print("✅ test_discovery_status_error_none_on_success")


# ───────────────────────── static audit ─────────────────────────

def test_ts_interface_includes_error_field():
    """The frontend TypeScript DiscoveryStatus interface must declare
    `error: string | null;`. If a refactor drops this from api.ts, the UI
    falls back to rendering nothing when refreshes fail — silent breakage.

    This test reads the TS file directly as text; there's no tsc in the
    functional-test runner. It's a grep-level regression guard."""
    from pathlib import Path
    import re

    ts_path = (
        Path(__file__).resolve().parents[3]
        / "frontend" / "src" / "lib" / "api.ts"
    )
    assert ts_path.exists(), f"frontend api.ts not found at {ts_path}"
    text = ts_path.read_text()

    m = re.search(
        r"export interface DiscoveryStatus \{([^}]*)\}",
        text,
        re.DOTALL,
    )
    assert m, "DiscoveryStatus interface not found in frontend/src/lib/api.ts"
    body = m.group(1)
    assert re.search(r"\berror\s*:\s*string\s*\|\s*null\b", body), (
        "DiscoveryStatus interface missing `error: string | null;` field.\n"
        f"Current body:\n{body}"
    )
    print("✅ test_ts_interface_includes_error_field")


TESTS = [
    test_discovery_status_has_error_field,
    test_discovery_status_error_none_when_no_refresh_ever,
    test_discovery_status_error_populated_on_failure,
    test_discovery_status_error_hidden_while_refreshing,
    test_discovery_status_error_none_on_success,
    test_ts_interface_includes_error_field,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
