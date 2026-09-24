# Relay helpers (no-key tenants)

Run from this folder. Big relay prompts and answers go through files, never through chat.

- `python3 mcp.py pending [video_id]` - saves each pending request to `req/<id>.json`, prints id, stage, target.
- `python3 mcp.py answer <request_id> <file>` - posts the file (code fences stripped, must be valid JSON).
- `./post.sh <request_id>` - photo judge answers: checks candidate ids match `req/<id>.json`, then posts `ans/<id>.json`.
- `VIDEO_ID=... ./waitnew.sh` - waits until a pending request appears whose id is not in `dispatched.txt`.
- `judge_brief.md` - brief for a Sonnet subagent judging one photo request ({REQ}/{IMG}/{ANS} paths).

`req/`, `ans/`, `img/`, `dispatched.txt` are scratch - gitignored.
