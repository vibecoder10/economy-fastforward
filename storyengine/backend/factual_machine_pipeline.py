"""The sourced, approximately 100-word machine path inside the existing script pipeline."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import re
from dvsu_script_brief import script_editorial_ready

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


def _episode_outline(roster):
    return [{"scene": scene, "machine": str(machine)} for scene, machine in enumerate(roster or [], 1)]


def _current_briefing_paragraph(payload, machine, subject_context=''):
    """Return only this machine's saved research wording reference, never roster evidence."""
    from machine_research_summary import research_summary_ready
    from pipeline_executor import _research_card_for_machine, _verified_source_package_for_machine

    card = _research_card_for_machine(_object(payload), machine) or {}
    package = _verified_source_package_for_machine(_object(payload), machine)
    summary = card.get("research_summary") if isinstance(card, dict) else None
    if research_summary_ready(machine, package, summary, subject_context):
        return str(summary.get("paragraph") or "")
    return ""


def _expected_script_packet(machine, package, subject_context, outline, current_briefing):
    """Derive cache identity from exactly the packet writer/reviewer will consume."""
    if not isinstance(package, dict) or "claim_assessment" not in package:
        return None
    from factual_machine_summary import _eligible_candidates
    from research_claim_assessment import current_assessment
    from script_research_packet import ScriptPacketError, compile_script_packet

    assessment = current_assessment(machine, package, subject_context)
    if assessment is None:
        return None
    try:
        return compile_script_packet(
            machine, package, assessment,
            _eligible_candidates(machine, package, subject_context),
            subject_context=subject_context, episode_outline=outline,
            current_briefing=current_briefing,
            model=os.getenv("CLAUDE_OPUS_MODEL", "claude-opus-4-5-20251101"),
        )
    except ScriptPacketError:
        return None


def factual_script_readiness(video, roster) -> bool:
    """Return whether every factual block is approved for this exact subject and source set."""
    from factual_machine_summary import REVIEW_CONTEXT_VERSION
    from pipeline_executor import _verified_source_package_for_machine

    payload = _object(video.get('research_payload'))
    validation = _object(video.get('script_validation'))
    blocks = validation.get('machine_script_blocks') or {}
    subject_context = str(video.get('video_title') or video.get('headline') or '')
    outline = _episode_outline(roster)
    def current(machine, scene):
        package = _verified_source_package_for_machine(payload, machine)
        block = blocks.get(machine) or {}
        packet = _expected_script_packet(machine, package, subject_context, outline,
                                         _current_briefing_paragraph(payload, machine, subject_context))
        # Assessed blocks are compiler-versioned. A stale/invalid assessment
        # cannot quietly fall back to the old unassessed cache contract.
        if isinstance(package, dict) and "claim_assessment" in package:
            if not packet or not script_editorial_ready(block):
                return False
            if (block.get("compiler_version") != packet.get("compiler_version")
                    or block.get("packet_fingerprint") != packet.get("packet_fingerprint")):
                return False
        return (
            block.get('passed') is True and block.get('paragraph')
            and block.get('machine_script_contract') == CONTRACT
            and block.get('review_context_version') == REVIEW_CONTEXT_VERSION
            and block.get('subject_context') == subject_context and block.get('scene') == scene
            and block.get('source_fingerprint') == source_fingerprint(machine, package)
        )
    return bool(roster) and all(
        current(machine, scene)
        for scene, machine in enumerate(roster, 1)
    )


