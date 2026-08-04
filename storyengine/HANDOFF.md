# HANDOFF - 2026-08-04 - carrier video: voice + pictures + thumbnail DONE, render blocked on one bug fix

## State
- Prod: 992cb3f0 deployed (se health verified: backend+frontend active, api healthy, no lock). 6 deploys this session.
- Branch: main pushed clean through 4b4e81b7. Worktree claude/sad-shamir-e31572 fully folded to main.
  Pre-existing dirt (untouched, not ours): storyengine/frontend/next-env.d.ts, stale tasks/loop-handoff.md.
- What shipped this session (carrier video d2e37cd6-521a-43aa-a14d-ce096a783c1e, tenant 561b872d):
  - VOICE 23/23 ($2.97): scenes 1-8 ElevenLabs v3, 9-23 v2 (Ryan kept them; redo cancelled cleanly mid-run).
    Tenant elevenlabs_model_id now eleven_v3 for ALL future videos. Voice durations now stamp at generation.
  - PICTURES 23/23, 67 frames, 0 parked ($5.35 incl. iteration): rotated views (quarter/side/top) enforced by a
    role-conformance vision judge; Ryan's anchor-chain architecture (first clean render feeds other angles);
    fill mode (rerun only generates missing views); roster-photo reuse; research-card facts ground title cards;
    CVA-01 gets honest Jane's-style BLUEPRINTS (never-built path + per-scene operator blueprint_override).
  - THUMBNAIL done ($0.10): "EVERY CLASS" red/black over the Argus render (first try wrote broken "EVERY BUILT").
  - Total ledgered $8.42 of the $20 cap. Status: ready_for_thumbnail (advance when render unblocks).

## Next action (start here cold)
The ONLY blocker is the render verb refusing static_docu videos ("nothing's been animated yet" - it demands clips
from a format that skips clips by design). Ryan already started fix chip task_baa632d0 in its own session.
1. Check that fix landed on main: cd ~/economy-fastforward/storyengine && git log --oneline -5 (look for the
   render-verb fix; also check the matcher-hardening session task_92cb9dd0 for a static_docu.py merge).
2. If landed: deploy via ssh storyengine-vps 'bash ~/projects/economy-fastforward/storyengine/scripts/vps-deploy.sh <name>'
   (check ~/deploy.lock + running background_tasks first - zero-activity window).
3. Then: MCP advance verb on d2e37cd6 (to ready_to_render), MCP render verb (compute-only, no external billing),
   watch via background_tasks, then eyes on the rendered video before any upload talk. Upload has skip-if-done.

## Open threads
- Render-verb format-blindness fix - task_baa632d0 RUNNING in separate session; render+upload blocked until it lands.
- Matcher hardening (scene-name -> roster entry tolerance) - task_92cb9dd0 running separately; expect static_docu.py merge.
- 4 machines have 2/3 views (parked thirds, honest judge rejects) - $0.05 each via fill runs, cosmetic, not blockers.
- Backlog unchanged: script-stage calls don't ledger; production-guide next_step says "characters" for static_docu
  (cosmetic); scripts.voice_id column stamps wrong id (runtime provably used vault voice); older parked items in
  tasks/loop-checklist.md.

## Gotchas learned this session
- Google Drive uploads via the engine UPDATE IN PLACE: same file id, new bytes. A file id is NEVER proof of
  freshness - re-download and compare bytes/duration (bit us on voice and thumbnail both).
- se db is read-only; prod writes go via scp'd asyncpg script with DATABASE_URL from ~/projects/.../storyengine/.env
  on the VPS (grep the var, don't source the file - it breaks). Token mint: /tmp/mint_tenant_token.py (se devtoken
  cannot bind tenant 561b872d).
- Scene-scoped pipeline runs (voice/images scene=N) do NOT advance video status - use the MCP advance verb after.
- Re-voicing needs scripts.script_status flipped back to 'Create' (skip guard keys on it); cancel endpoint
  POST /api/pipeline/cancel/{video_id} stops cleanly between scenes and ledgers only what was synthesized.
- Repeated angle/style generation failures = wrong input anchor, not wrong prompt wording (now in lessons.md + memory).
- First post-fix run is ONE billable unit, never the batch (Ryan's rule, now in lessons.md).
