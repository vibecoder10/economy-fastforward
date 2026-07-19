# Architectural Decisions

> Append-only log of significant choices and WHY they were made.
> Future sessions: read this before re-litigating settled questions.
> Format: Date, Decision, Context, Alternatives Considered, Why This Won.

---

## 2026-04-11 — Three-Tier Data Architecture: Hot DB + Vectors + Cold Archive

**Decision:** Implement content distillation pipeline that extracts structured intelligence from raw data (transcripts, research payloads) into a `content_intelligence` table with pgvector embeddings. Raw data stays in DB for now but is no longer selected in hot queries. Future: archive raw to GCS/R2.

**Context:** Supabase free plan exceeded — 5.5 GB egress from competitor transcripts (10-20 KB each × 5000+), research payloads, and agent logs fetched on every page load. At 500-1000 SaaS customers, unoptimized Supabase costs ~$2,700/mo vs ~$250/mo with tiered architecture.

**Alternatives:**
1. Just upgrade Supabase Pro ($25/mo) — delays problem, doesn't build data moat
2. Move everything to self-hosted Postgres — more ops work, no vector search built-in
3. Distill + vectorize + tier (chosen) — solves egress, builds queryable intelligence layer, enables cross-tenant insights

**Why this won:** Data is the product. Raw transcripts are expensive and useless at scale. Distilled intelligence (hook types, topic tags, structure patterns) + vector embeddings enable semantic search, trend detection, and cross-tenant learning. Each customer makes the intelligence better for all customers — network effect built on data.

**Key choices:**
- Embedding model: OpenAI text-embedding-3-small (1536 dims, $0.02/1M tokens) — cheapest, already have API key
- Summarization: Claude Haiku (~$0.001/transcript) — cost-efficient extraction
- Vector index: HNSW (no training required, works from row 1)
- Storage: pgvector in Supabase (hot), GCS Nearline for raw archive (future)

---

## 2026-04-06 — Thinking Partner + Structured Workflow over GSD installation

**Decision:** Cherry-pick GSD patterns into custom Claude Code skills rather than installing GSD as a dependency.

**Context:** GSD (v1 and v2) offers structured dev workflows. Our repo already has a 6-agent autonomous team, CLAUDE.md session protocol, and custom skills. GSD's file conventions (PROJECT.md, ROADMAP.md, STATE.md) would clash with our existing tasks/todo.md, tasks/lessons.md, SYSTEM_STATE.md.

**Alternatives:**
1. Install GSD globally — conflicts with existing agent system and file conventions
2. Install GSD locally for solo sessions only — still creates duplicate state files
3. Cherry-pick the best patterns into our own skills — fits our existing system

**Why this won:** We get the core value (discuss before plan, verify before done, proactive thinking) without the overhead of a second state management system. Our agent team is already beyond what GSD offers for multi-agent execution.

---

## 2026-04-06 — decisions.md as append-only log (inspired by GSD 2)

**Decision:** Add `tasks/decisions.md` for architectural choices, separate from `tasks/lessons.md`.

**Context:** GSD 2 introduced DECISIONS.md as an append-only architectural register. Our lessons.md captures mistakes and patterns. But *choices* (why we picked approach A over B) were scattered in todo.md handoffs and lost between sessions, causing future sessions to re-debate settled questions.

**Alternatives:**
1. Keep decisions in lessons.md — muddies the purpose (mistakes vs choices)
2. Keep decisions in todo.md handoffs — gets buried under task tracking
3. Separate decisions.md — clear purpose, easy to scan

**Why this won:** Different purpose = different file. Lessons = "don't do X." Decisions = "we chose Y because Z." Both are read at session start but serve different needs.

---

## 2026-04-06 — Markdown reorganization into typed folders

**Decision:** Move scattered root-level MDs into `docs/reports/`, `docs/reviews/`, `docs/reference/`, and rename `dailyjournal.md` → `tasks/roadmap.md`.

**Context:** 9 markdown files at root level with no organization. Completion reports mixed with config. Daily journal was actually a product roadmap.

**Alternatives:**
1. Leave them — works but cluttered, hard to find things
2. Move everything into docs/ flat — better but still no semantic grouping
3. Typed subfolders (reports, reviews, reference) — clear intent per folder

