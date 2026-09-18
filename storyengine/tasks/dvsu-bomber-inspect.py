import asyncio,json,sys
from pathlib import Path
ROOT=Path('/home/clawd/projects/economy-fastforward')
sys.path[:0]=[str(ROOT/'storyengine/backend'),str(ROOT/'skills/video-pipeline')]
from dotenv import load_dotenv
load_dotenv(ROOT/'storyengine/.env')
from arq.connections import create_pool
from arq.jobs import Job
from worker import WorkerSettings
async def main():
    redis=await create_pool(WorkerSettings.redis_settings)
    for attempt in (3,4,5):
        job=Job(f'autobuild:658e11e0-1f24-457e-95ef-3c8a0bd00f45:{attempt}',redis)
        result=await job.result_info() or await job.info()
        print(json.dumps({'attempt':attempt,'redis_status':str(await job.status()),'function':getattr(result,'function',None),'kwargs':getattr(result,'kwargs',None),'result':getattr(result,'result',None)},default=str))
    await redis.aclose()
asyncio.run(main())
