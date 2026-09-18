# Active — Replace DVSU research + script-writing logic with the new deterministic pipeline

Outcome: the entire pre-image DVSU content chain (roster discovery, source discovery, claim
assessment, research briefing, script writing/compilation) is torn out and replaced by the
3-call deterministic pipeline designed and prototyped 2026-09-18 (thesis+acts / roster+shared-
context / per-machine 6-question research packet with 6 targeted searches, primary sources
preferred over Wikipedia). Image selection (`static_docu.py`, `reference_selection.py`) is
explicitly OUT of scope - stays exactly as-is, untouched. The existing frontend UI and API
contract stay unchanged; it becomes the display shell for runs of the new logic.

Done when: `research/agent.py`'s roster logic, `factual_source_search.py`, `research_claim_assessment.py`,
`factual_machine_summary.py` (both research and script paths), `script_research_packet.py`, and
`dvsu_script_brief.py` no longer drive production - their call sites in `pipeline_executor.py`
point at new modules implementing the 3-call design - AND the existing UI/API surface for
Research/Script stages still works unchanged against the new backend, verified live in the
browser per this project's "run it like a user" rule.

Status: BOTH designs approved 2026-09-18, all open questions resolved. Research:
`docs/dvsu-research-pipeline-v2-2026-09-18/DESIGN.md`. Script-writing:
`docs/dvsu-script-pipeline-v2-2026-09-18/DESIGN.md`. Storage for both: reuse the existing
`research_payload` field already on the video row (no new DB schema) plus a Drive export mirroring
the hand-prototype. "Other sessions cracked the code" = the SYSTEM PROMPTS from the hand-prototype
sessions (now in both DESIGN.md files), not hidden software - confirmed by Ryan. The OLD pipeline
has real live state: 20/20 roster, 20/20 images, 20/20 research summaries, 1/20 scripts (Holland) -
untouched.

**Ryan's confirmed scope, with sequencing added 2026-09-18 (this session):** replace everything up
to image generation and voice (roster, research, script-writing). Gather Images/image generation/
voice/render/upload stay untouched. **BUT build and verify in two phases, per Ryan's explicit
instruction: "worry about gathering the information cheaply first, then worry about how we compile
the information in the script-writing stage."** Phase 1 (current focus) = Calls 1-3 only (thesis+
acts, roster+shared-context, per-machine research packet) - get this working and verified end-to-
end before touching script-writing wiring at all, even though the script design is already
approved. Phase 2 (later) = Call 4 (script paragraph) wiring.

**Isolated worktree ready:** `/Users/ryanayler/AgentVault/Projects/story-engine/.worktrees/
dvsu-pipeline-v2` (branch `feature/dvsu-pipeline-v2`, created off main at `140b7921`). `.worktrees/`
is gitignored (commit `140b7921`). No code written in it yet - next session should
`change_directory` there before writing anything, then fold back to main only when deploy-ready
per this project's worktree convention (root CLAUDE.md). Do NOT `cd` past the worktree root when
running shell commands from it - going to the parent resets the session's granted directory back to
the main checkout (happened once this session).

