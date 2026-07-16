# HANDOFF - 2026-07-16 (night) Writer pass 5 shipped; XB-15 PASSES; key out of credits

## State
- Prod: 4270bd22 deployed, healthy. Three deploys this session (51daa8df writer
  prompts/plan flag, e5d91977 repair mechanics, 4270bd22 citation hygiene).
- Branch: main - clean except this wrap and untracked storyengine/.claude/.
- **XB-15 preview PASSES the full frozen law + Anton quality audit** (green
  SCRIPT TEST PASSED in the UI, 2/23 with the XB-19 control). Verified live.
- B-17/B-52: reran twice, each round strictly better; final blockers are FIXED
  in 4270bd22 but the proof rerun is BLOCKED (below).

## BLOCKER (Ryan): DvsU tenant Anthropic key is OUT OF CREDITS
machine-script-preview returns 400 "Your Anthropic/Claude key is out of
credits" (hit right after XB-15's pass). Add credits or swap the key
(Settings -> API Keys for the Designed vs Used tenant), then just click
Rerun Script on B-17 and B-52 in the Script tab. Expected: both pass - their
last blockers were exactly what 4270bd22 fixes (see below).

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
1. Confirm Ryan topped up the tenant key.
2. Rerun B-17 + B-52 previews from the Script tab (paid confirm ~cents).
3. Judge vs notes/dvsu-paragraph-rubric.md. XB-15's passed paragraph is 5/6
   beats: beat 1 lacks the year, beat 3 lacks "only one was built" - both
   facts are in evidence; tune by re-roll or a one-line prompt nudge later,
   do not reopen laws.
4. Then the batch: B-24 + XB-39 repair, 17 machines' first research runs.

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
