# HANDOFF - StoryEngine chat-first producer

**Written:** 2026-06-22
**For:** the next session, to resume cold.
**Read order:** this file -> `GOAL.md` (north star + full Log) -> `~/.claude/plans/streamed-zooming-pascal.md` (architecture + file refs).

---

## One-line state

The chat-first "ChatGPT for video" experience is LIVE in prod. A genuinely
brand-new user now AUTO-lands in the guided setup (no "Start Here" click needed),
gets onboarded conversationally (intent -> what to automate -> paste channel -> 1-3
competitors -> soft Advanced-tier pitch -> "how do you want to model this?" -> 3
niche ideas), picks an idea, and the producer takes them through cards -> plan ->
created video. The onboarding now STICKS: intent/goals/niche/channel/competitors are
saved durably on channel_profiles.creator_brief and hydrated into every future
conversation, so the producer remembers across sessions. Everything below is
deployed and healthy. Remaining: an authenticated brand-new-user click-through
proof, O4 piece 3 (surface channel/competitors/intel in the visual pages), and
Phases 4-5 (deeper channel intelligence + follow-up edits).

- **Branch:** `feat/chat-first-producer`
- **origin/main == `5c166691`** (O4 piece 3). My chat-first work now lives interleaved
  on main with another session's parallel work (YouTube ruleset, GPT Image 2 character
  consistency, image clients, pipeline_executor, production tabs). That session is still
  actively committing+deploying to main AND leaves uncommitted WIP in the shared working
  tree. DEPLOY DISCIPLINE that worked: (1) `git fetch` + check the `<vps-head>..<your-push>`
  commit range before any VPS pull; (2) commit ONLY your own files (never `git add -A`);
  (3) when your push isn't a fast-forward and the shared tree is dirty with their WIP,
  do NOT rebase/stash/reset in it - instead `git worktree add --detach /tmp/se-deploy
  origin/main`, `git -C /tmp/se-deploy cherry-pick <your-commit>`, push from there,
  `git worktree remove`. That lands your commit cleanly on top of theirs without
  touching their work.
- **Prod-HEAD reality:** prod (VPS `~/projects/economy-fastforward`) was at
  `f1d44ddb`, NOT the `3def6c72` the prior handoff claimed - that commit was a
  docs-only GOAL.md change never deployed. The O4 pull (f1d44ddb -> e1af585d) added
  only the O4 code + that harmless doc. Always verify the VPS HEAD before deploying.
- **Prod:** https://storyengine.dev/api/health -> 200, healthy. Migrations 060 + 061
  applied (061 journal-confirmed on the latest restart).

---

## What is LIVE right now (deployed + verified)

**Chat is the home screen.** `/` renders `<ChatHome/>` for authed users; the old
dashboard is gone from `/`.

**The full flow as it works today:**
1. Welcome screen with a **"Start Here"** button (`start_onboarding` flag).
2. **Intent fork:** "tell stories" vs "automate my channel" (single-select card).
3. **What to automate:** ideas / scripts / voiceover / thumbnails / whole videos /
   all (multi-select). Stored as `goals`, tailors producer defaults.
4. **Paste channel URL** (composer text, not a card) -> `connect_youtube` scrape.
5. **1-3 competitor URLs** -> `analyze_competitors` (official YouTube Data API via
   `YOUTUBE_API_KEY` on the VPS - NOT yt-dlp, which is bot-blocked from the VPS IP).
6. **Soft Advanced-tier pitch** (Smart Analytics + Autopilot engine, no-pressure,
   "switch on anytime").
7. **"How do you want to model this?"** - summarizes the competitors' winning
   FORMAT + proposes 4 ownable adaptation angles (swap language / theme / audience /
   focus, e.g. Easy English Listening -> Easy Spanish/German, or workplace/travel
   scenarios). User picks one OR types their own niche. Stored as `state["niche_angle"]`.
8. **3 ideas FOR THAT NICHE** - modeling the winning format (not copying the
   competitor's topic), citing real title + view counts + recency (past week,
   `hours_old <= 240`). Tappable `idea_choice` cards.
9. **Pick an idea (or type your own)** -> hands off to the **producer**, which now
   KNOWS the niche/channel/competitors via `_creator_brief(state)` injected into
   every turn.
10. **Producer intake:** asks only what's missing, offers selector cards - **LOOK**
    (6 style presets with the same preview thumbnails as the New Video flow) and
    **LENGTH** (slider, 5s-30min, 5s steps) -> **production plan** -> "Make it" ->
    real video row created + pipeline kicked off -> **live friendly progress**
    tracker in chat (Story Approved -> Script Ready -> Visuals Creating -> Video
    Rendering -> Ready for Review).

