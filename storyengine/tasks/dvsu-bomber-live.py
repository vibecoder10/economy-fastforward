import json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
import httpx
ROOT=Path('/home/clawd/projects/economy-fastforward/storyengine') if Path('/tmp/se_token').exists() else Path(__file__).resolve().parents[1]
VIDEO='658e11e0-1f24-457e-95ef-3c8a0bd00f45'
TENANT='561b872d-7b73-45e3-9c44-7f30c3566eda'
token=Path('/tmp/se_token').read_text().strip() if Path('/tmp/se_token').exists() else subprocess.run([str(ROOT/'scripts/se.sh'),'token'],capture_output=True,text=True,check=True).stdout.strip()
with httpx.Client(base_url='http://localhost:8001' if Path('/tmp/se_token').exists() else 'https://storyengine.dev',headers={'Authorization':'Bearer '+token,'X-Active-Tenant':TENANT},timeout=90) as c:
    if len(sys.argv)>1 and sys.argv[1]=='cancel':
        r=c.post('/api/pipeline/cancel/'+VIDEO);r.raise_for_status();print(json.dumps(r.json()))
    elif len(sys.argv)>1 and sys.argv[1]=='resume':
        p=ROOT/('tasks/dvsu-bomber-resume-'+(sys.argv[2] if len(sys.argv)>2 else 'initial')+'.json')
        if p.exists(): raise SystemExit('Resume already attempted; reconcile saved state before any further request')
        state=c.get('/api/pipeline/task/'+VIDEO);state.raise_for_status()
        saved=state.json()
        research_checkpoint=(saved['status']=='completed' and any(message in (saved.get('message') or '') for message in ('18/28 machines researched; 10 still need review','23/28 machines researched; 5 still need review')))
        assert saved['status'] in {'failed','cancelled'} or research_checkpoint, 'Saved job not stopped; reconcile before resuming'
        health=c.get('/api/health');health.raise_for_status()
        assert health.json()['active_work']['total']==0, 'Active production work; not resuming'
        p.write_text(json.dumps({'requested_at':datetime.now(timezone.utc).isoformat(),'video':VIDEO,'target':'finish','outcome':'unknown'}))
        r=c.post('/api/pipeline/build/'+VIDEO,json={'target':'finish'})
        p.write_text(json.dumps({'requested_at':datetime.now(timezone.utc).isoformat(),'video':VIDEO,'target':'finish','http':r.status_code,'response':r.json()},indent=2))
        print(p.read_text());r.raise_for_status()
    else:
        out={'at':datetime.now(timezone.utc).isoformat()}
        r=c.get('/api/pipeline/task/'+VIDEO);r.raise_for_status();out['task']=r.json()
        r=c.get('/api/videos/'+VIDEO);r.raise_for_status();v=r.json()
        if 'video' in v:v=v['video']
        for k in ('id','video_title','status','final_video_url','youtube_url','upload_status','updated_at'):out[k]=v.get(k)
        payload=v.get('research_payload') or {}
        if isinstance(payload,str):payload=json.loads(payload)
        out['roster_count']=len(payload.get('unit_roster') or [])
        out['roster_passed']=(payload.get('unit_roster_validation') or {}).get('passed')
        out['hold']=(payload.get('unit_research_hold_validation') or {})
        out['hold']={k:out['hold'].get(k) for k in ('passed','passed_count','failed_count')}
        out['research_phase']=payload.get('research_phase')
        with (ROOT/'tasks/dvsu-bomber-progress.jsonl').open('a') as f:f.write(json.dumps(out)+'\n')
        print(json.dumps(out,indent=2))
