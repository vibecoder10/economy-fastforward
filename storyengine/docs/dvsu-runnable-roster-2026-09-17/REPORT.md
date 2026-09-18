# Runnable DVSU script roster

The repair connects factual card and batch starts to guarded research preparation. Previously the frontend disabled cards before their server preflight could run, while the batch backend lacked the selected-machine preparation used by previews.

Factual Run Script now reaches its server readiness check even when stored research readiness is incomplete. Preparable evidence can be repaired through the existing durable preview job; hard evidence/identity failures still stop before writing. Run All checks/prepares each assessed machine sequentially, rechecks current state after preparation, reuses current reviewed sections, and respects cancellation, budget and roster changes. The UI counts a production scene only when its saved reviewed block matches actual scene narration; cached previews are labeled separately.

Verification: 67 backend tests; 7 frontend unit tests; 2 rendered Chrome tests using intercepted APIs; frontend typecheck and production build. The browser fixture covers 20 cards, preparation through a completed durable mock job, hard-block/no-extra-POST behavior, batch dispatch, busy controls, and unchanged nonfactual gating. No paid generations were run.

Deployed and verified at f10e8f57048655c27511b05eae91c5910d9296e3. Local/origin/backend/worker parity confirmed; API healthy, frontend200, normal drain and zero active work. Authenticated live Chrome page: all18 remaining Run Script buttons and Run All enabled; 0 production scenes/2 passed previews correctly separated; both preview subtitles correct. Run All confirmation opened and was canceled without dispatch. Final DB hashes and scene count exactly match baseline (preservation.json); no production/research data changed.

Always next: Ryan may run the remaining script cards or Run All. Actual paid generation/content acceptance for the other18 remains unperformed; this release verifies runnable controls and guarded preparation, not that all18 narratives have been generated.
