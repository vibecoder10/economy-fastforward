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

## Maintenance
- Newest chunk at the top of its section; keep the C0x/C1x ordering.
- When every box for a chunk is ticked, note the date + who ran it and leave it (don't delete — it's the audit trail that the deferred `[V]` was actually closed).
- Referenced from the loop handoff in `tasks/todo.md` and the doc inventory in `tasks/storyengine-knowledge-map.md` §4.
