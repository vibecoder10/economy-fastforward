# Live Verification Queue

**Why this exists:** the build loop runs in an isolated sandbox with **no Kie/image-service key and no route to the production VPS** (HTTPS-proxy-only network, no SSH). So any `[V]` step that needs a real paid API call or the running prod backend can't execute here — it's verified at **test + code-trace** level in the sandbox and the live confirmation is deferred to this list. Nothing is skipped; it's parked with an exact recipe.

**Who runs these:** Ryan in the app (a tap-through is enough for most), or a VPS-capable session. Tick an item once its evidence is captured. Add new rows here whenever a chunk's `[V]` can only be partially done in-sandbox — same commit as the chunk.

**Safety context:** every deferred item below already has (a) the default/no-op path proven unchanged by tests, and (b) a fallback or bypass so a live failure degrades gracefully rather than breaking prod. These live checks are *confirmation*, not load-bearing gates.

---

## ⚡ WHEN YOU'RE AT THE COMPUTER / VPS RUN — do these first (Ryan)

1. **💰 Confirm the Veo 3.1 price (the one real money unknown).** Public pages conflict: Veo 3.1 Fast = **$0.40 or $0.30**, Veo 3.1 Quality = **$2.00 or $1.25** per 8s clip — and Veo Quality is by far the priciest model, so getting it right matters most. Generate ONE Veo clip on a test video, then read the Kie dashboard's credit-consumption log for that task (credits × $0.005 = the true price). Update `CLIP_PRICE_BY_MODEL`/`MODEL_REGISTRY.cost_per_clip` for veo-3.1-fast/quality in `skills/video-pipeline/shared/channel_profile.py`. Same one-clip-and-read for **Grok Imagine**, **Kling 3.0 Pro**, **Runway Gen-4 Turbo** if you wire them (details in §C09 below).
2. **🎙️ Confirm the ElevenLabs voice rate.** The ledger meters voice by REAL character count (accurate) but at an UNCONFIRMED **$0.30/1,000 chars** — ElevenLabs bills by a monthly character allowance tied to your plan, doesn't return a per-call cost, and it's your own (BYOK) key, so the true effective rate is per-account. Generate one voiceover, note the character count the ledger recorded (`se db "SELECT units, actual_cost FROM generation_ledger WHERE stage='voice' ORDER BY created_at DESC LIMIT 1"`), then check your ElevenLabs dashboard/usage for that account's real $/1,000-chars (or overage rate) and update `VOICE_PRICE_PER_1K_CHARS` in `skills/video-pipeline/shared/channel_profile.py` if it differs.
3. **🧾 One cheap picture-gen tests the WHOLE cost chain at once.** Generating a single scene's pictures (~$0.05–0.30) lights up C07-style ledger writes AND C08 image pricing AND C10's Est→Actual chip/drawer in one shot — do it on a test video and walk §C07/§C08/§C10 together instead of separately.
4. **🤖 MCP go-live (§C29 below).** Once C25a's held branch is folded into a coordinated deploy anyway (item 1/2/3 above are also good excuses to do that deploy), flip `MCP_ENABLED=true` and run the full external-client loop — see **§C29** for the exact ordered recipe. This is the ONE runbook for C26/C27/C28/C29/C47's combined live checks; don't chase them as five separate to-dos.
5. Everything else below is read-only or a light tap-through — knock them out while the account is already being spent.

---

## C52 — autopilot proposals surface (P4.2-c) · needs a real tenant with a live DB + running app

