"""Stripe billing routes: checkout, webhooks, subscription management, portal, usage tracking."""

import os
import uuid as _uuid

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from auth import get_tenant_id, verify_token, AuthUser
from database import fetch_one, fetch_all, execute
from email_service import send_billing_receipt  # email utility

router = APIRouter(prefix="/api/billing", tags=["billing"])

# Price IDs configured in Stripe Dashboard, stored as env vars
PLAN_PRICE_MAP = {
    "starter": os.getenv("STRIPE_PRICE_STARTER", ""),
    "pro": os.getenv("STRIPE_PRICE_PRO", ""),
    "agency": os.getenv("STRIPE_PRICE_AGENCY", ""),
}

WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


def _get_stripe():
    """Initialize stripe with API key. Raises if not configured."""
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    stripe.api_key = key
    return stripe


class CreateCheckoutRequest(BaseModel):
    plan: str  # "starter", "pro", or "agency"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class PortalRequest(BaseModel):
    return_url: Optional[str] = None


@router.post("/create-checkout")
async def create_checkout(
    body: CreateCheckoutRequest,
    user: AuthUser = Depends(verify_token),
    tenant_id: str = Depends(get_tenant_id),
):
    """Create a Stripe Checkout Session for a subscription plan."""
    s = _get_stripe()

    price_id = PLAN_PRICE_MAP.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {body.plan}. Must be starter, pro, or agency.")

    # Resolve account
    account_id = user.id
    if account_id == "dev-user":
        account_id = "00000000-0000-0000-0000-000000000001"

    account = await fetch_one(
        "SELECT id, email, stripe_customer_id FROM accounts WHERE id = $1",
        account_id,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Reuse existing Stripe customer or let Checkout create one
    customer_id = account.get("stripe_customer_id")

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    success = body.success_url or f"{frontend_url}/settings?billing=success"
    cancel = body.cancel_url or f"{frontend_url}/settings?billing=cancel"

    session_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success,
        "cancel_url": cancel,
        "metadata": {"account_id": account_id, "tenant_id": tenant_id},
    }

    if customer_id:
        session_params["customer"] = customer_id
    else:
        session_params["customer_email"] = account.get("email")

    session = s.checkout.Session.create(**session_params)
    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events for subscription lifecycle.

    No auth required — verified by Stripe signature.
    """
    s = _get_stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    try:
        event = s.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except s.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Idempotency: Stripe delivers at-least-once. Record the event id first;
    # if we've already processed it, skip (prevents duplicate receipt emails
    # and double-applied side effects on retried/redelivered events).
    seen = await fetch_one(
        """INSERT INTO stripe_events (event_id, event_type)
           VALUES ($1, $2)
           ON CONFLICT (event_id) DO NOTHING
           RETURNING event_id""",
        event["id"], event["type"],
    )
    if not seen:
        return {"received": True, "duplicate": True}

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data)

    return {"received": True}


async def _handle_checkout_completed(session: dict):
    """Link Stripe customer + subscription to account after successful checkout."""
    account_id = session.get("metadata", {}).get("account_id")
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    if not account_id:
        return

    # Get subscription to determine plan
    s = _get_stripe()
    sub = s.Subscription.retrieve(subscription_id)
    price_id = sub["items"]["data"][0]["price"]["id"] if sub["items"]["data"] else None

    plan = "free"
    for plan_name, pid in PLAN_PRICE_MAP.items():
        if pid == price_id:
            plan = plan_name
            break

    await execute(
        """UPDATE accounts
           SET stripe_customer_id = $1,
               stripe_subscription_id = $2,
               stripe_plan = $3,
               stripe_status = 'active',
               plan = $4,
               updated_at = now()
           WHERE id = $5""",
        customer_id, subscription_id, plan, plan, account_id,
    )

    # Send billing receipt email (best-effort, don't fail checkout on email error)
    try:
        acct = await fetch_one("SELECT email FROM accounts WHERE id = $1", account_id)
        if acct and acct.get("email"):
            s = _get_stripe()
            invoice = s.Invoice.list(subscription=subscription_id, limit=1)
            amount = f"${invoice.data[0].amount_paid / 100:.2f}" if invoice.data else "See Stripe receipt"
            await send_billing_receipt(acct["email"], plan.title(), amount)
    except Exception as e:
        print(f"[WARN] Billing receipt email failed: {e}")


async def _handle_subscription_updated(subscription: dict):
    """Update plan/status when subscription changes (upgrade, downgrade, payment issue)."""
    customer_id = subscription.get("customer")
    sub_status = subscription.get("status")  # active, past_due, canceled, etc.
    price_id = subscription["items"]["data"][0]["price"]["id"] if subscription.get("items", {}).get("data") else None

    plan = None
    if price_id:
        for plan_name, pid in PLAN_PRICE_MAP.items():
            if pid == price_id:
                plan = plan_name
                break

    account = await fetch_one(
        "SELECT id FROM accounts WHERE stripe_customer_id = $1", customer_id
    )
    if not account:
        return

    if sub_status != "active":
        # Fail CLOSED: any non-active state (past_due, canceled, unpaid,
        # incomplete) loses paid access — regardless of whether the price
        # mapped to a known plan. Previously an unmapped price left `plan`
        # untouched, so an unpaid customer kept full access (fail-open).
        await execute(
            """UPDATE accounts
               SET stripe_plan = COALESCE($1, stripe_plan), stripe_status = $2,
                   plan = 'free', updated_at = now()
               WHERE id = $3""",
            plan, sub_status, account["id"],
        )
    elif plan:
        await execute(
            """UPDATE accounts
               SET stripe_plan = $1, stripe_status = 'active', plan = $1, updated_at = now()
               WHERE id = $2""",
            plan, account["id"],
        )
    else:
        # Active but the price doesn't map to a known plan — a config error,
        # not a reason to revoke an active payer. Record status only.
        await execute(
            "UPDATE accounts SET stripe_status = 'active', updated_at = now() WHERE id = $1",
            account["id"],
        )


async def _handle_payment_failed(invoice: dict):
    """A renewal payment failed — revoke paid access (fail closed).

    Stripe also transitions the subscription to past_due and fires
    subscription.updated, but handling the invoice event directly means we
    don't depend on that ordering.
    """
    customer_id = invoice.get("customer")
    if not customer_id:
        return
    account = await fetch_one(
        "SELECT id FROM accounts WHERE stripe_customer_id = $1", customer_id
    )
    if not account:
        return
    await execute(
        """UPDATE accounts
           SET stripe_status = 'past_due', plan = 'free', updated_at = now()
           WHERE id = $1""",
        account["id"],
    )


async def _handle_subscription_deleted(subscription: dict):
    """Revoke access when subscription is canceled."""
    customer_id = subscription.get("customer")

    account = await fetch_one(
        "SELECT id FROM accounts WHERE stripe_customer_id = $1", customer_id
    )
    if not account:
        return

    await execute(
        """UPDATE accounts
           SET stripe_status = 'canceled', plan = 'free',
               stripe_subscription_id = NULL, updated_at = now()
           WHERE id = $1""",
        account["id"],
    )


@router.get("/subscription")
async def get_subscription(
    user: AuthUser = Depends(verify_token),
    tenant_id: str = Depends(get_tenant_id),
):
    """Get current subscription status for the authenticated user."""
    account_id = user.id
    if account_id == "dev-user":
        account_id = "00000000-0000-0000-0000-000000000001"

    account = await fetch_one(
        """SELECT plan, stripe_customer_id, stripe_subscription_id,
                  stripe_plan, stripe_status, trial_ends_at
           FROM accounts WHERE id = $1""",
        account_id,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    from datetime import datetime, timezone
    trial_ends_at = account.get("trial_ends_at")
    trial_active = False
    trial_days_remaining = 0
    if trial_ends_at and (account.get("plan") or "free") == "free":
        now = datetime.now(timezone.utc)
        if trial_ends_at > now:
            trial_active = True
            trial_days_remaining = max(0, (trial_ends_at - now).days)

    return {
        "plan": account.get("plan") or "free",
        "stripe_plan": account.get("stripe_plan"),
        "stripe_status": account.get("stripe_status"),
        "has_subscription": bool(account.get("stripe_subscription_id")),
        "trial_active": trial_active,
        "trial_days_remaining": trial_days_remaining,
    }


@router.post("/portal")
async def create_portal(
    body: PortalRequest,
    user: AuthUser = Depends(verify_token),
    tenant_id: str = Depends(get_tenant_id),
):
    """Create a Stripe Customer Portal session for self-service subscription management."""
    s = _get_stripe()

    account_id = user.id
    if account_id == "dev-user":
        account_id = "00000000-0000-0000-0000-000000000001"

    account = await fetch_one(
        "SELECT stripe_customer_id FROM accounts WHERE id = $1",
        account_id,
    )
    if not account or not account.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No Stripe customer found. Subscribe to a plan first.")

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    return_url = body.return_url or f"{frontend_url}/settings"

    portal_session = s.billing_portal.Session.create(
        customer=account["stripe_customer_id"],
        return_url=return_url,
    )

    return {"portal_url": portal_session.url}


# =============================================
# Plan Limits & Usage Tracking
# =============================================

PLAN_LIMITS = {
    "free": {"videos_per_month": 2, "render_minutes": 10, "concurrent_jobs": 1},
    # $50 Basic — video generation, no Autopilot/Analytics/Competitor (gated by
    # PRO_PATHS in the frontend; starter is below the 'pro' tier).
    "starter": {"videos_per_month": 12, "render_minutes": 60, "concurrent_jobs": 1},
    # $100 Pro — everything, including Autopilot.
    "pro": {"videos_per_month": 30, "render_minutes": 180, "concurrent_jobs": 3},
    "agency": {"videos_per_month": 50, "render_minutes": 500, "concurrent_jobs": 5},
}


async def _get_or_create_usage(tenant_id: _uuid.UUID) -> dict:
    """Get current month's usage row, creating if needed."""
    row = await fetch_one(
        """SELECT * FROM tenant_usage
           WHERE tenant_id = $1 AND period_start = date_trunc('month', now())::date""",
        tenant_id,
    )
    if row:
        return dict(row)
    await execute(
        """INSERT INTO tenant_usage (tenant_id, period_start)
           VALUES ($1, date_trunc('month', now())::date)
           ON CONFLICT (tenant_id, period_start) DO NOTHING""",
        tenant_id,
    )
    row = await fetch_one(
        """SELECT * FROM tenant_usage
           WHERE tenant_id = $1 AND period_start = date_trunc('month', now())::date""",
        tenant_id,
    )
    return dict(row) if row else {"videos_created": 0, "api_calls": 0, "render_minutes": 0, "storage_bytes": 0}


