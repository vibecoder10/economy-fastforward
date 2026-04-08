"""Shared email utility — Resend API integration.

NOTE: The actual implementation lives in email_service.py to avoid
shadowing Python's stdlib 'email' package. Import from email_service
in application code: `from email_service import send_email`

Uses Resend (RESEND_API_KEY env var) for transactional emails.
"""


def send_email(*args, **kwargs):
    raise ImportError("Use 'from email_service import send_email' — email.py shadows stdlib")


def send_templated_email(*args, **kwargs):
    raise ImportError("Use 'from email_service import ...' — email.py shadows stdlib")
