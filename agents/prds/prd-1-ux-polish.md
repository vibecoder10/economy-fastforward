# PRD 1: UX Polish — Empty States, Dashboard, Create Flow

**Priority:** HIGH — new users sign up, see blank pages, and bounce
**Target:** Make every page useful on day 1, even with zero data

---

## Context

StoryEngine has 24 pages, all wired with real API integration. Auth, billing, plan enforcement, trial logic, toast notifications, and error boundaries all exist. But a new user who signs up and enters the app sees blank white-on-black cards with no data and no guidance. This PRD fixes that first-time experience.

### What EXISTS (do NOT rebuild):
- Toast system: `storyengine/frontend/src/components/ui/toast.tsx` (useToast hook with success/error/warning/info)
- Error boundaries: `storyengine/frontend/src/app/error.tsx`, `global-error.tsx`, `not-found.tsx`
- Design system components: `GlassCard`, `StatCard`, `StatusPill`, `ActionButton`, `Spinner`, `Modal`, `FilterSelect`
- Billing/usage: `GET /api/billing/usage` returns `{ limits: { videos_per_month, render_minutes, concurrent_jobs }, usage: { videos_created, api_calls, render_minutes, storage_bytes } }`
- Plan enforcement: `check_plan_limits()` and `increment_usage()` in `storyengine/backend/routes/billing.py`
- Resend email integration: already used for password reset in `storyengine/backend/routes/google_auth.py` lines 375-404
- Dashboard: `storyengine/frontend/src/app/page.tsx` (530+ lines, has LandingPage for unauth + Dashboard for auth)
- Pipeline page: `storyengine/frontend/src/app/pipeline/page.tsx` (has video cards, create modal, discovery ideas)

