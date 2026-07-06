# HANDOFF - 2026-07-06 (Scenes page: "Finish pictures" gate + crash-resistant coverage)

(Prior handoff preserved as `HANDOFF.md.bak-20260706-111420`. Read GOAL.md too.)

Why this handoff exists: TWO desktop Claude threads doing this work leaked to
~70 GB and had to be cut (image-heavy threads balloon the desktop app). The
durable rule now: StoryEngine UI verification runs ONLY in a terminal CLI
session. This file is the full state - nothing needs re-deriving.

## The task (Ryan's report)

On video `cd5d2883-427e-4bfb-854d-8849d025d444` (PocoAPoco tenant
`44ecc95a-80f3-4261-8294-f963c03af2bd`) the Scenes page showed
"139/203 pictures" as if generation stalled, yet offered
"Animate everything - $13.90". Ryan asked: find the mismatch, make Build
run all images to completion, and audit the prompts before the paid run.

## Diagnosis - PROVEN against prod DB, do not redo

- **All planned images DID finish.** The four scene plans total 139 shots
  (32+36+38+33); all 139 are status='done', generation_method='coverage',
  created today 15:06-16:09. The background_tasks log shows all four
  coverage runs completed cleanly.
- **The "203" is fake.** The 64 extra rows are leftovers from the OLD
  sentence-segmentation plan: all created 2026-07-04 20:21:57-59, all
  status='pending', generation_method=NULL, never updated since. Coverage
  replaced that plan but never deleted its rows.
- Frontend gap: `needPictures` only counts scenes with ZERO pictures, so a
  partial set fell through to "Animate everything".
- The "one SSL error kills a scene" fragility was real: two asyncio.gather
  calls without return_exceptions in coverage.py.

## What's changed (uncommitted WIP, 3 files, verified: py_compile OK + tsc clean)

1. **`skills/video-pipeline/storyboard/coverage.py`** - crash-resistant frame gen:
   - `_gen_ref` wraps the image call in try/except: an SSL reset/timeout counts
     as a failed attempt and retries instead of escaping.
   - Moments + angles gathers use `return_exceptions=True` - one bad frame
     degrades to fewer frames, never kills siblings.
   - Flaky downloads get one retry before dropping a paid frame.

2. **`storyengine/backend/scripts/coverage_to_app.py`**:
   - `store_scene` DELETE also clears pictureless leftover rows
     (`image_url IS NULL AND video_clip_url IS NULL`) - coverage is the
     scene's plan of record. Rows with a paid image/clip are never deleted.
   - Each scene's `run_coverage` wrapped in try/except so one scene's crash
     doesn't stop the rest.

3. **`storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx`**:
   - New bulk kind `"finish"`: orange "Finish pictures (N missing)" button
     (calls handleReExtract) when some pictures exist but others are missing.
     Animate everything only offered when missing == 0.
   - Per-scene: amber "N pictures missing" chip; per-scene animate suppressed
     until sceneMissing === 0.

## What's LEFT (in order)

- [ ] **UI proof walk (LOCAL, terminal session).** `se devtoken`, run the dev
      server (port 3001), in the browser set
      `localStorage.se_active_tenant='44ecc95a-80f3-4261-8294-f963c03af2bd'`
      (else the video 404s - it belongs to the client tenant), open
      `/pipeline/cd5d2883-427e-4bfb-854d-8849d025d444` > Scenes. Expect:
      "Finish pictures (64 missing)" instead of Animate everything, amber
      chips per scene. Keep screenshots to 1-2 at the final gate.
- [ ] **One-time prod cleanup - NEEDS RYAN'S YES (deletes 64 rows):**
      `se db "DELETE FROM assets WHERE video_id='cd5d2883-427e-4bfb-854d-8849d025d444' AND image_url IS NULL AND video_clip_url IS NULL AND generation_method IS NULL"`
      After this the page reads 139/139 and Animate everything returns.
- [ ] **Deploy - NEEDS RYAN'S YES:** commit + push from local, `se deploy`
      (frontend + backend), then one /se-smoke pass.
- [ ] **Flag before the animate run:**
      - 2 dialogue lines exceed grok's 15s cap at 2.7 words/sec and WILL be cut
        mid-line: scene 3 image_index 136 (61 words, ~23s) and 137 (44 words,
        ~17s). Fix = shorten or split those lines - Ryan's call.
      - Real animate cost ~= $15.30, not $13.90 (115 clips @6s $0.10,
        20 @10s $0.15, 4 @15s $0.20). The UI estimate assumes flat $0.10/clip;
        optional later fix in clipCost().
      - Prompt audit otherwise CLEAN: 139/139 have image+video prompts, 130
        carry their dialogue embedded in the motion prompt, aspect 16:9
        consistent, clip durations are sized at animate time from spoken words
        (correct behavior; assigned_video_duration NULL is fine).

## Guardrails
- All VPS ops through `se` (health/logs/db/deploy/restart), not raw ssh.
- The store_scene DELETE is the one risky bit - its WHERE clause already
  protects any row holding a paid image_url or video_clip_url.
- UI verification for StoryEngine: terminal CLI only, never the desktop app.

## Kickoff line for the fresh terminal session
Read storyengine/HANDOFF.md and continue: walk the Scenes page proof locally,
then ask Ryan before the 64-row cleanup and the deploy.
