"""Background email tasks — trial warnings, etc."""

from database import fetch_all, execute
from email_service import send_trial_warning


async def check_trial_warnings():
    """Send warning emails to users whose trial expires within 3 days.

    Only sends once per account (uses trial_warning_sent flag).
    Only targets users without a paid subscription.
    """
    rows = await fetch_all(
        """SELECT a.id, a.email, a.display_name, a.trial_ends_at
           FROM accounts a
           WHERE a.trial_ends_at IS NOT NULL
             AND a.trial_ends_at > now()
             AND a.trial_ends_at <= now() + INTERVAL '3 days'
             AND a.trial_warning_sent IS NOT TRUE
             AND a.stripe_subscription_id IS NULL
             AND a.email IS NOT NULL""",
    )

    sent = 0
    for row in rows:
        days_left = max(1, (row["trial_ends_at"] - row["trial_ends_at"].__class__.now(row["trial_ends_at"].tzinfo)).days)
        name = row.get("display_name") or "there"

        ok = await send_trial_warning(row["email"], name, days_left)
        if ok:
            await execute(
                "UPDATE accounts SET trial_warning_sent = TRUE WHERE id = $1",
                row["id"],
            )
            sent += 1

    return {"checked": len(rows), "sent": sent}
