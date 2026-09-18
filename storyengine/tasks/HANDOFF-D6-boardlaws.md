# HANDOFF - 2026-07-29/30. Phase D6 shipped: the laws stopped being prose and became code, and the cast mystery was solved.

## Where things stand in one line
Phase D6 is COMPLETE as a build and PARTIAL as a proof: seven chunks landed and deployed to prod, but no
board has been drawn under the new laws yet, and one gap (D6-1c) must close before the proof run is even
meaningful. Total spend for the whole phase: **$0.00**.

## THE BIG FINDING - read this first, it reframes months of "quality" defects
Ryan, 2026-07-29: *"script is the origin of truth the rest of the video follows"* and *"I believe the
script was altered as a fix after the characters were generated but the characters get generated from
the script."*

**Confirmed by timestamps.** Video 686b4651:
| Event | Timestamp |
|---|---|
| scripts rows first written | 2026-07-27 23:19:55 |
| video_characters created | 2026-07-27 23:33:58 |
| scene-1 boards drawn | 2026-07-29 07:06:40 |
| scene 1 edited (escape beat) | 2026-07-29 23:46:17 |
| **scene 2 edited - the text naming "a woman in gold" and "an old man"** | **2026-07-30 01:46:37** |

The navy-suited elders were generated from a script that DID NOT YET CONTAIN those characters. The cast
was a faithful render of the script as it stood. We read it as a casting or drawing failure for days; it
was STALENESS. Before blaming a model for a quality defect, check whether the artifact predates the text.

This is now **law S6** in STORY-LAWS.md, and **phase D7** (5 chunks) exists to fix the mechanism. It is
systemic: of 40 videos with scripts, 15 of the 28 that have characters have a scene edited after the cast
was created. Every scene-edit path leaves characters, environments, the coverage hash and drawn assets
silently stale.

## What shipped and is LIVE on prod
Deployed 2026-07-30 04:02Z, backend `5ab07f04`, migrations 142/143/144 applied, health clean, $0 spent.
- **D6-1 canonical inputs** (migration 142): `video_characters.identity_tag`,
  `video_environments.material_map`, a written style precedence contract, canonical cast/style/material
  inserted VERBATIM by the sheet composer, three gates that raise before any paid call, and repair by
  FRESH RE-DERIVATION so a corrected canonical record heals old shots.
- **D6-2 repair stamps** (migration 143): `assets.shot_location`, `assets.group_arrangement`. Seven of
  eight board laws now have all three legs. **L16 and L22 are genuinely CALCULATED** -
  `compute_reverse_arrangement()` reverses the seating order and swaps frame-left for frame-right instead
  of asking a model to remember. L18's repair leg is deliberately absent with a stated reason.
- **D6-3 story law S3** (migration 144): `scripts.location`, plus `backend/story_laws.py` as the single
  home for S-law text and checks, reaching three of the four scene-writing paths.
- **D6-4 S1 + S5 + S2/S4**: S1 warn-only, S5 was already covered by S3 so no duplicate was built, S2
  admitted as having no deterministic gate, S4 got a partial warn-only gate.
- **D6-5 BOUNDARY-PASS-PLAN.md**: 532 lines, plan only, no code. Chunk 3 of it is unblocked because
  `format_boundary_blocks` already exists on main.

## THE THREE RULINGS - do not relitigate these
1. **A gate may only be HARD when the thing it compares against is CANONICAL.** Prose-versus-prose must
   WARN, never block. Paid for twice: a keyword gate blocked legal boards on "Her face is animated with
   delight" and "An oil painting hangs above the fireplace"; a location gate flagged the exact transit
   sentence S1 requires.
2. **S1 beats a strict S3.** A legal transit sentence names two locations. So `cross_location_text` warns
   permanently. S1 governs whether a script is filmable; S3 governs whether a scene is the right size.
3. **The script wins** (Ryan, 2026-07-29: "script does win"). The script's cast is canonical and the
   board is the defect. Closes S4's open question. Applies to the NEW video, never by hand-editing
   686b4651.

## THE SYSTEMIC BUG THAT WAS SILENTLY DEFEATING EVERYTHING
`worker.py:_run_stage`, the DEFAULT arq path used whenever Redis is up, only special-cased `"cancelled"`
and `"failed"`. Every other status, including `"needs_review"`, fell through to
`db_persist_task(..., "completed")`. A stage that BLOCKED its work reported success and discarded the
violation text. **Every quality gate in the product was decorative on the default path.** Found twice in
one day in unrelated chunks. Now `needs_review` persists as `failed` WITH the violation text, because
`background_tasks.status` has a hard CHECK constraint with no `needs_review` bucket. Applies to EVERY
stage, so expect stages that used to report "completed" while blocking to now report "failed" with real
text.

