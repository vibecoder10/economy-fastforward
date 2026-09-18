import asyncio,json,sys
from pathlib import Path
ROOT=Path('/home/clawd/projects/economy-fastforward')
sys.path[:0]=[str(ROOT/'storyengine/backend'),str(ROOT/'skills/video-pipeline')]
from dotenv import load_dotenv
load_dotenv(ROOT/'storyengine/.env')
import httpx
import pipeline_executor as pe
from factual_machine_research import build_factual_evidence_card,factual_card_contract_warnings

async def main():
    response=json.loads((ROOT/'storyengine/tasks/dvsu-kie-search-canary-gpt-5-2.json').read_text())
    leads=json.loads(response['response']['choices'][0]['message']['content'])
    machine=response['machine']; candidates=[]; sources=[]
    executor=object.__new__(pe.PipelineExecutor)
    async with httpx.AsyncClient(timeout=30,follow_redirects=True) as client:
        for index,lead in enumerate(leads,1):
            url=lead['exact_source_url'];text=await executor._fetch_source_text(client,url)
            excerpts=pe._sentence_candidates_from_source(text,machine,limit=10)
            sources.append({'url':url,'chars':len(text),'excerpt_count':len(excerpts)})
            for num,excerpt in enumerate(excerpts,1):
                candidates.append({'excerpt_id':f'S{index}-E{num}','source_id':f'S{index}','source_title':lead['title'],'source_url':url,'source_capture_method':'fetched_page','locator':f'S{index}-E{num}','text':excerpt})
    package={'machine':machine,'candidate_excerpts':candidates}
    card=build_factual_evidence_card(machine,package)
    warnings=factual_card_contract_warnings(machine,card,package)
    out={'machine':machine,'source_fetches':sources,'factual_card_excerpt_count':len(card['evidence_segments']),'warnings':warnings,'package':package,'card':card,'production_write':False}
    (ROOT/'storyengine/tasks/dvsu-kie-source-check.json').write_text(json.dumps(out,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k not in {'package','card'}},indent=2))

asyncio.run(main())
