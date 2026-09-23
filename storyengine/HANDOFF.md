# HANDOFF - 2026-09-23 - automation test video started; "every class" roster fix built (NOT deployed)

## State
- Prod: `0360a3001` (unchanged, healthy at session start). This session's fix is committed on
  local `main`, NOT pushed, NOT deployed. Deploy needs Ryan's yes.
- Backend suite: 5409 passed / 4 skipped / 3 failed. The 3 failures are all in
  `tests/test_dvsu_saved_evidence_replay.py` and pre-date this change: commit `df2046dc`
  (docs cleanup) deleted `docs/dvsu-run-all-reliability/replay-fixtures.json`, which they load.
  Fix: restore that file from git (`git show df2046dc^:storyengine/docs/dvsu-run-all-reliability/replay-fixtures.json`)
  or move it under `backend/tests/fixtures/` and repoint the test.
- Submarine video `6ac28204`: untouched, still `ready_for_voice`. Ryan said keep it as is.
- NEW test video `7b6914b6-3ff5-46d0-b05f-138a984baa32` "Every US Battleship Class Ever Built (2026)",
  tenant Designed Vs Used. Purpose: prove the pipeline runs unattended with NO API key
  (relay mode). Roster was selected on the OLD code and is wrong (see below).

## What this session did
1. `storyengine/CLAUDE.md` - new section "No API key? The session is the API (relay mode)":
   run the real pipeline via the storyengine MCP; the session only answers relay prompts
   (Sonnet subagents); vision passes too - answerer must download + Read every image.
2. Found on the test video: the roster call ("keep only the stronger one", "20-25") broke the
   "every class" promise - five single Iowa ships, ~9 classes missing - and the v2 structural
   check still passed it. Also: truncation to the runtime target cut the roster TAIL (the
   chronological ending).
3. Fix (Ryan chose "keep every class, runtime follows"):
   - `backend/dvsu_roster_v2.py::_call2_user_prompt` - complete titles (every/all/ever built,
     `_title_needs_complete_roster`) get `_COMPLETE_ROSTER_INSTRUCTIONS`: every class, one entry
     per class, never two ships of one class, no count limit. Other titles: prompt byte-identical.
   - `backend/pipeline_executor.py::run_roster_selection` v2 branch - complete title with >=3
     entries and a count != target: set `videos.video_length_minutes = count x minutes_per_machine`,
     recompute settings, no truncation.
   - 2 tests in `tests/test_dvsu_roster_v2.py`; both fail on old code, pass on new.

## Next action (start here cold)
1. Ask Ryan to approve deploy; then push main from the Mac and
   `scripts/se.sh deploy <session> ` (backend only).
2. Re-run the battleship roster. Its selection is `completed` with unchanged settings, so
   `research` will NOT redo it. Either reset `research_payload` (se db --write:
   `UPDATE videos SET research_payload='{"machine_script_contract":"factual_100_v1"}'::jsonb
   WHERE id='7b6914b6-...'` - check the fresh-video payload shape first) or create a fresh video
   with the same title and delete this one. Expect ~23 built classes (25 incl. 1920 South Dakota
   + Montana, which "ever built" should exclude).
3. Then continue unattended through the relay: `gather_roster_images` (vision via relay, free),
   detailed research, script. Stop and quote before voice (paid).
4. Record every place a human had to step in - that list is the "ready for automation" verdict.

## Open threads (carried)
- The headline slot contract (`SCOPE-research-slot-contract.md`) - Ryan has NOT approved
  building it yet; test on a copy, never the submarine video.
- Submarine script content notes, roster size, `_machine_story_plan` cleanup,
  `dvsu_script_operations` table, grammar judgment calls, VPS PAT rotation - unchanged.

## Gotchas learned this session
- Research relay requests arrive one at a time: thesis+acts, then roster (web_search). The guide
  can read "roster not_started" for a few seconds after the last answer - re-read before debugging.
- `research` quote shows ~$0.05 even with the relay on (actual spend $0). Cosmetic.
- `se db` JSON: `jsonb - 'key'` needs a cast (`-'key'::text`); big row dumps contain control
  chars, so pull single keys.

---

# HANDOFF - 2026-09-22 - submarine script finished (20/20, ready_for_voice); legacy script checker deleted; determinism steps 1+2 shipped

## State
- Prod: `0360a3001` deployed 2026-09-22T13:48Z, healthy, idle (`active_work` 0, no lock).
- Branch `main` = origin/main at `735e549d` (one commit ahead of prod: a docs-only
  scope file, nothing to deploy).
