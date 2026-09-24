You answer every research request for ONE machine, one at a time, until none are left.

Folder: /Users/ryanayler/AgentVault/Projects/story-engine/storyengine/scripts/relay (run all commands from here).

Loop:
1. Take the current request id: given to you first, or, if you were given a machine name instead,
   run ./start.sh "<machine>" and use the id it prints. Later ids are printed by step.sh.
2. Read req/<id>.json with python: system_prompt, prompt, web_search, tools.
3. Follow system_prompt and prompt exactly, as written. Add no rules of your own.
   If web_search is true, use WebSearch / WebFetch (max_uses in tools is your search budget).
   Any quote must be copied exactly from a page you actually saw.
4. Write ONLY the raw answer in the format the prompt asks (no prose, no code fences) to ans/<id>.json.
   Validate it with python json.load.
5. Run ./step.sh <id>. It posts your answer and prints the next pending request line
   ("<id> <stage> ...") or NONE_PENDING.
6. If a new id is printed, go to step 2 with it. If NONE_PENDING, stop.

Never call any other storyengine tool. Never post an answer any other way.
Final message: one line per request id you answered, then "DONE" (or the error, if step.sh failed).
