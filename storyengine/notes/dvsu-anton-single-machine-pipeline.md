# DVsU Anton Single-Machine Pipeline

## Source Materials Mapped

- Anton reference script: `/Users/ryanayler/Desktop/Designed vs used/TOP VIDEO SCRIPTS/Every US Strategic Bomber Ever Built.docx`
- Writing system: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Script_Writing_System.md`
- Research standard: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Research_Fact_Verification_Standard.md`
- Producer/voice standards: `/Users/ryanayler/Desktop/Designed vs used/DvsU_Producer_File_Standard.md`, `/Users/ryanayler/Desktop/Designed vs used/DvsU_Voiceover_File_Standard.md`

## Anton Paragraph Pattern From First Three Strategic Bombers

1. Identity/origin: name the machine and the date or role that puts it into the story.
2. Scale proof: use only the specs that prove the engineering ambition.
3. Build reality: prototype count or production scale.
4. Service reality: what the machine actually did, including combat or non-combat reality when important.
5. Memorable fact: one sourced fact serious viewers are unlikely to know, used only if it supports the engineering story.
6. Paragraph-derived conclusion: a short landed final sentence based only on the assembled paragraph, not a pre-researched meaning beat.

The paragraph is still one natural 95-120 word unit. The internal structure is not a visible four-beat scaffold.

## First Three Machines Broken Into Reusable Slots

| Machine | Identity/origin | Scale proof | Build reality | Service reality | Memorable fact | Paragraph-derived landed line |
| --- | --- | --- | --- | --- | --- | --- |
| Boeing XB-15 | First flew in 1937 as an experimental long-range strategic bomber | 149-foot wingspan, four 850-hp engines, 2,500-pound bomb load, 5,130-mile range | One prototype | Transport use in World War II; cargo across the Pacific; not combat as a bomber | A bomber prototype became useful as a wartime transport | Validated large multi-engine, long-range bomber concepts |
| Boeing B-17 Flying Fortress | Entered service in 1938; backbone of daylight precision bombing | Four 1,200-hp engines, 4,500-pound bomb load, 287 mph, 2,000-mile reach, thirteen .50-caliber guns | 12,731 built | Heavy Eighth Air Force losses over Europe | 4,735 B-17s lost over Europe, 47% of heavy bomber losses in the script | Daylight precision bombing worked, but at a severe human cost |
| Consolidated B-24 Liberator | First flew in 1941; became the most-produced American military aircraft | 110-foot wingspan, 8,000-pound bomb load, 290 mph, 2,100-mile reach, Davis wing efficiency | 18,482 produced | Every theater; Ploesti and Atlantic patrol work; less forgiving than B-17 | The most-produced American military aircraft was less forgiving than its famous rival | Industrial scale could overwhelm the enemy |

## Research Contract

Research runs one locked roster machine at a time. The model may use only fetched raw internet excerpts saved in `machine_raw_source_packages`.

Research cards use `schema_version: 3` and `evidence_segments` with Anton slot kinds:

- Required: `identity_origin`, `scale_specs`, `build_reality`, `service_reality`, `memorable_fact`
- Optional when directly sourced: `engineering_intent`, `role_category`, `combat_reality`, `tradeoff_or_limit`, `human_detail`, `historical_meaning`, `transition_hook`, `onscreen_label`

Do not research or pre-write a standalone "meaning" beat. The final sentence is editorial synthesis from the already-grounded paragraph and must not add new dates, numbers, events, specs, or sourced claims.

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
  "paragraph": "final spoken narration",
  "claim_map": [
    {
      "span": "exact paragraph words",
      "slot": "identity_origin",
      "used_evidence_ids": ["..."]
    }
  ],
  "onscreen_label": ""
}
```

Validation requires:

- one paragraph, 95-120 words, 4-6 sentences
- locked machine designation present
- claim-map spans copied exactly from the paragraph
- required Anton evidence slots covered
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
