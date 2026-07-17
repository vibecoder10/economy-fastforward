# StoryEngine Knowledge Map — where to look, when, and why

**Date:** 2026-07-17 · The routing table for every session working the Higgsfield-competitor plan.
Read this AFTER the handoff in `tasks/todo.md`. Rule of thumb: **never re-explore the codebase
for something a doc below already answers** — the audit cost real money; spend it once.

---

## 1. Where to look, by task

| You are about to… | Read | Why |
|---|---|---|
| Start any session | `tasks/todo.md` (handoff) → this map | Current state + what's next; this map routes the rest |
| Build a checklist item | `tasks/storyengine-wiring-fix-checklist.md` → the item's finding in `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` → its section in `tasks/storyengine-copilot-ux-map.md` | Checklist = WHAT + layers + verify; audit = WHY + file:line evidence; UX map = HOW users touch it (both doors) |
| Question strategy, scope, or "should we even…" | `docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md` + `tasks/decisions.md` (2026-07-17 entries) | The competitive why; settled decisions — don't re-litigate, append if genuinely new |
| Touch models/prompts/routing code | Audit findings §Sweep 2 (model inventory, routing map, fallback chains) | Exact client files + the fallback behavior that must survive refactors |
| Touch chat/copilot code | Audit findings §Sweep 1 + UX map "conversational quality bar" | The two-persona architecture, verb registry seam, money-gate pattern to extend not fork |
| Touch styles/camera/presets | Audit findings §Sweep 4 | The 5 profiles' 11 config sections; the env-var seam; what's already built |
| Touch upload/analytics/autopilot | Audit findings §Sweep 3 | Legacy-vs-SaaS split; which side is canonical; snapshot/learnings mechanics |
| Write a migration / new column | `storyengine/schema.sql` + checklist Definition of Done | Column must exist in live Supabase, not just schema.sql (verified, not assumed) |
| Debug a production failure | `docs/failure-modes.md` first | Known failures with fixes — don't re-diagnose known modes |
| Estimate/verify costs | `docs/cost-awareness.md` ⚠ partially stale (lists Seed Dream; scene images are GPT Image 2 now — update as part of P0.3) | Per-op costs; the ledger (P0.3) becomes the real source once built |
| Deploy / touch the VPS | CLAUDE.md VPS Deploy Coordination Rule + `docs/infrastructure.md` | Lock file, deploy script, shared-box protocol — sessions have clobbered each other |
| Repeat-mistake check | `tasks/lessons.md` | Read every session per protocol; 2026-07-17 entry covers subagent model policy |

## 2. When to REBUILD knowledge vs reuse it
- **Reuse always** for architecture facts (registries, seams, file locations) — code moves slowly; the audit is dated 2026-07-17 and findings carry file:line anchors you can spot-check in seconds.
- **Re-verify before relying** on anything marked [reported] in the Higgsfield report, all Higgsfield pricing (changed 3× in 90 days), and any audit finding you're about to build ON TOP OF (one `grep`/`Read` of the anchor, not a new sweep).
- **A finding that's been FIXED** should have its checklist box ticked in the same commit — if a box is ticked, the audit's description of that problem is historical.

---

## 3. Sweeps NOT yet run — run just-in-time, not up-front

The four completed sweeps (copilot flow, model routing/BYOK, growth loop, styles/presets)
covered the product surface. These six were deliberately deferred. Each lists its TRIGGER —
run it when the trigger phase starts, as ONE Explore agent on **Sonnet** (per CLAUDE.md model
policy; expect ~150-250k Sonnet tokens each, cheap), and append results to the audit findings
report so this map stays the single index.

