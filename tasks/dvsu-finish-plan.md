# DvsU Finish Plan — what is left to ship customer #1 (Anton, @designedused)

**Produced 2026-07-21** by a maestro mapping pass (3 parallel Explore sweeps: planning docs,
code/tests, live-verification queue), on branch `claude/dvsu-channel-story-engine-hzyts1`.
Tenant `561b872d`, render mode `static_docu`, active proof row
`fc73860c-a9af-444f-95a5-7f86d60503e0` (23-machine bomber roster).

**REFRAME (2026-07-21, Ryan):** the goal is NOT the StoryEngine platform backlog (mostly
finished/outdated) — it is the DvsU channel's own core problem: **locking down its
scripting so factual information is grounded in proper research.** The core arc is
DV-0 → DV-1 → DV-2 (seed the law → measure under the seeded law with fresh
provenance-gated research → close the writer/grounding gaps, iterating to 3/3 then 23/23).
The factual-grounding validators (D5/D6: QL-18 two-independent-source numeric check,
QL-19 claim-to-evidence grounding) are first-class DV-2 candidates, not nice-to-haves.
DV-3 (UI), DV-7 (production), DV-8 (docs) are downstream and deprioritized until the
scripting bar is met.

This file is the reconciled successor to `storyengine/GOAL.md` Phase G (which is stale —
last updated 2026-07-15, before the C46a–e quality-rules arc landed 2026-07-19). It does
NOT replace the loop files (`tasks/todo.md` handoff, `tasks/storyengine-wiring-fix-checklist.md`,
`tasks/live-verification-queue.md`); it maps the DVSU-specific remainder and points into them.

---

## ⟳ 2026-07-21 STATUS (live run — see tasks/dvsu-bomber-loop.md for full detail)
**The scripting problem is effectively SOLVED for the bomber video.** DV-0 seeded the 76 laws
live; then 23 worker-authored, individually-fact-checked, Anton-voice paragraphs were submitted
via `submit_script` and **passed the seeded-law critique with 0 violations** (verified: 23
`scripts` rows, correct roster order). Voice generated ($5.47, correct Nathaniel-C narrator).
**ONE blocker to a finished MP4:** a prod bug (`static_docu.py` dead-imported `_KIE_CLAUDE_URL`,
removed by C43) crashed every static-docu image run — likely why no DvsU video ever rendered
end-to-end. **Fixed on branch `claude/dvsu-channel-story-engine-hzyts1`, needs deploy** (I did
not push to main / deploy to live prod unprompted). After deploy: re-run `build` twice (images,
then finish→render+thumbnail), ~$0.8 of the $10 budget remains. Resume recipe in the loop file.
Key method finding: worker-write + `submit_script` (prose critic, not the brutal claim-map gate)
is the reliable path — no fragile research injection needed; static images self-source photos.

