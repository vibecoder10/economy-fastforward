# Runnable DVSU roster release preflight

Checked at 2026-09-17T17:43Z. This is a read-only preflight; no commit, push, deploy, or job action was taken.

## Checkout identity

- Command working directory: `/Users/ryanayler/AgentVault/Projects/story-engine/storyengine`
- Git top-level: `/Users/ryanayler/AgentVault/Projects/story-engine`
- Branch: `main`
- HEAD: `cbbb0492c9d8b6b38a35c3ef5b641b92bc96a21f`
- `origin`: `https://github.com/vibecoder10/economy-fastforward.git` (fetch/push)
- `vps`: `storyengine-vps:projects/economy-fastforward` (fetch/push)
- Local `main` and the locally recorded `origin/main` are even: `0 behind, 0 ahead` at the checked ref `cbbb0492c9d8b6b38a35c3ef5b641b92bc96a21f`.

## Live release safety gate

`scripts/se.sh drain-status` reported normal mode, `draining: false`, and zero active work: `background_tasks: 0`, `generation_claims: 0`, `total: 0`.

`scripts/se.sh health` reported both backend and frontend active, API `healthy`, database/storage true, frontend HTTP 200, no deploy lock, and 134G disk free. It recorded the deployed SHA as `cbbb0492c` at 2026-09-17T17:05:53Z.

No active jobs require a stop. A future release must re-run these checks immediately before deploying and stop if either active-work count is nonzero or drain status changes.

## Intended source allowlist

Modified tracked source files in scope:

- `backend/factual_machine_pipeline.py` (+56/-1)
- `backend/tests/functional/test_factual_machine_pipeline.py` (+197/-0)
- `frontend/src/components/production/ScriptVoiceTab.tsx` (+63/-14)

New focused test file in scope:

- `frontend/tests/dvsu-runnable-roster.spec.ts` (102 lines)

`git diff --check` passed for the three tracked source files. Test execution and rendered-page verification have not yet run in this preflight.

## Worktree boundary and readiness

The checkout contains substantial unrelated modified and untracked work, including root documentation/configuration, task receipts, and other plan directories. Preserve it. Any scoped commit must use an explicit file allowlist limited to the four files above plus this release record only if its inclusion is desired; do not use broad staging.

Readiness: **conditional GO after parent approval**. The live service gate is clear and the local branch matches the recorded `origin/main`; remaining prerequisites are the planned focused backend/frontend tests, frontend typecheck/build, rendered-page verification with provider POST interception, and an explicit parent-approved commit allowlist. Do not force-push, bypass drain, use raw SSH, or trigger paid generation.
