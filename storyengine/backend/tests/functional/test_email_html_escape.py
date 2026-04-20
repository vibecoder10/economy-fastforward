"""Functional test for SEC-EMAIL-001: prove user-controlled strings are
HTML-escaped before being dropped into email templates.

Pre-fix, a signup with display_name=``<script>alert(1)</script>`` would send
an email whose body contained the raw <script> tag, executed by any HTML
email client that renders script (rare) or — more likely — whose raw markup
could be leveraged for phishing via injected <a href>, <img>, or CSS.

Fix: html.escape() every user-provided string at the template boundary in
email_service.py. This test pins the boundary so a future "just pass
display_name in" patch can't silently regress.

No Resend API is hit — we intercept send_email() and inspect the `html` arg.
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import email_service


XSS_PAYLOADS = [
    "<script>alert('pwn')</script>",
    "<img src=x onerror=alert(1)>",
    "\"><svg onload=alert(1)>",
    "Robert'); DROP TABLE accounts;--",
    "<a href='javascript:alert(1)'>click me</a>",
]


def _capture_send():
    """Replace email_service.send_email with a capturing stub.
    Returns (captured_calls, restore_fn)."""
    captured = []

    async def fake_send(*, to, subject, html, from_address=None):
        captured.append({"to": to, "subject": subject, "html": html})
        return True

    original = email_service.send_email
    email_service.send_email = fake_send
    return captured, lambda: setattr(email_service, "send_email", original)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if (
        hasattr(asyncio, "_get_running_loop") and asyncio._get_running_loop()
    ) else asyncio.new_event_loop().run_until_complete(coro)


def _run_simple(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ───────────────────────── welcome_email ─────────────────────────

def test_welcome_email_escapes_display_name():
    """A malicious display_name must not appear raw in the welcome email HTML."""
    for payload in XSS_PAYLOADS:
        captured, restore = _capture_send()
        try:
            _run_simple(email_service.send_welcome_email("user@example.com", payload))
            assert captured, f"no email captured for payload: {payload!r}"
            html = captured[0]["html"]
            assert payload not in html, (
                f"raw XSS payload leaked into welcome email HTML:\n"
                f"  payload: {payload!r}\n  html:    {html[:200]!r}"
            )
            # Still renders a readable name — escape, don't drop.
            assert "<h2>" in html, "welcome email lost its header after escape"
        finally:
            restore()
    print("✅ test_welcome_email_escapes_display_name")


def test_welcome_email_empty_display_name_uses_fallback():
    """Empty display_name should render a safe fallback (not 'Hey ,')."""
    captured, restore = _capture_send()
    try:
        _run_simple(email_service.send_welcome_email("user@example.com", ""))
        html = captured[0]["html"]
        # Fallback greets 'there' rather than a blank.
        assert "Welcome to StoryEngine," in html
        assert "Welcome to StoryEngine, !" not in html, (
            "empty display_name rendered as blank — add a fallback"
        )
    finally:
        restore()
    print("✅ test_welcome_email_empty_display_name_uses_fallback")


# ───────────────────────── trial_warning ─────────────────────────

def test_trial_warning_escapes_display_name():
    for payload in XSS_PAYLOADS:
        captured, restore = _capture_send()
        try:
            _run_simple(email_service.send_trial_warning("u@e.com", payload, 3))
            html = captured[0]["html"]
            assert payload not in html, (
                f"raw XSS payload leaked into trial_warning HTML: {payload!r}"
            )
        finally:
            restore()
    print("✅ test_trial_warning_escapes_display_name")


def test_trial_warning_pluralization_still_works():
    """Escape logic must not break the 'day' vs 'days' pluralization."""
    captured, restore = _capture_send()
    try:
        _run_simple(email_service.send_trial_warning("u@e.com", "Ryan", 1))
        html_singular = captured[0]["html"]
        captured.clear()
        _run_simple(email_service.send_trial_warning("u@e.com", "Ryan", 3))
        html_plural = captured[0]["html"]
        assert "1 day<" in html_singular or "1 day</" in html_singular
        assert "3 days<" in html_plural or "3 days</" in html_plural
    finally:
        restore()
    print("✅ test_trial_warning_pluralization_still_works")


# ───────────────────────── trial_expired ─────────────────────────

def test_trial_expired_escapes_display_name():
    """trial_expired already escaped pre-cycle — pin it so nobody regresses."""
    for payload in XSS_PAYLOADS:
        captured, restore = _capture_send()
        try:
            _run_simple(email_service.send_trial_expired("u@e.com", payload))
            html = captured[0]["html"]
            assert payload not in html, (
                f"raw XSS payload leaked into trial_expired HTML: {payload!r}"
            )
        finally:
            restore()
    print("✅ test_trial_expired_escapes_display_name")


# ───────────────────────── billing_receipt ─────────────────────────

def test_billing_receipt_escapes_plan_and_amount():
    """Stripe-originated values are typically safe, but defense-in-depth.
    If a plan or amount_display ever reflects arbitrary input, it must escape."""
    for payload in XSS_PAYLOADS:
        captured, restore = _capture_send()
        try:
            _run_simple(email_service.send_billing_receipt("u@e.com", payload, "$29.00"))
            html = captured[0]["html"]
            assert payload not in html, (
                f"raw XSS payload leaked via plan into billing_receipt HTML: {payload!r}"
            )
        finally:
            restore()

        captured, restore = _capture_send()
        try:
            _run_simple(email_service.send_billing_receipt("u@e.com", "Creator", payload))
            html = captured[0]["html"]
            assert payload not in html, (
                f"raw XSS payload leaked via amount_display into billing_receipt HTML: {payload!r}"
            )
        finally:
            restore()
    print("✅ test_billing_receipt_escapes_plan_and_amount")


# ───────────────────────── boundary check ─────────────────────────

def test_html_escape_actually_applied():
    """Positive check: after fix, the escaped entity must appear in the HTML.
    This catches a 'forgot to escape at all' regression even if the raw
    payload substring-match test happens to false-negative."""
    captured, restore = _capture_send()
    try:
        _run_simple(email_service.send_welcome_email("u@e.com", "<b>Ryan</b>"))
        html = captured[0]["html"]
        assert "&lt;b&gt;Ryan&lt;/b&gt;" in html, (
            f"display_name was not HTML-escaped at all. html={html[:300]!r}"
        )
    finally:
        restore()
    print("✅ test_html_escape_actually_applied")


# ───────────────────────── runner ─────────────────────────

TESTS = [
    test_welcome_email_escapes_display_name,
    test_welcome_email_empty_display_name_uses_fallback,
    test_trial_warning_escapes_display_name,
    test_trial_warning_pluralization_still_works,
    test_trial_expired_escapes_display_name,
    test_billing_receipt_escapes_plan_and_amount,
    test_html_escape_actually_applied,
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
