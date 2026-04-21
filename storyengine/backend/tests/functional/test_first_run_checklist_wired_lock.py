"""Functional test for Stage 6.2 / Cycle 56: first-run checklist
regression lock.

The bug (pre-fix): new users landed on the dashboard after onboarding
with no guidance — 27 pages, no clear "what do I do next?" path. High
bounce rate on first login. Onboarding itself could be marked complete
while key gates (API keys saved, YouTube connected, first video made)
were still open, and then the user had no reminder.

The fix (landed — Stage 6.2):
1. `FirstRunChecklist` component in `frontend/src/components/onboarding/`
   renders a 3-gate strip (add API keys, connect YouTube, create first
   video) that stays visible on the dashboard until ALL three gates are
   green — even after onboarding is marked complete.
2. Backend `GET /api/dashboard/onboarding/status` computes gate state
   from real DB reads: `channel_profiles.channel_name`,
   `channel_profiles.youtube_refresh_token`, secret configured counts,
   and `videos` row count — never from a stale "onboarding flag."
3. TypeScript `OnboardingStatus` type mirrors the backend shape so the
   checklist reads the fields directly with no adapter layer.
4. The checklist is mounted on the dashboard (not the onboarding page)
   so returning users see it, not just first-session users.

This test pins each of those load-bearing pieces:
  - Backend endpoint exists + returns the expected step fields.
  - TS type mirrors the backend response shape.
  - `FirstRunChecklist` component exists and reads the expected gates.
  - Dashboard page imports + renders `FirstRunChecklist`.
  - The 3 user-visible gates (API keys, YouTube, first video) are all
    wired to real DB state, not hardcoded `true`.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _storyengine_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _dashboard_route() -> Path:
    return _storyengine_root() / "backend" / "routes" / "dashboard.py"


def _dashboard_page() -> Path:
    return _storyengine_root() / "frontend" / "src" / "app" / "dashboard" / "page.tsx"


def _checklist_component() -> Path:
    return (
        _storyengine_root()
        / "frontend"
        / "src"
        / "components"
        / "onboarding"
        / "FirstRunChecklist.tsx"
    )


def _api_ts() -> Path:
    return _storyengine_root() / "frontend" / "src" / "lib" / "api.ts"


def test_backend_onboarding_status_endpoint():
    """The endpoint must exist, live under `/dashboard` router, and
    return the 6 step fields the frontend reads. If any field goes
    missing the checklist silently reports that gate as `undefined`
    (falsy → "not done") and we're back to the unstarted-new-user pit."""
    text = _dashboard_route().read_text()
    assert re.search(
        r'@router\.get\(\s*["\']/onboarding/status["\']\s*\)', text
    ), (
        "Stage 6.2 regression — `/onboarding/status` endpoint removed "
        "from backend/routes/dashboard.py. The dashboard FirstRunChecklist "
        "has nothing to read."
    )
    # Must return each step the UI gates on
    required_fields = [
        "channel_configured",
        "api_keys",
        "youtube_connected",
        "first_video_created",
    ]
    missing = [f for f in required_fields if f not in text]
    assert not missing, (
        "Stage 6.2 regression — onboarding/status response no longer "
        f"contains required step fields: {missing}. Every missing field "
        "shows as 'not done' forever on the checklist."
    )
    print("✅ test_backend_onboarding_status_endpoint")


def test_backend_gates_read_from_db_not_hardcoded():
    """Every gate must be computed from a real DB read — not from a
    constant. If a gate gets hardcoded `True` during a refactor, users
    who haven't actually done the step see it as done forever."""
    text = _dashboard_route().read_text()
    # Find the get_onboarding_status function body. The signature contains
    # a `Depends(get_tenant_id)` default, so `\([^)]*\)` on params fails —
    # match up to the FIRST `:` that terminates the def line instead.
    m = re.search(
        r"async\s+def\s+get_onboarding_status\s*\([\s\S]+?\)\s*:([\s\S]+?)(?=\nasync\s+def\s|\ndef\s|\Z)",
        text,
    )
    assert m, "get_onboarding_status function not found"
    body = m.group(1)

    # channel_configured must be derived from channel_profiles query
    assert re.search(
        r"channel_profiles[\s\S]{0,200}channel_name", body, re.IGNORECASE
    ), "channel_configured no longer reads channel_profiles.channel_name"
    # youtube_connected must derive from youtube_refresh_token
    assert "youtube_refresh_token" in body, (
        "youtube_connected no longer derives from youtube_refresh_token. "
        "A hardcoded or simpler check would let unconnected users see "
        "the gate as 'done'."
    )
    # first_video_created must come from a videos table count
    assert re.search(
        r"FROM\s+videos\s+WHERE\s+tenant_id", body, re.IGNORECASE
    ), "first_video_created no longer derives from videos table count"
    # api_keys must loop + check each required key is configured
    assert "required_keys" in body and "get_secret_status" in body, (
        "api_keys.configured no longer iterates required_keys via "
        "get_secret_status. A static count would be wrong on first boot."
    )
    print("✅ test_backend_gates_read_from_db_not_hardcoded")


