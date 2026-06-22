"""Lock: email verification wiring.

New password signups start unverified and must confirm via an emailed link
before generating (gated in check_plan_limits behind EMAIL_VERIFY_REQUIRED so it
stays off until the sending domain is verified). Google signups + existing
accounts are verified. These checks pin the wiring so a refactor can't silently
drop a piece and either leave the gate open or lock everyone out.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _backend() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (_backend() / rel).read_text()


def test_migration_and_schema_have_column_and_grandfather():
    mig = _read("migrations/059_email_verification.sql")
    assert "email_verified" in mig and "ADD COLUMN IF NOT EXISTS email_verified" in mig
    # Existing accounts must be grandfathered to verified, or a deploy locks everyone out.
    assert re.search(r"UPDATE\s+accounts\s+SET\s+email_verified\s*=\s*true", mig, re.I), (
        "migration must grandfather existing accounts to verified=true"
    )
    schema = (_backend().parent / "schema.sql").read_text()
    assert "email_verified BOOLEAN" in schema, "schema.sql must declare email_verified"


def test_register_unverified_and_sends_link():
    src = _read("routes/google_auth.py")
    reg = re.search(r"async def register\([\s\S]+?\n\n\n", src).group(0)
    assert "email_verification_token" in reg and "false" in reg, "register must insert unverified + a token"
    assert "send_verification_email" in reg, "register must send the verification email"


def test_google_signup_is_verified():
    src = _read("routes/google_auth.py")
    # The brand-new google account INSERT must set email_verified true.
    assert re.search(r"INSERT INTO accounts[\s\S]{0,400}?email_verified[\s\S]{0,200}?true", src), (
        "Google signups must be created with email_verified=true"
    )


def test_verify_and_resend_endpoints_exist():
    src = _read("routes/google_auth.py")
    assert '@router.post("/verify-email")' in src, "verify-email endpoint missing"
    assert '@router.post("/resend-verification")' in src, "resend-verification endpoint missing"
    # verify must flip the flag and clear the token.
    vfn = re.search(r"async def verify_email\([\s\S]+?\n\n\n", src).group(0)
    assert "email_verified = true" in vfn and "email_verification_token = NULL" in vfn
    # /me exposes it for the banner.
    assert '"email_verified": bool(account.get("email_verified"))' in src


def test_gate_is_flagged_and_fail_safe():
    src = _read("routes/billing.py")
    # The gate lives in check_plan_limits, behind the env flag (off by default).
    assert "EMAIL_VERIFY_REQUIRED" in src, "gate must be behind EMAIL_VERIFY_REQUIRED flag"
    assert "email_not_verified" in src and "status_code=403" in src, "gate must 403 with email_not_verified"
    # The flag check must default to 'false' (deploy-safe — never locks out new users).
    assert re.search(r'getenv\(\s*["\']EMAIL_VERIFY_REQUIRED["\']\s*,\s*["\']false["\']', src), (
        "EMAIL_VERIFY_REQUIRED must default to false so a deploy can't lock out new users"
    )
    # The verified lookup must fail-safe (default True on a lookup miss).
    assert "_is_email_verified" in src and "True if not row" in src
    # And the gate check must actually call check_plan_limits' chokepoint.
    assert "async def check_plan_limits" in src


TESTS = [
    test_migration_and_schema_have_column_and_grandfather,
    test_register_unverified_and_sends_link,
    test_google_signup_is_verified,
    test_verify_and_resend_endpoints_exist,
    test_gate_is_flagged_and_fail_safe,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t(); print(f"✅ {t.__name__}")
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}"); failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}"); failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
