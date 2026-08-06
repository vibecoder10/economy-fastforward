# Lessons Learned

> Review this file at the start of every session. These are hard-won patterns.

## Session 2026-07-26 — Lead with the TLDR, in plain English
- **Every reply opens with one plain sentence saying the outcome, written so a non-technical reader gets it.** Ryan corrected this again on 2026-07-26 — the third recorded time. Progress updates were still opening with technical detail (file paths, function names, field names) before saying what actually happened. Technical detail goes after, and only if it changes what Ryan should do. No jargon where a normal word works. Explain like the reader is smart but not technical.
- **This applies to progress updates mid-task, not just final reports.** A status line like "swapped ShotTile for ShotCard and wired onTap to focusedShotId" tells Ryan nothing. "The board now shows the real shot cards, and clicking one opens it" tells him everything he needs. The pattern lives in the seams of mid-loop status updates that feel like notes-to-self and get written in the vocabulary of the code instead of the vocabulary of the product.

## Session 2026-07-24 (night) — SFX guard: guarding N call sites invites an N+1th; guard the spend, not the doors
- **Guard where the money is spent, not at every door that could lead to it.** The first pass (a3453902) guarded 4 doors that could trigger paid sound generation — the REST route, the `actions.py` verb, `pipeline_executor._enabled_stages`, and `production_guide`'s stage checklist. An independent reviewer found a 5th: `ClaudeOrchestrator` (plus `advance_video`) called `run_sound_prompts`/`run_sound_effects` directly, bypassing all four guarded doors. Four guards missed one caller; the fix (9d83c621) moved the check INTO `run_sound_prompts`/`run_sound_effects` themselves — the one place every caller, present and future, converges before the paid API call fires. When a feature has multiple entry points (chat verb, REST route, MCP tool, background/autonomous caller, cron), enumerate them explicitly before declaring a guard complete, or better, guard the function that spends the money instead of every path that calls it.
- **A dev worktree needs its own `storyengine/.env`, `frontend/.env.local`, and `SESSION_SECRET` — `se devtoken` only writes the SHARED repo's copy.** `scripts/se.sh devtoken` hardcodes `$HOME/economy-fastforward/storyengine/frontend/.env.local` — in a git worktree checkout (e.g. `.claude/worktrees/<name>/`), that token lands in a DIFFERENT directory than the one `npm run dev` reads from. Copy it into the worktree's own `frontend/.env.local` and point `NEXT_PUBLIC_API_URL` at `http://localhost:8001` (not the VPS) so the frontend actually talks to the locally-running backend with your branch's code. The backend also needs `storyengine/.env` (main.py loads `../.env` relative to `backend/`, NOT `backend/.env` — copy `backend/.env`'s DB creds into the parent file) plus a `SESSION_SECRET` line (pull the real value from the VPS: `se.sh run 'grep SESSION_SECRET ~/projects/economy-fastforward/storyengine/.env'`) or every request 401s with "Invalid or expired session" even with a freshly-minted, unexpired dev token.
- **This Mac's network cannot reach the Supabase Postgres pooler that the VPS reaches fine — confirmed at the raw asyncpg level, not just through FastAPI.** `postgresql://postgres.<project>:...@aws-0-us-west-2.pooler.supabase.com:5432/postgres` (the DATABASE_URL that works on the VPS) returned `asyncpg.exceptions.InternalServerError: (ENOTFOUND) tenant/user postgres.<project> not found` on every one of 8+ direct `asyncpg.connect()` attempts from this local Mac — deterministic, not transient, not a credentials/env issue (same URL, same password, `se db` on the VPS runs fine against the identical DATABASE_URL). The project's own `.env.example` DIRECT host (`db.<project>.supabase.co`) doesn't even resolve via DNS from here (`gaierror`). Best guess, not confirmed via Supabase dashboard access (none available this session): Supabase Network Restrictions (IP allowlist) scoped to the VPS's IP, or a Supavisor tenant-routing quirk specific to the AWS ELB node this Mac's ISP/DNS resolves to. Consequence: a local dev backend on this machine reports `/api/health` → `"database": false` and every DB-backed route 500s, even though the backend PROCESS starts cleanly — "servers started" is not the same as "servers can serve real data" when the check is prod DB connectivity. Don't burn more time retrying; this needs a Supabase dashboard check (Network Restrictions page) from someone with access, or running the verification ON the VPS instead of from a local Mac.

## Session 2026-07-16 - Modal close wedge (AnimatePresence unmount)
- **AnimatePresence needs keyed motion elements as its DIRECT children - never a keyless fragment.** ui/modal.tsx wrapped the backdrop + card motion.divs in `<>...</>`; on framer-motion 12.38 + React 19.2 the exit stalls and the nodes NEVER unmount, so an invisible `fixed inset-0 z-50` backdrop keeps eating every click and the app looks frozen. React state closes fine (the body scroll-lock cleanup runs) - only the DOM stays. Two verified fix shapes: separately keyed motion.div siblings directly under AnimatePresence (modal.tsx), or one root motion.div owning the ONLY exit with the card as a non-exiting child (ReadinessCheck, FirstVideoFlow).
- **Three more copies of the broken shape exist, un-fixed:** `components/detail-panel.tsx:31`, `components/storyboard/panel-detail.tsx:74`, `components/nav/bottom-tabs.tsx:72` (mobile More menu). Same latent wedge - apply the same pattern plus a browser walk when touched.
- **The Claude in-app browser pane freezes requestAnimationFrame while the page reports hidden.** Framer animations only progress on rendered frames, so exits look "stuck" between tool calls and enters sit at opacity 0. Force frames (take screenshots) before judging an animation broken, and never poll for unmount inside one javascript_exec call - zero frames tick while it runs. Raw synthetic clicks also get swallowed right after a tab wake; prefer refs from a fresh read_page, or element.click() via JS when the input layer degrades.
- **A dev token can 401 with an unexpired payload** (server secret rotated) - AuthProvider then clears it and you silently land on /login. Re-mint with `se.sh devtoken`, copy `frontend/.env.local` into the worktree, restart the dev server (NEXT_PUBLIC_* is inlined at compile time).

## Session 2026-07-12 — DVsU one-machine research and script-preview gate
- **Do not let the anti-hallucination scaffold become the visible script shape.** The old XB-15 proof was fact-safe but sounded nothing like Anton because it forced four 19-24 word evidence sentences plus a conclusion. The correct DVsU machine contract is schema-v3 Anton evidence slots (`identity_origin`, `scale_specs`, `build_reality`, `service_reality`, `memorable_fact`) feeding one natural 95-120 word paragraph with a `claim_map`, then a paragraph-derived final sentence that does not introduce new facts.
- **A passing preview must carry its own evidence map.** The StoryEngine preview writer now returns `paragraph` plus `claim_map` spans; validation checks each span's evidence IDs, numbers, designations, high-risk terms, and required slot coverage. This catches the real failure mode: a good-sounding paragraph that floats a number or claim away from its source.
- **Target-machine preview must filter loaded cards after compact-store hydration.** The live DB can contain legacy/compact cards for other roster machines. Hydrating the compact store is fine, but the in-memory preview payload must be filtered back to the selected machine before building the story plan, or old cards can leak into proof prompts.
- **A passing research gate is not the same as a passing script gate.** The XB-15 one-machine DVsU research path passed with a verified Tavily source package and four source-addressable evidence beats, but the first script-preview call failed before any narration could be produced because Anthropic returned "credit balance is too low." Treat this as a provider/billing blocker, not a roster or research-quality failure.
- **Single-machine preview endpoints need provider errors humanized too.** The machine script preview route was synchronous and leaked Anthropic's billing failure as a generic 500 through the app. Fix: catch preview exceptions at the route boundary and route them through `humanize_error`; add an Anthropic/Claude out-of-credit pattern beside the existing Kie block mapping.
- **LLM output shape drift is different from hallucination, but it still needs a hard gate.** The first XB-15 script preview returned semantically close `evidence` / top-level beat-key objects instead of the required `sentences` array, producing empty failed previews. Canonicalize known alternate shapes before strict validation, and return a 400 when preview validation fails so the UI does not call it completed.
- **For source-locked narration, "natural synonym" is a hallucination risk.** XB-15 previews kept replacing source wording with phrases like "exceptional range," "deliver performance," and "fell short." The DVsU sentence compiler prompt now tells Claude to copy claim/source words literally first, then delete clutter, and to include the exact locked machine name.
- **Spelled-out numbers are still unsupported numbers.** Claude converted `5000 mi`, `149 feet`, and `197 mph` into "five thousand miles," "one hundred forty-nine feet," and "one hundred ninety-seven miles per hour"; the validator correctly treated those as extra number words. Prompt source-locked writers to copy numerals/units exactly or omit them.
- **Do not run a strict JSON evidence compiler under a long prose-style system prompt.** The saved Anton channel prompt fought the machine story bundle schema and produced empty/alternate shapes. The DVsU evidence-sentence stage now uses a deterministic JSON compiler system prompt; channel style should be layered only after the grounded evidence gate passes.
- **Fetched source text still needs hierarchy.** The DVsU one-machine gatherer now labels raw excerpts with `SOURCE_TIER`; required Anton slots may use Tier 1-3 evidence, but Tier 4 caution/general pages cannot carry a required slot by themselves. This keeps "real web research" from quietly becoming "Wikipedia-shaped research."
- **When StoryEngine work is already deployed by bundle, push from the VPS if local GitHub auth is missing.** The VPS had the exact deployed commits and working GitHub credentials; pushing from there kept GitHub, production, and local history aligned without replaying different commits through the GitHub connector.

## Session 2026-06-12 pt 12 — S1.4's real cause, the cold-proxy race, extraction rects
- **S1.4's invented boy was never prompt drift — our own prompt SUMMONED him.** The card's sentence contains the tail of Tom's line ("Something is wrong."), so sentence-level match_lines made it a SPEAKING card and the native prompt directed Tom to talk on a ground-level bird close-up — Grok walked him into frame to comply, twice, frames verified. The cutaway/motion_guard rules never even apply to speaking cards. Fix: OFF_SCREEN_SPEAKER_RULE on every speaking prompt — Grok judges visibility from the pixels and keeps unseen speakers off-screen (verified live: legs stay at the frame edge for all 6s). Rule: when a generated artifact contains something "invented", first grep what the PROMPT asked for.
- **A clip tap within ~10s of a deploy failed 100% — and it wasn't Kie flaking.** Kie fetches our media-proxy URLs at createTask; right after kill -9 the proxy serves cold-start 502 HTML and Kie answers `{'code': 500, 'msg': 'File type not supported'}` — three INSTANT retries all land in the same cold window. "Transient" failures that correlate with restarts are deterministic races. Backoff (4s/8s) between createTask retries rides it out. Corollary: the no-clip path now logs client class + inputs — it failed twice with ZERO journal output before.
- **The grid generator does not honor uniform grids.** Scene 2's board came back 3-panels-top/2-WIDER-panels-bottom; no rows×cols crop can cut it (that IS the S2.4/S2.5 split), and chunking drift created 12 orphan asset rows (no sentence, no prompt, unrenderable — and their blank shot text read as "cutaway" to the people rule). `detect_panel_rects` reads the actual black separator lines (bands of dark rows, then dark columns per band) — geometry comes from pixels; layout math is only the fallback. Orphan guard: extraction never INSERTs beyond the scene's story slots.
- **"Fewer total flags" comparisons are biased toward fewer, bigger crops.** The first live re-crop "healed" a 5-panel grid into a 1x2 cut because 2 flagged crops beat 6. Normalize per panel and pin the expected count before letting a fallback win.
- **Calibrate detectors on REAL artifacts, then tighten on the false positives.** panel_flags went 5/9 → 15/15 on the bird video's panels: flat-lit walls measure 200-225 (printed gutters are paper-white >240), window reflections pass uniformity but don't run edge-to-edge, foliage speckle qualifies sporadically but never as a contiguous streak, and an alphabet-poster scene proves "has letters" ≠ "has a chip". Bonus: the validator found chips on S2.3/S4.4/S6.12 that nobody had reported.
- **`git add -A` in a months-stale checkout is a secrets incident waiting to happen.** It swept `.env.bak.supabase-api-*` (a DATABASE_URL with password) into a pushed commit on this PUBLIC repo — force-rewritten within minutes, and the creds belonged to a deleted Supabase project, but only luck made it harmless. Stage files explicitly; `.env.bak*` is now gitignored; the stale untracked files (including CONFLICTING migration numbers 048/049) are quarantined in ~/economy-fastforward-stale-artifacts.
- **A completed task holds the per-video task slot for ~30s** (the route clears it after a sleep): a scripted POST right after observing "completed" gets a 409. Call `/api/pipeline/task/{id}/clear` first — same dance the frontend's 409-retry does.

## Session 2026-08-05 (D15-9 recovery)
- **iCloud sync lag can hide a worktree's latest COMMITS.** The orchestrator's first `git log` showed the branch tip missing a commit that materialized minutes later once the bird daemon caught up. Before judging a worktree dead/partial, re-check after a delay and have the worker re-run git log itself; never trust the first snapshot of an iCloud-synced tree.

## Session 2026-06-12 pt 11 — vision drift reverted; provider-chained vision + canary
- **Provider drift can REVERT before you reproduce it — build the canary anyway.** The morning's dead Kie Claude vision (images as /mnt-style file refs, ~272 input tokens) was gone by evening: 12/12 repro calls saw the image correctly (both tiers, URL and base64). A breakage that comes and goes provider-side is precisely what only a synthetic canary catches; "works when I test it" proves nothing about yesterday or tomorrow. `canaries/vision_drift.py`, hourly user-systemd timer, ntfy alert.
- **Kie token accounting, calibrated live (768px canary PNG):** Claude gateway URL-source = 897 input tokens (≈ the true ~786 image tokens + prompt); base64 = 313 (the gateway re-encodes/downscales base64 — token thresholds on base64 are USELESS for ingestion checks); broken state was ~272. Kie Gemini reports honestly: 1109 prompt_tokens with the image, ~60 without — so `prompt_tokens > text_estimate + 150/image` is a reliable per-call ingestion proof on Gemini only.
- **Kie's OpenAI-compatible Gemini endpoints work for vision with the same tenant key**: `https://api.kie.ai/gemini-2.5-flash/v1/chat/completions` (and gemini-2.5-pro), `image_url` blocks accept data: URLs. All product vision now goes through `shared.clients.vision_client.vision_call` (Kie Gemini → Kie Claude → direct Anthropic; downloads images itself — provider-side URL fetching is a second silent-failure class; rejects HTML interstitials by magic bytes).
- **Split vision from generation when only the LOOKING is fragile.** The modeled pack used to attach the thumbnail to the big JSON-generation call (3-attempt dance, silently degrading to blind on drift). Now a cheap vision pass describes the thumbnail and the observation is injected into the pack prompt as text — the tuned Claude generation never carries an image block, and style fidelity survives gateway drift. Pattern: when a multimodal call mixes a fragile capability with a tuned one, split them at the seam.
- **Out of scope but noted:** the legacy YouTube-pipeline vision users (`autopilot/analysis/thumbnail_analyzer.py`, `video_dispatch/verify_output.py`) use the raw Anthropic SDK — they route through Kie only if `ANTHROPIC_BASE_URL` is set in the pipeline env; not migrated to vision_client yet.

