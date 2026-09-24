"""DVSU script-writing pipeline v2 - the ONLY DvsU machine-paragraph writer.

Implements ``storyengine/docs/dvsu-script-pipeline-v2-2026-09-18/DESIGN.md``
(Ryan-approved 2026-09-18, hand-validated on 4 real scripts) as code. It
replaced, with no fallback and no flag, the three legacy writers that used to
live in ``pipeline_executor._run_static_script_hold`` (Anton inventory mode,
the legacy non-inventory paragraph writer) and
``factual_machine_pipeline.run_factual_script_hold`` (the write+referee
``factual_100_v1`` path). Ripped out 2026-09-21; see HANDOFF.md.

Mirrors ``dvsu_research_v2.py``'s shape: prompt constants, pure
``_normalize_*`` helpers, one ``client.generate()`` per
paragraph with the same checkpoint/fingerprint pattern (so the agent LLM relay
and restart-resume work unchanged), fail-soft Drive export.

Locked rules:

1. One paid call per machine, NO referee call and NO code-side audit.
   The code-side checker (word band, forbidden-phrase regex, name-opener
   budget, terminology) and its bounded repair call were removed 2026-09-22
   at Ryan's direction: it was legacy, it blocked good paragraphs on regex
   false positives, and no script should ever be withheld. Every paragraph
   this module writes is saved and surfaced in full; quality is a human
   judgement made against docs/gold-scripts/standards/.
2. Script-writing is stateful and runs in roster/act order: every prior
   finished paragraph is passed as context.
3. No new storage layer. Blocks live where they always did
   (``videos.script_validation.machine_script_blocks`` + ``scripts`` rows,
   previews in ``research_payload.machine_script_previews``), plus a
   fail-soft ``02-script.md`` Drive export next to the research files.

The two gaps the design left open, resolved here (2026-09-21):

* Cross-act sibling relevance: EVERY prior finished paragraph (full text,
  tagged with its act) is passed, plus the next machine's name and its
  research "problem" line for a forward bridge. The model picks the bridge;
  code records ``bridged_to``. Bounded cost (~30 paragraphs x ~110
  words ~= 5K tokens by the end of a video). The roster stage is untouched.
* Word band: 95-120 is handed to the writer as guidance in the prompt and is
  never enforced. Empirical basis, docs/gold-scripts/grammar: 14 shipped
  scripts, 373 paragraphs, median 107, p10 84, p90 129; 24% under 95 and 18%
  over 120. "Never less, never more" is aspirational, not what ships - which
  is exactly why nothing rejects a paragraph for missing it.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Optional

_PIPELINE_PATH = Path(__file__).parent.parent.parent / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

logger = logging.getLogger(__name__)

SCRIPT_CONTRACT = "dvsu_script_v2"
RESEARCH_SOURCE = "dvsu_research_v2_packet"

# Length guidance handed to the writer in the prompt. Advisory only - nothing
# in this module blocks a paragraph for being outside it.
WORD_TARGET_MIN = 95
WORD_TARGET_MAX = 120

DEFAULT_VOICE_ID = "1SM7GgM6IMuvQlz2BwM3"

# ---------------------------------------------------------------------------
# Prompt (DESIGN.md "The v3-aligned prompt", PROMPT-v3, validated on 4 scripts)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You write one paragraph of a DvsU engineering-documentary script. DvsU is an engineering "
    "documentary channel that uses military machines as its subject: war is the setting, engineering "
    "is the story. The viewer is never watching because of the machine - they are watching because of "
    "the engineering decision the machine represents. Use only the supplied BRIEF for facts. Output "
    "only the requested JSON."
)

_OUTPUT_SHAPE = (
    '{"paragraph": "...", '
    '"claim_map": [{"sentence": "...", "fact_id": "<id from the BRIEF>"}], '
    '"opened_with_name": true|false, '
    '"bridged_to": "<machine name from this video>" | null}'
)


def _submarine_context(*texts: str) -> bool:
    return any(re.search(r"\bsubmarines?\b|\bsubs?\b|\bU-boats?\b", str(t or ""), re.I) for t in texts)


def _acts_block(acts: list[dict]) -> str:
    if not acts:
        return ""
    lines = "\n".join(f"  Act {a.get('act_number')}: {a.get('argument')}" for a in acts if isinstance(a, dict))
    return f"ACTS (the argument, in order):\n{lines}\n"


def _prior_paragraphs_block(prior: list[dict]) -> str:
    if not prior:
        return (
            "PRIOR PARAGRAPHS: none finished yet - this is the first paragraph, so open on the "
            "machine's own problem, paradox, date, human detail, consequence, or contrast.\n"
        )
    lines = []
    for row in prior:
        lines.append(
            f"[Act {row.get('act_number')}] {row.get('machine')}: {row.get('paragraph')}"
        )
    return (
        "PRIOR PARAGRAPHS (finished, in video order - the one directly above this machine is the "
        "immediate predecessor):\n" + "\n".join(lines) + "\n"
    )


def _next_machine_block(next_machine: Optional[dict]) -> str:
    if not next_machine:
        return "NEXT MACHINE: none - this is the final paragraph of the video; its last line ends the film.\n"
    problem = str(next_machine.get("problem") or "").strip()
    line = f"NEXT MACHINE: {next_machine.get('machine')} (Act {next_machine.get('act_number')})"
    if problem:
        line += f" - its problem: {problem}"
    return line + "\n"


def _opener_block(scene: int) -> str:
    assigned, alternate, previous = assigned_opener(scene)
    avoid = (
        f" The paragraph before this one was assigned {previous}, so do not open that way again."
        if previous else ""
    )
    return (
        f"OPENING (assigned for this paragraph): open with {assigned}. If the brief genuinely cannot "
        f"support that, open with {alternate} instead - but never open with the machine's name, and never "
        "open with a mechanical connector.{avoid_text}\n"
    ).replace("{avoid_text}", avoid)


def build_write_prompt(
    *,
    title: str,
    thesis: str,
    acts: list[dict],
    machine: str,
    act_number: int,
    act_thesis: str,
    scene: int,
    roster_size: int,
    brief_markdown: str,
    prior_paragraphs: list[dict],
    next_machine: Optional[dict],
) -> str:
    submarine = _submarine_context(title, machine, thesis)
    terminology = (
        "Submarine terminology (project-specific): refer to the subject and its successors as a "
        "submarine/submarines or vessel/vessels, never boat/boats.\n\n"
        if submarine else ""
    )
    return (
        f"You are writing one paragraph of a DvsU engineering-documentary script about the exact named "
        f"machine: {machine}, part of Act {act_number} - one-sentence act thesis: {act_thesis or thesis}.\n"
        f'Video: "{title}". Video thesis: {thesis}\n'
        f"{_acts_block(acts)}"
        f"This is paragraph {scene} of {roster_size}.\n\n"
        "Core rule: this paragraph is about the ENGINEERING DECISION the machine represents, not the "
        f"machine itself. Answer: what is the single reason historians still talk about {machine} today? "
        "Write about why it's remembered, not about what it did.\n\n"
        "Audience: military-history enthusiasts, 55+, who already know the machine exists and will "
        "fact-check every claim. Do not spend words proving it existed. Write as an equal, not a teacher.\n\n"
        "Source: use only the supplied BRIEF (Problem / Design / Trade-off / Outcome / Surprising fact / "
        "Contrast). Each fact is a verbatim quote from its source page - read it closely and state only what "
        "it says. Do not add outside knowledge or invented dates/numbers - but DO "
        "state the argued lesson the facts support. This is an essay making an argument, not a "
        "citation-safe recitation.\n\n"
        f"Length: {WORD_TARGET_MIN}-{WORD_TARGET_MAX} words. Never less, never more. A pivotal machine "
        "(first-of-kind, act-defining, a death/failure/reversal) earns the top of the range. A transitional "
        "machine earns the bottom. Equal length does not mean equal narrative weight.\n\n"
        "Must include, non-negotiable:\n"
        "- At least one surprising fact most viewers won't already know. Check the BRIEF's \"Surprising "
        "fact\" section first; don't cut it for budget.\n"
        "- A real contrast (expectation vs. reality, design vs. outcome, intention vs. legacy). Build it "
        "from the BRIEF's \"Contrast\" quote when it supports one - don't discard it.\n"
        "- A final line that lands: short, a paradox/irony/reversal. If the last sentence could be deleted "
        "without losing meaning, rewrite it. Never summarize; land.\n"
        "- The machine's name or designation somewhere in the paragraph (it need not be the opener).\n\n"
        f"{_opener_block(scene)}"
        "Bridging: the video must feel like a documentary, not a ranked list. If a prior paragraph (the "
        "immediate predecessor in the same act, or ANY earlier paragraph in an earlier act that shares a "
        "real fact with this machine) offers a genuine narrative bridge, open or close with it - grounded "
        "in an actual shared fact, never a mechanical connector (\"Next...\", \"Another submarine was...\"). "
        "A long-arc callback to an earlier act is welcome when the research supports it. You may also set "
        "up the NEXT MACHINE with your final line when a real shared fact exists. No invented causal links "
        "between machines that the research doesn't support. Report the machine you bridged to in "
        "bridged_to (or null).\n\n"
        "Forbidden: spec dumps; Wikipedia-style openings (\"The X was a [type] built by [company] in "
        "[year]\"); ANY sentence, not just the opener, that could appear in a Wikipedia article unchanged; "
        "list-writing (\"It had... it also had...\"); timeline/chronological-listing structure (\"First "
        "produced in 1942... modified in 1943... retired in 1957...\"); ending on a retirement date; hype "
        "(\"incredible,\" \"arguably,\" \"undoubtedly\"); generic praise (\"legendary,\" \"iconic,\" "
        "\"revolutionary,\" \"game-changing\"); a summary/conclusion sentence that restates rather than "
        "lands; orphan facts - any number that doesn't answer why it was designed this way, what problem "
        "it solved, or what consequence it created.\n\n"
        f"{terminology}"
        f"BRIEF:\n{brief_markdown}\n"
        f"{_prior_paragraphs_block(prior_paragraphs)}"
        f"{_next_machine_block(next_machine)}\n"
        "Return only JSON: " + _OUTPUT_SHAPE + "\n"
        "claim_map: one row per sentence that states a checkable fact. Cite the fact by its FACT ID from "
        "the list at the top of the BRIEF - do NOT write a source_url and do NOT write a quote; the quote "
        "is attached from the brief by code, so a quote you type would be ignored. Cite the id whose fact "
        "actually supports that sentence. If no fact in the brief supports a sentence, leave the sentence "
        "out of claim_map (the landing line is usually argued synthesis and needs no row). "
        "opened_with_name: true only if the first words are this machine's name or designation."
    )


# ---------------------------------------------------------------------------
# Brief: rebuilt from the saved Call-3 package (the packet itself is never persisted)
# ---------------------------------------------------------------------------


def brief_for_machine(payload: dict, machine: str) -> Optional[dict]:
    """The machine's 6-slot research packet, or None when no v2 packet is saved."""
    from pipeline_executor import _verified_source_package_for_machine
    from dvsu_research_v2 import packet_from_verified_source_package

    package = _verified_source_package_for_machine(payload if isinstance(payload, dict) else {}, machine)
    if not isinstance(package, dict):
        return None
    return packet_from_verified_source_package(machine, package)


