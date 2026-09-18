"""Single authorized Roster request and compact persisted readback; never Run All."""
import json, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
import httpx
ROOT=Path(__file__).resolve().parents[1]
VIDEO='44dbf2b2-a27a-47ea-a608-4c31c906be9a'
TENANT='561b872d-7b73-45e3-9c44-7f30c3566eda'
token=subprocess.run([str(ROOT/'scripts/se.sh'),'token'],capture_output=True,text=True,check=True).stdout.strip()
mode=sys.argv[1] if len(sys.argv)>1 else 'read'
with httpx.Client(base_url='https://storyengine.dev',headers={'Authorization':'Bearer '+token,'X-Active-Tenant':TENANT},timeout=90) as c:
 def get(path):
  r=c.get(path);r.raise_for_status();return r.json()
 task=get('/api/pipeline/task/'+VIDEO)
 v=get('/api/videos/'+VIDEO);v=v.get('video',v)
 p=v.get('research_payload') or {};p=json.loads(p) if isinstance(p,str) else p
 now=datetime.now(timezone.utc).isoformat()
 if mode in ('start', 'start-audit'):
  receipt=ROOT/('tasks/representative-roster-audit-request.json' if mode=='start-audit' else 'tasks/representative-roster-rerun-request.json')
  if mode=='start-audit':
   sys.path.insert(0,str(ROOT/'backend'))
   from roster_selection import representative_warnings
   assert len(p.get('unit_roster') or [])==20 and not representative_warnings(v.get('video_title') or '',p['unit_roster']), 'Saved roster must already contain20named representatives'
  assert not receipt.exists(),'Request exists; reconcile, do not repeat'
  assert task.get('status') not in ('pending','running','queued'),'Existing active task'
  health=get('/api/health')
  assert health['active_work']['total']==0 and not health['drain']['draining'],'Busy or draining'
  assert len(p.get('roster_selection_history') or [])>=2,'Preservation archive missing'
  assert not p.get('unit_research_cards'),'Old active cards not archived'
  assert (p.get('roster_selection') or {}).get('status')=='needs_review','Not prepared for explicit rerun'
  receipt.write_text(json.dumps({'at':now,'video':VIDEO,'state':'request_outcome_unknown'}))
  response=c.post('/api/pipeline/research/'+VIDEO,json={})
  receipt.write_text(json.dumps({'at':now,'video':VIDEO,'http':response.status_code,'response':response.json()},indent=2))
  print(receipt.read_text());response.raise_for_status()
 else:
  (ROOT/'tasks/representative-roster-rerun-live.json').write_text(json.dumps({'at':now,'video':v,'task':task},indent=2))
  summary={'at':now,'task':task,'selection_status':(p.get('roster_selection') or {}).get('status'),'phase':p.get('research_phase'),'validation_passed':(p.get('unit_roster_validation') or {}).get('passed'),'audit_passed':(p.get('independent_selection_audit') or {}).get('passed'),'count':len(p.get('unit_roster') or []),'names':p.get('recommended_final_roster'),'cards':len(p.get('unit_research_cards') or []),'history_counts':[len((h.get('payload') or {}).get('unit_roster') or []) for h in p.get('roster_selection_history',[])]}
  with (ROOT/'tasks/representative-roster-rerun-progress.jsonl').open('a') as f:f.write(json.dumps(summary)+'\n')
  print(json.dumps(summary,indent=2))