---

## Key files (where the work lives)

**Backend** (`~/economy-fastforward/storyengine/backend/`):
- `routes/chat.py` - THE central file. `ChatTurnRequest/Response`, producer intake
  (`call_producer` via `_creator_brief`), `_spec_to_create_request` (spec -> video +
  stage plan + length seconds->minutes), onboarding step-machine `_handle_onboarding`
  (intent -> goals -> channel -> competitors -> upsell -> modeling -> ideas) +
  `_finish_onboarding`. Modeling/ideas helpers: `_wait_for_scrape`,
  `_recent_competitor_rows`, `_video_lines`, `_claude_json` (sync, run via
  `asyncio.to_thread`), `_propose_modeling_angles` (4 angles),
  `_generate_competitor_ideas` (3 ideas), `_present_ideas_turn`, `_seed_producer`.
  Import: `from database import execute, fetch_all, fetch_one`.
- `producer_prompt.py` - `PRODUCER_SYSTEM_PROMPT`, `build_system_prompt`,
  `call_producer(..., api_key=, model=MODEL)`. `MODEL = "claude-sonnet-4-6"`,
  `ANTHROPIC_DIRECT_BASE_URL = "https://api.anthropic.com"`. LOOK card uses canonical
  style values (pixar_3d/flat_2d/realistic/anime/watercolor/comic); LENGTH is `slider`.
- `routes/onboarding.py` - the (now-registered) onboarding backend: `connect_youtube`,
  `analyze_competitors`, intelligence report, status/complete. NOTE: these take
  `(body, background_tasks, tenant_id)` - the missing `background_tasks` arg was a
  real bug; don't drop it again.
- `status_map.py` - `friendly_state()` + `FRIENDLY_STATE` map.
- `main.py` - registers `chat` + `onboarding` routers.
- `migrations/060_chat_conversations.sql` - applied live.

**Frontend** (`~/economy-fastforward/storyengine/frontend/src/`):
- `components/chat/ChatHome.tsx` - chat UI: welcome + Start Here, message thread with
  `renderRich` (minimal `**bold**`), Composer, SelectorCards (style thumbnails via
  `visualPresetById`, length slider, idea/intent/goals/upsell cards),
  ProductionPlanCard, CreatedCard (live SSE friendly tracker).
- `lib/visual-presets.ts` - shared 6 presets (used by ChatHome AND pipeline/page.tsx).
- `app/page.tsx` - `/` = `<ChatHome/>`.
- `lib/api.ts` - `sendChatTurn`, types (start_onboarding, ChatCard, ProductionPlan).

---

## How to deploy (the gotcha that caused a brief outage)

Deploy = push main from local, VPS pulls, restart.

```
# from local:
cd ~/economy-fastforward/storyengine
git push origin feat/chat-first-producer:main      # ungated from local

# on VPS (ssh storyengine-vps):
cd ~/projects/economy-fastforward && git pull --ff-only
# backend: MUST kill -9 (SIGTERM HANGS uvicorn -> closes listener -> 2-3min 502).
#   systemd Restart=always revives it after kill -9.
# frontend: needs `npm run build` first, then SIGTERM restart is fine.
```

- Real VPS deploy repo = `~/projects/economy-fastforward` (NOT `~/economy-fastforward`).
- Migrations auto-apply on backend startup (`_run_pending_migrations`).
- Redis/arq are NOT running on the VPS -> pipeline uses FastAPI BackgroundTasks
  fallback (which is what the chat kickoff already uses - fine).
- Producer needs the tenant's DIRECT Anthropic key from Vault (`anthropic_api_key`),
  NOT the Kie gateway (Kie can be banned). Ryan's key is set on his profile.
- After deploy, poll https://storyengine.dev/api/health for `{"status":"healthy"}`.

---

## How to test the flow

Hard-refresh storyengine.dev -> **Start Here** -> **Automate my channel** -> pick
what to automate -> paste a channel URL -> paste 1-3 DISTINCT competitor URLs ->
keep rolling past the Advanced pitch -> you should hit **"how do you want to model
this?"** with 4 angle cards -> pick one OR type your own niche -> get **3
niche-adapted ideas** with real view counts -> pick one -> producer asks LOOK +
LENGTH -> production plan -> Make it -> live progress.

