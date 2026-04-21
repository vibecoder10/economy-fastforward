"""Functional test for Stage 6.2 / Cycle 44: the persistent first-run
studio-readiness checklist.

Onboarding can finish while YouTube is still disconnected or a key never got
saved (step-2 skip + auto-complete paths). FinishSetupBanner only catches the
pre-completion case. Post-completion, users previously lost every reminder —
the dashboard showed stat cards full of zeros with no indication that a gate
was still open. This checklist fills that gap.

This test pins the contract so the wiring can't quietly regress:
- the component file exists with the expected exports
- it reads the three gate fields from OnboardingStatus (keys / yt / first video)
- the dashboard page imports and renders it, gated on onboarding.completed
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _frontend_src() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "src"


def _checklist_path() -> Path:
    return _frontend_src() / "components" / "onboarding" / "FirstRunChecklist.tsx"


def _dashboard_path() -> Path:
    return _frontend_src() / "app" / "dashboard" / "page.tsx"


def test_first_run_checklist_component_exists():
    """FirstRunChecklist.tsx must exist and export the component."""
    p = _checklist_path()
    assert p.exists(), f"FirstRunChecklist missing at {p}"
    text = p.read_text()
    assert "export function FirstRunChecklist" in text, (
        "FirstRunChecklist component export not found"
    )
    assert 'data-testid="first-run-checklist"' in text, (
        "missing data-testid anchor — Playwright can't find the banner"
    )
    print("✅ test_first_run_checklist_component_exists")


def test_checklist_reads_three_gate_fields():
    """The checklist must read the three gates from OnboardingStatus:
    api_keys.configured/required, youtube_connected, first_video_created.
    If someone refactors the status shape without updating this component,
    this test fails loud."""
    text = _checklist_path().read_text()
    required_reads = [
        "api_keys",
        "configured",
        "required",
        "youtube_connected",
        "first_video_created",
    ]
    missing = [r for r in required_reads if r not in text]
    assert not missing, (
        f"FirstRunChecklist no longer reads these OnboardingStatus fields: {missing}. "
        "Did the status shape change? Update the component in lockstep."
    )
    print("✅ test_checklist_reads_three_gate_fields")


def test_checklist_hides_when_all_gates_met():
    """Contract: the checklist returns null when all gates are done. Without
    this, users who finish setup see a permanent 'Studio setup 3 of 3 ready'
    strip — nag even after success."""
    text = _checklist_path().read_text()
    # The "hide when complete" guard must exist. We look for the idiomatic
    # return-null-when-full-count pattern.
    pattern = re.compile(r"doneCount\s*===\s*gates\.length[^\n]*return\s+null", re.DOTALL)
    assert pattern.search(text), (
        "FirstRunChecklist missing the 'hide when all gates met' guard. "
        "Expected `if (doneCount === gates.length) return null;` or equivalent."
    )
    print("✅ test_checklist_hides_when_all_gates_met")


def test_checklist_links_to_actionable_pages():
    """Each incomplete gate must link somewhere the user can act. Regression
    lock against someone stubbing href='#' during a refactor."""
    text = _checklist_path().read_text()
    # Must link to settings (keys + yt) and pipeline (first video).
    assert 'href: "/settings"' in text, "checklist missing /settings link for keys/YT gates"
    assert 'href: "/pipeline"' in text, "checklist missing /pipeline link for first-video gate"
    print("✅ test_checklist_links_to_actionable_pages")


def test_dashboard_imports_and_renders_checklist():
    """Dashboard must import FirstRunChecklist and render it gated on
    onboarding.completed. If the import or the render site is removed, users
    silently lose the reminder — this test catches that."""
    text = _dashboard_path().read_text()
    # Import check
    import_pat = re.compile(
        r'import\s*\{\s*FirstRunChecklist\s*\}\s*from\s*["\']'
        r'(?:@/components/onboarding/FirstRunChecklist|\.\./\.\./components/onboarding/FirstRunChecklist)'
        r'["\']'
    )
    assert import_pat.search(text), (
        "dashboard/page.tsx no longer imports FirstRunChecklist — did someone "
        "delete the import during a refactor?"
    )
    # Render check: component is referenced as a JSX element
    assert "<FirstRunChecklist" in text, (
        "dashboard/page.tsx imports FirstRunChecklist but doesn't render it"
    )
    # Gated on onboarding.completed (post-completion only — pre-completion is
    # FinishSetupBanner's job)
    gated = re.search(
        r"onboarding\?\.completed\s*&&\s*\([\s\S]{0,200}<FirstRunChecklist",
        text,
    )
    assert gated, (
        "FirstRunChecklist must be gated on `onboarding?.completed` — otherwise "
        "it competes with FinishSetupBanner during pre-completion."
    )
    print("✅ test_dashboard_imports_and_renders_checklist")


TESTS = [
    test_first_run_checklist_component_exists,
    test_checklist_reads_three_gate_fields,
    test_checklist_hides_when_all_gates_met,
    test_checklist_links_to_actionable_pages,
    test_dashboard_imports_and_renders_checklist,
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
