# Live Verification Queue

**Why this exists:** the build loop runs in an isolated sandbox with **no Kie/image-service key and no route to the production VPS** (HTTPS-proxy-only network, no SSH). So any `[V]` step that needs a real paid API call or the running prod backend can't execute here — it's verified at **test + code-trace** level in the sandbox and the live confirmation is deferred to this list. Nothing is skipped; it's parked with an exact recipe.

**Who runs these:** Ryan in the app (a tap-through is enough for most), or a VPS-capable session. Tick an item once its evidence is captured. Add new rows here whenever a chunk's `[V]` can only be partially done in-sandbox — same commit as the chunk.

**Safety context:** every deferred item below already has (a) the default/no-op path proven unchanged by tests, and (b) a fallback or bypass so a live failure degrades gracefully rather than breaking prod. These live checks are *confirmation*, not load-bearing gates.

---

## ⚡ WHEN YOU'RE AT THE COMPUTER / VPS RUN — do these first (Ryan)

1. **💰 Confirm the Veo 3.1 price (the one real money unknown).** Public pages conflict: Veo 3.1 Fast = **$0.40 or $0.30**, Veo 3.1 Quality = **$2.00 or $1.25** per 8s clip — and Veo Quality is by far the priciest model, so getting it right matters most. Generate ONE Veo clip on a test video, then read the Kie dashboard's credit-consumption log for that task (credits × $0.005 = the true price). Update `CLIP_PRICE_BY_MODEL`/`MODEL_REGISTRY.cost_per_clip` for veo-3.1-fast/quality in `skills/video-pipeline/shared/channel_profile.py`. Same one-clip-and-read for **Grok Imagine**, **Kling 3.0 Pro**, **Runway Gen-4 Turbo** if you wire them (details in §C09 below).
2. **🎙️ Confirm the ElevenLabs voice rate.** The ledger meters voice by REAL character count (accurate) but at an UNCONFIRMED **$0.30/1,000 chars** — ElevenLabs bills by a monthly character allowance tied to your plan, doesn't return a per-call cost, and it's your own (BYOK) key, so the true effective rate is per-account. Generate one voiceover, note the character count the ledger recorded (`se db "SELECT units, actual_cost FROM generation_ledger WHERE stage='voice' ORDER BY created_at DESC LIMIT 1"`), then check your ElevenLabs dashboard/usage for that account's real $/1,000-chars (or overage rate) and update `VOICE_PRICE_PER_1K_CHARS` in `skills/video-pipeline/shared/channel_profile.py` if it differs.
3. **🧾 One cheap picture-gen tests the WHOLE cost chain at once.** Generating a single scene's pictures (~$0.05–0.30) lights up C07-style ledger writes AND C08 image pricing AND C10's Est→Actual chip/drawer in one shot — do it on a test video and walk §C07/§C08/§C10 together instead of separately.
4. Everything else below is read-only or a light tap-through — knock them out while the account is already being spent.

---

