# Scope — the research slot contract

Written 2026-09-22, after removing the code-side script checker and shipping
steps 1 and 2 of deterministic scripting. Not started. This is the piece that
actually fixes the Barracuda class of defect.

## The problem, precisely

A brief slot handed to the writer is:

```json
{"answer": "<= 450 chars, a synthesis with one or two hard facts",
 "source_url": "...",
 "quote": "<= 250 chars, ONE exact sentence copied from the page"}
```

The `answer` is deliberately broader than the `quote`. That is the contract,
not a fault — and it is why a numeric support check at this level is useless:

| Check | Flag rate |
|---|---|
| brief slot: answer vs its own quote | **55%** of 179 pairings |
| script: sentence vs its one cited quote | 20% of 88 shipped rows |
| script: sentence vs the WHOLE brief | **0%** of the same 88 rows (shipped) |

55% is not 99 defects. It is the answer being wider than one sentence.

**But one of them is genuinely wrong.** Barracuda's `trade_off` answer asserts
"made only 18.7 knots against 21 designed"; its quote is about 5"/51 guns being
replaced with 3"/50s in 1928. The quote is not merely *narrower* — it is about a
**different subject**. Nothing in it concerns speed.

Today's shape cannot tell those two cases apart, because there is one quote and
nothing says which part of the answer it is meant to prove.

## Options

**A — one quote per hard fact.** Replace the single quote with a `support` list,
each row pairing one hard fact from the answer with its own quote. Makes the
numeric check valid per row. Biggest change: restructures the slot.

**B — declare the headline claim (recommended).** Keep one quote, add one field:

```json
{"answer": "...",
 "headline": "made 18.7 knots against 21 designed",
 "source_url": "...", "quote": "..."}
```

`headline` is the single claim the quote is meant to prove. Then `headline` vs
`quote` is a legitimate 1:1 comparison. Barracuda fails it. Ohio, whose quote is
on-topic but narrower, passes. One extra string per slot, no restructuring.

**C — a model judges support per slot.** ~120 calls per video, and it is exactly
the referee call the v2 design deliberately avoided. Not recommended.

**Recommendation: B.** Escalate to A only if B proves too coarse.

## The hard constraints — this is where the work actually is

1. **The packet round-trip is lossy.** `packet_from_verified_source_package`
   rebuilds each entry from `{text_key, source_url, quote}` only, reading claim
   text from `claims_by_index` and quote/url from `excerpts_by_index`. A new
   `headline` must be threaded through `_build_verified_source_package` into the
   stored package and read back out. **If it is not threaded it vanishes
   silently** — precisely the bug fixed in `routes/videos.py` on 2026-09-22,
   where a whole blob was dropped because a shape did not carry a key.

   Touches: `dvsu_research_v2.py` — the six `_call3_*_prompt` builders,
   `_normalize_answer_slot`, `_normalize_outcome_candidates`,
   `_build_verified_source_package`, `packet_from_verified_source_package`,
   `_machine_packet_markdown`, `adapt_packet_to_factual_card`.

2. **Fingerprint / spend risk.** `brief_fingerprint` hashes the whole brief. If
   `headline` lands on every rebuilt packet — even as an empty string — EVERY
   saved block in EVERY video goes stale, and the next bulk run pays to rewrite
   every paragraph. Omit the key entirely when absent, and pin it with a test
   that an old packet's fingerprint is byte-identical before and after.

3. **Old research has no headline.** The check must be *skipped*, never failed,
   when the field is absent. Existing videos must not be punished.

4. **Advisory only.** Surfaced on the research card. Nothing blocks. That is now
   law here — see the 2026-09-22 checker removal.

## Acceptance

- Barracuda's `trade_off` slot flags.
- Across the other 178 pairings the rate drops from 55% to a handful a human
  agrees are real. If it stays high, option B is too coarse — go to A.
- A round-trip test proves `headline` survives packet → package → storage →
  packet.
- A fingerprint test proves no mass invalidation of existing blocks.

## Sizing

Roughly half a day. The check itself is trivial; the risk is entirely in
constraints 1 and 2.

## Reusable pieces already shipped

`dvsu_script_v2.unsupported_figures()` and its helpers (`_figures`,
`_is_specific`, designation stripping, spelled-number folding) already do the
numeric comparison and are validated at 0% false positives. This scope needs the
right *thing to compare*, not new comparison code.
