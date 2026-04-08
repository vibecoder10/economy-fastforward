"""Stripe billing routes: checkout, webhooks, subscription management, portal, usage tracking."""

import os
import uuid as _uuid

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from auth import get_tenant_id, verify_token, AuthUser
from database import fetch_one, fetch_all, execute

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

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data)

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

    if plan:
        effective_plan = plan if sub_status == "active" else "free"
        await execute(
            """UPDATE accounts
               SET stripe_plan = $1, stripe_status = $2, plan = $3, updated_at = now()
               WHERE id = $4""",
            plan, sub_status, effective_plan, account["id"],
        )
    else:
        await execute(
            "UPDATE accounts SET stripe_status = $1, updated_at = now() WHERE id = $2",
            sub_status, account["id"],
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
                  stripe_plan, stripe_status
           FROM accounts WHERE id = $1""",
        account_id,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return {
        "plan": account.get("plan") or "free",
        "stripe_plan": account.get("stripe_plan"),
        "stripe_status": account.get("stripe_status"),
        "has_subscription": bool(account.get("stripe_subscription_id")),
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
    "starter": {"videos_per_month": 4, "render_minutes": 30, "concurrent_jobs": 1},
    "pro": {"videos_per_month": 15, "render_minutes": 120, "concurrent_jobs": 3},
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
    """Get plan for a tenant via membership -> account lookup."""
    row = await fetch_one(
        """SELECT a.plan FROM accounts a
           JOIN memberships m ON m.user_id = a.id
           WHERE m.tenant_id = $1 LIMIT 1""",
        tenant_id,
    )
    return (row.get("plan") if row else None) or "free"


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


async def check_plan_limits(tenant_id, action: str = "video"):
    """Check if tenant is within plan limits. Raises 402 if over limit."""
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
