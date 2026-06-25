# HANDOFF - StoryEngine v2 director pass (start here, cold)

(The prior chat-first-producer handoff is preserved as `HANDOFF.md.bak-20260624-222018`.)

You are picking up a full correctness pass on StoryEngine. Read these three, in order, before
touching code:
1. `storyengine/GOAL.md` - the plan (root cause, 9-subsystem state table, grok-imagine rules,
   Phases 0-10, the acceptance gate).
2. `storyengine/AUDIT-2026-06-24.md` - the receipts (every gap with file:line evidence).
3. Memory: `storyengine-goal-v2-director-pass` (the one-paragraph version).

## The prime directive
There is ONE root cause: two parallel pipelines drifted apart, and the live "coverage" path is
missing the old "grid" path's director machinery. **Do not patch symptoms on whichever file you
land on.** Unify on the coverage path first (Phase 0), then port machinery INTO it. Every claim of
"done" must be backed by a REAL run (a screenshot or a DB query), never a self-test - a broken
self-test asserting a stale string is exactly how this codebase accumulated fake "fixed."

## Guardrails (do not cross without Ryan)
- **Work on the branch `feat/director-pass`** (created off `feat/chat-first-producer`/`main`). Do
  NOT push risky pipeline changes to `origin/main` or deploy them to the live VPS while Ryan is
  away. Plan-doc commits to main are fine; code that changes what users see is not.
- **No spending.** Every paid step (image gen, clip gen, render) is Ryan's call. The only
  authorized spend is the Phase 10 Scene-1 proof, and only after Ryan eyeballs the storyboard.
- **The acceptance gate is Ryan's eyes.** Phase 10 does not "pass" on code logic; it passes when
  Ryan sees a Scene-1 storyboard that shows the angles, progresses the story, and defines
  characters + scene well.

## Environment cheatsheet
- Local repo: `~/economy-fastforward`. StoryEngine in `storyengine/backend`, `storyengine/frontend`,
  and `skills/video-pipeline`.
- Prod: `ssh storyengine-vps`. Deploy repo there: `~/projects/economy-fastforward` (branch `main`).
- DB URL on the VPS (read-only checks): `export DATABASE_URL=$(tr "\0" "\n" <
  /proc/$(pgrep -f uvicorn | head -1)/environ | grep ^DATABASE_URL= | cut -d= -f2-)`; run queries
  with `./venv/bin/python` from `storyengine/backend`. No `psql` on the box.
- Owner tenant: `ee93e6d1-a9cc-44c3-81e9-84adee8329aa` (ryan.ayler@gmail.com, plan `unlimited`).
- Deploy flow (only when Ryan approves): push `origin/main` from local -> on VPS `git fetch` +
  `git merge --ff-only origin/main` -> `npm run build` (frontend only) -> `kill -9` the uvicorn
  MainPID (SIGTERM hangs) and let systemd revive it -> confirm `/api/health` 200.
- Verification reality: local preview CANNOT reach authed pages. For frontend changes verify with
  `tsc` + `next build`; for backend with `py_compile` + the unit tests under
  `skills/video-pipeline/tests` and `storyengine/backend`. True behavior proof needs a (gated) prod
  run.

## Execution order
1. **Phase 0 - unify on coverage** (keystone). Until this is done the other phases have nowhere
   solid to land. Includes the false-proof cleanup (broken self-test, stale comments, lying
   docstrings).
2. **Phase 1 - data foundation** (route onboarding + model-a-video through the YouTube Data API;
   fail loud on missing key; stop writing views=0 rows; purge zero rows). Well-scoped, low-risk.
   Can run alongside 2/3/4.
3. **Phases 2, 3, 4** - director chat intelligence / style detect->apply / length from the
   specific modeled video.
4. **Phases 5-9** - port the director machinery into coverage: story progression, per-shot
   timing, grok-imagine motion + @image, character lock + 1-per-scene, environment lock.
5. **Phase 10** - the Scene-1 proof (Ryan's eyes + the only authorized spend).

Each phase in GOAL.md has its own root fix, file:line targets, and a proof step. Follow them.

## Definition of done (per phase)
- Code changed at the ROOT (not a new band-aid layer), builds/tests green.
- A real proof captured (screenshot or DB query), recorded in the morning report.
- The change committed to `feat/director-pass` with a clear message.
- GOAL.md phase tag flipped from `[todo]` to `[done <date>]` (or `[blocked: ...]`).

## Morning report (leave this for Ryan)
At the end of the session, write a short report at `storyengine/HANDOFF-REPORT.md`:
- What got done (per phase), with the proof for each.
- What's staged on `feat/director-pass` and ready for his review + deploy.
- What's blocked and why (be honest - "coded but unverified against prod" is a valid status).
- The exact next action for him (e.g. "review the branch, deploy Phase 0, then run the Scene-1
  proof for the spend").

## Do NOT
- Mark anything "done" off a code smoke test.
- Delete the old grid-path code before its replacement is proven; redirect first, delete last.
- Deploy to live prod or spend money while Ryan is asleep.
