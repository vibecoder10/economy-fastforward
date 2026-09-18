#!/usr/bin/env python3
"""Offline full-run test for the G2 v2 reviewer harness; no service calls."""
from __future__ import annotations
import asyncio, copy, importlib.util, json, os, sys, tempfile, types
from pathlib import Path

DOCS = Path(__file__).resolve().parent
HARNESS = DOCS / 'ss2-copyedit-referee-v2.py'
SNAPSHOT = DOCS / 'live-after-preview-flat.json'

spec = importlib.util.spec_from_file_location('g2v2', HARNESS)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

snapshot = json.loads(SNAPSHOT.read_text())
video = copy.deepcopy(snapshot)
video['research_payload'] = json.dumps(video['research_payload'], ensure_ascii=False)
video['max_spend'] = 10
video['total_cost'] = 0
calls = {'review': 0, 'acquire': 0, 'release': 0, 'cancel': 0, 'dotenv': 0}

class FakeExecutor:
    def __init__(self, tenant):
        assert tenant == mod.TENANT
        self._pipeline = types.SimpleNamespace(anthropic=object())
    async def _ensure_initialized(self):
        return None
    async def _get_video(self, video_id):
        assert video_id == mod.VIDEO
        return copy.deepcopy(video)

async def fake_cancel(tenant, video_id):
    calls['cancel'] += 1
    assert (tenant, video_id) == (mod.TENANT, mod.VIDEO)
    return False

async def fake_acquire(tenant, video_id, stage, claimed_by=None):
    calls['acquire'] += 1
    assert (tenant, video_id, stage) == (mod.TENANT, mod.VIDEO, 'main')
    assert str(claimed_by).startswith('g2-copyedit-referee:')
    return True

async def fake_release(tenant, video_id, stage, claimed_by):
    calls['release'] += 1
    assert (tenant, video_id, stage) == (mod.TENANT, mod.VIDEO, 'main')

async def fake_review(machine, package, client, raw, **kwargs):
    calls['review'] += 1
    assert machine == mod.MACHINE and client is not None
    assert kwargs['allow_sentence_removal'] is False
    assert len(raw['paragraph'].split()) == 96
    return {'passed': True, 'word_count': 96, 'warnings': [], 'claim_map': raw['claim_map'],
            'packet_fingerprint': kwargs['script_packet']['packet_fingerprint'],
            'factual_passed': True, 'editorial_review': {'passed': True}}

def fake_dotenv(_path):
    calls['dotenv'] += 1
    os.environ['DATABASE_URL'] = 'mock://offline-only'

# _offline_check has already exercised actual helper imports by the time _run
# imports these runtime seams. Replace only the external/live boundaries.
import pipeline_executor, factual_machine_summary
pipeline_executor.PipelineExecutor = FakeExecutor
factual_machine_summary.review_existing_factual_summary = fake_review
sys.modules['cancel_registry'] = types.SimpleNamespace(is_cancel_requested=fake_cancel)
sys.modules['generation_claims'] = types.SimpleNamespace(acquire=fake_acquire, release_owned=fake_release)
sys.modules['dotenv'] = types.SimpleNamespace(load_dotenv=fake_dotenv)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    mod.ROOT = root
    mod.DOCS = root
    mod.MARKER = root / 'started.json'
    mod.RESULT = root / 'result.json'
    mod.CHECK = root / 'check.json'
    old_database_url = os.environ.pop('DATABASE_URL', None)
    try:
        asyncio.run(mod._run())
    finally:
        if old_database_url is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = old_database_url
    assert calls == {'review': 1, 'acquire': 1, 'release': 1, 'cancel': 1, 'dotenv': 1}, calls
    assert mod.MARKER.exists() and mod.RESULT.exists()
    raw = root / 'ss2-copyedit-referee-v2-raw-result.json'
    assert raw.exists()
    stored_raw = json.loads(raw.read_text())
    envelope = json.loads(mod.RESULT.read_text())
    assert stored_raw['passed'] is True and envelope['result'] == stored_raw
    assert envelope['offline_check']['edited_word_count'] == 96
    assert envelope['offline_check']['fact_ids_preserved'] is True
    print(json.dumps({'passed': True, 'calls': calls, 'raw_result_saved': raw.exists(),
                      'envelope_saved': mod.RESULT.exists(), 'edited_word_count': 96}))
