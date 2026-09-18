# Research-purpose prompt map (read-only diagnosis)

This map describes the current `backend/factual_machine_summary.py` behavior when `generate_factual_machine_summary(..., purpose="research")` runs. That path does **not** build a compiled script packet, so `script_packet` is `None` in its writer and referee calls.

## Writer call

`generate_factual_machine_summary` first obtains `assessment = current_assessment(machine, source_package, subject_context)`, derives up to 60 eligible candidates, and converts them through `_evidence_payload`.

It invokes `_writer_prompt(machine, evidence, prior_issues, prior_draft, subject_context, "research", None, assessment)`. The resulting prompt contains:

- fixed writer rules, locked machine, subject context, repair text, and the requested JSON shape;
- `CLAIM ASSESSMENT`, produced by `json.dumps(claim_assessment, ensure_ascii=False)` with no projection; and
- `EVIDENCE`, a JSON array of the up-to-60 candidate rows. Each row contains `excerpt_id`, `source_id`, `source_title`, `source_url`, `locator`, `source_capture_method`, and complete candidate `text`.

`research_briefings` is set to `None` before the call. The compatibility helper `_compatibility_briefing_context` can only project an outline plus the current paragraph, but neither is serialized on this research invocation.

## Referee call

`review_existing_factual_summary` mechanically validates the draft, derives `_review_alternatives`, then calls `_review_prompt(..., claim_assessment=assessment, script_packet=None)`.

For this non-compiler branch, `_review_prompt` assigns `assessment_payload = claim_assessment` directly. Its `REVIEW PACKET` JSON contains:

- `review_context_version` and `locked_machine`;
- `draft_with_locked_provenance`: paragraph and claim map with each full citation/provenance row;
- `relevant_alternate_fetched_context`: up to `MAX_REVIEW_ALTERNATIVES` (8) full `_evidence_payload` rows; and
- `claim_assessment_constraints_not_evidence`: the complete assessment object, with no compact projection.

The compiler-only helpers `_compact_assessment_constraints`, `_review_packet_constraints`, and `_compiler_review_draft_projection` are not used for research purpose. The latter citation registry is selected only when `script_packet is not None`.

## Why nested history enters both prompts

`research_claim_assessment._narrative_receipt` stores the old receipt as `previous_assessment` inside the newly attempted `claim_assessment`. `current_assessment` returns a copy of the validated receipt with its other keys preserved. Since both research-purpose prompt builders serialize that assessment object wholesale, a nested `previous_assessment` enters both the writer's `CLAIM ASSESSMENT` and referee's `claim_assessment_constraints_not_evidence` payloads. Other retained receipt metadata also enters, including claims and their evidence/counterevidence, `raw_response` when present, `dvsu_recovery`, warnings, fingerprints, and narrative contract fields.

## Existing reusable projections and limits

- `_compatibility_briefing_context` projects legacy briefing rows to `{scene, machine}` outline entries and one current paragraph. It is not an assessment projection.
- `_compact_assessment_constraints` projects only assessment claim ID and status, but only compiler review uses it.
- `_review_packet_constraints` and `_compiler_review_draft_projection` are compiler-review-only projections.
- `_evidence_payload` is reusable but deliberately carries complete source text, so it does not compact research evidence.

`script_research_packet.assert_request_budget` is called immediately before the research writer (`max_tokens=900`) and referee (`max_tokens=1200`). It computes `len((prompt + system_prompt).encode("utf-8")) + 1024` as a conservative input-token upper bound, rejects input above `48,000`, and also rejects input plus reserved output above the `200,000` model-context limit. It does not remove or project payload fields; oversized requests fail before the provider call.
