# PRD — Onboarding UX Audit & Fix Plan

**Owner:** Ryan (via Osiris)
**Created:** 2026-04-17
**Status:** Audit complete → P0 fixes in this PR, P1+ tracked in Command Center

## Problem

New users drop into StoryEngine and feel they've been thrown into chaos. The 5-step `/onboarding` wizard was shipped (commit `44063a19`) to fix this, but a hands-on audit with Playwright + component review surfaced concrete UX bugs that still make the first minute confusing.

This PRD is the audit report + the ranked fix plan + an executable acceptance-criteria test (Playwright spec) that we iterate against.

## Audit Method

- **Live walk-through** via Playwright MCP with frontend running at `localhost:3001`, backend mocked/unreachable.
- **Component code review** of all 5 step components: `ChannelIdentityStep`, `ApiKeysStep`, `StyleSetupStep`, `YouTubeConnectStep`, `CreateVideoStep`.
- Screenshot evidence saved at `.playwright-mcp/onboarding-step-1-*.png`.

## Step-by-Step Findings

### Step 1 — "Your Channel" (ChannelIdentityStep.tsx)

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1.1 | **P0** | Backend fetch errors leak raw string `"Failed to fetch"` into the user-visible error line. Observed live. | `app/onboarding/page.tsx:169, 210` — `err.message` rendered directly |
| 1.2 | **P0** | Placeholder copy uses Ryan's own channel (`"e.g., Economy FastForward"`), audience example is one specific niche, and angle example is domain-specific. Non-economy users feel the product isn't for them. | `ChannelIdentityStep.tsx:71, 87` |
| 1.3 | **P1** | Niche and audience are both optional per the code (`disabled={!channelName.trim()}`) but the UI has no "(optional)" affordance. Users think they must fill all three. | `ChannelIdentityStep.tsx:69–91` |
| 1.4 | **P1** | Disabled `Continue` button only dims via `opacity-50` layered on a saturated turquoise background — at 50% opacity on a near-black bg it still looks clickable. | `ActionButton.tsx:44–49` |
| 1.5 | **P2** | No client-side validation; clicking Continue with the button disabled gives no hint why. | `ChannelIdentityStep.tsx:100–111` |
| 1.6 | **P2** | No `/favicon.ico` or `/icon-192.png`; every page shows 404s in console. | `app/layout.tsx` manifest |

### Step 2 — "Tools" / API Keys (ApiKeysStep.tsx)

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 2.1 | **P0** | All 3 keys hard-required with no save-and-come-back. If a user doesn't have (e.g.) a Kie.ai key yet, they're blocked from the rest of onboarding. | `ApiKeysStep.tsx` Continue gate |
| 2.2 | **P1** | Input placeholder `"Paste your API key…"` on a password-masked field — user can't see what they pasted. If they paste a malformed key, they learn only when Save & Test fails. Either switch to text input with visual toggle, or show format hint (`sk-ant-…`) as a masked prefix preview. | `ApiKeysStep.tsx:135–139` |
| 2.3 | **P1** | No explicit success confirmation when a key validates — only a state change. Silent success. | `ApiKeysStep.tsx:53–55` |
| 2.4 | **P1** | Parent handler `handleTestApiKey` silently swallows errors (returns `false`) — test failures render as "didn't work" with no reason. | `app/onboarding/page.tsx:225–237` |
| 2.5 | **P2** | `reason` field for each key is a one-liner; no "why this API matters for your videos" framing beyond that. | `ApiKeysStep.tsx` row rendering |
| 2.6 | **P2** | Password input lacks `aria-label`; screen reader users get no context. | `ApiKeysStep.tsx:135` |

### Step 3 — "Style" (StyleSetupStep.tsx)

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 3.1 | **P1** | Copy says "Describe how you want your videos to sound and feel" — ambiguous (narrator tone? script content? editing style?). Users don't know what to write. | `StyleSetupStep.tsx` heading |
| 3.2 | **P1** | No ETA / progress indicator while `generateSystemPrompts` runs (can take 10–30s). Only a `<Spinner />`; users may think it hung. | `StyleSetupStep.tsx:~100` |
| 3.3 | **P2** | After success, the summary card appears with no "Continue" affordance explanation — some users skip accidentally. | `StyleSetupStep.tsx:83` |
| 3.4 | **P2** | Skip button goes straight to next step without confirming "you can always come back in Settings". | `StyleSetupStep.tsx:114–119` |

### Step 4 — "YouTube" (YouTubeConnectStep.tsx)

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 4.1 | **P0** | **OAuth cancellation is silently swallowed.** If user clicks Connect → authorizes nothing / denies / closes the popup, `catch` block does not set error state. They return to the onboarding page with no feedback and no retry prompt. | `app/onboarding/page.tsx:175–184` (handler) + `YouTubeConnectStep.tsx` |
| 4.2 | **P1** | Scope-explanation copy is absent. Users consent to OAuth with no idea what StoryEngine will access. | `YouTubeConnectStep.tsx` |
| 4.3 | **P1** | Sync errors are caught and swallowed. If sync fails in background after Connect, user sees no indicator and may think data is still loading. | `app/onboarding/page.tsx:186–194` |
| 4.4 | **P2** | Skip button text `"Skip — you can connect later in Settings"` is good. Keep. But no analog on Styles step. | `YouTubeConnectStep.tsx:~117` |

