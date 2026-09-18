import asyncio,json,sys
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from static_docu import _wm_get,_COMMONS_API,_COMMONS_UA
from reference_selection import _fetch_image,SelectionFailure
import httpx
async def main():
 async with httpx.AsyncClient(timeout=30,headers=_COMMONS_UA) as c:
  r=await _wm_get(c,_COMMONS_API,params={'action':'query','titles':'File:USSBaracudaSS163.jpg','prop':'imageinfo','iiprop':'url|size','iiurlwidth':690,'format':'json'})
  info=next(iter(r.json()['query']['pages'].values()))['imageinfo'][0]
  out={'info':info}
  for name in ['thumburl','url']:
   if info.get(name):
    try:
     decoded=await _fetch_image(info[name]);out[name]={k:v for k,v in decoded.items() if not k.startswith('_')}
    except SelectionFailure as e:out[name]={'code':e.code,'reason':e.reason}
  (ROOT/'tasks/image-automation-native-probe.json').write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True)
asyncio.run(main())
