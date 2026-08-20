# Pain Hunter — Feature 1: The Hunter

**Status:** Spec / not built
**Date:** 2026-08-20
**Product:** Standalone iOS app. NOT part of StoryEngine, not part of the video pipeline.
This doc lives here only because it's the repo the design session ran in.

---

## 1. What Feature 1 is

A scheduled sweep that finds *pain worth solving* and pushes a small, ranked,
evidence-backed digest to your phone on a cadence. You are a reader. Feature 2
(capture — Share Sheet ingestion of pain you spot yourself) is a later feature
and is explicitly out of scope here.

```
sweep → extract → cluster → score → disqualify → solve → digest → notify → verdict
```

Every stage is idempotent and resumable. `signals` is append-only; everything
downstream is derived and re-computable from stored signals without re-sweeping.
This is the single most important architectural decision in the doc — see §5.

---

## 2. The core insight this whole design rests on

**Pain is free and infinite. Ranked pain is scarce.**

Anyone can scrape a subreddit and get 10,000 complaints by Tuesday. The scraper
is a weekend of work. **The scoring model is the product**, and everything else
exists to feed it or to make its output trustworthy.

Second insight, which sets the unit of value:

**One complaint is noise. A cluster of independent complaints is a market.**

So the atomic object of the product is not a complaint — it's a `pain_cluster`.
Fourteen people across three communities and two review sites describing the same
broken workflow is a signal. Fourteen comments in one thread is *one* signal
wearing a costume. The independence rule (§3.1) is what keeps the feed honest.

---

## 3. The scoring model (the IP)

**Design principle: each axis is computed from extracted evidence, not from an
LLM's opinion.** The LLM's job is extraction and classification — structured,
citable, verifiable. Judgment lives in code, except for one axis (buildability)
where it is applied as a *penalty* and must cite.

Total 100 points across five axes.

### 3.1 FREQUENCY — 0–25

How many *independent* voices, weighted for recency.

- `distinct_threads` — signals sharing a `thread_key` collapse to ONE. A thread
  is one event, no matter how many people pile on. **This rule alone removes most
  of the noise.**
- `distinct_sources` — appearing in 3 communities beats 10 hits in one.
- `distinct_authors` — capped, and only counted across threads.
- `recency` — half-life weighting; a pain from 2019 that stopped being mentioned
  is a solved pain or a dead market.

```
frequency = min(25,
    5.0 * distinct_sources
  + 2.0 * min(distinct_threads, 6)
  + 3.0 * recency_factor            # recency_factor in [0,1], 90-day half-life
)
```

### 3.2 SPEND EVIDENCE — 0–30 (heaviest weight, and the differentiator)

Is money already moving? "People complain" is weak evidence. **"People pay and
hate it" is a business.** You are not creating demand, you are redirecting a
budget line that already exists.

| Evidence found | Points |
|---|---|
| Explicit price stated by a sufferer ("we pay $400/mo and it's garbage") | 30 |
| Named paid tool + poor review sentiment | 24 |
| Agency / freelancer / VA doing it manually for money | 20 |
| Paid tool named, sentiment neutral | 12 |
| Only free tools mentioned | 5 |
| No evidence anyone pays anything | 0 |

This is **extraction, not judgment** — currency regex plus classification of
tool names, `we pay`, `we hired`, `quoted us`, `per seat`, `retainer`.

### 3.3 WORKAROUND EVIDENCE — 0–20

Are they duct-taping? A named workaround is the strongest proof that the pain is
both real *and* software-shaped, because they already tried to solve it with
software and failed.

Markers: spreadsheet, Airtable, Zapier/Make, "built an internal tool", "copy
paste", "manual", "our VA does it", "a Google Form and a prayer".

```
workaround = min(20, 7 * distinct_workaround_kinds + 6 * has_custom_internal_build)
```

### 3.4 REACHABILITY — 0–15

