You are standing in for a vision model API call inside a video pipeline. Your job: answer ONE photo-judging request exactly as the model would.

Request file: {REQ}  (JSON with keys system_prompt and prompt; read both in full with python, slicing the prompt in chunks if needed - never skip any part).
Scratch dir for images: {IMG}

Rules:
1. Follow the request's system_prompt and prompt exactly. The prompt lists candidates (c1, c2, ...) each with an image_url, caption, title and source evidence.
2. For EVERY candidate: download its image_url with curl (use -L, a browser User-Agent, and --max-time 60) into the scratch dir, shrink it if large (sips -Z 1200 on macOS), then open it with the Read tool and really look at it. Never judge a photo from its URL, filename or caption alone. If a download fails, retry once; if it still fails, judge it as not usable and say the image could not be loaded.
3. Identity evidence quotes must be EXACT substrings of the supplied text in the prompt, with the exact supplied URL. Check this with python before you finish.
4. Exactly one judgment per candidate id, no extras, no duplicates.
5. Write ONLY the raw JSON answer (no prose, no code fences) to {ANS}. Validate it with python json.load and check that every candidate id from the prompt is present exactly once.
6. Do NOT call any storyengine tools and do NOT post the answer anywhere. Your final message: the candidate ids you rated usable + confirmed, one line.
