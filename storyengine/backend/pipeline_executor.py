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

# Each bot folder has internal imports (e.g., script/run.py imports brief_translator).
# Add bot subdirectories to sys.path so these resolve correctly.
for bot_dir in ["script", "voice", "image_prompts", "images", "video_motion",
                "thumbnail", "render", "sound", "storyboard", "research",
                "upload", "analytics", "title_idea"]:
    bot_path = str(PIPELINE_PATH / bot_dir)
    if bot_path not in sys.path:
        sys.path.append(bot_path)

from database import fetch_one, fetch_all, execute
from error_utils import humanize_error, user_facing
from status_map import to_supabase, to_pipeline, get_bot_name, STAGE_BOT_MAP, is_at_or_past_stage, resolve_planned_status
from vault import get_secret
from extraction import extract_grid
from storage import upload_from_url
import engine_templates
from identity import IdentityContext, build_identity_context

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


def _spoken_word_count(text: str) -> int:
    """Deterministic voiceover word count.

    Never trust the model to self-report counts. Count in code, treating
    designations such as B-52 and contractions/hyphenations as one spoken token.
    """
    import re
    return len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", str(text or "")))


_ANTON_PARAGRAPH_MIN_WORDS = 95
_ANTON_PARAGRAPH_MAX_WORDS = 120
_ANTON_PARAGRAPH_MIN_SENTENCES = 4
_ANTON_PARAGRAPH_MAX_SENTENCES = 7
_ANTON_PARAGRAPH_TARGET_WORDS = "100-112"
_ANTON_PARAGRAPH_WORD_RANGE = f"{_ANTON_PARAGRAPH_MIN_WORDS}-{_ANTON_PARAGRAPH_MAX_WORDS}"
_ANTON_PARAGRAPH_SENTENCE_RANGE = f"{_ANTON_PARAGRAPH_MIN_SENTENCES}-{_ANTON_PARAGRAPH_MAX_SENTENCES}"

