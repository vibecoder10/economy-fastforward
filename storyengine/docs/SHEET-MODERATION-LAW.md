# Sheet Moderation Law

Storyboard sheets and character/cast reference sheets both go through GPT
Image 2 (`gpt-image-2-image-to-image`). OpenAI runs two moderation passes on
that call: an input-stage filter and an output-stage filter. The input filter
is deterministic - the same bad input fails the same way every time. The
output filter is stochastic near its threshold - the exact same prompt can
fail several times in a row, then pass unchanged on a later try (proven live,
2026-07-20/21: a board failed 13 times, then passed with nothing changed).

This doc is the settled law, not a debate. If a future session sees a sheet
failure, check this list before writing new code. Ground rules first, then
the evidence, then the operations rules that keep the ladder honest.

## The Law

1. Storyboard sheet images never bake dialogue captions into the picture.
   The spoken line lives only in the saved coverage plan.
2. Character/cast reference sheets and storyboard sheets carry no text of
   any kind - no name, no labels, no captions, no letters. The filter reads
   text inside reference images, so a clean, text-free sheet is law for
   every channel, not a per-channel choice.
3. Style text never carries a trademarked studio or brand name. Describe
   the look (medium, form, light), never the studio.
4. A risky prop gets named plainly in exactly one place, the FIXED SET
   line. Every other mention in the sheet prompt is neutralized.
5. Sheet headers use plain-sentence phrasing. Never an ALL-CAPS block
   header.
6. New-format (AXIS) storyboard sheets draw a hard maximum of 6 panels per
   sheet, in balanced boards, from one boundary function every caller
   shares.
7. A board that fails with a known zero-credit moderation signature - 400
   "could not be processed" / "content polic-" / "violat-", or 422
   "flagged as sensitive" / "sensitive", with 0 credits consumed - gets a
   free fallback-header retry, then up to 3 free re-rolls of the primary.
   This is because the output filter is stochastic near its threshold, not
   because the prompt is wrong.
8. A transient Kie 500 ("Internal Error", 0 credits) and a reference-image
   fetch failure both get their own free retry rungs. Both are infra flake,
   never moderation, never a reason to touch the prompt.
9. A credit-consuming failure is never retried. Retrying would just spend
   money re-drawing the same doomed prompt.
10. Every board failure is classified and stored per beat (never a silent
    empty slot) and shown to the creator as a chip in the UI.
