# Orchestrator Memory
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
- Thumbnail 400 + profile/analytics 404 have now recurred 8 consecutive sessions — root cause is stale browser state, NOT code bugs. Consider fixing the UX (better error message pointing to /login).
