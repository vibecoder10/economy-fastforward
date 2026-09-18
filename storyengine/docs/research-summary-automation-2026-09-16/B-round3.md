# B round 3 receipt

This final local B repair closes two Astra-reviewed correctness gaps. No provider calls, deployment, production mutation, roster re-selection, or media work occurred.

- Bulk factual hold now reads the target unit's stored warnings after each per-machine return. A raw or card checkpoint `UPDATE 0` writes `checkpoint refused` on that unit and returns before the next locked machine.
- `run_unit_research` now derives factual pending diagnostics from `factual_research_readiness(payload, [machine], title)`, not cached `unit.passed`. A stale or missing saved summary therefore reports its machine with either retained unit warnings or `factual research summary pending`, and cannot save `ready_for_scripting`.

Focused verification command:

`backend/venv/bin/python -m pytest -q backend/tests/test_machine_research_summary.py backend/tests/test_factual_machine_summary.py backend/tests/functional/test_factual_machine_pipeline.py backend/tests/functional/test_factual_machine_research.py -k 'not factual_resume_skips_old_g8_anton_surgical_prepass'`

Result: **72 passed, 1 deselected**. New direct assertions prove machine 3 is not gathered after a machine-2 raw checkpoint conflict, and an all-true stale verdict returns named summary-pending diagnostics while retaining `idea_logged`. `backend/venv/bin/python -m py_compile backend/pipeline_executor.py` and `git diff --check` also passed.

The deselected fixture belongs to C ownership. This receipt is local evidence for Astra review; production and live all-20 verification remain unproven.
