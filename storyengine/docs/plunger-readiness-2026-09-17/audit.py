#!/usr/bin/env python3
"""Offline scoped audit and real readiness harness for the Plunger preview."""
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from dvsu_research_handoff import package_brief
from research_claim_assessment import current_assessment


def load(path):
    """Accept one JSON document first, then se_db JSONL with row headers."""
    text = Path(path).read_text().strip()
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict) and set(loaded) == {"snapshot"} and isinstance(loaded["snapshot"], str):
            return json.loads(loaded["snapshot"])
        return loaded
    except json.JSONDecodeError:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line or re.fullmatch(r"--\s+\d+\s+rows?", line):
                continue
            rows.append(json.loads(line))
        if len(rows) != 1:
            raise ValueError(f"expected one se_dbjsonl row, found {len(rows)}")
        return rows[0]


def payload(video):
    value = video.get("research_payload") or {}
    return json.loads(value) if isinstance(value, str) else value


def stable_if_present(before, after, field, errors, unavailable):
    if field not in before or field not in after:
        unavailable.append(field)
    elif before[field] != after[field]:
        errors.append(f"production field changed: {field}")


def preview_summary(preview):
    paragraph = str(preview.get("paragraph") or "")
    words = preview.get("word_count")
    return {
        "word_count": words if words is not None else len(re.findall(r"\S+", paragraph)),
        "passed": preview.get("passed"),
        "factual_passed": preview.get("factual_passed"),
        "support_audit": preview.get("support_audit"),
        "editorial_review": preview.get("editorial_review"),
    }


def audit(before_path, after_path, output_path):
    before, after = load(before_path), load(after_path)
    bp, ap = payload(before), payload(after)
    errors, unavailable = [], []
    # An omitted snapshot column cannot prove an unchanged production field.
    for field in ("script", "script_validation", "status", "scripts", "script_hash", "validation_hash"):
        stable_if_present(before, after, field, errors, unavailable)
    if bp.get("unit_roster") != ap.get("unit_roster"):
        errors.append("unit roster changed")
    bpk, apk = bp.get("machine_raw_source_packages") or {}, ap.get("machine_raw_source_packages") or {}
    if set(bpk) != set(apk):
        errors.append("source package keys changed")
    for key, old in bpk.items():
        new = apk.get(key)
        if key != "SS2" and new != old:
            errors.append(f"non-SS2 package changed: {key}")
        if key == "SS2" and (not isinstance(new, dict) or new.get("sources", [])[:len(old.get("sources", []))] != old.get("sources", []) or new.get("candidate_excerpts", [])[:len(old.get("candidate_excerpts", []))] != old.get("candidate_excerpts", [])):
            errors.append("SS2 original evidence is not an exact append-only prefix")
    bpre, apre = bp.get("machine_script_previews") or {}, ap.get("machine_script_previews") or {}
    for key, old in bpre.items():
        if key != "SS2" and apre.get(key) != old:
            errors.append(f"non-SS2 preview changed: {key}")
    title = str(after.get("video_title") or after.get("headline") or ap.get("headline") or "")
    readiness = []
    for key, package in apk.items():
        machine = str(package.get("machine") or "")
        brief = package_brief(machine, package, title)
        claims = (package.get("claim_assessment") or {}).get("claims") or []
        roles = sum("narrative_roles" in claim for claim in claims if isinstance(claim, dict))
        missing = brief.get("missing_fields", [])
        current = current_assessment(machine, package, title)
        preparation_candidate = bool(current and missing and set(missing) <= {"intended_role", "design", "actual_use", "outcome"})
        readiness.append({"key": key, "machine": machine, "ready": bool(brief.get("ready")), "preparation_candidate": preparation_candidate, "missing_fields": missing, "legacy_explicit_role_claims": roles})
    ss2 = apre.get("SS2") or {}
    report = {
        "before": str(before_path), "after": str(after_path), "unchanged": not errors,
        "errors": errors, "unavailable_fields": unavailable,
        "title": title, "title_source": "video_title" if after.get("video_title") else ("row.headline" if after.get("headline") else "research_payload.headline"),
        "packages": readiness, "ready_count": sum(row["ready"] for row in readiness),
        "preparation_candidate_count": sum(row["preparation_candidate"] for row in readiness),
        "preparation_candidate_note": "Package-only preparation candidates; API base gates are untested by this audit.",
        "ss2_preview": preview_summary(ss2),
    }
    Path(output_path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    if errors:
        raise SystemExit("; ".join(errors))


async def readiness_check(snapshot_path, output_path):
    """Use real source/card gate logic while mocking only snapshot DB plumbing."""
    import pipeline_executor as pe
    video = load(snapshot_path)
    rp = payload(video)
    cards = rp.get("unit_research_cards") if isinstance(rp, dict) else None
    packages = rp.get("machine_raw_source_packages") if isinstance(rp, dict) else None
    if not isinstance(cards, list):
        report = {"mode": "offline_real_readiness", "status": "blocked", "snapshot": str(snapshot_path), "gap": "snapshot lacks unit_research_cards; cannot run real executor readiness checks", "package_count": len(packages) if isinstance(packages, dict) else 0}
        Path(output_path).write_text(json.dumps(report, indent=2) + "\n")
        return
    if not isinstance(packages, dict):
        report = {"mode": "offline_real_readiness", "status": "blocked", "snapshot": str(snapshot_path), "gap": "snapshot lacks machine_raw_source_packages; cannot run real source checks", "card_count": len(cards)}
        Path(output_path).write_text(json.dumps(report, indent=2) + "\n")
        return
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = str(video.get("tenant_id") or "offline-snapshot")
    async def no_db_init(): return None
    async def snapshot_video(_video_id): return video
    async def snapshot_cards(_video_id, current_rp, _roster, target_machine=None): return current_rp
    async def no_db_validation(*_args, **_kwargs): return None
    executor._ensure_initialized = no_db_init
    executor._get_video = snapshot_video
    executor._load_machine_research_cards = snapshot_cards
    executor._update_machine_research_validation = no_db_validation
    original_enrich = pe.enrich_research_payload_readiness
    async def no_db_enrich(_tenant_id, _video_id, current_rp): return current_rp
    pe.enrich_research_payload_readiness = no_db_enrich
    try:
        roster = pe._machine_documentary_hold_roster(video)
        results = [await executor.check_machine_script_preview_readiness(str(video.get("id") or ""), machine) for machine in roster]
    finally:
        pe.enrich_research_payload_readiness = original_enrich
    report = {
        "mode": "offline_real_readiness", "status": "completed", "snapshot": str(snapshot_path),
        "mocked": ["DB video/card loading", "readiness enrichment", "readiness checkpoint persistence"],
        "real": ["locked roster matching", "saved card selection", "verified source-package checks", "factual package brief checks"],
        "provider_calls": 0, "package_count": len(packages), "card_count": len(cards),
        "results": results, "ready_count": sum(bool(result.get("ready")) for result in results),
        "preparable_count": sum(bool(result.get("preparable")) for result in results),
    }
    Path(output_path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--readiness-check":
        asyncio.run(readiness_check(sys.argv[2], sys.argv[3]))
    elif len(sys.argv) == 4:
        audit(*sys.argv[1:])
    else:
        raise SystemExit("Usage: audit.py BEFORE.json AFTER.json audit.json | audit.py --readiness-check SNAPSHOT.json readiness.json")
