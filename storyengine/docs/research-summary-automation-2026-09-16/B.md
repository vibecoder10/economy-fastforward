# Package B receipt — saved factual research summaries

Status: local implementation and focused offline verification complete. No
provider call, production mutation, source gathering, or deployment occurred.

Implemented:

- Added `backend/machine_research_summary.py` with
  `RESEARCH_SUMMARY_VERSION = 1`, `research_summary_ready(...)`, and saved
  summary shaping. Currentness requires passed status, prose, nonempty
  claim-map and sources, current review version, exact subject context, and the
  `factual_machine_pipeline.source_fingerprint` for the raw package.
- Extended `generate_factual_machine_summary` with backward-compatible
  `purpose="script"` and optional `research_briefings`. Research uses the same
  source-grounding/referee path but is prompted as a briefing; script prompts
  label saved briefings as context only and retain fetched excerpts as evidence.
- Added factual briefing collection/readiness helpers in
  `factual_machine_pipeline.py`; briefings preserve locked roster/scene order.
- Updated factual `_run_unit_research_hold` to require a current
  `card["research_summary"]` before skip, create/checkpoint a briefing when
  stale or absent, retain failed briefing warnings, and upsert a failed compact
  verdict instead of treating excerpt-only evidence as success.
- Updated factual hold validation to materialize every locked-roster unit when
  the factual path reports a verdict, so a partial verdict list cannot pass the
  whole roster. Exact roster-index identity avoids normalized-code collisions.
- Extended factual card revalidation: existing excerpt-only cards remain
  resumable, but a card that has a failed/stale `research_summary` yields a
  blocking warning and cannot be rewritten as passed by the no-spend readiness
  endpoint.

Focused offline verification:

```text
backend/venv/bin/python -m pytest -q \
  backend/tests/test_machine_research_summary.py \
  backend/tests/test_factual_machine_summary.py \
  backend/tests/functional/test_factual_machine_pipeline.py \
  backend/tests/functional/test_factual_machine_research.py \
  -k 'not factual_resume_skips_old_g8_anton_surgical_prepass'

66 passed, 1 deselected
```

The deselected functional assertion is in package C's autobuild-status area;
it currently conflicts with that concurrent package's changed task-status
semantics and was not altered here. `git diff --check` passed.
