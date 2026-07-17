# Live Verification Queue

**Why this exists:** the build loop runs in an isolated sandbox with **no Kie/image-service key and no route to the production VPS** (HTTPS-proxy-only network, no SSH). So any `[V]` step that needs a real paid API call or the running prod backend can't execute here — it's verified at **test + code-trace** level in the sandbox and the live confirmation is deferred to this list. Nothing is skipped; it's parked with an exact recipe.

**Who runs these:** Ryan in the app (a tap-through is enough for most), or a VPS-capable session. Tick an item once its evidence is captured. Add new rows here whenever a chunk's `[V]` can only be partially done in-sandbox — same commit as the chunk.

**Safety context:** every deferred item below already has (a) the default/no-op path proven unchanged by tests, and (b) a fallback or bypass so a live failure degrades gracefully rather than breaking prod. These live checks are *confirmation*, not load-bearing gates.

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
