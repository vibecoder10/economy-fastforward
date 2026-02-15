# Research Agent Audit — Story 0

## Date: 2026-02-15
## Auditor: Claude Code (Pipeline Unification v1)

---

## Summary

**No standalone research agent exists.** The codebase has no dedicated "research agent" or "deep research" module. Research-like functionality is embedded in the `brief_translator/supplementer.py` module as targeted gap-filling, not as a standalone deep research system.

The PRD references a "deep research agent" that produced Elon Musk / Machiavellian theme content. No trace of that code exists in the git history or current codebase. It was likely built in an external session (possibly another Claude instance) and its output was manually pasted into Airtable.

---

## Where Research Logic Was Found

### 1. `brief_translator/supplementer.py` — **Embedded Research**

This is the only research-performing code in the codebase. It runs **targeted supplemental research** to fill gaps identified by the validator (Step 1b in the brief_translator pipeline).

**What it does:**
- Receives gap descriptions from `validator.py`
- Builds a prompt using `prompts/supplemental.txt` template
- Calls Claude (Sonnet) with `max_tokens=4000` to fill specific gaps
- Merges results back into the brief dict
- Retries up to `MAX_SUPPLEMENT_PASSES = 2` times

**What it does NOT do:**
- Deep thematic analysis (Machiavellian frameworks, psychological angles)
- Multi-source research across URLs
- Structured research payload generation (themes, facts, parallels)
- Historical parallel extraction
- Narrative arc suggestion
- Source bibliography generation

**Key functions:**
- `run_supplemental_research(anthropic_client, brief, gaps)` → returns text
- `merge_supplement_into_brief(brief, supplement_text, gaps)` → returns updated brief
- `build_supplemental_prompt(brief, gaps)` → returns prompt string

### 2. `brief_translator/validator.py` — **Research Quality Assessment**

Validates research quality across 8 criteria:
- `hook_strength`
- `fact_density`
- `framework_depth`
- `historical_parallel_richness`
- `character_visualizability`
- `implication_specificity`
- `visual_variety`
- `structural_completeness`

This maps to the research_payload structure needed but currently only evaluates existing content, doesn't generate it.

### 3. `bots/idea_bot.py` — **Idea Generation (Not Research)**

Generates 3 viral video concepts from URLs or topics. Outputs titles, hooks, narrative logic, thumbnail concepts. This is idea generation, not deep research.

### 4. `bots/trending_idea_bot.py` — **Trend Analysis (Not Research)**

Scrapes trending YouTube videos and generates ideas based on format patterns. Also not deep research.

---

## Git History Search

```
git log --oneline --all --grep="research"
→ 8aa95d2 Add brief-to-script translation layer for Ideas Bank to Pipeline bridging

git log --oneline --all --grep="Elon"
→ (no results)

git log --oneline --all --grep="Machiavelli"
→ (no results)

git log --oneline --all --grep="deep research"
→ (no results)
```

The only research-related commit is the brief_translator addition, which includes `supplementer.py`.

---

## Current Brief Fields (Expected by Validator)

The brief_translator expects these fields from the "Ideas Bank" (Airtable):
- `headline` — Video title/topic
- `thesis` — Core argument
- `executive_hook` — Opening hook
- `fact_sheet` — Key data points and statistics
- `historical_parallels` — Historical connections
- `framework_analysis` — Analytical framework
- `character_dossier` — Key figures/characters
- `narrative_arc` — Story structure
- `counter_arguments` — Opposing viewpoints
- `visual_seeds` — Visual concepts for imagery
- `source_bibliography` — Sources

These fields map closely to the PRD's `research_payload` structure.

---

## Action Plan

Since no standalone research agent exists, we need to **create one** that:

1. Takes a topic/idea + optional seed URLs
2. Performs deep research via Claude (using web search or extensive knowledge)
3. Produces a structured `research_payload` matching the brief_translator's expected fields
4. Can run standalone: `python research_agent.py --topic "topic"`
5. Can be imported by brief_translator as the primary content source

The supplementer.py will remain for gap-filling after initial research, but the main research generation will be in the new standalone module.

---

## Interface Pattern

The codebase uses async functions with client injection:
```python
# Pattern from existing modules:
async def function_name(anthropic_client, data_dict, ...) -> result
```

All modules accept `anthropic_client` as first parameter and return structured dicts or strings.
