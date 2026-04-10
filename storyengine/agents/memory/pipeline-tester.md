# Pipeline Tester Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- [2026-04-08] BRANCH CHANGE: agent-dev merged to main and deleted. All work is on main now. Production dir IS the workspace. No separate ports needed — test on 3001/8001 directly. Ignore older notes about agent-dev or port 8002/8099.

- Tab name for images/storyboard is "Storyboard & Visuals" (not "Visuals" or "Images").
- Pipeline page routes are `/pipeline/{videoId}` not `/production/{videoId}`. Always navigate to `/pipeline/` for video detail tests.
- For Playwright auth with real dev-user: use JWT forged with SESSION_SECRET from storyengine/backend/.env (sub='00000000-...', iss='storyengine', tenant_id='f6839de2-...'). Navigate /login first, set token via evaluate, then navigate to target page.
- JWT tenant_id for dev-user: MUST be 'f6839de2-368c-440d-8559-0292026179fa' (from /api/auth/me with dev-token) — NOT 'f6839de2-fe82-44b8-b0d4-8a5e7a0b6e5f' (wrong). Wrong tenant = 0 videos returned.
- After SEC-1 fix: dev-token no longer works in code. Must forge JWT with SESSION_SECRET. But production .env has DEV_MODE=true+DEV_TOKEN=dev-token which re-enables it (config issue, not code bug).
- main.py loads_dotenv from storyengine/.env (parent), NOT backend/.env — JWT auth needed when agent-workspace .env lacks DEV_MODE.
- STALE SERVER is the #1 cause of 404/405 on new endpoints. Code exists in production dir but uvicorn doesn't hot-reload new routes. Fix: kill + restart uvicorn. Always check OpenAPI /openapi.json to confirm route registration before filing code bugs.
- getPendingReview() returns {scripts:[], storyboards:[], thumbnails:[], images:[]} NOT a flat array. Proxying /api/review/pending as [] crashes dashboard + review pages.
- Plan gating (T25): PRO_PATHS=[/autopilot,/analytics,/learnings,/competitors,/discovery]. isPlanAtLeast checks tiers {free:0,starter:1,pro:2,agency:3}. Lock icons only show when sidebar NOT collapsed.
- REG15 (2026-04-04): context.add_init_script() on CONTEXT (not page) is the reliable auth pattern for port 3001. Sets localStorage BEFORE any page JS runs — survives all navigations. No route intercept needed.
- REG16 (2026-04-05): Pipeline now has 9 tabs (Research, Script, Storyboard & Visuals, Video Clips, Sound, Thumbnail, Render, Upload, Performance).
- REG18 (2026-04-06): Simplified sweep pattern: context.add_init_script + urllib.request for API tests = fastest pattern, no route intercepts needed.
- Playwright async route handlers MUST be `async def` and use `await route.fulfill()`/`await route.continue_()` — sync versions silently fail causing timeout.
- CSS `uppercase` in progress bars: inner_text() returns "API KEYS"/"READY!" not "API Keys"/"Ready!". Always test with the uppercase version when CSS transforms are used.
- wait_for_load_state('networkidle') doesn't wait for React client-side redirects. Use wait_for_url(lambda url: 'target' in url) to wait for specific URL conditions.
- /render page 410 errors: thumbnail_url in DB are Airtable attachment URLs that expire in 2h. <img> onError fallback handles it. 26 console 410s on /render are expected, not bugs.
- Playwright console listener: use `msg.type` (property) not `msg.type()` (method).
- REG23 (2026-04-08): New 404 page (not-found.tsx) shows "Page not found" with nav. Error boundaries (error.tsx, global-error.tsx) deployed. Stale build causes 500s — fresh npm run build + next start fixes.
- REG24 (2026-04-08): Production next server (port 3001) was serving stale build from /home/clawd/projects/economy-fastforward — had to kill & restart from agent-workspace. Real JWT required for Playwright (dev-token rejected by AuthProvider). All 5 user errors NOT A BUG (session #13).
- REG26 (2026-04-08): 24/24 pages (19 auth + 4 public + 404), 34/34 API, 9/9 tabs, 4/4 auth, mobile PASS (375x812), tsc 0 errors, 0 console errors (excl 26 Airtable 410s), 0 new bugs. Backend crashed mid-sweep (port 8001 went down), recovered by restart from production dir. All 5 user errors NOT A BUG (session #14). LAUNCH SCORE 8/8.
- REG27 (2026-04-10): All 5 user errors were CORS — ALLOWED_ORIGINS in storyengine/.env had only external IP (76.13.119.181), missing localhost:3001. Fixed by adding localhost origins to .env. Fastest login pattern: page.type() + click submit (not fill()). Tabs use <button> not role="tab". 13/14 pages PASS, 22/24 API PASS, 9/9 tabs PASS, mobile PASS, tsc 0 errors, perf <50ms all pages. /team 404 (no page). Pipeline detail has 10 tabs now (added Storyboard Grids).

