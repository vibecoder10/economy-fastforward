# Probability-judgment evidence map

Scope: source audit of the factual-machine judgment path at checkout
`f92c863b550dcf5cd3a72e351d045b554ef8fdcf`. No provider, production, or
test execution occurred.

## Observed confidence and ranking math

- The factual_100_v1 judgment path has no calibrated probability, probability
  threshold, Bayesian update, calibration dataset, or confidence aggregation.
  The only emitted confidence value in that path is the categorical string
  `"high"` on each evidence-card segment; it is assigned after traceability
  and exact-machine eligibility, with no numeric calculation
  ([factual_machine_research.py:104-139](../../backend/factual_machine_research.py),
  [factual_machine_research.py:156-181](../../backend/factual_machine_research.py)).
- Candidate eligibility is deterministic: an excerpt needs an ID, text, URL,
  locator, and an approved capture method (or `wayback:`); Grokipedia hosts are
  excluded. It must also pass the exact-machine matcher, and duplicate
  `(source_url, casefolded_text)` pairs are removed
  ([factual_machine_research.py:37-52](../../backend/factual_machine_research.py),
  [factual_machine_research.py:55-101](../../backend/factual_machine_research.py),
  [factual_machine_research.py:104-120](../../backend/factual_machine_research.py)).
- Evidence-card selection bounds the requested count to 1–12 and prefers one
  excerpt per URL before admitting second excerpts from those URLs. This is a
  diversity heuristic, not a confidence computation
  ([factual_machine_research.py:120-139](../../backend/factual_machine_research.py)).
- The separate review-context ranking is deterministic: `word_overlap + 3 ×
  number_overlap + 5 × high_risk_overlap`, where high-risk words are
  `all, cheapest, every, fastest, first, highest, largest, lowest, most,
  never, only, expensive`. At most eight alternate excerpts are retained,
  prioritizing unseen URLs then filling from already-seen URLs; it does not
  produce or consume a probability
  ([factual_machine_summary.py:38-47](../../backend/factual_machine_summary.py),
  [factual_machine_summary.py:325-391](../../backend/factual_machine_summary.py)).

## Claim and contradiction gates

- Before model review, a paragraph must be nonempty, at most 110 words, name
  the locked machine, and map every paragraph sentence exactly once. Each map
  row needs citation objects whose IDs resolve to eligible exact-machine
  excerpts; explicit quotes must be exact substrings (an omitted quote becomes
  the fetched excerpt text)
  ([factual_machine_summary.py:194-261](../../backend/factual_machine_summary.py),
  [factual_machine_summary.py:299-307](../../backend/factual_machine_summary.py)).
- Numeric guard: after removing machine designations, every numeric digit or
  number word in a sentence must occur in its cited quotes. Any set difference
  is blocking. The test is exact token presence, not numerical entailment
  ([factual_machine_summary.py:151-163](../../backend/factual_machine_summary.py),
  [factual_machine_summary.py:282-288](../../backend/factual_machine_summary.py)).
- Historical superlatives/"first" claims and construction totals have a
  stronger gate. The code accepts either a cited tier `"1"`/`"2"` source or
  two distinct citation hostnames; otherwise it marks the sentence
  uncorroborated and blocks it before independent review
  ([factual_machine_summary.py:186-191](../../backend/factual_machine_summary.py),
  [factual_machine_summary.py:273-296](../../backend/factual_machine_summary.py)).
- The independent reviewer receives locked provenance plus up to eight ranked
  alternatives. Its requested decision is boolean `passed` plus issues and
  exact rejected sentences; its prompt defines a contradiction as statements
  that cannot both be true, constrains rejection to unsupported claims or
  direct same-subject/same-configuration contradictions, and treats category
  qualifiers and distinct milestones as compatible where stated
  ([factual_machine_summary.py:445-482](../../backend/factual_machine_summary.py)).
- A malformed review, `passed: false`, or any nonempty review issue fails the
  result. A passing result requires valid mechanical checks plus a review
  response whose `passed` is true and whose issues list is empty
  ([factual_machine_summary.py:498-610](../../backend/factual_machine_summary.py)).

## Bounded recovery and final factual gate

- Generation makes at most two writer attempts. The writer uses temperature
  `0.1`; the reviewer uses `0.0`. On the final attempt only, an independently
  rejected set of exact full sentences may be removed once and the remaining
  paragraph is re-reviewed. A similar removal applies to optional
  uncorroborated record/count sentences only when at least one mapped sentence
  remains
  ([factual_machine_summary.py:498-600](../../backend/factual_machine_summary.py),
  [factual_machine_summary.py:613-667](../../backend/factual_machine_summary.py)).
- A factual script is ready only when every roster item has `passed is True`,
  prose, the factual contract, current review-context version, exact title
  context, matching scene number, and a source-package SHA-256 fingerprint.
  Failed summaries are checkpointed but not saved as scripts; only an all-roster
  readiness readback can advance to voice
  ([factual_machine_pipeline.py:22-48](../../backend/factual_machine_pipeline.py),
  [factual_machine_pipeline.py:195-211](../../backend/factual_machine_pipeline.py),
  [factual_machine_pipeline.py:251-265](../../backend/factual_machine_pipeline.py)).

