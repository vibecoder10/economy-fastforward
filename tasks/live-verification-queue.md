# Live Verification Queue

**Why this exists:** the build loop runs in an isolated sandbox with **no Kie/image-service key and no route to the production VPS** (HTTPS-proxy-only network, no SSH). So any `[V]` step that needs a real paid API call or the running prod backend can't execute here — it's verified at **test + code-trace** level in the sandbox and the live confirmation is deferred to this list. Nothing is skipped; it's parked with an exact recipe.

**Who runs these:** Ryan in the app (a tap-through is enough for most), or a VPS-capable session. Tick an item once its evidence is captured. Add new rows here whenever a chunk's `[V]` can only be partially done in-sandbox — same commit as the chunk.

**Safety context:** every deferred item below already has (a) the default/no-op path proven unchanged by tests, and (b) a fallback or bypass so a live failure degrades gracefully rather than breaking prod. These live checks are *confirmation*, not load-bearing gates.

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