## NEXT ACTIONS, in order
1. **D6-1c is DONE** (merged `7c760a24`). The real pictures path now prefers canonical
   `video_environments.material_map` over the planner's `[MATERIAL|]` prose. The sibling audit found
   `identity_tag` and the style string were ALREADY canonical on both paths, so the inversion was
   material_map only. **BUT IT IS INERT: every `material_map` and every `identity_tag` is NULL in
   production (38 and 69 rows, 0 populated each), so the canonical branch never runs today.** This is
   the trap for the next step - see the warning inside item 2.
2. **D6-6a - RYAN'S RULE, a $0 gate before any spend.** His words: *"before any image is actually
   generated you will run the script system through the pipeline for a single storyboard and cross check
   the output against the rules to see if it will turn out correct."* Author the corrected EIGHT-scene
   script onto a NEW video (take 686b4651's six scene texts, split scene 1's text into three by hand -
   escape / run and dead end / return - and submit via the FREE `submit_script`). Run to prompt emission
   only via the existing `plan_only` dry run (D3-59), dump the prompt, and cross-check it line by line
   against BOARD-LAWS L0-L29 and STORY-LAWS S1-S6. **Inspect BOTH paths, not just the preview.**
   Honest limit to state up front: a clean dry run proves the PROMPT obeys the laws, not that the picture
   will. The last proof run drew tube-shaped pods from text that said sphere.
3. **D6-6b - ONE paid board, max $0.20, ONLY on Ryan's explicit go.** $0.80 of his authorised $1 is spent.
4. **Phase D7** (5 chunks) - the invalidation mechanism for law S6. Start with D7-1, the cheapest and
   most confusing gap: `_extract_cast` reads the CACHED `videos.script`, but `update_scene_text` never
   syncs it, so a cast regenerated after an edit can STILL be built from stale text.
5. Then D6-1d (L29 still live for preset-only videos), D6-1e and D6-2b, D6-3f (a fourth ungated writer to
   `scripts` at `custom_film_production_runner.py:4535`), D6-3g.
6. Deferred behind those: D5 arbiter A6-A9 + A3b-2, parity chunks D3-55/56/57, D3-54, D3-58, D3-60,
   D3-61.

## HARD CONSTRAINTS - all earned, all cost money to learn
- **Do NOT split or re-derive video 686b4651.** Re-deriving runs `DELETE FROM scripts WHERE video_id = ...`
  (`user_script.py:188/382`), wiping every board, directive and prompt and orphaning $1.85 of drawn assets.
  It is the law-discovery artifact. It has SIX scenes; the eight-scene structure is what you AUTHOR onto the
  new video. Frame-level spend on its scene 1 is FROZEN.
- **`se deploy` REQUIRES the session name BEFORE any flags** (D3-60 still open): a bare flag binds to WHO and
  the frontend build silently skips while the log still prints the flag. Verify BUILD_ID mtime.
- **PATH-ROOT GOTCHA, burned four workers:** the pipeline skill is at REPO ROOT `skills/video-pipeline/`, the
  composer at `storyengine/backend/scripts/coverage_to_app.py`. Two different roots. Put this in every brief.
- **Creating a worktree is not the same as working in it.** One builder created one correctly then edited the
  main tree for 572 lines. Tell workers to use `-C <worktree>` on every git command and absolute worktree
  paths for every edit.
- **An `ImportError` at test collection with the change stashed is NOT a stash-proof.** It proves the module
  is new, not that behaviour changed. Three builders produced that weak form; demand an assertion failure.
- **Every canonical column is NULL for all existing rows** (154 scripts, 891 assets, 69 characters, 38
  environments). The laws are enforceable, not yet enforced on real data. A change that only works when
  canonical data exists will look right in tests and do nothing in production.
- `storyengine/tasks/deferred-verification.md` has conflicted on three merges. Append at the TAIL so the
  keep-both resolution stays trivial.
- Board and frame regens overwrite the SAME Drive file id, so URLs never rotate. Verify by content hash and
  expect browser cache to show stale images.
- Still redraw = $0.05 at 1k (gpt-image-2). The $0.09 chips in the Director UI are CLIP routing, not still price.
- The desktop MCP server is scoped to the WRONG tenant for owner-tenant videos - use `se db` or the VPS API
  with the /tmp/se_token bearer.
- Subagents refuse RELAYED MONEY authorisation by design, and they are right to. But note a deploy is a
  different thing: a worker correctly stopped when told to deploy while also being told not to push, because
  the sanctioned path pushes to origin/main and the VPS pulls from there. Authorise the mechanism explicitly.

## OPEN QUESTION FOR RYAN
Nothing is blocking. The only thing needing his word is **D6-6b**, the one paid board, and only after D6-6a
passes.

## Test baselines
Backend, from `storyengine/backend/venv` with pytest: **43 failed / 3761 passed / 2 skipped / 1 error**, all 43
pre-existing (4 in `test_custom_film_remotion.py` are a known environment gap). Repo-root
`skills/video-pipeline/tests/`: the D6 suites `test_board_laws.py` + `test_d6_2_repair_stamps.py` pass **63/63**
and must stay there; the full suite has 27 pre-existing failures from missing `numpy` and similar environment
gaps. Always diff the failure SET, not just the counts.
