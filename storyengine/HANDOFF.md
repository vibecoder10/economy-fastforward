# HANDOFF - 2026-07-29 late. D5 arc through A5 merged; set-lock root cause found (D3-66, UNSTARTED - API 529s); scene 1 script gained its escape beat

## State
- Prod: d5cb85cb deployed, healthy. Live: storyboard cohesion law (causal chain + BRIDGE), facing law rule 5g + FACING LOCK, image_prompt truncation fix, plan_only true dry run, D3-52 chat scroll fix, timeline T3/T2b/T5b, D3-65 redraw moment-master anchor fix.
- Merged on main, inert until A6: migrations 139 (arbiter_fingerprints) + 140 (frame_qa ledger columns), frame_arbiter.py (one-call scene judge + judge_board_sheet), arbiter_repair.py (board-only repair ladder, FRAME_REPAIR_ENABLED=False), A3b eval harness.
- Money on video 686b4651: total_cost 1.85 / max_spend 2.10. Of Ryan's authorized $1: $0.80 spent ($0.50 cohesion proof, $0.20 four failed redraws = the D3-65 repro, $0.05 scene-4 sheet fix, $0.05 the 108 diagnostic roll). $0.20 left. FRAME-LEVEL SPEND ON SCENE 1 IS FROZEN (D3-66 strike 2).
- Scene 1 prod state is a mixed bag: 6 good post-cohesion frames, 4 bad ones (101/102/108/109). 108's latest roll has CORRECT facing but the WRONG SET (pod bedroom, not corridor). Browser caching hides changes because redraws overwrite the same Drive file id.
- Scene 1 SCRIPT was edited (free, verified in DB, 411 -> 558 chars): the missing escape beat now exists - "Tonight, the whisper isn't enough. She finds the hatch release and presses it - a hiss of air as the seal gives way - and she climbs out into the corridor." Nothing has been regenerated from the new text yet. Scene 1's board grid is still the pre-cohesion-law sheet.

## Next action (start here cold)
1. D3-66 is FILED BUT UNSTARTED - four dispatch attempts all died on Anthropic API 529 overload; no worktree, no code. Full mechanism is in the checklist entry: every shot's stored prompt carries a lock reading "Set dressing and character blocking, identical in every shot of this scene: <FIRST LOCATION>: <full prop manifest>...", so corridor shots inherit the pod's furniture. Proven in pixels - the 108 roll reproduced the pod manifest item for item while its facing instruction rendered correctly. Fix = per-location manifests, never assert scene-wide identity across locations, derive location from SETUP-letter grouping / moment text / boards' [SET | ...] line, fail safe when undeterminable. Check whether the storyboard SHEET prompt path shares the defect (scene 4's theater bleed is the suspect).
2. THEN, and only in this order (Ryan's law, and he corrected me on it): verify the fix is genuinely in the deployed path -> re-roll ONE scene-1 BOARD from the new script text ($0.05, needs Ryan's go) -> judge that single sheet (escape beat its own moment? corridor panels in the corridor? facing holding?) -> frames only after the board passes.
3. Then: A6 go-live quote (migrations 139/140, flag, storyboard-stage hook, re-judge scheduling, ONE-scene live checkpoint), A7 Review feed, A8 ruling wire-up, A9 rollout, A3b-2 frames re-exam (Ryan re-adjudicates the disputed 108 facing label; cluster-level duplicate scoring).

## Standing laws set this session (in code + memory, not just prose)
- Board gate first: judge at the $0.05 storyboard before frames exist. When validating a logic change, the artifact to re-roll is the BOARD, not a frame.
- Never validate a fix with an artifact generated BEFORE the fix landed.
- Roll ONE, judge it, then scale - never batch paid operations on a path with no live proof.
- Learning ratchet: fingerprints record at JUDGMENT time only; repairs never write the ratchet; 2nd strike freezes the class and files root-cause instead of spending a third time.
- Judge every batch with the full director rubric, unprompted.
- Frame-level auto-repair FROZEN until A3b-2's exam passes.

## Gotchas (cumulative)
- se deploy REQUIRES a session-name arg BEFORE flags (D3-60 open): a bare flag binds to WHO, the frontend build silently skips, and the log still prints the flag. Verify BUILD_ID mtime or grep a literal in the deployed chunks.
- Storyboard AND frame regens overwrite the SAME Drive file id - URLs never rotate. Verify by content hash; expect browser cache to show stale images.
- redraw-image had no moment-master anchor (fixed, D3-65); setup-level (s_ref) anchoring still is not persisted per-asset - watch for under-anchoring.
- Still redraw = $0.05 at 1k (gpt-image-2). The $0.09 chips in the Director UI are CLIP routing, not still price.
- Scoped single-shot chat redraw requests resolve to the bulk $0.30 card (D3-61, reproduced twice with the shot chip attached).
- The desktop session's MCP server is scoped to the WRONG tenant for owner-tenant videos - use the VPS API with the /tmp/se_token bearer.
- Subagents refuse relayed money authorization by design; the orchestrator executes consent-bearing acts (cap raises, paid triggers) itself.
- Watcher/monitor agents try to hand their waits back ("standing by for the monitor") - there is no monitor; brief them that the polling loop must run inside their own turn.
- The coverage-images endpoint replaces a scene's frames wholesale and never redraws the board grid; storyboard-images?scene=N&beat=M does one sheet.