**Why this won:** Folder name tells you what kind of doc it is. Reports are historical artifacts. Reviews are analysis docs. Reference is outdated-but-preserved. Plans and specs already had this structure under docs/superpowers/.

---

## 2026-03-26 — Supabase as source of truth, Airtable as legacy

**Decision:** StoryEngine SaaS uses Supabase PostgreSQL as the single source of truth. Airtable remains for the VPS cron pipeline only.

**Context:** The VPS pipeline was built on Airtable (string-matched joins, no real relations). StoryEngine needs proper relational data, multi-tenancy, RLS.

**Alternatives:**
1. Migrate everything to Supabase — breaks VPS pipeline that works
2. Keep Airtable as source of truth — can't do multi-tenancy, RLS, proper joins
3. Dual-write (Airtable + Supabase) — complexity nightmare
4. Supabase for SaaS, Airtable for VPS pipeline — clean separation

**Why this won:** Don't break what works (VPS pipeline). Build new things right (Supabase). SupabaseAdapter bridges the gap for pipeline_executor.

---

## 2026-04-02 — Custom JWT Auth (not Supabase Auth) [ADR-001]

**Decision:** ✅ IMPLEMENTED — Custom auth with PBKDF2-SHA256 + JWT, not Supabase Auth.
**What was built:** `google_auth.py` handles registration, login, Google OAuth. JWT signed with SESSION_SECRET (30-day expiry). Accounts table stores credentials.
**Trade-off:** Must implement password reset ourselves (Supabase Auth does it free). But: full control over auth flow, no Supabase Auth SDK dependency on frontend.

---

## 2026-04-02 — S3-compatible storage, not Google Drive [ADR-002]

**Decision:** Migrate asset storage from Google Drive to Supabase Storage or Cloudflare R2.
**Why:** Google Drive requires per-user OAuth, has rate limits, URLs need conversion for Airtable. S3 gives: signed URLs, per-tenant isolation, CDN, no OAuth dance.
**Trade-off:** Migration effort. Existing pipeline writes to Drive everywhere. Need adapter layer.

---

## 2026-04-02 — Redis job queue, not in-process asyncio [ADR-003]

**Decision:** Add Redis-backed job queue for pipeline execution.
**Why:** Current in-process tasks die with the server. No retry. No priority. No concurrency control across tenants. Redis enables: persistent jobs, rate limiting per tenant, horizontal scaling.
**Trade-off:** Operational complexity (Redis server). Worth it for reliability.

---

## 2026-04-02 — Pooled API keys for launch, not BYOK [ADR-004]

**Decision:** Platform provides API keys for Claude, ElevenLabs, image gen. Users don't bring their own.
**Why:** BYOK creates terrible onboarding ("go sign up for 5 services before you can use ours"). Pool keys, absorb cost, bill via subscription.
**Trade-off:** Higher COGS. Offset by subscription pricing. BYOK available as Enterprise option.

---

## 2026-04-03 — Autonomous Agent Team, 6 agents all Opus [ADR-005]

**Decision:** ✅ IMPLEMENTED — 6 AI agents run on cron, handle PRDs, fix bugs, test UI.
**What was built:** Orchestrator, Backend Dev, Frontend Dev, QA, Pipeline Tester, Security Auditor. RUBRIC command center. PRD decomposition + auto-execution. Cross-agent handoffs. Telegram integration.
**Trade-off:** High API cost (~$50-100/day at turbo cadence). Offset by velocity — the agent team built auth, billing, onboarding in 2 days. Can scale back cadence after initial build sprint.

---

## 2026-04-04 — Supabase Storage for SaaS, Google Drive for VPS [ADR-006]

**Decision:** PARTIALLY IMPLEMENTED — Supabase Storage wired for storyboard grids. Google Drive still used for voice/images/video by the VPS pipeline.
**Migration plan:** SaaS users → Supabase Storage exclusively. Legacy VPS pipeline → Google Drive (existing). Adapter layer in `supabase_adapter.py` already abstracts storage.

---

## 2026-04-03 — Single agent runner, not two parallel systems

**Decision:** `run-agent.sh` is the ONE runner. It checks PRD tasks (priority) then falls through to task-queue. No separate `run-team.sh`.

