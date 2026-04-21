"""Functional test for Cycle 57: Stripe webhook signature-verification
regression lock.

The bug shape being prevented: `POST /api/billing/webhook` has no auth
dependency (by design — Stripe calls it unauthenticated). The ONLY
thing stopping an attacker from forging a `customer.subscription.updated`
event that flips their plan to `agency` is the signature check:

    event = s.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)

If a refactor:
  - drops `construct_event` and parses the raw payload as JSON directly,
  - replaces the `SignatureVerificationError` branch with a log+continue,
  - allows an empty `WEBHOOK_SECRET` (dev convenience) to fall through
    to the handler,
  - or adds a `verify_token` dep to `stripe_webhook` and assumes Stripe
    can authenticate (it can't),

…any one of those turns the endpoint into a free "upgrade my plan"
button for anyone on the internet. That's a revenue leak AND an
integrity problem — attackers could also delete subscriptions.

This test pins the safe shape:
  - `@router.post("/webhook")` still exists and has NO auth dependency
    (a wrong-direction refactor could ADD one, which would break
    Stripe's callback — but that's a different kind of regression).
  - `stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)` is
    still called before any handler dispatch.
  - `SignatureVerificationError` still becomes a 400 (not a 200, not
    silently-continue).
  - Missing/empty `WEBHOOK_SECRET` still raises 500 (refuses to process),
    not falls through to a skip-verification branch.
  - `construct_event` is called BEFORE any event dispatch — so a
    refactor that moves signature verification inside a handler
    branch wouldn't slip through.
"""
import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _billing_py() -> Path:
    return Path(__file__).resolve().parents[2] / "routes" / "billing.py"


def _get_webhook_function() -> ast.AsyncFunctionDef:
    """Return the AST node for `stripe_webhook`."""
    text = _billing_py().read_text()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "stripe_webhook":
            return node
    raise AssertionError(
        "stripe_webhook function not found in billing.py. If renamed, "
        "update this test — but keep the signature-verification invariants."
    )


def test_webhook_route_registered_and_unauth():
    """The webhook route must exist and take no auth dependency (Stripe
    can't auth our JWT). But it must ALSO be the ONLY route whose only
    defense is signature verification — so we verify the signature path
    explicitly below."""
    fn = _get_webhook_function()
    # Must be decorated with @router.post("/webhook") (or similar)
    decorator_texts = [ast.unparse(d) for d in fn.decorator_list]
    has_post_webhook = any(
        re.search(r'router\.post\(\s*["\']\/webhook["\']', d) for d in decorator_texts
    )
    assert has_post_webhook, (
        "`stripe_webhook` is no longer decorated with "
        '@router.post("/webhook"). If the path moved, update this test '
        "and also verify Stripe's configured webhook URL points at the "
        "new path — Stripe callbacks to the old path will silently 404."
    )
    # Params: only `request` (+ self if ever). MUST NOT have a
    # Depends(verify_token) / Depends(get_tenant_id) — those would
    # make Stripe callbacks fail with 401.
    for arg in fn.args.args:
        if arg.arg == "request":
            continue
        # Any OTHER arg is suspicious
        ann = ast.unparse(arg.annotation) if arg.annotation else ""
        assert "Depends" not in ann, (
            f"`stripe_webhook` now takes an auth-ish dependency "
            f"({arg.arg}: {ann}). Stripe can't provide our JWT — this "
            "breaks the webhook entirely. Remove the dep; the signature "
            "check is the only correct gate."
        )
    print("✅ test_webhook_route_registered_and_unauth")


def test_construct_event_is_called():
    """The signature check MUST use `stripe.Webhook.construct_event` —
    any home-grown parsing is a guaranteed vulnerability. Stripe's SDK
    does the HMAC comparison correctly; we shouldn't reimplement it."""
    fn = _get_webhook_function()
    src = ast.unparse(fn)
    assert re.search(
        r"\bWebhook\.construct_event\s*\(",
        src,
    ), (
        "Cycle 57 regression — `stripe_webhook` no longer calls "
        "`Webhook.construct_event`. A handmade JSON parse bypasses "
        "signature verification entirely — any attacker can forge a "
        "checkout.session.completed event to upgrade their plan."
    )
    # The call must pass payload, sig, AND webhook_secret — not just
    # payload (which would be no-op verification).
    m = re.search(
        r"Webhook\.construct_event\s*\(\s*([^)]+)\)",
        src,
    )
    assert m, "construct_event call malformed"
    args = [a.strip() for a in m.group(1).split(",")]
    assert len(args) >= 3, (
        f"Cycle 57 regression — `construct_event` called with "
        f"{len(args)} args (expected >=3: payload, sig, secret). "
        "A 1-arg call verifies nothing."
    )
    # Third arg should be WEBHOOK_SECRET or similar env-derived name
    secret_arg = args[2]
    assert re.search(r"WEBHOOK_SECRET|webhook_secret", secret_arg), (
        f"Cycle 57 regression — `construct_event` third arg is "
        f"`{secret_arg}` — expected `WEBHOOK_SECRET`. A literal empty "
        "string or unrelated var makes HMAC verification accept anything."
    )
    print("✅ test_construct_event_is_called")


