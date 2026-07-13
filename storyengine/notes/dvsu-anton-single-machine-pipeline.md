# DVsU Anton Single-Machine Pipeline

## Source Materials Mapped

- Anton reference script: `/Users/ryanayler/Desktop/Designed vs used/TOP VIDEO SCRIPTS/Every US Strategic Bomber Ever Built.docx`
- Channel identity: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Channel_Identity.md`
- Writing system: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Script_Writing_System.md`
- Research standard: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Research_Fact_Verification_Standard.md`
- Example paragraphs: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Example_Paragraphs.md`
- Producer/voice standards: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Producer_File_Standard.md`, `/Users/ryanayler/Desktop/Designed vs used/DvsU_Voiceover_File_Standard.md`, `/Users/ryanayler/Desktop/Designed vs used/DvsU_ElevenLabs_Settings.md`
- Downstream visual/packaging standards to apply after the script proof passes: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Image_Generation_Standard.md`, `/Users/ryanayler/Desktop/Designed vs used/DvsU_Image_Quality_Checklist.md`, `/Users/ryanayler/Desktop/Designed vs used/DvsU_Thumbnail_Standard.md`, `/Users/ryanayler/Desktop/Designed vs used/DvsU_Thumbnail_AB_Testing_Standard.md`, `/Users/ryanayler/Desktop/Designed vs used/DvsU_Ryan_Handoff_README.md`

## Anton Paragraph Pattern From First Three Strategic Bombers

1. Original problem: raw excerpt for the need, requirement, or situation that forced the machine into the story.
2. Engineering decision: raw excerpt for the design, procurement, or technical answer.
3. Tradeoff: raw excerpt for the sacrifice, limitation, compromise, or unintended consequence.
4. Reality: raw excerpt for what happened in testing, production, service, or combat.
5. Editorial thesis: the single engineering decision, tradeoff, or contrast that tells the writer why these facts belong together.
6. Paragraph-derived conclusion: a short landed final sentence based only on the assembled paragraph, not a pre-researched meaning beat.

The paragraph is one natural 95-120 word unit for this proof, matching Anton's current DVsU writing and voiceover standards. The hard compiler formula is five sentences: four evidence-backed sentences in `original_problem -> engineering_decision -> tradeoff -> reality` order, followed by one paragraph-derived conclusion. The extracted XB-15 benchmark paragraph remains shape-only reference metadata; it can guide rhythm, sentence jobs, and final-line job, but it no longer lowers the hard production floor. The internal structure is not a visible four-beat scaffold, and the saved `editorial_thesis` is not narration. It is the compiler's required declaration that the paragraph is about an engineering decision, not a catalog entry.

Anton's desktop writing standards add these quality locks to this formula:

- The paragraph is about the engineering decision, not the machine's existence. The audience already knows the machine exists; the script has to reveal why it mattered.
- Narrative weight matters. Major or pivotal machines should aim toward the high end of the 95-120 word range; transitional, prototype, interim, or limited machines should aim toward the low end without losing the four grounded beats.
- Every paragraph needs one memorable sourced fact for serious enthusiasts. This is not a fifth required research sentence. If a `memorable_fact` excerpt exists, the compiler folds it into the strongest of the four evidence-backed beats.
- Technical specifications are allowed when they prove the decision, tradeoff, or reality. The compiler should select the 2-4 useful technical facts instead of either dumping every spec or stripping the paragraph until it loses the Anton inventory feel.
- For the Strategic Bomber benchmark specifically, the script target is Anton's compact inventory cadence: identity/significance, selected scale or capability facts, production or service reality, and a landed verdict. The anti-spec-dump rule must not strip sourced scale facts so aggressively that the paragraph becomes a thin engineering essay unlike the reference script.
- For the first three machines, a verified human account, named decision, or official finding is required when the locked story plan contains one because the desktop DVsU standard uses it to build early trust. The system must never invent a human detail.

## First Three Machines Broken Into Reusable Slots

