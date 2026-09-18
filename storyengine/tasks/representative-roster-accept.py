"""Validate the final readback without modifying production or calling providers."""
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from roster_selection import selection_validation
from roster_coverage import selection_audit_is_current
snapshot=json.loads((ROOT/'tasks/representative-roster-rerun-live.json').read_text())
v=snapshot['video'];p=v['research_payload'];p=json.loads(p) if isinstance(p,str) else p
assert snapshot['task']['status']=='completed',snapshot['task']
assert (p.get('roster_selection') or {}).get('status')=='completed'
assert p.get('research_phase')=='roster_complete'
assert len(p['unit_roster'])==20
assert selection_validation(v['video_title'],p)['passed']
assert selection_audit_is_current(v['video_title'],p)
assert p['independent_selection_audit']['passed'] is True
assert p['unit_roster_validation']['passed'] is True
assert not p.get('unit_research_cards')
assert [len(h['payload']['unit_roster']) for h in p['roster_selection_history']]==[58,20]
archive=next(h for h in p['roster_selection_history'] if h.get('marker')=='representative-roster-rerun-20260916')
assert len(archive['compact_machine_research_cards'])==1
before=json.loads((ROOT/'tasks/representative-roster-before-rerun-full.json').read_text())['video']['research_payload']
assert p['roster_selection_history'][:-1]==before['roster_selection_history']
for k,value in before.items():
 if k not in ('roster_selection_history','unit_roster_validation','unit_research_cards'):
  assert archive['payload'].get(k)==value,('archive mismatch',k)
old_cards=[{k:v for k,v in c.items() if k!='readiness'} for c in before['unit_research_cards']]
archived_cards=[{k:v for k,v in c.items() if k!='readiness'} for c in archive['payload']['unit_research_cards']]
assert old_cards==archived_cards
result={'status':'passed','at':snapshot['at'],'roster_count':20,'names':p['recommended_final_roster'],'class_count':len({r['class_name'].casefold() for r in p['unit_roster']}),'fresh_audit':True,'audit_sources':p['independent_selection_audit']['sources'],'archive_counts':[58,20],'archived_compact_cards':1,'next':'Gather images for exact named boats; no later stage started.'}
(ROOT/'tasks/representative-roster-acceptance.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k not in ('names','audit_sources')},indent=2))
