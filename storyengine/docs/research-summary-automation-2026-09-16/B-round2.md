# B round 2 receipt

Scope: local factual-research summary implementation and focused offline tests only. No provider calls, deployment, production mutation, roster re-selection, or media work occurred.

## Delivered evidence

- `machine_research_summary.py` exports `RESEARCH_SUMMARY_VERSION = 1`, exact summary readiness, and a shared narrow transport classifier. A reusable summary needs a nonempty paragraph, claim map, source list, matching review context, subject context, and source fingerprint.
- The factual hold records every distinct Kie request in `source_discovery_requests`, with singular `source_discovery` fallback and unchanged ledger idempotency behavior.
- Bulk factual hold turns only bounded transport failures into a named failed-unit checkpoint and continues later units. Credential/account/credit/rate-limit, database/concurrency, cancellation, and programming errors rethrow. The shared classifier recognizes a `SourceDiscoveryError` only when its bounded cause chain is a known transport error.
- A generator-reported success is reshaped and rechecked with `research_summary_ready`; malformed output is stored failed with the named claims/citations warning. It cannot pass a unit or aggregate verdict.
- Target and bulk verdict handling materializes the full locked roster. `run_unit_research` recomputes factual readiness and emits named pending warnings and complete counts.
- Script assembly supplies current saved briefing objects in locked scene order through the optional `research_briefings` writer argument.

## Focused offline verification

Command: `backend/venv/bin/python -m pytest -q backend/tests/test_machine_research_summary.py backend/tests/test_factual_machine_summary.py backend/tests/functional/test_factual_machine_pipeline.py backend/tests/functional/test_factual_machine_research.py -k 'not factual_resume_skips_old_g8_anton_surgical_prepass'`

Result: **70 passed, 1 deselected**. The deselected fixture belongs to C's actions/status route ownership and is intentionally not a B acceptance result.

Assertions cover two distinct request IDs producing two ledger calls while a duplicate produces one; current saved-summary reuse with no generator; 20 verdict slots; malformed passed output persisted failed; wrapped timeout recovery versus credits/database nonrecovery; machine-2 timeout still attempting machine 3; and script writer receipt of a saved briefing.

Also passed: `backend/venv/bin/python -m py_compile backend/machine_research_summary.py backend/factual_machine_summary.py backend/factual_machine_pipeline.py backend/pipeline_executor.py` and `git diff --check`.

This is a local implementation receipt for Astra review, not acceptance, deployment, or live all-20 proof.
