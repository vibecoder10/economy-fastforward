# Orchestrator Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- Operator focus directives override tab-order rule. Advance current_tab to match focus.
- VideoDetail model/SQL often lag behind schema.sql — always check all 3 when auditing a tab.
- ThumbnailTab component reads suggested_thumbnail_urls from types but backend never sends them — pattern: check Pydantic model not just TS types.
- Frontend-dev marks tasks done by updating task-queue.json only, without writing the code — always grep the actual file to verify implementation before trusting done status.
- Tab status can drift out of sync (Tab 6 stayed "pending" after all tasks were verified) — always reconcile tab.status against actual task statuses before advancing current_tab.
- Frontend-dev sometimes already updates task-queue.json (verified + current_tab) in their commit — grep the committed file before making duplicate edits in MICRO sweep.
