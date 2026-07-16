# HANDOFF - 2026-07-17 PLAN->WRITE->EDIT shipped: writer restructured, 5/23 pass, B-24 fixed

## State
- Prod: cec7bc6d deployed, healthy. Six deploys this session (51daa8df writer
  prompts/plan flag, e5d91977 repair mechanics, 4270bd22 citation hygiene,
  80212c88 designation/abbreviation laws, 37d81ce4 token cap, cec7bc6d
  number floor).
- Branch: main - clean except this wrap and untracked storyengine/.claude/.
- **XB-15, B-17, and B-52 previews ALL PASS the full frozen law + Anton
  quality audit** (4/23 with the XB-19 control). Verified live on prod.

## PLAN -> WRITE -> EDIT (prod @ 5c15a380) - the writer restructure that stuck
Root cause of the oscillation named and fixed: ONE prompt was doing three
jobs (choosing facts, writing prose, keeping the citation ledger) under
~35 laws, dropping a different one per roll. Now:
- CODE picks the facts: _deterministic_beat_plan assigns each beat its
  slot + supports, names the twist source and the MANDATORY numbers
  (spec -> sentence 2, production count -> sentence 4).
- The model ONLY writes: small schema {thesis, twist, sentences[5]},
  ~14 voice rules, evidence inline under each sentence.
- CODE keeps the ledger: _derive_claim_ledger backs sentence N whole
  with beat N's ids; model claim maps are discarded.
- EDIT loop replaces the re-roll: same draft back with only the
  violations, up to 2 minimal rounds.
PROOF: B-24 (five straight failures on the old flow) PASSED FIRST ROLL,
richest paragraph the system has produced (contract number, Davis wing,
3,700-mile range, 18,500+ built in beat 4, number-free closer). B-17
regression: PASSED at 142 words, strictly richer than its old 102-word
pass. Zero gate edits; flow tests rewritten to the new contract;
suite 725.

## Shared checklist shipped (the 'once and for all' build, prod @ 450bc990)
Research and the script audit now grade by ONE checklist:
- _script_starvation_gaps predicts the frozen benchmark_cadence audit
  card-side (same vocab regexes, extracted to shared constants).
- _script_starvation_promote_actions plans FREE promotes from the package
  (support kinds only - never overwrites actual_outcome, bypasses the
  hint gate; plural 'B-17s' correctly reads as the locked machine).
- Wired: Repair ladder returns starvation promotes for referee-clean
  cards; single-machine preview SELF-HEALS before writing; readiness
  reports script_audit_gaps. 3 lock tests; suite 721.
- Also: COVERAGE LAW + production-count-home + under-length nudge in both
  prompts (prompt-vs-gate gaps five and six this pass).

## B-24 end-to-end proof: research automation PERFECT, writer oscillates
Fresh one-machine research -> auto Repair (2 free verbs) -> VERIFIED with
zero hand-editing. That whole leg is proven. The writer pass did NOT
converge in 5 rolls (~$0.50): each roll violated a DIFFERENT law
(count-in-closer x3 -> count dropped -> invented 'January' + decor +
semicolon). Two permanent laws came out of it. Do NOT keep re-rolling:
RESOLVED by the PLAN->WRITE->EDIT restructure above - B-24 passes.

## RESOLVED late night: key topped up; 3/3 PASS
After credits landed, B-52 passed on its first roll. B-17 took three more
surgical fixes (all deployed, prod @ cec7bc6d):
- B-17's requirement/tradeoff statements were hint-locked in the
  engineering_decision slot; promoted S9-E3 (original_problem) + S2-E10
  (tradeoff) + S2-E6/S2-E7/S10-E5 (production count, loss figure, spec
  numbers) - all FREE promote_excerpt calls.
- Designation + no-acronym-expansion laws added to the inventory prompts
  (gate existed, prompt did not - contract triangle gap).