### Step 5 — "First Video" (CreateVideoStep.tsx)

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 5.1 | **P0** | Topic placeholder `"Why the US dollar might lose reserve currency status"` is Ryan's actual domain. Cooking/fitness/travel creators feel the product isn't for them. Same issue repeated in angle placeholder. | `CreateVideoStep.tsx:~110, ~306` |
| 5.2 | **P1** | After clicking "Create Video & Start Pipeline", page navigates to `/pipeline/{videoId}` with no intermediate "Your video is being created…" confirmation. Users may think the flow is broken. | `CreateVideoStep.tsx:~64–71` |
| 5.3 | **P1** | Suggestion cards display cryptic "Thumbnail: {thumbnail_text}" — users don't expect a title-suggestion to carry thumbnail copy. Relabel as "Suggested thumbnail text". | `CreateVideoStep.tsx:230` |
| 5.4 | **P2** | Suggestion `score` badge shown only when `score > 0` — inconsistent, no explanation of what 0–10 means. | `CreateVideoStep.tsx:210` |
| 5.5 | **P2** | No "credits this will cost" warning before clicking Suggest Titles (API-costing action). | `CreateVideoStep.tsx:~190` |

### Cross-Cutting

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| X.1 | **P0** | If `getOnboardingStatus()` fails on mount, user lands on Step 0 with no network-health banner. | `app/onboarding/page.tsx:74–97` |
| X.2 | **P1** | URL `?step=<key>` is not read; only `?yt_connected=true` is. Users can't bookmark a step, and testing individual steps requires backend mocks. | `app/onboarding/page.tsx:43, 115–122` |
| X.3 | **P1** | Error messages across the flow use `err.message` directly. Need a `sanitizeError()` util that maps common fetch/network errors to user-friendly copy. | cross-cutting |

## P0 Fixes (This PR)

Ships in commit(s) on branch `claude/onboarding-ux-audit`:

1. **Sanitize error messages.** New util `frontend/src/lib/errors.ts::humanizeError(err)` that maps common network/fetch failures to user-friendly copy. Apply in `handleSaveChannel`, `handleGenerateStyle`. (Addresses 1.1, X.3.)
2. **Generic placeholders** in Steps 1 and 5. Replace Ryan-specific examples with neutral ones. (Addresses 1.2, 5.1.)
3. **"(optional)" labels** on Niche + Audience in Step 1. (Addresses 1.3.)
4. **Stronger disabled button state** — `ActionButton` gets `disabled:opacity-40` (not 50) + `disabled:grayscale` + cursor override to make disabled state unmistakable. (Addresses 1.4.)
5. **Network-health banner** — if `getOnboardingStatus()` fails on mount, show a yellow banner at top of page: "We couldn't load your progress. Check your connection and refresh." (Addresses X.1.)
6. **Favicon + icon-192** — add placeholder PNGs so console stops 404ing. (Addresses 1.6.)

## P1 Fixes (Next PR)

Tracked in Command Center — plan for follow-up:

- Partial-save / come-back on Step 2 (remove hard-gate).
- Password field visual toggle (eye icon) on Step 2.
- Explicit success/failure copy on key test.
- YouTube OAuth cancellation error handler.
- Scope explanation before YouTube connect.
- Step 3 clarifying copy + ETA.
- Step 5 intermediate "creating your video…" confirmation.
- Cross-cutting: URL `?step=` deep-linking.

## P2 Fixes (Backlog)

- Accessibility sweep across all steps (aria-live, aria-describedby, labels).
- First-run checklist on dashboard post-onboarding (fix-roadmap 6.2 already captured).
- Retry affordances on failed steps.

## Acceptance Criteria (Test Plan)

These are the statements the new Playwright spec (`frontend/tests/onboarding.spec.ts`) asserts. Each maps to one or more fixes above.

1. On fresh `/onboarding` load with a failing backend, the page renders Step 1 content AND a "couldn't load your progress" banner. (P0 #5)
2. Step 1 placeholder for Channel Name does NOT contain the string "Economy FastForward". (P0 #2)
3. Step 1 labels for Niche and Audience contain the substring "(optional)". (P0 #3)
4. Step 1 Continue button has `aria-disabled="true"` (or the disabled attribute) when Channel Name is empty, and its computed style opacity ≤ 0.4. (P0 #4)
5. Step 1 submit failure (mocked backend 500) shows a human-readable error, NOT the raw string "Failed to fetch" or any ERROR_CODE-like string. (P0 #1)
6. `<link rel="icon">` resolves 200 (not 404). (P0 #6)

Test file stubs the backend via `page.route()` so it runs offline.

## Out of Scope (for This PR)

- Backend changes. (All fixes are frontend-only.)
- Onboarding component restructure (component split, step branching).
- Re-architecting `?step=` URL support (tracked as P1).

## Files Changed in P0 Commit

- `storyengine/frontend/src/lib/errors.ts` *(new)*
- `storyengine/frontend/src/app/onboarding/page.tsx` *(error sanitization + network-health banner)*
- `storyengine/frontend/src/components/onboarding/ChannelIdentityStep.tsx` *(placeholders + optional labels)*
- `storyengine/frontend/src/components/onboarding/CreateVideoStep.tsx` *(placeholders)*
- `storyengine/frontend/src/components/ui/ActionButton.tsx` *(stronger disabled state)*
- `storyengine/frontend/public/favicon.ico` *(new)* + `icon-192.png` *(new)*
- `storyengine/frontend/tests/onboarding.spec.ts` *(new — 6 acceptance tests)*
- `storyengine/prds/onboarding-ux-audit-2026-04-17.md` *(this doc)*