def brief_markdown(brief: dict) -> str:
    from dvsu_research_v2 import _machine_packet_markdown
    return _machine_packet_markdown(brief)


def brief_fingerprint(machine: str, brief: Optional[dict]) -> str:
    """Identity of the research content a block was written from (act number excluded)."""
    content = {k: v for k, v in (brief or {}).items() if k not in ("act_number", "machine")}
    return hashlib.sha256(json.dumps(
        {"machine": machine, "brief": content, "contract": SCRIPT_CONTRACT},
        sort_keys=True, ensure_ascii=False, default=str,
    ).encode("utf-8")).hexdigest()


# DvsU_Script_Writing_System.md's opener menu. Allocated per scene rather
# than measured after the fact: rotating by scene guarantees no two adjacent
# paragraphs are assigned the same kind of opening, which is the actual
# failure the deleted name-opener detector was never able to see (scenes 14
# and 15 of the submarine video both opened "Nautilus's 1955 trials...").
OPENER_TYPES = (
    "a date or event",
    "a problem or need",
    "a paradox or irony",
    "a human detail",
    "a consequence",
    "a contrast",
    "a principle or idea",
)


def assigned_opener(scene: int) -> tuple[str, str, str]:
    """(assigned, alternate, previous) opener kinds for this scene."""
    index = max(1, int(scene or 1)) - 1
    return (
        OPENER_TYPES[index % len(OPENER_TYPES)],
        OPENER_TYPES[(index + 3) % len(OPENER_TYPES)],
        OPENER_TYPES[(index - 1) % len(OPENER_TYPES)] if index else "",
    )


