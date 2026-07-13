# DVsU Anton Single-Machine Pipeline

## Source Materials Mapped

- Anton reference script: `/Users/ryanayler/Desktop/Designed vs used/TOP VIDEO SCRIPTS/Every US Strategic Bomber Ever Built.docx`
- Writing system: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Script_Writing_System.md`
- Research standard: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Research_Fact_Verification_Standard.md`
- Producer/voice standards: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Producer_File_Standard.md`, `/Users/ryanayler/Desktop/Designed vs used/DvsU_Voiceover_File_Standard.md`

## Anton Paragraph Pattern From First Three Strategic Bombers

1. Original problem: raw excerpt for the need, requirement, or situation that forced the machine into the story.
2. Engineering decision: raw excerpt for the design, procurement, or technical answer.
3. Tradeoff: raw excerpt for the sacrifice, limitation, compromise, or unintended consequence.
4. Reality: raw excerpt for what happened in testing, production, service, or combat.
5. Editorial thesis: the single engineering decision, tradeoff, or contrast that tells the writer why these facts belong together.
6. Paragraph-derived conclusion: a short landed final sentence based only on the assembled paragraph, not a pre-researched meaning beat.

The paragraph is still one natural 90-120 word unit for this proof. Anton's general DVsU standard says 95-120 words, but the actual first XB-15 benchmark paragraph is 94 words; the validator keeps a narrow 90-word floor so the system can imitate the real bomber reference shape instead of rejecting it. The internal structure is not a visible four-beat scaffold, and the saved `editorial_thesis` is not narration. It is the compiler's required declaration that the paragraph is about an engineering decision, not a catalog entry.

Anton's desktop writing standards add two quality locks to this formula:

- The paragraph is about the engineering decision, not the machine's existence. The audience already knows the machine exists; the script has to reveal why it mattered.
- Every paragraph needs one memorable sourced fact for serious enthusiasts. This is not a fifth required research sentence. If a `memorable_fact` excerpt exists, the compiler folds it into the strongest of the four evidence-backed beats.
- Technical specifications are allowed when they prove the decision, tradeoff, or reality. The compiler should select the 2-4 useful technical facts instead of either dumping every spec or stripping the paragraph until it loses the Anton inventory feel.
- For the first three machines, a verified human account, named decision, or official finding is preferred when available because the desktop DVsU standard uses it to build early trust. This is advisory only; the system must never invent a human detail.

## First Three Machines Broken Into Reusable Slots

| Machine | Original problem | Engineering decision | Tradeoff | Reality | Optional memorable fact | Paragraph-derived landed line |
| --- | --- | --- | --- | --- | --- | --- |
| Boeing XB-15 | America attempted long-range strategic bombing before the engine technology was mature | Huge airframe, four engines, long range, and payload ambition | One prototype; not used in combat as a bomber | Became useful as a World War II Pacific transport | A bomber prototype became useful as cargo aircraft | Validated large multi-engine, long-range bomber concepts |
| Boeing B-17 Flying Fortress | America bet on daylight precision bombing over Europe | Defensive gunship-like bomber with range, payload, and thirteen machine guns | Crews believed it could defend itself without fighter escort; losses proved the cost | Heavy Eighth Air Force losses over Europe | 4,735 B-17s lost over Europe, 47% of heavy bomber losses in the script | Daylight precision bombing worked, but at a severe human cost |
| Consolidated B-24 Liberator | America needed mass, range, and fuel efficiency at global scale | Davis wing and production scale favored range and volume | Less forgiving than the B-17 despite stronger industrial output | Served in every theater, from Ploesti to Atlantic patrols | The most-produced American military aircraft was less forgiving than its famous rival | Industrial scale could overwhelm the enemy |

The first three benchmark profiles are also carried into the StoryEngine story plan as shape-only metadata: reference order, word count, sentence count, opening mode, sentence jobs, and final-line job. For the XB-15 proof, this means the compiler sees `94 words / 5 sentences / machine-date-significance opening` as a rhythm target, but it still may use only the locked source excerpts for facts.

## Research Contract

Research runs one locked roster machine at a time. The model may use only fetched raw internet excerpts saved in `machine_raw_source_packages`.

The fetch stage uses a cost-bounded eight-query set for the locked machine: official history, USAF/museum sources, manufacturer/design history, specifications, production/service reality, design tradeoffs/lessons, and human or unusual-fact accounts. This is how the raw package gathers the material needed for the four beats plus any sourced memorable fact.

The raw source package is checkpointed into `research_payload.machine_raw_source_packages[<machine_key>]` immediately after fetch/verification and before the research-card LLM call. A failed or blocked card generation can therefore still be reviewed from the exact gathered excerpts instead of disappearing with the failed model pass.

New source packages accept excerpt text only from a direct fetched page/PDF or Tavily `raw_content`. Tavily search-result `content` snippets are skipped because they are not reliable enough to serve as exact saved evidence. New excerpts carry `source_capture_method` so the review UI/prompt can distinguish `fetched_page`, `tavily_raw_content`, and legacy unmarked packages.

Cached raw source packages are reused only when their saved `machine_key`/`machine` identity still matches the locked target machine. A package stored under the right JSON key but internally belonging to another machine is ignored for research and rejected for script preview before any paid script call.

A successful selected-machine research pass sets `unit_research_hold_validation.target_machine_passed`, but it does not set the full `unit_research_hold_validation.passed` flag unless the entire locked roster is complete. UI progress and incomplete-research messages likewise count only cards that have a matching ready raw source package, so older legacy cards cannot make the new one-machine proof appear complete.

The Script/Voice calibration panel may show the single-machine preview control once at least one machine has a verified card and ready raw source package. That does not unblock full script generation; it only lets the operator preview the selected machine paragraph before paying to continue the roster.

Single-machine script preview is a review artifact path, not production script generation. It may save `machine_script_previews`, `machine_script_briefs`, and `machine_story_plans`, but it must not delete/insert rows in `scripts`, update `script_validation`, or advance the video status.

When the last locked machine is researched through the same selected-machine path, StoryEngine recomputes the full roster gate from every saved card and that card's matching raw source package. Only then does `unit_research_hold_validation.passed` become true.

Full static-docu script generation revalidates that same source package/card contract for every locked machine before spending a script LLM call or replacing `scripts` rows. The UI gate is a convenience layer; the backend remains the authority.

Single-machine preview artifacts are saved under the same normalized machine key as raw source packages, for example `XB15`, so retries from slightly different UI labels update the same preview slot instead of creating duplicate display-name keys.

Every selected-machine research checkpoint and final save is guarded by the original locked `unit_roster` snapshot. If the roster changes while a one-machine run is in flight, the save is refused rather than overwriting the newer roster state.

All machine-research saves and script-preview reads/writes are tenant-scoped. The legacy full-roster route now saves with `video_id + tenant_id` and refuses zero-row saves; the single-machine script preview reads the existing `voice_id` with the same tenant boundary before writing preview artifacts.

Single-machine preview artifact writes also carry the locked `unit_roster` snapshot and refuse zero-row updates. A missed `machine_script_briefs` or `machine_story_plans` save stops before the paragraph LLM call; a missed `machine_script_previews` save returns failure instead of a false completed preview.

Research cards use `schema_version: 3` and `evidence_segments` with Anton slot kinds:

- Required: `original_problem`, `engineering_decision`, `tradeoff`, `reality`
- Optional when directly sourced: `memorable_fact`, `role_category`, `human_detail`, `historical_meaning`, `transition_hook`, `onscreen_label`, or narrow context slots

Do not research or pre-write a standalone "meaning" beat. The final sentence is editorial synthesis from the already-grounded paragraph and must not add new dates, numbers, events, specs, or sourced claims.

`onscreen_label` is metadata for Producer File/on-screen text, never spoken narration. It may use only sourced full name, concise role, operator or build count, and service/date range. The script paragraph must remain clean voiceover text with no headers, labels, editor notes, thumbnail lines, or visual directions.

`memorable_fact` must not be invented. The research prompt asks for it when exact excerpts support one; the script preview audit will mark the machine as needing review if the story plan has no sourced memorable fact or if the paragraph ignores the one research found.

Each evidence segment must include an exact `source_excerpt`, `source_url`, `locator`, `numeric_tokens`, and `confidence`. Claims are constrained to words and numbers present in the copied excerpt.

Fetched source packages also carry `SOURCE_TIER` metadata:

- Tier 1: primary or official sources
- Tier 2: museum or authoritative secondary sources
- Tier 3: reference or secondary sources
- Tier 4: caution/general sources such as Wikipedia, YouTube, social pages, forums, or wiki mirrors

Required Anton slots cannot be supported only by Tier 4 evidence. Tier 3 remains acceptable when official or museum sources do not contain the needed fact, but high-risk exact facts still need cross-checking or hedging.

The desktop research standard's accuracy rule is enforced in the card prompts: be precise or be silent. If exact excerpts conflict or cannot verify a number, date, superlative, or specification, the card must use the more conservative supported wording, hedge it, or omit it rather than choosing the higher or more dramatic claim.

StoryEngine's Research and Script/Voice tabs mirror the backend source-package gate before enabling single-machine preview: matching machine identity, at least six excerpts, at least two distinct source URLs, and at least one non-caution source. Thin, wrong-machine, or caution-only packages show a blocked badge instead of a misleading ready state. If an older raw package lacks explicit `source_tier`, the UI infers tier from source URL using the same official/museum/caution hierarchy as the backend.

After a selected-machine research or preview run, the UI invalidates the saved video state so the freshly persisted `machine_raw_source_packages`, `machine_script_previews`, `machine_script_briefs`, and `machine_story_plans` can be reviewed without relying on a manual browser refresh.

## Script Contract

The script preview writer returns JSON:

```json
{
  "editorial_thesis": "single engineering decision or contrast",
  "paragraph": "final spoken narration",
  "claim_map": [
    {
      "span": "exact paragraph words",
      "slot": "original_problem",
      "used_evidence_ids": ["..."]
    }
  ],
  "onscreen_label": ""
}
```

Validation requires:

- one paragraph, 90-120 words, 4-7 sentences
- locked machine designation present
- `editorial_thesis` present, specific, 6-26 words, and centered on an engineering decision, tradeoff, or contrast
- claim-map spans copied exactly from the paragraph
- required Anton evidence slots covered: `original_problem`, `engineering_decision`, `tradeoff`, `reality`
- sourced `memorable_fact` used when the story plan provides one
- final sentence is a paragraph-derived conclusion, not a researched `historical_meaning` beat, and is not included in `claim_map`
- paragraph and each claim-map span use only numbers supported by their evidence IDs
- exact numbers, specifications, dates, production counts, and superlatives either cite two independent sources or are hedged/removed
- unsupported designations, high-risk terms, hype, list transitions, and semicolons rejected
- no deterministic extractive fallback can pass as final quality

The preview payload also includes `quality_audit.checks` so the StoryEngine UI can show the concrete Anton gate: 90-120 words, 4-7 sentences, four grounded beats, sourced memorable fact, concrete editorial thesis, landed final line, and no catalog/spec-dump pattern. When a first-three benchmark profile exists, the UI also shows advisory `reference_shape` and `early_human_detail` checks against the actual Anton paragraph shape and desktop human-detail preference.

## Isolation Rule

For the current proof, only the selected first machine is researched or previewed. Existing legacy cards for other roster machines remain untouched and are not loaded into the proof path.

## Current Runbook

1. Deploy only after Ryan approves the live StoryEngine update.
2. In StoryEngine, run one-machine research for `Boeing XB-15` only if the existing locked research card needs refresh.
3. Run only the single-machine script preview for `Boeing XB-15`.
4. Review the returned paragraph, warnings, `claim_map`, and research-card evidence segments in the UI.
5. Confirm the saved preview remains visible after switching between Research and Script/Voice; this proves the UI is reading persisted machine artifacts, not only local component state.
6. If the preview fails validation, do not save a deterministic fallback; use the audit to adjust the formula or rerun the single-machine step.
7. Move to Machine 2 only after the XB-15 paragraph passes Ryan's quality bar.
