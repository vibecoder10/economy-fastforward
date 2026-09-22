"""Factual (``factual_100_v1``) research-readiness helpers.

This module used to also hold ``run_factual_script_hold`` - the write+referee
machine-paragraph writer. That writer was deleted 2026-09-21 along with the
other two legacy script paths; the only script writer is now
``dvsu_script_v2.py``. What remains here is the research-side contract that
``pipeline_executor.run_research`` and ``machine_research_summary`` still
read: the per-machine evidence fingerprint and the "every locked machine has
a current saved research briefing" gate.
"""
from __future__ import annotations

import hashlib
import json

CONTRACT = 'factual_100_v1'


def _object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def source_fingerprint(machine, package):
    return hashlib.sha256(json.dumps(
        {'machine': machine, 'package': package, 'contract': CONTRACT},
        sort_keys=True, ensure_ascii=False, default=str,
    ).encode()).hexdigest()


def current_research_briefings(payload, roster, subject_context=''):
    """Return current saved factual research briefings in locked roster order."""
    from machine_research_summary import research_summary_ready
    from pipeline_executor import _research_card_for_machine, _verified_source_package_for_machine

    payload = _object(payload)
    briefings = []
    for scene, machine in enumerate(roster or [], 1):
        card = _research_card_for_machine(payload, machine) or {}
        package = _verified_source_package_for_machine(payload, machine)
        summary = card.get('research_summary') if isinstance(card, dict) else None
        if not research_summary_ready(machine, package, summary, subject_context):
            continue
        briefings.append({
            'machine': machine,
            'scene': scene,
            'paragraph': summary['paragraph'],
            'claim_map': summary['claim_map'],
            'sources': summary['sources'],
            'claim_assessment': summary['claim_assessment'],
        })
    return briefings


def factual_research_readiness(payload, roster, subject_context='') -> bool:
    """Require one current saved factual research briefing for every locked unit."""
    from dvsu_research_handoff import package_brief_warnings
    from pipeline_executor import _verified_source_package_for_machine
    return (bool(roster) and len(current_research_briefings(payload, roster, subject_context)) == len(roster)
            and all(not package_brief_warnings(machine, _verified_source_package_for_machine(_object(payload), machine),
                                               subject_context) for machine in roster))
