import json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
import httpx
root=Path(__file__).resolve().parents[1]
video='658e11e0-1f24-457e-95ef-3c8a0bd00f45'
receipt=root/'tasks/dvsu-bomber-image-hold-receipt.json'
token=subprocess.run([str(root/'scripts/se.sh'),'token'],capture_output=True,text=True,check=True).stdout.strip()
with httpx.Client(base_url='https://storyengine.dev',headers={'Authorization':'Bearer '+token,'X-Active-Tenant':'561b872d-7b73-45e3-9c44-7f30c3566eda'},timeout=60) as c:
 r=c.get('/api/videos/'+video);r.raise_for_status();v=r.json();v=v.get('video',v)
 action=sys.argv[1]
 if action=='hold':
  assert not receipt.exists(), 'Hold already attempted; reconcile before retry'
  assert v.get('max_spend') is None, 'Unexpected existing cap'
  saved={'video':video,'previous_cap':None,'temporary_cap':1,'at':datetime.now(timezone.utc).isoformat(),'state':'requested'}
  receipt.write_text(json.dumps(saved,indent=2))
  r=c.patch('/api/videos/'+video,json={'max_spend':1});r.raise_for_status()
 elif action=='restore':
  saved=json.loads(receipt.read_text());assert v.get('max_spend')==saved['temporary_cap'],'Cap changed; refusing restore'
  r=c.patch('/api/videos/'+video,json={'max_spend':saved['previous_cap']});r.raise_for_status()
 else: raise SystemExit('Unknown action')
 r=c.get('/api/videos/'+video);r.raise_for_status();check=r.json();check=check.get('video',check)
 saved['state']=action+' verified';saved['current_cap']=check.get('max_spend');receipt.write_text(json.dumps(saved,indent=2));print(receipt.read_text())
