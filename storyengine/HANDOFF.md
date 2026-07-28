# HANDOFF - 2026-07-28 D3 Chat surface and spend fixes shipped to production

## Where Things Stand

Main is at `23d0a47e`, pushed to origin, and deployed to production. Backend suite: 43 failed / 3476 passed / 1 error - the 43 are pre-existing, always compare failing test NAMES not counts to identify regressions. Three deploys on 2026-07-27 and 2026-07-28: 865d0be5, ceef025c, 23d0a47e. Roughly 19 fixes shipped, all merged to main and deployed.

## What Shipped This Session

Chat column layout is now correct - composer pinned at the bottom with no sideways scroll at any width, progress card updates in place instead of stacking (D3-1). Chat survives a refresh via a real `/chat/[videoId]` URL route, rehydrates history and progress, never drops you into the old pipeline screen (D3-2). Front door now sends `explicit_verb: "build"` so it starts a whole video instead of just a script (D3-15). Script quality rejections surface in plain English instead of silent status (D3-12). Stepper reads real per-stage state instead of faking it from coarse video status (D3-12). Voice failures actually stop the pipeline instead of billing for silence (D3-13). Dead controls look dead and the fake clone-a-video mockup is gone (D3-11). Character, environment, and five other paid paths are all metered and capped through one shared helper in actions.py (D3-16, D3-19). Storyboards no longer hidden behind a voice lock (D3-17). Chat cannot freeze silently - 16 of 129 conversations across two tenants were stuck, now fixed with 30s/90s timeouts (D3-18). Approval gates pause the build chain and ask for confirmation instead of auto-running (D3-20). Chat knows which shot or character is selected so editing applies to the right thing (D3-5 partial). Build offer card survives video creation (D3-27). Progress card stops lying about activity on videos with zero spend (D3-28). New videos open on the Scene board instead of a broken "Shot view - not designed yet" screen (D3-29). The "Open it" escape hatch to the old pipeline UI is gone from the chat; it's one unified window with no inner scroll on the script card (D3-30). Gates ask real questions and accept typed answers; a rejected script speaks up in the chat (D3-30). Results land one by one as they complete instead of jumping from empty to all-at-once (D3-31). The production guide shows real per-item counts as a plain "2/8 done" caption (D3-31).

## The Two Rules That Matter Most

1. **You drive the UI yourself and form your own verdict.** A worker saying "Pass" is an input, not a verdict. Ryan set this explicitly on 2026-07-27 after a day where he said "I havent seen you do anything tbh". Every screenshot that matters gets saved to disk and sent to you. Never skip this - synthetic events and green tests prove only that code runs, not that it works for a human.

2. **No paid generation without your explicit yes.** Deploys need separate approval each time, and prod must be quiet first because a restart kills in-flight customer builds. Three workers lost user builds by deploying during peak hours. Always check the clock and the queue depth before touching the restart button.

## Known Broken Right Now

- D3-39: Video header shows "Untitled video" while the database has the correct title.
- D3-40: "Loading this video's production map..." stuck permanently in chat and never resolves.
- D3-41: Adding a NEW character or inserting a NEW scene from the chat does not exist - only editing existing ones.
- D3-42: Free-text gate approval is UNVERIFIED on production; needs either a zero-cost gate or explicit spend approval.
- D3-43: The rejected-script chat message is UNVERIFIED live; verify on the next rejection.
- D3-44: Transient "Couldn't load this video" flash in the header on rapid navigation, possibly a fetch race.

## Hard-Won Gotchas a Fresh Session Must Know

- **`git stash` is shared across all worktrees in this repo.** Two workers stole each other's work by stashing in different worktrees and popping in a third. Never use it; use `git diff > /tmp/x.patch` plus `git checkout -- <paths>` instead.

- **A clean git merge is NOT proof.** Three times, git reported no conflicts and the combined behaviour was still broken. Always run the tests, always walk the app after a merge.

- **When a code path is replaced, its guards do not come with it.** A March guard on image spend was left behind when images moved to a new coverage path. Character generation exists in THREE independent implementations, all missing the same ledger write. Search the entire codebase for your guard, don't assume it moved.

- **Check WHICH TAB you are screenshotting.** Three false bug reports came from photographing a stale tab that already had the page open. Open fresh every time, or use the production URL in your screenshot to prove it's live.

- **The backend cannot run locally - the DB credentials are rotated.** Use `scripts/se.sh devtoken` and run the frontend locally against the PROD API. CORS only allows localhost:3000 and :3001, which is a real bottleneck with parallel workers. A better option nobody used: run a scratch backend on the VPS where the credentials work.

- **Workers repeatedly end their turn waiting on a background test run.** Tell them to block in the foreground or poll. Don't leave a session hanging on a background process.

- **For hunting bugs in the SHIPPED product, use Ryan's own Chrome against prod, not a local dev server.** Local dev points at prod anyway; if it's a prod-only bug, you need to see it there.

- **Do not close a bug just because a worker cannot reproduce it. Two bugs were wrongly closed today and one of them (D3-39) turned out to be real and visible on prod. Ryan sees the product more than any worker does.**

## Next Up

D3-30 and D3-31 are in flight. D3-30 is removing the "Open it" escape hatch and making the chat one unified window with talking gates. D3-31 is adding a cool progress spinner and landing storyboards/characters/scene images live as they complete.

After those, D3-32 through D3-34 are small real bugs: stepper clips at the right edge, toast text overlaps, canvas/rail panels throw on stubbed data.

Then D3-35 through D3-37 need your decisions: channel-scoped character generation cannot be metered (design call), what to do about tenant tgb29's silent video, nginx timeout change on the VPS.

D3-38 is a known money invariant drift: Custom Film keeps its own duplicate of the ledger write instead of using the canonical path.
