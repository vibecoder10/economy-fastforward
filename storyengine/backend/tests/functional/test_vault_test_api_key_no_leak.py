"""Functional test for SEC-KEYS-001: prove vault.test_api_key never leaks
raw exception strings (httpx internals, DNS hostnames, TLS paths) to the
client when the network layer blows up.

Pre-fix, the outer `except Exception as e` at the bottom of test_api_key
returned `f"Connection error: {str(e)}"`. A client hitting /api/settings/test-key
when DNS was misbehaving would see something like:

    "Connection error: HTTPSConnectionPool(host='api.anthropic.com', port=443):
     Max retries exceeded with url: /v1/models (Caused by
     NewConnectionError('<urllib3.connection.HTTPSConnection object at 0x...>:
     Failed to establish a new connection: [Errno 8] nodename nor servname
     provided, or not known'))"

That string exposes: upstream hostname, port, URL path, internal object id,
python module path, errno. None of it is actionable for the user, all of it
is reconnaissance for an attacker.

Fix: route the exception through error_utils.humanize_error. The raw error
still reaches the logs so devs can diagnose.
"""
import asyncio
import logging
import os
import sys
import types
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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


LEAKY_ERRORS = [
    # httpx / urllib3 style
    "HTTPSConnectionPool(host='api.anthropic.com', port=443): Max retries exceeded",
    "NewConnectionError('<urllib3.connection.HTTPSConnection object at 0x7f8a3c>')",
    "[Errno 8] nodename nor servname provided, or not known",
    # TLS
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1007)",
    # DNS
    "gaierror: [Errno -2] Name or service not known",
]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_test_api_key_never_leaks_raw_exception():
    """Force every known network-error shape through test_api_key and
    confirm the returned message never contains the raw substring."""

    # get_secret must return SOMETHING so we reach the try/except around httpx.
    async def fake_get_secret(name, tenant_id=None):
        return "sk-fake-test-value"

    for raw_error in LEAKY_ERRORS:

        class LeakyClient:
            """AsyncClient stand-in that raises on entry to the `async with`."""

            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                raise RuntimeError(raw_error)

            async def __aexit__(self, *a):
                return False

        with patch.object(vault, "get_secret", new=fake_get_secret), \
             patch("httpx.AsyncClient", LeakyClient):
            result = _run(vault.test_api_key("anthropic_api_key"))

        assert result["success"] is False, f"unexpected success for raw={raw_error!r}"
        msg = result["message"]
        assert raw_error not in msg, (
            f"raw exception leaked into test_api_key response:\n"
            f"  raw:     {raw_error!r}\n"
            f"  message: {msg!r}"
        )
        # Defense in depth: the specific high-value tokens must not appear.
        for token in ("HTTPSConnectionPool", "urllib3", "_ssl.c", "gaierror", "0x7f"):
            assert token not in msg, (
                f"internal token {token!r} leaked into test_api_key response:\n"
                f"  raw:     {raw_error!r}\n"
                f"  message: {msg!r}"
            )
    print("✅ test_test_api_key_never_leaks_raw_exception")


def test_test_api_key_leaky_exception_is_logged():
    """The raw error must still reach the logs at WARNING so devs can diagnose."""
    raw_error = "SECRET_VAULT_TOKEN_xyz_42 — httpx connection fail"

    async def fake_get_secret(name, tenant_id=None):
        return "sk-fake"

    class LeakyClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            raise RuntimeError(raw_error)

        async def __aexit__(self, *a):
            return False

    # Capture warnings on the error_utils logger.
    logger = logging.getLogger("error_utils")
    records = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = CaptureHandler(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        with patch.object(vault, "get_secret", new=fake_get_secret), \
             patch("httpx.AsyncClient", LeakyClient):
            result = _run(vault.test_api_key("anthropic_api_key"))
    finally:
        logger.removeHandler(handler)

    combined = "\n".join(records)
    assert "SECRET_VAULT_TOKEN_xyz_42" in combined, (
        f"raw error did not reach the logs — dev diagnosability broken.\n"
        f"records={records!r}"
    )
    # And still not in the user-facing message.
    assert "SECRET_VAULT_TOKEN" not in result["message"]
    print("✅ test_test_api_key_leaky_exception_is_logged")


def test_missing_key_path_is_unchanged():
    """Sanity: the pre-existing 'not configured' path must still work
    — we only modified the exception branch."""

    async def fake_get_secret_none(name, tenant_id=None):
        return None

    with patch.object(vault, "get_secret", new=fake_get_secret_none):
        result = _run(vault.test_api_key("anthropic_api_key"))

    assert result["success"] is False
    assert result["message"] == "API key not configured"
    print("✅ test_missing_key_path_is_unchanged")


# ───────────────────────── static audit ─────────────────────────

def test_no_raw_str_e_in_vault_responses():
    """Grep-level audit: vault.py must not contain any
    `f"...{str(e)}..."` patterns that escape into returned dicts."""
    import re
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "vault.py"
    text = path.read_text()

    # Looking for anything like:  "message": f"...{str(e)}..."  or  f"...{e}..."  in a return statement
    leak_patterns = [
        re.compile(r'return\s+\{[^}]*["\']message["\']\s*:\s*f["\'][^"\']*\{str\(e\)\}', re.DOTALL),
        re.compile(r'return\s+\{[^}]*["\']message["\']\s*:\s*f["\'][^"\']*\{e\}', re.DOTALL),
    ]
    leaks = []
    for pat in leak_patterns:
        for m in pat.finditer(text):
            leaks.append(m.group(0)[:140])

    assert not leaks, (
        "vault.py still returns raw str(e) / {e} in response message:\n"
        + "\n".join(leaks)
        + "\n\nUse humanize_error(e, context='...') instead."
    )
    print("✅ test_no_raw_str_e_in_vault_responses")


TESTS = [
    test_test_api_key_never_leaks_raw_exception,
    test_test_api_key_leaky_exception_is_logged,
    test_missing_key_path_is_unchanged,
    test_no_raw_str_e_in_vault_responses,
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