Can you find these people tomorrow? A pain concentrated in one findable community
is worth more than the same pain scattered across the open web, because the first
test (§7, item 8) is only possible if you can reach them.

```
reachability = 15 * concentration_ratio     # top-source share of signals,
                                            # floored when signals < 4
```

### 3.5 BUILDABILITY — 0–10, applied as a penalty

Is a digital thing actually the fix? Most pain is not software-shaped. Start at
10 and subtract for: physical logistics, licensed/regulated activity, needs
network effects from zero, enterprise procurement cycle, requires data you can't
legally obtain.

This is the one LLM-judged axis. It must return the deduction **with the reason
and the signal IDs that imply it** — no bare number.

### 3.6 Disqualifiers (zero the cluster regardless of score)

**These matter more than the score.** They are what keeps the feed from being 80%
garbage:

- **Platform-dependent** — the fix is a feature the platform will ship
  ("I wish Notion had…"). You'd be building on a trapdoor.
- **Single-company complaint** — it's a support ticket, not a market.
- **Already well-solved** — a good product exists, fairly priced, well reviewed.
- **Requires being someone you're not** — licensed, credentialed, capital-heavy.
- **Astroturf / marketing** — the "complaint" is a competitor's growth post.

### 3.7 Calibration warning

**Raw scores are meaningless in absolute terms.** Rank within the week's harvest
and ship the top N. Do NOT ship a fixed threshold ("anything above 70") until you
have several hundred scored clusters to calibrate against. Store every score with
its `scorer_version` so retuning is measurable rather than vibes.

---

## 4. Sources

Ordered by signal-to-noise, which is **not** the same as volume.

| Source | Yields | S/N | Friction |
|---|---|---|---|
| App Store / Play 1–2★ on *paid* apps | spend + pain in one item | highest | no official API for competitors; scraping |
| G2 / Capterra low reviews | spend + pain, B2B budgets | highest | ToS-hostile; scraping |
| Fiverr / Upwork listings + order counts | proven repeat spend | high | scraping |
| Reddit rants + "what do you use for X" | pain + workarounds | medium | OAuth API, rate limits, paid above free tier |
| GitHub issues: many 👍, no fix, stale | supply gap | medium | free API, generous |
| Hacker News "Ask HN" | pain, technical | medium | free Algolia API |

**Start with GitHub + Hacker News + Reddit.** All three have real APIs and low
legal friction. The review-scrapers are higher signal but will eat every hour you
have on anti-bot work while teaching you *nothing* about whether the product is
good. Add them in feature 1.5, once the pipeline produces a digest you trust.

---

## 5. Schema (Postgres / Supabase)