_FACT_SLOTS = ("problem", "design", "trade_off", "surprising_fact", "contrast")


def brief_facts(brief: dict) -> dict[str, dict]:
    """Every citable fact in the brief, keyed by a stable id.

    The writer cites these ids and never writes a quote; code attaches the
    source_url and the verbatim quote afterwards. A model that never types a
    quote cannot pair one with a sentence it does not support - which is what
    happened on 2026-09-22, when drafts quoted the brief's own summary prose
    (and, for Barracuda, a quote about deck guns backing a speed claim).
    """
    facts: dict[str, dict] = {}
    if not isinstance(brief, dict):
        return facts
    for slot in _FACT_SLOTS:
        entry = brief.get(slot)
        if isinstance(entry, dict) and entry.get("answer") and entry.get("source_url"):
            facts[slot] = {
                "source_url": str(entry["source_url"]).strip(),
                "quote": " ".join(str(entry.get("quote") or "").split()),
            }
    for index, entry in enumerate(brief.get("outcome_candidates") or [], start=1):
        if isinstance(entry, dict) and entry.get("fact") and entry.get("source_url"):
            facts[f"outcome{index}"] = {
                "source_url": str(entry["source_url"]).strip(),
                "quote": " ".join(str(entry.get("quote") or "").split()),
            }
    return facts


_SLOT_TITLES = {
    "problem": "Problem", "design": "Design", "trade_off": "Trade-off",
    "surprising_fact": "Surprising fact", "contrast": "Contrast",
}


def brief_markdown_with_fact_ids(brief: dict) -> str:
    """The writer's brief: each fact is its source's own words, labelled by the id the writer cites.

    The research model's summary (``answer``/``fact``) is left out on purpose.
    On the battleship run 34 claims had drifted from their sources (a wrong
    date, a sibling ship's fact, an added figure) and in all 34 the drift
    lived in that summary, never in the verbatim quote. The summary stays on
    the packet for labels and the Drive export; the writer only reads quotes.
    """
    facts = brief_facts(brief)
    lines = [
        "FACT IDS (cite these in claim_map; do NOT write quotes yourself):",
        *(f"  {fact_id} -> {value['source_url']}" for fact_id, value in facts.items()),
        "",
        f"# {(brief or {}).get('machine') or ''}",
        "",
    ]

    def _fact(fact_id: str, heading: str) -> None:
        lines.append(heading)
        lines.append("")
        fact = facts.get(fact_id)
        lines.append(f"[{fact_id}] {fact['source_url']}\n> {fact['quote']}" if fact else "(none)")
        lines.append("")

    for slot in ("problem", "design", "trade_off"):
        _fact(slot, f"## {_SLOT_TITLES[slot]}")
    outcome_ids = [fact_id for fact_id in facts if fact_id.startswith("outcome")]
    lines.append("## Outcome candidates")
    lines.append("")
    if not outcome_ids:
        lines.append("(none)")
    for fact_id in outcome_ids:
        lines.append(f"- [{fact_id}] {facts[fact_id]['source_url']}\n  > {facts[fact_id]['quote']}")
    lines.append("")
    for slot in ("surprising_fact", "contrast"):
        _fact(slot, f"## {_SLOT_TITLES[slot]}")
    return "\n".join(lines).rstrip() + "\n"


