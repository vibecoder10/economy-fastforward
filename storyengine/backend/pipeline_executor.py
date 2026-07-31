"""Pipeline Executor - Wraps existing pipeline skills for StoryEngine.

This module bridges StoryEngine and the video production pipeline.
It imports the pipeline skills directly and executes them with proper
error handling, activity logging, and dual-writes to Supabase.

Usage:
    from pipeline_executor import PipelineExecutor

    executor = PipelineExecutor(tenant_id="...")
    result = await executor.run_research(video_id)
"""

import os
import sys
import asyncio
import uuid
import re
import hashlib
from datetime import datetime, timezone
from typing import Optional, Any
from pathlib import Path
from urllib.parse import urlparse

# Add pipeline to path BEFORE any pipeline imports
PIPELINE_PATH = Path(__file__).parent.parent.parent / "skills" / "video-pipeline"
if str(PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PATH))

# C34b/S10-2: tenant-neutral narrator default. ElevenLabs premade/stock voice
# "Rachel" — documented in ElevenLabs' public voice library, and already the
# example id shown in the onboarding UI's placeholder text
# (frontend/src/components/onboarding/ApiKeysStep.tsx KEY_FORMAT_HINTS). Used
# whenever a tenant hasn't configured their own elevenlabs_voice_id in
# Settings -> API Keys. Deliberately NOT Models.VOICE_ID / ElevenLabsClient.
# DEFAULT_VOICE_ID — those are evaluated once at first import in this shared
# multi-tenant process and could freeze in whichever identity's env var
# happened to be set at that moment; this constant is applied explicitly,
# per tenant, at ElevenLabsClient construction time below (_ensure_initialized).
STOCK_NARRATOR_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# Each bot folder has internal imports (e.g., script/run.py imports brief_translator).
# Add bot subdirectories to sys.path so these resolve correctly.
for bot_dir in ["script", "voice", "image_prompts", "images", "video_motion",
                "thumbnail", "render", "sound", "storyboard", "research",
                "upload", "analytics", "title_idea"]:
    bot_path = str(PIPELINE_PATH / bot_dir)
    if bot_path not in sys.path:
        sys.path.append(bot_path)

from database import fetch_one, fetch_all, execute
from generation_ledger import record_ledger_entry
from error_utils import humanize_error, user_facing
from status_map import (
    to_supabase, to_pipeline, get_bot_name, STAGE_BOT_MAP, is_at_or_past_stage,
    resolve_planned_status, get_next_status_supabase,
    render_path_plays_sfx, render_path_sfx_block_reason, stages_excluding_blocked_sound,
)
from vault import get_secret
from extraction import extract_grid
from storage import upload_from_url
import engine_templates
from identity import IdentityContext, build_identity_context
import clip_asset_claims
import provider_dialect

import logging
_logger = logging.getLogger(__name__)


def _unit_display_name(item: Any) -> str:
    """Normalize a research unit_roster entry into a human-readable name."""
    if isinstance(item, dict):
        nested = item.get("unit") or item.get("machine")
        if nested and not (item.get("name") or item.get("title") or item.get("designation") or item.get("code")):
            return _unit_display_name(nested)
        name = str(item.get("name") or item.get("title") or "").strip()
        designation = str(item.get("designation") or item.get("code") or "").strip()
        if name and designation and designation.lower() not in name.lower():
            return f"{designation} {name}".strip()
        return name or designation
    return str(item or "").strip()


def _unit_code(text: str) -> str:
    """Extract the short machine/unit code that DvsU-style rosters hinge on."""
    import re
    s = str(text or "").upper().replace("–", "-").replace("—", "-")
    # Prefer explicit bomber/aircraft designations, then fall back to compact tokens.
    for pat in (
        r"\b(?:X?Y?B|FB)-?\d{1,3}[A-Z]?\b",  # XB-70, YB-40, B-52H, FB-111A
        r"\b[A-Z]{1,4}-\d{1,4}[A-Z]?\b",
    ):
        m = re.search(pat, s)
        if m:
            return m.group(0).replace(" ", "")
    words = re.findall(r"[A-Z0-9]+", s)
    return " ".join(words[:4])


def _normalized_unit_code(text: str) -> str:
    """Canonical designation equality (B-52 == B52; B-2 != B-21)."""
    import re
    return re.sub(r"[^A-Z0-9]", "", _unit_code(text).upper())


_AIRCRAFT_DESIGNATION_RE = re.compile(r"\b[A-Z]{1,4}-?\d{1,4}[A-Z]?\b", re.IGNORECASE)


def _target_machine_designation_codes(machine: str) -> set[str]:
    """Model-number designations allowed for the locked one-machine scope."""
    codes = {
        _normalized_unit_code(token)
        for token in _AIRCRAFT_DESIGNATION_RE.findall(str(machine or "").upper())
    }
    fallback = _normalized_unit_code(machine)
    if fallback:
        codes.add(fallback)
    return {code for code in codes if code}


# G16: ship-style DVsU rosters lock a LOCKED display name that often carries a
# leading pennant/hull-number prefix ("53 HMS Prince of Wales", "41 HMS King
# George V", "17 Duke of York", "79 Anson") - the roster's own bookkeeping
# token, not part of the ship's name. A model naturally writes the name
# without it ("HMS Prince of Wales"), and _unit_code's 4-token fallback then
# glues the pennant into the very first token of the collapsed code, so an
# exact/substring match against the un-prefixed name always missed. This is
# the ship-name cousin of the G2 "(D48)" fix (same technique: scan the
# display name for the extra token and add it to the allowed set) - only the
# LEADING standalone digit token is optional, so a sibling with a different
# name/pennant ("53 HMS King George V") is never pulled in by mistake.
_LEADING_PENNANT_RE = re.compile(r"^\d+\s+")


def _locked_machine_identity_codes(machine: str) -> set[str]:
    """Normalized identity codes that legitimately identify a LOCKED machine.

    Includes the code as written, plus - only when the display name opens
    with a standalone leading digit/pennant token - the code with that one
    token stripped. Never loosens anything else: a different machine's own
    name/pennant still normalizes to a different code entirely."""
    machine_text = str(machine or "")
    codes = {_normalized_unit_code(machine_text)}
    stripped = _LEADING_PENNANT_RE.sub("", machine_text, count=1)
    if stripped != machine_text and stripped.strip():
        codes.add(_normalized_unit_code(stripped))
    return {code for code in codes if code}


def _non_target_designation_codes(text: str, machine: str) -> list[str]:
    allowed = _target_machine_designation_codes(machine)
    if not allowed:
        return []
    # Multi-unit CLASS entry (2026-07-30): the display string names member
    # SHIPS but at most one pennant number, so sibling units' own pennants
    # read as foreign machines — "Centaur, Albion, Bulwark, Hermes (R12)
    # Centaur class" allows only R12, and genuine Centaur (R06) / Bulwark
    # (R08) excerpts were silently hidden from the card prompt. Membership
    # cannot be derived from the glued string, so for class entries the code
    # screen is skipped: both callers already require the excerpt to NAME
    # the machine/member, and the card contract still bars excerpts about
    # other machines. The strict screen remains for single-machine entries,
    # where it protects against variant confusion (B-52 vs XB-70).
    if "class" in (_unit_display_name(machine) or str(machine or "")).lower():
        return []
    found = {
        _normalized_unit_code(token)
        # Scan the ORIGINAL text, not an uppercased copy: real designations
        # are written with capitals (R06, B-52), while an all-lowercase hit
        # is a unit of measure — "20.9 m2" is square metres, not an M2.
        for token in _AIRCRAFT_DESIGNATION_RE.findall(str(text or ""))
        if any(ch.isupper() for ch in token)
    }
    return sorted(code for code in found if code and code not in allowed)


def _title_needs_complete_roster(title: str) -> bool:
    import re
    t = str(title or "").strip().lower()
    return bool(re.search(r"\b(every|all)\b", t) or "ever built" in t or "complete" in t)


def _title_is_broad_machine_roster(title: str) -> bool:
    """True for titles where a short shortlist is almost certainly wrong."""
    import re
    t = str(title or "").strip().lower()
    machine_terms = (
        "aircraft", "bomber", "fighter", "jet", "plane", "tank", "ship",
        "submarine", "helicopter", "missile", "weapon", "vehicle", "machine",
    )
    broad_terms = ("us ", "u.s.", "american", "soviet", "russian", "british", "german", "strategic")
    return (
        _title_needs_complete_roster(t)
        and any(term in t for term in machine_terms)
        and ("ever built" in t or any(term in t for term in broad_terms) or bool(re.search(r"\bevery\b", t)))
    )


def _payload_blob(payload: Any) -> str:
    import json
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return str(payload or "")


def _apply_camera_preset_override(prompt: str, camera_preset_id: Optional[str]) -> str:
    """C23 (checklist §2.2): a manual camera-preset pick (assets.camera_
    preset_id, set via the Scenes tab chip or the copilot's "use a crash
    zoom on scene 12") wins OUTRIGHT over the auto/"earned" motion prompt
    for a silent (non-dialogue) shot — see run_clip_generation._one's
    non-speaking branch, the one call site.

    get_move() returning None (blank/unknown id — every row before C23,
    and every row nobody has touched since) is a no-op: `prompt` comes back
    unchanged, so this is byte-identical to pre-C23 behavior whenever
    camera_preset_id is NULL. This is a pure function on purpose (no DB, no
    I/O) so the composition contract is directly unit-testable without
    mocking the whole clip-generation closure."""
    from image_prompts.engine.camera_moves import get_move
    move = get_move(camera_preset_id)
    return move.motion_prompt if move else prompt


def _spoken_word_count(text: str) -> int:
    """Deterministic voiceover word count.

    Never trust the model to self-report counts. Count in code, treating
    designations such as B-52 and contractions/hyphenations as one spoken token.
    """
    import re
    return len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", str(text or "")))


# QD-6 / QL-1 word law (approved 2026-07-16): universal HARD floor/ceiling with
# an advisory warn band and per-register targets. 80 passes 96% of the Anton
# corpus; a 90+ floor rejects the median entry of two shipped scripts.
_ANTON_PARAGRAPH_HARD_MIN_WORDS = 80
_ANTON_PARAGRAPH_HARD_MAX_WORDS = 170
_ANTON_PARAGRAPH_MIN_WORDS = 95   # warn-band top: 80-95 = advisory "confirm terse"
_ANTON_PARAGRAPH_MAX_WORDS = 120  # spec-block register ceiling (guidance band)

# QL-1 registers: the law names the register and its band, not one number.
# The bomber-style spec-block video targets 100-120.
_DVSU_REGISTER_TARGETS = {
    "tight_production": "85-105",
    "spec_block": "100-120",
    "long_form": "110-130",
}
_DVSU_DEFAULT_REGISTER = "spec_block"

# Advisory channel: warn-severity law flags carry this prefix. They surface in
# stored warnings for review but never block, never trigger a repair round.
_ADVISORY_PREFIX = "advisory: "


def _blocking_warnings(warnings: list) -> list:
    """Warn-severity (advisory-prefixed) flags never block or trigger repair."""
    return [
        warning for warning in (warnings or [])
        if not str(warning).startswith(_ADVISORY_PREFIX)
    ]


def _review_messages(warnings: list) -> list:
    """N5: user-facing review text drops the raw machine tag and labels
    warn-severity flags plainly."""
    rendered = []
    for warning in warnings or []:
        text = str(warning)
        if text.startswith(_ADVISORY_PREFIX):
            rendered.append(text[len(_ADVISORY_PREFIX):] + " (advisory)")
        else:
            rendered.append(text)
    return rendered


# QL-4 (OR-3 approved): expanded twist taxonomy - 5 canonical types + 11 named
# subtypes. "other" is a last resort; a script run over 40% "other" warns.
_DVSU_TWIST_TYPES = (
    "role_change", "obsolete_but_enduring", "myth_vs_reality", "cheap_beats_good",
    "ambition_outran_tech",
    "lost_fly_off", "treaty_politics_cancelled", "cost_killed",
    "mission_obsoleted_by_countermeasure", "redundant_backup", "incremental_stopgap",
    "peaked_obsolete_concept", "killed_by_secondary_threat", "self_destruction",
    "role_discontinued_by_budget", "built_for_a_threat_that_never_existed",
)
# QL-3: when the machine was used exactly as designed ("absent"), the entry
# MUST substitute one of these payloads.
_DVSU_TWIST_SUBSTITUTES = ("superlative", "legacy", "irony", "anti_twist")

# QL-12 baseline: ad hoc subjective-superlative phrase list (pre-dates the
# table-driven QL-12 banned-ADJECTIVE list; checklist C46c UNIONS a seeded
# QL-12 row's list with this one rather than replacing it - the two lists
# catch different things and additivity never regresses coverage).
_ANTON_HYPE_PHRASES = (
    "one of the greatest", "one of the most incredible", "arguably the greatest",
    "arguably the most", "undoubtedly", "iconic", "legendary", "game-changing",
)

# QL-66 (OR-9 RULED 2026-07-19 - checklist C46e): established DvsU series use
# IMMUTABLE thumbnail text, never reworded/synonym-swapped. Five locked
# phrases; a title matching none of them falls under the open 2-4-word rule.
# "BY PILOTS"/"BY CREWS" also top-perform per the law doc's own note, but
# Ryan's ruling keeps them OUT of this locked set until they prove out as
# their own series - so they are deliberately absent here, not an oversight.
# Audit note: before this chunk, NO code anywhere in this repo (StoryEngine
# or the legacy skills/video-pipeline) implemented this law at all - the
# checklist's "verify already matches, expected no change" premise did not
# hold; this is genuinely new, minimal, advisory-only (never blocking a live
# thumbnail generation this chunk didn't budget to load-test as a hard gate).
_DVSU_LOCKED_THUMBNAIL_SERIES: tuple[tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"\bevery\b.*\bever built\b", re.IGNORECASE), "EVER BUILT"),
    (re.compile(r"\bnever[- ]built\b", re.IGNORECASE), "NEVER BUILT"),
    (re.compile(r"\bmost hated\b", re.IGNORECASE), "MOST HATED"),
    (re.compile(r"\bmost underrated\b", re.IGNORECASE), "UNDERRATED"),
    (re.compile(r"\bsunk in combat\b", re.IGNORECASE), "SUNK IN COMBAT"),
)


def _dvsu_thumbnail_series_warning(title: str, thumbnail_text: str) -> Optional[str]:
    """QL-66: for a title matching one of the five established DvsU series,
    the thumbnail text must be the EXACT locked phrase - never reworded or
    synonym-swapped. A title matching no known series is unconstrained (the
    open 2-4-word rule). Returns a warning string when a known series' text
    doesn't match exactly (case-insensitive), else None. Pure, no DB/network -
    callers decide what to do with a non-None result (this chunk: log it as
    an advisory, never block)."""
    title_text = str(title or "")
    candidate = str(thumbnail_text or "").strip()
    for pattern, locked_phrase in _DVSU_LOCKED_THUMBNAIL_SERIES:
        if pattern.search(title_text):
            if candidate.upper() != locked_phrase:
                return (
                    f"QL-66: title matches the {locked_phrase!r} series - thumbnail text must be "
                    f"the exact locked phrase {locked_phrase!r}, not {candidate!r}."
                )
            return None
    return None

# B1 closer ruling (2026-07-16): nationality/geographic proper adjectives and
# place nouns are EDITORIAL COLOR in a closer ("over German skies") - advisory,
# never blocking. Curated for the military-history domain; extend as needed.
_GEOGRAPHIC_COLOR_WORDS = {
    "africa", "african", "america", "american", "asia", "asian", "atlantic",
    "australia", "australian", "berlin", "britain", "british", "china",
    "chinese", "europe", "european", "france", "french", "german", "germany",
    "hawaii", "hawaiian", "italian", "italy", "japan", "japanese", "korea",
    "korean", "london", "mediterranean", "moscow", "pacific", "russia",
    "russian", "soviet", "soviets", "tokyo", "vietnam", "vietnamese",
    "washington",
}

# QL-5 verdict-punch gate: contrast markers that mark a "turn" in the closer.
_DVSU_CONTRAST_MARKERS = (
    "but", "yet", "instead", "not", "never", "no", "still", "though", "although",
    "while", "whereas", "until", "only", "however", "except", "without",
)

_MONTH_NAMES = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}
_ANTON_PARAGRAPH_MIN_SENTENCES = 4
_ANTON_PARAGRAPH_MAX_SENTENCES = 7
_ANTON_PARAGRAPH_FORMULA_SENTENCES = 5
_ANTON_PARAGRAPH_TARGET_WORDS = "100-112"
_ANTON_PARAGRAPH_WORD_RANGE = f"{_ANTON_PARAGRAPH_MIN_WORDS}-{_ANTON_PARAGRAPH_MAX_WORDS}"
_ANTON_PARAGRAPH_SENTENCE_RANGE = f"{_ANTON_PARAGRAPH_MIN_SENTENCES}-{_ANTON_PARAGRAPH_MAX_SENTENCES}"
_ANTON_PARAGRAPH_FORMULA = "4 evidence-backed sentences + 1 paragraph-derived conclusion"
_ANTON_FINAL_SENTENCE_MAX_WORDS = 25

_ANTON_REFERENCE_BENCHMARKS = {
    "XB15": {
        "source_video": "Every US Strategic Bomber Ever Built",
        "reference_machine": "Boeing XB-15",
        "reference_order": 1,
        "word_count": 94,
        "sentence_count": 5,
        "opening_mode": "machine/date/significance",
        "sentence_jobs": [
            "problem: open with machine identity, date/context, and why the problem matters",
            "decision: use selected scale or capability evidence as the design answer",
            "tradeoff: pivot from ambition to the limiting compromise",
            "reality: show documented production, service, testing, or operational outcome",
            "landing: validate or reverse the concept without adding a new event",
        ],
        "final_line_job": "land on what the first four sentences prove, without new events or numbers",
    },
    "B17": {
        "source_video": "Every US Strategic Bomber Ever Built",
        "reference_machine": "Boeing B-17 Flying Fortress",
        "reference_order": 2,
        "word_count": 116,
        "sentence_count": 7,
        "opening_mode": "machine/service/significance",
        "sentence_jobs": [
            "problem: open with service role, significance, and thesis tension",
            "decision: turn selected capability facts into proof of doctrine or design",
            "tradeoff: show the assumption, limit, or sacrifice created by that design",
            "reality: use production, service, or loss evidence to reveal the cost",
            "landing: land on consequence or cost, not retirement or generic importance",
        ],
        "final_line_job": "land on the cost or consequence already shown",
    },
    "B24": {
        "source_video": "Every US Strategic Bomber Ever Built",
        "reference_machine": "Consolidated B-24 Liberator",
        "reference_order": 3,
        "word_count": 110,
        "sentence_count": 6,
        "opening_mode": "machine/date/production significance",
        "sentence_jobs": [
            "problem: open with date, production significance, or industrial need",
            "decision: use selected efficiency, range, or output evidence as the design answer",
            "tradeoff: contrast capability with handling, operational, or human cost",
            "reality: show production or service spread from locked evidence",
            "landing: land on the strategic consequence of the design choice",
        ],
        "final_line_job": "land on consequence, not a list ending",
    },
}


def _anton_reference_benchmark_profile(machine: str) -> Optional[dict]:
    """Shape-only benchmark from Anton's first strategic-bomber paragraphs."""
    key = _normalized_unit_code(machine)
    profile = _ANTON_REFERENCE_BENCHMARKS.get(key)
    if not profile:
        return None
    return dict(profile)


def _research_card_for_machine(payload: dict, machine: str) -> Optional[dict]:
    """Return the one-machine research card matching a locked roster item.

    Supports the planned `unit_research_cards[]` shape plus a few obvious
    aliases so older proof payloads don't break. Matching is deliberately
    conservative: exact normalized display/code match first, containment second.
    """
    if not isinstance(payload, dict):
        return None
    cards = payload.get("unit_research_cards") or payload.get("machine_research_cards") or payload.get("research_cards")
    if not isinstance(cards, list):
        return None
    target_name = _unit_display_name(machine).strip().lower()
    target_code = _normalized_unit_code(machine)
    for card in cards:
        if not isinstance(card, dict):
            continue
        raw_unit = (
            card.get("unit")
            or card.get("machine")
            or card.get("name")
            or card.get("designation")
            or card.get("title")
            or ""
        )
        card_name = _unit_display_name(raw_unit).strip().lower()
        card_code = _normalized_unit_code(_unit_display_name(raw_unit))
        if target_name and card_name == target_name:
            return card
        if target_code and card_code == target_code:
            return card
        # Common card shape: {"unit": {"name": "Boeing XB-15", ...}}
        if isinstance(raw_unit, dict):
            nested_name = _unit_display_name(raw_unit).strip().lower()
            nested_code = _normalized_unit_code(_unit_display_name(raw_unit))
            if (target_name and nested_name == target_name) or (target_code and nested_code == target_code):
                return card
        # No substring fallback: B-2/B-21 and B-1/B-10 must never collide.
    return None


def _locked_roster_item_for_machine(roster: list[str], machine: str) -> Optional[str]:
    """Return the canonical locked-roster item matching a user/UI machine label."""
    target_name = _unit_display_name(machine).strip().lower()
    target_code = _normalized_unit_code(_unit_display_name(machine))
    for item in roster or []:
        roster_name = _unit_display_name(item).strip().lower()
        roster_code = _normalized_unit_code(item)
        if target_code and roster_code == target_code:
            return item
        if target_name and roster_name == target_name:
            return item
    return None


def _roster_index_for_identity(roster: list[str], identity: Any) -> Optional[int]:
    """Resolve a card/machine identity to its 1-based slot in a locked roster.

    This is the roster's real row identity (machine_research_cards migration
    153 - see that migration for why machine_key alone cannot be trusted).
    Exact display-name match first: unambiguous even when two DIFFERENT
    roster entries derive the same _normalized_unit_code (e.g. "Audacious
    class / Malta class" and "CVA-01 class" both normalize to CVA01, but
    their display names never collide). Falls back to a code match only
    when exactly one roster entry has that code."""
    name = _unit_display_name(identity).strip().lower()
    if name:
        for index, machine in enumerate(roster or [], start=1):
            if _unit_display_name(machine).strip().lower() == name:
                return index
    code = _normalized_unit_code(_unit_display_name(identity))
    if not code:
        return None
    candidates = [
        index for index, machine in enumerate(roster or [], start=1)
        if _normalized_unit_code(machine) == code
    ]
    return candidates[0] if len(candidates) == 1 else None


def _research_source_for_machine(payload: dict, machine: str) -> tuple[str, str]:
    """Prefer one-machine card context; fall back to legacy video-level research."""
    import json
    card = _research_card_for_machine(payload, machine)
    if card:
        return json.dumps(card, ensure_ascii=False, indent=2)[:9000], "unit_research_card"
    source = "\n\n".join(
        str(payload.get(k) or "")
        for k in ("fact_sheet", "source_bibliography", "framework_analysis", "historical_parallels")
        if payload.get(k)
    )[:14000]
    return source, "legacy_research_blob"


def _target_machine_research_source(payload: dict, machine: str) -> str:
    """Return only source snippets that mention the locked target machine."""
    import re

    if not isinstance(payload, dict):
        payload = {}
    target_code = _normalized_unit_code(_unit_display_name(machine))
    target_name = _unit_display_name(machine).strip().lower()
    source_keys = (
        "fact_sheet",
        "source_bibliography",
        "framework_analysis",
        "historical_parallels",
        "roster_contract",
    )
    parts: list[str] = []
    for key in source_keys:
        text = str(payload.get(key) or "")
        if not text.strip():
            continue
        snippets: list[str] = []
        for chunk in re.split(r"(?<=[.!?])\s+|\n+", text):
            chunk = " ".join(str(chunk or "").split())
            if not chunk:
                continue
            chunk_code = _normalized_unit_code(chunk)
            chunk_lower = chunk.lower()
            if (target_code and target_code in chunk_code) or (target_name and target_name in chunk_lower):
                snippets.append(chunk)
            if len("\n".join(snippets)) >= 3500:
                break
        if snippets:
            parts.append(f"{key} target snippets:\n" + "\n".join(snippets))
    if parts:
        return "\n\n".join(parts)[:16000]
    return (
        f"No preloaded source excerpts are supplied for {machine}. "
        "Collect or select raw excerpts only for this locked machine; do not use other roster cards."
    )


def _source_text_fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(str(text or "").split()).encode("utf-8")).hexdigest()


def _verified_source_cache_key(machine: str) -> str:
    return _normalized_unit_code(_unit_display_name(machine))


def _clear_machine_preview_artifacts(payload: dict, machine_key: str) -> None:
    """Drop preview artifacts that were generated from older research for this machine."""
    if not isinstance(payload, dict) or not machine_key:
        return
    import json as _json_clear

    for field_name in ("machine_script_previews", "machine_script_briefs", "machine_story_plans"):
        artifacts = payload.get(field_name)
        if isinstance(artifacts, str):
            try:
                artifacts = _json_clear.loads(artifacts)
            except Exception:
                artifacts = {}
        if not isinstance(artifacts, dict):
            continue
        updated = dict(artifacts)
        updated.pop(machine_key, None)
        payload[field_name] = updated


def _verified_source_package_for_machine(payload: dict, machine: str) -> Optional[dict]:
    """Find the fetched raw-source package for one locked machine."""
    if not isinstance(payload, dict):
        return None
    packages = payload.get("machine_raw_source_packages")
    if not packages:
        return None

    target_code = _verified_source_cache_key(machine)
    target_name = _unit_display_name(machine).strip().lower()

    def package_matches(raw_key: Any, package: Any) -> bool:
        if not isinstance(package, dict):
            return False
        key_code = _normalized_unit_code(_unit_display_name(raw_key) or str(raw_key or ""))
        package_code = _normalized_unit_code(
            _unit_display_name(package.get("machine_key") or package.get("machine") or "")
        )
        package_name = _unit_display_name(package.get("machine") or "").strip().lower()
        if target_code and (key_code == target_code or package_code == target_code):
            return True
        return bool(target_name and package_name == target_name)

    if isinstance(packages, dict):
        direct = packages.get(target_code)
        if isinstance(direct, dict):
            return direct
        for raw_key, package in packages.items():
            if package_matches(raw_key, package):
                return package
    if isinstance(packages, list):
        for package in packages:
            if package_matches("", package):
                return package
    return None


_CITATION_MARKER_RE = re.compile(r"\[(?:\d+|[a-z]|note \d+|citation needed)\]", re.IGNORECASE)
_ORPHAN_PUNCTUATION_SPACE_RE = re.compile(r"\s+([,.;:!?)])")
_ONE_SIDED_HYPHEN_LEFT_RE = re.compile(r"(\w-)\s+(?=\w)")
_ONE_SIDED_HYPHEN_RIGHT_RE = re.compile(r"(?<=\w)\s+(-\w)")


def _normalized_source_text(text: str) -> str:
    """Tolerant fold for comparing a cited excerpt against fetched page text.

    Ported verbatim (GAP 1a, 2026-07-30) from the DVsU research simulator's
    ``_match_normalize`` (tasks/evidence/dvsu-research-simulator/build_package.py)
    - every one of these quirks rejected a REAL excerpt this week before being
    fixed there: a stripped inline citation marker left mid-sentence
    ("carrier.[9] The next ship..."), smart quotes/dashes a CMS renders instead
    of ASCII, NBSP standing in for a normal space, and the orphan space a
    stripped inline tag (a citation superscript or link) leaves behind - either
    before punctuation ("Treaty , Ark Royal") or on one side of a hyphen
    ("equipped- Hellcat IIs"). Applied identically to both sides of every
    excerpt-in-page-text comparison in this module, so the fold can only ever
    make a genuine match MORE likely to succeed, never less."""
    s = str(text or "")
    s = _CITATION_MARKER_RE.sub("", s)
    s = (
        s.replace("‘", "'").replace("’", "'")
         .replace("“", '"').replace("”", '"')
         .replace("–", "-").replace("—", "-")
         .replace(" ", " ")
    )
    s = " ".join(s.split()).lower()
    s = _ORPHAN_PUNCTUATION_SPACE_RE.sub(r"\1", s)
    s = _ONE_SIDED_HYPHEN_LEFT_RE.sub(r"\1", s)
    s = _ONE_SIDED_HYPHEN_RIGHT_RE.sub(r"\1", s)
    return s


def _html_to_visible_text(raw_html: str) -> str:
    """Lightweight HTML text extraction without adding another dependency."""
    import html as _html
    import re as _re

    text = _re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav).*?</\1>", " ", raw_html or "")
    text = _re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = _re.sub(r"(?is)</(p|div|section|article|li|tr|h[1-6])>", "\n", text)
    text = _re.sub(r"(?is)<[^>]+>", " ", text)
    return " ".join(_html.unescape(text).split())


# G13, 2026-07-31: generic naval type-prefix words ("HMS", "USS", ...) were
# being added as standalone _mentions_machine terms the same way individual
# name words are - so ANY page mentioning ANY ship with the same navy prefix
# counted as "mentioning" every other ship in that navy's roster. Real
# evidence (video d05efae3): an iwm.org.uk search-results page titled "Search
# for 'HMS Northampton'" - a completely different ship - satisfied
# _mentions_machine("...", "53 HMS Prince of Wales") on the bare word "hms"
# alone; the excerpt never contained "prince" or "wales" anywhere. Excluding
# these generic prefixes mirrors the existing aircraft-manufacturer
# exclusion below (a page merely saying "Boeing" isn't evidence for a
# specific Boeing aircraft either).
_GENERIC_MACHINE_DESIGNATION_WORDS = frozenset({
    "boeing", "consolidated", "convair", "douglas", "northrop", "lockheed", "martin",
    "hms", "uss", "hmas", "hmcs", "hmnzs", "hmis", "rfa", "sms", "ijn", "rms", "ins",
})


def _machine_mention_terms(machine: str) -> set[str]:
    import re as _re

    machine_text = _unit_display_name(machine)
    terms = {machine_text.lower()}
    code = _unit_code(machine_text)
    if code:
        terms.add(code.lower())
        terms.add(code.replace("-", "").lower())
    for word in _re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", machine_text):
        if word.lower() not in _GENERIC_MACHINE_DESIGNATION_WORDS:
            terms.add(word.lower())
    return {term for term in terms if term and len(term) >= 3}


def _mentions_machine(text: str, machine: str) -> bool:
    normalized = _normalized_source_text(text).replace("–", "-").replace("—", "-")
    for term in _machine_mention_terms(machine):
        pieces = re.findall(r"[a-z0-9]+", term.lower())
        if not pieces:
            continue
        if any(char.isdigit() for char in term):
            pattern = r"(?<![a-z0-9])" + r"[\s.\-]*".join(re.escape(piece) for piece in pieces)
            if not pieces[-1][-1:].isdigit():
                pattern += r"(?![a-z0-9])"
            else:
                pattern += r"(?:[a-z])?(?![a-z0-9])"
        else:
            pattern = r"(?<![a-z0-9])" + r"[\s.\-']+".join(re.escape(piece) for piece in pieces) + r"(?![a-z0-9])"
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return True
    return False


def _paragraph_opens_with_machine_name(paragraph: str, machine: str) -> bool:
    import re as _re

    sentence_parts = [
        part.strip()
        for part in _re.split(r"(?<=[.!?])\s+", str(paragraph or "").strip())
        if part.strip()
    ]
    if not sentence_parts:
        return False
    first_sentence = sentence_parts[0]
    machine_text = _unit_display_name(machine)
    terms = [machine_text]
    code = _unit_code(machine_text)
    if code:
        terms.extend([code, code.replace("-", "")])
    terms.extend(_re.findall(r"\b[A-Z]{1,4}-?\d{1,4}[A-Z]?\b", machine_text.upper()))
    for term in dict.fromkeys(item for item in terms if str(item or "").strip()):
        pieces = _re.findall(r"[A-Za-z0-9]+", str(term))
        if not pieces:
            continue
        pattern = (
            r"^[\"'(\[]*\s*(?:the\s+)?"
            + r"[\s.\-']*".join(_re.escape(piece) for piece in pieces)
            + r"s?(?:\b|[^A-Za-z0-9])"
        )
        if _re.search(pattern, first_sentence, flags=_re.IGNORECASE):
            return True
    return False


def _opening_assignment_warnings(machine: str, paragraph: str, opening_assignment: str) -> list[str]:
    assignment = str(opening_assignment or "").strip().lower()
    if "do not open with the machine name" not in assignment:
        return []
    if _paragraph_opens_with_machine_name(paragraph, machine):
        return ["opening assignment forbids machine-name opening"]
    return []


def _sentence_candidates_from_source(text: str, machine: str, limit: int = 10) -> list[str]:
    import re as _re

    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    raw_sentences = [
        " ".join(sentence.split()).strip()
        for sentence in _re.split(r"(?<=[.!?])\s+", cleaned)
        if " ".join(sentence.split()).strip()
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for span in (1, 2, 3):
        for index, sentence in enumerate(raw_sentences):
            if not _mentions_machine(sentence, machine) or index + span > len(raw_sentences):
                continue
            window = " ".join(raw_sentences[index:index + span]).strip()
            if len(window) < 45 or len(window) > 720:
                continue
            key = _normalized_source_text(window)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(window)
            if len(candidates) >= limit:
                return candidates
    return candidates


def _machine_source_variant_score(excerpts: list[str], machine: str) -> tuple[int, int, int]:
    """Score a fetched/raw source variant by usable Anton beat coverage."""
    coverage_candidates = [
        {"excerpt_id": f"V-E{index}", "text": excerpt}
        for index, excerpt in enumerate(excerpts or [], start=1)
    ]
    coverage = _anton_source_slot_coverage(coverage_candidates, machine)
    return (
        len(coverage.get("covered_slots") or []),
        int(coverage.get("distinct_slot_excerpt_count") or 0),
        len(excerpts or []),
    )


def _machine_source_variant_selection_metadata(
    source_variants: list[tuple[tuple[int, int, int, int], str, str, list[str]]],
    selected_capture_method: str,
) -> dict:
    """Review metadata for why one exact-text capture method was saved."""
    evaluated: list[dict] = []
    selected_variant: dict = {}
    for score, capture_method, source_text, excerpt_candidates in source_variants:
        row = {
            "source_capture_method": capture_method,
            "covered_slot_count": score[0],
            "distinct_slot_excerpt_count": score[1],
            "excerpt_count": score[2],
            "method_priority": score[3],
            "text_hash": _source_text_fingerprint(source_text),
            "text_chars": len(source_text or ""),
        }
        evaluated.append(row)
        if capture_method == selected_capture_method:
            selected_variant = dict(row)
    return {
        "selected_capture_method": selected_capture_method,
        "selected_variant": selected_variant,
        "evaluated_variants": evaluated,
        "selection_rule": (
            "highest Anton-slot coverage, then distinct required-slot excerpts, "
            "then excerpt count; fetched_page wins exact ties"
        ),
    }


def _source_variant_selection_summary(selection: Any) -> str:
    """Compact source-choice provenance for the verified-source prompt block."""
    if not isinstance(selection, dict):
        return ""
    selected_method = str(
        selection.get("selected_capture_method")
        or (selection.get("selected_variant") or {}).get("source_capture_method")
        or ""
    ).strip()
    variants = selection.get("evaluated_variants")
    variants = variants if isinstance(variants, list) else []
    selected_variant = selection.get("selected_variant") if isinstance(selection.get("selected_variant"), dict) else {}
    if not selected_variant and selected_method:
        selected_variant = next(
            (
                variant for variant in variants
                if isinstance(variant, dict)
                and str(variant.get("source_capture_method") or "").strip() == selected_method
            ),
            {},
        )
    compared = [
        str(variant.get("source_capture_method") or "").strip()
        for variant in variants
        if isinstance(variant, dict) and str(variant.get("source_capture_method") or "").strip()
    ]
    score = ""
    if isinstance(selected_variant, dict) and selected_variant:
        try:
            covered = int(selected_variant.get("covered_slot_count") or 0)
            distinct = int(selected_variant.get("distinct_slot_excerpt_count") or 0)
            score = f"{covered} slots/{distinct} distinct"
        except (TypeError, ValueError):
            score = ""
    selected_hash = str((selected_variant or {}).get("text_hash") or "").strip()
    rule = " ".join(str(selection.get("selection_rule") or "").split())
    return "; ".join(
        part for part in [
            f"selected={selected_method}" if selected_method else "",
            f"score={score}" if score else "",
            f"selected_text_hash={selected_hash[:12]}" if selected_hash else "",
            f"compared={'/'.join(compared)}" if len(compared) > 1 else "",
            f"rule={rule}" if rule else "",
        ]
        if part
    )


def _verified_machine_source_package_ready(package: Any) -> bool:
    if not isinstance(package, dict) or package.get("passed") is False:
        return False
    excerpts = package.get("candidate_excerpts")
    if not isinstance(excerpts, list):
        return False
    text_excerpts = [
        item for item in excerpts
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    return len(text_excerpts) >= 6


_DIRECT_FETCH_CAPTURE_METHODS = {"fetched_page", "tavily_raw_content"}
# GAP 1(b), 2026-07-30: capture methods added when a live fetch AND Tavily's
# own raw content both come back empty. Each is still a mechanically-verified
# real fetch - just a different network path - so it must count exactly like
# "fetched_page" everywhere a capture method is gated. Ported from the DVsU
# research simulator's build_package.py fallback chain: a National Archives
# Discovery record's own JSON API, or a real Wayback Machine snapshot resolved
# through the availability API (never a claimed/fabricated archive URL).
_FALLBACK_FETCH_CAPTURE_METHODS = {"national_archives_api"}
_WAYBACK_CAPTURE_METHOD_PREFIX = "wayback:"
_NATIONAL_ARCHIVES_DISCOVERY_RECORD_RE = re.compile(r"nationalarchives\.gov\.uk/details/r/(\w+)")


def _is_approved_source_capture_method(capture_method: Any) -> bool:
    method = str(capture_method or "").strip()
    if not method:
        return False
    return (
        method in _DIRECT_FETCH_CAPTURE_METHODS
        or method in _FALLBACK_FETCH_CAPTURE_METHODS
        or method.startswith(_WAYBACK_CAPTURE_METHOD_PREFIX)
    )


def _verified_source_candidate_traceable(item: Any) -> bool:
    """A raw excerpt can only unlock a required beat if the card can cite it later."""
    if not isinstance(item, dict):
        return False
    source_url = str(item.get("source_url") or "").strip()
    locator = str(item.get("locator") or item.get("excerpt_id") or "").strip()
    capture_method = str(item.get("source_capture_method") or "").strip()
    return bool(
        source_url
        and locator
        and _is_approved_source_capture_method(capture_method)
    )


def _verified_machine_source_package_with_anton_metadata(package: Any, machine: str = "") -> Any:
    """Return a raw-source package with reviewable Anton slot metadata attached."""
    if not _verified_machine_source_package_ready(package):
        return package
    hydrated = dict(package)
    hydrated_candidates: list[Any] = [
        dict(item) if isinstance(item, dict) else item
        for item in (hydrated.get("candidate_excerpts") or [])
    ]
    hydrated["candidate_excerpts"] = hydrated_candidates
    hydrated.setdefault("schema_version", 3)
    hydrated["source_slot_coverage"] = _anton_source_slot_coverage(
        [item for item in hydrated_candidates if isinstance(item, dict)],
        machine,
    )
    hydrated["traceable_source_slot_coverage"] = _anton_source_slot_coverage(
        [item for item in hydrated_candidates if _verified_source_candidate_traceable(item)],
        machine,
    )
    return hydrated


def _anton_source_slot_hints(text: str) -> set[str]:
    """Heuristic pre-LLM check that raw excerpts can support Anton's four beats."""
    lower = _normalized_source_text(text)
    hints: set[str] = set()
    slot_patterns = {
        "original_problem": (
            r"\bproblem\b",
            r"\b(?:requirement|required|called for|needed?|wanted|demanded|requested|specified)\b",
            r"\b(?:project|program|contract|mission|specification)\b",
            r"\b(?:designed|developed|intended)\s+to\b",
            r"\basked\s+(?:for|to|whether)\b",
            # Procurement-origin signals (2026-07-30, ship/vehicle domains):
            # naval histories state the need as an acquisition act — a hull
            # ordered, purchased, or requisitioned to fill a gap.
            r"\b(?:ordered|purchased?|requisitioned|laid down)\b",
        ),
        "engineering_decision": (
            r"\b(?:design|decision|built|developed|configured|equipped|mounted|carried|powered)\b",
            r"\b(?:wing|wingspan|fuselage|engine|engines|payload|range|speed|horsepower|propulsion)\b",
            r"\b(?:model|prototype|airframe|structure|configuration|feature|features)\b",
            # Ship/vehicle anatomy and shipyard verbs (2026-07-30): the list
            # above is aircraft vocabulary, so excerpts describing a flight
            # deck, hangar, island or a conversion/fitting-out never hinted
            # this beat and honest naval packages failed the coverage gate
            # (live case: HMS Eagle's "middle deck, as fitted for the
            # aircraft carrier Eagle").
            r"\b(?:deck|decks|hull|hangar|catapult|island|funnel|boiler|turbine|"
            r"armou?r|knots|conver(?:ted|sion)|fitted|refitted|rebuilt|turret|tracks)\b",
        ),
        "tradeoff": (
            r"\btrade[- ]?off\b",
            r"\b(?:limitation|limited|underpowered|slow|sluggish|obsolete|problem|failed|failure)\b",
            r"\b(?:could not|couldn['’]?t|unable|too\s+(?:slow|heavy|large|expensive|costly))\b",
            r"\b(?:sacrificed|compromise|drawback|despite|but|however|stranded|cancelled|canceled)\b",
        ),
        "reality": (
            r"\breality\b",
            r"\b(?:served|service|assigned|used|flew|operated|converted|transport|missions?)\b",
            r"\b(?:production|produced|built|prototype|prototypes|delivered|scrapped|retired)\b",
            r"\b(?:combat|war|world war|record|lost|losses|cancelled|canceled|operational)\b",
            # Loss-in-service verbs (2026-07-30): "sunk" was not reality
            # vocabulary, so the sinking of a warship - the single most
            # reality-laden fact a naval excerpt can state - hinted nothing
            # (found by the simulator's Courageous lane).
            r"\b(?:sunk|sank|torpedoed|mined|wrecked|foundered|capsized|shot down)\b",
            # Lifecycle verbs naval sources actually use for what-happened
            # facts (2026-07-30, Audacious/Malta lane): "completed",
            # "commissioned", "launched", "renamed" carried the entire
            # cancelled-programme-finished-as-different-ship story and
            # hinted nothing.
            r"\b(?:completed|commissioned|recommissioned|launched|renamed|laid up|paid off)\b",
        ),
    }
    for slot, patterns in slot_patterns.items():
        if any(re.search(pattern, lower) for pattern in patterns):
            hints.add(slot)
    return hints


def _excerpt_overlap_tokens(text: str, machine: str = "") -> set[str]:
    stopwords = {
        "a", "an", "and", "as", "by", "for", "from", "in", "into", "of", "on", "or",
        "source", "sourced", "supplied", "grounded", "claim", "claims", "exact",
        "text", "the", "this", "that", "to", "was", "with",
    }
    machine_tokens = set(re.findall(r"[a-z0-9]+", str(machine or "").lower()))
    return {
        token for token in re.findall(r"[a-z0-9]+", _normalized_source_text(text))
        if token not in stopwords and token not in machine_tokens
    }


def _excerpt_texts_overlap(left: str, right: str, machine: str = "") -> bool:
    """Return true when two saved excerpts are effectively the same evidence."""
    left_text = _normalized_source_text(left)
    right_text = _normalized_source_text(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text or left_text in right_text or right_text in left_text:
        return True
    left_tokens = _excerpt_overlap_tokens(left_text, machine)
    right_tokens = _excerpt_overlap_tokens(right_text, machine)
    if min(len(left_tokens), len(right_tokens)) < 12:
        return False
    overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    return overlap >= 0.95


def _distinct_anton_slot_assignment(
    coverage_by_slot: dict[str, list[str]],
    required_slots: list[str],
    excerpt_text_by_id: Optional[dict[str, str]] = None,
    machine: str = "",
) -> dict[str, str]:
    """Assign each required Anton beat to a different raw excerpt when possible."""
    ordered_slots = sorted(
        [slot for slot in required_slots if slot],
        key=lambda slot: len(coverage_by_slot.get(slot, [])),
    )
    assignment: dict[str, str] = {}
    used_excerpt_ids: set[str] = set()
    excerpt_text_by_id = excerpt_text_by_id or {}

    def conflicts_with_used(excerpt_id: str) -> bool:
        text = excerpt_text_by_id.get(excerpt_id, "")
        if not text:
            return False
        return any(
            _excerpt_texts_overlap(text, excerpt_text_by_id.get(used_id, ""), machine)
            for used_id in used_excerpt_ids
        )

    def assign(index: int) -> bool:
        if index >= len(ordered_slots):
            return True
        slot = ordered_slots[index]
        for excerpt_id in coverage_by_slot.get(slot, []):
            if not excerpt_id or excerpt_id in used_excerpt_ids or conflicts_with_used(excerpt_id):
                continue
            assignment[slot] = excerpt_id
            used_excerpt_ids.add(excerpt_id)
            if assign(index + 1):
                return True
            used_excerpt_ids.remove(excerpt_id)
            assignment.pop(slot, None)
        return False

    if not assign(0):
        return {}
    return {slot: assignment[slot] for slot in required_slots if slot in assignment}


def _anton_source_slot_coverage(candidates: list[dict], machine: str = "") -> dict:
    """Summarize raw-source coverage before the card-writing LLM runs."""
    coverage_by_slot: dict[str, list[str]] = {}
    excerpt_text_by_id: dict[str, str] = {}
    checked_excerpt_count = 0
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or (machine and not _mentions_machine(text, machine)):
            continue
        checked_excerpt_count += 1
        hints = sorted(_anton_source_slot_hints(text))
        item["anton_slot_hints"] = hints
        excerpt_id = str(item.get("excerpt_id") or item.get("locator") or "").strip()
        if excerpt_id:
            excerpt_text_by_id[excerpt_id] = text
        for slot in hints:
            if excerpt_id:
                coverage_by_slot.setdefault(slot, [])
                if excerpt_id not in coverage_by_slot[slot]:
                    coverage_by_slot[slot].append(excerpt_id)
    required_slots = [
        role for role, _accepted_kinds, _job in _ANTON_SLOT_SPECS
        if role in _ANTON_REQUIRED_SLOT_ROLES
    ]
    covered_slots = sorted(slot for slot in coverage_by_slot if slot in _ANTON_REQUIRED_SLOT_ROLES)
    distinct_assignment = _distinct_anton_slot_assignment(coverage_by_slot, required_slots, excerpt_text_by_id, machine)
    distinct_required_excerpts = sorted(set(distinct_assignment.values()))
    return {
        "required_slots": required_slots,
        "covered_slots": covered_slots,
        "missing_slots": sorted(set(required_slots) - set(covered_slots)),
        "distinct_slot_excerpt_assignment": distinct_assignment,
        "distinct_slot_excerpt_count": len(distinct_required_excerpts),
        "distinct_required_excerpt_ids": distinct_required_excerpts,
        "needs_distinct_slot_excerpts": len(distinct_assignment) < len(required_slots),
        "checked_excerpt_count": checked_excerpt_count,
        "evidence_by_slot": {
            slot: coverage_by_slot.get(slot, [])[:10]
            for slot in sorted(coverage_by_slot)
        },
    }


def _verified_machine_source_package_quality_errors(package: Any, machine: str = "") -> list[str]:
    """Reject thin raw-source packages before spending an LLM call."""
    if not _verified_machine_source_package_ready(package):
        return []
    candidates = [
        item for item in (package or {}).get("candidate_excerpts", [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    quality_candidates = candidates
    errors: list[str] = []
    if machine:
        quality_candidates = [
            item for item in candidates
            if _mentions_machine(str(item.get("text") or ""), machine)
        ]
        if len(quality_candidates) < 6:
            errors.append("Verified source package needs at least six exact excerpts mentioning the locked machine.")
        coverage = _anton_source_slot_coverage(quality_candidates, machine)
        traceable_quality_candidates = [
            item for item in quality_candidates
            if _verified_source_candidate_traceable(item)
        ]
        traceable_coverage = _anton_source_slot_coverage(traceable_quality_candidates, machine)
        missing_slots = coverage.get("missing_slots") or []
        if missing_slots:
            errors.append(
                "Verified source package needs exact excerpts plausibly covering Anton slot(s): "
                + ", ".join(missing_slots)
            )
        untraceable_slots: list[str] = []
        tier_four_only_slots: list[str] = []
        for slot in _ANTON_REQUIRED_SLOT_ROLES:
            slot_candidates = [
                item for item in quality_candidates
                if slot in (item.get("anton_slot_hints") or [])
            ]
            traceable_slot_candidates = [
                item for item in slot_candidates
                if _verified_source_candidate_traceable(item)
            ]
            if slot_candidates and not traceable_slot_candidates:
                untraceable_slots.append(slot)
            if traceable_slot_candidates and all(_source_tier_number(item) >= 4 for item in traceable_slot_candidates):
                tier_four_only_slots.append(slot)
        if untraceable_slots:
            errors.append(
                "Verified source package required Anton slot(s) need traceable source_url/locator excerpts: "
                + ", ".join(sorted(untraceable_slots))
            )
        if not missing_slots and not untraceable_slots and traceable_coverage.get("needs_distinct_slot_excerpts"):
            errors.append(
                "Verified source package needs distinct raw excerpts for each Anton slot that are traceable: "
                + ", ".join(traceable_coverage.get("required_slots") or [])
            )
        if tier_four_only_slots:
            # G14, 2026-07-31 (Ryan's ruling, decisions.md): a required beat
            # resting only on Tier 4/caution excerpts no longer blocks card
            # writing - it is worth flagging for review, not refusing the
            # card. _blocking_warnings() strips this advisory-prefixed
            # message; only genuinely blocking errors stop the writer.
            errors.append(
                _ADVISORY_PREFIX + "[caution_only_sources_advisory] "
                "Verified source package cannot support required Anton slot(s) only with Tier 4/caution excerpts: "
                + ", ".join(sorted(tier_four_only_slots))
            )
    source_urls = {
        str(item.get("source_url") or "").strip()
        for item in quality_candidates
        if str(item.get("source_url") or "").strip()
    }
    non_caution_urls = {
        str(item.get("source_url") or "").strip()
        for item in quality_candidates
        if str(item.get("source_url") or "").strip() and _source_tier_number(item) <= 3
    }
    # G13, 2026-07-31: a Tier 1-2 DOMAIN classification alone used to satisfy
    # this floor even when no candidate excerpt from that source was actually
    # relevant (real evidence: PoW's only "Tier 2" was an iwm.org.uk page
    # about HMS Northampton, a different ship; Howe's two "Tier 1" hits were
    # a giant USAF PDF and a US Pacific Fleet roster that only mention Howe
    # in passing). _tier_floor_relevant_excerpt requires the excerpt itself
    # to be genuinely about the machine, not just filed under a Tier 1-2
    # domain - guarded by `not machine` so callers that never pass a machine
    # (several existing quality-error checks above) keep their prior,
    # machine-agnostic behavior unchanged.
    authoritative_urls = {
        str(item.get("source_url") or "").strip()
        for item in quality_candidates
        if (
            str(item.get("source_url") or "").strip()
            and 1 <= _source_tier_number(item) <= 2
            and (not machine or _tier_floor_relevant_excerpt(str(item.get("text") or ""), machine))
        )
    }
    unsupported_capture_methods = sorted({
        str(item.get("source_capture_method") or "").strip()
        for item in quality_candidates
        if str(item.get("source_capture_method") or "").strip()
        and not _is_approved_source_capture_method(item.get("source_capture_method"))
    })
    missing_capture_method_count = sum(
        1 for item in quality_candidates
        if not str(item.get("source_capture_method") or "").strip()
    )
    missing_source_variant_selection_count = sum(
        1 for item in quality_candidates
        if not isinstance(item.get("source_variant_selection"), dict)
    )
    if len(source_urls) < 2:
        errors.append("Verified source package needs excerpts from at least two distinct source URLs.")
    # G14, 2026-07-31 (Ryan's ruling, decisions.md): the tier floor drops from
    # HARD BLOCK to advisory. "The accurate Wikipedia article is sitting
    # right there, let it carry the card" - Wikipedia-grade (Tier 3-4)
    # sources may now carry a card on their own. These two package-wide
    # floors are the ONLY entries in this function demoted; every other
    # error here (excerpt count, slot coverage, traceability, distinct
    # excerpts, capture method, source-selection provenance) is unrelated to
    # tier and stays a hard block. A pure-Tier-4 package (zero non-caution
    # sources anywhere) gets the louder caution_only_sources_advisory tag; a
    # package missing only the top Tier 1-2 primary/authoritative bar (but
    # holding Tier 3 reference sources) gets tier_floor_advisory.
    if not non_caution_urls:
        errors.append(
            _ADVISORY_PREFIX + "[caution_only_sources_advisory] "
            "Verified source package needs at least one non-caution source before Claude can write a card."
        )
    if not authoritative_urls:
        errors.append(
            _ADVISORY_PREFIX + "[tier_floor_advisory] "
            "Verified source package needs at least one Tier 1-2 primary/authoritative source before Claude can write a card."
        )
    if missing_capture_method_count:
        errors.append(
            f"Verified source package has {missing_capture_method_count} exact excerpt(s) without source capture method."
        )
    if unsupported_capture_methods:
        errors.append(
            "Verified source package contains unsupported source capture method(s): "
            + ", ".join(unsupported_capture_methods)
        )
    if missing_source_variant_selection_count:
        errors.append(
            f"Verified source package has {missing_source_variant_selection_count} exact excerpt(s) without source selection provenance."
        )
    return errors


def _verified_machine_source_package_identity_errors(package: Any, machine: str) -> list[str]:
    """Reject stale raw-source packages saved under the wrong machine key."""
    if not _verified_machine_source_package_ready(package):
        return []
    target_code = _verified_source_cache_key(machine)
    package_key = _normalized_unit_code(str((package or {}).get("machine_key") or ""))
    package_machine = _normalized_unit_code(_unit_display_name((package or {}).get("machine") or ""))
    errors: list[str] = []
    if not package_key and not package_machine:
        errors.append("Verified source package missing machine identity.")
    if package_key and package_key != target_code:
        errors.append(f"Verified source package machine_key {package_key} does not match locked machine {target_code}.")
    if package_machine and package_machine != target_code:
        errors.append(f"Verified source package machine {package_machine} does not match locked machine {target_code}.")
    return errors


def _source_tier_for_url(url: str, title: str = "") -> dict[str, Any]:
    """Classify fetched sources using the DVsU verification hierarchy."""
    host = urlparse(str(url or "")).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    title_l = str(title or "").lower()
    host_l = host.lower()
    caution_hosts = (
        "wikipedia.org", "youtube.com", "youtu.be", "facebook.com", "instagram.com",
        "tiktok.com", "x.com", "twitter.com", "reddit.com", "quora.com",
        "fandom.com", "pinterest.com",
    )
    if any(host_l == item or host_l.endswith(f".{item}") for item in caution_hosts):
        return {"tier": 4, "label": "Tier 4 caution/general"}
    if "forum" in host_l or "wiki" in host_l:
        return {"tier": 4, "label": "Tier 4 caution/general"}
    primary_hosts = (
        "boeing.com", "lockheedmartin.com", "northropgrumman.com", "rtx.com",
        "prattwhitney.com", "geaerospace.com", "defense.gov", "af.mil",
        "army.mil", "navy.mil", "marines.mil", "usafa.edu", "nasa.gov",
        "archives.gov", "congress.gov",
        # Non-US official/military (2026-07-30): the endswith(".gov")/".mil"
        # rule silently missed every Commonwealth institution — awm.gov.au
        # ends ".gov.au", royalnavy.mod.uk ends ".mod.uk" — so a Royal Navy
        # documentary's most authoritative sources were graded Tier 3
        # reference. mod.uk covers the whole UK Ministry of Defence estate;
        # navy.lk is the Sri Lanka Navy (HMS Hermes' wreck custodian).
        "mod.uk", "navy.lk",
        # Apex government domains escape the ".gov."-component rule below
        # (host "gov.uk" has no leading dot to match), and the National
        # Audit Office is an official UK body on a plain .org.uk domain.
        "gov.uk", "nao.org.uk",
    )
    # ".gov."/".govt."/".mil." as an inner TLD component catches gov.uk /
    # gov.au / govt.nz / mil.nz etc. without whitelisting every country.
    if (
        host_l.endswith(".gov") or host_l.endswith(".mil")
        or ".gov." in f"{host_l}." or ".govt." in f"{host_l}." or ".mil." in f"{host_l}."
        or any(host_l == item or host_l.endswith(f".{item}") for item in primary_hosts)
    ):
        return {"tier": 1, "label": "Tier 1 primary/official"}
    authoritative_hosts = (
        "si.edu", "airandspace.si.edu", "nationalww2museum.org", "iwm.org.uk",
        "imperialwarmuseums.org.uk", "rafmuseum.org.uk", "aerospace.org",
        "historynet.com", "aviation-history.com",
        # Naval museums (2026-07-30, same domain-bias fix as primary_hosts):
        # Royal Museums Greenwich and the National Museum of the Royal Navy
        # carry no "museum" substring in their hostnames, so the fallback
        # heuristic below never caught them.
        "rmg.co.uk", "nmrn.org.uk",
    )
    if any(host_l == item or host_l.endswith(f".{item}") for item in authoritative_hosts):
        return {"tier": 2, "label": "Tier 2 museum/authoritative secondary"}
    if "museum" in host_l or "museum" in title_l or "archive" in host_l:
        return {"tier": 2, "label": "Tier 2 museum/authoritative secondary"}
    return {"tier": 3, "label": "Tier 3 reference/secondary"}


def _source_tier_number(item: dict) -> int:
    try:
        tier = int(item.get("source_tier") or item.get("tier") or 0)
    except Exception:
        tier = 0
    if tier:
        return tier
    inferred = _source_tier_for_url(
        str(item.get("source_url") or item.get("url") or ""),
        str(item.get("source_title") or item.get("title") or ""),
    )
    return int(inferred["tier"])


_ANTON_SLOT_SPECS = (
    ("original_problem", ("original_problem", "design_problem", "engineering_intent", "design_requirement", "doctrinal_problem", "identity_origin", "design_intent"), "Raw excerpt for the problem, requirement, or need that made this machine enter the story."),
    ("engineering_decision", ("engineering_decision", "engineering_response", "design_response", "scale_specs", "validated_concept"), "Raw excerpt for the design or engineering decision made in response to that problem."),
    ("tradeoff", ("tradeoff", "tradeoff_or_limit", "limitation", "failure_mode"), "Raw excerpt for the sacrifice, limitation, or tradeoff created by the decision."),
    ("reality", ("reality", "actual_reality", "actual_outcome", "service_reality", "operational_reality", "combat_reality", "test_result", "build_reality", "production_reality", "prototype_reality", "historical_meaning", "legacy"), "Raw excerpt for what happened in testing, production, service, or combat reality, including exact downstream consequences when sourced."),
    ("identity_origin", ("identity_origin_context",), "Optional concise identity context when it is not already covered by original_problem."),
    ("scale_specs", ("scale_specs_context",), "Optional supporting scale/capability detail when it proves the engineering decision."),
    ("build_reality", ("build_reality_context",), "Optional supporting build or production detail when it is not the main reality beat."),
    ("service_reality", ("service_reality_context",), "Optional supporting service detail when it is not the main reality beat."),
    ("memorable_fact", ("memorable_fact", "surprising_fact", "retention_fact"), "Optional sourced fact serious viewers are unlikely to know; embed it only when it strengthens one of the four beats."),
    ("role_category", ("role_category", "classification"), "Name the role or category only when it helps the viewer understand the engineering lane."),
    ("human_detail", ("human_detail", "human_account", "named_person_detail"), "Optional named human detail or official finding; use only when directly sourced and attributed."),
    ("transition_hook", ("transition_hook",), "Optional bridge to the previous or next machine; never required for standalone preview quality."),
    ("onscreen_label", ("onscreen_label",), "On-screen metadata ingredients: full name, concise role, operator or build count, and service/date range; never spoken narration."),
    # Support slots for the two required CARD FIELDS (ruling 2026-07-16): the
    # contract demands timeframe_evidence_ids / visual_identity_evidence_ids,
    # so segments carrying that evidence must be legal kinds. Optional, never
    # narrative beats, never added to _ANTON_REQUIRED_SLOT_ROLES.
    ("timeframe", ("timeframe", "timeframe_context"), "Optional sourced dated anchor - first flight, service entry, or retirement - supporting the timeframe field; not a narrative beat."),
    ("visual_identity", ("visual_identity", "visual_identity_context", "visual_description"), "Optional sourced description of the machine's visible configuration supporting the visual_identity field; not a narrative beat."),
)


_ANTON_REQUIRED_SLOT_ROLES = {
    "original_problem",
    "engineering_decision",
    "tradeoff",
    "reality",
}


def _human_detail_has_attribution(text: str) -> bool:
    """Anton human-detail evidence must be named, or clearly official."""
    raw = str(text or "")
    lower = raw.lower()
    official_markers = (
        "official finding",
        "official inquiry",
        "inquiry finding",
        "accident report",
        "combat report",
        "test report",
        "after-action report",
        "board found",
        "board concluded",
        "report found",
        "report concluded",
        "memo warned",
        "letter warned",
        "official decision",
        "documented decision",
        "command decision",
        "ordered by",
        "recorded decision",
    )
    if any(marker in lower for marker in official_markers):
        return True

    machine_or_institution = {
        "Air Force",
        "Army Air",
        "Boeing XB",
        "Designed Vs",
        "Designed vs",
        "National Museum",
        "United States",
        "World War",
    }
    name_pattern = r"\b[A-Z][a-z]+(?:\s+(?:[A-Z]\.)?)*\s+[A-Z][a-z]+\b"
    for match in re.findall(name_pattern, raw):
        if any(term in match for term in machine_or_institution):
            continue
        return True
    return False


def _anton_slot_role_for_kind(kind: str) -> Optional[str]:
    normalized = str(kind or "").strip().lower()
    for role, accepted_kinds, _job in _ANTON_SLOT_SPECS:
        if normalized in accepted_kinds:
            return role
    return None


def _format_verified_machine_source_package(package: dict, machine: str = "") -> str:
    lines = [
        "Verified source package. The model may use ONLY these fetched excerpts.",
        "Every returned source_excerpt must be copied from one candidate below.",
        "Only approved-capture, source_url/locator-traceable rows for the locked machine are shown.",
    ]
    # Enforceable conversion-signal excerpts are exempt from the non-target
    # designation skip below. The gap gate orders the card to select exactly
    # these rows, and a cross-designation ("redesignated XC-105") is often the
    # signal itself - hiding them made the MUST-SELECT demand unsatisfiable
    # (the XB-15 refusal loop, 2026-07-16).
    signal_excerpt_ids: set[str] = set()
    if machine:
        signal_excerpt_ids = {
            str(signal.get("excerpt_id") or "").strip()
            for signal in _package_conversion_signals(package, machine)
            if signal.get("enforce") and str(signal.get("excerpt_id") or "").strip()
        }
    shown_count = 0
    for item in (package.get("candidate_excerpts") or []):
        if not isinstance(item, dict):
            continue
        if not _verified_source_candidate_traceable(item):
            continue
        item_excerpt_id = str(item.get("excerpt_id") or "").strip()
        is_signal_row = bool(item_excerpt_id and item_excerpt_id in signal_excerpt_ids)
        if machine and not is_signal_row and not _mentions_machine(str(item.get("text") or ""), machine):
            continue
        if machine and not is_signal_row:
            searchable = " ".join(
                str(item.get(key) or "")
                for key in ("source_title", "text")
            )
            if _non_target_designation_codes(searchable, machine):
                continue
        shown_count += 1
        tier = _source_tier_number(item)
        tier_label = item.get("source_tier_label") or _source_tier_for_url(
            str(item.get("source_url") or ""),
            str(item.get("source_title") or ""),
        ).get("label")
        source_selection = _source_variant_selection_summary(item.get("source_variant_selection"))
        lines.extend([
            "",
            f"EXCERPT_ID: {item.get('excerpt_id')}",
            f"SOURCE_TITLE: {item.get('source_title')}",
            f"SOURCE_URL: {item.get('source_url')}",
            f"SOURCE_TIER: {tier} - {tier_label}",
            f"SOURCE_CAPTURE_METHOD: {item.get('source_capture_method') or 'legacy_unmarked'}",
            f"SOURCE_SELECTION: {source_selection or 'missing'}",
            f"ANTON_SLOT_HINTS: {', '.join(item.get('anton_slot_hints') or []) or 'none'}",
            f"EXCERPT_TEXT_HASH: {item.get('text_hash') or ''}",
            f"LOCATOR: {item.get('locator')}",
            f"EXACT_TEXT: {item.get('text')}",
        ])
        if shown_count >= 60:
            break
    return "\n".join(lines)[:32000]


def _verified_machine_source_queries(title: str, machine: str) -> list[str]:
    """Cost-bounded query set for one machine's exact raw-source package.

    G13, 2026-07-31: this set was fired byte-identical at every machine,
    including ships - "USAF fact sheet" / "National Museum of the United
    States Air Force" / "wingspan" queries against a Royal Navy battleship
    (confirmed in all 5 KGV-class packages on video d05efae3) return junk:
    huge unrelated USAF/DoD PDFs and Pacific Fleet rosters that happen to
    contain the ship's name once, in passing. Naval machines now get a
    naval-vocabulary query set instead (_verified_machine_naval_source_queries);
    non-naval machines keep this exact aircraft set unchanged (regression
    surface - see test_verified_machine_source_queries_aircraft_snapshot)."""
    if _is_naval_gather_context(title, machine):
        return _verified_machine_naval_source_queries(title, machine)
    manufacturer = " ".join(_unit_display_name(machine).split()[:1]).strip()
    return list(dict.fromkeys([
        f'"{machine}" official history',
        f'"{machine}" USAF fact sheet',
        f'"{machine}" National Museum of the United States Air Force',
        f'"{machine}" {manufacturer} development design history'.strip(),
        f'"{machine}" specifications range payload wingspan engines',
        f'"{machine}" production prototype built service operational history',
        f'"{machine}" design tradeoff limitation lessons learned test report',
        f'"{machine}" pilot crew memoir oral history official inquiry unusual fact',
    ]))[:8]


def _verified_machine_naval_source_queries(title: str, machine: str) -> list[str]:
    """Cost-bounded query set for one SHIP's exact raw-source package.

    Same 8-query shape and cost bound as the aircraft set, but with naval
    vocabulary (class/displacement/armament/beam/commissioned) and queries
    that EMBED the DVsU research simulator's proven fetchable naval/
    Commonwealth domains (tasks/evidence/dvsu-research-simulator/) - the
    pattern that landed a Tier-1 National Archives hit for HMS Ark Royal -
    instead of aircraft-only vocabulary ("USAF fact sheet", "wingspan") that
    naval sources never satisfy."""
    return list(dict.fromkeys([
        f'"{machine}" official history commissioned',
        f'"{machine}" class battleship displacement armament beam launched',
        f'"{machine}" naval-history.net',
        f'"{machine}" uboat.net',
        f'"{machine}" service history war record engagement',
        f'"{machine}" loss damage board of enquiry discovery.nationalarchives.gov.uk',
        f'"{machine}" commissioned decommissioned scrapped fate',
        f'"{machine}" crew veteran memoir account officer',
    ]))[:8]


# GAP 1(c), 2026-07-30: iwm.org.uk 403s every automated fetch attempted this
# week (curl, WebFetch - see the DVsU research simulator's
# gather_brief_template.txt) and never yields a usable candidate excerpt, so
# excluding it from every Tavily call stops it burning a search-result slot on
# a page nobody can ever read. These Commonwealth/naval institutions fetch
# cleanly and are the simulator's proven anchors for a ship-roster
# documentary whose best official museum (IWM) is unreachable by automation.
_BLOCKED_AUTOMATION_SOURCE_DOMAINS = ["iwm.org.uk", "www.iwm.org.uk"]
_PREFERRED_NAVAL_SOURCE_DOMAINS = [
    "awm.gov.au", "rmg.co.uk", "gov.uk",
    "naval-encyclopedia.com", "naval-history.net", "uboat.net",
]
# G13, 2026-07-31: one Tavily call covering all 6 preferred domains at once
# (max_results=5) diluted every domain's share of results - Duke of York and
# Anson got zero awm/rmg/gov.uk hits with no fetch errors, just not in the
# combined top 5. Splitting into small grouped calls gives each domain pair
# its own max_results=5 budget.
_NAVAL_STEERING_DOMAIN_GROUPS = [
    ["awm.gov.au", "rmg.co.uk"],
    ["gov.uk", "naval-encyclopedia.com"],
    ["naval-history.net", "uboat.net"],
]
# Cost bound for _gather_verified_machine_source_package's Tavily calls per
# machine: 8 base queries + len(_NAVAL_STEERING_DOMAIN_GROUPS) grouped
# steering calls (naval only) + at most 1 reworded retry pass = 12 for a
# naval machine today; this constant is the hard ceiling regardless of how
# either list grows later. Extra passes past the bound are skipped and
# logged (never silently dropped).
_MAX_VERIFIED_SOURCE_TAVILY_CALLS_PER_MACHINE = 15
_NAVAL_GATHER_CONTEXT_KEYWORDS = (
    "ship", "naval", "navy", "carrier", "cruiser", "destroyer", "frigate",
    "submarine", "vessel", "hms", "uss", "fleet", "corvette", "battleship",
    "battleships", "warship", "warships", "minesweeper", "aircraft carrier",
)


def _is_naval_gather_context(title: str, machine: str) -> bool:
    """True when this machine is plausibly a ship, so the extra domain-scoped
    Tavily call below is worth its cost. A tank or aircraft roster gets no
    benefit from naval-museum-only sources, so this keeps the added call
    scoped to where it actually helps."""
    text = f"{title or ''} {machine or ''}".lower()
    return any(re.search(rf'\b{re.escape(keyword)}\b', text) for keyword in _NAVAL_GATHER_CONTEXT_KEYWORDS)


def _naval_museum_domain_query(machine: str) -> str:
    """Steering-call query text, scoped per-group via include_domains to the
    DVsU research simulator's proven fetchable naval/Commonwealth anchors.
    Additive to _verified_machine_source_queries, whose query sets stay
    unchanged and regression-locked."""
    return f'"{machine}" history design service'


def _naval_reworded_retry_query(machine: str) -> str:
    """G13, 2026-07-31: one reworded, domain-unrestricted retry when the base
    + domain-grouped steering passes still leave zero Tier 1-2 candidates.
    Drops the include_domains restriction (it already found nothing) and
    rewords away from the base set's phrasing so a differently-indexed page
    can surface instead of repeating the same losing queries a third way."""
    return f"{machine} Royal Navy warship history museum archive record"


def _tier_floor_relevant_excerpt(text: str, machine: str) -> bool:
    """Stricter relevance check for the Tier 1-2 tier-floor gate only (does
    NOT replace the general _mentions_machine excerpt filter used elsewhere -
    that stays as-is to avoid starving the six-mentions/Anton-slot checks).

    A bare _mentions_machine hit is not proof a Tier 1-2 DOMAIN source is
    actually ABOUT this machine. Real evidence (video d05efae3, HMS Howe):
    the excerpt "Howe, Northwest Africa; ing, 'The War in the Mediterranean'"
    is a bibliography citation to a historian named Howe - it matches
    _mentions_machine on the surname alone, but names no ship, navy, or
    battle. (The other real case - an iwm.org.uk page actually about a
    different ship, "HMS Northampton", matching only on the generic "HMS"
    prefix - is already excluded upstream by _machine_mention_terms dropping
    generic naval prefixes, so _mentions_machine itself returns False for
    it.) For naval machines, require the excerpt to also carry naval
    ship-context vocabulary (_NAVAL_GATHER_CONTEXT_KEYWORDS) - genuine ship
    history/service content overwhelmingly does. Non-naval machines are
    unaffected (regression surface)."""
    if not _mentions_machine(text, machine):
        return False
    if not _is_naval_gather_context("", machine):
        return True
    normalized = _normalized_source_text(text)
    return any(
        re.search(rf'\b{re.escape(keyword)}\b', normalized)
        for keyword in _NAVAL_GATHER_CONTEXT_KEYWORDS
    )


def _validate_card_against_verified_sources(card: dict, package: Optional[dict]) -> list[str]:
    """Require each evidence source excerpt to be text fetched before the LLM call."""
    if not _verified_machine_source_package_ready(package):
        return ["missing verified raw internet source package"]
    candidates = [
        item for item in (package or {}).get("candidate_excerpts", [])
        if (
            isinstance(item, dict)
            and str(item.get("text") or "").strip()
            and _verified_source_candidate_traceable(item)
        )
    ]
    warnings: list[str] = []
    required_slot_sources: dict[str, list[tuple[str, int, str]]] = {}
    selected_excerpt_text_by_id: dict[str, str] = {}
    selected_source_tiers: dict[str, int] = {}
    machine = _unit_display_name(
        (card or {}).get("unit")
        or (card or {}).get("machine")
        or (card or {}).get("name")
        or (card or {}).get("designation")
        or (package or {}).get("machine")
        or ""
    )
    for segment in (card.get("evidence_segments") if isinstance(card, dict) else []) or []:
        if not isinstance(segment, dict):
            continue
        evidence_id = str(segment.get("evidence_id") or "?").strip()
        excerpt = _normalized_source_text(segment.get("source_excerpt") or "")
        source_url = str(segment.get("source_url") or "").strip()
        segment_locator = str(segment.get("locator") or "").strip()
        if not excerpt:
            continue
        if not source_url:
            warnings.append(f"evidence segment {evidence_id} missing verified source_url")
            continue
        if not segment_locator:
            warnings.append(f"evidence segment {evidence_id} missing verified locator")
            continue
        matched = False
        for candidate in candidates:
            candidate_text = _normalized_source_text(candidate.get("text") or "")
            candidate_url = str(candidate.get("source_url") or "").strip()
            candidate_locator = str(candidate.get("locator") or "").strip()
            candidate_excerpt_id = str(candidate.get("excerpt_id") or "").strip()
            segment_excerpt_id = str(segment.get("source_excerpt_id") or segment.get("excerpt_id") or "").strip()
            url_matches = candidate_url == source_url
            locator_matches = (
                segment_locator == candidate_locator
                or segment_locator == candidate_excerpt_id
                or bool(candidate_locator and candidate_locator.startswith(f"{segment_locator};"))
            )
            if url_matches and locator_matches and excerpt in candidate_text:
                if segment_excerpt_id and candidate_excerpt_id and segment_excerpt_id != candidate_excerpt_id:
                    warnings.append(
                        f"evidence segment {evidence_id} source_excerpt_id {segment_excerpt_id} does not match verified excerpt {candidate_excerpt_id}"
                    )
                    break
                if candidate_excerpt_id:
                    segment["source_excerpt_id"] = candidate_excerpt_id
                if candidate.get("source_id"):
                    segment["source_id"] = candidate.get("source_id")
                if candidate.get("text_hash"):
                    segment["source_excerpt_hash"] = candidate.get("text_hash")
                tier = _source_tier_number(candidate)
                if tier:
                    segment["source_tier"] = tier
                    segment["source_tier_label"] = candidate.get("source_tier_label") or _source_tier_for_url(
                        candidate_url,
                        str(candidate.get("source_title") or ""),
                    ).get("label")
                if candidate.get("source_capture_method"):
                    segment["source_capture_method"] = candidate.get("source_capture_method")
                if isinstance(candidate.get("source_variant_selection"), dict):
                    segment["source_variant_selection"] = candidate.get("source_variant_selection")
                matched = True
                selected_source_tiers[evidence_id] = _source_tier_number(candidate)
                role = _anton_slot_role_for_kind(str(segment.get("kind") or ""))
                if role in _ANTON_REQUIRED_SLOT_ROLES:
                    candidate_hints = {
                        str(hint or "").strip()
                        for hint in (candidate.get("anton_slot_hints") or [])
                        if str(hint or "").strip()
                    }
                    if candidate_hints and role not in candidate_hints:
                        warnings.append(
                            f"evidence segment {evidence_id} maps {role} to raw excerpt "
                            f"{candidate_excerpt_id or candidate_locator} hinted for "
                            + ", ".join(sorted(candidate_hints))
                        )
                    excerpt_identity = candidate_excerpt_id or candidate_locator
                    if excerpt_identity:
                        selected_excerpt_text_by_id[excerpt_identity] = candidate_text
                    required_slot_sources.setdefault(role, []).append((
                        evidence_id,
                        _source_tier_number(candidate),
                        excerpt_identity,
                    ))
                break
        if not matched:
            warnings.append(
                f"evidence segment {evidence_id} source_excerpt/locator was not found in verified fetched source text"
            )
    for role, source_rows in required_slot_sources.items():
        if source_rows and all(tier >= 4 for _evidence_id, tier, _excerpt_id in source_rows):
            evidence_ids = ", ".join(evidence_id for evidence_id, _tier, _excerpt_id in source_rows)
            # G14, 2026-07-31: tier floor demoted to advisory - see the note
            # on _verified_machine_source_package_quality_errors.
            warnings.append(
                _ADVISORY_PREFIX + "[caution_only_sources_advisory] "
                f"required Anton slot {role} uses only Tier 4/caution sources: {evidence_ids}"
            )
    required_slots = [
        role for role, _accepted_kinds, _job in _ANTON_SLOT_SPECS
        if role in _ANTON_REQUIRED_SLOT_ROLES
    ]
    if all(required_slot_sources.get(role) for role in required_slots):
        selected_excerpts_by_slot = {
            role: [
                excerpt_id for _evidence_id, _tier, excerpt_id in required_slot_sources.get(role, [])
                if excerpt_id
            ]
            for role in required_slots
        }
        distinct_assignment = _distinct_anton_slot_assignment(
            selected_excerpts_by_slot,
            required_slots,
            selected_excerpt_text_by_id,
            machine,
        )
        if len(distinct_assignment) < len(required_slots):
            warnings.append(
                "research card must select distinct raw source excerpts for required Anton slots: "
                + ", ".join(required_slots)
            )
    # G14, 2026-07-31 (Ryan's ruling, decisions.md): tier floor demoted to
    # advisory - card writing/passing no longer requires a Tier 1-2 source.
    # See the matching note on _verified_machine_source_package_quality_errors.
    if selected_source_tiers and all(tier > 2 for tier in selected_source_tiers.values()):
        warnings.append(
            _ADVISORY_PREFIX + "[tier_floor_advisory] "
            "research card evidence needs at least one selected Tier 1-2 primary/authoritative source"
        )
    for field_name, label in (
        ("timeframe_evidence_ids", "timeframe"),
        ("visual_identity_evidence_ids", "visual_identity"),
    ):
        evidence_ids = [
            str(item).strip()
            for item in ((card or {}).get(field_name) if isinstance((card or {}).get(field_name), list) else [])
            if str(item).strip()
        ]
        matched_tiers = [selected_source_tiers[item] for item in evidence_ids if item in selected_source_tiers]
        if matched_tiers and all(tier >= 4 for tier in matched_tiers):
            warnings.append(
                _ADVISORY_PREFIX + "[caution_only_sources_advisory] "
                f"{label} uses only Tier 4/caution sources: " + ", ".join(evidence_ids)
            )
    rationale = " ".join(str((card or {}).get("why_this_unit_deserves_a_paragraph") or "").split())
    if rationale:
        rationale_for_numbers = rationale
        for designation in re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", machine.upper()):
            rationale_for_numbers = re.sub(
                rf"\b{re.escape(designation)}(?:s)?\b",
                "",
                rationale_for_numbers,
                flags=re.IGNORECASE,
            )
        rationale_numbers = _numeric_mentions_from_text(rationale_for_numbers)
        evidence_segments = (card.get("evidence_segments") if isinstance(card, dict) else []) or []
        allowed_number_keys = {
            _numeric_token_key(token)
            for segment in evidence_segments
            if isinstance(segment, dict)
            for token in (
                list(segment.get("numeric_tokens") if isinstance(segment.get("numeric_tokens"), list) else [])
                + _numeric_tokens_from_text(segment.get("source_excerpt") or "")
            )
        }
        unsupported_numbers = [
            mention["raw"] for mention in rationale_numbers
            if mention["key"] not in allowed_number_keys
        ]
        if unsupported_numbers:
            warnings.append(
                "why_this_unit_deserves_a_paragraph introduced unsupported numerical detail(s): "
                + ", ".join(unsupported_numbers)
            )

        # G2 fix: a class-style machine name often carries its own bracketed
        # pennant ("HMS Illustrious (D48) ... class"). _unit_code has no
        # hyphenated designation to latch onto for these names, so it falls
        # back to a 4-token glob that concatenates the WHOLE name into one
        # blob code ("HMSILLUSTRIOUSD48ILLUSTRIOUS...") - "D48" alone is a
        # substring of that blob but never equals it, so a SET membership
        # check against {_normalized_unit_code(machine)} alone always missed
        # it and flagged the machine's own pennant as an "unsupported
        # designation" inside why_this_unit_deserves_a_paragraph. Reuse the
        # same designation scan already applied to `machine` two lines above
        # (for the numeric check) so every embedded designation token, not
        # just the single collapsed code, is allowed.
        allowed_designations = {_normalized_unit_code(machine)}
        allowed_designations.update(
            _normalized_unit_code(designation)
            for designation in re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", machine.upper())
        )
        evidence_text = " ".join(
            f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
            for segment in evidence_segments
            if isinstance(segment, dict)
        )
        allowed_designations.update(
            _normalized_unit_code(token)
            for token in re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", evidence_text.upper())
        )
        rationale_designations = {
            _normalized_unit_code(token)
            for token in re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", rationale.upper())
        }
        unsupported_designations = sorted(
            token for token in rationale_designations
            if token and token not in allowed_designations
        )
        if unsupported_designations:
            warnings.append(
                "why_this_unit_deserves_a_paragraph introduced unsupported designation(s): "
                + ", ".join(unsupported_designations)
            )
    return warnings


def _clamp_card_excerpts_to_verified_sources(card: dict, package: Optional[dict]) -> dict:
    """Replace model-trimmed excerpts with the exact verified candidate row."""
    if not isinstance(card, dict) or not _verified_machine_source_package_ready(package):
        return card
    candidates = [
        item for item in (package or {}).get("candidate_excerpts", [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    if not candidates:
        return card
    by_locator = {
        str(candidate.get("locator") or candidate.get("excerpt_id") or "").strip(): candidate
        for candidate in candidates
    }
    for segment in card.get("evidence_segments") or []:
        if not isinstance(segment, dict):
            continue
        locator = str(segment.get("locator") or "").strip()
        source_url = str(segment.get("source_url") or "").strip()
        candidate = by_locator.get(locator)
        if candidate is None and locator:
            candidate = next(
                (
                    item for item in candidates
                    if str(item.get("excerpt_id") or "").strip() in locator
                    and (not source_url or str(item.get("source_url") or "").strip() == source_url)
                ),
                None,
            )
        if candidate is None:
            continue
        segment["source_excerpt"] = str(candidate.get("text") or "").strip()
        segment["source_url"] = str(candidate.get("source_url") or segment.get("source_url") or "").strip()
        segment["source_title"] = str(candidate.get("source_title") or segment.get("source_title") or "").strip()
        segment["locator"] = str(candidate.get("locator") or locator).strip()
    return card


def _stamp_card_segment_provenance(card: Any, package: Optional[dict]) -> Any:
    """Apply verified-source provenance to the REAL card's segments before save.

    The referee is pure (it grades a deep copy), so the incidental segment
    enrichment inside _validate_card_against_verified_sources (source_tier,
    source_id, source_excerpt_id, source_excerpt_hash, source_tier_label,
    source_capture_method, source_variant_selection) lands on the discarded
    copy. Every save path must re-apply it to the card that is actually
    persisted, or saved cards lose provenance (null tier/capture in the script
    brief, vanished audit hashes). Warnings are discarded here on purpose -
    grading stays the referee's job."""
    if isinstance(card, dict) and isinstance(card.get("evidence_segments"), list):
        _validate_card_against_verified_sources(card, package)
    return card


def _inventory_story_brief(payload: dict, machine: str) -> dict:
    """Compact source-addressable evidence summary for review artifacts."""

    card = _research_card_for_machine(payload, machine) or {}
    evidence, _errors = _normalize_machine_evidence(card, machine)

    slot_rows = []
    for segment in evidence:
        role = segment.get("slot_role") or _anton_slot_role_for_kind(segment.get("kind"))
        if not role:
            continue
        slot_rows.append({
            "slot": role,
            "evidence_id": segment.get("evidence_id"),
            "claim": segment.get("claim"),
            "source_excerpt": segment.get("source_excerpt"),
            "source_url": segment.get("source_url"),
            "locator": segment.get("locator"),
            "source_tier": segment.get("source_tier"),
            "source_capture_method": segment.get("source_capture_method"),
        })

    def first_claim(*roles: str) -> str:
        for role in roles:
            for row in slot_rows:
                if row.get("slot") == role:
                    return " ".join(str(row.get("claim") or "").split())
        return ""

    return {
        "machine": machine,
        "source_contract": "evidence_rows_only",
        "core_tension": first_claim("original_problem", "tradeoff"),
        "actual_outcome": first_claim("reality"),
        "historical_significance": first_claim("memorable_fact", "role_category", "reality"),
        "anton_slots": slot_rows,
        "onscreen_label": first_claim("onscreen_label"),
        "editorial_rule": (
            "Use Anton slots as candidate ingredients, not a checklist. Build one micro-story from problem, engineering decision, tradeoff, reality, then a paragraph-derived conclusion."
        ),
    }


_NUMBER_TOKEN_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "sixty": "60",
    "seventy": "70",
    "eighty": "80",
    "ninety": "90",
}


_NUMBER_SCALE_WORDS = {
    "hundred": 100,
    "thousand": 1000,
    "million": 1000000,
}


_INDEFINITE_NUMBER_SCALE_WORDS = {"hundreds", "thousands", "millions"}
_NUMBER_WORD_VOCABULARY = set(_NUMBER_TOKEN_WORDS) | set(_NUMBER_SCALE_WORDS) | _INDEFINITE_NUMBER_SCALE_WORDS | {"and"}
_NUMERIC_DIGIT_PATTERN = r"(?<![A-Za-z0-9])\d+(?:[,.]\d+)*(?:%|st|nd|rd|th|s)?(?![A-Za-z0-9])"
_VOICEOVER_UNIT_ABBREVIATIONS = {
    "ft": "foot or feet",
    "hp": "horsepower",
    "kg": "kilograms",
    "km": "kilometers",
    "kt": "knots",
    "kts": "knots",
    "lb": "pounds",
    "lbs": "pounds",
    "mi": "miles",
    "mph": "miles per hour",
    "rpm": "revolutions per minute",
}


def _parse_number_word_phrase(tokens: list[str]) -> Optional[int]:
    """Return a numeric value for precise spoken number phrases."""
    cleaned = [token for token in tokens if token and token != "and"]
    if not cleaned or any(token in _INDEFINITE_NUMBER_SCALE_WORDS for token in cleaned):
        return None

    values = [int(_NUMBER_TOKEN_WORDS[token]) for token in cleaned if token in _NUMBER_TOKEN_WORDS]
    if (
        len(values) in {2, 3}
        and len(values) == len(cleaned)
        and 10 <= values[0] <= 99
        and 20 <= values[1] <= 90
        and values[1] % 10 == 0
    ):
        # Handles spoken years such as "nineteen thirty three" -> 1933.
        return values[0] * 100 + sum(values[1:])

    total = 0
    current = 0
    seen = False
    for token in cleaned:
        if token in _NUMBER_TOKEN_WORDS:
            current += int(_NUMBER_TOKEN_WORDS[token])
            seen = True
            continue
        scale = _NUMBER_SCALE_WORDS.get(token)
        if scale is None:
            return None
        seen = True
        if scale == 100:
            current = max(current, 1) * scale
        else:
            total += max(current, 1) * scale
            current = 0
    return total + current if seen else None


def _numeric_token_key(token: Any) -> str:
    """Canonicalize equivalent numeric spellings without weakening support checks."""
    raw = str(token or "").strip().lower()
    word_tokens = re.findall(r"\b[a-z]+\b", raw.replace("-", " "))
    if word_tokens and all(token in _NUMBER_WORD_VOCABULARY for token in word_tokens):
        parsed = _parse_number_word_phrase(word_tokens)
        if parsed is not None:
            return str(parsed)
        return " ".join(word_tokens)
    cleaned = raw.replace(",", "")
    cleaned = re.sub(r"(?<=\d)(?:st|nd|rd|th)$", "", cleaned)
    return cleaned


def _numeric_mentions_from_text(text: str) -> list[dict[str, str]]:
    """Extract numeric mentions with raw text and a canonical comparison key."""
    lower = str(text or "").lower()
    mentions = [
        {"raw": token, "key": _numeric_token_key(token)}
        for token in re.findall(_NUMERIC_DIGIT_PATTERN, lower)
    ]
    tokens = re.findall(r"\b[a-z]+\b", lower.replace("-", " "))
    number_terms = set(_NUMBER_TOKEN_WORDS) | set(_NUMBER_SCALE_WORDS) | _INDEFINITE_NUMBER_SCALE_WORDS
    i = 0
    while i < len(tokens):
        if tokens[i] not in number_terms:
            i += 1
            continue
        phrase = [tokens[i]]
        j = i + 1
        while j < len(tokens):
            token = tokens[j]
            if token in number_terms:
                phrase.append(token)
                j += 1
                continue
            if token == "and" and j + 1 < len(tokens) and tokens[j + 1] in number_terms:
                phrase.append(token)
                j += 1
                continue
            break
        raw = " ".join(phrase)
        mentions.append({"raw": raw, "key": _numeric_token_key(raw)})
        i = j
    return mentions


def _numeric_tokens_from_text(text: str) -> list[str]:
    return [mention["raw"] for mention in _numeric_mentions_from_text(text)]


def _strip_designations_for_numbers(text: str, machine: str = "") -> str:
    """LAW (2026-07-16): designations are IDENTIFIERS, never numbers.

    Remove the locked machine's designation tokens and any designation-shaped
    token (XB-15, B-52, F-86D) before extracting numeric mentions, so a
    designation's digits are never graded as numbers needing spelling, source
    support, or hedges. XB-15's live preview flagged "15" from its own
    designation, and the hedge instruction then produced "XB-about 15".
    Foreign designations stay policed by the dedicated unsupported-designation
    check - this scrub only keeps them out of the NUMBER checks."""
    scrubbed = str(text or "")
    for designation in re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", str(machine or "").upper()):
        scrubbed = re.sub(rf"\b{re.escape(designation)}(?:s)?\b", " ", scrubbed, flags=re.IGNORECASE)
    return _AIRCRAFT_DESIGNATION_RE.sub(" ", scrubbed)


def _raw_digit_mentions_for_voiceover(text: str) -> list[str]:
    """Find digits that should be spoken words in DVsU narration.

    QL-10/QL-11 (OR-4 approved): digits are LEGAL for alphanumeric
    designations, calendar years, and exact figures of four or more digits
    (casualty tolls like 1,177, costs, hull numbers). Everything smaller (30
    knots, 87) is a spoken measure and must be spelled."""
    scrubbed = str(text or "")
    designation_pattern = (
        r"\b(?:"
        r"XB|YB|B|FB|F|MiG|Su|Tu|Il|La|Yak|Fw|Me|Ju|He|Do|A|C|KC|P|SR|U|"
        r"UH|AH|CH|OH|J|R|TF|BB|CV|CVN|DD|DDG|SS|SSN"
        r")-?\d{1,4}[A-Z]?\b"
    )
    scrubbed = re.sub(designation_pattern, " ", scrubbed, flags=re.IGNORECASE)
    # LAW (2026-07-16): digits inside ANY designation-shaped token are legal
    # and expected voiceover ("XB-15" is spoken as a name), never raw numerals.
    scrubbed = _AIRCRAFT_DESIGNATION_RE.sub(" ", scrubbed)
    mentions: list[str] = []
    for match in re.finditer(_NUMERIC_DIGIT_PATTERN, scrubbed):
        token = match.group(0)
        try:
            value = float(token.rstrip("%sthndr").replace(",", ""))
        except (TypeError, ValueError):
            value = 0.0
        # Years and exact 4+ digit figures stay digits by law.
        if value >= 1000:
            continue
        mentions.append(token)
    return list(dict.fromkeys(mentions))


def _written_unit_abbreviations_for_voiceover(text: str) -> list[str]:
    """Find unit abbreviations that should be expanded for clean narration."""
    pattern = r"(?<![A-Za-z0-9])(?:ft|hp|kg|km|kts?|lbs?|mi|mph|rpm)\.?(?![A-Za-z0-9])"
    return list(dict.fromkeys(match.group(0).rstrip(".").lower() for match in re.finditer(pattern, str(text or ""), flags=re.IGNORECASE)))


def _unit_word_variants_from_evidence(text: str) -> set[str]:
    """Allow common spoken unit expansions only when the source uses that unit."""
    lower = str(text or "").lower()
    variants: set[str] = set()
    if re.search(r"\bmi\b", lower):
        variants.update({"mile", "miles"})
    if re.search(r"\bmph\b", lower):
        variants.update({"mile", "miles", "per", "hour"})
    if re.search(r"\bft\b", lower):
        variants.update({"foot", "feet"})
    if re.search(r"\bkm\b", lower):
        variants.update({"kilometer", "kilometers"})
    if re.search(r"\blbs?\b", lower):
        variants.update({"pound", "pounds"})
    if re.search(r"\bkg\b", lower):
        variants.update({"kilogram", "kilograms"})
    if re.search(r"\bhp\b", lower):
        variants.update({"horsepower"})
    if re.search(r"\brpm\b", lower):
        variants.update({"revolution", "revolutions", "per", "minute"})
    if re.search(r"\bkts?\b", lower):
        variants.update({"knot", "knots"})
    return variants


def _grounding_stem(token: str) -> str:
    for suffix in ("ingly", "edly", "ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[:-len(suffix)]
    return token


def _ungrounded_factual_words(text: str, evidence_text: str, machine: str, *, extra_stopwords: Optional[set[str]] = None) -> list[str]:
    """Return non-glue words in text that are not supported by selected evidence."""
    import re

    stopwords = {
        "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "can", "could", "did", "do",
        "does", "for", "from", "had", "has", "have", "having", "if", "in", "into", "is", "it", "its", "made",
        "make", "more", "not", "of", "on", "only", "or", "own", "so", "than", "that", "the", "their", "then",
        "there", "these", "this", "those", "through", "to", "was", "were", "which", "while", "with", "without",
        "would", "yet",
        # Connector and compression words are allowed; nouns, design claims,
        # specs, places, and outcomes still need to appear in the evidence.
        "about", "across", "after", "against", "around", "before", "behind", "between", "beyond", "during",
        "inside", "less", "rather", "same", "together",
        "choice", "choices", "claim", "clear", "decision", "engineering", "grounded", "machine", "matter",
        "mattered", "service", "source", "supplied",
    } | _NUMBER_WORD_VOCABULARY | _unit_word_variants_from_evidence(evidence_text)
    if extra_stopwords:
        stopwords |= extra_stopwords

    evidence_vocab = {_grounding_stem(token) for token in re.findall(r"[a-z]+", evidence_text.lower())}
    machine_vocab = {_grounding_stem(token) for token in re.findall(r"[a-z]+", machine.lower())}

    def _grounded(stem: str) -> bool:
        if stem in evidence_vocab or stem in machine_vocab:
            return True
        return len(stem) >= 5 and any(
            len(candidate) >= 5 and (candidate.startswith(stem) or stem.startswith(candidate))
            for candidate in evidence_vocab
        )

    ungrounded: list[str] = []
    seen: set[str] = set()
    for raw_token in re.findall(r"[a-z]+", str(text or "").lower()):
        stem = _grounding_stem(raw_token)
        if raw_token in stopwords or stem in stopwords or _grounded(stem):
            continue
        if raw_token not in seen:
            ungrounded.append(raw_token)
            seen.add(raw_token)
    return ungrounded


def _normalize_machine_evidence(card: dict, machine: str) -> tuple[list[dict], list[str]]:
    """Validate atomic, source-addressable evidence for one locked machine."""
    import re

    raw_segments = card.get("evidence_segments") if isinstance(card, dict) else None
    if not isinstance(raw_segments, list) or not raw_segments:
        return [], ["missing evidence_segments; schema-v3 source-addressable research is required"]
    normalized: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_segments, start=1):
        if not isinstance(raw, dict):
            errors.append(f"evidence segment {index} is not an object")
            continue
        evidence_id = str(raw.get("evidence_id") or "").strip()
        kind = str(raw.get("kind") or "").strip().lower()
        slot_role = _anton_slot_role_for_kind(kind)
        if slot_role == "reality" and kind in {"historical_meaning", "legacy"}:
            kind = "reality"
            slot_role = "reality"
        claim = " ".join(str(raw.get("claim") or "").split())
        excerpt = " ".join(str(raw.get("source_excerpt") or "").split())
        source_url = str(raw.get("source_url") or "").strip()
        locator = str(raw.get("locator") or "").strip()
        if not evidence_id:
            errors.append(f"evidence segment {index} missing evidence_id")
        elif evidence_id in seen:
            errors.append(f"duplicate evidence_id {evidence_id}")
        seen.add(evidence_id)
        if not kind or not claim:
            errors.append(f"evidence segment {evidence_id or index} missing kind or atomic claim")
        elif slot_role is None:
            errors.append(f"evidence segment {evidence_id or index} has unsupported Anton slot kind: {kind}")
        elif slot_role == "human_detail" and not _human_detail_has_attribution(
            " ".join([claim, excerpt])
        ):
            errors.append(
                f"evidence segment {evidence_id or index} human_detail must name a person or cite an official finding"
            )
        if not excerpt:
            errors.append(f"evidence segment {evidence_id or index} missing source_excerpt")
        if not source_url and not locator:
            errors.append(f"evidence segment {evidence_id or index} missing source_url/locator")
        numbers = raw.get("numeric_tokens")
        if not isinstance(numbers, list):
            numbers = re.findall(_NUMERIC_DIGIT_PATTERN, claim.lower())
        normalized_numbers = [str(token).strip().lower() for token in numbers if str(token).strip()]

        grounding_stopwords = {
            "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "could", "did", "do",
            "for", "from", "had", "has", "have", "in", "into", "is", "it", "its", "made", "more", "not", "of",
            "on", "only", "or", "than", "that", "the", "their", "then", "through", "to", "was", "were", "which",
            "while", "with", "without", "would", "yet",
        } | _NUMBER_WORD_VOCABULARY | _unit_word_variants_from_evidence(excerpt)

        excerpt_vocab = {_grounding_stem(token) for token in re.findall(r"[a-z]+", excerpt.lower())}
        machine_vocab = {_grounding_stem(token) for token in re.findall(r"[a-z]+", machine.lower())}

        def _grounded_word(stem: str) -> bool:
            if stem in excerpt_vocab or stem in machine_vocab:
                return True
            return len(stem) >= 5 and any(
                len(candidate) >= 5 and (candidate.startswith(stem) or stem.startswith(candidate))
                for candidate in excerpt_vocab
            )

        ungrounded_words = sorted({
            stem
            for raw_token in re.findall(r"[a-z]+", claim.lower())
            for stem in [_grounding_stem(raw_token)]
            if raw_token not in grounding_stopwords and not _grounded_word(stem)
        })
        if ungrounded_words:
            # The claim is an internal compression of the fetched excerpt. If
            # the model adds unsourced wording there, clamp it back to the
            # exact excerpt instead of letting a restatement become evidence.
            claim = excerpt
            excerpt_for_numbers = excerpt
            for designation in re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", machine.upper()):
                excerpt_for_numbers = re.sub(
                    rf"\b{re.escape(designation)}(?:s)?\b",
                    "",
                    excerpt_for_numbers,
                    flags=re.IGNORECASE,
                )
            normalized_numbers = list(dict.fromkeys(
                normalized_numbers + [
                    token for token in _numeric_tokens_from_text(excerpt_for_numbers)
                    if _numeric_token_key(token)
                ]
            ))
        designation_tokens = set(re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", machine.upper()))
        numeric_claim = claim
        numeric_excerpt = excerpt
        for designation in designation_tokens:
            numeric_claim = re.sub(rf"\b{re.escape(designation)}(?:s)?\b", "", numeric_claim, flags=re.IGNORECASE)
            numeric_excerpt = re.sub(rf"\b{re.escape(designation)}(?:s)?\b", "", numeric_excerpt, flags=re.IGNORECASE)
        claim_numbers = _numeric_tokens_from_text(numeric_claim)
        excerpt_numbers = _numeric_tokens_from_text(numeric_excerpt)
        excerpt_number_keys = {_numeric_token_key(token) for token in excerpt_numbers}
        claim_number_keys = {_numeric_token_key(token) for token in claim_numbers}
        source_number_keys = claim_number_keys | excerpt_number_keys
        # numeric_tokens is validation metadata, not creative research prose.
        # Models often include aircraft designations like XB-19 or XBLR-2 here,
        # which are not numeric support tokens. Keep only model tokens that map
        # to actual numbers in the claim/excerpt, then deterministically add the
        # numbers found in the exact sourced text.
        normalized_numbers = list(dict.fromkeys(
            [
                token for token in normalized_numbers
                if _numeric_token_key(token) in source_number_keys
            ]
            + claim_numbers
            + excerpt_numbers
        ))
        normalized_number_keys = {_numeric_token_key(token) for token in normalized_numbers}
        missing_number_support = [token for token in claim_numbers if _numeric_token_key(token) not in excerpt_number_keys]
        undeclared_numbers = [token for token in claim_numbers if _numeric_token_key(token) not in normalized_number_keys]
        if undeclared_numbers and not missing_number_support:
            normalized_numbers = list(dict.fromkeys(normalized_numbers + undeclared_numbers))
            normalized_number_keys = {_numeric_token_key(token) for token in normalized_numbers}
            undeclared_numbers = [token for token in claim_numbers if _numeric_token_key(token) not in normalized_number_keys]
        invented_numeric_tokens = [
            token
            for token in normalized_numbers
            if _numeric_token_key(token) not in (claim_number_keys | excerpt_number_keys)
        ]
        if missing_number_support:
            errors.append(f"evidence segment {evidence_id or index} claim numbers absent from source_excerpt: {', '.join(missing_number_support)}")
        if undeclared_numbers:
            errors.append(f"evidence segment {evidence_id or index} claim numbers missing from numeric_tokens: {', '.join(undeclared_numbers)}")
        if invented_numeric_tokens:
            errors.append(f"evidence segment {evidence_id or index} numeric_tokens absent from claim/excerpt: {', '.join(invented_numeric_tokens)}")

        normalized_segment = {
            "evidence_id": evidence_id,
            "kind": kind,
            "slot_role": slot_role,
            "claim": claim,
            "source_excerpt": excerpt,
            "source_url": source_url,
            "source_title": str(raw.get("source_title") or "").strip(),
            "locator": locator,
            "numeric_tokens": normalized_numbers,
            "confidence": str(raw.get("confidence") or "").strip().lower() or "unknown",
        }
        for source_identity_field in (
            "source_excerpt_id",
            "excerpt_id",
            "source_id",
            "source_excerpt_hash",
            "source_tier_label",
            "source_capture_method",
        ):
            value = str(raw.get(source_identity_field) or "").strip()
            if value:
                normalized_segment[source_identity_field] = value
        if isinstance(raw.get("source_variant_selection"), dict):
            normalized_segment["source_variant_selection"] = raw.get("source_variant_selection")
        if "source_excerpt_id" not in normalized_segment and normalized_segment.get("excerpt_id"):
            normalized_segment["source_excerpt_id"] = normalized_segment["excerpt_id"]
        try:
            source_tier = int(raw.get("source_tier") or raw.get("tier") or 0)
        except (TypeError, ValueError):
            source_tier = 0
        if source_tier:
            normalized_segment["source_tier"] = source_tier
        normalized.append(normalized_segment)
    return normalized, list(dict.fromkeys(errors))


def _dvsu_mode_profile(payload: dict, card: Optional[dict] = None) -> dict:
    """OR-5 (approved): 'Most Hated' crew-testimony is a distinct named mode.

    The mode exists as a flag with its register / opener-budget /
    memorable-source overrides recorded in the format contract; the full
    crew-testimony build is a later phase. Default = the spec-block mode."""
    raw_mode = str(
        (card or {}).get("dvsu_mode")
        or (payload or {}).get("dvsu_mode")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")
    if raw_mode in {"most_hated", "crew_testimony", "crew_hate"}:
        return {
            "mode": "most_hated",
            "register": "long_form",
            # QL-7 crew variant: near-zero bare name-openers.
            "opener_name_budget": 0.2,
            # QL-9 crew variant: testimony is the memorable-fact source.
            "memorable_source": "crew_testimony",
        }
    return {
        "mode": "spec_block",
        "register": _DVSU_DEFAULT_REGISTER,
        "opener_name_budget": 0.6,
        "memorable_source": "sticky_fact",
    }


def _dvsu_mode_value_for_video(video: dict) -> Optional[str]:
    """Checklist C46e: the VIDEO-level ``dvsu_mode`` opt-in flag (never
    inferred from the title — see ``_dvsu_mode_profile``'s own docstring),
    read straight off ``research_payload`` so ``_load_dvsu_rule_overrides``
    can scope-match a ``{"dvsu_mode": "..."}`` quality_rules row against
    THIS video, once per script-hold run (not per machine — a per-machine
    card override, when present, is still honored later by
    ``_dvsu_mode_profile`` itself at paragraph-build time)."""
    import json as _json_mv

    if not isinstance(video, dict):
        return None
    payload = video.get("research_payload") or {}
    if isinstance(payload, str):
        try:
            payload = _json_mv.loads(payload)
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, dict):
        return None
    raw_mode = str(payload.get("dvsu_mode") or "").strip().lower().replace("-", "_").replace(" ", "_")
    return raw_mode or None


def _bare_tag_is_valid(card: dict) -> bool:
    """B2 (2026-07-16): the deliberately_bare tag is honored ONLY with a
    non-trivial gap_hunt_summary (what was searched, why no use-story exists).
    A bare tag without hunt evidence is a hard warning, never an exemption."""
    if not isinstance(card, dict) or card.get("deliberately_bare") is not True:
        return False
    return _spoken_word_count(str(card.get("gap_hunt_summary") or "")) >= 8


def _card_is_deliberately_bare(card: dict, narrative_weight: Optional[dict] = None) -> bool:
    """QL-3/QL-9 exemption: the deliberately-bare tag.

    The explicit card tag counts only with hunt evidence (B2); a transitional
    narrative weight (bare loser-prototype / connective entries) counts as the
    tag at the script stage, matching the six legitimately bare corpus entries."""
    if _bare_tag_is_valid(card):
        return True
    label = str((narrative_weight or {}).get("label") or "").strip().lower()
    return label == "transitional"


def _machine_story_plan(payload: dict, machine: str, dvsu_rule_overrides: Optional[dict] = None) -> dict:
    """Compile source-addressable evidence into Anton-style paragraph slots.

    ``dvsu_rule_overrides`` (checklist C46e, OR-5 ruled) is the tenant's
    resolved ``quality_rules.resolve_dvsu_overrides()`` result
    (``PipelineExecutor._load_dvsu_rule_overrides``) — when the video's mode
    is "most_hated" AND a seeded QL-7-MH/QL-9-MH row resolved an
    opener_budget/memorable_source override, that TABLE value wins over the
    hardcoded ``_dvsu_mode_profile`` default; absent overrides (every tenant
    before the seed script runs, or a non-Most-Hated video) leave
    mode_profile byte-identical to before this chunk."""
    card = _research_card_for_machine(payload, machine) or {}
    evidence, evidence_errors = _normalize_machine_evidence(card, machine)
    mode_profile = _dvsu_mode_profile(payload, card)
    if mode_profile.get("mode") == "most_hated" and dvsu_rule_overrides:
        opener_override = dvsu_rule_overrides.get("opener_budget") or {}
        if opener_override.get("value") is not None:
            mode_profile["opener_name_budget"] = opener_override["value"]
        memorable_override = dvsu_rule_overrides.get("memorable_source") or {}
        if memorable_override.get("value"):
            mode_profile["memorable_source"] = memorable_override["value"]
    narrative_weight = _anton_narrative_weight_profile(card, evidence, register=mode_profile["register"])
    # LAW (2026-07-16): the timeframe/visual_identity SUPPORT slots carry the
    # union of (segments with the matching support kind) AND (segments the
    # card's *_evidence_ids cite, whatever their kind), deduplicated. Leaving
    # cited support evidence out of the plan starved the two-source scan:
    # XB-15's year had a second locked source that never reached plan evidence.
    card_field_citations = {
        field_role: [
            str(item).strip()
            for item in (card.get(field_key) if isinstance(card.get(field_key), list) else [])
            if str(item).strip()
        ]
        for field_role, field_key in (
            ("timeframe", "timeframe_evidence_ids"),
            ("visual_identity", "visual_identity_evidence_ids"),
        )
    }
    segments_by_id = {
        str(item.get("evidence_id") or ""): item
        for item in evidence
        if str(item.get("evidence_id") or "")
    }
    slots = []
    seen_ids: set[str] = set()
    for role, accepted_kinds, job in _ANTON_SLOT_SPECS:
        segments = [
            item for item in evidence
            if item.get("kind") in accepted_kinds and item.get("evidence_id") not in seen_ids
        ]
        for cited_id in card_field_citations.get(role, ()):
            if any(str(item.get("evidence_id") or "") == cited_id for item in segments):
                continue
            cited_segment = segments_by_id.get(cited_id)
            if cited_segment is not None:
                segments.append(cited_segment)
        if segments:
            seen_ids.update(str(item.get("evidence_id") or "") for item in segments)
        slots.append({
            "slot": role,
            "required": role in _ANTON_REQUIRED_SLOT_ROLES,
            "evidence_ids": [segment["evidence_id"] for segment in segments],
            "evidence_segments": segments,
            "paragraph_job": job,
        })
    # First write wins: a segment shared between a narrative slot and a support
    # slot keeps its narrative role for formula-order attribution.
    role_by_id: dict[str, str] = {}
    for slot in slots:
        for segment in slot.get("evidence_segments", []):
            evidence_id = segment.get("evidence_id")
            if evidence_id:
                role_by_id.setdefault(evidence_id, slot["slot"])
    # Writer pass 5 (2026-07-16): the plan flags which evidence carries the
    # documented role conversion so the distiller can never write an
    # acceptance/testing event as reality while the twist sits unused (XB-15
    # wrote Wright Field acceptance and skipped the transport story).
    conversion_signal_evidence_ids = _conversion_signal_evidence_ids(
        evidence,
        _verified_source_package_for_machine(payload, machine),
        machine,
    )
    if conversion_signal_evidence_ids:
        flagged_ids = set(conversion_signal_evidence_ids)
        for slot in slots:
            for segment in slot.get("evidence_segments", []):
                if str(segment.get("evidence_id") or "") in flagged_ids:
                    segment["carries_conversion_signal"] = True
    return {
        "schema_version": 3,
        "machine": machine,
        "reference_benchmark": _anton_reference_benchmark_profile(machine),
        "evidence_errors": evidence_errors,
        "slots": slots,
        "slot_order": [slot["slot"] for slot in slots],
        "required_slots": sorted(_ANTON_REQUIRED_SLOT_ROLES),
        "evidence_slot_roles": role_by_id,
        "contract": {
            "paragraph_shape": f"one Anton/DVsU paragraph, {_ANTON_PARAGRAPH_FORMULA_SENTENCES} natural formula sentences",
            "movement": "raw original problem -> raw engineering decision -> raw tradeoff -> raw reality -> short paragraph-derived conclusion",
            "sentence_formula": _ANTON_PARAGRAPH_FORMULA,
            "paragraph_words": _ANTON_PARAGRAPH_WORD_RANGE,
            "narrative_weight": narrative_weight,
            # OR-5: the named DvsU mode with its overrides travels with the plan.
            "mode_profile": mode_profile,
            # QL-3/QL-9: the deliberately-bare tag is the only twist/memorable exemption.
            "deliberately_bare": _card_is_deliberately_bare(card, narrative_weight),
            # QL-4 (OR-3): the expanded twist menu the model must classify against.
            "twist_menu": list(_DVSU_TWIST_TYPES),
            "twist_substitutes": list(_DVSU_TWIST_SUBSTITUTES),
            # Writer pass 5: ranked ids of evidence carrying the documented
            # role conversion; the FIRST id is the mandatory reality-beat and
            # twist source. Empty when the package holds no enforceable signal.
            "conversion_signal_evidence_ids": conversion_signal_evidence_ids,
            "conversion_signal_rule": (
                "the evidence flagged carries_conversion_signal is the machine's documented "
                "designed-vs-used story; write the reality sentence FROM the first flagged id, "
                "cite it in that sentence's claim_map row, and build the twist from it - an "
                "acceptance, delivery, or test event is never the reality beat while a flagged "
                "conversion segment exists"
            ) if conversion_signal_evidence_ids else "",
            # QL-5: the four legal verdict-punch forms; QL-6 house punch first.
            "verdict_punch_forms": ["single_hammer", "antithesis", "concede_then_cut", "triad"],
            # Corpus recalibration (2026-07-16): Anton B-17/B-52 carry 14
            # claim-mapped numbers - spec-block and long-form allow 15;
            # tight-production keeps 8.
            "maximum_numerical_details": 8 if mode_profile["register"] == "tight_production" else 15,
            "editorial_thesis": "single engineering decision, tradeoff, or contrast; not a catalog summary",
            "benchmark_style_rule": "for Strategic Bomber benchmark machines, preserve Anton's compact inventory cadence: selected scale/spec facts, production or service reality, and a landed verdict, while using only locked evidence",
            "memorable_fact_rule": "if a sourced memorable_fact slot exists, fold it into the strongest required beat; do not create a separate fifth factual sentence",
            "early_human_detail_rule": "for the first three machines, use sourced human_detail, named decision, or official finding when available; never invent one",
            "conclusion_rule": "final sentence is editorial synthesis from the assembled paragraph only; no new sourced meaning beat, dates, specs, or numbers",
            "onscreen_label": "derive only from onscreen_label evidence or sourced role/operator/build/date slots; metadata for Producer File/on-screen text, never spoken narration",
        },
    }


def _parse_machine_story_sentences(raw: str) -> dict:
    """Parse the constrained Anton paragraph bundle returned by the story distiller."""
    import json
    import re

    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {"_parse_error": "story distiller must return valid JSON matching the Anton paragraph schema"}
    if not isinstance(parsed, dict):
        return {"_parse_error": "story distiller must return a JSON object matching the Anton paragraph schema"}

    parse_warnings: list[str] = []
    canonical_keys = {
        "editorial_thesis",
        "formula_sentences",
        "paragraph",
        "claim_map",
        "onscreen_label",
        # QL-3/QL-4: the model declares the designed-vs-used twist
        # {"type": <menu>, "substitute": <payload-or-null>, "summary": <text>}.
        "twist",
    }
    extra_keys = sorted(
        str(key) for key in parsed.keys()
        if str(key) not in canonical_keys
    )
    if extra_keys:
        parse_warnings.append(
            "story distiller returned extra top-level key(s) outside the exact Anton schema: "
            + ", ".join(extra_keys)
        )
    for key in ("paragraph", "voiceover", "narration"):
        if isinstance(parsed.get(key), str) and not isinstance(parsed.get("paragraph"), str):
            if key != "paragraph":
                parse_warnings.append(
                    f"story distiller used noncanonical key `{key}`; use exact key `paragraph`"
                )
            parsed["paragraph"] = parsed[key]
    if isinstance(parsed.get("paragraph"), str):
        parsed["paragraph"] = " ".join(parsed.get("paragraph", "").split())
    if not isinstance(parsed.get("formula_sentences"), list):
        for key in ("sentences", "sentence_assembly", "assembly"):
            if isinstance(parsed.get(key), list):
                parse_warnings.append(
                    f"story distiller used noncanonical key `{key}`; use exact key `formula_sentences`"
                )
                parsed["formula_sentences"] = parsed[key]
                break
    if isinstance(parsed.get("formula_sentences"), list):
        normalized_sentences: list[str] = []
        for item in parsed.get("formula_sentences") or []:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                parse_warnings.append("formula_sentences must be an array of strings, not objects")
                text = str(item.get("sentence") or item.get("span") or item.get("text") or "")
            else:
                text = ""
            text = " ".join(text.split())
            if text:
                normalized_sentences.append(text)
        parsed["formula_sentences"] = normalized_sentences
    if not isinstance(parsed.get("claim_map"), list):
        for key in ("claims", "evidence_map", "source_map"):
            if isinstance(parsed.get(key), list):
                parse_warnings.append(
                    f"story distiller used noncanonical key `{key}`; use exact key `claim_map`"
                )
                parsed["claim_map"] = parsed[key]
                break
    if not isinstance(parsed.get("editorial_thesis"), str):
        for key in ("engineering_decision", "throughline", "contrast_axis"):
            if isinstance(parsed.get(key), str):
                parse_warnings.append(
                    f"story distiller used noncanonical key `{key}`; use exact key `editorial_thesis`"
                )
                parsed["editorial_thesis"] = parsed[key]
                break
    if parse_warnings:
        parsed["_parse_warnings"] = list(dict.fromkeys(parse_warnings))
    sanitized = {
        key: parsed[key]
        for key in canonical_keys
        if key in parsed
    }
    if parsed.get("_parse_warnings"):
        sanitized["_parse_warnings"] = parsed["_parse_warnings"]
    return sanitized


def _anton_narrative_weight_profile(card: dict, evidence: list[dict], register: str = _DVSU_DEFAULT_REGISTER) -> dict:
    """Advisory Anton paragraph weight: richer for pivotal machines, tighter for transitional ones."""
    import re as _re

    explicit = str(
        (card or {}).get("narrative_weight")
        or (card or {}).get("story_weight")
        or (card or {}).get("paragraph_weight")
        or ""
    ).strip().lower()
    text = " ".join(
        str(value or "")
        for value in [
            (card or {}).get("engineering_thesis"),
            (card or {}).get("why_this_unit_deserves_a_paragraph"),
            (card or {}).get("surprising_fact"),
            (card or {}).get("design_problem"),
            (card or {}).get("engineering_response"),
            (card or {}).get("tradeoff"),
            (card or {}).get("actual_outcome"),
            *[
                f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
                for segment in evidence or []
                if isinstance(segment, dict)
            ],
        ]
    ).lower()
    major_terms = (
        "mass-produced", "most-produced", "mainstay", "workhorse", "backbone",
        "served in every theater", "decisive", "defined", "dominant",
        "large-scale combat", "heavy losses", "thousands",
    )
    transitional_terms = (
        "prototype", "only one", "single prototype", "experimental", "testbed",
        "never used in combat", "canceled", "cancelled", "too late",
        "limited production", "interim",
    )
    explicit_major = any(term in explicit for term in ("major", "pivotal", "landmark", "central", "core"))
    explicit_transitional = any(term in explicit for term in ("minor", "transitional", "brief", "prototype", "limited"))
    major_score = sum(1 for term in major_terms if term in text)
    transitional_score = sum(1 for term in transitional_terms if term in text)
    if _re.search(r"\b\d{4,}\b", text) and any(term in text for term in ("built", "produced", "lost", "losses")):
        major_score += 1
    if explicit_major:
        label = "major"
    elif explicit_transitional:
        label = "transitional"
    elif major_score > transitional_score:
        label = "major"
    elif transitional_score > major_score:
        label = "transitional"
    else:
        label = "standard"

    # QL-1/QL-2 (approved 2026-07-16): per-register bands, weight-scaled.
    # Marquee machines run 110-150; bare prototypes and connective entries run
    # 80-95 (the QD-6 warn band is their legal home); standard = register band.
    register = str(register or _DVSU_DEFAULT_REGISTER)
    register_band = _DVSU_REGISTER_TARGETS.get(register, _DVSU_REGISTER_TARGETS[_DVSU_DEFAULT_REGISTER])
    if label == "major":
        target_words = "110-150"
        guidance = "marquee paragraph; keep the required four beats, then use extra sourced human, combat, production, or memorable detail only if it strengthens the thesis"
    elif label == "transitional":
        target_words = "80-95"
        guidance = "deliberately bare paragraph; prove the machine's role, cut secondary specs, and land the contrast quickly"
    else:
        target_words = register_band
        guidance = "balanced paragraph; do not pad or compress unless the sourced role clearly deserves it"
    return {
        "label": label,
        "target_words": target_words,
        "register": register,
        "register_target_words": register_band,
        "major_score": major_score,
        "transitional_score": transitional_score,
        "guidance": guidance,
    }


def _narrative_weight_target_warning(paragraph: str, plan: dict) -> Optional[str]:
    import re as _re

    if not isinstance(plan, dict):
        return None
    narrative_weight = (plan.get("contract") or {}).get("narrative_weight")
    if not isinstance(narrative_weight, dict):
        return None
    label = str(narrative_weight.get("label") or "").strip().lower()
    if label not in {"major", "transitional", "standard"}:
        return None
    target_words = str(narrative_weight.get("target_words") or "").strip()
    match = _re.search(r"(\d+)\s*-\s*(\d+)", target_words)
    if not match:
        return None
    low, high = int(match.group(1)), int(match.group(2))
    word_count = _spoken_word_count(paragraph)
    if low <= word_count <= high:
        return None
    # QL-1/QL-2 register targets are guidance (QD-6: only 80/170 are hard).
    return _ADVISORY_PREFIX + (
        f"paragraph misses narrative_weight target {label} {low}-{high} words "
        f"({word_count} words)"
    )


# G16: single source of truth for the two content-shape rules that were
# previously ONLY taught to the model after a paid failure (via the raw
# warning string riding along in the repair prompt's "Warnings: ..." line).
# The word lists below are what the validators actually match against, so
# the writer-prompt rule lines built from them (see
# _why_paragraph_writer_rule_line / _visual_identity_writer_rule_line, used
# by _run_unit_research_hold's FIRST-pass prompt) can never drift from what
# review enforces - change a word list here and the validator, the warning
# text, and the writer prompt all move together.
_ENGINEERING_DECISION_WORDS = (
    "because", "but", "despite", "instead", "rather", "decision", "chose",
    "choice", "balanced", "trade", "traded", "tradeoff", "tension",
    "contrast", "proved", "validated", "failed", "solved", "created",
    "answered", "sacrificed", "compromise", "consequence", "outpaced",
    "survived", "needed", "requirement", "problem", "doctrine", "range",
    "payload", "production", "speed", "endurance", "survivability",
    "precision", "escort", "intercontinental",
)
_ENGINEERING_DECISION_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in _ENGINEERING_DECISION_WORDS) + r")\b"
)
_WHY_PARAGRAPH_CONTENT_RULE = (
    "why_this_unit_deserves_a_paragraph must name a concrete engineering decision, "
    "problem, tradeoff, or consequence"
)


def _why_paragraph_writer_rule_line() -> str:
    """Prompt-facing phrasing of the why_this_unit_deserves_a_paragraph
    content rule, built from the SAME word list the validator matches."""
    examples = ", ".join(_ENGINEERING_DECISION_WORDS[:14])
    return (
        f"- {_WHY_PARAGRAPH_CONTENT_RULE} - use language like {examples}, etc; "
        "do not just say it mattered, was famous, or deserves a paragraph."
    )


def _paragraph_worth_warnings(machine: str, paragraph_worth: str) -> list[str]:
    import re as _re

    text = " ".join(str(paragraph_worth or "").split())
    lower = text.lower()
    warnings: list[str] = []
    if _spoken_word_count(text) < 8:
        return ["missing/weak why_this_unit_deserves_a_paragraph"]
    generic_patterns = (
        r"\b(?:this|the)\s+(?:machine|aircraft|unit)\s+(?:mattered|was important|was significant|deserves a paragraph)\b",
        r"\b(?:because|since|as)\s+it\s+(?:existed|was built|was famous|was important|mattered)\b",
        r"\b(?:famous|iconic|legendary)\b",
    )
    if any(_re.search(pattern, lower) for pattern in generic_patterns):
        warnings.append("why_this_unit_deserves_a_paragraph is generic; state the unique engineering idea no other roster machine can replace")
    if not _ENGINEERING_DECISION_PATTERN.search(lower):
        warnings.append(_WHY_PARAGRAPH_CONTENT_RULE)
    machine_codes = _locked_machine_identity_codes(machine)
    normalized_text = _normalized_unit_code(text)
    if (
        machine_codes
        and not any(code in normalized_text for code in machine_codes)
        and _unit_display_name(machine).split()[-1].lower() not in lower
    ):
        warnings.append("why_this_unit_deserves_a_paragraph must be specific to the locked machine")
    return warnings


def _auto_cite_field_from_segments(
    field_text: str,
    segments: list[dict],
    machine: str,
    extra_stopwords: Optional[set[str]] = None,
) -> list[str]:
    """Greedily pick the segments whose text grounds the field's words.

    Citation selection is a set-cover problem code solves deterministically;
    asking the model to do this bookkeeping failed five straight XB-15 runs.
    Only segments that actually contain the field's factual words are cited -
    nothing is invented. Returns at most 3 evidence IDs. Uses the SAME
    field-specific stopword set as the grounding grader so the citer never
    hunts for words the grader would have ignored (confirmed asymmetry bug)."""
    text = " ".join(str(field_text or "").split())
    if not text:
        return []
    usable = [
        segment for segment in segments
        if isinstance(segment, dict) and str(segment.get("evidence_id") or "").strip()
    ]
    chosen: list[str] = []
    cited_text = ""
    remaining = len(_ungrounded_factual_words(text, cited_text, machine, extra_stopwords=extra_stopwords))
    for _ in range(3):
        if remaining == 0:
            break
        best_id, best_left, best_seg_text = "", remaining, ""
        for segment in usable:
            evidence_id = str(segment.get("evidence_id") or "").strip()
            if evidence_id in chosen:
                continue
            seg_text = f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
            left = len(_ungrounded_factual_words(text, f"{cited_text} {seg_text}", machine, extra_stopwords=extra_stopwords))
            if left < best_left:
                best_id, best_left, best_seg_text = evidence_id, left, seg_text
        if not best_id:
            break
        chosen.append(best_id)
        cited_text = f"{cited_text} {best_seg_text}"
        remaining = best_left
    return chosen


def _normalize_card_field_citations(card: dict, machine: str = "") -> dict:
    """Deterministically remap, drop, or derive *_evidence_ids citations.

    Models routinely cite package EXCERPT_IDs they never returned as segments
    (XB-15 attempts 4-5, 2026-07-16). Bookkeeping is code's job, not the
    model's: remap a dangling ID to the segment carrying that
    source_excerpt_id; drop what cannot be remapped; and when a field's list
    ends up EMPTY while its text exists, auto-cite the segments that ground
    the field's words (_auto_cite_field_from_segments). Only existing
    segments are ever cited; a list that stays empty is left for the
    validators so the repair pass hears a precise warning."""
    if not isinstance(card, dict):
        return card
    segments = card.get("evidence_segments")
    if not isinstance(segments, list):
        return card
    valid_ids = {
        str(segment.get("evidence_id") or "").strip()
        for segment in segments
        if isinstance(segment, dict) and str(segment.get("evidence_id") or "").strip()
    }
    excerpt_to_evidence: dict[str, str] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        excerpt_id = str(segment.get("source_excerpt_id") or "").strip()
        evidence_id = str(segment.get("evidence_id") or "").strip()
        if excerpt_id and evidence_id and excerpt_id not in excerpt_to_evidence:
            excerpt_to_evidence[excerpt_id] = evidence_id
    field_to_text = {
        "timeframe_evidence_ids": (str(card.get("timeframe") or ""), _TIMEFRAME_EXTRA_STOPWORDS),
        "visual_identity_evidence_ids": (str(card.get("visual_identity") or ""), _VISUAL_IDENTITY_EXTRA_STOPWORDS),
    }
    for field, (field_text, field_stopwords) in field_to_text.items():
        cited = card.get(field)
        if not isinstance(cited, list):
            continue
        cleaned: list[str] = []
        for item in cited:
            token = str(item or "").strip()
            if not token:
                continue
            mapped = token if token in valid_ids else excerpt_to_evidence.get(token, "")
            if mapped and mapped not in cleaned:
                cleaned.append(mapped)
        if not cleaned:
            cleaned = _auto_cite_field_from_segments(field_text, segments, machine, extra_stopwords=field_stopwords)
        card[field] = cleaned
    return card


def _cited_evidence_tier_warning(
    field: str,
    cited_ids: list[str],
    evidence_by_id: dict[str, dict],
) -> list[str]:
    """Flag (advisory, not blocking) a card field cited only by Tier-4 sources.

    G14, 2026-07-31 (Ryan's ruling, decisions.md): the tier floor demoted
    from hard block to advisory - Wikipedia-grade (Tier 3-4) sources may now
    carry a card. This warning still surfaces so the field is visible for
    review, but _blocking_warnings() strips it before any pass/fail or
    repair-round decision. NOTE: the frontend's own
    machineResearchCardStatus 'Tier 4-only · preview blocked' gate is a
    separate, frontend-owned check this backend change does not touch."""
    tiers = [
        _source_tier_number(evidence_by_id[item])
        for item in cited_ids
        if str(evidence_by_id[item].get("source_url") or evidence_by_id[item].get("url") or "").strip()
    ]
    tiers = [tier for tier in tiers if tier > 0]
    if tiers and all(tier >= 4 for tier in tiers):
        return [
            _ADVISORY_PREFIX + "[caution_only_sources_advisory] "
            f"{field}_evidence_ids cite Tier 4/caution sources only; cite at least one Tier 1-3 excerpt for {field}"
        ]
    return []


# Field-specific grounding stopwords, shared by the graders AND the deterministic
# auto-citer so both tokenize a field the same way. Keeping them out of sync let
# the auto-citer cite for words the grader ignored (a confirmed XB-15 asymmetry).
_VISUAL_IDENTITY_EXTRA_STOPWORDS = {
    "appearance", "brief", "cited", "configuration", "exact", "feature", "features",
    "identifiable", "identified", "identify", "image", "must", "recognizable",
    "show", "shown", "shows", "source", "unmistakable", "visible",
}
_TIMEFRAME_EXTRA_STOPWORDS = {
    "confirmed", "date", "dates", "documented", "era", "period", "service",
    "source", "sourced", "timeframe", "verified",
}
# G2: free repair-pass drop-list. These are stray filler words a card-writing
# model keeps adding to timeframe/visual_identity/why_this_unit_deserves_a_
# paragraph that never appear in any cited excerpt (observed this week
# hand-fixing DVsU cards; see tasks/evidence/dvsu-research-simulator/
# STATE.md). The deterministic pre-repair pass drops them outright instead
# of spending a paid repair round asking the model to remove them.
_GROUNDING_STRAY_DROP_WORDS = {"seen", "ship", "plus", "toward", "towards"}


def _all_segments_grounding_text(evidence: list[dict]) -> str:
    """Grading universe for per-word grounding: every segment's claim + excerpt.

    Ruling 2026-07-16: visual_identity and timeframe are graded against ALL of the
    card's evidence segments, not only the <=3 cited ids. Citations stay as
    provenance (validated separately) but are no longer the grounding universe.
    """
    return " ".join(
        f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
        for segment in evidence or []
        if isinstance(segment, dict)
    )


# G16: single source of truth for the visual_identity content rule (see the
# _ENGINEERING_DECISION_WORDS comment above _paragraph_worth_warnings for why
# this is a module-level constant rather than an inline regex string - the
# validator's own regex, the warning text, and the writer-prompt rule line
# are all built from this one list so they can never drift apart).
_VISUAL_IDENTITY_FEATURE_WORDS = (
    "wing", "wings", "engine", "engines", "nose", "tail", "fuselage",
    "cockpit", "canopy", "turret", "gun", "guns", "propeller", "propellers",
    "landing gear", "pod", "pods", "bay", "swept", "delta", "straight",
    "silhouette", "profile", "intake", "intakes", "exhaust", "boom", "booms",
    # ship / carrier
    "deck", "decks", "hull", "bow", "stern", "island", "mast", "masts",
    "funnel", "funnels", "superstructure", "bridge", "keel", "catapult",
    "catapults", "palisades", "derrick", "derricks", "crane", "cranes",
    "hangar", "ramp",
    # helicopter
    "rotor", "rotors", "tailboom", "skids",
    # armor / ground vehicle
    "track", "tracks", "barrel", "chassis", "cab", "wheels", "armor",
    "armour", "glacis", "hatch", "hatches",
)
_VISUAL_IDENTITY_FEATURE_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in _VISUAL_IDENTITY_FEATURE_WORDS) + r")\b"
)
_VISUAL_IDENTITY_CONTENT_RULE = "visual_identity must include concrete visible machine features"


def _visual_identity_writer_rule_line() -> str:
    """Prompt-facing phrasing of the visual_identity content rule, built
    from the SAME word list the validator matches."""
    examples = ", ".join(_VISUAL_IDENTITY_FEATURE_WORDS[:14])
    return (
        f"- {_VISUAL_IDENTITY_CONTENT_RULE} - name specific visible parts (for example "
        f"{examples}, etc), not generic praise like 'recognizable' or 'unmistakable' alone."
    )


def _visual_identity_warnings(
    machine: str,
    visual_identity: str,
    evidence: list[dict],
    evidence_ids: Any,
) -> list[str]:
    """Validate Producer File image-brief basis without leaking it into narration."""
    import re as _re

    text = " ".join(str(visual_identity or "").split())
    lower = text.lower()
    warnings: list[str] = []
    if _spoken_word_count(text) < 8:
        return ["missing/weak visual_identity"]

    generic_patterns = (
        r"\b(?:image|picture|photo|shot)\s+of\s+(?:the\s+)?(?:machine|aircraft|bomber|unit)\b",
        r"\b(?:hero\s+image|hero\s+shot|visual(?:ly)?\s+distinct|make\s+it\s+look\s+realistic)\b",
        # The lookahead's feature list mirrors visible_feature_pattern below —
        # same cross-domain extension (2026-07-30), same reason: "unmistakable"
        # next to "flight deck" or "twin funnels" is concrete, not generic.
        r"\b(?:recognizable|unmistakable|distinctive)\b(?![^.]{0,80}\b(?:wing|wings|engine|engines|nose|tail|fuselage|cockpit|canopy|turret|gun|propeller|landing gear|pod|pods|bay|silhouette|"
        r"deck|decks|hull|bow|stern|island|mast|masts|funnel|funnels|superstructure|catapult|hangar|"
        r"rotor|rotors|track|tracks|barrel|chassis|glacis)\b)",
    )
    if any(_re.search(pattern, lower) for pattern in generic_patterns):
        warnings.append("visual_identity is generic; name concrete visible features that identify the locked machine")

    production_patterns = (
        r"\b(?:camera|shot|pan|zoom|dolly|tilt|motion|animate|animation|transition|edit|editing|b-roll|thumbnail)\b",
        r"\b(?:on-screen text|onscreen text|text overlay|caption|lower third)\b",
    )
    if any(_re.search(pattern, lower) for pattern in production_patterns):
        warnings.append("visual_identity must describe visible machine features only, not camera/editing/text directions")

    # Cross-domain (2026-07-30): this list was aircraft-only, which made every
    # honest ship card fail "must include concrete visible machine features" —
    # a Majestic-class carrier has no wings or fuselage to name. DVsU covers
    # ships, helicopters, armor and ground vehicles too, so the vocabulary
    # carries each domain's visible anatomy. Additive: every previously
    # passing description still passes.
    if not _VISUAL_IDENTITY_FEATURE_PATTERN.search(lower):
        warnings.append(_VISUAL_IDENTITY_CONTENT_RULE)

    machine_codes = _locked_machine_identity_codes(machine)
    normalized_text = _normalized_unit_code(text)
    if (
        machine_codes
        and not any(code in normalized_text for code in machine_codes)
        and _unit_display_name(machine).split()[-1].lower() not in lower
    ):
        warnings.append("visual_identity must be specific to the locked machine")

    if not isinstance(evidence_ids, list) or not [item for item in evidence_ids if str(item).strip()]:
        warnings.append("visual_identity_evidence_ids must cite source-backed evidence IDs")
        return warnings

    evidence_by_id = {
        str(segment.get("evidence_id") or "").strip(): segment
        for segment in evidence or []
        if isinstance(segment, dict) and str(segment.get("evidence_id") or "").strip()
    }
    cited_ids = [str(item).strip() for item in evidence_ids if str(item).strip()]
    unknown_ids = [item for item in cited_ids if item not in evidence_by_id]
    if unknown_ids:
        warnings.append("visual_identity_evidence_ids reference unknown evidence ID(s): " + ", ".join(unknown_ids))
        return warnings
    warnings.extend(_cited_evidence_tier_warning("visual_identity", cited_ids, evidence_by_id))

    # Grounding + number support are graded against ALL evidence segments, not
    # only the cited ids (ruling 2026-07-16). Citations above stay as provenance.
    grounding_text = _all_segments_grounding_text(evidence)
    ungrounded = _ungrounded_factual_words(
        text, grounding_text, machine, extra_stopwords=_VISUAL_IDENTITY_EXTRA_STOPWORDS
    )
    if ungrounded:
        warnings.append(
            "visual_identity contains detail(s) not grounded in evidence segments: "
            + ", ".join(ungrounded[:8])
        )

    identity_for_numbers = text
    grounding_for_numbers = grounding_text
    for designation in _re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", machine.upper()):
        identity_for_numbers = _re.sub(
            rf"\b{_re.escape(designation)}(?:s)?\b",
            "",
            identity_for_numbers,
            flags=_re.IGNORECASE,
        )
        grounding_for_numbers = _re.sub(
            rf"\b{_re.escape(designation)}(?:s)?\b",
            "",
            grounding_for_numbers,
            flags=_re.IGNORECASE,
        )
    grounded_number_keys = {_numeric_token_key(token) for token in _numeric_tokens_from_text(grounding_for_numbers)}
    unsupported_numbers = [
        mention["raw"] for mention in _numeric_mentions_from_text(identity_for_numbers)
        if mention["key"] not in grounded_number_keys
    ]
    if unsupported_numbers:
        warnings.append(
            "visual_identity introduced unsupported numerical detail(s): "
            + ", ".join(unsupported_numbers)
        )
    return warnings


def _timeframe_warnings(
    machine: str,
    timeframe: str,
    evidence: list[dict],
    evidence_ids: Any,
) -> list[str]:
    """Validate the research-standard date/service-period basis."""
    import re as _re

    text = " ".join(str(timeframe or "").split())
    lower = text.lower()
    warnings: list[str] = []
    if _spoken_word_count(text) < 5:
        return ["missing/weak timeframe"]

    if _re.search(r"\b(?:documented|verified|sourced)\s+(?:date|dates|timeframe|service period)\b", lower) and not _re.search(
        r"\b(?:served|service|period|era|war|conflict|first flew|entered|retired|built|prototype|operational|from|between|during|in)\b",
        lower,
    ):
        warnings.append("timeframe is generic; state the sourced date, era, or service period")

    if not _re.search(
        r"\b(?:\d{3,4}s?|\d{1,2}(?:st|nd|rd|th)?\s+century|served|service|period|era|war|conflict|first flew|entered|retired|built|prototype|operational|from|between|during)\b",
        lower,
    ):
        warnings.append("timeframe must name a sourced date, era, or service period")

    machine_codes = _locked_machine_identity_codes(machine)
    normalized_text = _normalized_unit_code(text)
    if (
        machine_codes
        and not any(code in normalized_text for code in machine_codes)
        and _unit_display_name(machine).split()[-1].lower() not in lower
    ):
        warnings.append("timeframe must be specific to the locked machine")

    if not isinstance(evidence_ids, list) or not [item for item in evidence_ids if str(item).strip()]:
        warnings.append("timeframe_evidence_ids must cite source-backed evidence IDs")
        return warnings

    evidence_by_id = {
        str(segment.get("evidence_id") or "").strip(): segment
        for segment in evidence or []
        if isinstance(segment, dict) and str(segment.get("evidence_id") or "").strip()
    }
    cited_ids = [str(item).strip() for item in evidence_ids if str(item).strip()]
    unknown_ids = [item for item in cited_ids if item not in evidence_by_id]
    if unknown_ids:
        warnings.append("timeframe_evidence_ids reference unknown evidence ID(s): " + ", ".join(unknown_ids))
        return warnings
    warnings.extend(_cited_evidence_tier_warning("timeframe", cited_ids, evidence_by_id))

    # Grounding + number support are graded against ALL evidence segments, not
    # only the cited ids (ruling 2026-07-16). Citations above stay as provenance.
    grounding_text = _all_segments_grounding_text(evidence)
    ungrounded = _ungrounded_factual_words(
        text, grounding_text, machine, extra_stopwords=_TIMEFRAME_EXTRA_STOPWORDS
    )
    if ungrounded:
        warnings.append(
            "timeframe contains detail(s) not grounded in evidence segments: "
            + ", ".join(ungrounded[:8])
        )

    timeframe_for_numbers = text
    grounding_for_numbers = grounding_text
    for designation in _re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", machine.upper()):
        timeframe_for_numbers = _re.sub(
            rf"\b{_re.escape(designation)}(?:s)?\b",
            "",
            timeframe_for_numbers,
            flags=_re.IGNORECASE,
        )
        grounding_for_numbers = _re.sub(
            rf"\b{_re.escape(designation)}(?:s)?\b",
            "",
            grounding_for_numbers,
            flags=_re.IGNORECASE,
        )
    grounded_number_keys = {_numeric_token_key(token) for token in _numeric_tokens_from_text(grounding_for_numbers)}
    unsupported_numbers = [
        mention["raw"] for mention in _numeric_mentions_from_text(timeframe_for_numbers)
        if mention["key"] not in grounded_number_keys
    ]
    if unsupported_numbers:
        warnings.append(
            "timeframe introduced unsupported numerical detail(s): "
            + ", ".join(unsupported_numbers)
        )
    return warnings


# Round-8 FIX 1 (2026-07-16): role-conversion vocabulary that marks the
# designed-vs-used story inside raw package excerpts.
_CONVERSION_ROLE_TERMS = (
    "cargo", "converted", "conversion", "redesignated", "tanker",
    "target drone", "testbed", "trainer", "transport",
)


def _package_conversion_signals(package: Optional[dict], machine: str) -> list[dict]:
    """Deterministic scan for REDESIGNATION/CONVERSION signals in a raw
    source package (Round-8 FIX 1). No LLM involved.

    Round-9 recalibration (2026-07-16): the package is already MACHINE-SCOPED
    by construction (_checkpoint_machine_raw_source_package keys by machine),
    so a mentions-the-locked-machine guard is redundant and misses excerpts
    that carry the conversion by pronoun or cross-designation ("the sole
    example was redesignated XC-105 and used for cargo" - the live XB-15
    miss). ANY candidate excerpt carrying role-conversion vocabulary is an
    enforceable signal. Cross-prefix designation tokens (XB-15 -> XC-105) are
    recorded as additional signal data; a prefix-only hit (no vocabulary)
    still requires the machine mention and guides the prompt without ever
    blocking (comparison-mention noise bound)."""
    if not isinstance(package, dict):
        return []
    locked_codes = {code for code in _target_machine_designation_codes(machine) if code}
    locked_prefixes = {
        re.match(r"[A-Z]+", code).group(0)
        for code in locked_codes
        if re.match(r"[A-Z]+", code)
    }
    signals: list[dict] = []
    for item in package.get("candidate_excerpts") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        lower = text.lower()
        terms = sorted(
            term for term in _CONVERSION_ROLE_TERMS
            if re.search(rf"\b{re.escape(term)}\b", lower)
        )
        tokens: list[str] = []
        for raw_token in _AIRCRAFT_DESIGNATION_RE.findall(text.upper()):
            code = _normalized_unit_code(raw_token)
            if not code or code in locked_codes:
                continue
            prefix_match = re.match(r"[A-Z]+", code)
            if prefix_match and prefix_match.group(0) not in locked_prefixes:
                if code not in tokens:
                    tokens.append(code)
        if terms:
            # Vocabulary-bearing excerpts are enforceable signals - no mention
            # guard (the package is machine-scoped by construction).
            signals.append({
                "excerpt_id": str(item.get("excerpt_id") or item.get("locator") or "").strip(),
                "terms": terms,
                "tokens": tokens,
                "enforce": True,
            })
        elif tokens and _mentions_machine(text, machine):
            # Prefix-only hit: prompt guidance, never a block.
            signals.append({
                "excerpt_id": str(item.get("excerpt_id") or item.get("locator") or "").strip(),
                "terms": [],
                "tokens": tokens,
                "enforce": False,
            })
    return signals


def _conversion_signal_prompt_line(signals: list[dict]) -> str:
    """Round-8 FIX 1: the explicit must-select instruction for the card prompts."""
    enforced = [signal for signal in signals if signal.get("excerpt_id")]
    if not enforced:
        return ""
    described = ", ".join(
        signal["excerpt_id"]
        + " ("
        + ", ".join((signal.get("tokens") or []) + (signal.get("terms") or []))
        + ")"
        for signal in enforced[:4]
    )
    return (
        "- MUST-SELECT: the package contains a role-conversion signal - "
        f"{described}: this is the designed-vs-used story. Select that excerpt as evidence "
        "(reality/service kind) and write actual_outcome from it.\n"
    )


def _card_evidence_carries_signal(evidence: list[dict], signal: dict) -> bool:
    """True when any card evidence segment carries the conversion signal:
    same excerpt identity, the signal designation, or the signal vocabulary."""
    excerpt_id = str(signal.get("excerpt_id") or "")
    tokens = set(signal.get("tokens") or [])
    terms = signal.get("terms") or []
    for segment in evidence or []:
        if not isinstance(segment, dict):
            continue
        identity = {
            str(segment.get("source_excerpt_id") or "").strip(),
            str(segment.get("excerpt_id") or "").strip(),
            str(segment.get("locator") or "").strip(),
        }
        if excerpt_id and excerpt_id in identity:
            return True
        segment_text = f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
        if tokens and any(
            _normalized_unit_code(raw) in tokens
            for raw in _AIRCRAFT_DESIGNATION_RE.findall(segment_text.upper())
        ):
            return True
        segment_lower = segment_text.lower()
        if terms and any(re.search(rf"\b{re.escape(term)}\b", segment_lower) for term in terms):
            return True
    return False


# Writer pass 5 (2026-07-16): role nouns name what the machine BECAME; the
# remaining _CONVERSION_ROLE_TERMS ("converted", "redesignated", ...) are verbs
# that also fire on design-phase renamings ("redesignated XB-15 in July 1936"),
# so role-noun-bearing evidence outranks verb-only evidence when the story plan
# flags the twist source.
_CONVERSION_ROLE_NOUNS = (
    "cargo", "tanker", "target drone", "testbed", "trainer", "transport",
)


def _conversion_signal_evidence_ids(
    evidence: list[dict], package: Optional[dict], machine: str
) -> list[str]:
    """Card evidence segments that carry an enforceable package conversion
    signal, ranked: role-noun bearers (cargo/transport/...) first, bare
    conversion-verb hits last. The FIRST id is the designed-vs-used source
    the writer must build the reality beat from."""
    signals = [
        signal for signal in _package_conversion_signals(package, machine)
        if signal.get("enforce")
    ]
    if not signals:
        return []
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for segment in evidence or []:
        if not isinstance(segment, dict):
            continue
        evidence_id = str(segment.get("evidence_id") or "").strip()
        if not evidence_id or evidence_id in seen:
            continue
        if not any(_card_evidence_carries_signal([segment], signal) for signal in signals):
            continue
        seen.add(evidence_id)
        segment_lower = f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}".lower()
        has_role_noun = any(
            re.search(rf"\b{re.escape(term)}\b", segment_lower)
            for term in _CONVERSION_ROLE_NOUNS
        )
        ranked.append((0 if has_role_noun else 1, evidence_id))
    return [evidence_id for _, evidence_id in sorted(ranked, key=lambda row: row[0])]


def _timeframe_promotable_excerpts(card: dict, package: Optional[dict]) -> list[dict]:
    """Structured Round-8 FIX 3 scan: which package excerpts carry the dated
    anchor the timeframe field states but its segments lack. Deterministic.
    Rows: {"excerpt_id": str, "covered": [numeric keys]}."""
    if not isinstance(card, dict) or not isinstance(package, dict):
        return []
    timeframe = str(card.get("timeframe") or "")
    if not timeframe.strip():
        return []
    wanted_keys = {
        mention["key"]
        for mention in _numeric_mentions_from_text(_strip_designations_for_numbers(timeframe))
        if mention.get("key")
    }
    if not wanted_keys:
        return []
    segment_keys = {
        _numeric_token_key(token)
        for segment in (card.get("evidence_segments") or [])
        if isinstance(segment, dict)
        for token in _numeric_tokens_from_text(
            f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
        )
    }
    missing_keys = wanted_keys - segment_keys
    if not missing_keys:
        return []
    rows: list[dict] = []
    for item in package.get("candidate_excerpts") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        excerpt_id = str(item.get("excerpt_id") or item.get("locator") or "").strip()
        if not text or not excerpt_id:
            continue
        excerpt_keys = {
            mention["key"] for mention in _numeric_mentions_from_text(_strip_designations_for_numbers(text))
        }
        covered = sorted(missing_keys & excerpt_keys)
        if covered:
            rows.append({"excerpt_id": excerpt_id, "covered": covered})
        if len(rows) >= 3:
            break
    return rows


def _timeframe_repair_hints(card: dict, package: Optional[dict]) -> list[str]:
    """Round-8 FIX 3: when the timeframe field states dates its segments lack
    while the PACKAGE holds them, name the exact excerpt the repair should
    return as a kind=timeframe support segment. Deterministic."""
    return [
        f"REPAIR HINT: excerpt {row['excerpt_id']} contains the timeframe's date(s) "
        f"({', '.join(row['covered'])}) - return it as a kind=timeframe support segment "
        "and cite it in timeframe_evidence_ids."
        for row in _timeframe_promotable_excerpts(card, package)
    ]


def _designed_vs_used_gap_warnings(
    card: dict,
    evidence: list[dict],
    machine: str = "",
    source_package: Optional[dict] = None,
) -> list[str]:
    """QL-3 research leg (OR-1 approved): research must surface the GAP.

    The channel engine runs on built-for-X-used-as-Y. If the card's
    actual-use story (reality-family evidence plus actual_outcome) adds almost
    no content beyond the design-intent story (original_problem and
    engineering_decision evidence plus the design fields), research has merely
    restated the design intent and the writer has no gap to run on.
    Deterministic form: the used-side text must carry at least three novel
    content stems absent from the design-side text. The explicit
    deliberately_bare tag is the only exemption.

    Round-8 FIX 2: when the raw package holds enforceable conversion signals
    (vocabulary-bearing excerpts) and the card selected NONE of them,
    delivery/records-only outcomes never satisfy the gap - the warning stays
    and names the exact excerpt(s) to select."""
    import re as _re

    if not isinstance(card, dict) or _bare_tag_is_valid(card):
        return []
    unselected_signals = []
    if machine and source_package is not None:
        unselected_signals = [
            signal for signal in _package_conversion_signals(source_package, machine)
            if signal.get("enforce") and not _card_evidence_carries_signal(evidence, signal)
        ]
    if unselected_signals:
        described = ", ".join(
            (signal.get("excerpt_id") or "?")
            + " ("
            + ", ".join((signal.get("tokens") or []) + (signal.get("terms") or []))
            + ")"
            for signal in unselected_signals[:3]
        )
        return [
            "no designed-vs-used gap found - the package holds the role-conversion story and the card "
            f"selected none of it; select excerpt(s) {described} as evidence and write actual_outcome from it"
        ]
    design_texts = [
        str(card.get("design_problem") or ""),
        str(card.get("engineering_response") or ""),
        str(card.get("engineering_thesis") or ""),
    ]
    used_texts = [str(card.get("actual_outcome") or "")]
    for segment in evidence or []:
        if not isinstance(segment, dict):
            continue
        role = segment.get("slot_role") or _anton_slot_role_for_kind(str(segment.get("kind") or ""))
        segment_text = f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
        if role in {"original_problem", "engineering_decision", "identity_origin", "scale_specs"}:
            design_texts.append(segment_text)
        elif role in {"reality", "build_reality", "service_reality"}:
            used_texts.append(segment_text)
    used_blob = " ".join(used_texts)
    if not used_blob.strip():
        return [
            "no designed-vs-used gap found - research must surface how it was ACTUALLY used; "
            "if the hunt already ran and no gap exists, mark deliberately_bare with gap_hunt_summary"
        ]
    # The used-side must tell an EMPLOYMENT or FATE story, not delivery /
    # acceptance / first-flight logistics (which merely complete the design
    # intent - XB-15's stored card is the proven offender: "flew to Wright
    # Field to be accepted for testing"). Deterministic form: the used side
    # needs (a) at least one actual-use/fate marker word AND (b) at least
    # three content stems absent from the design side.
    use_or_fate_markers = (
        "abandoned", "bombed", "cancelled", "canceled", "cancellation", "cargo",
        "combat", "converted", "conversion", "convoy", "crashed", "damaged",
        "deployed", "deployment", "destroyed", "dropped", "exported", "ferried",
        "ferry", "fought", "losses", "lost", "mission", "missions", "modified",
        "mothballed", "museum", "operational", "operationally", "operations",
        "patrol", "patrols", "redesignated", "relegated", "retired",
        "retirement", "scrap", "scrapped", "served", "service", "serving",
        "shot", "sold", "sorties", "sortie", "sunk", "sank", "surplus",
        "trainer", "transport", "transported", "war", "warfare", "wartime",
    )
    used_lower = used_blob.lower()
    has_use_marker = any(
        _re.search(rf"\b{marker}\b", used_lower) for marker in use_or_fate_markers
    )
    ignore = _STORY_UNIQUENESS_STOPWORDS | _SCRIPT_GLUE_STOPWORDS
    design_stems = {
        _grounding_stem(token)
        for token in _re.findall(r"[a-z]+", " ".join(design_texts).lower())
    }
    novel_stems = {
        _grounding_stem(token)
        for token in _re.findall(r"[a-z]+", used_lower)
        if len(token) >= 4 and token not in ignore and _grounding_stem(token) not in design_stems
    }
    if not has_use_marker or len(novel_stems) < 3:
        return [
            "no designed-vs-used gap found - research must surface how it was ACTUALLY used; "
            "if the hunt already ran and no gap exists, mark deliberately_bare with gap_hunt_summary"
        ]
    return []


def _research_card_contract_warnings(
    machine: str,
    card: dict,
    source_package: Optional[dict] = None,
    require_source_package: bool = False,
) -> list[str]:
    """Shared DVsU one-machine research-card contract before save or spend.

    IDEMPOTENT + READ-ONLY: citation normalization/auto-citing runs here on a
    deep copy before grading, so the save path and the read-only readiness path
    grade byte-identical input and the caller's stored card is never mutated.
    Running the referee twice on its own output yields the same verdict."""
    import copy as _copy
    warnings: list[str] = []
    if not isinstance(card, dict):
        return ["research card was not an object"]
    card = _normalize_card_field_citations(_copy.deepcopy(card), machine)
    card_unit = _unit_display_name(
        card.get("unit") or card.get("machine") or card.get("machine_name")
        or card.get("name") or card.get("designation") or ""
    )
    if not card_unit or _normalized_unit_code(card_unit) not in _locked_machine_identity_codes(machine):
        warnings.append(f"card unit does not match locked machine {machine}")
    if _spoken_word_count(str(card.get("engineering_thesis") or "").strip()) < 4:
        warnings.append("missing/weak engineering_thesis")
    warnings.extend(
        _paragraph_worth_warnings(
            machine,
            str(card.get("why_this_unit_deserves_a_paragraph") or "").strip(),
        )
    )
    evidence, evidence_errors = _normalize_machine_evidence(card, machine)
    warnings.extend(
        _visual_identity_warnings(
            machine,
            str(card.get("visual_identity") or "").strip(),
            evidence,
            card.get("visual_identity_evidence_ids"),
        )
    )
    warnings.extend(
        _timeframe_warnings(
            machine,
            str(card.get("timeframe") or "").strip(),
            evidence,
            card.get("timeframe_evidence_ids"),
        )
    )
    if not str(card.get("surprising_fact") or "").strip():
        warnings.append("missing surprising_fact")
    source_notes = card.get("source_notes")
    if not isinstance(source_notes, list) or not source_notes:
        warnings.append("missing source_notes")
    warnings.extend(evidence_errors)
    if not evidence_errors:
        sourced_tiers = [
            tier for tier in (
                _source_tier_number(segment) for segment in evidence
                if isinstance(segment, dict)
                and str(segment.get("source_url") or segment.get("url") or "").strip()
            ) if tier > 0
        ]
        # G14, 2026-07-31 (Ryan's ruling, decisions.md): tier floor demoted
        # from hard block to advisory - Wikipedia-grade (Tier 3-4) sources
        # may carry a card. Was: "Mirror the UI's 'Research card needs
        # selected Tier 1-2 evidence' gate." _blocking_warnings() strips
        # this before any pass/fail decision; the anti-hallucination
        # grounding checks above (evidence_errors) are untouched and still
        # hard-block.
        if sourced_tiers and all(tier > 2 for tier in sourced_tiers):
            warnings.append(
                _ADVISORY_PREFIX + "[tier_floor_advisory] "
                "evidence_segments cite no Tier 1-2 source; cite at least one Tier 1-2 excerpt"
            )
    # B2: a bare tag is only honored with hunt evidence.
    if card.get("deliberately_bare") is True and not _bare_tag_is_valid(card):
        warnings.append(
            "bare tag without hunt evidence - deliberately_bare requires a non-trivial gap_hunt_summary"
        )
    # QL-9 / D4: the (valid) deliberately-bare tag exempts the memorable-fact demand.
    if not evidence_errors and not _bare_tag_is_valid(card) and not any(
        segment.get("slot_role") == "memorable_fact" for segment in evidence
    ):
        warnings.append("missing sourced memorable_fact evidence segment")
    # QL-3 research leg (OR-1 approved): the card must surface how the machine
    # was ACTUALLY used, not restate its design intent.
    if not evidence_errors:
        warnings.extend(_designed_vs_used_gap_warnings(card, evidence, machine, source_package))
    if source_package is not None or require_source_package:
        warnings.extend(_verified_machine_source_package_quality_errors(source_package, machine))
        warnings.extend(_verified_machine_source_package_identity_errors(source_package, machine))
        warnings.extend(_validate_card_against_verified_sources(card, source_package))
    if not evidence_errors:
        plan = _machine_story_plan({"unit_research_cards": [card]}, machine)
        missing_slots = [
            slot["slot"] for slot in plan["slots"]
            if slot.get("required") and not slot["evidence_ids"]
        ]
        if missing_slots:
            warnings.append("evidence_segments missing required Anton slots for: " + ", ".join(missing_slots))
    return list(dict.fromkeys(warnings))


def _card_readiness_from_validation(validation: Any) -> Optional[dict]:
    """Shape one stored referee verdict as the UI-facing readiness object."""
    import json as _json_readiness
    if isinstance(validation, str):
        try:
            validation = _json_readiness.loads(validation)
            if isinstance(validation, str):
                validation = _json_readiness.loads(validation)
        except (ValueError, TypeError):
            return None
    if not isinstance(validation, dict):
        return None
    return {
        "passed": bool(validation.get("passed")),
        "warnings": [str(item) for item in (validation.get("warnings") or []) if str(item).strip()],
    }


async def enrich_research_payload_readiness(tenant_id: str, video_id: str, research_payload: Any) -> Any:
    """Attach each machine's STORED referee verdict to research_payload cards.

    Single source of truth for the UI: every response that returns
    research_payload runs through here so `unit_research_cards[].readiness` is
    always present and consistent (no flicker between enriched/unenriched shapes).
    readiness = {"passed": bool, "warnings": [str]} from machine_research_cards.validation,
    matched by roster_index (migration 153 - the row identity) via the
    locked unit_roster: two roster entries can share a machine_key, so a
    machine_key-only match would apply one machine's verdict to a different
    machine's card. machine_key stays a fallback for the rare case a
    payload's unit_roster is unavailable to resolve against. A card with no
    stored verdict gets readiness = None. Failed cards are NEVER dropped -
    their verdict and warnings are exactly what the Research and Script tabs
    must display. Reads the compact verdict table directly (not
    _load_machine_research_cards, which drops failed rows)."""
    if not isinstance(research_payload, dict):
        return research_payload
    cards = research_payload.get("unit_research_cards")
    if not isinstance(cards, list) or not cards:
        return research_payload
    roster = [
        _unit_display_name(item) for item in (research_payload.get("unit_roster") or [])
        if _unit_display_name(item)
    ]
    verdict_by_index: dict[int, dict] = {}
    verdict_by_key: dict[str, dict] = {}
    try:
        rows = await fetch_all(
            "SELECT machine_key, roster_index, validation FROM machine_research_cards WHERE tenant_id = $1 AND video_id = $2",
            tenant_id, video_id,
        )
    except Exception as exc:  # compact table unavailable -> serve cards with readiness=None
        _logger.warning("[machine-research] readiness enrichment read unavailable: %s", str(exc)[:150])
        rows = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        readiness = _card_readiness_from_validation(row.get("validation"))
        if readiness is None:
            continue
        index = row.get("roster_index")
        if isinstance(index, int):
            verdict_by_index[index] = readiness
        key = _normalized_unit_code(str(row.get("machine_key") or ""))
        # Fallback-only: first-write-wins, and always overridden below
        # whenever roster-index resolution succeeds, so this can never
        # apply one colliding-pair member's verdict to the other once the
        # roster is available to disambiguate them.
        if key:
            verdict_by_key.setdefault(key, readiness)
    enriched = dict(research_payload)
    new_cards: list[Any] = []
    for card in cards:
        if not isinstance(card, dict):
            new_cards.append(card)
            continue
        identity = (
            card.get("unit") or card.get("machine") or card.get("machine_name")
            or card.get("name") or card.get("designation") or ""
        )
        index = _roster_index_for_identity(roster, identity) if roster else None
        card = dict(card)
        if index is not None and index in verdict_by_index:
            card["readiness"] = verdict_by_index[index]
        else:
            key = _normalized_unit_code(_unit_display_name(identity))
            card["readiness"] = verdict_by_key.get(key)  # None when no stored verdict
        new_cards.append(card)
    enriched["unit_research_cards"] = new_cards
    return enriched


# ---------------------------------------------------------------------------
# Roster orchestrator - surgical repair verbs (Ryan's ruling, 2026-07-16).
# Cheapest-first repair of failing machine research cards. LAW FREEZE: nothing
# here adds a gate law; these helpers only fix cards until the existing
# referee (_research_card_contract_warnings) passes. Full research re-runs
# REPLACE the source package (evidence re-rolls), so every verb below is
# card-surgical or package-append-only.
# ---------------------------------------------------------------------------

_REPAIR_VERB_EST_COST_USD = {
    "promote_excerpt": 0.0,
    "rekind_segments": 0.0,
    "targeted_fetch": 0.02,
    "select_excerpt": 0.01,
    "rewrite_field": 0.02,
    "mark_bare": 0.01,
    "full_rerun": 0.60,
}

_REWRITABLE_CARD_FIELDS = (
    "engineering_thesis",
    "why_this_unit_deserves_a_paragraph",
    "timeframe",
    "visual_identity",
)

# Same contract wording as the build and repair prompts (contract triangle law).
_FIELD_REWRITE_CONTRACTS = {
    "engineering_thesis": (
        "engineering_thesis states the one engineering idea this machine's paragraph argues, "
        "in one concise full sentence grounded in the evidence segments."
    ),
    "why_this_unit_deserves_a_paragraph": (
        "why_this_unit_deserves_a_paragraph must state the unique engineering idea this locked machine "
        "contributes to the video, specific enough that no other roster machine could replace it. "
        "Do not say it mattered, was famous, or deserves a paragraph. "
        "It may not introduce dates, numbers, other machine designations, events, or specifications "
        "absent from the evidence_segments."
    ),
    "timeframe": (
        "timeframe is the research-standard date/service-period basis only: state the sourced date range, "
        "era, first-flight/service period, or prototype/operational period, and cite it with "
        "timeframe_evidence_ids. Do not invent dates. timeframe text must name the locked machine's "
        "designation explicitly, and may use only factual words and numbers that appear inside the "
        "evidence_segments - if no evidence segment contains the month name, do not write the month."
    ),
    "visual_identity": (
        "visual_identity is Producer File/image-brief basis only, never spoken narration: state the exact "
        "visible machine features that make the locked unit unmistakable, and cite them with "
        "visual_identity_evidence_ids. Describe only what is visible on the machine; do not include camera "
        "movement, animation, transitions, thumbnail copy, on-screen text, captions, or editing directions. "
        "visual_identity text must name the locked machine's designation explicitly, and may use only "
        "factual words and numbers that appear inside the evidence_segments."
    ),
}

_TARGETED_FETCH_PRIMARY_DOMAINS = [
    "boeing.com", "lockheedmartin.com", "northropgrumman.com", "af.mil",
    "defense.gov", "navy.mil", "army.mil", "nasa.gov", "archives.gov",
    "si.edu",
]


def _find_candidate_excerpt(package: Optional[dict], excerpt_id: str) -> Optional[dict]:
    """Locate one package excerpt by excerpt_id or locator."""
    wanted = str(excerpt_id or "").strip()
    if not wanted or not isinstance(package, dict):
        return None
    for item in package.get("candidate_excerpts") or []:
        if not isinstance(item, dict):
            continue
        identity = {
            str(item.get("excerpt_id") or "").strip(),
            str(item.get("locator") or "").strip(),
        }
        if wanted in identity:
            return item
    return None


def _card_cited_excerpt_ids(card: Optional[dict]) -> set[str]:
    ids: set[str] = set()
    if not isinstance(card, dict):
        return ids
    for segment in card.get("evidence_segments") or []:
        if not isinstance(segment, dict):
            continue
        for key in ("source_excerpt_id", "excerpt_id"):
            value = str(segment.get(key) or "").strip()
            if value:
                ids.add(value)
    return ids


def _promote_excerpt_precheck_error(candidate: Optional[dict], kind: str, machine: str) -> str:
    """Reject promotions the referee would immediately warn about."""
    if candidate is None:
        return "excerpt_id not found in this machine's verified source package"
    if not _verified_source_candidate_traceable(candidate):
        return "excerpt is not traceable (missing source_url/locator/capture method) so the card cannot cite it"
    slot_role = _anton_slot_role_for_kind(kind)
    if slot_role is None:
        return f"unsupported Anton slot kind: {kind}"
    text = str(candidate.get("text") or "").strip()
    if not text:
        return "excerpt has no text"
    hints = [str(h).strip() for h in (candidate.get("anton_slot_hints") or []) if str(h).strip()]
    if slot_role in _ANTON_REQUIRED_SLOT_ROLES and hints and slot_role not in hints:
        return (
            f"excerpt is hinted for {', '.join(hints)}, not {slot_role}; "
            "promoting it there would fail the slot-hint gate"
        )
    if slot_role == "human_detail" and not _human_detail_has_attribution(text):
        return "human_detail promotion requires a named person or official finding in the excerpt"
    return ""


def _promoted_evidence_segment(candidate: dict, kind: str, machine: str, existing_ids: set[str]) -> dict:
    """Deterministically lift one verified package excerpt into a card segment.

    claim = the exact excerpt: fully grounded by construction, so the word and
    number gates cannot fire on it (the referee itself clamps ungrounded claims
    back to the excerpt, this just starts there)."""
    text = " ".join(str(candidate.get("text") or "").split())
    excerpt_id = str(candidate.get("excerpt_id") or "").strip()
    base_id = f"EP-{excerpt_id or 'X'}"
    evidence_id = base_id
    suffix = 2
    while evidence_id in existing_ids:
        evidence_id = f"{base_id}-{suffix}"
        suffix += 1
    segment = {
        "evidence_id": evidence_id,
        "kind": str(kind or "reality").strip().lower(),
        "claim": text,
        "source_excerpt": text,
        "source_excerpt_id": excerpt_id,
        "source_url": str(candidate.get("source_url") or "").strip(),
        "source_title": str(candidate.get("source_title") or "").strip(),
        "locator": str(candidate.get("locator") or excerpt_id).strip(),
        "numeric_tokens": _numeric_tokens_from_text(_strip_designations_for_numbers(text, machine)),
        "confidence": "high",
        "promoted_from_package": True,
    }
    source_id = str(candidate.get("source_id") or "").strip()
    if source_id:
        segment["source_id"] = source_id
    return segment


def _merge_card_into_review_cards(existing_cards: list, card: dict, machine: str) -> list:
    """Replace only the target card in the review list; keep the rest byte-identical."""
    target_key = _normalized_unit_code(machine)
    merged: list = []
    replaced = False
    for existing in existing_cards or []:
        if isinstance(existing, dict):
            raw_unit = existing.get("unit") or existing.get("machine") or existing.get("name") or existing.get("designation") or ""
            existing_key = _normalized_unit_code(_unit_display_name(raw_unit) or str(raw_unit))
            if target_key and existing_key == target_key:
                if not replaced:
                    merged.append(card)
                    replaced = True
                continue
        merged.append(existing)
    if not replaced:
        merged.append(card)
    return merged


def _hold_validation_with_unit_verdict(payload: dict, machine: str, warnings: list[str]) -> dict:
    """Update one machine's entry inside unit_research_hold_validation.

    G14, 2026-07-31: passed is computed from BLOCKING warnings only; the
    full `warnings` list (advisory notes included, e.g. tier_floor_advisory)
    is still stored so it stays visible to the caller/UI."""
    validation = payload.get("unit_research_hold_validation")
    validation = dict(validation) if isinstance(validation, dict) else {}
    units = [dict(unit) for unit in (validation.get("units") or []) if isinstance(unit, dict)]
    code = _normalized_unit_code(machine)
    blocking = _blocking_warnings(warnings)
    entry = {"machine": machine, "passed": not blocking, "warnings": list(warnings)}
    replaced = False
    for index, unit in enumerate(units):
        if _normalized_unit_code(str(unit.get("machine") or "")) == code:
            units[index] = entry
            replaced = True
            break
    if not replaced:
        units.append(entry)
    validation["units"] = units
    validation["passed"] = bool(units) and all(unit.get("passed") for unit in units)
    validation["in_progress"] = False
    validation["target_machine"] = machine
    validation["target_machine_passed"] = not blocking
    return validation


def _warning_targets_field(warning: str, field: str) -> bool:
    return field in str(warning or "")


def _segment_slot_hint_mismatches(card: Optional[dict], package: Optional[dict]) -> list[dict]:
    """Required-beat segments whose raw excerpt is hinted for a DIFFERENT beat.

    These are the referee's "maps X to raw excerpt hinted for Y" warnings,
    recomputed structurally so repair never string-parses warning text."""
    if not isinstance(card, dict) or not isinstance(package, dict):
        return []
    mismatches: list[dict] = []
    for segment in card.get("evidence_segments") or []:
        if not isinstance(segment, dict):
            continue
        role = _anton_slot_role_for_kind(str(segment.get("kind") or ""))
        if role not in _ANTON_REQUIRED_SLOT_ROLES:
            continue
        identity = str(segment.get("source_excerpt_id") or segment.get("excerpt_id") or "").strip() \
            or str(segment.get("locator") or "").strip()
        candidate = _find_candidate_excerpt(package, identity)
        if candidate is None:
            continue
        hints = [str(h).strip() for h in (candidate.get("anton_slot_hints") or []) if str(h).strip()]
        if hints and role not in hints:
            mismatches.append({
                "segment": segment,
                "role": role,
                "hints": hints,
                "excerpt_id": str(candidate.get("excerpt_id") or "").strip(),
            })
    return mismatches


def _promotable_slot_excerpt(
    package: Optional[dict], card: Optional[dict], slot: str, machine: str, max_tier: int = 3
) -> Optional[dict]:
    """Best uncited, traceable, slot-hinted package excerpt (lowest tier first)."""
    if not isinstance(package, dict):
        return None
    cited = _card_cited_excerpt_ids(card)
    ranked = sorted(
        (
            item for item in package.get("candidate_excerpts") or []
            if isinstance(item, dict)
            and str(item.get("excerpt_id") or "").strip()
            and str(item.get("excerpt_id") or "").strip() not in cited
            and slot in (item.get("anton_slot_hints") or [])
            and _source_tier_number(item) <= max_tier
            and _mentions_machine(str(item.get("text") or ""), machine)
        ),
        key=lambda item: (_source_tier_number(item), str(item.get("excerpt_id") or "")),
    )
    for item in ranked:
        if not _promote_excerpt_precheck_error(item, slot, machine):
            return item
    return None


def _tier4_only_required_slots(card: Optional[dict]) -> list[str]:
    """Required beats whose every sourced segment sits on Tier 4/caution rows."""
    if not isinstance(card, dict):
        return []
    tiers_by_role: dict[str, list[int]] = {}
    for segment in card.get("evidence_segments") or []:
        if not isinstance(segment, dict):
            continue
        role = _anton_slot_role_for_kind(str(segment.get("kind") or ""))
        if role not in _ANTON_REQUIRED_SLOT_ROLES:
            continue
        if not str(segment.get("source_url") or "").strip():
            continue
        tier = _source_tier_number(segment)
        if tier > 0:
            tiers_by_role.setdefault(role, []).append(tier)
    return sorted(
        role for role, tiers in tiers_by_role.items()
        if tiers and all(tier >= 4 for tier in tiers)
    )


def _segment_surgery_plan(card: Optional[dict], package: Optional[dict], machine: str) -> dict:
    """Shared deterministic plan for rekind_segments.

    rekinds: segments to re-label toward their excerpt's hint.
    promotes: hinted excerpts to lift so no required beat loses coverage.
    blocked: beats the PACKAGE cannot back-fill (targeted_fetch territory)."""
    plan: dict = {"rekinds": [], "promotes": [], "blocked": []}
    if not isinstance(card, dict) or not isinstance(package, dict):
        return plan
    segments = card.get("evidence_segments") or []
    mismatches = _segment_slot_hint_mismatches(card, package)
    mismatched_ids = {id(m["segment"]) for m in mismatches}
    planned_excerpts: set[str] = set()
    for mismatch in mismatches:
        segment, role, hints = mismatch["segment"], mismatch["role"], mismatch["hints"]
        covered = any(
            isinstance(other, dict) and other is not segment
            and id(other) not in mismatched_ids
            and _anton_slot_role_for_kind(str(other.get("kind") or "")) == role
            for other in segments
        )
        replacement = None
        if not covered:
            replacement = _promotable_slot_excerpt(package, card, role, machine)
            if replacement is not None and str(replacement.get("excerpt_id") or "") in planned_excerpts:
                replacement = None
            if replacement is None:
                plan["blocked"].append({"role": role, "evidence_id": segment.get("evidence_id"), "reason": "mismatch"})
                continue
        plan["rekinds"].append({
            "segment": segment,
            "evidence_id": segment.get("evidence_id"),
            "old_kind": str(segment.get("kind") or ""),
            "new_kind": hints[0],
        })
        if replacement is not None:
            plan["promotes"].append({"item": replacement, "kind": role, "reason": "mismatch"})
            planned_excerpts.add(str(replacement.get("excerpt_id") or ""))
    # G14, 2026-07-31: tier4_only-required-slot promotes/blocks are tagged
    # "reason": "tier4_only" so _structured_repair_feedback can route them
    # to a PREFERENCE hint (optional upgrade) instead of a must-fix NAMED
    # FIX directive - the underlying rule (a required beat resting only on
    # Tier 4/caution sources) is advisory now, not blocking. Mismatch-driven
    # entries above are a genuine structural/grounding fix and stay must-fix.
    for slot in _tier4_only_required_slots(card):
        item = _promotable_slot_excerpt(package, card, slot, machine)
        if item is not None and str(item.get("excerpt_id") or "") not in planned_excerpts:
            plan["promotes"].append({"item": item, "kind": slot, "reason": "tier4_only"})
            planned_excerpts.add(str(item.get("excerpt_id") or ""))
        elif item is None:
            plan["blocked"].append({"role": slot, "evidence_id": None, "reason": "tier4_only"})
    return plan


# Slot-focused append-only fetch queries (targeted_fetch focus="slot:<role>").
_SLOT_FETCH_QUERY_TERMS = {
    "original_problem": "requirement program specification designed to need",
    "engineering_decision": "design engineering configuration engine wing development",
    "tradeoff": "limitation problem compromise drawback lessons learned",
    "reality": "service history operational use combat fate",
}


def _package_gap_hunt_already_ran(package: Optional[dict]) -> bool:
    """True when an append-only reality/use-story hunt already extended this package."""
    if not isinstance(package, dict):
        return False
    return any(
        isinstance(entry, dict) and str(entry.get("focus") or "") == "reality"
        for entry in package.get("appended_fetches") or []
    )


# Writer pass 5 wrap-up (2026-07-16): ONE shared checklist. These are the
# frozen benchmark_cadence audit's own vocabularies, extracted so the research
# side can grade a card by the same rules the script judge will use. Change
# them ONLY together with the audit (law freeze).
_ANTON_SCALE_CAPABILITY_RE = re.compile(
    r"\b(wingspan|engine|engines|horsepower|payload|bombs?|pounds?|miles?|range|speed|mph|mach|feet|foot|altitude|ceiling|fuel|carry|carried|load|loads)\b"
)
_ANTON_PRODUCTION_SERVICE_RE = re.compile(
    r"\b(built|produced|production|served|service|combat|transport|campaign|theater|theatre|lost|losses|flew|prototype|prototypes|wartime|world war)\b"
)

_STARVATION_DECISION_ROLES = {"engineering_decision", "scale_specs"}
_STARVATION_REALITY_ROLES = {"reality", "build_reality", "service_reality"}


def _script_starvation_gaps(card: Optional[dict], machine: str) -> list[str]:
    """Predict, card-side, what the frozen benchmark_cadence audit will demand
    of the paragraph: >=2 numeric details available, scale/capability evidence
    for the decision beat, production/service evidence for the reality beat.
    A card can pass the research referee and still starve the writer - this is
    the seam that cost three hand-promote rounds on 2026-07-16. Empty list for
    non-benchmark machines (the audit does not grade cadence there) and for
    cards the referee already owns (no evidence)."""
    benchmark = _anton_reference_benchmark_profile(machine)
    if not (
        isinstance(benchmark, dict)
        and str(benchmark.get("source_video") or "") == "Every US Strategic Bomber Ever Built"
    ):
        return []
    evidence, _errors = _normalize_machine_evidence(card if isinstance(card, dict) else {}, machine)
    if not evidence:
        return []
    numeric_keys: set[str] = set()
    has_scale = False
    has_production = False
    for segment in evidence:
        role = segment.get("slot_role") or _anton_slot_role_for_kind(segment.get("kind"))
        text = f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
        lower = text.lower()
        if role in _STARVATION_DECISION_ROLES or role in _STARVATION_REALITY_ROLES:
            numeric_keys.update(
                key for key in (
                    _numeric_token_key(token)
                    for token in _numeric_tokens_from_text(_strip_designations_for_numbers(text, machine))
                ) if key
            )
        if role in _STARVATION_DECISION_ROLES and _ANTON_SCALE_CAPABILITY_RE.search(lower):
            has_scale = True
        if role in _STARVATION_REALITY_ROLES and _ANTON_PRODUCTION_SERVICE_RE.search(lower):
            has_production = True
    gaps: list[str] = []
    if len(numeric_keys) < 2:
        gaps.append("numeric_details")
    if not has_scale:
        gaps.append("scale_capability")
    if not has_production:
        gaps.append("production_service")
    return gaps


def _script_starvation_promote_actions(
    card: Optional[dict], package: Optional[dict], machine: str
) -> list[dict]:
    """FREE promote_excerpt actions that fill _script_starvation_gaps from the
    machine's own verified package. Always SUPPORT kinds (scale_specs_context /
    build_reality_context): they bypass the required-slot hint gate and never
    overwrite actual_outcome (a reality-kind promote rewrites the twist field).
    Candidates must mention the locked machine and carry no cross-designation
    (a foreign machine's numbers must never feed this card's spec block)."""
    gaps = set(_script_starvation_gaps(card, machine))
    if not gaps or not isinstance(package, dict):
        return []
    cited = _card_cited_excerpt_ids(card)

    def _numeric_key_count(text: str) -> int:
        return len({
            key for key in (
                _numeric_token_key(token)
                for token in _numeric_tokens_from_text(_strip_designations_for_numbers(text, machine))
            ) if key
        })

    scored: list[tuple[int, int, str, str, str]] = []
    for item in package.get("candidate_excerpts") or []:
        if not isinstance(item, dict):
            continue
        excerpt_id = str(item.get("excerpt_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not excerpt_id or not text or excerpt_id in cited:
            continue
        if not _verified_source_candidate_traceable(item):
            continue
        if not _mentions_machine(text, machine):
            continue
        searchable = " ".join(str(item.get(key) or "") for key in ("source_title", "text"))
        allowed_codes = _target_machine_designation_codes(machine)
        foreign_codes = [
            code for code in _non_target_designation_codes(searchable, machine)
            # "12,731 B-17s" reads as code B17S: a plural of the locked code
            # is the locked machine, not a foreign designation.
            if not any(code == f"{allowed}S" for allowed in allowed_codes)
        ]
        if foreign_codes:
            continue
        lower = text.lower()
        numbers = _numeric_key_count(text)
        if not numbers:
            continue
        is_scale = bool(_ANTON_SCALE_CAPABILITY_RE.search(lower))
        is_production = bool(_ANTON_PRODUCTION_SERVICE_RE.search(lower))
        if is_production and ("production_service" in gaps or "numeric_details" in gaps):
            kind = "build_reality_context"
        elif is_scale and ("scale_capability" in gaps or "numeric_details" in gaps):
            kind = "scale_specs_context"
        else:
            continue
        if _promote_excerpt_precheck_error(item, kind, machine):
            continue
        scored.append((_source_tier_number(item), -numbers, excerpt_id, kind, lower))

    actions: list[dict] = []
    remaining = set(gaps)
    remaining_numbers = 2
    for _tier, neg_numbers, excerpt_id, kind, lower in sorted(scored, key=lambda row: (row[0], row[1], row[2])):
        fills = set()
        if kind == "scale_specs_context" and "scale_capability" in remaining:
            fills.add("scale_capability")
        if kind == "build_reality_context" and "production_service" in remaining:
            fills.add("production_service")
        if "numeric_details" in remaining:
            fills.add("numeric_details")
        if not fills:
            continue
        actions.append({
            "verb": "promote_excerpt",
            "excerpt_id": excerpt_id,
            "kind": kind,
            "reason": "script audit demands " + ", ".join(sorted(fills)) + "; package carries it",
        })
        remaining -= {"scale_capability", "production_service"} & fills
        remaining_numbers += neg_numbers  # neg_numbers is negative
        if remaining_numbers <= 0:
            remaining.discard("numeric_details")
        if not remaining or len(actions) >= 3:
            break
    return actions


# ---------------------------------------------------------------------------
# PLAN -> WRITE -> EDIT (2026-07-17): the writer restructure. One prompt was
# doing three jobs - choosing facts, writing prose, and keeping the citation
# ledger - under ~35 simultaneous laws, and dropped a different one per roll.
# Now CODE picks the facts per beat and CODE keeps the ledger; the model only
# writes; failures get a minimal targeted edit of the same draft instead of a
# fresh re-roll. Gates are untouched (law freeze): this changes how the writer
# meets them, not what they demand.
# ---------------------------------------------------------------------------

_BEAT_ASSIGNMENTS = (
    (
        "original_problem",
        ("identity_origin", "timeframe", "role_category"),
        "State the problem, requirement, or ambition that created this machine.",
    ),
    (
        "engineering_decision",
        ("scale_specs", "visual_identity"),
        "State the design answer with its concrete scale/spec facts and numbers.",
    ),
    (
        "tradeoff",
        (),
        "State the cost, limit, sacrifice, or expectation the design created.",
    ),
    (
        "reality",
        ("build_reality", "service_reality", "memorable_fact", "human_detail"),
        "State what documented reality did: production, losses, service, conversion. "
        "The production count and its superlative live HERE, never in the closer.",
    ),
)


def _deterministic_beat_plan(story_plan: dict, machine: str) -> list[dict]:
    """CODE picks the facts. Each of the four evidence beats gets its required
    slot's segments plus its natural support slots, deduplicated in order. The
    writer selects within a beat but never across beats, so formula order can
    no longer be violated by citation."""
    slots_by_role = {
        str(slot.get("slot") or ""): slot
        for slot in (story_plan.get("slots") if isinstance(story_plan, dict) else []) or []
        if isinstance(slot, dict)
    }

    def _segments(role: str) -> list[dict]:
        return [
            segment for segment in (slots_by_role.get(role, {}).get("evidence_segments") or [])
            if isinstance(segment, dict)
        ]

    conversion_ids = [
        str(item) for item in (
            (story_plan.get("contract") or {}).get("conversion_signal_evidence_ids") or []
        ) if str(item).strip()
    ]
    beats: list[dict] = []
    for index, (role, supports, job) in enumerate(_BEAT_ASSIGNMENTS, start=1):
        segments = list(_segments(role))
        for support in supports:
            segments.extend(_segments(support))
        seen: set[str] = set()
        deduped: list[dict] = []
        for segment in segments:
            evidence_id = str(segment.get("evidence_id") or "").strip()
            if evidence_id and evidence_id not in seen:
                seen.add(evidence_id)
                deduped.append(segment)
        beat = {"index": index, "role": role, "job": job, "segments": deduped}
        if role == "reality" and conversion_ids:
            flagged = [eid for eid in conversion_ids if eid in seen]
            if flagged:
                beat["twist_source_id"] = flagged[0]
        beats.append(beat)
    return beats


def _beat_number_directives(beats: list[dict], machine: str) -> list[dict]:
    """Name the exact numeric facts sentences 2 and 4 must carry, so the
    number floor is met by assignment instead of hope."""
    directives: list[dict] = []
    for beat in beats:
        if beat["index"] not in (2, 4):
            continue
        best = None
        best_count = 0
        for segment in beat["segments"]:
            claim = " ".join(str(segment.get("claim") or "").split())
            count = len(_numeric_tokens_from_text(_strip_designations_for_numbers(claim, machine)))
            if count > best_count:
                best, best_count = segment, count
        if best is not None and best_count:
            directives.append({
                "sentence": beat["index"],
                "evidence_id": str(best.get("evidence_id") or ""),
                "fact": " ".join(str(best.get("claim") or "").split())[:240],
            })
    return directives


def _derive_claim_ledger(sentences: list[str], beats: list[dict]) -> list[dict]:
    """CODE keeps the ledger. Sentence N is backed, whole, by beat N's ids -
    the model never does clerical span work again. Same doctrine as
    _assemble_story_paragraph_from_sentences: assembly and bookkeeping are
    code-owned; the model authors prose only."""
    rows: list[dict] = []
    for beat in beats:
        position = beat["index"] - 1
        if position >= len(sentences):
            break
        span = " ".join(str(sentences[position] or "").split())
        ids = [
            str(segment.get("evidence_id") or "").strip()
            for segment in beat["segments"]
            if str(segment.get("evidence_id") or "").strip()
        ]
        if span and ids:
            rows.append({"span": span, "slot": beat["role"], "used_evidence_ids": ids})
    return rows


def _parse_planned_story_sentences(raw: str, beats: list[dict]) -> dict:
    """Parse the write/edit stage's small schema and attach the code ledger."""
    import json as _json_plan
    import re as _re_plan

    text = str(raw or "").strip()
    text = _re_plan.sub(r"^```(?:json)?\s*", "", text, flags=_re_plan.I).strip()
    text = _re_plan.sub(r"\s*```$", "", text).strip()
    try:
        parsed = _json_plan.loads(text)
    except (TypeError, ValueError):
        return {"_parse_error": "planned story writer must return valid JSON"}
    if not isinstance(parsed, dict):
        return {"_parse_error": "planned story writer must return a JSON object"}
    sentences_raw = parsed.get("sentences") or parsed.get("formula_sentences")
    if not isinstance(sentences_raw, list):
        return {"_parse_error": "planned story writer must return a `sentences` array"}
    if any(not isinstance(item, str) for item in sentences_raw):
        return {"_parse_error": "planned story writer sentences must be plain strings"}
    sentences = [" ".join(item.split()) for item in sentences_raw if item.strip()]
    if len(sentences) < 4:
        return {"_parse_error": "planned story writer must return the five formula sentences"}
    return {
        "editorial_thesis": parsed.get("editorial_thesis"),
        "twist": parsed.get("twist"),
        "onscreen_label": "",
        "formula_sentences": sentences,
        "paragraph": " ".join(sentences),
        "claim_map": _derive_claim_ledger(sentences, beats),
    }


def _beat_plan_prompt_block(beats: list[dict], machine: str) -> str:
    """Render the beat plan with each sentence's evidence INLINE."""
    lines: list[str] = []
    for beat in beats:
        lines.append(f"SENTENCE {beat['index']} ({beat['role']}): {beat['job']}")
        if beat.get("twist_source_id"):
            lines.append(
                f"  TWIST SOURCE (mandatory): build this sentence and the twist from evidence {beat['twist_source_id']}."
            )
        for segment in beat["segments"]:
            claim = " ".join(str(segment.get("claim") or "").split())
            lines.append(f"  - [{segment.get('evidence_id')}] {claim}")
        if not beat["segments"]:
            lines.append("  - (no locked evidence: write this beat from the other beats' facts only, adding nothing)")
    for directive in _beat_number_directives(beats, machine):
        lines.append(
            f"MANDATORY NUMBERS for sentence {directive['sentence']}: state the number(s) from [{directive['evidence_id']}] "
            f"\"{directive['fact']}\" (hedge with roughly/about/over if single-source; never drop them)."
        )
    lines.append(
        "SENTENCE 5 (closer): a verdict punch derived ONLY from sentences 1-4. No new facts, no numbers, "
        "no new names, 25 words or fewer. Legal forms: single-hammer, antithesis, concede-then-cut, triad."
    )
    return "\n".join(lines)


def _classify_repair_actions(machine: str, card: Optional[dict], package: Optional[dict]) -> list[dict]:
    """Cheapest-first repair plan for one machine. Deterministic, read-only.

    Order of verbs mirrors Ryan's ruling: promote_excerpt (free) beats
    targeted_fetch/rewrite (pennies) beats full re-run (last resort, re-rolls
    evidence). Returns [] when the card already passes the referee."""
    package_ready = _verified_machine_source_package_ready(package)
    if not package_ready:
        return [{
            "verb": "full_rerun",
            "reason": "no verified source package exists; only a full one-machine research run can create one",
        }]
    package_errors = (
        _verified_machine_source_package_quality_errors(package, machine)
        + _verified_machine_source_package_identity_errors(package, machine)
    )
    if not isinstance(card, dict) or not isinstance(card.get("evidence_segments"), list) or not card.get("evidence_segments"):
        actions: list[dict] = []
        if package_errors:
            actions.append({
                "verb": "targeted_fetch",
                "focus": "tier" if any("Tier 1-2" in error for error in package_errors) else "slots",
                "reason": "package gaps: " + "; ".join(package_errors[:2]),
            })
        actions.append({
            "verb": "full_rerun",
            "reason": "no usable research card (missing evidence segments)",
        })
        return actions
    warnings = _blocking_warnings(
        _research_card_contract_warnings(machine, card, package, require_source_package=True)
    )
    if not warnings:
        # Writer pass 5 wrap-up: a referee-clean card can still starve the
        # frozen script audit; the Repair button fills that for free too.
        return _script_starvation_promote_actions(card, package, machine)
    actions = []
    evidence = card.get("evidence_segments") or []
    cited = _card_cited_excerpt_ids(card)

    # 1. The select-miss class: the package holds the role-conversion story
    #    and the card never selected it. Free deterministic fix.
    for signal in _package_conversion_signals(package, machine):
        if not signal.get("enforce") or _card_evidence_carries_signal(evidence, signal):
            continue
        candidate = _find_candidate_excerpt(package, signal.get("excerpt_id"))
        if candidate is not None and not _promote_excerpt_precheck_error(candidate, "reality", machine):
            actions.append({
                "verb": "promote_excerpt",
                "excerpt_id": str(signal.get("excerpt_id") or "").strip(),
                "kind": "reality",
                "reason": "package holds the role-conversion story the card never selected",
            })
            break

    # 2. Timeframe support segment the package already carries.
    for row in _timeframe_promotable_excerpts(card, package):
        candidate = _find_candidate_excerpt(package, row["excerpt_id"])
        if candidate is not None and not _promote_excerpt_precheck_error(candidate, "timeframe", machine):
            actions.append({
                "verb": "promote_excerpt",
                "excerpt_id": row["excerpt_id"],
                "kind": "timeframe",
                "reason": "package excerpt carries the timeframe's dated anchor: " + ", ".join(row["covered"]),
            })
            break

    # 2b. Slot-hint mismatches and Tier-4-only required beats: free structural
    #     surgery (re-kind toward the hint, back-fill with hinted promotes).
    #     Beats the package cannot back-fill route to an append-only fetch.
    surgery = _segment_surgery_plan(card, package, machine)
    if surgery["rekinds"] or surgery["promotes"]:
        actions.append({
            "verb": "rekind_segments",
            "reason": "segments contradict their excerpts' slot hints or a required beat is Tier 4-only",
        })
    for blocked in surgery["blocked"][:2]:
        actions.append({
            "verb": "targeted_fetch",
            "focus": f"slot:{blocked['role']}",
            "reason": f"package holds no promotable {blocked['role']} excerpt to back-fill the beat",
        })

    # 3. Tier demands: promote a Tier 1-2 excerpt when the package has one,
    #    else append-fetch primary domains.
    if any("Tier 1-2" in warning for warning in warnings):
        tier_candidates = sorted(
            (
                item for item in (package.get("candidate_excerpts") or [])
                if isinstance(item, dict)
                and _verified_source_candidate_traceable(item)
                and _source_tier_number(item) <= 2
                and str(item.get("excerpt_id") or "").strip() not in cited
                and _mentions_machine(str(item.get("text") or ""), machine)
            ),
            key=lambda item: (_source_tier_number(item), str(item.get("excerpt_id") or "")),
        )
        promoted = False
        for item in tier_candidates:
            hints = [str(h).strip() for h in (item.get("anton_slot_hints") or []) if str(h).strip()]
            kind = hints[0] if hints else "timeframe"
            if not _promote_excerpt_precheck_error(item, kind, machine):
                actions.append({
                    "verb": "promote_excerpt",
                    "excerpt_id": str(item.get("excerpt_id") or "").strip(),
                    "kind": kind,
                    "reason": "card cites no Tier 1-2 source; package holds one",
                })
                promoted = True
                break
        if not promoted:
            actions.append({
                "verb": "targeted_fetch",
                "focus": "tier",
                "reason": "no Tier 1-2 source anywhere; append-fetch primary domains",
            })

    # 4. Package-level gaps that survive with a card present.
    if package_errors:
        actions.append({
            "verb": "targeted_fetch",
            "focus": "tier" if any("Tier 1-2" in error for error in package_errors) else "slots",
            "reason": "package gaps: " + "; ".join(package_errors[:2]),
        })

    # 5. Missing memorable_fact: a tiny LLM pick, then a free promote.
    if any("memorable_fact" in warning for warning in warnings):
        actions.append({
            "verb": "select_excerpt",
            "kind": "memorable_fact",
            "reason": "card is missing its sourced memorable_fact segment",
        })

    # 6. No designed-vs-used gap and no conversion signal to promote:
    #    hunt once (append-only), then honor the deliberately-bare fallback.
    gap_warnings = [w for w in warnings if str(w).startswith("no designed-vs-used gap found")]
    if gap_warnings and not any(
        signal.get("enforce") and not _card_evidence_carries_signal(evidence, signal)
        for signal in _package_conversion_signals(package, machine)
    ):
        if not _package_gap_hunt_already_ran(package):
            actions.append({
                "verb": "targeted_fetch",
                "focus": "reality",
                "reason": "hunt the gap: append-fetch service/fate coverage before going bare",
            })
        else:
            actions.append({
                "verb": "mark_bare",
                "reason": "gap hunt already ran and found no use-story; honest bare tag is the fallback",
            })

    # 7. Field-level prose warnings: single-field LLM rewrite.
    for field in _REWRITABLE_CARD_FIELDS:
        if any(_warning_targets_field(warning, field) for warning in warnings):
            actions.append({
                "verb": "rewrite_field",
                "field": field,
                "reason": f"{field} fails its contract",
            })

    # 8. Last resort.
    if not actions:
        actions.append({
            "verb": "full_rerun",
            "reason": "no surgical verb applies: " + "; ".join(str(w) for w in warnings[:3]),
        })
    return actions


def _repair_action_key(action: dict) -> str:
    return "|".join(
        str(action.get(key) or "")
        for key in ("verb", "excerpt_id", "kind", "field", "focus")
    )


_STORY_UNIQUENESS_STOPWORDS = {
    "about", "across", "after", "against", "aircraft", "because", "became",
    "before", "between", "bomber", "bombers", "built", "card", "concrete",
    "could", "decision", "deserves", "different", "engineering", "exposed",
    "flying", "from", "idea", "into", "machine", "machines", "other",
    "paragraph", "problem", "proves", "reality", "service", "specific",
    "story", "that", "their", "this", "tradeoff", "unit", "where", "with",
}


def _story_uniqueness_terms(machine: str, text: str) -> set[str]:
    """Token signature for catching duplicated unit engineering stories."""
    raw = str(text or "").lower()
    machine_tokens = set(re.findall(r"[a-z0-9]+", str(machine or "").lower()))
    machine_code = _normalized_unit_code(machine).lower()
    raw = raw.replace(machine_code, " ")
    tokens = re.findall(r"[a-z0-9]+", raw)
    return {
        token for token in tokens
        if len(token) >= 4
        and token not in _STORY_UNIQUENESS_STOPWORDS
        and token not in machine_tokens
    }


def _roster_story_uniqueness_warnings(roster: list[str], cards_by_roster_code: dict[str, dict]) -> dict[str, list[str]]:
    """Flag repeated engineering stories across a locked DVsU roster."""
    warnings_by_code: dict[str, list[str]] = {}
    seen: list[dict] = []
    fields = (
        ("engineering_thesis", "engineering_thesis"),
        ("why_this_unit_deserves_a_paragraph", "paragraph rationale"),
    )
    for machine in roster:
        code = _normalized_unit_code(machine)
        card = cards_by_roster_code.get(code)
        if not isinstance(card, dict):
            continue
        for field_name, label in fields:
            terms = _story_uniqueness_terms(machine, str(card.get(field_name) or ""))
            if len(terms) < 5:
                continue
            for previous in seen:
                if previous["field"] != field_name:
                    continue
                previous_terms = previous["terms"]
                overlap = len(terms & previous_terms)
                if overlap < 5:
                    continue
                union = len(terms | previous_terms)
                min_size = min(len(terms), len(previous_terms))
                jaccard = overlap / union if union else 0
                containment = overlap / min_size if min_size else 0
                if jaccard >= 0.72 or containment >= 0.86:
                    other_machine = previous["machine"]
                    warnings_by_code.setdefault(code, []).append(
                        f"{label} duplicates engineering story with {other_machine}"
                    )
                    warnings_by_code.setdefault(previous["code"], []).append(
                        f"{label} duplicates engineering story with {machine}"
                    )
            seen.append({
                "code": code,
                "machine": machine,
                "field": field_name,
                "terms": terms,
            })
    return {
        code: list(dict.fromkeys(warnings))
        for code, warnings in warnings_by_code.items()
        if warnings
    }


def _span_numeric_mentions_without_locked_designation(span: str, machine: str) -> list[dict[str, str]]:
    # LAW (2026-07-16): designations are identifiers, never numbers. Any
    # designation-shaped token is excluded from numeric mentions, so the
    # single-source softeners can never treat "XB-15" as an exact fact that
    # needs a hedge (foreign designations are policed by their own check).
    return _numeric_mentions_from_text(_strip_designations_for_numbers(span, machine))


# Shared hedge lexicon (LAW 2026-07-16): ONE list for the two-source gate, the
# high-risk-fact detector, the single-source softener, and the build/repair
# prompts. A quantity introduced with any of these reads as approximate, so it
# does not require two independent sources. XB-15 live: the model hedged with
# "approaching" and the gate did not recognize it.
_HEDGE_WORDS = (
    "about", "almost", "approaching", "approximately", "around", "at least",
    "between", "claimed", "close to", "estimated", "more than", "nearly",
    "on the order of", "over", "roughly", "some", "up to",
)
_HEDGE_WORDS_RE = re.compile(r"\b(?:" + "|".join(_HEDGE_WORDS) + r")\b")


def _span_has_high_risk_exact_fact(span: str, machine: str) -> bool:
    lowered = str(span or "").lower()
    if _HEDGE_WORDS_RE.search(lowered):
        return False
    if _span_numeric_mentions_without_locked_designation(span, machine):
        return True
    return bool(re.search(r"\b(first|only|largest|fastest|most|never)\b", lowered))


def _capitalize_sentence_starts(text: str) -> str:
    return re.sub(
        r"(^|[.!?]\s+)([a-z])",
        lambda match: match.group(1) + match.group(2).upper(),
        str(text or ""),
    )


def _remove_unsupported_never_clause(text: str) -> str:
    updated = str(text or "")
    updated = re.sub(
        r"\b(?:it|the aircraft|the bomber|the machine|the prototype)\s+never saw combat,\s*yet\s*",
        "",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(r"\bnever saw combat,\s*yet\s*", "", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\bnever\b", "did not", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\s+([,.;:!?])", r"\1", updated)
    updated = re.sub(r"\s{2,}", " ", updated).strip()
    return _capitalize_sentence_starts(updated)


# Writer pass 5 (2026-07-16): the digits-for-years law is enforced
# mechanically. The writer keeps spelling years and decades ("nineteen
# thirties", "nineteen thirty-five"), which the number gate then reads as
# unsupported quantities (B-17, twice). Years are calendar identifiers - they
# stay digits, and the repair layer converts spelled forms back.
_SPELLED_CENTURIES = {"eighteen": 18, "nineteen": 19, "twenty": 20}
_SPELLED_YEAR_TENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SPELLED_YEAR_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_SPELLED_DECADE_TENS = {
    "twenties": 20, "thirties": 30, "forties": 40, "fifties": 50,
    "sixties": 60, "seventies": 70, "eighties": 80, "nineties": 90,
}
_SPELLED_DECADE_RE = re.compile(
    r"\b(eighteen|nineteen|twenty)[ -](" + "|".join(_SPELLED_DECADE_TENS) + r")\b",
    re.IGNORECASE,
)
_SPELLED_YEAR_RE = re.compile(
    r"\b(eighteen|nineteen|twenty)[ -](" + "|".join(_SPELLED_YEAR_TENS) + r")"
    r"(?:[ -](" + "|".join(_SPELLED_YEAR_ONES) + r"))?\b",
    re.IGNORECASE,
)


def _normalize_spelled_years(text: str) -> str:
    """Convert spelled years/decades back to the digit forms the voiceover
    law demands ("nineteen thirties" -> 1930s, "nineteen thirty-five" -> 1935)."""
    updated = str(text or "")
    updated = _SPELLED_DECADE_RE.sub(
        lambda m: f"{_SPELLED_CENTURIES[m.group(1).lower()] * 100 + _SPELLED_DECADE_TENS[m.group(2).lower()]}s",
        updated,
    )
    updated = _SPELLED_YEAR_RE.sub(
        lambda m: str(
            _SPELLED_CENTURIES[m.group(1).lower()] * 100
            + _SPELLED_YEAR_TENS[m.group(2).lower()]
            + (_SPELLED_YEAR_ONES[m.group(3).lower()] if m.group(3) else 0)
        ),
        updated,
    )
    return updated


def _span_two_source_starved_number_keys(
    span: str, machine: str, evidence_by_id: dict
) -> set[str]:
    """Number mentions in an UNHEDGED span that the validator's two-source
    scan will block: sourced in exactly ONE distinct source across ALL locked
    evidence (year-like keys exempt, designations already stripped). Mirrors
    the _validate_machine_story_sentences rule so the repair layer hedges
    exactly what the frozen gate would flag."""
    if _HEDGE_WORDS_RE.search(str(span or "").lower()):
        return set()
    starved: set[str] = set()
    for mention in _span_numeric_mentions_without_locked_designation(span, machine):
        key = mention.get("key")
        if not key or key in starved or _is_year_like_key(key):
            continue
        supporting = {
            str(
                segment.get("source_url")
                or segment.get("source_id")
                or segment.get("locator")
                or ""
            ).strip()
            for segment in evidence_by_id.values()
            if key in {
                _numeric_token_key(token)
                for token in (segment.get("numeric_tokens") or [])
            }
        }
        supporting = {source for source in supporting if source}
        # Exactly one source: a hedge legalizes it. Zero sources: the number
        # is unsupported either way and belongs to the rebuild prompt.
        if len(supporting) == 1:
            starved.add(str(key))
    return starved


def _hedge_starved_number_mentions(span: str, machine: str, starved_keys: set) -> str:
    """Insert one legal hedge before the first single-source number phrase.
    `roughly` reads naturally even after articles ("a roughly five-thousand-mile
    range"); one hedge marks the whole span as hedged for the gate."""
    updated = str(span or "")
    if not starved_keys or _HEDGE_WORDS_RE.search(updated.lower()):
        return updated
    for mention in _span_numeric_mentions_without_locked_designation(updated, machine):
        if str(mention.get("key") or "") not in starved_keys:
            continue
        raw = str(mention.get("raw") or "").strip()
        if not raw:
            continue
        # Mentions come back space-joined even when the span hyphenates
        # ("five-thousand-mile"), so match across spaces and hyphens.
        pattern = re.compile(
            r"(?<![A-Za-z0-9-])" + r"[\s-]+".join(re.escape(part) for part in raw.split()),
            re.IGNORECASE,
        )
        match = pattern.search(updated)
        if match:
            return updated[:match.start()] + "roughly " + updated[match.start():]
    return updated


def _soften_single_source_span(span: str, machine: str) -> str:
    """Make single-source exact claims less brittle without adding facts."""
    updated = _remove_unsupported_never_clause(str(span or ""))
    updated = re.sub(r"\bOnly one\b", "A single", updated)
    updated = re.sub(r"\bonly one\b", "a single", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\bA single was built\b", "A single example was built", updated)
    updated = re.sub(r"\ba single was built\b", "a single example was built", updated, flags=re.IGNORECASE)
    updated = re.sub(
        r"\bone\s+(?=(?:[A-Z]{1,4}-?\d{1,4}[A-Z]?|prototype|aircraft|machine|bomber|example|unit)\b)",
        "a single ",
        updated,
        count=1,
        flags=re.IGNORECASE,
    )
    updated = re.sub(r"\bfirst flew in\s+((?:18|19|20)\d{2})\b", r"flew around \1", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\bfirst flight in\s+((?:18|19|20)\d{2})\b", r"flight around \1", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\bworld['’]s largest\b", "unusually large", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\bthe largest\b", "a large", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\blargest\b", "large", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\bfastest\b", "fast", updated, flags=re.IGNORECASE)
    # Writer pass 5: soften a determiner-guarded ordinal "first" ("its first
    # bombing mission" -> "its early bombing mission"). The guard keeps verb
    # phrases ("first flew ...") for the dedicated rules above.
    updated = re.sub(
        r"\b(its|the|their|a|his|her)\s+first\b",
        r"\1 early",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(r"\bnever\b", "did not", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\bonly\b\s*", "", updated, flags=re.IGNORECASE)
    if _span_numeric_mentions_without_locked_designation(updated, machine) and not _HEDGE_WORDS_RE.search(
        updated.lower()
    ):
        softened = re.sub(
            r"\bin\s+the early\s+((?:18|19|20)\d{2}s)\b",
            r"around the early \1",
            updated,
            count=1,
            flags=re.IGNORECASE,
        )
        if softened == updated:
            softened = re.sub(
                r"\bthe early\s+((?:18|19|20)\d{2}s)\b",
                r"around the early \1",
                updated,
                count=1,
                flags=re.IGNORECASE,
            )
        if softened == updated:
            softened = re.sub(
                r"\bin\s+((?:18|19|20)\d{2})\b",
                r"around \1",
                updated,
                count=1,
                flags=re.IGNORECASE,
            )
        if softened == updated:
            # LAW (2026-07-16): never hedge a designation's digits. The old
            # lookbehind allowed digits after a hyphen (or mid-number), which
            # turned "XB-15" into "XB-about 15" on live XB-15 previews.
            # Writer pass 5: model/type numbers are NAMES too - "Model 299"
            # must never become "Model about 299" (live B-17 artifact).
            for digit_match in re.finditer(
                r"(?<![A-Za-z0-9-])(\d+(?:[,.]\d+)*(?:%|st|nd|rd|th|s)?)", updated
            ):
                preceding = updated[:digit_match.start()].rstrip()
                preceding_word = preceding.rsplit(None, 1)[-1].lower() if preceding else ""
                if preceding_word in {"model", "type", "mark", "mk", "mk."}:
                    continue
                softened = (
                    updated[:digit_match.start()] + "about " + updated[digit_match.start():]
                )
                break
        updated = softened
    updated = re.sub(r"\s+([,.;:!?])", r"\1", updated)
    updated = re.sub(r"\s{2,}", " ", updated).strip()
    return updated


def _assemble_story_paragraph_from_sentences(bundle: dict) -> dict:
    """LAW (2026-07-16): paragraph assembly is CODE-OWNED.

    The model authors formula_sentences only; re-typing them into a separate
    paragraph string is clerical work it does badly (XB-15: mangled
    designation "XB-about 15", paraphrased clauses). Whenever the bundle
    carries formula_sentences, the paragraph IS their space-join and the
    model's own paragraph string is ignored. Legacy bundles without sentences
    keep their paragraph as a fallback."""
    if not isinstance(bundle, dict):
        return bundle
    formula_sentences = bundle.get("formula_sentences")
    if not isinstance(formula_sentences, list):
        return bundle
    sentences = [" ".join(str(item or "").split()) for item in formula_sentences if str(item or "").strip()]
    if sentences:
        bundle["formula_sentences"] = sentences
        bundle["paragraph"] = " ".join(sentences)
    return bundle


def _resplit_story_sentences(paragraph: str) -> list[str]:
    """Re-derive formula_sentences after a code edit to the assembled paragraph."""
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", str(paragraph or "").strip()) if part.strip()]


def _repair_machine_story_bundle_mechanics(machine: str, plan: dict, bundle: dict) -> dict:
    """Fix mechanical JSON-bundle failures without loosening source validation."""
    if not isinstance(bundle, dict):
        return bundle
    bundle = _assemble_story_paragraph_from_sentences(bundle)
    paragraph = " ".join(str(bundle.get("paragraph") or "").split())
    claim_rows = bundle.get("claim_map")
    if not paragraph or not isinstance(claim_rows, list):
        return bundle

    evidence_by_id: dict[str, dict] = {}
    role_by_id: dict[str, str] = {}
    for slot in (plan.get("slots") if isinstance(plan, dict) else []) or []:
        if not isinstance(slot, dict):
            continue
        role = str(slot.get("slot") or "")
        for segment in slot.get("evidence_segments", []) or []:
            if not isinstance(segment, dict):
                continue
            evidence_id = str(segment.get("evidence_id") or "").strip()
            if evidence_id:
                evidence_by_id[evidence_id] = segment
                # First-wins: shared support-slot segments keep narrative roles.
                role_by_id.setdefault(evidence_id, role)

    repaired_rows: list[dict] = []
    repaired_paragraph = paragraph
    for row in claim_rows:
        if not isinstance(row, dict):
            repaired_rows.append(row)
            continue
        repaired = dict(row)
        row_ids_raw = repaired.get("used_evidence_ids") or repaired.get("evidence_ids")
        row_ids = [str(item) for item in row_ids_raw if str(item).strip()] if isinstance(row_ids_raw, list) else []
        row_roles = {role_by_id[item] for item in row_ids if item in role_by_id}
        if len(row_roles) == 1:
            repaired["slot"] = next(iter(row_roles))
        span = " ".join(str(repaired.get("span") or repaired.get("text") or repaired.get("claim") or "").split())
        # Writer pass 5: spelled years/decades revert to digits BEFORE the
        # number checks, so "nineteen thirties" never grades as a quantity.
        if span:
            normalized_span = _normalize_spelled_years(span)
            if normalized_span != span and span in repaired_paragraph:
                repaired_paragraph = repaired_paragraph.replace(span, normalized_span, 1)
                repaired["span"] = normalized_span
                span = normalized_span
        if span and row_ids:
            row_evidence_text = " ".join(
                f"{evidence_by_id.get(evidence_id, {}).get('claim', '')} {evidence_by_id.get(evidence_id, {}).get('source_excerpt', '')}"
                for evidence_id in row_ids
                if evidence_id in evidence_by_id
            ).lower()
            unsupported_risk_terms = [
                term for term in ("first", "only", "largest", "fastest", "most", "never")
                if re.search(rf"\b{term}\b", span.lower()) and not re.search(rf"\b{term}\b", row_evidence_text)
            ]
            source_keys = {
                str(evidence_by_id.get(evidence_id, {}).get("source_url") or evidence_by_id.get(evidence_id, {}).get("locator") or "").strip()
                for evidence_id in row_ids
                if evidence_id in evidence_by_id
            }
            source_keys = {source for source in source_keys if source}
            # Writer pass 5: grade numbers the way the gate does - per number
            # against ALL locked evidence - not per row citation.
            starved_number_keys = _span_two_source_starved_number_keys(span, machine, evidence_by_id)
            if unsupported_risk_terms or starved_number_keys or (
                len(source_keys) < 2 and _span_has_high_risk_exact_fact(span, machine)
            ):
                softened = _soften_single_source_span(span, machine)
                if starved_number_keys:
                    softened = _hedge_starved_number_mentions(softened, machine, starved_number_keys)
                if softened and softened != span and span in repaired_paragraph:
                    repaired_paragraph = repaired_paragraph.replace(span, softened, 1)
                    repaired["span"] = softened
        repaired_rows.append(repaired)

    # Writer pass 5: citation hygiene for formula order. The writer blends a
    # neighboring required slot's id into a sentence it already grounds with
    # the expected slot; the frozen order gate then reads the sentence as
    # out-of-order. Dropping the wrong-slot citation is provenance metadata
    # only (word/number grounding is graded plan-wide) and enforces the gate's
    # own "span cites only its real source slot" law. Never drops a row's
    # last id and never touches a sentence missing its expected role.
    formula_roles = ("original_problem", "engineering_decision", "tradeoff", "reality")
    sentence_parts = _resplit_story_sentences(repaired_paragraph)
    rows_by_sentence: dict[int, list[dict]] = {}
    for row in repaired_rows:
        if not isinstance(row, dict):
            continue
        row_span = " ".join(str(row.get("span") or "").split())
        if not row_span:
            continue
        sentence_index = next(
            (
                idx for idx, sentence in enumerate(sentence_parts, start=1)
                if row_span == sentence or row_span in sentence
            ),
            None,
        )
        if sentence_index and sentence_index <= len(formula_roles):
            rows_by_sentence.setdefault(sentence_index, []).append(row)
    for sentence_index, sentence_rows in rows_by_sentence.items():
        expected_role = formula_roles[sentence_index - 1]
        cited_roles = {
            role_by_id.get(str(item))
            for row in sentence_rows
            for item in (row.get("used_evidence_ids") or row.get("evidence_ids") or [])
        }
        misplaced_roles = {
            role for role in cited_roles
            if role in _ANTON_REQUIRED_SLOT_ROLES and role != expected_role
        }
        if expected_role not in cited_roles or not misplaced_roles:
            continue
        for row in sentence_rows:
            ids_key = "used_evidence_ids" if isinstance(row.get("used_evidence_ids"), list) else (
                "evidence_ids" if isinstance(row.get("evidence_ids"), list) else None
            )
            if not ids_key:
                continue
            row_ids = [str(item) for item in row[ids_key] if str(item).strip()]
            kept = [item for item in row_ids if role_by_id.get(item) not in misplaced_roles]
            if kept and len(kept) < len(row_ids):
                row[ids_key] = kept
                kept_roles = {role_by_id[item] for item in kept if item in role_by_id}
                if len(kept_roles) == 1:
                    row["slot"] = next(iter(kept_roles))

    # Catch spelled years the claim map never covered (rows already normalized
    # in place, so this only touches text outside the mapped spans).
    repaired_paragraph = _normalize_spelled_years(repaired_paragraph)

    all_evidence_text = " ".join(
        f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
        for segment in evidence_by_id.values()
    ).lower()
    if re.search(r"\bnever\b", repaired_paragraph.lower()) and not re.search(r"\bnever\b", all_evidence_text):
        cleaned_paragraph = _remove_unsupported_never_clause(repaired_paragraph)
        if cleaned_paragraph != repaired_paragraph:
            cleaned_rows: list[dict] = []
            for row in repaired_rows:
                if not isinstance(row, dict):
                    cleaned_rows.append(row)
                    continue
                span = " ".join(str(row.get("span") or row.get("text") or row.get("claim") or "").split())
                if span and re.search(r"\bnever\b", span.lower()):
                    cleaned_span = _remove_unsupported_never_clause(span)
                    if cleaned_span and cleaned_span in cleaned_paragraph:
                        row = dict(row)
                        row["span"] = cleaned_span
                        cleaned_rows.append(row)
                    continue
                cleaned_rows.append(row)
            repaired_rows = cleaned_rows
            repaired_paragraph = cleaned_paragraph

    repaired_bundle = dict(bundle)
    repaired_bundle["paragraph"] = repaired_paragraph
    repaired_bundle["claim_map"] = repaired_rows
    # Keep the code-owned invariant paragraph == join(formula_sentences) after
    # in-place span edits (softening never adds or removes sentence boundaries).
    if repaired_paragraph != paragraph and bundle.get("formula_sentences"):
        repaired_bundle["formula_sentences"] = _resplit_story_sentences(repaired_paragraph)
    return repaired_bundle


def _trim_machine_story_bundle_to_contract(machine: str, plan: dict, bundle: dict) -> dict:
    """Drop optional-only sentences when a valid story bundle overruns Anton length."""
    if not isinstance(bundle, dict):
        return bundle
    bundle = _assemble_story_paragraph_from_sentences(bundle)
    paragraph = " ".join(str(bundle.get("paragraph") or "").split())
    claim_rows = bundle.get("claim_map")
    if _spoken_word_count(paragraph) <= 120 or not isinstance(claim_rows, list):
        return bundle
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
    if len(sentences) <= 4:
        return bundle
    normalized_rows = [dict(row) for row in claim_rows if isinstance(row, dict)]

    candidates: list[tuple[int, int, str, list[dict]]] = []
    for index, sentence in enumerate(sentences):
        sentence_rows = [
            row for row in normalized_rows
            if " ".join(str(row.get("span") or row.get("text") or row.get("claim") or "").split()) in sentence
        ]
        if not sentence_rows:
            continue
        row_roles = {
            str(row.get("slot") or row.get("slot_role") or "").strip()
            for row in sentence_rows
        }
        if not row_roles or any(role in _ANTON_REQUIRED_SLOT_ROLES for role in row_roles):
            continue
        kept_sentences = [item for item_index, item in enumerate(sentences) if item_index != index]
        trimmed_paragraph = " ".join(kept_sentences)
        trimmed_wc = _spoken_word_count(trimmed_paragraph)
        if trimmed_wc < 95 or trimmed_wc > 120:
            continue
        sentence_spans = {
            " ".join(str(row.get("span") or row.get("text") or row.get("claim") or "").split())
            for row in sentence_rows
        }
        kept_rows = [
            row for row in normalized_rows
            if " ".join(str(row.get("span") or row.get("text") or row.get("claim") or "").split()) not in sentence_spans
        ]
        candidates.append((_spoken_word_count(sentence), index, trimmed_paragraph, kept_rows))

    if not candidates:
        return bundle
    _, _, trimmed_paragraph, kept_rows = sorted(candidates, reverse=True)[0]
    trimmed_bundle = dict(bundle)
    trimmed_bundle["paragraph"] = trimmed_paragraph
    trimmed_bundle["claim_map"] = kept_rows
    # Keep the code-owned invariant paragraph == join(formula_sentences).
    if bundle.get("formula_sentences"):
        trimmed_bundle["formula_sentences"] = _resplit_story_sentences(trimmed_paragraph)
    return trimmed_bundle


# Function/quantifier glue for script-stage word grounding (LAW 2026-07-16):
# connective, quantifier, and epistemic-hedge words the narration needs that
# carry no checkable fact. Every single-word token of the shared _HEDGE_WORDS
# lexicon is here so an accepted hedge can never self-flag as an unsupported
# word ("approaching" did, live on XB-15). Real factual nouns stay strict
# (e.g. "giant" still needs grounded vocabulary - the evidence offers
# "mammoth"). Explicit inflections included because the grounding stemmer does
# not fold every form ("carried" -> "carri").
_SCRIPT_GLUE_STOPWORDS = {
    "almost", "approaching", "approximately", "close", "estimated", "even",
    "least", "nearly", "order", "roughly", "some", "up", "whether",
    "build", "builds", "building", "built",
    "carry", "carries", "carrying", "carried",
    "over", "single", "such", "where", "year", "years",
}


def _classify_opener_type(paragraph: str, machine: str) -> str:
    """QL-7: classify how an entry opens, for the name-opener budget.

    Types mirror the corpus analysis: bare name-opener ("The [Maker]
    [Designation]..."), bridge (chains from another machine/era), date/era
    context, count-fragment, role/thesis claim, other."""
    import re as _re

    first_sentence = ""
    for part in _re.split(r"(?<=[.!?])\s+", str(paragraph or "").strip()):
        if part.strip():
            first_sentence = part.strip()
            break
    if not first_sentence:
        return "other"
    head = " ".join(first_sentence.split()[:8])
    head_lower = head.lower()
    machine_words = [word for word in _unit_display_name(machine).split() if word]
    machine_head = " ".join(machine_words[:2]).lower()
    stripped = _re.sub(r"^(?:the|a|an)\s+", "", head_lower)
    # Bridge: opens by chaining (connective word, or a different designation
    # inside the opening words).
    bridge_starts = ("while ", "after ", "when ", "where ", "alongside ", "unlike ", "from the ", "as the ", "then ")
    machine_codes = _target_machine_designation_codes(machine)
    foreign_designation = any(
        _normalized_unit_code(token) not in machine_codes
        for token in _AIRCRAFT_DESIGNATION_RE.findall(head.upper())
        if _normalized_unit_code(token)
    )
    if head_lower.startswith(bridge_starts) or foreign_designation:
        return "bridge"
    # Date/era context: a year or era phrase in the opening words.
    if _re.search(r"\b(1[6-9]\d{2}|20\d{2})s?\b", head) or head_lower.startswith(("in the ", "by the ", "by ", "in ")):
        return "date_era"
    # Count-fragment: opens on a number word (crew-register cold symptom).
    first_word = head_lower.split()[0] if head_lower.split() else ""
    if first_word in _NUMBER_WORD_VOCABULARY or _re.match(r"^\d", first_word):
        return "count_fragment"
    # Bare name-opener: "The [Maker] [Designation] ..." (locked machine first).
    if machine_head and stripped.startswith(machine_head):
        return "name"
    if any(_normalized_unit_code(token) in machine_codes for token in _AIRCRAFT_DESIGNATION_RE.findall(head.upper())):
        return "name"
    # Role/thesis claim: opens on a role noun phrase or possessive thesis.
    if _re.match(r"^(?:america|britain|russia|germany|japan)", stripped) or stripped.startswith(("its ", "it was", "this was", "here was")):
        return "role_thesis"
    return "other"


def _checkable_fact_words(text: str) -> set[str]:
    """QD-2 (approved): grounding is HARD only for checkable facts.

    Checkable = proper nouns (capitalized mid-sentence tokens: places, people,
    programs, operators) and calendar-month words. Numbers, dates, and
    designations are policed by their own checks. Everything else - abstract
    nouns, common verbs, adjectives - is free vocabulary; colorful concrete
    nouns are warn-only. Returns the lowercase word set that must ground."""
    import re as _re

    checkable: set[str] = set()
    for match in _re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})\b", str(text or "")):
        checkable.add(match.group(1).lower())
    lower = str(text or "").lower()
    for month in _MONTH_NAMES:
        if _re.search(rf"\b{month}\b", lower):
            checkable.add(month)
    return checkable


def _is_year_like_key(key: Any) -> bool:
    """QD-4 (approved): exact dates are identity facts - single source suffices."""
    import re as _re
    return bool(_re.fullmatch(r"(1[6-9]\d{2}|20\d{2})s?", str(key or "")))


# QD-1 (approved 2026-07-16) removed the closer word-novelty check entirely:
# the final sentence has vocabulary freedom, and only the banned classes (new
# named entities, numbers, designations, high-risk claims) are gated. The old
# _final_sentence_novel_words helper is gone with it.


def _validate_machine_story_sentences(
    machine: str, plan: dict, bundle: dict, rule_overrides: Optional[dict] = None,
) -> tuple[str, list[str]]:
    """Validate one Anton-style paragraph against sourced slot evidence.

    ``rule_overrides`` (checklist C46c): a tenant's resolved DvsU delta
    overrides (``quality_rules.resolve_dvsu_overrides``) — forwarded into the
    twist-gate (D2/QL-3), twist-menu (D3/QL-4), and the nested word-floor/
    hype (QL-1/QL-12) checks inside ``_validate_static_unit_paragraph``. None
    (the default) is exactly pre-C46c behavior."""
    import re

    rule_overrides = rule_overrides or {}
    warnings: list[str] = []
    if not isinstance(bundle, dict):
        return "", ["story distiller must return a JSON object"]
    parse_error = " ".join(str(bundle.get("_parse_error") or "").split())
    if parse_error:
        warnings.append(parse_error)
    parse_warnings = bundle.get("_parse_warnings") if isinstance(bundle, dict) else None
    if isinstance(parse_warnings, list):
        warnings.extend(str(item) for item in parse_warnings if str(item).strip())
    # LAW (2026-07-16): the paragraph graded here (and every claim_map span
    # check below) is the CODE-ASSEMBLED join of formula_sentences whenever
    # sentences exist; the model's re-typed paragraph string is ignored.
    bundle = _assemble_story_paragraph_from_sentences(bundle)
    paragraph = " ".join(str(bundle.get("paragraph") or "").split())
    if not paragraph:
        warnings.append("story distiller must return a paragraph string")
        return "", list(dict.fromkeys(warnings))
    formula_sentences = bundle.get("formula_sentences")
    if not isinstance(formula_sentences, list):
        formula_sentences = []
    formula_sentences = [" ".join(str(item or "").split()) for item in formula_sentences if str(item or "").strip()]
    sentence_parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if part.strip()]
    sentence_count = len(sentence_parts)
    opening_assignment = str(((plan.get("contract") or {}) if isinstance(plan, dict) else {}).get("opening_assignment") or "")
    warnings.extend(_opening_assignment_warnings(machine, paragraph, opening_assignment))
    narrative_warning = _narrative_weight_target_warning(paragraph, plan)
    if narrative_warning:
        warnings.append(narrative_warning)

    # QD-5 (approved): editorial_thesis is graded warn-only, never blocking.
    editorial_thesis = " ".join(str(bundle.get("editorial_thesis") or "").split())
    if not editorial_thesis:
        warnings.append(_ADVISORY_PREFIX + "story distiller must declare editorial_thesis for the machine's engineering decision or contrast")
    else:
        thesis_wc = _spoken_word_count(editorial_thesis)
        thesis_lower = editorial_thesis.lower()
        if thesis_wc < 6 or thesis_wc > 26:
            warnings.append(_ADVISORY_PREFIX + f"editorial_thesis word count {thesis_wc} outside 6-26 range")
        if re.search(r"\b(?:this|the)\s+(?:machine|aircraft|unit)\s+(?:mattered|was important|was significant)\b", thesis_lower):
            warnings.append(_ADVISORY_PREFIX + "editorial_thesis is generic; name the specific engineering decision, tradeoff, or contrast")
        if not re.search(
            r"\b(?:because|but|despite|instead|rather|decision|chose|choice|balanced|trade|traded|tradeoff|tension|contrast|proved|validated|failed|solved|created|answered|sacrificed|compromise|consequence|outpaced|survived|needed)\b",
            thesis_lower,
        ):
            warnings.append(_ADVISORY_PREFIX + "editorial_thesis must state a concrete engineering decision, tradeoff, or contrast")

    # QL-3 (OR-1 approved, HARD) + QL-4 (OR-3 approved): every entry declares
    # its designed-vs-used twist from the expanded menu; a machine used exactly
    # as designed ("absent") MUST name a substitute payload. The deliberately-
    # bare tag is the only exemption.
    # Checklist C46c: severity/menu are TABLE-DRIVEN when a QL-3/QL-4 row is
    # seeded (quality_rules.resolve_dvsu_overrides); absent -> today's
    # hardcoded hard-gate severity and 16-type menu, byte-identical.
    deliberately_bare = bool(((plan.get("contract") or {}) if isinstance(plan, dict) else {}).get("deliberately_bare"))
    twist_gate_override = rule_overrides.get("twist_gate") or {}
    twist_gate_blocking = twist_gate_override.get("severity", "hard_gate") == "hard_gate"
    twist_gate_prefix = "" if twist_gate_blocking else _ADVISORY_PREFIX
    twist_menu_override = rule_overrides.get("twist_menu") or {}
    twist_menu = tuple(twist_menu_override.get("types") or ()) or _DVSU_TWIST_TYPES
    twist_menu_blocking = twist_menu_override.get("severity", "guidance") == "hard_gate"
    twist = bundle.get("twist") if isinstance(bundle.get("twist"), dict) else {}
    twist_type = str(twist.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
    twist_substitute = str(twist.get("substitute") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not deliberately_bare:
        if not twist_type:
            warnings.append(
                twist_gate_prefix + "entry declares no designed-vs-used twist - built for X, used as Y is the engine; "
                "declare twist.type from the menu or tag the entry deliberately bare"
            )
        elif twist_type == "absent":
            if twist_substitute not in _DVSU_TWIST_SUBSTITUTES:
                warnings.append(
                    twist_gate_prefix + "no gap and no substitute - reads as a spec dump; a used-as-designed entry must "
                    "substitute one of: " + ", ".join(_DVSU_TWIST_SUBSTITUTES)
                )
        elif twist_type != "other" and twist_type not in twist_menu:
            warnings.append(
                ("" if twist_menu_blocking else _ADVISORY_PREFIX)
                + f"twist type `{twist_type}` is not on the menu - pick the closest named subtype "
                "(counted as `other` for the script-run budget)"
            )

    evidence_by_id: dict[str, dict] = {}
    role_by_id: dict[str, str] = {}
    for slot in plan.get("slots", []):
        role = str(slot.get("slot") or "")
        if slot.get("required") and not slot.get("evidence_ids"):
            warnings.append(f"locked story plan missing required Anton slot evidence: {role}")
        for segment in slot.get("evidence_segments", []) or []:
            if not isinstance(segment, dict):
                continue
            evidence_id = str(segment.get("evidence_id") or "")
            if evidence_id:
                evidence_by_id[evidence_id] = segment
                # First-wins: shared support-slot segments keep narrative roles.
                role_by_id.setdefault(evidence_id, role)
    # LAW (2026-07-16): per-row WORD grounding is graded against ALL locked
    # story-plan evidence (same scope ruling as the two-source number check);
    # row citations stay provenance. "prototype" grounded by an uncited
    # onscreen_label segment is still grounded.
    all_locked_evidence_text = " ".join(
        f"{segment.get('claim', '')} {segment.get('source_excerpt', '')}"
        for segment in evidence_by_id.values()
    )
    # QL-19/QD-2: numbers are claims too - graded against ALL locked evidence.
    all_locked_number_keys = {
        _numeric_token_key(token)
        for segment in evidence_by_id.values()
        for token in (segment.get("numeric_tokens") or [])
    }
    all_locked_number_values = set()
    for key in all_locked_number_keys:
        try:
            all_locked_number_values.add(float(str(key).replace(",", "")))
        except (TypeError, ValueError):
            continue

    def _hedged_round_of_sourced_value(mention_key: str, span_lower: str) -> bool:
        """QD-3 + I3 (recalibrated 2026-07-16): a hedged round is legal only
        when DIRECTION-consistent with the NEAREST sourced value.

        - over / more than / at least: the sourced value must sit at or above
          the stated round ("over eight thousand" is true of a sourced 8,200).
        - under / up to / nearly / almost / close to / approaching: the sourced
          value must sit at or below the stated round.
        - about / around / approximately / roughly / some / estimated /
          claimed / on the order of: within +/-20 percent.
        Matching runs against the NEAREST sourced number only, and never
        across magnitudes (nearest must sit within 2x either way), so a round
        can never borrow support from an unrelated figure."""
        try:
            value = float(str(mention_key).replace(",", ""))
        except (TypeError, ValueError):
            return False
        if value <= 0 or not all_locked_number_values:
            return False
        nearest = min(all_locked_number_values, key=lambda sourced: abs(sourced - value))
        if nearest <= 0 or not (0.5 <= value / nearest <= 2.0):
            return False
        import re as _re_hedge
        def _has(*phrases: str) -> bool:
            return any(_re_hedge.search(rf"\b{phrase}\b", span_lower) for phrase in phrases)
        if _has("over", "more than", "at least") and nearest >= value:
            return True
        if _has("under", "up to", "nearly", "almost", "close to", "approaching") and nearest <= value:
            return True
        if _has("about", "around", "approximately", "roughly", "some", "estimated", "claimed", "on the order of") and 0.8 <= value / nearest <= 1.2:
            return True
        return False

    plan_supplies_evidence = bool(evidence_by_id)
    claim_rows = bundle.get("claim_map")
    if not isinstance(claim_rows, list) or not claim_rows:
        if plan_supplies_evidence:
            warnings.append("paragraph must include a non-empty claim_map")
        claim_rows = []
    used_ids: list[str] = []
    claim_span_details: list[dict[str, Any]] = []
    hedged_rounded_keys: set[str] = set()
    high_risk_terms = {"first", "only", "largest", "fastest", "most", "never"}
    for index, row in enumerate(claim_rows, start=1):
        if not isinstance(row, dict):
            warnings.append(f"claim_map row {index} must be an object")
            continue
        span = " ".join(str(row.get("span") or row.get("text") or row.get("claim") or "").split())
        if not span:
            warnings.append(f"claim_map row {index} missing span")
        elif span not in paragraph:
            warnings.append(f"claim_map row {index} span is not present in paragraph")
        elif sentence_parts:
            span_sentence_indexes = [
                sentence_index
                for sentence_index, sentence in enumerate(sentence_parts, start=1)
                if span == sentence or span in sentence
            ]
            broad_sentence_indexes = [
                sentence_index
                for sentence_index, sentence in enumerate(sentence_parts, start=1)
                if sentence and sentence in span and span != sentence
            ]
            if len(span_sentence_indexes) != 1 or broad_sentence_indexes:
                warnings.append(f"claim_map row {index} must map inside one formula sentence")
        row_ids_raw = row.get("used_evidence_ids") or row.get("evidence_ids")
        if not isinstance(row_ids_raw, list) or not row_ids_raw:
            warnings.append(f"claim_map row {index} must declare used_evidence_ids")
            row_ids: list[str] = []
        else:
            row_ids = [str(item) for item in row_ids_raw if str(item).strip()]
        row_unknown = [item for item in row_ids if item not in evidence_by_id]
        if row_unknown:
            warnings.append(f"claim_map row {index} used evidence outside the locked Anton slots: " + ", ".join(row_unknown))
        declared_slot = str(row.get("slot") or row.get("slot_role") or "").strip()
        row_slots = {role_by_id[item] for item in row_ids if item in role_by_id}
        if declared_slot and row_slots and declared_slot not in row_slots:
            warnings.append(f"claim_map row {index} declares slot {declared_slot} but uses {', '.join(sorted(row_slots))}")
        if span and row_ids:
            # LAW: designations are identifiers, never numbers.
            span_for_numbers = _strip_designations_for_numbers(span, machine)
            row_mentions = _numeric_mentions_from_text(span_for_numbers)
            row_evidence_text = " ".join(
                f"{evidence_by_id.get(evidence_id, {}).get('claim', '')} {evidence_by_id.get(evidence_id, {}).get('source_excerpt', '')}"
                for evidence_id in row_ids
                if evidence_id in evidence_by_id
            )
            span_lower = span.lower()
            hedged = bool(_HEDGE_WORDS_RE.search(span_lower))
            if all_locked_evidence_text:
                # QD-2 (approved): HARD grounding only for checkable facts
                # (proper nouns, month words); the rest of the vocabulary is
                # free, with colorful concrete nouns warn-only.
                ungrounded = _ungrounded_factual_words(
                    span,
                    all_locked_evidence_text,
                    machine,
                    extra_stopwords=_SCRIPT_GLUE_STOPWORDS,
                )
                checkable = _checkable_fact_words(span)
                unsupported_facts = [word for word in ungrounded if word in checkable]
                unsupported_vocab = [word for word in ungrounded if word not in checkable]
                if unsupported_facts:
                    warnings.append(
                        f"claim_map row {index} introduced unsupported factual word(s): "
                        + ", ".join(unsupported_facts[:10])
                    )
                if unsupported_vocab:
                    warnings.append(
                        _ADVISORY_PREFIX + f"claim_map row {index} uses vocabulary outside the locked evidence "
                        "(prefer evidence wording for concrete nouns): " + ", ".join(unsupported_vocab[:10])
                    )
            span_number_keys = {mention["key"] for mention in row_mentions}
            # QL-19: numbers ground against ALL locked evidence, not only the
            # row's citations; QD-3 legalizes hedged direction-consistent rounds.
            row_unsupported_numbers: list[str] = []
            for mention in row_mentions:
                if mention["key"] in all_locked_number_keys:
                    continue
                if hedged and _hedged_round_of_sourced_value(mention["key"], span_lower):
                    hedged_rounded_keys.add(mention["key"])
                    warnings.append(
                        _ADVISORY_PREFIX + f"claim_map row {index} rounds a sourced value with a hedge: "
                        + str(mention["raw"])
                    )
                    continue
                row_unsupported_numbers.append(mention["raw"])
            if row_unsupported_numbers:
                warnings.append(
                    f"claim_map row {index} introduced unsupported numerical detail(s): "
                    + ", ".join(row_unsupported_numbers)
                )
            span_risk_terms = {
                term for term in high_risk_terms
                if re.search(rf"\b{re.escape(term)}\b", span_lower)
            }
            if row_slots:
                claim_span_details.append({
                    "span": span,
                    "roles": row_slots,
                    "number_keys": span_number_keys,
                    "risk_terms": span_risk_terms,
                    "evidence_text": row_evidence_text,
                })
            has_high_risk_term = bool(span_risk_terms)
            if row_mentions and not hedged:
                insufficient_number_sources: list[str] = []
                seen_insufficient_number_keys: set[str] = set()
                for mention in row_mentions:
                    mention_key = mention.get("key")
                    if not mention_key or mention_key in seen_insufficient_number_keys:
                        continue
                    # QD-4 (approved): exact dates are identity facts - a single
                    # locked source suffices; two-source applies to quantities.
                    if _is_year_like_key(mention_key):
                        continue
                    # LAW (2026-07-16): the two-independent-sources requirement is
                    # graded against ALL of the story plan's locked evidence
                    # segments, not only the row's cited ids (citations stay
                    # provenance). XB-15's 149-foot wingspan lives in two locked
                    # segments across different slots; the row cited only one.
                    # Independent = distinct source_url/source_id (locator only
                    # as a last resort), so two excerpts from one source never
                    # count twice.
                    supporting_sources = {
                        str(
                            segment.get("source_url")
                            or segment.get("source_id")
                            or segment.get("locator")
                            or ""
                        ).strip()
                        for segment in evidence_by_id.values()
                        if mention_key in {
                            _numeric_token_key(token)
                            for token in (segment.get("numeric_tokens") or [])
                        }
                    }
                    supporting_sources = {source for source in supporting_sources if source}
                    if len(supporting_sources) < 2:
                        insufficient_number_sources.append(str(mention.get("raw") or mention_key))
                        seen_insufficient_number_keys.add(mention_key)
                if insufficient_number_sources:
                    warnings.append(
                        f"claim_map row {index} needs two independent sources or a hedge for exact numerical detail(s): "
                        + ", ".join(insufficient_number_sources)
                    )
            if has_high_risk_term and not hedged:
                row_source_keys = {
                    str(evidence_by_id.get(evidence_id, {}).get("source_url") or evidence_by_id.get(evidence_id, {}).get("locator") or "").strip()
                    for evidence_id in row_ids
                    if evidence_id in evidence_by_id
                }
                row_source_keys = {source for source in row_source_keys if source}
                if len(row_source_keys) < 2:
                    warnings.append(
                        f"claim_map row {index} needs two independent sources or a hedge for high-risk exact term(s)"
                    )
        used_ids.extend(row_ids)
    used_ids = list(dict.fromkeys(used_ids))
    unknown_ids = [item for item in used_ids if item not in evidence_by_id]
    if unknown_ids:
        warnings.append("paragraph used evidence outside the locked Anton slots: " + ", ".join(unknown_ids))

    covered_roles = {role_by_id[item] for item in used_ids if item in role_by_id}
    memorable_ids = [
        evidence_id
        for slot in plan.get("slots", [])
        if str(slot.get("slot") or "") == "memorable_fact"
        for evidence_id in (slot.get("evidence_ids") or [])
    ]
    # QL-9 (OR-7 approved): memorable-fact stays WARN until research coverage
    # is proven; the deliberately-bare tag is exempt entirely.
    if not deliberately_bare:
        if not memorable_ids:
            warnings.append(_ADVISORY_PREFIX + "story plan missing sourced memorable_fact for Anton paragraph")
        elif not any(evidence_id in used_ids for evidence_id in memorable_ids):
            warnings.append(_ADVISORY_PREFIX + "paragraph must use sourced memorable_fact when the story plan provides one")
    reference_benchmark = plan.get("reference_benchmark") if isinstance(plan, dict) else None
    try:
        reference_order = int((reference_benchmark or {}).get("reference_order") or 0)
    except Exception:
        reference_order = 0
    human_detail_ids = [
        evidence_id
        for slot in (plan.get("slots", []) if isinstance(plan, dict) else [])
        if str(slot.get("slot") or "") == "human_detail"
        for evidence_id in (slot.get("evidence_ids") or [])
    ]
    if 1 <= reference_order <= 3 and human_detail_ids and not any(
        evidence_id in used_ids for evidence_id in human_detail_ids
    ):
        warnings.append("first-three Anton paragraph must use sourced human_detail when the story plan provides one")
    missing_required = sorted(role for role in _ANTON_REQUIRED_SLOT_ROLES if role not in covered_roles)
    if plan_supplies_evidence and missing_required:
        warnings.append("paragraph missing required Anton slot evidence: " + ", ".join(missing_required))
    if plan_supplies_evidence and len(covered_roles) < 4:
        warnings.append("paragraph must use evidence from at least four Anton slots")

    # LAW: designations are identifiers, never numbers. QL-19: paragraph
    # numbers ground against ALL locked evidence; QD-3 keeps row-accepted
    # hedged rounds legal here too.
    paragraph_numbers = _numeric_mentions_from_text(_strip_designations_for_numbers(paragraph, machine))
    unsupported_numbers = [
        mention["raw"] for mention in paragraph_numbers
        if mention["key"] not in all_locked_number_keys
        and mention["key"] not in hedged_rounded_keys
    ]
    if plan_supplies_evidence and unsupported_numbers:
        warnings.append("paragraph introduced unsupported numerical detail(s): " + ", ".join(unsupported_numbers))
    numeric_density_cap = int((plan.get("contract") or {}).get("maximum_numerical_details") or 15)
    if len(paragraph_numbers) > numeric_density_cap:
        warnings.append(f"paragraph contains {len(paragraph_numbers)} numerical details; maximum is {numeric_density_cap}")
    # QL-10 (OR-4 approved): spell what a narrator speaks; digits stay legal
    # for designations, calendar years, and exact 4-plus-digit figures. Warn-only.
    raw_digit_mentions = _raw_digit_mentions_for_voiceover(paragraph)
    if raw_digit_mentions:
        warnings.append(
            _ADVISORY_PREFIX + "paragraph uses raw numeric digit(s); write spoken numbers as words: "
            + ", ".join(raw_digit_mentions)
        )
    unit_abbreviations = _written_unit_abbreviations_for_voiceover(paragraph)
    if unit_abbreviations:
        warnings.append(
            _ADVISORY_PREFIX + "paragraph uses written unit abbreviation(s); spell out for voiceover: "
            + ", ".join(
                f"{abbr} -> {_VOICEOVER_UNIT_ABBREVIATIONS.get(abbr, 'spoken words')}"
                for abbr in unit_abbreviations
            )
        )

    allowed_designations = set(_target_machine_designation_codes(machine))
    # QL-19 scope: designations named anywhere in the LOCKED evidence (engine
    # models like J57, gun designations) are grounded facts, not leakage.
    allowed_designations.update(
        _normalized_unit_code(token)
        for token in _AIRCRAFT_DESIGNATION_RE.findall(all_locked_evidence_text.upper())
        if _normalized_unit_code(token)
    )
    allowed_evidence_text = " ".join(
        f"{evidence_by_id.get(eid, {}).get('claim', '')} {evidence_by_id.get(eid, {}).get('source_excerpt', '')}"
        for eid in used_ids
    )
    paragraph_designations = {
        _normalized_unit_code(token)
        for token in _AIRCRAFT_DESIGNATION_RE.findall(paragraph.upper())
    }
    unsupported_designations = sorted(
        token for token in paragraph_designations
        if token
        and token not in allowed_designations
        # Plural surface form of an allowed designation ("B-52s") is legal.
        and not (token.endswith("S") and token[:-1] in allowed_designations)
    )
    if plan_supplies_evidence and unsupported_designations:
        warnings.append("paragraph designation(s) not grounded in locked evidence or the locked machine: " + ", ".join(unsupported_designations))

    # Corpus recalibration (2026-07-16): trailing punch FRAGMENTS (six spoken
    # words or fewer, up to three, at the paragraph end) are punch units that
    # belong to the single conclusion slot - Anton's triads ("Eight engines.
    # Intercontinental range. The bomber that refuses to retire.") never blow
    # the sentence range or the formula.
    trailing_fragment_count = 0
    for candidate in reversed(sentence_parts):
        if trailing_fragment_count >= 3 or len(sentence_parts) - trailing_fragment_count <= 1:
            break
        if _spoken_word_count(candidate) <= 6:
            trailing_fragment_count += 1
        else:
            break
    # Folding absorbs EXTRA punch units only - it never shrinks a paragraph
    # below the five-slot formula (a normal five-sentence entry with a short
    # hammer keeps its five counted sentences).
    trailing_fragment_count = min(
        trailing_fragment_count,
        max(0, sentence_count - _ANTON_PARAGRAPH_FORMULA_SENTENCES),
    )
    effective_sentence_count = sentence_count - trailing_fragment_count
    if effective_sentence_count < _ANTON_PARAGRAPH_MIN_SENTENCES or effective_sentence_count > _ANTON_PARAGRAPH_MAX_SENTENCES:
        warnings.append(
            f"paragraph sentence count {effective_sentence_count} outside Anton {_ANTON_PARAGRAPH_SENTENCE_RANGE} range"
        )
    if effective_sentence_count != _ANTON_PARAGRAPH_FORMULA_SENTENCES:
        # Corpus recalibration: Anton runs 4-7 counted units (B-17 runs 7);
        # the five-slot formula is the design target, not a hard shape.
        warnings.append(
            _ADVISORY_PREFIX + f"paragraph runs {effective_sentence_count} counted sentences; the Anton formula target is "
            f"{_ANTON_PARAGRAPH_FORMULA} ({_ANTON_PARAGRAPH_FORMULA_SENTENCES} sentences)"
        )
    if len(formula_sentences) != _ANTON_PARAGRAPH_FORMULA_SENTENCES:
        warnings.append(
            _ADVISORY_PREFIX + f"formula_sentences carries {len(formula_sentences)} slots; the Anton formula target is "
            f"{_ANTON_PARAGRAPH_FORMULA_SENTENCES}: {_ANTON_PARAGRAPH_FORMULA}"
        )
    # No assembly-mismatch warning: the paragraph IS the code-assembled join of
    # formula_sentences (see _assemble_story_paragraph_from_sentences), so a
    # model-side mismatch is structurally impossible.
    # The CLOSER UNIT = the trailing fragments when they exist (they are the
    # punch), else the last sentence.
    closer_start_index = len(sentence_parts) - (trailing_fragment_count or (1 if sentence_parts else 0)) + 1
    closer_sentences = sentence_parts[closer_start_index - 1:] if sentence_parts else []
    last_sentence = " ".join(closer_sentences)
    final_sentence_index = len(sentence_parts)
    formula_roles = ["original_problem", "engineering_decision", "tradeoff", "reality"]
    for sentence_index, sentence in enumerate(sentence_parts, start=1):
        in_closer_unit = sentence_index >= closer_start_index
        sentence_claim_spans = [
            detail for detail in claim_span_details
            if detail.get("span") and (detail["span"] == sentence or detail["span"] in sentence)
        ]
        if in_closer_unit and sentence_claim_spans:
            warnings.append("final sentence must be paragraph-derived synthesis, not source-backed claim_map evidence")
        if not sentence_claim_spans:
            if not in_closer_unit and plan_supplies_evidence:
                warnings.append(f"sentence {sentence_index} is not covered by claim_map evidence")
            continue
        if effective_sentence_count == _ANTON_PARAGRAPH_FORMULA_SENTENCES and sentence_index <= len(formula_roles):
            sentence_roles = {
                role
                for detail in sentence_claim_spans
                for role in detail.get("roles", set())
            }
            expected_role = formula_roles[sentence_index - 1]
            if expected_role not in sentence_roles:
                warnings.append(f"sentence {sentence_index} must carry {expected_role} evidence in Anton formula order")
            unexpected_required_roles = sorted(
                role for role in sentence_roles
                if role in _ANTON_REQUIRED_SLOT_ROLES and role != expected_role
            )
            if unexpected_required_roles:
                warnings.append(
                    f"sentence {sentence_index} used out-of-order required Anton slot evidence: "
                    + ", ".join(unexpected_required_roles)
                )
        # LAW: designations are identifiers, never numbers.
        sentence_for_numbers = _strip_designations_for_numbers(sentence, machine)
        span_number_keys = {
            key
            for detail in sentence_claim_spans
            for key in detail.get("number_keys", set())
        }
        uncovered_sentence_numbers = [
            mention["raw"] for mention in _numeric_mentions_from_text(sentence_for_numbers)
            if mention["key"] not in span_number_keys
        ]
        if uncovered_sentence_numbers:
            warnings.append(
                f"sentence {sentence_index} numerical detail(s) outside claim_map span coverage: "
                + ", ".join(uncovered_sentence_numbers)
            )
        sentence_lower = sentence.lower()
        span_risk_terms = {
            term
            for detail in sentence_claim_spans
            for term in detail.get("risk_terms", set())
        }
        uncovered_risk_terms = sorted(
            term for term in high_risk_terms
            if re.search(rf"\b{re.escape(term)}\b", sentence_lower) and term not in span_risk_terms
        )
        if uncovered_risk_terms:
            warnings.append(
                f"sentence {sentence_index} high-risk term(s) outside claim_map span coverage: "
                + ", ".join(uncovered_risk_terms)
            )
        if not in_closer_unit:
            uncovered_text = sentence
            for detail in sentence_claim_spans:
                span = str(detail.get("span") or "")
                if span:
                    uncovered_text = uncovered_text.replace(span, " ", 1)
            if uncovered_text.strip():
                # LAW (2026-07-16): unmapped words are graded against ALL
                # locked evidence too (with the glue stoplist), matching the
                # row-level word-grounding scope.
                unsupported_unmapped_words = _ungrounded_factual_words(
                    uncovered_text,
                    all_locked_evidence_text,
                    machine,
                    extra_stopwords=_SCRIPT_GLUE_STOPWORDS,
                )
                if unsupported_unmapped_words:
                    warnings.append(
                        f"sentence {sentence_index} unsupported factual word(s) outside claim_map span coverage: "
                        + ", ".join(unsupported_unmapped_words[:10])
                    )
    if sentence_parts:
        # The closer unit = trailing fragments when present, else last sentence.
        prior_paragraph_text = " ".join(sentence_parts[:closer_start_index - 1])
        last_wc = _spoken_word_count(last_sentence)
        if last_wc > _ANTON_FINAL_SENTENCE_MAX_WORDS:
            warnings.append(
                f"final sentence word count {last_wc} is too long to land cleanly; "
                f"maximum is {_ANTON_FINAL_SENTENCE_MAX_WORDS}"
            )
        if re.search(
            r"\b(in conclusion|overall|to summarize|this shows that|those choices|these choices|beyond its own service)\b"
            r"|made\s+(?:the\s+)?(?:machine|aircraft|unit)\s+matter\b",
            last_sentence.lower(),
        ):
            warnings.append("final sentence uses generic summary language instead of a landed Anton line")
        # B1 (2026-07-16): the closer may reuse the body's numbers ("Eight
        # engines." echoes the body's eight turbojets). Only NEW numbers flag,
        # and a new number ALONE is advisory - it hard-blocks only when it
        # co-occurs with a new entity (see below). Designation digits never count.
        prior_number_keys = {
            mention["key"]
            for mention in _numeric_mentions_from_text(_strip_designations_for_numbers(prior_paragraph_text, machine))
        }
        final_numbers = [
            mention for mention in _numeric_mentions_from_text(_strip_designations_for_numbers(last_sentence, machine))
            if mention["key"] not in prior_number_keys
        ]
        # B1: entity parser fixed outright - a capitalized sentence START
        # ("Though...", "American...", "Intercontinental range.") is grammar,
        # not an entity. Only capitalized runs that continue past the sentence
        # start, or capitalized tokens mid-sentence, are entity candidates.
        closer_entity_candidates: list[str] = []
        for closer_sentence in closer_sentences:
            for match in re.finditer(
                r"\b(?:[A-Z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)?|[A-Z]{2,}|[IVX]{1,4})"
                r"(?:\s+(?:[A-Z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)?|[A-Z]{2,}|[IVX]{1,4}))*\b",
                closer_sentence,
            ):
                entity = " ".join(match.group(0).split())
                if match.start() == 0:
                    # Drop the sentence-initial token; keep any capitalized
                    # continuation ("Though the Air Force..." -> "Air Force").
                    entity_tokens = entity.split()[1:]
                    entity = " ".join(entity_tokens)
                if entity:
                    closer_entity_candidates.append(entity)
        known_entity_text = f"{prior_paragraph_text} {machine}"
        ignored_final_entities = {
            "a", "an", "and", "as", "but", "it", "its", "so", "that", "the",
            "these", "this", "those", "together",
        }
        machine_code = _normalized_unit_code(machine)
        new_hard_entities: list[str] = []
        new_color_entities: list[str] = []
        for entity in closer_entity_candidates:
            entity_tokens = [
                token for token in entity.split()
                if token.lower() not in ignored_final_entities
            ]
            stripped_entity = " ".join(entity_tokens)
            if not stripped_entity:
                continue
            if stripped_entity in known_entity_text:
                continue
            if machine_code and _normalized_unit_code(stripped_entity) == machine_code:
                continue
            # B1(a): nationality/geographic color is editorial - advisory.
            if all(token.lower() in _GEOGRAPHIC_COLOR_WORDS for token in entity_tokens):
                new_color_entities.append(stripped_entity)
            else:
                new_hard_entities.append(stripped_entity)
        if new_hard_entities:
            warnings.append(
                "final sentence must not introduce new named entity/event detail(s): "
                + ", ".join(dict.fromkeys(new_hard_entities))
            )
        if new_color_entities:
            warnings.append(
                _ADVISORY_PREFIX + "closer uses geographic/nationality color outside the body: "
                + ", ".join(dict.fromkeys(new_color_entities))
            )
        # B1(b): a NEW number co-occurring with ANY new entity (color included)
        # is a fabricated-fact shape - hard. A new number alone is advisory.
        if final_numbers and new_hard_entities:
            warnings.append(
                "final sentence pairs a new number with a new entity - fabricated-fact shape: "
                + ", ".join(mention["raw"] for mention in final_numbers)
            )
        elif final_numbers:
            warnings.append(
                _ADVISORY_PREFIX + "closer introduces number(s) not in the body: "
                + ", ".join(mention["raw"] for mention in final_numbers)
            )
        # B1(d): contrast machinery (never/only/still) is LEGAL punch-form
        # vocabulary in a closer. Guarantee-style absolutes remain gated, and
        # hard only when attached to a new number or new entity.
        closer_absolute_terms = sorted(
            term for term in ("first", "largest", "fastest", "most")
            if re.search(rf"\b{re.escape(term)}\b", last_sentence.lower())
        )
        if closer_absolute_terms and (final_numbers or new_hard_entities):
            warnings.append(
                "final sentence must not attach absolute term(s) to new facts: "
                + ", ".join(closer_absolute_terms)
            )
        elif closer_absolute_terms:
            warnings.append(
                _ADVISORY_PREFIX + "closer uses absolute term(s) - confirm the body earns them: "
                + ", ".join(closer_absolute_terms)
            )
        # QL-5 recap heuristic, RECALIBRATED (I1+I4, 2026-07-16): HARD only
        # when the closer is a SINGLE sentence (no punch fragments - a closer
        # ending in fragments is never hard-recap), its repeat ratio vs the
        # body is >= 0.9, it carries no contrast marker, and it runs over 12
        # spoken words. Anything else recap-ish (ratio > 0.8) is advisory.
        closer_wc = _spoken_word_count(last_sentence)
        if closer_wc > 12 and len(sentence_parts) > 1 and prior_paragraph_text.strip():
            closer_lower = last_sentence.lower()
            has_contrast_marker = any(
                re.search(rf"\b{re.escape(marker)}\b", closer_lower)
                for marker in _DVSU_CONTRAST_MARKERS
            )
            body_stems = {
                _grounding_stem(token)
                for token in re.findall(r"[a-z]+", prior_paragraph_text.lower())
            }
            closer_content_stems = [
                _grounding_stem(token)
                for token in re.findall(r"[a-z]+", closer_lower)
                if len(token) >= 4
            ]
            repeat_ratio = (
                sum(1 for stem in closer_content_stems if stem in body_stems) / len(closer_content_stems)
                if closer_content_stems else 0.0
            )
            is_single_sentence_closer = trailing_fragment_count == 0
            if (
                is_single_sentence_closer
                and repeat_ratio >= 0.9
                and not has_contrast_marker
            ):
                warnings.append(
                    "closer restates facts - rewrite as an antithesis or a single hammer "
                    "(legal punch forms: single-hammer, antithesis, concede-then-cut, triad)"
                )
            elif repeat_ratio > 0.8 and not has_contrast_marker:
                warnings.append(
                    _ADVISORY_PREFIX + "closer leans recap-ish (most content words repeat the body) - "
                    "consider a sharper turn or the house punch"
                )
    if ";" in paragraph:
        warnings.append("paragraph may not use semicolons")

    evidence_text = allowed_evidence_text.lower()
    unsupported_risk_terms = sorted(
        term for term in high_risk_terms
        if re.search(rf"\b{term}\b", paragraph.lower()) and not re.search(rf"\b{term}\b", evidence_text)
    )
    if plan_supplies_evidence and unsupported_risk_terms:
        warnings.append("paragraph used high-risk term(s) absent from sourced evidence: " + ", ".join(unsupported_risk_terms))

    warnings.extend(PipelineExecutor._validate_static_unit_paragraph(machine, paragraph, rule_overrides))
    return paragraph, list(dict.fromkeys(warnings))


def _anton_preview_quality_audit(
    machine: str, plan: dict, bundle: dict, paragraph: str, warnings: list[str],
    rule_overrides: Optional[dict] = None,
) -> dict:
    """Small deterministic checklist for judging one machine against Anton's contract.

    ``rule_overrides``: only the "word_range" check's bounds are threaded
    (checklist C46c) - every other check already derives pass/fail from the
    ``warnings`` list, which is itself table-driven upstream, so it self-
    adapts with no separate override needed here."""
    import re

    rule_overrides = rule_overrides or {}
    word_floor_override = rule_overrides.get("word_floor") or {}
    audit_hard_min = int(word_floor_override.get("hard_min") or _ANTON_PARAGRAPH_HARD_MIN_WORDS)
    audit_hard_max = int(word_floor_override.get("hard_max") or _ANTON_PARAGRAPH_HARD_MAX_WORDS)
    paragraph = " ".join(str(paragraph or "").split())
    # Token-matched pass/fail keys off BLOCKING warnings only; advisory
    # (warn-severity) flags surface via the advisory validator_warnings row.
    warning_text = " | ".join(str(item) for item in _blocking_warnings(warnings or [])).lower()
    sentence_parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
    audit_trailing_fragments = 0
    for candidate in reversed(sentence_parts):
        if audit_trailing_fragments >= 3 or len(sentence_parts) - audit_trailing_fragments <= 1:
            break
        if _spoken_word_count(candidate) <= 6:
            audit_trailing_fragments += 1
        else:
            break
    audit_trailing_fragments = min(
        audit_trailing_fragments,
        max(0, len(sentence_parts) - _ANTON_PARAGRAPH_FORMULA_SENTENCES),
    )
    audit_effective_sentences = len(sentence_parts) - audit_trailing_fragments
    claim_rows = bundle.get("claim_map") if isinstance(bundle, dict) else []
    claim_rows = claim_rows if isinstance(claim_rows, list) else []
    formula_sentences = bundle.get("formula_sentences") if isinstance(bundle, dict) else []
    formula_sentences = formula_sentences if isinstance(formula_sentences, list) else []
    used_ids = list(dict.fromkeys(
        str(evidence_id)
        for row in claim_rows if isinstance(row, dict)
        for evidence_id in (
            row.get("used_evidence_ids") if isinstance(row.get("used_evidence_ids"), list)
            else row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list)
            else []
        )
        if str(evidence_id).strip()
    ))
    role_by_id: dict[str, str] = {}
    slot_ids: dict[str, list[str]] = {}
    for slot in (plan.get("slots", []) if isinstance(plan, dict) else []):
        role = str(slot.get("slot") or "")
        ids = [str(item) for item in (slot.get("evidence_ids") or []) if str(item).strip()]
        slot_ids[role] = ids
        for evidence_id in ids:
            # First-wins: shared support-slot segments keep narrative roles.
            role_by_id.setdefault(evidence_id, role)
    covered_roles = {role_by_id[evidence_id] for evidence_id in used_ids if evidence_id in role_by_id}
    missing_roles = sorted(role for role in _ANTON_REQUIRED_SLOT_ROLES if role not in covered_roles)
    claim_text_by_role: dict[str, list[str]] = {}
    for row in claim_rows:
        if not isinstance(row, dict):
            continue
        span = " ".join(str(row.get("span") or row.get("text") or row.get("claim") or "").split())
        if not span:
            continue
        row_ids = row.get("used_evidence_ids") if isinstance(row.get("used_evidence_ids"), list) else row.get("evidence_ids")
        row_ids = row_ids if isinstance(row_ids, list) else []
        for evidence_id in row_ids:
            role = role_by_id.get(str(evidence_id))
            if role:
                claim_text_by_role.setdefault(role, []).append(span)
    memorable_ids = slot_ids.get("memorable_fact") or []
    memorable_used = [evidence_id for evidence_id in memorable_ids if evidence_id in used_ids]
    final_line_warnings = [
        "final sentence word count",
        "final sentence uses generic",
        "final sentence must be paragraph-derived",
        "final sentence must not introduce",
        "final sentence ends on",
        # QL-5: summary/recap closers are banned.
        "closer restates facts",
    ]
    voiceover_clean_warnings = [
        "production cue/label",
        "bracketed production note",
        "meta/commentary",
        "must be exactly one paragraph",
        "raw numeric digit",
        "written unit abbreviation",
        "semicolon",
    ]
    assembly_warnings = [
        "formula_sentences",
    ]
    rhythm_warnings = [
        "three consecutive long sentences",
    ]
    opening_warnings = [
        "opening assignment forbids machine-name opening",
    ]
    narrative_weight_warnings = [
        "narrative_weight target",
    ]
    catalog_warnings = [
        "wikipedia-style",
        "list/spec-dump",
        "timeline/chronology",
        "hype language",
        "ranked-list connector",
        "orphan facts",
    ]

    def check(name: str, label: str, passed: bool, detail: str, advisory: bool = False) -> dict:
        row = {"name": name, "label": label, "passed": bool(passed), "detail": detail}
        if advisory:
            row["advisory"] = True
        return row

    word_count = _spoken_word_count(paragraph)
    narrative_weight = (plan.get("contract") or {}).get("narrative_weight") if isinstance(plan, dict) else None
    narrative_weight = narrative_weight if isinstance(narrative_weight, dict) else {}
    narrative_label = str(narrative_weight.get("label") or "standard").strip() or "standard"
    narrative_target = str(narrative_weight.get("target_words") or _ANTON_PARAGRAPH_TARGET_WORDS).strip()
    reference_benchmark = plan.get("reference_benchmark") if isinstance(plan, dict) else None
    twist = bundle.get("twist") if isinstance(bundle, dict) and isinstance(bundle.get("twist"), dict) else {}
    twist_type = str(twist.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
    deliberately_bare = bool(((plan.get("contract") or {}) if isinstance(plan, dict) else {}).get("deliberately_bare"))
    twist_tokens = ["designed-vs-used twist", "no gap and no substitute"]
    checks = [
        check(
            "word_range",
            # QD-6: hard window 80-170; the register band is guidance.
            # Checklist C46c: bounds come from a seeded QL-1 row when present.
            f"{audit_hard_min}-{audit_hard_max} words hard window",
            audit_hard_min <= word_count <= audit_hard_max,
            f"{word_count} words (register target {narrative_target})",
        ),
        check(
            "sentence_shape",
            f"{_ANTON_PARAGRAPH_SENTENCE_RANGE} counted sentences",
            _ANTON_PARAGRAPH_MIN_SENTENCES <= audit_effective_sentences <= _ANTON_PARAGRAPH_MAX_SENTENCES,
            f"{audit_effective_sentences} counted sentences ({len(sentence_parts)} raw); {_ANTON_PARAGRAPH_FORMULA}",
        ),
        check(
            # QL-3 (OR-1): the designed-vs-used engine, or a named substitute.
            "twist_gate",
            "Designed-vs-used twist",
            deliberately_bare or (
                bool(twist_type) and not any(token in warning_text for token in twist_tokens)
            ),
            (
                "deliberately bare (exempt)" if deliberately_bare
                else f"twist: {twist_type or 'undeclared'}"
                + (f" / substitute: {twist.get('substitute')}" if twist.get("substitute") else "")
            ),
        ),
        check(
            "sentence_assembly",
            "Sentence assembly",
            bool(formula_sentences)
            and " ".join(" ".join(str(item or "").split()) for item in formula_sentences) == paragraph
            and not any(token in warning_text for token in assembly_warnings),
            "formula_sentences assemble into paragraph" if not any(token in warning_text for token in assembly_warnings) else "formula_sentences mismatch",
        ),
        check(
            "four_evidence_beats",
            "Four grounded beats",
            not missing_roles,
            "covered" if not missing_roles else "missing " + ", ".join(missing_roles),
            advisory=not any(slot_ids.get(role) for role in _ANTON_REQUIRED_SLOT_ROLES),
        ),
        check(
            "memorable_fact",
            "Sourced memorable fact",
            deliberately_bare or bool(memorable_used),
            (
                "deliberately bare (exempt)" if deliberately_bare and not memorable_used else
                "used " + ", ".join(memorable_used)
                if memorable_used else
                "research plan has no sourced memorable_fact" if not memorable_ids else
                "available but unused"
            ),
            advisory=True,  # QL-9 (OR-7): warn until research coverage is proven.
        ),
        check(
            "editorial_thesis",
            "Concrete editorial thesis",
            isinstance(bundle, dict) and bool(str(bundle.get("editorial_thesis") or "").strip())
            and "editorial_thesis" not in warning_text,
            str(bundle.get("editorial_thesis") or "").strip() if isinstance(bundle, dict) else "",
            advisory=True,  # QD-5: thesis is graded warn-only, never blocking.
        ),
        check(
            "landed_final_line",
            "Landed final line",
            bool(sentence_parts) and not any(token in warning_text for token in final_line_warnings),
            sentence_parts[-1] if sentence_parts else "missing final sentence",
        ),
        check(
            "clean_voiceover",
            "Clean voiceover only",
            not any(token in warning_text for token in voiceover_clean_warnings),
            "clean" if not any(token in warning_text for token in voiceover_clean_warnings) else "production/meta artifact flagged",
        ),
        check(
            "spoken_rhythm",
            "Spoken rhythm",
            not any(token in warning_text for token in rhythm_warnings),
            "varied sentence lengths" if not any(token in warning_text for token in rhythm_warnings) else "three long sentences in a row",
        ),
        check(
            "opening_assignment",
            "Opening assignment",
            not any(token in warning_text for token in opening_warnings),
            "matched" if not any(token in warning_text for token in opening_warnings) else "machine-name opener flagged",
        ),
        check(
            "narrative_weight",
            "Narrative weight",
            (lambda match: not match or int(match.group(1)) <= word_count <= int(match.group(2)))(
                re.search(r"(\d+)\s*-\s*(\d+)", narrative_target)
            ),
            f"{narrative_label} target {narrative_target}; {word_count} words",
            advisory=True,  # QL-1/QL-2: register targets are guidance.
        ),
        check(
            "not_catalog_copy",
            "Not catalog/spec dump",
            not any(token in warning_text for token in catalog_warnings),
            "clean" if not any(token in warning_text for token in catalog_warnings) else "catalog pattern flagged",
        ),
    ]
    if (
        isinstance(reference_benchmark, dict)
        and str(reference_benchmark.get("source_video") or "") == "Every US Strategic Bomber Ever Built"
    ):
        claim_mapped_text = " ".join(
            span
            for spans in claim_text_by_role.values()
            for span in spans
        )
        # LAW: designations are identifiers, never numbers.
        numeric_keys = {
            mention["key"]
            for mention in _numeric_mentions_from_text(_strip_designations_for_numbers(claim_mapped_text, machine))
            if mention.get("key")
        }
        decision_text = " ".join(claim_text_by_role.get("engineering_decision") or []).lower()
        reality_text = " ".join(claim_text_by_role.get("reality") or []).lower()
        has_scale_or_capability = bool(_ANTON_SCALE_CAPABILITY_RE.search(decision_text))
        has_production_or_service = bool(_ANTON_PRODUCTION_SERVICE_RE.search(reality_text))
        benchmark_cadence_passed = len(numeric_keys) >= 2 and has_scale_or_capability and has_production_or_service
        checks.append(check(
            "benchmark_cadence",
            "Benchmark cadence",
            benchmark_cadence_passed,
            (
                f"{len(numeric_keys)} claim-mapped numerical details; "
                f"scale/capability {'present' if has_scale_or_capability else 'missing'}; "
                f"production/service reality {'present' if has_production_or_service else 'missing'}"
            ),
        ))
    # Advisory (warn-severity) validator flags never block the audit.
    blocking_validator_warnings = _blocking_warnings(warnings)
    if blocking_validator_warnings:
        checks.append(check(
            "validator_warnings",
            "Validator warnings",
            False,
            "; ".join(str(item) for item in blocking_validator_warnings[:3])[:240],
        ))
    elif warnings:
        checks.append(check(
            "validator_warnings",
            "Validator warnings",
            True,
            "advisory only: " + "; ".join(str(item) for item in warnings[:3])[:220],
            advisory=True,
        ))
    if isinstance(reference_benchmark, dict):
        try:
            benchmark_words = int(reference_benchmark.get("word_count") or 0)
        except Exception:
            benchmark_words = 0
        try:
            benchmark_sentences = int(reference_benchmark.get("sentence_count") or 0)
        except Exception:
            benchmark_sentences = 0
        word_delta = abs(word_count - benchmark_words) if benchmark_words else 0
        sentence_delta = abs(len(sentence_parts) - benchmark_sentences) if benchmark_sentences else 0
        checks.append(check(
            "reference_shape",
            "Reference shape",
            bool(benchmark_words and benchmark_sentences and word_delta <= 8 and sentence_delta <= 1),
            (
                f"{word_count} words/{len(sentence_parts)} sentences; "
                f"benchmark {benchmark_words} words/{benchmark_sentences} sentences; "
                f"{reference_benchmark.get('opening_mode') or 'shape only'}"
            ),
            advisory=True,
        ))
        try:
            reference_order = int(reference_benchmark.get("reference_order") or 0)
        except Exception:
            reference_order = 0
        if 1 <= reference_order <= 3:
            human_detail_ids = [
                evidence_id
                for slot in plan.get("slots", [])
                if str(slot.get("slot") or "") == "human_detail"
                for evidence_id in (slot.get("evidence_ids") or [])
            ]
            human_detail_used = [evidence_id for evidence_id in human_detail_ids if evidence_id in used_ids]
            if human_detail_used:
                human_detail = "used " + ", ".join(human_detail_used[:3])
            elif human_detail_ids:
                human_detail = "available but unused: " + ", ".join(human_detail_ids[:3])
            else:
                human_detail = "no sourced human_detail, named decision, or official finding in locked slots"
            checks.append(check(
                "early_human_detail",
                "Early human detail",
                bool(human_detail_used),
                human_detail,
                advisory=not bool(human_detail_ids),
            ))
    hard_checks_passed = all(item["passed"] or item.get("advisory") for item in checks)
    return {
        "passed": hard_checks_passed,
        "checks": checks,
        "summary": "Anton quality audit passed" if hard_checks_passed else "Anton quality audit needs review",
    }


def _static_docu_locked_unit_roster(video: dict) -> Optional[list]:
    """Shared gate for the siloed static-docu machine-roster path: return the
    RAW ``unit_roster`` list from a video's persisted research payload, or
    None if this video isn't (yet) on the locked machine-documentary path.

    Animation, narrative, dialogue, modeled, and clip-based videos remain on
    the global whole-video writer even if a roster-shaped field appears in
    research. No fact-sheet/LLM inference is allowed here: the roster must
    already be an explicit persisted list.

    Factored out of what used to be _machine_documentary_hold_roster's own
    body so that function (flat display-name strings — many callers depend
    on that exact shape) and _machine_documentary_hold_roster_entries (name +
    aliases, added for the roster reference-photo prefetch) can never drift
    apart on WHICH videos/rosters qualify.
    """
    import json as _json_mh

    if not isinstance(video, dict) or (video.get("render_mode") or "") != "static_docu":
        return None
    payload = video.get("research_payload") or {}
    if isinstance(payload, str):
        try:
            payload = _json_mh.loads(payload)
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, dict):
        return None
    marker = str(payload.get("documentary_style") or payload.get("pipeline_style") or "").strip().lower()
    has_machine_marker = (
        marker in {"machine_documentary", "designed_vs_used", "dvsu"}
        or isinstance(payload.get("machine_discovery_buckets"), dict)
        or isinstance(payload.get("unit_research_hold_validation"), dict)
    )
    if not has_machine_marker:
        return None
    roster = payload.get("unit_roster")
    return roster if isinstance(roster, list) else None


def _machine_documentary_hold_roster(video: dict) -> list[str]:
    """Return the locked machine roster only for the siloed static-docu path.

    Animation, narrative, dialogue, modeled, and clip-based videos remain on the
    global whole-video writer even if a roster-shaped field appears in research.
    No fact-sheet/LLM inference is allowed here: the roster must already be an
    explicit persisted list.
    """
    roster = _static_docu_locked_unit_roster(video)
    if roster is None:
        return []
    names = [_unit_display_name(item) for item in roster]
    names = [name for name in names if name]
    return names if 3 <= len(names) <= 40 else []


def _unit_roster_aliases(item: Any) -> list[str]:
    """Derive searchable aliases for one unit_roster entry, WITHOUT touching
    its display name (see _unit_display_name / _machine_key — the display
    name is the static_reference_cache primary key and must never change).

    For an aircraft/bomber roster entry (e.g. name="Valkyrie",
    designation="XB-70") the display name alone is already a clean, unique,
    searchable string. But for a ship-class roster entry the researcher
    often fills `designation` with a category/member-ship list instead of a
    real designation (e.g. name="Attacker class (US-built)",
    designation="Lend-Lease escort carriers"; or name="Courageous class",
    designation="Courageous, Glorious" — the actual member ships). Gluing
    those together the way _unit_display_name does for the SAVED string
    ("Lend-Lease escort carriers Attacker class (US-built)") produces a
    Wikipedia/Commons query nobody can match. Real-world proof (Every
    British Aircraft Carrier Class Ever Built, 2026-07-27): 6 of 23 roster
    machines had zero verified reference photo two days after research
    completed, and several of those misses were exactly this shape.

    Aliases returned here, in order:
      - C3 (2026-07-29, additive `member_units` field): each entry in
        `member_units` when the research schema supplied it, preferred
        first — this is the clean, purpose-built field for a class's named
        members, so it needs no comma/slash surgery to be searchable.
      - the bare `name`
      - the bare `designation`
      - each comma-split member (handles "Courageous, Glorious")
      - each side of a slash-compound (handles "Audacious class / Malta
        class"), also comma-split within each side

    The `member_units` step is purely additive: a roster item with no
    `member_units` key (every roster persisted before this field existed,
    and any future roster where the researcher left designation short/
    empty as instructed) produces byte-identical output to before this
    field existed — the name/designation comma/slash-split fallback below
    is untouched.

    Order-preserving, de-duplicated case-insensitively. Never includes the
    combined display name itself (the caller already has that separately).
    """
    if not isinstance(item, dict):
        return []
    nested = item.get("unit") or item.get("machine")
    if nested and not (item.get("name") or item.get("title") or item.get("designation") or item.get("code")):
        return _unit_roster_aliases(nested)

    aliases: list[str] = []
    seen_lower: set = set()

    def _add(raw: Any) -> None:
        s = str(raw or "").strip()
        key = s.lower()
        if s and key not in seen_lower:
            seen_lower.add(key)
            aliases.append(s)

    member_units_raw = item.get("member_units")
    if isinstance(member_units_raw, list):
        for unit in member_units_raw:
            if isinstance(unit, dict):
                _add(unit.get("name") or unit.get("title") or "")
            else:
                _add(unit)
    elif isinstance(member_units_raw, str):
        for part in member_units_raw.split(","):
            _add(part.strip())

    name = str(item.get("name") or item.get("title") or "").strip()
    designation = str(item.get("designation") or item.get("code") or "").strip()
    for base in (name, designation):
        if not base:
            continue
        for slash_part in base.split("/"):
            slash_part = slash_part.strip()
            if not slash_part:
                continue
            _add(slash_part)
            for comma_part in slash_part.split(","):
                _add(comma_part.strip())
    return aliases


# --- C5: never-built roster classification (2026-07-29) --------------------
#
# Some roster entries are cancelled programs or paper projects that were
# NEVER PHYSICALLY COMPLETED — no photograph can ever exist because no
# hardware was ever built (the live example: "CVA-01 class", the British
# carrier programme cancelled in 1966 before being laid down). Today those
# entries sit in the exact same "missing, paste a URL" bucket as a machine
# that just needs another search attempt or a better alias — misleading,
# because no amount of retrying will ever find CVA-01 a photo.
#
# CONSERVATIVE BY DESIGN: a false "never built" verdict is much worse than a
# missed one. It permanently tells the operator and the UI no photo can
# exist, suppressing the retry affordance for a machine whose photo is
# genuinely findable. Under-detection is the correct failure mode throughout
# this section.
#
# REVISION (2026-07-29, same day, corrected against REAL prod data): the
# first cut of this rule keyed entirely off `status` being the bare word
# "cancelled". Pulling the actual roster for video d2e37cd6 proved that
# wrong — the researcher tags status LOOSELY, and BOTH of these real rows
# carry the exact same status, "cancelled-built":
#
#   CVA-01 class (MUST classify never-built):
#     status="cancelled-built", built_count="0 ships built, cancelled
#     February 1966 before construction [Friedman 1988]"
#
#   Audacious class / Malta class (MUST stay refused — one ship, HMS Eagle,
#   was actually completed):
#     status="cancelled-built", built_count="1 ship completed (Eagle R05),
#     3 cancelled on slips (...) [Friedman 1988]"
#
# `status` cannot separate these — it's identical on both. `built_count` is
# the only field that actually distinguishes a zero-hull paper cancellation
# from a class where one hull reached completion, so built_count is now the
# PRIMARY decisive signal, with status reduced to a coarse safety gate
# (must at least mention "cancelled" somewhere) rather than the deciding
# vocabulary word.
#
# THE TRAP (kept from the original design, still real): "cancelled-built"
# and "built-prototype" both name a programme where at least one physical
# unit WAS completed (the Audacious/Malta shape above; the aircraft
# equivalent is the Avro Arrow / North American XB-70 / TSR-2 — the
# programme died, but real prototypes were built and photographed). A
# built_count asserting ANY positive completed count, for ANY status, must
# always veto the classification — it dominates every other signal.
_QUANTITY_WORD = (
    r"(?:[1-9]\d*|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"several|many|some|a\s+few)"
)

# VETO #1: built_count asserts a POSITIVE completed count for ANY reason —
# a number/quantity word tied to a unit noun ("1 ship completed", "2 ships
# converted") or tied to a completion verb ("3 built", "several flown").
# Requires the quantity to be POSITIVE (never "0"), so "0 ships built"
# (CVA-01's real text) does NOT trip this — only [1-9]/spelled-out/vague-
# plural quantities do.
_BUILT_COUNT_POSITIVE_RE = re.compile(
    rf"\b{_QUANTITY_WORD}\s*(?:ships?|units?|aircraft|hulls?|vehicles?|"
    rf"prototypes?|examples?|airframes?)\b"
    rf"|\b{_QUANTITY_WORD}\s*(?:were\s+|was\s+)?(?:built|converted|completed|"
    rf"delivered|produced|constructed|flown)\b",
    re.IGNORECASE,
)

# VETO #2: built_count mentions a hull being LAID DOWN at all, regardless of
# quantity or whether it was later cancelled/completed. A laid-down hull is
# physical steel on a slipway — it may well have been photographed under
# construction before cancellation, even though zero units were ever
# "completed". This is deliberately MORE cautious than the completed-count
# veto: it fires on the bare phrase, no positive-quantity requirement,
# because under-detection (refusing to classify) is the correct failure
# mode here too. CVA-01's real built_count text never mentions "laid
# down" — consistent with history: CVA-01 was cancelled at the design
# stage in 1966, before any steel was ever cut, so this veto correctly
# stays silent for it. A hypothetical future entry like "2 hulls laid
# down, 0 completed, program cancelled" WOULD be vetoed by this rule even
# though its completed count is zero — that is the intended, conservative
# behavior, not a bug.
_BUILT_COUNT_LAID_DOWN_RE = re.compile(r"\blaid\s+down\b", re.IGNORECASE)

# DECISIVE POSITIVE SIGNAL: built_count explicitly asserts ZERO units were
# ever completed — "0 ships built", "0 built", "none completed", "never
# built", "no ships were built". This is now the PRIMARY route to a
# never-built verdict (see Route B below), because it is a factual count
# claim, not a loosely-applied status label.
_BUILT_COUNT_ZERO_RE = re.compile(
    r"\b0\s*(?:ships?|units?|aircraft|hulls?|vehicles?|prototypes?|"
    r"examples?|airframes?)\b"
    r"|\b0\s*(?:built|completed|delivered|produced|constructed)\b"
    r"|\bnone\s+(?:built|completed|delivered|produced|constructed)\b"
    r"|\bnever\s+built\b"
    r"|\bno\s+(?:ships?|units?|aircraft|hulls?|vehicles?|prototypes?|"
    r"examples?)\s+(?:were\s+|was\s+)?(?:built|completed|delivered|"
    r"produced|constructed)\b",
    re.IGNORECASE,
)


def _roster_built_count_vetoes_never_built(built_count: str) -> bool:
    """True when built_count text contains EITHER veto signal — a positive
    completed count, or any mention of a hull being laid down. Either one
    alone is enough to refuse a never-built classification; see the two
    veto docstrings above (_BUILT_COUNT_POSITIVE_RE, _BUILT_COUNT_LAID_DOWN_RE)
    for why each exists. Shared by both classification routes below and by
    the repair-warning helper, so the veto condition can never drift out of
    sync between them."""
    if not built_count:
        return False
    return bool(
        _BUILT_COUNT_POSITIVE_RE.search(built_count)
        or _BUILT_COUNT_LAID_DOWN_RE.search(built_count)
    )


def _roster_entry_never_built(item: Any) -> bool:
    """Conservative, structured-data-only detector: can this roster entry
    NEVER have a real photograph because it was cancelled before any
    physical unit existed?

    Two independent routes to a True verdict, EITHER of which is vetoed by
    _roster_built_count_vetoes_never_built (a positive completed count, or
    any "laid down" mention) — the veto always dominates.

    ROUTE A (original design, kept per explicit instruction not to remove
    it): `status`, trimmed/lowercased, is the bare word "cancelled" and
    nothing else. Still useful for a roster that uses the vocabulary
    cleanly, but real prod data (see the REVISION note above this function)
    shows the researcher does NOT reliably do that — CVA-01 itself is
    tagged "cancelled-built", so this route alone would miss it.

    ROUTE B (added after the real-data correction, now the PRIMARY route in
    practice): `status` merely CONTAINS the substring "cancelled" (catches
    "cancelled", "cancelled-built", "cancelled-prototype", etc — a coarse
    safety gate, not the decisive signal) AND `built_count` explicitly
    asserts a ZERO completed count (_BUILT_COUNT_ZERO_RE). built_count is a
    factual count claim and is trusted over the loosely-applied status
    word — this is exactly what separates the real CVA-01 row
    (built_count="0 ships built...") from the real Audacious/Malta row
    (built_count="1 ship completed (Eagle R05), 3 cancelled on slips...",
    same status="cancelled-built" on both) which the veto refuses.

    Status values with NO "cancelled" substring at all ("production",
    "converted", "prototype", "built-prototype", "special-purpose",
    "secret-or-black-program", "edge-case", "disputed", "variant") — and a
    missing/empty status — never reach either route. Under-detection is
    the correct failure mode.

    Only ever meaningful on a structured roster dict; a bare display-name
    string (older roster shape, or a fixture with no status field) always
    returns False here — there is nothing to classify from.
    """
    if not isinstance(item, dict):
        return False
    status = str(item.get("status") or "").strip().lower()
    built_count = str(item.get("built_count") or "").strip()

    if _roster_built_count_vetoes_never_built(built_count):
        return False

    if status == "cancelled":  # Route A
        return True

    if "cancelled" in status and _BUILT_COUNT_ZERO_RE.search(built_count):  # Route B
        return True

    return False


def _roster_status_built_count_contradicts(item: Any) -> bool:
    """True exactly when a roster item's status is the bare word "cancelled"
    but its built_count asserts real hardware was completed or laid down —
    the Route A case where _roster_entry_never_built refuses to classify
    because the two fields disagree outright (status implies zero, count
    says otherwise). Kept as its own function (rather than inlining the
    negation in _roster_validation) so the contradiction condition can
    never quietly drift out of sync with the classifier it mirrors."""
    if not isinstance(item, dict):
        return False
    status = str(item.get("status") or "").strip().lower()
    if status != "cancelled":
        return False
    built_count = str(item.get("built_count") or "").strip()
    return _roster_built_count_vetoes_never_built(built_count)


def _roster_status_built_wording_but_zero_completed(item: Any) -> bool:
    """True when `status` uses "-built"/"built-" wording ("cancelled-built",
    "built-prototype" — implying SOMETHING physical exists) but built_count
    explicitly says ZERO units were ever completed, with no veto. This is
    the exact mislabeling verified live in prod on 2026-07-29: the real
    CVA-01 class row — a programme with ZERO hulls ever laid down — is
    tagged status="cancelled-built", not bare "cancelled". The never-built
    classifier already reads through this correctly via built_count (Route
    B), so this is NOT a blocker — but the mislabeling itself is worth
    flagging as a soft repair warning so a future research pass uses bare
    "cancelled" for a true zero-hull program and reserves "-built"/"built-"
    wording for a programme with real completed hardware."""
    if not isinstance(item, dict):
        return False
    status = str(item.get("status") or "").strip().lower()
    if "built" not in status:
        return False
    built_count = str(item.get("built_count") or "").strip()
    if not built_count or _roster_built_count_vetoes_never_built(built_count):
        return False
    return bool(_BUILT_COUNT_ZERO_RE.search(built_count))


def _machine_documentary_hold_roster_entries(video: dict) -> list[dict]:
    """Same gate as _machine_documentary_hold_roster (same 3-40 bound, same
    static-docu machine-marker requirement), but returns each roster item as
    {"name": <UNCHANGED display name>, "aliases": [...], "never_built": bool}
    instead of throwing the structured entry away.

    This is an ADDITIVE parallel accessor, not a replacement:
    _machine_documentary_hold_roster has many other callers
    (pipeline_executor.py's own run_research/run_one_machine_research/etc,
    scripts/dvsu_machine_preflight.py) that depend on the flat list[str]
    shape and on the display name being byte-identical to what's cached in
    static_reference_cache (_machine_key hashes that exact string — there
    are live cached rows keyed on today's names). Only the roster reference-
    photo prefetch (static_docu.prefetch_roster_references) needs aliases or
    never_built, so only it calls this.

    Aliases equal to the display name (case-insensitive) are dropped as
    redundant.

    C5 (2026-07-29): `never_built` (see _roster_entry_never_built) lets
    static_docu.prefetch_roster_references skip the ENTIRE doomed Wikimedia
    + paid vision lookup chain for a machine that structurally can never
    have a photograph, recording REASON_NEVER_BUILT directly instead of
    exhausting a real search first. Additive: existing consumers of this
    function that only read name/aliases are unaffected.
    """
    roster = _static_docu_locked_unit_roster(video)
    if roster is None:
        return []
    entries: list[dict] = []
    for item in roster:
        name = _unit_display_name(item)
        if not name:
            continue
        aliases = [a for a in _unit_roster_aliases(item) if a.lower() != name.lower()]
        # VIS-1 (2026-07-30): `facts` carries the structured entry's own
        # role/years/status/built_count through to the vision identity check.
        # Why: audited live on video d2e37cd6 — the alias-found candidates
        # for 5 roster entries "verified" 4 wrong photos (Courageous in her
        # PRE-conversion battlecruiser configuration, HMS Glory — a
        # Colossus-class ship — cached as "Majestic class", Pretoria Castle
        # as her post-war liner reconversion, and USS Guadalcanal — a US
        # Navy Casablanca-class CVE — as the RN "Ruler class"). The vision
        # prompt asked only "is this consistent with <name>?", a question a
        # sister class or a different-era configuration of the right ship
        # passes. The roster entry already KNOWS the role, era, and status
        # that distinguish those; this hands that knowledge to the check
        # instead of leaving it behind in the payload. Additive: existing
        # consumers read name/aliases/never_built only.
        facts = {}
        if isinstance(item, dict):
            for key in ("role", "years", "status", "built_count"):
                value = str(item.get(key) or "").strip()
                if value:
                    facts[key] = value
        entries.append({
            "name": name,
            "aliases": aliases,
            "never_built": _roster_entry_never_built(item),
            "facts": facts,
        })
    return entries if 3 <= len(entries) <= 40 else []


def _anton_inventory_title_mode(title: str) -> bool:
    """Titles promising a machine inventory need the Anton slot compiler."""
    return bool(re.search(
        r"\b(every|all)\b|complete (history|list|roster)|\bever built\b",
        str(title or ""),
        re.IGNORECASE,
    ))


def _list_len(value: Any) -> int:
    """Count list-like discovery fields defensively."""
    return len(value) if isinstance(value, list) else 0


def _machine_bucket_summary(payload: dict) -> dict:
    """Return counts for broad DVsU machine-discovery buckets."""
    buckets = payload.get("machine_discovery_buckets") if isinstance(payload, dict) else None
    if not isinstance(buckets, dict):
        buckets = {}
    keys = (
        "core_roster",
        "built_prototypes",
        "converted_or_special_variants",
        "secret_cancelled_or_black_programs",
        "boundary_disputes",
    )
    return {key: _list_len(buckets.get(key)) for key in keys}


def _roster_pacing_targets(video_length_minutes: Any) -> Optional[dict]:
    """Channel-calibrated roster pressure for DVsU/Anton-style machine videos."""
    try:
        minutes = float(video_length_minutes or 0)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None

    import math

    target_final = max(1, round((minutes * 60) / 60))
    minimum_final = max(1, math.floor(target_final * 0.85))
    good_measure = max(2, math.ceil(target_final * 0.10))
    candidate_target = target_final + good_measure
    return {
        "video_length_minutes": minutes,
        "seconds_per_machine_screen_time": 60,
        "words_per_machine_segment_range": _ANTON_PARAGRAPH_WORD_RANGE,
        "default_words_per_machine_segment": 105,
        "expected_final_roster": target_final,
        "minimum_final_roster": minimum_final,
        "candidate_universe_target": candidate_target,
        "extra_good_measure": good_measure,
        "heuristic_note": "Runtime target for the locked final roster; research a small reserve for exclusions/swaps, not an endless universe.",
    }


def _roster_validation(
    title: str,
    payload: dict,
    script_units: Optional[list[str]] = None,
    video_length_minutes: Any = None,
) -> dict:
    """Validate the research/script roster contract without adding DB columns.

    Stored into research_payload/script_validation so the UI can show the same
    truth Ryan just caught manually: a complete-title video cannot silently run
    on a curated shortlist.
    """
    roster_raw = payload.get("unit_roster") if isinstance(payload, dict) else None
    roster = [_unit_display_name(x) for x in (roster_raw or [])]
    roster = [x for x in roster if x]
    roster_codes = [_unit_code(x) for x in roster if _unit_code(x)]
    contract = str((payload or {}).get("roster_contract") or "") if isinstance(payload, dict) else ""
    counter = str((payload or {}).get("counter_arguments") or "") if isinstance(payload, dict) else ""
    audit = payload.get("roster_audit") if isinstance(payload, dict) else None
    if not isinstance(audit, dict):
        audit = {}
    complete_title = _title_needs_complete_roster(title)

    warnings: list[str] = []
    gaps: list[str] = []
    # C4 (2026-07-29): severity tiers. `warnings` stays the full combined list
    # (unchanged shape/order — every existing reader that just dumps
    # `warnings` keeps working byte-for-byte). `hard_warnings` are structural/
    # data-integrity failures that must still block a complete-title video
    # from advancing; `soft_warnings` are pacing/count nitpicks (roster a bit
    # short or a bit long vs the runtime target, the generic edge-case-class
    # heuristic, the aircraft-only subvariant-padding check) that get
    # recorded and flagged for human review but must NOT dead-end the video.
    # This is what let video d2e37cd6's real 23-ship roster sit at 0/23
    # verified photos for two days on one soft pacing warning alone (see
    # loop-checklist.md "Why"). `passed` now means "no hard failures" —
    # a soft-only roster passes and advances, marked needs_review.
    hard_warnings: list[str] = []
    soft_warnings: list[str] = []

    def _warn(message: str, *, hard: bool) -> None:
        warnings.append(message)
        (hard_warnings if hard else soft_warnings).append(message)

    lower = f"{contract}\n{counter}".lower()
    bucket_counts = _machine_bucket_summary(payload or {})
    bucket_total = sum(bucket_counts.values())
    audit_excluded = []
    audit_obj = payload.get("roster_audit") if isinstance(payload, dict) else None
    if isinstance(audit_obj, dict) and isinstance(audit_obj.get("excluded_candidates"), list):
        audit_excluded = audit_obj.get("excluded_candidates") or []
    gap_hunt_items = payload.get("gap_hunt_matrix") if isinstance(payload, dict) else None
    if not isinstance(gap_hunt_items, list):
        gap_hunt_items = []
    # Candidate-universe pressure should count everything the research visibly
    # chased: final roster, buckets, gap-hunt candidates, and source-backed
    # exclusions. Some good passes put researched rejects in excluded_candidates
    # instead of duplicating them in buckets.
    candidate_names: set[str] = set()
    def _add_candidate_name(value: Any) -> None:
        name = _unit_display_name(value)
        if name:
            candidate_names.add(name.lower())
    for item in roster_raw or []:
        _add_candidate_name(item)
    buckets_obj = payload.get("machine_discovery_buckets") if isinstance(payload, dict) else None
    if isinstance(buckets_obj, dict):
        for values in buckets_obj.values():
            if isinstance(values, list):
                for item in values:
                    _add_candidate_name(item)
    for item in audit_excluded:
        _add_candidate_name(item)
    for item in gap_hunt_items:
        if isinstance(item, dict):
            _add_candidate_name(item.get("candidate") or item.get("name"))
        else:
            _add_candidate_name(item)
    candidate_universe_count = max(bucket_total, len(candidate_names))
    pacing_targets = _roster_pacing_targets(video_length_minutes)
    recommended = payload.get("recommended_final_roster") if isinstance(payload, dict) else None
    gap_hunt = payload.get("gap_hunt_matrix") if isinstance(payload, dict) else None
    edge_case_matrix = payload.get("edge_case_matrix") if isinstance(payload, dict) else None
    operator_points = payload.get("operator_decision_points") if isinstance(payload, dict) else None
    has_recommendation = isinstance(recommended, list) and len(recommended) > 0
    has_gap_hunt = isinstance(gap_hunt, list) and len(gap_hunt) > 0
    has_edge_case_matrix = isinstance(edge_case_matrix, list) and len(edge_case_matrix) > 0
    is_review_ready = "review_ready" in lower
    contract_norm = contract.strip().lower()
    is_incomplete = contract_norm.startswith("incomplete") and not is_review_ready

    # C5 contract-triangle repair warning (2026-07-29): flag a roster item
    # whose `status` and `built_count` contradict each other for the
    # never-built classifier (_roster_entry_never_built, this same module).
    # A bare "cancelled" status paired with a built_count that itself
    # asserts real hardware (a positive unit count, or a build-completion
    # verb) means the researcher used the vocabulary inconsistently — the
    # classifier already refuses to act on it (conservative-by-design), but
    # a human should still see it and correct the status to
    # "cancelled-built" or "built-prototype" for the next research pass.
    # Applies to every static-docu roster regardless of title shape — this
    # is a data-integrity check, not a pacing/count nitpick.
    status_contradictions: list[str] = []
    for item in roster_raw or []:
        if _roster_status_built_count_contradicts(item):
            display = _unit_display_name(item) or str((item or {}).get("name") or "").strip()
            if display:
                status_contradictions.append(display)
    if status_contradictions:
        shown = status_contradictions[:8]
        more = len(status_contradictions) - len(shown)
        _warn(
            "status is 'cancelled' (never built) but built_count asserts real hardware for: "
            + ", ".join(shown)
            + (f" (+{more} more)" if more > 0 else "")
            + ". Use 'cancelled-built' or 'built-prototype' when a cancelled programme's "
            "hardware was actually completed — bare 'cancelled' means nothing was ever built.",
            hard=False,
        )

    # C5 SECOND repair warning, added 2026-07-29 after real prod data proved
    # the first one insufficient: the live CVA-01 row — a programme with
    # ZERO hulls ever laid down — is tagged status="cancelled-built", not
    # bare "cancelled". The never-built classifier reads through this fine
    # (built_count is the decisive signal, see _roster_entry_never_built
    # Route B), but the mislabeling itself is worth surfacing so a future
    # research pass reserves "-built"/"built-" status wording for a
    # programme that actually has completed hardware.
    built_wording_zero_count: list[str] = []
    for item in roster_raw or []:
        if _roster_status_built_wording_but_zero_completed(item):
            display = _unit_display_name(item) or str((item or {}).get("name") or "").strip()
            if display:
                built_wording_zero_count.append(display)
    if built_wording_zero_count:
        shown = built_wording_zero_count[:8]
        more = len(built_wording_zero_count) - len(shown)
        _warn(
            "status uses '-built'/'built-' wording (implying real hardware exists) but "
            "built_count says zero units were ever completed for: "
            + ", ".join(shown)
            + (f" (+{more} more)" if more > 0 else "")
            + ". Use bare 'cancelled' for a programme with zero completed hardware — "
            "reserve 'cancelled-built'/'built-prototype' for one that actually has some.",
            hard=False,
        )

    if complete_title and not roster:
        _warn("This title promises a complete roster, but research_payload.unit_roster is missing.", hard=True)
    if complete_title and len(roster) < 3:
        _warn(f"Complete-roster title has only {len(roster)} roster item(s); likely incomplete.", hard=True)
    if _title_is_broad_machine_roster(title) and len(roster) < 15:
        # SOFT: a count/pacing signal, same family as the minimum/expected/
        # candidate-universe pacing checks below — not a structural failure.
        _warn(
            f"Broad machine-roster title has only {len(roster)} item(s); likely a shortlist, not the full title promise.",
            hard=False,
        )
    small_category_proof = any(term in lower for term in ("genuinely small", "small closed category", "only known", "no additional built"))
    if (
        _title_is_broad_machine_roster(title)
        and complete_title
        and pacing_targets
        and len(roster) < pacing_targets["minimum_final_roster"]
        and not small_category_proof
    ):
        # SOFT: pacing/count warning — record + needs-review, do not block.
        _warn(
            "Broad complete-roster title has fewer than "
            f"{pacing_targets['minimum_final_roster']} final items for a "
            f"{pacing_targets['video_length_minutes']:g}-minute Anton-paced video "
            f"(expected around {pacing_targets['expected_final_roster']}) without proving the category is genuinely small.",
            hard=False,
        )
    if (
        _title_is_broad_machine_roster(title)
        and complete_title
        and pacing_targets
        and len(roster) < pacing_targets["expected_final_roster"]
        and not small_category_proof
    ):
        # SOFT: pacing/count warning — record + needs-review, do not block.
        _warn(
            "Broad complete-roster title is below the Anton-paced final roster target: "
            f"{len(roster)} final items vs expected around {pacing_targets['expected_final_roster']} "
            f"for a {pacing_targets['video_length_minutes']:g}-minute video. Lock enough source-backed machines to fit the runtime or "
            "prove with sources that the category is genuinely smaller.",
            hard=False,
        )
    if (
        _title_is_broad_machine_roster(title)
        and complete_title
        and pacing_targets
        and len(roster) > pacing_targets["candidate_universe_target"]
        and not small_category_proof
    ):
        # SOFT: pacing/count warning — this is the EXACT condition that
        # stalled video d2e37cd6 ("23 final items vs target around 20") for
        # two days. Record + needs-review, never block.
        _warn(
            "Broad complete-roster final roster is larger than the runtime target plus reserve: "
            f"{len(roster)} final items vs target around {pacing_targets['expected_final_roster']} "
            f"for a {pacing_targets['video_length_minutes']:g}-minute video. Tighten the roster to fit the requested runtime, "
            "or prove that the title requires the larger count.",
            hard=False,
        )
    if _title_is_broad_machine_roster(title):
        if bucket_total == 0:
            _warn(
                "Broad machine-roster research is missing machine_discovery_buckets for core/prototypes/variants/secret programs/boundary disputes.",
                hard=True,
            )
        if not has_recommendation:
            _warn("Broad machine-roster research is missing recommended_final_roster.", hard=True)
        elif isinstance(recommended, list) and len(recommended) != len(roster):
            _warn(
                f"recommended_final_roster count ({len(recommended)}) does not match unit_roster count ({len(roster)}); "
                "the locked machine list is internally inconsistent.",
                hard=True,
            )
        if not has_gap_hunt:
            _warn("Broad machine-roster research is missing gap_hunt_matrix showing the adversarial omission follow-up pass.", hard=True)
        if not has_edge_case_matrix:
            _warn("Broad machine-roster research is missing edge_case_matrix showing generic omission classes checked.", hard=True)
        blob_lower = _payload_blob(payload or {}).lower()
        generic_edge_classes = {
            "designation/number sequence gaps": ("designation", "sequence", "number"),
            "prefix/classification variants": ("prefix", "classification", "class"),
            "mission-converted/special-purpose variants": ("converted", "special-purpose", "special purpose", "support"),
            "renamed/reclassified/predecessor-successor programs": ("renamed", "reclassified", "predecessor", "successor"),
            "foreign-built/license/local-modification candidates": ("foreign-built", "license", "locally modified", "local modification", "export"),
            "common false positives/exclusions": ("false positive", "excluded", "exclusion"),
        }
        covered_classes = [
            label for label, needles in generic_edge_classes.items()
            if any(needle in blob_lower for needle in needles)
        ]
        if len(covered_classes) < 4:
            # SOFT: heuristic, not a data-integrity failure.
            _warn("Broad machine-roster research did not explicitly resolve enough generic edge-case classes.", hard=False)
            for label in generic_edge_classes:
                if label not in covered_classes and label not in gaps:
                    gaps.append(label)

        # Catch count-padding with minor subvariants when the parent machine is
        # already in the final roster. Complete-title machine videos need one
        # audience-facing section per machine/program, not B-29 plus B-29B /
        # B-36 plus B-36J just to hit the runtime target. Distinct programs with
        # no plain parent row (for example A/B program variants) are left alone.
        import re as _roster_re
        family_entries: dict[str, list[str]] = {}
        for item in roster:
            code = _unit_code(item)
            match = _roster_re.search(r"\b(B|FB)-(\d{1,3})([A-Z]?)\b", code)
            if not match:
                continue
            family = f"{match.group(1)}-{match.group(2)}"
            family_entries.setdefault(family, []).append(code)
        padded_families = [
            family for family, codes in family_entries.items()
            if family in codes and any(code != family for code in codes)
        ]
        if padded_families and not any(term in str(title or "").lower() for term in ("variant", "variants", "class", "classes")):
            # SOFT: aircraft-only heuristic (test_unit_code_family_detection_is_aircraft_only
            # proves it is a structural no-op for ship rosters) — a nitpick, not a
            # data-integrity failure.
            _warn(
                "Final roster appears padded with minor subvariants while the parent machine is already included: "
                + ", ".join(padded_families)
                + ". Combine minor variants under the parent unless the title asks for variants/classes or the subvariant is a distinct audience-facing program.",
                hard=False,
            )

        # C3 (2026-07-29, additive `member_units` field): contract-triangle
        # repair-warning half. The research prompt now has an explicit place
        # (`member_units`) for a class's individual named units, so a
        # `designation` that's still a comma-separated member-ship/unit list
        # (e.g. "Courageous, Glorious" or "Illustrious, Formidable, Victorious,
        # Indomitable") with no `member_units` supplied means the researcher
        # stuffed the list into the wrong field instead of leaving
        # `designation` as a short searchable identifier. Flagged SOFT so
        # every pre-existing roster in the DB (frozen, no `member_units`
        # field ever) keeps passing/advancing exactly as before — this is
        # visibility to steer the NEXT repair/research pass, never a new hard
        # gate. Deliberately conservative (comma-list shape only): a
        # designation that's merely a multi-word category phrase with no
        # comma (e.g. "Lend-Lease escort carriers") is NOT caught here — a
        # reliable heuristic for that shape risks false-positiving on
        # legitimate multi-word designations, so it's left as a known
        # follow-up rather than guessed at.
        designation_stuffed_items: list[str] = []
        for item in roster_raw or []:
            if not isinstance(item, dict) or item.get("member_units"):
                continue
            designation_value = str(item.get("designation") or item.get("code") or "")
            comma_parts = [p.strip() for p in designation_value.split(",") if p.strip()]
            if len(comma_parts) >= 2:
                display = _unit_display_name(item) or str(item.get("name") or "").strip()
                if display:
                    designation_stuffed_items.append(display)
        if designation_stuffed_items:
            shown = designation_stuffed_items[:8]
            more = len(designation_stuffed_items) - len(shown)
            _warn(
                "designation holds a comma-separated member-ship/unit list instead of a short "
                "searchable code for: " + ", ".join(shown)
                + (f" (+{more} more)" if more > 0 else "")
                + ". Move the individual member units into member_units and keep designation "
                "short or empty — a glued member-list designation is not a searchable machine name.",
                hard=False,
            )

        excluded_codes: dict[str, str] = {}
        for item in audit_excluded:
            name = _unit_display_name(item)
            code = _unit_code(name)
            if code:
                excluded_codes[code] = name
        overlap = [name for name, code in zip(roster, roster_codes) if code in excluded_codes]
        if overlap:
            _warn(
                "Roster is internally inconsistent: candidate appears in both unit_roster and excluded_candidates: "
                + ", ".join(overlap),
                hard=True,
            )

        title_lower = str(title or "").lower()
        if "ever built" in title_lower and any(
            term in _payload_blob(audit_excluded).lower()
            for term in ("not operationally delivered", "not yet operational", "not operationally deployed")
        ):
            _warn(
                "Ever-built title is excluding a candidate for not being operational/delivered. "
                "For 'ever built', physical build/flight is the boundary; operational status alone is not a valid exclusion.",
                hard=True,
            )
    if is_incomplete or any(term in lower for term in ("misleading", "should either be narrowed", "research expanded")):
        _warn("Research payload admits the roster/title may be incomplete or narrowed.", hard=True)
    if complete_title:
        queries = audit.get("search_queries_used") or []
        families = audit.get("source_families_crosschecked") or []
        unresolved = audit.get("unresolved_candidates") or []
        confidence_raw = str(audit.get("confidence") or "").strip().lower()
        confidence = ""
        for level in ("high", "medium", "low"):
            if level in confidence_raw:
                confidence = level
                break
        if not audit:
            _warn("Complete-roster research is missing roster_audit proof of exhaustive search.", hard=True)
        elif len(queries) < 6:
            _warn("Complete-roster research used fewer than 6 distinct roster-discovery searches.", hard=True)
        if audit and len(families) < 3:
            _warn("Complete-roster research cross-checked fewer than 3 source families.", hard=True)
        if audit and unresolved and not (is_review_ready and has_recommendation):
            _warn(f"Complete-roster research still has {len(unresolved)} unresolved candidate(s).", hard=True)
        if audit and confidence and confidence not in ("high", "medium"):
            _warn(f"Complete-roster audit confidence is {confidence}, not high/medium.", hard=True)
        if isinstance(unresolved, list):
            for item in unresolved:
                name = _unit_display_name(item)
                code = _unit_code(name)
                if code and code not in roster_codes and code not in gaps:
                    gaps.append(code)
    # Pull explicit designations from caveats so the UI can name the likely gaps.
    import re
    for code in re.findall(r"\b(?:X?Y?B|FB)-?\d{1,3}[A-Z]?\b", f"{contract}\n{counter}", flags=re.I):
        norm = code.upper().replace(" ", "")
        if norm not in roster_codes and norm not in gaps:
            gaps.append(norm)

    script_missing: list[str] = []
    script_extra: list[str] = []
    if script_units is not None and roster_codes:
        if len(script_units) != len(roster):
            _warn(
                f"Script has {len(script_units)} paragraph(s) for {len(roster)} locked roster item(s); "
                "static DVsU scripts must not add separate conclusion, transition, or non-machine rows.",
                hard=True,
            )
        script_blob = "\n".join(script_units)
        script_codes = [_unit_code(u) for u in script_units if _unit_code(u)]
        for name, code in zip(roster, roster_codes):
            if code and code not in script_blob.upper():
                script_missing.append(name)
        for code in script_codes:
            if code and code not in roster_codes and code not in script_extra:
                script_extra.append(code)
        if script_missing:
            _warn(f"Script omitted {len(script_missing)} roster item(s).", hard=True)
        if script_extra:
            _warn(f"Script added {len(script_extra)} item(s) outside the locked roster.", hard=True)

    return {
        # C4 (2026-07-29): `passed` now means "no HARD failures" — a
        # soft-only roster (pacing/count nitpicks, the generic edge-case
        # heuristic, aircraft-only subvariant padding) passes and is free to
        # advance. Every existing caller that gates on `.get("passed")`
        # (run_research's autonomous-repair trigger and advance-to-scripting
        # check, run_unit_research, _validate_static_script_roster's callers,
        # research_ingest.accept_submitted_research) gets this looser,
        # intentional behavior for free just by reading the same key.
        "passed": len(hard_warnings) == 0,
        # New keys for callers that want to distinguish severity explicitly
        # rather than infer it from `passed` alone.
        "hard_warnings": hard_warnings,
        "soft_warnings": soft_warnings,
        "needs_review": len(soft_warnings) > 0,
        "complete_title": complete_title,
        "roster_count": len(roster),
        "roster": roster,
        # Unchanged: full combined list, same order, same content as before
        # the severity split — every existing reader that just displays or
        # joins `warnings` keeps working byte-for-byte.
        "warnings": warnings,
        "gaps": gaps,
        "script_missing": script_missing,
        "script_extra": script_extra,
        "machine_bucket_counts": bucket_counts,
        "candidate_universe_count": candidate_universe_count,
        "roster_pacing_targets": pacing_targets,
        "has_recommended_final_roster": has_recommendation,
        "has_gap_hunt_matrix": has_gap_hunt,
        "operator_decision_count": len(operator_points) if isinstance(operator_points, list) else 0,
        "review_ready": is_review_ready,
    }


def _live_roster_gate(video: dict, payload: dict) -> dict:
    """The roster gate verdict, RECOMPUTED from the payload — never read back
    out of ``research_payload['unit_roster_validation']``.

    The stored copy is a point-in-time record of what the gate rules said on
    the day research ran. It is still written (for display and history), but a
    gate must never READ it, because doing so freezes that day's rules onto the
    row: a video rejected by a rule that has since been loosened or removed
    stays rejected forever, and the only way to clear it is to pay for a full
    research re-run that regenerates the entire roster and orphans its verified
    reference photos.

    That is not hypothetical. Video d2e37cd6 ("Every British Aircraft Carrier
    Class Ever Built") sat at idea_logged from 2026-07-27 onward on a stored
    ``passed: false`` whose ONLY complaint was roster pacing — 23 ships against
    a 20-minute runtime target. The C4 severity split (2026-07-29) reclassified
    exactly that complaint from fatal to soft, so the live rules score the same
    roster ``passed: true, needs_review: true``. The row never noticed.

    Safe to call anywhere: ``_roster_validation`` is a pure function of
    (title, payload, runtime) — no LLM, no network, no DB write. Both research
    stage gates run pre-script, so ``script_units`` is correctly omitted here;
    the script-time roster check passes its own units separately.
    """
    return _roster_validation(
        video.get("video_title") or video.get("headline") or "",
        payload,
        video_length_minutes=video.get("video_length_minutes"),
    )


def resolve_prompt(
    per_video: Optional[str],
    tenant: Optional[str],
    prompt_key: str,
    identity: "IdentityContext",
) -> Optional[str]:
    """Resolve a single system prompt for one pipeline stage. PURE + testable.

    Precedence: per-video override > tenant override > neutral engine template.
    The neutral fallback is `engine_templates.render(prompt_key, identity)` IF
    that key has a template; otherwise None (keys without a template — e.g.
    sound_curation / sound_generation — keep None so the bot's own neutral
    default is used).

    Whatever is chosen (override OR template), the identity placeholders are
    filled via `engine_templates.safe_fill` so the channel's identity is
    injected in every path while foreign braces ({HEADLINE}, {{x}}, …) survive
    verbatim. Phase 1 invariant: a tenant with a custom override still gets
    that override — we only fill identity slots and never overwrite it.

    C44 (P4.1e corrections loop): `identity.standing_preferences` — channel-
    scoped director_preferences (C15c), pre-formatted by
    `identity._standing_preferences_block` — is APPENDED after whichever
    source won, never templated into it. This is the extra precedence rung:
    explicit per-video prompt > tenant_prompt_defaults > standing preferences
    > identity-learned values > neutral template. A per-video/tenant override
    is a human-authored full prompt and still wins outright; but whatever text
    was chosen, the standing directions ride along on top of it, framed to
    override any CONFLICTING identity-LEARNED content (the neutral template's
    injected voice/niche/etc.) — mirroring C15c's chat framing verbatim.
    Empty when there are none / on a DB error, so this is a no-op for every
    tenant with no standing preferences.

    D6-3 (STORY-LAWS S3): for prompt_key == "script", story_laws.
    SCENE_LOCATION_LAW rides along the SAME way standing_preferences does —
    appended after whichever source won, so a tenant's own custom script
    prompt still carries the law instead of silently opting out of it. This
    is the ONE place path (a), the ACT-based docu generator, picks up S3:
    skills/video-pipeline/script/run.py reads `pipeline.script_system_prompt`
    (set from this function's return value) and passes it straight through
    as the LLM system prompt. The modeled-script path does NOT go through
    this function (it reads video.script_system_prompt directly — see
    pipeline_executor._run_modeled_script, which carries the same law text
    via its own inline prompt instead).

    D6-4 (STORY-LAWS S1): story_laws.LOCATION_TRANSIT_LAW rides along
    right after SCENE_LOCATION_LAW, same reasoning, same call site — a
    writer needs both laws at once (S3: one location per scene; S1: narrate
    the move between scenes) or it can satisfy one by breaking the other.

    D7-6 (STORY-LAWS S6): story_laws.SCRIPT_IS_SOURCE_OF_TRUTH_LAW rides
    along right after LOCATION_TRANSIT_LAW, same call site, same reasoning —
    the writer is told the script is canonical and that cast/environments/
    boards built from an older draft go stale the moment these words change,
    so it writes the full truth into the script rather than leaving it for
    an artifact generated from older text to (incorrectly) supply.

    Returns the resolved prompt string, or None when there's nothing to set
    (so the bot falls back to its built-in default).
    """
    def _nonblank(v):
        # Treat None and whitespace-only strings as "no override" so a blank
        # override falls through to the next source rather than producing an
        # empty prompt (mirrors identity.py's blank-is-missing philosophy).
        return v if (isinstance(v, str) and v.strip()) else None

    neutral = engine_templates.render(prompt_key, identity)  # "" if no template
    chosen = _nonblank(per_video) or _nonblank(tenant) or _nonblank(neutral)
    if chosen:
        filled = engine_templates.safe_fill(chosen, identity)
        law = ""
        if prompt_key == "script":
            import story_laws
            law = (
                "\n\n" + story_laws.SCENE_LOCATION_LAW
                + "\n\n" + story_laws.LOCATION_TRANSIT_LAW
                + "\n\n" + story_laws.SCRIPT_IS_SOURCE_OF_TRUTH_LAW
            )
        return filled + law + (getattr(identity, "standing_preferences", "") or "")
    return None


def _resolve_visual_profile_id(idea: dict) -> str:
    """Resolve the value written to the VISUAL_PROFILE env seam (checklist
    §2.1, C20 — the 5 rich Python visual-profile engines: neutral_v1,
    holographic_hud, cinematic_dossier, clay_mannequin, cinematic_illustration).

    Precedence: an explicit `style_preset_id` (routes/videos.py's
    create_video validates it against the style_presets table before it's
    ever stored, so its value ALWAYS matches a real
    shared.profiles.visual._PROFILE_MODULES key) wins over the legacy
    free-text `visual_style` column, which wins over the style-agnostic
    default. Fail-soft: a missing/blank style_preset_id (every video created
    before C20, and every video where a creator never picks one) falls
    straight through to the ORIGINAL behavior, byte-for-byte unchanged.

    idea's dict shape is Airtable-style field names (supabase_adapter.py's
    _row_to_idea) — pipeline_constants.IdeaFields is the source of truth
    for those keys, not the raw Supabase column names.
    """
    from orchestrator.pipeline_constants import IdeaFields
    return (
        (idea.get(IdeaFields.STYLE_PRESET_ID) or "").strip()
        or (idea.get(IdeaFields.VISUAL_STYLE) or "").strip()
        or "neutral_v1"
    )


def _resolve_script_profile_id(idea: dict) -> str:
    """Resolve the value written to the SCRIPT_PROFILE env seam (checklist
    §2.3, C24 — the editorial-voice engines in shared.profiles.script:
    neutral_v1, power_doctrine_v2, power_doctrine_v1).

    Mirrors _resolve_visual_profile_id's shape exactly: an explicit
    `script_profile` (routes/videos.py's create_video and update_video both
    validate it against shared.profiles.script.list_profiles() before it's
    ever stored, so its value ALWAYS names a real profile id) wins over the
    "neutral_v1" default. Fail-soft: a missing/blank script_profile (every
    video created before C24, and every video where a creator never opens
    Advanced) resolves to "neutral_v1" — the SAME value
    shared.profiles.script.load_script_profile() already falls back to when
    SCRIPT_PROFILE is unset (its own DEFAULT_PROFILE_ID), so this reproduces
    the pre-C24 script voice byte-for-byte. Power Doctrine is never the
    fallback here — it stays strictly opt-in (storyengine/CLAUDE.md: "Power
    Doctrine as a default identity" is deleted on purpose).

    idea's dict shape is Airtable-style field names (supabase_adapter.py's
    _row_to_idea) — pipeline_constants.IdeaFields is the source of truth
    for those keys, not the raw Supabase column names.
    """
    from orchestrator.pipeline_constants import IdeaFields
    return (idea.get(IdeaFields.SCRIPT_PROFILE) or "").strip() or "neutral_v1"


async def _cache_channel_thumbnail_blueprint(tenant_id: str, blueprint: str) -> None:
    """Cache a freshly-extracted thumbnail_blueprint onto channel_identity.

    Checklist C40: read-modify-write through the shared provenance helper
    (module-level, not a method, so it's independently unit-testable) so this
    best-effort cache write can never clobber identity_builder's fields,
    channel_format's visual_format/format_locked, or the _sources/_history
    envelope — this used to be a SQL `||` merge, which was fine for THIS one
    field but blind to the envelope."""
    import json as _json
    from channel_dna_meta import coerce_identity, stamp_identity_write

    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1", tenant_id)
    current = coerce_identity((row or {}).get("channel_identity"))
    merged = stamp_identity_write(
        current, {"thumbnail_blueprint": blueprint}, learner="thumbnail_formula"
    )
    await execute(
        "UPDATE channel_profiles SET channel_identity = $2::jsonb "
        "WHERE tenant_id = $1", tenant_id, _json.dumps(merged))


class PipelineExecutor:
    """Executes pipeline stages with StoryEngine integration.

    Wraps the existing pipeline skills and:
    - Loads API keys from Vault (fallback to .env)
    - Logs activity to bot_activity table
    - Updates video status in Supabase after each stage
    - Handles errors gracefully
    """

    def __init__(self, tenant_id: str):
        """Initialize the executor.

        Args:
            tenant_id: Supabase tenant ID for activity logging
        """
        self.tenant_id = tenant_id
        self._pipeline = None
        self._initialized = False

    async def _ensure_initialized(self):
        """Lazily initialize pipeline clients."""
        if self._initialized:
            return

        import sys
        print("[INIT] Starting pipeline initialization...", flush=True)

        # Load API keys from Vault into environment.
        # SECURITY: Clear ALL known pipeline env vars first to prevent cross-tenant
        # contamination. Without this, a previous tenant's keys persist in os.environ
        # and get picked up by downstream pipeline code that reads env vars directly.
        keys_to_load = [
            "anthropic_api_key",
            "airtable_api_key",
            "elevenlabs_api_key",
            # Narrator voice configuration (not API keys, same vault->env seam).
            # Without these the tenant's configured narrator voice/model is
            # silently ignored and every channel gets the process default —
            # seen live on DvsU 2026-07-07 (fixed voice is part of that brand).
            "elevenlabs_voice_id",
            "elevenlabs_model_id",
            "elevenlabs_voice_style",
            "kie_ai_api_key",
            "openai_api_key",
            "gemini_api_key",
        ]
        # Model/style tuning keys (NOT identity) have a legitimate process-level
        # default in the service .env (legacy single-tenant behavior). Snapshot
        # those before clearing so a tenant WITHOUT a vault override keeps the
        # .env engine-quality default instead of silently dropping to the
        # hardcoded default.
        #
        # elevenlabs_voice_id is DELIBERATELY EXCLUDED from this restore set.
        # C34b/S10-2: this used to include voice_id too, which meant ANY tenant
        # with no vault-configured voice got whatever ELEVENLABS_VOICE_ID sat in
        # this shared backend process's env — Ryan's own cloned voice, set in
        # storyengine/.env for his legacy single-tenant usage. That's a real
        # cross-tenant identity leak, not a helpful default: every SaaS tenant
        # who skipped the voice step narrated in Ryan's actual cloned voice.
        # Fix: a tenant-scoped run's voice chain is now vault (this tenant's
        # own elevenlabs_voice_id, loaded below) -> STOCK_NARRATOR_VOICE_ID (a
        # neutral ElevenLabs stock voice, passed explicitly to ElevenLabsClient
        # at construction below) — NEVER this process's env value, which
        # belongs to whichever identity's .env happens to be loaded. Ryan's
        # own legacy cron pipeline (skills/video-pipeline, a separate
        # process/env from this backend) is unaffected —
        # it reads ELEVENLABS_VOICE_ID directly from ITS OWN .env, never through
        # this tenant-scoped executor. For Ryan's storyengine tenant to keep his
        # cloned voice here, he needs his own vault-set elevenlabs_voice_id
        # (Settings -> API Keys, the field already exists) — same as any tenant.
        VOICE_CONFIG_KEYS = ("elevenlabs_model_id", "elevenlabs_voice_style")
        process_voice_defaults = {
            k.upper(): os.environ[k.upper()]
            for k in VOICE_CONFIG_KEYS
            if k.upper() in os.environ
        }
        env_names_to_clear = [k.upper() for k in keys_to_load] + ["WAVESPEED_API_KEY", "ANTHROPIC_BASE_URL"]
        for env_name in env_names_to_clear:
            os.environ.pop(env_name, None)

        for key_name in keys_to_load:
            print(f"[INIT] Loading key: {key_name}...", flush=True)
            try:
                value = await get_secret(key_name, self.tenant_id)
                if value:
                    env_name = key_name.upper()
                    os.environ[env_name] = value
                    # ElevenLabs client looks for WAVESPEED_API_KEY, not ELEVENLABS_API_KEY
                    if key_name == "elevenlabs_api_key":
                        os.environ["WAVESPEED_API_KEY"] = value
                    print(f"[INIT]   ✓ {key_name} loaded", flush=True)
                else:
                    print(f"[INIT]   - {key_name} not found", flush=True)
            except Exception as e:
                print(f"[INIT]   ✗ {key_name} error: {e}", flush=True)

        # Restore process-level voice defaults for keys no tenant override set.
        for env_name, value in process_voice_defaults.items():
            if not os.environ.get(env_name):
                os.environ[env_name] = value
                print(f"[INIT]   ↩ {env_name} restored from process env (no tenant override)", flush=True)

        # Claude runs on DIRECT Anthropic (the tenant's anthropic_api_key loaded
        # above) — it's the reliable path. Kie is ONLY a fallback for Claude when a
        # tenant has no Anthropic key (the Kie gateway 500s/hangs and drops image
        # blocks). Images/video always use Kie. On fallback, AnthropicClient reads
        # ANTHROPIC_BASE_URL and switches to Bearer auth + undated model aliases.
        if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("KIE_AI_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = os.environ["KIE_AI_API_KEY"]
            os.environ["ANTHROPIC_BASE_URL"] = os.getenv(
                "KIE_CLAUDE_BASE_URL", "https://api.kie.ai/claude"
            )
            print("[INIT] Claude routed via Kie.ai gateway (no direct Anthropic key)", flush=True)

        # Create a lightweight pipeline object that only has what we need.
        # We can't import VideoPipeline directly because it imports ALL clients
        # (Slack, Google, ElevenLabs, etc.) which hang if services are unavailable.
        print("[INIT] Creating lightweight pipeline...", flush=True)

        from supabase_adapter import SupabaseAdapter

        class LightPipeline:
            """Minimal pipeline that only has the clients we need."""

            scene_filter = None
            image_filter = None
            should_cancel = None  # armed per-run by _install_cancel_support
            character_reference_urls = None  # approved cast, loaded per-run

            @property
            def _is_targeted_run(self):
                """True if scene/image filters are set (partial run, don't advance status)."""
                return self.scene_filter is not None or self.image_filter is not None

            def _log_filters(self):
                """Print active targeting filters."""
                if self.scene_filter is not None and self.image_filter is not None:
                    print(f"  🎯 TARGETED RUN: Scene {self.scene_filter}, Image {self.image_filter}")
                elif self.scene_filter is not None:
                    print(f"  🎯 TARGETED RUN: Scene {self.scene_filter} (all images)")

            def _filter_by_scene(self, records, scene_key="Scene"):
                """Filter records by scene_filter and image_filter if set."""
                if self.scene_filter is not None:
                    records = [r for r in records if r.get(scene_key) == self.scene_filter]
                if self.image_filter is not None:
                    from orchestrator.pipeline_constants import ImageFields
                    records = [r for r in records if r.get(ImageFields.IMAGE_INDEX) == self.image_filter]
                return records

            def _update_status(self, new_status):
                """Update idea status in the adapter and in-memory cache."""
                from orchestrator.pipeline_constants import IdeaFields
                if self.current_idea:
                    self.airtable.update_idea_status(self.current_idea_id, new_status)
                    self.current_idea[IdeaFields.STATUS] = new_status

        self._pipeline = LightPipeline()
        self._pipeline.airtable = SupabaseAdapter(tenant_id=self.tenant_id)
        print("[INIT] SupabaseAdapter OK", flush=True)

        # Anthropic client — required for research, script, prompts
        try:
            from shared.clients.anthropic_client import AnthropicClient
            self._pipeline.anthropic = AnthropicClient()
            print("[INIT] AnthropicClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] AnthropicClient skipped: {e}", flush=True)
            self._pipeline.anthropic = None

        # Try to load optional clients (non-blocking)
        try:
            from shared.clients.google_client import GoogleClient
            # strict_folder: backend's shared app-owned Drive identity — see
            # google_client.py's DEFAULT_PARENT_FOLDER_ID docstring.
            self._pipeline.google = GoogleClient(strict_folder=True)
            print("[INIT] GoogleClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] GoogleClient skipped: {e}", flush=True)
            # No-op google client that returns safe defaults
            class NoOpGoogle:
                def get_or_create_folder(self, *a, **kw):
                    return {"id": "no-google-drive"}
                def __getattr__(self, name):
                    return lambda *a, **kw: None
            self._pipeline.google = NoOpGoogle()

        try:
            from shared.clients.slack_client import SlackClient
            self._pipeline.slack = SlackClient()
            print("[INIT] SlackClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] SlackClient skipped: {e}", flush=True)
            # Create a no-op slack client
            class NoOpSlack:
                def __getattr__(self, name):
                    """Return a no-op for any method call."""
                    return lambda *a, **kw: None
            self._pipeline.slack = NoOpSlack()

        try:
            from shared.clients.image_client import ImageClient
            self._pipeline.image_client = ImageClient(
                google_client=self._pipeline.google, tenant_id=self.tenant_id)
            print("[INIT] ImageClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] ImageClient skipped: {e}", flush=True)
            self._pipeline.image_client = None

        try:
            from shared.clients.elevenlabs_client import ElevenLabsClient
            # C34b/S10-2: resolve the voice EXPLICITLY from this tenant's own
            # current env state (set above from vault, or absent — never
            # restored from a process default, see VOICE_CONFIG_KEYS note),
            # falling back to the tenant-neutral stock voice. Passed as an
            # explicit constructor arg rather than letting ElevenLabsClient
            # fall through to its own os.getenv/DEFAULT_VOICE_ID resolution —
            # that class-level default is computed once at first import in
            # this shared process and must not be trusted as a per-tenant seam.
            resolved_voice_id = os.environ.get("ELEVENLABS_VOICE_ID") or STOCK_NARRATOR_VOICE_ID
            self._pipeline.elevenlabs = ElevenLabsClient(voice_id=resolved_voice_id)
            print(f"[INIT] ElevenLabsClient OK (voice={resolved_voice_id})", flush=True)
        except Exception as e:
            print(f"[INIT] ElevenLabsClient skipped: {e}", flush=True)
            self._pipeline.elevenlabs = None

        try:
            from shared.clients.gemini_client import GeminiClient
            self._pipeline.gemini = GeminiClient()
            print("[INIT] GeminiClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] GeminiClient skipped: {e}", flush=True)
            self._pipeline.gemini = None

        # Pipeline state properties (set by _load_idea)
        self._pipeline.current_idea = None
        self._pipeline.current_idea_id = None
        self._pipeline.video_title = None
        self._pipeline.visual_style = None
        self._pipeline.project_folder_id = None
        self._pipeline.google_doc_id = None
        self._pipeline.core_image_url = None
        self._pipeline.video_config = None
        self._pipeline._duration_was_set = True

        # Import pipeline helper methods we need
        from orchestrator.pipeline_config import VideoConfig
        from orchestrator.pipeline_constants import IdeaFields, Statuses

        def _load_idea(idea):
            """Load an idea record into pipeline state."""
            self._pipeline.current_idea = idea
            self._pipeline.current_idea_id = idea.get("id")
            self._pipeline.video_title = idea.get(IdeaFields.VIDEO_TITLE, "")
            # Point the title→id adapter at THIS exact video so script scene
            # reads/writes can't misroute to a duplicate-titled video (the
            # adapter otherwise resolves by title with LIMIT 1).
            try:
                self._pipeline.airtable.current_video_id = idea.get("id")
            except Exception:
                pass
            # Style-agnostic default; an explicit tenant choice still wins.
            # C20: a validated style_preset_id (the 5 rich Python profile
            # engines) takes precedence over the legacy free-text field —
            # see _resolve_visual_profile_id's docstring for the fail-soft
            # precedence chain.
            visual_style = _resolve_visual_profile_id(idea)
            self._pipeline.visual_style = visual_style
            # The skill pipeline resolves the visual profile via this env var
            # (load_profile() reads VISUAL_PROFILE). The backend's _load_idea
            # override never set it before, so every tenant silently got the
            # registry default — set it here so the tenant's chosen profile is
            # honored and an unset tenant gets the neutral engine.
            os.environ["VISUAL_PROFILE"] = visual_style
            # Per-run RESET of the channel look (the neutral profile injects it
            # at build time). Set unconditionally so a previous tenant's value
            # can never leak in. The per-video override is the floor here; the
            # image stages upgrade this to the full identity look (which falls
            # back to the channel's style_description) via _export_visual_style.
            os.environ["VISUAL_STYLE_DESCRIPTION"] = (
                idea.get(IdeaFields.IMAGE_STYLE_OVERRIDE) or ""
            ).strip()
            # C24: same seam shape as VISUAL_PROFILE just above — the skill
            # pipeline's brief_translator resolves the editorial voice via
            # this env var (shared.profiles.script.load_script_profile()
            # reads SCRIPT_PROFILE, called with no args at
            # script/brief_translator/__init__.py's `self.profile =
            # load_script_profile()`). Set unconditionally (not only when a
            # per-video pick exists) so a previous tenant's/run's value can
            # never leak into this one — the resolver's own "neutral_v1"
            # fallback keeps this byte-identical to the pre-C24 default.
            os.environ["SCRIPT_PROFILE"] = _resolve_script_profile_id(idea)
            self._pipeline.project_folder_id = idea.get(IdeaFields.DRIVE_FOLDER_ID, "")
            # Video config
            video_length = idea.get(IdeaFields.VIDEO_LENGTH_MIN)
            if video_length:
                self._pipeline._duration_was_set = True
                self._pipeline.video_config = VideoConfig(video_length_minutes=int(float(video_length)))
            else:
                self._pipeline._duration_was_set = False
                self._pipeline.video_config = VideoConfig(video_length_minutes=10)
            # Core image
            core_img = idea.get(IdeaFields.CORE_IMAGE)
            if isinstance(core_img, list) and core_img:
                self._pipeline.core_image_url = core_img[0].get("url")

        self._pipeline._load_idea = _load_idea

        def _update_status(new_status):
            """Update status via adapter (pipeline skills call this)."""
            if self._pipeline.current_idea_id:
                self._pipeline.airtable.update_idea_status(
                    self._pipeline.current_idea_id, new_status
                )

        self._pipeline._update_status = _update_status

        def get_idea_by_status(status):
            ideas = self._pipeline.airtable.get_ideas_by_status(status, limit=1)
            return ideas[0] if ideas else None

        self._pipeline.get_idea_by_status = get_idea_by_status

        # Pipeline filter properties (used by some bot stages)
        self._pipeline.image_filter = None
        self._pipeline.scene_filter = None
        self._pipeline.channel_profile = None

        @property
        def _is_targeted_run(pipe):
            return pipe.scene_filter is not None or pipe.image_filter is not None

        LightPipeline._is_targeted_run = _is_targeted_run

        def _log_filters():
            if self._pipeline.scene_filter is not None:
                print(f"  🎯 Scene filter: {self._pipeline.scene_filter}", flush=True)
            if self._pipeline.image_filter is not None:
                print(f"  🎯 Image filter: {self._pipeline.image_filter}", flush=True)

        self._pipeline._log_filters = _log_filters

        # Import pipeline stage runners (lazy — they import their own deps)
        async def run_brief_translator():
            from script.run import run
            return await run(self._pipeline)

        async def run_voice_bot():
            from voice.run import run
            return await run(self._pipeline)

        async def run_styled_image_prompts():
            from image_prompts.run import run
            return await run(self._pipeline)

        async def run_image_bot():
            from images.run import run
            return await run(self._pipeline)

        async def run_video_script_bot():
            from video_motion.run_scripts import run
            return await run(self._pipeline)

        async def run_video_gen_bot():
            from video_motion.run_generate import run
            return await run(self._pipeline)

        async def run_thumbnail_bot():
            from thumbnail.run import run
            return await run(self._pipeline)

        async def run_render_bot():
            from render.run import run
            return await run(self._pipeline)

        async def run_sound_prompt_bot():
            from sound.run_design import run
            return await run(self._pipeline)

        async def run_sound_bot():
            from sound.run_effects import run
            return await run(self._pipeline)

        async def run_storyboard_prompts(scene_filter=None, progress_callback=None):
            """Run storyboard prompt generation for the pipeline, optionally filtered by scene."""
            from storyboard.run import run
            return await run(self._pipeline, scene_filter=scene_filter, progress_callback=progress_callback)

        async def run_storyboard_images(scene_filter=None, progress_callback=None):
            from storyboard.run_images import run
            return await run(self._pipeline, scene_filter=scene_filter, progress_callback=progress_callback)

        async def run_storyboard_extract():
            from storyboard.run_extract import run
            return await run(self._pipeline)

        self._pipeline.run_brief_translator = run_brief_translator
        self._pipeline.run_voice_bot = run_voice_bot
        self._pipeline.run_styled_image_prompts = run_styled_image_prompts
        self._pipeline.run_image_bot = run_image_bot
        self._pipeline.run_video_script_bot = run_video_script_bot
        self._pipeline.run_video_gen_bot = run_video_gen_bot
        self._pipeline.run_thumbnail_bot = run_thumbnail_bot
        self._pipeline.run_render_bot = run_render_bot
        self._pipeline.run_sound_prompt_bot = run_sound_prompt_bot
        self._pipeline.run_sound_bot = run_sound_bot
        self._pipeline.run_storyboard_prompts = run_storyboard_prompts
        self._pipeline.run_storyboard_images = run_storyboard_images
        self._pipeline.run_storyboard_extract = run_storyboard_extract

        print("[INIT] Pipeline ready!", flush=True)

        self._initialized = True

    async def _log_activity(
        self,
        bot_name: str,
        video_id: Optional[str],
        status: str,
        message: Optional[str] = None,
        cost: float = 0,
    ):
        """Log activity to bot_activity table.

        Args:
            bot_name: Name of the bot (e.g., "Research Agent")
            video_id: Supabase video UUID
            status: One of: started, running, completed, failed
            message: Optional status message
            cost: Cost in USD
        """
        # Humanize at the write boundary so /api/activity never returns
        # raw str(e) to the UI. ~20 call sites in this file pass
        # error_msg = str(e) → here — one line covers all of them.
        safe_message = message
        if status == "failed" and message:
            safe_message = humanize_error(message)
        try:
            await execute(
                """INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message, cost)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                self.tenant_id, bot_name, video_id, status, safe_message, cost,
            )
        except Exception as e:
            print(f"Failed to log activity: {e}")

    async def _get_video(self, video_id: str) -> Optional[dict]:
        """Get video from Supabase by ID."""
        return await fetch_one(
            "SELECT * FROM videos WHERE id = $1 AND tenant_id = $2",
            video_id, self.tenant_id,
        )

    async def _fetch_source_text(self, client: Any, url: str) -> str:
        """Fetch one search result and extract visible text for excerpt verification."""
        if not url:
            return ""
        try:
            response = await client.get(url)
            if response.status_code >= 400:
                return ""
            content_type = str(response.headers.get("content-type") or "").lower()
            if "pdf" in content_type or url.lower().split("?")[0].endswith(".pdf"):
                import io
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(response.content))
                return " ".join((page.extract_text() or "") for page in reader.pages[:8])
            return _html_to_visible_text(response.text)
        except Exception as exc:  # noqa: BLE001 - source fetch failures are represented in validation.
            _logger.info("[machine-source] fetch failed for %s: %s", url[:140], str(exc)[:120])
            return ""

    async def _wayback_snapshot_url(self, client: Any, url: str) -> str:
        """Resolve the newest REAL Wayback Machine snapshot of `url` via the
        availability API. GAP 1(b), 2026-07-30: an agent CLAIMING an archive
        capture exists is not evidence - a gather agent reported verifying an
        excerpt against a snapshot the archive provably does not hold (the Ark
        Royal S8 incident) - so a snapshot URL is only ever used when this API
        actually returned it. Empty string on any failure or missing snapshot."""
        if not url:
            return ""
        try:
            response = await client.get(
                "https://archive.org/wayback/available", params={"url": url}
            )
            if response.status_code >= 400:
                return ""
            snap = (response.json().get("archived_snapshots") or {}).get("closest") or {}
            return str(snap.get("url") or "").strip()
        except Exception as exc:  # noqa: BLE001 - fallback failures fall through to the next leg.
            _logger.info("[machine-source] wayback availability lookup failed for %s: %s", url[:140], str(exc)[:120])
            return ""

    async def _fetch_source_fallback_text(self, client: Any, url: str) -> tuple[str, str]:
        """When a live fetch AND Tavily's own raw content both come back
        empty, try the two fallback legs ported from the DVsU research
        simulator's build_package.py (GAP 1b, 2026-07-30), in order:

        1. If the URL is a National Archives Discovery record page, its own
           JSON API - retried a few times, because the API answers an empty
           202 Accepted while it warms a cold record, and one empty response
           is not evidence of absence (2 genuine Tier-1 records were wrongly
           dropped over this in the simulator).
        2. A REAL Wayback Machine snapshot resolved through the availability
           API (never a claimed/fabricated archive URL).

        Returns (text, capture_method_label); ("", "") when neither leg
        produces text."""
        match = _NATIONAL_ARCHIVES_DISCOVERY_RECORD_RE.search(url or "")
        if match:
            api_url = f"https://discovery.nationalarchives.gov.uk/API/records/v1/details/{match.group(1)}"
            text = ""
            for attempt in range(3):
                text = await self._fetch_source_text(client, api_url)
                if text:
                    break
                if attempt < 2:
                    await asyncio.sleep(3)
            if text:
                return text, "national_archives_api"
        snapshot_url = await self._wayback_snapshot_url(client, url)
        if snapshot_url:
            text = await self._fetch_source_text(client, snapshot_url)
            if text:
                return text, f"{_WAYBACK_CAPTURE_METHOD_PREFIX}{snapshot_url}"
        return "", ""

    async def _gather_verified_machine_source_package(self, title: str, machine: str, payload: dict) -> dict:
        """Search the live internet, fetch pages, and save exact excerpt candidates for one machine.

        This is deliberately pre-LLM. Claude may summarize or select after this,
        but it may not invent source text because card validation checks against
        this package.
        """
        cache_key = _verified_source_cache_key(machine)
        cached = ((payload or {}).get("machine_raw_source_packages") or {}).get(cache_key)
        cached = _verified_machine_source_package_with_anton_metadata(cached, machine)
        # G14, 2026-07-31: an advisory-only tier gap (e.g. no Tier 1-2 source)
        # must not defeat cache reuse - that would silently re-spend a paid
        # Tavily search on every call for a package that's otherwise fine.
        if (
            _verified_machine_source_package_ready(cached)
            and not _blocking_warnings(_verified_machine_source_package_quality_errors(cached, machine))
            and not _verified_machine_source_package_identity_errors(cached, machine)
        ):
            return cached

        tavily_key = await get_secret("tavily_api_key", self.tenant_id)
        if not tavily_key:
            return {
                "passed": False,
                "machine": machine,
                "machine_key": cache_key,
                "errors": ["Tavily API key is required for verified one-machine internet research."],
                "candidate_excerpts": [],
                "sources": [],
            }

        queries = _verified_machine_source_queries(title, machine)
        is_naval = _is_naval_gather_context(title, machine)

        import httpx as _httpx

        search_results: list[dict] = []
        errors: list[str] = []
        skipped_search_queries: list[str] = []
        headers = {"User-Agent": "StoryEngine/1.0 (verified source research)"}
        async with _httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
            search_passes = [(query, None) for query in queries]
            # GAP 1(c), 2026-07-30: iwm.org.uk 403s every automated fetch (curl,
            # WebFetch - all of it), so a search hit there can never become a
            # usable candidate; excluding it stops it burning a source slot on
            # every single call. For a ship/naval machine, add domain-grouped
            # steering calls scoped to the DVsU research simulator's proven
            # fetchable Commonwealth/naval anchors (gather_brief_template.txt)
            # so the roster's best sources are not all behind IWM's bot-wall.
            # G13, 2026-07-31: this used to be ONE call covering all 6 domains
            # combined (max_results=5 diluted across every domain) - Duke of
            # York and Anson got zero awm/rmg/gov.uk hits with no fetch
            # errors, just not in that combined top 5. Grouped calls give
            # each domain pair its own max_results=5 shot.
            if is_naval:
                for domain_group in _NAVAL_STEERING_DOMAIN_GROUPS:
                    search_passes.append((_naval_museum_domain_query(machine), list(domain_group)))

            # Cost bound: never exceed _MAX_VERIFIED_SOURCE_TAVILY_CALLS_PER_MACHINE
            # calls for this machine, base queries + steering + the reworded
            # retry pass below combined. Anything trimmed is logged, never
            # silently dropped.
            retry_reserve = 1 if is_naval else 0
            wave_budget = max(0, _MAX_VERIFIED_SOURCE_TAVILY_CALLS_PER_MACHINE - retry_reserve)
            if len(search_passes) > wave_budget:
                skipped_search_queries = [query for query, _ in search_passes[wave_budget:]]
                search_passes = search_passes[:wave_budget]

            calls_used = 0

            async def _run_search_pass(query: str, include_domains: Optional[list[str]]) -> None:
                nonlocal calls_used
                calls_used += 1
                try:
                    body = {
                        "api_key": tavily_key,
                        "query": query,
                        "search_depth": "advanced",
                        "include_answer": False,
                        "include_raw_content": True,
                        "max_results": 5,
                        "exclude_domains": list(_BLOCKED_AUTOMATION_SOURCE_DOMAINS),
                    }
                    if include_domains:
                        body["include_domains"] = include_domains
                    response = await client.post("https://api.tavily.com/search", json=body)
                    if response.status_code >= 400:
                        errors.append(f"Tavily search failed for {query}: HTTP {response.status_code}")
                        return
                    for item in (response.json().get("results") or []):
                        if isinstance(item, dict) and item.get("url"):
                            item = dict(item)
                            item["_query"] = query
                            search_results.append(item)
                except Exception as exc:  # noqa: BLE001 - keep gathering from remaining queries.
                    errors.append(f"Tavily search failed for {query}: {str(exc)[:120]}")

            for query, include_domains in search_passes:
                await _run_search_pass(query, include_domains)

            sources: list[dict] = []
            candidate_excerpts: list[dict] = []
            search_result_audit: list[dict] = []
            seen_urls: set[str] = set()

            async def _process_search_result(item: dict) -> None:
                url = str(item.get("url") or "").strip()
                title_text = str(item.get("title") or url).strip()
                query = item.get("_query")
                if not url:
                    return
                if url in seen_urls:
                    search_result_audit.append({
                        "url": url,
                        "title": title_text,
                        "query": query,
                        "accepted": False,
                        "rejected_reason": "duplicate_url",
                    })
                    return
                seen_urls.add(url)
                fetched_text = await self._fetch_source_text(client, url)
                raw_content = str(item.get("raw_content") or "")
                source_variants: list[tuple[tuple[int, int, int, int], str, str, list[str]]] = []
                variant_audit: list[dict] = []

                def _register_variant(capture_method: str, source_text: str, method_priority: int) -> bool:
                    variant_row = {
                        "source_capture_method": capture_method,
                        "text_chars": len(source_text or ""),
                        "text_hash": _source_text_fingerprint(source_text) if source_text else "",
                        "mentions_machine": bool(source_text and _mentions_machine(source_text, machine)),
                    }
                    if not source_text:
                        variant_row["rejected_reason"] = "empty_capture"
                        variant_audit.append(variant_row)
                        return False
                    if not variant_row["mentions_machine"]:
                        variant_row["rejected_reason"] = "machine_not_found_in_capture"
                        variant_audit.append(variant_row)
                        return False
                    excerpt_candidates = _sentence_candidates_from_source(source_text, machine, limit=10)
                    variant_row["excerpt_count"] = len(excerpt_candidates)
                    if not excerpt_candidates:
                        variant_row["rejected_reason"] = "no_sentence_excerpt_candidates"
                        variant_audit.append(variant_row)
                        return False
                    coverage_score = _machine_source_variant_score(excerpt_candidates, machine)
                    variant_row.update({
                        "covered_slot_count": coverage_score[0],
                        "distinct_slot_excerpt_count": coverage_score[1],
                        "method_priority": method_priority,
                    })
                    variant_audit.append(variant_row)
                    source_variants.append(((*coverage_score, method_priority), capture_method, source_text, excerpt_candidates))
                    return True

                for capture_method, source_text in (
                    ("fetched_page", fetched_text),
                    ("tavily_raw_content", raw_content),
                ):
                    _register_variant(capture_method, source_text, 1 if capture_method == "fetched_page" else 0)

                if not source_variants:
                    # GAP 1(b), 2026-07-30: the direct fetch AND Tavily's own raw
                    # content both came back empty (e.g. iwm.org.uk 403ing the
                    # request) - fall back exactly as the DVsU research
                    # simulator's build_package.py does before giving up on this
                    # source entirely. Lowest method_priority: a live capture is
                    # always preferred over an archived one on a genuine tie.
                    fallback_text, fallback_method = await self._fetch_source_fallback_text(client, url)
                    if fallback_text and fallback_method:
                        _register_variant(fallback_method, fallback_text, -1)

                if not source_variants:
                    search_result_audit.append({
                        "url": url,
                        "title": title_text,
                        "query": query,
                        "accepted": False,
                        "rejected_reason": "no_exact_text_variant",
                        "variants": variant_audit,
                    })
                    return
                _score, capture_method, source_text, excerpt_candidates = max(
                    source_variants,
                    key=lambda row: row[0],
                )
                variant_selection = _machine_source_variant_selection_metadata(
                    source_variants,
                    capture_method,
                )
                source_id = f"S{len(sources) + 1}"
                source_hash = _source_text_fingerprint(source_text)
                source_tier = _source_tier_for_url(url, title_text)
                sources.append({
                    "source_id": source_id,
                    "title": title_text,
                    "url": url,
                    "source_tier": source_tier["tier"],
                    "source_tier_label": source_tier["label"],
                    "query": item.get("_query"),
                    "source_capture_method": capture_method,
                    "source_variant_selection": variant_selection,
                    "text_hash": source_hash,
                    "text_chars": len(source_text),
                })
                search_result_audit.append({
                    "url": url,
                    "title": title_text,
                    "query": query,
                    "accepted": True,
                    "source_id": source_id,
                    "selected_capture_method": capture_method,
                    "source_tier": source_tier["tier"],
                    "source_tier_label": source_tier["label"],
                    "source_variant_selection": variant_selection,
                    "variants": [
                        {
                            **row,
                            "selected": row.get("source_capture_method") == capture_method,
                        }
                        for row in variant_audit
                    ],
                })
                for excerpt in excerpt_candidates:
                    excerpt_id = f"{source_id}-E{len([e for e in candidate_excerpts if e.get('source_id') == source_id]) + 1}"
                    candidate_excerpts.append({
                        "excerpt_id": excerpt_id,
                        "source_id": source_id,
                        "source_title": title_text,
                        "source_url": url,
                        "source_tier": source_tier["tier"],
                        "source_tier_label": source_tier["label"],
                        "source_capture_method": capture_method,
                        "source_variant_selection": variant_selection,
                        "locator": f"{excerpt_id}; query={item.get('_query')}",
                        "text": excerpt,
                        "text_hash": _source_text_fingerprint(excerpt),
                    })
                    if len(candidate_excerpts) >= 60:
                        break

            for item in search_results:
                if len(candidate_excerpts) >= 60:
                    break
                await _process_search_result(item)

            # G13, 2026-07-31: naval steering (base queries + domain-grouped
            # calls above) can still land zero Tier 1-2 candidates - Duke of
            # York and Anson both did, with no fetch errors, the domains just
            # never surfaced a museum/official hit in that pass. One reworded,
            # domain-unrestricted retry, bounded by the same call budget,
            # before giving up on a Tier 1-2 anchor for this machine.
            if (
                is_naval
                and calls_used < _MAX_VERIFIED_SOURCE_TAVILY_CALLS_PER_MACHINE
                and not any(1 <= _source_tier_number(c) <= 2 for c in candidate_excerpts)
            ):
                retry_query = _naval_reworded_retry_query(machine)
                pre_retry_count = len(search_results)
                await _run_search_pass(retry_query, None)
                for item in search_results[pre_retry_count:]:
                    if len(candidate_excerpts) >= 60:
                        break
                    await _process_search_result(item)

        if skipped_search_queries:
            errors.append(
                f"Verified source gathering skipped {len(skipped_search_queries)} "
                f"quer(y/ies) past the {_MAX_VERIFIED_SOURCE_TAVILY_CALLS_PER_MACHINE}-call "
                "budget: " + "; ".join(skipped_search_queries)
            )

        package = {
            "passed": len(candidate_excerpts) >= 6,
            "schema_version": 3,
            "machine": machine,
            "machine_key": cache_key,
            "search_queries": queries,
            "sources": sources,
            "search_result_audit": search_result_audit,
            "candidate_excerpts": candidate_excerpts,
            "errors": errors,
            "gathered_at": datetime.now(timezone.utc).isoformat(),
        }
        package["source_slot_coverage"] = _anton_source_slot_coverage(candidate_excerpts, machine)
        package["traceable_source_slot_coverage"] = _anton_source_slot_coverage(
            [item for item in candidate_excerpts if _verified_source_candidate_traceable(item)],
            machine,
        )
        quality_errors = _verified_machine_source_package_quality_errors(package, machine)
        # G14, 2026-07-31: package["passed"] is what _verified_machine_source_
        # package_ready() gates on everywhere - it must only go False for a
        # genuinely BLOCKING quality error, or the (now advisory) tier-only
        # gaps demoted above would still hard-block card writing through
        # this back door. Advisory-only errors still get recorded in
        # package["errors"] for visibility.
        if _blocking_warnings(quality_errors):
            package["passed"] = False
        if quality_errors:
            package["errors"] = list(dict.fromkeys(errors + quality_errors))
        if not package["passed"] and not package["errors"]:
            package["errors"] = [
                "Verified source gathering found fewer than six exact machine-matching excerpts."
            ]
        return package

    async def _load_machine_research_cards(
        self,
        video_id: str,
        payload: dict,
        roster: Optional[list[str]] = None,
        target_machine: Optional[str] = None,
    ) -> dict:
        """Merge trustworthy compact rows into legacy cards in locked-roster order.

        Keyed by roster_index (migration 153), not machine_key: two distinct
        roster entries can normalize to the same machine_key, so a
        machine_key-keyed merge would silently collapse two different
        machines' cards into one (see _roster_index_for_identity)."""
        if not isinstance(payload, dict):
            payload = {}
        roster = roster or [
            _unit_display_name(item) for item in (payload.get("unit_roster") or [])
            if _unit_display_name(item)
        ]
        if not roster:
            return payload
        target_index = _roster_index_for_identity(roster, target_machine) if target_machine else None
        try:
            if target_index:
                rows = await fetch_all(
                    """SELECT machine_key, machine_name, roster_index, card, validation
                       FROM machine_research_cards
                       WHERE tenant_id = $1 AND video_id = $2 AND roster_index = $3
                       ORDER BY roster_index""",
                    self.tenant_id, video_id, target_index,
                )
            else:
                rows = await fetch_all(
                    """SELECT machine_key, machine_name, roster_index, card, validation
                       FROM machine_research_cards
                       WHERE tenant_id = $1 AND video_id = $2
                       ORDER BY roster_index""",
                    self.tenant_id, video_id,
                )
        except Exception as exc:  # migration-safe compatibility fallback
            _logger.warning("[machine-research] compact read unavailable: %s", str(exc)[:150])
            return payload
        cards_by_index: dict[int, dict] = {}
        # G13, 2026-07-31 (bonus fix): a row here is dropped for two very
        # different reasons - (a) it doesn't actually belong to this roster
        # slot (stale/mismatched identity - a real "no card" case), or (b) it
        # belongs here but the referee rejected it (validation.passed is
        # False - a card EXISTS with a REAL, specific rejection reason).
        # Both used to fall through the same `continue`, so a caller like
        # _run_unit_research_hold's _full_research_validation, which only
        # sees the post-drop unit_research_cards list, could not tell "never
        # researched" from "researched and rejected" and reported the
        # misleading "missing saved one-machine research card" for a machine
        # that actually failed the referee with specific, named warnings
        # (e.g. "evidence_segments missing required Anton slots for:
        # original_problem, engineering_decision, tradeoff, reality").
        # Stashing the real verdict here lets that caller name the real
        # reason while every other caller's "trustworthy cards only" merge
        # (cards_by_index / cards below) is completely unchanged.
        dropped_failed_validations: dict[str, dict] = {}
        for card in payload.get("unit_research_cards") or []:
            if not isinstance(card, dict):
                continue
            identity = card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or ""
            index = _roster_index_for_identity(roster, identity)
            if index:
                cards_by_index[index] = card
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("card"), dict):
                continue
            row_index = row.get("roster_index")
            if not isinstance(row_index, int) or row_index < 1 or row_index > len(roster):
                continue
            expected_key = _normalized_unit_code(roster[row_index - 1])
            name_key = _normalized_unit_code(str(row.get("machine_name") or ""))
            card = row["card"]
            identity = card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or ""
            card_index = _roster_index_for_identity(roster, identity)
            if not expected_key or name_key != expected_key or card_index != row_index:
                continue
            validation = row.get("validation") or {}
            if isinstance(validation, dict) and validation.get("passed") is False:
                dropped_failed_validations[expected_key] = {
                    "machine_name": str(row.get("machine_name") or roster[row_index - 1]),
                    "roster_index": row_index,
                    "warnings": [
                        str(item).strip() for item in (validation.get("warnings") or []) if str(item).strip()
                    ],
                }
                continue
            cards_by_index[row_index] = card
        cards = [cards_by_index[index] for index in range(1, len(roster) + 1) if index in cards_by_index]
        hydrated = dict(payload)
        hydrated["unit_research_cards"] = cards
        if dropped_failed_validations:
            hydrated["_dropped_failed_research_card_validations"] = dropped_failed_validations
        return hydrated

    @staticmethod
    def _compact_store_unavailable(exc: Exception) -> bool:
        """True only for rollout compatibility or database availability errors."""
        sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
        if sqlstate in {"42P01", "42703", "57P01", "57P02", "57P03", "08000", "08001", "08003", "08004", "08006"}:
            return True
        message = str(exc).lower()
        return any(token in message for token in (
            "undefined table", "does not exist", "connection refused", "connection closed",
            "connection reset", "database is unavailable",
        ))

    @staticmethod
    def _db_write_missed(result: Any) -> bool:
        """True when asyncpg reports a write matched no rows."""
        if not isinstance(result, str):
            return False
        tag = " ".join(result.strip().upper().split())
        return tag in {"UPDATE 0", "INSERT 0 0"}

    async def _upsert_machine_research_card(
        self, video_id: str, machine: str, roster_index: int, card: dict, validation: dict
    ) -> None:
        """Checkpoint one compact card under exact tenant/video/roster-slot identity.

        Keyed by roster_index (migration 153), not machine_key: two distinct
        locked roster entries can legitimately normalize to the same
        machine_key (e.g. two "-class" ship variants), so a machine_key
        conflict target would let the second entry's write silently clobber
        the first's row instead of the two coexisting. machine_key stays
        populated on every write for the informational/no-collision lookups
        that still use it, it just no longer decides row identity.
        """
        import json
        machine_key = _normalized_unit_code(machine)
        if not machine_key:
            raise ValueError("compact machine research card requires a non-empty machine key")
        try:
            result = await execute(
                """INSERT INTO machine_research_cards
                 (tenant_id, video_id, machine_key, machine_name, roster_index, card, validation)
               SELECT $1, v.id, $3, $4, $5, $6::jsonb, $7::jsonb
               FROM videos v WHERE v.id = $2 AND v.tenant_id = $1
               ON CONFLICT (tenant_id, video_id, roster_index) DO UPDATE SET
                 machine_key = EXCLUDED.machine_key,
                 machine_name = EXCLUDED.machine_name,
                 card = EXCLUDED.card,
                 validation = EXCLUDED.validation,
                 updated_at = now()""",
                self.tenant_id, video_id, machine_key, machine,
                roster_index, json.dumps(card), json.dumps(validation),
            )
            if self._db_write_missed(result):
                raise RuntimeError("compact machine research card checkpoint refused because the video is no longer available for this tenant")
        except Exception as exc:
            if not self._compact_store_unavailable(exc):
                raise
            _logger.warning("[machine-research] compact write unavailable; legacy checkpoint retained: %s", str(exc)[:150])

    async def _update_machine_research_validation(
        self, video_id: str, machine: str, roster_index: int, validation: dict
    ) -> None:
        """Persist a fresh referee verdict for one stored card (validation column ONLY).

        Called from READ paths (the no-spend readiness check), so it is
        UPDATE-only by design: it never INSERTs a row and never writes card
        text computed on a read. A card row that does not exist yet simply
        keeps readiness = null until a real save creates it. Fire-and-forget:
        a failed write logs and must never fail the caller's response. This is
        how stale pre-change verdicts self-heal on the first readiness check.

        Scoped by roster_index (migration 153), not machine_key: two locked
        roster entries can share a machine_key, and a machine_key-only WHERE
        would refresh BOTH rows with one machine's verdict."""
        import json
        if not isinstance(roster_index, int) or roster_index < 1:
            return
        try:
            await execute(
                """UPDATE machine_research_cards
                   SET validation = $4::jsonb, updated_at = now()
                   WHERE tenant_id = $1 AND video_id = $2 AND roster_index = $3""",
                self.tenant_id, video_id, roster_index, json.dumps(validation),
            )
        except Exception as exc:
            _logger.warning("[machine-research] readiness verdict refresh skipped: %s", str(exc)[:150])

    async def _checkpoint_machine_raw_source_package(
        self, video_id: str, machine_key: str, source_package: dict, locked_roster_snapshot: str
    ) -> Any:
        """Persist fetched exact excerpts before any LLM research-card work."""
        import json

        if not machine_key:
            raise ValueError("raw source package checkpoint requires a non-empty machine key")
        return await execute(
            """UPDATE videos SET research_payload = jsonb_set(
                   jsonb_set(
                     jsonb_set(
                       jsonb_set(
                         COALESCE(research_payload::jsonb, '{}'::jsonb),
                         '{machine_raw_source_packages}',
                         COALESCE(research_payload::jsonb->'machine_raw_source_packages', '{}'::jsonb)
                           || jsonb_build_object($1::text, $2::jsonb),
                         true
                       ),
                       '{machine_script_previews}',
                       COALESCE(research_payload::jsonb->'machine_script_previews', '{}'::jsonb) - $1::text,
                       true
                     ),
                     '{machine_script_briefs}',
                     COALESCE(research_payload::jsonb->'machine_script_briefs', '{}'::jsonb) - $1::text,
                     true
                   ),
                   '{machine_story_plans}',
                   COALESCE(research_payload::jsonb->'machine_story_plans', '{}'::jsonb) - $1::text,
                   true
               ), updated_at = now()
               WHERE id = $3 AND tenant_id = $4
                 AND (
                     research_payload->'unit_roster' IS NULL
                     OR research_payload->'unit_roster' = $5::jsonb
                 )""",
            machine_key, json.dumps(source_package), video_id, self.tenant_id, locked_roster_snapshot,
        )

    async def _checkpoint_one_machine_research_result(
        self,
        video_id: str,
        review_cards: list[Any],
        validation: dict,
        locked_roster_snapshot: str,
    ) -> Any:
        """Persist only the review card array and validation for one-machine research."""
        import json

        return await execute(
            """UPDATE videos SET research_payload = jsonb_set(
                   jsonb_set(
                     COALESCE(research_payload::jsonb, '{}'::jsonb),
                     '{unit_research_cards}',
                     $1::jsonb,
                     true
                   ),
                   '{unit_research_hold_validation}',
                   $2::jsonb,
                   true
               ), updated_at = now()
               WHERE id = $3 AND tenant_id = $4
                 AND (
                     research_payload->'unit_roster' IS NULL
                     OR research_payload->'unit_roster' = $5::jsonb
                 )""",
            json.dumps(review_cards), json.dumps(validation), video_id, self.tenant_id, locked_roster_snapshot,
        )

    async def _checkpoint_machine_script_preview(
        self, video_id: str, machine_key: str, preview: dict, locked_roster_snapshot: str
    ) -> Any:
        """Persist one isolated machine script preview without touching production script rows."""
        import json

        if not machine_key:
            raise ValueError("machine script preview checkpoint requires a non-empty machine key")
        return await execute(
            """UPDATE videos SET research_payload = jsonb_set(
                   COALESCE(research_payload::jsonb, '{}'::jsonb),
                   '{machine_script_previews}',
                   COALESCE(research_payload::jsonb->'machine_script_previews', '{}'::jsonb)
                     || jsonb_build_object($1::text, $2::jsonb),
                   true
               ), updated_at = now()
               WHERE id = $3 AND tenant_id = $4
                 AND (
                     research_payload->'unit_roster' IS NULL
                     OR research_payload->'unit_roster' = $5::jsonb
                 )""",
            machine_key, json.dumps(preview), video_id, self.tenant_id, locked_roster_snapshot,
        )

    @staticmethod
    def _enabled_stages(video: Optional[dict]) -> Optional[list]:
        """The video's EFFECTIVE stage plan (list of enabled stage keys), or
        None for 'run the full pipeline with no exclusions'.

        Two sources feed this, both additive (either can shrink the plan,
        never grow it back):

        1. The creator's pipeline_stages JSONB column — reads either a parsed
           list or a JSON string (asyncpg returns JSONB as a str unless a
           codec is set).
        2. status_map.render_path_plays_sfx(video) — a video whose render
           path can never mix in sound effects (Custom Film, static_docu,
           grok_native, character_dialogue — see the comment on run_render's
           dispatch block) has 'sound' force-excluded here even when the
           creator never touched the stage plan. Every status write inside
           this class (_update_video_status / _skip_disabled_next) reads this
           method, so it routes every transition it produces around the sound
           stage automatically, the same way a creator-disabled stage already
           gets skipped. The ONE write outside this class, routes/videos.py's
           `advance_video` (the human "Advance" button — a raw
           `UPDATE videos SET status`, not funneled through
           _update_video_status), calls this SAME static method directly and
           reroutes with status_map.resolve_planned_status itself — same
           source of truth, different call shape, not a parallel copy.
        """
        stages: Optional[list] = None
        if video:
            raw = video.get("pipeline_stages")
            if raw is not None:
                if isinstance(raw, str):
                    import json
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        raw = None
                if isinstance(raw, list) and raw:
                    stages = list(raw)

        return stages_excluding_blocked_sound(stages, video)

    @staticmethod
    def _skip_disabled_next(video: dict, natural_next: str) -> str:
        """Given a stage's natural next status, reroute it to honor this video's
        stage plan: skip stages the creator turned off, and return 'done' once
        the plan has no more enabled work.

        When the video has no explicit plan (pipeline_stages NULL) this falls
        back to the original skip_voice-only behavior, so existing videos are
        unaffected."""
        stages = PipelineExecutor._enabled_stages(video)
        if stages:
            return resolve_planned_status(natural_next, stages)
        if natural_next == "ready_for_voice" and video.get("skip_voice"):
            return "ready_for_image_prompts"
        return natural_next

    async def _skip_sound_stage(self, video_id: str, video: dict, current_status: str, natural_next: str) -> dict:
        """Advance a video past the sound stage without running it, because
        its render path will never play the result (status_map.
        render_path_plays_sfx — see the comment on run_render's dispatch
        block). `natural_next` is the status sound work would normally hand
        off to (run_sound_prompts always targets 'ready_for_sound_effects',
        run_sound_effects always targets 'ready_for_video_scripts' — the SAME
        hardcoded defaults those two methods already fall back to when their
        bot doesn't say otherwise, not a re-derivation of "next status after
        current_status", which would misbehave if this is ever reached from
        an unexpected current_status).

        Shared by three callers so the skip result is byte-identical no
        matter which one hits it:
          1. `_run_next_step_status_map`'s explicit guard — a video already
             PARKED at ready_for_sound_design/effects (written before this
             guard existed) gets a fast, specific skip instead of running the
             handler at all.
          2 & 3. `run_sound_prompts`/`run_sound_effects`'s own inner guard —
             the backstop EVERY caller (known or not: chat, MCP, the REST
             endpoints, ClaudeOrchestrator.execute, a future caller nobody's
             written yet) hits by construction, because this is the only
             place a paid Kie.ai sound generation can actually begin.
        """
        next_status = self._skip_disabled_next(video, natural_next) if natural_next else None
        reason = render_path_sfx_block_reason(video) or "this render path drops sound effects."
        if next_status and next_status != current_status:
            await self._update_video_status(video_id, next_status, video)
            await self._log_transition(
                video_id, current_status, next_status, triggered_by="sfx_guard_skip")
        return {
            "status": next_status or current_status or "idle",
            "video_id": video_id,
            "skipped_stage": "sound",
            "message": f"Sound stage skipped — {reason}",
        }

    def _load_idea_from_video(self, video_id: str):
        """Load idea into pipeline state from Supabase video UUID.

        Uses the SupabaseAdapter which returns Airtable-shaped dicts.
        """
        idea = self._pipeline.airtable.get_idea(video_id)
        if idea:
            self._pipeline._load_idea(idea)
        else:
            print(f"[WARN] Could not load idea for video_id={video_id}", flush=True)

    async def _export_visual_style(self, video: dict) -> None:
        """Export the channel LOOK to the skill image pipeline.

        The neutral default visual profile declares no medium of its own;
        image_prompts/prompt_builder.py reads ``VISUAL_STYLE_DESCRIPTION`` and
        front-loads it into every image prompt (a per-video image_style_override
        still wins). Skills can't import the backend, so this env var is the
        seam — mirroring ``VISUAL_PROFILE``.

        The image stages (run_prompts / run_images / storyboard) do NOT go
        through ``_load_prompt_overrides`` (which is where text stages set this),
        so they call this directly. Set unconditionally so a previous tenant's
        value can never leak into this run.
        """
        try:
            identity = await build_identity_context(self.tenant_id, video)
            os.environ["VISUAL_STYLE_DESCRIPTION"] = identity.visual_style or ""
        except Exception as e:  # never let look resolution break a run
            _logger.warning("export visual style failed; using per-video override: %s", e)
            os.environ["VISUAL_STYLE_DESCRIPTION"] = (
                (video or {}).get("image_style_override") or ""
            ).strip()

    async def _check_voice_exists(self, video_id: str, scene: int = None) -> tuple[bool, int, int]:
        """Check if voice has been generated for all scenes (or just one).

        A scene is voiced when its narrator track exists (scripts.voice_over_url)
        OR when dialogue-voice finished every spoken line (each dialogue_segments
        entry with text carries its own audio_url). All-dialogue scenes never get
        a narrator track, so voice_over_url alone would reject them forever.

        Pass `scene` to scope the check to a single scene (used by the coverage
        image-generation gate below for a targeted single-scene redraw).

        Returns (all_have_voice, total_scenes, scenes_with_voice).
        """
        from dialogue_voice import _as_segments

        query = "SELECT voice_over_url, dialogue_segments FROM scripts WHERE video_id = $1"
        params: list = [video_id]
        if scene is not None:
            query += " AND scene = $2"
            params.append(scene)
        rows = await fetch_all(query, *params)
        total = len(rows)
        with_voice = 0
        for r in rows:
            if r.get("voice_over_url"):
                with_voice += 1
                continue
            segments = _as_segments(r.get("dialogue_segments"))
            if segments and all(
                seg.get("audio_url")
                for seg in segments
                if (seg.get("text") or "").strip()
            ):
                with_voice += 1
        return (total > 0 and with_voice == total), total, with_voice

    async def _update_video_status(self, video_id: str, new_status: str, video: Optional[dict] = None):
        """Update video status in Supabase, honoring the video's stage plan.

        If the creator restricted this video to a subset of stages, a forward
        advance is rerouted to the next enabled stage — or to 'done' when the
        plan has no more enabled work. Videos with no plan (pipeline_stages NULL,
        i.e. every existing video and every full run) are unaffected: the status
        is written exactly as given. This is the single chokepoint every stage
        uses to advance, so the creator's on/off switches are honored everywhere.

        Args:
            video_id: Supabase video UUID
            new_status: New status in Supabase format
            video: Optional already-loaded video row (avoids a re-fetch)
        """
        if new_status != "done":
            v = video if video is not None else await self._get_video(video_id)
            stages = self._enabled_stages(v)
            if stages:
                new_status = resolve_planned_status(new_status, stages)
        await execute(
            "UPDATE videos SET status = $1, updated_at = now() WHERE id = $2",
            new_status, video_id,
        )

    async def _log_transition(
        self,
        video_id: str,
        from_status: str,
        to_status: str,
        triggered_by: str = "api",
        cost: float = 0,
        error_message: Optional[str] = None,
    ):
        """Log status transition."""
        await execute(
            """INSERT INTO stage_transitions
               (video_id, tenant_id, from_status, to_status, triggered_by, cost, error_message)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            video_id, self.tenant_id, from_status, to_status, triggered_by, cost, error_message,
        )

    async def _load_prompt_overrides(self, video: dict):
        """Load system prompt overrides onto the pipeline object.

        Priority: per-video override > tenant override > neutral engine template
        (filled with the channel's IdentityContext). Keys without an engine
        template (sound_curation / sound_generation) fall through to None so the
        bot uses its own built-in default.

        Phase 1 invariant: a tenant that already has a custom override still gets
        that override — we only inject identity placeholders into it; we never
        replace it with the neutral template. Behavior only changes where there
        was NO override before (previously None, now a neutral identity-filled
        prompt).

        Sets pipeline attributes like `script_system_prompt`, `thumbnail_system_prompt`,
        etc. that bots read via `getattr(pipeline, '<key>_system_prompt', None)`.

        Args:
            video: Video row dict from Supabase (contains per-video override columns).
        """
        # Mapping: tenant prompt_key -> (video column, pipeline attribute)
        # `title` has no per-video override column (like `research`) — it
        # resolves per-video None > tenant override > the neutral `title`
        # engine template (checklist C34d — closes the "Phase 3 wires it"
        # gap: title generation used to borrow the `thumbnail` override
        # wholesale via thumbnail/run.py's ThumbnailTitleEngine construction;
        # it now gets its own `title_system_prompt` seam, read by
        # thumbnail/run.py separately from thumbnail_system_prompt).
        PROMPT_MAP = {
            "script":           ("script_system_prompt",       "script_system_prompt"),
            "thumbnail":        ("thumbnail_system_prompt",    "thumbnail_system_prompt"),
            "title":            (None,                         "title_system_prompt"),
            "video_motion":     ("video_motion_system_prompt", "video_motion_system_prompt"),
            "sound_curation":   ("sound_system_prompt",        "sound_curation_system_prompt"),
            "sound_generation": ("sound_system_prompt",        "sound_generation_system_prompt"),
            "research":         (None,                         "research_system_prompt"),
        }

        # Build the channel identity once for this run (defensive — never raises).
        self._identity = await build_identity_context(self.tenant_id, video)

        # Export the channel's LOOK to the skill pipeline. The neutral visual
        # profile declares no medium of its own; image_prompts/prompt_builder.py
        # reads VISUAL_STYLE_DESCRIPTION and front-loads it into every image
        # prompt (per-video image_style_override still wins). Skills can't import
        # the backend, so this env var is the seam (mirrors VISUAL_PROFILE).
        os.environ["VISUAL_STYLE_DESCRIPTION"] = self._identity.visual_style or ""

        # Export the channel's NICHE the same way (checklist C34c, S10-4):
        # thumbnail/selector.py reads CHANNEL_NICHE as the fallback signal for
        # whether an unmatched video still belongs on Template A (Map +
        # Barrier — a finance/geopolitics channel's home turf) or the
        # niche-neutral Template E. Same seam pattern as VISUAL_STYLE_DESCRIPTION
        # above; skills can't import the backend's IdentityContext directly.
        os.environ["CHANNEL_NICHE"] = self._identity.niche or ""

        # Fetch tenant-level defaults
        tenant_overrides = {}
        try:
            rows = await fetch_all(
                "SELECT prompt_key, prompt_text FROM tenant_prompt_defaults WHERE tenant_id = $1",
                self.tenant_id,
            )
            tenant_overrides = {r["prompt_key"]: r["prompt_text"] for r in rows}
        except Exception as e:
            _logger.warning("Failed to load tenant prompt overrides: %s", e)

        # Resolve each prompt: per-video > tenant > neutral identity template.
        for prompt_key, (video_col, pipeline_attr) in PROMPT_MAP.items():
            # Per-video override (if column exists on the videos table)
            per_video = video.get(video_col) if video_col else None
            # Tenant override
            tenant = tenant_overrides.get(prompt_key)
            resolved = resolve_prompt(per_video, tenant, prompt_key, self._identity)
            setattr(self._pipeline, pipeline_attr, resolved)

        # Channel thumbnail formula: when the identity builder extracted a
        # repeatable thumbnail_style from the channel's own top videos (vision
        # pass, channel_profiles.channel_identity), every generated thumbnail
        # must match that formula — it's the channel's visual brand. Appended
        # (never replacing) so custom overrides keep working.
        try:
            row = await fetch_one(
                "SELECT channel_identity->'thumbnail_style' AS ts "
                "FROM channel_profiles WHERE tenant_id = $1", self.tenant_id)
            ts = (row or {}).get("ts")
            if isinstance(ts, str):
                import json as _json_ts
                ts = _json_ts.loads(ts)
            if isinstance(ts, dict) and ts:
                base = getattr(self._pipeline, "thumbnail_system_prompt", None) or ""
                import json as _json_ts
                formula = _json_ts.dumps(ts, indent=2)
                setattr(
                    self._pipeline, "thumbnail_system_prompt",
                    base + "\n\nCHANNEL THUMBNAIL FORMULA (extracted from this "
                    "channel's own top-performing thumbnails — match its style, "
                    "text treatment, composition and mood; the composition itself "
                    "must still be fresh for this video):\n" + formula,
                )
        except Exception as e:
            _logger.warning("thumbnail formula injection skipped: %s", e)

        # Slop-proofing (anti-demonetization), baked into the prompts:
        #   - SCRIPT: Wall 1 (a real point of view) + Wall 2 (a genuinely NEW
        #     PLOT vs this channel's recent videos), so every video tells a
        #     different story by construction.
        #   - THUMBNAIL: keep the channel's STYLE consistent (that is brand), but
        #     never reuse a TEMPLATE — force a new composition vs recent thumbs.
        # The look/format/title style may repeat; the plot and the thumbnail
        # composition may not. History-aware, invisible to the creator, never a
        # gate. Applies on top of whatever was resolved above (custom override OR
        # neutral template). Fully defensive: any failure leaves prompts as-is,
        # and the always-on mandates (point of view, anti-template) still land
        # even if the history read fails. See backend/originality.py.
        try:
            import originality
            try:
                recent_fps = await originality.load_recent_fingerprints(
                    self.tenant_id,
                    exclude_video_id=str(video["id"]) if video.get("id") else None,
                )
            except Exception as e:
                _logger.warning("recent fingerprints unavailable: %s", e)
                recent_fps = []
            # Hand the recent PLOTS to the skill side (Phase 2 silent re-roll in
            # script/brief_translator) over the same env-var seam used for
            # VISUAL_STYLE_DESCRIPTION. Always set (even "[]") so a previous
            # video's plots never leak into this run.
            try:
                import json as _json
                _slim = [
                    {"title": f.get("title", ""),
                     "plot": f.get("script_excerpt") or f.get("hook") or ""}
                    for f in recent_fps
                ]
                os.environ["RECENT_PLOTS_JSON"] = _json.dumps(_slim)
            except Exception:
                os.environ["RECENT_PLOTS_JSON"] = "[]"
            for kind, attr in (
                ("script", "script_system_prompt"),
                ("thumbnail", "thumbnail_system_prompt"),
            ):
                base = getattr(self._pipeline, attr, None)
                if not base:
                    continue
                extra = originality.build_generation_guardrails(kind, recent_fps)
                if extra:
                    setattr(self._pipeline, attr, base + "\n\n" + extra)
        except Exception as e:
            _logger.warning("originality guardrails skipped: %s", e)

    async def _install_cancel_support(self, video_id: str):
        """Arm cooperative cancellation for a paid generation run.

        Clears any stale cancel request first (a Stop from a previous run must
        never kill the resume), then exposes pipeline.should_cancel — an async
        callable the generation loops poll between paid items. Works across
        processes (arq worker) via the background_tasks 'cancelled' marker row.
        """
        # NOTE: stale-cancel cleanup happens at run start in _set_task_status
        # (routes/pipeline.py) — resetting here raced with real Stop requests
        # arriving while the executor was still initializing.
        from cancel_registry import is_cancel_requested
        tenant_id = self.tenant_id

        async def _should_cancel() -> bool:
            try:
                return await is_cancel_requested(tenant_id, video_id)
            except Exception:
                return False

        self._pipeline.should_cancel = _should_cancel

    async def _load_character_refs(self, video_id: str, video: dict):
        """Load the approved cast onto the pipeline for reference-locked
        generation. Returns an error string when characters exist but the cast
        isn't approved yet (the character-design gate); None otherwise.
        Videos with no designed characters skip the step entirely."""
        try:
            rows = await fetch_all(
                "SELECT reference_url FROM video_characters "
                "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
                "ORDER BY sort, created_at",
                video_id, self.tenant_id,
            )
        except Exception:
            rows = []
        if not rows:
            self._pipeline.character_reference_urls = None
            return None
        if not video.get("characters_approved_at"):
            self._pipeline.character_reference_urls = None
            return user_facing("Your cast is designed but not approved yet — open the Characters tab, "
                               "review the portraits, and hit Approve before generating visuals.")
        # ONE labeled cast sheet conditions far better than N competing
        # portraits (live finding: 6 refs at once = inconsistent characters).
        # approve_cast stores the sheet on character_reference_url.
        sheet = video.get("character_reference_url")
        if sheet:
            self._pipeline.character_reference_urls = [sheet]
        else:
            self._pipeline.character_reference_urls = [r["reference_url"] for r in rows][:6]
        return None

    async def _load_environment_refs(self, video_id: str, video: dict):
        """Load approved location references onto the pipeline as a
        {location_id: reference_url} map. Mirrors the character gate: returns an
        error string when environments exist but aren't approved; None otherwise.
        Videos that never designed environments skip it entirely (opt-in)."""
        try:
            rows = await fetch_all(
                "SELECT name, reference_url FROM video_environments "
                "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
                "ORDER BY sort, created_at",
                video_id, self.tenant_id,
            )
        except Exception:
            rows = []
        if not rows:
            self._pipeline.environment_reference_urls = None
            return None
        if not video.get("environments_approved_at"):
            self._pipeline.environment_reference_urls = None
            return user_facing("Your environments are designed but not approved yet — open the "
                               "Environments tab, review them, and hit Approve before generating grids.")
        self._pipeline.environment_reference_urls = {
            r["name"]: r["reference_url"] for r in rows if r.get("name") and r.get("reference_url")
        }
        return None

    async def _environments_ready_gate(self, video_id: str, video: dict) -> Optional[str]:
        """Storyboards require the environments step to be DONE — either
        approved (locations locked) or explicitly skipped ("No locations" stamps
        environments_approved_at with no rows). Returns an error string to block,
        or None to allow. Applies to bulk AND per-scene generation, so the
        creator can't sail past environment design unintentionally."""
        if video.get("environments_approved_at"):
            return None
        try:
            row = await fetch_one(
                "SELECT count(*) AS n FROM video_environments WHERE video_id = $1 AND tenant_id = $2",
                video_id, self.tenant_id,
            )
            n = (row or {}).get("n") or 0
        except Exception:
            n = 0
        if n > 0:
            return user_facing(
                "Approve your environments first — open the Environments tab, review the "
                "locations, and hit Approve before generating storyboards."
            )
        return user_facing(
            "Design your environments first — open the Environments tab and design the "
            "locations (or hit “No locations — skip” if this video has none) before "
            "generating storyboards."
        )

    async def _persist_url(self, source_url: str, storage_path: str) -> str:
        """Re-upload a temporary URL to Google Drive for permanent access.

        Returns the permanent URL, or the original URL if upload fails or URL is already permanent.
        """
        if not source_url:
            return source_url
        if "drive.google.com" in source_url or "supabase.co/storage" in source_url:
            return source_url
        try:
            return await upload_from_url(source_url, storage_path, tenant_id=self.tenant_id)
        except Exception as e:
            _logger.warning("Failed to persist %s: %s", storage_path, e)
            return source_url

    async def _persist_asset_urls(self, video_id: str) -> int:
        """Re-upload all temp asset image_urls for a video to Google Drive.

        Returns the number of URLs persisted.
        """
        assets = await fetch_all(
            """SELECT id, scene, image_index, image_url FROM assets
               WHERE video_id = $1 AND tenant_id = $2 AND image_url IS NOT NULL
               AND image_url NOT LIKE '%drive.google.com%'
               AND image_url NOT LIKE '%supabase.co/storage%'""",
            video_id, self.tenant_id,
        )
        count = 0
        for a in assets:
            path = f"{video_id}/images/S{a['scene']}-{a['image_index']}.png"
            new_url = await self._persist_url(a["image_url"], path)
            if new_url != a["image_url"]:
                await execute(
                    "UPDATE assets SET image_url = $1, updated_at = now() WHERE id = $2",
                    new_url, a["id"],
                )
                count += 1
        return count

    async def _persist_storyboard_urls(self, video_id: str) -> int:
        """Re-upload all temp storyboard grid URLs to Google Drive.

        Returns the number of URLs persisted.
        """
        scenes = await fetch_all(
            """SELECT id, scene, storyboard_1_url, storyboard_2_url,
                      storyboard_3_url, storyboard_4_url, storyboard_5_url
               FROM scripts WHERE video_id = $1 AND tenant_id = $2
               ORDER BY scene""",
            video_id, self.tenant_id,
        )
        count = 0
        for sc in scenes:
            updates = []
            params = []
            idx = 1
            for beat in range(1, 6):
                col = f"storyboard_{beat}_url"
                url = sc.get(col)
                if url and "drive.google.com" not in url and "supabase.co/storage" not in url:
                    path = f"{video_id}/storyboard/S{sc['scene']}-B{beat}.png"
                    new_url = await self._persist_url(url, path)
                    if new_url != url:
                        updates.append(f"{col} = ${idx}")
                        params.append(new_url)
                        idx += 1
                        count += 1
            if updates:
                params.append(sc["id"])
                sql = f"UPDATE scripts SET {', '.join(updates)}, updated_at = now() WHERE id = ${idx}"
                await execute(sql, *params)
        return count

    async def create_idea(
        self,
        topic: str,
        source: str = "storyengine",
    ) -> dict:
        """Create a new video idea.

        Creates a video record in Supabase with status 'idea_logged'.
        Research and scripting are triggered separately from the video detail page.

        Args:
            topic: Topic or headline for the video
            source: Source identifier

        Returns:
            Dict with video_id and status
        """
        # No pipeline initialization needed — just a DB insert
        bot_name = "Idea Bot"
        video_id = None

        try:
            await self._log_activity(bot_name, None, "started", f"Creating idea: {topic}")

            # Resolve project for tenant
            from routes.projects import _get_or_create_project
            project = await _get_or_create_project(self.tenant_id)
            project_id = str(project["id"])

            # Create video record in Supabase
            result = await fetch_one(
                """INSERT INTO videos (tenant_id, project_id, video_title, status, headline, source, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, now())
                   RETURNING id""",
                self.tenant_id, project_id, topic, "idea_logged", topic, source,
            )
            video_id = str(result["id"])

            await self._log_activity(bot_name, video_id, "completed", "Idea created")

            return {
                "video_id": video_id,
                "status": "idea_logged",
                "message": "Idea created successfully",
            }

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {
                "video_id": video_id,
                "status": "failed",
                "error": error_msg,
            }

    async def run_research(self, video_id: str) -> dict:
        """Run research agent on a video idea.

        Args:
            video_id: Supabase video UUID

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()
        bot_name = "Research Agent"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            topic = video.get("video_title") or video.get("headline")

            if not topic:
                return {"status": "failed", "error": "No topic found for video"}

            await self._log_activity(bot_name, video_id, "started", f"Researching: {topic}")

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            # Import research agent
            from research.agent import run_research

            # Feed the channel's OWN research approach (extracted from its top
            # videos by the identity builder) into the research context, so the
            # agent looks for what this channel's format actually needs (e.g.
            # DVU: program designations, unit costs, cancellation dates).
            research_context = None
            try:
                row = await fetch_one(
                    "SELECT channel_identity->'research_approach' AS ra "
                    "FROM channel_profiles WHERE tenant_id = $1", self.tenant_id)
                ra = (row or {}).get("ra")
                if isinstance(ra, str) and ra.strip().startswith(("{", "[", '"')):
                    import json as _json_ra
                    try:
                        ra = _json_ra.loads(ra)
                    except ValueError:
                        pass
                if ra:
                    research_context = (
                        "THIS CHANNEL'S RESEARCH APPROACH (match it — these are "
                        "the facts its videos are built from):\n"
                        + (ra if isinstance(ra, str) else str(ra))
                    )
            except Exception:  # noqa: BLE001 — context is a bonus, never a blocker
                pass

            pacing_targets = _roster_pacing_targets(video.get("video_length_minutes"))
            if pacing_targets and _title_is_broad_machine_roster(topic):
                pacing_context = (
                    "VIDEO LENGTH / ROSTER PACING PRESSURE:\n"
                    f"Target length: {pacing_targets['video_length_minutes']:g} minutes. "
                    "For Anton/DVsU machine-roster videos, calibrate to ~60 seconds "
                    "of final screen time per audience-facing machine section, with "
                    f"{_ANTON_PARAGRAPH_WORD_RANGE} script words per machine. "
                    f"Expected final roster: around {pacing_targets['expected_final_roster']} machines. "
                    f"Minimum acceptable final roster before proving a small closed category: {pacing_targets['minimum_final_roster']}. "
                    f"Research reserve before final filtering: about {pacing_targets['candidate_universe_target']} total candidates "
                    f"({pacing_targets['extra_good_measure']} extra for exclusions/swaps). "
                    "Lock the strongest runtime-fit roster; do not optimize for an endless universe or pad weak fits."
                )
                research_context = (research_context + "\n\n" if research_context else "") + pacing_context

            # Run research. record_id MUST be this video — without it the
            # adapter creates a brand-new idea row (a stray duplicate video
            # appeared in the workspace, seen live on DVU 2026-07-02).
            payload = await run_research(
                anthropic_client=self._pipeline.anthropic,
                topic=topic,
                context=research_context,
                airtable_client=self._pipeline.airtable,
                record_id=video_id,
                system_prompt_override=getattr(self._pipeline, "research_system_prompt", None),
            )

            if not payload:
                raise Exception("Research returned no results")

            roster_check = _roster_validation(topic, payload, video_length_minutes=video.get("video_length_minutes"))
            if roster_check.get("complete_title") and not roster_check.get("passed"):
                pacing = roster_check.get("roster_pacing_targets") or {}
                pacing_repair_note = ""
                if pacing:
                    pacing_repair_note = (
                        "\nAnton/DVsU pacing gate to satisfy unless sources prove a small closed category:\n"
                        f"- Expected final roster: around {pacing.get('expected_final_roster')} audience-facing machines.\n"
                        f"- Minimum failure floor: {pacing.get('minimum_final_roster')} machines. Do not treat this as the target.\n"
                        f"- Research reserve before filtering: about {pacing.get('candidate_universe_target')} total candidates for exclusions/swaps, not an endless universe.\n"
                        "If your final roster is below the expected target by more than one slot while you found a large reserve, that is not runtime-fit; promote the strongest source-backed edge candidates until the roster fits, or prove a genuinely small closed category.\n"
                    )
                repair_context = (
                    (research_context or "")
                    + "\n\nAUTONOMOUS ROSTER REPAIR PASS:\n"
                    + "The first roster-discovery draft failed the production gate. "
                    + "Do not ask the operator for help. Re-run the discovery as a corrective pass, "
                    + "apply defensible default boundary decisions, and return a script-ready roster if possible.\n"
                    + pacing_repair_note
                    + "Validator warnings to fix:\n- "
                    + "\n- ".join(str(w) for w in roster_check.get("warnings", []))
                    + "\nLikely gaps/designations named by validation:\n- "
                    + "\n- ".join(str(g) for g in roster_check.get("gaps", []))
                    + "\nRequired fixes: include a non-empty gap_hunt_matrix and edge_case_matrix, at least 6 search_queries_used, "
                    + "at least 3 source_families_crosschecked, a recommended_final_roster, and a final "
                    + "roster_contract of CONFIRMED unless the roster is genuinely impossible to bound. "
                    + "Every disputed candidate must land in unit_roster, a discovery bucket with an "
                    + "applied decision, or excluded_candidates with a source-backed reason."
                )
                await self._log_activity(
                    bot_name, video_id, "running",
                    "Roster gate failed first pass; running autonomous repair pass before scripting.",
                )
                repair_payload = await run_research(
                    anthropic_client=self._pipeline.anthropic,
                    topic=topic,
                    context=repair_context,
                    airtable_client=self._pipeline.airtable,
                    record_id=video_id,
                    system_prompt_override=getattr(self._pipeline, "research_system_prompt", None),
                )
                if repair_payload:
                    repair_check = _roster_validation(topic, repair_payload, video_length_minutes=video.get("video_length_minutes"))
                    payload = repair_payload
                    roster_check = repair_check
            payload["unit_roster_validation"] = roster_check
            if not roster_check.get("passed"):
                await self._log_activity(
                    bot_name, video_id, "running",
                    "Roster contract needs review: " + "; ".join(roster_check.get("warnings", []))[:800],
                )
            elif roster_check.get("needs_review"):
                # C4: a soft-only roster (pacing/count nitpicks etc, no hard
                # failures) still ADVANCES — but log it visibly so a human
                # can see it flagged, instead of the old behavior where a
                # single soft warning silently dead-ended the whole video.
                await self._log_activity(
                    bot_name, video_id, "running",
                    "Roster passed with soft warnings, needs review: "
                    + "; ".join(roster_check.get("soft_warnings", []))[:800],
                )

            # Update Supabase with research payload. Never advance a complete-roster
            # title to scripting when the production roster gate still failed after
            # repair; that is exactly how a bad paid pass leaks downstream.
            import json
            passed_roster_gate = bool(roster_check.get("passed"))
            passed_unit_research_hold = True
            hold_video = dict(video)
            hold_video["research_payload"] = payload
            roster_names = _machine_documentary_hold_roster(hold_video)
            if passed_roster_gate and roster_names:
                payload = await self._run_unit_research_hold(video_id, topic, payload, roster_names)
                hold_validation = payload.get("unit_research_hold_validation") if isinstance(payload, dict) else None
                passed_unit_research_hold = bool(
                    isinstance(hold_validation, dict) and hold_validation.get("passed")
                )
            next_status = "ready_for_scripting" if (passed_roster_gate and passed_unit_research_hold) else (current_status or "idea_logged")
            save_result = await execute(
                """UPDATE videos SET
                   research_payload = $1,
                   thesis = $2,
                   executive_hook = $3,
                   status = $4,
                   research_skipped = FALSE,
                   updated_at = now()
                   WHERE id = $5 AND tenant_id = $6""",
                json.dumps(payload),
                payload.get("thesis", ""),
                payload.get("executive_hook", ""),
                next_status,
                video_id,
                self.tenant_id,
            )
            if self._db_write_missed(save_result):
                warning = "Research save refused because the video is no longer available for this tenant"
                await self._log_activity(bot_name, video_id, "failed", warning)
                return {"status": "failed", "video_id": video_id, "error": warning}
            from drive_workspace import sync_video_workspace_fail_soft
            await sync_video_workspace_fail_soft(video_id, self.tenant_id)

            # C3 fix (2026-07-29): the roster is ALREADY PERSISTED above
            # (research_payload = $1, just written) the instant it exists,
            # independent of whether the roster/unit-research gate below
            # passes. Dispatching here (before the gate check, not after it)
            # means a roster that fails the gate on a soft warning (e.g. "23
            # items vs target ~20") still gets its reference photos fetched
            # instead of sitting with zero photos until a human intervenes —
            # exactly what happened live to video
            # d2e37cd6-521a-43aa-a14d-ce096a783c1e for two days. `video`
            # (the ORIGINAL pre-payload-update dict, not `hold_video`) is
            # passed deliberately: dispatch_roster_prefetch only reads
            # render_mode off it to decide whether to schedule anything at
            # all, and render_mode never changes over a research run, so the
            # original dict is exactly as valid a source for it as any later
            # copy would be.
            from static_docu import dispatch_roster_prefetch
            dispatch_roster_prefetch(video, video_id, self.tenant_id)

            if not (passed_roster_gate and passed_unit_research_hold):
                gate_error = "Roster validation failed" if not passed_roster_gate else "Unit research-hold failed"
                await self._log_transition(video_id, current_status or "unknown", next_status, "api", error_message=gate_error)
                await self._log_activity(bot_name, video_id, "failed", f"Research gate failed; not advancing to scripting: {gate_error}")
                return {
                    "status": "failed",
                    "video_id": video_id,
                    "error": f"Research gate failed; not advancing to scripting: {gate_error}",
                    "headline": payload.get("headline"),
                }

            await self._log_transition(video_id, current_status, "ready_for_scripting", "api")
            await self._log_activity(bot_name, video_id, "completed", "Research complete")

            return {
                "status": "ready_for_scripting",
                "video_id": video_id,
                "headline": payload.get("headline"),
            }

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_one_machine_research(self, video_id: str, machine: str) -> dict:
        """Refresh one locked machine card without paying for or replacing the rest of the roster."""
        await self._ensure_initialized()
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}
        payload = video.get("research_payload") or {}
        if isinstance(payload, str):
            import json as _json_one
            payload = _json_one.loads(payload)
        if not isinstance(payload, dict):
            return {"status": "failed", "error": "Research payload is missing or invalid"}
        roster = _machine_documentary_hold_roster(video)
        matched = _locked_roster_item_for_machine(roster, machine)
        if not matched:
            return {"status": "failed", "error": f"Machine is not in the locked roster: {machine}"}
        import json as _json_one
        locked_roster_snapshot = _json_one.dumps(payload.get("unit_roster"), sort_keys=True, ensure_ascii=False)
        title = video.get("video_title") or video.get("headline") or "Untitled documentary"
        original_status = video.get("status") or "idea_logged"
        payload = await self._run_unit_research_hold(
            video_id, title, payload, roster, target_machine=matched
        )
        validation = payload.get("unit_research_hold_validation") or {}
        if not validation.get("target_machine_passed"):
            units = validation.get("units") or []
            warnings = units[-1].get("warnings", []) if units else validation.get("warnings", [])
            summary = (
                "One-machine research saved raw source evidence, but "
                f"{matched} still needs review before script preview."
            )
            return {
                "status": "needs_review",
                "video_id": video_id,
                "machine": matched,
                "summary": summary,
                "error": "; ".join(str(item) for item in warnings),
                "warnings": warnings,
                "next_action": "review_research_warnings_before_script_preview",
                "research_payload": await enrich_research_payload_readiness(self.tenant_id, video_id, payload),
            }
        final_save_result = await execute(
            """UPDATE videos
               SET status = $1, updated_at = now()
               WHERE id = $2 AND tenant_id = $3
                 AND (
                     research_payload->'unit_roster' IS NULL
                     OR research_payload->'unit_roster' = $4::jsonb
                 )""",
            original_status, video_id, self.tenant_id, locked_roster_snapshot,
        )
        if self._db_write_missed(final_save_result):
            return {
                "status": "failed",
                "video_id": video_id,
                "error": "persisted unit_roster changed concurrently; final one-machine research save refused",
            }
        card = _research_card_for_machine(payload, matched)
        return {
            "status": "completed",
            "video_id": video_id,
            "machine": matched,
            "research_card": card,
            "next_action": "run_machine_script_preview",
            "research_payload": await enrich_research_payload_readiness(self.tenant_id, video_id, payload),
        }

    # ------------------------------------------------------------------
    # Roster orchestrator - surgical repair verbs (2026-07-16).
    # ------------------------------------------------------------------

    async def _load_machine_repair_context(self, video_id: str, machine: str) -> dict:
        """Everything one repair verb needs: payload, locked roster, card copy, package."""
        import copy as _copy
        import json as _json_ctx

        video = await self._get_video(video_id)
        if not video:
            return {"error": "Video not found"}
        payload = video.get("research_payload") or {}
        if isinstance(payload, str):
            try:
                payload = _json_ctx.loads(payload)
            except (ValueError, TypeError):
                payload = None
        if not isinstance(payload, dict):
            return {"error": "Research payload is missing or invalid"}
        roster = _machine_documentary_hold_roster(video)
        if not roster:
            return {"error": "No locked machine roster found"}
        matched = _locked_roster_item_for_machine(roster, machine)
        if not matched:
            return {"error": f"Machine is not in the locked roster: {machine}"}
        payload = await self._load_machine_research_cards(video_id, payload, roster, target_machine=matched)
        snapshot = _json_ctx.dumps(payload.get("unit_roster"), sort_keys=True, ensure_ascii=False)
        package = _verified_source_package_for_machine(payload, matched)
        if package is not None:
            package = _verified_machine_source_package_with_anton_metadata(package, matched)
        card = _research_card_for_machine(payload, matched)
        return {
            "video": video,
            "payload": payload,
            "roster": roster,
            "machine": matched,
            "code": _normalized_unit_code(matched),
            "snapshot": snapshot,
            "package": package,
            "card": _copy.deepcopy(card) if isinstance(card, dict) else None,
            "roster_index": roster.index(matched) + 1,
        }

    async def _persist_repaired_card(
        self, video_id: str, ctx: dict, card: dict, warnings: list[str], verb: str
    ) -> str:
        """Save one surgically repaired card. Returns an error string or ''."""
        payload = ctx["payload"]
        machine = ctx["machine"]
        payload["unit_research_cards"] = _merge_card_into_review_cards(
            payload.get("unit_research_cards") if isinstance(payload.get("unit_research_cards"), list) else [],
            card,
            machine,
        )
        payload["unit_research_hold_validation"] = _hold_validation_with_unit_verdict(payload, machine, warnings)
        _clear_machine_preview_artifacts(payload, ctx["code"])
        result = await self._checkpoint_one_machine_research_result(
            video_id,
            payload["unit_research_cards"],
            payload["unit_research_hold_validation"],
            ctx["snapshot"],
        )
        if self._db_write_missed(result):
            return "persisted unit_roster changed concurrently; repair save refused"
        # The checkpoint writes only cards + validation; stale previews for this
        # machine must also leave the stored payload (same rule as research).
        await execute(
            """UPDATE videos SET research_payload = jsonb_set(
                   jsonb_set(
                     jsonb_set(
                       COALESCE(research_payload::jsonb, '{}'::jsonb),
                       '{machine_script_previews}',
                       COALESCE(research_payload::jsonb->'machine_script_previews', '{}'::jsonb) - $1::text,
                       true
                     ),
                     '{machine_script_briefs}',
                     COALESCE(research_payload::jsonb->'machine_script_briefs', '{}'::jsonb) - $1::text,
                     true
                   ),
                   '{machine_story_plans}',
                   COALESCE(research_payload::jsonb->'machine_story_plans', '{}'::jsonb) - $1::text,
                   true
               ), updated_at = now()
               WHERE id = $2 AND tenant_id = $3
                 AND (
                     research_payload->'unit_roster' IS NULL
                     OR research_payload->'unit_roster' = $4::jsonb
                 )""",
            ctx["code"], video_id, self.tenant_id, ctx["snapshot"],
        )
        # G14, 2026-07-31: passed reflects BLOCKING warnings only; the stored
        # warnings list keeps advisory notes (e.g. tier_floor_advisory) visible.
        await self._upsert_machine_research_card(
            video_id, machine, ctx["roster_index"], card,
            {"machine": machine, "passed": not _blocking_warnings(warnings), "warnings": list(warnings), "repair_verb": verb},
        )
        return ""

    def _repair_response(self, ctx: dict, verb: str, warnings: list[str], extra: Optional[dict] = None) -> dict:
        # G14, 2026-07-31: same blocking-only passed rule as everywhere else.
        blocking = _blocking_warnings(warnings)
        response = {
            "status": "completed" if not blocking else "needs_review",
            "machine": ctx["machine"],
            "verb": verb,
            "passed": not blocking,
            "warnings": list(warnings),
        }
        if extra:
            response.update(extra)
        return response

    async def repair_promote_excerpt(
        self, video_id: str, machine: str, excerpt_id: str, kind: str = "reality"
    ) -> dict:
        """Deterministically lift a verified package excerpt into card evidence.

        Free (no LLM). Fixes the select-miss class: the story is already in the
        package, the card just never cited it (XB-15's transport story)."""
        await self._ensure_initialized()
        ctx = await self._load_machine_repair_context(video_id, machine)
        if ctx.get("error"):
            return {"status": "failed", "error": ctx["error"]}
        card, package = ctx["card"], ctx["package"]
        if card is None:
            return {"status": "failed", "error": "No saved research card to repair; run one-machine research first"}
        if package is None:
            return {"status": "failed", "error": "No verified source package for this machine; run one-machine research first"}
        kind = str(kind or "reality").strip().lower()
        candidate = _find_candidate_excerpt(package, excerpt_id)
        precheck = _promote_excerpt_precheck_error(candidate, kind, ctx["machine"])
        if precheck:
            return {"status": "failed", "error": precheck}
        segments = card.get("evidence_segments") if isinstance(card.get("evidence_segments"), list) else []
        existing_ids = {
            str(segment.get("evidence_id") or "").strip()
            for segment in segments if isinstance(segment, dict)
        }
        segment = _promoted_evidence_segment(candidate, kind, ctx["machine"], existing_ids)
        segments.append(segment)
        card["evidence_segments"] = segments
        slot_role = _anton_slot_role_for_kind(segment["kind"])
        if slot_role == "reality":
            # The promoted excerpt IS the actual-use story; a stale refusal or
            # phantom bare tag must not survive it.
            card["actual_outcome"] = segment["claim"]
            card.pop("deliberately_bare", None)
            card.pop("gap_hunt_summary", None)
        if slot_role == "memorable_fact":
            card["surprising_fact"] = segment["claim"]
        for field_kind, field_name in (("timeframe", "timeframe_evidence_ids"), ("visual_identity", "visual_identity_evidence_ids")):
            if segment["kind"] == field_kind:
                cited = card.get(field_name) if isinstance(card.get(field_name), list) else []
                if segment["evidence_id"] not in cited:
                    card[field_name] = list(cited) + [segment["evidence_id"]]
        notes = card.get("source_notes") if isinstance(card.get("source_notes"), list) else []
        if segment["source_url"] and segment["source_url"] not in notes:
            card["source_notes"] = list(notes) + [segment["source_url"]]
        card = _normalize_card_field_citations(card, ctx["machine"])
        _stamp_card_segment_provenance(card, package)
        warnings = _research_card_contract_warnings(ctx["machine"], card, package, require_source_package=True)
        error = await self._persist_repaired_card(video_id, ctx, card, warnings, "promote_excerpt")
        if error:
            return {"status": "failed", "error": error}
        await self._log_activity(
            "Research Agent", video_id, "completed",
            f"promote_excerpt {segment['source_excerpt_id']} -> {ctx['machine']} "
            + ("(card passes)" if not _blocking_warnings(warnings) else f"({len(warnings)} warnings remain)"),
        )
        return self._repair_response(ctx, "promote_excerpt", warnings, {
            "promoted_evidence_id": segment["evidence_id"],
            "research_payload": await enrich_research_payload_readiness(self.tenant_id, video_id, ctx["payload"]),
        })

    async def repair_rekind_segments(self, video_id: str, machine: str) -> dict:
        """Free structural surgery on evidence segments. Two deterministic moves:

        1. A required-beat segment whose raw excerpt is hinted for a DIFFERENT
           beat gets re-kinded TOWARD the hint (the compliant direction under
           the relabel law), and the vacated beat is back-filled by promoting a
           correctly-hinted Tier 1-3 excerpt from the package.
        2. A required beat sitting only on Tier 4/caution rows gets a Tier 1-3
           hinted excerpt promoted alongside it."""
        await self._ensure_initialized()
        ctx = await self._load_machine_repair_context(video_id, machine)
        if ctx.get("error"):
            return {"status": "failed", "error": ctx["error"]}
        card, package = ctx["card"], ctx["package"]
        if card is None or package is None:
            return {"status": "failed", "error": "Segment surgery needs a saved card and verified source package"}
        machine_name = ctx["machine"]
        segments = card.get("evidence_segments") if isinstance(card.get("evidence_segments"), list) else []
        card["evidence_segments"] = segments
        plan = _segment_surgery_plan(card, package, machine_name)
        if not plan["rekinds"] and not plan["promotes"]:
            blocked = ", ".join(sorted({str(b["role"]) for b in plan["blocked"]})) or "none"
            return {
                "status": "failed",
                "error": f"No structural segment surgery applies; beats blocked on package gaps: {blocked}",
            }
        changes: list[str] = []
        for rekind in plan["rekinds"]:
            rekind["segment"]["kind"] = rekind["new_kind"]
            changes.append(f"re-kinded {rekind['evidence_id']} {rekind['old_kind']} -> {rekind['new_kind']}")
        for promote in plan["promotes"]:
            existing_ids = {
                str(seg.get("evidence_id") or "").strip()
                for seg in segments if isinstance(seg, dict)
            }
            segment = _promoted_evidence_segment(promote["item"], promote["kind"], machine_name, existing_ids)
            segments.append(segment)
            notes = card.get("source_notes") if isinstance(card.get("source_notes"), list) else []
            if segment["source_url"] and segment["source_url"] not in notes:
                card["source_notes"] = list(notes) + [segment["source_url"]]
            changes.append(f"promoted {segment['source_excerpt_id']} as {promote['kind']}")
        for blocked in plan["blocked"]:
            changes.append(f"blocked: no promotable {blocked['role']} excerpt in package")
        card = _normalize_card_field_citations(card, machine_name)
        _stamp_card_segment_provenance(card, package)
        warnings = _research_card_contract_warnings(machine_name, card, package, require_source_package=True)
        error = await self._persist_repaired_card(video_id, ctx, card, warnings, "rekind_segments")
        if error:
            return {"status": "failed", "error": error}
        await self._log_activity(
            "Research Agent", video_id, "completed",
            f"rekind_segments -> {machine_name}: " + "; ".join(changes[:4])
            + (" (card passes)" if not _blocking_warnings(warnings) else f" ({len(warnings)} warnings remain)"),
        )
        return self._repair_response(ctx, "rekind_segments", warnings, {
            "changes": changes,
            "research_payload": await enrich_research_payload_readiness(self.tenant_id, video_id, ctx["payload"]),
        })

    async def repair_rewrite_field(self, video_id: str, machine: str, field: Optional[str] = None) -> dict:
        """Rewrite exactly ONE card field with a small LLM call; evidence untouched."""
        import json as _json_rw

        await self._ensure_initialized()
        ctx = await self._load_machine_repair_context(video_id, machine)
        if ctx.get("error"):
            return {"status": "failed", "error": ctx["error"]}
        card, package = ctx["card"], ctx["package"]
        if card is None or package is None:
            return {"status": "failed", "error": "Rewrite needs a saved card and verified source package; run one-machine research first"}
        anthropic_client = getattr(self._pipeline, "anthropic", None)
        if anthropic_client is None:
            return {"status": "failed", "error": "Field rewrite requires an Anthropic client, but none is configured."}
        warnings_before = _blocking_warnings(
            _research_card_contract_warnings(ctx["machine"], card, package, require_source_package=True)
        )
        if not field:
            field = next(
                (item for item in _REWRITABLE_CARD_FIELDS
                 if any(_warning_targets_field(w, item) for w in warnings_before)),
                "",
            )
        if field not in _REWRITABLE_CARD_FIELDS:
            return {"status": "failed", "error": f"No rewritable field warning found (field={field or 'auto'})"}
        field_warnings = [w for w in warnings_before if _warning_targets_field(w, field)]
        # Show the LLM the NORMALIZED evidence (post-clamp), never the raw
        # claims: a raw claim can carry words the excerpt lacks (the XB-15
        # calendar-page "October"), and the referee grades against the clamped
        # universe - a rewrite fed raw claims keeps the ungrounded word forever.
        normalized_evidence, _normalize_errors = _normalize_machine_evidence(card, ctx["machine"])
        segments_view = [
            {
                "evidence_id": segment.get("evidence_id"),
                "kind": segment.get("kind"),
                "claim": segment.get("claim"),
                "source_excerpt": segment.get("source_excerpt"),
            }
            for segment in normalized_evidence
            if isinstance(segment, dict)
        ]
        cites_ids = field in ("timeframe", "visual_identity")
        response_keys = f'{{"{field}": "..."' + (f', "{field}_evidence_ids": ["..."]' if cites_ids else "") + "}"
        prompt = (
            f"Rewrite ONE field of a Designed vs Used research card for LOCKED MACHINE: {ctx['machine']}.\n\n"
            f"FIELD: {field}\n"
            f"FIELD CONTRACT: {_FIELD_REWRITE_CONTRACTS[field]}\n"
            f"CURRENT VALUE: {str(card.get(field) or '(empty)')}\n"
            f"REVIEW WARNINGS: {'; '.join(field_warnings) or '; '.join(warnings_before[:4])}\n\n"
            "Use ONLY the factual words and numbers inside these evidence segments. "
            "Do not touch, add, or remove evidence segments.\n"
            f"EVIDENCE SEGMENTS:\n{_json_rw.dumps(segments_view, ensure_ascii=False)[:12000]}\n\n"
            f"Return ONLY valid JSON: {response_keys}"
        )
        raw = await anthropic_client.generate(
            prompt=prompt,
            system_prompt="You repair exactly one field of a JSON research card. Output only valid JSON.",
            max_tokens=600,
            temperature=0.05,
        )
        try:
            text = str(raw or "").strip()
            if text.startswith("```"):
                import re as _re_rw
                text = _re_rw.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=_re_rw.I | _re_rw.S).strip()
            parsed = _json_rw.loads(text)
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": f"invalid JSON field rewrite: {str(exc)[:120]}"}
        if not isinstance(parsed, dict) or not str(parsed.get(field) or "").strip():
            return {"status": "failed", "error": f"field rewrite returned no {field}"}
        card[field] = str(parsed.get(field)).strip()
        if cites_ids and isinstance(parsed.get(f"{field}_evidence_ids"), list):
            card[f"{field}_evidence_ids"] = [
                str(item).strip() for item in parsed[f"{field}_evidence_ids"] if str(item).strip()
            ]
        card = _normalize_card_field_citations(card, ctx["machine"])
        _stamp_card_segment_provenance(card, package)
        warnings = _research_card_contract_warnings(ctx["machine"], card, package, require_source_package=True)
        error = await self._persist_repaired_card(video_id, ctx, card, warnings, "rewrite_field")
        if error:
            return {"status": "failed", "error": error}
        await self._log_activity(
            "Research Agent", video_id, "completed",
            f"rewrite_field {field} -> {ctx['machine']} "
            + ("(card passes)" if not _blocking_warnings(warnings) else f"({len(warnings)} warnings remain)"),
        )
        return self._repair_response(ctx, "rewrite_field", warnings, {
            "field": field,
            "research_payload": await enrich_research_payload_readiness(self.tenant_id, video_id, ctx["payload"]),
        })

    async def repair_targeted_fetch(self, video_id: str, machine: str, focus: Optional[str] = None) -> dict:
        """APPEND-ONLY fetch into the existing verified source package.

        Full research re-runs replace the package and re-roll good evidence
        (proven on XB-15, 2026-07-16). This verb only ever adds sources and
        excerpts; existing rows are never touched."""
        import httpx as _httpx
        import json as _json_tf

        await self._ensure_initialized()
        ctx = await self._load_machine_repair_context(video_id, machine)
        if ctx.get("error"):
            return {"status": "failed", "error": ctx["error"]}
        package = ctx["package"]
        if package is None or not isinstance(package.get("candidate_excerpts"), list):
            return {"status": "failed", "error": "No verified source package to extend; run one-machine research first"}
        machine_name = ctx["machine"]
        package_errors = (
            _verified_machine_source_package_quality_errors(package, machine_name)
            + _verified_machine_source_package_identity_errors(package, machine_name)
        )
        if not focus:
            focus = "tier" if any("Tier 1-2" in error for error in package_errors) else (
                "slots" if package_errors else "tier"
            )
        include_domains: Optional[list[str]] = None
        if focus.startswith("slot:"):
            slot = focus.split(":", 1)[1]
            terms = _SLOT_FETCH_QUERY_TERMS.get(slot, "history development service")
            queries = [
                f'"{machine_name}" {terms}',
                f'"{machine_name}" fact sheet history',
                f'"{machine_name}" development program history',
            ]
        elif focus == "tier":
            include_domains = list(_TARGETED_FETCH_PRIMARY_DOMAINS)
            queries = [
                f'"{machine_name}" fact sheet',
                f'"{machine_name}" history museum',
                f'"{machine_name}" development service',
            ]
        elif focus == "reality":
            queries = [
                f'"{machine_name}" service history operational use combat',
                f'"{machine_name}" converted redesignated retired scrapped fate',
                f'"{machine_name}" transport cargo missions wartime',
            ]
        else:  # slot coverage gaps
            queries = [
                f'"{machine_name}" design requirement program development history',
                f'"{machine_name}" limitation tradeoff lessons learned test',
                f'"{machine_name}" production service operational record',
            ]
        tavily_key = await get_secret("tavily_api_key", self.tenant_id)
        if not tavily_key:
            return {"status": "failed", "error": "Tavily API key is required for targeted source fetching."}
        existing_sources = [s for s in (package.get("sources") or []) if isinstance(s, dict)]
        existing_urls = {
            str(s.get("url") or "").strip() for s in existing_sources if str(s.get("url") or "").strip()
        }
        new_sources: list[dict] = []
        new_excerpts: list[dict] = []
        errors: list[str] = []
        headers = {"User-Agent": "StoryEngine/1.0 (targeted source research)"}
        async with _httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
            search_results: list[dict] = []
            for query in queries:
                try:
                    body = {
                        "api_key": tavily_key,
                        "query": query,
                        "search_depth": "advanced",
                        "include_answer": False,
                        "include_raw_content": True,
                        "max_results": 5,
                    }
                    if include_domains:
                        body["include_domains"] = include_domains
                    response = await client.post("https://api.tavily.com/search", json=body)
                    if response.status_code >= 400:
                        errors.append(f"Tavily search failed for {query}: HTTP {response.status_code}")
                        continue
                    for item in (response.json().get("results") or []):
                        if isinstance(item, dict) and item.get("url"):
                            item = dict(item)
                            item["_query"] = query
                            search_results.append(item)
                except Exception as exc:  # noqa: BLE001 - keep gathering from remaining queries.
                    errors.append(f"Tavily search failed for {query}: {str(exc)[:120]}")
            seen_urls: set[str] = set(existing_urls)
            for item in search_results:
                if len(new_sources) >= 6 or len(new_excerpts) >= 30:
                    break
                url = str(item.get("url") or "").strip()
                title_text = str(item.get("title") or url).strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                fetched_text = await self._fetch_source_text(client, url)
                raw_content = str(item.get("raw_content") or "")
                source_variants: list[tuple[tuple[int, int, int, int], str, str, list[str]]] = []
                for capture_method, source_text in (
                    ("fetched_page", fetched_text),
                    ("tavily_raw_content", raw_content),
                ):
                    if not source_text or not _mentions_machine(source_text, machine_name):
                        continue
                    excerpt_candidates = _sentence_candidates_from_source(source_text, machine_name, limit=10)
                    if not excerpt_candidates:
                        continue
                    coverage_score = _machine_source_variant_score(excerpt_candidates, machine_name)
                    method_priority = 1 if capture_method == "fetched_page" else 0
                    source_variants.append(
                        ((*coverage_score, method_priority), capture_method, source_text, excerpt_candidates)
                    )
                if not source_variants:
                    continue
                _score, capture_method, source_text, excerpt_candidates = max(source_variants, key=lambda row: row[0])
                variant_selection = _machine_source_variant_selection_metadata(source_variants, capture_method)
                source_id = f"S{len(existing_sources) + len(new_sources) + 1}"
                source_tier = _source_tier_for_url(url, title_text)
                new_sources.append({
                    "source_id": source_id,
                    "title": title_text,
                    "url": url,
                    "source_tier": source_tier["tier"],
                    "source_tier_label": source_tier["label"],
                    "query": item.get("_query"),
                    "source_capture_method": capture_method,
                    "source_variant_selection": variant_selection,
                    "text_hash": _source_text_fingerprint(source_text),
                    "text_chars": len(source_text),
                    "appended_by": "targeted_fetch",
                })
                for excerpt_index, excerpt in enumerate(excerpt_candidates, start=1):
                    excerpt_id = f"{source_id}-E{excerpt_index}"
                    new_excerpts.append({
                        "excerpt_id": excerpt_id,
                        "source_id": source_id,
                        "source_title": title_text,
                        "source_url": url,
                        "source_tier": source_tier["tier"],
                        "source_tier_label": source_tier["label"],
                        "source_capture_method": capture_method,
                        "source_variant_selection": variant_selection,
                        "locator": f"{excerpt_id}; query={item.get('_query')}",
                        "text": excerpt,
                        "text_hash": _source_text_fingerprint(excerpt),
                    })
                    if len(new_excerpts) >= 30:
                        break
        if not new_excerpts:
            return {
                "status": "failed",
                "error": "Targeted fetch found no new machine-matching excerpts"
                         + ("; " + "; ".join(errors[:2]) if errors else ""),
                "focus": focus,
            }
        merged = dict(package)
        merged["sources"] = existing_sources + new_sources
        merged["candidate_excerpts"] = list(package.get("candidate_excerpts") or []) + new_excerpts
        merged["search_queries"] = list(dict.fromkeys(list(package.get("search_queries") or []) + queries))
        history = [entry for entry in (package.get("appended_fetches") or []) if isinstance(entry, dict)]
        history.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "focus": focus,
            "queries": queries,
            "added_source_ids": [s["source_id"] for s in new_sources],
            "added_excerpt_count": len(new_excerpts),
        })
        merged["appended_fetches"] = history
        merged["source_slot_coverage"] = _anton_source_slot_coverage(
            [item for item in merged["candidate_excerpts"] if isinstance(item, dict)], machine_name
        )
        merged["traceable_source_slot_coverage"] = _anton_source_slot_coverage(
            [item for item in merged["candidate_excerpts"] if _verified_source_candidate_traceable(item)],
            machine_name,
        )
        merged["passed"] = len([
            item for item in merged["candidate_excerpts"]
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]) >= 6
        fresh_quality_errors = _verified_machine_source_package_quality_errors(merged, machine_name)
        # G14, 2026-07-31: same fix as _gather_verified_machine_source_package
        # - only a genuinely blocking quality error may flip passed to False.
        if _blocking_warnings(fresh_quality_errors):
            merged["passed"] = False
        merged["errors"] = list(dict.fromkeys(errors + fresh_quality_errors)) if fresh_quality_errors else []
        checkpoint = await self._checkpoint_machine_raw_source_package(
            video_id, ctx["code"], merged, ctx["snapshot"]
        )
        if self._db_write_missed(checkpoint):
            return {"status": "failed", "error": "persisted unit_roster changed concurrently; targeted fetch save refused"}
        ctx["payload"].setdefault("machine_raw_source_packages", {})[ctx["code"]] = merged
        _clear_machine_preview_artifacts(ctx["payload"], ctx["code"])
        card_warnings: list[str] = []
        if isinstance(ctx["card"], dict):
            hydrated = _verified_machine_source_package_with_anton_metadata(merged, machine_name)
            _stamp_card_segment_provenance(ctx["card"], hydrated)
            card_warnings = _research_card_contract_warnings(
                machine_name, ctx["card"], hydrated, require_source_package=True
            )
            error = await self._persist_repaired_card(video_id, ctx, ctx["card"], card_warnings, "targeted_fetch")
            if error:
                return {"status": "failed", "error": error}
        await self._log_activity(
            "Research Agent", video_id, "completed",
            f"targeted_fetch({focus}) appended {len(new_sources)} source(s), {len(new_excerpts)} excerpt(s) -> {machine_name}",
        )
        return self._repair_response(ctx, "targeted_fetch", card_warnings, {
            "focus": focus,
            "added_sources": [
                {"source_id": s["source_id"], "url": s["url"], "source_tier": s["source_tier"]}
                for s in new_sources
            ],
            "added_excerpt_count": len(new_excerpts),
            "package_passed": bool(merged.get("passed")),
            "package_errors": fresh_quality_errors,
            "research_payload": await enrich_research_payload_readiness(self.tenant_id, video_id, ctx["payload"]),
        })

    async def repair_mark_bare(self, video_id: str, machine: str) -> dict:
        """Deliberately-bare fallback: honest bare tag with a sourced hunt summary.

        Only legal when the package holds NO unselected role-conversion story -
        a bare tag on top of an available story would be a lie the referee
        exists to prevent."""
        import json as _json_mb

        await self._ensure_initialized()
        ctx = await self._load_machine_repair_context(video_id, machine)
        if ctx.get("error"):
            return {"status": "failed", "error": ctx["error"]}
        card, package = ctx["card"], ctx["package"]
        if card is None or package is None:
            return {"status": "failed", "error": "Bare tag needs a saved card and verified source package"}
        evidence = card.get("evidence_segments") or []
        unselected = [
            signal for signal in _package_conversion_signals(package, ctx["machine"])
            if signal.get("enforce") and not _card_evidence_carries_signal(evidence, signal)
        ]
        if unselected:
            return {
                "status": "failed",
                "error": "package holds a role-conversion story; promote it instead of marking bare "
                         f"(excerpt {unselected[0].get('excerpt_id')})",
            }
        anthropic_client = getattr(self._pipeline, "anthropic", None)
        if anthropic_client is None:
            return {"status": "failed", "error": "Bare tag summary requires an Anthropic client, but none is configured."}
        searched = list(package.get("search_queries") or [])
        for entry in package.get("appended_fetches") or []:
            if isinstance(entry, dict):
                searched.extend(entry.get("queries") or [])
        prompt = (
            f"LOCKED MACHINE: {ctx['machine']}.\n"
            "The research hunt for a designed-vs-used gap (how this machine was ACTUALLY used or ended: "
            "combat, service, conversion, redesignation, cancellation, scrapping) found no use-story in any "
            "fetched source. Write the required honest gap_hunt_summary: one or two sentences stating what "
            "was searched and why no use-story exists. State only what the queries and sources show.\n\n"
            f"QUERIES RUN:\n{_json_mb.dumps(searched, ensure_ascii=False)[:2000]}\n\n"
            f"SOURCES FETCHED:\n{_json_mb.dumps([str(s.get('title') or s.get('url') or '') for s in (package.get('sources') or []) if isinstance(s, dict)], ensure_ascii=False)[:2000]}\n\n"
            'Return ONLY valid JSON: {"gap_hunt_summary": "..."}'
        )
        raw = await anthropic_client.generate(
            prompt=prompt,
            system_prompt="You write one honest research gap summary. Output only valid JSON.",
            max_tokens=200,
            temperature=0.05,
        )
        try:
            text = str(raw or "").strip()
            if text.startswith("```"):
                import re as _re_mb
                text = _re_mb.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=_re_mb.I | _re_mb.S).strip()
            summary = str((_json_mb.loads(text) or {}).get("gap_hunt_summary") or "").strip()
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": f"invalid JSON bare summary: {str(exc)[:120]}"}
        card["deliberately_bare"] = True
        card["gap_hunt_summary"] = summary
        if not _bare_tag_is_valid(card):
            return {"status": "failed", "error": "generated gap_hunt_summary was too thin to honor the bare tag"}
        _stamp_card_segment_provenance(card, package)
        warnings = _research_card_contract_warnings(ctx["machine"], card, package, require_source_package=True)
        error = await self._persist_repaired_card(video_id, ctx, card, warnings, "mark_bare")
        if error:
            return {"status": "failed", "error": error}
        await self._log_activity(
            "Research Agent", video_id, "completed",
            f"mark_bare -> {ctx['machine']} " + ("(card passes)" if not _blocking_warnings(warnings) else f"({len(warnings)} warnings remain)"),
        )
        return self._repair_response(ctx, "mark_bare", warnings, {
            "gap_hunt_summary": summary,
            "research_payload": await enrich_research_payload_readiness(self.tenant_id, video_id, ctx["payload"]),
        })

    async def _select_memorable_excerpt_id(self, machine: str, card: dict, package: dict) -> str:
        """Tiny LLM pick of the most surprising uncited excerpt; promotion stays code."""
        anthropic_client = getattr(self._pipeline, "anthropic", None)
        if anthropic_client is None:
            return ""
        cited = _card_cited_excerpt_ids(card)
        rows = []
        for item in package.get("candidate_excerpts") or []:
            if not isinstance(item, dict) or not _verified_source_candidate_traceable(item):
                continue
            excerpt_id = str(item.get("excerpt_id") or "").strip()
            text = str(item.get("text") or "").strip()
            if not excerpt_id or not text or excerpt_id in cited:
                continue
            if not _mentions_machine(text, machine):
                continue
            rows.append(f"{excerpt_id}: {text[:220]}")
            if len(rows) >= 20:
                break
        if not rows:
            return ""
        raw = await anthropic_client.generate(
            prompt=(
                f"LOCKED MACHINE: {machine}. Pick the ONE excerpt below carrying the most surprising "
                "verified fact a serious viewer is unlikely to know (a pioneered feature, an odd capability, "
                "an unexpected record). Return ONLY that EXCERPT_ID, nothing else.\n\n" + "\n".join(rows)
            ),
            system_prompt="You select one excerpt id. Output only the id.",
            max_tokens=20,
            temperature=0.0,
        )
        token = str(raw or "").strip().split()[0].strip(".,;:\"'`") if str(raw or "").strip() else ""
        return token if _find_candidate_excerpt(package, token) is not None else ""

    async def _execute_repair_action(self, video_id: str, machine: str, action: dict) -> dict:
        """Run one classified repair action; returns the verb result dict."""
        verb = str(action.get("verb") or "")
        if verb == "promote_excerpt":
            return await self.repair_promote_excerpt(
                video_id, machine, str(action.get("excerpt_id") or ""), str(action.get("kind") or "reality")
            )
        if verb == "rekind_segments":
            return await self.repair_rekind_segments(video_id, machine)
        if verb == "targeted_fetch":
            return await self.repair_targeted_fetch(video_id, machine, action.get("focus"))
        if verb == "rewrite_field":
            return await self.repair_rewrite_field(video_id, machine, action.get("field"))
        if verb == "mark_bare":
            return await self.repair_mark_bare(video_id, machine)
        if verb == "select_excerpt":
            ctx = await self._load_machine_repair_context(video_id, machine)
            if ctx.get("error"):
                return {"status": "failed", "error": ctx["error"]}
            if ctx["card"] is None or ctx["package"] is None:
                return {"status": "failed", "error": "select_excerpt needs a saved card and package"}
            excerpt_id = await self._select_memorable_excerpt_id(ctx["machine"], ctx["card"], ctx["package"])
            if not excerpt_id:
                return {"status": "failed", "error": "no promotable memorable-fact excerpt found"}
            return await self.repair_promote_excerpt(video_id, machine, excerpt_id, "memorable_fact")
        if verb == "full_rerun":
            result = await self.run_one_machine_research(video_id, machine)
            result.setdefault("verb", "full_rerun")
            return result
        return {"status": "failed", "error": f"unknown repair verb: {verb}"}

    async def repair_machine_auto(
        self, video_id: str, machine: str, allow_full_rerun: bool = False,
        budget_usd: float = 1.0, max_actions: int = 4,
    ) -> dict:
        """One machine through the cheapest-first ladder until the referee passes."""
        await self._ensure_initialized()
        spend = 0.0
        actions_log: list[dict] = []
        seen: set[str] = set()
        warnings: list[str] = []
        for _attempt in range(max_actions):
            ctx = await self._load_machine_repair_context(video_id, machine)
            if ctx.get("error"):
                return {"status": "failed", "error": ctx["error"], "actions": actions_log}
            card, package = ctx["card"], ctx["package"]
            if card is not None:
                warnings = _blocking_warnings(
                    _research_card_contract_warnings(ctx["machine"], card, package, require_source_package=True)
                )
            else:
                warnings = ["missing saved one-machine research card"]
            if not warnings:
                break
            # Seen-keys carry a state fingerprint so a FREE deterministic verb
            # may run again after another verb changed the card or package
            # (fetch appends an excerpt -> rekind gets a second pass), while
            # identical state never repeats an action.
            excerpt_count = len((package or {}).get("candidate_excerpts") or []) if isinstance(package, dict) else 0
            fingerprint = f"@{excerpt_count}|{len(warnings)}|{abs(hash(tuple(sorted(warnings)))) % 10**8}"
            plan = _classify_repair_actions(ctx["machine"], card, package)
            action = next((a for a in plan if _repair_action_key(a) + fingerprint not in seen), None)
            if action is None:
                break
            if action["verb"] == "full_rerun" and not allow_full_rerun:
                actions_log.append({**action, "status": "skipped", "detail": "full re-run disabled for this pass"})
                break
            cost = _REPAIR_VERB_EST_COST_USD.get(action["verb"], 0.05)
            if spend + cost > budget_usd:
                actions_log.append({**action, "status": "skipped", "detail": f"budget cap ${budget_usd:.2f} reached"})
                break
            seen.add(_repair_action_key(action) + fingerprint)
            result = await self._execute_repair_action(video_id, ctx["machine"], action)
            spend += cost
            actions_log.append({
                **{k: action.get(k) for k in ("verb", "excerpt_id", "kind", "field", "focus", "reason") if action.get(k)},
                "status": result.get("status"),
                "detail": result.get("error") or "",
                "est_cost_usd": cost,
            })
            if result.get("status") == "failed":
                continue
        ctx = await self._load_machine_repair_context(video_id, machine)
        if not ctx.get("error") and ctx.get("card") is not None:
            warnings = _blocking_warnings(
                _research_card_contract_warnings(ctx["machine"], ctx["card"], ctx["package"], require_source_package=True)
            )
        return {
            "status": "completed" if not warnings else "needs_review",
            "machine": ctx.get("machine") or machine,
            "verb": "auto",
            "passed": not warnings,
            "warnings": warnings[:8],
            "actions": actions_log,
            "est_spend_usd": round(spend, 2),
            "research_payload": (
                await enrich_research_payload_readiness(self.tenant_id, video_id, ctx["payload"])
                if not ctx.get("error") else None
            ),
        }

    async def run_roster_orchestrator(
        self,
        video_id: str,
        machines: Optional[list[str]] = None,
        budget_usd: float = 5.0,
        allow_full_rerun: bool = True,
        max_actions_per_machine: int = 4,
        progress: Optional[Any] = None,
    ) -> dict:
        """Walk the locked roster, repairing each failing card cheapest-first.

        Bounded retries per card, one shared budget cap, alerts only on budget
        breach or systemic failure. Done metric: most machines clear in one or
        two actions without a full re-run."""
        import json as _json_orch

        await self._ensure_initialized()
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}
        roster = _machine_documentary_hold_roster(video)
        if not roster:
            return {"status": "failed", "error": "No locked machine roster found"}
        targets = roster
        if machines:
            wanted = {_normalized_unit_code(item) for item in machines if _normalized_unit_code(item)}
            targets = [item for item in roster if _normalized_unit_code(item) in wanted]
            if not targets:
                return {"status": "failed", "error": "None of the requested machines are in the locked roster"}
        spend = 0.0
        units: list[dict] = []
        alerts: list[str] = []
        consecutive_failures = 0
        budget_breached = False
        for index, machine in enumerate(targets, start=1):
            if callable(progress):
                try:
                    progress(f"Repairing {index}/{len(targets)}: {machine}")
                except Exception:  # noqa: BLE001 - progress is advisory only
                    pass
            machine_budget = max(0.0, budget_usd - spend)
            if machine_budget <= 0:
                budget_breached = True
                alerts.append(
                    f"budget cap ${budget_usd:.2f} reached before {machine}; "
                    f"{len(targets) - index + 1} machine(s) not attempted"
                )
                break
            result = await self.repair_machine_auto(
                video_id, machine,
                allow_full_rerun=allow_full_rerun,
                budget_usd=machine_budget,
                max_actions=max_actions_per_machine,
            )
            spend += float(result.get("est_spend_usd") or 0.0)
            unit = {
                "machine": machine,
                "passed": bool(result.get("passed")),
                "actions": result.get("actions") or [],
                "warnings": (result.get("warnings") or [])[:4],
            }
            units.append(unit)
            consecutive_failures = 0 if unit["passed"] else consecutive_failures + 1
            if consecutive_failures >= 3:
                alerts.append(
                    f"systemic failure: 3 machines in a row did not clear (stopped at {machine})"
                )
                break
        # Full-roster readiness from the stored referee verdicts. Keyed by
        # roster_index (migration 153's row identity), not machine_key: two
        # roster entries can share a machine_key, and a machine_key-keyed
        # dict would collapse them onto one verdict.
        ready_count = 0
        try:
            rows = await fetch_all(
                "SELECT roster_index, validation FROM machine_research_cards WHERE tenant_id = $1 AND video_id = $2",
                self.tenant_id, video_id,
            )
            verdicts_by_index = {
                row.get("roster_index"): _card_readiness_from_validation(row.get("validation"))
                for row in rows or [] if isinstance(row, dict) and isinstance(row.get("roster_index"), int)
            }
            ready_count = sum(
                1 for index, _item in enumerate(roster, start=1)
                if (verdicts_by_index.get(index) or {}).get("passed")
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[orchestrator] readiness recount unavailable: %s", str(exc)[:150])
        report = {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "targets": len(targets),
            "attempted": len(units),
            "cleared": sum(1 for unit in units if unit["passed"]),
            "ready_count": ready_count,
            "roster_count": len(roster),
            "est_spend_usd": round(spend, 2),
            "budget_usd": budget_usd,
            "budget_breached": budget_breached,
            "alerts": alerts,
            "units": units,
        }
        # Persist a compact cumulative report for the dashboard.
        try:
            payload = video.get("research_payload") or {}
            if isinstance(payload, str):
                payload = _json_orch.loads(payload)
            previous = payload.get("roster_orchestrator_report") if isinstance(payload, dict) else {}
            previous_total = float((previous or {}).get("est_spend_usd_total") or 0.0)
            stored = {
                **{k: report[k] for k in (
                    "ran_at", "targets", "attempted", "cleared", "ready_count",
                    "roster_count", "est_spend_usd", "budget_usd", "budget_breached", "alerts",
                )},
                "est_spend_usd_total": round(previous_total + spend, 2),
                "units": [
                    {
                        "machine": unit["machine"],
                        "passed": unit["passed"],
                        "verbs": [str(a.get("verb") or "") for a in unit["actions"]],
                        "warnings": unit["warnings"][:2],
                    }
                    for unit in units
                ],
            }
            await execute(
                """UPDATE videos SET research_payload = jsonb_set(
                       COALESCE(research_payload::jsonb, '{}'::jsonb),
                       '{roster_orchestrator_report}', $1::jsonb, true
                   ), updated_at = now()
                   WHERE id = $2 AND tenant_id = $3""",
                _json_orch.dumps(stored), video_id, self.tenant_id,
            )
            report["est_spend_usd_total"] = stored["est_spend_usd_total"]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[orchestrator] report persist skipped: %s", str(exc)[:150])
        await self._log_activity(
            "Research Agent", video_id, "completed",
            f"roster orchestrator: {report['cleared']}/{report['attempted']} cleared, "
            f"{ready_count}/{len(roster)} ready, est ${report['est_spend_usd']:.2f}"
            + ("; " + "; ".join(alerts) if alerts else ""),
        )
        report["status"] = "completed"
        return report

    async def roster_repair_dashboard(self, video_id: str) -> dict:
        """No-spend roster readiness snapshot: N/M ready, per-machine next verb."""
        import json as _json_dash

        await self._ensure_initialized()
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}
        payload = video.get("research_payload") or {}
        if isinstance(payload, str):
            try:
                payload = _json_dash.loads(payload)
            except (ValueError, TypeError):
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        roster = _machine_documentary_hold_roster(video)
        if not roster:
            return {"status": "failed", "error": "No locked machine roster found"}
        payload = await self._load_machine_research_cards(video_id, payload, roster)
        # Keyed by roster_index (migration 153's row identity), not
        # machine_key: two roster entries can share a machine_key, and a
        # machine_key-keyed dict would apply one machine's verdict to a
        # different roster slot.
        verdicts_by_index: dict[int, Optional[dict]] = {}
        try:
            rows = await fetch_all(
                "SELECT roster_index, validation FROM machine_research_cards WHERE tenant_id = $1 AND video_id = $2",
                self.tenant_id, video_id,
            )
            for row in rows or []:
                if isinstance(row, dict) and isinstance(row.get("roster_index"), int):
                    verdicts_by_index[row["roster_index"]] = _card_readiness_from_validation(row.get("validation"))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[orchestrator] dashboard verdict read unavailable: %s", str(exc)[:150])
        previews = payload.get("machine_script_previews")
        previews = previews if isinstance(previews, dict) else {}
        # C3: per-machine reference-photo readiness (static_reference_cache),
        # read live — no new table, computed the same way generate_static_
        # images_for_video itself checks the cache. Best-effort: a read
        # failure (e.g. the cache table not created yet on a tenant that has
        # never run static_docu generation or prefetch) degrades every
        # machine to "missing" rather than failing the whole dashboard.
        ref_cache_by_key: dict[str, dict] = {}
        from static_docu import _machine_key as _static_machine_key
        try:
            ref_rows = await fetch_all(
                "SELECT machine_key, hosted_url, source_url FROM static_reference_cache "
                "WHERE tenant_id = $1", self.tenant_id,
            )
            ref_cache_by_key = {
                row.get("machine_key"): row for row in (ref_rows or []) if isinstance(row, dict)
            }
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[orchestrator] dashboard reference read unavailable: %s", str(exc)[:150])
        # C8: WHY a still-missing machine missed, read per-video from
        # static_reference_misses (static_docu._record_reference_miss /
        # _clear_reference_miss). Same degrade-gracefully pattern as the
        # cache read above — a table that doesn't exist yet (tenant has
        # never run a prefetch) just means every machine shows "missing"
        # with no reason, not a broken dashboard.
        miss_by_key: dict[str, dict] = {}
        try:
            miss_rows = await fetch_all(
                "SELECT machine_key, reason_code, reason_detail FROM static_reference_misses "
                "WHERE tenant_id = $1 AND video_id = $2", self.tenant_id, video_id,
            )
            miss_by_key = {
                row.get("machine_key"): row for row in (miss_rows or []) if isinstance(row, dict)
            }
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[orchestrator] dashboard miss-reason read unavailable: %s", str(exc)[:150])
        units: list[dict] = []
        ready_count = 0
        for roster_position, machine in enumerate(roster, start=1):
            code = _normalized_unit_code(machine)
            verdict = verdicts_by_index.get(roster_position)
            card = _research_card_for_machine(payload, machine)
            package = _verified_source_package_for_machine(payload, machine)
            if package is not None:
                package = _verified_machine_source_package_with_anton_metadata(package, machine)
            passed = bool((verdict or {}).get("passed"))
            state = "ready" if passed else ("needs_research" if card is None else "needs_repair")
            if passed:
                ready_count += 1
            suggestion = None
            if not passed:
                plan = _classify_repair_actions(machine, card, package)
                if plan:
                    suggestion = {k: plan[0].get(k) for k in ("verb", "excerpt_id", "kind", "field", "focus", "reason") if plan[0].get(k)}
            preview = previews.get(code) if isinstance(previews.get(code), dict) else None
            ref_row = ref_cache_by_key.get(_static_machine_key(machine))
            if ref_row:
                reference = {
                    "status": "verified",
                    "hosted_url": ref_row.get("hosted_url"),
                    "source_url": ref_row.get("source_url"),
                }
            else:
                miss_row = miss_by_key.get(_static_machine_key(machine))
                reference = {"status": "missing"}
                if miss_row:
                    # never_built (reserved for C5, not produced yet) is the
                    # one code that means "stop offering to retry" — every
                    # other code is a worth-another-try miss. Surfaced as a
                    # separate boolean rather than making the frontend know
                    # the reason vocabulary, so C5 slotting in the real
                    # never_built detection later needs no frontend change.
                    reference["reason_code"] = miss_row.get("reason_code")
                    reference["reason_detail"] = miss_row.get("reason_detail")
                    reference["retryable"] = miss_row.get("reason_code") != "never_built"
            units.append({
                "machine": machine,
                "state": state,
                "warnings": ((verdict or {}).get("warnings") or [])[:4],
                "suggested_action": suggestion,
                "preview": (
                    {
                        "passed": bool(preview.get("passed")),
                        "word_count": preview.get("word_count"),
                    } if preview else None
                ),
                "reference": reference,
            })
        report = payload.get("roster_orchestrator_report")
        report = report if isinstance(report, dict) else {}
        return {
            "status": "completed",
            "video_id": video_id,
            "ready": ready_count,
            "total": len(roster),
            "est_spend_usd_total": float(report.get("est_spend_usd_total") or 0.0),
            "last_run": {
                k: report.get(k) for k in ("ran_at", "attempted", "cleared", "alerts", "budget_breached")
                if k in report
            } if report else None,
            "units": units,
        }

    async def run_unit_research(self, video_id: str) -> dict:
        """Continue the locked-roster machine research hold without rediscovering the roster."""
        await self._ensure_initialized()
        bot_name = "Machine Research Agent"
        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            payload = video.get("research_payload") or {}
            if isinstance(payload, str):
                import json as _json
                payload = _json.loads(payload)
            if not isinstance(payload, dict):
                return {"status": "failed", "error": "Research payload is missing or invalid"}

            # Recomputed, not read back off the row — see _live_roster_gate.
            # This is the gate that was blocking per-machine research on a
            # verdict written by rules that no longer exist.
            roster_gate = _live_roster_gate(video, payload)
            if not roster_gate.get("passed"):
                return {"status": "failed", "error": "Lock and approve the machine roster before running machine research"}

            roster = _machine_documentary_hold_roster(video)
            if not roster:
                return {"status": "failed", "error": "No locked machine roster found"}

            title = video.get("video_title") or video.get("headline") or "Untitled documentary"
            await self._log_activity(bot_name, video_id, "started", f"Researching {len(roster)} locked machines")
            payload = await self._run_unit_research_hold(video_id, title, payload, roster)
            validation = payload.get("unit_research_hold_validation") or {}
            passed = bool(validation.get("passed"))
            next_status = "ready_for_scripting" if passed else (video.get("status") or "idea_logged")

            import json as _json
            save_result = await execute(
                "UPDATE videos SET research_payload = $1, status = $2, updated_at = now() WHERE id = $3 AND tenant_id = $4",
                _json.dumps(payload), next_status, video_id, self.tenant_id,
            )
            if self._db_write_missed(save_result):
                warning = "Machine research save refused because the video is no longer available for this tenant"
                await self._log_activity(bot_name, video_id, "failed", warning)
                return {"status": "failed", "video_id": video_id, "error": warning}
            from drive_workspace import sync_video_workspace_fail_soft
            await sync_video_workspace_fail_soft(video_id, self.tenant_id)
            completed = len(payload.get("unit_research_cards") or [])
            if passed:
                await self._log_activity(bot_name, video_id, "completed", f"Machine research complete: {completed}/{len(roster)}")
                return {"status": next_status, "video_id": video_id, "message": f"Machine research complete: {completed}/{len(roster)}"}

            warning = "; ".join(str(w) for w in validation.get("warnings", [])) or "Machine research validation failed"
            await self._log_activity(bot_name, video_id, "failed", warning[:800])
            return {"status": "failed", "video_id": video_id, "error": warning}
        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def _inject_learnings_into_writer_guidance(self, video_id: str):
        """Inject learned patterns into writer_guidance before script generation.

        This closes the script feedback loop: videos with high/low retention
        have their structural patterns extracted → stored in learnings table →
        injected here as writer guidance → script generator adapts.
        """
        try:
            learnings = await fetch_all(
                """SELECT category, pattern, avg_ctr, avg_retention, sample_size, confidence
                   FROM learnings
                   WHERE tenant_id = $1 AND active = true
                     AND category IN ('script', 'hook', 'framework')
                     AND confidence >= 40
                   ORDER BY confidence DESC, avg_retention DESC NULLS LAST
                   LIMIT 10""",
                self.tenant_id,
            )
            if not learnings:
                return

            guidance_lines = ["\n\n--- PERFORMANCE LEARNINGS (from past videos) ---"]
            for l in learnings:
                cat = l.get("category", "")
                pattern = l.get("pattern", "")
                ret = float(l["avg_retention"]) if l.get("avg_retention") else None
                ctr = float(l["avg_ctr"]) if l.get("avg_ctr") else None
                conf = float(l.get("confidence", 0))
                verdict = "PROVEN" if conf >= 60 else "AVOID" if conf <= 40 else "TESTING"

                metrics = []
                if ret:
                    metrics.append(f"{ret:.0f}% retention")
                if ctr:
                    metrics.append(f"{ctr:.1f}% CTR")
                metric_str = f" ({', '.join(metrics)})" if metrics else ""

                if verdict == "AVOID":
                    guidance_lines.append(f"- AVOID: {pattern}{metric_str}")
                else:
                    guidance_lines.append(f"- USE: {pattern}{metric_str} [{verdict}]")

            guidance_lines.append("--- END LEARNINGS ---")
            learnings_block = "\n".join(guidance_lines)

            # Append to existing writer_guidance
            video = await fetch_one(
                "SELECT writer_guidance FROM videos WHERE id = $1",
                video_id,
            )
            existing = (video or {}).get("writer_guidance") or ""
            updated = existing + learnings_block

            await execute(
                "UPDATE videos SET writer_guidance = $1 WHERE id = $2",
                updated, video_id,
            )
            # Capture WHAT was applied so the creator can see it (autopilot scorecard
            # + chat) - transparency, not a black box.
            try:
                import json as _json
                applied = [
                    {
                        "category": l.get("category", ""),
                        "pattern": l.get("pattern", ""),
                        "verdict": ("PROVEN" if float(l.get("confidence", 0)) >= 60
                                    else "AVOID" if float(l.get("confidence", 0)) <= 40 else "TESTING"),
                    }
                    for l in learnings
                ]
                await execute(
                    "UPDATE videos SET applied_intelligence = "
                    "COALESCE(applied_intelligence, '{}'::jsonb) || jsonb_build_object('learnings_used', $1::jsonb) "
                    "WHERE id = $2",
                    _json.dumps(applied), video_id,
                )
            except Exception as _e:
                print(f"[Script] record applied learnings failed: {_e}")
            print(f"[Script] Injected {len(learnings)} learnings into writer_guidance for {video_id[:8]}")

        except Exception as e:
            print(f"[Script] Error injecting learnings: {e}")

    async def _static_unit_roster(self, video: dict) -> list[str]:
        """The machine list a static documentary must cover, in order.

        Source of truth is the research payload: a structured `unit_roster`
        field when research provided one, else a one-shot extraction from the
        fact sheet (cheap, and works for payloads created before the roster
        field existed). Returns [] when nothing reliable is available - the
        script then runs uncontracted rather than with a bad roster."""
        import json as _json_ur

        rp = video.get("research_payload")
        if isinstance(rp, str):
            try:
                rp = _json_ur.loads(rp)
            except (ValueError, TypeError):
                return []
        if not isinstance(rp, dict):
            return []

        roster = rp.get("unit_roster")
        if isinstance(roster, list):
            names = [_unit_display_name(m) for m in roster]
            names = [n for n in names if n]
            if 3 <= len(names) <= 40:
                return names

        fact = rp.get("fact_sheet") or ""
        if not isinstance(fact, str) or len(fact) < 200:
            return []
        try:
            raw = await self._pipeline.anthropic.generate(
                prompt=(
                    "From this research fact sheet, list every distinct MACHINE it covers "
                    "(exact designation and name, e.g. 'Boeing XB-15', 'Convair B-36 Peacemaker'), "
                    "in the order they appear. One per line. No numbering, no commentary, "
                    "no variants that are only mentioned in passing - only machines with their "
                    "own story block.\n\n" + fact[:12000]
                ),
                system_prompt="You extract structured lists. Output only the list, one item per line.",
                max_tokens=800,
                temperature=0.0,
            )
            names = [ln.strip(" -•\t") for ln in (raw or "").splitlines() if ln.strip()]
            names = [n for n in names if 2 <= len(n.split()) <= 8][:32]
            return names if len(names) >= 8 else []
        except Exception as e:  # noqa: BLE001 — roster is an enhancement, never a blocker
            _logger.warning("[unit-roster] extraction failed: %s", str(e)[:150])
            return []

    async def _run_unit_research_hold(
        self,
        video_id: str,
        title: str,
        payload: dict,
        roster: list[str],
        target_machine: Optional[str] = None,
    ) -> dict:
        """DVsU/static-docu research path: enrich one locked machine at a time.

        This runs after roster validation passes. It does not reopen the roster;
        it creates/updates `unit_research_cards[]` so script-hold can consume a
        small card for the current machine instead of the full video fact blob.
        """
        import json as _json_uh

        bot_name = "Research Agent"
        if not isinstance(payload, dict) or not roster:
            return payload
        target_code = _normalized_unit_code(_unit_display_name(target_machine or "")) if target_machine else ""
        original_unit_research_cards = (
            list(payload.get("unit_research_cards"))
            if isinstance(payload.get("unit_research_cards"), list)
            else []
        )
        payload = await self._load_machine_research_cards(
            video_id, payload, roster, target_machine=target_machine if target_code else None
        )

        # Exact serialized snapshot, not merely a count/name projection. Every
        # card pass must leave the structured locked roster byte-for-byte equal.
        locked_roster_snapshot = _json_uh.dumps(payload.get("unit_roster"), sort_keys=True, ensure_ascii=False)
        verified_source_package: Optional[dict] = None

        def _hydrate_compatibility_fields(card: dict) -> dict:
            """Derive legacy UI fields from schema-v3 evidence without asking the model to repeat itself."""
            if not isinstance(card, dict):
                return card
            segments = card.get("evidence_segments") or []
            by_kind = {}
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                kind = str(segment.get("kind") or "").strip().lower()
                if _anton_slot_role_for_kind(kind) == "reality" and kind in {"historical_meaning", "legacy"}:
                    kind = "reality"
                by_kind[kind] = str(segment.get("claim") or "").strip()
            card.setdefault(
                "design_problem",
                by_kind.get("original_problem")
                or by_kind.get("engineering_intent")
                or by_kind.get("design_requirement")
                or by_kind.get("doctrinal_problem")
                or by_kind.get("identity_origin")
                or by_kind.get("design_problem")
                or by_kind.get("design_intent")
                or "",
            )
            card.setdefault(
                "engineering_response",
                by_kind.get("engineering_decision")
                or by_kind.get("design_response")
                or by_kind.get("scale_specs")
                or by_kind.get("engineering_response")
                or "",
            )
            card.setdefault(
                "tradeoff",
                by_kind.get("tradeoff")
                or by_kind.get("tradeoff_or_limit")
                or by_kind.get("limitation")
                or by_kind.get("failure_mode")
                or "",
            )
            card.setdefault(
                "actual_outcome",
                by_kind.get("reality")
                or by_kind.get("actual_reality")
                or by_kind.get("actual_outcome")
                or by_kind.get("service_reality")
                or by_kind.get("operational_reality")
                or by_kind.get("test_result")
                or by_kind.get("combat_reality")
                or by_kind.get("build_reality")
                or "",
            )
            card.setdefault("why_this_unit_deserves_a_paragraph", "")
            card.setdefault("onscreen_label", by_kind.get("onscreen_label") or "")
            card.setdefault(
                "surprising_fact",
                by_kind.get("memorable_fact")
                or by_kind.get("surprising_fact")
                or by_kind.get("retention_fact")
                or by_kind.get("human_detail")
                or card.get("surprising_fact")
                or by_kind.get("build_reality")
                or by_kind.get("combat_reality")
                or by_kind.get("service_reality")
                or card.get("actual_outcome")
                or card.get("tradeoff")
                or card.get("engineering_response")
                or "",
            )
            card.setdefault("source_notes", list(dict.fromkeys(
                str(segment.get("source_url") or segment.get("locator") or "").strip()
                for segment in segments if isinstance(segment, dict) and (segment.get("source_url") or segment.get("locator"))
            )))
            card.setdefault("high_risk_claims", [])
            return card

        def _card_warnings(
            machine: str,
            card: dict,
            source_package: Optional[dict] = None,
            require_source_package: bool = False,
        ) -> list[str]:
            return _research_card_contract_warnings(
                machine,
                card,
                source_package,
                require_source_package=require_source_package,
            )

        def _reanchor_card_citations_by_text(target_card: dict, package: Optional[dict]) -> int:
            """FREE, deterministic (no model call): re-point a segment's
            source_excerpt_id/source_url/source_title/locator to the CURRENT
            package row whose EXACT_TEXT contains that segment's own
            source_excerpt, when ids/locators drifted (a package rebuild
            renumbers/drops rows and strands a previously-fine card on stale
            identity). Ported from tasks/evidence/dvsu-research-simulator/
            reanchor_card.py: content is never altered, only provenance
            fields; a segment whose text no longer exists anywhere in the
            package is left untouched (that needs a real repair, not a
            re-label). Uses the SAME normalizer (_normalized_source_text)
            _validate_card_against_verified_sources itself uses for its
            excerpt-in-candidate_text match, so a re-anchor here is
            guaranteed to satisfy the referee. Returns segments moved."""
            if not isinstance(target_card, dict) or not isinstance(package, dict):
                return 0
            candidates = [
                item for item in package.get("candidate_excerpts") or []
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ]
            normed_candidates = [
                (item, _normalized_source_text(str(item.get("text") or "")))
                for item in candidates
            ]
            moved = 0
            for segment in target_card.get("evidence_segments") or []:
                if not isinstance(segment, dict):
                    continue
                want = _normalized_source_text(str(segment.get("source_excerpt") or "")).strip()
                if not want:
                    continue
                row = next((item for item, text in normed_candidates if want in text), None)
                if row is None:
                    continue
                new_excerpt_id = str(row.get("excerpt_id") or "").strip()
                new_locator = str(row.get("locator") or "").strip() or str(segment.get("locator") or "").strip()
                new_source_url = str(row.get("source_url") or "").strip()
                current_excerpt_id = str(segment.get("source_excerpt_id") or segment.get("excerpt_id") or "").strip()
                if (
                    current_excerpt_id == new_excerpt_id
                    and str(segment.get("locator") or "").strip() == new_locator
                    and str(segment.get("source_url") or "").strip() == new_source_url
                ):
                    continue
                segment["source_excerpt_id"] = new_excerpt_id
                segment["source_url"] = new_source_url
                segment["source_title"] = str(row.get("source_title") or "").strip()
                segment["locator"] = new_locator
                moved += 1
            return moved

        def _best_inflection_match(word: str, evidence_words: set) -> Optional[str]:
            """Find the evidence word most likely to be a different inflection
            of `word` ("spent" -> "spending"). _grounding_stem only strips
            regular suffixes, so it never bridges pairs like this (spend/spent
            share no suffix-stripped stem) - a shared-prefix ratio is the
            simplest deterministic signal a human coordinator uses when
            eyeballing this exact fix, and it stays conservative: both words
            must be at least 4 characters and share at least 4 leading
            characters covering most of the shorter word."""
            if len(word) < 4:
                return None
            best, best_len = None, 0
            for candidate in evidence_words:
                if candidate == word or len(candidate) < 4:
                    continue
                shared = 0
                for a, b in zip(word, candidate):
                    if a != b:
                        break
                    shared += 1
                if shared < 4:
                    continue
                if shared / min(len(word), len(candidate)) < 0.65:
                    continue
                if shared > best_len:
                    best, best_len = candidate, shared
            return best

        def _apply_inflection_grounding_fixes(
            field_text: str,
            evidence_text: str,
            machine_name: str,
            extra_stopwords: Optional[set] = None,
        ) -> tuple[str, int]:
            """FREE, deterministic single-word grounding fix: for each word the
            referee flags as ungrounded, either swap it for the excerpt's own
            inflection of the word ("spent" -> "spending", matching the
            hand-fixes made this week) or drop a stray filler word models keep
            adding that never appears in any excerpt ("seen"/"ship"/"plus"/
            "toward"/"towards"). Returns (new_text, words_fixed)."""
            ungrounded = _ungrounded_factual_words(
                field_text, evidence_text, machine_name, extra_stopwords=extra_stopwords
            )
            if not ungrounded:
                return field_text, 0
            evidence_words = set(re.findall(r"[a-z]+", evidence_text.lower()))
            new_text = field_text
            fixed = 0
            for word in ungrounded:
                if word in _GROUNDING_STRAY_DROP_WORDS:
                    replaced = re.sub(rf"\s*\b{re.escape(word)}\b", "", new_text, count=1, flags=re.IGNORECASE)
                    if replaced != new_text:
                        new_text = replaced
                        fixed += 1
                    continue
                replacement = _best_inflection_match(word, evidence_words)
                if replacement and replacement.lower() != word.lower():
                    replaced = re.sub(rf"\b{re.escape(word)}\b", replacement, new_text, count=1, flags=re.IGNORECASE)
                    if replaced != new_text:
                        new_text = replaced
                        fixed += 1
            return " ".join(new_text.split()), fixed

        def _free_pre_repair_card(target_card: dict, machine_name: str, package: Optional[dict]) -> dict:
            """The deterministic PRE-repair pass: pure string/dict operations,
            no model call, runs before EACH paid repair round below and never
            consumes one of the 2 rounds. Fixes the two failure shapes a
            human coordinator kept hand-fixing this week on the DVsU
            simulator (tasks/evidence/dvsu-research-simulator/STATE.md):
            drifted citation ids/locators (re-anchor by excerpt TEXT) and
            single-word grounding misses in timeframe/visual_identity/why
            (inflection swap or stray-word drop). A card with only these two
            problems can now converge with ZERO model rounds spent."""
            if not isinstance(target_card, dict):
                return target_card
            _reanchor_card_citations_by_text(target_card, package)
            grounding_text = _all_segments_grounding_text(target_card.get("evidence_segments") or [])
            for field, stopwords in (
                ("timeframe", _TIMEFRAME_EXTRA_STOPWORDS),
                ("visual_identity", _VISUAL_IDENTITY_EXTRA_STOPWORDS),
                ("why_this_unit_deserves_a_paragraph", None),
            ):
                field_text = str(target_card.get(field) or "")
                if not field_text.strip():
                    continue
                new_text, fixed = _apply_inflection_grounding_fixes(
                    field_text, grounding_text, machine_name, extra_stopwords=stopwords
                )
                if fixed:
                    target_card[field] = new_text
            return target_card

        def _structured_repair_feedback(
            machine_name: str,
            target_card: dict,
            warnings_list: list[str],
            package: Optional[dict],
        ) -> tuple[list[str], list[str]]:
            """Turn raw referee warning strings into NAMED, per-failure fix
            directives for the repair prompt: which segment, which row to
            re-cite, and the exact contract rules the model must satisfy.
            Reuses the SAME structural analysis the interactive Repair-button
            path already has (_segment_surgery_plan / _promotable_slot_excerpt),
            which the automated per-machine loop below never consulted - this
            is the gap that made a human coordinator spell these fixes out by
            hand this week instead of the pipeline converging on its own.

            Returns (directives, preference_hints). G14, 2026-07-31 (Ryan's
            ruling, decisions.md): the tier floor demoted from hard block to
            advisory, so a required beat resting only on Tier 4/caution
            sources is no longer a rule a paid repair round must chase - it
            is now a PREFERENCE hint (an available upgrade), never a NAMED
            FIX. Only _segment_surgery_plan entries tagged
            reason=="tier4_only" route here; genuine structural fixes
            (slot-hint mismatches, missing required Anton slot coverage,
            invalid kinds, ungrounded/unspecific fields) stay must-fix
            directives - none of those are tier rules."""
            directives: list[str] = []
            preference_hints: list[str] = []
            if not isinstance(target_card, dict):
                return directives, preference_hints
            machine_display = _unit_display_name(machine_name) or machine_name
            display_tokens = machine_display.split()
            last_token = display_tokens[-1] if display_tokens else ""
            first_four_code = _unit_code(machine_display)

            surgery = _segment_surgery_plan(target_card, package, machine_name)
            for rekind in surgery.get("rekinds") or []:
                directives.append(
                    f"segment {rekind.get('evidence_id')}: its cited excerpt is hinted for "
                    f"'{rekind.get('new_kind')}', not '{rekind.get('old_kind')}' - change this segment's kind "
                    f"to '{rekind.get('new_kind')}' (or cite a different excerpt if '{rekind.get('old_kind')}' "
                    "is truly what it supports)."
                )
            for promote in surgery.get("promotes") or []:
                item = promote.get("item") or {}
                text = (
                    f"required beat '{promote.get('kind')}': a stronger evidence segment is available citing "
                    f"excerpt {item.get('excerpt_id')} ({item.get('source_title') or item.get('source_url')}, "
                    f"Tier {_source_tier_number(item)}) - it is hinted for this beat and is not Tier 4/caution."
                    if promote.get("reason") == "tier4_only" else
                    f"required beat '{promote.get('kind')}': add a NEW evidence segment citing excerpt "
                    f"{item.get('excerpt_id')} ({item.get('source_title') or item.get('source_url')}, "
                    f"Tier {_source_tier_number(item)}) - it is hinted for this beat and is not Tier 4/caution."
                )
                (preference_hints if promote.get("reason") == "tier4_only" else directives).append(text)
            for blocked in surgery.get("blocked") or []:
                text = (
                    f"required beat '{blocked.get('role')}' has no promotable Tier 1-3 excerpt in this "
                    "machine's verified package - Tier 4/caution support is acceptable now; no action required."
                    if blocked.get("reason") == "tier4_only" else
                    f"required beat '{blocked.get('role')}' has no promotable Tier 1-3 excerpt in this "
                    "machine's verified package - soften or omit a specific claim for this beat rather than "
                    "inventing one."
                )
                (preference_hints if blocked.get("reason") == "tier4_only" else directives).append(text)
            already_named_slots = {p.get("kind") for p in (surgery.get("promotes") or [])}
            missing_warning = next(
                (w for w in warnings_list if "missing required Anton slots for" in w), ""
            )
            if missing_warning:
                missing_slots = [
                    slot.strip() for slot in missing_warning.split(":", 1)[-1].split(",") if slot.strip()
                ]
                for slot in missing_slots:
                    if slot in already_named_slots:
                        continue
                    row = _promotable_slot_excerpt(package, target_card, slot, machine_name)
                    if row is not None:
                        directives.append(
                            f"missing required beat '{slot}': add a NEW evidence segment citing excerpt "
                            f"{row.get('excerpt_id')} ({row.get('source_title') or row.get('source_url')}, "
                            f"Tier {_source_tier_number(row)})."
                        )
                    else:
                        directives.append(
                            f"missing required beat '{slot}': the package holds no promotable Tier 1-3 "
                            "excerpt for it - reuse the best-fitting excerpt honestly rather than inventing one."
                        )

            for segment in target_card.get("evidence_segments") or []:
                if not isinstance(segment, dict):
                    continue
                kind = str(segment.get("kind") or "").strip().lower()
                if kind and _anton_slot_role_for_kind(kind) is None:
                    directives.append(
                        f"segment {segment.get('evidence_id') or '?'}: kind '{kind}' is not a valid Anton "
                        "slot kind - kind is NEVER the bare word 'context' or 'spec'; use a full kind such as "
                        "'identity_origin_context'/'scale_specs_context' or one of the four required beats."
                    )

            for field, label in (
                ("timeframe", "timeframe"),
                ("visual_identity", "visual_identity"),
                ("why_this_unit_deserves_a_paragraph", "why_this_unit_deserves_a_paragraph"),
            ):
                field_warnings = [w for w in warnings_list if _warning_targets_field(w, label)]
                if not field_warnings:
                    continue
                if any("must be specific to the locked machine" in w for w in field_warnings):
                    directives.append(
                        f"{label} must be specific to '{machine_display}': open the field with the machine's "
                        f"first four tokens ('{first_four_code}' normalized) or include its last word "
                        f"('{last_token}') verbatim."
                    )
                grounding_warning = next(
                    (w for w in field_warnings if "not grounded in evidence segments" in w), ""
                )
                if grounding_warning:
                    flagged = grounding_warning.split(":", 1)[-1].strip()
                    directives.append(
                        f"{label} contains word(s) not grounded in any evidence segment: {flagged}. Every "
                        "factual word must literally appear (or its own inflection, e.g. 'spending' for "
                        "'spent') inside a segment's claim or source_excerpt. Grounding tokenizes on "
                        "apostrophes, so \"Attacker's\" leaves a stray token 's' that fails grounding - write "
                        "\"HMS Attacker in her first mission\", never \"HMS Attacker's first mission\"."
                    )
            return directives, preference_hints

        def _full_research_validation(cards: list[dict]) -> tuple[list[dict], bool]:
            cards_by_roster_code: dict[str, dict] = {}
            for item in cards:
                if not isinstance(item, dict):
                    continue
                raw_unit = item.get("unit") or item.get("machine") or item.get("name") or item.get("designation") or ""
                key = _normalized_unit_code(_unit_display_name(raw_unit) or str(raw_unit))
                if key:
                    cards_by_roster_code[key] = item
            units: list[dict] = []
            for roster_machine in roster:
                code = _normalized_unit_code(roster_machine)
                card = cards_by_roster_code.get(code)
                if card:
                    warnings = _card_warnings(
                        roster_machine,
                        card,
                        _verified_source_package_for_machine(payload, roster_machine),
                        require_source_package=True,
                    )
                else:
                    # G13, 2026-07-31 (bonus fix): a missing card here can
                    # mean "never researched" OR "researched, saved, and the
                    # referee rejected it" - _load_machine_research_cards
                    # drops referee-failed rows from unit_research_cards by
                    # design (many callers need trustworthy-only cards), but
                    # stashes the real verdict so THIS aggregate check can
                    # still name the real rejection reason instead of the
                    # generic missing-card message.
                    dropped = (payload.get("_dropped_failed_research_card_validations") or {}).get(code)
                    warnings = (
                        list(dropped["warnings"])
                        if isinstance(dropped, dict) and dropped.get("warnings")
                        else ["missing saved one-machine research card"]
                    )
                # G14, 2026-07-31: passed reflects BLOCKING warnings only.
                units.append({"machine": roster_machine, "passed": not _blocking_warnings(warnings), "warnings": warnings})
            uniqueness_warnings = _roster_story_uniqueness_warnings(roster, cards_by_roster_code)
            if uniqueness_warnings:
                for unit in units:
                    code = _normalized_unit_code(unit.get("machine") or "")
                    unit_warnings = uniqueness_warnings.get(code) or []
                    if unit_warnings:
                        merged = list(dict.fromkeys((unit.get("warnings") or []) + unit_warnings))
                        unit["warnings"] = merged
                        unit["passed"] = False
            return units, all(unit.get("passed") for unit in units)

        def _merge_target_card_for_review(existing_cards: list[Any], target_card: dict, machine: str) -> list[Any]:
            """Keep unrelated legacy cards unchanged while replacing only the target card."""
            target_key = _normalized_unit_code(machine)
            merged: list[Any] = []
            replaced = False
            for existing in existing_cards:
                if isinstance(existing, dict):
                    raw_unit = existing.get("unit") or existing.get("machine") or existing.get("name") or existing.get("designation") or ""
                    existing_key = _normalized_unit_code(_unit_display_name(raw_unit) or str(raw_unit))
                    if target_key and existing_key == target_key:
                        if not replaced:
                            merged.append(target_card)
                            replaced = True
                        continue
                merged.append(existing)
            if not replaced:
                merged.append(target_card)
            return merged

        def _without_target_card_for_review(existing_cards: list[Any], machine: str) -> list[Any]:
            """Remove the target review card when a refresh produced no valid card."""
            target_key = _normalized_unit_code(machine)
            if not target_key:
                return list(existing_cards)
            kept: list[Any] = []
            for existing in existing_cards:
                if isinstance(existing, dict):
                    raw_unit = existing.get("unit") or existing.get("machine") or existing.get("name") or existing.get("designation") or ""
                    existing_key = _normalized_unit_code(_unit_display_name(raw_unit) or str(raw_unit))
                    if existing_key == target_key:
                        continue
                kept.append(existing)
            return kept

        anthropic_client = getattr(self._pipeline, "anthropic", None)
        if anthropic_client is None:
            msg = "Unit research-hold requires an Anthropic client, but none is configured."
            payload["unit_research_hold_validation"] = {"passed": False, "units": [], "warnings": [msg]}
            await self._log_activity(bot_name, video_id, "failed", msg)
            return payload

        existing_cards_raw = payload.get("unit_research_cards")
        existing_cards = existing_cards_raw if isinstance(existing_cards_raw, list) else []
        cards_by_code: dict[str, dict] = {}
        for card in existing_cards:
            if not isinstance(card, dict):
                continue
            raw_unit = card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or ""
            code = _normalized_unit_code(_unit_display_name(raw_unit) or str(raw_unit))
            if code:
                cards_by_code[code] = card

        if not target_code:
            validation_units, _existing_hold_passed = _full_research_validation(existing_cards)
            invalid_or_missing = [
                str(unit.get("machine") or "")
                for unit in validation_units
                if not unit.get("passed")
            ]
            if invalid_or_missing:
                msg = (
                    "Bulk DVsU machine-card generation is disabled for hallucination safety. "
                    "Run verified one-machine research for a single locked machine first: "
                    + ", ".join(invalid_or_missing[:6])
                )
                payload["unit_research_hold_validation"] = {
                    "passed": False,
                    "in_progress": False,
                    "units": validation_units,
                    "warnings": [msg],
                }
                await self._log_activity(bot_name, video_id, "failed", msg)
                return payload

        if target_code:
            verified_source_package = await self._gather_verified_machine_source_package(
                title, target_machine or "", payload
            )
            payload.setdefault("machine_raw_source_packages", {})[target_code] = verified_source_package
            _clear_machine_preview_artifacts(payload, target_code)
            checkpoint_result = await self._checkpoint_machine_raw_source_package(
                video_id, target_code, verified_source_package, locked_roster_snapshot
            )
            if self._db_write_missed(checkpoint_result):
                conflict = "persisted unit_roster changed concurrently; raw source package checkpoint refused"
                payload["unit_research_hold_validation"] = {
                    "passed": False,
                    "in_progress": False,
                    "target_machine": target_machine,
                    "units": [{"machine": target_machine, "passed": False, "warnings": [conflict]}],
                    "warnings": [conflict],
                }
                await self._log_activity(bot_name, video_id, "failed", conflict)
                return payload
            source_package_errors = (
                _verified_machine_source_package_quality_errors(verified_source_package, target_machine or "")
                + _verified_machine_source_package_identity_errors(verified_source_package, target_machine or "")
            )
            # G14, 2026-07-31 (Ryan's ruling, decisions.md): THE pre-card hard
            # block - "Verified source package needs at least one Tier 1-2
            # primary/authoritative source before Claude can write a card"
            # dropped from HARD BLOCK to advisory. Card writing below now
            # proceeds on an advisory-only gap (e.g. Wikipedia-grade Tier 3-4
            # sources with no Tier 1-2 primary source); only a genuinely
            # blocking error (not ready, missing excerpts, untraceable
            # slots, unsupported capture method, identity mismatch, etc.)
            # still stops the writer here.
            blocking_source_package_errors = _blocking_warnings(source_package_errors)
            if not _verified_machine_source_package_ready(verified_source_package) or blocking_source_package_errors:
                messages = _blocking_warnings([
                    str(item) for item in (verified_source_package.get("errors") or [])
                    if str(item).strip()
                ]) + blocking_source_package_errors
                msg = "; ".join(dict.fromkeys(messages))
                msg = msg or "Verified one-machine internet research did not return enough exact source excerpts."
                payload["unit_research_hold_validation"] = {
                    "passed": False,
                    "in_progress": False,
                    "target_machine": target_machine,
                    "target_machine_passed": False,
                    "units": [{"machine": target_machine, "passed": False, "warnings": [msg]}],
                    "warnings": [msg],
                }
                validation_checkpoint_result = await self._checkpoint_one_machine_research_result(
                    video_id,
                    original_unit_research_cards,
                    payload["unit_research_hold_validation"],
                    locked_roster_snapshot,
                )
                if self._db_write_missed(validation_checkpoint_result):
                    conflict = "persisted unit_roster changed concurrently; source validation checkpoint refused"
                    payload["unit_research_hold_validation"] = {
                        "passed": False,
                        "in_progress": False,
                        "target_machine": target_machine,
                        "target_machine_passed": False,
                        "units": [{"machine": target_machine, "passed": False, "warnings": [conflict]}],
                        "warnings": [conflict],
                    }
                    await self._log_activity(bot_name, video_id, "failed", conflict)
                    return payload
                await self._log_activity(bot_name, video_id, "failed", msg)
                return payload
            legacy_source = _format_verified_machine_source_package(verified_source_package, target_machine or "")
            source_label = "VERIFIED RAW INTERNET EXCERPTS FOR THIS MACHINE"
        else:
            legacy_source = "\n\n".join(
                str(payload.get(k) or "")
                for k in ("fact_sheet", "source_bibliography", "framework_analysis", "historical_parallels", "roster_contract")
                if payload.get(k)
            )[:16000]
            if not legacy_source.strip():
                legacy_source = _payload_blob(payload)[:16000]
            source_label = "VIDEO-LEVEL RESEARCH / SOURCES"
        unit_cards: list[dict] = []
        if target_code:
            for roster_machine in roster:
                code = _normalized_unit_code(roster_machine)
                if not code or code == target_code or code not in cards_by_code:
                    continue
                existing_card = cards_by_code[code]
                existing_warnings = _card_warnings(
                    roster_machine,
                    existing_card,
                    _verified_source_package_for_machine(payload, roster_machine),
                    require_source_package=True,
                )
                if not existing_warnings:
                    unit_cards.append(existing_card)
        validation_units: list[dict] = []
        await self._log_activity(bot_name, video_id, "running", f"Unit research-hold active: enriching {1 if target_code else len(roster)} machine card(s) one at a time")

        for i, machine in enumerate(roster, start=1):
            code = _normalized_unit_code(machine)
            if target_code and code != target_code:
                continue
            if code and code in cards_by_code and not target_code:
                card = cards_by_code[code]
                warnings = _card_warnings(
                    machine,
                    card,
                    _verified_source_package_for_machine(payload, machine),
                    require_source_package=True,
                )
                # G14, 2026-07-31: an advisory-only warning (e.g. tier floor)
                # must not force a perfectly good existing card to regenerate.
                if not _blocking_warnings(warnings):
                    # Referee grades a copy; re-stamp provenance on the card we persist.
                    _stamp_card_segment_provenance(card, _verified_source_package_for_machine(payload, machine))
                    unit_cards.append(card)
                    reused_validation = {"machine": machine, "passed": True, "reused_existing": True, "warnings": []}
                    validation_units.append(reused_validation)
                    # Opportunistically backfill legacy JSONB-only cards.
                    await self._upsert_machine_research_card(video_id, machine, i, card, reused_validation)
                    continue
                # Backfill the stored verdict for a stale/failing existing card
                # before regenerating it. machine_research_cards.validation is what
                # the tabs read; a stale passed=True left here is exactly the XB-15
                # bug. Verdict-only write; the regeneration below overwrites it if
                # the repair succeeds. Same video/tenant guard as every compact write.
                # Intentional last-write-wins: no roster-snapshot guard on this
                # freshness backfill - the newest referee verdict should always win.
                _stamp_card_segment_provenance(card, _verified_source_package_for_machine(payload, machine))
                await self._upsert_machine_research_card(
                    video_id, machine, i, card,
                    {"machine": machine, "passed": False, "revalidated_existing": True, "warnings": warnings},
                )

            machine_scope_line = (
                f"LOCKED SELECTED MACHINE: {machine}\n"
                if target_code else f"LOCKED MACHINE {i} OF {len(roster)}: {machine}\n"
            )
            # Round-8 FIX 1: deterministic conversion-signal scan of the raw
            # package; signals become an explicit must-select prompt line.
            machine_source_package = (
                verified_source_package if target_code
                else _verified_source_package_for_machine(payload, machine)
            )
            conversion_signal_line = _conversion_signal_prompt_line(
                _package_conversion_signals(machine_source_package, machine)
            )
            prompt = (
                "Create ONE Designed vs Used machine research card.\n\n"
                f"VIDEO TITLE: {title}\n"
                f"{machine_scope_line}\n"
                "HARD CONTRACT:\n"
                "- The roster is locked. Do not add, remove, replace, or relitigate machines.\n"
                f"- Research/enrich only THIS machine enough to support one Anton-quality {_ANTON_PARAGRAPH_WORD_RANGE} word DVsU paragraph and its three-view image brief.\n"
                "- Do not use facts, model numbers, predecessor/successor names, competitor names, or comparison claims about any other machine.\n"
                "- If an excerpt mentions a different aircraft or machine designation, ignore that excerpt.\n"
                "- HUNT THE GAP: DVsU runs on built-as-X-actually-used-as-Y. Prioritize evidence for how the machine was ACTUALLY used or ended - combat, service, conversion, redesignation, cancellation, scrapping - not its delivery, acceptance, or first flight. A card whose actual-use story merely restates the design intent fails review.\n"
                f"{conversion_signal_line}"
                "- Only when the hunt genuinely finds no use-story may you set \"deliberately_bare\": true, and then you MUST also return \"gap_hunt_summary\": one or two sentences stating what was searched and why no use-story exists. A bare tag without that summary is rejected.\n"
                "- DVsU is engineering documentary: facts serve the engineering decision, not an encyclopedia/spec dump.\n"
                "- Keep every prose value concise (normally 1-3 sentences) so the complete JSON object fits comfortably.\n"
                "- Return ONLY valid JSON. No markdown.\n\n"
                "Required JSON keys: schema_version (3), unit, include, engineering_thesis, why_this_unit_deserves_a_paragraph, timeframe, timeframe_evidence_ids, visual_identity, visual_identity_evidence_ids, evidence_segments.\n"
                "why_this_unit_deserves_a_paragraph must state the unique engineering idea this locked machine contributes to the video, specific enough that no other roster machine could replace it. Do not say it mattered, was famous, or deserves a paragraph.\n"
                "why_this_unit_deserves_a_paragraph may not introduce dates, numbers, other machine designations, events, or specifications absent from the returned evidence_segments.\n"
                "timeframe is the research-standard date/service-period basis only: state the sourced date range, era, first-flight/service period, or prototype/operational period, and cite it with timeframe_evidence_ids. Do not invent dates.\n"
                "visual_identity is Producer File/image-brief basis only, never spoken narration: state the exact visible machine features that make the locked unit unmistakable, and cite them with visual_identity_evidence_ids.\n"
                "visual_identity may describe only what is visible on the machine; do not include camera movement, animation, transitions, thumbnail copy, on-screen text, captions, or editing directions.\n"
                "timeframe_evidence_ids and visual_identity_evidence_ids must each cite at least one SOURCE_TIER 1-3 excerpt when the package provides one for that fact; Tier 4/caution rows may support but never be the only citation.\n"
                "timeframe and visual_identity are CARD FIELDS cited via the *_evidence_ids arrays. Prefer citing existing narrative-beat segments; when the dated anchor or visible-configuration excerpt fits no narrative beat, you MAY return an optional support segment with kind timeframe or visual_identity to carry it. Support segments never replace or count toward the required four-beat kinds. NEVER create an evidence segment whose kind is spec.\n"
                "timeframe and visual_identity text must each name the locked machine's designation explicitly (for example start with it), and may use only factual words and numbers that appear inside the returned evidence_segments (any segment's claim or source_excerpt, not only the cited ones) - if no evidence segment contains the month name, do not write the month.\n"
                "Optional key: narrative_weight with one of major, standard, or transitional. Use major for pivotal machines that deserve a richer paragraph near 120 words; transitional for prototypes, interim, limited, or minor bridge machines that should stay near 95 words.\n"
                "Do NOT return legacy prose fields, script beats, source_notes, or high-risk-claim summaries; code derives compatibility fields from evidence_segments.\n"
                "CONTENT-SHAPE RULES (review checks these before this card is accepted - satisfy them in this first draft, not after a repair round):\n"
                f"{_why_paragraph_writer_rule_line()}\n"
                f"{_visual_identity_writer_rule_line()}\n"
                "EVIDENCE SEGMENT CONTRACT:\n"
                "- Return 6-9 atomic evidence segments using Anton slot kinds only.\n"
                "- Required four-beat slot kinds at least once: original_problem, engineering_decision, tradeoff, reality.\n"
                "- Use ANTON_SLOT_HINTS as the first-pass map for required slots. Do not relabel an excerpt hinted for one required beat as a different required beat unless the copied source text plainly supports that slot.\n"
                "- The required four-beat slot kinds must use four distinct EXCERPT_ID rows. Do not map original_problem, engineering_decision, tradeoff, and reality to the same broad excerpt.\n"
                "- Script-critical high-risk facts need duplicate support: for exact dates, counts, model numbers, specifications, and superlatives like first/only/largest/most/never, return matching evidence segments from two independent source_url values when the verified excerpt package contains them.\n"
                "- If only one source supports a high-risk exact fact, prefer a qualitative claim from a better-supported slot instead of making that fact central to the card.\n"
                "- original_problem = raw excerpt for the situation, requirement, or need that created the machine.\n"
                "- engineering_decision = raw excerpt for the design/procurement/engineering answer.\n"
                "- tradeoff = raw excerpt for the sacrifice, limitation, compromise, or unintended consequence.\n"
                "- reality = raw excerpt for what happened in testing, production, service, or combat reality.\n"
                "- memorable_fact is REQUIRED: return exactly one memorable_fact segment carrying the most surprising verified excerpt (a fact serious viewers are unlikely to know - a pioneered feature, an odd capability, an unexpected record). Nearly every verified package contains one; the card FAILS review without it. If a strong candidate also fits another slot, cite a different excerpt for that slot and keep the surprise as memorable_fact. Never invent one.\n"
                "- For machines 1-3, prefer one verified human_detail, named decision, or official finding when the excerpt package supports it. Never invent a human account.\n"
                "- A human_detail segment must be attributed to a named person or cite an official finding/decision. Generic pilot, crew, or engineer claims are invalid.\n"
                "- Do not create a pre-written meaning, legacy, or conclusion beat. If an exact excerpt states a concrete downstream consequence, return it as reality, not historical_meaning.\n"
                "- Prefer SOURCE_TIER 1-2 excerpts. SOURCE_TIER 3 is acceptable when it is the best available support. Never use SOURCE_TIER 4/caution as the sole support for a required slot kind.\n"
                "- Add human_detail, role_category, transition_hook, onscreen_label, and optional context slots only when directly supported by exact excerpts.\n"
                "- onscreen_label is metadata for Producer File/on-screen text, never spoken narration; use only sourced full name, concise role, operator or build count, and service/date range.\n"
                "- Each claim must be one concise factual proposition, maximum 35 words. A technical claim may bundle 2-4 related specifications only if the source excerpt contains them together and they serve the engineering_decision beat.\n"
                "- Each segment must contain exactly: evidence_id, kind, claim, source_excerpt, source_excerpt_id, source_url, source_title, locator, numeric_tokens (array), confidence.\n"
                "- One segment = one research slot. Do not write narration or pre-assemble the paragraph.\n"
                "- claim must be a concise restatement of source_excerpt using no factual noun, verb, adjective, or number absent from that excerpt.\n"
                "- numeric_tokens must list every number-like token used by claim, including years, model numbers, counts, speeds, ranges, decades like 1940s, and spelled numbers. Tokens may contain only numbers present in claim or source_excerpt.\n"
                "- source_excerpt must be copied character-for-character from one EXACT_TEXT row in the verified excerpt package. Do not paraphrase, trim together multiple rows, or synthesize a source_excerpt. source_excerpt_id must equal that row's EXCERPT_ID; source_url and locator must match that same row.\n"
                "- Do not use memory, training data, general knowledge, or unsupplied web facts.\n"
                "- Do not manufacture an excerpt, URL, locator, or claim. If the supplied excerpts cannot support a required slot, make that absence explicit in validation rather than guessing.\n"
                "- Be precise or be silent: if the exact excerpts cannot verify a claim to reasonable confidence, soften it or omit it.\n"
                "- If excerpts conflict on a number, date, superlative, or specification, use the more conservative supported wording, hedge it, or leave it out; never pick the higher or more dramatic claim.\n"
                "- Research remains evidence, not prose composition. Do not return script_beats or a paragraph.\n\n"
                f"{source_label}:\n{legacy_source}"
            )
            raw = await anthropic_client.generate(
                prompt=prompt,
                system_prompt="You produce source-grounded JSON research cards for one locked DVsU machine. Output only valid JSON.",
                max_tokens=4200,
                temperature=0.15,
            )
            card: dict = {}
            warnings: list[str] = []
            try:
                text = str(raw or "").strip()
                if text.startswith("```"):
                    import re as _re_uh
                    text = _re_uh.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=_re_uh.I | _re_uh.S).strip()
                card = _hydrate_compatibility_fields(_json_uh.loads(text))
                card = _clamp_card_excerpts_to_verified_sources(card, verified_source_package)
                card = _normalize_card_field_citations(card, machine)
                warnings = _card_warnings(machine, card, verified_source_package if target_code else _verified_source_package_for_machine(payload, machine), require_source_package=True)
            except Exception as e:
                warnings = [f"invalid JSON research card: {str(e)[:120]}"]

            # Up to two repair rounds: interacting contract rules (tier citations,
            # required memorable_fact, field-vs-kind) rarely converge in one shot.
            # G14, 2026-07-31: gate on BLOCKING warnings only - an advisory-only
            # tier gap must never spend a paid repair round chasing a dead rule.
            for _card_repair_round in range(2):
                if not _blocking_warnings(warnings):
                    break
                # FREE pre-repair pass (pure string/dict ops, no model call,
                # never consumes a paid repair round): re-anchor citations
                # whose ids/locators drifted from a package rebuild by
                # matching each segment's own excerpt TEXT against the
                # current package rows, and fix single-word grounding misses
                # by swapping in the evidence's own inflection or dropping a
                # stray filler word. Recompute warnings before spending a
                # model call - a card whose only problems are these two
                # shapes converges here with zero paid rounds.
                _free_pre_repair_card(card, machine, machine_source_package)
                warnings = _card_warnings(
                    machine, card, machine_source_package, require_source_package=True,
                )
                if not _blocking_warnings(warnings):
                    break
                timeframe_hints = _timeframe_repair_hints(card, machine_source_package)
                repair_directives, repair_preference_hints = _structured_repair_feedback(
                    machine, card, warnings, machine_source_package
                )
                repair_prompt = (
                    f"Repair this ONE-machine research card for LOCKED MACHINE: {machine}.\n"
                    f"Warnings: {'; '.join(_blocking_warnings(warnings))}\n"
                    + "".join(f"NAMED FIX - {directive}\n" for directive in repair_directives)
                    + "".join(
                        f"OPTIONAL IMPROVEMENT (not required to pass) - {hint}\n"
                        for hint in repair_preference_hints
                    )
                    + "".join(hint + "\n" for hint in timeframe_hints)
                    + f"{conversion_signal_line}"
                    "Return ONLY valid schema_version 3 JSON with the minimal required keys and evidence_segments array. "
                    "why_this_unit_deserves_a_paragraph must state the unique engineering idea this locked machine contributes to the video, specific enough that no other roster machine could replace it; do not use generic fame/importance wording. "
                    "It may not introduce dates, numbers, other machine designations, events, or specifications absent from the returned evidence_segments. "
                    "Return timeframe plus timeframe_evidence_ids; timeframe is the research-standard date/service-period basis only and must cite exact evidence IDs for the sourced date range, era, first-flight/service period, or prototype/operational period. "
                    "Return visual_identity plus visual_identity_evidence_ids; visual_identity is Producer File/image-brief basis only, never spoken narration. "
                    "It must state exact visible machine features from cited evidence IDs and must not include camera movement, animation, transitions, thumbnail copy, on-screen text, captions, or editing directions. "
                    "timeframe_evidence_ids and visual_identity_evidence_ids must each cite at least one SOURCE_TIER 1-3 excerpt when the package provides one for that fact; Tier 4/caution rows may support but never be the only citation. "
                    "timeframe and visual_identity are CARD FIELDS cited via the *_evidence_ids arrays; prefer citing existing narrative-beat segments, but when the dated anchor or visible-configuration excerpt fits no narrative beat you MAY return an optional support segment with kind timeframe or visual_identity to carry it; support segments never replace or count toward the required four-beat kinds; NEVER create an evidence segment whose kind is spec. "
                    "timeframe and visual_identity text must each name the locked machine's designation explicitly, and may use only factual words and numbers that appear inside the returned evidence_segments (any segment's claim or source_excerpt, not only the cited ones) - if no evidence segment contains the month name, do not write the month. "
                    "If the excerpts clearly support it, include narrative_weight as major, standard, or transitional; use major for pivotal machines and transitional for prototype/interim/limited bridge machines. "
                    "Do not return legacy prose fields, source_notes, high_risk_claims, unrelated visual metadata, or script beats. "
                    "Return 6-9 Anton-slot evidence segments. Required four-beat kinds at least once: original_problem, engineering_decision, tradeoff, reality. "
                    "Use ANTON_SLOT_HINTS as the first-pass map for required slots; do not relabel an excerpt hinted for one required beat as a different required beat unless the copied source text plainly supports that slot. "
                    "The required four-beat kinds must use four distinct EXCERPT_ID rows; do not map multiple required slots to the same broad excerpt. "
                    "Script-critical high-risk facts need duplicate support: for exact dates, counts, model numbers, specifications, and superlatives like first/only/largest/most/never, return matching evidence segments from two independent source_url values when the verified excerpt package contains them. "
                    "If only one source supports a high-risk exact fact, prefer a qualitative claim from a better-supported slot instead of making that fact central to the card. "
                    "Do not use facts, model numbers, predecessor/successor names, competitor names, or comparison claims about any other machine. "
                    "If an excerpt mentions a different aircraft or machine designation, ignore that excerpt. "
                    "HUNT THE GAP: if review says no designed-vs-used gap was found, FIRST attempt the hunt - return reality/service evidence for how the machine was ACTUALLY used or ended (combat, service, conversion, redesignation, cancellation, scrapping); delivery, acceptance, or first-flight logistics merely restate the design intent. Only after that hunt finds nothing may you set \"deliberately_bare\": true together with a required \"gap_hunt_summary\" (what was searched, why no use-story exists) - a bare tag without the summary is rejected. "
                    "original_problem is the source-backed need; engineering_decision is the design/procurement answer; tradeoff is the sacrifice or limitation; reality is what happened in testing, production, service, or combat. "
                    "memorable_fact is REQUIRED: return exactly one memorable_fact segment carrying the most surprising verified excerpt; nearly every package contains one and the card fails review without it. Do not invent trivia. "
                    "For machines 1-3, prefer one verified human_detail, named decision, or official finding when the excerpt package supports it; never invent a human account. "
                    "A human_detail segment must be attributed to a named person or cite an official finding/decision; generic pilot, crew, or engineer claims are invalid. "
                    "Do not create a pre-written meaning, legacy, or conclusion beat. If an exact excerpt states a concrete downstream consequence, return it as reality, not historical_meaning. "
                    "Prefer SOURCE_TIER 1-2 excerpts. SOURCE_TIER 3 is acceptable when it is the best available support. Never use SOURCE_TIER 4/caution as the sole support for a required slot kind. "
                    "Add human_detail, role_category, transition_hook, onscreen_label, and optional context slots only when supported by exact excerpts. "
                    "onscreen_label is metadata for Producer File/on-screen text, never spoken narration; use only sourced full name, concise role, operator or build count, and service/date range. "
                    "Every evidence segment must have evidence_id, kind, one atomic claim, source_excerpt, source_excerpt_id, source_url, source_title, locator, numeric_tokens, and confidence. "
                    "numeric_tokens must include every number-like token used by claim, including years, model numbers, counts, speeds, ranges, decades like 1940s, and spelled numbers. "
                    "Each source_excerpt must be copied character-for-character from one EXACT_TEXT row in the verified source package below; source_excerpt_id must equal that row's EXCERPT_ID; source_url and locator must match the same fetched excerpt row. Do not paraphrase, merge, trim across rows, or synthesize source_excerpt. "
                    "Do not use memory, training data, general knowledge, or unsupplied web facts. "
                    "Be precise or be silent: if the exact excerpts cannot verify a claim to reasonable confidence, soften it or omit it. "
                    "If excerpts conflict on a number, date, superlative, or specification, use the more conservative supported wording, hedge it, or leave it out; never pick the higher or more dramatic claim. "
                    "Do not create script_beats or a paragraph. Keep prose concise and complete the JSON object. Do not reopen the roster.\n\n"
                    f"BAD/RAW CARD:\n{raw}\n\n{source_label}:\n{legacy_source}"
                )
                raw = await anthropic_client.generate(
                    prompt=repair_prompt,
                    system_prompt="You repair one JSON research card. Output only valid JSON.",
                    max_tokens=4200,
                    temperature=0.05,
                )
                try:
                    text = str(raw or "").strip()
                    if text.startswith("```"):
                        import re as _re_uh2
                        text = _re_uh2.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=_re_uh2.I | _re_uh2.S).strip()
                    card = _hydrate_compatibility_fields(_json_uh.loads(text))
                    card = _clamp_card_excerpts_to_verified_sources(card, verified_source_package)
                    card = _normalize_card_field_citations(card, machine)
                    warnings = _card_warnings(machine, card, verified_source_package if target_code else _verified_source_package_for_machine(payload, machine), require_source_package=True)
                except Exception as e:
                    card = {"unit": machine, "validation": {"passed": False}, "raw_output": str(raw or "")[:4000]}
                    warnings = [f"invalid JSON after repair: {str(e)[:120]}"]

            # Canonical identity/index come from the immutable roster, never the
            # model. This does not permit the card pass to alter roster contents.
            if not isinstance(card, dict):
                card = {"unit": machine, "validation": {"passed": False}, "raw_output": str(raw or "")[:4000]}
                warnings = warnings or ["research card was not an object after repair"]
            # Referee grades a copy; re-stamp verified-source provenance on the
            # REAL card so the JSONB checkpoint and compact upsert below persist
            # segments with source_tier/source_id/source_excerpt_hash intact.
            _stamp_card_segment_provenance(
                card,
                verified_source_package if target_code else _verified_source_package_for_machine(payload, machine),
            )
            invalid_placeholder_card = (
                bool(warnings)
                and isinstance(card, dict)
                and bool(card.get("raw_output"))
                and not isinstance(card.get("evidence_segments"), list)
            )
            if invalid_placeholder_card:
                failed_validation = {"machine": machine, "passed": False, "warnings": warnings}
                validation_units.append(failed_validation)
                payload["unit_research_cards"] = (
                    _without_target_card_for_review(original_unit_research_cards, machine)
                    if target_code else
                    unit_cards
                )
                payload["unit_research_hold_validation"] = {
                    "passed": False,
                    "in_progress": False,
                    "units": validation_units,
                }
                if target_code:
                    payload["unit_research_hold_validation"]["target_machine"] = machine
                    payload["unit_research_hold_validation"]["target_machine_passed"] = False
                    checkpoint_result = await self._checkpoint_one_machine_research_result(
                        video_id,
                        payload.get("unit_research_cards") if isinstance(payload.get("unit_research_cards"), list) else [],
                        payload.get("unit_research_hold_validation") if isinstance(payload.get("unit_research_hold_validation"), dict) else {},
                        locked_roster_snapshot,
                    )
                else:
                    checkpoint_result = await execute(
                        """UPDATE videos
                           SET research_payload = $1, updated_at = now()
                           WHERE id = $2 AND tenant_id = $3
                             AND (
                                 research_payload->'unit_roster' IS NULL
                                 OR research_payload->'unit_roster' = $4::jsonb
                             )""",
                        _json_uh.dumps(payload), video_id, self.tenant_id, locked_roster_snapshot,
                    )
                if self._db_write_missed(checkpoint_result):
                    conflict = "persisted unit_roster changed concurrently; stale research checkpoint refused"
                    payload["unit_research_hold_validation"] = {
                        "passed": False,
                        "in_progress": False,
                        "units": [{"machine": machine, "passed": False, "warnings": [conflict]}],
                    }
                    await self._log_activity(bot_name, video_id, "failed", conflict)
                    return payload
                await self._log_activity(bot_name, video_id, "failed", f"Unit research-hold stopped at {machine}: " + "; ".join(warnings))
                return payload
            card["unit"] = machine
            card["include"] = True
            card["locked_roster_index"] = i
            if target_code:
                card["source_package_key"] = target_code
            unit_cards.append(card)
            # G14, 2026-07-31: passed is computed from BLOCKING warnings only -
            # an advisory-only tier note must not fail a correctly-grounded card.
            # The full `warnings` list (advisory included) is still stored/shown.
            blocking_warnings = _blocking_warnings(warnings)
            validation_units.append({"machine": machine, "passed": not blocking_warnings, "warnings": warnings})

            if _json_uh.dumps(payload.get("unit_roster"), sort_keys=True, ensure_ascii=False) != locked_roster_snapshot:
                warnings = ["locked unit_roster changed during per-machine research"]
                blocking_warnings = warnings
                validation_units[-1] = {"machine": machine, "passed": False, "warnings": warnings}

            # Durable checkpoint after each machine. A crash or later-machine
            # failure cannot discard research cards already completed.
            roster_order = {_normalized_unit_code(item): index for index, item in enumerate(roster)}
            unit_cards.sort(key=lambda item: roster_order.get(_normalized_unit_code(_unit_display_name(item)), len(roster)))
            payload["unit_research_cards"] = (
                _merge_target_card_for_review(original_unit_research_cards, card, machine)
                if target_code else
                unit_cards
            )
            target_machine_passed = not blocking_warnings
            full_validation_units, full_hold_passed = (
                _full_research_validation(unit_cards)
                if target_code else
                (validation_units, not blocking_warnings and i == len(roster))
            )
            if target_code:
                target_machine_passed = next(
                    (
                        bool(unit.get("passed"))
                        for unit in full_validation_units
                        if _normalized_unit_code(unit.get("machine") or "") == code
                    ),
                    target_machine_passed,
                )
            payload["unit_research_hold_validation"] = {
                "passed": full_hold_passed,
                "in_progress": False if target_code else not blocking_warnings and i < len(roster),
                "units": full_validation_units,
            }
            if target_code:
                payload["unit_research_hold_validation"]["target_machine"] = machine
                payload["unit_research_hold_validation"]["target_machine_passed"] = target_machine_passed
            if target_code:
                checkpoint_result = await self._checkpoint_one_machine_research_result(
                    video_id,
                    payload.get("unit_research_cards") if isinstance(payload.get("unit_research_cards"), list) else [],
                    payload.get("unit_research_hold_validation") if isinstance(payload.get("unit_research_hold_validation"), dict) else {},
                    locked_roster_snapshot,
                )
            else:
                checkpoint_result = await execute(
                    """UPDATE videos
                       SET research_payload = $1, updated_at = now()
                       WHERE id = $2 AND tenant_id = $3
                         AND (
                             research_payload->'unit_roster' IS NULL
                             OR research_payload->'unit_roster' = $4::jsonb
                         )""",
                    _json_uh.dumps(payload), video_id, self.tenant_id, locked_roster_snapshot,
                )
            if self._db_write_missed(checkpoint_result):
                conflict = "persisted unit_roster changed concurrently; stale research checkpoint refused"
                validation_units[-1] = {"machine": machine, "passed": False, "warnings": [conflict]}
                payload["unit_research_hold_validation"] = {
                    "passed": False,
                    "in_progress": False,
                    "units": validation_units,
                }
                await self._log_activity(bot_name, video_id, "failed", conflict)
                return payload
            await self._upsert_machine_research_card(video_id, machine, i, card, validation_units[-1])
            if warnings:
                await self._log_activity(bot_name, video_id, "failed", f"Unit research-hold stopped at {machine}: " + "; ".join(warnings))
                return payload

        target_machine_passed = bool(validation_units and validation_units[-1].get("passed"))
        full_validation_units, full_hold_passed = _full_research_validation(unit_cards)
        if target_code and validation_units:
            target_code_final = _normalized_unit_code(validation_units[-1].get("machine") or "")
            target_machine_passed = next(
                (
                    bool(unit.get("passed"))
                    for unit in full_validation_units
                    if _normalized_unit_code(unit.get("machine") or "") == target_code_final
                ),
                target_machine_passed,
            )
        payload["unit_research_hold_validation"] = {
            "passed": full_hold_passed,
            "in_progress": False,
            "units": full_validation_units,
        }
        if target_code and validation_units:
            payload["unit_research_hold_validation"]["target_machine"] = validation_units[-1].get("machine")
            payload["unit_research_hold_validation"]["target_machine_passed"] = target_machine_passed
        await self._log_activity(bot_name, video_id, "running", f"Unit research-hold complete: {len(unit_cards)} machine card(s)")
        return payload

    async def _resplit_static_scenes(self, video_id: str) -> None:
        """Static documentaries: one scene per UNIT PARAGRAPH, not per act.

        The script bot writes one scripts row per ACT (pipeline_control), which
        for a static docu collapses a 24-30 machine video into ~6 scenes = ~6
        held image set (seen live on DVsU 2026-07-07). The channel format is one
        machine / one paragraph / one caption / two-to-three views, so re-split the
        narration into paragraph scenes. Also strips non-spoken junk (act
        markers, markdown headings, dividers, meta notes) so nothing that is
        not narration can reach TTS. Fail-open: a resplit error keeps the
        act-level rows rather than blocking the stage."""
        try:
            video = await self._get_video(video_id)
            script = (video or {}).get("script") or ""
            if not script.strip():
                return
            units: list[str] = []
            for para in script.split("\n\n"):
                p = para.strip()
                if not p or p.startswith("[ACT") or p.startswith("@@@"):
                    continue
                if p.startswith("#") or p.startswith("---") or p.lower().startswith("**angle"):
                    continue
                # Drop leftover markdown emphasis wrappers on meta lines
                if len(p.split()) < 25:
                    continue  # fragments / stray connectors are not units
                units.append(p)
            if len(units) < 8:
                _logger.warning("[static-resplit] %s: only %d unit paragraphs — keeping act scenes",
                                video_id, len(units))
                return
            rows = await fetch_all(
                "SELECT voice_id FROM scripts WHERE video_id = $1 AND tenant_id = $2 LIMIT 1",
                video_id, self.tenant_id)
            voice_id = (rows[0].get("voice_id") if rows else None) or "1SM7GgM6IMuvQlz2BwM3"
            await execute("DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2",
                          video_id, self.tenant_id)
            for i, text in enumerate(units, start=1):
                await execute(
                    """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
                       VALUES ($1, $2, $3, $4, $5, 'Create', $6)""",
                    self.tenant_id, video_id, i, text,
                    video.get("video_title"), voice_id,
                )
            await self._log_activity("Script Bot", video_id, "completed",
                                     f"Static format: split into {len(units)} unit scenes (one machine per scene)")
            _logger.info("[static-resplit] %s: %d unit scenes", video_id, len(units))
        except Exception as e:  # noqa: BLE001 — never block the stage
            _logger.warning("[static-resplit] failed for %s: %s", video_id, str(e)[:200])

    async def _validate_static_script_roster(self, video_id: str) -> dict:
        """Hard gate: static complete-roster videos must script every locked unit."""
        import json as _json_vr
        video = await self._get_video(video_id)
        rp = (video or {}).get("research_payload") or {}
        if isinstance(rp, str):
            try:
                rp = _json_vr.loads(rp)
            except Exception:
                rp = {}
        rows = await fetch_all(
            "SELECT scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
            video_id, self.tenant_id,
        )
        units = [r.get("scene_text") or "" for r in (rows or [])]
        check = _roster_validation(
            (video or {}).get("video_title") or "",
            rp if isinstance(rp, dict) else {},
            units,
            video_length_minutes=(video or {}).get("video_length_minutes"),
        )
        existing = (video or {}).get("script_validation")
        try:
            validation = _json_vr.loads(existing) if isinstance(existing, str) and existing.strip() else (existing or {})
        except Exception:
            validation = {}
        if not isinstance(validation, dict):
            validation = {}
        validation["unit_roster"] = check
        await execute(
            "UPDATE videos SET script_validation = $1 WHERE id = $2 AND tenant_id = $3",
            _json_vr.dumps(validation), video_id, self.tenant_id,
        )
        if not check.get("passed"):
            await self._log_activity(
                "Script Bot", video_id, "failed",
                "Script roster gate failed: " + "; ".join(check.get("warnings", []))[:800],
            )
        return check

    @staticmethod
    def _clean_static_unit_paragraph(text: str) -> str:
        """Normalize a one-machine script-hold response into spoken narration."""
        import re

        paragraph = str(text or "").strip()
        paragraph = re.sub(r"^```[a-zA-Z]*\s*", "", paragraph).strip()
        paragraph = re.sub(r"\s*```$", "", paragraph).strip()
        paragraph = re.sub(r"^(?:scene|paragraph|machine)\s*\d*\s*[:\-]\s*", "", paragraph, flags=re.I).strip()
        paragraph = re.sub(r"^#+\s*.+\n+", "", paragraph).strip()
        # Preserve paragraph boundaries until deterministic validation runs.
        return paragraph.strip()

    @staticmethod
    def _validate_static_unit_paragraph(
        machine: str, paragraph: str, rule_overrides: Optional[dict] = None,
    ) -> list[str]:
        """Deterministic per-machine gate for static-docu script-hold output.

        ``rule_overrides`` (checklist C46c, ``quality_rules.resolve_dvsu_
        overrides``): when the tenant has seeded QL-1 (word floor) and/or
        QL-12 (banned hype words) rows, the TABLE VALUE wins for that check;
        absent/unparseable keys fall back to today's hardcoded constants
        byte-identically. None (the default) is exactly pre-C46c behavior."""
        import re

        rule_overrides = rule_overrides or {}
        warnings: list[str] = []
        text = str(paragraph or "").strip()
        wc = _spoken_word_count(text)
        machine_code = _normalized_unit_code(machine)
        if not text:
            warnings.append("empty paragraph")
        if "\n" in text:
            warnings.append("must be exactly one paragraph")
        # QD-6/QL-1 (approved): universal hard floor 80 and ceiling 170; 80-95
        # is an advisory warn band ("confirm terse on purpose"); the register
        # band itself is guidance handled by the narrative-weight advisory.
        # Code is authoritative; model self-counts are ignored.
        word_floor = rule_overrides.get("word_floor") or {}
        hard_min = int(word_floor.get("hard_min") or _ANTON_PARAGRAPH_HARD_MIN_WORDS)
        warn_top = int(word_floor.get("warn_top") or _ANTON_PARAGRAPH_MIN_WORDS)
        hard_max = int(word_floor.get("hard_max") or _ANTON_PARAGRAPH_HARD_MAX_WORDS)
        # D2/QL-12 pattern: a non-hard_gate severity on the seeded row demotes
        # a floor/ceiling miss to advisory rather than blocking.
        floor_blocking = word_floor.get("severity", "hard_gate") == "hard_gate"
        floor_prefix = "" if floor_blocking else _ADVISORY_PREFIX
        if text and wc < hard_min:
            warnings.append(
                floor_prefix + f"word count {wc} under the {hard_min}-word hard floor - thicken or fold the entry"
            )
        elif wc > hard_max:
            warnings.append(
                floor_prefix + f"word count {wc} over the {hard_max}-word hard ceiling - split or cut the entry"
            )
        elif text and wc < warn_top:
            warnings.append(
                _ADVISORY_PREFIX + f"word count {wc} in the {hard_min}-{warn_top} "
                "warn band - confirm the entry is terse on purpose"
            )
        normalized_text = re.sub(r"[^A-Z0-9]", "", text.upper())
        if machine_code and machine_code not in normalized_text:
            warnings.append(f"missing locked machine designation {machine_code}")
        lower = text.lower()
        meta_patterns = (
            r"\bas an ai\b", r"\bi can't\b", r"\bcannot verify\b",
            r"\bhere is\b", r"\bmarkdown\b",
        )
        if any(re.search(pattern, lower) for pattern in meta_patterns):
            warnings.append("contains meta/commentary instead of narration")
        production_patterns = (
            r"^\s*(?:act|unit)\s+(?:[ivx]+|\d+)\b",
            r"\b(?:b-roll|visual cue|image prompt|thumbnail|graphics list|producer file|on-screen text|onscreen text)\b",
        )
        if any(re.search(pattern, lower) for pattern in production_patterns):
            warnings.append("contains production cue/label instead of clean voiceover narration")
        if re.search(r"\[[^\]]+\]", text):
            warnings.append("contains bracketed production note instead of clean voiceover narration")
        raw_digit_mentions = _raw_digit_mentions_for_voiceover(text)
        if raw_digit_mentions:
            # QL-10 (OR-4): number rendering is warn-severity.
            warnings.append(
                _ADVISORY_PREFIX + "uses raw numeric digit(s); write spoken numbers as words: "
                + ", ".join(raw_digit_mentions)
            )
        unit_abbreviations = _written_unit_abbreviations_for_voiceover(text)
        if unit_abbreviations:
            # QL-10 (OR-4): number/unit rendering is warn-severity.
            warnings.append(
                _ADVISORY_PREFIX + "uses written unit abbreviation(s); spell out for voiceover: "
                + ", ".join(
                    f"{abbr} -> {_VOICEOVER_UNIT_ABBREVIATIONS.get(abbr, 'spoken words')}"
                    for abbr in unit_abbreviations
                )
            )
        # QL-12 (checklist C46c): a seeded row's parsed banned-adjective list
        # is UNIONED with this baseline (never replaces it - additivity is
        # sacred; the law's list and this ad hoc superlative-phrase list
        # catch different things). Severity on the seeded row governs the
        # whole check once present; absent = today's hard/blocking behavior.
        banned_hype = rule_overrides.get("banned_hype_words") or {}
        hype_terms = _ANTON_HYPE_PHRASES + tuple(banned_hype.get("words") or ())
        hype_blocking = banned_hype.get("severity", "hard_gate") == "hard_gate"
        if any(term in lower for term in hype_terms):
            warnings.append(
                ("" if hype_blocking else _ADVISORY_PREFIX) + "contains forbidden Anton/DVsU hype language"
            )
        list_transition_patterns = (
            r"\bmoving\s+(?:on|down)\s+(?:to|the list)\b",
            r"\bnext\s+(?:is|was|came|comes)\b",
            r"\banother\s+(?:aircraft|bomber|machine|unit|example)\s+was\b",
            r"\bat\s+number\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b",
            r"\bcoming\s+in\s+at\s+number\b",
            r"\bon\s+this\s+list\b",
            r"\bthe\s+next\s+(?:aircraft|bomber|machine|unit)\b",
        )
        if any(re.search(pattern, lower) for pattern in list_transition_patterns):
            warnings.append("contains forbidden Anton/DVsU ranked-list connector language")
        sentence_parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        first_sentence = sentence_parts[0] if sentence_parts else ""
        if re.search(
            r"^\s*(?:the\s+)?[A-Z0-9][A-Za-z0-9 .'\-]{0,90}\s+was\s+(?:a|an)\s+"
            r"[A-Za-z0-9 .'\-]{0,90}\b(?:developed|manufactured|built|powered|carried|entered service)\b",
            first_sentence,
            flags=re.IGNORECASE,
        ):
            warnings.append("opens with a Wikipedia-style existence sentence instead of significance")
        list_starts = [
            part for part in sentence_parts
            if re.match(r"^(?:it|the aircraft|the machine)\s+(?:also\s+)?(?:had|featured|carried|mounted|used)\b", part, flags=re.IGNORECASE)
        ]
        if len(list_starts) >= 2:
            warnings.append("contains list/spec-dump sentence pattern instead of an engineering argument")
        timeline_starts = [
            part for part in sentence_parts
            if (
                re.match(
                    r"^(?:the\s+)?[A-Z0-9][A-Za-z0-9 .'\-]{0,90}\s+"
                    r"(?:first\s+flew|entered\s+service|was\s+(?:designed|developed|modified|retired|built|produced)|"
                    r"served\s+(?:in|during|until)|transferred\s+to)\b",
                    part,
                    flags=re.IGNORECASE,
                )
                or re.match(r"^(?:in|by|between|from)\s+(?:18|19|20)\d{2}\b", part, flags=re.IGNORECASE)
            )
        ]
        if len(timeline_starts) >= 3:
            warnings.append("contains timeline/chronology structure instead of an engineering argument")
        written_connector_starts = [
            part for part in sentence_parts
            if re.match(r"^(?:however|nevertheless|furthermore|moreover|additionally|in addition)\b", part, flags=re.IGNORECASE)
        ]
        if written_connector_starts:
            warnings.append("contains written-language connector sentence start instead of spoken documentary flow")
        long_run = 0
        for part in sentence_parts:
            if _spoken_word_count(part) > 28:
                long_run += 1
                if long_run >= 3:
                    warnings.append("contains three consecutive long sentences instead of varied voiceover rhythm")
                    break
            else:
                long_run = 0
        if sentence_parts:
            last_sentence = sentence_parts[-1].lower()
            if re.search(r"\b(?:retired|retirement|decommissioned)\b", last_sentence) and re.search(r"\b(?:18|19|20)\d{2}\b|\b\d+\s+years?\b", last_sentence):
                warnings.append("final sentence ends on a retirement/date fact instead of a landed Anton line")
        return warnings

    async def _load_dvsu_rule_overrides(self, video: dict) -> dict:
        """Checklist C46c: fetch this tenant's ACTIVE ``quality_rules`` rows,
        scope-match them against THIS video's own shape data (deterministic,
        never LLM judgment - the same ``quality_rules.active_rules_for_video``
        C46b's script critic already uses), and resolve the DvsU delta
        overrides (``quality_rules.resolve_dvsu_overrides``) that the
        static-docu script-hold's deterministic gates read before falling
        back to their own hardcoded constants.

        Fails OPEN: any error (no table yet, bad JSON, etc.) returns ``{}``,
        which is exactly today's pre-C46c hardcoded behavior for every
        non-seeded tenant and for DvsU itself before the seed script runs.

        Checklist C46e (OR-5 ruled): also resolves this video's ``dvsu_mode``
        opt-in value (``_dvsu_mode_value_for_video``) and passes it through
        as the scope-match's ``dvsu_mode_value`` — a seeded QL-7-MH/QL-9-MH
        row (``applies_to={"dvsu_mode": "most_hated"}``) only ever matches
        when this video's own research_payload explicitly opted into that
        mode, never inferred from the title."""
        try:
            import quality_rules

            rule_rows = await fetch_all(
                "SELECT rule_id, law, evidence, severity, applies_to "
                "FROM quality_rules WHERE tenant_id = $1 AND active",
                self.tenant_id,
            )
            matched = quality_rules.active_rules_for_video(
                video, rule_rows or [], dvsu_mode_value=_dvsu_mode_value_for_video(video),
            )
            return quality_rules.resolve_dvsu_overrides(matched)
        except Exception:
            return {}

    async def _run_static_script_hold(
        self,
        video_id: str,
        video: dict,
        roster: list[str],
        target_machine: Optional[str] = None,
        save_target_script: bool = False,
    ) -> dict:
        """DVsU/static-docu script path: one locked machine paragraph at a time.

        Scoped by the caller to videos.render_mode == 'static_docu'. Normal
        StoryEngine videos keep the existing full-script brief-translator flow.
        """
        import json as _json_sh

        bot_name = "Script Bot"
        title = video.get("video_title") or video.get("headline") or ""
        if target_machine:
            matched_target = _locked_roster_item_for_machine(roster, target_machine)
            if not matched_target:
                return {"status": "failed", "error": f"Machine is not in the locked roster: {target_machine}"}
            target_machine = matched_target
        rp = video.get("research_payload") or {}
        if isinstance(rp, str):
            try:
                rp = _json_sh.loads(rp)
            except Exception:
                rp = {}
        if not isinstance(rp, dict):
            rp = {}
        rp = await self._load_machine_research_cards(
            video_id, rp, roster, target_machine=target_machine if target_machine else None
        )
        response_research_payload = await enrich_research_payload_readiness(
            self.tenant_id, video_id, dict(rp)
        )

        # Writer pass 5 wrap-up: ONE shared checklist. Before a single-machine
        # preview, promote (FREE, deterministic) the package excerpts the
        # frozen script audit will demand, so a research-verified card can
        # never starve the writer again (the seam that cost three hand-promote
        # rounds on 2026-07-16).
        if target_machine:
            heal_card = _research_card_for_machine(rp, target_machine)
            heal_package = _verified_source_package_for_machine(rp, target_machine)
            heal_actions = _script_starvation_promote_actions(heal_card, heal_package, target_machine)
            healed: list[str] = []
            for heal_action in heal_actions:
                heal_result = await self.repair_promote_excerpt(
                    video_id, target_machine, heal_action["excerpt_id"], heal_action["kind"]
                )
                if isinstance(heal_result, dict) and heal_result.get("status") == "completed":
                    healed.append(f"{heal_action['excerpt_id']} -> {heal_action['kind']}")
            if healed:
                await self._log_activity(
                    bot_name, video_id, "processing",
                    f"self-healed script starvation for {target_machine}: promoted " + ", ".join(healed),
                )
                video = await self._get_video(video_id) or video
                rp = video.get("research_payload") or {}
                if isinstance(rp, str):
                    try:
                        rp = _json_sh.loads(rp)
                    except Exception:
                        rp = {}
                if not isinstance(rp, dict):
                    rp = {}
                rp = await self._load_machine_research_cards(
                    video_id, rp, roster, target_machine=target_machine
                )
                response_research_payload = await enrich_research_payload_readiness(
                    self.tenant_id, video_id, dict(rp)
                )

        def _mirror_response_artifact(container: str, key: str, value: dict) -> None:
            existing = response_research_payload.get(container)
            if isinstance(existing, str):
                try:
                    existing = _json_sh.loads(existing)
                except Exception:
                    existing = {}
            if not isinstance(existing, dict):
                existing = {}
            response_research_payload[container] = {**existing, key: value}

        locked_roster_snapshot = _json_sh.dumps(rp.get("unit_roster"), sort_keys=True, ensure_ascii=False)
        if target_machine:
            target_key = _normalized_unit_code(target_machine)
            rp = dict(rp)
            rp["unit_research_cards"] = [
                card for card in (rp.get("unit_research_cards") or [])
                if isinstance(card, dict)
                and _normalized_unit_code(_unit_display_name(
                    card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or ""
                )) == target_key
            ]
        video_thesis = (
            rp.get("thesis")
            or rp.get("narrative_arc_suggestion")
            or rp.get("narrative_arc")
            or "Trace how each locked machine changed the engineering answer to the title's central problem."
        )
        if isinstance(video_thesis, (dict, list)):
            video_thesis = _json_sh.dumps(video_thesis, ensure_ascii=False)

        await self._log_activity(
            bot_name, video_id, "started",
            f"Script-hold active: generating {len(roster)} static-docu machine paragraph(s) one at a time",
        )

        # The machine writer is not allowed to fall back to the global fact
        # sheet. Research and script are separate artifacts, and every locked
        # machine must have its own persisted card before any script rows change.
        selected_units = (
            [(roster.index(target_machine) + 1, target_machine)]
            if target_machine else list(enumerate(roster, start=1))
        )

        async def _return_saved_failed_preview(
            machine: str,
            scene: int,
            msg: str,
            *,
            check_name: str = "evidence_gate",
            check_label: str = "Evidence gate",
            research_source: str = "preview_error",
            story_plan: Optional[dict] = None,
        ) -> dict:
            machine_key = _verified_source_cache_key(machine)
            preview = {
                "machine": machine,
                "scene": scene,
                "paragraph": "",
                "word_count": 0,
                "passed": False,
                "warnings": [msg],
                "onscreen_label": "",
                "research_source": research_source,
                "story_plan": story_plan,
                "claim_bundle": {
                    "editorial_thesis": "",
                    "formula_sentences": [],
                    "claim_map": [],
                },
                "quality_audit": {
                    "passed": False,
                    "summary": msg,
                    "checks": [
                        {
                            "name": check_name,
                            "label": check_label,
                            "passed": False,
                            "detail": msg,
                        }
                    ],
                },
            }
            preview_save_result = await self._checkpoint_machine_script_preview(
                video_id, machine_key, preview, locked_roster_snapshot,
            )
            if self._db_write_missed(preview_save_result):
                save_msg = "persisted unit_roster changed concurrently; script preview save refused"
                await self._log_activity(bot_name, video_id, "failed", save_msg)
                return {"status": "failed", "error": save_msg, "video_id": video_id}
            _mirror_response_artifact("machine_script_previews", machine_key, preview)
            await self._log_activity(
                bot_name,
                video_id,
                "failed",
                f"Single-machine script preview needs review: {machine}",
            )
            return {
                "status": "completed",
                "video_id": video_id,
                "preview": preview,
                "research_payload": response_research_payload,
            }

        missing_cards = [machine for _, machine in selected_units if _research_card_for_machine(rp, machine) is None]
        if missing_cards:
            msg = "Script-hold requires a saved research card for every locked machine; missing: " + ", ".join(missing_cards)
            await self._log_activity(bot_name, video_id, "failed", msg[:900])
            if target_machine and selected_units:
                return await _return_saved_failed_preview(
                    selected_units[0][1],
                    selected_units[0][0],
                    msg,
                    check_name="research_card",
                    check_label="Research card",
                )
            return {"status": "failed", "error": msg, "video_id": video_id}
        source_gate_failures: list[str] = []
        for _, machine in selected_units:
            selected_card = _research_card_for_machine(rp, machine) or {}
            source_package = _verified_source_package_for_machine(rp, machine)
            source_errors = _research_card_contract_warnings(
                machine,
                selected_card,
                source_package,
                require_source_package=True,
            )
            if source_errors:
                source_gate_failures.append(f"{machine}: " + "; ".join(source_errors))
        if source_gate_failures:
            prefix = "Script preview evidence gate failed" if target_machine else "Script-hold evidence gate failed"
            msg = prefix + ": " + " | ".join(source_gate_failures)
            await self._log_activity(bot_name, video_id, "failed", msg[:900])
            if target_machine and selected_units:
                return await _return_saved_failed_preview(selected_units[0][1], selected_units[0][0], msg)
            return {"status": "failed", "error": msg, "video_id": video_id}

        anthropic_client = getattr(self._pipeline, "anthropic", None)
        if anthropic_client is None:
            msg = "Script-hold requires an Anthropic client, but none is configured."
            await self._log_activity(bot_name, video_id, "failed", msg)
            return {"status": "failed", "error": msg, "video_id": video_id}
        # Unit-by-unit generation must inherit the same resolved per-video/tenant
        # script contract as the global writer. For DVsU this is Anton's full
        # saved channel prompt, not a generic military-history instruction.
        script_system_prompt = getattr(self._pipeline, "script_system_prompt", None) or (
            "You write precise military-history documentary voiceover. Output only the requested spoken paragraph."
        )

        rows = await fetch_all(
            "SELECT voice_id FROM scripts WHERE video_id = $1 AND tenant_id = $2 LIMIT 1",
            video_id, self.tenant_id,
        )
        voice_id = (rows[0].get("voice_id") if rows else None) or "1SM7GgM6IMuvQlz2BwM3"

        # Checklist C46c: resolved ONCE per script-hold run (not per machine)
        # and threaded into every validator call below.
        dvsu_rule_overrides = await self._load_dvsu_rule_overrides(video)

        # Stage every replacement paragraph in memory. Existing script rows remain
        # untouched unless the complete roster validates successfully.
        paragraphs: list[str] = []
        validation_units: list[dict] = []
        for i, machine in selected_units:
            prev_machine = roster[i - 2] if i > 1 else "None"
            next_machine = roster[i] if i < len(roster) else "None"
            machine_scope_line = (
                f"LOCKED SELECTED MACHINE: {machine}\n"
                if target_machine else f"LOCKED MACHINE {i} OF {len(roster)}: {machine}\n"
            )
            neighbor_context = "" if target_machine else (
                f"PREVIOUS MACHINE: {prev_machine}\n"
                f"NEXT MACHINE: {next_machine}\n"
            )
            research_source, research_source_kind = _research_source_for_machine(rp, machine)
            # Anton allows only 4-5 name-openers across a full video. Assign them
            # deterministically so independent calls cannot all default to the
            # easiest Wikipedia-style opening.
            name_opener_slots = {1, 6, 11, 16, 21}
            if i in name_opener_slots:
                opening_brief = "A machine-name opening is allowed here, but only if it immediately states why the machine mattered."
            else:
                opening_modes = (
                    "a problem or operational need",
                    "a paradox or contradiction",
                    "a consequence or institutional decision",
                    "a date/event or sourced human detail",
                    "a documented use or outcome",
                )
                opening_brief = f"Do NOT open with the machine name. Open with {opening_modes[(i - 1) % len(opening_modes)]}."
            complete_inventory_mode = _anton_inventory_title_mode(title)
            precomputed_story_plan = None
            narrative_weight = {
                "label": "standard",
                "target_words": _ANTON_PARAGRAPH_TARGET_WORDS,
                "guidance": "balanced paragraph",
            }
            if complete_inventory_mode:
                precomputed_story_plan = dict(_machine_story_plan(rp, machine, dvsu_rule_overrides))
                narrative_weight = dict(
                    ((precomputed_story_plan.get("contract") or {}).get("narrative_weight") or narrative_weight)
                )
                narrative_target_words = str(narrative_weight.get("target_words") or _ANTON_PARAGRAPH_TARGET_WORDS)
                narrative_guidance = str(narrative_weight.get("guidance") or "").strip()
                story_brief = _inventory_story_brief(rp, machine)
                research_source = _json_sh.dumps(story_brief, ensure_ascii=False, indent=2)
                research_source_kind = "compact_editorial_brief"
                structure_brief = (
                    "FORMAT MODE: COMPLETE INVENTORY MICRO-STORY. The roster fulfills the title; this paragraph only has to make this machine memorable.\n"
                    f"- NARRATIVE WEIGHT: {narrative_weight.get('label')}; target {narrative_target_words} words inside the absolute {_ANTON_PARAGRAPH_WORD_RANGE} validator. {narrative_guidance}\n"
                    "- Before writing, silently rank the Anton slots. Keep the details needed to explain: original problem, engineering decision, tradeoff, and reality. Omit everything else.\n"
                    f"- Use exactly {_ANTON_PARAGRAPH_FORMULA_SENTENCES} sentences: original_problem, engineering_decision, tradeoff, reality, then a paragraph-derived conclusion. Each sentence should do one clear job, not carry a list.\n"
                    "- Sentence 1 should create the tension: requirement, ambition, contradiction, consequence, or why this machine enters the argument. Do not merely define the machine.\n"
                    "- Sentence 2 should turn the engineering decision into selected capability or scale facts that prove the decision.\n"
                    "- Sentence 3 should pivot into the cost, limit, sacrifice, or expectation-versus-reality contrast created by that decision.\n"
                    "- Sentence 4 should show what happened in production, testing, service, combat, or documented reality.\n"
                    "- Sentence 5 should land as a short verdict, paradox, irony, or reversal from the first four sentences only.\n"
                    "- Use only sourced numerical details. A number earns its place only when it makes the machine's scale, count, service period, service consequence, or final contrast understandable. A sourced spec or production number that is single-sourced is kept as a hedged round (about/nearly/over/roughly), never dropped.\n"
                    "- Build a small narrative around one tension, decision, or consequence. Give the machine a natural Anton micro-hook, not a manufactured twist.\n"
                    "- Do not inventory every dimension, engine, payload, speed, range, date, crew feature, and legacy field. Select the 2-4 technical facts that prove the decision, tradeoff, or reality.\n"
                    "- For the Strategic Bomber benchmark, preserve Anton's compact inventory cadence: identity/significance, selected scale or capability facts, production or service reality, then a landed verdict. Do not strip useful specs until the paragraph becomes a pure thesis essay.\n"
                    "- Use sourced memorable_fact when the plan provides it, folded into one of the four evidence-backed sentences. Do not add a separate trivia sentence.\n"
                    "- Prefer clean spoken history over technical completeness, but the paragraph still needs a concrete engineering thesis and a final line that lands.\n"
                )
            else:
                structure_brief = (
                    "FORMAT MODE: ENGINEERING ARGUMENT.\n"
                    "- Anton/DVsU movement: establish the engineering problem or decision, show the response and meaningful trade-off, then reveal the real outcome. Do not write a chronological biography.\n"
                    "- Use one surprising supported fact as evidence for the engineering idea, never as an orphan spec.\n"
                    "- End with a short verdict, paradox, irony, or reversal that lands. Never end on a retirement date or generic summary.\n"
                )
            inventory_system_override = ""
            if complete_inventory_mode:
                inventory_system_override = (
                    "\n\nSCOPED OVERRIDE — COMPLETE INVENTORY MODE:\n"
                    "For titles promising Every, All, or a complete history, this block replaces conflicting paragraph rules above. "
                    "Write a short Anton micro-story, not a compressed fact sheet and not a miniature engineering essay. "
                    "For the Strategic Bomber benchmark, keep Anton's compact inventory cadence: selected scale/spec facts, production or service reality, and a landed verdict, all from locked evidence. "
                    "Silently cherry-pick only the details needed for one clear narrative: problem, decision, tradeoff, reality, and a paragraph-derived landing line. Omission is a feature. "
                    f"Use the NARRATIVE WEIGHT target while staying inside {_ANTON_PARAGRAPH_WORD_RANGE} words and exactly {_ANTON_PARAGRAPH_FORMULA_SENTENCES} sentences. Use the formula: {_ANTON_PARAGRAPH_FORMULA}. Never list research-card fields. "
                    "Open with the machine's most interesting tension, ambition, or consequence, then move cleanly to why it mattered. "
                    "Use a sourced memorable_fact when the story plan provides one, but merge it into the strongest required beat instead of adding trivia. "
                    "The final line must land as a verdict, paradox, irony, or reversal; brevity decides which secondary facts to cut, not whether the paragraph has a point. "
                    "Count the finished paragraph before returning it. If it exceeds the narrative-weight target, remove the least important fact rather than compressing more facts into longer sentences. "
                    "If it lands UNDER the register target band, fold in one more sourced fact - a number, loss figure, or documented detail from the plan - rather than returning thin; major machines earn their 110-150 words."
                )
            story_distiller_system_prompt = (
                "You are a source-grounded Anton/DVsU paragraph compiler for a machine documentary. "
                "Output only valid JSON matching the requested schema. Do not write prose outside JSON, markdown, citations, or alternate keys."
            )
            story_plan = None
            bundle = None
            if complete_inventory_mode:
                story_plan = dict(precomputed_story_plan or _machine_story_plan(rp, machine, dvsu_rule_overrides))
                story_plan["contract"] = dict(story_plan.get("contract") or {})
                story_plan["contract"]["opening_assignment"] = opening_brief
                story_plan["contract"]["narrative_weight"] = dict(narrative_weight)
                machine_artifact_key = _verified_source_cache_key(machine)
                plan_errors = list(story_plan.get("evidence_errors") or [])
                missing_slots = [
                    slot["slot"] for slot in story_plan["slots"]
                    if slot.get("required") and not slot["evidence_ids"]
                ]
                if missing_slots:
                    plan_errors.append(f"missing source-addressable evidence for Anton slots: {', '.join(missing_slots)}")
                if plan_errors:
                    msg = "Story compiler evidence gate failed: " + "; ".join(plan_errors)
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    if target_machine:
                        return await _return_saved_failed_preview(
                            machine,
                            i,
                            msg,
                            story_plan=story_plan,
                        )
                    return {"status": "failed", "error": msg, "video_id": video_id}
                brief_save_result = await execute(
                    """UPDATE videos SET research_payload = jsonb_set(
                           COALESCE(research_payload::jsonb, '{}'::jsonb),
                           '{machine_script_briefs}',
                           COALESCE(research_payload::jsonb->'machine_script_briefs', '{}'::jsonb)
                             || jsonb_build_object($1::text, $2::jsonb),
                           true
                       ), updated_at = now()
                       WHERE id = $3 AND tenant_id = $4
                         AND (
                             research_payload->'unit_roster' IS NULL
                             OR research_payload->'unit_roster' = $5::jsonb
                         )""",
                    machine_artifact_key, _json_sh.dumps(story_brief), video_id, self.tenant_id, locked_roster_snapshot,
                )
                if self._db_write_missed(brief_save_result):
                    msg = "persisted unit_roster changed concurrently; script preview brief save refused"
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    return {"status": "failed", "error": msg, "video_id": video_id}
                _mirror_response_artifact("machine_script_briefs", machine_artifact_key, story_brief)
                plan_save_result = await execute(
                    """UPDATE videos SET research_payload = jsonb_set(
                           COALESCE(research_payload::jsonb, '{}'::jsonb),
                           '{machine_story_plans}',
                           COALESCE(research_payload::jsonb->'machine_story_plans', '{}'::jsonb)
                             || jsonb_build_object($1::text, $2::jsonb),
                           true
                       ), updated_at = now()
                       WHERE id = $3 AND tenant_id = $4
                         AND (
                             research_payload->'unit_roster' IS NULL
                             OR research_payload->'unit_roster' = $5::jsonb
                         )""",
                    machine_artifact_key, _json_sh.dumps(story_plan), video_id, self.tenant_id, locked_roster_snapshot,
                )
                if self._db_write_missed(plan_save_result):
                    msg = "persisted unit_roster changed concurrently; script preview story-plan save refused"
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    return {"status": "failed", "error": msg, "video_id": video_id}
                _mirror_response_artifact("machine_story_plans", machine_artifact_key, story_plan)
                # PLAN -> WRITE -> EDIT (2026-07-17). Code picks the facts and
                # keeps the ledger; the model only writes; failures get minimal
                # targeted edits of the SAME draft. See _deterministic_beat_plan.
                beat_plan = _deterministic_beat_plan(story_plan, machine)
                twist_menu = list((story_plan.get("contract") or {}).get("twist_menu") or [])
                voice_rules = (
                    "VOICE RULES (the only laws the writer owns - everything else is planned for you):\n"
                    "- GROUNDING: zero freedom in WHAT is claimed. Every checkable fact (number, date, proper noun, spec) must come from this sentence's listed evidence. Abstract vocabulary and common verbs are free; prefer the evidence's own concrete nouns. Never invent a month, place, or name the evidence lacks.\n"
                    "- Sourced names stay as written: never expand an abbreviation (`RAF` never becomes `Royal Air Force`).\n"
                    "- The narration must say the locked machine designation at least once (a precursor model name does not count).\n"
                    f"- Hedge lexicon (the gate recognizes exactly these): {', '.join(_HEDGE_WORDS)}. A single-source quantity is stated as a hedged round, never dropped. Designations are names: never hedge or respell their digits.\n"
                    "- Spoken number words for counts, speeds, weights, and percentages. Digits ONLY for designations, calendar years, and exact figures of four or more digits. Spell out unit abbreviations (mph -> miles per hour).\n"
                    "- One terminal period per sentence: no semicolons, no internal periods, no abbreviations with dots.\n"
                    "- Avoid high-risk absolutes unless this sentence's evidence uses the exact word: first, only, largest, fastest, most, never.\n"
                    "- Vary sentence length for spoken delivery; never three long sentences in a row. No hype words, no Wikipedia-style existence openers, no ranked-list connectors, no However/Furthermore/Moreover starts.\n"
                    "- The paragraph should read like Anton: facts serve the engineering argument, not an encyclopedia checklist.\n"
                    f"- WORD BAND: hard floor {_ANTON_PARAGRAPH_HARD_MIN_WORDS}, hard ceiling {_ANTON_PARAGRAPH_HARD_MAX_WORDS}; aim for the register target. If a draft lands under the target, fold in one more planned fact rather than returning thin.\n"
                )
                reference_benchmark = story_plan.get("reference_benchmark") if isinstance(story_plan.get("reference_benchmark"), dict) else {}
                benchmark_line = ""
                if reference_benchmark:
                    benchmark_line = (
                        "REFERENCE SHAPE (reference_benchmark, shape only): "
                        f"~{reference_benchmark.get('word_count')} words, {reference_benchmark.get('sentence_count')} sentences, "
                        f"opening mode {reference_benchmark.get('opening_mode')}, final line job: {reference_benchmark.get('final_line_job')}. "
                        "Do not copy or infer unsourced facts from it.\n"
                    )
                write_prompt = (
                    "WRITE ONE ANTON-STYLE PARAGRAPH AS FIVE SENTENCES FROM THE BEAT PLAN BELOW.\n\n"
                    f"VIDEO TITLE: {title}\n"
                    f"{machine_scope_line}"
                    f"{neighbor_context}"
                    f"OPENING ASSIGNMENT: {opening_brief}\n"
                    "Follow OPENING ASSIGNMENT exactly. If it says not to open with the machine name, the first sentence must not start with the locked machine name or designation.\n"
                    f"NARRATIVE WEIGHT: {narrative_weight.get('label')} / target {narrative_weight.get('target_words')} words / {narrative_weight.get('guidance')}\n"
                    f"{benchmark_line}\n"
                    "The facts are already chosen. Sentence N uses ONLY the evidence listed under sentence N - your craft decides how it reads, not what it claims. "
                    "Citation bookkeeping is handled by code; do not produce a claim map.\n\n"
                    f"STYLE / SENTENCE CRAFT:\n{structure_brief}\n"
                    f"BEAT PLAN:\n{_beat_plan_prompt_block(beat_plan, machine)}\n\n"
                    f"{voice_rules}\n"
                    "TWIST: declare the designed-vs-used gap the reality sentence proves. "
                    f"twist.type comes from this menu: {', '.join(twist_menu) or 'role_change, mission_change, absent'}; "
                    "only a machine used exactly as designed may declare `absent`, and then twist.substitute names superlative, legacy, irony, or anti_twist.\n"
                    "editorial_thesis: 6-26 words naming the specific engineering decision, tradeoff, or contrast.\n\n"
                    "Return ONLY this JSON: "
                    '{"editorial_thesis":"...","twist":{"type":"...","substitute":null,"summary":"built for X, used as Y"},'
                    '"sentences":["sentence 1","sentence 2","sentence 3","sentence 4","closer"]}'
                )
                raw_story = await anthropic_client.generate(
                    prompt=write_prompt,
                    system_prompt=story_distiller_system_prompt + inventory_system_override,
                    max_tokens=1200,
                    temperature=0.2,
                )
                bundle = _parse_planned_story_sentences(raw_story, beat_plan)
                bundle = _repair_machine_story_bundle_mechanics(machine, story_plan, bundle)
                bundle = _trim_machine_story_bundle_to_contract(machine, story_plan, bundle)
                paragraph, warnings = _validate_machine_story_sentences(machine, story_plan, bundle, dvsu_rule_overrides)
                # EDIT loop: same draft back with only the violations - minimal
                # local fixes converge where fresh re-rolls oscillated.
                edit_round = 0
                while _blocking_warnings(warnings) and edit_round < 2:
                    edit_round += 1
                    current_sentences = bundle.get("formula_sentences") or []
                    edit_prompt = (
                        "EDIT THIS DRAFT MINIMALLY. Change ONLY what the violations name; keep every other word.\n\n"
                        "CURRENT SENTENCES:\n"
                        + "\n".join(f"{i}. {s}" for i, s in enumerate(current_sentences, start=1))
                        + "\n\nVIOLATIONS TO FIX (everything else already passes):\n"
                        + "\n".join(f"- {w}" for w in _blocking_warnings(warnings))
                        + "\n\nEach sentence may use ONLY its beat's evidence:\n"
                        + _beat_plan_prompt_block(beat_plan, machine)
                        + f"\n\n{voice_rules}\n"
                        "Return ONLY this JSON (all five sentences, edited ones included): "
                        '{"editorial_thesis":"...","twist":{"type":"...","substitute":null,"summary":"..."},'
                        '"sentences":["...","...","...","...","..."]}'
                    )
                    raw_story = await anthropic_client.generate(
                        prompt=edit_prompt,
                        system_prompt=story_distiller_system_prompt + inventory_system_override,
                        max_tokens=1200,
                        temperature=0.1,
                    )
                    edited = _parse_planned_story_sentences(raw_story, beat_plan)
                    if edited.get("_parse_error"):
                        break
                    edited["editorial_thesis"] = edited.get("editorial_thesis") or bundle.get("editorial_thesis")
                    edited["twist"] = edited.get("twist") or bundle.get("twist")
                    bundle = _repair_machine_story_bundle_mechanics(machine, story_plan, edited)
                    bundle = _trim_machine_story_bundle_to_contract(machine, story_plan, bundle)
                    paragraph, warnings = _validate_machine_story_sentences(machine, story_plan, bundle, dvsu_rule_overrides)
                research_source_kind = "structured_story_plan"
            else:
                prompt = (
                    "Write ONE spoken narration paragraph for a Designed vs Used static machine documentary.\n\n"
                    f"VIDEO TITLE: {title}\n"
                    f"VIDEO THESIS / ARC: {video_thesis}\n"
                    f"{machine_scope_line}"
                    f"{neighbor_context}\n"
                    "HARD CONTRACT:\n"
                    f"- Return exactly ONE paragraph. WORD LAW: hard floor {_ANTON_PARAGRAPH_HARD_MIN_WORDS} words, hard ceiling {_ANTON_PARAGRAPH_HARD_MAX_WORDS}; target the register band {_DVSU_REGISTER_TARGETS['spec_block']} (marquee machines may run 110-150, deliberately bare entries 80-95).\n"
                    "- TWIST LAW: run the entry on its designed-vs-used gap - state what it was built for, then invert to how it was actually used or ended; a machine used exactly as designed must substitute a superlative, legacy hook, or timing irony.\n"
                    f"- CLOSER: end on a sharpened verdict (single-hammer, antithesis, concede-then-cut, or triad) of {_ANTON_FINAL_SENTENCE_MAX_WORDS} words or fewer. Any editorial vocabulary is legal there, but introduce no new named entities, numbers, or designations.\n"
                    "- The paragraph is final voiceover narration, not notes. No heading, markdown, bullets, labels, citations, JSON, b-roll cues, thumbnail lines, or bracketed production notes.\n"
                    "- Concentrate all effort on THIS machine only. Do not summarize the whole roster.\n"
                    "- Do not mention any other aircraft or machine designation.\n"
                    f"- Use only facts supported by the {research_source_kind} below. If a detail is not supported, omit it.\n"
                    "- Include the locked machine designation/name naturally.\n"
                    f"- OPENING ASSIGNMENT: {opening_brief}\n"
                    f"{structure_brief}"
                    "- Documentary authority: calm, precise, spoken, and specific. No hype, generic praise, Wikipedia opening, list writing, or spec dump.\n"
                    "- Vary sentence length for spoken delivery. Do not write three long sentences in a row.\n"
                    "- Do not write a chronological biography. Dates are allowed only when they prove the engineering problem, decision, tradeoff, or reality.\n"
                    "- Avoid written-language connector sentence starts such as However, Nevertheless, Furthermore, Moreover, Additionally, or In addition.\n"
                    + ("" if target_machine else "- Bridge naturally from the previous machine when useful, but never use ranked-list connectors such as Next is, Next came, Another aircraft was, Moving on to, At number, Coming in at number, or on this list.\n")
                    + "\n"
                    f"RESEARCH SOURCE ({research_source_kind}):\n{research_source}"
                )
                paragraph = await anthropic_client.generate(
                    prompt=prompt,
                    system_prompt=script_system_prompt + inventory_system_override,
                    max_tokens=450,
                    temperature=0.45,
                )
                paragraph = self._clean_static_unit_paragraph(paragraph)
                warnings = self._validate_static_unit_paragraph(machine, paragraph, dvsu_rule_overrides)
                warnings.extend(_opening_assignment_warnings(machine, paragraph, opening_brief))

            # Warn-severity (advisory-prefixed) flags never trigger a repair round.
            # Inventory mode already ran its convergent EDIT loop above; the
            # fresh-re-roll rebuild below is retired for it (2026-07-17) and
            # kept only for the legacy non-inventory paragraph path.
            if _blocking_warnings(warnings) and not complete_inventory_mode:
                if complete_inventory_mode:
                    repair_prompt = (
                        "REBUILD THE ANTON-STYLE PARAGRAPH JSON FROM THE SAME LOCKED STORY PLAN.\n\n"
                        f"Validation warnings: {'; '.join(warnings)}\n\n"
                        f"OPENING ASSIGNMENT: {opening_brief}\n"
                        f"NARRATIVE WEIGHT: {narrative_weight.get('label')} / target {narrative_weight.get('target_words')} words / {narrative_weight.get('guidance')}\n\n"
                        f"STYLE / SENTENCE CRAFT:\n{structure_brief}\n"
                        "Return only the exact JSON shape: {\"editorial_thesis\":\"single engineering decision or contrast\",\"twist\":{\"type\":\"role_change\",\"substitute\":null,\"summary\":\"built for X, used as Y in one line\"},\"formula_sentences\":[\"original_problem sentence\",\"engineering_decision sentence\",\"tradeoff sentence\",\"reality sentence\",\"paragraph-derived conclusion\"],\"claim_map\":[{\"span\":\"exact formula-sentence words\",\"slot\":\"original_problem\",\"used_evidence_ids\":[\"...\"]}],\"onscreen_label\":\"...\"}. "
                        "editorial_thesis must be 6-26 words and state the specific engineering decision, tradeoff, or contrast this machine represents; it is not narration and not a generic importance summary. "
                        "TWIST LAW (hard): declare twist.type from the plan's twist_menu (closest NAMED subtype; `other` is a last resort). Only a used-exactly-as-designed machine may declare `absent`, and then twist.substitute MUST name superlative, legacy, irony, or anti_twist - no gap and no substitute reads as a spec dump and is rejected. "
                        "CONVERSION SIGNAL (hard): when the plan's contract carries conversion_signal_evidence_ids, the FIRST listed id is the machine's documented designed-vs-used story - write the reality sentence FROM that flagged evidence, cite it in that sentence's claim_map row, and build the twist from it; an acceptance, delivery, or test event is never the reality beat while a flagged conversion segment exists. "
                        f"Write exactly {_ANTON_PARAGRAPH_FORMULA_SENTENCES} formula_sentences following {_ANTON_PARAGRAPH_FORMULA}; code assembles the paragraph by joining them with spaces. WORD LAW: hard floor {_ANTON_PARAGRAPH_HARD_MIN_WORDS} and hard ceiling {_ANTON_PARAGRAPH_HARD_MAX_WORDS} words; hit the register target in NARRATIVE WEIGHT (major machines 110-150, transitional 80-95, spec-block register {_DVSU_REGISTER_TARGETS['spec_block']}); a draft under the register band folds in one more sourced fact rather than returning thin. "
                        "formula_sentences must contain the exact five final sentences in order; do NOT return a paragraph key and never re-type the sentences anywhere else - code does the joining. "
                        "Follow OPENING ASSIGNMENT exactly; if it says not to open with the machine name, the first sentence must not start with the locked machine name or designation. "
                        "The narration must name the locked machine designation at least once (a precursor or model name does not satisfy this). "
                        "Sourced names are locked as written: never expand or alter an abbreviation the evidence uses (evidence `RAF` never becomes `Royal Air Force`). "
                        "claim_map must cover every factual clause and use selected evidence IDs covering original_problem, engineering_decision, tradeoff, and reality. "
                        "COVERAGE LAW (hard): inside the four evidence-backed sentences every content-carrying word must sit INSIDE a claim-mapped span; text between spans is connective glue only (and, but, while, that, which, its) - a factual phrase you cannot claim-map gets cut, never decorated around the evidence. "
                        "Each claim_map span must sit inside exactly one formula sentence; never use a whole paragraph, multiple sentences, or a span that crosses sentence boundaries. "
                        "If the plan provides a memorable_fact slot, use at least one memorable_fact evidence ID inside the strongest required beat; do not add a separate trivia sentence. "
                        "If the plan provides a human_detail slot for one of the first three benchmark machines, use it inside the strongest evidence-backed beat; do not add a separate anecdote sentence. "
                        "The final sentence must be editorial synthesis from the rebuilt paragraph only. Do not include it in claim_map; if it needs evidence IDs, rewrite it without the new fact. "
                        "VERDICT PUNCH (hard): the closer must be single-hammer, antithesis, concede-then-cut, or triad - never a summary or recap. If the flagged closer restates facts, rewrite it as the house punch: a two-part parallel antithesis restating the designed-vs-used gap and landing on the result side, each half four to nine words. "
                        "CLOSER FREEDOM: the closer may use any editorial or abstract vocabulary, including nationality/geographic color; it may NOT introduce new person, organization, or operation names, new designations, or a new number paired with a new entity. "
                        "GROUNDING LAW: checkable facts (numbers, dates, proper nouns, designations, spec claims) must appear in locked evidence; abstract vocabulary is free; prefer evidence wording for colorful concrete nouns. A hedged direction-consistent round of a sourced value is legal; exact dates need one locked source, quantities need two. "
                        "Every unhedged exact number, specification, production count, date, or superlative must appear in locked evidence from two independent sources (two different source URLs anywhere in the locked story plan, not only the cited IDs); otherwise HEDGE the claim - do not drop it. Designations are exempt: never hedge, source-check, or reword a designation. "
                        "SPEC LAW (hard): a single-source number is HEDGED, never omitted - when the plan carries sourced scale, capability, or production numbers, keep the spec block and production reality with real numbers, writing single-sourced values as hedged rounds; `many`/`several` where a count exists is a rejection. "
                        "NUMBER FLOOR (hard, Strategic Bomber benchmark): the evidence-backed sentences must carry at least TWO sourced numerical details inside claim-mapped spans (spec figure, production count, loss figure, range, or speed); a number-free paragraph is rejected. "
                        "The production count and any superlative it earns belong in the fourth evidence-backed sentence with the reality beat, NEVER in the closer - the closer is number-free synthesis. "
                        f"Accepted hedge words (the gate recognizes exactly these): {', '.join(_HEDGE_WORDS)}. "
                        "For the Strategic Bomber benchmark, keep Anton's compact inventory cadence: selected scale/spec facts, production or service reality, and a landed verdict, all from locked evidence. "
                        "Use voice-ready spoken number words for years and quantities. Designations like XB-15, B-52, and F-86 are NAMES, not numbers: keep their digits exactly as written, never spell them out, never hedge them, and they need no numeric source support. Spell unit abbreviations like mph, rpm, ft, lb, mi, and hp into spoken words in narration. If validation says raw numeric digit or written unit abbreviation, rewrite that quantity as spoken words but leave designations untouched. "
                        f"Use at most {story_plan['contract']['maximum_numerical_details']} numerical details total (the register cap), including years, counts, ranges, speeds, weights, percentages, and spelled numbers. "
                        "If validation says a number is unsupported, remove that exact number from the paragraph and claim_map entirely; do not try to remap it. "
                        "If validation says there are too many numerical details, rewrite around fewer concepts: original problem, engineering decision, tradeoff, and reality. "
                        "No orphan facts: every technical detail must explain why the machine was designed that way, what problem it solved, or what consequence it created. "
                        "No markdown, labels, b-roll cues, thumbnail lines, or bracketed production notes. "
                        "Vary sentence length for spoken delivery; do not write three long sentences in a row. "
                        "Do not write a chronological biography. Dates are allowed only when they prove the engineering problem, decision, tradeoff, or reality. "
                        "Remove written-language connector sentence starts such as However, Nevertheless, Furthermore, Moreover, Additionally, or In addition. "
                        "Remove ranked-list connectors such as Next is, Next came, Another aircraft was, Moving on to, At number, Coming in at number, or on this list. "
                        "Do not include optional-slot numbers if required slots already tell the story. "
                        "Introduce no unsupported claims, designations, or numerical details. "
                        "Delete every unsupported high-risk term named in the validation warnings unless that exact word appears in the selected source evidence. "
                        f"End with a paragraph-derived Anton-style verdict of {_ANTON_FINAL_SENTENCE_MAX_WORDS} words or fewer, not a generic summary, and do not add dates, specs, production counts, or new events there. The rejected draft is hidden; start fresh.\n\n"
                        f"LOCKED STORY PLAN:\n{_json_sh.dumps(story_plan, ensure_ascii=False, indent=2)}"
                    )
                    raw_story = await anthropic_client.generate(
                        prompt=repair_prompt,
                        system_prompt=story_distiller_system_prompt + inventory_system_override,
                        max_tokens=1500,
                        temperature=0.15,
                    )
                    bundle = _parse_machine_story_sentences(raw_story)
                    bundle = _repair_machine_story_bundle_mechanics(machine, story_plan, bundle)
                    bundle = _trim_machine_story_bundle_to_contract(machine, story_plan, bundle)
                    paragraph, warnings = _validate_machine_story_sentences(machine, story_plan, bundle, dvsu_rule_overrides)
                else:
                    repair_prompt = (
                        f"Write a fresh replacement paragraph for LOCKED MACHINE: {machine}.\n"
                        f"Validation warnings: {'; '.join(warnings)}\n\n"
                        f"OPENING ASSIGNMENT: {opening_brief}\n\n"
                        f"Return exactly ONE spoken paragraph. WORD LAW: hard floor {_ANTON_PARAGRAPH_HARD_MIN_WORDS} words, hard ceiling {_ANTON_PARAGRAPH_HARD_MAX_WORDS}; target the register band {_DVSU_REGISTER_TARGETS['spec_block']}. "
                        "Run the entry on its designed-vs-used gap (built for X, used as Y, or a named substitute). "
                        f"End on a sharpened verdict of {_ANTON_FINAL_SENTENCE_MAX_WORDS} words or fewer - single-hammer, antithesis, concede-then-cut, or triad; free editorial vocabulary, but no new named entities, numbers, or designations. "
                        "Follow OPENING ASSIGNMENT exactly. No markdown, labels, b-roll cues, thumbnail lines, or bracketed production notes. Include the locked designation/name. Use only the same research source. "
                        "Do not mention any other aircraft or machine designation. "
                        "Vary sentence length for spoken delivery; do not write three long sentences in a row. "
                        "Do not write a chronological biography. Dates are allowed only when they prove the engineering problem, decision, tradeoff, or reality. "
                        "Remove ranked-list connectors such as Next is, Next came, Another aircraft was, Moving on to, At number, Coming in at number, or on this list. "
                        "Preserve the engineering thesis, one surprising fact, and a clean final irony/reversal; cut secondary specs and timeline filler.\n\n"
                        "The rejected draft is deliberately hidden so you do not preserve its structure or fact density. Start over from this research source.\n\n"
                        f"RESEARCH SOURCE:\n{research_source}"
                    )
                    paragraph = await anthropic_client.generate(
                        prompt=repair_prompt,
                        system_prompt=script_system_prompt + "\n\nRepair only the supplied paragraph. Output only final spoken narration.",
                        max_tokens=450,
                        temperature=0.25,
                    )
                    paragraph = self._clean_static_unit_paragraph(paragraph)
                    warnings = self._validate_static_unit_paragraph(machine, paragraph, dvsu_rule_overrides)
                    warnings.extend(_opening_assignment_warnings(machine, paragraph, opening_brief))

            # QL-7: classify and STORE the opener type; budget the name-openers.
            opener_type = _classify_opener_type(paragraph, machine)
            mode_profile = ((story_plan or {}).get("contract") or {}).get("mode_profile") if isinstance(story_plan, dict) else None
            opener_name_budget = float((mode_profile or {}).get("opener_name_budget") or 0.6)
            if complete_inventory_mode:
                existing_previews = rp.get("machine_script_previews") if isinstance(rp.get("machine_script_previews"), dict) else {}
                prior_opener_types = []
                for prior_key, prior_preview in existing_previews.items():
                    if not isinstance(prior_preview, dict):
                        continue
                    if _normalized_unit_code(str(prior_preview.get("machine") or prior_key)) == _normalized_unit_code(machine):
                        continue
                    prior_opener_types.append(
                        str(prior_preview.get("opener_type") or "")
                        or _classify_opener_type(str(prior_preview.get("paragraph") or ""), str(prior_preview.get("machine") or ""))
                    )
                all_opener_types = prior_opener_types + [opener_type]
                name_share = all_opener_types.count("name") / max(1, len(all_opener_types))
                if len(all_opener_types) >= 3 and name_share > opener_name_budget:
                    warnings.append(
                        _ADVISORY_PREFIX + f"name-openers at {int(round(name_share * 100))}% of previews exceed the "
                        f"{int(round(opener_name_budget * 100))}% budget - open on a bridge, role/thesis claim, or date context (QL-7)"
                    )
                if len(all_opener_types) >= 3 and len(set(all_opener_types[-3:])) == 1:
                    warnings.append(
                        _ADVISORY_PREFIX + f"three consecutive {all_opener_types[-1]} openers - vary the opener type (QL-7)"
                    )

            quality_audit = _anton_preview_quality_audit(
                machine,
                story_plan or {},
                bundle or {},
                paragraph,
                warnings,
                dvsu_rule_overrides,
            ) if complete_inventory_mode else {}
            audit_checks = (quality_audit or {}).get("checks") if isinstance(quality_audit, dict) else []
            audit_blocking_checks_passed = bool(audit_checks) and all(
                isinstance(check, dict) and (check.get("passed") is True or check.get("advisory") is True)
                for check in audit_checks
            )
            # Warn-severity (advisory-prefixed) flags never block a preview.
            preview_passed = (not _blocking_warnings(warnings)) and (
                bool((quality_audit or {}).get("passed")) and audit_blocking_checks_passed
                if complete_inventory_mode else
                True
            )
            bundle_twist = bundle.get("twist") if isinstance(bundle, dict) and isinstance(bundle.get("twist"), dict) else {}
            twist_type_label = str(bundle_twist.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
            validation_units.append({
                "scene": i,
                "machine": machine,
                "word_count": _spoken_word_count(paragraph),
                "research_source": research_source_kind,
                "passed": preview_passed,
                "warnings": warnings,
                "opener_type": opener_type,
                "twist_type": twist_type_label,
                "quality_audit": quality_audit,
            })
            if target_machine:
                claim_bundle = bundle if isinstance(bundle, dict) else {}
                preview = {
                    "machine": machine,
                    "scene": i,
                    "paragraph": " ".join(paragraph.split()),
                    "word_count": _spoken_word_count(paragraph),
                    "passed": preview_passed,
                    "warnings": warnings,
                    "onscreen_label": str(claim_bundle.get("onscreen_label") or "").strip(),
                    "research_source": research_source_kind,
                    "story_plan": story_plan,
                    "claim_bundle": claim_bundle,
                    "opener_type": opener_type,
                    "twist_type": twist_type_label,
                    "quality_audit": quality_audit,
                }
                if save_target_script:
                    preview["saved"] = False
                    if preview_passed:
                        script_block = await self._save_machine_script_block(
                            video_id=video_id,
                            video=video,
                            roster=roster,
                            script_block=preview,
                            title=title,
                            voice_id=voice_id,
                        )
                        await self._log_activity(
                            bot_name, video_id, "completed",
                            f"Single-machine script block saved: {machine}",
                        )
                        return {"status": "completed", "video_id": video_id, "script_block": script_block}
                    await self._log_activity(
                        bot_name, video_id, "failed",
                        f"Single-machine script block needs review: {machine}",
                    )
                    return {"status": "completed", "video_id": video_id, "script_block": preview}
                preview_save_result = await self._checkpoint_machine_script_preview(
                    video_id, _verified_source_cache_key(machine), preview, locked_roster_snapshot,
                )
                if self._db_write_missed(preview_save_result):
                    msg = "persisted unit_roster changed concurrently; script preview save refused"
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    return {"status": "failed", "error": msg, "video_id": video_id}
                _mirror_response_artifact(
                    "machine_script_previews",
                    _verified_source_cache_key(machine),
                    preview,
                )
                await self._log_activity(
                    bot_name, video_id, "completed" if preview_passed else "failed",
                    f"Single-machine script preview {'passed' if preview_passed else 'needs review'}: {machine}",
                )
                return {
                    "status": "completed",
                    "video_id": video_id,
                    "preview": preview,
                    "research_payload": response_research_payload,
                }
            if not preview_passed:
                validation = {"script_hold": {"passed": False, "units": validation_units}}
                await execute(
                    "UPDATE videos SET script_validation = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
                    _json_sh.dumps(validation), video_id, self.tenant_id,
                )
                msg = f"Script-hold stopped at machine {i}/{len(roster)} ({machine}): " + "; ".join(
                    _review_messages(warnings) or [str((quality_audit or {}).get("summary") or "Anton quality audit needs review")]
                )
                await self._log_activity(bot_name, video_id, "failed", msg[:900])
                return {"status": "failed", "error": msg, "video_id": video_id}

            paragraph = " ".join(paragraph.split())
            paragraphs.append(paragraph)
            # Persist only hold/progress metadata after each machine. Script rows
            # remain atomic and are replaced only after every paragraph passes.
            # The UI can therefore show real machine-level progress without a
            # failed run ever exposing or replacing a partial documentary script.
            progress_hold = {
                "passed": False,
                "in_progress": True,
                "completed_count": len(paragraphs),
                "total_count": len(roster),
                "units": validation_units,
            }
            await execute(
                """UPDATE videos
                   SET script_validation = jsonb_set(
                       COALESCE(script_validation::jsonb, '{}'::jsonb),
                       '{script_hold}', $1::jsonb, true
                   ), updated_at = now()
                   WHERE id = $2 AND tenant_id = $3""",
                _json_sh.dumps(progress_hold), video_id, self.tenant_id,
            )
            await self._log_activity(bot_name, video_id, "started", f"Script-hold paragraph {i}/{len(roster)} passed: {machine}")

        full_script = "\n\n".join(paragraphs)
        existing = video.get("script_validation")
        try:
            validation = _json_sh.loads(existing) if isinstance(existing, str) and existing.strip() else (existing or {})
        except Exception:
            validation = {}
        if not isinstance(validation, dict):
            validation = {}
        # QL-4 script-run budget: warn when over 40% of classified twists fall
        # to `other` (or off-menu labels counted as `other`).
        script_run_warnings: list[str] = []
        classified_twists = [
            str(unit.get("twist_type") or "") for unit in validation_units
            if str(unit.get("twist_type") or "")
        ]
        other_like_twists = [
            label for label in classified_twists
            if label not in _DVSU_TWIST_TYPES and label != "absent"
        ]
        if classified_twists and len(other_like_twists) / len(classified_twists) > 0.4:
            script_run_warnings.append(
                _ADVISORY_PREFIX + f"{len(other_like_twists)}/{len(classified_twists)} twists fell to `other` "
                "(over the 40% budget) - pick named subtypes from the menu (QL-4)"
            )
        validation["script_hold"] = {"passed": True, "units": validation_units, "warnings": script_run_warnings}
        staged_rows = [
            {"scene": i, "scene_text": paragraph}
            for i, paragraph in enumerate(paragraphs, start=1)
        ]
        # One PostgreSQL statement means video mirror update + script row
        # replacement either all commit or all roll back. The scripts mutation is
        # gated by the updated video row so a tenant/video miss cannot create
        # orphan replacement rows.
        replacement_result = await execute(
            """WITH updated AS (
                   UPDATE videos
                   SET script = $6, script_validation = $7, updated_at = now()
                   WHERE id = $2 AND tenant_id = $1
                   RETURNING id
               ), deleted AS (
                   DELETE FROM scripts s
                   USING updated u
                   WHERE s.video_id = u.id AND s.tenant_id = $1
                   RETURNING 1
               )
               INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
               SELECT $1, u.id, staged.scene, staged.scene_text, $4, 'Create', $5
               FROM updated u
               CROSS JOIN (SELECT count(*) AS deleted_count FROM deleted) d
               CROSS JOIN jsonb_to_recordset($3::jsonb) AS staged(scene int, scene_text text)""",
            self.tenant_id,
            video_id,
            _json_sh.dumps(staged_rows),
            title,
            voice_id,
            full_script,
            _json_sh.dumps(validation),
        )
        if self._db_write_missed(replacement_result):
            msg = "Script-hold final save refused because the video is no longer available for this tenant"
            await self._log_activity(bot_name, video_id, "failed", msg)
            return {"status": "failed", "error": msg, "video_id": video_id}
        from drive_workspace import sync_video_workspace_fail_soft
        await sync_video_workspace_fail_soft(video_id, self.tenant_id)

        roster_check = await self._validate_static_script_roster(video_id)
        if roster_check.get("complete_title") and not roster_check.get("passed"):
            msg = "Script roster gate failed after script-hold: " + "; ".join(roster_check.get("warnings", []))
            await self._log_activity(bot_name, video_id, "failed", msg[:900])
            return {"status": "failed", "error": msg, "video_id": video_id}

        current_status = str(video.get("status") or "ready_for_scripting")
        eff_status = self._skip_disabled_next(video, "ready_for_voice")
        await self._update_video_status(video_id, eff_status)
        await self._log_transition(video_id, current_status, eff_status, "api")
        await self._log_activity(
            bot_name, video_id, "completed",
            f"Script-hold complete ({len(paragraphs)} machine paragraphs, {len(full_script.split())} words)",
        )
        return {"status": eff_status, "video_id": video_id, "new_status": eff_status}

    async def _factual_gate_static(self, video_id: str) -> None:
        """Factual gate for static documentaries: verify every claim in the
        script against the research payload; on flagged claims, regenerate
        ONCE with an explicit only-use-researched-facts directive, then
        re-verify. The final verdict lands in the activity feed either way so
        the operator can see exactly what was flagged. Fail-open on errors —
        a broken checker must not block a build — but a *flagged* script gets
        its one correction pass."""
        try:
            import json as _json_fg
            from script.brief_translator.script_generator import verify_script_claims

            video = await self._get_video(video_id)
            script = (video or {}).get("script") or ""
            rp_raw = (video or {}).get("research_payload")
            if not script.strip() or not rp_raw:
                return
            brief = _json_fg.loads(rp_raw) if isinstance(rp_raw, str) else rp_raw
            client = getattr(self._pipeline, "anthropic", None)
            if client is None or not isinstance(brief, dict):
                return

            flagged = await verify_script_claims(client, script, brief)
            if not (flagged or "").strip():
                await self._log_activity(
                    "Script Bot", video_id, "running",
                    "Fact check passed: every claim traces to the research")
                return

            await self._log_activity(
                "Script Bot", video_id, "running",
                "Fact check flagged claims — rewriting from the research only:\n"
                + flagged[:600])
            existing = (video.get("writer_guidance") or "")
            block = (
                "\n\n--- FACTUAL CORRECTION (auto, internal) ---\n"
                "This channel publishes exact figures; its audience checks them. "
                "Rewrite using ONLY facts present in the research payload. Remove "
                "or replace every flagged claim below — if the research doesn't "
                "state it, the script may not either. Flagged:\n"
                + flagged.strip()
                + "\n--- END FACTUAL CORRECTION ---"
            )
            await execute(
                "UPDATE videos SET writer_guidance = $1 WHERE id = $2",
                existing + block, video_id)
            self._load_idea_from_video(video_id)
            await self._pipeline.run_brief_translator()

            video = await self._get_video(video_id)
            flagged2 = await verify_script_claims(
                client, (video or {}).get("script") or "", brief)
            if (flagged2 or "").strip():
                await self._log_activity(
                    "Script Bot", video_id, "running",
                    "Fact check STILL flags claims after one rewrite — review "
                    "before publishing:\n" + flagged2[:600])
            else:
                await self._log_activity(
                    "Script Bot", video_id, "completed",
                    "Fact check passed after rewrite: claims trace to the research")
        except Exception as e:  # noqa: BLE001
            print(f"[Script] factual gate skipped for {video_id[:8]}: {str(e)[:200]}", flush=True)

    async def _grade_and_maybe_revise_script(
        self, video_id: str, regenerate=None, *, hold_status: Optional[str] = None,
    ) -> dict:
        """C46a generalized quality-critic hook. Absorbs the single grading
        call this pipeline already made here (originality.grade_script_with_client)
        into script_quality.critique_script - same one Claude call, never a
        second one for the same draft - then runs DvsU's proven bounded
        convergence instead of a flat one-reroll:

          - 'revise': same-draft targeted EDIT (script_quality.edit_draft_with_
            violations), up to script_quality.MAX_EDIT_ROUNDS (2) rounds -
            NOT a fresh re-roll.
          - 'regenerate': ONE fresh reroll via ``regenerate`` (originality's
            own bound), when the caller wired one.
          - Still failing after those bounds -> needs_review: violations are
            attached to videos.script_validation (the same "passed"/"checks"
            shape the modeled-script, user_script, and DvsU save paths
            already use), and if ``hold_status`` is given (the modeled path
            already advanced the video's status before grading runs), that
            status is reverted so an unresolved script does not silently
            slide to the next stage. The plain brief_translator path passes
            no hold_status because grading runs BEFORE it advances status -
            the caller just checks this method's return value first.

        rules_text seam (C46b): sourced from this tenant's active
        `quality_rules` rows, scope-matched against THIS video's own shape
        (research/story/render_style — see quality_rules.resolve_video_shape)
        via quality_rules.active_rules_for_video, severity-tagged by
        quality_rules.compose_rules_text. script_templates.structure (the
        channel's house SCRIPT FORMAT, distinct from a graded law) is kept
        as an additional appended block, not dropped.

        Returns {} when grading itself could not run at all (no script, no
        client) - falsy, so a caller/test that ignores the return value keeps
        the pre-C46a "always advance" behavior. Otherwise returns
        {"needs_review": bool, "violations": [...]}. Fail-open and
        best-effort throughout: any error leaves the already-generated
        script in place and never blocks the pipeline.
        """
        try:
            import json as _json_q
            import script_quality

            video = await self._get_video(video_id)
            script = (video or {}).get("script") or ""
            if not script.strip():
                return {}

            client = getattr(self._pipeline, "anthropic", None)
            if client is None:
                return {}

            # Niche keeps grading niche-appropriate (a how-to is not punished for
            # lacking a story arc). Resolved defensively; falls back to neutral.
            niche = ""
            try:
                identity = await build_identity_context(self.tenant_id, video)
                niche = identity.niche
            except Exception:
                niche = ""

            # C46b: the real per-channel rules table replaces C46a's
            # script_templates.structure-only stopgap. Scope-matched
            # deterministically against THIS video's own shape data (never
            # LLM judgment about which gates apply — Ryan's 2026-07-19
            # ruling) via quality_rules.active_rules_for_video, using this
            # method's OWN already-patched fetch_all (see
            # tests/test_c46a_quality_critic_wiring.py's fake-DB convention)
            # rather than quality_rules.py opening a second DB surface.
            import quality_rules

            rules_text = ""
            severity_by_rule: dict = {}
            try:
                rule_rows = await fetch_all(
                    "SELECT rule_id, law, evidence, severity, applies_to "
                    "FROM quality_rules WHERE tenant_id = $1 AND active",
                    self.tenant_id,
                )
                matched = quality_rules.active_rules_for_video(video, rule_rows or [])
                rules_text, severity_by_rule = quality_rules.compose_rules_text(matched)
            except Exception:
                rules_text, severity_by_rule = "", {}

            # script_templates.structure is the channel's house FORMAT prose
            # (hook shape, segment order, pacing) — a distinct, still-useful
            # signal from the LAW/gate rows above, so it's kept as an
            # ADDITIONAL block rather than dropped: quality_rules answers
            # "what must this script clear", script_templates answers "what
            # shape should this script take". Byte-compatible with C46a's
            # own wiring test when no quality_rules rows exist yet (empty
            # rules_text + this block == exactly the old rules_text).
            try:
                tpl = await fetch_one(
                    "SELECT structure FROM script_templates WHERE tenant_id = $1 AND is_default "
                    "ORDER BY created_at DESC LIMIT 1",
                    self.tenant_id,
                )
                house_format = (tpl or {}).get("structure") or ""
                if house_format:
                    rules_text = (
                        house_format if not rules_text
                        else rules_text + "\n\n--- CHANNEL HOUSE FORMAT (structural convention, not a graded law) ---\n"
                        + house_format
                    )
            except Exception:
                pass

            scene_rows = await fetch_all(
                "SELECT scene, scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
                video_id, self.tenant_id,
            )
            scene_list = [
                {"scene": int(r["scene"]), "text": r["scene_text"] or ""}
                for r in (scene_rows or []) if (r.get("scene_text") or "").strip()
            ]
            if not scene_list:
                scene_list = [{"scene": 1, "text": script}]

            async def _regenerate_scenes():
                if regenerate is None:
                    return None
                # Modeled videos re-roll through the MODELED generator, not the
                # documentary brief_translator (which would steamroll their
                # style); the plain path's callback is run_brief_translator.
                await regenerate()
                fresh_rows = await fetch_all(
                    "SELECT scene, scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
                    video_id, self.tenant_id,
                )
                out = [
                    {"scene": int(r["scene"]), "text": r["scene_text"] or ""}
                    for r in (fresh_rows or []) if (r.get("scene_text") or "").strip()
                ]
                return out or None

            outcome = await script_quality.run_critique_and_edit(
                self.tenant_id, video_id, scene_list,
                client=client, niche=niche,
                title=video.get("video_title"),
                hook=video.get("executive_hook") or video.get("hook_script"),
                rules_text=rules_text,
                severity_by_rule=severity_by_rule,
                regenerate=_regenerate_scenes if regenerate is not None else None,
            )

            grade = outcome["critique"]
            print(f"[Script] quality critic {video_id[:8]}: {grade.verdict} "
                  f"(score {grade.score}) gates={grade.failing_gates} "
                  f"edit_rounds={outcome['edit_rounds']} regenerated={outcome['regenerated']}",
                  flush=True)

            # Capture the grade so the creator can SEE it (autopilot scorecard +
            # chat), whether or not we edited/rerolled - transparency, not a
            # black box.
            await self._record_applied_retention(
                video_id, grade, bool(outcome["edit_rounds"] or outcome["regenerated"])
            )

            if outcome["changed"]:
                new_scenes = outcome["scenes"]
                full_script = "\n\n".join(s["text"].strip() for s in new_scenes)
                await execute(
                    "DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2",
                    video_id, self.tenant_id,
                )
                for i, sc in enumerate(new_scenes, start=1):
                    await execute(
                        """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
                           VALUES ($1, $2, $3, $4, $5, 'Create', $6)""",
                        self.tenant_id, video_id, i, sc["text"].strip(),
                        video.get("video_title"), "1SM7GgM6IMuvQlz2BwM3",
                    )
                await execute(
                    "UPDATE videos SET script = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
                    full_script, video_id, self.tenant_id,
                )

            needs_review = bool(outcome["needs_review"])
            try:
                existing_validation = video.get("script_validation")
                if isinstance(existing_validation, str):
                    existing_validation = (
                        _json_q.loads(existing_validation) if existing_validation.strip() else {}
                    )
                if not isinstance(existing_validation, dict):
                    existing_validation = {}
                existing_validation["quality_critic"] = {
                    "passed": not needs_review,
                    "verdict": grade.verdict,
                    "score": grade.score,
                    "failing_gates": grade.failing_gates,
                    "violations": grade.violations,
                    "edit_rounds": outcome["edit_rounds"],
                    "regenerated": outcome["regenerated"],
                    # C46d: the per-rule pass/fail + this tenant's own
                    # severity map, so the Script Validation banner
                    # (ScriptVoiceTab) can render "rule-by-rule with
                    # severity" instead of only the flattened violations
                    # strings above. New keys only — every existing reader
                    # of this dict (tests, _record_applied_retention) keys
                    # off the fields already present, untouched.
                    "rule_verdicts": [
                        rv.model_dump() if hasattr(rv, "model_dump") else dict(rv)
                        for rv in grade.rule_verdicts
                    ],
                    "severity_by_rule": severity_by_rule,
                }
                await execute(
                    "UPDATE videos SET script_validation = $1 WHERE id = $2 AND tenant_id = $3",
                    _json_q.dumps(existing_validation), video_id, self.tenant_id,
                )
            except Exception:
                pass

            if needs_review and hold_status:
                await execute(
                    "UPDATE videos SET status = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
                    hold_status, video_id, self.tenant_id,
                )

            return {"needs_review": needs_review, "violations": grade.violations}
        except Exception as e:
            print(f"[Script] quality critic skipped for {video_id[:8]}: {str(e)[:200]}", flush=True)
            return {}

    async def _record_applied_retention(self, video_id: str, grade, regenerated: bool) -> None:
        """Persist the retention grade onto videos.applied_intelligence so the creator
        can see what the hook/retention engine did (autopilot scorecard + chat).
        Best-effort; never blocks the pipeline."""
        try:
            import json as _json
            rule_verdicts = getattr(grade, "rule_verdicts", None) or []
            rec = {
                "fired": bool(regenerated),
                "score": getattr(grade, "score", None),
                "verdict": getattr(grade, "verdict", None),
                "failing_gates": list(getattr(grade, "failing_gates", []) or []),
            }
            if rule_verdicts:
                # Only present when a rules_text pass ran (script_quality
                # C46a) - keeps the record byte-identical for callers that
                # only ever pass a plain originality.ScriptGrade.
                rec["rule_verdicts"] = [
                    rv.model_dump() if hasattr(rv, "model_dump") else dict(rv)
                    for rv in rule_verdicts
                ]
            await execute(
                "UPDATE videos SET applied_intelligence = "
                "COALESCE(applied_intelligence, '{}'::jsonb) || jsonb_build_object('retention_grade', $1::jsonb) "
                "WHERE id = $2",
                _json.dumps(rec), video_id,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[Script] record retention grade failed: {str(e)[:160]}")

    async def _telemetry_quality_critique(self, video_id: str, hold_result: dict) -> None:
        """C46a additivity call site for the static-docu writer path.

        _run_static_script_hold already runs its own hard-gate paragraph
        harness (_validate_machine_story_sentences + its bounded EDIT loop:
        grounding law, claim maps, hedge-word discipline, twist taxonomy —
        stricter than the generic critic's 5 universal gates). Re-judging or
        gating that output with the generic critic would double-critique a
        path that already has a stricter judge; per decisions.md 2026-07-19's
        additivity constraint, this call is TELEMETRY ONLY: one best-effort
        grade recorded onto applied_intelligence for visibility (so the
        creator's scorecard/chat digest sees a quality signal from every
        script path, per checklist C46a item 3), never an edit loop, never a
        status change. Fail-soft throughout — never touches the pipeline.
        """
        try:
            if not isinstance(hold_result, dict) or hold_result.get("status") == "failed":
                return
            import script_quality

            video = await self._get_video(video_id)
            script = (video or {}).get("script") or ""
            if not script.strip():
                return
            client = getattr(self._pipeline, "anthropic", None)
            if client is None:
                return
            grade = await script_quality.critique_script(
                self.tenant_id, video_id,
                {"script": script, "title": (video or {}).get("video_title")},
                client=client,
            )
            await self._record_applied_retention(video_id, grade, False)
        except Exception as e:  # noqa: BLE001
            print(f"[Script] static-docu telemetry critique skipped for {video_id[:8]}: {str(e)[:200]}", flush=True)

    async def _regen_modeled_script(self, video_id: str) -> None:
        """Re-roll a modeled script through the MODELED generator (used by the
        retention grade so a modeled video keeps its replicated style on revision)."""
        v = await self._get_video(video_id)
        if v:
            await self._run_modeled_script(video_id, v)

    @staticmethod
    def _parse_modeled_scenes(raw: str) -> list:
        """Parse modeled-script model output into [{"scene", "text"}].

        Primary format is sentinel markers (@@@SCENE n@@@), which are robust to
        quotes and newlines inside long narration — the old JSON contract broke
        on unescaped quotes in the text. Falls back to the JSON shape for any
        response that still comes back as {"scenes": [...]}. Scenes are
        renumbered sequentially from 1.
        """
        import json as _json
        import re as _re
        text = (raw or "").strip()
        if text.startswith("```"):
            # drop the opening fence line and any trailing closing fence
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        markers = list(_re.finditer(r"@@@\s*SCENE\s*\d+\s*@@@", text, _re.IGNORECASE))
        if markers:
            out: list = []
            for idx, m in enumerate(markers):
                start = m.end()
                end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
                body = text[start:end].strip()
                if body:
                    out.append({"scene": len(out) + 1, "text": body})
            return out

        # Fallback: legacy JSON contract.
        try:
            data = _json.loads(text)
        except Exception:
            return []
        raw_scenes = data.get("scenes") if isinstance(data, dict) else None
        if not isinstance(raw_scenes, list):
            return []
        out = []
        for s in raw_scenes:
            t = (s.get("text") or "").strip() if isinstance(s, dict) else ""
            if t:
                out.append({"scene": len(out) + 1, "text": t})
        return out

    async def _run_modeled_script(self, video_id: str, video: dict) -> dict:
        """Script generation for style-replicated ('Model A Video') videos.

        The brief_translator is hardwired as a documentary writer (power-doctrine
        frameworks, number-density validation) and steamrolls any style override —
        a replicated kids-animation video came out as 'The Hidden Economics of
        Compassion'. Modeled videos instead get a direct generation in the
        reference's style, structured around the modeled scene concepts, and skip
        the documentary-specific editorial validation.
        """
        bot_name = "Script Bot"
        await self._log_activity(bot_name, video_id, "started", "Writing script in the reference's style")
        current_status = video.get("status")

        import json as _json
        import story_laws
        original_dna = video.get("original_dna")
        if isinstance(original_dna, str):
            try:
                original_dna = _json.loads(original_dna)
            except Exception:
                original_dna = {}
        pack = (original_dna or {}).get("modeled_pack") or {}
        concepts = pack.get("scene_concepts") or []
        minutes = int(video.get("video_length_minutes") or 10)
        # Scene count + word target scale with length so a SHORT (1-2 min) video isn't
        # forced into a long, over-segmented script. 3+ min keep their prior values.
        default_scenes = max(2, min(8, round(minutes * 2.5)))
        target_words = max(120, minutes * 145)
        min_scenes = 3 if minutes >= 3 else 2
        concept_lines = "\n".join(
            f"{i}. {c.get('concept')}" for i, c in enumerate(concepts, start=1)
        ) or f"Structure the story into {default_scenes} natural scenes."

        research = video.get("research_payload")
        if isinstance(research, dict):
            research = _json.dumps(research)
        research_excerpt = (research or "")[:4000]

        prompt = f"""Write the complete spoken script for a video titled "{video.get('video_title')}".

{video.get('writer_guidance') or ''}

SCENE PLAN — follow these story beats in order. SPLIT any beat that moves between locations into
separate scenes, one location each:
{concept_lines}

{story_laws.SCENE_LOCATION_LAW}

{story_laws.LOCATION_TRANSIT_LAW}

{story_laws.SCRIPT_IS_SOURCE_OF_TRUTH_LAW}

Target length: about {target_words} words total, spread across the scenes.

Background material you may draw from (use only what fits the video's style and audience):
{research_excerpt}

VOICE — write every scene in the EXACT voice, tense, vocabulary and FORMAT your style
instructions above define. If they call for character DIALOGUE, write dialogue (speaker
turns like "Mum: ..." are fine); if narration, write narration; if both, both. Match their
sentence length and reading level. Do NOT default to a third-person narrator unless the
style explicitly says to — the style above wins over any default. The LOCATION header is the
ONE exception to "write only what's heard" — it is never spoken, it is stripped before voice.

FORMAT — plain text, no JSON, no markdown headings. Start each scene on its own line with
exactly this marker:
@@@SCENE n@@@
directly followed by that scene's LOCATION header (see above) as the very next line, then
that scene's spoken text on the lines after. Use the markers and nothing else to separate
scenes."""

        style_system = video.get("script_system_prompt") or ""
        # Long free-text narration used to be returned as one big JSON blob and
        # json.loads choked on unescaped quotes/newlines inside the text
        # (JSONDecodeError ~char 5298). Sentinel markers are immune to that.
        # Retry once with a stricter nudge + lower temperature before giving up.
        scenes: list = []
        for attempt in range(2):
            raw = await self._pipeline.anthropic.generate(
                prompt=prompt if attempt == 0 else (
                    prompt + "\n\nIMPORTANT: separate scenes with ONLY the "
                    "@@@SCENE n@@@ markers. Do not return JSON."
                ),
                system_prompt=style_system,
                max_tokens=16000,
                temperature=0.7 if attempt == 0 else 0.4,
            )
            scenes = self._parse_modeled_scenes(raw)
            if len(scenes) >= min_scenes:
                break
            if attempt == 0:
                await self._log_activity(bot_name, video_id, "started",
                                         "Reformatting script for clean scene breaks")
        if len(scenes) < min_scenes:
            raise Exception("Modeled script came back with too few scenes")

        # D6-3 (S3 parser leg): pull each scene's LOCATION header into its own
        # field and strip it from the spoken text (it must never reach voice/
        # TTS — see the prompt's own carve-out above). Platform-generated
        # content, no verbatim concern, so stripping is safe here (contrast
        # with the SUBMIT path in user_script.py, which never strips).
        for scene in scenes:
            location, stripped = story_laws.extract_scene_location(scene["text"])
            scene["location"] = location
            scene["text"] = stripped if location else scene["text"].strip()

        # D6-3 (S3 GATE leg): hard-fail at generation, before anything is
        # written. Defensible here — this is a fresh generation, nothing
        # downstream has consumed it yet, and it mirrors this same path's
        # existing quality-critic gate shape (needs_review, no auto-spend
        # retry). Checked BEFORE the DB writes below so a failing script
        # never reaches `scripts` or advances `videos.status` in the first
        # place — no revert needed, unlike the critic gate that runs after
        # this function returns.
        law_check = story_laws.check_scene_location_law([
            {"scene": i, "location": s.get("location"), "scene_text": s["text"]}
            for i, s in enumerate(scenes, start=1)
        ])
        if not law_check["passed"]:
            detail = "; ".join(
                f"scene {v['scene']}: {v['detail']}" for v in law_check["violations"]
            )
            await self._log_activity(
                bot_name, video_id, "failed",
                f"Story law S3 (one location per scene) failed: {detail}"[:900],
            )
            return {
                "status": "needs_review", "video_id": video_id,
                "violations": [v["detail"] for v in law_check["violations"]],
                "message": ("The script needs another look — some scenes don't hold to a "
                            "single stated location: " + detail)[:900],
            }
        if law_check["warnings"]:
            # D6-3b: cross_location_text is advisory-only, permanently (see
            # story_laws.check_scene_location_law's docstring — the S1/S3
            # conflict). Logged so it's visible, never blocks.
            warn_detail = "; ".join(
                f"scene {w['scene']}: {w['detail']}" for w in law_check["warnings"]
            )
            await self._log_activity(
                bot_name, video_id, "started",
                f"Story law S3 advisory (cross-location text, non-blocking): {warn_detail}"[:900],
            )

        # D6-4 (S1 GATE leg): cross-scene, warn-only, permanently (see
        # story_laws.check_location_transit_law's docstring — Ruling 1).
        # Runs AFTER the S3 gate so it only ever sees an S3-passing scene
        # list (every scene has a location, so the comparison is
        # meaningful); logged exactly like the S3 advisory above, never
        # blocks, never touched again after this — nothing downstream in
        # this function reads it.
        s1_check = story_laws.check_location_transit_law([
            {"scene": i, "location": s.get("location"), "scene_text": s["text"]}
            for i, s in enumerate(scenes, start=1)
        ])
        if s1_check["warnings"]:
            s1_warn_detail = "; ".join(
                f"scene {w['scene']}: {w['detail']}" for w in s1_check["warnings"]
            )
            await self._log_activity(
                bot_name, video_id, "started",
                f"Story law S1 advisory (unnarrated location change, non-blocking): {s1_warn_detail}"[:900],
            )

        full_script = "\n\n".join(s["text"].strip() for s in scenes)
        await execute(
            """UPDATE videos SET script = $1, script_validation = $2, status = $3, updated_at = now()
               WHERE id = $4 AND tenant_id = $5""",
            full_script,
            _json.dumps({"passed": True, "checks": [
                {"name": "style_replication", "passed": True,
                 "detail": "Documentary editorial checks skipped — script written in the reference video's style"}]}),
            self._skip_disabled_next(video, "ready_for_voice"),
            video_id, self.tenant_id,
        )
        await execute("DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2", video_id, self.tenant_id)
        for i, scene in enumerate(scenes, start=1):
            await execute(
                """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, location, title, script_status, voice_id)
                   VALUES ($1, $2, $3, $4, $5, $6, 'Create', $7)""",
                self.tenant_id, video_id, i, scene["text"].strip(), scene.get("location"),
                # Mark — on Kie's allowed roster. The previous id was
                # off-roster, so every TTS call burned a wasted createTask
                # before the client's fallback (which lands on Mark anyway).
                video.get("video_title"), "1SM7GgM6IMuvQlz2BwM3",
            )

        await self._log_transition(video_id, current_status, "ready_for_voice", "api")

        # Dialogue intelligence runs unattended right after every script —
        # the north-star is full automation, so format detection (performed
        # dialogue vs pure voiceover) can never be a manual step. Best-effort:
        # a tagging hiccup must not fail the script stage (manual retro
        # trigger: POST /api/videos/{id}/script/tag-dialogue).
        try:
            from dialogue_intelligence import tag_video_dialogue
            tag_result = await tag_video_dialogue(video_id, self.tenant_id)
            _logger.info("[dialogue] %s: %s", video_id, tag_result)
        except Exception as e:
            _logger.warning("[dialogue] tagging failed for %s: %s", video_id, str(e)[:200])

        from drive_workspace import sync_video_workspace_fail_soft
        await sync_video_workspace_fail_soft(video_id, self.tenant_id)
        await self._log_activity(bot_name, video_id, "completed",
                                 f"Modeled-style script complete ({len(scenes)} scenes, {len(full_script.split())} words)")
        # generation_ledger (script/storyboard ledger-gap fix, same as
        # run_script's brief-translator path): this modeled-style path spent
        # real Anthropic tokens via self._pipeline.anthropic.generate above
        # and had no ledger write either. Same flat-estimate reasoning/source
        # as run_script's write.
        from actions import SCRIPT_COST_ESTIMATE
        await record_ledger_entry(
            tenant_id=self.tenant_id, video_id=video_id, stage="script",
            model=None, units=1, unit_cost=SCRIPT_COST_ESTIMATE,
            actual_cost=SCRIPT_COST_ESTIMATE,
        )
        return {"status": "ready_for_voice", "video_id": video_id, "new_status": "ready_for_voice"}

    async def _save_machine_script_block(
        self,
        *,
        video_id: str,
        video: dict,
        roster: list[str],
        script_block: dict,
        title: str,
        voice_id: str,
    ) -> dict:
        """Persist one validated machine paragraph as its real script scene."""
        import json as _json_block

        scene = int(script_block.get("scene") or 0)
        machine = str(script_block.get("machine") or "").strip()
        paragraph = " ".join(str(script_block.get("paragraph") or "").split())
        if scene < 1 or not machine or not paragraph:
            raise ValueError("Cannot save incomplete machine script block")

        existing_rows = await fetch_all(
            "SELECT scene, scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
            video_id, self.tenant_id,
        )
        scene_texts: dict[int, str] = {}
        for row in existing_rows or []:
            try:
                row_scene = int(row.get("scene") or 0)
            except Exception:
                continue
            row_text = " ".join(str(row.get("scene_text") or "").split())
            if row_scene > 0 and row_text:
                scene_texts[row_scene] = row_text
        scene_texts[scene] = paragraph
        full_script = "\n\n".join(scene_texts[idx] for idx in sorted(scene_texts))

        existing_validation = video.get("script_validation")
        try:
            validation = (
                _json_block.loads(existing_validation)
                if isinstance(existing_validation, str) and existing_validation.strip()
                else (existing_validation or {})
            )
        except Exception:
            validation = {}
        if not isinstance(validation, dict):
            validation = {}

        prior_hold = validation.get("script_hold") if isinstance(validation.get("script_hold"), dict) else {}
        units_by_scene: dict[int, dict] = {}
        for unit in prior_hold.get("units") or []:
            if not isinstance(unit, dict):
                continue
            try:
                unit_scene = int(unit.get("scene") or 0)
            except Exception:
                continue
            if unit_scene > 0:
                units_by_scene[unit_scene] = unit
        units_by_scene[scene] = {
            "scene": scene,
            "machine": machine,
            "word_count": script_block.get("word_count"),
            "research_source": script_block.get("research_source"),
            "passed": True,
            "warnings": [],
        }
        units = [units_by_scene[idx] for idx in sorted(units_by_scene)]
        passed_scenes = {
            int(unit.get("scene") or 0)
            for unit in units
            if unit.get("passed") is True
        }
        all_passed = len(roster) > 0 and all(idx in passed_scenes for idx in range(1, len(roster) + 1))
        validation["script_hold"] = {
            "passed": all_passed,
            "in_progress": not all_passed,
            "completed_count": len(passed_scenes),
            "total_count": len(roster),
            "units": units,
        }
        blocks = validation.get("machine_script_blocks")
        if not isinstance(blocks, dict):
            blocks = {}
        saved_block = dict(script_block)
        saved_block["saved"] = True
        blocks[machine] = saved_block
        validation["machine_script_blocks"] = blocks

        new_status = None
        if all_passed:
            new_status = self._skip_disabled_next(video, "ready_for_voice")

        if new_status:
            await execute(
                """WITH updated AS (
                       UPDATE scripts
                          SET scene_text = $4, title = $5, script_status = 'Create',
                              voice_status = NULL, voice_over_url = NULL,
                              voice_duration_seconds = NULL, voice_id = $6,
                              updated_at = now()
                        WHERE tenant_id = $1 AND video_id = $2 AND scene = $3
                        RETURNING 1
                   ), inserted AS (
                       INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
                       SELECT $1, $2, $3, $4, $5, 'Create', $6
                       WHERE NOT EXISTS (SELECT 1 FROM updated)
                       RETURNING 1
                   )
                   UPDATE videos
                      SET script = $7, script_validation = $8, status = $9, updated_at = now()
                    WHERE id = $2 AND tenant_id = $1""",
                self.tenant_id, video_id, scene, paragraph, title, voice_id,
                full_script, _json_block.dumps(validation), new_status,
            )
            await self._log_transition(video_id, str(video.get("status") or ""), new_status, "api")
        else:
            await execute(
                """WITH updated AS (
                       UPDATE scripts
                          SET scene_text = $4, title = $5, script_status = 'Create',
                              voice_status = NULL, voice_over_url = NULL,
                              voice_duration_seconds = NULL, voice_id = $6,
                              updated_at = now()
                        WHERE tenant_id = $1 AND video_id = $2 AND scene = $3
                        RETURNING 1
                   ), inserted AS (
                       INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
                       SELECT $1, $2, $3, $4, $5, 'Create', $6
                       WHERE NOT EXISTS (SELECT 1 FROM updated)
                       RETURNING 1
                   )
                   UPDATE videos
                      SET script = $7, script_validation = $8, updated_at = now()
                    WHERE id = $2 AND tenant_id = $1""",
                self.tenant_id, video_id, scene, paragraph, title, voice_id,
                full_script, _json_block.dumps(validation),
            )

        # D7-2 (STORY-LAWS S6): this writes videos.script directly (a
        # machine-documentary hold, not routes/videos.py's shared
        # sync_video_script), so it needs its own call to the same
        # cast/environments staleness check.
        from routes.videos import _flag_stale_cast_and_environments
        await _flag_stale_cast_and_environments(video_id, self.tenant_id)

        saved_block["script_hold"] = validation["script_hold"]
        if new_status:
            saved_block["new_status"] = new_status
        return saved_block

    async def run_machine_script_preview(self, video_id: str, machine: str) -> dict:
        """Generate one isolated machine paragraph without touching production script rows or status."""
        await self._ensure_initialized()
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}
        await self._load_prompt_overrides(video)
        rp = video.get("research_payload") or {}
        if isinstance(rp, str):
            import json as _json_preview
            rp = _json_preview.loads(rp)
        roster = _machine_documentary_hold_roster(video)
        if not roster:
            return {"status": "failed", "error": "No locked machine roster found"}
        matched = _locked_roster_item_for_machine(roster, machine)
        if not matched:
            return {"status": "failed", "error": f"Machine is not in the locked roster: {machine}"}
        return await self._run_static_script_hold(video_id, video, roster, target_machine=matched)

    async def check_machine_script_preview_readiness(self, video_id: str, machine: str) -> dict:
        """No-spend check for whether one locked machine is ready for script preview."""
        await self._ensure_initialized()
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "ready": False, "error": "Video not found", "next_action": "select_valid_video"}
        rp = video.get("research_payload") or {}
        if isinstance(rp, str):
            import json as _json_preview_ready
            rp = _json_preview_ready.loads(rp)
        if not isinstance(rp, dict):
            return {"status": "failed", "ready": False, "error": "Research payload is missing or invalid", "next_action": "fix_research_payload"}
        roster = _machine_documentary_hold_roster(video)
        if not roster:
            return {"status": "failed", "ready": False, "error": "No locked machine roster found", "next_action": "run_or_fix_roster_research"}
        matched = _locked_roster_item_for_machine(roster, machine)
        if not matched:
            return {"status": "failed", "ready": False, "error": f"Machine is not in the locked roster: {machine}", "next_action": "select_locked_roster_machine"}
        rp = await self._load_machine_research_cards(
            video_id, rp, roster, target_machine=matched
        )
        rp = await enrich_research_payload_readiness(self.tenant_id, video_id, rp)
        scene = roster.index(matched) + 1
        card = _research_card_for_machine(rp, matched)
        if card is None:
            msg = "Script-hold requires a saved research card for every locked machine; missing: " + matched
            return {
                "status": "needs_review",
                "ready": False,
                "video_id": video_id,
                "machine": matched,
                "scene": scene,
                "summary": msg,
                "warnings": [msg],
                "next_action": "run_one_machine_research_refresh",
                "research_payload": rp,
            }
        source_package = _verified_source_package_for_machine(rp, matched)
        source_errors = _research_card_contract_warnings(
            matched,
            card,
            source_package,
            require_source_package=True,
        )
        # Self-heal stale stored verdicts: this no-spend check just computed the
        # freshest strict verdict, so persist it (validation column ONLY - never
        # card text from a read path; UPDATE-only, failure-tolerant) and patch
        # the served card.readiness in-place so the badge and the toast agree
        # within one click even if the write fails.
        await self._update_machine_research_validation(
            video_id,
            matched,
            scene,
            {
                "machine": matched,
                "passed": not source_errors,
                "warnings": source_errors,
                "revalidated_no_spend": True,
            },
        )
        card["readiness"] = {"passed": not source_errors, "warnings": list(source_errors)}
        if source_errors:
            msg = "Script preview evidence gate failed: " + matched + ": " + "; ".join(source_errors)
            return {
                "status": "needs_review",
                "ready": False,
                "video_id": video_id,
                "machine": matched,
                "scene": scene,
                "summary": msg,
                "warnings": source_errors,
                "next_action": "run_one_machine_research_refresh",
                "research_payload": rp,
            }
        return {
            "status": "completed",
            "ready": True,
            "video_id": video_id,
            "machine": matched,
            "scene": scene,
            "summary": "Machine script preview is ready.",
            "warnings": [],
            "next_action": "run_machine_script_preview",
            # Writer pass 5 wrap-up: informational only - a preview run
            # self-heals these gaps with FREE package promotes before writing.
            "script_audit_gaps": _script_starvation_gaps(card, matched),
            "self_heal_promotes_available": len(
                _script_starvation_promote_actions(card, source_package, matched)
            ),
            "research_payload": rp,
        }

    async def run_machine_script_block(self, video_id: str, machine: str) -> dict:
        """Generate and save one validated machine paragraph as script scene state."""
        await self._ensure_initialized()
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}
        await self._load_prompt_overrides(video)
        roster = _machine_documentary_hold_roster(video)
        if not roster:
            return {"status": "failed", "error": "No locked machine roster found"}
        return await self._run_static_script_hold(
            video_id,
            video,
            roster,
            target_machine=machine,
            save_target_script=True,
        )

    async def _check_scene_location_law(self, video_id: str) -> dict:
        """D6-3 — STORY-LAWS S3 GATE. Deterministic, pure-read: fetches this
        video's current scripts rows and runs story_laws.check_scene_location_law
        against them. No I/O beyond the one SELECT, no LLM call, safe to call
        read-only against ANY video at ANY time (used exactly that way for
        the D6-3 decisive test against video 686b4651, and safe to reuse for
        an on-demand check from a route without side effects)."""
        import story_laws
        rows = await fetch_all(
            "SELECT scene, location, scene_text FROM scripts WHERE video_id = $1 "
            "AND tenant_id = $2 ORDER BY scene",
            video_id, self.tenant_id,
        )
        return story_laws.check_scene_location_law([dict(r) for r in (rows or [])])

    async def _check_location_transit_law(self, video_id: str) -> dict:
        """D6-4 — STORY-LAWS S1 GATE. Same read-only, pure-read shape as
        _check_scene_location_law above (separate query, not merged with
        it, so a caller that only wants S3 doesn't pay for S1's extra scan
        and vice versa — both are cheap single SELECTs either way). Runs
        story_laws.check_location_transit_law, which is warn-only,
        permanently — see that function's docstring. Safe to call
        read-only against ANY video at ANY time, including a pre-migration
        video with every location NULL (returns no location_changes and no
        warnings — see that function's docstring for why that is the
        correct, honest answer, not a false negative)."""
        import story_laws
        rows = await fetch_all(
            "SELECT scene, location, scene_text FROM scripts WHERE video_id = $1 "
            "AND tenant_id = $2 ORDER BY scene",
            video_id, self.tenant_id,
        )
        return story_laws.check_location_transit_law([dict(r) for r in (rows or [])])

    async def run_script(self, video_id: str, progress_callback=None,
                         force_rewrite: bool = False) -> dict:
        """Generate script for a video.

        Args:
            video_id: Supabase video UUID
            force_rewrite: D3-51 — set by the chat follow-up-edit path
                (actions.make_action_step, only when the "script" verb's
                confirm card carried an actual change: cfg["edit"] and
                pending["change"] in routes/chat.py's _run_pending_action)
                to make an EXPLICIT confirmed rewrite request always take
                the real generation path below, never the "supplied script
                verbatim" shortcut. Proven live 2026-07-28 on video
                686b4651-e495-44be-baf6-97fc6dd527e9: a confirmed chat edit
                appended text to writer_guidance correctly, then run_script's
                script_source=='user_supplied' shortcut fired anyway,
                reported "completed" with cost=0, and never touched the
                scenes rows — the user's confirmed rewrite was silently
                discarded while the bot claimed success. A user_supplied
                video with no pending change (plain re-run, queue/autopilot
                pass-through) is unaffected — this only overrides the
                shortcut, it never forces a rewrite nobody asked for.

        Returns:
            Dict with status and result
        """
        async def _report(message: str):
            if progress_callback:
                try:
                    result = progress_callback(message)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

        await self._ensure_initialized()
        bot_name = "Script Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}
            await _report("Preparing the script brief…")

            current_status = video.get("status")
            if not is_at_or_past_stage(current_status, "ready_for_scripting"):
                return {"status": "failed", "error": f"Video not ready for scripting (status: {current_status})"}

            rp_for_gate = video.get("research_payload")
            import json as _json_gate
            if isinstance(rp_for_gate, str):
                try:
                    rp_for_gate = _json_gate.loads(rp_for_gate)
                except Exception:
                    rp_for_gate = {}
            if isinstance(rp_for_gate, dict):
                # Recomputed, not read back off the row — see _live_roster_gate.
                # This also fixes a quieter bug in the old fallback: it called
                # _roster_validation WITHOUT video_length_minutes, so on the one
                # path that did compute fresh, the pacing targets were derived
                # from the default runtime instead of this video's own.
                roster_gate = _live_roster_gate(video, rp_for_gate)
                if roster_gate.get("complete_title") and not roster_gate.get("passed"):
                    msg = "Fix research roster before scripting: " + "; ".join(roster_gate.get("warnings", []))
                    await self._log_activity(bot_name, video_id, "failed", msg[:900])
                    return {"status": "failed", "error": msg}

            # Creator-supplied scripts are used VERBATIM: no generation, no
            # grading, no gates (user_script.set_user_script already persisted
            # the scenes). This guard also makes re-runs and the queue/autopilot
            # step loop pass straight through the script stage.
            #
            # D3-51: `not force_rewrite` is the fix for the verbatim shortcut
            # silently eating a CONFIRMED chat follow-up edit. An explicit
            # user change must always win over "keep using what I gave you
            # before" — force_rewrite=True (set only by the follow-up-edit
            # dispatch path) skips this shortcut entirely and falls through
            # to the real generation below, which reads the just-appended
            # writer_guidance. A plain re-run with no pending change (the
            # ordinary queue/autopilot pass-through this guard exists for)
            # still takes the verbatim path exactly as before.
            if (
                (video.get("script_source") or "generated") == "user_supplied"
                and (video.get("script") or "").strip()
                and not force_rewrite
            ):
                eff_status = self._skip_disabled_next(video, "ready_for_voice")
                if not is_at_or_past_stage(current_status, eff_status):
                    await self._update_video_status(video_id, eff_status)
                    await self._log_transition(video_id, current_status, eff_status, "api")
                await self._log_activity(bot_name, video_id, "completed",
                                         "Using your supplied script verbatim")
                return {"status": eff_status, "video_id": video_id}

            # Style-replicated videos get a dedicated script path — the
            # brief_translator's documentary machinery ignores their style.
            # Jarvis: modeled videos still go through the SAME hook/retention loop as
            # every other pathway. Inject learnings first (the modeled prompt reads
            # writer_guidance), generate, then grade + maybe re-roll via the MODELED
            # generator (not the documentary brief_translator).
            if video.get("source") == "modeled" and video.get("script_system_prompt"):
                await _report("Writing the script from the modeled format…")
                await self._inject_learnings_into_writer_guidance(video_id)
                video = await self._get_video(video_id)
                result = await self._run_modeled_script(video_id, video)
                # D6-3 (S3 GATE): _run_modeled_script now checks the
                # deterministic location law BEFORE writing anything, and
                # returns needs_review without touching scripts/videos.status
                # when it fails. Short-circuit here instead of falling into
                # the LLM quality critic below — grading stale/unwritten
                # content would be a wasted paid call, and the critic has
                # nothing new to grade.
                if isinstance(result, dict) and result.get("status") == "needs_review":
                    return result
                # _run_modeled_script already advanced the video's status
                # before grading runs (it commits ready_for_voice as part of
                # its own save), so pass hold_status: if the critic still
                # flags the script needs_review after its bounded edit/reroll
                # loop, this reverts status rather than leaving an unresolved
                # script silently on ready_for_voice.
                await _report("Checking the script against quality rules…")
                grade_result = await self._grade_and_maybe_revise_script(
                    video_id, regenerate=lambda: self._regen_modeled_script(video_id),
                    hold_status=current_status,
                )
                if grade_result and grade_result.get("needs_review"):
                    violations = grade_result.get("violations") or []
                    # bot_activity.status has a hard CHECK (started/running/
                    # completed/failed) - "failed" here logs the review need,
                    # same convention _run_static_script_hold's own
                    # per-machine save already uses; the RETURN dict's
                    # "status" (a plain field, no DB constraint) is the one
                    # that actually says "needs_review".
                    review_msg = ("Quality critic still flags issues after the edit-loop bound: "
                                  + "; ".join(violations))[:900]
                    await self._log_activity(bot_name, video_id, "failed", review_msg)
                    # C-frontdoor2: the internal-log line above keeps the raw
                    # gate keys (e.g. "hook_speed") for anyone reading logs -
                    # the human-facing message translates them to plain
                    # English (script_quality.plain_english_violations) since
                    # this now actually reaches the creator (see ChatPipelineMap's
                    # needs_review banner), not just a log line.
                    import script_quality
                    human_msg = ("The script needs another look — "
                                 + "; ".join(script_quality.plain_english_violations(violations)))[:900]
                    # C46d: "message" (not just "violations") so the
                    # task-status/chat surface actually shows something —
                    # make_action_step's _run (actions.py) and routes/
                    # pipeline.py's direct /script route both already read
                    # result.get("message") as their fallback display text;
                    # before this, a needs_review result carried no
                    # "error"/"message" key at all, so the poller/chat
                    # showed a bare "completed" with nothing about why.
                    return {"status": "needs_review", "video_id": video_id,
                            "violations": violations, "message": human_msg}
                return result

            await self._log_activity(bot_name, video_id, "started", "Generating script")

            # Inject performance learnings into writer_guidance BEFORE script generation
            await self._inject_learnings_into_writer_guidance(video_id)

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            # Load idea into pipeline state from Supabase
            self._load_idea_from_video(video_id)

            # First-time-right format contract: when this video carries an
            # attached LOCKED cast (source='project'), those characters are
            # the ONLY allowed speakers. The contract is appended at the very
            # END of the writing prompt - after the topic brief - so a brief
            # that describes an instructor/cashier can never out-pull the
            # format (the Senora-Martinez failure), and required closing
            # beats (quiz recap / hook) can't be buried by a long premise.
            # Channels without a locked cast are untouched.
            try:
                cast_rows = await fetch_all(
                    "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2 "
                    "AND source = 'project' ORDER BY sort, created_at",
                    video_id, self.tenant_id,
                )
                cast_names = [r["name"] for r in (cast_rows or []) if (r.get("name") or "").strip()]
            except Exception:  # noqa: BLE001
                cast_names = []
            if cast_names:
                names = ", ".join(cast_names)
                who_narrates = cast_names[0] + (f" or {cast_names[1]}" if len(cast_names) > 1 else "")
                self._pipeline.script_allowed_speakers = cast_names
                self._pipeline.script_format_contract = (
                    "=== FINAL OUTPUT CONTRACT - THIS OVERRIDES EVERYTHING ABOVE, INCLUDING THE TOPIC BRIEF ===\n"
                    f"1. THE ONLY SPEAKERS in this script are: {names}. Write dialogue lines for NO ONE else - "
                    "no instructors, cashiers, relatives, phone voices or crowds, even when the topic brief "
                    "describes such a person. Other people may exist in the story but NEVER speak: "
                    f"{who_narrates} says out loud what they do and reports their words.\n"
                    "2. Every spoken dialogue line is exactly 'Name: spoken words' using ONLY the names above. "
                    "No stage directions, no parentheses, no asterisks, no brackets.\n"
                    "3. HARD LIMIT: no single dialogue line may exceed 30 spoken words. Each line becomes one "
                    "video clip and the clip model cannot speak more than that before the clip ends, cutting "
                    "the character off mid-sentence. Break any longer speech into several consecutive shorter "
                    "lines by the same speaker - each beat of the speech becomes its own line.\n"
                    "4. Follow the system prompt's STORY RULES and OUTPUT CONTRACT to the letter, ESPECIALLY any "
                    "required closing beats (quiz recap, next-episode hook) - a long or exciting topic brief "
                    "never excuses skipping them."
                )
            else:
                self._pipeline.script_allowed_speakers = None
                self._pipeline.script_format_contract = None

            # Blast-radius guardrail: script-hold is ONLY for static-image
            # documentary videos (DVsU-style render_mode='static_docu') that
            # already have a locked machine roster. Every other StoryEngine
            # script path keeps the existing full-script generator untouched.
            roster = _machine_documentary_hold_roster(video)
            if roster:
                await _report(
                    f"Writing one sourced section for each of {len(roster)} items…"
                )
                hold_result = await self._run_static_script_hold(video_id, video, roster)
                # C46a additivity: this path already runs its OWN hard-gate
                # harness (_validate_machine_story_sentences + its bounded
                # EDIT loop, grounding law, claim maps, hedge words - much
                # stricter than the generic critic). The generic critic must
                # never re-judge or override that harness, so it runs here
                # ONLY as telemetry: one best-effort grade recorded for
                # visibility, no edit loop, no status change.
                await self._telemetry_quality_critique(video_id, hold_result)
                return hold_result

            # Run normal global script generation for animation/narrative videos,
            # and for static docs without an explicit locked machine roster.
            await _report("Writing the script…")
            result = await self._pipeline.run_brief_translator()

            if result.get("error"):
                raise Exception(result["error"])

            # C46a quality critic: universal retention gates + this tenant's
            # rules_text, with a bounded same-draft edit loop / one reroll on
            # failure (script_quality.run_critique_and_edit). Status has NOT
            # advanced yet at this point, so a still-failing verdict simply
            # short-circuits below instead of needing to revert anything.
            await _report("Checking the script against quality rules…")
            grade_result = await self._grade_and_maybe_revise_script(video_id)
            if grade_result and grade_result.get("needs_review"):
                violations = grade_result.get("violations") or []
                review_msg = ("Quality critic still flags issues after the edit-loop bound: "
                              + "; ".join(violations))[:900]
                await self._log_activity(bot_name, video_id, "failed", review_msg)
                # C-frontdoor2: plain-English translation for the human-facing
                # message — see the modeled-path branch above for the same
                # fix and why (the internal log line above keeps the raw
                # gate keys on purpose).
                import script_quality
                human_msg = ("The script needs another look — "
                             + "; ".join(script_quality.plain_english_violations(violations)))[:900]
                # C46d: see the modeled-path branch above for why "message" is
                # attached here too (task-status/chat surfacing).
                return {"status": "needs_review", "video_id": video_id,
                        "violations": violations, "message": human_msg}

            # Static documentaries are exact-figures formats: fact-check the
            # script against the research payload and re-roll once if claims
            # can't be traced. (Advisory-only elsewhere; a GATE here.)
            if (video.get("render_mode") or "") == "static_docu":
                await self._factual_gate_static(video_id)
                # One machine / one paragraph / one view set: scene rows must be
                # unit paragraphs, not acts (the bot writes one row per act).
                await self._resplit_static_scenes(video_id)
                roster_check = await self._validate_static_script_roster(video_id)
                if roster_check.get("complete_title") and not roster_check.get("passed"):
                    raise Exception("Script roster gate failed: " + "; ".join(roster_check.get("warnings", [])))
            else:
                # D6-3b — STORY-LAWS S3 GATE for the ACT-based docu path.
                # static_docu is exempted: its "scenes" are one-machine unit
                # paragraphs (product reviews), not narrative story beats, so
                # a physical "location" per S3 isn't a meaningful concept
                # there, and _resplit_static_scenes just rewrote the rows
                # above without location awareness anyway.
                #
                # HONEST NOTE on write ordering (corrects D6-3's report,
                # which wrongly claimed "checked before any DB write" for
                # this path too — that claim is only true for the modeled
                # path in _run_modeled_script). By the time run_brief_
                # translator() returns above, skills/video-pipeline/script/
                # brief_translator/__init__.py's _write_script_records has
                # ALREADY deleted the old scripts rows and progressively
                # INSERTed the new (possibly S3-violating) ones — this gate
                # only SELECTs what is already committed. This is the SAME
                # shape the quality-critic gate immediately above already
                # has (it also runs after scenes are written; "status has
                # not advanced yet" was always about videos.status, never
                # about scripts rows) — not a new defect D6-3 introduced,
                # but D6-3's own doc/report overclaimed it as clean. On a
                # violation: delete the just-written (bad) scenes rows so
                # `scripts` doesn't keep an unreviewed, un-gated draft
                # around, and record the violation on videos.script_
                # validation (not just the bot-activity log) so it's
                # inspectable the same way the critic's needs_review is.
                # videos.status still never advances either way.
                law_check = await self._check_scene_location_law(video_id)
                if not law_check.get("passed"):
                    detail = "; ".join(
                        f"scene {v['scene']}: {v['detail']}" for v in law_check["violations"]
                    )
                    await execute(
                        "DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2",
                        video_id, self.tenant_id,
                    )
                    import json as _json_s3
                    await execute(
                        "UPDATE videos SET script_validation = $1, updated_at = now() "
                        "WHERE id = $2 AND tenant_id = $3",
                        _json_s3.dumps({"passed": False, "checks": [
                            {"name": "story_law_s3", "passed": False, "detail": detail[:2000]}]}),
                        video_id, self.tenant_id,
                    )
                    await self._log_activity(
                        bot_name, video_id, "failed",
                        f"Story law S3 (one location per scene) failed: {detail}"[:900],
                    )
                    return {
                        "status": "needs_review", "video_id": video_id,
                        "violations": [v["detail"] for v in law_check["violations"]],
                        "message": ("The script needs another look — some scenes don't hold to a "
                                    "single stated location: " + detail)[:900],
                    }
                if law_check.get("warnings"):
                    warn_detail = "; ".join(
                        f"scene {w['scene']}: {w['detail']}" for w in law_check["warnings"]
                    )
                    await self._log_activity(
                        bot_name, video_id, "started",
                        f"Story law S3 advisory (cross-location text, non-blocking): {warn_detail}"[:900],
                    )

                # D6-4 (S1 GATE leg): cross-scene, warn-only, permanently —
                # same shape as the S3 advisory just above, and only reached
                # when the S3 gate above already passed (every scene has a
                # location), so the comparison is meaningful. See
                # story_laws.check_location_transit_law's docstring.
                s1_check = await self._check_location_transit_law(video_id)
                if s1_check.get("warnings"):
                    s1_warn_detail = "; ".join(
                        f"scene {w['scene']}: {w['detail']}" for w in s1_check["warnings"]
                    )
                    await self._log_activity(
                        bot_name, video_id, "started",
                        f"Story law S1 advisory (unnarrated location change, non-blocking): {s1_warn_detail}"[:900],
                    )

            # Dialogue intelligence runs unattended after EVERY script path —
            # the modeled and user-supplied paths already had this hook, but
            # the brief-translator path (the most common one) was missing it,
            # so dialogue scripts stayed untagged and voice/clips fell back to
            # narrator-only. Best-effort: a tagging hiccup must not fail the
            # stage (manual retro trigger: POST .../script/tag-dialogue).
            try:
                await _report("Mapping speakers and dialogue…")
                from dialogue_intelligence import tag_video_dialogue, cast_character_voices
                tag_result = await tag_video_dialogue(video_id, self.tenant_id)
                if tag_result.get("dialogue_mode") == "character_dialogue":
                    await cast_character_voices(video_id, self.tenant_id)
                _logger.info("[dialogue] %s: %s", video_id, tag_result)
            except Exception as e:
                _logger.warning("[dialogue] tagging failed for %s: %s", video_id, str(e)[:200])

            new_status = result.get("new_status", "ready_for_voice")
            eff_status = self._skip_disabled_next(video, to_supabase(new_status))

            # Update Supabase
            await self._update_video_status(video_id, eff_status)
            await self._log_transition(video_id, current_status, eff_status, "api")
            await self._log_activity(bot_name, video_id, "completed", "Script generated")

            # generation_ledger (script/storyboard ledger-gap fix): the
            # brief-translator call above already spent real workspace-key
            # Anthropic tokens — this stage had NO write path into
            # generation_ledger at all before this fix, so total_cost sat at
            # its DEFAULT 0 forever for every video's script step (found
            # live on video f00ea79a: script generated + storyboard sheets
            # drawn, ledger empty, cost widget read $0.00 -> $0.00). No
            # token-usage figure is threaded back from
            # self._pipeline.run_brief_translator() today, so this reuses
            # the SAME flat SCRIPT_COST_ESTIMATE actions.py's pre-generation
            # "script" verb quote already charges — one number, one source
            # (shared.channel_profile.SCRIPT_PRICE_ESTIMATE), not a second
            # hardcoded literal drifting out of sync with the quote.
            from actions import SCRIPT_COST_ESTIMATE
            await record_ledger_entry(
                tenant_id=self.tenant_id, video_id=video_id, stage="script",
                model=None, units=1, unit_cost=SCRIPT_COST_ESTIMATE,
                actual_cost=SCRIPT_COST_ESTIMATE,
            )

            return {
                "status": to_supabase(new_status),
                "video_id": video_id,
            }

        except Exception as e:
            import traceback
            error_msg = str(e)
            tb = traceback.format_exc()
            print(f"\n{'='*60}\nPIPELINE ERROR in run_script:\n{tb}\n{'='*60}\n", flush=True)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_voice(
        self,
        video_id: str,
        scene: int = None,
        progress_callback=None,
    ) -> dict:
        """Generate voice narration for a video.

        Args:
            video_id: Supabase video UUID
            scene: Optional scene number for single-scene generation

        Returns:
            Dict with status and result
        """
        async def _report(message: str):
            if progress_callback:
                try:
                    result = progress_callback(message)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

        await self._ensure_initialized()
        bot_name = "Voice Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}
            await _report("Preparing the voice track…")

            current_status = video.get("status")
            if scene is None and not is_at_or_past_stage(current_status, "ready_for_voice"):
                return {"status": "failed", "error": f"Video not ready for voice (status: {current_status})"}

            msg = f"Generating voice (scene {scene})" if scene else "Generating voice"
            await self._log_activity(bot_name, video_id, "started", msg)

            # Load idea into pipeline state from Supabase
            self._load_idea_from_video(video_id)

            # The voice bot must know whether this is a dialogue video — the
            # narrator's text drops character lines there (the cast performs
            # them; they must never be read twice).
            self._pipeline.dialogue_mode = video.get("dialogue_mode") or ""

            # Override status to "Ready For Voice" so the bot's internal check passes.
            if self._pipeline.current_idea:
                self._pipeline.current_idea["Status"] = "Ready For Voice"

            # Set scene filter for targeted generation
            if scene is not None:
                self._pipeline.scene_filter = scene

            # Run voice generation
            await self._install_cancel_support(video_id)
            await _report("Recording narration…")
            result = await self._pipeline.run_voice_bot()
            if result.get("voice_count"):
                await _report(
                    f"Recorded {result['voice_count']} narration track(s)…"
                )

            # generation_ledger (checklist §0.3b/C08, metered in §0.3c/C09):
            # one row per run_voice() call that actually synthesized
            # something, whether it finished or was stopped mid-way — audio
            # already generated already cost money. ElevenLabs bills per
            # character, not per run (docs/cost-awareness.md), and
            # voice/run.py now reports exactly how many narration characters
            # it sent this call (total_chars) — meter on THAT instead of the
            # flat actions.VOICE_COST_ESTIMATE guess whenever it's available;
            # fall back to the flat estimate only if it's missing/zero (an
            # older bot module, or nothing actually got synthesized this
            # call despite voice_count>0, which shouldn't happen but must
            # never crash the ledger write). record_ledger_entry() is
            # fail-soft.
            if result.get("voice_count", 0) > 0:
                from actions import VOICE_COST_ESTIMATE, VOICE_PRICE_PER_1K_CHARS
                total_chars = int(result.get("total_chars") or 0)
                if total_chars > 0:
                    per_char = VOICE_PRICE_PER_1K_CHARS / 1000
                    voice_units, voice_unit_cost, voice_actual = (
                        total_chars, round(per_char, 6), round(total_chars * per_char, 2))
                else:
                    voice_units, voice_unit_cost, voice_actual = (
                        1, VOICE_COST_ESTIMATE, VOICE_COST_ESTIMATE)
                await record_ledger_entry(
                    tenant_id=self.tenant_id,
                    video_id=video_id,
                    stage="voice",
                    model="elevenlabs",
                    units=voice_units,
                    unit_cost=voice_unit_cost,
                    actual_cost=voice_actual,
                )

            if result.get("cancelled"):
                kept = result.get("voice_count", 0)
                msg = f"Stopped — kept {kept} completed voice track(s). Run Voice again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg)
                self._pipeline.scene_filter = None
                return {"status": "cancelled", "video_id": video_id, "error": msg}

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_image_prompts")

            # Update Supabase
            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Voice generated")

            # Dialogue-mode videos also get their per-segment performance
            # track (narrator + character lines) — silent plumbing, like the
            # tag-dialogue hook: best-effort, never fails the voice stage.
            if scene is None and (video.get("dialogue_mode") or "") == "character_dialogue":
                try:
                    await _report("Matching character voices to dialogue…")
                    seg_result = await self.run_dialogue_voice(video_id)
                    print(f"[dialogue-voice] {video_id}: {seg_result}", flush=True)
                except Exception as e:
                    print(f"[dialogue-voice] hook failed for {video_id}: {str(e)[:200]}", flush=True)

            return {
                "status": to_supabase(new_status),
                "video_id": video_id,
            }

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_dialogue_voice(self, video_id: str, scene: int = None, progress_callback=None) -> dict:
        """Voice every dialogue_segments entry (per-segment performance track).

        Narration segments use the scene's narrator voice; dialogue lines use
        the character's cast voice (video_characters.voice_name). Additive —
        does not touch scripts.voice_over_url or advance the video status.
        Untagged videos get the dialogue intelligence pass first (unattended
        north-star: no manual prerequisite steps).
        """
        await self._ensure_initialized()
        bot_name = "Dialogue Voice Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            if not self._pipeline.elevenlabs:
                return {"status": "failed", "error": user_facing(
                    "Voice synthesis isn't configured — add a Kie.ai or ElevenLabs key in Settings → Keys.")}

            if not video.get("dialogue_mode"):
                from dialogue_intelligence import tag_video_dialogue, cast_character_voices
                tag_result = await tag_video_dialogue(video_id, self.tenant_id)
                if tag_result.get("dialogue_mode") == "character_dialogue":
                    await cast_character_voices(video_id, self.tenant_id)
                video = await self._get_video(video_id)

            if (video.get("dialogue_mode") or "") != "character_dialogue":
                msg = "Narration-only video — no per-segment voices needed"
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id, "message": msg}

            label = f"Voicing dialogue segments (scene {scene})" if scene else "Voicing dialogue segments"
            await self._log_activity(bot_name, video_id, "started", label)
            await self._install_cancel_support(video_id)

            from dialogue_voice import synthesize_video_segments
            result = await synthesize_video_segments(
                video_id,
                self.tenant_id,
                tts=self._pipeline.elevenlabs,
                scene_filter=scene,
                progress_callback=progress_callback,
                cancel_check=self._pipeline.should_cancel,
            )

            # Self-healing sweeps: a transient ElevenLabs/network hiccup no
            # longer strands a half-voiced video for the creator to babysit -
            # failed lines are retried in up to two extra passes (already-
            # voiced lines are skipped, so sweeps are cheap and idempotent).
            sweeps = 1
            while (not result.get("cancelled")
                   and not result.get("budget_stopped")
                   and result.get("segments_failed", 0) > 0
                   and sweeps < 3):
                sweeps += 1
                await asyncio.sleep(5)
                if progress_callback:
                    try:
                        await progress_callback(
                            f"Retry pass {sweeps}: finishing {result['segments_failed']} missed line(s)…"
                        )
                    except Exception:  # noqa: BLE001
                        pass
                again = await synthesize_video_segments(
                    video_id,
                    self.tenant_id,
                    tts=self._pipeline.elevenlabs,
                    scene_filter=scene,
                    progress_callback=progress_callback,
                    cancel_check=self._pipeline.should_cancel,
                )
                made_progress = again.get("segments_voiced", 0) > 0
                result = {
                    **again,
                    "segments_voiced": result["segments_voiced"] + again.get("segments_voiced", 0),
                    "segments_skipped": result["segments_skipped"],
                    "warnings": result["warnings"] + again.get("warnings", []),
                }
                if not made_progress and result.get("segments_failed", 0) > 0:
                    break  # hard failure, stop burning retries

            if result.get("cancelled"):
                msg = (f"Stopped — kept {result['segments_voiced']} voiced segment(s). "
                       "Run again to resume.")
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg, **result}

            # Money-safety fix: a mid-batch cap refusal is a clean pause, not
            # a failure — matches the "Paused — ..." pattern every other
            # per-video spend cap uses (actions.make_autobuild_step,
            # routes/characters.py's design_characters batch).
            if result.get("budget_stopped"):
                msg = (f"Paused — voiced {result['segments_voiced']} segment(s) before this "
                       "video's spend cap would have been exceeded. Raise the cap in "
                       "Settings, then run Generate Voice again to finish the rest.")
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id, "message": msg, **result}

            still_failed = result.get("segments_failed", 0)
            if still_failed:
                msg = (f"Voiced {result['segments_voiced']} segment(s), but {still_failed} "
                       "line(s) couldn't be voiced after retries — run Generate Voice again "
                       "to finish them (voiced lines are kept).")
                await self._log_activity(bot_name, video_id, "failed", msg)
                return {"status": "failed", "video_id": video_id, "error": msg, **result}

            msg = (f"Voiced {result['segments_voiced']} segment(s) across "
                   f"{result['scenes']} scene(s)"
                   + (f", {result['segments_skipped']} already done" if result["segments_skipped"] else "")
                   + (f" — {len(result['warnings'])} warning(s)" if result["warnings"] else ""))
            for w in result["warnings"]:
                print(f"[dialogue-voice] {video_id}: ⚠ {w}", flush=True)
            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": "completed", "video_id": video_id, "message": msg, **result}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_clip_generation(
        self,
        video_id: str,
        asset_id: str = None,
        scene: int = None,
        force: bool = False,
        progress_callback=None,
        only_scenes: list = None,
        force_model_id: str = None,
        asset_ids: list = None,
        section_contract: dict = None,
    ) -> dict:
        """Generate motion clips from final pictures — one card, several
        cards, one scene, or all.

        All rungs of the trust ladder land here (tap a card / tap several
        cards / Animate this scene / Animate everything). Honors
        videos.video_model via MODEL_REGISTRY (Grok + Veo wired). Clip
        result URLs expire ~24h, so every clip downloads immediately and
        persists to Drive {video}/clips/. Additive: only a full run that
        finishes every clip advances status.

        C1 (feat/per-card-parallel-clips) adds ``asset_ids``: a list of 2+
        asset ids for a manual multi-card run (``routes/pipeline.py``'s
        "clip_manual" lane). Additive and backward-compatible — every
        existing caller keeps passing the singular ``asset_id`` (or
        neither) and sees byte-identical behavior; internally both collapse
        to the same ``_ids`` list the candidate query and the concurrency
        guard below both key off. Only one of ``asset_id``/``asset_ids``
        should be set by a caller (the route normalizes this); if both are
        somehow set, ``asset_ids`` wins.

        Concurrency safety for a multi-target run (the actual point of this
        chunk): several ``run_clip_generation`` calls — including two
        overlapping manual multi-card runs — can now be in flight on the
        SAME video at once. Every candidate this call is about to animate
        is claimed via ``clip_asset_claims`` BEFORE any paid call, and any
        id already claimed by another in-flight call is silently skipped
        (never animated twice, never double-charged) — see that module's
        docstring for why a plain in-process claim is safe here without a
        lock, and the "asset-level claim guard" comment below for exactly
        where it's applied.

        C17 (checklist §1.3 "Draft cheap, finish expensive") adds two params,
        both additive — every existing caller (the "Animate"/"animate" verb,
        the per-scene redo button) passes neither and sees byte-identical
        behavior:

        ``only_scenes`` (mirrors coverage_to_app.generate_coverage_for_video's
        C16b allowlist): a list of scene numbers to scope this run to —
        `finalize`'s entry point ("regenerate ONLY approved scenes"). Combined
        with ``force=True`` it forces exactly those scenes to redraw their
        clips regardless of whether a clip already exists (finalize must
        overwrite an approved scene's existing DRAFT clip), while every scene
        NOT in the list is never even fetched from the DB — never touched.

        ``force_model_id``: when set, EVERY row this call processes animates
        through this model_id instead of its resolved routed/override model —
        `draft_pass`'s entry point ("route ALL scenes' clips to the draft
        tier for one cheap pass"). Deliberately bypasses resolve_clip_model()
        for the run rather than writing this model into assets.routed_model/
        assets.model_override — those columns are `finalize`'s later source
        of truth for the REAL target tier, and must survive a draft pass
        completely untouched (see actions._runner_draft_pass).
        """
        await self._ensure_initialized()
        bot_name = "Clip Bot"
        import re as _re

        async def _report(msg: str):
            if progress_callback:
                try:
                    await progress_callback(msg)
                except Exception:
                    pass

        # C1: defined here (not inside the try below) so the outer except's
        # release-on-abort net always has something to check, even if the
        # exception fires before the claim step below ever runs (then it's
        # just an empty set — release() on an empty/no-op set is a no-op).
        _won_ids: set = set()

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}
            section_camera_mode = ""
            section_exact_seconds = None
            if section_contract is not None:
                animation = section_contract.get("animation")
                camera = section_contract.get("camera")
                if (
                    section_contract.get("render_mode") != "coverage"
                    or not isinstance(animation, dict)
                    or animation.get("enabled") is not True
                    or animation.get("mode") != "grok_native"
                    or not isinstance(camera, dict)
                    or camera.get("mode")
                    not in {"dialogue_coverage", "investigative_coverage"}
                    or type(section_contract.get("exact_seconds")) is not int
                    or section_contract["exact_seconds"] < 1
                ):
                    raise ValueError("Unsupported animated section clip contract")
                section_camera_mode = str(camera["mode"])
                section_exact_seconds = int(section_contract["exact_seconds"])

            from shared.channel_profile import MODEL_REGISTRY, DEFAULT_VIDEO_MODEL
            from shared.model_router import resolve_clip_model
            # LAW 3: one channel-tone hint, fetched once per run and threaded
            # into every speaking_prompt() call below — None (no-op) for a
            # channel that hasn't set channel_identity.voice_tone.
            from channel_format import get_channel_tone
            channel_tone = await get_channel_tone(self.tenant_id)
            model_id = (video.get("video_model") or "").strip() or DEFAULT_VIDEO_MODEL
            profile = MODEL_REGISTRY.get(model_id)
            # Only models with a live generation path are selectable — the
            # old dropdown silently ignored the choice and always ran Grok.
            # `wired` lives on the ModelProfile itself (single source of truth,
            # also exposed via GET /api/models) — no second hardcoded set that
            # can drift from this gate (storyengine-wiring-fix-checklist.md §0.2).
            if not profile or not profile.wired:
                return {"status": "failed", "error": user_facing(
                    f"'{model_id}' isn't available yet — pick Grok Imagine or Veo 3.1 under Advanced.")}

            # C1: unify asset_id/asset_ids into one id list. `asset_ids`
            # wins if a caller somehow sets both (route never does — see
            # docstring); a bare `asset_id` still produces a 1-element
            # list, so every downstream check below only ever has to ask
            # "_ids is None?" (untargeted run) vs "_ids has N ids?"
            # (targeted run), never juggle asset_id vs asset_ids separately.
            _ids = list(dict.fromkeys(asset_ids)) if asset_ids else ([asset_id] if asset_id else None)

            where = "video_id = $1 AND tenant_id = $2"
            params = [video_id, self.tenant_id]
            if _ids:
                # ANY($3::uuid[]) also covers the single-id case (a 1-element
                # array) — same pattern already used elsewhere in this
                # codebase (routes/chat.py, routes/media.py) for a scoped id
                # list, so this isn't new SQL shape, just applied here too.
                where += " AND id = ANY($3::uuid[])"
                params.append(_ids)
            elif scene is not None:
                where += " AND scene = $3"
                params.append(scene)
            elif only_scenes:
                # C17/finalize: scope to EXACTLY this scene list — every other
                # scene's rows are never fetched, so they can never be touched
                # by the force-redo below either (checklist §1.3).
                where += " AND scene = ANY($3::int[])"
                params.append(list(only_scenes))
            rows = await fetch_all(
                f"SELECT id, scene, image_index, image_url, drive_image_url, video_prompt, "
                f"video_clip_url, duration_seconds, sentence_text, image_prompt, assigned_dialogue, "
                f"routed_model, model_override, camera_preset_id, generation_method, "
                f"motion_gate_status "
                f"FROM assets WHERE {where} ORDER BY scene, image_index",
                *params,
            )
            candidates = [
                r for r in rows
                if (r.get("image_url") or r.get("drive_image_url"))
                and (force or not r.get("video_clip_url"))
            ]
            # FAIL CLOSED (code law, 2026-07-22): a shot the motion-prompt
            # gate blocked (motion_gate_status='blocked', migration 118) — or
            # any row that simply has no video_prompt at all — must never be
            # animated on a silent default. Skip it here, before any Grok
            # call or ledger write; the batch still proceeds for every other
            # valid shot (partial progress, never a silent full-stop).
            def _motion_blocked(r):
                return (not (r.get("video_prompt") or "").strip()
                        or (r.get("motion_gate_status") or "") == "blocked")

            blocked_rows = [r for r in candidates if _motion_blocked(r)]
            todo = [r for r in candidates if not _motion_blocked(r)]
            if blocked_rows:
                shot_labels = ", ".join(
                    f"S{r['scene']}.{r['image_index']}" for r in blocked_rows)
                # user_facing(): this is a plain warning, not a raw
                # exception — without the marker, _log_activity's
                # status=="failed" humanize_error() pass would replace the
                # shot list with a generic "Something went wrong" string.
                await self._log_activity(
                    bot_name, video_id, "failed",
                    user_facing(
                        (f"Skipped {len(blocked_rows)} shot(s) with no usable motion prompt — "
                         f"needs a human edit before animating: {shot_labels}")[:900]),
                )

            if not todo:
                msg = ("Nothing to animate — every drawable shot here is blocked at the "
                       "motion-prompt gate and needs a human edit."
                       if blocked_rows else
                       "Nothing to animate — every picture here already has a clip.")
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id, "message": msg,
                        "clips_generated": 0, "clips_failed": 0, "cost": 0.0,
                        "clips_blocked": len(blocked_rows)}

            # --- C1: asset-level claim guard (feat/per-card-parallel-clips) ---
            # Several run_clip_generation calls can now be in flight on the
            # SAME video at once — routes/pipeline.py's "clip_manual" lane
            # deliberately does NOT block a second manual run against
            # itself. That lane rule alone can't stop two overlapping calls
            # from both picking up the SAME asset id; this claim is the
            # actual guard against animating (and charging for) one asset
            # twice. Claim happens synchronously, before any paid call or
            # even the cheap prep work below, so the window where two calls
            # could both believe they own the same id is zero. Released
            # per-row the instant that row finishes (in _safe_one's finally,
            # far below) and again for the whole batch right after gather as
            # a backstop; clip_asset_claims.STALE_SECONDS is the last-resort
            # self-heal if a release is ever skipped entirely (crash).
            _todo_ids = [r["id"] for r in todo]
            _won_ids = set(clip_asset_claims.claim(self.tenant_id, video_id, _todo_ids))
            already_animating = [r for r in todo if r["id"] not in _won_ids]
            todo = [r for r in todo if r["id"] in _won_ids]
            if already_animating:
                already_labels = ", ".join(
                    f"S{r['scene']}.{r['image_index']}" for r in already_animating)
                await self._log_activity(
                    bot_name, video_id, "started",
                    user_facing(
                        (f"Skipping {len(already_animating)} shot(s) already animating in "
                         f"another run: {already_labels}")[:900]),
                )
            if not todo:
                msg = "Already animating — every requested shot here is already being generated by another in-flight run."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id, "message": msg,
                        "clips_generated": 0, "clips_failed": 0, "cost": 0.0,
                        "clips_blocked": len(blocked_rows),
                        "clips_in_progress_elsewhere": len(already_animating)}

            label = (f"clip S{todo[0]['scene']}.{todo[0]['image_index']}" if _ids and len(_ids) == 1
                     else f"scene {scene}" if scene is not None else f"{len(todo)} clips")
            await self._log_activity(bot_name, video_id, "started", f"Animating {label} ({model_id})")
            await self._install_cancel_support(video_id)
            should_cancel = self._pipeline.should_cancel

            base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")

            def _proxy_url(url: str) -> str:
                # C25a: the proxy now requires a tenant-scoped token — mint a
                # short-lived one inline (backend-to-Kie fetch, no user session
                # to forward; self.tenant_id is this job's known tenant).
                from routes.media import mint_media_token
                m = _re.search(r"[?&]id=([\w-]+)", url) or _re.search(r"/d/([\w-]+)", url)
                return f"{base}/api/media/drive/{m.group(1)}?token={mint_media_token(self.tenant_id)}" if m else url

            from storage import upload_bytes
            from clip_dialogue import (load_dialogue_lines, match_lines, match_assigned,
                                       speaking_prompt, native_speaking_prompt, motion_guard,
                                       NO_SPEECH_CLAUSE,
                                       duck_audio, download_voice, mux_voice,
                                       DIALOGUE_VOICE_LEAD_SECONDS, speech_seconds,
                                       spoken_word_count, pick_clip_duration, clip_cost_for)
            from shared.clients.image_client import CONTENT_POLICY_MARKER
            client = self._pipeline.image_client
            # Grok-imagine takes any duration 6–30s (Kie). Use every tier the
            # model profile declares so a long spoken line isn't cut at 6/10s;
            # the per-clip selector below picks the smallest tier that fits.
            durations = sorted(profile.durations) or [6]

            # D13-1 (provider-dialect adapter): which client method a shot's
            # prompt/kwargs get shaped for — Grok vs Seedance vs Veo — is now
            # provider_dialect.dialect_for_model(mid), consulted per resolved
            # per-row model inside _animate_recover below and the
            # non-speaking branch's Veo dispatch. Swapping a scene's engine
            # (resolve_clip_model()) no longer needs a picker function here —
            # see backend/provider_dialect.py.
            _vaspect = (video.get("aspect_ratio") or "16:9")
            _vres = (video.get("video_resolution") or "720p")

            # Grok takes up to 7 reference images (@image1, @image2... in the
            # prompt): @image1 = the panel, @image2 = the labeled cast sheet.
            # Same one-sheet conditioning that fixed storyboard character
            # drift; plus the video's style directive goes into every prompt
            # (clips were drifting style on weaker panels).
            sheet = (video.get("character_reference_url") or "").strip()
            style_note = (video.get("image_style_override") or "").strip()[:180]
            # Per-video choice (Ryan: the overlay is OPTIONAL — it "fucked
            # up" this video): grok_native lets Grok voice the exact
            # scripted words itself; voice_over overlays ElevenLabs lines.
            native_voices = (video.get("dialogue_audio") or "voice_over") == "grok_native"
            cast_names = ""
            cast_voice_by_name: dict = {}
            if (video.get("dialogue_mode") or "") == "character_dialogue":
                name_rows = await fetch_all(
                    "SELECT name, voice_name FROM video_characters WHERE video_id = $1 ORDER BY sort",
                    video_id)
                cast_names = ", ".join((c["name"] or "").strip() for c in name_rows if c.get("name"))
                cast_voice_by_name = {(c["name"] or "").strip().casefold(): c["voice_name"]
                                      for c in name_rows if c.get("voice_name")}
            # Option A voice lock: speaking clips get their audio re-rendered
            # in the character's pinned ElevenLabs voice (speech-to-speech
            # keeps timing, so the mouth stays synced). Since 2026-07-22 this
            # covers voice_over too, not just grok_native — the swapped take
            # then CARRIES its line (assets.carries_own_line, migration 114)
            # and the performance assembler plays the clip's own audio instead
            # of overlaying the TTS mp3. Needs the tenant's direct ElevenLabs
            # key; off without one, or via env.
            xi_key = None
            if ((video.get("dialogue_mode") or "") == "character_dialogue"
                    and os.getenv("VOICE_SWAP", "on") != "off"):
                from vault import get_secret
                xi_key = await get_secret("elevenlabs_api_key", self.tenant_id)

            # D13-1: the @image1/@image2 Grok-dialect decoration that used to
            # live in a local _decorate() here moved verbatim to
            # provider_dialect.decorate_grok_prompt — called from inside
            # _animate_recover below (grok/seedance) and the non-speaking
            # branch's Veo dispatch (which calls provider_dialect.build_call
            # directly and gets the RAW prompt back, undecorated).

            # 💬 cards speak: map this video's tagged dialogue lines to cards.
            # A tap never dead-ends — scenes whose lines aren't voiced yet get
            # their segment voices synthesized first (contract: auto-chain).
            dialogue_by_scene: dict = {}
            if (video.get("dialogue_mode") or "") == "character_dialogue":
                dialogue_by_scene = await load_dialogue_lines(video_id, self.tenant_id)
                # voice_over mode needs the segment voices to exist (auto-
                # chain); grok_native voices the lines itself — no synthesis.
                # Coverage cards keep the moment SUMMARY in sentence_text and
                # the verbatim line in assigned_dialogue, so check both — the
                # summary-only check silently skipped the chain for coverage
                # rows (and the final render needs EVERY segment voiced, so an
                # unvoiced line on any card in the scene triggers it).
                if (video.get("dialogue_audio") or "voice_over") != "grok_native":
                    def _card_lines(r):
                        return (match_lines(r.get("sentence_text"), dialogue_by_scene.get(r["scene"]))
                                or match_assigned(r.get("assigned_dialogue"), dialogue_by_scene.get(r["scene"])))
                    unvoiced_scenes = sorted({
                        r["scene"] for r in todo
                        if any(not l.get("audio_url") for l in _card_lines(r))
                    })
                    for sc in unvoiced_scenes:
                        await _report(f"Creating the voices for scene {sc} first…")
                        await self.run_dialogue_voice(video_id, scene=sc, progress_callback=progress_callback)
                    if unvoiced_scenes:
                        dialogue_by_scene = await load_dialogue_lines(video_id, self.tenant_id)

            done = failed = 0
            cost = 0.0
            total = len(todo)
            generated_artifacts: list[dict] = []
            # Clips fan out concurrently; CLIP_CONCURRENCY tunes the width
            # (Kie queues server-side — same account the coverage image gens
            # already hit concurrently).
            sem = asyncio.Semaphore(int(os.getenv("CLIP_CONCURRENCY", "6")))
            cancelled = False
            CLIP_DEADLINE = 420  # hard per-clip cap (sem already held): a stuck Grok
            # job frees its slot in ~7 min instead of holding it for the full internal
            # retry budget (~30 min). The clip is counted failed and retried next round.

            async def _gen(coro):
                return await asyncio.wait_for(coro, CLIP_DEADLINE)

            async def _animate_recover(r, image_url, core_prompt, clip_dur, row_model_id=None, task_id_out=None):
                """Generate the clip through the provider-dialect adapter
                (D13-1: provider_dialect.build_call — grok/seedance share the
                @imageN decoration, each gets its own kwarg shape); if
                Grok's content filter (failCode 430) flags the frame, redraw
                the shot with a safer wholesome framing and retry ONCE.
                Returns (clip_url_or_None, image_url_actually_used).

                ``row_model_id`` (checklist §1.2/C13): the per-row resolved
                model (see ``resolve_clip_model`` in ``_one`` below);
                defaults to the video-level ``model_id`` so any caller that
                doesn't pass one keeps the pre-C13 behavior. NEVER a Veo id
                in practice — the non-speaking branch's Veo case is
                dispatched separately below (no content-policy retry there,
                unchanged from pre-D13-1), and the speaking branch forces a
                Veo-routed row back to Grok/Seedance before reaching here."""
                row_model_id = row_model_id or model_id
                extra = [_proxy_url(sheet)] if sheet else []

                async def _call(img):
                    call = provider_dialect.build_call(
                        row_model_id,
                        provider_dialect.ClipDialectRequest(
                            core_prompt=core_prompt, image_url=img, duration=clip_dur,
                            aspect_ratio=_vaspect, resolution=_vres,
                            reference_image_urls=extra, cast_names=cast_names,
                            style_note=style_note, camera_mode=section_camera_mode,
                            camera_seconds=section_exact_seconds, task_id_out=task_id_out,
                        ),
                    )
                    fn = getattr(client, call.method)
                    if call.method == "generate_video_veo":
                        return await fn(call.prompt, **call.kwargs)
                    return await fn(img, call.prompt, **call.kwargs)

                try:
                    return (await _gen(_call(image_url)), image_url)
                except Exception as e:
                    if CONTENT_POLICY_MARKER not in str(e):
                        raise  # not a content block — let _safe_one count it failed
                    sc, idx = r["scene"], r["image_index"]
                    await _report(f"S{sc}.{idx} was flagged by the video filter — redrawing it safer…")
                    print(f"[clips] S{sc}.{idx} content-policy block — redrawing safer + retrying", flush=True)
                    try:
                        from scripts.coverage_to_app import redraw_asset_image
                        rr = await redraw_asset_image(video_id, self.tenant_id, r["id"], safe_reframe=True)
                    except Exception as re_err:
                        print(f"[clips] S{sc}.{idx} safe-redraw errored: {str(re_err)[:150]}", flush=True)
                        return None, image_url
                    if (rr or {}).get("status") != "completed":
                        return None, image_url
                    nr = await fetch_one(
                        "SELECT image_url, drive_image_url FROM assets WHERE id = $1", r["id"])
                    new_img = _proxy_url((nr or {}).get("drive_image_url")
                                         or (nr or {}).get("image_url") or image_url)
                    try:
                        return (await _gen(_call(new_img)), new_img)
                    except Exception as e2:
                        if CONTENT_POLICY_MARKER in str(e2):
                            print(f"[clips] S{sc}.{idx} still flagged after safe redraw — giving up",
                                  flush=True)
                            return None, new_img
                        raise

            async def _one(r):
                nonlocal done, failed, cost, cancelled
                async with sem:
                    if cancelled:
                        return
                    try:
                        if await should_cancel():
                            cancelled = True
                            return
                    except Exception:
                        pass
                    sc, idx = r["scene"], r["image_index"]
                    img = _proxy_url(r.get("drive_image_url") or r.get("image_url"))
                    # Per-scene model routing (checklist §1.2/C13, C14): resolve_clip_model
                    # precedence is assets.model_override (C14 — the creator's own
                    # one-tap pick in the Scenes workspace, first-precedence) ->
                    # assets.routed_model (C12, ONLY if it names a wired registry
                    # model) -> model_id (the video-level model resolved above,
                    # itself already gated wired). A NULL/unknown/unwired
                    # routed_model/model_override falls through, so any asset with no
                    # routing or override (every video before C12, or a row whose
                    # shot-plan-time routing try/except tripped) resolves to EXACTLY
                    # model_id — the same value every row got before C13.
                    #
                    # C17/draft_pass: force_model_id, when given, wins OUTRIGHT for
                    # this call only — it deliberately bypasses resolve_clip_model()
                    # (and therefore assets.model_override/routed_model) entirely, so
                    # a draft pass never reads OR writes those columns. This is what
                    # lets `finalize` later resolve the SAME row back to its real
                    # routed/override tier as if the draft pass had never happened.
                    if force_model_id and force_model_id in MODEL_REGISTRY and MODEL_REGISTRY[force_model_id].wired:
                        row_model_id = force_model_id
                    else:
                        row_model_id = resolve_clip_model(
                            r.get("routed_model"), model_id, scene_override=r.get("model_override"))
                    if row_model_id != model_id:
                        row_profile = MODEL_REGISTRY.get(row_model_id) or profile
                        row_durations = sorted(row_profile.durations) or durations
                    else:
                        row_profile, row_durations = profile, durations
                    # Fresh per-clip box (not a shared attribute on `client`) so
                    # concurrent clips never clobber each other's Kie taskId —
                    # generation_ledger traceability (checklist §0.3a / C07).
                    task_id_box: list = []
                    # In grok_native mode the coverage motion-writer is the SINGLE
                    # source of truth for what a shot says — it embeds the exact
                    # line in video_prompt and Grok voices it. Don't let the older
                    # match_lines path second-guess that: it matched a phrase in the
                    # shot's DESCRIPTION and overrode the embed, making one line play
                    # 3× while others dropped. voice_over (ElevenLabs overlay) still
                    # needs match_lines to find the line to lay over the clip.
                    vp = (r.get("video_prompt") or "").strip()
                    embedded_words = spoken_word_count(vp)
                    # voice_over line lookup: legacy cards carry the words in
                    # sentence_text (match_lines); coverage masters keep only
                    # the moment SUMMARY there — their verbatim line lives in
                    # assigned_dialogue (match_assigned). Without the second
                    # check, coverage speaking masters shipped with NO voice
                    # muxed and were sized/ducked as silent B-roll.
                    #
                    # LAW 1 (root cause, video f00ea79a scene 1): a coverage
                    # row's assigned_dialogue is the SINGLE SOURCE OF TRUTH for
                    # whether it speaks — NULL means non-speaking, period.
                    # match_lines is a substring match against sentence_text,
                    # and a reaction card's beat label ("T16 — Vanessa softens:
                    # \"Flores. Flowers. Okay. That is sweet.\"") embeds the
                    # full quoted line, so match_lines was silently promoting a
                    # silent reaction card to speaking — discarding its own
                    # motion prompt and (via the spk fallback below) handing it
                    # the SPEAKER's ElevenLabs voice instead of staying mute.
                    # match_lines only ever runs for legacy non-coverage cards
                    # now (their words live in sentence_text, per the comment
                    # above); a coverage row goes through match_assigned alone,
                    # which already returns [] when assigned_dialogue is NULL.
                    is_coverage = r.get("generation_method") == "coverage"
                    if is_coverage:
                        lines = ([] if (native_voices and vp) else
                                 [l for l in match_assigned(r.get("assigned_dialogue"), dialogue_by_scene.get(sc))
                                  if native_voices or l.get("audio_url")])
                    else:
                        lines = ([] if (native_voices and vp) else
                                 [l for l in (match_lines(r.get("sentence_text"), dialogue_by_scene.get(sc))
                                              or match_assigned(r.get("assigned_dialogue"), dialogue_by_scene.get(sc)))
                                  if native_voices or l.get("audio_url")])
                    # Speaking = a matched line, or (native) an embedded line.
                    is_speaking = bool(lines) or (native_voices and embedded_words > 0)

                    if lines:
                        # Speaking card → Grok animates the FULL SCENE with
                        # the line embedded, so the mouth performs the exact
                        # words at Grok's own pace. voice_over takes then get
                        # their audio re-rendered in the pinned cast voice via
                        # ElevenLabs speech-to-speech (the voice-lock branch
                        # below) — same timing, same mouth, consistent
                        # identity. InfiniteTalk (audio-driven talking clips)
                        # was REMOVED 2026-07-22: zero successful clips since
                        # it shipped 2026-07-03 — every task died on Kie's
                        # side (422/500/timeout) after burning up to 20
                        # minutes, then fell back here anyway.
                        clip_url = None
                        clip_cost = 0.0
                        clip_dur = None
                        effective_model_id = row_model_id
                        if not clip_url:
                            # Grok speaking path — the only speaking animator.
                            # The provider-dialect adapter has NO Veo case for
                            # a speaking shot — this leg can only ever really
                            # run Seedance (if routed there) or Grok (every
                            # other id). Before C13 this was a narrower
                            # pre-existing gap (only reachable if the whole
                            # VIDEO's own default model was Veo); C13's
                            # per-scene routing widens the surface (a shot can
                            # now be routed to Veo by purpose alone), so fix
                            # it here: force the row to the engine this leg
                            # can actually run BEFORE computing duration/cost,
                            # so model_used/ledger never claim an engine that
                            # didn't run (checklist §1.2/C13 orchestrator
                            # review — money invariant #1 applies here too).
                            if not (row_model_id.startswith("seedance")
                                    or row_model_id == DEFAULT_VIDEO_MODEL):
                                row_model_id = DEFAULT_VIDEO_MODEL
                                row_profile = MODEL_REGISTRY[DEFAULT_VIDEO_MODEL]
                                row_durations = sorted(row_profile.durations) or durations
                            effective_model_id = row_model_id
                            # A coverage master already has a WRITTEN motion
                            # prompt with its line embedded — keep that
                            # direction; generic speaking_prompt is the
                            # fallback for legacy cards.
                            if native_voices:
                                core = native_speaking_prompt(lines, r.get("sentence_text"))
                            elif vp and embedded_words > 0:
                                core = vp
                            else:
                                core = speaking_prompt(lines, tone=channel_tone)
                            # The whole spoken line has to fit inside the clip,
                            # or Grok cuts it off. native = Grok times its own
                            # speech; voice_over = the synthesized line's
                            # measured length plus its lead-in.
                            if native_voices:
                                need = speech_seconds(spoken_word_count(core))
                            else:
                                need = (sum(float(l.get("duration") or 2.0) for l in lines)
                                        + DIALOGUE_VOICE_LEAD_SECONDS)
                            clip_dur = pick_clip_duration(need, row_durations)
                            # _animate_recover shapes+decorates `core` via
                            # provider_dialect.build_call (D13-1) — no
                            # separate _decorate() call needed here anymore.
                            clip_url, img = await _animate_recover(
                                r, img, core, clip_dur, row_model_id, task_id_out=task_id_box)
                            clip_cost = clip_cost_for(row_profile.cost_per_clip, clip_dur)
                    else:
                        # Motion prompt from the video-scripts stage; a tapped
                        # card without one still animates (safe default) instead
                        # of dead-ending. The default is deliberately filler-free
                        # ("gentle/soft/subtle" are banned by the motion rules and
                        # read as screensaver motion) — a single slow push-in plus
                        # a fidelity lock to the frame.
                        prompt = (r.get("video_prompt") or "").strip() or (
                            "Slow push-in on the main subject. Keep the characters, art "
                            "style, and composition exactly as shown, and animate only "
                            "what is already in the frame.")
                        # C23 camera-preset chip (checklist §2.2): a manual pick
                        # wins outright over the auto/"earned" motion above — the
                        # whole point of the chip is letting the creator override
                        # earn-the-move. See _apply_camera_preset_override's
                        # docstring for the byte-identical-when-NULL contract.
                        prompt = _apply_camera_preset_override(prompt, r.get("camera_preset_id"))
                        # People rule (Ryan: S1.4's bird close-up grew an
                        # invented toddler — twice): cutaway cards get an
                        # absolute NO PEOPLE, every other narration card gets
                        # nobody-NEW. Decision table lives in motion_guard.
                        prompt = motion_guard(r.get("image_prompt"),
                                              r.get("sentence_text"), cast_names) + prompt
                        # LAW 2: the people-rule polices who's in frame, not
                        # whether they speak — nothing stopped a silent
                        # reaction card from mouthing words on its own. Say it
                        # explicitly for every non-speaking clip.
                        prompt = f"{prompt} {NO_SPEECH_CLAUSE}"
                        # A coverage shot carries its spoken line INSIDE the
                        # motion prompt (<Name> says ...: "line") — size the clip
                        # to exactly how long that line takes to say, so the video
                        # ENDS when the speech does and Grok has no slack to ad-lib
                        # filler (live finding: an over-long clip invents garbage
                        # past the line). A silent shot keeps the base length; a
                        # timed segment still acts as a floor.
                        spoken_secs = speech_seconds(spoken_word_count(prompt))
                        seg_dur = float(r.get("duration_seconds") or 0)
                        clip_dur = pick_clip_duration(max(spoken_secs, seg_dur), row_durations)
                        if row_model_id.startswith("veo-3.1"):
                            veo_model = client.VEO_MODEL_QUALITY if row_model_id.endswith("quality") else client.VEO_MODEL_FAST
                            # D13-1: provider_dialect.build_call's "veo"
                            # dialect returns the RAW (undecorated) prompt +
                            # the image_url=/model= kwarg shape — moved
                            # verbatim from this inline branch.
                            veo_call = provider_dialect.build_call(
                                row_model_id,
                                provider_dialect.ClipDialectRequest(
                                    core_prompt=prompt, image_url=img, duration=clip_dur,
                                    aspect_ratio=_vaspect, resolution=_vres,
                                    veo_model=veo_model, task_id_out=task_id_box,
                                ),
                            )
                            clip_url = await _gen(client.generate_video_veo(
                                veo_call.prompt, **veo_call.kwargs))
                            clip_dur = row_profile.durations[0]
                        else:
                            clip_url, img = await _animate_recover(
                                r, img, prompt, clip_dur, row_model_id, task_id_out=task_id_box)
                        clip_cost = clip_cost_for(row_profile.cost_per_clip, clip_dur)
                        # This branch has a real Veo case (above) — row_model_id
                        # always names the engine that actually ran here.
                        effective_model_id = row_model_id

                    if not clip_url:
                        failed += 1
                        # A no-clip return must leave a trail: which client
                        # class ran, what it was fed. (S1.4 failed twice in
                        # ~1.4s with zero journal output — undebuggable.)
                        print(f"[clips] S{sc}.{idx} returned no clip — "
                              f"client={type(client).__module__}.{type(client).__name__} "
                              f"speaking={is_speaking} dur={clip_dur} img={img[:90]}",
                              flush=True)
                        await _report(f"S{sc}.{idx} didn't generate ({done + failed}/{total})")
                        return
                    clip_bytes = await client.download_image(clip_url)
                    # Audio per mode: grok_native keeps Grok's full audio on
                    # speaking cards (its voices + ambience ARE the take);
                    # voice_over lays the ElevenLabs line over a quiet bed.
                    # Narration cards keep quiet ambience either way — the
                    # renderer mixes narration and music over them.
                    carries_line = False
                    clip_speech = (None, None)
                    try:
                        if is_speaking and xi_key and (native_voices or lines):
                            # Voice lock: swap Grok's invented voice for the
                            # speaker's pinned ElevenLabs voice. Same timing,
                            # same mouth, consistent identity. A swap failure
                            # ships grok_native's original take, or drops
                            # voice_over to the overlay-mux fallback below
                            # (never lose a paid clip over the polish pass).
                            spk = (r.get("assigned_dialogue") or "").split(":", 1)[0].strip()
                            if not spk and lines and not is_coverage:
                                # Legacy non-coverage cards have no
                                # assigned_dialogue — without this fallback
                                # the swap silently no-ops (mapped 2026-07-22).
                                # LAW 1: a coverage row's speaker lives ONLY in
                                # assigned_dialogue — never borrow a matched
                                # line's speaker for one, or a silent reactor's
                                # clip can inherit the SPEAKER's voice lock.
                                spk = (lines[0].get("speaker") or "").strip()
                            voice_id = cast_voice_by_name.get(spk.casefold())
                            # A Grok take can chain SEVERAL speakers' lines
                            # ("Then" chaining) — converting the whole clip
                            # with one voice puts the tail of a line in the
                            # wrong throat (La Lavandería v2). Split per turn.
                            turn_speakers = {(l.get("speaker") or "").casefold()
                                             for l in (lines or []) if l.get("speaker")}
                            if len(turn_speakers) > 1:
                                try:
                                    from clip_dialogue import swap_voice_turns
                                    clip_bytes = await swap_voice_turns(
                                        clip_bytes,
                                        [{"speaker": l.get("speaker"), "text": l.get("text") or ""}
                                         for l in lines],
                                        cast_voice_by_name, xi_key)
                                    # carries_line deliberately stays False:
                                    # a chained take converts EVERY turn, but
                                    # nothing guarantees this shot CLAIMS all
                                    # of them on the assembler's timeline — an
                                    # unclaimed line would then play twice
                                    # (clip + TTS track). Multi-speaker shots
                                    # keep the overlay path; the swap still
                                    # pins the voices under it (adversarial
                                    # review 2026-07-22 finding #3).
                                    await _report(f"S{sc}.{idx}: voices locked "
                                                  f"({len(turn_speakers)} speakers)")
                                except Exception as se:
                                    print(f"[clips] S{sc}.{idx} multi-voice swap failed "
                                          f"({str(se)[:120]}) — keeping Grok's take", flush=True)
                            elif voice_id:
                                try:
                                    from clip_dialogue import swap_voice
                                    clip_bytes = await swap_voice(clip_bytes, voice_id, xi_key)
                                    carries_line = not native_voices
                                    await _report(f"S{sc}.{idx}: voice locked ({spk})")
                                except Exception as se:
                                    print(f"[clips] S{sc}.{idx} voice swap failed "
                                          f"({str(se)[:120]}) — keeping Grok's take", flush=True)
                            else:
                                print(f"[clips] S{sc}.{idx} no pinned voice for "
                                      f"'{spk or '?'}' — voice not locked", flush=True)
                            if carries_line:
                                # Measure where the line actually sits in the
                                # take — the assembler sizes this shot's window
                                # from these bounds instead of assuming a 0.5s
                                # head (migration 114). No bounds → overlay
                                # fallback keeps today's behavior.
                                try:
                                    from clip_dialogue import measure_speech_bounds
                                    clip_speech = await measure_speech_bounds(clip_bytes)
                                    if clip_speech[0] is None:
                                        carries_line = False
                                except Exception as me:
                                    print(f"[clips] S{sc}.{idx} speech-bounds measure "
                                          f"failed ({str(me)[:120]}) — overlay fallback",
                                          flush=True)
                                    clip_speech = (None, None)
                                    carries_line = False
                        if lines and not native_voices and not carries_line:
                            voice_secs = sum(float(l.get("duration") or 2.0) for l in lines)
                            vbytes = [b for b in [await download_voice(l["audio_url"]) for l in lines] if b]
                            if vbytes:
                                lead = max(0.0, min(DIALOGUE_VOICE_LEAD_SECONDS,
                                                    float(clip_dur) - voice_secs - 0.1))
                                clip_bytes = await mux_voice(clip_bytes, vbytes,
                                                             delay_seconds=lead, bed_gain=0.2)
                            else:
                                clip_bytes = await duck_audio(clip_bytes)
                        elif not is_speaking and getattr(row_profile, "strip_audio", False):
                            # Only SILENT shots get ducked. Grok sometimes ad-libs
                            # a stray line over a B-roll insert, so we duck these
                            # HARD (to a faint room-tone bed, not dead silence) so
                            # any invented speech is inaudible. A speaking shot
                            # keeps Grok's voice at full volume — the line IS the take.
                            silent_gain = float(os.getenv("SILENT_CLIP_GAIN", "0.06"))
                            clip_bytes = await duck_audio(clip_bytes, gain=silent_gain)
                    except Exception as e:
                        print(f"[clips] S{sc}.{idx} audio mux failed, keeping raw clip: {str(e)[:150]}", flush=True)
                    drive_url = await upload_bytes(
                        clip_bytes, f"{video_id}/clips/S{sc:02d}-{idx:02d}.mp4", "video/mp4", tenant_id=self.tenant_id)
                    # carries_own_line rides the SAME statement as the clip
                    # url so a re-animate can never leave a stale marker from
                    # a dead clip's timing (assembler sizes windows from it).
                    # video_status=NULL (T5b, 2026-07-28): a prior failed
                    # attempt on this row (see _safe_one below) may have left
                    # video_status='failed' — this success write clears it in
                    # the same statement, mirroring the existing redraw path
                    # (coverage_to_app.py's picture-redraw clears it the same
                    # way when a stale clip is invalidated).
                    await execute(
                        "UPDATE assets SET video_clip_url = $1, video_duration = $2, "
                        "carries_own_line = $3, clip_speech_start = $4, "
                        "clip_speech_end = $5, video_status = NULL, updated_at = now() "
                        "WHERE id = $6",
                        drive_url, clip_dur, carries_line,
                        clip_speech[0], clip_speech[1], r["id"],
                    )
                    # model_used (checklist §1.2/C13, migration 088): which model
                    # ACTUALLY generated this clip — `effective_model_id`, NOT
                    # `row_model_id` (the routed TARGET): the two can differ
                    # (InfiniteTalk ran instead of the routed model; the
                    # speaking branch's Grok/Seedance-only leg couldn't honor
                    # a Veo route — orchestrator review). Deliberately a
                    # SEPARATE statement from the video_clip_url write above,
                    # and wrapped in its own try/except: this is a nice-to-have
                    # record, and must never risk the clip result itself
                    # (fail-soft).
                    try:
                        await execute(
                            "UPDATE assets SET model_used = $1 WHERE id = $2",
                            effective_model_id, r["id"],
                        )
                    except Exception as mu_err:  # noqa: BLE001 — never break a clip that already cost money
                        print(f"[clips] S{sc}.{idx} model_used write failed "
                              f"(clip itself succeeded): {str(mu_err)[:150]}", flush=True)
                    done += 1
                    generated_artifacts.append(
                        {
                            "asset_id": str(r["id"]),
                            "video_clip_url": drive_url,
                            "provider_model": effective_model_id,
                            "duration_seconds": str(clip_dur),
                        }
                    )
                    cost += clip_cost
                    # generation_ledger: one row per completed clip, single source
                    # of truth for videos.total_cost (checklist §0.3a / C07).
                    # unit_cost/actual_cost both resolve to clip_cost — the SAME
                    # value already computed above (row_profile.cost_per_clip);
                    # Kie never returns an actual-spend figure in the
                    # task-status payload, so there's no better "actual"
                    # than that for now. `model` is `effective_model_id`
                    # (checklist §1.2/C13 money invariant #1, tightened by the
                    # orchestrator's review) — the engine that ACTUALLY ran this
                    # clip, never the routed target when the two diverge — so a
                    # mixed-routing video's ledger prices each row by what really
                    # generated it instead of one flat video-wide price (or a
                    # false one borrowed from a model that never ran).
                    # record_ledger_entry() is fail-soft internally — never
                    # raises — so the clip result above is never at risk.
                    # [-1], not [0]: _animate_recover's content-policy redraw
                    # retry appends a SECOND task id, leaving [0] pointing at
                    # the blocked task (found 2026-07-22 recovering raw clips —
                    # the ledger cited tasks that produced nothing).
                    await record_ledger_entry(
                        tenant_id=self.tenant_id,
                        video_id=video_id,
                        stage="clip",
                        model=effective_model_id,
                        units=1,
                        unit_cost=clip_cost,
                        actual_cost=clip_cost,
                        kie_task_id=(task_id_box[-1] if task_id_box else None),
                    )
                    await _report(f"Animated S{sc}.{idx} ({done}/{total} done)")

            async def _safe_one(r):
                # One clip's failure — including a RAISED error (an SSL blip during
                # download, a Drive/DB hiccup, or a per-clip timeout) — must never
                # abort the batch. Count it, log it, move on; the additive re-run +
                # frontend auto-resume retry it next round.
                nonlocal failed
                try:
                    await _one(r)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    failed += 1
                    print(f"[clips] S{r.get('scene')}.{r.get('image_index')} isolated error: "
                          f"{type(e).__name__}: {str(e)[:150]}", flush=True)
                    # T5b (2026-07-28): persist a real failure marker so the
                    # Timeline Workbench can show "failed" honestly instead
                    # of indistinguishable-from-never-attempted (T1's
                    # finding). video_status is the right column — it's
                    # already the dedicated clip-status field (unused by any
                    # live read path today except this one and the redraw
                    # clear above), never conflicts with `status` (which
                    # means "picture done"), and is excluded from every
                    # retry-candidate query (those only check
                    # image_url/video_clip_url) — so a failed row is still
                    # picked up and retried next run exactly as before.
                    # Wrapped in its own try/except: a marker-write failure
                    # must never mask the real error this branch already
                    # caught, or break the batch for the other rows.
                    try:
                        await execute(
                            "UPDATE assets SET video_status = $1, updated_at = now() WHERE id = $2",
                            "failed", r["id"],
                        )
                    except Exception as marker_err:  # noqa: BLE001
                        print(f"[clips] S{r.get('scene')}.{r.get('image_index')} "
                              f"failure-marker write failed: {str(marker_err)[:150]}", flush=True)
                    try:
                        await _report(f"S{r.get('scene')}.{r.get('image_index')} hit an error ({done + failed}/{total})")
                    except Exception:
                        pass
                finally:
                    # C1: release THIS row's asset-level claim the instant its
                    # own work finishes (success, failure, or cancellation) —
                    # not at the end of the whole batch — so an overlapping
                    # run can pick it up again as soon as possible.
                    clip_asset_claims.release(self.tenant_id, video_id, [r["id"]])

            try:
                await asyncio.gather(*[_safe_one(r) for r in todo])
            finally:
                # Backstop: _safe_one already released every row above; this
                # is a no-op in the normal case. Only matters if something
                # aborts the gather itself before every _safe_one runs.
                clip_asset_claims.release(self.tenant_id, video_id, _won_ids)

            if cancelled:
                msg = f"Stopped — kept {done} finished clip(s). Animate again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg, cost=cost)
                return {"status": "cancelled", "video_id": video_id, "error": msg,
                        "clips_generated": done, "clips_failed": failed, "cost": cost}

            # Full untargeted run with everything clipped → stage complete.
            # `_ids is None` (not `asset_id is None`) so a C1 multi-card
            # manual run (asset_ids set, asset_id left None) is correctly
            # excluded here too — same targeted-run treatment the original
            # single asset_id path always got.
            if _ids is None and scene is None and failed == 0:
                remaining = await fetch_one(
                    "SELECT COUNT(*) AS n FROM assets WHERE video_id = $1 AND tenant_id = $2 "
                    "AND (image_url IS NOT NULL OR drive_image_url IS NOT NULL) AND video_clip_url IS NULL",
                    video_id, self.tenant_id,
                )
                if not (remaining or {}).get("n") and not is_at_or_past_stage(video.get("status"), "ready_for_thumbnail"):
                    await self._update_video_status(video_id, "ready_for_thumbnail")
                    await self._log_transition(video_id, video.get("status"), "ready_for_thumbnail", "api")

            # Auto-stitch the scene(s) this run touched once they're FULLY animated,
            # so the creator can watch the whole scene (and the final render concats
            # these). A single re-animate re-stitches just its scene; a bulk run
            # stitches every now-complete scene. Best-effort — never fails the clip task.
            try:
                if _ids is not None:
                    if len(_ids) == 1:
                        arow = await fetch_one("SELECT scene FROM assets WHERE id = $1", _ids[0])
                        consider = [arow["scene"]] if arow and arow.get("scene") is not None else []
                    else:
                        # C1 multi-card run: scope to the DISTINCT scenes the
                        # requested ids actually touch, not the whole video.
                        srows = await fetch_all(
                            "SELECT DISTINCT scene FROM assets WHERE id = ANY($1::uuid[]) "
                            "AND scene IS NOT NULL", _ids)
                        consider = [r["scene"] for r in srows]
                elif scene is not None:
                    consider = [scene]
                else:
                    srows = await fetch_all(
                        "SELECT DISTINCT scene FROM assets WHERE video_id = $1 AND tenant_id = $2 "
                        "AND scene IS NOT NULL", video_id, self.tenant_id)
                    consider = [r["scene"] for r in srows]
                if consider:
                    from render_stitch import stitch_video
                    # Dialogue voice_over scenes preview via the performance-
                    # track assembler (segment audio + timed muted shots) so
                    # the preview sounds like the final render.
                    #
                    # FAIL CLOSED (code law, 2026-07-22 — "the prompt is the
                    # prompt; we can't be downgrading prompts under
                    # automation," same rule applied to render quality):
                    # plain stitch is a REAL quality downgrade (no dialogue
                    # timing, no lip-sync), so an assembly failure no longer
                    # auto-runs it. Default: stop, log the failure, leave
                    # this scene's preview stale. SE_ALLOW_FALLBACK_STITCH=1
                    # is the explicit opt-in that restores the old
                    # auto-fallback behavior for a human who's consciously
                    # chosen it (0fb33de6's original fallback + its
                    # bot_activity warning both still exist, just gated).
                    use_perform = (
                        (video.get("dialogue_mode") or "") == "character_dialogue"
                        and (video.get("dialogue_audio") or "voice_over") != "grok_native")
                    allow_fallback_stitch = os.getenv("SE_ALLOW_FALLBACK_STITCH", "0") == "1"
                    for sc in consider:
                        comp = await fetch_one(
                            "SELECT COUNT(*) AS pics, COUNT(video_clip_url) AS clips FROM assets "
                            "WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 "
                            "AND (image_url IS NOT NULL OR drive_image_url IS NOT NULL)",
                            video_id, self.tenant_id, sc)
                        if comp and comp["pics"] > 0 and comp["clips"] == comp["pics"]:
                            try:
                                scene_url = None
                                assembly_blocked = False
                                if use_perform:
                                    try:
                                        from render_perform import assemble_scene
                                        pres = await assemble_scene(video_id, self.tenant_id, sc)
                                        scene_url = pres["scene_video_url"]
                                        print(f"[stitch] scene {sc} performance-assembled "
                                              f"({pres['shots']} shots, {pres['duration_seconds']}s)", flush=True)
                                    except Exception as pe:
                                        assembly_blocked = not allow_fallback_stitch
                                        print(f"[stitch] scene {sc} performance assembly failed "
                                              f"({str(pe)[:150]}) — "
                                              + ("falling back to plain stitch "
                                                 "(SE_ALLOW_FALLBACK_STITCH=1)" if allow_fallback_stitch
                                                 else "BLOCKED, no auto-fallback stitch "
                                                 "(set SE_ALLOW_FALLBACK_STITCH=1 to allow it)"),
                                              flush=True)
                                        # A silent downgrade must never be silent again: the
                                        # performance track carries dialogue timing/lip-sync,
                                        # plain stitch does not — surface the quality drop (or
                                        # the block) on the visible bot_activity feed, not just
                                        # stdout.
                                        # user_facing(): a plain warning, not a raw exception —
                                        # without the marker, _log_activity's status=="failed"
                                        # humanize_error() pass replaces this with a generic
                                        # "Something went wrong" string, losing the scene number
                                        # and the fallback-vs-blocked distinction.
                                        await self._log_activity(
                                            "Render Bot", video_id, "failed",
                                            user_facing(
                                                f"Scene {sc}: performance-track assembly failed — "
                                                + (f"fell back to plain stitch (lower quality, no "
                                                   f"dialogue timing/lip sync): {str(pe)[:300]}"
                                                   if allow_fallback_stitch else
                                                   f"blocked, needs a human decision (no auto-fallback "
                                                   f"to plain stitch — set SE_ALLOW_FALLBACK_STITCH=1 to "
                                                   f"allow the lower-quality stitch): {str(pe)[:300]}")))
                                if assembly_blocked:
                                    continue
                                if not scene_url:
                                    res = await stitch_video(video_id, self.tenant_id, scene=sc)
                                    scene_url = res["final_video_url"]
                                    print(f"[stitch] scene {sc} auto-stitched ({res['clip_count']} clips)", flush=True)
                                await execute(
                                    "UPDATE scripts SET scene_video_url = $1, updated_at = now() "
                                    "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
                                    scene_url, video_id, sc, self.tenant_id)
                            except Exception as se:
                                print(f"[stitch] scene {sc} auto-stitch skipped: {str(se)[:150]}", flush=True)
            except Exception as e:
                print(f"[stitch] auto-stitch scan failed: {str(e)[:150]}", flush=True)

            msg = (f"Animated {done} clip(s) (${cost:.2f})"
                   + (f" — {failed} failed, tap them to retry" if failed else "")
                   + (f" — {len(blocked_rows)} blocked at the motion gate, needs a human edit"
                      if blocked_rows else "")
                   + (f" — {len(already_animating)} already animating in another run"
                      if already_animating else ""))
            await self._log_activity(bot_name, video_id, "completed" if not failed else "completed", msg, cost=cost)
            return {"status": "completed" if done or not failed else "failed",
                    "video_id": video_id, "message": msg,
                    "clips_generated": done, "clips_failed": failed, "cost": cost,
                    "clips_blocked": len(blocked_rows),
                    "clips_in_progress_elsewhere": len(already_animating),
                    "requested_asset_ids": list(_ids or []),
                    "generated_asset_ids": [
                        row["asset_id"] for row in generated_artifacts
                    ],
                    "generated_artifacts": generated_artifacts,
                    "error": msg if failed and not done else None}

        except Exception as e:
            # C1 backstop: an exception ANYWHERE between the claim step and
            # the gather's own try/finally (e.g. dialogue-voice setup,
            # _install_cancel_support) would otherwise leave `_won_ids`
            # claimed until clip_asset_claims' 10-minute stale sweep — release
            # them now instead. release() is itself safe/idempotent (already-
            # released ids are a no-op), so this can never double-free or
            # mask the real error below.
            if _won_ids:
                try:
                    clip_asset_claims.release(self.tenant_id, video_id, _won_ids)
                except Exception:
                    pass
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_split(self, video_id: str) -> dict:
        """Split scene text into timed sentence segments.

        Uses the deterministic splitter with voice duration for accurate WPS.
        Creates asset records with sentence_text, duration, and timing.
        No API calls — pure Python, fast and free.

        Args:
            video_id: Supabase video UUID

        Returns:
            Dict with status, scenes_split, total_segments
        """
        bot_name = "Sentence Splitter"

        try:
            # Import the deterministic splitter
            from shared.clients.deterministic_splitter import segment_scene_deterministic

            # Load scripts with voice for this video
            scripts = await fetch_all(
                "SELECT id, scene, scene_text, voice_over_url, voice_duration_seconds "
                "FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
                "ORDER BY scene",
                video_id, self.tenant_id,
            )

            if not scripts:
                return {"status": "failed", "error": "No scripts found for this video"}

            # Get the video title for asset records
            video = await fetch_one(
                "SELECT video_title FROM videos WHERE id = $1 AND tenant_id = $2",
                video_id, self.tenant_id,
            )
            video_title = video.get("video_title", "") if video else ""

            total_segments = 0
            scenes_split = 0

            for script in scripts:
                scene_num = script.get("scene")
                scene_text = script.get("scene_text")
                voice_duration = script.get("voice_duration_seconds")

                if not scene_text or not scene_text.strip():
                    continue

                # Convert voice_duration to float if present
                if voice_duration is not None:
                    voice_duration = float(voice_duration)

                # Run the deterministic splitter
                segments = segment_scene_deterministic(scene_text, voice_duration)

                if not segments:
                    continue

                # Delete existing assets that don't have images yet (safe re-split)
                # Preserve assets with generated images to avoid data loss
                await execute(
                    "DELETE FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3 "
                    "AND (image_url IS NULL OR image_url = '')",
                    video_id, scene_num, self.tenant_id,
                )
                # Check if scene still has assets with images (skip if so)
                existing = await fetch_one(
                    "SELECT COUNT(*) as cnt FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
                    video_id, scene_num, self.tenant_id,
                )
                if existing and existing.get("cnt", 0) > 0:
                    # Scene has assets with images — skip to avoid duplicates
                    continue

                # Insert new asset records for each segment
                for seg in segments:
                    await execute(
                        """INSERT INTO assets (
                            tenant_id, video_id, video_title, scene,
                            image_index, sentence_index, sentence_text,
                            duration_seconds, status
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                        self.tenant_id, video_id, video_title, scene_num,
                        seg['segment_index'], seg['segment_index'], seg['text'],
                        seg['duration'], 'pending',
                    )

                total_segments += len(segments)
                scenes_split += 1

            await self._log_activity(
                bot_name, video_id, "completed",
                f"Split {total_segments} segments across {scenes_split} scenes",
            )

            return {
                "status": "completed",
                "scenes_split": scenes_split,
                "total_segments": total_segments,
            }

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_next_step(self, video_id: str, user_intent: str = None) -> dict:
        """Run the next pipeline step for a video.

        If CLAUDE_ORCHESTRATION is enabled for this tenant, uses Claude to
        decide which skill to invoke. Otherwise falls back to the status map.

        Args:
            video_id: Supabase video UUID
            user_intent: Optional natural language from user

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()

        # Feature flag: Claude orchestration
        use_claude = await self._is_claude_orchestration_enabled()

        if use_claude:
            return await self._run_next_step_claude(video_id, user_intent)
        else:
            return await self._run_next_step_status_map(video_id)

    async def _is_claude_orchestration_enabled(self) -> bool:
        """Check if Claude orchestration is enabled for this tenant."""
        try:
            from vault import get_secret
            flag = await get_secret("claude_orchestration", self.tenant_id)
            return flag and flag.lower() in ("true", "1", "yes", "on")
        except Exception:
            return False

    async def _run_next_step_claude(self, video_id: str, user_intent: str = None) -> dict:
        """Claude-driven next step decision."""
        try:
            from claude_orchestrator import ClaudeOrchestrator

            orchestrator = ClaudeOrchestrator(self.tenant_id)
            decision = await orchestrator.decide(video_id, user_intent=user_intent)

            if decision.confidence < ClaudeOrchestrator.CONFIDENCE_THRESHOLD:
                return {
                    "status": "needs_input",
                    "decision": decision.model_dump(),
                    "message": f"Low confidence ({decision.confidence:.0%}). {decision.reasoning}",
                    "alternatives": decision.alternatives,
                }

            result = await orchestrator.execute(decision, video_id, executor=self)
            return {
                "status": "completed" if result.success else "failed",
                "decision": decision.model_dump(),
                "result": result.execution_result,
                "error": result.error,
            }
        except Exception as e:
            # Fallback to status map on any failure
            print(f"[orchestrator] Claude orchestration failed: {e}, falling back to status map")
            return await self._run_next_step_status_map(video_id)

    # Statuses that require explicit user approval before running the next stage.
    # "Run Next Step" will NOT auto-advance past these — user must approve in the UI.
    APPROVAL_GATE_STATUSES = {
        "ready_for_voice": "Script & Voice needs approval before proceeding. Generate voice for all scenes, then approve.",
        "ready_for_images": "Visuals need approval before proceeding. Go to the Storyboard & Visuals tab to review and approve.",
        "ready_for_thumbnail": "Thumbnail needs approval before proceeding. Go to the Thumbnail tab to review and approve.",
    }

    async def _run_next_step_status_map(self, video_id: str) -> dict:
        """Original status-driven next step (fallback).

        Runs ONE stage and stops. Respects approval gates — certain statuses
        require explicit user approval before advancing.
        """
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}

        current_status = video.get("status")

        # Check approval gates — block auto-advance at these statuses
        gate_message = self.APPROVAL_GATE_STATUSES.get(current_status)
        if gate_message:
            # C55 (P4.2-f): this is the ONLY place a needs_approval stop is
            # produced, so it is the single seam every _run_full_pipeline
            # loop (routes/autopilot.py, routes/queue.py) already hits —
            # no new scheduler needed. Full-auto gets ONE chance, right
            # here, to continue instead of parking.
            continuation = await self._full_auto_continue_past_gate(video_id, video, current_status)
            if continuation is not None:
                return continuation
            return {
                "status": "needs_approval",
                "message": gate_message,
            }

        # SFX guard, OUTER layer (status_map.render_path_plays_sfx — see
        # run_render's dispatch comment): there's no approval gate on
        # ready_for_sound_design/ready_for_sound_effects, so a video whose
        # render path can never play sound effects gets a fast, specific skip
        # here instead of even reaching the handler dispatch below — this is
        # UX polish (a precise "why" for a video PARKED at this status,
        # written before this guard existed) on top of the INNER backstop in
        # run_sound_prompts/run_sound_effects themselves (_skip_sound_stage's
        # docstring), which is what actually makes "no paid sound generation
        # for a blocked render path" true for every caller, not just this one.
        if current_status in ("ready_for_sound_design", "ready_for_sound_effects") and not render_path_plays_sfx(video):
            natural_next = get_next_status_supabase(current_status)
            return await self._skip_sound_stage(video_id, video, current_status, natural_next)

        # Map status to handler
        handlers = {
            "idea_logged": self.run_research,
            "approved": self.run_research,
            "ready_for_scripting": self.run_script,
            # Static documentaries route their image stage to run_coverage_stage,
            # whose static branch creates the verified aircraft view set; the legacy
            # prompt bot must never run for them.
            "ready_for_image_prompts": (
                self.run_coverage_stage
                if (video.get("render_mode") or "") == "static_docu"
                else self.run_prompts),
            # GOAL v2 Phase 0: the image stages now draw via the unified coverage path
            # (run_coverage_stage), not the old 3x3 grid. Coverage does prompts+images in
            # one paid draw and advances to ready_for_images, so all three map to it.
            "ready_for_storyboards": self.run_coverage_stage,
            "ready_for_storyboard_images": self.run_coverage_stage,
            "ready_for_storyboard_extraction": self.run_coverage_stage,
            "ready_for_sound_design": self.run_sound_prompts,
            "ready_for_sound_effects": self.run_sound_effects,
            "ready_for_video_scripts": self.run_video_scripts,
            "ready_for_video_generation": self.run_video_generation,
            "ready_to_render": self.run_render,
            "rendered": self.run_upload,
        }

        handler = handlers.get(current_status)
        if not handler:
            return {
                "status": "idle",
                "message": f"No action available for status: {current_status}",
            }

        return await handler(video_id)

    # --- Full-auto continuation past an approval gate (C55, P4.2-f) -------------
    # dial=full_auto is supposed to proceed through finalize+upload UNLESS the
    # kill switch is tripped or the weekly cap is breached. Two stop-points
    # need this, both hit by the SAME pre-existing loops (routes/autopilot.py's
    # and routes/queue.py's `_run_full_pipeline`, which already call
    # run_next_step in a for-cycle) — no new scheduler:
    #   1. The needs_approval stop `_run_next_step_status_map` produces at the
    #      three APPROVAL_GATE_STATUSES — handled right here via
    #      `_full_auto_continue_past_gate`, called from that method.
    #   2. The 'rendered' status, which those two loops treat as terminal
    #      BEFORE ever calling run_next_step again (so run_upload is never
    #      reached even for auto_draft today) — handled by the loops calling
    #      the public `full_auto_may_continue` directly before honoring their
    #      terminal-status break, since that stop lives outside this class.
    #
    # Scope is autopilot-launched videos ONLY: videos.source starts with
    # 'autopilot' — 'autopilot_<channel>' for a candidate launch
    # (routes/autopilot.py::_do_launch_candidate) or 'autopilot_queue' for an
    # autopilot-drained queue item (routes/queue.py::auto_produce_next, tagged
    # distinctly from a human's manual '.../queue/{id}/launch' click, which
    # keeps plain 'queue' — see routes/queue.py for why the two needed to be
    # told apart). A human-launched video's source NEVER matches this prefix,
    # so it always stops at the gate, at any dial_level, exactly as today.
    _FULL_AUTO_SOURCE_PREFIX = "autopilot"

    async def full_auto_may_continue(self, video_id: str, video: dict, checkpoint: str) -> bool:
        """The ONE eligibility check for continuing an autopilot-launched
        build past ANY stop-point full-auto is meant to sail through —
        the three APPROVAL_GATE_STATUSES gates below via
        `_full_auto_continue_past_gate`, AND the 'rendered' stop
        routes/autopilot.py's and routes/queue.py's `_run_full_pipeline`
        loops treat as terminal today (upload is otherwise a human-click-only
        step exactly like the approval gates in spirit — it's just
        implemented as a loop-level terminal-status set instead of
        APPROVAL_GATE_STATUSES, so it needs the SAME check, called from the
        loop instead of from here). Public (no leading underscore) because
        those two loops live outside this class.

        True iff ALL of:
          1. video.source starts with 'autopilot' (scope — see the class
             comment above `_FULL_AUTO_SOURCE_PREFIX`). A human-launched
             video's source never matches, so it always returns False here.
          2. dial_level == 'full_auto' EXACTLY (auto_draft/propose_only never
             continue past a checkpoint — unchanged from before this chunk).
          3. kill_switch_tripped_at IS NULL.
          4. weekly_budget_cap IS NOT NULL — C54b's runtime demotion: an
             elevated dial with no cap is treated as NOT full_auto here too
             (never a free pass just because the writer-side invariant was
             somehow bypassed).
          5. check_weekly_budget() says ok. A breach trips the kill switch
             (C54's law — never a silent pause) and this returns False, so
             the video parks at the checkpoint exactly like a normal
             needs_approval/terminal stop; nothing already generated is
             rolled back.

        The dial is re-read fresh on every call (every checkpoint, every
        tick) — never frozen at launch — so turning the dial down mid-build
        takes effect at the very next checkpoint the build reaches.

        Logs ONE bot_activity attribution row (contract item 4) whenever it
        returns True — under a bot_name that can never be mistaken for a
        human approval, mirroring routes/videos.py::advance_video's
        stage_transitions.triggered_by='user' (the existing "who approved"
        record for the images/thumbnail gates)."""
        source = str(video.get("source") or "")
        if not source.startswith(self._FULL_AUTO_SOURCE_PREFIX):
            return False

        from autopilot_dial import check_weekly_budget, get_autopilot_dial, trip_kill_switch

        try:
            dial = await get_autopilot_dial(self.tenant_id)
        except Exception:
            _logger.exception(
                "[FullAuto] Tenant %s: dial read failed — stopping at %s",
                str(self.tenant_id)[:8], checkpoint)
            return False

        if dial.dial_level != "full_auto":
            return False
        if dial.kill_switch_tripped_at is not None:
            return False
        if dial.weekly_budget_cap is None:
            _logger.warning(
                "[FullAuto] Tenant %s: dial_level=full_auto but no weekly_budget_cap "
                "set — config anomaly, treating as NOT full_auto (stopping at %s)",
                str(self.tenant_id)[:8], checkpoint)
            return False

        try:
            ok, spent, cap = await check_weekly_budget(self.tenant_id)
        except Exception:
            _logger.exception(
                "[FullAuto] Tenant %s: budget check failed — stopping at %s",
                str(self.tenant_id)[:8], checkpoint)
            return False
        if not ok:
            reason = f"Weekly budget cap ${cap:.2f} reached (spent ${spent:.2f})"
            await trip_kill_switch(self.tenant_id, reason)
            _logger.warning(
                "[FullAuto] Tenant %s: %s — stopped at %s", str(self.tenant_id)[:8], reason, checkpoint)
            return False

        await self._log_activity(
            "autopilot_full_auto", video_id, "completed",
            f"Full-auto continued past {checkpoint} for "
            f"{video.get('video_title') or video_id}",
        )
        return True

    async def _full_auto_continue_past_gate(
        self, video_id: str, video: dict, gate_status: str
    ) -> Optional[dict]:
        """Returns a run_next_step-shaped dict (so the caller's loop just
        keeps going) when full-auto legitimately continues past this
        APPROVAL_GATE_STATUSES gate; None means "stop at the gate exactly
        like today" (see `full_auto_may_continue` for the eligibility
        contract this defers to)."""
        if not await self.full_auto_may_continue(video_id, video, gate_status):
            return None
        return await self._full_auto_pass_gate(video_id, gate_status, video)

    async def _full_auto_pass_gate(self, video_id: str, gate_status: str, video: dict) -> dict:
        """The gate-specific action a human would otherwise have to trigger —
        mirrors the real human path for each gate exactly, never a parallel
        status machine:

          - ready_for_voice: a human clicks "Generate Voice", which calls
            run_voice() — run_voice ADVANCES THE STATUS ITSELF on success
            (to ready_for_image_prompts or wherever the video's reduced
            stage plan reroutes it). Full-auto does the identical call.
          - ready_for_thumbnail: a human clicks "Generate Thumbnail"
            (run_thumbnail — deliberately does NOT advance, so Regenerate
            keeps working) then "Approve & Advance". Mirrored as
            run_thumbnail (skip-if-already-generated, same as the human
            path) followed by the same advance as ready_for_images below.
          - ready_for_images: the human's only remaining action is
            "Approve & Advance" (routes/videos.py::advance_video). Mirrored
            here via the SAME status-advance chokepoint every stage handler
            already uses (self._update_video_status, which honors a reduced
            pipeline_stages plan) plus a stage_transitions row.
        """
        if gate_status == "ready_for_voice":
            return await self.run_voice(video_id)

        if gate_status == "ready_for_thumbnail":
            if not (video.get("thumbnail_url") or "").strip():
                r = await self.run_thumbnail(video_id)
                if r.get("status") == "failed":
                    return r

        next_status = get_next_status_supabase(gate_status)
        if not next_status:
            return {"status": "idle", "message": f"No next stage after {gate_status}."}
        await self._update_video_status(video_id, next_status, video)
        await self._log_transition(
            video_id, gate_status, next_status, triggered_by="autopilot_full_auto")
        return {"status": next_status, "video_id": video_id}

    # --- Unified live image path (GOAL v2 Phase 0) ------------------------------
    # The coverage flow (scripts/coverage_to_app.py) is the single live image
    # generator. These thin wrappers let the co-pilot dock reach it through the
    # normal executor dispatch instead of the old 3x3 grid path (run_prompts/
    # run_images, run_storyboard_prompts/run_storyboard_images). They do NOT change
    # video.status (coverage doesn't), so they are safe for one-off co-pilot actions.
    # NOTE: the run_next_step status map above still routes the image STAGES to the
    # old grid handlers; swapping those to coverage needs status-advance handling +
    # a FINISH/autopilot test and is a follow-up (see HANDOFF-REPORT).
    async def run_coverage_images(self, video_id: str, scene: int = None) -> dict:
        """Draw the real per-shot, multi-angle pictures for a scene (or all scenes)
        via coverage — the live image path. Replaces the old grid run_prompts+run_images.
        STATIC-DOCU videos take a verified aircraft view set per segment instead, so route them
        to the static path (scene-scoped when a scene is given — lets a review-gate
        re-roll fix ONE segment without re-rolling the others)."""
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}
        # Money gate (voicefix): image generation must never run on a video
        # whose scenes have no narration. This is the modern, single live
        # image path — chat's "images" verb (actions.py ACTIONS["images"]),
        # the MCP `images` tool, and ClaudeOrchestrator's autonomous "images"
        # skill dispatch (claude_orchestrator.py skill_to_method) ALL
        # converge here — it replaced the old run_prompts/run_images 3x3-grid
        # handlers (which DO have this same check) without carrying the
        # check over. That gap is exactly how video 146242df (tenant tgb29,
        # 0/3 scenes voiced) got billed $1.50 of real image spend three times
        # after voice silently failed and (pre-fix) advanced status anyway.
        # Mirrors _check_voice_exists's use in run_images/run_prompts.
        if not video.get("skip_voice"):
            all_voiced, total, voiced = await self._check_voice_exists(video_id, scene=scene)
            if not all_voiced:
                label = f"scene {scene}" if scene is not None else f"{total - voiced}/{total} scenes"
                msg = f"Voice generation must complete before image generation. Missing voice for {label}."
                await self._log_activity("Image Bot", video_id, "failed", msg)
                return {"status": "failed", "error": msg}
        if (video.get("render_mode") or "") == "static_docu":
            return await self.run_coverage_stage(
                video_id, only_scenes={scene} if scene else None)
        from scripts.coverage_to_app import generate_coverage_for_video
        return await generate_coverage_for_video(video_id, self.tenant_id, scene=scene)

    async def run_storyboard_sheet(self, video_id: str, scene: int = None) -> dict:
        """Draw the cheap single-image storyboard SHEET preview for a scene via
        coverage. Replaces the old grid run_storyboard_prompts+run_storyboard_images.
        Static-documentary videos have no generic storyboard stage (their 2–3
        aircraft views use the format-specific path), so refuse cleanly instead of running the
        wrong generic-coverage path."""
        video = await self._get_video(video_id)
        if video and (video.get("render_mode") or "") == "static_docu":
            return {"status": "skipped",
                    "message": "This static-documentary channel generates its own "
                               "verified aircraft view set, not generic storyboards."}
        from scripts.coverage_to_app import generate_storyboard_sheet_for_scene
        result = await generate_storyboard_sheet_for_scene(video_id, self.tenant_id, scene=scene)
        # D5 chunk A6 (FRAME-ARBITER-PLAN.md): flag-gated Frame Arbiter pass,
        # scoped to exactly ONE (video_id, scene) via env config — see
        # frame_arbiter_hook.py's own module docstring for the flag/sub-flag
        # law. scene_is_in_scope's own check (inside run_after_storyboard_
        # sheet) is env-only and returns instantly for every scene except
        # the one flagged one, so this import + call costs nothing on the
        # unflagged path (byte-identical `result` returned below). Only
        # attempted when a scene was actually drawn (never on the bulk
        # scene=None path, and never when the sheet draw itself failed —
        # there is nothing fresh to judge).
        if scene is not None and result.get("status") not in ("failed", "skipped"):
            from frame_arbiter_hook import run_after_storyboard_sheet
            try:
                arbiter_result = await run_after_storyboard_sheet(self.tenant_id, video_id, scene)
            except Exception as exc:  # noqa: BLE001 - the arbiter must never break the storyboard stage itself
                _logger.exception(
                    "frame_arbiter_hook failed for video=%s scene=%s: %s", video_id, scene, exc
                )
                arbiter_result = None
            if arbiter_result is not None:
                result = dict(result, frame_arbiter=arbiter_result)
        return result

    async def run_coverage_stage(self, video_id: str, only_scenes: set = None) -> dict:
        """Unified image STAGE (GOAL v2 Phase 0): draw the real per-shot, multi-angle
        pictures via coverage — the single live image path — mirroring the proven chat
        auto-build image phase (routes/chat.py). This is what the autopilot status map
        and the Claude orchestrator now call instead of the old 3x3 grid handlers
        (run_storyboard_prompts/run_storyboard_images), so no entry point produces a
        different result. Satisfies the storyboard gates + writes the Story Bible first
        (same as chat), then stops at ready_for_images (the pictures-review checkpoint)."""
        await self._ensure_initialized()
        bot_name = "Storyboard Bot"
        video = await self._get_video(video_id)
        if not video:
            return {"status": "failed", "error": "Video not found"}
        # Money gate (voicefix) — same guard as run_coverage_images, and for
        # the same reason: this method IS the modern image stage (the
        # "ready_for_storyboards"/"ready_for_storyboard_images"/
        # "ready_for_storyboard_extraction" status-map handlers and
        # ClaudeOrchestrator's "storyboard" skill dispatch all call this
        # directly, not through run_coverage_images), so it needs its own
        # copy of the check rather than relying on the caller to have it.
        # only_scenes narrows the check to those scenes when it's a single
        # scene; anything else (None, or more than one) checks every scene,
        # since a partial redo must not be a loophole for an otherwise
        # unvoiced video.
        if not video.get("skip_voice"):
            check_scene = next(iter(only_scenes)) if only_scenes and len(only_scenes) == 1 else None
            all_voiced, total, voiced = await self._check_voice_exists(video_id, scene=check_scene)
            if not all_voiced:
                label = f"scene {check_scene}" if check_scene is not None else f"{total - voiced}/{total} scenes"
                msg = f"Voice generation must complete before image generation. Missing voice for {label}."
                await self._log_activity(bot_name, video_id, "failed", msg)
                return {"status": "failed", "error": msg}
        # STATIC-DOCU videos take 2–3 verified aircraft views per segment instead
        # of generic coverage (no cast, no story bible) — same branch as the
        # chat auto-build, so every entry point produces the same result.
        if (video.get("render_mode") or "") == "static_docu":
            await self._log_activity(bot_name, video_id, "started",
                                     "Creating three aircraft views per segment (static documentary)")
            from static_docu import generate_static_images_for_video
            st = await generate_static_images_for_video(
                video_id, self.tenant_id, only_scenes=only_scenes) or {}
            if st.get("status") == "completed":
                await execute(
                    "UPDATE videos SET status = 'ready_for_images', updated_at = now() "
                    "WHERE id = $1 AND tenant_id = $2",
                    video_id, self.tenant_id)
                await self._log_activity(bot_name, video_id, "completed",
                                         st.get("message") or "Segment images created")
                return {"status": "ready_for_images", "video_id": video_id}
            err = st.get("error") or "Couldn't create the segment images."
            await self._log_activity(bot_name, video_id, "failed", err)
            return {"status": "failed", "error": err}
        # Satisfy the storyboard gates + write the Story Bible (continuity anchor),
        # exactly as the chat auto-build does before calling coverage.
        await execute(
            "UPDATE videos SET environments_approved_at = COALESCE(environments_approved_at, now()), "
            "characters_approved_at = COALESCE(characters_approved_at, now()), updated_at = now() "
            "WHERE id = $1 AND tenant_id = $2",
            video_id, self.tenant_id)
        try:
            await self.run_story_bible(video_id)
        except Exception:  # noqa: BLE001 — bible is best-effort, coverage still draws
            pass
        await self._log_activity(bot_name, video_id, "started",
                                 "Drawing the storyboard pictures (coverage)")
        from scripts.coverage_to_app import generate_coverage_for_video
        cov = await generate_coverage_for_video(video_id, self.tenant_id) or {}
        if cov.get("status") == "completed":
            await execute(
                "UPDATE videos SET status = 'ready_for_images', updated_at = now() "
                "WHERE id = $1 AND tenant_id = $2",
                video_id, self.tenant_id)
            await self._log_activity(bot_name, video_id, "completed",
                                     "Storyboard pictures drawn (coverage)")
            return {"status": "ready_for_images", "video_id": video_id}
        err = cov.get("error") or "Couldn't draw the pictures."
        await self._log_activity(bot_name, video_id, "failed", err)
        return {"status": "failed", "error": err}

    async def run_characters(self, video_id: str, scene: int = None) -> dict:
        """Design/redesign the cast — the 4-view character reference sheets the storyboard
        anchors on. Reuses the Characters-tab generator (routes.characters helpers) so the
        co-pilot dock ('redesign the cast') produces the same sheets as the tab button."""
        from routes.characters import _extract_cast, _generate_portrait, _persist_portrait_url
        from vault import get_secret
        video = await fetch_one(
            "SELECT * FROM videos WHERE id=$1 AND tenant_id=$2", video_id, self.tenant_id)
        if not video:
            return {"status": "failed", "error": "video not found"}
        video = dict(video)
        video["tenant_id"] = self.tenant_id

        # LOCKED CHANNEL CAST: the creator's own sheets are brand assets — no
        # generation, no approval step. Import the project cast, build the
        # sheet, stamp the approval, done. This is also what lets queued /
        # autopilot videos pass the cast gate autonomously.
        if video.get("project_id"):
            proj = await fetch_one(
                "SELECT cast_locked, character_references FROM projects "
                "WHERE id = $1 AND tenant_id = $2",
                video["project_id"], self.tenant_id,
            )
            refs = (proj or {}).get("character_references")
            if isinstance(refs, str):
                import json as _cast_json
                try:
                    refs = _cast_json.loads(refs)
                except (ValueError, TypeError):
                    refs = []
            refs = [c for c in (refs or [])
                    if isinstance(c, dict) and c.get("reference_url")
                    # `always: false` members are optional extras — imported per
                    # video via the Use Saved Cast picker, never auto-attached.
                    and c.get("always", True)]
            if proj and proj.get("cast_locked") and refs:
                from routes.characters import _build_cast_sheet, _sync_bible_to_cast
                existing = await fetch_all(
                    "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2",
                    video_id, self.tenant_id,
                )
                existing_names = {r["name"] for r in (existing or [])}
                for i, c in enumerate(refs):
                    if (c.get("name") or f"Character {i+1}") in existing_names:
                        continue
                    await execute(
                        "INSERT INTO video_characters (tenant_id, video_id, name, description, "
                        "reference_url, source, status, sort, voice_name) "
                        "VALUES ($1,$2,$3,$4,$5,'project','approved',$6,$7)",
                        self.tenant_id, video_id, (c.get("name") or f"Character {i+1}")[:120],
                        (c.get("description") or "")[:1000], c["reference_url"], i,
                        # Channel voice pin rides the locked cast (Ryan=Adam,
                        # Vanessa=Pamela) — auto-cast only fills BLANK voices,
                        # so a pinned voice survives every future video.
                        c.get("voice_name"),
                    )
                await execute(
                    "UPDATE video_characters SET status = 'approved', updated_at = now() "
                    "WHERE video_id = $1 AND tenant_id = $2",
                    video_id, self.tenant_id,
                )
                cast_rows = await fetch_all(
                    "SELECT name, reference_url FROM video_characters "
                    "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
                    "ORDER BY sort, created_at",
                    video_id, self.tenant_id,
                )
                cast_list = [dict(r) for r in cast_rows]
                sheet_url = await _build_cast_sheet(self.tenant_id, video_id, cast_list)
                await _sync_bible_to_cast(video_id, self.tenant_id, [
                    {**c, "description": c.get("description") or ""} for c in refs
                ])
                await execute(
                    "UPDATE videos SET characters_approved_at = now(), character_reference_url = $1, "
                    "updated_at = now() WHERE id = $2 AND tenant_id = $3",
                    sheet_url or refs[0]["reference_url"], video_id, self.tenant_id,
                )
                return {"status": "completed",
                        "message": f"Using your locked channel cast ({len(cast_list)} characters) — no generation needed."}

        api_key = await get_secret("kie_ai_api_key", str(self.tenant_id))
        if not api_key:
            return {"status": "failed", "error": "Add your Kie.ai API key in Settings → Keys first."}
        style_dna = video.get("image_style_override") or ""
        cast = await _extract_cast(video, api_key)
        if not cast:
            return {"status": "failed", "error": "No recurring characters found in this script."}
        # Replace prior generated drafts; keep uploaded/imported ones. Reset the approval.
        await execute("DELETE FROM video_characters WHERE video_id=$1 AND tenant_id=$2 "
                      "AND source='generated' AND status='draft'", video_id, self.tenant_id)
        # D7-2 (STORY-LAWS S6): this is a second, parallel cast-creation path
        # (the copilot "redesign the cast" dock command) that reads the same
        # video.get("script") _extract_cast just used — stamp it exactly
        # like routes/characters.py::design_characters does, or a cast built
        # via THIS path would never be eligible for staleness detection.
        from routes.videos import _full_script_hash
        await execute("UPDATE videos SET characters_approved_at = NULL, characters_hash = $3 "
                      "WHERE id=$1 AND tenant_id=$2",
                      video_id, self.tenant_id, _full_script_hash(video.get("script") or ""))
        from actions import budget_check, picture_price_for, video_summary
        from generation_ledger import record_ledger_entry
        done = 0
        for i, ch in enumerate(cast):
            # Money-safety fix: this copilot "redesign the cast" verb is the
            # SAME real GPT Image 2 spend as the Characters tab button
            # (routes/characters.py), which had no ledger write and no cap
            # check at all — fixed the same way here, checked fresh every
            # character since spend accrues across the loop.
            summary = await video_summary(self.tenant_id, video_id)
            breach = budget_check(summary, picture_price_for(None)) if summary else None
            if breach:
                msg = (
                    f"Paused — this would put you at ${breach['projected']:.2f} against this "
                    f"video's ${breach['cap']:.2f} spend cap (${breach['spent']:.2f} already "
                    "spent). Raise the cap in Settings, then try again."
                )
                if done:
                    msg = f"Cast designed: {done}/{len(cast)} character sheets ready before the cap stopped it. " + msg
                return {"status": "completed", "message": msg}
            row = await fetch_one(
                "INSERT INTO video_characters (tenant_id, video_id, name, description, sort) "
                "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                self.tenant_id, video_id, ch["name"][:120], ch.get("description") or "", i)
            char_id = str(row["id"])
            for attempt in range(3):
                try:
                    portrait = await _generate_portrait(api_key, ch.get("description") or ch["name"], style_dna, name=ch.get("name") or "")
                    url = await _persist_portrait_url(self.tenant_id, video_id, char_id, portrait["url"])
                    await execute("UPDATE video_characters SET reference_url=$1, updated_at=now() WHERE id=$2",
                                  url, char_id)
                    cost = picture_price_for(portrait["model"])
                    await record_ledger_entry(
                        tenant_id=self.tenant_id, video_id=video_id, stage="character_sheet",
                        model=portrait["model"], units=1, unit_cost=cost, actual_cost=cost,
                        kie_task_id=portrait.get("task_id"),
                    )
                    done += 1
                    break
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(2 * (attempt + 1))
        return {"status": "completed",
                "message": f"Cast designed: {done}/{len(cast)} character sheets ready — review, then approve."}

    async def run_prompts(self, video_id: str, scene: int = None, index: int = None) -> dict:
        """Generate image prompts for a video.

        Args:
            video_id: Supabase video UUID
            scene: Optional scene number for single-scene generation
            index: Optional segment index within a scene for single-segment generation

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()
        bot_name = "Image Prompt Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            # Pipeline integrity check: voice must exist before image prompts (full runs only).
            # Skipped when the video opted out of AI voice-over (skip_voice).
            if scene is None and not video.get("skip_voice"):
                all_voiced, total, voiced = await self._check_voice_exists(video_id)
                if not all_voiced:
                    # Fail without touching status: demoting here regressed a
                    # status the voice bot had legitimately advanced, trapping
                    # the video behind the ready_for_voice approval gate.
                    msg = f"Voice generation must complete before image prompts. Missing voice for {total - voiced}/{total} scenes."
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    return {"status": "failed", "error": msg}

            current_status = video.get("status")

            # Modeled videos: the Model A Video flow seeds per-scene CONCEPT
            # rows (generation_method='modeled') as inspectable pre-prompts.
            # They carry image_prompt values, so the engine's resume logic sees
            # every scene as "completed" and generates nothing. Clear them on a
            # full run — the pack stays archived in original_dna/research_payload
            # — so the engine builds the real per-scene prompt set (styled via
            # image_style_override, which carries the modeled image DNA).
            if scene is None and video.get("source") == "modeled":
                cleared = await execute(
                    "DELETE FROM assets WHERE video_id = $1 AND tenant_id = $2 "
                    "AND generation_method = 'modeled'",
                    video_id, self.tenant_id,
                )
                print(f"[Prompts] Cleared modeled concept rows before full generation ({cleared})", flush=True)

            if scene is not None and index is not None:
                log_msg = f"Generating prompt for scene {scene} segment {index}"
            elif scene is not None:
                log_msg = f"Generating prompts for scene {scene}"
            else:
                log_msg = "Generating prompts"
            await self._log_activity(bot_name, video_id, "started", log_msg)

            self._load_idea_from_video(video_id)
            # Deliver the channel look to the neutral image profile (per-video
            # override else channel style_description). This stage doesn't go
            # through _load_prompt_overrides, so set it here.
            await self._export_visual_style(video)

            # Override status so the bot's internal check passes on re-runs
            if self._pipeline.current_idea:
                self._pipeline.current_idea["Status"] = "Ready For Image Prompts"

            # Set filters for targeted generation
            if scene is not None:
                self._pipeline.scene_filter = scene
            if index is not None:
                self._pipeline.image_filter = index

            result = await self._pipeline.run_styled_image_prompts()

            # Reset filters after run
            self._pipeline.scene_filter = None
            self._pipeline.image_filter = None

            if result.get("error"):
                raise Exception(result["error"])

            # For targeted runs, skip status advancement
            if scene is not None:
                await self._log_activity(bot_name, video_id, "completed", log_msg)
                return {"status": current_status, "video_id": video_id}

            new_status = result.get("new_status", "ready_for_images")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Prompts generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            # Reset filters on error
            self._pipeline.scene_filter = None
            self._pipeline.image_filter = None
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_prompts(self, video_id: str, scene: int = None, progress_callback=None) -> dict:
        """Generate storyboard prompts for a video.

        Args:
            scene: If set, only generate prompts for this scene number.
            progress_callback: Called with (message: str) to report progress.
        """
        await self._ensure_initialized()
        bot_name = "Storyboard Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            scene_label = f" (Scene {scene})" if scene else ""

            # Gate: environments must be designed+approved (or explicitly
            # skipped) before ANY storyboard prompts — bulk or per-scene — so
            # backgrounds get locked instead of silently drifting.
            env_gate = await self._environments_ready_gate(video_id, video)
            if env_gate:
                await self._log_activity(bot_name, video_id, "failed", env_gate)
                return {"status": "failed", "error": env_gate}

            await self._log_activity(bot_name, video_id, "started", f"Generating storyboard prompts{scene_label}")

            self._load_idea_from_video(video_id)
            # Deliver the channel look to the neutral image profile.
            await self._export_visual_style(video)

            # Reconcile the Story Bible's character costumes with the APPROVED
            # cast BEFORE writing prompts. The bible is generated from the script
            # and invents its own outfits (Tom in a hoodie, Dad in glasses) that
            # contradict the approved portraits — and the storyboard prompt text
            # then overrides the cast-sheet image, so characters drift. The
            # approved descriptions (vision pass from the portraits) are the
            # source of truth. Runs every prompt build so re-approvals propagate.
            try:
                cast_rows = await fetch_all(
                    "SELECT name, description FROM video_characters "
                    "WHERE video_id = $1 AND tenant_id = $2 AND reference_url IS NOT NULL "
                    "ORDER BY sort, created_at",
                    video_id, self.tenant_id,
                )
                if cast_rows:
                    from routes.characters import _sync_bible_to_cast
                    await _sync_bible_to_cast(video_id, self.tenant_id, [dict(r) for r in cast_rows])
            except Exception as e:
                _logger.warning("[storyboard] bible<-cast sync skipped: %s", str(e)[:150])

            result = await self._pipeline.run_storyboard_prompts(
                scene_filter=scene,
                progress_callback=progress_callback,
            )

            if result.get("error"):
                raise Exception(result["error"])

            # For per-scene runs, don't advance video status
            if scene is not None:
                await self._log_activity(bot_name, video_id, "completed", f"Scene {scene} prompts generated")
                return {"status": current_status, "video_id": video_id}

            new_status = result.get("new_status", "ready_for_images")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Storyboard director complete — image prompts enriched")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_story_bible(self, video_id: str) -> dict:
        """Generate and persist a Story Bible for a video.

        StoryEngine-native (checklist D10-2ab): generation runs entirely in
        ``story_bible_native.py`` (one Claude call via the SAME
        ``self._pipeline.anthropic`` bridge every other ``run_*`` step
        already uses) and persistence is a direct tenant-scoped
        ``UPDATE videos SET story_bible = $1`` — no legacy
        ``storyboard.bot`` import, no Airtable-shim
        (``supabase_adapter.update_idea_fields``) column-replace round trip.
        This step alone was moved; every other ``run_*`` stage (including
        ``run_storyboard_prompts``, which still calls the legacy generator
        as its OWN fallback if a bible is somehow still missing) is
        untouched.
        """
        import json
        import story_bible_native

        await self._ensure_initialized()
        bot_name = "Story Bible Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating Story Bible")

            video_title = video.get("video_title") or ""
            video_length_min = video.get("video_length_minutes") or 10

            script_rows = await fetch_all(
                "SELECT scene, scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
                "ORDER BY scene",
                video_id, self.tenant_id,
            )
            if not script_rows:
                raise Exception(f"No script found for '{video_title}'")

            full_script_text = "\n\n".join(
                f"[SCENE {r.get('scene', 0)}]\n{r.get('scene_text') or ''}"
                for r in script_rows
            )

            anthropic_client = getattr(self._pipeline, "anthropic", None)
            if anthropic_client is None:
                raise Exception("Anthropic client not available for Story Bible generation")

            bible = await story_bible_native.generate_story_bible_native(
                anthropic_client=anthropic_client,
                full_script_text=full_script_text,
                video_title=video_title,
                video_length_minutes=int(video_length_min),
            )
            if not bible:
                raise Exception("Story Bible generation returned empty result")

            await execute(
                "UPDATE videos SET story_bible = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
                json.dumps(bible), video_id, self.tenant_id,
            )

            await self._log_activity(bot_name, video_id, "completed", "Story Bible generated")
            return {"status": current_status or "ready_for_storyboards", "video_id": video_id}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_images(self, video_id: str, scene: int = None, progress_callback=None) -> dict:
        """Generate storyboard images for a video.

        Args:
            scene: If set, only generate images for this scene number.
            progress_callback: Called with (message: str) to report progress.
        """
        await self._ensure_initialized()
        bot_name = "Storyboard Images Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            scene_label = f" (Scene {scene})" if scene else ""
            await self._log_activity(bot_name, video_id, "started", f"Generating storyboard images{scene_label}")

            self._load_idea_from_video(video_id)
            # Deliver the channel look (storyboard keyframe prompts + grids).
            await self._export_visual_style(video)

            # Per-video output shape, chosen at creation. The grid generation
            # request honors it; the model has historically ignored aspect on
            # some paths, so the deterministic backstop (panel normalization)
            # is still owed — see the aspect_ratio handoff. Defaults to 16:9.
            self._pipeline.aspect_ratio = video.get("aspect_ratio") or "16:9"

            gate = await self._load_character_refs(video_id, video)
            if gate and scene is None:
                await self._log_activity(bot_name, video_id, "failed", gate)
                return {"status": "failed", "error": gate}

            # Gate: environments must be done (approved or explicitly skipped)
            # before grids — bulk OR per-scene. After it passes,
            # _load_environment_refs populates the {location: ref} map the bot
            # conditions each grid on (empty when the video was skipped).
            env_gate = await self._environments_ready_gate(video_id, video)
            if env_gate:
                await self._log_activity(bot_name, video_id, "failed", env_gate)
                return {"status": "failed", "error": env_gate}
            await self._load_environment_refs(video_id, video)

            await self._install_cancel_support(video_id)
            result = await self._pipeline.run_storyboard_images(
                scene_filter=scene,
                progress_callback=progress_callback,
            )

            if result.get("cancelled"):
                kept = result.get("grids_generated", 0)
                msg = f"Stopped — kept {kept} completed grid(s). Run grids again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg}

            if result.get("error"):
                raise Exception(result["error"])

            # Persist temp storyboard grid URLs to Supabase Storage
            persisted = await self._persist_storyboard_urls(video_id)
            if persisted:
                _logger.info("Persisted %d storyboard grid URL(s) to Supabase Storage", persisted)

            # For per-scene runs, don't advance video status
            if scene is not None:
                await self._log_activity(bot_name, video_id, "completed", f"Scene {scene} images generated")
                return {"status": current_status, "video_id": video_id}

            new_status = result.get("new_status", "ready_for_storyboard_extraction")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", f"Storyboard images generated ({persisted} grids persisted)")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_storyboard_extract(self, video_id: str, progress_callback=None) -> dict:
        """Extract storyboard grid images into individual panels via Supabase Storage.

        Two-pass approach for instant feedback:
        Pass 1 (fast): PIL crop + upload → write to DB immediately (panels appear in UI)
        Pass 2 (slow): AI upscale each panel → update DB with better URL
        """
        await self._ensure_initialized()
        bot_name = "Storyboard Extract Bot"

        async def _report(msg: str):
            if progress_callback:
                try:
                    await progress_callback(msg)
                except Exception:
                    pass

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            # Mandatory storyboard gate: extraction turns approved boards into
            # final images (the paid upscale pass) — locked stories only.
            if not video.get("story_locked_at"):
                msg = user_facing("Lock your story first — review the storyboard grids and hit "
                                  "'Lock story' before extracting panels into final images.")
                await self._log_activity(bot_name, video_id, "failed", msg)
                return {"status": "failed", "error": msg}

            current_status = video.get("status")
            video_title = video.get("video_title", "")
            await self._log_activity(bot_name, video_id, "started", "Extracting storyboard frames")

            scenes = await fetch_all(
                """SELECT id, scene, storyboard_1_url, storyboard_2_url,
                          storyboard_3_url, storyboard_4_url, storyboard_5_url,
                          storyboard_beat_count
                   FROM scripts WHERE video_id = $1 AND tenant_id = $2
                   ORDER BY scene""",
                video_id, self.tenant_id,
            )

            if not scenes:
                raise Exception("No script scenes found for video")

            total_scenes = len([s for s in scenes if any(s.get(f"storyboard_{i}_url") for i in range(1, 6))])
            total_panels = 0
            scene_errors = []
            # Collect panel DB records for upscale pass
            all_panel_records = []  # (asset_id, panel_url, scene, beat, seq)
            # Assets whose picture got replaced under an existing clip —
            # their clips re-animate after extraction (Ryan's answer 2).
            stale_clip_assets = []

            # ── Pass 1: Fast crop + upload + write to DB ──
            scenes_done = 0
            for sc in scenes:
                scene_num = sc["scene"]
                beat_urls = []
                for i in range(1, 6):
                    url = sc.get(f"storyboard_{i}_url")
                    if url:
                        beat_urls.append((i, url))

                if not beat_urls:
                    continue

                # Resume: a scene whose every slot already has a final picture
                # is done — re-runs only touch scenes with missing panels.
                slot_rows = await fetch_all(
                    "SELECT image_url FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
                    video_id, scene_num, self.tenant_id,
                )
                if slot_rows and all(r.get("image_url") for r in slot_rows):
                    continue

                # The grids were GENERATED with grid_layout_for(panel_count),
                # slots chunked 9 per beat in order — crop with the same
                # geometry instead of guessing from pixels.
                from extraction import grid_layout_for
                slot_total = len(slot_rows)
                beat_panel_counts = []
                remaining = slot_total
                for _ in beat_urls:
                    take = min(9, remaining) if remaining > 0 else 0
                    beat_panel_counts.append(take)
                    remaining -= take

                scenes_done += 1
                panel_offset = 0
                for bi, (beat_num, grid_url) in enumerate(beat_urls):
                    expected = beat_panel_counts[bi] if bi < len(beat_panel_counts) else 0
                    rows, cols = grid_layout_for(expected) if expected > 0 else (0, 0)
                    try:
                        await _report(f"Extracting Scene {scenes_done}/{total_scenes}, Beat {beat_num}...")
                        # Fast: PIL crop only (no image_client = no upscale)
                        panels = await extract_grid(
                            grid_url, video_id, scene_num, beat_num, panel_offset,
                            rows=rows, cols=cols, expected_panels=expected,
                            tenant_id=self.tenant_id,
                        )
                        for p in panels:
                            flags = p.get("flags") or []
                            existing = await fetch_one(
                                """SELECT id, video_clip_url FROM assets
                                   WHERE video_id = $1 AND scene = $2 AND image_index = $3
                                   AND tenant_id = $4""",
                                video_id, scene_num, p["image_index"], self.tenant_id,
                            )
                            if existing:
                                asset_id = existing["id"]
                                if existing.get("video_clip_url"):
                                    stale_clip_assets.append(asset_id)
                                await execute(
                                    """UPDATE assets SET image_url = $1, status = 'done',
                                              generation_method = 'storyboard_extract',
                                              extraction_flags = $2, updated_at = now()
                                       WHERE id = $3""",
                                    p["panel_url"], flags or None, asset_id,
                                )
                            elif slot_total == 0:
                                asset_id = str(uuid.uuid4())
                                await execute(
                                    """INSERT INTO assets
                                       (id, tenant_id, video_id, video_title, scene, image_index,
                                        image_url, status, generation_method, extraction_flags,
                                        created_at, updated_at)
                                       VALUES ($1, $2, $3, $4, $5, $6, $7, 'done',
                                               'storyboard_extract', $8, now(), now())""",
                                    asset_id, self.tenant_id, video_id, video_title,
                                    scene_num, p["image_index"], p["panel_url"], flags or None,
                                )
                            else:
                                # Orphan guard: more crops than story slots means
                                # the grid geometry drifted (the bird video got 12
                                # story-less rows this way — no sentence, no
                                # prompt, un-renderable). Never invent rows the
                                # script doesn't have.
                                print(f"[extract] S{scene_num}.{p['image_index']} has no "
                                      f"story slot (scene has {slot_total}) — skipping "
                                      f"orphan crop", flush=True)
                                scene_errors.append(
                                    f"Scene {scene_num}: crop {p['image_index']} exceeds "
                                    f"the scene's {slot_total} pictures (skipped)")
                                continue
                            total_panels += 1
                            all_panel_records.append((
                                asset_id, p["panel_url"], scene_num, beat_num,
                                p["image_index"],
                            ))
                        panel_offset += len(panels)
                    except Exception as e:
                        scene_errors.append(f"Scene {scene_num} beat {beat_num}: {e}")

            if total_panels == 0 and scene_errors:
                raise Exception(f"All extractions failed: {'; '.join(scene_errors)}")

            # Advance status immediately — panels are visible in UI now
            new_status = "ready_for_images"
            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")

            msg = f"Extracted {total_panels} panels"
            if scene_errors:
                msg += f" ({len(scene_errors)} beat errors skipped)"

            # ── Pass 2: AI upscale (slow, but panels already visible) ──
            # DISABLED by default: nano-banana-2 refuses to regenerate images
            # of children ("Google's Generative AI Prohibited Use policy") —
            # on the bird video ALL 82 upscales were filtered (0 credits, ~40
            # wasted minutes). Until a non-generative upscaler (ESRGAN-class)
            # is wired in, extraction returns the clean crops and the manual
            # "Upscale" action (run_upscale_panels) remains for retries.
            import os as _os
            upscale_enabled = _os.getenv("EXTRACT_AUTO_UPSCALE", "false").lower() == "true"
            image_client = getattr(self._pipeline, "image_client", None) if upscale_enabled else None
            upscaled = 0
            if image_client and all_panel_records:
                await _report(f"Panels extracted! Upscaling {len(all_panel_records)} images...")
                # Money-safety fix: same real Nano Banana 2 spend as
                # run_upscale_panels above, and this Pass-2 loop had NO
                # ledger write and NO cap check either. This path is
                # EXTRACT_AUTO_UPSCALE-gated (off by default per the comment
                # above), but metered anyway so a future flip of that flag
                # can't spend silently.
                from actions import budget_refusal, picture_price_for
                pass2_quote = picture_price_for("nano-banana-2")
                pass2_budget_stopped = False
                for idx, (asset_id, panel_url, sc_num, bt_num, img_idx) in enumerate(all_panel_records):
                    refusal = await budget_refusal(self.tenant_id, video_id, pass2_quote, "this panel upscale")
                    if refusal:
                        _logger.info("Storyboard-extract upscale stopped by spend cap: %s", refusal)
                        pass2_budget_stopped = True
                        break
                    try:
                        await _report(f"Upscaling Scene {sc_num} Image {img_idx} ({idx + 1}/{len(all_panel_records)})")
                        prompt = (
                            "Upscale this image to high resolution. "
                            "Remove any text labels like [KF1 | LS | 12s], [KF7 | MS | 9s], "
                            "or similar keyframe/shot/duration overlays — cleanly paint over "
                            "them with the surrounding image content. "
                            "Otherwise do NOT alter the image in any way. "
                            "Keep the exact same composition, pose, expression, colors, "
                            "and details. Only increase resolution, clarity, and remove labels."
                        )
                        result = await image_client.generate_scene_image(
                            prompt=prompt,
                            reference_image_url=panel_url,
                        )
                        if result and result.get("url"):
                            path = f"{video_id}/images/S{sc_num}-B{bt_num}-P{img_idx}_hd.png"
                            upscaled_url = await upload_from_url(result["url"], path, tenant_id=self.tenant_id)
                            await execute(
                                "UPDATE assets SET image_url = $1, updated_at = now() WHERE id = $2",
                                upscaled_url, asset_id,
                            )
                            upscaled += 1
                            await record_ledger_entry(
                                tenant_id=self.tenant_id, video_id=video_id, stage="image",
                                model="nano-banana-2", units=1, unit_cost=pass2_quote,
                                actual_cost=pass2_quote,
                            )
                    except Exception as e:
                        _logger.warning("Upscale failed for panel %d: %s — keeping original", idx, e)

                msg += f", {upscaled}/{len(all_panel_records)} upscaled"
                if pass2_budget_stopped:
                    msg += " (stopped early — spend cap reached)"

            # AUTO RE-ANIMATE (Ryan's answer 2): pictures replaced under an
            # existing clip regenerate that clip — only clips that already
            # existed, ~$0.10 each, no human in the loop.
            if stale_clip_assets:
                await _report(f"Pictures changed — re-animating {len(stale_clip_assets)} stale clip(s)…")
                reanimated = 0
                for aid in stale_clip_assets:
                    res = await self.run_clip_generation(video_id, asset_id=aid, force=True)
                    if res.get("clips_generated"):
                        reanimated += res["clips_generated"]
                msg += f" — re-animated {reanimated}/{len(stale_clip_assets)} stale clip(s)"

            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": to_supabase(new_status), "video_id": video_id, "panels_extracted": total_panels}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_fix_text_card(self, video_id: str, asset_id: str) -> dict:
        """One-tap 'Fix text': redraw a title/word card via GPT Image 2 (best-in-class
        for legible lettering — nano-banana garbles text). Uses the current panel as the
        art-style + layout reference and its image_prompt/narration for the intended
        wording. Scenes stay on nano-banana; only the tapped card is redrawn, replaced in
        place. Any clip made from the old card is cleared so it re-animates."""
        bot_name = "Fix Text"
        try:
            await self._ensure_initialized()
            asset = await fetch_one(
                "SELECT scene, image_index, image_prompt, sentence_text, image_url, "
                "drive_image_url FROM assets WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
                asset_id, video_id, self.tenant_id,
            )
            if not asset:
                return {"status": "failed", "error": "Picture not found"}
            ref_url = asset.get("drive_image_url") or asset.get("image_url")
            if not ref_url:
                return {"status": "failed", "error": "This card has no picture yet to fix"}
            client = getattr(self._pipeline, "image_client", None)
            if not client:
                return {"status": "failed", "error": "Image generator unavailable right now"}

            video = await self._get_video(video_id)
            aspect = (video or {}).get("aspect_ratio") or "16:9"
            style = ((video or {}).get("image_style_override") or "").strip()
            intent = (asset.get("sentence_text") or asset.get("image_prompt") or "").strip()
            # Keep the prompt LEAN — the reference image carries the art style/layout; the
            # model's job is legible text. A long/noisy prompt risks confusing it (and can
            # trip provider errors), so cap the style + wording we append.
            prompt = (
                "Redraw this title/word card keeping the EXACT same art style, colours, and "
                "layout as the reference image, but render all on-card text large, perfectly "
                "legible, correctly spelled, and cleanly typeset. Keep it a clean card — same "
                "scene, no new characters or scenery, no watermarks."
                f"{(' Art style: ' + style[:280] + '.') if style else ''}"
                f"{(' Intended wording/content: ' + intent[:280] + '.') if intent else ''}"
            )
            sc, idx = asset["scene"], asset["image_index"]

            # Money-safety fix: this one-tap redraw is a real GPT Image 2
            # call with NO generation_ledger write and NO cap check — same
            # per-call refusal pattern as every other single-shot paid site
            # (actions.budget_refusal).
            from actions import budget_refusal, picture_price_for
            quote = picture_price_for("gpt-image-2")
            refusal = await budget_refusal(self.tenant_id, video_id, quote, "this text fix")
            if refusal:
                await self._log_activity(bot_name, video_id, "completed", refusal)
                return {"status": "completed", "video_id": video_id, "message": refusal}

            await self._log_activity(bot_name, video_id, "started", f"Fixing text on S{sc}.{idx} (GPT Image 2)…")
            res = await client.generate_thumbnail_gpt2(prompt, [ref_url], aspect_ratio=aspect)
            new_url = (res or {}).get("url")
            if not new_url:
                await self._log_activity(bot_name, video_id, "failed", "GPT Image 2 didn't return a card — try again.")
                return {"status": "failed", "error": "The text fix didn't generate — tap Fix text to try again."}

            # generation_ledger: the redraw above already cost real money the
            # moment new_url came back.
            await record_ledger_entry(
                tenant_id=self.tenant_id, video_id=video_id, stage="image",
                model="gpt-image-2", units=1, unit_cost=quote, actual_cost=quote,
            )

            durable = await self._persist_url(new_url, f"{video_id}/images/S{sc}-{idx}_text.png")
            await execute(
                "UPDATE assets SET image_url = $1, drive_image_url = $1, video_clip_url = NULL, "
                "updated_at = now() WHERE id = $2 AND tenant_id = $3",
                durable, asset_id, self.tenant_id,
            )
            await self._log_activity(bot_name, video_id, "completed", f"Text fixed on S{sc}.{idx}")
            return {"status": "completed", "video_id": video_id,
                    "message": "Card text redrawn with GPT Image 2 — re-animate it to refresh its clip.",
                    "image_url": durable}
        except Exception as e:
            await self._log_activity(bot_name, video_id, "failed", str(e))
            return {"status": "failed", "error": str(e)}

    async def run_recrop_panel(self, video_id: str, asset_id: str) -> dict:
        """One-tap 'Re-crop this picture' (Ryan's bad-crop rule, answer 4).

        A split crop never comes alone — wrong geometry breaks every panel
        on its grid — so this re-crops the tapped asset's whole BEAT with
        the self-healing layout in extract_grid and refreshes every asset
        the beat covers. Pure PIL, free, replaces Drive content in place
        (same file ids; the md5-ETag proxy busts caches).
        """
        bot_name = "Re-crop"
        try:
            asset = await fetch_one(
                "SELECT scene, image_index FROM assets "
                "WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
                asset_id, video_id, self.tenant_id,
            )
            if not asset:
                return {"status": "failed", "error": "Picture not found"}
            scene_num, image_index = asset["scene"], asset["image_index"]

            sc = await fetch_one(
                "SELECT storyboard_1_url, storyboard_2_url, storyboard_3_url, "
                "storyboard_4_url, storyboard_5_url FROM scripts "
                "WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
                video_id, scene_num, self.tenant_id,
            )
            beat_urls = [(i, sc.get(f"storyboard_{i}_url")) for i in range(1, 6)
                         if sc and sc.get(f"storyboard_{i}_url")]
            if not beat_urls:
                return {"status": "failed", "error": "This scene has no storyboard grids to re-crop from"}

            slot_rows = await fetch_all(
                "SELECT id, image_index FROM assets WHERE video_id = $1 AND scene = $2 "
                "AND tenant_id = $3 AND sentence_text IS NOT NULL ORDER BY image_index",
                video_id, scene_num, self.tenant_id,
            )
            slot_total = len(slot_rows)

            # Same greedy 9-per-beat chunking the grids were built with —
            # find the beat whose index range covers the tapped picture.
            from extraction import extract_grid, grid_layout_for
            offset = 0
            target = None
            for bi, (beat_num, grid_url) in enumerate(beat_urls):
                take = min(9, max(0, slot_total - offset))
                if offset < image_index <= offset + take or (take == 0 and bi == len(beat_urls) - 1):
                    target = (beat_num, grid_url, offset, take)
                    break
                offset += take
            if not target:
                return {"status": "failed", "error": "Couldn't match this picture to a storyboard grid"}

            beat_num, grid_url, panel_offset, expected = target
            rows, cols = grid_layout_for(expected) if expected > 0 else (0, 0)
            await self._log_activity(bot_name, video_id, "started",
                                     f"Re-cropping S{scene_num} beat {beat_num}")
            panels = await extract_grid(grid_url, video_id, scene_num, beat_num,
                                        panel_offset, rows=rows, cols=cols,
                                        expected_panels=expected, tenant_id=self.tenant_id)
            # Which of the beat's assets already had a clip? Their clips go
            # stale the moment the picture under them changes.
            beat_range = await fetch_all(
                "SELECT id, image_index, video_clip_url FROM assets "
                "WHERE video_id = $1 AND scene = $2 AND tenant_id = $3 "
                "AND image_index > $4 AND image_index <= $5",
                video_id, scene_num, self.tenant_id,
                panel_offset, panel_offset + max(expected, len(panels)),
            )
            had_clip = {r["image_index"]: r["id"] for r in beat_range if r.get("video_clip_url")}

            updated = 0
            stale_clip_assets = []
            for p in panels:
                flags = p.get("flags") or []
                await execute(
                    """UPDATE assets SET image_url = $1, status = 'done',
                              generation_method = 'storyboard_extract',
                              extraction_flags = $2, updated_at = now()
                       WHERE video_id = $3 AND scene = $4 AND image_index = $5
                       AND tenant_id = $6""",
                    p["panel_url"], flags or None, video_id, scene_num,
                    p["image_index"], self.tenant_id,
                )
                updated += 1
                if p["image_index"] in had_clip:
                    stale_clip_assets.append(had_clip[p["image_index"]])

            still_bad = sum(1 for p in panels if p.get("flags"))
            msg = (f"Re-cropped {updated} picture(s) on S{scene_num} beat {beat_num}"
                   + (f" — {still_bad} still flagged" if still_bad else ""))

            # AUTO RE-ANIMATE (Ryan's answer 2): a redone picture regenerates
            # its clip — only clips that already existed, ~$0.10 each, fully
            # unattended (north star: no human in the loop).
            reanimated = 0
            for aid in stale_clip_assets:
                res = await self.run_clip_generation(video_id, asset_id=aid, force=True)
                if res.get("clips_generated"):
                    reanimated += res["clips_generated"]
            if stale_clip_assets:
                msg += f" — re-animated {reanimated}/{len(stale_clip_assets)} stale clip(s) (~${0.10 * reanimated:.2f})"

            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": "completed", "video_id": video_id, "message": msg,
                    "panels": updated, "still_flagged": still_bad,
                    "reanimated": reanimated}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_upscale_panels(self, video_id: str, progress_callback=None) -> dict:
        """Upscale extracted panels that haven't been upscaled yet (no _hd in URL).

        Resumes from where a previous upscale was interrupted.
        """
        await self._ensure_initialized()
        bot_name = "Panel Upscaler"

        async def _report(msg: str):
            if progress_callback:
                try:
                    await progress_callback(msg)
                except Exception:
                    pass

        try:
            image_client = getattr(self._pipeline, "image_client", None)
            if not image_client:
                return {"status": "failed", "error": "No image client available for upscaling"}

            # Find all extracted panels that haven't been upscaled
            raw_panels = await fetch_all(
                """SELECT id, scene, image_index, image_url
                   FROM assets
                   WHERE video_id = $1 AND tenant_id = $2
                   AND generation_method = 'storyboard_extract'
                   AND image_url NOT LIKE '%%_hd.png%%'
                   ORDER BY scene, image_index""",
                video_id, self.tenant_id,
            )

            if not raw_panels:
                return {"status": "completed", "message": "All panels already upscaled"}

            await self._log_activity(bot_name, video_id, "started",
                                     f"Upscaling {len(raw_panels)} panels")
            await _report(f"Upscaling {len(raw_panels)} images — removing KF labels...")

            # Money-safety fix: every panel here is a real Nano Banana 2 call
            # (image_client.generate_scene_image is hardcoded to that model —
            # see shared.clients.image_client.ImageClient.SCENE_MODEL) with
            # NO generation_ledger write and NO cap check — a video could
            # have dozens of un-upscaled panels, so this loop alone could
            # blow past a cap with total_cost never moving. Checked fresh
            # before EVERY panel (spend accrues across the loop), same
            # per-iteration pattern as routes/environments.py's design loop.
            from actions import budget_refusal, picture_price_for
            quote = picture_price_for("nano-banana-2")
            upscaled = 0
            budget_stopped = False
            for idx, panel in enumerate(raw_panels):
                refusal = await budget_refusal(self.tenant_id, video_id, quote, "this panel upscale")
                if refusal:
                    _logger.info("Panel upscale stopped by spend cap: %s", refusal)
                    budget_stopped = True
                    break
                try:
                    await _report(
                        f"Upscaling Scene {panel['scene']} Image {panel['image_index']} "
                        f"({idx + 1}/{len(raw_panels)})"
                    )
                    prompt = (
                        "Upscale this image to high resolution. "
                        "Remove any text labels like [KF1 | LS | 12s], [KF7 | MS | 9s], "
                        "or similar keyframe/shot/duration overlays — cleanly paint over "
                        "them with the surrounding image content. "
                        "Otherwise do NOT alter the image in any way. "
                        "Keep the exact same composition, pose, expression, colors, "
                        "and details. Only increase resolution, clarity, and remove labels."
                    )
                    result = await image_client.generate_scene_image(
                        prompt=prompt,
                        reference_image_url=panel["image_url"],
                    )
                    if result and result.get("url"):
                        path = f"{video_id}/images/S{panel['scene']}-I{panel['image_index']}_hd.png"
                        upscaled_url = await upload_from_url(result["url"], path, tenant_id=self.tenant_id)
                        await execute(
                            "UPDATE assets SET image_url = $1, updated_at = now() WHERE id = $2",
                            upscaled_url, panel["id"],
                        )
                        upscaled += 1
                        # generation_ledger: this upscale already cost real
                        # money the moment the provider returned a url.
                        await record_ledger_entry(
                            tenant_id=self.tenant_id, video_id=video_id, stage="image",
                            model="nano-banana-2", units=1, unit_cost=quote,
                            actual_cost=quote,
                        )
                except Exception as e:
                    _logger.warning("Upscale failed S%d I%d: %s", panel["scene"], panel["image_index"], e)

            msg = f"Upscaled {upscaled}/{len(raw_panels)} panels"
            if budget_stopped:
                msg += " — stopped early, this video's spend cap was reached"
            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": "completed", "message": msg, "upscaled": upscaled,
                    "budget_stopped": budget_stopped}

        except Exception as e:
            error_msg = str(e) or e.__class__.__name__
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_images(self, video_id: str, scene: int = None, index: int = None) -> dict:
        """Generate images for a video.

        Args:
            video_id: Supabase video UUID
            scene: Optional scene number for single-scene generation
            index: Optional segment index within a scene for single-image generation
        """
        await self._ensure_initialized()
        bot_name = "Image Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")

            # Full runs require voice completion; targeted re-runs bypass the stage gate.
            # Skipped when the video opted out of AI voice-over (skip_voice).
            if scene is None and not video.get("skip_voice"):
                all_voiced, total, voiced = await self._check_voice_exists(video_id)
                if not all_voiced:
                    # Fail without touching status: demoting here regressed a
                    # status the voice bot had legitimately advanced, trapping
                    # the video behind the ready_for_voice approval gate.
                    msg = f"Voice generation must complete before image generation. Missing voice for {total - voiced}/{total} scenes."
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    return {"status": "failed", "error": msg}

            if scene is not None and index is not None:
                log_msg = f"Generating image for scene {scene} segment {index}"
            elif scene is not None:
                log_msg = f"Generating images for scene {scene}"
            else:
                log_msg = "Generating images"
            await self._log_activity(bot_name, video_id, "started", log_msg)

            self._load_idea_from_video(video_id)
            # Deliver the channel look (drives characters/environments + any
            # prompt rebuilds). This stage doesn't go through _load_prompt_overrides.
            await self._export_visual_style(video)

            # Override status so the bot's internal check passes on re-runs
            if self._pipeline.current_idea:
                self._pipeline.current_idea["Status"] = "Ready For Images"

            # Targeted re-generation hooks already exist in the underlying pipeline.
            if scene is not None:
                self._pipeline.scene_filter = scene
            if index is not None:
                self._pipeline.image_filter = index

            # For targeted runs, reset matching assets to 'pending' so the image bot picks them up.
            # Assets may be in 'approved' status (from storyboard approval) with no image_url.
            if scene is not None:
                reset_sql = "UPDATE assets SET status = 'pending' WHERE video_id = $1 AND scene = $2 AND image_url IS NULL"
                reset_params = [video_id, scene]
                if index is not None:
                    reset_sql += " AND image_index = $3"
                    reset_params.append(index)
                await execute(reset_sql, *reset_params)

            # Mandatory storyboard gate: image spend only happens on a story
            # the creator reviewed and explicitly locked. Targeted single-image
            # regens bypass (they're post-lock fixes by definition).
            if scene is None and not video.get("story_locked_at"):
                msg = user_facing("Lock your story first — review the storyboard grids and hit "
                                  "'Lock story' on the Storyboard tab before generating images.")
                await self._log_activity(bot_name, video_id, "failed", msg)
                return {"status": "failed", "error": msg}

            gate = await self._load_character_refs(video_id, video)
            if gate and scene is None:
                await self._log_activity(bot_name, video_id, "failed", gate)
                return {"status": "failed", "error": gate}

            await self._install_cancel_support(video_id)
            result = await self._pipeline.run_image_bot()

            # Always reset filters after run
            self._pipeline.scene_filter = None
            self._pipeline.image_filter = None

            # generation_ledger (checklist §0.3b / C08): whatever generated
            # already cost money, whether the run finished, was stopped mid-way
            # (cancelled), or errored partway through — written before those
            # branches so no completed image's spend is lost. Reuses
            # actions.PICTURE_COST, the same constant store_scene()/
            # redraw_asset_image() use for the coverage path (this is the
            # OTHER live image path: targeted re-runs + the "remake visuals"
            # followup-edit flow via FOLLOWUP_STAGES).
            # kie_task_id intentionally left None (C16c): img_count aggregates
            # a whole run_image_bot() batch (many images, many Kie tasks) into
            # ONE ledger row — same reasoning as run_image_variants above, see
            # migration 093's header.
            img_count = result.get("image_count", 0)
            if img_count > 0:
                from actions import PICTURE_COST
                await record_ledger_entry(
                    tenant_id=self.tenant_id, video_id=video_id, stage="image",
                    model=None, units=img_count, unit_cost=PICTURE_COST,
                    actual_cost=round(img_count * PICTURE_COST, 2),
                )

            if result.get("cancelled"):
                kept = result.get("image_count", 0)
                await self._persist_asset_urls(video_id)
                msg = f"Stopped — kept {kept} completed image(s). Run Images again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg}

            if result.get("error"):
                raise Exception(result["error"])

            # Persist temp image URLs to Supabase Storage
            persisted = await self._persist_asset_urls(video_id)
            if persisted:
                _logger.info("Persisted %d image URL(s) to Supabase Storage", persisted)

            # For targeted runs, keep the current video status stable.
            if scene is not None:
                await self._log_activity(bot_name, video_id, "completed", log_msg)
                return {"status": current_status, "video_id": video_id}

            new_status = result.get("new_status", "ready_for_thumbnail")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", f"Images generated ({persisted} persisted to storage)")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            self._pipeline.scene_filter = None
            self._pipeline.image_filter = None
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_image_variants(self, video_id: str, scene: int, index: int, variants: int = 3) -> dict:
        """Generate image variants for a single scene/index without affecting primary assets."""
        await self._ensure_initialized()
        bot_name = "Image Variant Bot"

        if not self._pipeline.image_client:
            return {"status": "failed", "error": "Image client not available"}

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            asset = await fetch_one(
                """SELECT id, sentence_index, sentence_text, image_prompt, shot_type, hero_shot
                   FROM assets
                   WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 AND image_index = $4
                     AND (generation_method IS NULL OR generation_method <> 'variant_candidate')
                   ORDER BY created_at
                   LIMIT 1""",
                video_id, self.tenant_id, scene, index,
            )
            if not asset:
                return {"status": "failed", "error": f"Base asset not found for scene {scene} image {index}"}

            prompt = asset.get("image_prompt")
            if not prompt:
                return {"status": "failed", "error": "Base asset has no image prompt"}

            await self._log_activity(
                bot_name,
                video_id,
                "started",
                f"Generating {variants} variant(s) for scene {scene} image {index}",
            )

            self._load_idea_from_video(video_id)

            from shared.clients.airtable_client import get_image_model_override
            from shared.clients.image_model_router import (
                generate_scene_image_for_model, VALID_IMAGE_MODELS,
            )

            model_override = get_image_model_override(self._pipeline.current_idea or {})
            if model_override and model_override not in VALID_IMAGE_MODELS:
                model_override = ""

            existing = await fetch_one(
                """SELECT COALESCE(MAX(panel_position), 0) AS max_variant
                   FROM assets
                   WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 AND image_index = $4
                     AND generation_method = 'variant_candidate'""",
                video_id, self.tenant_id, scene, index,
            )
            next_variant_position = int(existing.get("max_variant") or 0) + 1
            created = 0

            for offset in range(variants):
                # ONE shared resolver for the whole app (also used by
                # scripts/coverage_to_app.py) — GPT Image 2 stays the default
                # and the content-policy/failure fallback for an explicit
                # nano-banana-2/z-image override; see image_model_router.py.
                image_url, model_used = await generate_scene_image_for_model(
                    self._pipeline.image_client, model_override, prompt,
                    reference_urls=self._pipeline.core_image_url, aspect_ratio="16:9",
                )

                if not image_url:
                    continue

                # Persist variant to Supabase Storage
                variant_path = f"{video_id}/images/S{scene}-{index}-v{next_variant_position + offset}.png"
                image_url = await self._persist_url(image_url, variant_path)

                drive_download_url = None
                try:
                    image_content = await self._pipeline.image_client.download_image(image_url)
                    filename = (
                        f"Scene_{str(scene).zfill(2)}_{str(index).zfill(2)}"
                        f"_variant_{str(next_variant_position + offset).zfill(2)}.png"
                    )
                    drive_file = self._pipeline.google.upload_image(
                        image_content, filename, self._pipeline.project_folder_id
                    )
                    if drive_file and drive_file.get("id"):
                        drive_download_url = self._pipeline.google.make_file_public(drive_file["id"])
                except Exception as drive_err:
                    print(f"      ⚠️ Variant Drive upload failed: {drive_err}", flush=True)

                await execute(
                    """INSERT INTO assets (
                        id, tenant_id, video_id, video_title, scene, image_index, sentence_index,
                        sentence_text, image_prompt, shot_type, hero_shot, image_url, drive_image_url,
                        status, generation_method, panel_position, image_model, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7,
                        $8, $9, $10, $11, $12, $13,
                        $14, $15, $16, $17, now(), now()
                    )""",
                    str(uuid.uuid4()),
                    self.tenant_id,
                    video_id,
                    video.get("video_title"),
                    scene,
                    index,
                    asset.get("sentence_index") or index,
                    asset.get("sentence_text"),
                    prompt,
                    asset.get("shot_type"),
                    asset.get("hero_shot") or False,
                    image_url,
                    drive_download_url,
                    "done",
                    "variant_candidate",
                    next_variant_position + offset,
                    model_used,
                )
                created += 1

            if created == 0:
                raise Exception("No image variants were generated successfully")

            await self._log_activity(
                bot_name,
                video_id,
                "completed",
                f"Generated {created} variant(s) for scene {scene} image {index}",
            )
            # generation_ledger (checklist §0.3b/C08, priced per-model in
            # §0.3c/C09): model_used is known here (image_model_router
            # reports which of the 3 real image models drew the pixels) —
            # price with THAT model's real rate instead of the flat blended
            # default the other (model-unaware) image call sites still use.
            # kie_task_id intentionally left None (C16c): this row aggregates
            # `created` variants from `created` separate generate_scene_image_
            # for_model() calls (each with its own Kie task) into ONE ledger
            # row (units=created) — a single task id can't honestly represent
            # a batch, and a re-run of this loop mints brand-new task ids
            # anyway, so threading one wouldn't add real dedup protection
            # (see migration 093's header for the full audit). Contrast with
            # redraw_asset_image (coverage_to_app.py) and the two single-image
            # thumbnail paths below, which write one row per one task and DO
            # thread it.
            from actions import picture_price_for
            picture_cost = picture_price_for(model_used)
            await record_ledger_entry(
                tenant_id=self.tenant_id, video_id=video_id, stage="image",
                model=model_used, units=created, unit_cost=picture_cost,
                actual_cost=round(created * picture_cost, 2),
            )
            return {"status": video.get("status"), "video_id": video_id, "variants_created": created}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_sound_prompts(self, video_id: str) -> dict:
        """Generate sound design prompts for a video."""
        bot_name = "Sound Design Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")

            # SFX guard, INNER backstop (status_map.render_path_plays_sfx —
            # see run_render's dispatch comment and _skip_sound_stage's
            # docstring): this is the ONE place a paid sound-prompt
            # generation can actually begin, so this is the check that makes
            # "no spend for a render path that drops the result" true for
            # EVERY caller — REST, chat, MCP, ClaudeOrchestrator.execute, or
            # anything written after this comment — not just the ones that
            # happen to check first. The REST endpoint / actions.py verb /
            # auto-advance checks above this in the call chain are UX polish
            # (a fast 400 / a disabled button); this is the backstop.
            #
            # Checked BEFORE _ensure_initialized() (deliberately out of the
            # usual order every other run_* method uses — init first, then
            # fetch the video) so a blocked video costs NOTHING: no vault key
            # loads, no bot construction, no network call of any kind, not
            # just no Kie.ai spend.
            if not render_path_plays_sfx(video):
                return await self._skip_sound_stage(
                    video_id, video, current_status, "ready_for_sound_effects")

            await self._ensure_initialized()
            await self._log_activity(bot_name, video_id, "started", "Generating sound prompts")

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_sound_prompt_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_sound_effects")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Sound prompts generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_sound_effects(self, video_id: str) -> dict:
        """Generate sound effects for a video."""
        bot_name = "Sound Effects Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")

            # SFX guard, INNER backstop — see run_sound_prompts's identical
            # check just above for the full rationale, including WHY this
            # runs before _ensure_initialized(). This is the ONE place a
            # paid Kie.ai sound-EFFECT generation can actually begin.
            if not render_path_plays_sfx(video):
                return await self._skip_sound_stage(
                    video_id, video, current_status, "ready_for_video_scripts")

            await self._ensure_initialized()
            await self._log_activity(bot_name, video_id, "started", "Generating sound effects")

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_sound_bot()

            # generation_ledger (checklist §0.3b / C08): one row per run, sized
            # to what actually generated. Reuses SoundClient's OWN existing
            # per-generation price (shared/clients/sound_client.py
            # ESTIMATED_COST_PER_GENERATION) rather than actions.py's separate
            # flat SOUND_COST_ESTIMATE — sound_bot.py already multiplies it out
            # into result["estimated_cost"] for the Slack notification above,
            # so this is the SAME number, not a new one. Fail-soft internally.
            total_generated = result.get("total_generated", 0)
            if total_generated > 0:
                from shared.clients.sound_client import SoundClient
                await record_ledger_entry(
                    tenant_id=self.tenant_id,
                    video_id=video_id,
                    stage="sound",
                    model=SoundClient.MODEL,
                    units=total_generated,
                    unit_cost=SoundClient.ESTIMATED_COST_PER_GENERATION,
                    actual_cost=result.get(
                        "estimated_cost",
                        round(total_generated * SoundClient.ESTIMATED_COST_PER_GENERATION, 2),
                    ),
                )

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_video_scripts")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Sound effects generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_video_scripts(self, video_id: str) -> dict:
        """Generate video motion scripts for a video."""
        await self._ensure_initialized()
        bot_name = "Video Script Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating video scripts")

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_video_script_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_video_generation")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Video scripts generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_video_generation(self, video_id: str) -> dict:
        """Generate video clips for a video."""
        await self._ensure_initialized()
        bot_name = "Video Gen Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating video clips")

            self._load_idea_from_video(video_id)

            await self._install_cancel_support(video_id)
            result = await self._pipeline.run_video_gen_bot()

            if result.get("cancelled"):
                kept = result.get("video_count", 0)
                msg = f"Stopped — kept {kept} completed clip(s). Run clip generation again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "cancelled", "video_id": video_id, "error": msg}

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "ready_for_thumbnail")

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Video clips generated")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def _run_channel_formula_thumbnail(
        self, video_id: str, video: dict
    ) -> Optional[dict]:
        """Own-brand thumbnail modeling: take the channel's OWN top-performing
        thumbnail, extract its structured JSON blueprint (vision pass, cached on
        channel_identity.thumbnail_blueprint), transform it onto THIS video's
        title, and generate. The same proven blueprint machinery as competitor
        modeling — the reference is simply the channel itself.

        Returns the completed result dict, or None to fall through to the
        legacy from-scratch designer (no own thumbnails / no Claude creds)."""
        import json as _json_cf
        from routes.model_video import _resolve_claude_creds, _describe_thumbnail_style

        bot_name = "Thumbnail Bot"
        top = await fetch_one(
            "SELECT thumbnail_url FROM channel_videos "
            "WHERE tenant_id = $1 AND thumbnail_url IS NOT NULL "
            "ORDER BY view_count DESC NULLS LAST LIMIT 1", self.tenant_id)
        if not (top and top.get("thumbnail_url")):
            return None
        creds = await _resolve_claude_creds(self.tenant_id)
        if not creds:
            return None

        # Blueprint: cached on the identity, or extracted now from the top thumb.
        blueprint = None
        row = await fetch_one(
            "SELECT channel_identity->>'thumbnail_blueprint' AS bp "
            "FROM channel_profiles WHERE tenant_id = $1", self.tenant_id)
        if row and (row.get("bp") or "").strip().startswith("{"):
            blueprint = row["bp"]
        if not blueprint:
            await self._log_activity(
                bot_name, video_id, "started",
                "Reading the channel's own top thumbnail formula (vision)")
            blueprint = await _describe_thumbnail_style(creds, top["thumbnail_url"])
            if not (blueprint or "").strip():
                return None
            try:
                # Checklist C40: routes through the shared provenance helper
                # (module-level _cache_channel_thumbnail_blueprint, above the
                # class) so this best-effort cache write can never clobber
                # identity_builder's fields, channel_format's visual_format/
                # format_locked, or the _sources/_history envelope.
                await _cache_channel_thumbnail_blueprint(self.tenant_id, blueprint)
            except Exception:  # noqa: BLE001 — cache is a bonus
                pass

        # Channel constants the model must not reinterpret:
        # 1) consensus formula (3-thumbnail extraction) as the style tie-breaker;
        # 2) the REAL background color, MEASURED as the median of a border ring
        #    on the maxres thumbnail (corner-averaging a letterboxed hqdefault
        #    sampled salmon-pink, live on DVU — median ring on maxres is robust).
        consensus = ""
        try:
            row = await fetch_one(
                "SELECT channel_identity->'thumbnail_style' AS ts "
                "FROM channel_profiles WHERE tenant_id = $1", self.tenant_id)
            ts = (row or {}).get("ts")
            if isinstance(ts, str):
                ts = _json_cf.loads(ts)
            if isinstance(ts, dict) and ts:
                consensus = _json_cf.dumps(ts, indent=1)
        except Exception:  # noqa: BLE001
            pass
        hexbg = await self._measure_channel_thumb_bg()

        # This video's REAL subject(s): the machines from the static segments.
        subjects = ""
        seed = None
        try:
            rows = await fetch_all(
                "SELECT image_url, caption FROM assets WHERE video_id=$1 AND tenant_id=$2 "
                "AND image_url IS NOT NULL AND generation_method='static_docu' "
                "ORDER BY scene", video_id, self.tenant_id)
            names = []
            for r in rows:
                cap = r.get("caption")
                if isinstance(cap, str):
                    cap = _json_cf.loads(cap)
                if isinstance(cap, dict) and cap.get("title"):
                    names.append(cap["title"])
            subjects = ", ".join(names[:5])
            if rows:
                seed = rows[0].get("image_url")
        except Exception:  # noqa: BLE001
            pass

        await self._log_activity(
            bot_name, video_id, "started",
            "Modeling the channel's own thumbnail formula onto this video")

        # A creator-edited prompt always wins (Regenerate refines it). It can be
        # the full structured JSON spec (preferred, editable field-by-field) or
        # plain text — both work.
        saved = (video.get("thumbnail_prompt") or "").strip()
        spec = None
        gen_prompt = None
        if saved:
            if saved.startswith("{"):
                try:
                    spec = _json_cf.loads(saved)
                except ValueError:
                    gen_prompt = saved
            else:
                gen_prompt = saved
        if spec is None and gen_prompt is None:
            spec = await self._transform_channel_thumbnail_spec(
                creds, blueprint, consensus, hexbg,
                video.get("video_title") or "", subjects)
        if spec is not None:
            gen_prompt = (spec.get("prompt") or "").strip()
            neg = (spec.get("negative_prompt") or "").strip()
            if neg:
                gen_prompt += f"\n\nAvoid (negative prompt): {neg}"
            bg = ((spec.get("color_palette") or {}).get("background") or "").strip()
            if bg:
                gen_prompt += f"\n\nBACKGROUND (exact, non-negotiable): {bg}."
            # QL-66 (OR-9 ruled, checklist C46e): advisory only - log, never
            # block a live thumbnail generation on a locked-phrase deviation.
            # bot_activity.status is a hard-CHECK'd enum (started/running/
            # completed/failed, no "warning") - "running" is the legal
            # non-terminal status other advisory logs in this file already use.
            primary_text = str(((spec.get("text") or {}).get("primary_text") or {}).get("content") or "")
            ql66_warning = _dvsu_thumbnail_series_warning(video.get("video_title") or "", primary_text)
            if ql66_warning:
                await self._log_activity(bot_name, video_id, "running", ql66_warning)
        if not gen_prompt:
            return None
        # What the creator sees/edits in the UI prompt box: the full spec.
        stored_prompt = (_json_cf.dumps(spec, indent=2) if spec is not None else gen_prompt)

        client = self._pipeline.image_client
        thumb_ar = video.get("aspect_ratio") or "16:9"

        # Subject fidelity: seed with THIS video's own hero segment image when
        # one exists (static docs: the real featured machine in the channel's
        # studio look) so the thumbnail shows our actual subject, not an
        # invented one. Text-to-image is the fallback.
        # Fresh box per call (checklist C16c) — one thumbnail, one ledger
        # row below; shared across the seed/fallback attempts so whichever
        # one succeeds contributes its real Kie task id.
        task_id_box: list = []
        res = None
        if seed:
            res = await client.generate_thumbnail_gpt2(
                gen_prompt + "\nUse the machine in the reference image as the "
                "thumbnail's subject — same vehicle, same configuration, no "
                "invented markings.",
                [seed], aspect_ratio=thumb_ar, task_id_out=task_id_box)
        if not (res or {}).get("url"):
            res = await client.generate_scene_image_gpt(
                gen_prompt, None, aspect_ratio=thumb_ar, task_id_out=task_id_box)
        url = (res or {}).get("url")
        if not url:
            await self._log_activity(
                bot_name, video_id, "failed",
                "Channel-formula thumbnail returned no image")
            return {"status": "failed", "error": user_facing(
                "The thumbnail didn't generate this time — tap Regenerate to try again.")}
        durable = await self._persist_url(url, f"{video_id}/thumbnails/thumb.png")
        await execute(
            "UPDATE videos SET thumbnail_url = $1, thumbnail_prompt = $2, "
            "updated_at = now() WHERE id = $3 AND tenant_id = $4",
            durable, stored_prompt, video_id, self.tenant_id)
        await self._log_activity(
            bot_name, video_id, "completed",
            "Thumbnail modeled from the channel's own formula")
        # generation_ledger (checklist §0.3b / C08): reuses actions.THUMBNAIL_COST,
        # the same flat number the confirm card quotes for the "thumbnail" verb.
        # kie_task_id (C16c): box[0] is the first task id created across the
        # seed/fallback attempts above — same convention as the clip path
        # (task_id_box[0]) — giving migration 093's dedup index real teeth.
        from actions import THUMBNAIL_COST
        await record_ledger_entry(
            tenant_id=self.tenant_id, video_id=video_id, stage="thumbnail",
            model="gpt-image-2", units=1, unit_cost=THUMBNAIL_COST,
            actual_cost=THUMBNAIL_COST,
            kie_task_id=(task_id_box[0] if task_id_box else None),
        )
        return {"status": "completed", "video_id": video_id,
                "thumbnail_url": durable}

    async def _measure_channel_thumb_bg(self) -> Optional[str]:
        """The channel's real thumbnail background color as an exact hex.

        Median of a border ring sampled on the MAXRES thumbnail of the top
        video (median beats averaging: compression noise and letterbox bars
        can't drag it; near-black letterbox pixels are dropped explicitly).
        Returns None when unmeasurable — callers must treat it as optional."""
        try:
            import io as _io_bg
            import httpx as _httpx_bg
            from PIL import Image as _Image_bg

            top = await fetch_one(
                "SELECT video_id, thumbnail_url FROM channel_videos "
                "WHERE tenant_id = $1 AND thumbnail_url IS NOT NULL "
                "ORDER BY view_count DESC NULLS LAST LIMIT 1", self.tenant_id)
            if not top:
                return None
            urls = []
            if top.get("video_id"):
                urls.append(f"https://i.ytimg.com/vi/{top['video_id']}/maxresdefault.jpg")
            urls.append(top.get("thumbnail_url"))
            data = None
            async with _httpx_bg.AsyncClient(timeout=30.0, follow_redirects=True) as c:
                for u in urls:
                    if not u:
                        continue
                    rr = await c.get(u)
                    if rr.status_code == 200 and len(rr.content) > 5000:
                        data = rr.content
                        break
            if not data:
                return None
            im = _Image_bg.open(_io_bg.BytesIO(data)).convert("RGB")
            w, h = im.size
            inset = max(6, w // 100)
            pts = []
            for i in range(12):
                x = inset + (w - 2 * inset) * i // 11
                pts += [(x, inset), (x, h - 1 - inset)]
            for i in range(6):
                y = inset + (h - 2 * inset) * i // 5
                pts += [(inset, y), (w - 1 - inset, y)]
            cols = [im.getpixel(p) for p in pts]
            lit = [c for c in cols if sum(c) > 60]  # drop letterbox bars
            cols = lit or cols
            med = tuple(sorted(c[i] for c in cols)[len(cols) // 2] for i in range(3))
            return "#%02X%02X%02X" % med
        except Exception:  # noqa: BLE001
            return None

    async def _transform_channel_thumbnail_spec(
        self, creds: dict, blueprint: str, consensus: str,
        hexbg: Optional[str], title: str, subjects: str,
    ) -> Optional[dict]:
        """Blueprint + consensus + measured constants + OUR topic -> the FULL
        structured thumbnail spec (format/style/scene/objects/composition/
        text/color_palette/prompt/negative_prompt). The spec is the editable
        source of truth; the flat generation prompt is derived from it."""
        import json as _json_ts
        from routes.model_video import _call_claude, _strip_code_fences

        brand = ""
        try:
            from routes.model_video import _fetch_channel_brand
            brand = await _fetch_channel_brand(self.tenant_id)
        except Exception:  # noqa: BLE001
            pass

        ask = (
            "You design YouTube thumbnails by MODELING a channel's proven formula "
            "onto a new video — never copying the reference image, always rebuilding "
            "its winning structure with our subject.\n\n"
            f"CHANNEL BLUEPRINT (vision-extracted from its top thumbnail):\n{blueprint}\n\n"
            + (f"CHANNEL CONSENSUS (across its top 3 thumbnails — wins any conflict "
               f"with the blueprint):\n{consensus}\n\n" if consensus else "")
            + (f"MEASURED CONSTANTS (authoritative, pixel-sampled from the channel's "
               f"real thumbnails — override any color words above): background = a "
               f"clean uniform studio backdrop of exactly {hexbg}.\n\n" if hexbg else "")
            + f"OUR VIDEO TITLE: {title}\n"
            + (f"OUR REAL SUBJECT(S): {subjects} — a reference image of the featured "
               "machine is supplied at generation time; the spec must describe THAT "
               "real machine, never an invented design.\n" if subjects else "")
            + (f"CHANNEL BRAND: {brand}\n" if brand else "")
            + "\nReply with ONE JSON object only, with EXACTLY these keys:\n"
            '{"format": "youtube_thumbnail", "aspect_ratio": "16:9",\n'
            ' "style": {"medium","look","lighting","mood"},\n'
            ' "scene": {"setting","main_action","click_moment","focal_point","secondary_focal_point"},\n'
            ' "objects": [{"object","description","position"}],\n'
            ' "composition": {"camera","layout","depth_of_field","thumbnail_rules"},\n'
            ' "text": {"primary_text": {"content","placement","style"},'
            ' "secondary_text": {...}, "small_text": {...}},\n'
            ' "color_palette": {"background","main_object","text_primary","text_secondary","badge","accent"},\n'
            ' "prompt": "<one rich self-contained generation prompt consistent with every field above>",\n'
            ' "negative_prompt": "<thorough>"}\n\n'
            "Rules:\n"
            "- Every field detailed and concrete (positions, sizes as % of frame, exact hexes).\n"
            "- The subject is the REAL machine named above — accurate configuration, and "
            "ABSOLUTELY NO invented text/stencils/markings on the vehicle.\n"
            "- color_palette.background must be the measured hex verbatim when given.\n"
            "- Text uses the channel's split-color treatment from the formula.\n"
            "- The 'prompt' field must restate the background hex and the no-invented-text rule."
        )
        try:
            raw = await _call_claude(ask, creds, tier="smart", max_tokens=4000)
            spec = _json_ts.loads(_strip_code_fences(raw))
            return spec if isinstance(spec, dict) and spec.get("prompt") else None
        except Exception as e:  # noqa: BLE001
            _logger.warning("channel thumbnail spec transform failed: %s", str(e)[:200])
            return None

    async def _build_modeled_thumbnail_prompt(
        self, video_id: str, video: dict, ref_yt: str, has_cast: bool
    ) -> str:
        """JSON-blueprint modeling: turn the reference thumbnail into OUR modeled
        thumbnail prompt — our story + our channel brand, in the reference's proven
        winning formula. Reads the structured blueprint (stored at modeling time, or
        generated on the fly for older videos), transforms it against our title/brand/
        cast via Claude, and returns a single rich generation prompt (negatives baked
        in, content-safety enforced). Falls back to the text-assembly builder if the
        LLM path is unavailable so Regenerate never dead-ends."""
        try:
            from routes.model_video import (
                _resolve_claude_creds, _describe_thumbnail_style,
                _model_thumbnail_prompt, _fetch_channel_brand)
            creds = await _resolve_claude_creds(self.tenant_id)
            if creds:
                blueprint = (video.get("thumbnail_style_override") or "").strip()
                if not blueprint.startswith("{"):
                    # Older video without a stored JSON blueprint — read it now.
                    ref_thumb = f"https://img.youtube.com/vi/{ref_yt}/maxresdefault.jpg"
                    blueprint = (await _describe_thumbnail_style(creds, ref_thumb)) or blueprint
                brand = await _fetch_channel_brand(self.tenant_id)
                names = ""
                try:
                    rows = await fetch_all(
                        "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2 ORDER BY sort",
                        video_id, self.tenant_id)
                    names = ", ".join((r.get("name") or "").strip() for r in rows if r.get("name"))
                except Exception:
                    pass
                modeled = await _model_thumbnail_prompt(
                    creds, blueprint, video.get("video_title") or "", brand, names, has_cast)
                if modeled:
                    return modeled
        except Exception as e:
            await self._log_activity(
                "Thumbnail Bot", video_id, "running",
                f"JSON modeling unavailable, using fallback ({str(e)[:100]})")
        return await self._build_thumbnail_model_prompt(video_id, video, has_cast=has_cast)

    async def _build_thumbnail_model_prompt(
        self, video_id: str, video: dict, has_cast: bool = True
    ) -> str:
        """Modeled thumbnail prompt (MODEL, not copy): design OUR OWN thumbnail of
        OUR video's moment — driven by our title — applying the reference's winning
        FORMULA + STYLE (stored in thumbnail_style_override) and proven thumbnail
        rules. Never traces the reference's image. has_cast=True frames it around the
        cast sheet (character videos, image-to-image); has_cast=False frames a faceless
        EVENT/iconography scene (explainer/documentary, text-to-image). Seeded into
        thumbnail_prompt for in-app refine."""
        names = ""
        try:
            rows = await fetch_all(
                "SELECT name FROM video_characters WHERE video_id = $1 AND tenant_id = $2 ORDER BY sort",
                video_id, self.tenant_id)
            names = ", ".join((r.get("name") or "").strip() for r in rows if r.get("name"))
        except Exception:
            pass
        signature = (video.get("thumbnail_style_override") or "").strip()
        text = (video.get("thumbnail_text") or "").strip()
        title = (video.get("video_title") or "").strip()
        ar = video.get("aspect_ratio") or "16:9"
        # Subject is driven by OUR title (drop the "| channel suffix").
        clean_title = title.split("|")[0].strip()

        parts = [
            f"YouTube thumbnail, {ar}. Design a NEW, ORIGINAL thumbnail for OUR video. We are "
            "MODELING a proven competitor's winning thumbnail formula — not copying it: do NOT "
            "reproduce any competitor image, scene, object or composition. Build our own.",
        ]
        if has_cast:
            parts.append(
                "The reference image provided is OUR OFFICIAL CHARACTER CAST SHEET — reproduce these "
                "EXACT characters (same faces, hair, skin tone, ages and clothing) and keep their "
                "rendering style; never invent or substitute anyone.")
            if names:
                parts.append(f"The cast is: {names}.")
            subject = (
                "Stage the single most click-worthy moment this title promises — its surprising "
                "reveal or payoff, caught the instant it happens — as our own original scene with our cast.")
        else:
            parts.append(
                "This is a FACELESS video — there is NO recurring cast. Build our own original scene "
                "or bold iconography; any people are generic and incidental, not a fixed character.")
            subject = (
                "Depict the single most click-worthy MOMENT or visual this title promises — show the "
                "EVENT or the charged subject the instant it lands (not a flat, static object shot). "
                "Use one clear, instantly-readable focal subject plus simple iconography (arrows, "
                "highlights, split-screen, glowing charts) where it sharpens the idea.")
        if clean_title:
            parts.append(f'OUR video is titled "{clean_title}". ' + subject)
        if signature:
            parts.append(
                "Apply this proven winning STYLE and CLICK FORMULA (match the look and the pattern, "
                "but on OUR subject above — never the reference's specific objects): " + signature)
        # Overlay text is part of the MODELED formula: render OUR words in the
        # reference's text TREATMENT and LAYOUT — big and bold, spanning across the
        # screen the same way (same scale, tiers, colors, outline). The text style
        # comes from the signature above; the WORDS are ours.
        if text:
            headline_clause = f'render the headline reading exactly "{text}"'
        else:
            headline_clause = (
                f'render a large, punchy headline that captures OUR title\'s hook (derived from '
                f'"{clean_title}", not a verbatim copy of it)')
        parts.append(
            "MODEL THE TEXT: " + headline_clause + ". Make it BIG and BOLD, spanning across the "
            "screen in the SAME text treatment and layout as the reference described above — match "
            "its scale, number of tiers, color per tier, font weight/case and heavy outline. The "
            "text is a primary element, not a small label.")
        # Proven hard rules (from the YouTube intelligence ruleset).
        parts.append(
            "Follow proven thumbnail rules: ONE clear focal point and at most THREE distinct "
            "elements; exaggerated facial emotion; bright with extreme contrast so it pops in dark "
            "mode; a single 'click-to-unpause' moment; text readable at 120px. No competitor "
            "logos, watermarks or badges.")
        return " ".join(parts)

    async def run_thumbnail(self, video_id: str, force: bool = False) -> dict:
        """Generate thumbnail for a video.

        `force` (C16d, S7-3): default False skips generation (and the paid
        ledger write) when videos.thumbnail_url is already set — every one of
        the three completion branches below (modeled/channel-formula/legacy
        from-scratch) previously regenerated + rebilled unconditionally on
        every call, including a routine status-machine resume that reaches
        this stage a second time. force=True (the ONLY way to bypass the
        guard) is threaded in explicitly by every caller that represents a
        real "redo it" request: the ACTIONS["thumbnail"] chat/button verb
        (actions.py's make_action_step), the prompt-studio "Apply & redo"
        path (routes/chat.py's _make_prompt_regen), and the Scenes page's
        Regenerate button (routes/pipeline.py's POST /thumbnail/{video_id},
        which now accepts ?force=true — mirroring the existing
        POST /clip/{video_id} convention). Callers that represent natural
        first-time progression (the autobuild finish chain, the arq/queue
        stage runner, claude_orchestrator's skill dispatch) pass nothing and
        get the skip-if-done default, same as C16b's coverage guard.
        """
        await self._ensure_initialized()
        bot_name = "Thumbnail Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            if not force and (video.get("thumbnail_url") or "").strip():
                msg = "Thumbnail already exists — skipping (already generated)."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id,
                        "thumbnail_url": video["thumbnail_url"], "message": msg,
                        "skipped": True}

            current_status = video.get("status")

            # ── Modeled mode (model, NOT copy) ────────────────────────
            # When the video was modeled on a reference video (reference_url),
            # design OUR OWN thumbnail of OUR story's moment using the reference's
            # winning FORMULA + STYLE — never tracing the reference's image. Works
            # for ANY video, with or without a cast:
            #   • cast videos    → generate from the CAST SHEET ONLY (it carries our
            #     characters + the modeled look, so the composition stays fresh and
            #     our cast can't be overwritten).
            #   • faceless videos (explainer/documentary, no cast sheet) → build the
            #     scene from text (GPT Image 2 text-to-image); the style signature in
            #     the prompt carries the modeled look.
            # The editable thumbnail_prompt drives refinement: every Regenerate
            # re-runs with whatever prompt is saved. Status stays at ready_for_thumbnail
            # so Regenerate keeps working — the creator clicks Approve & Advance when happy.
            import re as _re_thumb
            _ref = (video.get("reference_url") or "")
            _m = (_re_thumb.search(r"[?&]v=([\w-]{11})", _ref)
                  or _re_thumb.search(r"youtu\.be/([\w-]{11})", _ref)
                  or _re_thumb.search(r"/embed/([\w-]{11})", _ref)
                  or _re_thumb.search(r"/shorts/([\w-]{11})", _ref))
            ref_yt = _m.group(1) if _m else None
            cast_sheet = (video.get("character_reference_url") or "").strip()
            if ref_yt:
                has_cast = bool(cast_sheet)
                await self._log_activity(
                    bot_name, video_id, "started",
                    "Modeling thumbnail on the reference's winning formula"
                    + ("" if has_cast else " (faceless)"))
                prompt = (video.get("thumbnail_prompt") or "").strip()
                if not prompt:
                    prompt = await self._build_modeled_thumbnail_prompt(
                        video_id, video, ref_yt, has_cast)
                client = self._pipeline.image_client
                thumb_ar = video.get("aspect_ratio") or "16:9"
                # Fresh box per call (checklist C16c) — one thumbnail, one
                # ledger row below; shared across the cast/fallback attempts
                # so whichever one succeeds contributes its real Kie task id.
                task_id_box: list = []
                if has_cast:
                    # CAST SHEET ONLY — the one authoritative seed image (identities +
                    # the modeled look). GPT Image 2 holds character identity best (live
                    # A/B); nano-banana-pro fallback so Regenerate never dead-ends.
                    res = await client.generate_thumbnail_gpt2(
                        prompt, [cast_sheet], aspect_ratio=thumb_ar, task_id_out=task_id_box)
                    if not (res or {}).get("url"):
                        res = await client.generate_with_reference(
                            prompt, [cast_sheet], aspect_ratio=thumb_ar, task_id_out=task_id_box)
                else:
                    # FACELESS — no cast sheet to seed from. Build from text: GPT Image 2
                    # text-to-image. The style signature in the prompt carries the look.
                    res = await client.generate_scene_image_gpt(
                        prompt, None, aspect_ratio=thumb_ar, task_id_out=task_id_box)
                url = (res or {}).get("url")
                if not url:
                    await self._log_activity(bot_name, video_id, "failed",
                                             "Modeled thumbnail returned no image")
                    return {"status": "failed", "error": user_facing(
                        "The thumbnail didn't generate this time — tap Regenerate to try again.")}
                durable = await self._persist_url(url, f"{video_id}/thumbnails/thumb.png")
                await execute(
                    "UPDATE videos SET thumbnail_url = $1, thumbnail_prompt = $2, "
                    "updated_at = now() WHERE id = $3 AND tenant_id = $4",
                    durable, prompt, video_id, self.tenant_id,
                )
                await self._log_activity(bot_name, video_id, "completed",
                                         "Thumbnail modeled from reference")
                # generation_ledger (checklist §0.3b / C08): same reuse as the
                # channel-formula path above — actions.THUMBNAIL_COST.
                # kie_task_id (C16c): box[0] is the first task id created
                # across the cast/fallback attempts above — same convention
                # as the clip path (task_id_box[0]).
                from actions import THUMBNAIL_COST
                await record_ledger_entry(
                    tenant_id=self.tenant_id, video_id=video_id, stage="thumbnail",
                    model="gpt-image-2", units=1, unit_cost=THUMBNAIL_COST,
                    actual_cost=THUMBNAIL_COST,
                    kie_task_id=(task_id_box[0] if task_id_box else None),
                )
                return {"status": "completed", "video_id": video_id,
                        "thumbnail_url": durable}

            # ── Channel-formula mode (own-brand modeling) ─────────────
            # No reference video, but the channel HAS its own proven
            # thumbnails (an onboarded existing channel like Designed vs
            # Used): model the channel's own top thumbnail — vision pass →
            # JSON blueprint → transformed onto OUR title — the exact same
            # proven machinery as competitor modeling, pointed at the brand
            # itself. Falls through to the legacy bot on any failure.
            try:
                own = await self._run_channel_formula_thumbnail(video_id, video)
                if own is not None:
                    return own
            except Exception as e:  # noqa: BLE001
                await self._log_activity(
                    bot_name, video_id, "running",
                    f"Channel-formula thumbnail unavailable ({str(e)[:100]}) — using the standard designer")

            # ── From-scratch mode (existing bot) ──────────────────────
            await self._log_activity(bot_name, video_id, "started", "Generating thumbnail")

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            self._load_idea_from_video(video_id)

            # The legacy bot expects the pipeline-format status; override like
            # run_voice does so a regenerate works from any current status.
            if self._pipeline.current_idea:
                self._pipeline.current_idea["Status"] = "Ready For Thumbnail"

            result = await self._pipeline.run_thumbnail_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "done")

            # Save thumbnail URL back to videos table (persist to Supabase Storage)
            thumbnail_url = result.get("thumbnail_url")
            if thumbnail_url:
                thumbnail_url = await self._persist_url(
                    thumbnail_url, f"{video_id}/thumbnails/thumb.png"
                )
                await execute(
                    "UPDATE videos SET thumbnail_url = $1, updated_at = now() WHERE id = $2",
                    thumbnail_url, video_id,
                )

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Thumbnail generated")
            # generation_ledger (checklist §0.3b / C08): same actions.THUMBNAIL_COST
            # reuse as the modeled/channel-formula paths above (mutually exclusive
            # branches — only one of the three thumbnail paths runs per call, so
            # no double-count risk between them).
            # kie_task_id intentionally left None (C16c): this is the legacy
            # "from-scratch" path — `self._pipeline.run_thumbnail_bot()` calls
            # into the separate skills/video-pipeline `thumbnail.run` bot,
            # which doesn't surface a Kie task id back through `result` today.
            # Not threaded here; see migration 093's header for the full
            # per-stage audit of what's protected vs. still None.
            from actions import THUMBNAIL_COST
            await record_ledger_entry(
                tenant_id=self.tenant_id, video_id=video_id, stage="thumbnail",
                model=None, units=1, unit_cost=THUMBNAIL_COST,
                actual_cost=THUMBNAIL_COST,
            )

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def _run_stitch_render(
        self, video_id: str, video: dict, current_status: str,
        orientation: str = "auto",
    ) -> dict:
        """Fast render for grok_native videos — FFmpeg-stitch the existing
        clips (each already carries Grok's baked-in audio) into the final video.

        Bypasses the Remotion path's two blockers (missing render_config.json;
        Scene.tsx muting clips while playing the narrator). Clips that differ in
        size/orientation are normalized onto one canvas (scale+pad), joined in a
        single encode, and each render works in its own temp dir. orientation:
        'auto'|'portrait'|'landscape'. See render_stitch.py.
        """
        bot_name = "Render Bot"
        await self._log_activity(
            bot_name, video_id, "started", "Stitching clips into final video"
        )

        async def _progress(msg: str) -> None:
            await self._log_activity(bot_name, video_id, "running", msg)

        from render_stitch import stitch_video

        result = await stitch_video(
            video_id,
            self.tenant_id,
            title=video.get("video_title") or "",
            orientation=orientation,
            on_progress=_progress,
        )

        final_url = result["final_video_url"]
        await execute(
            "UPDATE videos SET final_video_url = $1 WHERE id = $2",
            final_url, video_id,
        )
        from drive_workspace import sync_video_workspace_fail_soft
        await sync_video_workspace_fail_soft(video_id, self.tenant_id)
        await self._update_video_status(video_id, to_supabase("rendered"))
        await self._log_transition(video_id, current_status, to_supabase("rendered"), "api")

        duration_min = max(1, round(result.get("duration_seconds", 0) / 60))
        await self._charge_render_minutes(video_id, duration_min)

        await self._log_activity(
            bot_name, video_id, "completed",
            f"Stitched {result['clip_count']} clips "
            f"({result['duration_seconds']:.0f}s, {result.get('resolution', '?')} "
            f"{result.get('orientation', '')}) into final video",
        )
        return {
            "status": to_supabase("rendered"),
            "video_id": video_id,
            "final_video_url": final_url,
            "clip_count": result["clip_count"],
            "duration_seconds": result["duration_seconds"],
            "resolution": result.get("resolution"),
            "orientation": result.get("orientation"),
            "method": result["method"],
        }

    async def _run_perform_render(
        self, video_id: str, video: dict, current_status: str,
        orientation: str = "auto",
    ) -> dict:
        """Final render for character-dialogue voice_over videos — the
        performance-track assembler (render_perform.py): one audio track per
        scene built from the dialogue segments, every shot timed to its
        segment's span, all clips muted."""
        bot_name = "Render Bot"
        await self._log_activity(
            bot_name, video_id, "started",
            "Assembling the performance track and final video"
        )

        async def _progress(msg: str) -> None:
            await self._log_activity(bot_name, video_id, "running", msg)

        from render_perform import render_performance_video

        result = await render_performance_video(
            video_id,
            self.tenant_id,
            title=video.get("video_title") or "",
            orientation=orientation,
            on_progress=_progress,
        )

        final_url = result["final_video_url"]
        await execute(
            "UPDATE videos SET final_video_url = $1 WHERE id = $2",
            final_url, video_id,
        )
        from drive_workspace import sync_video_workspace_fail_soft
        await sync_video_workspace_fail_soft(video_id, self.tenant_id)
        await self._update_video_status(video_id, to_supabase("rendered"))
        await self._log_transition(video_id, current_status, to_supabase("rendered"), "api")

        duration_min = max(1, round(result.get("duration_seconds", 0) / 60))
        await self._charge_render_minutes(video_id, duration_min)

        await self._log_activity(
            bot_name, video_id, "completed",
            f"Assembled {result['clip_count']} timed shots across "
            f"{result['scene_count']} scene(s) "
            f"({result['duration_seconds']:.0f}s, {result.get('resolution', '?')} "
            f"{result.get('orientation', '')}) into the final video",
        )
        return {
            "status": to_supabase("rendered"),
            "video_id": video_id,
            "final_video_url": final_url,
            "clip_count": result["clip_count"],
            "scene_count": result["scene_count"],
            "duration_seconds": result["duration_seconds"],
            "resolution": result.get("resolution"),
            "orientation": result.get("orientation"),
            "method": result["method"],
            "warnings": result.get("warnings") or [],
        }

    async def _run_static_render(
        self, video_id: str, video: dict, current_status: str,
    ) -> dict:
        """Static-documentary render (render_mode='static_docu') — one to three
        verified views per narration segment, with a continuous title/spec card
        and smooth alternating push-in/pull-out motion. No animated clips.
        See render_static.py."""
        bot_name = "Render Bot"
        await self._log_activity(
            bot_name, video_id, "started", "Rendering the static documentary"
        )

        async def _progress(msg: str) -> None:
            await self._log_activity(bot_name, video_id, "running", msg)

        from render_static import render_static_video

        result = await render_static_video(
            video_id,
            self.tenant_id,
            title=video.get("video_title") or "",
            on_progress=_progress,
        )

        final_url = result["final_video_url"]
        await execute(
            "UPDATE videos SET final_video_url = $1 WHERE id = $2",
            final_url, video_id,
        )
        from drive_workspace import sync_video_workspace_fail_soft
        await sync_video_workspace_fail_soft(video_id, self.tenant_id)
        await self._update_video_status(video_id, to_supabase("rendered"))
        await self._log_transition(video_id, current_status, to_supabase("rendered"), "api")

        duration_min = max(1, round(result.get("duration_seconds", 0) / 60))
        await self._charge_render_minutes(video_id, duration_min)

        await self._log_activity(
            bot_name, video_id, "completed",
            f"Rendered {result['scene_count']} aircraft segments "
            f"({result['duration_seconds']:.0f}s, {result.get('resolution', '?')}) "
            f"into the final documentary",
        )
        return {
            "status": to_supabase("rendered"),
            "video_id": video_id,
            "final_video_url": final_url,
            "scene_count": result["scene_count"],
            "duration_seconds": result["duration_seconds"],
            "resolution": result.get("resolution"),
            "method": result["method"],
        }

    async def _run_custom_film_render(
        self,
        video_id: str,
        video: dict,
        current_status: str,
        *,
        runtime_job_id: str | None = None,
    ) -> dict:
        """One render-door dispatch into the dedicated section compositor."""
        bot_name = "Render Bot"
        await self._log_activity(
            bot_name,
            video_id,
            "started",
            "Assembling the approved Custom Film sections",
        )

        async def _progress(message: str) -> None:
            await self._log_activity(bot_name, video_id, "running", message)

        from custom_film_compositor import render_custom_film_video
        from custom_film_remotion import (
            AUTOMATIC_RENDER_POLICY,
            run_remotion_renderer,
        )

        result = await render_custom_film_video(
            video_id,
            self.tenant_id,
            title=video.get("video_title") or "",
            on_progress=_progress,
            render_engine=AUTOMATIC_RENDER_POLICY,
            remotion_renderer=run_remotion_renderer,
            runtime_job_id=runtime_job_id,
        )
        if result.get("status") != "rendered" or not result.get("final_video_url"):
            raise RuntimeError("Custom Film compositor returned no exact final artifact")
        if result.get("render_engine") not in {"ffmpeg", "remotion"}:
            raise RuntimeError("Custom Film compositor returned no renderer identity")
        await self._log_transition(
            video_id, current_status, to_supabase("rendered"), "api"
        )
        await self._charge_render_minutes(
            video_id,
            max(1, round(float(result["duration_seconds"]) / 60)),
        )
        await self._log_activity(
            bot_name,
            video_id,
            "completed",
            f"Assembled {result['section_count']} approved sections "
            f"({result['duration_seconds']:.0f}s, {result['resolution']}) "
            f"into one exact Custom Film with {result['render_engine']}",
        )
        return result

    async def _charge_render_minutes(self, video_id: str, minutes) -> None:
        """Charge render minutes idempotently — only the delta above what this
        video was already charged. Re-renders (edit/retry) of one deliverable
        don't keep eating the customer's monthly allowance. Best-effort:
        billing must never block delivery of a finished render."""
        try:
            from routes.billing import increment_usage
            minutes = max(1, int(round(float(minutes or 0))))
            row = await fetch_one(
                """UPDATE videos AS v
                   SET render_minutes_charged = GREATEST(COALESCE(v.render_minutes_charged, 0), $2)
                   FROM (SELECT COALESCE(render_minutes_charged, 0) AS prev
                         FROM videos WHERE id = $1 AND tenant_id = $3) old
                   WHERE v.id = $1 AND v.tenant_id = $3
                   RETURNING GREATEST(COALESCE(v.render_minutes_charged, 0), $2) - old.prev AS delta""",
                video_id, minutes, self.tenant_id,
            )
            delta = float(row["delta"]) if row and row.get("delta") is not None else 0
            if delta > 0:
                await increment_usage(self.tenant_id, "render_minutes", delta)
        except Exception:
            pass

    async def run_render(
        self,
        video_id: str,
        orientation: str = "auto",
        *,
        custom_film_runtime_job_id: str | None = None,
    ) -> dict:
        """Render final video.

        C57 audit fix: routes/pipeline.py::run_render (the HTTP door) calls
        `check_plan_limits(tenant_id, "render")` BEFORE ever reaching this
        method — but chat's "render"/"build" verbs (actions.make_action_step/
        make_autobuild_step -> this method directly), MCP's SAME "render"/
        "build" tools (they dispatch through the identical actions.py path),
        and the autopilot full-auto continuation loop (PipelineExecutor.
        run_next_step's status-map dispatch -> self.run_render) all call
        THIS method directly, bypassing that route entirely. Only the HTTP
        door was ever gated; render-minute cap enforcement was a no-op for
        every other caller. The gate belongs at the ONE method every caller
        converges on, not duplicated at each door — fail the SAME way this
        method's other error paths already do (a {"status":"failed",
        "error":...} dict, never raise) so every caller's existing
        `result.get("error")` handling picks it up unchanged. The route's
        own pre-check is left in place (redundant, but harmless — a fast,
        synchronous 402 before it even queues a background task).
        """
        await self._ensure_initialized()
        from fastapi import HTTPException as _HTTPException
        from routes.billing import check_plan_limits
        try:
            await check_plan_limits(self.tenant_id, "render")
        except _HTTPException as e:
            detail = e.detail
            if isinstance(detail, dict):
                detail = detail.get("message") or "Render limit reached for your plan."
            return {"status": "failed", "error": detail}
        bot_name = "Render Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")

            # SFX guard: the four early-return branches below (custom_film,
            # static_docu, grok_native stitch, character_dialogue perform)
            # each render through a closed audio schema with no sound-effects
            # track — only the fallback at the bottom of this dispatch (the
            # legacy Remotion bot) ever mixes in assets.sound_effect_url.
            # status_map.render_path_plays_sfx() mirrors this exact branch
            # order so every other caller (routes/pipeline.py's sound
            # endpoints, actions.py's "sound" verb, the auto-advance status
            # map, the frontend's Sound tab / stage checkbox) can answer
            # "will SFX play?" without re-deriving these branches — if you
            # change the order or the conditions here, update that function
            # too, in the same order, or the two will drift.

            # Custom Film is interpreted exactly once at the render boundary.
            # Media/provider callers remain profile-agnostic.
            if video.get("custom_film_plan_id"):
                return await self._run_custom_film_render(
                    video_id,
                    video,
                    current_status,
                    runtime_job_id=custom_film_runtime_job_id,
                )

            # grok_native videos carry Grok's dialogue baked into each clip, so
            # the final video is just the clips stitched in order — no Remotion,
            # no render_config.json/Whisper, no muted-clip+narrator bug. Clips
            # that differ in orientation are normalized onto one canvas. Each
            # render is isolated (own temp dir), so many can run at once.
            # voice_over videos still use the Remotion timeline (narrator) below.
            # static_docu videos (image-per-segment documentaries) render via
            # the Supabase-native Remotion path — checked FIRST since their
            # dialogue_audio is voice_over.
            if (video.get("render_mode") or "") == "static_docu":
                return await self._run_static_render(video_id, video, current_status)
            if (video.get("dialogue_audio") or "voice_over") == "grok_native":
                return await self._run_stitch_render(
                    video_id, video, current_status, orientation)
            # character_dialogue + voice_over: the performance-track assembler
            # lays every segment voice (narrator + character lines) on one
            # per-scene track, times each shot to its segment, and plays the
            # clips muted — see render_perform.py.
            if (video.get("dialogue_mode") or "") == "character_dialogue":
                return await self._run_perform_render(
                    video_id, video, current_status, orientation)

            await self._log_activity(bot_name, video_id, "started", "Rendering video")

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_render_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "rendered")

            # Update with video URL if available
            video_url = result.get("video_url")
            if video_url:
                await execute(
                    "UPDATE videos SET final_video_url = $1 WHERE id = $2",
                    video_url, video_id,
                )

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Video rendered")

            duration = video.get("video_length_minutes") or 10
            await self._charge_render_minutes(video_id, duration)

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_upload(self, video_id: str, force: bool = False) -> dict:
        """Generate SEO metadata and upload video to YouTube as unlisted draft.

        `force` (C16e, S7-9 follow-up — mirrors C16d's run_thumbnail guard
        exactly): default False skips the upload (the per-tenant native path)
        when the video already has a recorded youtube_video_id/youtube_url —
        every one of this method's callers previously re-ran the full upload
        unconditionally on a second invocation, which mints a genuine SECOND
        YouTube draft (recoverable by deleting it in Studio, but burns
        another one of the shared project's 100 daily upload calls and confuses the creator with
        two drafts). force=True (the ONLY way to bypass the guard) is not
        yet threaded from any caller by default — every real caller (the
        autobuild finish chain via run_next_step, the arq/queue stage
        runner, claude_orchestrator's skill dispatch, the manual POST
        /upload/{video_id} route, and the chat "upload" verb via
        actions.make_action_step) passes nothing and gets the skip-if-done
        default. routes/pipeline.py exposes `?force=true` on the manual
        route (mirroring the existing POST /thumbnail/{video_id}?force=true
        convention) for a future genuinely-new-upload affordance; no caller
        sets it today.

        S10-1 (C34a, audit finding — multi-tenant branding sweep): there is
        NO legacy-bot fallback here anymore. A tenant with no connected
        YouTube channel (`channel_profiles.youtube_refresh_token`) gets a
        clear failure, full stop. The old fallback called into
        skills/video-pipeline/upload/ (via a now-deleted `run_upload_bot`
        shim in `_ensure_initialized` — the SaaS backend has no remaining
        import path to that package; it's still used, correctly, by Ryan's
        own Airtable-driven cron pipeline at
        skills/video-pipeline/orchestrator/pipeline.py:859), which
        (a) hardcodes @Power_Doctrine SEO defaults onto the wrong
        tenant's video, (b) uploads through Ryan's own shared VPS OAuth
        token files — i.e. onto RYAN'S personal channel, category 25 — not
        the tenant's, and (c) never passed through C33's YouTube quota
        guard (that guard lives in `youtube_publish.upload_video_to_youtube`,
        the native path's function, not in the legacy bot). None of that is
        recoverable after the fact — it publishes. See
        `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` §S10-1.
        """
        await self._ensure_initialized()
        bot_name = "YouTube Upload Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            existing_url = (video.get("youtube_url") or "").strip()
            existing_id = (video.get("youtube_video_id") or "").strip()
            if not force and (existing_url or existing_id):
                msg = f"Already uploaded to YouTube — skipping (existing draft: {existing_url or existing_id})."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id,
                        "youtube_url": existing_url or None,
                        "youtube_video_id": existing_id or None,
                        "message": msg, "skipped": True}

            await self._log_activity(bot_name, video_id, "started", "Uploading to YouTube")

            # Supabase-native, per-tenant path: if the creator has connected their OWN
            # YouTube channel, upload there using the stored SEO (no Airtable, no shared
            # token, no Power Doctrine defaults).
            cp = await fetch_one(
                "SELECT youtube_refresh_token FROM channel_profiles WHERE tenant_id=$1",
                self.tenant_id)
            if cp and cp.get("youtube_refresh_token"):
                from youtube_publish import generate_and_store_seo, upload_video_to_youtube
                # Only auto-generate when there's no SEO yet — never clobber the
                # creator's edited/saved description+tags.
                if not (video.get("seo_description") or "").strip():
                    seo = await generate_and_store_seo(video_id, self.tenant_id)
                    if seo.get("error"):
                        raise Exception(seo["error"])
                up = await upload_video_to_youtube(video_id, self.tenant_id)
                if up.get("error"):
                    raise Exception(up["error"])
                await self._log_activity(
                    bot_name, video_id, "completed",
                    f"Uploaded to YouTube ({up.get('channel') or 'your channel'}) as an unlisted draft")
                return {"status": "uploaded_draft", "video_id": video_id,
                        "video_url": up.get("youtube_url")}

            # S10-1: no connected channel — fail clearly. Do NOT fall through to
            # skills/video-pipeline/upload/'s legacy bot (see class docstring above).
            error_msg = "Connect your YouTube channel first — Settings → YouTube."
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}
