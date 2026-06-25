# Morning report - overnight Phase 0 + 1 (2026-06-24 -> 25)

Good morning. Here's what I did while you slept, what's proven, and exactly what's next.

**Nothing was deployed to prod. No money was spent.** All work is on the branch
`feat/director-pass` (4 commits, off `main`). Review it, then deploy when you're happy.

## TL;DR
- **Phase 0 (unify the pipeline):** killed the false-proof rot, and unified the **interactive**
  image path on coverage (the chat dock now draws the same way the auto-build does). The deeper
  status-map swap is left for you to review (it touches the FINISH/autopilot chain I can't verify
  without a live run).
- **Phase 1 (real data):** the two paths that were writing fake zeros - "model a video" and
  onboarding - now pull real view/duration numbers from the official YouTube Data API, heal or
  skip zero rows, and say so loudly if the key is missing.
- Everything compiles; no tests regressed (286 pass; the 5 failures already fail on `main`).
- **Honesty flag:** this is code-level done (compile + unit tests). It is NOT yet proven against
  a real run - StoryEngine's authed pages can't be verified locally. The real proof is a staged
  prod test, which is your call.

## What's on the branch (4 commits)
1. **Kill false-proof signals.** The producer self-test asserted a string that no longer exists,
   so it failed before checking anything (fake confidence). Fixed it, and corrected two lying
   docstrings (coverage.py said it "isn't wired" - it's the live path now; pipeline_config claimed
   per-segment clip durations that don't actually happen). _Proof: the self-test now passes._
2. **Unify the interactive image path on coverage.** The chat dock's "make the pictures" /
   "storyboards" used the OLD grid path while the auto-build used coverage - two paths, different
   results. Added coverage-backed methods and pointed the dock at them. _Proof: no dock verb still
   points at a grid handler (grep clean); compiles._
3. **Model-a-video uses real data.** It modeled from yt-dlp (bot-blocked here) then oEmbed (no
   views at all), writing views=0 rows. Now it tries the YouTube Data API first (real
   views/duration), and both competitor upserts heal a prior zero instead of being blocked by it.
   _Proof: compiles; the new `fetch_single_video` mirrors the proven `fetch_channel_videos`._
4. **Onboarding uses real data.** Same fix for the competitor scrape: API-first (the same helper
   the daily scrape already uses), skips any zero-view row, falls back to yt-dlp only without a
   key. _Proof: keys matched the existing INSERT, so it's a drop-in; compiles._

## What I deliberately did NOT do (and why)
1. **The status-map swap (rest of Phase 0).** `run_next_step` still routes the batch/autopilot
   image stage to the old grid handlers. Swapping it needs status-advance handling and a
   FINISH/autopilot test I can't run unattended. The interactive path you care about is already
   unified; this is the batch path. Left for you to review.
2. **The own-channel onboarding ingestion** (your own channel's stats, separate from competitors)
   still uses yt-dlp. Lower stakes than competitor data; same fix applies when you want it.
3. **Purging the 23 existing zero rows on prod.** That's a data deletion on the live DB, so I left
   it for you. It's a one-liner (below). New rows won't be zeros anymore after deploy.

## Your move (in order)
1. **Review the branch:** `git checkout feat/director-pass` then `git log --oneline main..HEAD` and
   skim the diffs. It's pushed to origin as a branch (not main).
2. **Deploy it** when happy (backend-only; no frontend build needed): push to main, then on the
   VPS `git fetch` + `merge --ff-only`, `kill -9` the uvicorn pid, confirm `/api/health` 200.
3. **Purge the old zero rows** (after deploy), on the VPS DB:
   ```sql
   DELETE FROM competitor_videos WHERE COALESCE(views,0) <= 0;
   ```
   (Optionally scope to your tenant: `AND tenant_id = 'ee93e6d1-a9cc-44c3-81e9-84adee8329aa'`.)
4. **Prove Phase 1:** re-run onboarding or "model a video" for a channel and confirm the new
   competitor rows carry real views/duration (a quick `SELECT count(*) FILTER (WHERE views>0)` ).
5. **Then continue the plan:** Phase 2 (feed real competitor titles/hooks into the producer every
   turn) and Phase 3 (connect the "Worth modeling" click to the style detector) are the next
   highest-leverage wins toward the director chat. The Scene-1 proof (Phase 10) and its spend wait
   for you.

## Verification status (honest)
- Compile: all 8 touched files pass `py_compile`.
- Tests: 286 skills tests pass; 5 pre-existing failures unrelated to this work (confirmed on main).
- NOT verified: a real onboarding/model run against YouTube + DB, and the co-pilot dock drawing
  via coverage end-to-end. Those need the staged prod test in step 4.
