import asyncio,json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/home/clawd/projects/economy-fastforward/storyengine')
sys.path.insert(0,str(ROOT/'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from vault import get_secret
import httpx

async def main():
    model=sys.argv[1] if len(sys.argv)>1 else 'gemini-2.5-flash'
    assert model in {'gemini-2.5-flash','gpt-5-2'}
    receipt=ROOT/('tasks/dvsu-kie-search-canary-'+model+'.json' if model!='gemini-2.5-flash' else 'tasks/dvsu-kie-search-canary.json')
    if receipt.exists():
        raise SystemExit('Existing request receipt; reconcile it instead of repeating the request')
    key=await get_secret('kie_ai_api_key','561b872d-7b73-45e3-9c44-7f30c3566eda')
    assert key, 'No tenant-scoped Kie key'
    headers={'Authorization':'Bearer '+key}
    out={'requested_at':datetime.now(timezone.utc).isoformat(),'status':'unknown','model':model,'machine':'General Dynamics FB-111A Aardvark'}
    async with httpx.AsyncClient(timeout=180,follow_redirects=True) as client:
        balance=await client.get('https://api.kie.ai/api/v1/chat/credit',headers=headers)
        out['balance_before']=balance.json()
        receipt.write_text(json.dumps(out,indent=2))
        r=await client.post('https://api.kie.ai/'+model+'/v1/chat/completions',headers=headers,json={
            'messages':[{'role':'user','content':'Use Google Search to find 4 real official or museum pages specifically about the General Dynamics FB-111A strategic bomber variant. Return only a compact JSON array with title, exact source URL, and one sentence stating what FB-111A facts the page supports. Prefer US Air Force or SAC Museum. Do not confuse FB-111A with generic F-111 or F-111F. No invented URLs. Keep the whole answer below 450 words.'}],
            'tools':[{'type':'function','function':{'name':'web_search' if model=='gpt-5-2' else 'googleSearch'}}],
            'stream':False,
        })
        out.update({'status':'response_received','http':r.status_code,'response':r.json()})
        receipt.write_text(json.dumps(out,indent=2))
        balance=await client.get('https://api.kie.ai/api/v1/chat/credit',headers=headers)
        out['balance_after']=balance.json()
        receipt.write_text(json.dumps(out,indent=2))
        print(json.dumps(out,indent=2))
        r.raise_for_status()

asyncio.run(main())
