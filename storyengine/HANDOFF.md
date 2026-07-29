# HANDOFF - 2026-07-29 evening. D5 Frame Arbiter arc through A5 merged; cohesion + facing laws live; repair-path anchor fixed

## State
- Prod: d5cb85cb deployed, healthy. Live on prod: storyboard cohesion law (causal chain + BRIDGE), facing law rule 5g + FACING LOCK, image_prompt truncation fix, plan_only true dry run, D3-52 chat scroll fix (bundle verified by literal after the D3-60 stale-bundle saga), timeline T3/T2b/T5b, D3-65 redraw moment-master anchor fix.
- Merged on main, NOT yet applied/live (inert until A6): migrations 139 (arbiter_fingerprints) + 140 (frame_qa ledger columns), frame_arbiter.py (one-call scene judge + judge_board_sheet), arbiter_repair.py (board-only repair ladder, FRAME_REPAIR_ENABLED=False lock), A3b eval harness.
- Money on video 686b4651: total_cost 1.80 / max_spend 2.10. Of Ryan's authorized $1: $0.75 spent ($0.50 cohesion proof, $0.20 failed redraws now serving as the D3-65 repro, $0.05 scene-4 sheet fix - bleed gone, hash-verified), $0.25 left with $0.20 earmarked for the four scene-1 re-rolls.
- Scene 1 on prod currently holds 4 known-bad frames (101/102/108/109) awaiting re-rolls under the fixed anchor path.

## Next action (start here cold)
Read storyengine/tasks/loop-handoff.md and the D5 section of tasks/loop-checklist.md. Waiting on Ryan: (1) "roll them" - four scene-1 re-rolls, $0.20, recipe DV-6 in deferred-verification.md, judge each vs its labeled defect; (2) A6 go-live quote approval - apply migrations 139/140, feature flag, storyboard-stage hook calling judge_board_sheet then repair_board_finding, re-judge scheduling, ONE-scene live checkpoint (quote the vision+repair cost before running); (3) then A7 Review feed, A8 ruling wire-up, A9 rollout, A3b-2 frames re-exam (108 label re-adjudication with Ryan + cluster-level duplicate scoring).

## Standing laws set this session (all in code/memory, not just prose)
- Board gate first: judge at the $0.05 storyboard before frames exist (Ryan's ruling, proven same-day: sheet fix $0.05 vs frame fixes $0.20+).
- Learning ratchet: fingerprint occurrences record at JUDGMENT time only; repairs never write the ratchet; 2nd strike freezes the class and files root-cause instead of spending.
- Judge every batch with the full director rubric, unprompted - narrow judge briefs miss what Ryan catches in minutes.
- Frame-level auto-repair FROZEN until the judge passes A3b-2's exam (>=3/3 labeled defects, correct classes).

## Gotchas (new this session, on top of yesterday's)
- se deploy REQUIRES a session-name arg before flags (D3-60 open) - bare flags bind to WHO and the frontend build silently skips; verify BUILD_ID mtime or grep a literal in the deployed chunks.
- Storyboard regen overwrites the SAME Drive file id - URLs never rotate; verify by content hash.
- redraw-image previously sent no moment-master anchor (fixed, D3-65) - but setup-level (s_ref) anchoring is still not persisted per-asset; watch DV-6's re-rolls for under-anchoring.
- The still-redraw price is $0.05 at 1k (gpt-image-2); the $0.09 chips in the Director UI are CLIP routing, not still price.
- Chat scoped single-shot redraw requests resolve to the bulk $0.30 card (D3-61, reproduced twice with the shot chip attached).
- MCP server in the desktop session is scoped to the WRONG tenant for owner-tenant videos - use the VPS API with the /tmp/se_token bearer directly.
- Subagents refuse relayed money authorization by design: the orchestrator executes consent-bearing acts (cap raises, paid triggers) with its own hands.
