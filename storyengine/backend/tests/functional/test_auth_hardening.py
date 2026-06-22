"""Lock: password hashing is strong + upgradeable, and auth endpoints are
brute-force throttled.

Before this: passwords used PBKDF2-SHA256 at 100k iterations (below the OWASP
floor) and /api/auth/{login,register,forgot-password} had NO rate limiting (the
global middleware skips /api/auth and keys on tenant_id, which doesn't exist
pre-login) — so an attacker could spray passwords at full speed.
"""
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from routes import google_auth as ga


def _backend() -> Path:
    return Path(__file__).resolve().parents[2]


def test_hash_uses_strong_iterations():
    h = ga._hash_password("correct horse battery staple")
    m = re.match(r"pbkdf2_sha256\$(\d+)\$", h)
    assert m, f"hash not in self-describing format: {h[:40]}"
    assert int(m.group(1)) >= 600_000, f"iterations {m.group(1)} below the 600k floor"
    assert ga._verify_password("correct horse battery staple", h)
    assert not ga._verify_password("wrong", h)
    assert not ga._password_needs_upgrade(h)
    print("✅ test_hash_uses_strong_iterations")


def test_legacy_hash_verifies_and_flags_upgrade():
    import hashlib
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", b"legacypw", salt, 100_000)
    legacy = salt.hex() + ":" + key.hex()
    assert ga._verify_password("legacypw", legacy), "legacy hash must still verify"
    assert not ga._verify_password("nope", legacy)
    assert ga._password_needs_upgrade(legacy), "legacy hash must be flagged for upgrade"
    print("✅ test_legacy_hash_verifies_and_flags_upgrade")


def _fake_request(ip):
    return SimpleNamespace(headers={"x-forwarded-for": ip},
                           client=SimpleNamespace(host=ip))


def test_auth_rate_limit_blocks_after_cap():
    ip = "203.0.113.77"  # unique to this test so buckets don't bleed
    req = _fake_request(ip)
    # _AUTH_MAX allowed, then 429
    for i in range(ga._AUTH_MAX):
        ga._auth_rate_limit(req, f"user{i}@ex.com")  # vary email so IP is the cap
    try:
        ga._auth_rate_limit(req, "another@ex.com")
    except Exception as e:
        assert getattr(e, "status_code", None) == 429, f"expected 429, got {e}"
        print("✅ test_auth_rate_limit_blocks_after_cap")
        return
    raise AssertionError("auth rate limit did not trigger after the cap")


def test_rate_limit_wired_on_all_auth_endpoints():
    src = (_backend() / "routes" / "google_auth.py").read_text()
    for fn in ("login", "register", "forgot_password"):
        m = re.search(rf"async def {fn}\([\s\S]+?\n\n\n", src)
        assert m, f"{fn} not found"
        assert "_auth_rate_limit(" in m.group(0), (
            f"{fn} no longer calls _auth_rate_limit — brute-force guard lost"
        )
        assert "request: Request" in m.group(0), f"{fn} missing the Request param"
    # Transparent upgrade must be wired in login.
    login_src = re.search(r"async def login\([\s\S]+?\n\n\n", src).group(0)
    assert "_password_needs_upgrade" in login_src, "login no longer rehashes legacy passwords"
    print("✅ test_rate_limit_wired_on_all_auth_endpoints")


TESTS = [
    test_hash_uses_strong_iterations,
    test_legacy_hash_verifies_and_flags_upgrade,
    test_auth_rate_limit_blocks_after_cap,
    test_rate_limit_wired_on_all_auth_endpoints,
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