_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_TENS_RE = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_ONES_RE = "one|two|three|four|five|six|seven|eight|nine"
_DESIGNATION_RE = re.compile(r"\b[A-Za-z]{1,5}[-\u2013]\d+\b")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_COMPOUND_NUMBER_RE = re.compile(r"\b(" + _TENS_RE + r")[-\s](" + _ONES_RE + r")\b")


def _normalize_number(token: str) -> str:
    token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token.lstrip("0") or "0"


def _figures(text: str) -> set[str]:
    """Every number in the text, with spelled-out forms folded into digits.

    Machine designations (A-7, SS-163, V-1) are stripped first: their digits
    are part of a name, not a quantity.
    """
    body = _DESIGNATION_RE.sub(" ", str(text or ""))
    found = {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(body)}
    low = _COMPOUND_NUMBER_RE.sub(
        lambda m: " %d " % (_WORD_NUMBERS[m.group(1)] + _WORD_NUMBERS[m.group(2)]), body.lower()
    )
    found |= {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(low)}
    for word, value in _WORD_NUMBERS.items():
        if re.search(r"\b" + word + r"\b", low):
            found.add(str(value))
    return found


def _is_specific(token: str) -> bool:
    """Decimals, years and numbers >= 100 - figures a paragraph cannot invent.

    Small integers are excluded because that is where an author's own
    arithmetic lives: "forty seconds longer" is a correct reading of a brief
    that says 100 seconds versus 60, and must not be called a fabrication.
    """
    return "." in token or len(token.replace(".", "")) >= 3


def unsupported_figures(paragraph: str, brief: dict) -> list[str]:
    """Specific figures the paragraph states that appear NOWHERE in the brief.

    Measured against the WHOLE brief, not against one cited quote. A sentence
    legitimately synthesises across slots while citing the single most
    relevant fact, so a per-quote comparison flags ordinary good writing
    (20% of the submarine video's shipped rows). Against the whole brief the
    same 88 rows flag 0%, which is the point: anything left is a figure the
    research never contained.

    Advisory. Nothing here blocks a paragraph.
    """
    known = _figures(brief_markdown(brief)) if isinstance(brief, dict) else set()
    return sorted(
        figure for figure in _figures(paragraph) - known if _is_specific(figure)
    )


def brief_source_urls(brief: dict) -> set[str]:
    urls: set[str] = set()
    for slot in ("problem", "design", "trade_off", "surprising_fact", "contrast"):
        entry = brief.get(slot) if isinstance(brief, dict) else None
        if isinstance(entry, dict) and entry.get("source_url"):
            urls.add(str(entry["source_url"]).strip())
    for entry in (brief.get("outcome_candidates") or []) if isinstance(brief, dict) else []:
        if isinstance(entry, dict) and entry.get("source_url"):
            urls.add(str(entry["source_url"]).strip())
    return urls


# ---------------------------------------------------------------------------
# Word count (informational only - reported on the block, never gates it)
# ---------------------------------------------------------------------------


def word_count(text: str) -> int:
    """Deterministic spoken word count: designations like B-52 and contractions are one token."""
    return len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", str(text or "")))


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


# ---------------------------------------------------------------------------
# Draft normalization
# ---------------------------------------------------------------------------


def _normalize_draft(raw: Any, brief: dict, roster: list[str], machine: str) -> tuple[Optional[dict], list[str]]:
    """Coerce a model response into {paragraph, claim_map, opened_with_name, bridged_to}."""
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, ["writer returned no JSON object"]
    paragraph = " ".join(str(raw.get("paragraph") or "").split())
    if not paragraph:
        return None, ["writer returned an empty paragraph"]
    # The quote is ALWAYS attached here from the brief, never taken from the
    # model. A row cites a fact_id; an older-shape row citing only a
    # source_url is resolved when that url identifies exactly one fact.
    # Anything the model typed as a quote is discarded.
    facts = brief_facts(brief)
    by_url: dict[str, list[str]] = {}
    for fact_id, value in facts.items():
        by_url.setdefault(value["source_url"], []).append(fact_id)
    claim_map: list[dict] = []
    unknown = 0
    for row in raw.get("claim_map") or []:
        if not isinstance(row, dict):
            continue
        sentence = " ".join(str(row.get("sentence") or "").split())
        if not sentence:
            continue
        fact_id = str(row.get("fact_id") or "").strip()
        if fact_id not in facts:
            source_url = str(row.get("source_url") or "").strip()
            candidates = by_url.get(source_url) or []
            fact_id = candidates[0] if len(candidates) == 1 else ""
        if not fact_id:
            unknown += 1
            continue
        fact = facts[fact_id]
        claim_map.append({
            "sentence": sentence,
            "fact_id": fact_id,
            "source_url": fact["source_url"],
            "quote": fact["quote"],
        })
    if unknown:
        warnings.append(
            f"{unknown} claim_map row(s) named no fact in the brief and were dropped"
        )
    bridged_to = raw.get("bridged_to")
    bridged_name: Optional[str] = None
    if isinstance(bridged_to, str) and bridged_to.strip():
        wanted = _squash(bridged_to)
        for candidate in roster:
            if candidate == machine:
                continue
            if _squash(candidate) == wanted or (wanted and (wanted in _squash(candidate) or _squash(candidate) in wanted)):
                bridged_name = candidate
                break
        if bridged_name is None:
            warnings.append(f"bridged_to named '{bridged_to}', which is not another machine in this roster")
    return {
        "paragraph": paragraph,
        "claim_map": claim_map,
        "opened_with_name_reported": bool(raw.get("opened_with_name")),
        "bridged_to": bridged_name,
    }, warnings


