# StoryEngine - operating card

Multi-tenant AI video engine (script -> voice -> images -> clips -> stitched
video). Prod runs on the VPS (`ssh storyengine-vps`), backend port 8001,
frontend port 3001. Goal: first 10 paying customers actually using it.

## Run + verify (the ladder - fastest first)

1. **Local UI, before any deploy:** `scripts/se.sh devtoken` (fresh 30-day
   token into `frontend/.env.local`), then the dev server (launch.json name
   `storyengine`, port 3001). It auto-logs-in as Ryan against the PROD API -
   authed pages render with real data. Walk the changed flow per gate.
2. **Code checks:** backend tests run with the backend venv, NOT system
   python3 (that's 3.9, the suite needs 3.10+ and will refuse with a clear
   error): `cd backend && ./venv/bin/python -m pytest tests/ -q`. Create the
   venv once: `python3.11 -m venv venv && ./venv/bin/pip install -r
   requirements.txt -r requirements-test.txt`. Full-run results match
   per-file runs (tests/conftest.py isolates each file's stubs - keep it).
   Frontend `npx tsc --noEmit` + `npm run build`.
3. **Deploy** (ask Ryan first - live system): push main from the LOCAL Mac,
   then `scripts/se.sh deploy <session-name> [--with-frontend]`. Honors
   ~/deploy.lock; `--force` only on a stale (>2h) lock.
4. **Prove on prod:** one `/se-smoke` pass (deep-link URL map lives in that
   skill). Screenshot proof. UX problems count as failures.

## VPS ops - always through `scripts/se.sh` (docs: /se skill)

`se health` | `se logs [svc] [N]` | `se db "SQL"` (read-only; `--write` to
mutate) | `se deploy` | `se restart [svc]` | `se token [--mint]` |
`se devtoken` | `se run 'cmds'` (batch!). Never hand-roll ssh for these.

## Map

- `backend/main.py` - FastAPI app; routes in `backend/routes/`
- `backend/actions.py` - THE verb registry (20 verbs): prices, gates,
  estimator; chat and buttons both call it. Extend here, never fork it.
- `backend/pipeline_executor.py` - the build pipeline
- `backend/agent_brain.py` - chat tool loop; `backend/routes/chat.py` - producer
- `frontend/src/app/` - pages; `frontend/src/lib/api.ts` - API client
- `schema.sql` + `migrations/` - DB shape; query via `se db`
- Plans/handoffs at this root: GOAL.md, HANDOFF.md (one file, no dated copies)
- Canonical local project: `/Users/ryanayler/AgentVault/Projects/story-engine/`

## No API key? The session is the API (relay mode)

When a workspace has no Anthropic key, run the pipeline through the
`storyengine` MCP exactly as normal. Do not hand-write research or scripts,
and do not use `submit_research`/`submit_script` shortcuts. The pipeline code
runs unchanged; this session only stands in for the Anthropic API.

1. `get_workspace_info` - `agent_llm_relay: true` means the relay is live
   (tenant opted in AND no key; `backend/agent_relay.py::relay_active`).
2. Start the stage with its normal verb (`research`, `script`, ...).
3. Loop: `list_pending_llm_requests(status=pending)` -> answer the prompt
   exactly as the model would (raw output, same format) -> `answer_llm_request`.
   Requests come one at a time; poll again after each answer.
4. Hand each prompt to a Sonnet subagent: give it the `request_id` so it
   fetches the prompt itself, tell it to return ONLY the raw answer and never
   call `answer_llm_request`. The session posts the answer.
5. Vision passes go through the relay too (roster photo checks via
   `gather_roster_images`; `reference_selection.judge_mode` returns "relay"
   when there is no key). The answerer must really LOOK at every image:
   download each candidate `image_url` to the scratchpad with curl and open
   it with Read. Never judge a photo from its URL, filename or caption.

Goal: prove the system runs unattended. When a key is added later, the same
pipeline runs with no change. Media stages (voice, images, clips, render)
are still real spend - quote first.

## Hard rules

- **Money:** anything that triggers paid generation (images, clips, voice)
  gets a cost quote and a yes first - in the UI, local dev included.
- **Never `pkill -f uvicorn`** on the VPS (it has matched voice-osiris and the
  ssh session). Restart by unit MainPID - `se restart` does it right.
- **Env lives in the PARENT `storyengine/.env`** on the VPS, not backend/.env.
- **Never inline multi-line Python over ssh** - scratchpad + scp, or `se db`.
- `channel_videos` is the shared analytics table - extend it, never recreate.
- Deleted on purpose, don't resurrect: /competitors page, the niche wizard,
  legacy pipeline routes (410), Power Doctrine as a default identity.
- Image gen policy: GPT Image 2 first, intelligent nano-banana-2 fallback,
  one shared path.
