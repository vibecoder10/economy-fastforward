# Probability consumption map

Scope: source-only audit of the consumption path at checkout `f92c863b550dcf5cd3a72e351d045b554ef8fdcf`. No providers, runtime endpoints, production state, or tests were run. “Probability” below means an explicit numeric/probabilistic estimate, not the codebase’s descriptive use of words such as *confidence* or *calibration*.

## Persistence and state

1. Migration 081 creates the tenant- and video-scoped `machine_research_cards` checkpoint. A row holds the operational `card` JSON and a separate `validation` JSON; migration 081 originally keys on `machine_key` and makes roster index unique; migration 153 changes the primary key to `(tenant_id, video_id, roster_index)` ([migration 153:33](../../backend/migrations/153_machine_research_cards_roster_index_identity.sql#L33)). Raw research/media are expressly outside the table ([backend/migrations/081_machine_research_cards.sql:10-26](../../backend/migrations/081_machine_research_cards.sql#L10-L26), [47-48](../../backend/migrations/081_machine_research_cards.sql#L47-L48)). The same migration says `videos.research_payload.unit_research_cards` remains dual-written for compatibility ([1-2](../../backend/migrations/081_machine_research_cards.sql#L1-L2)).

2. The executor loads compact rows in locked-roster order and overlays only cards whose stored identity matches the roster slot. A failed stored validation is deliberately omitted from the trusted-card merge but carried in `_dropped_failed_research_card_validations` with its warnings ([backend/pipeline_executor.py:9940-10036](../../backend/pipeline_executor.py#L9940-L10036)). Card writes upsert both card and validation under that same slot identity ([10058-10095](../../backend/pipeline_executor.py#L10058-L10095)).

3. Every served `research_payload` can be enriched from the compact table: `validation` becomes `card.readiness = {passed, warnings}`. The enrichment retains failed cards for display and yields `readiness=None` where there is no stored verdict ([backend/pipeline_executor.py:4330-4345](../../backend/pipeline_executor.py#L4330-L4345), [4357-4395](../../backend/pipeline_executor.py#L4357-L4395)).

4. Aggregate unit research rereads compact validation rows, counts only `passed` slots, persists `unit_research_hold_validation` plus a summary report into `videos.research_payload`, and sets status to `ready_for_scripting` only when the reconciled validation passes ([backend/pipeline_executor.py:12283-12355](../../backend/pipeline_executor.py#L12283-L12355)). Separately, the top-level research save writes `research_payload`, `thesis`, `executive_hook`, and the conditional next status; a failed roster or unit-research hold returns without the transition ([11246-11326](../../backend/pipeline_executor.py#L11246-L11326)).

## UI consumption and uncertainty

1. `ResearchTab` treats backend-owned `card.readiness` as the only readiness source. Its three user-visible states are verified, revalidation needed (no verdict), and blocked with stored warnings ([frontend/src/components/production/ResearchTab.tsx:708-730](../../frontend/src/components/production/ResearchTab.tsx#L708-L730)). Each roster row renders those states and exposes its warnings; it offers repair or rerun actions for an unverified card ([1648-1723](../../frontend/src/components/production/ResearchTab.tsx#L1648-L1723)).

2. The tab counts verified cards against the locked roster and disables “Approve Research” until the full-machine gate passes ([frontend/src/components/production/ResearchTab.tsx:1382-1455](../../frontend/src/components/production/ResearchTab.tsx#L1382-L1455)). The approval handler independently repeats that check before calling `advanceVideo` ([1199-1227](../../frontend/src/components/production/ResearchTab.tsx#L1199-L1227)).

3. The no-spend readiness endpoint loads the compact/legacy card, enriches the returned payload, recomputes blocking evidence warnings, and updates only the stored validation verdict. The response exposes `ready`, `warnings`, and `next_action` ([backend/pipeline_executor.py:16250-16344](../../backend/pipeline_executor.py#L16250-L16344)); the route confirms it makes no provider call ([backend/routes/pipeline.py:1221-1238](../../backend/routes/pipeline.py#L1221-L1238)).

4. The stage rail consumes aggregate status as an operational count—ready cards versus locked roster—not a probability. It blocks Script until Research is done ([frontend/src/components/production/StaticDocuStageRail.tsx:119-153](../../frontend/src/components/production/StaticDocuStageRail.tsx#L119-L153), [225-252](../../frontend/src/components/production/StaticDocuStageRail.tsx#L225-L252)).

## Research-to-script handoff

1. The public script route admits a video only at or past `ready_for_scripting`, then invokes `PipelineExecutor.run_script` asynchronously ([backend/routes/pipeline.py:1140-1193](../../backend/routes/pipeline.py#L1140-L1193)).

2. `run_script` parses `research_payload` and recomputes the live roster gate before work; a failed complete-title gate returns “Fix research roster before scripting” ([backend/pipeline_executor.py:16581-16607](../../backend/pipeline_executor.py#L16581-L16607)). A locked static-documentary roster then takes `_run_static_script_hold`, rather than the generic script generator ([16751-16772](../../backend/pipeline_executor.py#L16751-L16772)).

3. The static hold’s successful persistence replaces script rows while writing `videos.script` and `script_validation` in one statement, then advances to `ready_for_voice` only after its roster check passes ([backend/pipeline_executor.py:15322-15377](../../backend/pipeline_executor.py#L15322-L15377)). A single-machine preview is explicitly isolated from production script rows/status at the route boundary ([backend/routes/pipeline.py:1196-1218](../../backend/routes/pipeline.py#L1196-L1218)).

## Calibration, probability, and evaluator-feedback search coverage

Bounded search targets were `backend/pipeline_executor.py`, `backend/routes/pipeline.py`, migration 081, `ResearchTab.tsx`, `ScriptVoiceTab.tsx`, `StaticDocuStageRail.tsx`, `frontend/src/lib/api.ts`, and related backend tests. Searches were case-insensitive for `probability`, `calibration|calibrate`, `evaluator_feedback|evaluator feedback`, `feedback`, `confidence`, `research_payload`, `machine_research_cards`, and `script_validation`.

* No explicit probability value, probability distribution, calibration record/table, or evaluator-feedback field was found in the bounded research-card persistence, UI readiness, or script-handoff path. The consumed readiness signal is boolean plus warning text.
* “Confidence” is displayed for a roster audit in the Research UI, but this is a descriptive payload field rather than a probability consumed by the card-to-script gate ([frontend/src/components/production/ResearchTab.tsx:1529](../../frontend/src/components/production/ResearchTab.tsx#L1529)). The script tab’s only local “calibration” copy is inside a dead `false &&` preview block ([frontend/src/components/production/ScriptVoiceTab.tsx:2611-2617](../../frontend/src/components/production/ScriptVoiceTab.tsx#L2611-L2617)).
* Creator “Request Changes” saves free text to `videos.revision_notes` through the generic video PATCH, whose allowlist includes that field ([frontend/src/components/production/ResearchTab.tsx:2181-2223](../../frontend/src/components/production/ResearchTab.tsx#L2181-L2223), [backend/routes/videos.py:881-891](../../backend/routes/videos.py#L881-L891)); the schema migration only adds that text column ([backend/migrations/011_revision_notes.sql:1-2](../../backend/migrations/011_revision_notes.sql#L1-L2)). Within the bounded consumption targets, no read of `revision_notes` into research-card readiness or the static-documentary script hold was found.

## Existing test evidence

* `test_machine_documentary_hold.py` proves a failed compact verdict is preserved as the real aggregate warning rather than relabeled as a missing card ([backend/tests/test_machine_documentary_hold.py:2740-2759](../../backend/tests/test_machine_documentary_hold.py#L2740-L2759)).
* The same suite asserts an isolated preview may save preview/brief/plan artifacts while neither inserting/deleting `scripts` nor writing `script_validation`; it also asserts response readiness enrichment queries the compact verdict table ([5948-6013](../../backend/tests/test_machine_documentary_hold.py#L5948-L6013)).
* `test_run_all_research_resume.py` asserts coverage feedback is injected into corrective discovery before the unit-research handoff ([backend/tests/functional/test_run_all_research_resume.py:169-198](../../backend/tests/functional/test_run_all_research_resume.py#L169-L198)). This is corrective gate feedback, not a persisted evaluator-feedback or probability-calibration loop.

## Limits

This maps source behavior only. It does not establish that migration 081 is applied, that compact and legacy payloads are synchronized in a live database, that the UI is currently deployed, or that the cited tests pass in this checkout.
