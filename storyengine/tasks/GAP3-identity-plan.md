# GAP 3 plan - machine identity declared by research, not guessed downstream

Draft for Ryan's /goal session, 2026-07-30. Source: G3-PLAN read-only sweep
(evidence verified against the live DB, file:line refs checked in code).
Nothing here is built yet - this is the plan to approve, amend, or reject.

## The problem, in plain English

Research produces a roster entry as a display string ("Lend-Lease escort
carriers Attacker class (US-built)"). Eight different downstream functions
then GUESS the machine's identity by regexing that glued string. The guesses
collide, and the collision is live on the carrier video d2e37cd6:

- `machine_research_cards` has 21 rows for a 23-machine roster. Indices 9 and
  21 were silently overwritten: "Audacious class / Malta class" and "CVA-01
  class" both hash to key CVA01; "Attacker class (US-built)" and "Ruler class
  (US-built)" both hash to LENDLEASEESCORTCARRIERS. Write path:
  `_upsert_machine_research_card` (pipeline_executor.py:7813-7841), keyed by
  `_normalized_unit_code` of the glued string, `ON CONFLICT DO UPDATE` - last
  write wins, no error.
- It is benign TODAY only by accident: single-machine reads go through the
  un-deduped payload list, not the table.
- Same class of bug waits in every other deriver: "M4 Sherman" and "M4
  Carbine" both tokenize to `m4` in static_docu's title matcher, so a carbine
  article can pass as a trusted photo source for the tank. The slash-split
  alias logic turned "Archer class / Empire Mac-Ship conversions" into the
  alias "Archer class", which names a real, different ship.

The full deriver inventory (8 functions across pipeline_executor.py and
static_docu.py, with file:line and a concrete breakage each) is in the G3
sweep report - headline: `_normalized_unit_code` alone has ~90 call sites.

## The fix

Research DECLARES identity per roster entry; downstream consumes the
declaration and stops re-deriving. New fields on each `unit_roster` entry
(additive, next to the existing `member_units` from C3):

- `canonical_name` - the one unique string everything downstream hashes.
- `search_aliases` - replaces the guessed comma/slash split.
- `disambiguators` - terms that separate this entry from same-token
  entities in other domains (kills M4-vs-M4 structurally).
- `identifier_kind` - designation / class_name / hull_number / program_name /
  no_formal_designation; tells `_unit_code` whether its aircraft-designation
  regex is even valid to run.

## Phasing (recommended order)

**Phase 0 - stop the bleeding (small, self-contained, could ship ahead of
the rest with your yes).** Key `machine_research_cards` writes and reads by
`roster_index`, which is already collision-free and carries a UNIQUE
constraint; demote `machine_key` to informational. Repair script: for any
video where distinct keys < roster length, replay `payload.unit_research_cards`
back into the table keyed by roster_index - recovers the two dropped rows on
d2e37cd6 with no payload changes. No prompt or contract changes. $0 in API
spend; the replay is a DB write, so it rides a deploy window.

**Phase 1 - the contract.** Emit the four fields in the roster prompt schema
(research/agent.py ROSTER_DISCOVERY_PROMPT_TEMPLATE, ~818-829), validate in
`_roster_validation` (the C3 contract-triangle pattern: prompt + repair
warning + gate in one commit), store them, and make machine_key a slug of
canonical_name for NEW writes. Backward compatible: old payloads without the
fields keep the current fallback path.

**Phase 2 - the consumer swap.** Move the 8 derivers to consume the declared
fields, function by function, with the two regex families (pipeline_executor
vs static_docu) changed in lockstep to avoid drift. This is the wide, slow
part (~90 call sites). Fold in the known noun-list gaps while touching them:
`_BUILT_COUNT_ZERO_RE` lacks helicopters/tanks/jeeps; `_GENERIC` lacks plural
"helicopters"/"vehicles".

**Explicitly untouched:** `static_reference_cache` keeps its current keys.
It is a tenant-global photo cache, not a source of truth - a miss just
re-fetches, and re-keying would invalidate every verified prod row for zero
data-loss benefit.

## Risks and open questions for Ryan

1. The consumer swap is a multi-session refactor, not one PR. Phase 0 and 1
   deliver the safety win early; Phase 2 can trail without leaving damage.
2. research/agent.py's schema is shared by the backend AND the standalone
   pipeline - one schema edit, many consumers, so Phase 1 must be additive
   like C3's member_units rollout.
3. Unchecked so far: whether the frontend displays or links machine_key
   anywhere (sweep gap - cheap to confirm before Phase 0), and whether any
   roster-prompt path exists beyond research/agent.py.
4. Decision needed: does Phase 0 ship inside the current bulletproofing loop
   (my recommendation - it is the only part that fixes silent data loss), or
   wait for the full GOAL.md pass?
