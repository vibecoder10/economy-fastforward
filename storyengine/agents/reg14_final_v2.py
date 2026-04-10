"""
REG14 — StoryEngine Full Regression Test (DEFINITIVE)
All 14 pages + 6 video detail tabs + 2 mobile viewport checks.

Auth: context.add_init_script + page.route("**/api/auth/me")
Selectors: tuned from actual DOM inspection.
"""

import json, os, sys
from playwright.sync_api import sync_playwright

TAKE_ALL_SCREENSHOTS = '--screenshots' in sys.argv

BASE_URL = "http://localhost:3001"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDEiLCJpc3MiOiJzdG9yeWVuZ2luZSIsInRlbmFudF9pZCI6ImY2ODM5ZGUyLTM2OGMtNDQwZC04NTU5LTAyOTIwMjYxNzlmYSIsImV4cCI6MTc3NTMwNjEzOX0.M8JwDZ2hWlgJYXTyjnqC-PBpoxS03ThvQYV0GNSndwA"
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
VIDEO_ID = "f9749bd2-5045-42a5-b90e-ecd253bd7c20"

USER_MOCK = {
    "id": "00000000-0000-0000-0000-000000000001",
    "email": "ryan.ayler@gmail.com",
    "display_name": "Ryan",
    "avatar_url": None,
    "plan": "pro",
    "tenant_id": "f6839de2-368c-440d-8559-0292026179fa",
    "created_at": "2026-03-26 00:10:41.942902+00:00"
}

results = []


def should_ignore_error(url: str, status: int) -> bool:
    if status == 410 and "airtable" in url.lower():
        return True
    if status == 404 and "audio-token" in url.lower():
        return True
    return False


