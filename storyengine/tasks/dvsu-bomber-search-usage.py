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
    key=await get_secret('tavily_api_key','561b872d-7b73-45e3-9c44-7f30c3566eda')
    assert key, 'No tenant-scoped Tavily key'
    async with httpx.AsyncClient(timeout=30) as client:
        result=await client.get('https://api.tavily.com/usage',headers={'Authorization':'Bearer '+key})
    result.raise_for_status()
    raw=result.json()
    allowed={'usage','limit','current_plan','plan_usage','plan_limit','paygo_usage','paygo_limit','search_usage','extract_usage','crawl_usage','map_usage','research_usage'}
    out={'at':datetime.now(timezone.utc).isoformat(),'credential_source':'customer tenant-scoped vault entry','account_owner':'not provided by API'}
    for scope in ('key','account'):
        out[scope]={k:v for k,v in (raw.get(scope) or {}).items() if k in allowed}
    print(json.dumps(out,indent=2))

asyncio.run(main())
