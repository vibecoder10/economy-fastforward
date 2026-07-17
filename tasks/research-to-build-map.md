# Research → Build Traceability Map

**Date:** 2026-07-17 · Guarantees the Higgsfield research + 4-agent audit convert into work, not shelf-ware. EVERY insight from `docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md` has a row and a disposition. No blank dispositions allowed — if new research lands, it gets rows here in the same commit.

**Dispositions:**
- **BUILD-NOW** → item exists in `tasks/storyengine-wiring-fix-checklist.md` (ref given)
- **BUILD-LATER** → checklist Backlog section (ref given)
- **GROWTH** → marketing/distribution play, §Growth backlog below (not engineering)
- **PARKED** → deliberately not now; revisit trigger stated
- **REJECTED** → will not do; reason stated

---

## Part 1 insights — what makes Higgsfield special

| Insight (gap-analysis ref) | Disposition | Maps to |
|---|---|---|
| Aggregator thesis: 15-30+ models, one interface | BUILD-NOW + BUILD-LATER | P1.1 decision-table registry is the foundation; Backlog B1 expands the wired lineup (Kling 3.0 / WAN / Sora 2 via Kie as they're exposed) |
| "New SOTA within 24h" integration velocity | BUILD-LATER | B1 — registry-as-data (P1.1) is what makes adding a model a config row, not a deploy |
| Workflow orchestration positioning (not raw aggregation; 40% usage via studios) | BUILD-NOW | The whole P1 router + draft/finalize IS this positioning; north-star framing in gap analysis Part 5 |
| Generation-time camera control as first-class surface | BUILD-NOW | P2.2 camera chips from the existing 40+ move catalog |
| Preset hides model+scaffolding+pacing ("preset IS the router") | BUILD-NOW | P2.1 styles-as-data bundling look+camera+model; UX map §3 |
| ~10 presets/day shipped, cycled by engagement data | BUILD-NOW (our version) | P3.1 preset-performance loop on OUR channel CTR — better data than their engagement metric |
| Soul ID character consistency (oversold; breaks profile/overhead) | GROWTH | G5 — SE cast-lock is already competitive (audit Sweep 4 finding 6); name it, market it, don't rebuild it |
| Supercomputer agentic chat | BUILD-NOW | Already at parity via Producer/co-pilot; UX map conversational quality bar closes the polish gap; MCP (P2.4) exceeds it |
| Credit pricing: 10-15× per-model variance surfaced to users | BUILD-NOW | P1.2 itemized per-tier quotes; P0.3 true-cost ledger |
| Throttled "unlimited" + billing dark patterns (verified) | GROWTH + PARKED | G1 anti-positioning marketing; PARKED as billing-design principles until SE ships its own paid plans — revisit when pricing work starts |
| ~70% agency revenue, ~$1k ACV, pro-skew | PARKED | ICP/pricing strategy input — revisit at monetization planning; not an engineering item |
| No timeline editor / clips-only weakness | BUILD-NOW | Already SE's moat (full pipeline); no action beyond not regressing it — market in G1 |
| Credits expire 90 days / queue waits / no batch | GROWTH | G1 — contrast copy for BYOK true-cost positioning |
| Public API exists but account-bound credits (opposite of BYOK) | BUILD-NOW | P2.4 MCP with BYOK pass-through is the direct counter |
| Trustpilot polarization / trust deficit | GROWTH | G1 — trust is the wedge; also reinforces money-gate sacredness (decisions.md) |
| Pricing churned 3× in 90 days | PARKED | Competitive-watch note; re-verify their pricing before any public comparison content (knowledge map §2) |

## Part 2 insights — how Higgsfield promotes

| Insight | Disposition | Maps to |
|---|---|---|
| Higgsfield Earn: pay-per-engagement UGC at scale | REJECTED as-is; GROWTH adapted | Weak moderation caused racist-content scandal + payment failures (verified reporting). Adapted version = G2 "made with StoryEngine" optional attribution + showcase, no pay-per-view |
| Preset-as-content-marketing (every preset a meme format) | GROWTH | G3 — every new style/camera preset launches with a YouTube Short + template video |
| Model-comparison blog as SEO + routing education | GROWTH | G4 — publish OUR "best model for X on your own keys" content; doubles as router documentation |
| Celebrity/organic virality, 20× spike | PARKED | Not reproducible by plan; the YouTube-native answer is users' published videos being inherently public — no build item |
| MCP as agent-ecosystem distribution channel | BUILD-NOW | P2.4 — and ours ends at a published video with performance data (moat sentence) |
| Rage-bait/controversy strategy | REJECTED | Trust is our wedge; explicitly listed in gap analysis "not to copy" |
| Dark-pattern checkout/cancellation | REJECTED | Same; PARKED billing principles row above covers the positive version |

## Part 3 insights — routing

| Insight | Disposition | Maps to |
|---|---|---|
| Per-model "best for" badges (editorial routing) | BUILD-NOW | P1.1 `/api/models` best_for data + badges |
| Published task→model decision tables | BUILD-NOW | P1.2 router mapping (scene intent → model), seeded from our 4 wired models |
| "Draft cheap, finish expensive" cost strategy | BUILD-NOW | P1.3 draft_pass/finalize verbs — enforced as product, not advice |
| Preset-encoded routing | BUILD-NOW | P2.1 preset bundles include model choice |
| Agent auto-select with manual override (MCP pattern) | BUILD-NOW | P1.2 routed-with-why + one-tap override; decisions.md 2026-07-17 |
| GPT-4.1/5 planning layer translating intent → structured instructions ([reported], single source) | BUILD-NOW (our version) | The Producer already IS this layer (Claude); no new build — noted so nobody chases a phantom feature |
| 9 e-commerce format presets (UGC/unboxing/TV spot) | PARKED | E-commerce formats aren't our ICP; revisit if SE targets brand/agency users. YouTube-native format presets (explainer/doc/listicle) fold into P2.1 preset design when authored |

## Part 4/5 — comparison verdicts & recommendations
All 8 recommendations map 1:1: #1→P1.1-1.2 · #2→P1.3 · #3→P0.1-0.2 · #4→P2.1-2.2 · #5→P3.1 · #6→P0.3 · #7→P0.4-0.6 · #8→G3+G4+P2.4. The 4-agent audit findings map is in the checklist header + audit report (every finding → checklist ref, incl. P3.3/P3.4 sweep-ins).

---

## Growth backlog (marketing/distribution — NOT engineering; owner: Ryan)
- **G1 — Trust/true-cost positioning:** landing + comparison page powered by the real ledger (P0.3): "this video cost $12.40 on your keys — the same generations behind a credit wall: ~$30-60." Contrast: no expiry, no throttled unlimited, no cancellation maze. Blocked by: P0.3 shipped.
- **G2 — "Made with StoryEngine" attribution + showcase:** optional per-video attribution; showcase gallery of user videos WITH their public CTR/growth stats (proof Higgsfield can't show). No pay-per-engagement. Blocked by: multi-tenant readiness (S10 sweep).
- **G3 — Preset launches as content:** each new style/camera preset ships with a YouTube Short demo + a one-click "make one like this" template link. Blocked by: P2.1 gallery.
- **G4 — Model-routing content/SEO:** "best model for X at true cost" series; doubles as product docs for the router. Blocked by: P1 shipped (write from real routing tables).
- **G5 — Name and market cast-lock** (character consistency): SE's answer to Soul ID marketing; capability already exists. Blocked by: nothing — copy task.

## Checklist Backlog additions (engineering, post-router)
- **B1 — Expand wired model lineup:** wire Kling 3.0 / WAN / Sora 2 (etc.) through Kie as Kie exposes them; each addition = registry row with best_for/tier/cost + wired flag (no code path changes once P1.1 lands). Added to checklist Backlog.

## Maintenance rule
When any future research lands (new sweep, new competitor teardown, pricing re-check): add its insights as rows here WITH dispositions in the same commit, and link new BUILD items to the checklist. An insight without a row is a bug in the process.
