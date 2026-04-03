# Pipeline Tester Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->

- Gen/Regen/Variants buttons in StoryboardVisualsTab are tiny (text-[9px]) inside overflow containers — Playwright standard click times out; use JS .click() or force=True.
- Approval/Reject buttons only appear in StoryboardVisualsTab when seg.status === 'done'; with all-pending assets, 0 buttons show (expected behavior, not a bug).
- Backend auth: all /api/* endpoints require 'Authorization: Bearer dev-token' header; without it returns 403.
- Tab name for images/storyboard is "Storyboard & Visuals" (not "Visuals" or "Images").
- page.on('console', ...) use msg.type and msg.text as properties (not methods) in newer Playwright.
- API calls from the frontend go to the public IP (76.13.119.181:8001) not localhost — filter on '/api/' in URL to catch both.
- Auth requires a real JWT for frontend; use sub='dev-user' (maps to dev account 00000000-...) with iss=storyengine, tenant_id from /api/auth/me with dev-token. Use browser.new_context(storage_state={"origins":[{"origin":"http://localhost:3002","localStorage":[{"name":"token","value":JWT}]}]}) — evaluate() after navigate fails because AuthProvider clears token on getMe() failure.
- Always proxy /api/** routes with route.fulfill() + Python urllib to bypass CORS (localhost:3002 not in backend CORS allowlist). Combine with storage_state for auth.
- storyboard_status values replace underscore with space in UI: 'grids_generated' shows as 'grids generated', search page_text with spaces not underscores.
- Supabase pooler gets circuit breaker after bad auth attempts — use direct DB URL (db.PROJECT.supabase.co:5432) not pooler (pooler.supabase.com) to avoid this.
- email/password register endpoint broken (FK violation memberships->users) — BUG-AUTH-001 filed (now FIXED in commit 4cc9dec).
- Autopilot ConfigUpdate model (autopilot.py) only accepts videos_per_month/videos_per_scrape — does NOT accept weights/thresholds. T13-002 backend bug filed.
- Autopilot page T13-001: 'Last cycle' text only shows when state.last_cycle is non-null; 'Next production: in N days' shows when days_until_next > 0. Both are correct null-handling behavior.
- Auth in Playwright: use context.add_init_script() to set localStorage token BEFORE page loads; storage_state JSON approach also works but add_init_script is more reliable for React apps that read localStorage on mount.
- update_visual_report.py: when TASK_ID arg is passed, it filters by TASK_ID prefix so use the screenshot filename prefix (e.g. 'reg5') not a task ID like 'T10-005'. Run without args to upload ALL new files.
- T17-005: Stripe endpoints return 'Stripe not configured' without STRIPE_SECRET_KEY — correct behavior, not a bug. Google OAuth returns 'Invalid Google token' without real client creds. Both are expected in dev.
- Ports 3001/3002 serve pre-built Next.js; if the build is stale (code committed after last build), test on a dev server (npm run dev -- --port 3003) to get the current code.
- Auth intercept pattern: context.add_init_script sets localStorage token + route handler intercepts /api/auth/me to return FAKE_USER dict — this reliably bypasses AuthProvider redirect without needing a valid JWT.
- AuthProvider skips getMe() when token==='dev-token' (stays null, redirects to login) — use window.fetch patch to fake /api/auth/me response in JS-only Playwright tests, or use a real JWT from POST /api/auth/register.
- T13-012 pre-validation: API proxy with real JWT on port 3003 is the reliable way to test React pages — localStorage.setItem in addInitScript + route.fulfill for all /api/** calls bypasses CORS and auth redirect.
- T8-003: RenderTab has render trigger + task poller + scene timeline but NO final_video_url display. Backend also missing final_video_url from VideoDetail model/SQL (in schema.sql line 117 but never returned). BUG-T8-FINAL-URL (backend) + BUG-T8-OUTPUT-DISPLAY (frontend) filed.