async def run_factual_script_hold(ex, video_id, video, roster, target_machine=None, save_target_script=False):
    from factual_machine_summary import (
        REVIEW_CONTEXT_VERSION,
        _eligible_candidates,
        generate_factual_machine_summary,
        review_existing_factual_summary,
    )
    from pipeline_executor import (
        _locked_roster_item_for_machine, _verified_source_package_for_machine,
        _verified_source_cache_key, execute, fetch_all,
    )

    matched = _locked_roster_item_for_machine(roster, target_machine) if target_machine else None
    if target_machine and not matched:
        return {'status': 'failed', 'error': 'Machine is not in the locked roster'}
    selected = [(i, m) for i, m in enumerate(roster, 1) if not matched or m == matched]
    client = getattr(ex._pipeline, 'anthropic', None)
    if client is None:
        return {'status': 'failed', 'error': 'Anthropic client is required for sourced machine summaries'}
    rows = await fetch_all(
        'SELECT scene, scene_text, voice_id, voice_over_url, voice_status FROM scripts '
        'WHERE video_id=$1 AND tenant_id=$2 ORDER BY scene', video_id, ex.tenant_id,
    )
    voice_id = (rows[0].get('voice_id') if rows else None) or '1SM7GgM6IMuvQlz2BwM3'
    voiced_scenes = {
        int(row.get('scene') or 0)
        for row in rows
        if row.get('voice_over_url') or row.get('voice_status') == 'Done'
    }
    subject_context = str(video.get('video_title') or video.get('headline') or '')
    outline = _episode_outline(roster)
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
        carrier_topic = bool(re.search(r'\baircraft\s+carriers?\b', subject_context, re.I))
        search_queries = [
            str(query).strip()
            for query in ((package or {}).get('search_queries') or [])
            if str(query).strip()
        ]
        carrier_scoped = bool(search_queries) and all(
            re.search(r'\baircraft\s+carriers?\b', query, re.I)
            for query in search_queries
        )
        eligible_urls = {
            str(row.get('source_url') or '').strip()
            for row in (_eligible_candidates(machine, package or {}, subject_context) or {}).values()
            if str(row.get('source_url') or '').strip()
        }
        refresh_sources = getattr(ex, '_run_unit_research_hold', None)
        if carrier_topic and len(eligible_urls) < 2 and not carrier_scoped and callable(refresh_sources):
            # Old factual packages predate subject-scoped naval queries. Remove
            # only this machine from a deep copy so the existing research hold
            # performs its normal guarded gather/checkpoint path while every
            # other machine's fetched evidence remains intact.
            refresh_payload = copy.deepcopy(payload)
            package_key = _verified_source_cache_key(machine)
            packages = refresh_payload.get('machine_raw_source_packages')
            if isinstance(packages, dict):
                packages.pop(package_key, None)
            await refresh_sources(
                video_id,
                subject_context,
                refresh_payload,
                fresh_roster,
                target_machine=machine,
            )
            fresh = await ex._get_video(video_id)
            if not fresh:
                return {'status': 'failed', 'error': 'Video disappeared after source refresh'}
            if _machine_documentary_hold_roster(fresh) != fresh_roster:
                return {'status': 'failed', 'error': 'Locked roster changed during source refresh'}
            payload = _object(fresh.get('research_payload'))
            package = _verified_source_package_for_machine(payload, machine)
        current_briefing = _current_briefing_paragraph(payload, machine, subject_context)
        script_packet = _expected_script_packet(machine, package, subject_context, outline, current_briefing)
        fingerprint = source_fingerprint(machine, package)
        validation = _object(fresh.get('script_validation'))
        saved = (validation.get('machine_script_blocks') or {}).get(machine) or {}
        summary = None
        prior_review = None
        saved_matches = (saved.get('machine_script_contract') == CONTRACT
                and saved.get('source_fingerprint') == fingerprint
                and saved.get('scene') == scene and saved.get('paragraph'))
        assessed_package = isinstance(package, dict) and 'claim_assessment' in package
        saved_packet_matches = (not assessed_package or (
            script_packet is not None
            and saved.get('compiler_version') == script_packet.get('compiler_version')
            and saved.get('packet_fingerprint') == script_packet.get('packet_fingerprint')
        ))
        saved_is_current = (saved_matches and saved.get('passed') is True
                and saved.get('review_context_version') == REVIEW_CONTEXT_VERSION
                and saved.get('subject_context') == subject_context and saved_packet_matches
                and (not assessed_package or script_editorial_ready(saved)))
        if saved_is_current and assessed_package:
            # Accepted compiled packets are immutable cache hits, including
            # intentionally short sections; do not spend a model call expanding them.
            results.append(saved)
            if target_machine:
                return {'status': 'completed', 'video_id': video_id,
                        'script_block' if save_target_script else 'preview': saved}
            continue
        if not target_machine and saved_is_current:
            if (len(str(saved.get('paragraph') or '').split()) >= 80
                    or saved.get('length_target_attempted') is True):
                results.append(saved)
                continue
            prior_review = saved
        preview = (payload.get('machine_script_previews') or {}).get(_verified_source_cache_key(machine)) or {}
        preview_matches = (preview.get('machine_script_contract') == CONTRACT
                and preview.get('source_fingerprint') == fingerprint
                and preview.get('scene') == scene and preview.get('paragraph'))
        preview_packet_matches = (not assessed_package or (
            script_packet is not None
            and preview.get('compiler_version') == script_packet.get('compiler_version')
            and preview.get('packet_fingerprint') == script_packet.get('packet_fingerprint')
        ))
        preview_is_current = (preview_matches and preview.get('passed') is True
            and preview.get('review_context_version') == REVIEW_CONTEXT_VERSION
            and preview.get('subject_context') == subject_context and preview_packet_matches
            and (not assessed_package or script_editorial_ready(preview)))
        # A restarted worker consumes its last exact persisted draft, including
        # a rejected one, instead of inventing a new story and losing the repair.
        if assessed_package:
            # A matching preview was already generated and refereed but did
            # not reach the durable section save. Promote it without another
            # writer/referee call. Older packets are prose-only repair input.
            if preview_is_current:
                cached = None
                prior_review = preview
            elif preview_matches and preview_packet_matches:
                # A newer rejected checkpoint is the best bounded repair
                # input. Keep its exact review issues rather than replacing
                # them with an older saved section's prose.
                if preview.get('passed') is True:
                    prior_review = {**preview, 'passed': False,
                                    'warnings': list(preview.get('warnings') or []) +
                                    ['Prior assessed draft requires current factual review.']}
                else:
                    prior_review = preview
                cached = None
            elif saved_matches and saved_packet_matches:
                if saved.get('passed') is True:
                    prior_review = {**saved, 'passed': False,
                                    'warnings': list(saved.get('warnings') or []) +
                                    ['Prior assessed draft requires current factual review.']}
                else:
                    prior_review = saved
                cached = None
            elif saved_matches or preview_matches:
                old = preview if preview_matches else saved
                prior_review = {**old, 'passed': False,
                                'warnings': list(old.get('warnings') or []) +
                                ['Prior assessed draft does not match the current script packet.']}
                cached = None
            else:
                cached = None
        elif prior_review is not None:
            cached = saved
        elif preview_matches:
            cached = preview
        elif saved_matches:
            cached = saved
        else:
            cached = None
        if cached and prior_review is None:
            prior_review = await review_existing_factual_summary(
                machine, package, client, cached, allow_sentence_removal=True,
                subject_context=subject_context, script_packet=script_packet,
            )
        length_attempted_for_context = bool(
            cached
            and cached.get('length_target_attempted') is True
            and cached.get('subject_context') == subject_context
        )
        if assessed_package and preview_is_current:
            summary = prior_review
        elif prior_review and prior_review.get('passed'):
            if (len(str(prior_review.get('paragraph') or '').split()) >= 80
                    or length_attempted_for_context):
                summary = prior_review
        await ex._log_activity('Script Bot', video_id, 'running', f'Writing sourced section {scene}/{len(roster)}: {machine} (about 100 words, up to 110)')
        if summary is None:
            summary = await generate_factual_machine_summary(
                machine, package, client, subject_context=subject_context,
                previous_summary=prior_review,
                episode_outline=outline, current_briefing=current_briefing,
                script_packet=script_packet,
            )
            summary = {**summary, 'length_target_attempted': True}
        block = {**summary, 'machine': machine, 'scene': scene,
                 'machine_script_contract': CONTRACT, 'source_fingerprint': fingerprint,
                 'research_source': 'verified_machine_sources', 'saved': False,
                 'subject_context': subject_context}
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
            unchanged_saved_prose = (
                saved_matches
                and ' '.join(str(saved.get('paragraph') or '').split())
                == ' '.join(str(block.get('paragraph') or '').split())
            )
            if (unchanged_saved_prose and scene in voiced_scenes
                    and any(int(row.get("scene") or 0) == scene
                            and str(row.get("scene_text") or "") == summary["paragraph"] for row in rows)):
                # The existing save helper correctly invalidates narration when
                # prose changes. A review-version/title-context upgrade with the
                # exact same prose only changes block metadata, so persist that
                # metadata directly and retain the already-rendered narration.
                updated_validation = dict(validation)
                updated_blocks = dict(updated_validation.get('machine_script_blocks') or {})
                block = {**block, 'saved': True}
                updated_blocks[machine] = block
                updated_validation['machine_script_blocks'] = updated_blocks
                updated = await execute(
                    'UPDATE videos SET script_validation = $1, updated_at=now() '
                    'WHERE id=$2 AND tenant_id=$3',
                    json.dumps(updated_validation), video_id, ex.tenant_id,
                )
                if ex._db_write_missed(updated):
                    return {'status': 'failed', 'error': f'Summary metadata save failed: {machine}'}
            else:
                block = await ex._save_machine_script_block(
                    video_id=video_id, video=fresh, roster=roster, script_block=block,
                    title=video.get('video_title') or video.get('headline') or '', voice_id=voice_id,
                    advance_status=False,
                )
            readback = await ex._get_video(video_id) or {}
            stored = (_object(readback.get('script_validation')).get('machine_script_blocks') or {}).get(machine) or {}
            if (stored.get('paragraph') != summary['paragraph'] or stored.get('source_fingerprint') != fingerprint
                    or (assessed_package and stored.get('packet_fingerprint') != script_packet.get('packet_fingerprint'))):
                return {'status': 'failed', 'error': f'Summary save could not be verified: {machine}'}
        results.append(block)
        if target_machine:
            return {'status': 'completed', 'video_id': video_id,
                    'script_block' if save_target_script else 'preview': block}
    if failures:
        return {'status': 'needs_review', 'error': ' | '.join(failures), 'units': results, 'video_id': video_id}
    final = await ex._get_video(video_id) or {}
    if not factual_script_readiness(final, roster):
        return {'status': 'failed', 'error': 'Saved script completeness could not be verified', 'video_id': video_id}
    # Partial old passes cannot release voice while another section failed its
    # current review. Only this all-roster readback advances the factual lane.
    new_status = ex._skip_disabled_next(final, 'ready_for_voice')
    updated = await execute('UPDATE videos SET status=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3',
                            new_status, video_id, ex.tenant_id)
    if ex._db_write_missed(updated):
        return {'status': 'failed', 'error': 'Script completion status was not saved', 'video_id': video_id}
    await ex._log_transition(video_id, final.get('status'), new_status, 'api')
    return {'status': 'completed', 'video_id': video_id, 'units': results,
            'script': final.get('script'), 'new_status': new_status}
