# DVSU script-writing pipeline v2 — design spec

Status: design validated via hand-run prototype (Sonnet acting as the writer directly, no paid API
call), same method used for the research pipeline. All 4 machines that had a finished v2 research
packet (Holland, S-class, Nautilus, Thresher/Permit) were scripted and self-audited against the
real channel standard. Not yet implemented as code. **This write-up recovers work that was already
done earlier today (Drive docs timestamped 18:35–19:08 UTC) but never got written into a DESIGN.md
or reflected back into CHECKLIST.md/HANDOFF.md** — the same "lost across session handoff" failure
HANDOFF.md already flagged for the research design. Companion doc:
`docs/dvsu-research-pipeline-v2-2026-09-18/DESIGN.md`.

Replaces: `factual_machine_summary.py`'s script path (the `_script_writer_prompt()` function and
its paid Opus 4.5 write+referee call), `dvsu_script_brief.py`, `script_research_packet.py`'s role
in assembling the old `DVSU BRIEF` JSON packet for script purposes.

## Source of truth for the standard

"DvsU — Script Writing System v3" is the real channel standard. Ryan pasted its full text earlier
in today's session; it was never saved to a file (same gap DESIGN.md's research doc flagged). The
adapted prompt below (`PROMPT-v3`, Drive) is the operational translation of that standard, revised
once already after a self-review caught two rules the first pass missed. **The v3 standard's own
original text should still be captured to a file if Ryan can re-supply it** — the adapted prompt is
a faithful working translation, validated against 4 real examples, but it is not a substitute for
having the source standard on record.

## Pipeline shape: 1 call per machine, no separate paid referee

Mirrors the research design's "no separate validation pass" decision: the old pipeline ran a
separate paid Opus 4.5 referee/citation-integrity call after the writer call. The v3-aligned prompt
folds a self-audit into the same call's contract (see "Per-call output shape" below) instead of a
second call. **This is the biggest open risk in this design — flagged for Ryan below, not assumed.**

Input to each call: the machine's finished Stage-3 research packet (Problem / Design / Trade-off /
Outcome / Surprising fact / Contrast, from the research pipeline design) plus act context (the
act's one-sentence thesis, and the previous sibling unit's script if one exists in the same act).

## The v3-aligned prompt (validated, from Drive `PROMPT-v3`)

**Prompt template:**
```
You are writing one paragraph of a DvsU engineering-documentary script about the exact named
machine: {machine}, part of {act_name} — one-sentence act thesis: {act_thesis}.

Core rule: this paragraph is about the ENGINEERING DECISION the machine represents, not the
machine itself. Answer: what is the single reason historians still talk about {machine} today?
Write about why it's remembered, not about what it did.

Audience: military-history enthusiasts, 55+, who already know the machine exists and will
fact-check every claim. Do not spend words proving it existed. Write as an equal, not a teacher.

Source: use only the supplied BRIEF (Problem / Design / Trade-off / Outcome / Surprising fact /
Contrast, each already sourced). Do not add outside knowledge or invented dates/numbers — but DO
state the argued lesson the facts support. This is an essay making an argument, not a
citation-safe recitation.

Length: 95–120 words. Never less, never more. A pivotal machine (first-of-kind, act-defining, a
death/failure/reversal) earns the top of the range. A transitional machine earns the bottom. Equal
length does not mean equal narrative weight.

Must include, non-negotiable:
- At least one surprising fact most viewers won't already know. Check the BRIEF's "Surprising
  fact" section first; don't cut it for budget.
- A real contrast (expectation vs. reality, design vs. outcome, intention vs. legacy). The BRIEF's
  "Contrast" section is often already written as this — use it or sharpen it, don't discard it.
- A final line that lands: short, a paradox/irony/reversal. If the last sentence could be deleted
  without losing meaning, rewrite it. Never summarize; land.

Opening: do NOT open with the machine's name by default — across a full 24–30-unit video only 4–5
total may open that way. Open instead with a date, a problem, a paradox, a human detail, a
consequence, or a contrast. Naming the machine first is a conscious exception, not the default.

Bridging: if a sibling unit in the same act (or a directly relevant prior act) already has a
finished paragraph, open or close with a real narrative bridge to it, grounded in an actual shared
fact — never a mechanical connector ("Next...", "Another submarine was..."). No invented causal
links between machines that the research doesn't support.

Forbidden: spec dumps; Wikipedia-style openings ("The X was a [type] built by [company] in
[year]"); ANY sentence, not just the opener, that could appear in a Wikipedia article unchanged;
list-writing ("It had... it also had..."); timeline/chronological-listing structure ("First
produced in 1942... modified in 1943... retired in 1957..."); hype ("incredible," "arguably,"
"undoubtedly"); generic praise ("legendary," "iconic," "revolutionary," "game-changing"); a
summary/conclusion sentence that restates rather than lands; orphan facts — any number that
doesn't answer why it was designed this way, what problem it solved, or what consequence it
created.

Submarine terminology (project-specific, carried over from the old prompt): refer to the subject
and its successors as a submarine/submarines or vessel/vessels, never boat/boats.

BRIEF: {research doc content — Problem/Design/Trade-off/Outcome/Surprising fact/Contrast}
ACT CONTEXT: {act thesis sentence + sibling unit's key line, if one exists in the same act}
```

