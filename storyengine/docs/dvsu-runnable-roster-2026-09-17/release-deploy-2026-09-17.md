# Runnable DVSU roster release receipt

Released 2026-09-17 using the sanctioned command:

```sh
./scripts/se.sh deploy dvsu-runnable-roster-20260917 --with-frontend
```

## Committed and pushed scope

- Commit: `df316f28e8c46cc06b59d0c3b988b2fa35e585ad` (`fix: prepare runnable DVSU roster scripts`)
- Branch and recorded `origin/main`: both `df316f28e8c46cc06b59d0c3b988b2fa35e585ad` after push.
- Commit contained only the approved five source/test files:
  - `backend/factual_machine_pipeline.py`
  - `backend/tests/functional/test_factual_machine_pipeline.py`
  - `backend/tests/functional/test_script_voice_machine_preview.py`
  - `frontend/src/components/production/ScriptVoiceTab.tsx`
  - `frontend/tests/dvsu-runnable-roster.spec.ts`

Unrelated dirty and untracked work remained unstaged and untouched.

## Deployment evidence

- Immediately before deployment: drain was normal with zero background tasks and zero generation claims.
- Deploy drained safely at zero work, fast-forwarded remote code from `cbbb0492c` to `df316f28e`, and found migrations `169 applied / 0 pending`.
- During deployment, the sanctioned script reported backend active and worker code parity: `commit=df316f28e`, directory `/home/clawd/projects/economy-fastforward/storyengine/backend`.
- Final `scripts/se.sh health`: backend and frontend active; API healthy with database/storage true; frontend HTTP 200; deploy lock clear; deploy recorded at `2026-09-17T17:52:23Z` as `cbbb0492c -> df316f28e --with-frontend`.
- Final `scripts/se.sh drain-status`: normal, `draining: false`, `background_tasks: 0`, `generation_claims: 0`, `total: 0`.

No raw SSH, forced deployment/push, data mutation, or provider/generation action was used.
