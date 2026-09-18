# Package A round 3 receipt — portable roster-label fixture

Scope: Package A test packaging only. No implementation behavior, provider request, deployment, production mutation, or saved-source snapshot mutation was made.

Extracted the locked 20 class labels into `backend/tests/fixtures/research-roster-class-labels.json`. `backend/tests/test_research_class_identity.py` now reads that portable fixture and no longer depends on the audit-only `saved-source-packages.jsonl` document.

Offline verification:

`backend/venv/bin/python -m pytest backend/tests/test_research_class_identity.py backend/tests/functional/test_kie_factual_source_search.py -q`

Result: `18 passed`. `git diff --check` passed. A repository search confirms the focused class-identity test references only the new fixture, not the audit snapshot.