# ---------------------------------------------------------------------------
# One machine: write, assemble the block
# ---------------------------------------------------------------------------


async def _generate(client: Any, prompt: str, checkpoint_scope: Optional[dict]) -> Any:
    from orchestrator.pipeline_constants import Models
    from shared.json_utils import parse_json_response
    from shared.research_response import checkpoint_path, request_fingerprint

    model = Models.CLAUDE_SONNET
    max_tokens = 1400
    # Deterministic output (2026-09-22). The same brief must produce the same
    # paragraph on every run: a rerun should be a no-op, not a re-roll. Any
    # sampling here turns quality into a dice roll, which is what the deleted
    # code-side checker was built to paper over. Temperature also feeds
    # request_fingerprint below, so the checkpoint/relay cache keys on it.
    temperature = 0.0
    response = await client.generate(
        prompt=prompt, system_prompt=SYSTEM_PROMPT, model=model,
        max_tokens=max_tokens, temperature=temperature, complete_response=True,
        checkpoint_path=checkpoint_path(checkpoint_scope, request_fingerprint(
            prompt=prompt, system_prompt=SYSTEM_PROMPT, model=model,
            max_tokens=max_tokens, temperature=temperature, tools=None,
        )),
    )
    return parse_json_response(response, default=None), model


async def write_paragraph(
    client: Any,
    *,
    title: str,
    thesis: str,
    acts: list[dict],
    roster: list[str],
    machine: str,
    scene: int,
    act_number: int,
    brief: dict,
    prior_paragraphs: list[dict],
    next_machine: Optional[dict],
    checkpoint_scope: Optional[dict] = None,
) -> dict:
    """One paid call; returns the block dict. Nothing here can reject a paragraph."""
    act_thesis = next(
        (str(a.get("argument") or "") for a in acts if isinstance(a, dict) and int(a.get("act_number") or 0) == int(act_number)),
        "",
    )
    write_prompt = build_write_prompt(
        title=title, thesis=thesis, acts=acts, machine=machine, act_number=act_number, act_thesis=act_thesis,
        scene=scene, roster_size=len(roster), brief_markdown=brief_markdown_with_fact_ids(brief),
        prior_paragraphs=prior_paragraphs, next_machine=next_machine,
    )
    raw, model = await _generate(client, write_prompt, checkpoint_scope)
    draft, warnings = _normalize_draft(raw, brief, roster, machine)
    attempts = 1
    if draft is None:
        # Nothing parseable came back. That is a transport failure, not a
        # quality judgement - there is no paragraph to surface, so the block
        # is marked unusable and the caller leaves the scene alone.
        draft = {"paragraph": "", "claim_map": [], "opened_with_name_reported": False, "bridged_to": None}

    fabricated = unsupported_figures(draft["paragraph"], brief)
    if fabricated:
        # Advisory only - surfaced next to the paragraph for a human to judge.
        warnings.append(
            "[[user-facing]] figure(s) not found anywhere in this machine's research: "
            + ", ".join(fabricated)
        )

    return {
        "machine": machine,
        "scene": scene,
        "act_number": act_number,
        "paragraph": draft["paragraph"],
        "word_count": word_count(draft["paragraph"]),
        # `passed` now means only "there is a usable paragraph here". Quality
        # is never judged in code: a written paragraph always passes.
        "passed": bool(draft["paragraph"].strip()),
        "warnings": list(dict.fromkeys(warnings)),
        "violations": [] if draft["paragraph"].strip() else list(dict.fromkeys(warnings)),
        "claim_map": draft["claim_map"],
        "opened_with_name": bool(draft["opened_with_name_reported"]),
        "bridged_to": draft["bridged_to"],
        "machine_script_contract": SCRIPT_CONTRACT,
        "research_source": RESEARCH_SOURCE,
        "source_fingerprint": brief_fingerprint(machine, brief),
        "subject_context": str(title or ""),
        "model": model,
        "attempts": attempts,
        "saved": False,
    }


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def _object(value: Any) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def saved_blocks(video: dict) -> dict:
    blocks = _object(video.get("script_validation")).get("machine_script_blocks")
    return blocks if isinstance(blocks, dict) else {}


def _block_for(blocks: dict, machine: str) -> dict:
    block = blocks.get(machine)
    if isinstance(block, dict):
        return block
    wanted = _squash(machine)
    for key, candidate in blocks.items():
        if isinstance(candidate, dict) and (_squash(str(key)) == wanted or _squash(str(candidate.get("machine") or "")) == wanted):
            return candidate
    return {}


