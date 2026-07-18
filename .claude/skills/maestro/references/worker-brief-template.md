# Sonnet worker brief — template

Every worker brief carries these sections. Keep it tight but complete: the
worker reads the files, the orchestrator doesn't — so anything the worker
needs (file paths, line hints, gotchas from past corrections) must be IN the
brief, not assumed.

Fill `<...>` per chunk; drop sections that genuinely don't apply (e.g. no
Cost cap section for a docs-only chunk). If the project has a playbook with
its own brief template (this repo: `tasks/orchestrator-and-worker-playbook.md`
§3 for StoryEngine work), prefer that version — it carries project-specific
rules this generic one can't know.

```
You are the Sonnet worker for chunk **<id> · <title>**. <1 sentence: what + why>.

Repo root: <path>. Working branch: `<branch>` (already checked out; do NOT
switch/create branches, do NOT push, do NOT merge — the orchestrator merges).

## Chunk spec (from tasks/loop-checklist.md)
<paste the chunk's bullets verbatim; name specific files/functions/line hints;
include any lessons noted on the checklist from prior corrections>

## Cost cap
<sandbox constraints: no paid API calls / use --dry-run / cheapest path.
Never perform an irreversible external action (publish, delete, send).>

## Verify
<the chunk's VERIFY step, plus the evidence contract:>
- Prove your tests are real: `git stash` your changes, show the tests FAIL,
  `git stash pop`, show they pass. A test that passes both ways is vacuous.
- Run the full relevant suite; report counts vs the pre-existing baseline —
  zero NEW failures is the regression proof.
- Run the project's static checks on touched files (compile/typecheck/lint).
- Anything you cannot verify in this sandbox (money, live services, browser):
  say so explicitly and write the exact manual recipe + expected result for
  tasks/deferred-verification.md. Be honest; never fabricate a result.

## Deliverables
1. Implement ALL listed layers of the chunk end-to-end — goal, not just
   bullets (if the primary user-facing path still fails, the chunk isn't done).
2. Update any structural docs the project requires (e.g. SYSTEM_STATE.md)
   if files/tables/routes moved or were created.
3. Commit to the branch with message starting `<id>: <summary>`. Set the
   project's commit identity first if it has one. Do NOT push.

## Report back to the orchestrator ONLY (tight):
- Files touched (+ any migration/column/endpoint added).
- Key evidence: quote the decisive code (the condition/write/resolver),
  prove the default/existing path is unchanged, paste test output.
- Stash-proof result and full-suite counts vs baseline.
- Static check status. Commit SHA.
- Explicit safe-to-merge assessment: does this change existing behavior?
  merge vs hold?
- Anything you couldn't verify (honest list), pre-existing bugs found,
  blockers.
```

## Sizing and variants

- **Too big for one pass?** Tell the worker to STOP, split the chunk in the
  checklist, and do part 1 only.
- **SWEEP/REVIEW chunks** run as ONE read-only Sonnet `Explore` agent: it
  audits, it does not edit. Findings become new checklist chunks the same
  iteration.
- **Second-opinion verification** (thin evidence on a high-blast-radius
  chunk): a read-only Sonnet `Explore` agent briefed to hunt for the ONE
  failure mode the tests can't catch (stale callers, off-by-one placeholders,
  NULL-path defaults) — cheaper than the orchestrator reading the code itself.
