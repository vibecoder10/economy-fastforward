import json, subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
import httpx
ROOT=Path(__file__).resolve().parents[1]; VIDEO='44dbf2b2-a27a-47ea-a608-4c31c906be9a';TENANT='561b872d-7b73-45e3-9c44-7f30c3566eda'
token=subprocess.run([str(ROOT/'scripts/se.sh'),'token'],capture_output=True,text=True,check=True).stdout.strip()
def now():return datetime.now(timezone.utc).isoformat()
with httpx.Client(base_url='https://storyengine.dev',headers={'Authorization':'Bearer '+token,'X-Active-Tenant':TENANT},timeout=90) as c:
 def get(p):
  r=c.get(p);r.raise_for_status();return r.json()
 task=get('/api/pipeline/task/'+VIDEO);v=get('/api/videos/'+VIDEO);v=v.get('video',v);p=v.get('research_payload') or {};p=json.loads(p) if isinstance(p,str) else p
 action=sys.argv[1] if len(sys.argv)>1 else 'read'
 if action in ('select','build'):
  suffix='-boundary2' if len(sys.argv)>2 and sys.argv[2]=='boundary2' else ('-boundary' if len(sys.argv)>2 and sys.argv[2]=='boundary' else '')
  receipt=ROOT/('tasks/submarine-stage-'+action+suffix+'-request.json')
  if suffix:assert action=='select' and task.get('status')=='failed' and len(p.get('unit_roster') or []) in (20,21), 'Boundary repair requires saved failed 21-candidate checkpoint'
  assert not receipt.exists(),'Request already attempted; reconcile receipt'
  assert task.get('status') not in ('running','queued','pending'),'Existing task active'
  assert get('/api/health')['active_work']['total']==0,'Active production work'
  if action=='select':assert (p.get('roster_selection') or {}).get('status')!='completed','Selection already completed'
  else:assert (p.get('roster_selection') or {}).get('status')=='completed' and (p.get('unit_roster_validation') or {}).get('passed'),'Roster must pass before detailed research'
  receipt.write_text(json.dumps({'at':now(),'action':action,'outcome':'unknown'}))
  r=c.post('/api/pipeline/'+('research/' if action=='select' else 'build/')+VIDEO,json={} if action=='select' else {'target':'finish'})
  receipt.write_text(json.dumps({'at':now(),'action':action,'http':r.status_code,'response':r.json()},indent=2));print(receipt.read_text());r.raise_for_status()
 else:
  out={'at':now(),'task':task,'video_status':v.get('status'),'selection':p.get('roster_selection'),'phase':p.get('research_phase'),'count':len(p.get('unit_roster') or []),'validation':p.get('unit_roster_validation'),'hold':p.get('unit_research_hold_validation'),'cards':len(p.get('unit_research_cards') or []),'history_counts':[len((x.get('payload') or {}).get('unit_roster') or []) for x in p.get('roster_selection_history',[])],'names':p.get('recommended_final_roster')}
  (ROOT/'tasks/submarine-stage-live-latest.json').write_text(json.dumps({'at':now(),'video':v,'task':task},indent=2))
  with (ROOT/'tasks/submarine-stage-progress.jsonl').open('a') as f:f.write(json.dumps(out)+'\n')
  print(json.dumps(out,indent=2))
