#!/usr/bin/env python3
"""Parent-review-only CAS save preparation for the fresh G2 v2 referee result.

--check builds the exact proposed payload locally and makes no external call.
--apply is intentionally guarded for a later parent GO and is not invoked here.
"""
from __future__ import annotations
import copy, hashlib, json, os, sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parents[1]
BASELINE = DOCS / 'live-after-preview-flat.json'
FRESH = DOCS / 'ss2-copyedit-referee-v2-result.json'
PROPOSAL = DOCS / 'ss2-copyedit-cas-proposal.json'
TENANT = '561b872d-7b73-45e3-9c44-7f30c3566eda'
VIDEO = '44dbf2b2-a27a-47ea-a608-4c31c906be9a'

# Only non-review cache identity/authoring fields survive from the old preview.
CACHE_FIELDS = {'machine', 'scene', 'machine_script_contract', 'source_fingerprint',
                'research_source', 'saved', 'subject_context', 'writer_request_budget',
                'length_target_attempted'}
STALE_REVIEW_FIELDS = {'paragraph', 'word_count', 'passed', 'warnings', 'advisories', 'claim_map',
    'sources', 'factual_passed', 'editorial_review', 'editorial_review_version', 'support_audit',
    'review_context_version', 'compiler_version', 'packet_fingerprint', 'selected_fact_ids',
    'script_packet_receipt', 'review_request_budget'}

def read(path: Path) -> dict:
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict): raise RuntimeError(f'{path.name} is not an object')
    return value

def proposal() -> tuple[dict,dict]:
    baseline, envelope = read(BASELINE), read(FRESH)
    payload=baseline.get('research_payload')
    old=((payload or {}).get('machine_script_previews') or {}).get('SS2')
    fresh=envelope.get('result')
    if not isinstance(payload,dict) or not isinstance(old,dict) or not isinstance(fresh,dict):
        raise RuntimeError('baseline preview or fresh referee result is absent')
    if fresh.get('passed') is not True or fresh.get('factual_passed') is not True:
        raise RuntimeError('fresh referee result did not pass factual gate')
    editorial=fresh.get('editorial_review') or {}
    if editorial.get('passed') is not True or any(v is not True for v in (editorial.get('checks') or {}).values()):
        raise RuntimeError('fresh referee result did not pass every editorial gate')
    if fresh.get('warnings') != [] or len(str(fresh.get('paragraph') or '').split()) != 96:
        raise RuntimeError('fresh referee result is not the reviewed 96-word clean result')
    audit=fresh.get('support_audit') or []
    if len(audit) != 5 or any(row.get('supported') is not True for row in audit if isinstance(row,dict)):
        raise RuntimeError('fresh referee support audit is incomplete')
    original_hash=hashlib.sha256(str(old.get('paragraph') or '').encode()).hexdigest()
    if envelope.get('original_paragraph_sha256') != original_hash:
        raise RuntimeError('fresh result does not bind the baseline original paragraph')
    if [r.get('fact_ids') for r in fresh.get('claim_map') or []] != [r.get('fact_ids') for r in old.get('claim_map') or []]:
        raise RuntimeError('fresh result changed fact IDs')
    cache={key:copy.deepcopy(old[key]) for key in CACHE_FIELDS if key in old}
    new_preview={**cache, **copy.deepcopy(fresh)}
    # Fresh result is the only review state. Nothing absent from it may leak
    # forward from the old preview, especially advisories and warnings.
    for key in STALE_REVIEW_FIELDS:
        if key not in fresh: new_preview.pop(key,None)
    new_payload=copy.deepcopy(payload)
    new_payload.setdefault('machine_script_previews',{})['SS2']=new_preview
    new_preview['copyedit_receipt'] = {
      'original_paragraph_sha256': original_hash,
      'minimal_edits': [
        {'from':'with crews living ashore or aboard tenders rather than at sea','to':'with their crews living ashore or aboard tenders'},
        {'from':'a teacher by necessity','to':'a teacher in practice'}],
      'referee_rerun': True,
      'fresh_referee_packet_fingerprint': fresh.get('packet_fingerprint')}
    # Only the current SS2 preview changes. Historical durable job is untouched.
    restored=copy.deepcopy(new_payload)
    restored['machine_script_previews']['SS2']=copy.deepcopy(old)
    if restored != payload: raise RuntimeError('proposal changes data outside SS2 preview')
    sensitive={key:baseline.get(key) for key in ('status','script','script_validation','max_spend','total_cost','render_mode','video_title','headline')}
    receipt={'mode':'prepared_not_applied','tenant_id':TENANT,'video_id':VIDEO,
      'expected_research_payload_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
      'new_research_payload_sha256':hashlib.sha256(json.dumps(new_payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
      'production_sensitive_snapshot':sensitive,'original_paragraph_sha256':original_hash,
      'new_paragraph':new_preview['paragraph'],'fresh_packet_fingerprint':fresh['packet_fingerprint'],
      'fresh_review_passed':True,'fresh_editorial_passed':True,'fresh_support_rows':len(audit),
      'old_preview_review_keys_removed':sorted(key for key in STALE_REVIEW_FIELDS if key not in fresh and key in old),
      'new_payload':new_payload}
    return receipt, baseline

async def apply(receipt:dict, baseline:dict)->None:
    if os.environ.get('G2_CAS_PARENT_GO') != 'YES':
        raise RuntimeError('apply requires explicit G2_CAS_PARENT_GO=YES')
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    if not os.environ.get('DATABASE_URL'): raise RuntimeError('canonical backend .env did not provide DATABASE_URL')
    sys.path.insert(0,str(ROOT/'backend'))
    from database import execute
    old=baseline['research_payload']; s=receipt['production_sensitive_snapshot']
    sql='''UPDATE videos SET research_payload=$1::jsonb, updated_at=now()
WHERE id=$2 AND tenant_id=$3
  AND research_payload=$4::jsonb
  AND status IS NOT DISTINCT FROM $5
  AND script IS NOT DISTINCT FROM $6
  AND script_validation IS NOT DISTINCT FROM $7
  AND max_spend IS NOT DISTINCT FROM $8
  AND total_cost::double precision IS NOT DISTINCT FROM $9::double precision
  AND render_mode IS NOT DISTINCT FROM $10
  AND video_title IS NOT DISTINCT FROM $11
  AND headline IS NOT DISTINCT FROM $12'''
    result=await execute(sql,json.dumps(receipt['new_payload'],ensure_ascii=False),VIDEO,TENANT,json.dumps(old,ensure_ascii=False),s['status'],s['script'],(None if s['script_validation'] is None else json.dumps(s['script_validation'],ensure_ascii=False)),s['max_spend'],s['total_cost'],s['render_mode'],s['video_title'],s['headline'])
    if result != 'UPDATE 1': raise RuntimeError(f'CAS refused concurrent state: {result}')

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in {'--check','--apply'}: raise SystemExit('usage: --check|--apply')
    receipt, baseline=proposal()
    PROPOSAL.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if sys.argv[1]=='--apply':
        import asyncio; asyncio.run(apply(receipt,baseline))
    print(json.dumps({key:receipt[key] for key in receipt if key!='new_payload'},ensure_ascii=False))
if __name__=='__main__': main()
