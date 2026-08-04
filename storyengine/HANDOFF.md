# HANDOFF - 2026-08-04 - carrier video RENDERED and verified; upload is the only step left

## State
- Prod: 8d373f7d deployed 20:06 UTC. Render-verb fix (format-aware gate) + G24b matcher hardening both
  folded to main and live. Full suite on merged main: 4390 passed, 0 failed.
- Carrier video d2e37cd6-521a-43aa-a14d-ce096a783c1e (tenant 561b872d): status RENDERED.
  - Render ran 20:08-21:2x UTC, $0.00 external (25.00 render minutes charged internally).
  - Output verified EYES-ON from a fresh Drive download (file id 1l86Dkw-2QJAGvG71LsEduvE3KbkOKCbH,
    425MB, 25:11, 1080p h264+aac): 16 frames sampled across the full runtime - clean museum-model style
    throughout, correct opening title card (Argus 1918, flush-deck fact), rotated views present,
    CVA-01 (scene 13) renders as honest Jane's-style blueprints (side elevation + top-plan sheet),
    narration audio present at 100s/700s/1400s. No black frames, no broken text.
  - Drive folder: https://drive.google.com/drive/folders/1qQGwDe5wVRKvjQnson0zWy2KgWunVO83
  - Ledger $8.42 of $20 cap. Creative + render 100% done.

## Next action (start here cold)
UPLOAD - needs Ryan's explicit go (publishing to YouTube is outward-facing).
When he says go: MCP upload verb on d2e37cd6 (it has skip-if-done), then verify the YouTube draft
(SEO title/desc/tags, thumbnail attached) before any publish. YouTube upload quota today: 100 remaining.

## Open threads
- 4 machines have 2/3 views (parked thirds) - $0.05 each via fill runs, cosmetic.
- Backlog: script-stage calls don't ledger; production-guide next_step says "characters" for static_docu
  (cosmetic, confirmed again 2026-08-04); scripts.voice_id stamps wrong id; voice_duration_seconds null
  for THIS video's scenes (stamping only applies to future videos); tasks/loop-checklist.md older items.
- Unmerged branches, not blockers: claude/festive-bouman-6e2cb8 (self-provision Remotion assets in fresh
  worktrees), claude/stoic-allen-c5af1a (dead code removal).

## Gotchas learned this session
- ps + grep + head can hide the hot process (old idle PIDs sort first; head cuts the render). Use
  ps aux --sort=-%cpu before concluding "nothing is running".
- A branch cut before a design decision can carry a test asserting the OLD behavior - on merge, keep
  the decision, not the chronology (still-blocks vs blueprint-path).
- rclone backend copyid gdrive: <fileid> <dest> downloads a Drive file by id cleanly (no uc?id
  interstitial trouble at 425MB).
- Prior session gotchas (Drive update-in-place, se db read-only, scene-scoped runs don't advance
  status, re-voice needs script_status flip, one billable unit after a fix) still stand.
