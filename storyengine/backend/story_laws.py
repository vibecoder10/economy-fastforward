"""Story laws shared across every script-generation and script-submission path.

``STORY-LAWS.md`` (repo root: ``storyengine/STORY-LAWS.md``) is the source
text a human reads. This module is the ONE place that prose and its
deterministic checks live in code, so a law is written once and can reach
every path that writes to the ``scripts`` table instead of being copy-pasted
per path and drifting. See STORY-LAWS.md's "How a law becomes behaviour"
section for the PROMPT / GATE / REPAIR contract this module exists to serve.

D6-3 implements S3 (ONE SCENE IS ONE LOCATION AND ONE CONTINUOUS BEAT) and
lays the groundwork S5 (A SCENE STATES WHERE IT IS) lands on next: the
``scripts.location`` column (migration 144) and the ``LOCATION:`` header
convention this module parses.

D6-4 (2026-07-29) closes two of the remaining gaps and is honest about the
other two:

  - **S5 (A SCENE STATES WHERE IT IS) is ALREADY SATISFIED by D6-3's
    ``no_location`` check**, not a separate thing — see
    ``check_scene_location_law``'s docstring below. S5's full text is
    "every scene names its location explicitly in its own text, even when
    unchanged from the scene before"; that is EXACTLY what a hard,
    per-scene, no-exception ``location IS NOT NULL`` check enforces. No
    duplicate check was built. D6-4 only updated this module's and
    STORY-LAWS.md's documentation to say so plainly instead of leaving S5
    marked "not implemented" when it already was.
  - **S1 (NARRATE EVERY LOCATION CHANGE)** is implemented below as
    ``LOCATION_TRANSIT_LAW`` (PROMPT) and ``check_location_transit_law``
    (GATE, cross-scene, warn-only — see that function's docstring for the
    hard/warn split ruling).
  - **S2 (A PAYOFF MUST BE PAID FOR EARLIER)** has NO deterministic check
    here, and none is planned. "Is the closing theme earned by an earlier
    cost" is a judgement about dramatic structure, not a fact any column or
    reliable text pattern can answer — a hard OR warn gate here would be
    security theatre. See STORY-LAWS.md's status section for the same
    admission in the law document.
  - **S4 (THE SCRIPT IS THE SOURCE OF TRUTH FOR CAST)** gets a PARTIAL,
    warn-only gate — ``check_cast_consistency_law`` — because one side of
    the comparison (``video_characters.name``) is a real column even
    though the other side (the script) is free text. See that function's
    docstring for exactly what it can and cannot catch.

D7-6 (2026-07-30) lands S6's PROMPT leg (THE SCRIPT IS THE ORIGIN OF TRUTH,
AND CHANGING IT INVALIDATES WHAT CAME BEFORE) — ``SCRIPT_IS_SOURCE_OF_TRUTH_
LAW`` below. S6's GATE (hash compare-and-flag: ``videos.characters_hash`` /
``environments_hash``, migration 145) and REPAIR (invalidation on every
scene-text write) legs already landed on main (D7-2, D7-3) in
``routes/videos.py`` — that mechanism is deliberately NOT duplicated here;
this module only carries the law's TEXT, same as S1/S3/S4's constants do,
so a script-writing model is told the same contract the gate/repair legs
already enforce mechanically. Unlike S1/S3 (which shape scene STRUCTURE),
S6 has no per-scene deterministic check of its own to add here — "did the
writer treat the script as canonical" is not a fact any column or text
pattern can verify, so PROMPT is S6's only leg in this module.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# S3 — ONE SCENE IS ONE LOCATION AND ONE CONTINUOUS BEAT
# ---------------------------------------------------------------------------

# The instruction text every script-writing prompt must carry (PROMPT leg).
# This replaces the near-verbatim prose that used to live only inline in
# pipeline_executor.py's _run_modeled_script prompt — that call site now
# imports this constant instead of hand-rolling its own copy.
SCENE_LOCATION_LAW = (
    "ONE LOCATION PER SCENE (S3) — every scene takes place in a SINGLE "
    "physical location and covers ONE continuous beat of action. The moment "
    "the story moves somewhere new, or moves into a distinct new phase of "
    "action, START A NEW SCENE. A beat that spans several places or several "
    "phases becomes several scenes, one per place or phase — never let one "
    "scene carry, say, waking up, a decision, an escape, a chase and a "
    "return all at once; each of those is its own scene.\n\n"
    "Every scene MUST begin with a machine-readable header naming its "
    "single location, alone on the first line, in EXACTLY this form "
    "(nothing before it):\n"
    "LOCATION: <short name of the physical place>\n"
    "Example: LOCATION: the garage\n"
    "The header names ONE place. If the scene's action moves to a second "
    "place, that is the signal that it must split into a second scene with "
    "its own LOCATION header — never list two places on one header line, "
    "and never omit the header."
)

# Matches ONLY when the whole line is the header (optionally leading/trailing
# whitespace) — deliberately strict so ordinary narration that happens to
# contain the word "location" is never mistaken for the header.
_LOCATION_HEADER_RE = re.compile(r"^\s*LOCATION\s*:\s*(.+?)\s*$", re.IGNORECASE)

# S7-A — ACTION: <direction>, the stage-direction sibling of LOCATION:. Same
# strict whole-line match, same reasoning: ordinary narration that happens to
# use the word "action" must never be misread as the header.
_ACTION_HEADER_RE = re.compile(r"^\s*ACTION\s*:\s*(.+?)\s*$", re.IGNORECASE)


def _extract_leading_header(
    text: str, own_re: "re.Pattern[str]", other_re: "re.Pattern[str]"
) -> tuple[str | None, str]:
    """Shared scan behind :func:`extract_scene_location` and
    :func:`extract_scene_action`. Looks at the first non-blank line for
    ``own_re``. LOCATION: and ACTION: may coexist as a scene's two leading
    header lines in EITHER order (S7-A), so when that first line instead
    matches ``other_re`` (the sibling header), tolerates it and looks at the
    NEXT non-blank line for ``own_re`` — never more than one line of
    tolerance, so a stray header-shaped line deeper in the narration is
    still never mistaken for the real thing.

    Returns ``(value, remaining_text)`` exactly like the two public
    extractors: ``remaining_text`` has ONLY the matched header line (and any
    blank lines strictly before it) removed — a sibling header line, if
    tolerated, is left in place for that sibling's own extractor to strip.
    When nothing matches, returns ``(None, text)`` — the original text,
    byte-for-byte.
    """
    if not text:
        return None, text or ""
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return None, text
    m = own_re.match(lines[idx])
    header_idx = idx
    if not m:
        if not other_re.match(lines[idx]):
            return None, text
        idx2 = idx + 1
        while idx2 < len(lines) and not lines[idx2].strip():
            idx2 += 1
        if idx2 >= len(lines):
            return None, text
        m = own_re.match(lines[idx2])
        if not m:
            return None, text
        header_idx = idx2
    value = m.group(1).strip().strip("\"“”'")
    if not value:
        return None, text
    remaining = "\n".join(lines[:header_idx] + lines[header_idx + 1:]).strip()
    return value, remaining


def extract_scene_location(text: str) -> tuple[str | None, str]:
    """Pull a leading ``LOCATION: <place>`` header off scene text.

    Looks at the first non-blank line, tolerating at most one leading
    ``ACTION:`` line before it (S7-A — the two headers may coexist, in
    either order, as the scene's two leading lines) — the writer's contract
    requires the LOCATION header to be one of the first (at most) two
    non-blank lines, so a stray "location" mention deeper in the narration
    is never misread as the header. Returns ``(location, remaining_text)``
    where ``remaining_text`` has the LOCATION line (and any blank lines
    strictly before it) removed — an ACTION line, if present, is left in
    place; only :func:`extract_scene_action` strips that one. When no
    header is present, or nothing matches, returns ``(None, text)`` — the
    original text, byte-for-byte.

    Call sites that must preserve their input byte-for-byte (the SUBMIT
    path's verbatim guarantee for creator-supplied scripts) should read only
    the first element of the tuple and keep using their ORIGINAL text, never
    the second element.
    """
    return _extract_leading_header(text, _LOCATION_HEADER_RE, _ACTION_HEADER_RE)


def parse_scene_location(text: str) -> str | None:
    """Read-only variant of :func:`extract_scene_location` — the location
    only; the input text is never altered or even considered mutable by the
    caller. Use this at any call site that must not touch stored text (the
    SUBMIT path's creator-verbatim guarantee)."""
    return extract_scene_location(text)[0]


def extract_scene_action(text: str) -> tuple[str | None, str]:
    """Pull a leading ``ACTION: <direction>`` header off scene text — the
    S7-A stage-direction sibling of :func:`extract_scene_location`, same
    contract, same tolerance for the OTHER header preceding this one (a
    LOCATION: line may sit before the ACTION: line; at most one line of
    tolerance, never more).

    ``action`` is the physical stage business a scene must SHOW on screen
    (e.g. "she jumps on the table and dances", "he sprints across the
    parking lot") that spoken ``Name:`` dialogue lines alone never carry —
    it is NEVER spoken or voiced. Returns ``(action, remaining_text)`` where
    ``remaining_text`` has ONLY the ACTION line (and any blank lines
    strictly before it) removed — a LOCATION line, if present, is left in
    place for :func:`extract_scene_location` to strip. When no header is
    present, or nothing matches, returns ``(None, text)`` — the original
    text, byte-for-byte.

    Call sites that must preserve their input byte-for-byte (the SUBMIT
    path's verbatim guarantee for creator-supplied scripts) should read only
    the first element of the tuple and keep using their ORIGINAL text, never
    the second element.
    """
    return _extract_leading_header(text, _ACTION_HEADER_RE, _LOCATION_HEADER_RE)


def parse_scene_action(text: str) -> str | None:
    """Read-only variant of :func:`extract_scene_action` — the action only;
    the input text is never altered or even considered mutable by the
    caller. Use this at any call site that must not touch stored text (the
    SUBMIT path's verbatim guarantee)."""
    return extract_scene_action(text)[0]


def _location_spans(text: str, location: str) -> list[tuple[int, int]]:
    """All word-boundary occurrences of ``location`` inside ``text``."""
    if len(location) < 3 or not text:
        return []
    pattern = r"\b" + re.escape(location) + r"\b"
    return [m.span() for m in re.finditer(pattern, text, re.IGNORECASE)]


def _mentions_other_location(text: str, own_spans: list[tuple[int, int]], other: str) -> bool:
    """Does ``text`` name ``other`` (a sibling scene's location) in a way
    that ISN'T just a substring of THIS scene's own, longer location name?

    D6-3b fix: a raw word-boundary search alone still false-positives when
    one location name is a prefix of another — "the pod" (a sibling's
    location) inside "the pod bay" (THIS scene's own, longer, declared
    location), or "Diner" (a sibling's location) inside "Diner Parking Lot"
    (this scene's own). Any ``other`` match fully contained inside a span
    where this scene's OWN location name also matched is the scene naming
    its own place, not a foreign one — suppressed.
    """
    for start, end in _location_spans(text, other):
        if any(a <= start and end <= b for a, b in own_spans):
            continue
        return True
    return False


def check_scene_location_law(scenes: list[dict]) -> dict:
    """Deterministic S3 GATE for one video's scenes. Pure function: no I/O,
    no LLM call, safe to run read-only against any video at any time.

    ``scenes`` is an ordered list of ``{"scene": int, "location": str|None,
    "scene_text": str}`` — exactly the shape a
    ``SELECT scene, location, scene_text FROM scripts WHERE video_id = $1
    ORDER BY scene`` row maps to.

    Two checks, two different severities — D6-3b ruling, not a suggestion:

      1. ``no_location`` (HARD — goes in ``violations``, may block). A scene
         with no declared location. ``location`` is a real COLUMN, not
         prose — canonical, not a guess — so its absence is a fact a caller
         is entitled to treat as a hard failure. This is also what flags
         every scene of a pre-migration video (location is NULL for all of
         them): an honest, unavoidable consequence of a NEW column with no
         backfill, not a false positive — those scenes genuinely never
         stated a location.

         D6-4 NOTE: this single check is ALSO the full S5 contract (A SCENE
         STATES WHERE IT IS — "every scene names its location explicitly in
         its own text, even when it is the same location as the scene
         before"). It does not special-case "same as the previous scene" —
         it requires a location on EVERY scene, unconditionally, which is
         precisely S5's "even when unchanged" clause. S5 is therefore
         already implemented by D6-3, in all three legs: PROMPT
         (``SCENE_LOCATION_LAW`` requires a header on every scene, not just
         changed ones), GATE (this check, unconditional), REPAIR
         (``edit_scene_text``/``regenerate_scene_text`` in routes/videos.py
         carry the column forward via COALESCE and re-run this same check).
         No separate S5 function exists and none should be added — see
         STORY-LAWS.md's S5 entry.
      2. ``cross_location_text`` (WARN ONLY — goes in ``warnings``, must
         NEVER block, permanently). A scene whose text contains another
         scene's declared location name as a whole phrase. This compares
         PROSE to PROSE, and prose is never canonical: a character can
         legally mention, remember, or look out a window at another
         location (BOARD-LAWS L11) without the scene itself spanning two
         places, and S1 (NARRATE EVERY LOCATION CHANGE) *requires* an
         outgoing scene's text to name the place the story is headed to —
         "She leaves the corridor behind and steps onto the bridge" is
         exactly what S1 demands, and it will always trip this heuristic.
         Hard-blocking on prose-to-prose comparison would put S3 in direct
         conflict with S1; this resolves it in S1's favor (S1 governs
         whether the script is filmable at all, S3 governs scene size) by
         making the check advisory. See STORY-LAWS.md's S3 entry for the
         same ruling in the law document itself.

    Returns ``{"passed": bool, "violations": [{"scene", "reason":
    "no_location", "detail"}, ...], "warnings": [{"scene", "reason":
    "cross_location_text", "detail"}, ...]}``. ``passed`` reflects
    ``violations`` only — a video with warnings but no violations still
    passes.
    """
    violations: list[dict] = []
    warnings: list[dict] = []
    all_locations = {
        (s.get("location") or "").strip()
        for s in scenes
        if (s.get("location") or "").strip()
    }
    for s in scenes:
        scene_num = s.get("scene")
        location = (s.get("location") or "").strip()
        text = s.get("scene_text") or ""
        if not location:
            violations.append({
                "scene": scene_num,
                "reason": "no_location",
                "detail": "Scene has no LOCATION header — cannot verify it holds a single location.",
            })
            continue
        own_spans = _location_spans(text, location)
        others = all_locations - {location}
        hits = [
            other for other in sorted(others)
            if _mentions_other_location(text, own_spans, other)
        ]
        if hits:
            warnings.append({
                "scene": scene_num,
                "reason": "cross_location_text",
                "detail": (
                    f"Scene declares '{location}' and its text also names "
                    f"{', '.join(hits)} — another scene's location. This is "
                    "advisory only: mentioning, remembering, or narrating a "
                    "move to another place is legal (and S1 requires it for "
                    "an outgoing scene) — review, don't assume a violation."
                ),
            })
    return {"passed": not violations, "violations": violations, "warnings": warnings}


# ---------------------------------------------------------------------------
# S1 — NARRATE EVERY LOCATION CHANGE
# ---------------------------------------------------------------------------

# PROMPT leg. Appended alongside SCENE_LOCATION_LAW (S3) at every call site
# that carries it — the two laws are complementary (S3: don't let one scene
# span two places; S1: when you DO move between scenes, write the move) and
# a writer needs both at once or it will solve one by breaking the other
# (e.g. silently cutting between LOCATION headers with nothing narrated in
# between, which satisfies S3's "one location per scene" while violating S1).
LOCATION_TRANSIT_LAW = (
    "NARRATE EVERY LOCATION CHANGE (S1) — when the story moves a character "
    "from one place to the next scene's different place, WRITE THE MOVE. "
    "Not a summary of it — the actual beat: the door, the threshold, the "
    "exit, the travel, the arrival. If scene N is in one LOCATION and scene "
    "N+1 is in a different one, put the transit somewhere in that pair — "
    "the end of the outgoing scene ('She leaves the corridor behind and "
    "steps onto the bridge') or the start of the incoming one ('The garage "
    "door creaks up and she ducks inside'). A board asked to draw an "
    "unnarrated move will either invent one or silently skip it, and both "
    "read on screen as a broken cut. Do not just end one LOCATION header's "
    "scene and start the next with nothing narrated between them."
)

# Best-effort prose signal that SOME kind of transit is described — a
# secondary heuristic alongside the cross-location-mention check below.
# Deliberately generous (many hits, not a strict grammar) because this is
# warn-only forever (see check_location_transit_law) — a false "transit
# found" just means one fewer advisory warning, never a missed hard defect.
_TRANSIT_HINTS_RE = re.compile(
    r"\b("
    r"door|doorway|hatch|threshold|corridor|hallway|hall|stairs?|stairwell|"
    r"elevator|lift|window|gate|entrance|exit|"
    r"walks?\s+(?:to|into|toward|through|out)|"
    r"steps?\s+(?:into|through|out|toward|inside|off)|"
    r"enters?|exits?|arrives?|departs?|"
    r"heads?\s+(?:to|toward|for|out)|"
    r"leaves?|climbs?|crosses?\s+(?:into|through)|"
    r"makes?\s+(?:her|his|their)\s+way\s+(?:to|into|toward)|"
    r"runs?\s+(?:to|into|toward|down|through)|"
    r"cut\s+to|moments\s+later|back\s+(?:at|in)|now\s+(?:at|in)"
    r")\b",
    re.IGNORECASE,
)


def _has_transit_language(text: str) -> bool:
    """Loose, best-effort signal that a scene's text describes SOME kind of
    physical transit (a door, a corridor, a verb of arriving/leaving/
    walking). Never authoritative — see check_location_transit_law."""
    return bool(text) and bool(_TRANSIT_HINTS_RE.search(text))


def check_location_transit_law(scenes: list[dict]) -> dict:
    """Deterministic S1 GATE for one video's scenes, in scene order. Pure
    function: no I/O, no LLM call, same shape/safety contract as
    check_scene_location_law (safe to run read-only against any video at
    any time — this is the exact shape a
    ``SELECT scene, location, scene_text FROM scripts WHERE video_id = $1
    ORDER BY scene`` row maps to).

    THE HARD/WARN SPLIT (D6-4 ruling, STORY-LAWS.md's S1 entry — read that
    first): S1 is naturally two questions, and Ruling 1 (a gate may only be
    HARD when what it compares is CANONICAL; prose-vs-prose must warn) puts
    them on opposite sides of the line:

      1. "Does scene N's location differ from scene N-1's?" — a comparison
         of two CANONICAL COLUMN values (``scripts.location``, migration
         144). This is reliable, not a guess, and per Ruling 1 is ELIGIBLE
         to be hard. It is surfaced as its own structured, always-computed
         ``location_changes`` list so any caller that only needs "did the
         location change" (not "was it narrated") has a trustworthy answer
         without re-deriving it from prose. But — and this is the whole
         point of the split — a location changing between scenes is NOT
         itself a defect. Stories are SUPPOSED to move characters around.
         Nothing is ever blocked on this fact alone; there is no
         "violations" bucket in this function's return value, on purpose.
      2. "Was a transit actually narrated?" — inherently PROSE detection.
         There is no reliable way to recognise a narrated threshold in
         free text; a "she leaves the bedroom" beat can be phrased in
         effectively unlimited ways, and a real transit narrated in words
         this heuristic doesn't recognise must never be punished as if it
         were missing. Per Ruling 1 this MUST warn, always, permanently —
         exactly the same reasoning S3's ``cross_location_text`` check
         already uses (and this function REUSES that check's own
         ``_mentions_other_location`` machinery as its strongest signal:
         if the incoming scene's text names the outgoing scene's location,
         or vice versa, that is direct textual evidence of the move — it
         is literally what S1 asks a writer to do). A secondary, looser
         keyword heuristic (``_has_transit_language``) catches phrasings
         that don't name either location explicitly (generic "she opens
         the door and steps outside"). Absence of BOTH signals produces a
         warning, never a violation.

    Scenes with no declared location are skipped as a comparison endpoint
    (both here and as anything being compared TO) — S3/S5's ``no_location``
    check already hard-flags those separately, and a missing location on
    either side means there is nothing canonical to compare, so this
    function stays silent about that pair rather than guessing. This is
    also why running this function against a fully pre-migration video
    (every scene's ``location`` is NULL) returns ``{"location_changes": [],
    "warnings": []}`` — correctly silent, not a false negative: NO
    canonical location data exists to compare, so S1 cannot be verified
    here at all. That gap is what ``no_location`` (S3/S5) already reports;
    S1 does not duplicate it.

    Returns ``{"location_changes": [{"from_scene", "to_scene",
    "from_location", "to_location"}, ...], "warnings": [{"scene",
    "from_scene", "to_scene", "reason": "unnarrated_location_change",
    "detail"}, ...]}``. ``scene`` on a warning equals ``to_scene`` (kept for
    shape-parity with check_scene_location_law's per-scene warnings, which
    only ever concern one scene); ``from_scene``/``to_scene`` are there
    explicitly because an S1 warning is inherently about a PAIR — a caller
    that wants "does scene N have any S1 issue" must check both, not just
    ``scene``, or it will silently miss every warning where scene N is the
    OUTGOING half of the pair. Deliberately has NO ``violations`` key and NO
    ``passed`` key — unlike check_scene_location_law, S1 has no hard leg to
    report, and a caller must never synthesize a "passed" flag from this
    output; that would silently reintroduce the hard block Ruling 1
    forbids.
    """
    ordered = sorted(
        (s for s in scenes if s.get("scene") is not None),
        key=lambda s: s["scene"],
    )
    location_changes: list[dict] = []
    warnings: list[dict] = []
    prev = None  # (location, text, scene_num) of the last scene WITH a location
    for s in ordered:
        location = (s.get("location") or "").strip()
        text = s.get("scene_text") or ""
        if not location:
            # No canonical data for this scene — can't compare it to
            # anything, and can't let a later scene compare across the gap
            # either (that would be guessing what happened in between).
            prev = None
            continue
        if prev is not None:
            prev_location, prev_text, prev_scene = prev
            if location.lower() != prev_location.lower():
                location_changes.append({
                    "from_scene": prev_scene,
                    "to_scene": s.get("scene"),
                    "from_location": prev_location,
                    "to_location": location,
                })
                incoming_spans = _location_spans(text, location)
                outgoing_spans = _location_spans(prev_text, prev_location)
                narrated = (
                    _mentions_other_location(text, incoming_spans, prev_location)
                    or _mentions_other_location(prev_text, outgoing_spans, location)
                    or _has_transit_language(text)
                    or _has_transit_language(prev_text)
                )
                if not narrated:
                    warnings.append({
                        "scene": s.get("scene"),
                        "from_scene": prev_scene,
                        "to_scene": s.get("scene"),
                        "reason": "unnarrated_location_change",
                        "detail": (
                            f"Scene {prev_scene} is in '{prev_location}' and scene "
                            f"{s.get('scene')} is in '{location}' — no transit "
                            "(door, threshold, travel, arrival) found in either "
                            "scene's text. This is advisory only: transit "
                            "detection is a prose heuristic, so review before "
                            "assuming the narration is really missing."
                        ),
                    })
        prev = (location, text, s.get("scene"))
    return {"location_changes": location_changes, "warnings": warnings}


# ---------------------------------------------------------------------------
# S4 — THE SCRIPT IS THE SOURCE OF TRUTH FOR CAST (PARTIAL — see docstring)
# ---------------------------------------------------------------------------

# Dialogue speaker tags at the start of a line — the exact convention
# pipeline_executor._run_modeled_script's own prompt teaches the writer
# ("speaker turns like 'Mum: ...' are fine"). Deliberately conservative:
# line-start, followed by a space then a non-space, AND — the D6-4 false-
# positive-hunt fix — EVERY word in the tag must itself be Title Case
# (1-3 words). A first cut of this regex only required the FIRST word to
# be capitalized, which live-tested against video 686b4651's real scene 3
# ("Then Nyla finds it: a lens hidden in her ceiling...") false-positived
# on "Then Nyla finds it" as a speaker name — ordinary narration that
# happens to contain a colon. Requiring ALL words to be capitalized (a
# real speaker tag is a name or role — "Mum", "Elder Mara", "Old Man" —
# never a sentence with lowercase connective words in it) rejects that
# case while still matching every real speaker-tag shape the prompt
# teaches.
_SPEAKER_TAG_RE = re.compile(
    r"^[ \t]*((?:[A-Z][A-Za-z''\-]*(?:[ \t]+[A-Z][A-Za-z''\-]*){0,2})):[ \t]+\S",
    re.MULTILINE,
)
_GENERIC_SPEAKER_WORDS = {"location", "narrator", "note", "scene", "voiceover", "vo"}


def _speakers_in_script(text: str) -> set[str]:
    """Best-effort extraction of dialogue speaker names from script text.
    Not exhaustive: prose-only narration with no dialogue produces none,
    and that's correct, not a bug — S4's speaker check only has signal
    where the script actually names a speaker."""
    if not text:
        return set()
    out: set[str] = set()
    for m in _SPEAKER_TAG_RE.finditer(text):
        name = m.group(1).strip()
        if name and name.lower() not in _GENERIC_SPEAKER_WORDS:
            out.add(name)
    return out


def _name_in_text(name: str, text: str) -> bool:
    """Whole-word, case-insensitive search — no length floor (unlike
    _location_spans, which floors at 3 chars to avoid over-matching short
    location words; character names are proper nouns and short ones like
    "Al" or "Bo" are common enough to be worth checking)."""
    if not name or not text or len(name) < 2:
        return False
    return re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE) is not None


def check_cast_consistency_law(scenes: list[dict], cast: list[dict]) -> dict:
    """PARTIAL S4 GATE — warn-only, PERMANENTLY. Pure function: no I/O, no
    LLM call. ``scenes`` is the same shape check_scene_location_law and
    check_location_transit_law take (only ``scene_text`` is read here);
    ``cast`` is an ordered list of ``{"name": str, ...}`` — exactly what a
    ``SELECT name FROM video_characters WHERE video_id = $1`` row maps to.

    WHY THIS IS PARTIAL, AND WHY IT CAN NEVER BE HARD (Ruling 1): one side
    of the comparison, ``video_characters.name``, IS a real column — but
    the other side is the script's free text, and matching a canonical
    name against prose is still fundamentally a prose search. A script can
    legitimately describe a character without ever using their sheet name
    ("a woman in gold" instead of "Elder Mara") — that is not a defect,
    it's how narration and description work. So, exactly like S1's
    transit check and S3's cross_location_text check, this can only ever
    warn.

    Two directions:
      1. ``cast_not_named_in_script`` — a video_characters row whose
         ``name`` never appears (whole-word, case-insensitive) anywhere in
         the video's script text. Catches a character the visual layer
         invented that the writer's words never named.
      2. ``speaker_not_in_cast`` — a dialogue speaker tag in the script
         ("Name: ...", see ``_speakers_in_script``) that doesn't match any
         cast member's name. Catches a named speaker with no character
         sheet at all.

    NOT exhaustive, and not meant to be — this is the real, still-open
    case in HANDOFF.md/STORY-LAWS.md: a script naming "a woman in gold"
    and "an old man" while the board cast three named navy-suited elders.
    This function WILL flag that mismatch (direction 1, three times, since
    none of the cast names appear in the script's prose) — it will NOT and
    CANNOT decide which side is right. STORY-LAWS.md's S4 law says the
    script wins; whether that is actually correct for THIS video is a
    human call this function does not make.

    Returns ``{"warnings": [{"reason", "name", "detail"}, ...]}``. No
    ``violations``, no ``passed`` key — there is no hard leg for S4.
    """
    script_text = "\n\n".join((s.get("scene_text") or "") for s in scenes)
    cast_names = [
        (c.get("name") or "").strip() for c in cast if (c.get("name") or "").strip()
    ]
    warnings: list[dict] = []
    for name in cast_names:
        if len(name) < 2:
            continue
        if not _name_in_text(name, script_text):
            warnings.append({
                "reason": "cast_not_named_in_script",
                "name": name,
                "detail": (
                    f"'{name}' is cast in the visual layer (video_characters) but "
                    "is never named anywhere in the script text — review whether "
                    "the script describes this character by a different name or "
                    "description, or whether the visual layer invented a "
                    "character the writer didn't."
                ),
            })
    cast_lower = {n.lower() for n in cast_names}
    for speaker in sorted(_speakers_in_script(script_text)):
        if speaker.lower() not in cast_lower:
            warnings.append({
                "reason": "speaker_not_in_cast",
                "name": speaker,
                "detail": (
                    f"The script has a speaker labeled '{speaker}:' with no "
                    "matching video_characters entry — review whether this "
                    "speaker needs a character sheet or is a minor/off-camera "
                    "voice the visual layer intentionally skipped."
                ),
            })
    return {"warnings": warnings}


# ---------------------------------------------------------------------------
# S6 — THE SCRIPT IS THE ORIGIN OF TRUTH, AND CHANGING IT INVALIDATES WHAT
# CAME BEFORE (D7-6 — PROMPT leg only; GATE/REPAIR already live in
# routes/videos.py — see this module's docstring above)
# ---------------------------------------------------------------------------

# PROMPT leg. Injected at the SAME call sites SCENE_LOCATION_LAW/
# LOCATION_TRANSIT_LAW already ride along at: pipeline_executor.resolve_prompt
# (ACT-based docu path) and _run_modeled_script's inline prompt (modeled
# path). Unlike S1/S3, which are instructions about scene STRUCTURE, S6 is an
# instruction about what the writer treats as AUTHORITATIVE: the script text
# itself, never a cast sheet, environment design, or board generated from an
# earlier draft. This is the same rule the GATE (hash compare) and REPAIR
# (stale-flagging) legs already enforce mechanically after the fact — this
# constant is what tells the model up front, so fewer scripts trigger it.
SCRIPT_IS_SOURCE_OF_TRUTH_LAW = (
    "THE SCRIPT IS THE ORIGIN OF TRUTH (S6) — every downstream artifact (cast, "
    "environments, storyboards, coverage, voice) is generated FROM this "
    "script, never the other way around. Write the full truth directly into "
    "the script text itself: every character who appears, anything about "
    "how they look or what they wear that the story actually needs, and "
    "every place the story visits. Do not leave these to be inferred later "
    "from a character sheet, environment design, or board that already "
    "exists — those were built from an EARLIER version of this script, and "
    "the moment the words here change, that older artifact is stale and "
    "will be regenerated from what you write now, not preserved on the "
    "assumption it still matches. A script that under-describes its own "
    "cast or world forces a later stage to guess or invent; a script that "
    "states the full truth in its own words does not."
)
