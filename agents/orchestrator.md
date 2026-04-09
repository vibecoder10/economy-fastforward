# Orchestrator Memory

## Product Brain — Read First

**Before anything else, read the product brain:**

```bash
cat agents/product-brain.md
```

This tells you what's actually built (don't re-spec it), which roadmap days are done, and what to build next. If it's missing or >24h stale, regenerate it first:

```bash
./agents/refresh-product-brain.sh
```

The product brain is your substitute for the operator. It answers: "What would the owner want built today?"

---

## PRD Queue — Session Startup Protocol

**Every session MUST run these steps (in order):**

0. `cat agents/product-brain.md`       → Read product state, gap queue, and PRD guidelines
1. `./agents/prd-loader.sh --status`   → See which PRD is active and what's left
2. `./agents/prd-loader.sh --what-next` → See exact unblocked tasks to assign agents now
3. `./agents/prd-loader.sh`            → Write prd.json from active PRD for swarm execution
4. `./agents/prd-loader.sh --advance`  → When PRD is fully done, advance queue to next PRD

**When the queue runs low (< 2 pending PRDs):**
- `./agents/prd-generator.sh` — Auto-invents the next PRD from `tasks/roadmap.md` using Claude
- `./agents/prd-generator.sh --preview` — See what the next PRD would cover without writing it
- `prd-loader.sh` triggers this automatically when it detects low queue depth

**Product roadmap (source of truth for new PRDs):** `tasks/roadmap.md`
- 18-day SaaS plan: Week 1 (payable) → Week 2 (core UX) → Week 3 (reliable) → Week 4 (launchable)
- prd-generator.sh reads this + existing PRDs to invent the next logical chunk of work
- It uses Claude to write a full PRD in the same style as prd-1 through prd-4

**Current Queue Snapshot:**
- **PRD 1 — UX Polish:** ✅ COMPLETE (10/10 tasks, 2026-04-08)
- **PRD 2 — Pipeline UX:** ✅ COMPLETE (14/14 tasks, 2026-04-08)
- **PRD 3 — Infrastructure:** ✅ COMPLETE (11/11 tasks, 2026-04-08)
- **PRD 4 — Growth & Launch:** 🔵 ACTIVE (10/15 done) — remaining: T11, T12, T13, T14, T15

**Key files:**
- `agents/product-brain.md` — **LIVING product state** (what's built, gaps, priorities) — read first
- `agents/refresh-product-brain.sh` — regenerates product-brain.md from live codebase
- `agents/prd-queue.json` — machine-readable queue state (source of truth)
- `agents/prd-loader.sh`  — queue manager (status / what-next / load / advance)
- `agents/prd-generator.sh` — PRD inventor (reads product-brain + roadmap → writes prd-N-*.md)
- `agents/prds/prd-N-*.md` — PRD documents (human-readable specs for each chunk of work)
- `agents/prd.json`       — generated task file consumed by swarm/agents (gitignored)

---

## Session End Protocol

**Before finishing ANY session, refresh the product brain:**

```bash
./agents/refresh-product-brain.sh
```

This ensures the next autonomous session starts with an accurate picture of what was built. Without this, the next session's PRD generation is blind to today's progress.

Also run the normal end-of-session checklist:
- `tasks/todo.md` — update with current progress and clear handoff
- `tasks/lessons.md` — capture any corrections or new patterns
- `tasks/decisions.md` — append any architectural choices made

---

<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- Operator focus directives override tab-order rule. Advance current_tab to match focus.
- VideoDetail model/SQL often lag behind schema.sql — always check all 3 when auditing a tab.
- ThumbnailTab component reads suggested_thumbnail_urls from types but backend never sends them — pattern: check Pydantic model not just TS types.
- Frontend-dev marks tasks done by updating task-queue.json only, without writing the code — always grep the actual file to verify implementation before trusting done status.
- Tab status can drift out of sync (Tab 6 stayed "pending" after all tasks were verified) — always reconcile tab.status against actual task statuses before advancing current_tab.
- Frontend-dev sometimes already updates task-queue.json (verified + current_tab) in their commit — grep the committed file before making duplicate edits in MICRO sweep.
- All 17 original tabs complete as of 2026-04-03. Phase 2 starts at Tab 18 (Review nav, Create enhancement, Mobile UX). Product vision gaps: no calendar page, no onboarding wizard, no multi-channel yet.
- Task queue context provided at session start can be stale — always re-read the actual file before editing, as agents may have updated it between prompt generation and execution.
- QA agent sometimes verifies via code review and commits verification_notes to T20-001 but forgets to update T20-002 status — always check if the verified sibling task was also updated.
- Phase 1 (Tabs 1-17) + Phase 2 (Tabs 18-22) + Phase 3 (Tabs 23) all complete as of 2026-04-03. Tab 24 = Onboarding Wizard (redirect new users, 3-step channel+key+done flow). After 24: multi-channel.
- SEC-1 (dev-token fix) invalidates all existing sessions — users see analytics/profile 404s that are really 401s. Root fix: user clears localStorage and re-logins at /login. Not a code bug.
- Tab 27 extraction pipeline complete: T27-001 to T27-007 all done (84 panels extracted, in Supabase). T27-004 (grid migration) superseded by T27-005 success. T27-008 (permanent storage for all image gen) is the only remaining task.
- Thumbnail 400 + profile/analytics 404 have now recurred 15 consecutive sessions — NOT code bugs. BUG-UX-AUTH-STALE deployed. User must clear localStorage + re-login. Stop filing these as bugs.
- Launch Score stuck at 6/8: last 2 criteria (Stripe billing live, Google OAuth live) require STRIPE_SECRET_KEY + GOOGLE_CLIENT_ID env vars configured in production — not code changes.
- [retro 2026-04-05] Before dispatching pipeline-tester to QA a task, check git log for a commit confirming the fix is merged. The BUG-T11-006-QA re-verify task was avoidable with a one-line git check.
- Recurring user errors (thumb 400 + profile/analytics 404) now at session #17+ — confirmed NOT code bugs every time. Skip triage after first check; go straight to OPS report.
- Launch Score reached 8/8 on 2026-04-06 (REG18 sweep). Product is launch-ready. Awaiting operator go/no-go. No new build tasks needed.
- Session #18: video f9749bd2 status changed to ready_to_render (thumbnail done) — thumb endpoint now returns "running" not 400. Pipeline is progressing on its own.
- Phase 1 backend fully shipped (plan enforcement T29-001, password reset T30-001, free trial T31-001) as of 2026-04-08. Frontend is the sole bottleneck — 3 tasks (T29-003, T30-002, T31-002) + 3 QA tasks pending.
- Session #20+: thumbnail 400 + analytics/profile 404 still recurring — skip direct triage, go straight to MICRO sweep. These are confirmed NOT code bugs every session.
- task-queue.json lives at /home/clawd/agent-workspace/storyengine/agents/task-queue.json — NOT in storyengine/frontend subdir or cwd-relative path.
- Operator shipped system prompts feature (5cc7070) outside task queue — always check git log for untracked operator features and add QA tab when found.
- PRD queue system added 2026-04-09: prd-queue.json tracks active PRD, prd-loader.sh converts it to prd.json for agents. Always run prd-loader.sh --what-next at session start before spawning agents.