| Machine | Original problem | Engineering decision | Tradeoff | Reality | Optional memorable fact | Paragraph-derived landed line |
| --- | --- | --- | --- | --- | --- | --- |
| Boeing XB-15 | America attempted long-range strategic bombing before the engine technology was mature | Huge airframe, four engines, long range, and payload ambition | One prototype; not used in combat as a bomber | Became useful as a World War II Pacific transport | A bomber prototype became useful as cargo aircraft | Validated large multi-engine, long-range bomber concepts |
| Boeing B-17 Flying Fortress | America bet on daylight precision bombing over Europe | Defensive gunship-like bomber with range, payload, and thirteen machine guns | Crews believed it could defend itself without fighter escort; losses proved the cost | Heavy Eighth Air Force losses over Europe | 4,735 B-17s lost over Europe, 47% of heavy bomber losses in the script | Daylight precision bombing worked, but at a severe human cost |
| Consolidated B-24 Liberator | America needed mass, range, and fuel efficiency at global scale | Davis wing and production scale favored range and volume | Less forgiving than the B-17 despite stronger industrial output | Served in every theater, from Ploesti to Atlantic patrols | The most-produced American military aircraft was less forgiving than its famous rival | Industrial scale could overwhelm the enemy |

The first three benchmark profiles are also carried into the StoryEngine story plan as shape-only metadata: reference order, word count, sentence count, opening mode, sentence jobs, and final-line job. For the XB-15 proof, this means the compiler sees `94 words / 5 sentences / machine-date-significance opening` as a rhythm target, but it still may use only the locked source excerpts for facts.

Opening assignments are separate from the shape-only benchmark. Anton's desktop writing standard allows only 4-5 machine-name openings across a full video, so StoryEngine deterministically assigns name-openers to roster slots 1, 6, 11, 16, and 21. All other slots save `contract.opening_assignment` into the machine story plan and the validator rejects a first sentence that starts with the locked machine name or designation. This keeps one-machine calls from all defaulting to the same Wikipedia-style opener.

## Research Contract

Research runs one locked roster machine at a time. The model may use only fetched raw internet excerpts saved in `machine_raw_source_packages`.

The fetch stage uses a cost-bounded eight-query set for the locked machine: official history, USAF/museum sources, manufacturer/design history, specifications, production/service reality, design tradeoffs/lessons, and human or unusual-fact accounts. This is how the raw package gathers the material needed for the four beats plus any sourced memorable fact.

The raw source package is checkpointed into `research_payload.machine_raw_source_packages[<machine_key>]` immediately after fetch/verification and before the research-card LLM call. A failed or blocked card generation can therefore still be reviewed from the exact gathered excerpts instead of disappearing with the failed model pass.

The one-machine query set stays capped at eight searches, but it explicitly covers official/museum/manufacturer history, specifications, production/service reality, design tradeoffs, test reports, and Anton's early-trust sources: pilot or crew memoirs, oral histories, official inquiries, and unusual facts. This is meant to gather enough exact text to write, not an endless encyclopedia scrape.

New source packages accept excerpt text only from a direct fetched page/PDF or Tavily `raw_content`. Tavily search-result `content` snippets are skipped because they are not reliable enough to serve as exact saved evidence. New excerpts carry `source_capture_method`, and selected-machine preview requires it to be either `fetched_page` or `tavily_raw_content`. `legacy_unmarked` may still display on older saved artifacts, but it is not a ready-state capture method for the new proof path.

Cached raw source packages are reused only when their saved `machine_key`/`machine` identity still matches the locked target machine. A package stored under the right JSON key but internally belonging to another machine is ignored for research and rejected for script preview before any paid script call.

A successful selected-machine research pass sets `unit_research_hold_validation.target_machine_passed`, but it does not set the full `unit_research_hold_validation.passed` flag unless the entire locked roster is complete. UI progress and incomplete-research messages likewise count only cards that have a matching ready raw source package, so older legacy cards cannot make the new one-machine proof appear complete.

The Script/Voice calibration panel may show the single-machine preview control once at least one machine has a verified card and ready raw source package. That does not unblock full script generation; it only lets the operator preview the selected machine paragraph before paying to continue the roster.

