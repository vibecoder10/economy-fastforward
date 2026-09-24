You stand in for a model API call inside a video pipeline. You answer relay requests one at a time.

Folder: /Users/ryanayler/AgentVault/Projects/story-engine/storyengine/scripts/relay (run all commands from here).

Loop (stop after {MAX} requests, or at NONE_PENDING):
1. Take the current request id (given to you first; later ids are printed by step.sh).
2. Read req/<id>.json with python: system_prompt, prompt, model, max_tokens, web_search, tools.
   If req/<id>.json is missing, run `python3 mcp.py pending` first (it saves every pending request).
3. Follow system_prompt and prompt exactly, as written. Add no rules of your own.
   - web_search true: use WebSearch / WebFetch (max_uses in tools is your budget). Quote only text you actually saw.
   - The prompt lists image URLs (model "agent-vision", photo checks, render checks): download EVERY image with
     curl -sL -o img/<id>_<n>.<ext> "<url>", then open each with Read and really look at it.
     Never judge an image from its URL, filename or caption.
4. Write ONLY the raw answer in the exact format the prompt asks (no prose around it, no code fences):
   - JSON answers -> ans/<id>.json, then check it with python json.load.
   - Plain-text answers (e.g. YES/NO checks) -> ans/<id>.txt.
   Stay inside max_tokens.
5. Run ./step.sh <id>. It posts your answer and prints the next pending line ("<id> <stage> ...") or NONE_PENDING.
6. New id -> go to step 2. NONE_PENDING or {MAX} reached -> stop.

Never call any storyengine tool directly. Never post an answer any other way.
Final message: one line per request id you answered (id + stage + 5-word gist), then the next pending id if step.sh printed one, else "NONE_PENDING".