async def _get_tenant_plan(tenant_id: _uuid.UUID) -> str:
    """Get plan for a tenant via membership -> account lookup.

    During active trial, free users get 'pro' limits.
    """
    row = await fetch_one(
        """SELECT a.plan, a.trial_ends_at FROM accounts a
           JOIN memberships m ON m.user_id = a.id
           WHERE m.tenant_id = $1 LIMIT 1""",
        tenant_id,
    )
    if not row:
        return "free"
    plan = row.get("plan") or "free"
    if plan == "free" and row.get("trial_ends_at"):
        from datetime import datetime, timezone
        if row["trial_ends_at"] > datetime.now(timezone.utc):
            return "pro"  # Active trial gets pro limits
    return plan


async def increment_usage(tenant_id, field: str, amount: int = 1):
    """Increment a usage counter for the current month."""
    valid_fields = {"videos_created", "api_calls", "render_minutes", "storage_bytes"}
    if field not in valid_fields:
        return
    await _get_or_create_usage(tenant_id)
    await execute(
        f"""UPDATE tenant_usage SET {field} = {field} + $1, updated_at = now()
            WHERE tenant_id = $2 AND period_start = date_trunc('month', now())::date""",
        amount, tenant_id,
    )


# Tier ladder for feature gating. Higher rank = more access. Trial users resolve
# to 'pro' via _get_tenant_plan, so an active trial passes a require_plan("pro") gate.
_PLAN_RANK = {"free": 0, "starter": 1, "pro": 2, "agency": 3, "studio": 3}


