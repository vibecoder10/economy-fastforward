"""Per-channel quality-rules store (checklist C46b).

C46a shipped the generic critic (``script_quality.py``) with a ``rules_text``
seam fed by a stopgap (this tenant's ``script_templates.structure`` — the
channel's house FORMAT prose, never a graded law list). This module is the
real thing: discrete, severity-tagged LAW rows (modeled on
``storyengine/notes/dvsu-quality-law.md``'s QL/QD row shape — id, testable
law text, evidence, severity) stored per-tenant in the ``quality_rules``
table (migration 105), plus the DETERMINISTIC scope resolution Ryan required
(decisions.md 2026-07-19): which rules apply to a given video is decided
from DATA the video already carries, never an LLM's judgment call at grading
time.

Three layers, kept deliberately separate:

  1. **Pure resolver** (``resolve_video_shape``, ``rule_matches``,
     ``active_rules_for_video``, ``compose_rules_text``) — no DB, no
     network. Callers fetch the tenant's active rule ROWS themselves (via
     ``list_all_rules`` or their own query) and hand them in; this keeps the
     scope-matching logic itself trivially unit-testable and lets
     ``pipeline_executor.py`` keep using its own already-patched
     ``fetch_all``/``fetch_one`` names for every DB read (the established
     test convention in this codebase — see
     ``tests/test_c46a_quality_critic_wiring.py``), rather than this module
     opening a second, separately-mockable DB surface for the same table.

  2. **CRUD** (``list_all_rules``, ``create_rule``, ``bulk_create_rules``,
     ``update_rule``, ``get_rule``, ``deactivate_rule``) — the only code
     that writes ``quality_rules`` rows. Used by ``routes/quality_rules.py``
     (the tenant-facing CRUD route) and by the chat ingestion door's
     CONFIRMED-draft handler (never by the parser itself).

  3. **Ingestion parser** (``parse_rules_document``, ``parse_markdown_table``,
     ``llm_parse_rules_prose``, ``suggest_applies_to``) — turns an uploaded
     or pasted rules document into QL-shaped candidate rows. Parsing (and
     its ``suggest_applies_to`` scope GUESS) never writes anything; a human
     confirm tap is what actually calls ``bulk_create_rules`` (see
     ``routes/chat.py``'s ``draft_quality_rules`` op / confirm card, the
     same "no rows until confirmed" pattern C22's ``draft_style`` uses).

``applies_to`` vocabulary (also documented in migrations/105_quality_rules.sql's
header — read both if you're extending this): a rule matches a video if ANY
key resolves true (OR across keys, never AND):

  "all": true                    -- universal; always true.
  "research": true               -- the video's research stage actually ran
                                     (not skipped) — videos.research_skipped
                                     + videos.pipeline_stages (the workflow
                                     plan).
  "story": true                  -- narrative/documentary-arc laws — resolved
                                     from videos.render_mode == 'static_docu'
                                     today (the one render_mode this signal
                                     set can identify as arc-driven; extend
                                     THIS function, not the resolver's
                                     contract, as more arc-driven formats
                                     land).
  "animated": true               -- videos.render_style == 'animated'.
  "realistic": true              -- videos.render_style == 'realistic'.
  "channel_format": "<value>"    -- STRING-valued: matches case-insensitively
                                     against a ``channel_format`` value the
                                     CALLER supplies on video_row (this
                                     module does no channel_profiles lookup
                                     of its own — a forward-compatible stub
                                     until a discrete format-id registry
                                     exists; a rule scoped this way simply
                                     never matches until a caller starts
                                     supplying the value).
  "dvsu_mode": "<value>"         -- STRING-valued (checklist C46e, OR-5):
                                     matches case-insensitively against a
                                     ``dvsu_mode`` value the CALLER supplies
                                     (``pipeline_executor.py``'s
                                     ``_dvsu_mode_profile`` already resolves
                                     this per-video from ``research_payload.
                                     dvsu_mode`` — an explicit opt-in field,
                                     never inferred from the title). Lets a
                                     mode like "most_hated" carry its OWN
                                     rule-table overrides (opener budget,
                                     memorable-fact source) instead of the
                                     spec-block default's.

An unrecognized applies_to key is skipped and logged — never crashes, never
matches. A rule with zero resolvable keys never matches (fails closed).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from database import execute, fetch_all, fetch_one  # noqa: F401 - execute kept for future direct-SQL callers
from status_map import stage_enabled_in_plan

logger = logging.getLogger(__name__)

SEVERITIES = {"hard_gate", "warn", "guidance"}
# "mcp_agent" (checklist C47): the setup-surface `upsert_quality_rule` MCP
# tool stamps this so a rule an agent wrote is distinguishable from one typed
# through chat or parsed from an uploaded doc — same attribution spirit as
# script_source='agent_submitted' (user_script.accept_external_script, C46d).
SOURCES = {"doc_upload", "chat", "seed", "mcp_agent"}

_BOOL_SCOPE_KEYS = {"all", "research", "story", "animated", "realistic"}

_SEVERITY_LABEL = {"hard_gate": "HARD-GATE", "warn": "WARN", "guidance": "GUIDANCE"}
_SEVERITY_ORDER = {"hard_gate": 0, "warn": 1, "guidance": 2}


# ---------------------------------------------------------------------------
# Pure scope resolution — no DB, no network.
# ---------------------------------------------------------------------------

def _research_active(video_row: dict) -> bool:
    """Research ran (or is planned to) for this video: not explicitly
    skipped, and — when the creator restricted the pipeline — "research" is
    actually a member of that plan. Reuses status_map's own plan parser
    rather than re-decoding pipeline_stages JSON here."""
    if bool((video_row or {}).get("research_skipped")):
        return False
    return stage_enabled_in_plan("research", (video_row or {}).get("pipeline_stages"))


def resolve_video_shape(video_row: dict) -> dict:
    """The deterministic signal set a video carries, used to match
    applies_to scopes. Pure function of the row's own columns — no
    inference, no model call."""
    video_row = video_row or {}
    return {
        "all": True,
        "research": _research_active(video_row),
        "story": (video_row.get("render_mode") or "") == "static_docu",
        "animated": (video_row.get("render_style") or "") == "animated",
        "realistic": (video_row.get("render_style") or "") == "realistic",
    }


def _coerce_applies_to(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


_STRING_SCOPE_KEYS = {"channel_format": "channel_format_value", "dvsu_mode": "dvsu_mode_value"}


def rule_matches(
    applies_to: Any,
    shape: dict,
    *,
    channel_format_value: Optional[str] = None,
    dvsu_mode_value: Optional[str] = None,
    rule_id: str = "",
) -> bool:
    """Deterministic OR-across-keys scope match. Unknown keys are logged and
    skipped (never crash, never match); a rule whose only keys are unknown
    never matches any video (fails closed on garbage scope)."""
    applies_to = _coerce_applies_to(applies_to)
    if not applies_to:
        return False
    string_values = {"channel_format": channel_format_value, "dvsu_mode": dvsu_mode_value}
    for key, value in applies_to.items():
        if key in _STRING_SCOPE_KEYS:
            caller_value = string_values.get(key)
            if caller_value and str(value).strip().lower() == str(caller_value).strip().lower():
                return True
            continue
        if key in _BOOL_SCOPE_KEYS:
            if bool(value) and shape.get(key):
                return True
            continue
        logger.warning(
            "quality_rules: unrecognized applies_to scope key %r on rule %s — skipped, never matched",
            key, rule_id or "<unknown>",
        )
    return False


def active_rules_for_video(
    video_row: dict,
    rules: list[dict],
    *,
    channel_format_value: Optional[str] = None,
    dvsu_mode_value: Optional[str] = None,
) -> list[dict]:
    """Filter already-fetched active ``quality_rules`` rows down to the ones
    that apply to this video, by deterministic scope-matching alone — never
    an LLM call, never a judgment about which gates SHOULD apply (Ryan's
    2026-07-19 scoping requirement). A hybrid video (e.g. research ran AND
    render_mode='static_docu') naturally collects both scopes' rules, since
    each rule is matched independently."""
    shape = resolve_video_shape(video_row)
    return [
        r for r in (rules or [])
        if rule_matches(
            r.get("applies_to"), shape,
            channel_format_value=channel_format_value,
            dvsu_mode_value=dvsu_mode_value,
            rule_id=r.get("rule_id", ""),
        )
    ]


def compose_rules_text(rules: list[dict]) -> tuple[str, dict[str, str]]:
    """Build the severity-tagged text C46a's ``script_quality.critique_script``
    consumes as ``rules_text``, plus a parallel ``{rule_id: severity}`` map
    the caller uses to deterministically enforce hard-gate blocking after
    grading (``script_quality._apply_rule_severity`` — severity is an
    authored fact about the rule, not something the judge's own holistic
    verdict should be trusted alone to encode). Returns ("", {}) for an
    empty rule list so a caller with no rules configured yet gets exactly
    the pre-C46b empty-rules_text behavior."""
    if not rules:
        return "", {}
    lines = [
        "Each rule below is tagged with its exact ID in brackets, then its "
        "severity, then its law text. When you report a rule in "
        "rule_verdicts, set \"rule\" to that EXACT bracketed ID (e.g. "
        "\"QL-12\"), never a paraphrase — severity is enforced "
        "deterministically after grading using that id.",
        "",
    ]
    severity_by_rule: dict[str, str] = {}
    for r in sorted(rules, key=lambda r: _SEVERITY_ORDER.get(r.get("severity"), 3)):
        rid = str(r.get("rule_id") or "").strip()
        if not rid:
            continue
        severity = r.get("severity") if r.get("severity") in SEVERITIES else "guidance"
        severity_by_rule[rid] = severity
        law = str(r.get("law") or "").strip()
        if not law:
            continue
        evidence = str(r.get("evidence") or "").strip()
        line = f"[{rid}] [{_SEVERITY_LABEL.get(severity, severity.upper())}] {law}"
        if evidence:
            line += f" (why: {evidence})"
        lines.append(line)
    return "\n".join(lines), severity_by_rule


# ---------------------------------------------------------------------------
# CRUD — the only code that writes quality_rules rows.
# ---------------------------------------------------------------------------

_SELECT_COLS = "id, rule_id, law, evidence, severity, applies_to, source, active, created_at, updated_at"


def _decode_row(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    row = dict(row)
    row["applies_to"] = _coerce_applies_to(row.get("applies_to"))
    return row


def _dump_applies_to(applies_to: Any) -> str:
    return json.dumps(applies_to if isinstance(applies_to, dict) and applies_to else {"all": True})


async def list_all_rules(tenant_id, *, active_only: bool = False) -> list[dict]:
    query = f"SELECT {_SELECT_COLS} FROM quality_rules WHERE tenant_id = $1"
    if active_only:
        query += " AND active"
    query += " ORDER BY created_at DESC"
    rows = await fetch_all(query, tenant_id)
    return [_decode_row(r) for r in (rows or [])]


async def get_rule(tenant_id, id_: str) -> Optional[dict]:
    row = await fetch_one(
        f"SELECT {_SELECT_COLS} FROM quality_rules WHERE tenant_id = $1 AND id = $2",
        tenant_id, id_,
    )
    return _decode_row(row)


async def create_rule(
    tenant_id, *, rule_id: str, law: str, severity: str,
    evidence: Optional[str] = None, applies_to: Optional[dict] = None,
    source: str = "chat",
) -> dict:
    """Insert, or update-in-place on a (tenant_id, rule_id) collision — so
    re-uploading a revised rules doc naturally edits existing rows instead
    of accumulating duplicates (one of the two "rule edits ... via both
    doors" paths the checklist calls for)."""
    severity = severity if severity in SEVERITIES else "guidance"
    source = source if source in SOURCES else "chat"
    row = await fetch_one(
        f"""INSERT INTO quality_rules (tenant_id, rule_id, law, evidence, severity, applies_to, source)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            ON CONFLICT (tenant_id, rule_id) DO UPDATE SET
              law = EXCLUDED.law, evidence = EXCLUDED.evidence, severity = EXCLUDED.severity,
              applies_to = EXCLUDED.applies_to, source = EXCLUDED.source, active = true, updated_at = now()
            RETURNING {_SELECT_COLS}""",
        tenant_id, str(rule_id).strip()[:40], str(law).strip(),
        (str(evidence).strip() if evidence else None), severity,
        _dump_applies_to(applies_to), source,
    )
    return _decode_row(row)


async def bulk_create_rules(tenant_id, rows: list[dict], *, source: str) -> list[dict]:
    """The ONLY place parsed-draft rows become real rows. Callers must only
    invoke this AFTER an explicit human confirm (chat's draft-card tap, or a
    future seed script for C46c) — never from the parser itself, which only
    returns candidate dicts."""
    saved = []
    for r in rows or []:
        rule_id = str(r.get("rule_id") or "").strip()
        law = str(r.get("law") or "").strip()
        if not rule_id or not law:
            continue
        saved.append(await create_rule(
            tenant_id, rule_id=rule_id, law=law,
            severity=r.get("severity") or "guidance",
            evidence=r.get("evidence"), applies_to=r.get("applies_to"),
            source=source,
        ))
    return saved


async def update_rule(tenant_id, id_: str, updates: dict) -> Optional[dict]:
    """Edit a subset of {law, evidence, severity, applies_to, active}.
    Column names are a hardcoded whitelist below (never built from caller
    input), so this is safe despite the dynamic SET list."""
    set_clauses: list[str] = []
    args: list[Any] = []
    idx = 1
    for col in ("law", "evidence", "severity", "applies_to", "active"):
        if col not in updates:
            continue
        if col == "applies_to":
            set_clauses.append(f"applies_to = ${idx}::jsonb")
            args.append(_dump_applies_to(updates[col]))
        else:
            set_clauses.append(f"{col} = ${idx}")
            args.append(updates[col])
        idx += 1
    if not set_clauses:
        return await get_rule(tenant_id, id_)
    set_clauses.append("updated_at = now()")
    args.extend([tenant_id, id_])
    query = (
        f"UPDATE quality_rules SET {', '.join(set_clauses)} "
        f"WHERE tenant_id = ${idx} AND id = ${idx + 1} RETURNING {_SELECT_COLS}"
    )
    row = await fetch_one(query, *args)
    return _decode_row(row)


async def deactivate_rule(tenant_id, id_: str) -> bool:
    row = await update_rule(tenant_id, id_, {"active": False})
    return row is not None


# ---------------------------------------------------------------------------
# Ingestion parser — doc/paste -> candidate QL-shaped rows. Never writes.
# ---------------------------------------------------------------------------

_SEVERITY_ALIASES = {
    "hard-gate": "hard_gate", "hard gate": "hard_gate", "hard_gate": "hard_gate",
    "warn": "warn", "warning": "warn",
    "guidance": "guidance",
}
_RULE_ID_RE = re.compile(r"^[A-Za-z]{1,4}-\d+$")

_RESEARCH_KEYWORDS = (
    "source", "citation", "cited", "cross-reference", "cross reference",
    "evidence", "verify", "verified", "grounded", "grounding", "hedge",
    "fact-check", "unverifiable", "primary source",
)
_STORY_KEYWORDS = (
    "twist", "act ", "act-break", "arc", "punch", "cliffhanger", "closer",
    "verdict", "designed-vs-used", "designed vs used", "bookend", "opener",
    "spine", "cold-open", "cold open",
)


def suggest_applies_to(law: str) -> dict:
    """A zero-cost keyword-heuristic DEFAULT scope, proposed only at
    INGESTION time — the human sees and can edit it on the draft confirm
    card before any row is written. This is NOT the runtime gate (that's
    ``active_rules_for_video``, which reads video data, never a law's
    wording); conflating the two would reintroduce the LLM-judgment-at-
    grading-time pattern Ryan's ruling explicitly rejected."""
    text = (law or "").lower()
    research = any(k in text for k in _RESEARCH_KEYWORDS)
    story = any(k in text for k in _STORY_KEYWORDS)
    if research and story:
        return {"research": True, "story": True}
    if research:
        return {"research": True}
    if story:
        return {"story": True}
    return {"all": True}


def parse_markdown_table(text: str) -> list[dict]:
    """Deterministic parser for dvsu-quality-law.md's own pipe-table row
    shape: ``| ID | Law (testable) | Evidence (counts) | Triangle - B/R/G |
    Sev |``. No LLM call, no cost. The Triangle (B/R/G) column is read and
    discarded — not part of this chunk's stored row shape."""
    rows: list[dict] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        rule_id = cells[0]
        if not _RULE_ID_RE.match(rule_id):
            continue  # header ("ID"), separator ("---"), or a prose line that happens to have pipes
        severity = _SEVERITY_ALIASES.get(cells[4].strip().lower())
        if not severity:
            continue
        law = cells[1].strip()
        if not law:
            continue
        evidence = cells[2].strip() or None
        rows.append({
            "rule_id": rule_id,
            "law": law,
            "evidence": evidence,
            "severity": severity,
            "applies_to": suggest_applies_to(law),
        })
    return rows


async def llm_parse_rules_prose(text: str, client: Any) -> list[dict]:
    """Fallback for a rules doc that ISN'T a QL/QD pipe table (e.g. a
    creator's plain-prose/bulleted rules pasted in chat). One Claude call
    extracts candidate rows; still confirm-gated by the caller before any
    insert — this only parses, never writes."""
    if client is None or not (text or "").strip():
        return []
    prompt = (
        "Extract distinct, testable QUALITY RULES from the document below. "
        "For each rule, give: an id (invent a short one like \"R-1\" if none "
        "is given in the text), the rule text itself (testable/checkable, "
        "one sentence), any evidence/rationale given (or null), and a "
        "severity of exactly one of hard_gate | warn | guidance (infer from "
        "language: \"must/never/reject\" = hard_gate, \"should/avoid/flag\" "
        "= warn, \"prefer/try to/lean toward\" = guidance).\n\n"
        "Return ONLY JSON, no commentary: {\"rules\": [{\"rule_id\": string, "
        "\"law\": string, \"evidence\": string|null, \"severity\": "
        "\"hard_gate\"|\"warn\"|\"guidance\"}]}\n\nDOCUMENT:\n" + text[:12000]
    )
    try:
        raw = await client.generate(
            prompt=prompt,
            system_prompt=(
                "You are a precise rules analyst. Extract structure only; "
                "never invent a rule the text doesn't imply."
            ),
            max_tokens=2000,
            temperature=0.2,
        )
        from originality import _extract_json
        data = json.loads(_extract_json(raw))
        rows: list[dict] = []
        for item in (data.get("rules") or []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            rule_id = str(item.get("rule_id") or "").strip()[:40]
            law = str(item.get("law") or "").strip()
            if not rule_id or not law:
                continue
            severity = _SEVERITY_ALIASES.get(str(item.get("severity") or "").strip().lower(), "guidance")
            evidence = item.get("evidence")
            rows.append({
                "rule_id": rule_id,
                "law": law,
                "evidence": str(evidence).strip() if evidence else None,
                "severity": severity,
                "applies_to": suggest_applies_to(law),
            })
        return rows
    except Exception as e:  # noqa: BLE001
        logger.warning("quality_rules: LLM prose parse failed: %s", e)
        return []


async def parse_rules_document(text: str, *, client: Any = None) -> list[dict]:
    """Entry point for both ingestion doors: try the deterministic table
    parser first (handles dvsu-quality-law.md's own format, and any doc
    shaped like it, for free); fall back to the LLM prose parser only when
    no table rows were found."""
    rows = parse_markdown_table(text)
    if rows:
        return rows
    return await llm_parse_rules_prose(text, client)


# ---------------------------------------------------------------------------
# DvsU delta overrides (checklist C46c) — the reference-tenant table-driven
# gates. Pure function: given a video's already ACTIVE + SCOPE-MATCHED
# ``quality_rules`` rows (the same list ``active_rules_for_video`` returns),
# extract the structured VALUES ``pipeline_executor._validate_machine_story_
# sentences`` / ``_validate_static_unit_paragraph`` read before falling back
# to their own hardcoded constants. Each key below is populated ONLY when
# the corresponding rule_id is present AND its `law` text parses with the
# extractor's pattern — a present-but-unparseable row (wording drifted from
# the pattern) is silently skipped for that key alone, never raises, never
# partially applies a broken value. No DB, no network — callers fetch rows
# themselves, same layering discipline as the rest of this module.
# ---------------------------------------------------------------------------

_QL1_WORD_LAW_RE = re.compile(
    r"under\s+(\d+)\s+spoken\s+words.*?warn\s+(\d+)\s*-\s*(\d+).*?over\s+(\d+)",
    re.IGNORECASE | re.DOTALL,
)
_QL4_SUBTYPES_RE = re.compile(r"recurring subtypes:\s*([^.]+)\.", re.IGNORECASE)
_QL12_BANNED_WORDS_RE = re.compile(r"thumbnail-hype adjectives\s*\(([^)]+)\)", re.IGNORECASE)

# OR-5 (approved, checklist C46e): the "Most Hated" mode's own overrides,
# seeded as QL-7-MH / QL-9-MH rows scoped {"dvsu_mode": "most_hated"} (see
# scripts/seed_dvsu_quality_rules.py). Mirrors QL-7's opener-budget law and
# QL-9's memorable-fact law, but for the crew-testimony register — a rule
# row present but reworded away from these patterns is skipped for that key
# alone, same fail-soft-per-key discipline as QL-1/QL-3/QL-4/QL-12 above.
_QL7MH_OPENER_BUDGET_RE = re.compile(r"cap bare name-openers at about (\d+)\s*%", re.IGNORECASE)
_QL9MH_MEMORABLE_SOURCE_RE = re.compile(r"memorable fact must come from ([a-z][a-z ]*[a-z])\b", re.IGNORECASE)

# QL-4's five canonical types are named only in the doc's Evidence column
# (discarded by parse_markdown_table, never part of `law`), so they stay a
# small hardcoded constant here rather than something re-parsed per seed —
# unioned with whatever QL-4's `law` text supplies as the 11 recurring
# subtypes. Mirrors pipeline_executor.py's own `_DVSU_TWIST_TYPES` canonical
# half exactly (by design: this IS the same taxonomy, read from the same
# source doc).
_QL4_CANONICAL_TYPES = (
    "role_change", "obsolete_but_enduring", "myth_vs_reality",
    "cheap_beats_good", "ambition_outran_tech",
)


def _normalize_twist_token(raw: str) -> str:
    return re.sub(r"[\s/-]+", "_", raw.strip().lower()).strip("_")


def resolve_dvsu_overrides(rules: list[dict]) -> dict:
    """Extract the DvsU delta overrides from a tenant's scope-matched rule
    rows. Returns a dict with only the keys whose backing rule parsed:

      "word_floor": {"hard_min": int, "warn_top": int, "hard_max": int,
                      "severity": str}                      -- from QL-1
      "twist_gate": {"severity": str}                        -- from QL-3
      "twist_menu": {"types": tuple[str, ...], "severity": str} -- from QL-4
      "banned_hype_words": {"words": tuple[str, ...], "severity": str} -- QL-12
      "opener_budget": {"value": float, "severity": str}     -- QL-7-MH
                        (checklist C46e, OR-5's Most Hated mode override)
      "memorable_source": {"value": str, "severity": str}    -- QL-9-MH
                        (checklist C46e, OR-5's Most Hated mode override)

    An empty return (``{}``) means every check falls back to today's
    hardcoded constants — the exact behavior for any non-seeded tenant and
    for DvsU itself before the seed script runs."""
    overrides: dict = {}
    by_id = {str(r.get("rule_id") or "").strip().upper(): r for r in (rules or [])}

    ql1 = by_id.get("QL-1")
    if ql1:
        m = _QL1_WORD_LAW_RE.search(str(ql1.get("law") or ""))
        if m:
            hard_min, _warn_lo, warn_top, hard_max = (int(g) for g in m.groups())
            overrides["word_floor"] = {
                "hard_min": hard_min, "warn_top": warn_top, "hard_max": hard_max,
                "severity": ql1.get("severity") if ql1.get("severity") in SEVERITIES else "hard_gate",
            }

    ql3 = by_id.get("QL-3")
    if ql3:
        overrides["twist_gate"] = {
            "severity": ql3.get("severity") if ql3.get("severity") in SEVERITIES else "hard_gate",
        }

    ql4 = by_id.get("QL-4")
    if ql4:
        m = _QL4_SUBTYPES_RE.search(str(ql4.get("law") or ""))
        if m:
            subtypes = tuple(
                _normalize_twist_token(item)
                for item in m.group(1).split(",")
                if item.strip()
            )
            overrides["twist_menu"] = {
                "types": tuple(dict.fromkeys(_QL4_CANONICAL_TYPES + subtypes)),
                "severity": ql4.get("severity") if ql4.get("severity") in SEVERITIES else "guidance",
            }

    ql12 = by_id.get("QL-12")
    if ql12:
        m = _QL12_BANNED_WORDS_RE.search(str(ql12.get("law") or ""))
        if m:
            words = tuple(item.strip().lower() for item in m.group(1).split(",") if item.strip())
            overrides["banned_hype_words"] = {
                "words": words,
                "severity": ql12.get("severity") if ql12.get("severity") in SEVERITIES else "hard_gate",
            }

    ql7mh = by_id.get("QL-7-MH")
    if ql7mh:
        m = _QL7MH_OPENER_BUDGET_RE.search(str(ql7mh.get("law") or ""))
        if m:
            overrides["opener_budget"] = {
                "value": int(m.group(1)) / 100.0,
                "severity": ql7mh.get("severity") if ql7mh.get("severity") in SEVERITIES else "warn",
            }

    ql9mh = by_id.get("QL-9-MH")
    if ql9mh:
        m = _QL9MH_MEMORABLE_SOURCE_RE.search(str(ql9mh.get("law") or ""))
        if m:
            overrides["memorable_source"] = {
                "value": re.sub(r"\s+", "_", m.group(1).strip().lower()),
                "severity": ql9mh.get("severity") if ql9mh.get("severity") in SEVERITIES else "warn",
            }

    return overrides
