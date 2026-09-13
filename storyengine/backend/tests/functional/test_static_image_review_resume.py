"""Saved factual images cannot bypass updated machine-configuration QA."""
import json
import importlib
from unittest.mock import AsyncMock

import pytest
import static_docu as sd
import actions
from static_image_review import image_review_stamp, image_review_current, factual_image_review_required

FACTS = {"role": "split deck aircraft carrier", "years": "1918-1923"}
URL = "https://storage.example/render.png"
REF = "https://storage.example/reference.jpg"


def test_approval_is_bound_to_pixels_reference_machine_and_facts():
    stamp = image_review_stamp("HMS Vindictive", REF, FACTS, URL)
    assert image_review_current(stamp, URL, stamp)
    for machine, ref, facts, url in [
        ("HMS Hawkins", REF, FACTS, URL),
        ("HMS Vindictive", REF + "?revision=2", FACTS, URL),
        ("HMS Vindictive", REF, {"role": "cruiser"}, URL),
        ("HMS Vindictive", REF, FACTS, URL + "?revision=2"),
    ]:
        assert not image_review_current(stamp, url, image_review_stamp(machine, ref, facts, url))
    assert not image_review_current({"image_review_version": 0}, URL)
    assert not image_review_current("invalid-json", URL)


@pytest.mark.asyncio
async def test_saved_wrong_configuration_is_parked_and_cannot_be_reused(monkeypatch):
    primary = AsyncMock(return_value=False)
    arbiter = AsyncMock(return_value=False)
    db = AsyncMock()
    monkeypatch.setattr(sd, "_render_matches_reference", primary)
    monkeypatch.setattr(sd, "_arbiter_confirms_render", arbiter)
    monkeypatch.setattr(sd, "execute", db)
    cap = {"view_role": "three_quarter"}
    assert not await sd._revalidate_saved_photo_view(
        {"id": "saved", "image_url": URL}, cap, "tenant", "HMS Vindictive", [], REF, FACTS)
    assert primary.await_args.kwargs["facts"] == FACTS
    assert arbiter.await_args.kwargs["facts"] == FACTS
    sql, row_id, retained_url, _ = db.await_args.args
    assert "status='qa_rejected'" in sql and "image_url=NULL" in sql
    assert row_id == "saved" and retained_url == URL
    assert "image_review_version" not in cap


@pytest.mark.asyncio
async def test_good_saved_image_reviewed_once_then_reused_without_generation(monkeypatch):
    primary = AsyncMock(return_value=True)
    arbiter = AsyncMock(return_value=False)
    db = AsyncMock()
    monkeypatch.setattr(sd, "_render_matches_reference", primary)
    monkeypatch.setattr(sd, "_arbiter_confirms_render", arbiter)
    monkeypatch.setattr(sd, "execute", db)
    cap = {"view_role": "side_profile", "specs": ["Beam 65 ft"]}
    args = ({"id": "saved", "image_url": URL}, cap, "tenant", "HMS Vindictive", [], REF, FACTS)
    assert await sd._revalidate_saved_photo_view(*args)
    assert await sd._revalidate_saved_photo_view(*args)
    primary.assert_awaited_once()
    arbiter.assert_not_awaited()
    db.assert_awaited_once()
    assert json.loads(db.await_args.args[2])["specs"] == ["Beam 65 ft"]
    assert "DELETE" not in db.await_args.args[0]


@pytest.mark.asyncio
async def test_missing_reference_cannot_approve_saved_pixels(monkeypatch):
    primary, db = AsyncMock(), AsyncMock()
    monkeypatch.setattr(sd, "_render_matches_reference", primary)
    monkeypatch.setattr(sd, "execute", db)
    assert not await sd._revalidate_saved_photo_view(
        {"id": "saved", "image_url": URL}, {}, "tenant", "HMS Vindictive", [], None, FACTS)
    primary.assert_not_awaited()
    assert "qa_rejected" in db.await_args.args[0]


