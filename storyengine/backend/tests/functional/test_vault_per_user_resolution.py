"""Functional tests for per-user API key resolution in vault.get_secret.

When PER_USER_KEYS_ENABLED is True and user_id is provided, get_secret resolves
in two tiers: user-scoped key first (tenant:user:name), then tenant-shared
fallback (tenant:name). Raises KeyError if neither exists. When the flag is off
(default), the user_id kwarg is silently ignored and existing behavior is
preserved exactly.

Covers acceptance scenarios:
  1. User key present -> returns user value
  2. User key missing, tenant key present -> returns tenant value
  3. Both missing -> raises KeyError
  4. Flag off -> legacy path unchanged, user_id ignored
  5. DB error -> raises RuntimeError (not misleading KeyError)
  6. Flag on, no tenant_id -> falls back to legacy path silently
"""
import asyncio
import os
import sys
import types
from unittest.mock import patch

# When run via pytest, sys.path is configured by storyengine/backend/tests/conftest.py.
# When run directly (python3 test_vault_per_user_resolution.py), set it here.
_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

# Stub database so vault can import without a DB connection.
if "database" not in sys.modules:
    dbmod = types.ModuleType("database")

    async def _fetch_one(*a, **kw):
        return None

    async def _fetch_all(*a, **kw):
        return []

    async def _execute(*a, **kw):
        return None

    dbmod.fetch_one = _fetch_one
    dbmod.fetch_all = _fetch_all
    dbmod.execute = _execute
    sys.modules["database"] = dbmod


import vault


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Test 1: user key present -> returns user value
# ---------------------------------------------------------------------------

def test_user_key_present_returns_user_value():
    """When PER_USER_KEYS_ENABLED=True and the user-scoped key exists in DB,
    get_secret returns the user value without touching the tenant key."""

    async def fake_fetch_one(query, name_value):
        if name_value == "t1:u1:anthropic_api_key":
            return {"value": "sk-user-key"}
        # Tenant key should NOT be reached
        if name_value == "t1:anthropic_api_key":
            return {"value": "sk-tenant-key"}
        return None

    with patch.object(vault, "PER_USER_KEYS_ENABLED", True), \
         patch.object(vault, "fetch_one", new=fake_fetch_one):
        result = _run(vault.get_secret("anthropic_api_key", tenant_id="t1", user_id="u1"))

    assert result == "sk-user-key", f"expected user key, got {result!r}"
    print("\u2705 test_user_key_present_returns_user_value")


# ---------------------------------------------------------------------------
# Test 2: user key missing, tenant fallback returns tenant value
# ---------------------------------------------------------------------------

def test_user_missing_tenant_fallback_returns_tenant_value():
    """When PER_USER_KEYS_ENABLED=True and user key is absent but tenant key
    exists, get_secret falls back to the tenant value."""

    async def fake_fetch_one(query, name_value):
        if name_value == "t1:u1:anthropic_api_key":
            return None  # user key absent
        if name_value == "t1:anthropic_api_key":
            return {"value": "sk-tenant-key"}
        return None

    with patch.object(vault, "PER_USER_KEYS_ENABLED", True), \
         patch.object(vault, "fetch_one", new=fake_fetch_one):
        result = _run(vault.get_secret("anthropic_api_key", tenant_id="t1", user_id="u1"))

    assert result == "sk-tenant-key", f"expected tenant fallback, got {result!r}"
    print("\u2705 test_user_missing_tenant_fallback_returns_tenant_value")


# ---------------------------------------------------------------------------
# Test 3: both missing -> raises KeyError
# ---------------------------------------------------------------------------

def test_both_missing_raises_key_error():
    """When PER_USER_KEYS_ENABLED=True and neither user nor tenant key exists,
    get_secret raises KeyError with a descriptive message."""

    async def fake_fetch_one(query, name_value):
        return None

    with patch.object(vault, "PER_USER_KEYS_ENABLED", True), \
         patch.object(vault, "fetch_one", new=fake_fetch_one):
        try:
            _run(vault.get_secret("anthropic_api_key", tenant_id="t1", user_id="u1"))
            assert False, "expected KeyError but get_secret returned without raising"
        except KeyError as exc:
            msg = str(exc)
            assert "anthropic_api_key" in msg, f"KeyError missing key name: {msg}"
            assert "u1" in msg, f"KeyError missing user_id: {msg}"
            assert "t1" in msg, f"KeyError missing tenant_id: {msg}"

    print("\u2705 test_both_missing_raises_key_error")


