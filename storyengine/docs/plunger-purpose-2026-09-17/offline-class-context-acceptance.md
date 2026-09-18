# SS2 class-context offline acceptance

This receipt used the saved SS2 package and saved PigBoats page with the production extractor, merge function, candidate gate, assessment prompt builder, writer prompt builder, and input-budget helper. It made no model, provider, network, database, or live write.

- The extractor returned one verified contiguous class context of 5,565 characters. `_sentence_candidates_from_source` returned that exact one candidate.
- The source-to-merge path grew the package from 6 to 7 sources and from 24 to 25 excerpts. The merged text is byte-equal to the extracted candidate and retains double-newline section boundaries.
- The new candidate is identity-pending with `context_scope=class_design`; it is excluded from ordinary writer eligibility until a current, saved same-claim identity review connects it to a separate exact-hull anchor. The saved package supplies 24 strict exact-machine anchors.
- The assessment builder includes the pending context in its 25 candidates: 34,990 prompt bytes and 36,014 conservative input bytes including the helper's 1,024-byte allowance. Assessment currently does not invoke this helper in production; this is a direct builder measurement.
- The production research-summary writer serializes `_evidence_payload`, not raw candidate dictionaries, and uses all normal eligible candidates capped at 60. The current saved package is 31,740 conservative input bytes. The conservative upper-bound measurement that includes the pending class-context candidate and the current 10-claim assessment projection is 37,621; both pass the 48,000-byte input guard.

The pending upper bound does not assert a new supported claim or valid assessment. A normal assessment and saved identity review remain required before the class context can enter a writer request.

Relevant combined regression files:

- `backend/tests/test_factual_class_context.py`
- `backend/tests/test_factual_source_prefix.py`
- `backend/tests/test_factual_source_sections.py`
- `backend/tests/test_contextual_source_identity.py`
- `backend/tests/test_dvsu_research_prompt_budget.py`
- `backend/tests/test_dvsu_targeted_discovery.py`
- `backend/tests/functional/test_kie_factual_source_search.py`
- `backend/tests/test_factual_pdf_source.py`
- `backend/tests/test_factual_machine_summary.py`
- `backend/tests/test_script_compiler_integration.py`
