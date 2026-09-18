# SS-2 known-source recapture route inventory

Read-only source inspection on 2026-09-17. No request was sent.

The existing API is synchronous:

`POST /api/pipeline/machine-research-one/{video_id}`

It accepts this exact body shape:

```json
{
  "machine": "SS-2 USS Plunger",
  "confirmed_paid_run": true,
  "source_urls": [
    "https://www.historycentral.com/navy/Submarine/plunger.html",
    "https://www.navsource.net/archives/08/08002.htm"
  ]
}
```

`MachineResearchRequest` validates the body, the route requires
`confirmed_paid_run`, and tenant scope comes from `get_tenant_id`. It directly
awaits `PipelineExecutor.run_one_machine_research`; it does not create an ARQ
job or use the durable machine-preview job table. The current frontend helper
does not expose `source_urls`, so this is an API-level route contract.

The executor resolves the exact locked roster member before it accepts the
URLs. For non-empty `source_urls`, it validates them, makes a private copy of
the payload, and sets `_dvsu_known_sources = {machine: matched, urls: ...}`.
The selected-machine path then calls `_run_unit_research_hold` only for that
locked member. Its roster snapshot checks and tenant/video guarded checkpoints
remain in force; no other roster member is selected by this route.

`supplement_missing_research` recognizes `_dvsu_known_sources`. Explicit URLs
bypass the `discovery_completed` no-repeat early return, recapture only the
provided URLs, and, if gaps remain, take the explicit-URL return before the
targeted-discovery branch. Thus the two saved URLs are a bounded recapture path
and do not restart source discovery.

There is one receipt-preservation detail to verify in any parent fix. When a
recapture adds excerpts, `merge_research_sources` moves the old
`claim_assessment` into `prior_claim_assessments`; that preserves the old
`dvsu_recovery` receipt as historical data. The explicit-URL branch does not
itself restore `dvsu_recovery` onto the newly assessed top-level receipt. A
repair that requires the active receipt to retain `discovery_completed` must
copy it forward deliberately; current source only guarantees its retained prior
assessment copy. This does not cause a new discovery within the explicit-URL
branch.

Relevant source locations: `backend/routes/pipeline.py:127-130,1371-1400`,
`backend/pipeline_executor.py:11487-11557`, and
`backend/dvsu_research_handoff.py:121-123,151-176`.
