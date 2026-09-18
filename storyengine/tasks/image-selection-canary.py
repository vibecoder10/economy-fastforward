"""One tracked selection attempt each for two saved roster entries; no roster edits."""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path.cwd()
sys.path.insert(0,str(ROOT/'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from database import fetch_one, execute, close_pool
from pipeline_executor import _machine_documentary_hold_roster_entries
from static_docu import _prefetch_one_machine, _machine_key
from reference_selection import selection_receipt

VIDEO='44dbf2b2-a27a-47ea-a608-4c31c906be9a'
TENANT='561b872d-7b73-45e3-9c44-7f30c3566eda'
OUT=ROOT/'tasks/image-selection-canary-result.json'

async def main():
    assert not OUT.exists(), 'Canary already attempted; reconcile saved receipt, do not repeat.'
    import httpx
    async with httpx.AsyncClient() as c:
        health=(await c.get('http://localhost:8001/api/health')).json()
    assert health['active_work']['total']==0 and not health['drain']['draining'], 'Work active or drain enabled.'
    video=await fetch_one('SELECT id,render_mode,research_payload FROM videos WHERE id=$1 AND tenant_id=$2',VIDEO,TENANT)
    entries=_machine_documentary_hold_roster_entries(video)
    assert len(entries)==20
    targets=[e for name in ('Albacore','Barbel') for e in entries if name in e['name']]
    assert len(targets)==2
    OUT.write_text(json.dumps({'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','results':[]}))
    task=await fetch_one("INSERT INTO background_tasks (tenant_id,video_id,task_type,status,message,started_at,attempt) VALUES ($1,$2,'roster_images','running','Reviewing Albacore and Barbel image choices',now(),1) RETURNING id",TENANT,VIDEO)
    results=[]
    terminal='failed'
    try:
        for entry in targets:
            await execute('UPDATE background_tasks SET message=$1 WHERE id=$2','Reviewing image choices: '+entry['name'],task['id'])
            ok=await _prefetch_one_machine(TENANT,VIDEO,entry['name'],entries.index(entry),aliases=entry.get('aliases'),facts=entry.get('facts'))
            row=await fetch_one('SELECT receipt FROM static_reference_reviews WHERE tenant_id=$1 AND video_id=$2 AND machine_key=$3',TENANT,VIDEO,_machine_key(entry['name']))
            result=selection_receipt((row or {}).get('receipt'))
            results.append(result)
            OUT.write_text(json.dumps({'status':'running','results':results},indent=2))
            selected=result.get('selected') or {}
            print(json.dumps({'machine':entry['name'],'selected':ok,'compared':result.get('compared_count'),'reason_code':result.get('reason_code'),'reason':result.get('reason'),'source':selected.get('source_page'),'view':selected.get('view'),'score':selected.get('score')}),flush=True)
            if result.get('status')=='error':
                break
        terminal='completed' if len(results)==2 and all(x.get('status')=='selected' for x in results) else 'failed'
    finally:
        OUT.write_text(json.dumps({'status':terminal,'results':results},indent=2))
        await execute('UPDATE background_tasks SET status=$1,message=$2,completed_at=now() WHERE id=$3',terminal,'Image-selection sample: '+str(sum(x.get('status')=='selected' for x in results))+'/2 selected',task['id'])
        await close_pool()

asyncio.run(main())
