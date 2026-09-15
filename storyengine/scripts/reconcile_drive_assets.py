"""Rehome registered Drive media left outside canonical video folders by legacy bots."""
import asyncio,json,sys,re
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from collections import defaultdict
from dotenv import load_dotenv
APP=Path(__file__).resolve().parents[1]
load_dotenv(APP/'.env');sys.path.insert(0,str(APP/'backend'));sys.path.insert(0,str(APP.parent/'skills'/'video-pipeline'))
from database import fetch_all,close_pool
from storage import _get_google_client
from drive_layout import children


def drive_id(url):
    if not isinstance(url,str): return None
    p=urlparse(url)
    if p.hostname in ('drive.google.com','docs.google.com'):
        value=(parse_qs(p.query).get('id') or [None])[0]
        m=re.search(r'/(?:file/)?d/([^/]+)',p.path)
        return value or (m.group(1) if m else None)
    m=re.search(r'/api/media/drive/([A-Za-z0-9_-]+)',p.path)
    return m.group(1) if m and p.hostname in ('storyengine.dev','localhost') else None


def batch(client, requests):
    results={}
    for start in range(0,len(requests),50):
        b=client.drive_service.new_batch_http_request()
        def receive(key,response,error):
            results[key]={'error':str(error)} if error else response
        for key,request in requests[start:start+50]: b.add(request,callback=receive,request_id=key)
        b.execute()
    return results

async def main():
    c=_get_google_client();apply='--apply' in sys.argv
    videos=await fetch_all('SELECT id,tenant_id,drive_folder_id,to_jsonb(v) AS data FROM videos v WHERE deleted_at IS NULL')
    rows=await fetch_all('SELECT s.video_id,to_jsonb(s) AS data FROM scripts s JOIN videos v ON v.id=s.video_id WHERE v.deleted_at IS NULL')
    rows+=await fetch_all('SELECT a.video_id,to_jsonb(a) AS data FROM assets a JOIN videos v ON v.id=a.video_id WHERE v.deleted_at IS NULL')
    rows += [{'video_id':v['id'],'data':v['data']} for v in videos]
    kinds={'voice_over_url':'Audio','sound_effect_url':'Audio','scene_video_url':'Video','video_url':'Video','video_clip_url':'Video','final_video_url':'Video','final_video_attachment_url':'Video','thumbnail_url':'Thumbnails','image_url':'Images','drive_image_url':'Images','storyboard_grid_url':'Images','storyboard_preview_url':'Images','core_image_url':'Images','character_reference_url':'References'}
    kinds.update({f'storyboard_{i}_url':'Images' for i in range(1,6)})
    uses=defaultdict(set)
    for row in rows:
        data=row['data'];data=json.loads(data) if isinstance(data,str) else data
        for key,kind in kinds.items():
            fid=drive_id(data.get(key))
            if fid:uses[fid].add((str(row['video_id']),kind))
    folders={}
    for v in videos:
        if v['drive_folder_id']:
            folders[str(v['id'])]={x['name'].lower():x['id'] for x in children(c,v['drive_folder_id'])}
            data=json.loads(v['data']) if isinstance(v['data'],str) else v['data']
            other=folders[str(v['id'])].get('other assets')
            if other:
                for doc in children(c,other):
                    if doc['mimeType']=='application/vnd.google-apps.document' and doc['name']==data.get('video_title'):
                        uses[doc['id']].add((str(v['id']),'Script'))

    service=c.drive_service.files()
    records=batch(c,[(fid,service.get(fileId=fid,fields='id,name,parents,mimeType')) for fid in uses])
    moves=[];missing=[];shared=[];already=0
    for fid,owners in uses.items():
        record=records[fid]
        if record.get('error'):
            missing.append({'id':fid,'error':record['error']});continue
        if len({vid for vid,kind in owners})>1:
            shared.append({'id':fid,'uses':sorted(owners)});continue
        vid,kind=sorted(owners)[0]
        target=folders.get(vid,{}).get(kind.lower())
        if not target: raise RuntimeError('Missing canonical folder '+vid+' '+kind)
        parents=record.get('parents',[])
        if parents==[target]:already+=1;continue
        moves.append({'id':fid,'video':vid,'name':record['name'],'from':parents,'to':target})
    print(json.dumps({'plan':moves,'already_correct':already,'missing':missing,'shared':shared}),flush=True)
    if apply:
        result=batch(c,[(m['id'],service.update(fileId=m['id'],addParents=m['to'],removeParents=','.join(p for p in m['from'] if p!=m['to']),fields='id,parents')) for m in moves])
        failures=[{'id':m['id'],'result':result[m['id']]} for m in moves if result[m['id']].get('parents')!=[m['to']]]
        print(json.dumps({'moved':len(moves)-len(failures),'failures':failures,'missing_count':len(missing),'shared_count':len(shared)}),flush=True)
        if failures:raise RuntimeError('Some asset moves failed')
    await close_pool()

if __name__=='__main__':asyncio.run(main())
