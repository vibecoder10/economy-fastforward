# PRD 2: Pipeline UX — Real-time Progress, Landing Page, Notifications

**Date:** 2026-04-08
**Status:** Ready for Decomposition
**Priority:** HIGH — User-facing UX improvements that directly impact first-time experience and daily workflow
**Stack:** Next.js 16, React 19, TailwindCSS 4, Framer Motion, FastAPI, Supabase PostgreSQL

---

## Context

StoryEngine's pipeline page works but feels static. Videos move through 13 stages, but users have no real-time feedback — they must manually refresh to see progress. The SSE endpoint exists but the frontend doesn't consume it. The landing page exists at `/` but needs a significant upgrade with social proof, demo video, and pricing embed. Settings lacks key validation UX, and notifications are limited to basic toasts without pipeline event integration.

### What Already Exists

- **SSE endpoint** at `GET /api/activity/stream` in `storyengine/backend/routes/activity.py:99` — polls `bot_activity` table every 5 seconds, emits JSON entries with `bot_name`, `video_id`, `status`, `message`
- **`stage_transitions` table** — tracks `video_id`, `from_status`, `to_status`, `triggered_by`, `cost`, `duration_seconds`, `error_message`, `created_at` with tenant isolation
- **Pipeline page** at `/pipeline` with video cards, status dots, and drag-and-drop ordering
- **Video detail page** at `/pipeline/[videoId]` with 9 tabs, `ProgressStepper` component, and `useTaskPoller` hook for background polling
- **Landing page** at `/` (root `page.tsx`) — hero, pipeline steps, value props, CTA. Renders for unauthenticated users via `AuthenticatedShell` check
- **Toast system** at `storyengine/frontend/src/components/ui/toast.tsx` — `useToast()` with `success`, `error`, `warning`, `info` methods, Framer Motion animations
- **Billing webhook** at `POST /api/billing/webhook` handles `checkout.session.completed` event
- **Resend email integration** in `storyengine/backend/routes/google_auth.py` (password reset emails)
- **Trial tracking** — `trial_ends_at` column on `accounts` table, 14-day trial set on signup
- **Design tokens** — dark theme, charcoal `#0A0A0B`, teal `var(--turquoise)`, amber `var(--orange)`, gold `var(--gold)`, font Outfit

---

## Task 1: Real-time Pipeline SSE Stream (Backend + Frontend)

**Role:** backend-dev, frontend-dev
**Priority:** HIGH

### Description

Enhance the SSE endpoint to also emit `stage_transitions` data (not just `bot_activity`), and build a frontend hook that consumes the stream for live pipeline updates.

### Backend Changes (`storyengine/backend/routes/activity.py`)

1. Modify `activity_stream()` to query BOTH `bot_activity` AND `stage_transitions` tables
2. Emit two event types via SSE: `event: activity` (existing bot_activity data) and `event: stage_change` (stage transition data)
3. The `stage_change` event payload should include: `video_id`, `video_title`, `from_status`, `to_status`, `triggered_by`, `created_at`
4. Track `last_transition_id` separately from `last_activity_id` to avoid missing events
5. Use SSE event types so the frontend can distinguish: `event: activity\ndata: {...}\n\n` and `event: stage_change\ndata: {...}\n\n`

### Frontend Changes

