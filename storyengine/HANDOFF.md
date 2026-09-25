# HANDOFF - 2026-09-25 - first one-click calendar run on the relay: reached photo gather, found 2 pipeline gaps

## State
- Prod: `fa4a31939` deployed (23:15Z), healthy, NO lock. Backend, frontend, worker all active.
- Branch: main clean (plus untracked `scripts/relay/undispatched.sh` - commit it).
- Branch `queue-length` (commit `36065b58b`, worktree `../.claude/worktrees/queue-length`): calendar "Length (minutes)"
  box + migration 164. Tested, NOT merged, NOT deployed, migration NOT applied.
- Customer rules (memory): Kie + ElevenLabs spend OK; Anthropic key NOT OK (removed) -> all text runs on the relay.
- What shipped this session:
  - Relay: helper token cost measured (general 77k vs `relay-researcher` 26k start). Helicopter 09debd56 script 20/20.
  - Worker: autobuild 12h limit (`AUTOBUILD_TIMEOUT_SECONDS`); a timed-out build now fails cleanly and frees the queue.
  - All build-path text calls use the relay when it is on (vision QA merged into `static_docu._vision_qa_transport`, SEO `allow_relay=True`).
  - /calendar paste box: strips list numbers + invisible chars; "Add to calendar" saves only; per-title "Start building".
  - ROOT-CAUSE FIX: `task_store.py` `$N IS NULL` params untyped since 2026-09-17 -> every durable job record failed silently
    and the worker refused every Run All / queue job. Now `$N::text`. Plus: required start record + skip finished arq leftovers.
  - Calendar list loaded: 10 DvsU titles (queue positions 110-200).

## Next action (start here cold)
Build the APPROVED plan (Ryan said "go"), in a new worktree off main, Sonnet workers, then merge `queue-length` too:
A. Title picks the machines (`backend/dvsu_roster_v2.py`, `pipeline_executor.py:180` `_title_needs_complete_roster`):
   route EVERY title through list-first (`_call_category_roster` + `_call_story_for_roster`). The list prompt
   (`_category_roster_prompt` ~L145) takes rules from the title: only the title's machine type; superlative titles
   (most hated/worst/best/deadliest) need a sourced reason per machine and prefer in-service machines over one-off
   prototypes; "Never-Built" titles allow unbuilt designs. Ask for target+3 spares, best first
   (`roster_selection.bound_selection_candidates` already stores extras in `roster_candidate_overflow`, unused today).
   NO output checker (Ryan's rule) - rules go in the prompt only.
B. Missing photo never stops the video (`static_docu.prefetch_roster_references` ~L4591, `reference_sources.collect_candidates`,
   `pipeline_executor.run_roster_image_gather` ~L9992): for a machine with 0 verified photos, run a wider 2nd search
   (each alias alone, unquoted, higher cap); still none -> swap in the best spare (same act if possible) at that
   roster index, record `roster_swaps`, re-baseline `roster_fingerprint` so the "roster changed" check does not fire.
   Photos come BEFORE research/script, so nothing downstream needs invalidating. Spares exhausted -> fail as today.
Then: full tests, ask Ryan, deploy (with queue-length + apply migration 164 + set the 9 saved titles to 20 min),
reset test video 59fd34a4 (clear research_payload to the contract only, queue item 3e6d4329 -> queued, attempts 0) and rerun.

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
