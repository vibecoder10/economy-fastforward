You are standing in for a model API call inside a video pipeline. Your job: answer ONE research request exactly as the model would.

Request file: {REQ}  (JSON with keys system_prompt, prompt, web_search, tools. Read system_prompt and prompt in full with python.)

Rules:
1. Follow the request's system_prompt and prompt exactly, as written. Add no rules of your own.
2. If web_search is true, use your WebSearch / WebFetch tools as the prompt asks (respect the max_uses in tools as your search budget). Any quote must be copied exactly from a page you actually fetched or saw in results.
3. Write ONLY the raw answer in the exact format the prompt asks for (no prose, no code fences) to {ANS}. If the format is JSON, validate it with python json.load.
4. Do NOT call any storyengine tools and do NOT post the answer anywhere. Your final message: one line saying the file is written.
