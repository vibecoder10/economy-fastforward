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
5. Historical meaning: a short landed final sentence or clause that states what the machine proved.

The paragraph is still one natural 95-120 word unit. The internal structure is not a visible four-beat scaffold.

## First Three Machines Broken Into Reusable Slots

| Machine | Identity/origin | Scale proof | Build reality | Service reality | Meaning / landed line |
| --- | --- | --- | --- | --- | --- |
| Boeing XB-15 | First flew in 1937 as an experimental long-range strategic bomber | 149-foot wingspan, four 850-hp engines, 2,500-pound bomb load, 5,130-mile range | One prototype | Transport use in World War II; cargo across the Pacific; not combat as a bomber | Validated large multi-engine, long-range bomber concepts |
| Boeing B-17 Flying Fortress | Entered service in 1938; backbone of daylight precision bombing | Four 1,200-hp engines, 4,500-pound bomb load, 287 mph, 2,000-mile reach, thirteen .50-caliber guns | 12,731 built | Heavy Eighth Air Force losses over Europe | Daylight precision bombing worked, but at a severe human cost |
| Consolidated B-24 Liberator | First flew in 1941; became the most-produced American military aircraft | 110-foot wingspan, 8,000-pound bomb load, 290 mph, 2,100-mile reach, Davis wing efficiency | 18,482 produced | Every theater; Ploesti and Atlantic patrol work; less forgiving than B-17 | Industrial scale could overwhelm the enemy |

## Research Contract

Research runs one locked roster machine at a time. The model may use only fetched raw internet excerpts saved in `machine_raw_source_packages`.

Research cards use `schema_version: 3` and `evidence_segments` with Anton slot kinds:

- Required: `identity_origin`, `scale_specs`, `build_reality`, `service_reality`, `historical_meaning`
- Optional when sourced: `engineering_intent`, `role_category`, `combat_reality`, `tradeoff_or_limit`, `transition_hook`, `onscreen_label`

Each evidence segment must include an exact `source_excerpt`, `source_url`, `locator`, `numeric_tokens`, and `confidence`. Claims are constrained to words and numbers present in the copied excerpt.

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
- required Anton slots covered
- paragraph and each claim-map span use only numbers supported by their evidence IDs
- unsupported designations, high-risk terms, hype, list transitions, and semicolons rejected
- no deterministic extractive fallback can pass as final quality

## Isolation Rule

For the current proof, only the selected first machine is researched or previewed. Existing legacy cards for other roster machines remain untouched and are not loaded into the proof path.
