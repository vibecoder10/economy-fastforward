import json,subprocess
from pathlib import Path
from datetime import datetime,timezone
import httpx
ROOT=Path(__file__).resolve().parents[1]; video='44dbf2b2-a27a-47ea-a608-4c31c906be9a'
receipt=ROOT/'tasks/submarine-research-resume-request.json'
assert not receipt.exists(),'Resume already submitted; reconcile receipt'
token=subprocess.run([str(ROOT/'scripts/se.sh'),'token'],capture_output=True,text=True,check=True).stdout.strip()
with httpx.Client(base_url='https://storyengine.dev',headers={'Authorization':'Bearer '+token,'X-Active-Tenant':'561b872d-7b73-45e3-9c44-7f30c3566eda'},timeout=90) as c:
 health=c.get('/api/health').json();assert health['active_work']['total']==0
 v=c.get('/api/videos/'+video).json();v=v.get('video',v);p=v['research_payload'];p=json.loads(p) if isinstance(p,str) else p
 before=json.loads((ROOT/'tasks/submarine-research-run1-terminal.json').read_text())
 assert p['recommended_final_roster']==before['names']
 assert p['roster_images']['verified']==20
 passed={x['unit']:x['research_summary'] for x in before['payload']['unit_research_cards'] if x.get('research_summary',{}).get('passed')}
 for name,summary in passed.items(): assert next(x for x in p['unit_research_cards'] if x['unit']==name)['research_summary']==summary
 receipt.write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'status':'unknown','preserved_passed':list(passed)}))
 r=c.post('/api/pipeline/machine-research/'+video);body=r.json();receipt.write_text(json.dumps({'status':r.status_code,'response':body,'preserved_passed':list(passed)},indent=2));print(r.status_code,body);r.raise_for_status()
