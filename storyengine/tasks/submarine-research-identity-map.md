# Submarine research identity map

Input inspected: `tasks/representative-roster-acceptance.json` (accepted at
`2026-09-16T19:43:44.210729+00:00`), `frontend/src/components/production/ResearchTab.tsx`,
`backend/routes/{videos,pipeline}.py`, and `backend/pipeline_executor.py`.

## Accepted identity contract

The acceptance receipt names and orders 20 exact submarine display labels, from
`SS-1 USS Holland` through `SSBN-616 USS Lafayette`; its UI receipt says
`20/20 selected and independently accepted.`  This is the source roster for
research selection.  It is not a class/range roster and it has no accepted
research cards yet.

Backend canonical display-name construction is `_unit_display_name` in
`backend/pipeline_executor.py:72-81`.  Exact display-name matching, followed
only by a unique normalized-code fallback, is implemented by
`_roster_index_for_identity` at `backend/pipeline_executor.py:928-954`.

## Current path and anchors

| Boundary | Current behavior | Anchor |
|---|---|---|
| Video detail sent to ResearchTab | Enriches existing `unit_research_cards` with DB verdicts, then applies live roster validation. It does not call the compact-card filtering loader. | `backend/routes/videos.py:753-760` |
| Roster dashboard | Reads the locked roster, calls `_load_machine_research_cards`, then emits one row per roster position with its card/package/verdict/reference state. | `backend/routes/pipeline.py:1458-1474`; `backend/pipeline_executor.py:12446-12576` |
| All-roster research | Recomputes the live roster gate, requires completed current-roster image gathering, then passes the locked roster into `_run_unit_research_hold`. | `backend/routes/pipeline.py:1313-1352`; `backend/pipeline_executor.py:12579-12629` |
| One-submarine research | Accepts a user-supplied `machine` only after paid confirmation, then delegates to `run_one_machine_research`. | `backend/routes/pipeline.py:1285-1311` |
| Compact card hydration | Reads `machine_research_cards` by tenant/video, rejects rows whose `roster_index`, normalized machine name, or resolved card identity do not match the locked roster slot; returns compact cards in roster-index order. | `backend/pipeline_executor.py:10018-10130` |
| UI list / selected inspector | Iterates `research.unit_roster`, renders its label, and finds its card/package by helper match. The select uses the same roster labels as values. | `frontend/src/components/production/ResearchTab.tsx:1602-1613`, `1662-1665`, `1759-1772` |

## Exact-name join assessment

The backend has the intended durable identity: `machine_research_cards.roster_index`
is the primary row identity.  The loader's range/identity rejection is concrete:
it skips a row when its position is out of range, its `machine_name` code differs
from the roster slot, or its card identity does not resolve to that same slot
(`backend/pipeline_executor.py:10088-10100`).  The dashboard therefore represents
only the current accepted roster.

The video-detail path exposes a narrower stale-card risk.  `enrich_research_payload_readiness`
attaches readiness to every JSONB card still in `unit_research_cards`, but does
not apply `_load_machine_research_cards` filtering (`backend/pipeline_executor.py:4342-4416`).
ResearchTab then joins by `machineLabelMatches`, which considers *either* exact
full label equality *or* normalized code equality (`ResearchTab.tsx:85-96`).

For the accepted named-submarine roster, hull codes are unique, so ordinary
valid card joins work.  But a stale card such as `SS-212 USS Gato class` would
join the accepted `SS-212 USS Gato` solely because both normalize to `SS212`.
The same code-only fallback is used for `machine_raw_source_packages` in
`sourcePackageForMachine` (`ResearchTab.tsx:733-755`).  That can display a
stale range/class card and its package as Gato's current exact-submarine card.
This is the concrete mismatch with the requested exact named-submarine contract.

## Label parity

The actual rendered roster labels preserve the accepted names and order because
they come from `research.unit_roster` (`ResearchTab.tsx:1606-1610`, `1662-1665`,
`1764-1767`).  However, the user-facing headings still say `Machine research
roster` and `Selected machine inspector` (`ResearchTab.tsx:1622`, `1753`).
That is terminology drift from the accepted submarine roster; it does not alter
the selection value or backend research input.

## Focused acceptance tests for a later implementation

1. With the accepted 20-name array, render exactly 20 list rows and exactly 20
   select options in receipt order; each row label must exactly equal the
   corresponding accepted label.
2. With a saved card and source package both labeled `SS-212 USS Gato`, the
   Gato row receives that card/package and no other row does.
3. With a stale range card/package labeled `SS-212 USS Gato class`, the exact
   `SS-212 USS Gato` row must remain `Not run` and show no stale source package.
   This currently fails at the UI code fallback.
4. With a compact DB row at `roster_index=21`, the dashboard must omit it and
   still return exactly 20 ordered units. With an in-range index whose card
   identity is a class/range label, it must also be omitted.
5. With a verified current card and a failed current card, retain the failed
   current card plus its warnings in video detail; do not replace it with a
   different hull-code-matched range card.
6. Rename the visible headings and action copy to `submarine` only after the
   exact-name/card/package test is passing; this is label parity, not evidence
   or readiness logic.

## Scope conclusion

No implementation, API call, provider call, deployment, or data mutation was
performed.  The material design decision for Astra is whether video-detail
payloads should receive the same stale-card isolation as the dashboard, and
whether UI card/package matching must be exact display-name only once a locked
runtime roster exists.
