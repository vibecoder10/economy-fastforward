"""Functional test for Stage 6.5 / Cycle 45: surface discovery-refresh errors
to the user.

Pre-fix state: /api/discovery/refresh kicks off a background task, failures
get written to `_refresh_tasks[tenant_id]["error"]`, and the /status endpoint
returns that as `DiscoveryStatus.error`. The frontend type had `error: string
| null` — but the pipeline page (where most users click Refresh) never read
it. Discovery page already rendered a banner; pipeline page did not.

Effect: the "Refresh Ideas" button on pipeline would appear to fail silently.
The user would click, nothing would happen, and the real failure reason
(missing API key, Claude error, no competitors) was dropped on the floor.

This test pins the wire: the pipeline page must read `discoveryStatus.error`
and show a banner with the message + a Retry action. If a refactor removes
the banner, CI fails before the regression ships.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _frontend_src() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "src"


def _backend() -> Path:
    return Path(__file__).resolve().parents[2]


def _pipeline_page() -> Path:
    return _frontend_src() / "app" / "pipeline" / "page.tsx"


def _discovery_page() -> Path:
    return _frontend_src() / "app" / "discovery" / "page.tsx"


def _api_ts() -> Path:
    return _frontend_src() / "lib" / "api.ts"


def _discovery_py() -> Path:
    return _backend() / "routes" / "discovery.py"


def test_discovery_status_type_has_error_field():
    """The `error` field on DiscoveryStatus is the whole contract. If someone
    removes it from either side the banner dies silently."""
    fe = _api_ts().read_text()
    be = _discovery_py().read_text()
    # Frontend interface
    fe_match = re.search(
        r"interface\s+DiscoveryStatus\s*\{[^}]*error\s*:\s*string\s*\|\s*null",
        fe,
        re.DOTALL,
    )
    assert fe_match, (
        "DiscoveryStatus interface in lib/api.ts no longer has `error: string | null`. "
        "This is the only signal the UI has that a background refresh failed."
    )
    # Backend model
    be_match = re.search(
        r"class\s+DiscoveryStatus\s*\(BaseModel\)\s*:[^\n]*\n(?:[^\n]*\n){0,15}?\s*error\s*:\s*Optional\[str\]",
        be,
        re.DOTALL,
    )
    assert be_match, (
        "DiscoveryStatus pydantic model in routes/discovery.py no longer has "
        "`error: Optional[str]`. Without this the UI cannot surface refresh failures."
    )
    print("✅ test_discovery_status_type_has_error_field")


def test_pipeline_page_renders_discovery_error_banner():
    """Pipeline page must show a banner when a refresh fails. Before Cycle 45
    it silently dropped the error even though it was right there on
    discoveryStatus."""
    text = _pipeline_page().read_text()
    assert 'data-testid="discovery-error-banner"' in text, (
        "pipeline/page.tsx missing data-testid=discovery-error-banner — either "
        "the banner was removed or the testid moved. Playwright / regression "
        "cannot find it."
    )
    # The banner must be gated on error present AND not currently refreshing
    # (we don't want the error from last attempt shown while a new attempt is
    # in flight).
    gate = re.search(
        r"discoveryStatus\?\.error\s*&&\s*!discoveryStatus\.is_refreshing",
        text,
    )
    assert gate, (
        "pipeline/page.tsx missing the `discoveryStatus?.error && "
        "!discoveryStatus.is_refreshing` gate. Without it the stale error "
        "flashes during a retry."
    )
    # The banner must actually render the error text (not just check for its
    # presence and then show a generic message).
    renders_error = re.search(
        r"\{\s*discoveryStatus\.error\s*\}",
        text,
    )
    assert renders_error, (
        "pipeline/page.tsx checks for discoveryStatus.error but never renders "
        "the message itself — users see 'Last refresh failed' with no reason."
    )
    print("✅ test_pipeline_page_renders_discovery_error_banner")


def test_pipeline_error_banner_offers_retry():
    """A failure banner with no recovery action is a dead end. The banner
    must wire a Retry button to `refreshMutation.mutate()` so the user can
    re-attempt without hunting for the toolbar button."""
    text = _pipeline_page().read_text()
    # Anchor on the testid and scan the following chunk of JSX for a retry
    # invocation. 1800 chars is generous headroom for the banner block.
    idx = text.find('data-testid="discovery-error-banner"')
    assert idx >= 0, "discovery-error-banner testid not found"
    banner_chunk = text[idx : idx + 1800]
    assert "refreshMutation.mutate" in banner_chunk, (
        "discovery-error-banner does not wire a Retry action to refreshMutation."
    )
    print("✅ test_pipeline_error_banner_offers_retry")


def test_discovery_page_banner_still_present():
    """Stage 6.5 only adds to the pipeline page; the existing discovery-page
    banner must not regress. Both pages show the refresh button, so both need
    the error surfaced."""
    text = _discovery_page().read_text()
    assert re.search(
        r"status\?\.error\s*&&\s*!status\.is_refreshing", text
    ), (
        "discovery/page.tsx no longer renders the error banner. If it was "
        "intentionally moved, update this test — but do not drop it."
    )
    print("✅ test_discovery_page_banner_still_present")


def test_backend_error_messages_are_humanized():
    """Lock in that the backend writes user-readable errors (not raw
    exception text) to `_refresh_tasks[...]['error']`. We rely on this to
    render a helpful banner message instead of a stacktrace preview."""
    text = _discovery_py().read_text()
    # The two known paths: explicit friendly string for missing API key, and
    # humanize_error for generic exceptions. Either change would indicate a
    # refactor that should be accompanied by a test update.
    assert "No Claude or kie.ai API key configured. Add one in Settings → API Keys." in text, (
        "discovery.py no longer emits the 'No Claude or kie.ai API key configured' "
        "friendly error. Did the copy change? Update the test if intentional."
    )
    assert "humanize_error" in text, (
        "discovery.py no longer calls humanize_error for generic failures — "
        "raw exception messages would reach the UI."
    )
    print("✅ test_backend_error_messages_are_humanized")


TESTS = [
    test_discovery_status_type_has_error_field,
    test_pipeline_page_renders_discovery_error_banner,
    test_pipeline_error_banner_offers_retry,
    test_discovery_page_banner_still_present,
    test_backend_error_messages_are_humanized,
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