def test_ts_type_mirrors_backend_shape():
    """The frontend reads fields by dotted path — `status.steps.api_keys.configured`
    etc. If the TS type drops a field, the checklist still compiles but
    the gate flips to undefined → falsy → "not done" forever."""
    text = _api_ts().read_text()
    m = re.search(
        r"export\s+type\s+OnboardingStatus\s*=\s*\{([\s\S]+?)\n\};",
        text,
    )
    assert m, "OnboardingStatus type missing from frontend/src/lib/api.ts"
    body = m.group(1)
    required = [
        r"\bchannel_configured\s*:\s*boolean\b",
        r"\bapi_keys\s*:\s*\{[^}]*configured\s*:\s*number[^}]*required\s*:\s*number[^}]*\}",
        r"\byoutube_connected\s*:\s*boolean\b",
        r"\bfirst_video_created\s*:\s*boolean\b",
    ]
    missing = [pat for pat in required if not re.search(pat, body)]
    assert not missing, (
        "Stage 6.2 regression — OnboardingStatus TS type no longer has "
        f"required fields (patterns not found): {missing}. "
        "Dashboard checklist will silently gate on undefined."
    )
    print("✅ test_ts_type_mirrors_backend_shape")


def test_first_run_checklist_component_reads_expected_gates():
    """The component file must exist and must read the three gates
    (api_keys / youtube_connected / first_video_created) from the
    status prop. If it's gutted or the field names drift, the strip
    stops firing for users who still need the reminders."""
    path = _checklist_component()
    assert path.exists(), (
        "Stage 6.2 regression — FirstRunChecklist.tsx deleted. "
        "Dashboard will import-fail and the whole page breaks; or worse, "
        "if import was removed too, new users lose the reminder strip."
    )
    text = path.read_text()
    assert re.search(
        r"status\.steps\.api_keys\.configured", text
    ), "FirstRunChecklist no longer reads status.steps.api_keys.configured"
    assert re.search(
        r"status\.steps\.youtube_connected", text
    ), "FirstRunChecklist no longer reads status.steps.youtube_connected"
    assert re.search(
        r"status\.steps\.first_video_created", text
    ), "FirstRunChecklist no longer reads status.steps.first_video_created"
    print("✅ test_first_run_checklist_component_reads_expected_gates")


def test_dashboard_mounts_first_run_checklist():
    """The checklist has to be mounted on the DASHBOARD (not just the
    onboarding page) — that's the whole point: returning users who
    skipped a step still see the gates. If the import is dropped or the
    JSX <FirstRunChecklist /> is removed, the fix is undone."""
    text = _dashboard_page().read_text()
    assert re.search(
        r'import\s+\{\s*FirstRunChecklist\s*\}\s+from\s+["\'][^"\']*FirstRunChecklist["\']',
        text,
    ), (
        "Stage 6.2 regression — dashboard/page.tsx no longer imports "
        "FirstRunChecklist. The strip will not render for returning users."
    )
    assert re.search(r"<FirstRunChecklist\b", text), (
        "Stage 6.2 regression — dashboard/page.tsx imports "
        "FirstRunChecklist but no longer renders it. Same effect as "
        "removing the import entirely."
    )
    print("✅ test_dashboard_mounts_first_run_checklist")


TESTS = [
    test_backend_onboarding_status_endpoint,
    test_backend_gates_read_from_db_not_hardcoded,
    test_ts_type_mirrors_backend_shape,
    test_first_run_checklist_component_reads_expected_gates,
    test_dashboard_mounts_first_run_checklist,
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