**Exact wiring facts from two read-only trace agents this session (full detail in HANDOFF.md, this
is the condensed version needed to implement):**
- Roster call site: `run_roster_selection` (`storyengine/backend/pipeline_executor.py:11008-11200`)
  currently calls `research.agent.run_research(anthropic_client, topic, context, record_id,
  selection_settings, checkpoint_scope)` (skills/video-pipeline/research/agent.py) and merges only
  an allow-listed key set into `research_payload`. **Do not delete `research/agent.py` - it's
  shared with the separate Airtable-driven orchestrator pipeline** (discovery/bot.py, script/run.py,
  orchestrator/*.py all import it). Only remove the one call site inside `run_roster_selection`.
- Gather Images (untouched) reads the roster via `_machine_documentary_hold_roster_entries`
  (`pipeline_executor.py:7980+`), needs `research_payload.unit_roster` as a list of dicts with
  `name`/`title` (+ optional `designation`/`code`/`member_units`), plus one "machine marker" true -
  simplest is keeping `research_payload.roster_selection = {"version":1,"settings":{...}}`
  (`roster_selection.is_runtime_selection`, `roster_selection.py:132-134`) even though the old
  pacing/target-count logic itself is dropped. `act_number` not required by Gather Images itself,
  but final `unit_roster` list order should still be act-order/chronological per DESIGN.md.
- Research call site: `_run_unit_research_hold` (`pipeline_executor.py:13030-13489+`), only inside
  the `is_factual_machine_contract(payload)` branch (`factual_machine_research.py:15`, checks
  `machine_script_contract == "factual_100_v1"`). **Confirmed via `se db` query that the live DVSU
  video (`44dbf2b2-a27a-47ea-a608-4c31c906be9a`, "US Submarine Class Evolution") IS on this
  contract** - this is the right branch. A sibling non-factual legacy branch in the same function
  serves other tenants - do not touch it.
- Shape mismatch to bridge with an adapter (not a frontend change): `ResearchTab.tsx` reads
  `unit_research_cards[].evidence_segments[]` with `kind` in 4 legacy slots
  (original_problem/engineering_decision/tradeoff/reality) plus a `research_summary` object
  (paragraph/word_count/passed/warnings/claim_map/sources). The new 6-slot packet
  (problem/design/trade_off/outcome_candidates/surprising_fact/contrast) does not match 1:1 -
  write the new module clean per DESIGN.md, then translate into these exact legacy field names at
  the boundary. Suggested mapping: problem→original_problem, design→engineering_decision,
  trade_off→tradeoff, contrast→reality, surprising_fact stays its own slot.
- `backend/roster_selection.py` and `backend/roster_coverage.py` have other consumers
  (actions.py, production_guide.py, worker.py) - do not delete either file; only stop calling
  `roster_coverage`'s old independent-audit/repair-loop (the design explicitly drops this - "no
  separate roster-validation pass by design") from the new roster code.
- Before deleting any other old DVSU-only module (`factual_source_search.py`,
  `research_claim_assessment.py`, `factual_machine_summary.py`'s research path,
  `script_research_packet.py`, `dvsu_script_brief.py`, `dvsu_research_handoff.py`,
  `class_context_assessment.py`, `factual_class_context.py`, `contextual_source_identity.py`,
  `factual_machine_pipeline.py`, `factual_machine_research.py`): re-grep for importers AFTER
  rewiring Phase 1's call sites; delete only files left with zero remaining consumers.
- Script-writing call chain (`_run_static_script_hold`, `pipeline_executor.py:14770`) was traced by
  a second agent this session for Phase 2 prep, but its result lives only in the session that ran
  it and was not folded back before the handoff - redo that trace (or read
  `pipeline_executor.py:14770` onward directly) when Phase 2 actually starts.

Boundaries: Gather Images/image-selection code (`static_docu.py`, `reference_selection.py`) is
explicitly out of scope - do not modify; only make sure the new roster shape is compatible with
what it reads. Image generation, voice, render, upload: also untouched. Preserve all existing
evidence, accepted previews/assets, the old pipeline's live 20/20 state, and unrelated dirty work
already in the tree (see `git status` - large amount of untracked task/docs output from other
sessions' work). Deployment and any paid canary require separate explicit approval, per standing
project practice.

**Phase 1 implemented 2026-09-18 (cloud session, no local Mac worktree in that environment — built
directly on `main-khm80l`, pushed).** `storyengine/backend/dvsu_roster_v2.py` (Call 1+2, commit
`a4fd6f5`) and `storyengine/backend/dvsu_research_v2.py` (Call 3 + legacy adapter, commit
`65545d8`) are wired in, gated behind `is_factual_machine_contract`. Verified at unit/code-trace
level only (5474 passing, zero regressions vs. baseline; adapter proven against the real legacy
gate functions across 5 identity formats) — **no live model/search call or browser run has
happened yet**, this cloud sandbox has no VPS/SSH route. Live verification recipe (roster+research
run on the real submarine video, browser walk, no-spend-skip proof) is queued at
`tasks/live-verification-queue.md`, "DVSU research pipeline v2 — Phase 1" section — run that next,
on a VPS-capable session, before calling Phase 1 done. One known cosmetic wrinkle carried over
from Phase 1b: `evidence_segments[].source_excerpt` carries a `"Regarding <machine>: "` bookkeeping
prefix ahead of the real quote (documented in `dvsu_research_v2.py::_candidate_text`) — harmless to
gate-passing, worth Ryan's eyes if it looks odd in the UI.

Always next: run the live-verification-queue.md recipe above; once Ryan accepts Phase 1's live
results, start Phase 2 (script-writing, Call 4) per `docs/dvsu-script-pipeline-v2-2026-09-18/DESIGN.md`.

Market: Ryan/editor; hypothesis is completing saved project without developer intervention; distribution is existing private StoryEngine UI; real test counts manual interventions and rejected sections. Build/Market/Operate tracked on SE-0002.

## Historical evidence (superseded active status)

### Superseded 2026-09-18 — DVSU Run All reliability, evidence-led writing
Outcome: current submarine video becomes a reviewed playable MP4. Done when: offline reliability checks pass, authorized live pipeline produces verified media and Ryan accepts viewing/listening.

Status: deployed as 0229e9fb (fce298f8 core + verified UI correction). Both migrations applied; backend/worker parity, matching hashes, health and live UI verified. S1 no-spend readiness passes with no warnings. No paid operation created. Evidence: docs/dvsu-run-all-reliability/deployment.json. Paid canary/media/human acceptance remain open.

Boundaries: preserve all existing evidence, accepted previews/assets and unrelated dirty work. Local/offline repair authorized. Deployment and paid canary require separate approval. No upload.

Research receipt: 2026-09-17 live failed job 8463d9d7-3da0-4ce8-a539-61bbad7595e9 and saved SS105 package; missing editorial role triggered source search despite 12 supported claims. Consumed in writing step: Ryan selected evidence-led 80–110-word narration; narrative categories optional.

Always next (superseded — replaced by the rip-and-replace outcome above): obtain separate approval for one S1 saved-evidence writing canary, ceiling $1.50; zero discovery, no production promotion, voice, images, render or upload. Runtime backend/worker use direct Anthropic Opus4.5. Completed canary must pass actual prose/citation review before expansion.

Superseded because: Ryan decided 2026-09-18 the underlying research/script logic itself is wrong and should be replaced wholesale, not incrementally repaired further.


## Latest status — Holland paid test stopped before writing
Authorized Holland-only canary ran one research repair and STOPPED at readiness; no paid script preview. Source archive grew1->3sources and2->8excerpts; original sources/quotes, other19packages,roster,video status and production script hashes unchanged. Missing actual_use remains; two Navy fetches failed SSL certificate validation. New facts describe design/licensing, not operational service. Assessor also mislabels first-submarine identity as intended role; no claim of DVSU quality restored. One-machine response hides target warnings via units[-1]; readiness returns actual Holland gap. Evidence docs/dvsu-brief-2026-09-16/canary-result.json. Next: source capture/targeted extraction repair from captured data, no more paid calls this test.

## Latest status — DVSU code deployed; paid writing verification pending
Compact DVSU brief/code deployed cc9ee724b at23:19:24UTC. Terra compiler/writer + Astra integration/review round1 PASS:122 backend tests,7frontend tests,production build. Live served frontend editorial gate, exact source hashes/release,3active services,worker parity,healthy API,normal drain,lockclear. Holland no-spend readiness now correctly rejects missing intended_role/actual_use/outcome before writing. Production script/validation/scene hashes unchanged. Saved20 replay has missing fields on every old package; brief48–233words. Evidence docs/dvsu-brief-2026-09-16/deployment.json. NOT complete writing acceptance: user popup pending for one paid Holland-only append research + preview; none started.
Always next: on popup approval, one Holland research repair, readiness, then one preview only if ready; inspect actual wording/citations/80–110 count and editorial/factual verdict. Do not repeat a failed paid loop or touch production scripts.

## Latest verified outcome — preview status corrected
Round1 Terra implementation/Astra review PASS. Fixed frontend review version5->6; regression reads actual UI/backend constants.6tests,production build and actual saved Holland preview replay pass. Release1857c383e deployed22:56:48UTC; publicly served JS checks version6; APIhealthy,frontend200,worker parity,drainnormal,lockclear. Saved preview and production script/validation hashes unchanged. No provider generation. Evidence docs/preview-review-version-2026-09-16/. Next: refresh existing Holland preview and review wording; do not regenerate just to clear stale UI warning.

## Latest verified outcome — preview label fix deployed
Preview label fix deployed as 7e6adc151 at22:44:23UTC. Terra round1 implementation and Astra review PASS;98tests. Exact live em-dash Holland label returns HTTP200 ready=true, canonical SS-1 USS Holland,scene1. Release/source hashes and active backend/worker verified; production status/script/validation/scene-row hashes unchanged. No paid generation. Evidence docs/preview-label-2026-09-16/review.json. Always next: refresh and retry Holland Preview; inspect generated narration before saving production script.

# Submarine terminology copy edit — 2026-09-17

Done when: submarine narration uses submarine/vessel terminology while the accepted Holland preview changes only the two user-requested nouns with original-review provenance preserved.

Evidence: release `58ca96c30` deploys the prompt rule and `notes/dvsu-quality-law.md` terminology convention; backend/worker are active, API healthy, frontend HTTP 200, drain normal and lock clear. `preview-terminology-copy-edit-receipt.json` records one CAS update of `machine_script_previews.SS1`: production hashes, roster (20), source packages, status, cost, pass flags, editorial receipt and warnings are unchanged; two support-audit rows retain `reviewed_sentence`. No provider call or production promotion occurred.

Always next: Ryan reviews the corrected Holland narration as part of the existing creative/listening acceptance gate.

# Final bounded Holland verification — 2026-09-17

Done when: one deployed Holland-only preview returns a technically valid and content-reviewed DVSU paragraph through the actual frontend wrapper, without changing the 20-machine production state beyond its preview receipt.

Evidence: `docs/dvsu-automatic-evidence-2026-09-16/canary-ui-editorial-response.json` records one POST HTTP 200 in 27.8 seconds and a 96-word/five-sentence result: `passed=true`, `factual_passed=true`, all six editorial checks true, five of five support-audit rows supported, no warnings, and a seven-word ending. `scope-audit-final.json` records a fresh database readback with only `research_payload.machine_script_previews.SS1` changed; roster, all 20 source packages, production status/cost/script hash/validation hash remain unchanged. `tests-editorial-sufficiency.log` has 101 backend passes; gateway recovery has 11 frontend test passes plus TypeScript/build receipts. Backend `7af5ab8ff` is live; frontend `6a590ed4` remains live with public asset proof.

Status: bounded technical/content proof PASS. Ryan creative/listening acceptance remains pending. This does not complete the full 20-machine roster script, publish, or promote production.

Always next: have Ryan review and accept or reject the actual Holland narration, then keep the remaining 19 machine scripts in their own scoped workflow.

# Current stage — Holland writing-contract restoration awaiting deployment (2026-09-17)

Local DVSU writer/referee restoration is review-passing: 100 backend checks, `PROMPT_RULES_VERSION=4`, 95–105 word target within the approved 80–110 hard range, an approximately five-sentence engineering-decision arc, and a non-truncating <=18-word final-verdict guard. Automatic source ingestion is complete locally; the compact brief is 176 fact words / 2,200 canonical JSON bytes. The previous 110-word Holland preview passed factual automation but remains creatively unaccepted. Nothing in this stage is deployed, provider-run, or production-promoted.

Always next: deploy the reviewed v4 contract through the approved release path, then run exactly one Holland preview and inspect both reviews, source support, actual narration, and Ryan’s creative acceptance. Gateway-only recovery is separately planned in `docs/dvsu-automatic-evidence-2026-09-16/PLAN.md`.

# Current outcome — bounded script compiler deployed (2026-09-16)

Ryan approved deployment. Release64ddf60de deployed22:32:37UTC through se.sh. Origin main and VPS checkout match; all three production module hashes equal tested source. Backend/worker active with restart/parity verified; public API healthy, frontend200, drain normal, lock clear,0active work.

Local DoD PASS:94tests;20/20real saved research packets deterministic; exact source quotes preserved; maximum packet31,554B, writer/referee conservative bounds33,861/39,466 with0overflows. Completed sections resume by source/rules/model/outline fingerprint. No paid provider call or script/voice/render/upload was started. Human narration/live generation acceptance remains open.

Exact plan and rounds: [PLAN.md](docs/script-compiler-2026-09-16/PLAN.md). Evidence: [deployment.json](docs/script-compiler-2026-09-16/deployment.json), deploy.log, production-readback.txt, review.json, final-tests.log and replay.json. All unrelated dirty work preserved; only six reviewed code/test files committed.

Always next: quote/authorize one representative script-only canary through normal workflow, inspect factual support/readability and usage, then consider full-episode rerun. Market checkpoint: DVSU editor/channel owner evaluates the real section. SE-0002 deployment done; full end-to-end narration acceptance remains open.

# Current outcome — named submarine research complete

2026-09-16: Terra implementation and Astra review delivered source-backed confidence/conflicts. Live API and browser confirm 20/20 exact named submarines, 20 verified photos, 20 current claim assessments and 20 passing saved summaries. Normal assembly returns all 20 briefings in roster order. Status Ready for Script; Approve Research enabled. Final backend release 582c1b97a, frontend 44b29cd96; services healthy. The final readiness refresh preserved every source package and summary with no cost increase. Histories 58/20 retained. Evidence: tasks/submarine-research-acceptance.json, live-validation.json, assembled-briefings.json and final-gate-deploy.log. No script/voice/render/upload started. Always next: review/approve Research, then Script. Market checkpoint: DVSU editor reviews source support and exclusions before script production.

# Current continuation — named submarine research live run

2026-09-16: Source-backed confidence and conflicts selected by Ryan. Terra implementation and Astra round 2 local review PASS: 106 backend tests, 8 frontend tests, production build. Deployed a3381755e; backend/worker parity and frontend health verified. Live Research shows all 20 canonical submarine names; image dashboard loaded 20/20 verified. One research-only request accepted at 21:00:36 UTC. Provider run is active; live completion not yet established. No script/render/upload requested. Evidence: tasks/submarine-research-review.json, deploy.log, request.json and progress.jsonl. Always next: inspect saved assessments and summaries through terminal state; preserve roster/photos.

# Current continuation: submarine image repair complete

Image repair complete2026-09-16 20:30UTC:20/20exact named submarine photos verified in live API and browser. Terra/medium implemented caption identity guard; Astra round1review passed48tests. Deployed b1f828c21 via se.sh with healthy worker parity. Saved-candidate recovery replaced only Plunger with c1 (caption USS Plunger in1902); other19sourceURLs unchanged. Accepted20roster, old58/20history and0active research cards preserved. Research/script not started. Evidence tasks/named-machine-image-acceptance.json, source-review.json, visual-review.json, caption-deploy.log. Always next:Research.

# Current outcome — named-machine roster rerun complete

Roster rerun complete2026-09-16 19:43UTC. Live API and browser:20/20selected and independently accepted; one named boat per20distinct classes; no range designations; Tang=USS Tang SS-563. Old58history and full old20payload+1compact research card archived and verified.21focused budget tests plus3archive tests; source audit budget scales12-40 (24here), deployed9919c0d5b with healthy worker parity. No subsequent stage run. Gather Images now correctly shows0/20fornewboatidentities. Always next: Gather Images for exact20boats, then Research. Evidence tasks/representative-roster-acceptance.json, representative-roster-final-db.txt, representative-roster-audit-deploy.log. Browser verified full named20list and green roster.

# Research summary deployment — 2026-09-16

Ryan approved deploy. Commit d8b010fd live at19:15:40UTC; backend healthy, worker parity confirmed, frontend200, drain normal and lock clear. Local/live browser Research inspector verified. Evidence: docs/research-summary-automation-2026-09-16/deploy.log and deployment.json. Existing20 roster/photos and legacy research remain; no paid generation started. Always next: authorize and run a research/script-only live canary, checking all20 saved summaries before script handoff. Full video DoD remains open.

# Current outcome — reliable machine research summaries for automated script assembly

Ryan correction 2026-09-16: the objective is name -> research -> saved summary for each machine -> agent-led script assembly, with automation continuing without repeated manual repairs. Confidence calibration is not the next task. Preserve locked roster20, gathered images20, completed research and unrelated edits.

Done when: local normal entrypoints produce and persist a source-backed summary per locked machine; bounded transient recovery and explicit actionable terminal errors; resume reuses completed units; script assembly consumes summaries. Local checks and live end-to-end proof must be reported separately. Current video:44dbf2b2-a27a-47ea-a608-4c31c906be9a; live contract factual_100_v1; research currently incomplete.

Astra diagnostic and plan-completeness gates PASS. Local implementation/review complete: A/B rounds1–3; C/D integration reviewed; Astra corrected one legacy test fixture. Evidence: docs/research-summary-automation-2026-09-16/REPORT.md, review.json, integration-tests.log (126 passed), D.md (frontend build passed), scoped release.patch. Concurrent roster and research-agent changes excluded. No provider generation or deployment. Browser acceptance, live20 summaries, script handoff, and full-video proof remain open.

Always next: approve scoped deployment under CLAUDE.md:19, verify changed UI and service health, then explicitly authorize a paid research/script-only live canary. Preserve existing roster/images and completed evidence. No voice/render/upload authority inferred.

# Current audit — DVSU probabilistic research (2026-09-16)

Outcome: code-backed research map, uncertainty gaps, prioritized solutions. DoD: three bounded Terra maps reviewed against code, final report with measurable next experiment. Scope: local read-only audit and documentation; no implementation or provider runs. Baseline: f92c863b550dcf5cd3a72e351d045b554ef8fdcf plus preserved unrelated dirty work.

Astra plan completeness PASS; round 1. Exact executable steps: [audit plan](docs/research-probability-audit-2026-09-16/plan.json). Status: audit complete; round 1 Astra review PASS. Evidence: docs/research-probability-audit-2026-09-16/REPORT.md and review.json; three Terra maps; offline synthetic conflicting-excerpts probe. No application implementation or production changes. Historical recommendation superseded by Ryan’s machine-summary automation correction above. This audit does not close the prior full Run All check.

# Current outcome — automatic image gathering complete

Done: normal Gather completed at2026-09-16 01:30:38UTC with20/20 source-checked, comparatively selected photos and zero missing slots. Live UI shows all20 and enables Research. Barracuda now shows the actual submarine rather than the distant tender group; Tang uses a clearer side profile. No manual photo URLs, class-specific overrides or forced readiness were used.

Release f92c863b5 is live, with healthy services, worker parity and normal drain.94 focused checks pass. Production Barracuda comparison automatically retried an incomplete response and succeeded. Final saved-evidence replay added zero model calls (checkpoint receipts identical before/after). Source citation normalization preserves exact ordered words/numbers and canonical source-page identity; invented quotes and different designations/files/queries remain rejected. Existing15 successful references, roster20, saved research card1 and original58-entry roster history preserved.

Evidence: tasks/image-automation-terminal-summary.json; image-automation-citation-tests.log; image-automation-citation-replay.json; image-automation-checkpoints-before-replay.jsonl and after-replay.jsonl; image-automation-citation-deploy.log. Browser verified20/20 and Barracuda photo, source links, score factors and limitations.

Astra plan/reviews: IMAGE-AUTOMATION-PLAN.md. Terra source rounds1–3 and provider rounds1–2; Astra owned integration, live interpretation and citation recovery. Image automation DoD passed. This is selection among retrieved candidates; archived photos retain visible resolution, waterline and configuration limitations. No whole-video completion claim.

Always next: continue detailed Research for the saved roster, then verify a separate representative roster through Roster → Gather → Research. No further research/render was initiated as part of this image-repair acceptance. SE-0002 image-gather and automation steps complete; earlier full Run All continuation remains an outstanding broader pipeline check.

# Previous outcome — initial new-rule sweep had five unresolved reviews

Live readback2026-09-16 00:43UTC: gather ended failed/needs_review with15/20 ready under the new rule.19/20 entries still have visible saved photos. The only blank is Barracuda(V-1):4candidate files found, but provider comparison was unreadable; no selected photo saved. Skipjack also returned unreadable comparison; Virginia returned malformed scores/reasons. S-class lost its only relevant candidate to minimum image size, and the remaining search results were unrelated. Tang's cached photo lacked a retrieved caption; alternatives were unrelated or the older SS-306 vessel. Saved previews were preserved for all four of these other unresolved entries.

Release659f0345 remains live.65backend checks plus UI/build checks and representative sample passed, but full-roster proof exposes unresolved structured-response and source-discovery quality problems. Do not call image gathering complete or force these entries ready. Roster20/card1/history58 preserved. Evidence: tasks/image-selection-terminal-summary.json and tasks/image-gather-live-latest.json.

Always next: capture/validate structured comparison responses and improve exact-entity source retrieval for these five entries; preserve successful15 and existing previews, and avoid a blind full sweep. Ryan's current question is diagnostic; no retry or production mutation performed this turn. SE-0002 stays active.

# Previous status — parsing recovery verified; roster quality still blocked

Deployed: 6e5944030, healthy worker parity, 2026-09-15 18:37UTC.
Verification: 24focused tests pass. Normal live correction hit max_tokens and automatically completed with end_turn, recovering7016additional characters. No manual retry between continuation responses.
Live result18:45UTC:58roster entries saved, factual gate failed, no script/render/upload. Original parser crash is repaired; end-to-end outcome is NOT achieved.
Remaining findings: duplicated Plunger/Adder class; missing or confused AA-1/T-class; mixed completed/unfinished member ranges in Tench/Virginia class entries. Findings are validator/audit output, not independently verified historical conclusions.
Next: correct the class-versus-member coverage repair path using the saved58-entry draft and exact findings, verify sources and rerun factual acceptance. Preserve quality gates and saved paid work; avoid another blind Run All retry.

---

# Previous attempt and repair evidence

# New-video roster recovery

Outcome: Run All recovers malformed research once and reports honest stage status.

Done when: Focused regressions pass; approved release advances affected video into saved roster or exposes an actionable actual blocker.

## step-1: Diagnose saved failure
- inputSource: Video 44dbf2b2-a27a-47ea-a608-4c31c906be9a; current research agent and stage rail
- action: Read exact video and worker error through se.sh; inspect research parser and stage indicator.
- writeBoundary: skills/video-pipeline/research/agent.py; backend/error_utils.py; StaticDocuStageRail.tsx; focused tests; CHECKLIST.md and JOURNAL
- expectedOutput: Focused patch, test receipt, production progress receipt in tasks/
- dependencies: User failure report
- acceptanceEvidence: Diagnose saved failure
- authorityStop: Local fixes authorized; deployment requires approval under project operating card; preserve unrelated work and paid results
- done: True
- evidence: Production task failed parsing research; saved payload contains only machine_script_contract.

## step-2: Repair malformed research handling
- inputSource: Video 44dbf2b2-a27a-47ea-a608-4c31c906be9a; current research agent and stage rail
- action: Add one same-response JSON formatting recovery in research/agent.py, useful error copy, and substantive research detection in stage rail; preserve dirty edits.
- writeBoundary: skills/video-pipeline/research/agent.py; backend/error_utils.py; StaticDocuStageRail.tsx; focused tests; CHECKLIST.md and JOURNAL
- expectedOutput: Focused patch, test receipt, production progress receipt in tasks/
- dependencies: Previous step
- acceptanceEvidence: Repair malformed research handling
- authorityStop: Local fixes authorized; deployment requires approval under project operating card; preserve unrelated work and paid results
- done: True
- evidence: Focused patch prepared; 12 regression tests, TypeScript and production build passed.

## step-3: Verify focused regressions
- inputSource: Video 44dbf2b2-a27a-47ea-a608-4c31c906be9a; current research agent and stage rail
- action: Test malformed response recovery, bounded repeated failure, valid response, wrong JSON shape, and metadata-only research indicator.
- writeBoundary: skills/video-pipeline/research/agent.py; backend/error_utils.py; StaticDocuStageRail.tsx; focused tests; CHECKLIST.md and JOURNAL
- expectedOutput: Focused patch, test receipt, production progress receipt in tasks/
- dependencies: Previous step
- acceptanceEvidence: Verify focused regressions
- authorityStop: Local fixes authorized; deployment requires approval under project operating card; preserve unrelated work and paid results
- done: True
- evidence: Focused patch prepared; 12 regression tests, TypeScript and production build passed.

## step-4: Deploy and verify affected video
- inputSource: Video 44dbf2b2-a27a-47ea-a608-4c31c906be9a; current research agent and stage rail
- action: After live deployment approval, release only scoped edits and resume the existing video within its approved generation settings; verify durable roster progress.
- writeBoundary: skills/video-pipeline/research/agent.py; backend/error_utils.py; StaticDocuStageRail.tsx; focused tests; CHECKLIST.md and JOURNAL
- expectedOutput: Focused patch, test receipt, production progress receipt in tasks/
- dependencies: Previous step
- acceptanceEvidence: Deploy and verify affected video
- authorityStop: Local fixes authorized; deployment requires approval under project operating card; preserve unrelated work and paid results
- done: False
- evidence: 

Verification: 10 backend tests and 2 frontend behavior tests pass; TypeScript and production build pass; git diff --check passes. Scoped release patch: tasks/submarine-roster-recovery.patch.

Status: local repair tested; deployment approved and verified at 6302489d0; existing video resumed once. Affected video now running under autobuild; roster not yet saved.
Next: verify actual saved roster progress and autonomous next-stage continuation.


## Live acceptance failed
At 17:54:18 UTC original response (49,847 chars) failed parsing; automatic formatting recovery failed at 17:57:59 UTC. No roster saved. Local test success did not establish production recovery. DoD NOT passed. No further retry authorized by this receipt.

Next: capture provider stop_reason and failed response safely, then design a bounded structured-output repair from actual evidence. Do not resubmit the same discovery blindly.

# Continuation: production response diagnosis and durable repair
User reauthorized repair on 2026-09-15, including existing deployment/resume authority. No repeated alignment needed. Prior local repair failed live acceptance.

## Round 1 plan completeness gate — Astra reviewed
1. Input: existing research agent/client, exact submarine video and tenant, live credentials through PipelineExecutor initialization. Action: one diagnostic discovery call via ResearchAgent with channel prompt; intercept SDK response, save request arguments and model_dump response to a private production tasks/submarine-diagnostic directory, stop before repair or database save. Files: tasks/submarine-diagnostic.py and private diagnostic files only. Output: response JSON and short stop_reason/size receipt. Dependency: no active run for this video. Acceptance: real response captured without secrets or second paid call. Authority: existing user-approved research repair; stop after one provider response, on provider/account error, or active work. Terra may choose ordinary script plumbing only.
2. Input: captured provider response plus current JSON parser. Action: Astra diagnoses exact parse failure locally, defines deterministic regression and bounded repair; no paid retry while analyzing. Files: checklist/journal only until repair plan is appended. Output: exact parse location, stop reason, reproducible fixture. Acceptance: reproduce failure from captured bytes and explain cause. Stop: no guessing or altering factual checks.
3. Implementation and deployment plan will be written from step 2 evidence before Terra executes. Acceptance remains live saved roster and autonomous next-stage continuation, not synthetic test success.

## Required regression evidence for the diagnosed repair
- Replay captured provider response locally; test must fail under old behavior and pass under repair without any network call.
- Finished valid JSON remains unchanged, including roster identities, source URLs and exclusion reasons.
- Truncated/paused/refused responses cannot be mistaken for a completed research brief.
- Any continuation/recovery has a finite bound; provider-account errors are not retried as formatting errors.
- Retained data is scoped to tenant/video/request so resumed work cannot reuse another video's draft or silently repeat a paid failed call.
- Existing factual coverage and saved-card reuse tests continue to pass.
- Live acceptance requires the same submarine video's roster to be saved and the next stage to start through normal Run All; no hand-written roster or direct quality-gate bypass.

## Evidence and Round 1 implementation plan — Astra complete
Captured `tasks/submarine-diagnostic/response.json` is a direct Sonnet 4.5 response, stop_reason=max_tokens, output_tokens=16524, 52659 text characters, eight searches. Its final JSON string is visibly cut mid-value. No payload fabrication or fuzzy JSON repair can recover missing bytes. Provider documentation https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons (2026-09-15) distinguishes max_tokens, pause_turn and end_turn.

### Execute bounded response continuation
- Input: captured request/response; shared/clients/anthropic_client.py generate; research/agent.py ResearchAgent and run_research.
- Action: add opt-in complete-response handling to generate, used by ResearchAgent for initial discovery and its existing single formatting recovery. Keep all other callers' behavior unchanged. Preserve raw provider response plus completion reason before parsing. Continue max_tokens using accumulated assistant response plus a user instruction to emit only the missing suffix without repeating text or searching again. Continue pause_turn with assistant content and unchanged tools. Accumulate text without inserting newline at a truncated JSON boundary. Never return incomplete data as complete. At most initial+3 continuation responses per fingerprint, including across resumes. Refusal/context exhaustion/unknown stop reasons stop with explicit saved-work message; do not catch/retry account errors as formatting errors.
- Durable state: private files (directory 0700/file0600, atomic replace) under storyengine/data/research-responses (env override for tests). Filename derived from tenant/video scope and full request fingerprint including prompt/context/system/model/tools; no secrets. Store each provider response and fingerprint, read on retries, reconstruct continuation from retained responses; complete response replays without new provider call. Never reuse a different tenant/video/request. No checkpoint if scope absent (standalone tests/calls still get bounded in-memory continuation).
- Wiring: run_research passes tenant (from airtable_client.tenant_id) plus record_id to ResearchAgent as optional checkpoint_scope. ResearchAgent builds per-request hashed paths and passes complete_response=True/checkpoint_path to real client, for both discovery and recovery. Ensure independent scope/fingerprint for repair. Preserve existing factual/coverage validators and card reuse paths. Ignore runtime checkpoint directory in Git.
- Files/write boundary: skills/video-pipeline/shared/clients/anthropic_client.py; new shared/research_response.py helper if useful; research/agent.py; backend/tests/test_research_format_recovery.py; new backend/tests/test_research_response_continuation.py; storyengine/.gitignore. No other code, no prompt taxonomy changes, no deploy/paid call by worker.
- Expected output: scoped implementation plus focused test receipt.
- Dependencies: diagnosis completed above; existing deployed 6302489d0 remains baseline.
- Acceptance: replay captured prefix with synthetic suffix proves old truncated failure and new complete JSON; two max_tokens pages assemble exact string; pause_turn retains tool blocks; terminal end_turn performs one call; completed checkpoint performs zero calls on resume; interrupted continuation resumes saved prefix without initial rediscovery; bound persists across resumes; fingerprint isolates tenant/video/prompt; malformed complete JSON still uses existing one repair; provider exceptions propagate; existing 10 format tests pass. Tests use fake SDK and temporary checkpoint dirs, no network or credentials. Do not commit raw capture.
- Authority/stop: local bounded implementation authorized; Terra ordinary helper names/plumbing allowed only. Missing material decisions return to Astra. Parent reviews before deploy. Existing user's deploy/resume approval persists. No change to primary model or other dirty files.

### Live protocol canary (parallel with local implementation; Astra-authorized)
Input: exact private captured request.json and response.json. Action: one SDK continuation of saved response: original user prompt, full assistant content, user instruction 'The previous response hit the output limit. Continue from exactly the last character. Return only the missing suffix, no repetition, commentary, markdown fences, or new research.' Remove tools for this max_tokens completion; keep model/max_tokens/system/temperature otherwise identical. Use initialized tenant client; save response to continuation-response.json before parsing; no DB mutation, no pipeline build. Output: raw response + stop_reason/token count. Acceptance: provider accepts retained server-tool history without new searches, resulting combined JSON parses. On error stop and report, no automatic canary retries. This is completion of retained diagnostic work, not fresh discovery. Scope: tasks/submarine-continuation-canary.py and private diagnostic files. Existing repair authority applies.

## Round 1 Astra review
Real captured two-response SDK replay passed: identical55-entry parsed data, zero calls on completed-checkpoint replay. Focused + existing resume suite:40passed/2failed; the same2 roster-loop fixture failures reproduce on isolated unchanged HEAD6302489d0 (14passed/2failed), so they predate this patch. No quality-gate code changed.

### Round 2 small review correction
Input: new continuation/checkpoint error strings and backend/error_utils.py. Action: change bound/terminal text to avoid promising resume when the bound is exhausted, and map tightly matched internal prefixes to clear safe user copy (limit: draft saved, review needed; unusable checkpoint: no new research started; provider incomplete/refusal: saved draft and reason category only). Files: shared/clients/anthropic_client.py, backend/error_utils.py, backend/tests/test_research_response_continuation.py or test_research_format_recovery.py. Expected: focused tests pass and raw provider details never exposed. Dependency: reviewed round1 implementation. Acceptance: known new failure cases humanize specifically; no infinite/repeated retries introduced. No other scope/paid calls/deploy by technician.

## Round 2 Astra review / Round 3 exact correction
21 focused tests passed. Review found checkpoint mismatch says 'does not match' rather than 'is', so error-copy prefix misses it; unknown provider stop names outside whitelist also need fixed safe fallback. Terra instruction: accept both checkpoint prefixes, add safe no-interpolation provider-stop fallback after known-category regex, add exact mismatch/tool_use raw-tail tests, run focused suite. Write boundary backend/error_utils.py and test_research_format_recovery.py only. No other scope. After this passing review, release bounded fix.

## Round3 Astra passing code review
23focused tests pass;actual captured replay passes with55entries and zero repeated calls. Two broader fixture failures reproduce baseline unchanged. Commit9a0480b4 pushed;safe deployment running. Live acceptance remains pending.

## Astra takeover — live streamed SDK compatibility
- Input: production400 messages.1.content.16.text.parsed_output; saved correction checkpoint f717278d with max_tokens and51490 retained characters.
- Action: remove SDK-only parsed_output and __json_buf from outgoing assistant block copies, including saved checkpoints; preserve full diagnostic checkpoint and legitimate tool inputs/citations.
- Boundary: anthropic_client.py, continuation regression test; then scoped commit/deploy under existing approval and one resume.
- Acceptance: SDK ParsedTextBlock replay omits forbidden field, retained checkpoint unchanged,23existing focused tests pass; live correction resumes saved response without rediscovery and reaches factual gate.
- Dependencies: third worker review completed; Astra handles precise live repair.
- Stop: preserve quality gates; no blind retries or unrelated changes.
# Corrected roster workflow — Astra plan-completeness gate passed
Outcome/DoD: 20 minute video at 1 minute/machine saves 20 real distinct title-fitting classes, completes Roster independently, then normal Run All starts detailed research on exactly that saved roster. Preserve old paid data and provider continuation. No exhaustive omission requirements in runtime selections.

> Superseded sequence, 2026-09-15: Ryan requires image gathering immediately after the accepted roster. Current order is Roster -> Gather images -> Research. Existing accepted roster and saved research remain reusable. Detailed executable plan: [IMAGE-GATHER-PLAN.md](IMAGE-GATHER-PLAN.md). Same feature card SE-0002; reviewed implementation committed and release/live verification below.

### Image gather review round 1 — changes requested

Parent independent acceptance suite: 11 passed (actual executor preservation/cache/partial/cancel/stale/save failure/direct research gate and real Run All ordering). Terra's TypeScript/build passed, but code review found status-only image counting, incomplete panel mode separation, stale copy, absent generic next-step dispatch, missing duration in guide gate input, and one-machine hold incorrectly accepted as complete research. Round 2 prescribed exact fixes and frontend regression tests. No deployment or live gather has run for this feature yet.

### Image gather rounds 2–3 and Astra takeover

Round 2 still failed panel separation, saved-research display and a direct background runner outside the plan. Round 3 corrected those; Astra finalized shared-watcher arming and truthful failed fallback state, and updated an obsolete navigation expectation. Parent verification passed: 68 backend tests, 11 frontend tests, TypeScript and full production build. Actual stdout is saved in tasks/image-gather-{backend-tests,frontend-tests,types,build}.log; earlier worker summaries are not evidence. Local browser visibly shows accepted 20/20 Roster, separate Gather images at 0/20, and existing Research 1/20 gated by images. No local generation was triggered.

Scoped commit 82201e54 pushed to main, preserving the five unrelated dirty tracked files. Deployment through se.sh started; live gather remains pending and has not been represented as complete. Next: prove deployed worker parity and health, run only Gather images once on the accepted20, then read actual photos/sources and retained card/history counts.

Live release verified at20:32UTC: 82201e54 backend/frontend/worker healthy, worker parity correct, normal drain. Gather endpoint submitted exactly once at20:33UTC. At20:40UTC: 5 entries processed, 4 verified photos saved; Barracuda candidate vision_rejected. Original20 roster, one paid research card, and58-entry prior history preserved. Current job continues; no Research/provider retry was triggered by missing photos.

Live progress repair57d6a829 is pushed and awaiting the current job's terminal state before deployment. New endpoint markers now use task_type=roster_images; the panel also recognizes a running image receipt while the shared watcher is active. Four focused checks and full build pass. Browser control disconnected during the second local screen check; the earlier local and production stage screens were verified. Next: finish the same sweep, deploy the progress repair after active work clears, inspect final image/source counts and missing reasons.

### Final image sweep result — 20:57UTC

- [x] Feature implemented and initial deployment verified; ordered Roster -> Gather images -> Research with current cache truth, whole-roster gating and preserved research.
- [x] One real sweep finished on the accepted20, with17 photo references containing both hosted and source URLs. Job terminal failed and receipt needs_review correctly prevent false completion.
- [x] Original20 accepted roster, saved detailed card1 and prior58-entry history retained. No detailed research or generated pictures were started by this request.
- [ ] Three references still need replacement candidates: SS-163 through SS-165 Barracuda (V-1) class; SS-417 through SS-525 Tench class; AGSS-569 Albacore class. Each current candidate failed vision identity verification. Do not force acceptance or rerun the entire provider search blindly.
- [x] Progress-label repair57d6a829 deployed20:59UTC with healthy backend/frontend, worker code parity, normal drain and zero active work. Fresh production browser reconnected: visible17/20 photo gallery, source links, three missing-reference reasons, enabled Retry missing images, completed Roster and Research1/20 gated. Screenshot visually confirms the first saved photos render; this is technical UI verification, not creative acceptance.

Evidence: tasks/image-gather-request.json (one request), image-gather-live-latest.json and progress.jsonl (actual cache/source/roster/card/history readback), image-gather-barracuda-miss.log (persisted rejection), image-gather-deploy.log and image-gather-progress-deploy.log. Always next: gather different source photos for the three missing classes through normal verification; then resume detailed research on the saved20. Full video is unfinished.

## Round 1 execution
1. Inputs: canonical HEAD6e594403, saved submarine draft, runtime and existing research_payload.roster_settings.minutes_per_machine (default1). Files: backend/roster_selection.py (new), backend/pipeline_executor.py, backend/roster_coverage.py, skills/video-pipeline/research/agent.py and new focused backend tests. Action: introduce versioned runtime-selection contract. Count=max(1,floor(duration/minutes_per_machine+0.5)); reject invalid/nonfinite/nonpositive parameters. New static_docu research calls select roster only; narrative paths unchanged. Use a dedicated concise selection prompt via ResearchAgent optional selection settings: title predicates remain mandatory, Every/all never overrides count; select exact target or return honest insufficiency with sources; no padding, member-hull enumeration, title/cinematic/writer generation or adapter early DB writes. Keep existing bounded complete_response/checkpoint parsing recovery. Include saved draft as source data for selection; checkpoint request naturally changes.
2. Same boundaries. Action: independent selected-entry audit, reuse existing authoritative source rules and caching but fingerprint/version selection settings. For runtime selection, audit real/distinct/title-fit only, not omitted qualifying entries. Two consulted primary/archive sources, source-backed findings for wrong entries/aliases; review may confirm genuine insufficiency. Structural gate checks nonempty/count/exact duplicate names/real-build contradictions/recommended consistency; bypass exhaustive buckets, search quotas, omission matrices only in explicit versioned runtime-selection mode. Title policy retains nationality/role/build requirements. Legacy payloads retain legacy gate behavior.
3. Same boundaries. Action: PipelineExecutor.run_roster_selection called by run_research for static_docu new or unaccepted draft; existing accepted legacy roster with downstream work must be reused, not recounted. Selection merges into saved payload and archives previous changed roster payload snapshot once under roster_selection_history (no deletion of cards/packages). Save draft BEFORE independent audit; preserve on exception. At most one correction using exact draft+findings; save it before re-audit. On pass persist roster_selection.status=completed and research_phase=roster_complete with selected_count, inputs and independent current verdict, return status=roster_ready (do not set unsupported videos status); no unit hold, prefetch, script, drive sync or other generation inside Roster. On failure persist needs_review/insufficient status and factual reasons then return failed. Repeated successful Roster calls must do no provider work or detailed research. Legacy accepted roster call also stops Roster rather than run_unit_research.
4. Same boundaries. Action: _live_roster_gate dispatches selection validator for explicit selection contract and requires current independent audit; _machine_documentary_hold_roster exposes all nonempty saved lists (remove3..40 invisibility) while render-mode/marker guard stays. run_unit_research records research_phase=unit_research at start, runs only on passed saved roster, preserves card reuse and detailed factual gates. Dashboard exposes saved roster regardless gate status. Preserve original legacy deep-research path for nonstatic videos. Ordinary helper names and test fixture plumbing permitted. Any missing material decision returns to Astra.
5. Parent owns orchestration, UI and settings endpoint changes after mapping, then integration review. UI: Roster completion based on accepted selected list, photos auxiliary; drafts visible, detailed research not done from roster fact_sheet. Persist minutes-per-machine setting via tenant-scoped endpoint, prevent edits during work or after accepted roster/downstream work. No additional Run buttons. Run All dispatches roster and unit_research in separate steps.

Acceptance: focused fake-provider tests exact20, custom pacing10, invalid values, no Every override, no padding insufficient, duplicates/build mismatch, current audit invalidation, saved draft on failure, Roster zero hold/prefetch/title-generation calls, repeated accepted roster zero provider calls, separate next Research step; 24 existing recovery tests preserved. Frontend SSR/typecheck/build and browser actual flow. Round1 Terra execution then Astra review, at most3rounds. No worker deployment/paid call/commit. Parent deploy only scoped reviewed files via se.sh under existing user approval; verify pushed/deployed hash/health, resume same video once only if idle, read saved20+completed Roster before subsequent Research start. Stop on provider block; never blindly retry. Evidence in canonical tasks/submarine-stage-*; card SE-0002 aligned.
Market checkpoint: documentary creators, reliable one-button production, existing StoryEngine channel, real submarine workflow is next test. No new outreach/publication.
Acceptance: focused fake-provider tests exact20, custom pacing10, invalid values, no Every override, no padding insufficient, duplicates/build mismatch, current audit invalidation, saved draft on failure, Roster zero hold/prefetch/title-generation calls, repeated accepted roster zero provider calls, separate next Research step; 24 existing recovery tests preserved. Frontend SSR/typecheck/build and browser actual flow. Round1 Terra execution then Astra review, at most3rounds. No worker deployment/paid call/commit. Parent deploy only scoped reviewed files via se.sh under existing user approval; verify pushed/deployed hash/health, resume same video once only if idle, read saved20+completed Roster before subsequent Research start. Stop on provider block; never blindly retry. Evidence in canonical tasks/submarine-stage-*; card SE-0002 aligned.
Market checkpoint: documentary creators, reliable one-button production, existing StoryEngine channel, real submarine workflow is next test. No new outreach/publication.

## Parent-defined frontend/orchestration implementation details
- Input: current actions.make_autobuild_step plus roster_ready result. In actions.py progress key add research_phase and roster_selection.status (not just video.status) so independent Roster completion permits next iteration. In static idea_logged/approved branch: if selection not completed call run_research first, accept roster_ready by continue, failed selection terminates with preserved draft (must not run repair ladder). On next iteration for completed selection call run_unit_research; keep existing factual pending-card ladder only after unit research failure, never selection failure. Legacy valid run_research returns roster_ready too: persist phase roster_complete before returning. Stage-plan research-only behavior should finish after detailed research via existing _advance resolver. Preserve provider/cancel/budget controls; no new DB status.
- UI files: RosterStagePanel.tsx, StaticDocuStageRail.tsx, pipeline/[videoId]/page.tsx, lib/api.ts and lib/static-docu-navigation.ts; tests. Canonical pre-existing dirty frontend files are copied into worktree and must be preserved. Add video prop to RosterStagePanel. Derive draft units from research_payload.unit_roster if dashboard unavailable; preserve existing remove/reference controls. Roster stage shows target count calculation duration / minutes-per-machine, selected count, completed/draft/review-needed status from selection+live unit_roster_validation. Existing accepted legacy rosters derive completion from live verdict; reference photos secondary and do not block Roster/Research. Research stage only complete on actual ready saved cards or hold pass; a roster/fact_sheet in selection mode never counts. Cards==0 yields not_started unless phase unit_research. Research gating requires Roster passed. Keep one Run All/Resume button and existing styling/components. Skip editing product guide if parent owns.
- Roster settings endpoint parent-owned: POST /api/pipeline/roster-settings/{videoId}, JSON {minutes_per_machine:number}; returns saved setting. Duration/title use existing video fields; UI displays title and duration, editable numeric minutes/machine default1 and Save pacing button before completed roster (disabled task running/downstream/status complete). No paid work. API helper and UI wired to this exact route; on save invalidate video and roster-dashboard. Backend rejects invalid values/nonstatic/active task/accepted roster/downstream work. Worker may add optional prop to ease tests but actual page passes video. No changes to shared component library dependencies.
- Acceptance frontend: SSR stages selection complete+zero photos→Roster done Research not_started; draft58 visible; unit research phase→in_progress; hold/cards ready→done; settings input and count10 at20/2; remove label preserved; TypeScript/build against shared canonical node_modules. Action tests prove event order roster save/end then next iteration run_unit_research with20 and no repeat selection; failed roster no hold/ladder; phase progress avoids false no-advance. Tests can use existing stubs. No network/deploy/paid calls. Parent handles backend settings endpoint and production_guide.

## Round1 review — did not pass
Local scaffolding tests passed, but Astra integration review found missing checkpoint scope in new selection calls, contradictory legacy system prompt, unsafe legacy promotion, missing script-gate selection dispatch, unchecked saves, and Run All first-call fallthrough. No deployment or paid retry. Round2 prescribed fixes cover these exact findings: source-scoped durable selection/audit calls; dedicated compact system policy; current gate validation on reuse; legacy payloads retain legacy contract; allowlisted merges/full prior snapshot; saved gate verdict and write checks; script parity; cancellation/terminal failure; first no-marker draft to independent Roster then unit research on next iteration. Parent also added settings exclusivity and terminal worker status proof (12 tests passed).

## Astra takeover after Round3 — final integration
Round3 reports were insufficient: actual code still used a stale stored legacy verdict and script paragraph matching treated full paragraphs as literal names. Astra corrected legacy/live-gate reuse, protected compact saved cards/scripts from rescaling, completed fresh-roster marker handling, audited pending/failed save truth, and tested real executor persistence directly.55focused backend tests pass, including9executor integrations and24prior recovery tests. Broader roster-loop suite15pass/2known baseline fake-fixture failures; no claim those legacy failures were repaired. Frontend TypeScript/build and focused behavior tests pass. Local UI browser verification underway before approved release.

## Release verification — 2026-09-15
Astra final checks: 55 focused backend tests passed; 14 updated research/resume tests passed; 5 frontend behavior tests passed; TypeScript and production frontend build passed. Broader legacy roster loop has 15 passing and 2 previously established baseline fixture failures. Browser on localhost:3001 verified all 58 saved draft names visible, target 20 at 1 minute/machine, Research not started, no photo completion requirement. Commit f561ddf6 pushed to origin/main; relevant existing Remove-label work incorporated and original three frontend files backed up under /tmp/se-pre-integration-backup. Other dirty work preserved. Authorized se.sh deployment in progress. Live proof will run standalone Roster once, read saved completed 20 and idle state, then resume normal build for the separate detailed Research stage. No repeated discovery if it passes.

## Live boundary repair — Astra
Standalone live attempt preserved58-history, returned0 for erroneous Every/completeness objection, then correction saved21; independent audit also incorrectly applied omissions. No detailed work began. Exact repair: selection_source_data exposes candidates/sources without old exhaustive prose; selection_subject removes leading Every/All quantity words while retaining nationality/type/build/date; audit version2 invalidates old criteria. Application takes target-sized prefix of provider order, preserves surplus as roster_candidate_overflow, never pads; candidate audit remains mandatory. Reuse saved runtime candidate list before provider discovery, then review20 independently. Write scope seven selection/research/test files in isolated worktree;43focused tests passed, including saved21→20 with zero rediscovery, surplus preservation, factual failure retained, and correct audit subject. Release backend-only via se.sh; one checkpoint-aware roster resume after idle verification, then detailed research only after completed live gate.

## Live acceptance complete — 2026-09-15
- Deploy c798a0c1: backend/frontend/worker healthy, worker parity verified, drain normal, active work clear after deploy.
- First standalone Roster attempt correctly stopped on audit capacity; no detailed cards. Boundary repair reused saved candidate evidence, increased audit budget from6 to12, and reran once.
- Live Roster readback: task completed with message “Roster selection complete; detailed research is next.” `roster_selection.status=completed`, target20, selected20, `unit_roster_validation` passed, independent audit version2 passed with empty findings and authoritative NHHC/Naval News sources, `roster_selection_history` contains original58 entries, no research cards or hold.
- Live UI readback: “20/20 selected and independently accepted”; Research says detailed research has not started before next step.
- Separate detailed Research started once via normal build after idle check. Current readback: task running “Researching the saved roster…”, `research_phase=unit_research`, saved roster20, first unit card in progress, no script/render/upload. This is the requested stage boundary; full video remains unfinished.
- Focused tests: 55 backend + 14 research/resume + 43 boundary/integration + 5 frontend behavior; TypeScript and production build passed. Two broader legacy fixture failures remain known baseline.


## Roster correction — one machine per class (2026-09-16)
User instruction: choose any one real machine from each selected class. Tang choice: USS Tang (SS-563). Class ranges are metadata, never research identities. Preserve runtime20 and completed work. Local plan: {"id": "representative-roster", "title": "Build: one named machine per selected class", "inputSource": "User correction 2026-09-16; backend/roster_selection.py, backend/roster_coverage.py, ../skills/video-pipeline/research/agent.py; current saved20 roster", "action": "Require one source-backed named representative per selected class in selection and independent audit; reject class ranges and duplicate classes; verify focused regressions. USS Tang SS-563 is the requested Tang representative choice.", "writeBoundary": "Those three source files; backend/tests/test_representative_roster.py; CHECKLIST.md; JOURNAL; tasks/representative-roster-*", "expectedOutput": "Reviewed local patch and focused test receipt; live migration remains separate pending release authority and preserved-evidence mapping", "dependencies": "Existing runtime-selection contract and current user correction", "acceptanceEvidence": "Class/range identities rejected, named representatives accepted, duplicate classes rejected, runtime count preserved; no source fabrication", "authorityStop": "Local correction authorized. No deployment, paid provider calls, or live roster replacement during preparation. Preserve completed research and images; require exact-subject revalidation before reuse.", "done": false, "evidence": ""}

Roster representative local review PASS: selection prompt, structural gate and independent factual audit now require one named member per selected class; duplicate classes and range identities rejected. 18 focused tests pass (tasks/representative-roster-tests.log). USS Tang SS-563 verified against NHHC DANFS. NOT deployed; saved20 unchanged. Always next: scoped release and source-backed saved-roster conversion, retaining original evidence and revalidating images against chosen boats.


### Roster rule deployed — 2026-09-16
User approved deployment: "reploy this". Release 9a29062a7 deployed via se.sh; 18 focused tests pass against latest baseline. Backend/worker parity and healthy API verified; normal drain restored and deploy lock cleared. Evidence: tasks/representative-roster-deploy.log and representative-roster-release-tests.log. Saved roster has not been converted; next: source-backed one-member-per-class selection for the existing video, preserving old research and revalidating photos.


## Authorized roster rerun — 2026-09-16
Astra plan-completeness PASS. Round1 Terra bounded archive-preparation implementation, parent review and live execution. Exact step: tasks/representative-roster-rerun-plan.json. User explicitly requests rerun of the saved20; previous preserve-roster instruction now means preserve original evidence in history, not retain class-range identities.

Roster rerun round1 failed local review; round2 passed after prescribed corrections (tasks/representative-roster-rerun-review.json).3offline tests pass. Archive applied and verified in transaction: full prior payload and1compact card retained; old58history retained. One normal Roster request started19:34:43UTC; await source audit and saved20 individual-machine acceptance.

Named roster saved20 with all class ranges removed. Final independent audit blocked at12searches (verified12/20), source metadata clarification on Barracuda also reported. Focused repair plan Astra PASS: tasks/representative-audit-budget-plan.json. Preserve saved20 and archive; no repeat discovery unless existing normal bounded correction requires it.


## Current continuation — images for named boats
User authorized Terra subagents and image repair. Astra plan-completeness PASS: tasks/named-machine-image-plan.json. DoD20/20verified exact-name photos and visual review; preserve accepted20, archives and existing cache evidence. Next normal Gather once, diagnose saved misses only if needed.

Submarine-image review found Plunger false-ready: caption pronouns + filename, not named subject. Astra repair plan PASS tasks/named-machine-image-caption-plan.json; Terra local round1 while normal gather continues. Preserve current valid work; no active-run deployment.


## Named submarine images — caption repair round1 review
Astra review PASS:48 focused tests; portable Plunger receipt proves identity failure and corrected-caption success. Saved live first10 replay retains9 valid photos and rejects Plunger with saved c1 alternative, no provider calls. Source review through Barbel clean except Plunger. Deployment waits current gather terminal. Evidence tasks/named-machine-image-caption-review.json, caption-replay.json, caption-tests.log.


## Active: named submarine research and source-backed confidence
DoD:Research tab matches accepted20submarine names; source-backed support/conflict assessments remain attached to evidence and saved briefings; current research run can assemble exact-name cards. No numerical truth probabilities. Initial read-only Terra maps under tasks/submarine-research-plan.json; Astra design/review before execution. No script/render/upload.


## Submarine research round2 review — local PASS
106backend +8frontend tests pass; frontendproduction build passes. Actual assessmentcomponent SSR/visual reviewed. Round1review identified metadata alias drift and assessment excluded from scriptcachehash; round2corrected fullidentity joins and fullpackagefingerprint, invalidreceipt preservation and stalegate tests. Scoped worktree ready forauthorized deployment/research-only run. Evidence tasks/submarine-research-review.json.

## Research round 3 — typography-only quote recovery
Astra plan completeness PASS. Input: tasks/submarine-research-live-latest.json Holland SS1 saved raw response uses straight apostrophes where original excerpts have curly apostrophes; strict substring rejects otherwise identical quotes. Action: in research_claim_assessment.py add bounded deterministic quote resolution: exact substring first, then character-by-character normalization of curly single/double quotes, nonbreaking spaces and dash variants only, preserving length/index mapping; accept only a unique normalized substring and return the exact original source slice. Never fuzzy words, omit text, alter numbers or permit ambiguous matches. Write boundary: backend/research_claim_assessment.py and backend/tests/test_research_claim_assessment.py in /tmp/storyengine-submarine-research. Expected: source quote is restored verbatim; one saved-response replay can validate without a new provider assessment. Dependencies: live receipt preserved, no deploy while live research active. Acceptance: tests for actual curly-apostrophe failure, source slice preservation, substantive/number mismatch and ambiguous match rejection; existing tests pass. Authority: local edits/tests only, no provider calls/deploy/data mutation. Terra ordinary helper naming permitted. Stop on any wider repair/design need. Astra reviews before integration.
Round3 recovery refinement: assess_verified_package may replay only a saved failed raw_response when machine/context/source_fingerprint still exactly match current original package and version1, raw_response_truncated is false, and structural validation under the typography resolver now passes. Build normal assessed receipt, then normal current-assessment validation. If replay fails, retain normal one-call behavior. Test replay consumes zero provider calls; stale fingerprint never replays. This avoids paying again for already-captured valid claims; no original evidence changes.
Round3 Astra review found a second real-input defect: S-1 summary and claim_map identical first sentence contains “Submarine No. 105”; sentence tokenizer splits at No. before a numeral. Astra takes this narrow parser repair: protect No./Nos. only when followed by digits; do not alter source/paragraph text or broad sentence boundaries. Files: factual_machine_summary.py and tests/test_factual_machine_summary.py; acceptance exact S-1 paragraph yields three unchanged sentences, ordinary sentence ending No. still splits, existing summary suite passes. Live S-1 remains failed until normal referee rerun passes; never flip passed flags manually.
Astra live review correction after round3: factual-contract cards show stale Anton-slot preview warnings despite passed saved briefings. Parent owns final UI repair: ResearchTab factual ready message uses saved source-backed summary status, legacy status remains for other contracts; hide legacy Anton coverage chips for factual contract; assessment source labels show excerpt IDs and source titles/links, no internal search query locator. Files ResearchTab.tsx and submarine-research.test.mjs only; acceptance node tests and production build, then live passed card lacks contradictory blocked warning. No provider/data changes.
Final Astra gate repair: live full-roster completion retained target_machine=Lafayette, making Research approval reject an otherwise passed 20/20 result. Input tasks/submarine-research-live-latest.json. In run_unit_research only, remove target_machine and target_machine_passed after its full-roster hold returns; one-machine entrypoint untouched. Files backend/pipeline_executor.py and tests/test_roster_stage_integration.py. Acceptance real entrypoint regression asserts aggregate marker absent and ready_for_scripting, then no-spend saved-summary continuation yields live full approval gate. Backend-only deploy when idle; preserve all source packages and summaries exactly; no provider retry.


## Script compiler deployment authorized — 2026-09-16
Ryan: “You can deploy.” Input: six reviewed files in docs/script-compiler-2026-09-16/integration.json;94 passing tests,20/20real saved packet replay. Action: verify exact hashes and canonical main/upstream; commit only six scoped code/test files, push main, deploy backend using scripts/se.sh deploy dvsu-script-compiler-20260916; read health/worker parity/commit/drain/lock. Files: six reviewed code/test files plus deployment evidence/checklist/journal/SE-0002; no unrelated edits, no dependency or schema changes. Output: scoped release commit and deploy.log/deployment.json. Dependencies: user approval, matching hashes, clean release index and fast-forward main. Acceptance: remote main==release, VPS checkout==release, backend/worker active with restarted worker on release, API healthy, frontend200, drain normal and lock clear. Authority: deployment approved; no paid generation or video state changes; never interrupt active work/force a lock. Always next: representative script-only canary with cost/authority before any full-episode run.


## Completed preview label repair
Holland UI label uses em dash; strict parser fails before canonical matching. Astra plan completeness PASS: docs/preview-label-2026-09-16/PLAN.md. Terra round1 narrow parser/tests; existing deployment approval applies. DoD canonical scene1 readiness, wrong hull/name still blocked, production script hashes unchanged; no paid generation.


## Completed preview review version repair
Astra round1 plan completeness PASS. Input: saved Holland preview passed=true,warnings=[],review_context_version=6; backend factual_machine_summary.py REVIEW_CONTEXT_VERSION=6; UI hardcoded5. Action: change UI constant to6 only; test harness must extract actual UI constant instead of independently hardcoding; regression compare actual backend version with UI, accept Holland emdash label current6, reject stale5 and failed6. Write boundary: frontend/src/components/production/ScriptVoiceTab.tsx and ScriptVoiceTab.factual.test.ts, plus evidence. Ordinary test naming permitted. Output: two-file diff, focused Vitest and build logs. Dependencies: source inspection complete. Acceptance: version parity and current/stale checks pass; frontend production build passes. Authority: local edits/tests; no provider calls, DB mutations, commit or deployment by Terra. Stop and return material gaps to Astra. Parent reviews, commits only two files, deploys se.sh --with-frontend under existing approval, verifies service/release and served frontend version; preserve saved preview/production script. Next: refresh existing preview without regenerate.


## Active DVSU compact brief repair
Astra plan completeness PASS; round1 bounded Terra compiler/writer implementation, parent research/integration/review. Plan: /Users/ryanayler/AgentVault/Projects/story-engine/storyengine/docs/dvsu-brief-2026-09-16/PLAN.md
DoD: compact complete brief;80word floor; source and DVSU editorial checks; missing evidence blocked before paid draft; tested/deployed; no mass generation.


## Holland-only paid verification authorized
Ryan: “Okay, you could spend on just that one.” Execute one Holland-only research repair; readiness; one preview only if ready. Stop after this bounded test. Preserve production scripts and other machines. Evidence docs/dvsu-brief-2026-09-16/canary-*.


## Active no-paid source recovery
Astra plan completeness PASS: /Users/ryanayler/AgentVault/Projects/story-engine/storyengine/docs/dvsu-source-recovery-2026-09-16/PLAN.md
Original source already contains training history; preserve section identity and later service paragraphs, validate archive fallback, return target warnings. No live paid or research mutation.


## Source recovery round1 — deployed, bounded DoD PASS
Release c5956e190; source extractor and target warning repair deployed/verified, including production-server original museum fetch recovering exact training. Tests38+7distinct targeted+12additional pass;6old failures reproduced on baseline. Zero paid calls; research/production hashes unchanged. Evidence docs/dvsu-source-recovery-2026-09-16/REPORT.md and deployment.json. Overall Holland writing acceptance remains OPEN: explicit intended-role evidence and fresh reviewed script not yet established. Always next: review primary-source intended role and four-field brief before another paid preview.


## Active Holland primary-source brief
Astra plan completeness PASS: /Users/ryanayler/AgentVault/Projects/story-engine/storyengine/docs/holland-brief-2026-09-16/PLAN.md; free retrieval/local facts and editorial example only. No paid calls or live data writes.


## Holland primary brief — local DoD PASS
Holland primary brief local review PASS. Congressional Record1901 printed3089/PDF77 visually verifies commander coast/harbor-defense advocacy; museum supports design/training/A-class. Four human-reviewed claims47words; real briefbuilder931bytes, deterministic under repeat/reorder;99word manual example. No paid calls or live writes. No production assessment or preview claimed; PDF first8page limit prevents automatic retrieval of page77; Smithsonian403/NavyTLS failures excluded. Evidence docs/holland-brief-2026-09-16/BRIEF.md, evidence.json and verification.json. Next: page-targeted source ingestion then normal assessment/preview within authorized spend; full episode remains unverified.


## Active automatic DVSU evidence ingestion
Astra plan completeness PASS: /Users/ryanayler/AgentVault/Projects/story-engine/storyengine/docs/dvsu-automatic-evidence-2026-09-16/PLAN.md; source/identity technician round1; parentintegration/review. No paid calls or live datawrites before scopedverificationauthority.


### DVSU global handoff repair — 2026-09-17, open
User next-machine failure exposed incomplete legacy narrative assessment migration: read-only audit20current assessments but only SS1brief ready. Astra round1 stepA gate PASS; executable ownership and acceptance in docs/plunger-readiness-2026-09-17/PLAN.md. Terra assigned migration; infrastructure inventory read-only. Next: generic selected-machine preparation and durable UI handoff, then SS2 live acceptance and all20no-spend audit. Production script unchanged; no global readiness claim. Existing SE-0002 card updated.

DVSU global handoff review progress: A round1 caught failed-receipt replay eligibility conflated with paid retry eligibility; Terra round2 repaired, Astra reviewed13 assessment tests PASS. Stable writer/source/compiler regression union107 PASS (unchanged-contract-tests.log). B round1 rejected: lost recaptured evidence, incorrect readiness field, incomplete guards/fingerprint persistence and insufficient behavioral tests; round2 in progress. C preliminary review rejected readiness false-pass copy, repeated POST on resume, and malformed result/activity handling; corrections/tests in progress before formal review. D1 harness review requires crash-safe ID persistence, strict GET-only resume, and honest missing snapshot fields. No new provider calls or deployment yet.

DVSU global repair implementation review: A round2 PASS; B round2 plus explicit-citation cache correction PASS (125-test backend union); C source review PASS with9 behavioral route/worker checks and3 polling checks, frontend typecheck/build pass. New actual API-wrapper tests remain in progress before release. Complete live preflight saved in docs/plunger-readiness-2026-09-17/live-before.json:20 packages/roster,0 script rows, empty production and exact Holland copyedit. No new provider calls yet. Next: finish frontend acceptance and actual saved-card readiness replay; then scoped commit/deploy and SS2-only canary.

DVSU global handoff release and first SS-2 action: initial release `b53879e6d` deployed successfully. The one SS-2 preview job stopped during factual research-summary preparation because the prior writer request exceeded the conservative input budget; it did not write a preview or production script. The canary response records the budget error, and `live-audit.json` reports the before/after snapshot unchanged, preserving production state and the other19 machines. Round3 is limited to compacting archived assessment projection from research writer/referee prompts, rejecting non-narrative role labels while retaining facts, and treating the exact stale-summary warning as preparable recovery. Final deployment and a successful canary remain open. Evidence: `docs/plunger-readiness-2026-09-17/canary-response.json`, `live-audit.json`, and `research-prompt-budget-measurements.json` (writer 22,008 UTF-8 bytes; referee 10,374 bytes after projection).

DVSU global handoff Round3 live review: commit40b610b13 deployed healthy. SS2 job2308290c-bf50-4883-8ab9-ba6a288dddda completed needs_review (intended_role/design absent); no scriptdraft or production change. Actual all20 API no-spend audit1ready/19preparable. Recaptureadded5; discoveryadded0; receipts prevent rediscovery. Astra takeover found real source extraction defect: foreign hulls late in a publishersection discard earlier engineering/testing; explicit renamedUSS A1 mistaken forforeignidentity. Narrow contiguous anchoredprefix implementation preserves sourcewords, stopsatforeignship/cap, accepts only literalrename occurrence. Sourceprefix realpageproof passed for bothoriginals; researchrequestbound30061<48000. Preserved explicitrecapture discoveryreceipt and moved gapbookkeeping into assessment to prevent fingerprint drift. 48focusedtestsPASS. Sourceprefix backendrelease in progress, then one same-original-source refresh (no discovery) and preview ONLY if ready; other19/production unchanged. Scope PLAN.md, evidence source-prefix-free-proof.json and source-prefix-final-tests.log. End-to-end DoD remainsOPEN until realpreview passes.

DVSU source-prefix release and refresh handoff: shared code deployed at `b1dcf0154`. The release covers archived-assessment prompt compaction, durable job/automatic preparation, meaningful role guards, source-prefix extraction, literal renamed-alias handling, and recovery-receipt preservation. One SS2 refresh used only the two saved original URLs: sources=6, excerpts=24, discovery receipts remain2. It produced design=3, actual_use=2, outcome=2, but intended_role=0; no passing new preview was written. Saved audits preserve production, the other19, and the Holland copyedit. The latest actual all20 readiness was1ready/19preparable before this final refresh; it is not a claim that all20 are written. Current focused tests48PASS; prior broader suite145pass with one known sentence-map baseline failure. Next: source-backed intended-role research for SS2, without a blind generation retry. Overall DoD remainsOPEN. Evidence: docs/plunger-readiness-2026-09-17/REPORT.md and after-refresh-assessment-report.json.

## DVSU purpose-context continuation — open
The user continued the bounded SS-2 recovery after same-source extraction left intended_role empty. Step C in `docs/plunger-purpose-2026-09-17/PLAN.md` is implementing verified A-class context from Pigboats; a separate purpose-source harness accepts only `https://pigboats.com/A-class`, with a one-POST marker and readiness-only follow-up. The earlier original URLs are not supplied again by this harness. No purpose source has been captured through this harness, no preview is authorized automatically, and the end-to-end DoD remains open until a source-grounded SS-2 preview passes its factual and editorial gates while production, other19, Holland, roster, and original source prefixes remain preserved.

## DVSU SS-2 purpose-context proof — bounded feature complete

SS-2 now has a saved 96-word, five-sentence preview with factual pass, five supported support-audit rows, six passing editorial checks, and no warnings. The original preview job was `eebdafff-a420-4de7-b3c9-d166669d08f6`. A two-noun-equivalent wording correction received one replacement referee pass after the first referee response was lost during receipt serialization without a database write; CAS v3 then changed only `machine_script_previews.SS2`. Final source-package comparison is exact across all 20 packages, both preservation audits passed, production script rows remain zero, and the no-spend all-20 replay is 2 ready/18 preparable. Evidence: `docs/plunger-purpose-2026-09-17/REPORT.md`, `plunger-preview.md`, `ss2-copyedit-referee-v2-result.json`, `ss2-copyedit-cas-v3-verification.json`, `g2-source-package-preservation.json`, and `all20-no-spend-readiness.json`. Ryan creative acceptance and the remaining 18 previews remain open; no production promotion occurred.

## Runnable DVSU roster follow-up — active
User screenshot proves research-only UI gates prevent entering automatic preparation; batch lacks selected-machine preparation and previews mislabeled production. PLAN: docs/dvsu-runnable-roster-2026-09-17/PLAN.md. Done when rendered buttons reach guarded flow, batch prepares missing facts/reuses previews, truthful production labels, tests+frontend release+live readback. No paid generation during verification.

Runnable roster review rounds: Round1 Astra corrected UI production-text equality/downstream gate scope and backend post-readiness reload. Round2 backend mixed-batch proof and stale test contracts PASS; 67 backend tests pass, source diff clean. Frontend rendered 20-card mock flow/7 unit tests/typecheck/build pass pending final busy-state assertion. No paid calls or live data mutation; release waits final browser test receipt.

Runnable DVSU roster final review PASS: deployed f10e8f570 (core df316f28). 67 backend/7 frontend unit/2 rendered browser tests, typecheck and production build pass. Live authenticated page all18cardbuttons+RunAll enabled; correct0production/2previewlabels/subtitles; confirmation opened/canceled, zero paiddispatch. DB script/validation/research hashes and scene_count unchanged. Healthy parity/normaldrain/0active. Evidence docs/dvsu-runnable-roster-2026-09-17/REPORT.md. Next: user may run remaining cards/RunAll; actual paid18script acceptance notclaimed.

## SS105 recapture assessment recovery — active
Actual saved9claim response: one quote changed until1922 toin1922; strict validator rejects wholeassessment, leaving8validrows unusable. Fix response-boundary partialclaim admission and exact-bound savedfailedresponse replay without relaxing strictquote/identity gates; retain proven prior facts and continue boundedpreparation. PLAN docs/dvsu-recapture-validation-2026-09-17/PLAN.md. No paidcalls duringverification.

SS105 recovery review PASS: Terra implementation plus Astra correction of malformed-response prior fallback. Strict quote/claim/receipt validators AST-identical; 72 assessment/handoff/identity tests plus15 packet/budget tests pass. Actual saved fullsnapshot readiness replay SS105 preparable=true, missing only intended_role, zero provider calls; compiled recovered packet20,276 UTF8bytes. Backend release in progress; live readiness verification pending. Scope and authority remain no paid generation, no production/source edits.

SS105 recovery deployed/readiness verification PASS at9e77c2cb40963ca3c0df988484be2d436440c08d. Actual authenticated live readiness preparable=true, ready=false, intended_role missing; no internal recapture assessment error. Protected production/all20sources/roster/previews/cost unchanged.87testsPASS, zero paidverificationcalls. docs/dvsu-recapture-validation-2026-09-17/REPORT.md. Overall remaining18-script end-to-end acceptance staysOPEN; next normal SS105 preparation/preview then inspect actualresult.
