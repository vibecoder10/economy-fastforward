"""Compact DVSU research coverage and append-only, one-pass evidence recovery."""
from __future__ import annotations

import copy


RECOVERY_VERSION = 1
_NARRATIVE_FIELDS = {'intended_role', 'design', 'actual_use', 'outcome'}


class RecoveryStopped(RuntimeError):
    """A guarded recovery phase stopped before another provider call."""


def _missing_fields(machine, package, title):
    return [field for field in package_brief(machine, package, title).get('missing_fields', [])
            if field in _NARRATIVE_FIELDS]


def _recovery(package):
    assessment = package.get('claim_assessment') if isinstance(package, dict) else None
    return assessment.get('dvsu_recovery') if isinstance(assessment, dict) else None


def _with_recovery(package, source_fingerprint, stage, missing_fields):
    """Keep recovery state inside the assessment, outside its source fingerprint."""
    result = copy.deepcopy(package)
    assessment = result.get('claim_assessment')
    if isinstance(assessment, dict):
        assessment['dvsu_recovery'] = {'version': RECOVERY_VERSION, 'source_fingerprint': source_fingerprint,
                                       'stage': stage, 'missing_fields': list(missing_fields)}
    return result


def _stopped(package, source_fingerprint, stage, missing_fields, warning):
    result = _with_recovery(package, source_fingerprint, stage, missing_fields)
    assessment = result.get('claim_assessment')
    if isinstance(assessment, dict):
        assessment.setdefault('dvsu_recovery', {}).update({'warning': warning})
    return result


async def _call(callback, *args):
    if callback is None:
        return True
    value = callback(*args)
    if hasattr(value, '__await__'):
        value = await value
    return value


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
        row['locator'] = row['excerpt_id'] + '; ' + str(row.get('locator') or row.get('source_url') or '')
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


async def supplement_missing_research(ex, title, machine, payload, package, cache_key, *,
                                      assess=None, checkpoint=None, guard=None):
    """Called only inside an authorized research run; never by script generation."""
    brief = package_brief(machine, package, title)
    fields = [f for f in brief.get('missing_fields', []) if f in _NARRATIVE_FIELDS]
    known = payload.get('_dvsu_known_sources') or {}
    explicit_urls = known.get('urls', []) if known.get('machine') == machine else []
    if not fields and not explicit_urls:
        return package
    from research_claim_assessment import assessment_fingerprint, current_assessment
    fingerprint = assessment_fingerprint(machine, package, title)
    recovery = _recovery(package) or {}
    if not explicit_urls and recovery.get('source_fingerprint') == fingerprint and recovery.get('stage') in {
            'discovery_started', 'discovery_completed'}:
        # Preserve the exact completed/uncertain receipt. Its stage is the
        # durable no-repeat boundary for unchanged evidence.
        return package
    if not await _call(guard, 'before_recapture'):
        raise RecoveryStopped('Research recovery guard stopped before source recapture.')
    from factual_source_recapture import recapture_sources
    urls = list(dict.fromkeys(explicit_urls + [s.get('url') or s.get('source_url')
        for s in package.get('sources', []) if s.get('url') or s.get('source_url')]))[:6]
    if urls:
        captured = await recapture_sources(ex, title, machine, urls)
        merged, _, added = merge_research_sources(package, captured)
        if added:
            merged['source_recapture'] = {'urls': urls, 'added_excerpt_count': added,
                                         'errors': captured.get('errors', []), 'paid_search_calls': 0}
            if not await _call(checkpoint, merged, 'recapture_captured'):
                raise RecoveryStopped('Research recovery checkpoint was refused after recapture.')
            if assess is not None:
                assessed = await _call(assess, merged, 'recapture_assessment')
                if isinstance(assessed, dict):
                    merged = assessed
            if explicit_urls and recovery.get('stage') in {'discovery_started', 'discovery_completed'}:
                # Refreshing original citations must not reopen an exhausted
                # or uncertain paid-discovery attempt for the new evidence.
                merged = _with_recovery(merged, assessment_fingerprint(machine, merged, title),
                                        recovery['stage'], _missing_fields(machine, merged, title))
            if not await _call(checkpoint, merged, 'recapture_assessment'):
                raise RecoveryStopped('Research recovery assessment checkpoint was refused.')
            if assess is not None and current_assessment(machine, merged, title) is None:
                raise RecoveryStopped('Narrative assessment is invalid after recapture.')
            package = merged
            fields = _missing_fields(machine, merged, title)
            if not fields:
                return merged
        if explicit_urls:
            # An explicit citation repair never silently spends on rediscovery.
            # Bookkeeping cannot change the source fingerprint after assessment.
            merged.setdefault('claim_assessment', {})['dvsu_research_last_gap'] = {
                'missing_fields': fields, 'added_excerpt_count': added,
                'errors': captured.get('errors', []), 'paid_search_calls': 0}
            return merged
    # A discovery request may have reached a provider while its response was
    # lost. Never repeat it on unchanged evidence; surface an honest stop.
    # Recapture may have changed immutable source evidence, so its new
    # fingerprint is the restart boundary for the one discovery request.
    fingerprint = assessment_fingerprint(machine, package, title)
    marked = _with_recovery(package, fingerprint, 'discovery_started', fields)
    if not await _call(checkpoint, marked, 'discovery_started'):
        raise RecoveryStopped('Research recovery checkpoint was refused before targeted discovery.')
    if not await _call(guard, 'before_discovery'):
        raise RecoveryStopped('Research recovery guard stopped before targeted discovery.')
    gather_payload = copy.deepcopy(payload)
    gather_payload.setdefault('machine_raw_source_packages', {}).pop(cache_key, None)
    gather_payload['_dvsu_source_recovery'] = {
        'machine': machine, 'missing_fields': fields,
        'attempted_urls': [s.get('url') or s.get('source_url') for s in package.get('sources', [])
                           if s.get('url') or s.get('source_url')],
    }
    gather_payload['_dvsu_source_recovery']['missing_fields'] = fields
    supplement = await ex._gather_verified_machine_source_package(title, machine, gather_payload)
    merged, discoveries, added = merge_research_sources(marked, supplement)
    if not added:
        # Preserve the unchanged archive, but attach discovery receipts so the
        # normal research checkpoint/billing code can account for this request.
        if discoveries:
            merged['source_discovery_requests'] = list(merged.get('source_discovery_requests') or []) + discoveries
        merged['dvsu_research_last_gap'] = {'missing_fields': fields, 'added_excerpt_count': 0}
    if not await _call(checkpoint, merged, 'discovery_captured'):
        raise RecoveryStopped('Research recovery checkpoint was refused after targeted discovery.')
    if assess is not None:
        assessed = await _call(assess, merged, 'discovery_assessment')
        if isinstance(assessed, dict):
            merged = assessed
    # A fresh valid assessment owns the new source fingerprint; retain the
    # completed recovery receipt there for no-repeat restart behavior.
    final_fingerprint = assessment_fingerprint(machine, merged, title)
    merged = _with_recovery(merged, final_fingerprint, 'discovery_completed', _missing_fields(machine, merged, title))
    if not await _call(checkpoint, merged, 'discovery_completed'):
        raise RecoveryStopped('Research recovery final checkpoint was refused.')
    if assess is not None and current_assessment(machine, merged, title) is None:
        raise RecoveryStopped('Narrative assessment is invalid after targeted discovery.')
    return merged
