# Relay helpers (no-key tenants)

Run from this folder. Big relay prompts and answers go through files, never through chat.

- `python3 mcp.py pending [video_id]` - saves each pending request to `req/<id>.json`, prints id, stage, target.
- `python3 mcp.py answer <request_id> <file>` - posts the file (code fences stripped, must be valid JSON).
- `./post.sh <request_id>` - photo judge answers: checks candidate ids match `req/<id>.json`, then posts `ans/<id>.json`.
- `VIDEO_ID=... ./waitnew.sh` - waits until a pending request appears whose id is not in `dispatched.txt`.
- `judge_brief.md` - brief for a Sonnet subagent judging one photo request ({REQ}/{IMG}/{ANS} paths).

`req/`, `ans/`, `img/`, `dispatched.txt` are scratch - gitignored.

Per-machine research (one Sonnet helper per machine, not per request - each helper costs ~77k tokens to start):
- `./start.sh "<machine>"` - starts `research_machine`, prints the first pending request.
- `./step.sh <request_id>` - posts `ans/<id>.json`, prints the next pending request or NONE_PENDING.
- `./check.sh` - machines whose research verdict is no longer pending.
- `machine_brief.md` - brief for a helper that runs a whole machine (use agent type `relay-researcher`).
- `research_brief.md` - brief for a helper that answers a single request.
