"""Generic script-quality critic (checklist C46a).

**This formalizes existing law, it does not replace it.** Ryan's prior
sessions already built the two pieces this module generalizes:

  1. ``originality.grade_script`` / ``grade_script_with_client`` — a single
     fail-open Claude call that grades a freshly written script against five
     universal retention gates (hook speed, but/therefore causality,
     escalation, payoff, specificity) and returns a verdict
     (pass/revise/regenerate) plus concrete rewrite guidance. This module's
     ``critique_script`` reuses that system prompt and user-prompt builder
     VERBATIM (imported from ``originality``, not re-typed) and only adds an
     optional second grading pass against a channel's own rules text.

  2. The DvsU PLAN->WRITE->EDIT harness's proven EDIT loop
     (``pipeline_executor.py``'s ``_run_static_script_hold``, ~L10486-10518):
     on a failing draft, resend the SAME draft with ONLY the named
     violations named — never a fresh re-roll — bounded at 2 rounds, then
     the caller marks the result ``needs_review``. ``edit_draft_with_violations``
     generalizes that exact prompt pattern (still "change ONLY what the
     violations name; keep every other word") from DvsU's 5-sentence
     paragraph shape to an arbitrary multi-scene script, using the SAME
     ``@@@SCENE n@@@`` sentinel format the modeled-script path and
     ``user_script.py`` already use to round-trip scene boundaries through a
     single text blob — so this module needs no pipeline_executor import to
     stay decoupled (mirrors originality.py's own decoupling contract).

``run_critique_and_edit`` is the orchestrator: grade once, and only on
'revise' run the bounded same-draft edit loop; only on 'regenerate' (broadly
weak, no targeted fix helps) invoke the caller's one-fresh-reroll callback.
Still failing after those bounds -> ``needs_review`` (the caller decides what
that means for its own status field; DvsU's own convention, e.g.
``_save_machine_script_block``'s ``all_passed`` gate, is "do not advance the
video's stage, attach the violations, let a human or a re-run fix it").

Everything here is internal-only, fails OPEN, and is niche-safe. No user
facing gate/block/warning is produced directly by this module.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel, Field, field_validator

from database import fetch_one  # noqa: F401 - see _fetch_story_bible (D10-3b)
from originality import (
    _SCRIPT_JUDGE_SYSTEM,
    _build_script_judge_user_prompt,
    _extract_json,
)

# DvsU's proven bound (pipeline_executor._run_static_script_hold's own EDIT
# loop: `while _blocking_warnings(warnings) and edit_round < 2`).
MAX_EDIT_ROUNDS = 2


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

class RuleVerdict(BaseModel):
    """One per-rule grading result, when the critic was given rules_text."""

    rule: str = ""
    passed: bool = True
    note: str = ""


class CritiqueResult(BaseModel):
    """Same shape as ``originality.ScriptGrade``, extended with per-rule
    verdicts. Kept field-compatible on purpose so existing consumers of a
    grade object (``_record_applied_retention``) need no changes."""

    verdict: str = "pass"                 # pass | revise | regenerate (internal)
    score: int = 100                      # 0-100 overall
    failing_gates: List[str] = Field(default_factory=list)
    rewrite_guidance: str = ""            # concrete, actionable fixes
    rule_verdicts: List[RuleVerdict] = Field(default_factory=list)

    @field_validator("rewrite_guidance", mode="before")
    @classmethod
    def _coerce_guidance(cls, v):
        # Mirrors originality.ScriptGrade: the judge sometimes returns a list
        # instead of one string - join it rather than fail the whole grade.
        if isinstance(v, list):
            return "\n".join(str(x).strip() for x in v if str(x).strip())
        return "" if v is None else v

    @field_validator("rule_verdicts", mode="before")
    @classmethod
    def _coerce_rule_verdicts(cls, v):
        if not v:
            return []
        out: List[Dict[str, Any]] = []
        for item in v:
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, str) and item.strip():
                out.append({"rule": item.strip(), "passed": False, "note": ""})
        return out

    @property
    def needs_revision(self) -> bool:
        return (self.verdict or "").strip().lower() in ("revise", "regenerate")

    @property
    def failed_rule_names(self) -> List[str]:
        return [rv.rule for rv in self.rule_verdicts if not rv.passed and rv.rule]

    @property
    def violations(self) -> List[str]:
        """Everything worth naming to a writer/human: universal failing gates
        plus any failed channel-rule names. Falls back to the free-text
        rewrite_guidance when the judge gave no discrete gate/rule list (still
        actionable, just not machine-checkable one-by-one)."""
        names = list(self.failing_gates) + self.failed_rule_names
        if names:
            return names
        return [self.rewrite_guidance.strip()] if self.rewrite_guidance.strip() else []


# ---------------------------------------------------------------------------
# Plain-English translation (checklist C-frontdoor2, 2026-07-27)
#
# The judge's `failing_gates` names the five universal gates from its own
# system prompt (_SCRIPT_JUDGE_SYSTEM in originality.py: "HOOK SPEED",
# "CAUSALITY", "ESCALATION", "PAYOFF", "SPECIFICITY") — internal jargon never
# meant for a human to read (the class docstring says so: "Never surfaced to
# the creator"). A needs_review verdict changes that: the creator now DOES
# see why, so the internal gate key must never leak through as-is (a live
# repro showed exactly `gates=['hook_speed', 'escalation']` reaching the
# task-status message). This is intentionally forgiving about the judge's
# exact casing/spelling (underscores, spaces, capitalized words) since the
# model is free-text, not a strict enum — anything not recognized falls back
# to a de-slugged version of whatever the judge said, never a raw crash or a
# blank line.
# ---------------------------------------------------------------------------

_GATE_PLAIN_ENGLISH: Dict[str, str] = {
    "hook_speed": "the opening is slow to hook the viewer",
    "hook": "the opening is slow to hook the viewer",
    "causality": "the beats don't connect with a clear cause and effect",
    "but_therefore": "the beats don't connect with a clear cause and effect",
    "but_therefore_causality": "the beats don't connect with a clear cause and effect",
    "escalation": "the story doesn't escalate — it plateaus or sags partway through",
    "payoff": "the opening's promise never pays off by the end",
    "specificity": "the script leans on vague, generic language instead of concrete details",
}


def plain_english_violation(name: str) -> str:
    """One violation name -> a plain-English sentence fragment a creator can
    act on. Falls back to a de-slugged version of an unrecognized name
    (a channel-specific rule, or the free-text rewrite_guidance fallback)
    rather than ever showing a raw internal key or crashing."""
    raw = (name or "").strip()
    if not raw:
        return ""
    key = re.sub(r"[\s/&-]+", "_", raw.lower()).strip("_")
    if key in _GATE_PLAIN_ENGLISH:
        return _GATE_PLAIN_ENGLISH[key]
    return raw.replace("_", " ").strip()


def plain_english_violations(names: Sequence[str]) -> List[str]:
    """Same translation, applied to a whole violations list, empties dropped."""
    return [v for v in (plain_english_violation(n) for n in names) if v]


# ---------------------------------------------------------------------------
# Critic — one Claude call, universal gates + optional rules_text
# ---------------------------------------------------------------------------

def _rules_addendum(rules_text: str) -> str:
    """Appended to the universal judge prompt when rules_text is supplied.

    C46b lands the real per-channel rules table (QL/QD row shape). Until
    then, the seam accepts whatever prose rules text a caller can source
    cheaply - e.g. this tenant's `script_templates.structure` (the channel's
    house script format, already used to steer the WRITER via
    routes/script_templates.py::apply_default_template) - and asks the judge
    to extract checkable rules from it rather than assuming a strict
    line-per-rule format.
    """
    return (
        "\n\nADDITIONALLY grade against this channel's own rules text below "
        "(may be loose prose describing a house format, not a strict rule "
        "list - use judgment to extract distinct, checkable rules from it):\n"
        "--- CHANNEL RULES ---\n" + rules_text.strip() + "\n--- END CHANNEL RULES ---\n\n"
        "For each distinct rule you can extract, add one entry to "
        "\"rule_verdicts\": a failure of a channel rule alone can justify a "
        "'revise' verdict even when the universal gates above pass. If the "
        "rules text is too vague to check mechanically, return an empty "
        "rule_verdicts list rather than guessing.\n\n"
        "Return ONLY this JSON (note the added rule_verdicts field): "
        '{"verdict": "pass|revise|regenerate", "score": int, '
        '"failing_gates": [string, ...], "rewrite_guidance": string, '
        '"rule_verdicts": [{"rule": string, "passed": bool, "note": string}, ...]}'
    )


def _strict_rules_addendum(
    rules_text: str,
    rule_ids: Sequence[str],
    *,
    retry: bool = False,
) -> str:
    ids = ", ".join(rule_ids)
    retry_law = (
        "\nRETRY CONTRACT: The prior response was empty, malformed, or "
        "truncated. Return one compact JSON object on one line, no markdown. "
        "Keep every note under 16 words."
        if retry
        else ""
    )
    return (
        "\n\nADDITIONALLY grade the script against exactly these authored rule "
        f"IDs, in this exact order: {ids}.\n"
        "The rules text may contain nested explanatory prose. That prose is "
        "context for its parent rule ID, never another output rule.\n"
        "--- EXACT RULE CONTRACTS ---\n"
        + rules_text.strip()
        + "\n--- END EXACT RULE CONTRACTS ---\n"
        "Return exactly one rule_verdicts entry for each listed ID and no other "
        "rule names. A failed authored rule can justify revise even when the "
        "universal gates pass."
        + retry_law
        + "\nReturn ONLY this JSON: "
        '{"verdict":"pass|revise|regenerate","score":int,'
        '"failing_gates":[string,...],"rewrite_guidance":string,'
        '"rule_verdicts":[{"rule":"EXACT_ID","passed":bool,"note":string},...]}'
    )


def _parse_critique_result(
    raw: Any,
    *,
    strict_rule_ids: Sequence[str],
) -> CritiqueResult:
    if strict_rule_ids and not str(raw or "").strip():
        raise ValueError("empty critic response")
    decoded = json.loads(_extract_json(str(raw or "")))
    if strict_rule_ids:
        if not isinstance(decoded, Mapping):
            raise ValueError("critic JSON is not an object")
        required = {
            "verdict",
            "score",
            "failing_gates",
            "rewrite_guidance",
            "rule_verdicts",
        }
        if not required.issubset(decoded):
            raise ValueError("critic JSON is missing required fields")
    result = CritiqueResult(**decoded)
    if strict_rule_ids:
        observed = [verdict.rule for verdict in result.rule_verdicts]
        if observed != list(strict_rule_ids):
            raise ValueError(
                "critic rule verdict IDs are missing, extra, or reordered"
            )
    return result


def _safe_critique_failure_reason(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "malformed_json"
    if isinstance(exc, ValueError):
        return "invalid_or_truncated_shape"
    return "client_or_schema_error"


def _apply_rule_severity(
    result: CritiqueResult, severity_by_rule: Optional[Dict[str, str]]
) -> CritiqueResult:
    """Deterministic enforcement (checklist C46b): a rule's severity is an
    authored fact set when the rule was created/parsed, not something the
    grading call's own holistic verdict should be trusted alone to encode.
    If ANY failed rule_verdict names a rule tagged ``hard_gate`` in
    ``severity_by_rule``, the result must be at least 'revise' even when the
    judge itself returned 'pass' overall - this is what lets
    ``run_critique_and_edit``'s existing bounded edit loop (which only runs
    on ``verdict == "revise"``) actually engage for a hard-gate failure the
    judge under-called. 'warn'/'guidance' failures never force a verdict
    change on their own - they still surface via rule_verdicts/violations
    either way, informationally. No-op when severity_by_rule is empty/None
    (byte-identical to pre-C46b behavior for any caller that doesn't pass
    per-rule severity)."""
    if not severity_by_rule:
        return result
    hard_failed = any(
        not rv.passed and severity_by_rule.get(rv.rule) == "hard_gate"
        for rv in result.rule_verdicts
    )
    if hard_failed and result.verdict == "pass":
        result.verdict = "revise"
    return result


# ---------------------------------------------------------------------------
# Story-structure signal (checklist D10-3b) — the critic ALSO checks a
# script against this video's own StoryEngine-native Story Bible
# (story_bible_native.py, D10-2ab), when one exists and carries the three
# NEW top-level sections it can generate: ``narrative`` (genre/tone/themes/
# conflict/stakes/time_period/world_rules), ``relationships`` (the web of
# character dynamics), and ``arcs`` (each character's start/end state).
#
# Wiring choice: fetched HERE, inside ``critique_script`` itself, keyed off
# the ``tenant_id``/``video_id`` every caller already passes in — not
# threaded through a new parameter on ``critique_script``/
# ``run_critique_and_edit``. Every one of this module's four call sites
# (``pipeline_executor._grade_and_maybe_revise_script``,
# ``pipeline_executor._telemetry_quality_critique``,
# ``user_script.accept_external_script``,
# ``custom_film_production_runner``'s per-section quality pass) already has
# a ``video`` row in hand with ``story_bible`` on it by the time it calls in
# — but re-threading "the bible" through 4 call sites and 2 function
# signatures for one extra JSONB column is exactly the caller-signature
# churn the brief asks to avoid when the data is one indexed-PK read away.
# A video with no native bible (every video today, and any Custom Film
# section video — a different production style that never populates
# story_bible) simply gets ``None`` back and the prompt is untouched.
# ---------------------------------------------------------------------------

async def _fetch_story_bible(tenant_id: str, video_id: str) -> Optional[dict]:
    """Best-effort ``videos.story_bible`` read. Tolerant of the JSONB-as-text
    shape asyncpg returns with no jsonb codec registered — the same
    ``isinstance(sb, str)`` fallback ``scripts/coverage_to_app.py``'s
    ``_story_bible_locations`` and ``routes/characters.py``'s ``_parse_json``
    already use for this exact column.

    Raises on ANY problem (no DB reachable, missing row, malformed JSON,
    wrong shape) — deliberately not fail-open itself, so its caller's own
    try/except can log once and keep the fail-open contract local to the
    bible fetch, never letting a bible-side error escape into the critique's
    own outer fail-open (which would skip grading entirely, not just the
    story-structure addendum).
    """
    row = await fetch_one(
        "SELECT story_bible FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    sb = (row or {}).get("story_bible")
    if isinstance(sb, str):
        sb = json.loads(sb) if sb.strip() else None
    return sb if isinstance(sb, dict) else None


def _story_structure_addendum(bible: Mapping[str, Any]) -> str:
    """Render ``bible``'s ``narrative``/``relationships``/``arcs`` sections
    into a system-prompt addendum, or ``""`` when there is nothing usable.

    Returns ``""`` for BOTH shapes that must leave the assembled prompt
    byte-identical to pre-D10-3b behavior:
      - a legacy bible (no ``narrative``/``relationships``/``arcs`` keys at
        all — every bible generated before D10-2ab), and
      - a freshly-normalized native bible whose new sections are all present
        but empty (``story_bible_native.normalize_story_bible`` always adds
        these keys, even when the model contributed nothing to them — an
        explainer-style video with one character and no relationships, say).
    """
    narrative = bible.get("narrative")
    narrative = narrative if isinstance(narrative, Mapping) else {}
    relationships = bible.get("relationships")
    relationships = relationships if isinstance(relationships, list) else []
    arcs = bible.get("arcs")
    arcs = arcs if isinstance(arcs, Mapping) else {}

    narrative_lines: List[str] = []
    for label, key in (
        ("Genre", "genre"), ("Tone", "tone"), ("Conflict", "conflict"),
        ("Stakes", "stakes"), ("Time period", "time_period"),
    ):
        val = str(narrative.get(key) or "").strip()
        if val:
            narrative_lines.append(f"{label}: {val}")
    themes = [str(t).strip() for t in (narrative.get("themes") or []) if str(t).strip()]
    if themes:
        narrative_lines.append("Themes: " + ", ".join(themes))
    world_rules = [str(r).strip() for r in (narrative.get("world_rules") or []) if str(r).strip()]
    if world_rules:
        narrative_lines.append("World rules: " + "; ".join(world_rules))

    arc_lines: List[str] = []
    for char_id, arc in arcs.items():
        if not isinstance(arc, Mapping):
            continue
        start = str(arc.get("start_state") or "").strip()
        end = str(arc.get("end_state") or "").strip()
        if not (start or end):
            continue
        turns = [str(s) for s in (arc.get("turning_scenes") or [])]
        turn_note = (
            f" (turns at scene{'s' if len(turns) != 1 else ''} {', '.join(turns)})"
            if turns else ""
        )
        arc_lines.append(
            f'- {char_id}: starts "{start or "unspecified"}", '
            f'ends "{end or "unspecified"}"{turn_note}'
        )

    rel_lines: List[str] = []
    for rel in relationships:
        if not isinstance(rel, Mapping):
            continue
        pair = rel.get("characters")
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        dynamic = str(rel.get("dynamic") or "").strip()
        tension = str(rel.get("tension_source") or "").strip()
        evolves = str(rel.get("evolves_to") or "").strip()
        details = [d for d in (
            dynamic,
            f"tension: {tension}" if tension else "",
            f"evolves to: {evolves}" if evolves else "",
        ) if d]
        line = f"- {pair[0]} <-> {pair[1]}"
        if details:
            line += ": " + "; ".join(details)
        rel_lines.append(line)

    if not (narrative_lines or arc_lines or rel_lines):
        return ""

    sections: List[str] = ["--- STORY STRUCTURE TO HONOR (from this video's Story Bible) ---"]
    if narrative_lines:
        sections.append("\n".join(narrative_lines))
    if arc_lines:
        sections.append("Character arcs:\n" + "\n".join(arc_lines))
    if rel_lines:
        sections.append("Relationships:\n" + "\n".join(rel_lines))
    sections.append(
        "Check the script against this structure. Flag any scene that reverses "
        "or contradicts a character's stated arc direction, any payoff that "
        "ignores the stated stakes or conflict, and any relationship reversal "
        "that happens with no visible cause in the script. Name each such "
        "contradiction — with the scene number when you can identify it — as "
        "its own entry in \"failing_gates\", exactly like any other violation "
        "this critic finds. Do this IN ADDITION to, never instead of, any "
        "rule_verdicts entries you were asked to fill in elsewhere in this "
        "prompt."
    )
    sections.append("--- END STORY STRUCTURE ---")
    return "\n\n" + "\n\n".join(sections)


async def critique_script(
    tenant_id: str,
    video_id: str,
    script_payload: Dict[str, Any],
    *,
    rules_text: Optional[str] = None,
    severity_by_rule: Optional[Dict[str, str]] = None,
    strict_rule_ids: Optional[Sequence[str]] = None,
    critic_max_tokens: Optional[int] = None,
    retry_invalid_critique: bool = False,
    client: Any = None,
) -> CritiqueResult:
    """Grade a freshly generated script (one Claude call by default). Lifts
    ``originality.grade_script_with_client``'s shape and prompt verbatim;
    adds a second, additive grading pass against ``rules_text`` when given.

    ``script_payload`` is a dict with at least ``script``, optionally
    ``title``, ``hook``, ``niche`` - identical contract to
    ``originality.grade_script``'s ``draft``.

    ``severity_by_rule`` (checklist C46b, ``quality_rules.compose_rules_text``'s
    second return value): an optional ``{rule_id: severity}`` map used to
    deterministically upgrade a 'pass' verdict to 'revise' when a hard-gate
    rule failed but the judge's own holistic verdict missed it - see
    ``_apply_rule_severity``. Ignored when ``rules_text`` carries no rule
    ids the judge could echo back.

    ``strict_rule_ids`` opts a caller into one exact verdict per authored ID.
    With ``retry_invalid_critique=True``, an empty, malformed, truncated, or
    wrong-ID response gets one compact-JSON retry. Defaults preserve the
    existing DVsU/general critic behavior.

    ``client`` is any object with an async
    ``generate(prompt, system_prompt, max_tokens, temperature) -> str``
    method (the tenant's AnthropicClient, Kie-gateway-aware) - same
    duck-typed contract ``grade_script_with_client`` already uses, so this
    module stays DB/pipeline-decoupled like originality.py.

    Fails OPEN: a missing client, an empty script, or any error returns a
    ``pass`` verdict so a transient model/network problem never blocks the
    pipeline. tenant_id/video_id are used for log correlation AND (D10-3b)
    to best-effort fetch this video's Story Bible (``_fetch_story_bible``) so
    the judge can ALSO check the script against its narrative/relationships/
    arcs, when that bible exists and carries them — see
    ``_story_structure_addendum``. That fetch has its own inner fail-open
    (a bible-side problem only skips the addendum, never the grading call
    itself — see the try/except around it below). Skipped entirely when
    ``strict_rule_ids`` is given: that contract belongs to Custom Film's
    per-section quality pass, a role/purpose-grounded production style that
    never populates a Story Bible narrative/arcs/relationships (a different,
    documentary-style concept) and already carries its OWN exhaustive
    hard-gate rules via ``rules_text``/``severity_by_rule`` — and a strict
    caller has a proven "total critic failure must touch no DB at all"
    contract (tests/functional/test_m7_4f_av_screenplay_adversarial.py's
    ``test_two_malformed_strict_critic_responses_fail_before_persistence``)
    this fetch must never put at risk.
    """
    if client is None or not str(script_payload.get("script") or "").strip():
        return CritiqueResult()
    try:
        system = _SCRIPT_JUDGE_SYSTEM
        text_rules = (rules_text or "").strip()
        exact_rule_ids = tuple(strict_rule_ids or ())
        if text_rules:
            system = system + (
                _strict_rules_addendum(text_rules, exact_rule_ids)
                if exact_rule_ids
                else _rules_addendum(text_rules)
            )

        # D10-3b: story-structure signal, additive only, never for a strict
        # caller (see docstring). Deliberately its OWN try/except, separate
        # from this function's outer fail-open below — a bible fetch/parse
        # problem must only skip THIS addendum, never skip the grading call
        # itself (the outer fail-open is reserved for the actual critic call
        # failing).
        story_structure = ""
        if not exact_rule_ids:
            try:
                bible = await _fetch_story_bible(tenant_id, video_id)
                story_structure = _story_structure_addendum(bible) if bible else ""
            except Exception as bible_exc:  # noqa: BLE001
                print(
                    f"[script_quality] story bible skipped for "
                    f"{str(video_id)[:8]} (tenant {str(tenant_id)[:8]}) "
                    f"class={type(bible_exc).__name__}",
                    flush=True,
                )
                story_structure = ""
        if story_structure:
            system = system + story_structure

        raw = await client.generate(
            prompt=_build_script_judge_user_prompt(script_payload),
            system_prompt=system,
            max_tokens=(
                critic_max_tokens
                if critic_max_tokens is not None
                else (900 if text_rules else 700)
            ),
            temperature=0.3,  # low, for stable gate decisions
        )
        try:
            result = _parse_critique_result(
                raw,
                strict_rule_ids=exact_rule_ids,
            )
        except Exception as first_exc:
            if not (retry_invalid_critique and exact_rule_ids):
                raise
            print(
                f"[script_quality] critique parse retry for "
                f"{str(video_id)[:8]} (tenant {str(tenant_id)[:8]}) "
                f"class={type(first_exc).__name__} "
                f"reason={_safe_critique_failure_reason(first_exc)}",
                flush=True,
            )
            retry_system = _SCRIPT_JUDGE_SYSTEM + _strict_rules_addendum(
                text_rules,
                exact_rule_ids,
                retry=True,
            )
            retry_raw = await client.generate(
                prompt=_build_script_judge_user_prompt(script_payload),
                system_prompt=retry_system,
                max_tokens=(
                    critic_max_tokens
                    if critic_max_tokens is not None
                    else 1800
                ),
                temperature=0.1,
            )
            result = _parse_critique_result(
                retry_raw,
                strict_rule_ids=exact_rule_ids,
            )
        return _apply_rule_severity(result, severity_by_rule)
    except Exception as exc:
        print(
            f"[script_quality] critique failed open for {str(video_id)[:8]} "
            f"(tenant {str(tenant_id)[:8]}) "
            f"class={type(exc).__name__} "
            f"reason={_safe_critique_failure_reason(exc)}",
            flush=True,
        )
        return CritiqueResult(verdict="pass", failing_gates=["grade unavailable - failed open"])


# ---------------------------------------------------------------------------
# Edit loop — DvsU's same-draft, named-violations pattern, generalized to a
# multi-scene script via the @@@SCENE n@@@ sentinel format already shared by
# the modeled-script path and user_script.py.
# ---------------------------------------------------------------------------

def _parse_scene_markers(raw: str) -> List[Dict[str, Any]]:
    """Parse '@@@SCENE n@@@' delimited text into ordered [{"scene", "text"}].

    Deliberately a standalone duplicate of the marker-splitting half of
    ``PipelineExecutor._parse_modeled_scenes`` (no JSON-fallback branch is
    needed here - this module always PROMPTS for the marker format) so
    script_quality.py has no import dependency on pipeline_executor, the same
    decoupling contract originality.py already keeps for its own DB-optional
    import story.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    markers = list(re.finditer(r"@@@\s*SCENE\s*\d+\s*@@@", text, re.IGNORECASE))
    if not markers:
        return []
    out: List[Dict[str, Any]] = []
    for idx, m in enumerate(markers):
        start = m.end()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        body = text[start:end].strip()
        if body:
            out.append({"scene": len(out) + 1, "text": body})
    return out


def _scene_marker_block(scenes: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for s in scenes:
        lines.append(f"@@@SCENE {s.get('scene')}@@@")
        lines.append(str(s.get("text") or "").strip())
    return "\n".join(lines)


async def edit_draft_with_violations(
    scenes: List[Dict[str, Any]],
    violations: List[str],
    *,
    client: Any,
    max_tokens: int = 4000,
) -> Optional[List[Dict[str, Any]]]:
    """DvsU's proven EDIT-loop prompt, generalized: resend the SAME draft
    with ONLY the named violations - never a fresh re-roll. Returns the
    edited scenes, or None when the response can't be parsed back into the
    same scene count (the caller should stop editing and escalate rather
    than retry against a broken parse - same defensive shape DvsU's own loop
    uses: `if edited.get("_parse_error"): break`).
    """
    if not scenes or not violations or client is None:
        return None
    prompt = (
        "EDIT THIS SCRIPT MINIMALLY. Change ONLY what the violations name; "
        "keep every other word, scene, and marker exactly as given.\n\n"
        "CURRENT SCRIPT (by scene):\n" + _scene_marker_block(scenes) +
        "\n\nVIOLATIONS TO FIX (everything else already passes):\n"
        + "\n".join(f"- {v}" for v in violations if str(v).strip()) +
        "\n\nReturn ONLY the full edited script using the SAME "
        "@@@SCENE n@@@ markers, one per scene, in order, for EVERY scene "
        "(unedited scenes included verbatim). No commentary, no markdown."
    )
    try:
        raw = await client.generate(
            prompt=prompt,
            system_prompt=(
                "You are a precise script editor. Make only the requested "
                "targeted changes; never rewrite untouched material."
            ),
            max_tokens=max_tokens,
            temperature=0.1,
        )
    except Exception:
        return None
    edited = _parse_scene_markers(raw)
    if len(edited) != len(scenes):
        return None
    return edited


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_critique_and_edit(
    tenant_id: str,
    video_id: str,
    scenes: List[Dict[str, Any]],
    *,
    client: Any,
    niche: str = "",
    title: Optional[str] = None,
    hook: Optional[str] = None,
    rules_text: Optional[str] = None,
    severity_by_rule: Optional[Dict[str, str]] = None,
    strict_rule_ids: Optional[Sequence[str]] = None,
    critic_max_tokens: Optional[int] = None,
    retry_invalid_critique: bool = False,
    regenerate: Optional[Callable[[], Any]] = None,
    max_edit_rounds: int = MAX_EDIT_ROUNDS,
    edit_constraints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Grade a script, then converge on a passing draft within DvsU's proven
    bounds:

      - ``revise``: same-draft targeted EDIT, up to ``max_edit_rounds`` (2).
      - ``regenerate``: ONE fresh reroll via the caller's ``regenerate``
        callback (originality's own bound - the caller does the actual
        regeneration and returns the new scene list; None means "not
        available", e.g. a path with no regenerate hook wired).
      - Still failing after those bounds -> ``needs_review`` (caller decides
        what that means for its own status field).

    ``edit_constraints`` are immutable instructions appended to every targeted
    edit round. They let a caller preserve an approved grounding/timing
    contract while the critic's named violations change between rounds.

    ``regenerate`` is an async zero-arg callable returning the fresh
    ``[{"scene", "text"}, ...]`` list, or a falsy value if the reroll
    produced nothing usable.

    Returns a dict: ``scenes`` (final scene list), ``critique`` (the final
    CritiqueResult), ``needs_review`` (bool), ``edit_rounds`` (int),
    ``regenerated`` (bool), ``changed`` (bool - True iff ``scenes`` differs
    from the input, so the caller knows whether a DB write is needed).
    """
    current = list(scenes)

    def _full_text(sc: List[Dict[str, Any]]) -> str:
        return "\n\n".join(str(s.get("text") or "").strip() for s in sc)

    async def _grade() -> CritiqueResult:
        payload = {"niche": niche, "title": title, "hook": hook, "script": _full_text(current)}
        return await critique_script(
            tenant_id, video_id, payload, rules_text=rules_text,
            severity_by_rule=severity_by_rule,
            strict_rule_ids=strict_rule_ids,
            critic_max_tokens=critic_max_tokens,
            retry_invalid_critique=retry_invalid_critique,
            client=client,
        )

    grade = await _grade()
    edit_rounds = 0
    regenerated = False

    if grade.verdict == "revise":
        violations = grade.violations
        while grade.needs_revision and edit_rounds < max_edit_rounds and violations:
            edited = await edit_draft_with_violations(
                current,
                [*violations, *(edit_constraints or [])],
                client=client,
            )
            edit_rounds += 1
            if edited is None:
                break
            current = edited
            grade = await _grade()
            violations = grade.violations

    if grade.verdict == "regenerate" and regenerate is not None:
        fresh = await regenerate()
        regenerated = True
        if fresh:
            current = list(fresh)
            grade = await _grade()

    return {
        "scenes": current,
        "critique": grade,
        "needs_review": grade.needs_revision,
        "edit_rounds": edit_rounds,
        "regenerated": regenerated,
        "changed": current != scenes,
    }
