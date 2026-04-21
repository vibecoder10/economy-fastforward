"""Functional test for Stage 6.5 / Cycle 54: Refresh Ideas silent-failure
regression lock.

The bug (pre-fix): the Discovery "Refresh Ideas" button kicks off a
background task. When that task failed (no competitor videos scraped yet,
Claude rate limit, DB error, missing API key), the error was stored in
`_refresh_tasks[tenant_id]["error"]` and returned by
`GET /api/discovery/status` — but the frontend never displayed it. Users
clicked Refresh, nothing happened, they thought the button was broken.

The fix (landed):
1. `DiscoveryStatus` TypeScript interface in `frontend/src/lib/api.ts`
   gained an `error: string | null` field — so the value typed through
   and the UI could use it.
2. Discovery page (`frontend/src/app/discovery/page.tsx`) renders a
   red error banner (`status?.error && !status.is_refreshing`) showing
   "Last refresh failed: {status.error}".
3. Pipeline page (`frontend/src/app/pipeline/page.tsx`) renders the
   same error in its refresh-status card via `discoveryStatus.error`.
4. Backend `DiscoveryStatus` pydantic model still exposes `error:
   Optional[str]`.
5. Backend `/refresh` flow produces a human-friendly message when there
   are no competitor videos ("Scrape competitor channels first.") and
   routes other exceptions through `humanize_error()` instead of leaking
   raw stack text.

This test pins all five so a refactor can't silently reintroduce the
swallow-the-error bug:
  - TS interface still has the field.
  - Both pages still render it.
  - Backend pydantic model still exposes it.
  - Backend still produces the friendly "scrape first" message.
  - Backend still imports + calls `humanize_error`.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _storyengine_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _api_ts() -> Path:
    return _storyengine_root() / "frontend" / "src" / "lib" / "api.ts"


def _discovery_page() -> Path:
    return _storyengine_root() / "frontend" / "src" / "app" / "discovery" / "page.tsx"


def _pipeline_page() -> Path:
    return _storyengine_root() / "frontend" / "src" / "app" / "pipeline" / "page.tsx"


def _discovery_route() -> Path:
    return _storyengine_root() / "backend" / "routes" / "discovery.py"


def test_ts_interface_has_error_field():
    """The fix hinges on the frontend types declaring the `error` field —
    otherwise TS would refuse to read `status.error` and the banner would
    never render."""
    text = _api_ts().read_text()
    m = re.search(
        r"export\s+interface\s+DiscoveryStatus\s*\{([^}]+)\}",
        text,
    )
    assert m, (
        "DiscoveryStatus interface no longer defined in frontend/src/lib/api.ts. "
        "If it moved or was renamed, update this test — but keep the `error` "
        "field, it's what makes Refresh Ideas failures visible."
    )
    body = m.group(1)
    assert re.search(r"\berror\s*:\s*string\s*\|\s*null\b", body), (
        "Stage 6.5 regression — DiscoveryStatus no longer has "
        "`error: string | null`. The field is how backend refresh failures "
        "reach the red banner UI. Without it, the button appears broken."
    )
    print("✅ test_ts_interface_has_error_field")


def test_discovery_page_renders_error_banner():
    """The red 'Last refresh failed' banner on the Discovery page is the
    user-visible half of the fix — if it disappears, refresh failures go
    silent again."""
    text = _discovery_page().read_text()
    # Conditional guard — we only show the banner when there IS an error
    # AND the task isn't currently running (otherwise it's just a stale
    # error being overwritten).
    assert re.search(
        r"status\??\.error\s*&&\s*!\s*status\.is_refreshing",
        text,
    ), (
        "Stage 6.5 regression — Discovery page no longer gates the error "
        "banner on `status?.error && !status.is_refreshing`. Either the "
        "banner was removed or the conditional changed — re-introduce the "
        "gated render or the UI hides refresh failures again."
    )
    # Human-readable copy — the raw error is shown but with a clear lead
    assert re.search(
        r"[Ll]ast\s+refresh\s+failed",
        text,
    ), (
        "Stage 6.5 regression — Discovery page no longer labels the error "
        "banner with 'Last refresh failed'. The raw error text alone is "
        "ambiguous; users won't know it's a refresh issue."
    )
    print("✅ test_discovery_page_renders_error_banner")


def test_pipeline_page_renders_error():
    """The Pipeline tab has its own Discovery status card — it must also
    render the error, otherwise power users staying on Pipeline never see
    the failure."""
    text = _pipeline_page().read_text()
    assert re.search(
        r"discoveryStatus\??\.error",
        text,
    ), (
        "Stage 6.5 regression — Pipeline page no longer references "
        "`discoveryStatus.error`. The status card there would hide refresh "
        "failures even though the field is available on the API response."
    )
    # Reuse the "Last refresh failed" label for consistency
    assert re.search(
        r"[Ll]ast\s+refresh\s+failed",
        text,
    ), (
        "Stage 6.5 regression — Pipeline page no longer labels its "
        "Discovery error section as 'Last refresh failed'."
    )
    print("✅ test_pipeline_page_renders_error")


def test_backend_status_model_exposes_error():
    """Frontend can't show what the backend doesn't send. The pydantic
    model that serializes `/api/discovery/status` must keep the `error`
    field — otherwise even a perfect UI gets an empty string every time."""
    text = _discovery_route().read_text()
    m = re.search(
        r"class\s+DiscoveryStatus\s*\(\s*BaseModel\s*\)\s*:\s*([\s\S]+?)(?=\nclass\s|\n@router|\n# ---|\Z)",
        text,
    )
    assert m, (
        "DiscoveryStatus pydantic model not found in routes/discovery.py. "
        "If it moved, update this test — but preserve the `error` field."
    )
    body = m.group(1)
    assert re.search(
        r"\berror\s*:\s*Optional\s*\[\s*str\s*\]", body
    ), (
        "Stage 6.5 regression — backend DiscoveryStatus no longer exposes "
        "`error: Optional[str]`. The status endpoint won't serialize the "
        "failure reason and the UI will show empty banners."
    )
    print("✅ test_backend_status_model_exposes_error")


def test_backend_produces_friendly_no_competitors_message():
    """The #1 cause of a failed refresh for new users is 'no competitors
    scraped yet'. The fix specifically called for a friendly message on
    that path — not the raw DB count or a stack trace."""
    text = _discovery_route().read_text()
    # The exact copy or a close variant — allow wording drift but require
    # the 'scrape ... first' shape.
    assert re.search(
        r"[Ss]crape\s+competitor\s+channels?\s+first",
        text,
    ), (
        "Stage 6.5 regression — the friendly 'Scrape competitor channels "
        "first.' message is no longer produced when a tenant has 0 "
        "competitor videos. New users will see a raw DB error instead."
    )
    # AND the message must be stored where the status endpoint can read it
    assert re.search(
        r"_refresh_tasks\s*\[\s*tenant_id\s*\]\s*=\s*\{[^}]*['\"]error['\"]\s*:",
        text,
    ), (
        "Stage 6.5 regression — the friendly message is no longer written "
        "into `_refresh_tasks[tenant_id]['error']`. Without that, the "
        "status endpoint never sees it and the UI banner stays empty."
    )
    print("✅ test_backend_produces_friendly_no_competitors_message")


def test_backend_uses_humanize_error():
    """Every other exception path should route through `humanize_error`
    so users don't see Python stack text (which was the original bug
    shape before this cycle)."""
    text = _discovery_route().read_text()
    # Must import it
    assert re.search(
        r"from\s+error_utils\s+import\s+[^\n]*\bhumanize_error\b",
        text,
    ), (
        "Stage 6.5 regression — routes/discovery.py no longer imports "
        "`humanize_error` from error_utils. Unhandled exceptions would "
        "leak to users as raw stack text again."
    )
    # And must actually call it at least once
    assert re.search(r"\bhumanize_error\s*\(", text), (
        "Stage 6.5 regression — routes/discovery.py imports "
        "`humanize_error` but never calls it. Every refresh exception "
        "would bypass the friendly-copy layer."
    )
    print("✅ test_backend_uses_humanize_error")


TESTS = [
    test_ts_interface_has_error_field,
    test_discovery_page_renders_error_banner,
    test_pipeline_page_renders_error,
    test_backend_status_model_exposes_error,
    test_backend_produces_friendly_no_competitors_message,
    test_backend_uses_humanize_error,
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
