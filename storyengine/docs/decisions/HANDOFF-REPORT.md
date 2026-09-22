# HANDOFF — StoryEngine (resume cold, 2026-06-26)

Branch **`feat/director-pass`**, deploys straight to **`main`** (push `origin feat/director-pass:main`).
Latest work all live on main. Test video `973c9bd6-1fc7-43d8-802a-83a743a48d66` ("He Wanted A Big
Fish"), owner tenant `ee93e6d1-a9cc-44c3-81e9-84adee8329aa`, modeled from `youtube.com/watch?v=lecSrI7CJwo`.

## NEXT TASK (start here — fresh session, "option B")
**Make the thumbnail faithfully MODEL the competitor's thumbnail — style, colors, text, composition —
with our cast + our title.** The current clone flow is buggy/half-built. Full findings, the wrong-data
bug, code locations, and the plan are in memory **`storyengine-thumbnail-modeling-rebuild`**. Read it first.

## Done this session (all live on main)
The whole scene/clip pipeline was hardened (a long bug-hunt on scenes 1-3 of the test video):
- **grok-imagine lip-sync** proven; **per-clip duration** sized to the spoken line (6-30s, no cutoff,
  no over-fill gibberish); **dead-space auto-trim** at stitch time.
- **Dialogue placement EXACT** (Option B): coverage planner assigns one line per speaker TURN as it
  draws, deterministic reconcile guarantees one-speaker-per-shot, no drops/dups; motion-writer is
  camera-only. (memory `storyengine-grok-lipsync-confirmed`.)
- **Cinematic shot prompts** (subject stays in frame); **content-filter (430) auto-recovery**
  (redraw safer + retry); **16:9 aspect** now passed to grok + a **video_resolution selector**
  (480p/720p, migration 064); **silent-insert ad-lib** ducked out.
- **Storage switched Supabase → Google Drive** (the intended design) + media-proxy fixes. See memory
  `storyengine-storage-drive-switch`. **Pending: wipe old Supabase media** once Ryan grabs what he wants.
- Scenes 1-3 generated; scene 3 = the clean 16:9/1080p one. Full scenes-1-3 stitch in Drive. Scenes
  1-2 are the OLD portrait/low-res clips (not re-animated, by Ryan's call); 4-8 not built. The video
  was a BUG-FINDING vehicle, not meant to be finished.

## Known non-blockers
- Render button gated: a backend-built video sits at status `ready_for_image_prompts`, so the UI
  "Render Now" rejects ("not ready"); render music/resolution/format selectors aren't wired yet.
- Coverage can draw many silent cutaways on dialogue scenes (scene 3 = 9 speaking / 12 silent of 21).

## Deploy + verify cheatsheet
- Push `origin feat/director-pass:main` from LOCAL → on VPS `cd ~/projects/economy-fastforward &&
  git fetch origin && git merge --ff-only origin/main`. Backend: `kill -9 $(pgrep -f "uvicorn main:app"|head -1)`
  (SIGTERM hangs), systemd revives; confirm `/api/health` 200. Frontend: `cd storyengine/frontend &&
  npm run build` then `kill $(systemctl show -p MainPID --value storyengine-frontend.service)`; serves :3001.
- DB: `export DATABASE_URL=$(tr "\0" "\n" < /proc/$(pgrep -f uvicorn|head -1)/environ | grep ^DATABASE_URL= | cut -d= -f2-)`
  then `./venv/bin/python` from storyengine/backend. (information_schema has a `youtuber_bak` schema too —
  filter `table_schema='public'`.) Run pipeline funcs standalone with `PYTHONPATH=.` and the proc env loaded.
- Authed pages can't be browser-previewed locally — verify with `npm run build` / py_compile + DB checks.
