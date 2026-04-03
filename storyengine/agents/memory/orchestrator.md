# Orchestrator Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- Operator focus directives override tab-order rule. Advance current_tab to match focus.
- VideoDetail model/SQL often lag behind schema.sql — always check all 3 when auditing a tab.
- ThumbnailTab component reads suggested_thumbnail_urls from types but backend never sends them — pattern: check Pydantic model not just TS types.
- Frontend-dev marks tasks done by updating task-queue.json only, without writing the code — always grep the actual file to verify implementation before trusting done status.
