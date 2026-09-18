import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path('backend').resolve()))
import httpx
from pipeline_executor import PipelineExecutor,_sentence_candidates_from_source
from factual_machine_research import candidate_mentions_machine
urls={
'undersea':'https://navalunderseamuseum.org/undersea-pioneers2/',
'australia':'https://submarinemuseum.au/explore/australia-submarine/submarines/a-history-of-submarines/',
'lyncean':'https://lynceans.org/all-posts/a-brief-look-back-at-the-worlds-first-modern-submarine-2/',
'navy':'https://www.history.navy.mil/our-collections/photography/us-navy-ships/alphabetical-listing/h/uss-holland--submarine-torpedo-boat--1-0.html'}
async def main():
 ex=PipelineExecutor.__new__(PipelineExecutor)
 async with httpx.AsyncClient(timeout=30,follow_redirects=True) as c:
  async def capture(k,u):
   text=await ex._fetch_source_text(c,u)
   Path(f'docs/dvsu-source-recovery-2026-09-16/{k}.txt').write_text(text)
   excerpts=_sentence_candidates_from_source(text,'SS-1 USS Holland',matcher=candidate_mentions_machine)
   print(json.dumps({'key':k,'url':u,'chars':len(text),'excerpts':excerpts}),flush=True)
  await asyncio.gather(*(capture(k,u) for k,u in urls.items()))
asyncio.run(main())