def block_is_current(block: Any, machine: str, scene: int, subject_context: str, fingerprint: str) -> bool:
    if not isinstance(block, dict):
        return False
    return bool(
        block.get("passed") is True
        and str(block.get("paragraph") or "").strip()
        and block.get("machine_script_contract") == SCRIPT_CONTRACT
        and int(block.get("scene") or 0) == int(scene)
        and str(block.get("subject_context") or "") == str(subject_context or "")
        and block.get("source_fingerprint") == fingerprint
    )


def preview_readiness(payload: dict, machine: str) -> dict:
    """No-spend check: can this machine be written right now?"""
    brief = brief_for_machine(payload, machine)
    if brief is None:
        msg = (f"No DVSU v2 research packet is saved for {machine}; run per-machine research "
               "(Research tab) before writing its paragraph.")
        return {"ready": False, "summary": msg, "warnings": [msg], "next_action": "run_one_machine_research_refresh"}
    return {"ready": True, "summary": "Machine script preview is ready.", "warnings": [],
            "next_action": "run_machine_script_preview"}


def script_readiness(video: dict, roster: list[str]) -> bool:
    """Every locked machine has a saved, passed, current v2 block for this exact subject and brief."""
    payload = _object(video.get("research_payload"))
    blocks = saved_blocks(video)
    subject_context = str(video.get("video_title") or video.get("headline") or "")
    if not roster:
        return False
    for scene, machine in enumerate(roster, 1):
        brief = brief_for_machine(payload, machine)
        if brief is None:
            return False
        if not block_is_current(_block_for(blocks, machine), machine, scene, subject_context, brief_fingerprint(machine, brief)):
            return False
    return True


# ---------------------------------------------------------------------------
# Context assembly (stateful, roster order)
# ---------------------------------------------------------------------------


def _roster_act_numbers(payload: dict, roster: list[str]) -> dict[str, int]:
    from pipeline_executor import _unit_display_name

    by_machine: dict[str, int] = {}
    for row in payload.get("unit_roster") or []:
        if not isinstance(row, dict):
            continue
        name = _unit_display_name(row.get("machine") or row.get("name") or row)
        try:
            act = int(row.get("act_number") or 0)
        except (TypeError, ValueError):
            act = 0
        if name:
            by_machine[name] = act
    return {machine: by_machine.get(machine, 0) for machine in roster}


def _prior_context(
    roster: list[str], scene: int, blocks: dict, previews: dict, subject_context: str, act_numbers: dict[str, int],
    written_this_run: dict[str, dict],
) -> list[dict]:
    """Every earlier-scene paragraph that is current (this run > saved block > saved preview)."""
    prior: list[dict] = []
    for earlier_scene in range(1, scene):
        earlier = roster[earlier_scene - 1]
        candidate = written_this_run.get(earlier)
        if not isinstance(candidate, dict) or not candidate.get("passed"):
            candidate = _block_for(blocks, earlier)
            if not (isinstance(candidate, dict) and candidate.get("passed") is True and candidate.get("paragraph")):
                candidate = None
        if candidate is None:
            preview = _block_for(previews, earlier)
            if isinstance(preview, dict) and preview.get("passed") is True and preview.get("paragraph") \
                    and preview.get("machine_script_contract") == SCRIPT_CONTRACT:
                candidate = preview
        if not candidate:
            continue
        paragraph = " ".join(str(candidate.get("paragraph") or "").split())
        prior.append({"machine": earlier, "act_number": act_numbers.get(earlier, 0), "paragraph": paragraph})
    return prior


def _next_machine_context(payload: dict, roster: list[str], scene: int, act_numbers: dict[str, int]) -> Optional[dict]:
    if scene >= len(roster):
        return None
    machine = roster[scene]
    brief = brief_for_machine(payload, machine)
    problem = str(((brief or {}).get("problem") or {}).get("quote") or "") if brief else ""
    return {"machine": machine, "act_number": act_numbers.get(machine, 0), "problem": problem}


# ---------------------------------------------------------------------------
# The hold: bulk (roster order, checkpointed) or one machine (preview / block)
# ---------------------------------------------------------------------------


async def _cancelled(ex: Any) -> bool:
    cancel = getattr(getattr(ex, "_pipeline", None), "should_cancel", None)
    if not callable(cancel):
        return False
    value = cancel()
    if inspect.isawaitable(value):
        value = await value
    return bool(value)


def _over_budget(video: dict) -> bool:
    cap = video.get("max_spend")
    return cap is not None and float(video.get("total_cost") or 0) >= float(cap)