# ---------------------------------------------------------------------------
# Test 4: flag off -> legacy path unchanged
# ---------------------------------------------------------------------------

def test_flag_off_legacy_path_unchanged():
    """When PER_USER_KEYS_ENABLED=False, passing user_id has no effect;
    returns the tenant key exactly as before (no KeyError, no user lookup)."""

    call_log = []

    async def fake_fetch_one(query, name_value):
        call_log.append(name_value)
        if name_value == "t1:anthropic_api_key":
            return {"value": "sk-tenant-key"}
        return None

    with patch.object(vault, "PER_USER_KEYS_ENABLED", False), \
         patch.object(vault, "fetch_one", new=fake_fetch_one):
        result = _run(vault.get_secret("anthropic_api_key", tenant_id="t1", user_id="u1"))

    assert result == "sk-tenant-key", f"expected tenant key, got {result!r}"
    # The user-scoped name should never have been queried
    assert "t1:u1:anthropic_api_key" not in call_log, (
        f"user-scoped key was queried even with flag off: {call_log}"
    )
    print("\u2705 test_flag_off_legacy_path_unchanged")


# ---------------------------------------------------------------------------
# Test 5: DB error raises RuntimeError, not misleading KeyError
# ---------------------------------------------------------------------------

def test_db_error_raises_runtime_error():
    """When PER_USER_KEYS_ENABLED=True and the DB raises an exception,
    get_secret raises RuntimeError (not a misleading KeyError saying key is missing)."""

    async def broken_fetch_one(query, name_value):
        raise Exception("connection refused")

    with patch.object(vault, "PER_USER_KEYS_ENABLED", True), \
         patch.object(vault, "fetch_one", new=broken_fetch_one):
        try:
            _run(vault.get_secret("anthropic_api_key", tenant_id="t1", user_id="u1"))
            assert False, "expected RuntimeError but no exception raised"
        except RuntimeError as exc:
            msg = str(exc)
            assert "database temporarily unavailable" in msg.lower(), (
                f"RuntimeError message should mention DB unavailability: {msg!r}"
            )
        except KeyError:
            assert False, (
                "Got KeyError instead of RuntimeError — DB errors must not be "
                "masked as 'key not found'"
            )

    print("\u2705 test_db_error_raises_runtime_error")


# ---------------------------------------------------------------------------
# Test 6: flag on, user_id without tenant_id falls back to legacy path
# ---------------------------------------------------------------------------

def test_flag_on_no_tenant_falls_back_to_legacy():
    """When PER_USER_KEYS_ENABLED=True but tenant_id is None, user_id is ignored
    and the legacy path (env-var fallback) is used."""
    call_log = []

    async def fake_fetch_one(query, name_value):
        call_log.append(name_value)
        return None  # no DB record

    with patch.object(vault, "PER_USER_KEYS_ENABLED", True), \
         patch.object(vault, "fetch_one", new=fake_fetch_one), \
         patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-env-key"}):
        result = _run(vault.get_secret("anthropic_api_key", tenant_id=None, user_id="u1"))

    assert result == "sk-env-key", f"expected env-var fallback, got {result!r}"
    assert all("u1" not in name for name in call_log), (
        f"user-scoped query ran without tenant_id: {call_log}"
    )
    print("\u2705 test_flag_on_no_tenant_falls_back_to_legacy")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    test_user_key_present_returns_user_value,
    test_user_missing_tenant_fallback_returns_tenant_value,
    test_both_missing_raises_key_error,
    test_flag_off_legacy_path_unchanged,
    test_db_error_raises_runtime_error,
    test_flag_on_no_tenant_falls_back_to_legacy,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"\u274c {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"\u274c {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
