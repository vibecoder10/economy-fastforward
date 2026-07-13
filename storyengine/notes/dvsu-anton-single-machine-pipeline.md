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

The paragraph is still one natural 95-120 word unit. The internal structure is not a visible four-beat scaffold, and the saved `editorial_thesis` is not narration. It is the compiler's required declaration that the paragraph is about an engineering decision, not a catalog entry.

Anton's desktop writing standards add two quality locks to this formula:

- Every paragraph needs one memorable sourced fact for serious enthusiasts. This is not a fifth required research sentence. If a `memorable_fact` excerpt exists, the compiler folds it into the strongest of the four evidence-backed beats.
- Technical specifications are allowed when they prove the decision, tradeoff, or reality. The compiler should select the 2-4 useful technical facts instead of either dumping every spec or stripping the paragraph until it loses the Anton inventory feel.

## First Three Machines Broken Into Reusable Slots

| Machine | Original problem | Engineering decision | Tradeoff | Reality | Optional memorable fact | Paragraph-derived landed line |
| --- | --- | --- | --- | --- | --- | --- |
| Boeing XB-15 | America attempted long-range strategic bombing before the engine technology was mature | Huge airframe, four engines, long range, and payload ambition | One prototype; not used in combat as a bomber | Became useful as a World War II Pacific transport | A bomber prototype became useful as cargo aircraft | Validated large multi-engine, long-range bomber concepts |
| Boeing B-17 Flying Fortress | America bet on daylight precision bombing over Europe | Defensive gunship-like bomber with range, payload, and thirteen machine guns | Crews believed it could defend itself without fighter escort; losses proved the cost | Heavy Eighth Air Force losses over Europe | 4,735 B-17s lost over Europe, 47% of heavy bomber losses in the script | Daylight precision bombing worked, but at a severe human cost |
| Consolidated B-24 Liberator | America needed mass, range, and fuel efficiency at global scale | Davis wing and production scale favored range and volume | Less forgiving than the B-17 despite stronger industrial output | Served in every theater, from Ploesti to Atlantic patrols | The most-produced American military aircraft was less forgiving than its famous rival | Industrial scale could overwhelm the enemy |

## Research Contract

Research runs one locked roster machine at a time. The model may use only fetched raw internet excerpts saved in `machine_raw_source_packages`.

Research cards use `schema_version: 3` and `evidence_segments` with Anton slot kinds:

- Required: `original_problem`, `engineering_decision`, `tradeoff`, `reality`
- Optional when directly sourced: `memorable_fact`, `role_category`, `human_detail`, `historical_meaning`, `transition_hook`, `onscreen_label`, or narrow context slots

Do not research or pre-write a standalone "meaning" beat. The final sentence is editorial synthesis from the already-grounded paragraph and must not add new dates, numbers, events, specs, or sourced claims.

`memorable_fact` remains optional at the research-card level because the system must not invent a surprising detail. Once research has saved one, it becomes required at the script level and must be used inside one required beat, not as disconnected trivia.

Each evidence segment must include an exact `source_excerpt`, `source_url`, `locator`, `numeric_tokens`, and `confidence`. Claims are constrained to words and numbers present in the copied excerpt.

Fetched source packages also carry `SOURCE_TIER` metadata:

- Tier 1: primary or official sources
- Tier 2: museum or authoritative secondary sources
- Tier 3: reference or secondary sources
- Tier 4: caution/general sources such as Wikipedia, YouTube, social pages, forums, or wiki mirrors

Required Anton slots cannot be supported only by Tier 4 evidence. Tier 3 remains acceptable when official or museum sources do not contain the needed fact, but high-risk exact facts still need cross-checking or hedging.

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

- one paragraph, 95-120 words, 4-6 sentences
- locked machine designation present
- `editorial_thesis` present, specific, 6-26 words, and centered on an engineering decision, tradeoff, or contrast
- claim-map spans copied exactly from the paragraph
- required Anton evidence slots covered: `original_problem`, `engineering_decision`, `tradeoff`, `reality`
- sourced `memorable_fact` used when the story plan provides one
- final sentence is a paragraph-derived conclusion, not a researched `historical_meaning` beat
- paragraph and each claim-map span use only numbers supported by their evidence IDs
- exact numbers, specifications, dates, production counts, and superlatives either cite two independent sources or are hedged/removed
- unsupported designations, high-risk terms, hype, list transitions, and semicolons rejected
- no deterministic extractive fallback can pass as final quality

## Isolation Rule

For the current proof, only the selected first machine is researched or previewed. Existing legacy cards for other roster machines remain untouched and are not loaded into the proof path.

## Current Runbook

1. Deploy only after Ryan approves the live StoryEngine update.
2. In StoryEngine, run one-machine research for `Boeing XB-15` only if the existing locked research card needs refresh.
3. Run only the single-machine script preview for `Boeing XB-15`.
4. Review the returned paragraph, warnings, `claim_map`, and research-card evidence segments in the UI.
5. If the preview fails validation, do not save a deterministic fallback; use the audit to adjust the formula or rerun the single-machine step.
6. Move to Machine 2 only after the XB-15 paragraph passes Ryan's quality bar.
