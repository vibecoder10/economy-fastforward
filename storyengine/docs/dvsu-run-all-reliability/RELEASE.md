# Scoped release and rollback

Prepared locally from `main` at `9e77c2cb40963ca3c0df988484be2d436440c08d`. No commit, push, deploy, migration or provider submission is included in the completed work. `release-manifest.json` and `release.patch` identify the exact code/test/fixture changes. Preserve all unlisted dirty and untracked work.

## Deployment — separate approval required

1. Verify the manifest hashes and current Git/remote state. Stage only listed implementation files; include REPORT/RELEASE/plan/check receipts deliberately if desired. Never use `git add .`. If upstream changed, reconcile and rerun only affected checks before release.
2. Drain new generation with `scripts/se.sh drain dvsu-reliability`; inspect drain status and stop if paid work is still active. Record deployed SHA and service/source hashes for rollback.
3. Apply migrations 161 and 162 through the existing migration mechanism. They create backend-only operation journals with RLS and tenant/video foreign keys. Existing `videos_tenant_id_id_uidx` was verified read-only in `migration-prerequisites.jsonl`. Stop on any migration error before provider traffic.
4. Commit/push only the scoped change and deploy with `scripts/se.sh deploy dvsu-run-all-reliability --with-frontend`. Verify backend and worker run the same release, source hashes match, API and frontend are healthy, and journals are available. Do not accept an HTTP 200 alone as release proof.
5. Walk readiness/preview status/error display in the browser without clicking a generation action. Recheck saved production/source/preview state against the baseline. Clear the deployment drain only after health and parity checks; do not launch Run All.

## Rollback

Keep generation drained. Revert only the release commit, preserving unrelated work; push/deploy the revert through se.sh and verify worker/backend parity and health. Retain both additive journal tables and rows: they are recovery evidence, not disposable schema. Before permitting old code to generate, reconcile every submitted/uncertain operation because old code does not honor these receipts. No rollback authorizes resubmitting a possibly billed request. Save original/new SHAs and all readbacks.

## Paid canary — another approval required

Scope: one S-1 preview from its unchanged saved package, zero discovery calls, no production promotion, voice, images, render or upload. Read-only `.env` configuration currently selects direct Anthropic `claude-opus-4-5-20251101`; verify effective runtime model/host again before submitting, since process environment may override the file.

Proposed approval ceiling: $1.50 for this one canary. The compiled path permits at most two 900-output-token writer calls and two 2,200-output-token review calls. Each request has a 48,000-input-token conservative byte bound. At Opus 4.5 standard $5/M input and $25/M output, the conservative request bound is $1.115 total. Source: [Anthropic Opus 4.5 pricing](https://www.anthropic.com/news/claude-opus-4-5), checked 2026-09-17. No SDK or wrapper retries are allowed in this journaled path. Recheck actual request/model/token limits before starting; stop if this bound cannot be established. Do not rely on the generic script ledger estimate to enforce this approval.

Before the canary, snapshot the S-1 package and previews, prove saved-evidence readiness, verify there is no prior unresolved matching script operation and reserve the entire quoted ceiling within the authorized video budget. Invoke the normal single-machine preview once. Stop after its bounded result; unresolved submissions require reconciliation rather than another click. Inspect the actual narration, 80–110 words, citation map, identity, factual/editorial receipts and zero source-operation delta. Record manual interventions and obtain editorial acceptance before expanding.

Remaining video estimate is not yet a firm quote: configured static images are approximately $3 for 20 scenes × three views × $0.05, and configured voice is $0.10 per 1,000 characters. Those are local configuration estimates, exclude retries/rejected media and do not establish provider availability or actual billing. Quote the remaining scripts/voice/images/audio after canary review and actual narration lengths. The recorded $0.0573 baseline consists of Kie research entries only, not verified all-provider spend.

## Final delivery gate

After separately authorized completion, inspect the encoded MP4 for scene coverage, playback, sound, duration and synchronization. Register the exact completed file in AgentVault Generations and verify live gallery readback. Ryan must watch and listen before marking the feature complete. Upload remains excluded.