- Backend suite 5405 passed / 4 skipped. Frontend `tsc` clean.
- Not mine, left alone: `../tasks/decisions.md` (Ryan's uncommitted Jev entries),
  untracked `storyengine/jev-key-box.html`. Also untracked:
  `storyengine/DvsU_submarines_script.md` - the 20-paragraph script I generated
  for Ryan's review; delete it freely, it is regenerable from the DB.
- Video `6ac28204-681c-4839-9d11-6c3ba57b7b6e` (Every US Submarine Class Ever Built,
  tenant Designed Vs Used `561b872d-7b73-45e3-9c44-7f30c3566eda`): **status
  `ready_for_voice`**, 20/20 paragraphs saved, all cards green. Voice is the next
  paid stage and has NOT been run. Ryan has read the script.

- What shipped this session:
  1. `e97a8b33` - deleted the legacy code-side script checker: `audit_paragraph`,
     the boat/mentions/name-opener detectors, `build_repair_prompt` + the repair
     loop, and the branch that refused to save. Nothing can block a paragraph on
     quality now. `passed` means only "there is a usable paragraph here"; an
     unparseable writer response still fails closed (no text to surface).
  2. `e7a1056c` - **real bug**: `routes/videos.py::_parse_script_validation` only
     passed JSON through if it had `"checks"` or `"quality_critic"`. The DvsU blob
     has neither, so the whole thing was dropped to `None` on the way out of the
     API and a finished script read "0/20 production scenes". Key allow-list
     removed; any JSON object now passes through. Second time this trap fired.
  3. `c4d7b86c` - determinism step 1: temperature 0.4 -> 0.0, and quote-locked
     citations (the writer cites a `fact_id`; code attaches source_url + verbatim
     quote from the brief and discards any quote the model typed).
  4. `0360a300` - step 2: opener KINDS allocated per scene (adjacent scenes can no
     longer get the same opening), plus `unsupported_figures()` advisory.
  5. `735e549d` - scope doc for the research slot contract (not started).

## Next action (start here cold)
Implement `storyengine/SCOPE-research-slot-contract.md` (Ryan approved scoping it;
he has NOT yet approved building it - confirm first). Recommended option B: add a
`headline` field to each brief slot naming the one claim its quote proves, making
a 1:1 support check legitimate. Start by reading that file, then
`backend/dvsu_research_v2.py` (`_normalize_answer_slot`,
`_build_verified_source_package`, `packet_from_verified_source_package`).

The two risks are the whole job, not the check: (a) the packet round-trip rebuilds
from `{text, source_url, quote}` only, so an unthreaded field vanishes silently;
(b) `brief_fingerprint` hashes the brief, so if `headline` lands on old packets
every saved block in every video goes stale and the next bulk run pays to rewrite
everything. Write the fingerprint-stability test FIRST.

## Open threads
- Voice stage for 6ac28204 is unrun and PAID. Needs a cost quote + Ryan's yes.
- Script content notes Ryan has (from my read against
  `docs/gold-scripts/standards/DvsU_Script_Writing_System.md`), none fixed:
  scene 1 Holland says Dewey's "victory untenable" but the source says the
  SPANISH having two craft would have left Dewey's FLEET untenable - real
  precision slip; scenes 14/15 both open "Nautilus's 1955 trials..." (step 2
  prevents this in future writes, does not fix the saved text); scene 11 Tang has
  muddy pronouns; scenes 4/8/17 have long trailing final lines instead of short
  landings; scene 2 "sunk Holland's own first trial" is figurative but risky;
  scene 12 says the pin was "stitched together" - it was *designed*.
- Roster size: 20 units against the standard's 24-30 target (15 floor). Ryan's
  call, untouched.
- Carried: delete `_machine_story_plan` + `_script_starvation_*` +
  `repair_promote_excerpt` together; drop `dvsu_script_operations` table;
  `docs/gold-scripts/grammar/` judgment calls unreviewed; VPS git remote PAT
  rotation (Ryan only).

## Gotchas learned this session
- **The relay cache for 6ac28204 is cold twice over.** Both the prompt shape and
  the temperature changed, and `request_fingerprint` keys on both. A rerun of the
  script stage re-asks all 20 paragraphs through the relay; the saved script is
  untouched. Expect ~2 min of Sonnet subagent time per paragraph.
- **Measure a proposed checker before wiring it in.** The number-support check
  flags 20% of shipped rows per-quote, 55% at the research slot level, and 0%
  against the whole brief. Only the last one shipped. A brief slot pairs a
  450-char synthesis with ONE 250-char quote - the quote being narrower is the
  contract, not a defect.
- `se db` runs POSIX regex; `\y` works, `\s` in `substring(... from ...)` gets
  eaten by the shell. `.env` on the VPS cannot be `source`d (line 42 has an
  unquoted `<` in EMAIL_FROM) - use
  `env $(grep -E "^(DATABASE_URL|SUPABASE)" ../.env | xargs -d "\n")`.
- `database.py` has no `init_db`; just import `fetch_one` and call it.
- The prod frontend at `76.13.119.181:3001` shows the marketing page when signed
  out. Verify against the LOCAL dev server (`se devtoken`) which auto-logs-in
  against the PROD API - that tests deployed backend code.
- If another chat owns port 3001, `preview_start` refuses; just `navigate` to
  `localhost:3001` and reuse it. Clicks need the Browser pane visible;
  `read_page`/`get_page_text`/`find` work while it is hidden.