Single-machine script preview is a review artifact path, not production script generation. It may save `machine_script_previews`, `machine_script_briefs`, and `machine_story_plans`, but it must not delete/insert rows in `scripts`, update `script_validation`, or advance the video status.

Inventory-style titles that use `Every`, `All`, `Complete`, or `Ever Built` route into the same Anton slot compiler. This keeps titles like "World's Most Strategic Bombers Ever Built" from falling back to the older unstructured paragraph writer simply because they do not start with "Every."

When the last locked machine is researched through the same selected-machine path, StoryEngine recomputes the full roster gate from every saved card and that card's matching raw source package. Only then does `unit_research_hold_validation.passed` become true.

Full static-docu script generation revalidates that same source package/card contract for every locked machine before spending a script LLM call or replacing `scripts` rows. The final production replacement updates the tenant/video row first and only then deletes/inserts `scripts` rows, so a missed video update cannot create orphan replacement scenes. The UI gate is a convenience layer; the backend remains the authority.

Static DVsU production scripts must have exactly one paragraph row per locked roster machine. The final unit's last sentence is where the thesis lands; the roster validator rejects extra conclusion, transition, or non-machine rows even when they do not mention an outside machine code.

Single-machine preview artifacts are saved under the same normalized machine key as raw source packages, for example `XB15`, so retries from slightly different UI labels update the same preview slot instead of creating duplicate display-name keys.

Every selected-machine research checkpoint and final save is guarded by the original locked `unit_roster` snapshot. If the roster changes while a one-machine run is in flight, the save is refused rather than overwriting the newer roster state.

All machine-research saves and script-preview reads/writes are tenant-scoped. The legacy full-roster route now saves with `video_id + tenant_id` and refuses zero-row saves; the single-machine script preview reads the existing `voice_id` with the same tenant boundary before writing preview artifacts.

Single-machine preview artifact writes also carry the locked `unit_roster` snapshot and refuse zero-row updates. A missed `machine_script_briefs` or `machine_story_plans` save stops before the paragraph LLM call; a missed `machine_script_previews` save returns failure instead of a false completed preview.

Research cards use `schema_version: 3` and `evidence_segments` with Anton slot kinds:

- Required: `original_problem`, `engineering_decision`, `tradeoff`, `reality`
- Optional when directly sourced: `memorable_fact`, `role_category`, `human_detail`, `transition_hook`, `onscreen_label`, or narrow context slots

Research cards also require `timeframe` and `timeframe_evidence_ids`. This is the research-standard verified date/service-period basis. It must state the sourced date range, era, first-flight/service period, or prototype/operational period, and cite evidence IDs whose copied excerpts support it. It is metadata for research confidence and Producer/on-screen use; the spoken paragraph uses it only when the date or period proves one of the four Anton beats.

Research cards also require `visual_identity` and `visual_identity_evidence_ids`. This is Producer File/image-brief basis only, not spoken narration. It must name the exact visible features that make the locked machine unmistakable and cite evidence IDs whose copied excerpts support those features. It must not include camera movement, animation, transitions, thumbnail copy, on-screen text, captions, or editing directions.

Research cards may also include `narrative_weight` as `major`, `standard`, or `transitional`. If the card does not provide it, StoryEngine infers a conservative advisory profile from the locked evidence and stores it in `machine_story_plans[*].contract.narrative_weight`. The compiler follows that target inside the hard 95-120 word range instead of forcing equal paragraph weight.

`why_this_unit_deserves_a_paragraph` is required and must state the unique engineering idea this locked machine contributes to the video. Generic fame, importance, existence, or "this machine mattered" wording fails card validation because Anton's rule is that no other roster machine should be able to replace the unit's reason for inclusion. It may not introduce dates, numbers, other machine designations, events, or specifications absent from the returned evidence segments.

When the full locked roster is evaluated, StoryEngine also compares saved cards for repeated `engineering_thesis` or `why_this_unit_deserves_a_paragraph` signatures. If two machines tell effectively the same engineering story, the full research gate stays blocked so the duplicate can be fixed one machine at a time before script generation.

