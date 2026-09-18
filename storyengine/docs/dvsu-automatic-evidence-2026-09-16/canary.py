"""One bounded Holland-only request per stage; no automatic retries."""
import json,subprocess,urllib.request,urllib.error,sys
from pathlib import Path
p=Path(__file__).resolve().parent
stage=sys.argv[1]
assert stage in {'research','resume','resume_review','readiness','preview','preview_final','preview_verified','preview_audited','preview_audit_retry'}
endpoint={'research':'machine-research-one','resume':'machine-research-one','resume_review':'machine-research-one','readiness':'machine-script-preview-readiness','preview':'machine-script-preview','preview_final':'machine-script-preview','preview_verified':'machine-script-preview','preview_audited':'machine-script-preview','preview_audit_retry':'machine-script-preview'}[stage]
marker=p/f'canary-{stage}-started.json'
body={'machine':'SS-1 — USS Holland'}
if stage!='readiness': body['confirmed_paid_run']=True
if stage=='research': body['source_urls']=[
 'https://www.govinfo.gov/content/pkg/GPO-CRECB-1901-pt4-v34/pdf/GPO-CRECB-1901-pt4-v34-2.pdf#page=77',
 'https://navalunderseamuseum.org/undersea-pioneers2/']
if stage in {'preview','preview_final','preview_verified','preview_audited','preview_audit_retry'}:
 ready=json.loads((p/'canary-readiness-response.json').read_text())
 assert ready['response'].get('ready') is True,'Readiness must pass before a paid preview'
token=subprocess.run(['./scripts/se.sh','token'],capture_output=True,text=True,check=True).stdout.strip()
assert len(token.split('.'))==3
tenant=json.loads(Path('docs/preview-label-2026-09-16/workspace.json').read_text())['tenant_id']
with marker.open('x') as f: json.dump({'stage':stage,'body':body},f)
req=urllib.request.Request('https://storyengine.dev/api/pipeline/'+endpoint+'/44dbf2b2-a27a-47ea-a608-4c31c906be9a',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token,'X-Active-Tenant':tenant},method='POST')
try:
 with urllib.request.urlopen(req,timeout=900) as r: status=r.status;data=json.load(r)
except urllib.error.HTTPError as e:
 status=e.code; raw=e.read().decode('utf-8',errors='replace')
 try:data=json.loads(raw)
 except ValueError:data={'detail':'Gateway returned a non-JSON error','raw_body':raw[:2000]}
except Exception as e:
 (p/f'canary-{stage}-uncertain.json').write_text(json.dumps({'error_type':type(e).__name__,'message':str(e),'retry':False}))
 raise
(p/f'canary-{stage}-response.json').write_text(json.dumps({'http_status':status,'response':data},ensure_ascii=False))
print(json.dumps({'http_status':status,**{k:v for k,v in data.items() if k in ['status','ready','machine','scene','summary','warnings','detail','next_action']}}),flush=True)
