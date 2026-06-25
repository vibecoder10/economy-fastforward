# HANDOFF - StoryEngine director pass (resume cold, 2026-06-25)

Resume here. Branch **`feat/director-pass`**, deployed live to `main` throughout. Latest commit at
write time: **`b7fa1166`**. Read `storyengine/GOAL.md` (the v2 plan) + `storyengine/AUDIT-2026-06-24.md`
(the receipts) + memory `storyengine-goal-v2-director-pass` for the why. This file is the WHAT-NOW.

## The test video (everything below was proven on it)
`973c9bd6-1fc7-43d8-802a-83a743a48d66` — "He Wanted A Big Fish…", modeled from the ESL reference
`youtube.com/watch?v=lecSrI7CJwo`. State: dialogue script (8 scenes, **one location each**), 4-view
cast sheets (Tom + Dad), 4 approved environments (Living room, Tom's bedroom, Lake shore, Car park),
scene 1 + 2 coverage frames drawn (character + environment lock verified clean), motion prompts
written (dialogue-aware). Owner tenant `ee93e6d1-a9cc-44c3-81e9-84adee8329aa` (ryan.ayler@gmail.com).

## WHERE WE LEFT OFF — the immediate next action
Testing **grok-imagine lip-sync**. Key discovery: grok-imagine 1.5 *does* lip-sync dialogue when the
spoken line is in the prompt (kie.ai format, inline: `<Name> says <manner>: "<line>"`). The motion-
writer now embeds the verbatim line on shots where a character's face is delivering dialogue (inserts/
cutaways stay motion-only). **Ryan was about to animate `S-02.104`** (scene 2 medium shot, "Tom says
eagerly: 'Tomorrow I will catch a big fish…'") to confirm grok actually lip-syncs.
- **If lip-sync works:** next refinement = speaking clips often need **longer duration** (long lines
  get cut at 6s; grok supports up to 30s) — set speaking-shot clip length from the line, or split long
  lines. Then animate the scene, then render.
- **If lip-sync is poor:** tune the dialogue prompt format / try `mode` (fun/normal/spicy) or delivery cues.

## Shipped this session (all live on main, on `feat/director-pass`)
Reliability + foundation (overnight + early):
- Killed false-proof signals (broken self-test, lying docstrings).
- **Claude + vision analysis on DIRECT Anthropic** (per-tenant key); Kie only for image/video gen +
  Claude fallback. Fixed the Kie-gateway hang. Stale model ids → `claude-sonnet-4-6`.
- Phase 1 data: model-a-video + onboarding fetch via the YouTube Data API (real views), skip/heal zeros.
- Co-pilot interactive image path unified on coverage.

The live-test build (the bulk — script → storyboard → images → clips, all driven by Ryan testing):
- **Style:** modeled-script writes in the captured voice (dialogue, not narrator).
- **Character lock:** per-scene presence (`scene_aware_bible`/`_scenes_present_for` in coverage_to_app.py)
  → each scene's directive names only the characters in it. **4-view 360 reference sheets** (was single frame).
- **Environment lock:** distinct env extraction (kitchen ≠ garage), location lock sources the approved
  `video_environments` first, "use only these locked locations, never invent" directive.
- **One location per scene:** script segmentation splits a beat that changes location into separate scenes.
- **Coverage parallelized** (~4-5× faster; `COVERAGE_CONCURRENCY=5`, env-tunable). Moments + angles draw
  concurrently, master-first preserved.
- **Per-shot motion prompts (Phase 7):** written at coverage time onto `assets.video_prompt` (the clip
  generator already reads it); **dialogue-aware** (embeds the spoken line on speaking face-shots for grok lip-sync).
- **Co-pilot:** added a `characters` verb (`run_characters`) so "redesign the cast" stops mis-routing to
  script; fixed the paid-action confirm message; clip gate lets a targeted (one-card/one-scene) animate
  bypass the global status gate.
- **UX:** auto-refresh on co-pilot task completion (pipeline page SSE); "Regenerate storyboard" button
  (Scenes page) + "Regenerate script" button (Script tab). Frontend deploys need `npm run build`.

## Deploy + verify cheatsheet
- Push `origin/main` from local → on VPS `cd ~/projects/economy-fastforward && git fetch && git merge
  --ff-only origin/main`. Backend: `kill -9 $(pgrep -f uvicorn | head -1)` (SIGTERM hangs), systemd
  revives; confirm `/api/health` 200. Frontend changes: `cd storyengine/frontend && npm run build` then
  kill the `storyengine-frontend.service` MainPID; it serves on **:3001**.
- DB checks: `export DATABASE_URL=$(tr "\0" "\n" < /proc/$(pgrep -f uvicorn|head -1)/environ | grep
  ^DATABASE_URL= | cut -d= -f2-)`; run `./venv/bin/python` from `storyengine/backend`. No `psql`.
- Authed pages can't be verified via local preview — use tsc + next build / py_compile + DB checks.

## Known refinements queued (not blockers)
- Speaking-clip duration vs line length (above). • Coverage favors inserts on some speaking beats —
  could bias the director toward face shots when a line is spoken. • Branch not yet merged to a PR /
  squashed — it's been deploying straight to main.
