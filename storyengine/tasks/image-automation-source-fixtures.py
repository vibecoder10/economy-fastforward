import asyncio,json,sys
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from static_docu import _wm_get,_WIKIPEDIA_API,_COMMONS_UA
import httpx
async def main():
 out={}
 async with httpx.AsyncClient(timeout=30,headers=_COMMONS_UA) as c:
  for title in ['United States S-class submarine','USS Barracuda (SS-163)','Tang-class submarine']:
   r=await _wm_get(c,_WIKIPEDIA_API,params={'action':'parse','page':title,'prop':'text|wikitext','redirects':1,'format':'json'})
   r.raise_for_status();out[title]=r.json()
 (ROOT/'tasks/image-automation-article-fixtures.json').write_text(json.dumps(out))
 print(json.dumps({k:{'title':v.get('parse',{}).get('title'),'html_chars':len(v.get('parse',{}).get('text',{}).get('*','')),'error':v.get('error')} for k,v in out.items()}))
asyncio.run(main())
