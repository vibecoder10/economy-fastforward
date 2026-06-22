"""Lock: billing fails CLOSED on unpaid, and the webhook is idempotent.

Two launch-money invariants:
  1. When a subscription is not 'active' (past_due, canceled, unpaid, ...),
     `_handle_subscription_updated` sets plan='free' — even if the price didn't
     map to a known plan. The old code left `plan` untouched on an unmapped
     price, so an unpaid customer kept full access (fail-open).
  2. `invoice.payment_failed` revokes access (plan='free').
  3. The webhook records each event id (ON CONFLICT DO NOTHING) and skips
     duplicates, so Stripe's at-least-once retries don't double-fire.

(1) and (2) are exercised behaviorally; (3) is a static wiring check.
"""
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")

import routes.billing as billing


def _patch_db():
    """Capture execute() calls; account lookup always resolves. Returns the log."""
    calls = []

    async def fake_fetch_one(sql, *args):
        if "FROM accounts" in sql:
            return {"id": "acct-1"}
        return None

    async def fake_execute(sql, *args):
        calls.append((sql, args))
        return "UPDATE 1"

    billing.fetch_one = fake_fetch_one
    billing.execute = fake_execute
    return calls


def _sub(status, price_id="price_unmapped"):
    return {
        "customer": "cus_1",
        "status": status,
        "items": {"data": [{"price": {"id": price_id}}]},
    }


def test_nonactive_subscription_forces_free_even_with_unmapped_price():
    calls = _patch_db()
    for status in ("past_due", "canceled", "unpaid", "incomplete_expired"):
        calls.clear()
        asyncio.run(billing._handle_subscription_updated(_sub(status)))
        assert calls, f"{status}: no UPDATE issued"
        sql, args = calls[-1]
        assert "plan = 'free'" in sql, (
            f"{status}: UPDATE did not force plan='free' (fail-open leak):\n{sql}"
        )
    print("✅ test_nonactive_subscription_forces_free_even_with_unmapped_price")


def test_payment_failed_revokes_access():
    calls = _patch_db()
    asyncio.run(billing._handle_payment_failed({"customer": "cus_1"}))
    assert calls, "payment_failed issued no UPDATE"
    sql, _ = calls[-1]
    assert "plan = 'free'" in sql and "past_due" in sql, (
        f"payment_failed must set plan='free' + past_due:\n{sql}"
    )
    print("✅ test_payment_failed_revokes_access")


def test_active_mapped_price_grants_plan():
    """Sanity: an active, mapped subscription still sets the paid plan."""
    calls = _patch_db()
    billing.PLAN_PRICE_MAP["pro"] = "price_pro_test"
    asyncio.run(billing._handle_subscription_updated(_sub("active", "price_pro_test")))
    sql, args = calls[-1]
    assert "plan = $1" in sql and "pro" in args, f"active mapped sub should grant plan:\n{sql} {args}"
    print("✅ test_active_mapped_price_grants_plan")


def test_webhook_idempotency_wired():
    """Static: the webhook records the event id before dispatch and skips dups."""
    src = (Path(__file__).resolve().parents[2] / "routes" / "billing.py").read_text()
    fn = re.search(r"async def stripe_webhook\([\s\S]+?\n\n\n", src)
    assert fn, "stripe_webhook not found"
    body = fn.group(0)
    assert "INSERT INTO stripe_events" in body, (
        "webhook no longer records event ids — duplicate deliveries will double-fire"
    )
    assert "ON CONFLICT" in body and "DO NOTHING" in body, (
        "stripe_events insert must be ON CONFLICT DO NOTHING for idempotency"
    )
    # The dedup must come BEFORE the dispatch (the if event_type == ... chain).
    insert_pos = body.find("INSERT INTO stripe_events")
    dispatch_pos = body.find("event_type ==")
    assert insert_pos != -1 and dispatch_pos != -1 and insert_pos < dispatch_pos, (
        "idempotency insert must precede handler dispatch"
    )
    print("✅ test_webhook_idempotency_wired")


TESTS = [
    test_nonactive_subscription_forces_free_even_with_unmapped_price,
    test_payment_failed_revokes_access,
    test_active_mapped_price_grants_plan,
    test_webhook_idempotency_wired,
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
