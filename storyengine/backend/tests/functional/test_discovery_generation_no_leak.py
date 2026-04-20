"""Functional test for SEC-ERR-002: prove _run_discovery_generation never
leaks raw exception strings (httpx internals, DNS hostnames, DB connection
details) into _refresh_tasks[tenant_id]["error"] — which Cycle 29 just
started surfacing directly in the user-facing Discovery page UI.

Pre-fix, the bottom generic `except Exception as e` at
routes/discovery.py:613-615 returned `{"error": str(e)}`. After Cycle 29
shipped, that string now lights up a red AlertTriangle banner visible to
any logged-in user who clicks Refresh — so a DNS error, DB connection
string, or asyncpg stack fragment became reconnaissance-quality output for
an attacker. Same bug class as SEC-KEYS-001 (Cycle 27, vault.py).

Fix: route the exception through error_utils.humanize_error so the user
sees curated copy and the raw error still reaches the logs.
"""
import asyncio
import logging
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Stub out DB/auth modules the same way other functional tests do, so this
# file can run standalone without a live Postgres.
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


# vault.get_secret is imported locally inside _run_discovery_generation, so
# we need to stub the vault module before it's imported. We'll patch by
# injecting a get_secret shim into sys.modules.
_vault_stub = types.ModuleType("vault")


async def _fake_get_secret(name, tenant_id=None):
    return "sk-fake-test-key"


_vault_stub.get_secret = _fake_get_secret
# Replace any existing vault module with our stub so the inner-function
# `from vault import get_secret` resolves to the fake.
sys.modules["vault"] = _vault_stub


from routes import discovery as discovery_mod


TENANT = "tenant-test-leak"


LEAKY_ERRORS = [
    # Network / httpx / asyncpg shapes
    "HTTPSConnectionPool(host='api.anthropic.com', port=443): Max retries exceeded",
    "[Errno 8] nodename nor servname provided, or not known",
    "gaierror: [Errno -2] Name or service not known",
    # DB internals — asyncpg-style
    "asyncpg.exceptions.ConnectionFailureError: [Errno 111] Connect call failed "
    "('10.0.0.42', 5432)",
    # TLS
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get "
    "local issuer certificate (_ssl.c:1007)",
    # Stack fragment with object ids
    "<urllib3.connection.HTTPSConnection object at 0x7f8a3c>",
]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reset():
    discovery_mod._refresh_tasks.clear()


def test_generation_never_leaks_raw_exception():
    """Force each LEAKY_ERROR shape into _run_discovery_generation's
    outermost except and prove the raw string never lands in
    _refresh_tasks[tenant]["error"]."""
    import database as db_mod

    for raw_error in LEAKY_ERRORS:
        _reset()

        async def _explode(*a, **kw):
            raise RuntimeError(raw_error)

        # Patch fetch_all on the module `routes.discovery` imported it from.
        # routes/discovery.py does `from database import fetch_all` so the
        # binding lives on the discovery module as an attribute.
        original_fetch_all = discovery_mod.fetch_all
        discovery_mod.fetch_all = _explode
        try:
            _run(discovery_mod._run_discovery_generation(TENANT, "batch-xxx"))
        finally:
            discovery_mod.fetch_all = original_fetch_all

        state = discovery_mod._refresh_tasks.get(TENANT, {})
        assert state.get("running") is False, (
            f"tenant state not cleaned after exception: {state!r}"
        )
        stored_error = state.get("error", "")
        assert stored_error, (
            f"no error recorded for raw={raw_error!r} — _refresh_tasks={state!r}"
        )
        assert raw_error not in stored_error, (
            "raw exception leaked into _refresh_tasks error:\n"
            f"  raw:     {raw_error!r}\n"
            f"  stored:  {stored_error!r}"
        )
        # Defense in depth: the specific high-value internal tokens must not
        # appear in the user-facing string.
        for token in (
            "HTTPSConnectionPool",
            "urllib3",
            "_ssl.c",
            "gaierror",
            "0x7f",
            "asyncpg",
            "Errno",
            "10.0.0.42",
            "5432",
        ):
            assert token not in stored_error, (
                f"internal token {token!r} leaked into user-facing error:\n"
                f"  raw:     {raw_error!r}\n"
                f"  stored:  {stored_error!r}"
            )
    print("✅ test_generation_never_leaks_raw_exception")


