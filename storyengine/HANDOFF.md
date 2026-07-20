# HANDOFF - 2026-07-20 - C25a coordinated deploy day: MCP went LIVE, 13 hotfixes, models verified

## State
- Prod: c8ea9783 deployed (20:17 UTC), healthy. main == origin == local (846c2607 is a docs commit on top).
- Branch: main, clean (one stash: "partial C25a-fix3 voice edits" - redo as a proper chunk).
- What shipped this session:
  - C25a media auth deployed + hardened through fix2-fix13 (internal URL signing, .png suffix, workspace-membership auth, 10s negative cache).
  - MCP LIVE: MCP_ENABLED=true, Streamable HTTP compliance, 86 tools, paywall verified live, subscription-first tool descriptions. Connected via Claude Code (`claude mcp add`, user scope) - claude.ai Connectors UI needs the OAuth wrapper (not built).
  - Models verified per Ryan's THREE MODELS ruling: Grok $0.09 OK, GPT i2i $0.05 OK, Veo Fast $0.30 confirmed then retired with Veo Quality (can't take refs) and Z-Image (1k char cap). Seedance payload fixed (first-frame only, aspect threaded) - NOT yet live-tested.
  - GPT sheet 400s root-caused: OpenAI filter DENSITY scoring. Header reworded (fix8, pre-flight proven), builder text neutralized (fix9b). Caption-dense sheets still trip it.
  - Ledger proven to the cent vs Kie credits; Est→Actual chip live. Stripe env repointed to the new $29/$79/$199 prices; AGENCY price existed nowhere before today.
  - El Mercado (467dc9cc, PocoAPoco) created via MCP chat, scripted (5 scenes, ready_for_voice).

## Next action (start here cold)
Build the sheet AUTO-SPLIT chunk: when a storyboard sheet draw fails with the zero-credit
filter signature (failCode 400 + creditsConsumed 0, both known failMsg strings - see
`_sheet_filter_reject()` in storyengine/backend/scripts/coverage_to_app.py), split the sheet
into two smaller boards (panel counts already vary) and redraw each - halves caption density
per request, captions stay verbatim. Dispatch one Sonnet worker with trace-first brief; test
via the VPS probe recipe (failures are free). Then have Ryan draw the Spanish video
(cd5d2883) sheets that still fail (scene 2).

## Open threads
- Seedance live clip test (~$0.60) - blocked on the Spanish video reaching pictures; payload fix deployed but unproven.
- billing.py LIMIT-1-no-ORDER-BY x3 (incl. token MINT gate) - same bug fix10 fixed for authenticate_with_standing.
- Pipeline SSE stream resolves home tenant only (same class as fix12) - needs minted SSE token + frontend change.
- OAuth wrapper for claude.ai/phone connectors - unlocks the Connectors UI path.
- MCP paid-verb confirm failure silently re-quotes - agents misread as "started"; return an explicit confirm_failed error.
- research/script stages write NO generation_ledger rows (thinking spend untracked).
- agent_tokens.created_by migration (standing should follow minting account).
- Voice fixes (stash): targeted regen no-ops + full-run status regression (rendered -> ready_for_image_prompts).
- youtube_quota toordinal bug: guard reads fail, assumes 0 used - quota ceiling unenforced.
- UX papercuts: model badge lag, retry label quotes wrong price, failed redraw shows no toast, login drops on deploy restart.
- Ryan owes: rotate the agent token he pasted into chat (Settings -> Agent access); name the $79 Stripe price, archive $50/$100; easyspanish92@gmail.com was comped to plan='pro' (deliberate).

## Gotchas learned this session
- OpenAI's image filter scores accumulated word density (threshold-y, flips near the line); failed createTasks cost 0 credits so bisection/pre-flight iteration is free.
- claude.ai/Desktop "Connectors" UI is OAuth-only - bearer-token MCP servers connect via `claude mcp add` only.
- Claude Code's MCP client requires notifications/initialized -> 202 (bare JSON-RPC "Unknown method" error kills the handshake silently).
- Kie Seedance: reference image and first/last frame are mutually exclusive scenarios.
- Media-proxy tokens: browser session JWT resolves the HOME tenant only (pre-fix12); Kie-facing URLs need mint_media_token + .png suffix.
- se db is read-only by default; writes need `se db --write`. public.videos title column is `video_title` (a youtuber_bak schema shadows `videos` with a `title` column).
