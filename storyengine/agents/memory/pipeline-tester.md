# Pipeline Tester Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->

- Gen/Regen/Variants buttons in StoryboardVisualsTab are tiny (text-[9px]) inside overflow containers — Playwright standard click times out; use JS .click() or force=True.
- Approval/Reject buttons only appear in StoryboardVisualsTab when seg.status === 'done'; with all-pending assets, 0 buttons show (expected behavior, not a bug).
- Backend auth: all /api/* endpoints require 'Authorization: Bearer dev-token' header; without it returns 403.
- Tab name for images/storyboard is "Storyboard & Visuals" (not "Visuals" or "Images").
- page.on('console', ...) use msg.type and msg.text as properties (not methods) in newer Playwright.
- API calls from the frontend go to the public IP (76.13.119.181:8001) not localhost — filter on '/api/' in URL to catch both.
