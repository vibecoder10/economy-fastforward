# StoryEngine Copilot UX Map — Two Doors for Every Feature

**Date:** 2026-07-17 · Companion to `tasks/storyengine-wiring-fix-checklist.md` and the Higgsfield gap analysis.

## The design law: Two doors, one registry

Every capability ships with BOTH doors, and both doors call the SAME verb in `backend/actions.py`:

1. **Clickable door** — a visible control on the page where the work happens (badge, chip, button, gallery). Discoverable, zero-typing.
2. **Conversational door** — the Producer (home) or co-pilot (in-video dock) understands natural phrasing for it, and eventually the same verb is reachable from OUTSIDE via the StoryEngine MCP server ("talk to StoryEngine from Claude").

A feature with only one door is incomplete: chat-only = invisible to browsers; UI-only = the co-creation partner "doesn't know about it" and trust breaks the first time it says "I can't do that" for something a button can do. This is the same wiring law as DB↔backend↔frontend, applied to interaction.

**Why this matters (from the teardown):** Higgsfield's biggest UX win is that a user can sit in Claude, talk like they're briefing a director, and the thing just gets made — model choice, framing, pacing all handled. StoryEngine's structural advantage is that our verbs already exist in one registry; Higgsfield had to build an agent product (Supercomputer) — we mostly have to *expose* ours.

---

## 1. Copilot Router (per-scene model routing) — checklist P1.1–1.2

**What the user experiences:** they never pick a model unless they want to. They describe intent; the system routes and *shows its work*.

### Conversational door
| User says | Copilot does |
|---|---|
| "Make the reveal at the end feel epic" | Tags scene as hero → routes Veo Quality → "Scene 12 is your reveal — I'll use Veo Quality there ($1.25). Rest stays on Grok. OK?" (confirm card) |
| "Why did scene 4 use Grok?" | Reads `routing_reason`: "It's connective b-roll — motion is simple, so I saved you $1.15 there." |
| "Use Seedance for all the dialogue scenes" | Scene-level overrides written for scenes tagged `character`; badges update; cost quote refreshes |
| "This is a big-budget one, don't cut corners" | Sets video routing bias to premium; re-quotes: "All 14 scenes on Veo Quality: $17.50 (was $4.20)." |

### Clickable door
- **ScenesWorkspaceTab:** every scene card carries a **model badge** (`Grok · draft` / `Veo Q · hero`) with a "why" tooltip. Tap badge → bottom sheet: the 4 wired models with best-for one-liners + per-clip price; picking one writes the scene override (override badge gets a dot so routed vs manual is visually distinct).
- **Build/confirm cards:** cost quote itemized by tier ("11 × Grok $1.10 + 3 × Veo Q $3.75"), not one blended number.

---

## 2. Draft cheap, finish expensive — checklist P1.3

**The user's mental model:** "sketch first, ink later." Never explain tiers unless asked.

### Conversational door
- "Let me see it first" / "rough cut" / plan approval default → **draft pass**: "I'll draft all 14 scenes on the cheap model — about $1.40 — so you can judge the story before we spend real money."
- After review: "Scenes 3, 7 and 12 are keepers, finish those" → **finalize verb** regenerates only those on their routed tier, quote first.
- Copilot proactively offers: "Happy with the pacing? Finalizing your 5 approved scenes costs $5.10 — the other 9 stay as drafts unless you approve them."

### Clickable door
- **GuidedNextStep** (the one-big-button): after pictures/animatic review its label becomes **"Draft the video (~$1.40)"**, then **"Finalize 5 approved scenes (~$5.10)"** — the workflow is IN the button text.
- Scene cards get **Approve** ticks (already exist for cast/environments — same pattern); Finalize only touches ticked scenes.
- Savings line on the confirm card: "vs $17.50 all-premium — you're saving $12.40."

---

## 3. Style gallery (5 rich profiles surfaced) — checklist P2.1

### Conversational door
- Producer LOOK selector card is rebuilt from `/api/style-presets` (same source as the gallery — kills the duplicated lists). "Something like a war-room hologram feel" → matches `holographic_hud`, shows its preview card "✨ Recommended", one tap to lock.
- "What styles do I have?" → carousel of preset cards with best-for lines and cost tier.
- "Make me a new style: watercolor but darker" → copilot drafts a custom style description, saves it as a **user preset row** (styles are data now), names it, and it appears in the gallery for reuse.

### Clickable door
- **Create flow + /pipeline form:** replace the 6-icon strip with the gallery grid — preview image, name, "best for", cost tier chip. Same grid lives in Settings → Styles for browsing/renaming/deleting user presets.
- **Video page:** current style shown as a chip on the header; tap → gallery sheet (locked once images exist, with "changing style requires re-generating pictures" warning + cost).

---

## 4. Camera moves as clickable presets — checklist P2.2

### Conversational door
- "Give the opening a slow push-in" / "crash zoom on the reveal" → copilot maps to catalog move, writes the shot's motion instruction, confirms: "Crash zoom on scene 1 — I'll re-animate that clip ($0.10)."
- "Make the camera work more dramatic overall" → router biases move selection toward high-intensity purposes; lists what changed per scene before regenerating.

### Clickable door
- **Scene card:** camera chip (`auto · push-in`). Tap → preset sheet grouped by purpose (Reveal / Scale / Establish / Payoff) with the move's one-line "best for". Picking one marks the chip `manual` and queues just that clip's re-animation with a price tag.
- Auto remains default — the chip makes the invisible "earn the move" system visible and correctable.

