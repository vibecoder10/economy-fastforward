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
