# StoryEngine Pricing Proposal — July 2026

Status: PROPOSAL for Ryan's decision. Competitor data researched 2026-07-20 (web, cited;
confidence flags below). Structural rulings already settled in tasks/decisions.md:
the agent token IS the paywall (C57); one workspace = one channel = one subscription seat
(C61 ruling); flat subscription over per-token billing (BYOK economics).

## The market's shape (research summary)

- **Credits are the dominant metric** (Higgsfield, Crayo, Revid, Pika, Luma, Runway, InVideo,
  vidIQ) — compute resale at ~2–10× markup. Example: Higgsfield ≈58 credits (~$2.90 at
  ~$5/100) for a Veo-class 8s clip that costs $0.30–1.25 direct on Kie (our registry prices).
- **Minutes** for avatar tools (Synthesia $29 entry/10 min-mo; Pictory $29/200 min).
- **Posts-per-week** for faceless-shorts autoposters (AutoShorts $19/39/69).
- **Per-series/channel pricing exists**: Faceless.video charges $20–49/mo PER SERIES —
  precedent for our per-channel seat.
- **Autopilot-to-YouTube is essentially unowned**: only Revid.ai ("Auto-Mode Workers",
  Growth $39–99 → Ultra $199) names it. Higgsfield has none. Our dial (propose → auto-draft →
  full-auto with weekly budget + kill switch + learning flywheel) has no direct comparable.
- **Channel intelligence**: vidIQ Max $39/mo, TubeBuddy Legend ~$49/mo — our analytics
  flywheel + early warning covers this category as a feature, not a product.
- **Claude subscription** (the MCP brain runs on the CUSTOMER'S plan): Pro $20/mo,
  Max from $100/mo. Their spend, not ours — but it means our MCP story is
  "$20 Claude + our sub + raw generation cost."
- **Annual discounts cluster ~20%** (Runway/Pika/Luma/TubeBuddy).

Confidence caveats: Higgsfield, InVideo, Fliki, AutoShorts, Faceless.video, TubeBuddy pages
resisted scraping (JS SPA / 403) — figures are aggregator-reconciled, directional not exact.
Synthesia, Pictory, Runway, Pika, Luma, vidIQ, claude.com fetched from vendor pages directly.

## Our structural edges (what the price is FOR)

1. **BYOK**: users pay raw generation cost (~$3–15 per 10-min video depending on model mix,
   per docs/cost-awareness.md) on their own keys; our marginal cost ≈ 0. Subscription is pure
   software value — no credit-markup defense needed. Publish the credit-math comparison.
2. **Workspace = channel = seat**: the value metric scales with the customer's business,
   not usage anxiety. Multi-channel = multiple workspaces (C61 ruling), each its own seat.
3. **The autonomy ladder is the tier ladder**: manual pipeline → chat director + DNA →
   MCP + autopilot. Top rung competes with hiring a channel manager, not with tools.

## Proposed ladder (existing Stripe plans: starter / pro / agency)

|  | Starter $29/mo | Pro $79/mo | Agency $199/mo |
|---|---|---|---|
| Annual (~20% off) | ~$24/mo | ~$64/mo | ~$159/mo |
| Channel workspaces | 1 | 1 (+$49/mo each extra) | 3 included (+$49/mo each) |
| Full pipeline UI + chat director | ✓ | ✓ | ✓ |
| BYOK generation (raw cost) | ✓ | ✓ | ✓ |
| Videos/month | 10 | Unlimited (fair use) | Unlimited |
| Channel DNA (learn_channel) | — | ✓ | ✓ |
| Quality engine + channel patterns | — | ✓ | ✓ |
| Analytics flywheel + early warning | — | ✓ | ✓ |
| MCP access (Claude/phone driving) | — | ✓ | ✓ |
| Autopilot dial | — | propose → auto-draft | full-auto + weekly budget ceiling |
| Invite-a-manager (future chunk) | — | — | ✓ |

Trial: 14 days (machinery exists — accounts.trial_ends_at, migrations 026/041). No free tier:
BYOK means trialists already pay their own generation; a free tier would only ration software.

## Positioning anchors

- Starter $29 = entry cluster (AutoShorts $19, Synthesia/Pictory $29) with longform pipeline.
- Pro $79 = under Higgsfield Ultra ($79–129) WITH DNA/MCP/auto-draft they lack; beats
  vidIQ Max ($39) + Revid Growth ($39–99) COMBINED as a two-product replacement.
- Agency $199 = Revid Ultra parity for a vastly deeper product; $49/channel validated by
  Faceless.video's $35–49/series; real alternative is a human channel manager ($2k+/mo).
- Total-cost story vs credits: a 10-min video ≈ $3–15 raw BYOK vs multiple hundreds of
  credits at 2–10× markup elsewhere.

## Ryan's decisions to lock (then C62: wire prices into Stripe/UI)

1. **LOCKED** (tasks/decisions.md 2026-07-20 "PRICING RATIFIED"): the three price points +
   annual discount rate, ladder as proposed.
2. Extra-channel seat price ($49/mo proposed) — still open (Stripe price object not yet
   created; no code gate needed until it exists).
3. **LOCKED, WIRED (C62)**: Starter caps are max **video LENGTH 10 minutes** (new) + max **12
   video generations/month** (this was already the number in `PLAN_LIMITS["starter"]` before
   C62 — only the length axis was new). Pro/Agency: **unlimited** video-generation quantity
   (`PLAN_LIMITS["pro"/"agency"]["videos_per_month"]` raised to the same 1,000,000 sentinel the
   comped "unlimited" tier already used) and unlimited uploads (no upload meter exists at all —
   confirmed by trace, nothing to change). Enforcement: `routes/billing.py::
   enforce_video_length_cap` (new), called from `routes/videos.py::create_video` (the C38
   canonical door), `routes/discovery.py::launch_idea` (a separate pre-existing INSERT C38's
   convergence didn't cover — closed as part of this wiring, see SYSTEM_STATE.md §C62), and
   `actions.py::apply_followup_edit` (the chat "redo the script at N minutes" post-create seam).
4. Trial length (14 days proposed) — still open, unchanged this chunk.
5. **LOCKED, WIRED (C62)**: MCP = Pro+ (fills the parked "which tier gets MCP" decision).
   `routes/agent_access.py::create_token`'s commented seam is now a real `_mcp_tier_ok` check
   (operator accounts — `accounts.is_operator` — exempt); the per-request verify gate
   (`auth_agent.get_agent_tenant_id` via `agent_tokens.authenticate_with_standing`, piggybacked
   onto the SAME query, no extra round trip) enforces the same tier check so a live token dies
   same-day on a Pro→Starter downgrade, mirroring how C57 already makes a lapsed subscription
   die same-day.
6. Whether Agency full-auto requires a minimum weekly budget cap set (recommended: yes,
   already enforced by C54b's no-autonomy-without-a-ceiling law) — still open, unchanged.

Implementation note: prices live in Stripe (STRIPE_PRICE_* env vars) + a plan-limits map in
routes/billing.py::check_plan_limits — pricing changes are config + one limits-map edit, not
an architecture change. MCP tier-gating slots into the C57 seam left in create_token.