## ▶ VIDEO #2 PLAN (Ryan approved 2026-07-21) — "agent-researches → inject as VERIFIED → platform grounds the script"
The standard flow for the NEXT DvsU video, so it shows grounded research + VERIFIED cards +
an auditable evidence chain (unlike video #1, which used the prose-critic shortcut):
1. **Agent researches** each machine (my subscription — real WebFetch of authoritative sources,
   per-fact source URLs, adversarial fact-check). Free.
2. **Structure + inject as the platform's evidence**, per machine, in the EXACT gate contract
   (from audit §research-schema): `machine_raw_source_packages[key]` = ≥6 traceable verbatim
   excerpts, ≥2 distinct source URLs, ≥1 Tier-1/2, `source_capture_method` ∈
   {fetched_page,tavily_raw_content}, `source_variant_selection`, covering the 4 required Anton
   slots with DISTINCT excerpts; + `machine_research_cards` row (schema_version 3, evidence_segments
   citing those excerpts, engineering_thesis, etc.). Inject via jsonb_set/upsert (non-destructive,
   roster-snapshot guard) since the per-machine `/machine-research-one` route is session-JWT-locked
   from the agent token. Result: each machine reads **VERIFIED**.
3. **Ground the script against that stored evidence** — either the platform's own writer, OR I
   write the paragraph AND bind every fact to an injected evidence_id via claim_map so it passes
   the FULL `_run_static_script_hold` evidence gate (two-source numeric grounding QL-18/19), not
   just the prose critic. → fully auditable.
4. Then voice → images (now PARALLEL, main 5b7c25c) → render.
- **DE-RISK FIRST:** validate steps 2-3 on ONE machine (e.g. XB-15) on a scratch/new video —
  confirm it shows VERIFIED + the injected card+package clears `_research_card_contract_warnings`
  + a grounded paragraph passes `_run_static_script_hold` — BEFORE doing a full roster.
- **BLOCKED ON:** a title for video #2 (Ryan supplies). Video #1 (bomber) finishes first.

## Definition of Complete (extracted from GOAL.md Phase G + Ryan's 2026-07-15 rulings)

1. **Quality law live:** the 74+2 DvsU quality rules are seeded into `quality_rules` for
   tenant 561b872d and provably control real generations (table-driven gates fire).
2. **3-machine quality proof passes:** XB-15 (fresh provenance-gated research), B-17, B-52
   script previews pass the full law and read like Anton per
   `storyengine/notes/dvsu-paragraph-rubric.md`. (Last live run 2026-07-16: **0/3**, all
   failures writer-side.)
3. **V1 finish line — full bomber video end-to-end:** 23/23 research + scripts, fixed
   narrator voice, one white-studio image per machine (static_docu), Ken Burns render with
   caption/chyron check, 2 thumbnails. MP4 delivered for Ryan's review, **NO upload**,
   within the $20/video cap. Osiris drives the UI; Ryan reviews at gates.
4. **Channel-manager UI loop usable (G3c):** inline card inspectors, editable preview
   paragraphs, no silent-save traps, jump links, batch confirms, DvsU-aware guided banner.
5. **Production (G4):** Anton's first 3–5 real titles through the same flow; 2–3 week
   monitoring armed; thumbnail A/B only after baseline parity.
6. **Docs true again:** GOAL.md Phase G statuses reconciled; stale notes marked superseded;
   open OR rulings recorded in `tasks/decisions.md`.

---

## Status ledger (reconciled: docs × code × live-verification queue)

| Item | State | Evidence |
|---|---|---|
| G1 six tenant prompt slots | **DONE, live** (2026-07-07, 6/6 CUSTOM via API) | GOAL.md:151 |
| G2 fixed narrator voice | **DONE** — but note the original fix caused a cross-tenant voice leak, since fixed by C34b (2026-07-19); C34b's live listen-check is still owed | GOAL.md:154, todo.md C34b, live-queue §C34b |
| C46a–e quality-rules engine | **BUILT + MERGED, code-complete** (generic critic, `quality_rules` table mig 105, DvsU delta gates, trust boundaries, Most-Hated mode, channel_patterns) — extensively unit-tested (252-test machine-documentary suite, zero skips), genuinely wired into `pipeline_executor` | todo.md C46a–C46e, `test_c46c_dvsu_deltas_wiring.py` |
| C46 engine **live for DvsU** | **NO — inert.** `seed_dvsu_quality_rules.py --apply` has never run; `quality_rules` has 0 rows for every tenant. The whole arc controls nothing until seeded | live-queue §C46c/§C46e (all unchecked); seed script's own docstring |
| G3a 3-machine quality proof | **HALF DONE** — research half: 3/3 cards VERIFIED (~$0.10). Script half: **0/3 previews passed**, all writer-side. Never re-run since C46 landed. XB-15 raw package predates the provenance gate → needs a fresh one-machine research pass before preview | GOAL.md:167, runbook doc step 2 |
| G3b missing script laws | **PARTIAL** — shipped: park-don't-halt (C46a), verdict-punch gate (in code), census-format prompt, D1/D2/D3 hardcoded, QL-12 union. **Still open:** preview promotion, category-aware Tavily queries, no-redundancy + spec-block as code-level validators, D4 bare-fact exemption, D5/D6 (QL-18/19 two-source & grounding) | GOAL.md:174 vs todo.md C46c; dvsu-quality-law.md §3 |
| G3c channel-manager UI rework | **OPEN, untouched** (closest adjacent: C46d's Quality Review card, which is a different feature) | GOAL.md:177 |
| G3d full bomber video e2e | **OPEN, untouched** — no DvsU video has ever rendered end-to-end on prod. static_docu + render_static code paths are fully implemented and wired | GOAL.md:180; code audit |
| G4 production (3–5 real titles) | **OPEN, untouched** — gated behind G3a–d | GOAL.md:183 |
| Chyron | **SPEC/CODE GAP** — GOAL.md V1 says "animated chyrons"; code implements a FIXED caption overlay (`captionTitle`/`captionSub` in Scene.tsx); the string "chyron" appears nowhere in code | code audit; needs Ryan ruling |

**Cross-cutting live checks that should ride along with the first paid DvsU runs (from
`tasks/live-verification-queue.md`):** §C34b voice listen-check (stock "Rachel" default vs
tenant override, Slack silence), ElevenLabs real $/1k-char rate confirm, §C46a critic
false-positive watch on first ~5 real scripts, §C46b doc-upload parse round-trip (use
dvsu-quality-law.md itself), §C46d Quality-Review banner in a real browser, RLS-recurrence
watch on `static_reference_cache`/`channel_video_retention`.

---

## The remaining-work chunk queue (dependency-ordered)

Numbered DV-0… (not C66+) to avoid colliding with the parked platform loop's chunk series.
Owner key: **[R]** Ryan-at-computer required · **[A]** agent-buildable in sandbox ·
**[R$]** paid, needs cost quote + yes (or rides the approved $20/video Osiris cap).

- [x] **DV-0 · Seed the quality law live** — **DONE 2026-07-21** (Ryan-approved, via Supabase
  MCP; evidence in live-queue §C46c). All 76 rows live for tenant 561b872d: scope story 49 /
  research 21 / all 4 / most_hated 2; severity hard_gate 53 / warn 16 / guidance 7; pre-write
  count was 0; idempotency proven (re-upsert → still 76, `updated_at` advanced). ⚠ Still owed
  (rides DV-1's first preview run): the post-seed smoke — one real script-hold generation
  showing `_load_dvsu_rule_overrides` firing, QL-12's full banned-word list active, and
  D1/D2/D3 behavior unchanged vs pre-seed.
- [ ] **DV-1 · Re-run the 3-machine proof under the seeded law** [R$ ~$0.50–1] — fresh
  provenance-gated one-machine research for XB-15 (its saved package has 23 legacy excerpts
  without `source_capture_method` — preflight will point at `run_one_machine_research_refresh`),
  then `/machine-script-preview-readiness` → `/machine-script-preview` for XB-15/B-17/B-52.
  Judge vs `dvsu-paragraph-rubric.md`. Output: pass/fail per machine + a failure taxonomy.
  This measures how much of the old 0/3 writer gap C46 + verdict-punch already closed —
  **evidence before building DV-2.**
- [ ] **DV-2 · Close the writer gaps DV-1 still shows** [A; repeat DV-1 until 3/3] —
  candidate list (build only what DV-1's taxonomy demands): preview promotion; category-aware
  Tavily queries; no-redundancy as a code-level validator (today prompt-text only); spec-block
  presence validator (QL-15 is warn-only law text); D4 deliberately-bare memorable-fact
  exemption; D5/D6 (QL-18/QL-19 two-source & grounding, still "in-flight").
- [ ] **DV-3 · G3c channel-manager UI rework** [A] — inline card inspectors on Research +
  Script tabs, editable preview paragraphs, fix silent-save traps, jump links, batch
  confirms, DvsU-aware guided banner. Parallelizable with DV-2. (web-design-system skill
  first, per CLAUDE.md.)
- [ ] **DV-4 · Rulings package for Ryan** [R decision, free] — (a) chyron: accept the fixed
  caption overlay for V1, or build an animated lower-third; (b) record OR-1/2/3/4/7 rulings
  in decisions.md (C46c treats them as "already ruled AND landed" but the law doc shows no
  RULED tag and decisions.md has no entries — genuinely ambiguous); (c) deploy-timing
  question (still unanswered since C37, blocks any coordinated DvsU deploy).
- [ ] **DV-5 · G3d full bomber video end-to-end** [R$ ≤$20, Osiris-driven, Ryan at gates] —
  23/23 research + scripts (full-law revalidation, one paragraph per machine), voice, one
  white-studio image per machine via static_docu (vision-verified reference path), Ken Burns
  render + caption check, 2 thumbnails. MP4 delivered for review, **NO upload**. Ride-along
  live checks: §C34b voice, ElevenLabs rate, §C46a watch, §C46b parse round-trip, §C46d
  banner. Tick the corresponding live-queue boxes as they pass.
- [ ] **DV-6 · Ryan reviews the MP4 vs Anton's real video** [R] — the G3d acceptance gate.
  Verdict gates G4; failures loop back to DV-2/DV-5.
- [ ] **DV-7 · G4 production** [R$ per video] — Anton's first 3–5 real titles through the
  same flow; roster-walk orchestrator (one button per video); warship-title Tavily proofing;
  monitor 2–3 weeks; thumbnail A/B via YouTube Experiments only after baseline parity.
- [ ] **DV-8 · Doc reconciliation** [A, docs-only] — update GOAL.md Phase G to the ledger
  above; mark `dvsu-anton-single-machine-pipeline.md`'s retired four-beat sections superseded
  (todo.md's 2026-07-13 handoff retired that shape, the note was never updated — but the
  doc-lock test `test_dvsu_anton_runbook.py` asserts literal strings in it, so update test +
  doc together); fix dvsu-quality-law.md D8–D11 wording nits; update
  `dvsu-script-prompt-addition.md`'s stale "NOT APPLIED" header.

---

## Blockers & risks

- **The single hard blocker is Ryan-at-computer:** DV-0 (live DB write to a production
  tenant) and every paid run. All agent-buildable work (DV-2/DV-3/DV-8) can proceed in the
  sandbox meanwhile, but DV-2 should wait for DV-1's evidence.
- The platform loop is PARKED (todo.md 2026-07-20) with its own Ryan-only queue (Stripe
  price confirms, sheet auto-split for the Spanish video, etc.) — DVSU work shares the VPS
  and the deploy protocol (`deploy.lock`, `se.sh deploy`), so coordinate sessions.
- Sandbox has no Kie/ElevenLabs keys and no VPS route: DV-1/DV-5 verification is live-only
  by nature; recipes live in `tasks/live-verification-queue.md` §C46c/§C46e/§C34b.
- Two contradictions to not trip over: GOAL.md's flat `[todo]` on G3b undersells real
  progress (don't rebuild verdict-punch/park-don't-halt); the OR-1..4/7 ruling ambiguity
  (DV-4b) should be settled before widening gate surface.