## Related legacy DVsU gate and adaptive repair (separate contract)

- `pipeline_executor._research_card_contract_warnings` dispatches a
  `machine_research_contract == "factual_100_v1"` card directly to
  `factual_card_contract_warnings`; its legacy Anton/DVsU checks therefore do
  not apply to factual_100_v1 cards. For other cards, it performs legacy field,
  evidence, deliberately-bare, designed-vs-used, verified-package, and required
  Anton-slot checks. Tier-only evidence is advisory because
  `_blocking_warnings` removes advisory-prefixed messages before pass/fail
  decisions
  ([pipeline_executor.py:424-429](../../backend/pipeline_executor.py),
  [pipeline_executor.py:4206-4222](../../backend/pipeline_executor.py),
  [pipeline_executor.py:4260-4309](../../backend/pipeline_executor.py)).
- The legacy DVsU path is adaptive, but its action selection is a deterministic
  policy rather than probability updating: estimated action costs are
  promote/rekind `$0.00`, select/mark-bare `$0.01`, targeted fetch/rewrite
  `$0.02`, and full rerun `$0.60`. The classifier orders free promotion and
  structural repair before targeted fetch and last-resort rerun
  ([pipeline_executor.py:4403-4420](../../backend/pipeline_executor.py),
  [pipeline_executor.py:5328-5379](../../backend/pipeline_executor.py)).
- For a missing designed-vs-used use-story, the legacy classifier fetches
  reality/service evidence once; only after the package records that hunt does
  it propose `mark_bare`. The tag is valid only with a `gap_hunt_summary` of at
  least eight spoken words, so it is not an unconditional bypass
  ([pipeline_executor.py:5477-5494](../../backend/pipeline_executor.py),
  [pipeline_executor.py:3057-3075](../../backend/pipeline_executor.py)).
- `repair_machine_auto` rechecks the card after each selected action, permits a
  maximum of four actions by default, defaults to a `$1.00` estimated-spend
  cap, skips full rerun unless explicitly allowed, and returns `needs_review`
  when blocking warnings remain. This is existing bounded adaptation; runtime
  provider outcomes and real spend are outside this source-only audit
  ([pipeline_executor.py:12112-12213](../../backend/pipeline_executor.py)).

## Representative test assertions (inspected, not executed)

- An invented `18` aircraft claim against a cited `15` fails mechanical numeric
  validation without a review call
  ([test_factual_machine_summary.py:89-100](../../backend/tests/test_factual_machine_summary.py)).
- A wrong-machine attribution is rejected after the independent review and
  consumes the bounded two writer/two review calls
  ([test_factual_machine_summary.py:68-86](../../backend/tests/test_factual_machine_summary.py)).
- A tier-3 record or construction-count claim fails corroboration without a
  reviewer call; two excerpts pass that gate only when their hostnames differ
  ([test_factual_machine_summary.py:422-454](../../backend/tests/test_factual_machine_summary.py)).
- Optional disputed-count removal preserves the supported sentence and
  re-reviews it; removing the sole sentence cannot produce a pass
  ([test_factual_machine_summary.py:479-504](../../backend/tests/test_factual_machine_summary.py)).
- A rejected factual summary is checkpointed but never saved as script, and a
  stale review/title context prevents readiness from releasing voice
  ([test_factual_machine_pipeline.py:66-72](../../backend/tests/functional/test_factual_machine_pipeline.py),
  [test_factual_machine_pipeline.py:112-125](../../backend/tests/functional/test_factual_machine_pipeline.py),
  [test_factual_machine_pipeline.py:171-184](../../backend/tests/functional/test_factual_machine_pipeline.py)).
- Factual_100_v1 cards dispatch through the factual card contract and reject a
  mutated claimed excerpt; legacy repair tests assert a free promotion outranks
  paid repairs, and a deliberately-bare card needs a substantive hunt summary
  ([test_factual_machine_research.py:62-91](../../backend/tests/functional/test_factual_machine_research.py),
  [test_roster_orchestrator.py:138-172](../../backend/tests/test_roster_orchestrator.py),
  [test_machine_documentary_hold.py:10347-10364](../../backend/tests/test_machine_documentary_hold.py)).

## Limits observed from code

`passed` is a gated boolean outcome, not an estimated probability of truth.
The factual_100_v1 categorical `high` segment label, overlap ranking, model
temperatures, and two-attempt limit do not supply calibration evidence or
measured error rates. The separate legacy DVsU repair ladder is adaptive and
cost-bounded, but it also does not calculate calibrated truth probabilities.
The independent reviewer is model-mediated; its prompt and the surrounding
mechanical gates are observable, while its runtime factual judgment is not
deterministically derivable from these files.
