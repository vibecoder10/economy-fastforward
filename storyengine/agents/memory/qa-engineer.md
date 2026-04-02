# QA Engineer Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- T2-005: Info tab fully wired — 5 sections (Story DNA, Source, Story Bible, Research Payload, Original DNA, Quality Pipeline). All 18 backend fields verified in models.py + api.ts + info-tab.tsx. Tab 2 complete.
- Verify pre-existing "already implemented" tasks (like T8-001) by grepping for the route and checking main.py registration — don't assume they're correct just because description says so.
- Unicode em-dashes in JSON files cause Edit tool mismatches — read the exact bytes before editing.
- Always verify "done" tasks have actual git commits — backend-dev marked T7-004 done without committing code. grep models.py and videos.py SELECT to confirm fields exist.
- Tab 7 (Thumbnail) complete: 7 tasks verified. Key wiring: pipeline.py:808 triggers, pipeline_executor saves URL, models.py:90-91 suggested fields, videos.py:227 allows prompt PATCH, accept/reject at lines 453/496.
- Next.js Turbopack dev server can silently serve 500s for client JS if it encounters compile errors — always restart dev server before Playwright testing. Stale server = no React hydration = no API calls.
