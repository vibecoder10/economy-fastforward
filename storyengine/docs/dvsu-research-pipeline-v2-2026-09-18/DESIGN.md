# DVSU research pipeline v2 — design spec

Status: design validated via hand-run prototype (Osiris acting as the LLM directly, using its own
WebSearch tool — no new infrastructure built). 4 of 20 machines fully researched and written to
Drive as proof. Not yet implemented as code. This is the durable record of the design — CHECKLIST.md
tracks status/scope, this file is the actual spec.

Replaces: `research/agent.py` (roster), `factual_source_search.py` (source discovery),
`research_claim_assessment.py` (claim assessment), `factual_machine_summary.py`'s research path
(briefing writer) — see HANDOFF.md history / CHECKLIST.md for why (expensive: 4-5 LLM calls per
machine with retries/review passes; non-deterministic: temp-0.7 roster + variable web search).

## Pipeline shape: 3 call types

1. **Thesis + Acts** — 1 call, no search, once per video.
2. **Roster + shared context** — 1 search-enabled call, once per video. Produces the 20-25 machine
   roster AND 3-5 cross-cutting facts as one output (folded together so the roster call's own
   research work isn't wasted — no separate call needed for shared context).
3. **Per-machine research packet** — repeated once per machine (~20-25x per video). Internally
   **6 separate, narrowly-targeted search calls**, never one broad combined search — this was a
   correction made mid-design: a first attempt combined all 6 questions into one broad query and
   produced worse, less specific answers than running 6 discrete searches.

## Two locked rules (apply to every Stage 3 search)

1. **One targeted search per question slot.** Never a single broad query trying to cover multiple
   questions at once. Proven concretely on USS Nautilus: the broad-query version missed the best
   available facts; the 6-discrete-query version found a specific 1954 USNI Proceedings source for
   the "why nuclear power" question and a genuinely surprising fact (Mamie Eisenhower's christening)
   that the broad search never surfaced.
2. **Primary/institutional sources preferred over Wikipedia.** Navy History and Heritage Command,
   museum associations (e.g. Submarine Force Library & Museum), USNI Proceedings, established
   history publications. Wikipedia only as an absolute last resort, and should be replaced on a
   follow-up search if used. Proven on Thresher and S-class: replacing Wikipedia citations with the
   Submarine Force Museum's own account produced *better*, more specific facts (a direct
   last-transmission quote; a legal-fault-split detail), not just "more proper" sourcing.

## Call 1 — Thesis + Acts (no search, cheap, once per video)

**System prompt:**
```
You are a documentary structure analyst for DvsU, an engineering-history channel. DvsU videos are
not about machines - they are about one engineering argument, proven through a sequence of machines.
War is the setting. Engineering is the story.
```

**User prompt template:**
```
Video title: "{TITLE}"

Formulate ONE thesis for this video - a single engineering argument the whole video will prove.
Strong theses read like: "Britain kept cancelling the right tank and building the wrong one."
Then break that thesis into 4-7 acts. Each act is one sentence describing a distinct step in the
argument, NOT a time period. Example acts: "The missile replaces the gun." / "The carrier becomes
a country." Moving between acts should feel like the argument shifting, not a timeline advancing.

Return only JSON: {"thesis": "...", "acts": [{"act_number": 1, "argument": "one sentence"}, ...]}
```

Worked example (title: "Every British Battleship Ever Built"):
```json
{
  "thesis": "The Royal Navy kept solving the previous decade's problem instead of the next one.",
  "acts": [
    {"act_number": 1, "argument": "The Navy tried to remove everything but the guns."},
    {"act_number": 2, "argument": "The Navy tried to maximize every variable at once."},
    {"act_number": 3, "argument": "The Navy learned moderation was the real constraint."},
    {"act_number": 4, "argument": "The Navy overcorrected toward pure protection."}
  ]
}
```

## Call 2 — Roster + shared context (1 search-enabled call, once per video)

**System prompt:**
```
You research real named military machines using web search. You never invent a machine, a
production number, or a date - every claim must trace to a search result. Output only the
requested JSON.
```

**User prompt template:**
```
Video title: "{TITLE}"
Thesis: "{THESIS}"
Acts:
{numbered list of acts}

Using web search, find 20-25 real, specifically-named machines (not a category like "destroyers"
or "cruisers" - one concrete named unit or named class, e.g. "HMS Devastation", "Ajax class") that
together prove this thesis. Assign every machine to exactly one act - the machine must exist
BECAUSE it proves that act's argument. If two machines would prove the same point, keep only the
stronger one. Order machines chronologically within each act.

Also note 3-5 facts you encounter that apply across MULTIPLE machines rather than one specific
unit (a shared technological shift, a doctrine change, an external event that reframes several
entries) - these will be given to the per-machine research step as background, so it isn't
re-discovered 20 times.

Return only JSON: {"roster": [{"machine": "...", "act_number": 1}, ...],
"shared_context": ["...", ...]}
```

No separate roster-validation pass by design — a machine that can't find real sources at Stage 3
is the validation. This intentionally removes the current pipeline's separate roster-coverage
audit / repair-loop complexity.

## Call 3 — Per-machine research packet (6 targeted searches, once per machine)

**System prompt:**
```
You research one specific named military machine using web search, for a documentary paragraph
about the engineering decision it represents - not a biography of the machine. Every fact must
trace to a search result; cite the source URL for each answer. Never invent a date, number, or
quote. Prefer primary/institutional sources (official history offices, museums, established
history publications) over Wikipedia; use Wikipedia only as a last resort. Output only the
requested JSON.
```

**Six separate targeted searches per machine** (never one combined broad search):

1. **Problem** — "why did [need/authority] want/need {MACHINE}" — what situation or need required
   this machine.
2. **Design** — "{MACHINE} design decision/innovation {specific feature}" — the specific
   engineering decision made in response.
3. **Trade-off** — "{MACHINE} limitation/trade-off {specific consequence}" — what was sacrificed to
   get that design.
4. **Outcome (broad)** — "{MACHINE} {event/record/fate}" — gather 2-4 candidate facts (a dated
   event, a production/scale number, a failure mode or operator account, its eventual fate). Don't
   pick just one in the search itself — surface several, let the writer choose later.
5. **Surprising fact** — "{MACHINE} interesting/little-known fact" or a specific named-detail query
   once something promising turns up in the other searches (e.g. searching a named person or
   incident mentioned in passing) — one fact most viewers wouldn't already know.
6. **Contrast** — "{MACHINE} intended vs actual / obsoleted / legacy" — the gap between what it was
   designed/intended for and what actually happened, or how it's remembered now.

**Per-question output shape:** `{"answer": "...", "source_url": "...", "quote": "..." }` for
slots 1-3, 5-6; slot 4 (Outcome) is a list of 2-4 such objects.

**Full packet JSON shape:**
```json
{"machine": "...", "act_number": 1,
 "problem": {"answer": "...", "source_url": "...", "quote": "..."},
 "design": {"answer": "...", "source_url": "...", "quote": "..."},
 "trade_off": {"answer": "...", "source_url": "...", "quote": "..."},
 "outcome_candidates": [{"fact": "...", "source_url": "...", "quote": "..."}, ...],
 "surprising_fact": {"answer": "...", "source_url": "...", "quote": "..."},
 "contrast": {"answer": "...", "source_url": "...", "quote": "..."}}
```

## Output file layout (Drive, as prototyped)

```
StoryEngine Research/<Video Title>/
  00-thesis-and-roster.md      # Call 1 + Call 2's roster half
  01-shared-context.md         # Call 2's shared_context half
  machines/
    <machine-slug>.md          # one file per machine, Call 3 output as markdown
```

**Decision — Ryan, 2026-09-18: no database. Drive export is sufficient on its own.** Do not build
new DB tables/rows for roster/research output.

**Unresolved tension flagged for next session, not resolved here:** CHECKLIST.md's Done-when
requires "the existing UI/API surface for Research/Script stages still works unchanged against the
new backend, verified live in the browser." The current frontend renders roster/photos/research
from DB-backed routes. If storage is Drive-only, the backend routes need to read from Drive instead
of DB to keep that UI contract - a real (if small) piece of implementation work, not a given. Get
Ryan's confirmation on this specific mechanics question (backend reads Drive live vs. some other
bridge) before writing the pipeline_executor.py wiring.

## How the 6-slot template was derived

Reverse-engineered from 4 real finished DvsU-style scripts Ryan supplied (ironclads/battleships,
Vietnam-era helicopters, helicopter danger/reliability + "most hated warships," American
pre-dreadnought/dreadnought battleship lineage), then reconciled against the channel's actual style
guide ("DvsU — Script Writing System v3," full text pasted by Ryan this session — not yet saved to
a file anywhere; if this becomes load-bearing for the script-writing design too, get Ryan to
re-supply it or locate wherever the other session saved it, per HANDOFF.md's open thread on this).

The v3 spec's own paragraph logic (Problem → Design → Trade-off → Outcome, one surprising fact
required, ending must land as a contrast/irony/paradox) is what the 6-slot template maps directly
onto — Design/Trade-off/Problem map 1:1, "Outcome" is deliberately broad because the v3 spec treats
multiple evidence types (event, stat, failure mode, fate, legacy) as candidates for a single
paragraph beat, and Surprising-fact + Contrast are called out explicitly because the v3 spec
requires them and they don't reliably fall out of the other 4 by accident.