1. Create `storyengine/frontend/src/hooks/use-pipeline-sse.ts`
2. The hook should:
   - Connect to `/api/activity/stream` using `EventSource`
   - Parse both `activity` and `stage_change` event types
   - Expose: `{ stageChanges, activities, isConnected }` — arrays of recent events
   - Auto-reconnect on disconnect (exponential backoff: 1s, 2s, 4s, max 30s)
   - Include the JWT token via query param (EventSource doesn't support headers): `/api/activity/stream?token=...`
   - Clean up EventSource on unmount
3. Update backend to accept `token` query param as auth fallback for SSE connections (EventSource limitation)

### Files to Modify

- `storyengine/backend/routes/activity.py` — enhance SSE endpoint
- `storyengine/backend/auth.py` — add query param token fallback for SSE
- `storyengine/frontend/src/hooks/use-pipeline-sse.ts` — NEW file

### Acceptance Criteria

- [ ] SSE endpoint emits both `activity` and `stage_change` event types
- [ ] `usePipelineSSE` hook connects and receives events
- [ ] Hook auto-reconnects on disconnect
- [ ] Hook cleans up EventSource on component unmount
- [ ] Auth works via query param token for EventSource
- [ ] TypeScript compiles: `cd storyengine/frontend && npx tsc --noEmit`

---

## Task 2: Pipeline Progress Visualization (Frontend)

**Role:** frontend-dev
**Priority:** HIGH

### Description

Add a visual stage stepper to the video detail page showing all 13 pipeline stages as connected nodes. Current stage glows, completed stages show checkmarks, future stages are dimmed. Wire to the SSE hook from Task 1 for live updates.

### Implementation

1. Replace the existing `ProgressStepper` usage on the video detail page with a new pipeline-specific stepper
2. Create `storyengine/frontend/src/components/production/PipelineStepper.tsx`
3. 13 stages displayed horizontally with connecting lines:
   - `research` → `script` → `split` → `voice` → `image_prompts` → `storyboard` → `images` → `video_scripts` → `video_gen` → `sound` → `thumbnail` → `render` → `upload`
4. Visual states:
   - **Completed:** Teal fill (`var(--turquoise)`) with checkmark icon
   - **Current:** Pulsing amber border (`var(--orange)`) with stage label below, shows elapsed time or "In progress..."
   - **Future:** Dimmed (`var(--text-tertiary)`) with step number
   - **Error:** Red border with X icon (if `stage_transitions` has `error_message`)
5. Connecting lines between stages: solid teal for completed, dashed gray for future
6. Responsive: horizontal scroll on mobile, all visible on desktop (compact labels)
7. Consume `usePipelineSSE` to show live status message under the current stage (e.g., "Generating Script... Scene 2/6")
8. Also update the pipeline list page (`/pipeline`) to show live status changes on video cards — invalidate React Query cache when a `stage_change` SSE event arrives for a video

### Files to Modify

- `storyengine/frontend/src/components/production/PipelineStepper.tsx` — NEW file
- `storyengine/frontend/src/app/pipeline/[videoId]/page.tsx` — wire new stepper + SSE hook
- `storyengine/frontend/src/app/pipeline/page.tsx` — wire SSE for live card updates

### Acceptance Criteria

- [ ] 13-stage stepper renders at top of video detail page
- [ ] Completed stages show teal with checkmarks
- [ ] Current stage pulses amber with elapsed time or live message
- [ ] Future stages are dimmed gray
- [ ] Error states show red with X icon
- [ ] Pipeline list page cards update live when a stage change arrives
- [ ] Responsive: horizontally scrollable on mobile
- [ ] Framer Motion entrance animation on page load

---

## Task 3: Landing Page Upgrade (Frontend)

**Role:** frontend-dev
**Priority:** HIGH

### Description

The landing page at `/` exists but needs to be more compelling for potential users. Upgrade it with social proof, a demo video section, testimonials, a "How it works" flow, and an embedded pricing section. This is the first thing potential users see — it must be visually impressive.

### Implementation

Modify the existing `LandingPage` component in `storyengine/frontend/src/app/page.tsx`. Do NOT create a separate route — the existing auth-gated pattern already shows `LandingPage` for unauthenticated users and `Dashboard` for authenticated users.

### New Sections (in order)

1. **Hero (upgrade existing)**
   - Add a demo video placeholder (styled 16:9 frame with play button overlay, gradient border)
   - Add social proof line: "Trusted by 200+ YouTube creators" with subtle avatar stack (placeholder images or initials)
   - Existing headline "Topic in. Video out." is good — keep it

2. **How It Works (new)**
   - 3-step horizontal flow with numbered circles and connecting lines
   - Step 1: "Paste a topic or URL" (icon: Clipboard)
   - Step 2: "AI produces your video" (icon: Sparkles) — show mini pipeline visualization
   - Step 3: "Review and publish" (icon: Upload)
   - Each step has a short description and subtle animation on scroll

3. **Feature Showcase (upgrade existing)**
   - Upgrade the 4 value props to 6 features with richer cards:
     - AI Research, Smart Scripts, Voice Synthesis, Cinematic Visuals, Learning Engine, One-Click Render
   - Each card: icon, title, 2-line description, subtle hover effect (border glow)

4. **Stats Bar (new)**
   - Horizontal bar with 3-4 stats: "13 pipeline stages", "4 visual styles", "6-act narrative structure", "48h performance tracking"
   - Animated count-up on scroll into view

5. **Pricing Embed (new)**
   - Import and render the pricing tiers from `/pricing` page (or duplicate the minimal version)
   - 3 tiers: Starter ($49), Creator ($149), Studio ($399)
   - Highlight Creator as "Most Popular"
   - CTA buttons link to `/login`

6. **CTA (upgrade existing)**
   - Keep existing CTA section, add "No credit card required" more prominently

7. **Footer (upgrade existing)**
   - Add links: Pricing, Login, Terms, Privacy
   - Add copyright year

### Design Requirements

- Use `whileInView` Framer Motion animations for each section (stagger children)
- Dark theme consistent with existing design tokens
- Gradient accents: teal-to-green gradient for primary CTA, subtle glass morphism cards
- Responsive: single column on mobile, multi-column on desktop
- No external images — use Lucide icons and CSS for all visuals

### Files to Modify

- `storyengine/frontend/src/app/page.tsx` — upgrade `LandingPage` component

### Acceptance Criteria

- [ ] Landing page has 7 distinct sections (hero, how-it-works, features, stats, pricing, CTA, footer)
- [ ] Demo video placeholder renders with styled frame
- [ ] How-it-works 3-step flow with connecting lines
- [ ] 6 feature cards with hover effects
- [ ] Stats bar with animated count-up
- [ ] Pricing section shows 3 tiers with CTA buttons
- [ ] All sections animate on scroll via Framer Motion `whileInView`
- [ ] Responsive: works on mobile (375px) through desktop (1440px)
- [ ] No broken links — all CTAs point to `/login` or `/pricing`
- [ ] TypeScript compiles: `cd storyengine/frontend && npx tsc --noEmit`

---

## Task 4: Settings Page — API Key Validation (Frontend + Backend)

**Role:** backend-dev, frontend-dev
**Priority:** MEDIUM

### Description

Add a "Test Connection" button next to each API key input on the settings page. Clicking it calls a backend validation endpoint that tests the key against the real API. Show green checkmark for success, red X for failure, with error message.

### Backend Changes

1. Create `POST /api/settings/keys/validate` endpoint in `storyengine/backend/routes/settings.py`
2. Request body: `{ "key_name": "anthropic_api_key", "key_value": "sk-..." }`
3. Validation logic per key type:
   - `anthropic_api_key` — call `GET https://api.anthropic.com/v1/models` with the key as `x-api-key` header
   - `openai_api_key` — call `GET https://api.openai.com/v1/models` with Bearer token
   - `elevenlabs_api_key` — call `GET https://api.elevenlabs.io/v1/user` with `xi-api-key` header
   - `kie_ai_api_key` — call `GET https://kieai.erweima.com/api/v1/user/balance` with token param
   - `google_client_id` / `google_refresh_token` — just check non-empty (OAuth flow validates separately)
4. Return: `{ "valid": true/false, "message": "Connected successfully" | "Invalid API key" | "Rate limited — key works but hit limit" }`
5. Timeout: 10 second max per validation call

### Frontend Changes

1. Add a "Test" button (small, inline) next to each API key input on `/settings/keys`
2. Clicking shows a spinner, then green checkmark + "Connected" or red X + error message
3. Add a section header: "Required" for Anthropic + OpenAI keys, "Optional" for others
4. Add help text below each key field explaining what the service is used for:
   - Anthropic: "Powers script generation, prompts, and analysis"
   - OpenAI: "Whisper audio transcription"
   - ElevenLabs: "AI voice synthesis"
   - etc.
5. Add integration status indicators at the top of the settings page showing connected vs not connected for each service (green dot vs gray dot)

### Files to Modify

- `storyengine/backend/routes/settings.py` — add validate endpoint
- `storyengine/frontend/src/app/settings/keys/page.tsx` — add test buttons, help text, status indicators
- `storyengine/frontend/src/lib/api.ts` — add `validateApiKey(name, value)` function

### Acceptance Criteria

- [ ] "Test" button appears next to each API key input
- [ ] Clicking test shows spinner then result (green check or red X)
- [ ] Validation actually calls the real API (not just format check)
- [ ] 10-second timeout prevents hanging
- [ ] "Required" vs "Optional" labels on key groups
- [ ] Help text explains each service's purpose
- [ ] Integration status dots at top of settings page

---

## Task 5: In-App Pipeline Notifications via SSE (Frontend)

**Role:** frontend-dev
**Priority:** MEDIUM

### Description

Wire the SSE stream from Task 1 to the toast notification system. When a pipeline stage completes or fails, show a toast notification anywhere in the app.

### Implementation

1. Create a `PipelineNotificationProvider` component that wraps the app and listens to the SSE stream
2. Place it inside the `AuthenticatedShell` so it only runs for authenticated users
3. Map SSE events to toast notifications:
   - `stage_change` where `to_status` matches a completion stage → `success` toast: "Script generation complete for [video_title]"
   - `activity` where `status === 'failed'` → `error` toast: "[bot_name] failed: [message]"
   - `activity` where `status === 'started'` → `info` toast: "[bot_name] started for [video_title]"
4. Toast behavior:
   - Success: green, auto-dismiss after 5 seconds
   - Error: red, persist until manually dismissed
   - Info: neutral, auto-dismiss after 3 seconds
5. Clicking a toast with a `video_id` navigates to `/pipeline/[videoId]`
6. Rate limit: max 1 toast per 3 seconds to prevent spam during multi-stage processing
7. Don't show notifications for events on the current page (e.g., if user is already viewing the video detail page, don't show toast for that video's events)

### Files to Modify

- `storyengine/frontend/src/components/notifications/PipelineNotificationProvider.tsx` — NEW file
- `storyengine/frontend/src/components/auth/AuthenticatedShell.tsx` — wrap children with notification provider
- `storyengine/frontend/src/app/providers.tsx` — may need to adjust provider order

### Acceptance Criteria

- [ ] Toasts appear when pipeline stages complete
- [ ] Error toasts persist, success toasts auto-dismiss
- [ ] Clicking toast navigates to the video detail page
- [ ] Rate limited to max 1 toast per 3 seconds
- [ ] No duplicate toasts for same event
- [ ] Only active for authenticated users
- [ ] Does not show toast for events on the currently viewed video

---

## Task 6: Billing Receipt Email on Subscription (Backend)

**Role:** backend-dev
**Priority:** MEDIUM

### Description

When a user completes Stripe checkout, send a billing receipt email using the existing Resend integration.

### Implementation

1. In `storyengine/backend/routes/billing.py`, inside `_handle_checkout_completed()`, add email sending after the subscription is recorded
2. Extract Resend email sending into a shared utility: `storyengine/backend/email.py`
   - Move the `_send_email()` function from `google_auth.py` into `email.py`
   - Import and use from both `google_auth.py` and `billing.py`
3. Email template for billing receipt:
   ```
   Subject: "Your StoryEngine subscription is confirmed"
   Body:
   - Welcome message
   - Plan name (Starter / Creator / Studio)
   - Price
   - Next billing date
   - Link to dashboard
   - Link to billing portal to manage subscription
   ```
4. Fetch the user's email from `accounts` table using the `stripe_customer_id` from the checkout session
5. Non-blocking: wrap in try/except so email failure doesn't break the webhook handler
6. Log success/failure for debugging

### Files to Modify

- `storyengine/backend/email.py` — NEW file, shared email utility
- `storyengine/backend/routes/billing.py` — add email send in `_handle_checkout_completed()`
- `storyengine/backend/routes/google_auth.py` — refactor to import from `email.py`

### Acceptance Criteria

- [ ] Receipt email sent after successful checkout
- [ ] Email contains plan name, price, and next billing date
- [ ] Email failure does not break webhook processing
- [ ] Shared email utility extracted (DRY principle)
- [ ] Existing password reset email still works after refactor

---

## Task 7: Trial Expiry Warning Email (Backend)

**Role:** backend-dev
**Priority:** MEDIUM

### Description

Send an email 3 days before a user's trial expires, encouraging them to upgrade. Add a `trial_warning_sent` flag to prevent duplicate emails.

### Implementation

1. Create migration `storyengine/backend/migrations/029_trial_warning_sent.sql`:
   ```sql
   ALTER TABLE accounts ADD COLUMN IF NOT EXISTS trial_warning_sent BOOLEAN DEFAULT FALSE;
   ```
2. Create `storyengine/backend/email_tasks.py` with a function `check_trial_warnings()`:
   - Query: `SELECT id, email, display_name, trial_ends_at FROM accounts WHERE trial_ends_at IS NOT NULL AND trial_ends_at BETWEEN NOW() AND NOW() + INTERVAL '3 days' AND (trial_warning_sent IS NULL OR trial_warning_sent = FALSE) AND stripe_subscription_id IS NULL`
   - For each account found, send email and set `trial_warning_sent = TRUE`
3. Email template:
   ```
   Subject: "Your StoryEngine Pro trial ends in 3 days"
   Body:
   - Personalized greeting
   - What they'll lose: Autopilot, learning loop, advanced analytics, priority render
   - Upgrade CTA with link to /billing
   - "Questions? Reply to this email"
   ```
4. Wire `check_trial_warnings()` into the existing background task system in `pipeline_executor.py` — call it once per hour (or on a schedule)
5. Use the shared email utility from Task 6

### Files to Modify

- `storyengine/backend/migrations/029_trial_warning_sent.sql` — NEW migration
- `storyengine/backend/email_tasks.py` — NEW file
- `storyengine/backend/email.py` — use shared utility from Task 6
- `storyengine/backend/pipeline_executor.py` — wire trial check into background tasks

### Acceptance Criteria

- [ ] Migration adds `trial_warning_sent` column
- [ ] `check_trial_warnings()` correctly identifies accounts expiring within 3 days
- [ ] Email sent with correct plan information and upgrade CTA
- [ ] `trial_warning_sent` flag prevents duplicate emails
- [ ] Only targets accounts WITHOUT an active Stripe subscription (free trial users)
- [ ] Non-blocking: email failure logged but doesn't crash

---

## Task 8: Empty States for Key Pages (Frontend)

**Role:** frontend-dev
**Priority:** MEDIUM

### Description

Add compelling empty states to the 5 most-visited pages. New users see blank pages — this is the biggest "this feels broken" signal. Each empty state should explain what the page does and have a clear CTA.

### Pages and Empty States

1. **Dashboard** (`/` authenticated view) — Already has basic empty states. Upgrade: add a "Quick Start" card when user has 0 videos: "Create your first video in 3 steps" with numbered checklist (1. Set up API keys, 2. Add a competitor channel, 3. Create your first video) and CTA buttons for each.

2. **Pipeline** (`/pipeline`) — When no videos exist: full-page illustration area with "Your production pipeline is empty" headline, "Create your first video to see it move through 13 stages" description, and a prominent "Create Video" button.

3. **Competitors** (`/competitors`) — When no competitor channels: "Track competitor performance" headline, "Add YouTube channels to monitor their titles, thumbnails, and views per hour" description, "Add Competitor" CTA.

4. **Analytics** (`/analytics`) — When no published videos: "Performance data arrives after publishing" headline, "Publish your first video to see CTR, retention, and view trends" description, link to pipeline.

5. **Learnings** (`/learnings`) — When no learnings: "Your AI gets smarter with each video" headline, "After publishing 2+ videos, the system extracts patterns about what works for your audience" description.

### Design Guidelines

- Use Lucide icons (large, 48px, teal colored) as visual anchors
- Short headline (6-8 words max)
- 1-2 line description
- Primary CTA button (teal gradient) + optional secondary link
- Consistent glass-morphism card style (`GlassCard` component)
- Framer Motion fade-in animation

### Files to Modify

- `storyengine/frontend/src/app/page.tsx` — dashboard quick start card
- `storyengine/frontend/src/app/pipeline/page.tsx` — pipeline empty state
- `storyengine/frontend/src/app/competitors/page.tsx` — competitors empty state
- `storyengine/frontend/src/app/analytics/page.tsx` — analytics empty state
- `storyengine/frontend/src/app/learnings/page.tsx` — learnings empty state

### Acceptance Criteria

- [ ] All 5 pages show compelling empty states when no data exists
- [ ] Each empty state has: icon, headline, description, CTA
- [ ] CTA buttons navigate to the correct action (create video, add competitor, etc.)
- [ ] Framer Motion entrance animations
- [ ] Empty states disappear once data exists (conditional rendering)
- [ ] Consistent visual style across all 5 pages

---

## Task 9: QA Verification (Full Flow Testing)

**Role:** qa-engineer
**Priority:** HIGH — Run AFTER all other tasks complete

### Description

End-to-end verification of all features built in this PRD. Use Playwright (via `webapp-testing` skill) to test the running application.

### Test Plan

**Pre-requisites:**
- Backend running: `cd storyengine/backend && python -m uvicorn main:app --reload --port 8001`
- Frontend running: `cd storyengine/frontend && npm run dev`
- At least one test user account exists

**1. SSE Stream (Task 1)**
- [ ] Open browser devtools Network tab, filter by EventSource
- [ ] Navigate to `/pipeline` — verify SSE connection established
- [ ] Trigger a pipeline stage (or simulate via direct DB insert into `stage_transitions`)
- [ ] Verify SSE event received in browser within 5 seconds
- [ ] Disconnect network briefly — verify reconnection

**2. Pipeline Stepper (Task 2)**
- [ ] Navigate to `/pipeline/[videoId]` for a video in mid-pipeline
- [ ] Verify 13 stages visible in stepper
- [ ] Completed stages show teal + checkmark
- [ ] Current stage shows amber pulse
- [ ] Future stages are dimmed
- [ ] Mobile viewport (375px): verify horizontal scroll works

**3. Landing Page (Task 3)**
- [ ] Log out / open incognito
- [ ] Navigate to `/`
- [ ] Verify all 7 sections render
- [ ] Scroll down — verify Framer Motion animations trigger
- [ ] Click "Start Free Trial" — navigates to `/login`
- [ ] Click "See Pricing" — navigates to `/pricing`
- [ ] Mobile viewport: verify responsive layout

**4. Settings Key Validation (Task 4)**
- [ ] Navigate to `/settings/keys`
- [ ] Click "Test" on an API key — verify spinner then result
- [ ] Test with invalid key — verify red X + error message
- [ ] Verify "Required" / "Optional" labels visible
- [ ] Verify help text for each key field

**5. Toast Notifications (Task 5)**
- [ ] Trigger a pipeline event (via API or DB)
- [ ] Verify toast appears within 5 seconds
- [ ] Success toast auto-dismisses after 5s
- [ ] Error toast persists until X clicked
- [ ] Click toast — navigates to video detail

**6. Empty States (Task 8)**
- [ ] Create new test account (or clear data)
- [ ] Navigate to each of the 5 pages
- [ ] Verify empty state renders with icon, headline, description, CTA
- [ ] Click CTA — verify navigation

**7. TypeScript + Build**
- [ ] `cd storyengine/frontend && npx tsc --noEmit` — zero errors
- [ ] `cd storyengine/frontend && npm run build` — successful production build

**8. Email Tasks (Tasks 6 & 7)**
- [ ] Verify `email.py` shared utility exists and is importable
- [ ] Verify `_handle_checkout_completed` calls email send
- [ ] Verify migration `029_trial_warning_sent.sql` exists and is valid SQL
- [ ] Verify `check_trial_warnings()` query is correct (run against test DB)

### Files to Check

- All new files created in Tasks 1-8 exist
- No console errors in browser
- No TypeScript errors
- No unhandled promise rejections

### Acceptance Criteria

- [ ] All 8 test sections pass
- [ ] TypeScript compiles with zero errors
- [ ] Production build succeeds
- [ ] No console errors in browser during testing
- [ ] All new components use existing design tokens (no hardcoded colors)

---

## Dependency Graph

```
Task 1 (SSE Backend + Hook)
  ├── Task 2 (Pipeline Stepper) — depends on Task 1
  ├── Task 5 (Toast Notifications) — depends on Task 1
  │
Task 3 (Landing Page) — independent
Task 4 (Settings Validation) — independent
Task 6 (Billing Receipt Email) — independent
Task 7 (Trial Warning Email) — depends on Task 6 (shared email utility)
Task 8 (Empty States) — independent
  │
  └── Task 9 (QA) — depends on ALL tasks
```

### Recommended Execution Order

1. **Parallel batch 1:** Task 1 (backend-dev) + Task 3 (frontend-dev) + Task 6 (backend-dev)
2. **Parallel batch 2:** Task 2 (frontend-dev, needs Task 1) + Task 4 (backend-dev + frontend-dev) + Task 7 (backend-dev, needs Task 6)
3. **Parallel batch 3:** Task 5 (frontend-dev, needs Task 1) + Task 8 (frontend-dev)
4. **Final:** Task 9 (qa-engineer)

---

## Design Tokens Reference

```css
--bg-void: #0A0A0B;
--bg-surface: #111113;
--bg-elevated: #1A1A1D;
--border: rgba(255, 255, 255, 0.06);
--text-primary: #F5F5F5;
--text-secondary: #A0A0A0;
--text-tertiary: #666666;
--turquoise: #00D4AA;      /* Primary accent — completed, success */
--orange: #E8913A;          /* Active/current state, warnings */
--gold: #D4A844;            /* Amber accent — pending, draft */
--green: #4CAF50;           /* Success, published */
--red: #E74C3C;             /* Error states */
/* Font: Outfit (display + body) */
```

---

## Notes for Agents

- **EventSource limitation:** `EventSource` does not support custom headers. Auth must be passed via query param. The backend `get_tenant_id` dependency needs a fallback to check `request.query_params.get("token")`.
- **SSE reconnection:** Browsers auto-reconnect EventSource, but add manual reconnection for robustness.
- **React Query invalidation:** When an SSE `stage_change` event arrives, invalidate the relevant query keys (`["videos"]`, `["video", videoId]`) so the UI refreshes without a full page reload.
- **Email utility:** Extract `_send_email()` from `google_auth.py` into `email.py` FIRST (Task 6), then Task 7 can import it. This avoids duplication.
- **Landing page:** Do NOT create a new route. Modify the existing `LandingPage` function in `page.tsx`. The auth gating already works via `AuthenticatedShell`.
- **Migration numbering:** Check existing migrations before numbering. Current highest is `028`. Use `029` for the trial warning migration.
