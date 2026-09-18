import asyncio,json,sys
from pathlib import Path
ROOT=Path.cwd();sys.path[:0]=['/tmp/image-automation-source',str(ROOT/'backend')]
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from database import fetch_one,close_pool
from pipeline_executor import _machine_documentary_hold_roster_entries
from static_docu import _machine_key
from reference_selection import selection_ready,_fetch_image,SelectionFailure
from reference_sources import collect_candidates,_entity_queries,_names
VIDEO='44dbf2b2-a27a-47ea-a608-4c31c906be9a';TENANT='561b872d-7b73-45e3-9c44-7f30c3566eda'
async def main():
 video=await fetch_one('SELECT id,render_mode,research_payload FROM videos WHERE id=$1 AND tenant_id=$2',VIDEO,TENANT)
 out=[]
 for entry in _machine_documentary_hold_roster_entries(video):
  machine=entry['name'];cached=await fetch_one("SELECT source_url,hosted_url,reference_kind,selection_review FROM static_reference_cache WHERE tenant_id=$1 AND machine_key=$2 AND reference_kind='photo'",TENANT,_machine_key(machine))
  if selection_ready(cached):continue
  candidates=await collect_candidates(machine,entry.get('aliases'),facts=entry.get('facts'),cached_url=(cached or {}).get('source_url'))
  for c in candidates:
   if c.get('reason_code'):continue
   try:
    decoded=await _fetch_image(c['image_url']);c['decoded']={k:v for k,v in decoded.items() if not k.startswith('_')}
   except SelectionFailure as exc:c['decode_error']={'code':exc.code,'reason':exc.reason}
  out.append({'machine':machine,'queries':_entity_queries(machine,_names(machine,entry.get('aliases')),entry.get('facts')),'candidates':candidates})
  (ROOT/'tasks/image-automation-source-probe.json').write_text(json.dumps(out,indent=2))
  print(json.dumps({'machine':machine,'queries':out[-1]['queries'],'candidates':[{'title':c.get('title'),'caption':c.get('caption','')[:140],'decoded':c.get('decoded'),'error':c.get('decode_error') or c.get('reason_code')} for c in candidates]}),flush=True)
 await close_pool()
asyncio.run(main())