async def run_script_hold(
    ex: Any, video_id: str, video: dict, roster: list[str],
    target_machine: Optional[str] = None, save_target_script: bool = False,
) -> dict:
    """The one script path for static-docu videos with a locked machine roster.

    ``target_machine`` set + ``save_target_script`` False: write ONE paragraph,
    checkpoint it as a preview, touch no script rows (``{"status", "preview"}``).
    ``target_machine`` set + ``save_target_script`` True: same, then save it as
    the real scene when it passes (``{"status", "script_block"}``).
    No target: walk the whole roster in order, reuse blocks that are already
    current (no spend), write the rest, checkpoint each one, and advance to
    ready_for_voice only when every machine has a current passed block.
    """
    from pipeline_executor import (
        _locked_roster_item_for_machine, _machine_documentary_hold_roster, _verified_source_cache_key,
        execute, fetch_all,
    )

    bot_name = "Script Bot"
    matched = _locked_roster_item_for_machine(roster, target_machine) if target_machine else None
    if target_machine and not matched:
        return {"status": "failed", "error": f"Machine is not in the locked roster: {target_machine}", "video_id": video_id}
    selected = [(i, m) for i, m in enumerate(roster, 1) if not matched or m == matched]

    client = getattr(getattr(ex, "_pipeline", None), "anthropic", None)
    if client is None:
        msg = "Script-hold requires an Anthropic client, but none is configured."
        await ex._log_activity(bot_name, video_id, "failed", msg)
        return {"status": "failed", "error": msg, "video_id": video_id}

    payload = _object(video.get("research_payload"))
    payload = await ex._load_machine_research_cards(video_id, payload, roster, target_machine=matched)
    title = str(video.get("video_title") or video.get("headline") or "")
    thesis = str(payload.get("thesis") or "")
    acts = [a for a in (payload.get("acts") or []) if isinstance(a, dict)]
    act_numbers = _roster_act_numbers(payload, roster)
    locked_roster_snapshot = json.dumps(payload.get("unit_roster"), sort_keys=True, ensure_ascii=False)
    checkpoint_scope = {"tenant_id": ex.tenant_id, "video_id": video_id}

    rows = await fetch_all(
        "SELECT voice_id FROM scripts WHERE video_id = $1 AND tenant_id = $2 LIMIT 1", video_id, ex.tenant_id,
    )
    voice_id = (rows[0].get("voice_id") if rows else None) or DEFAULT_VOICE_ID

    await ex._log_activity(
        bot_name, video_id, "started",
        f"DVSU script v2: writing {len(selected)} of {len(roster)} machine paragraph(s) in roster order",
    )

    written: dict[str, dict] = {}
    results: list[dict] = []
    failures: list[str] = []

    async def _checkpoint_preview(block: dict) -> Optional[dict]:
        write = await ex._checkpoint_machine_script_preview(
            video_id, _verified_source_cache_key(block["machine"]), block, locked_roster_snapshot,
        )
        if ex._db_write_missed(write):
            return {"status": "failed", "error": "persisted unit_roster changed concurrently; script preview save refused",
                    "video_id": video_id}
        previews = payload.get("machine_script_previews") if isinstance(payload.get("machine_script_previews"), dict) else {}
        payload["machine_script_previews"] = {**previews, _verified_source_cache_key(block["machine"]): block}
        return None

    def _target_result(block: dict) -> dict:
        key = "script_block" if save_target_script else "preview"
        return {"status": "completed", "video_id": video_id, key: block, "research_payload": payload}

    for scene, machine in selected:
        fresh = await ex._get_video(video_id)
        if not fresh:
            return {"status": "failed", "error": "Video disappeared", "video_id": video_id}
        if _machine_documentary_hold_roster(fresh) != [str(m) for m in roster]:
            return {"status": "failed", "error": "Locked roster changed during script generation", "video_id": video_id}
        if _over_budget(fresh):
            return {"status": "paused", "message": "Video budget reached; completed sections are saved.", "video_id": video_id}
        if await _cancelled(ex):
            return {"status": "cancelled", "message": "Stopped; completed sections are saved.", "video_id": video_id}

        blocks = saved_blocks(fresh)
        previews = payload.get("machine_script_previews") if isinstance(payload.get("machine_script_previews"), dict) else {}
        brief = brief_for_machine(payload, machine)
        if brief is None:
            readiness = preview_readiness(payload, machine)
            block = {
                "machine": machine, "scene": scene, "act_number": act_numbers.get(machine, 0), "paragraph": "",
                "word_count": 0, "passed": False, "warnings": list(readiness["warnings"]),
                "violations": list(readiness["warnings"]), "claim_map": [], "opened_with_name": False,
                "bridged_to": None, "machine_script_contract": SCRIPT_CONTRACT, "research_source": "preview_error",
                "source_fingerprint": "", "subject_context": title, "saved": False,
            }
            await ex._log_activity(bot_name, video_id, "failed", readiness["summary"][:900])
            failures.append(f"{machine}: {readiness['summary']}")
            results.append(block)
            if matched:
                refused = await _checkpoint_preview(block)
                return refused or _target_result(block)
            continue

        fingerprint = brief_fingerprint(machine, brief)
        saved = _block_for(blocks, machine)
        if not matched and block_is_current(saved, machine, scene, title, fingerprint):
            # Bulk runs never pay to rewrite a paragraph that is already
            # current. A single-machine press is an explicit paid regenerate.
            written[machine] = saved
            results.append(saved)
            await ex._log_activity(bot_name, video_id, "running", f"Paragraph {scene}/{len(roster)} reused (current): {machine}")
            continue

        prior = _prior_context(roster, scene, blocks, previews, title, act_numbers, written)
        next_machine = _next_machine_context(payload, roster, scene, act_numbers)
        await ex._log_activity(
            bot_name, video_id, "running",
            f"Writing paragraph {scene}/{len(roster)}: {machine} (act {act_numbers.get(machine, 0)}, "
            f"{len(prior)} prior paragraph(s) in context)",
        )
        block = await write_paragraph(
            client, title=title, thesis=thesis, acts=acts, roster=roster, machine=machine, scene=scene,
            act_number=act_numbers.get(machine, 0), brief=brief, prior_paragraphs=prior, next_machine=next_machine,
            checkpoint_scope=checkpoint_scope,
        )
        refused = await _checkpoint_preview(block)
        if refused:
            return refused

        if not block["passed"]:
            # Reached only when the writer returned nothing usable at all.
            # No quality rule can land here - there is simply no text to save.
            reason = "; ".join(block["warnings"] or ["writer returned no usable paragraph"])
            failures.append(f"{machine}: {reason}")
            results.append(block)
            await ex._log_activity(bot_name, video_id, "failed", f"No paragraph written: {machine}: {reason}"[:800])
            if matched:
                return _target_result(block)
            continue

        if not matched or save_target_script:
            block = await ex._save_machine_script_block(
                video_id=video_id, video=fresh, roster=roster, script_block=block, title=title, voice_id=voice_id,
                advance_status=bool(matched),
            )
            readback = await ex._get_video(video_id) or {}
            stored = _block_for(saved_blocks(readback), machine)
            if stored.get("paragraph") != block.get("paragraph") or stored.get("source_fingerprint") != fingerprint:
                return {"status": "failed", "error": f"Script block save could not be verified: {machine}", "video_id": video_id}
            await ex._log_activity(bot_name, video_id, "completed", f"Paragraph {scene}/{len(roster)} saved: {machine}")
        else:
            await ex._log_activity(bot_name, video_id, "completed", f"Paragraph preview passed: {machine}")
        written[machine] = block
        results.append(block)
        if matched:
            return _target_result(block)

    if failures:
        return {"status": "needs_review", "error": " | ".join(failures), "units": results, "video_id": video_id}
    final = await ex._get_video(video_id) or {}
    if not script_readiness(final, roster):
        return {"status": "failed", "error": "Saved script completeness could not be verified", "video_id": video_id}
    new_status = ex._skip_disabled_next(final, "ready_for_voice")
    updated = await execute(
        "UPDATE videos SET status=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3", new_status, video_id, ex.tenant_id,
    )
    if ex._db_write_missed(updated):
        return {"status": "failed", "error": "Script completion status was not saved", "video_id": video_id}
    await ex._log_transition(video_id, final.get("status"), new_status, "api")
    await export_script_to_drive_fail_soft(title, roster, saved_blocks(final), act_numbers)
    return {"status": "completed", "video_id": video_id, "units": results,
            "script": final.get("script"), "new_status": new_status}


