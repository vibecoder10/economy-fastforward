# Director Phase 1 - Post-Deploy Verification

Four items built and wired but not verifiable in this sandbox. Exact proof level reached and test recipes below.

## Deploy 2026-07-26 (evening): LANDED and VERIFIED

`main` was fast-forwarded to `feat/director-chat`'s tip (`28afc1f4`, which already contained
`origin/main`'s `cd7b7d80`), pushed to `origin/main`, and deployed to prod with
`se deploy osiris-director-chat-unify --with-frontend`. Health gate was clear before deploy
(`active_work.total: 0`, no deploy lock). Deploy completed clean: migrations 147/147 applied (0
pending), backend + worker + frontend all came back healthy, drain returned to normal. Checks 1
and 2 below are now CLOSED with real evidence. See `HANDOFF.md` for full deploy log.

## Deploy attempt 2026-07-26: BLOCKED by merge conflicts, checks below NOT run

Gate check `git merge-base --is-ancestor origin/main feat/director-chat` returned `1` (branch does
not contain main's tip). `origin/main` had moved 109 commits past the branch's last sync point
(merge-base `8e7c495f`, 2026-07-24 22:05) up to tip `cd7b7d80` (2026-07-26 11:43), including 7
commits from today's Custom Film / Scene Control work. A test merge (`git merge origin/main
--no-commit --no-ff`) produced real content conflicts in `backend/main.py` (two different
`custom_film` router registrations — HEAD registers `custom_film.router` unconditionally,
`origin/main` registers `custom_film_scene_control.router` behind a `CUSTOM_FILM_SCENE_CONTROL_V1`
env flag — these are two different modules, not a formatting diff) and in
`tasks/deferred-verification.md` (both branches appended notes to the same section). The merge was
aborted (`git merge --abort`), nothing was resolved, and **no deploy was performed**. A safety
backup branch `backup/feat-director-chat-pre-mainmerge-20260726` was created pointing at the
pre-merge-attempt tip in case that's useful.

Because deploy did not happen, checks 1 and 2 below are still open and were NOT tested today.
Whoever resolves the `backend/main.py` conflict needs to decide whether both custom-film routers
should coexist (they may be two different, non-overlapping features) — that's a product/engineering
call, not something to auto-resolve.

## 1. `GET /api/custom-film/recipes` returning a live 200 — CLOSED 2026-07-26

**Verified against live prod after deploy `cd7b7d80` -> `28afc1f4`:**
```
$ curl -s -w "\n%{http_code}\n" -H "Authorization: Bearer $(cat /tmp/se_token)" http://76.13.119.181:8001/api/custom-film/recipes
{"recipes":[]}
200
```
Exact match to the predicted result. Also confirmed through the real frontend proxy (not just the
backend directly): a browser session at `https://storyengine.dev/` issued
`GET https://storyengine.dev/api/custom-film/recipes` -> `200` (seen in the browser's network
log), and `GET https://storyengine.dev/api/custom-film/17454567-0605-4249-8598-482b4240243e/scene-control`
-> `200` in the same session, confirming Codex's Scene Control route also still resolves through
the same deploy.

## 2. The saved-styles empty state rendering on screen — CLOSED 2026-07-26

**Verified live in browser** (signed in as the owner tenant `ee93e6d1`, storyengine.dev, real JWT,
not a stub): the "Your saved styles" section reads "0 saved" in the header, and shows a gold
dashed-border card with a star icon and the exact copy "You haven't saved a style yet", plus the
explanatory paragraph and "Lock this as a style" call-to-action. No red error box anywhere on the
page. Confirmed via `get_page_text` extraction and a visual screenshot. (Note: the tenant used
here has real production history — 4 "looks ready" and 13 recent videos — but 0 saved styles, so
this is a genuine empty state, not a fresh-account artifact.)

## 3. The Build button end to end — STILL OPEN

**Proof level reached (2026-07-26):** Confirmed present and rendered on a live video's canvas
("Below the Forecast") in prod: green "Finish the video" button, "THIS VIDEO $0.25" cost chip.
Deliberately **never clicked** — Ryan authorized zero downstream spend for this verification pass.

**Not checkable without spending money.**

**Test recipe:** On a real video with work pending, click Build/Finish, confirm the dialog, and check the cost ledger moves by the amount the confirm dialog quoted.

## 4. A populated Scene altitude view — STILL OPEN

**Proof level reached (2026-07-26):** Verified the altitude segmented control itself works
end-to-end in prod on "Below the Forecast" (a real, empty Custom-Film-Directed video: 0 scenes, 0
shots) — Shot/Scene/Timeline all switch state correctly and render distinct honest empty-state
copy: Shot view says "Not designed yet; say the word and it gets built out"; Timeline view renders
a static illustrative mockup of clip/narration/music tracks explicitly labeled "New — doesn't
exist in the product yet" (this is clearly marked as not-live-data, not a bug, but flag it as a
UX item — a real user could mistake the fake clip thumbnails for real content if they don't read
the label). Right rail tabs (Media/Voice/Music/Cast/Environments) all switch cleanly with
consistent "No X designed/recorded yet" empty copy, no console errors on any tab.

**Not yet checked:** an altitude view actually populated with real scenes/shots (this video had
none). A full visual check against the mockup's populated Scene view was not done.

**Test recipe:** Open a video with several scenes and drawn shots. Compare the scene rows and shot tiles against the mockup's Scene view at `tasks/director-mockup/index.html`.