def require_plan(min_tier: str):
    """FastAPI dependency: 402 unless the tenant's plan is >= min_tier.

    Use on routes that sell a premium feature server-side (autopilot, analytics,
    competitor scraping) so the tier isn't UI-only/bypassable. Returns tenant_id
    so the route can keep using it. NOTE: only attach to routes whose frontend
    surfaces a clean upgrade prompt on 402 — don't gate endpoints a shared
    dashboard polls for everyone, or free users get a broken page.
    """
    async def _dep(tenant_id=Depends(get_tenant_id)):
        plan = await _get_tenant_plan(tenant_id)
        if _PLAN_RANK.get(plan, 0) < _PLAN_RANK.get(min_tier, 99):
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "plan_required",
                    "message": f"This feature requires the {min_tier.title()} plan or higher.",
                    "plan": plan,
                    "required": min_tier,
                    "upgrade_url": "/pricing",
                },
            )
        return tenant_id
    return _dep


async def _is_email_verified(tenant_id) -> bool:
    """Whether the tenant's account has confirmed its email. Defaults True on a
    lookup miss so a transient query issue never locks a tenant out."""
    row = await fetch_one(
        """SELECT a.email_verified FROM accounts a
           JOIN memberships m ON m.user_id = a.id
           WHERE m.tenant_id = $1 LIMIT 1""",
        tenant_id,
    )
    return True if not row else bool(row.get("email_verified"))


