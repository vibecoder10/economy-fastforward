import json,subprocess,urllib.request,urllib.error,sys
from pathlib import Path
p=Path('docs/dvsu-brief-2026-09-16')
stage=sys.argv[1]
assert stage in {'research','readiness','preview'}
endpoints={'research':'machine-research-one','readiness':'machine-script-preview-readiness','preview':'machine-script-preview'}
output=p/f'canary-{stage}-response.json'
if output.exists(): raise SystemExit('Response already exists; no duplicate request permitted')
token=subprocess.run(['./scripts/se.sh','token'],capture_output=True,text=True,check=True).stdout.strip()
assert len(token.split('.'))==3
tenant=json.loads(Path('docs/preview-label-2026-09-16/workspace.json').read_text())['tenant_id']
body={'machine':'SS-1 — USS Holland'}
if stage!='readiness':body['confirmed_paid_run']=True
req=urllib.request.Request('https://storyengine.dev/api/pipeline/'+endpoints[stage]+'/44dbf2b2-a27a-47ea-a608-4c31c906be9a',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token,'X-Active-Tenant':tenant},method='POST')
try:
 with urllib.request.urlopen(req,timeout=900) as r:status=r.status;data=json.load(r)
except urllib.error.HTTPError as e:status=e.code;data=json.load(e)
output.write_text(json.dumps({'http_status':status,'response':data},ensure_ascii=False))
print(json.dumps({'http_status':status,**{k:v for k,v in data.items() if k in ['status','ready','machine','scene','summary','warnings','detail','next_action']}}),flush=True)
