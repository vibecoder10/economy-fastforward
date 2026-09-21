# HANDOFF - 2026-09-21 DVSU roster gate + Drive folder fix built, pushed, verified; awaiting deploy

## State
- `main` == `origin/main` (`559eebee` + this handoff commit), linear. VPS checkout
  `~/projects/economy-fastforward` is fast-forwarded to the same commit. **Prod backend is still running
  the OLD code and env** (no restart yet) - both fixes below go live on the next deploy.
- VPS `storyengine/.env` now has `DVSU_RESEARCH_DRIVE_FOLDER_ID=1cPXLQN1Xs5bWa2lPoQ2KL5ufJrA4ZqRU`
  (only read at process start).
- Full suite (backend venv): no new failures vs a clean baseline; +4 passing tests total this session.

## Shipped to main this session
1. `2f1a3e45` - `_live_roster_gate` no longer requires `independent_selection_audit` for DVSU v2
   (`factual_100_v1`) rosters (v2 skips that audit by design). Cause of production_guide "roster:
   not_started" for `6ac28204-681c-4839-9d11-6c3ba57b7b6e`; it also blocked run_unit_research and
   roster-image gathering. Verified on the VPS against the video's REAL saved payload: gate now
   returns passed=true, 20 machines, no warnings.
2. `559eebee` - Drive export targets a Shared Drive folder by ID: `google_client.py` passes
   supportsAllDrives/includeItemsFromAllDrives on create_folder/search_folder/search_file/upload_file;
   `dvsu_roster_v2.research_root_folder()` uses `DVSU_RESEARCH_DRIVE_FOLDER_ID` (name lookup when unset),
   used by both roster and machine-packet exports. Live-verified: real export from the VPS with the
   backend's credentials landed in folder `1GP07If5NlbeC8smSooXhCJgrL37DUQrq`, whose parent is
   `1cPXLQN1...` (Ryan's intended Shared Drive folder).

## Next action (start here cold)
1. **Deploy (ask Ryan first - live system):** `scripts/se.sh deploy <session-name>`; lock was absent.
   Backend-only, no frontend change.
2. After deploy: `get_production_guide` for `6ac28204-681c-4839-9d11-6c3ba57b7b6e` should show roster
   done; then confirm `systemctl is-active storyengine-backend.service` via `se health`.
3. Ask Ryan: the two earlier test files (thesis+roster, shared context) are still in the pipeline's old
   "StoryEngine Research" folder `1H7uG1YDAmZFMcZm_-8ykbXIIN3INycRs` (under "Storyengine"). A fresh copy is
   already in the right place, so nothing needs moving; Ryan can trash the old folder or leave it.
4. Then Phase 1 roster half is done. Next: live-verify Research (Call 3) the same way (mock the LLM call,
   run the real code, check the DB + Drive). Phase 2 (script) stays untouched until Phase 1 closes.

## Open threads
- No Anthropic API key exists for this tenant (bot_activity 401s); real non-mocked runs fail until fixed.
- Test video `6ac28204...` holds a hand-composed submarine roster (Claude-written, not web-verified) -
  keep / regenerate once a key exists / discard.
- **SECURITY: VPS git remote URL embeds a GitHub personal access token in plain text**
  (`~/projects/economy-fastforward/.git/config`); it also appeared in session output. Rotate it and switch to
  a deploy key or credential helper.
- VPS repo pre-push hook (`.githooks`) blocks pushes of 3+ files unless `tasks/lessons.md` and
  `tasks/todo.md` are updated in the commit.
- An untracked `storyengine/jev-key-box.html` appeared locally mid-session (not from this work) - left alone.

## Gotchas
- Ryan's rule: keep git clean yourself - fetch at start, fast-forward main, linear commits on main, remove
  worktrees/branches you create. Never leave him a merge to remember.
- Context-ceiling hook now warns at 400k (was 150k): `~/.claude/scripts/context-ceiling-warn.py`.
- zsh: `echo =====` errors (`=cmd` expansion) - quote it.

---
paste this to start the next session:
Resume StoryEngine. Read HANDOFF.md first. Next action: get Ryan's yes, then deploy main (roster-gate fix +
Drive Shared-Drive fix) with `scripts/se.sh deploy`, then verify get_production_guide shows roster done for
video 6ac28204-681c-4839-9d11-6c3ba57b7b6e, then live-verify Research (Call 3).