```sql
create extension if not exists vector;

create table sources (
  id            uuid primary key default gen_random_uuid(),
  kind          text not null,            -- reddit_sub | github_search | hn_query | app_store | g2
  identifier    text not null,            -- r/smallbusiness | "label:bug is:open" | ...
  config        jsonb not null default '{}',
  enabled       boolean not null default true,
  last_swept_at timestamptz,
  unique (kind, identifier)
);

-- APPEND-ONLY. Never mutated, never deleted. Everything below is derived.
create table signals (
  id            uuid primary key default gen_random_uuid(),
  source_id     uuid not null references sources(id),
  external_id   text not null,            -- provider's id, for dedupe on re-sweep
  thread_key    text not null,            -- collapses same-thread pile-ons (see 3.1)
  permalink     text not null,
  author_hash   text,                     -- HASHED. never store the username.
  captured_text text not null,
  posted_at     timestamptz,
  captured_at   timestamptz not null default now(),
  raw           jsonb,
  unique (source_id, external_id)
);
create index on signals (thread_key);
create index on signals (posted_at desc);

create table signal_extractions (
  signal_id      uuid primary key references signals(id) on delete cascade,
  pain_statement text,
  signal_type    text,                    -- pain | spend | workaround | supply_gap | noise
  price_mentions jsonb  not null default '[]',   -- [{amount, currency, period, quote}]
  tools_named    text[] not null default '{}',
  workarounds    text[] not null default '{}',
  embedding      vector(1024),
  model          text not null,
  extractor_ver  text not null,
  extracted_at   timestamptz not null default now()
);

create table pain_clusters (
  id                 uuid primary key default gen_random_uuid(),
  canonical_statement text not null,      -- the pain in THEIR words, one sentence
  domain             text,
  centroid           vector(1024),
  first_seen_at      timestamptz not null,
  last_seen_at       timestamptz not null,
  status             text not null default 'active'
);

create table cluster_signals (
  cluster_id uuid not null references pain_clusters(id) on delete cascade,
  signal_id  uuid not null references signals(id) on delete cascade,
  similarity real not null,
  added_at   timestamptz not null default now(),
  primary key (cluster_id, signal_id)
);

-- VERSIONED. You will retune the scorer weekly; you need to diff models.
create table cluster_scores (
  id             uuid primary key default gen_random_uuid(),
  cluster_id     uuid not null references pain_clusters(id) on delete cascade,
  scorer_version text not null,
  frequency      real not null,
  spend          real not null,
  workaround     real not null,
  reachability   real not null,
  buildability   real not null,
  total          real not null,
  disqualifiers  text[] not null default '{}',
  inputs         jsonb not null,          -- every number that produced the score
  computed_at    timestamptz not null default now(),
  unique (cluster_id, scorer_version)
);

create table solutions (
  id          uuid primary key default gen_random_uuid(),
  cluster_id  uuid not null references pain_clusters(id) on delete cascade,
  headline    text not null,
  features    jsonb not null,   -- [{feature, evidence_signal_ids: [...]}]  <- REQUIRED
  first_test  jsonb not null,   -- {who, where, dm_copy, landing_headline}
  model       text not null,
  created_at  timestamptz not null default now()
);

-- The compounding loop. Without this the app is a static feed forever.
create table verdicts (
  id         uuid primary key default gen_random_uuid(),
  cluster_id uuid not null references pain_clusters(id) on delete cascade,
  verdict    text not null,    -- pursue | park | kill
  reason     text,
  decided_at timestamptz not null default now()
);

create table digests (
  id          uuid primary key default gen_random_uuid(),
  period_start date not null,
  cluster_ids  uuid[] not null,
  sent_at      timestamptz,
  opened_at    timestamptz
);
```

**Three decisions worth defending:**

1. **`signals` is immutable and append-only.** When you retune the extractor or
   the scorer — and you will, constantly — you re-run over stored rows instead of
   re-scraping. This is what makes iteration cheap. Get it wrong and every model
   change costs you a full sweep and a rate-limit fight.
2. **`author_hash`, never the username.** You're storing complaints written by
   real people. Privacy, Reddit's ToS, and App Store review all point the same
   direction. The permalink is the attribution; the handle isn't yours to keep.
3. **`solutions.features[].evidence_signal_ids` is required, not optional.** A
   feature with no evidence trace doesn't get rendered. This is the difference
   between a product and ChatGPT with extra steps.

**Clustering:** embed each extraction, incremental assignment — nearest centroid
above a cosine threshold (start ~0.82, tune) joins that cluster, otherwise open a
new one. Recompute the centroid on join. Anthropic doesn't serve embeddings;
Voyage is the recommended pairing, pgvector stores them.

---

## 6. Model + cost architecture

**Extraction is ~90% of your spend. Everything else rounds to zero.** That single
fact should drive the whole design.

| Stage | Volume | Model | Why |
|---|---|---|---|
| Extraction | every signal (~5k/wk) | **Claude Haiku 4.5** ($1/$5 per 1M) | structured, verifiable, schema-checked — capability isn't the constraint |
| Clustering | every extraction | embedding model, no LLM | pure vector math |
| Scoring | every cluster | **no LLM** — deterministic code | reproducible, free, debuggable |
| Buildability penalty | surviving clusters only | Claude Haiku 4.5 | one narrow judgment, must cite |
| Solution + first test | ~5 clusters/wk | **Claude Opus 5** ($5/$25), adaptive thinking, web search | the one place quality is visible to you |