`human_detail` must either name a person or cite an official finding/decision. Generic pilot, crew, or engineer claims are invalid even when they come from a fetched excerpt, because Anton's rule is about a documented perspective that builds trust without replacing the engineering thesis.

Do not research or pre-write a standalone "meaning" beat. If a source states a concrete downstream consequence, save it as `reality`; the final sentence remains editorial synthesis from the already-grounded paragraph and must not add new dates, numbers, events, specs, or sourced claims.

`onscreen_label` is metadata for Producer File/on-screen text, never spoken narration. It may use only sourced full name, concise role, operator or build count, and service/date range. The script paragraph must remain clean voiceover text with no headers, labels, editor notes, thumbnail lines, or visual directions.

The voiceover-clean gate rejects Producer File artifacts inside narration: unit labels, act labels, b-roll cues, thumbnail lines, graphics-list language, and bracketed production notes. These belong to Producer File or downstream assembly, not the single-machine spoken paragraph.

The spoken-rhythm gate rejects three consecutive long sentences. Anton's voiceover standard allows long sentences for momentum, but they must be broken by shorter emphasis or landing sentences so the paragraph reads cleanly in ElevenLabs.

The timeline-structure gate rejects paragraphs that stack dated biography sentences. A single dated anchor is allowed when it proves the engineering problem, decision, tradeoff, or reality; a sequence of "designed, entered service, modified, retired" facts triggers review.

The narrative-flow gate rejects ranked-list connector language such as "Next came," "Another aircraft was," "Moving on to," "At number," and "on this list." Anton paragraphs must bridge through problem, contrast, consequence, or the prior machine instead of announcing another list entry.

`memorable_fact` must not be invented, and the saved research card must contain a sourced `memorable_fact`, `surprising_fact`, or `retention_fact` evidence segment before script preview is enabled. The script preview audit will still mark the machine as needing review if the paragraph ignores the one research found.

Each evidence segment must include an exact `source_excerpt`, `source_url`, `locator`, `numeric_tokens`, and `confidence`. Claims are constrained to words and numbers present in the copied excerpt.

Fetched source packages also carry `SOURCE_TIER` metadata:

- Tier 1: primary or official sources
- Tier 2: museum or authoritative secondary sources
- Tier 3: reference or secondary sources
- Tier 4: caution/general sources such as Wikipedia, YouTube, social pages, forums, or wiki mirrors

Required Anton slots cannot be supported only by Tier 4 evidence. Tier 3 remains acceptable when official or museum sources do not contain the needed fact, but high-risk exact facts still need cross-checking or hedging.

The desktop research standard's accuracy rule is enforced in the card prompts: be precise or be silent. If exact excerpts conflict or cannot verify a number, date, superlative, or specification, the card must use the more conservative supported wording, hedge it, or omit it rather than choosing the higher or more dramatic claim.

StoryEngine's Research and Script/Voice tabs mirror the backend preview gate before enabling single-machine preview: a matching saved research card plus a ready raw source package with matching machine identity, at least six excerpts, at least two distinct source URLs, at least one non-caution source, and at least one Tier 1-2 primary/authoritative source. Missing-card, thin, wrong-machine, caution-only, or Tier 3-only packages show a blocked badge instead of a misleading ready state. If an older raw package lacks explicit `source_tier`, the UI infers tier from source URL using the same official/museum/caution hierarchy as the backend.

Before Claude writes or previews a machine card, the raw package must also include at least one Tier 1 primary/official or Tier 2 museum/authoritative secondary source. Tier 3 reference sources may support individual details when they are the best available evidence, but a Tier 3-only package is not enough for Anton-quality DVsU research confidence.

Before Claude writes the card, the raw package must also contain exact fetched excerpts that plausibly cover all four required Anton beats: `original_problem`, `engineering_decision`, `tradeoff`, and `reality`. A package that only contains specifications, generic descriptions, or thin identity facts is not research-ready, even if it has enough excerpts and source URLs. New packages save `source_slot_coverage` plus per-excerpt `anton_slot_hints` so the operator can review which raw excerpts unlocked each beat before a card-writing call runs.

