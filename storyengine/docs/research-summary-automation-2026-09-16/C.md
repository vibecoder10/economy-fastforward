# Package C receipt

Implemented the bounded factual Run All path in `backend/actions.py` and durable task handling in `backend/routes/pipeline.py`.

- Factual runs enumerate the saved locked roster, including empty/partial hold verdict lists; excerpt-only cards remain pending.
- The runtime selected-roster path uses bounded one-machine research directly, reuses versioned attempt counters, and does not first invoke bulk unit research.
- A completed worker result is read back from the saved card/source package before counting; final readiness also requires the locked roster to be unchanged.
- Known transport/service failures are converted to a bounded factual card review and continue other independent machines through the shared classifier. Account, budget, database, and unknown errors still stop.
- `needs_review` is persisted as `failed`; app-authored factual diagnostics retain the machine and Research next action through error humanization.

Validation: `./venv/bin/python -m pytest tests/test_research_automation_status.py tests/functional/test_frontdoor_needs_review_surfacing.py tests/functional/test_g8_roster_research_loop.py -q` — 35 passed. `./venv/bin/python -m py_compile actions.py routes/pipeline.py` passed. No provider, API, or production action was run.
