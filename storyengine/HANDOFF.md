# HANDOFF - 2026-07-29 Overnight loop: chat render fixed for real, cohesion law live and proven, $0.50 spent

## State
- Prod: 845e7daf deployed and healthy; frontend manually rebuilt 07:08Z (BUILD_ID sXOMgj7ceQWaenIDlAgll) after se deploy's silent frontend skip (D3-60); final scroll probe 3/3 PASS
- Branch: main, pushed. Tonight's worktrees (all merged): d3-52-chat-render, d3-53-cohesion, d3-53c-bridge, d3-59-planonly, t-lane - removable after a three-dot diff check
- Shipped: D3-52 chat render (anchor scroll -> settle loop -> setInterval hidden-tab-proof; both "prod failures" were the stale bundle), D3-53b+c storyboard cohesion law (causal chain + additive BRIDGE output contract, 2/2 plan proof), D3-59 plan_only true dry run, T3 unpack/approve persistence, T2b real-timecode ruler (DV-5 closed live), T5b clip-failure marker + deriveState precedence fix
- $1 proof RUN AND PASSED: scene 1 of 686b4651 regenerated under the new law - 10 frames, $0.50, judge verdict COHESIVE (real bridge shot: her own pod visible behind her as she exits). Evidence: tasks/evidence/d3-53-proof/. Money: total_cost 1.55 / max_spend 2.10.

## Next action (start here cold)
Ryan's morning decisions: (1) pending chat confirm on 686b4651 ("Do it ~$0.30 / Cancel") - scene-1 pictures were JUST regenerated; Do it re-spends. Recommend Cancel. (2) OpenArt parity chunks D3-55 (collapse turns to one-liners), D3-56 (Undo/Redo/Preview/Export toolbar), D3-57 (inline result card) - pick. (3) D3-60 deploy-tooling fix - small, needs a go since it is deploy tooling.

## Open threads
- D3-60 (NEW, HIGH): se deploy silent frontend no-op - until fixed, ALWAYS `se deploy <name> --with-frontend` and verify BUILD_ID mtime after
- (BRIDGE) tag absent from stored image_prompts though the rendered transition is correct - cheap plumbing check owed before trusting the formal contract
- Scene-1 board GRID (storyboard_1_url) still the old sheet - the coverage-images endpoint draws frames only
- D3-54 docked co-pilot never hydrates chat history; D3-58 stale env.local guard; D3-42/43 still parked
- Backend baseline doc correction: test_custom_film_remotion.py = 28 of the 43 baseline failures, not 4

## Gotchas learned this session
- `se deploy` MUST get a session-name arg before flags (D3-60): the flag otherwise binds to WHO and the build silently skips while the log looks right
- requestAnimationFrame AND ResizeObserver never fire in a hidden/backgrounded tab; correctors need setInterval (throttled to 1Hz hidden, still fires)
- Dev-mode Next timing masks production-build races - verify layout/scroll behavior on `npm run build && npm start`
- plan_only used to null drawn storyboard URLs (fixed, D3-59); the raw coverage path has NO budget_check (chat layer only)
- The coverage-images endpoint replaces a scene's frames wholesale (stale 07-28 batch silently swapped out) and never redraws the board grid
- Subagents refuse relayed money authorization by design - the orchestrator itself executes consent-bearing acts (cap raise, paid trigger)
