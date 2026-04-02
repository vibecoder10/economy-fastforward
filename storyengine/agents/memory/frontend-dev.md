# Frontend Dev Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- formatNumber() exists in lib/utils.ts — use it for view counts and other large numbers instead of rolling your own.
- types.ts has frontend-only types (camelCase). api.ts has backend-matching types (snake_case). Components import from api.ts — check both before adding types.
- acceptSuggestion/rejectSuggestion already exist in api.ts — check api.ts for existing wrappers before writing new fetch calls.
- Many tasks claim "backend returns X" but the field isn't in models.py or SQL query — always grep backend before starting. T3-002 (script_validation), T8-002 (final_video_url) are backend-blocked.
- PerformanceTab was using frontend Video type (types.ts) but videoForTabs passes VideoDetail (api.ts) as any — use VideoDetail directly for snapshot fields.
