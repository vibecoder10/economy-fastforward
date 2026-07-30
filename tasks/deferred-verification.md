# Deferred Verification

**Why this exists:** some checks need a real human at the keyboard (a mutating click, a
production dashboard nobody scripted access to) or hit an environment limit this session
couldn't work around. Nothing here is skipped-and-forgotten — each item has an exact
copy-pasteable recipe and an expected result. Tick items off as they're run; add new ones
whenever a session can't finish a live check itself.

---

## SFX render-path guard (commits a3453902, 9d83c621, branch `claude/exciting-swirles-4d8fba`) — 2026-07-24 night session

### 1. Local dev servers could not reach the production DB from this Mac — UI never actually verified live

**Blocker, not a code problem.** Backend started cleanly (`uvicorn main:app --port 8001`,
process up, `/api/health` responding), but every DB-backed request failed. Isolated with a raw
`asyncpg.connect()` test outside FastAPI — same `DATABASE_URL` that `se db` uses successfully
from the VPS returns `asyncpg.exceptions.InternalServerError: (ENOTFOUND) tenant/user
postgres.<project> not found` on every attempt from this local network (8/8 failures,
deterministic, not transient). See tasks/lessons.md 2026-07-24 (night) for the full
reproduction. Best guess: Supabase Network Restrictions (IP allowlist) scoped to the VPS's IP —
not confirmed, no Supabase dashboard access this session.

**What to run once this is fixed (or from a session that HAS prod DB access, e.g. on the VPS
itself):**

```bash
# 1. Confirm servers + DB reachable
curl -s localhost:8001/api/health | python3 -m json.tool | grep database   # expect "database": true

# 2. Confirm the new API fields, both videos
TOKEN=$(grep NEXT_PUBLIC_DEV_TOKEN storyengine/frontend/.env.local | cut -d= -f2)
curl -s localhost:8001/api/videos/65a8021e-eafa-4cff-94dc-31982ae7b63d \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep -i sound_effects
# Expected: "sound_effects_supported": false,
#           "sound_effects_unsupported_reason": "this video uses character-dialogue performance
#           rendering, which has no sound-effects track."

curl -s localhost:8001/api/videos/b4067bf5-9d6b-484e-8f7d-6fe7eb11416e \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep -i sound_effects
# Expected: "sound_effects_supported": true,
#           "sound_effects_unsupported_reason": null

# 3. Browser walk (Claude Browser tools or Playwright), both video IDs' Sound tab:
#    /production/65a8021e-eafa-4cff-94dc-31982ae7b63d  -> Generate buttons DISABLED,
#      amber banner visible, text names the render path ("character-dialogue performance
#      rendering, which has no sound-effects track")
#    /production/b4067bf5-9d6b-484e-8f7d-6fe7eb11416e  -> normal Sound tab, buttons enabled,
#      NO banner (regression check — this is one of the ~44 legacy videos everything used to work
#      on)
#    Check browser console for errors on both.
```

**What IS verified (code-level, not live):** `storyengine/backend/status_map.py`'s
`_render_path_sfx_reason()` was read directly and manually evaluated against each video's real
DB row (pulled via `se db`, read-only):
- BLOCKED video `65a8021e-eafa-4cff-94dc-31982ae7b63d` ("El Mercado..."):
  `dialogue_mode='character_dialogue'`, `render_mode=NULL`, `dialogue_audio=NULL`,
  `custom_film_plan_id=NULL` → falls through to the `dialogue_mode == 'character_dialogue'`
  branch → `sound_effects_supported=False`, reason = "this video uses character-dialogue
  performance rendering, which has no sound-effects track."
- ALLOWED video `b4067bf5-9d6b-484e-8f7d-6fe7eb11416e` ("She Wanted To Bake A Cake..."): all
  four fields NULL → `_render_path_sfx_reason` returns `""` → `sound_effects_supported=True`,
  `sound_effects_unsupported_reason=None`.
- `storyengine/frontend/src/components/production/SoundTab.tsx` was read directly:
  `sfxSupported = video.sound_effects_supported !== false` (line 187) gates both Generate
  buttons' `disabled` prop (lines 405, 417) and the amber banner block (lines 385–396), which
  renders `video.sound_effects_unsupported_reason` verbatim. The wiring is present and
  self-consistent; it has NOT been watched render in a browser against real data.

This is a real gap: "the code reads correctly" is not the same as "a user sees the right thing."
Do not treat this as done until step 3 above has actually run.

### 2. Advance-button behavior on a blocked video — mutates prod, needs a human

Not attempted this session (mutation ban — see the session's safety rule, live prod DB, no user
awake to approve). What to check once someone can click things:

