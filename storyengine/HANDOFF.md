# HANDOFF - 2026-07-16 (evening) Orchestrator shipped; research half done; the writer is the last boss

## State
- Prod: 35bb428f deployed, healthy (se.sh health verified). No lock, 0 active tasks.
- Branch: main - clean except GOAL.md/HANDOFF.md (this wrap) and untracked storyengine/.claude/.
- What shipped this session:
  - Roster orchestrator, 5 surgical verbs cheapest-first in pipeline_executor.py:
    promote_excerpt + rekind_segments (FREE, deterministic), targeted_fetch
    (APPEND-ONLY, focus=tier/reality/slot:<role>), rewrite_field (fed NORMALIZED
    post-clamp evidence), mark_bare. Full re-run last resort only.
  - Endpoints: POST /api/pipeline/machine-repair/{id} (verb=auto ladder),
    POST /roster-orchestrate/{id} (background walk, budget cap), GET /roster-dashboard/{id}.
    Research tab: per-card Repair + "Repair All (Orchestrator)". Confirm modals live.
  - XB-15 refusal trap ROOT-CAUSED + FIXED: _format_verified_machine_source_package hid
    excerpts carrying cross-designations (XC-105) while the gap gate ordered the model to
    select exactly those rows. Enforced signal rows now shown.
  - Tests: 31 new locks (tests/test_roster_orchestrator.py); suite 710 pass / same 16+1 pre-existing fails.
- PROOF: XB-15, B-17, B-52 all VERIFIED via Repair clicks in the live UI (~$0.10, zero re-runs).
  Board 4/23 ready. B-17's single click auto-ran rekind -> slot fetch (+30 excerpts) -> rekind.
- Previews under full law: 0/3 passed. XB-19's stored preview still passes (control).
  Spend: ~$4.50 of the $20/video cap.

## Next action (start here cold): FIX THE WRITER (fifth and final pass - fix causes, not symptoms)
The research system is done; every preview failure is writer-side. Two systemic causes, both
prompt/plan-side (LAW FREEZE holds - do not add or change gates):
1. TWIST-BLIND WRITER: XB-15's card carries the transport story (segment EP-S6-E7: eight years,
   5,200 passengers, 440,000 lb cargo) but the writer wrote Wright Field acceptance and skipped
   beat 4. Fix: _machine_story_plan (pipeline_executor.py ~line 2100) must FLAG which reality
   segment carries the conversion signal (_package_conversion_signals already computes it) and
   the distiller prompt in _run_static_script_hold (~8200) must treat it as the mandatory
   designed-vs-used beat source.
2. DUAL-SOURCE LAW STARVES BEATS 2-3: writer OMITS single-source exact numbers instead of
   HEDGING them (the law already allows a hedge). All 3 previews shipped with no wingspan/
   engine/production numbers - an automatic Anton rubric fail. Fix: distiller prompt must say
   "hedge single-source numbers, never drop the spec block"; optionally add targeted_fetch
   focus="spec" to fetch duplicate numeric support.
Verify: rerun the 3 previews from the Script tab (paid confirm), judge vs
notes/dvsu-paragraph-rubric.md. Done = 3/3 preview passes that also pass the 6-beat rubric.
Read memory storyengine-dvsu-writer-gap first; per-preview warnings are in
research_payload.machine_script_previews.<KEY>.warnings (se.sh db).

## Open threads
- B-24 + XB-39 sit needs_repair (untested against the ladder); 17 machines have no first
  research run. Batch AFTER the writer passes: "Repair All" then Run Research per card.
- Dashboard est-spend counts only orchestrator clicks, not previews - estimate, not a meter.
- "ten-man crew" single-source blocker on XB-15: S6-E9 (pacificwrecks) carries "Crew Ten" as a
  second source; a promote as scale_specs_context would dual-source it if the writer pass
  doesn't make hedging cover it.
- VPS password rotation still owed (carried).

## Gotchas learned this session
- Browser pane: resizing the viewport bigger than the pane breaks click translation silently -
  clicks land nowhere. Keep 811x898 and scroll; take a fresh screenshot before coordinate clicks.
- rewrite_field must see NORMALIZED evidence: raw claims can carry words their excerpts lack
  (XB-15's calendar-page "October") and the LLM will faithfully keep the ungrounded word forever.
- Conversion-signal scan has false positives: XB-15's "redesignated XB-15 in July 1936" (design-
  phase renaming) is vocabulary-matched as a conversion. Promote satisfied the gate; harmless
  here, but signal ranking should prefer excerpts with role words (cargo/transport) over bare
  "redesignated" when the writer pass starts consuming signal flags.
- A deploy mid-page-load shows a cosmetic 502 "Failed to load video" - just reload.
