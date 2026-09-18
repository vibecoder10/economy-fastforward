# Writer contract evidence

- Implemented the evidence-led editorial v2 contract in the bounded writer files.
- A nonempty supported fact packet is ready even when narrative categories are absent; `missing_narrative_roles` records those advisory gaps while `missing_fields` contains only blockers.
- Preserved the 80–110-word, identity, claim-map/citation, and factual clause-audit gates. Removed the separate closing-verdict form and length gate.
- Valid editorial v1 receipts remain accepted; new reviews emit v2 with `evidence_led`, `coherent`, and `spoken_style` checks.

Verification: `backend/venv/bin/python -m pytest backend/tests/test_dvsu_script_brief.py backend/tests/test_dvsu_script_writer.py -q` — 18 passed. Full output: `writer-tests.log`.

## Saved-evidence replay verification

- Replayed the saved SS-105 USS S-1 source package and baseline card offline. Its current assessment, compact brief, and compiled packet all resolve from saved evidence with no provider.
- The real preview entrypoint reaches the writer hold using that saved package and makes zero `run_one_machine_research` calls.
- A mutated saved citation invalidates the assessment and blocks readiness.
- Updated prior automatic-preparation and missing-category expectations to the no-preparation/evidence-led contract. No `test_runnable_factual_roster.py` exists; the discovered batch coverage is `backend/tests/functional/test_factual_machine_pipeline.py`, which was inspected but not edited because this bounded step did not require a change there.

Verification: `backend/venv/bin/python -m pytest backend/tests/test_dvsu_script_brief.py backend/tests/test_dvsu_global_handoff.py backend/tests/test_dvsu_research_handoff.py backend/tests/test_dvsu_saved_evidence_replay.py -q` — 31 passed. Full output: `writer-replay-tests.log`.

## Integration contract refresh

- Replaced legacy automatic-preparation expectations in the authorized factual batch suite with no-research `needs_review` outcomes.
- Retained the fresh-state safeguards by mutating cancellation, budget, and roster state during the readiness callback; the batch rechecks each before writing.
- Baseline export readback covered all 20 saved roster packages offline: 20 ready, 0 gaps, 0 research/provider calls.

Verification: `backend/venv/bin/python -m pytest backend/tests/functional/test_factual_machine_pipeline.py backend/tests/test_dvsu_role_quality.py backend/tests/test_dvsu_saved_evidence_replay.py -q` — 36 passed. Full output: `writer-integration-tests.log`.

## Replay fixture packaging

- Added `replay-fixtures.json` with the exact saved twenty source packages, title, roster, and SS-105 research card used by the replay tests.
- The committed replay test no longer reads `baseline-video.json` or `baseline-cards.json`; those remain local evidence exports.

Verification: `backend/venv/bin/python -m pytest backend/tests/test_dvsu_saved_evidence_replay.py -q` — 4 passed. Full output: `writer-replay-tests.log`.
