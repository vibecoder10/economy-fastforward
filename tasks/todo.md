# Task Tracking

> **New session?** Read `tasks/orchestrator-and-worker-playbook.md` FIRST — it's the
> orchestrator + Sonnet-worker operating manual (how to run this loop). Then the LOOP
> PROGRESS handoff below is your resume point.

## ⟳ HANDOFF — 2026-07-25 — M8 storyboard-driven Custom Film director loop

**Branch/worktree:** `agent/custom-film-director-loop` in
`/Users/ryanayler/economy-fastforward-custom-film-director`.

**Last done:** the M8 foundation and safe Stage 1 activation seam now compile the film
bible/ordered shots, lock narrator/sound/captions, stage every downstream gate, persist
visual rejection evidence, and admit only clean clips to Director Remotion. With
`CUSTOM_FILM_DIRECTOR_V1=true`, new intake is deterministic and no-inference: it requires
an explicit `CUSTOM_FILM_DIRECTOR_PASS_MAX_CENTS`, shows an exact cumulative
script/director approval, persists an unapproved-media plan/video plus consume-once
zero-call schedule, and cannot fall into the legacy runtime on approval or reload.
Proof: 491/491 Custom Film tests, all 37 Remotion tests, TypeScript/bundle, and the
visually accepted 72-frame local render.

**Next:** replace the current 48,000-token single-response/two-call prototype—which
cannot fit through the configured 8,192-token Kie response cap for a roughly 50-shot
film—with a multi-pass film-bible -> outline -> shot-batch executor. Price its complete
call bill under a new authority version, journal actual usage/cost, and persist its
compiled contract; do not reuse the current two-call approval. Then add the reference
-> storyboard -> final-picture -> animation/voice approval cards and executors before
the production renderer adapter. The activation flag remains off and migration 135 is
unapplied. Paid provider work, migration application, deployment, upload, and
publication remain unauthorized; $8.57 is historical accounting only, not permission
for the next call.

## ⧗ HANDOFF — 2026-07-24 (night) — SFX render-path guard: code done, live UI check BLOCKED (report only, no code changes this session)

**Branch:** `claude/exciting-swirles-4d8fba`, commits a3453902 (initial guard) + 9d83c621 (closed
the ClaudeOrchestrator/advance_video/production_guide gaps a reviewer found). Not this session's
work — this session's job was to verify the change in a browser and record the docs.

**What this session did:** Overnight, user asleep, mutation-ban rule in effect (no clicks that
touch prod data, no deploys, no paid calls). Pulled two real videos via `se db` (read-only):
BLOCKED = `65a8021e-eafa-4cff-94dc-31982ae7b63d` ("El Mercado...",
`dialogue_mode='character_dialogue'`), ALLOWED = `b4067bf5-9d6b-484e-8f7d-6fe7eb11416e` ("She
Wanted To Bake A Cake...", all render-path fields NULL). Started local backend (8001) + frontend
(3001) in this worktree — **backend process started cleanly but could not reach the production
DB from this Mac** (confirmed via a raw `asyncpg.connect()` test outside FastAPI, deterministic,
not transient — see tasks/lessons.md 2026-07-24 night entry for the reproduction and best-guess
cause). So the intended curl + browser screenshot verification of `sound_effects_supported`/
`sound_effects_unsupported_reason` **did not happen live**. What DID happen: manually evaluated
`status_map._render_path_sfx_reason()` against both videos' real DB rows by reading the code —
matches expected BLOCKED (banner text: "this video uses character-dialogue performance
rendering, which has no sound-effects track.") / ALLOWED (no banner, buttons enabled) outcomes —
and read `SoundTab.tsx` to confirm the wiring is self-consistent. **This is a code read, not a
live UI verification — do not treat it as equivalent.** Full recipe + exact expected output for
whoever picks this up: `tasks/deferred-verification.md` (new file, SFX section).

**What's next:**
1. Someone with real prod DB access from their machine (or a session running ON the VPS) runs
   `tasks/deferred-verification.md`'s SFX section step 1 (curl the two fields, screenshot both
   Sound tabs, check console). This is the load-bearing check nobody has done yet.
2. Ryan (awake, at the keyboard) runs deferred-verification.md's SFX section step 2 — Advance a
   blocked video through the sound stage and confirm it skips cleanly instead of deadlocking —
   and step 5's tiny real paid SFX generation on an ALLOWED (legacy) video as a regression check,
   with cost approval first.
3. Step 3 — the `/pipeline` create-page "Sound design" checkbox disabling for static-documentary
   — also unverified live, same DB blocker.
4. Docs are current as of this session: `docs/failure-modes.md` (new row), `tasks/lessons.md`
   (2026-07-24 night entry), `tasks/decisions.md` (2026-07-24 "Keep the Sound feature, guard the
   spend" entry), `tasks/deferred-verification.md` (new file). Nothing else in this file was
   touched — the huge LOOP PROGRESS section below is unrelated prior work, left as-is.

## ✅ RESOLVED 2026-07-21 — stale VPS repo copies deleted
Ryan approved; `/home/clawd/agent-workspace` and `/home/clawd/economy-fastforward`
(the two orphaned checkouts carrying the old bare `pkill -f "next-server"`) are
`rm -rf`'d. Audit first confirmed zero references (crontab, systemd system+user
units, home-dir scripts, running processes). The uvicorn kill in
`storyengine_deploy.sh` is port-scoped to 8001 on main @ 72e32914; the live
deploy repo (`~/projects/economy-fastforward`) picks that up on next `se deploy`.

## ⟳ LOOP PROGRESS (read this first — resume point)
- **Last done (WORKER, not yet orchestrator-reviewed/merged): C66 · MCP process brain (2026-07-21) — the co-pilot that keeps Ryan on track.** tasks/decisions.md 2026-07-21 "MCP co-pilot must be PROCESS-AWARE": the connected agent skipped environment design + a character-presence check because nothing taught it the canonical stage order or a video's gaps. New `storyengine/backend/production_guide.py`: ONE `GUIDE_STAGES` list (research→script→voice→characters→environments→storyboards→images→sound→video→thumbnail→render→upload) feeds BOTH (a) `build_process_instructions()`, called LIVE on every MCP `initialize` dispatch (never baked into a module constant — lock-tested by monkeypatching the map and re-dispatching), and (b) the new `get_production_guide(video_id)` MCP tool — per-stage done/in_progress/not_started/skipped_by_format for ONE video plus concrete gaps (missing character sheets, unapproved environments — a HARD gate on storyboards per `pipeline_executor._environments_ready_gate`, scenes with no storyboard grid) and a `next_step` recommendation. Order + format-skip derive from `status_map.py`'s real `STAGE_ORDER`/`static_stage_plan`/`parse_stage_plan` (not invented) plus `pipeline_executor.py`'s traced character/environment gates (~L7614-7696) — independently matches `next-action.ts`'s own step order. Gap detection reads only already-stored data (video_characters/video_environments rows, story_bible, scripts.storyboard_*_url, background_tasks); a missing Story Bible reports "unavailable", never guesses. PLUS the environments MCP tool family (the NAMED skipped step — environment DESIGN had no verb/tool at all before this chunk, unlike characters): `design_environments`/`redo_environment` (PAID, same `_paid_gate` confirm_token cycle every atomic paid tool uses, quote scales with existing environment-row count at `actions.PICTURE_COST`) + `edit_environment`/`delete_environment` (free) — all four thin wraps over existing `routes/environments.py` endpoints (`get_environment_images`/C48 already covered the read side). Tool surface 91→96 (pinned test updated with a comment). 28 new tests (`tests/functional/test_c66_production_guide.py`), non-vacuous via `git stash` + moving `production_guide.py` aside (collection fails outright without it). Full suite **2126P/15F/1E** = baseline(2098)+28, zero new failures, same 15/1 by name. `py_compile` clean. No migration, no frontend. See SYSTEM_STATE.md §C66, checklist tick, live-verification-queue §C66. **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate** — purely additive (5 new MCP tool names, no existing tool's schema/dispatch touched, no DB/migration/frontend change); `initialize`'s instructions text grows (additive/informational only); the only non-additive edit is the pre-existing lock test's count bump.
- **Next chunk:** orchestrator should review C66 (spot-check: read `_environments_ready_gate`/`_load_character_refs` in `pipeline_executor.py` and confirm they really are the HARD/soft gates the guide's gap text describes; confirm the `initialize` instructions really are built live — not cached — by re-reading the `_dispatch` call site; re-run the full suite) and merge if satisfied. After C66, the build queue is empty except C46e (Ryan verification/decision item, OR-9 QL-66 check) and whatever Ryan surfaces next from live use.
- **Prior "Last done" (WORKER, orchestrator-reviewed?: pending — see above): C48 · Media-bearing MCP tools + `quick_demo_video` (2026-07-21) — the build queue's ONLY remaining chunk, now unblocked at the time.** C25a's signed media proxy merged+deployed 2026-07-21 (see below + decisions.md "PROCESS-AWARE"), so this chunk's stale "BLOCKED on C25a" note is gone from the checklist. Shipped: 4 signed-media-URL MCP read tools — `get_scene_boards` (a scene's drawn pictures capped at 6, or a no-image per-scene count summary with no `scene` arg — MCP twin of chat.py's C15b `_handle_show_op`), `get_character_sheets` (video's cast, or the channel-level locked cast with no `video_id`), `get_environment_images`, `get_thumbnail_image` — all signed via new `_sign_media_url()` in `routes/mcp.py`, a THIN reuse of `shared.clients.image_client._kie_fetchable_url` (the SAME function Kie's own image-to-image calls use, C25a-fix2) — not a forked signing scheme (locked by a source-pattern test). TTL note reads the real default off `routes.media.mint_media_token` via `inspect`, so it can't drift (currently states 60 min). PLUS `quick_demo_video` — staged (create → quote → confirm, exactly like every other paid tool; NOT a single do-it-all call, per the brief's explicit "do not weaken money gates" instruction) — a thin pass-through to the EXISTING `_call_create_video`/`_call_verb("build", ...)` dispatchers, since the "build" meta-verb already auto-advances script→cast→pictures with zero new pipeline composition needed. Runbook: `tasks/live-verification-queue.md` §C29 gained Step 5d (the guided-session walkthrough: prompt → `quick_demo_video` staged create+build → `get_scene_boards` per-scene review → approve/redo → clips, incl. a bare-fetch-with-no-session proof that a signed URL actually authenticates and a past-TTL 401 proof) and the "model this video" flagship recipe's board-review step now points at these tools instead of a "still missing" flag. 24 new tests (`tests/functional/test_c48_media_tools.py`), non-vacuous via `git stash -- storyengine/backend/routes/mcp.py` (23/24 fail without the implementation — the 24th is a pre-existing S5-2 invariant this chunk doesn't touch). One pre-existing tool-count lock test legitimately bumped 86→91 (`test_c25a_fix11_streamable_http_compliance.py`, C48 added exactly 5 tools to the surface). Full suite **2098P/15F/1E** = baseline (2074P/15F/1E, the post-C25a-merge baseline established this session) + 24, zero new failures, same 15/1 by name. `py_compile` clean on both touched files. No migration, no frontend. See SYSTEM_STATE.md §C48, checklist tick. **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate** — purely additive (5 new MCP tool names, no existing tool's schema/dispatch touched, no DB/migration/frontend change); the only non-additive edit is the pre-existing lock test's count bump, which tracks a real intended increase, not a behavior change.
- **Next chunk:** orchestrator should review C48 (spot-check worth doing: read `_sign_media_url` and confirm it really calls the shared `_kie_fetchable_url` rather than reimplementing signing; confirm `quick_demo_video`'s paid path is a literal pass-through to `_call_verb` with no new confirm_tokens/background_tasks call of its own; re-run the full suite) and merge if satisfied. After C48, the checklist's build queue (per the C46e/C48 entries) is down to C46e (Ryan verification/decision item, OR-9 QL-66 check), the newly-queued C66 process-brain chunk (2026-07-21 decisions.md: MCP `initialize` server instructions for canonical stage order, `get_production_guide(video_id)`, environments MCP tool family — NOTE: this chunk's `get_environment_images` READ tool is NOT C66's environments tool family, which additionally needs design/approve/skip WRITE wrappers), and whatever Ryan surfaces next from live use.
- **Prior "Last done" (2026-07-20 evening, at-computer live-fire session): MCP IS LIVE + 6 more hotfixes shipped (fix7-fix13).** MCP go-live COMPLETE: MCP_ENABLED=true in prod env; agent token minted (PocoAPoco workspace); connected via `claude mcp add --transport http -s user` (claude.ai/Desktop Connectors UI is OAuth-only — bearer tokens can't use it; OAuth wrapper = queued chunk for phone access); fix11 added Streamable HTTP compliance (the real breakage: 'notifications/initialized' was rejected instead of 202'd) → `claude mcp list` shows ✔ Connected, 86 tools, REAL SESSION drove list_videos/research/script with quote-gating working. Paywall passed live fire: refused a free-plan token (C57/C62 working); exposed the arbitrary-member standing bug → fix10 (owner-deterministic ORDER BY; same LIMIT-1 pattern ALSO in billing.py ×3 incl. the MINT gate — queued). fix12: media proxy now honors ALL workspace memberships (session JWT resolved only the HOME tenant → every client-channel image 404'd; pipeline SSE stream shares the bug class — queued). fix10 also: negative allowlist-cache TTL 3600s→10s (fresh-image race). GPT sheet saga RESOLVED root-cause: OpenAI content-filter DENSITY scoring — fix8 reworded the convicted header (pre-flight proven), fix9b single-naming+neutral-phrasing for builder text (captions verbatim per law); REMAINING GAP: caption-dense sheets (Spanish cooking-lesson vocab) still trip the filter → AUTO-SPLIT-ON-REJECTION chunk queued (Ryan ruled NO nano fallback — fix the structure, decisions.md). fix7: Seedance payload (first-frame only — Kie: ref image and first/last frames mutually exclusive; live re-test still owed, ~$0.60 on the Spanish video's clips once pictures exist). Veo Fast $0.30 CONFIRMED via Kie credits (60cr); Veo Quality CANNOT take reference images (Kie rule) — registry exclusion queued; THE THREE MODELS ruling: Grok/Seedance/GPT only. fix13: MCP tool descriptions steer subscription-first thinking (submit_research/submit_script = standard path) + initialize now returns instructions; get_video Decimal serialization fixed. Stripe: dashboard prices created ($29/$79/$199) and VPS env repointed (old env charged $50/$100 and AGENCY was missing entirely); $79 price needs a name; old $50/$100 prices should be archived. Ledger PROVEN live to the cent (Grok $0.09=18cr, GPT $0.05=10cr, Veo $0.30=60cr); Est→Actual chip verified. Baseline **2056P/14F/1E**. Prod @ c8ea9783. Queued (priority order): sheet AUTO-SPLIT on filter rejection; Seedance live clip; billing.py LIMIT-1 trio; pipeline-SSE workspace bug; OAuth wrapper for claude.ai connectors; agent_tokens.created_by migration; voice-fix3 redo (stash 'partial C25a-fix3'); model-picker cleanup (hide Veo/Z-Image); UX papercuts (badge lag, retry price label, no-error toast, login drop on restart); youtube_quota toordinal bug (guard assumes 0 used!).
- **Last done (2026-07-20 at-computer session): C25a COORDINATED DEPLOY SHIPPED + VERIFIED LIVE — C48 IS NOW UNBLOCKED (next build chunk).** Hold branch `claude/c25a-media-auth-hold` merged to main (38fc6297 — docs conflicts only, all code auto-merged; main's docs already described C25a so they resolved to main's side verbatim). Full suite on Ryan's Mac: **1987P/14F/1E**, failure set BYTE-IDENTICAL pre/post merge (proved by running the suite at acee008f in a scratch worktree and diffing names — the documented "15 pre-existing" was already stale before today; this machine's set is 14, same categories: YouTube OAuth/oembed, discovery, activity-feed, dialogue-ffmpeg). Deployed `se deploy c25a-coordinated --with-frontend` (no skew window). Live: auth gate 401 no-token / 401 garbage / 200 real bytes / **404 cross-tenant** / 206 video Range — orchestrator re-ran the 401 probes independently. Surface walk (Sonnet worker in Ryan's Chrome) found 4 surfaces rendering RAW `video.thumbnail_url` Drive links (pre-existing, not a regression — files never imported the helper): pipeline list cards, RenderTab poster, UploadTab, /render dashboard. Hotfix **aec8afa1** wrapped all 6 remaining thumbnail_url render sites in `toDisplayImageUrl` (incl. analytics/autopilot; helper passes non-Drive URLs through), redeployed `--with-frontend`, re-walk ALL PASS on new bundle hashes, zero drive.google.com requests, zero console errors. live-verification-queue §C25a marked DONE (also deduped — the merge had left two copies of the section). **Next:** remaining at-computer runbook top-down — ⚡ cheap paid checks (one scene pictures ~$0.05-0.30 lights up C07/C08/C10; Veo price confirm; ElevenLabs rate), then MCP go-live §C29, Stripe price check §C63, feature-board seed §C65, DvsU rules seed. C48 buildable the moment the orchestrator has a free slot.
- **LOOP PARKED (2026-07-20) — QUEUE FULLY DRAINED except Ryan-only items + orchestrator review.** Everything buildable without Ryan is DONE, verified, and on main through C61b; C62 (plan-limits wiring), C63 (pricing UI copy), and C65 (feature board) are ALL ORCHESTRATOR-REVIEWED AND FF-MERGED TO MAIN (C62: operator exemption + gate code read, suite re-run 1946; C63: card copy reviewed, prices confirmed in PLANS arrays; C65: operator gate + live tables + cross-tenant design confirmed, suite re-run 1968, tsc clean). Branch == main == origin at C65's commit. NOTHING pending review. Latest verified baseline **1968P/15F/1E** (baseline(1946)+22 from C65's new tests; 1946 was unchanged by C63 — frontend-only; was 1929P/15F/1E before C62's +17). Remaining work requires Ryan at the computer (tasks/live-verification-queue.md, top-down): (1) C25a coordinated deploy (`claude/c25a-media-auth-hold`, backend+frontend together) → unblocks C48 (media-bearing MCP walkthrough — the ONLY remaining build chunk); (2) MCP go-live runbook §C29 (~$1-2) incl. the new §5c composition recipes + "model this video" flagship + the C61b "Managing multiple channels" subsection; (2b) **NEW from C63:** confirm `STRIPE_PRICE_STARTER/PRO/AGENCY` in the Stripe dashboard actually match $29/$79/$199 (see live-verification-queue §C63) — the UI now shows the ratified numbers but checkout will charge whatever Stripe's dashboard prices actually are; (2c) **NEW from C65:** Ryan seeds 4-5 real feature-board candidates + walks the operator status ladder live (see live-verification-queue §C65); (3) DvsU rules seed; (4) parked decisions REMAINING after C62 resolved "which tier gets MCP": extra-channel seat Stripe price object ($49/mo, also referenced in C63's new copy — still no Stripe object), trial length, annual billing (C63 shows annual figures as DISPLAY ONLY, no annual Stripe price/toggle wired), deploy timing, legacy-tenant question blocking the rate_limit plan-lookup dedup (C60b finding), Agency full-auto minimum-budget-cap confirmation; (5) C61b's trace-recommended build (self-serve second-workspace + invite-a-manager, both explicitly NOT built — note: "invite-a-manager" is now ALSO seeded as a feature-board candidate per (2c), so it may get customer votes before it gets built). Next orchestrator session: resume from THIS file + the playbook; review/merge C62, C63, and C65, then C48 is the next chunk the moment the C25a deploy lands.
- **Last done (WORKER, not yet orchestrator-reviewed/merged): C65 · Feature board — "suggest a feature" with upvotes + status ladder.** Built the platform's FIRST deliberately CROSS-TENANT surface (tasks/decisions.md 2026-07-20 "Feature board" entry) — every customer sees the SAME board, writes attributed per ACCOUNT not tenant. Migration 112 (`feature_requests`/`feature_request_votes`, live-applied + reconfirmed via `information_schema`; the votes table's composite PRIMARY KEY *is* the one-vote-per-account rule — proven LIVE with a raw duplicate insert raising `23505 duplicate key value violates unique constraint`, and a bad status value raising a live `check_violation`, both against temp rows created+cleaned up in the real `wrromlupsmyzrrcqlucn` project). New `routes/feature_board.py` (registered in `main.py`): `GET/POST /api/feature-board`, `POST`/`DELETE .../vote`, `PATCH .../status` — reads via `Depends(verify_token)` (deliberately USER-scoped, NOT `get_tenant_id`), status-change reuses `routes/workspaces.py::_is_operator` verbatim (403 non-operator), create rate-limited via a plain per-day `COUNT(*)` query (NOT `rate_limit.py`'s in-memory per-minute bucket — wrong tool, explained in the route's docstring). 3 new MCP tools (`list_feature_requests`, `suggest_feature`, `vote_feature_request` — free, no status-change tool per the spec) dispatch through the SAME route functions via a new `account_id_for_tenant()` resolver (MCP tokens are tenant-scoped; feature-board attribution is account-scoped, so a representative account is resolved per tenant). New `/ideas` frontend page + nav entry (`sidebar.tsx`); operator status control gated on the SAME `GET /api/workspaces.is_operator` the workspace switcher already reads — no new operator-detection mechanism invented. 22 new tests (`tests/test_c65_feature_board.py`) covering create/length-caps/rate-limit (incl. toggle-the-constant non-vacuity proof), one-vote-no-op+unvote, cross-ACCOUNT visibility (the explicit non-isolation pin), operator gate (incl. toggle-the-flag non-vacuity proof), bad-status rejection, raw-text round-trip (no server-side HTML interpretation), and MCP attribution. Full suite **1968P/15F/1E** = baseline(1946)+22, same 15 named failures/1 error, zero new. `rm -rf .next && npx tsc --noEmit` clean; `npm run build` succeeds, `/ideas` in the route list. See SYSTEM_STATE.md §C65, checklist tick, live-verification-queue §C65 (Ryan seeds 4-5 real candidates incl. invite-a-manager/in-chat storyboard review/talking-head format/per-scene voice casting, then walks the ladder live). **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate** — purely additive (2 new tables, no existing table/route/component modified), RLS-enabled-no-policies (proven-safe house pattern), no money path touched, backend+frontend ship in the same commit so no `--with-frontend` skew risk.
- **Prior — C63 · Pricing on the UI (ratified ladder).** Updated `/pricing`, `/billing`, and the landing page (`/`) plan cards from the stale Basic $50/Pro $100 ladder to the ratified Starter $29/Pro $79/Agency $199 (tasks/decisions.md 2026-07-20 "PRICING RATIFIED"), with feature copy matching what C62 enforces (Starter: 1 channel, videos up to 10 min, 12 gens/mo; Pro/Agency: unlimited generation & uploads, Channel DNA, MCP, autopilot dial). Annual prices (~20% off: $24/$64/$159) shown as display-only text — no annual Stripe price object exists yet, checkout still only wires monthly. Sweep found and fixed TWO stragglers not named in the original brief: the landing page (`frontend/src/app/page.tsx`) had its own separate stale `PRICING_TIERS` array (same $50/$100 numbers) — updated to match; `AuthenticatedShell.tsx`'s `UpgradePrompt` hardcoded a THIRD stale number, "Starting at $40/month" — corrected to $79. Left untouched (checked, not plan pricing): `docs/page.tsx`'s "$11-19/video" BYOK cost FAQ, `ApiKeysStep.tsx`'s "~$15-30/mo" BYOK estimate, `settings/page.tsx`'s dynamic `{subscription.plan} Plan`. Backend: NONE — Stripe price objects (`STRIPE_PRICE_STARTER/PRO/AGENCY`) are Ryan's dashboard config; flagged as the first live-verification item in `tasks/live-verification-queue.md` §C63 (new section) since a mismatch there means checkout charges the wrong amount. `rm -rf .next && npx tsc --noEmit` clean; `npm run build` succeeds (33 routes). Backend suite **1946P/15F/1E**, identical to the pre-chunk baseline (frontend-only change, no backend file touched, run anyway per protocol). See SYSTEM_STATE.md §C63, checklist tick, live-verification-queue §C63. **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate** — pure copy/display change on already-public pages, no data flow or component-behavior change, no schema/backend touched; only risk is a Stripe-dashboard/UI number mismatch, which is a Ryan config fix, not a code risk.
- **Prior — C62 · Plan-limits wiring for the ratified pricing.** Wires tasks/decisions.md's 2026-07-20 "PRICING RATIFIED" entry (Starter = 10min length cap + 12 videos/mo; Pro/Agency = unlimited count + uploads; MCP = Pro+Agency) into real gates. `routes/billing.py`: `PLAN_LIMITS` pro/agency `videos_per_month` raised to the 1,000,000 "unlimited" sentinel (starter was ALREADY 12, pre-set by C57 — not new); new `enforce_video_length_cap(tenant_id, minutes)` (starter-only, 402 past 10 min); new `_get_tenant_plan_and_operator`/`_mcp_tier_ok` (operator-account-exempt Pro+ decision, shared by mint + per-request). Length cap wired into THREE real doors: `routes/videos.py::create_video` (canonical C38 door), `routes/discovery.py::launch_idea` (a separate pre-existing INSERT C38's convergence never covered — found + closed this chunk, its `LaunchIdeaRequest` default of 15 min was already above the new cap), and `actions.py::apply_followup_edit` (the chat "redo the script at N minutes" post-create seam). MCP tier gate wired at BOTH the mint route (`routes/agent_access.py::create_token`, the C57 seam) AND the per-request verify gate (`auth_agent.get_agent_tenant_id` via `agent_tokens.authenticate_with_standing`, whose single JOIN query was extended to also carry `plan`/`is_operator` — zero added round trips, 3-tuple→5-tuple return, all callers/mocks updated) so a live token dies same-day on a Pro→Starter downgrade, same pattern C57 already used for lapsed subscriptions. Operator accounts (`accounts.is_operator`, Ryan's own) exempted from the MCP tier gate — traced and confirmed necessary: Ryan's own `accounts.plan` defaults to `'free'` (no migration ever set it), so without the exemption this chunk would have locked him out of MCP. Tests: new `tests/functional/test_c62_plan_length_and_count_caps.py` (9, behavioral/DB-faked, non-vacuous via `git stash -- routes/billing.py`, 7/9 fail without the fix); `test_c57_mcp_billing_gate.py` extended (+8 net, one renamed since C62 supersedes its old "MCP deliberately not tier-gated" premise), non-vacuous (14/32 fail without the fix); pre-existing `test_c26_mcp_agent_tokens.py`/`test_c29_mcp_full_session_dry_run.py` needed fake-row fixes (`plan`/`is_operator` added) since the arity change broke their untouched fixtures — fixed, not worked around. Full suite **1946P/15F/1E** = baseline(1929P)+17, same 15 failures/1 error BY NAME, zero new. `py_compile` clean. No migration, no frontend. See SYSTEM_STATE.md §C62, checklist's C29-item-6 marked RESOLVED, `docs/pricing-proposal-2026-07.md` decision list annotated LOCKED/WIRED. Commit — see `git log -1`. **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate, WITH an explicit day-one-skew call-out** — this is a REAL behavior change for live accounts on the next hourly deploy (any existing free/starter-plan `agent_tokens` row starts 402ing on MCP calls; any starter tenant creating a >10-min video now gets rejected) — this is the INTENDED effect of shipping the ratification, not a bug, and the operator exemption specifically protects Ryan's own workflow. No schema/frontend change; every new gate fails the same 402/upgrade-url shape existing gates already use.
- **Prior — C61b · Workspace-as-channel — `get_workspace_info` whoami tool + multi-channel runbook + second-workspace trace.** Per Ryan's C61 ruling ("Option A — ONE WORKSPACE = ONE CHANNEL", decisions.md 2026-07-20) — no restructuring, `projects`-multi-row build is DEAD. (a) New MCP read tool `get_workspace_info` (`storyengine/backend/routes/mcp.py`, in `_READ_TOOLS`/`_READ_HANDLERS`, no args): returns `workspace_name` (channel_profiles.channel_name → tenants.name → "Workspace", matching `routes/workspaces.py`'s own switcher-label precedence), `niche`/`style_summary` (plain `channel_profiles.niche`/`.style_description` columns, deliberately NOT the heavy `channel_identity` DNA blob that `get_channel_dna` already owns), `autopilot` (`dial_level`/`kill_switch_tripped`/`kill_switch_reason` via the shared `autopilot_dial.get_autopilot_dial`), and `plan` (via `routes.billing._get_tenant_plan`). No-secrets guard: builds the response from explicitly named fields, never spreads a DB row — proven in `tests/functional/test_c61b_workspace_info.py` by feeding a POISONED row (fake `youtube_refresh_token`/`api_key` keys) and asserting none leak, plus a negative-control test proving a naive `dict(row)` passthrough WOULD fail that same assertion. (b) Runbook: added "Managing multiple channels (one connector per workspace)" subsection to `tasks/live-verification-queue.md` §C29 after Step 4 (one MCP server entry per workspace, own `se_agent_...` token, `storyengine-<channel>` naming, `get_workspace_info` as the disambiguation check, honest pricing-lever caveat), plus a one-line pointer in Step 5c's intro. (c) TRACE ONLY (report, no build), appended as §C61b to `docs/reports/2026-07-17-storyengine-agent-audit-findings.md`: every signup path (password + Google OAuth) funnels through ONE function (`routes/google_auth.py::_create_tenant_for_account`), called exactly once per new account — one account/one tenant/one membership always; Stripe/plan lives on `accounts`, NOT `tenants` (`tenants.plan` is vestigial), so N tenants under one account would currently share ONE subscription; a second-workspace UI path DOES exist (`routes/workspaces.py`, mirrors the same 4-insert shape) but is gated to `accounts.is_operator` (true only for Ryan) — it's his own client-channel command center, not self-serve; ZERO invite-a-manager flow exists anywhere (no "invite" hits in any route file). Recommended build shape (not built): drop the operator gate, gate on `is_account_in_good_standing` instead, require a NEW Stripe checkout scoped to the new tenant_id before the insert (makes "own subscription seat" real); invite-a-manager is a separate larger feature, its own chunk. 7 new tests, non-vacuous via `git stash push -- routes/mcp.py` (6/7 fail without the change: `AttributeError: module 'routes.mcp' has no attribute '_call_get_workspace_info'`). Full suite **1929P/15F/1E** = baseline(1922P)+7, same 15 named failures/1 error, zero new. `py_compile` clean; no frontend touched (`npx tsc` not run — backend/docs-only change). See SYSTEM_STATE.md §C61b, checklist C61 tick (rescope note). **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate** — new tool name in the still-dark (`MCP_ENABLED` unset) MCP router, no schema/existing-tool/frontend change, docs-only elsewhere.
- **Prior — C61 · MCP channel-manager surface — STOPPED AT TRACE 2026-07-20, no code changed, RESCOPED by Ryan's ruling above (superseded by C61b, not further action needed).** Per the chunk's own STOP clause. The trace found "channel identity" is fragmented across three incompatible layers, not just `projects` vs `channel_profiles`: (1) `projects` is schema-multi (many rows/tenant allowed, `videos.project_id` FK exists) but practice-singular — every read site is `_get_or_create_project()`/`LIMIT 1`, and the frontend only ever calls `/api/projects/current` with no switcher/list/create UI, so there's no existing seam to wrap for `create_channel`/`list_channels` without inventing UI-invisible state (forbidden by the governing decision); (2) `channel_profiles` is DB-`UNIQUE(tenant_id)` (hard single row) and is the LIVE store for DNA (`channel_identity`), YouTube OAuth, Google Drive OAuth, onboarding state, creator brief — touched by ~20 files, not dead legacy; (3) `autopilot_config` (also `UNIQUE(tenant_id)`), `quality_rules`, `channel_patterns`, `autopilot_proposals`, `learnings`, `content_intelligence`, `discovery_ideas` have no `project_id` column anywhere in schema or Python (`channel_dna.py`/`quality_rules.py`/`autopilot_dial.py` all take `tenant_id` only). Only `create_video` has a real per-channel column to scope today. Full scope table + two candidate product directions are in decisions.md's 2026-07-20 "C61 STOPPED at trace" entry (search that heading). Ryan's ruling (below in decisions.md, "C61 RULING") resolved this: Option A, one workspace = one channel — see C61b bullet above for what shipped.
- **Also done:** C60 · MICRO maintenance pair (orchestrator-verified: suite 1922P/15F/1E exact, sacred boundary confirmed in diff, ff-merged to main; the C60b STOP was CORRECT — checklist's "canonical" label didn't survive a full read, rate_limit's copy handles a legacy shape billing.py's doesn't). (a) Deleted now-dead `storyengine/frontend/src/components/storyboard/` (`index.ts`/`scene-grid.tsx`/`panel-detail.tsx`/`progress-bar.tsx`) — C39 had already found it dead but left it in scope-discipline; this chunk re-proved orphanhood FRESH (whole-frontend grep for every export name + every plausible import path — zero external consumers, only internal cross-refs within the folder itself), confirmed the SACRED in-page storyboard UI (`ScenesWorkspaceTab.tsx`) and backend storyboard pipeline stages don't touch it, then `git rm` all 4 files. `rm -rf .next && npx tsc --noEmit` clean, `npm run build` succeeded (33 routes). (b) `rate_limit.py`'s private `_get_tenant_plan` vs `routes/billing.py`'s "canonical" one (C57 finding) — READ BOTH FIRST per the chunk's own instruction, found they are NOT behaviorally identical: rate_limit.py falls back to the legacy `tenants.plan` column (pre-`accounts`/`memberships`-split tenants) when no membership row exists, billing.py has no such fallback (returns `"free"` immediately); rate_limit.py also caches 60s, billing.py doesn't (this half's a documented anti-429-storm fix, not an oversight). Per the chunk's explicit "match the canonical one only if behavior stays identical for every input; otherwise STOP and report" branch — STOPPED, made NO code change to either file (forcing rate_limit onto billing's version would silently drop the legacy-tenant fallback, a regression). Import-cycle check done anyway for whoever picks this up next: no cycle exists today (`routes/billing.py`'s import chain never reaches `rate_limit`/`main`; `rate_limit.py` already uses deferred function-body imports for `database`/`agent_tokens`, so a deferred `from routes.billing import ...` would be safe once/if the semantics get reconciled). No lock-test added (nothing true to pin — two definitions intentionally differ today). Full backend suite **1922P/15F/1E**, exact match to session baseline, zero new (expected: (a) frontend-only, (b) no code changed). Commit 6e09819. See SYSTEM_STATE.md §C60, checklist tick. **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate** — (a) removes dead code with zero live consumers, proven by full-repo grep + clean tsc/build; (b) is pure investigation, nothing to regress.
- **Next chunk:** orchestrator should review C60 (spot-check: re-run the grep-proof for (a) independently; read both `_get_tenant_plan` implementations and confirm the legacy-fallback + caching divergence is real, not a misreading) and merge if satisfied. THEN, if picking up the (b) follow-up: first answer the product question — do any tenants still exist with no `memberships` row relying on the legacy `tenants.plan` fallback (a live DB query, not a code question)? If no, delete the fallback from `rate_limit.py` as its own reviewable change, THEN dedupe onto one shared helper (billing.py re-exports if a cycle risk ever materializes) with a lock-test pinning one definition. If yes, the fallback needs to be ADDED to billing.py's version first (a behavior change to billing.py, needs its own review) before anything can be deduped.
- **Prior "Last done" (WORKER, not yet orchestrator-reviewed/merged):** C58 · Early-warning launch classifier (Follow-up queue, the LAST P4.2 scout gap). SaaS-side port of the legacy `autopilot/monitoring/early_warning.py` CONCEPT (fixed absolute CTR% bands) onto the C46e/C56 data-derived-per-channel LAW: new `early_warning.py::classify_early_signal` compares a video's write-once `ctr_48h` snapshot (maturity-matched by construction — every video locks it at the identical 48h-post-publish milestone) against the SAME tenant's OTHER videos' `ctr_48h` median, reusing `channel_patterns.MIN_COHORT`(5)/`OUTLIER_THRESHOLD_PCT`(30%, the `underperforming` cutoff; `watch`=half that, 15%) directly — no parallel constants invented. "Young" = ctr_48h available + never classified (`early_signal_at IS NULL`); self-bounding since ctr_48h is itself write-once. A too-thin channel cohort leaves the marker unset so the SAME video retries next sync — never guesses, self-heals as the channel grows. Wired into `routes/youtube_sync.py::_writeback_matched_videos` as a SECOND, independent, fail-soft batched trigger alongside C56's launch-pattern flywheel (a video can queue for both in the same sync). Storage: migration 111 (`videos.early_signal`/`early_signal_evidence`/`early_signal_at`, live-applied via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema`); `schema.sql` updated (and, while there, picked up C56's `launch_pattern_analyzed_at` column that schema.sql had never gained — a pre-existing drift, fixed alongside). Notify: one `bot_activity` row (`bot_name="early_warning"`) ONLY on `underperforming`, and only ever once (write-once marker). Surface: `models.py`'s `VideoSummary` (list+detail) gains `early_signal`, `VideoDetail` additionally gains `early_signal_evidence`/`early_signal_at`; `routes/videos.py`'s `list_videos`/`get_video` both select+return it; `routes/analytics.py::get_channel_videos` gains a `LEFT JOIN videos` + `early_signal` key (natural badge slot next to the title on that list row — no frontend change made). MCP decision: NO new tool — `get_video`/`list_videos` MCP tools dispatch through `actions.video_summary` (a production-status dict, not `VideoDetail`/`VideoSummary`), so adding analytics fields there would be scope creep on an unrelated surface; revisit if an MCP consumer needs it. 31 new tests (`tests/test_c58_early_signal.py`: 13 pure classifier cases incl. exact boundary values + a lock that the underperforming threshold literally equals `channel_patterns.OUTLIER_THRESHOLD_PCT`, 11 `run_early_signal_classification` cases incl. self-exclusion-from-own-history/notify-only-on-underperforming/notify-failure-doesn't-undo-the-write/one-video-failure-doesn't-abort-the-batch/cross-tenant-isolation, 7 `_writeback_matched_videos` wiring cases incl. already-matured-vs-freshly-matured-this-sync/never-requeues-mature/both-flywheels-fire-independently). NON-VACUOUS via `git stash` (stashed all 7 implementation files, kept the new test file): collection fails OUTRIGHT with `ModuleNotFoundError: No module named 'early_warning'` against the pre-C58 tree — the strongest possible proof. Full backend suite **1910P/15F/1E** = baseline(1879P/15F/1E)+31, same 15 named failures/1 error, zero new. `py_compile` clean on all 6 touched/new `.py` files. No frontend touched (per design constraint 6 — additive field only, no UI work required this chunk); `npx tsc` not run. No migration risk: 3 new nullable columns, default NULL, no backfill (every existing video simply queues for classification exactly once on its next sync). Read-only signal confirmed — no write to `total_cost`/`generation_ledger`/kill-switch/pause anywhere in `early_warning.py`. See SYSTEM_STATE.md §C58, checklist tick, live-verification-queue §C58. Commit dc2bd67. **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate** — purely additive columns/fields, existing per-row UPDATE unchanged when a video doesn't qualify, new module isolated behind its own try/except, every new response field defaults to `None`/absent-safe for any existing frontend build.
- **Also done (WORKER, not yet orchestrator-reviewed/merged):** C59 · Tenant-scoped BYOK adapter for the title-modeling brains + the two skipped MCP tools. Re-diagnosis of the C49 finding: `idea_modeling.py`'s `decompose_title`/`generate_modeled_ideas` already took `anthropic_client` as a REQUIRED param (never constructed one internally) — the real bug was both Claude call sites using the raw-SDK `anthropic_client.messages.create(...)` shape while EVERY real caller (`TrendingIdeaBot`, `pipeline.py`'s `--more-ideas`, `pipeline_control.py`) passes the `shared.clients.anthropic_client.AnthropicClient` WRAPPER, which exposes only `.generate()` and has no `.messages` attribute (confirmed via AST scan) — so every real invocation silently failed (broad `except Exception` swallowed the `AttributeError`, returned `None`/`[]`), with zero existing tests to catch it. Fixed both to call `.generate(...)` instead — no new parameter needed, the pre-existing param already was the injection point once its contract matched. `GapTitleEngine` was already correctly additive (`anthropic_client=None` + lazy global-env fallback) — untouched. New `routes/mcp.py::_resolve_tenant_anthropic_client()` resolves the tenant's key via the SAME `vault.get_secret("anthropic_api_key", tenant_id)` + EXACT error wording `routes/videos.py::rewrite_scene_text` uses (`"Anthropic API key required. Configure it in Settings > API Keys."`, grep-pinned equal), constructs a tenant-keyed `AnthropicClient(api_key=...)` (never the global-env one). Two new FREE-BYOK MCP tools in `_ATOMIC_FREE_HANDLERS` (no `confirm_token`, matching C49's `regenerate_scene_text`/`suggest_video_titles` precedent): `generate_modeled_ideas` (thin wrap: `decompose_title` per seed title → `extract_format` → `generate_modeled_ideas`, zero new pipeline logic) and `generate_gap_titles` (wraps `GapTitleEngine.generate_titles`, the Claude-calling half `score_title_gap_structures` deliberately left unwrapped). New `_ensure_pipeline_on_path()` helper factored out of `_call_score_title_gap_structures`'s inline sys.path snippet (now shared by 3 call sites, not duplicated). Model-id check: NO stale hardcoded literals found — both files already reference the legacy package's OWN `Models.CLAUDE_SONNET` single source (env-overridable), a DIFFERENT (by design) single source than the SaaS backend's `channel_profile.CLAUDE_MODELS`; forcing these two call sites onto the backend's constant would fork the legacy package's convention for just these two files and break "byte-identical legacy default" — correctly left alone. Tests: pipeline-side `title_idea/tests/test_idea_modeling.py` (NEW, 6 tests, hand-rolled `FakeAnthropicClient` to dodge this sandbox's pre-existing broken system-python cryptography chain) + backend-side `tests/functional/test_c59_title_modeling_byok.py` (NEW, 12 tests: tool surface/classification, no-media-url schema check, missing-key clean-error both tools, vault call-shape proof, tenant-isolation proof via the client reaching the REAL pipeline functions, same-callable proof, bad-input short-circuits before any vault lookup, re-proof of C49's `score_title_gap_structures`-never-constructs-`GapTitleEngine` invariant). NON-VACUOUS via `git stash` on both source files independently: pipeline-side 5/6 new tests fail (exact `AttributeError: 'FakeAnthropicClient' object has no attribute 'messages'`); backend-side 11/12 fail (`AttributeError: module 'routes.mcp' has no attribute '_call_generate_gap_titles'`) — both restored, full re-pass. Pipeline suite baseline **56P/1F** (1 pre-existing `_cffi_backend`/cryptography panic, unrelated) → after **62P/1F**, +6, same failure. Backend full suite baseline **1910P/15F/1E** (re-confirmed live via stash) → after **1922P/15F/1E** = baseline+12, SAME 15 failures/1 error by name, zero new. `py_compile` clean on all touched/new `.py` files. No migration, no frontend touched (`npx tsc` not run — backend/pipeline-only change). See SYSTEM_STATE.md §C59, checklist tick, live-verification-queue §C59 (real tenant-key MCP call recipe for both tools). Commit d03f627. **Deploy-safety assessment (worker's own, pending orchestrator review): ff-merge candidate** — 2 new dark-by-default MCP tool names (`MCP_ENABLED` off in prod), no migration/schema/existing-route/frontend change; the `idea_modeling.py` internal-call fix has no working legacy behavior to regress (every real caller already silently failed identically before this fix) and is BYOK-only (never StoryEngine-billed).
- **Next chunk:** orchestrator should review C58 (read `early_warning.py` in full — it's ~250 lines incl. docstring, the load-bearing bits are `classify_early_signal`'s band logic and `run_early_signal_classification`'s self-exclusion-from-own-history line; re-verify the migration 111 columns live via `execute_sql`; re-run the full suite) AND C59 (spot-check: grep `idea_modeling.py`'s two `anthropic_client.generate(` call sites replaced `.messages.create(`; grep `routes/mcp.py` for `_NO_ANTHROPIC_KEY_ERROR` matching `routes/videos.py`'s literal string; confirm `_ensure_pipeline_on_path` refactor didn't change `_call_score_title_gap_structures`'s behavior; re-run both suites) and merge if satisfied. Then pick up C60 (MICRO maintenance pair: dead `frontend/src/components/storyboard/` deletion + `rate_limit.py`'s duplicate `_get_tenant_plan` dedupe onto `routes/billing.py`'s canonical helper).
- **Prior "Last done":** C38 · Create-surface convergence (chat-primary, Ryan's C37 ruling). Commit 3b29f17. ORCHESTRATOR VERIFIED: read model_video.py (zero INSERT left, calls the real `create_video` in-process), read the title/reference validation branch (no-title + no-reference still 400s; only a valid YouTube reference unlocks the placeholder path), full suite independently re-run **1879P/15F/1E** zero new. ff-merged to main. **New baseline: 1879P/15F/1E. BUILD QUEUE NOW EMPTY** except C48 (blocked on C25a coordinated deploy) + C37 OPEN decision items (Ryan). Original worker report follows: TRACE found 4 of 5 UX doors ALREADY converged on `routes.videos.create_video` (chat.py imports/calls it directly per its own docstring; New Video form posts to it; FirstVideoFlow shares the exact same `createMutation.mutate`/`mutationFn: createVideo` as the New Video form in `pipeline/page.tsx`; onboarding.py has zero `INSERT INTO videos` of its own — driven entirely by chat.py's `_handle_onboarding`). The ONE holdout: `routes/model_video.py::model_video` (Model A Video) had its own INSERT + its own `check_plan_limits`/`increment_usage`. Fix: `create_video` already had a `reference_url`/`is_modeled` branch (built for the New Video form's "copy this video's style" clone path) but only ever ran with a hardcoded `preserve_topic=True`; extended it — `models.py`'s `CreateVideoRequest.title` is now `Optional[str] = None`, and `create_video` derives `preserve_topic = is_modeled and bool(title)` (title present = copy style onto it, unchanged; title absent + reference_url = derive a brand-new modeled idea, Model A Video's shape, newly reachable) — forwarded into the `_run_modeling` background call instead of the old literal `True`. `model_video.py`'s endpoint now just builds `CreateVideoRequest(reference_url=url)` (no title) and calls `routes.videos.create_video` directly (same in-process pattern chat.py/MCP already use) — zero INSERT left in that file, zero frontend changes (endpoint path/shape held stable — `modelVideo()`/`model-video-modal.tsx` untouched, confirmed the frontend never reads the response's `status` field). Plan-limit lock unaffected: Model A Video was never one of the 4 AST-locked entry points (`test_plan_limits_enforcement_lock.py`), confirmed by reading that test's own entry-point list — re-ran it + `test_c53_launch_candidate_gates.py` clean. Checked-not-fixed: `create_video`'s post-insert side effects (`apply_default_template`/`apply_format_defaults`/`apply_locked_cast`) now also run for Model A Video (previously skipped) — traced each, no new collision risk (already interacts this way with the shipped clone path, `apply_format_defaults` never touches `image_style_override` so no precedence fight; the `script_system_prompt` template-vs-modeling overwrite quirk is pre-existing on the clone path too, out of scope to fix here). New `tests/functional/test_c38_create_convergence.py` (8 tests): behavioral proof the endpoint calls the REAL `create_video` with the right title-empty/reference_url shape, a bad-URL guard, source-level pins on `preserve_topic`'s derivation and the title-required 400, a grep-proof of zero `INSERT INTO videos` left in model_video.py, and 3 locks on the already-converged surfaces (page.tsx mutation sharing, chat.py reuse, onboarding.py's absence of its own INSERT). Non-vacuous via `git stash`: 4/8 fail against the pre-C38 code (the other 4 pin pre-existing, unchanged behavior). Full suite **1879P/15F/1E** = baseline(1871P)+8, same 15 named failures/1 error, zero new/missing (re-confirmed reverts to 1871P/15F/1E via the same stash). `test_model_video.py`'s 2 pre-existing failures unchanged (traced to `_run_modeling`, which this chunk never touched). No migration. Frontend: `npx tsc --noEmit` clean, zero files touched. Deploy-safe both directions (old-frontend/new-backend byte-identical `/api/model-video` shape; `CreateVideoRequest.title` widened required→optional is strictly additive) — recommend ff-merge. See SYSTEM_STATE.md §C38, checklist tick.
- **Also done (WORKER, not yet orchestrator-reviewed/merged):** C39 · MICRO — deleted the orphaned `/pipeline/[videoId]/storyboards` standalone page. Fresh grep-proof (per C19b discipline, not trusting the old audit): zero `href`/`router.push`/`Link` references to the route anywhere in the frontend; the only `storyboards` hits in `lib/api.ts` are backend API calls (`/api/videos/{id}/storyboards...`) used by `ScenesWorkspaceTab`, not frontend routes; the video-detail tab system has no `storyboards` tab id at all (in-page storyboard UI lives entirely in the `scenes` tab). SACRED boundary confirmed untouched: storyboard CREATION stage (`pipeline_executor.py`'s `run_storyboard_prompts`/`run_storyboard_images`/`run_storyboard_extract`/`run_storyboard_sheet`, wired via `worker.py`'s `arq_run_storyboards`) and the in-page Storyboard tab (`ScenesWorkspaceTab.tsx`) — neither in this commit's diff. Deleted `storyengine/frontend/src/app/pipeline/[videoId]/storyboards/page.tsx` (`git rm -r`). Left `components/storyboard/` (SceneGrid/PanelDetail/StoryboardProgressBar) in place even though it's now only imported by the deleted page — task scope was explicitly "deletes only the unreachable route," not a wider cleanup; flagged as a candidate for a future chunk. Fixed stale doc entries in `storyengine/agents/blueprints/frontend.md` (removed the route-table row) and `docs/reports/WIRING_STATUS.md` (route row now `DELETED (C39, 2026-07-20)`, bug-log item 6 annotated) — did NOT rewrite that doc's other pre-existing staleness (out of scope). `.next` cache had to be cleared first (stale generated-types reference to the deleted page broke `tsc` until removed — build-cache staleness, not a regression). After that: `npx tsc --noEmit` clean, `npm run build` succeeds (route table confirms `/pipeline/[videoId]/storyboards` is gone). Backend untouched but full suite re-run anyway: **1871P/15F/1E**, exact match to baseline (same 15 named failures/1 error, zero new). No migration, no deploy-skew. See SYSTEM_STATE.md §C39, checklist tick.
- **Also done (WORKER, not yet orchestrator-reviewed/merged):** C49 · MCP atomic-surface completion — 21 new thin-wrapper MCP tools in `routes/mcp.py` across shot-level (`get_shots`/`edit_shot_image_prompt`/`edit_shot_motion_prompt`/`set_shot_model_override`/`improve_prompt`/`redraw_shot` PAID), script surgery (`get_scene_script`/`edit_scene_text`/`regenerate_scene_text` FREE-BYOK), character granularity (`get_characters`/`edit_character`/`redo_character_sheet` PAID), voice control (`set_narrator_voice`/`redo_dialogue_scene_voice` PAID), pre-publish (`get_publish_info`/`edit_publish_info` — real gap fixed: added `category_id` to `youtube_publish.save_seo()`, wired both the new MCP tool and the existing HTTP PATCH route to it), analytics reads (`get_style_performance`/`get_top_channel_videos`), and reference-modeling reads (`pull_reference_video_metadata`/`get_channel_top_performers`/`score_title_gap_structures`/`suggest_video_titles`). New generic `_paid_gate` helper reuses confirm_tokens.py's exact create/redeem for the 3 PAID tools with no actions.ACTIONS verb of their own. Judgment call: `pull_reference_video_metadata` kept SYNCHRONOUS (not start/poll) since a single yt-dlp pull is seconds not minutes — flagged for live proof, not verifiable in-sandbox (no network). Skipped "no existing seam": `idea_modeling.py`/`GapTitleEngine`'s Claude-calling halves hardcode a non-tenant-scoped global-key client — only the pure `score_structures` half wrapped. Composition recipes (6, incl. the "model this video" flagship) added to `live-verification-queue.md` §C29's new Step 5c. 29 new tests in `test_c49_mcp_atomic_surface.py`, non-vacuous via `git stash` (28/29 fail without the implementation). Full suite **1871P/15F/1E** = baseline(1842P)+29, same 15 failures/1 error by name, zero new. No migration, no frontend. See SYSTEM_STATE.md §C49, checklist tick, live-verification-queue §C29 Step 5c. Commit bae275f. ORCHESTRATOR VERIFIED: `_paid_gate` read in full — genuinely reuses confirm_tokens.py's create/redeem/params_hash (params-bound per tool+subject, no fork); `set_narrator_voice` hardcodes the ONE vault key name (cannot write arbitrary keys); C25a URL-stripping confirmed at every carrying read site; full suite independently re-run **1871P/15F/1E** zero new. ff-merged to main. **New baseline: 1871P/15F/1E. Build queue EMPTY except C48 (blocked on C25a coordinated deploy) + C38/C39 (C37-answer chunks) + C37 OPEN decision items.**
- **Also done:** C57 · MCP ⇄ existing-billing wiring ("the token IS the paywall") — no pre-existing "good standing" concept existed (`check_plan_limits`/`_get_tenant_plan` only ever read `plan`/`trial_ends_at`, never `stripe_status` — dead data for gating). Added `routes/billing.py::_good_standing_from_fields`/`is_account_in_good_standing` (the ONE decision function), mirroring TWO dichotomies billing.py already draws elsewhere rather than inventing a third: the webhook's own `sub_status != "active"` fail-closed line, and the trial-downgrade cron's `stripe_subscription_id IS NULL` trial-safety filter. Mint gate (`routes/agent_access.py::create_token`, 402 `subscription_lapsed` + `/billing` pointer) and verify gate (`agent_tokens.authenticate_with_standing`, NEW, piggybacked onto `auth_agent.py`'s existing per-request token-row query via one JOIN through memberships→accounts — no second DB round trip per MCP call) both call it; `auth_agent.get_agent_tenant_id` now returns 402 (not 401) for a valid-but-lapsed token, so existing tokens die same-day with zero revocation machinery. Item 5 (tier-gating MCP itself) deliberately NOT implemented — commented seam left in `create_token`, added as checklist C37 OPEN item 6 ("which tier gets MCP", recommend pro+agency). AUDIT (item 4) found `create_video`/`accept_autopilot_proposal` MCP tools already gated (they call the exact routes the existing `check_plan_limits` lock already pins) — but found a REAL pre-existing bug: chat's "render"/"build" verbs, MCP's IDENTICAL tools, and autopilot's full-auto continuation loop all call `PipelineExecutor.run_render` DIRECTLY (via `actions.py`'s dispatcher), bypassing `routes/pipeline.py::run_render` — the ONLY place `check_plan_limits('render')` was ever called. Render-minute cap enforcement was a no-op for chat/MCP/autopilot alike, not an MCP-specific hole. Fixed at the ONE method every caller converges on (`PipelineExecutor.run_render` now calls the gate itself, fails the same way its other error paths do — a dict, never raises). 27 new/changed tests (new file `test_c57_mcp_billing_gate.py` + extensions to `test_plan_limits_enforcement_lock.py`/`test_c26_mcp_agent_tokens.py`/`test_c29_mcp_full_session_dry_run.py`), non-vacuous via stash (25/27 fail pre-fix; the 2 that don't are confirmatory locks on already-correct behavior). Full suite **1842P/15F/1E** = baseline(1815)+27, same 15 failures/1 error by name, zero new. No migration (all 4 columns already existed). No frontend. See SYSTEM_STATE.md §C57, checklist tick, live-verification-queue §C57 (live lapsed-account recipe). Commit a434141. ORCHESTRATOR VERIFIED: read the auth_agent 402 gate + the run_render gate site (correct fail-as-dict semantics for background callers; gate at the ONE convergence method; redundant route pre-check left harmlessly), full suite independently re-run **1842P/15F/1E** zero new. ff-merged to main. **New baseline: 1842P/15F/1E.** ⚠ Skew note: the render gate is live-on-deploy for chat/UI callers too — semantics unchanged for any plan whose render cap wasn't already breached (the gate simply now fires where it was always documented to). Flags parked: rate_limit.py's duplicate `_get_tenant_plan` (pre-existing, dedupe candidate).
- **Next chunk:** orchestrator should review C38 (this session — the create-surface convergence trace + Model A Video rewire, full detail above and in SYSTEM_STATE.md §C38) and C39 (grep-proof of orphanhood, sacred-boundary non-touch, tsc/build clean, backend suite exact-match) and merge if satisfied — independent of each other and of C49, no ordering constraint. Also review C49's evidence (worth checking: the `_paid_gate` helper genuinely reuses confirm_tokens.py rather than forking it; the `category_id`/`save_seo` extension is additive; the "no existing seam" skip on idea_modeling/GapTitleEngine is a real tenant-scoping gap, not laziness), commit it (currently uncommitted on the branch), and merge if satisfied. After all three land, the checklist's build queue is down to C46e (Ryan verification/decision item, OR-9 QL-66 check) and C48 (blocked on the C25a coordinated deploy) — compose a new chunk or pick up a sweep/decision item from the C37 OPEN list.
- **Last done:** C13 · P1.2b clip generation follows per-scene routing — `resolve_clip_model(scene_override_seam, routed_model, video_model)` in `shared/model_router.py` (wired-registry-gated; NULL/unknown/unwired → video-level model BYTE-IDENTICALLY, proven by object-identity fallback in `run_clip_generation._one`); per-row profile/durations/animator via `_animate_for`; `model_used` written fail-soft post-clip; ledger + quote path now truthful (`estimate_cost` animate/build sums per-row routed prices; pre-plan quotes keep old math, honestly flagged). Orchestrator review caught + worker fixed a false-record edge: speaking-branch (voice_over) rows can't run Veo, so a Veo-routed speaking row now demotes to DEFAULT_VIDEO_MODEL BEFORE pricing, and `effective_model_id` (never the routed target) is the only value written to `model_used`/ledger — InfiniteTalk clips now record `"infinitalk"` too (pre-existing video-level-veo variant of this bug also fixed). Commit 24b4151. VERIFIED: 17 new tests non-vacuous via stash; full suite 797P/16F/1E = baseline+17, zero new. Live mixed-routing build deferred → live-verification-queue §C13. Existing videos byte-identical → ff-merged to main.
- **Also done:** C13b · Channel-style routing guardrail (Ryan's 2026-07-18 rule: LOOK first, scene importance second) — `ModelProfile.styles` affinity in the registry (grok=animated/stylized, seedance=realistic, veo=realistic/cinematic), exposed on `GET /api/models`; `videos.render_style` (migration 089, live-confirmed); `route_shot_model` now: declared style filters to wired style-matching models ("reveal scene, but channel is animated → Grok Imagine"), NULL style → video-level model only ("channel style not set — using channel default") — tier-upgrading is OPT-IN now, the money-safe default. Auto-derivation reuses the existing 6-preset normalizers via `channel_format.render_style_for_preset` (realistic→realistic, the 5 illustrated presets→animated, ambiguous→NULL; `COALESCE` never overwrites an explicit value; orchestrator verified the preset vocabulary makes the 5-vs-1 split unambiguous). Commit 8f923f3. VERIFIED: 16 new tests non-vacuous via stash, 9 C12/C13 tests deliberately updated to pass explicit render_style, full suite 813P/16F/1E, zero new failures. Live style-respecting build deferred → live-verification-queue §C13b. Recommendations-only change (clips unchanged via C13 fallback) → ff-merged to main.
- **Also done:** C14 · P1.2c routing UI — `assets.model_override` (migration 090, live-confirmed) wired as `resolve_clip_model`'s first-precedence arg in BOTH `run_clip_generation._one` AND the quote path (`_routed_clip_costs`), so quotes match spend; new `PATCH /api/assets/{id}/model-override` (tenant-scoped on read+write, rejects non-wired models — orchestrator verified) + `render_style` via existing `PATCH /api/videos/{id}`; `SegmentCard` badge shows effective model (`model_used` after clip, else override > routed > video default) with "why" tooltip, one-tap override sheet priced from the `["models"]` query (no hardcoded prices), Channel-look control (Animated/Realistic/Auto). Commit on branch (see git log). VERIFIED: 11 new tests non-vacuous via stash, full suite 824P/16F/1E = baseline+11 zero new failures, tsc + `npm run build` clean. Playwright honestly skipped (assets routes need live DB) → deferred with recipe, live-verification-queue §C14. Backend+frontend additive, ship together → ff-merged to main (frontend appears on VPS after next `--with-frontend` deploy). ⚠ Worker note: CLAUDE.md's `web-design-system` skill doesn't exist in this environment — used `web-design-guidelines` + mirrored existing components.
- **Also done:** C15 · P1.2d routing conversation + itemized confirm cards — `actions.py` refactored onto ONE shared row-query/precedence pair (`_routed_clip_rows` + `_resolved_model_id`, orchestrator-verified both `_routed_clip_costs` [money] and new `cost_breakdown` [display] consume them — no parallel math, sums-to-total pinned by test against `estimate_cost`'s own return); `_confirm_card` gains optional additive `breakdown` (lines/total/all_premium_total/hero_scenes carrying `routing_reason` verbatim) + `guardrail_note()` phrasing ("channel is set to Animated, so everything stays on Grok"); `agent_brain._tool_cost` itemizes fail-soft; `ConfirmActionCard` renders the panel only when present (byte-identical old payloads, pinned by test). Commit a5cf172. VERIFIED: 15 new tests non-vacuous via stash, full suite 839P/16F/1E = baseline+15 zero new, tsc + build clean, additive both deploy directions. Live chat round-trip deferred → live-verification-queue §C15. ff-merged to main. **Router phase C11-C15 COMPLETE.**
- **Also done:** C15a · "Make it" quote gap closed — ProductionPlanCard now carries a server-sourced "Estimated cost" line (shape a: informed consent on the existing tap; a pre-plan confirm card would've been theater since `cost_breakdown` needs a shot plan). `estimate_plan_cost(minutes)` derives scene count from the REAL pipeline formula (`VideoConfig.act_count`, `pipeline_config.py:53`, traced end-to-end to the per-act `scripts` rows `estimate_cost` prices — orchestrator sent the first flat-$1.50-for-any-length version back; now 1min≈$0.30 / 10min≈$1.50 / 20-30min≈$1.80 with the real 6-act cap surfaced honestly in the card text "~N scenes"), fed through `estimate_cost("build")` — one estimator, no parallel math, fail-soft. Commit 8204c63 (amended). VERIFIED: 12 tests incl. scene-count==act_count equality + monotonic-scaling pins, non-vacuous via stash (8/12 fail pre-fix, incl. the exact 1min==20min bug); full suite 851P/16F/1E = baseline+12 zero new; tsc clean; additive both deploy directions; `_handle_approve` untouched. Live tap-test deferred → live-verification-queue §C15a. ff-merged to main.
- **Also done:** C15b · Inline storyboards in chat + per-scene approve — new `kind="show"` copilot op (`_handle_show_op`: tenant+video+scene-scoped SQL — orchestrator verified the WHERE clause — capped at _MAX_SHOW_IMAGES in SQL AND client-side, Drive URLs rewritten through the media proxy via `_media_proxy_url`, empty scene → friendly offer WITH a real `_estimate_cost` quote); new `approve_scene` verb in `actions.py` (scene-scoped UPDATE, tenant-verified, free/reversible so no money gate); `ChatCore` renders `card.images` as a labeled thumbnail grid (fail-safe: field-presence-gated, byte-identical without it). Commit 0a3cbe7. VERIFIED: 18 new tests non-vacuous via stash, full suite 869P/16F/1E = baseline+18 zero new, tsc + build clean, additive both deploy directions, zero new paid paths. ⚠ Gap noted for a future chunk: Scenes tab has NO approve affordance at all (approve exists only on the old /review page) — `approve_scene` is chat-only today. Live round-trip deferred → live-verification-queue §C15b. ff-merged to main.
- **Also done:** C15c · Director memory — durable preference store — new tenant-scoped table `director_preferences` (migration `091_director_preferences.sql`, applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`; RLS enabled no policies) chosen over `creator_brief`-style JSONB because preferences need individual listing/soft-delete + per-video AND per-channel scoping. Both decision schemas (`agent_brain.py`'s tool-loop brain + `routes/chat.py`'s fallback classifier for the in-video co-pilot, `producer_prompt.py`'s `profile_ops` for the home producer) gained `remember`/`forget` triggers on "always.../never.../remember that.../from now on..." — instruction captured VERBATIM, scoped channel-wide by default or to the current video when the model judges it video-specific. `_save_preference`/`_list_preferences`/`_preferences_brief`/`_deactivate_preference` mirror the existing `_save_creator_brief`/`_hydrate_creator_brief` fail-soft pattern. Hydration wired into BOTH system-prompt builders as an additive "STANDING PREFERENCES" block (capped 20 most-recent, 3000-char limit); "what do you remember?" answers from that hydrated block directly (no op); "forget #N"/"forget that" soft-deletes (`active=false`, never `DELETE`). Commit 6367dd4. VERIFIED: 38 new tests non-vacuous via stash, full suite 907P/16F/1E = baseline+38 zero new, `py_compile` clean, frontend untouched (chat text is the UI). Prompt-injection note (orchestrator): preference text reaches only the system-prompt block; money gates are CODE-level (quote+confirm cards), so a malicious "preference" cannot bypass spend confirmation. Live conversational round-trip deferred → live-verification-queue §C15c. ff-merged to main (orchestrator verdict: additive both directions, new table only).
- **Also done:** C15d · One director voice + data reach — `producer_prompt.DIRECTOR_VOICE` extracted (tone, "co-thinking partner", "DIAGNOSE BEFORE YOU ACT", the "NEVER mention internal machinery" pipeline/stage/render ban) from the middle of `PRODUCER_SYSTEM_PROMPT` into its own constant; `PRODUCER_SYSTEM_PROMPT` now composes it (same effective text, no longer inlined-only) and `agent_brain.run_copilot_brain`'s system prompt now opens with the SAME constant, explicitly framing itself as "the SAME director as the studio's home producer, not a different voice" — its op/verb instructions, confidence gating, and JSON decision schema (`_decision_schema()`) are untouched. Data reach: `_next_to_make_brief`/`_own_performance_brief`/`_learnings_brief` moved out of `routes/chat.py` into new module `channel_briefs.py` (no dependency on chat.py/agent_brain.py — zero circular-import risk); `routes/chat.py`'s `_loop_brief` now imports them from there (same names/call sites, no behavior change); `agent_brain.py` gained a new read-only `channel_data` tool (`_tool_channel_data`, TOOL_DOC + `_run_tool` dispatch) that calls the SAME three functions, fail-soft to a plain "no data available" line when everything's empty. VERIFIED: 15 new tests non-vacuous via stash (fails with `ModuleNotFoundError` pre-change), full suite 922P/16F/1E = baseline+15 zero new, `py_compile` clean, frontend untouched (no UI surface — chat text + a backend tool only). Regression-pinned: C15c's STANDING PREFERENCES hydration still present in both prompts; decision-schema verb vocabulary unchanged; `routes.chat._next_to_make_brief` etc. are the identical function objects `channel_briefs` defines (one source, not a fork). Live "voice feels the same + copilot answers data questions" round-trip deferred → live-verification-queue §C15d. Prompt-only + read-tool, zero new paid paths, zero schema/verb changes — ff-merged to main (orchestrator verdict: prompt-only + read-tool, worst case is an off-sounding reply, never a broken action or extra spend).
- **Also done:** C16 · SWEEP S7 (queue/idempotency) — Explore audit complete, findings appended to `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` §S7. VERDICT: C17 blocked — chat/autobuild path (which C17 extends) has ZERO idempotency (the good arq `make_job_id` dedup only serves manual pipeline routes). 2 CRITICAL: S7-1 chat double-dispatch → concurrent duplicate paid runs (no `_is_task_active` gate anywhere in chat.py/actions.py); S7-2 images/coverage re-bills every scene on re-invoke (only paid stage without skip-if-done — and it's exactly what finalize calls). Plus S7-5 no ledger uniqueness backstop, S7-3 thumbnail unguarded, S7-4 silent 24h no-op on arq re-runs, S7-6 restart-fragile dict guard, S7-7/8/9 hygiene. Fix chunks C16a-d inserted in the checklist; C16a/b/c gate C17. Docs-only iteration → ff-merged.
- **Also done:** C16a · S7-1+S7-6 fix: DB-backed generation claim — new `generation_claims` table (migration 092, live via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns` + unique index + `relrowsecurity=true`) keyed `(tenant_id, video_id, stage)` UNIQUE. `generation_claims.py`'s `acquire()` is TOCTOU-free via a per-VIDEO `pg_advisory_xact_lock` serializing stale-sweep→cross-stage-check→`INSERT...ON CONFLICT DO NOTHING` in one transaction (the lock is keyed on the video, not the stage — this is what makes a "main" acquire racing a "voice" acquire on the same video safe, which a plain per-row `ON CONFLICT` could never see); a claim >2h old is swept + retaken. Fail-closed on DB error for `acquire()`/`is_blocked()` (deny — spend safety must never degrade), fail-soft for `release()` (best-effort DELETE, self-heals via the next acquire's stale sweep). Chat gated at all 3 paid dispatch sites (`_handle_approve`'s autobuild kickoff, `_run_pending_action`'s "build" verb, and its single-stage copilot verb) — denied → "I'm already working on that — I'll let you know when it's done." and NO `add_task`. Lane granularity (justified): chat's autobuild claims "main" (not a separate label, so it composes with the existing lane vocabulary with zero cross-reference); a copilot verb claims its own lane (voice/characters/thumbnail via `stage_for_verb`) or "main" otherwise — reuses `routes/pipeline.py`'s EXISTING lane rules exactly. `actions.py`'s `make_action_step`/`make_autobuild_step` release the claim in the SAME finally block that already runs on success, the first-error break, AND any raised exception (traced, not assumed). Manual routes unified: `_is_task_active` is now `async def`, consults `generation_claims.is_blocked` as the DB authority whenever the in-process dict is clear; ~35 call sites across `pipeline.py`/`videos.py`/`environments.py`/`characters.py` updated to `await` (mechanical — each already inside an async handler). Commit (see git log). VERIFIED: 31 new tests (25 in `test_c16a_generation_claims.py` + 6 in `queue_recovery/test_c16a_manual_routes_claim_check.py`) non-vacuous via `git stash -u` (6 failures + 1 collection error against pre-C16a source), full suite 953P/16F/1E = baseline(922)+31 zero new, `py_compile` clean on all 7 touched/added `.py` files, frontend untouched (backend-only chunk). Live double-tap round-trip deferred → live-verification-queue §C16a. **ff-merged to main** (orchestrator verdict after re-verifying all 3 chat gate sites, the finally-release placement, and grep-confirming zero un-awaited `_is_task_active` call sites) — only concurrent-duplicate dispatch is refused; every existing single-action flow (manual button, chat turn, one-tap confirm) is byte-identical to before. Worst-case failure mode of THIS chunk itself (a leaked claim from a hard process kill between acquire and release) self-heals via the 2h stale sweep — never a permanent wedge, matching the existing `STALE_TASK_THRESHOLD_MIN` reaper pattern already in `routes/pipeline.py` for the same class of problem.
- **Also done:** C16b · S7-2 fix: scene-level skip-if-done + scene allowlist in `generate_coverage_for_video` (`coverage_to_app.py`) — new `_expected_coverage_frame_count(directive, max_moments, angles_max, max_frames)` runs the SAME `parse_coverage()`+`enforce_shot_budget()` math `run_coverage()` itself uses on a saved directive, so "how many frames should exist" is derived from the real planner, never guessed. Completeness rule: a scene skips iff its `coverage_directive_hash` matches the current script hash (pre-existing gate, unchanged) AND its `assets` row count (`generation_method='coverage'`, `image_url`+`drive_image_url` both set) is `>=` that expected count — a crash/content-policy-skip mid-scene leaves the row count short (store_scene's `usable` filter only inserts rows for frames that actually drew), so it correctly reads as incomplete, never a false "done". New `only_scenes: list[int]|None` allowlist (finalize's future entry point) narrows `targets` and FORCES its named scenes regardless of completeness; the pre-existing single `scene=N` param now also forces (preserves the per-scene "regenerate scene N" button's verb byte-for-byte). No `force: bool` added anywhere — chat/autobuild and the "Generate all pictures" button both default to skip-if-done (the money-safe design call), and every legitimate redo already routes through `scene=N`, `only_scenes`, or the wholly separate per-frame `redraw_asset_image` verb. **Incidental CRITICAL fix found while building this** (blocking any end-to-end test of the function): `render_style`/`video_model_id` were referenced at the `run_coverage()` call site but the `v` row's SELECT here never fetched those 2 columns (only the neighboring `generate_storyboard_sheet_for_scene` did) — every real "Generate pictures" click has raised `NameError` since C13b (commit `8f923f3`), meaning **the ONE paid image stage has been completely broken in production** for however long C13b has been live; no test caught it because every existing coverage test exercises sub-functions, never this function end-to-end. Fixed by adding `render_style, video_model` to the SELECT. Commit (see git log). VERIFIED: 14 new tests (`test_c16b_coverage_skip_if_done.py`) non-vacuous via `git stash push -- storyengine/backend/scripts/coverage_to_app.py` (collection error against pre-fix source), full suite 967P/16F/1E = baseline(953)+14 zero new, video-pipeline coverage suite 8P/1 pre-existing F unchanged (`test_drops_moment_with_no_angles`), `py_compile` clean, frontend untouched (backend-only, no UI surface). Live re-invoke-costs-$0 proof deferred → live-verification-queue §C16b. **ff-merged to main** (orchestrator verdict after re-verifying the SELECT fix in-file: pure cost fix + genuine crash-fix; redo verbs unaffected). NameError nuance confirmed by orchestrator read: the per-scene try/except turns the crash into 'Scene N: errored — moving on', so the failure mode was fail-BEFORE-spend — zero pictures, zero billing, never wasted money. ⚠ Prod impact depends on whether the VPS backend restarted after C13b landed — check queued at live-verification §C16b (grep prod logs for "name 'render_style' is not defined"); merging this fix FIRST protects any future restart. Lesson captured in tasks/lessons.md (stub-tests masking missing SELECT columns).
- **Also done:** C16c · S7-5 fix: ledger uniqueness backstop — migration 093 (idempotent `CREATE UNIQUE INDEX IF NOT EXISTS generation_ledger_dedup_idx ON generation_ledger (video_id, stage, kie_task_id) WHERE kie_task_id IS NOT NULL`), applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn` after a pre-apply duplicate scan found **zero rows** (table is empty in prod today — 0 rows total, 0 with a `kie_task_id`); confirmed via `pg_indexes`. `record_ledger_entry()` now inserts with `ON CONFLICT (video_id, stage, kie_task_id) WHERE kie_task_id IS NOT NULL DO NOTHING`, inspects asyncpg's `"INSERT 0 0"` status to log a loud `DUPLICATE SKIPPED` line, and keeps the `total_cost` rollup unconditional (SUM-based, correct either way) — fail-soft fully preserved (same try/except, never raises). Provider-id threading: added `task_id_out` (fresh-box-per-call, append-don't-assign — same pattern as C07's clip `task_id_out`) to `ImageClient.generate_and_wait`/`generate_scene_image_zimage`/`generate_with_reference`/`generate_thumbnail_gpt2`/`generate_scene_image_gpt`, threaded through every branch of `image_model_router.generate_scene_image_for_model`, and wired into the 3 call sites that write ONE ledger row per ONE Kie task: `coverage_to_app.py::redraw_asset_image` and pipeline_executor.py's 2 single-image thumbnail paths (`_run_channel_formula_thumbnail`, `run_thumbnail`'s modeled-on-reference branch). Left `kie_task_id=None` (documented, not a gap) on `run_image_variants`/`run_images`/`store_scene` (all aggregate MANY images/tasks into ONE ledger row — a single id can't honestly represent a batch) and on voice/sound/the legacy "from-scratch" thumbnail bot (no real per-unit id ever surfaces there); migration 093's header explains the tradeoff — a synthetic UNIQUE id gives zero protection, a synthetic CONSTANT id would wrongly dedup two legitimate separate spends. Commit (see git log). VERIFIED: +4 tests in `test_generation_ledger.py` (20 total) non-vacuous via `git stash` on `generation_ledger.py` alone (after tightening the fake DB to only enforce dedup when the query text carries `ON CONFLICT`, the stash reproduces the ORIGINAL bug — duplicate row actually lands, not just a missing log line); +7 tests in `test_image_model_router.py` (19 total) non-vacuous via `git stash` on `image_client.py`+`image_model_router.py` (6/7 new tests TypeError on the missing kwarg). Full backend suite 971P/16F/1E = baseline(967)+4 zero new failures, `py_compile` clean, frontend untouched. Live duplicate-scan + `pg_indexes` results pasted in SYSTEM_STATE.md §C16c. Live race-proof deferred → live-verification-queue §C16c. **ff-merged to main** (orchestrator verdict after re-reading `record_ledger_entry`: ON CONFLICT targets the partial index correctly, duplicate-skip logs loudly, sacred never-raises fail-soft intact): purely additive index + `ON CONFLICT DO NOTHING` semantics — can only change behavior on an EXACT `(video_id, stage, kie_task_id)` repeat of a non-NULL key, which is precisely the double-spend race this chunk closes; never fires on two genuinely different generations or on any NULL-id row (never deduped at all). Does not touch C16a's claim logic or C16b's skip-if-done logic.
- **Also done:** C16d · Queue hardening (S7-3/S7-4/S7-7/S7-8/S7-9 fixes, all 5 shipped in one chunk) — **S7-3**: `PipelineExecutor.run_thumbnail(video_id, force=False)` gains a skip-if-done guard (one check before all 3 completion branches — the channel-formula branch is only ever reached FROM run_thumbnail, so gating at the top covers it) that skips regeneration + ledger billing when `videos.thumbnail_url` is already set; `force=True` threaded explicitly by every real "redo" caller (`actions.py::make_action_step` special-cases the "thumbnail" verb the same way it already special-cased `run_script`; `routes/chat.py`'s prompt-studio "Apply & redo"; new `POST /thumbnail/{id}?force=true` mirroring the pre-existing `/clip/{id}?force=true` convention) — traced that `ThumbnailTab.tsx`'s SAME button serves both "Generate Thumbnail" (natural first-run, no force) and "Regenerate" (force=true only when `video.thumbnail_url` already set) off one handler, so the frontend now conditions the query param on that. **S7-4**: `routes/pipeline.py::_enqueue_or_fallback` derives `attempt` from `COALESCE(MAX(attempt),0)+1` over prior `background_tasks` rows (same source main.py's restart-recovery already reads) instead of hardcoding 1 (which collided with arq's own 24h job_id dedup on every legit retry); a genuine dedup-hit now raises the SAME `HTTPException(409, "Task already running")` `_is_task_active` gates already use (frontend already retries on this shape) instead of a silent 200; `**stage_kwargs` threads S7-3's `force` through `job_queue.enqueue_stage`→arq's `enqueue_job`→`worker.py`'s `arq_run_thumbnail`→`_run_stage` so Regenerate works identically whether Redis is up or not. **S7-7**: `/api/health` + `/api/health/detailed` add `"queue": "arq"|"degraded-inprocess"` off `app.state.arq` (no UI banner yet — follow-up). **S7-8**: live duplicate-scan FIRST (0 rows, 468 total rows in `background_tasks`, 0 carry a job_id — arq's never actually been in the loop in prod) → migration 094 (partial UNIQUE index on `job_id WHERE job_id IS NOT NULL`, applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `pg_indexes`) → `task_store.db_persist_task`'s shared INSERT gains `ON CONFLICT (job_id) WHERE job_id IS NOT NULL DO NOTHING`, fail-soft preserved. **S7-9**: new "Per-Stage Resumability" table in `docs/failure-modes.md` — voice/sound-prompts/sound-effects/clips/images-coverage(C16b)/thumbnail(C16d) skip-if-done; research/script/render full-restart (cheap, low-stakes); **upload flagged as a real gap** — no re-publish guard at all, a re-invoke can mint a second YouTube draft (not fixed here, out of this chunk's scope, noted as a follow-up). Commit (see git log). VERIFIED: 17 new tests across 4 files, each confirmed non-vacuous via `git stash` per source file (task_store's race test needed a fake-DB restructure — snapshot-then-yield, not yield-then-snapshot — to actually reproduce the TOCTOU window instead of being accidentally protected by the pre-existing app-level check regardless of the DB fix). Full suite 988P/16F/1E = baseline(971)+17 zero new failures, `py_compile` clean, tsc clean, `npm run build` compiles+typechecks clean (fails only at static-prerender on a pre-existing sandbox env gap, `NEXT_PUBLIC_API_URL` unset — unrelated). Frontend WAS touched (`ThumbnailTab.tsx`, one line changed) — necessary for the force-intent signal to actually reach the backend; noted explicitly since most backend-only chunks say "frontend untouched." Live re-invoke/degraded-mode checks deferred → live-verification-queue §C16d. **ff-merged to main — orchestrator verdict: S7-3/S7-7/S7-8/S7-9 additive (force-vs-skip caller mapping re-verified in actions.py: chat 'thumbnail' verb forces, autobuild finish-chain skips); S7-4's 409-instead-of-silent-no-op accepted because the live scan proved the arq path has NEVER run in prod (0 job_ids in 468 rows) and 409 reuses the exact signal the frontend already handles** (orchestrator should confirm): purely additive guards/fields/index, every existing flow traced and threaded correctly. **S7-4's 409-instead-of-200 half needs one more look before ff-merge**: it's a real behavior change on the (currently dormant in prod — 0 job_ids live) arq-active path — confirm the frontend's existing `_is_task_active`-409 retry handling actually covers this new source too before calling it fully safe.
- **Also done:** C17 · P1.3a `draft_pass` + `finalize` verbs (checklist §1.3, S7 design requirements) — the trust-ladder centerpiece: draft the whole video's CLIPS at the cheapest wired draft tier in one cheap pass (pictures untouched — they're already cheap/stage-shared; "draft" is specifically about the expensive clip-generation step), review, then finalize only the approved scenes at their real routed/premium tier. **Design decision:** `run_clip_generation` gains two additive params — `force_model_id` (draft_pass: EVERY row animates through this model for the call, completely bypassing `resolve_clip_model`, so `assets.routed_model`/`model_override` are NEVER read or written by a draft pass — the routing recommendation survives untouched for finalize to read back later) and `only_scenes` (finalize: mirrors C16b's coverage allowlist — `scene = ANY($3::int[])` scopes the SQL fetch itself, so an unapproved scene's row is never even queried, combined with `force=True` so an already-drafted approved scene's clip gets OVERWRITTEN at the real tier instead of skipped as "already has a clip"). **Lane choice:** both verbs claim `generation_claims` stage `"main"` — `stage_for_verb()` needed ZERO changes since neither verb is in `SIDE_LANES`, and "main" is exactly right because a whole-video clip pass genuinely must conflict with any other main-lane work (script rewrite, images, render) in flight, same as a manual "Animate everything" click. **Pass-identity (the S7 job-key requirement):** new module `generation_passes.py` + migration 095 (`generation_passes` table, UNIQUE `(tenant_id, video_id, pass, scene_set_hash)`, applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`; also added to `schema.sql` — the drift test caught the omission) — deliberately NOT reusing generation_claims (concurrency-only, released the instant a run ends) or C16d's `background_tasks.job_id` (a different, more fragile channel already carrying UI-poll semantics); `scene_set_hash()` hashes SORTED `(scene, target_model_id)` pairs, so approving MORE scenes (or changing a routing override) between two finalize calls mints a NEW hash — never wrongly deduped — while a bare repeat of the identical pass hashes identically and is refused via `already_done()` BEFORE any claim is even attempted; a row is written ONLY on successful completion (`mark_done`, fail-soft) so a failed run always stays retryable. Both verbs are runner-style (`ACTIONS[...]["runner"]`, like `seo`/`approve_scene`) so each owns its explicit claim-acquire + pass-check, mirroring the "build" verb's explicit pattern rather than `_run_pending_action`'s generic (non-claiming) runner path. `estimate_cost`/`cost_breakdown` extended for both verbs (reusing `_routed_clip_rows`/`_resolved_model_id` — one resolver, no parallel math): draft_pass prices every row at `_draft_tier_model_id()` (data-driven cheapest wired `tier="draft"` registry entry — never hardcodes "grok-imagine"); finalize prices only `_approved_scenes()` rows at their real resolved tier; both itemizations sum to exactly `estimate_cost`'s own total. Classifier vocabulary (`routes/chat.py`'s legacy classifier + `agent_brain.py`'s tool-loop brain) both gained `draft_pass`/`finalize` in the verb enum + VERB MEANINGS prose, explicitly distinguished from `build`/"animate everything" (real quality) so the two tiers are never conflated. `[U]` deliberately NONE this chunk (C18 owns GuidedNextStep labels/Approve ticks/savings-line copy) — confirmed `_confirm_card` renders sensible text for both new verbs unmodified. Commit (see git log). VERIFIED: 13 new tests (`test_c17_draft_pass_and_finalize.py`) non-vacuous via `git stash` (12/13 fail against pre-C17 source; the 13th — `scene_set_hash`'s pure-function test — legitimately still passes since it exercises only the new standalone `generation_passes.py` module, unaffected by stashing the OTHER files). Full backend suite 1001P/16F/1E = baseline(988)+13 zero new failures, `py_compile` clean on all 6 touched/added `.py` files. Frontend untouched (no UI surface this chunk — `[U]` is C18's). **Deploy-safety:** ff-merged to main (orchestrator verdict after re-verifying: pass-dedup checked BEFORE claim, claim acquired before dispatch, mark_done only on success, release present in both runners' finally paths, force_model_id gated to wired registry models) — both verbs are brand-new additive registry entries (no existing verb's behavior changes); `run_clip_generation`'s two new params default to `None`/unused for every existing caller (`animate`, the per-scene redo button) → byte-identical; `generation_passes` is a new table (migration 095, applied live) with zero interaction with any existing table's rows; classifier prompt changes are additive vocabulary (existing verb meanings/wording untouched). Live full-cycle (draft → approve 3 → finalize → only 3 regenerate → ledger shows both passes) deferred → live-verification-queue §C17 with an exact recipe.
- **Also done:** C18 · P1.3b GuidedNextStep draft/finalize labels + scene Approve ticks + savings line (checklist §1.3 `[U]`, UX map §2) — the clickable door for C17's chat-only verbs. **`[B]` (thin, two doors one registry):** three new routes in `routes/pipeline.py`, all calling `actions.RUNNERS[verb]` DIRECTLY (the exact function chat's `_run_pending_action` already calls, zero forked claim/dedupe logic) — `POST /actions/{id}/draft-pass` + `.../finalize` share `_run_action_runner()`, which detects whether the runner actually scheduled work by diffing `len(background_tasks.tasks)` before/after (every guard branch inside the runner returns without calling `add_task`, so a zero delta is a reliable signal — never string-matching the runner's free-form chat reply); a non-scheduled reply equal to `actions._ALREADY_WORKING_REPLY` becomes HTTP 409, every OTHER non-scheduled reply ("already drafted", "nothing approved yet") is a graceful 200 `status="skipped"`. `POST /actions/{id}/approve-scene` is the missing clickable half of C15b's `approve_scene` verb — same runner, `background_tasks=None` (the verb never schedules anything). `GET /actions/{id}` (existing) gains an additive `breakdown` field per action (`actions.cost_breakdown`, same call chat's confirm cards already make) and `cost_breakdown()` itself gains one additive key, `scene_count` (distinct scene count behind the itemization) — the ONLY new backend math, needed so "Finalize N approved scenes" reads N server-side instead of guessing from asset-row counts (a scene has multiple rows). **`[U]`:** GuidedNextStep gains a new override branch (checked AFTER the existing failure/running/celebrate branches, so it can never pre-empt a real in-flight task) sitting between the old "Animate scene 1"/"Animate the rest" ladder and "Create your thumbnail" — `action.key==="clips-taste"` + a live unblocked `draft_pass` action → "Draft the whole video (~$X)"; `action.key==="thumbnail"` + a live unblocked `finalize` action with `scene_count>0` → "Finalize N approved scenes (~$Y)"; both fall back to the ORIGINAL pre-C18 ladder byte-identical whenever draft_pass/finalize aren't wired for a video (strict superset, not a replacement). Confirm flow reuses ScenesWorkspaceTab's existing two-tap `confirmable()` shape (tap arms → "Confirm — $X" + Cancel link → tap fires) instead of inventing a new affordance; on fire, `status==="running"` calls the SAME `markStarted()` the file already uses (RUNNING banner/Stop/completion-toast all reused for free), `status==="skipped"` is a plain info toast. A "Skip" link beside the button reuses the file's OWN `start()` handler unchanged (draft-offer skip = pre-C18 navigate-to-Scenes; finalize-offer skip = literally running the thumbnail stage directly, identical to the OLD button) — a fail-safe escape hatch, see the noted gap below. ScenesWorkspaceTab's scene header gained an Approve pill/badge (outline "Approve" ↔ green "Approved ✓", reading `_approved_scenes`' own "any approved row approves the whole scene" rule) calling the new `approveScene()` API, invalidating both `["video-assets", id]` and `["video-actions", id]` (so Finalize's live N/cost refreshes immediately — both components share that query key). Savings line computed in GuidedNextStep from BOTH actions' `breakdown` objects — `draftTotal`/`allPremiumTotal` from draft_pass's (its `all_premium_total` covers every not-yet-clipped row video-wide, stable whether or not draft already ran, since `cost_breakdown` doesn't filter on clip existence), `finalizeTotal`/`sceneCount` from finalize's; the ONLY client math is `combinedTotal = draftTotal + finalizeTotal` (explicitly spec-allowed); renders "Draft $X now + finalize N scene(s) $Y later ≈ $Z total vs $W all-premium" once approved, or a shorter pre-approval variant. **Known gap (documented, not fixed this chunk):** `cost_breakdown`'s finalize quote doesn't know if an approved scene was ALREADY finalized (C17's own pre-existing semantics — real double-spend protection is `generation_passes`' scene-set-hash dedup INSIDE the runner, not the estimator), so the Finalize button can keep re-offering itself with a nonzero quote after it's already run; tapping again is SAFE (runner replies "already finalized... nothing's changed", zero re-spend) but is a UX wrinkle — the "Skip — go straight to the thumbnail" link is the deliberate escape hatch; flagged for a future chunk if it proves annoying live. Commit (see git log). VERIFIED: 20 tests (7 new in `test_c18_guided_actions_ui.py` + 2 new assertions in `test_c17_draft_pass_and_finalize.py`, not new test functions) non-vacuous via `git stash` (all 7 new tests fail `KeyError`/`AttributeError` against pre-C18 source, stash popped clean). Full backend suite 1008P/16F/1E = baseline(1001)+7 zero new failures, `py_compile` clean on all touched/added `.py` files. Frontend: `npx tsc --noEmit` clean; `npm run build` compiles+typechecks clean (fails only at the pre-existing sandbox `NEXT_PUBLIC_API_URL` prerender gap, same as every prior chunk). **Deploy-safety:** ff-merged to main (orchestrator verdict after re-verifying tenant scoping on all 3 new routes and that they dispatch the IDENTICAL actions.RUNNERS function objects chat uses — two doors, one verb, no fork), safe BOTH skew directions — new backend + old frontend: three routes and the `breakdown` field are pure additions an old frontend never reads; new frontend + old backend (the real skew risk since VPS frontend only redeploys `--with-frontend`): every new frontend read is optional-chained with a `??` fallback, so a missing `breakdown` key resolves both offers and the savings line to "nothing to show" rather than crashing, and the three new POST routes 404 gracefully (caught, toasted) on an old backend. Live click-through (draft → tick 3 scenes → finalize → confirm regenerate-only-3 + savings-line numbers match ledger) deferred → live-verification-queue §C18 with an exact recipe (supersedes manually triggering §C17's verbs once both are deployed together).
- **Also done:** C16e · Upload re-publish guard (checklist Phase 1, found by C16d's S7-9 resumability pass) — `PipelineExecutor.run_upload(video_id, force=False)` gains the same skip-if-done shape as C16d's `run_thumbnail`: checks `videos.youtube_url`/`youtube_video_id` right after fetching the video, BEFORE the channel_profiles lookup (so a skip never even reaches the native OR legacy upload path) — returns `{"status":"completed","skipped":True,"youtube_url":...,"youtube_video_id":...}` + an activity log line. Every real caller (the autobuild finish chain's `"rendered": self.run_upload` mapping, the arq/queue stage runner, `claude_orchestrator.py`'s skill dispatch, the manual `POST /upload/{video_id}` route, the chat "upload" verb) passes nothing and gets the default skip; `force=True` is the only bypass, exposed via the manual route's new `?force=true` (mirroring `/thumbnail/{id}?force=true`) and `arq_run_upload`'s matching param — not yet called by any caller this chunk (no UI hook needed since `UploadTab.tsx`'s button already self-disables once `youtubeUrl` is set). **Caller-intent mapping + design decision (deliberately DIFFERENT from C16d's thumbnail verb, which ALWAYS forces):** a chat "upload it"/"publish" turn on an already-uploaded video is judged far more likely an accidental double-tap (repeated turn, or the autobuild chain having just uploaded it) than genuine "make a second draft" intent — because unlike "redo the thumbnail" (unambiguous; no other way to say "regenerate"), and because a duplicate YouTube draft is real non-refundable quota burn (~1,600/10,000 daily units), not just a redundant free call. New shared helper `actions.already_uploaded_reply(tenant_id, video_id)` returns a friendly message naming the existing URL (or id) when already uploaded; `routes/chat.py::_run_pending_action`'s "upload" branch checks it BEFORE claiming a `generation_claims` lane or scheduling `background_tasks` — a double-tap gets the friendly reply immediately, wasting neither a claim nor a task. The executor's own `force=` guard remains the real money/quota-safety backstop (checked independently on every call); the chat check only keeps the reply honest. Commit (see git log). VERIFIED: 11 new tests (`test_c16e_upload_skip_if_done.py`) across all 3 layers (executor guard incl. upload-client-not-called assertion via monkeypatched `youtube_publish.upload_video_to_youtube` raising if reached; `already_uploaded_reply` unit tests; `chat._run_pending_action`'s upload branch — double-tap returns the reply with zero dispatch, not-yet-uploaded proceeds normally) non-vacuous via `git stash` (8/11 fail against pre-fix source: boom-mocks actually reached, `AttributeError` on the missing helper/import). Full backend suite 1019P/16F/1E = baseline(1008)+11 zero new failures, `py_compile` clean on all 5 touched + 1 new file. Frontend untouched (confirmed via `git diff --stat` — no `storyengine/frontend` paths). Live re-invoke-costs-zero-quota proof deferred → live-verification-queue §C16e (needs a real connected YouTube channel + an already-uploaded test video). **ff-merged to main** (orchestrator verdict — grep-confirmed only ONE production call site of upload_video_to_youtube, inside the guarded run_upload; the chat-skips-instead-of-forces deviation from C16d's thumbnail pattern is accepted as correct for non-refundable quota): purely additive `force` params (all default `False`, preserving prior behavior shape except now correctly refusing a duplicate draft), one new standalone helper, one new early-return branch scoped to `verb == "upload"` only — no schema change (columns pre-existed), no existing caller signature broken.
- **Also done:** C20 · P2.1a `style_presets` table seeded from the 5 Python visual profiles' `TemplateMetadata` (neutral_v1, holographic_hud, cinematic_dossier, clay_mannequin, cinematic_illustration — copied verbatim from each module, NOT invented copy) + `GET /api/style-presets` (mirrors `/api/models`'s tenant-auth posture) + `create_video` accepts + validates `style_preset_id` (400 on unknown/inactive, matching the `reference_url` precedent) + executor mapping. Migration 096 (table + idempotent `ON CONFLICT DO UPDATE` seed refreshing only code-derived columns, never `active`/`preview_url` + `videos.style_preset_id` FK) applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema` + a live 5-row content check; `schema.sql` updated (FK attached via a trailing `ALTER TABLE` since `style_presets` is defined after `videos` in the file, which runs top-to-bottom on a fresh DB). Executor: new `pipeline_executor._resolve_visual_profile_id(idea)` gives `style_preset_id` precedence over the legacy free-text `visual_style` field for the `VISUAL_PROFILE` env seam (checklist's "existing seam at L6358", re-verified now at ~L6385 after C19's sweep), fail-soft to the EXACT prior expression when absent. **Real pre-existing bug surfaced (not fixed here, flagged for C21):** `videos.visual_style` is populated today by the 6-shallow-preset system (`"Pixar 3D"` etc, traced via `GET /style-default`), not a Python profile id — so the seam has likely been silently no-op'ing to `neutral_v1` for every tenant until this chunk's `style_preset_id` gave it its first guaranteed-valid input. **S9-5 resolved to THREE axes, not two** (full breakdown SYSTEM_STATE.md §C20): `style_presets` (this chunk, structural image-engine choice) is COMPLEMENTARY to — not a duplicate of — the existing `visual_styles` CRUD + hardcoded `VISUAL_PRESETS` (both feed a different axis, `VISUAL_STYLE_DESCRIPTION`, a free-text aesthetic overlay); C21 reconciles the latter two, never merges axis 1 into either. Commit (see git log). VERIFIED: 10 new tests (`test_c20_style_presets.py`) non-vacuous via `git stash` (collection ImportError against pre-C20 source), full backend suite 1029P/16F/1E = baseline(1019)+10 zero new failures, `test_schema_sql_migrations_drift.py` confirms schema.sql was actually updated, `py_compile` clean on all 6 touched/added `.py` files. Frontend untouched (no `[U]` this chunk — C21 owns the gallery). Live "pick preset → prompts carry its style" deferred → live-verification-queue §C20 (completes together with C21). **Deploy-safety:** ff-merged to main (orchestrator verdict — applied the C16b lesson: confirmed the new column is mapped in supabase_adapter and every read is fail-soft .get() with default, so the missing-SELECT-column bug class can't occur) — purely additive (new table, new nullable FK column defaulting NULL, new route, two new optional Pydantic fields defaulting `None`); `_resolve_visual_profile_id`'s fail-soft chain reproduces the exact prior expression when `style_preset_id` is absent (every existing video, proven by test); no existing migration/route/model field renamed or removed.
- **Also done:** C19a · S9-1/S9-2/S9-8 frontend-state fixes (gate before C21) — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C19a. **S9-1:** hoisted the ONE `useTaskWatcher` into `pipeline/[videoId]/page.tsx`; new `TaskWatcherBridge` (`{running, message, markStarted, subscribe}`, chosen as a prop, not context — only 10 direct children of one page consume it) + new `useSharedTaskWatcher` hook (`hooks/use-task-poller.ts`) let `GuidedNextStep`, `ScenesWorkspaceTab`, and 7 other tabs (Research/ScriptVoice×2/Characters/Environments/Sound/Thumbnail/Render) subscribe instead of each opening their own 3s interval against `getPipelineTaskStatus` (was up to 3 concurrent identical polls, now 1) — every tab's own `onComplete`/`onFailed`/`onProgress` body AND its `enabled`-gate (only reacts to work IT believes it started) preserved byte-for-byte, verified by reading each one (several fire attributed toasts like "Sound generation failed" that would have mis-fired on unrelated tasks had the gate been dropped instead of preserved). **S9-2:** `getNextAction()` (`lib/next-action.ts`) gained an optional `clipPriceByModel` param + `resolveClipCost()` helper that prefers it over the mutable `CLIP_COST_PER_MODEL` cache; `GuidedNextStep` now passes its own already-fetched `videoActions.prices.clip` straight through — reactive same-render, mirroring `ScenesWorkspaceTab`'s `priceForModel` pattern, no more $0.30-fallback-on-first-paint. **S9-8:** decided to KEEP the 5s `video-assets` `refetchInterval` (not drop it) — reasoned + documented inline: it's the only thing keeping that query (and the cost estimate) fresh page-wide/every-tab, since the watcher's onProgress invalidation is Scenes-tab-scoped and SSE only fires on terminal/stage-change events, never mid-stage. Known minor disclosed deviation: `RenderTab` used to poll at 10s, now rides the shared 3s cadence (can only notice completion sooner, never later; cost is immaterial over a 10-20min render). Out of scope, confirmed dead via `grep -rln`, left untouched for C19b: `ScriptTab.tsx`/`StoryboardTab.tsx`/`VoiceReviewTab.tsx`. Commit (see git log). VERIFIED: `tsc --noEmit` clean; `npm run build` compiles+typechecks clean (fails only at the pre-existing `NEXT_PUBLIC_API_URL` prerender step, confirmed pre-existing via `git stash` + rebuild against unmodified main); grep-proof exactly one `useTaskWatcher(` mount + `useSharedTaskWatcher(` in all 9 live consumers, zero in dead files. No backend touched (nothing to run). No frontend test harness exists in this repo — no runtime click-through this session; deferred with an exact recipe → live-verification-queue §C19a. **Deploy-safety:** ff-merged to main (orchestrator verdict — frontend ships only via a deliberate `--with-frontend` deploy, and the live click-through is queued §C19a to run before/at that deploy, so the no-runtime-test gap is covered at the right layer; ships with the next `--with-frontend` deploy alongside C14/C18/C20's frontend pieces) — every side-effect body unchanged, only the polling mechanism consolidated; risk is a stale bridge reference across renders, ruled out by `useMemo`-stabilizing it and `tsc`/build catching any prop-shape mismatch.
- **Also done:** C21a · P2.1b part 1 — S9-3 card-kind lookup + New Video "Look Engine" gallery — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C21a. **Split from C21** (checklist §2.1 [U]): tracing the deletion FIRST (per the wiring-audit protocol) surfaced that `routes/chat.py`'s reference-video vision-style detector (`_detect_reference_style_preset`/`_annotate_style_recommendation`) also imports `producer_prompt.VISUAL_PRESETS`, but to classify a video's ANIMATION MEDIUM (pixar_3d/flat_2d/anime/...) — a totally different question than "which of the 5 engine presets" the new gallery picks from, with no valid mapping between the two vocabularies. Deleting the dict blind would either crash that import or silently mis-wire a recommendation — an Anti-Bandaid-rule stop, not a same-session fix. **Shipped this chunk (frontend-only, zero backend touched):** (1) S9-3 — new `cardKind()` in `ChatCore.tsx` is now the ONE place that classifies a card (`prompt_apply`/`confirm_action`/`secure_key`/`connect`/`images`/`generic`), replacing the 4 scattered `card.id`-string-match sites the audit flagged (the action-card finder, the 3-branch action-card render block — now one `ACTION_CARD_RENDERERS` lookup — the inline scene-boards filter, the connect-button check); every prop/handler carried over byte-identical, confirmed by diff. (2) New Video "Look Engine" gallery (`app/pipeline/page.tsx`) — the FIRST caller to ever send `style_preset_id` (C20 wired the backend end-to-end, nothing sent it until now): new `useStylePresets()` hook (`hooks/use-style-presets.ts`, `["style-presets"]` query, same fetcher C21b's chat door will reuse) + new `StylePresetGallery` component (loading/error-with-retry/empty states; onError-safe preview images — no seeded preset has a `preview_url` yet, so "no url" renders a labeled placeholder, never a broken-image icon) sits in a clearly labeled NEW section ABOVE the renamed "Style description" section (was "Visual style" — same fields/logic untouched), with helper copy explaining the two axes are independent (pick one, both, or neither). (3) S9-4 also fixed on the PRE-EXISTING 6-item preset pickers in both doors (`PresetPreviewImage`/`PresetOptionImage` onError wrappers) since that picker stays live until C21b. `visual-presets.ts`/`producer_prompt.VISUAL_PRESETS` NOT deleted yet — that's C21b, along with the chat LOOK card wiring (adds one new `cardKind()` entry, per the lookup this chunk built for exactly that) and the vision-detector fix (recommended approach written up in SYSTEM_STATE.md §C21a). Commit (see git log). VERIFIED: `npx tsc --noEmit` clean, `npm run build` compiles+typechecks clean (same pre-existing `NEXT_PUBLIC_API_URL` prerender-only failure as every prior frontend chunk). Grep-proof: zero `card.id === "`/`c.id === "` comparisons in `ChatCore.tsx` outside `cardKind()`'s own definition + the pre-existing unrelated `isSliderCard` helper. Backend untouched (confirmed via `git status --short`) — no Python suite run, nothing to run. No frontend test harness exists; live click-through (gallery renders 5 real presets, a pick round-trips to `videos.style_preset_id`, both axes travel independently) deferred → live-verification-queue §C21a, extending §C20's deferred full-loop check. **Deploy-safety:** ff-merged to main (orchestrator verdict — the pre-deletion trace that caught the dual-vocabulary entanglement is exactly the anti-stub behavior the loop exists for; split accepted) — additive optional field + behavior-preserving refactor + strictly-better onError handling, backend untouched.
- **Also done:** C21b · P2.1b part 2 — DELETE `visual-presets.ts` + `producer_prompt.VISUAL_PRESETS` + producer/chat backend sourcing + chat gallery card — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C21b. Both hardcoded copies of the six style-DESCRIPTION ids DELETED entirely, replaced by ONE source: new `channel_format.STYLE_DESCRIPTIONS`, served over new `GET /api/style-descriptions` (a thin static-dict view, no DB table needed — this axis was never DB-backed) and read by the reference-video vision classifier (renamed/reframed as ANIMATION-MEDIUM classification, not "visual presets" — same 6 ids, honest name), `_spec_to_create_request`'s axis-B mapping (unchanged behavior, re-sourced only), `routes/projects.py::_channel_style_dna`, and both frontend doors via new `use-style-descriptions.ts` (with a `FALLBACK_WIRED_MODELS`-style frozen skew-fallback array for old-backend/network-failure only). **Correction to §C21a's own handoff recommendation, flagged not silently followed:** that text said to drop the axis-B lookup "entirely" and set `style_preset_id` "directly from the card pick" — taken literally this would have repurposed the existing 6-option "style" card into the 5-option engine axis, breaking `image_style_override`/the C13b guardrail; instead the axis-B mapping was KEPT (just re-sourced) and `style_preset_id` was added as a NEW, independent, ADDITIVE field via a separate optional `"look_engine"` card — matching the chunk's own explicit "BOTH axes" requirement (UX map §3), which is the correct read over the prior handoff's compressed phrasing. New fail-soft `_style_presets_brief(tenant_id)` (live `style_presets` table read, frozen 1-line fallback on DB error/empty table) teaches the producer this card's real, current ids; wired into both `_seed_producer` and `chat_turn`'s intake brief chains. `_handle_approve` merges `selections["look_engine"]` into `spec["style_preset_id"]`, mirroring the pre-existing `style`→`visual_style` merge exactly. `ChatCore.tsx`'s `cardKind()` gained exactly one new branch (`"look_engine"`) rendering the SAME `StylePresetGallery`/`["style-presets"]` query as the New Video gallery (C21a) — confirming that lookup really was built for one-line new-kind additions, as its own docstring claimed. A THIRD hardcoded copy of the six ids (`ProductionPlanCard`'s `PRESET_LABELS`, not previously flagged by the audit) found while tracing and fixed too. 22 new tests in `test_c21b_style_axis_split.py`, non-vacuous via `git stash` (whole module fails to import against pre-C21b source — `STYLE_DESCRIPTIONS` doesn't exist yet). Full backend suite 1051P/16F/1E = baseline(1029)+22 zero new failures (16 failing test NAMES diffed byte-identical against the stashed pre-C21b baseline run, not just the count). `py_compile` clean. Frontend: `tsc --noEmit` clean; `npm run build` compiles+typechecks clean (same pre-existing `NEXT_PUBLIC_API_URL` prerender gap). Grep-proofs: zero real `VISUAL_PRESETS` code references backend-wide (regex distinguishing real usage from historical comments); zero remaining imports of the deleted `@/lib/visual-presets` module frontend-wide; zero new `.id === "` string-match sites in `ChatCore.tsx` outside `cardKind()`/`isSliderCard`. No live chat round-trip this session (no paid Anthropic/Kie key in sandbox) — deferred with an exact recipe → live-verification-queue §C21b (both-axes-through-chat, the new card's rarity/optionality, the vision classifier's unaffected behavior, the DB-error fail-soft path). Closes checklist §2.1 `[U]` for good (both C21a's New Video gallery + this chunk's chat door + deletions). **Deploy-safety:** ff-merged to main (orchestrator verdict — verified all re-pointed STYLE_DESCRIPTIONS reads are .get()-fail-soft incl. the create path + vision classifier; the worker's correction of §C21a's own faulty recommendation is accepted and is exactly the right skeptical behavior) (no schema/migration this chunk; additive-only fields both directions; skew analysis in SYSTEM_STATE.md §C21b — orchestrator to confirm before merge).
- **Also done:** C19b · S9-6 dead-code delete — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C19b. Deleted 13 confirmed-dead files (4,017 lines), each re-verified fresh via `grep -rn` for both import path and bare JSX name (not trusted from the 2-day-old audit, since C19a/C21a/C21b had touched adjacent files since): all 10 flagged `components/video-detail/*.tsx` (`info-tab`, `panel-magnifier`, `performance-tab`, `pipeline-action-bar`, `scene-editor`, `script-tab`, `segment-list`, `stage-advancer`, `storyboard-viewer`, `thumbnail-tab`), plus `components/production/ScriptTab.tsx` (1,114 lines, superseded by `ScriptVoiceTab.tsx`, frozen field-name bug), `StoryboardTab.tsx` (350 lines), `VoiceReviewTab.tsx` (525 lines) — all zero importers. Kept 3 `video-detail/` files with live importers (`cost-ledger-chip.tsx`, `prompt-expander.tsx`, `voice-player.tsx` — one more than the audit's "2 live" since code moved). **`storyboards/page.tsx` route NOT deleted — flagged instead**, per the chunk's own explicit instruction ("if the operating docs reference it, flag instead of delete"): `storyengine/agents/blueprints/frontend.md`'s route catalog and `docs/reports/WIRING_STATUS.md` both still document it as a real, WIRED page, even though no in-app `Link`/`router.push` reaches it anymore (confirmed by grepping every `/pipeline/${...}` navigation site — all target the base page, none append `/storyboards`). Needs a follow-up decision (confirm docs are stale + delete together, or re-link it) — not this chunk's call. Commit (see git log). VERIFIED: `npx tsc --noEmit` clean; `npm run build` compiles+typechecks clean with `NEXT_PUBLIC_API_URL` set (all 32 routes build incl. the kept storyboards page); without the env var, fails only at the same pre-existing prerender gap every prior frontend chunk hits. No backend files touched — backend suite not re-run. **Deploy-safety:** ff-merged to main (orchestrator verdict — fresh re-verification over stale audit data was the right call; storyboards-route doc/code drift stays flagged for a docs-vs-delete decision) — pure deletion of code proven to have zero live importers at delete-time, zero behavior change on any reachable path, the one file left alone changes nothing either way.
- **Also done:** C22 · P2.1c conversational style creation, "make me a new style…" (checklist §2.1 [U] closure, UX map §3) — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C22. **Scope decision (stated explicitly, per the brief):** a chat-created "style" is a tenant-owned STYLE DESCRIPTION — a row in the EXISTING `visual_styles` CRUD (migration 010, profile page, C20's axis-2) — NOT a new `style_presets` engine row (those are Python rendering engines, not conversationally authorable); the CRUD was already exactly fit for purpose, so this chunk adds a conversational front door onto it rather than building a 4th style system. Two new home-producer `profile_ops` (`draft_style`, `use_style`, taught in `producer_prompt.py` alongside `remember`/`forget` with the same "wired up" framing — C15c's precedent for HOW to add an op): `draft_style` ONLY stashes `state["pending_style_draft"]`, proven to touch zero DB calls (`test_draft_style_stashes_pending_draft_and_touches_no_database` leaves `fetch_one/fetch_all/execute` bound to `_boom` stubs). **The actual hard part — confirm-before-save as a backend guarantee, not an LLM-trust hope:** new `chat_turn` step 3.6 intercepts `selections.style_draft` BEFORE the normal intake turn (which would otherwise just hand it to the LLM as text) and routes to new `_handle_style_draft_confirm`, which is the ONLY code path that can create a `visual_styles` row — and only on the creator's own "yes" tap — via `routes.visual_styles.create_visual_style(...)` called DIRECTLY (same function `POST /api/visual-styles` calls, same pattern `_handle_approve` already uses to call `create_video` directly; one write path, never forked). New `style_draft` preview card (`_style_draft_card`, reusing `ChatCard`'s existing `label`/`body`/`options` fields — no new frontend-facing field) is attached ONLY when THIS turn's ops genuinely included `draft_style` AND a draft is actually pending (`_maybe_attach_style_draft_card`), so the LLM's prose alone can never manufacture a save-ready card. "Use <name>" resolves via the CRUD's OWN `activate_visual_style` (exact-name then `ILIKE` fallback) — channel-wide, mirroring `identity.build_identity_context`'s existing precedence chain; a NEW `_visual_styles_brief(tenant_id)` (fail-soft, empty-when-nothing-saved — unlike `_style_presets_brief`'s frozen fallback) also lets the producer resolve "use my X style for THIS video" straight into `spec.image_style_override` without switching the channel default. **Deliberately NOT touched, flagged explicitly:** the docked (in-video) co-pilot's `kind` classifier and `agent_brain.py`'s tool-loop schema — every existing channel-config verb (`add_competitor`, `set_niche`, `set_channel_format`, …) lives ONLY in the home producer's `profile_ops`, never the docked schema, since channel-level config has never been a docked-copilot concern and there's no existing path to change an ALREADY-CREATED video's style anyway (that's the UX map's separate, unbuilt "video header chip" feature) — extending the docked schema here would have been scope creep. Frontend: new `"style_draft"` `CardKind` entry in C21a's `cardKind()`/`ACTION_CARD_RENDERERS` lookup (one more entry, zero new string-match branches — grep-proofed) + new `StyleDraftCard` component (text-only preview, no image — the cost-cap constraint: a preview render would be paid generation with no quote gate); on save, `queryClient.invalidateQueries({queryKey:["visualStyles"]})` fires from `ChatCore.tsx` so the Profile page reflects it without waiting out the 30s default `staleTime` (chat and `/profile` are different route trees but share ONE `QueryClient` via the root `Providers`). `ScenesWorkspaceTab.tsx` NOT touched this chunk (S9-7's trust-ladder hook extraction correctly deferred — see below). Commit (see git log). VERIFIED: 23 new tests (`test_c22_style_draft.py`) non-vacuous via `git stash` (all 23 fail against pre-C22 source — `AttributeError` on the new functions). Full backend suite 1074P/16F/1E = baseline(1051)+23 zero new failures — failing/erroring test-name list confirmed BYTE-IDENTICAL against a full stashed-baseline rerun via `diff` (not just a count match). `py_compile` clean. Frontend: `npx tsc --noEmit` clean; `npm run build` compiles+typechecks clean (same pre-existing `NEXT_PUBLIC_API_URL` prerender gap). No live conversational round-trip this session (no paid Anthropic/Kie key in sandbox) — deferred with an exact recipe → live-verification-queue §C22. Closes checklist §2.1 `[U]` for good (the gallery + this chunk's create door together). **Deploy-safety / ff-merged to main** (orchestrator verdict — the deterministic pre-LLM confirm interception is the right money-safe pattern: no LLM misfire can create a row; reuse-not-fork of the CRUD write verified by pinned payload test): two new `profile_ops` verbs an old backend simply never emitted/recognized before (an unrecognized op was already silently ignored by the existing `if kind == ...` chain); one new `ChatCard` id an older frontend build falls through to `cardKind()`'s `generic` case for, same as every prior new card kind; no existing route/migration/Pydantic field changed or removed; the CRUD write path itself (`routes/visual_styles.py`) is untouched, only called from a new call site — new backend + old frontend and new frontend + old backend both degrade to "card/op simply doesn't render/fire," never a crash.
- **Also done:** C23 · P2.2 camera-preset chips: `/api/camera-presets` + scene chip + sheet (UX map §4; checklist §2.2) — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C23. **Prep commit first (S9-7, the audit's own gate on this chunk):** extracted the clip trust-ladder/auto-resume state machine out of `ScenesWorkspaceTab.tsx` into new `hooks/use-clip-trust-ladder.ts` — `generatingClipIds`/`failedClipIds`/`confirmKey` state, `clipResumeRef`/`prevRunningRef`, `startClipTask`/`animateOne`/`animateScene`/`animateAll`/`maybeResumeClips`, the auto-resume trigger effect, `confirmable()`; the storyboard chain (`chainRef`/`generatingScene`) and the shared `onComplete`/`onFailed`/Stop handlers stayed in the component (they serve both concerns) and now reach into the hook's exposed setters/`cancelResume()`. 2403→2321 lines (-82), behavior-preserving (tsc + build clean). Commit `ffab537` (`C23-prep: ...`). **Main chunk:** new `GET /api/camera-presets` (`routes/camera_presets.py`, registered in `main.py`) reads `image_prompts.engine.camera_moves.py`'s catalog server-side via `get_move()` — curated to 12 ids (`dolly_in, dolly_out, crash_zoom_in, slow_zoom_in, pan_right, tilt_up_reveal, crane_up_reveal, drone_orbit, orbit_right, whip_pan, handheld_follow, static_locked`), auth mirrors `/api/models` (tenant-required, not tenant-scoped data). New `assets.camera_preset_id` (migration 097, live-confirmed via Supabase MCP against `wrromlupsmyzrrcqlucn`, mirrors `model_override`/migration 090's NULL-falls-through shape exactly) written by new `PATCH /api/assets/{id}/camera-preset` (`routes/assets.py`, same tenant-scoping + `get_move()` validation as the model-override endpoint). **The composition seam:** new pure function `pipeline_executor._apply_camera_preset_override(prompt, camera_preset_id)` — a hit REPLACES the composed prompt outright with the preset's own `motion_prompt` (guaranteeing the [V] contract literally, not just "contains"), a miss (NULL/blank/unknown — every row before C23) is byte-identical; wired into `run_clip_generation._one`'s SILENT/non-dialogue shot branch only (the dialogue/speaking-shot branch is a disclosed, deliberate gap — flagged in SYSTEM_STATE.md §C23, not silently skipped). **Conversational door:** new `camera_preset` verb in `actions.py` (free, no confirm card, same as `approve_scene`) with `_runner_camera_preset` resolving free text ("use a crash zoom on scene 12") via `get_move()` first then a small alias map, writing the SAME `camera_preset_id` column scene-wide; added to BOTH classifiers that need it — `agent_brain.py`'s docked-copilot tool-loop schema and `routes/chat.py`'s legacy fallback — same two places `approve_scene` lives (the C15b precedent the task named). **Frontend:** new camera-move chip in `ScenesWorkspaceTab.tsx`'s `SegmentCard` (next to the C14 model badge, same gating/manual-dot convention) driven by new `describeCameraMove()` helper (fail-safe: camera_preset_id → catalog name; else camera_movement parsed; else "Auto" — never a broken chip), tap opens new `CameraPresetSheet` (reuses the `ModelOverrideSheet` pattern exactly, grouped by purpose per UX map §4). VERIFIED: 20 new tests (`test_c23_camera_presets.py`) across all 4 layers (endpoint shape/curated-count, PATCH validation, the pure composition function's byte-identical/contains-contract, the runner's alias resolution + tenant/scene scoping), non-vacuous via `git stash` (ImportError on the new function against pre-C23 source). Full backend suite 1094P/16F/1E = baseline(1074)+20, zero new failures — failing-test-name list byte-identical to a fresh stashed-baseline rerun via `diff`. `py_compile` clean. Frontend: `tsc --noEmit` clean; `npm run build` compiles+typechecks clean (32/32 routes, same pre-existing `NEXT_PUBLIC_API_URL` prerender gap). No live pick→animate→verify-motion-prompt round trip this session (no paid Kie/Anthropic key, no live DB in the sandbox) — deferred with a detailed recipe → live-verification-queue §C23, including an explicit check on whether the disclosed dialogue-branch gap is really inert live. Closes checklist §2.2 for good. **Deploy-safety / ff-merged to main** (orchestrator verdict — NULL-path byte-identity proven, speaking-branch scope-out accepted as honest and correctly reasoned): additive-only both directions (new endpoints an old frontend never calls; a new frontend against an old backend 404s on `/api/camera-presets` but fails soft — chip still renders via the `camera_movement` fallback, sheet just shows a load-failure message); every touched hot path (`run_clip_generation._one`) proven byte-identical when the new column is NULL, which is every row before this migration.
- **Also done:** C24 · P2.3 script voice profiles selectable (checklist §2.3) — full detail in SYSTEM_STATE.md §C24. Mirrors C20's `VISUAL_PROFILE` seam exactly, same "two doors, one write path" law. `shared.profiles.script/*.py` (`neutral_v1` default, `power_doctrine_v2`/`power_doctrine_v1` opt-in) already existed as a runtime engine but had no per-video selection. New `videos.script_profile` TEXT column (migration 098, applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema`) — **no FK** (unlike `style_preset_id`): the catalog is a small code-reviewed Python registry (3 rows), not admin-mutable table data, same "no new DB table" rationale as `camera_preset_id`/migration 097. New `GET /api/script-profiles` (`routes/script_profiles.py`, registered in `main.py`) reads `shared.profiles.script.list_profiles()`/`load_script_profile()` server-side, copy pulled verbatim from each profile's own `template_metadata` (nothing invented) — `neutral_v1` sorts first as `is_default`. New `IdeaFields.SCRIPT_PROFILE = "Script Profile"` (the exact Airtable field name the profile system's own README already documented but nothing had wired) + `supabase_adapter.IDEA_FIELD_MAP` entry — since `_row_to_idea`/`_get_video` `SELECT *`, the column flows through automatically (C16b lesson, `.get()` fail-soft). **The executor seam:** new `pipeline_executor._resolve_script_profile_id(idea)`, byte-for-byte mirror of `_resolve_visual_profile_id` in shape: `(idea.get(SCRIPT_PROFILE) or "").strip() or "neutral_v1"`, wired into `_load_idea` right next to `VISUAL_PROFILE` (`os.environ["SCRIPT_PROFILE"] = ...`, set UNCONDITIONALLY — same stash-proofing as `VISUAL_STYLE_DESCRIPTION`'s "a previous tenant's value can never leak in"). Confirmed the consumer: `script/brief_translator/__init__.py`'s `self.profile = load_script_profile()` (no-arg call — env-var-or-default is the only precedence path it exercises), and confirmed the engine's OWN default is `"neutral_v1"` (`DEFAULT_PROFILE_ID`) — so NULL/blank reproduces the pre-C24 script voice byte-identically; Power Doctrine is never the fallback anywhere (storyengine/CLAUDE.md: "Power Doctrine as a default identity... deleted on purpose, don't resurrect"). **Write-time validation:** new `routes/videos.py::_resolve_script_profile(script_profile)` (sync — checks `list_profiles()` in-process, no DB round-trip needed, unlike the async `_resolve_style_preset_id`), wired into BOTH `create_video`'s INSERT and `update_video`'s generic PATCH `allowed_fields` (the ScriptVoiceTab door) — one validation, one column, both doors. `get_video`'s SELECT/response also gained the field. **Conversational door:** new `script_profile` verb in `actions.py` (`paid: False, needs: None` — settable before or after a script exists, no confirm card) with `_resolve_script_profile_text` resolving free text ("write it in the investigative style" → `power_doctrine_v2`, "use the framework explainer voice" → `power_doctrine_v1`) via a real-id-first-then-alias-map pattern identical to C23's camera resolver; exact clear-words ("auto"/"clear"/"default"/"neutral"/"normal") always land on `None`, NEVER on a Power Doctrine id (pinned by its own test) — added to BOTH classifiers (`agent_brain.py`'s tool-loop schema + VERB MEANINGS, `routes/chat.py`'s legacy schema + ACTIONS list + prose), same two places `camera_preset` lives. **Frontend:** new shared `["script-profiles"]` query (`hooks/use-script-profiles.ts`, mirrors `use-style-presets.ts`); New Video "Advanced options" gains a labeled native `<select>` (description line below it, pulled from the API, never invented) wired into `handleCreate`; `ScriptVoiceTab.tsx` gains a new self-contained `ScriptVoiceCard` (placed after the top action bar, before the Script System Prompt editor — explicitly documented in-file as a DIFFERENT axis from the pre-existing `CustomVoiceCard` just below it, which is the ElevenLabs AUDIO voice, not the editorial WRITING voice) writing through the same `updateVideo` PATCH path. VERIFIED: 19 new tests (`test_c24_script_profiles.py`) across all 5 layers (endpoint shape/copy-provenance, write-time validation, the executor seam's byte-identical/stash-proof NULL contract, `update_video`'s wiring, the conversational runner's alias resolution + never-Power-Doctrine-on-clear guarantee). Full backend suite **1113P/16F/1E = baseline(1094)+19, zero new failures** — failing-test-name list confirmed BYTE-IDENTICAL against the pre-change baseline via `diff`, not just a count match. `py_compile` clean on every touched/added `.py` file. Frontend: `npx tsc --noEmit` clean; `npm run build` compiles+typechecks clean (32/32 routes with `NEXT_PUBLIC_API_URL` set — same pre-existing prerender-only gap every prior frontend chunk hits, confirmed cosmetic by re-running with a dummy value). Also spot-checked `skills/video-pipeline/tests/test_pipeline_integration.py`: 2 pre-existing failures confirmed unrelated (image-prompt marker assertions; reproduce identically with the one touched pipeline-package file, `pipeline_constants.py`, stashed out via `git stash`). Checklist §2.3 left UNCHECKED on purpose per this chunk's own instructions: `[D]`/`[B]`/`[U]` are built and unit-verified, but the full `[V]` ("generate the same topic under both profiles; scripts differ per profile laws") is a real paid Claude script-generation call, deferred with an exact 6-step recipe → `tasks/live-verification-queue.md` §C24 — only tick §2.3 once that live check actually passes. **Deploy-safety / ff-merged to main** (orchestrator verdict — Power-Doctrine-never-by-default pinned by test, honoring the CLAUDE.md deletion rule; §2.3 checkbox honestly left open pending the paid live [V]) (additive-only: `script_profile` NULL for every existing row, no backfill; executor seam proven byte-identical on NULL/blank; both write doors reject unknown ids rather than silently storing garbage; skew both directions degrade fail-soft — an old frontend never sends the field, a new frontend against an old backend 404s on `/api/script-profiles` and the select/card degrade to just "Neutral (default)", never a crash). No known gaps analogous to C23's dialogue-branch caveat — script profiles only affect `brief_translator`'s prompt assembly text, not a per-shot composition path.
- **Also done:** C25a · S5-1 BLOCKER fix — media proxy tenant auth — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C25a. Traced how `<img>`/`<video>` tags actually authenticate today BEFORE picking a mechanism (the chunk's own stated trap): found the codebase already has an accepted precedent for exactly this problem — `auth.verify_token` accepts a JWT via `?token=` for SSE, and `routes/videos.py::create_audio_token`/`_audio_token_tenant` already do the same for `<audio>` playback. C25a extends that SAME query-param-JWT pattern to `/api/media/drive/{file_id}` rather than inventing signed URLs or a cookie-session scheme. Two token shapes both decode to a `tenant_id`: the user's own full session JWT (frontend reuses its existing `localStorage["token"]` unchanged, via new `withMediaAuth()` in `lib/utils.ts`) for every `<img>`/`<video>` the browser renders, and a new short-lived `mint_media_token(tenant_id)` (60 min, `purpose: "media"`) for backend-internal fetches that have `tenant_id` in scope but no live user session to forward (`characters.py`'s cast-sheet + saved-cast vision passes, `environments.py`'s vision rewrite, `pipeline_executor.py`'s talking-clip `_proxy_url`). **The actual BLOCKER fix:** `_ALLOWLIST_SQL`'s 7 `EXISTS` subqueries all gained `tenant_id = $2` (were whole-database, no tenant clause at all); `_is_allowed(file_id, tenant_id)` cache re-keyed to `(file_id, tenant_id)` so no cross-tenant cache bleed; `serve_drive_file` now resolves+requires a valid tenant token BEFORE any allowlist query (proven by a test that makes `_is_allowed` raise if reached pre-auth). Never bakes a token into a PERSISTED url — chat.py's `_media_proxy_url` stays bare; the frontend attaches live auth at RENDER time instead, so old chat history doesn't go stale. Caught mid-fix: `pipeline_executor.py` was appending a cosmetic `.png`/`.mp3` suffix to the TAIL of these urls for Kie's validators — with a `?token=` now present, tail-appending corrupts the token; fixed with new `_with_ext()` that inserts the suffix before the query string. Also fixed 2 frontend cache-buster call sites in `ScenesWorkspaceTab.tsx` that would have produced an invalid second `?` the same way (new `appendQueryParam()` helper). Rate-limit exemption on `/api/media/` KEPT (deliberate call: it existed for perf, not security, and auth now gates the route before any DB/Drive touch either way). Commit (see git log). VERIFIED: 18 new tests (`test_c25a_media_tenant_auth.py`), non-vacuous via `git stash` (11/18 fail against pre-fix code, the other 7 are tenant-agnostic shape checks). Full backend suite **1131P/16F/1E = baseline(1113)+18, zero new failures** (failing-test-name list unchanged). `py_compile` clean on all 4 touched backend files. Frontend: `npx tsc --noEmit` clean; `npm run build` compiles+typechecks clean (32/32 routes with `NEXT_PUBLIC_API_URL` set). Checklist §S5-1 ticked — the BLOCKER is genuinely closed, **C26 is unblocked**. **Deploy-safety — HELD, not ff-merged:** this is the rare chunk where the skew window is a real app-wide risk, addressed explicitly rather than hand-waved. Backend auto-deploys hourly; frontend only on `--with-frontend`. An old (unpatched) frontend against the new backend sends NO `?token=` on any media url → new backend 401s → every image in the app blanks out until the frontend catches up — this is the literal risk the chunk brief warned about, and it's real given the deploy cadence mismatch. No accept-but-log-unsigned grace path was added (that would just leave the tenant-blind bug live a while longer, defeating the fix). **Recommendation: hold this on the branch until the next planned `--with-frontend` deploy, then ship backend+frontend together as one coordinated deploy** (VPS Deploy Coordination Rule §1, lock file held for the duration) — do NOT let this go out via the routine backend-only hourly `git pull`. Required live browser check (Playwright, not self-eval) queued at `tasks/live-verification-queue.md` §C25a, to run immediately after that coordinated deploy: every image surface (Scenes workspace, chat boards, characters/environments, thumbnails, render preview) plus a live talking-clip generation and cast-lock to prove the backend-internal mint sites work outside the test harness.
- **Also done:** C25b · S5-5/6/7 security hardening batch — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C25b. Three independent MED findings, none touching any C25a file (media.py, characters.py/environments.py vision-fetch, pipeline_executor's talking-clip path, frontend utils/ChatCore/ScenesWorkspaceTab were all avoided on purpose — zero conflict with the held C25a branch). **S5-5:** added the 4 missing dynamic-column files (`routes/characters.py`, `routes/environments.py`, `routes/queue.py`, `routes/chat.py`) to `test_sql_column_injection_lock.py`'s `AUDIT_FILES`. Doing so surfaced two false-positive shapes in the audit's own pattern-matcher, not real bugs: `len(params)`/`len(params)-1` sizing `$N` placeholders (extended the safe-by-index regex to `len(\w+)(± N)?` — same safety class as the already-allowed bare `idx`) and `chat.py`'s `key_col`/`col` (both trace to a hardcoded ternary / closed dict, added to `_VERIFIED_SAFE` with why-safe comments). Canary-proofed: injecting a real `f"UPDATE ... SET {bad_col} = $1"` (unrouted, from `body.status`) into `routes/queue.py` makes the audit fail immediately; reverted, passes again. **Bonus:** the `len()` regex fix also resolved a genuine PRE-EXISTING failure in this same test (root cause: `routes/youtube_sync.py`'s identical `len(values)` shape, present before this chunk touched anything — confirmed via `git stash -u` full-tree baseline) — so this chunk nets 16→15 pre-existing failures, not just "zero new." **S5-6:** `routes/visual_styles.py`'s `activate_visual_style`/`delete_visual_style` did an ownership `SELECT ... WHERE id=$1 AND project_id=$2` then mutated with bare `WHERE id=$1` — no tenant clause repeated in the actual mutating query. `visual_styles` has `project_id` (not `tenant_id` — schema.sql confirmed, tenant scoping goes through `projects.tenant_id`), so all 3 mutating queries (~L416 activate, ~L448 reactivate-first-default, ~L453 delete) now carry `AND project_id = $2`. New `tests/test_visual_styles_tenant_scoping.py` (5 tests) — non-vacuous via `git stash` (3/5 fail pre-fix); one test directly calls the exact UPDATE text with a forged project_id against a fake table to prove the WHERE clause itself blocks the mutation, independent of the route's own 404 pre-check. **S5-7:** `main.py`'s `/api/health/detailed` used `if token and (...)`, so an unset `HEALTH_TOKEN` short-circuited the whole auth check and served unauthenticated (error rate, task-queue depth, memory/uptime). Now explicitly fails closed: `if not token: raise HTTPException(503, ...)` before the bearer check. `/api/health` (plain, needed public for uptime monitors + carries the C16d/S7-7 queue-status field) is untouched. Updated `test_c16d_health_queue_status.py`'s no-token test (previously asserted the OLD fail-open behavior — now uses a real token) and added 3 new tests (fail-closed 503, wrong-token 401, `/api/health` still public). Non-vacuous via `git stash` on `main.py` alone. Commit (see git log). **VERIFIED:** `py_compile` clean on all 3 touched `.py` files. Full backend suite **1122P/15F/1E** — true clean-checkout baseline on THIS branch (confirmed via `git stash -u`) was **1113P/16F/1E**, not the checklist's stated "1131P/16F/1E" (that number is C25a's own post-fix count; C25a is parked on the separate `claude/c25a-media-auth-hold` branch and isn't present here, so 1113 is the correct diff base). Net: +9 passing (5 visual_styles + 3 health + 1 previously-failing SQLi-lock test now fixed), zero new failures, one pre-existing failure resolved. Frontend: untouched, confirmed via `git status` — no `tsc`/`build` run needed. Checklist §C25b ticked. **Deploy-safety / ff-merged to main (orchestrator verdict — canary proof shows the widened lock genuinely audits; net suite improvement 16F→15F):** clean — backend-only, additive-shaped (new WHERE clauses, a new 503 branch, test-only changes), zero overlap with C25a's held files, no frontend skew risk either direction. Recommend ff-merge to main on the routine hourly deploy, no coordination needed.
- **Also done:** C26 · P2.4a MCP endpoint + `agent_tokens` migration + auth, SHIPPED DARK — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C26. Deliberately scoped to endpoint + tokens + auth + one read-only proof tool (C27 does the full tool set + money gate). `agent_tokens` table (migration 099, applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`) — `token_hash` is a plain sha256 (not a slow KDF — hashes a 256-bit random secret, not a human password). `auth_agent.py::get_agent_tenant_id` is the DISTINCT S5-4 dependency: parses `Bearer se_agent_<secret>`, checks `revoked_at IS NULL` on every call (S5-3, no caching), 401 otherwise; `auth.py` is completely untouched (grep-proof test: no `se_agent_`/`agent_tokens`/`auth_agent` string anywhere in it, exactly one `verify_token`/`get_tenant_id` def each). `routes/mcp.py` is a single `POST /api/mcp` JSON-RPC 2.0 route (`initialize`/`tools/list`/`tools/call`, no SSE — justified in the module docstring since the UX map §7 spec only names "streamable-HTTP" parenthetically and this server has no server-initiated pushes yet; open question deferred to C29's live-client test) exposing exactly 2 read-only tenant-scoped tools (`list_videos`, `get_video` via `actions.video_summary()` unchanged) — no paid verbs, no `remember`/`forget` (S5-2), no media URLs (C25a not deployed — tested explicitly). Router registered in `main.py` ONLY inside `if os.getenv("MCP_ENABLED","").lower()=="true":` — proven dark via an actual `main.py` reload under each env state, not a source-read: `/api/mcp` absent when unset/false, present when true. `routes/agent_access.py` (mint/list/revoke) uses the NORMAL session auth (`Depends(get_tenant_id)`), registered unconditionally — C28 wires its UI. **VERIFIED:** 27 new tests (`tests/functional/test_c26_mcp_agent_tokens.py`) — hash-not-plaintext, authenticate round-trip, revoked-token-rejected-immediately, revoke idempotent+tenant-scoped, fail-soft `last_used_at`, cross-acceptance BOTH directions (agent token 401s on `auth.verify_token`; session JWT 401s on `get_agent_tenant_id`), tool-surface pinned to exactly `{list_videos, get_video}`, both tools tenant-scoped via fake two-tenant data, dark/enabled router reload. Non-vacuous via `git stash -u` on all 7 new/changed files (test collection errors with them gone, all 27 pass restored). `python -m py_compile` clean. Full backend suite **1149P/15F/1E** = baseline (1122P/15F/1E) + exactly the 27 new tests, same 15 pre-existing failure names, zero new failures. Frontend untouched (confirmed via `git status`). Checklist §C26 ticked (also caught + ticked C25b's checklist box, which was done+merged but left unticked by that chunk). **Deploy-safety: ff-merged to main (orchestrator verdict — all S5 design laws pinned by two-way rejection tests; dark-ship proven by app reload under each flag state), dark-shipped** — `/api/mcp` genuinely does not exist post-merge (MCP_ENABLED unset in prod), `/api/agent-tokens` is a normal authed route with no UI caller yet; zero overlap with C25a's held files; safe on the routine hourly deploy. The MCP surface stays inert until a deliberate, separately-coordinated `MCP_ENABLED=true` flip after C25a merges.
- **Also done:** C27 · P2.4b full tool set + quote/confirm_token money gate, SHIPPED DARK — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C27. Expanded C26's 2 read-only tools to the FULL `actions.ACTIONS` verb registry: 7 reads (`list_videos`/`get_video` + new `get_scenes`/`get_script`/`get_ledger`/`list_style_presets`/`list_models`, none carrying a media URL — `preview_url`/`thumbnail_url` explicitly stripped where a reused route would otherwise leak one), 12 free writes (execute immediately — `approve_cast`, `camera_preset`, `lock`, `drive_push`, etc. + `create_video`), 15 paid verbs (`script` through `build`, including `upload` — carries BOTH C16e's skip-if-already-uploaded AND the new money gate). Every verb dispatches through the SAME `routes.chat._run_pending_action` chat/buttons call — no forked dispatch (proven by patching that exact function, not an MCP-local copy). New `confirm_tokens.py` (migration 100, `mcp_confirm_tokens` table, applied LIVE) is the money gate: single-use + 10-min-expiry + params-hash-bound, one atomic UPDATE — a quote for "animate scene 3" cannot spend on "animate scene 12" (bait-and-switch fails closed). Closed the C26-flagged rate-limit gap: `rate_limit.py::_extract_tenant_from_jwt` now recognizes `se_agent_` tokens via `agent_tokens.authenticate()` (hashed 30s cache), proven end-to-end through the real middleware (a seeded-to-limit tenant's agent-token request 429s). Attribution seam for C28: `_run_pending_action` gained `caller: str = "chat"` (default preserves every existing chat.py `claimed_by` string byte-for-byte), MCP passes `caller="agent:<token name>"` (resolved via new fail-soft `agent_tokens.name_for_token`) all the way into `generation_claims.claimed_by` — **C28's chip should read `generation_claims.claimed_by LIKE 'agent:%'`** (live attribution while a claim is held; free verbs have no durable marker, noted as an explicit scope boundary, not a migration). VERIFIED: 39 new tests (`test_c27_mcp_toolset_money_gate.py` ×33 + `test_c27_rate_limit_agent_tokens.py` ×6) non-vacuous via `git stash push` on the 7 tracked modified files (22 failed + 6 errored against pre-chunk code, stash popped clean). Full backend suite **1188P/15F/1E** = baseline (1149P/15F/1E) + exactly 39, zero new failures. `py_compile` clean. Frontend untouched (`git status` confirms zero `storyengine/frontend/` files) — matches the checklist's `[U]` none this chunk. **Deploy-safety: ff-merged to main (orchestrator verdict — money-gate matrix complete, atomic single-use confirm token, same-runner dispatch pinned; verified MCP create_video writes only the row with zero autobuild so 'free' is correct), still dark** — every change is either inside `routes/mcp.py` (unreachable while `MCP_ENABLED` is unset), a pure-addition rate-limit extractor branch (real JWTs take the identical prior path, proven), or a `caller` param defaulting to byte-identical pre-C27 behavior. No overlap with C25a's held files.
- **Also done:** C28 · P2.4c Settings "Agent access" UI + "via agent" attribution chip — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C28. New `/settings/agent-access` page (new "Agent Access" tab in `PROFILE_TABS`, between "API Keys" and "Billing") wired to C26's existing session-authed `routes/agent_access.py` — list (name/created/last-used/revoked-badge, revoked tokens stay struck-through for audit, never removed from view), create (plaintext `token` shown exactly once in the SAME modal with a copy button + "you won't see this again" warning — verified by trace: `setMintedToken` is component `useState` only, never `queryClient.setQueryData`'d into the cache, and clears to `null` on any close path), revoke (confirm modal, not a bare click). Deliberately mirrors `/settings/keys`' Card/Modal vocabulary, not `/settings/page.tsx`'s GlassCard style — an agent token is the same kind of secret-management task. Plus a "How to connect" block: the literal `${API_URL}/api/mcp` endpoint + an honest "requires MCP_ENABLED on your server" note. **Attribution chip:** traced the C19a shared task watcher end-to-end — `GuidedNextStep`'s running banner reads `taskWatcher.running`/`.message` off the `TaskWatcherBridge` `pipeline/[videoId]/page.tsx` builds from its one `useTaskWatcher` poll against `GET /api/pipeline/task/{video_id}`, which did NOT carry attribution before this chunk. Smallest correct addition (no migration): `generation_claims.get_claimed_by()` (new, read-only, FAIL-SOFT unlike acquire/is_blocked — no money-safety reason to fail closed on a UI-only lookup) + `routes/pipeline._agent_name_from_claimed_by()` (pure parser: `"agent:<name>:<verb...>"` → `"<name>"`, everything else incl. `"chat:..."`/`None` → `None` — the chip's fail-safe) feed an additive `via_agent` field on `get_task_status`, looked up only while `status=="running"`. Frontend: `TaskStatus.via_agent` (optional), `useTaskWatcher` tracks `viaAgent` (same lifecycle as `message`; cleared on `markStarted()`'s optimistic arm too, so a locally-started run never briefly shows a stale name from a PRIOR agent-held run), `TaskWatcherBridge.viaAgent`, chip rendered in `GuidedNextStep`'s running banner only when `!locking && viaAgent` (absent/null → no chip, by construction). **VERIFIED:** 15 new tests (`test_c28_agent_attribution.py`) — pure-parser cases, `get_claimed_by` (live claim, no-claim, stale-ignored, fail-soft-on-DB-error, tenant-scoped mirroring `test_cross_tenant_task_isolation.py`'s existing contract), endpoint cases (`via_agent` present for agent claim / absent for chat claim / absent for no claim / lookup skipped entirely when not running). Non-vacuous via `git stash push` on the 2 tracked modified files (14/15 failed pre-chunk with `KeyError`/`AttributeError`; the 15th legitimately passes both ways — it pins the pre-existing idle-branch shape). `python -m py_compile` clean. Full backend suite **1203P/15F/1E** = baseline (1188P/15F/1E) + exactly 15, zero new failures. Frontend: `npx tsc --noEmit` clean; `npm run build` clean WITH `NEXT_PUBLIC_API_URL` set (without it, `/privacy` fails to prerender on a PRE-EXISTING `env.ts` guard untouched by this diff — confirmed via `git log` on both files — matches the chunk brief's own "prerender quirk pre-existing" framing, not a new regression); `/settings/agent-access` prerendered fine alongside the other 32 routes. Checklist §C28 ticked. **Deploy-safety: ff-merged to main (orchestrator verdict — plaintext-once verified at the component level, attribution field additive + double-direction skew-safe)** — calls only routes already live on main (`agent_access.py` since C26, `get_task_status` gains an ADDITIVE field an older frontend simply ignores and a newer frontend reads via `?? null` so a hypothetical rollback is also safe); no migration; no `MCP_ENABLED` interaction (minting/revoking/viewing tokens works regardless of the flag — only actually USING a token against the dark MCP endpoint needs it); no overlap with C25a's held files.
- **Also done:** C29 · P2.4d external-client loop verify, split per its own recommendation — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C29. Sandbox half shipped: `test_c29_mcp_full_session_dry_run.py`, an 11-step simulated external-client MCP session driven through the REAL ASGI app (`main.app` via `TestClient`, `MCP_ENABLED=true`, the same reload-main technique C26 established) — real HTTP requests, real JSON-RPC envelope, real `RateLimitMiddleware`, real `auth_agent.get_agent_tenant_id`, real `agent_tokens.*`, and the REAL `confirm_tokens.create`/`redeem` money-gate logic (only its own DB call faked). Session: initialize → tools/list (paid schemas carry confirm_token, S5-2 exclusion holds) → create_video (free, thumbnail_url stripped) → get_video → `script` (paid) with no confirm_token → quote, executor NOT invoked → same call WITH the token → dispatches, `run_pending_mock.assert_awaited_once_with` pins the exact args + `caller="agent:C29 Dry-Run Session"` attribution → SAME token reused → refused, executor still called exactly once → get_ledger → revoke the token via the REAL `DELETE /api/agent-tokens/{id}` route → next MCP call with the revoked token → real 401. Plus a separate real-404 proof for `MCP_ENABLED` off. Non-vacuous via a canary (no `git stash` here — this tests EXISTING C26/C27 code, not new production code): temporarily changed `routes/mcp.py`'s `if not ok:` to `if False:`, re-ran — step 7's reuse-refusal assertion failed exactly as expected, reverted, confirmed zero diff via `git diff --stat`, re-ran — both tests pass again. Full backend suite **1205P/15F/1E** = baseline (1203P/15F/1E) + exactly 2, zero new failures. Frontend untouched. Live half (a REAL external MCP client against a REAL coordinated deploy) shipped as the runbook, not run here: new **`tasks/live-verification-queue.md` §C29** (placed near the top, right after the "WHEN YOU'RE AT THE COMPUTER" list) is the ONE consolidated recipe folding in C26's "does a real client need SSE/Streamable-HTTP" question, C27's "live money-gate spot-check", and C28's "chip appears on a live agent-driven run" — 6 ordered steps (coordinated deploy incl. C25a's held branch → flip `MCP_ENABLED=true` → mint a token → connect a real MCP client, exact `.mcp.json` config given → run the UX-map §7 example session on a disposable test video, capped ~$1–2, cheapest/draft-tier models, NO premium finalize without Ryan's explicit OK → revoke + confirm 401), each with an expected result AND a rollback note (unset the flag = instant dark). Checklist §C29 ticked (sandbox half + runbook delivered; the live half's own ticks live inside the runbook itself, run independently by whoever executes it on the VPS). **Deploy-safety: ff-merged to main (orchestrator verdict — canary-neuter proof accepted as the right non-vacuity for a test-only chunk; zero-diff revert verified by the worker)** — the only shipped diff is one new test file (zero runtime surface) + two docs edits; the canary edit to `routes/mcp.py` was reverted before commit (confirmed zero diff). `MCP_ENABLED` stays unset in prod; nothing here changes what's reachable.
- **Also done:** C30 · P3.1a preset/model performance aggregation — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C30. Investigated the linkage question first: `videos` already carries its own synced performance columns (`views`/`ctr`/`avg_retention`/`last_analytics_sync`), written by the SAME `youtube_sync.py::_writeback_matched_videos` job that fills `channel_videos` — joining `channel_videos` would silently drop freshly-uploaded videos (no row there until the next channel-wide sync walk), so the aggregation reads `videos` directly, matching the existing `get_framework_performance`/`_own_performance_brief` precedent. **No migration needed** — every column (`style_preset_id` C20, `render_style` C13b, `script_profile` C24, `model_used`/ledger C13/C07) already existed. New `analytics_by_style.py`: one `get_style_performance(tenant_id)` grouping by style_preset_id/render_style/script_profile (GROUP BY straight off `videos`, spend joined from a `generation_ledger` CTE) plus a 4th "dominant clip model" dimension (per-video mode via `ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY COUNT(*) DESC)` so a mixed-routing video's performance counts exactly once). Honest NULL handling: `synced_count` vs `video_count` kept separate, averages computed only over the synced subset via SQL `FILTER` (never coerced to 0). New `GET /api/analytics/by-style` (routes/analytics.py, no `main.py` change — router already registered) + `StyleChoiceAggregate`/`StylePerformanceResponse` in models.py. Read-tool: new `channel_briefs._style_performance_brief` (same aggregation, not re-derived) wired into BOTH `agent_brain._tool_channel_data` and `routes/chat._loop_brief` (the C15d one-director-voice symmetry) — cites only groups clearing `MIN_SAMPLE=2` synced videos. `[U]` explicitly out of scope (C31). VERIFIED: 10 new tests non-vacuous via stash (moved `analytics_by_style.py` aside + stashed tracked changes → ModuleNotFoundError, confirmed real); full suite 1215P/15F/1E = baseline(1205)+10, failing-test-name list byte-identical to baseline, zero new failures. py_compile clean on all 7 files. Live "real channel data aggregates sensibly" check deferred → live-verification-queue §C30 (needs a tenant with actual multi-preset synced analytics). Purely additive (new route/models/brief-call, nothing renamed/removed, no DDL) → ff-merged to main (orchestrator verdict — column interpolation verified against the closed _COLUMN_DIMENSIONS dict, never user input; the sync-gap linkage decision is the right call).
- **Also done:** C31 · P3.1b "by style" analytics panel + producer LOOK citations — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C31. `[U]` closer of checklist §3.1: new "Performance by Style" section on `storyengine/frontend/src/app/analytics/page.tsx` (placed right after the existing "What's Working (by framework)" block, same GlassCard/tab-strip visual language) — 4 dimension tabs labeled from schema.sql's own column comments (Look Engine=`style_preset_id`, Channel Look=`render_style`, Script Voice=`script_profile`, Clip Model=dominant ledger model), table columns Choice/Videos(synced/total)/Avg CTR/Avg Retention/Total Views/Total Spend/Cost-per-1k-Views. Unlike the framework panel above it (which hides sub-2-sample groups), this one shows EVERY row the endpoint returns — full transparency was the explicit ask — with a clear dimmed "no data yet" label (not a bare dash) on any `synced_count===0` row. Cost-per-1k-views is derived ONLY from the two totals the endpoint already serves (`total_spend`/`total_views`), guarded against div-by-zero; three fail-safe formatters (`pct1`/`pct0`/`money`) route every cell so a missing field renders `"--"`, never `NaN`. New `frontend/src/lib/api.ts` types (`StyleChoiceAggregate`/`StylePerformanceResponse`, copied field-for-field from `models.py`) + `getStylePerformance()`, React Query key `["style-performance"]`. `[B]` half: one paragraph added to `producer_prompt.py`'s existing LOOK bullet (inside `CARD GUIDANCE:`, not a new section) teaching the producer to quote `_style_performance_brief`'s real numbers when recommending a LOOK ("your holographic videos average 2.1x the channel CTR — want to stay with it?") and to say NOTHING about channel performance when the brief carries no data for that choice — never fabricate. No new ops/routes/schema; `_style_performance_brief` was already reaching the prompt via C30's `_loop_brief`, this chunk only changed what the model does with it. Two-doors note: the copilot's `channel_data` tool already covers the conversational read (C30) — nothing more needed there. VERIFIED: 5 new tests (`test_c31_style_citation.py`, C15d prompt-pin pattern) non-vacuous via stash (all 5 fail without the change), full backend suite 1220P/15F/1E = baseline(1215)+5, same 15 failing names + same 1 error, zero new failures. `python -m py_compile` clean. Frontend: `npx tsc --noEmit` clean; `npm run build` reproduces the PRE-EXISTING `NEXT_PUBLIC_API_URL` prerender failure on `/pipeline` AND `/analytics` (confirmed unrelated to this chunk — re-running with the env var set builds all 33 routes cleanly). Live "panel shows real aggregates, producer actually cites" check deferred → live-verification-queue §C31 (same sandbox-has-no-multi-preset-tenant gap as C30). Purely additive both sides (new page section reading an already-shipped GET endpoint; one appended prompt paragraph, old empty-brief behavior byte-identical) → ff-merged to main (orchestrator verdict — cite-only-real-data pinned in both directions; fail-safe dashes never NaN).
- **Also done:** C32 · P3.2 legacy stubs: scorer placeholders + learning_extractor + competitor_title_patterns — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C32. Traced each stub's reachability from something that actually runs (`infra/setup_cron.sh`'s VPS cron — none of the three are called from StoryEngine's backend) before deciding wire vs. inert vs. delete. **`ConfidenceScorer._score_channel_momentum`/`_score_retention_patterns`** (cron-reachable via `autopilot.autopilot --check-cycle` → real idea-picking decision): were flat `50.0` placeholders carrying `0.10`/`0.08` config weight — a fixed unearned +9.0 on every candidate's score before the `min_confidence_score` threshold check. Made **honest-inert**: both weights pinned to `0.0` in `autopilot_program.md` (source of truth) + `WeightsConfig` defaults, the other four weights renormalized in their original ratio (0.30:0.25:0.20:0.07 → 0.37:0.30:0.24:0.09, still sums to 1.0); `ConfidenceScorer.__init__` now logs a one-time `WARNING` if either weight is ever non-zero again (regression guard, proven to fire). Not implemented "for real" because no data pipeline backs either signal (competitor_scraper has no time series for momentum; retention is never written to `topic_performance.md` because the writer — `learning_extractor` — is itself broken, see next item) — building that is a new feature, not a stub fix. **`learning_extractor.run_daily_extraction()`** (cron-reachable via daily `autopilot-learn`): root cause is TWO gaps, not one — `ExperimentState.status` is never set to `"monitoring"` anywhere in the codebase (so its own guard has never once passed in production) AND the CTR/Airtable pull was never written either; this is why LEARNINGS.md has shown "Videos produced: 0". Made **honest-inert, left running**: docstring now states both gaps, misleading "Learning extraction is ready" print replaced with an honest `logging.warning` every run, two now-fully-unused local instantiations removed. Deliberately **NOT deprecated** in favor of StoryEngine's `routes/learning_extraction.py` (a complete, working equivalent) — because that route reads Supabase's per-tenant `videos` table and the legacy Economy FastForward channel has no tenant row there; deprecating would remove the channel's only learning loop, even a no-op one. **`osiris/learnings_engine.get_competitor_title_patterns()`**: zero callers anywhere in the repo (confirmed by grep) — **deleted**, no callers to update. **Bonus (caught by this chunk's own `[V]` grep)**: `PatternLibrary.get_best_structures_for_topic()` — same shape (TODO stub, zero callers) — also **deleted**. VERIFIED: `grep -rn "TODO" skills/video-pipeline/autopilot skills/video-pipeline/analytics` → empty. `python -m py_compile` clean on all 5 touched files. `autopilot/tests/` → 144 passed, 2 failed (identical to pre-existing baseline — both failures are an unrelated pre-existing f-string bug in `autopilot.py:306`, not one of this chunk's items). Non-vacuous proof: real config parses to zeroed weights summing to 1.0; constructing the scorer with the OLD non-zero weights correctly fires the regression-guard warning. Backend full suite 1220P/15F/1E — byte-identical to documented baseline (chunk touches zero `storyengine/` files). Frontend untouched. Commit — see `git log`. Deploy-safety: cron-reachable code changes ship on the next hourly `git pull --ff-only`; no cron config changed (no VPS re-run needed) → **ff-merged to main (orchestrator verdict — no more fake signals in a real cron decision; renormalized weights still sum to 1.0; regression tripwires in place)**.
- **Also done:** C32a · fix pre-existing invalid f-string at `skills/video-pipeline/autopilot/autopilot.py:306`/`:310` (flagged out-of-scope by C32) — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C32a. `f"{best_score:.0f if best_score else 'N/A'}"` is not valid format-spec syntax (a conditional expression can't live inside `:...}`) — raised `ValueError` on the "no candidates meet threshold" path. Fixed with a `best_score_str = f"{best_score:.0f}" if best_score is not None else "N/A"` computed once, used in both the `print` and the Slack `_notify` string (`is not None` rather than truthiness, so a real `0` score would still render `"0"`, not `"N/A"` — closer to the evident original intent). **Honest result: the crash is gone, but the suite did NOT go green as the chunk brief expected (146P/0F)** — it's still 144 passed/2 failed, now on `assert result is True` instead of a `ValueError`. Root-caused (not hand-waved): `test_integration.py`'s mock Airtable fixtures hardcode absolute `Published Date` timestamps (`2026-03-17`/`2026-03-16`) meant to read as "~24h/~48h old" when written; `check_cycle` computes `hours_old` itself from that date vs. `datetime.now(timezone.utc)` (ignores the fixture's own unused `'Hours Old': 24` field) — against this session's clock those dates are ~124 days old, past `ConfidenceScorer.MAX_HOURS` (168h), so `timing_freshness` scores 0 and the composite falls under `min_confidence_score: 60`, so `scorer.get_best()` correctly returns `None`. Proved by direct computation: the same candidates scored with their fixture-intended `hours_old` (24/48) come out 62.7-69.9 (comfortably over threshold) vs. ~49 with the actual rotted dates — a time-bomb test fixture (absolute date rots as wall-clock time passes), not a production bug, and unrelated to the f-string or to C32's weight renormalization. Left unfixed per this chunk's explicit "zero other changes" scope and the "don't force-fix tests to pass" instruction — flagged as a new follow-up (fixture should compute `Published Date` relative to `datetime.now()` at test-run time). VERIFIED: `python -m py_compile` clean; `autopilot/tests/` → 144P/2F (same count as baseline, crash replaced by a different, now-documented assertion failure, zero new/net-different failures). Backend untouched — `git diff --stat` confirms only the one autopilot.py file changed. Checklist §C32a ticked with the caveat spelled out (not silently claimed as the expected 146P/0F). **Deploy-safety: ff-merged to main (orchestrator verdict — global quota scope proven by credential trace; VPH reuses the competitor formula, no fork)** — single-file, cosmetic print/Slack-string change on the below-threshold notification path only, no scoring/decision logic touched; ships on the routine hourly `git pull --ff-only`, no VPS coordination needed.
- **Also done:** C32b · Time-bomb fixture fix (found by C32a) — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C32b. `test_integration.py`'s `mock_airtable` fixture hardcoded absolute `Published Date` strings (`2026-03-17`/`2026-03-16`) meant to read as ~24h/~48h old at write time; `check_cycle` computes `hours_old` from that date vs. `datetime.now(timezone.utc)` (ignores the fixture's own unused `'Hours Old'` field), so the dates rotted past `ConfidenceScorer.MAX_HOURS` (168h) as wall-clock time advanced. Fixed by computing both `Published Date` values at test-run time — `(datetime.now(timezone.utc) - timedelta(hours=24/48)).isoformat()` — so the fixture always represents the ages it was written to represent, no matter when the suite runs. Test-only, zero production code touched. Swept neighboring autopilot test files for the same rot pattern: 5 more hardcoded dates found (`test_state_manager.py`, `test_pattern_library_curiosity_gap.py`, `test_memory_writer_structure.py`, `test_memory_writer.py`, `test_pattern_library.py`, `test_notifier.py`) but none are time-bombs — confirmed by grepping each for `datetime.now|MAX_HOURS|freshness|days_until|age` (no hits); they're opaque strings round-tripped through save/load equality or static markdown/assertion content, never diffed against "now". VERIFIED: `python -m py_compile` clean; `autopilot/tests/` → **146 passed / 0 failed** (both previously-failing tests now pass, net +2 vs. C32a's 144P/2F baseline, zero new failures). Backend untouched — only the one test file changed. Checklist §C32b ticked. **Deploy-safety: ff-merged to main (orchestrator verdict — deletion grep-proofed, connected tenants byte-identical, and the worker independently verified the mid-chunk operator update against decisions.md before acting: exemplary injection hygiene)** — test-only change, no production behavior affected; ships on the routine hourly `git pull --ff-only`, no VPS coordination needed.
- **Also done:** C33 · P3.4 quota guard + own-video VPH — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C33. **Quota guard:** investigated scope first — grepped every `GOOGLE_OAUTH_CLIENT_ID/SECRET` read across the backend, confirmed ALL tenants share ONE OAuth app (no per-tenant client id anywhere), so the 10,000-units/day quota is billed to a single Google Cloud project — counter is GLOBAL, no `tenant_id` (a per-tenant counter would under-count the real cross-tenant risk). New `youtube_quota.py` + migration 101 `youtube_quota_usage` (day PK, applied LIVE via Supabase MCP to `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`/`relrowsecurity`; RLS no-policies, same proven pattern as `secrets`). Unit costs from Google's published quota-cost table (`videos.insert`=1600, `thumbnails.set`=50, list calls=1 each); `DEFAULT_CEILING=9000` (headroom under the real 10k, more conservative than the checklist's illustrative "10k/6 uploads" framing). Wired into `youtube_publish.py::upload_video_to_youtube` (the ONLY `videos().insert` call site, confirmed via grep) — checked before download (fail fast), recorded after success; fail-soft throughout (tracker error → log + allow). `routes/youtube_sync.py` records its own (small, ungated) list-call cost for an honest running total. Both `/api/health` endpoints surface `youtube_quota: {units_used, ceiling, remaining}`. `[U]` Upload-tab chip NOT built this chunk — honestly flagged as a small follow-up. **Own-video VPH:** new `own_vph.py::compute_own_vph()` reuses `routes.niche._calculate_vph` (the SAME math the competitor side already uses — checked for an existing legacy own-VPH calc first, found none to reuse) rather than reimplementing; returns `None` (not `0.0`) for unpublished or under-1-hour-old (near-zero-denominator extrapolation guard). Derived at read time, no stored column. Wired into `channel_briefs._own_performance_brief`, `routes/analytics.py::get_channel_videos`, and C30's `analytics_by_style.py` aggregation (new `avg_vph` in both SQL aggregation queries + `models.py`'s `StyleChoiceAggregate` + a new "Avg VPH" column in `analytics/page.tsx`'s by-style table). **Verify:** non-vacuous via file-hide (`ModuleNotFoundError` on all 3 new test files without the 2 new modules) + `git stash -u`; 21 new tests (12 quota + 6 VPH + 3 wiring), full backend suite **1241 passed / 15 failed / 1 error** (baseline 1220/15/1 + 21 new, zero new failures — fixed one drift-checker failure along the way by adding `youtube_quota_usage` to `schema.sql`); autopilot suite untouched, confirmed **146/0** unchanged. `npx tsc --noEmit` clean. Deploy-safe, ff-merged to main (orchestrator verdict — the worker found and closed the REAL leak vector (env-restore + import-time class attrs), not just the literal; Slack default-off matches the recorded retirement decision) — purely additive.
- **Also done:** C34a · S10-1 CRITICAL fix: remove/hard-block the legacy upload fallback — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C34a. `pipeline_executor.run_upload`'s no-connected-channel branch no longer falls through to `self._pipeline.run_upload_bot()` (the legacy `skills/video-pipeline/upload/` bot) — it returns `{"status":"failed","error":"Connect your YouTube channel first — Settings → YouTube."}` immediately; native connected-tenant path is byte-identical. Traced every caller (manual route, chat/MCP "upload" verb, claude_orchestrator's skill dispatch, arq worker, and the autobuild "finish" chain — which, traced in full, never actually reaches upload: `DONE_STATUSES` includes `"rendered"` itself, so the finish loop stops there before ever calling `run_next_step`'s upload mapping) — all get the same dict-return handling already in place, no special-casing needed. Belt-and-suspenders route gate added to `routes/pipeline.py POST /upload/{video_id}` (400 before the task lock is claimed). **Mid-chunk operator update changed the wire-or-delete calculus:** Ryan confirmed he no longer runs Power Doctrine or its Slack channel (the prototype), so instead of "leave the legacy bot for the cron pipeline," DELETED `skills/video-pipeline/upload/run.py`, `seo_generator.py`, `youtube_uploader.py`, `manifest.json` outright (grep-proofed nothing else imports them); kept `run_package.py` (unrelated Remotion-packaging helper, still used by `render/run.py`/`package_for_remotion`). Surgically removed the stage-10 upload hookup in the legacy `orchestrator/pipeline.py`'s `run_next_step` (a Rendered idea now falls through to "No work to do" instead of crashing on the deleted import) but kept `run_youtube_upload_bot` as a soft-fail stub since `pipeline_control.py`'s Slack `upload` command still calls it directly — deleting it outright would've turned that into an `AttributeError` crash. Also deleted the now-dead `run_upload_bot` closure/shim from `pipeline_executor.py::_ensure_initialized` (nothing called it anymore). VERIFIED: 8 new tests, non-vacuous via `git stash` (4/8 correctly fail against pre-fix code); full backend suite **1249 passed / 15 failed / 1 error** (baseline 1241/15/1 + 8 new, zero new failures); autopilot **146/0** unchanged; `python -m py_compile` clean on every touched file; frontend untouched (confirmed via `git status`). **Deploy-safety: ff-merged to main (orchestrator verdict — bonus find accepted: the unconditional Economy-FastForward USER prompt was a live leak to all 3 real tenants, now fixed + pinned; legacy Template A path proven preserved)** — connected-tenant behavior byte-identical, unconnected tenants get a clear failure instead of silently shipping onto Ryan's own channel; legacy cron pipeline still imports/runs fine.
- **Also done:** C34b · S10-2/S10-3 fix: voice + Slack de-globalization — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C34b. **Voice (S10-2):** the real bug wasn't just `Models.VOICE_ID`'s hardcoded literal (Ryan's own ElevenLabs clone `G17SuINrv2H9FC6nvetn`) — it was `pipeline_executor._ensure_initialized`'s `VOICE_CONFIG_KEYS` "restore process-level default" step (added by the DvsU 2026-07-07 fix, meaning well) snapshotting `os.environ["ELEVENLABS_VOICE_ID"]` BEFORE clearing and restoring it for any tenant with no vault override — on the shared SaaS backend process that snapshot is whichever identity's `.env` happens to be loaded (Ryan's own clone), so any tenant who skipped the voice step silently narrated in his actual voice. Traced `vault.get_secret`: with a `tenant_id` it never falls back to env vars, confirming the leak was executor-level, not vault. Fix: `elevenlabs_voice_id` removed from `VOICE_CONFIG_KEYS` (model_id/style — non-identity engine tuning — still restore); `ElevenLabsClient(...)` construction now passes `voice_id` EXPLICITLY (`os.environ.get("ELEVENLABS_VOICE_ID") or STOCK_NARRATOR_VOICE_ID`, resolved fresh per tenant) rather than relying on `ElevenLabsClient.DEFAULT_VOICE_ID`/`Models.VOICE_ID` (frozen at first import in this shared process — a second, subtler leak vector, closed by never touching it here); new `STOCK_NARRATOR_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"` (ElevenLabs' own premade "Rachel," already the onboarding placeholder example in `ApiKeysStep.tsx`); `Models.VOICE_ID`'s literal fallback changed to match. Onboarding already has a reachable `elevenlabs_voice_id` field (Settings → API Keys) — no UI built this chunk, a friendlier voice-picker flagged as follow-up. Ryan's own legacy cron pipeline reads `ELEVENLABS_VOICE_ID` from its OWN separate `.env` — untouched. **Slack (S10-3):** `SlackClient` now requires BOTH a bot token AND new env `SLACK_NOTIFICATIONS_ENABLED=true` (default off) to send anything — a token alone is no longer sufficient, closing the class of bug (any future legacy stage reachable from SaaS is silent by default) not just the two flagged call sites. Every instantiation site audited (SaaS backend + 10 legacy-cron/bot sites) — all now silent unless the legacy pipeline's own `.env` opts back in; matches Ryan's stated intent that the prototype channel is retired. VERIFIED: 12 new tests (`test_c34b_voice_and_slack_tenant_isolation.py`), non-vacuous via `git stash` (6/12 correctly fail against pre-fix code); full backend suite **1261 passed / 15 failed / 1 error** (baseline 1249/15/1 + 12 new, zero new failures); autopilot **146/0** unchanged; legacy `skills/video-pipeline/tests/` pre-existing environment failures confirmed unrelated (missing `_cffi_backend`/PIL, not Slack/voice); `python -m py_compile` clean; frontend untouched. **Deploy-safety: ff-merged to main (orchestrator verdict — strict-subset matcher proof accepted)** — Ryan's own voice/Slack behavior unaffected (separate process/env); SaaS tenants get strictly safer defaults, no paid path or migration changed.
- **Also done:** C34c · S10-4/S10-5/S10-6 fix: thumbnail/title/category genericization — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C34c. **Thumbnail (S10-4):** `thumbnail/selector.py::select_template` fell back to Template A (Map + Barrier — a geopolitical satellite-map visual) unconditionally whenever a video matched none of the person/split/symbolic keyword lists, reachable for any new tenant with no thumbnail history via `pipeline_executor.py`'s from-scratch-bot fallback. Fixed with two signals ahead of a new neutral default: `GEO_KEYWORDS` (the video's OWN content is geopolitical/macro — map, chokepoint, trade route, GDP, reserve currency) still earns `template_a`, and `GEO_NICHE_KEYWORDS` (the tenant's own niche is finance/geopolitics) is a fallback consulted only when nothing else matched — niche reaches the selector via an explicit `"niche"` key on `video_metadata` or the new `CHANNEL_NICHE` env var (`pipeline_executor.py`'s `_load_prompt_overrides` exports it from `IdentityContext.niche`, same cross-package seam pattern as `VISUAL_STYLE_DESCRIPTION`). Everything else falls to a NEW **Template E (Subject Focus)** — no map/country assumption baked in — added to `templates.py` + `prompt_builder.py`. **Title (S10-5):** `TITLE_GENERATION_SYSTEM_PROMPT` hardcoded "Economy FastForward, a finance/economics YouTube channel" plus a mandatory geopolitics-flavored caps-word vocabulary; traced why it looked unreachable (`_load_prompt_overrides` always resolves a non-blank `thumbnail`-template override for every StoryEngine tenant, fed to `TitleGenerator` too — flagging as a NOT-fixed-this-chunk pre-existing mismatch: title generation borrows the *thumbnail* craft template, not the niche-neutral `title` template that already exists in `engine_templates.py` but sits unwired per its own "Phase 3 wires it" comment) — meaning the hardcoded prompt was live only for the legacy Airtable-only pipeline (no override mechanism at all) and any future call site that forgets to wire one. Rewrote the prompt niche-neutral (generic `[Subject]` shapes, register-matching caps-word rule, examples spanning cooking/language-learning/investigation) in the same style as `engine_templates.py`; JSON-schema mechanic untouched; `TITLE_FORMULAS` (opt-in, zero live callers) left as Ryan's preserved legacy examples. Bonus fix in the same file: the USER prompt also hardcoded `f'Generate a title for this Economy FastForward video:'` UNCONDITIONALLY (fired regardless of override) — every StoryEngine tenant's title call was leaking this into its user turn; fixed to plain text. **Category (S10-6):** `generate_and_store_seo` already computed a real `category_id` from the video's own content but threw it away — the UPDATE only persisted description/tags/hashtags; `upload_video_to_youtube` always shipped the hardcoded `_DEFAULT_CATEGORY` ("27" — Education) regardless. New `videos.seo_category_id TEXT` column (migration 102, applied LIVE via Supabase MCP to `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`) — reuses the same UPDATE/storage pattern as the other SEO fields; `generate_and_store_seo` now persists it, `upload_video_to_youtube` reads and passes it through, falling back to "27" only when NULL/blank. VERIFIED: 24 new tests (19 `skills/video-pipeline/thumbnail/tests/` + 5 `storyengine/backend/tests/functional/test_c34c_seo_category.py`), non-vacuous via `git stash` (7/19 + 3/5 correctly fail against pre-fix code); full backend suite **1266 passed / 15 failed / 1 error** (baseline 1261/15/1 + this chunk's 5 backend tests — the 19 thumbnail tests run in the separate `skills/video-pipeline` pytest invocation, not counted in the backend suite — zero new failures in either run); `python -m py_compile` clean; frontend untouched (no `category_id`/`seo_category_id` referenced anywhere in `frontend/src/`, confirmed by grep). **Ryan's legacy Template A path proven preserved**: a realistic Economy FastForward-style headline with zero niche info still selects `template_a` via `GEO_KEYWORDS` (`test_ryans_legacy_content_still_lands_on_template_a`), and the `CHANNEL_NICHE` env-var path also confirmed. **Deploy-safety: ff-merged to main (orchestrator verdict — the 4 stale-404-model-id fixes alone justify the chunk; silent-success→loud-failure is the right direction)** — migration is purely additive (nullable, no backfill, existing rows fall back to the exact old "27" behavior); no paid path changed.
- **Also done:** C34d · two micro follow-ups flagged (not fixed) by C34c — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C34d. **(1) Title template wiring:** `pipeline_executor.py`'s `_load_prompt_overrides` PROMPT_MAP gains `"title": (None, "title_system_prompt")` (was omitted with a "Phase 3 wires it" comment). `ThumbnailTitleEngine.__init__` (`thumbnail/engine.py`) gained an independent `title_system_prompt_override` param, passed to `TitleGenerator` only — decoupled from `system_prompt_override` (still passed to `ThumbnailPromptBuilder` unchanged). `thumbnail/run.py`'s call site now passes `title_system_prompt_override=getattr(pipeline, "title_system_prompt", None)`. Net: title generation resolves the neutral `engine_templates.py` `title` craft by default instead of silently borrowing whatever thumbnail override was set. **(2) Word-boundary keyword matching:** all five keyword lists in `thumbnail/selector.py` (`PERSON_KEYWORDS`/`SPLIT_KEYWORDS`/`SYMBOLIC_KEYWORDS`/`GEO_KEYWORDS`/`GEO_NICHE_KEYWORDS`) switched from plain `kw in searchable` substring checks to a start-anchored `\b` regex (`_compile_keyword_pattern`/`_any_keyword_match`) — blocks "king" matching inside "talking"/"breaking" while preserving intentional word-stems (`financ`→finance, `strangl`→strangled, `weaponiz`→weaponized, `geopolit`→geopolitical), plurals (`agent`→agents), and multi-word phrases (`prime minister`) exactly as before (anchoring only the START, not both ends, is what makes this a strict subset of the old matches — never a new false positive, only fewer). VERIFIED: 9 new tests (6 `thumbnail/tests/test_selector.py` + 3 NEW `thumbnail/tests/test_engine.py` + 3 NEW `storyengine/backend/tests/functional/test_c34d_title_prompt_wiring.py`), non-vacuous via two separate `git stash`es (1/6 selector test + all 3 backend tests correctly fail pre-fix); full backend suite **1269 passed / 15 failed / 1 error** (baseline 1266/15/1 + 3 new, zero new failures); thumbnail tests **28/28** (19 baseline + 6 + 3 new); `python -m py_compile` clean; frontend untouched. **Deploy-safety: ff-merged to main (orchestrator verdict — cap gate matrix complete incl. the byte-identical-when-NULL pins; the VideoDetail response-model wiring bug catch is exactly the checklist's field-passthrough lesson applied)** — no schema change, no new paid call site, selector fix is a behavior-only subset of the old matches, title fix can only add a missing default (never override an existing per-video/tenant setting since none exists yet for `title`).
- **Also done:** C35 · P3.4 Whisper-key friction + Claude tier map single-sourcing — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C35. **Whisper:** traced today's live keyless-tenant behavior first — the only real Whisper call site left anywhere is `skills/video-pipeline/render/audio_sync/transcriber.py` (legacy Airtable-cron pipeline); StoryEngine SaaS's three real render paths (`render_perform.py`/`render_static.py`/`render_stitch.py`) never call Whisper at all, so `routes/pipeline.py`'s existing C04 soft-hint ("pipeline still runs without it") is already accurate there, left unchanged. The real bug was `run_audio_sync.py`'s per-scene `except: continue` swallowing every transcription failure (incl. missing key) and still returning a no-`"error"`-key "success" dict with 0 durations — every caller (Slack `sync`, direct `pipeline.run_audio_sync()`) reported success, matching failure-modes.md's documented "3s uniform durations" symptom. Fixed with the smallest honest improvement (no Kie equivalent exists, so `[B]` routing wasn't feasible): new `transcriber.is_configured()`; `run_audio_sync.run()` now fails fast with a clear error + Slack notify when the key's missing/placeholder (before wasting Drive downloads), and never writes `render_config.json`/claims success when `duration_updates == 0` after the loop. **Tier map:** traced ~15 independent hardcoded-literal call sites across the backend (routes/chat.py ×3, routes/videos.py ×2, model_video.py, pipeline.py, script_templates.py, discovery.py, system_prompts.py, youtube_channel.py, producer_prompt.py, static_docu.py, identity_builder.py, user_script.py, originality.py, youtube_publish.py, claude_orchestrator.py, distillation/distiller.py, distillation/meta_analyzer.py, render_static.py, coverage_to_app.py ×5, kie_unified.py's own `AnthropicDirectClient.generate` default) — 4 of them (`claude_orchestrator.DECISION_MODEL`, `system_prompts.py`, `youtube_channel.py`, `kie_unified`'s default param) had drifted to a stale `"claude-sonnet-4-20250514"` id that **404s on the live Anthropic API today** (confirmed by a pre-existing `producer_prompt.py` comment) — a real live bug, fixed alongside the consolidation. Single source: `shared/channel_profile.py::CLAUDE_MODELS` (next to `MODEL_REGISTRY`, C09 pattern) + `claude_model_for_direct_client()` (replaces the repeated `"claude-sonnet-4-6" if type(client).__name__=="AnthropicDirectClient" else None` idiom); `actions.py` re-exports both, same pattern as `CLIP_COST`. `kie_unified.CLAUDE_MODEL_ALIASES` (a translation shim for old ids) and `canaries/validator_drift.py`/`vision_drift.py` (drift probes that must pin on purpose) deliberately NOT folded in, documented why. Regression pin: `test_c35_claude_tier_single_source.py` — map shape/values, `actions.py` re-export, and a static AST audit of every backend `.py` file for the canonical literals (allowlisting only `kie_unified.py`/`canaries/*`). VERIFIED: Whisper fix non-vacuous via stash (7/9 new tests fail pre-fix; full `render/audio_sync/tests/` 61/61); tier-map fix non-vacuous via stash (all 3 pin-test assertions fail pre-fix, listing ~30 duplicate sites); one pre-existing test updated (not just added) — `test_learn_voice.py` pinned the stale 404ing id, now asserts the bug-fixed canonical value. Full backend suite **1272 passed / 15 failed / 1 error** (baseline 1269/15/1 + 3 new, zero new failures); autopilot **146/0** unchanged; `py_compile` clean on all ~27 touched files; frontend untouched. **Deploy-safety: ff-merged to main (orchestrator verdict — the blind-overwrite data-loss fix alone justifies the chunk; race-window tradeoff honestly logged for C41)** — Whisper fix can only turn a silent "success" into a clear failure (no working path now fails); tier-map fix is value-identical for ~17 sites and a confirmed-broken-id fix for 4, no schema change, no new paid integration.
- **Also done:** C36 · P3.3 UX debt batch: checkpoint-audio expectation, cold-start card, budget ceiling, confidence telemetry — DONE 2026-07-19, full detail in SYSTEM_STATE.md §C36. **Checkpoint-audio:** `actions.PICTURES_READY_MSG` now says "(no voice yet, that's next)"; `ScenesWorkspaceTab.tsx`'s hard "Voice Required" gate (`!hasVoice && !voiceSkipped`) previously blocked reviewing pictures the chat autobuild had JUST finished making (build-to-pictures deliberately defers voice) — now only blocks when pictures don't exist yet (`hasPictures` bypass), with an inline advisory banner replacing the block when pictures exist without voice. **Cold-start:** the fresh-conversation greeting now checks `_recent_competitor_rows()` directly (not just "ideas is None", which conflates zero-competitors with a missing Anthropic key — the latter is P0.4's territory and a competitors card would mislead there) and attaches a new one-tap `_add_competitors_card()`; a new standalone `_handle_cold_start_competitor_followup()` drives the add/skip/paste-URLs follow-up turns, reusing the onboarding step's `analyze_competitors`/`_parse_urls` calls WITHOUT routing through the onboarding step machine (this fires for an already-onboarded creator who simply never added competitors — re-triggering connect_yt/connect_drive/upsell would be a regression). **Budget ceiling (the substantial item):** `videos.max_spend` — nullable per-video spend cap (migration 103, applied LIVE via Supabase MCP to `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`). One column, three doors: the existing generic `PATCH /api/videos/{id}` (validated), a new `BudgetCapCard` UI field (`ScriptVoiceTab.tsx`, next to `ScriptVoiceCard`), and a new free `budget_cap` chat verb ("cap this video at $15"/"remove the cap", wired into both classifiers' prompts — the legacy one-shot AND `agent_brain.py`'s tool-loop brain — and auto-picked-up by `routes/mcp.py`'s dynamic tool list). The gate itself: `actions.budget_check(summary, quote_cost)` — pure function, reads the REAL `generation_ledger`-rolled-up `total_cost` (newly added to `video_summary()`'s SELECT, deliberately separate from the existing artifact-count `"spent"` key to avoid regressing legacy videos' spend display) against the cap; returns `None` (no cap, or under cap) or a breach dict. NEVER silent-blocks: `routes/chat.py`'s confirm card folds the warning in (relabels "yes" to "Do it anyway · $X", tapping it IS the override); `routes/mcp.py`'s quote carries the same `budget_warning` key (confirm_token still minted); `actions.make_autobuild_step()`'s loop (+ its pre-loop "finish" voice pass) pauses cleanly with a clear message when already at/over cap, mirroring the existing no-progress/18-iteration-cap stop pattern — no per-iteration quote exists at this granularity, so "already at/over cap" is the honest check available, distinct from the confirm-card path's precise quote+total math. **Confidence telemetry:** new `routes.chat._log_classification_confidence()` writes one `bot_activity` row per classified turn (`bot_name='copilot_classifier'`, a compact key=value message: kind/verb/confidence/source/gated) plus a log line — reuses the existing table (no new one), called in `_handle_copilot()` BEFORE the confidence-gate branches, so clarify-loop misfires are recorded too, not just passing turns. Deliberately no dashboard this chunk (tuning the 0.55 threshold itself is a follow-up once real traffic accumulates). VERIFIED: 28 new tests across 3 files (`test_c36_budget_cap.py` 16 — including a wiring-lock test that caught a real bug live: `GET /api/videos/{id}`'s strict `response_model=VideoDetail` and its own explicit SELECT column list both silently dropped `max_spend`, fixed in `models.py`/`routes/videos.py` in this same chunk — `test_c36_confidence_telemetry.py` 4, `test_c36_cold_start_and_checkpoint_audio.py` 8); non-vacuous via `git stash` of the 5 modified backend `.py` files (24/27 assertions correctly fail pre-fix — the 3 incidental passes are the byte-identical "no cap"/"under cap" paths, correctly unaffected); full backend suite **1300 passed / 15 failed / 1 error** (baseline 1272/15/1 + 28 new, zero new failures); `py_compile` clean; `npx tsc --noEmit` clean (`ScenesWorkspaceTab.tsx`, `ScriptVoiceTab.tsx`, `lib/api.ts`). Live end-to-end proof (real cap hit mid-autobuild, actual UI wording) deferred to `tasks/live-verification-queue.md` §C36. **Deploy-safety: all four items additive/opt-in** — `max_spend` defaults NULL (no behavior change unless set), telemetry write is fail-soft, cold-start card only appears on genuinely-empty competitor data, checkpoint-audio fix only widens (never narrows) when the Scenes tab renders. ff-merged to main (orchestrator verdict — server-resolved revert index, sibling-intent design, and the flagged money-rule judgment all accepted; MCP async-tool deferral recorded for roadmap D1)
- **Also done:** C40 · P4.1a Channel DNA digest data model — DONE 2026-07-19, full detail in
  SYSTEM_STATE.md §C40. Phase 4 Pillar 1 (Channel DNA ingestion) build-queue's first chunk — C38/C39
  (create-surface convergence, /storyboards delete) remain UNCHECKED in the checklist, this session
  was scoped to C40 only, jumped ahead per this session's task assignment. New
  `storyengine/backend/channel_dna_meta.py`: `stamp_identity_write(identity, fields, learner,
  confidence=None)` read-modify-write merges a `_sources`/`_history` provenance envelope INTO
  `channel_profiles.channel_identity` JSONB (no new table/migration, per checklist C40 `[D]`) —
  `field_provenance()` + `restore_field()` round it out. Migrated ALL THREE real writers found by
  grep (`identity_builder.build_channel_identity` — was a BLIND overwrite, now merges;
  `channel_format.set_channel_format` — was a SQL `||` merge, now Python-merges via the helper;
  `pipeline_executor`'s thumbnail_blueprint cache — extracted to a module-level
  `_cache_channel_thumbnail_blueprint()` so it's independently testable, same SQL-`||`→helper fix).
  Readers (`identity.py`, `channel_format.get_channel_format`, `static_docu.py`,
  `routes/chat.py::_format_identity`) already pluck specific known keys rather than iterating, so
  they structurally ignore the envelope — pinned with a byte-identity test rather than changed.
  VERIFIED: 19 new tests (`tests/test_channel_dna_meta.py`) — helper unit tests, reader byte-identity,
  and one merge test PER writer proving the OTHER two writers' fields/provenance survive; non-vacuous
  via `git stash` of the 3 modified writer files (3 of the 19 fail against pre-C40 code, the other 16
  pass unaffected — confirmed live). Full suite 1319P/15F/1E = baseline(1300P)+19, zero new failures.
  `py_compile` clean. Frontend untouched (backend-only diff). Not committed as its own commit yet at
  time of this note — see git log for the actual C40 commit. ff-merged to main (orchestrator verdict — zero live callers = zero regression surface; migration 104 verified idempotent AND applied live via MCP by the orchestrator, video_id nullable confirmed) (additive JSONB shape
  change, all writers' public return values unchanged, no migration to apply).
- **Also done:** C41 · P4.1b unified Channel-DNA ingestion orchestrator — DONE 2026-07-19, full detail
  in SYSTEM_STATE.md §C41. New `storyengine/backend/channel_dna.py::learn_channel(tenant_id, *,
  channel_url=None, example_script_text=None, reference_video_url=None, progress_cb=None)` sequences
  the FIVE existing learners behind one entry point (no new learner logic): (1) optional import via
  `routes.onboarding._import_channel_videos` (now returns a saved-count int instead of `None` — its
  only other caller already discarded the return value) when `channel_url` given (own or not-my-
  channel — idempotent upsert either way); (2) `identity_builder.build_channel_identity` unmodified,
  always runs; (3) optional `routes.script_templates.analyze_and_save_template` when an example script
  is supplied — a pre-check query distinguishes "replaced your house template" from "saved your first
  one" (the function itself DELETEs-then-INSERTs, so you can't tell after the fact); (4)
  `channel_format.set_channel_format` — ALWAYS attempted but only actually locks when
  `_format_confident()` (style+motion both detected AND >=2 videos analyzed) says so, otherwise
  surfaces the detection unlocked; (5) optional reference-video style distill, reusing
  `routes.model_video`'s extraction chain + `_distill_dna` unmodified, folded into a NEW
  `reference_video_style` field via `channel_dna_meta.stamp_identity_write(..., learner=
  "reference_video")` — closes the audit finding that Model A Video's DNA never persisted past the one
  video it modeled. **Concurrency (closes C40's flagged race-window note):** new migration 104 makes
  `generation_claims.video_id` nullable + adds a partial unique index `(tenant_id, stage) WHERE
  video_id IS NULL`; new `generation_claims.acquire_channel()`/`release_channel()` (video-less variants)
  wrap the whole `learn_channel` call, released in a `finally` — every existing per-video claim
  call site/SQL is untouched (their own tests pass unmodified). Result contract is digest-ready for
  C42: `{ok, busy, error, learners: {name: {status: learned|skipped|failed, summary, fields_written,
  error}}, identity: <current channel_identity with _sources/_history>}`. Cost estimate documented in
  the module docstring: ~$0.05-$0.30/run in Claude calls (tenant's BYOK key) worst case, plus Firecrawl
  scrape credits — no new paid integration. **`learn_channel` has NO route/chat/UI door wired to it
  yet** (that's C42/C45) — it is importable and fully tested but has zero live callers today.
  VERIFIED: 18 new tests (`tests/functional/test_c41_channel_dna.py` — 14 orchestration/learner tests
  incl. call order, per-learner fail-soft isolation, not-my-channel import-first, claim held/released
  incl. on an exception, double-run busy refusal, script-template replaced-vs-saved wording, and
  reference-video's real fold-in through `stamp_identity_write` proving the `reference_video` provenance
  tag; + 4 `generation_claims.acquire_channel`/`release_channel` fake-pool tests). Non-vacuous: `git
  stash` of the 2 modified tracked files (`generation_claims.py`, `routes/onboarding.py` — `channel_dna.py`
  + the test file + the migration are new/untracked and stay) reproduces exactly 10/14 failures
  (every claim-touching test), confirmed live, stash popped back. Full suite **1333P/15F/1E** =
  baseline(1319P)+14 (the 4 claim tests live inside that same file/count), zero new failures.
  `py_compile` clean. Frontend untouched (`git diff --stat` shows no `storyengine/frontend/` changes).
  Live "learn a real channel" run deferred → `tasks/live-verification-queue.md` §C41 (also flagged as
  C42's own natural live test — do both together). ff-merged to main (orchestrator verdict — audit table + zero-line pipeline_executor diff accepted as byte-identity proof; the two declined merges were correct restraint)
  callers of the new module yet, so this chunk cannot regress any existing user-facing flow).
  **Next up: C42 · P4.1c chat front door + confirmable digest card** — wire `learn_channel` behind a
  "learn this channel: <url>" chat intent (ack-now background-task pattern — `progress_cb` already
  supports it), render the digest as a per-field confirm-before-save card (closes identity_builder's
  save-without-review gap), route corrections to C44's seam.
- **Also done:** C42 · P4.1c "learn this channel" chat front door + confirmable digest card — DONE
  2026-07-19, full detail in SYSTEM_STATE.md §C42. `learn_channel` gets its first real callers: a chat
  intent (`_learn_channel_intent` — a SIBLING of `_identity_intent`, not a rewrite: matches "channel" +
  a learn/study/analyze/manage/managing verb, dispatched BEFORE `_identity_intent` so "learn my
  channel's voice" gets the FULL C41 orchestrator, not identity_builder alone) and a thin
  `POST/GET /api/channel-dna/learn|status` route (new `routes/channel_dna.py`, proven to call the
  EXACT SAME `learn_channel` callable chat uses — one implementation, two doors, for C45/onboarding + a
  future MCP tool). `_handle_learn_channel` mirrors `_handle_build_identity`'s exact ack-now +
  background-task shape, states the ~$0.10-0.30 cost per the checklist's money-honesty requirement
  (flagged for Ryan: no confirm gate added, matching the existing identity-build + research/SEO-verb
  precedent — if storyengine/CLAUDE.md's "paid generation gets a quote+yes" rule was meant to cover ANY
  spend, this should gate too). New `channel_dna_digest` card kind (S9-3 lookup-table pattern, zero new
  scattered `card.id === ` checks): per-learner status rows + per-field rows with `_sources` provenance
  and a Revert button (server re-resolves the history index at click time, never trusts the client),
  an honest header when a learner failed. Card actions (deterministic, source-locked before producer
  intake, same discipline as C22's style_draft confirm): **keep** (default, no write — C41 already
  saved on write, per the checklist's own design law for this chunk, which supersedes the checklist's
  older "confirm-before-save" phrasing), **revert** (`channel_dna.revert_field`, C40's history undo),
  **correct** (free text → a channel-scope `director_preference` via the existing `_save_preference` —
  the deterministic form-posted precursor to C44's full remember/forget routing). New `_last_run`
  envelope key (`channel_dna_meta.py`, alongside `_sources`/`_history`) persists each run's digest so a
  later turn/route read doesn't need to re-run anything; `_persist_last_run` fails soft (an `execute()`
  hiccup can't break an otherwise-successful `learn_channel` call). MCP tool deferred (not "cheap" this
  chunk — `routes/mcp.py`'s tool calls are synchronous, a 1-2 minute-blocking tool is a different
  reliability shape; C25a's held media-proxy files untouched). VERIFIED: 37 new tests non-vacuous via
  `git stash -u`, full suite **1370P/15F/1E** = baseline(1333)+37 zero new failures, `py_compile` clean,
  tsc + `npm run build` clean, zero new `card.id === "` matches (grep-confirmed). Live end-to-end
  (chat digest render + revert/correct round-trip + thin-route parity) deferred →
  `tasks/live-verification-queue.md` §C42 (subsumes §C41's now-merged entry). No migration, no schema
  change, additive-both-directions frontend. Safe to ff-merge.
  **Next up: C43 · P4.1d consumption audit + convergence** — every build path reads the ONE saved DNA
  object; reconcile `identity.py`'s per-request injection vs `system_prompts.py`'s one-shot
  `tenant_prompt_defaults` writes (can silently fight today); reconcile the TWO thumbnail-formula
  impls (`pipeline_executor` vs `identity_builder`).
- **Also done:** C43 · P4.1d consumption audit + convergence — DONE 2026-07-19, full detail in
  SYSTEM_STATE.md §C43. Audit: traced every generation path (chat/queue-worker/autopilot/direct-routes
  all instantiate the SAME `PipelineExecutor`, one execution engine, not parallel implementations) —
  every stage reads channel DNA through `_load_prompt_overrides`/`_export_visual_style` →
  `build_identity_context` → `resolve_prompt`/env-seam, or a documented direct `channel_identity->'...'`
  read (research_approach, thumbnail_style, thumbnail_blueprint, static_docu's visual_format) — zero
  undocumented gaps found. `creator_brief` NOT reaching generation assessed as CORRECT DESIGN (chat-
  continuity memory, not voice DNA — forcing it in would conflate "what the creator once said" with
  "how the channel's own videos actually sound," identity_builder's own stated principle), not fixed.
  Precedence law (per-video > tenant override > identity-filled neutral template) confirmed already
  correct via the pre-existing `test_resolve_prompt.py` — no code change there. Real risk was SILENCE:
  `routes/system_prompts.py::generate_prompts` blind-overwrote `channel_profiles.style_description` (the
  same column `identity_builder` COALESCE-writes + stamps) with zero provenance — now it ALSO
  read-modify-writes `channel_identity` via `channel_dna_meta.stamp_identity_write(learner=
  "system_prompts")` so a later DNA digest shows the overwrite; unrelated identity_builder fields
  survive untouched (proven by test). Thumbnail convergence: confirmed the two flagged impls
  (`identity_builder._thumbnail_style` = consensus-across-3-thumbnails aggregate; `routes/model_video.
  _describe_thumbnail_style` = one detailed blueprint, feeding `pipeline_executor.
  _run_channel_formula_thumbnail`) are NOT duplicate computations — different schemas for different
  consumers, and the pipeline already treats identity_builder's output as the authoritative tie-breaker
  over the blueprint on conflict. Collapsing schemas was rejected as bigger-than-warranted; the real
  drift was RELIABILITY — `_thumbnail_style` hit Kie's Claude gateway directly with a raw httpx call,
  the exact endpoint `shared/clients/vision_client.py` exists to route around (twice-drifted silent
  image-block-drop bug). Converged it onto the SAME safe `vision_call` primitive
  `_describe_thumbnail_style` already used; `pipeline_executor.py` itself has a ZERO-line diff this
  chunk (git diff --stat empty) — the strongest possible proof the no-DNA fallback ordering stayed
  byte-identical. VERIFIED: 5 new tests non-vacuous via `git stash -u` (reproduces exact pre-chunk
  baseline 1370P/15F/1E), full suite **1375P/15F/1E** = baseline+5 zero new failures, `py_compile`
  clean, `test_resolve_prompt.py`/`test_channel_dna_meta.py`/`test_system_prompts_generate.py` (33
  tests) all pass unmodified. Frontend untouched (no diff, no new UI surface). No migration, no schema
  change, no new route — safe to ff-merge. Live verification (a real DNA digest showing the
  `system_prompts` provenance tag; a real vision_call against live Kie thumbnails) deferred →
  `tasks/live-verification-queue.md` §C43.
  **Next up: C44 · corrections loop wiring** — formalize the LLM-classified remember/forget routing
  C42's digest-card "correct" action deliberately deferred (today: a deterministic form-post to
  `_save_preference`, not the full natural-language classification `_handle_copilot`'s remember/forget
  triggers already do elsewhere).
- **Also done:** C44 · P4.1e corrections loop wiring — DONE 2026-07-19, full detail in SYSTEM_STATE.md
  §C44. The core wire: `identity.py` gained `IdentityContext.standing_preferences` (new field, default
  "") + `_standing_preferences_block(tenant_id)`, a channel-scope-ONLY, capped (20 rows / 3000 chars),
  fail-soft read of `director_preferences` (C15c) — injected into the ONE seam every generation stage
  shares per C43's own audit table (`build_identity_context`, consumed by both
  `_load_prompt_overrides` -> `resolve_prompt` for script/research/thumbnail/title/video_motion, and
  `_export_visual_style` for the image pipeline's env seam). Deliberately a SEPARATE minimal query, not
  an import of chat.py's `_list_preferences` — chat.py sits on a heavy import chain (FastAPI router,
  actions.py, the whole skills/video-pipeline package via actions.py's own sys.path insert) this
  low-level, widely-imported module must not pull in. Precedence law extended one rung:
  `pipeline_executor.resolve_prompt` now APPENDS `identity.standing_preferences` after whichever prompt
  source won (per-video override > tenant override > standing preferences > neutral template), framed
  "STANDING CREATOR DIRECTIONS (obey these over any conflicting learned style):" — mirrors C15c's chat
  framing, applies unconditionally so a tenant's custom override can't silently swallow it, and is a
  pure no-op (byte-identical output) for every tenant with zero preferences (empty string default).
  Per-video-scoped preferences deliberately STAY chat-only (not read into generation) — a note about
  ONE video's chat session shouldn't rewrite how the CHANNEL builds every other video, and
  `build_identity_context` is shared across every video for a tenant; C15c's own `_preferences_brief`
  already scopes it this way (channel-wide + this-video-only, hydrated only into that video's chat).
  Digest extension (`_build_dna_digest_card` in routes/chat.py): a cheap, explicitly-NOT-NLP keyword
  match (`_FIELD_OVERRIDE_KEYWORDS`/`_match_preference_override`, per the checklist's own hedge) flags a
  learned field's `overridden_by` when a standing preference's text mentions that field's keyword(s);
  since a real correction often won't use the field's exact word, the card ALSO carries an
  unconditional `standing_directions` footer (every active channel-scope preference, regardless of
  match) so nothing is ever silently hidden by a keyword miss — chose the hybrid over a footer-only
  design specifically so a clean keyword hit still gets the more useful inline "this exact field is
  overridden" flag. Frontend: `ChatDnaFieldRow.overridden_by` + `ChatCard.standing_directions` (both
  optional/additive), `DnaDigestCard` renders an inline "Overridden by your standing direction: ..."
  note per field plus a "Your standing directions" footer section (new `History`/`PencilLine` icon
  reuse, no new imports). The `web-design-system` skill CLAUDE.md mandates for UI work is not installed
  in this environment (only the review-only `web-design-guidelines` skill exists) — followed the
  existing `DnaDigestCard`'s established component/CSS-var language instead, flagged here rather than
  silently skipped. 21 new tests in `test_c44_corrections_loop.py`, non-vacuous via `git stash` (20/21
  fail against the pre-C44 baseline — the 21st is the explicit "empty preferences = byte-identical to
  pre-C44" regression pin, which correctly still passes on the old code too). Full backend suite
  **1396P/15F/1E** = baseline(1375)+21, zero new failures — same 15 failure names/1 error as C40-C43's
  documented baseline. `py_compile` clean. Frontend: `npx tsc --noEmit` clean, `npm run build` clean
  (same pre-existing `NEXT_PUBLIC_API_URL` prerender note), zero new `card.id === "` matches (grep-
  confirmed — the only new JSX lives inside the existing `channel_dna_digest` branch). C15c regression
  pinned: `_preferences_brief`'s own chat-turn framing text is asserted UNCHANGED and distinct from the
  new generation-seam framing (different strings, by design — one is per-turn chat guidance, the other
  is a standing generation directive). No migration, no schema change, no new route. Live verification
  (a real chat correction changing the NEXT real script/research/thumbnail generation) deferred to
  `tasks/live-verification-queue.md` §C44. Deploy-safe both directions, additive-only — ff-merge
  candidate.
- **Also done:** C45 · P4.1f onboarding hookup + intelligence-report retirement — the P4.1 closer,
  DONE 2026-07-19, full detail in SYSTEM_STATE.md §C45. Traced the LIVE onboarding surface first (not
  the stale docstring): `/onboarding` now
  redirects to the chat-driven flow at `/` (the multi-step form only survives behind
  `?manual=1`, and its own STEPS array doesn't even render a competitors/intelligence step) —
  `routes/chat.py`'s `_handle_onboarding` step machine is the one real caller of
  `routes.onboarding.connect_youtube`/`analyze_competitors`, and it already fires-and-forgets every
  background step (never "waits" on anything) — so the smallest-change hook point is
  `connect_youtube` itself, not a new step. Added `_import_then_learn` (one background task:
  import, THEN `channel_dna.learn_channel(tenant_id)` in own-channel mode — no `channel_url`, since
  the import already seeded `channel_videos` and passing one would make learn_channel's own
  optional import step re-scrape the same channel a second time), gated by a new
  `_has_usable_generation_key` check computed BEFORE scheduling — a keyless tenant gets zero
  background tasks and a `dna_learning: "needs_key"` response field instead of a doomed task;
  `connect_youtube` reports `"started"`/`"needs_key"` so `_handle_onboarding`'s "channel" step ack
  either states the ~$0.10-0.30 cost or shows a non-blocking "add a key" hint (C04 precedent —
  onboarding always advances to "competitors" regardless). Digest surfacing: rather than invent a
  new wait-then-show step (nothing else in this flow waits either), `_finish_onboarding` — the
  existing end-of-flow moment that already folds in competitor results — now also checks
  `channel_dna.is_learning`/`channel_identity["_last_run"]` and appends the SAME C42
  `_build_dna_digest_card` card the "show the channel digest" chat intent renders (one digest, both
  surfaces, no second renderer), or a "still learning, ask me in a bit" note if the background pass
  hasn't finished yet, or nothing at all if no channel was ever connected. Retirement: grepped every
  frontend surface (chat + manual form + api.ts) and found ZERO callers of
  `/api/onboarding/intelligence-report*` anywhere — the live flow was already using
  `_propose_modeling_angles`/`_generate_competitor_ideas` before this chunk, so there was no
  frontend step left to re-point. The 3 routes now return `410 Gone` pointing at Channel DNA
  (matching this repo's existing 410-retirement convention, e.g. `routes/pipeline.py`);
  `_build_intelligence_report` + `_fallback_intelligence_report` + `_parse_report_json` +
  `_run_intelligence_report_job` + the `_report_jobs` dict + the unused `IntelligenceReportRequest`
  model are DELETED outright (not left unreachable) — grep-proofed zero remaining callers.
  `intelligence_reports` (DB table) is untouched, retired-in-place, no drop migration — same for
  `content_intelligence` (a DIFFERENT, actively-used table the original brief's parenthetical
  conflated with `intelligence_reports`; confirmed by grep it's read by `/api/intelligence/*`,
  distillation, discovery, autopilot, dashboard — correctly left alone). 19 new tests in
  `test_c45_onboarding_dna_hookup.py`, non-vacuous via the pre-C45 baseline commit (`8b44187`) swapped
  in for `routes/onboarding.py`/`routes/chat.py` since a parallel docs commit on this branch had
  already folded part of this chunk's onboarding.py diff into history mid-session (`git stash` would
  have been distorted) — 18/19 fail against that baseline. Full backend suite **1415P/15F/1E** =
  baseline(1396)+19, zero new failures, identical 15 failure names/1 error. `py_compile` clean on
  all touched modules. Frontend untouched (no re-pointing needed, per the grep above) — `npx tsc
  --noEmit` clean regardless. No migration, no schema change, no new route (only 410s on 3 existing
  ones). Deploy-safe, additive-only on the live path — ff-merged to main (orchestrator verdict — P4.1 C40-C45 COMPLETE; the worker's brief-error catch (content_intelligence is LIVE, intelligence_reports was the dead one) is exactly the skeptical verification the loop wants; git-incident handling per corrected instructions accepted). Live verification (fresh
  tenant → onboard → channel learned → digest → produce, closing the whole P4.1 arc's acceptance
  test) deferred to `tasks/live-verification-queue.md` §C45.
  **P4.1 COMPLETE (C40-C45, 2026-07-19).** Next: either C46 (quality-rules engine, awaiting Ryan's
  yes) or P4.2 (tenant-autopilot scouting) — the orchestrator decides.
- **Also done:** C46a · generalize the script-quality critic hook — DONE 2026-07-19, full detail in
  SYSTEM_STATE.md §C46a. Ryan approved C46 with a HARD constraint (decisions.md 2026-07-19): the
  quality-rules engine must AUDIT-THEN-ABSORB his prior dial-in work, never build a parallel path.
  Traced first: `originality.py::grade_script`/`grade_script_with_client` (the fail-open LLM judge) and
  the DvsU EDIT-loop pattern (`_run_static_script_hold`'s same-draft targeted edit, 2-round bound) —
  AND found `_grade_and_maybe_revise_script` already wired into `run_script` at 2 call sites, so this
  chunk generalizes/absorbs an EXISTING hook, it doesn't add a new one. New
  `storyengine/backend/script_quality.py`: `critique_script(...)` reuses originality's judge prompt
  verbatim + an optional per-tenant `rules_text` pass (wired to `script_templates.structure` — the
  cheapest EXISTING per-tenant rules-ish text, until C46b's real rules table lands);
  `edit_draft_with_violations(...)` generalizes DvsU's exact edit prompt from its 5-sentence-paragraph
  shape to an arbitrary multi-scene script via the `@@@SCENE n@@@` marker format the modeled-script
  path/`user_script.py` already share (kept import-free of pipeline_executor, mirroring originality.py's
  own decoupling); `run_critique_and_edit(...)` orchestrates the bound: `revise` → same-draft edit loop
  (max 2 rounds), `regenerate` → one fresh reroll via a caller callback, still failing → `needs_review`.
  Wiring: `_grade_and_maybe_revise_script` now calls this (the SAME single grading call, confirmed not
  doubled), persists edited scenes back to the `scripts` table + `videos.script`, attaches violations to
  `videos.script_validation.quality_critic`, and (new) returns `{needs_review, violations}` so
  `run_script`'s plain AND modeled call sites can short-circuit to `{"status": "needs_review", ...}`
  instead of silently advancing — the modeled path passes `hold_status=current_status` since
  `_run_modeled_script` already commits `ready_for_voice` before grading runs, so a still-failing verdict
  reverts that status. **Additivity for the static-docu roster path:** it already runs a stricter
  hard-gate harness (`_validate_machine_story_sentences` + its own bounded EDIT loop), so per Ryan's
  constraint the generic critic runs there ONLY as telemetry (new `_telemetry_quality_critique` — one
  best-effort grade recorded, no edit loop, no status change) — genuinely new coverage (that path fired
  zero grading calls before), not a duplicate. `user_script.py`'s `user_supplied` bypass is untouched,
  pinned by a dedicated test. VERIFIED: 35 new tests (`test_script_quality.py` ×22 pure-module,
  `test_c46a_quality_critic_wiring.py` ×13 PipelineExecutor wiring) — non-vacuous via `git stash` on
  `pipeline_executor.py` alone (11/13 wiring tests fail against pre-C46a code; the 2 that still pass
  legitimately pin unchanged backward-compat behavior) plus moving `script_quality.py` aside (import
  error, proving the new module itself is exercised). `python -m py_compile` clean on all 4
  touched/new files. Full backend suite **1450P/15F/1E** = baseline(1415P/15F/1E, independently
  re-confirmed) + exactly 35, identical failure names, zero new failures. Existing
  `test_machine_documentary_hold.py` (239 tests) still passes unchanged. Frontend untouched (confirmed
  via `git status`/`git diff --stat`). Checklist §C46a ticked. **Deploy-safety: recommend ff-merge
  candidate, not yet merged by this chunk** (left to the orchestrator) — no migration/schema/route
  change, but flags one real user-visible behavior change worth a second look before merge: a script
  that's STILL `needs_review` after the full bounded loop no longer silently advances to
  `ready_for_voice` on the plain/modeled paths (pre-C46a always advanced, "silent nudge" only) — a
  deliberate formalization of DvsU's own `_save_machine_script_block` gating convention, but real.
  Live grade-a-real-script check deferred → `tasks/live-verification-queue.md` §C46a. **Next: C46b · per-
  channel rules store** (new table modeled on the QL/QD row shape + `shared/profiles/script`'s typed
  schema — replaces this chunk's `script_templates.structure` stopgap `rules_text` source with the real
  thing).
- **Also done:** C46b · per-channel quality-rules store with scope-aware resolution — DONE 2026-07-19,
  full detail in SYSTEM_STATE.md §C46b. New `quality_rules` table (migration 105, applied LIVE via
  Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`, 0 rows today):
  `tenant_id`/`rule_id`/`law`/`evidence`/`severity` (hard_gate|warn|guidance)/`applies_to` jsonb/`source`
  (doc_upload|chat|seed)/`active`, `UNIQUE(tenant_id, rule_id)`, RLS enabled no policies. **`applies_to`
  vocabulary** (Ryan's 2026-07-19 scoping requirement — resolved from DATA the video carries, never LLM
  judgment about which gates apply): `all` (universal), `research` (from `videos.research_skipped` +
  `pipeline_stages` workflow plan), `story` (from `render_mode == 'static_docu'`, the one signal that
  identifies a narrative-arc format today), `animated`/`realistic` (from `render_style`), `channel_format`
  (string-valued, forward-compatible stub — no live data source plumbed yet, documented boundary). A rule
  matches if ANY key resolves true (OR); a hybrid research+story video (e.g. DvsU) collects BOTH scopes'
  rules; an unrecognized key is logged+skipped, never matches, never crashes. `quality_rules.py`'s
  `active_rules_for_video`/`resolve_video_shape`/`rule_matches`/`compose_rules_text` are PURE (no DB) —
  `pipeline_executor.py` fetches rule rows itself via its own already-patched `fetch_all` (matching
  `test_c46a_quality_critic_wiring.py`'s fake-DB convention) rather than a second, separately-mockable DB
  surface, which is exactly what let C46a's existing wiring test keep passing unmodified against the new
  code path. **Severity reaches the critic's blocking logic**: `script_quality.critique_script`/
  `run_critique_and_edit` gained an optional `severity_by_rule` map (default `None`, byte-compatible); new
  `_apply_rule_severity` deterministically upgrades a judge's own `"pass"` to `"revise"` when a FAILED
  rule_verdict names a `hard_gate` rule — proven end-to-end through `pipeline_executor`'s real wiring (3
  Claude calls: forced-revise grade → edit → re-grade pass, scenes actually persisted), not just at the
  script_quality unit level. `_grade_and_maybe_revise_script`'s `rules_text` seam now sources from
  `quality_rules` FIRST, with `script_templates.structure` (the house FORMAT, a distinct signal from a
  graded LAW) kept as an ADDITIONAL block, never dropped — empty-both case stays byte-identical `""`.
  **Two ingestion doors:** (1) chat op `draft_quality_rules` (mirrors C22's `draft_style` confirm pattern
  exactly — stash-only, a preview card, `_handle_quality_rules_draft_confirm` is the ONLY place a row can
  be created from chat, gated on an explicit "yes"; producer taught the vocabulary in prose + the
  `profile_ops` JSON schema example); (2) thin CRUD route `routes/quality_rules.py`
  (`GET/POST/PATCH/DELETE /api/quality-rules[/{id}]`, tenant-scoped, registered in `main.py`) for C47's
  MCP pickup + a future settings UI, no UI this chunk. **Parser:** `parse_markdown_table` is a
  deterministic, zero-cost pipe-table splitter that round-trips `dvsu-quality-law.md`'s own row shape
  exactly (tried first); `llm_parse_rules_prose` is the one-Claude-call fallback for non-tabular docs
  (only reached when the table parser finds zero rows, proven by a forbidden-call assertion);
  `suggest_applies_to` is a zero-cost keyword-heuristic DEFAULT scope proposed at ingestion time only —
  explicitly distinct from, never a substitute for, the runtime resolver. **Not this chunk:** DvsU's 74
  laws are NOT seeded (C46c's job, deliberately, as the reference-tenant proof); no gate-behavior changes
  beyond feeding the existing critic real rules; no settings UI. VERIFIED: 61 new tests
  (`test_quality_rules.py` ×39 pure-module, `test_c46b_quality_rules_wiring.py` ×22 wiring) — non-vacuous
  via `git stash push` on the 6 tracked modified files + temporarily moving aside the 2 new modules (both
  new test files fail to collect, `ModuleNotFoundError`, against pre-chunk code). `python -m py_compile`
  clean on all 8 touched/new files. Full backend suite **1511P/15F/1E** = baseline(1450P/15F/1E) +
  exactly 61, identical 15 pre-existing failure names/1 error (all unrelated — YouTube OAuth/oembed,
  discovery, activity-feed, clip-dialogue ffmpeg), zero new failures. Frontend untouched — confirmed via
  `git status`, no `tsc`/`build` run needed (no UI this chunk, per spec). Checklist §C46b ticked.
  **Deploy-safety: recommend ff-merged to main (orchestrator verdict — deterministic scope resolution per Ryan's requirement, severity→blocking proven end-to-end, ships inert at 0 rows), not yet ff-merged by this chunk** (left to the
  orchestrator) — additive migration (new table, zero risk to any existing query), new route (dark, no
  frontend caller yet), new chat op (dormant until the producer LLM actually emits it live — a real chat
  round-trip is queued, not proven here). The one hot-path change (`rules_text` composition) ships inert
  today since the live `quality_rules` table has 0 rows for every tenant (confirmed via Supabase MCP).
  Live doc-upload round-trip, prose-fallback-parser-against-a-real-model, and scope-matched-rules-change-
  real-grading checks deferred → `tasks/live-verification-queue.md` §C46b. **Next: C46c · DvsU deltas as
  reference implementation** — seed the 74 laws via this chunk's `bulk_create_rules`/`source="seed"`,
  replacing `_validate_machine_story_sentences`'s hardcoded constants with reads from this table.
- **Also done:** C46c · DvsU deltas as the reference-tenant table-driven gates — DONE 2026-07-19, full
  detail in SYSTEM_STATE.md §C46c. **Key finding before writing code:** D1/D2/D3 (word floor 80, twist-
  or-substitute hard gate, expanded twist taxonomy) were ALREADY landed as hardcoded constants in an
  earlier session, byte-identical to the law — the doc's §3 DELTAS table describing them as open gaps is
  stale, not a live to-do. Only QL-12 (banned-hype list) was a genuine mismatch (an older ad hoc
  superlative-phrase list, not the law's actual banned-adjective list) — UNIONED, not replaced (additivity
  is sacred). New seed script `scripts/seed_dvsu_quality_rules.py` (NOT wired into any migration/cron/
  auto-seed — DvsU is a real production tenant on the LIVE db): parses the doc via C46b's
  `parse_markdown_table` (exactly 74 rows, QL-1..QL-74 — QD-1..6 use a 4-column table format the parser's
  5-cell minimum doesn't match, and are already reflected in the landed code's own QD-tagged comments
  regardless), assigns `applies_to` scope by SECTION (not the generic keyword-heuristic default): QL-1..20
  → `story` (49 rows once 46-74 are folded in), QL-21..24 → `all`, QL-25..45 → `research`, QL-46..74 →
  `story` as the closest existing fit (**flagged, not papered over**: C46b's scope vocabulary has no
  dedicated voiceover/image/thumbnail key yet). `--dry-run` default (zero DB touch), `--apply` required to
  write, idempotent via `bulk_create_rules`. New `quality_rules.resolve_dvsu_overrides` (pure): parses
  QL-1/QL-3/QL-4/QL-12's `law` text with targeted regexes proven against the REAL doc into structured
  override values (word_floor, twist_gate severity, twist_menu, banned_hype_words) — a rule_id absent or
  its law text reworded away from the pattern means that key is simply missing, never raises. `pipeline_
  executor.py`'s `_validate_static_unit_paragraph`/`_validate_machine_story_sentences`/`_anton_preview_
  quality_audit` each gained an optional `rule_overrides=None` param (100% backward-compatible — the
  9000-line existing test suite calls these with 2-3 positional args hundreds of times, needed zero
  changes beyond one fetch-call-list assertion). Severity drives blocking vs advisory uniformly
  (`!= "hard_gate"` demotes to advisory, never suppresses). New `PipelineExecutor._load_dvsu_rule_
  overrides` fetches+scope-matches+resolves ONCE per `_run_static_script_hold` run (proven before the
  per-machine loop via a wiring-lock test) and threads through every validator call (wiring-lock tests
  grep the method's own source, mirroring `test_first_run_checklist_wired_lock.py`'s pattern).
  **Generalization proof:** a hypothetical "Acme Explainers" tenant's own completely different word-count
  law round-trips through the exact same resolver and gets its OWN numbers back — nothing reads "DvsU" or
  any channel-specific string. **Open rulings left for Ryan, not decided:** OR-5 (crew-hate variant
  scope), OR-6 (corpus hygiene tagging — not a code change), OR-9 (fixed thumbnail-text set) — OR-1
  through OR-4/OR-7/OR-8 are already ruled AND already landed, not re-litigated. VERIFIED: 28 new tests
  across 4 files (`test_quality_rules.py` +8, `test_machine_documentary_hold.py` +8 plus 1 updated fetch-
  call assertion, `test_c46c_dvsu_deltas_wiring.py` +6 NEW, `test_c46c_seed_dvsu_quality_rules.py` +6 NEW)
  — non-vacuous via `git stash -u`: reverted → **15F/1511P/1E** (identical to C46b's own baseline,
  confirming the 15/1 are genuinely pre-existing), popped back → **15F/1539P/1E** = exactly +28, zero new
  failures. The pre-existing `test_machine_documentary_hold.py` suite (239 tests before this chunk) stayed
  100% green untouched — every call there omits the new `rule_overrides` arg, exercising the byte-
  identical fallback by construction. `python -m py_compile` clean on all 7 touched/new files. Frontend
  untouched — confirmed via `git status`. Checklist §C46c ticked. **Deploy-safety: recommend ff-merge
  candidate, not yet ff-merged by this chunk** (left to the orchestrator) — zero behavior change for every
  tenant today (the live `quality_rules` table still has 0 rows; the seed script is deliberately NOT run
  this chunk); the only thing that changes ANYTHING once the seed script runs with `--apply` is the DvsU
  tenant's own script-hold gates, no other tenant reachable by this path. **Live seed run deferred to
  `tasks/live-verification-queue.md` §C46c** (exact command + expected row count + post-seed smoke plan —
  this chunk deliberately does not touch the live DB). **Next: C46d · trust boundaries** — MCP/agent-
  submitted scripts (C47 ingest) pass the SAME critic; `user_supplied` verbatim scripts keep their
  explicit no-gate bypass; wire the critic verdict into the C42 digest/chat surfaces so failures list
  rule-by-rule.
- **Also done:** C46d · trust boundaries — the C46 arc closer — DONE 2026-07-19, full detail in
  SYSTEM_STATE.md §C46d. New `user_script.accept_external_script(tenant_id, video_id, scenes, source=)` —
  the seam C47's MCP `submit_script` tool will call. Design call: unlike `run_script`'s own bounded EDIT
  loop (fair game — it's editing OUR OWN draft), an agent-submitted script gets NO server-side rewrite —
  the words aren't ours to change — so this runs `script_quality.critique_script` verdict-only (proven:
  one grading call per test, never a second) and branches: `pass` (incl. WARN-severity rule failures that
  never flip the verdict) → ACCEPT, saved through the exact scene/`videos.script` path `set_user_script`
  uses, `script_source` = the caller's value (default `agent_submitted`, never `user_supplied` —
  `source='user_supplied'` is refused outright, that contract stays `set_user_script`'s alone), status
  advances; `revise`/`regenerate` (universal gate OR hard-gate channel rule) → REJECT, nothing saved,
  nothing advances, full rule-by-rule violations returned so the agent can fix and resubmit. **Two real
  gaps found while tracing the "natural host" for surfacing (not just wired around):** (1)
  `routes/videos.py::_parse_script_validation` (the GET /api/videos/{id} serializer) was silently dropping
  a `script_validation` blob to `None` whenever it held ONLY `{"quality_critic": {...}}` (no sibling
  `"checks"` key) — exactly what `_grade_and_maybe_revise_script` writes for a plain script hold and what
  `accept_external_script` writes on accept — so the banner would have had nothing to render for the most
  common case; fixed by widening the passthrough condition. (2) `run_script`'s `needs_review` return dicts
  carried `violations` but no `"error"`/`"message"`, and `_set_task_status` normalizes any non-running/
  non-failed status to "completed" — so the task-status/chat surface showed a bare "completed" with zero
  indication anything was flagged; fixed by attaching a `"message"` field (both `needs_review` dicts) and
  extending the direct `/script` route's `_set_task_status` call to the same error-or-message fallback
  `actions.py::make_action_step` already had. New "Quality Review Needed" card in `ScriptVoiceTab.tsx`
  (natural host — sits right next to the existing "Script Validation" card): rule-by-rule + severity
  (FAIL/WARN badges from the now-extended `quality_critic.rule_verdicts`/`severity_by_rule`), "Use it
  anyway" (the EXISTING `advanceVideo`/`PATCH /advance` verb, zero new backend code, gated by a light
  confirm — free and effectively reversible, the hold only ever parks `videos.status`) and "Regenerate"
  (the EXISTING `handleRegenerateScript` callback) — no new verbs invented, both buttons hand off to code
  that already existed and was already tested. VERIFIED: 15 new tests (`test_c46d_trust_boundaries.py`) —
  accept/reject/warn matrix incl. severity-driven hard-gate rejection with the rule id named, `user_
  supplied` refusal before any DB touch, tenant scoping (wrong tenant = not-found, zero writes), 5
  parametrized bad-scene-shape cases (all raise before any `execute`), 3 `_parse_script_validation` cases
  (the fix + 2 regression checks proving `checks`-shape and legacy-plain-text paths are untouched) — plus
  2 pinned C46a tests extended (not weakened) for the new `"message"` key. Non-vacuous via plain `git
  stash` (source only, new test file stays): **13/15 new tests fail** against pre-C46d code (the 2 that
  still pass are the deliberately-unaffected regression checks) — `AttributeError: no attribute
  'accept_external_script'` and the quality_critic blob dropping to `None`. Popped back: full suite
  **1554P/15F/1E** = baseline (1539/15/1) + exactly 15, zero new failures. `python -m py_compile` clean.
  Frontend: `npx tsc --noEmit` clean; `npm run build` compiles/typechecks clean (the one build-time error,
  a missing `NEXT_PUBLIC_API_URL`, is a pre-existing env-config requirement, confirmed unrelated by setting
  the var and getting a fully clean build). **Deploy-safety: recommend ff-merge candidate** — every new
  dict key is additive-only, `_parse_script_validation`'s widened condition is strictly more permissive
  (proven by regression tests), `accept_external_script` is inert dead-code-with-tests until C47 registers
  an MCP tool that calls it, and the new frontend card is unreachable today (zero videos in production
  have ever produced a `quality_critic.passed === false` shape — quality_rules still has 0 live rows per
  C46a/b/c). Live round-trip (a real MCP submit + a real browser look at the banner) deferred to
  `tasks/live-verification-queue.md` §C46d.
- **Also done:** C46e · Land Ryan's OR rulings (decisions.md 2026-07-19 OR-5/OR-6/OR-9 + the same-day OR-6
  expansion + import-caveat entries) — full detail in SYSTEM_STATE.md §C46e. Part 1 (OR-5 + D7): the
  "Most Hated" mode-selection mechanism (`_dvsu_mode_profile`, opt-in `research_payload.dvsu_mode`, never
  title-inferred) turned out to already be landed (Ryan wrote it 2026-07-16, ahead of the formal ruling);
  what was missing — its opener-budget/memorable-source overrides being table-driven — is now landed:
  new `dvsu_mode` string `applies_to` scope key, two new `resolve_dvsu_overrides` keys from hand-authored
  seed rows (QL-7-MH/QL-9-MH), `_machine_story_plan` prefers the table value only when
  `mode_profile["mode"]=="most_hated"`. D7 (QL-10 number rendering) was ALSO already landed
  (`_raw_digit_mentions_for_voiceover`, dated 2026-07-16, "OR-4 approved") — unblocked now that OR-5 is
  ruled. Part 2 (OR-6 EXPANDED): new `channel_patterns` table (migration 106, live via Supabase MCP against
  `wrromlupsmyzrrcqlucn`) + `channel_patterns.py` (pure exclusion resolver — only
  `status='confirmed' AND polarity='anti'` rows ever exclude anything — plus CRUD + `score_outlier_patterns`
  import-time analysis against the channel's own VPH/CTR/retention median); wired into
  `identity_builder.py::_ranked_videos` (the real style-seed picker OR-6's own MostHated-Warships example
  was about) for exclusion, `channel_dna.py::learn_channel` as a 6th learner (`_run_pattern_analysis`) for
  import-time proposals, and `routes/chat.py`'s DNA digest card (+ `ChatCore.tsx`) for Confirm/Retire —
  nothing takes effect until confirmed. Per-launch incremental proposals are explicitly P4.2's flywheel,
  not built here — seam is `create_pattern(..., source="launch_analysis")`. Part 3 (OR-9/QL-66): the
  checklist's "verify already matches, expected no change" premise did NOT hold — zero code anywhere
  (StoryEngine or the legacy pipeline) implemented the five-locked-phrase rule before this chunk; landed
  `_dvsu_thumbnail_series_warning` (pure, unit-tested) wired ADVISORY-only (never blocking) into
  `_run_channel_formula_thumbnail`. Law doc updated: §3 D1/D2/D3 corrected to "landed" (C46c's own finding),
  D7 corrected to "landed" (this chunk's finding); §4 OR-5/OR-6/OR-9 rulings recorded with the 2026-07-19
  date, mirroring OR-8's existing annotation style. VERIFIED: 6 new/extended test files (2 new pure-module
  files, 2 new wiring files, 2 extended), non-vacuous via `git stash -u` (reverts untracked new files too —
  needed since `channel_patterns.py`/its route/2 new test files are untracked): pre-C46e full suite
  **1554P/15F/1E** (exact match to the stated baseline), post-C46e **1624P/15F/1E** = baseline+70, zero new
  failures/errors. `python -m py_compile` clean on every touched file. `npx tsc --noEmit` clean; `npm run
  build` compiles+typechecks clean (fails only at the same pre-existing `NEXT_PUBLIC_API_URL`
  static-prerender gap C46d already noted, confirmed unrelated). **Deploy-safety: recommend ff-merge
  candidate** — every new scope key/override/table starts empty/inert for every tenant today (no seeded
  QL-7-MH/QL-9-MH row until the seed script's `--apply` runs; `channel_patterns` has zero rows until a
  learner run produces an outlier; the QL-66 check never blocks). One pre-existing, unrelated finding
  surfaced (not fixed — flagged per the Supabase MCP tool's own instruction): `static_reference_cache`/
  `channel_video_retention` have RLS disabled, fully exposed to anon/authenticated — needs Ryan's call on
  policies before enabling RLS (would otherwise block all access). Live import-analysis + confirm
  round-trip deferred to `tasks/live-verification-queue.md` §C46e. **C46 ARC (a-e) COMPLETE.** **Next: C47 ·
  MCP setup surface + ingest tools** — expose system prompts/script templates/quality rules/channel
  DNA/script-profile selection/channel-patterns CRUD through MCP, PLUS `submit_research`/`submit_script` —
  the latter now has `accept_external_script` ready and waiting. May split C47a (setup)/C47b (ingest) on
  size.
- **Also done:** C47 · MCP setup surface + content-ingest surface (decisions.md 2026-07-19's "MCP is the
  setup brain" + "MCP economics" entries) — shipped as ONE chunk, no split needed. Full detail in
  SYSTEM_STATE.md §C47. 16 setup tools (`get_channel_dna`, `learn_channel_start`/`_status`, quality-rules
  CRUD, channel-patterns confirm/retire, script template get/set, script profiles list, system prompts
  get/set, `set_render_style`/`set_style_preset`), all wrapping EXISTING functions/routes verbatim — no
  new logic, no parallel store. `script_profile`/`budget_cap` deliberately NOT duplicated (already free
  MCP verb tools since C27). 2 ingest tools: `submit_research` (new `research_ingest.py` — shape
  validation against the real `run_research` payload shape + reuse of `pipeline_executor._roster_
  validation` verbatim as the accept/reject gate, explicitly does NOT run the expensive live source-fetch
  hold step) and `submit_script` (thin wrapper over C46d's `accept_external_script`). Real gap found+
  fixed while tracing `set_style_preset`: `videos.style_preset_id` had NO write path after video creation
  at all — added to `update_video`'s `allowed_fields`, reusing the existing `_resolve_style_preset_id`
  validator. Attribution: `confirmed_by`/`source="mcp_agent"` land in real DB columns where one exists
  (channel_patterns/quality_rules); logged (not persisted) where no provenance column exists yet
  (tenant_prompt_defaults, script_templates) — flagged honestly, not invented around. 42 new tests
  (`tests/functional/test_c47_mcp_setup_and_ingest.py`), non-vacuous via `git stash` (test module fails to
  even collect without the implementation — `ModuleNotFoundError`), full suite **1666P/15F/1E** = baseline
  (1624/15/1) + exactly 42, zero new failures. `python -m py_compile` clean. Frontend: **untouched** (zero
  files changed — this chunk is entirely backend, no UI surface by design, still dark behind
  `MCP_ENABLED`). Live round-trip deferred to `tasks/live-verification-queue.md` §C29 Step 5b (folded into
  the existing MCP go-live runbook alongside C26/C27/C28, not a new fragment). **Deploy-safety: recommend
  ff-merge candidate** — every new tool is dead code until `MCP_ENABLED=true` AND an agent token exists
  (same posture as C26/C27); `style_preset_id`'s allowlist addition is the one change reachable outside
  the MCP flag (also benefits the ordinary web UI), strictly additive and re-validated through the same
  catalog check `create_video` already trusted.

  **Next up: P4.2 tenant-autopilot SCOUT (Explore, per the Phase-4 outline)** — the orchestrator
  dispatches it.
- **Also done:** P4.2 scout (Explore) — port map in audit report §P4.2 (headline: SaaS autopilot HALF-BUILT — `autopilot_config` table, `calculate_confidence_with_breakdown` scorer, `queue.py::auto_produce_next` 30-min loop as the template, real learnings loop; gaps: no scored-candidate auto-launch, no weekly budget, no kill switch, no early-warning classifier; scheduling verdict: sibling in-process loop, NO arq cron). Chunks C50-C56 queued in the checklist (commit 867ff2e). Ryan's "model this video" MCP flagship workflow recorded in decisions.md + folded into C48/C49 scope (commit 4a88895).
- **Also done:** C50 · P4.2-a autopilot dial schema — migration 107 (applied LIVE via Supabase MCP, orchestrator independently re-confirmed all 5 columns + CHECK via information_schema/pg_constraint): `autopilot_config` gains `dial_level` (propose_only|auto_draft|full_auto, NOT NULL default propose_only — today's semantics preserved), `weekly_budget_cap`, `weekly_spend_reset_at`, `kill_switch_tripped_at`, `kill_switch_reason` (kill switch = system-tripped, explicit human re-enable, DISTINCT from `enabled` — documented in migration header + accessor docstring). New `autopilot_dial.py` (`get_autopilot_dial(tenant_id) -> AutopilotDial` dataclass, safe defaults on missing row) is the SINGLE read surface C51-C56 import; additive fields on `GET /api/autopilot/summary`'s AutopilotConfig (skew-safe, old frontend ignores). NO writers yet (by design — C52/C54). Commit 53d73cd. VERIFIED: 7 new tests non-vacuous (ModuleNotFoundError on stashed tree), orchestrator re-ran them (7 passed); full suite 1673P/15F/1E = baseline 1666+7, zero new failures; idempotency proven by second live run. Worker flags for C52/C54: `POST /config`/`POST /toggle` hand-build per-field SQL (no shared write seam); `/api/autopilot/summary` is the ONLY config read route (nested `config` object). Schema+read only → ff-merged to main. **New baseline: 1673P/15F/1E.**
- **Also done:** C51 · P4.2-b candidate auto-launch loop (FIRST SHIPPABLE autopilot piece) — `autopilot_launch.py::auto_launch_best_candidate` as the queue-empty fallthrough inside `main.py::_auto_produce_queue` (the design `routes/queue.py`'s docstring already anticipated; same per-tenant cadence lane, so never queue-launch + candidate-action in one window). Dial-gated via C50's accessor: kill-switch-tripped → tenant skipped BEFORE scoring; propose_only (default) → scores via the EXISTING `get_candidates`/`calculate_confidence_with_breakdown` (first real consumer of `min_confidence_score` — orchestrator confirmed it was previously read nowhere), records ONE `autopilot_proposals` row (migration 108, live-applied + orchestrator-reconfirmed; proposed→accepted/dismissed/expired, evidence jsonb) — structurally cannot reach `launch_candidate` (name never bound in that branch; test monkeypatches it to raise, asserts zero calls); auto_draft/full_auto → EXISTING `launch_candidate` verbatim (full_auto=auto_draft until C55; BackgroundTasks constructed + fired via create_task since the route requires it positionally). Cadence GREATEST() includes proposals (once per window, not per 30-min tick). Commit 97c7d7a. VERIFIED: orchestrator read the full module + main.py diff + called-route signatures, re-confirmed the live table, re-ran the 14 new tests AND the full suite itself: 1687P/15F/1E = baseline 1673+14, zero new. Deploy-safe: every existing tenant is propose_only (zero spend), auto_draft requires an explicit dial write which has NO writer yet. ff-merged to main. **New baseline: 1687P/15F/1E.** ⚠ Worker finding folded into C54: kill switch does NOT yet gate the pre-existing queue drain. Also noted: MCP monetization ruling + CORRECTION (Stripe already exists — see decisions.md) recorded; C57 rescoped to wiring + MCP plan-gate audit.
- **Also done:** C52 · P4.2-c proposals surface — propose-only loop now user-visible end-to-end. Routes: `GET /api/autopilot/proposals`, accept/dismiss (shared functions = ONE definition of accept for HTTP + MCP; accept = kill-switch 409 check → `launch_candidate` FIRST → `mark_decided` only on success, so a failed launch never consumes the proposal — orchestrator read the code and verified ordering + atomic `WHERE status='proposed'` guard); notify = existing `bot_activity` feed row (best-effort) + additive `pending_proposals_count` on summary; MCP: `list/accept/dismiss_autopilot_proposal` (accept = free, reasoning documented in routes/mcp.py — same path as human Launch, paid stages keep downstream gates); frontend Proposals card on /autopilot (GlassCard idiom, React Query, states). Commit d39b49f. VERIFIED: orchestrator re-ran 27 new tests + FULL suite (1714P/15F/1E = 1687+27 zero new) + `npx tsc --noEmit` clean; worker's `npm run build` succeeded (env-var quirk pre-existing, proven by stash). Skew-safe both directions (new-frontend-vs-old-backend 404 renders ErrorCard). ff-merged to main. **New baseline: 1714P/15F/1E.** ⚠ C52 worker findings: pre-existing `launch_candidate` double-launch race → C53 audit item (fix = claims-lock house pattern); C48-C51 skipped SYSTEM_STATE.md entries (flagged there); Playwright impossible in sandbox → manual recipe at live-verification-queue §C52.
- **Also done:** C53 · P4.2-d auto-draft verification + double-launch race fix — AUDIT results: `budget_check` absent from the launch_candidate path but EQUALLY for humans (one shared path, no auto-worse-than-human asymmetry; flagged §C53, C54's weekly ceiling is the auto backstop); approval gates fire identically for auto-launched videos (same `run_next_step` loop) surfacing in existing UI; `check_plan_limits` was a GENUINE BYPASS on launch_candidate — a free-plan tenant could exceed video caps via autopilot/calendar launch — now wired + regression-locked as the 4th create entry point (partially pre-answers C57's MCP-bypass audit for this path). RACE FIX: migration 109 `competitor_videos.launch_claimed_at` (live, orchestrator-reconfirmed), atomic claim UPDATE → loser 409s before anything paid; failure clears claim (guarded so a completed launch is never clobbered); 10-min stale sweep. Commit 5c0b33c. VERIFIED: orchestrator read claim/release code, re-ran full suite 1720P/15F/1E = 1714+6 zero new. ff-merged to main. **New baseline: 1720P/15F/1E.** Note: worker ticked its own checklist entry this chunk (fine — accurate); orchestrator stamp appended.
- **Also done:** C54 · P4.2-e per-tenant weekly budget ceiling + kill-switch writers + closing the queue-drain gap — `autopilot_dial.py` gains the FIRST writers: `get_weekly_spend` (sums `generation_ledger.actual_cost`, NOT `videos.total_cost` — the latter has no "since when" axis; rolling window via an atomic `ON CONFLICT ... DO UPDATE ... WHERE` upsert), `check_weekly_budget` (NULL cap = always ok; `spent >= cap` = breach), `trip_kill_switch` (idempotent — never overwrites the first reason, notifies via `bot_activity` only on an actual trip), `clear_kill_switch` (the only clearer). GAP CLOSED: `main.py::_auto_produce_queue`'s per-tenant body extracted into `_produce_for_tenant` — reads the dial ONCE per tick, and a tripped switch OR budget breach now skips BOTH the queue drain (`routes.queue.auto_produce_next`, previously ungated) AND the candidate fallback. `autopilot_launch.py`'s auto_draft branch gets its OWN defense-in-depth budget re-check right before `launch_candidate` (scoring can go stale); propose_only structurally never reaches it (pinned by a test that makes the budget-check fake raise if called). Writers: `POST /api/autopilot/config` (dial_level/weekly_budget_cap, validated, `model_fields_set` distinguishes null-clears-cap from omitted); NEW `POST /api/autopilot/kill-switch/reset` (attributed via `AuthUser.email`); MCP `set_autopilot_dial`/`reset_autopilot_kill_switch` (both FREE — the kill-switch reset classification was a real judgment call, decided by the SAME precedent as `accept_autopilot_proposal`, documented in routes/mcp.py). Frontend: `/autopilot` gains an "Autonomy & Budget" card (3-option dial + budget cap input + "spent $Y of $X this week") and a prominent kill-switch banner with a Re-enable button. Commit (see git log — message starts `C54:`). VERIFIED: 29 new tests (`test_c54_weekly_budget_kill_switch.py`) + 4 changed/added in `test_c51_candidate_auto_launch.py`, non-vacuous via `git stash` (all fail restored/pass); full suite **1752P/15F/1E** = baseline 1720+32, zero new failures; `npx tsc --noEmit` clean; `npm run build` succeeds (needs `NEXT_PUBLIC_API_URL` set — pre-existing sandbox quirk, unrelated). No migration (C50's 107 already has every column). Deploy-safe: for every tenant that's never set a cap (100% today), `check_weekly_budget` always returns ok — provable no-op on the default path; the queue-drain fix can't fire for a tenant that's never been tripped (100% today). Live verification (real breach, live UI round-trip) deferred → live-verification-queue.md §C54. Backend leads frontend (additive/optional fields both directions) — ff-merge candidate.
- **Also done:** C54b · hardening fix from orchestrator review — closed the "raise dial_level to auto_draft/full_auto with NO weekly_budget_cap = unattended uncapped spending, reachable via the free `set_autopilot_dial` MCP tool" gap. New shared invariant `autopilot_dial.validate_dial_change` (the ONE place both writers call): computes the EFFECTIVE dial_level/cap a change would produce and rejects if elevated with no cap — covers raise-without-cap (reject), raise-with-cap-in-same-call (ok), clear-cap-while-elevated (reject), clear-cap-with-simultaneous-lower-to-propose_only (ok). `routes/autopilot.py::update_config` calls it directly (400 on violation); `routes/mcp.py::set_autopilot_dial` needed NO code change — it already dispatches through `update_config`, so the invariant applies transitively (confirmed by new tests hitting the REAL `update_config`, not mocked). Runtime belt-and-suspenders for any row that predates/escapes the writers: `autopilot_launch.py` computes an `effective_dial_level` (elevated+no-cap demotes to propose_only, logged, never a kill-switch trip — a config anomaly isn't a spend breach) and `main.py::_produce_for_tenant` logs the same condition (visibility only, no behavior branch — it doesn't itself gate on dial_level). `reset_autopilot_kill_switch`'s response now carries `previous_kill_switch_reason`/`previous_kill_switch_tripped_at` (the trip it just cleared) so an agent can't silently wave a trip away. Frontend: Auto-Draft/Full Auto dial buttons disabled with a gold hint until a cap is set; inline error surfaced if the call is rejected anyway. Commits: C54=21eae93, C54b=2b83266 (authorship-fixed rebase of the worker's 654111f/246b5c1 — same trees). VERIFIED: 17 new tests, non-vacuous via `git stash` on the 5 production files (all 15 hardening-specific assertions fail restored/pass; the 4 "allowed" shapes pass either way, correctly, since old code never rejected anything); full suite **1771P/15F/1E** = C54's 1752+19, zero new failures; tsc + build clean. Deploy-safe: for every tenant that's never raised the dial past propose_only through these doors (100% today, since no writer could set a cap before C54/C54b ship together), the runtime demotion is unreachable — only fires for a hand-edited DB row. ff-merge candidate, same batch as C54.
- **BUILD QUEUE COMPLETE (C01-C37, 2026-07-19).** C37 (Ryan's decision chunk) is COMPOSED — see the checklist's C37 entry: 3 decisions already answered+recorded this week (Power Doctrine retirement; legacy cron stays as reference impl; Phase 4 green-lit, DNA-first), 5 open items for Ryan (create-surface convergence, per-user BYOK, multi-shot sequences timing, orphaned /storyboards route, coordinated-deploy scheduling) — none block anything. Remaining work: (1) tasks/live-verification-queue.md — at-the-computer runbook, C25a coordinated deploy + MCP go-live at top; (2) hold branch `claude/c25a-media-auth-hold` awaits that deploy; (3) Phase 4 outline + roadmap ideas map — chunk when Ryan green-lights. Fresh sessions resume from THIS file + the playbook. **PHASE 4 · P4.1 COMPLETE (C40-C45, 2026-07-19)** (checklist Phase 4 queue; inventory in audit report §P4.1); C38 (chat-primary create convergence) + C39 (storyboards page delete) still queued from C37 answers, untouched by P4.1. Next: either C46 (quality-rules engine, awaiting Ryan's yes) or P4.2 (tenant-autopilot scouting) — the orchestrator decides.
- **Branch:** work + push on `claude/storyengine-build-orchestration-epkcr0` (this session's branch — the `tfdg8n`/`sgnm8l` names in older loop docs don't exist in this clone); ff-merge deploy-safe chunks to main. **C25a is an exception: hold it on the branch, do NOT ff-merge, until it can ship in the SAME `--with-frontend` deploy as its frontend half** (see the C25a entry above for why).

## Handoff — 2026-07-17 (Higgsfield teardown + full build plan COMPLETE → next session BUILDS)

**Mission:** StoryEngine becomes the main competitor to Higgsfield (higgsfield.ai).
Differentiation: open BYOK (user's own keys at true cost — Higgsfield's MCP/API locks billing
into their credits) + YouTube-native publishing with a performance feedback loop (Higgsfield
has NO social integrations — their agent makes clips; ours runs a channel). The copilot should
feel like Higgsfield's best trick: talk to it like a co-writing partner and it just makes what
you want — with our mapped shots.

### What this session produced (all on main, nothing pending)
This was a research + planning session. NO product code was changed. Five docs were produced,
all committed to main and cross-referenced:

1. `docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md` — the research.
   Higgsfield teardown (product / promotion / prompt-routing), 13-dimension comparison table,
   8 ranked recommendations. Claims labeled [verified] (survived adversarial checks) vs
   [reported]. Do NOT re-run research; do NOT trust Higgsfield price points beyond July 2026.
2. `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` — THE EVIDENCE. Full
   findings of the 4-agent StoryEngine sweep (copilot flow, model routing/BYOK, growth loop,
   styles/presets) with file:line references. Every checklist item traces to a finding here —
   consult it before re-exploring the codebase; do NOT re-run the audit.
3. `tasks/storyengine-wiring-fix-checklist.md` — THE WORK QUEUE. P0→P3, every item mapped
   to `[D]`ata / `[B]`ackend / `[U]`I layers with a `[V]`erify step. An item is not done until
   every listed layer ships AND Verify passes with evidence. P3.4 holds the audit findings
   that aren't part of the router build (quota guard, own-video VPH, per-user BYOK slice,
   Whisper-key friction, hardcoded Claude tiers, Power-Doctrine-branded SEO).
4. `tasks/storyengine-copilot-ux-map.md` — HOW USERS TOUCH EACH FEATURE. Per feature: the
   clickable door (exact controls/click paths) AND the conversational door (example
   utterances), plus the MCP server spec (§7) and the conversational quality bar.
5. `tasks/storyengine-knowledge-map.md` — THE ROUTER. Where to look by task, when to reuse
   vs re-verify knowledge, and the queue of 6 NOT-yet-run sweeps (security/tenancy, schema
   drift, queue reliability, render path, frontend state, multi-tenant branding) each with
   its just-in-time trigger tied to a checklist phase. Run pending sweeps as ONE Sonnet
   Explore agent each when their trigger fires; append results to the audit findings report.
6. `tasks/research-to-build-map.md` — NO INSIGHT WASTED. Traceability matrix: every research
   insight → disposition (BUILD-NOW w/ checklist ref, BUILD-LATER w/ backlog ref, GROWTH
   play G1-G5, PARKED w/ revisit trigger, or REJECTED w/ reason). Maintenance rule: new
   research gets rows here in the same commit, or it's a process bug.
7. CLAUDE.md + tasks/lessons.md — subagent model policy (see Session rules below).

### Build order (work the checklist top-down)
1. **P0 first — integrity bugs that lie to users today.** Cosmetic image-model dropdown
   (`scripts/coverage_to_app.py` hardcodes `generate_scene_image_gpt`, never reads
   `video.image_model_override`); 3 dead models in `MODEL_REGISTRY` (Kling 3.0 Pro, Runway
   Gen-4 Turbo, Hailuo 2.3); cost counter wrong (prices duplicated in `actions.py` +
   `lib/next-action.ts` + `MODEL_REGISTRY`, no actual-spend ledger, `videos.total_cost`
   never rolled up); home Producer hard-requires Anthropic key (`routes/chat.py` ~3176)
   breaking Kie-only tenants; research silently skipped in default autobuild
   (`actions.py` L401-421); docked co-pilot drops file attachments (`ChatCore.attachFiles`
   early-returns when docked ~L359).
2. **P1 — the copilot router.** Decision table as data (`GET /api/models` with best_for/tier/
   cost/wired) → per-scene routing (scene intent from existing `camera_selector.py` purpose
   tags → routed_model + routing_reason columns) → model badges with "why" + one-tap override
   in ScenesWorkspaceTab → draft-cheap/finalize-expensive verbs with itemized quotes.
3. **P2 — surface the buried machinery.** Style gallery from the 5 Python visual profiles
   (styles become DB rows; DELETE the duplicated 6-preset lists in `visual-presets.ts` and
   `producer_prompt.VISUAL_PRESETS`); camera-move chips from the 40+ catalog; script voice
   selection; **StoryEngine MCP server (P2.4)** — expose the `actions.py` verb registry to
   external agents, per-user tokens, BYOK pass-through, quote+confirm_token money gate.
4. **P3 — learning loops + stub cleanup.** Per-preset CTR/retention tracking (the moat);
   legacy stubs get wired or deleted, no third option (momentum/retention placeholders
   returning 50.0 in `confidence_scorer.py`; `learning_extractor` CTR TODO;
   `get_competitor_title_patterns()` returning "").

### Key architectural decisions (also in tasks/decisions.md — do not re-litigate)
- **Two doors, one registry:** every capability = clickable control + conversational path,
  both calling the same `actions.py` verb; MCP becomes the third door on the same registry.
- **Router routes by declared outcome, not model name;** always shows "why"; override always
  one tap away; per-scene not per-video.
- **Ledger is truth, estimates are hints:** actual per-generation spend recorded from API
  responses; single price source; Est → Actual shown in UI.
- **Styles are data, not code:** DB-backed preset catalog; Python profiles remain the runtime
  engine behind it.

### Session rules established (in CLAUDE.md, follow them)
- **Subagent model policy:** premium model (Fable/Opus tier) for main-loop orchestration/
  synthesis ONLY; ALL fan-out subagents get explicit `model: "sonnet"` (Agent calls and
  workflow `agent()` opts). This session burned ~4M premium tokens by not doing this.
- Docs-only commits were fast-forward merged to main with Ryan's explicit approval; code
  changes go through the normal branch flow — main must stay deployable (VPS auto-pulls
  hourly).

### Watch-outs for the builder
- The StoryEngine SaaS backend (`storyengine/backend`) is canonical; `skills/video-pipeline/`
  is the legacy Airtable side. When both implement a thing, fix the SaaS side; legacy stubs
  are wire-or-delete decisions, not silent parallel maintenance.
- Frontend/backend duplicated constants are the #1 drift source found (prices, presets,
  wired-model lists). Every fix should END with one source of truth + derived consumers.
- Money gate is sacred: no new path (router, MCP, finalize) may spend without a quote and
  explicit confirm — extend `_estimate_cost`/confirm cards, don't fork them.
- Per the checklist's Definition of Done: `[V]` evidence required, `npx tsc --noEmit` clean,
  SYSTEM_STATE.md updated for structural changes, checklist box ticked in the same commit
  as the fix.

**Opener for next session:** "Read the handoff in tasks/todo.md, then start at P0.1 of
tasks/storyengine-wiring-fix-checklist.md, building UX to tasks/storyengine-copilot-ux-map.md."

## Handoff - 2026-07-16 (Modal close wedge FIXED - on main, NOT pushed, NOT deployed)

The shared Modal (`ui/modal.tsx`) never unmounted after close: AnimatePresence held the exited
backdrop + card in the DOM forever (keyless fragment root; framer-motion 12.38 + React 19.2), so
an invisible `fixed inset-0 z-50` layer blocked every click after closing any dialog. Fixed at all
3 sites and verified like a user on local dev against the prod API (se devtoken ladder):

- `ui/modal.tsx` - backdrop and card are now two KEYED direct children of AnimatePresence (covers
  ModelVideoModal, pipeline Delete + New Video modals, discovery Manage Channels + Launch). Added
  `data-testid="modal-backdrop"` / `"modal-card"` for future smoke tests.
- `ReadinessCheck.tsx` + `FirstVideoFlow.tsx` - each rolled its own copy of the same broken shape;
  root is now ONE motion.div owning the only exit, backdrop is a plain div, card keeps its enter
  spring (no exit). `pipeline/page.tsx` mounts got explicit keys. data-testids added.
- Proof: pre-fix reproduced locally (React state closed, DOM stuck, backdrop intercepted a real
  click on "New Video"); post-fix all three dialogs open AND close clean via Escape, X button, and
  the readiness->create cascade; zero full-screen blockers left in DOM; `tsc --noEmit` clean.
- Deploy note: frontend-only change, needs `se deploy <session> --with-frontend` when Ryan ships it.
- `confirm.tsx` header comment updated (bug fixed); moving it back onto Modal is optional.
- ⚠ Same broken fragment shape still exists un-fixed in `components/detail-panel.tsx`,
  `components/storyboard/panel-detail.tsx`, `components/nav/bottom-tabs.tsx` (More menu) - same
  latent wedge, fix with the same pattern + a browser walk.

## Handoff — 2026-07-13 (DVsU Anton one-machine pipeline)

Current DVsU bomber proof state:

- `fc73860c-a9af-444f-95a5-7f86d60503e0` has a locked 23-machine roster.
- The old four-beat evidence-sentence preview shape is intentionally retired. It was fact-safe but visibly unlike Anton.
- Current StoryEngine machine research cards use Anton schema-v3 evidence slots: required `identity_origin`, `scale_specs`, `build_reality`, `service_reality`, `memorable_fact`; optional `engineering_intent`, `role_category`, `combat_reality`, `tradeoff_or_limit`, `human_detail`, `historical_meaning`, `transition_hook`, `onscreen_label`. The final sentence is paragraph-derived synthesis, not a researched meaning beat.
- Verified raw source packages now label each fetched excerpt with `SOURCE_TIER`; required Anton slots can use Tier 1-3 support, but Tier 4 caution/general sources cannot carry required evidence by themselves.
- Current StoryEngine machine script preview expects one 95-120 word paragraph plus `claim_map` spans. Validation checks exact span presence, required slot coverage, per-span/paragraph number support, unsupported designations, high-risk terms, sentence count, final-line length, and static DVsU paragraph rules.
- The deterministic extractive fallback is disabled. If the model cannot produce an Anton-quality claim-mapped paragraph after repair, the preview must fail for review instead of saving safe filler.
- Target-machine preview now filters the hydrated compact/legacy card set back to only the requested machine before building the story plan, so other roster cards are not loaded into the proof prompt.
- StoryEngine UI now exposes exact `evidence_segments` on each researched machine card and returns/showcases failed `machine-script-preview` audits instead of hiding them behind an HTTP error. This lets the operator inspect the source excerpt map before accepting or rerunning.
- Local no-spend proof passed with real fetched XB-15 sources from Boeing Images, National Museum of the USAF, and Pacific Wrecks: 99 words, no research-card errors, no validator warnings.
- VPS read-only check: backend service is active and running from checkout `e288cec8`; the DB still has the old saved XB-15 preview marked `passed=false`, `word_count=122`, with warnings for too many numbers, overlong final sentence, high-risk terms, and word count. This is good: the system is not treating the old preview as acceptable.
- New note/spec file: `storyengine/notes/dvsu-anton-single-machine-pipeline.md` maps Anton desktop materials, the first three Strategic Bomber paragraphs, the research slot contract, script JSON contract, and isolation rule.

Next safe action: after Ryan approves deploy + paid Anthropic preview rerun, deploy the local ahead commits, run only `/api/pipeline/machine-script-preview/{video_id}` for `Boeing XB-15` through the StoryEngine UI/API, and inspect the paragraph plus evidence map in-app. Do not run the full roster script until that preview passes Ryan's quality bar.

## Handoff — 2026-06-22 (chat-first creative producer)

Shipped the chat-first pivot: StoryEngine now opens to a ChatGPT-style producer
chat (at `/`) that turns one sentence into questions → selector cards → a
production plan → an approved video, then runs the pipeline. Full plan + status:
`storyengine/GOAL.md` (Phases 1-3 done; 4 = channel intelligence, 5 = follow-up
edits still to build).

- New: `backend/routes/chat.py` (intake + spec→create_video + pipeline kickoff),
  `backend/producer_prompt.py` (producer brain, direct Anthropic via tenant Vault
  key), `migration 060_chat_conversations`, `frontend/.../chat/ChatHome.tsx`.
- Changed: `status_map.py` (5 friendly states + SSE `friendly` field), sidebar
  (Chat / Dashboard / Advanced), login+onboarding land on chat.
- Deploy: this commit MERGED the prod working-tree snapshot (branch
  `vps-live-20260622`) with the chat work — zero conflicts. Migration 060
  auto-applies on backend restart. The chat producer needs each tenant to have a
  direct `anthropic_api_key` in their profile/Vault.
- TODO next: rotate the GitHub PAT in the VPS git remote URL (plaintext); build
  Phases 4-5; the deterministic panel-aspect backstop below still stands.

## ★ NEW SESSION BUILD PLAN — next-up work (queued, not started)

Forward work for a fresh session. Each = what + where. Priority order.
(DONE this session: research toggle → 14g; env style-lock + voice toggle → 14h;
structured image prompts → 14i; scene-vs-thumbnail style split → 14j; clip-pipeline
resilience (was #1) → 14k.)

1. **Deterministic panel-aspect backstop** (aspect feature enforcement — owed; task #10).
   The image model can return the wrong aspect even when asked; force each cropped
   panel to the chosen aspect in storyboard extraction/upscale. Needs a paid test
   to tune (pad vs crop). ⚠ CORRECTION from the verify run: clips are portrait
   because **Grok reshapes** them (the still panels were 16:9 already) — so the
   real aspect lever is the **Grok clip stage**, not the image stage. See
   [[storyengine-aspect-ratio]].

2. **voice_over / Remotion aspect support** (deferred from the aspect feature).
   aspect_ratio flows through grok_native (stitch) but NOT Remotion —
   `remotion-video/src/Root.tsx` + `renderConfig` hardcode 1920x1080, so portrait
   voice_over videos render letterboxed.

3. **Extend stage toggles to the rest of the pipeline** ✅ **DONE + DEPLOYED + VERIFIED
   IN PROD (2026-06-16, commit `ced64159`).** The original "add `skip_<stage>` columns"
   framing was SUPERSEDED: the general per-video `pipeline_stages` plan (commits
   `d11b63e2`/`b4de08f4`) already made every step toggleable at creation, reroutes the
   pipeline around turned-off steps at the `_update_video_status` chokepoint, and the
   per-video page already hides a turned-off step's tab (`tabVisible`/`TAB_STAGES` —
   so "pipeline-page reflection still owed" was already done). The only real remaining
   work was "harden each gate," which this commit did:
   - **Backend:** new `status_map` helpers `parse_stage_plan` + `stage_enabled_in_plan`,
     and a `_require_stage_enabled(video, stage)` guard wired into **12** manual
     trigger endpoints in `routes/pipeline.py` (research, voice, dialogue-voice, clip,
     sound-prompts, sound-effects, video-scripts, video-generation, generate-video-prompts,
     thumbnail, render, upload). A disabled step now returns a clear 400 instead of
     running the bot + burning Kie credits + persisting an artifact. Full-pipeline videos
     (plan NULL) are untouched. 8 new unit tests (21/21 pass).
   - **Frontend:** the shared Scenes tab (`ScenesWorkspaceTab.tsx`) showed for an
     images-only plan (Scenes = images OR video) but still exposed Animate controls →
     a `videoStageEnabled` flag now hides every animate/clip affordance (card hover
     "Animate", tap-to-animate, "Animate this scene", "Animate the rest", the clip
     counter, the ⋯ Clips/Speaking-voices/motion block, and the silent motion-prompt
     auto-run) when the `video` stage is off. Picture workspace stays. tsc + build clean.
   See [[storyengine-pipeline-stage-plan]]. Open follow-up: `split` (deterministic, free
   timing) is intentionally NOT gated — a no-voice/images-only video may still need scene
   timing for the visual timeline.

4. **Env style polish — small remainders.** Structured prompts (14i) fixed the gross
   drift (verified: 2D→3D and photoreal→3D both lock). Open: (a) `fence_line_rubbish`
   and other "bad-side"/grungy scenes still come back more 2D-outlined than 3D — re-roll
   confirmed it's systematic; add a "stay soft 3D CG even when grungy/bad-side" nudge to
   the env prompt. (b) The stronger lever if any drift remains is a VISUAL anchor: pass
   the character cast sheet to `_generate_environment` as `image_input` (the Kie field
   for refs) with "match the art style/medium only, keep the location empty" — needs a
   paid test (risk: it pulls a character in).
   Also: the per-panel builder hardcodes `_CHARACTER_PREFIX/_ENVIRONMENT_PREFIX =
   "Cinematic 2D animated illustration of"` (image_prompts/engine/prompt_builder.py
   :284,289) ignoring image_style_override — a latent 2D-vs-3D contradiction for any
   video that uses the per-panel path (clip videos use the storyboard-grid path, so
   it didn't bite here, but worth reconciling).

5. **Bidirectional script ↔ Google Drive sync** ✅ **DONE + VERIFIED IN PROD (2026-06-15,
   commit 94d732ec).** Spec: [`tasks/script-drive-sync-spec.md`](script-drive-sync-spec.md).
   Shipped Phase 1 (Push) + Phase 2 (Pull) + cheap part of Phase 3 (modifiedTime "Drive
   edited" badge). Build: migration 053 (`videos.drive_script_doc_id/_synced_at/
   _doc_modified_at`); `GoogleClient.replace_document_body/read_document_text/
   get_file_modified_time`; `POST .../script/push-to-drive`, `POST .../script/sync-from-drive`,
   `GET .../script/drive-status` (routes/videos.py); ScriptTab Drive card (Edit/Update in
   Drive, Open Doc, Sync, badge, conflict "Sync anyway"). Per-tenant client uses
   `GOOGLE_OAUTH_CLIENT_ID` (mints the tenant token) w/ `GOOGLE_CLIENT_ID` fallback. Scene
   map = `### SCENE n` markers; Pull fails loud (422) if missing; changed scenes clear
   voice/image/clip (mirror delete_clip). Verified live on the "SLOW ENGLISH" video:
   editable scene-delimited Doc in Drive, edit→Sync updated scene 12 + cleared its voice
   (snapshot+restored byte-identical). **Required Google Docs API enabled on OAuth project
   802685987716 — done 2026-06-15.** Backend deployed; frontend UI deploys with the next
   web build. Open follow-ups: (a) `drive_newer` reads true ~1-2s after a push (Drive
   modifiedTime settles post-batchUpdate) — cosmetic, self-heals; (b) Pull maps onto
   EXISTING scenes only (a Doc-added scene is skipped); (c) re-push at a stale doc_id (user
   trashed the Doc) → 502, could recreate on 404.

6. **Auto-detect text cards → "Fix all text cards"** (fast-follow to 14l; Ryan: "manual
   now, auto later"). The manual per-card "Fix text" (GPT Image 2) is DONE + verified.
   Now make it automatic: tag title/word-card beats at the image-prompt stage (add a
   `title_card` scene_type in `scene_expander.py`, or an `assets.is_text_card` flag) — the
   LLM already follows a "use a word/title card" rule (story_bible.py:267) so it knows when
   it's making one — then a "Fix all text cards" batch that runs GPT Image 2 on the flagged
   panels (reuse `run_fix_text_card`). Keep the GPT Image 2 prompt LEAN (long prompts → Kie
   500s; see 14l).

7. **De-Power-Doctrine the GLOBAL defaults** (multi-tenant correctness — owed). Ryan's own
   tenant is now fixed (see the 2026-06-16 Power-Doctrine-leak handoff), but the platform-wide
   defaults still hardcode the old geopolitics channel, so a FRESH signup inherits it:
   `storyengine/backend/prompt_defaults.py` SCRIPT/RESEARCH/THUMBNAIL personas literally say
   "Power Doctrine"/"Economy FastForward" + a 6-act geopolitical-exposé structure, and
   `skills/video-pipeline/title_patterns.json` (`power_doctrine_adaptations`, `master_formulas`
   — imported by autopilot/research/discovery-scanner/learnings) is the same channel's title
   science. Real fix = make the base templates niche-neutral + channel-driven. NOTE the in-app
   meta-prompt flow (`routes/system_prompts.py`) only rewrites VOICE and is told to keep ALL
   structure EXACTLY, so it does NOT solve this. Needs a product call on the universal default.

**Context for the older items below:** the 3 content-quality fixes (char descriptions,
environment locking, recap continuity) are DONE + verified end-to-end on a real
cloned video; see the handoff below. The verify also fixed 3 bugs live
(env-directive misfire, env-image proxy allowlist, harmful clone-research).

---

## ★ HANDOFF — 2026-06-16 (Engine/Identity split — Phases 1+2 BUILT + MERGED + DEPLOYED)

Executes [`tasks/engine-identity-split-plan.md`](engine-identity-split-plan.md) — turning StoryEngine into a
"cloneable system" where the universal ENGINE (craft) is separated from the swappable per-channel
IDENTITY (voice/look). See [[storyengine-cloneable-system-vision]]. Subagent-driven; each piece
reviewer-approved.

- **Phase 1 (Foundation):** `storyengine/backend/identity.py` (`IdentityContext` + builder, projects→
  channel_profiles→neutral precedence; frameworks parsed from JSONB string), `engine_templates.py`
  (neutral craft templates + `safe_fill` — fills only the 6 identity slots, leaves `{HEADLINE}`/`{{json}}`
  untouched), and `pipeline_executor.py` (`resolve_prompt`: per-video→tenant→neutral engine template,
  then safe_fill). Overrides still win → no change for customized tenants; keyless steps now get neutral
  craft instead of None/PD.
- **Phase 2 (Text engine):** `script` (engine template + neutralized `script_generator.py` append-blocks
  + dropped the PD quota lines from the user-prompt tail), the script **validator** (PD checks —
  number-density/framework-density/wallet-401k/position-yourself — now OPT-IN via `ScriptProfile`,
  default OFF; `power_doctrine_v2` re-enables; ESL/cooking scripts pass default, fail under PD gates),
  `research` (no more "Economy FastForward (Power Doctrine)" / 19-numbers / incentive-chain), and
  `video_motion` (dropped the "never show humans" rule + missile/bomber examples; kept verb-first/
  camera-discipline/banned-filler craft). PD originals preserved verbatim in
  `tasks/engine-identity-seeds/power-doctrine.md`. 24 backend + 154 script tests green.
- **Phase 2b (ScriptProfile — the REAL gate, found by the first live ESL proof):** the script
  generation loads a `ScriptProfile` (`shared/profiles/script/`) that was hardcoded
  `DEFAULT_PROFILE_ID = "power_doctrine_v2"` — UPSTREAM of the validator (it re-armed all the gates) AND
  of the brief validator (`validate_brief` in `brief_translator/validator.py`, an LLM judge with
  documentary criteria that REJECTED a simple ESL premise before any model call → `total_cost=0`). So
  the prior "validator default OFF" was true at the class level but moot at runtime. FIX (commit
  `64b0db67`): added `shared/profiles/script/neutral_v1.py` (all PD gates off, `requires_research_brief=
  False`, `min_words=150`, neutral structure), flipped `DEFAULT_PROFILE_ID="neutral_v1"`, and made the
  brief gate profile-aware (`BriefTranslator` skips `validate_brief` when `requires_research_brief=False`).
  `power_doctrine_v2`/`v1` stay loadable (SCRIPT_PROFILE env / explicit). 161 script tests green.
  NOTE: SCRIPT_PROFILE is NOT set in the prod backend env, so tenants now resolve to `neutral_v1`.
- **Phase 3 (Titles + Thumbnails) — DONE + MERGED + DEPLOYED (commits `4c1418dd`+`048fd887`+`84bff0c3`):**
  neutralized `title_patterns.json` (kept reader keys/schema + the title SCIENCE; stripped
  `power_doctrine_adaptations`/PROXY-WAR/NATO/Machiavelli verdict map), the `TITLE_GENERATION_PROMPT`/
  `TITLE_REFINEMENT_PROMPT` + the `infer_framework_from_research` 17-framework geopolitics classifier (now
  returns ''/neutral) in `research/agent.py`, and the thumbnail `VARIABLE_FILL_SYSTEM_PROMPT` (stripped
  Economy-FastForward + CHECKMATE/WEAPONIZED power-words + bear-trap/map metaphors). Promoted
  `engine_templates.py` `title`+`thumbnail` to real neutral craft; `prompt_defaults.THUMBNAIL_SYSTEM_PROMPT`
  → engine_templates. Reviewer-approved (craft preserved, JSON neutral at runtime, no PD fallback). 24+161+22 tests green.
- **Phase 4 (Images) — DONE + MERGED + DEPLOYED + PROVEN LIVE (commit `faa0e4c8`, 2026-06-17):**
  neutralized the visual engine. New `shared/profiles/visual/neutral_v1.py` (style-agnostic: empty medium
  prefix + technical-only suffix, `allow_human_figures=True`, NO national archetypes, neutral scene
  system-prompt with non-political examples, empty metaphor table). Flipped the visual default at all 7
  spots → `neutral_v1` (the real gate; backend never set `VISUAL_PROFILE` before, so this also fixed a
  latent "tenants can't switch styles" bug). `prompt_builder.py` constants neutralized; equipment-integrity
  now profile opt-in (ON for `cinematic_illustration`, OFF for neutral); an unknown/stale profile id resolves
  to neutral, NEVER holographic. `anthropic_client.py` holographic system/user prompt fires only for explicit
  `holographic_hud`; profile-None fallback now neutral. `storyboard/bot.py` `_KF_*` + keyframe footer
  neutralized. **QUICK store (Open Question 1, Ryan picked it):** the channel's free-text look is injected at
  build time via `VISUAL_STYLE_DESCRIPTION` (per-video `image_style_override` wins, else
  `IdentityContext.visual_style`/channel `style_description`); backend exports it on every image stage
  (`_load_idea` per-run reset + `_export_visual_style` on run_prompts/run_images/storyboard). `cinematic_
  illustration`/`holographic_hud`/`clay_mannequin` stay loadable opt-in presets. Reviewer-approved (2 delivery
  bugs found + fixed). PROVEN: deployed code on prod, fed Ryan's "Slow English" ESL identity, emits image
  prompts in the channel look with ZERO Power Doctrine across all 5 scene types.
- **Still tracked (separate later tasks):** `_generate_cinematic_direction` (PD act-structure
  ORDINARY-PERSON/OPERATOR/ARCHITECT/PROPHET) in `research/agent.py`; `title_idea/curiosity_gap/
  gap_title_engine.py` (`MF_FORMULAS` CHOKE POINT / "Weaponized [Geography]"); the PRE-EXISTING
  `title_patterns.json` loader path bug (a fix is staged uncommitted in `discovery/scanner.py` +
  `research/agent.py` — `Path.resolve().parent.parent`); and a cleanup of 18 pre-existing stale
  *holographic-era* unit tests in `image_prompts/engine/tests/` (red on `origin/main` before Phase 4).
- **Next:** Phase 5 (clone seeds the voice + creator-direction layer).

---

## ★ HANDOFF — 2026-06-16 ("Power Doctrine" leak in title/idea generation — FIXED + DEPLOYED + VERIFIED IN PROD)

Ryan: "when I generate an example title it still uploads my old Power Doctrine channel —
it's locked in." ROOT CAUSE was THREE stacked things (NOT a stale cache):

1. **DATA** — his authoritative `projects` row was still `name="Power Doctrine",
   niche="Tech"` (channel_profiles said TOPAI/technology, but the idea engine now prefers
   `projects` per commits `6ba6896a`/`1978a894`). So every generator was told the channel IS
   Power Doctrine. → Renamed `projects` + `channel_profiles` to `name="Slow English",
   niche="Beginner English learning (ESL)"` (Ryan's call — it's a throwaway example channel,
   editable live in Profile; the name is FREE TEXT, not pulled from a YouTube connection).

2. **CODE** — `routes/discovery.py _build_discovery_prompt` hardcoded a geopolitics "Master
   Formula" voice (PROXY WAR/NATO/PBOC examples, Machiavellian frameworks, "How [Country]
   Secretly…", neg-framing-+63%, 55-char ceiling). Even pointed at ESL competitors it reframed
   kids' English videos into "How SWIFT Sanctions Broke Russia's War Machine". → Genericized:
   the title rules, `framework` field, and JSON example are now niche-neutral + driven by
   `{ch_niche}` and the competitor titles, with an explicit "NEVER reframe into
   politics/geopolitics unless that IS the niche" guard. Commit `2fd1f6d1`, deployed (backend
   restart only — backend-only change). py_compile clean.

3. **LATENT** — `tenant_prompt_defaults` was EMPTY for his tenant, so a real video render would
   fall back to the hardcoded Power Doctrine script/research/thumbnail personas in
   `prompt_defaults.py`. → Seeded his tenant with ESL starter prompts for `script`/`research`/
   `thumbnail` (the resolver is PER-KEY; `video_motion`/`sound_*` stay on the neutral defaults).

**VERIFIED end-to-end on prod:** cleared his 20 stale geopolitical ideas, `POST
/api/discovery/refresh` → 5 fresh ideas, ALL clean ESL ("Are You a Good Guest or a Bad Guest?
| Slow English (A1-A2)", "They Laughed at the Quiet Girl… Then This Happened", thumbs
"GOOD vs BAD"/"SO JEALOUS!"). Zero geopolitics. Frameworks now "good vs bad contrast story",
not "Hegemonic Transition Theory".

**GitHub hygiene:** repo was already even with `origin/main` (nothing unpushed). Gitignored
`*.tsbuildinfo` (untracked the churning frontend cache) + auto-gen `docs/product-brain.md`;
committed the hand-written `docs/storyengine-creator-flow-ux-map.md`.

⚠ **STILL OPEN (systemic — see build-plan item 7):** the GLOBAL defaults are still Power
Doctrine. `prompt_defaults.py` templates + `skills/video-pipeline/title_patterns.json` hardcode
the old geopolitical channel, so a FRESH tenant inherits it until the base templates are made
niche-neutral. Ryan's tenant is clean; the platform default is not.

**Deploy gotcha learned:** `kill -9 $(pgrep -f "uvicorn main:app")` self-matches when run from
an SSH command whose argv contains that literal string — it kills its own shell. The uvicorn
procs still died + systemd revived them (confirmed: old PIDs gone, fresh proc serving new code),
but for a clean restart run the kill from a script FILE on the VPS (its argv is `bash file.sh`),
or use a `[u]vicorn`-style bracket pattern, to avoid the self-match.

---

## ★ HANDOFF — 2026-06-16 (New Video = idea/title generator + free channel mgmt + "Generate from my channels" UNBLOCKED end-to-end — ALL DEPLOYED)

New feature area (the CREATE/idea surface, not the render pipeline). 8 commits on `main`,
all deployed to prod (storyengine.dev). North star unchanged: the title (next to the
thumbnail) decides a video's success, so the create flow should *generate* metric-backed
ideas, not force the creator to type a topic.

**Commits (oldest→newest):** `e0b4fdd3` `c5da2f66` `eb9c62db` `f369a4f6` `d38c64d1`
`f4ec72bc` `49ed96ad` `340be6f0`.

**(1) New Video modal is now a title/idea generator (frontend).** `app/pipeline/page.tsx`
(the returning-creator "New Video" modal). Topic field is OPTIONAL (no more red `*`; Create
still needs a title, typed OR picked). Under it:
- **"Ideas from your example channels"** — pre-loads `getDiscoveryIdeas("fresh")` on modal
  open; each row = best title option + score + the competitor it's modeled on + its VPH.
  Pick → fills title + carries the idea's `our_angle` into writer guidance. Empty states:
  mining spinner, "Generate from my channels" (triggers `refreshDiscoveryIdeas`), and now
  surfaces `discoveryStatus.error` (e.g. "add a key") instead of failing silently (`c5da2f66`).
- **"Suggest titles for this"** — appears when a topic is typed; calls `suggestTitles(topic)`.
- `suggestTitles` in `lib/api.ts` now NORMALIZES the response (backend can return bare
  strings) → `{title, thumbnail_text, score}`; this also un-broke FirstVideoFlow/CreateVideoStep
  which were rendering `s.title` on raw strings (blank rows).

**(2) Free example-channel management + Profile IA.** New shared component
`components/channels/ExampleChannels.tsx` (add-by-URL / delete / re-sync), used BOTH on the
Profile page and inline in the New Video modal ("Manage channels" toggle / no-channels state).
Nav relabels (routes unchanged): **"Settings" → "Profile"** (`/settings`, H1 too) with an
**Example channels** section at the top; **"Visual Profile" → "Visual Styles"** (`/profile`)
to kill the name clash (`sidebar.tsx`, `bottom-tabs.tsx`). Channel CRUD is now FREE — the
`/api/niche/*` endpoints were never backend-gated; the heavy `/competitors` analytics page
stays Pro (`PRO_PATHS` in `AuthenticatedShell.tsx`). See [[storyengine-channels-profile-ia]].

**(3) LLM provider router for titles/ideas (backend).** `suggest_titles` (`routes/videos.py`)
and discovery (`routes/discovery.py`) now call `kie_unified.get_text_client_for_tenant(tenant)`
— tenant's own Anthropic key → `AnthropicDirectClient`, else their `kie_ai_api_key` →
`KieClaudeClient` (kie.ai is the "one key for everything", same path scripts/onboarding use),
else a clear "add a key" 400. Both use `await client.generate(prompt, model=, max_tokens=)`.
Model = **Sonnet 4.6** for titles/ideas (Ryan's call after a side-by-side: tiny outputs, the
cost delta vs Haiku is pennies, Sonnet's hooks are sharper). **`kie_unified.py` is now committed**
(was VPS-only though onboarding already imported it — committing it un-broke fresh clones).
kie model facts (live-probed): `claude-haiku-4-5` works (~10s, cheap), `claude-sonnet-4-6`
works (~35s), `claude-3-5-haiku-*` 422 on kie. The `CLAUDE_MODEL_ALIASES` fix (`d38c64d1`)
stops Haiku being silently upgraded to Sonnet — keep Haiku for bulk/script work later.
See [[storyengine-tenant-api-keys]].

**(4) "Generate from my channels" UNBLOCKED — the big one.** It was returning 0 ideas. Root
cause was NOT in this feature: **YouTube bot-blocks the VPS datacenter IP**, so the yt-dlp
per-video scrape got 0 views / no dates → VPH 0 → discovery's `VPH >= 50` filter rejected
everything. Fixed two ways:
  a. **Competitor scraping switched to the official YouTube Data API** (`49ed96ad`). New
     `backend/youtube_data_api.py` (`fetch_channel_videos`); `_run_scrape` (`routes/niche.py`)
     uses it when `YOUTUBE_API_KEY` is set (lazy import, falls back to yt-dlp otherwise),
     skipping the bot-blocked per-video call. ~3 quota units/channel; one server key reads
     PUBLIC data for all tenants (competitor data is public — no per-user OAuth, and quota is
     per-PROJECT not per-user so OAuth wouldn't help anyway). KEY: created in GCP project
     **storyengineagent** ("Competitor Scrape (StoryEngine)", restricted to YouTube Data API
     v3), lives as `YOUTUBE_API_KEY` in `storyengine/.env` on the VPS (gitignored).
  b. **Fixed a latent `UnboundLocalError: json`** (`340be6f0`) in `_run_discovery_generation`
     — a redundant `import json` inside an `if distilled_summary` branch made `json` local to
     the whole function, so `json.dumps()` at the insert threw and EVERY generated idea was
     silently dropped. Was masked until the scrape finally produced eligible videos.
  **VERIFIED end-to-end on prod:** re-scraping Ryan's "Slow English" example channel via the
  API revealed its videos actually have 80k–400k views / VPH 174–1795 (the "0 views" was
  ENTIRELY the bot-block) → discovery generated + saved **5 idea cards** (real competitor
  matches, appeal 7–9, 3 scored titles each). The engine takes the competitor's winning
  FORMAT ("Good vs Bad" comparison) and reframes it into the channel's niche (AI/tech/geopol
  from `channel_profiles`). See [[storyengine-youtube-scrape-botblock]].

**Gotchas for next session:**
- Ryan's tenant `ee93e6d1-…` has a **kie.ai key, NO Anthropic key**; plan=`null` (free tier)
  → generation runs via kie.ai/Sonnet.
- **Local dev preview can't reach authed pages** (login gate); verify with `tsc --noEmit` +
  `next build`, not the browser. See [[storyengine-local-preview-auth]].
- **Standalone VPS debug scripts** must load `storyengine/.env` first (for `DATABASE_URL`) or
  `vault.get_secret` silently returns None. Pattern used all session: read `../.env`, then
  `from vault import get_secret, fetch_all`.
- Deploy unchanged: push `main` → on VPS `git pull --ff-only` → restart. Backend SIGTERM
  STALLS (SSE drains) → escalate to `kill -9 MainPID`; systemd `Restart=always` revives. The
  frontend stops cleanly. `127.0.0.1:8001` works on the VPS (NOT `localhost` → that's IPv6
  `::1`; uvicorn binds IPv4 `0.0.0.0`).

**Open / next feature set (queued):**
1. **Add real popular channels in Ryan's niche** (operational, not code). His only example
   channel is the test "Slow English" one — it works (it has real views), but ideas come out
   reframed into the channel-profile niche. For on-target ideas, add the competitors he
   actually models. `fetch_channel_videos` handles channel-id, `@handle`, `/user/`, and falls
   back to `search.list` (100 quota units) for `/c/` custom URLs.
2. **Route SCRIPT writing through the same resolver** + a cheaper model. Scripts/onboarding
   currently use the env/default Sonnet path; `get_text_client_for_tenant` + Haiku-for-bulk
   would cut cost and unify on "one key". This is where Haiku's savings actually matter (long
   outputs), unlike titles.
3. **Discovery thresholds may be too strict** — `VPH >= 50` AND `hours_old <= 720` (30d). An
   infrequently-posting (but good) channel can yield 0 eligible videos. Consider relaxing the
   recency window or adding a raw-views fallback when velocity is unavailable. (Ryan was
   offered "rank by raw views" earlier and chose to fix the scraper first — revisit if real
   channels still come up empty.)
4. **Cheaper/faster kie model for titles at scale** — currently Sonnet (~13–35s via kie). If
   the inline "Suggest titles" latency annoys, `claude-haiku-4-5` is ~10s and ~3× cheaper
   (one-line model swap in `routes/videos.py`).
5. **Cosmetic:** a stale orphan `competitor_videos` row (a Rick Astley video, vph 0, no date)
   survives re-scrapes because it's not in the channel's current uploads — harmless, filtered
   out by discovery; delete if tidying.
6. **yt-dlp transcripts still bot-blocked** — only matters if/when transcript-level "content
   DNA" distillation is wanted (the idea engine doesn't need it). Same cookies/proxy fix as
   documented, OR an Apify/transcript-API path — separate, lower priority.

---

## ★ HANDOFF — 2026-06-14m (portrait/reference retry — one flake can't block approve — DONE + DEPLOYED)

The verify-run bug: `design_characters` / `design_environments` generated each portrait/
reference ONCE; on any failure (Kie hiccup, SSL, vision refusal) they dropped it silently,
leaving an empty card that BLOCKED approve ("Maria has no image yet"). Fixed: each item now
retries 3× with backoff before giving up (`routes/characters.py` ~286, `routes/environments.py`
~253). Persistent failures still surface via the per-card Regenerate + the clear approve error.
Happy path unchanged (succeeds first try). Commit `35729cec`, deployed. ⚠ Not paid-tested
(would need to force a transient failure mid-design) — low-risk retry wrapper, py_compile clean.

---

## ★ HANDOFF — 2026-06-14l (Part 2: "Fix text" via GPT Image 2 — DONE + DEPLOYED + verified)

Legible title/word cards. Ryan chose MANUAL-first. A per-card **"Fix text"** hover button
(Type icon) on each picture redraws just that card via GPT Image 2 (`gpt-image-2-image-to-
image` through Kie, the same model the thumbnails use). Scenes stay on nano-banana.
Commits `22a22383` + `7f14e7df`, deployed.
- `pipeline_executor.run_fix_text_card(video_id, asset_id)`: loads the panel, redraws via
  `generate_thumbnail_gpt2` (current panel = art-style/layout ref + a LEAN prompt for the
  wording), persists to Drive, replaces `assets.image_url` in place, clears the stale clip.
- `POST /api/videos/{video_id}/assets/{asset_id}/fix-text` (mirrors recrop) + frontend
  button + `fixTextAsset` api.
- VERIFIED on a bird panel (then restored exactly — bird untouched): GPT Image 2 rendered
  perfectly legible, correctly-spelled text ("How can I help you today?" + a clean speech
  bubble) in the 3D Pixar style. ⚠ LEARNING: a long/noisy prompt → Kie returns
  `failCode 500 "Internal Error"` (0 credits charged); the LEAN prompt (cap style+wording
  to ~280 chars each) succeeds. Keep fix-text/GPT-Image-2 prompts short.
- Bonus finding: GPT Image 2 nails clean SPEECH BUBBLES on scene panels too — a possible
  future lever for ESL caption/dialogue frames, not just title cards.

NEXT (Ryan's fast-follow): **auto-detect text cards** — tag title/word-card beats at the
image-prompt stage (a `title_card` scene_type or `assets.is_text_card`) and add a "Fix all
text cards" batch, so it's not purely manual. (Queue item below.)

---

## ★ HANDOFF — 2026-06-14k (clip-pipeline resilience — queue #1 — DONE + DEPLOYED)

The "Animate the rest" fragilities (no resume on restart, one error kills the batch,
stuck clips hog slots). Commit `99112390`, deployed (backend restart + frontend rebuild).
Key insight: the backend is ALREADY additive + durable (each clip writes
`assets.video_clip_url` immediately; a re-run only does the missing ones) — so resume =
re-trigger, no checkpoint table needed.
- **Frontend auto-resume** (`ScenesWorkspaceTab.tsx`): "Animate the rest" loops the
  additive backend until nothing's left — surviving restarts/transients with no re-click,
  no double-charge. Guards: 25-round cap, halt after 2 no-progress rounds, Stop cancels.
- **Per-clip isolation** (`pipeline_executor._safe_one`): a raised error (SSL/Drive/DB/
  timeout) is counted, never aborts the batch.
- **Per-clip deadline** (`_gen`=`asyncio.wait_for 420s`): stuck Grok job frees its slot
  in ~7 min, retried next round.
Verified FREE: py_compile + tsc clean, deployed healthy. ⚠ Full restart-mid-run / forced-
failure proof needs a real paid clip run — safe to do on the next "Animate the rest"
(additive + guarded). See [[storyengine-clip-pipeline-fragilities]].

---

## ★ HANDOFF — 2026-06-14j (scene style from frames, thumbnail style from thumbnail — DONE + DEPLOYED + verified)

Ryan's correction to 14i: the VIDEO's scene style must be read from a real **video
frame**, not the thumbnail (a YouTube thumbnail is a punched-up click asset — split-
screen collages, bold text — a bad proxy for the scenes). Thumbnail style stays
read from the thumbnail. Commit `f06bd437`, deployed.

`model_video.py:_generate_modeled_pack` now runs TWO vision passes:
- **SCENE** ← `_describe_scene_style` over 3 real mid-video frames (`i.ytimg.com/vi/
  <id>/hq1..3.jpg` — same CDN as thumbnails, so it bypasses the yt-dlp bot-check) →
  `image_dna` / `visual_style_brief` / every scene image_prompt.
- **THUMBNAIL** ← `_describe_thumbnail_style` → `thumbnail_dna` / `thumbnail_prompt` only.
The pack prompt labels both and routes each to the right fields; scene-style failure
is a loud blocker (falls back to thumbnail at worst), never silent.

VERIFIED: cloned ref `cfIHXpqOLxw` into a throwaway → scene style = "Pixar 3D, golden-
hour, supermarket interiors", thumbnail style = "split-screen, bold outlined text" —
correctly different. Bonus: yt-dlp was bot-blocked on the server yet scene style still
classified (CDN frames bypass it). Throwaway deleted. See [[storyengine-style-classifier-bulletproof]].

⚠ Minor pre-existing cosmetic: the oembed-fallback blocker still says "modeled from
the title, channel, and thumbnail only" even though scene FRAMES are now used too —
harmless, low priority.

---

## ★ HANDOFF — 2026-06-14i (structured prompts + bulletproof style classifier — DONE + DEPLOYED)

**(1) Structured image prompts — DONE (commit `226a5f0f`, deployed + image-verified).**
Replaced the prose char/env prompts (where the style clause got buried → drift) with
a structured JSON spec whose FIRST slots are `art_style` + `render_medium`, IDENTICAL
in both `routes/characters.py:_generate_portrait` and `routes/environments.py:
_generate_environment` → cast and locations lock to one medium. The GPT Image 2 skill's
#1 lesson, on nano-banana-2. VERIFIED by regenerating `13c334b5`'s drifted envs and
eyeballing the PNGs: maple_street (flat-2D→3D Pixar), toms_living_room (photoreal→3D
Pixar), garden_lawn (2D→3D Pixar) all clean. ⚠ `fence_line_rubbish` (a "bad-side" scene)
came back improved but more 2D-illustrated/outlined than the others — the style_dna's
"bold outlines" + bad-side grunge pulls the medium flatter. Open: re-roll it, or add a
"stay 3D CG even when grungy/bad-side" nudge. front_doorstep_morning was already fine;
classroom_title_card is a TEXT card → leave for Part 2 (GPT Image 2 routing).

**(2) Clone style-classifier bulletproofed — DONE (commit `ce4443bb`, deployed).** Ryan's
requirement: a shared-link clone must always classify the source's TRUE style (incl.
realistic/live-action), never silently default to animated — that's what lets us
reproduce ANY style. `model_video.py`: the thumbnail vision pass (`_describe_thumbnail_style`)
now retries 3×; a failed classification appends a creator-facing **blocker** (was silent
text-guess fallback); the observation prompt forces an explicit `MEDIUM:` label and forbids
defaulting to animated; the pack example is de-biased. See [[storyengine-style-classifier-bulletproof]].

**Still open from this thread:** Part 2 = route TEXT frames (title/word cards, signs) to
GPT Image 2 via Kie (`gpt-image-2-image-to-image`, already wired for thumbnails) for legible
lettering — Ryan approved direction; needs text-frame detection (cleanest: tag title-card
beats in the story bible). And the structured-prompt pattern could extend to the per-panel
builder's hardcoded `_CHARACTER_PREFIX/_ENVIRONMENT_PREFIX` (queue item 6).

---

## ★ HANDOFF — 2026-06-14h (env style-lock + voice toggle — DONE + DEPLOYED + verified)

Two asks from Ryan while reviewing the "Living in a House" video (`13c334b5`).

**(1) Env style not locking — FIXED (commit `0a5aa384`, deployed).** The env
reference images drifted across flat-2D and photorealistic even though this video's
`image_style_override` explicitly forbids both ("3D Pixar-style… No photorealism…
no flat 2D vector illustration"). Root cause: `routes/environments.py
_generate_environment` appended the style as a TRAILING "Visual style: …" clause;
an empty establishing shot is style-ambiguous so the model ignored it (characters
survive the same shape because "3D Pixar character" is unambiguous). Fix: lead with
the art style, tie it to the character art's medium, add an explicit "don't switch
medium — no photorealism, no flat 2D" lock (mirrors the storyboard grid's STYLE
LOCK). Prompt-only → affects NEW/REGENERATED env refs. **Ryan: Redo the drifted
env cards (maple_street_exterior, shared_driveway, garden_lawn) to pick it up.** If
it still drifts, see queue item 6 (visual anchor — needs a paid test).

**(2) AI voice-over now optional — DONE (commit `0a5aa384`, deployed + live-verified).**
First creation-time STAGE toggle (Ryan chose creation-time over live per-stage).
grok_native (clip) videos carry their own baked-in audio, so render_stitch ignores
`voice_over_url` — narration was generated-but-unused for them. Now skippable:
- migration `052` `videos.skip_voice` (applied to prod) + `CreateVideoRequest.skip_voice`
  + persisted in `create_video`.
- `pipeline_executor._skip_disabled_next(video, natural_next)` — a finished script
  advances past `ready_for_voice` straight to `ready_for_image_prompts` when
  skip_voice (both script paths routed through it); both voice gates (image-prompts
  @~1699, image-gen @~2384) are satisfied without narration. Generalizes to other
  stages (queue item 5).
- Frontend "Add AI voice-over?" toggle on BOTH create surfaces (onboarding +
  dashboard modal). Default ON → unchanged behavior.
- Live-verified on prod: skip_voice=true persists; skip_voice→idea_logged,
  skip_research+skip_voice→ready_for_scripting (test rows soft-deleted). Pre-checks:
  py_compile + tsc clean. ⚠ Safe for CLIP videos; a documentary/Ken-Burns video with
  skip_voice would render silent (its narration IS the audio) — UI copy frames it as
  "No narration · Clips' own audio".

---

## ★ HANDOFF — 2026-06-14g (research toggle for typed topics — DONE, not yet deployed)

Build-plan item #1 (Ryan's ask). For typed-topic videos, research is now OPTIONAL
at creation — a "Research this topic first?" choice. Default = research ON (status
`idea_logged`, unchanged). Skip → video lands straight at `ready_for_scripting`,
same as clones; the standard script bot writes from title + writer_guidance +
framework_angle (verified: `skills/video-pipeline/script/run.py:100-121` already
builds a full brief when `research_payload` is empty — "not set — legacy idea").

Touched (byte-identical default behavior — `skip_research` defaults False everywhere):
- `backend/models.py` — `CreateVideoRequest.skip_research: bool = False`.
- `backend/routes/videos.py:create_video` — `initial_status = ready_for_scripting if
  skip_research else idea_logged`; INSERT renumbered to bind status as a param.
- `frontend/src/lib/api.ts` — `createVideo({ …, skip_research? })`.
- `frontend/src/components/onboarding/CreateVideoStep.tsx` — "Research this topic
  first?" two-button picker (mirrors the aspect picker), `needsResearch` state,
  sends `skip_research: !needsResearch`.
- `frontend/src/app/pipeline/page.tsx` — SAME toggle in the dashboard "New Video"
  modal's Advanced options (the repeat-creator flow — onboarding runs once). NOTE:
  this modal still lacks the aspect picker (aspect only shipped in onboarding) — a
  small consistency gap if anyone wants to close it.

DEPLOYED + LIVE-VERIFIED (2026-06-14, commit `2aa68514` on prod). Backend
restarted + frontend rebuilt/restarted; public edge 200. Live end-to-end test
against prod: `POST /api/videos {skip_research:true}` → `ready_for_scripting`;
default → `idea_logged` (test rows soft-deleted). Pre-checks: `py_compile`
(backend) + `tsc --noEmit` clean. Note: the deploy restart also cleared a stale
in-memory "running" task flag that had video `13c334b5` ("Living in a House")
jammed at `ready_for_storyboard_extraction` (storyboard-image batch died ~1.5h
prior without clearing it — the no-resume fragility in [[storyengine-clip-pipeline-fragilities]]);
it's unblocked now.

---

## ★ HANDOFF — 2026-06-14f (content-quality: ALL 3 FIXES DONE; paid verify next)

**Fix #3 — forward-continuity + recap — DONE (commit `dcf46f9d`, deployed + restarted).**
The image-plan/description prompts had "find the primary verb, show that action" with no
story-state notion, so vocab-recap narration ("Word six: Bandage…") got literally re-staged
(bird re-bandaged after release). Added two rules at BOTH prompt stages
(`script/story_bible.py` scene_blocks plan + `script/brief_translator/scene_expander.py`
description writer): FORWARD CONTINUITY (no re-staging a resolved state) + RECAP/OUTRO/CTA
narration → word cards / character-to-viewer / resolved-callback, never re-enact the problem.
Prompt-only; affects NEW videos.

**All 3 content-quality fixes are DONE + deployed.** Ryan approved a PAID end-to-end verify
(a NEW small test video, NOT the bird) to confirm: Fix #1 (real char descriptions), Fix #2
(2-ref env conditioning holds the room without softening faces), Fix #3 (recap shows word
cards, not re-staging). Recommended bounded test = run a new video THROUGH STORYBOARD GRIDS
only (~$1–3), inspect the grids, before any clip spend (~$7+).

---

## ★ HANDOFF — 2026-06-14e (content-quality: Fix #1 + Fix #2 DONE; Fix #3 next)

**Fix #2 — ENVIRONMENT LOCKING — DONE (commit `f1d0490b`, deployed: migration 051
applied to prod, backend restarted + booted with the new router, frontend rebuilt).**
Scenes drifted because environments were only text labels with no locked image. Now
mirrors character locking:
- `video_environments` table (per `story_bible.locations[]`) + `videos.environments_approved_at`
  gate + `assets.location_id` (structured per-panel location). Migration `051`.
- `routes/environments.py` (clone of characters.py) + a new **Environments tab** (between
  Characters and Scenes) design/approve a reference image per location (nano-banana-2,
  16:9, "no people" establishing shot, ~$0.025 each, 2–4/video).
- **Keystone:** `image_prompts/run.py` now persists `block_location_id` onto each asset
  (`assets.location_id`, via `supabase_adapter`); `_row_to_image` surfaces it. THIS is the
  reliable beat→location key (the bible's scene_blocks/location_ids don't map cleanly to
  the final beats — they're a planning layer).
- **Conditioning:** each storyboard grid resolves its dominant `location_id` from its
  panels and passes ONE location ref alongside the cast sheet (exactly 2 refs — ≥3 dilutes
  the character lock). `bot._resolve_env_ref_for_images` + the `generate_contact_sheet`
  "last image is the location" directive. **Opt-in** — no approved environments = byte-
  identical to before.
- Verified FREE: migration live, backend boots + `/environments` route 200, the env-ref
  resolver unit-tested (dominant/opt-out/unmapped/empty), frontend compiles + serves.
- ⚠ **STILL NEEDS ONE PAID NEW TEST VIDEO** to validate conditioning QUALITY (do 2 refs hold
  the room without softening faces?). If faces soften, the fallback is prompt-only env (drop
  the env image — one-line revert in `bot.py`). Do NOT regen the bird.

**Fix #3 — recap/continuity beats — NOT started (task #13).** Scene-8 vocab recap re-stages
resolved plot (Tom re-bandaging the bird after release). Smaller, free, self-contained.

(Fix #1 — character-description refusal bug — DONE, see below.)

---

## ★ HANDOFF — 2026-06-14d (content-quality tightening; Fix #1 of 3 DONE)

Ryan watched the rendered bird video (B−) and flagged 3 issues to tighten before
launch. Diagnosis is grounded (read the script, the storyboard prompts, AND the
images). Working ONE AT A TIME, review each before spend.

**Fix #1 — character-description refusal bug — DONE (commit `d7a67c1c`, live).**
Every `video_characters.description` was an AI refusal ("I'm unable to access or
view files…"). The character-design **vision pass** (`routes/characters.py` ~557,
`vision_call`) hit Kie's Claude gateway silently dropping the image; `_try_kie_claude`
has no ingestion guard, so the refusal was saved as the description → no facial text
anchor. Cascade: storyboard-prompt gen then **invented** outfits ("Tom: red t-shirt"
when the real reference is a **light-blue** fox tee) → fought the reference → drift.
Fix: centralized refusal detector in `skills/video-pipeline/shared/clients/vision_client.py`
(`_looks_like_refusal`) — refusal replies now treated as provider failures. Regenerated
all 6 bird descriptions from the real portraits (accurate now). ⚠ Does NOT retroactively
fix the bird's already-generated panels — visible gain needs panel+prompt REGENERATION.

**Fix #2 — environment reference images (task #12, NOT started).** Environments are
text labels only (`SUNNY_GARDEN`, `VET_EXAMINATION_ROOM`) — no locked image, re-invented
each panel. Ryan's idea: generate one ref image per environment, condition panel gen on it.

**Fix #3 — recap/continuity beats (task #13, NOT started).** Script is correct; the
scene-8 vocabulary recap (panels 10–21) re-illustrates words literally — "bandage" =
Tom re-wrapping the bird AFTER it flew free. Recap/outro beats must not re-stage resolved
plot (word cards / kids-to-camera / labeled callbacks); add bird-state awareness.

**Also found:** aspect correction — panels are 16:9 (1376×768); clips are portrait because
**Grok reshapes** them (ignores input aspect) → the aspect lever is the CLIP stage, not
the image stage. And a style contradiction: grids say "3D Pixar CG", per-panel image_prompt
says "2D animated illustration".

---

## ★ HANDOFF — 2026-06-14c (aspect ratio chosen at creation; bird is clean vertical)

Commit `8ed98340`, deployed (backend restarted + frontend rebuilt + prod DB migrated).

**Bird video `f32ed182-…` is now a clean VERTICAL video** (728×1080, no distortion,
in sync, plays in-app). Its clips are physically portrait (73/74 × 464×688), so
vertical is correct — Ryan agreed to roll with it. `aspect_ratio` column set to `9:16`.

**New: aspect ratio is a first-class creation choice.**
- `videos.aspect_ratio` column (`'16:9'|'9:16'`, default 16:9, CHECK). Migration
  `add_videos_aspect_ratio` applied to prod (existing rows backfilled to 16:9).
- Picker on the create screen (`CreateVideoStep.tsx`, by the length picker:
  "What shape should the video be?" 16:9 / 9:16). `CreateVideoRequest.aspect_ratio`
  (Literal) + create INSERT (`routes/videos.py:180`). Verified live: 9:16 stores
  9:16, default stores 16:9, invalid → 422.
- Flows into the **storyboard grid request** (executor sets `pipeline.aspect_ratio`
  → `run_images` → `run_storyboard_images` → `generate_contact_sheet`, was hardcoded
  "16:9") and the **thumbnail** (`run_thumbnail` clone path + `_build_thumbnail_clone_prompt`).
- **Render needs NO column wiring** — `render_stitch` auto-detects orientation by
  probing the actual clips (robust for legacy/mismatched content). The column drives
  generation; render follows the pixels.

**STILL OWED — deterministic panel-aspect backstop (task #10, needs a paid test gen):**
The image model (Kie/nano-banana) returned PORTRAIT for the bird even though the grid
was requested at 16:9 — so requesting the aspect is necessary but NOT sufficient. The
guarantee layer is forcing each cropped panel to the chosen aspect (scale+pad or
center-crop) in the storyboard extraction/upscale path, so Grok clips (which inherit
the image shape — Grok has no aspect param) come out right. NOT built: it needs one
real 16:9 video run through generation to observe + tune (pad vs crop), and there's a
`generate_scene_image`/`upscale_panel` signature mismatch to resolve. **9:16 likely
works already** (model defaults portrait); **16:9 is the unproven case.** Don't claim
16:9 generation works until that test is run. Voice_over/Remotion aspect also deferred.

---

## ★ HANDOFF — 2026-06-14b (render FROZEN-FRAME bug fixed + final video plays in-app)

Two follow-ups after the stitch shipped (commit `985c507a`, deployed: backend
restarted + frontend rebuilt):

1. **Frozen-frame bug FIXED.** Ryan's first stitched download froze on frame 1
   in QuickTime while audio played. Cause: `-c copy` concat keeps only the FIRST
   clip's H.264 parameter set (avcC) in the MP4 header; each Grok clip has its own
   SPS/PPS (+ an mjpeg attached-pic track + unset mov timescale), so strict players
   freeze (ffmpeg/VLC were lenient and hid it). `render_stitch.py` `_concat` now
   **re-encodes** to one clean H.264 stream (`-map 0:v:0 -map 0:a:0`, libx264
   veryfast, CFR 24, clean timescale). ~50s for the 9-min bird video. Re-rendered:
   final is now 48.6MB, single h264+aac, frames verified advancing. **No stream-copy
   fast path anymore** — it's a footgun for these clips. Preset/crf/fps via
   `STITCH_X264_PRESET`/`STITCH_X264_CRF`/`STITCH_FPS` env.
2. **Final video now plays IN-APP.** It was broken: the player fed the raw Drive
   `uc?export=download` URL into `<video>` (won't stream). Fixes: allowlist
   `final_video_url` in the media proxy (`routes/media.py` `_ALLOWLIST_SQL`); add
   HTTP **Range/206** to `serve_drive_file` (`_download_range`) so `<video>` streams
   + seeks; new `toDisplayVideoUrl` (`frontend/src/lib/utils.ts`) + `RenderTab.tsx`
   route the player through `/api/media/drive/<id>`. Verified: proxy returns 206 with
   correct Content-Range; full fetch is a valid mp4. Ryan should hard-refresh the
   Render tab to see it.

20-concurrent note: with re-encode the 4-core VPS is the ceiling (~17 min for the
last of 20 simultaneous 9-min renders, vs 60–90 min EACH on old Remotion). The
ffmpeg semaphore (`STITCH_FFMPEG_CONCURRENCY`, default 3) queues the burst.

---

## ★ HANDOFF — 2026-06-14 (RENDER SOLVED for grok_native — FFmpeg stitch is LIVE)

Read this first. Supersedes the render sections below (their *file-lines* are
still accurate, but RENDER is no longer blocked for grok_native).

**What shipped (deployed to prod, commits `0085c448` + `75f847c6`):**
- New **FFmpeg clip-stitch render path** for grok_native videos. Every grok_native
  clip already carries Grok's baked-in audio, so the "render" is just the clips
  concatenated in (scene, image_index) order — no Remotion, no
  `render_config.json`/Whisper, no `Scene.tsx` muted-clip+narrator bug. Code:
  `storyengine/backend/render_stitch.py` (`stitch_video()`); wired in
  `pipeline_executor.py` `run_render` → branches `grok_native` → `_run_stitch_render`,
  else legacy Remotion (unchanged). The route (`/api/pipeline/render/<id>`) and the
  render fast-path are IDENTICAL — no new endpoint.
- **Bird video `f32ed182-…` is now `rendered`.** `final_video_url` set (Drive),
  102MB, h264 736x400 + AAC 48kHz, **539.1s**, audio verified present
  (mean −30 dB). Real production path: ~27s start→finish, method=`copy` (stream-copy).
- **Built for ~20 concurrent renders** (Ryan's explicit ask): per-render `tempfile`
  dir (no shared `public/` collision like Remotion had), a per-worker GoogleClient
  download pool (httplib2 is NOT thread-safe — one shared connection raced and
  crashed; fixed in `75f847c6`), and a process-wide ffmpeg semaphore
  (`STITCH_FFMPEG_CONCURRENCY`, default 3) so the re-encode fallback can't melt the
  4-core box. Stress-tested **4 concurrent stitches → 4/4 OK, load 0.50→0.89** (CPU
  is nowhere near the limit; stream-copy is ~free). At true 20× the ceilings become
  Drive download bandwidth + RAM (each render holds ~100MB final bytes in memory for
  upload) — both have headroom (13Gi free), but streaming the upload is the obvious
  next optimization if needed.

**Still owed / not done here:**
- **voice_over videos still hit the Remotion blockers** (missing `render_config.json`
  crash + `Scene.tsx`). Only grok_native is on the new path. Wire `run_audio_sync`
  (or stitch+narrator-mux) if a voice_over video needs to render.
- **Clip-pipeline fragility fix** (no resume / one-blip-kills-batch / 10-min
  slow-poll) is STILL UNFIXED — see the fragilities section below. Separate from render.
- Thumbnail character-fidelity issue (generic look-alikes) still open — see below.

---

## ★ HANDOFF — 2026-06-14 (clips DONE, thumbnail built, RENDER is next)

Read this first. The "▶ NEXT GOAL" and older handoffs below are still correct on
render *details/file-lines* but their status numbers are STALE.

**Bird video `f32ed182-be1f-4a24-a8de-bb8db4ac88df`, tenant `ee93e6d1-…`. State now (prod DB):**
- **All 74/74 clips animated** (was 8/74). Finished this session with a server-side
  per-scene → per-asset runner because the "Animate the rest" button kept dying
  mid-batch (see fragilities note below). grok_native, so Grok's dialogue is baked
  into the clips.
- **Thumbnail built + live.** status `ready_for_thumbnail`. The in-app **Regenerate**
  button (`production/ThumbnailTab.tsx` → POST `/api/pipeline/thumbnail/<id>`) now runs a
  **reference-clone**: cast sheet (`character_reference_url`) fed FIRST + the modeled
  YouTube thumbnail (`reference_url` → `img.youtube.com/vi/<id>/maxresdefault.jpg`)
  SECOND/layout-only, driven by the editable **`thumbnail_prompt`**. Model = **GPT Image 2**
  (`gpt-image-2-image-to-image` via kie.ai, `image_client.generate_thumbnail_gpt2`),
  nano-banana-pro fallback. Code: `pipeline_executor.py` `run_thumbnail` +
  `_build_thumbnail_clone_prompt`; commits **80fc65db, 29c59d22, 8fcc7fd6** (all deployed).
- **Thumbnail OPEN ISSUE (Ryan rejected current quality):** the generated people are
  generic Pixar look-alikes, NOT the exact cast-sheet characters — faces/builds/outfits
  differ, Dr. May loses her East-Asian design. Root cause: one 6-up cast sheet is weak
  conditioning; the model invents faces. Options offered (Ryan deferred to do the render):
  (1) per-character reference crops [strongest generative lock], (2) composite the real
  character art [exact chars but stiff poses], (3) accept type-accurate. NOTE: the video's
  own scene panels ALSO drift from the sheet — broader character-consistency gap, not just
  the thumbnail.

**NEXT STEP = RENDER. Two real code blockers remain (now MORE relevant — all clips are grok_native):**
1. **HARD BLOCKER — `timing/<id>/render_config.json` missing → instant crash.**
   `render/run.py:141` raises RuntimeError if `skills/video-pipeline/timing/<video_id>/render_config.json`
   is absent, and the prod pipeline never calls `run_audio_sync`. FIX: run audio-sync for
   this video (run `render/run_audio_sync.py` for the video_id on the VPS, or wire it into
   the render preflight). Whisper must be installed where it runs.
2. **grok_native audio will be wrong.** `remotion-video/src/Scene.tsx:260` hardcodes
   `muted` on every clip and `Main.tsx` always plays the ElevenLabs narrator. This video is
   grok_native (dialogue baked into the clips) → render would mute the clips and play only
   the narrator. FIX: thread `dialogue_audio` + a per-scene "speaking" flag from the videos
   row → `render/upload/run_package.py` props.json + render_config → `Scene.tsx`; drop
   `muted` and duck/suppress the narrator on grok_native speaking scenes; keep voice_over
   unchanged. Preview with `cd remotion-video && npm run studio` before a full render.

**Render fast path (after the two fixes):** Approve & Advance (Thumbnail tab) to
`ready_to_render`, then POST `/api/pipeline/render/<id>` → ~10–20 min `npx remotion render`
in `remotion-video/`, uploads mp4 to Drive, sets `videos.final_video_url`, status→rendered.
Poll `GET /api/pipeline/status/<id>`. **Do NOT deploy/restart during the render (no resume).**
Then check the audio; optional `POST /api/pipeline/upload/<id>` → private YouTube draft.

**Infra (NEW this session — operating prod from Ryan's Mac):**
- `ssh storyengine-vps` (user `clawd`, key `~/.ssh/storyengine_vps`). Project
  `/home/clawd/projects/economy-fastforward`.
- **Deploy = git push main (Mac) → on VPS `git pull --ff-only` + restart.** No passwordless
  sudo, so restart = `kill -9 $(pgrep -f "uvicorn main:app")` and systemd `Restart=always`
  revives it (~10–15s). Verify: `curl localhost:8001/api/pipeline/task/<id>`.
- Token `/tmp/se_token` (re-minted, 7-day). API `localhost:8001`. Prod DB = Supabase
  `wrromlupsmyzrrcqlucn` (via Supabase MCP). API keys (KIE/OpenAI/…) live in the `secrets`
  vault TABLE, hydrated to env at runtime — NOT in `.env`/`/proc`; a standalone script must
  `vault.get_secret(...)` or inherit the running uvicorn process's env. No OpenAI key set —
  GPT image runs through kie.ai's `KIE_AI_API_KEY`.
- **Clip pipeline still FRAGILE + UNFIXED** (Ryan approved fixing it but we did the thumbnail
  instead): all-clips batch has no resume (a restart/crash/SSL blip kills it), clips slow-poll
  ~10 min, a just-completed task lingers 30s and 409s the next tap. Regenerate clips
  scene-by-scene / per-asset, never one giant batch.

---

## ▶ NEXT GOAL (Ryan, explicit): finish the bird video to THUMBNAIL + RENDER on the VPS

Read this section, then the full handoff below. Recon for this was done by a
4-agent workflow (thumbnail/render/state/banner) with adversarial blocker
verification — the findings below are verified, not guesses.

**Where the bird video is right now (prod DB, confirmed):** status
`ready_for_video_generation`, dialogue_audio `grok_native`, 74/74 pictures,
**8/74 clips**, no thumbnail, no final video, `render_config.json` MISSING.

**The honest situation:**
- THUMBNAIL works today (no code needed). It makes 3 options from text (no
  vision). The fancy Gemini "best-of-3" 4th image is skipped because Ryan's
  tenant has no Gemini key — that's fine, you still get a thumbnail.
- RENDER has **two real problems** that must be handled before a good render:
  1. **HARD BLOCKER — the timing file is missing and nothing makes it.**
     `render/run.py:141` raises `RuntimeError` ("Audio sync must run before
     rendering") if `skills/video-pipeline/timing/<video_id>/render_config.json`
     doesn't exist. It doesn't for this video, and the production LightPipeline
     NEVER calls `run_audio_sync` (only the old image-prompts stage did). So a
     plain render request CRASHES instantly. FIX: wire `run_audio_sync` so it
     runs for Supabase videos (add a standalone trigger, or run
     `render/run_audio_sync.py` for this video_id on the VPS), OR add it to the
     render preflight. Whisper must be installed where it runs. This is the #1
     job before render will do anything.
  2. **AUDIO WILL BE WRONG for grok_native — code fix in Remotion.**
     `remotion-video/src/Scene.tsx:260` hardcodes `muted` on every clip and
     `Main.tsx` always plays the ElevenLabs narrator track. For this video the
     Grok dialogue is baked INTO the clips — render mutes it and plays only the
     narrator, the opposite of grok_native. `grep dialogue_audio remotion-video`
     = 0 hits. FIX: thread `dialogue_audio` (+ a per-scene "speaking" flag) from
     the videos row → `render/upload/run_package.py` props.json + render_config →
     `Scene.tsx`; drop `muted` and suppress/duck the narrator on grok_native
     speaking scenes. Keep current behavior for voice_over. Preview with
     `cd remotion-video && npm run studio` before a full VPS render.

**Phantom blockers — DO NOT chase these (verified false):**
- Plan/billing gate: tenant is at 0/120 render-minutes, passes clean.
- No Redis on the VPS: render runs in-process via BackgroundTasks fine — just
  don't deploy/restart during the ~10–20 min render (it has no resume).
- Kie-Claude vision drift: does NOT touch the thumbnail stage (text-only gen).

**Fast path to a render (exact calls; `T=$(cat /tmp/se_token)` on the VPS,
base `http://localhost:8001`, header `Authorization: Bearer $T`):**
1. Clips: either finish (`POST /api/pipeline/clip/<id>` = all 66 remaining,
   ~$6.60 at $0.10/clip; or per scene `?scene=3`) OR skip
   (`PATCH /api/videos/<id>/advance?to=ready_for_thumbnail`). grok_native +
   stills get gentle zoom, so skipping is viable — but note skipped scenes have
   NO spoken dialogue (only the clips carry Grok's voice), so for a real watch
   you probably want clips finished. Ryan's call.
2. Thumbnail: `POST /api/pipeline/thumbnail/<id>` (or skip
   `?to=ready_to_render`). Advances to ready_to_render.
3. **Fix render blocker #1** (render_config) — render crashes without it.
4. Render: `POST /api/pipeline/render/<id>` → ~10–20 min `npx remotion render`
   in `remotion-video/`, uploads the mp4 to Drive, sets `videos.final_video_url`,
   status → rendered. Poll `GET /api/pipeline/status/<id>`.
5. Watch the mp4's audio — if grok_native sounds wrong, that's blocker #2.
6. (Optional) `POST /api/pipeline/upload/<id>` → private YouTube draft.

**Two still-flagged bad crops (cosmetic, won't block render):** S4.4, S6.12
(`extraction_flags=['label_leak']`) — tap "Bad crop — fix it" in the Scenes
tab to re-crop, or leave them.

**Full thumbnail/render entry points** (for when you build the fixes):
thumbnail route `routes/pipeline.py:1247` → `PipelineExecutor.run_thumbnail`
(`pipeline_executor.py:2710`) → `thumbnail/engine.py`. Render route
`routes/pipeline.py:1297` → `run_render` (`:2757`) → `render/run.py:run()` →
`npx remotion render Main` (composition in `remotion-video/src/Main.tsx`).

---

## ★ THREAD HANDOFF — read this first (2026-06-13, Scenes-workspace thread: all 4 answers shipped)

**North star (in agent memory too):** any person pastes a YouTube link → the
machine replicates that video (new script/idea) FULLY UNATTENDED. Ryan has a
queue of people wanting their channels automated; every design choice must
work without a human in the loop. Intelligence layers detect format — never
manual flags. Corollary: every pipeline element must be OPTIONAL
("sometimes they just want research, ideas and script").

**Working video:** the "Injured Baby Bird" ESL kids animation,
`f32ed182-be1f-4a24-a8de-bb8db4ac88df` (Ryan's tenant `ee93e6d1-…`).
Kie-only stack. Prod = systemd from /home/clawd/projects/economy-fastforward
(git push main → pull there; restart = kill -9 MainPID, uvicorn hangs
draining SSE). Dev repo = /home/clawd/economy-fastforward. Auth for API
test scripts: mint JWT {iss:"storyengine", sub:<account uuid>, tenant_id}
with SESSION_SECRET from PROD storyengine/.env (dev repo has NO .env;
account 381bdcc3-…, a ready token sits in /tmp/se_token on the VPS).
⚠ Clip taps within ~10s of a restart fail (cold-proxy race, see lessons
pt 12 — backoff shipped, but don't script POSTs right after a deploy).

**RYAN'S 4 ANSWERS — ALL SHIPPED + VERIFIED LIVE this thread:**
1. ONE SCENES WORKSPACE ✓ — `ScenesWorkspaceTab.tsx` replaces the separate
   Storyboard + Video Clips tabs (both DELETED). One card per scene: boards
   row (drag-drop replace, per-slot X) → animatic → narration → a
   SegmentCard grid where each story segment shows its clip (tap=play,
   hover Redo/X) OR its picture (tap=Animate ~$0.10, hover X), with the 💬
   speaker badge and the red bad-crop badge. Per-scene verbs (Plan / Draw /
   Redo boards / Start over / Animate this scene·$X), one status strip, one
   merged ⋯ Advanced. Tabs renumbered 10→9 ("4 · Scenes"); legacy tab ids
   map across; next-action targets "scenes"; default tab lands on Scenes
   through ready_for_video_generation. Verified live on prod (Playwright,
   Ryan's tenant): 8 scenes, 12/13 boards, 74/74 pictures, 7 Animate-scene
   buttons, 3 bad-crop badges, zero console errors; Scene 1 board + 4
   picture cards render (screenshots in /tmp/scenes_workspace*.png).
2. AUTO RE-ANIMATE ✓ — run_recrop_panel AND run_storyboard_extract track
   pictures replaced under an existing clip and re-run clip generation for
   exactly those (force=true, ~$0.10 each, never animating unpaid cards).
   Verified live: scene-2 re-crop → "re-animated 3/3 stale clip(s) (~$0.30)".
3. OFF-SCREEN SPEAKER RULE ✓ (supersedes "cutaway rule") — S1.4 was never a
   cutaway: its sentence carries the tail of Tom's line, so it's a SPEAKING
   card and the prompt itself summoned the boy. OFF_SCREEN_SPEAKER_RULE now
   rides every speaking prompt (verified live: legs stay at frame edge).
   motion_guard still guards NARRATION cards (cutaway → NO PEOPLE; else →
   nobody-NEW).
4. EXTRACTION VALIDATION ✓ — panel_flags (label_leak/gutter_split, 15/15 on
   real panels), separator-rect cropping (the generator drew scene 2 as
   3-top/2-WIDER-bottom — uniform crops CANNOT cut it), chip auto-trim,
   orphan guard, migration 050 assets.extraction_flags, POST
   /videos/{id}/assets/{aid}/recrop (re-cuts the whole beat, background
   task), red badge + one-tap fix wired into the Scenes workspace. Scene 2
   re-cropped 5/5 clean live; 12 orphan rows deleted + Drive copies trashed.

**What is LIVE (this thread + clips day):**
- THE SCENES WORKSPACE is now the visuals surface (see answer 1 above). The
  old VideoClipsTab/StoryboardVisualsTab are gone — don't resurrect them.
- Clip generation per the UX contract: tap card = animate ($0.10 Grok, no
  confirm), per-scene buttons, banner trust ladder, 💬 speaker badges,
  hover Redo/X, real cost math, ⋯ Advanced (model picker — grok + veo
  wired), silent motion-prompt auto-run, always-on useTaskWatcher (pill).
- All 158 dialogue segments voiced (ElevenLabs via Kie, jsonb audio_url+
  duration); cast: Tom=Finn, Lisa=Brittney, Mom=Tiffany, Dad=Brian,
  Dr.May=Bella, Bird=Emma; narrator=Mark. Casting excludes narrator voice.
- DIALOGUE AUDIO IS PER-VIDEO (migration 049 videos.dialogue_audio, toggle
  in clips ⋯ menu). Bird video = 'grok_native': NO overlay, Grok speaks the
  EXACT scripted words (native_speaking_prompt feeds only the sentences the
  card covers; match_lines is sentence-level). Ryan LOVES S1.3 native.
  'voice_over' mode (ElevenLabs overlay + ambience bed) is one toggle away.
- Clip prompts: constraints LEAD (@image1 = ground truth, no invented/
  resized characters, off-screen stays off-screen), cast sheet as @image2
  with names, style directive appended, cutaway no-people rule.
- Skip buttons live on the guided banner (white pill, "I don't need this —
  skip it →", consequence confirm, advance?to= forward jump): research,
  review, voice, clips rungs, sound, thumbnail.
- The lip-sync saga is SETTLED — read decisions.md before touching it:
  five approaches tested in one day; final = Grok full-scene + native
  voices for this video. Kling-style video lip-RETARGETING is the upgrade
  if Kie ever ships one.
- Claude-via-Kie VISION IS DEAD (gateway drift; images become file refs,
  ~272 input tokens). Parallel session rerouted vision via
  shared.clients.vision_client + canary (see pt 11 handoff below).

**VERIFIED / RESOLVED this thread (2026-06-13 early):**
- S1.4 ✓ off-screen rule holds (bird close-up stays a cutaway, audio track
  carries the line — Ryan should LISTEN to confirm the words).
- S2.2/S2.3/S2.4/S2.5 ✓ re-cropped clean (chips trimmed, split healed);
  their 3 existing clips were redone on the new pictures (~$0.30).
- Motion prompts: real coverage is 74/74 — the "86" included 12 orphan
  extraction rows (no sentence/prompt), now deleted. Stat is honest now.
- Two extra bad crops found + healed that nobody had reported: S4.4,
  S6.12 (the validator caught them; S2.3's chip too).
- SECURITY NOTE: a stale .env backup briefly hit the PUBLIC repo (force-
  rewritten in minutes; creds were for a DELETED Supabase project — dead).
  .env.bak* now gitignored. Stale local artifacts quarantined in
  ~/economy-fastforward-stale-artifacts (they had CONFLICTING migration
  numbers — never git add -A in that old Mac checkout).

**Open / next session:**
- RYAN TO REVIEW the Scenes workspace end-to-end (it's a big surface change —
  every video opens here now). Watch a re-crop on S4.4 or S6.12 (still
  flagged) and confirm the bad-crop badge → one-tap fix feels right.
- S2.2 style (semi-photoreal bird) — label bar is FIXED; redrawing the
  board would replace 4 good panels. Ryan's taste call.
- Scene 5 'Receptionist' speaks 2 lines in narrator voice (uncast walk-on).
- tag-dialogue auto-hook still modeled-path only.
- Next pipeline elements (from clips day): (b) animatic segment timeline;
  (e) render respecting dialogue_audio (grok_native clips carry their own
  audio); full keep/skip matrix so every element is obviously optional.
- Scene 5 'Receptionist' speaks 2 lines in narrator voice (uncast walk-on).
- tag-dialogue auto-hook still modeled-path only.

**Read before coding:** tasks/lessons.md pt 12 (off-screen speaker rule,
cold-proxy race, extraction rects, per-panel flag comparisons) and pts
7–10 (NULL-column .get trap, status-lag gates, Kie TTS flakes, vision
drift, watcher-not-poller×2), tasks/decisions.md (clips UX contract,
extraction-trusts-pixels, off-screen speaker, dialogue final form,
voice-over optional). Session history below.

## Handoff (2026-06-12 pt 11 — vision rerouted + canary live)

The morning's dead Kie Claude vision REVERTED on its own (12/12 repro calls
fine by evening) — classic provider drift, so the fix is structural:
- `shared/clients/vision_client.py`: ALL product vision goes through one
  provider chain (Kie Gemini 2.5 Flash with per-call ingestion proof →
  Kie Claude → direct Anthropic). 9 unit tests.
- Rerouted: model_video thumbnail pass (now a separate vision pass whose
  observation is injected into the pack prompt as TEXT — generation never
  carries an image block), storyboard `_grid_style_matches_reference`,
  characters approve-cast rewrite.
- `canaries/vision_drift.py` hourly USER systemd timer (no root; linger on)
  + ntfy alert (same topic as validator canary). Known image: red circle on
  blue at Supabase `assets/<tenant>/canary/vision_canary.png` (~$1.5/mo).
- NOT migrated (legacy YouTube pipeline, direct Anthropic SDK):
  autopilot/analysis/thumbnail_analyzer.py, video_dispatch/verify_output.py.

## Handoff (2026-06-12 pt 7 — clips UX contract locked + per-segment voice SHIPPED)

Ryan answered 8 design questions for the clips stage (full contract appended to
decisions.md as "Video Clips stage UX contract" — read it before touching the
clips tab). Headlines: three-rung trust ladder (card tap ~$0.10 → "Animate this
scene" → banner-gated "Animate everything"), Generate Prompts button dies
(prompts auto-run silently), ALL segments get clips, 💬+name badge on dialogue
cards, voice auto-chain on tap, cost confirm >$0.50 only, play-inline +
hover Redo/X on cards, strip + ⋯ Advanced replaces all six header surfaces.
Found during recon: VideoClipsTab cost is fake (86×$0.30 hardcoded = $25.80;
Grok is ~$0.10/6s → ~$8.60), the model dropdown writes videos.video_model but
the BACKEND IGNORES IT (Grok hardcoded in image_client.py:704-785), and no
single-clip endpoint exists at all — both get wired during the clips build.

STEP (a) PER-SEGMENT VOICE SYNTHESIS SHIPPED:
- backend/dialogue_voice.py: walks scripts.dialogue_segments; narrator voice
  (scripts.voice_id) for narration, video_characters.voice_name for dialogue
  (stability .45 / style .2 / speed 1.05 — client gained style+speed params),
  uploads {video}/voice/S{n}-seg{i}.mp3 via storage.upload_bytes, writes
  audio_url + duration (+voice_name) into the jsonb AFTER EVERY segment
  (resume-safe), 3 attempts/segment with 5s backoff (Kie TTS flakes
  "internal error" transiently — hit twice live), cooperative cancel.
- executor.run_dialogue_voice (auto-tags untagged videos first; narration-only
  videos complete as a no-op) + silent auto-hook after full voice runs for
  dialogue-mode videos + POST /api/pipeline/dialogue-voice/{video_id}?scene=N.
- 6 functional tests: tests/functional/test_dialogue_voice.py (module-stub
  pattern, zero network) — voice routing, resume skip, per-segment persist,
  cancel-keeps-work, scene filter, helpers.
- Bird video live: scene 1 verified (14/14 voiced; real MPEG bytes pulled via
  authorized Drive API; header duration == db duration; 19.4s timeline).
  Tom RECAST Mark→Finn (his cast voice was IDENTICAL to the narrator —
  cast_character_voices now excludes the narrator's voice from the roster);
  scripts.voice_id was an off-roster id, set to Mark explicitly. Full 8-scene
  run (158 segs, ~$1-2 TTS) launched in background — check segment counts via
  scripts.dialogue_segments before building (b).

CLIPS TAB REBUILT same session (the UX contract is now LIVE code):
- POST /api/pipeline/clip/{video_id}?asset_id=&scene=&force= — ONE endpoint
  for all three rungs (tap a card / Animate this scene / Animate everything);
  executor.run_clip_generation honors videos.video_model via MODEL_REGISTRY
  (grok + veo-3.1 fast/quality wired; others rejected with friendly copy),
  proxies panel images via PUBLIC_MEDIA_BASE/api/media/drive/{id} for Kie,
  downloads clips IMMEDIATELY (24h URL expiry) → Drive {video}/clips/
  S{nn}-{ii}.mp4 → assets.video_clip_url, semaphore(3), cancel support,
  full-run-complete advances to ready_for_thumbnail.
- GET /api/videos/{id}/dialogue-map (💬 badges), DELETE /api/videos/{id}/
  clips/{asset_id} (hover-X: clears column + trashes Drive copy).
- VideoClipsTab rebuilt: status strip + ⋯ Advanced (model picker with real
  prices, coming-soon disabled, re-run prompts, motion instructions toggle);
  scene groups with "Animate this scene · $X"; tap card = animate (~$0.10,
  no confirm), tap done card = play inline; hover Redo/X; failed = red Try
  again; 💬 speaker badges via dialogue-map substring match; motion prompts
  AUTO-RUN silently on arrival (promptlessCount guard); confirms only >$0.50.
- next-action.ts: clips trust ladder (Animate scene 1 → Animate the rest →
  thumbnail) + clipCost()/CLIP_COST_PER_MODEL as the single price source;
  GuidedNextStep passes clipsDone/clipsTotal. Old Generate Prompts/Generate
  All Clips/Advance Stage/visible dropdown/always-on prompt editor all gone.

VERIFIED LIVE ON PROD (Playwright + API, Ryan's tenant):
- Tap → $0.10 Grok clip → Drive {video}/clips/S01-01.mp4 → assets row →
  plays via media proxy (frames eyeballed: on-model Pixar Tom, real motion).
- Tab renders: "1 of 86 pictures animated · ≈ $8.50 · Grok Imagine", 8 scene
  buttons, 34 💬 badges, real card pictures, zero old surfaces, banner shows
  "Animate the rest". Console clean on warm backend (cold-start 502s are
  transient, see lessons).
- THREE live bugs found+fixed en route: assets column is duration_seconds;
  clip gate + banner keyed on lagging status strings (bird video =
  ready_for_images with 86/86 finals); GET /api/videos/{id} SELECTed
  story_locked_at but never passed it to VideoDetail → banner re-offered
  Lock forever (one-line constructor fix).

STEP (c) DIALOGUE SPEAKING CLIPS SHIPPED (same day, Ryan: "S1.2 got no
dialogue — fix"): backend/clip_dialogue.py — norm/match_lines pairs a card's
sentence_text with the scene's tagged dialogue lines (same containment logic
as the frontend 💬 badge), speaking_prompt() directs Grok lip movement,
mux_voice() replaces Grok's invented audio with the segment's ElevenLabs
line(s) via ffmpeg (concat for multi-line cards), strip_audio() silences
narration clips (renderer narrates over them). run_clip_generation now:
speaking cards get the speaking prompt + a clip long enough for the line +
the voice muxed in; unvoiced scenes auto-chain run_dialogue_voice first
(contract Q5); mux failures keep the raw clip with a logged warning.
3 functional tests incl. a REAL ffmpeg mux round-trip.
ALSO fixed: NULL duration_seconds rows crashed the whole video-scripts run
('.get(key, default)' ≠ NULL-safe — see lessons); clips tab switched to the
always-on useTaskWatcher (purple progress pill shows ANY running task, taps
during a run explain what's running instead of a bare 409).

LIP-SYNC, FINAL FORM (Ryan: "way off the other direction — research how
people actually do this", then "the BOY's lips moved with Lisa's line"):
dialogue clips are AUDIO-DRIVEN PORTRAIT CUT-INS. 💬 cards →
image_client.generate_talking_video (Kie `infinitalk/from-audio`: the
SPEAKER'S APPROVED PORTRAIT (video_characters.reference_url) + segment
ElevenLabs mp3 via media-proxy URLs + who-speaks prompt → talking clip,
length = audio length, $0.015/s ≈ $0.03-0.05/line, 7-10 min/clip, poll
budget 15 min). Why portrait not panel: on multi-character panels the
model animates the MOST PROMINENT face (Tom mouthed Lisa's line — Ryan
caught it watching; my still-frame check had called it wrong). Portrait =
one subject = can't miss + deterministic + the approved lip-test recipe.
Verified live on S2.1: Lisa alone, articulating, $0.03. Fallback: full
panel when speaker has no portrait (logged warning). Vision onset
detection + mux + speaker-crop all RETIRED (git history); strip_audio
stays for narration clips. Multi-line cards: first line only.

⚠ DISCOVERED: CLAUDE-VIA-KIE VISION IS DEAD (gateway drift) — images
become /mnt-style file refs the model can't see (272 input tokens, no
image; haiku refuses, sonnet preambles then ends; URL and base64 both).
Likely silently degrading: model_video thumbnail style-DNA (modeled
videos!), storyboard vision QA loop, approve-cast description rewrite.
NEEDS ITS OWN INVESTIGATION + canary. _call_claude now joins all text
blocks (content[0] truncated multi-block replies).

DIALOGUE AUDIO IS NOW PER-VIDEO (migration 049, videos.dialogue_audio,
toggle in clips ⋯ menu): 'grok_native' (bird video's setting — Grok speaks
the EXACT scripted words, native_speaking_prompt feeds only the sentences
covered by the card; no synthesis chain, full Grok audio kept) vs
'voice_over' (ElevenLabs overlay + ambience bed). match_lines is now
sentence-level (lines spanning cards — the S1.3 wrong-words bug).

RYAN'S 4 ANSWERS (2026-06-12 late — the next build's spec):
1. ONE SCENES WORKSPACE: merge storyboard + final pictures + clips into a
   per-scene view (boards, pictures, clips side by side, redo at any level).
   The separate storyboard/clips tabs collapse into it. THIS IS THE NEXT
   BIG BUILD — invoke web-design-guidelines/react skills, plan from
   tasks/decisions.md UX contract.
2. AUTO RE-ANIMATE: redoing a picture auto-regenerates its clip (~$0.10,
   cost note shown).
3. CUTAWAYS (shipped same night): no-people hard rule prepended for cards
   whose image_prompt+sentence mention no cast name and match no dialogue
   line (deterministic — no vision needed). S1.4 class.
4. BAD CROPS: extraction must VALIDATE panels (internal-gutter split check,
   label-bar [KFn|XX|Ns] leak check — white-on-black text defeats the
   brightness trim) → red 'bad crop' badge + one-tap 'Re-crop this picture'.
   Ryan hit both on S2.4/S2.5 (split across two pictures) + a label leak.
Also open: S1.4 regenerated the invented boy AGAIN even with constraints-
first prompt (before the cutaway rule shipped) — verify the cutaway rule
catches it on next redo.

SKIP V1 SHIPPED: banner shows 'I don't need this — skip it →' on optional
steps (research/review/voice/clips rungs/sound/thumbnail), inline
consequence confirm, advance?to=<status> forward-jump (validated). S1.2/
S1.3 regenerated grok_native and approved-ish by Ryan (S1.3 'love it').
NEXT: full keep/skip matrix view — every pipeline element obviously
optional per video ("sometimes they just want research/ideas/script — make
it very obvious, a skip button on certain elements"). Then: (b) animatic
segment timeline; (e) render (respecting dialogue_audio — grok_native clips
carry their own dialogue audio); (f) tag-dialogue on non-modeled path.

## Handoff (2026-06-12 pt 6 — dialogue intelligence SHIPPED, lip test PASSED)

Ryan greenlit the dialogue plan with decisions (recorded in decisions.md):
ElevenLabs character voices + Grok lips; narrator pauses; convert bird video
in place; everything must serve UNATTENDED channel automation (north-star,
also in agent memory).

DONE this session:
1. LIP TEST PASSED: Grok clip from Lisa's portrait — she visibly speaks
   (mouth movement, acting, leans to the bird Grok added from the prompt);
   muxed with a Kie/ElevenLabs line → `lisa-dialogue-test.mp4` in the bird
   video's Drive folder for Ryan to watch. Cost ~$0.06.
2. DIALOGUE INTELLIGENCE LIVE (dialogue_intelligence.py + migration 048):
   detect_dialogue_mode (whole script → character_dialogue|narration_only),
   segment_scene (ordered narrator/speaker timeline, attributions dropped,
   words verbatim, 60% retention sanity check), cast_character_voices
   (stable Kie ElevenLabs voice ID per character; curated 13-voice subset;
   full 67-voice enum + preview URLs in the session notes below).
   POST /api/videos/{id}/script/tag-dialogue + auto-hook after modeled
   script stage (best-effort). Bird video: character_dialogue, 8 scenes,
   65 dialogue lines, cast: Tom=Mark, Lisa=Brittney, Mom=Tiffany, Dad=Brian,
   Dr. May=Bella, Baby Bird=Emma. (Audit: Tom's 'Mark' is an adult voice —
   audition via https://static.aiquickdraw.com/elevenlabs/voice/<id>.mp3,
   Finn vBKc2FfBKJfcZNyEt1n6 is the boy option.)
3. Kie ElevenLabs API facts: voice param takes the ID (names rejected),
   input {text<=5000, voice, stability .45, style .2, speed 1.05 reads
   younger}; do NOT send language_code on multilingual-v2.

NEXT (in order, per the approved plan):
a. Per-segment voice synthesis: walk dialogue_segments, TTS each segment
   (narrator voice for narration, character voice_name for dialogue) via Kie,
   upload {video}/voice/S{n}-seg{i}.mp3, write audio_url+duration into the
   jsonb. Executor stage + banner progress.
b. Animatic plays the new timeline (radio-play rehearsal, $0).
c. Grok clip client in the pipeline (grok-imagine/image-to-video, duration
   STRING, mux ElevenLabs line over dialogue clips, label-bar cleanup first).
d. Per-scene "Animate this scene" + scene-gate + bulk with cost confirm.
e. Render: Remotion timeline with narration pauses + dialogue clip audio.
f. Auto-hook the NON-modeled script path too (only modeled path hooked now).

## Handoff (2026-06-12 pt 5 — extraction geometry fix, upscale policy wall, dialogue-clips plan)

Ryan: scene 2 animatic showed 3-panels-in-one and didn't rotate; scenes 7/8 had
no player; 82/85 mystery. All fixed + verified (Playwright: 8/8 players, S2
plays 6 single panels, audio rolling):
1. EXTRACTION GEOMETRY: extraction.py guessed grid layout from dark-band pixel
   detection; scene 2's 2x3 grid was misread → full-row composite crops, 3
   empty slots. Fix: `grid_layout_for(panel_count)` (mirrors bot._grid_layout),
   executor chunks scene slots 9-per-beat and passes exact rows/cols; detection
   is fallback only. Scene 2 re-extracted → 6 clean panels.
2. PER-SCENE RESUME on extraction: scenes with all slots filled are skipped.
3. UPSCALE = POLICY WALL, not a bug: nano-banana-2 refuses to regenerate
   images of CHILDREN (Google Prohibited Use policy) — all 82 upscales filtered,
   0 credits, ~40 min wasted. Auto-upscale now DISABLED (EXTRACT_AUTO_UPSCALE
   env to re-enable). Needs an ESRGAN-class non-generative upscaler on Kie for
   stills; clips path makes stills less critical.
4. AnimaticPlayer: never unmounts on audio error; retries once with fresh
   token (5-min TTL — players outlive it). Root cause of the missing 7/8
   players was the pre-fix HTML audio killing the component at mount.
5. Known warts for the clips phase: some panels keep their [KFn|MS|10s] label
   bar (white-on-black text defeats the brightness>100 trim scan — fix before
   clips, Grok will reproduce labels from reference); scene 2 gained a 6th
   slot with no sentence_text (executor inserts rows for extra real panels).
6. DB env gotcha: load backend/.env BEFORE root .env in scripts — root has a
   dead DATABASE_URL and the legacy Drive parent.

DIALOGUE-CLIPS PLAN written and reported to Ryan (NOT built — awaiting his
sign-off on: Grok-native vs ElevenLabs character voices for dialogue;
narration pauses vs ducks during dialogue; convert bird script in place).

## Handoff (2026-06-12 pt 4 — animatic player, silent extraction, dead audio fix, Grok Imagine validated)

Ryan: voice player dead on the storyboard page; extraction should be invisible
("do it in the background"); build the animatic player; switch clips to Grok
Imagine (cheaper) — research what Kie expects. All done except the Grok pipeline
wiring (researched + smoke-tested, integration is THE next build):
1. DEAD AUDIO, two root causes: (a) SecureAudioPlayer guessed
   `https://<host>:8001` for the API (unreachable port in prod); (b) the backend
   audio proxy streamed Drive PUBLIC links → HTML interstitial served as
   "200 audio/mpeg" — players sat at 0:00/0:00. Fixed: API_URL from env +
   authorized Drive API download (same as routes/media.py). Verified: real
   ID3/MPEG bytes, Playwright played scene 1 to 6.7s/28.7s.
2. ANIMATIC PLAYER (AnimaticPlayer.tsx): per-scene $0 preview — final pictures
   under the scene's narration, per-panel duration = sentence word-count share,
   caption overlay, progress bar, panel counter. Mounted on scene cards when
   finals exist; falls back to plain voice player until then. Live: 8 players.
3. SILENT EXTRACTION: Lock Story now auto-starts storyboard-extract (banner
   shows progress; visible step remains only as failure recovery, relabeled
   "Finish making your pictures"). next-action gained finalsMissing guard:
   clips step can never show for a video with 0 finals (the skip-trap Ryan
   screenshotted). Bird video: locked + extracted in background → 82/85 panels
   (3 slots skipped as blank boards — per-segment regen exists in scene
   details if they matter). Upscale ran but no _hd URLs recorded — check
   whether upscale writes in place now (cache fix makes that fine) or skipped.
4. GROK IMAGINE (clips at ~1/6 the cost) — researched on Kie docs + LIVE
   smoke test: model `grok-imagine/image-to-video`, same jobs API
   (createTask/recordInfo), input {image_urls:[proxy URL], prompt, mode:
   "normal", duration:"6"–"30" STRING, resolution:"480p"|"720p"}. Test clip
   from real S1 panel: $0.048, 31s generation, on-model Pixar look, real story
   beat (Tom kneels to the bird). 720p ≈ $0.09–0.12/clip vs Veo Fast $0.30
   (video drops $6–12 → ~$2–4). NO start/end-frame support (Veo keeps that);
   audio always baked in (strip/duck under narration); result URLs expire 24h
   (download immediately); resultJson is a JSON STRING with resultUrls.
   Veo 3.1 Lite ($0.15 flat) is the middle option.

NEXT BUILD (agreed direction): per-scene "Animate this scene" button (clips
appear beside the boards, scene 1 = motion taste-test gate before bulk run),
clip model selector defaulting to grok-imagine/image-to-video, motion presets
by shot type (LS=push-in, ECU=parallax, etc.), then bulk "animate everything".

## Handoff (2026-06-12 pt 3 — ONE-button consolidation of the pipeline page)

Ryan (with screenshot): the storyboard stage had FOUR competing "what now" surfaces
(header Run Next Step/Skip Stage, the guided banner, an 8-button action bar, a
4-step tracker with its own giant CTA) — "consolidate to one button, Apple-esque,
grandma-proof, regeneration lives on the scene cards." Shipped + verified on prod
(Playwright: every old surface gone, exactly one Next-up banner, 0 console errors):
1. GuidedNextStep banner = THE button. New `useTaskWatcher` (use-task-poller.ts)
   watches the video's task slot CONTINUOUSLY → progress + Stop appear in the
   banner no matter which control started the work. Lock Story is now executed BY
   the banner (gold button, kind "lock", zero-board guard in next-action.ts).
   Watcher fires onComplete/onFailed only on live-observed transitions
   (wasRunningRef) + epoch guard so in-flight polls can't misfire after markStarted.
2. Header: Run-next/Skip/Reset/Export → one ⋯ menu. Stepper passive.
3. Storyboard tab: stats row, action bar, tracker, toggle, inline progress banner
   all deleted. One status strip ("8 scenes · 12 of 12 boards" + Unlock when
   locked + ⋯ Advanced: model, upscale, delete finals, re-extract missing,
   start over, skip stage). Scene cards: "Plan this scene" / "Draw the pictures" /
   "Redo pictures" (slot-clears then regen, plan kept) / "Start scene over" which
   AUTO-CHAINS plan→pictures via chainRef consumed in watcher onComplete — the old
   clear-wipes-prompts dead end is gone. Stop dispatches `se:stop-requested` so
   pending chain stages stand down (cancelled reads as completed to pollers).
4. Adversarial review workflow ran (21 agents; verify phase partially hit session
   limits — self-verified the flagged races): fixed stale failure card, zero-board
   lock, menu outside-click close, watcher poll race, chain-409 retry, duplicate
   failure toasts, jargon (Final pictures / picture plans), dead computed values.
Playwright note: headless verification of prod needs /api/auth/me stubbed via
route interception (instant fulfill) — the mount-time /me fetch gets ERR_ABORTED
under headless; everything after auth proxies fine (see /tmp/verify_final.py pattern).
Known minor (documented, not fixed): banner may flicker idle for ≤3s between chain
stages (two watcher instances); switching tabs mid-chain drops the queued stage
(banner self-heals: next action becomes "Finish your storyboard").

Bird video remains: review boards → Lock the story (now the one gold button) →
Create the final pictures.

## Handoff (2026-06-12 pt 2 — per-board X delete, drop-to-replace, stale cache fix)

Ryan: "Drive images aren't what's on screen; no clean way to delete ONE storyboard
image without losing prompts; want to drag Drive images onto a board." All three done:
1. STALE SCREEN: boards regenerate IN PLACE on Drive (same file id) but the media
   proxy said max-age=86400 immutable → browser showed yesterday's pixels for a day.
   Proxy now: ETag = Drive md5Checksum, Cache-Control public no-cache, If-None-Match
   → 304 without download. Verified live (200 + md5 etag, 304 on revalidate).
   → Ryan: a hard refresh once and from then on boards are always current.
2. PER-BOARD X: DELETE /api/videos/{id}/storyboards/{scene}/{beat} clears ONE slot,
   keeps prompts + other boards, trashes the Drive copy (folder matches screen),
   guards scene status (only downgrades grids_generated→prompts_ready for in-range
   beats). Hover X on every filled board card. Bot's per-beat resume skip means
   "create storyboard" after an X only regenerates the missing slot (~$0.07).
3. DROP-TO-REPLACE: drag-drop existed but was invisible (replace-in-place + cached
   URL = nothing seemed to happen). Now: "Drop to replace this picture" overlay,
   uploads land in {video}/storyboard/S{n}-B{m}.png (replaces bot grid in place,
   was orphan grids/ folder), cache-busted <img> after upload, success/error toasts.
   Per-scene Clear confirm now warns it's a FULL redo and points at the X.
Also: trashed empty duplicate Drive video folder (created by a root-.env diagnostic
script — see lessons). Full cycle (upload→proxy-serve→X-delete→Drive-trash) verified
on prod against the bird video's unused slot 5. Tests 5/5 + 7/7, tsc clean.

Bird video remains: review boards → Lock Story → Create final pictures.

## Handoff (2026-06-12 — style drift root causes + vision QA loop)

Ryan: "scene styles still don't match, stale extracted images showing, last scene has
three of the same images." All three fixed + verified by eye:
1. STALE EXTRACTED: 74 pre-storyboard asset images (image_url set, never extracted)
   showed in the Extracted Panels section. Cleared (image_url/drive_image_url NULL,
   status pending). Drive files remain in the library.
2. DUPLICATE PANELS: the director template's HERO BEAT EXPANSION explicitly asked for
   sub-shots showing "the SAME subject — don't change what's shown" (3 crayon panels,
   4 chair holds). Rules now demand visually distinct panels / fewer keyframes + blanks.
3. STYLE DRIFT (2D/photoreal mixed with 3D): two layers —
   a. Template preamble HARDCODED "Cinematic 2D animated illustration..." (the April
      never-hardcode-style lesson again). Now interpolates profile.visual_style_directive
      (= the video's Image Style Override).
   b. Even with correct prompts everywhere, nano-banana-pro stochastically rendered
      photoreal ~1 in 4-12 grids. Instructions can't fix randomness → added a vision
      QA loop: every reference-conditioned grid is compared to the cast sheet
      (Haiku via Kie) and regenerated once on mismatch. Caught a live drift on its
      first run.
KIE CLAUDE VISION GATEWAY QUIRKS (calibrated live, see bot._grid_style_matches_reference):
   URL image sources unreliable, assistant prefill IGNORED, small max_tokens IGNORED
   on vision calls → use base64 images + parse a 'FINAL: YES/NO' closing line.
Bird video: 12/12 boards now style-consistent (audited via the calibrated checker +
eyeballed S1/S5/S8). Ready for review → Lock Story.

## Handoff (2026-06-11 pt 4 — character consistency: labeled cast sheet)

Ryan: "character styles are all over the place in the boards." Root causes + fixes:
1. SIX separate portrait refs in image_input dilute each other — model can't map
   names to faces. FIX: approve_cast composes ONE labeled cast sheet (PIL, portrait
   + name per tile) -> videos.character_reference_url; executor passes it as the
   single reference; generate_contact_sheet prompt says "match these EXACT labeled
   characters."
2. Story Bible character text diverged from approved portraits (text fought image).
   FIX: approval syncs bible descriptions to the cast.
3. Stored descriptions described what portraits were generated FROM, not what they
   show (gen takes liberties: "light blue tee" -> red). FIX: vision pass at approval
   rewrites each description from the actual portrait pixels.
Result (visually verified): all 13 boards across 8 scenes now share one cast —
same Tom/Lisa/Mom/Dad/Dr. May in every panel. Boards ready for Ryan to review+lock.
Note: per-scene storyboard CLEAR also wipes that scene's prompts — regen prompts
before grids (bit Ryan on scene 4, me on scene 1; worth auto-chaining later).
Also this session: media proxy (/api/media/drive/{id}) replaced Supabase serving
copies — Supabase bucket purged (92 objects), Drive is sole media store.

## Handoff (2026-06-11 pt 3 — grandma-proof guided flow + storage reliability)

Ryan's storyboard run silently failed + "UI is confusing, needs next-next-next."

Root causes found & fixed:
1. Kie rejected character refs ('image_input file type not supported') — the stored
   drive.google.com URLs had degraded into HTML interstitials (even lh3 CDN form).
   FIX: dual persistence — Drive stays the organized library, Supabase Storage is the
   serving copy and the URL we store (storage.py drive branch). Public 'assets' bucket
   created. Bird video backfilled (6 portraits + grids + 74 images) via authorized
   Drive download.
2. generate_with_reference poll budget was 120s; multi-ref grids take 2-4 min →
   silent 'returned None'. Budget now 450s. Misleading "$0.07 so far" log on failure
   still exists (bot.py increments cost before checking result) — minor, open.
3. Bird video storyboard now COMPLETE: 12 grids across 8 scenes (scene 4 was deleted
   by Ryan mid-debug; regenerated per-scene). Story still UNLOCKED — Ryan reviews
   boards → Lock → Create final pictures.

Guided UX (from 7-agent audit + synthesis, full report in workflow output):
- lib/next-action.ts: getNextAction() decision table → ONE plain-English next action
  per state (label, cost, tab, step N of 10).
- GuidedNextStep banner on the video page: big single CTA, live progress + Stop,
  PERSISTENT failure card with Try Again (replaces 6s toasts).
- Tabs renumbered 1·Research … 10·Results; storyboard tab buttons in plain English.

UX backlog (synthesis items not yet built): Advanced overflow menus per tab (hide
Reset/Skip/Upscale), disabled-button reason captions, per-segment failed badges with
"Fix missing pictures (N)", tab lock icons for not-ready tabs, cost-confirm pattern
for every >$0.50 action, stepper/pill unification via STATUS_LABELS. Full decision
table + per-tab hierarchy in the uiux-map workflow output.

## Handoff (2026-06-11 pt 2 — Drive consolidated under RAD Creations/Projects/Storyengine)

Everything now lives in ONE tree (Ryan's requested layout):
  Storyengine/<video title>/{characters/, storyboard/, images/} + scripts/voice/briefs in root.
- StoryEngine backend GOOGLE_DRIVE_FOLDER_ID redirected to the Storyengine folder
  (old value in storyengine/.env.bak-20260611). google_client folder lookups are now
  parent-scoped (global name search would have resurrected old folders / collided on
  generic subfolder names). Path routing: scene images + extracted panels -> images/,
  grids -> storyboard/, portraits -> characters/.
- Migrations executed (file ids unchanged, all stored URLs intact): both video folders
  moved + internally sorted; legacy 'StoryEngine Assets' uuid tree emptied + trashed;
  the legacy Power Doctrine pipeline's 'Economy Fastforward' folder moved WHOLESALE
  under Storyengine — its folder id is unchanged so the root .env and all existing
  links keep working without modification.
- Frontend renders Drive images via lh3.googleusercontent.com CDN (toDisplayImageUrl)
  since uc?export=download links don't load in <img> tags.

## Handoff (2026-06-11 — Creator Control Run shipped: Stop, Characters, Story Lock)

All three phases of docs/superpowers/specs/2026-06-10-creator-control-run.md are LIVE:
- Stop button on Visuals/Clips/Storyboard/Voice tabs; cooperative cancel keeps paid
  work, stage re-run resumes. Live-verified twice (grids stopped mid-run; a found
  cancel-eaten race + stale-clear race fixed and re-verified with a 3s cancel).
- Characters tab between Script and Storyboard: design cast → 6/6 portraits generated
  live for the bird video (Tom, Lisa, Mom, Dad, Dr. May, Baby Bird), approve gate
  blocks grids/images until approved (verified live), cast saved to project.
- Mandatory storyboard: storyboard_on_off defaults On, toggle replaced with REQUIRED
  badge, Lock Story (needs ≥1 reviewed grid) gates full image runs + extraction
  (both refusals verified live), unlock-story to iterate.
- Adversarial review pre-deploy: 11 claims refuted, 2 confirmed + fixed (cancel
  endpoint was blocked by the concurrent-job limiter; schema.sql missing
  video_characters RLS).

### Bird video state (f32ed182) — heads up
During live testing a cancel race let an image run complete: the video now sits at
ready_for_sound_design with 74 generated images (~$1.85, styled by the modeled
Pixar DNA — review them, they're likely usable). Cast is approved + saved to the
project; scene 1 has a storyboard grid; story is UNLOCKED. For a clean full-flow
test of the new gates, model a fresh video: script → Characters tab → approve →
grids → redo boards → Lock Story → Extract.

### Open items
1. Storyboard grid generation is not yet blocked AFTER lock (only images/extract are
   gated) — locking then regenerating boards is possible; unlock-to-iterate is the
   official path. Consider gating grids post-lock or auto-unlocking on grid regen.
2. Stale 'running' background_tasks rows accumulate when a task's terminal write
   misses (cleaned by recover_stale_tasks on restart) — they inflate the concurrent-
   job count between restarts.
3. voice_duration_seconds still not recorded in Kie voice mode (word-count fallback).
4. Characters tab does not auto-resume polling if the page reloads mid-design
   (background task continues; refresh shows the finished cast).

## Handoff (2026-06-10 pt 4 — voice via Kie + full click-path to ready_for_images)

Ryan: "voice uses kie as well." Shipped + verified live on the bird video (f32ed182):
- ElevenLabsClient Kie gateway mode: createTask/recordInfo jobs against
  elevenlabs/text-to-speech-multilingual-v2 (SoundClient pattern). Kie only accepts
  its OWN voice roster — off-roster ids rejected with "not within the range of
  allowed options"; falls back to "Mark" (1SM7GgM6IMuvQlz2BwM3) with a logged warning.
  Kie.ai is now the ONLY required pipeline key (anthropic + elevenlabs both optional).
- Voice click: 8/8 scenes voiced via Kie, audio in Drive. NOTE: voice_duration_seconds
  not recorded in Kie mode (engine falls back to word-count timing) — worth fixing.
- Prompts click first produced ZERO prompts: the modeled concept asset rows carry
  image_prompt values, so the engine's resume logic saw all scenes "completed."
  Fixed: full prompt runs on modeled videos clear generation_method='modeled' rows
  first (pack stays archived in original_dna). Re-run: 74 prompts across 8 scenes,
  ALL carrying the animation style (image_style_override active in the engine log).
- Current state: f32ed182 at ready_for_images with 74 styled prompts. Next click
  (Images) costs ~$1.85 kie credit + clips after — left for Ryan per cost rules.
- Watch items: prompts came out "2D animated illustration" (profile prefix blends
  with the 3D-Pixar override — consider selecting visual profile from the modeled
  DNA); story_bible column empty though the engine generated one in-run.
## Handoff (2026-06-10 pt 3 — replicate mode shipped + modeled script path)

Ryan's correction: Model A Video must REPLICATE the dropped-in video (same genre/
style/audience, sibling topic), NOT adapt it to his channel. Shipped + verified on
his video f32ed182 (ESL turtle reference fVdj037FNYI):
- Pack prompt rewritten to replicate-mode, channel profile removed, reference
  thumbnail attached as vision input. Result: "🐦😱 What Should We Do To Help The
  Injured Baby Bird? | Easy English Listening for Beginners (A2 Level)" + image DNA
  "3D Pixar/Disney CG animation style..." (observed from the thumbnail).
- New `script_dna` → `videos.script_system_prompt`; `pipeline_executor.run_script`
  branches for source='modeled' → `_run_modeled_script` (direct generation in the
  reference's style, 8 scene rows, documentary validation skipped). Verified: script
  opens "Look! A baby bird is on the ground. It cannot fly. What should we do?" —
  8 scenes, ready_for_voice.
- Click path verified end-to-end through script. Voice is next and needs Ryan's
  ElevenLabs key; then images/clips run on kie credit via existing buttons (the
  image prompts stage should honor image_style_override — NOT yet verified live,
  next test after voice).

## Handoff (2026-06-10 pt 2 — Kie-routed Claude + modeled click-through path)

Ryan's goal: paste link → modeled title/script/image DNA/video DNA → click through to a
similar finished video. Shipped and verified live on his video f32ed182 (tenant ee93e6d1):

- **All Claude calls via Kie.ai** (his directive). model_video routes kie-first; the
  PIPELINE bots too: `AnthropicClient` gateway mode via `ANTHROPIC_BASE_URL`
  (set by pipeline_executor when tenant has kie key but no anthropic key).
  Gateway traps found live: Bearer auth (SDK `auth_token`), Kie WAF blocks the SDK
  User-Agent (override it), dated model ids 422 (normalize to undated aliases),
  server-side web_search tools not executed (stripped in gateway mode), and **Kie 500s
  any non-streaming response taking >~110s — gateway mode must STREAM** (12/12 research
  calls failed non-streaming; identical call streams fine).
- **Modeled DNA steers downstream stages** via existing channels: writer_guidance
  (script), image_style_override (image prompts), thumbnail_style_override (thumbnail),
  video_motion_system_prompt (clip prompts). Pack prompt outputs explicit
  image_dna/motion_dna/thumbnail_dna. Full pack archived in original_dna (research
  stage overwrites research_payload by design). video_length_minutes now set from
  reference duration (script gen refuses to run without it).
- **Bug fixes en route:** psycopg2 UUID adapter registered in supabase_adapter
  (research save crashed: "can't adapt type 'UUID'"); rate limiter 429-storm fixed
  (read tenants.plan instead of accounts+trial → trial users got free-tier 15/min;
  also free floor now 60/min, both plan-name generations mapped).
- **Verified click-path on prod DB:** Model → idea+DNA ✓ → Research click (41KB
  payload, Kie-streamed, ~4min) ✓ → Script click (11.7KB script, editorial validation
  PASSED, ready_for_voice) ✓. Voice is the next click and needs Ryan's ElevenLabs key
  (BYOK) — that's where it correctly stops today.

### Open items
1. Ryan must add his ElevenLabs key (Settings → Keys) for voice; then images/clips run
   on his kie credit via existing buttons.
2. Script stage produced ONE scripts row holding the whole script (scene=1). Pre-existing
   script-stage behavior, not modeling-specific — verify voice/image stages handle it,
   or whether 6-scene splitting should happen here.
3. yt-dlp cookies support merged (PR #456): export YouTube cookies to
   ~/.config/storyengine/youtube_cookies.txt to unlock transcripts.
4. Other storyengine routes (learn-voice, suggest-titles, distiller) still anthropic-direct
   — task chip open ("Route all backend Claude calls through Kie.ai", partially done:
   pipeline bots + model_video covered).

## Handoff (2026-06-10 — Model A Video shipped)

### What shipped
"Model A Video" Dashboard feature: button → modal (one field: YouTube URL) →
`POST /api/model-video` creates a tenant-scoped video row at `idea_logged` and runs a
background task (extract via yt-dlp with oEmbed fallback → style-DNA distill via Haiku →
new modeled idea + prompt pack via Sonnet → persist). Pack lands in: videos fields
(title/headline, thesis, writer_guidance, title_candidates, thumbnail_prompt,
original_dna, research_payload incl. 8 scene_concepts + blockers), 8 `assets` rows
(image_prompt + video_prompt, generation_method='modeled'), `competitor_videos`
attribution upsert (our_video_id, modeled_at), best-effort Drive markdown brief.
Progress polled via existing `/api/pipeline/task/{video_id}` + `useTaskPoller`.
Retry endpoint: `POST /api/model-video/{video_id}/retry`. No migration needed.

### Verified
- Backend functional tests 6/6 (`tests/functional/test_model_video.py`), humanization suite still green
- `tsc --noEmit` clean, `npm run build` passes
- Live E2E on VPS against real DB (disposable test tenant, cleaned up): full happy path
  with mock Claude endpoint (ANTHROPIC_API_URL override), real oEmbed fallback (yt-dlp is
  bot-blocked on this VPS IP — see lessons), plan-limit 402 enforced, 401 unauthenticated,
  invalid-URL 400, missing-key actionable error
- Playwright UI E2E: button → modal → validation → failed state w/ Retry → modeled video
  visible in Pipeline list + detail page

### Known gaps / follow-ups
1. ~~No live-Claude run~~ RESOLVED same-day: Ryan clarified Claude calls go through
   Kie.ai. model_video now resolves creds kie-first (`https://api.kie.ai/claude/v1/messages`,
   Bearer auth, `stream:false` required, models claude-sonnet-4-5 / claude-haiku-4-5,
   beware 200-with-error-body) with direct-Anthropic fallback. NOTE: the rest of the
   backend (distiller, learn-voice, suggest-titles, pipeline executor) still hits
   api.anthropic.com directly with anthropic_api_key — aligning those to Kie is open work.
2. yt-dlp is bot-blocked on the VPS IP ("Sign in to confirm you're not a bot") — oEmbed
   fallback covers title/channel/thumbnail, but transcripts won't extract until cookies
   or a different egress is configured. Affects competitor scraping too, worth its own fix.
3. Videos whose modeling failed keep the "Modeling a reference video…" placeholder title
   in Pipeline; retry from the modal fixes them, but a retry affordance on the video card
   would be nicer.

## Handoff (2026-04-19 — Osiris full-autonomy overnight ship mode started)

### Context
Ryan granted full-autonomy ship-while-sleep mandate (see `~/.claude/projects/-Users-osiris-claude-agent/memory/project_storyengine_full_autonomy.md`). Single-agent (Osiris) continuous builder, Karpathy build-test-learn loop, functional tests only (no smoke-test ship gate). Daily ship log at `storyengine/daily-ship-log-YYYY-MM-DD.md`.

### Completed this cycle
- **Trial-downgrade cron (fix-roadmap 3.2)** — migration 041, `send_trial_expired` email, `check_trial_expired` task, `_auto_check_trial_expired` wired in lifespan @ 6h interval. Functional test in `backend/tests/functional/test_trial_expired.sql` green against prod Supabase.
- **Humanize error strings (frontend)** — 11 raw-error leak sites routed through `humanizeError()`. Pages: login, forgot-password, reset-password, settings/drive-callback, settings/youtube-callback, system-prompts, profile, competitors. Components: CreateVideoStep, FirstVideoFlow, storyboard-viewer. `npx tsc --noEmit` clean. Users no longer see "API error 500" or "Failed to fetch".
- **Flow B slice 1 — existing-channel detection** — new `GET /api/youtube/my-videos` endpoint fetches user's top uploads via OAuth + uploads-playlist pattern. Frontend `YouTubeConnectStep` auto-fetches + renders "We found N top-performing videos on your channel" card after OAuth succeeds. Backend functional tests (4/4 ✅) including live contract check against googleapis.com.
- **Flow B slice 2 — voice auto-learn** — new `POST /api/youtube/learn-voice` endpoint: top-5 videos → Claude Sonnet 4 voice summarization → persists `channel_profiles.style_description`. **Reordered onboarding steps** to `channel → keys → youtube → style → video` so voice-learn can pre-fill the Style step. `StyleSetupStep` shows "We drafted this from your top YouTube videos" banner when pre-filled. Backend functional test `test_learn_voice.py` (3/3 ✅) including LIVE 401 contract test against api.anthropic.com. `npx tsc --noEmit` clean.
- **Grandma-mode override audit + script bot wired (Cycle 6)** — Cycle 1's "wiring in 7 places" claim was wrong. `test_prompt_override_wiring.py` (3 tests ✅) audits via runtime + static grep. Found 1/6 bots reading their override (video_motion only). Wired the `script` bot end-to-end: `script_generator.py` (`system_prompt_override` param → `anthropic_client.generate(system_prompt=...)`) + `brief_translator/__init__.py` (both `BriefTranslator.__init__` and `translate_brief` convenience func) + `script/run.py` (passes `getattr(pipeline, "script_system_prompt", None)`). 2/6 wired after Cycle 6.
- **All 6 bots wired (Cycle 7)** — completed the grandma-mode rollout. Thumbnail bot (3 Claude call sites via `ThumbnailTitleEngine` → `TitleGenerator` + `ThumbnailPromptBuilder`, wired in `thumbnail/run.py`). Sound bots (`SoundPromptBot` now takes both `sound_curation_` and `sound_generation_` overrides, wired in `sound/run_design.py`). Research bot (`ResearchAgent` + `run_research` take override, wired at SaaS executor boundary `pipeline_executor.py:run_research`). Audit test broadened regex to match `self._pipeline.<attr>`; CONSUMER_SPEC updated. **6/6 WIRED** with a full-loop regression guard asserting all 6 stay wired.
- **Backend error humanization (Cycle 8)** — new `storyengine/backend/error_utils.py` with `humanize_error(err, context=...)` mirror of frontend `src/lib/errors.ts`. Fixed 11 HTTPException leak sites across 6 customer-facing routes (visual_styles.py × 5, intelligence.py × 1, pipeline.py × 1, system_prompts.py × 1, youtube_channel.py × 1, videos.py × 1). Raw `str(e)` / upstream-API bodies no longer reach users; all get logged at WARNING with `[humanize_error]` prefix for dev grep. Functional test `test_error_humanization.py` (8/8 ✅) including static audit regex-scan that asserts 0 raw-error leaks across all 6 customer-facing route files — acts as a regression guard for any new route added later.
- **Background-task error humanization (Cycle 9)** — closed the leak surface flagged as Cycle 8's honest gap. `_set_task_status` in `routes/pipeline.py` now humanizes at the write boundary, covering all ~15 `str(e)` call sites in one change. `routes/agents.py` agent-pipeline run uses `humanize_error(e, context="The agent pipeline hit an error")` at both the in-memory `_set_task` and the `bot_activity` INSERT. Runtime test `test_set_task_status_humanizes_failure_errors` (via FastAPI-free module stubs) proves a raw `HTTPSConnectionPool(host='api.kie.ai'...)` input never leaks into `_running_tasks['error']`. Full suite: 9/9 green. Prompt-override wiring test still 6/6 WIRED.
- **Activity-feed humanization (Cycle 10)** — uncovered a third independent leak surface: `pipeline_executor._log_activity` writes `message` to `bot_activity` which `/api/activity` returns verbatim to the UI. ~20 call sites in `pipeline_executor.py` pass `error_msg = str(e)`. Fixed with a single-line funnel guard inside `_log_activity` (`humanize_error(message)` when status=="failed"). Also fixed `/orchestrator/decide` returning `reasoning=f"Orchestrator error: {e}"`. Static-grep test added. 10/10 tests green.
- **Orchestrator result humanization (Cycle 11)** — closed the 4th and last leak funnel flagged in Cycle 10's honest gap. `claude_orchestrator.ClaudeOrchestrator.execute` previously built `OrchestratorResult(error=str(e))` on exception; now runs through `humanize_error(e, context=f"Executing {decision.skill_id} hit an error")` so `/orchestrator/execute` callers never see raw stack text. 10/10 tests still green. Four leak surfaces, four cycles, one helper, zero API growth.
- **Transcript-based voice-learn (Cycle 12)** — upgraded `/api/youtube/learn-voice` (Flow B slice 2) from titles+descriptions to actual yt-dlp transcripts. New `_fetch_transcripts_for_videos` helper runs 5 concurrent yt-dlp fetches via `asyncio.gather(run_in_executor(...))` reusing `routes.niche._extract_video_info`. Silent per-video fallback (transcript → description → `(no description)`). `TRANSCRIPT_CHAR_CAP=2000` bounds per-video context cost. Response surface adds `transcript_count` + `has_transcript` per video so frontend can show signal strength. 4 new tests (mixed prompt path, silent-fail, char-cap, template-mentions-transcripts) + 3 existing = 7/7 green in `test_learn_voice.py`. Regression suites still clean (10/10 humanize, 6/6 override-wired).
- **UI signal-strength banner (Cycle 13)** — surfaced `transcript_count` from Cycle 12 into `StyleSetupStep.tsx` with three-state copy: "learned from N transcripts (+M descriptions)" / "learned from N descriptions — add captions for sharper voice learning" / generic fallback. `api.ts` + `onboarding/page.tsx` types+state plumbing. `npx tsc --noEmit` clean.
- **Prod deploy of Cycles 8-13 (Cycle 14)** — Ryan granted SSH to VPS (clawd@76.13.119.181). Stashed dirty runtime artifacts on `~/projects/economy-fastforward`, `git pull origin main` (19 commits behind), `pip install -q`, `npm install && npm run build`, `sudo systemctl restart` both services. Migration 041 auto-applied. storyengine.dev `/` + `/api/health` + `/onboarding` all 200. Ran both functional suites against live VPS env: `test_error_humanization.py` 10/10, `test_learn_voice.py` 7/7. First time tonight's work reached production.
- **Runtime E2E activity-feed audit (Cycle 15)** — `tests/functional/test_activity_feed_no_raw_errors.py`: two passive scans against live prod DB (`bot_activity.message` + `background_tasks.error_message` for 16 raw-exception signatures — HTTPSConnectionPool, Traceback, Errno, 6 Python exception types, 3 upstream API hostnames, Connection aborted/refused/reset) + a helper-pattern pin that guards against adding a pattern to the catalog the helper can't strip. 3/3 green on VPS: 87 failed bot_activity rows + 1 failed background_task scanned, zero leaks. Closes the "needs a live backend" honest-gap flagged in Cycles 8-11.
- **Kie.ai validator hotfix (live customer bug)** — Ryan hit "Saved but validation failed" on the TOOLS onboarding step. Root cause: `vault.test_api_key` called `api.kie.ai/api/v1/user/balance` which 404s (deprecated endpoint) AND Kie.ai uses the 200-OK-with-error-body pattern, so checking HTTP status alone would still be wrong. Fixed by switching to `/api/v1/chat/credit` + parsing `{code, msg, data}` body. Ryan's key was valid all along (4335.86 credit). Shipped as commit `a61a4d2e`, pulled+restarted on VPS, verified `test_api_key` returns `{'success': True, 'message': 'Kie.ai API key valid (credit: 4335.86)'}`. 35-min turnaround screenshot→fix-live.
- **ElevenLabs validator hotfix (Ryan 2nd report)** — Same bug class. `/v1/user` requires the `user_read` scope which Ryan's TTS-only key doesn't have. Fixed by switching to `/v1/voices` (the endpoint StoryEngine actually calls for voice-picker population) + parsed the 401 body to distinguish `invalid_api_key` from `missing_permissions` for an actionable error message. Shipped as commit `bfcc9b46`. Verified green on VPS. Principle: validate against endpoints we actually use, not "hello world" endpoints.
- **TOOLS step UI fix (Cycle 17)** — Ryan's "4 keys but only 3 to enter, no Continue button" report. ElevenLabs groups two backend keys into one visual card, but the progress counter/disabled gate was counting raw keys. Switched to provider-count semantics (`renderItems.length`, `every(configured)` per grouped provider). `ApiKeysStep.tsx` commit `946ea7aa`, shipped, browser-verified live — counter reads "2 of 3 connected" and button reads "Connect all 3 tools to continue" with coherent state.
- **Dashboard WelcomeQuest — the "huge win" (Cycle 18)** — closed the "no onboarding after keys" gap. New `components/dashboard/welcome-quest.tsx` renders a three-step quest panel (add competitors → distill first insight → create first video) above the dashboard's analytics widgets, visible only while `video_count === 0`, dismissible with localStorage persistence. Backend added a `first_run: {competitor_count, distilled_count, video_count}` block to `/api/dashboard/onboarding/status`. Commit `68b9ee9d`, both services restarted on VPS, browser-verified live with all three cards rendering "0 of 3 done" on a fresh account.
- **Intelligence-teaser strategy memo (Task #24)** — Ryan's "do we let them run a free pass to get hooked?" question. Wrote a strategy memo at `storyengine/notes/intelligence-teaser-strategy-2026-04-19.md`. Recommendation: don't build the StoryEngine-funded teaser yet. BYOK already gives us a near-free hook (user's own credits cost pennies, $0 to us). First ship the UX changes shipped tonight + add event tracking, measure dropoff for two weeks, THEN decide whether to spend engineering on a funded teaser targeted at the specific dropoff point.

### Next in queue (priority order)
1. First real end-to-end customer-style render (Ryan as dogfood) — proves live output variation between two overrides end-to-end. Task #11.
2. **Audit the other `test_api_key` branches for the 200-OK-with-error-body pattern** — Anthropic, OpenAI, Gemini, ElevenLabs, Tavily all check HTTP status only. Same bug class would hit all of them if any provider silently moves to 200+JSON-code style.
3. **Synthetic canary for upstream-validator drift** — hourly cron hits `test_api_key` against known-good keys for each provider, pages on regression. Catches endpoint deprecation (like the Kie.ai one) before users see "validation failed."
4. Live yt-dlp stability test against a stable public YouTube URL (catches version drift + YouTube anti-scrape changes).
5. Fresh fix-roadmap.md rewrite against ground truth (drop items already shipped).
6. Clean-replacement override semantics — when an override is present, also strip the profile-derived voice preamble from the user-prompt body. (Current v1: override lands as `system_prompt`, preamble still in user body → Claude blends.)
7. Hourly launchd/cron wrap of Cycle 15's audit — continuous surveillance instead of ad-hoc runs.
8. Bump pydantic + pyjwt to satisfy supabase lib requirements (noted as non-fatal warnings during Cycle 14 deploy).

### Open questions for Ryan
- **Override replacement semantics:** currently the tenant override lands as Claude's `system_prompt` while the profile-derived voice preamble still lives in the user-prompt body → Claude blends the two. Clean-replacement (skip profile preamble when override present) is a follow-up decision once we measure output variation end-to-end.
- **Python-layer test harness:** backend expects local PG proxy on :55432 that isn't running on this Mac. For functional Python tests (not just SQL), either start the proxy or write tests as VPS-executable scripts.

## Handoff (2026-04-14 — PRD 3 T5 Storage + Bug Triage)

### Completed
- PRD 3 T5: Extended `storyengine/backend/storage.py` with Supabase Storage backend
  - `STORAGE_BACKEND` env var: "google_drive" (default) or "supabase"
  - Per-tenant path isolation: `{tenant_id}/{video_id}/{filename}`
  - `create_signed_url()` for time-limited access
  - All 4 acceptance criteria pass
- Investigated 5 live user errors: all routes work, errors were transient

### Next
- T12 (QA): Storage isolation verification — ready for qa-engineer
- T13 (Security): Final infrastructure audit — deps now met (T5 done)
- Consider updating `pipeline_executor.py` and `extraction.py` callers to pass `tenant_id` when `STORAGE_BACKEND=supabase`

---

## Handoff (2026-04-11 — Autopilot Intelligence + Second-Order Distillation)

### Phase 5: Intelligence Advisor (DONE)
- `storyengine/backend/distillation/advisor.py` (NEW) — IntelligenceAdvisor class
  - Queries content_intelligence aggregates for best-performing patterns
  - Returns: best hook type, thumbnail style, title structure, publish timing, top topics
  - `to_prompt_context()` formats for Claude prompt injection
  - `to_dict()` serializes for API response
  - Parallel async queries, confidence = min(1.0, sample_size / 50)
- Wired into `routes/autopilot.py` — Intelligence scoring now matches candidate DNA against niche recommendations
  - Candidates with matching hook_type get +15, title_structure +10, topics +10
  - Candidates query LEFT JOINs content_intelligence for hook_type, title_structure, topic_tags
  - New `GET /api/autopilot/recommendations` endpoint for dashboard
- Wired into `routes/discovery.py` — `_get_learnings_context()` now includes niche intelligence recommendations section

### Phase 6: Auto-Distillation + Meta-Analysis (DONE)
- `_auto_distill_intelligence()` background task in main.py (12h cycle, 25 videos/batch)
- `_auto_generate_meta_insights()` background task in main.py (24h cycle)
- `storyengine/backend/distillation/meta_analyzer.py` (NEW) — Second-order distillation
  - Gathers 10+ aggregated pattern queries (hooks, titles, thumbnails, topics, timing, controversy, tones, viral videos)
  - Sends to Claude Haiku for meta-analysis
  - Extracts: top_patterns, combination_insights, timing_strategy, contrarian_findings, niche_signature
  - Stores in `niche_meta_insights` table (upserted per tenant)
- `storyengine/backend/migrations/040_niche_meta_insights.sql` (NEW) — niche_meta_insights table
- `routes/intelligence.py` — 3 new endpoints:
  - `GET /api/intelligence/recommendations` — advisor recommendations
  - `GET /api/intelligence/meta-insights` — latest meta-analysis report
  - `POST /api/intelligence/meta-insights/generate` — trigger meta-analysis

### Phase 7: Frontend Dashboard (DONE)
- `api.ts`: New types + API functions (IntelligenceRecommendations, NicheMetaInsights, 4 new fetch functions)
- `analytics/page.tsx`: Two new panels in Niche Intelligence section:
  - **AI Recommendations** — 4-card grid: Best Hook, Best Title Structure, Best Thumbnail, Best Timing + top topics
  - **Niche Meta-Analysis** — Claude-generated report with top patterns, contrarian findings, winning combinations
  - Generate button for meta-analysis when 20+ videos distilled

### What's next:
1. **Deploy**: Restart backend to auto-apply migrations 036-040 + start background tasks
2. **Trigger backfill**: `POST /api/intelligence/backfill?batch_size=50` (or wait 12h for auto-distillation)
3. **Trigger meta-analysis**: `POST /api/intelligence/meta-insights/generate` (or wait 24h)
4. Extend distillation to video_scripts, research_payloads, agent_paper_trails
5. Add GCS archival for raw transcripts after distillation
6. Autopilot auto-launch: use recommendations to auto-select which discovery idea to launch

**Design decisions:** See `tasks/decisions.md` — ADR 2026-04-11

### Previous: Phases 1-4 (Content Intelligence Full Stack) — DONE
- Backend distillation pipeline (Haiku + Gemini Vision + OpenAI embeddings)
- 10 intelligence API endpoints + frontend UI
- Intelligence-driven scoring in autopilot + discovery

---

## Active Work

**Execution Plan:** `tasks/roadmap.md` — 18-day SaaS transformation
**Current PRD:** PRD 3 — Infrastructure (Security, Rate Limiting, Task Persistence, Logging, Health Check)
**Agent Team:** 6 agents on Opus. PRD 2 mostly complete (11/13). PRD 4 complete (15/15).

### PRD 3 Progress
- [x] **Task 1** (SEC-1, SEC-2, SEC-3): Already done by agent team — verified
- [x] **Task 2** (SEC-4, SEC-5, SEC-6): SEC-4/SEC-6 already done. SEC-5 safety comments added to all 12 f-string SQL queries
- [x] **Task 3**: Rate limiting middleware (`rate_limit.py`) — per-plan token bucket, concurrent job limits
- [x] **Task 4**: Persistent background tasks — migration 032, `_db_persist_task()` fire-and-forget, `recover_stale_tasks()` on startup
- [ ] **Task 5**: Per-tenant storage — DEFERRED (users will connect own Google Drives, not Supabase Storage)
- [x] **Task 6**: Structured JSON logging (`logging_config.py`) — all `print()` in main.py replaced with `logger.*`
- [x] **Task 7**: Health check expansion — `/api/health` checks DB + active tasks, `/api/health/detailed` with token auth
- [ ] **Task 8**: QA security verification (depends on Tasks 1-2)
- [ ] **Task 9**: QA infrastructure verification (depends on Tasks 3-7)
- [ ] **Task 10**: Frontend health status indicator (depends on Task 7)
- [ ] **Task 11**: Security final audit (depends on all tasks)

## Handoff (2026-04-10 — PRD 3 Phase 1+2 Build)

**What was built:**
- `storyengine/backend/rate_limit.py` (NEW) — Token bucket rate limiter per plan (free: 15/min, starter: 30, creator: 100, studio: 300). Concurrent pipeline job limits. Skips health/auth paths.
- `storyengine/backend/logging_config.py` (NEW) — StructuredFormatter (JSON), RequestLoggingMiddleware, error rate tracking (10/5min threshold)
- `storyengine/backend/migrations/032_background_tasks.sql` (NEW) — Persistent task tracking table with RLS
- `storyengine/backend/routes/pipeline.py` — Added `_db_persist_task()` (fire-and-forget DB writes on key transitions), `recover_stale_tasks()` (startup recovery). 61 `_set_task_status` calls now pass `tenant_id=tenant_id` for DB persistence.
- `storyengine/backend/main.py` — Wired RateLimitMiddleware + RequestLoggingMiddleware. Replaced ALL 18 `print()` with `logger.*`. Added startup task recovery. Expanded `/api/health` + new `/api/health/detailed`.
- `storyengine/schema.sql` — Added background_tasks table definition
- 10 route files — Added SEC-5 SECURITY comments to all f-string SQL queries

**Design decisions:**
- Task tracking is dual-layer: in-memory dict for real-time progress (sync-compatible with progress callbacks), DB for persistence/history. Fire-and-forget via `asyncio.create_task()`.
- Task 5 (per-tenant Supabase Storage) deferred — user wants BYOD Google Drive model.
- Rate limiting is in-memory (resets on restart) — acceptable for v1 since it's protective not billing-critical.

**What's next (Phase 3):**
- Tasks 8-9: QA verification of security + infrastructure
- Task 10: Frontend health status indicator component
- Task 11: Final security audit
- Deploy to VPS and verify migration 032 runs

**Previous:** PRD2 T1-T11 verified. PRD 4 complete (15/15).

**PRD 2 status:** 11/13 done. T12 (QA Playwright regression) and T13 (already done by qa-engineer) are the only remaining items. T12 dependencies now all met.

**PRD 4 COMPLETE** — All 15/15 tasks done.

**Still open:** 3 SEC bugs in task queue (SEC-SSE-001 cross-tenant SSE, SEC-EMAIL-001 HTML injection, SEC-KEYS-001 exception leak). These are for backend-dev.

Previous handoff (PRD 2):
All 7 PRD 2 backend tasks are committed and passing acceptance criteria:
- Task 1: Migration 029 (trial_warning_sent column)
- Task 2: Query-param token auth in auth.py for SSE connections
- Task 3: SSE stage_change events (already existed)
- Task 4: POST /keys/validate bulk API key testing with timeout
- Task 5: email_service.py shared email module + email.py stub
- Task 6: Billing receipt email on checkout (already wired)
- Task 7: email_tasks.py trial warning system (already created)
Frontend tasks 8-12 are now unblocked. Task queue is empty.

### What Shipped Today (2026-04-08)
- Billing page (`/billing`) with plan comparison, usage bars, Stripe integration
- Critical Bug Fixes PRD: all 14 tasks (6 backend, 6 frontend, 1 QA, 1 security)
- Competitors page refactored (server-side pagination, filters, sort, scrape progress)
- Error boundaries + 404 page
- Toast notification system (replaced 81 alert() calls)
- System prompt editors on pipeline tabs
- Trial countdown badge + banner
- REG24 regression sweep: 24/24 pages, 33/33 API, 9/9 tabs — 0 bugs
- UX Polish PRD backend tasks: render_minutes tracking, suggest-titles endpoint, welcome email

### Next Up (from roadmap Day 3-5)
- [ ] Plan enforcement: `tenant_usage` table, `check_plan_limits()` middleware, usage hooks
- [ ] Free trial logic: 14-day Creator trial on signup, countdown, downgrade-on-expiry
- [ ] Password reset flow: token table, email (Resend), `/reset-password` page
- [ ] Disable dev-token in production mode
- [x] Create video simplification: POST /api/videos/suggest-titles endpoint built
- [ ] Frontend: wire suggest-titles into create video flow (PRD Task 8)

---

## Blocked / Pending

### Storyboard Extraction V2 (from 2026-04-04)
- **T27-003**: Rewrite storyboard-extract endpoint for Supabase
  - Wire `extraction.py` into `pipeline_executor.py` (currently silently does nothing for Supabase videos)
  - Read grid URLs from `scripts` table → call `extract_grid()` → update `assets.image_url`
  - Grid layout is 3x2 (6 panels per grid), NOT 3x3
  - Test video: f9749bd2 ("Drones"), 6 scenes
- **T27-004/005/008**: Permanent storage for all image gen steps (Supabase Storage)

### Security Issues (from Critical Bug Fixes PRD)
- SEC-1 (CRITICAL): dev-token bypasses all auth in dev mode
- SEC-2 (HIGH): get_scene_audio skips tenant check
- SEC-3 (HIGH): API keys revealed without rate limiting
- SEC-4 (HIGH): Hardcoded IP in CORS allowlist
- SEC-5 (MEDIUM): Dynamic SQL via f-strings
- SEC-6 (MEDIUM): No audit logging for key management

### Rubric / Agent Team Improvements
- [x] Cron health audit: crons.json synced with setCadence, security-auditor wired, health checks fixed
- [x] Cadence buttons: all 6 tiers (light/normal/fast/max/turbo/ultra) now sync crontab + crons.json + UI labels
- [x] Feature 1: Concurrency guard — PID lock file + stale lock cleanup in run-agent.sh
- [x] Feature 2: Run timeout — `timeout` command wrapping Claude CLI (30min default)
- [x] Feature 3: Duration + cost tracking — timing, cost heuristic, model in activity log
- [x] Feature 4: Log viewer — `/api/logs` + `/api/logs/:agent` endpoints, dashboard modal with auto-refresh
- [x] Feature 5: Crons-controls sync — grayed out paused/OFF jobs, "Team OFF" badges
- [x] Feature 6: Runtime visualization — `/api/run-history` endpoint, calendar overlay (green/red/amber bars), Scheduled/Actual/Both toggle
- [x] Feature 7: Dashboard notifications — toast alerts polling activity log, auto-dismiss
- [x] Feature 8: Cost summary panel — `/api/cost-summary` endpoint, 24h/7d/30d cards + per-agent bar chart
- Command Center: Master ON/OFF toggle, clear queue button, task counter reset
- Activity feed: auto-scroll, WebSocket for real-time, collapse old entries
- Playwright auth fix: 13/20 QA tests skip (need shared auth intercept fixture)

---

## Latest Handoff (2026-04-08)

**What completed (PRD 2 backend):**
- Task 1: Migration 029 (trial_warning_sent column) — already existed
- Task 2: Query-param token auth for SSE — already existed
- Task 3: SSE stage_change events in /api/activity/stream — NEW: polls stage_transitions table, emits `event: stage_change` alongside `event: activity`
- Task 4: POST /api/settings/keys/validate — already existed
- Task 5: email_service.py extracted from google_auth.py — already existed (named email_service.py not email.py to avoid stdlib shadow)
- Task 6: Billing receipt email on checkout.session.completed — NEW: sends receipt via email_service after Stripe checkout
- Task 7: email_tasks.py with check_trial_warnings() — NEW: finds accounts with trial expiring in 3 days, sends warning, sets trial_warning_sent flag

**Frontend tasks UNBLOCKED:** 8, 9, 12 (depend on task 3), 11 (depends on task 4)
**QA task 14** depends on all other tasks

**Key context for next session:**
- `tasks/roadmap.md` has the full 18-day plan with daily deliverables
- `tasks/decisions.md` has settled architectural choices (10 ADRs)
- email_tasks.py needs to be wired into a background loop in main.py lifespan (not done yet — task 7 only creates the module)

Previous handoffs archived in `tasks/archive/handoffs-2026-03-to-04.md`

## Handoff (2026-04-10 — QA verification + security audit)
PRD2 Pipeline UX: 12/14 done+verified. T12 (full regression) blocked on T3/T4/T7/T10.
- BUG-USER-800807 confirmed fixed (380178b) — backend returns "Invalid or expired session", frontend suppresses auth 401s from RUBRIC
- T9 verified: trial warning wired in main.py lifespan (12h interval), email_tasks.py + migration 029 present
- T2 verified: SSE hook matches backend event shapes exactly (stage_change + task_progress), tsc clean
- T13 security audit DONE — filed 3 bugs for backend-dev:
  - SEC-SSE-001 HIGH: _running_tasks dict at pipeline.py:51 has no tenant scoping — cross-tenant leak via SSE stream
  - SEC-EMAIL-001 HIGH: email_service.py:59,110 — display_name not html.escape()'d in email templates
  - SEC-KEYS-001 MEDIUM: vault.py:326 Gemini key in URL + vault.py:356/settings.py:231 leak exception details
- Remaining: T3 (PipelineStepper), T4 (wire stepper), T7 (key validation UI), T10 (notification provider) for frontend-dev
- T12 (full QA regression) depends on all of the above

## Handoff (2026-04-10)
- PRD 2 (Pipeline UX) is active with 13 tasks, agents executing
- Fixed: ANTHROPIC_API_KEY leak ($64/day), stale progress.md, RUBRIC PRD display, agent coordination
- RUBRIC layout: two-column (queue + activity feed), tasks labeled by PRD
- Agents use OAuth now (no API key charges)
- Monitor: check cost page Apr 11 to confirm $0 API charges

## Handoff (2026-06-08 — pipeline import repair + Youtuber agent)
- **Fixed:** 5 stale shim-name imports left by 17b03be0 — pipeline now imports cleanly again (orchestrator.pipeline + all 5 touched entrypoints verified). Branch `claude/repair-pipeline-imports`. Done in an isolated git worktree (~/yt-repair) to avoid the storyengine dev-swarm's git stash/checkout/reset on the shared tree.
- **Not done / next:** smoke test was import-only (no paid run). Before relying on production: run a single-video dry pass, and reinstall the setup_cron.sh production jobs (queue/discover/autopilot) — they are NOT in the live crontab (only storyengine/agents swarm + bot_healthcheck).
- **Separate effort:** standing up a new Hermes agent profile `Youtuber` (~/.hermes/profiles/youtuber) as the YouTube production brain that drives this pipeline; multi-channel generalization planned (ChannelConfig). See ~/Desktop/Power_Doctrine Pipeline-main-integration/HERMES_REBUILD_PLAN.md.
- **Caution:** `/home/clawd/pipeline-bot/venv` (referenced by infra detect_python) does not exist; live fallback is repo-root `economy-fastforward/venv`.

## Handoff (2026-06-08 — neuter Slack for customer-facing bot)
- SlackClient no longer raises without a token; degrades to a silent no-op (enabled flag + guarded API methods). Verified: no-token instantiation + all notify_* return None, no exceptions.
- Paired with blanking SLACK_BOT_TOKEN/SLACK_APP_TOKEN in the VPS .env (gitignored) so the pipeline posts nothing to Slack. The legacy Slack listener (pipeline_control.py) is already stopped + its healthcheck cron disabled.
- Context: pipeline is being driven by the new Telegram bot @YoutubeAGI_bot (Hermes profile 'youtuber'); Slack is being retired.

## Handoff (2026-06-08 — multi-tenant ChannelConfig foundation)
- DONE: dedicated free Supabase project `youtuber` + multi-tenant schema (creators/channels/channel_config/drive_connections/videos/competitors/video_metrics, RLS on). `shared/channels/` ChannelConfig loader. Threaded into VideoPipeline + --channel flag. Verified: default-equivalent for economy_fastforward + distinct config loads for a second channel.
- NEXT: (1) per-creator Google Drive OAuth connect flow (needs a hosted OAuth callback for the Telegram UX — design decision). (2) Supabase-backed status machine so state_store='supabase' channels actually produce (videos table read/write path; today only config is multi-tenant, EFF still on Airtable). (3) wire onboarding to auto-create a creator's ChannelConfig.
- Secrets: YOUTUBER_DB_URL in VPS .env (gitignored). psycopg2-binary added to requirements.

## Handoff (2026-06-10 — yt-dlp YouTube bot-check investigation)
- DONE: confirmed VPS IP is hard-flagged by YouTube (all player clients, latest yt-dlp, PO-token provider, youtube-transcript-api all blocked — see lessons.md). Wired `YTDLP_COOKIES_FILE` + `YTDLP_PROXY` env support into routes/niche.py (`_ytdlp_antibot_opts()`); verified wiring + graceful degradation + flat-listing/oEmbed regression on real videos. Branch `claude/ytdlp-bot-check-fix`.
- ACTION NEEDED (Ryan): export YouTube cookies from a logged-in browser (Get cookies.txt extension, Netscape format), upload to the VPS (e.g. /home/clawd/.config/storyengine/youtube_cookies.txt), add `YTDLP_COOKIES_FILE=<path>` to storyengine/backend/.env, restart backend + worker. Use a throwaway/secondary Google account — YouTube can flag accounts used for scraping. Alternative: set `YTDLP_PROXY` to a residential proxy.
- After cookies/proxy are in place, re-verify: `_extract_video_info("PHe0bXAIuk0")` returns title + transcript, then check Model A Video extract, competitor scrape, voice-learn.

## Handoff (2026-06-22 — character consistency: GPT Image 2 scene images + coverage)
- DONE: GPT Image 2 is the character-lock scene-image path (`image_client.generate_scene_image_gpt`, always-available scene model). Coverage-frames-to-app store path (`scripts/coverage_to_app.py`) + pipeline route wiring + Characters / Scenes workspace UI. Committed here after being found running-but-uncommitted on the VPS.
- ALSO shipped today (separate effort): the YouTube intelligence ruleset is live - but/therefore + a 15-second hook rule in the script engine, a retention grader gate (`grade_script_with_client` routes via the tenant's `AnthropicClient` so it covers Kie-gateway tenants too), an idea scorer in chat, and a format-aware script engine that auto-applies story craft vs teaching craft per niche (verified live: ESL teaches, true-crime tells a story). See `storyengine/YOUTUBE-INTELLIGENCE-RULESET.md`.
- NEXT: the character-consistency / coverage UI may still be mid-iteration (the session was actively editing `pipeline.py` when this was committed) - verify a real coverage run end to end. The format-aware engine supersedes `tasks/engine-identity-seeds/faceless-story.md` for auto-handling channel types.

## Handoff (2026-07-12 - DVsU single-machine script proof)
- SUPERSEDED by the 2026-07-13 Anton schema-v3 handoff at the top of this file.
- The four-beat problem/decision/tradeoff/outcome sentence compiler and deterministic extractive fallback are intentionally retired for DVsU machine previews.
- Current next step remains: deploy the Anton slot + claim-map pipeline, then rerun only the XB-15 `machine-script-preview` endpoint and review the saved paragraph before touching Machine 2.

## Handoff (2026-07-13 - First DVsU machine pass UI lock)
- XB-15 is the first single-machine research + script preview pass. Keep the workflow scoped to one selected machine until the operator approves moving forward.
- Superseded UI rule: Research must show saved machine research cards and exact evidence only. Script output belongs in the Script phase, where the selected machine action writes/saves the real script block.
- Required Anton slots include `memorable_fact`; if verified one-machine research cannot source a memorable fact that supports the engineering story, the preview should fail for formula adjustment instead of producing a generic catalog paragraph.

## Handoff (2026-07-13 - DVsU selected-machine script blocks)
- Script phase should generate one selected machine at a time as a real script block, not as a Research preview.
- The selected-machine script action saves a validated paragraph into that machine's `scripts` row, updates `script_validation.script_hold`, and leaves the full roster untouched.
- Next: run Machine 2 from Script after reviewing its saved research card; do not run Machine 3 or a full roster script until Machine 2 passes.

## Handoff (2026-07-24 — Custom Film Remotion showcase)

- COMPLETE locally: reusable Remotion finishing manifest/adapter, nine motion primitives,
  exact 300-second synthetic master, creative/audio/caption/crop inspection, fallback and
  artifact-boundary tests, and Ryan's centered Evidence Board correction.
- Playable master: `remotion-video/out/full-showcase-proof/master-a.mp4` (SHA-256
  `60bb164707194ddc46b2e5f15b6691795337cd6fcb51e574142cd8f29d5175fd`).
- Next decision: creative changes, or request a refreshed exact BYOK quote <= $15.
  Paid flagship footage, push, deploy, migration, upload, and release remain unapproved.