### Design System (MANDATORY for all UI work):
- Background: `var(--bg-void)` (#0A0A0B), cards: `glass-card` class
- Primary accent: `var(--turquoise)` (#00D4AA), secondary: `var(--orange)`, gold: `var(--gold)`
- Text: `var(--text-primary)`, `var(--text-secondary)`, `var(--text-tertiary)`
- Red for errors: `var(--red)`
- Font: `font-display` for headings
- Use existing components: `GlassCard`, `ActionButton`, `StatusPill`, `Spinner`
- Motion: Framer Motion with `container`/`item` stagger pattern used on every page

---

## T1: Fix render_minutes usage increment

**Role:** backend-dev
**Priority:** CRITICAL — plan enforcement for render is broken without this

**Problem:** When a video renders successfully, `render_minutes` is never incremented in `tenant_usage`. The `check_plan_limits(tenant_id, "render")` check exists and reads `render_minutes`, but nothing writes to it after render completes. Users on free/starter plans can render unlimited videos.

**Implementation:**
1. In `storyengine/backend/pipeline_executor.py`, in the `run_render()` method (line ~1897), after the render succeeds and before returning:
   - Import `increment_usage` from `routes.billing`
   - Calculate render duration in minutes from the result or from video metadata (the video's `video_length_minutes` column, or fallback to a default of 10 minutes)
   - Call `await increment_usage(self.tenant_id, "render_minutes", duration_minutes)`
2. The `increment_usage` function already exists at `storyengine/backend/routes/billing.py:339` and accepts `(tenant_id, field, amount)` where amount can be an int.

**Files to modify:**
- `storyengine/backend/pipeline_executor.py` — `run_render()` method, ~line 1929 (after `_log_activity` "completed" call)

**Acceptance criteria:**
- [ ] After a successful render, `tenant_usage.render_minutes` is incremented by the video's duration
- [ ] If video duration is unknown, defaults to 10 minutes
- [ ] Failed renders do NOT increment usage
- [ ] `GET /api/billing/usage` reflects the updated render_minutes after render completes

---

## T2: Empty state component + wiring for 8 pages

**Role:** frontend-dev
**Priority:** HIGH — every blank page is a bounce risk

**Problem:** When a new user has zero videos, zero competitors, zero learnings, most pages render empty card grids with no content. There's no guidance on what to do next.

**Implementation:**

Create a reusable `EmptyState` component, then wire it into 8 pages.

### 2a: Create EmptyState component

**File:** `storyengine/frontend/src/components/ui/EmptyState.tsx` (NEW)

```tsx
interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
}
```

Design: centered layout inside a `GlassCard` with dashed border. Icon in a circular tinted container (turquoise bg at 10% opacity). Title in `text-primary`, description in `text-secondary`, CTA as an `ActionButton`. Use the existing Framer Motion `item` variant for entrance animation.

### 2b: Wire empty states into pages

Each page should check if its primary data array is empty (after loading completes) and render `EmptyState` instead of the empty grid.

| Page | File | Condition | Icon | Title | Description | CTA |
|------|------|-----------|------|-------|-------------|-----|
| Dashboard | `src/app/page.tsx` (Dashboard component) | `videos?.length === 0` | `Film` | "Create your first video" | "Paste a YouTube URL or describe a topic to start your first AI-produced video." | "Create Video" → `/pipeline` |
| Pipeline | `src/app/pipeline/page.tsx` | `videos?.length === 0` | `Sparkles` | "No videos in production" | "Start your first video to see it move through the pipeline stages." | "Create Video" → open create modal |
| Competitors | `src/app/competitors/page.tsx` | no niche channels loaded | `TrendingUp` | "Add your first competitor channel" | "Track competitor YouTube channels to discover winning video ideas and title patterns." | "Set Up Niche" → trigger niche setup |
| Analytics | `src/app/analytics/page.tsx` | `videos?.length === 0` or no videos with CTR data | `BarChart3` | "No analytics yet" | "Publish a video to YouTube and sync metrics to see CTR, retention, and performance data." | "Go to Pipeline" → `/pipeline` |
| Learnings | `src/app/learnings/page.tsx` | no learnings returned | `Brain` | "AI learnings appear after performance" | "After your videos get impressions on YouTube, the AI extracts patterns about what works for your audience." | "View Analytics" → `/analytics` |
| Discovery | `src/app/discovery/page.tsx` | no discovery ideas | `Sparkles` | "Discover winning video ideas" | "Set up competitor channels first, then discovery will surface high-VPH ideas from your niche." | "Set Up Competitors" → `/competitors` |
| Calendar | `src/app/calendar/page.tsx` | no videos with dates | `Calendar` | "Your production calendar" | "Videos will appear here as they move through the pipeline with scheduled dates." | "Create Video" → `/pipeline` |
| Review | `src/app/review/page.tsx` | nothing pending | `CheckCircle` | "Nothing to review" | "When pipeline stages need your approval (scripts, thumbnails, storyboards), they'll appear here." | "Go to Pipeline" → `/pipeline` |

**Files to modify:**
- `storyengine/frontend/src/components/ui/EmptyState.tsx` (NEW)
- `storyengine/frontend/src/app/page.tsx` — Dashboard component
- `storyengine/frontend/src/app/pipeline/page.tsx`
- `storyengine/frontend/src/app/competitors/page.tsx`
- `storyengine/frontend/src/app/analytics/page.tsx`
- `storyengine/frontend/src/app/learnings/page.tsx`
- `storyengine/frontend/src/app/discovery/page.tsx`
- `storyengine/frontend/src/app/calendar/page.tsx`
- `storyengine/frontend/src/app/review/page.tsx`

**Acceptance criteria:**
- [ ] New `EmptyState` component renders correctly with all props
- [ ] Each of the 8 pages shows the empty state when data is absent (not during loading — show Spinner during loading)
- [ ] CTA buttons navigate to the correct destination or trigger the correct action
- [ ] Empty states use the design system (GlassCard, turquoise accent, font-display headings)
- [ ] `npx tsc --noEmit` passes with zero errors

---

## T3: Dashboard — add usage meter and quick actions

**Role:** frontend-dev
**Priority:** HIGH — dashboard should answer "what should I do next?"

**Problem:** The current dashboard shows stat cards (videos this month, in production, avg cost, avg CTR) but doesn't show plan usage or give clear next-step guidance for new users.

**Implementation:**
1. Add a **usage meter row** below the stat cards. Fetch from `GET /api/billing/usage` (use `getUsage` from api.ts — already exists at `storyengine/frontend/src/lib/api.ts`). Show two progress bars:
   - "Videos: X / Y this month" (videos_created / videos_per_month)
   - "Render: X / Y minutes" (render_minutes / render_minutes limit)
   - Style: horizontal bar inside a GlassCard, turquoise fill, orange when >80%, red when >95%
2. Add a **quick actions section** when there are pending reviews: "You have N items to review" with a link to `/review`.
3. The existing empty state from T2 handles the zero-videos case. This task adds the usage meter for users who DO have data.

**Files to modify:**
- `storyengine/frontend/src/app/page.tsx` — Dashboard component (add usage meter section after stat cards, ~line 514)
- `storyengine/frontend/src/lib/api.ts` — verify `getUsage` function exists; if not, add it

**Acceptance criteria:**
- [ ] Usage meter shows videos_created / videos_per_month with a progress bar
- [ ] Usage meter shows render_minutes / render_minutes limit with a progress bar
- [ ] Bar color changes at 80% (orange) and 95% (red) thresholds
- [ ] Pending review banner shows when `pendingCount > 0` (data already fetched on dashboard)
- [ ] Usage meter gracefully handles billing API errors (show nothing, don't crash)
- [ ] `npx tsc --noEmit` passes

---

## T4: Create video — simplified topic input

**Role:** frontend-dev
**Priority:** HIGH — current create flow requires too much knowledge

**Problem:** The pipeline page has a create modal, but it requires the user to know about visual styles, accent colors, and writer guidance. New users just want to type a topic and go.

**Implementation:**
1. In the pipeline page's create modal (or a new `/create` route), add a **simplified input** at the top:
   - Single text input: "Paste a YouTube URL or describe your video topic"
   - Large, prominent, with a turquoise "Create Video" submit button
   - On submit: call `POST /api/videos` (existing `createVideo` in api.ts) with the topic as `title` and sensible defaults for everything else
2. Below the simple input, add an **expandable "Advanced Options"** section (collapsed by default) with:
   - Visual style dropdown (cinematic_illustration, holographic_hud, cinematic_dossier, clay_mannequin)
   - Accent color dropdown (cold teal, muted crimson, warm amber, muted green)
   - Video length input (minutes, default 8)
   - Writer guidance textarea
3. After creation succeeds, navigate to `/dashboard/{videoId}` (the video detail page) and show a success toast.

**Files to modify:**
- `storyengine/frontend/src/app/pipeline/page.tsx` — simplify the existing create modal or replace with a new flow
- Alternatively create `storyengine/frontend/src/components/production/CreateVideoFlow.tsx` (NEW) and import into pipeline page

**Acceptance criteria:**
- [ ] User can create a video by typing a topic and pressing Enter or clicking Create
- [ ] Advanced options are hidden by default, expandable via chevron/toggle
- [ ] After creation, user is navigated to the video detail page
- [ ] Success toast appears: "Video created! Starting pipeline..."
- [ ] If creation fails (plan limit, API error), error toast appears with actionable message
- [ ] `npx tsc --noEmit` passes

---

## T5: Suggest titles endpoint (backend)

**Role:** backend-dev
**Priority:** MEDIUM — enhances T4 create flow

**Problem:** The simplified create flow (T4) would be even better if users could get AI-generated title suggestions before committing. This endpoint supports a future enhancement where the user types a topic and sees 3 title options.

**Implementation:**
1. Add `POST /api/videos/suggest-titles` endpoint to `storyengine/backend/routes/videos.py`
2. Request body: `{ "topic": string }`
3. Response: `{ "titles": string[], "topic": string }`
4. Use Claude API (Anthropic client) to generate 3 compelling YouTube titles for the topic
5. Prompt should reference the channel's niche/style if available (read from `channel_profiles` table)
6. Rate limit: count as 1 API call via `increment_usage(tenant_id, "api_calls")`

```python
class SuggestTitlesRequest(BaseModel):
    topic: str

class SuggestTitlesResponse(BaseModel):
    titles: list[str]
    topic: str

@router.post("/suggest-titles", response_model=SuggestTitlesResponse)
async def suggest_titles(
    body: SuggestTitlesRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    # Use Anthropic client to generate 3 titles
    # Return as list of strings
    ...
```

**Files to modify:**
- `storyengine/backend/routes/videos.py` — add endpoint
- `storyengine/backend/models.py` — add Pydantic models if not using inline

**Acceptance criteria:**
- [ ] `POST /api/videos/suggest-titles` with `{"topic": "China economy collapse"}` returns 3 titles
- [ ] Titles are compelling YouTube-style (not generic)
- [ ] Returns 401 if not authenticated
- [ ] Returns error gracefully if Anthropic API key not configured
- [ ] Increments `api_calls` usage
- [ ] Endpoint responds in < 10 seconds

---

## T6: Welcome email on signup

**Role:** backend-dev
**Priority:** MEDIUM — improves first impression, reuses existing Resend integration

**Problem:** Users sign up and get no email. No confirmation, no onboarding guidance, no reminder of the trial.

**Implementation:**
1. In `storyengine/backend/routes/google_auth.py`, add a `_send_welcome_email(email, name)` function (pattern matches existing `_send_reset_email` at line 375)
2. Call it after successful registration in both:
   - `register()` endpoint (email/password signup, ~line 149) — after account + tenant + membership creation succeeds
   - `google_auth()` endpoint (Google OAuth) — after new account creation succeeds (the `if not account:` branch)
3. Email content:
   - Subject: "Welcome to StoryEngine — your 14-day Pro trial starts now"
   - Body: Welcome message, what they can do (create first video, set up competitors, explore pipeline), link to dashboard, trial countdown reminder
4. Use Resend API (same pattern as `_send_reset_email`). Non-blocking — wrap in try/except, log failures but don't break signup.
5. Ensure `EMAIL_FROM` is in `.env.example` if not already.

**Files to modify:**
- `storyengine/backend/routes/google_auth.py` — add `_send_welcome_email()`, call after registration in both auth paths
- `storyengine/.env.example` — add `EMAIL_FROM` if missing

**Acceptance criteria:**
- [ ] Email signup triggers welcome email
- [ ] Google OAuth signup triggers welcome email
- [ ] Email includes trial info and link to dashboard
- [ ] Email failure does NOT block signup (non-blocking, logged only)
- [ ] Dev mode (no RESEND_API_KEY) logs to console instead of sending
- [ ] No duplicate emails if user logs in again (only on FIRST registration)

---

## T7: Pipeline stage error surfacing

**Role:** frontend-dev
**Priority:** MEDIUM — users see failures as silent stalls

**Problem:** When a pipeline stage fails, the stage-advancer component shows a generic error or nothing at all. The user doesn't know what went wrong or how to fix it.

**Implementation:**
1. In `storyengine/frontend/src/components/video-detail/stage-advancer.tsx`:
   - The `friendlyError()` function (line 10) already parses some error types. Extend it to handle more cases:
     - API key missing: "API key not configured. Go to Settings to add your [service] key."
     - Timeout: "Stage timed out. This can happen with long videos. Try again."
     - Rate limit: "API rate limit hit. Wait a few minutes and retry."
   - When the stage fails (error state), show a red-bordered GlassCard with:
     - Error icon (XCircle from lucide)
     - The friendly error message
     - A "Retry" button that re-runs the stage
     - A "Skip Stage" link for non-critical stages
2. Also fire a toast notification on failure using the existing `useToast` hook:
   - `toast.error("Script generation failed: [reason]")`

**Files to modify:**
- `storyengine/frontend/src/components/video-detail/stage-advancer.tsx` — extend error handling, add toast on failure
- May need to import `useToast` from `@/components/ui/toast`

**Acceptance criteria:**
- [ ] Stage failures show a visible red error card with the error message
- [ ] Error message is human-readable (not raw JSON or stack traces)
- [ ] Toast notification fires on stage failure
- [ ] "Retry" button re-triggers the failed stage
- [ ] Missing API key errors point user to Settings page
- [ ] `npx tsc --noEmit` passes

---

## T8: Loading states audit

**Role:** frontend-dev
**Priority:** MEDIUM — loading states should feel intentional, not broken

**Problem:** Some pages show a blank screen while data loads (no spinner), or show partial content with undefined values flickering.

**Implementation:**
Audit and fix loading states on the 8 pages from T2 plus the dashboard:
1. Every page should show `<Spinner size="lg" />` centered in the page while the primary query is loading (`isLoading === true`)
2. The spinner should appear BEFORE any content renders (no partial content with `undefined` values)
3. After loading completes, if data is empty → show EmptyState (T2). If data exists → show normal content.
4. Error state: if the query fails, show a simple error card with "Failed to load [page]. Try refreshing." and a Retry button.

Pattern for every page:
```tsx
if (isLoading) return <div className="flex items-center justify-center h-64"><Spinner size="lg" /></div>;
if (error) return <ErrorCard message="Failed to load data" onRetry={refetch} />;
if (!data?.length) return <EmptyState ... />;
return <NormalContent />;
```

**Files to modify:**
- `storyengine/frontend/src/app/page.tsx` (Dashboard — already has spinner, verify)
- `storyengine/frontend/src/app/pipeline/page.tsx`
- `storyengine/frontend/src/app/competitors/page.tsx`
- `storyengine/frontend/src/app/analytics/page.tsx`
- `storyengine/frontend/src/app/learnings/page.tsx`
- `storyengine/frontend/src/app/discovery/page.tsx`
- `storyengine/frontend/src/app/calendar/page.tsx`
- `storyengine/frontend/src/app/review/page.tsx`
- Optionally create `storyengine/frontend/src/components/ui/ErrorCard.tsx` (NEW) if a reusable error component doesn't exist

**Acceptance criteria:**
- [ ] All 8 pages + dashboard show a centered spinner during initial load
- [ ] No page shows undefined/null values during loading
- [ ] All 8 pages show an error card if the API call fails
- [ ] Error card has a "Retry" button that refetches data
- [ ] Transition from loading → empty state or loading → content is smooth (no flash)
- [ ] `npx tsc --noEmit` passes

---

## T9: TypeScript build verification

**Role:** qa-engineer
**Priority:** CRITICAL — must pass before merge

**Description:** After all frontend tasks (T2, T3, T4, T7, T8) are complete, verify the build.

**Steps:**
1. Run `cd storyengine/frontend && npx tsc --noEmit` — must produce 0 errors
2. Run `cd storyengine/frontend && npm run build` — must succeed (no build errors)
3. Verify no unused imports were added
4. Verify all new components use the design system (check for hardcoded hex colors — should use CSS variables)

**Files to check:**
- All files modified in T2, T3, T4, T7, T8
- `storyengine/frontend/src/components/ui/EmptyState.tsx`
- `storyengine/frontend/src/components/ui/ErrorCard.tsx` (if created)

**Acceptance criteria:**
- [ ] `npx tsc --noEmit` — 0 errors
- [ ] `npm run build` — succeeds
- [ ] No hardcoded colors (all use CSS variables via `var(--...)`)
- [ ] No unused imports
- [ ] All new components have proper TypeScript types (no `any`)

---

## T10: End-to-end QA — new user flow

**Role:** qa-engineer
**Priority:** CRITICAL — validates the full PRD

**Description:** Test the complete new-user experience from signup through first video creation. Use Playwright (webapp-testing skill) against the running app.

**Test Script:**
1. Start backend: `cd storyengine/backend && python -m uvicorn main:app --reload --port 8001`
2. Start frontend: `cd storyengine/frontend && npm run dev`
3. Navigate to `/` — should see landing page (unauthenticated)
4. Navigate to `/login` — sign up with a new email
5. After signup: verify welcome email would be sent (check console logs in dev mode for `[DEV] Welcome email`)
6. Redirected to onboarding → complete it
7. Navigate to `/` (dashboard) — should show EmptyState "Create your first video"
8. Navigate to `/pipeline` — should show EmptyState with create CTA
9. Navigate to `/competitors` — should show EmptyState with niche setup CTA
10. Navigate to `/analytics` — should show EmptyState
11. Navigate to `/learnings` — should show EmptyState
12. Navigate to `/discovery` — should show EmptyState pointing to competitors
13. Navigate to `/calendar` — should show EmptyState
14. Navigate to `/review` — should show EmptyState "Nothing to review"
15. Go back to `/pipeline` → click "Create Video" → type a topic → submit
16. Verify video is created and user is navigated to video detail page
17. Verify success toast appears
18. Go to dashboard → verify usage meter shows "1 / N videos"
19. Check for console errors on every page — should be 0

**Files:** No files to modify — this is verification only.

**Acceptance criteria:**
- [ ] All 8 empty states render correctly with correct text and CTAs
- [ ] Create video flow works end-to-end
- [ ] Dashboard usage meter reflects video creation
- [ ] No console errors on any page
- [ ] No visual regressions (pages that had content still work)
- [ ] Toast notifications fire on video creation success
- [ ] Loading spinners appear on all pages during data fetch

---

## Dependency Graph

```
T1 (render_minutes fix)           — independent, do first
T5 (suggest-titles endpoint)      — independent, do anytime
T6 (welcome email)                — independent, do anytime

T2 (empty states)                 — do before T8
T3 (dashboard usage meter)        — do after T2 (uses EmptyState for zero case)
T4 (create video simplification)  — do after T5 if using suggest-titles, else independent
T7 (error surfacing)              — independent
T8 (loading states audit)         — do after T2 (uses EmptyState and ErrorCard)

T9 (TypeScript build)             — do after T2, T3, T4, T7, T8
T10 (E2E QA)                     — do after ALL tasks
```

## Agent Assignment

| Task | Agent | Est. Effort |
|------|-------|-------------|
| T1 | backend-dev | 15 min |
| T2 | frontend-dev | 45 min |
| T3 | frontend-dev | 20 min |
| T4 | frontend-dev | 30 min |
| T5 | backend-dev | 20 min |
| T6 | backend-dev | 15 min |
| T7 | frontend-dev | 20 min |
| T8 | frontend-dev | 25 min |
| T9 | qa-engineer | 10 min |
| T10 | qa-engineer | 30 min |

**Parallel lanes:**
- Lane 1 (backend-dev): T1 → T5 → T6
- Lane 2 (frontend-dev): T2 → T3 → T4 → T7 → T8
- Lane 3 (qa-engineer): wait for lanes 1+2 → T9 → T10
