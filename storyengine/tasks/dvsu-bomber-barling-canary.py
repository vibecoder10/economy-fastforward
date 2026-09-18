import json,subprocess
from pathlib import Path
from datetime import datetime,timezone
import httpx
root=Path(__file__).resolve().parents[1]
video='658e11e0-1f24-457e-95ef-3c8a0bd00f45'
p=root/'tasks/dvsu-bomber-barling-canary-receipt.json'
assert not p.exists(),'Canary already attempted; reconcile saved state'
token=subprocess.run([str(root/'scripts/se.sh'),'token'],capture_output=True,text=True,check=True).stdout.strip()
with httpx.Client(base_url='https://storyengine.dev',headers={'Authorization':'Bearer '+token,'X-Active-Tenant':'561b872d-7b73-45e3-9c44-7f30c3566eda'},timeout=60) as c:
 r=c.get('/api/health');r.raise_for_status();assert r.json()['active_work']['total']==0
 r=c.get('/api/videos/'+video);r.raise_for_status();v=r.json();v=v.get('video',v);assert v['status']=='ready_for_images' and v.get('max_spend') is None
 p.write_text(json.dumps({'video':video,'scene':1,'state':'requested','at':datetime.now(timezone.utc).isoformat()}))
 r=c.post('/api/pipeline/coverage-images/'+video,params={'scene':1});p.write_text(json.dumps({'video':video,'scene':1,'http':r.status_code,'result':r.json()},indent=2));r.raise_for_status();print(p.read_text())
