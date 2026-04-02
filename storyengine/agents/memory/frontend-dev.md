# Frontend Dev Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- formatNumber() exists in lib/utils.ts — use it for view counts and other large numbers instead of rolling your own.
- types.ts has frontend-only types (camelCase). api.ts has backend-matching types (snake_case). Components import from api.ts — check both before adding types.