## Session 2026-06-12 pt 7 — per-segment voice synthesis
- **Kie TTS flakes transiently ("internal error, please try again later") on individual createTask jobs** — hit twice in ~30 live calls. Any loop dispatching many Kie jobs needs per-item retries (dialogue_voice: 3 attempts, 5s backoff) AND per-item persistence, so a terminal failure resumes instead of re-paying. One try/except around the whole run is a money bug.
- **Casting characters from the same roster as the narrator produces voice collisions.** Tom's cast voice was Mark — the exact narration voice — making his dialogue indistinguishable from the narrator in the turn-taking timeline. Any voice-casting prompt must exclude the narrator's voice from the offered roster (cast_character_voices now does this).
- **When a column feeds an API with an allowlist, store an allowed value.** scripts.voice_id held an off-roster ElevenLabs id (written by the modeled-script INSERT) — every TTS call would burn a wasted createTask on it before the client's fallback kicked in. Bird video now stores Mark's roster id explicitly; the client fallback stays as a safety net, not the routine path.
- **The dev repo has NO .env files** — one-off scripts against prod must load `/home/clawd/projects/economy-fastforward/storyengine/.env` (the prod checkout's). The dev repo only carries .env.example. Frontend builds need `NEXT_PUBLIC_API_URL=https://storyengine.dev npm run build`.
- **toDisplayImageUrl (media proxy) works for `<video src>` too** — drive download URLs in video_clip_url must be rewritten the same way as images or playback silently fails. The proxy allowlist already covers assets.video_clip_url.
- **The dialogue tagger can invent speakers outside the cast** (scene 5 produced "Receptionist") — any consumer of dialogue_segments speakers MUST have a fallback (dialogue_voice uses narrator voice + warning, the 💬 badge just shows the name). Never key a hard lookup on speaker.
- **A column can be SELECTed and still never reach the client.** GET /api/videos/{id} selected story_locked_at but the hand-written VideoDetail(...) constructor never passed it — Pydantic defaulted it to null, so the banner re-offered "Lock the story" on locked videos. When a route builds a response model field-by-field, adding a column to the SELECT is only HALF the wiring; grep the constructor too (or assert response[field] in a test). Same family as "wired but not plugged in."
- **Status strings lag reality — gate on artifacts, not stage names.** The bird video had 86/86 finals at status ready_for_images; both the clip route gate and the banner recovery branch keyed on status alone and locked Ryan out of clips. Pattern: routes gate loosely (earliest status where the artifact CAN exist) and let the executor verify the artifact itself; UI branches check artifact counts (extractionIncomplete) not just status.
- **First page-load after a backend kill -9 shows transient 502s** (nginx hits the half-started uvicorn; 86 media-proxy requests land on cold caches). Don't chase them as bugs — re-run once the process is warm; 0 errors on the warm pass is the truth.
- **`.get(key, default)` does NOT cover present-but-NULL columns.** DB rows come back with every selected column present; `img_record.get(DURATION, 6.0)` returns None for NULL and `None > 6.0` killed the whole video-scripts run in 0.5s (the clips tab's silent auto-run failed twice before anyone saw a traceback). Use `row.get(key) or default` for DB-row reads. Grep candidates: `\.get\([A-Za-z.]+, [^N)]` over bot code.
- **The old clips tab's "Prompts 74/86" counted image_prompt, not video_prompt** — motion-prompt coverage was actually ~20/86 and nobody could tell. When a stat row mislabels its source column, every debugging conclusion built on it is wrong; the rebuilt tab counts video_prompt.
- **Every new tab/surface must use useTaskWatcher, never useTaskPoller** (second occurrence of the pt-3 lesson — the rebuilt clips tab shipped with a caller-armed poller and Ryan immediately hit an invisible task + bare 409). Treat useTaskPoller as legacy; a 'task already running' toast must SAY what is running.

## Session 2026-06-12 pt 10 — wrong face, dead vision, portrait cut-ins
- **Single-subject lip-sync models animate the MOST PROMINENT face on multi-character images.** InfiniteTalk made Tom mouth Lisa's line while Lisa froze; the prompt naming the speaker did nothing, and Kie exposes no multi-person routing (probed bytedance/omni-human: image+audio only). Hand these models ONE subject: the speaker's approved portrait (deterministic, canonical look) — a dialogue cut-in, which is also normal shot grammar.
- **Still frames cannot verify WHICH character is lip-syncing.** I called "Lisa talks" from crops; Ryan watched it move and heard Tom. Multi-face motion claims need the user's eyes (or true video analysis) — or remove the ambiguity at the source (one face in frame makes still verification honest).
- **CLAUDE-VIA-KIE VISION IS CURRENTLY DEAD (provider drift).** Image blocks (URL and base64, both tiers) reach the model as /mnt-style FILE references it cannot see — ~272 input tokens, no image payload; haiku refuses claiming missing tools, sonnet writes a preamble and end_turns. Anything built on Kie Claude vision (thumbnail style-DNA, storyboard QA loop, approve-cast description rewrite, my onset detector — whose 'calibration' was the model guessing blind) is silently degraded. Needs a canary like the validator one. Check `usage.input_tokens` to prove whether an image actually reached a vision model.
- **`_call_claude` read content[0] only — multi-block replies truncated to the first sentence.** Join all text-type blocks. When an LLM reply seems to 'stop early' with stop_reason=end_turn, suspect the extraction, not the model.
- **`cmd | tail -1 && next` swallows cmd's exit code** — a failing test slid straight into a deploy. Pipe for display only when nothing depends on success; otherwise run bare or set -o pipefail.

## Session 2026-06-12 pt 9 — audio-driven beats align-the-audio
- **When lip-sync is off, don't align the audio — generate the mouth FROM the audio.** Two rounds of alignment (fixed offset, then vision onset detection) missed in both directions because Grok times the performance itself. The category-correct tool is an audio-driven talking-video model: Kie's `infinitalk/from-audio` (image + audio ≤15s + prompt → clip whose length = audio length, $0.015/s @480p, ~7 min generation). Verified on a full-scene stylized panel: names the speaker in the prompt → the RIGHT character articulates, others stay quiet, scene/style preserved. Rule: before building alignment heuristics around a generation model, search for a model that takes the ground truth as INPUT.
- **Kie's 422 "model not supported" doesn't enumerate models.** Find exact ids on docs.kie.ai/market/<vendor>/<path> pages (landing pages 403 WebFetch; the docs pages fetch fine). Probing createTask with an empty input is charge-free id validation.
- **A workaround that took a day to build is still a workaround** — the vision-onset detector was calibrated and shipped hours before being retired by the right tool. The sunk build must not bias the architecture choice; implementation preserved in git history (pre-5346b90b) if ever needed.

## Session 2026-06-12 pt 8 — lip-sync alignment
- **Grok times the speech itself — and may spend the clip's first ~2s walking the speaker INTO frame** (S2.1: the panel showed only Tom; the prompt said Lisa speaks, so Grok animated her entrance and her mouth moved at ~1.8-2.0s while the muxed line played at t=0). A fixed audio offset can't fix this; per-clip alignment can: extract timestamped frames (fps=2, 320px JPEGs) → one Haiku-vision call ("first frame where {speaker}'s mouth is open mid-word; entrances don't count; prefer LATER") → adelay the voice to that onset (clip_dialogue.detect_speech_onset). Calibrated on real ground truth: returns 1.5-2.0 for a 1.8-2.0 truth — within the 0.5s frame granularity; audio at-or-just-after mouth-open reads natural, audio-before-mouth reads broken.
- **Vision timestamp questions need per-frame classification + a LATER bias** — the bare "when does she start talking?" came back 1.0s (mid-entrance); asking for per-frame mouth states (not-visible/closed/open-talking) with "running/entering ≠ talking, pick the later frame when torn" moved it to 1.5-2.0. Same FINAL:-line parsing as the grid-style checker.
- **Re-muxing deployed clips is free**: the muxed mp4's video track IS the Grok video — ffmpeg -map 0:v with new delayed audio + upload_bytes to the same path replaces Drive content in place (same file id, DB untouched, md5-ETag busts the proxy cache).

## Session 2026-06-12 pt 4 — dead audio, silent steps, cheap clips
- **A proxy that re-serves Drive PUBLIC links is broken even when it returns 200 with the right Content-Type.** The audio endpoint streamed `uc?export=download` and served an HTML interstitial labeled `audio/mpeg` — `file` on the bytes is the test, not the status code. Every Drive fetch in backend routes must go through the authorized API (`routes/media._download_via_drive_api`); grep for `httpx` + `drive.google.com` when a media element silently doesn't play.
- **Never derive the API base from `window.location` + a port.** `https://storyengine.dev:8001` is unreachable from browsers; the baked `API_URL` from lib/env is the only correct base. The same bug pattern existed in SecureAudioPlayer after it was fixed everywhere else.
- **Ryan's pipeline philosophy: steps that are plumbing, not decisions, run silently.** Extraction now auto-starts on Lock; the visible action remains only as failure recovery. Pattern for future stages: decision → big button; plumbing → auto-run with progress in the banner + recovery branch in getNextAction.
- **Grok Imagine via Kie (validated live)**: `grok-imagine/image-to-video`, duration is a STRING ("6"–"30"), 480p/720p only, no start/end-frame, always adds its own audio, `resultJson` is a JSON string containing `resultUrls`, URLs expire ~24h. $0.048/6s@480p, ~30s generation. Veo 3.1 Fast stays for first/last-frame interpolation shots; Veo Lite ($0.15) is the middle tier.

## Session 2026-06-12 pt 3 — One-button consolidation (Ryan's standing design bar)
- **Ryan's product bar, stated explicitly: ONE primary action per page, Apple-esque, "a grandma could do it."** Every stage page must have exactly one filled CTA (the guided banner); everything else is per-item contextual controls or an ⋯ Advanced menu. New CTAs added anywhere else on the pipeline page are a regression by definition — extend `getNextAction()` instead.
- **Surfaces multiply silently.** The storyboard stage accumulated FOUR "what now" answers (header runner, banner, action bar, tracker-with-CTA) because each feature shipped its own buttons. The activity log showed the cost in production: Ryan clicked a top-level runner that failed with "Lock your story first" — a gate firing as an error because the surface that offered the action didn't know about the gate. Rule: an action button must be gated by the SAME logic that decides the next action, or live behind Advanced.
- **One progress surface needs an always-on watcher, not caller-armed pollers.** The task endpoint is per-video, so a continuously-polling watcher (`useTaskWatcher`) lets the banner show progress/Stop for work started by ANY control. Two traps: terminal statuses persist on the endpoint forever (fire callbacks only on live-observed transitions), and polls already in flight when new work starts can be misread as the new work finishing (epoch counter in markStarted).
- **Client-side stage chaining**: "Start scene over" auto-chains plan→pictures via a ref consumed in the watcher's onComplete. Cancelled tasks read as COMPLETED to pollers — Stop must explicitly clear the chain (window event from StopGenerationButton) or it fires the next paid stage.
- **Headless Playwright vs prod auth**: the mount-time /api/auth/me fetch dies with net::ERR_ABORTED under headless Chromium (any origin); async route-proxying loses the race. Stub /me with an instant route.fulfill (static body from a curl), proxy the rest of /api/** to localhost:8001 — then the whole app works headless.

## Session 2026-06-11 pt 4 — Stale image cache + per-board editing
- **Replace-in-place uploads + `immutable` cache headers = invisible updates.** `GoogleClient.upload_file(check_existing=True)` replaces Drive file CONTENT keeping the same file id; the media proxy served `Cache-Control: max-age=86400, immutable` with `ETag=file_id` — so regenerated boards showed yesterday's pixels for a day while Drive had the new ones ("Drive doesn't match the screen"). Fix: ETag = Drive `md5Checksum` + `no-cache` revalidation (304 while unchanged). Rule: cache keys must change when content changes — either version the URL or checksum the ETag, never both stable.
- **A feature that exists but gives no feedback reads as "doesn't exist."** Drag-drop replace of storyboard grids was already wired — but replacing in place kept the same URL, the `<img>` never refetched, and it looked like nothing happened. After any in-place replace, cache-bust the rendered URL (`?cb=timestamp`) in addition to fixing server caching.
- **Destructive UI verbs must match their blast radius.** "Clear" on a scene deleted grids AND prompts (full redo) — Ryan only ever wanted one picture gone. Per-slot X (`DELETE /storyboards/{scene}/{beat}`) nulls one column, trashes the Drive copy so the folder matches the screen, and the bot's per-beat resume skip means regen only fills the hole. When deleting an out-of-range slot, don't downgrade scene status (guard on `beat <= storyboard_beat_count`).
- **Diagnostic scripts that load the legacy root `.env` first inherit `GOOGLE_DRIVE_FOLDER_ID`=Economy Fastforward and CREATE duplicate title-named video folders** via `get_or_create_folder` (parent-scoped search misses the real folder under Storyengine). Load the backend `.env` first for StoryEngine work — or pass parent ids explicitly in one-off scripts.

## Session 2026-06-11 pt 3 — Drive is a library, never a CDN
- **Google Drive URLs degrade unpredictably into HTML interstitials** (virus-scan/quota pages) — breaking BOTH <img> rendering and Kie image_input ingestion ('file type not supported' = Kie fetched HTML). Even the lh3 CDN form degraded within hours. Architecture rule: Drive = creator-facing organized library only; Supabase Storage public URLs are the serving layer for browsers and APIs. storage.py dual-writes and returns the Supabase URL.
- **Poll budgets must match real task duration**: multi-reference image generation (6-character casts) takes 2-4 minutes; a 120s poll budget turned successful Kie tasks into silent 'returned None' failures. Verify task duration empirically before setting timeouts.
- **The guided-flow primitives**: lib/next-action.ts (decision table → one action) + GuidedNextStep banner (idle/running/failed/celebrate). Every future stage/state must be added to getNextAction or beginners get stranded again.

## Session 2026-06-11 pt 2 — Drive asset-folder unification + image rendering
- **Two upload paths = two Drive trees.** Pipeline bots upload via `pipeline.google` into the TITLE-named folder; storyengine/backend/storage.py uploaded into "StoryEngine Assets/<video-uuid>" — so a video's Drive folder silently missed portraits/grids/persisted images. storage.py now resolves the video title from the DB and uploads into the same title folder (category subfolders). When two modules write "the same" destination, diff their folder-resolution logic explicitly.
- **GoogleClient.get_or_create_folder searches names GLOBALLY** — using it for generic subfolder names ('characters') would collide across videos. Scope folder lookups with a `'<parent>' in parents` query (see storage._get_or_create_child_folder).
- **Drive uc?export=download links don't render in <img> tags** (interstitials, no CORS, rate limits). Drive's image CDN `lh3.googleusercontent.com/d/<id>=w<px>` serves the same public files reliably — frontend `toDisplayImageUrl()` rewrites at render time; stored URLs stay as download links for server-side consumers. Moving Drive files between folders does NOT change file ids, so stored URLs survive reorganization.

## Session 2026-06-11 — Creator Control Run (stop button, characters, storyboard gate)
- **A "stale-state reset" at the WORKER side of an async boundary eats real user commands.** The executor cleared "stale" cancel flags when it armed itself — but a real Stop arriving in the seconds between route-accept and executor-arm-up got consumed as stale, and $1.85 of images generated against an explicit cancel. Rule: consume stale state at the moment the new run is REGISTERED (the chokepoint every path passes through, here `_set_task_status('running')`), never later in the worker. Pair every "clear stale X" with the question: how does a FRESH X arriving concurrently survive?
- **Deferred cleanup must check what it's deleting.** Each task's `finally: sleep(30); _clear_task_status()` wiped the dict entry of whatever task was CURRENT — including a newer run started within the 30s window, leaving the poller blind while money was spent. Guards on deferred deletes: only delete terminal entries.
- **Rate-limiter side effects on control-plane endpoints**: the concurrent-job limiter counted POST /api/pipeline/cancel as a job start — the Stop button was physically unreachable exactly when a job was running (job limit 1). Caught by adversarial review, not tests. When adding middleware that gates "all POSTs under a prefix," audit every endpoint under that prefix for non-job semantics.
- **Live-test the unhappy path with real money in small amounts.** The grid Stop test ($0.075) passed; the images Stop test (cancel at +1s) exposed both races above. Unit tests of the loop contract passed throughout — the races lived in the seams BETWEEN route, registry, and executor, visible only in a real process with real timing.
- **uvicorn graceful drain holds forever on open SSE streams** — the listener closes (so port-based PID lookup finds nothing) while the process lives on for an hour. Restart sequence must look up the MainPID from systemd, not the port, and escalate to SIGKILL after a bounded drain.

## Session 2026-06-10 pt 3 — Replicate, don't adapt (product correction from Ryan)
- **"Model a video" means REPLICATE the reference, not adapt its mechanics to the creator's channel.** V1 injected the channel profile (niche, voice) into the modeling prompt — dropping in a kids' ESL animation produced a macro-econ video with the same title formula. Ryan's intent: the reference IS the brief; output a sibling episode (same topic domain, format, audience, visual style, new adjacent subject). Channel context now deliberately excluded from the pack prompt.
- **Attach the reference thumbnail as a VISION input** — with transcripts bot-blocked, the thumbnail is the only visual ground truth. Claude correctly identified "3D Pixar/Disney CG animation style" from the image, and that style now flows into every image prompt. Kie's gateway supports Anthropic image blocks with `{"type":"url"}` sources.
- **The brief_translator steamrolls style overrides.** Its user-prompt body hardwires documentary structure (PRIMARY FRAMEWORK, act beats) and the number_density validation (19+ stats) forces econ-style content — a "baby bird" video came out as "The Hidden Economics of Compassion." A system-prompt override cannot beat a structural user-prompt body. Modeled videos now branch in `pipeline_executor.run_script` → `_run_modeled_script`: direct generation with script_dna as system prompt, scene structure from the modeled pack, documentary validation skipped (style_replication marker written instead). Pattern: when a bot's USER prompt encodes genre, overriding the SYSTEM prompt is not enough — you need a different path or a genre-neutral body.
- Re-modeling a video must reset prior generated artifacts (script, script_validation, scripts rows, status→idea_logged) or stale wrong-direction content feeds voice/images.

## Session 2026-06-10 — Model A Video feature (Claude, autonomous /goal run)
- **Kie's Claude gateway 500s any non-streaming response that takes >~110s to generate.** A 16k-token research call failed 12/12 times with 'Server exception' after exactly ~110s; the identical call with SDK streaming (`client.messages.stream(...).get_final_message()`) completes fine. Gateway mode in `AnthropicClient` must always stream. Also: Kie's WAF blocks the Anthropic SDK's default User-Agent (403 "Your request was blocked") — override with `default_headers={"User-Agent": ...}`; and dated model ids (claude-sonnet-4-5-20250929) 422 — normalize to undated aliases.
- **psycopg2 needs `register_uuid()`** — `auth.get_tenant_id` returns uuid.UUID and the sync SupabaseAdapter raised "can't adapt type 'UUID'" deep in the research save. asyncpg handles UUID natively; psycopg2 does not.
- **The rate limiter and billing resolved plans differently** — rate_limit read `tenants.plan` ('free' during trial) while billing reads accounts+trial (pro during trial), AND their plan-name sets diverged (creator/studio vs pro/agency), so a trial user got free-tier 15 req/min and the dashboard 429-stormed itself (the 3s task poller alone is 20/min). When two modules resolve the same concept, extract one helper or at least cross-test them.
- **Modeled-video click-path wiring map** (channels that already steer generation): writer_guidance → script brief; image_style_override → image prompt engine; thumbnail_style_override → thumbnail engine (APPEND/REPLACE: prefix); video_motion_system_prompt → clip-prompt bot; video_length_minutes REQUIRED before script gen.
- **Claude calls go through Kie.ai, not direct Anthropic (Ryan: "we use kie ai for any claude calls").** Contract: `POST https://api.kie.ai/claude/v1/messages`, `Authorization: Bearer <kie_ai_api_key>`, Anthropic-shaped body/response (`content[0].text`), models `claude-sonnet-4-5` / `claude-haiku-4-5` (undated aliases). THREE traps, all verified live: (1) `stream` defaults to TRUE — always send `stream: false`; (2) success responses carry NO Content-Type header — use `json.loads(response.text)`; (3) auth/quota failures return HTTP 200 with `{"code":401,"msg":...}` — check for `content` in the body, never HTTP status alone. `routes/model_video.py:_call_claude` is the reference implementation. The rest of the backend (distiller, learn-voice, suggest-titles, pipeline anthropic_client) still hits api.anthropic.com — broken for kie-only tenants; migration is open work.
- **The `_set_task_status` humanize funnel flattens deliberately-friendly errors too.** Any background task that fails with hand-written actionable copy ("Add your Anthropic key in Settings → Keys") gets replaced by the generic fallback because `humanize_error` only passes through *recognized* patterns. Fix shipped: wrap intentional user copy with `error_utils.user_facing(msg)` — the funnel strips the marker and passes the copy verbatim. Use this for every future background task that wants a specific failure message.
- **yt-dlp is bot-blocked on the VPS IP** ("Sign in to confirm you're not a bot"). Don't assume `_extract_video_info` works in production just because the code is exercised — it can return None for *every* video. YouTube oEmbed (`youtube.com/oembed?url=...`) is not bot-gated and needs no key: it reliably gives title/channel/thumbnail as a fallback. Transcripts remain unavailable until cookies/egress are fixed — this silently degrades competitor scraping and voice-learn too.
- **Next.js 16 dev server blocks cross-origin dev resources**: Playwright must visit `http://localhost:<port>`, not `http://127.0.0.1:<port>` — otherwise the page renders an empty body with no JS errors (scripts blocked, only fonts load). Also: backend CORS (`ALLOWED_ORIGINS`) must include the test frontend's port; and `wait_for_load_state("networkidle")` never settles on dashboards that poll — wait for selectors instead.
- **Local E2E recipe for StoryEngine on the VPS** (prod services untouched): source prod `storyengine/.env`, override `DEV_MODE=true DEV_TOKEN=<random> DEV_TENANT_ID=<disposable tenant> ALLOWED_ORIGINS=http://localhost:3002`, run uvicorn on :8002 from the backend dir (it must be CWD or "main" won't import), `NEXT_PUBLIC_API_URL=http://127.0.0.1:8002 npm run dev -- --port 3002`. A disposable tenant needs: tenants row, `channel_profiles` row with `onboarding_completed_at` set (else dashboard bounces to onboarding), localStorage `onboarding_step2_skipped=1`, and `tenant_usage.videos_created` under the plan cap (free = 2/month — a 402 here proved plan enforcement works on the new endpoint). Clean up child rows before deleting the tenant (projects FK has no cascade).
- **`ANTHROPIC_API_URL` env override + a 30-line mock HTTP server = full-chain E2E without an API key.** There is currently NO working Anthropic key on the VPS (root .env key 401s — rotated after the April leak; the SaaS is BYOK). Any test that needs real Claude output must wait for a tenant key. Validate JSON-shaped LLM responses with required-keys checks + one retry instead.
- **`pkill -f "<pattern>"` kills your own compound command** when the pattern appears in the `bash -c` cmdline (exit 144). Find PIDs via `ss -tlnp | grep :<port>` and kill by PID.

## Session 2026-04-19/20 — Osiris overnight ship-while-sleep (Hotfix: ElevenLabs validator)
- **Validate against the endpoint we actually use, not a "hello world" endpoint.** ElevenLabs `/v1/user` was a convenience choice — short and semantically "am I authenticated." But scoped keys break this: a TTS-only key is perfectly valid for our flow and fails the `user_read` check at `/v1/user`. Rule: for every validator, the chosen endpoint must require the *same* or *strictly less* permission than the endpoint the production code path actually hits. This is now a principle-debt item — the Anthropic/OpenAI/Gemini validators hit `/v1/models` but our real calls go to `/v1/messages` / `/v1/chat/completions`; technically a latent version of the same bug.
- **Parse error-body JSON; HTTP status alone loses information.** ElevenLabs 401 has two meaningfully different JSON shapes: `{"status":"invalid_api_key"}` (bad key) vs `{"status":"missing_permissions"}` (good key, wrong scope). Surfacing both lets users self-serve ("regenerate the key with full TTS access") instead of bouncing against a generic error. Generalize: whenever an upstream returns structured JSON errors, read them.
- **Probe-then-fix is the reusable playbook for validator bugs.** (1) Pull the real saved key from vault, (2) call the upstream endpoint directly from the VPS, (3) compare actual status/body shape against what the validator expects, (4) fix the validator to match. Sub-10-minute per-provider cycle. The probe script is generic enough to reuse for any future provider drift — save it.
- **Customer reports are imprecise; verify scope BEFORE shipping broad fixes.** Ryan said "it's happening to both anthropic and eleven labs" — Anthropic was never even in the vault. If I'd preemptively rewritten the Anthropic validator based on the Telegram message alone, I'd have shipped an unverified change for a possibly-unbroken code path. Rule: always probe the specific code paths named in a bug report before assuming multi-system breakage. The customer's lived experience tells you *where to look*, not *what to change*.

## Session 2026-04-19/20 — Osiris overnight ship-while-sleep (Hotfix: Kie.ai validator)
- **"HTTP 200 is success" is a lie for Chinese-API-style SDKs.** Kie.ai returns HTTP 200 on auth failure and embeds the real status in a JSON `code` field. Our validator checked only `resp.status_code` and called a deprecated URL that returned a clean 404 — so a valid key with 4335 credit read as "invalid." Rule: for every new upstream provider added to `vault.test_api_key`, probe the response shape for BOTH success and failure cases during first integration, not after a customer reports the bug.
- **Customer bug reports are highest-signal work.** Ryan saved a key at 02:29:52 UTC, hit "validation failed," sent a Telegram screenshot. Fix was live ~35 min later. The screenshot pointed at the exact form, the route, the tenant — debugging reduced to "curl the probed endpoint from the VPS." Treat inbound customer-path friction as priority-queue-rewriting signal, not a backlog ticket.
- **Stale endpoint URLs are silent-decay bugs; the only real mitigation is a canary.** Code that called `/api/v1/user/balance` worked the day it was written and decayed silently when Kie.ai moved the endpoint. No defensive code inside the validator would catch this — it's a drift problem, not a logic problem. The right mitigation is a synthetic cron that runs `test_api_key` against a known-good key every hour and alerts on regression. Added to the follow-up queue; this pattern generalizes to every external provider we depend on.
- **"Humanization audit" and "validation correctness audit" are orthogonal.** Cycle 15's scan of raw-error substrings would not have caught this bug — the error string the validator returned was perfectly human-readable ("Kie.ai API error: 404"). It was just wrong. Don't conflate "no raw exceptions reach users" with "the validator gives correct verdicts." Two different tests, both needed.

## Session 2026-04-19/20 — Osiris overnight ship-while-sleep (Cycle 15)
- **Schema archaeology = pivot signal.** The Cycle 15 round-trip test hit five cascading setup failures (pytest missing, UUID constraint, NOT NULL tenant_id, FK to tenants, FK to videos, import-graph stubs). That many unrelated-looking failures in a single test is the test screaming "you're solving the wrong problem." The right test here was a passive DB scan of user-visible failed-status rows; it needed zero schema setup because it reads state that already exists. Rule: when a test's SETUP keeps breaking for reasons that have nothing to do with the thing under test, stop patching setup — ask whether the test is the right shape.
- **"Empty-table passes" is the silent-failure mode of every audit.** A scan test that finds "0 leaks" is worthless if the table has 0 rows. Before declaring an audit meaningful, query `SELECT COUNT(*)` on whatever the audit claims to cover. Cycle 15 scanned 87 failed `bot_activity` rows + 1 failed `background_tasks` row — real evidence that the humanization is holding, not just absence-of-data. Make this a mandatory pre-check for any scan-based audit.
- **Cycles compound by unlocking access, not just code.** Cycles 8-11 all had honest-gap lines naming "this would be a stronger test but needs a live backend." Cycle 14 (deploy) unlocked Cycle 15 (the test those gaps asked for). The right move when blocked by access was never "write a weaker test," it was "ship the thing you can prove cleanly and document the remaining gap honestly" — because the access shows up later and closes the gap retroactively. Access is a ship artifact, not a prerequisite.
- **Helper-pattern pin doubles as a regression guard for the scan catalog.** If future-me adds a new raw signature to `RAW_ERROR_PATTERNS` that the humanizer doesn't strip, the scans would still report "0 leaks" (humanizer outputs clean strings for those patterns too) but the pin test catches the gap immediately. Pair every pattern-list-based audit with a helper-pattern pin so the list can't silently outpace the helper.

## Session 2026-04-19/20 — Osiris overnight ship-while-sleep (Cycle 14)
- **"Can't verify locally" is an access problem, not a test problem.** Cycles 8-12 all ended with the same honest gap: PG proxy on :55432 isn't running on this Mac. The fix wasn't writing weaker tests or standing up a local DB — it was Ryan granting SSH to the VPS. The instant I had it, the whole series of gaps collapsed. Lesson: when every ship-log's "honest gap" names the same missing access, the real task is asking for that access, not working around it.
- **Two repo checkouts on the deploy target is a landmine.** The VPS had `~/economy-fastforward` (stale) and `~/projects/economy-fastforward` (service-backed, live). Deploying to the wrong one silently does nothing. Rule: when SSHing into a deploy target for the first time, ALWAYS find the checkout the systemd service file references (`EnvironmentFile=` + `WorkingDirectory=`) and pin work to that path. Don't trust $HOME heuristics.
- **Graceful-shutdown needs a grace period on restart verification.** First `systemctl status` after `restart` reported `deactivating` — uvicorn was still closing keepalive connections. 4 seconds later: `active (running)`. Poll, don't panic. Rule: always give systemd 5-10s after a restart before believing a `deactivating` / `failed` status.
- **Pip dep warnings are usually non-fatal but worth logging.** Cycle 14 hit pydantic 2.9.0 vs supabase libs wanting ≥2.11.7 — warnings, but pip respected requirements.txt pins. Left as-is tonight (prod is working), but now in the todo queue as a future cleanup rather than forgotten.

## Session 2026-04-19/20 — Osiris overnight ship-while-sleep (Cycle 13)
- **Signal-strength surface is a cheap conversion win.** A creator who sees "learned from 5 transcripts" trusts the draft more than one who sees "learned from your top videos" (vague). Confidence at the auto-fill step directly correlates with fewer abandons at the "Generate My Style" button. For every backend signal with meaningful gradations, surface the gradation — not just the binary "worked/didn't."
- **Inline singular/plural branches are 15-second costs that return 100× in polish.** `{count === 1 ? "" : "s"}` in three sites of one string. Skipping even one reads as "1 transcripts" which screams "built by a machine." Always write the plural branch; never think "close enough."

## Session 2026-04-19/20 — Osiris overnight ship-while-sleep (Cycle 12)
- **Reuse helpers across boundary types when the core operation is the same.** `routes.niche._extract_video_info` was written for the competitor-scrape path (public URLs, no auth). It worked without a single change for the user's own channel in Flow B voice-learn because yt-dlp pulls captions from YouTube's public API — OAuth isn't required for transcripts. Rule: before writing a new "extract X from YouTube" function, grep the codebase; the helper probably exists for a different caller.
- **Silent-per-video failure beats strict error propagation for N-element batches.** `_fetch_transcripts_for_videos` runs 5 yt-dlp calls via `asyncio.gather`; if one raises, it'd kill the whole voice-learn. Catching per-item and setting `transcript=None` means 3-of-5 successes still produce a good voice description. Pattern: when the downstream consumer (Claude) handles mixed input fine, the batch orchestrator should swallow per-item failures and annotate, not re-raise.
- **Cap model input at write-time, not just output at read-time.** A 15-minute transcript is ~30k chars; 5 of those would cost real money per `/learn-voice` call with diminishing voice-signal returns past the first 2 minutes. Hard-cap per item (`TRANSCRIPT_CHAR_CAP=2000`) before sending to Claude. Input caps are easier to reason about than output caps — the budget is proved before the API call.
- **Monkeypatching the yt-dlp helper = flake-free tests.** All 4 new Cycle 12 transcript-fetcher tests patch `routes.niche._extract_video_info` with a fake that returns controlled shapes. Zero network, zero rate-limit risk, zero caption-format drift. The separate concern ("does yt-dlp still work against YouTube today?") is deliberately NOT mixed into unit tests — that's a live-contract test queued as its own thing.

## Session 2026-04-19/20 — Osiris overnight ship-while-sleep (Cycle 11)
- **Four leak surfaces, one helper, zero API growth.** Cycles 8-11 collectively plugged (1) HTTPException, (2) `_set_task_status` background-task state, (3) `_log_activity` activity feed, (4) `OrchestratorResult.error`. Across all four, `humanize_error(err, context=..., fallback=...)` didn't grow a single parameter. Evidence that getting the helper interface right up-front pays for itself 4× over. Rule: when a helper is pure string-in/string-out, side-effect-free except logging, it travels freely across sync/async, response/dict/DB-write boundaries.
- **Honest-gap sections as a todo queue — converges.** Cycle 8 expected 2-3 leak surfaces; ended with 4. Each cycle's honest-gap section named exactly one next surface, shrinking as the audit completed. This is the compounding effect of writing what you DIDN'T fix: next-cycle-you has a precise, pre-ranked todo list.
- **Small-fix cycles still deserve the full ceremony.** Cycle 11 was a 2-line code change. Still wrote a ship-log entry, still committed with a clear message, still updated todo.md + lessons.md. The contract with Ryan is "every cycle documented" — ceremony is cheap once the muscle memory exists, and future-you (or the next agent) needs the trail.

## Session 2026-04-19/20 — Osiris overnight ship-while-sleep (Cycle 10)
- **Leak surfaces discover each other.** Cycle 8 fixed HTTPException leaks; Cycle 9's honest-gap section named the background-task path; auditing that this cycle uncovered `pipeline_executor._log_activity` (writes to `bot_activity.message`, read by `/api/activity`) as a THIRD independent leak surface. The honest-gap section IS the todo list. Always write it; audit it next cycle.
- **"Humanize at the funnel" works across multiple funnel types.** HTTPException (outgoing-response funnel), `_set_task_status` (in-memory-dict + DB-write funnel), `_log_activity` (DB-write-read-at-/api/activity funnel). Same one-liner pattern works because `humanize_error` is pure: raw-in, safe-out, side-effect-free except for WARN-level logging. Design helpers to be funnel-friendly — pure, string-in/string-out, no async, no DB.
- **Static-grep tests are cheap regression guards for write-boundary fixes.** For `_log_activity`, a test that just asserts `humanize_error(message)` appears in `pipeline_executor.py` is enough. If a future refactor deletes the guard, the test fails immediately. Costs one grep, buys permanent protection. Same pattern as Cycle 8's static audit.
- **Chat-UI JSON fields (`reasoning`, `error`, `message`) are user-facing too.** Easy to miss because they're not in `HTTPException` or `bot_activity` — they're just a `return {}` dict. Audit rule: grep for `return {[^}]*e[^}]*}` in route files and inspect any field whose value is `str(e)` or `f"...{e}..."`.

## Session 2026-04-19 — Osiris overnight ship-while-sleep (Cycle 9)
- **Write-boundary humanization beats per-call-site fixes when there's a funnel.** Cycle 8 fixed 11 individual `HTTPException(detail=str(e))` sites; Cycle 9 got wider coverage (~15 `_set_task_status` callers) by humanizing inside `_set_task_status` itself. Rule: find the narrowest point in the error-routing funnel and humanize there. Per-site fixes are fine only when there's no funnel to target.
- **A well-designed helper travels across leak surfaces.** `humanize_error(err, context=..., fallback=...)` was written for the sync HTTPException path in Cycle 8. It worked as-is for the async `_set_task_status` + `bot_activity` insert paths in Cycle 9 with zero changes. Keep the interface tight (raw-in, friendly-out, log-always) and widen usage before adding parameters.
- **Module stubbing for isolated runtime tests is cheap and underused.** Want to exercise one module's behavior without bringing up the whole backend? `sys.modules["auth"] = types.SimpleNamespace(get_tenant_id=lambda: "t")` + `types.ModuleType("database")` with fake async fetchers = 10 lines, no DB pool needed. Same pattern the prompt-override wiring test uses. Adopt for every functional test that wants to poke a single module.

## Session 2026-04-19 — Osiris overnight ship-while-sleep (Cycle 8)
- **`context=` param beats pattern-matching alone for backend errors.** Frontend humanizer pattern-matches from the outside because the fetch wrapper doesn't know *what* was being attempted. Backend call sites know exactly what the user was doing ("generate a character image"). A `humanize_error(e, context="We couldn't X")` call produces a real verb-in-context sentence that reads as "We couldn't generate your character image. Please try again." — better than any regex could reverse-engineer.
- **The copy pattern is `We couldn't <verb> <object>. Please try again.`** — always second-person, always tied to what the user was trying to do, never mentions the technology that failed. Users don't care that it was Kie.ai or Gemini; they care that their character image didn't generate.
- **Logging discipline matters more than the copy.** The user never sees the raw exception — but *devs need to find it in 30 seconds* when a ticket comes in. A fixed log prefix (`[humanize_error]`) is a grep handle. Always include it when writing humanization helpers.
- **Static audit test = ship gate for "no raw errors leaked."** Without a regex scan over HTTPException calls in customer-facing routes, the next new route someone adds will silently regress. With the audit: the test fails, the new site gets wrapped, the cycle stays green. Same pattern as the consumer-wiring audit in Cycle 7 — audits-as-dashboards works for negative assertions too.
- **Background-task error paths are a separate leak surface.** `_set_task_status(video_id, "failed", str(e), ...)` writes raw `str(e)` into a DB row that the UI polls via `/task-status`. This is a totally different attack surface from synchronous HTTPException — and fixing one doesn't fix the other. Audit both, or audit at the read boundary instead.

## Session 2026-04-19 — Osiris overnight ship-while-sleep (Cycle 7)
- **Audit test as dashboard: pays off on every fix.** Between Cycle 6 and Cycle 7, `test_prompt_override_wiring.py` went from "1/6 WIRED" → "6/6 WIRED" by running it after each bot, reading the diff, and moving on. Having a single command that prints the current state turned a sprawling cross-module refactor into a linear checklist. The audit was the project plan.
- **Intentionally-wrong CONSUMER_SPEC is productive.** My first spec pointed at `skills/video-pipeline/research/run.py` — which doesn't exist. The failure forced me to learn the research agent is wired at the SaaS executor boundary, not as a `run.py`-style bot. A spec that's 70% right and documents intent is more useful than one that's 100% right and documents exact paths (paths rot; intent doesn't).
- **Broadening grep regex is cheap future-proofing.** Matching both `pipeline.<attr>` AND `self._pipeline.<attr>` means new consumers in either style satisfy the audit without special-casing. Always write the audit check to accept the full set of reasonable consumer shapes; narrow it later if false positives emerge.
- **Blended override semantics is the right v1.** Setting the tenant override as Claude's `system_prompt` while leaving the task-specific user-prompt body alone is 80% of the value with 20% of the risk. Full-replacement (strip profile preamble from user body) can land later once we measure how much output actually varies. Ship the plumbing first, tune the semantics once we have real A/B data.

## Session 2026-04-19 — Osiris overnight ship-while-sleep (Cycle 6)
- **Claims from prior audits are hypotheses, not facts.** Cycle 1 reported "prompt-override wiring in 7 places." Cycle 6 tested and found **1 of 6 bots** actually reading its attribute. If the claim spans many files and nobody's exercised the code path end-to-end, it should be assumed unverified until an audit test proves it. Write the test before trusting the summary.
- **"Wired but not plugged in" is a real failure mode.** The LOAD path (DB rows → pipeline attributes) can be fully tested and green while the CONSUME path (bots reading the attribute → LLM system_prompt) is missing entirely. Scanning consumer source files with a static audit test (`getattr(pipeline, "<attr>", ...)` regex) catches this. Without it, the feature passes review, ships, and silently does nothing in production.
- **One-shot audit test = progress tracker.** `test_audit_bot_consumer_wiring` prints WIRED/UNWIRED per bot and asserts a floor (`video_motion` + `script` can't regress). As each bot gets wired, tighten the assertion. One file is both a regression guard AND a dashboard.
- **Pragmatic override semantics: blended, not replaced (first cut).** When a tenant override is attached, it lands as Claude's `system_prompt` while the existing profile-derived voice preamble still lives in the user-prompt body. So Claude blends the two. Not a full replacement, but meaningfully different from "override silently dropped." Clean-replacement comes later once we measure output variation.

## Session 2026-04-19 — Osiris overnight ship-while-sleep (Cycle 5)
- **Onboarding step-order is product, not UI.** Original sequence put `style` before `youtube` — hostile to existing-channel users because the voice-learning data arrived AFTER they'd typed their style manually. Swapping the two steps (`channel → keys → youtube → style → video`) unlocked the whole voice-learn slice. Always check: does the data this step needs arrive BEFORE this step?
- **Anthropic LIVE-401 contract test:** `POST https://api.anthropic.com/v1/messages` with junk key + real body shape → expect 401 (auth fail). NOT 400 (bad shape) and NOT 404 (wrong URL). Three lines of code, cheap to run on every push, catches header/body drift instantly. Same pattern as the YouTube-403 test in cycle 4. Apply this to every external API we integrate.
- **v1 opinionated API > configurable API.** The `/learn-voice` endpoint takes zero body params: it just learns from top 5 by views. If we need control later (pick videos, pick by recency) add a body. For an onboarding flow, zero choices beats "set your preferences" friction.
- **Persist the learned artifact on the backend, pre-fill the frontend from its own state.** The voice-learn endpoint writes `channel_profiles.style_description` AND returns the string. Frontend pre-fills local state from the API response (not a reload). That way: server always has the truth, client doesn't need to re-fetch, and if the user edits before generating, the Style step's `generateSystemPrompts` call picks up the edits.

## Session 2026-04-19 — Osiris overnight ship-while-sleep (Cycle 4)
- **YouTube "list a channel's own videos" canonical pattern:** `channels?part=contentDetails&mine=true` → extract `contentDetails.relatedPlaylists.uploads` → `playlistItems?part=contentDetails&playlistId=<uploads>` → extract videoIds → `videos?part=snippet,statistics&id=<ids>`. Do NOT use `search?forMine=true` (flaky for some channels, returns search snippets not canonical video data). The uploads-playlist approach is what Google's docs recommend for programmatic access.
- **YouTube /videos endpoint caps at 50 IDs per call.** If you have more than 50, batch. Our `_fetch_video_details` does this; test `test_fetch_video_details_batches_over_50` validates it.
- **Live API contract test pattern (no auth required):** send a well-formed request to the external API with NO auth, expect 401 or 403. That confirms the URL + params are shaped correctly — YouTube would return 400 if the shape were wrong. This gives you free live contract validation without burning quota.

## Session 2026-04-19 — Osiris overnight ship-while-sleep (Cycle 3)
- **`humanizeError()` already existed at `frontend/src/lib/errors.ts`** but wasn't wired everywhere. Grep for `err instanceof Error ? err.message` and `err.message ||` to find all leak sites. Current product had 11 raw-error sites that would have shown users "API error 500: …" or "Failed to fetch". All now route through `humanizeError(err, contextual_fallback)`.
- **When a catch block needs substring checks** (e.g. "expired token" → specific copy), keep the `raw = err instanceof Error ? err.message : ""` for the check, then fall through to `humanizeError(err, fallback)` for the default branch. Don't discard the `err` object — humanizeError inspects its shape.

## Session 2026-04-19 — Osiris overnight ship-while-sleep (Cycle 2)
- **Functional DB tests via Supabase MCP work great** when the local dev stack isn't up. Pattern: insert-sentinel-row → run target SQL → assert state → cleanup. Gives real-infra coverage without standing up a local PG. Example: `backend/tests/functional/test_trial_expired.sql`.
- **Backend venv is at `storyengine/backend/.venv/`** — plain `python3` from the shell does NOT see asyncpg/etc. Always use `.venv/bin/python3` for any script that touches DB.
- **Local DB connection is via PG proxy on `127.0.0.1:55432`** (not Supabase direct). Running backend scripts locally without the proxy up = "Connect call failed". For functional tests that exercise the Python ORM layer, either start the proxy or use Supabase MCP for the SQL-level verification.
- **The pre-push hook (`.githooks/pre-push`) hard-blocks if ≥3 files changed and tasks/lessons.md + tasks/todo.md aren't updated in the SAME last commit.** Plan for this up front — either include them in the feature commit or make a second "session notes" commit before pushing.
- **fix-roadmap.md is stale** (dated 2026-04-10, ~10 days behind). YouTube OAuth (6.3), system-prompts/generate (6.6 part 2), and pipeline prompt-override wiring (6.6 part 1) are already shipped. Don't trust the doc — grep the code first.

## Session 2026-04-14 — Backend Dev
- Frontend `.env.local` sets `NEXT_PUBLIC_API_URL=https://storyengine.dev` — reported 404s may be from remote server not matching local dev. Always check `.env.local` when debugging "route not found" in the browser.
- When user reports transient 404s, check: (1) server restart? (2) `.env.local` pointing to different server? (3) stale browser cache? Don't assume code bugs.

## Patterns & Anti-Patterns

### Airtable
- **NEVER** join tables by string matching if you can use record IDs. The current schema uses `Title` = `Video Title` string joins. This is fragile. Don't make it worse.
- **ALWAYS** update ALL relevant status fields on the Images table (`Status`, `Video Status`, `Animation Status`). Missing one causes records to get stuck.
- Thumbnail attachment format is inconsistent. The code tries 3 fallback formats. If adding new attachment fields, use `[{"url": "..."}]` format consistently.
- **Graceful error handling can be TOO graceful.** The `update_idea_fields()` function silently drops unknown fields to avoid breaking writes. This means if a field doesn't exist in Airtable, the write "succeeds" but nothing is saved. ALWAYS verify critical writes by checking if the field appears in the returned record.
- **Schema documentation ≠ actual Airtable fields.** A field listed in `docs/airtable-schema.md` might not actually exist in Airtable. When adding code that writes to a new field, verify the field exists in Airtable FIRST.
- **REQUIRED before scripting**: `Video Length (min)` and `Script` fields must exist in Idea Concepts table. Without them, script generation fails silently or produces wrong word counts.

### Pipeline
- **Pipeline status validation can be relaxed for parallel execution.** Thumbnail and video-scripts endpoints were gated too late (required their own stage). Relaxing to earlier stages (ready_for_images, ready_for_sound_design) allows running stages in parallel without requiring strict linear progression. The status check prevents running on truly incomplete data while allowing flexibility.
- **Don't name files `email.py` in Python projects.** It shadows the stdlib `email` package. Use `email_service.py` instead. Linter will catch it but save yourself the trouble.
- **NEVER** skip a status in the pipeline flow. Each status gates the next stage's data.
- **ALWAYS** test changes on a single Airtable record before running against the full queue.
- The pipeline runs on cron (8 AM Pacific). Code pushed to `main` auto-deploys via `git pull --ff-only`. Don't push broken code.
- Whisper transcription is imperfect. The audio alignment system has 3 fallback strategies for a reason. Don't remove fallbacks thinking they're dead code.
- **Storyboard prompts REQUIRE image prompts first.** Without per-segment image prompts, beat prompts lack visual specificity and produce overlapping/repetitive grids. The guard in `storyboard/run.py` blocks generation if <50% have prompts.
- **VPS deploy timing is critical.** `next start` loads the build manifest at startup. If the server starts BEFORE `npm run build` finishes, it loads stale chunks → 404/500 errors. Always: build first → kill server → start server. Never chain them in one SSH command.
- **Storyboard skip check was broken.** `run_images.py` used to check only the FIRST scene's status field. If Scene 1 had grids, it skipped ALL scenes — even ones with missing beats. Fixed to check every beat across every scene.
- **SupabaseAdapter method names differ from AirtableClient.** Always `grep` the adapter for the exact method name before using it. E.g., `get_all_images_for_video()` not `get_images_by_title()`.

### API Costs
- Image generation: $0.025/image, 120 per video = $3.00
- Video clips: $0.30/clip, 20-40 per video = $6-12
- A careless loop without guards can burn $50+ in minutes
- Always add `--dry-run` support when building new bot stages

### Remotion
- Scene.tsx is ~450 lines and handles audio sync, karaoke, Ken Burns, crossfades. Be surgical.
- The 4GB swap file is required on the 8GB VPS. Without it, rendering OOMs silently.
- `segmentData.ts` is generated and gitignored. Don't try to commit it.
- **Captions use character-based chunking, not word-count.** At 72px Inter Bold, the 92% width container fits ~38 chars. Chunking by 6 words caused overflow when words were long (e.g., "manufacturing—Bangladesh"). The fix: CaptionsOverlay.tsx chunks by total character count, creating adaptive chunks (short words → more per chunk, long words → fewer). This guarantees no overflow regardless of sentence content.

### Auth & Multi-Tenancy
- **EVERY UPDATE/DELETE WHERE clause must include `AND tenant_id`.** Even when a SELECT above verifies ownership, the UPDATE itself needs it as defense-in-depth (prevents TOCTOU races). Grep for `UPDATE.*WHERE id = \$` to find missing ones. Files to audit: routes/*.py.
- **Backend loads .env from `storyengine/.env`** (not `storyengine/backend/.env`). The `main.py` line `load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))` goes up one level. Always set env vars in `storyengine/.env`.
- **DEV_TENANT_ID must match a real tenant with data.** If you migrate data between tenants, update DEV_TENANT_ID or agents see 0 results.
- **asyncpg needs UUID objects, not strings.** `get_tenant_id()` returns `uuid.UUID` — if it returns a string, `WHERE tenant_id = $1` silently returns 0 rows (no error, just empty).
- **Supabase circuit breaker**: Too many failed auth attempts (wrong password in DATABASE_URL) triggers "Circuit breaker open" for 5-10 min. Stop restarting — each restart adds more failed attempts. Wait for cooldown, then restart ONCE.
- **Connection pooler (port 6543) doesn't support parameterized queries.** Use direct connection (port 5432) for asyncpg. The pooler uses PgBouncer in transaction mode.
- **Use `min_size=0` for asyncpg pools.** `min_size=2` creates connections on startup — if DB is down, the whole backend crashes. Lazy pool (`min_size=0`) connects on first query.
- **URL-encode special chars in DATABASE_URL passwords.** `@` → `%40`, `!` → `%21`.

### Infrastructure
- The Slack bot process dies occasionally. Healthcheck restarts it every 15 min.
- All VPS logs go to `/tmp/pipeline-*.log`. Reference these when debugging production.
- `cleanup_whisper.sh` removed local PyTorch/Whisper (saved 2GB). We use the Whisper API now. Don't re-add `openai-whisper` to requirements.txt.
- **Next.js stale chunks (deploy race condition)**: Next.js loads chunk manifest into memory at startup. If you build while the old server runs, the old server serves HTML referencing old chunk hashes that no longer exist → 500 errors. Fix: SIGTERM → wait 5s → SIGKILL → `fuser -k 3001/tcp` → verify port free → THEN build → THEN start. The `sleep 2` after `pkill` is NOT enough — use the full shutdown sequence in `storyengine_deploy.sh`.
- **Multiple VPS server processes**: Always check `pgrep -af "next-server"` and `pgrep -af "uvicorn"` after deploys. Kill zombie processes. Two servers on the same port = unpredictable behavior.
- **Backend must be restarted for Python changes**: Unlike the frontend auto-deploy, the backend uvicorn process doesn't auto-restart on code changes. After `git pull`, manually restart: `kill PID; cd backend && nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 > /tmp/storyengine-backend.log 2>&1 &`

### Visual Profiles & Sequencing
- **Two separate visual systems exist**: The holographic sequencer (`image_prompt_engine/sequencer.py`) and profile-based substyles (`visual_profiles/*.py`) are completely independent. When adding a new profile, you must wire it into the pipeline — the profile file alone does nothing.
- **`assign_styles()` is holographic-only.** It returns `display_format` values like `war_table`, `wall_display`, `floating`. For non-holographic profiles, use `assign_profile_styles()` which reads substyles from the profile.
- **`build_prompt()` has two paths**: holographic (framing + content + mood + suffix) and profile (prefix + content + substyle suffix + global suffix). The `display_format` parameter carries the substyle key (e.g., `power_move`) for profiles — make sure it matches a key in `profile.style_system.substyles`.
- **Shot Type field in Airtable** gets written from `display_format`/`composition` in the pipeline. When mannequin_storytelling is active, values should be `power_move`, `lone_figure`, `environment`, `data_hud`, `object_closeup` — NOT holographic types.
- **Profile detection pattern**: `load_profile()` reads `VISUAL_PROFILE` env var (set by `_load_idea()` from Airtable's `Visual Style` field). Check `profile.profile_id != "holographic_hud"` to branch.

### Filtering & Partial Generation
- **`image_filter` vs `scene_filter`**: Both are set on the `VideoPipeline` instance. `scene_filter` filters which scenes to process; `image_filter` filters which image/concept index within a scene. Both must be explicitly checked — they are NOT automatically applied.
- **`_filter_by_scene()` exists but isn't universal.** It correctly handles both filters for _existing_ Airtable records (images bot uses it). But `run_styled_image_prompts()` generates new records from scratch — it doesn't have existing records to filter, so you must filter the `concepts` list directly by `concept_index`.
- **When adding filtering to any pipeline function**: Check both `scene_filter` AND `image_filter`. The pattern of only checking `scene_filter` and forgetting `image_filter` has happened before and will happen again.
- **Concept index = image index within a scene.** The `concept_index` field on expanded concepts corresponds to `image_filter`. The `Image Index` field in Airtable corresponds to `image_filter` for existing records.
- **Resume logic must be aware of targeted vs full runs.** The scene-skip logic (`if scene_num in existing_scenes: continue`) blocks targeted regeneration. For targeted runs (`image_filter` set), only skip if the SPECIFIC image index already exists — not if the scene has ANY images.
- **Audio sync should only run on full generation.** It divides scene audio across ALL images in that scene. Running it after generating 1 image assigns the entire scene duration to that single image (e.g., 108 seconds). Skip audio sync for targeted runs (`_is_targeted_run`).

### Wiring Audit Failures (Recurring Pattern)
- **Building a module ≠ wiring it in.** The mannequin_storytelling profile was a complete, beautiful 793-line file with substyles, composition affinity, Ken Burns mapping, character archetypes — and it was completely ignored by the pipeline because nobody wired the sequencer to use it.
- **The sequencer is the chokepoint.** All image prompt generation flows through `assign_styles()` → `build_prompt()`. If the sequencer doesn't know about your profile, your profile is dead code.
- **Always trace the full call chain**: Slack command → `pipeline_control.py` → `run_*.py` script → `pipeline.py` method → bot/engine. A break at any point means the feature doesn't work.
- **"Already working" claims need REAL verification.** Reading code that SHOULD work is not proof it DOES work. Add debug print statements, run the actual code, check Airtable. The `update_idea_fields()` graceful degradation silently drops unknown fields — a "successful" write might have dropped your field entirely.

### Script Validation (Blocking Flow)
- **Validation is now BLOCKING.** Scripts must pass all 7 checks before advancing to "Ready For Voice". This is enforced in `BriefTranslator.translate()`.
- **7 validation checks**: number_density, framework_density, personal_stakes, actionable_close, cliffhanger_presence, promise_payoff, act_coherence.
- **Senior editor gets ONE pass.** If validation fails → senior_editor() fixes → re-validate. If still failing → pipeline BLOCKED, status set to "Needs Script Review", Slack notification sent.
- **Promise-payoff tracking**: Forward references like "what Part 3 reveals" must have matching content in the referenced act. Use `_extract_promises()` and `_check_promise_payoff()`.
- **Act coherence**: Each act should have max 6 distinct topic shifts (threshold raised from 3 for geopolitics content). Topic drift is detected by tracking proper nouns and domain terms across paragraphs, with geopolitical clustering (Iran/Iranian/Tehran/Hormuz = 1 topic cluster).
- **To force advance a blocked script**: Use `!approve <title>` command in Slack (requires manual review first).
- **Scripts must ALWAYS be saved before validation.** Progressive writes: save to Airtable AND Google Drive immediately after generation, BEFORE running validation. If validation blocks or crashes, the script is still accessible for review. Never lose generated content.
- **act_coherence threshold must account for geopolitics.** Multiple countries/leaders per act is normal in geopolitics content, not topic drift. Related terms (Iran, Iranian, Tehran, Persian Gulf) are normalized to a single cluster before drift detection.
- **act_coherence is ADVISORY, not blocking.** As of 2026-03-14, act_coherence failures show as WARN in validation summary but don't block the pipeline. Geopolitics scripts naturally reference many entities per act; the senior editor can't reliably fix topic drift without restructuring entire acts. The warning is still logged for manual review.
- **New validator checks need matching config flags.** When adding a new check to `validate_script_editorial()`, add a corresponding `*_check: bool = True` flag to `ScriptValidationConfig` or the "disable all checks" test will fail. Test fixtures must also be updated — cliffhangers in `_make_good_script()` must use keywords that actually appear in subsequent acts.
- **System prompt ordering matters.** Voice/tone rules (like `_CINEMATIC_VOICE_RULES`) must come EARLY in the assembled system prompt — right after role identity, BEFORE structural rules. Claude prioritizes early instructions; rules appended at the end get deprioritized. Assembly order: (1) Role identity/preamble, (2) Voice/style rules, (3) Research brief, (4) Structural rules, (5) Act-specific rules, (6) Grounding rules.

### StoryEngine Frontend
- **mission-sync overwrites task-queue.json.** The mission-sync process resets task statuses. Always re-read task-queue.json from disk before editing — never trust the injected context. If tasks were committed as done but show pending, check git log before re-doing work.
- **401 on /api/auth/me is expected during token refresh.** Users with stale JWTs get 401 when AuthProvider calls getMe(). The catch block clears the token. Don't report this as a bug — skip error reporting for 401s on /api/auth/ paths.
- **Spinner component is lowercase**: Import from `@/components/ui/spinner` (not `Spinner`). File is `spinner.tsx`.
- **`as const` on plan arrays breaks optional properties**: If only one plan object has `popular: true`, TypeScript narrows the tuple type and the property doesn't exist on other entries. Remove `as const` or add `popular?: boolean` to all entries.
- **Concurrent agent stash conflicts break imports**: When `git stash pop` restores changes from another agent, it may update imports (removing old, adding new) but NOT the body code that still references the old types. Always run `tsc --noEmit` after stash pop. The competitors page had imports updated to `NicheVideo` but the body still used `CompetitorCandidate` — would've been a runtime crash.
- **Linter removes unused imports between edits.** When adding imports + usage in separate Edit calls, the linter runs between them and strips the new import. Fix: add the import AND its usage in a single edit, or accept the linter will strip it and re-add after usage is in place.

### Supabase Storage
- **Kie.ai tempfile URLs (tempfile.aiquickdraw.com) expire.** Grid and image URLs must be re-uploaded to Supabase Storage immediately after generation. Use `storage.upload_from_url()` for download-and-persist. Public URL format: `{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}`.
- **Grid layout detection by aspect ratio.** Kie.ai storyboard grids are 1376x768 (3x2 = 6 panels per grid, not 3x3 = 9). Use `extraction.detect_grid_layout()` which checks aspect ratio: >1.3 = 3x2, <0.7 = 2x3, else 3x3.

### StoryEngine Pipeline (Supabase)
- **Database schema gaps are silent killers.** The pipeline writes to columns that may not exist in Supabase. PostgreSQL throws errors but `SupabaseAdapter.update_idea_fields()` catches them gracefully — the write "succeeds" but the field is dropped. Always run migration 013+ before testing pipeline steps.
- **Missing columns discovered during E2E testing (2026-03-31):** `stage_transitions.cost`, `stage_transitions.error_message`, `videos.drive_folder_link`, `videos.drive_folder_id`, `videos.idea_reasoning`, `videos.script_validation`, `assets.video_title`, `assets.sentence_index`, `assets.aspect_ratio`. All added in migration 013.
- **`shared/clients/__init__.py` imports ALL clients at package level.** This means importing `AnthropicClient` also imports `GoogleClient` (needs `google-auth`), `SlackClient` (needs `slack_sdk`), etc. If any dependency is missing, ALL client imports fail. Install: `google-auth google-auth-oauthlib google-api-python-client slack_sdk pyairtable mutagen`.
- **`title_idea/` must be in sys.path for research agent.** The research agent imports from `curiosity_gap.gap_title_engine` which lives under `title_idea/curiosity_gap/`. Without `title_idea` in the bot directory list, research fails with `ModuleNotFoundError`.
- **Voice is a hard dependency for image prompts.** `_check_voice_exists()` verifies `voice_over_url` is set on ALL scripts rows before allowing prompt generation. Without ElevenLabs, set placeholder URLs and estimated durations (word_count / 2.5 wps).
- **Script validation can BLOCK scene creation.** If editorial validation fails, `BriefTranslator.translate()` returns `status: "blocked"` before reaching the scene-writing code at line 575. The full script IS saved to `videos.script`, but no `scripts` table rows are created. For testing, create scene rows manually from the saved script text.

## Project-Specific Rules

1. **Async everywhere.** All bots, all clients, all pipeline code uses async Python. Don't introduce sync blocking calls.
2. **httpx, not requests.** The project uses `httpx` for async HTTP. Don't add `requests`.
3. **6 images per scene, 20 scenes per video.** This is the standard. Changes to this ratio cascade through the entire pipeline.
4. **Visual style system is profile-driven.** Holographic HUD uses Dossier/Schema/Echo. Cinematic Illustration (default) uses power_move/lone_figure/environment/data_hud/object_closeup with illustrated characters. The sequencer must match the active profile.
5. **Max consecutive same-type constraint varies by profile.** Holographic: 4 max. Mannequin: 3 max. Read from `profile.rotation.max_consecutive_same_content_type`.
6. **ElevenLabs voice ID is configured, not hardcoded.** Use `ELEVENLABS_VOICE_ID` from .env.
7. **Google Drive is the media store.** Images, audio, and video go to Drive. Don't store large files locally on the VPS.
8. **When adding CLI args to a pipeline function**, make sure EVERY code path that calls it actually passes and uses those args. The `image_filter` arg was parsed correctly in 3 places but never used in the function that mattered.

### Image Prompt Pipeline Patterns
- **Character prefix is conditional.** Only scenes with CHARACTER indicators (seated, walking, wearing, etc.) get the character prefix. Data displays, environments, objects, and maps do NOT get the prefix. Use `_is_non_character_scene()` to check first.
- **Non-character scene types**: holographic display, data visualization, charts, factory floor, military base, aerial view, satellite view, map overlays — these should NEVER have character prefix regardless of any keywords.
- **Regeneration needs context.** When regenerating a prompt for consecutive_location or consecutive_data violations, pass the SURROUNDING locations/types (indices i-2, i-1, i+1, i+2) so Claude doesn't regenerate with a conflicting neighbor.
- **Equipment integrity default.** Drones, weapons, vehicles default to "fully assembled" unless the narration explicitly mentions wreckage/damage. Remove "detached", "disassembled" language from non-damage scenes.

### Visual Style System (Cinematic Illustration)
- **Default style changed from mannequin to cinematic illustration (2026-03-14).** New style: "Cinematic animated illustration in muted earthy color palette with ink outlines and dramatic lighting. Stylized illustrated characters with expressive faces."
- **Two prefixes now exist**: `_CHARACTER_PREFIX` (for scenes with characters) and `_ENVIRONMENT_PREFIX` (for data/environment/object scenes). Both share `_UNIVERSAL_SUFFIX`.
- **Backwards compatibility via alias REMOVED (2026-03-14).** The `mannequin_storytelling` alias and profile file were deleted. Only `clay_mannequin` remains as a separate valid style.
- **Mannequin validation removed.** The prompt_validator no longer checks for naked mannequins or mannequin hands — these checks were style-specific. Style-agnostic checks remain: camera_distance, consecutive_location, consecutive_data.
- **Profile detection changed.** Pipeline uses `uses_story_bible` (any profile except holographic_hud) instead of `is_mannequin_profile`. This is more accurate now that mannequin style is deprecated.
- **Legacy code remnants cause phantom failures.** After ANY style/profile swap, do a full codebase grep to catch stragglers. Dead type hints, comments referencing removed values, and deprecated aliases will confuse validators and cause false positives. Run: `grep -rn "old_style_name" skills/video-pipeline/ --include="*.py"`

### Prompt Builder Data Paths (4 separate concerns)
- **`visual_description` = narration_excerpt** (Story Bible visual content — what to SHOW). NEVER use verbatim script text here. The 9f0093d commit accidentally set `visual_description` to `verbatim_text`, which put raw narrator dialogue into the Scene field of prompts.
- **`sentence_text` = verbatim script text** (exact words from Script table). Used for Airtable Sentence Text field and duration calculation.
- **Characters = costume + action, integrated.** Don't dump raw costume descriptions. Integrate: "figure in [costume], [action]". The `camera_direction` (Story Bible `action` field) tells you what the character is doing.
- **Duration = word_count / WPS** from sentence_text. The V2 scene blocks path must calculate this the same way deterministic_splitter does (DEFAULT_WPS = 2.5, or voice_duration-based). Missing duration causes downstream clip duration decisions to use wrong defaults.
- **These are FOUR separate data paths. Don't cross them.** A fix to one (e.g., making sentence_text verbatim) must not accidentally change another (e.g., visual_description).

### Scene Blocking System (Story Bible V2)
- **Two Story Bible formats exist**: V1 (`visual_arc`) and V2 (`scene_blocks`). Use `has_scene_blocks()` to detect version.
- **Scene blocks group 2-5 images** sharing location + lighting. Only camera angle, action, expression change within a block.
- **First image of every block MUST be wide.** Enforced by validation; auto-fixed if violated.
- **Act boundaries force new blocks.** When narration transitions to a new act, start a new scene block.
- **Global image_index is sequential.** Images numbered 1, 2, 3... across entire video (60-80 total). No per-scene arithmetic.
- **NEVER use Story Bible narration_excerpt for sentence_text.** The deterministic splitter (`segment_scene_deterministic()`) produces verbatim script segments. Story Bible images provide VISUAL CONTEXT only (location, lighting, characters). The V2 path was rewritten 2026-03-15 to fix cross-scene contamination caused by fuzzy-matching narration_excerpts across all scenes.
- **Story Bible ≠ text splitter.** The Story Bible tells you WHERE and WHO. The deterministic splitter tells you WHAT TEXT each image covers. These are separate concerns. `_find_block_context()` maps segments to blocks by text overlap, but `sentence_text` always comes from the splitter.
- **Pre-filter images to the current scene.** `get_all_images_from_blocks()` returns images from ALL scenes. ALWAYS filter by narration_excerpt text overlap before mapping. Without filtering, fuzzy matching leaks images from neighbouring scenes.
- **Total images must match VideoConfig.** If VideoConfig says 60 clips, Story Bible must output exactly 60 images distributed across 12-20 blocks.
- **Block context flows to prompt builder.** Concepts include `block_location`, `block_lighting`, `block_characters` for consistent prompts.
- **Backward compatibility automatic.** Existing V1 Story Bibles (visual_arc) continue to work. New videos use V2 (scene_blocks) by default.

### Prompt Builder Prefix/Suffix (Profile-Driven)
- **NEVER hardcode style prefix/suffix in prompt_builder.py.** Read `profile.style_system.style_prefix`, `.character_prefix`, `.style_suffix` from the visual profile. The `_CHARACTER_PREFIX`, `_ENVIRONMENT_PREFIX`, `_UNIVERSAL_SUFFIX` module constants are legacy fallbacks ONLY.
- **`character_prefix` is optional on StyleSystemConfig.** Falls back to `style_prefix` when empty. Only cinematic_illustration needs it (adds "expressive faces" language for character scenes).
- **Every time visual system code is touched, check if hardcoded strings snuck back in.** This has happened repeatedly — a new feature uses a constant instead of reading from the profile, breaking all other visual styles.

## Session Review Log

_After each session, add a one-line summary of what was done and any new lessons discovered._

| Date | Summary | Lessons Added |
|------|---------|---------------|
| 2026-02-22 | Added CLAUDE.md workflow orchestration + project architecture | Initial lessons seeded from codebase analysis |
| 2026-03-12 | Fixed image_filter ignored in prompt gen + wired mannequin_storytelling scene types into sequencer | Visual profiles wiring, filtering gotchas, profile-aware sequencing pattern |
| 2026-03-12 | Fixed resume logic blocking targeted runs + skip audio sync for partial generation | Targeted vs full run resume logic, audio sync scope |
| 2026-03-14 | Added blocking script validation: promise-payoff tracking, act coherence, senior editor pass | Script validation blocking flow, 7 validation checks |
| 2026-03-14 | Image prompt pipeline fixes: conditional mannequin prefix, context-aware regeneration, MANDATORY rules first, equipment integrity | Image prompt pipeline patterns |
| 2026-03-14 | Visual style overhaul: replaced mannequin with cinematic illustration (312 tests passing) | Visual style system patterns, backwards compat alias |
| 2026-03-14 | Added cinematic voice rules to script writer: scene-driven openings, active framing, film-style transitions | Voice/style additions go in system prompt constants, wire into both profile and legacy paths |
| 2026-03-14 | Implemented Scene Blocking System (Story Bible V2): scene_blocks format, block-aware expansion, prompt builder | Scene blocks patterns, V1/V2 backward compat, narration text matching |
| 2026-03-14 | Removed legacy mannequin_storytelling code remnants: deleted profile file, removed alias, cleaned type hints/comments | Legacy code remnants cause phantom validation failures — always grep after style swap |
| 2026-03-14 | Hotfix: progressive writes before validation + act_coherence threshold to 6 + geopolitical clustering | Scripts must ALWAYS be saved before validation; geopolitics needs higher topic threshold |
| 2026-03-14 | Research agent narrative fields: shared extraction via narrative_extractor.py, wired into all 3 entry points | Shared utilities in clients/ folder; all entry points must use the same extraction logic |
| 2026-03-14 | Fix 3 pipeline issues: cinematic voice prompt position, act_coherence advisory, verified progressive writes | System prompt ordering matters; advisory checks for unreliable fixes; progressive writes already worked |
| 2026-03-15 | Fix cross-scene sentence contamination: V2 path now uses deterministic splitter for text + Story Bible for visual context only. Prompt builder prefix/suffix now reads from profile instead of hardcoded constants. | Story Bible ≠ text splitter; pre-filter images to current scene; never hardcode prefix/suffix |
| 2026-03-14 | Debug Script field write + add !approve command for blocked scripts | Wiring audit failed — "already working" claims need ACTUAL verification with debug logs, not code reading |
| 2026-03-14 | Fix Script field missing from Airtable setup — field documented but never created | Documentation ≠ implementation; always check setup scripts match field audit comments |
| 2026-03-15 | Fix 3 prompt builder bugs: Scene uses narration_excerpt, duration from word count, character integration | 4 separate data paths in prompt builder — don't cross them; V2 scene blocks must match V1 deterministic_splitter capabilities |
| 2026-03-15 | Redesigned prompt builder: profile-driven assembly with substyle suffixes, archetype expressions, metaphor table, negative prompts | Profile data is the intelligence — don't hardcode what the profile already defines; action field is scene direction not camera direction |
| 2026-03-17 | Render pipeline loose wires: wired karaoke captions, Ken Burns, transitions from render_config into Scene.tsx. Removed dead EconomyVideoAnimated composition + dependency tree. Fixed test expectation, Tuning constants, removed voice_speed dead field. | Python writes data → render_config.json → TypeScript reads it. If TS ignores a field, the Python computation is wasted. Always trace data flow end-to-end across language boundaries. |
| 2026-03-18 | Wired Story Bible into storyboard bot: characters, locations, visual arc, scene blocks now injected as binding constraints into directive generation | The storyboard bot was a parallel visual system completely disconnected from Story Bible. Two visual systems generating independently = guaranteed inconsistency. Any new visual generation path must consume the Story Bible — it's the single source of truth for character/location appearance. |
| 2026-03-18 | Fixed 3 pipeline issues: (1) Duration validation halts script gen when Video Length not set, (2) Script field write verification + loud failure, (3) Interactive approval flow for blocked scripts | Silent defaults cause downstream disasters — always validate required fields and notify when missing. Graceful error handling can be TOO graceful — `update_idea_fields` silently drops unknown fields. ALWAYS verify writes succeeded. Schema docs ≠ actual Airtable fields — check both. |
| 2026-03-20 | Fixed karaoke caption overflow: replaced 6-word chunks with character-based chunking (max 38 chars). Container at 72px Inter Bold fits ~39 chars but old code allowed 56+ char chunks. | Don't chunk captions by word count — chunk by character count. Long words like "manufacturing—Bangladesh" (56 chars for 6 words) caused 40% overflow. Character-based chunking adapts: short words → more per chunk, long words → fewer. |
| 2026-03-26 | Unblocked Supabase pipeline: LightPipeline, UUID loading, bot subdir sys.path, no-op clients | LightPipeline pattern works for adapter layer. Bot run.py files have internal imports requiring parent dir on sys.path. Adapter must return written fields for verification. VideoConfig param is video_length_minutes not target_minutes. |
| 2026-04-01 | Per-scene storyboard generation + progress callbacks + deploy race condition fix | Next.js chunk manifest is loaded into memory at startup — `pkill` + `sleep 2` is NOT enough. Use full shutdown sequence. Always restart backend uvicorn after Python changes. The production page uses `production/StoryboardVisualsTab.tsx`, not `video-detail/visuals-tab.tsx` — always verify which component the actual route uses before modifying. |
| 2026-04-03 | Fixed agent crashes (exit 126): prompt exceeded ARG_MAX when task-queue.json grew to 83KB | Pipe prompt via stdin (`< $PROMPT_FILE`) instead of passing as `-p "$PROMPT"` argument. Linux ARG_MAX is ~2MB — large task queues + blueprints + memory easily exceed this. |
| 2026-04-03 | Operator messages were being ignored because they appeared before the task queue in the prompt | Move operator controls + feedback AFTER the task queue (last thing agent reads). Claude prioritizes later instructions. Feedback alone gets ignored — must ALSO set focus directive. Telegram system prompt updated to always set focus on operator messages. |
| 2026-04-03 | RUBRIC server must be restarted after code deploys for new features to work | The RUBRIC server (node server.js) loads code into memory at startup. New API endpoints or schedule changes don't take effect until server restart. Always: `kill $(pgrep -f "node.*server.js"); cd rubric/scaffold && nohup node server.js > /tmp/storyengine-agents/rubric.log 2>&1 &` |
| 2026-04-03 | Built portable agent team template but it's NOT wired to the existing cron system | Two agent systems exist: `run-agent.sh` (StoryEngine-specific, cron-driven) and `run-team.sh` (portable, PRD-driven). They don't talk to each other. Need a dispatcher script that checks context and routes to the right system. |
| 2026-04-03 | Research: Devin is anti-multi-agent, Anthropic says 3-5 agents max | Multi-agent coordination is fragile. Better: single-agent iterative loops with persistent state (progress.md + git). Agents reset context each iteration to prevent hallucination drift. Quality gates (hooks) are more reliable than agent self-reporting. |
| 2026-04-03 | Pipeline Tester is Level 1 with 0 tasks — the "eyes" of the system are blind | The tester must be the most capable agent (Opus, not Sonnet). It should proactively open every page, click through like a user, and file specific bugs as handoffs. Without real browser testing, other agents build blind. |
| 2026-04-03 | Node.js exec() sends SIGTERM to long-running Claude CLI | Use spawn() or a wrapper shell script instead of exec() for Claude CLI calls. exec() has hidden buffer/timeout limits that kill the process. The generate-prd.sh wrapper pattern works: shell script runs Claude, writes result JSON. |
| 2026-04-03 | PROJECT_ROOT was hardcoded to Mac path — silently broke everything on VPS | Never hardcode paths. Auto-detect: `SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"` then `PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"`. The Mac path default caused PRD detection, health checks, activity logging, and server restarts to ALL silently fail. |
| 2026-04-03 | Two disconnected agent systems = nobody learns, nothing is shared | Don't build parallel systems. run-agent.sh is the ONE runner. It checks for PRD tasks (priority) then falls through to task-queue. Same memory, same skills, same RUBRIC activity feed regardless of work source. |
| 2026-04-03 | Frontend safety timeout (3min) was shorter than Claude Opus generation time (4min) | Opus on long prompts takes 3-5 minutes. Safety timeouts must be generous (10min). Add visible elapsed counter so the user knows it's still working, not dead. |
| 2026-04-03 | Agents commit code but servers serve stale builds | After any agent commits frontend changes: npm run build + restart next. After backend changes: restart uvicorn. Without this, Pipeline Tester tests old code and reports false results. |
| 2026-04-03 | Agents referenced skills that don't exist (.claude/skills/) | Only reference skills with actual SKILL.md files. 3 skills were referenced but never existed (systematic-debugging, verification-before-completion, requesting-code-review). Audit .claude/skills/ before adding to agent instructions. |
| 2026-04-03 | User-browser errors are the highest-priority signal | When the user clicks something and gets a 404/405, that's a real bug happening NOW. Auto-inject these at the TOP of every agent's prompt. Auto-create BUG-USER tasks. Auto-spawn agents to fix within 60 seconds. |
| 2026-04-08 | File edits via Edit tool get reverted by external process | Use Bash (sed/cat >>) for edits to backend files, then immediately git add + commit. The Edit tool changes sometimes get overwritten before staging. |
| 2026-04-08 | email.py shadows Python stdlib email package | Never name a module `email.py` — it shadows `email.parser` used by `http.client`/`httpx`. Use `email_service.py` for the real implementation. Keep `email.py` as a non-importable stub if acceptance criteria require the filename. |
| 2026-04-08 | Pre-push hooks require tasks/lessons.md + tasks/todo.md updates | Git pre-push hook blocks if >3 files changed without updating lessons.md and todo.md. Always update both before pushing. |
| 2026-04-10 | setCadence updates crontab but not crons.json — dashboard shows stale data | Any function that writes to the system crontab must ALSO sync the Crons dashboard data file (`rubric/crons/data/crons.json`). Otherwise the two sources of truth diverge silently. |
| 2026-04-10 | security-auditor existed as agent file + standing orders but was never scheduled | When adding a new agent, wire it into ALL three places: (1) agent .md file, (2) scaffold config.json, (3) setCadence cron schedule. Missing any one = dead agent. |
| 2026-04-10 | Backend health check only restarted on connection refused (000), not on 500 errors | Health checks must match the strictness of their counterparts. Frontend checked `!= 200`, backend only checked `= 000`. Use consistent thresholds — allow 200 and 401 (auth-gated), restart on anything else. |
| 2026-04-10 | RUBRIC cron system: 7 features (concurrency guard, timeout, cost tracking, log viewer, crons-controls sync, runtime viz, toast notifications) | PID lock files + trap cleanup is the standard Unix concurrency pattern. Wrap long-running CLI with `timeout --signal=TERM --kill-after=60`. Duration-based cost heuristic (Opus ~$0.05/min, Sonnet ~$0.01/min) is good enough for dashboards. Always validate path params with regex before constructing file paths (prevent path traversal). |

### StoryEngine / Agents
- **Stash merge conflicts on profile.py**: When a git stash creates conflicts, the upstream (committed) version usually has the better code — keep it. Profile.py upstream has robust try/except for email uniqueness; stash had a simpler version without it.
- **agents/progress.md**: This file was deleted upstream — accept the deletion, don't restore it.
- **Global in-memory dicts need tenant scoping**: `_running_tasks` in pipeline.py was keyed by `video_id` only — any authenticated user could see all tenants' task progress via SSE. Always key cross-tenant caches by `(tenant_id, resource_id)`.
- **HTML-escape user input in email templates**: `display_name` was f-string interpolated directly into HTML email body. Use `html.escape()` on all user-controlled values before HTML interpolation.
- **Don't send API keys as URL query params**: Gemini validation put the key in `?key=VALUE` — gets logged in access logs. Use `x-goog-api-key` header. Also don't return raw `str(e)` to clients — generic error messages only.
- **FastAPI route ordering matters**: Literal path segments (`/keys/validate`) must be defined BEFORE parameterized segments (`/keys/{key_name}`) or the parameter route will catch both. POST `/keys/validate` was unreachable for months because `/keys/{key_name}` matched first.

### run-agent.sh sources .env which leaks ANTHROPIC_API_KEY to Claude Code (2026-04-10)
- run-agent.sh does `source .env` to get Slack tokens etc, but this also exports ANTHROPIC_API_KEY
- Claude Code sees the env var and uses it instead of OAuth, billing $64/day to the API key
- Fix: `unset ANTHROPIC_API_KEY` after sourcing .env
- Pattern: Always audit what env vars leak to child processes when sourcing .env files

### Stale progress.md causes false task completion (2026-04-10)
- progress.md from PRD 4 had [x] marks for tasks 1-15. When PRD 2 deployed with tasks 1-13, mission-status saw all as done
- Fix: verify progress.md title matches current PRD before trusting any [x] marks
- Pattern: Any file that persists across PRD deployments MUST be validated against the current PRD

### Shim-removal refactor left 5 stale imports (pipeline couldn't import) (2026-06-08)
- Commit 17b03be0 "Remove all shims, update all imports, squeaky clean" deleted the back-compat shim packages (curiosity_gap/, brief_translator/, audio_sync/, etc.) but missed updating 5 imports, leaving `ModuleNotFoundError: No module named 'curiosity_gap.gap_title_engine'` — `orchestrator.pipeline` (and --run-queue/--discover) could not import at all.
- Missed imports: title_idea/{idea_bot,cli,trending_idea_bot}.py + research/agent.py used `from curiosity_gap.gap_title_engine import ...` (canonical: `title_idea.curiosity_gap.gap_title_engine`); script/run.py used `from brief_translator import ...` (canonical: `script.brief_translator`).
- Pattern: after a "remove shims + rewrite imports" sweep, grep the WHOLE tree for the old top-level names (`^\s*(from|import)\s+<oldname>`) before trusting it — the leftover empty dirs (only __pycache__/tests) hide that the package is gone. Vestigial dirs without __init__.py are a tell.
- NOTE: `python -m orchestrator.pipeline` with NO args is NOT a safe smoke test — it instantiates clients and hangs/works; use `python -c "import orchestrator.pipeline"` instead.

### SlackClient now no-ops without a token (neuter for customer-facing) (2026-06-08)
- SlackClient.__init__ used to `raise ValueError` if SLACK_BOT_TOKEN was missing, and the pipeline instantiates it unconditionally (VideoPipeline.__init__) — so simply blanking the token in .env would CRASH every run.
- Fix: __init__ sets `self.enabled = bool(token)` and `self.client = None` when absent (no raise); the 4 API methods (send_message/send_blocks/add_reaction/get_message) early-return None when not enabled. notify/notify_blocks + all notify_* delegate to those, so the whole client goes silent.
- To actually silence Slack: this code change + blank SLACK_BOT_TOKEN/SLACK_APP_TOKEN in .env. Pattern: an optional integration should degrade to a no-op, not raise, when its credential is absent.

### Multi-tenant ChannelConfig foundation (2026-06-08)
- Pipeline is going multi-tenant (a customer-facing channel-growth product). Content/media stays in each creator's own Google Drive; a dedicated free Supabase project (`youtuber`, ref wrromlupsmyzrrcqlucn) holds only lightweight per-tenant state/config (KB/video — Supabase cost fear only applies to media, which we don't store there).
- New `shared/channels/` package: `ChannelConfig` + `load_channel(slug)` reads channels+channel_config (+ latest drive_connections) from Supabase via psycopg2 over the session pooler (host `aws-1-us-east-1.pooler.supabase.com`, scoped role `youtuber_agent`, RLS policies per-role). YOUTUBER_DB_URL in .env (gitignored).
- Default channel `economy_fastforward` falls back to env vars if the DB is unset/unreachable → legacy single-channel pipeline runs unchanged even without Supabase. Verified default-equivalent: VideoPipeline() yields identical airtable base / voice / drive folder.
- Threading pattern: clients already accept overrides (AirtableClient(base_id=), ElevenLabsClient(voice_id=), GoogleClient(refresh_token=) + .parent_folder_id attr). Per-channel script/visual profile flows to sub-bots by setting SCRIPT_PROFILE/VISUAL_PROFILE env in VideoPipeline.__init__ (no need to edit each bot). `--channel <slug>` CLI flag (stripped from argv; resolves via CHANNEL_ID env).
- state_store column: 'airtable' (legacy EFF) vs 'supabase' (new creators). The Supabase-backed status machine (videos table reads/writes) is NOT wired yet — that's the next increment; today only config is multi-tenant.

### YouTube bot-checks the VPS IP — yt-dlp watch-page extraction is dead without cookies or a proxy (2026-06-10)
- YouTube hard-flagged the VPS egress IP: every watch-page/player extraction returns "Sign in to confirm you're not a bot". This silently degraded Model A Video transcript analysis, competitor scraping (routes/niche.py), and voice-learn (routes/youtube_channel.py) — all funnel through `routes.niche._extract_video_info`.
- **Verified dead ends (don't retry these):** all alternate `player_client`s (android/ios/mweb/tv_embedded/web_embedded/web_safari/tv_simply), upgrading yt-dlp (2026.03.17 → 2026.06.09), the bgutil PO-token provider (plugin registered fine, bot check fires anyway — PO tokens fix format gating, not IP bans), and youtube-transcript-api (raises `IpBlocked` from the same IP).
- **Still working from the flagged IP:** flat channel listing (`extract_flat` on /videos tabs — browse endpoints aren't blocked, only player/watch) and the oEmbed API (title/author/thumbnail, no auth). That's why Phase-1 scraping kept partially working while transcripts vanished.
- **Only real fixes:** (1) `YTDLP_COOKIES_FILE` — Netscape cookies.txt exported from a browser logged into YouTube, or (2) `YTDLP_PROXY` — residential/unflagged egress. Both now wired into `_ytdlp_antibot_opts()` in routes/niche.py and documented in .env.example + docs/env-vars.md. The bot-check failure is now logged with a fix hint instead of swallowed (`ignoreerrors` removed from `_extract_video_info` so the DownloadError reaches our except).
- Pattern: when a scraper "returns None sometimes", reproduce from the PRODUCTION egress IP before debugging code — IP reputation, not code, was the root cause.

### Script ↔ Drive sync: per-tenant Docs needs the Docs API enabled + creds nuance (2026-06-15)
- The per-tenant Drive refresh token (`channel_profiles.google_drive_refresh_token`) is minted by the **`GOOGLE_OAUTH_CLIENT_ID`** app (routes/google_auth.py), NOT the pipeline's `GOOGLE_CLIENT_ID`/`GOOGLE_REFRESH_TOKEN` app. To refresh a tenant token you MUST build the client with `GOOGLE_OAUTH_CLIENT_ID/SECRET` (we fall back to `GOOGLE_CLIENT_ID/SECRET` for single-app setups). Both are set in the LOADED env file `storyengine/.env` (main.py loads `../.env`); `storyengine/backend/.env` is a stale unused file — check the right one.
- Creating a Google **Doc** uses the Docs API (`docs.googleapis.com`), which is a SEPARATE enablement from the Drive API on the GCP project. Brief-upload only ever used the Drive API, so Docs was never enabled — first push 403'd "Google Docs API has not been used in project 802685987716...". Enabled it in console (project `storyengineagent` = 802685987716); push worked immediately. `drive.file` scope is fine for create+batchUpdate+get/export on app-created files.
- A Doc's Drive `modifiedTime` keeps settling for ~1-2s AFTER a Docs `batchUpdate` returns, so a status check right after a push can read "Drive newer than last sync" falsely. Cosmetic; self-heals on the next status/sync. If it ever matters, store modifiedTime from a re-read a couple seconds post-write.
- Scene-map contract verified: the push preamble literally contains the string `### SCENE n`, but the Pull parser regex requires a DIGIT after SCENE (`scene\s+(\d+)`), so the instructional line is safely ignored — `count("### SCENE")` is scenes+1.

### Deploying: `kill <uvicorn PID>` can hang ~50s; use `kill -9` when prod is idle (2026-06-15)
- The documented deploy ("git pull, kill the uvicorn PID, systemd Restart=always revives in ~5s") hung: SIGTERM made uvicorn release port 8001 immediately (health → 000) but the Python process stayed alive ~50s, stuck in graceful shutdown on the in-process BackgroundTasks executor. Because the signal was sent DIRECTLY (not `systemctl stop`), systemd still saw its MainPID alive and never applied TimeoutStopSec → no auto-SIGKILL, no replacement started.
- Fix: `kill -9 <PID>` — the hard exit makes systemd notice MainPID died and `Restart=always` brings up a fresh process on the new code in ~10s. SAFE here only because prod was confirmed idle first (`SELECT ... FROM background_tasks WHERE completed_at IS NULL` empty). NEVER -9 mid-clip-run/render (no resume).
- Before any restart, check `background_tasks` for unfinished work via the Supabase MCP (project wrromlupsmyzrrcqlucn). Migrations auto-apply on boot — confirmed via the "Migration applied: NNN_*.sql" startup log line.

### GPT Image 2 locks cast identity better than nano-banana for SCENE images (2026-06-22)
- Character drift between scenes (a face or outfit changing shot to shot) is a top "cheap AI" tell. The default scene-image model is now GPT Image 2 because it holds the cast's identity from the cast sheet far better than nano-banana. `image_client.generate_scene_image_gpt`: image-to-image when a cast reference exists (reuses `generate_thumbnail_gpt2`), text-to-image (`gpt-image-2-text-to-image`, 2K) when not. gpt-image-2 is always offered as a scene model regardless of the profile's configured list.
- Coverage frames (multi-angle keyframes per scene) now have a store-in-app path: `scripts/coverage_to_app.py` runs `coverage.py` for one or all scenes with the tenant's own Claude + Kie keys, uploads each frame to app storage, and INSERTs an `assets` row tagged `generation_method='coverage'`. Wired via `routes/pipeline.py`.
- GOTCHA (git): this work lived ONLY as uncommitted edits on the VPS working tree (edited ~22:0x, committed to no branch including the `claude/*` ones). A `git checkout`/clean would have destroyed it AND reverted the live image model on the next restart. Lesson: running-but-unsaved is not "implemented". Run `git log --all -S <signature>` to confirm before treating uncommitted-but-live work as safe to discard.

### DVsU single-machine script proof: numeric form is not numeric support (2026-07-12)
- The story compiler should validate numeric identity, not surface formatting. If source/evidence supports `5000`, a script sentence may say `5,000`, `5000`, or `five thousand`; if it says `six thousand`, the validator must still fail.
- Prompting the model to "never spell numbers" over-constrains the voice and causes false rejects. The safer contract is: numbers may be numerals or words, but every number must map back to the locked beat's `numeric_tokens` and source excerpt.
- Claude may return a compact `evidence_sentences` array even after being asked for keyed `sentences`; canonicalize that shape before validation, then let the strict beat/order/evidence checks decide pass/fail.
- Do not use a deterministic extractive fallback for DVsU machine script previews. If the model cannot produce a natural Anton-style paragraph whose `claim_map` validates against the locked evidence slots, fail the preview for review instead of saving safe filler.

### DVsU Anton slots: memorable facts are a hard quality gate (2026-07-13)
- Required single-machine script evidence slots are `identity_origin`, `scale_specs`, `build_reality`, `service_reality`, and `memorable_fact`. `historical_meaning` is optional source context only; the final sentence should synthesize the paragraph rather than research a meaning beat.
- Anton's desktop writing standard says every paragraph needs one surprising or memorable fact; if verified one-machine research cannot source that, the preview should fail instead of producing a generic catalog paragraph.
- Keep the validator, research prompt, script prompt, and tests aligned so the model is not asked to cover a slot the code silently treats differently.

### DVsU phase gates: preview is not a Research artifact (2026-07-13)
- Research phase must only gather, verify, and save selected-machine research cards with exact evidence. Do not run or display script output from Research just because an endpoint exists.
- Script phase owns one-machine writing. The operator action should be "write/save selected machine script block"; an internal preview/dry-run may exist for developer validation, but product UI should not present it as the script workflow.
- Saving one machine script block should update only that machine's `scripts.scene_text`, keep script-hold progress in `script_validation`, and advance to voice only after every locked roster machine has passed.

### Subagent model tiers: premium for brains, Sonnet for hands (2026-07-17)
- Fan-out subagents (codebase exploration, search sweeps, web research, mechanical edits) inherit the SESSION model when no override is passed — a premium-model session silently makes every fan-out premium. A 4-agent repo exploration + 28-agent research workflow all ran on the top tier when Sonnet would have produced the same file-reading output.
- Standing policy (now in CLAUDE.md → Subagent Strategy): premium model for the main loop only (orchestration, architecture, verification, final synthesis); pass `model: "sonnet"` on every Agent call and `{model: 'sonnet'}` in workflow `agent()` opts for all hands-work. Escalate a subagent to premium only when the subtask itself needs deep reasoning, and say so.

## 2026-07-18 — Stub-driven tests can mask missing SELECT columns (caught in C16b)
C13b added `render_style`/`video_model_id` references at `generate_coverage_for_video`'s
`run_coverage()` call site but never added the columns to `v`'s SELECT — a NameError on every
real invocation. All tests stayed green because they exercised sub-functions with stubbed rows
carrying extra keys; nothing drove the real function end-to-end. The per-scene try/except then
turned the crash into silent "Scene N: errored — moving on" (fail-before-spend, so no billing,
but the paid image stage produced nothing). RULE for orchestrator briefs: when a chunk adds a
new column reference to any function that reads DB rows, the worker must (a) quote the updated
SELECT list in its report and (b) add at least one test that drives the REAL function with a row
shaped exactly by that SELECT (no extra stub keys). Orchestrator review should grep the SELECT
whenever a report says "threaded a new field through."

## 2026-07-18 — A fake-async race test can be vacuous even with an explicit yield point (caught in C16d)
Testing a TOCTOU race (two `asyncio.gather`'d calls both reading "not found" before either
writes) with a fully in-memory fake DB requires the fake to snapshot its read result BEFORE
yielding to the scheduler (`await asyncio.sleep(0)`), not after. Yielding first, then computing
the result, lets caller A run its ENTIRE read+write to completion in one uninterrupted scheduler
turn (since a non-blocking fake has no other suspension point), so by the time caller B's read
actually executes, A has already written — B's own pre-existing "does one exist?" check then
correctly finds A's row and returns early, which looks identical to the fix under test working,
even when tested against the PRE-FIX source with the fake wired to allow duplicates. The
`test_c16d_task_store_job_id_conflict.py` race test passed against both fixed AND stashed
(pre-fix) `task_store.py` on the first attempt for exactly this reason — silently vacuous
despite having an explicit `asyncio.sleep(0)` in the fake. RULE: when simulating a race with a
hand-rolled async fake (not real threads/real DB), the read's RETURN VALUE must be computed
BEFORE the yield point, so every "concurrent" caller observes the state as it existed at the
moment they'd have issued the real query, not the state after a sibling call already mutated it.
Always run the non-vacuous `git stash` proof on the EXACT race test, not just the simpler
sequential-call tests in the same file — a suite can be 3/4 real and 1/4 theater.

## 2026-07-19 — Orchestrator: no git branch operations while a worker is mid-edit
The orchestrator ran a docs commit + checkout main + ff-merge while a Sonnet worker was actively
editing the shared tree; git carried the worker's uncommitted modifications across the branch switch
(harmless this time, could have clobbered). RULE: the orchestrator only runs checkout/merge/reset in
the window between a worker's completion report and the next dispatch. Docs-only commits on the
working branch are fine ONLY with explicit paths (`git add <file> <file>`) — NEVER `git add -A`/-a
while a worker runs (2026-07-19 second incident: `git add -A` swept a worker's in-progress 633-line
onboarding.py rewrite into a docs commit; tree stayed intact but history split the chunk's diff and
broke the worker's stash-proof mechanics). Branch switching remains forbidden during a worker run.

## 2026-07-19 — Never assert a subsystem's absence from session memory (Ryan correction)
Claimed "there's no Stripe/billing in the codebase" while designing MCP monetization — Ryan
corrected: he hooked Stripe up months ago (routes/billing.py, 527 lines, plan gates, webhooks,
regression-locked tests). The session's build loop never touched billing, so it never entered
context — absence from MY context is not absence from the REPO. Rule: before any "X doesn't
exist / has to be built" claim that shapes a design or a chunk brief, run the 10-second
`Grep -i <x>` across the repo first. Existence claims are cheap to verify and expensive to get
wrong (I nearly queued a chunk to build a parallel subscription system beside a live one).

## 2026-07-24 — Scope visual fixes to the defective primitive

Ryan identified one concrete visual defect in the five-minute synthetic showcase: the
Evidence Board title was not centered and crossed its boundary. A global title-position
change fixed that frame but created a new collision in the 4:57 StoryEngine reveal.
The accepted repair added a per-primitive title-style override only to EvidenceBoard and
then checked both the reported frame and the downstream reveal. Rule: when visual feedback
names one primitive, repair that primitive first and inspect high-value downstream scenes
before generalizing the layout change.

## 2026-07-24 — Creative acceptance outranks container-byte purity for showcase QA

The initial full-proof loop over-weighted byte-identical delivery MP4s. Ryan clarified that
the decision is primarily what the film looks and sounds like. Source PNG/WAV determinism,
manifest identity, probing, and hashing remain necessary engineering diagnostics, but they
must not consume the creative-review budget once silent drift is prevented. Directly inspect
the motion primitives, typography, framing, captions, pacing, audio intent, crop behavior,
and product reveal; report any remaining delivery-hash difference honestly.

## 2026-07-26 — A deterministic control proof must bind identity, playback, and truth

Regex-valid placeholder hashes, a synthetic-only hard-coded shot board, and status text
without playable artifacts can all make a control system look complete while proving
little. The accepted Scene Control verifier pass required one cross-language canonical
hash chain, exact non-synthetic shot read models, same-origin byte-bound playback, and
stale-versus-current evidence labels. Also test adversarial boundaries that happy-path
fixtures hide: scene-number gaps, arbitrary existing-video seeding, fractional-cent
rounding, arbitrary transition evidence, and manifest drift.

## 2026-07-27 — A once-per-mount ref plus a `cancelled` cleanup flag = a permanent spinner under Strict Mode

The Director chat column (`DirectorSurface.tsx`, the only `docked={false}` mount of
`ChatCore`) sat on its first-load spinner forever on every dev page load. It looked like a
hung or silently-failing fetch. It was neither: `/api/dashboard/onboarding/status` returned
200 every time. The effect that clears `checking` had TWO guards that cancel each other out:
an `autoTriedRef` so the body runs once per component instance, and a `cancelled` closure
flag set by the effect cleanup and checked before every `setChecking(false)`. React Strict
Mode (ON by default for the App Router whenever `next.config.ts` omits `reactStrictMode`)
mounts, cleans up, then remounts every component once in dev. Run #1's cleanup set
`cancelled = true`; run #2 hit the ref and returned instantly. Nothing ever cleared the flag.

Rules:
- **A ref guard and a cleanup-cancel flag in the same effect is a bug shape.** Pick one. A
  `cancelled` flag is for effects that RE-RUN and race (keyed on deps, like the dock's
  `[docked, videoId]` hydrate). A once-per-instance ref means there is no second run to race,
  so the flag can only ever suppress the single real run. React 18+ makes setState on a truly
  unmounted component a silent no-op, so the flag buys nothing there either.
- **Request COUNTS in the network panel identify a Strict Mode remount instantly.** Two
  effects in the same component, one firing twice (`/api/chat/suggested-models`, no guard)
  and one firing once (`/api/dashboard/onboarding/status`, ref-guarded), is the signature.
  A 200 on the single-fire request rules out "the fetch never resolved" in one look.
- **The backend CORS allowlist is `localhost:3001,3000` only** (`backend/main.py`, the
  `ALLOWED_ORIGINS` default). A worktree dev server on any other port gets an opaque
  `TypeError: Failed to fetch` on every API call and lands you on `/login` with no console
  error, which reads exactly like a broken dev token. Run on 3000 or 3001, or nothing works.
- **The Claude in-app browser pane cannot reach the prod API at all** (`Failed to fetch` to
  `76.13.119.181:8001` even when `curl` from the same Mac returns 200). For any StoryEngine
  local walk against prod data, drive the real Chrome via `claude-in-chrome`, not the pane.

## Session 2026-07-27 — git stash is shared across worktrees
- **`git stash` is shared across ALL worktrees of a repo. It is NOT per-worktree.** When parallel workers run in separate worktrees at the same time, a stash/pop cycle on one can accidentally pull the other worker's uncommitted work into its own tree. Two separate worktrees shared one stash state; one worker stashed, worked, then popped and got the wrong contents (both tree's uncommitted state mixed). This was caught and restored, but it could have destroyed work silently.
- **Rule for parallel workers in a shared repo: never use `git stash`.** To prove a fix (the "stash-proof"), use `git diff > /tmp/patch && git checkout -- <explicit paths>` and reapply, or better, prove it on a scratch branch or with a test that fails before and passes after. Also always commit by explicit path only (`git add <exact-path>`, never `git add -A`), to avoid colliding with another worker's staged changes or sweeping up secrets.

## Session 2026-07-27 — Clean merges are not proof; guards do not travel with replaced code

1. **A clean git merge is not proof.** Twice today two branches touched different lines of the same file, git reported "Automatic merge went well" with zero conflicts, and the combined behaviour was still wrong - once a rejected script still showed a green tick because the two changes touched different lines but contradicted in meaning. After every merge, ask what each side intended and confirm the combined result still delivers both. Compare the sorted list of FAILING TEST NAMES before and after, not just the counts.

2. **When a code path is replaced, its guards do not come with it.** Confirmed twice today. A March guard stopping image spend on a voiceless video was left behind when the image system moved to a new coverage path - the old guarded code still sits there unused while every real caller goes around it. Separately, character generation exists in three independent implementations and all three were missing the same ledger write. When you find a missing guard, grep for OTHER implementations of the same feature before assuming you fixed it.

## Session 2026-07-29 — Driving the in-app Browser pane against prod: the working recipe

Context: verified chat-card inline scene editing live against the prod API from a
worktree, with ports 3000/3001 both held by OTHER sessions' dev servers. All four
of these were paid for in wasted clicks; together they make the pane fully usable:

- **Scratchpad CORS proxy beats both known blockers at once.** The pane page can't
  fetch `76.13.119.181:8001` directly (2026-07-27 lesson) and the backend's CORS
  allowlist is 3000/3001 only. Fix: tiny python proxy on `localhost:9001` that
  forwards to prod and answers CORS/preflight itself (auth is a Bearer header, so
  `Access-Control-Allow-Origin: *` is safe), plus `.env.local` pointing
  `NEXT_PUBLIC_API_URL` at it. Dev server can then run on ANY free port. Proxy
  lives in the session scratchpad, zero tracked-file changes.
- **`computer` click coordinates are SCREENSHOT-pixel space, not viewport space.**
  Screenshots come back 800x450 for a 1280x720 viewport; multiply
  `getBoundingClientRect()` centers by 0.625 before clicking. A click in the wrong
  space hits `<html>` (instrument with a capture-phase click listener logging
  `e.target` to see this instantly). Misleading detail: the tool ECHOES ref-based
  click positions in viewport space, which makes the two spaces look identical.
- **In a hidden pane, programmatic `el.focus()`/`el.blur()` fire no real focus
  events** (document isn't focused), so React `onBlur` handlers never run and
  `element.click()`-opened editors autofocus silently fails. Real injected clicks
  DO move focus. Rule: enter/exit focus states with real clicks at converted
  coordinates; keep synthetic events for dispatching keydowns (React sees those).
- **Transient UI states (a 1.5s "Saved" flash) can't be caught across tool calls**
  (~1-2s latency each). Install a MutationObserver logging to a `window.__x` array
  BEFORE the real interaction, then read the array after. Caught the full
  Saving→Saved lifecycle on the first try after three timing misses.
- Also: a fresh worktree needs no `npm install` for frontend checks — symlink the
  main checkout's `frontend/node_modules` (works for tsc, `npm run build`, AND the
  dev server). And ChatCore's rAF scroll re-anchor loop will yank
  `scrollIntoView()` away right after mount or a card expand — measure element
  rects in the SAME eval that scrolls, immediately before clicking, once
  animations have settled.

## 2026-07-30 - git stash is ONE shared ref across all worktrees (real incident)
Two concurrent workers ran stash-based stash-proofs in different worktrees of the same repo; the pops interleaved and each worker popped the OTHER's stash - foreign diffs landed in the wrong trees mid-test. Recovered via `git fsck --unreachable` (stash WIP commits dangle after a wrong pop). Rule: NEVER use `git stash` for stash-proof testing while parallel worktree sessions run. Use a patch file instead: `git diff > /tmp/chunk.patch && git checkout -- <files>`, run the tests, `git apply /tmp/chunk.patch`. Every worker brief that asks for a stash-proof must name this technique.

## 2026-07-31 - Two lessons from the Veo 3.1 Lite first/last-frame test

**1. Sampled stills CANNOT verify a video. (correction from Ryan)**
I pulled 6 frames at ~1.5s intervals from an 8s clip, saw good composition in each,
and reported "real weight transfer, not a dissolve." Ryan watched the actual video:
the subject falls, then FLOATS IN DEAD AIR for ~3 seconds, then gets grabbed. Motion
artifacts (floating, morphing, sliding, judder, padded holds) live BETWEEN sparse
samples - stills are structurally incapable of showing them.
Rule: never judge motion from sampled frames. Either watch it, or build a dense
contact sheet (`-vf "select='not(mod(n,7))',scale=440:-1,tile=4x5"`) which shows
the motion progression in one image and exposes floats/slides immediately. The
contact sheet made all of it obvious in one look after the sparse stills hid it.

**2. Veo 3.1 Lite first/last-frame is keyframe matching, NOT motion inference.**
Given a start frame (mid-fall, reaching) and end frame (caught, hanging) over 8s,
it nailed both endpoints and PADDED THE MIDDLE with a static hold rather than
redistributing the action across the clip. It will not "read between the lines."
Rule: only use first/last-frame interpolation when the real action naturally fills
the whole clip length - slow turns, reveals, pushes, expression changes. For any
shot with an impact beat (a catch, a hit, a landing), the model pads and the shot
dies. Match clip duration to the action's true duration, or drive it with
single-image i2v + a motion prompt so the model owns the timing instead of being
pinned to a destination frame.
Cost of the test: $0.20 ($0.025 x2 GPT Image 2 keyframes + $0.15 Veo 3.1 Lite 8s).

## 2026-07-31 - Question the gate, don't appease it (Ryan's co-founder rule)
Weeks of sessions (Claude and GPT) tuned normalizers, queries, and repair prompts to
satisfy the research referee's Tier 1-2 source floor. First hands-free run: 5/5
rejected, zero false facts - all prestige formalism. One plain paragraph to Ryan about
the gate itself and he dropped the requirement in one message.
THE RULE: when the same gate/spec eats 2+ rounds of fixes, stop and question the
design. Bring Ryan: what keeps failing, why the design causes it, ONE recommended
change, the tradeoff in plain words. Inherited gates from earlier sessions are not
sacred. Silent grinding against a bad rule is the most expensive form of diligence.

### Batch-press scripts must log FULL warnings (2026-08-03)
- The 22-card and repair-run scripts logged only pass/fail summaries; diagnosing the residue cost 5 extra paid presses to recapture warnings the responses already contained. Any batch runner must log the complete blocking-warnings list per item.
- A "RUN COMPLETE ok=22" line is not success - count per-card outcomes (4 of those "ok" were 0-second no-ops). Sum lines lie; per-item lines don't.
- Log-line claims from a previous session are hypotheses, not diagnoses: "polish dropped roughly" was wrong twice over - the real causes were a sentence-scoped hedge flag and a last-word designation fallback. Reproduce offline through the REAL function before building a fix.

### When generation fails an angle/view, question the INPUT before the wording (2026-08-04)
- The static-docu bow-quarter view failed vision QA 4x across 2 tuning rounds ($0.20). Both rounds tuned prompt wording and judge strictness. The actual cause was architecture: every view was generated directly from the raw historical reference photo, whose own camera angle bleeds into the output. Ryan saw it immediately; the orchestrator did not.
- THE RULE: when an image/video generation repeatedly misses a viewpoint, style, or framing target, diagnose the DATA FLOW first - what image is the model anchored to, and does that anchor fight the instruction? Only tune wording after the inputs are right.
- Sharper form: the fix (generate one clean canonical render, derive all other views FROM it) was already house law for characters ("char sheets first, pass as image_input to every keyframe"). Asset types differ; the anchoring pattern transfers. Check the existing playbook for the same problem solved in another domain before inventing.

### First post-fix run is ONE unit, never the batch (2026-08-04)
- After the pictures-stage planner bug was fixed, the orchestrator proposed re-running the full $3.45 batch as the proof. Ryan's correction: run ONE machine (~$0.15) and look at it first. This is the standing Scene Lab habit (under-$1 iterative proofs) applied to every stage: the first run after ANY fix or config change is the smallest billable unit, verified with eyes, before the batch. The batch quote comes second, not first.

## 2026-07-30 - fold jobs must NEVER git-stash the shared checkout (second stash incident today)
A Haiku fold job hit local mods in the shared main checkout and "helpfully" ran git stash to merge,
leaving the ENTIRE day's uncommitted task-file state (199 checklist ticks, the loop handoff) in
stash@{0} instead of the working tree - on a box a second live session shares. Recovered by pop +
keep-both conflict resolution. Rule: fold/merge briefs must say "if local mods block the merge, STOP
and report - never stash, never reset". The task files being uncommitted-by-convention makes them
invisible-fragile; treat any operation that touches the index on the shared tree as a stop condition.

### 2026-08-05 - A verifier can fabricate evidence too (ENV-1 maestro loop)
A Haiku verification agent asked to paste `git show --stat fbdff463` output pasted a plausible-looking but FALSE stat (4 files, 399 insertions, including a models.py change that was never in the commit; the real commit is 6 files, 780 insertions). The orchestrator trusted the fabricated paste over the builder's accurate report and burned a bounce accusing the builder of overclaiming. Rule: when two agents contradict each other about repo state, neither report settles it - run the exact command yourself in the pinned worktree and compare raw output. And never ask a verifier for a "condensed" paste of command output; condensing invites small models to reconstruct instead of paste. Ask for verbatim output of narrow commands.

## 2026-08-05 - Parallel builders in ONE shared worktree: isolation experiments must never touch another lane's files
During the S6 loop, two builders worked the same worktree on disjoint files. One lane's "isolate my changes" experiment ran `git stash push` to revert the OTHER lane's uncommitted edits and reproduce a baseline. That silently wiped the sibling's in-progress work from the tree (recovered from the stash, but the pop also swept in a stale years-old stash entry that conflicted with tasks/deferred-verification.md).
**Why:** stash/checkout/clean operate on the whole tree, not "my files" - in a shared tree they are cross-lane weapons.
**How to apply:** briefs for parallel same-tree builders must say: never stash, revert, or checkout files you don't own; if you need an isolation experiment on another lane's changes, do it in a throwaway clone (`git worktree add /tmp/... HEAD`), never in the shared tree; commit your own work early to shrink the exposure window.

## 2026-08-06 - Changing a query's positional args breaks arg-count-pinned test fakes far from the feature
S7-A's update_scene_text gained a 6th positional UPDATE arg (a COALESCE for the new action column, alongside the existing location COALESCE). Three test fixtures (test_d7_2_staleness_hash.py, test_d7_1_script_sync.py, test_d7_3_scene_edit_invalidation.py) each had a `_make_fake_db` that unpacked that query's args as a fixed 5-tuple, and broke with "ValueError: too many values to unpack (expected 5)". None of the three appeared in the feature-keyword grep (searching for "action", "stage direction", etc.) that picked S7-A's targeted test set, because the fixtures live under staleness-hash and script-sync test names, not action-feature names - the break only surfaced later, in S7-C's run.
Rule: when a change adds or removes a SQL query's positional args, grep tests/ for fixtures that unpack THAT query's args (and for exact SQL substrings of the changed statement) BEFORE running only the targeted/keyword-matched test set. A feature-keyword search misses fixtures named after a different feature that happen to share the same query.

## 2026-08-06 - A speech/storage split needs a boundary sweep, not a call-site fix
S7-C needed one property proven everywhere: scene_text can carry LOCATION:/ACTION: headers in storage, but nothing spoken may ever include them. Rather than patching narration_text and calling it done, the work built a sweep table of every scene_text-to-speech surface in the codebase with an explicit verdict per row (protected transitively / protected directly / no third boundary needed). That table is what caught a transitive dependency (custom_film_production_runner.py's _voice() imports narration_text directly, so it needed no separate edit) that a call-site-by-call-site fix would have missed, and confirmed the dialogue paths (dialogue_voice, clip_dialogue) were covered by the one upstream segment_scene strip rather than needing their own.
Rule: when a value must be prevented from crossing a boundary (storage-to-speech, internal-to-external, trusted-to-untrusted, etc.), enumerate every consumer of the source value into a sweep table with a verdict per row, not just the consumers you already suspect. The pattern generalizes past this feature.