Everything is proven at the unit/code-trace level in the sandbox (27 new tests,
`tests/test_c52_autopilot_proposals_surface.py`, non-vacuous via `git stash`; full suite 1714P/15F/1E,
zero new failures vs. the 1687P/15F/1E baseline) — but the sandbox has **no `DATABASE_URL`** (backend
can't even start) and **no route to the VPS**, so no Playwright run happened here. What's deferred:

1. **A propose_only proposal actually appears.** On a tenant with `dial_level='propose_only'` (the
   default — every tenant today) and at least one qualifying `competitor_videos` candidate, either wait
   for the next autopilot cadence tick or force one (`python -m autopilot.autopilot --force`-equivalent
   / directly call `autopilot_launch.auto_launch_best_candidate(tenant_id)`), then:
   - `se db "SELECT id, video_title, confidence_score, status FROM autopilot_proposals WHERE tenant_id='<uuid>' ORDER BY created_at DESC LIMIT 3"` → confirm a new `status='proposed'` row.
   - `se db "SELECT bot_name, status, message FROM bot_activity WHERE tenant_id='<uuid>' AND bot_name='autopilot_proposal' ORDER BY created_at DESC LIMIT 1"` → confirm the notify row landed (the "notify" mechanism this chunk reused — no new infra).
2. **UI round-trip.** Open `/autopilot` in the app (real login or `se devtoken`): confirm the new
   "Proposals" card shows the row from step 1 (title, confidence score + the VPH/Freshness/Intel
   breakdown line, "proposed Xh/d ago"), and the header's gold "N proposals pending" pill matches the
   `pending_proposals_count` the summary now returns.
3. **Accept, live.** Tap Accept on that row: confirm (a) the row disappears from the pending list, (b)
   a new `videos` row exists with `source LIKE 'autopilot%'` and the SAME `candidate_id`'s title, (c) the
   pipeline actually starts (research kicks off — check `bot_activity`/the pipeline task poller), (d)
   `autopilot_proposals.status='accepted'`, `decided_by='<your email>'`, `video_id` set to the new video,
   and (e) you land on `/pipeline/<video_id>`.
4. **Kill switch refuses accept.** With `autopilot_config.kill_switch_tripped_at` set on the tenant (hand
   -set it or trip it for real per C54/C56's mechanism once that lands), confirm accept on a proposal
   returns the "kill switch is tripped" message and the proposal is STILL `status='proposed'` afterward
   (`se db` check) — i.e. it wasn't silently consumed.
5. **Dismiss, live.** Tap Dismiss on a different proposal: confirm it disappears from the pending list
   and `se db` shows `status='dismissed'`, `decided_by` set, `video_id` still NULL.
6. **MCP parity (only if `MCP_ENABLED=true`, folds into the C29 runbook).** Call `list_autopilot_proposals`
   / `accept_autopilot_proposal` / `dismiss_autopilot_proposal` from a real connected client; confirm
   `accept_autopilot_proposal` needs no confirm_token (runs immediately) and the accepted row's
   `decided_by='mcp_agent'`.
- **Cost:** proposal creation/accept/dismiss/list are all free DB reads/writes at THIS layer — accepting
  a proposal starts the SAME research-then-advance pipeline `launch_candidate` already runs unguarded
  today (a manual Launch click has zero cost gate at this layer either), so the actual spend, if any,
  happens later at each PAID stage's own confirm gate exactly as it would from any other door. No new
  cost category.

---

## C54 — per-tenant weekly budget ceiling + kill-switch writers + queue-drain gap (P4.2-e) · needs a real tenant with a live DB + running app

Everything is proven at the unit/code-trace level in the sandbox (29 new tests,
`tests/test_c54_weekly_budget_kill_switch.py`, plus 4 changed/added in `tests/test_c51_candidate_auto_
launch.py`; non-vacuous via `git stash`; full suite 1752P/15F/1E, zero new failures vs. the 1720P/15F/1E
baseline) — but the sandbox has no `DATABASE_URL` and no route to the VPS, so no Playwright run and no
real-money budget breach happened here. What's deferred:

1. **Set a real weekly cap and watch it breach.** On a real test tenant with `dial_level='auto_draft'`
   (so autopilot can actually spend): set a small cap via the `/autopilot` page's new Autonomy & Budget
   card (e.g. `$1`), or `POST /api/autopilot/config {"weekly_budget_cap": 1}`. Let a real paid stage run
   (or hand-insert a `generation_ledger` row with `actual_cost > 1` for that tenant to fake the breach
   without spending real money) then force an autopilot tick and confirm:
   - `se db "SELECT dial_level, weekly_budget_cap, weekly_spend_reset_at, kill_switch_tripped_at, kill_switch_reason FROM autopilot_config WHERE tenant_id='<uuid>'"` → `kill_switch_tripped_at` is now set, `kill_switch_reason` mentions the cap/spend numbers.
   - `se db "SELECT bot_name, status, message FROM bot_activity WHERE tenant_id='<uuid>' AND bot_name='autopilot_kill_switch' ORDER BY created_at DESC LIMIT 1"` → the trip notify landed.
   - The NEXT autopilot tick does nothing for this tenant — neither a queue-drain launch nor a candidate
     proposal/launch appears — confirming the queue-drain gap fix actually holds live, not just in the
     monkeypatched test.
2. **UI round-trip for the kill-switch banner.** Open `/autopilot`: confirm the red "Autopilot kill
   switch tripped" banner renders with the real reason + relative time, and every other autopilot
   surface (Proposals, Top Recommendations) still renders normally underneath it (the banner doesn't
   replace the page).
3. **Re-enable, live.** Tap "Re-enable" on the banner (or `POST /api/autopilot/kill-switch/reset`):
   confirm (a) the banner disappears, (b) `se db` shows both `kill_switch_tripped_at`/`kill_switch_
   reason` back to NULL, (c) a `bot_activity` row exists naming who cleared it
   (`message LIKE 'Kill switch re-enabled by%'`), and (d) the NEXT autopilot tick resumes normally (if
   the underlying spend is still over cap, it should re-trip on the very next tick rather than running
   unattended again — confirms clearing the switch doesn't bypass the budget check itself).
4. **Weekly window rolls over.** Hand-set `weekly_spend_reset_at` to 8+ days ago for a tenant with ledger
   rows both before and after that timestamp; call `GET /api/autopilot/summary` and confirm (a)
   `weekly_spend_reset_at` in the DB rolled forward to ~now, and (b) `config.weekly_spent` only reflects
   spend AFTER the new reset point (not the old one).
5. **Dial selector + budget cap UI.** On `/autopilot`, click each of the 3 Autonomy options and confirm
   the active one highlights + persists on reload; edit the Weekly Budget Cap field, save a value, reload
   and confirm it round-trips; clear it back to blank and confirm "no cap set" reappears.
6. **MCP parity (only if `MCP_ENABLED=true`, folds into the C29 runbook).** Call `set_autopilot_dial`
   (both fields, then just one, then a bad `dial_level` to confirm the 400-equivalent error) and
   `reset_autopilot_kill_switch` from a real connected client; confirm neither needs a `confirm_token`
   and both changes are visible immediately via `get_autopilot_dial`/`GET /api/autopilot/summary`.
- **Cost:** the budget check/trip/clear/dial-set writes are all free DB reads/writes at THIS layer — no
  new spend category. The actual spend this chunk gates continues to happen at each PAID stage's own
  confirm gate exactly as before; this chunk only adds an earlier stop sign in front of the unattended
  paths (queue drain, auto_draft launch).

---

## C36 — budget ceiling + cold-start card + checkpoint-audio · needs a real tenant, a real chat turn, real UI

Everything in C36 (checklist §3.3) is proven at the unit/code-trace level in the sandbox (27 new
tests, `test_c36_budget_cap.py`/`test_c36_confidence_telemetry.py`/`test_c36_cold_start_and_
checkpoint_audio.py`); migration 103 (`videos.max_spend`) is already applied LIVE. What's deferred:

1. **Budget cap end-to-end.** On a real test video: set a small cap (e.g. "cap this video at $1" in
   chat, or the new Budget cap field on the Script/Voice tab), then run/continue a build past it.
   Confirm (a) the confirm card shows "Do it anyway · $X" with the breach message when a quote would
   exceed the cap, (b) an autobuild that hits the cap mid-chain pauses with the "Paused — you've spent
   $X against your $Y cap" message (not silently continuing, not failing), and (c) clearing the cap
   ("remove the cap") lets a paused build resume with "keep going". Free to check on a near-zero cap —
   no need to actually let real spend accumulate first.
2. **Cold-start card.** On a genuinely fresh tenant with zero competitors added (or a test tenant with
   `competitor_videos` cleared), open the home chat cold — confirm the "Add 3 competitors now" card
   appears alongside the greeting (not just the generic dragon-video example), tapping "Add" prompts
   for URLs, pasting URLs kicks off `analyze_competitors` and acks, and "Not now" falls through to the
   ordinary greeting cleanly.
3. **Checkpoint-audio.** Run a normal chat "build it" to the pictures-review checkpoint (no explicit
   voice request) on a test video, then open the Scenes tab: confirm the pictures render (no "Voice
   Required" block) with the new "No voice yet — that's expected here" advisory banner, and that the
   chat's own message says "(no voice yet, that's next)" rather than implying audio already exists.
- **Cost:** budget-cap check is near-zero (cap it at $0.01 to force the breach instantly, no need to
  actually spend); cold-start and checkpoint-audio checks are free (read-only / one cheap build to a
  checkpoint you'd run anyway).

---

## C29 — StoryEngine MCP go-live runbook · the ONE recipe for C26/C27/C28/C29's live checks

**Why this is one runbook, not four:** C26 shipped the MCP endpoint + agent tokens, C27 the full tool
set + money gate, C28 the Settings UI + attribution chip — all SHIPPED DARK (`MCP_ENABLED` unset in
prod today, `routes/mcp.py` structurally doesn't exist). Every one of those chunks deferred its live
check to "after the coordinated deploy + flag flip" — they're the SAME deploy and the SAME flag, so
they get walked together, once, here. C29's own sandbox half is
`storyengine/backend/tests/functional/test_c29_mcp_full_session_dry_run.py` (11-step simulated
session against the real ASGI app + real HTTP + real auth/money-gate code, executor/DB stubbed —
see that file's docstring for exactly what's real vs. stubbed). This section is the OTHER half: the
live recipe, since a real coordinated deploy + a real external MCP client can't run in the sandbox
(no route to the VPS, no MCP client installed there).

**Cost cap for this whole runbook: ~$1–2.30, cheapest models, NO finalize on a premium clip model
unless Ryan explicitly chooses one.** See step 5's breakdown for the honest per-line estimate; step
5b (C47 setup + ingest) adds ~$0.10-0.30 on top (learn_channel_start's BYOK spend — everything else
in that step is free).

### Step 1 — Coordinated deploy, including C25a's held branch

MCP_ENABLED can't safely flip until C25a's media-proxy tenant-auth fix (`claude/c25a-media-auth-hold`,
commit `0460cb2`) is ALSO on main — the MCP read tools return `video_summary`/scene data that, once a
real client is poking around, makes it that much more likely someone asks for a thumbnail or a
scene image next, and the media proxy needs its tenant-auth fix live before that happens over a
door with no browser session backing it. Fold both into ONE `--with-frontend` deploy (VPS Deploy
Coordination Rule §1, `~/deploy.lock` held for the duration):
1. Merge `claude/c25a-media-auth-hold` to main (see **§C25a above** for its own required post-deploy
   browser check — do that FIRST, before touching the MCP flag, so a media-proxy regression isn't
   confused with an MCP one).
2. `push main` from the local Mac, then `scripts/se.sh deploy <session> --with-frontend` (ask Ryan
   first — live system).
3. **Expected result:** `se health` shows the new commit; `/api/mcp` still 404s (flag not flipped
   yet — confirm this BEFORE step 2 below, so you know the dark-by-default mechanism itself is
   intact post-deploy, not just pre-deploy).
- **Rollback:** nothing MCP-specific to roll back yet — this is a normal deploy. If C25a's own
  browser check fails, that's `--with-frontend`'s existing rollback path (redeploy prior commit),
  independent of MCP.

### Step 2 — Flip `MCP_ENABLED=true`

1. On the VPS, add `MCP_ENABLED=true` to `storyengine/.env` (the PARENT env file, per
   storyengine/CLAUDE.md — NOT `backend/.env`).
2. `scripts/se.sh restart backend` (never raw `pkill -f uvicorn` — see the VPS Deploy Coordination
   Rule and storyengine/CLAUDE.md's hard rule).
3. **Expected result:** `se logs backend` shows a clean restart; `curl -s -o /dev/null -w "%{http_code}"
   https://<domain>/api/mcp` (no auth header) now returns `401` (route exists, auth required) instead
   of `404`. `/api/agent-tokens` was already live since C26 (unconditional) — unaffected.
- **Rollback (the whole point of shipping dark):** unset `MCP_ENABLED` (or set it back to `false`) +
  `se.sh restart backend` — the router stops being registered at all, back to a structural 404,
  same as before this step. No migration to reverse, no data to clean up (agent_tokens/
  mcp_confirm_tokens tables stay, harmlessly unused).

### Step 3 — Mint a token in Settings → Agent access

1. Log into the app as Ryan (or `se.sh devtoken` for local dev against prod API), go to
   **Profile → Agent Access** (C28's tab, between API Keys and Billing).
2. "Create token" → name it something identifiable (e.g. "C29 live verify") → copy the plaintext
   `se_agent_...` value shown in the modal — **it is shown exactly once** (C28's plaintext-once
   discipline; closing the modal and reopening will NOT show it again — mint a new one if lost).
- **Expected result:** the token appears in the list (name, "just now" last-used blank, no revoked
  badge). **Rollback:** none needed — an unused token costs nothing; revoke it in step 6 either way.

### Step 4 — Connect a real MCP client

**This step is where C26's deferred "does a real client need more than bare JSON-RPC-over-POST"
question (`routes/mcp.py`'s own module docstring, "Protocol shape (justified)") actually gets
answered — it could not be answered in the sandbox at all.** v1 is a single `POST /api/mcp` JSON-RPC
2.0 endpoint (`initialize`/`tools/list`/`tools/call`), no SSE stream, no `Mcp-Session-Id` transport
negotiation. Point a real client at it and watch what happens:

- **Claude Code CLI** (`claude mcp add`) or a project-level `.mcp.json` — the HTTP transport shape:
  ```json
  {
    "mcpServers": {
      "storyengine": {
        "type": "http",
        "url": "https://<your-storyengine-domain>/api/mcp",
        "headers": {
          "Authorization": "Bearer se_agent_<paste-the-token-from-step-3>"
        }
      }
    }
  }
  ```
- **Claude Desktop / claude.ai remote connectors** — same URL + bearer header, wherever that client's
  UI takes a custom MCP server URL + auth header (exact UI varies by client version — this is the
  one part of this recipe that may need adjusting live, since MCP client configuration surfaces
  change).
- **Hermes** (or any other MCP-capable agent) — same shape: URL + `Authorization: Bearer <token>`.
- **Expected result — 3 possible outcomes, all worth recording:**
  1. **Connects cleanly, `tools/list` populates.** Bare JSON-RPC-over-POST is sufficient for this
     client — note which client, so the next person doesn't re-litigate this.
  2. **Client refuses to connect / hangs waiting for an SSE handshake.** This is the "does it need
     the fuller Streamable HTTP transport" answer landing as YES for that client — real follow-up
     work (add the SSE half of Streamable HTTP to `routes/mcp.py`), not a bug in what shipped.
  3. **Connects but a specific call shape differs from what a hand-rolled JSON-RPC client (like
     C29's dry-run test) sent.** Note the diff — most likely candidate is content-type or a header
     the real client insists on that curl/TestClient didn't need.
- **Rollback:** disconnect the client / delete the `.mcp.json` entry — no server-side state changes
  from merely connecting (only `tools/call` mutates anything, and every paid one is quote-gated).

### Step 5 — Run the §7 example session live, ON A DISPOSABLE TEST VIDEO

Mirrors `tasks/storyengine-copilot-ux-map.md` §7's example conversation and C29's sandbox dry-run's
step order, for real:
1. **`create_video`** ("a 2-scene test video, any topic") → free, no cost. **Expected:** a real
   `videos` row, visible in the web UI too (proves the "no MCP-only shadow data" property — anything
   an agent creates is the SAME row the web UI reads).
2. **`draft_pass`** with NO `confirm_token` → expect a quote (cost + `confirm_token`). Read the
   quoted cost before doing anything else.
   - **Cost gate — confirm BEFORE calling confirm:** draft_pass prices at the draft-tier clip model
     (`_draft_tier_model_id()`, currently Grok Imagine's cheapest 6s tier from
     `skills/video-pipeline/shared/channel_profile.py`'s `MODEL_REGISTRY["grok-imagine"]
     .cost_per_clip`) = **$0.09/clip**. For a 2-scene test video: ~2 clips ≈ **$0.18**, plus
     whatever pictures those clips need (GPT Image 2 default, $0.05/image, or override to z-image
     at $0.004/image for a cheaper run — z-image is the cheapest wired image model, see
     `docs/cost-awareness.md`) — say 6–12 images ≈ **$0.03–0.60**. **Draft-pass subtotal: roughly
     $0.20–0.80** for a 2-scene test video.
3. Call `draft_pass` AGAIN with that `confirm_token` → dispatches for real. **Expected:** the web UI
   (GuidedNextStep running banner) shows the task running WITH the **"via agent: `<token name>`"
   chip** (C28's attribution seam) — this is the live proof C28's own deferred check needed; screenshot it.
4. **`finalize`** with NO `confirm_token` → another quote. **STOP AND READ THE QUOTED COST before
   confirming — do NOT finalize on a premium clip model (Veo 3.1 Quality, Seedance 2.0, ...) unless
   Ryan explicitly picks one for this test.** Finalize on the SAME draft-tier/cheapest model keeps
   this in the same ~$0.20–0.80 ballpark as draft_pass; a premium finalize could run **$6–50** per
   `docs/cost-awareness.md`'s clip table — that is explicitly NOT what this cheap smoke test is for.
5. Confirm `finalize` with the token. **Expected:** same "via agent" chip live in the UI while
   running.
6. **`get_ledger`** → **Expected:** real `generation_ledger` rows for both passes, `total_spent`
   matching what the UI's Est→Actual chip shows (C10) — this is C27's own deferred "live money-gate
   spot-check" (real quote → real spend → real ledger row, not a stubbed number).
7. Open the video in the web UI: **Expected:** the video's activity/task history shows entries
   attributed to the agent (not silently indistinguishable from a chat-driven run) — confirms
   `generation_claims.claimed_by` actually carried `agent:<token name>:<verb>` through the real
   pipeline executor, not just through the mocked `_run_pending_action` C29's sandbox test stubbed.
- **Total expected spend for this step: ~$0.50–1.50**, comfortably inside the ~$1–2 cap, assuming
  cheapest/draft-tier models both passes and a small (2-scene) test video. **Rollback:** none needed
  — this is real, intentional, capped spend on a disposable test video; delete the test video
  afterward if you don't want it cluttering the dashboard.

### Step 5b — Setup + ingest session (C47), same connected client, same token

**Why this rides the same runbook:** C47's setup/ingest tools are dark behind the SAME
`MCP_ENABLED` flag and the SAME `se_agent_...` token minted in Step 3 — nothing new to deploy,
flip, or mint. This step is free (setup tools) except one $0.10-0.30 BYOK line (learn_channel_start)
and reuses the SAME disposable test video from Step 5, or a fresh one — either is fine.

1. **Configure the channel** (setup tools, free):
   - `get_channel_dna` → expect the tenant's current identity (voice/hooks/structure if any DNA has
     been learned before, or a near-empty dict on a brand-new tenant — both are valid, not a bug).
   - `learn_channel_start` with no arguments (learns from whatever's already imported) → expect
     `{"started": true, "busy": false, "message": "...roughly $0.10-0.30..."}`. **Cost gate:** this is
     the one real-money line in this step — BYOK Anthropic/Firecrawl spend, ~$0.10-0.30, same as the
     Settings UI's own "learn this channel" button.
   - Poll `learn_channel_status` every 15-30s until `learning: false`. **Expected:** `learners` shows
     each learner's status (learned/skipped/failed) and `identity` carries the freshly-learned fields
     — the SAME digest the chat "learn this channel" turn renders.
   - `upsert_quality_rule` with `{"rule_id": "QL-TEST", "law": "Never claim a machine is the fastest without a cited source.", "severity": "warn"}` → expect the saved row back, `source` field = `"mcp_agent"` (check via `se db "SELECT rule_id, source FROM quality_rules WHERE tenant_id = '<tenant>' AND rule_id = 'QL-TEST'"`).
   - `list_quality_rules` → expect QL-TEST present. `deactivate_quality_rule` with that row's `id` →
     expect `{"status": "deactivated"}`; re-list to confirm `active: false` (harmless to leave
     deactivated, or delete via `se db --write "DELETE FROM quality_rules WHERE rule_id = 'QL-TEST'"`).
   - `set_render_style` with `{"video_id": "<test video>", "render_style": "animated"}` → expect
     `{"status": "updated", ...}`; confirm in the web UI's Script/Voice tab that the channel-look
     control now shows "Animated". `set_style_preset` similarly (any id from `list_style_presets`),
     confirmed the same way. Both are the exact PATCH `/api/videos/{id}` path the UI itself uses —
     the web UI updating live from an MCP-only write proves there's no shadow data path.
2. **Submit research** (ingest, free to run the tool itself — thinking already happened on your own
   Claude subscription, not billed by StoryEngine):
   - On a NEW test video (not one already past the research stage — this overwrites), call
     `submit_research` with a small hand-written payload, e.g. `{"video_id": "<id>", "payload": {"headline": "Test headline", "thesis": "Test thesis.", "executive_hook": "A test hook."}}` (a non-roster title — no `unit_roster` needed). **Expected:** `{"accepted": true, "status": "ready_for_scripting", ...}`; open the video in the web UI's Research tab and confirm the headline/thesis/hook you sent are what's shown — the SAME `research_payload` column the platform's own `research` verb writes.
   - Optional adversarial check: submit a payload with `"unit_roster": "not a list"` → expect an
     `isError: true` result naming `unit_roster` — proves the shape gate runs before any DB write
     (no half-saved row).
3. **Submit a script** (ingest — the "MCP economics" centerpiece):
   - On that same video (now `ready_for_scripting`), call `submit_script` with 2-3 short scenes, e.g.
     `{"video_id": "<id>", "scenes": [{"text": "Scene one narration..."}, {"text": "Scene two narration..."}]}`.
   - **Expected on a clean pass:** `{"accepted": true, "verdict": "pass", "scenes": 2, "status": "ready_for_voice", ...}`; open the Script/Voice tab and confirm the submitted text is there, `script_source` reads as an agent submission (not "user_supplied" — check `se db "SELECT script_source FROM videos WHERE id = '<id>'"` shows `agent_submitted`, never `user_supplied`), and the Quality Review card (if any rule warned) shows the same rule-by-rule shape a platform-generated script's review card shows.
   - **Expected on a deliberately bad submission** (e.g. one scene of just `"x"`, or text that trips
     an active hard-gate quality rule): `{"accepted": false, "verdict": "revise"/"regenerate", "violations": [...]}`; confirm NOTHING changed in the web UI (script/status untouched) — the reject-with-rule-list contract holding for real, not just in the sandbox's fake Claude client.
- **Total expected spend for this step: ~$0.10-0.30** (learn_channel_start only — everything else is
  free). **Rollback:** delete the test video/rule row if you don't want them cluttering the dashboard;
  no migration or flag to revert (same dark/on-flag posture as the rest of §C29).

### Step 6 — Revoke the token, confirm 401

1. Profile → Agent Access → Revoke the token minted in step 3 (confirm modal).
2. From the still-connected MCP client (or a bare curl with the old bearer value), make ONE more
   call (`tools/list` is enough, free, no side effects). **Expected: 401**, immediately — no
   propagation delay (S5-3: `agent_tokens.authenticate()` re-checks `revoked_at IS NULL` on every
   single call, no cache on the auth path itself — only the UNRELATED rate-limit tenant-bucketing
   cache has a 30s TTL, and that only affects which bucket a request counts against, never whether
   it's accepted).
- **Rollback:** none needed — revocation is the terminal, intended state. Mint a fresh token if you
  want to keep testing.

### Fold-ins — what this replaces

- **§C26's deferred check** ("does a real external MCP client actually connect, and does it need the
  fuller Streamable HTTP transport") — answered by **Step 4** above.
- **§C27's deferred check** ("live MCP-client full-loop verify... every paid step quote-gated, ledger
  rows written") — answered by **Step 5** above (draft_pass + finalize, both quote-gated, both
  ledger-verified).
- **§C28's deferred check** ("mint → copy → connect a real MCP client → chip appears on a live
  agent-driven run") — answered by **Step 5.3/5.5** above (the "via agent" chip, screenshotted live).
- **§C47's deferred check** ("does a real Claude session actually configure a channel and land a
  submitted script through the real quality gate, not just the sandbox's mocked critic") — answered
  by **Step 5b** above (learn_channel_start/status, a quality rule round-trip, render_style/
  style_preset live in the web UI, submit_research + submit_script's accept AND reject paths).

### §C26 / §C27 / §C28 / §C47 — see §C29 above

Each of these chunks' own deferred live-verification note (in `SYSTEM_STATE.md` and the checklist)
points here — this is the one runbook, not four separate fragments. Nothing below these headers;
this is a redirect, not a duplicate.

---

## C34b — voice + Slack de-globalization · needs a real ElevenLabs listen + a live Slack-silence check

**Why deferred:** the fix is proven correct in-sandbox with a fully monkeypatched vault/env (see
`test_c34b_voice_and_slack_tenant_isolation.py` — 12 tests, non-vacuous via `git stash`: 6 of 12
correctly fail against pre-fix code). What's NOT provable without hitting the real ElevenLabs API and
the real (shared) storyengine backend process: does a tenant with no configured voice actually
NARRATE in the stock "Rachel" voice rather than Ryan's clone, and does a live pipeline run on the SaaS
backend really produce zero Slack traffic even if a bot token exists somewhere in that process's env.
No paid generation is required beyond whatever a normal voice-stage run already costs (~$1-2/video,
ElevenLabs bills per character regardless of which voice id is used) — don't trigger one solely for
this check, piggyback on a real tenant's normal voice run.

1. **Stock-voice listen-check.** Pick (or create) a SaaS tenant with NO `elevenlabs_voice_id` set in
   Settings → API Keys. Run/re-run the voice stage on one of their videos, then listen to the
   resulting narration audio — it should sound like ElevenLabs' "Rachel" premade voice
   (`21m00Tcm4TlvDq8ikWAM`), not Ryan's own cloned voice. Cross-check server-side: the `[INIT]
   ElevenLabsClient OK (voice=...)` log line (`se logs backend`) around that run should read
   `voice=21m00Tcm4TlvDq8ikWAM`.
2. **Tenant's-own-voice still wins, live.** Same as above but for a tenant who HAS set their own
   `elevenlabs_voice_id` — confirm the log line shows their configured id, not the stock one, and
   the audio matches their chosen voice.
3. **Slack silence, live.** On the VPS, confirm `storyengine/.env` does not set
   `SLACK_NOTIFICATIONS_ENABLED` (it shouldn't; `.env.example` documents it as legacy-cron-only).
   Trigger a normal voice or thumbnail run for any SaaS tenant and confirm nothing posts to Slack
   (no new message in the retired C0A9U1X8NSW channel) even if `SLACK_BOT_TOKEN` happens to be set
   in that process's env for some other reason.
4. **Legacy cron pipeline, if Ryan wants his own Slack notifications back:** add
   `SLACK_NOTIFICATIONS_ENABLED=true` to `skills/video-pipeline`'s own `.env` (NOT storyengine's) and
   confirm one of the legacy cron notifications (e.g. `notify_voice_done`) posts again.

---

## C34c — thumbnail/title/category genericization · needs a real thumbnail render + a real upload

**Why deferred:** the fix is proven correct in-sandbox with fully monkeypatched clients/DB (24 tests —
19 in `skills/video-pipeline/thumbnail/tests/`, 5 in
`storyengine/backend/tests/functional/test_c34c_seo_category.py` — non-vacuous via `git stash`: 7/19 +
3/5 correctly fail against pre-fix code). What's NOT provable without a real Kie.ai image-generation
call and a real YouTube upload: does Template E actually RENDER as a clean, non-map, subject-focused
thumbnail image, and does a real upload's category actually land somewhere other than Education on
YouTube's own Studio UI.

1. **Template E render check (paid — ~$0.05-0.15 for 1-3 thumbnail variants, per
   `docs/cost-awareness.md`; get a cost quote + explicit yes first).** Pick a tenant with no channel
   thumbnail history and no finance/geopolitics niche configured (or set `channel_profiles.niche` to
   something like "cooking tutorials" for a test tenant), create a video whose title/summary is
   deliberately NOT geopolitical/person/split/symbolic (e.g. "5 Ways to Fix a Broken Sauce"), and run
   the thumbnail stage. Confirm: (a) the activity log / `se logs backend` shows `template_e` was
   selected, not `template_a`; (b) the resulting thumbnail image genuinely shows a food-related subject
   with no map, no country outlines, no satellite-view backdrop.
2. **Template A still reachable, live.** Same tenant/setup but with a video whose content IS
   geopolitical (e.g. mentions "trade route" or "chokepoint") — confirm the log shows `template_a`
   selected despite the tenant's non-finance niche (content-level `GEO_KEYWORDS` win).
3. **Ryan's legacy channel, live.** Confirm a real run of the legacy Airtable-only pipeline
   (`skills/video-pipeline/orchestrator`) still selects `template_a` for a typical Economy FastForward
   headline — no `CHANNEL_NICHE` env var exists in that process at all, so this exercises the
   content-only `GEO_KEYWORDS` path exactly as it ran before this chunk.
4. **Category persistence + upload, live.** Run `POST /api/videos/{id}/generate-seo` on a real video
   whose actual topic maps to a non-Education category (e.g. a gaming or entertainment video) —
   `se db "SELECT seo_category_id FROM videos WHERE id='<id>'"` should show the resolved numeric id
   (not `27`). Then run a real upload (unlisted draft is fine) and confirm in YouTube Studio that the
   video's category is NOT "Education" — it should match what `seo_category_id` held.
5. **Fallback still correct, live.** Pick (or leave) a video that predates migration 102 (or one where
   SEO was never generated) — `seo_category_id` should read `NULL` — and confirm a real upload still
   lands in Education, exactly as before this chunk.

---

## C33 — YouTube quota guard + own-video VPH · needs a real upload day + a real synced channel

**Why deferred:** the quota tracker (`youtube_quota.py`) and VPH derivation (`own_vph.py`) are
proven correct in-sandbox with an in-memory fake DB (unit accumulation, ceiling refusal at an
explicit 10k ceiling matching the checklist's "6 uploads then 7th blocked" scenario, fail-soft on
tracker errors, midnight-PT reset via monkeypatched `_pt_today()`, VPH fixtures with known
views/hours — see `test_c33_youtube_quota.py` / `test_c33_own_vph.py` / `test_c33_vph_wiring.py`).
What's NOT provable without a real deployment: does the counter actually survive a real day of
uploads without drifting, and does VPH look sane against a real synced channel. No paid generation
is required for either check below (quota: read the counter after normal use; VPH: read already-
synced numbers) — cost is $0.

1. **Quota counter sanity.** After a normal day of real use (whatever uploads happen naturally —
   don't force extra ones just to test this), `se db "SELECT * FROM youtube_quota_usage ORDER BY
   day DESC LIMIT 5"` and cross-check `units_used` against how many uploads actually happened that
   day (`se db "SELECT count(*) FROM videos WHERE upload_date::date = '<day>'"` × ~1600-1650).
   `GET /api/health` (no auth needed) should show `youtube_quota.units_used` matching the same
   number, and `youtube_quota.remaining` should equal `9000 - units_used` (or whatever
   `YOUTUBE_DAILY_QUOTA_CEILING` is set to in the VPS `.env`).
2. **Quota refusal, if/when a heavy upload day occurs naturally** (don't force it — 6+ real uploads
   in one day is unusual for a single-channel tenant): confirm the next upload attempt after the
   ceiling is hit returns the friendly "quota resets at midnight Pacific" message (check
   `background_tasks`/activity log for the upload stage's error text), not a raw YouTube 403.
3. **Own-video VPH sanity.** Pick a tenant with `/api/youtube/sync` run recently and at least one
   video with `last_analytics_sync IS NOT NULL`. Ask the copilot "how did my videos do?" (or the
   home producer) and confirm the "YOUR OWN PUBLISHED VIDEOS" answer includes a `~N/hr` VPH figure
   for videos published more than an hour ago, and correctly omits it (or the whole line reads
   sensibly without one) for anything unpublished or too fresh. Cross-check the number by hand:
   `se db "SELECT video_title, views, upload_date FROM videos WHERE tenant_id='<id>' AND
   last_analytics_sync IS NOT NULL"` → `views / ((now() - upload_date) in hours)` should match what
   the copilot said, within rounding.
4. **`avg_vph` on the by-style analytics panel.** Open `/analytics` as a tenant with 2+ synced
   videos sharing a style/render/script/clip-model choice, confirm the new "Avg VPH" column shows a
   `~N/hr` value for groups with real synced data and "no data yet" (dimmed) for groups without —
   same dependency as C30/C31's live checks above, so do this alongside those if the same tenant
   qualifies for both.

---

## C30 — preset/model performance aggregation · needs a tenant with real multi-preset synced analytics

**Why deferred:** `analytics_by_style.get_style_performance()` and `GET /api/analytics/by-style` are
proven correct in-sandbox with stubbed rows (grouping, NULL/no-data-yet handling, fail-soft,
one-source brief/endpoint agreement — see `test_c30_style_performance.py`), but "does it aggregate
SENSIBLY against a real channel's data" needs an actual tenant with (a) 2+ videos published under
different `style_preset_id`/`render_style`/`script_profile` values, and (b) synced YouTube analytics
(`last_analytics_sync IS NOT NULL`) on at least some of them. No migration was needed for this
chunk, so there's no `information_schema` proof to run here — this is the ONLY outstanding check.

1. Confirm the tenant has run `/api/youtube/sync` recently (`se db "SELECT count(*) FROM videos
   WHERE tenant_id='<id>' AND last_analytics_sync IS NOT NULL"` should be > 0). If it's 0, run a
   sync first (read-only, no cost).
2. `curl -H "Authorization: Bearer <token>" https://<host>/api/analytics/by-style | jq` — check that
   `by_style_preset`/`by_render_style`/`by_script_profile` groups match what `se db "SELECT
   style_preset_id, render_style, script_profile, ctr, avg_retention, views FROM videos WHERE
   tenant_id='<id>' AND deleted_at IS NULL"` shows by eye (same choices, plausible averages, spend
   roughly matching `se db "SELECT video_id, SUM(actual_cost) FROM generation_ledger WHERE
   tenant_id='<id>' GROUP BY video_id"`).
3. Ask the in-video copilot "which look/model earns the most views on my channel?" (or the home
   producer) and confirm the answer cites the SAME numbers the curl above returned — proves
   `channel_briefs._style_performance_brief` and the endpoint didn't silently drift apart in prod
   the way they can't in the test suite (same function, but worth the one live sanity check).
4. If the tenant has fewer than `MIN_SAMPLE=2` synced videos per group, expect (correctly) an empty
   `by_*` list / no citation from the copilot — that's the honest "not enough data yet" behavior,
   not a bug; don't force a false positive by lowering `MIN_SAMPLE` just to see numbers.

---

## C31 — "by style" analytics panel + producer LOOK citations · same data dependency as C30

**Why deferred:** same root cause as C30 above (no multi-preset synced-analytics tenant in the
sandbox) — this chunk is the UI/prompt half built ON TOP of C30's data layer, so it inherits the
same gap. Unit-level correctness (panel rendering logic, prompt composition) is proven in
`test_c31_style_citation.py` + a clean `npx tsc --noEmit` / `npm run build` (with
`NEXT_PUBLIC_API_URL` set) — what's NOT provable without real data is "does the panel actually
show real channel aggregates, and does the producer actually cite them unprompted."

1. Once the C30 checklist above confirms `GET /api/analytics/by-style` returns real multi-preset
   data for a tenant, open `/analytics` in the browser as that tenant and confirm: the new
   "Performance by Style" section renders (not stuck on the loading spinner or the "no data yet"
   empty state), all 4 dimension tabs (Look Engine / Channel Look / Script Voice / Clip Model)
   switch correctly, and a row with `synced_count === 0` shows the dimmed "no data yet" cells
   rather than a raw `0%`/`NaN%`.
2. In the home producer chat, ask for a video in a look this tenant already has real synced data
   for (e.g. "make me another holographic one") and confirm the assistant's LOOK recommendation
   text actually quotes a real number from the brief (not just "I have data on this" — the actual
   CTR/retention figure), and that it says NOTHING about channel performance for a tenant/look
   with no synced data (no fabricated stat).
3. Confirm the cost-per-1k-views column on the panel is arithmetically consistent with the ledger:
   spot-check one row's `total_spend`/`total_views` against `se db` directly.

---

## C25a — media proxy tenant auth · REQUIRED live browser check before the next `--with-frontend` deploy

**Why this is REQUIRED, not optional (unlike most rows below):** the fix (tenant-scoped
`_ALLOWLIST_SQL` + `serve_drive_file` now requiring a `?token=` on every Drive-backed
`<img>`/`<video>` url) closes a real cross-tenant leak (SYSTEM_STATE.md §C25a), but it also means
an OLD frontend (no `?token=` yet) against the NEW backend gets a 401 on every image the instant
the backend deploys — a real app-wide "every image blanks out" risk until the frontend redeploys.
This can't be proven safe from the sandbox (no browser, no prod backend route). Do NOT let this
ship as a backend-only hourly `git pull` — it must go out as a coordinated
`vps-deploy.sh <session> --with-frontend` (VPS Deploy Coordination Rule §1, lock file held for the
duration), and this check must run RIGHT AFTER that deploy, before calling it done:

- [ ] **Every image surface renders post-deploy.** Open (fresh page load, not a client nav so
      nothing is cached from before the deploy): Scenes workspace (storyboard grids + clip
      thumbnails), a chat conversation with a "show me scene N's boards" card (SceneBoardsGrid),
      Characters tab (portraits), Environments tab (references), Thumbnail tab, Render tab (final
      video preview `<video>` scrub/seek). Use `webapp-testing` (Playwright), not self-evaluation —
      screenshot proof, check for broken-image icons and console 401s on `/api/media/drive/*`.
- [ ] **A stale/cached OLD frontend tab, still open across the deploy, is acceptable collateral
      (documented, not silently ignored).** Confirm it degrades to broken images (not a crash) and
      that a hard reload recovers it — this is the known, accepted skew-window cost (SYSTEM_STATE
      §C25a "Deploy-safety assessment"), not a new bug to chase.
- [ ] **Backend-internal mint sites actually work live**, not just unit-tested: generate one
      talking-clip video (InfiniteTalk path, `pipeline_executor.py::_proxy_url`) and lock one
      character/environment cast sheet (vision rewrite path, `characters.py`/`environments.py`) —
      confirm both complete without a 401 from the media proxy in `se logs backend`.
- **Cost:** the talking-clip check above is a real generation — get a cost quote + explicit yes
  first per the Money rule, same as any other paid check on this list. Everything else (browser
  tap-through) is free.

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

## C15a — home Producer "Make it" tap quote · live tap-through check
Checklist §1.2 follow-up (2026-07-18 director-gap audit's MONEY GAP finding,
plus a same-day orchestrator review that caught the estimate ignoring the
plan's own length). `actions.estimate_plan_cost(video_length_minutes=None)`
now derives the real scene count from length via `VideoConfig.act_count`
(`skills/video-pipeline/orchestrator/pipeline_config.py:53` — the SAME
formula the live script generator targets, imported not re-derived) and
`routes/chat.py::_stamp_plan_estimate()` threads `plan.spec.
video_length_minutes` through, naming the scene count in the card text. All
covered at the unit level (12 tests in `test_c15a_plan_cost_quote.py`,
confirmed non-vacuous via `git stash` TWICE — the original fix and this
length-scaling follow-up; `npx tsc --noEmit` clean) — no live LLM call in
that pass (`call_producer` has no no-network path in this sandbox). What's
NOT provable without a live conversation:
- [ ] **Local E2E boot** (same recipe as C14/C15's entries above): source
      prod `storyengine/.env`, `DEV_MODE=true DEV_TOKEN=<random>
      DEV_TENANT_ID=<disposable tenant>`, uvicorn on :8002,
      `NEXT_PUBLIC_API_URL=http://127.0.0.1:8002 npm run dev -- --port 3002`.
- [ ] **Start a fresh home chat conversation** (no `video_id` yet — the
      un-docked producer flow, not the in-video co-pilot): describe a SHORT
      idea (nudge the length slider to ~1 min) through to phase `"plan"`,
      confirm the `ProductionPlanCard`'s "Estimated cost" line reads
      something like *"Making this ≈ $0.30 — pictures for ~1 scenes (rough
      estimate; refined once the script's written)."*
- [ ] **Repeat with a LONG idea** (nudge the length slider to ~20-30 min):
      confirm the estimate reads a VISIBLY LARGER figure (≈$1.80, capped at
      6 scenes) — not the same number the short plan showed. This is the
      exact bug the orchestrator review caught; confirming it moved is the
      point of this recipe.
- [ ] Confirm both numbers match `actions.estimate_plan_cost(minutes)` called
      directly in a Python shell for the same `video_length_minutes` (today:
      1 min→≈$0.30, 5 min→≈$0.90, 10 min→≈$1.50, 12-30 min→≈$1.80 capped) —
      i.e. neither is silently drifting from the source of truth.
- [ ] **Tap "Make it"** on the long plan: confirm the existing plumbing is
      completely unaffected — `create_video` fires, the video is created,
      the autobuild kicks off exactly as it did before this chunk (research
      → script → pictures, or script → pictures depending on channel mode),
      and the assistant's "I'm building it now…" message appears unchanged.
      Once the script is written, spot-check that the real scene count
      lands near what the quote named (exact match not required — the
      producer/creator can still steer the story; this is a sanity check
      that the estimate wasn't wildly off, not a hard assertion).
- [ ] **Regression check:** run through the onboarding ("Start Here") path
      that hands off into `_seed_producer` too, confirming the SAME
      length-scaled estimated-cost line appears there (both call sites must
      show it, not just the main intake turn).
- **Cost:** free through the plan/quote checks (no generation until "Make
  it" is tapped). Tapping "Make it" costs whatever the seeded channel's
  script + however many scenes × 6 pictures actually costs (~$0.30 for a
  1-scene short to ~$1.80+ for a capped-6-scene long video, GPT Image 2 2K
  default) — same spend the autobuild always incurred; this chunk adds
  visibility (now length-aware), not a new charge.
- **Safety net:** `estimate_plan_cost`/`_stamp_plan_estimate` are pure reads
  (no writes, no DB touched by the branch they exercise) layered onto a
  `plan` dict that already existed; the two new plan fields are additive and
  only ever populated when a plan is present — a stale frontend build (or a
  plan payload from before this fix) renders the exact pre-C15a card, and
  `_handle_approve`'s create+autobuild call chain is completely untouched.

---

## C15b — director review loop part 1 (show boards + approve scene) · live round-trip check
Checklist §1.2 (Ryan's Hermes-director vision, 2026-07-18). New `kind="show"`
copilot path (`routes/chat.py::_handle_show_op` + matching vocabulary in
`agent_brain.py`) surfaces a scene's pictures inline via a new `images` field
on the chat card, every URL run through new `_media_proxy_url`; new free
`approve_scene` verb (`actions.py`) flips one scene's `assets.status` to
`'approved'`. All covered at the unit level (18 tests in
`test_c15b_show_and_approve_scene.py`, confirmed non-vacuous via `git
stash`; `npx tsc --noEmit` + `npm run build` clean) — no live chat turn, no
real Drive-hosted image, and no live agent-brain LLM call in that pass (no
paid Anthropic/Kie key in this sandbox). What's NOT provable without a real
video with real pictures:
- [ ] **Local E2E boot** (same recipe as C14/C15/C15a's entries above):
      source prod `storyengine/.env`, `DEV_MODE=true DEV_TOKEN=<random>
      DEV_TENANT_ID=<disposable tenant>`, uvicorn on :8002,
      `NEXT_PUBLIC_API_URL=http://127.0.0.1:8002 npm run dev -- --port 3002`.
- [ ] **Open (or build) a video that already has pictures for at least 2
      scenes.** In the video's co-pilot dock, type "show me scene 2's
      boards" (or whatever scene has pictures). Confirm: a thumbnail grid
      renders inline in the chat bubble, each tile shows a real picture (not
      a broken-image icon), and opening the browser network tab shows every
      image request hitting `/api/media/drive/<id>` on the SAME origin —
      never a `drive.google.com` URL directly from the browser.
- [ ] **Ask for a scene with NO pictures yet** ("show me scene 19's boards"
      on a scene that hasn't generated): confirm the reply is the friendly
      "doesn't have any pictures yet — want me to generate them? (~$X)" line
      with a real, non-zero dollar figure — not a crash, not an empty card.
- [ ] **Scroll back up** through the conversation after a few more turns:
      confirm the scene-2 thumbnail grid is STILL rendered in its original
      message bubble (proves the "renders in every past turn, not just the
      newest" design — unlike the ephemeral confirm/prompt cards).
- [ ] **Say "approve scene 2"** (chat, in the same video): confirm the reply
      is "Scene 2 approved ✓ — N shots locked in…" with NO confirm-tap
      required (free verb), then verify directly in the DB (`se db "SELECT
      scene, status FROM assets WHERE video_id='<id>' ORDER BY scene,
      image_index"`) that ONLY scene 2's rows flipped to `'approved'` —
      every other scene's rows must be untouched.
- [ ] **Say "approve scene 2" again on a DIFFERENT tenant's video** (or a
      video with no scene 2): confirm it either approves that tenant's OWN
      scene 2 (never cross-tenant) or replies "doesn't have any pictures yet
      — nothing to approve there" if that scene has none.
- [ ] **Agent-brain path:** repeat the two chat turns above with a real
      Anthropic/Kie key configured (whichever the tenant already uses) so
      `run_copilot_brain` actually runs instead of silently falling back to
      the one-shot classifier — confirm both `kind="show"` and
      `verb="approve_scene"` are reachable through THAT path too, not just
      the fallback classifier the unit tests exercise directly.
- **Cost:** free — `show`/`approve_scene` are both read/free paths; the only
  spend possible in this recipe is if the creator accepts the "want me to
  generate them?" offer on an empty scene, which is the pre-existing
  per-scene "images" verb's own cost (~$0.30 for 6 shots at GPT Image 2 2K),
  not a new charge this chunk introduces.
- **Safety net:** `_handle_show_op` is a pure read (SELECT only, no writes);
  `approve_scene`'s only write is the single scoped `UPDATE` already unit-
  tested for its exact WHERE clause and bound params. The new `images` card
  field and `kind="show"`/`verb="approve_scene"` vocabulary are additive —
  a stale frontend build simply never renders the grid (text reply still
  lands), and a stale backend never emits the new kind/verb at all.

---

## C15c — director memory: durable preference store · live conversational round-trip check
Checklist §Phase 1 (Ryan's "a correction said once becomes standing"
vision, 2026-07-18). New `director_preferences` table (migration
`091_director_preferences.sql`, applied live via Supabase MCP, confirmed via
`information_schema.columns`), new `remember`/`forget` vocabulary in both
decision schemas (`agent_brain.py`'s tool-loop brain + `routes/chat.py`'s
fallback classifier for the in-video co-pilot, `producer_prompt.py`'s
`profile_ops` for the home producer), and a new "STANDING PREFERENCES"
hydration block in both chats' system prompts. All covered at the unit
level (38 tests in `test_c15c_director_memory.py`, confirmed non-vacuous
via `git stash`) — no live LLM call classified a real standing instruction
in that pass (no paid Anthropic/Kie key in this sandbox). What's NOT
provable without a real conversation:
- [ ] **Local E2E boot** (same recipe as C14/C15/C15a/C15b's entries above):
      source prod `storyengine/.env`, `DEV_MODE=true DEV_TOKEN=<random>
      DEV_TENANT_ID=<disposable tenant>`, uvicorn on :8002,
      `NEXT_PUBLIC_API_URL=http://127.0.0.1:8002 npm run dev -- --port 3002`.
- [ ] **Home producer chat:** say something with clear standing-instruction
      phrasing — e.g. "never use premium models on Poco" or "from now on,
      always suggest the watercolor look first." Confirm the reply reads
      like "Got it — I'll remember: ... Say 'forget that' any time to undo
      it," then verify directly in the DB (`se db "SELECT scope, text,
      active FROM director_preferences WHERE tenant_id='<id>' ORDER BY
      created_at DESC LIMIT 5"`) that a row landed with `scope='channel'`
      and `text` matching the creator's words VERBATIM (not paraphrased).
- [ ] **Fresh conversation, same tenant:** start a brand-new home chat
      conversation (not a continuation) and ask something the remembered
      preference would affect (e.g. ask for a Poco video and see if it
      avoids premium models, or ask a general question and see if the
      watercolor look gets suggested first). Confirm the preference is
      honored WITHOUT re-stating it — this is the actual "said once,
      remembered forever" proof, not just the DB row existing.
- [ ] **"What do you remember?"** in that fresh conversation: confirm the
      reply lists the preference(s) in plain English (numbered), sourced
      from the live table, not a hallucinated answer.
- [ ] **In-video co-pilot, video-scoped:** open a specific video's co-pilot
      and say something clearly about THIS video only (e.g. "the kitten in
      this video is gray, not orange"). Confirm the confirmation reply says
      "for this video" (not "channel-wide"), then verify the DB row's
      `scope` column holds that video's UUID, not `'channel'`. Open a
      DIFFERENT video's co-pilot and confirm that preference is NOT
      mentioned/honored there (proves the scoping actually isolates).
- [ ] **"Forget that":** in the same conversation, say "forget that" (or
      "forget #1" if multiple were listed). Confirm the reply names what
      was removed, then verify in the DB that the row's `active` flipped to
      `false` — NOT deleted (`SELECT active FROM director_preferences WHERE
      id='<id>'` should still return the row). Ask "what do you remember?"
      again and confirm that preference no longer appears.
- [ ] **Agent-brain path:** repeat the remember/forget turns above with a
      real Anthropic/Kie key configured so `run_copilot_brain` actually
      runs (in-video co-pilot) instead of falling back to the one-shot
      classifier — confirm `kind="remember"`/`kind="forget"` are reachable
      through THAT path too, not just the fallback classifier the unit
      tests exercise directly.
- **Cost:** free — remember/forget/list are all free, no-confirm-card paths;
  this chunk introduces zero new paid work.
- **Safety net:** `_save_preference`/`_deactivate_preference` are the only
  writes, both already unit-tested for exact query shape and bound params
  (`_deactivate_preference` soft-deletes only, never `DELETE`). The
  hydration block and `remember`/`forget` vocabulary are additive — a stale
  frontend needs no changes (chat text is the UI), and a tenant with zero
  saved preferences sees byte-identical prompts to pre-C15c (`_preferences_
  brief` returns `""` when there's nothing to hydrate).

---

## C15d — one director voice + data reach · live voice-feel + data-question check
Checklist entry (audit-found gap, 2026-07-18): the in-video copilot's tool
loop (`agent_brain.run_copilot_brain`) now opens its system prompt with
`producer_prompt.DIRECTOR_VOICE` — the SAME personality core the home
producer speaks in — and gained a read-only `channel_data` tool that reaches
the same competitor/performance/learnings briefs the home producer's "what
should I make next" already uses. Covered at the unit level (15 tests in
`test_c15d_voice_and_data_reach.py`, confirmed non-vacuous via `git stash`,
including a fake-client run that captures the ACTUAL system prompt sent to
the model) — no live LLM call was made in that pass (no paid Anthropic/Kie
key in this sandbox), so the following are unverified against a real model:
- [ ] **Local E2E boot** (same recipe as C15/C15a/b/c's entries above):
      source prod `storyengine/.env`, `DEV_MODE=true DEV_TOKEN=<random>
      DEV_TENANT_ID=<disposable tenant>`, uvicorn on :8002,
      `NEXT_PUBLIC_API_URL=http://127.0.0.1:8002 npm run dev -- --port 3002`.
- [ ] **Voice feels the same, not just prompt-text-identical:** open the
      home producer chat and ask a strategic question ("what should I make
      next?"); separately open an existing video's in-video co-pilot and
      ask the SAME question. A real model (not the unit tests' fake client)
      should read as ONE director in both places — same warmth, same
      willingness to push back/give an opinion, never saying "pipeline" /
      "stage" / "render" / "storyboard" in either transcript.
- [ ] **In-video "what should I make next?":** with a tenant that has
      synced `competitor_videos` rows, ask the in-video co-pilot this
      question. Confirm the reply names a specific scored pick (not a
      generic answer) — proves `channel_data` actually fired and its output
      reached the model's final answer, not just that the tool dispatches
      in isolation.
- [ ] **In-video "how are my videos doing?":** with a tenant that has
      `last_analytics_sync` rows on `videos`, ask the in-video co-pilot.
      Confirm the reply cites real view/CTR/retention numbers matching what
      the home producer's own "how's the channel" answer would cite for the
      SAME tenant — proves both surfaces read the identical data, not two
      different numbers.
- [ ] **No data yet, tenant with nothing synced:** ask the in-video
      co-pilot the same questions on a fresh/empty tenant. Confirm it says
      plainly there's no data yet (the `channel_data` tool's fail-soft
      string) rather than inventing a stat or crashing the turn.
- [ ] **Regression spot-check:** run a few of the copilot's existing
      this-video actions (e.g. "redo the thumbnail", "show me scene 2's
      boards", "approve scene 1") through a live model call and confirm the
      op/verb classification and confirm-card behavior are unchanged from
      before this chunk — the voice/tool additions must not have shifted
      the model's classification precision.
- **Cost:** free — `channel_data` (like all six agent_brain tools) is a
  read-only SELECT-and-format call; this chunk introduces zero new paid
  work and touches no confirm-card/spend path.
- **Safety net:** the voice change is prompt-text-only (no code branch
  depends on it); the `channel_data` tool is reachable only through the
  model's own tool-call loop, same trust boundary as the five tools already
  there, and its three underlying brief functions were already exercised
  fail-soft in production via the home producer's `_loop_brief` before this
  chunk moved them — this chunk only added a second caller, not new query
  logic.

---

## C16a — DB-backed generation claim (S7-1 + S7-6 fix) · live double-tap check
Checklist entry C16a (audit `docs/reports/2026-07-17-storyengine-agent-audit-
findings.md` §S7-1 CRITICAL + §S7-6 MED, sweep C16). New `generation_claims`
table (migration 092, live via Supabase MCP) + `generation_claims.py` module
now gate every chat-driven paid dispatch (`_handle_approve`'s autobuild
kickoff, `_run_pending_action`'s "build" verb, and its single-stage copilot
verb) and are consulted by the manual `routes/pipeline.py` routes too
(`_is_task_active` now checks `generation_claims.is_blocked` when the
in-process dict is clear). Covered at the unit level (31 tests across
`test_c16a_generation_claims.py` + `queue_recovery/
test_c16a_manual_routes_claim_check.py`, confirmed non-vacuous via `git
stash -u`) with a hand-rolled fake Postgres connection standing in for the
real `pg_advisory_xact_lock` + transaction — no live DB session was driven
through this in the sandbox, so the following need a real backend + DB:
- [ ] **Double-tap the "Make it" button** (home producer, ProductionPlanCard)
      twice in quick succession on the same plan. Confirm only ONE video +
      ONE autobuild run happens — `se db "SELECT count(*) FROM videos WHERE
      video_title='<test title>' AND created_at > now() - interval '2
      minutes'"` should show 1, not 2, and the second tap's UI should show
      the busy reply (or simply no visible second run) rather than a second
      "Building..." card.
- [ ] **Double-send a copilot action** (in-video co-pilot, e.g. type "redo
      the thumbnail" twice back-to-back before the first confirm-card
      resolves, or confirm the SAME pending action twice). Confirm the
      second attempt gets "I'm already working on that — I'll let you know
      when it's done." and `generation_ledger`/`assets` show only ONE new
      thumbnail row, not two.
- [ ] **Cross-surface conflict:** kick off a chat "build" (autobuild) on a
      video, then — while it's still running — click the manual "Generate
      Script" (or any main-lane) button for the SAME video in the UI.
      Confirm the manual click gets refused (409 / "Task already running")
      rather than racing the chat run — this is the actual S7-6 unification
      proof (chat's DB claim blocking a manual UI click).
- [ ] **Claim table sanity:** while a build is mid-run, `se db "SELECT
      tenant_id, video_id, stage, claimed_at FROM generation_claims"` should
      show exactly one row for that video/stage; after it finishes (success
      or failure), the row should be gone within a few seconds (release
      fires in the task's finally block, not on a timer).
- [ ] **Stale-claim self-heal (optional, slower):** if a claim is ever
      manually left behind (e.g. `se db --write "UPDATE generation_claims
      SET claimed_at = now() - interval '3 hours' WHERE ..."` on a test
      row), confirm the NEXT acquire attempt on that video/stage succeeds
      (the row is swept, not permanently wedged) — proves the 2h stale
      sweep works against a real Postgres transaction, not just the fake.
- **Cost:** near-zero — this is a concurrency/locking check, not a new
  generation path; any picture/voice/etc. spend triggered is the SAME spend
  that action always cost, just proven to happen exactly once instead of
  potentially twice.
- **Safety net:** fail-closed on DB error (a claims-table outage refuses
  dispatch rather than risking a double-spend) and self-healing on a leaked
  claim (2h stale sweep, matching the existing `STALE_TASK_THRESHOLD_MIN`
  reaper pattern already in `routes/pipeline.py`) — worst case of this
  chunk being wrong in some untested way is an over-cautious "busy" refusal
  or a temporary (≤2h) lock, never an unblocked double-spend.

---

## C16b — coverage skip-if-done + scene allowlist (S7-2 fix) · live re-invoke check
Checklist entry C16b (audit `docs/reports/2026-07-17-storyengine-agent-audit-
findings.md` §S7-2 CRITICAL, sweep C16). `scripts/coverage_to_app.py::
generate_coverage_for_video` now skips a scene whose `coverage_directive_hash`
is unchanged AND whose drawn `assets` row count meets the expected count
(`_expected_coverage_frame_count`) derived from that same directive. Covered
at the unit level (14 tests in `test_c16b_coverage_skip_if_done.py`, confirmed
non-vacuous via `git stash`) with a fully faked DB/run_coverage — no live DB
or paid API call was driven through this in the sandbox, so the following
need a real backend + DB + Kie key:
- [ ] **Re-invoke costs $0.** On a video that already has coverage pictures
      for every scene (unchanged script since), click "Generate all pictures"
      again. Confirm: (a) the task completes near-instantly with a message
      like "Coverage done: 0 frames across 0 scene(s) (N scene(s) already
      done, skipped)", (b) `se db "SELECT count(*) FROM generation_ledger
      WHERE video_id='<test-vid>' AND stage='image' AND created_at > now() -
      interval '2 minutes'"` shows 0 new rows, and (c) no new Kie image-gen
      calls appear in `se logs backend 200` for that window.
- [ ] **Edit the script, re-invoke — it regenerates.** Edit one scene's
      script text (changing `coverage_directive_hash`), click "Generate all
      pictures" again. Confirm ONLY that scene redraws (progress message
      shows "script changed since the storyboard — re-planning…" for that
      scene, nothing for the others) and its `assets` rows get replaced
      (`store_scene`'s delete-then-insert).
- [ ] **Per-scene "regenerate scene N" still forces a redraw.** On a video
      with complete, unchanged pictures, use the existing per-scene button
      (`scene=N`) on one scene. Confirm it redraws (new `updated_at` on that
      scene's assets, a new `generation_ledger` row) even though nothing
      about the script changed — the forced-scene override must not have
      regressed the existing redo verb.
- [ ] **Autobuild resume doesn't re-bill.** Start a chat "build" on a video,
      let it draw pictures for a few scenes, then interrupt (kill the
      backend process or let the task fail) before all scenes finish.
      Re-trigger the same autobuild (or click "Generate all pictures").
      Confirm the already-drawn scenes are skipped (no re-draw, no new
      ledger rows) and only the incomplete/undrawn scenes proceed — this is
      the actual money-saving case C16b exists for.
- **Cost:** the FIRST full run of pictures on a fresh test video is a normal
  paid generation (unavoidable — need real drawn pictures to test skip
  against). Every check ABOVE this is designed to spend $0 (that's exactly
  what's being proven) except the "edit one scene" check, which spends only
  that one scene's normal per-scene cost.
- **Safety net:** the completeness check requires BOTH a matching directive
  hash AND a frame count at least equal to the plan's expected count — an
  undercount (crash, content-policy skip) always re-triggers a real draw,
  never silently strands a half-finished scene. Worst case if this chunk is
  wrong in some untested way: a scene that should have skipped redraws
  anyway (wasted money, same as before this chunk existed), never a scene
  that should have redrawn silently staying blank.

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

## C16c — generation_ledger uniqueness backstop (S7-5 fix) · live race + threading check
Checklist entry C16c (audit `docs/reports/2026-07-17-storyengine-agent-audit-
findings.md` §S7-5 HIGH, sweep C16). Migration 093 added a partial unique
index (`video_id, stage, kie_task_id` WHERE `kie_task_id IS NOT NULL`) and
`record_ledger_entry()` now inserts with `ON CONFLICT ... DO NOTHING` +
loud duplicate-skip logging. Provider task ids are now threaded into 3
single-image-per-row call sites (`redraw_asset_image`, the 2 single-image
thumbnail paths). Covered at the unit level (24 new tests across
`test_generation_ledger.py` + `test_image_model_router.py`, both confirmed
non-vacuous via `git stash`) with a fully faked DB/ImageClient — no live DB
row or concurrent race was actually driven through this in the sandbox, so
the following need a real backend + DB + Kie key:
- [ ] **Real duplicate-scan re-check before trusting the index long-term.**
      The pre-apply scan (this chunk) found 0 rows total in
      `generation_ledger` — re-run periodically as real spend accumulates:
      `se db "SELECT video_id, stage, kie_task_id, COUNT(*) FROM
      generation_ledger WHERE kie_task_id IS NOT NULL GROUP BY video_id,
      stage, kie_task_id HAVING COUNT(*) > 1"` should always return 0 rows
      (the unique index makes a future duplicate impossible to INSERT, but
      confirm nothing slipped in via a path that bypasses `record_ledger_
      entry`, e.g. a manual `se db --write` insert).
- [ ] **Redraw a picture, confirm a real `kie_task_id` lands.** Use the
      per-frame "redraw" action on one asset (`redraw_asset_image`). Confirm
      `se db "SELECT stage, kie_task_id FROM generation_ledger WHERE
      video_id='<test-vid>' AND stage='image' ORDER BY created_at DESC LIMIT
      1"` shows a non-NULL `kie_task_id` (a real Kie taskId string, not a
      placeholder) — proves the `task_id_out` threading actually reaches the
      ledger row in a live call, not just in the FakeImageClient unit tests.
- [ ] **Regenerate a thumbnail (channel-formula or modeled-on-reference
      path), confirm a real `kie_task_id` lands** the same way, `stage =
      'thumbnail'`.
- [ ] **Force a real double-spend race and confirm the backstop fires.**
      Hardest to stage live (needs two concurrent workers finishing the SAME
      Kie task), but if a natural one is ever caught in the wild (e.g. two
      requests overlapping during a flaky retry): confirm `se logs backend`
      shows the `DUPLICATE SKIPPED` line for that video/stage/task_id, and
      `se db "SELECT COUNT(*) FROM generation_ledger WHERE video_id='<vid>'
      AND stage='<stage>' AND kie_task_id='<id>'"` returns exactly 1, not 2.
      Absent a natural occurrence, this is the one check that can't be
      manufactured safely without directly calling `record_ledger_entry`
      twice from a script (which would prove the SQL but not a real app-level
      race) — lower priority than the two threading checks above.
- [ ] **Batch call sites unaffected.** Generate several image variants
      (`run_image_variants`) or run a fresh "Generate all pictures" pass.
      Confirm `generation_ledger` rows for those still land with
      `kie_task_id IS NULL` (by design — see migration 093's header) and
      `videos.total_cost` still sums correctly across mixed NULL/non-NULL
      rows for the same video.
- **Cost:** the redraw/thumbnail-regenerate checks are normal paid actions
  a creator would trigger anyway (~$0.05 each) — no new spend surface, just
  confirming the id lands on the row that already gets written.
- **Safety net:** the index is additive and partial (`WHERE kie_task_id IS
  NOT NULL`) — it can only ever refuse an INSERT that is an EXACT repeat of
  an existing non-NULL key, which is precisely the double-spend case this
  chunk exists to close; it cannot block or alter any row with a NULL
  `kie_task_id` (still the vast majority of stages today) or any two rows
  with genuinely different task ids. Worst case of this chunk being wrong
  in some untested way is a duplicate slipping through uncaught (same as
  before this chunk — no regression), never a legitimate spend being
  refused.

---

## C16d — Queue hardening: S7-3/S7-4/S7-7/S7-8/S7-9 fixes · live re-invoke + degraded-mode check
Checklist entry C16d (audit `docs/reports/2026-07-17-storyengine-agent-audit-
findings.md` §S7, the hardening tier — S7-3 HIGH, S7-4 HIGH, S7-7 MED, S7-8
LOW, S7-9 LOW). Thumbnail now skips regeneration when `thumbnail_url` is
already set unless `force=true`; `_enqueue_or_fallback` derives `attempt`
from real history and raises an honest 409 on a genuine arq dedup-hit instead
of a silent 200; `/api/health` reports `queue: "arq"|"degraded-inprocess"`;
`background_tasks.job_id` has a live partial unique index (migration 094,
confirmed via `pg_indexes`, zero pre-existing duplicates). Covered at the
unit level (17 new tests across 4 files, all confirmed non-vacuous via `git
stash` per source file) with fully faked DB/request objects — none of the
following was driven through a real backend + DB + arq/Redis pool in the
sandbox:
- [ ] **Thumbnail Regenerate spends $0 on a no-op re-click.** On a video that
      already has a thumbnail, tap the Thumbnail tab's action button when its
      label reads "Regenerate" is NOT what to test first — that path already
      passes `force=true` by design. Instead: trigger `POST
      /api/pipeline/thumbnail/{id}` directly with NO `force` param (e.g. via
      `se db` isn't right here — use `curl` against the live backend or the
      `runPipelineStage(id, "thumbnail")` call with no params) on a video that
      already has `thumbnail_url` set. Confirm the response/task-status shows
      `"skipped": true` / a "already exists" message, and `se db "SELECT
      COUNT(*) FROM generation_ledger WHERE video_id='<id>' AND
      stage='thumbnail'"` does NOT grow.
- [ ] **Thumbnail Regenerate with `force=true` still works end to end.** Tap
      the real Regenerate button in the UI (thumbnail already exists) —
      confirm a NEW image actually generates (thumbnail_url changes) and one
      new `generation_ledger` row lands.
- [ ] **`/api/health` reflects the real queue state.** `se db` won't show
      this — hit the endpoint directly (`curl <backend>/api/health` or via
      `se health` if it proxies there). Confirm `queue` reads `"arq"` if
      `storyengine-worker`/Redis are actually up on the VPS, or
      `"degraded-inprocess"` if not — cross-check against `journalctl -u
      storyengine-worker` / `se logs backend` for the "Redis/arq pool not
      available" startup line to make sure the field agrees with reality.
- [ ] **A genuine concurrent double-enqueue surfaces the 409, not a silent
      success.** Hardest to stage live (needs arq/Redis actually connected
      AND two requests racing the same not-yet-persisted attempt number).
      If Redis isn't running on the VPS today (check first via the health
      field above), this whole path is dormant — skip until arq is actually
      wired into a live deploy, and note that in this checklist rather than
      forcing it.
- [ ] **Legitimate retries no longer silently no-op for 24h.** With arq
      connected, run the SAME stage twice in a row (e.g. two research runs on
      one video). Confirm the SECOND enqueue actually queues (not swallowed)
      by checking `se db "SELECT attempt, job_id FROM background_tasks WHERE
      video_id='<id>' ORDER BY created_at"` shows attempt=1 then attempt=2
      with two DIFFERENT job_ids, not the same job_id refused twice.
- **Cost:** the thumbnail force-regenerate check is a normal paid action a
  creator would trigger anyway (~$0.05) — no new spend surface. The
  skip-if-done check should cost exactly $0 — that's the point.
- **Safety net:** the thumbnail guard only ever skips work that would have
  produced a byte-identical result (same prompt, same seed inputs) when
  `thumbnail_url` is already set and no caller asked for a redo; every real
  redo path threads `force=true` explicitly (traced and unit-tested). The
  409 fix only ever fires on an EXACT duplicate `(stage, video_id, attempt)`
  key — a state that was already a bug (a job silently not running) before
  this chunk, never a legitimate two-different-jobs collision.

## C17 — `draft_pass` + `finalize` verbs (checklist §1.3) · live full-cycle check
Checklist entry §1.3 `[B]`. `draft_pass` routes every scene's clip to the
cheapest wired draft-tier model (today: Grok Imagine) in one pass without
touching `assets.routed_model`/`model_override`; `finalize` regenerates ONLY
`assets.status='approved'` scenes at their real routed/override tier.
Pass-identity dedup via new `generation_passes` table (migration 095, applied
live, confirmed via `information_schema.columns`); concurrency via the
existing `generation_claims` "main" lane. Covered at the unit level (13 new
tests in `test_c17_draft_pass_and_finalize.py`, confirmed non-vacuous via
`git stash`) with fully faked DB/Kie/PipelineExecutor objects — none of the
following was driven through a real backend + DB + paid Kie call in the
sandbox:

- [ ] **Draft pass produces real cheap clips for every scene.** On a test
      video that already has pictures (any number of scenes, e.g. 6-8), say
      "draft the whole video" in the co-pilot dock (or trigger the `draft_pass`
      verb directly once C18 wires a button). Confirm the cost quote shown
      matches `~(pics_with_no_clip_yet × grok_price)`, confirm on it, and once
      it completes: `se db "SELECT scene, model_used, routed_model,
      model_override FROM assets WHERE video_id='<id>' ORDER BY scene"` —
      every row's `video_clip_url` is set, every `model_used` = the draft
      model (`grok-imagine`), and CRITICALLY `routed_model`/`model_override`
      are UNCHANGED from before the draft pass (compare against a pre-draft
      snapshot) — this is the money invariant the whole design rests on.
- [ ] **Approve 3 scenes, then finalize regenerates exactly those 3.**
      Snapshot each scene's `video_clip_url` right after the draft pass
      (`se db "SELECT scene, video_clip_url FROM assets WHERE
      video_id='<id>'"`). Approve 3 scenes (`approve_scene` verb / tap
      Approve on those scene cards once C18 ships the tick). Say "finalize"
      (or trigger the `finalize` verb directly). Confirm the cost quote only
      itemizes those 3 scenes at their routed/override price (not all
      scenes' draft price). After it completes: re-run the same `se db`
      query — ONLY the 3 approved scenes' `video_clip_url` values changed
      (new clip) and their `model_used` now equals their real routed/override
      model (not the draft model); every OTHER scene's `video_clip_url` is
      BYTE-IDENTICAL to the draft-pass snapshot.
- [ ] **A second identical finalize is refused, not re-billed.** Immediately
      say "finalize" again with NOTHING newly approved since. Confirm the
      copilot's reply is the "already finalized" line (no new confirm-card
      quote, no dispatch) and `se db "SELECT COUNT(*) FROM generation_ledger
      WHERE video_id='<id>' AND stage='clip'"` does NOT grow from this second
      call. Then approve one MORE scene and say "finalize" a third time —
      confirm THIS one goes through (a new `scene_set_hash`, so it's not
      wrongly deduped) and only that new scene's clip regenerates.
- [ ] **`generation_passes` rows match reality.** `se db "SELECT pass,
      scene_set_hash, completed_at FROM generation_passes WHERE
      video_id='<id>' ORDER BY completed_at"` — expect one `draft_pass` row
      and TWO `finalize` rows (the second-approval pass from the check above)
      with DIFFERENT `scene_set_hash` values, each with a `completed_at`
      timestamp, and NO row for the refused duplicate finalize attempt (rows
      are written only on success).
- [ ] **Ledger shows both passes.** `se db "SELECT stage, model,
      unit_cost, actual_cost, kie_task_id FROM generation_ledger WHERE
      video_id='<id>' AND stage='clip' ORDER BY created_at"` — one row per
      clip generated across BOTH the draft pass and the finalize pass(es),
      each with its own `kie_task_id` (C16c's uniqueness backstop still
      applies — no duplicate `(video_id, stage, kie_task_id)` rows even
      though this is now two separate generation PASSES touching the same
      video/stage).
- [ ] **Concurrent double-tap of "finalize" is refused, not double-billed.**
      Fire two "finalize" requests back-to-back (fast enough to race the
      `generation_claims` "main" claim) — confirm the SECOND gets the
      "already working on that" busy reply immediately (not a queued second
      run), and only ONE finalize's worth of clips/ledger rows land.
- **Cost:** draft_pass (~6-8 clips × $0.09-0.225 Grok tier ≈ $0.60-1.80) +
  finalize on 3-4 scenes at a mix of tiers (≈ $1-5 depending on routed
  models) — get an explicit cost-quote confirm from Ryan before running
  either on a real video, per storyengine/CLAUDE.md's money rule. Use the
  smallest test video available (fewest scenes) to minimize spend.
- **Safety net:** `run_clip_generation`'s two new params
  (`force_model_id`/`only_scenes`) are additive and default to unused for
  every EXISTING caller (`animate`, the per-scene redo button) — this live
  check only needs to exercise the two NEW call paths (draft_pass/finalize
  themselves), not re-verify existing animate behavior. `generation_passes`
  is a brand-new table with zero interaction with any other table's rows
  besides its two `tenants`/`videos` foreign keys.

---

## C18 — GuidedNextStep draft/finalize labels + scene Approve ticks + savings
line (checklist §1.3 [U]) · live click-through check

Checklist §1.3 `[U]`. C17's `draft_pass`/`finalize` verbs were chat-only;
this chunk added the CLICKABLE door — GuidedNextStep's one-big-button now
offers "Draft the whole video (~$X)" then "Finalize N approved scenes
(~$Y)", ScenesWorkspaceTab's scene header gained an Approve tick, and a
savings line renders under both buttons. Covered at the unit level (20
tests across `test_c18_guided_actions_ui.py` + `test_c17_draft_pass_and_
finalize.py`'s 2 new assertions, non-vacuous via `git stash`) with faked
DB/runner boundaries — none of the following was driven through a real
browser + backend + DB + paid Kie call in the sandbox. This is the SAME
live scenario as §C17 above, now walked through the actual UI instead of
raw verb calls — run this INSTEAD of (not in addition to) manually
triggering the verbs, once both chunks are deployed together.

- [ ] **Draft button appears and quotes correctly.** On a test video with
      pictures but no clips yet, open the video page — GuidedNextStep's big
      button should read "Draft the whole video (~$X)" where X matches
      `GET /api/pipeline/actions/{id}`'s `draft_pass` action's `cost_text`
      exactly (cross-check via `se db` or the network tab). Tap once — the
      button becomes "Confirm — $X" with a "Cancel" link beside it; tap
      Cancel and confirm it reverts to the original label with no request
      fired. Tap the label again then Confirm — the RUNNING banner (spinner
      + Stop button) should take over immediately.
- [ ] **Scene Approve ticks flip and persist.** On the Scenes tab, each
      scene with pictures should show an outline "Approve" pill next to its
      "Scene N" badge; tap it — it flips to a green "Approved ✓" badge
      within one request (no page reload needed), and stays approved after
      a hard refresh. Approving a scene should NOT touch any other scene's
      badge.
- [ ] **Finalize button appears once ≥1 scene is approved, quotes N
      correctly, and only regenerates ticked scenes.** After the draft pass
      completes and you approve exactly 3 scenes via the tick above,
      GuidedNextStep's button should read "Finalize 3 approved scenes
      (~$Y)" — confirm the "3" matches the number of scenes actually ticked
      (not a stale count from before a tick). Fire it; confirm only those 3
      scenes' clips regenerate (cross-check against §C17's DB queries).
- [ ] **Savings line reads correctly and matches the ledger.** Under the
      Finalize button, confirm the line "Draft $X now + finalize 3 scenes
      $Y later ≈ $Z total vs $W all-premium" appears, `Z` really is `X + Y`
      to the cent, and `W` is at least `Z` (never less — all-premium is
      supposed to be the expensive baseline). Cross-check `X`+`Y` loosely
      against `se db "SELECT SUM(actual_cost) FROM generation_ledger WHERE
      video_id='<id>' AND stage='clip'"` (ledger is real spend, the savings
      line is a quote — they should be in the same ballpark, not identical).
- [ ] **Skip escape hatch works both ways.** From the Draft offer, tap "I'll
      animate scenes one at a time instead" — confirm it navigates to the
      Scenes tab without spending anything. From the Finalize offer, tap
      "Skip — go straight to the thumbnail" — confirm it runs the thumbnail
      stage directly (same as the pre-C18 button would have) and does NOT
      touch any approved scene's clip.
- [ ] **Fail-safe with no wired draft tier (if testable).** On a channel/
      video where no `tier="draft"` model is wired, confirm GuidedNextStep
      falls back to the ORIGINAL pre-C18 ladder ("Animate scene 1" / "Animate
      the rest") byte-identical to before this chunk — no broken button, no
      `undefined`/`NaN` in any label.
- **Cost:** same order of magnitude as §C17 above (draft ~$0.60-1.80 on a
  6-8 scene test video, finalize on 3 scenes ~$1-5 depending on routed
  tiers) — get an explicit cost-quote confirm from Ryan before running on a
  real video, per storyengine/CLAUDE.md's money rule.
- **Safety net:** every new frontend read is optional-chained with a `??`
  fallback (`draftInfo?.breakdown?.total ?? draftInfo?.cost ?? 0`), so a
  stale/old-backend response (missing `breakdown`) makes both offers and
  the savings line resolve to "nothing to show" rather than crash — if the
  draft/finalize buttons don't appear at all, check the deployed backend
  actually carries C18 (`GET .../actions/{id}` response should include a
  `breakdown` key per action) before assuming the UI is broken.

---

## C20 — `style_presets` catalog + `GET /api/style-presets` + executor mapping
(checklist §2.1 [D]+[B]) · live pick-a-preset-and-generate check

Checklist §2.1's own `[V]` line: "Pick `holographic_hud` in UI → generated
prompts carry its style system." This chunk shipped the DATA + BACKEND
layers only (no `[U]` — C21 builds the gallery picker), so this full
end-to-end check needs C21 deployed too. Covered at the unit level in the
sandbox (10 tests in `test_c20_style_presets.py`, non-vacuous via `git
stash`; `information_schema` + live row-count/content confirmed via
Supabase MCP) — none of the following was driven through a real pipeline
run, since there's no UI yet to pick a preset from and no paid budget in
the sandbox.

- [ ] **`GET /api/style-presets` returns the live catalog.** `se db "SELECT
      id, display_name, cost_tier, sort, active FROM style_presets ORDER BY
      sort"` should list exactly the 5 rows (neutral_v1, holographic_hud,
      cinematic_dossier, clay_mannequin, cinematic_illustration); curl the
      route (with a valid tenant token) and confirm it matches the DB
      exactly, in the same order.
- [ ] **`create_video` with a valid `style_preset_id` stores it.** `curl -X
      POST .../api/videos` with `{"title": "test", "style_preset_id":
      "holographic_hud"}` → `se db "SELECT style_preset_id FROM videos
      WHERE id='<new-id>'"` should read back `holographic_hud`.
- [ ] **An invalid `style_preset_id` 400s, not silently drops.** Same POST
      with `"style_preset_id": "not_a_real_preset"` → expect HTTP 400, no
      video row inserted with a bogus id (confirm no orphan row was created
      at all — the whole request should fail before the INSERT, not create
      a video with `style_preset_id=NULL`).
- [ ] **The executor actually sets `VISUAL_PROFILE` from the stored id.**
      On a video created with `style_preset_id="holographic_hud"`, trigger
      any stage that calls `_load_idea` (e.g. re-run image prompts) and
      check the backend log/process env at that moment — `VISUAL_PROFILE`
      should read `holographic_hud`, not `neutral_v1`. The cheapest way to
      observe this without a paid image call: temporarily log
      `os.environ.get("VISUAL_PROFILE")` right after `_load_idea` runs (or
      add a one-off `print` and grep `se logs backend`), rather than
      running the full costed image stage.
- [ ] **The full checklist ask — generated prompts actually carry the
      profile's style system.** C21a shipped the New Video door's picker
      (the "Look engine" gallery, `app/pipeline/page.tsx`) — this check can
      now run through THAT door: create a video, pick `holographic_hud` in
      the gallery, run image prompts for one scene, and inspect the
      resulting prompt text — it should read as a holographic/HUD/data-
      visualization scene (per that profile's own `preview_prompts` in
      `shared/profiles/visual/holographic_hud.py`), not the neutral/
      photorealistic default. The CHAT door is now ALSO wired (C21b —
      `_spec_to_create_request` passes `style_preset_id` straight from the
      new "look_engine" card pick) — re-run this same check from a
      chat-built video too; see §C21b below for that door's own checklist.
      This is the check that closes checklist §2.1's `[V]` line for good,
      across BOTH doors.
- **Cost:** the image-prompt check is free (text generation only, no image
  render needed to confirm the STYLE the prompt carries); only run the
  full "generate real images and eyeball them" version if you also want to
  visually confirm the look, which is paid (~$0.025-0.05/image per
  storyengine/CLAUDE.md's cost table) — get an explicit yes from Ryan
  first if so.
- **Safety net:** `_resolve_visual_profile_id`'s fail-soft chain means a
  video with NO `style_preset_id` (every video created before this chunk,
  or via any path that doesn't set it) behaves byte-identically to before
  — if something looks wrong, first confirm the test video's
  `style_preset_id` column is actually non-NULL before suspecting the
  executor mapping itself.

---

## C21a — card-kind lookup refactor + New Video "Look Engine" gallery
(checklist §2.1 [U] part 1) · live click-through check

Frontend-only chunk (no backend changes; `GET /api/style-presets` and
`create_video`'s `style_preset_id` validation are C20, already live). No
frontend test harness exists in this repo, so none of the following was
driven through a browser this session — `tsc --noEmit` + `npm run build`
were the only proof (both clean, see SYSTEM_STATE.md §C21a).

- [ ] **New Video modal renders the Look Engine gallery.** Open "New Video"
      → the "Look engine" section (above the renamed "Style description"
      section) should show 5 cards: Neutral Documentary, Holographic
      Intelligence Display, Cinematic Intelligence Briefing, Clay Mannequin
      Dioramas, Cinematic Animated Illustration — each with a placeholder
      icon (no `preview_url` seeded yet, so a broken-image icon here would
      mean the S9-4 onError fix regressed), a display name, and up to 2
      "Best for" tags.
- [ ] **Picking a card round-trips `style_preset_id`.** Click "Holographic
      Intelligence Display", fill in a title, submit → `se db "SELECT
      style_preset_id FROM videos WHERE id='<new-id>'"` should read
      `holographic_hud`. Click the SAME card again to deselect (toggle
      behavior) → the gallery should show no card selected before submit.
- [ ] **Both axes travel independently.** Pick a Look Engine card AND type a
      custom "Style description" (or pick one of the 6-item preset grid) in
      the SAME create → confirm the created video's row has BOTH
      `style_preset_id` (engine) AND `image_style_override`/
      `visual_style_label` (description) populated, neither one clobbering
      the other.
- [ ] **Fail-soft on a slow/broken `GET /api/style-presets`.** Throttle or
      break the endpoint (or just watch the loading state on a cold cache)
      → the gallery should show the spinner then either the grid, the error
      message with a working Retry button, or (on a genuinely empty table)
      the "your channel's default will be used" text — never a crash, never
      a blank gap in the form, and the rest of the New Video form must stay
      usable regardless (submit should still work with `style_preset_id`
      simply omitted).
- [ ] **Chat's existing LOOK card option images no longer show a broken-image
      icon if a `/style-icons/<id>.png` file is ever missing** (S9-4 fix on
      the pre-existing 6-item picker, both in `ChatCore.tsx` and the New
      Video "Style description" grid) — temporarily rename/move one PNG in
      `public/style-icons/` and confirm both pickers swap to the text label
      instead of a broken-image glyph.
- **Cost:** free — every check above is a read + a video-creation POST (no
  paid stage runs; don't advance the created test video past `idea_logged`
  unless intentionally testing the executor mapping per §C20 above).
- **Safety net:** `style_preset_id` is optional everywhere in this chunk —
  if the gallery fails to load entirely, the New Video form must still
  submit successfully with the field simply absent (identical to every
  video created before C20/C21a existed).

---

## C21b — delete duplicated preset lists + producer/chat backend sourcing +
chat gallery card (checklist §2.1 [U] part 2) · live click-through check

Closes the CHAT-door half of C20's `[V]` line ("generated prompts carry the
profile's style system") that C21a left open, plus deletes both hardcoded
copies of the six-entry style-DESCRIPTION vocabulary (backend `producer_
prompt.VISUAL_PRESETS`, frontend `lib/visual-presets.ts`) in favor of one
live source (`channel_format.STYLE_DESCRIPTIONS`, served over the new `GET
/api/style-descriptions`). Verified so far by 22 new sandbox tests (non-
vacuous via `git stash` — the whole module fails to even import against the
pre-C21b source), `tsc --noEmit` + `npm run build` (both clean), and
grep-proofs (zero real `VISUAL_PRESETS` readers, zero `visual-presets.ts`
imports). None of the following was driven through a live chat conversation
this session (no paid Anthropic/Kie key in the sandbox) — do these on the
next dev-server pass with a real key.

- [ ] **Chat's "style" LOOK card still offers the same 6 looks, now
      server-sourced.** Start a fresh home-chat conversation, describe a
      video with no style mentioned — the "style" card's 6 options (Pixar
      3D / 2D flat / Realistic / Anime / Watercolor / Comic) and their
      preview images should render identically to before this chunk. Break
      `GET /api/style-descriptions` (stop the backend briefly or 404 it) and
      confirm the picker falls back to `STYLE_DESCRIPTIONS_FALLBACK`
      (`use-style-descriptions.ts`) instead of rendering empty.
- [ ] **The NEW "look_engine" card appears only when asked, and is genuinely
      optional.** In a normal "make me a video about X" conversation, the
      Look Engine card should almost never appear (per the system prompt's
      "most turns, don't mention this at all" guidance) — confirm a handful
      of ordinary conversations reach `phase: "plan"` without ever seeing
      it. Then explicitly ask "what rendering engines / visual styles do you
      support beyond the six looks?" — the producer should offer a
      `"look_engine"` card whose options match the LIVE `style_presets` table
      (`se db "SELECT id, display_name FROM style_presets WHERE active"`),
      not a stale/hardcoded list.
- [ ] **Picking a `look_engine` option round-trips `style_preset_id` through
      chat.** Pick "Holographic Intelligence Display" on that card, finish
      the plan, tap "Make it" → `se db "SELECT style_preset_id FROM videos
      WHERE id='<new-id>'"` should read `holographic_hud`.
- [ ] **Both axes travel independently through chat, same as the New Video
      door.** In one conversation, pick BOTH a "style" look (e.g. Anime) AND
      a "look_engine" pick (e.g. Clay Mannequin Dioramas) → confirm the
      created video's row has BOTH `visual_style='anime'`/
      `image_style_override` (description) AND `style_preset_id=
      'clay_mannequin'` (engine) populated, neither clobbering the other.
      This closes C20's original `[V]` ask for good, across both doors.
- [ ] **The reference-video vision classifier still recommends a "style"
      option, unaffected by the axis split.** Model a reference video
      ("make one like this: <url>") and confirm the "style" card still
      shows a "✨ Recommended" badge on the option matching the reference's
      detected look (unchanged behavior — this is the
      `_detect_reference_style_preset`/`_annotate_style_recommendation`
      path, now reading `channel_format.STYLE_DESCRIPTIONS` instead of the
      deleted `producer_prompt.VISUAL_PRESETS`, but the same 6-id
      vocabulary). It must NEVER badge the new `look_engine` card (no
      vision-classify-into-5-engines exists — confirm no "Recommended" badge
      ever appears there).
- [ ] **A DB error on the `style_presets` table never crashes a chat turn.**
      Temporarily break the `style_presets` table/connection (or just watch
      behavior if it's ever briefly unavailable) and confirm the producer
      still responds normally — worst case the `look_engine` card is simply
      never offered (or offers only the frozen `neutral_v1` fallback), never
      a broken/empty assistant turn.
- **Cost:** the card-rendering / picking checks are free (no paid stage runs
  until "Make it" — same cost profile as any other chat plan). The vision
  classifier check burns one cheap vision call (Kie Gemini 2.5 Flash tier,
  ~$0.0005/call per docs/cost-awareness.md) — trivial, no explicit sign-off
  needed.
- **Safety net:** every new field (`style_preset_id` from chat,
  `look_engine` card) is additive and optional — a conversation that never
  touches this axis behaves byte-identically to pre-C21b chat (confirmed by
  the sandbox's `_spec_to_create_request` unit tests: no `style_preset_id`
  in spec -> `req.style_preset_id is None`, unchanged create-video path).

---

## C22 — conversational style creation: "make me a new style…" (checklist §2.1 [U] / P2.1c) · live chat check

New home-producer `profile_ops` (`draft_style`, `use_style`) plus a
deterministic confirm gate (`chat_turn` step 3.6 →
`_handle_style_draft_confirm`) that saves through the SAME
`routes.visual_styles.create_visual_style` the profile page's CRUD calls —
full detail in SYSTEM_STATE.md §C22. Verified so far by 23 new sandbox
tests (non-vacuous via `git stash`), `tsc --noEmit` + `npm run build`
(both clean), and a full backend-suite byte-identical failure-list diff
against the stashed baseline. No paid Anthropic/Kie key in the build
sandbox, so the producer LLM was never actually driven this session — do
these on the next dev-server pass with a real key.

- [ ] **"Make me a new style" drafts, never saves, on turn 1.** In a fresh
      home-chat conversation say something like "make me a new style —
      dreamy Ghibli summer, soft light, no text overlays." Confirm: (a) the
      reply describes a drafted name + one-sentence look, (b) a
      `style_draft` preview card appears with "Save this style" / "Not
      quite" buttons, (c) `se db "SELECT * FROM visual_styles WHERE
      project_id='<test-project>' ORDER BY created_at DESC LIMIT 1"` shows
      NO new row yet.
- [ ] **Tapping "Save this style" creates exactly one row, tapping "Not
      quite" creates none.** After the draft card above, tap Save — confirm
      a NEW `visual_styles` row now exists with the drafted name and
      `style_profile->>'prompt_prefix'` matching the drafted look, and the
      assistant's reply names it and says where to find/use it. Start a
      fresh draft (a different look) and tap "Not quite" instead — confirm
      no new row appears and the reply invites another description.
- [ ] **The new style shows up on the Profile page without a manual
      refresh.** Immediately after tapping Save (same session, Profile page
      NOT already open in another tab within the last 30s), navigate to
      Profile → Visual Styles — the new style should already be listed. If
      the Profile page WAS already mounted/cached, confirm the
      `["visualStyles"]` query invalidation from `ChatCore.tsx` refreshes it
      without requiring a manual page reload.
- [ ] **"Use my <name> style" activates it — channel-wide.** In a later
      conversation, say "always use my <drafted name> style" (or "make it my
      default look") — confirm the reply confirms the switch, and `se db
      "SELECT name, is_active FROM visual_styles WHERE project_id=
      '<test-project>'"` shows ONLY that row `is_active = true`, every other
      row `false`. Then build a plain video with no style mentioned and
      confirm its generated image prompts front-load that style's look
      sentence (via `identity.build_identity_context`'s
      `channel_visual_style` fallback).
- [ ] **"Use my <name> style for this one" resolves the CURRENT plan without
      switching the default.** Ask for a new video and, while planning it,
      say "use my <name> style for this one" without asking to make it the
      default — confirm the created video's `image_style_override` matches
      that saved style's look, but a DIFFERENT concurrent/later video (with
      no style mentioned) still uses whatever was already the channel's
      active default, not this one-off pick.
- [ ] **A garbled or empty draft never half-creates anything.** Ask for a
      style with genuinely no description ("make me a new style" and
      nothing else) — confirm the producer asks a clarifying question
      instead of drafting a blank card, and no `style_draft` card /
      `visual_styles` row appears.
- **Cost:** free — every check above is a chat-only, no-paid-generation
  flow (text drafting + a DB row write, same cost profile as any other
  profile_op like `remember`/`set_niche`).
- **Safety net:** if a draft card ever seems to "save itself," confirm
  `state["pending_style_draft"]` is actually being popped/cleared on both
  the yes and no paths (`_handle_style_draft_confirm`) — a leftover pending
  draft from an abandoned conversation could otherwise resurface if the
  creator later says an unrelated "yes" to something else while a stale
  card kind check misfires; this was reasoned through in the sandbox
  (`_maybe_attach_style_draft_card` only re-attaches when THIS turn's ops
  include `draft_style`) but never watched live across a long multi-topic
  conversation.

---

## C24 — `videos.script_profile` + `GET /api/script-profiles` (checklist §2.3) · live generate-under-both-profiles check

New `videos.script_profile` column (migration 098), `GET /api/script-profiles`, the New Video
"Advanced" script-voice select + `ScriptVoiceTab`'s `ScriptVoiceCard`, and the copilot's
`script_profile` verb ("write it in the investigative style") — full detail in SYSTEM_STATE.md
§C24. Verified so far by 19 new sandbox tests (non-vacuous — each layer's resolver/runner/route
was exercised directly, e.g. `_resolve_script_profile_id({})` really does return `"neutral_v1"`),
`tsc --noEmit` + `npm run build` (both clean), and a full backend-suite byte-identical
failure-list diff against the pre-change baseline. What was NOT driven: an actual Claude script-
generation call under each profile, since that costs real Anthropic API spend and this sandbox has
no paid key wired for a live run. This is checklist §2.3's own `[V]`: "Generate same topic under
both profiles; scripts differ per profile laws" — do this on the next dev-server pass with a real
key, and only tick §2.3 in the checklist once it passes.

- [ ] **Neutral (no pick) really is unchanged.** Create a video with NO script-voice pick (leave
      Advanced collapsed, or explicitly select "Neutral (default)"). Run the script stage
      (`se db "SELECT script_profile FROM videos WHERE id='<video-id>'"` should show `NULL`).
      Confirm the generated script reads the same as any pre-C24 video's script would — no
      Power-Doctrine-flavored language ("follow the money", incentive-chain framing) should appear
      unless the channel's own system-prompt override already adds it.
- [ ] **Picking "Investigative Reveal" changes the script's voice/structure.** Create (or edit
      an existing video pre-script) with `script_profile = power_doctrine_v2` — via the New Video
      Advanced select, OR `se db --write "UPDATE videos SET script_profile='power_doctrine_v2'
      WHERE id='<video-id>'"`, OR say "write it in the investigative style" to the copilot on a
      video that hasn't been scripted yet. Run/re-run the script stage on the SAME topic/brief a
      neutral run just used. Confirm: (a) `se logs backend 200` around script generation shows the
      line `Script profile loaded: power_doctrine_v2` (`script/brief_translator/__init__.py`'s
      `logger.info` at profile-load time), (b) the resulting script actually reads differently
      from the neutral run — follow-the-money incentive-chain framing, the analyst voice
      `power_doctrine_v2.py`'s `voice.identity`/`voice.tone` describe — not just a different
      random seed's worth of paraphrasing.
- [ ] **"Framework Explainer" (`power_doctrine_v1`) also changes the voice, differently from v2.**
      Same recipe with `script_profile = power_doctrine_v1` (or say "use the framework explainer
      voice") — confirm the script reads as documentary-teaching/explicit-framework, distinguishable
      from BOTH the neutral run and the `power_doctrine_v2` run (not just "some other script").
- [ ] **The New Video Advanced select's description text matches the API.** Open the New Video
      modal → Advanced → confirm the select shows exactly 3 options ("Neutral (default)",
      "Power Doctrine — Investigative Reveal", "Power Doctrine — Framework Explainer") and the
      one-line description under it updates when you change the pick — cross-check against
      `curl <api>/api/script-profiles` directly (should be verbatim, not paraphrased by the UI).
- [ ] **`ScriptVoiceTab`'s `ScriptVoiceCard` writes the SAME column, live.** On an existing video's
      Script tab, change the "Script voice" select — confirm (a) the description line below updates
      immediately, (b) `se db "SELECT script_profile FROM videos WHERE id='<video-id>'"` reflects
      the new pick, (c) it round-trips correctly (reload the tab — the select shows the saved pick,
      not reverted to Neutral).
- [ ] **The copilot's clear words never resolve to Power Doctrine.** Say "put the script voice back
      to neutral" (or "auto"/"clear"/"default") on a video that currently has `power_doctrine_v2`
      set — confirm `script_profile` goes back to `NULL`, never silently re-landing on a Power
      Doctrine id (this is unit-tested in the sandbox but worth a live sanity check given the
      "never resurrect Power Doctrine as a default" rule's history).
- **Cost:** each "generate under a profile" check is a real Claude script-generation call (per
  `docs/cost-awareness.md`, roughly $0.01-0.05 for a Sonnet script-writing call — cheap relative to
  the image/clip checks elsewhere in this file, but still real spend). Get Ryan's go-ahead first
  per storyengine/CLAUDE.md's money rule; three script generations (neutral, v2, v1) on the SAME
  short topic keeps the total well under $1.
- **Safety net:** if `GET /api/script-profiles` ever 404s (stale deploy skew), the New Video
  select degrades to just "Neutral (default)" and `ScriptVoiceCard` shows an empty select with no
  description — a degraded-but-safe state (never a crash), so check the endpoint directly first if
  the select looks empty.

---

## C23 — camera-preset chips: `/api/camera-presets` + scene chip + sheet (checklist §2.2) · live pick-and-animate check

New `GET /api/camera-presets` (curated 12-move subset), `PATCH
/api/assets/{id}/camera-preset` (`assets.camera_preset_id`, migration 097),
a Scenes-tab per-shot camera chip + preset sheet, and the copilot's
`camera_preset` verb ("use a crash zoom on scene 12") — full detail in
SYSTEM_STATE.md §C23. Verified so far by 20 new sandbox tests (non-vacuous
via `git stash`), `tsc --noEmit` + `npm run build` (both clean), and a full
backend-suite byte-identical failure-list diff against the stashed
baseline. `_apply_camera_preset_override` (the actual composition
function) is proven byte-identical on NULL and to literally equal the
preset's `motion_prompt` when set — but ONLY as a pure-function unit test;
no live DB, no paid Kie/Anthropic key in the build sandbox, so the real
"pick a preset in the UI → the next real clip actually carries it" loop
was never driven end-to-end. Do this on the next dev-server pass with a
real key + DB.

- [ ] **The chip shows Auto by default, and the sheet lists the curated
      12.** Open a video with existing pictures (post-coverage) in the
      Scenes tab — every shot card should show a small camera-icon chip
      (`Auto` or a humanized auto-pick name like "Dolly In", not blank/
      broken) next to the model badge. Tap it — the sheet should open
      grouped by purpose (Reveal/Scale/Establish/Isolation/Payoff, plus an
      "Other" group holding Static) with 12 real move names + no console
      error.
- [ ] **Picking "Crash Zoom In" writes the column and updates the chip.**
      Tap a preset in the sheet — confirm (a) the chip immediately shows
      "Crash Zoom In · manual" (the purple dot) without a page reload, (b)
      `se db "SELECT camera_preset_id FROM assets WHERE id='<asset-id>'"`
      returns `crash_zoom_in`.
- [ ] **Re-animating that shot carries the preset's motion_prompt.** Tap
      "Redo this clip" (or the card itself) on the shot from the check
      above — confirm the cost quote/confirm behaves normally, then after
      the clip lands, check `se logs backend 200` around the generation (or
      `assets.video_prompt` immediately before the call, if logged) for the
      literal text "Crash zoom: the lens snaps rapidly in toward the main
      target with sudden aggressive speed" (the catalog's own
      `motion_prompt` for `crash_zoom_in`) — NOT a paraphrase.
- [ ] **"Use Auto" clears the override and the chip reverts.** From the
      sheet, tap "Use Auto (earn the move)" — confirm `camera_preset_id`
      goes back to `NULL` in the DB and the chip shows the auto/"earned"
      value again (or "Auto" if `camera_movement` is also unset).
- [ ] **The conversational door writes the SAME column.** In the docked
      copilot (viewing that video), say "use a crash zoom on scene N" for
      some scene N with existing shots — confirm the reply names the scene
      + move + shot count, `se db "SELECT camera_preset_id FROM assets
      WHERE video_id='<video-id>' AND scene=N"` shows `crash_zoom_in` on
      EVERY shot in that scene (not just one), and the Scenes tab's chips
      for that scene now show the manual pick without a manual refresh
      (reload the tab if the query hasn't invalidated — this is the one
      piece not wired to auto-invalidate across the chat/tab boundary,
      confirm whether that's actually true live).
- [ ] **A garbled camera phrase writes nothing.** Say "make the camera do
      something weird and cool on scene N" (no recognizable move name) —
      confirm the reply asks for a clearer instruction (crash zoom, push
      in, etc.) and `camera_preset_id` is untouched on every row in that
      scene.
- [ ] **Known gap — dialogue shots don't honor the override yet.** Pick a
      camera preset on a SPEAKING shot (one with a matched dialogue line /
      InfiniteTalk or Grok-speaking path) and re-animate it — per
      SYSTEM_STATE.md §C23 this is a disclosed gap, expected to have NO
      effect on that shot's actual motion. Confirm this is really true live
      (the clip's motion doesn't change) rather than silently working by
      accident — if it DOES work, the gap note in SYSTEM_STATE.md §C23 is
      stale and should be corrected.
- **Cost:** the pick/clear/copilot checks are free (metadata only). The
  "re-animate carries the motion_prompt" check is ONE paid clip
  (~$0.09-$1.25 depending on the video's model) — get a quote and Ryan's
  go-ahead first per storyengine/CLAUDE.md's money rule, same as every
  other live-verification clip check in this file.
- **Safety net:** if the chip ever shows a raw catalog id instead of a
  name (e.g. "crash_zoom_in" instead of "Crash Zoom In"), the
  `["camera-presets"]` query probably failed to load — `describeCameraMove`
  falls back to `humanizeCameraId()` in that case (title-cased words, still
  readable, not a crash), so this is a degraded-but-safe state, not a bug
  to panic over; check `GET /api/camera-presets` directly first.

---

## C19a — task-watcher consolidation + GuidedNextStep price source
(§S9-1/S9-2/S9-8, gate before C21) · live click-through check

Frontend-only refactor, verified so far by `tsc --noEmit` + `npm run build`
(compile+typecheck clean) and grep-proofs (exactly one `useTaskWatcher(`
mount, `useSharedTaskWatcher(` in all 9 live consumers). No frontend
unit-test harness exists in this repo, so none of the following was driven
through a real running build this session — do this on the next dev-server
pass before/alongside a `--with-frontend` deploy.

- [ ] **One build running → banner + tab both reflect progress.** Kick off
      any pipeline stage from a tab (e.g. Sound tab → "Generate All SFX").
      Confirm: (a) GuidedNextStep's banner (visible once you switch to a
      non-Scenes tab) shows "running" state within ~3s, not stale; (b) the
      Sound tab's own button shows its "Generating…" state; (c) open the
      Network tab — only ONE request to `/api/pipeline/task-status` (or
      equivalent) fires every ~3s, not two/three concurrent identical ones.
- [ ] **Completion refreshes assets exactly once, not 2-3x.** Same run — on
      completion, confirm `video-assets`/`video-script`/`video` queries
      refetch/invalidate a bounded number of times (watch Network tab or
      React Query devtools), not visibly duplicated bursts from multiple
      watchers reacting to the same transition.
- [ ] **Tab-switch mid-run doesn't lose the banner.** Start a run from the
      Scenes tab (ScenesWorkspaceTab's own command bar), switch to another
      tab mid-run — GuidedNextStep's banner should appear and show live
      progress (it was hidden while Scenes was active, per the existing
      `currentTab !== "scenes"` guard — unchanged by this chunk).
- [ ] **GuidedNextStep's clip price is never the $0.30 fallback on a video
      whose real per-clip price differs.** Open a video with clips pending
      on a non-default model (e.g. Seedance 2.0) directly via URL (fresh
      page load, not a client-side nav from another video) — the "Animate
      scene 1" / "Animate the rest" cost text should show that model's real
      price immediately, not a stale/fallback number that then jumps a
      moment later.
- [ ] **RenderTab's now-faster cadence doesn't do anything surprising.**
      Start a render, confirm the RenderTab UI updates its progress
      smoothly (no visible jank from the cadence change from 10s→3s) and
      that completion is reported once render actually finishes, not early.
- **Cost:** free — every check above only needs a running pipeline stage on
  an existing test video; no new paid generation required beyond whatever
  stage you were already exercising.
- **Safety net:** if the banner ever looks "stuck" after this change,
  check whether the tab's local `taskRunning`/equivalent flag ever got set
  without a matching completion (the `enabled` gate on `useSharedTaskWatcher`
  is unchanged from the old `useTaskPoller` `enabled` prop, so a stuck flag
  reproduces a pre-existing bug in that tab, not something this chunk
  introduced — confirm against `main` before assuming regression).

---

## C42 — "learn this channel" chat front door + confirmable digest card · live end-to-end run
### (subsumes C41's entry below — `learn_channel` now has its first real door: chat + a thin HTTP route)

Verified so far at unit level only (C41: 18 tests, SYSTEM_STATE.md §C41; C42: 37 more, SYSTEM_STATE.md
§C42) — nobody has clicked through this live yet. C42 gives `learn_channel` its first real callers (a
chat intent + `POST /api/channel-dna/learn`), so this is now clickable in the sandbox/dev server, not
just a VPS Python-REPL exercise.

- [ ] **Chat: "learn this channel" end-to-end.** In the chat UI (home producer, no `video_id`), send
      "learn this channel: `<a real public YouTube channel URL>`". Confirm: (a) the ack reply lands
      immediately (within the chat-turn gateway window) and states the ~$0.10-0.30 cost; (b) a minute
      or two later, sending "show the channel digest" renders the `channel_dna_digest` card with real
      per-learner rows (not placeholders) and an honest header if anything failed; (c) field rows show
      real provenance ("via identity_builder · `<date>`").
- [ ] **Digest card actions round-trip for real.** On a rendered digest card: (a) tap **Revert** on a
      field that has a prior value — confirm the chat reply says "Reverted..." and `se db "SELECT
      channel_identity FROM channel_profiles WHERE tenant_id='<id>'"` shows the field's OLD value
      restored, with `_sources->'<field>'->>'learner' = 'restore'`; (b) type a correction (e.g.
      "actually the voice is more playful") and Save — confirm `se db "SELECT * FROM
      director_preferences WHERE tenant_id='<id>' ORDER BY created_at DESC LIMIT 1"` shows the exact
      verbatim text, `scope='channel'`; (c) tap **Keep everything** — confirm no DB write happens and
      the card closes out cleanly.
- [ ] **Thin route parity.** `curl -X POST .../api/channel-dna/learn` with a real channel_url (same
      auth as the chat door) — confirm the SAME digest appears via `GET .../api/channel-dna/status`
      moments later, and that it matches what "show the channel digest" renders in chat for the same
      tenant (proving the "one implementation, two doors" claim isn't just a code-identity check).
- [ ] **Full sequence against a real tenant's own channel** (from C41, still unverified). On the VPS:
      `await channel_dna.learn_channel(tenant_id)` (no `channel_url` — learns from whatever's already
      in that tenant's `channel_videos`). Confirm: (a) `learners["identity_builder"]["status"] ==
      "learned"` with a real `videos_analyzed` count > 0 (needs `FIRECRAWL_API_KEY` set and the tenant
      to already have imported channel videos with transcripts fetchable — reuse an
      onboarding-connected test tenant); (b) `se db "SELECT channel_identity FROM channel_profiles
      WHERE tenant_id='<id>'"` shows real voice_tone/hook_style/real_quotes text, not placeholders;
      (c) `_sources`/`_history`/`_last_run` envelope present and readable.
- [ ] **Not-my-channel path.** Call `learn_channel(tenant_id, channel_url="https://youtube.com/@
      SomeOtherChannel")` for a channel the tenant has never imported. Confirm `learners
      ["import_channel_videos"]["status"] == "learned"` with a real saved count, and that
      `channel_videos` actually gained rows for that tenant (`se db "SELECT count(*) FROM
      channel_videos WHERE tenant_id='<id>'"`).
- [ ] **Example script replaces cleanly.** Call with `example_script_text=<a real script>` twice in a
      row for the same tenant — confirm the SECOND call's `learners["script_template"]["summary"]`
      says "replaced" and `se db "SELECT count(*) FROM script_templates WHERE tenant_id='<id>'"`
      stays at 1 (single-slot, not accumulating).
- [ ] **Reference video folds in.** Call with `reference_video_url=<a real public YouTube URL>` —
      confirm `channel_identity->>'reference_video_style'` is populated with real summary text and
      `_sources->'reference_video_style'->>'learner' = 'reference_video'`.
- [ ] **Concurrency: two overlapping calls.** Fire `learn_channel(tenant_id)` twice back-to-back
      (e.g. two terminal tabs, or `asyncio.gather`) — confirm the SECOND returns `{"busy": true}`
      immediately rather than both running (check `se db "SELECT * FROM generation_claims WHERE
      video_id IS NULL"` mid-run to see the "dna" claim row), and that the chat/route doors surface
      that as a friendly "already learning" message rather than a silent no-op.
- **Cost:** per SYSTEM_STATE.md §C41/§C42's estimate, roughly $0.05-$0.30 in Claude calls (tenant's own
  BYOK key) per full run, plus Firecrawl scrape credits for the identity_builder step. Get a cost
  quote/go-ahead per storyengine/CLAUDE.md's money rule before running the full-sequence checks above
  on a real (not throwaway) tenant.
- **Safety net:** every learner is individually fail-soft (a missing `FIRECRAWL_API_KEY` or a
  transcript-fetch bot-block degrades that ONE learner to `"failed"` with a reason, never crashes the
  whole call — see docs/env-vars.md's `YTDLP_COOKIES_FILE`/`YTDLP_PROXY` for the same bot-block this
  reference_video step can hit).

---

## C43 — Channel-DNA consumption audit + convergence · live checks

Both fixes were verified with mocked externals (Claude API, `vision_call`) — no live Claude call, no
live vision call, this chunk. SYSTEM_STATE.md §C43.

- [ ] **`generate_prompts` provenance shows up in the real digest.** On a tenant that already has
      DNA learned (`channel_identity.style_description` set with `_sources.style_description.learner
      == "identity_builder"`), call `POST /api/system-prompts/generate` with a fresh
      `style_description` from the Settings > System Prompts page. Confirm: (a) `se db "SELECT
      channel_identity->'_sources'->'style_description' FROM channel_profiles WHERE tenant_id='<id>'"`
      now shows `"learner": "system_prompts"`; (b) "show the channel digest" in chat renders the
      `style_description` field row with that new provenance, not the old `identity_builder` tag; (c)
      any OTHER field (e.g. `voice_tone`) still shows `"learner": "identity_builder"` untouched.
- [ ] **`_thumbnail_style` against a real Kie key.** On a tenant with `kie_ai_api_key` configured and
      at least 3 imported `channel_videos` with `thumbnail_url` set, call
      `identity_builder.build_channel_identity(tenant_id)` (or trigger via "learn my channel" in
      chat). Confirm: (a) it completes without raising; (b) `channel_identity->'thumbnail_style'` is
      populated with real JSON (not empty/null) — this is the first LIVE exercise of the new
      `vision_call`-routed path (Gemini-first per that helper's provider chain, falling back to Kie
      Claude); (c) tail backend logs for the run — no "gateway silently dropped image blocks"-shaped
      failure (a refusal-marker log line from `vision_client._looks_like_refusal`, if it fires, means
      the SAME drift the convergence was meant to catch — flag immediately, don't silently retry).
- [ ] **Own-brand thumbnail generation still produces a real image.** On a channel with its own
      thumbnails imported (own-brand modeling path, `_run_channel_formula_thumbnail`), generate a
      thumbnail for a new video. Confirm it still completes and looks like a plausible match to the
      channel's own thumbnail style — this exercises the UNCHANGED `pipeline_executor.py` path end to
      end, confirming the byte-identity proof (zero-line diff) holds in practice, not just in the
      diff.
- **Cost:** the `generate_prompts` check is a normal Claude call (existing feature, no new cost). The
  `_thumbnail_style` check costs whatever `build_channel_identity`'s vision pass already costs
  (unchanged — same provider tier, same 3-thumbnail cap) — this is re-running an existing paid
  learner, not a new spend category.

---

## C44 — corrections loop wiring: `director_preferences` now reach GENERATION · live checks

No paid Claude call, no live LLM round-trip this chunk (sandbox has no key) — everything was proven
with monkeypatched DB reads. SYSTEM_STATE.md §C44.

- [ ] **A channel-wide correction actually changes the next real script/research/thumbnail prompt.**
      On a tenant with DNA already learned, say something like "actually the voice is more playful"
      in chat's DNA digest "Something off?" box (or via "always be more playful, never formal" as a
      standing instruction — either lands in `director_preferences` scope='channel'). Then trigger a
      real `run_script` (or research/thumbnail) for a video on that tenant. Confirm: (a) `se db "SELECT
      text FROM director_preferences WHERE tenant_id='<id>' AND scope='channel' AND active"` shows the
      correction; (b) tail backend logs / add a temporary print of the resolved system prompt (or check
      whatever debug surface exists) and confirm it ends with "STANDING CREATOR DIRECTIONS (obey these
      over any conflicting learned style):" followed by the correction text; (c) the actual generated
      script/research/thumbnail concept qualitatively reflects the correction (playful, not formal).
- [ ] **Digest shows the override.** After the correction above, "show the channel digest" in chat.
      Confirm: (a) if the correction's wording happens to keyword-match a field (e.g. mentions "voice"),
      that field's row shows "Overridden by your standing direction: ..."; (b) regardless of match, the
      "Your standing directions" footer lists the correction; (c) "forget that" removes it from BOTH the
      footer and the next build's system prompt (re-run (a)/(b) above after forgetting).
- [ ] **Per-video preference does NOT leak into generation.** In a specific video's co-pilot chat, say
      something clearly video-scoped ("the kitten in THIS video is orange, not gray") so it saves with
      `scope=<that video_id>` (not 'channel'). Build a DIFFERENT video for the same tenant. Confirm the
      orange/kitten note does NOT appear in that other video's resolved system prompt — only channel-
      scope preferences should ever reach `identity._standing_preferences_block`.
- **Cost:** whatever the script/research/thumbnail generation itself already costs (existing feature,
  no new spend category) — this chunk added a read, not a new paid call.

---

## C45 — onboarding hookup + intelligence-report retirement · live checks (P4.1 arc closer)

Everything this chunk touches was proven at unit level only (19 tests, SYSTEM_STATE.md §C45) with
monkeypatched DB/vault/`channel_dna` — no live Claude call, no live Firecrawl scrape, no real chat
onboarding run yet. This is the acceptance test for the WHOLE P4.1 arc (C40-C45): a fresh tenant
onboards, connects a real channel, gets learned, and sees the digest.

- [ ] **Fresh tenant, full onboarding, real channel.** Create (or reuse) a tenant with zero
      `channel_profiles` row. In the home chat, run the onboarding flow through the "channel" step
      with a real public YouTube channel URL. Confirm: (a) the ack states the ~$0.10-0.30 cost (this
      tenant must already have a Kie/Anthropic key from the earlier "key" step — expected, since the
      flow gates on one before reaching "channel"); (b) a minute or two later, `se db "SELECT
      channel_identity FROM channel_profiles WHERE tenant_id='<id>'"` shows a real `_last_run` with
      `identity_builder` learned (not the empty/skeleton shape); (c) `channel_videos` for that tenant
      has real rows (proving the import step actually ran before `_import_then_learn`'s learn_channel
      call, not concurrently with it).
- [ ] **Digest lands at the end of onboarding.** Continue the same onboarding session through
      competitors/connect_yt/connect_drive/upsell to the finishing turn. If the DNA learn pass
      finished by then, confirm the finishing turn's `cards` list includes a `channel_dna_digest` card
      (same shape "show the channel digest" renders) ALONGSIDE the modeling-angle card (or alone, in
      the no-competitor-data fallback) — proving two unrelated cards render correctly on one turn. If
      it's still running, confirm the finishing text says "still learning... ask me in a bit" instead.
- [ ] **Keyless path never blocks.** With a tenant that has never configured ANY generation key,
      attempt the "channel" step directly via `POST /api/onboarding/connect-youtube` (bypassing the
      chat flow's earlier key gate, to actually exercise the defensive check). Confirm: (a) the
      response has `"dna_learning": "needs_key"`, `"status": "ok"`; (b) `channel_videos` still gained
      rows (the import ran); (c) `generation_claims` gained NO new "dna"-stage row (learn_channel was
      never scheduled at all, not scheduled-then-failed).
- [ ] **Retired routes respond honestly.** `curl -X POST .../api/onboarding/intelligence-report`
      (and the two GET variants) on any tenant — confirm all three return HTTP 410 with a detail
      message naming Channel DNA / `learn_channel` as the replacement, not a 404/500 or a silent 200.
- **Cost:** per SYSTEM_STATE.md §C41/§C42's estimate, roughly $0.05-$0.30 in Claude calls (tenant's own
  BYOK key) for the DNA learn pass triggered by connect-youtube — same spend category already
  live-verification-queued under §C41/§C42, not a new one. Get a cost quote/go-ahead per
  storyengine/CLAUDE.md's money rule before running the full onboarding checks above on a real (not
  throwaway) tenant.
- **Safety net:** every learner inside `learn_channel` is individually fail-soft (see §C41/§C42's own
  safety-net note) — a bad run here degrades to a partial digest, never a broken onboarding flow.

---

## C46a — generalized script-quality critic hook · live grade-a-real-script check

Everything this chunk touches was proven at unit level only (35 tests, SYSTEM_STATE.md §C46a) with a
fake Claude client returning canned JSON — no live call has confirmed the judge still discriminates
weak-vs-strong scripts the way `originality.py`'s own `_selftest()` proves it does standalone, nor that
the generalized `@@@SCENE n@@@` edit loop produces a sane targeted edit against a REAL model response
(vs. the fake client's clean marker output).

- [ ] **Real critique call, both verdicts.** On a tenant with a live Anthropic/Kie key, run
      `python3 storyengine/backend/originality.py`-style self-test through `script_quality.
      critique_script` directly (or trigger `run_script` on one weak and one strong test video) —
      confirm the weak script gets `revise`/`regenerate` with concrete `rewrite_guidance`, the strong
      one gets `pass`, matching `originality.py`'s existing self-test discrimination.
- [ ] **Real edit-loop round-trip.** Trigger a `revise` verdict on a real multi-scene script and confirm
      `edit_draft_with_violations`'s response actually comes back with the SAME scene count and only the
      flagged scene(s) changed — the fake-client tests prove the prompt/parse plumbing, not that a real
      model reliably preserves untouched scenes byte-for-byte.
- [ ] **rules_text pass is genuinely useful, not noise.** Pick a tenant with a populated
      `script_templates.structure` row and confirm the judge's `rule_verdicts` are sensible (not
      hallucinated rules, not silently empty) against that tenant's real house format text.
- [ ] **needs_review actually surfaces.** Force a script to fail the full bounded loop (e.g. inject
      deliberately bad `writer_guidance`) and confirm: (a) `run_script` returns `{"status":
      "needs_review", ...}`; (b) the video's `status` column did NOT advance past its pre-scripting
      value; (c) `script_validation.quality_critic` shows `passed: false` with the violations listed;
      (d) the modeled path's `hold_status` revert actually un-sticks a status that `_run_modeled_script`
      had already advanced.
- **Cost:** 1-3 extra Claude calls per script generation (tenant's own key) — same class as the
  originality grade call already live-verification-queued nowhere explicitly (it shipped silently
  before C46a); this is the first live check of that spend category too.
- **Safety net:** fail-open throughout (any error returns a `pass` verdict, per script_quality.py's own
  docstring) — a broken live run degrades to "grade unavailable, ships as-is," never a blocked pipeline.

---

## C46b — per-channel quality-rules store · live rules-upload round-trip check

Everything this chunk touches was proven at unit level only (61 tests, SYSTEM_STATE.md §C46b) — a fake
parser client, fake DB rows, fake chat state. No live check has confirmed the doc-upload → parse →
confirm-card → save round trip against a REAL uploaded document, nor that the composed `rules_text`
actually changes a real Claude judge's grading behavior.

- [ ] **Real doc upload + parse.** On a tenant with a live Anthropic/Kie key, drop the real
      `storyengine/notes/dvsu-quality-law.md` (or an excerpt) into chat as a file attachment, say
      "here are my quality rules," and confirm: the file's `chat_assets.parsed_text` round-trips
      through `quality_rules.parse_markdown_table` (should hit the deterministic table path, zero LLM
      cost) into the expected rule count/severities, the draft card shows the right hard-gate/warn/
      guidance split, and NO `quality_rules` row exists yet (query `quality_rules` table — should be
      empty for this tenant until the confirm tap).
- [ ] **Confirm tap actually saves.** Tap "Save these rules" on the card; confirm the exact parsed rows
      landed in `quality_rules` (`rule_id`/`law`/`severity`/`applies_to` match what the card showed), and
      that `chat_assets.filed_as = 'quality_rules'` was set on the source file.
- [ ] **Prose fallback.** Paste a few "always/never"-style rules as plain prose (not a table) and confirm
      the LLM fallback parser (`llm_parse_rules_prose`) produces sane rows — this is the one code path
      unit tests could only fake-client-test, never confirm against a real model's JSON discipline.
- [ ] **Scope resolution changes real grading.** With a hard-gate rule saved and scoped to `{"all": true}`,
      generate (or re-grade) a real script that deliberately violates it (e.g. a banned hype word) and
      confirm `script_validation.quality_critic.violations` names that rule — and that a script on a
      DIFFERENT scope (e.g. a rule scoped `{"story": true}` on a non-`static_docu` video) is correctly
      absent from the judge's system prompt (`docs/failure-modes.md`-style spot check via VPS logs, not
      just the DB row).
- [ ] **CRUD route smoke test.** `GET /api/quality-rules`, `POST /api/quality-rules`, `PATCH
      /api/quality-rules/{id}` against a real tenant token — confirm tenant isolation (a second tenant's
      token never sees the first tenant's rules).
- **Cost:** the deterministic table parser is free; the prose fallback and the rules-augmented script
  grading pass are the only paid calls here — same class as C46a's already-queued grading spend, no new
  cost category.
- **Safety net:** parsing/ingestion never writes without an explicit confirm tap (proven at unit level);
  scope resolution fails closed on a garbage/unknown key (logged, never matches, never crashes); grading
  itself stays fail-open per script_quality.py's existing contract.

---

## C46c — DvsU deltas as the reference-tenant table-driven gates · live seed run

Everything this chunk touches was proven at unit level only (28 tests, SYSTEM_STATE.md §C46c) — real law
text copied verbatim into test fixtures, but no live run has ever seeded the ACTUAL `quality_rules` table
for the ACTUAL DvsU tenant, nor confirmed a real script-hold generation reads the seeded values. This
chunk deliberately did NOT touch the live DB (DvsU is a real production tenant on the shared sandbox DB) —
that's this section's job.

- [ ] **Dry run first (always).** From `storyengine/backend` on the VPS (or anywhere with `DATABASE_URL`
      set):
      ```bash
      cd storyengine/backend
      ./venv/bin/python scripts/seed_dvsu_quality_rules.py --tenant-id <DvsU's tenant UUID>
      ```
      (or `--channel-name "<substring of DvsU's channel_profiles.channel_name>"` if the UUID isn't handy
      — the script refuses to proceed unless that substring matches EXACTLY one tenant). Confirm the
      printed report: **74 rows**, scope split **story 49 / research 21 / all 4**, severity split
      **hard_gate 53 / warn 14 / guidance 7**. No DB write happens in this step — sanity-check the numbers
      before going further.
- [ ] **Confirm the live table is still empty for DvsU** before seeding (expected — C46b's own live check
      confirmed 0 rows for every tenant): `se db "SELECT count(*) FROM quality_rules WHERE tenant_id =
      '<uuid>'"` → expect `0`.
- [ ] **Apply the seed:**
      ```bash
      ./venv/bin/python scripts/seed_dvsu_quality_rules.py --tenant-id <DvsU's tenant UUID> --apply
      ```
      Confirm: "Upserted 74 quality_rules row(s)". Then `se db "SELECT rule_id, severity, applies_to FROM
      quality_rules WHERE tenant_id = '<uuid>' ORDER BY rule_id"` → spot-check QL-1 (severity=hard_gate,
      applies_to={"story":true}), QL-12 (severity=hard_gate, applies_to={"story":true} — QL-1..20 all
      score "story"), QL-25 (severity=hard_gate, applies_to={"research":true}).
- [ ] **Re-run is idempotent.** Run the exact same `--apply` command again; confirm row count stays 74
      (no duplicates — `ON CONFLICT (tenant_id, rule_id) DO UPDATE`) and `updated_at` moved on every row.
- [ ] **Post-seed smoke: the gates actually fire from table values, not just exist as rows.** Trigger one
      DvsU script-hold generation for a single locked machine (the app UI, or `POST
      /api/pipeline/machine-script/{video_id}?machine=<name>` per the existing DvsU preview route) and
      confirm via `se logs backend` / the returned `preview.warnings`:
      - QL-12's REAL banned-adjective list is now active (not just the old ad hoc phrase list) — if the
        writer's draft ever used one of "incredible/amazing/stunning/insane/epic/jaw-dropping/mind-
        blowing/breathtaking/unbelievable/spectacular", confirm it's flagged (it wasn't, pre-seed, for
        several of these words — see SYSTEM_STATE.md §C46c's mismatch finding).
      - The word-floor/twist-gate checks still behave identically to pre-seed (D1/D2/D3 were already
        correct hardcoded values — the seed should change NOTHING observable for those three, only prove
        the values now come from the table). Confirm by diffing `preview.warnings` against a pre-seed
        preview run for the SAME machine/research payload, if practical — should match exactly.
      - Confirm `PipelineExecutor._load_dvsu_rule_overrides`'s one new `SELECT ... FROM quality_rules`
        query shows up in the backend's query logs for this run (proves it's actually being read, not
        just sitting unused).
- **Cost:** the seed script itself is free (deterministic parse + DB writes only, no Claude/Kie calls).
  The post-seed smoke test's script-hold generation is a normal per-machine Claude call — same cost class
  as any other script-hold run for this tenant, no new cost category introduced by this chunk.
- **Safety net:** the seed script defaults to dry-run (write requires explicit `--apply`); `bulk_create_
  rules` is idempotent (re-seeding after editing the doc edits rows in place, never duplicates); every
  gate fails back to today's exact hardcoded behavior if a row is later deactivated or deleted (no
  quality_rules row = no override, proven at unit level).

---

## C46e — Land Ryan's OR rulings + the per-channel pattern capability · live checks

Everything this chunk touches was proven at unit level only (SYSTEM_STATE.md §C46e — 70 new tests, `git
stash -u` non-vacuous). Three live gaps this section closes: the `channel_patterns` table exists live
(migration 106 applied) but has never actually scored a real tenant's imported analytics; the Most Hated
mode's QL-7-MH/QL-9-MH rows exist only as code (`_MOST_HATED_MODE_ROWS`), never seeded into the live
`quality_rules` table for any real tenant; and the chat digest's Confirm/Retire buttons have never been
tapped against a real `channel_patterns` row.

- [ ] **Import-time pattern analysis, live.** Pick a tenant with imported `channel_videos` history (DvsU
      or any onboarded creator with >=5 videos carrying `view_count`+`published_at`). Trigger "learn this
      channel" (chat, or `POST /api/channel-dna/learn`) and confirm the digest's `learners.pattern_analysis`
      entry: `status="learned"` with an N-proposed count, or `status="skipped"` with the "not enough
      data"/"nothing stood out" message if the channel is too small/uniform. Then `se db "SELECT pattern,
      polarity, source, status, evidence FROM channel_patterns WHERE tenant_id = '<uuid>' ORDER BY
      created_at DESC"` — confirm real proposed rows exist, `source='import_analysis'`,
      `status='proposed'`, and `evidence` carries a real `video_ids`/`metric`/`channel_median`/
      `video_value`/`delta_pct`/`cohort_size` shape (not a placeholder).
- [ ] **Digest card renders the patterns section.** "Show the channel digest" in chat for that same
      tenant — confirm the card's `patterns` array is non-empty and the frontend (`ChatCore.tsx`'s
      `DnaDigestCard`) actually renders the "Patterns from your analytics" section with Confirm/Retire
      buttons (not just present in the JSON payload — a real browser look, per the Visual Output
      Verification Rule).
- [ ] **Confirm takes effect; nothing before it does.** Before tapping Confirm on an 'anti' proposal, run
      `identity_builder.build_channel_identity` (or trigger "learn this channel" again) and confirm the
      flagged video is STILL included in the ranked candidate pool (`_ranked_videos`) — proposed rows must
      never exclude anything. Tap Confirm; `se db "SELECT status, confirmed_at, confirmed_by FROM
      channel_patterns WHERE id = '<row-id>'"` → `status='confirmed'`, `confirmed_by='chat'`, timestamp
      set. Re-run identity building for the same tenant and confirm the flagged video's `video_id` is now
      ABSENT from the ranked pool the transcripts get pulled from (log the candidate list, or temporarily
      lower `top_n` to make the exclusion's effect on which videos get analyzed unambiguous).
- [ ] **Retire reverses it.** Tap Retire on the same now-confirmed row; confirm `status='retired'`; re-run
      identity building once more and confirm the video is back in the eligible pool.
- [ ] **Most Hated mode seed + gate, live.** `scripts/seed_dvsu_quality_rules.py --apply` now seeds 76
      rows (the doc's 74 plus `_MOST_HATED_MODE_ROWS`'s QL-7-MH/QL-9-MH — confirmed at unit level by
      `test_dry_run_reports_most_hated_scope_bucket`, never run live). Run the dry-run first, confirm
      "Parsed 76 law(s)" and a `dvsu_mode=most_hated: 2 rule(s)` line, then `--apply` for a DvsU-style
      tenant; `se db "SELECT rule_id, applies_to FROM quality_rules WHERE tenant_id='<uuid>' AND rule_id
      IN ('QL-7-MH','QL-9-MH')"` → confirm both rows exist with `applies_to={"dvsu_mode":"most_hated"}`.
      Set a real video's `research_payload.dvsu_mode = "most_hated"`, trigger a script-hold
      preview for one locked machine, and confirm via `preview.warnings`/logs that the opener-budget check
      is now firing at ~20% (not the spec-block default 60%) and that a video WITHOUT `dvsu_mode` set
      stays on the 60% default — proving the override never leaks across videos.
- [ ] **QL-66 advisory fires (or doesn't) as expected.** Generate a channel-formula thumbnail for a video
      whose title matches one of the five locked series (e.g. "Every ... Ever Built") and confirm
      `bot_activity` gets a `status='running'` row containing "QL-66" whenever the model's chosen text
      isn't the exact locked phrase — and confirm generation still SUCCEEDS (advisory only, never blocks).
- **Cost:** `_run_pattern_analysis` adds one `channel_videos` SELECT per `learn_channel` run — free (no
  new Claude/Kie calls). Confirm/retire are free DB writes. The Most Hated mode seed is free (same
  deterministic write path as C46c's seed script). The thumbnail QL-66 check runs inside the EXISTING
  channel-formula thumbnail generation — no new cost category.
- **Safety net:** every exclusion/override starts inert (empty table / no seeded row) — a live check that
  finds nothing proposed or nothing seeded is not a failure, just an untested-yet path; re-run against a
  tenant with more analytics history or hand-seed the Most Hated rows to force the path.

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

## §C46a-watch · First real builds after deploy: needs_review rate
The generic critic now HOLDS a script at needs_review (violations attached to
script_validation.quality_critic) instead of silently advancing when it still fails after 2 targeted
edits + 1 reroll. Expected: rare. WATCH the first ~5 real script generations post-deploy — if
needs_review fires on obviously-fine scripts, the judge prompt is too strict for that tenant's niche;
tune before C46c widens the gate surface. Fail-open means infra errors can never cause this.

## §RLS-recurrence · INVESTIGATE: why did RLS turn off on static_reference_cache/channel_video_retention?
Found 2026-07-19 by C46e's worker, confirmed + RE-FIXED live by the orchestrator (idempotent re-enable,
verified relrowsecurity=true). C01a had enabled + verified these same tables earlier — something in
between disabled RLS (suspect: a DROP+recreate path in in-process DDL, or an out-of-band change).
Watch: re-check `SELECT relname, relrowsecurity FROM pg_class WHERE relname IN
('static_reference_cache','channel_video_retention')` after the next few backend restarts; if it
regresses again, grep for DROP TABLE paths touching these and fix at the source. (`vault.secrets`
rls=false is Supabase's own internal vault schema — by design, ignore.)
