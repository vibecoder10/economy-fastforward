# HANDOFF - 2026-08-04/05. The film-studio program: built, deployed, proven live; One Road (D15) 6 of 9 chunks folded.

## State
- Prod: e75e6fa7 deployed (window "film-studio-window"), healthy, 0 active tasks, no lock. Migrations 145-152 live.
- Local main: e5d88ab1 - ~10 commits AHEAD of origin (all D15 + docs checkpoints). NOT pushed. Tree clean except generated next-env.d.ts.
- What shipped this session:
  - The 22-point film-studio audit -> full build: staleness system (D7), frame judge live (D8), Custom Film harvest (D9), native story bible (D10), shot archetypes + DP fields + mechanical prompt compiler (D11), pacing/transitions/rhythm (D12), provider dialect (D13). All test-proven, fresh-eyes verified.
  - Deploy window (~$0.08) + Scene Lab iteration 1 ($0.588): locks extracted from real pixels, 16 panels judged (3 real defects), freeze-on-repeat proven. Boards sent to Ryan.
  - One Road (D15): plans persist everywhere (D15-2), all buttons routed through the judged executor with plan_only provably free (D15-3), arbiter repair loop-proof (D15-4), ONE canonical shot-context builder (D15-5), redraw folded onto it (D15-6).
- One Road (D15) COMPLETE 9/9, all folded to local main 2026-08-05: one style resolver (D15-7), uniform purpose WARN gate (D15-8), one directive gate (D15-9). NOT deployed; NOT pushed.

## Next action (start here cold)
Invoke the maestro skill and read tasks/loop-handoff.md - the D15 lane is complete and folded; the loop is idle pending Ryan's calls (deploy window ships D15 with the voice-gate deploy note, then the $0 plan-only convergence proof from deferred-verification.md's tail, then Scene Lab iteration 2 if approved). Local main is ~18 commits ahead of origin - NEVER push outside the deploy window.

## Open threads
- Scene Lab iteration 2 - Ryan's call: redraw 3 defective panels + teach judge insert-subject fidelity (~$0.15), or clips of best 5 (~$0.50).
- Next deploy window ships D15; deploy note REQUIRED: picture button now enforces the voice gate (deliberate).
- Parked decisions: D8-5 rollout, D8-6 eval relabel, D8-8 Gemini judge bake-off (parked till volume), D8-3c channel scoping + deep-link 404.
- CARRIER VIDEO (other session's loop): d2e37cd6 RENDERED and eyes-on verified, $8.42/$20 - ONLY UPLOAD REMAINS, gated on Ryan's go. Full detail in git history of this file (commit e75e6fa7) + the checklist's top section.

## Gotchas learned this session
- git stash is ONE shared ref across worktrees; two workers collided. Fleet rule: patch-file stash-proofs only, folds never stash (lessons.md).
- Task files are now COMMITTED-by-convention (checkpoint commits) - stops fold collisions and stale overwrites by the other session.
- Fresh-worktree "28 custom_film_remotion failures" are phantom: symlink backend/venv, remotion-video/node_modules, remotion-video/public from main checkout -> 81/81 pass.
- Only chat-initiated draws were judged until D15-3; sheet previews create no asset rows; the desktop MCP is tenant-scoped wrong for owner-tenant videos - use se db / VPS API with /tmp/se_token.
