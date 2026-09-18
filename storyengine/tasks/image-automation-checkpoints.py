import json
from pathlib import Path
root=Path.cwd()/'data/reference-reviews'
for p in sorted(root.glob('*.json')):
 d=json.loads(p.read_text());attempts=[]
 for a in d.get('attempts',[]):
  usage={}
  try:usage=json.loads(a.get('provider_response_body') or '{}').get('usage',{})
  except ValueError:pass
  attempts.append({k:a.get(k) for k in ('number','status','http_status','stop_reason','error')}|{'usage':usage})
 print(json.dumps({'file':p.name,'machine':d.get('machine'),'status':d.get('status'),'checked_at':d.get('checked_at'),'attempts':attempts}),flush=True)
