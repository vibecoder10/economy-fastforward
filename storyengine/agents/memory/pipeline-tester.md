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