def test_signature_verification_error_becomes_400():
    """When Stripe's SDK raises `SignatureVerificationError`, we MUST
    turn it into a 400 (or 401/403). Silently swallowing it and
    continuing into the handler dispatch would accept forged events."""
    fn = _get_webhook_function()
    src = ast.unparse(fn)
    # Locate the except line, then inspect the next ~3 lines (the handler
    # body is typically one statement). A multi-line regex on indented
    # unparse() output is flaky; split-by-line is both simpler and more
    # robust to formatting drift.
    lines = src.split("\n")
    sig_idx = -1
    for i, line in enumerate(lines):
        if re.search(r"except\s+[^:]*SignatureVerificationError[^:]*:", line):
            sig_idx = i
            break
    assert sig_idx != -1, (
        "Cycle 57 regression — `stripe_webhook` no longer has an "
        "`except SignatureVerificationError` branch. A bad signature "
        "would now propagate as a 500, OR (worse) be caught by a bare "
        "`except Exception: pass` elsewhere."
    )
    # Inspect the 3 lines following the except — the handler body before
    # the next dedented statement.
    branch_body = "\n".join(lines[sig_idx + 1 : sig_idx + 4])
    assert "raise HTTPException" in branch_body, (
        "Cycle 57 regression — SignatureVerificationError no longer "
        f"raises HTTPException. Body was:\n{branch_body!r}\n"
        "Silent swallow = forged events accepted."
    )
    # The status code must be 4xx (not 2xx — that would signal "accepted
    # but ignored" and Stripe would consider the event handled).
    assert re.search(r"status_code\s*=\s*4\d\d", branch_body), (
        "Cycle 57 regression — SignatureVerificationError branch raises "
        "HTTPException but not with a 4xx status. Must be 4xx (400/401/403)."
    )
    print("✅ test_signature_verification_error_becomes_400")


def test_missing_webhook_secret_refuses_processing():
    """If `WEBHOOK_SECRET` is empty/unset, the webhook MUST refuse to
    process. A dev-mode fallback that just skips verification would be
    a permanent prod backdoor the moment the env var drops."""
    fn = _get_webhook_function()
    src = ast.unparse(fn)
    # Must be a guard early in the function: `if not WEBHOOK_SECRET: raise`
    # BEFORE construct_event is called. Otherwise construct_event would
    # accept anything against an empty secret.
    secret_check = re.search(
        r"if\s+not\s+WEBHOOK_SECRET\s*:\s*\n\s*raise\s+HTTPException",
        src,
    )
    assert secret_check, (
        "Cycle 57 regression — `stripe_webhook` no longer refuses to "
        "process when WEBHOOK_SECRET is empty. If the env var drops, "
        "construct_event runs against '' as the secret and verifies "
        "nothing — every attacker-forged event gets accepted."
    )
    # That guard must come BEFORE construct_event
    secret_pos = secret_check.start()
    construct_pos = src.find("construct_event")
    assert secret_pos < construct_pos, (
        "Cycle 57 regression — `if not WEBHOOK_SECRET` guard now comes "
        "AFTER `construct_event`. The verification call will run against "
        "an empty secret first and accept forgeries."
    )
    print("✅ test_missing_webhook_secret_refuses_processing")


def test_construct_event_precedes_dispatch():
    """`construct_event` must be called BEFORE any `event["type"]`
    dispatch. If someone refactors to read event_type first from the
    raw JSON and then verify later (or only verify certain event types),
    attackers control which branches they hit."""
    fn = _get_webhook_function()
    src = ast.unparse(fn)
    construct_pos = src.find("construct_event")
    # The dispatch reads event["type"] — find where
    dispatch_pos = src.find('event["type"]')
    if dispatch_pos == -1:
        dispatch_pos = src.find("event_type")
    assert dispatch_pos != -1, (
        "Webhook handler no longer reads event[\"type\"] or event_type. "
        "If dispatch moved, update this test — but ensure construct_event "
        "still precedes whatever replaced it."
    )
    assert construct_pos < dispatch_pos, (
        "Cycle 57 regression — event type is read BEFORE "
        "`construct_event` finishes. Any refactor that reorders these "
        "lets an attacker dispatch on unverified JSON. Keep "
        "construct_event first."
    )
    print("✅ test_construct_event_precedes_dispatch")


def test_webhook_secret_loaded_from_env():
    """Positive check: WEBHOOK_SECRET must be loaded from env, never
    hardcoded. A hardcoded secret is both useless (Stripe's is
    per-endpoint) and a leak risk."""
    text = _billing_py().read_text()
    assert re.search(
        r'WEBHOOK_SECRET\s*=\s*os\.getenv\(\s*["\']STRIPE_WEBHOOK_SECRET["\']',
        text,
    ), (
        "Cycle 57 regression — WEBHOOK_SECRET no longer loaded via "
        "`os.getenv('STRIPE_WEBHOOK_SECRET')`. A hardcoded string is "
        "both wrong (Stripe's secret is per-endpoint) and a repo leak."
    )
    print("✅ test_webhook_secret_loaded_from_env")


TESTS = [
    test_webhook_route_registered_and_unauth,
    test_construct_event_is_called,
    test_signature_verification_error_becomes_400,
    test_missing_webhook_secret_refuses_processing,
    test_construct_event_precedes_dispatch,
    test_webhook_secret_loaded_from_env,
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
