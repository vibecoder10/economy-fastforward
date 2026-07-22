# HANDOFF - 2026-07-22 - film-grammar deployed; chat identity pool + voice-less dialogue flow shipped; pipeline UI decluttered

## State
- Prod: b340c124 deployed (se health verified: backend+frontend active, api healthy,
  active_tasks 0). Migrations 115 (env props) + 116 (skip_voice_source) live.
  Local main = origin main = b340c124. Four deploys this session:
  osiris-film-grammar (2c66923d), osiris-ui-cleanup (10f4af85),
  osiris-identity-voiceless (e1740bad), osiris-rail-only-nav (b340c124).
- Branch: main - uncommitted: parallel static_docu session files only
  (tasks/loop-checklist.md, loop-handoff.md, storyengine/.claude/, ref-dryrun txt).
- What shipped this session (all deployed + verified):
  - Film-grammar rebuild C1-C9 LIVE: classifier diet, 1-move budget, setup
    scaling + B-CU shared anchors, reaction/insert floors + editor durations,
    prop manifest (115), sheet/pictures parity + legacy-sheet guard, env-matcher
    fix, reactions face their listener. Scene-2 dry-run proof passed Ryan's bar.
  - Chat identity pool Phase 1 LIVE + live-proven: channel_identity_context.py
    brief leads all 3 chat surfaces; reference = topic-only; length from OWN
    median; length_user_set needs a real phrase; clear_reference op + durable
    lesson. MCP verb get_channel_identity_context.
  - Voice-less dialogue flow LIVE: >=0.8 dialogue-share auto-skips voice
    (bidirectional via skip_voice_source, DvsU/static protected, test-pinned);
    ScriptVoiceTab collapses to Script -> Approve; TTS clock auto-builds in
    Animate (voice_over mode still NEEDS it - never delete generation).
  - Pipeline UI decluttered: broken Try-again removed (failure banner kept as
    TaskFailureBanner.tsx), budget-cap card + script-voice selector removed,
    NEXT UP card + numbered tab strip removed -> stage-rail-only nav + new
    Results bubble.
  - Ops: stale repo-root .env on VPS had DEAD Supabase host in DATABASE_URL/
    SUPABASE_URL - fixed (backup .env.bak-2026-07-22), script gen unblocked.

## Next action (start here cold)
Ryan is driving the 1-min test video HIMSELF through the UI: f00ea79a-06bd-407a
(PocoAPoco, Birthday Cake, 3 scenes/26 shots planned, envs NOT approved,
video_length_minutes still 3 - he wants 1; pictures ~$1.10 at 26 shots).
First move: `se db "SELECT status, video_length_minutes FROM videos WHERE
id='f00ea79a-06bd-407a-a467-2f014f184744'"` then support his drive - this is
the film-grammar REAL-FRAMES proof. Judge frames at full res at the picture gate.

## Open threads
- Chat Phase 2 (scoped, not started): true tool-calling producer chat
  (agent_brain + routes/mcp.py registry verbs) + DECLARED per-channel
  performance-vs-narrated format flag in the identity pool (Ryan asked).
- Spanish Class scenes 2-4: REGENERATE storyboard sheets first (legacy sheets
  trip the new panel-count guard -> unanchored composition); ~$2.10/scene at
  48 shots. Ryan runs from UI.
- Budget cap has NO UI surface now (card removed) - settable via copilot chat
  ("cap this video at $15") or MCP budget_cap verb only. Decide a future home.
- Worker-flagged pre-existing bugs (parked): parse_coverage drift + _gen_ref
  task_id_out test failures (both suites' baselines); coverage_to_app CLI
  main() passes 2-tuples to store_scene which unpacks 4 (dev CLI only);
  skills test env missing pytest-asyncio (inflates failure counts).
- PipelineStepper fallback: while production-guide loads, page briefly has no
  tab nav (pre-existing path, now the only nav) - flagged by U5 worker.
- Carried: billing.py LIMIT-1 x3, SSE home-tenant bug, OAuth wrapper for
  Connectors, agent-token + VPS password rotation owed, Hostinger abuse-notice
  check owed, box-sharing cleanup parked.

## Gotchas learned this session
- VPS repo-root .env (~/projects/economy-fastforward/.env) is loaded by
  pipeline init and OVERRIDES the correct storyengine/.env values - it held a
  dead Supabase host for 6+ weeks. Audit it when adding env vars.
- se health's frontend probe reads 000/http 000 during the frontend restart
  window - poll localhost:3001 on the box before diagnosing.
- Deploy guard blocks on active generations (saved a paid run once today);
  for auto-deploy wait for 3 consecutive idle checks 45s apart - a single
  idle check races Ryan's clicks.
- Chat tests use inspect.getsource source-locks on chat_turn/_handle_copilot -
  extracting prompt-assembly into helpers breaks test_c15c/c15d/c21b/c22.
- devtoken = owner tenant; PocoAPoco workspace is UNREACHABLE for UI walks
  (only Slow English + DvsU are owner client channels) - PocoAPoco visual
  checks are Ryan-only.
- voice_over-mode dialogue videos: TTS segments are the render TIMING CLOCK
  (render_perform bails without them). Fold the UI step, never the generation;
  Animate auto-chains it (pipeline_executor ~12613).
