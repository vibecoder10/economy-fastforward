# Step B — pipeline integration, round 2

Implemented the assessed factual Script path in `backend/factual_machine_summary.py` and `backend/factual_machine_pipeline.py`.

- Assessed scripts compile the current machine's eligible evidence into a deterministic packet before writing. The writer receives selected facts, compact outline, and optional current-machine research paragraph only; legacy full-roster briefing objects are whitelisted to names/scenes and never serialized.
- Generated claim maps carry `fact_ids`; code materializes authoritative citations before existing mechanical validation. The independent referee receives draft citations, selected-fact constraints, compact ledger status, and relevant alternate evidence. Legacy research review preserves its full claim-assessment constraint behavior.
- Writer and referee requests use the conservative UTF-8 upper-bound preflight. Packet, materialization, or preflight failure returns a reviewable failed result without calling a provider.
- The pipeline recomputes the expected packet from current model, source package, assessment, outline, and current paragraph. Assessed accepted blocks require the matching compiler version/fingerprint to be current; matching saved blocks and passed previews reuse/promote without model calls. Old assessed blocks are retained only as bounded repair wording, never accepted under the new contract.

Validation: canonical backend virtualenv `py_compile` passed. Focused existing summary/pipeline tests passed 52 tests; one directly affected old test still asserts the removed full-roster `research_briefings` writer argument and is being updated by Step C.

Limits: no provider, database, network, deployment, or live-video writes were performed.

## Round 3 — compiler referee packet size repair

The compiler-only referee prompt now serializes repeated draft citations through a lossless `citation_evidence_registry`. Each outbound claim-map citation is an `evidence_id`; the registry contains the complete unchanged provenance and exact quote once, keyed by a stable SHA-256-derived identifier. The referee is explicitly instructed to resolve each ID and verify each sentence against its own `fact_ids`. Stored drafts, citations, mechanical validation, alternates, and legacy non-compiler review serialization are unchanged.

The assessed checkpoint selector also prioritizes a newer matching failed preview over an older saved block, preserving its exact repair warnings. Stale-packet or stale-approved blocks remain unapproved repair input.

Narrow offline projection check: four rows repeating a 12,000-byte exact quote reduced outbound serialized bytes from 48,975 to 12,692 with one registry row; every projected citation resolved to the unchanged quote. `py_compile` and diff whitespace checks passed. No provider or external writes occurred.
