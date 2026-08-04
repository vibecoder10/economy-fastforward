# HANDOFF - 2026-08-04 - render fix deployed, carrier video RENDERING now

## State
- Prod: 8d373f7d deployed 20:06 UTC (fable-render-unblock). Both fix branches folded to main:
  - claude/xenodochial-tharp-cd2cd6 (task_baa632d0): render verb is format-aware - static_docu gates on
    voice+views, not clip count. Proven live: verb quoted $0.00 instead of refusing.
  - claude/vibrant-einstein-0375bf (task_92cb9dd0): G24b discriminative roster matching. Merge conflict
    resolved: kept the new scene-22 e2e test AND the blueprint-path never-built test; dropped the branch's
    stale still-blocks test (written before Ryan's blueprint decision).
- Full backend suite on merged main: 4390 passed, 0 failed (the 28-failure baseline only bites fresh
  worktrees missing Remotion assets; main checkout has them).
- Carrier video d2e37cd6-521a-43aa-a14d-ce096a783c1e (tenant 561b872d):
  - Advanced ready_for_thumbnail -> ready_to_render via MCP advance verb.
  - RENDER RUNNING since 20:08 UTC: background_tasks 36677014-547c-40ae-a164-037db24a4c8d, remotion
    rendering /tmp/static_d2e37cd6_hyu98wjq/out.mp4 on the VPS (concurrency=3, swangle - slow, expect 1-3h).
  - Ledger unchanged at $8.42 of $20; render quoted $0.00 (compute-only).

## Next action (start here cold)
1. Check render: se db "SELECT status FROM background_tasks WHERE id='36677014-547c-40ae-a164-037db24a4c8d'"
   plus pgrep -f 'remotion render Main' on the VPS (a dead process with a stuck 'running' row is the failure
   mode to watch for).
2. When completed: find the output (video row render/final URL fields, or /tmp/static_d2e37cd6_hyu98wjq/out.mp4),
   download it, and EYES ON IT - watch the actual video, check text cards, captions, audio sync, blueprint
   scenes (CVA-01), before any upload talk. Upload has skip-if-done.
3. If failed: read error_message + journalctl around the failure; the render path is render_static.py ->
   remotion-video.

## Open threads
- 4 machines have 2/3 views (parked thirds, honest judge rejects) - $0.05 each via fill runs, cosmetic.
- Backlog: script-stage calls don't ledger; production-guide next_step says "characters" for static_docu
  (cosmetic, confirmed again today); scripts.voice_id column stamps wrong id; older items in tasks/loop-checklist.md.
- Unmerged branches that may still hold work: claude/festive-bouman-6e2cb8 (self-provision Remotion assets
  in fresh worktrees - would kill the 28-failure baseline for worktree sessions), claude/stoic-allen-c5af1a
  (remove dead _target_machine_research_source). Neither is a blocker.

## Gotchas learned this session
- ps + grep + head can hide the hot process (PID order puts old idle chromium first; head cuts the real
  render). Sort by CPU (ps aux --sort=-%cpu) before concluding "nothing is running".
- A branch cut before a design decision can carry a test asserting the OLD behavior - on merge, keep the
  decision, not the chronology (still-blocks vs blueprint-path).
- Prior gotchas (Drive update-in-place, se db read-only, scene-scoped runs don't advance status, re-voice
  needs script_status flip, one billable unit after a fix) all still stand - see git log e6fbfbad for detail.