_ANTON_REFERENCE_BENCHMARKS = {
    "XB15": {
        "source_video": "Every US Strategic Bomber Ever Built",
        "reference_machine": "Boeing XB-15",
        "reference_order": 1,
        "word_count": 94,
        "sentence_count": 5,
        "opening_mode": "machine/date/significance",
        "sentence_jobs": [
            "problem: experimental leap into long-range strategic bombing",
            "decision: scale, engines, payload, and range as the design answer",
            "tradeoff: one prototype, but proof that large multi-engine bombers could fly intercontinental distances",
            "reality: wartime transport service instead of bomber combat",
            "landing: validated concepts without adding a new event",
        ],
        "final_line_job": "land on validation of the larger strategic-aviation concept",
    },
    "B17": {
        "source_video": "Every US Strategic Bomber Ever Built",
        "reference_machine": "Boeing B-17 Flying Fortress",
        "reference_order": 2,
        "word_count": 116,
        "sentence_count": 7,
        "opening_mode": "machine/service/significance",
        "sentence_jobs": [
            "problem: daylight precision bombing over Europe",
            "decision: four-engine bomber with selected capability specs",
            "tradeoff: defensive-gun belief before escort reality",
            "reality: production scale and Eighth Air Force losses",
            "landing: daylight precision worked, but at severe human cost",
        ],
        "final_line_job": "land on cost, not retirement or generic importance",
    },
    "B24": {
        "source_video": "Every US Strategic Bomber Ever Built",
        "reference_machine": "Consolidated B-24 Liberator",
        "reference_order": 3,
        "word_count": 110,
        "sentence_count": 6,
        "opening_mode": "machine/date/production significance",
        "sentence_jobs": [
            "problem: wartime need for range, efficiency, and mass",
            "decision: Davis wing plus selected range/payload facts",
            "tradeoff: less forgiving than B-17 despite stronger output",
            "reality: every-theater service and production scale",
            "landing: industrial scale as the real strategic answer",
        ],
        "final_line_job": "land on industrial consequence, not a list ending",
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


def _normalized_source_text(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


def _html_to_visible_text(raw_html: str) -> str:
    """Lightweight HTML text extraction without adding another dependency."""
    import html as _html
    import re as _re

    text = _re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav).*?</\1>", " ", raw_html or "")
    text = _re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = _re.sub(r"(?is)</(p|div|section|article|li|tr|h[1-6])>", "\n", text)
    text = _re.sub(r"(?is)<[^>]+>", " ", text)
    return " ".join(_html.unescape(text).split())


def _machine_mention_terms(machine: str) -> set[str]:
    import re as _re

    machine_text = _unit_display_name(machine)
    terms = {machine_text.lower()}
    code = _unit_code(machine_text)
    if code:
        terms.add(code.lower())
        terms.add(code.replace("-", "").lower())
    for word in _re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", machine_text):
        if word.lower() not in {"boeing", "consolidated", "convair", "douglas", "northrop", "lockheed", "martin"}:
            terms.add(word.lower())
    return {term for term in terms if term and len(term) >= 3}


def _mentions_machine(text: str, machine: str) -> bool:
    normalized = _normalized_source_text(text)
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    for term in _machine_mention_terms(machine):
        if term in normalized or re.sub(r"[^a-z0-9]", "", term) in compact:
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
    for index, sentence in enumerate(raw_sentences):
        if not _mentions_machine(sentence, machine):
            continue
        windows = [
            " ".join(raw_sentences[index:index + span]).strip()
            for span in (1, 2, 3)
            if index + span <= len(raw_sentences)
        ]
        for window in windows:
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
    unsupported_capture_methods = sorted({
        str(item.get("source_capture_method") or "").strip()
        for item in quality_candidates
        if str(item.get("source_capture_method") or "").strip()
        and str(item.get("source_capture_method") or "").strip() not in {"fetched_page", "tavily_raw_content"}
    })
    missing_capture_method_count = sum(
        1 for item in quality_candidates
        if not str(item.get("source_capture_method") or "").strip()
    )
    if len(source_urls) < 2:
        errors.append("Verified source package needs excerpts from at least two distinct source URLs.")
    if not non_caution_urls:
        errors.append("Verified source package needs at least one non-caution source before Claude can write a card.")
    if missing_capture_method_count:
        errors.append(
            f"Verified source package has {missing_capture_method_count} exact excerpt(s) without source capture method."
        )
    if unsupported_capture_methods:
        errors.append(
            "Verified source package contains unsupported source capture method(s): "
            + ", ".join(unsupported_capture_methods)
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
    )
    if host_l.endswith(".gov") or host_l.endswith(".mil") or any(
        host_l == item or host_l.endswith(f".{item}") for item in primary_hosts
    ):
        return {"tier": 1, "label": "Tier 1 primary/official"}
    authoritative_hosts = (
        "si.edu", "airandspace.si.edu", "nationalww2museum.org", "iwm.org.uk",
        "imperialwarmuseums.org.uk", "rafmuseum.org.uk", "aerospace.org",
        "historynet.com", "aviation-history.com",
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


def _format_verified_machine_source_package(package: dict) -> str:
    lines = [
        "Verified source package. The model may use ONLY these fetched excerpts.",
        "Every returned source_excerpt must be copied from one candidate below.",
    ]
    for item in (package.get("candidate_excerpts") or [])[:60]:
        if not isinstance(item, dict):
            continue
        tier = _source_tier_number(item)
        tier_label = item.get("source_tier_label") or _source_tier_for_url(
            str(item.get("source_url") or ""),
            str(item.get("source_title") or ""),
        ).get("label")
        lines.extend([
            "",
            f"EXCERPT_ID: {item.get('excerpt_id')}",
            f"SOURCE_TITLE: {item.get('source_title')}",
            f"SOURCE_URL: {item.get('source_url')}",
            f"SOURCE_TIER: {tier} - {tier_label}",
            f"SOURCE_CAPTURE_METHOD: {item.get('source_capture_method') or 'legacy_unmarked'}",
            f"LOCATOR: {item.get('locator')}",
            f"EXACT_TEXT: {item.get('text')}",
        ])
    return "\n".join(lines)[:32000]


def _verified_machine_source_queries(title: str, machine: str) -> list[str]:
    """Cost-bounded query set for one machine's exact raw-source package."""
    manufacturer = " ".join(_unit_display_name(machine).split()[:1]).strip()
    return list(dict.fromkeys([
        f'"{machine}" official history',
        f'"{machine}" USAF fact sheet',
        f'"{machine}" National Museum of the United States Air Force',
        f'"{machine}" {manufacturer} development design history'.strip(),
        f'"{machine}" specifications range payload wingspan engines',
        f'"{machine}" production prototype built service operational history',
        f'"{machine}" design tradeoff limitation lessons learned',
        f'"{machine}" pilot crew engineer account unusual fact test report',
    ]))[:8]


def _validate_card_against_verified_sources(card: dict, package: Optional[dict]) -> list[str]:
    """Require each evidence source excerpt to be text fetched before the LLM call."""
    if not _verified_machine_source_package_ready(package):
        return ["missing verified raw internet source package"]
    candidates = [
        item for item in (package or {}).get("candidate_excerpts", [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    warnings: list[str] = []
    required_slot_sources: dict[str, list[tuple[str, int]]] = {}
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
            url_matches = candidate_url == source_url
            locator_matches = (
                segment_locator == candidate_locator
                or segment_locator == candidate_excerpt_id
                or bool(candidate_locator and candidate_locator.startswith(f"{segment_locator};"))
            )
            if url_matches and locator_matches and excerpt in candidate_text:
                matched = True
                role = _anton_slot_role_for_kind(str(segment.get("kind") or ""))
                if role in _ANTON_REQUIRED_SLOT_ROLES:
                    required_slot_sources.setdefault(role, []).append((evidence_id, _source_tier_number(candidate)))
                break
        if not matched:
            warnings.append(
                f"evidence segment {evidence_id} source_excerpt/locator was not found in verified fetched source text"
            )
    for role, source_rows in required_slot_sources.items():
        if source_rows and all(tier >= 4 for _evidence_id, tier in source_rows):
            evidence_ids = ", ".join(evidence_id for evidence_id, _tier in source_rows)
            warnings.append(
                f"required Anton slot {role} uses only Tier 4/caution sources: {evidence_ids}"
            )
    return warnings


def _inventory_story_brief(payload: dict, machine: str) -> dict:
    """Hide exhaustive card fields from the complete-inventory writer."""
    import re

    card = _research_card_for_machine(payload, machine) or {}
    evidence, _errors = _normalize_machine_evidence(card, machine)

    def sentences(value, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            return ""
        parts = re.split(r"(?<=[.!?])\s+", text)
        return " ".join(parts[:limit]).strip()

    return {
        "machine": machine,
        "core_tension": sentences(
            card.get("engineering_thesis") or card.get("tradeoff") or card.get("design_problem"), 1
        ),
        "actual_outcome": sentences(
            card.get("actual_outcome") or card.get("operational_reality") or card.get("result"), 2
        ),
        "historical_significance": sentences(
            card.get("why_this_unit_deserves_a_paragraph")
            or card.get("legacy")
            or card.get("historical_significance"),
            1,
        ),
        "anton_slots": [
            {
                "slot": segment.get("slot_role") or _anton_slot_role_for_kind(segment.get("kind")),
                "evidence_id": segment.get("evidence_id"),
                "claim": segment.get("claim"),
            }
            for segment in evidence
            if segment.get("slot_role") or _anton_slot_role_for_kind(segment.get("kind"))
        ],
        "onscreen_label": card.get("onscreen_label") or "",
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
        for token in re.findall(r"(?<![A-Za-z])\d+(?:[,.]\d+)*(?:%|st|nd|rd|th|s)?", lower)
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
        elif _anton_slot_role_for_kind(kind) is None:
            errors.append(f"evidence segment {evidence_id or index} has unsupported Anton slot kind: {kind}")
        elif _anton_slot_role_for_kind(kind) == "human_detail" and not _human_detail_has_attribution(
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
            numbers = re.findall(r"(?<![A-Za-z])\d+(?:[,.]\d+)*(?:%|st|nd|rd|th|s)?", claim.lower())
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
        normalized_number_keys = {_numeric_token_key(token) for token in normalized_numbers}
        missing_number_support = [token for token in claim_numbers if _numeric_token_key(token) not in excerpt_number_keys]
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

        normalized.append({
            "evidence_id": evidence_id,
            "kind": kind,
            "slot_role": _anton_slot_role_for_kind(kind),
            "claim": claim,
            "source_excerpt": excerpt,
            "source_url": source_url,
            "source_title": str(raw.get("source_title") or "").strip(),
            "locator": locator,
            "numeric_tokens": normalized_numbers,
            "confidence": str(raw.get("confidence") or "").strip().lower() or "unknown",
        })
    return normalized, list(dict.fromkeys(errors))


def _machine_story_plan(payload: dict, machine: str) -> dict:
    """Compile source-addressable evidence into Anton-style paragraph slots."""
    card = _research_card_for_machine(payload, machine) or {}
    evidence, evidence_errors = _normalize_machine_evidence(card, machine)
    slots = []
    seen_ids: set[str] = set()
    for role, accepted_kinds, job in _ANTON_SLOT_SPECS:
        segments = [
            item for item in evidence
            if item.get("kind") in accepted_kinds and item.get("evidence_id") not in seen_ids
        ]
        if segments:
            seen_ids.update(str(item.get("evidence_id") or "") for item in segments)
        slots.append({
            "slot": role,
            "required": role in _ANTON_REQUIRED_SLOT_ROLES,
            "evidence_ids": [segment["evidence_id"] for segment in segments],
            "evidence_segments": segments,
            "paragraph_job": job,
        })
    role_by_id = {
        segment.get("evidence_id"): slot["slot"]
        for slot in slots
        for segment in slot.get("evidence_segments", [])
        if segment.get("evidence_id")
    }
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
            "paragraph_shape": f"one Anton/DVsU paragraph, {_ANTON_PARAGRAPH_SENTENCE_RANGE} natural sentences",
            "movement": "raw original problem -> raw engineering decision -> raw tradeoff -> raw reality -> short paragraph-derived conclusion",
            "paragraph_words": _ANTON_PARAGRAPH_WORD_RANGE,
            "maximum_numerical_details": 8,
            "editorial_thesis": "single engineering decision, tradeoff, or contrast; not a catalog summary",
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
        return {}
    if not isinstance(parsed, dict):
        return {}

    for key in ("paragraph", "voiceover", "narration"):
        if isinstance(parsed.get(key), str) and not isinstance(parsed.get("paragraph"), str):
            parsed["paragraph"] = parsed[key]
    if isinstance(parsed.get("paragraph"), str):
        parsed["paragraph"] = " ".join(parsed.get("paragraph", "").split())
    if not isinstance(parsed.get("claim_map"), list):
        for key in ("claims", "evidence_map", "source_map"):
            if isinstance(parsed.get(key), list):
                parsed["claim_map"] = parsed[key]
                break
    if not isinstance(parsed.get("editorial_thesis"), str):
        for key in ("engineering_decision", "throughline", "contrast_axis"):
            if isinstance(parsed.get(key), str):
                parsed["editorial_thesis"] = parsed[key]
                break
    return parsed


def _validate_machine_story_sentences(machine: str, plan: dict, bundle: dict) -> tuple[str, list[str]]:
    """Validate one Anton-style paragraph against sourced slot evidence."""
    import re

    warnings: list[str] = []
    if not isinstance(bundle, dict):
        return "", ["story distiller must return a JSON object"]
    paragraph = " ".join(str(bundle.get("paragraph") or "").split())
    if not paragraph:
        return "", ["story distiller must return a paragraph string"]
    opening_assignment = str(((plan.get("contract") or {}) if isinstance(plan, dict) else {}).get("opening_assignment") or "")
    warnings.extend(_opening_assignment_warnings(machine, paragraph, opening_assignment))

    editorial_thesis = " ".join(str(bundle.get("editorial_thesis") or "").split())
    if not editorial_thesis:
        warnings.append("story distiller must declare editorial_thesis for the machine's engineering decision or contrast")
    else:
        thesis_wc = _spoken_word_count(editorial_thesis)
        thesis_lower = editorial_thesis.lower()
        if thesis_wc < 6 or thesis_wc > 26:
            warnings.append(f"editorial_thesis word count {thesis_wc} outside 6-26 range")
        if re.search(r"\b(?:this|the)\s+(?:machine|aircraft|unit)\s+(?:mattered|was important|was significant)\b", thesis_lower):
            warnings.append("editorial_thesis is generic; name the specific engineering decision, tradeoff, or contrast")
        if not re.search(
            r"\b(?:because|but|despite|instead|rather|decision|chose|choice|balanced|trade|traded|tradeoff|tension|contrast|proved|validated|failed|solved|created|answered|sacrificed|compromise|consequence|outpaced|survived|needed)\b",
            thesis_lower,
        ):
            warnings.append("editorial_thesis must state a concrete engineering decision, tradeoff, or contrast")

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
                role_by_id[evidence_id] = role

    claim_rows = bundle.get("claim_map")
    if not isinstance(claim_rows, list) or not claim_rows:
        warnings.append("paragraph must include a non-empty claim_map")
        claim_rows = []
    used_ids: list[str] = []
    claim_span_details: list[dict[str, Any]] = []
    high_risk_terms = {"first", "only", "largest", "fastest", "most", "never"}
    designation_tokens = set(re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", machine.upper()))
    for index, row in enumerate(claim_rows, start=1):
        if not isinstance(row, dict):
            warnings.append(f"claim_map row {index} must be an object")
            continue
        span = " ".join(str(row.get("span") or row.get("text") or row.get("claim") or "").split())
        if not span:
            warnings.append(f"claim_map row {index} missing span")
        elif span not in paragraph:
            warnings.append(f"claim_map row {index} span is not present in paragraph")
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
            span_for_numbers = span
            for designation in designation_tokens:
                span_for_numbers = re.sub(rf"\b{re.escape(designation)}(?:s)?\b", "", span_for_numbers, flags=re.IGNORECASE)
            row_mentions = _numeric_mentions_from_text(span_for_numbers)
            row_evidence_text = " ".join(
                f"{evidence_by_id.get(evidence_id, {}).get('claim', '')} {evidence_by_id.get(evidence_id, {}).get('source_excerpt', '')}"
                for evidence_id in row_ids
                if evidence_id in evidence_by_id
            )
            if row_evidence_text:
                unsupported_words = _ungrounded_factual_words(span, row_evidence_text, machine)
                if unsupported_words:
                    warnings.append(
                        f"claim_map row {index} introduced unsupported factual word(s): "
                        + ", ".join(unsupported_words[:10])
                    )
            span_number_keys = {mention["key"] for mention in row_mentions}
            row_number_keys = {
                _numeric_token_key(token)
                for evidence_id in row_ids
                for token in evidence_by_id.get(evidence_id, {}).get("numeric_tokens", [])
            }
            row_unsupported_numbers = [
                mention["raw"] for mention in row_mentions
                if mention["key"] not in row_number_keys
            ]
            if row_unsupported_numbers:
                warnings.append(
                    f"claim_map row {index} introduced unsupported numerical detail(s): "
                    + ", ".join(row_unsupported_numbers)
                )
            span_lower = span.lower()
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
                })
            has_high_risk_term = bool(span_risk_terms)
            hedged = bool(re.search(r"\b(approximately|around|roughly|estimated|about|claimed|at least|more than|between)\b", span_lower))
            if (row_mentions or has_high_risk_term) and not hedged:
                row_source_keys = {
                    str(evidence_by_id.get(evidence_id, {}).get("source_url") or evidence_by_id.get(evidence_id, {}).get("locator") or "").strip()
                    for evidence_id in row_ids
                    if evidence_id in evidence_by_id
                }
                row_source_keys = {source for source in row_source_keys if source}
                if len(row_source_keys) < 2:
                    warnings.append(
                        f"claim_map row {index} needs two independent sources or a hedge for high-risk exact fact(s)"
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
    if not memorable_ids:
        warnings.append("story plan missing sourced memorable_fact for Anton paragraph")
    elif not any(evidence_id in used_ids for evidence_id in memorable_ids):
        warnings.append("paragraph must use sourced memorable_fact when the story plan provides one")
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
    if missing_required:
        warnings.append("paragraph missing required Anton slot evidence: " + ", ".join(missing_required))
    if len(covered_roles) < 4:
        warnings.append("paragraph must use evidence from at least four Anton slots")

    paragraph_for_numbers = paragraph
    for designation in designation_tokens:
        paragraph_for_numbers = re.sub(rf"\b{re.escape(designation)}(?:s)?\b", "", paragraph_for_numbers, flags=re.IGNORECASE)
    paragraph_numbers = _numeric_mentions_from_text(paragraph_for_numbers)
    allowed_number_keys = {
        _numeric_token_key(token)
        for evidence_id in used_ids
        for token in evidence_by_id.get(evidence_id, {}).get("numeric_tokens", [])
    }
    unsupported_numbers = [
        mention["raw"] for mention in paragraph_numbers
        if mention["key"] not in allowed_number_keys
    ]
    if unsupported_numbers:
        warnings.append("paragraph introduced unsupported numerical detail(s): " + ", ".join(unsupported_numbers))
    if len(paragraph_numbers) > int((plan.get("contract") or {}).get("maximum_numerical_details") or 8):
        warnings.append(f"paragraph contains {len(paragraph_numbers)} numerical details; maximum is 8")

    allowed_designations = {_normalized_unit_code(machine)}
    allowed_evidence_text = " ".join(
        f"{evidence_by_id.get(eid, {}).get('claim', '')} {evidence_by_id.get(eid, {}).get('source_excerpt', '')}"
        for eid in used_ids
    )
    allowed_designations.update(
        _normalized_unit_code(token)
        for token in re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", allowed_evidence_text.upper())
    )
    paragraph_designations = {
        _normalized_unit_code(token)
        for token in re.findall(r"\b[A-Z]{1,4}-?\d+[A-Z]?\b", paragraph.upper())
    }
    unsupported_designations = sorted(token for token in paragraph_designations if token and token not in allowed_designations)
    if unsupported_designations:
        warnings.append("paragraph introduced unsupported designation(s): " + ", ".join(unsupported_designations))

    sentence_count = len([part for part in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if part.strip()])
    if sentence_count < _ANTON_PARAGRAPH_MIN_SENTENCES or sentence_count > _ANTON_PARAGRAPH_MAX_SENTENCES:
        warnings.append(
            f"paragraph sentence count {sentence_count} outside Anton {_ANTON_PARAGRAPH_SENTENCE_RANGE} range"
        )
    sentence_parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if part.strip()]
    last_sentence = sentence_parts[-1] if sentence_parts else ""
    final_sentence_index = len(sentence_parts)
    for sentence_index, sentence in enumerate(sentence_parts, start=1):
        sentence_claim_spans = [
            detail for detail in claim_span_details
            if detail.get("span") and (detail["span"] in sentence or sentence in detail["span"])
        ]
        if sentence_index == final_sentence_index and sentence_claim_spans:
            warnings.append("final sentence must be paragraph-derived synthesis, not source-backed claim_map evidence")
        if not sentence_claim_spans:
            if sentence_index != final_sentence_index:
                warnings.append(f"sentence {sentence_index} is not covered by claim_map evidence")
            continue
        sentence_for_numbers = sentence
        for designation in designation_tokens:
            sentence_for_numbers = re.sub(rf"\b{re.escape(designation)}(?:s)?\b", "", sentence_for_numbers, flags=re.IGNORECASE)
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
    if sentence_parts:
        last_wc = _spoken_word_count(last_sentence)
        if last_wc > 28:
            warnings.append(f"final sentence word count {last_wc} is too long to land cleanly")
        if re.search(r"\b(in conclusion|overall|to summarize|this shows that)\b", last_sentence.lower()):
            warnings.append("final sentence uses generic summary language instead of a landed Anton line")
        final_sentence_for_numbers = last_sentence
        for designation in designation_tokens:
            final_sentence_for_numbers = re.sub(rf"\b{re.escape(designation)}(?:s)?\b", "", final_sentence_for_numbers, flags=re.IGNORECASE)
        final_numbers = _numeric_mentions_from_text(final_sentence_for_numbers)
        if final_numbers:
            warnings.append(
                "final sentence must be paragraph-derived synthesis without new numerical detail(s): "
                + ", ".join(mention["raw"] for mention in final_numbers)
            )
        final_risk_terms = sorted(
            term for term in high_risk_terms
            if re.search(rf"\b{re.escape(term)}\b", last_sentence.lower())
        )
        if final_risk_terms:
            warnings.append(
                "final sentence must not introduce high-risk exact term(s): "
                + ", ".join(final_risk_terms)
            )
        prior_paragraph_text = " ".join(sentence_parts[:-1])
        known_entity_text = f"{prior_paragraph_text} {machine}"
        ignored_final_entities = {
            "a", "an", "and", "as", "but", "it", "its", "so", "that", "the",
            "these", "this", "those", "together",
        }
        final_entities = [
            " ".join(match.split())
            for match in re.findall(
                r"\b(?:[A-Z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)?|[A-Z]{2,}|[IVX]{1,4})"
                r"(?:\s+(?:[A-Z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)?|[A-Z]{2,}|[IVX]{1,4}))*\b",
                last_sentence,
            )
        ]
        new_final_entities = []
        for entity in final_entities:
            if entity.lower() in ignored_final_entities:
                continue
            if entity not in known_entity_text:
                new_final_entities.append(entity)
        if new_final_entities:
            warnings.append(
                "final sentence must not introduce new named entity/event detail(s): "
                + ", ".join(dict.fromkeys(new_final_entities))
            )
    if ";" in paragraph:
        warnings.append("paragraph may not use semicolons")

    evidence_text = allowed_evidence_text.lower()
    unsupported_risk_terms = sorted(
        term for term in high_risk_terms
        if re.search(rf"\b{term}\b", paragraph.lower()) and not re.search(rf"\b{term}\b", evidence_text)
    )
    if unsupported_risk_terms:
        warnings.append("paragraph used high-risk term(s) absent from sourced evidence: " + ", ".join(unsupported_risk_terms))

    warnings.extend(PipelineExecutor._validate_static_unit_paragraph(machine, paragraph))
    return paragraph, list(dict.fromkeys(warnings))


def _anton_preview_quality_audit(machine: str, plan: dict, bundle: dict, paragraph: str, warnings: list[str]) -> dict:
    """Small deterministic checklist for judging one machine against Anton's contract."""
    import re

    paragraph = " ".join(str(paragraph or "").split())
    warning_text = " | ".join(str(item) for item in (warnings or [])).lower()
    sentence_parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
    claim_rows = bundle.get("claim_map") if isinstance(bundle, dict) else []
    claim_rows = claim_rows if isinstance(claim_rows, list) else []
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
            role_by_id[evidence_id] = role
    covered_roles = {role_by_id[evidence_id] for evidence_id in used_ids if evidence_id in role_by_id}
    missing_roles = sorted(role for role in _ANTON_REQUIRED_SLOT_ROLES if role not in covered_roles)
    memorable_ids = slot_ids.get("memorable_fact") or []
    memorable_used = [evidence_id for evidence_id in memorable_ids if evidence_id in used_ids]
    final_line_warnings = [
        "final sentence word count",
        "final sentence uses generic",
        "final sentence must be paragraph-derived",
        "final sentence must not introduce",
        "final sentence ends on",
    ]
    voiceover_clean_warnings = [
        "production cue/label",
        "bracketed production note",
        "meta/commentary",
        "must be exactly one paragraph",
    ]
    rhythm_warnings = [
        "three consecutive long sentences",
    ]
    opening_warnings = [
        "opening assignment forbids machine-name opening",
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
    reference_benchmark = plan.get("reference_benchmark") if isinstance(plan, dict) else None
    checks = [
        check(
            "word_range",
            f"{_ANTON_PARAGRAPH_WORD_RANGE} words",
            _ANTON_PARAGRAPH_MIN_WORDS <= word_count <= _ANTON_PARAGRAPH_MAX_WORDS,
            f"{word_count} words",
        ),
        check(
            "sentence_shape",
            f"{_ANTON_PARAGRAPH_SENTENCE_RANGE} natural sentences",
            _ANTON_PARAGRAPH_MIN_SENTENCES <= len(sentence_parts) <= _ANTON_PARAGRAPH_MAX_SENTENCES,
            f"{len(sentence_parts)} sentences",
        ),
        check(
            "four_evidence_beats",
            "Four grounded beats",
            not missing_roles,
            "covered" if not missing_roles else "missing " + ", ".join(missing_roles),
        ),
        check(
            "memorable_fact",
            "Sourced memorable fact",
            bool(memorable_used),
            (
                "used " + ", ".join(memorable_used)
                if memorable_used else
                "research plan has no sourced memorable_fact" if not memorable_ids else
                "available but unused"
            ),
        ),
        check(
            "editorial_thesis",
            "Concrete editorial thesis",
            isinstance(bundle, dict) and bool(str(bundle.get("editorial_thesis") or "").strip())
            and "editorial_thesis" not in warning_text,
            str(bundle.get("editorial_thesis") or "").strip() if isinstance(bundle, dict) else "",
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
            "not_catalog_copy",
            "Not catalog/spec dump",
            not any(token in warning_text for token in catalog_warnings),
            "clean" if not any(token in warning_text for token in catalog_warnings) else "catalog pattern flagged",
        ),
    ]
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


def _machine_documentary_hold_roster(video: dict) -> list[str]:
    """Return the locked machine roster only for the siloed static-docu path.

    Animation, narrative, dialogue, modeled, and clip-based videos remain on the
    global whole-video writer even if a roster-shaped field appears in research.
    No fact-sheet/LLM inference is allowed here: the roster must already be an
    explicit persisted list.
    """
    import json as _json_mh

    if not isinstance(video, dict) or (video.get("render_mode") or "") != "static_docu":
        return []
    payload = video.get("research_payload") or {}
    if isinstance(payload, str):
        try:
            payload = _json_mh.loads(payload)
        except (ValueError, TypeError):
            return []
    if not isinstance(payload, dict):
        return []
    marker = str(payload.get("documentary_style") or payload.get("pipeline_style") or "").strip().lower()
    has_machine_marker = (
        marker in {"machine_documentary", "designed_vs_used", "dvsu"}
        or isinstance(payload.get("machine_discovery_buckets"), dict)
        or isinstance(payload.get("unit_research_hold_validation"), dict)
    )
    if not has_machine_marker:
        return []
    roster = payload.get("unit_roster")
    if not isinstance(roster, list):
        return []
    names = [_unit_display_name(item) for item in roster]
    names = [name for name in names if name]
    return names if 3 <= len(names) <= 40 else []


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

    if complete_title and not roster:
        warnings.append("This title promises a complete roster, but research_payload.unit_roster is missing.")
    if complete_title and len(roster) < 3:
        warnings.append(f"Complete-roster title has only {len(roster)} roster item(s); likely incomplete.")
    if _title_is_broad_machine_roster(title) and len(roster) < 15:
        warnings.append(
            f"Broad machine-roster title has only {len(roster)} item(s); likely a shortlist, not the full title promise."
        )
    small_category_proof = any(term in lower for term in ("genuinely small", "small closed category", "only known", "no additional built"))
    if (
        _title_is_broad_machine_roster(title)
        and complete_title
        and pacing_targets
        and len(roster) < pacing_targets["minimum_final_roster"]
        and not small_category_proof
    ):
        warnings.append(
            "Broad complete-roster title has fewer than "
            f"{pacing_targets['minimum_final_roster']} final items for a "
            f"{pacing_targets['video_length_minutes']:g}-minute Anton-paced video "
            f"(expected around {pacing_targets['expected_final_roster']}) without proving the category is genuinely small."
        )
    if (
        _title_is_broad_machine_roster(title)
        and complete_title
        and pacing_targets
        and len(roster) < pacing_targets["expected_final_roster"]
        and not small_category_proof
    ):
        warnings.append(
            "Broad complete-roster title is below the Anton-paced final roster target: "
            f"{len(roster)} final items vs expected around {pacing_targets['expected_final_roster']} "
            f"for a {pacing_targets['video_length_minutes']:g}-minute video. Lock enough source-backed machines to fit the runtime or "
            "prove with sources that the category is genuinely smaller."
        )
    if (
        _title_is_broad_machine_roster(title)
        and complete_title
        and pacing_targets
        and len(roster) > pacing_targets["candidate_universe_target"]
        and not small_category_proof
    ):
        warnings.append(
            "Broad complete-roster final roster is larger than the runtime target plus reserve: "
            f"{len(roster)} final items vs target around {pacing_targets['expected_final_roster']} "
            f"for a {pacing_targets['video_length_minutes']:g}-minute video. Tighten the roster to fit the requested runtime, "
            "or prove that the title requires the larger count."
        )
    if _title_is_broad_machine_roster(title):
        if bucket_total == 0:
            warnings.append("Broad machine-roster research is missing machine_discovery_buckets for core/prototypes/variants/secret programs/boundary disputes.")
        if not has_recommendation:
            warnings.append("Broad machine-roster research is missing recommended_final_roster.")
        elif isinstance(recommended, list) and len(recommended) != len(roster):
            warnings.append(
                f"recommended_final_roster count ({len(recommended)}) does not match unit_roster count ({len(roster)}); "
                "the locked machine list is internally inconsistent."
            )
        if not has_gap_hunt:
            warnings.append("Broad machine-roster research is missing gap_hunt_matrix showing the adversarial omission follow-up pass.")
        if not has_edge_case_matrix:
            warnings.append("Broad machine-roster research is missing edge_case_matrix showing generic omission classes checked.")
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
            warnings.append("Broad machine-roster research did not explicitly resolve enough generic edge-case classes.")
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
            warnings.append(
                "Final roster appears padded with minor subvariants while the parent machine is already included: "
                + ", ".join(padded_families)
                + ". Combine minor variants under the parent unless the title asks for variants/classes or the subvariant is a distinct audience-facing program."
            )

        excluded_codes: dict[str, str] = {}
        for item in audit_excluded:
            name = _unit_display_name(item)
            code = _unit_code(name)
            if code:
                excluded_codes[code] = name
        overlap = [name for name, code in zip(roster, roster_codes) if code in excluded_codes]
        if overlap:
            warnings.append(
                "Roster is internally inconsistent: candidate appears in both unit_roster and excluded_candidates: "
                + ", ".join(overlap)
            )

        title_lower = str(title or "").lower()
        if "ever built" in title_lower and any(
            term in _payload_blob(audit_excluded).lower()
            for term in ("not operationally delivered", "not yet operational", "not operationally deployed")
        ):
            warnings.append(
                "Ever-built title is excluding a candidate for not being operational/delivered. "
                "For 'ever built', physical build/flight is the boundary; operational status alone is not a valid exclusion."
            )
    if is_incomplete or any(term in lower for term in ("misleading", "should either be narrowed", "research expanded")):
        warnings.append("Research payload admits the roster/title may be incomplete or narrowed.")
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
            warnings.append("Complete-roster research is missing roster_audit proof of exhaustive search.")
        elif len(queries) < 6:
            warnings.append("Complete-roster research used fewer than 6 distinct roster-discovery searches.")
        if audit and len(families) < 3:
            warnings.append("Complete-roster research cross-checked fewer than 3 source families.")
        if audit and unresolved and not (is_review_ready and has_recommendation):
            warnings.append(f"Complete-roster research still has {len(unresolved)} unresolved candidate(s).")
        if audit and confidence and confidence not in ("high", "medium"):
            warnings.append(f"Complete-roster audit confidence is {confidence}, not high/medium.")
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
        script_blob = "\n".join(script_units)
        script_codes = [_unit_code(u) for u in script_units if _unit_code(u)]
        for name, code in zip(roster, roster_codes):
            if code and code not in script_blob.upper():
                script_missing.append(name)
        for code in script_codes:
            if code and code not in roster_codes and code not in script_extra:
                script_extra.append(code)
        if script_missing:
            warnings.append(f"Script omitted {len(script_missing)} roster item(s).")
        if script_extra:
            warnings.append(f"Script added {len(script_extra)} item(s) outside the locked roster.")

    return {
        "passed": len(warnings) == 0,
        "complete_title": complete_title,
        "roster_count": len(roster),
        "roster": roster,
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
        return engine_templates.safe_fill(chosen, identity)
    return None


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
        # Voice-config keys have a legitimate process-level default in the
        # service .env (legacy single-tenant behavior). Snapshot those before
        # clearing so a tenant WITHOUT a vault override keeps the .env value
        # instead of silently dropping to the hardcoded default voice.
        VOICE_CONFIG_KEYS = ("elevenlabs_voice_id", "elevenlabs_model_id", "elevenlabs_voice_style")
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
            self._pipeline.google = GoogleClient()
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
            self._pipeline.image_client = ImageClient(google_client=self._pipeline.google)
            print("[INIT] ImageClient OK", flush=True)
        except Exception as e:
            print(f"[INIT] ImageClient skipped: {e}", flush=True)
            self._pipeline.image_client = None

        try:
            from shared.clients.elevenlabs_client import ElevenLabsClient
            self._pipeline.elevenlabs = ElevenLabsClient()
            print("[INIT] ElevenLabsClient OK", flush=True)
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
            visual_style = idea.get(IdeaFields.VISUAL_STYLE) or "neutral_v1"
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

        async def run_upload_bot():
            from upload.run import run
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
        self._pipeline.run_upload_bot = run_upload_bot

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

    async def _gather_verified_machine_source_package(self, title: str, machine: str, payload: dict) -> dict:
        """Search the live internet, fetch pages, and save exact excerpt candidates for one machine.

        This is deliberately pre-LLM. Claude may summarize or select after this,
        but it may not invent source text because card validation checks against
        this package.
        """
        cache_key = _verified_source_cache_key(machine)
        cached = ((payload or {}).get("machine_raw_source_packages") or {}).get(cache_key)
        if (
            _verified_machine_source_package_ready(cached)
            and not _verified_machine_source_package_quality_errors(cached, machine)
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

        import httpx as _httpx

        search_results: list[dict] = []
        errors: list[str] = []
        headers = {"User-Agent": "StoryEngine/1.0 (verified source research)"}
        async with _httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
            for query in queries:
                try:
                    response = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": tavily_key,
                            "query": query,
                            "search_depth": "advanced",
                            "include_answer": False,
                            "include_raw_content": True,
                            "max_results": 5,
                        },
                    )
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

            sources: list[dict] = []
            candidate_excerpts: list[dict] = []
            seen_urls: set[str] = set()
            for item in search_results:
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title_text = str(item.get("title") or url).strip()
                fetched_text = await self._fetch_source_text(client, url)
                raw_content = str(item.get("raw_content") or "")
                source_text = fetched_text or raw_content
                if not source_text or not _mentions_machine(source_text, machine):
                    continue
                capture_method = "fetched_page" if fetched_text else "tavily_raw_content"
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
                    "text_hash": source_hash,
                    "text_chars": len(source_text),
                })
                for excerpt in _sentence_candidates_from_source(source_text, machine, limit=10):
                    excerpt_id = f"{source_id}-E{len([e for e in candidate_excerpts if e.get('source_id') == source_id]) + 1}"
                    candidate_excerpts.append({
                        "excerpt_id": excerpt_id,
                        "source_id": source_id,
                        "source_title": title_text,
                        "source_url": url,
                        "source_tier": source_tier["tier"],
                        "source_tier_label": source_tier["label"],
                        "source_capture_method": capture_method,
                        "locator": f"{excerpt_id}; query={item.get('_query')}",
                        "text": excerpt,
                        "text_hash": _source_text_fingerprint(excerpt),
                    })
                    if len(candidate_excerpts) >= 60:
                        break
                if len(candidate_excerpts) >= 60:
                    break

        package = {
            "passed": len(candidate_excerpts) >= 6,
            "schema_version": 3,
            "machine": machine,
            "machine_key": cache_key,
            "search_queries": queries,
            "sources": sources,
            "candidate_excerpts": candidate_excerpts,
            "errors": errors,
            "gathered_at": datetime.now(timezone.utc).isoformat(),
        }
        quality_errors = _verified_machine_source_package_quality_errors(package, machine)
        if quality_errors:
            package["passed"] = False
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
        """Merge trustworthy compact rows into legacy cards in locked-roster order."""
        if not isinstance(payload, dict):
            payload = {}
        roster = roster or [
            _unit_display_name(item) for item in (payload.get("unit_roster") or [])
            if _unit_display_name(item)
        ]
        target_key = _normalized_unit_code(_unit_display_name(target_machine or "")) if target_machine else ""
        roster_by_key = {
            _normalized_unit_code(machine): machine for machine in roster
            if _normalized_unit_code(machine)
        }
        roster_index_by_key = {
            _normalized_unit_code(machine): index for index, machine in enumerate(roster, start=1)
            if _normalized_unit_code(machine)
        }
        if not roster_by_key:
            return payload
        try:
            if target_key:
                rows = await fetch_all(
                    """SELECT machine_key, machine_name, roster_index, card, validation
                       FROM machine_research_cards
                       WHERE tenant_id = $1 AND video_id = $2 AND machine_key = $3
                       ORDER BY roster_index, machine_key""",
                    self.tenant_id, video_id, target_key,
                )
            else:
                rows = await fetch_all(
                    """SELECT machine_key, machine_name, roster_index, card, validation
                       FROM machine_research_cards
                       WHERE tenant_id = $1 AND video_id = $2
                       ORDER BY roster_index, machine_key""",
                    self.tenant_id, video_id,
                )
        except Exception as exc:  # migration-safe compatibility fallback
            _logger.warning("[machine-research] compact read unavailable: %s", str(exc)[:150])
            return payload
        cards_by_key: dict[str, dict] = {}
        for card in payload.get("unit_research_cards") or []:
            if not isinstance(card, dict):
                continue
            identity = card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or ""
            key = _normalized_unit_code(_unit_display_name(identity))
            if key and key in roster_by_key:
                cards_by_key[key] = card
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("card"), dict):
                continue
            metadata_key = _normalized_unit_code(str(row.get("machine_key") or ""))
            name_key = _normalized_unit_code(str(row.get("machine_name") or ""))
            card = row["card"]
            identity = card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or ""
            card_key = _normalized_unit_code(_unit_display_name(identity))
            validation = row.get("validation") or {}
            if (
                not metadata_key or metadata_key not in roster_by_key
                or metadata_key != name_key or metadata_key != card_key
                or row.get("roster_index") != roster_index_by_key[metadata_key]
                or (isinstance(validation, dict) and validation.get("passed") is False)
            ):
                continue
            cards_by_key[metadata_key] = card
        cards = [cards_by_key[key] for key in roster_by_key if key in cards_by_key]
        hydrated = dict(payload)
        hydrated["unit_research_cards"] = cards
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
        """Checkpoint one compact card under exact tenant/video/machine identity."""
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
               ON CONFLICT (tenant_id, video_id, machine_key) DO UPDATE SET
                 machine_name = EXCLUDED.machine_name,
                 roster_index = EXCLUDED.roster_index,
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

    async def _checkpoint_machine_raw_source_package(
        self, video_id: str, machine_key: str, source_package: dict, locked_roster_snapshot: str
    ) -> Any:
        """Persist fetched exact excerpts before any LLM research-card work."""
        import json

        if not machine_key:
            raise ValueError("raw source package checkpoint requires a non-empty machine key")
        return await execute(
            """UPDATE videos SET research_payload = jsonb_set(
                   COALESCE(research_payload::jsonb, '{}'::jsonb),
                   '{machine_raw_source_packages}',
                   COALESCE(research_payload::jsonb->'machine_raw_source_packages', '{}'::jsonb)
                     || jsonb_build_object($1::text, $2::jsonb),
                   true
               ), updated_at = now()
               WHERE id = $3 AND tenant_id = $4
                 AND (
                     research_payload->'unit_roster' IS NULL
                     OR research_payload->'unit_roster' = $5::jsonb
                 )""",
            machine_key, json.dumps(source_package), video_id, self.tenant_id, locked_roster_snapshot,
        )

    @staticmethod
    def _enabled_stages(video: Optional[dict]) -> Optional[list]:
        """The video's per-video stage plan (list of enabled stage keys), or
        None for 'run the full pipeline'. Reads the pipeline_stages JSONB column,
        tolerating either a parsed list or a JSON string (asyncpg returns JSONB
        as a str unless a codec is set)."""
        if not video:
            return None
        raw = video.get("pipeline_stages")
        if raw is None:
            return None
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except Exception:
                return None
        if isinstance(raw, list) and raw:
            return raw
        return None

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

    async def _check_voice_exists(self, video_id: str) -> tuple[bool, int, int]:
        """Check if voice has been generated for all scenes.

        A scene is voiced when its narrator track exists (scripts.voice_over_url)
        OR when dialogue-voice finished every spoken line (each dialogue_segments
        entry with text carries its own audio_url). All-dialogue scenes never get
        a narrator track, so voice_over_url alone would reject them forever.

        Returns (all_have_voice, total_scenes, scenes_with_voice).
        """
        from dialogue_voice import _as_segments

        rows = await fetch_all(
            "SELECT voice_over_url, dialogue_segments FROM scripts WHERE video_id = $1",
            video_id,
        )
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
        # NOTE: `title` is intentionally left out for now — Phase 3 wires it.
        PROMPT_MAP = {
            "script":           ("script_system_prompt",       "script_system_prompt"),
            "thumbnail":        ("thumbnail_system_prompt",    "thumbnail_system_prompt"),
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
            await execute(
                """UPDATE videos SET
                   research_payload = $1,
                   thesis = $2,
                   executive_hook = $3,
                   status = $4,
                   updated_at = now()
                   WHERE id = $5""",
                json.dumps(payload),
                payload.get("thesis", ""),
                payload.get("executive_hook", ""),
                next_status,
                video_id,
            )
            from drive_workspace import sync_video_workspace_fail_soft
            await sync_video_workspace_fail_soft(video_id, self.tenant_id)

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
            return {"status": "failed", "video_id": video_id, "error": "; ".join(str(item) for item in warnings)}
        final_save_result = await execute(
            """UPDATE videos
               SET research_payload = $1, status = $2, updated_at = now()
               WHERE id = $3 AND tenant_id = $4
                 AND (
                     research_payload->'unit_roster' IS NULL
                     OR research_payload->'unit_roster' = $5::jsonb
                 )""",
            _json_one.dumps(payload), original_status, video_id, self.tenant_id, locked_roster_snapshot,
        )
        if self._db_write_missed(final_save_result):
            return {
                "status": "failed",
                "video_id": video_id,
                "error": "persisted unit_roster changed concurrently; final one-machine research save refused",
            }
        card = _research_card_for_machine(payload, matched)
        return {"status": "completed", "video_id": video_id, "machine": matched, "research_card": card}

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

            roster_gate = payload.get("unit_roster_validation") or {}
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
            by_kind = {
                str(segment.get("kind") or "").strip().lower(): str(segment.get("claim") or "").strip()
                for segment in segments if isinstance(segment, dict)
            }
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
            card.setdefault("why_this_unit_deserves_a_paragraph", by_kind.get("historical_meaning") or by_kind.get("legacy") or "")
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
            warnings: list[str] = []
            if not isinstance(card, dict):
                return ["research card was not an object"]
            card_unit = _unit_display_name(
                card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or ""
            )
            if not card_unit or _normalized_unit_code(card_unit) != _normalized_unit_code(machine):
                warnings.append(f"card unit does not match locked machine {machine}")
            if len(str(card.get("engineering_thesis") or "").strip()) < 20:
                warnings.append("missing/weak engineering_thesis")
            if not str(card.get("surprising_fact") or "").strip():
                warnings.append("missing surprising_fact")
            source_notes = card.get("source_notes")
            if not isinstance(source_notes, list) or not source_notes:
                warnings.append("missing source_notes")
            _, evidence_errors = _normalize_machine_evidence(card, machine)
            warnings.extend(evidence_errors)
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
                warnings = (
                    _card_warnings(
                        roster_machine,
                        card,
                        _verified_source_package_for_machine(payload, roster_machine),
                        require_source_package=True,
                    )
                    if card else ["missing saved one-machine research card"]
                )
                units.append({"machine": roster_machine, "passed": not warnings, "warnings": warnings})
            return units, all(unit.get("passed") for unit in units)

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
            validation_units = []
            invalid_or_missing = []
            for i, machine in enumerate(roster, start=1):
                code = _normalized_unit_code(machine)
                card = cards_by_code.get(code)
                warnings = (
                    _card_warnings(
                        machine,
                        card,
                        _verified_source_package_for_machine(payload, machine),
                        require_source_package=True,
                    )
                    if card else ["missing saved one-machine research card"]
                )
                validation_units.append({"machine": machine, "passed": not warnings, "warnings": warnings})
                if warnings:
                    invalid_or_missing.append(machine)
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
            if not _verified_machine_source_package_ready(verified_source_package) or source_package_errors:
                messages = [
                    str(item) for item in (verified_source_package.get("errors") or [])
                    if str(item).strip()
                ] + source_package_errors
                msg = "; ".join(dict.fromkeys(messages))
                msg = msg or "Verified one-machine internet research did not return enough exact source excerpts."
                payload["unit_research_hold_validation"] = {
                    "passed": False,
                    "in_progress": False,
                    "target_machine": target_machine,
                    "units": [{"machine": target_machine, "passed": False, "warnings": [msg]}],
                    "warnings": [msg],
                }
                await self._log_activity(bot_name, video_id, "failed", msg)
                return payload
            legacy_source = _format_verified_machine_source_package(verified_source_package)
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
            unit_cards = [
                cards_by_code[code]
                for roster_machine in roster
                for code in [_normalized_unit_code(roster_machine)]
                if code and code != target_code and code in cards_by_code
            ]
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
                if not warnings:
                    unit_cards.append(card)
                    reused_validation = {"machine": machine, "passed": True, "reused_existing": True, "warnings": []}
                    validation_units.append(reused_validation)
                    # Opportunistically backfill legacy JSONB-only cards.
                    await self._upsert_machine_research_card(video_id, machine, i, card, reused_validation)
                    continue

            prompt = (
                "Create ONE Designed vs Used machine research card.\n\n"
                f"VIDEO TITLE: {title}\n"
                f"LOCKED MACHINE {i} OF {len(roster)}: {machine}\n\n"
                "HARD CONTRACT:\n"
                "- The roster is locked. Do not add, remove, replace, or relitigate machines.\n"
                f"- Research/enrich only THIS machine enough to support one Anton-quality {_ANTON_PARAGRAPH_WORD_RANGE} word DVsU paragraph and one image brief.\n"
                "- DVsU is engineering documentary: facts serve the engineering decision, not an encyclopedia/spec dump.\n"
                "- Keep every prose value concise (normally 1-3 sentences) so the complete JSON object fits comfortably.\n"
                "- Return ONLY valid JSON. No markdown.\n\n"
                "Required JSON keys: schema_version (3), unit, include, engineering_thesis, why_this_unit_deserves_a_paragraph, evidence_segments.\n"
                "Do NOT return legacy prose fields, script beats, source_notes, or high-risk-claim summaries; code derives compatibility fields from evidence_segments.\n"
                "EVIDENCE SEGMENT CONTRACT:\n"
                "- Return 6-9 atomic evidence segments using Anton slot kinds only.\n"
                "- Required four-beat slot kinds at least once: original_problem, engineering_decision, tradeoff, reality.\n"
                "- original_problem = raw excerpt for the situation, requirement, or need that created the machine.\n"
                "- engineering_decision = raw excerpt for the design/procurement/engineering answer.\n"
                "- tradeoff = raw excerpt for the sacrifice, limitation, compromise, or unintended consequence.\n"
                "- reality = raw excerpt for what happened in testing, production, service, or combat reality.\n"
                "- memorable_fact should be returned when the verified excerpts support a fact serious viewers are unlikely to know; it will be required for Anton-quality script preview, but never invent one.\n"
                "- For machines 1-3, prefer one verified human_detail, named decision, or official finding when the excerpt package supports it. Never invent a human account.\n"
                "- A human_detail segment must be attributed to a named person or cite an official finding/decision. Generic pilot, crew, or engineer claims are invalid.\n"
                "- Do not create a pre-written meaning, legacy, or conclusion beat. If an exact excerpt states a concrete downstream consequence, return it as reality, not historical_meaning.\n"
                "- Prefer SOURCE_TIER 1-2 excerpts. SOURCE_TIER 3 is acceptable when it is the best available support. Never use SOURCE_TIER 4/caution as the sole support for a required slot kind.\n"
                "- Add human_detail, role_category, transition_hook, onscreen_label, and optional context slots only when directly supported by exact excerpts.\n"
                "- onscreen_label is metadata for Producer File/on-screen text, never spoken narration; use only sourced full name, concise role, operator or build count, and service/date range.\n"
                "- Each claim must be one concise factual proposition, maximum 35 words. A technical claim may bundle 2-4 related specifications only if the source excerpt contains them together and they serve the engineering_decision beat.\n"
                "- Each segment must contain exactly: evidence_id, kind, claim, source_excerpt, source_url, source_title, locator, numeric_tokens (array), confidence.\n"
                "- One segment = one research slot. Do not write narration or pre-assemble the paragraph.\n"
                "- claim must be a concise restatement of source_excerpt using no factual noun, verb, adjective, or number absent from that excerpt.\n"
                "- numeric_tokens must list every number used by claim and may contain only numbers present in claim or source_excerpt.\n"
                "- source_excerpt must be copied from EXACT_TEXT in the verified excerpt package; source_url and locator must match that excerpt.\n"
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
                max_tokens=2400,
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
                warnings = _card_warnings(machine, card, verified_source_package if target_code else None, require_source_package=bool(target_code))
            except Exception as e:
                warnings = [f"invalid JSON research card: {str(e)[:120]}"]

            if warnings:
                repair_prompt = (
                    f"Repair this ONE-machine research card for LOCKED MACHINE: {machine}.\n"
                    f"Warnings: {'; '.join(warnings)}\n"
                    "Return ONLY valid schema_version 3 JSON with the minimal required keys and evidence_segments array. "
                    "Do not return legacy prose fields, source_notes, high_risk_claims, visual metadata, or script beats. "
                    "Return 6-9 Anton-slot evidence segments. Required four-beat kinds at least once: original_problem, engineering_decision, tradeoff, reality. "
                    "original_problem is the source-backed need; engineering_decision is the design/procurement answer; tradeoff is the sacrifice or limitation; reality is what happened in testing, production, service, or combat. "
                    "memorable_fact should be returned when supported by exact excerpts and must strengthen one of those four beats; do not invent trivia. "
                    "For machines 1-3, prefer one verified human_detail, named decision, or official finding when the excerpt package supports it; never invent a human account. "
                    "A human_detail segment must be attributed to a named person or cite an official finding/decision; generic pilot, crew, or engineer claims are invalid. "
                    "Do not create a pre-written meaning, legacy, or conclusion beat. If an exact excerpt states a concrete downstream consequence, return it as reality, not historical_meaning. "
                    "Prefer SOURCE_TIER 1-2 excerpts. SOURCE_TIER 3 is acceptable when it is the best available support. Never use SOURCE_TIER 4/caution as the sole support for a required slot kind. "
                    "Add human_detail, role_category, transition_hook, onscreen_label, and optional context slots only when supported by exact excerpts. "
                    "onscreen_label is metadata for Producer File/on-screen text, never spoken narration; use only sourced full name, concise role, operator or build count, and service/date range. "
                    "Every evidence segment must have evidence_id, kind, one atomic claim, source_excerpt, source_url, source_title, locator, numeric_tokens, and confidence. "
                    "Each source_excerpt must be copied from EXACT_TEXT in the verified source package below; source_url and locator must match the same fetched excerpt row. "
                    "Do not use memory, training data, general knowledge, or unsupplied web facts. "
                    "Be precise or be silent: if the exact excerpts cannot verify a claim to reasonable confidence, soften it or omit it. "
                    "If excerpts conflict on a number, date, superlative, or specification, use the more conservative supported wording, hedge it, or leave it out; never pick the higher or more dramatic claim. "
                    "Do not create script_beats or a paragraph. Keep prose concise and complete the JSON object. Do not reopen the roster.\n\n"
                    f"BAD/RAW CARD:\n{raw}\n\n{source_label}:\n{legacy_source}"
                )
                raw = await anthropic_client.generate(
                    prompt=repair_prompt,
                    system_prompt="You repair one JSON research card. Output only valid JSON.",
                    max_tokens=2400,
                    temperature=0.05,
                )
                try:
                    text = str(raw or "").strip()
                    if text.startswith("```"):
                        import re as _re_uh2
                        text = _re_uh2.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=_re_uh2.I | _re_uh2.S).strip()
                    card = _hydrate_compatibility_fields(_json_uh.loads(text))
                    warnings = _card_warnings(machine, card, verified_source_package if target_code else None, require_source_package=bool(target_code))
                except Exception as e:
                    card = {"unit": machine, "validation": {"passed": False}, "raw_output": str(raw or "")[:4000]}
                    warnings = [f"invalid JSON after repair: {str(e)[:120]}"]

            # Canonical identity/index come from the immutable roster, never the
            # model. This does not permit the card pass to alter roster contents.
            if not isinstance(card, dict):
                card = {"unit": machine, "validation": {"passed": False}, "raw_output": str(raw or "")[:4000]}
                warnings = warnings or ["research card was not an object after repair"]
            card["unit"] = machine
            card["include"] = True
            card["locked_roster_index"] = i
            if target_code:
                card["source_package_key"] = target_code
            unit_cards.append(card)
            validation_units.append({"machine": machine, "passed": not warnings, "warnings": warnings})

            if _json_uh.dumps(payload.get("unit_roster"), sort_keys=True, ensure_ascii=False) != locked_roster_snapshot:
                warnings = ["locked unit_roster changed during per-machine research"]
                validation_units[-1] = {"machine": machine, "passed": False, "warnings": warnings}

            # Durable checkpoint after each machine. A crash or later-machine
            # failure cannot discard research cards already completed.
            roster_order = {_normalized_unit_code(item): index for index, item in enumerate(roster)}
            unit_cards.sort(key=lambda item: roster_order.get(_normalized_unit_code(_unit_display_name(item)), len(roster)))
            payload["unit_research_cards"] = unit_cards
            target_machine_passed = not warnings
            full_validation_units, full_hold_passed = (
                _full_research_validation(unit_cards)
                if target_code else
                (validation_units, not warnings and i == len(roster))
            )
            payload["unit_research_hold_validation"] = {
                "passed": full_hold_passed,
                "in_progress": False if target_code else not warnings and i < len(roster),
                "units": full_validation_units,
            }
            if target_code:
                payload["unit_research_hold_validation"]["target_machine"] = machine
                payload["unit_research_hold_validation"]["target_machine_passed"] = target_machine_passed
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
        full_validation_units, full_hold_passed = (
            _full_research_validation(unit_cards)
            if target_code else
            (validation_units, True)
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
        held images (seen live on DvsU 2026-07-07). The channel format is one
        machine / one paragraph / one image / one caption, so re-split the
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
    def _validate_static_unit_paragraph(machine: str, paragraph: str) -> list[str]:
        """Deterministic per-machine gate for static-docu script-hold output."""
        import re

        warnings: list[str] = []
        text = str(paragraph or "").strip()
        wc = _spoken_word_count(text)
        machine_code = _normalized_unit_code(machine)
        if not text:
            warnings.append("empty paragraph")
        if "\n" in text:
            warnings.append("must be exactly one paragraph")
        # Anton/DVsU hard production range. Code is authoritative; model
        # self-counts are ignored.
        if wc < _ANTON_PARAGRAPH_MIN_WORDS or wc > _ANTON_PARAGRAPH_MAX_WORDS:
            warnings.append(f"word count {wc} outside {_ANTON_PARAGRAPH_WORD_RANGE} script-hold range")
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
        if any(term in lower for term in (
            "one of the greatest", "one of the most incredible", "arguably the greatest",
            "arguably the most", "undoubtedly", "iconic", "legendary", "game-changing",
        )):
            warnings.append("contains forbidden Anton/DVsU hype language")
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

    async def _run_static_script_hold(
        self, video_id: str, video: dict, roster: list[str], target_machine: Optional[str] = None
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

        # The machine writer is not allowed to fall back to the global fact
        # sheet. Research and script are separate artifacts, and every locked
        # machine must have its own persisted card before any script rows change.
        selected_units = (
            [(roster.index(target_machine) + 1, target_machine)]
            if target_machine else list(enumerate(roster, start=1))
        )
        missing_cards = [machine for _, machine in selected_units if _research_card_for_machine(rp, machine) is None]
        if missing_cards:
            msg = "Script-hold requires a saved research card for every locked machine; missing: " + ", ".join(missing_cards)
            await self._log_activity(bot_name, video_id, "failed", msg[:900])
            return {"status": "failed", "error": msg, "video_id": video_id}
        source_gate_failures: list[str] = []
        for _, machine in selected_units:
            selected_card = _research_card_for_machine(rp, machine) or {}
            source_package = _verified_source_package_for_machine(rp, machine)
            source_errors = (
                _verified_machine_source_package_quality_errors(source_package, machine)
                + _verified_machine_source_package_identity_errors(source_package, machine)
                + _validate_card_against_verified_sources(selected_card, source_package)
            )
            if source_errors:
                source_gate_failures.append(f"{machine}: " + "; ".join(source_errors))
        if source_gate_failures:
            prefix = "Script preview evidence gate failed" if target_machine else "Script-hold evidence gate failed"
            msg = prefix + ": " + " | ".join(source_gate_failures)
            await self._log_activity(bot_name, video_id, "failed", msg[:900])
            return {"status": "failed", "error": msg, "video_id": video_id}

        rows = await fetch_all(
            "SELECT voice_id FROM scripts WHERE video_id = $1 AND tenant_id = $2 LIMIT 1",
            video_id, self.tenant_id,
        )
        voice_id = (rows[0].get("voice_id") if rows else None) or "1SM7GgM6IMuvQlz2BwM3"

        # Stage every replacement paragraph in memory. Existing script rows remain
        # untouched unless the complete roster validates successfully.
        paragraphs: list[str] = []
        validation_units: list[dict] = []
        for i, machine in selected_units:
            prev_machine = roster[i - 2] if i > 1 else "None"
            next_machine = roster[i] if i < len(roster) else "None"
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
                    "a contrast with the previous machine",
                )
                opening_brief = f"Do NOT open with the machine name. Open with {opening_modes[(i - 1) % len(opening_modes)]}."
            complete_inventory_mode = _anton_inventory_title_mode(title)
            if complete_inventory_mode:
                story_brief = _inventory_story_brief(rp, machine)
                research_source = _json_sh.dumps(story_brief, ensure_ascii=False, indent=2)
                research_source_kind = "compact_editorial_brief"
                structure_brief = (
                    "FORMAT MODE: COMPLETE INVENTORY MICRO-STORY. The roster fulfills the title; this paragraph only has to make this machine memorable.\n"
                    f"- TARGET {_ANTON_PARAGRAPH_TARGET_WORDS} words, while remaining inside the absolute {_ANTON_PARAGRAPH_WORD_RANGE} validator.\n"
                    "- Before writing, silently rank the Anton slots. Keep the details needed to explain: original problem, engineering decision, tradeoff, and reality. Omit everything else.\n"
                    f"- Use {_ANTON_PARAGRAPH_SENTENCE_RANGE} sentences and no more than 5 factual story beats total. Each sentence should do one clear job, not carry a list.\n"
                    "- Use only sourced numerical details. A number earns its place only when it makes the machine's scale, count, service period, or historical meaning understandable.\n"
                    "- Build a small narrative around one tension, decision, or consequence. Give the machine a natural Anton micro-hook, not a manufactured twist.\n"
                    "- Do not inventory every dimension, engine, payload, speed, range, date, crew feature, and legacy field. Select the 2-4 technical facts that prove the decision, tradeoff, or reality.\n"
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
                    "Silently cherry-pick only the details needed for one clear narrative: problem, decision, tradeoff, reality, and a paragraph-derived landing line. Omission is a feature. "
                    f"Target {_ANTON_PARAGRAPH_TARGET_WORDS} words and {_ANTON_PARAGRAPH_SENTENCE_RANGE} sentences. Use no more than six factual story beats. Never list research-card fields. "
                    "Open with the machine's most interesting tension, ambition, or consequence, then move cleanly to why it mattered. "
                    "Use a sourced memorable_fact when the story plan provides one, but merge it into the strongest required beat instead of adding trivia. "
                    "The final line must land as a verdict, paradox, irony, or reversal; brevity decides which secondary facts to cut, not whether the paragraph has a point. "
                    "Count the finished paragraph before returning it. If it exceeds 110 words, remove the least important fact rather than compressing more facts into longer sentences."
                )
            story_distiller_system_prompt = (
                "You are a source-grounded Anton/DVsU paragraph compiler for a machine documentary. "
                "Output only valid JSON matching the requested schema. Do not write prose outside JSON, markdown, citations, or alternate keys."
            )
            story_plan = None
            bundle = None
            if complete_inventory_mode:
                story_plan = dict(_machine_story_plan(rp, machine))
                story_plan["contract"] = dict(story_plan.get("contract") or {})
                story_plan["contract"]["opening_assignment"] = opening_brief
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
                prompt = (
                    "WRITE ONE ANTON-STYLE PARAGRAPH FROM LOCKED SOURCE SLOTS.\n\n"
                    f"VIDEO TITLE: {title}\n"
                    f"LOCKED MACHINE {i} OF {len(roster)}: {machine}\n"
                    f"PREVIOUS MACHINE: {prev_machine}\n"
                    f"NEXT MACHINE: {next_machine}\n"
                    f"OPENING ASSIGNMENT: {opening_brief}\n\n"
                    "You are not writing from memory. Select only from the locked Anton slots below, then compose one natural paragraph. "
                    "The target movement is four evidence-backed sentences from original_problem, engineering_decision, tradeoff, and reality, then one paragraph-derived conclusion.\n\n"
                    "HARD CONTRACT:\n"
                    "- Return only valid JSON with this exact shape: "
                    '{"editorial_thesis":"single engineering decision or contrast","paragraph":"...","claim_map":[{"span":"exact paragraph words","slot":"original_problem","used_evidence_ids":["..."]}],"onscreen_label":"..."}\n'
                    "- editorial_thesis must be 6-26 words and state the specific engineering decision, tradeoff, or contrast this machine represents. It is not narration and not a generic importance summary.\n"
                    f"- paragraph must be final spoken narration: exactly one paragraph, {_ANTON_PARAGRAPH_WORD_RANGE} words, {_ANTON_PARAGRAPH_SENTENCE_RANGE} natural sentences.\n"
                    "- Follow OPENING ASSIGNMENT exactly. If it says not to open with the machine name, the first sentence must not start with the locked machine name or designation.\n"
                    f"- Target {_ANTON_PARAGRAPH_TARGET_WORDS} words. If you are above 112 words, remove the least important sourced detail instead of compressing more facts. Concise prototype entries may land below 100 only when all evidence beats are complete.\n"
                    "- claim_map must cover every factual clause that carries a date, number, event, service claim, production claim, specification, or sourced consequence.\n"
                    "- claim_map used_evidence_ids must cover original_problem, engineering_decision, tradeoff, and reality.\n"
                    "- If the plan provides a memorable_fact slot, at least one claim_map row must use a memorable_fact evidence ID by folding it into the strongest required beat.\n"
                    "- If the plan provides a human_detail slot for one of the first three benchmark machines, use it inside the strongest evidence-backed beat. Do not add a separate anecdote sentence.\n"
                    "- The final sentence is editorial synthesis from the assembled paragraph only. Do not include it in claim_map; if it needs evidence IDs, rewrite it without the new fact.\n"
                    "- Each claim_map span must be copied exactly from the paragraph and use only evidence IDs from that span's real source slot.\n"
                    "- Exact numbers, specifications, production counts, dates, and superlative terms must cite two independent evidence IDs when the plan contains them; otherwise hedge the claim or remove it.\n"
                    "- You may include role_category and combat_reality when they strengthen the paragraph and are sourced.\n"
                    "- Use only facts supported by the selected evidence IDs. Do not add dates, numbers, names, programs, specifications, causes, events, or claims absent from those claims/source excerpts.\n"
                    "- Prefer voice-ready spoken number words for years and quantities, matching the DVsU Voiceover File Standard. Keep designations/model names like B-52, XB-15, and F-86 as designations. Every number, spelled or numeral, must map to numeric_tokens/source_excerpt in the selected evidence.\n"
                    "- Use at most 8 numerical details total, including years, counts, ranges, speeds, weights, percentages, and spelled numbers.\n"
                    "- Prefer fewer than 6 numerical details when optional slots add clutter; keep only numbers that explain the problem, decision, tradeoff, or reality.\n"
                    "- Do not include optional-slot numbers if required slots already tell the story.\n"
                    "- Avoid high-risk terms unless the exact selected source evidence uses them: first, only, largest, fastest, most, never.\n"
                    "- Vary sentence length for spoken delivery. Do not write three long sentences in a row.\n"
                    "- Do not write a chronological biography. Dates are allowed only when they prove the engineering problem, decision, tradeoff, or reality.\n"
                    "- The paragraph should read like Anton: facts serve the engineering meaning, not an encyclopedia checklist.\n"
                    "- Avoid written-language connector sentence starts: However, Nevertheless, Furthermore, Moreover, Additionally, In addition.\n"
                    "- Do not use ranked-list connectors: Next is, Next came, Another aircraft was, Moving on to, At number, Coming in at number, or on this list. Bridge through problem, contrast, consequence, or the previous machine instead.\n"
                    "- If LOCKED STORY PLAN includes reference_benchmark, use it only for shape and rhythm: word count, sentence count, opening mode, sentence jobs, and final-line job. Do not copy or infer unsourced facts from it.\n"
                    "- Include sourced memorable_fact only when it strengthens one of the four beats. No orphan facts and no separate trivia sentence.\n"
                    "- End with a short verdict, paradox, irony, or reversal based only on the preceding paragraph. The final sentence must be 28 words or fewer and contain no dates, specs, production counts, or new events.\n"
                    "- onscreen_label is metadata only, not narration. It must be empty unless onscreen_label evidence or sourced role/operator/build/date slots support it.\n"
                    "- No citations, headings, markdown, commentary, unit labels, act labels, b-roll cues, thumbnail lines, bracketed production notes, hype, or list transitions.\n\n"
                    f"LOCKED STORY PLAN:\n{_json_sh.dumps(story_plan, ensure_ascii=False, indent=2)}"
                )
                raw_story = await anthropic_client.generate(
                    prompt=prompt,
                    system_prompt=story_distiller_system_prompt + inventory_system_override,
                    max_tokens=950,
                    temperature=0.25,
                )
                bundle = _parse_machine_story_sentences(raw_story)
                paragraph, warnings = _validate_machine_story_sentences(machine, story_plan, bundle)
                research_source_kind = "structured_story_plan"
            else:
                prompt = (
                    "Write ONE spoken narration paragraph for a Designed vs Used static machine documentary.\n\n"
                    f"VIDEO TITLE: {title}\n"
                    f"VIDEO THESIS / ARC: {video_thesis}\n"
                    f"LOCKED MACHINE {i} OF {len(roster)}: {machine}\n"
                    f"PREVIOUS MACHINE: {prev_machine}\n"
                    f"NEXT MACHINE: {next_machine}\n\n"
                    "HARD CONTRACT:\n"
                    f"- Return exactly ONE paragraph, {_ANTON_PARAGRAPH_WORD_RANGE} words inclusive. Expand any result below {_ANTON_PARAGRAPH_MIN_WORDS}.\n"
                    "- The paragraph is final voiceover narration, not notes. No heading, markdown, bullets, labels, citations, JSON, b-roll cues, thumbnail lines, or bracketed production notes.\n"
                    "- Concentrate all effort on THIS machine only. Do not summarize the whole roster.\n"
                    f"- Use only facts supported by the {research_source_kind} below. If a detail is not supported, omit it.\n"
                    "- Include the locked machine designation/name naturally.\n"
                    f"- OPENING ASSIGNMENT: {opening_brief}\n"
                    f"{structure_brief}"
                    "- Documentary authority: calm, precise, spoken, and specific. No hype, generic praise, Wikipedia opening, list writing, or spec dump.\n"
                    "- Vary sentence length for spoken delivery. Do not write three long sentences in a row.\n"
                    "- Do not write a chronological biography. Dates are allowed only when they prove the engineering problem, decision, tradeoff, or reality.\n"
                    "- Avoid written-language connector sentence starts such as However, Nevertheless, Furthermore, Moreover, Additionally, or In addition.\n"
                    "- Bridge naturally from the previous machine when useful, but never use ranked-list connectors such as Next is, Next came, Another aircraft was, Moving on to, At number, Coming in at number, or on this list.\n\n"
                    f"RESEARCH SOURCE ({research_source_kind}):\n{research_source}"
                )
                paragraph = await anthropic_client.generate(
                    prompt=prompt,
                    system_prompt=script_system_prompt + inventory_system_override,
                    max_tokens=450,
                    temperature=0.45,
                )
                paragraph = self._clean_static_unit_paragraph(paragraph)
                warnings = self._validate_static_unit_paragraph(machine, paragraph)
                warnings.extend(_opening_assignment_warnings(machine, paragraph, opening_brief))

            if warnings:
                if complete_inventory_mode:
                    repair_prompt = (
                        "REBUILD THE ANTON-STYLE PARAGRAPH JSON FROM THE SAME LOCKED STORY PLAN.\n\n"
                        f"Validation warnings: {'; '.join(warnings)}\n\n"
                        f"OPENING ASSIGNMENT: {opening_brief}\n\n"
                        "Return only the exact JSON shape: {\"editorial_thesis\":\"single engineering decision or contrast\",\"paragraph\":\"...\",\"claim_map\":[{\"span\":\"exact paragraph words\",\"slot\":\"original_problem\",\"used_evidence_ids\":[\"...\"]}],\"onscreen_label\":\"...\"}. "
                        "editorial_thesis must be 6-26 words and state the specific engineering decision, tradeoff, or contrast this machine represents; it is not narration and not a generic importance summary. "
                        f"Write exactly one paragraph, target {_ANTON_PARAGRAPH_TARGET_WORDS} words, absolute range {_ANTON_PARAGRAPH_WORD_RANGE} words, {_ANTON_PARAGRAPH_SENTENCE_RANGE} sentences. "
                        "Follow OPENING ASSIGNMENT exactly; if it says not to open with the machine name, the first sentence must not start with the locked machine name or designation. "
                        "claim_map must cover every factual clause and use selected evidence IDs covering original_problem, engineering_decision, tradeoff, and reality. "
                        "If the plan provides a memorable_fact slot, use at least one memorable_fact evidence ID inside the strongest required beat; do not add a separate trivia sentence. "
                        "If the plan provides a human_detail slot for one of the first three benchmark machines, use it inside the strongest evidence-backed beat; do not add a separate anecdote sentence. "
                        "The final sentence must be editorial synthesis from the rebuilt paragraph only. Do not include it in claim_map; if it needs evidence IDs, rewrite it without the new fact. "
                        "Exact numbers, specifications, production counts, dates, and superlative terms must cite two independent evidence IDs when available; otherwise hedge the claim or remove it. "
                        "Prefer voice-ready spoken number words for years and quantities while preserving designations/model names like B-52, XB-15, and F-86. Use at most 8 numerical details total, including years, counts, ranges, speeds, weights, percentages, and spelled numbers. "
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
                        "End with a paragraph-derived Anton-style verdict of 28 words or fewer, not a generic summary, and do not add dates, specs, production counts, or new events there. The rejected draft is hidden; start fresh.\n\n"
                        f"LOCKED STORY PLAN:\n{_json_sh.dumps(story_plan, ensure_ascii=False, indent=2)}"
                    )
                    raw_story = await anthropic_client.generate(
                        prompt=repair_prompt,
                        system_prompt=story_distiller_system_prompt + inventory_system_override,
                        max_tokens=950,
                        temperature=0.15,
                    )
                    bundle = _parse_machine_story_sentences(raw_story)
                    paragraph, warnings = _validate_machine_story_sentences(machine, story_plan, bundle)
                else:
                    repair_prompt = (
                        f"Write a fresh replacement paragraph for LOCKED MACHINE: {machine}.\n"
                        f"Validation warnings: {'; '.join(warnings)}\n\n"
                        f"OPENING ASSIGNMENT: {opening_brief}\n\n"
                        f"Return exactly ONE spoken paragraph, {_ANTON_PARAGRAPH_WORD_RANGE} words inclusive. Expand any result below {_ANTON_PARAGRAPH_MIN_WORDS} and cut any result above {_ANTON_PARAGRAPH_MAX_WORDS}. "
                        "Follow OPENING ASSIGNMENT exactly. No markdown, labels, b-roll cues, thumbnail lines, or bracketed production notes. Include the locked designation/name. Use only the same research source. "
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
                    warnings = self._validate_static_unit_paragraph(machine, paragraph)
                    warnings.extend(_opening_assignment_warnings(machine, paragraph, opening_brief))

            quality_audit = _anton_preview_quality_audit(
                machine,
                story_plan or {},
                bundle or {},
                paragraph,
                warnings,
            ) if complete_inventory_mode else {}
            validation_units.append({
                "scene": i,
                "machine": machine,
                "word_count": _spoken_word_count(paragraph),
                "research_source": research_source_kind,
                "passed": not warnings,
                "warnings": warnings,
                "quality_audit": quality_audit,
            })
            if target_machine:
                preview = {
                    "machine": machine,
                    "scene": i,
                    "paragraph": " ".join(paragraph.split()),
                    "word_count": _spoken_word_count(paragraph),
                    "passed": not warnings,
                    "warnings": warnings,
                    "onscreen_label": str(bundle.get("onscreen_label") or "").strip(),
                    "research_source": research_source_kind,
                    "story_plan": story_plan,
                    "claim_bundle": bundle,
                    "quality_audit": quality_audit,
                }
                preview_save_result = await execute(
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
                    _verified_source_cache_key(machine), _json_sh.dumps(preview), video_id, self.tenant_id, locked_roster_snapshot,
                )
                if self._db_write_missed(preview_save_result):
                    msg = "persisted unit_roster changed concurrently; script preview save refused"
                    await self._log_activity(bot_name, video_id, "failed", msg)
                    return {"status": "failed", "error": msg, "video_id": video_id}
                await self._log_activity(
                    bot_name, video_id, "completed" if not warnings else "failed",
                    f"Single-machine script preview {'passed' if not warnings else 'needs review'}: {machine}",
                )
                return {"status": "completed", "video_id": video_id, "preview": preview}
            if warnings:
                validation = {"script_hold": {"passed": False, "units": validation_units}}
                await execute(
                    "UPDATE videos SET script_validation = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
                    _json_sh.dumps(validation), video_id, self.tenant_id,
                )
                msg = f"Script-hold stopped at machine {i}/{len(roster)} ({machine}): " + "; ".join(warnings)
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
        validation["script_hold"] = {"passed": True, "units": validation_units}
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

    async def _grade_and_maybe_revise_script(self, video_id: str, regenerate=None) -> None:
        """Phase 2 retention gate: grade the freshly generated script against the
        YouTube retention rules (hook speed, but/therefore causality, escalating
        stakes, a delivered payoff, specificity). On a 'revise'/'regenerate'
        verdict, append the grader's concrete guidance to writer_guidance and
        regenerate the script ONCE.

        Mirrors originality.py's philosophy: no user-facing gate, just a silent
        quality nudge. Fail-open and best-effort - any error here leaves the
        already-generated script in place and never blocks the pipeline.
        """
        try:
            import asyncio
            from originality import grade_script, grade_script_with_client

            video = await self._get_video(video_id)
            script = (video or {}).get("script") or ""
            if not script.strip():
                return

            # Niche keeps grading niche-appropriate (a how-to is not punished for
            # lacking a story arc). Resolved defensively; falls back to neutral.
            niche = ""
            try:
                identity = await build_identity_context(self.tenant_id, video)
                niche = identity.niche
            except Exception:
                niche = ""

            draft = {
                "niche": niche,
                "title": video.get("video_title"),
                "hook": video.get("executive_hook") or video.get("hook_script"),
                "script": script,
            }
            # Route through the tenant's AnthropicClient so grading works for
            # EVERY tenant - direct-key tenants AND Kie-gateway tenants (Bearer
            # auth + model aliasing). Fall back to the bare direct client only if
            # the pipeline has no client (edge case).
            client = getattr(self._pipeline, "anthropic", None)
            if client is not None:
                grade = await grade_script_with_client(draft, client)
            else:
                grade = await asyncio.to_thread(grade_script, draft)
            print(f"[Script] retention grade {video_id[:8]}: {grade.verdict} "
                  f"(score {grade.score}) gates={grade.failing_gates}", flush=True)

            regenerating = bool(grade.needs_revision and (grade.rewrite_guidance or "").strip())
            # Capture the grade so the creator can SEE it (autopilot scorecard + chat),
            # whether or not we re-rolled - transparency, not a black box.
            await self._record_applied_retention(video_id, grade, regenerating)
            if not regenerating:
                return

            # Append the grader's guidance and regenerate exactly once. writer_guidance
            # is read by BOTH the documentary brief_translator and the modeled-script
            # prompt, so the re-run picks it up on either pathway.
            existing = (video.get("writer_guidance") or "")
            block = (
                "\n\n--- RETENTION REVISION (auto, internal) ---\n"
                + grade.rewrite_guidance.strip()
                + "\n--- END RETENTION REVISION ---"
            )
            await execute(
                "UPDATE videos SET writer_guidance = $1 WHERE id = $2",
                existing + block, video_id,
            )
            # Modeled videos must re-roll through the MODELED generator, not the
            # documentary brief_translator (which would steamroll their style).
            if regenerate is not None:
                await regenerate()
            else:
                self._load_idea_from_video(video_id)
                await self._pipeline.run_brief_translator()
            print(f"[Script] regenerated {video_id[:8]} once after retention grade", flush=True)
            # ponytail: one re-roll only. If the rewrite is still weak it ships -
            # a silent nudge, not a hard gate; looping would risk stalling a run.
        except Exception as e:
            print(f"[Script] retention grade skipped for {video_id[:8]}: {str(e)[:200]}", flush=True)

    async def _record_applied_retention(self, video_id: str, grade, regenerated: bool) -> None:
        """Persist the retention grade onto videos.applied_intelligence so the creator
        can see what the hook/retention engine did (autopilot scorecard + chat).
        Best-effort; never blocks the pipeline."""
        try:
            import json as _json
            rec = {
                "fired": bool(regenerated),
                "score": getattr(grade, "score", None),
                "verdict": getattr(grade, "verdict", None),
                "failing_gates": list(getattr(grade, "failing_gates", []) or []),
            }
            await execute(
                "UPDATE videos SET applied_intelligence = "
                "COALESCE(applied_intelligence, '{}'::jsonb) || jsonb_build_object('retention_grade', $1::jsonb) "
                "WHERE id = $2",
                _json.dumps(rec), video_id,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[Script] record retention grade failed: {str(e)[:160]}")

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

ONE LOCATION PER SCENE (important) — every scene must take place in a SINGLE physical location.
The moment the action moves somewhere new (e.g. living room -> garage -> lakeside), START A NEW
SCENE with a new @@@SCENE n@@@ marker. A beat that travels through several places becomes several
scenes, one per place. NEVER let one scene span two locations — this keeps each scene's visuals
consistent for the storyboard and the stitched video.

Target length: about {target_words} words total, spread across the scenes.

Background material you may draw from (use only what fits the video's style and audience):
{research_excerpt}

VOICE — write every scene in the EXACT voice, tense, vocabulary and FORMAT your style
instructions above define. If they call for character DIALOGUE, write dialogue (speaker
turns like "Mum: ..." are fine); if narration, write narration; if both, both. Match their
sentence length and reading level. Do NOT default to a third-person narrator unless the
style explicitly says to — the style above wins over any default.

FORMAT — plain text, no JSON, no markdown headings. Start each scene on its own line with
exactly this marker:
@@@SCENE n@@@
where n is the scene number (1, 2, 3, ...). Put that scene's spoken text on the lines right
after its marker — exactly what is heard in that scene. Use the markers and nothing else to
separate scenes."""

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
                """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
                   VALUES ($1, $2, $3, $4, $5, 'Create', $6)""",
                self.tenant_id, video_id, i, scene["text"].strip(),
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
        return {"status": "ready_for_voice", "video_id": video_id, "new_status": "ready_for_voice"}

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

    async def run_script(self, video_id: str) -> dict:
        """Generate script for a video.

        Args:
            video_id: Supabase video UUID

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()
        bot_name = "Script Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

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
                roster_gate = rp_for_gate.get("unit_roster_validation") or _roster_validation(
                    video.get("video_title") or video.get("headline") or "", rp_for_gate
                )
                if isinstance(roster_gate, str):
                    try:
                        roster_gate = _json_gate.loads(roster_gate)
                    except Exception:
                        roster_gate = {}
                if roster_gate.get("complete_title") and not roster_gate.get("passed"):
                    msg = "Fix research roster before scripting: " + "; ".join(roster_gate.get("warnings", []))
                    await self._log_activity(bot_name, video_id, "failed", msg[:900])
                    return {"status": "failed", "error": msg}

            # Creator-supplied scripts are used VERBATIM: no generation, no
            # grading, no gates (user_script.set_user_script already persisted
            # the scenes). This guard also makes re-runs and the queue/autopilot
            # step loop pass straight through the script stage.
            if (video.get("script_source") or "generated") == "user_supplied" and (video.get("script") or "").strip():
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
                await self._inject_learnings_into_writer_guidance(video_id)
                video = await self._get_video(video_id)
                result = await self._run_modeled_script(video_id, video)
                await self._grade_and_maybe_revise_script(
                    video_id, regenerate=lambda: self._regen_modeled_script(video_id)
                )
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
                return await self._run_static_script_hold(video_id, video, roster)

            # Run normal global script generation for animation/narrative videos,
            # and for static docs without an explicit locked machine roster.
            result = await self._pipeline.run_brief_translator()

            if result.get("error"):
                raise Exception(result["error"])

            # Phase 2: silent retention grade + at most one auto-revise.
            # Best-effort; never blocks the stage.
            await self._grade_and_maybe_revise_script(video_id)

            # Static documentaries are exact-figures formats: fact-check the
            # script against the research payload and re-roll once if claims
            # can't be traced. (Advisory-only elsewhere; a GATE here.)
            if (video.get("render_mode") or "") == "static_docu":
                await self._factual_gate_static(video_id)
                # One machine / one paragraph / one image: scene rows must be
                # unit paragraphs, not acts (the bot writes one row per act).
                await self._resplit_static_scenes(video_id)
                roster_check = await self._validate_static_script_roster(video_id)
                if roster_check.get("complete_title") and not roster_check.get("passed"):
                    raise Exception("Script roster gate failed: " + "; ".join(roster_check.get("warnings", [])))

            # Dialogue intelligence runs unattended after EVERY script path —
            # the modeled and user-supplied paths already had this hook, but
            # the brief-translator path (the most common one) was missing it,
            # so dialogue scripts stayed untagged and voice/clips fell back to
            # narrator-only. Best-effort: a tagging hiccup must not fail the
            # stage (manual retro trigger: POST .../script/tag-dialogue).
            try:
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

    async def run_voice(self, video_id: str, scene: int = None) -> dict:
        """Generate voice narration for a video.

        Args:
            video_id: Supabase video UUID
            scene: Optional scene number for single-scene generation

        Returns:
            Dict with status and result
        """
        await self._ensure_initialized()
        bot_name = "Voice Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

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
            result = await self._pipeline.run_voice_bot()

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

    async def _stamp_padded_audio(self, video_id: str, scene: int, line: dict, pad_url: str) -> None:
        """Record a speaking shot's padded performance audio on its segment in
        the dialogue_segments jsonb. Two jobs: bookkeeping, and the media-proxy
        ALLOWLIST — the proxy only serves DB-referenced files, and the talking-
        clip model fetches this audio through it. Best-effort."""
        try:
            import json as _json
            from clip_dialogue import norm as _norm
            row = await fetch_one(
                "SELECT id, dialogue_segments FROM scripts "
                "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3",
                video_id, self.tenant_id, scene)
            raw = (row or {}).get("dialogue_segments")
            if isinstance(raw, str):
                raw = _json.loads(raw)
            if not raw:
                return
            for seg in raw:
                if (seg.get("type") == "dialogue"
                        and _norm(seg.get("speaker")) == _norm(line.get("speaker"))
                        and _norm(seg.get("text")) == _norm(line.get("text"))):
                    seg["padded_audio_url"] = pad_url
                    break
            else:
                return
            await execute(
                "UPDATE scripts SET dialogue_segments=$1, updated_at=now() WHERE id=$2",
                _json.dumps(raw), row["id"])
        except Exception as e:
            print(f"[clips] padded-audio stamp failed ({str(e)[:120]})", flush=True)

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
    ) -> dict:
        """Generate motion clips from final pictures — one card, one scene, or all.

        All three rungs of the trust ladder land here (tap a card / Animate
        this scene / Animate everything). Honors videos.video_model via
        MODEL_REGISTRY (Grok + Veo wired). Clip result URLs expire ~24h, so
        every clip downloads immediately and persists to Drive {video}/clips/.
        Additive: only a full run that finishes every clip advances status.
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

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            from shared.channel_profile import MODEL_REGISTRY, DEFAULT_VIDEO_MODEL
            model_id = (video.get("video_model") or "").strip() or DEFAULT_VIDEO_MODEL
            profile = MODEL_REGISTRY.get(model_id)
            # Only models with a live generation path are selectable — the
            # old dropdown silently ignored the choice and always ran Grok.
            wired = {"grok-imagine", "seedance-2-fast", "veo-3.1-fast", "veo-3.1-quality"}
            if not profile or model_id not in wired:
                return {"status": "failed", "error": user_facing(
                    f"'{model_id}' isn't available yet — pick Grok Imagine or Veo 3.1 under Advanced.")}

            where = "video_id = $1 AND tenant_id = $2"
            params = [video_id, self.tenant_id]
            if asset_id:
                where += " AND id = $3"
                params.append(asset_id)
            elif scene is not None:
                where += " AND scene = $3"
                params.append(scene)
            rows = await fetch_all(
                f"SELECT id, scene, image_index, image_url, drive_image_url, video_prompt, "
                f"video_clip_url, duration_seconds, sentence_text, image_prompt, assigned_dialogue "
                f"FROM assets WHERE {where} ORDER BY scene, image_index",
                *params,
            )
            todo = [
                r for r in rows
                if (r.get("image_url") or r.get("drive_image_url"))
                and (force or not r.get("video_clip_url"))
            ]
            if not todo:
                msg = "Nothing to animate — every picture here already has a clip."
                await self._log_activity(bot_name, video_id, "completed", msg)
                return {"status": "completed", "video_id": video_id, "message": msg,
                        "clips_generated": 0, "clips_failed": 0, "cost": 0.0}

            label = (f"clip S{todo[0]['scene']}.{todo[0]['image_index']}" if asset_id
                     else f"scene {scene}" if scene is not None else f"{len(todo)} clips")
            await self._log_activity(bot_name, video_id, "started", f"Animating {label} ({model_id})")
            await self._install_cancel_support(video_id)
            should_cancel = self._pipeline.should_cancel

            base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")

            def _proxy_url(url: str) -> str:
                m = _re.search(r"[?&]id=([\w-]+)", url) or _re.search(r"/d/([\w-]+)", url)
                return f"{base}/api/media/drive/{m.group(1)}" if m else url

            from storage import upload_bytes
            from clip_dialogue import (load_dialogue_lines, match_lines, match_assigned,
                                       speaking_prompt, native_speaking_prompt, motion_guard,
                                       duck_audio, download_voice, mux_voice, pad_line_audio,
                                       DIALOGUE_VOICE_LEAD_SECONDS, speech_seconds,
                                       spoken_word_count, pick_clip_duration, clip_cost_for)
            from shared.clients.image_client import CONTENT_POLICY_MARKER
            client = self._pipeline.image_client
            # Grok-imagine takes any duration 6–30s (Kie). Use every tier the
            # model profile declares so a long spoken line isn't cut at 6/10s;
            # the per-clip selector below picks the smallest tier that fits.
            durations = sorted(profile.durations) or [6]

            # Seedance is a drop-in animator with the same call shape as Grok
            # (img, prompt, duration, extra_image_urls). Veo keeps its own branch below.
            _vaspect = (video.get("aspect_ratio") or "16:9")
            _vres = (video.get("video_resolution") or "720p")
            if model_id.startswith("seedance"):
                def animate(img, prompt, duration=6, extra_image_urls=None):
                    return client.generate_video_seedance(
                        img, prompt, duration=duration,
                        extra_image_urls=extra_image_urls, aspect_ratio=_vaspect)
            else:
                # Pass the video's aspect + resolution to Grok — without aspect it
                # crops every clip to vertical (16:9 came out 9:16); resolution is
                # the quality selector (480p / 720p).
                def animate(img, prompt, duration=6, extra_image_urls=None):
                    return client.generate_video(
                        img, prompt, duration=duration,
                        extra_image_urls=extra_image_urls,
                        aspect_ratio=_vaspect, resolution=_vres)

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
            # Option A voice lock: grok_native speaking clips get their audio
            # re-rendered in the character's pinned ElevenLabs voice (speech-
            # to-speech keeps timing, so the mouth stays synced). Needs the
            # tenant's direct ElevenLabs key; off without one, or via env.
            xi_key = None
            if native_voices and os.getenv("VOICE_SWAP", "on") != "off":
                from vault import get_secret
                xi_key = await get_secret("elevenlabs_api_key", self.tenant_id)

            def _decorate(core_prompt: str) -> str:
                # @image1 is the GROUND TRUTH for this shot, and the
                # constraints LEAD the prompt (early instructions win — the
                # trailing version still let Grok invent a toddler on a
                # panel that doesn't show Tom). References can only lock
                # characters who are IN the picture; off-screen characters
                # must stay off-screen.
                p = ("Animate @image1 exactly as shown: same characters, same faces, ages,"
                     " heights, proportions and clothing. NEVER introduce a character who"
                     " is not visible in @image1 — if someone is off-screen, only hands or"
                     " feet may enter the frame.")
                if sheet:
                    p += (f" @image2 is the official cast sheet"
                          + (f" ({cast_names})" if cast_names else "")
                          + " — anyone visible in @image1 must match it precisely.")
                if style_note:
                    p += f" Art style: {style_note}"
                p += f" Motion: {core_prompt}"
                return p

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

            async def _animate_recover(r, image_url, full_prompt, clip_dur):
                """Generate the clip; if Grok's content filter (failCode 430) flags
                the frame, redraw the shot with a safer wholesome framing and retry
                ONCE. Returns (clip_url_or_None, image_url_actually_used)."""
                extra = [_proxy_url(sheet)] if sheet else None
                try:
                    return (await _gen(animate(image_url, full_prompt, duration=clip_dur,
                                               extra_image_urls=extra)), image_url)
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
                        return (await _gen(animate(new_img, full_prompt, duration=clip_dur,
                                                   extra_image_urls=extra)), new_img)
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
                    lines = ([] if (native_voices and vp) else
                             [l for l in (match_lines(r.get("sentence_text"), dialogue_by_scene.get(sc))
                                          or match_assigned(r.get("assigned_dialogue"), dialogue_by_scene.get(sc)))
                              if native_voices or l.get("audio_url")])
                    # Speaking = a matched line, or (native) an embedded line.
                    is_speaking = bool(lines) or (native_voices and embedded_words > 0)

                    if lines:
                        # Speaking card → Grok animates the FULL SCENE.
                        # Loose sync by design (Ryan's call): scene
                        # continuity beats mouth precision in this format —
                        # see decisions.md 2026-06-12.
                        # DUAL-ANIMATOR ROUTING (Ryan's call, 2026-07-03):
                        # voice_over speaking shots animate via InfiniteTalk —
                        # the mouth is GENERATED FROM the line's waveform, so
                        # lip-sync is structural (Grok speaking was a coin flip:
                        # the live test's second mouth never moved). Silent
                        # shots keep Grok's camera/action motion. Any talking
                        # failure falls back to the Grok+mux path below.
                        clip_url = None
                        clip_cost = 0.0
                        clip_dur = None
                        talked = False
                        talking_model = os.getenv("TALKING_CLIP_MODEL", "infinitalk")
                        if not native_voices and talking_model != "off":
                            try:
                                vbytes = [b for b in [await download_voice(l["audio_url"])
                                                      for l in lines] if b]
                                if vbytes:
                                    padded = await pad_line_audio(
                                        vbytes, head=DIALOGUE_VOICE_LEAD_SECONDS,
                                        tail=float(os.getenv("PERFORM_DIALOGUE_TAIL", "0.25")))
                                    pad_url = await upload_bytes(
                                        padded, f"{video_id}/voice/padded/S{sc:02d}-{idx:02d}.mp3",
                                        "audio/mpeg", tenant_id=self.tenant_id)
                                    # The media proxy serves only DB-referenced
                                    # files — stamp the padded url into the
                                    # first line's segment jsonb (allowlist).
                                    await self._stamp_padded_audio(video_id, sc, lines[0], pad_url)
                                    talk_prompt = (
                                        f"{(lines[0].get('speaker') or 'The character')} speaks "
                                        "naturally with expressive face and small natural "
                                        "gestures, keeping the exact pose, framing and scene "
                                        "shown in the image.")
                                    clip_url = await asyncio.wait_for(
                                        client.generate_talking_video(
                                            img + ".png" if "/api/media/drive/" in img else img,
                                            _proxy_url(pad_url) + ".mp3",
                                            prompt=talk_prompt,
                                            resolution=_vres),
                                        timeout=int(os.getenv("TALKING_CLIP_DEADLINE", "1200")))
                                    if clip_url:
                                        talked = True
                                        audio_len = (DIALOGUE_VOICE_LEAD_SECONDS
                                                     + sum(float(l.get("duration") or 2.0) for l in lines)
                                                     + float(os.getenv("PERFORM_DIALOGUE_TAIL", "0.25")))
                                        clip_dur = round(audio_len, 2)
                                        clip_cost = round(audio_len * float(
                                            os.getenv("INFINITALK_USD_PER_SEC", "0.03")), 3)
                            except Exception as te:
                                print(f"[clips] S{sc}.{idx} talking clip failed "
                                      f"({str(te)[:120]}) — falling back to Grok", flush=True)
                                clip_url = None
                        if not clip_url:
                            # Grok speaking path (grok_native, kill-switched
                            # talking model, or InfiniteTalk failure).
                            # A coverage master already has a WRITTEN motion
                            # prompt with its line embedded — keep that
                            # direction; generic speaking_prompt is the
                            # fallback for legacy cards.
                            if native_voices:
                                core = native_speaking_prompt(lines, r.get("sentence_text"))
                            elif vp and embedded_words > 0:
                                core = vp
                            else:
                                core = speaking_prompt(lines)
                            prompt = _decorate(core)
                            # The whole spoken line has to fit inside the clip,
                            # or Grok cuts it off. native = Grok times its own
                            # speech; voice_over = the synthesized line's
                            # measured length plus its lead-in.
                            if native_voices:
                                need = speech_seconds(spoken_word_count(core))
                            else:
                                need = (sum(float(l.get("duration") or 2.0) for l in lines)
                                        + DIALOGUE_VOICE_LEAD_SECONDS)
                            clip_dur = pick_clip_duration(need, durations)
                            clip_url, img = await _animate_recover(r, img, prompt, clip_dur)
                            clip_cost = clip_cost_for(profile.cost_per_clip, clip_dur)
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
                        # People rule (Ryan: S1.4's bird close-up grew an
                        # invented toddler — twice): cutaway cards get an
                        # absolute NO PEOPLE, every other narration card gets
                        # nobody-NEW. Decision table lives in motion_guard.
                        prompt = motion_guard(r.get("image_prompt"),
                                              r.get("sentence_text"), cast_names) + prompt
                        # A coverage shot carries its spoken line INSIDE the
                        # motion prompt (<Name> says ...: "line") — size the clip
                        # to exactly how long that line takes to say, so the video
                        # ENDS when the speech does and Grok has no slack to ad-lib
                        # filler (live finding: an over-long clip invents garbage
                        # past the line). A silent shot keeps the base length; a
                        # timed segment still acts as a floor.
                        spoken_secs = speech_seconds(spoken_word_count(prompt))
                        seg_dur = float(r.get("duration_seconds") or 0)
                        clip_dur = pick_clip_duration(max(spoken_secs, seg_dur), durations)
                        if model_id.startswith("veo-3.1"):
                            veo_model = client.VEO_MODEL_QUALITY if model_id.endswith("quality") else client.VEO_MODEL_FAST
                            clip_url = await _gen(client.generate_video_veo(prompt, image_url=img, model=veo_model))
                            clip_dur = profile.durations[0]
                        else:
                            clip_url, img = await _animate_recover(r, img, _decorate(prompt), clip_dur)
                        clip_cost = clip_cost_for(profile.cost_per_clip, clip_dur)

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
                    try:
                        if native_voices and is_speaking and xi_key:
                            # Option A voice lock: swap Grok's invented voice
                            # for the speaker's pinned ElevenLabs voice. Same
                            # timing, same mouth, consistent identity. A swap
                            # failure ships Grok's original take (never lose
                            # a paid clip over the polish pass).
                            spk = (r.get("assigned_dialogue") or "").split(":", 1)[0].strip()
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
                                    await _report(f"S{sc}.{idx}: voices locked "
                                                  f"({len(turn_speakers)} speakers)")
                                except Exception as se:
                                    print(f"[clips] S{sc}.{idx} multi-voice swap failed "
                                          f"({str(se)[:120]}) — keeping Grok's take", flush=True)
                            elif voice_id:
                                try:
                                    from clip_dialogue import swap_voice
                                    clip_bytes = await swap_voice(clip_bytes, voice_id, xi_key)
                                    await _report(f"S{sc}.{idx}: voice locked ({spk})")
                                except Exception as se:
                                    print(f"[clips] S{sc}.{idx} voice swap failed "
                                          f"({str(se)[:120]}) — keeping Grok's take", flush=True)
                        elif lines and not native_voices and talked:
                            pass  # an InfiniteTalk clip already carries its line
                        elif lines and not native_voices:
                            voice_secs = sum(float(l.get("duration") or 2.0) for l in lines)
                            vbytes = [b for b in [await download_voice(l["audio_url"]) for l in lines] if b]
                            if vbytes:
                                lead = max(0.0, min(DIALOGUE_VOICE_LEAD_SECONDS,
                                                    float(clip_dur) - voice_secs - 0.1))
                                clip_bytes = await mux_voice(clip_bytes, vbytes,
                                                             delay_seconds=lead, bed_gain=0.2)
                            else:
                                clip_bytes = await duck_audio(clip_bytes)
                        elif not is_speaking and getattr(profile, "strip_audio", False):
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
                    await execute(
                        "UPDATE assets SET video_clip_url = $1, video_duration = $2, "
                        "updated_at = now() WHERE id = $3",
                        drive_url, clip_dur, r["id"],
                    )
                    done += 1
                    cost += clip_cost
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
                    try:
                        await _report(f"S{r.get('scene')}.{r.get('image_index')} hit an error ({done + failed}/{total})")
                    except Exception:
                        pass

            await asyncio.gather(*[_safe_one(r) for r in todo])

            if cancelled:
                msg = f"Stopped — kept {done} finished clip(s). Animate again to resume."
                await self._log_activity(bot_name, video_id, "completed", msg, cost=cost)
                return {"status": "cancelled", "video_id": video_id, "error": msg,
                        "clips_generated": done, "clips_failed": failed, "cost": cost}

            # Full untargeted run with everything clipped → stage complete.
            if asset_id is None and scene is None and failed == 0:
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
                if asset_id is not None:
                    arow = await fetch_one("SELECT scene FROM assets WHERE id = $1", asset_id)
                    consider = [arow["scene"]] if arow and arow.get("scene") is not None else []
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
                    # the preview sounds like the final render; plain stitch
                    # stays the fallback so a preview never dead-ends.
                    use_perform = (
                        (video.get("dialogue_mode") or "") == "character_dialogue"
                        and (video.get("dialogue_audio") or "voice_over") != "grok_native")
                    for sc in consider:
                        comp = await fetch_one(
                            "SELECT COUNT(*) AS pics, COUNT(video_clip_url) AS clips FROM assets "
                            "WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 "
                            "AND (image_url IS NOT NULL OR drive_image_url IS NOT NULL)",
                            video_id, self.tenant_id, sc)
                        if comp and comp["pics"] > 0 and comp["clips"] == comp["pics"]:
                            try:
                                scene_url = None
                                if use_perform:
                                    try:
                                        from render_perform import assemble_scene
                                        pres = await assemble_scene(video_id, self.tenant_id, sc)
                                        scene_url = pres["scene_video_url"]
                                        print(f"[stitch] scene {sc} performance-assembled "
                                              f"({pres['shots']} shots, {pres['duration_seconds']}s)", flush=True)
                                    except Exception as pe:
                                        print(f"[stitch] scene {sc} performance assembly failed "
                                              f"({str(pe)[:150]}) — falling back to plain stitch", flush=True)
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
                   + (f" — {failed} failed, tap them to retry" if failed else ""))
            await self._log_activity(bot_name, video_id, "completed" if not failed else "completed", msg, cost=cost)
            return {"status": "completed" if done or not failed else "failed",
                    "video_id": video_id, "message": msg,
                    "clips_generated": done, "clips_failed": failed, "cost": cost,
                    "error": msg if failed and not done else None}

        except Exception as e:
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
            return {
                "status": "needs_approval",
                "message": gate_message,
            }

        # Map status to handler
        handlers = {
            "idea_logged": self.run_research,
            "approved": self.run_research,
            "ready_for_scripting": self.run_script,
            # Static documentaries route their image stage to run_coverage_stage,
            # whose static branch creates one image per segment; the legacy
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
        via coverage — the live image path. Replaces the old grid run_prompts+run_images."""
        from scripts.coverage_to_app import generate_coverage_for_video
        return await generate_coverage_for_video(video_id, self.tenant_id, scene=scene)

    async def run_storyboard_sheet(self, video_id: str, scene: int = None) -> dict:
        """Draw the cheap single-image storyboard SHEET preview for a scene via
        coverage. Replaces the old grid run_storyboard_prompts+run_storyboard_images."""
        from scripts.coverage_to_app import generate_storyboard_sheet_for_scene
        return await generate_storyboard_sheet_for_scene(video_id, self.tenant_id, scene=scene)

    async def run_coverage_stage(self, video_id: str) -> dict:
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
        # STATIC-DOCU videos take one archival image per segment instead of
        # multi-angle coverage (no cast, no story bible) — same branch as the
        # chat auto-build, so every entry point produces the same result.
        if (video.get("render_mode") or "") == "static_docu":
            await self._log_activity(bot_name, video_id, "started",
                                     "Creating one image per segment (static documentary)")
            from static_docu import generate_static_images_for_video
            st = await generate_static_images_for_video(video_id, self.tenant_id) or {}
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
        await execute("UPDATE videos SET characters_approved_at = NULL WHERE id=$1 AND tenant_id=$2",
                      video_id, self.tenant_id)
        done = 0
        for i, ch in enumerate(cast):
            row = await fetch_one(
                "INSERT INTO video_characters (tenant_id, video_id, name, description, sort) "
                "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                self.tenant_id, video_id, ch["name"][:120], ch.get("description") or "", i)
            char_id = str(row["id"])
            for attempt in range(3):
                try:
                    temp_url = await _generate_portrait(api_key, ch.get("description") or ch["name"], style_dna, name=ch.get("name") or "")
                    url = await _persist_portrait_url(self.tenant_id, video_id, char_id, temp_url)
                    await execute("UPDATE video_characters SET reference_url=$1, updated_at=now() WHERE id=$2",
                                  url, char_id)
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
        """Generate and persist a Story Bible for a video."""
        await self._ensure_initialized()
        bot_name = "Story Bible Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating Story Bible")

            self._load_idea_from_video(video_id)
            idea = getattr(self._pipeline, "current_idea", None)
            idea_id = getattr(self._pipeline, "current_idea_id", None)
            if not idea or not idea_id:
                raise Exception("Could not load idea for Story Bible generation")

            from storyboard.bot import _generate_story_bible_for_storyboard

            fields = idea.get("fields", idea)
            video_title = fields.get("Video Title", "")
            video_length_min = fields.get("Video Length Min", 10) or 10
            script_records = self._pipeline.airtable.get_scripts_by_title(video_title)
            if not script_records:
                raise Exception(f"No script found for '{video_title}'")

            result = await _generate_story_bible_for_storyboard(
                anthropic_client=self._pipeline.anthropic,
                airtable_client=self._pipeline.airtable,
                idea_id=idea_id,
                video_title=video_title,
                script_records=script_records,
                video_length_min=int(video_length_min),
                slack_client=getattr(self._pipeline, "slack", None),
            )
            if not result:
                raise Exception("Story Bible generation returned empty result")

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
                for idx, (asset_id, panel_url, sc_num, bt_num, img_idx) in enumerate(all_panel_records):
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
                    except Exception as e:
                        _logger.warning("Upscale failed for panel %d: %s — keeping original", idx, e)

                msg += f", {upscaled}/{len(all_panel_records)} upscaled"

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
            await self._log_activity(bot_name, video_id, "started", f"Fixing text on S{sc}.{idx} (GPT Image 2)…")
            res = await client.generate_thumbnail_gpt2(prompt, [ref_url], aspect_ratio=aspect)
            new_url = (res or {}).get("url")
            if not new_url:
                await self._log_activity(bot_name, video_id, "failed", "GPT Image 2 didn't return a card — try again.")
                return {"status": "failed", "error": "The text fix didn't generate — tap Fix text to try again."}

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
                                        expected_panels=expected)
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

            upscaled = 0
            for idx, panel in enumerate(raw_panels):
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
                except Exception as e:
                    _logger.warning("Upscale failed S%d I%d: %s", panel["scene"], panel["image_index"], e)

            msg = f"Upscaled {upscaled}/{len(raw_panels)} panels"
            await self._log_activity(bot_name, video_id, "completed", msg)
            return {"status": "completed", "message": msg, "upscaled": upscaled}

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

            from orchestrator.pipeline_constants import Models
            from shared.clients.image_client import ImageClient
            from shared.clients.airtable_client import get_image_model_override

            model_override = get_image_model_override(self._pipeline.current_idea or {})
            if model_override and model_override not in ImageClient.VALID_SCENE_MODELS:
                model_override = ""

            use_reference = bool(self._pipeline.core_image_url) and model_override != Models.IMAGE_ZIMAGE

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
                if model_override == Models.IMAGE_ZIMAGE:
                    result = await self._pipeline.image_client.generate_scene_image_zimage(prompt, aspect_ratio="16:9")
                elif use_reference:
                    result = await self._pipeline.image_client.generate_scene_image(prompt, self._pipeline.core_image_url)
                else:
                    result_urls = await self._pipeline.image_client.generate_and_wait(prompt, aspect_ratio="16:9")
                    result = {"url": result_urls[0]} if result_urls else None

                if not result or not result.get("url"):
                    continue

                image_url = result["url"]
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
                        status, generation_method, panel_position, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7,
                        $8, $9, $10, $11, $12, $13,
                        $14, $15, $16, now(), now()
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
            return {"status": video.get("status"), "video_id": video_id, "variants_created": created}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}

    async def run_sound_prompts(self, video_id: str) -> dict:
        """Generate sound design prompts for a video."""
        await self._ensure_initialized()
        bot_name = "Sound Design Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
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
        await self._ensure_initialized()
        bot_name = "Sound Effects Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Generating sound effects")

            # Load system prompt overrides (tenant + per-video)
            await self._load_prompt_overrides(video)

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_sound_bot()

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
                await execute(
                    "UPDATE channel_profiles SET channel_identity = "
                    "COALESCE(channel_identity, '{}'::jsonb) || "
                    "jsonb_build_object('thumbnail_blueprint', $2::text) "
                    "WHERE tenant_id = $1", self.tenant_id, blueprint)
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
        res = None
        if seed:
            res = await client.generate_thumbnail_gpt2(
                gen_prompt + "\nUse the machine in the reference image as the "
                "thumbnail's subject — same vehicle, same configuration, no "
                "invented markings.",
                [seed], aspect_ratio=thumb_ar)
        if not (res or {}).get("url"):
            res = await client.generate_scene_image_gpt(gen_prompt, None, aspect_ratio=thumb_ar)
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

    async def run_thumbnail(self, video_id: str) -> dict:
        """Generate thumbnail for a video."""
        await self._ensure_initialized()
        bot_name = "Thumbnail Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

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
                if has_cast:
                    # CAST SHEET ONLY — the one authoritative seed image (identities +
                    # the modeled look). GPT Image 2 holds character identity best (live
                    # A/B); nano-banana-pro fallback so Regenerate never dead-ends.
                    res = await client.generate_thumbnail_gpt2(
                        prompt, [cast_sheet], aspect_ratio=thumb_ar)
                    if not (res or {}).get("url"):
                        res = await client.generate_with_reference(
                            prompt, [cast_sheet], aspect_ratio=thumb_ar)
                else:
                    # FACELESS — no cast sheet to seed from. Build from text: GPT Image 2
                    # text-to-image. The style signature in the prompt carries the look.
                    res = await client.generate_scene_image_gpt(
                        prompt, None, aspect_ratio=thumb_ar)
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
        """Static-documentary render (render_mode='static_docu') — one image
        per narration segment held with a Ken Burns pan over the voiceover,
        rendered with the existing Remotion composition. No animated clips.
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
            f"Rendered {result['scene_count']} held segments "
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

    async def run_render(self, video_id: str, orientation: str = "auto") -> dict:
        """Render final video."""
        await self._ensure_initialized()
        bot_name = "Render Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")

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

    async def run_upload(self, video_id: str) -> dict:
        """Generate SEO metadata and upload video to YouTube as unlisted draft."""
        await self._ensure_initialized()
        bot_name = "YouTube Upload Bot"

        try:
            video = await self._get_video(video_id)
            if not video:
                return {"status": "failed", "error": "Video not found"}

            current_status = video.get("status")
            await self._log_activity(bot_name, video_id, "started", "Uploading to YouTube")

            # Supabase-native, per-tenant path: if the creator has connected their OWN
            # YouTube channel, upload there using the stored SEO (no Airtable, no shared
            # token, no Power Doctrine defaults). Falls back to the legacy bot otherwise.
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

            self._load_idea_from_video(video_id)

            result = await self._pipeline.run_upload_bot()

            if result.get("error"):
                raise Exception(result["error"])

            new_status = result.get("new_status", "Uploaded (Draft)")

            # Update with YouTube URL if available
            video_url = result.get("video_url")
            if video_url:
                await execute(
                    "UPDATE videos SET youtube_url = $1 WHERE id = $2",
                    video_url, video_id,
                )

            await self._update_video_status(video_id, to_supabase(new_status))
            await self._log_transition(video_id, current_status, to_supabase(new_status), "api")
            await self._log_activity(bot_name, video_id, "completed", "Video uploaded to YouTube")

            return {"status": to_supabase(new_status), "video_id": video_id}

        except Exception as e:
            error_msg = str(e)
            await self._log_activity(bot_name, video_id, "failed", error_msg)
            return {"status": "failed", "error": error_msg}
