# QA Blueprint

## Verification Commands
```bash
# TypeScript check
cd storyengine/frontend && npx tsc --noEmit

# Curl test pattern
curl -s http://localhost:8001/api/ENDPOINT | python3 -m json.tool

# Check router registered
grep "include_router" storyengine/backend/main.py | grep "ROUTE_NAME"

# Check model exists
grep "class MODEL_NAME" storyengine/backend/models.py

# Check API function exists
grep "FUNCTION_NAME" storyengine/frontend/src/lib/api.ts

# Check component uses API
grep "FUNCTION_NAME\|TYPE_NAME" storyengine/frontend/src/components/PATH/Component.tsx

# Build check
cd storyengine/frontend && npm run build
```

## Backend Verification Checklist
For a backend task:
1. Route file exists in `backend/routes/`
2. Router registered in `main.py` (`grep include_router`)
3. Pydantic model in `models.py` matches response shape
4. Curl returns correct shape (test with real or dev data)
5. DB columns exist (check `schema.sql` or run migration)

## Frontend Verification Checklist
For a frontend task:
1. TypeScript compiles (`npx tsc --noEmit`)
2. Type in `lib/types.ts` (or inline in `api.ts`) matches backend response
3. API function in `lib/api.ts` hits correct endpoint path
4. Component imports and uses the API function
5. Loading/error/empty states exist

## Full Wiring Check
1. Curl backend endpoint — note response field names
2. Check `lib/types.ts` has matching field names (exact case)
3. Check `lib/api.ts` calls correct endpoint path (including `/api/` prefix)
4. Check component renders each field from the API response
5. `npm run build` passes
6. No console errors (verify via Playwright or browser)

## Common Failure Modes
- **PipelineStatus enum mismatch** — frontend uses simplified names (`scripting`) but backend uses full status strings (`ready_for_scripting`). Always match backend exactly.
- **Case sensitivity** — backend writes `approved`/`rejected` (lowercase), some frontend filters expect `Pending` (capital). Standardize to lowercase.
- **Missing router registration** — route file exists in `routes/` but `app.include_router()` is missing from `main.py`. Always grep `main.py`.
- **Field name mismatch** — backend returns `scene_text`, frontend type says `narrationText`. Copy names from Pydantic model, never retype.
- **Stale React Query cache** — data updates but UI shows old values. Invalidate the correct query key after mutations.
- **Missing loading/error states** — component renders empty div while data loads. Always destructure `{ data, isLoading, error }` from useQuery.
- **POST body shape wrong** — frontend sends `{ title }` but Pydantic expects `{ video_title }`. Match Pydantic model field names exactly.
- **API path mismatch** — frontend calls `/api/videos/detail` but route is `/api/videos/{id}`. Curl first, then copy the exact path.

## Router Prefix Quick Reference
| Route file | Prefix |
|---|---|
| dashboard.py | `/api/dashboard` |
| videos.py | `/api/videos` |
| assets.py | `/api/assets` |
| activity.py | `/api/activity` |
| review.py | `/api/review` |
| pipeline.py | `/api/pipeline` |
| settings.py | `/api/settings` |
| autopilot.py | `/api/autopilot` |
| niche.py | `/api/niche` |
| discovery.py | `/api/discovery` |
| learning_extraction.py | `/api/learnings` |
| youtube_sync.py | `/api/youtube` |
| visual_styles.py | `/api/visual-styles` |
| projects.py | `/api/projects` |
| channel_profile.py | `/api/channel-profile` |
| agents.py | `/api/agents` |
| skills.py | `/api/skills` |

## Playwright Browser Testing (USE THIS)

The VPS has Playwright + Chromium installed. Use it to ACTUALLY CLICK THROUGH the live site. This is the most reliable way to verify frontend work.

**StoryEngine URLs:**
- Frontend: `http://localhost:3001`
- Backend API: `http://localhost:8001`

**How to run Playwright tests:**
```bash
# Navigate to a page and check it loads (no errors)
npx playwright test --browser chromium -c - << 'TESTEOF'
const { test, expect } = require('@playwright/test');
test('page loads', async ({ page }) => {
  await page.goto('http://localhost:3001/pipeline');
  await page.waitForLoadState('networkidle');
  // Check no error messages visible
  const errorText = await page.locator('text=error').count();
  console.log('Errors found:', errorText);
  // Take screenshot for evidence
  await page.screenshot({ path: '/tmp/qa-screenshot.png' });
});
TESTEOF
```

**Common Playwright checks to run:**
```bash
# Check a specific page loads data (not empty)
node -e "
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();

  // Navigate
  await page.goto('http://localhost:3001/PAGE_PATH');
  await page.waitForLoadState('networkidle');

  // Check for content (not empty/loading forever)
  const body = await page.textContent('body');
  const hasContent = body.length > 200;
  console.log('Page loaded:', hasContent ? 'YES' : 'NO (possibly empty)');

  // Check for console errors
  page.on('console', msg => {
    if (msg.type() === 'error') console.log('CONSOLE ERROR:', msg.text());
  });

  // Check specific elements exist
  const buttons = await page.locator('button').count();
  console.log('Buttons found:', buttons);

  // Screenshot as evidence
  await page.screenshot({ path: '/tmp/qa-PAGE_PATH.png', fullPage: true });

  await browser.close();
})();
"
```

**What to verify with Playwright for each tab:**
1. Page loads without console errors
2. Data appears (not just spinners/empty states)
3. Buttons are clickable (not disabled when they shouldn't be)
4. API calls complete (check network tab or console for fetch errors)
5. Take a screenshot as evidence

**Always take screenshots.** Save to `storyengine/agents/screenshots/TASKID-before.png` and `storyengine/agents/screenshots/TASKID-after.png`. These are served by the dashboard at `/api/screenshots/TASKID-before.png` so the operator can see exactly what you verified. Commit the screenshots with your other changes.

## Tab Completion Criteria
A tab is 100% complete when:
- All tasks for the tab have status `done` AND `verified: true`
- `npx tsc --noEmit` = 0 errors
- All endpoints return correct shapes (curl verified)
- All UI components render real data (not mock/hardcoded)
- Loading states show while fetching
- Error states handle failures gracefully
- No console errors in browser
- `npm run build` passes

## Verification Script Template
```bash
# Run this sequence for any tab before marking complete
cd storyengine/frontend && npx tsc --noEmit
echo "---"
curl -s http://localhost:8001/api/ENDPOINT | python3 -c "import sys,json; d=json.load(sys.stdin); print(list(d.keys()) if isinstance(d,dict) else f'{len(d)} items')"
echo "---"
cd storyengine/frontend && npm run build 2>&1 | tail -5
```
