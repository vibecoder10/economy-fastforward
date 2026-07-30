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
