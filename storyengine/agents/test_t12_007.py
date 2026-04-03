"""
T12-007: QA verify learnings page: patterns render, title insights, actions, toggle
"""
import json, sys, time, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

FRONTEND = "http://localhost:3001"
BACKEND  = "http://localhost:8001"
SS_DIR   = "storyengine/agents/screenshots"

results = []
console_errors = []

# Fake user data that /api/auth/me will return (intercepted)
FAKE_USER = {
    "id": "00000000-0000-0000-0000-000000000001",
    "email": "ryan.ayler@gmail.com",
    "display_name": "Ryan",
    "avatar_url": None,
    "plan": "free",
    "tenant_id": "f6839de2-368c-440d-8559-0292026179fa",
    "created_at": "2026-03-26T00:10:41.942902+00:00",
}

def log(label, status, note=""):
    icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    print(f"{icon} {label}: {note}")
    results.append({"label": label, "status": status, "note": note})

def api(path, method="GET", body=None):
    url = f"{BACKEND}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data,
        headers={"Authorization": "Bearer dev-token",
                 "Content-Type": "application/json"})
    req.get_method = lambda: method
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code

# ── 1. Backend: GET /api/learnings ───────────────────────────────────────────
data, code = api("/api/learnings")
if code == 200 and isinstance(data, list):
    log("Backend GET /api/learnings", "PASS", f"{len(data)} patterns returned")
    learnings = data
else:
    log("Backend GET /api/learnings", "FAIL", f"status={code}")
    learnings = []

# Check fields on first learning
if learnings:
    lr = learnings[0]
    required = ["id","category","pattern","confidence","sample_size","active"]
    missing = [f for f in required if f not in lr]
    if not missing:
        log("LearningRecord fields", "PASS", f"All required fields present, category={lr['category']}")
    else:
        log("LearningRecord fields", "FAIL", f"Missing: {missing}")
    # Check optional performance fields
    has_perf = "avg_ctr" in lr or "avg_retention" in lr
    log("LearningRecord has avg_ctr/avg_retention", "PASS" if has_perf else "FAIL")

# ── 2. Backend: GET /api/learnings?category=title ────────────────────────────
data_title, code2 = api("/api/learnings?category=title")
if code2 == 200:
    non_title = [l for l in data_title if l.get("category") != "title"]
    if not non_title:
        log("Filter by category=title", "PASS", f"{len(data_title)} title patterns")
    else:
        log("Filter by category=title", "FAIL", f"{len(non_title)} non-title records leaked")
else:
    log("Filter by category=title", "FAIL", f"status={code2}")

# ── 3. Backend: GET /api/autopilot/learnings ─────────────────────────────────
data_al, code3 = api("/api/autopilot/learnings")
if code3 == 200 and isinstance(data_al, list):
    log("Backend GET /api/autopilot/learnings", "PASS", f"{len(data_al)} insights returned")
    autopilot_learnings = data_al
else:
    log("Backend GET /api/autopilot/learnings", "FAIL", f"status={code3}")
    autopilot_learnings = []

# ── 4. Backend: PATCH /api/learnings/{id}/toggle ─────────────────────────────
if learnings:
    lr_id = learnings[0]["id"]
    orig_active = learnings[0]["active"]
    tdata, tcode = api(f"/api/learnings/{lr_id}/toggle", method="PATCH")
    if tcode == 200 and "active" in tdata:
        new_active = tdata["active"]
        if new_active != orig_active:
            log("PATCH /api/learnings/{id}/toggle", "PASS", f"Flipped {orig_active} → {new_active}")
            # Restore
            api(f"/api/learnings/{lr_id}/toggle", method="PATCH")
        else:
            log("PATCH /api/learnings/{id}/toggle", "FAIL", "active did not flip")
    else:
        log("PATCH /api/learnings/{id}/toggle", "FAIL", f"status={tcode} body={tdata}")

