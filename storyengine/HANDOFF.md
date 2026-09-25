# HANDOFF - 2026-09-25 - roster spares + photo swap + calendar length DEPLOYED; paused before the rerun

## State
- Prod: `db2ecbcad` deployed 2026-09-25 00:23Z with frontend. Healthy. NO lock. Backend, frontend and worker are active.
- Migration 164 is applied (`production_queue.video_length_minutes`).
- Main is clean and pushed. There are no feature worktrees open for this work.
- What shipped:
  - Every title picks its machine list first (+3 spares in `roster_candidate_overflow`). Title rules are in the prompt only.
  - Photo gather: a miss gets a wider 2nd search. Still no photo -> best spare (same act first) swapped in, logged in `roster_swaps`.
  - Calendar "Length (minutes)" box (queue-length branch merged).
- Tests: 5445 pass; 3 old fails in `test_dvsu_saved_evidence_replay.py` (fail on main too).

## Next action (start here cold)
Ryan said: deploy, then pause. Pick up here:
1. Set the 9 saved calendar titles to 20 min (`production_queue.video_length_minutes`; only new items get it).
2. Reset test video 59fd34a4: clear research_payload to the contract only; queue item 3e6d4329 -> queued, attempts 0.
3. Rerun it on the relay and watch it (list-first roster + spares, then photo gather with swap). Check `roster_swaps`.

## Open threads
- Test video `59fd34a4` "Most Hated Helicopters": failed at photo gather ("Missing verified images: Kamov Ka-22"). Its roster
  is thesis-picked junk (HZ-1 Aerocycle, Air Horse, Rotodyne, XV-1, R22) - clear it before the rerun.
- Relay run needs this session watching: `scripts/relay/watch.sh` via Monitor (30 min, re-arm), `undispatched.sh`,
  photo checks 1 helper each with `judge_brief.md` + `post.sh`; text calls with `relay_brief.md` + `step.sh`.
- "Generate SEO" button (routes/videos.py inline) still calls Claude via Kie on relay tenants.
- Vision-QA relay requests carry no video_id (list pending workspace-wide, not per video).
- LATER: weekday + time-of-day cadence for the queue (today: every N days, needs Autopilot on).
- Old: research race resets verdicts; research_machine can't re-apply a fixed answer; two research card copies.

## Gotchas learned this session
- Queue-created videos had NO `video_length_minutes` -> roster fails "duration and minutes_per_machine must be finite positive numbers" (fixed on queue-length branch).
- Only titles with every/all/ever built/complete get list-first; everything else lets the thesis pick the roster.
- A refused arq job keeps its job id 24h; re-launch reused it and got 409 (fixed: skip finished leftovers).
- Deploy restarts the worker and kills a running build: never deploy mid-test.
- A non-continuous queue item that fails stays `failed` (no auto-retry); reset it by hand to rerun.
