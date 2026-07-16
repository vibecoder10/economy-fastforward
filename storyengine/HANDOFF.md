# HANDOFF - 2026-07-16 (late night) WRITER PASS 5 DONE: 3/3 previews PASS (XB-15, B-17, B-52)

## State
- Prod: cec7bc6d deployed, healthy. Six deploys this session (51daa8df writer
  prompts/plan flag, e5d91977 repair mechanics, 4270bd22 citation hygiene,
  80212c88 designation/abbreviation laws, 37d81ce4 token cap, cec7bc6d
  number floor).
- Branch: main - clean except this wrap and untracked storyengine/.claude/.
- **XB-15, B-17, and B-52 previews ALL PASS the full frozen law + Anton
  quality audit** (4/23 with the XB-19 control). Verified live on prod.

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
