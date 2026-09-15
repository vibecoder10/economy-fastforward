"""Inventory or organize registered StoryEngine channel/video folders; no sharing changes."""
import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

APP = Path(__file__).resolve().parents[1]
load_dotenv(APP / '.env')
sys.path.insert(0, str(APP / 'backend'))
sys.path.insert(0, str(APP.parent / 'skills' / 'video-pipeline'))
from database import fetch_all, execute, close_pool
from storage import _get_google_client
from drive_layout import channel_folder, video_layout, tidy_video, children
from drive_workspace import _workspace_folder_name

async def main():
    apply = '--apply' in sys.argv
    client = _get_google_client()
    profiles = await fetch_all('SELECT tenant_id,channel_name,youtube_channel_name FROM channel_profiles ORDER BY tenant_id')
    videos = await fetch_all('SELECT id,tenant_id,video_title,drive_folder_id FROM videos WHERE deleted_at IS NULL ORDER BY tenant_id,id')
    ids = [v['drive_folder_id'] for v in videos if v['drive_folder_id']]
    if len(ids) != len(set(ids)):
        raise RuntimeError('Shared video folders require reconciliation before moving')
    errors = []
    names = {str(p['tenant_id']): p['channel_name'] or p['youtube_channel_name'] or '' for p in profiles}
    if apply:
        for tenant, name in names.items():
            folder = await asyncio.to_thread(channel_folder, client, tenant, name)
            print(json.dumps({'channel':tenant,'name':name,'folder':folder}),flush=True)
    async def organize(v):
        v['tenant_id'] = str(v['tenant_id']);v['id'] = str(v['id'])
        v['channel_name'] = names.get(v['tenant_id'], '')
        try:
            before = None
            if v['drive_folder_id']:
                before = await asyncio.to_thread(lambda: client.drive_service.files().get(fileId=v['drive_folder_id'],fields='id,name,parents').execute())
            print(json.dumps({'before': v, 'folder':before}),flush=True)
            if not apply:
                return
            channel, folder, types = await asyncio.to_thread(video_layout,client,v,_workspace_folder_name(v['video_title'] or 'Untitled',v['id']))
            changes = await asyncio.to_thread(tidy_video,client,folder,types)
            await execute('UPDATE videos SET drive_folder_id=$1,drive_folder_link=$2 WHERE id=$3 AND tenant_id=$4',folder,'https://drive.google.com/drive/folders/'+folder,v['id'],v['tenant_id'])
            after = await asyncio.to_thread(lambda: client.drive_service.files().get(fileId=folder,fields='id,parents').execute())
            assert after['parents']==[channel]
            remaining = await asyncio.to_thread(children,client,folder)
            assert all(x['id'] in types.values() for x in remaining)
            print(json.dumps({'verified':v['id'],'channel_folder':channel,'video_folder':folder,'types':types,'moves':changes}),flush=True)
        except Exception as e:
            errors.append({'video':v['id'],'error':str(e)})
            print(json.dumps(errors[-1]),flush=True)
    semaphore = asyncio.Semaphore(4)
    async def bounded(v):
        async with semaphore:
            await organize(v)
    await asyncio.gather(*(bounded(v) for v in videos))
    print(json.dumps({'complete':not errors,'videos':len(videos),'channels':len(names),'errors':errors}),flush=True)
    await close_pool()
    if errors:sys.exit(1)

asyncio.run(main())
