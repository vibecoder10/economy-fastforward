"""Guarded research-only request and canonical-name/assessment readback."""
import json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
VIDEO='44dbf2b2-a27a-47ea-a608-4c31c906be9a'
TENANT='561b872d-7b73-45e3-9c44-7f30c3566eda'
mode=sys.argv[1] if len(sys.argv)>1 else 'read'
token=subprocess.run([str(ROOT/'scripts/se.sh'),'token'],capture_output=True,text=True,check=True).stdout.strip()
with httpx.Client(base_url='https://storyengine.dev',headers={'Authorization':'Bearer '+token,'X-Active-Tenant':TENANT},timeout=90) as c:
 def get(path):
  r=c.get(path);r.raise_for_status();return r.json()
 task=get('/api/pipeline/task/'+VIDEO)
 v=get('/api/videos/'+VIDEO);v=v.get('video',v);p=v.get('research_payload')or{};p=json.loads(p) if isinstance(p,str) else p
 names=json.loads((ROOT/'tasks/representative-roster-acceptance.json').read_text())['names']
 assert p.get('recommended_final_roster')==names,'Accepted roster changed'
 at=datetime.now(timezone.utc).isoformat()
 if mode=='run':
  receipt=ROOT/'tasks/submarine-research-request.json'
  assert not receipt.exists(),'Research request already attempted; reconcile saved receipt'
  assert task.get('status') not in ('running','pending','queued'),'Active video task'
  assert get('/api/health')['active_work']['total']==0,'Production active work'
  assert p.get('roster_images',{}).get('verified')==20
  assert p.get('machine_script_contract')=='factual_100_v1'
  receipt.write_text(json.dumps({'at':at,'outcome':'unknown','video':VIDEO}))
  r=c.post('/api/pipeline/machine-research/'+VIDEO)
  receipt.write_text(json.dumps({'at':at,'http':r.status_code,'response':r.json()},indent=2));print(receipt.read_text());r.raise_for_status()
 else:
  cards=p.get('unit_research_cards')or[]
  packages=p.get('machine_raw_source_packages')or{}
  rows=[]
  for name in names:
   card=next((x for x in cards if x.get('unit')==name),{})
   package=next((x for x in packages.values() if isinstance(x,dict) and x.get('machine')==name),{})
   assessment=package.get('claim_assessment')or{}
   summary=card.get('research_summary')or{}
   rows.append({'machine':name,'card':bool(card),'readiness':card.get('readiness'),'assessment_status':assessment.get('status'),'claim_counts':{status:sum(x.get('status')==status for x in assessment.get('claims',[])) for status in ['supported','disputed','insufficient','out_of_scope']},'summary_passed':summary.get('passed'),'warnings':summary.get('warnings') or assessment.get('warnings',[])})
  result={'at':at,'task':task,'status':v.get('status'),'total_cost':v.get('total_cost'),'images':p.get('roster_images'),'names':names,'rows':rows,'payload':p}
  (ROOT/'tasks/submarine-research-live-latest.json').write_text(json.dumps(result,indent=2))
  with (ROOT/'tasks/submarine-research-progress.jsonl').open('a') as f:f.write(json.dumps({k:x for k,x in result.items() if k!='payload'})+'\n')
  print(json.dumps({'at':at,'task':task,'summaries':sum(r['summary_passed'] is True for r in rows),'assessments':sum(r['assessment_status']=='assessed' for r in rows),'cards':sum(r['card'] for r in rows),'total_cost':v.get('total_cost')}))
