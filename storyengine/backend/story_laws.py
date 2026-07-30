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
convention this module parses. S5 itself — hard-requiring every scene to
name its location even when unchanged from the previous scene — is NOT
implemented here; today's gate only flags a MISSING location as one symptom
of an unverifiable S3 scene, it does not yet enforce S5's full contract.
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


def extract_scene_location(text: str) -> tuple[str | None, str]:
    """Pull a leading ``LOCATION: <place>`` header off scene text.

    Looks only at the first non-blank line — the writer's contract requires
    it there and nowhere else, so a stray "location" mention deeper in the
    narration is never misread as the header. Returns
    ``(location, remaining_text)`` where ``remaining_text`` has the header
    line (and any blank lines before it) removed. When no header is present,
    or the first line doesn't match, returns ``(None, text)`` — the original
    text, byte-for-byte.

    Call sites that must preserve their input byte-for-byte (the SUBMIT
    path's verbatim guarantee for creator-supplied scripts) should read only
    the first element of the tuple and keep using their ORIGINAL text, never
    the second element.
    """
    if not text:
        return None, text or ""
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return None, text
    m = _LOCATION_HEADER_RE.match(lines[idx])
    if not m:
        return None, text
    location = m.group(1).strip().strip("\"“”'")
    if not location:
        return None, text
    remaining = "\n".join(lines[:idx] + lines[idx + 1:]).strip()
    return location, remaining


def parse_scene_location(text: str) -> str | None:
    """Read-only variant of :func:`extract_scene_location` — the location
    only; the input text is never altered or even considered mutable by the
    caller. Use this at any call site that must not touch stored text (the
    SUBMIT path's creator-verbatim guarantee)."""
    return extract_scene_location(text)[0]


def check_scene_location_law(scenes: list[dict]) -> dict:
    """Deterministic S3 GATE for one video's scenes. Pure function: no I/O,
    no LLM call, safe to run read-only against any video at any time.

    ``scenes`` is an ordered list of ``{"scene": int, "location": str|None,
    "scene_text": str}`` — exactly the shape a
    ``SELECT scene, location, scene_text FROM scripts WHERE video_id = $1
    ORDER BY scene`` row maps to.

    Flags two things — both explicitly the "strong version" of the S3 gate
    the location column makes possible:

      1. ``no_location`` — a scene with no declared location. S3 requires a
         single stated location per scene; without one, single-location
         compliance can't be verified at all, so absence itself is a
         violation. This is also what flags every scene of a
         pre-migration video (location is NULL for all of them) — an
         honest, unavoidable consequence of a NEW column with no backfill,
         not a false positive: those scenes genuinely never stated a
         location.
      2. ``cross_location_text`` — a scene whose text contains another
         scene's declared location name as a whole phrase. A heuristic
         (substring / word-boundary match, case-insensitive), not proof —
         short or generic location names can false-positive, and a real
         cross-location beat that doesn't happen to repeat the other
         scene's exact name will false-negative. Documented as a known
         limitation, not silently pretended to be complete.

    Returns ``{"passed": bool, "violations": [{"scene": n, "reason": str,
    "detail": str}, ...]}``.
    """
    violations: list[dict] = []
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
        others = all_locations - {location}
        hits = []
        for other in others:
            if len(other) < 3:
                continue  # too short/generic to match on safely
            pattern = r"\b" + re.escape(other) + r"\b"
            if re.search(pattern, text, re.IGNORECASE):
                hits.append(other)
        if hits:
            violations.append({
                "scene": scene_num,
                "reason": "cross_location_text",
                "detail": (
                    f"Scene declares '{location}' but its text also names "
                    f"{', '.join(sorted(hits))} — another scene's location."
                ),
            })
    return {"passed": not violations, "violations": violations}