@pytest.mark.asyncio
async def test_downstream_resume_rewinds_stale_factual_images_but_keeps_completed_video(monkeypatch):
    video = {"id": "v", "render_mode": "static_docu", "status": "ready_for_render",
             "research_payload": {"machine_script_contract": "factual_100_v1"}}
    db = AsyncMock(return_value=[{"image_url": URL, "caption": {"view_role": "side_profile"}}])
    monkeypatch.setattr(actions, "fetch_all", db)
    assert factual_image_review_required(video)
    assert await actions._factual_image_recheck_needed(video, "tenant")
    db.return_value[0]["caption"] = image_review_stamp("HMS Vindictive", REF, FACTS, URL)
    assert not await actions._factual_image_recheck_needed(video, "tenant")
    video["status"] = "rendered"
    db.reset_mock()
    assert not await actions._factual_image_recheck_needed(video, "tenant")
    db.assert_not_awaited()
    video["status"] = "ready_for_render"
    video["research_payload"] = {}
    assert not await actions._factual_image_recheck_needed(video, "tenant")
    db.assert_not_awaited()


def _use_factual_video(monkeypatch, env):
    import pipeline_executor as pe
    old_fetch = sd.fetch_one
    async def fetch(query, *args):
        row = await old_fetch(query, *args)
        if 'FROM videos' in query:
            row.update(render_mode='static_docu', research_payload={'machine_script_contract': 'factual_100_v1'})
        return row
    monkeypatch.setattr(sd, 'fetch_one', fetch)
    monkeypatch.setattr(pe, '_machine_documentary_hold_roster_entries', lambda _v: [
        {'name': 'HMS Argus', 'aliases': ['I49 HMS Argus'], 'facts': {'role': 'aircraft carrier'}}])
    planner = AsyncMock(side_effect=AssertionError('factual identity must not use model planning'))
    monkeypatch.setattr(sd, '_scene_subjects', planner)
    monkeypatch.setattr(sd, '_machine_research_cards_by_scene', AsyncMock(side_effect=AssertionError('legacy cards not required')))
    return planner


@pytest.mark.asyncio
async def test_factual_image_stage_needs_no_optional_specs_or_new_identity_model(monkeypatch):
    from test_static_docu_qa_park import _pipeline_env
    env = _pipeline_env(monkeypatch, verdicts=[True], gen_urls=[URL], docu_module=sd, image_client_module=importlib.import_module("shared.clients.image_client"))
    planner = _use_factual_video(monkeypatch, env)
    updates = []
    old_db = sd.execute
    async def execute(query, *args):
        if "image_model='gpt-image-2', caption=$4" in query:
            updates.append(json.loads(args[3]))
        return await old_db(query, *args)
    monkeypatch.setattr(sd, 'execute', execute)
    result = await sd.generate_static_images_for_video(env['video_id'], env['tenant_id'])
    assert result['status'] == 'completed'
    planner.assert_not_awaited()
    assert len(env['gen_prompts']) == 1
    assert updates[0]['title'] == 'HMS Argus'
    assert updates[0]['sub'] == '' and updates[0]['specs'] == []
    assert image_review_current(updates[0], updates[0]['image_review_url'])
    assert not any('blocked_missing_metadata' == row.get('status') for row in env['assets'].values())


@pytest.mark.asyncio
async def test_factual_fill_preserves_single_passed_view_and_generates_only_two_missing(monkeypatch):
    from test_static_docu_qa_park import _pipeline_env, REF_HOSTED
    cap = {'view_role': 'side_profile', 'title': 'HMS Argus', 'sub': '', 'specs': [],
           **image_review_stamp('HMS Argus', REF_HOSTED, {'role': 'aircraft carrier'}, URL)}
    kept = {'id': 'kept', 'status': 'done', 'image_url': URL, 'caption': json.dumps(cap)}
    env = _pipeline_env(monkeypatch, verdicts=[True, True], gen_urls=[URL+'2', URL+'3'],
                        isolate_single_view=False, existing_asset_rows=[kept], docu_module=sd, image_client_module=importlib.import_module("shared.clients.image_client"))
    env['assets']['kept'] = kept.copy()
    _use_factual_video(monkeypatch, env)
    result = await sd.generate_static_images_for_video(env['video_id'], env['tenant_id'])
    assert result['status'] == 'completed'
    assert len(env['gen_prompts']) == 2
    assert env['assets']['kept']['image_url'] == URL
    assert not any('DELETE FROM assets WHERE video_id=' in q and 'status=' not in q for q in env['queries'])
