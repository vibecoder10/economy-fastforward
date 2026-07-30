# D6-6a dry run — what's in this folder

This is a $0 test. Nothing here was drawn. These are four text files you can paste,
one at a time, into a free image tool (ChatGPT, Gemini, whatever you'd normally
hand-tune boards in) to see what the pipeline WOULD draw, before we pay for it for
real.

## The four files

There are two "paths" through the code that can turn a scene into a picture
prompt, and they don't always agree — that's exactly why we're checking both.

- **`sheet-preview_scene1_escape.txt`** — the cheap $0.05 storyboard-sheet path,
  for the new escape scene (Nyla waking up, whispering, opening the hatch). One
  prompt, six small panels on one sheet.
- **`sheet-preview_scene4_elites.txt`** — same cheap path, for the elites-watching
  scene (the woman in gold and the old man).
- **`pictures-path_scene1_escape.txt`** — the real, full-price per-shot path for
  the escape scene. This one has six separate prompts in it (one per camera
  shot), each marked "SHOT 1 of 6", "SHOT 2 of 6", and so on. Paste them into the
  tool one at a time — each is a single finished frame, not a sheet of panels.
- **`pictures-path_scene4_elites.txt`** — same real path, five separate shots,
  for the elites scene.

## What to look for when you draw these

**On the escape scene (both files):** Does the pod read as PART glass, PART
solid white shell — never fully see-through, never fully opaque? Does the hatch
look big enough for a person to climb through standing up, not a tiny hole she'd
have to crawl through? Is there really only Nyla in every panel?

One thing to know going in: both files stop with Nyla still inside the pod,
about to press the hatch release. Neither one actually shows her stepping out
into the corridor — the scene's whole point (the escape itself) got trimmed off
by the shot-count budget before it could be drawn. That's a real gap in the
plan, not something for you to fix by hand — it's flagged below.

**On the elites scene (both files):** Look for exactly the woman in the gold
gown and the old man in the black dinner suit sitting right next to each other,
with three other elites in the background — never three interchangeable old men
in navy suits (that was the old bug). Is there a shot that shows both of them in
frame together at the same size (not just each one alone)? Does the giant screen
show the underground pods, and is it ever missing from a shot where the
description says the camera is standing between the row and the screen (it
should be — that's the screen's own light on their faces, not the screen itself
sitting behind them)?

One thing to know here too: the sheet-preview file mistakenly pulled in the
POD'S wall description instead of the elite hall's own wall description. That
happened because the elites' own scene mentions "her pod" (they're watching
Nyla's pod on the giant screen), and the code that decides "which room is this
scene in" got confused by that mention and picked the pod. The pictures-path
file does NOT have this problem — it has the hall's correct wall description.
This is a real bug, already flagged for a fix — see below.

## Bottom line

The core thing D6-6a was testing — does the room's real, locked-down wall
description and the real, locked-down cast descriptions actually make it into
the prompt, word for word, instead of the AI guessing — passed. You'll see the
same wall and cast text, unchanged, in both paths (except for the one
mismatched-room bug above, and the elites' cast names getting cut short in the
sheet-preview file's header). Two real defects came out of this test, both
already flagged separately for their own fix:

1. A scene's shot-count budget can silently drop the LAST beat of a scene when
   that beat is the payoff (the escape, in this case) — this hit both the sheet
   preview and the real per-shot picture prompt, so this isn't a fluke of my
   test.
2. The code that decides which room a scene belongs to can be fooled when a
   scene legitimately mentions a different location by name (like a screen
   showing a different room) — it picked the wrong room's wall description
   for the sheet-preview file.

Neither defect stopped this test from proving what it needed to prove; both are
worth fixing before we spend real money drawing full videos.
