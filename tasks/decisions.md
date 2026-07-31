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

## 2026-07-19 — MCP economics: the connected Claude DOES the thinking stages (Ryan, direct)
Ryan: "The benefit of using the MCP is that we can probably do the research, the scripting with a
Claude subscription. Then it follows the pipeline for video and image gen, render, upload etc."
Architectural implication for C47: beyond setup tools, the MCP surface needs CONTENT-INGEST tools —
the connected agent (running on the user's flat-rate Claude subscription) performs research and
scriptwriting ITSELF and submits the results, which StoryEngine accepts through the SAME validated
store+advance paths run_research/run_script use (validation, machine-research-card shape, status
advance) — then the paid media pipeline (images/clips/voice/render/upload, BYOK Kie/ElevenLabs)
takes over. Cost story per video shifts from "all stages on API keys" to "media-only on API keys,
thinking on the subscription." Synergy with C46: agent-authored scripts pass through the SAME
quality-rules critic as platform-generated ones — the rules engine is the trust boundary that makes
externally-written content safe to accept. This is also just the structured version of what Ryan
already does manually in Claude sessions today.

## 2026-07-19 — DvsU open rulings RULED by Ryan (OR-5/6/9)
- **OR-5: RULED — follow the recommendation.** "Most Hated" (pilot-testimony format) becomes a
  SEPARATE NAMED DvsU mode with its own rule overrides (opener budget, memorable-fact source),
  never folded into the spec-block default. Unblocks D7 (number normalization pending OR-5).
- **OR-6: RULED — recommendation REJECTED, capability accepted.** Do NOT blackball
  MostHated-Warships (or any style): "it might work for another channel or niche." Build the
  CAPABILITY to tag a video/style as an anti-pattern excluded from style-seed/few-shot sets —
  PER-CHANNEL, opt-in, nothing tagged by default. A style is only weak in a context.
- **OR-9: RULED — follow the recommendation.** Five thumbnail phrases stay locked; "BY PILOTS"/
  "BY CREWS" (and any future phrase) promote to the locked set only after proving out as a series;
  everything else under the open 2-4-word rule. (Verify QL-66's current code already matches — it
  should; if so, no code change.)

## 2026-07-19 — OR-6 EXPANDED into a design principle: anti-patterns are DATA-DERIVED, per-channel, never hardcoded (Ryan, direct)
Ryan: patterns are "developed on a channel only after the channel is actually running and has data...
this pattern might work well for another channel so that shouldn't be a blanket pattern... the system
must remain as flexible as possible — proper tagging happens per channel based on the data we see in
the YouTube analytics, not a hardcoded system." Design law for C46e item 2 (and the future P4.2 loop):
- Anti-pattern (and positive-pattern) tags are PROPOSED FROM THE CHANNEL'S OWN ANALYTICS (the C30
  by-style aggregates / C33 VPH / CTR-retention data), each proposal carrying its evidence
  ("openers of this shape underperform your channel median by X% across N videos").
- Human CONFIRMS before any tag takes effect; tags are per-channel rows, reversible (soft-off),
  and NEVER copied across channels or baked into code/prompts as universal truths.
- The exclusion mechanism (keep a tagged pattern out of style-seed/few-shot sets) is generic
  capability; WHICH patterns get tagged is always that channel's data + that creator's confirmation.

