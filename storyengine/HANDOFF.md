# HANDOFF - 2026-07-22 - STS voice-lock shipped; film-grammar rebuild planned

## State
- Prod: bbed20a8 deployed (deploys.log + se health verified), healthy. Local/origin
  main = b071ce0d (one docs-only commit ahead: the film-grammar plan file).
- Branch: main - uncommitted: HANDOFF-adjacent files from the PARALLEL static_docu
  session (tasks/loop-checklist.md, loop-handoff.md, ref-dryrun txt, .claude/) -
  do not touch/commit. Check git log for interleaved static_docu commits.
- What shipped this session (all deployed + live-proven):
  - InfiniteTalk REMOVED (0 prod successes ever; each attempt burned up to 20 min).
    Speaking clips now: Grok performs the line -> ElevenLabs speech-to-speech
    re-voices in pinned cast voice -> carries_own_line + speech bounds persisted
    (migration 114, applied) -> assembler plays the clip's OWN audio, timed by
    measured speech. Proven live on S-01.105 ($0.09).
  - Adversarial review caught 2 critical timeline bugs pre-ship; fixed, repro-proven.
  - StageRail: clickable stage icons on the pipeline page (new REST route
    /production-guide), skipped stages auto-hide; Performance Track panel now
    honest + per-scene "voice-locked N/M" chips.
  - Scene 1 Spanish Class: 28 older clips manually sync-aligned (not carrier-marked,
    chips read 1/29); full re-animate (~$2.60) upgrades all to true voice-lock.
  - Ledger kie_task_id bug fixed (was recording the failed attempt's task id).

## Next action (start here cold)
Implement the film-grammar coverage rebuild. Read
~/economy-fastforward/storyengine/tasks/FILM-GRAMMAR-PLAN.md - design approved by
Ryan, all mapping DONE with file:line evidence (do NOT re-map). Build with Sonnet
subagents + adversarial review, then the dry-run proof: run the planner on Spanish
Class scene 2 (cd5d2883) script text and print the shot list for Ryan before
drawing any frames. Goal: dialogue shot and cut like a movie.

## Open threads
- Camera/film-grammar build - plan file above, not started.
- Spanish Class scenes 2-4: pictures + clips still to generate (Ryan runs from UI;
  clips now go through the new voice path automatically).
- Kie logs recovery trick: dashboard endpoint pageRecordListByDoris (browser
  session auth, pageNum/pageSize) lists tasks the public API can't; task media
  kept 14 days.
- VPS stability: box lost NETWORK twice tonight (not OOM, not a crash - kernel
  logs clean, backend kept running; both deaths within minutes of my bulk media
  transfer bursts; Hostinger null-route suspected, NOT confirmed). Ryan should
  check Hostinger for abuse/DDoS notices. Keep bulk transfers off the box or
  throttled sequential.
- Box-sharing cleanup parked: Hailey cloudflared quick tunnel + TWO n8n installs
  (clawd + ubuntu) + ns-* services live on the StoryEngine VPS; npm ci runs at
  boot; load avg 10 at boot. Ryan said clean up later.
- Carried: billing.py LIMIT-1 x3, SSE home-tenant bug, OAuth wrapper for
  Connectors, agent-token rotation owed, VPS password rotation owed.

## Gotchas learned this session
- The performance assembler MUTES all clips and lays TTS on its own clock - any
  per-clip audio fix is invisible in the stitch unless carries_own_line marks the
  shot (that's what demotion rules protect).
- reboots wipe /tmp on the VPS (se_token, uploaded scripts) - re-scp after.
- ElevenLabs v3 is TTS-only; STS stays on eleven_multilingual_sts_v2
  (env ELEVEN_STS_MODEL to swap when a newer STS family lands).
- The camera-move "rotation" root cause is the continuity boilerplate poisoning
  the purpose classifier ("behind" in set-dressing text -> REVEAL x32) - re-run
  proven; details + fix design in FILM-GRAMMAR-PLAN.md.
- se db blocks writes without --write; se deploy needs a session name.
