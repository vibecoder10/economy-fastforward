"""Compact DVSU research coverage and append-only, one-pass evidence recovery."""
from __future__ import annotations

import copy


def package_brief(machine, package, subject_context=''):
    from factual_machine_summary import _eligible_candidates, _model_name
    from research_claim_assessment import current_assessment
    from script_research_packet import compile_script_packet, ScriptPacketError
    from dvsu_script_brief import build_dvsu_brief
    assessment = current_assessment(machine, package, subject_context)
    if assessment is None:
        return {'ready': False, 'missing_fields': ['current_claim_assessment']}
    try:
        packet = compile_script_packet(machine, package, assessment,
            _eligible_candidates(machine, package, subject_context),
            subject_context=subject_context, model=_model_name())
        return build_dvsu_brief(packet)
    except ScriptPacketError as exc:
        return {'ready': False, 'missing_fields': ['valid_script_packet'], 'detail': str(exc)}


def package_brief_warnings(machine, package, subject_context=''):
    from dvsu_script_brief import brief_warnings
    return brief_warnings(package_brief(machine, package, subject_context))


def merge_research_sources(original, supplement):
    """Keep old rows byte-equivalent; append new quotes with unique source IDs."""
    merged = copy.deepcopy(original)
    sources = merged.setdefault('sources', [])
    excerpts = merged.setdefault('candidate_excerpts', [])
    used_sources = {str(s.get('source_id')) for s in sources}
    used_excerpts = {str(e.get('excerpt_id')) for e in excerpts}
    seen = {(e.get('source_url'), e.get('text')) for e in excerpts}
    source_map = {}
    added = 0
    for source in supplement.get('sources') or []:
        source = copy.deepcopy(source)
        old_id = str(source.get('source_id') or '')
        n = 1
        while f'DVSU{n}' in used_sources:
            n += 1
        new_id = f'DVSU{n}'
        source_map[old_id] = new_id
        used_sources.add(new_id)
        source['source_id'] = new_id
        sources.append(source)
    for row in supplement.get('candidate_excerpts') or []:
        if (row.get('source_url'), row.get('text')) in seen:
            continue
        row = copy.deepcopy(row)
        source_id = source_map.get(str(row.get('source_id') or ''))
        if not source_id:
            continue
        n = 1
        while f'{source_id}-E{n}' in used_excerpts:
            n += 1
        old_excerpt = row.get('excerpt_id')
        row['source_id'] = source_id
        row['excerpt_id'] = f'{source_id}-E{n}'
        row['locator'] = row['excerpt_id']
        row['original_excerpt_id'] = old_excerpt
        excerpts.append(row)
        used_excerpts.add(row['excerpt_id'])
        seen.add((row.get('source_url'), row.get('text')))
        added += 1
    # Source discovery receipts must survive even an empty search so billing
    # remains traceable. The original assessment stays current if nothing changed.
    discoveries = list(supplement.get('source_discovery_requests') or [])
    if not discoveries and supplement.get('source_discovery'):
        discoveries = [supplement['source_discovery']]
    if not added:
        return copy.deepcopy(original), discoveries, 0
    previous = merged.pop('claim_assessment', None)
    if previous:
        merged.setdefault('prior_claim_assessments', []).append(previous)
    merged['search_queries'] = list(dict.fromkeys(list(merged.get('search_queries') or []) +
                                                 list(supplement.get('search_queries') or [])))
    merged['source_discovery_requests'] = list(merged.get('source_discovery_requests') or []) + discoveries
    merged['dvsu_research_supplements'] = list(merged.get('dvsu_research_supplements') or []) + [
        {'added_excerpt_count': added, 'new_source_ids': sorted(source_map.values())}]
    return merged, discoveries, added


async def supplement_missing_research(ex, title, machine, payload, package, cache_key):
    """Called only inside an authorized research run; never by script generation."""
    brief = package_brief(machine, package, title)
    fields = [f for f in brief.get('missing_fields', [])
              if f in {'intended_role', 'design', 'actual_use', 'outcome'}]
    if not fields:
        return package
    gather_payload = copy.deepcopy(payload)
    gather_payload.setdefault('machine_raw_source_packages', {}).pop(cache_key, None)
    gather_payload['_dvsu_source_recovery'] = {
        'machine': machine, 'missing_fields': fields,
        'attempted_urls': [s.get('url') or s.get('source_url') for s in package.get('sources', [])
                           if s.get('url') or s.get('source_url')],
    }
    supplement = await ex._gather_verified_machine_source_package(title, machine, gather_payload)
    merged, discoveries, added = merge_research_sources(package, supplement)
    if not added:
        # Preserve the unchanged archive, but attach discovery receipts so the
        # normal research checkpoint/billing code can account for this request.
        if discoveries:
            merged['source_discovery_requests'] = list(merged.get('source_discovery_requests') or []) + discoveries
        merged['dvsu_research_last_gap'] = {'missing_fields': fields, 'added_excerpt_count': 0}
    return merged