**Context:** Two agent systems were built independently: `run-agent.sh` (StoryEngine-specific, cron-driven) and `run-team.sh` (portable, PRD-driven). They didn't share memory, skills, or activity feeds.

**Alternatives:**
1. Keep both systems with a dispatcher — more code, split context
2. Merge into run-agent.sh with priority routing — single system, shared everything

**Why this won:** Two disconnected systems = nobody learns, nothing is shared. One runner with priority routing (PRD > focus directive > task queue > standing orders) keeps everything unified.

## 2026-06-12: Video Clips stage UX contract (Ryan answered 8 design questions)
**Decision:** The clips stage is rebuilt around a trust ladder with these locked choices:
1. **Three-rung granularity:** tap a card = generate that ONE clip (~$0.10); "Animate this scene" per scene group; "Animate everything" appears in the guided banner only AFTER the first scene's clips look good.
2. **"Generate Prompts" button dies:** motion prompts auto-generate silently when the stage is reached (plumbing, cents); failures surface as a banner recovery card.
3. **All clips, always:** every segment gets a motion clip on every video (~$8.60/video at Grok 6s). No stills/clips mix, no format detection for coverage.
4. **Dialogue badge:** dialogue cards show a quiet 💬 + character name; tap behaves identically (system handles lips + ElevenLabs voice automatically).
5. **Voice auto-chain:** tapping a dialogue card whose segment voice doesn't exist yet synthesizes that voice first, then the clip — one tap never dead-ends. Whole-video segment voice still runs as its own silent background step.
6. **Cost confirm >$0.50:** card taps just go; scene/bulk actions get one confirm with the exact dollar amount. Cost math must use the real selected-model price (the hardcoded 86×$0.30=$25.80 was Veo pricing; Grok is $0.10/6s).
7. **Card affordances:** tap plays inline; hover shows Redo ↻ and X (same as storyboard cards); failed cards turn red with Try Again on the card. No explicit approve step.
8. **Tab layout:** one status strip + ⋯ Advanced (model picker, motion system prompt, re-run prompts, skip stage). Generate Prompts / Generate All Clips / Advance Stage buttons all die; the GuidedNextStep banner is the only big CTA.
**Context:** Ryan (screenshot of the clips tab): "clunky… UI/UX needs to be so simple a grandma can hit a button and go… we are not trusting the system yet, so generate one by one by tapping the card." Also found: the model dropdown writes videos.video_model but the backend ignores it (Grok hardcoded) — wiring it is part of this build.
**Why this won:** Matches the standing one-button design bar (2026-06-12 pt 3) and gives an explicit trust-graduation path from $0.10 taps to full-video runs.