The saved research card itself must select at least one Tier 1-2 source-backed evidence segment. A raw package is not considered enough if it contains an authoritative source but the model ignores that source when building the card. `timeframe` and `visual_identity` evidence cannot be supported only by Tier 4/caution sources.

The Research and Script/Voice tabs also check that the card's selected `source_excerpt` + `source_url` + `locator` rows still match the saved raw package before showing the selected machine as ready. This keeps stale card locators, cards that ignored Tier 1-2 sources, and Tier 4-only timeframe or visual identity evidence from appearing preview-ready in the UI.

When a selected evidence segment validates against a fetched raw candidate, the backend enriches it with `source_excerpt_id`, `source_id`, `source_excerpt_hash`, `source_tier`, `source_tier_label`, and `source_capture_method`. The UI uses `source_excerpt_id` and `source_excerpt_hash` as the primary match before falling back to URL/locator/text matching, then shows those fields beside the raw excerpt so review is tied to an exact fetched row, not a loose paraphrase.

After a selected-machine research or preview run, the UI invalidates the saved video state so the freshly persisted `machine_raw_source_packages`, `machine_script_previews`, `machine_script_briefs`, and `machine_story_plans` can be reviewed without relying on a manual browser refresh.

The Script/Voice single-machine preview displays the saved `formula_sentences` as a review stack. Each of the first four sentences shows the selected source excerpts from its matching claim-map evidence IDs directly under the sentence; the fifth conclusion stays source-free because it is paragraph-derived synthesis only.

## Script Contract

The script preview writer returns JSON:

```json
{
  "editorial_thesis": "single engineering decision or contrast",
  "formula_sentences": [
    "original_problem sentence",
    "engineering_decision sentence",
    "tradeoff sentence",
    "reality sentence",
    "paragraph-derived conclusion"
  ],
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

- one paragraph, 95-120 words, exactly five formula sentences
- `formula_sentences` contains those exact five final sentences and joins with spaces to reproduce `paragraph`
- narrative weight target followed inside that hard range: major machines closer to 120 words, transitional machines closer to 95 words, with no padding
- locked machine designation present
- `editorial_thesis` present, specific, 6-26 words, and centered on an engineering decision, tradeoff, or contrast
- claim-map spans copied exactly from the paragraph
- required Anton evidence slots covered: `original_problem`, `engineering_decision`, `tradeoff`, `reality`
- sourced `memorable_fact` used when the story plan provides one
- sourced `human_detail` used for the first three benchmark machines when the story plan provides one
- final sentence is a paragraph-derived conclusion, not a researched meaning beat, and is not included in `claim_map`
- opening assignment is followed; when the assignment says not to open with the machine name, the first sentence cannot start with the locked machine name or designation
- paragraph and each claim-map span use only numbers supported by their evidence IDs
- every unhedged exact number, specification, date, production count, and superlative is supported by two independent evidence IDs that both contain that exact numeric detail, or it is hedged/removed
- voice-ready number wording is required for years and quantities; designations/model names such as B-52, XB-15, and F-86 remain designations; unit abbreviations such as mph, rpm, ft, lb, mi, and hp are spelled out for narration
- sentence length varies for spoken delivery; three consecutive long sentences trigger review
- unsupported designations, high-risk terms, hype, ranked-list connectors, timeline-biography structure, production cues, bracketed notes, written-language connector sentence starts, and semicolons rejected
- no deterministic extractive fallback can pass as final quality

The preview payload also includes `quality_audit.checks` so the StoryEngine UI can show the concrete Anton gate: 95-120 words, five formula sentences, exact sentence assembly, four grounded beats, sourced memorable fact, concrete editorial thesis, landed final line, clean voiceover only, spoken rhythm, opening assignment, narrative weight, and no catalog/spec-dump pattern. The audit also carries a hard `validator_warnings` row whenever any backend validator warning remains, so the UI cannot show a passing Anton audit for a paragraph the backend rejected. When a first-three benchmark profile exists, the UI also shows an advisory `reference_shape` check against the actual Anton paragraph shape. `early_human_detail` stays advisory only when no sourced detail exists; if the locked story plan contains one, unused human-detail evidence is a hard review failure.

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