**Revision already made once:** the first pass of this adapted prompt only forbade a Wikipedia-
style *opener*. A review of the Thresher script against the real v3 text caught that the rule
applies to *any* sentence in the paragraph, and that timeline/chronological-listing structure is
its own separately-named forbidden pattern — both fixed in the version above.

**Per-call output shape (proposed for implementation, not yet locked):** `{"paragraph": "...",
"claim_map": [{"sentence": "...", "source_url": "...", "quote": "..."}], "opened_with_name":
bool, "bridged_to": "<machine>" | null}` — `claim_map` mirrors the old pipeline's citation
mechanism; `opened_with_name`/`bridged_to` make the two cross-machine rules (opening-name budget,
real bridging) auditable in code rather than trusted to the model's self-report.

## What changed from the old (deployed, legacy) prompt

| | Old (`_script_writer_prompt`, backend) | New (v3-aligned) |
|---|---|---|
| Length | 95–105 target, 80–110 hard range | 95–120, never less/more |
| Opening | Name the machine early, every time | Name it in ~4–5 of ~30 units only |
| Ending | Avoid closing flourishes | Must land: paradox/irony/reversal, mandatory |
| Cross-machine | Fully isolated, no other-briefing detail allowed | Bridge to real siblings in the same act |
| Surprising fact | Not required | Required every paragraph |
| Specs | At most two | As many as the thesis needs, none orphaned |
| Interpretation | No invented lesson | The argued lesson IS the point |

## Why the 6-slot research packet maps directly onto this prompt

The v3 standard's own paragraph logic (Problem → Design → Trade-off → Outcome, one surprising fact
required, ending must land as contrast/irony/paradox) is exactly what the research pipeline's
6-slot packet was built to produce (see research DESIGN.md's "How the 6-slot template was
derived"). This was confirmed, not assumed: writing all 4 scripts by hand from the finished
research packets required zero additional research or invented facts — every non-negotiable
element (surprising fact, contrast, final-line landing) was already sitting in a labeled packet
field.

## Validated on 4 real examples (Drive `Every US Submarine Class Ever Built (2026)/`)

- **USS Holland (SS-1)** — Act 1, unit 1. Opens on the designer's own earlier submarine (a human/
  paradox opener, not the name). 119 words.
- **S-class** — Act 1, unit 2. Opens with a real bridge to Holland ("Holland proved a submarine
  could threaten without fighting..."), sourced independently on both sides, not invented. 119
  words.
- **USS Nautilus (SSN-571)** — Act 4. Opens with a bridge back to Act 1 (Holland/S-class's need to
  surface constantly) — demonstrates the bridge rule reaching across acts, not just within one.
  119 words.
- **Thresher/Permit-class** — Act 6, no researched sibling yet. Correctly opens on a human detail
  (the last transmission) and explicitly does *not* force an invented bridge, since the design's
  own rule is "no invented causal links... that the research doesn't support." 120 words.

Each was self-audited line-by-line against every v3 rule (opening budget, engineering-decision
framing, surprising fact present, contrast present, ending lands, no orphan facts, terminology)
before being accepted as a validated example — that audit process is what surfaced the one prompt
revision above.

Old-prompt comparison drafts for Holland and Nautilus are preserved in Drive under `Legacy/` for
reference (written from the actual deployed `_script_writer_prompt` text, to make the before/after
concrete — not part of the new design).

## Decisions — Ryan, 2026-09-18

1. **Referee call: dropped.** Ship single-call as designed. Rely on code-side checks (word count,
   forbidden-phrase regex) instead of a second LLM call for QA. No independent-review pass.
2. **Cross-machine state: confirmed.** Script-writing runs in roster/act order, stateful (opening-
   name running tally + prior sibling paragraphs passed as context) — not any-order like research.
3. **Storage: no database.** Drive export is sufficient on its own. Do not build DB rows for
   script output — matches the existing hand-prototype's actual output surface, no new storage
   layer needed.

All 3 open questions resolved — this design is now approved for implementation, same status as
research DESIGN.md.
