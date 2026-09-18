# Submarine source-assessment map

Scope: read-only inspection for `factual_100_v1`. This records current data
shapes and bounded attachment points for source-backed **confidence and
conflicts**. It does not choose a final schema, add probabilities, run a
provider, or change readiness behavior.

## Existing source and citation truth

1. `factual_machine_research._candidate_traceable` at lines 111-126 accepts an
   excerpt only when it has `excerpt_id`, exact `text`, `source_url`, a locator,
   and an approved capture method. It rejects Grokipedia. `candidate_mentions_machine`
   at lines 129-184 applies the locked-machine/class/named-vessel identity guard.
2. `useful_factual_candidates` at lines 187-222 filters to those traceable
   exact-machine excerpts, de-duplicates `(source_url, text)`, and prefers one
   excerpt per URL before additional excerpts. This is the narrowest safe source
   input for an assessment pass.
3. `build_factual_evidence_card` at lines 239-265 copies each selected source
   verbatim into `evidence_segments`. The durable anchors are:
   `source_excerpt_id`, `source_id`, `source_url`, `source_title`,
   `source_capture_method`, `locator`, `numeric_tokens`, and both exact-text
   fields `claim`/`source_excerpt`. It currently sets every segment
   `confidence: "high"` at line 257, even though this denotes no separate
   support or conflict judgment.
4. `factual_card_contract_warnings` at lines 268-302 re-derives candidates from
   the current package and rejects changed text, source URL, locator, or numeric
   tokens. It does not currently validate `confidence`, classify conflicts, or
   preserve a per-claim assessment object.

## Existing summary and citation review hooks

1. `factual_machine_summary._eligible_candidates` at lines 60-104 uses the
   same factual candidate guards, keeps `source_id`, URL, locator, capture
   method, and exact text. `_evidence_payload` at lines 310-322 presents those
   fields and exact text to the writer.
2. `_validate_draft` at lines 194-307 binds every prose sentence to one or
   more candidate `excerpt_id`s. It requires explicit legacy quote text to be
   an exact substring, then records the resulting `sources` provenance as
   `excerpt_id`, `source_id`, title, URL, locator, exact `quote`, and capture
   method (lines 262-281). This is the existing place where exact source quotes
   survive into a saved research/script summary.
3. It already flags unsupported numbers and applies a narrow record/count
   corroboration rule (lines 282-306): one tier-1/2 source or two hostnames.
   This is a source-host proxy only; it records warnings and optional sentence
   removal, not an evidence-family or competing-claim assessment.
4. `_review_alternatives` at lines 333-391 chooses up to the bounded alternate
   excerpts by token/number/high-risk overlap and URL diversity. `_review_prompt`
   at lines 449-486 tells the referee to distinguish true conflicts from
   different milestones/scopes. `review_existing_factual_summary` converts a
   rejection into strings in `warnings`, then may remove the exact disputed
   sentences (lines 537-604). It does **not** save a structured conflict, the
   alternate sources considered, or a reviewer assessment per claim.
5. `_writer_prompt` at lines 394-445 tells the writer to omit disputed optional
   records and uses only `EVIDENCE`. Its `research_briefings` argument is
   context-only. The factual writer/referee result returned at lines 605-614
   contains paragraph, claim_map, sources, warnings/pass, review version, and
   subject context; no confidence/conflict field is retained.

## Persistence, fingerprints, cache readiness, and writer consumption

1. `source_fingerprint(machine, package)` in `factual_machine_pipeline.py:22-26`
   hashes the complete package plus exact machine and contract. If assessments
   are embedded in the verified source package, source changes automatically
   invalidate both research-summary and script caches. If assessments live only
   on the card/summary, this fingerprint will *not* notice changes; a separate
   assessment fingerprint/version must then be part of the relevant readiness
   tests.
2. `machine_research_summary.saved_research_summary` at lines 82-100 is the
   fixed saved summary projection. It currently drops any new assessment fields.
   `research_summary_ready` at lines 54-79 requires only schema version, passed
   prose/claim_map/sources, review context, subject context, and source
   fingerprint. A new assessment stored with a research summary needs an
   explicit projection here plus schema/readiness versioning; otherwise it can
   disappear or stale assessments can remain ready.
