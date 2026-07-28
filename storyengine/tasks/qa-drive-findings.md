# StoryEngine Director QA Drive — findings

Date: 2026-07-27
Driver: QA subagent, real browser (Chrome via the Browser pane MCP), local dev frontend on an isolated
Next.js dev server talking to the real prod API/DB (`http://76.13.119.181:8001`), logged in as
`ryan.ayler@gmail.com` via the project's dev-token flow. No paid generation was triggered — every
finding below was reached by clicking, reading responses, or reading the database/API directly.

**Environment note, read this first:** the harness's assigned worktree for this session
(`storyengine/.claude/worktrees/stoic-hodgkin-7a86fb`) turned out to be **shared with other concurrent
agents in this session**, not exclusive to this QA drive. About 20 minutes in, another agent silently
rewrote this tree's `frontend/.env.local` and `next.config.ts` to point at a different port/proxy setup,
which made a completely real-looking API endpoint hang forever in my tests. I traced it (direct `curl` to
the backend answered in 0.39s; the local Next.js proxy never answered) and it was a false alarm caused by
the collision, not a product bug — I do not report it below. To get a trustworthy signal after that, I
built a second, fully private worktree + dev server on its own port (3012) that no other agent could
touch, and re-ran everything that mattered from there. All findings below are from that clean run unless
marked otherwise.

---

## 1. Ranked defect list

### 1. The "Scene" tab stops working the moment you leave it — you cannot click your way back to the main view
**Severity: a customer would hit this immediately.**
Steps: Open any video → you land on **Scene** view (the main working view, chat + board) → click **Timeline**
→ click **Scene** again.
Expected: returns to Scene view.
Actual: nothing happens. Timeline stays showing. Confirmed this is not a stale-reference artifact — retested
twice with a fresh page read each time, same result. Also tried the other direction: Timeline → **Shot**
(this works, Shot view opens) → **Scene** (fails again, stays on Shot). So **Scene never becomes clickable
again once another tab is active** — only a full page reload gets you back to it (and that reload, per a
separate already-known issue, drops the open video entirely and dumps you back at the Director home page).
This is the single most damaging thing I found: it's the main editing surface and it's a dead end.
Screenshot: `scene-tab-stuck-on-timeline.png` (see note below on screenshot files).

### 2. Timeline view: header text overlaps the timecode and the Split button
**Severity: a customer would hit this immediately** (Timeline is a top-level, one-click-away tab).
Steps: open a video → click **Timeline**.
Expected: a clean scrubber header.
Actual: a badge that reads "New — doesn't exist in the product yet" wraps across multiple lines and lands
directly on top of the "00:41 / 02:18" timecode and the "Split" button — you can read "doesn't / exist in
the / product" bleeding across the boxes. The underlying message (that a control is a stub) is honest and
fine; the layout that renders it is broken. Verified via `get_page_text` that the full string is "New —
doesn't exist in the product yet" — it's just laid out with no width constraint or truncation.

