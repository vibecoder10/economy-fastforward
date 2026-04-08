# Frontend Dev Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- formatNumber() exists in lib/utils.ts — use it for view counts and other large numbers instead of rolling your own.
- types.ts has frontend-only types (camelCase). api.ts has backend-matching types (snake_case). Components import from api.ts — check both before adding types.
- acceptSuggestion/rejectSuggestion already exist in api.ts — check api.ts for existing wrappers before writing new fetch calls.
- Many tasks claim "backend returns X" but the field isn't in models.py or SQL query — always grep backend before starting. T3-002 (script_validation), T8-002 (final_video_url) are backend-blocked.
- PerformanceTab was using frontend Video type (types.ts) but videoForTabs passes VideoDetail (api.ts) as any — use VideoDetail directly for snapshot fields.
- Analytics has 3 dedicated endpoints (/api/analytics/overview, /ctr-timeline, /framework-performance) — don't use getVideos() for analytics data.
- Profile page (/profile) is a Visual Style Manager, not a stub — add new sections to it rather than replacing. Account section added at top in T16-002.
- ScriptTab.tsx is a DEAD COMPONENT — pipeline page imports ScriptVoiceTab.tsx. Always check which component is actually rendered before adding features.
- Pipeline stage buttons must have frontend status gates matching backend's is_at_or_past_stage() check. Use getStageIndex() from constants.ts to compare. Backend returns 400 without frontend gates.
- Profile (/api/profile) and analytics (/api/analytics/*) 404s are backend runtime issues (routes registered correctly) — likely need backend restart, not frontend fixes.
- Plan gating lives in AuthenticatedShell.tsx — PRO_PATHS array and isPlanAtLeast() are exported for sidebar/bottom-tabs reuse. user.plan comes from AuthProvider (AuthUser.plan field).
- Always destructure `error` from useQuery and add error states — React Query silently swallows API failures, leaving users with empty/broken cards if not handled.
- PUBLIC_PATHS in AuthenticatedShell.tsx controls which routes render without auth shell (no sidebar). /pricing is public. Add new marketing pages there.
