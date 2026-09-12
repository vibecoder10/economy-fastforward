"""The sourced, <=100-word machine path inside the existing script pipeline."""
from __future__ import annotations

import hashlib
import inspect
import json

CONTRACT = 'factual_100_v1'


def _object(value):
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def source_fingerprint(machine, package):
    return hashlib.sha256(json.dumps(
        {'machine': machine, 'package': package, 'contract': CONTRACT},
        sort_keys=True, ensure_ascii=False, default=str,
    ).encode()).hexdigest()


async def run_factual_script_hold(ex, video_id, video, roster, target_machine=None, save_target_script=False):
    from factual_machine_summary import generate_factual_machine_summary, review_existing_factual_summary
    from pipeline_executor import (
        _locked_roster_item_for_machine, _verified_source_package_for_machine,
        _verified_source_cache_key, fetch_all,
    )

    matched = _locked_roster_item_for_machine(roster, target_machine) if target_machine else None
    if target_machine and not matched:
        return {'status': 'failed', 'error': 'Machine is not in the locked roster'}
    selected = [(i, m) for i, m in enumerate(roster, 1) if not matched or m == matched]
    client = getattr(ex._pipeline, 'anthropic', None)
    if client is None:
        return {'status': 'failed', 'error': 'Anthropic client is required for sourced machine summaries'}
    rows = await fetch_all(
        'SELECT voice_id FROM scripts WHERE video_id=$1 AND tenant_id=$2 LIMIT 1', video_id, ex.tenant_id,
    )
    voice_id = (rows[0].get('voice_id') if rows else None) or '1SM7GgM6IMuvQlz2BwM3'
    failures = []
    results = []
    for scene, machine in selected:
        fresh = await ex._get_video(video_id)
        if not fresh:
            return {'status': 'failed', 'error': 'Video disappeared'}
        cap = fresh.get('max_spend')
        if cap is not None and float(fresh.get('total_cost') or 0) >= float(cap):
            return {'status': 'paused', 'message': 'Video budget reached; completed sections are saved.'}
        cancel = getattr(ex._pipeline, 'should_cancel', None)
        if callable(cancel):
            cancelled = cancel()
            if inspect.isawaitable(cancelled):
                cancelled = await cancelled
            if cancelled:
                return {'status': 'cancelled', 'message': 'Stopped; completed sections are saved.'}
        payload = _object(fresh.get('research_payload'))
        fresh_roster = [str(m) for m in roster]
        from pipeline_executor import _machine_documentary_hold_roster
        if _machine_documentary_hold_roster(fresh) != fresh_roster:
            return {'status': 'failed', 'error': 'Locked roster changed during script generation'}
        package = _verified_source_package_for_machine(payload, machine)
        fingerprint = source_fingerprint(machine, package)
        validation = _object(fresh.get('script_validation'))
        saved = (validation.get('machine_script_blocks') or {}).get(machine) or {}
        summary = None
        if (not target_machine and saved.get('passed') is True
                and saved.get('machine_script_contract') == CONTRACT
                and saved.get('source_fingerprint') == fingerprint
                and saved.get('scene') == scene and saved.get('paragraph')):
            if saved.get('review_context_version') == 2:
                results.append(saved)
                continue
            # Retain the exact saved prose when broader source review passes;
            # a review upgrade must not pay to rewrite every passed section.
            reviewed = await review_existing_factual_summary(machine, package, client, saved, allow_sentence_removal=True)
            if reviewed.get('passed'):
                summary = reviewed
        await ex._log_activity('Script Bot', video_id, 'running', f'Writing sourced section {scene}/{len(roster)}: {machine} (100-word maximum)')
        if summary is None:
            summary = await generate_factual_machine_summary(machine, package, client)
        block = {**summary, 'machine': machine, 'scene': scene,
                 'machine_script_contract': CONTRACT, 'source_fingerprint': fingerprint,
                 'research_source': 'verified_machine_sources', 'saved': False}
        snapshot = json.dumps(payload.get('unit_roster'), sort_keys=True, ensure_ascii=False)
        # Both success and failure remain reviewable with their exact citations.
        write = await ex._checkpoint_machine_script_preview(
            video_id, _verified_source_cache_key(machine), block, snapshot,
        )
        if ex._db_write_missed(write):
            return {'status': 'failed', 'error': 'Roster changed; summary checkpoint refused'}
        if not summary.get('passed'):
            failures.append(f"{machine}: " + '; '.join(summary.get('warnings') or ['factual review failed']))
            results.append(block)
            if target_machine:
                return {'status': 'completed', 'preview': block, 'video_id': video_id}
            continue
        if not target_machine or save_target_script:
            block = await ex._save_machine_script_block(
                video_id=video_id, video=fresh, roster=roster, script_block=block,
                title=video.get('video_title') or video.get('headline') or '', voice_id=voice_id,
                advance_status=False,
            )
            readback = await ex._get_video(video_id) or {}
            stored = (_object(readback.get('script_validation')).get('machine_script_blocks') or {}).get(machine) or {}
            if stored.get('paragraph') != summary['paragraph'] or stored.get('source_fingerprint') != fingerprint:
                return {'status': 'failed', 'error': f'Summary save could not be verified: {machine}'}
        results.append(block)
        if target_machine:
            return {'status': 'completed', 'video_id': video_id,
                    'script_block' if save_target_script else 'preview': block}
    if failures:
        return {'status': 'needs_review', 'error': ' | '.join(failures), 'units': results, 'video_id': video_id}
    final = await ex._get_video(video_id) or {}
    validation = _object(final.get('script_validation'))
    blocks = validation.get('machine_script_blocks') or {}
    payload = _object(final.get('research_payload'))
    complete = all(
        (blocks.get(machine) or {}).get('passed') is True
        and (blocks.get(machine) or {}).get('review_context_version') == 2
        and (blocks.get(machine) or {}).get('scene') == scene
        and (blocks.get(machine) or {}).get('source_fingerprint') == source_fingerprint(
            machine, _verified_source_package_for_machine(payload, machine))
        for scene, machine in enumerate(roster, 1)
    )
    if not complete:
        return {'status': 'failed', 'error': 'Saved script completeness could not be verified', 'video_id': video_id}
    # Partial old passes cannot release voice while another section failed its
    # current review. Only this all-roster readback advances the factual lane.
    new_status = ex._skip_disabled_next(final, 'ready_for_voice')
    from pipeline_executor import execute
    updated = await execute('UPDATE videos SET status=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3',
                            new_status, video_id, ex.tenant_id)
    if ex._db_write_missed(updated):
        return {'status': 'failed', 'error': 'Script completion status was not saved', 'video_id': video_id}
    await ex._log_transition(video_id, final.get('status'), new_status, 'api')
    return {'status': 'completed', 'video_id': video_id, 'units': results,
            'script': final.get('script'), 'new_status': new_status}
