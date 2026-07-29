# HANDOFF - 2026-07-28 Editor timeline shipped, supervised drive proved the vision, three chat bugs caught

## State
- Prod: c05b77d7 deployed --with-frontend, healthy (se health: all active, 0 active work, drain normal)
- Branch: main, pushed. Worktrees removable: t1-slot-model, t2-timeline, d3-48-sidebar, d3-49b-fixes, d3-51-verbatim (all merged and deployed)
- What shipped this session:
  - Chat card squash fix + right-rail media lightbox (D3-45/46)
  - REAL editor timeline on /chat: docked track, storyboard segments unpack in place into slot cells, honest ruler, Voice/Music lanes (T1+T2, layout corrected to Ryan's OpenArt spec after he rejected a vertical-card first pass)
  - Sidebar full-hide toggle with edge restore tab (D3-48)
  - Verbatim-guard fix: a confirmed follow-up edit now forces the script rewrite (D3-51)
  - Chat guard surfaces "still finishing" instead of eating taps; confirm card echoes the understood change (D3-49b)
  - Supervised drive (D3-50): dialogue into scenes 1-2, 9 scene-1 frames generated ($0.45 of approved $1), timeline showed Storyboard 1 unpacked with real stills

## Next action (start here cold)
Fix D3-52: chat turns and pending confirm cards NEVER render - not live, not after reload. Proven: "Generate the pictures for scene 1" on video 686b4651 POSTed 200 and queued pending_action {verb: images, scene: 1} in chat_conversations.state, but no user bubble and no confirm card ever appeared. A money decision sat invisible in the DB. Start: read tasks/loop-checklist.md D3-52 entry, then trace where the thread render reads history vs where the turn response and pending_action land (frontend ChatCore.tsx render path + routes/chat.py response shape). Invoke maestro, dispatch a Sonnet worker.

## Open threads
- D3-52 chat render gap - HIGHEST value bug, blocks the core chat loop whenever a turn is missed
- D3-51 live proof - deferred: next real script-change request on some OTHER video (NOT 686b4651 - a rewrite would clobber the hand-written dialogue and 9 fresh frames)
- Timeline plan (TIMELINE-WORKBENCH-PLAN.md): T3 unpack/approve persistence, T2b backend one-liner exposing video_duration on the assets serializer (unlocks the real timecode ruler, frontend auto-activates), T5b clip-failure marker, then T5/T6 clips-first, then T4/T7 chat commands + gating together
- Video 686b4651: max_spend cap still at 1.60 (Ryan's $1 drive cap) - raise or clear before more work on it
- backend/.env checked into repo has stale DATABASE_URL + missing SESSION_SECRET (worker finding, unfiled)
- D3 leftovers: D3-39/40 (on video 67a87d3c), D3-32..34, D3-41..44

## Gotchas learned this session
- VPS API is localhost:8001, NOT 8000 (se.sh knows; curl workers guessed wrong and got silent empty responses)
- generation_ledger has no "cost" column (use units/stage); scripts keys on "scene" not "scene_number"; se db needs --write for writes and one statement per call
- Frontend devDependencies break the VPS build (no-devDeps install + Next type-check): any chunk shipping dev tooling must prove `npm ci --omit=dev && npm run build` first (vitest lesson, fixed via tsconfig exclude)
- The in-app Browser pane's click-coordinate mapping drifts when the pane resizes - verify pointer reachability via elementFromPoint hit-testing, drive state via DOM clicks
- videos.script_source is set once ("user_supplied") and never resets - anything gating on it must consider staleness
- Chat turns render nothing if missed live (D3-52): the DB state is the truth, the thread display is not