11. Sheets draw on GPT Image 2 ONLY - nano-banana-2 is banned from boards.
    (Ryan, 2026-07-21 evening, reversing that same morning's nano-sheets
    ruling after reviewing a full video of nano boards: nano dodges the
    filter but loses character identity - boards drifted photoreal against
    the channel style and one board invented an entirely different cast
    with clean cast refs attached. "I actually really hate all of these
    nano banana boards... we will stick to gpt image 2.") Every sheet draw
    passes `no_nano_fallback=True`; a board that exhausts the free ladder
    fails clean into rule 10's error chip, never onto nano.
12. Filter risk is handled at the SOURCE, not by switching models: no
    weapons, knives, scissors, blades, sharp tools, violence or threat
    anywhere in generated content. Enforced in the script engine template
    (VISUAL CONTENT SAFETY section), the coverage planner (rule 7 in
    `_coverage_system_prompt`), the environment generator (exclude slot +
    location-extraction instruction), and PocoAPoco's tenant script prompt
    (rule 7). Food appears already prepared; hands hold spoons and wooden
    utensils; conflict lives in dialogue and reactions. Rule 4's
    neutralizers remain the backstop for legacy stored text. Root evidence:
    a knife GPT staged by its own liberty on a kitchen env ref (it was in
    no description) rode into every Scene 1 shot of video cd5d2883 as a
    reference image and randomly tripped the output filter all run long -
    the drawn IMAGE is the trigger, so the object must never exist.

## Evidence

**Rule 1 - no baked captions.** `96b7e788` (dialogue captions were the
surviving filter trigger on dense Spanish-lesson sheets; captions are
protected spoken script that can't be reworded, so they were removed from
the sheet image entirely and left in the plan).

**Rule 2 - no text on reference sheets.** Established doctrine from the LEO
sheet failure (a labeled, text-heavy character sheet was a proven failure
source). Enforced in generation code same-day in
`routes/characters.py::_generate_portrait` (used by both the per-video
character flow and the channel cast generator in `routes/projects.py`) -
see this session's diff.

**Rule 3 - no studio names in style text.** `b03b50eb` (a trademarked studio
name in the style prompt read as an IP/policy reference to GPT Image 2 and
400'd; removing it flipped a reliably-failing board to a clean pass with
nothing else changed). `_neutralize_style_brands()` is wired into
`_resolve_style`, the one seam every image path reads style from.

**Rule 4 - single-naming for risky props.** `2153fe59` (the chef's-knife
case: sheet 1 named the knife once in FIXED SET and passed; sheet 2 on the
same scene named it again in the camera kit and nearly every panel brief,
and 400'd on accumulated risky-prop density). `_neutralize_risky_props()`
strips every mention outside the one canonical slot.

**Rule 5 - no ALL-CAPS headers.** `8bf5fd42` (the old ALL-CAPS "PRODUCTION
STORYBOARD SHEET" header deterministically 400'd standalone, taskId
`cdb23fdc`; a plain-sentence header passed standalone and with a full real
sheet body).

**Rule 6 - hard 6-panel cap.** `6076c45b` and `47c9499a` (9-panel 3x3 sheets
reliably tripped the density filter - proven on the Spanish Class video
where every holdout board was a 9-panel sheet; a 7-panel board on the same
scene drew clean). `panels_per_sheet_for` is the one boundary function every
caller reads.

**Rule 7 - stochastic output filter, free re-roll ladder.** `b03b50eb`
(free re-roll on the zero-cost filter signature, gated so it never touches a
credit-consuming failure) and `4aa4336d` (60 failures ground-truthed one by
one against Kie's own record-info API: zero were timeouts, zero were rate
limits, zero were abandoned-but-succeeded; 100% were genuine zero-cost
moderation rejections, and the 422 "flagged as sensitive" class, taskId
`9b5af734f2455c8cbf39422142396051`, was added to the same gate).

**Rule 8 - transient infra gets its own ladder rung.** `4891c218` (Kie 500
"Internal Error" hit 4 of 7 recent sheet failures on Seedance-launch day;
new `_sheet_transient_kie_error` predicate, 15s breather, never the
fallback-header retry since a 500 has nothing to do with prompt wording) and
`0804572b` (a reference-image fetch failure was Kie failing to download a
reference because the media proxy shares the backend process with another
channel's parallel renders and times out under load - transient infra, not
moderation; refs were exonerated with 58 minutes of token slack still on the
clock).

**Rule 9 - never retry a real failure.** Repeated as a load-bearing guard
in every retry predicate (`2153fe59`, `b03b50eb`, `4aa4336d`): the 0-credit
check is mandatory and must never be loosened.

**Rule 10 - per-board failure surfacing.** `6d25d089` (migration 113,
`storyboard_errors` jsonb column keyed by beat number; failure class/code/
message/attempts stored, cleared the moment a board lands; the Scenes UI
shows a red chip with the raw message on hover instead of a blank slot) and
`0804572b` (the ref-fetch class gets its own chip label, "ref_fetch",
instead of falling into "unknown").

## Operations rules

- **Never deploy during active generations.** A deploy kills the backend
  process, which kills every in-process background task with it, including
  a paid picture or video run mid-flight. `scripts/vps-deploy.sh` now
  refuses to deploy while the backend reports active tasks, unless
  `--force` is passed.
- **A `kill -9` restart strands `generation_claims` rows.** Killing the
  backend process does not release claims held by in-flight work. Delete
  stale rows by hand after an unplanned restart, or they will block a
  later attempt from acquiring the same lane.
- **`PYTHONUNBUFFERED=1` is required for truthful logs.** Without it,
  Python's stdout buffering can delay or reorder log lines under load,
  which misleads exactly the kind of live-log debugging this doc's evidence
  came from. Every canary service sets it; any long-running StoryEngine
  process should too.
- **Kie's docs list envelope codes only.** The `failCode` inside a task
  record is the upstream OpenAI error, not a code Kie's own docs enumerate.
  Don't try to look up a `failCode` like 400/422 in Kie's API reference and
  conclude it's undocumented or wrong - it's OpenAI's code, passed through.
