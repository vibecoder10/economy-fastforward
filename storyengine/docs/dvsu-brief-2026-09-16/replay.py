import json,sys
from pathlib import Path
sys.path.insert(0,str(Path('backend').resolve()))
from pipeline_executor import _verified_source_package_for_machine,_unit_display_name
from dvsu_research_handoff import package_brief
from factual_machine_summary import _script_writer_prompt
v=json.loads(Path('docs/script-compiler-2026-09-16/live-input.jsonl').read_text());v['research_payload']=json.loads(v['research_payload'])
rows=[]
for item in v["research_payload"]["unit_roster"]:
 machine=_unit_display_name(item)
 b=package_brief(machine,_verified_source_package_for_machine(v['research_payload'],machine),v['video_title'])
 prompt=_script_writer_prompt(b,[]) if b.get('ready') else ''
 rows.append({'machine':machine,'ready':b['ready'],'missing_fields':b['missing_fields'],'brief_words':len(json.dumps(b).split()),'brief_bytes':len(json.dumps(b,ensure_ascii=False,separators=(',',':')).encode()),'writer_prompt_words':len(prompt.split()) if prompt else None})
p=Path('docs/dvsu-brief-2026-09-16/replay.json');p.write_text(json.dumps(rows,indent=2))
print(json.dumps(rows,indent=2))
