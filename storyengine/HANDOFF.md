# HANDOFF - 2026-07-07 DvsU first-customer build-out: profile encoded, pipeline hardened, beta video mid-flight

## State
- Prod: fb60a3db deployed, healthy (se health green; backend+frontend active)
- Branch: main - uncommitted changes in CAMERA-ENGINE-PLAN.md (another session's, do not touch)
- What shipped this session:
  - All six DvsU tenant prompts hand-written from Anton's 10-doc package, live (tenant 561b872d); profile filled; format locked; package archived to Agent Vault/Projects/storyengine/designed-vs-used/
  - Narrator voice vault wiring fixed (voice/model/style secrets -> env; multilingual-v2 pin; .env defaults restored for others) @ 34f276c3
  - Static-docu image accuracy: pure-white studio, no nano fallback, page-title trust check, output vision gate, 1K resolution, Wikimedia Retry-After + verified-reference cache @ fad2cd3a/19793f7d/ed186ec4
  - Script format enforcement: no spoken citations, per-unit scene re-split @ 1c61773d, research roster -> script contract @ fb60a3db; research never renames a video @ 6bbda52e (title restored)
  - UI: per-video prompt editor shows the channel's real prompt @ d52f0daf; per-scene wand rewrite + always-visible Regenerate script @ 477c80c4
  - Beta video "Every US Strategic Bomber Ever Built" (6398a4e5-6aaa-4e8b-855d-b6c439323c32): research PASS, script restructured offline into 13 machine scenes (one per machine, wand-editable). NOT voiced/imaged/rendered yet.

## Next action (start here cold)
Ryan reviews the 13 machine blocks in the UI (storyengine.dev/pipeline/6398a4e5-6aaa-4e8b-855d-b6c439323c32, operating "Designed vs Used"), wands any machine he dislikes (scenes 11 and 13 run 132/140 words - over the 120 cap), then:
1. Confirm Anton's ElevenLabs key is in the tenant profile (Settings > API Keys while operating DvsU). Verify presence: `se db "SELECT name FROM secrets WHERE name LIKE '561b872d%'"` - need `elevenlabs_api_key`.
2. Generate Voice, then walk images/render/thumbnail gate by gate. Grade each against `Agent Vault/Projects/storyengine/designed-vs-used/` checklists.

## Open threads
- Voice blocked on Anton's elevenlabs_api_key (Kie roster rejects the custom Nathaniel C voice; direct key required).
- Beta video has 13 units, not ~23 - research pre-dates the roster mandate; missing B-47, B-58, XB-70. Fine for pipeline proof, NOT for upload. Real production videos start fresh (research now mandates 24-30 shortlist + unit_roster field).
- Thumbnail gate watch item: research stores a generic winner_thumbnail suggestion; check the fixed series text (EVER BUILT) wins at generation. If not, cut that wire like the title one.
- Word-count drift: script model still writes long (115-140) even under the 95-120 law; wand rewrites enforce it per scene. If it stays chronic, add a code-side trim pass.
- Never uploaded anything to Anton's channel - keep it that way until Ryan/Anton review.
- Background chip pending: fix stale test_prompt_override_wiring.py (task_544dc92e, spawned to separate session).

## Gotchas learned this session
- NEVER deploy while a generation is in flight - se deploy kill -9s the backend and the stage dies mid-run (burned two of Ryan's script rolls).
- The script bot writes ONE scripts row per ACT; static docu needs the post-script re-split (now in run_script) - if scenes==acts, the re-split didn't run.
- tenant_prompt_defaults overrides: research/script system prompts must explicitly force the task JSON/output contract or Claude follows the persona into prose (research parse failure at char 0).
- Kie ElevenLabs gateway silently swaps off-roster voices to "Mark"; custom voices need the direct key path.
- /api/videos/defaults/*-prompt endpoints were tenant-blind (fixed) - if a prompt box ever shows "general educational content channel" on a custom channel, suspect that class of bug.
