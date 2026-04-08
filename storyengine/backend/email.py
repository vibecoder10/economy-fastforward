"""Shared email utility — re-exports from email_service to avoid stdlib conflict.

Import from email_service directly in application code.
This file exists for acceptance criteria compatibility.
"""

from email_service import (  # noqa: F401
    send_email,
    send_welcome_email,
    send_reset_email,
    send_billing_receipt,
    send_trial_warning,
)
