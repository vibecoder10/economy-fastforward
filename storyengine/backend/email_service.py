"""Shared email utility using Resend API.

All email sending goes through this module.
Falls back to console logging when RESEND_API_KEY is not set.
"""

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
    return await send_email(
        to=email,
        subject="Welcome to StoryEngine",
        html=(
            f"<h2>Welcome to StoryEngine, {display_name}!</h2>"
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


async def send_billing_receipt(email: str, plan: str, amount_display: str) -> bool:
    """Send billing receipt after successful checkout."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    return await send_email(
        to=email,
        subject=f"StoryEngine — Payment confirmed ({plan})",
        html=(
            f"<h2>Payment confirmed</h2>"
            f"<p>You're now on the <strong>{plan}</strong> plan.</p>"
            f"<p>Amount: {amount_display}</p>"
            f'<p><a href="{frontend_url}">Go to your dashboard</a></p>'
        ),
    )


async def send_trial_warning(email: str, display_name: str, days_left: int) -> bool:
    """Send trial expiry warning email."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    return await send_email(
        to=email,
        subject=f"Your StoryEngine trial expires in {days_left} day{'s' if days_left != 1 else ''}",
        html=(
            f"<h2>Hey {display_name},</h2>"
            f"<p>Your free trial expires in <strong>{days_left} day{'s' if days_left != 1 else ''}</strong>.</p>"
            f"<p>Upgrade now to keep your pipeline running and unlock Autopilot + Analytics.</p>"
            f'<p><a href="{frontend_url}/pricing">View plans</a></p>'
        ),
    )