Rough weekly math at 5,000 signals (~600 in / ~250 out each):

- Extraction on Haiku 4.5: ~$3.00 in + ~$6.25 out ≈ **$9.25/week**
- Synthesis on Opus 5, 5 clusters: ≈ **$1.25/week**

Two levers that cut the dominant line item roughly 4×, and you should take both:

- **Batch API — 50% off.** The sweep is nightly or weekly. It is the textbook
  non-latency-sensitive workload. There is no reason to pay realtime rates.
- **Prompt caching on the extraction system prompt.** The taxonomy and few-shot
  examples are a stable prefix across thousands of calls — up to ~90% off the
  cached portion. Keep the prefix byte-stable (no timestamps, sorted JSON) and
  verify with `usage.cache_read_input_tokens`; a silent invalidator costs you the
  whole saving without erroring.

Landing around **~$10–12/month** in model spend at that volume. Use structured
outputs (`output_config.format`) on extraction so the rows land typed and you're
not writing defensive JSON parsers over model output.

---

## 7. The digest — the actual product surface

What arrives on the phone. Per cluster, in this order:

1. **The pain in one sentence, in *their* words** — not your paraphrase
2. **Score, and the single axis that carried it** ("this scored on spend")
3. **Three verbatim quotes with tappable permalinks** — the trust anchor; without
   this the whole thing reads as an LLM being agreeable
4. **What they pay today** — the spend evidence, stated explicitly
5. **The workaround** — what duct tape exists right now
6. **Proposed digital solution — 3 features max**, each showing the signals that
   justify it
7. **Why it might be a trap** — the strongest disqualifier that *didn't* fire.
   An honest counter-case is what makes the other six items believable.
8. **The first test** — who to DM, where they are, the DM copy, and the landing
   page headline in their own words

**Item 8 is the whole differentiator.** An app that ends at "here's your idea"
leaves you at the most dangerous moment: full conviction, zero evidence anyone
pays. An app that ends at "here are the 8 people who complained and the message
to send them" is a different product.

9. **Verdict: Pursue / Park / Kill** — writes to `verdicts`, which is the only
   thing that makes the scorer improve over time.

---

## 8. Build order

The app comes last, deliberately. Feature 1's proof is "the digest is good," and
that can be proven in a text file.

- **Step 1 — sweep + store, no LLM.** GitHub + HN + Reddit into Supabase. Then
  read the raw `signals` table. *Gate: do these rows contain real pain?*
- **Step 2 — extract + cluster + score v0.** Output a ranked markdown file. Read
  it. *Gate: is the top 5 any good? Would you act on one?*
- **Step 3 — solution + first test + digest + push.** Then the Expo shell around
  it.

Stack: **Expo / React Native** (TypeScript + React carries over from what you
already run daily) on **FastAPI + Supabase** — same shapes you use every day, no
new stack to learn while also figuring out the product.

If Step 2's gate fails, you've spent two weekends instead of three months.

---

## 9. Open risks

- **Crowded category.** GummySearch, IdeaBrowser, Exploding Topics and others
  sell "find pain on Reddit". The wedge has to be spend evidence + the first
  test. "Reddit scraper with an AI summary" is not a wedge.
- **Reddit API terms.** OAuth app registration required, free tier is rate-limited
  and non-commercial. Verify current terms before designing around volume.
- **App Store review** will want to see this isn't reselling scraped third-party
  content. The evidence-and-permalink model helps; storing raw dumps doesn't.
- **Scorer overfitting to your taste.** `verdicts` makes the loop compound, but it
  also teaches the model to show you what you already like. Keep one "wildcard"
  slot per digest that ignores the learned weights.