## C12 — per-scene model router + `routed_model`/`routing_reason` at shot-plan time · live build check
Checklist §1.2 (P1.2a slice). New `shared/model_router.py` (data-driven
lookup over C11's `MODEL_REGISTRY.best_for`/`tier`/`wired`) is called from
`storyboard/coverage.py`'s `plan_camera_moves()` — BEFORE frames are drawn
— and the recommendation rides the shot dict through
`generate_coverage_frames()` into `coverage_to_app.py`'s `store_scene()`,
which persists `routed_model`/`routing_reason` onto the `assets` row
(migration 088, confirmed live via `information_schema.columns` on project
`wrromlupsmyzrrcqlucn` — all 3 new columns exist, nullable TEXT, no
default). `model_used` (C13's column) is deliberately never written by this
path. Proven in-sandbox at test + trace level only (router unit tests +
`store_scene()` persistence tests with a stubbed DB —
`tests/functional/test_scene_model_routing.py`, 10 tests; shot-plan
integration tests — `skills/video-pipeline/tests/test_coverage.py`, 3 new
tests proving `plan_camera_moves()` itself stamps the fields and that a
routing failure doesn't touch the camera-move plan; all confirmed
non-vacuous via `git stash`). No paid Kie/Anthropic key in the build
sandbox, so a REAL coverage build was never run — that's the gap this
entry defers:
- [ ] **Run a real coverage build** on a test video (any scene with
      "Generate coverage" / the storytelling coverage path —
      `python3 scripts/coverage_to_app.py --video <id> --scene <N>` on the
      VPS, or trigger it from the app) with a scene whose narration reads
      as a clear reveal/payoff beat (so the router doesn't just default to
      draft on every shot).
- [ ] **Confirm routing landed on real rows:**
      `se db "SELECT scene, image_index, camera_movement, routed_model,
      routing_reason, model_used FROM assets WHERE video_id='<test-vid>'
      AND scene=<N> ORDER BY image_index"` — expect `routed_model`/
      `routing_reason` populated wherever `camera_movement` isn't NULL/
      `'static'`-only, `model_used` NULL on every row (C13 hasn't wired it
      yet), and `routed_model` always one of the 4 wired ids (never
      `kling-3.0-pro`/`runway-gen4-turbo`/`hailuo-2.3-standard`).
- [ ] **Spot-check the reveal/payoff beat specifically:** that shot's
      `routed_model` should read `veo-3.1-quality` and `routing_reason`
      should mention "hero" — confirms the purpose→tag mapping fired on
      real (not synthetic) camera-selector output, not just the unit
      tests' hand-built `ShotContext`.
- [ ] **Confirm fail-soft in production conditions too:** temporarily break
      the import (or watch a real log) and confirm a routing hiccup logs
      `"model routing failed (shot ships without a recommendation)"` but
      the scene's coverage frames/camera moves still generate normally —
      no aborted build.
- **Cost:** whatever a normal coverage build already costs (image
  generation only — no clip generation is triggered by routing itself,
  since C13 hasn't wired clip generation to read `routed_model` yet). No
  NEW paid step beyond a build you'd run anyway.
- **Safety net:** routing is wrapped in its own try/except separate from
  camera-move assignment (proven by test, see above) — even a total router
  failure degrades to `routed_model`/`routing_reason` staying NULL on
  those shots, never a failed/aborted shot plan. Nothing downstream reads
  these columns yet (C13/C14 not built), so a live surprise here has zero
  blast radius on production behavior today.

---

## C13 — clip generation reads per-scene routed model; records `model_used` · live mixed-routing build check
Checklist §1.2 (P1.2b slice). `shared/model_router.resolve_clip_model()`
(precedence: scene override seam → C12's `assets.routed_model` when wired →
video-level model) is now called per row inside
`pipeline_executor.py::run_clip_generation`; `model_used` is written
fail-soft on completion, priced by a new `effective_model_id` (the engine
that ACTUALLY ran — NOT always `row_model_id`, the routed target: the
speaking/dialogue branch has no Veo case at all, so a Veo-routed speaking
row is forced down to Grok before pricing, and a successful InfiniteTalk
clip records `"infinitalk"` instead of whatever model routing picked);
`generation_ledger` rows and `actions.estimate_cost` quotes both price by
the ACTUALLY-resolved per-row model. Proven in-sandbox at test + trace
level only (17 tests: 6 `resolve_clip_model` unit tests, 5 quote-summation
tests, 6 real `run_clip_generation` wiring tests via `PipelineExecutor.__new__`
+ a fully monkeypatched DB/storage/image-client — 4 routing tests + 2
orchestrator-review speaking-branch tests —
`tests/functional/test_scene_model_routing.py` +
`tests/functional/test_c13_clip_model_routing.py`; all confirmed
non-vacuous via `git stash`). No paid Kie key in the build sandbox, so a
REAL mixed-routing clip run — Grok's animate call shape, Veo's, InfiniteTalk's,
and a real Kie charge — was never exercised end-to-end. That's the gap this
entry defers:
- [ ] **Build a coverage video through to clips** on a test video with at
      least one reveal/payoff scene (routes to `veo-3.1-quality`) and one
      ordinary/establishing scene (routes to `grok-imagine` or
      `veo-3.1-fast`) — confirm C12's routing landed first (§C12 above),
      then tap "Animate" (whole video or per-scene).
- [ ] **Confirm clips actually differ per scene:** watch the backend logs
      for the `"Animating ... ({model_id})"` line and (for Veo shots) that
      `client.generate_video_veo` actually fires — not every clip silently
      running through Grok regardless of `routed_model`.
- [ ] **Confirm `model_used` landed on real rows:**
      `se db "SELECT scene, image_index, routed_model, model_used FROM
      assets WHERE video_id='<test-vid>' ORDER BY scene, image_index"` —
      `model_used` should equal `routed_model` on every SILENT (non-speaking)
      row that had a wired routed_model, and should equal the video's own
      `video_model` on any row whose `routed_model` was NULL/unwired. On a
      video with `dialogue_mode='character_dialogue'`, a SPEAKING row
      routed to a Veo model is the interesting case: `model_used` must read
      `"infinitalk"` (if InfiniteTalk generated it) or `"grok-imagine"`
      (if it fell back to Grok) — NEVER `"veo-3.1-fast"`/`"veo-3.1-quality"`,
      since Veo cannot actually animate a speaking/dialogue shot today
      (orchestrator review, no live coverage to prove this outside tests).
- [ ] **Confirm the ledger priced each clip by its ACTUAL model:**
      `se db "SELECT model, unit_cost, actual_cost FROM generation_ledger
      WHERE video_id='<test-vid>' AND stage='clip' ORDER BY created_at"` —
      a Veo Quality row should show `unit_cost=1.25` (or whatever §C09's
      Veo price-confirmation task above landed on), a Grok row `~0.09-0.225`
      depending on duration tier — never a single flat number across every
      row on a mixed-routing video.
- [ ] **Confirm the pre-spend quote matched what actually got spent:** note
      the "Animate" confirm card's quoted $ before tapping, then compare to
      `videos.total_cost` (or the ledger sum for stage='clip') after the run
      — they should match (mixed-routing quote summation, checklist §1.2/C13
      money invariant #2).
- **Cost:** whatever real clips already cost (see `docs/cost-awareness.md`
  — a Veo Quality clip is the priciest single line item, ~$1.25/clip at the
  currently-registered price). Use the smallest test video that has both a
  reveal/payoff beat and an ordinary beat — no need for a full 20-scene
  video to prove per-scene divergence.
- **Safety net:** the `model_used` write is in its own try/except AFTER the
  clip's real `video_clip_url` write — a forced failure there (proven by
  test) cannot lose a paid clip. A NULL/unwired `routed_model` falls back to
  the video's own model byte-identically (proven by test with real object
  identity, not just equal values) — so even if C12's routing turns out
  wrong or absent on some rows, clip generation behaves exactly as it did
  before this chunk on those rows.

## C13b — channel-style routing guardrail · live style-declared build check
Checklist §C13b. `shared/model_router.route_shot_model()` gained
`render_style`/`video_model_id` params: a NULL `videos.render_style` (every
video today — no UI sets it yet) returns the video's own model unchanged;
a declared style filters the C12/C13 purpose→tier cascade to wired models
whose `ModelProfile.styles` include it, so an animated channel never
matches veo/seedance even for a hero-tagged shot. Proven at unit/trace
level only (22 new tests — router guardrail cascade, `/api/models` `styles`
field, `render_style_for_preset()`'s two derivation call chains — all
confirmed non-vacuous via `git stash`; migration 089 confirmed live via
`information_schema.columns`). No real video has `render_style` declared
yet (only two narrow auto-derivation paths exist, neither UI-driven), so
the guardrail's actual effect on a real coverage build was never exercised
end-to-end:
- [ ] **Declare a style on a real video:** `se db "UPDATE videos SET
      render_style='animated' WHERE id='<test-vid>'" --write` on a test
      video whose `video_model` is `grok-imagine` (or set it to that first).
- [ ] **Run coverage on a scene with a reveal/payoff beat** (would earn the
      "hero" tag pre-C13b, routing to `veo-3.1-quality`) and confirm
      `assets.routed_model` for that shot is `grok-imagine`, not
      `veo-3.1-quality` — `se db "SELECT scene, image_index, routed_model,
      routing_reason FROM assets WHERE video_id='<test-vid>' ORDER BY
      scene, image_index"`; `routing_reason` should read something like
      "reveal scene, but channel is animated → Grok Imagine".
- [ ] **Repeat with `render_style='realistic'`** on a different test video
      and confirm a reveal/payoff shot DOES route to `veo-3.1-quality`
      (the guardrail filters by style, it doesn't disable the cascade for a
      channel that declared a matching style).
- [ ] **Confirm an undeclared-style video (the common case today) is
      unaffected:** run coverage on a video with `render_style` still NULL
      and confirm every shot's `routed_model` equals that video's own
      `video_model` with `routing_reason='channel style not set — using
      channel default'` — never a tier-upgraded pick.
- [ ] **Confirm auto-derivation fired where expected:** create a video via
      the New Video modal choosing an explicit preset (e.g. "Pixar 3D") and
      check `se db "SELECT visual_style, render_style FROM videos WHERE
      id='<new-vid>'"` shows `render_style='animated'`; repeat with
      "Realistic"/"Cinematic" and confirm `render_style='realistic'`; and
      with a channel-locked animated format (no explicit style chosen),
      confirm `apply_format_defaults` populated both `visual_style` AND
      `render_style` together.
- **Cost:** cheap — image-only coverage generation, no clip spend needed to
  prove `routed_model`/`routing_reason` (only the LAST checklist item, if
  someone chooses to also tap "Animate" to see the clip itself, costs
  whatever that clip model charges).
- **Safety net:** the guardrail's NULL-style branch is the default for
  every video today, and it returns the video's own model verbatim
  (proven by test) — so even if this live check is never run, no existing
  video's clip generation changes at all; only the (currently unused)
  `routed_model` recommendation field goes quieter.

---

## C14 — per-scene model badge + override sheet + Channel look control · live UI + build check
Checklist §1.2 [U]. Migration 090 (`assets.model_override`, confirmed live
via `information_schema.columns`) plus the wiring that makes it real:
`shared.model_router.resolve_clip_model()`'s `scene_override` param (C13
reserved it, always called with `None`) is now fed from
`assets.model_override` at both the quote (`actions._routed_clip_costs`)
and generation (`pipeline_executor.run_clip_generation`'s `_one` closure)
call sites — proven non-vacuous via `git stash` (14 tests in
`test_c13_clip_model_routing.py`, all pass with the fix, 3 of them
specifically for the override precedence fail without it). Two new/reused
endpoints: `PATCH /api/assets/{id}/model-override` (new, tenant-scoped,
gates against `MODEL_REGISTRY[...].wired`) and `render_style` folded into
the existing generic `PATCH /api/videos/{id}` (`update_video`'s
`allowed_fields`) — both covered by
`test_c14_model_override_and_render_style.py` (8 tests, TestClient +
monkeypatched DB, no live DB). Frontend: `ScenesWorkspaceTab.tsx` gained a
per-scene model badge (effective model = override > routed > video default,
`model_used` once a clip exists; "why" tooltip from `routing_reason` /
"Manual override" / "Channel default"), a tap-to-open override sheet
(`ModelOverrideSheet`, prices sourced from the existing `["models"]` query —
no hardcoded prices), and a "Channel look" select (Auto/Animated/Realistic)
next to the existing Clips model picker. `npx tsc --noEmit` and
`npm run build` both clean (build required `NEXT_PUBLIC_API_URL` set — an
existing prod-build requirement, unrelated to this chunk).

**What was NOT run:** a real Playwright pass against booted dev servers.
Unlike `GET /api/models` (C03's "DEV_MODE with no DB" case — that route only
reads the in-process `MODEL_REGISTRY`), `GET /api/videos/{id}/assets` and
`GET /api/videos/{id}` both query the real `videos`/`assets` tables — there
is no no-DB path for them, so a badge/sheet render genuinely needs a live
video with scene assets behind it. The full recipe:
- [ ] **Local E2E boot** (`tasks/lessons.md`'s recipe): source prod
      `storyengine/.env`, `DEV_MODE=true DEV_TOKEN=<random>
      DEV_TENANT_ID=<disposable tenant>`, uvicorn on :8002 (CWD = backend
      dir), `NEXT_PUBLIC_API_URL=http://127.0.0.1:8002 npm run dev -- --port
      3002`. Disposable tenant needs the same tenants/channel_profiles/
      tenant_usage rows the lesson describes.
- [ ] **Seed one video with routed/overridden scenes:** `se db "UPDATE
      assets SET routed_model='veo-3.1-quality', routing_reason='reveal
      scene -> hero tier (premium)' WHERE video_id='<test-vid>' AND
      scene=1" --write`; leave a second scene's `routed_model` NULL to see
      the video-default fallback badge.
- [ ] **Playwright:** open the video's Scenes tab, confirm scene 1's card
      shows a "Veo 3.1 Quality" badge with the routing_reason in its title
      tooltip, scene 2's card shows the video's own default model; tap scene
      1's badge, confirm the sheet lists all wired models with $/clip and
      highlights the active one; pick a different model, confirm the badge
      updates (with the manual-override dot) and `assets.model_override`
      is set (`se db "SELECT model_override FROM assets WHERE id='<row>'"`);
      tap "Use recommendation", confirm it clears back to the routed badge
      (no dot); set "Channel look" to Animated/Realistic in the model-
      controls bar, confirm `videos.render_style` updates
      (`se db "SELECT render_style FROM videos WHERE id='<test-vid>'"`) and
      the helper line under the controls bar changes text.
- [ ] **The full checklist §1.2 [V]** (generate real clips on an override,
      confirm `model_used`/the ledger/the badge all agree post-generation,
      and that the quote a creator confirmed matches what was actually
      spent) stays deferred here too — same paid-generation gap C13's entry
      above already flags, now extended to cover the override path.
- **Cost:** free through the seed/UI checks above (no generation). The last
  bullet (real clip generation) costs whatever the picked model's per-clip
  price is (~$0.09 Grok to ~$1.25 Veo Quality).
- **Safety net:** every new column is nullable and additive
  (`model_override`/`render_style` both default NULL), `resolve_clip_model`
  falls through to pre-C14 behavior whenever `model_override` is unset (the
  case for every existing asset row), and the badge/sheet are additive UI
  gated on `videoStageEnabled` — an images-only plan renders no badge at
  all, so a video with no video stage is unaffected either way.

---

## C15 — copilot routing conversation + itemized confirm cards · live round-trip check
Checklist §1.2 [B]/[U] (UX map §1's worked example: "Scene 12 is your
reveal — Veo Quality ($1.25); Grok elsewhere. Total $4.20 vs $25
all-premium"). `actions.cost_breakdown()` (one resolver over the same
`_routed_clip_rows`/`_resolved_price` C13/C14 already use), `guardrail_note()`,
the `_handle_copilot` confirm-text/card wiring, and the `ConfirmActionCard`
frontend render are all covered at the unit level (15 tests in
`test_c15_itemized_cost_breakdown.py`, 2 in `test_agent_brain_cost_tool.py`,
`npx tsc --noEmit` + `npm run build` clean) — no live LLM call, no live DB,
no paid generation anywhere in that pass. What's NOT provable without a
live conversation:
- [ ] **Local E2E boot** (same recipe as C14's entry above): source prod
      `storyengine/.env`, `DEV_MODE=true DEV_TOKEN=<random>
      DEV_TENANT_ID=<disposable tenant>`, uvicorn on :8002, `NEXT_PUBLIC_API_URL=
      http://127.0.0.1:8002 npm run dev -- --port 3002`.
- [ ] **Seed a mixed-routing video** (reuse C14's seed recipe): one scene's
      `routed_model='veo-3.1-quality'` + a real `routing_reason`, a second
      scene's `model_override` set to a different wired model, a third
      scene's `routed_model` left NULL. Optionally set `videos.render_style`
      to `'animated'` or `'realistic'` to exercise the guardrail phrasing.
- [ ] **Open the video's chat dock, type "animate scene 3"** (or "animate
      it"/"finish it" for the build path): confirm the assistant's reply text
      itemizes the per-model counts/subtotals, names the hero (premium-tier)
      scene(s) with their real `routing_reason`, states the all-premium
      comparison figure, and mentions the channel-look guardrail state
      matching whatever `render_style` was seeded; confirm the rendered
      confirm card shows the same itemized lines (not just the blended
      total).
- [ ] **Ask "how much has this cost?"** after some real spend exists; confirm
      the "Finishing adds ~$X" tail also itemizes (agent_brain's optional
      cheap-add path) and matches the confirm card's own numbers for the
      same video.
- [ ] **Tap "Do it"** on an itemized confirm card; confirm the SAME clips
      generate at the SAME per-row models the card itemized (ties back to
      C13's live verification — the quote a creator confirms must match
      what was actually spent).
- **Cost:** free through the seed/chat-read checks above (no generation
  until the last bullet). The last bullet costs whatever the seeded models'
  per-clip prices are (~$0.09 Grok to ~$1.25 Veo Quality per scene).
- **Safety net:** `cost_breakdown`/`guardrail_note` are pure reads (no writes,
  no new columns) layered on data C12/C13/C13b/C14 already write; the new
  `breakdown` card field and `render_style` summary field are both additive
  and only ever populated when non-empty — a stale frontend build (or a
  quote with nothing to itemize) renders the exact pre-C15 confirm card.

---

## C10 — UI "Est → Actual" cost chip + ledger drawer · live generate-and-compare check
Checklist §0.3d. New `GET /api/videos/{id}/ledger` endpoint, a `CostLedgerChip`
component (chip + drawer) on the video-detail page header, and a `cost` tool
in `agent_brain.py` for the copilot's "how much has this cost?" answer — all
three read the SAME `generation_ledger` table / `videos.total_cost` rollup
C07–C09a already wire and write to. No paid Kie key or running app in the
build sandbox, so this is proven at test + trace level only
(`tests/functional/test_video_ledger_endpoint.py` — 5 tests against the route
function with a fake DB; `tests/functional/test_agent_brain_cost_tool.py` — 4
tests locking the exact phrasing; `npx tsc --noEmit` clean). What's NOT
provable without a live paid generation + browser:
- [ ] **Generate one scene's pictures** on a test video (cheapest paid step —
      "Generate the pictures" on a single scene, ~$0.05-0.30 depending on shot
      count) and watch the video-detail page header.
- [ ] **Confirm a `generation_ledger` row appeared and `total_cost`
      incremented:** `se db "SELECT stage, model, units, unit_cost,
      actual_cost, created_at FROM generation_ledger WHERE
      video_id='<test-vid>' ORDER BY created_at DESC LIMIT 5"` and `se db
      "SELECT total_cost FROM videos WHERE id='<test-vid>'"` — the video row's
      `total_cost` must equal `SUM(actual_cost)` over that video's ledger rows.
- [ ] **Chip shows the update:** the header chip's "Actual" side (right of the
      arrow) matches the DB's `total_cost` after the page refetches (poll or
      manual reload) — no stale $0.00.
- [ ] **Drawer matches the ledger:** click the chip, confirm the drawer opens
      (loading spinner briefly, then rows), the per-stage breakdown sums to
      the same `total_cost`, and the stage label(s) shown match what actually
      ran (e.g. "Pictures $X.XX").
- [ ] **Empty state on a fresh video:** open a video with zero ledger rows —
      chip shows `Actual $0.00`, drawer (if opened) shows the "No spend
      recorded yet" copy, not a blank panel or a console error.
- [ ] **Copilot conversational door:** in that video's co-pilot dock, ask
      "how much has this cost so far?" — confirm the reply cites the same
      dollar figure and per-stage breakdown as the drawer (it's reading the
      same table via the new `cost` tool in `agent_brain.py`), not a vague or
      hallucinated number.
- **Cost:** one cheap picture-generation step (~$0.05-0.30) — the only paid
  step needed; everything else above is read-only.
- **Safety net:** the endpoint is additive (new route, no existing route
  changed) and the frontend fails soft — chip renders off data the page
  already fetches, drawer shows its own error/empty state rather than a
  broken render if the ledger endpoint 404s or 500s.

---

## C07 — `generation_ledger` clip-path write + `total_cost` rollup · live paid-clip check
Checklist §0.3a. `pipeline_executor.run_clip_generation` now calls
`generation_ledger.record_ledger_entry(stage="clip", model=<resolved
video_model>, units=1, unit_cost=actual_cost=clip_cost, kie_task_id=...)`
right after each clip's `assets.video_clip_url` write succeeds; the helper
INSERTs one `generation_ledger` row then recomputes `videos.total_cost =
SUM(actual_cost)` for that video. Proven in-sandbox: 6 unit tests against an
in-memory fake `database.execute` lock the row shape, the SUM-recompute
behavior (including that it REPLACES a stale non-ledger `total_cost`, not
increments it), per-video scoping, and fail-soft (a forced INSERT exception
never propagates and leaves neither table touched) —
`tests/functional/test_generation_ledger.py`. Migration `087_generation_ledger.sql`
applied live to `wrromlupsmyzrrcqlucn`; table, both columns' shape, both
indexes, and RLS-enabled all confirmed via `information_schema`/`pg_indexes`/
`pg_class`. No paid Kie key in the build sandbox, so the actual clip → ledger
row → total_cost round trip against a real Kie response was NOT run. What's
NOT provable without a live paid clip:
- [ ] **Generate one clip** on a test video (Scenes tab, tap "Animate" on
      one card, or `Animate this scene` on a scene with exactly one shot to
      keep it cheap) using the default `grok-imagine` model (~$0.10-0.15 for
      the shortest duration tier).
- [ ] **Confirm a `generation_ledger` row appeared:** `se db "SELECT stage,
      model, units, unit_cost, actual_cost, kie_task_id, created_at FROM
      generation_ledger WHERE video_id='<test-vid>' ORDER BY created_at
      DESC LIMIT 3"` → expect one new row, `stage='clip'`, `model='grok-imagine'`
      (or whichever model the test video is set to), `unit_cost = actual_cost`
      matching `MODEL_REGISTRY['grok-imagine'].cost_per_clip[<duration>]`,
      and `kie_task_id` NOT NULL (proves the `task_id_out` threading through
      `ImageClient.generate_video` actually captured a real Kie taskId, not
      just the fake-clip-result unit test's assumption).
- [ ] **Confirm `videos.total_cost` incremented by exactly that row's
      `actual_cost`:** `se db "SELECT total_cost FROM videos WHERE
      id='<test-vid>'"` before and after the clip. If the video had prior
      clips, `total_cost` should equal the full `SUM(actual_cost)` across
      all its `generation_ledger` rows, not just the delta.
- [ ] **Generate a second clip on the same video** and confirm `total_cost`
      accumulates correctly (sum of both rows) rather than resetting or
      double-counting — the concurrency note in SYSTEM_STATE.md §C07 (fresh
      `task_id_box` per clip, recompute-not-increment rollup) is the thing
      actually being checked here.
- [ ] **Backend log check (fail-soft, best-effort):** confirm no
      `[generation_ledger] write/rollup failed` line appears in the backend
      log for a clip that otherwise completed successfully — that would mean
      the bookkeeping silently missed a real charge (still not a bug in the
      clip itself, per the fail-soft design, but worth catching).
- **Cost:** ~$0.10-0.15 (one Grok Imagine clip, shortest duration tier).
  Per storyengine/CLAUDE.md, get a cost quote + explicit yes before
  triggering any paid generation, even for this check.
- **Safety net:** the ledger write is wrapped in
  `generation_ledger.record_ledger_entry`'s own try/except (fail-soft) — a
  failure here cannot fail or roll back the clip generation itself; worst
  case is a clip that generated correctly but didn't get billed to the
  ledger (silent under-count, never an error surfaced to the creator, never
  a lost asset).

---

## C08 — ledger writes on images/voice/thumbnail/sound · live per-stage spend check
Checklist §0.3b. Extends C07's `generation_ledger`/`record_ledger_entry()`
(unchanged) to the 4 remaining paid stages, 9 call sites total: `store_scene`/
`redraw_asset_image`/`run_images`/`run_image_variants` (stage="image",
`actions.PICTURE_COST`=0.08/unit); `run_voice` (stage="voice",
`actions.VOICE_COST_ESTIMATE`=0.30 flat per run); `run_thumbnail`'s 3
completion paths + `_run_channel_formula_thumbnail` (stage="thumbnail",
`actions.THUMBNAIL_COST`=0.10 flat); `run_sound_effects` (stage="sound",
`SoundClient.ESTIMATED_COST_PER_GENERATION`=0.05/unit — the real per-
generation number `sound_bot.py` already computes, reused as-is). Proven
in-sandbox: 6 new unit tests (12 total with C07's) against the same
in-memory fake `database.execute` — one per stage confirming it writes with
the right `stage` tag and imports the REAL price constant (not a re-typed
literal, so drift in `actions.py`/`SoundClient` breaks the test too); one
proving all 5 stages (clip + the 4 new) sum into `total_cost` without
double-counting; one confirming C07's fail-soft guarantee holds identically
for every new stage — `tests/functional/test_generation_ledger.py`. No paid
Kie/ElevenLabs key in the build sandbox, so no real generation → ledger row
round trip was run for any of the 4 stages. What's NOT provable without live
paid generation:
- [ ] **Images — bulk coverage:** on a test video with a scripted scene,
      tap "Generate the pictures" (coverage path). Confirm one
      `generation_ledger` row per scene appears: `se db "SELECT stage,
      model, units, unit_cost, actual_cost FROM generation_ledger WHERE
      video_id='<test-vid>' AND stage='image' ORDER BY created_at DESC"` →
      `units` should equal that scene's frame count, `unit_cost=0.08`,
      `actual_cost = units * 0.08`.
- [ ] **Images — single redraw:** tap "Redraw" on one picture. Confirm a
      second `stage='image'` row with `units=1`, `actual_cost=0.08`.
- [ ] **Images — variant regen** (if reachable from the current UI):
      generate 3 variants for one shot; confirm `units=3`,
      `actual_cost=0.24`.
- [ ] **Voice:** tap "Generate the voiceover". Confirm one `stage='voice'`
      row, `unit_cost=actual_cost=0.30`, regardless of scene count (known
      flat-estimate limitation — see SYSTEM_STATE.md §C08 price-sourcing
      note; C09 may replace this with a real per-char ElevenLabs figure).
- [ ] **Thumbnail:** tap "Redo the thumbnail" (whichever of the 3 paths
      fires — modeled/channel-formula/from-scratch, check the activity feed
      message to know which). Confirm one `stage='thumbnail'` row,
      `unit_cost=actual_cost=0.10`.
- [ ] **Sound:** run "Add sound" through to sound effects. Confirm one
      `stage='sound'` row, `unit_cost=0.05`, `units` = the number of sound
      effects actually generated (check against the activity-feed message
      "Generated N sound effects").
- [ ] **`videos.total_cost` sums across ALL stages on one video:** after
      running clip (C07) + image + voice + thumbnail + sound on the same
      test video, `se db "SELECT total_cost FROM videos WHERE
      id='<test-vid>'"` should equal the straight sum of every
      `generation_ledger` row's `actual_cost` for that video, across all 5
      distinct `stage` values — `se db "SELECT stage, SUM(actual_cost) FROM
      generation_ledger WHERE video_id='<test-vid>' GROUP BY stage"` to
      check per-stage subtotals against the total.
- [ ] **Backend log check (fail-soft, best-effort):** confirm no
      `[generation_ledger] write/rollup failed` lines for any of the 4
      stages during this run.
- **Cost:** ~$0.30-1.00 total for a small test video across all 4 stages
  (coverage for 1-2 scenes, one voice run, one thumbnail, a few sound
  effects). Get a cost quote + explicit yes before triggering, per
  storyengine/CLAUDE.md.
- **Safety net:** every write goes through C07's existing
  `record_ledger_entry()` try/except (fail-soft, unchanged by C08) — a
  ledger failure on any of these 4 stages cannot fail or roll back the
  generation itself; worst case is a completed asset that didn't get billed
  to the ledger.

---

## C09 — single price source + real per-model/per-char pricing · live Kie-charge observation
Checklist §0.3c. Consolidated every generation price into
`shared/channel_profile.py` (read by `actions.py` and the frontend, see
SYSTEM_STATE.md §C09) and made pricing model-aware where the call site
knows enough (`picture_price_for(model_used)` for images, real character
count for voice). STEP 1 confirmed Kie's job-status response never carries
a cost/credit field, and `GET /api/v1/chat/credit` is an account-wide
balance, not a per-task charge — so there is no way to get a REAL
per-generation number without observing the Kie dashboard directly as the
account drains. That observation is what this section queues; it's the
product owner's explicitly requested follow-up, not a nice-to-have.

**C09a (2026-07-18) update:** a web-research pass found Kie's PUBLISHED
per-model/per-resolution pricing pages at a confirmed $0.005/credit rate,
and traced each StoryEngine call site to the exact resolution/duration tier
it actually requests (see `shared/channel_profile.py`'s comments and
`docs/cost-awareness.md`). This RESOLVED gpt-image-2, nano-banana-2,
z-image, grok-imagine clips, and nano-banana-pro/thumbnail — all now priced
off published rates, not guesses, and struck from the list below. What's
left is genuinely still uncertain (no public price found, or two
conflicting public prices) — a real Kie-dashboard read is still the only
way to close these out:
- [ ] **veo-3.1-fast / veo-3.1-quality clip prices** — Kie's pricing page
      lists $0.40 / $2.00 per 8s clip, but a later Kie announcement claims a
      cut to $0.30 / $1.25; unclear whether that cut is Veo-3.0-vs-3.1
      specific or applies to both, and unclear which figure is current.
      `MODEL_REGISTRY["veo-3.1-fast"].cost_per_clip[8]` / `["veo-3.1-quality"]
      .cost_per_clip[8]` already carry the LOWER (cut) figures — left
      unchanged by C09a, not re-verified. These are WIRED, live, selectable
      models (unlike the 3 below) — highest priority of what's left here.
  - [ ] **Read the Kie dashboard's per-task credit consumption**
        (`kie.ai/logs`) for one recent Veo 3.1 Fast and one Veo 3.1 Quality
        clip, back out $/unit (credits ÷ $0.005), compare against 0.30/1.25,
        update `shared/channel_profile.py` if off.
- [ ] **kling-3.0-pro clip price** — only a "Turbo" tier price was found on
      Kie's public pages; unconfirmed whether that's the same SKU as "Pro".
      UNWIRED (`wired=False`, no live generation path) — no real spend
      depends on this, low priority.
- [ ] **runway-gen4-turbo clip price** — found via a low-confidence
      secondary source only, not Runway's or Kie's own pricing page.
      UNWIRED — low priority, same reasoning as kling above.
- [ ] **Grok's image-generation price** (a distinct SKU from Grok Imagine's
      video-clip price, which IS resolved) — not found published anywhere.
      Not currently a selectable image model in StoryEngine
      (`image_model_router.VALID_IMAGE_MODELS` doesn't include it) — no real
      spend depends on this either.
- [ ] **ElevenLabs voice** — current price `$0.30/1000 chars`
      (`docs/cost-awareness.md`) — confirm against a real synthesis call's
      billed character count (ElevenLabs' own dashboard/invoice, not
      Kie's — voice doesn't route through Kie, so the $0.005/credit research
      pass didn't touch it).
- [ ] **After confirming/correcting any price above**, update the SAME
      constant in `shared/channel_profile.py` (never re-add a hand-copied
      number anywhere else — `actions.py` and the frontend both re-export
      from there) and re-run
      `tests/functional/test_generation_ledger.py::test_actions_prices_are_the_same_object_as_channel_profile`
      to confirm nothing drifted apart during the edit.
- **Cost:** $0 to READ the dashboard/logs (no new generation needed — this
  reconciles against generations that already happened for other reasons).
  If a fresh generation of each type is needed instead (dashboard doesn't
  show old-enough history), budget ~$0.20-0.40 total for one tiny example of
  each type — get a cost quote + explicit yes first, per storyengine/CLAUDE.md.
- **Safety net:** this is a read-then-maybe-edit-a-constant task — no code
  path depends on the observation succeeding; a stale/unconfirmed price
  just means the cost dashboard under- or over-reports slightly until this
  is done, never a broken generation or a wrong CHARGE to a creator
  (StoryEngine doesn't bill per-generation yet).

---

## C06 — Research-skipped transparency chip · live tap-test
Checklist §0.5. `actions.make_autobuild_step` records `videos.research_skipped
= TRUE` when the default autobuild skips research for a non-`static_docu`
video (unchanged default behavior — this only adds visibility). The pipeline
page's `GuidedNextStep` card shows a "Research: skipped (script writes from
topic) — Run research" chip when the flag is set, with a one-tap button that
calls the existing `POST /api/pipeline/research/{id}` trigger. Proven
in-sandbox: 3 unit tests lock the record/no-record behavior for
static_docu vs. not (`tests/functional/test_research_skipped_chip.py`,
confirmed non-vacuous via `git stash`); `tsc --noEmit` + `py_compile` clean;
full trace read end to end (autobuild write → API SELECT → VideoDetail field
→ frontend type → chip render → tap → `runPipelineStage(id, "research")` →
existing trigger route → `pipeline_executor.run_research` → clears the flag
on save). What's NOT provable without a running app + browser:
- [ ] **Create a default video** (any non-static-documentary channel, normal
      "full" build) and open its pipeline page. Expected: the "Research:
      skipped — Run research" chip is visible on the `GuidedNextStep` card
      before the script finishes (the video's status will already be past
      `idea_logged`/`approved` by the time you look, which is fine — the flag
      persists once set).
- [ ] **Tap "Run research."** Expected: the chip's button shows "Starting…",
      the card flips into the shared running/progress state (same banner any
      other step uses), and a `research` stage kicks off — confirm via the
      activity feed or `background_tasks`/`stage_transitions` rows for that
      video showing a `research` entry.
- [ ] **After it completes,** confirm `videos.research_skipped` is now
      `false` for that video (`se db "SELECT research_skipped FROM videos
      WHERE id='<id>'"`) and that the chip has disappeared from the page
      (may need a refresh/refetch if SSE doesn't push it).
- [ ] **Plan-restricted edge case (optional):** create a video via a
      "script only" or other reduced-workflow chat plan (so `pipeline_stages`
      excludes `"research"`), then tap the chip's "Run research" from that
      video's page anyway. Expected: it still works — the trigger route
      widens `pipeline_stages` to include `"research"` first instead of
      400ing, and the chip clears the same way.
- **Cost:** research is a paid Claude/agent call (~$0.05-0.20 per the
  `docs/cost-awareness.md` "Claude API" line) — get a nod before running it if
  that matters for the test tenant's budget, but it's a single call, not a
  video-scale spend.
- **Safety net:** the DEFAULT autobuild behavior (skip research for
  non-`static_docu`) is completely unchanged by this chunk — worst case the
  chip is cosmetic-only and the one-tap silently no-ops into the existing
  `/research/{id}` route's own error handling (409 if a task's already
  running, 404 if the video's gone). No new failure mode on the build path
  itself.

---

## C06a — autobuild honors explicit research request in plan · live confirmation
Follow-up fix to the bug C06 flagged but explicitly didn't touch (see
SYSTEM_STATE.md §C06 "Found but explicitly NOT fixed" / §C06a).
`actions.make_autobuild_step`'s skip branch (idea_logged/approved,
non-`static_docu`) now checks the video's `pipeline_stages` plan before
skipping: `parse_stage_plan(video.get("pipeline_stages"))` — if the plan is
`None` (the ordinary default, unrestricted pipeline), it still skips exactly
as before (byte-identical, no behavior change for any existing/default
video). If the plan is a real list that NAMES `"research"` (e.g.
`workflow:"research"` -> `pipeline_stages=["research"]`, or a custom plan
like `["research", "script"]`), it now calls `PipelineExecutor.run_research`
instead of skipping, mirroring the `static_docu` branch's pattern (advance on
success, hard-stop with a failure message on research failure rather than
silently writing a script from thin air).

Proven in-sandbox: 5 new unit tests
(`tests/functional/test_autobuild_explicit_research_plan.py`) lock (a) the
default no-plan case still skips and never calls `run_research`, (b) an
explicit `["research"]` plan calls `run_research` and never records
`research_skipped`, (c) a custom plan naming research alongside other stages
also runs it, (d) a restricted plan that does NOT name research still skips,
and (e) `static_docu` with research in its plan researches exactly once (no
double-run — the new check is structurally unreachable for `static_docu`).
Confirmed non-vacuous via `git stash` (the two explicit-plan tests fail
without the fix; the default/no-plan/`static_docu` tests pass either way,
proving the default path is untouched). Full backend suite: same 16
pre-existing failures + 1 pre-existing error before and after (`git stash`
compared), unrelated to this change. `py_compile` clean.

What's NOT provable without a running app + a real Claude API key:
- [ ] **Create a video via the chat producer with workflow `"research"`**
      (ask it to "just research the topic" / pick the "research" workflow
      card) or any custom plan that includes research alongside other
      stages, then trigger the build ("Build the video" / the build button /
      autobuild). Expected: the activity feed / `stage_transitions` shows a
      real `research` stage running (not skipped), `videos.research_payload`
      gets populated, and `videos.research_skipped` stays `false` for that
      video throughout.
- [ ] **Create a video the normal way** (default "full" workflow, no
      restricted plan) and build it. Expected: unchanged — research is
      skipped, `videos.research_skipped` flips to `true`, no `research` stage
      appears in the activity feed. This is the regression check that the
      DEFAULT path truly didn't change.
- **Cost:** research is a paid Claude/agent call (~$0.05-0.20 per
  `docs/cost-awareness.md`'s "Claude API" line) — same order of cost as the
  C06 chip's live check, one call per test video.
- **Safety net:** the default (no-plan) autobuild path is provably unchanged
  by the non-vacuous test above — a live failure here can only affect videos
  that explicitly requested research in their plan, which previously got
  silently and incorrectly skipped anyway; worst case this live check
  surfaces a research-call failure that the code already handles by stopping
  the build with a failure message instead of routing to `done`.

---

## C01a — RLS enablement (migration 083) · post-deploy smoke check
Migration `083_enable_rls_ad_hoc_tables.sql` flips Row Level Security ON for `secrets`, `static_reference_cache`, `channel_video_retention`. Proven safe in-sandbox (the backend role bypasses RLS — `secrets` already runs RLS-on/0-policies live and works). Auto-deploys on the next `git pull` + backend restart.
- [ ] After 083 has auto-deployed, confirm the backend still functions normally — specifically anything that reads/writes **`static_reference_cache`** (static-docu feature) and **`channel_video_retention`** (analytics/retention). Expected: no change in behavior (backend bypasses RLS). If either suddenly errors on read, 083 is the suspect — the fix is to add a permissive policy or confirm the connecting role.
- **Evidence to capture:** one successful static-docu run + one analytics/retention read after the deploy, or simply "no new errors in `journalctl -u storyengine-backend` referencing those tables."

---

## C02 — image-model override honored · live Kie confirmation
The Pictures model selector now routes the **bulk "Generate all pictures"** path (and redraw/redo paths) through the shared resolver so `image_model_override` is honored, records `image_model` on each asset, and shows a per-panel badge. Default (`gpt-image-2`/no override) is test-proven byte-identical. These live checks confirm the non-default models actually reach Kie:
- [ ] **z-image:** on a test video set the Pictures model to **z-image**, run "Generate pictures," then confirm: (a) the Kie task payload names the z-image model, (b) the generated `assets` row has `image_model = 'z-image'`, (c) the panel badge reads **Z**.
- [ ] **nano-banana-2:** repeat the above with **nano-banana-2** → payload names nano, asset row `image_model = 'nano-banana-2'`, badge reads **Nano**.
- [ ] **default unchanged:** a video with no override (or `gpt-image-2`) still generates via GPT Image 2, asset row `image_model = 'gpt-image-2'`, badge reads **GPT** — and looks the same as before this change.
- [ ] **content-policy fallback:** trigger a prompt the chosen model refuses → confirm it falls back to GPT Image 2 **and** the asset row truthfully records `image_model = 'gpt-image-2'` (not the requested model). *(Optional — only if a refusing prompt is handy.)*
- **Cost:** ~$0.025/image; one image per model is enough (<$0.15 total). **No YouTube publish needed.**
- **Safety net:** the fallback means even a total z-image/nano failure degrades to a working GPT image — it can't hard-break a video.

---

## C03 — single-sourced `wired` flag + `GET /api/models` · live clip-generation confirmation
The Scenes clip-model dropdown now derives its options from `GET /api/models`
(`storyengine/backend/routes/model_registry.py`), which reads the same
`ModelProfile.wired` flag `pipeline_executor.run_clip_generation`'s gate
checks — the two can no longer drift. Confirmed in-sandbox: `curl
/api/models` (backend booted locally with no DB/Redis) returned `wired:false`
for Kling 3.0 Pro / Runway Gen-4 Turbo / Hailuo 2.3 Standard and `wired:true`
for Grok Imagine / Seedance 2.0 / Veo 3.1 Fast / Veo 3.1 Quality, matching the
gate exactly; `tests/functional/test_model_registry.py` pins this. What's
NOT provable without a paid Kie key is that every *wired* model actually
produces a clip end to end (the checklist's literal "selecting every listed
model generates without the isn't-available-yet error"):
- [ ] For each wired model (**Grok Imagine, Seedance 2.0 Cinematic, Veo 3.1
      Fast, Veo 3.1 Quality**) on a test video: select it in the Clips
      dropdown, animate one scene, confirm the clip completes (no "isn't
      available yet" error, no silent fallback to Grok) and the resulting
      `assets.video_clip_url` is playable.
- [ ] Confirm the 3 unwired models (Kling 3.0 Pro, Runway Gen-4 Turbo, Hailuo
      2.3 Standard) are simply absent from the rendered dropdown (or shown
      disabled) — never selectable — matching what `GET /api/models` reports.
- **Cost:** one clip per wired model — Grok Imagine ~$0.10-0.15, Seedance 2.0
  ~$0.30, Veo 3.1 Fast ~$0.30, Veo 3.1 Quality ~$1.25 (durations vary; use the
  shortest tier). ~$2 total for all four. **No YouTube publish needed.**
- **Safety net:** the gate (`pipeline_executor.py`) still rejects any
  unwired `model_id` server-side even if a stale client somehow posts one —
  a live failure here is a generation-quality issue, not a data-integrity one.

---

## C04 — home Producer Kie-only fallback · live production-plan confirmation
The home Producer (the main chat intake turn in `chat_turn`, and the onboarding
hand-off in `_seed_producer`, both in `storyengine/backend/routes/chat.py`) used
to hard-require an `anthropic_api_key` and tell a Kie-only tenant to go add one.
It now resolves through the same fallback the in-video co-pilot already uses
(`_resolve_producer_client` → `kie_unified.get_text_client_for_tenant`: direct
Anthropic key first, else the Kie.ai key, friendly "add a key" message only if
neither exists) and `producer_prompt.call_producer` drives whichever client
comes back through its shared `.client.messages.create(...)` shape. Proven
in-sandbox: source trace (both entry points call the shared resolver, the old
`anthropic_api_key` hard-gate is gone from both) + 6 new unit tests
(`tests/functional/test_producer_kie_fallback.py`) covering client resolution
(Kie-only → `KieClaudeClient`, both-keys → `AnthropicDirectClient` still wins,
neither → `None` not a raise) and `call_producer` driving a fake resolved
client without an `api_key`. What's NOT provable without a paid key is the
full live turn:
- [ ] **Fresh tenant, Kie key only:** create/use a tenant with ONLY a Kie.ai
      key configured (no Anthropic key in Vault). Complete onboarding, then
      type an idea on the home chat (or let onboarding hand off to the
      producer with a typed idea). Expected: a normal production plan comes
      back — no "add an Anthropic key" wall, no 500, no silent hang.
- [ ] Confirm the assistant's plan-turn reply includes the soft **Tip:** line
      ("add an Anthropic key too... for the sharpest possible plans") — visible
      but not blocking, and only appears once per conversation (ask a
      follow-up in the same conversation and confirm the tip doesn't repeat).
- [ ] **Anthropic-key tenant unaffected:** same test on a tenant with an
      Anthropic key configured — plan comes back with NO Kie tip line (control
      case, proves the hint is gated correctly).
- **Cost:** one small producer text call on Kie's Claude endpoint (~$0.01-0.05
  equivalent) — negligible. **No image/video/YouTube spend, no publish needed.**
- **Safety net:** `_resolve_producer_client` only ever returns `None` (never
  raises) when both keys are missing, so a live failure here degrades to the
  existing friendly key-prompt message, not a crash.

---

## C05 — docked co-pilot accepts file attachments · live drop confirmation
The docked co-pilot (`ChatCore.tsx` with `docked`) silently swallowed file
drops two ways: `attachFiles` hard early-returned `if (docked) return;`, and
the docked `<Composer>` render never even received the
`attachments`/`uploading`/`onAttach` props — so there was no attach
affordance in the dock at all, only in the home chat. Both are fixed:
- the docked `<Composer>` now gets the same props as the home composers, so
  drag-drop, paste, and the paperclip button all render in the dock;
- `attachFiles` no longer early-returns for `docked`, and passes `videoId`
  through to `uploadChatAsset`;
- `POST /api/chat/upload` (`storyengine/backend/routes/chat.py`) takes an
  optional `video_id` form field, verifies the video belongs to the tenant,
  and persists it on the new `chat_assets.video_id` column (migration
  `085_chat_assets_video_id.sql`, applied live to `wrromlupsmyzrrcqlucn` —
  confirmed present via `information_schema.columns`);
- `_handle_copilot` now calls the same `_attach_assets` helper the home flow
  uses on `body.attachments`, and folds `_assets_brief(...)` into the summary
  fed to both the agent brain and the legacy classifier, so a follow-up
  message can reference a dropped file.

Proven in-sandbox: source trace (request → `/api/chat/upload` handler →
`chat_assets` INSERT with `video_id`; docked turn → `_handle_copilot` →
`_attach_assets` → `_assets_brief` → prompt), `npx tsc --noEmit` clean,
`python -m py_compile routes/chat.py` clean, `pytest -k "chat or upload"` (5
passed), column confirmed live via MCP `execute_sql` introspection. What's
NOT provable without a running app + browser:
- [ ] **Open a video's co-pilot dock** (any video's pipeline page, the
      docked chat panel) and **drop a PNG** onto the composer (drag-drop or
      the paperclip button). Expected: an upload progress spinner, then an
      attachment chip appears — no silent no-op.
- [ ] Query `chat_assets` for that row and confirm `video_id` matches the
      video the dock was open on (`kind = 'image'`, `video_id` set, not
      NULL).
- [ ] Send a follow-up message referencing the drop (e.g. "use that image I
      just dropped as a reference for scene 2") and confirm the copilot's
      reply acknowledges the file (it should show up in
      `_assets_brief`'s "FILES THE CREATOR DROPPED..." block fed to the
      model) rather than asking "what file?".
- [ ] **Home chat unaffected:** drop a file on the home (un-docked) chat and
      confirm it still uploads and attaches exactly as before (no
      `video_id` on that row).
- **Cost:** free — just an upload + a read-only chat turn, no paid
  generation triggered by a drop alone.
- **Safety net:** `video_id` is fully optional end to end (Pydantic field
  defaults to `None`, DB column nullable, upload route ownership-check
  fails soft to unscoped) — a mismatched frontend/backend deploy order
  degrades to "upload works, just not video-scoped," never an error.

---

## Running these from a VPS session (the intended runner)

A session ON the VPS has the Kie key + `scripts/se.sh` tooling + prod DB — everything the build sandbox lacked. Before running any C02 check, make sure the VPS is on the code that contains the fix:

1. **Confirm C02 is deployed.** C02 is on `main` (commit `ef7fcbf`+earlier). Main auto-pulls hourly, but confirm/force it: check the running commit (`se health` / `se logs backend`); if it predates `16aec80`, deploy per the storyengine/CLAUDE.md ladder — push main, `se deploy <session> [--with-frontend]`, **ask Ryan first** (live system, honor `~/deploy.lock`). Migration `084` (`assets.image_model`) is already applied; `083` (RLS) auto-applies on the backend restart that a deploy triggers.
2. **Money rule (hard):** the picture generation below is PAID (~$0.025/image). Per storyengine/CLAUDE.md, get a cost quote + an explicit yes before triggering it — even here. One image per model is enough.
3. **Run the C02 checks:** set the Pictures model to z-image on a test video (app UI via `se devtoken` login, or set `videos.image_model_override` directly), generate one panel, then verify both ends:
   - DB: `se db "SELECT id, image_model FROM assets WHERE video_id='<test-vid>' ORDER BY created_at DESC LIMIT 3"` → expect `image_model = 'z-image'`.
   - Payload: `se logs backend 200` around the generation → the Kie task names the z-image model.
   - Then repeat for `nano-banana-2`, and confirm a no-override video still records `gpt-image-2`.
4. **Tick the boxes above** with the evidence (the `se db` row + a log snippet), commit, and note who/when.

## Maintenance
- Newest chunk at the top of its section; keep the C0x/C1x ordering.
- When every box for a chunk is ticked, note the date + who ran it and leave it (don't delete — it's the audit trail that the deferred `[V]` was actually closed).
- Referenced from the loop handoff in `tasks/todo.md` and the doc inventory in `tasks/storyengine-knowledge-map.md` §4.