# ---------------------------------------------------------------------------
# Hand-written door (the old G23a submit path)
# ---------------------------------------------------------------------------


def submitted_block(video: dict, roster: list[str], machine: str, paragraph: str) -> dict:
    """Wrap a hand-written paragraph as a block; no model call, no grading."""
    payload = _object(video.get("research_payload"))
    title = str(video.get("video_title") or video.get("headline") or "")
    scene = roster.index(machine) + 1
    act_numbers = _roster_act_numbers(payload, roster)
    brief = brief_for_machine(payload, machine)
    text = " ".join(str(paragraph or "").split())
    return {
        "machine": machine, "scene": scene, "act_number": act_numbers.get(machine, 0), "paragraph": text,
        "word_count": word_count(text), "passed": True,
        "warnings": [],
        "violations": [], "claim_map": [], "opened_with_name": False,
        "bridged_to": None, "machine_script_contract": SCRIPT_CONTRACT, "research_source": "hand_submitted",
        "source_fingerprint": brief_fingerprint(machine, brief), "subject_context": title, "saved": False,
    }


# ---------------------------------------------------------------------------
# Drive export (fail-soft) - 02-script.md next to the research files
# ---------------------------------------------------------------------------


def script_markdown(title: str, roster: list[str], blocks: dict, act_numbers: dict[str, int]) -> str:
    lines = [f"# {title} - Script", ""]
    for scene, machine in enumerate(roster, 1):
        block = _block_for(blocks, machine)
        lines.append(f"### {scene}. {machine} (Act {act_numbers.get(machine, 0)})")
        lines.append("")
        lines.append(str(block.get("paragraph") or "(not written)"))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _export_script_to_drive(title: str, roster: list[str], blocks: dict, act_numbers: dict[str, int]) -> dict:
    from shared.clients.google_client import GoogleClient
    from dvsu_roster_v2 import research_root_folder

    client = GoogleClient(strict_folder=True)
    root = research_root_folder(client)
    folder = client.get_or_create_folder(title or "Untitled", parent_id=root["id"])
    uploaded = client.upload_file(
        script_markdown(title, roster, blocks, act_numbers).encode("utf-8"),
        "02-script.md", folder["id"], mime_type="text/markdown",
    )
    return {"folder_id": folder["id"], "file_id": uploaded.get("id")}


async def export_script_to_drive_fail_soft(title: str, roster: list[str], blocks: dict, act_numbers: dict[str, int]) -> Optional[dict]:
    """Best-effort Drive export. Never allowed to block or fail script generation."""
    try:
        exported = await asyncio.to_thread(_export_script_to_drive, title, roster, blocks, act_numbers)
        logger.info("DVSU script exported to Drive for %r: %s", title, exported)
        return exported
    except Exception as exc:  # noqa: BLE001 - intentional fail-soft boundary
        logger.warning("DVSU script Drive export failed for %r: %s", title, str(exc)[:240])
        return None
