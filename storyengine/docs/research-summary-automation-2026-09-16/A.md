# Package A receipt — identity and source discovery

Scope: local Package A implementation only. No provider request, deployment, production mutation, or source-snapshot mutation was made.

## Implemented

- `backend/factual_machine_research.py` adds `factual_research_subject`, which removes only a leading naval hull/range bookkeeping prefix while keeping the locked display identity unchanged. The factual candidate matcher now accepts a punctuation-tolerant full class phrase, or a distinctive lead-vessel name together with an exact locked hull. A single-hull lead can use the saved-source sentence context only when that same sentence ties the name to a Navy submarine event; the rule has no machine-name exceptions.
- `backend/factual_source_search.py` accepts the normalized subject while retaining the original locked identity in the Kie prompt. Optional prior-URL and unreadable-host inputs constrain one alternate wave and are recorded in its receipt.
- `backend/pipeline_executor.py` uses the factual matcher only in `_gather_verified_machine_source_package` and in its optional sentence matcher. A factual gather that has no exact-subject excerpt makes exactly one alternate Kie discovery request, preserving first-wave evidence and avoiding previously attempted URLs and wholly empty-capture hosts. The legacy matcher default and Tavily path are unchanged.
- `backend/tests/test_research_class_identity.py` covers all 20 saved labels, class punctuation, Gato/Balao, S-class/generic wording, named-lead-plus-hull, Albacore, Holland source context, and person/designer negatives. `backend/tests/functional/test_kie_factual_source_search.py` covers the bounded alternate Kie wave and its two receipts.

## Offline evidence

`backend/venv/bin/python -m pytest backend/tests/test_research_class_identity.py backend/tests/functional/test_kie_factual_source_search.py -q`

Result: `18 passed`.

`backend/venv/bin/python -m py_compile backend/factual_machine_research.py backend/factual_source_search.py backend/pipeline_executor.py` and `git diff --check` both passed.

The read-only saved-source replay now finds two traceable exact-subject Holland excerpts and returns no package warnings for `SS-1 Holland class`; it makes zero provider calls.

## Shared-work note

An earlier combined run that included `backend/tests/functional/test_factual_machine_research.py` had eight failures in concurrently changed Package B factual-summary behavior around `pipeline_executor.py:12953`, where its fixtures provide no Anthropic client. Package A did not edit that B-owned range or its tests. No Package A plan gap remains.