## 2026-06-12 (evening): Voice-over is OPTIONAL per video; bird video goes Grok-native
**Decision (Ryan's):** `videos.dialogue_audio` ('voice_over' default | 'grok_native', migration 049, toggle in the clips ⋯ menu). grok_native = no ElevenLabs overlay at all; Grok voices the lines itself, fed the EXACT scripted words (only the sentences covered by that card — lines span cards, see S1.3). The bird video is set to grok_native: the overlay "is actually fucking it up" while Grok's native take (S1.3) "actually looks great."
**Cost of the trade:** no voice lock — the same character can sound different clip to clip (the original reason voice-over was chosen). Accepted for this format; voice_over remains one toggle away.
**Bigger product direction captured with it:** EVERY pipeline element must be obviously skippable in the UI ("sometimes they don't even want to generate images or videos — they might just want the research, video ideas and script"). A keep/skip matrix per video is the next UX build.

## 2026-06-12 (FINAL, supersedes the InfiniteTalk decision below): Dialogue clips = Grok full-scene + loose voice overlay
**Decision (Ryan's):** 💬 cards generate with Grok on the FULL PANEL (speaking prompt: who talks, others react) and the segment's ElevenLabs line is overlaid with a fixed 0.5s lead. Lip-sync is deliberately loose. Portrait cut-ins are REJECTED: "it changed the entire clip from a scene in the animation to a talking head girl."
**The full tour, so nobody re-walks it:** (1) mux at t=0 → voice leads mouth; (2) vision-aligned mux → Claude-via-Kie vision is dead (blind guesses); (3) InfiniteTalk on the panel → animates the most prominent face (Tom mouthed Lisa's line); (4) InfiniteTalk on the portrait → perfect sync, right character, but destroys scene continuity; (5) video lip-RETARGETING (Kling lipsync-on-video) would be the real answer (Grok scene + retargeted mouth) but Kie does not host one — re-probe occasionally.
**Why this won:** scene continuity outranks mouth precision for this format (reference kids' channels are loose too); Grok is fast (~30s) and $0.10; the renderer owns final timing anyway.

## 2026-06-12: Dialogue clips are audio-DRIVEN (InfiniteTalk), not Grok + mux
**Decision:** 💬 cards generate via Kie's `infinitalk/from-audio`: panel image + the segment's ElevenLabs mp3 + a who-speaks prompt → talking clip whose mouth is generated FROM the waveform. The Grok+mux approach (overlay the line on a Grok motion clip, align with vision onset detection) is retired — it missed in both directions across two live rounds because Grok times the performance itself. Narration cards stay Grok motion clips (audio stripped).
**Context:** Ryan: "lip sync is way off... research how people actually do this." Industry standard for character speech is audio-driven talking-video models, not post-hoc alignment.
**Alternatives:** Kling AI Avatar 2.0 on Kie (avatar-centric, up to 5 min — heavier than needed); Veo native speech (no voice lock per the earlier decision); keep polishing vision alignment (±0.5s ceiling from frame granularity, entrance shots unfixable).
**Why this won:** Sync is inherent, not estimated. Verified live on S2.1's full-scene stylized panel: Lisa articulates her line, Tom stays quiet, scene/style fully preserved, output length = audio length. CHEAPER than Grok for dialogue ($0.015/s ≈ $0.04/line vs $0.10/clip + vision). Trade-off: ~7 min generation per clip (vs Grok ~30s) — acceptable for unattended runs.
**Known gap:** multi-line cards lip-sync the FIRST line only (renderer assembles full exchanges later); InfiniteTalk audio cap is 15s/clip.

## 2026-06-12: Dialogue-aware clips — voices, pauses, detection
**Decision:** (1) Dialogue lines are voiced by ELEVENLABS character voices (via Kie), with Grok Imagine providing the on-screen lip movement (its native audio muted/replaced). (2) The narrator PAUSES during dialogue — clean turn-taking timeline, no overlap. (3) Dialogue handling sits behind an INTELLIGENCE layer: a per-video analysis detects whether the script/channel format uses character dialogue at all (dialogue_mode) — narration-only channels are untouched. No manual flags: detection must work unattended for any pasted reference video (north-star: full channel automation).
**Alternatives:** Grok-native dialogue voices (free, perfect lips) — rejected as default: no voice lock, same character can sound different per clip; kept as a per-video experiment option.
**Why this won:** Voice consistency is brand-critical for repeat-viewer channels; ElevenLabs gives each character a stable voice forever while Grok still sells the visual of the character speaking.

## 2026-06-12: All product vision goes through one provider-chained helper
**Decision:** Every call that needs a model to SEE pixels routes through `shared.clients.vision_client.vision_call`: Kie Gemini 2.5 Flash primary (its `prompt_tokens` proves image ingestion per call), Kie Claude gateway fallback, direct Anthropic last. The helper downloads images itself and sends them inline (data URLs / base64) — provider-side URL fetching is banned. Vision is split from generation: the modeled pack's thumbnail is described by a cheap vision pass and injected as TEXT; the tuned Claude generation call never carries an image block. Health is owned by `canaries/vision_drift.py` (hourly user-systemd timer, ntfy alert).
**Alternatives:** (1) Keep Kie Claude vision primary with token-threshold checks — rejected: the gateway re-encodes base64 images to unpredictable sizes (~313 tokens for a 768px PNG), so working and broken states are indistinguishable by tokens. (2) Per-call content assertions — impossible in general (we don't know the image's content at runtime).
**Why this won:** The 2026-06-12 gateway drift was a SILENT failure (HTTP 200, plausible prose, no pixels) that reverted before it could be reproduced. Only a provider whose usage reporting is honest (Gemini) plus a synthetic canary turns that failure mode into a detectable one.

## 2026-06-12 (night): Extraction trusts pixels, not layout math; bad crops get deterministic validation
**Decision:** Panel extraction crops by `detect_panel_rects` (the grid's actual black separator lines: bands of full-width dark rows, then dark columns within each band); uniform rows×cols cropping is only the fallback. Every crop is validated by `panel_flags` — `label_leak` (contiguous near-black chip streak cut by bright glyph strokes in the top rows) and `gutter_split` (≥3 adjacent paper-white >240 or separator-black <35 columns running edge-to-edge through the interior). Leaked chips are TRIMMED off at crop time when that clears the flag; flags persist to `assets.extraction_flags` (migration 050); extraction never INSERTs rows beyond the scene's story slots (orphan guard). One-tap re-crop = `POST /videos/{id}/assets/{aid}/recrop`, which re-cuts the asset's whole beat (a split never comes alone).
**Context:** Ryan's answer 4 (S2.4/S2.5 split, label leaks). Live findings: the image generator drew scene 2 as 3-top/2-wider-bottom — uniform cropping CANNOT cut it; chunking drift had created 12 orphan rows; the validator found 3 leaks nobody reported (S2.3/S4.4/S6.12). Verified live: scene 2 re-cropped 5/5 clean, chips gone, split healed.
**Alternatives:** vision-based QA (rejected: vision drift is a known silent failure; pixel rules are free and deterministic); regenerating flagged boards (costs money and risks good panels — re-crop is free and surgical).
**Why this won:** deterministic, calibrated 15/15 on real panels, heals instead of just flagging, and the unattended north star needs extraction that self-corrects without a human eye.

## 2026-06-12 (night): Speaking prompts carry an OFF-SCREEN speaker rule
**Decision:** Every speaking prompt (native and voice-over) ends with: if the speaker is not visible in the image, the voice comes from off-screen — never add them or any new person; keep the framing exactly as shown. Grok judges visibility from the pixels.
**Context:** S1.4's "invented toddler" was our own direction: the card's sentence carries the tail of Tom's line (sentence-level match_lines), so the native prompt told Tom to SPEAK on a bird close-up where only his sneakers show — Grok obliged by walking him in. Name-substring visibility checks can't fix this ("Tom's sneakers… without face" names Tom).
**Alternatives:** suppress speech on cards where the speaker isn't fully visible (loses the spoken words — that sentence fragment is voiced ONLY by this card in grok_native); re-allocating spanned lines to the speaker-visible card (changes timing, complex). 
**Why this won:** off-screen dialogue over a cutaway is normal film grammar, it's one deterministic sentence in the prompt, and it verified live on the first try (legs stay at frame edge, audio track carries the line).

## 2026-07-17: StoryEngine positioning vs Higgsfield — open BYOK + YouTube-native loop
**Decision:** StoryEngine competes with Higgsfield head-on as the open alternative: user's own API keys at true cost (vs their credit-markup wall), full videos not clips, published to YouTube with CTR/retention feeding back into future creative decisions. The copilot replicates Higgsfield's winning UX (outcome-based model routing, preset-first, agentic co-creation) without their dark patterns (throttled "unlimited", billing traps, rage-bait marketing).
**Context:** Deep-research teardown 2026-07-17 (`docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md`): Higgsfield hit ~$500M ARR in 15 months on multi-model aggregation + camera presets + paid-UGC distribution, but has no timeline editor, no social integrations, and a documented trust deficit.
**Why this won:** Their two structural blind spots map exactly onto our existing strengths (end-to-end pipeline, YouTube publishing + analytics). Their MCP proves agentic co-creation is a growth channel; ours is better-shaped because sessions end in a published video with performance data, not a downloaded clip.

## 2026-07-17: Two doors, one registry (interaction law)
**Decision:** Every user-facing capability ships BOTH a clickable control AND a conversational path (Producer/co-pilot), both calling the same verb in `storyengine/backend/actions.py`. The planned MCP server is the third door on the same registry. A feature with one door is incomplete by definition.
**Context:** The 4-agent audit found ~25 cases of built-but-invisible (40+ camera moves, 5 visual profiles, per-user BYOK) or visible-but-fake (image-model dropdown ignored by the live path, dead registry models). Root cause: layers built without wiring to the layers users touch.
**Alternatives:** chat-first only (breaks discoverability), UI-first only (copilot says "I can't do that" for things buttons do — trust-killer for a co-creation partner).
**Why this won:** The registry already exists and already powers both chat and buttons for ~20 verbs — the law formalizes what the architecture was built for, at near-zero marginal cost.

## 2026-07-17: Copilot routes models by declared outcome, per scene, with visible reasoning
**Decision:** Users declare intent ("hero shot", "b-roll", "keep it under $10"); the router maps scene intent → model via a decision table stored as data (`best_for`/`tier`/`cost`/`wired` per model, served by `GET /api/models`). Every routed choice shows a one-line "why" and a one-tap override. Routing is per-scene (`routed_model`/`routing_reason`/`model_used` columns), not one global video model. "Draft cheap, finish expensive" ships as verbs (draft_pass / finalize on approved scenes), not advice.
**Context:** Higgsfield's core insight — users think in outcomes, not model names; their presets/MCP hide model selection. StoryEngine already classifies scenes (camera purpose REVEAL/ESTABLISH/PAYOFF, scene-planner peaks), so intent tags largely exist.
**Alternatives:** keep global model dropdown (10x cost mistakes, user must learn models); fully hidden auto-routing (black box — breaks trust and the BYOK true-cost story).
**Why this won:** Auto-with-visible-reasoning is the only version consistent with our trust positioning, and per-scene routing is what makes draft/finalize economics possible ($1-2 drafts vs $17+ all-premium).

## 2026-07-17: Cost ledger is truth; estimates are hints; one price source
**Decision:** Every generation writes an actual-cost row (`generation_ledger`: video, stage, model, units, actual cost, kie_task_id) and rolls up `videos.total_cost`. Price constants live in ONE place (model registry / `/api/models`); `actions.py` estimates and all frontend displays derive from it. UI shows "Est → Actual". Frontend copies of price tables are deleted, not synced.
**Context:** Cost counter is wrong today: prices duplicated across `actions.py`, `lib/next-action.ts`, and `MODEL_REGISTRY` (drift), and spend is inferred from artifact counts because no ledger exists.
**Why this won:** BYOK's whole pitch is true cost; a platform that can't state actual spend can't make that pitch. Ledger rows are also the substrate for budget caps and per-preset ROI analytics (P3).

## 2026-07-19 — Power Doctrine + prototype Slack channel are RETIRED (Ryan, direct)
Ryan: "I don't use Power Doctrine anything anymore or the Slack channel — it was the prototype
that got us started." Consequences for the codebase:
- Legacy Power-Doctrine-branded paths are not protecting any live workflow → prefer DELETE over
  preserve-for-cron when they're the only consumer (applied from C34a onward: legacy upload bot).
- The Slack notification channel (C0A9U1X8NSW) is unused → SlackClient becomes no-op/removed for
  SaaS runs (C34b); no per-tenant Slack integration needed.
- Power Doctrine script profiles stay available as OPT-IN voices (C24) — the retirement covers the
  branding/identity as a default and the prototype infra, not the writing style as a choice.
- OPEN (C37, needs Ryan): does retirement extend to the ENTIRE legacy Airtable/cron pipeline
  (autopilot cycle, competitor scraper, approval watcher, healthcheck)? Not assumed — those crons
  still run on the VPS until Ryan says otherwise.

## 2026-07-19 — The endgame is per-tenant AUTOPILOT: "one brain, one director, three doors" (Ryan, direct)
The legacy cron autopilot is NOT retired — it's the single-channel REFERENCE IMPLEMENTATION of the
product's endgame. Ryan's vision, verbatim spirit: a creator builds their channel manually, fine-tunes
with the director until comfortable, then flips ON autopilot — from then on the ENTIRE channel is
data-driven: idea selection, hook/title/thumbnail/script generation, publishing, and a YouTube-metrics
feedback flywheel picking the next video. Controllable/observable through ALL THREE DOORS (UI, chat,
MCP) off the one verb registry. Design law for the port: the autopilot switch is a GRADUATED dial
(propose-only → auto-draft/manual-publish → fully autonomous with a budget ceiling), mirroring the
per-video trust ladder; unattended spend demands the strongest guardrails in the codebase (claims,
skip-if-done, ledger backstop, quota guard, per-tenant budget).

## 2026-07-19 — Phase 4 Pillar 1 is CHANNEL DNA INGESTION ("learn this channel") (Ryan, direct)
Real-world driver: Ryan channel-manages an existing channel (machine-research + Ken-Burns style) and
found no clean way to say "here's a channel — learn it and produce in its exact style." The ingredients
exist scattered (voice-learn transcripts, channel-formula thumbnails, static_docu machine-research
workflow, script templates, reference-video modeling, creator brief) but there is no single
conversational front door that runs all learners, shows a confirmable digest of what was learned, and
saves it as the channel's DNA consumed by every subsequent build. Pillar 1 ships BEFORE Pillar 2
(tenant autopilot): ingestion + autopilot together = "point it at any channel, it learns it, then runs
it" — the ultimate-YouTuber-tool pitch.

## 2026-07-19 — C37 decisions (Ryan, via screenshot of the choice list)
1. **Create-surface convergence: CHAT-PRIMARY.** The producer chat plan is THE way to create a
   video; the New Video form stays as the power-user door; the other entry points (Model A Video,
   onboarding create step, FirstVideoFlow) become thin wrappers routing into those two. → build
   chunk C38.
2. **BYOK is a COMMERCIAL PILLAR, verbatim intent:** "I'm not paying for people's generations —
   I just want a subscription and then they pay for what they use." The platform NEVER subsidizes
   generation costs; tenants bring their own keys (already the live model). Orchestrator's
   interpretation of the per-USER flag question: for solo creators tenant-key == user-key, so
   `PER_USER_KEYS_ENABLED` stays deferred until multi-seat teams exist — the pillar is satisfied
   at the tenant level today. (Flagged for Ryan to correct if he meant per-seat keys NOW.)
3. **Multi-shot "Lost Wind Chime" sequences: PARKED.** Ryan: "Lost Wind Chime wasn't even supposed
   to make it here — it was an attempt on my Hermes agent." Not a committed product feature;
   stays in the roadmap ideas list only (A1), no build priority.
4. **/storyboards orphan page: DELETE — but the storyboard CREATION PROCESS is sacred.** Ryan:
   "We don't need a separate page for storyboards but I want to make sure we keep storyboard
   creation process as it's a key step." Delete only the unreachable standalone page + stale doc
   entries; the storyboard pipeline stage and the in-page Storyboard tab are untouched. → micro
   chunk C39.
5. Deploy timing: not yet answered — remains open.

## 2026-07-19 — C40 Channel DNA provenance envelope: Python read-modify-write, not SQL merge (worker, implementation-level)

**Decision:** `channel_dna_meta.stamp_identity_write()` fetches the CURRENT `channel_identity` JSONB,
merges in Python, and writes back a plain `channel_identity = $N::jsonb` replace — not a SQL-side
`jsonb_set`/`||` merge. Two of the three pre-existing writers (`channel_format.set_channel_format`,
`pipeline_executor`'s thumbnail_blueprint cache) used to do the merge atomically in SQL
(`COALESCE(...) || $2::jsonb`); the third (`identity_builder.build_channel_identity`) did a blind
overwrite. All three now go through the same read-then-merge-then-write shape.

**Context:** The provenance envelope needs dict-of-dicts merging (`_sources`) and bounded-array
append-with-eviction (`_history`, cap 20) — both awkward/unreadable in raw `jsonb_set` SQL, trivial
in Python, and this is where all the unit-testable logic (stamp/provenance/restore) needs to live
for C40's `[V]` (non-vacuous tests, no live DB). The tradeoff: a fetch-then-write pair is not atomic,
so two concurrent writers on the same tenant could race (last write wins for whichever field the
loser touched) — a narrower window than before for channel_format/thumbnail_blueprint (previously
atomic), unchanged for identity_builder (was never atomic-safe against other writers to begin with,
since it blind-overwrote regardless).

**Alternatives considered:** (1) Keep SQL-side merges and bolt provenance on via nested
`jsonb_set(jsonb_set(...))` calls — rejected, unreadable and untestable without a live DB. (2)
`SELECT ... FOR UPDATE` row lock around the fetch+write — rejected as scope creep for a `[D]` "no
migration expected, JSONB shape change only" chunk; these three writers are low-frequency
(identity rebuild is an explicit chat action, format lock is a one-time chat edit, thumbnail cache
writes once and then short-circuits on cache hit), so the race window is real but low-odds and not
worth new locking infra here.

**Why this won:** Matches the checklist's own "simplicity-first, reversible" framing for the
envelope choice itself; keeps 100% of the provenance logic pure-Python and unit-testable per `[V]`;
if concurrent-write races on this column become a real problem later (e.g. once C41's ingestion
orchestrator can run multiple learners writing distinct fields close together), the fix is additive
(a row lock or an advisory lock keyed on tenant_id) — flagging for whoever builds C41+ to watch, not
blocking this chunk on it.

## 2026-07-19 — C41 channel-level claim: extend `generation_claims` (nullable video_id + second partial
index), not a parallel table (worker, implementation-level)

**Decision:** `channel_dna.py::learn_channel`'s concurrency guard reuses the SAME `generation_claims`
table C16a built, via two additions rather than a new table: migration 104 drops `video_id`'s `NOT
NULL` and adds `CREATE UNIQUE INDEX ... ON generation_claims (tenant_id, stage) WHERE video_id IS
NULL`; `generation_claims.py` gets `acquire_channel()`/`release_channel()`, video-less siblings of
`acquire()`/`release()` that always write/read `video_id = NULL` rows through the new index. Every
existing per-video call site (`acquire`/`release`/`is_blocked`, their SQL, their money-safety
guarantees) is untouched — proven by their own test file passing unmodified after this change.

**Context:** `learn_channel` doesn't operate on a single video (it rebuilds tenant-wide
`channel_profiles.channel_identity`), so the existing `(tenant_id, video_id, stage)` claim key has
nothing to key on. The ORIGINAL unique index never fires for a `video_id IS NULL` row (Postgres
treats NULLs as pairwise distinct in a plain unique index) — so without the second partial index, two
concurrent channel-level claims for the same tenant+stage could both `INSERT` and neither would be
denied. This is exactly the race C40's note above flagged as future work "once C41's ingestion
orchestrator can run."

**Alternatives considered:** (1) A brand-new `channel_claims` table mirroring the same shape —
rejected: two claim tables split the "is this tenant/video busy" answer across two lookups forever,
and the checklist explicitly said "reuse generation_claims." (2) Fake a `video_id` by pointing at some
sentinel row — rejected: either requires a real (and misleading) `videos` row to satisfy the FK, or a
magic UUID constant that every future per-video query would need to know to exclude; nullable + a
second index is the standard Postgres pattern for "sometimes this FK doesn't apply" and needed no
schema-wide awareness elsewhere.

**Why this won:** Additive on both sides (nullable column can't retroactively null an existing row;
the new index only ever matches NULL rows the old index never matched) — zero risk to the S7-1
CRITICAL video-scoped guarantee, confirmed by running `generation_claims`' own test file after the
migration. Same acquire/release/stale-sweep/fail-closed discipline as the proven video-scoped code,
just re-keyed on `(tenant_id, stage)` instead of `(tenant_id, video_id, stage)`.

## 2026-07-19 — C46 APPROVED with an ADDITIVITY constraint + the MCP-as-setup-brain insight (Ryan, direct)
Ryan: yes to C46 (script quality-rules engine), with: "I want to make sure what we're doing is ADDING
to the enhancement — I have done many extensive sessions trying to dial in the script and the research
steps. I have done it all through Claude sessions, not through the platform." Constraints and insight:
1. **C46 must AUDIT-THEN-ABSORB the prior dial-in work before building anything**: the DvsU
   PLAN→WRITE→EDIT writer restructure (git history, "5/23 pass" checklist state), existing script/
   research tuning artifacts in-repo (script profiles, tenant_prompt_defaults, script_system_prompt,
   script_templates, machine-research prompts, GOAL.md/HANDOFF.md at storyengine root), and treat them
   as the FOUNDATION the rules engine formalizes — never a parallel path that ignores hard-won tuning.
2. **MCP is the setup brain**: the dial-in itself happened in Claude sessions because Claude-level
   intelligence is the right tool for CONFIGURATION, not just production. Product implication: the MCP
   surface should expose the SETUP layer (system prompts, script templates, quality rules, channel DNA
   read/corrections) so anyone can configure their StoryEngine channel from Claude/any agent without
   ever using the StoryEngine door — "use Claude to set up StoryEngine" is a first-class path. → C47.
