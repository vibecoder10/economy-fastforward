---
name: etsy-product-hunt
description: Hunt for profitable Etsy product niches using the EverBee MCP connector (product, keyword, and shop analytics). Use when the user wants to find product opportunities, validate a niche or listing idea, size demand for a keyword, size up a competitor shop, or asks to "hunt", "research products", "find a niche", or "check if X sells" on Etsy/print-on-demand.
---

# Etsy Product Hunt (EverBee)

Turn a vague "what should I sell?" into a ranked, evidence-backed shortlist.

## Prerequisite

Requires the `everbee` MCP server (configured in `.mcp.json`). If its tools are
absent, the user has not completed OAuth — tell them to run `/mcp` → `everbee`
→ Authenticate, and stop. Do not substitute guesses or general web search for
EverBee data and present it as if it were EverBee data.

## Step 0 — Discover the tools (do this first, every time)

Do not assume tool names. Read the actual `mcp__everbee__*` tools in your tool
list and their schemas, then map them onto the three jobs below:

- **product analytics** — sales, revenue, conversion rate, views, ~12mo trend
- **keyword analytics** — search volume, competition, keyword score
- **shop analytics** — competitor revenue, bestsellers, growth

If a job has no matching tool, say so and adapt the funnel rather than faking
the step. Scope granted is `products:read` — this connector is read-only.

## The funnel

Never hand back raw tool dumps. Run all four stages, narrowing each time.

### 1. Frame the hunt
Pin down before querying — ask only if the answer changes the search:
- Seed: niche, keyword, product type, or a competitor shop to reverse-engineer
- Fulfilment: print-on-demand, handmade, digital download (this sets margin)
- Constraints: budget, ship complexity, any category the user won't touch

Digital vs. physical matters more than any other input — it changes which
revenue numbers actually clear as profit.

### 2. Cast wide (keyword + product analytics)
Generate 8-15 candidate search terms around the seed — include adjacent and
long-tail phrasings, not just the obvious head term. Pull volume and
competition for each. Keep terms with real demand and beatable competition.

### 3. Screen the survivors (product analytics)
For each surviving term, pull the listings actually winning it and check:

| Signal | Why it matters |
|---|---|
| Monthly sales + revenue | Is there money here at all |
| Conversion rate | Demand is real, not just browsers |
| 12-month trend | Growing / flat / decaying — reject decaying |
| Age of top listings | New listings ranking = the niche is still enterable |
| Listing count vs. volume | The actual saturation ratio |
| Price band | Whether margin survives fulfilment cost |

**Reject on:** demand concentrated in one dominant shop, a decaying trend, or
a price band that cannot carry the fulfilment cost. Say which rule killed it.

### 4. Verify with shops (shop analytics)
For the top 3-5, examine shops ranking for the term. A niche where several
mid-sized shops earn steadily is healthier than one a single incumbent owns.
Check whether recently-opened shops are gaining traction — that is the single
best proof the niche is still enterable.

## Calibrate thresholds, do not inherit them

Any specific cutoff ("volume > 1,000", "under 10k listings") is a starting
heuristic, not a law — the right numbers differ by category and move over
time. Derive them from the data in this hunt: pull a term the user already
knows sells and use its numbers as the baseline to judge candidates against.
State the thresholds you used so they can be argued with.

## Output

A ranked shortlist. Per candidate:

- **Niche / keyword** and why it surfaced
- **The numbers** — volume, competition, monthly revenue of top listings, trend
- **The opening** — the specific underserved angle, not "there is demand"
- **The risk** — what would make this fail
- **Verdict** — pursue / watch / reject, with the deciding signal named

Close with the single strongest pick and the first concrete listing to test.

## Honesty rules

- Cite the numbers EverBee returned. Never invent or round-fill a metric.
- If data is thin or contradictory, say so — a weak hunt reported honestly is
  worth more than a confident shortlist built on three data points.
- Seasonality is a trap: a term peaking in Q4 looks like growth in November.
  Check where in the 12-month curve you are before calling anything a trend.
- EverBee's figures are estimates from marketplace signals, not Etsy's books.
  Treat them as directional — good for ranking candidates, not for forecasting
  revenue to the dollar.
