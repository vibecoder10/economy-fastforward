import json
from pathlib import Path
root=Path('/home/clawd/projects/economy-fastforward/storyengine/data/research-responses')
for path in sorted(root.glob('*.json'),key=lambda p:p.stat().st_mtime):
 data=json.loads(path.read_text())
 responses=data.get('responses',[])
 print(json.dumps({'file':path.name,'responses':len(responses),'stop_reasons':[r.get('stop_reason') for r in responses],'output_tokens':[(r.get('metadata',{}).get('usage') or {}).get('output_tokens') for r in responses],'text_lengths':[len(r.get('text','')) for r in responses]}))
