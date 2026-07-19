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
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

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


async def critique_script(
    tenant_id: str,
    video_id: str,
    script_payload: Dict[str, Any],
    *,
    rules_text: Optional[str] = None,
    severity_by_rule: Optional[Dict[str, str]] = None,
    client: Any = None,
) -> CritiqueResult:
    """Grade a freshly generated script (one Claude call). Lifts
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

    ``client`` is any object with an async
    ``generate(prompt, system_prompt, max_tokens, temperature) -> str``
    method (the tenant's AnthropicClient, Kie-gateway-aware) - same
    duck-typed contract ``grade_script_with_client`` already uses, so this
    module stays DB/pipeline-decoupled like originality.py.

    Fails OPEN: a missing client, an empty script, or any error returns a
    ``pass`` verdict so a transient model/network problem never blocks the
    pipeline. tenant_id/video_id are used only for log correlation.
    """
    if client is None or not str(script_payload.get("script") or "").strip():
        return CritiqueResult()
    try:
        system = _SCRIPT_JUDGE_SYSTEM
        text_rules = (rules_text or "").strip()
        if text_rules:
            system = system + _rules_addendum(text_rules)
        raw = await client.generate(
            prompt=_build_script_judge_user_prompt(script_payload),
            system_prompt=system,
            max_tokens=900 if text_rules else 700,
            temperature=0.3,  # low, for stable gate decisions
        )
        result = CritiqueResult(**json.loads(_extract_json(raw)))
        return _apply_rule_severity(result, severity_by_rule)
    except Exception:
        print(
            f"[script_quality] critique failed open for {str(video_id)[:8]} "
            f"(tenant {str(tenant_id)[:8]})", flush=True,
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
    regenerate: Optional[Callable[[], Any]] = None,
    max_edit_rounds: int = MAX_EDIT_ROUNDS,
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
            severity_by_rule=severity_by_rule, client=client,
        )

    grade = await _grade()
    edit_rounds = 0
    regenerated = False

    if grade.verdict == "revise":
        violations = grade.violations
        while grade.needs_revision and edit_rounds < max_edit_rounds and violations:
            edited = await edit_draft_with_violations(current, violations, client=client)
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