(Downstream image/video stages depend on Kie.ai; if Kie is banned they fail
gracefully in the tracker - intake + script work regardless.)

---

## What's PENDING (in priority order)

1. **O4 polish:**
   - [DONE 2026-06-22] Auto-trigger onboarding for brand-new users (no channel, no
     videos, onboarding not completed) - ChatHome fetches getOnboardingStatus on
     mount and fires `start_onboarding`; established tenants get the normal welcome.
   - [DONE 2026-06-22] Persist `intent`/`goals`/`niche_angle`/`channel`/`competitors`
     DURABLY on `channel_profiles.creator_brief` (migration 061), written during
     onboarding (the `_save_creator_brief` upsert called from `_ob_reply` + the
     niche-set point) and hydrated into every new conversation (`_hydrate_creator_brief`
     in `chat_turn`, non-onboarding path, fills only missing keys). `_creator_brief`
     unchanged downstream.
   - [DONE 2026-06-22, HEAD 5c166691] Piece 3: surfaced the chat-onboarding setup +
     intelligence report on /competitors (two cards: "Your setup" from creator_brief +
     an "Intelligence report" panel reading the previously-unshown intelligence_reports
     row). Backend exposed creator_brief + youtube_channel_name on /api/onboarding/status;
     frontend getCreatorSetup + getIntelligenceReport (coerces JSONB-string report fields).
     Skipped Visual Styles (independent visual_styles assets, nothing onboarding maps to it).
     Owed: an authed view of /competitors to confirm the cards render.
   - [LEFT] Authenticated brand-new-user click-through: confirm the auto-trigger fires
     for a fresh tenant and the niche/goals survive into a brand-new conversation.
2. **Phase 4 - deeper channel intelligence in the producer** (overlaps O4; the
   intelligence report already feeds ideas - extend so the producer's
   titles/hooks/thumbnail directions reflect proven channel patterns).
3. **Phase 5 - conversational follow-up edits** [DONE 2026-06-22, layer 1+2, HEAD
   488b2c0b]. A dedicated handler in chat.py (`_classify_followup` -> `_apply_followup_edit`
   -> `_make_stage_step`), NOT the orchestrator (it can't apply params + uses the 404
   model + is flag-gated off; registry actually works). "make it shorter" / "redo the
   thumbnail" / "change the look" / "keep going" all route correctly; unclear -> ask.
   LIVE-PROOF owed: an authed follow-up on a real video (Kie-independent "make it
   shorter" is the clean test).
4. **Phase 6 - full finished-video proof** the moment Kie.ai is restored.
5. **Track B (output quality / visual chain)** - parallel, Kie-blocked. Lives in the
   `skills/video-pipeline/storyboard/coverage.py` work (see GOAL.md Track B). This is
   a SEPARATE track - don't tangle it with the chat work.

---

## Known caveats / lessons (don't relearn these)

- **LENGTH slider captures intent, not exact output yet.** The pipeline sizes in
  whole minutes (`int(float(len))`), so a 30s pick won't guarantee a 30s final cut
  until the short-form pipeline route lands. Flagged to Ryan.
- **Test with REAL function bodies, not mocks of the thing under test.** Two runtime
  bugs (missing `background_tasks` arg; `fetch_all` not imported) slipped through
  because earlier sims mocked the very functions that were broken. Now: run the real
  bodies, mock only Claude + DB.
- **Don't send customers through Google Cloud Console.** Ryan already built one-click
  OAuth setup for customers; the YouTube data path is handled on his end
  (`YOUTUBE_API_KEY` is set on the VPS). Build ON the existing setup.
- **Producer model id:** use `claude-sonnet-4-6` (the orchestrator's old
  `claude-sonnet-4-20250514` 404s on the live API).
- **Reading live Vault secrets over SSH is blocked by the auto classifier** - diagnose
  via journal logs (`journalctl -u storyengine-backend`) + code reads instead.

---

## SECURITY follow-up (Ryan is aware)

The VPS git remote URL has a GitHub PAT in plaintext. Rotate it + move to a
credential helper.

---

## Do not touch (separate work in the tree)

`skills/video-pipeline/storyboard/coverage.py`, `tests/test_coverage.py`,
`proof_spec.json`, `backend/scripts/coverage_to_app.py`, `SEEDANCE-PIPELINE-PLAN.md`
are the concurrent coverage/Seedance track (Track B). Leave them as-is unless the
task is explicitly about that track. `GOAL.md.bak-20260622-092738` is the pre-pivot
backup - keep it.
