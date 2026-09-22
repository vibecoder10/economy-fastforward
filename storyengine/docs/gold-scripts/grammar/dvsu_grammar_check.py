"""Pure DvsU script-grammar checker.

check(script_text) -> list[Violation]

Grades a full DvsU script against the rules in script_grammar.json (derived from
DvsU_Script_Writing_System.md / DvsU_Example_Paragraphs.md, cross-checked against
storyengine/notes/dvsu-quality-law.md). No I/O, no network, no state - safe to run
against any script text, generated or gold.

Two things this checker does NOT grade, by design:
- Acts (4-7 per video): not present as markers in any of the 14 gold scripts' text
  (see script_grammar.json's acts_per_video.note). Pass act_count if the outline
  stage has it; otherwise the result reports it as not_checked.
- Everything in dvsu-quality-law.md that isn't paragraph/script grammar: research
  sourcing, image briefs, voiceover file format/metadata, thumbnails, producer-file
  block structure. Those are separate concerns with separate gates.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_GRAMMAR_PATH = Path(__file__).resolve().parent / "script_grammar.json"


def _load_grammar() -> dict:
    return json.loads(_GRAMMAR_PATH.read_text(encoding="utf-8"))


_GRAMMAR = _load_grammar()

# --- structural-leakage detection ---------------------------------------------
# A script_text may still carry the title line and/or a trailing on-screen
# name/graphics list (see build_fixtures.py's docstring for why that split exists
# in the raw source material). check() strips these before grading narration so a
# leaked title or names list doesn't get graded as a malformed paragraph - and
# reports the leak itself as a violation, since QL-47 (storyengine/notes/
# dvsu-quality-law.md) requires the voiceover file to contain narration only.

_TAIL_MARKERS = ("[END OF SCRIPT]", "GRAPHICS LIST", "ON-SCREEN", "THUMBNAIL A/B TEST")
_DIVIDER_RE = re.compile(r"^[─—\-•\s]{6,}$")
# "Name [Class/Role] • [id/count] • years" - the on-screen roster line shape used
# across every gold script's trailing list (see docs/gold-scripts/scripts/*.txt).
_ROSTER_LINE_RE = re.compile(r"^[^.!?]{3,80}•[^.!?]{2,60}•[^.!?]{2,40}$")
_TITLE_LINE_RE = re.compile(r"^(EVERY|MOST|NEVER-BUILT)\b.{0,60}$", re.IGNORECASE)
_TITLE_PREFIX_RE = re.compile(r"^(Every|Most|Never-Built)\b")
# A lowercase letter directly abutting an uppercase run with no space/punctuation
# in between never occurs in normal prose - it's the fingerprint of a title glued
# straight onto the first paragraph with no separator (see build_fixtures.py's
# docstring: e.g. "...Ever BuiltHMS Furious began...").
_GLUE_RE = re.compile(r"[a-z](?=[A-Z]{2})")


def _split_structural_content(script_text: str) -> tuple[str, bool, bool]:
    """Returns (narration_only_text, leaked_title, leaked_tail)."""
    lines = script_text.splitlines()
    leaked_title = False
    leaked_tail = False

    start = 0
    if lines and _TITLE_LINE_RE.match(lines[0].strip()):
        leaked_title = True
        start = 1
        # a metadata line ("DvsU - Production Script | N Units | ...") sometimes
        # immediately follows the title; treat it as part of the leaked title.
        if start < len(lines) and "|" in lines[start] and "Units" in lines[start]:
            start += 1
    elif lines and _TITLE_PREFIX_RE.match(lines[0]):
        glue = _GLUE_RE.search(lines[0][:100])
        if glue:
            leaked_title = True
            lines[0] = lines[0][glue.end():]

    end = len(lines)
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if any(marker in stripped for marker in _TAIL_MARKERS) or _DIVIDER_RE.match(stripped) or _ROSTER_LINE_RE.match(stripped):
            leaked_tail = True
            end = i
            break

    narration = "\n".join(lines[start:end])
    return narration, leaked_title, leaked_tail


# --- word counting / paragraph splitting ---------------------------------------

def _split_paragraphs(narration_text: str) -> list[str]:
    return [line.strip() for line in narration_text.splitlines() if line.strip()]


def _word_count(paragraph: str) -> int:
    return len(paragraph.split())


# --- name-opener classification -------------------------------------------------

_NAME_OPENER_RE = re.compile(
    r"^The ([A-Z][\w.\-]*(?:\s+[A-Z0-9][\w.\-']*){0,5})\s+"
    r"(was|is|entered|first flew|first|became|had|served|flew)\b"
)


def _is_name_opener(paragraph: str) -> bool:
    return bool(_NAME_OPENER_RE.match(paragraph))


# --- forbidden patterns ----------------------------------------------------------

def _compile_forbidden_rules(rules: list[dict]) -> list[dict]:
    compiled = []
    for rule in rules:
        entry = {"id": rule["id"], "severity": rule["severity"]}
        if "terms" in rule:
            entry["term_res"] = [
                re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE) for term in rule["terms"]
            ]
        if "regex" in rule:
            flags = re.IGNORECASE if "i" in rule.get("flags", "") else 0
            entry["regex"] = re.compile(rule["regex"], flags)
        compiled.append(entry)
    return compiled


_FORBIDDEN_RULES = _compile_forbidden_rules(_GRAMMAR["forbidden_patterns"])


@dataclass
class Violation:
    rule: str
    severity: str  # "violation" | "warning" | "info"
    message: str
    paragraph_index: Optional[int] = None

    def to_dict(self) -> dict:
        d = {"rule": self.rule, "severity": self.severity, "message": self.message}
        if self.paragraph_index is not None:
            d["paragraph_index"] = self.paragraph_index
        return d


def _check_forbidden_patterns(paragraphs: list[str]) -> list[Violation]:
    violations = []
    for idx, paragraph in enumerate(paragraphs):
        for rule in _FORBIDDEN_RULES:
            hit = None
            if "term_res" in rule:
                for term_re in rule["term_res"]:
                    if term_re.search(paragraph):
                        hit = term_re.pattern
                        break
            if hit is None and "regex" in rule:
                if rule["regex"].search(paragraph):
                    hit = rule["id"]
            if hit is not None:
                violations.append(
                    Violation(
                        rule=f"forbidden_pattern:{rule['id']}",
                        severity=rule["severity"],
                        message=f"paragraph {idx} matches forbidden pattern '{rule['id']}'",
                        paragraph_index=idx,
                    )
                )
    return violations


def check(script_text: str, act_count: Optional[int] = None) -> list[dict]:
    """Grade a DvsU script against script_grammar.json. Pure function: no I/O.

    Args:
        script_text: the full script - narration paragraphs, one per line/block.
            May still carry a leaked title line and/or trailing on-screen name
            list; both are detected, stripped before grading, and reported.
        act_count: optional act count from the outline stage. Acts aren't
            derivable from script_text alone (see script_grammar.json's
            acts_per_video.note); pass this to also validate the 4-7 band.

    Returns:
        list of violation dicts: {rule, severity, message, paragraph_index?}.
        severity is one of "violation" (hard-gate), "warning" (target/band miss),
        "info" (a rule that couldn't be checked and why).
    """
    violations: list[Violation] = []

    narration_text, leaked_title, leaked_tail = _split_structural_content(script_text)
    if leaked_title:
        violations.append(
            Violation("leaked_structural_content", "violation",
                       "script_text carries a title line; the voiceover file must contain narration only (QL-47)")
        )
    if leaked_tail:
        violations.append(
            Violation("leaked_structural_content", "violation",
                       "script_text carries a trailing on-screen name/graphics list; strip it before this is a voiceover file (QL-47)")
        )

    paragraphs = _split_paragraphs(narration_text)
    n = len(paragraphs)

    # paragraph_count_per_video
    pc = _GRAMMAR["paragraph_count_per_video"]
    if n < pc["hard_floor"]:
        violations.append(Violation("paragraph_count", "violation",
                                     f"{n} paragraphs is under the {pc['hard_floor']}-paragraph floor"))
    elif n > pc["soft_ceiling"]:
        violations.append(Violation("paragraph_count", "warning",
                                     f"{n} paragraphs exceeds {pc['soft_ceiling']} - split into Part 1/2"))
    elif not (pc["target_min"] <= n <= pc["target_max"]):
        violations.append(Violation("paragraph_count", "warning",
                                     f"{n} paragraphs is outside the {pc['target_min']}-{pc['target_max']} target band"))

    # paragraph_word_count
    wc = _GRAMMAR["paragraph_word_count"]
    for idx, paragraph in enumerate(paragraphs):
        words = _word_count(paragraph)
        if words < wc["hard_min"] or words > wc["hard_max"]:
            violations.append(Violation("paragraph_word_count", "violation",
                                         f"paragraph {idx} has {words} words, outside the hard "
                                         f"{wc['hard_min']}-{wc['hard_max']} band",
                                         paragraph_index=idx))
        elif not (wc["target_min"] <= words <= wc["target_max"]):
            violations.append(Violation("paragraph_word_count", "warning",
                                         f"paragraph {idx} has {words} words, outside the "
                                         f"{wc['target_min']}-{wc['target_max']} target band",
                                         paragraph_index=idx))

    # name_openers
    no = _GRAMMAR["name_openers"]
    if n > 0:
        opener_count = sum(1 for p in paragraphs if _is_name_opener(p))
        share = opener_count / n
        if share > no["warn_share"]:
            violations.append(Violation("name_openers", "warning",
                                         f"{opener_count}/{n} paragraphs ({share:.0%}) open with the bare unit "
                                         f"name, above the {no['warn_share']:.0%} warn threshold "
                                         f"(written ideal is {no['doc_ideal_max_share']:.0%})"))

    # acts_per_video
    acts = _GRAMMAR["acts_per_video"]
    if act_count is None:
        violations.append(Violation("acts_per_video", "info",
                                     "act_count not supplied; acts are not derivable from script_text alone"))
    elif not (acts["min"] <= act_count <= acts["max"]):
        violations.append(Violation("acts_per_video", "warning",
                                     f"{act_count} acts is outside the {acts['min']}-{acts['max']} band"))

    # forbidden patterns (includes the ending/conclusion-paragraph rule, which is
    # just the conclusion_language pattern group applying to every paragraph,
    # including the last)
    violations.extend(_check_forbidden_patterns(paragraphs))

    return [v.to_dict() for v in violations]
