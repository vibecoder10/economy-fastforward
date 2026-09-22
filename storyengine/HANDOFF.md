# HANDOFF - 2026-09-21 Research 20/20 verified + shipped; gold-standard scripts found; script-stage build starts next

## State
- Prod: `8d4f2583d` deployed, healthy (`se.sh health` clean, no lock). 2 doc-only commits landed after
  that deploy (`2a15110b`, `ff3d3faa`) - nothing to deploy for those.
- Branch: `main`, pushed and clean except pre-existing `frontend/next-env.d.ts` / `../tasks/decisions.md`
  (not mine, leave alone) and untracked `storyengine/jev-key-box.html` (not mine, leave alone).
- What shipped this session:
  - Deleted the invalid Anthropic key for "Designed vs Used"; proved the free relay photo judge live on
    a 4-machine proof video (`dc217efd-...`, safe to delete); subject-named image discovery confirmed live.
  - **Research 20/20 verified** on `6ac28204-...` ("Every US Submarine Class Ever Built"). Found + fixed a
    real matcher bug (labels with a trailing parenthetical, e.g. "Barracuda class (V-1 group)", could never
    match evidence) and a writer-brief size limit (unbounded relay answers failed 5/8 cards) - both deployed.
  - One rule everywhere now: key installed -> pipeline uses it (paid); no key -> the connected agent answers
    (free) (`agent_relay.relay_active`). Before this session the relay flag beat an installed key.
  - UI: Research "Approve Research" button now follows the real gate at 20/20 (was stuck on "incomplete");
    Gather panel shows real title, hides "Retry" at 100%, labels hand-placed photos.
  - New Run All target `research` (static docs only): roster -> images -> per-machine research, stops before
    script. "Run to Research" button added; Run All buttons no longer scroll off-screen on narrow layouts.
  - **Found the real gold-standard scripts** (my first DB-based guess was wrong, corrected by Ryan): pulled
    into `docs/gold-scripts/` from `~/Desktop/Projects/Designed vs used/`.

## Next action (start here cold)
Read `docs/gold-scripts/standards/DvsU_Script_Writing_System.md` first (its `SUMMARY CHECKLIST` at the end
is nearly a machine-readable grammar already), then `DvsU_Example_Paragraphs.md`. Before writing a parser,
resolve the open thread below (structural labels vs narration in some extracted `.txt` files) by opening one
of the ambiguous `.docx` files directly (e.g. `docs/gold-scripts/scripts/Every_US_Aircraft_Carrier_Ever_Built.docx`)
and checking its paragraph styles. Then write `script_grammar.json` (word count 95-120/paragraph, 24-30
paragraphs/video with a 15 floor, 4-7 acts, <=5 name-openers/video, the forbidden-pattern list, ends on the
final unit with no separate conclusion paragraph) plus a pure `check(script_text) -> violations`, validated
against all 14 gold `.txt` files as fixtures - before touching `dvsu_script_brief.py` or any generation code.
Read `DvsU_Research_Fact_Verification_Standard.md` in full (417 lines, only skimmed this session) before
building the research/claim side of the new script stage.

## Open threads
- **Structural-label ambiguity (blocks Step 1):** several extracted gold `.txt` files mix real ~100-word
  paragraphs with short 1-15-word lines (act headers or unit-name labels, probably) - e.g.
  `every-us-strategic-bomber-ever-built.txt`, `every-us-aircraft-carrier-ever-built.txt`,
  `every-us-destroyer-class-ever-built-1898-1945.txt`. The `VOICEOVER_*`-named files look clean (no short
  lines) - likely narration already stripped of labels. Confirm before building the word-count checker.
- **Roster-size formula may need to change:** the real standard is thesis-driven (24-30 units, 4-7 acts,
  "curate for story, not completeness"); the current pipeline derives roster size from
  `video_length_minutes / minutes_per_machine` (runtime-driven). Needs Ryan's call before Step 2.
- The 20-machine submarine roster (`6ac28204-...`) is hand-composed, not web-verified - keep only as a
  research/script-writing fixture; do the real roster run on a NEW video once the script stage exists.
- VPS git remote embeds a GitHub PAT (`~/projects/economy-fastforward/.git/config`) - rotate it (Ryan only).

## Gotchas learned this session
- `list_pending_llm_requests {status:"answered"}` caps at 50, oldest first, and the reply is huge (saved to
  a file) - parse with python3, don't trust "all accepted" from a subagent without checking saved cards.
- A relay-answered machine's card can be accepted (6/6 answers) yet still fail to save - check
  `research_payload.unit_research_cards[].script_brief_readiness.passed` and grep backend logs for
  "Factual source research stopped at" - don't trust the MCP guide's stage-level summary alone.
- docx text extraction needs no library: `zipfile` + regex over `word/document.xml`'s `<w:t>` runs works
  cleanly and preserves paragraph order.