---

## 5. Cost ledger + budget — checklist P0.3, P3.3

### Conversational door
- "How much has this video cost?" → ledger read (free): "Actual spend so far $6.85: pictures $2.40, clips $3.90, voice $0.55. Finishing (thumbnail + render) adds ~$0.45."
- "Keep this under $10" → sets `max_spend`; every later quote shows headroom ("$2.60 of budget left"); autobuild halts with a "budget reached" card instead of silently continuing.
- "What did I spend this month?" (home Producer) → tenant-level ledger rollup by video.

### Clickable door
- **Video header:** `Est $8.20 → Actual $6.85` chip; tap → ledger drawer itemized by stage/model.
- **Create flow (advanced):** optional budget field; progress bar on the video page when set.

---

## 6. Research transparency + onboarding fixes — checklist P0.4, P0.5

- **Chat:** plan summary always states "Research: skipped — script writes from the topic. Want a research pass first (~$0.20)?" One-word "yes" enables it. Kie-only tenants get a working Producer (fallback client) with a soft "add an Anthropic key for sharper plans" hint, never a wall.
- **UI:** research chip on the plan card and pipeline stepper ("skipped — tap to run"); key-status pill in Settings → Keys already exists, link it from the hint.

---

## 7. NEW — StoryEngine MCP server: "talk to it from Claude" — the Higgsfield-killer door

**The feature the user asked for by name:** sit in Claude (or any MCP client), talk like you're briefing a producer, and StoryEngine makes the video — with our mapped shots, routed models, and YouTube publishing on the other end. Higgsfield proved this is a growth channel (their MCP launched 2026-04-30); ours is *better-shaped* because a session ends with a published YouTube video, not a downloaded clip.

### Architecture (thin by design)
- **`storyengine/backend/mcp_server.py`** (or `routes/mcp.py`, streamable-HTTP MCP endpoint): tools are generated FROM the `actions.py` verb registry + create/plan/status/ledger reads. One registry → three doors (buttons, chat, MCP). No logic in the MCP layer beyond auth + tool schemas.
- **Auth:** per-user StoryEngine API token (Settings → Keys → "Agent access") scoped to the tenant. BYOK carries through automatically — generations run on the user's own vault keys. This is the anti-Higgsfield stance: their MCP locks billing into their credits; ours passes true cost through.
- **Money gate preserved:** paid tools return a quote + `confirm_token` first; the agent must call `confirm(confirm_token)` to spend. Same `_estimate_cost` path as chat — no bypass door for spending.
- **Tool set v1:** `create_video(spec)`, `get_plan/approve_plan`, `list_scenes` (with routed models + reasons — the mapped shots ARE the conversation surface), `set_scene_intent/override_model/set_camera_move`, `draft_pass`, `finalize(scenes)`, `regenerate(shot)`, `get_status`, `get_ledger`, `upload_draft_to_youtube`, `get_performance(video)`.

### What co-creation from Claude looks like
> **User (in Claude):** "I want a 8-min video on why the Panama Canal is drying up, investigative tone, hero shot of the locks at night."
> **Claude → MCP:** `create_video` → plan back → shows title options + shot map ("14 scenes; scene 12 routed Veo Quality — your locks-at-night hero").
> **User:** "Swap scene 3 to a drone pull, and keep it under $8."
> **Claude → MCP:** `set_camera_move(3, drone_pull)`, `set_budget(8)` → re-quote → user says go → `draft_pass` → later `finalize` → `upload_draft_to_youtube` → "Draft is on your channel for review."
> Next week: **"How did the canal video do?"** → `get_performance` → "4.8% CTR at 48h — the hero-shot thumbnail is outperforming your average; want me to plan a follow-up in the same style?"

That last exchange is the moat sentence: an agent that can *see the YouTube results* of what it made. Higgsfield's MCP ends at the download.

### Checklist addendum (add to wiring checklist as P2.4)
- [ ] `[B]` MCP endpoint wrapping actions registry + read tools; per-user token auth; confirm-token money gate.
- [ ] `[D]` `agent_tokens` table (user, tenant, scopes, created/revoked).
- [ ] `[U]` Settings → "Agent access": create/revoke token, copy MCP config snippet, per-token last-used display.
- [ ] `[U]` Activity attribution: videos/actions created via MCP show an "via agent" chip in the UI so web users aren't surprised by ghost activity.
- [ ] `[V]` From Claude Code with the MCP configured: full loop above on a test tenant — create → route → draft → finalize → upload draft — with every paid step quote-gated, ledger rows written, and the video visible in the web UI with correct badges.

---

## Conversational quality bar (applies to every door-2 flow)

What "just talk to it and it makes what you want" actually requires — test scripts for each feature's chat door:
1. **Intent over vocabulary.** "Make it cheaper" must work without knowing the word "Grok". "More cinematic" without knowing "Veo".
2. **Show the work, then act.** Every routing/spend decision is narrated in one sentence with the price BEFORE it runs (existing money-gate pattern — extend, don't fork).
3. **Everything the UI shows, chat can read; everything chat does, the UI reflects live** (badges/chips update via existing SSE — no "chat did something invisible").
4. **Undo is a sentence.** "Put scene 3 back the way it was" reverts the override (state kept per-scene, not destructive).