def make_page(browser, width=1440, height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script(f"localStorage.setItem('token', '{TOKEN}')")
    page = ctx.new_page()
    page.route("**/api/auth/me",
               lambda r: r.fulfill(status=200, content_type="application/json",
                                   body=json.dumps(USER_MOCK)))
    cerr, nerr = [], []
    page.on("console", lambda m: cerr.append(m.text) if m.type == "error" else None)
    page.on("response", lambda r: nerr.append(f"{r.status} {r.url}")
             if r.status >= 400 and not should_ignore_error(r.url, r.status) else None)
    return ctx, page, cerr, nerr


def goto(page, path, wait_ms=3000, timeout=15000):
    try:
        page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_timeout(wait_ms)
        return True
    except Exception as e:
        print(f"  nav error {path}: {e}")
        return False


def is_authed(page):
    try:
        body = page.evaluate("document.body.innerText")
        return "Sign in to your account" not in body and len(body.strip()) > 50
    except Exception:
        return False


def has_el(page, selector, timeout=5000):
    try:
        page.wait_for_selector(selector, timeout=timeout, state="visible")
        return True
    except Exception:
        return False


def get_main_text(page):
    try:
        return page.evaluate("""
            () => {
                const m = document.querySelector('main');
                return m ? m.innerText.trim().substring(0, 300) : document.body.innerText.trim().substring(0, 300);
            }
        """)
    except Exception:
        return ""


def ss(page, name, force=False):
    """Take screenshot. Only captures when --screenshots flag is passed or force=True (for failures)."""
    if not TAKE_ALL_SCREENSHOTS and not force:
        return
    try:
        page.screenshot(path=f"{SCREENSHOT_DIR}/reg14-{name}.png", full_page=False)
    except Exception as e:
        print(f"  screenshot error {name}: {e}")


def rec(name, ok, content, cerr, nerr, notes="", auth_note="OK"):
    results.append(dict(name=name, ok=ok, content=content,
                        cerr=cerr, nerr=nerr, notes=notes, auth_note=auth_note))


def print_results():
    print("\n" + "=" * 120)
    print(f"{'PAGE':<52} {'STATUS':<8} {'CONTENT':<9} {'AUTH':<8} {'CERR':<6} {'NERR':<6} NOTES")
    print("=" * 120)
    for r in results:
        c = "YES" if r["content"] else "NO "
        s = "OK" if r["ok"] else "FAIL"
        print(f"{r['name']:<52} {s:<8} {c:<9} {r['auth_note']:<8} {len(r['cerr']):<6} {len(r['nerr']):<6} {r['notes'][:55]}")
    print("=" * 120)
    ok_count = sum(1 for r in results if r["ok"])
    total = len(results)
    content_ok = sum(1 for r in results if r["content"])
    print(f"\nSUMMARY: {ok_count}/{total} pages passed | {content_ok}/{total} have content | {total - ok_count} failed")

    all_e = []
    for r in results:
        for e in r["cerr"]:
            all_e.append(f"  [{r['name'][:30]}] CONSOLE: {e[:110]}")
        for e in r["nerr"]:
            all_e.append(f"  [{r['name'][:30]}] NETWORK: {e[:110]}")
    if all_e:
        print(f"\nALL ERRORS ({len(all_e)}):")
        for e in all_e[:100]:
            print(e)
        if len(all_e) > 100:
            print(f"  ... +{len(all_e) - 100} more")
    else:
        print("\nNo console or network errors detected.")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── 1. Dashboard / ─────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/")
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Stat cards: "VIDEOS THIS MONTH", production overview
        content = "Production Overview" in main or "VIDEOS THIS MONTH" in main or has_el(page, "h1, h2", 3000)
        ss(page, "01-dashboard")
        print(f"[01-Dashboard  ] auth={authed} content={content}")
        rec("/ (dashboard)", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 2. /pipeline ───────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/pipeline")
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Pipeline: "Videos", stage filter buttons, video cards
        content = "Videos" in main and ("Idea Logged" in main or "In Production" in main or "Published" in main)
        ss(page, "02-pipeline")
        print(f"[02-Pipeline   ] auth={authed} content={content}")
        rec("/pipeline", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 3. /pipeline/VIDEO_ID + all 6 tabs ─────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, f"/pipeline/{VIDEO_ID}")
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Video detail: title + action buttons + tab nav
        content = "Back to Videos" in main and ("Research" in main or "Script" in main or "Render" in main)
        ss(page, "03-video-detail")
        print(f"[03-VideoDetail] auth={authed} content={content}")

        tab_results = []
        if authed:
            TABS = [
                ("Script", "script"),
                ("Storyboard & Visuals", "storyboard"),
                ("Thumbnail", "thumbnail"),
                ("Render", "render"),
                ("Performance", "performance"),
                ("Research", "research"),
            ]
            for tab_label, tab_slug in TABS:
                ce_before = len(ce)
                clicked = False
                for sel in [f"button:has-text('{tab_label}')",
                             f"[role='tab']:has-text('{tab_label}')"]:
                    try:
                        loc = page.locator(sel).first
                        if loc.count() > 0:
                            loc.click()
                            page.wait_for_timeout(1200)
                            clicked = True
                            break
                    except Exception:
                        pass
                if not clicked:
                    for partial in [tab_label, tab_label.split()[0]]:
                        try:
                            res = page.evaluate(f"""
                                () => {{
                                    for (const el of document.querySelectorAll('button, [role="tab"], a, li')) {{
                                        if ((el.innerText||'').trim().includes('{partial}')) {{
                                            el.click(); return true;
                                        }}
                                    }}
                                    return false;
                                }}
                            """)
                            if res:
                                clicked = True
                                page.wait_for_timeout(1200)
                                break
                        except Exception:
                            pass
                # Check content appeared after tab click
                tab_main = get_main_text(page)
                tab_content = len(tab_main.strip()) > 50
                new_e = len(ce) - ce_before
                tab_results.append(
                    f"{tab_label}:{'CLICK' if clicked else 'MISS'}/{'OK' if tab_content else 'EMPTY'}/E:{new_e}"
                )
                ss(page, f"03-tab-{tab_slug}")
                print(f"  Tab {tab_label:<25}: click={clicked} content={tab_content} errs={new_e}")

        tab_notes = " | ".join(tab_results) if tab_results else "no tabs"
        rec(f"/pipeline/{VIDEO_ID[:8]}... (detail+tabs)", authed, content, ce, ne,
            tab_notes, "OK" if authed else "FAIL")
        ctx.close()

        # ── 4. /review  (API-heavy: 7s wait) ───────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/review", wait_ms=7000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Review: tabs Scripts/Storyboards/Thumbnails/Images, count badges
        content = "Review" in main and ("Scripts" in main or "Storyboards" in main or "pending" in main)
        ss(page, "04-review")
        print(f"[04-Review     ] auth={authed} content={content}")
        rec("/review", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 5. /discovery  (API-heavy: 7s wait) ────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/discovery", wait_ms=7000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Discovery: idea cards with VPH, "ideas" count
        content = "Discovery" in main and ("ideas" in main.lower() or "VPH" in main or "fresh" in main.lower())
        ss(page, "05-discovery")
        print(f"[05-Discovery  ] auth={authed} content={content}")
        rec("/discovery", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 6. /competitors  (API-heavy: 7s wait) ──────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/competitors", wait_ms=7000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Competitors: channel pills, "Competitor Analysis", "All Channels"
        content = "Competitor" in main and ("Channel" in main or "Channels" in main)
        ss(page, "06-competitors")
        print(f"[06-Competitors] auth={authed} content={content}")
        rec("/competitors", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 7. /learnings ──────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/learnings", wait_ms=5000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        content = "Learnings" in main or "pattern" in main.lower() or has_el(page, "h1, h2, h3", 3000)
        ss(page, "07-learnings")
        print(f"[07-Learnings  ] auth={authed} content={content}")
        rec("/learnings", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 8. /autopilot ──────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/autopilot", wait_ms=5000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Autopilot: ON/OFF toggle, stat cards, recommendations
        content = "Autopilot" in main and ("ON" in main or "OFF" in main or "AVG CTR" in main)
        ss(page, "08-autopilot")
        print(f"[08-Autopilot  ] auth={authed} content={content}")
        rec("/autopilot", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 9. /analytics ──────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/analytics", wait_ms=5000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        content = "Analytics" in main or has_el(page, "h1, h2", 3000)
        ss(page, "09-analytics")
        print(f"[09-Analytics  ] auth={authed} content={content}")
        rec("/analytics", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 10. /calendar ──────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/calendar", wait_ms=5000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Calendar: "Production Calendar", month grid, video tiles
        content = "Calendar" in main and (
            "April" in main or "March" in main or "May" in main or "SUN" in main
        )
        ss(page, "10-calendar")
        print(f"[10-Calendar   ] auth={authed} content={content}")
        rec("/calendar", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 11. /settings ──────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/settings", wait_ms=4000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Settings: "Channel Settings", channel profile form, niche selector
        content = "Settings" in main and ("Channel" in main or "NICHE" in main or "Integrations" in main)
        ss(page, "11-settings")
        print(f"[11-Settings   ] auth={authed} content={content}")
        rec("/settings", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 12. /settings/keys ─────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/settings/keys", wait_ms=4000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # API Keys: Anthropic, ElevenLabs, Kie.ai, etc.
        content = "API Keys" in main or "Anthropic" in main or "ElevenLabs" in main
        ss(page, "12-settings-keys")
        print(f"[12-SettingsKey] auth={authed} content={content}")
        rec("/settings/keys", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 13. /profile ───────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        goto(page, "/profile", wait_ms=4000)
        authed = is_authed(page)
        main = get_main_text(page) if authed else ""
        # Profile: Name, Email, Plan badge, member since
        content = "Profile" in main and ("NAME" in main or "EMAIL" in main or "PLAN" in main)
        ss(page, "13-profile")
        print(f"[13-Profile    ] auth={authed} content={content}")
        rec("/profile", authed, content, ce, ne,
            main[:60].replace("\n", " "), "OK" if authed else "FAIL")
        ctx.close()

        # ── 14. /onboarding (public) ───────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser)
        page.goto(f"{BASE_URL}/onboarding", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        body = page.evaluate("document.body.innerText")[:300]
        # Onboarding: multi-step with CHANNEL, API KEYS, READY sections
        content = "CHANNEL" in body or "API KEYS" in body or "Your Channel" in body
        ss(page, "14-onboarding")
        print(f"[14-Onboarding ] (public) content={content}")
        rec("/onboarding", True, content, ce, ne,
            body[:70].replace("\n", " "), "PUBLIC")
        ctx.close()

        # ── MOBILE: /pipeline ──────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser, 375, 812)
        goto(page, "/pipeline", wait_ms=4000)
        authed = is_authed(page)
        scroll_w = page.evaluate("document.documentElement.scrollWidth") if authed else 999
        overflow = scroll_w > 375
        bottom_nav = []
        if authed:
            bottom_nav = page.evaluate("""
                () => Array.from(document.querySelectorAll(
                    'nav, footer, [class*="bottom"], [class*="tab"]'
                )).filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.height > 0 && r.bottom > window.innerHeight * 0.7;
                }).map(el => ({
                    cls: (el.className||'').substring(0,60),
                    h: Math.round(el.getBoundingClientRect().height)
                }))
            """)
        has_bottom = len(bottom_nav) > 0
        ss(page, "mobile-pipeline")
        notes = f"scrollW={scroll_w} {'OVERFLOW' if overflow else 'OK'} | bottomNav={'YES' if has_bottom else 'NO'}"
        print(f"[M-Pipeline    ] auth={authed} scrollW={scroll_w} overflow={overflow} bottomNav={has_bottom}")
        if has_bottom:
            print(f"  BottomNav: {bottom_nav[0]}")
        rec("/pipeline (mobile 375px)", not overflow and authed,
            not overflow and authed, ce, ne, notes, "OK" if authed else "FAIL")
        ctx.close()

        # ── MOBILE: / ──────────────────────────────────────────────────────────
        ctx, page, ce, ne = make_page(browser, 375, 812)
        goto(page, "/", wait_ms=4000)
        authed = is_authed(page)
        scroll_w = page.evaluate("document.documentElement.scrollWidth") if authed else 999
        overflow = scroll_w > 375
        bottom_nav = []
        if authed:
            bottom_nav = page.evaluate("""
                () => Array.from(document.querySelectorAll(
                    'nav, footer, [class*="bottom"], [class*="tab"]'
                )).filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.height > 0 && r.bottom > window.innerHeight * 0.7;
                }).map(el => ({
                    cls: (el.className||'').substring(0,60),
                    h: Math.round(el.getBoundingClientRect().height)
                }))
            """)
        has_bottom = len(bottom_nav) > 0
        ss(page, "mobile-dashboard")
        notes = f"scrollW={scroll_w} {'OVERFLOW' if overflow else 'OK'} | bottomNav={'YES' if has_bottom else 'NO'}"
        print(f"[M-Dashboard   ] auth={authed} scrollW={scroll_w} overflow={overflow} bottomNav={has_bottom}")
        rec("/ (mobile 375px)", not overflow and authed,
            not overflow and authed, ce, ne, notes, "OK" if authed else "FAIL")
        ctx.close()

        browser.close()

    print_results()


if __name__ == "__main__":
    run()
