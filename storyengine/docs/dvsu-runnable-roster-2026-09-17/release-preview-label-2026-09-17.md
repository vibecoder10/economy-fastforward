# Cached-preview label follow-up release receipt

Released 2026-09-17 with the sanctioned command:

```sh
./scripts/se.sh deploy dvsu-preview-label-20260917 --with-frontend
```

## Scoped commit

- Full SHA: `f10e8f57048655c27511b05eae91c5910d9296e3`
- Subject: `fix: label cached script previews`
- The commit contained only:
  - `frontend/src/components/production/ScriptVoiceTab.tsx`
  - `frontend/tests/dvsu-runnable-roster.spec.ts`
- Local `main` was pushed to `origin/main` without force.

## Deployment evidence

- Pre-deploy drain status was normal with zero background tasks, zero generation claims, and zero total active work.
- The deploy safely drained at zero work, fast-forwarded `df316f28e` to `f10e8f570`, and left migrations at `169 applied / 0 pending`.
- The sanctioned output reported backend active and worker code parity at `f10e8f570`.
- Final `scripts/se.sh health` reported backend/frontend active, API healthy, frontend HTTP 200, normal drain, and no deploy lock.
- The deployment ledger records: `2026-09-17T17:58:37Z dvsu-preview-label-20260917 deployed df316f28e -> f10e8f570 --with-frontend`.

No provider, generation, data, force-push, raw SSH, or out-of-scope source action was taken.