def test_generation_leaky_exception_is_logged():
    """Raw error must still reach the error_utils WARNING log so devs
    can diagnose even though the user never sees the details."""
    raw_error = "SENTINEL_DISCOVERY_LEAK_42 — asyncpg pool dead"
    _reset()

    async def _explode(*a, **kw):
        raise RuntimeError(raw_error)

    logger = logging.getLogger("error_utils")
    records = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = CaptureHandler(level=logging.WARNING)
    logger.addHandler(handler)
    original_fetch_all = discovery_mod.fetch_all
    discovery_mod.fetch_all = _explode
    try:
        _run(discovery_mod._run_discovery_generation(TENANT, "batch-log-test"))
    finally:
        discovery_mod.fetch_all = original_fetch_all
        logger.removeHandler(handler)

    combined = "\n".join(records)
    assert "SENTINEL_DISCOVERY_LEAK_42" in combined, (
        f"raw error did not reach the error_utils logger — dev diagnosability "
        f"broken.\nrecords={records!r}"
    )
    # And still not in the user-facing string.
    state = discovery_mod._refresh_tasks.get(TENANT, {})
    assert "SENTINEL_DISCOVERY_LEAK_42" not in state.get("error", "")
    print("✅ test_generation_leaky_exception_is_logged")


def test_curated_error_strings_preserved():
    """The non-exception error paths (no API key, no competitors, Claude
    non-200) must keep their curated messages — we only changed the
    generic exception branch, nothing else should regress."""
    _reset()

    # No API key path — get_secret returns None.
    async def _no_key(name, tenant_id=None):
        return None

    original_get_secret = sys.modules["vault"].get_secret
    sys.modules["vault"].get_secret = _no_key
    try:
        _run(discovery_mod._run_discovery_generation(TENANT, "batch-no-key"))
    finally:
        sys.modules["vault"].get_secret = original_get_secret

    state = discovery_mod._refresh_tasks.get(TENANT, {})
    assert state.get("error") == "No Anthropic API key configured", (
        f"curated no-key message changed: {state.get('error')!r}"
    )
    print("✅ test_curated_error_strings_preserved")


# ───────────────────────── static audit ─────────────────────────

def test_no_raw_str_e_in_discovery_refresh_tasks():
    """Grep-level audit: discovery.py must not set `"error": str(e)` (or
    `"error": f"...{e}..."`) anywhere that writes to _refresh_tasks.
    Catches a regression where a future edit reintroduces the leak."""
    import re
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "routes" / "discovery.py"
    text = path.read_text()

    # Patterns that would leak: _refresh_tasks[...] = {... "error": str(e) ...}
    # or "error": f"...{e}..." or "error": f"...{str(e)}..."
    leak_patterns = [
        re.compile(r'_refresh_tasks\[[^\]]+\]\s*=\s*\{[^}]*["\']error["\']\s*:\s*str\(e\)', re.DOTALL),
        re.compile(r'_refresh_tasks\[[^\]]+\]\s*=\s*\{[^}]*["\']error["\']\s*:\s*f["\'][^"\']*\{str\(e\)\}', re.DOTALL),
        re.compile(r'_refresh_tasks\[[^\]]+\]\s*=\s*\{[^}]*["\']error["\']\s*:\s*f["\'][^"\']*\{e\}', re.DOTALL),
    ]

    leaks = []
    for pat in leak_patterns:
        for m in pat.finditer(text):
            leaks.append(m.group(0)[:180])

    assert not leaks, (
        "routes/discovery.py still stores raw str(e)/{e} in _refresh_tasks error:\n"
        + "\n".join(leaks)
        + "\n\nUse humanize_error(e, context='...') instead."
    )
    print("✅ test_no_raw_str_e_in_discovery_refresh_tasks")


TESTS = [
    test_generation_never_leaks_raw_exception,
    test_generation_leaky_exception_is_logged,
    test_curated_error_strings_preserved,
    test_no_raw_str_e_in_discovery_refresh_tasks,
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