async def check_plan_limits(tenant_id, action: str = "video"):
    """Check if tenant is within plan limits. Raises 402 if over limit."""
    # Email-verification gate. Only enforced when EMAIL_VERIFY_REQUIRED=true —
    # kept OFF until the email sending domain is verified, so we never lock out
    # new users who can't yet receive the link. Existing accounts are
    # grandfathered verified (migration 059); Google signups are verified on
    # create. This is the single chokepoint every generate/render path calls.
    if os.getenv("EMAIL_VERIFY_REQUIRED", "false").lower() == "true":
        if not await _is_email_verified(tenant_id):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "email_not_verified",
                    "message": "Confirm your email to start generating — check your inbox for the link.",
                },
            )
    plan = await _get_tenant_plan(tenant_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    usage = await _get_or_create_usage(tenant_id)

    if action == "video" and usage.get("videos_created", 0) >= limits["videos_per_month"]:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "plan_limit_reached",
                "message": f"You've used {usage['videos_created']}/{limits['videos_per_month']} videos this month. Upgrade your plan for more.",
                "plan": plan,
                "limit": limits["videos_per_month"],
                "used": usage["videos_created"],
                "upgrade_url": "/pricing",
            },
        )
    elif action == "render" and float(usage.get("render_minutes", 0)) >= limits["render_minutes"]:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "plan_limit_reached",
                "message": f"You've used {usage['render_minutes']}/{limits['render_minutes']} render minutes this month. Upgrade your plan for more.",
                "plan": plan,
                "limit": limits["render_minutes"],
                "used": float(usage["render_minutes"]),
                "upgrade_url": "/pricing",
            },
        )


@router.get("/usage")
async def get_usage(tenant_id=Depends(get_tenant_id)):
    """Get current month's usage and plan limits."""
    plan = await _get_tenant_plan(tenant_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    usage = await _get_or_create_usage(tenant_id)

    return {
        "plan": plan,
        "limits": limits,
        "usage": {
            "videos_created": usage.get("videos_created", 0),
            "api_calls": usage.get("api_calls", 0),
            "render_minutes": float(usage.get("render_minutes", 0)),
            "storage_bytes": usage.get("storage_bytes", 0),
        },
        "period_start": str(usage.get("period_start", "")),
    }
