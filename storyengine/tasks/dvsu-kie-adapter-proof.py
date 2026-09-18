import asyncio,json,sys
from pathlib import Path
ROOT=Path('/home/clawd/projects/economy-fastforward')
sys.path[:0]=['/tmp/dvsu-kie-adapter',str(ROOT/'storyengine/backend'),str(ROOT/'skills/video-pipeline')]
from dotenv import load_dotenv
load_dotenv(ROOT/'storyengine/.env')
import pipeline_executor as pe
from factual_machine_research import factual_package_contract_warnings

async def main():
    output=Path('/tmp/dvsu-kie-adapter/proof.json')
    if output.exists(): raise SystemExit('Proof already attempted; inspect saved result')
    output.write_text(json.dumps({'state':'requesting','result':'unknown'}))
    executor=object.__new__(pe.PipelineExecutor)
    executor.tenant_id='561b872d-7b73-45e3-9c44-7f30c3566eda'
    package=await executor._gather_verified_machine_source_package(
        'Every US Strategic Bomber Ever Built (2026)','General Dynamics FB-111A Aardvark',
        {'machine_script_contract':'factual_100_v1'},
    )
    output.write_text(json.dumps(package,indent=2))
    print(json.dumps({'passed':package['passed'],'sources':len(package['sources']),
        'excerpts':len(package['candidate_excerpts']),'warnings':factual_package_contract_warnings(package['machine'],package),
        'discovery':package.get('source_discovery'),'production_write':False},indent=2))

asyncio.run(main())
