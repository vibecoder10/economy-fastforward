# HANDOFF - 2026-09-21 DVSU roster gate fixed; Drive folder fix is next

## State
- `main` == `origin/main`, linear, clean (one commit this session: roster-gate fix + docs). Stale
  `.worktrees/dvsu-pipeline-v2` worktree and its merged branch were removed.
- **Prod is NOT redeployed yet** - the roster-gate fix is pushed but undeployed. Deploy needs Ryan's yes
  (`scripts/se.sh deploy <name>`; lock file was absent at last check).
- Tests: full suite baseline vs patched = identical failing sets (113 failed + 4 collection errors,
  all pre-existing), patched has +1 passing (the new regression test). Run with the backend venv.

## Done this session
- Root cause of `production_guide` showing "roster: not_started" for test video
  `6ac28204-681c-4839-9d11-6c3ba57b7b6e`: NOT `videos.status` (it's `approved`; the guide never reads it
  for static docs). `_live_roster_gate` (backend/pipeline_executor.py) demanded
  `independent_selection_audit.passed` for every runtime selection, but the DVSU v2 roster path skips
  that audit by design. Fix: exempt `factual_100_v1` (`is_factual_machine_contract`) from the audit
  check. The same gate also blocked run_unit_research and roster-image gathering for v2 videos, so this
  unblocks Call 3. Test: `test_live_roster_gate_accepts_saved_v2_roster_without_independent_audit`.
- Diagnosed the Drive mixup (not fixed): `GoogleClient.get_or_create_folder` IS parent-scoped. Root =
  env `GOOGLE_DRIVE_FOLDER_ID` = folder "Storyengine" (`1NBFKU8h56qlJS8sUbcAFNMp8_STf19Qy`, My Drive,
  in VPS `storyengine/.env`). "StoryEngine Research" is found/created inside it -> `1H7uG1YDAmZFMcZm_-8ykbXIIN3INycRs`
  (pipeline-created 2026-09-19). Ryan wants `1cPXLQN1Xs5bWa2lPoQ2KL5ufJrA4ZqRU` (Shared Drive root
  `0AGEVWQ9GwbVCUk9PVA`, created 2026-09-18). `skills/video-pipeline/shared/clients/google_client.py`
  has NO `supportsAllDrives`/`includeItemsFromAllDrives` anywhere, so it cannot see or write into a
  Shared Drive at all.

## Next action (start here cold) - Ryan approved the recommended option
1. `google_client.py`: add `supportsAllDrives=True` (+ `includeItemsFromAllDrives=True` on list) to
   `create_folder`, `search_folder`, and the upload create/update calls (lines ~196, 242, 404, 468-475).
   Harmless for My Drive. Leave other call sites alone.
2. `dvsu_roster_v2.py:349-351` and `dvsu_research_v2.py:554-557`: resolve the root by ID from env
   `DVSU_RESEARCH_DRIVE_FOLDER_ID` when set (one shared helper), else fall back to the name lookup.
   Add tests with a fake client.
3. Set `DVSU_RESEARCH_DRIVE_FOLDER_ID=1cPXLQN1Xs5bWa2lPoQ2KL5ufJrA4ZqRU` in the VPS
   `~/projects/economy-fastforward/storyengine/.env` (parent .env, not backend/.env).
4. Live write test from the VPS with the backend's own credentials (scratchpad script + scp, not inline
   ssh python). Confirm via Drive that the file's parent is `1cPXLQN1...`. Unknown until tested: whether
   the backend's Google login is a member of that Shared Drive.
5. Ask Ryan: move the two already-written test files, or leave them in `1H7uG1Yd...`.
6. Deploy (ask first), then re-check `get_production_guide` for the test video shows roster done.

## Open threads
- No Anthropic API key exists for this tenant (bot_activity 401s). Real non-mocked runs keep failing until
  Ryan fixes that. Test video `6ac28204...` holds a hand-composed submarine roster - keep/regenerate/discard.
- Research (Call 3) still needs its own live-verification pass. Phase 2 (script) untouched until Phase 1 closes.
- **SECURITY: the VPS git remote URL embeds a GitHub personal access token in plain text**
  (`~/projects/economy-fastforward/.git/config`). Recommend rotating it and switching to a credential
  helper / deploy key. It has also appeared in this session's transcript.
- VPS repo has a pre-push hook (`.githooks`): pushes of 3+ files are blocked unless `tasks/lessons.md`
  and `tasks/todo.md` are updated in the commit.

## Gotchas
- Ryan's rule: keep git clean yourself. Fetch at session start, fast-forward main, commit linearly on
  main, delete worktrees/branches you create. Never leave him a merge to remember.
- zsh: `echo =====` errors (`=cmd` expansion) - quote it.

---
paste this to start the next session:
Resume StoryEngine. Read HANDOFF.md first. Next action: the DVSU Drive folder fix (Shared Drive by ID,
per HANDOFF.md "Next action" steps 1-6). The roster-gate fix is already pushed to main; confirm with Ryan
before deploying.