- distiller max_tokens 950 -> 1500 (enriched plan truncated the bundle
  JSON mid-parse).
- NUMBER FLOOR added to both prompts (benchmark_cadence demands >=2
  claim-mapped numbers; the prompt only ever said to limit numbers -
  third triangle gap this pass).
Final paragraphs: XB-15 (transport twist, hedged spec block), B-52
("Built for nuclear deterrence, it outlasted the mission."), B-17
(guns/bomb-load spec, 12,700+ built, 4,700 lost, "Heavy guns bought
survival, not victory.").

## What shipped (all prompt/plan/repair-side, LAW FREEZE intact - zero gate edits)
1. Twist flag: _machine_story_plan flags conversion-signal evidence
   (carries_conversion_signal, contract.conversion_signal_evidence_ids ranked
   role-nouns-first); both distiller prompts make the first flagged id the
   mandatory reality-beat + twist source. All 3 machines now write the real
   designed-vs-used story (XB-15 finally tells the transport twist).
2. SPEC LAW in both prompts: single-source numbers HEDGED, never dropped;
   spec block + production reality keep real numbers.
3. Repair mechanics (deterministic last mile in
   _repair_machine_story_bundle_mechanics / _soften_single_source_span):
   - per-number two-source grading vs ALL locked evidence + "roughly" hedging
     (covers spelled numbers the old digit-only softener skipped);
   - spelled years/decades -> digits ("nineteen thirties" -> 1930s);
   - "Model 299"-class numbers are names, never hedged;
   - citation hygiene: wrong-required-slot ids dropped from a sentence that
     already carries its expected slot (killed the formula-order blocker);
   - determiner-guarded "first" -> "early" (high-risk single-source blocker).
4. XB-15 research: promoted S3-E10 + S4-E5 as scale_specs_context (FREE, via
   machine-repair verb=promote_excerpt) so the writer has a wingspan; skipped
   S6-E9 deliberately - its Span/Length values are swapped (149' is length
   there; do NOT promote it as spec evidence).
- Tests: 10 new locks; suite 718 pass / same 16+1 pre-existing fails.

## Next action (start here cold)
1. The batch: B-24 + XB-39 repair ("Repair All" then Run Research per card),
   then 17 machines' first research runs, then their script cards. The
   proven recipe per machine: research VERIFIED -> preview roll -> if the
   audit flags a missing beat/number, promote the package excerpt that
   carries it (FREE) -> one more roll.
2. Rubric fine-tuning stays optional, laws stay frozen: XB-15 beat 1 lacks
   the year and beat 3 lacks "only one was built"; B-52 could carry its
   wingspan/production numbers. All facts sit in evidence - one-line prompt
   nudge or re-roll later if Anton fidelity demands it.

## Gotchas learned this session
- Browser pane screenshots sometimes capture OFFSET (black band on top);
  coordinates read off those MISS. Reliable loop: read_page -> scroll_to(ref)
  -> click(ref) immediately, verify via javascript_tool DOM probe (not
  screenshot). Details in memory browser-pane-click-space-gotcha.
- machine-repair accepts explicit verbs: promote_excerpt with excerpt_id +
  kind is free and needs no paid confirm - the sanctioned way to hand a card
  a package excerpt.
- The preview "passed" flag needs the quality AUDIT too, not just empty
  blocking warnings (benchmark_cadence demands scale vocab in the
  engineering_decision spans specifically).
- Softener/gate divergence was the systemic bug class: the gate grades per
  number plan-wide, mechanics graded per row citation. Aligned now; if a new
  "needs two sources or a hedge" class appears, check mechanics mirrors the
  gate before touching prompts.

## Open threads (carried)
- B-24 + XB-39 needs_repair; 17 machines no first research run.
- Dashboard est-spend counts only orchestrator clicks, not previews.
- VPS password rotation still owed.
- ui/modal.tsx invisible-backdrop bug (chip filed earlier, still open).
