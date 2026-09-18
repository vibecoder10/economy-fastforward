Deployment update: release `0229e9fb` is live and verified; see `deployment.json`. The no-spend S-1 readiness check passes. Paid canary/video delivery remain pending. The following sections retain the predeployment implementation evidence.

# DVSU Run All reliability — local implementation review

The authorized offline repair is implemented. It is not deployed, and no new paid generation or upload has run. The intended outcome remains an MP4 Ryan accepts after watching and listening.

## Baseline and preservation

Video `44dbf2b2-a27a-47ea-a608-4c31c906be9a` has 20 locked submarine entries, 20 saved source packages and two saved previews. There are zero production script rows, zero assets and zero active generation claims. Its `ready_for_voice` label is not evidence that the script exists. Reuse saved source packages and eligible reviewed previews; production scripts, voice, visual/audio assets and encoded movie remain to be created after approval. No preview is treated as Ryan's creative acceptance without that evidence.

S-1's package contains two sources and 12 supported claims. All 20 saved packages pass the new evidence-led brief gate offline. This establishes sufficient input to attempt writing, not that generated prose will pass factual or human review.

`baseline-summary.json` records original hashes. `preservation.json` confirms identical fresh database records for the video, cards, scripts, assets, preview jobs, claims and ledger. Raw readback snapshots are local diagnostic material and excluded from the release patch. `replay-fixtures.json` contains the saved source packages and required replay inputs without credentials.

## Implemented

- Evidence-led 100-word target, 80–110 hard range; four editorial categories are optional guidance. Identity, citations, contradictory evidence and claim support remain checked. Valid prior editorial receipts are accepted without a version-triggered rewrite.
- Preview and full Script consume saved evidence. A real insufficiency reports Research review; missing category labels do not launch discovery. Independent ready sections can complete while insufficient sections remain blocked.
- Source requests have durable operation identity, sanitized response receipts before parsing, typed failures, one malformed-response retry and two explicit transient retries at most. Attempt counters survive restarts. Unknown paid submissions require reconciliation. URL/fetched-page evidence restrictions remain.
- A compare-and-swap source journal prevents duplicate submission and records known Kie usage before another request. Failed critical checkpoints stop execution. Unmetered prior responses block further budgeted source retries.
- DVSU writer/referee calls are individually journaled and replay saved responses by request/input fingerprint. SDK and wrapper resubmission are disabled for these calls. An unresolved call or failed response save stops for reconciliation.
- Task changes are scoped by tenant, video, stage and job identity. Required start persistence precedes executor work; adapter retry policy is not multiplied by queue retries. UI error markers are stripped and typed details are retained.
- Voice requires matching reviewed production scenes. Previews, production promotion and human acceptance remain distinct.

## Evidence and limits

`final-verification.log` records 229 passing focused backend tests; `verify.sh` reproduces it. Frontend: 16 tests across two files, TypeScript check and production build passed (`frontend-*.log`). `final-task-tests.log` and `script-checkpoint-final.log` cover the final ownership/response-save corrections. `git diff --check` passes.

The Run All replay exercises the real coordinator from roster/research through script/voice/images/thumbnail/render with stage/provider/database stubs. Separate real executor/adapter tests verify saved S-1 routing, artifact guards, retry budgets, cancellation, task isolation, partial completion and saved-media reuse. Upload retry/idempotency tests run offline only. This is control-flow evidence, not live provider or encoded-media evidence.

Two additional existing roster-settings tests fail on a clean `9e77c2cb` checkout as well: `test_guide_does_not_confuse_roster_with_detailed_research` and `test_roster_ready_worker_message_does_not_claim_detailed_research`. See `baseline-roster-settings-tests.log`. They are not counted as passing and remain outside this scoped repair.

Database journal tests use stubs; migration application, real database concurrency, deployed browser behavior and backend/worker parity must be verified during release. The UI has not been walked against a deployed version of this repair. Anthropic response text is durable, but the current string-returning client does not expose its actual billable usage to the script ledger. The generic $0.02 script estimate is not a reliable factual-script budget. Use the bounded canary procedure in RELEASE.md; do not authorize an uncapped full run from that estimate.

## Review rounds and next gate

Round 1: bounded Terra writing, source and ownership implementations; Astra found legacy forced-research expectations, incomplete strict task-start persistence, voice advancing on labels, and hidden SDK/client retries. Corrections were prescribed within the same feature.

Round 2: bounded Terra corrections and Astra integration/review; durable script-response handling and final checkpoint-error corrections are included. Offline scoped checks pass. Overall product DoD remains open.

Always next: approve and perform the scoped deployment, verify migrations/health/worker parity/browser, then request a separate capped S-1 paid writing canary. Preserve the two existing previews and all 20 evidence packages. After S-1 quality review, quote the remaining generation, complete the encoded MP4, verify playback/audio/synchronization, register it in AgentVault Generations, and obtain Ryan's watching/listening acceptance.

Market checkpoint: Ryan is the initial editor. Use the existing StoryEngine UI for the saved project; record each manual intervention and rejected section. The offline work does not yet prove completion without developer intervention.