### S5 — Security & tenant isolation ⚠ highest stakes
- **Trigger:** BEFORE starting P2.4 (MCP server) or any external API token work. Also before enabling `PER_USER_KEYS_ENABLED`.
- **Scope:** tenant scoping on every route in `storyengine/backend/routes/` (can tenant A read/write tenant B's videos/assets/keys?); vault leak paths (keys in logs, error messages, chat history); money-gate bypass attempts (any paid path without quote+confirm — including future MCP tools); prompt-injection from untrusted inputs (competitor titles/transcripts/YouTube descriptions flow into producer prompts — can a malicious video title steer the copilot?); token scope design for `agent_tokens`.
- **Why:** the MCP server turns the verb registry into an attack surface; BYOK means a leak costs the USER's money, which is fatal to the trust positioning.

### S6 — Schema & data integrity
- **Trigger:** BEFORE the first P0.3 migration (`generation_ledger`) — piggyback the new tables on a verified base.
- **Scope:** `schema.sql` vs live Supabase drift (columns that exist in one, not the other); orphaned tables/columns from deleted features (niche wizard, /competitors); missing indexes for upcoming query patterns (ledger rollups per video/tenant, per-preset analytics joins, scorecard reads); migration history coherence (`backend/migrations/` vs applied).
- **Why:** the build plan adds 4+ migrations; the wiring rule's #1 DB failure is "column in schema.sql that was never migrated."

### S7 — Queue, reliability & observability
- **Trigger:** WITH P1.3 (draft/finalize) — its no-double-billing guarantee depends on job idempotency.
- **Scope:** arq worker per-stage timeouts/retries vs actual stage durations; idempotent `job_id` coverage (`stage:video:attempt`) on every paid path incl. new draft/finalize verbs; the SILENT Redis fallback (in-process BackgroundTasks with no error — how does a user learn their queue is degraded?); SSE dropout/reconnect behavior; error surfacing (which failures reach the UI as cards vs die in logs); log hygiene (no keys/PII).
- **Why:** draft/finalize multiplies generation calls; a retry bug that double-bills a BYOK user's own key is the worst possible bug for this product.

### S8 — Render & media path
- **Trigger:** BEFORE shipping the draft-pass UX (P1.3) — drafts are only useful if render/preview turnaround is fast and reliable.
- **Scope:** StoryEngine-side render flow (`run_render`, Remotion invocation, VPS memory/swap constraints); audio-sync (Whisper alignment) failure modes on the SaaS side; app-storage vs Drive lifecycle (orphaned assets, disk growth); stitch paths; what a "draft-quality fast render" option would need.
- **Why:** the only pipeline region no sweep covered end-to-end; it's where all the money spent upstream becomes a watchable file.

### S9 — Frontend state & UX compliance
- **Trigger:** ALONGSIDE P2 surfacing work (gallery, chips, badges add many new stateful components).
- **Scope:** React Query invalidation map (which mutations invalidate which keys — stale-cache is a listed top failure mode); loading/error/empty states inventory on existing components (find the gaps before copying patterns); mobile behavior of the dock/sheets; dead components left from deleted features; `web-design-guidelines` audit of the new surfaces.
- **Why:** the two-doors law means every feature doubles its UI surface; inconsistent state handling would multiply with it.

### S10 — Multi-tenant readiness & branding leakage
- **Trigger:** BEFORE onboarding a second real tenant/channel.
- **Scope:** grep-level hunt for Power-Doctrine/Economy-FastForward hardcoding beyond the known SEO case (`@Power_Doctrine` line, default ElevenLabs voice `G17SuINrv2H9FC6nvetn`, category 25 default, Slack channel constants); plan gating correctness (`check_plan_limits` paths); per-tenant defaults audit (what does tenant #2 inherit that it shouldn't?).
- **Why:** audit found one branding leak in 4 sweeps without looking for it — there will be more; each one emails another channel's audience with your branding.

### Deliberately NOT queued
- **Test-coverage sweep** — fold into each build item instead: the checklist's Definition of Done already demands verify evidence; add tests where you touch code, don't audit testing in the abstract.
- **Content-policy/compliance sweep** (YouTube AI-disclosure, made-for-kids, moderation) — becomes relevant with the growth push / Earn-style programs, not during the router build. Revisit when marketing starts.

---

## 4. Doc inventory (single list, newest plan first)
| Doc | Role | Maintained? |
|---|---|---|
| `tasks/todo.md` | Session handoff — always current | Every session (protocol) |
| `tasks/storyengine-knowledge-map.md` | This map — routing + sweep queue | When docs/sweeps are added |
| `tasks/storyengine-wiring-fix-checklist.md` | Work queue with layer mapping | Tick boxes in fix commits |
| `tasks/storyengine-copilot-ux-map.md` | Interaction spec (two doors + MCP) | When UX decisions change |
| `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` | Audit evidence (append future sweep results here) | Append-only |
| `docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md` | Competitive research | Frozen (re-research only on demand) |
| `tasks/decisions.md` / `tasks/lessons.md` | Settled choices / hard-won patterns | Append-only, per protocol |
