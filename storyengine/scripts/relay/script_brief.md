You answer every script request for ONE video, one at a time, until none are left.

Folder: /Users/ryanayler/AgentVault/Projects/story-engine/storyengine/scripts/relay (run all commands from here).

Loop:
1. Take the current request id (given to you first; later ids are printed by step.sh).
2. Read req/<id>.json with python: system_prompt, prompt, max_tokens.
3. Follow system_prompt and prompt exactly, as written. Add no rules of your own.
   Use no web search: the prompt's BRIEF is the only source.
4. Write ONLY the raw answer in the format the prompt asks (no prose, no code fences) to ans/<id>.json.
   Validate it with python json.load.
5. Run ./step.sh <id>. It posts your answer and prints the next pending request line
   ("<id> <stage> ...") or NONE_PENDING.
6. If a new id is printed, go to step 2 with it. If NONE_PENDING, do NOT run step.sh again
   (it would re-post). Run `python3 mcp.py pending <video_id>` up to 3 times, 30 seconds apart.
   If a new id shows, go to step 2. If not, stop.

Never call any other storyengine tool. Never post an answer any other way.
Final message: one line per request id you answered (id + stage), then "DONE" (or the error).