3. The research hold gathers/reuses the package at
   `pipeline_executor.py:13024-13068`, builds the factual card at 13071, creates
   the research briefing at 13077-13108, and checkpoints the card at
   13121-13135. This is the smallest production attachment window: assess the
   verified package after it is available and before the card/summary are built;
   attach an immutable assessment receipt to the chosen owner; then make card
   and summary projection/readiness consume it.
4. `PipelineExecutor._research_card_warnings` (4214-4233) already funnels the
   factual card and research-summary readiness warning into hold validation.
   That is the bounded readiness/UI failure path for an invalid, missing, or
   stale assessment without treating it as a source-fetch failure.
5. `current_research_briefings` in `factual_machine_pipeline.py:29-49` emits
   only `{machine, scene, paragraph, claim_map, sources}` for ready summaries.
   `run_factual_script_hold` collects it at line 109 and passes it to the writer
   at lines 219-223. An assessment intended to influence later writing must be
   deliberately included in this emitted briefing (with allowed wording and
   conflicts), rather than assuming the current paragraph or provenance carries
   it.
6. Script blocks persist `source_fingerprint` at lines 172 and 225-228; both
   saved-block reuse and `factual_script_readiness` at lines 57-76 require it.
   Assessment changes embedded in `package` invalidate this exact path. A
   summary-only assessment would need an analogous fingerprint/readiness gate
   before any script reuse can be trusted.

## Bounded integration points for Astra's schema decision

* **Assessment input/output:** consume only the current verified package's
  `candidate_excerpts` after the factual traceability/identity filters; key each
  assessment to `excerpt_id` plus the existing source anchors. Preserve source
  text as-is. Add source-family/lineage only as sourced/unknown metadata, never
  infer it from hostname alone.
* **Card projection:** replace the unconditional semantic meaning of
  `confidence: "high"` with a separately versioned assessment projection, or
  preserve that field for backward compatibility and add explicit
  `provenance_status`, `support_status`, `conflict_status`, and
  `confidence_status` fields. `factual_card_contract_warnings` is the exact
  contract check to validate that projection against its source anchors.
* **Summary/review projection:** attach claim-level assessment IDs/statuses to
  `_validate_draft`'s normalized claim-map/source provenance and expose relevant
  conflicts to `_writer_prompt` and `_review_prompt`. Keep `sources[].quote`
  unchanged; assessment text must point to, not replace, original excerpts.
* **Staleness:** prefer embedding an immutable assessment receipt/version in
  the verified package so existing `source_fingerprint` invalidates all cached
  research and script summaries. If that ownership is rejected, add an explicit
  assessment fingerprint/version to `saved_research_summary`,
  `research_summary_ready`, saved script blocks, and `factual_script_readiness`.
* **Readiness:** retain current factual pass/fail behavior initially in shadow
  mode. Surface `sources captured`, `conflict/disputed`, and `ready to script`
  separately through existing hold warnings/summary state. Do not turn a source
  quote, source tier, URL count, or reviewer pass into a numeric probability.

## Current failure modes relevant to this change

* Traceable excerpts are stored as `confidence: "high"` without a support or
  conflict evaluation (`factual_machine_research.py:239-258`).
* URL diversity and two-host corroboration can stand in for independence;
  provenance records no origin/family/lineage.
* Conflicts found by the referee become transient warning strings and may cause
  sentence deletion. Competing evidence and the decision rationale are not
  persisted for the card or UI.
* `saved_research_summary` and `current_research_briefings` drop all unknown
  fields, so adding an assessment to an intermediate result alone cannot reach
  writer context or readiness.
* Current fingerprints cover exact package content, not a card-only assessment;
  such a design would permit stale ready summaries and script blocks.
* Alternate-evidence ranking optimizes lexical/numeric relevance, not explicit
  contradiction, claim scope, or source lineage.