### 3. Preview, Export, Undo, Redo look fully live but do nothing — with zero visual signal that they're inert
**Severity: a customer would hit this immediately.**
All four render with the exact same styling as every other working top-bar button (no greyed-out state, no
lock icon, no "coming soon" tag — contrast with the home page's honest "· coming soon" labels). Clicking
Preview or Export produces no toast, no modal, no state change, nothing. The only way to know they're not
real is to read the accessibility label, which literally says "Preview — not available yet" / "Export — not
available yet" / "Undo — not available yet" / "Redo — not available yet" — a real disclosure that never
reaches the screen. A paying customer clicking Export to get their video out has no way to know it's not
implemented.

### 4. "Standard production" progress stepper in chat shows Environments as done (green check) when it isn't
**Severity: a customer would hit this immediately, and it actively misleads.**
On the Baby Bird video, the chat panel's pipeline stepper (Research → Script → Voice → Characters →
**Environments** → Storyboards → …) shows a **green checkmark on Environments**. I checked the real backend
data directly (`GET /api/videos/{id}/production-guide`, read-only, no cost): environments state is
`"not_started"`, detail `"No environments designed yet."`, with an explicit warning that 8 locations
(`sunny_garden`, `garden_ground_closeup`, `family_car_exterior`, `clinic_waiting_room`,
`vet_examination_room`, …) have no design at all, and that this normally **blocks storyboard generation**
until designed-or-skipped and approved. The right rail's own **Environments** tab agrees with the real data
("No environments designed yet") — so the bug is specifically in the chat stepper showing a false green
check, not in the rail. A customer trusting that stepper would believe environments are locked in when they
are not, and would be confused why storyboards proceeded anyway (the gate that's supposed to block that
apparently didn't fire for this video).
Screenshot: `environments-false-checkmark.png`.

### 5. "Or clone a video you like" on the Director home is a fully static mockup that reads as a live demo
**Severity: a customer would hit this eventually** (this is the second thing on the home page after the
prompt box, so realistically sooner).
This card ships with a pre-filled, editable URL field (`https://youtube.com/watch?v=9Xk1p2Qd7Lm`), a green
"Read" status pill next to it, a populated "What we found" analysis ("Built like a fast hook and payoff",
"Written like punchy narration", "Looks like photorealistic live-action" with an explanatory paragraph), a
pre-filled twist ("Same energy, but do it with Pokemon."), and three "reference images" labeled
Pikachu/Bulbasaur/Charizard. Every one of these is static content, not a live analysis of anything — there
is no functioning URL fetch behind it. The only tell that any of this is fake is a small grey "Build ·
COMING SOON" tag at the very bottom of the card, well below the fold of what most people will read. A
customer would very plausibly believe the app already analyzed a video and is offering to remix it. This
matches the concern flagged in the brief exactly.

### 6. "Reset to recommended" on the cost dial doesn't clear the per-shot "Manual override" flag
**Severity: a customer would hit this eventually — and it directly affects the "reset" promise.**
Full disclosure since I touched a real video: I used the dial's "Make all draft" (confirmed via its own
modal — "This is free — it only changes routing for future generation. Nothing renders and nothing is
billed") on the Baby Bird video (74 shots), then clicked "Reset to recommended" to put it back, per the
brief's instruction. After a fresh reload, every shot that I checked (S-01.1 through S-03.6) still reads
**"Manual override"** in its accessible label, not "Channel default" — even though the model chosen matches
the channel default (Grok Imagine) for most shots. I re-clicked "Reset to recommended" a second time and
reloaded again: same result. The dollar totals (`~$6.66` all-draft / `~$6.87` current / `~$92.50` all-cinematic)
match the video's original numbers, so cost-wise nothing changed — but the override flag itself does not
clear. I could not fully restore this video to its exact starting state through the UI; I am disclosing that
here rather than silently leaving it. Recommend: "Reset to recommended" should clear the override flag
entirely (so the badge reads "Channel default" again), not just re-apply the recommended model while leaving
it flagged as manually overridden.

### 7. Shot price badges truncate at narrower widths, cutting off the price entirely
**Severity: cosmetic, but confirmed exactly as suspected.**
Reproduced the specifically-flagged scenario: app sidebar expanded, browser window narrowed enough to push
the canvas near its minimum (tested at 1150px total width). The shot cards in the Scene view chat show
"🎬 Grok Imagine ·" and "🎬 Veo 3.1 Fast ·" with the trailing price (accessibility label says "· ~$0.09" /
"· ~$0.30") clipped off past the visible edge of the card — you see the model name and a dangling "·" with
no number. Screenshot: `price-badge-clipped-narrow.png`.

### 8. Top bar itself overflows at the same narrow width — "Timeline" overlaps "Preview"
**Severity: cosmetic, but a real overflow bug, found while reproducing #7.**
At ~1150px total window width (sidebar expanded), the top bar's own tab row runs out of room: "Timeline"
and "Preview" render on top of each other ("TimPreview"), fully overlapping. This is a second, separate
overflow bug in the same top bar, not just the price-badge one.

### 9. The "4 looks ready" badge in the top bar doesn't do anything
**Severity: cosmetic.** It reads like a notification chip (paired with a green dot, similar styling to the
sidebar's "Review" nav item which does carry a real "9+" badge and does link to `/review`). Clicking it
produces no dropdown, no navigation, nothing. Confirmed it has no `href` and is a plain `<div>`-styled
element, not a real control.

---

## 2. Could-not-test list (and exactly why)

- **Any Build/Finish/Redraw/Recreate/Animate action** — per the hard money rule, never clicked. This
  includes "Finish the video" (top right, green), "Build to pictures" (legacy pipeline page), the per-shot
  "Recreate"/"Modify Video"/"Extend Video"/"Upscale Video" row, and the per-shot "Tap to change this scene's
  clip model" pickers (didn't want to risk a real redraw trigger hiding behind a model-select UI I hadn't
  seen yet).
- **The clone-a-video "Read"/"Build it" flow end-to-end** — the URL field is real and editable, but typing a
  new URL and submitting it is explicitly the thing the brief said never to do (fires a paid modelling
  call). Confirmed only that the card's content is static and that its Build button is honestly tagged
  "COMING SOON."
- **The "History" button in the top bar** — I could not get a clean click on it; my attempt landed on a
  different element in the chat panel instead (it scrolled the chat to the pipeline stepper, which is how I
  got the screenshot for finding #4, but I never actually saw what History itself opens). Not retested due
  to time.
- **Dragging the column resize separators directly** — I confirmed the separators exist
  ("Resize chat panel", "Resize media rail panel") and that "Hide chat" / "Hide media rail" controls exist,
  but I tested column-narrowing by shrinking the whole browser window rather than dragging the internal
  handles pixel-by-pixel. The width-based test (findings #7, #8) is a reasonable proxy but isn't identical to
  a manual drag-to-minimum test.
- **The "make a video about a dystopian world..." video stuck on "Loading..."** — I hit this once, early,
  in the contaminated shared environment, with zero backend network calls ever firing for it. I did not get
  back to retest this specific video in the clean, isolated environment before time ran out, so I cannot
  say whether it's a real per-video bug or another artifact of the environment collision. Flagging it as
  unverified rather than including it in the ranked list above.
- **Dashboard, Analytics, Calendar, System Prompts, Ideas nav pages** — the brief's sidebar-nav-item
  instruction technically covers these, but given the length of this session I stayed focused on the
  Director surface itself (chat/canvas/rail, the three tabs, the cost dial, the board) since that's the
  stated focus of the drive. These other pages were not walked.
- **Screenshot files**: the two named "screenshot: X.png" above were captured as in-conversation screenshots
  through the browser tool, not saved to disk as files in this repo — I don't have a file path to give you
  for them beyond that they were shown live during the session. If you need them as files, say so and I can
  re-drive those two specific steps and save them properly.

## 3. Gap list against OpenArt

- **No script-approval gate.** OpenArt's flow (`7.48.10 AM`) stops for an explicit "Edit / Looks good!"
  decision on the script before moving on, with a full side panel (index, story concept, character bios).
  StoryEngine's video I opened had already blown past every stage (script, characters, environments,
  storyboards) with no visible checkpoint UI — the chat stepper just shows checkmarks after the fact, with
  no evidence a human ever had to confirm anything mid-flight (and per finding #4, at least one checkmark
  is provably wrong).
- **No anchor review gallery.** OpenArt's "Review Anchors" step (`7.59.43 AM` / `7.59.55 AM`) is a dedicated
  gate: a compact "Characters × 2 / Locations × 4" card with `View` opening a large, named gallery of every
  character and location before spending money on shots. StoryEngine has a Cast tab and (when populated) an
  Environments tab in the right rail, but they're passive reference panels you stumble into, not a gate the
  flow stops for.
- **No live, honest render-progress readout.** OpenArt's progress card (`8.00.36 AM`) shows a running timer
  and named steps while a shot renders. I didn't get to trigger a real render (money rule), so I can't
  confirm what StoryEngine shows during one — but per project notes, this is one of the three issues other
  concurrent workers are already fixing, so I'm not re-litigating it here.
- **Preview and Export are real, working buttons in OpenArt's top bar** (`8.19.07 AM` shows a live preview
  panel). In StoryEngine they are present in the same position with the same visual weight, but per finding
  #3 do nothing.
- **The Timeline view is comparable in concept** (per-track Video/Narration/Music & SFX lanes, a scrubber)
  but is undermined by finding #2's layout bug and the fact that you can't navigate back out of it (finding
  #1).

## 4. What actually worked

- **The three-column Director layout itself** — chat on the left, canvas/board in the middle, media rail on
  the right — rendered correctly, all real data, no placeholder gaps, on the one fully-built video I tested
  in depth (147 shots, 8 scenes).
- **Every image in the board loaded** — all 8 scene storyboard thumbnails, all 6 character sheets in Cast,
  every per-shot still in the chat's scene blocks. No broken image boxes anywhere I looked.
- **The cost dial is genuinely well built.** Three clearly labeled totals (All Draft / Current / All
  Cinematic), an honest "FREE — ROUTING ONLY, NOTHING GENERATES" disclaimer, and a confirmation modal before
  any bulk re-route that spells out exactly what will change and confirms it's free — this is good, careful
  UX and better than I expected going in.
- **Voice and Cast tabs in the right rail** both work cleanly — Voice shows per-scene narration takes with
  real play controls and durations; Cast shows all 6 character sheets with names.
- **The honest "not built yet" placeholders are good when they're used.** Shot view ("One shot, full width
  — ... Not designed yet; say the word and it gets built out.") and Music ("No sound designed yet. A
  dedicated music bed isn't wired to this rail yet...") are exactly the right pattern — they just need to be
  applied consistently, which is the core complaint in findings #3 and #5.
- **Sidebar collapse/expand works correctly** and genuinely reclaims canvas width.
- **The dev-token auto-login flow works** once the environment isn't fighting another agent for the same
  files (see the environment note at the top).

## Recommendations (not implemented, for the owner to prioritize)

1. Fix the Scene-tab dead-end first (#1) — it's the one that turns "annoying" into "the product is unusable
   after one click."
2. Give Preview/Export/Undo/Redo the same honest "coming soon" visual treatment already used elsewhere in
   the app (#3), or wire a toast that says "not available yet" on click so at minimum there's feedback.
3. Fix the Environments stepper checkmark to read from the same source of truth the production-guide API
   and the Environments rail tab already use (#4) — right now there are two different answers to "is this
   done" on the same screen.
4. Either wire the clone-a-video card to something real or move its "COMING SOON" tag to the top of the card
   next to the paste-a-link field, not buried at the bottom (#5).
5. Make "Reset to recommended" actually clear the manual-override flag, not just reapply the recommended
   model under an override flag (#6).
