"""Shared email utility using Resend API.

All email sending goes through this module.
Falls back to console logging when RESEND_API_KEY is not set.
"""

import html as html_lib
import os
from typing import Optional

import httpx


async def send_email(
    to: str,
    subject: str,
    html: str,
    from_address: Optional[str] = None,
) -> bool:
    """Send an email via Resend API.

    Returns True if sent (or logged in dev mode), False on failure.
    """
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        print(f"[DEV] Email to {to}: {subject}")
        return True

    sender = from_address or os.getenv("EMAIL_FROM", "StoryEngine <noreply@storyengine.ai>")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": sender,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
                timeout=10.0,
            )
            if resp.status_code not in (200, 201):
                print(f"[WARN] Email send failed ({resp.status_code}): {resp.text}")
                return False
            return True
    except Exception as e:
        print(f"[WARN] Email send error: {e}")
        return False


async def send_welcome_email(email: str, display_name: str) -> bool:
    """Send welcome email to new users."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    safe_name = html_lib.escape(display_name or "there")
    return await send_email(
        to=email,
        subject="Welcome to StoryEngine",
        html=(
            f"<h2>Welcome to StoryEngine, {safe_name}!</h2>"
            f"<p>Your AI video production pipeline is ready.</p>"
            f"<p>Get started: add API keys, set up your channel, create your first video.</p>"
            f'<p><a href="{frontend_url}">Go to your dashboard</a></p>'
        ),
    )


async def send_reset_email(email: str, token: str, expiry_hours: int = 1) -> bool:
    """Send password reset email."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        print(f"[DEV] Password reset token for {email}: {token}")
        return True

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    reset_url = f"{frontend_url}/reset-password?token={token}"
    return await send_email(
        to=email,
        subject="Reset your StoryEngine password",
        html=(
            f"<p>You requested a password reset.</p>"
            f'<p><a href="{reset_url}">Click here to reset your password</a></p>'
            f"<p>This link expires in {expiry_hours} hour.</p>"
            f"<p>If you didn't request this, you can safely ignore this email.</p>"
        ),
    )


async def send_verification_email(email: str, display_name: str, token: str) -> bool:
    """Send the 'confirm your email' link. Returns False if the send fails so the
    caller can tell the user to retry / resend."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    verify_url = f"{frontend_url}/verify-email?token={token}"
    safe_name = html_lib.escape(display_name or "there")
    return await send_email(
        to=email,
        subject="Confirm your email for StoryEngine",
        html=(
            f"<h2>Welcome to StoryEngine, {safe_name}!</h2>"
            f"<p>Confirm your email to start creating videos.</p>"
            f'<p><a href="{verify_url}" style="display:inline-block;padding:10px 18px;'
            f'background:#00D4AA;color:#0b0b0b;border-radius:8px;text-decoration:none;'
            f'font-weight:600">Confirm my email</a></p>'
            f'<p>Or paste this link into your browser:<br>{verify_url}</p>'
            f"<p>This link expires in 24 hours. If you didn't sign up, ignore this email.</p>"
        ),
    )


async def send_billing_receipt(email: str, plan: str, amount_display: str) -> bool:
    """Send billing receipt after successful checkout."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    safe_plan = html_lib.escape(plan or "")
    safe_amount = html_lib.escape(amount_display or "")
    return await send_email(
        to=email,
        subject=f"StoryEngine — Payment confirmed ({plan})",
        html=(
            f"<h2>Payment confirmed</h2>"
            f"<p>You're now on the <strong>{safe_plan}</strong> plan.</p>"
            f"<p>Amount: {safe_amount}</p>"
            f'<p><a href="{frontend_url}">Go to your dashboard</a></p>'
        ),
    )


async def send_trial_warning(email: str, display_name: str, days_left: int) -> bool:
    """Send trial expiry warning email."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    safe_name = html_lib.escape(display_name or "there")
    return await send_email(
        to=email,
        subject=f"Your StoryEngine trial expires in {days_left} day{'s' if days_left != 1 else ''}",
        html=(
            f"<h2>Hey {safe_name},</h2>"
            f"<p>Your free trial expires in <strong>{days_left} day{'s' if days_left != 1 else ''}</strong>.</p>"
            f"<p>Upgrade now to keep your pipeline running and unlock Autopilot + Analytics.</p>"
            f'<p><a href="{frontend_url}/pricing">View plans</a></p>'
        ),
    )


async def send_trial_expired(email: str, display_name: str) -> bool:
    """Send email when trial has expired and account has been downgraded."""
    import html as html_lib
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    safe_name = html_lib.escape(display_name or "there")
    return await send_email(
        to=email,
        subject="Your StoryEngine trial has ended",
        html=(
            f"<h2>Hey {safe_name},</h2>"
            f"<p>Your free trial just ended. Your account is still active on the <strong>Starter</strong> plan — "
            f"you can still log in, view your videos, and pick up where you left off.</p>"
            f"<p>To keep generating new videos with Autopilot + Analytics, upgrade anytime:</p>"
            f'<p><a href="{frontend_url}/pricing">See plans</a></p>'
            f"<p>Questions? Just reply to this email.</p>"
        ),
    )