## 2026-07-19 — Pattern learning has TWO convergent entry points (Ryan, direct — the import caveat)
Ryan: an imported channel arrives WITH YouTube analytics/history — "we will need to analyze the
analytics and the patterns when we import a channel for those patterns to create a rule for that
channel"; a ground-up channel learns "with every new video that launches"; and after import both
apply — "we will obviously be launching new videos, so those videos will also teach the system.
New patterns as the channel grows with our platform." Design law:
- ONE per-channel pattern store, ONE evidence+confirm flow (per the OR-6 expansion), TWO triggers:
  (a) IMPORT-TIME bulk analysis — part of the P4.1 learn_channel ingestion: analyze the imported
  channel_videos' analytics history and PROPOSE the channel's initial patterns in the DNA digest;
  (b) PER-LAUNCH incremental — each new platform-published video's analytics feed ongoing proposals
  (the P4.2 flywheel's job).
- Imported baseline + incremental learning COMPOSE: patterns keep evolving post-import; nothing is
  frozen at import day; confirmed rules can be superseded by newer evidence (proposal to retire a
  pattern is also evidence-backed + confirmed).

## 2026-07-19 — "Model this video" is the MCP's flagship workflow (Ryan, direct)
Ryan: "give it a video and ask it to model this video where it will give me new title ideas based on
looking at a channel's top 3 videos. Then be able to clone the video style but with my own twist. I
should be able to in plain English work with Claude to custom craft any video style I want at any
length as long as I am willing to pay for it. It will be smart enough to know the pathways and help
me decide in a Claude chat and craft anything or style I want." Design law for C48/C49:
- The MCP surface's job is not just atomic tools — it must support the MODELING workflow end-to-end:
  reference video in → analyze it + the channel's top performers → title ideas grounded in that data
  → a style-clone profile the user can TWIST in plain English → walkthrough creation with boards in
  steps → normal quote+confirm on every paid step, any length, any wired model.
- REUSE, don't rebuild: the ingredients exist — routes/niche.py's Model-A-Video metadata pull,
  competitor_videos top-performer data, title_idea/idea_modeling.py + curiosity_gap, Channel DNA
  (learn_channel) for style capture, style/script profiles + director_preferences for the "twist".
  C48/C49 wire these into MCP-reachable pathways; the intelligence layer is the connected Claude
  session itself (on the user's subscription — the MCP-economics decision), guided by a §C29
  runbook recipe ("model a video") so Claude knows the pathway.
- "Smart enough to know the pathways" = the runbook recipes + tool descriptions carry the pathway
  knowledge; no new server-side orchestrator LLM for this.

## 2026-07-19 — MCP monetization: the agent token IS the paywall; flat subscription over per-token billing (Ryan + orchestrator design)
Ryan: "I don't wanna give this away for free via the MCP... Higgsfield charges per token and MCP runs
through their platform, but we flipped it on its head where it's a bring-your-own-keys model. So they
need to access our platform, save their keys, and then they could use it."
Design ruling:
- BYOK inverts Higgsfield's economics: their per-token metering exists because generation runs on
  THEIR keys. Ours runs on the customer's keys (media) + customer's Claude subscription
  (intelligence), so marginal cost ≈ 0 → FLAT SUBSCRIPTION is the right model. The product being
  sold is the machine (pipeline, Channel DNA, quality engine, autopilot, orchestration, storage),
  not tokens.
- Enforcement seams (all already exist, all server-side — every MCP tool call hits OUR backend):
  (1) token MINT requires an account with active subscription; (2) token VERIFY (auth_agent
  dependency, per-request DB lookup already) also checks tenant subscription status — lapsed
  subscription kills existing tokens same-day with a renew-here error message; (3) optional tier
  limits live in actions.py (the ONE verb registry all three doors — UI/chat/MCP — funnel through),
  never per-door. Recommendation: MCP access is a Pro-tier feature (power-user upsell).
- NO per-token/per-call billing machinery. We do not meter what we do not pay for.
- Build order: (a) entitlement seam NOW, dark — `subscription_status` per tenant defaulting
  'active' (zero behavior change) + checks at the three seams; (b) Stripe checkout/webhooks LATER,
  after Ryan picks pricing/tiers/trial at the computer (his decisions, not built ahead).
- Honest caveat recorded: BYOK means the API calls aren't the moat — the accumulated per-channel
  intelligence (DNA, rules, patterns, analytics flywheel) in our DB is. Retention story: cancel and
  the channel's brain goes dormant.

## 2026-07-19 — CORRECTION to the MCP-monetization entry above: Stripe ALREADY EXISTS (Ryan caught it)
Ryan: "Really are you sure? I hooked the Stripe account up a while ago." Verified by repo search —
the orchestrator's "no billing system exists" claim was WRONG. What actually exists:
`routes/billing.py` (527 lines: checkout, webhooks w/ signature lock, portal, usage), `accounts`
columns stripe_customer_id/stripe_subscription_id/stripe_plan/stripe_status (migration 022), plans
starter/pro/agency via STRIPE_PRICE_* env vars, trial handling (migrations 026/041), and
`check_plan_limits(tenant_id, action)` — a 402-raising gate regression-locked by functional tests
on the video-create + render routes. Frontend /billing + /pricing pages exist.
REVISED build order (supersedes "(a) entitlement seam / (b) Stripe later"):
- C57 is now a WIRING chunk, not a build chunk: hook the MCP surface into the EXISTING system —
  (1) agent-token mint requires an account in good standing (reuse the same status/trial logic
  billing.py already encodes — read it, don't re-derive); (2) `auth_agent.py` per-request verify
  consults the same standing check (lapsed → 402-style renew message, existing tokens die
  same-day); (3) IF MCP is tier-gated, it's a new action kind in `check_plan_limits` ("mcp") —
  the one existing gate, not a parallel one.
- AUDIT REQUIRED in C57: do MCP-originated create/render paths (create_video tool → actions.py →
  executor) pass through `check_plan_limits` like the 3 locked UI routes do, or do they bypass it?
  The lock tests only cover the UI routes — an MCP bypass would let a free-plan tenant exceed caps
  via Claude. Whatever's found, the fix is calling the SAME gate.
- Ryan's remaining decisions shrink to: which tier gets MCP (recommend pro+agency), and whether
  plan-limit numbers change. Checkout/portal/webhooks need nothing new.

## 2026-07-20 — MCP channel-manager direction (Ryan): multi-channel drivable from one Claude chat; signup stays in browser; UI = confirmation surface
Ryan: "Can I sign up via the MCP and have access via a channel manager?... have Claude set everything
up via the MCP but I have the user interface for double triple confirmation. Many people will want to
use the system to run multiple channels."
Rulings/facts:
- Signup + Stripe checkout stay BROWSER-ONLY by design — that flow IS the paywall (C57: agent tokens
  mint only from a paid, logged-in account). One-time minutes; everything after is MCP-drivable.
- UI-as-confirmation is already structural: every MCP setup tool writes the same DB the UI reads.
  Keep it that way — never add MCP-only state invisible to the UI.
- Economics clarified for the record: chat-Claude intelligence = user's Claude subscription;
  backend-internal Claude calls (script/research stages, BYOK tools) = tenant's API key;
  submit_research/submit_script let power users keep thinking-work on subscription.
- GAP (verified in code): `projects` table = one row per channel, many per account — but the MCP
  surface is single-channel-implicit (no list/create/select channel tools, no channel scope param).
  → C61 queued: channel-manager MCP surface, additive scoping.

## 2026-07-20 — C61 STOPPED at trace: "channel identity" is fragmented across 3 incompatible layers, not just `projects` vs `channel_profiles` — needs Ryan's ruling before any MCP scoping is built
Per the chunk's own STOP clause ("if the trace shows projects/channel_profiles duality is
genuinely unresolved... STOP after the trace"). The trace found the duality is real AND worse
than the entry above assumed — it's not two tables, it's three tiers of scoping that don't line up:

1. **`projects`** (schema allows many-per-tenant, `videos.project_id` FK exists) — but ZERO code
   path anywhere (backend or frontend) ever creates or selects a second row. Every single read site
   is `_get_or_create_project()` / `SELECT ... FROM projects WHERE tenant_id = $1 LIMIT 1`
   (`routes/projects.py`, `routes/characters.py`, `routes/discovery.py`, `routes/videos.py`,
   `identity.py`, `pipeline_executor.py`, `channel_profile_documents.py`). The frontend only ever
   calls `/api/projects/current` (`frontend/src/lib/api.ts` — no switcher, no list view, no create
   button). `routes/projects.py`'s own docstring: "The UI currently shows only the first project."
   So `projects` is schema-multi, practice-singular — there is no existing "create a second channel"
   seam to wrap for `create_channel`, and a `list_channels` MCP tool would enumerate rows the UI has
   no way to view/select, which is exactly the "MCP-only state invisible to the UI" the governing
   decision above rules out.
2. **`channel_profiles`** — DB-enforced single row per tenant (`tenant_id UUID ... UNIQUE NOT NULL`).
   This is NOT dead legacy: it's the LIVE store for channel identity DNA (`channel_identity` —
   `channel_dna.py`, `channel_format.py`, `identity.py`, `identity_builder.py`), creator brief,
   channel_intel, onboarding state, style_description, and BOTH OAuth connections (YouTube
   `youtube_refresh_token`/`youtube_channel_id`, Google Drive `google_drive_refresh_token`) —
   touched by ~20 backend files (`routes/chat.py`, `routes/onboarding.py`, `routes/google_auth.py`,
   `routes/youtube_channel.py`, `routes/youtube_sync.py`, `routes/dashboard.py`,
   `routes/system_prompts.py`, `routes/analytics.py`, `pipeline_executor.py`, `youtube_publish.py`,
   `static_docu.py`, `main.py`, ...). It has NO `project_id` column and its UNIQUE constraint makes
   a second row per tenant impossible without a migration + a real decision about which existing
   column set (name/niche/target_audience overlaps `projects`; OAuth tokens/DNA/onboarding do not)
   moves where.
3. **Tenant-only, no project_id at all, ever** (checked schema.sql directly): `autopilot_config`
   (`tenant_id UNIQUE NOT NULL` — hard single-row, same as channel_profiles), `quality_rules`,
   `channel_patterns`, `autopilot_proposals`, `learnings`, `content_intelligence`,
   `discovery_ideas`, `competitor_channels`/`competitor_videos`. Confirmed at the Python layer too —
   `channel_dna.py`, `quality_rules.py`, `autopilot_dial.py` all take `tenant_id` as their only scope
   arg, no `project_id`/`channel_id` parameter exists to thread through.

Net: of the chunk's named tool families, only `create_video` has a real, live, already-wired
per-channel column (`videos.project_id`) to attach an optional scope arg to. DNA/learn_channel,
quality rules, channel patterns, and autopilot dial/proposals are ALL genuinely tenant-level today
— adding a `channel_id` param to those MCP tools would either be silently ignored (no-op) or require
restructuring tenant-scoped tables into channel-scoped ones, which the chunk explicitly forbids
("do NOT restructure... report the boundary honestly"). Analytics reads split: `channel_videos`
(→ `routes/analytics.py::get_channel_videos`) is tenant-only like the above; nothing there is
project-scoped either.

**Why this blocks tool-building, not just "ship what's scopable":** `list_channels`/`create_channel`
need a real multi-project UI seam to wrap (there isn't one) and a place for a second project's DNA/
OAuth/quality-rules/patterns to live (there isn't one — they're pinned to the tenant, not the
project). Building `list_channels`/`create_channel`/`get_channel` over `projects` alone, with every
other tool family staying tenant-scoped, would produce a channel manager where "channels" are cosmetic
containers (name/niche/visual style/cast only) while the DNA, YouTube connection, Drive connection,
quality rules, patterns, and autopilot dial all keep silently applying to whichever channel happens
to be the tenant's implicit first `projects` row — i.e. the "run multiple channels" product promise
would not actually hold, and the UI (which only ever shows the first project) would have no way to
reveal that gap to the user. That is a product/architecture ruling, not an additive-scoping exercise.

**Parked for Ryan (no code changed this chunk):**
- Does "multiple channels" require promoting `channel_profiles`'s columns (DNA, OAuth, onboarding)
  onto `projects` (a real migration + data move + every one of those ~20 files repointed), or is
  "multiple channels" instead meant as multiple `videos.project_id` buckets under ONE shared
  DNA/OAuth/autopilot identity (i.e. sub-brands of one channel, not independent channels)? These are
  different products and change which tables the MCP tools should even target.
- If the former: `autopilot_config`/`quality_rules`/`channel_patterns` need `project_id` columns +
  migrations + every reader/writer updated (`autopilot_dial.py`, `quality_rules.py`,
  `channel_dna.py`, the autopilot loop in `main.py`) — a multi-chunk build, not C61-sized.
- If the latter: C61 shrinks to just `create_video`'s optional `project_id` (already wired end to
  end) plus a real "create a second project" UI seam (currently missing) before any MCP
  `create_channel` tool can wrap it — still needs the UI seam built first, since "no MCP-only state"
  forbids shipping the MCP tool ahead of it.
- Either way: `channel_profiles`'s UNIQUE(tenant_id) constraint and `autopilot_config`'s
  UNIQUE(tenant_id) constraint are the literal DB-level blockers — no tool-layer scoping can route
  around a UNIQUE index.

C61 checklist bullet left UNCHECKED. Next step is Ryan's ruling, not another trace pass — the code
was read closely enough this session to be confident the gap is structural, not a search-harder
problem.

## 2026-07-20 — C61 RULING (Ryan): Option A — ONE WORKSPACE = ONE CHANNEL
Ryan: "Option A one workspace = one channel. Exactly."
Consequences (append-only law):
- A channel IS a tenant/workspace. Everything already per-tenant (DNA, OAuth, quality rules,
  patterns, autopilot dial/budget/kill-switch, proposals) is therefore already per-channel —
  NO migration, no restructuring, the C50-C56 arc was channel-scoped all along.
- Multi-channel users = one human in multiple workspaces (memberships already supports this).
  The Claude-side channel manager = one MCP connector per channel (one agent token per
  workspace) — tool calls are unambiguous, isolation is total, and the paywall stays per-channel
  (a pricing lever: each channel workspace is its own subscription seat).
- `projects` multi-row ambition is DEAD for channel identity — a tenant's single project row is
  channel-local config only. Do not build multi-project UI/tools.
- C61 rescoped to: (a) document the one-connector-per-channel pattern (runbook); (b) a cheap
  `get_workspace_info`/whoami MCP read so Claude always knows WHICH channel a connector speaks
  for; (c) TRACE (report, decide later): can a user create a SECOND workspace today (UI/signup
  flow, account/tenant/Stripe relationship), or is that the one missing build?

## 2026-07-20 — PRICING RATIFIED (Ryan): ladder + Starter caps locked
Ryan: "I like those metrics you came up with I think they are fair. For the starter I think we
should cap the video length at 10 min with a max video generation at 12? The other tiers get full
unlock unlimited video generation qty and unlimited uploads."
Locked (supersedes the proposal doc's open items 1/3/5):
- Ladder ratified: Starter $29 / Pro $79 / Agency $199 (+$49/mo per extra channel workspace),
  ~20% annual discount, per docs/pricing-proposal-2026-07.md.
- STARTER caps: max VIDEO LENGTH 10 minutes; max 12 video generations per month.
- PRO + AGENCY: unlimited video generation quantity, unlimited uploads (fair-use language on
  the pricing page; no hard meter).
- MCP access = Pro + Agency (ratified with the table; fills the parked C37 OPEN item 6 —
  wire into the C57 seam in create_token).
Still open (small): trial length (14d proposed), Agency-full-auto-requires-cap (code already
enforces via C54b regardless).

## 2026-07-20 — Feature board (Ryan): Reddit-like "suggest a feature" + upvotes = product self-improvement loop
Ryan: "a Reddit like page on the platform that says suggest a feature... upvoted if more people
want that feature... part of the platform self improvement loop where we take in real customer
wants and make it a reality as beta features. Like maybe someone who is a YouTuber who does
talking head videos and explainers... just wants access to the autopilot."
Rulings/design:
- Build as C65. Core loop: suggest → upvote (one vote per account per idea) → STATUS LADDER
  (under_review → planned → building → in_beta → shipped / declined) → beta flag for voters
  first (reuse the existing per-tenant feature-flag pattern). The ladder is the product; votes
  are the sensor.
- FIRST deliberately CROSS-TENANT surface in the platform: the board is shared. Its tables are
  explicitly non-tenant-scoped (votes/authorship attributed per account) — do NOT copy the
  tenant-isolation idiom blindly; display of customer text to other customers needs escaping/
  moderation care.
- Submission carries an optional "what kind of channel do you run?" archetype field — the board
  doubles as market-segment discovery (the talking-head/explainer example).
- Optional MCP tool suggest_feature/list_feature_requests so customers can file from Claude.
- Also 2026-07-20: C64 ffmpeg render spike PARKED ("we'll cross that bridge as it comes") —
  stays queued, unbuilt; render capacity plan lives in docs/pricing-proposal-2026-07.md notes.

## 2026-07-20 — Z-Image → GPT Image 2 fallback for reference-based draws is CORRECT (Ryan, direct)
Ryan: "z image doesnt have an image to image and falls back to gpt2 image which is fine and is
correct." Z-Image is text-to-image only; any draw that needs reference images (storyboard sheets
with cast/location refs, image-to-image redraws) legitimately routes to GPT Image 2 image-to-image
even when the tenant's PICTURES override is z-image. Do NOT "fix" this fallback. The 2026-07-20
storyboard failures were NOT the routing: (a) the z-image createTask error was eaten by the
present-but-null `.get("data", {})` crash (C25a-fix4 hardened every Kie client parse site), and
(b) GPT i2i rejected the media-proxy input_urls because they lack a file extension — Kie model
validators want a recognizable file type (same family as the InfiniteTalk fix 10d232e5;
C25a-fix5 adds the .png suffix in _kie_fetchable_url).

## 2026-07-20 — THE THREE MODELS (Ryan, direct): Grok cheap clips, Seedance premium clips, GPT Image 2 all images
Ryan: "forget all the others right now besides our 3 main models. Grok Imagine, GPT image 2, and
seed dance. I wont use anything else, seed dance for expensive, grok for cheap, gpt image 2 always."
Consequences: Veo (Fast worked/$0.30 confirmed; Quality can't take reference images at all) and
Z-Image (1,000-char documented prompt cap) are OUT of the working set — deprioritize their fixes,
gate them out of pickers in a future chunk rather than fixing their edge cases. The build effort
goes to: (1) Seedance payload fix (Kie: reference image and first/last frames are mutually
exclusive — our client sends both; also requested 9:16 on a 16:9 video), (2) GPT Image 2 sheet
draws must work (the 2026-07-20 400s are NOT prompt length — June sheets at 11-13k chars drew
fine, docs allow 20k; leading suspect is the 3rd reference image added by the LOCKED LOCATION
env-ref feature), (3) ledger/pricing stays exactly as proven today ($0.09 Grok / $0.05 GPT i2i
confirmed against Kie credit billing).

## 2026-07-20 — NO nano-banana fallback for storyboard sheets (Ryan, direct): fix the PROMPT STRUCTURE
Ryan: "i dont want nano bannana at all... fix the damn prompting structure, stop putting bandaids on
everything." Ruling: sheets are GPT Image 2 only; filter rejections are fixed by restructuring the
sheet-prompt builder, never by silently swapping the model. Root cause of body-level rejections:
the builder repeats blade-nouns (knife/chef's knife/chopping/cortar) across FIXED SET + CAMERA KIT +
every panel brief — accumulated density trips OpenAI's filter (sheet 1 passed at lower density with
identical caption content). Structural fix: name risky props ONCE in the set block, neutral references
elsewhere, deterministic neutral-phrasing pass over builder-authored text only — CAPTIONS (the spoken
script) stay verbatim, always. Every wording change pre-flighted against the real filter before deploy.

## 2026-07-21 — MCP co-pilot must be PROCESS-AWARE (Ryan, from live driving): no more skipped steps
Ryan: "I need the mcp to know each and every step of the generation process, there were several
processes that were skipped today, like environment design, and knowing if there are characters
there or not... surface the images in the chat and then handle all the image prompting and video
prompting and storyboard prompting... it should be my co pilot to keep me on track."
Root cause: the MCP exposes ~60 atomic tools but NO canonical process map — the driving agent
improvises stage order from tool names, so silent stages (environment design, character-presence
checks) get skipped. Rulings:
- C66 queued: process brain — (a) MCP initialize response carries SERVER INSTRUCTIONS teaching
  the canonical per-format stage order + house rules (every session starts process-aware);
  (b) `get_production_guide(video_id)` tool: full stage checklist for THAT video's format with
  per-stage done/missing/gaps (characters present? sheets built? environments designed? boards
  drawn? voice? clips? sound? thumbnail?), next-step recommendation — read off the SAME status
  machine the UI uses, no parallel logic; (c) environments MCP tool family (the named skipped
  step) wrapping routes/environments.py.
- C48 UNBLOCKED (C25a confirmed merged into main by Ryan's coordinated deploy, verified via
  git merge-base 2026-07-21) — media-bearing tools ship per its existing spec.
- New verified baseline post-deploy-merge: 2074P/15F/1E.

## 2026-07-24 — Custom Film uses Remotion as an internal finishing engine

- Remotion is not a fifth public profile and not a provider. It consumes the immutable
  approved Custom Film section/media/audio/caption contract and returns its output through
  the existing StoryEngine artifact verification, storage, and readback boundary.
- FFmpeg remains the production default and safe fallback. Once a Remotion assembly identity
  is journaled, it cannot silently switch engines; selecting another engine requires a fresh
  approved identity.
- Full showcase acceptance is creative-first. Exact duration, probe, manifest identity, source
  frame/audio determinism, and artifact hashes remain enforced or reported, while byte-identical
  delivery MP4s are a secondary diagnostic.
- A real flagship run requires a refreshed exact BYOK quote <= $15 and Ryan's explicit approval.
  Push, migration, deploy, upload, and public release are separate gates.

## 2026-07-24 — Keep the Sound feature, guard the spend, don't wire SFX into the modern render paths (yet)

**Decision:** Sound design/effects generation stays in the product, but is now refused (400,
with the human-readable reason) for any video whose render path discards `assets.sound_effect_url`
— Custom Film, `static_docu`, Grok-native dialogue, and character-dialogue performance rendering.
We did NOT delete the Sound stage, and we did NOT wire SFX playback into those four render paths
this session.

**Context:** `assets.sound_effect_url` is only ever consumed by the legacy Remotion fallback render
path (`skills/video-pipeline/render/run.py` → `upload/run_package.py:93-100` →
`remotion-video/.../Scene.tsx:176`). The other four render paths silently dropped it — sound
design/effects spend (~$0.05/effect via Kie.ai ElevenLabs Sound Effect V2) on those videos bought
nothing. Verified live against prod (`se db`, 2026-07-24): `SELECT count(*) FROM assets WHERE
sound_effect_url IS NOT NULL` → **0**, out of 833 total `assets` rows — nobody has ever actually
generated a sound effect on this platform yet, on any render path. Zero production usage to
preserve, and zero videos retroactively broken by adding the guard.

**Alternatives considered:**
1. Delete the Sound stage entirely — rejected. Ryan confirmed he may want it wired into the modern
   render paths later; deleting it would mean rebuilding the prompts/generation/ledger plumbing
   from scratch instead of just adding a mixing step.
2. Wire SFX into `render_perform` (the modern/Custom-Film-style render path) now — rejected for
   THIS session, deferred as demand-driven work. `render_perform`'s audio mix uses `amix` with
   `normalize=0` and no per-source volume control; SFX would need a per-source gain field added to
   the placements tuple to avoid drowning out dialogue/narration, which is a real (if contained)
   schema + mixing change, not a guard.
3. Guard the spend at every call site individually — this is what a3453902 did first; superseded by
   9d83c621 which moved the check into `run_sound_prompts`/`run_sound_effects` themselves (see
   tasks/lessons.md 2026-07-24 "guarding N call sites invites an N+1th").

**Why this won:** Zero production usage on the blocked paths means nothing breaks by refusing the
spend today, and keeping the feature (rather than deleting it) means the eventual "wire SFX into
the modern render paths" work is additive, not a rebuild. The guard buys time without burning the
option.

## 2026-07-25 — Custom Film profiles are shot techniques; the film bible owns identity

**Decision:** DVsU documentary coverage, Poco dialogue, Power Doctrine exposition, and
cinematic silent action may be selected per shot, but none may change the film's medium,
style, characters, environments, props, geography, timeline, or story state. Those are
owned by one immutable film bible and injected into every storyboard, picture, and motion
prompt.

**Why:** The failed five-minute Custom Film treated profile choices as independent visual
systems, which produced realistic and animated style drift, unlocked characters, unclear
progression, narration in place of performance, and no reliable storyboard contract. A
film-level law lets the director choose the right communication technique without losing
the audience's understanding of who, where, when, and what changed.

**Consequence:** Reference images must be approved before storyboards; storyboards before
final media; start/middle/end clip verification before Remotion. A changed film bible,
shot contract, reference gate, or storyboard gate invalidates downstream authority. The
old $8.57 ceiling is not permission for a new stage.

## 2026-07-25 — Custom Film director activation is a staged replacement, not a legacy-runtime patch

**Decision:** The new director loop will first persist a no-provider plan/video identity,
then require an exact cumulative approval for the script/director pass before any text
client call. References, storyboards, final pictures, animation plus every voice line,
verification repair, and deterministic Remotion assembly each advance from the prior
accepted gate through their own immutable schedule. The existing all-at-once approval
must not dispatch a director film into the legacy section-summary runtime.

**Why:** A complete film bible and storyboard plan cannot be safely generated after the
old runtime has already started buying pictures. Conversely, generating that plan before
approval would itself hide provider work. The staged reservation removes the
chicken-and-egg problem and makes helper work, retries, and cumulative spend explicit.

**Consequence:** The current local compiler/gates/composition remain inactive until the
new reservation, chat approval, executor, and renderer adapter are wired together. This
is intentional fail-closed scope, not permission to resume under the historical $8.57.

## 2026-07-25 — Director activation never guesses price or plans before consent

**Decision:** New director-mode intake is deterministic and provider-free. It creates a
full-film planning scaffold, derives an exact immutable Stage 1 authority only from a
deployment-supplied whole-cent ceiling, and shows the prior plus new cumulative amount
before resolving or calling a text client. A missing ceiling blocks activation. The
approved transaction stores an unapproved-media plan/video and consumes Stage 1 into a
zero-call schedule; it does not enqueue the task.

**Why:** Calling the existing section planner to discover what the film should be would
already spend before the script/director gate, while assigning a guessed text price
would make the cumulative approval fictional. A deterministic scaffold lets the real
director own story/style/cast/environment/shot selection after exact consent without
approving any downstream imagery.

**Consequence:** `CUSTOM_FILM_DIRECTOR_V1` remains an explicit activation switch and
`CUSTOM_FILM_DIRECTOR_PASS_MAX_CENTS` is mandatory. Historical plans without the new
execution-model marker retain replay compatibility. A future executor must reconcile
actual text usage/cost inside the held ceiling before this switch can be enabled.

## 2026-07-25 — A 50-shot director plan must be chunked and newly quoted

**Decision:** The current one-response plus one-repair director prototype is a compiler
proof, not an executable Stage 1 production plan. It requests up to 48,000 output tokens,
but the configured Kie text client caps each response at 8,192. Stage 1 must instead
compile a film bible, story/shot outline, and bounded shot batches through a versioned
multi-pass executor, then validate the whole assembled contract.

**Why:** A five-minute film is expected to carry roughly 50 rich shot records. Truncating
that contract would create exactly the missing progression, character drift, and
continuity failures this rebuild exists to prevent. Raising a local request value does
not raise the provider response cap.

**Consequence:** The current two-call authority is deliberately non-transferable. The
multi-pass executor needs an exact new call bill, deployment price, cumulative approval,
authority version, per-call usage/cost journal, and deterministic assembly/retry law
before `CUSTOM_FILM_DIRECTOR_V1` may be enabled.

## 2026-07-26 — Stage 1 has one call manifest and no hidden retries

**Decision:** A five-minute/50-shot director pass is one immutable v2 graph: film bible,
complete outline, seven contiguous maximum-eight-shot batches, and one conditional
repair paired to each initial operation. Its maximum is 18 calls, but a clean run uses
9. Every operation has its own identity, input hash, dependency/result slot, token cap,
and deployment-priced whole-cent ceiling. The execution protocol is `execute_once`;
the existing retrying Kie helper is not a valid adapter.

**Why:** Treating an internally retrying helper as one approved call would hide up to
three external requests, while whole-contract repair would burn money and discard
valid story/continuity work. Small bounded batches fit the real 8,192-token response
cap and make the failed unit attributable.

**Consequence:** A failed partial may consume only its paired repair. Hidden retry
counts, token/cost overages, or malformed usage receipts are authorization failures,
not creative failures, and stop for spend reconciliation.

## 2026-07-26 — Director attempts are append-only financial evidence

**Decision:** Each text operation must commit an `attempt_started` event before the
external request and exactly one completed/failed terminal event afterward. A started
event without a terminal is permanently reconciliation-required; it is never
automatically retried. The final director contract persists only when the durable
receipt manifest exactly matches the validated execution, then an immutable execution
row binds schedule, authority, spend, receipt hashes, and director revision.

**Why:** Database transactions cannot roll back an external call. Treating a crash as
an ordinary retry risks paying twice and recreates the ambiguous-spend failure that
invalidated the earlier Custom Film authority.

**Consequence:** Migration 135 now includes append-only call events and executions.
The production adapter must additionally reconcile terminal text receipts into the
canonical generation ledger before activation; the historical $8.57 is not headroom.

## 2026-07-26 — Scene authority is one explicit hash-bound gate

**Decision:** Scene Control reuses the immutable director and shot contracts, then
adds only six film-level locks, one contiguous scene head, and append-only transition
events. Every forward gate requires the current revision plus its exact artifact
evidence; a paid quote is read-only and no scene-control route can execute it.

**Why:** A whole-stage approval hides media types, retries, and later-scene authority.
One scene/one operation makes creative review, continuity, and spend scope inspectable
without creating a parallel production pipeline.

**Consequence:** Only `accepted` unlocks the next scene. Local synthetic playback may
remain available after rejection as comparison evidence, but it is acceptance evidence
only when the assembly hash is current and the scene is assembled or accepted.

## 2026-07-30 - Film-studio program rulings (Ryan, maestro session)
- Decision: Custom Film gets HARVESTED into the flagship coverage pipeline, not promoted. Context: the 22-point audit showed Custom Film has the strongest schemas (locks, state chain, per-shot purpose) but zero production rows, while coverage is the flagship. Alternatives: promote Custom Film as the data model (long migration under live users), or park it. Why this won: no migration risk, main stays deployable, the engineering value still gets captured piece by piece (phase D9).
- Decision: Program scope is the FULL gap list (phases D8-D14 appended to loop-checklist.md). Context: Ryan - "I just want everything, so whatever it takes to make it all work, and have a clear plan to chew through."
- Decision: Frame-arbiter rollout is Ryan's tenant only (f6839de2), hard per-video budget cap, cost quoted before enabling; auto-redraw sits behind its own sub-flag, DEFAULT OFF, until eval chunk D5-A3b-2 graduates. Alternatives: warn-only for all tenants; build-but-leave-off.
- Decision: Deploys are HELD until Ryan gives a window - another live session is working the DVSU roster loop on the same VPS. All build work happens in worktrees meanwhile.

## 2026-07-31 - Tier floor demoted to advisory (Ryan, dvsu-bulletproof session)
- Decision: the DVsU research referee's Tier 1-2 source requirement drops from a HARD
  BLOCK to an advisory note. Wikipedia-grade (Tier 3-4) sources may carry a card's
  paragraphs. The anti-hallucination core stays untouched: every claim must still match
  text the pipeline itself fetched, verbatim, with server-side capture methods.
- Context: the first fully hands-free roster research run (5 KGV battleships, video
  d05efae3) was rejected 5/5 by the referee - every rejection was source-prestige
  formalism, none was a false fact. Two ships were blocked from writing anything while
  accurate on-topic Wikipedia articles sat fetched in their packages. Many prior
  sessions (Claude + GPT) had been improving gate-appeasement (normalizers, queries,
  repair prompts) instead of questioning the gate.
- Alternatives: keep grinding on gather quality until Tier 1-2 sources are reliably
  found for every machine type (G13 still ships - it helps - but stops being
  load-bearing); or per-beat tier exceptions (more rulebook, same disease).
- Why this won: Ryan's quality target is accurate research in the script, not archival
  pedigree. The verbatim-grounding check alone already prevents invented facts.