1. Open a video on a blocked render path (e.g. `65a8021e-eafa-4cff-94dc-31982ae7b63d`, or any
   live `dialogue_mode='character_dialogue'` video that hasn't reached the sound stage yet).
2. Advance it through the pipeline up to the sound design stage (`POST
   /api/pipeline/advance/{id}` or the UI's Advance button) and confirm it **skips the Sound
   stage automatically** rather than getting stuck — `pipeline_executor._enabled_stages()`
   should exclude `"sound"` for this video (per `status_map.stages_excluding_blocked_sound`),
   and `_run_next_step_status_map()` should skip-and-advance past
   `ready_for_sound_design`/`ready_for_sound_effects` without deadlocking.
3. Confirm via `se db "SELECT status FROM videos WHERE id='<id>'"` that status lands on the next
   real stage (thumbnail/render), not stuck at a sound status.
4. Also worth a click: try `POST /api/sound-prompts/{id}` and `POST /api/sound-effects/{id}`
   directly on the blocked video and confirm a 400 with the render-path reason in the body (this
   IS safe to test with a mutating-looking call since it's expected to be REFUSED, not to spend
   money — but skipped this session anyway per the blanket "no mutating clicks" rule; use
   judgment if re-attempting).
5. Sanity-check on an ALLOWED (legacy) video: confirm Sound generation still actually starts
   normally (a real, tiny paid call — get explicit cost approval first, this is real money).

### 3. Frontend `/pipeline` create-page checkbox (mentioned in commit a3453902's message)

The commit says the pipeline create page disables the "Sound design" stage checkbox when the
selected production style is static-documentary. Not walked live this session (same DB
blocker as above). Once the DB blocker is fixed: open `/pipeline` (create-video flow), pick the
static-documentary production style, and confirm the Sound design stage checkbox is disabled
with an explanatory tooltip/label, not just unchecked-but-clickable.

---

## D7-2 staleness hash (branch `d7-2-staleness-hash`) — apply migration 145 on next deploy window

**Built and tested in a worktree only — migration 145 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). NOTE: `backend/main.py`'s startup
hook auto-applies every not-yet-applied file under `backend/migrations/*.sql` (tracked in a
`_migrations` table) — so the normal `se deploy` for this branch (which restarts the backend
service) applies migration 145 automatically. There is no separate manual-SQL step; the
"deferred" part is verifying it actually landed, since a per-migration failure there only logs
a warning and does NOT fail the boot (`except Exception as e: logger.warning(...)` inside
`main.py::_run_pending_migrations`) — a broken migration could silently no-op forever unless
someone checks:

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran (not just that the file shipped) —
#    check the startup log line and the tracking table:
se logs backend 200 | grep "145_script_staleness_hash"
# Expect: "Migration applied: 145_script_staleness_hash.sql"
se db "SELECT filename FROM _migrations WHERE filename = '145_script_staleness_hash.sql'"
# Expect exactly 1 row. If it's missing, check `se logs backend` around boot time for
# "Migration 145_script_staleness_hash.sql failed: ..." and fix forward — do NOT hand-apply
# the raw SQL over `se db --write` as a workaround without first finding out WHY the
# auto-apply failed (silent partial-schema drift is worse than a slow fix).

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'videos' \
  AND column_name IN ('characters_hash', 'environments_hash')"
# Expect 2 rows.

# 4. Verify the CHECK constraints were actually extended (not left as two constraints —
#    the DROP/ADD pattern in the migration is idempotent, but confirm the OLD constraint
#    name matched what migration 046/051 actually created)
se db "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint \
  WHERE conname IN ('video_characters_status_check', 'video_environments_status_check')"
# Expect both definitions to read: CHECK (status = ANY (ARRAY['draft'::text, 'approved'::text, 'stale'::text]))
# If either constraint is MISSING (name didn't match, e.g. renamed by some migration
# between 046/051 and now that this session's grep didn't find), migration 145's ADD
# CONSTRAINT line would have thrown and step 2's log/table check above would already have
# surfaced the failure — so a clean "applied" record already proves the name matched.

# 5. Sanity check no existing rows already sit outside (draft, approved, stale) — the
#    migration would have refused to apply if any did, but confirm anyway:
se db "SELECT status, count(*) FROM video_characters GROUP BY status"
se db "SELECT status, count(*) FROM video_environments GROUP BY status"

# 6. Smoke the round trip on ONE real video with an existing cast/environments:
#    a. Note its current video_characters/video_environments status values.
#    b. Edit one scene's text (PATCH .../scenes/{n}/text or the Director chat) enough
#       to change the wording.
#    c. se db "SELECT status FROM video_characters WHERE video_id='<id>'" -- expect 'stale'
#       (unless characters_hash was NULL because this video predates the migration and
#       nothing was ever regenerated since — that's the expected no-op case, not a bug).
#    d. Regenerate the cast (Characters tab -> Design characters) and confirm status
#       goes back to 'draft' (regeneration heals, per design).
```

**What IS verified (code-level + a full local test suite pass, not live prod):** all 4 writers
(`update_scene_text`, `rewrite_scene_text`, chat's `_apply_prompt_draft`, Drive pull-sync) plus
the 2 inline pipeline/Custom-Film script-write paths were exercised against a fake DB in
`storyengine/backend/tests/functional/test_d7_2_staleness_hash.py` (12 tests, all passing) —
including a stash-proof (neutering `_flag_stale_cast_and_environments` to a no-op produces 6
real `AssertionError` failures, reverted after confirming) and a second stash-proof substituting
a `DELETE` for the `UPDATE video_characters SET status='stale'` write (caught by the `_no_deletes`
helper). The full backend suite (`./venv/bin/python -m pytest tests/ -q`) passes 3848/3877 both
with and without this branch's changes — the same 29 pre-existing failures (`test_custom_film_
remotion.py`, `test_youtube_oauth_diagnostics.py`), byte-identical sorted FAILED sets stashed vs
applied. What is NOT verified: the migration actually running against the real Supabase
Postgres instance, and a real browser/UI walk of a script edit flagging a real video's cast card
"stale" (there is no UI for this yet — D7-4, per the chunk spec, is UI-out-of-scope for D7-2).

---

## D8-3b arbiter findings persistence (branch `d8-3b-findings-persist`) — apply migration 146 BEFORE D8-2's live run

**Built and tested in a worktree only — migration 146 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as
migration 145 above (`backend/main.py`'s startup hook applies every not-yet-applied file under
`backend/migrations/*.sql`, tracked in `_migrations`, a per-file failure only logs a warning and
does not fail boot) — so the normal `se deploy` for this branch applies migration 146
automatically, but landing it must happen BEFORE D8-2's first live arbiter run (parked on Ryan's
deploy window) or that run's per-instance findings are lost the same way D8-3 found them lost
before this chunk.

```bash
# 1. Lock the deploy window first (storyengine/CLAUDE.md's VPS coordination rule), then deploy
#    this branch normally: push main, then scripts/se.sh deploy <session-name> [--with-frontend]
#    — BEFORE letting D8-2's live run fire.

# 2. Confirm the migration actually ran:
se logs backend 200 | grep "146_arbiter_findings"
# Expect: "Migration applied: 146_arbiter_findings.sql"
se db "SELECT filename FROM _migrations WHERE filename = '146_arbiter_findings.sql'"
# Expect exactly 1 row. If missing, check `se logs backend` around boot time for
# "Migration 146_arbiter_findings.sql failed: ..." and fix forward — never hand-apply the raw
# SQL over `se db --write` without first finding out WHY the auto-apply failed.

# 3. Verify the table + both indexes exist:
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'arbiter_findings' ORDER BY ordinal_position"
# Expect all 17 columns: id, tenant_id, video_id, scene, station, reference, label, image_url,
# classification, failure_class, rule_id, fingerprint_key, rubric_level,
# decisive_prompt_fragment, description, new_vs_previous, cost, created_at (18 incl. id).
se db "SELECT indexname FROM pg_indexes WHERE tablename = 'arbiter_findings'"
# Expect arbiter_findings_pkey, arbiter_findings_tenant_created_idx, arbiter_findings_video_scene_idx.

# 4. AFTER D8-2's first live run fires (the actual point of this chunk): confirm rows exist and
#    match what the board station judged:
se db "SELECT station, reference, classification, failure_class, cost, created_at \
  FROM arbiter_findings ORDER BY created_at DESC LIMIT 20"
# Expect one row per panel judged in that run, station='board' (judge_scene_batch/judge_frame
# are not wired to any hook yet, only judge_board_sheet is), classification one of
# MODEL_DEFECT/AUTHORING_DEFECT/TASTE_QUESTION/OK.

# 5. Confirm GET /api/review/findings returns those same rows under `instances`:
TOKEN=$(grep NEXT_PUBLIC_DEV_TOKEN storyengine/frontend/.env.local | cut -d= -f2)
curl -s https://<prod-api-host>/api/review/findings -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool | grep -A3 '"instances"' | head -20
# Expect a non-empty `instances` array shaped per backend/models.py's ArbiterFindingInstance.

# 6. Walk the Findings tab in the browser (webapp-testing / se-smoke skill): /review -> Findings
#    tab -> confirm a "Judged frames & panels" section renders below the existing fingerprint/
#    spend sections, with a classification badge, station/reference, description, and (when the
#    judge call attached one) an image thumbnail per row.
```

**What IS verified (code-level + a full local test suite pass, not live prod):**
`storyengine/backend/tests/functional/test_d8_3b_findings_persist.py` (14 tests) covers
`arbiter_findings.record_finding_instances`'s field-mapping (board `panel`->`reference`/`label`
vs frame `image_index`->`reference`/`shot_type`->`label`, per-finding cost winning over call-level
cost, skipped/unrecognized-classification entries never persisted, one bad row never blocking the
rest of a batch) and `frame_arbiter_hook.run_after_storyboard_sheet`'s wiring (a write fires with
the right tenant/video/scene/station/cost/image_url after BOTH the first judgment and a
successful post-repair rejudge; a raised exception from `write_findings_fn` never propagates out
of the hook and never skips a later sheet's own judge/repair pass). `test_d8_3_review_findings.py`
was extended for the endpoint's third query (per-instance rows, scoped to tenant_id + the
`_FINDING_INSTANCES_LIMIT` cap). Three real stash-proofs were run (patch-file technique, never
`git stash`, per tasks/lessons.md's fleet rule): (a) neutering `_finding_cost` to always return
`call_cost` broke the frame-station cost assertion with a real `AssertionError` (999.0 == 0.019
mismatch); (b) removing the `try/except` around the hook's write call let a simulated
`RuntimeError` propagate all the way out of `run_after_storyboard_sheet`, failing the test with
that real exception; (c) neutering `get_findings` to always return `instances=[]` broke the
endpoint shape test with a real `AssertionError` (`0 == 1`) — all three reverted immediately
after confirming. The full backend suite (`./venv/bin/python -m pytest tests/ -q`, main checkout's
venv binary against worktree code) passes 3867/3896 stashed-technique baseline vs applied — the
same pre-existing 29 failures (`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`),
sorted FAILED sets byte-identical (diffed, empty output, exit 0). Frontend: `npx tsc --noEmit`
clean, `npm run build` passes (34/34 static pages) once `frontend/node_modules` and
`frontend/.env.local` are present in the worktree — neither is git-tracked, so a fresh worktree
needs `npm install` (or a symlink to an existing checkout's `node_modules`) and a copy of
`.env.local` (or `scripts/se.sh devtoken`) before running the frontend checks; this was done
locally for verification and removed afterward, not committed. What is NOT verified: the
migration actually running against the real Supabase Postgres instance, any real per-instance row
from a live judge call (D8-2's first live run hasn't happened yet — that is the entire point this
chunk exists to protect), and a real browser walk of the Findings tab's new "Judged frames &
panels" section against live data.
## G1 — gatherer fallbacks: normalizer, NA/Wayback chain, source steering — 2026-07-30

Ported into `storyengine/backend/pipeline_executor.py::_gather_verified_machine_source_package`
from the DVsU research simulator (`storyengine/tasks/evidence/dvsu-research-simulator/
build_package.py`, untracked, main checkout only): (a) the tolerant `_normalized_source_text`
fold (citation markers, smart quotes/dashes, NBSP, orphan punctuation/hyphen spaces), (b) the
National Archives Discovery JSON API + real-Wayback-availability fallback chain (new capture
methods `national_archives_api` and `wayback:<url>`, threaded through
`_verified_source_candidate_traceable` and the `unsupported_capture_methods` quality gate via a
new shared `_is_approved_source_capture_method` helper), (c) source steering — every Tavily call
now sends `exclude_domains: ["iwm.org.uk", "www.iwm.org.uk"]`, plus one additional
`include_domains`-scoped call to `awm.gov.au / rmg.co.uk / gov.uk / naval-encyclopedia.com /
naval-history.net / uboat.net` when `_is_naval_gather_context(title, machine)` detects a
ship/naval machine from the video title or machine name.

Cost cap respected: every test (`storyengine/backend/tests/test_machine_documentary_hold.py`,
15 new tests) runs fully offline against a fake `httpx.AsyncClient` — no live Tavily, National
Archives, or Wayback calls were made this session. **What is NOT verified live:**

### 1. The real National Archives Discovery API and Wayback availability API were never called live
The retry-on-empty-202 logic and the Wayback `archived_snapshots` response shape are both typed
from the reference simulator's own hard-won notes (`STATE.md`: "National Archives API 202s when
cold — retry or sidecar") and from `build_package.py`'s working implementation, not from a fresh
live call this session. Recipe to confirm against the real APIs (no API key needed, both are
public/unauthenticated):
```bash
# National Archives Discovery record -> its own JSON API. Use any real record id, e.g. one
# already gathered in the simulator's raw/ directory, or search discovery.nationalarchives.gov.uk
# for a British WW2-era ship-file record and take the id from its /details/r/<ID> URL.
curl -s "https://discovery.nationalarchives.gov.uk/API/records/v1/details/<ID>" | head -c 500
# Expect: JSON (may be empty/202-shaped on a cold record — the pipeline retries 3x, 3s apart).

# Wayback availability API for a real URL known to be archived.
curl -s "http://archive.org/wayback/available?url=https://www.iwm.org.uk/collections/item/object/205211678"
# Expect: {"archived_snapshots": {"closest": {"url": "https://web.archive.org/web/...", ...}}}
```
If either shape has drifted from what's coded (e.g. NA now nests the payload differently, or the
availability API renamed a key), `_fetch_source_fallback_text`/`_wayback_snapshot_url` in
`pipeline_executor.py` need a matching update — the fixture-based tests would keep passing
(they pin the CODED shape) while the live path silently stopped working, so a periodic live
recipe re-run is worth keeping.

### 2. Not yet run through a real gather for a machine whose ONLY sources are behind the iwm.org.uk bot-wall
The Definition of Complete's "a machine whose best sources sit behind a bot-wall must still yield
a passing package" is proven at the unit/fixture level (traceable capture methods, exclude/
include domains wired correctly) but not end-to-end against a live video. Recipe once Ryan
authorizes a paid Tavily run: pick one of the DVsU carrier roster machines noted in
`dvsu-research-simulator/STATE.md` as gathered mostly from IWM-adjacent pages, clear its cached
`machine_raw_source_packages` entry, and re-run research through the pipeline's own API path —
confirm the resulting package's sources include at least one `national_archives_api` or
`wayback:` capture method and still passes `_verified_machine_source_package_quality_errors`.

### 3. `static_docu.py`'s "reference fetching" was investigated and deliberately NOT touched
The chunk brief named `static_docu.py`'s reference fetching alongside
`_gather_verified_machine_source_package` as a second port target. Read in full
(`storyengine/backend/static_docu.py:770-894`, `_host_reference` / `_gather_reference_candidates`):
it is a Wikimedia Commons IMAGE-reference fetcher for ship-roster PHOTOS, unrelated to the
text-excerpt research package — it never touches iwm.org.uk, awm.gov.au, rmg.co.uk,
naval-encyclopedia.com, naval-history.net, or uboat.net, and has no citation-marker/excerpt
normalization concern at all. Porting the three GAP-1 capabilities there would not address any
real failure mode in that code. Flagging instead of silently dropping: if Ryan wants a
Wayback-image fallback for `_host_reference` (e.g. when a Commons file 404s), that is a distinct,
separately-scoped follow-up, not part of this chunk's Definition of Complete.

---

## D9-1 shot-purpose harvest (branch `d9-1-shot-purpose`) — apply migration 147 on next deploy window; confirm the PURPOSE tag actually shows up in a real plan

**Built and tested in a worktree only — migration 147 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every
prior migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file
error) — the "deferred" part is confirming it actually landed AND that a real planner call
actually emits the new PURPOSE row (a prompt-only change; no test in this chunk calls the real
Claude API):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "147_shot_purpose"
# Expect: "Migration applied: 147_shot_purpose.sql"
se db "SELECT filename FROM _migrations WHERE filename = '147_shot_purpose.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'assets' \
  AND column_name IN ('purpose_kind', 'shot_purpose')"
# Expect 2 rows.

# 4. Plan ONE real scene's coverage (sheet-preview planning, no spend — Scenes page ->
#    "plan the shots" / plan_only path) and read the raw directive.txt/coverage_directive
#    back out:
se db "SELECT coverage_directive FROM scripts WHERE video_id='<id>' AND scene=<n>"
# Confirm the planner ACTUALLY wrote "PURPOSE: <kind> | <text>" rows under real MASTER/ANGLE
# lines — this chunk only proves the PARSER handles the tag correctly if the LLM writes it;
# it does not prove Claude reliably follows a brand-new prompt rule on its first live call.
# If PURPOSE rows are sparse/absent on a real plan, check_shot_purpose_present's WARN log line
# ("shot-purpose check (D9-1): ... carries no PURPOSE: line") should be showing up in
# `se logs backend` around that plan's generation — confirms the WARN gate itself is live,
# even if the prompt compliance needs a follow-up nudge.

# 5. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and
#    confirm the columns actually populate:
se db "SELECT scene, image_index, purpose_kind, shot_purpose FROM assets \
  WHERE video_id='<id>' AND scene=<n> AND generation_method='coverage' ORDER BY image_index"
# Expect purpose_kind/shot_purpose populated (non-NULL) for shots whose PURPOSE row survived
# step 4's plan, NULL for any shot the planner didn't tag (floor-added REACTION/INSERT shots,
# or a plain miss) — NULL here is not itself a bug, see step 4.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d9_1_shot_purpose.py` (11 tests) covers `parse_coverage`'s
extraction of the per-shot `PURPOSE: <kind> | <text>` row (master and angle independently, bold
markdown tolerated, kind lowercased), the row never surviving into the stored `description` (the
whole reason it lives on its own line — rule 23/L27, INSTRUCTIONS ARE NOT CAPTIONS), BACKWARD
COMPATIBILITY against `SAMPLE` — the exact pre-existing fixture `test_coverage.py` already used
before this chunk — parsing byte-identical on `shot_type`/`description` with purpose fields simply
`None`, the new `check_shot_purpose_present` WARN gate (silent when every shot is tagged, flags
exactly the untagged ones, flags all 5 shots on the legacy `SAMPLE` fixture with no crash),
`generate_coverage_frames` threading `purpose_kind`/`shot_purpose` onto its frame dicts AND proof
the purpose text never reaches the actual image-generation prompt string (a planted marker string
in `shot_purpose` is asserted absent from the prompt `_gen_ref` receives), `enforce_setup_variety`'s
content-swap carrying purpose fields along with `shot_type`/`description` (so a swap never leaves
a shot's stated purpose describing a framing that moved elsewhere), and `plan_moments_deterministic`
(the ONE shared parse->budget->floors->variety pipeline both the sheet-preview planning path and
the real-pictures path call) preserving purpose fields end to end including a floor-added filler
shot correctly landing with none. `storyengine/backend/tests/functional/
test_d9_1_shot_purpose_stamp.py` (3 tests) proves `store_scene`'s INSERT actually stamps
`purpose_kind`/`shot_purpose` from a frame dict's fields (present, NULL-default, and independently
per-shot within one moment) — the sheet-preview planning path never inserts an asset row at all
("Storyboard SHEETS are a preview, not an asset row" is coverage_to_app.py's own comment, confirmed
by reading it — nothing to stamp there), so `store_scene` is the one real stamping site and both
paths feed it identical parsed fields via the shared `plan_moments_deterministic`. Real stash-proof
(patch-file technique, never `git stash`, per tasks/lessons.md's fleet rule): `git diff --cached`
of the full chunk saved to a patch, reverse-applied cleanly (`git apply -R`, working tree confirmed
clean after), pipeline suite (`test_board_laws.py` + `test_d6_2_repair_stamps.py` + `test_coverage.py`)
still 150/150 passing reverted (new D9-1 test files gone with the revert, no orphaned failures),
full backend suite (`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against
worktree code) 29 failed / 3867 passed reverted vs 29 failed / 3882 passed applied (the +15 are
this chunk's own new tests) — sorted FAILED sets byte-identical (diffed, empty output), then the
patch forward-applied cleanly to restore the chunk. `schema.sql`'s `assets` table updated with the
2 new columns (with a note: `assets.shot_location`/`assets.group_arrangement` from migration 143
were ALREADY missing from `schema.sql` before this chunk touched it — a pre-existing drift, not
something this chunk introduced or fixed; flagged separately, not folded into this migration).
What is NOT verified: the migration actually running against the real Supabase Postgres instance,
whether Claude reliably follows the new PURPOSE-row prompt rule on a real, unseen scene (prompt
compliance is never provable from a parser unit test — that's what step 4 above is for), and a
real `assets.purpose_kind`/`shot_purpose` value landing from an actual paid coverage-picture draw.

---

## D10-2ab: StoryEngine-native Story Bible generator (backend/story_bible_native.py)

**What changed:** `PipelineExecutor.run_story_bible` no longer imports the legacy
`storyboard.bot._generate_story_bible_for_storyboard` (a sys.path reach into
`skills/video-pipeline`) or persists through the Airtable-shim
`supabase_adapter.update_idea_fields`. It now calls a new backend-native module
(`story_bible_native.generate_story_bible_native`, ONE extended Claude call via the same
`self._pipeline.anthropic` bridge every other `run_*` step already uses) and persists with a
direct, tenant-scoped `UPDATE videos SET story_bible = $1 WHERE id = $2 AND tenant_id = $3`. The
document schema is unchanged for consumers (`characters`/`locations`/`scene_blocks`, matching the
legacy V2 normalizer field-for-field) plus three new top-level sections (`narrative`,
`relationships`, `arcs`) that dangling-reference-validate against the same generation's character
ids and drop bad refs with a logged warning rather than failing generation.

**What IS verified (code-level + a full local test suite pass, no real LLM call, $0):**
`storyengine/backend/tests/test_story_bible_native.py` (22 tests, pure module — no DB, no
PipelineExecutor) covers the ported normalizer defaults for characters/locations/scene_blocks
(costume/description fallback, first-image-forced-wide, location lookup by id, image-count and
consecutive-same-location warnings that never abort generation), the three new sections'
defaults, and dangling-character-id drops for both `relationships` and `arcs` (asserted via
`capsys`, never a raised exception). `storyengine/backend/tests/test_d10_2ab_run_story_bible.py`
(9 tests) covers the wiring: scripts are fetched tenant-scoped by `video_id`, the persisted
UPDATE query text and args are tenant-scoped and match the full generated document byte-for-byte
after a JSON round trip, and every failure path (Claude raises, no script rows, missing Anthropic
client, unparseable response, video not found) returns `status: "failed"` with zero writes to
`videos.story_bible` and never logs `bot_activity` as `"completed"`. `tests/functional/
test_characters.py` and `tests/functional/test_c66_production_guide.py` (the two named
"unaffected consumer" checks) pass unmodified. Two real stash-proofs were run (patch-file
technique, never `git stash`, per tasks/lessons.md's fleet rule): the full backend suite
(`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against worktree code) was
run BOTH on the reverted tree (`git checkout -- pipeline_executor.py` + the three new files moved
out of the tree, restored via `git apply` on a saved patch afterward) and on the applied tree —
29 failed / 3886 passed (reverted) vs 29 failed / 3908 passed (applied, +22 for the new test
files), sorted FAILED sets byte-identical (diffed, empty output, exit 0) — the same pre-existing
29 failures (`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`) as every other
recent D-series chunk.

**What is NOT verified — deploy-window check owed:**

### 1. A real Story Bible generation on a test video with a live Claude call

No live LLM call was made (every test above stubs `self._pipeline.anthropic`). Before this ships
to a real customer's build, run one real generation end to end and confirm:
- The new `narrative`/`relationships`/`arcs` sections are actually present and sensible on a
  REAL script (not just the hand-written fixture the tests use) — in particular, whether Claude
  reliably keeps `relationships`/`arcs` character ids matching `characters` ids without the
  dangling-ref dropper silently emptying them out on a real generation.
- `scene_blocks` total image count roughly matches the requested `total_images` (a mismatch only
  warns, never fails — worth eyeballing on a real script rather than assuming the model complies).
- The downstream legacy consumers (`routes/characters.py`'s bible<->cast sync,
  `scripts/coverage_to_app.py`'s `_story_bible_locations`, `channel_profile_documents.py`) render
  correctly against a bible that now has 3 extra top-level keys they've never seen live before.
- `run_storyboard_prompts` (still on the legacy `storyboard/run.py` path, untouched by this
  chunk) does NOT regenerate its own bible when one from this native path is already persisted —
  confirm `videos.story_bible` is non-empty after `run_story_bible` so its own
  `_generate_story_bible_for_storyboard` fallback never fires.

**Recipe:** pick a test video already past scripting (`ready_for_storyboards` or earlier, with
scripted scenes), call `POST /api/pipeline/{video_id}/story-bible` (or the equivalent chat/action
verb) once, then `se db "SELECT story_bible FROM videos WHERE id = '<video_id>'"` and eyeball the
JSON. **Cost: one Claude Sonnet call, ~$0.02-0.05** (per docs/cost-awareness.md's "Claude API
(Sonnet) ~$0.01-0.05/call" line — no image/video/voice spend, this step is text-only) — quote
this and get a yes before running it live.

---

## D9-6/D9-7 transition + causality harvest (branch `d9-67-transitions`) — apply migration 148 on next deploy window; confirm TRANSITION/CAUSED_BY rows actually show up in a real plan

**Built and tested in a worktree only — migration 148 was NOT applied to prod this session** (no
prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every prior
migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file error) —
the "deferred" part is confirming it actually landed AND that a real planner call actually emits
the new TRANSITION/CAUSED_BY rows (a prompt-only change; no test in this chunk calls the real
Claude API):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "148_shot_transition_causality"
# Expect: "Migration applied: 148_shot_transition_causality.sql"
se db "SELECT filename FROM _migrations WHERE filename = '148_shot_transition_causality.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'assets' \
  AND column_name IN ('transition_kind', 'continuity_bridge', 'caused_by')"
# Expect 3 rows.

# 4. Plan ONE real scene's coverage (sheet-preview planning, no spend — Scenes page ->
#    "plan the shots" / plan_only path) and read the raw directive.txt/coverage_directive
#    back out:
se db "SELECT coverage_directive FROM scripts WHERE video_id='<id>' AND scene=<n>"
# Confirm the planner ACTUALLY wrote "TRANSITION: <kind> | <bridge>" and "CAUSED_BY: M<n>-..."
# rows under real MASTER/ANGLE lines, in ADDITION to D9-1's PURPOSE rows — this chunk only
# proves the PARSER handles the two new tags correctly if the LLM writes them; it does not
# prove Claude reliably follows two brand-new prompt rules (25/26) stacked on top of an
# existing one (24) on its first live call, or that it correctly derives the M<n>-MASTER/
# M<n>-ANGLE<k> label format for a CAUSED_BY reference without being shown a worked example
# beyond the prompt's own template. If TRANSITION/CAUSED_BY rows are sparse/absent/malformed
# on a real plan, the four new WARN log lines ("shot-transition check (D9-6): ...", "shot-
# transition-bridge check (D9-6): ...", "shot-causality check (D9-7): ...") should be showing
# up in `se logs backend` around that plan's generation — confirms the WARN gates themselves
# are live, even if prompt compliance needs a follow-up nudge. Pay particular attention to
# whether Claude gets the CAUSED_BY label format right (M<n>-MASTER / M<n>-ANGLE<k>) — this is
# the one place this chunk asks the planner to do something more structured than free prose,
# and check_shot_causality_valid's "does this label exist / is it earlier" check depends on it
# being syntactically exact.

# 5. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and
#    confirm the columns actually populate:
se db "SELECT scene, image_index, transition_kind, continuity_bridge, caused_by FROM assets \
  WHERE video_id='<id>' AND scene=<n> AND generation_method='coverage' ORDER BY image_index"
# Expect transition_kind/caused_by populated (non-NULL) for shots whose rows survived step 4's
# plan, continuity_bridge populated only for a non-continuous/non-opening kind that stated one,
# NULL for any shot the planner didn't tag (floor-added REACTION/INSERT shots, or a plain miss,
# or the scene's true first shot for caused_by specifically) — NULL here is not itself a bug,
# see step 4.
```

**Grammar decision (documented here since it drives what step 4 above needs to confirm):** TWO
separate trailing rows, `TRANSITION: <kind> | <bridge>` (rule 25) and `CAUSED_BY: <label>` (rule
26) — not folded into one row, and not folded into D9-1's PURPOSE row. Each is independently
optional, independently gated by its own warn check(s), and Custom Film itself keeps
transition_from_previous/continuity_bridge and caused_by as separate ShotDraft fields — combining
them would conflate distinct warn conditions behind one piece of text for no reduction in grammar
surface. CAUSED_BY carries a SINGLE reference (not a tuple like Custom Film's `caused_by`): the
flagship grammar has no LLM-assigned `shot_key` the way ShotDraft does, so the reference format
taught here is a label the planner can derive purely from context already on the page —
`M<moment_number>-MASTER` / `M<moment_number>-ANGLE<k>` — never a running global shot count it
would have to track across the whole scene; one clear reference is more likely to be authored
correctly than a list the planner has to keep internally consistent.

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d9_6_7_transition_causality.py` (29 tests) covers `parse_
coverage`'s extraction of the per-shot `TRANSITION: <kind> | <bridge>` row (bridge optional,
omitted entirely for "continuous") and `CAUSED_BY: <label>` row, independently and together with
D9-1's PURPOSE row IN ANY ORDER the planner writes them (the decisive robustness property: a
naive "check PURPOSE first" scan let PURPOSE's own `.+?` capture swallow trailing TRANSITION/
CAUSED_BY rows whole before the fix — `_strip_shot_metadata_rows` now picks whichever candidate
regex match starts LATEST in the current text each pass, peeling the true tail row first
regardless of which of the three it is), the rows never surviving into the stored `description`,
BACKWARD COMPATIBILITY against BOTH the legacy zero-metadata-row `SAMPLE` fixture (byte-identical
shot_type/description, all five fields None) AND a synthesized D9-1-era fixture (PURPOSE rows
present, TRANSITION/CAUSED_BY absent — the real shape of every plan generated between D9-1
landing and this chunk landing), the four new WARN gates (`check_shot_transition_present`,
`check_shot_transition_bridge_present` — including the "opening" exemption alongside
"continuous", a deliberate refinement over the task brief's literal wording to faithfully mirror
Custom Film's own model where an opening shot structurally never carries a bridge —
`check_shot_causality_present`, `check_shot_causality_valid` — nonexistent-reference, forward-
reference, and self-reference all correctly flagged, a correct earlier reference correctly
silent), `generate_coverage_frames` threading all three new fields onto its frame dicts AND proof
the bridge/caused_by text never reaches the actual image-generation prompt string (planted marker
strings in both fields asserted absent from the prompt `_gen_ref` receives), `enforce_setup_
variety`'s content-swap carrying transition_kind/continuity_bridge/caused_by along with shot_type/
description/purpose_kind/shot_purpose (documented judgment call: these three describe WHY/HOW a
specific piece of content cuts in and what it follows from, not a fact about the position it
occupies, so they travel with content on a swap exactly like D9-1's purpose fields do — a known
residual: since caused_by is a positional LABEL and enforce_setup_variety only trades within the
same/adjacent moment, a swap can in rare cases leave a shot's caused_by pointing at itself or at
the position it just vacated; `check_shot_causality_valid` catches this post-swap as an ordinary
warn, by design, rather than needing a special case), and `plan_moments_deterministic` (the ONE
shared parse->budget->floors->variety pipeline both the sheet-preview and real-pictures paths
call) preserving all fields end to end including a floor-added filler shot correctly landing with
none. `storyengine/backend/tests/functional/test_d9_6_7_transition_causality_stamp.py` (4 tests)
proves `store_scene`'s INSERT stamps `transition_kind`/`continuity_bridge`/`caused_by` from a
frame dict's fields (present, NULL-default, independently per-shot within one moment, and a
non-continuous kind WITH a bridge stamping both) — same "store_scene is the one real stamping
site" reasoning as D9-1 (re-confirmed by re-reading coverage_to_app.py, nothing changed about
that). `storyengine/backend/tests/functional/test_d9_1_shot_purpose_stamp.py` was UPDATED (not
left broken): this chunk's migration 148 appends three columns AFTER migration 147's purpose_kind/
shot_purpose in the INSERT's column list, which shifted D9-1's own hardcoded `params[-2]`/
`params[-1]` positional assertions off target (they silently started reading continuity_bridge/
caused_by instead, or in one case still passed by coincidence since both new-and-old values were
None) — caught by running D9-1's stamp test after this chunk's change, fixed to `params[-5]`/
`params[-4]` (and `[-5:-3]` for the two-shots-in-one-moment test) with a comment explaining why,
re-verified passing. Real stash-proof (patch-file technique, never `git stash`, per tasks/
lessons.md's fleet rule): `git diff --cached` of the full chunk (all 7 touched/new files) saved to
a patch, `git checkout --`/`rm` reverted the tree to byte-identical pre-chunk state (confirmed via
`git status --porcelain` empty except for the untouched worktree baseline), pipeline suite
(`test_board_laws.py` + `test_d6_2_repair_stamps.py` + `test_coverage.py` + `test_d9_1_shot_
purpose.py`) back to 161/161 passing reverted, full backend suite (`./venv/bin/python -m pytest
tests/ -q`, main checkout's venv binary against worktree code) 29 failed / 3904 passed / 4 skipped
reverted — IDENTICAL to this chunk's own pre-change baseline capture, sorted FAILED-test-name sets
diffed byte-identical (empty diff) — then the patch forward-applied cleanly (`git apply`, no
conflicts) to restore the chunk; broader pipeline suite sweep (`tests/` minus two files with
pre-existing, unrelated collection errors on main) also diffed clean: same 18 failed/3 errors on
both main and this worktree, only the passed-count delta (+29) accounted for by this chunk's own
new tests. `schema.sql`'s `assets` table updated with the 3 new columns, comment cross-referencing
migration 148.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether Claude reliably follows the two new prompt rules (25/26) on a real, unseen scene, including
whether it gets the CAUSED_BY label format (`M<n>-MASTER`/`M<n>-ANGLE<k>`) syntactically right
without more than the prompt template as an example (prompt compliance is never provable from a
parser unit test — that's what step 4 above is for); real `assets.transition_kind`/
`continuity_bridge`/`caused_by` values landing from an actual paid coverage-picture draw; and
whether the D12-2 render-layer consumption of `transition_kind` (explicitly out of scope for this
chunk — data + warn checks only) will want the stored value in a different shape than "as
authored, lowercased" once that chunk is built.

---

## D11-1 professional shot-archetype library (branch `d11-1-archetypes`) — apply migration 149 on next deploy window; confirm ARCHETYPE rows actually show up in a real plan, and that the planner's chosen ids land in the catalog

**Built and tested in a worktree only — migration 149 was NOT applied to prod this session** (no
prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every prior
migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file error) —
the "deferred" part is confirming it actually landed AND that a real planner call actually emits
well-formed `ARCHETYPE: <id>` rows using ids that are IN `storyboard.shot_archetypes.
SHOT_ARCHETYPES` (a prompt-only change; no test in this chunk calls the real Claude API — the
whole point of rule 27 being OPTIONAL is the planner may simply never use it, which is fine, but
if it DOES use it, the id vocabulary needs to actually match):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
scripts/se.sh db "SELECT column_name FROM information_schema.columns WHERE table_name='assets' AND column_name='shot_archetype'"
# Expect one row back.

# 3. Generate a real scene's coverage directive (any normal chat/coverage-build flow) and read
#    the raw directive text (scripts/coverage_to_app.py writes it, or grab it from
#    scripts.coverage_directive on the scene row) — look for ARCHETYPE: rows under some of the
#    MASTER/ANGLE lines. Since rule 27 says "MAY", zero rows on any given scene is NOT a failure;
#    the interesting failure mode is an ARCHETYPE row present with an id NOT in
#    storyboard.shot_archetypes.SHOT_ARCHETYPES (the exact thing check_shot_archetype_valid warns
#    on — check the coverage-run logs for "⚠️ shot-archetype check (D11-1)" lines).

# 4. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and confirm
#    the column actually populates:
scripts/se.sh db "SELECT id, shot_type, shot_archetype FROM assets WHERE video_id='<vid>' AND scene=<n> ORDER BY image_index"
# Expect shot_archetype populated (non-NULL) for whichever shots the planner chose to tag — very
# likely a MINORITY of shots (optional, unlike PURPOSE/TRANSITION/CAUSED_BY), NULL is expected and
# fine for the rest.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d11_1_shot_archetype.py` (27 tests) covers catalog integrity
(`storyboard/shot_archetypes.py`: 45 unique ids across the six required categories — establishing/
coverage/detail/angle/composition/specialty — every required text field non-empty, every
`pairs_well_after` reference resolves to a real catalog id, `format_archetype_menu()` renders under
an 8000-char budget at 5799 chars/~1450 tokens actual, `get_archetype()` case/whitespace tolerant),
`parse_coverage`'s extraction of the per-shot `ARCHETYPE: <id>` row (lowercased, tolerant of bold,
correctly independent when stacked with PURPOSE/TRANSITION/CAUSED_BY in ANY order — same
latest-starting-candidate mechanism D9-6/D9-7 built, now handling four row types instead of three),
BACKWARD COMPATIBILITY against ALL THREE prior directive eras (legacy zero-metadata-row `SAMPLE`,
D9-1-era PURPOSE-only, D9-6/D9-7-era PURPOSE+TRANSITION+CAUSED_BY — all three byte-identical on
shot_type/description, shot_archetype simply None), the new WARN gate `check_shot_archetype_valid`
firing ONLY on an invalid catalog id — never on an absent one, since tagging is optional (unlike
every prior D9-1/D9-6/D9-7 "present" check), `generate_coverage_frames` threading shot_archetype
onto its frame dicts AND proof the id never reaches the actual image-generation prompt string,
`enforce_setup_variety`'s content-swap carrying shot_archetype along with shot_type/description/
purpose_kind/etc (same "travels with content, not position" judgment call as D9-1/D9-6/D9-7), and
`plan_moments_deterministic` preserving shot_archetype end to end including a floor-added filler
shot correctly landing with none. `storyengine/backend/tests/functional/test_d11_1_shot_archetype_
stamp.py` (3 tests, new) proves `store_scene`'s INSERT stamps `shot_archetype` from a frame dict's
field (present as the LAST positional param, NULL-default, independently per-shot within one
moment) — same "store_scene is the one real stamping site" reasoning as D9-1/D9-6/D9-7.
`storyengine/backend/tests/functional/test_d9_1_shot_purpose_stamp.py` (3 assertions) and
`test_d9_6_7_transition_causality_stamp.py` (4 assertions) were UPDATED (not left broken): this
chunk's migration 149 appends `shot_archetype` AFTER migration 148's caused_by in the INSERT's
column list, which shifted their hardcoded negative-index positional assertions off target by one
— caught by running both stamp tests after this chunk's change, fixed (`params[-5]`/`params[-4]` →
`params[-6]`/`params[-5]` for D9-1's; `params[-3]/-2/-1` → `params[-4]/-3/-2` for D9-6/D9-7's) with
comments explaining why, re-verified passing — same discipline D9-6/D9-7 itself used when it
shifted D9-1's stamp test the same way one migration earlier. Real stash-proof (patch-file
technique, never `git stash`, per tasks/lessons.md's fleet rule): `git diff --cached` of the full
chunk (9 touched/new files) saved to a patch, `git apply -R` reverted the tree to byte-identical
pre-chunk state (confirmed via `git status --short` empty), pipeline suite (`test_board_laws.py` +
`test_d6_2_repair_stamps.py` + `test_coverage.py` + `test_d9_1_shot_purpose.py` +
`test_d9_6_7_transition_causality.py`) back to 190/190 passing reverted, full backend suite
(`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against worktree code) 29
failed / 3946 passed / 4 skipped reverted — sorted FAILED-test-name sets diffed byte-identical
(empty diff) against this chunk's own applied-state run (29 failed / 3949 passed — the +3 delta is
exactly this chunk's own new `test_d11_1_shot_archetype_stamp.py` tests) — then the patch
forward-applied cleanly (`git apply`, no conflicts) to restore the chunk. `schema.sql`'s `assets`
table updated with the new `shot_archetype` column, comment cross-referencing migration 149.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether Claude ever spontaneously reaches for the ARCHETYPE row at all given it's purely optional
(rule 27 says "MAY", so a real planner might simply never use it — that's a legitimate outcome, not
a bug, but it also means the catalog's real-world value is unproven until a session watches actual
plans use it); whether the ids Claude picks, when it does tag a shot, cluster sensibly by category
or drift toward a handful of favorites; and whether `check_shot_archetype_valid`'s WARN-only
posture should be promoted to a hard gate once that track record exists (explicitly flagged as
hard-eligible under Ruling 1 in the check's own docstring, but promotion is a separate, deliberate
call, not automatic).

---

## D10-3a: coverage/board planner learns per-video narrative signal (branch `d10-3a-planner-narrative`) — eyeball a real native-bible board plan on next deploy window

**What changed:** `scripts/coverage_to_app.py`'s `scene_aware_bible()` now attaches `narrative`
(and `relationships`, if present) straight off `videos.story_bible` — a NEW, unconditional read
(`_story_bible_narrative_context`), separate from `_scene_locations`' story-bible fallback which
only fires when a video has no approved `video_environments` rows. The final `bible if (...) else
None` gate was widened to include `narrative`, so a video whose ONLY signal is narrative (no
locked characters, no environments) no longer collapses to `None`. A new pure formatter,
`_narrative_context_block`, renders that into a delimited `<narrative>...</narrative>` block
(genre/tone/themes/conflict/stakes/time_period/world_rules, plus one `<relationships>` line per
character pair when present); `_board_rules_text_with_narrative` composes it ahead of whatever
board-scoped `quality_rules` text a call already has. Both `scene_aware_bible()` call sites
(`generate_storyboard_sheet_for_scene` and `generate_coverage_for_video`) route their
`board_rules_text` argument to `generate_coverage_directive` through this helper — the ONE
free-text hook that reaches `storyboard/coverage.py`'s planner system prompt without editing that
file (out of scope for this chunk; BOARD LAWS coverage.py stays untouched). Call site 2 needed one
extra branch: when a scene has no saved plan (`directive is None`), `run_coverage`'s OWN internal
`generate_coverage_directive` call has no `board_rules_text` parameter at all, so for a
narrative-bearing bible the directive is now precomputed directly (same call shape as site 1)
before falling into `run_coverage`; for every bible without narrative, that branch never fires and
`directive_text` stays `None` exactly as before this chunk.

**What IS verified (code-level + a full local test suite pass, no real LLM call, $0):**
`storyengine/backend/tests/functional/test_d10_3a_planner_narrative.py` (37 tests) covers:
`_narrative_context_block` (empty/None/absent-key/empty-dict bible all render "", full narrative
renders every field, partial narrative omits absent fields, relationships render one line each and
are dropped when malformed or when narrative itself is empty); `_board_rules_text_with_narrative`
(narrative-first-then-rules composition, "" + "" => ""); `_story_bible_narrative_context` (NULL
column, missing row, legacy pre-D10-2ab dict, unparseable JSON string, non-object JSON, dict vs.
JSON-string column shapes, wrong-typed narrative/relationships); `scene_aware_bible()` end to end
(legacy video carries no `narrative`/`relationships` keys at all, a native video attaches both, a
narrative-only video — no characters, no environments — no longer returns `None`, a truly empty
video still returns `None`, an unparseable `story_bible` JSON string degrades to legacy behavior
without crashing). **THE key byte-identical proof** renders `storyboard.coverage`'s REAL
`_coverage_system_prompt`/`_coverage_user_prompt` (no mocks, no LLM call — both are pure string
builders, imported directly, `storyboard/coverage.py` itself untouched) against a legacy bible
fixture with and without this chunk's wrapper and asserts the two prompts are byte-identical,
across four bible/board-rules-text combinations (both absent, board-rules-only, legacy
characters+locations, and a bible carrying an explicit-but-empty `narrative: {}` section — the
degenerate-generation case). A companion test proves the `<narrative>` block, when present, sits
between `</channel_style>` and `<rules>` in that SAME real system prompt (the exact slot
`board_rules_block` already occupies today) and that narrative sorts ahead of quality-rule text
when both exist. Wiring proofs at both real call sites (`generate_coverage_for_video`,
`generate_storyboard_sheet_for_scene`, DB/Claude/ImageClient all mocked, the site-1 test exploits
`plan_moments_deterministic("")` returning `None` so the mocked empty directive short-circuits
before any image-drawing code runs — a genuinely $0 test) confirm: a native bible makes
`generate_coverage_directive` get called with `<narrative>`/`Genre: heist thriller` inside
`board_rules_text`; a legacy bible at call site 2 never calls `generate_coverage_directive` at all
(directive stays `None`, `run_coverage` plans internally exactly as it did before this chunk —
control-flow-level byte-identical, not just prompt-text-level); a legacy bible at call site 1
passes `board_rules_text=""` through unchanged. Real stash-proof (patch-file technique, never `git
stash`, per `tasks/lessons.md`'s fleet rule): `git diff` of `coverage_to_app.py` saved to a patch,
`git apply -R` reverted the tree to byte-identical pre-chunk state (`git status --porcelain` empty
except the new test file), and separately the new test file fails at COLLECTION
(`ImportError: cannot import name '_story_bible_narrative_context'`) on the reverted tree — the
loudest possible "before" signal. Full backend suite (`./venv/bin/python -m pytest tests/ -q`,
main checkout's venv binary against worktree code) run on both trees with the new test file
excluded for a fair comparison: 29 failed / 3930 passed (both reverted and applied), sorted
FAILED-test-name sets byte-identical (diffed, empty output) — the same pre-existing 29 failures
(`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`) as every other recent
D-series chunk. With the new test file included, applied: 29 failed / 3967 passed / 4 skipped.

**What is NOT verified — deploy-window check owed:**

### 1. A real board plan on a native-bible video, eyeballed via the $0(ish) dry-run path

No video in prod has a StoryEngine-native `story_bible` yet — D10-2ab (the generator that writes
`narrative`/`relationships`) landed the same day as this chunk and its own deferred-verification
entry above still owes a real generation. This chunk's `<narrative>` block has therefore never
been seen inside a REAL Claude-planner prompt, only in synthetic fixtures. Once D10-2ab's real
generation has run on a test video (owed by that chunk's own deploy-window check) and
`videos.story_bible` carries a non-empty `narrative` section, plan that video's board with
`plan_only=True` (`generate_storyboard_sheet_for_scene(..., plan_only=True)` — the D3-59 dry-run
path: plans and returns the shot list, persists nothing, draws no images) and confirm:
- The `<narrative>` block actually appears in the assembled system prompt sent to Claude (add a
  temporary print of `board_rules_text`, or inspect via a debugger/log — this repo has no existing
  "show me the raw prompt" endpoint for this call).
- The plan Claude returns actually reads as tonally/genre-consistent with the injected block (e.g.
  a "heist thriller, tense" narrative should visibly influence shot framing/pacing choices, not
  just sit inertly in the prompt) — a real qualitative read, not something a parser test can prove.
- `relationships` lines (when the bible has 2+ characters) don't crowd out or contradict the
  existing `VISUAL BIBLE` character block already in the same user prompt.

**Recipe:** after D10-2ab's real generation check has run and produced a native bible, `se db
"SELECT story_bible->'narrative' FROM videos WHERE id = '<video_id>'"` to confirm the column is
populated, then call the storyboard-planning entry point (`POST
/api/pipeline/{video_id}/scenes/{scene}/storyboard` or the equivalent chat/action verb) with
`plan_only=True` for one scene. **Cost: one Claude Sonnet call, ~$0.01-0.05** (per
`docs/cost-awareness.md`'s "Claude API (Sonnet)" line — `plan_only=True` draws zero images, so
this is the LLM-call-only cost, not the ~$0.05/board sheet-preview cost) — quote this and get a
yes before running it live.

---

## D10-3a addendum: call-site-2 precomputed-directive branch never persists (pre-existing gap, not a regression) — manager review finding

Manager review on D10-3a asked for a traced parity check between `run_coverage`'s two ways of
obtaining `directive_text` — planned internally (`directive_text=None`, the pre-existing path) vs.
precomputed by `generate_coverage_for_video`'s new fallback branch (this chunk, when the bible
carries narrative and no saved plan exists). Traced with quoted lines:

**(c) Post-parse warn checks — YES, identical either way.** `storyboard/coverage.py::run_coverage`
(`skills/video-pipeline/storyboard/coverage.py:3906-3925`):
```python
    if directive_text is None:
        directive_text = await generate_coverage_directive(
            beat_text, video_title, profile, story_bible, beat_scenes, image_prompts or [],
            max_moments=max_moments, angles_min=angles_min, angles_max=angles_max,
            anthropic_client=anthropic_client, model=directive_model)
    with open(os.path.join(outdir, "directive.txt"), "w") as f:
        f.write(directive_text)
    ...
    moments = plan_moments_deterministic(directive_text, max_moments, angles_max,
                                         max_frames=max_frames, verbose=True, props=props)
    if not moments:
        return {"error": "no moments parsed from directive", "directive_chars": len(directive_text)}
```
The `if directive_text is None:` check is the ONLY branch point — both the local `directive.txt`
file write immediately below it and every check that follows (`plan_moments_deterministic`'s own
"parse -> budget -> floors -> variety" pipeline, then `coverage.py:3927-3965`'s
`check_facing_law_compliance`, `check_headcount_stated`, `check_shot_purpose_present`,
`check_shot_transition_present`/`check_shot_transition_bridge_present`,
`check_shot_causality_present`/`check_shot_causality_valid`, and the rest of the BOARD LAWS gate
leg) run unconditionally on `directive_text`/`moments` regardless of which branch supplied it.
Setup variety is enforced inside `plan_moments_deterministic` itself (its own docstring: "parse ->
budget -> floors -> variety, in that exact order"), same unconditional call. Argument parity
confirmed too: `generate_coverage_for_video`'s new precomputed call
(`scripts/coverage_to_app.py`'s `if _narrative_board_text:` branch) passes the exact same
`beat_text`/`video_title`/`profile`/`story_bible`/`beat_scenes`/`max_moments`/`angles_min`/
`angles_max`/`anthropic_client`/`model` values `run_coverage`'s own internal call would have used
— `board_rules_text` is the only argument that differs (narrative text vs. the internal call's
implicit `""` default).

**(a) Persist the directive / (b) stamp `coverage_directive_hash` — NO, identical either way (a
PRE-EXISTING gap, not introduced by this chunk).** `run_coverage`'s own docstring
(`storyboard/coverage.py:3849-3850`): `"Saves frames + coverage.json locally with angle/shot-type
metadata. No DB writes (storing into Image records is Phase 2, where the animator consumes
them)."` — confirmed by grep: zero `await execute(...)` calls anywhere in `run_coverage`.
`generate_coverage_for_video`'s entire body (`scripts/coverage_to_app.py:4388-4729`) was swept the
same way — zero `UPDATE scripts` / `await execute(...)` calls touching `coverage_directive` or
`coverage_directive_hash` anywhere; the only DB write in that function is `store_scene`
(`scripts/coverage_to_app.py:732`, `"INSERT INTO assets (...)"`), a different table entirely. So
when this fallback branch fires (no saved plan for the scene — `directive is None` going in), the
resulting directive is NEVER written back to `scripts.coverage_directive`/`coverage_directive_hash`
— not by the pre-existing internal-planning path, and not by this chunk's new precomputed-directive
path. Contrast with call site 1 (`generate_storyboard_sheet_for_scene`), which DOES persist —
the STREAMING CONTRACT UPDATE (`scripts/coverage_to_app.py:2830-2837`):
```python
            if not plan_only:
                blocks = "\n\n".join(f"--- BEAT {i} ---\n{p}" for i, p in enumerate(prompts, start=1))
                await execute(
                    "UPDATE scripts SET coverage_directive=$1, coverage_directive_hash=$2, "
                    "storyboard_prompts=$3, storyboard_beat_count=$4, storyboard_1_url=NULL, "
                    "storyboard_2_url=NULL, storyboard_3_url=NULL, storyboard_4_url=NULL, "
                    "storyboard_5_url=NULL, storyboard_errors=NULL, updated_at=now() WHERE id=$5",
                    directive, _scene_text_hash(s["scene_text"] or ""), blocks, len(prompts), srow["id"])
```
which is exactly why call site 2's designed, gated flow is to plan via call site 1 first (its own
docstring, `generate_storyboard_sheet_for_scene:2450-2451`: "'Generate pictures' then executes THIS
EXACT saved plan (generate_coverage_for_video reuses it via coverage_directive)") — the fallback
this chunk touches only fires when that gate was bypassed (a scene that reached "Generate all
pictures" without ever going through the sheet-preview step).

**Consequence (unchanged by this chunk, quantified):** a scene that repeatedly hits this fallback
(no saved plan, every "Generate all pictures" call) re-runs a fresh Claude planning call EVERY TIME
— true before D10-3a (`run_coverage` planned internally, uncached, on every such call) and equally
true after (this chunk's precomputed call is equally uncached). This chunk does not add a new
re-spend; it relocates the SAME already-uncached spend so narrative can ride along on it.

**Why not fixed here:** adding persistence (an `UPDATE scripts SET coverage_directive=...,
coverage_directive_hash=...` in `generate_coverage_for_video`) would (1) be a real behavioral
change to the D3-59 plan_only / D7 staleness-hash contract, not a narrative-injection change —
outside this chunk's declared scope ("this chunk is coverage_to_app.py + tests only" meant the
narrative feature, not a persistence-model change); (2) directly touch the exact machinery three
OTHER active fleet workers on this same loop currently own (`d7-2-staleness`, `d7-3-invalidation`,
`d7-7-external-stale` — see their own entries above and `tasks/deferred-verification.md`'s D7-2/
D7-3 sections) — editing it here risks a merge collision or a silent contract disagreement with
their in-flight work; (3) site 1's UPDATE also nulls `storyboard_1_url..5_url`/`storyboard_errors`/
`storyboard_beat_count`, fields that mean nothing in call site 2's real-picture-draw context —
porting it naively would be semantically wrong, not a copy-paste fix. Flagging instead: this is a
good small follow-up chunk (persist the fallback-planned directive + hash in
`generate_coverage_for_video`, scoped and tested on its own, coordinated with whichever D7 worker
currently owns `coverage_directive_hash` semantics) — NOT bundled into D10-3a.

---

## D10-3d — channel profile doc: Story Bible narrative summary (2026-07-30)

**What shipped:** `backend/channel_profile_documents.py::_visual_generation_lines`
no longer treats `videos.story_bible` as an opaque string it blindly truncates
to 1800 chars. A new pure helper, `_story_bible_narrative_summary_lines(raw_bible)`,
parses the bible JSON and — only when a StoryEngine-native bible (D10-2ab) is
present with a non-empty `narrative` section (genre/tone/conflict/stakes) —
prepends a compact 1-2 line human-readable summary before the existing
truncated raw-JSON section. A legacy bible, an unparseable string, a non-dict
JSON value, or a freshly-normalized-but-empty `narrative` section all fall
through to today's exact byte-identical single-line output; the helper never
raises (wrapped in `try/except Exception: return []`). Tests:
`backend/tests/test_d10_3d_docs_narrative.py` (10 tests, pure-function
coverage over `_visual_generation_lines` and the new helper directly — no DB,
no network).

**Verification:** full backend suite (main venv binary
`storyengine/backend/venv/bin/python`, worktree code) run twice — reverted
(HEAD's `channel_profile_documents.py`, new test file moved out) and applied
— sorted `FAILED` test-name sets are byte-identical: 29 failures both runs,
same names, same order (`diff` empty). Applied run: 4005 passed / 29 failed /
4 skipped (exactly 10 more passing than reverted's 3995, matching the 10 new
tests added). Guard-neuter proof: forcing the summary helper to `return []`
unconditionally turned 3 of the new tests into real `AssertionError` failures
(the ones asserting a populated bible DOES get a summary); reverting the
neuter returned all 10 to green — proves the tests exercise real behavior,
not import/collection errors. No other test file in the suite references
`channel_profile_documents` — the "existing tests pass unmodified" checklist
item is vacuously satisfied (there were none before this chunk).

**Not touched, flagged for awareness:** `relationships`/`arcs` sections of
the native bible (also new in D10-2ab) are NOT summarized here — the brief
scoped this chunk to genre/tone/conflict/stakes only. A follow-up could add a
one-line "N characters, M relationships tracked" note the same way, if the
transparency-doc's audience (a customer inspecting their own channel's AI
inputs) wants that visibility too. Not blocking; small, isolated addition
if wanted later.

---

---

## D9-2 character-lock harvest (branch `d9-2-character-locks`) — apply migration 151 on next deploy window; RE-APPROVE a cast so the locks actually populate (populate-or-inert trap)

**Built and tested in a worktree only — migration 151 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every
prior migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file
error). Unlike D9-1/D9-6/D9-7/D11-1 (which harvest a planner-LLM tag that appears the next time
ANY scene is planned), this chunk's three columns populate ONLY at cast-APPROVAL time — every
existing character row has NULL locks today, and stays NULL forever unless its video's cast is
re-approved. The canonical branch in `load_character_bible`/`redraw_asset_image` never runs on a
single real video until that happens. The deploy-window recipe below MUST include a
re-approval step, not just a migration check:

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "151_character_locks"
# Expect: "Migration applied: 151_character_locks.sql"
se db "SELECT filename FROM _migrations WHERE filename = '151_character_locks.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'video_characters' \
  AND column_name IN ('face_body_lock', 'wardrobe_lock', 'forbidden_drift')"
# Expect 3 rows.

# 4. THE POPULATE-OR-INERT TRAP: confirm today's rows are NULL (expected, not a bug)
se db "SELECT id, name, face_body_lock, wardrobe_lock, forbidden_drift FROM video_characters \
  WHERE video_id='8d90df90-...' " # full id from tasks/ notes
# Expect all three NULL for every row — proves nothing yet, this is the baseline.

# 5. Re-approve that video's cast (Characters tab -> "Approve cast" again; this re-runs the
#    SAME vision pass that already exists in prod today, now with the extended prompt — no NEW
#    paid call is introduced, this is not an extra spend beyond what approval already costs).
#    Then re-check:
se db "SELECT id, name, face_body_lock, wardrobe_lock, forbidden_drift FROM video_characters \
  WHERE video_id='8d90df90-...'"
# Expect face_body_lock/wardrobe_lock populated for characters whose portrait vision call
# succeeded and followed the labeled format; forbidden_drift populated too (stored only, not
# consumed yet). A character with all three still NULL after this step means the vision reply
# didn't follow the labeled format that pass — check `se logs backend` for
# "[characters] D9-2 lock extraction partial for <name>" (this chunk's own warning) to confirm
# it degraded loudly rather than silently.

# 6. Plan (free) or draw (paid — confirm cost with Ryan first) that video's storyboard for a
#    scene with a locked character, and confirm the assembled CHARACTER block actually carries
#    the lock text verbatim. The D6-1 board-laws evidence at
#    tasks/evidence/d6-6a-dryrun/sheet-preview_scene1_*.txt shows this project already has a
#    free way to dump the assembled sheet-prompt text for review before any paid draw — reuse
#    that path for a scene with a re-approved character and grep the dump for the exact
#    face_body_lock/wardrobe_lock string stored in step 5. This is the one step this chunk could
#    not run itself (no live prod DB access from this Mac — see MEMORY.md's
#    "Backend loads env from storyengine/.env..." note) and is the strongest remaining proof gap:
#    every consumer of `costume`/`_identity_tag_or_locks` is unit-tested against synthetic rows,
#    but no test here proves a REAL re-approval's extracted text survives unchanged into a REAL
#    assembled prompt end to end.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`storyengine/backend/tests/functional/test_d9_2_character_locks.py` (24 tests) covers
`_parse_character_lock_reply` (full labeled reply, a reply missing one or more labels, a reply
that ignores the format entirely — parses to `{}`, never raises — multi-line values, case
insensitivity), `approve_cast`'s background task with the vision call stubbed: the happy path
writes all three lock columns AND `description` in exactly ONE `UPDATE` (proving the "one call,
not two" requirement at the SQL-write level, not just prompt level), a reply with no labels falls
back to the exact pre-D9-2 whole-reply-as-description behavior and writes zero lock columns, a
partial reply (some labels present, some missing) writes only the fields that parsed and leaves
the others untouched (not nulled — a deliberate choice so a transient miss on re-approval can't
erase a prior good extraction; documented in migration 151's own comment), a raising vision call
degrades exactly as fail-soft as the pre-existing description-refresh pass, and the no-Claude-
creds case skips the whole vision pass (zero calls) with approval still completing.
`scripts/coverage_to_app.py`'s consumer side: `_locks_text`/`_identity_tag_or_locks` (the two
helpers `load_character_bible` and `redraw_asset_image` now share) tested directly for every
precedence combination, `load_character_bible`'s SELECT proven to include the new columns, the
KEY backward-compat case (NULL locks -> costume falls back to description/identity_tag exactly as
before this migration, asserted byte-identical) plus the populated case (locks appear verbatim,
description text is provably absent from the result) plus the override case (a creator-set
identity_tag still wins over populated locks). `_character_identity_line` proven to render the
locks verbatim once they flow through the bible, and proven byte-identical on a NULL-locks
character. All 37 pre-existing tests in `test_characters.py` / `test_c4_prop_manifest.py` /
`test_money_safety_character_environment_metering.py` pass unmodified. Real stash-proof (checkout-
swap technique, never `git stash`, per tasks/lessons.md's fleet rule): after committing the chunk,
the 3 modified files were checked out back to their pre-chunk (`HEAD~1`) content and the 2 new
files (migration + test) moved out to the scratchpad, full backend suite
(`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against worktree code) run
reverted (29 failed / 3958 passed / 4 skipped), then the 3 files checked back out to `HEAD` and the
2 new files restored (`git diff --stat HEAD` empty, confirming byte-identical restoration) and the
suite run again applied (29 failed / 3982 passed / 4 skipped — the +24 delta is exactly this
chunk's own new test file). Sorted `FAILED` test-name sets diffed byte-identical (empty diff)
between reverted and applied. `schema.sql`'s `video_characters` table updated with the 3 new
columns and a comment cross-referencing migration 151 (note: `identity_tag`/`material_map` from
migration 142 were ALREADY missing from `schema.sql` before this chunk touched the table — a
pre-existing drift this chunk did not introduce and left alone, same class of gap D9-1's entry
above flagged for `assets.shot_location`/`group_arrangement`).

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether the extended vision prompt reliably produces the labeled format on a real, unseen portrait
(prompt compliance is never provable from a parser unit test — steps 5-6 above are what that's
for); a real re-approval's extracted face_body_lock/wardrobe_lock text surviving unchanged into a
REAL assembled board or final-picture prompt (step 6 — the strongest remaining gap, no live DB
access from this Mac); and whether the "identity_tag always wins over locks" precedence call
(this chunk's own judgment, not explicitly specified by the brief) is what Ryan actually wants
once a creator has both an authored identity_tag and freshly-extracted locks disagreeing — flagged
for a look at the next opportunity, not re-litigated silently.
successful post-repair rejudge; a raised exception from `write_findings_fn` never propagates out
of the hook and never skips a later sheet's own judge/repair pass). `test_d8_3_review_findings.py`
was extended for the endpoint's third query (per-instance rows, scoped to tenant_id + the
`_FINDING_INSTANCES_LIMIT` cap). Three real stash-proofs were run (patch-file technique, never
`git stash`, per tasks/lessons.md's fleet rule): (a) neutering `_finding_cost` to always return
`call_cost` broke the frame-station cost assertion with a real `AssertionError` (999.0 == 0.019
mismatch); (b) removing the `try/except` around the hook's write call let a simulated
`RuntimeError` propagate all the way out of `run_after_storyboard_sheet`, failing the test with
that real exception; (c) neutering `get_findings` to always return `instances=[]` broke the
endpoint shape test with a real `AssertionError` (`0 == 1`) — all three reverted immediately
after confirming. The full backend suite (`./venv/bin/python -m pytest tests/ -q`, main checkout's
venv binary against worktree code) passes 3867/3896 stashed-technique baseline vs applied — the
same pre-existing 29 failures (`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`),
sorted FAILED sets byte-identical (diffed, empty output, exit 0). Frontend: `npx tsc --noEmit`
clean, `npm run build` passes (34/34 static pages) once `frontend/node_modules` and
`frontend/.env.local` are present in the worktree — neither is git-tracked, so a fresh worktree
needs `npm install` (or a symlink to an existing checkout's `node_modules`) and a copy of
`.env.local` (or `scripts/se.sh devtoken`) before running the frontend checks; this was done
locally for verification and removed afterward, not committed. What is NOT verified: the
migration actually running against the real Supabase Postgres instance, any real per-instance row
from a live judge call (D8-2's first live run hasn't happened yet — that is the entire point this
chunk exists to protect), and a real browser walk of the Findings tab's new "Judged frames &
panels" section against live data.
## G1 — gatherer fallbacks: normalizer, NA/Wayback chain, source steering — 2026-07-30

Ported into `storyengine/backend/pipeline_executor.py::_gather_verified_machine_source_package`
from the DVsU research simulator (`storyengine/tasks/evidence/dvsu-research-simulator/
build_package.py`, untracked, main checkout only): (a) the tolerant `_normalized_source_text`
fold (citation markers, smart quotes/dashes, NBSP, orphan punctuation/hyphen spaces), (b) the
National Archives Discovery JSON API + real-Wayback-availability fallback chain (new capture
methods `national_archives_api` and `wayback:<url>`, threaded through
`_verified_source_candidate_traceable` and the `unsupported_capture_methods` quality gate via a
new shared `_is_approved_source_capture_method` helper), (c) source steering — every Tavily call
now sends `exclude_domains: ["iwm.org.uk", "www.iwm.org.uk"]`, plus one additional
`include_domains`-scoped call to `awm.gov.au / rmg.co.uk / gov.uk / naval-encyclopedia.com /
naval-history.net / uboat.net` when `_is_naval_gather_context(title, machine)` detects a
ship/naval machine from the video title or machine name.

Cost cap respected: every test (`storyengine/backend/tests/test_machine_documentary_hold.py`,
15 new tests) runs fully offline against a fake `httpx.AsyncClient` — no live Tavily, National
Archives, or Wayback calls were made this session. **What is NOT verified live:**

### 1. The real National Archives Discovery API and Wayback availability API were never called live
The retry-on-empty-202 logic and the Wayback `archived_snapshots` response shape are both typed
from the reference simulator's own hard-won notes (`STATE.md`: "National Archives API 202s when
cold — retry or sidecar") and from `build_package.py`'s working implementation, not from a fresh
live call this session. Recipe to confirm against the real APIs (no API key needed, both are
public/unauthenticated):
```bash
# National Archives Discovery record -> its own JSON API. Use any real record id, e.g. one
# already gathered in the simulator's raw/ directory, or search discovery.nationalarchives.gov.uk
# for a British WW2-era ship-file record and take the id from its /details/r/<ID> URL.
curl -s "https://discovery.nationalarchives.gov.uk/API/records/v1/details/<ID>" | head -c 500
# Expect: JSON (may be empty/202-shaped on a cold record — the pipeline retries 3x, 3s apart).

# Wayback availability API for a real URL known to be archived.
curl -s "http://archive.org/wayback/available?url=https://www.iwm.org.uk/collections/item/object/205211678"
# Expect: {"archived_snapshots": {"closest": {"url": "https://web.archive.org/web/...", ...}}}
```
If either shape has drifted from what's coded (e.g. NA now nests the payload differently, or the
availability API renamed a key), `_fetch_source_fallback_text`/`_wayback_snapshot_url` in
`pipeline_executor.py` need a matching update — the fixture-based tests would keep passing
(they pin the CODED shape) while the live path silently stopped working, so a periodic live
recipe re-run is worth keeping.

### 2. Not yet run through a real gather for a machine whose ONLY sources are behind the iwm.org.uk bot-wall
The Definition of Complete's "a machine whose best sources sit behind a bot-wall must still yield
a passing package" is proven at the unit/fixture level (traceable capture methods, exclude/
include domains wired correctly) but not end-to-end against a live video. Recipe once Ryan
authorizes a paid Tavily run: pick one of the DVsU carrier roster machines noted in
`dvsu-research-simulator/STATE.md` as gathered mostly from IWM-adjacent pages, clear its cached
`machine_raw_source_packages` entry, and re-run research through the pipeline's own API path —
confirm the resulting package's sources include at least one `national_archives_api` or
`wayback:` capture method and still passes `_verified_machine_source_package_quality_errors`.

### 3. `static_docu.py`'s "reference fetching" was investigated and deliberately NOT touched
The chunk brief named `static_docu.py`'s reference fetching alongside
`_gather_verified_machine_source_package` as a second port target. Read in full
(`storyengine/backend/static_docu.py:770-894`, `_host_reference` / `_gather_reference_candidates`):
it is a Wikimedia Commons IMAGE-reference fetcher for ship-roster PHOTOS, unrelated to the
text-excerpt research package — it never touches iwm.org.uk, awm.gov.au, rmg.co.uk,
naval-encyclopedia.com, naval-history.net, or uboat.net, and has no citation-marker/excerpt
normalization concern at all. Porting the three GAP-1 capabilities there would not address any
real failure mode in that code. Flagging instead of silently dropping: if Ryan wants a
Wayback-image fallback for `_host_reference` (e.g. when a Commons file 404s), that is a distinct,
separately-scoped follow-up, not part of this chunk's Definition of Complete.

---

## D9-1 shot-purpose harvest (branch `d9-1-shot-purpose`) — apply migration 147 on next deploy window; confirm the PURPOSE tag actually shows up in a real plan

**Built and tested in a worktree only — migration 147 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every
prior migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file
error) — the "deferred" part is confirming it actually landed AND that a real planner call
actually emits the new PURPOSE row (a prompt-only change; no test in this chunk calls the real
Claude API):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "147_shot_purpose"
# Expect: "Migration applied: 147_shot_purpose.sql"
se db "SELECT filename FROM _migrations WHERE filename = '147_shot_purpose.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'assets' \
  AND column_name IN ('purpose_kind', 'shot_purpose')"
# Expect 2 rows.

# 4. Plan ONE real scene's coverage (sheet-preview planning, no spend — Scenes page ->
#    "plan the shots" / plan_only path) and read the raw directive.txt/coverage_directive
#    back out:
se db "SELECT coverage_directive FROM scripts WHERE video_id='<id>' AND scene=<n>"
# Confirm the planner ACTUALLY wrote "PURPOSE: <kind> | <text>" rows under real MASTER/ANGLE
# lines — this chunk only proves the PARSER handles the tag correctly if the LLM writes it;
# it does not prove Claude reliably follows a brand-new prompt rule on its first live call.
# If PURPOSE rows are sparse/absent on a real plan, check_shot_purpose_present's WARN log line
# ("shot-purpose check (D9-1): ... carries no PURPOSE: line") should be showing up in
# `se logs backend` around that plan's generation — confirms the WARN gate itself is live,
# even if the prompt compliance needs a follow-up nudge.

# 5. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and
#    confirm the columns actually populate:
se db "SELECT scene, image_index, purpose_kind, shot_purpose FROM assets \
  WHERE video_id='<id>' AND scene=<n> AND generation_method='coverage' ORDER BY image_index"
# Expect purpose_kind/shot_purpose populated (non-NULL) for shots whose PURPOSE row survived
# step 4's plan, NULL for any shot the planner didn't tag (floor-added REACTION/INSERT shots,
# or a plain miss) — NULL here is not itself a bug, see step 4.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d9_1_shot_purpose.py` (11 tests) covers `parse_coverage`'s
extraction of the per-shot `PURPOSE: <kind> | <text>` row (master and angle independently, bold
markdown tolerated, kind lowercased), the row never surviving into the stored `description` (the
whole reason it lives on its own line — rule 23/L27, INSTRUCTIONS ARE NOT CAPTIONS), BACKWARD
COMPATIBILITY against `SAMPLE` — the exact pre-existing fixture `test_coverage.py` already used
before this chunk — parsing byte-identical on `shot_type`/`description` with purpose fields simply
`None`, the new `check_shot_purpose_present` WARN gate (silent when every shot is tagged, flags
exactly the untagged ones, flags all 5 shots on the legacy `SAMPLE` fixture with no crash),
`generate_coverage_frames` threading `purpose_kind`/`shot_purpose` onto its frame dicts AND proof
the purpose text never reaches the actual image-generation prompt string (a planted marker string
in `shot_purpose` is asserted absent from the prompt `_gen_ref` receives), `enforce_setup_variety`'s
content-swap carrying purpose fields along with `shot_type`/`description` (so a swap never leaves
a shot's stated purpose describing a framing that moved elsewhere), and `plan_moments_deterministic`
(the ONE shared parse->budget->floors->variety pipeline both the sheet-preview planning path and
the real-pictures path call) preserving purpose fields end to end including a floor-added filler
shot correctly landing with none. `storyengine/backend/tests/functional/
test_d9_1_shot_purpose_stamp.py` (3 tests) proves `store_scene`'s INSERT actually stamps
`purpose_kind`/`shot_purpose` from a frame dict's fields (present, NULL-default, and independently
per-shot within one moment) — the sheet-preview planning path never inserts an asset row at all
("Storyboard SHEETS are a preview, not an asset row" is coverage_to_app.py's own comment, confirmed
by reading it — nothing to stamp there), so `store_scene` is the one real stamping site and both
paths feed it identical parsed fields via the shared `plan_moments_deterministic`. Real stash-proof
(patch-file technique, never `git stash`, per tasks/lessons.md's fleet rule): `git diff --cached`
of the full chunk saved to a patch, reverse-applied cleanly (`git apply -R`, working tree confirmed
clean after), pipeline suite (`test_board_laws.py` + `test_d6_2_repair_stamps.py` + `test_coverage.py`)
still 150/150 passing reverted (new D9-1 test files gone with the revert, no orphaned failures),
full backend suite (`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against
worktree code) 29 failed / 3867 passed reverted vs 29 failed / 3882 passed applied (the +15 are
this chunk's own new tests) — sorted FAILED sets byte-identical (diffed, empty output), then the
patch forward-applied cleanly to restore the chunk. `schema.sql`'s `assets` table updated with the
2 new columns (with a note: `assets.shot_location`/`assets.group_arrangement` from migration 143
were ALREADY missing from `schema.sql` before this chunk touched it — a pre-existing drift, not
something this chunk introduced or fixed; flagged separately, not folded into this migration).
What is NOT verified: the migration actually running against the real Supabase Postgres instance,
whether Claude reliably follows the new PURPOSE-row prompt rule on a real, unseen scene (prompt
compliance is never provable from a parser unit test — that's what step 4 above is for), and a
real `assets.purpose_kind`/`shot_purpose` value landing from an actual paid coverage-picture draw.

---

## D10-2ab: StoryEngine-native Story Bible generator (backend/story_bible_native.py)

**What changed:** `PipelineExecutor.run_story_bible` no longer imports the legacy
`storyboard.bot._generate_story_bible_for_storyboard` (a sys.path reach into
`skills/video-pipeline`) or persists through the Airtable-shim
`supabase_adapter.update_idea_fields`. It now calls a new backend-native module
(`story_bible_native.generate_story_bible_native`, ONE extended Claude call via the same
`self._pipeline.anthropic` bridge every other `run_*` step already uses) and persists with a
direct, tenant-scoped `UPDATE videos SET story_bible = $1 WHERE id = $2 AND tenant_id = $3`. The
document schema is unchanged for consumers (`characters`/`locations`/`scene_blocks`, matching the
legacy V2 normalizer field-for-field) plus three new top-level sections (`narrative`,
`relationships`, `arcs`) that dangling-reference-validate against the same generation's character
ids and drop bad refs with a logged warning rather than failing generation.

**What IS verified (code-level + a full local test suite pass, no real LLM call, $0):**
`storyengine/backend/tests/test_story_bible_native.py` (22 tests, pure module — no DB, no
PipelineExecutor) covers the ported normalizer defaults for characters/locations/scene_blocks
(costume/description fallback, first-image-forced-wide, location lookup by id, image-count and
consecutive-same-location warnings that never abort generation), the three new sections'
defaults, and dangling-character-id drops for both `relationships` and `arcs` (asserted via
`capsys`, never a raised exception). `storyengine/backend/tests/test_d10_2ab_run_story_bible.py`
(9 tests) covers the wiring: scripts are fetched tenant-scoped by `video_id`, the persisted
UPDATE query text and args are tenant-scoped and match the full generated document byte-for-byte
after a JSON round trip, and every failure path (Claude raises, no script rows, missing Anthropic
client, unparseable response, video not found) returns `status: "failed"` with zero writes to
`videos.story_bible` and never logs `bot_activity` as `"completed"`. `tests/functional/
test_characters.py` and `tests/functional/test_c66_production_guide.py` (the two named
"unaffected consumer" checks) pass unmodified. Two real stash-proofs were run (patch-file
technique, never `git stash`, per tasks/lessons.md's fleet rule): the full backend suite
(`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against worktree code) was
run BOTH on the reverted tree (`git checkout -- pipeline_executor.py` + the three new files moved
out of the tree, restored via `git apply` on a saved patch afterward) and on the applied tree —
29 failed / 3886 passed (reverted) vs 29 failed / 3908 passed (applied, +22 for the new test
files), sorted FAILED sets byte-identical (diffed, empty output, exit 0) — the same pre-existing
29 failures (`test_custom_film_remotion.py`, `test_youtube_oauth_diagnostics.py`) as every other
recent D-series chunk.

**What is NOT verified — deploy-window check owed:**

### 1. A real Story Bible generation on a test video with a live Claude call

No live LLM call was made (every test above stubs `self._pipeline.anthropic`). Before this ships
to a real customer's build, run one real generation end to end and confirm:
- The new `narrative`/`relationships`/`arcs` sections are actually present and sensible on a
  REAL script (not just the hand-written fixture the tests use) — in particular, whether Claude
  reliably keeps `relationships`/`arcs` character ids matching `characters` ids without the
  dangling-ref dropper silently emptying them out on a real generation.
- `scene_blocks` total image count roughly matches the requested `total_images` (a mismatch only
  warns, never fails — worth eyeballing on a real script rather than assuming the model complies).
- The downstream legacy consumers (`routes/characters.py`'s bible<->cast sync,
  `scripts/coverage_to_app.py`'s `_story_bible_locations`, `channel_profile_documents.py`) render
  correctly against a bible that now has 3 extra top-level keys they've never seen live before.
- `run_storyboard_prompts` (still on the legacy `storyboard/run.py` path, untouched by this
  chunk) does NOT regenerate its own bible when one from this native path is already persisted —
  confirm `videos.story_bible` is non-empty after `run_story_bible` so its own
  `_generate_story_bible_for_storyboard` fallback never fires.

**Recipe:** pick a test video already past scripting (`ready_for_storyboards` or earlier, with
scripted scenes), call `POST /api/pipeline/{video_id}/story-bible` (or the equivalent chat/action
verb) once, then `se db "SELECT story_bible FROM videos WHERE id = '<video_id>'"` and eyeball the
JSON. **Cost: one Claude Sonnet call, ~$0.02-0.05** (per docs/cost-awareness.md's "Claude API
(Sonnet) ~$0.01-0.05/call" line — no image/video/voice spend, this step is text-only) — quote
this and get a yes before running it live.

---

## D9-6/D9-7 transition + causality harvest (branch `d9-67-transitions`) — apply migration 148 on next deploy window; confirm TRANSITION/CAUSED_BY rows actually show up in a real plan

**Built and tested in a worktree only — migration 148 was NOT applied to prod this session** (no
prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every prior
migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file error) —
the "deferred" part is confirming it actually landed AND that a real planner call actually emits
the new TRANSITION/CAUSED_BY rows (a prompt-only change; no test in this chunk calls the real
Claude API):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "148_shot_transition_causality"
# Expect: "Migration applied: 148_shot_transition_causality.sql"
se db "SELECT filename FROM _migrations WHERE filename = '148_shot_transition_causality.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'assets' \
  AND column_name IN ('transition_kind', 'continuity_bridge', 'caused_by')"
# Expect 3 rows.

# 4. Plan ONE real scene's coverage (sheet-preview planning, no spend — Scenes page ->
#    "plan the shots" / plan_only path) and read the raw directive.txt/coverage_directive
#    back out:
se db "SELECT coverage_directive FROM scripts WHERE video_id='<id>' AND scene=<n>"
# Confirm the planner ACTUALLY wrote "TRANSITION: <kind> | <bridge>" and "CAUSED_BY: M<n>-..."
# rows under real MASTER/ANGLE lines, in ADDITION to D9-1's PURPOSE rows — this chunk only
# proves the PARSER handles the two new tags correctly if the LLM writes them; it does not
# prove Claude reliably follows two brand-new prompt rules (25/26) stacked on top of an
# existing one (24) on its first live call, or that it correctly derives the M<n>-MASTER/
# M<n>-ANGLE<k> label format for a CAUSED_BY reference without being shown a worked example
# beyond the prompt's own template. If TRANSITION/CAUSED_BY rows are sparse/absent/malformed
# on a real plan, the four new WARN log lines ("shot-transition check (D9-6): ...", "shot-
# transition-bridge check (D9-6): ...", "shot-causality check (D9-7): ...") should be showing
# up in `se logs backend` around that plan's generation — confirms the WARN gates themselves
# are live, even if prompt compliance needs a follow-up nudge. Pay particular attention to
# whether Claude gets the CAUSED_BY label format right (M<n>-MASTER / M<n>-ANGLE<k>) — this is
# the one place this chunk asks the planner to do something more structured than free prose,
# and check_shot_causality_valid's "does this label exist / is it earlier" check depends on it
# being syntactically exact.

# 5. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and
#    confirm the columns actually populate:
se db "SELECT scene, image_index, transition_kind, continuity_bridge, caused_by FROM assets \
  WHERE video_id='<id>' AND scene=<n> AND generation_method='coverage' ORDER BY image_index"
# Expect transition_kind/caused_by populated (non-NULL) for shots whose rows survived step 4's
# plan, continuity_bridge populated only for a non-continuous/non-opening kind that stated one,
# NULL for any shot the planner didn't tag (floor-added REACTION/INSERT shots, or a plain miss,
# or the scene's true first shot for caused_by specifically) — NULL here is not itself a bug,
# see step 4.
```

**Grammar decision (documented here since it drives what step 4 above needs to confirm):** TWO
separate trailing rows, `TRANSITION: <kind> | <bridge>` (rule 25) and `CAUSED_BY: <label>` (rule
26) — not folded into one row, and not folded into D9-1's PURPOSE row. Each is independently
optional, independently gated by its own warn check(s), and Custom Film itself keeps
transition_from_previous/continuity_bridge and caused_by as separate ShotDraft fields — combining
them would conflate distinct warn conditions behind one piece of text for no reduction in grammar
surface. CAUSED_BY carries a SINGLE reference (not a tuple like Custom Film's `caused_by`): the
flagship grammar has no LLM-assigned `shot_key` the way ShotDraft does, so the reference format
taught here is a label the planner can derive purely from context already on the page —
`M<moment_number>-MASTER` / `M<moment_number>-ANGLE<k>` — never a running global shot count it
would have to track across the whole scene; one clear reference is more likely to be authored
correctly than a list the planner has to keep internally consistent.

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d9_6_7_transition_causality.py` (29 tests) covers `parse_
coverage`'s extraction of the per-shot `TRANSITION: <kind> | <bridge>` row (bridge optional,
omitted entirely for "continuous") and `CAUSED_BY: <label>` row, independently and together with
D9-1's PURPOSE row IN ANY ORDER the planner writes them (the decisive robustness property: a
naive "check PURPOSE first" scan let PURPOSE's own `.+?` capture swallow trailing TRANSITION/
CAUSED_BY rows whole before the fix — `_strip_shot_metadata_rows` now picks whichever candidate
regex match starts LATEST in the current text each pass, peeling the true tail row first
regardless of which of the three it is), the rows never surviving into the stored `description`,
BACKWARD COMPATIBILITY against BOTH the legacy zero-metadata-row `SAMPLE` fixture (byte-identical
shot_type/description, all five fields None) AND a synthesized D9-1-era fixture (PURPOSE rows
present, TRANSITION/CAUSED_BY absent — the real shape of every plan generated between D9-1
landing and this chunk landing), the four new WARN gates (`check_shot_transition_present`,
`check_shot_transition_bridge_present` — including the "opening" exemption alongside
"continuous", a deliberate refinement over the task brief's literal wording to faithfully mirror
Custom Film's own model where an opening shot structurally never carries a bridge —
`check_shot_causality_present`, `check_shot_causality_valid` — nonexistent-reference, forward-
reference, and self-reference all correctly flagged, a correct earlier reference correctly
silent), `generate_coverage_frames` threading all three new fields onto its frame dicts AND proof
the bridge/caused_by text never reaches the actual image-generation prompt string (planted marker
strings in both fields asserted absent from the prompt `_gen_ref` receives), `enforce_setup_
variety`'s content-swap carrying transition_kind/continuity_bridge/caused_by along with shot_type/
description/purpose_kind/shot_purpose (documented judgment call: these three describe WHY/HOW a
specific piece of content cuts in and what it follows from, not a fact about the position it
occupies, so they travel with content on a swap exactly like D9-1's purpose fields do — a known
residual: since caused_by is a positional LABEL and enforce_setup_variety only trades within the
same/adjacent moment, a swap can in rare cases leave a shot's caused_by pointing at itself or at
the position it just vacated; `check_shot_causality_valid` catches this post-swap as an ordinary
warn, by design, rather than needing a special case), and `plan_moments_deterministic` (the ONE
shared parse->budget->floors->variety pipeline both the sheet-preview and real-pictures paths
call) preserving all fields end to end including a floor-added filler shot correctly landing with
none. `storyengine/backend/tests/functional/test_d9_6_7_transition_causality_stamp.py` (4 tests)
proves `store_scene`'s INSERT stamps `transition_kind`/`continuity_bridge`/`caused_by` from a
frame dict's fields (present, NULL-default, independently per-shot within one moment, and a
non-continuous kind WITH a bridge stamping both) — same "store_scene is the one real stamping
site" reasoning as D9-1 (re-confirmed by re-reading coverage_to_app.py, nothing changed about
that). `storyengine/backend/tests/functional/test_d9_1_shot_purpose_stamp.py` was UPDATED (not
left broken): this chunk's migration 148 appends three columns AFTER migration 147's purpose_kind/
shot_purpose in the INSERT's column list, which shifted D9-1's own hardcoded `params[-2]`/
`params[-1]` positional assertions off target (they silently started reading continuity_bridge/
caused_by instead, or in one case still passed by coincidence since both new-and-old values were
None) — caught by running D9-1's stamp test after this chunk's change, fixed to `params[-5]`/
`params[-4]` (and `[-5:-3]` for the two-shots-in-one-moment test) with a comment explaining why,
re-verified passing. Real stash-proof (patch-file technique, never `git stash`, per tasks/
lessons.md's fleet rule): `git diff --cached` of the full chunk (all 7 touched/new files) saved to
a patch, `git checkout --`/`rm` reverted the tree to byte-identical pre-chunk state (confirmed via
`git status --porcelain` empty except for the untouched worktree baseline), pipeline suite
(`test_board_laws.py` + `test_d6_2_repair_stamps.py` + `test_coverage.py` + `test_d9_1_shot_
purpose.py`) back to 161/161 passing reverted, full backend suite (`./venv/bin/python -m pytest
tests/ -q`, main checkout's venv binary against worktree code) 29 failed / 3904 passed / 4 skipped
reverted — IDENTICAL to this chunk's own pre-change baseline capture, sorted FAILED-test-name sets
diffed byte-identical (empty diff) — then the patch forward-applied cleanly (`git apply`, no
conflicts) to restore the chunk; broader pipeline suite sweep (`tests/` minus two files with
pre-existing, unrelated collection errors on main) also diffed clean: same 18 failed/3 errors on
both main and this worktree, only the passed-count delta (+29) accounted for by this chunk's own
new tests. `schema.sql`'s `assets` table updated with the 3 new columns, comment cross-referencing
migration 148.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether Claude reliably follows the two new prompt rules (25/26) on a real, unseen scene, including
whether it gets the CAUSED_BY label format (`M<n>-MASTER`/`M<n>-ANGLE<k>`) syntactically right
without more than the prompt template as an example (prompt compliance is never provable from a
parser unit test — that's what step 4 above is for); real `assets.transition_kind`/
`continuity_bridge`/`caused_by` values landing from an actual paid coverage-picture draw; and
whether the D12-2 render-layer consumption of `transition_kind` (explicitly out of scope for this
chunk — data + warn checks only) will want the stored value in a different shape than "as
authored, lowercased" once that chunk is built.

---

## D11-1 professional shot-archetype library (branch `d11-1-archetypes`) — apply migration 149 on next deploy window; confirm ARCHETYPE rows actually show up in a real plan, and that the planner's chosen ids land in the catalog

**Built and tested in a worktree only — migration 149 was NOT applied to prod this session** (no
prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every prior
migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file error) —
the "deferred" part is confirming it actually landed AND that a real planner call actually emits
well-formed `ARCHETYPE: <id>` rows using ids that are IN `storyboard.shot_archetypes.
SHOT_ARCHETYPES` (a prompt-only change; no test in this chunk calls the real Claude API — the
whole point of rule 27 being OPTIONAL is the planner may simply never use it, which is fine, but
if it DOES use it, the id vocabulary needs to actually match):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
scripts/se.sh db "SELECT column_name FROM information_schema.columns WHERE table_name='assets' AND column_name='shot_archetype'"
# Expect one row back.

# 3. Generate a real scene's coverage directive (any normal chat/coverage-build flow) and read
#    the raw directive text (scripts/coverage_to_app.py writes it, or grab it from
#    scripts.coverage_directive on the scene row) — look for ARCHETYPE: rows under some of the
#    MASTER/ANGLE lines. Since rule 27 says "MAY", zero rows on any given scene is NOT a failure;
#    the interesting failure mode is an ARCHETYPE row present with an id NOT in
#    storyboard.shot_archetypes.SHOT_ARCHETYPES (the exact thing check_shot_archetype_valid warns
#    on — check the coverage-run logs for "⚠️ shot-archetype check (D11-1)" lines).

# 4. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and confirm
#    the column actually populates:
scripts/se.sh db "SELECT id, shot_type, shot_archetype FROM assets WHERE video_id='<vid>' AND scene=<n> ORDER BY image_index"
# Expect shot_archetype populated (non-NULL) for whichever shots the planner chose to tag — very
# likely a MINORITY of shots (optional, unlike PURPOSE/TRANSITION/CAUSED_BY), NULL is expected and
# fine for the rest.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d11_1_shot_archetype.py` (27 tests) covers catalog integrity
(`storyboard/shot_archetypes.py`: 45 unique ids across the six required categories — establishing/
coverage/detail/angle/composition/specialty — every required text field non-empty, every
`pairs_well_after` reference resolves to a real catalog id, `format_archetype_menu()` renders under
an 8000-char budget at 5799 chars/~1450 tokens actual, `get_archetype()` case/whitespace tolerant),
`parse_coverage`'s extraction of the per-shot `ARCHETYPE: <id>` row (lowercased, tolerant of bold,
correctly independent when stacked with PURPOSE/TRANSITION/CAUSED_BY in ANY order — same
latest-starting-candidate mechanism D9-6/D9-7 built, now handling four row types instead of three),
BACKWARD COMPATIBILITY against ALL THREE prior directive eras (legacy zero-metadata-row `SAMPLE`,
D9-1-era PURPOSE-only, D9-6/D9-7-era PURPOSE+TRANSITION+CAUSED_BY — all three byte-identical on
shot_type/description, shot_archetype simply None), the new WARN gate `check_shot_archetype_valid`
firing ONLY on an invalid catalog id — never on an absent one, since tagging is optional (unlike
every prior D9-1/D9-6/D9-7 "present" check), `generate_coverage_frames` threading shot_archetype
onto its frame dicts AND proof the id never reaches the actual image-generation prompt string,
`enforce_setup_variety`'s content-swap carrying shot_archetype along with shot_type/description/
purpose_kind/etc (same "travels with content, not position" judgment call as D9-1/D9-6/D9-7), and
`plan_moments_deterministic` preserving shot_archetype end to end including a floor-added filler
shot correctly landing with none. `storyengine/backend/tests/functional/test_d11_1_shot_archetype_
stamp.py` (3 tests, new) proves `store_scene`'s INSERT stamps `shot_archetype` from a frame dict's
field (present as the LAST positional param, NULL-default, independently per-shot within one
moment) — same "store_scene is the one real stamping site" reasoning as D9-1/D9-6/D9-7.
`storyengine/backend/tests/functional/test_d9_1_shot_purpose_stamp.py` (3 assertions) and
`test_d9_6_7_transition_causality_stamp.py` (4 assertions) were UPDATED (not left broken): this
chunk's migration 149 appends `shot_archetype` AFTER migration 148's caused_by in the INSERT's
column list, which shifted their hardcoded negative-index positional assertions off target by one
— caught by running both stamp tests after this chunk's change, fixed (`params[-5]`/`params[-4]` →
`params[-6]`/`params[-5]` for D9-1's; `params[-3]/-2/-1` → `params[-4]/-3/-2` for D9-6/D9-7's) with
comments explaining why, re-verified passing — same discipline D9-6/D9-7 itself used when it
shifted D9-1's stamp test the same way one migration earlier. Real stash-proof (patch-file
technique, never `git stash`, per tasks/lessons.md's fleet rule): `git diff --cached` of the full
chunk (9 touched/new files) saved to a patch, `git apply -R` reverted the tree to byte-identical
pre-chunk state (confirmed via `git status --short` empty), pipeline suite (`test_board_laws.py` +
`test_d6_2_repair_stamps.py` + `test_coverage.py` + `test_d9_1_shot_purpose.py` +
`test_d9_6_7_transition_causality.py`) back to 190/190 passing reverted, full backend suite
(`./venv/bin/python -m pytest tests/ -q`, main checkout's venv binary against worktree code) 29
failed / 3946 passed / 4 skipped reverted — sorted FAILED-test-name sets diffed byte-identical
(empty diff) against this chunk's own applied-state run (29 failed / 3949 passed — the +3 delta is
exactly this chunk's own new `test_d11_1_shot_archetype_stamp.py` tests) — then the patch
forward-applied cleanly (`git apply`, no conflicts) to restore the chunk. `schema.sql`'s `assets`
table updated with the new `shot_archetype` column, comment cross-referencing migration 149.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether Claude ever spontaneously reaches for the ARCHETYPE row at all given it's purely optional
(rule 27 says "MAY", so a real planner might simply never use it — that's a legitimate outcome, not
a bug, but it also means the catalog's real-world value is unproven until a session watches actual
plans use it); whether the ids Claude picks, when it does tag a shot, cluster sensibly by category
or drift toward a handful of favorites; and whether `check_shot_archetype_valid`'s WARN-only
posture should be promoted to a hard gate once that track record exists (explicitly flagged as
hard-eligible under Ruling 1 in the check's own docstring, but promotion is a separate, deliberate
call, not automatic).


## D11-2: per-shot DP (director of photography) fields as structured data (migration 150)

**What is deferred:** live proof that the coverage planner (Claude, via the coverage system
prompt) actually writes the new OPTIONAL `DP: <lens_mm> | <camera_height> | <dof>` row (rule 28)
on a real scene, and that `check_shot_dp_valid`'s WARN gate fires correctly against whatever
Claude actually writes — a prompt-only change; no test in this chunk calls the real Claude API,
mirroring exactly the deferred-verification gap D11-1 (ARCHETYPE) logged one chunk earlier. Rule
28 being OPTIONAL means the planner may simply never use it, which is fine — but if it DOES, the
lens_mm/camera_height/dof vocabulary needs to actually match what the checker enforces:

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
scripts/se.sh db "SELECT column_name FROM information_schema.columns WHERE table_name='assets' AND column_name IN ('lens_mm','camera_height','dof')"
# Expect three rows back.

# 3. Generate a real scene's coverage directive (any normal chat/coverage-build flow) and read
#    the raw directive text (scripts/coverage_to_app.py writes it, or grab it from
#    scripts.coverage_directive on the scene row) — look for DP: rows under some of the
#    MASTER/ANGLE lines (and their PURPOSE/TRANSITION/CAUSED_BY/ARCHETYPE siblings, if present).
#    Since rule 28 says "MAY", zero rows on any given scene is NOT a failure; the interesting
#    failure mode is a DP row present with a camera_height/dof word NOT in
#    storyboard.coverage.CAMERA_HEIGHT_KINDS/DOF_KINDS, or a lens value outside 10-200mm or not
#    shaped like "<digits>mm" (the exact things check_shot_dp_valid warns on — check the
#    coverage-run logs for "⚠️ shot-DP check (D11-2)" lines).

# 4. Draw that same scene's real pictures (spend gate — confirm cost with Ryan first) and confirm
#    the columns actually populate:
scripts/se.sh db "SELECT id, shot_type, lens_mm, camera_height, dof FROM assets WHERE video_id='<vid>' AND scene=<n> ORDER BY image_index"
# Expect lens_mm/camera_height/dof populated (non-NULL) for whichever shots the planner chose to
# tag — very likely a MINORITY of shots (optional, unlike PURPOSE/TRANSITION/CAUSED_BY), NULL is
# expected and fine for the rest. A shot may carry only SOME of the three (e.g. lens_mm set,
# camera_height/dof NULL) — that's the taught grammar working as designed, not a bug.
```

**What IS verified (code-level + full local test suite passes, not live prod):**
`skills/video-pipeline/tests/test_d11_2_shot_dp.py` (28 tests, new) covers the vocabulary
constants (`CAMERA_HEIGHT_KINDS` = ground/low/waist/chest/eye/high/overhead, `DOF_KINDS` =
shallow/medium/deep, `DP_LENS_MIN_MM`/`DP_LENS_MAX_MM` = 10/200), `parse_coverage`'s extraction of
the per-shot `DP: <lens_mm> | <camera_height> | <dof>` row — each of the three pipe-separated
slots independently optional (lens-only with no pipes at all, middle slot skipped but its pipe
kept, only the first slot populated, etc), tolerant of bold/case, correctly independent when
stacked with PURPOSE/TRANSITION/CAUSED_BY/ARCHETYPE in ANY order (same latest-starting-candidate
mechanism D9-6/D9-7/D11-1 built, now handling five row types instead of four), BACKWARD
COMPATIBILITY against ALL FOUR prior directive eras (legacy zero-metadata-row `SAMPLE`, D9-1-era
PURPOSE-only, D9-6/D9-7-era PURPOSE+TRANSITION+CAUSED_BY, D11-1-era +ARCHETYPE — all four
byte-identical on shot_type/description, lens_mm/camera_height/dof simply None), the new WARN gate
`check_shot_dp_valid` firing on an out-of-range lens (parsed but outside 10-200mm), a MALFORMED
lens value (text present but not shaped like "<digits>mm" — proven to not silently vanish to a
false "nothing written" None), an out-of-vocabulary camera_height, an out-of-vocabulary dof, and
all three independently on one shot (3 separate warnings, not 1 merged one) — never on an absent
row/slot, since the whole row is optional (unlike every prior D9-1/D9-6/D9-7 "present" check),
`generate_coverage_frames` threading lens_mm/camera_height/dof onto its frame dicts AND proof none
of the three (nor the literal "DP" label) ever reaches the actual image-generation prompt string,
`enforce_setup_variety`'s content-swap carrying all three DP fields along with shot_type/
description/purpose_kind/shot_archetype/etc (same "travels with content, not position" judgment
call as D9-1/D9-6/D9-7/D11-1), and `plan_moments_deterministic` preserving all three end to end
including a floor-added filler shot correctly landing with none.
`storyengine/backend/tests/functional/test_d11_2_shot_dp_stamp.py` (4 tests, new) proves
`store_scene`'s INSERT stamps lens_mm/camera_height/dof from a frame dict's fields (NULL-default,
independently per-shot within one moment, and a PARTIAL row — only one of the three slots stated —
stamps that one value with the other two staying NULL rather than getting invented) — same
"store_scene is the one real stamping site" reasoning as D9-1/D9-6/D9-7/D11-1, written name-keyed
via `_param_index` from the start (see below) rather than a positional index that would break on
the next chunk's trailing column.

**Stamp-test fragility fix (explicitly asked for in this chunk's brief):**
`test_d9_1_shot_purpose_stamp.py`, `test_d9_6_7_transition_causality_stamp.py`, and
`test_d11_1_shot_archetype_stamp.py` each shipped with a HARDCODED negative-index positional
assertion (`params[-6]`, `params[-4]`, `params[-1]`, etc) into `store_scene`'s INSERT params tuple
— three chunks running (D9-6/D9-7, D11-1, and now D11-2) each broke a different one of these files
by appending trailing columns after the ones the file was asserting on, requiring a manual
index-math fix every time. This chunk converts all three (plus the new D11-2 stamp test, written
name-keyed from the start) to compute a column's position from the INSERT's own column-name text
(which `_insert_columns()` already re-read from source for a `"X" in cols` sanity check) via a new
shared-shape `_column_names()` + `_param_index(name)` pair, duplicated per-file (matching the
existing per-file duplication convention rather than introducing a new shared test-util import).
`_column_names()` needed one wrinkle beyond a naive `.split(",")` + `.strip()`: the INSERT's SQL
string is built from several adjacent Python string literals split across source lines (for
readability), so the RAW SOURCE TEXT between two literals contains a stray
`"\n<indentation>"` artifact that glues onto the front of whichever column name sits right after a
line break (e.g. splitting on "," yields a token like `'"\n                "camera_height'`
instead of a clean `'camera_height'`) — confirmed live by actually running the split against the
real file before trusting it, not assumed. Fixed by taking the LAST identifier-like regex match
(`[A-Za-z_][A-Za-z0-9_]*`) in each token rather than a plain `.strip()`, which correctly recovers
`'camera_height'`, `'transition_kind'`, and every other affected token — verified end to end with a
standalone script that printed the parsed column list and each computed `_param_index()` result
against the ACTUAL current 34-column/32-param INSERT before trusting the fix in the test files
(shot_archetype→28, lens_mm→29, camera_height→30, dof→31, all correct against the real `$29`-`$32`
placeholders). `_param_index` also subtracts the two SQL-literal columns (`status`='done',
`generation_method`='coverage') that occupy a column-list slot but no `$N` placeholder. This ends
the recurring fragility going forward: a FUTURE chunk appending more trailing columns after `dof`
cannot break any of these four files' assertions again, since they no longer encode a position,
only a name.

Real stash-proof (patch-file technique, never `git stash`): `git diff` of the full chunk (6
touched + 3 new files) saved to a patch; the 3 new untracked files moved aside (not deletable via
`git checkout`, since they don't exist in `HEAD`); `git checkout --` on the 6 tracked files
reverted the tree to byte-identical pre-chunk state (confirmed via `git status --short` empty).
Pipeline suite (`tests/` minus two PRE-EXISTING, unrelated collection errors —
`test_sound_curation.py`/`test_ctr_12h_tracking.py` fail to import `sound_prompt_bot`/
`performance_tracker` under system `python3` 3.9.6 regardless of this chunk, confirmed via `git
status --short` showing zero diff on either file) ran 18 failed/546 passed reverted vs 18
failed/574 passed applied — the +28 delta is exactly this chunk's own new
`test_d11_2_shot_dp.py` tests — sorted FAILED-test-name sets diffed byte-identical (empty diff).
Full backend suite (`/Users/ryanayler/economy-fastforward/storyengine/backend/venv/bin/python -m
pytest tests/ -q`, the MAIN checkout's venv binary run against this WORKTREE's code, per this
chunk's own instructions) ran 29 failed/3958 passed reverted vs 29 failed/3962 passed applied —
sorted FAILED-test-name sets diffed byte-identical (empty diff); the applied run's 29 failures are
all in `test_custom_film_remotion.py` and `test_youtube_oauth_diagnostics.py`, pre-existing and
untouched by this chunk. The patch then forward-applied cleanly (`git apply`, no conflicts) and the
3 new files were moved back, restoring the chunk exactly (`git status --short` confirmed identical
to pre-revert). `schema.sql`'s `assets` table updated with the three new `lens_mm`/`camera_height`/
`dof` columns, comments cross-referencing migration 150. `coverage_to_app.py`'s `store_scene` INSERT
touched SURGICALLY — only the one SQL statement's column list, `VALUES` placeholder list, and
trailing `execute()` args, per this chunk's brief warning that another worker was editing a
different region of that same file concurrently (confirmed via `git diff --stat` showing only that
one file's 13-line diff, no unrelated hunks).

**Vocabulary decision worth a human glance:** rule 11 (FOUR CAMERA FACTS) states camera height as
FREE PROSE with illustrative examples ("bed height, eye height, low tilted up, standing height"),
not a fixed enum — that's WHY `check_camera_facts_present`'s own docstring calls facts (b)/(c) not
mechanically checkable. This chunk's `camera_height` field is therefore a NEW controlled
vocabulary, not a literal extraction of rule 11's words — it reuses rule 11's own recognizable
single words where they exist ("eye" from "eye height", "low" from "low tilted up") and extends
with ground/waist/chest/high/overhead to cover the same range of heights a director would actually
call out. If a future session sees Claude's real DP rows drifting toward height phrases NOT in
this set (e.g. writing "bed height" or "standing" literally, copying rule 11's own prose instead of
the DP row's controlled vocabulary), that's a prompt-wording issue in rule 28, not a parser bug —
worth tightening rule 28's phrasing rather than silently widening `CAMERA_HEIGHT_KINDS` to catch
whatever Claude happens to write.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether Claude ever spontaneously reaches for the DP row at all given it's purely optional (rule 28
says "MAY", so a real planner might simply never use it — that's a legitimate outcome, not a bug,
but it also means the field's real-world value is unproven until a session watches actual plans use
it); whether Claude, when it DOES use the row, keeps `camera_height` inside the taught vocabulary
or drifts toward rule 11-style prose phrases instead (see the vocabulary note above); whether the
ARCHETYPE-SYNERGY guidance in rule 28 (an archetype's typical_lens as lens_mm's default) actually
influences what Claude writes, since `shot_archetypes.format_archetype_menu()` does not surface
each archetype's `typical_lens` value to the planner at all (that field exists only in the Python
catalog, read-only for this chunk) — the synergy note is pure prompt guidance the planner would
have to already know or infer, not a value it can look up from what it's shown; and whether
`check_shot_dp_valid`'s WARN-only posture should be promoted to a hard gate once a track record
exists (explicitly flagged as hard-eligible under Ruling 1 in the check's own docstring for all
three checkable facts, but promotion is a separate, deliberate call, not automatic).


## D9-3 environment-lock harvest (branch `d9-3-environment-locks`) — apply migration 152 on next deploy window; RE-APPROVE environments so the locks actually populate (populate-or-inert trap, same shape as D9-2)

**Built and tested in a worktree only — migration 152 was NOT applied to prod this session**
(no prod-migration writes allowed from a build-only chunk). Same auto-apply mechanism as every
prior migration (`main.py`'s startup hook, tracked in `_migrations`, warn-not-fail on a per-file
error). Same shape as D9-2 (migration 151, character locks): these three columns populate ONLY at
environment-APPROVAL time — every existing environment row has NULL locks today, and stays NULL
forever unless its video's environments are re-approved. The canonical branch in
`_canonical_environment_locks_line`/`redraw_asset_image` never runs on a single real video until
that happens. The deploy-window recipe below MUST include a re-approval step, not just a migration
check — and per this chunk's own brief, it must specifically cover video
8d90df90-be0f-4328-b9d3-20f6bb5b71a6 (tenant ee93e6d1)'s three environments (Pod, Corridor, Elite
Viewing Hall — the same video D6-6b's material_map location-matching fix was proven against):

```bash
# 1. Lock the deploy window first (see storyengine/CLAUDE.md's VPS coordination rule), then
#    deploy this branch normally: push main, then
#    scripts/se.sh deploy <session-name> [--with-frontend]

# 2. Confirm the migration actually ran
se logs backend 200 | grep "152_environment_locks"
# Expect: "Migration applied: 152_environment_locks.sql"
se db "SELECT filename FROM _migrations WHERE filename = '152_environment_locks.sql'"
# Expect exactly 1 row.

# 3. Verify the columns exist
se db "SELECT column_name FROM information_schema.columns WHERE table_name = 'video_environments' \
  AND column_name IN ('architecture_lock', 'lighting_time_weather_lock', 'palette_lock')"
# Expect 3 rows.

# 4. THE POPULATE-OR-INERT TRAP: confirm today's rows are NULL (expected, not a bug)
se db "SELECT id, name, architecture_lock, lighting_time_weather_lock, palette_lock \
  FROM video_environments WHERE video_id='8d90df90-be0f-4328-b9d3-20f6bb5b71a6'"
# Expect all three NULL for every row (Pod, Corridor, Elite Viewing Hall) — proves nothing yet,
# this is the baseline.

# 5. Re-approve that video's environments (Environments tab -> "Approve environments" again; this
#    re-runs the SAME vision pass that already exists in prod today (the description-refresh
#    call), now with the extended labeled prompt — no NEW paid call is introduced beyond what
#    approval already costs; the prop-manifest extraction is a separate call, unaffected). Then
#    re-check:
se db "SELECT id, name, architecture_lock, lighting_time_weather_lock, palette_lock \
  FROM video_environments WHERE video_id='8d90df90-be0f-4328-b9d3-20f6bb5b71a6'"
# Expect architecture_lock/lighting_time_weather_lock/palette_lock populated for whichever
# environments' vision call succeeded and followed the labeled format. An environment with all
# three still NULL after this step means the vision reply didn't follow the labeled format that
# pass — check `se logs backend` for "[environments] D9-3 lock extraction partial for <name>"
# (this chunk's own warning) to confirm it degraded loudly rather than silently.

# 6. Plan (free) or draw (paid — confirm cost with Ryan first) that video's storyboard for a scene
#    set in a re-approved location, and confirm the assembled sheet-prompt text actually carries
#    an "ENVIRONMENT LOCKS — fixed for this whole set: ..." block with the exact lock text stored
#    in step 5. The D6-1 board-laws evidence at tasks/evidence/d6-6a-dryrun/sheet-preview_scene1_*
#    .txt shows this project already has a free way to dump the assembled sheet-prompt text for
#    review before any paid draw — reuse that path. This is the one step this chunk could not run
#    itself (no live prod DB access from this Mac — same gap D9-2's entry logged) and is the
#    strongest remaining proof gap: every consumer of `_env_locks_text`/
#    `_canonical_environment_locks_line` is unit-tested against synthetic rows, but no test here
#    proves a REAL re-approval's extracted text survives unchanged into a REAL assembled prompt
#    end to end.
```

**Scope call, stated plainly — the FINAL COVERAGE PICTURE batch path is NOT wired to these locks
in this chunk.** `_canonical_material_line`'s two production callers inside
`scripts/coverage_to_app.py` (the initial board-sheet-preview plan and its sweep/escalation
re-plan) both got an `env_locks_line` sibling this chunk, feeding a new `ENVIRONMENT LOCKS` block
into `_plan_sheet_prompts` — that covers "board... prompts" per the brief. For "final-picture
prompts", the ONLY final-picture composer that lives inside `coverage_to_app.py` itself is
`redraw_asset_image`'s repair leg (the material_map REPAIR LEG's exact sibling, now also emitting
an "Environment locks, fixed for this whole set: ..." clause). The FIRST-DRAW final-picture batch
path (`generate_coverage_for_video`'s call to `run_coverage()`) delegates its own prompt
composition entirely to `skills/video-pipeline/storyboard/coverage.py`, which this chunk's brief
explicitly forbade touching (another worker's region). That module already has its own "MATERIAL
MAP LOCK" section reading `matched_env.get("material_map")` from the SAME `canonical_envs`/
`matched_env` dicts `_approved_envs` now also populates with `architecture_lock`/
`lighting_time_weather_lock`/`palette_lock` — so the DATA is already flowing into that call
(`coverage_to_app.py:4709-4735`'s `canonical_envs=envs, matched_env=env`), but nothing in
`coverage.py` reads the three new keys yet. Wiring that in is real, valuable follow-up work for
whichever chunk next has clearance to edit `coverage.py`'s material-lock section — flagged here
rather than silently left unstated.

**No WARN drift check was added.** The brief asked for one "mirroring `check_material_map_
consistency`'s shape if one fits naturally; skip if it doesn't — state your call." Grepped the
whole backend (`story_laws.py`, `routes/*.py`) for that name and for any material_map-consistency
WARN check: none exists anywhere in this codebase today — `story_laws.py` has exactly three
`check_*` functions (`check_scene_location_law`, `check_location_transit_law`,
`check_cast_consistency_law`), none of which compare a canonical field's text against anything.
D9-2 (character locks, the direct sibling chunk this one templates from) made the identical call
one chunk earlier: `forbidden_drift` is "STORED ONLY... not yet read by any prompt or the frame
arbiter" with no drift check either, deferred to D9-4. Skipped here for the same reason —
inventing a drift check against a function that doesn't exist would be building new law, not
mirroring existing law, and the brief's own phrasing ("if one fits naturally") anticipated this.

**What IS verified (code-level + full local test suite passes, not live prod):**
`storyengine/backend/tests/functional/test_d9_3_environment_locks.py` (24 tests, new) covers
`_parse_environment_lock_reply` (full labeled reply, a reply missing one or more labels, a reply
that ignores the format entirely — parses to `{}`, never raises — multi-line values, case
insensitivity), `approve_environments`' background task with the vision call stubbed AND the
separate `_extract_env_props` call stubbed to fail (isolating the lock-population assertions from
the unrelated prop-manifest call): the happy path writes all three lock columns AND `description`
in exactly ONE `UPDATE` (proving the "one call, not two" requirement at the SQL-write level, not
just prompt level) while confirming the description/locks vision call itself only fires ONCE, a
reply with no labels falls back to the exact pre-D9-3 whole-reply-as-description behavior and
writes zero lock columns, a partial reply (some labels present, some missing) writes only the
fields that parsed and leaves the others untouched (not nulled), a raising vision call degrades
exactly as fail-soft as the pre-existing description-refresh pass, and the no-Claude-creds case
skips the whole vision pass (zero calls) with approval still completing. `scripts/coverage_to_app
.py`'s consumer side: `_env_locks_text` (join-skip-empty, mirrors `_locks_text`) tested for every
presence combination, `_canonical_environment_locks_line` (mirrors `_canonical_material_line`
exactly) tested for the single-location case, the multi-location/LOCSET case (one clause per
location that has locks, a location with none simply omitted, never invented), the KEY backward-
compat case (all-NULL locks -> "", proven directly), and the no-match case. `_approved_envs`
proven to SELECT the three new columns and carry their values through unmodified. `_plan_sheet_
prompts` proven to stamp locks VERBATIM into their own "ENVIRONMENT LOCKS" block positioned
immediately after "MATERIAL MAP" (matching the concatenation order in the source), AND — the key
NULL-locks byte-identical test — a call with `env_locks_line=""` produces OUTPUT BYTE-IDENTICAL to
a call that never passes the parameter at all (`with_default == with_explicit_empty`, asserted
directly), proving every pre-migration-152 call site is unaffected. All pre-existing tests in
`test_c4_prop_manifest.py`, `test_money_safety_character_environment_metering.py`, and
`test_d9_2_character_locks.py` pass unmodified (97 passed across the targeted `-k
"environ or material or D6_1 or d6_1"` sweep). Real stash-proof (patch-file technique, never `git
stash`, per tasks/lessons.md's fleet rule): `git diff` of the 3 modified files saved to a patch;
the 2 new untracked files (migration + test) moved to the scratchpad; `git checkout --` on the 3
tracked files reverted the tree to byte-identical pre-chunk state (confirmed via `git status
--short` empty). Full backend suite (`/Users/ryanayler/economy-fastforward/storyengine/backend/
venv/bin/python -m pytest tests/ -q`, the MAIN checkout's venv binary run against this WORKTREE's
code) ran 29 failed / 4033 passed / 4 skipped reverted vs 29 failed / 4057 passed / 4 skipped
applied — the +24 delta is exactly this chunk's own new test file; sorted FAILED-test-name sets
diffed byte-identical (empty diff, exit 0) — the applied run's 29 failures are all in
`test_custom_film_remotion.py` and `test_youtube_oauth_diagnostics.py`, pre-existing and untouched
by this chunk. The patch then forward-applied cleanly (`git apply`, no conflicts) and the 2 new
files were moved back, restoring the chunk exactly (`git status --short` confirmed identical to
pre-revert). `schema.sql`'s `video_environments` table updated with the three new columns and
comments cross-referencing migration 152 (note, matching D9-2's own honest flag: migration 142's
`material_map` is ALSO still missing from `schema.sql`'s `video_environments` definition — a
pre-existing drift from before D9-3 touched the table, left alone, same class of gap D9-1's and
D9-2's entries above both flagged).

**Diff confined to the environment/material canonical-insert region, per this chunk's own
file-boundary rule** (another worker was in `coverage.py`'s narrative/pacing region and in
`routes/characters.py` concurrently): `git diff --stat` shows exactly 3 files touched
(`routes/environments.py` +123/-managed, `scripts/coverage_to_app.py` +110/-managed, `schema.sql`
+13) plus 2 new files (migration, test); every hunk in `coverage_to_app.py` sits inside
`_approved_envs`, `_canonical_material_line`'s neighborhood, `_plan_sheet_prompts`,
`generate_storyboard_sheet_for_scene`, or `redraw_asset_image` — confirmed via `git diff -- ... |
grep "^@@"` showing only those five functions' line ranges, nothing in the narrative/pacing region
and nothing in `characters.py`/`script_quality.py`/`pipeline_executor.py`/`skills/video-pipeline/**`.

What is NOT verified: the migration actually running against the real Supabase Postgres instance;
whether the extended vision prompt reliably produces the labeled format on a real, unseen reference
image (prompt compliance is never provable from a parser unit test — steps 5-6 above are what
that's for); a real re-approval's extracted architecture_lock/lighting_time_weather_lock/
palette_lock text surviving unchanged into a REAL assembled board or final-picture prompt (step 6
— the strongest remaining gap, no live DB access from this Mac); whether `coverage.py`'s own
MATERIAL MAP LOCK section should be extended to also read the three new keys now flowing through
`matched_env` (a real, valuable follow-up, out of scope per this chunk's file-boundary rule — see
the scope call above); and whether skipping a WARN drift check entirely (no analogous check exists
to mirror) is the right permanent posture once D9-4 (or a sibling chunk) revisits `forbidden_drift`
consumption for characters — the two decisions should probably be made together, not separately.