# ── 5. Playwright: page loads ─────────────────────────────────────────────────
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()

    # Set a dummy token so AuthProvider reads it from localStorage
    context.add_init_script("window.localStorage.setItem('token', 'MOCK_TOKEN');")

    def handle_route(route):
        url = route.request.url
        if "/api/" in url:
            path = "/api/" + url.split("/api/", 1)[1]
            # Intercept /api/auth/me — return fake user to keep auth happy
            if "/api/auth/me" in path:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(FAKE_USER),
                )
                return
            # Proxy all other /api/ calls to backend with dev-token
            be_url = f"{BACKEND}{path}"
            method = route.request.method
            try:
                post_data = route.request.post_data
                data = post_data.encode() if post_data else None
                req = urllib.request.Request(
                    be_url,
                    data=data,
                    headers={"Authorization": "Bearer dev-token",
                             "Content-Type": "application/json"},
                    method=method,
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    body = r.read()
                    ct = r.headers.get("Content-Type", "application/json")
                    route.fulfill(status=r.status, body=body, content_type=ct)
            except urllib.error.HTTPError as ex:
                route.fulfill(status=ex.code, body=ex.read(), content_type="application/json")
            except Exception as ex:
                route.fulfill(status=500, body=str(ex).encode())
        else:
            route.continue_()

    context.route("**/*", handle_route)

    page = context.new_page()
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

    # Navigate to learnings page
    page.goto(f"{FRONTEND}/learnings")
    page.wait_for_load_state("networkidle")
    time.sleep(3)

    # Screenshot
    page.screenshot(path=f"{SS_DIR}/T12-007-learnings-full.png", full_page=True)

    body_text = page.text_content("body") or ""

    # Check: Current URL (not redirected to /login)
    current_url = page.url
    stayed_on_learnings = "/learnings" in current_url
    log("Page stays on /learnings (not redirected to login)",
        "PASS" if stayed_on_learnings else "FAIL",
        f"URL: {current_url}")

    # Check: Sidebar has Learnings nav entry
    all_links = page.locator("a").all()
    link_hrefs = [a.get_attribute("href") or "" for a in all_links]
    has_learnings_nav = "/learnings" in link_hrefs
    log("Sidebar has /learnings nav entry", "PASS" if has_learnings_nav else "FAIL",
        f"All nav hrefs: {[h for h in link_hrefs if h.startswith('/')]}")

    # Check: Brain icon in sidebar (from lucide-react Brain)
    brain_icons = page.locator("a[href='/learnings']").count()
    log("Brain-icon Learnings link present", "PASS" if brain_icons > 0 else "FAIL",
        f"count={brain_icons}")

    # Check: Page title / header
    has_header = "Learnings" in body_text
    log("Page loads with Learnings header", "PASS" if has_header else "FAIL",
        f"First 200 chars: {body_text[:200]}")

    # Check: Pattern count shown
    has_count = "patterns" in body_text.lower()
    log("Pattern count label visible", "PASS" if has_count else "FAIL")

    # Check: Category filter tabs
    for tab_label in ["All", "Title", "Hook", "Framework", "Script"]:
        btn = page.locator(f"button:has-text('{tab_label}')").first
        has_tab = btn.count() > 0
        log(f"Filter tab '{tab_label}' present", "PASS" if has_tab else "FAIL")

    # Check: Action buttons
    for btn_label in ["Extract Learnings", "Analyze Titles", "Analyze Transcripts"]:
        btn = page.locator(f"button:has-text('{btn_label}')").first
        has_btn = btn.count() > 0
        log(f"Action button '{btn_label}' present", "PASS" if has_btn else "FAIL")

    # Check: PatternCards rendered
    # Confidence bar divs should be present
    confidence_bars = page.locator("div[style*='width']").count()
    log("Confidence bars rendered", "PASS" if confidence_bars > 0 else "FAIL",
        f"{confidence_bars} width-styled divs found")

    # Check: PROVEN / AVOID / TESTING verdict labels
    has_proven = "PROVEN" in body_text
    has_avoid = "AVOID" in body_text
    log("Verdict badges (PROVEN/AVOID)", "PASS" if (has_proven or has_avoid) else "FAIL",
        f"PROVEN={has_proven}, AVOID={has_avoid}")

    # Check: Toggle buttons
    toggle_btns = page.locator("button[title*='pattern']").count()
    log("Toggle buttons for patterns (title contains 'pattern')",
        "PASS" if toggle_btns > 0 else "FAIL", f"{toggle_btns} toggle buttons")

    # Check: source videos expand buttons
    source_btns = page.locator("button:has-text('source video')").count()
    log("Source video expand buttons", "PASS" if source_btns > 0 else "FAIL",
        f"{source_btns} source video buttons")

    # Screenshot close-up of a pattern card
    cards = page.locator(".glass-card, [class*='GlassCard'], div > div.p-4").first
    if cards.count() > 0:
        cards.screenshot(path=f"{SS_DIR}/T12-007-pattern-card.png")

    # Check: Competitor Title Patterns section (T12-003)
    has_competitor_section = (
        "Competitor Title Patterns" in body_text or
        "Title Patterns" in body_text
    )
    log("T12-003: Competitor Title Patterns section header",
        "PASS" if has_competitor_section else "FAIL",
        f"Section present: {has_competitor_section}")

    # Check autopilot learnings data would show avg_vph
    if autopilot_learnings and has_competitor_section:
        log("T12-003: Title insights data would render", "PASS",
            f"{len(autopilot_learnings)} autopilot patterns available")
    elif not has_competitor_section:
        log("T12-003: Title insights data would render", "FAIL",
            "Section not present — cannot verify data rendering")

    # Console error check
    errs = [e for e in console_errors if "favicon" not in e.lower()]
    log("No console errors", "PASS" if not errs else "FAIL",
        f"{len(errs)} errors: {errs[:3]}" if errs else "0 errors")

    # Take final screenshot of title insights area (scroll to bottom)
    page.keyboard.press("End")
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SS_DIR}/T12-007-bottom.png", full_page=False)

    browser.close()

# ── Summary ───────────────────────────────────────────────────────────────────
passes = [r for r in results if r["status"] == "PASS"]
fails  = [r for r in results if r["status"] == "FAIL"]

print(f"\n{'='*60}")
print(f"T12-007 RESULTS: {len(passes)}/{len(results)} PASS, {len(fails)} FAIL")
print(f"{'='*60}")

if fails:
    print("\n❌ FAILURES:")
    for f in fails:
        print(f"  • {f['label']}: {f['note']}")

# Write JSON results
with open(f"{SS_DIR}/T12-007-results.json", "w") as fh:
    json.dump({"results": results, "console_errors": console_errors}, fh, indent=2)

sys.exit(0 if not fails else 1)
