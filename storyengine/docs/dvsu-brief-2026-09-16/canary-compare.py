from pathlib import Path
import json
p=Path('docs/dvsu-brief-2026-09-16')
before=json.loads((p/'canary-before.json').read_text())
after=json.loads((p/'canary-after.json').read_text())
def obj(v):return json.loads(v) if isinstance(v,str) else v
b,a=obj(before['research_payload']),obj(after['research_payload'])
bp,ap=b['machine_raw_source_packages'],a['machine_raw_source_packages']
assert b['unit_roster']==a['unit_roster']
for key in bp:
 if key!='SS1':assert bp[key]==ap[key],f'Other machine package changed: {key}'
for key in ['sources','candidate_excerpts']:
 old,new=bp['SS1'].get(key,[]),ap['SS1'].get(key,[])
 assert new[:len(old)]==old,f'Original Holland {key} modified'
summary={'roster_unchanged':True,'other_machine_source_packages_unchanged':True,'original_holland_sources_preserved':True,
 'holland_sources_before':len(bp['SS1'].get('sources',[])),'holland_sources_after':len(ap['SS1'].get('sources',[])),
 'holland_excerpts_before':len(bp['SS1'].get('candidate_excerpts',[])),'holland_excerpts_after':len(ap['SS1'].get('candidate_excerpts',[])),
 'status_before':before['status'],'status_after':after['status'],'recorded_total_cost_before':before.get('total_cost'),'recorded_total_cost_after':after.get('total_cost')}
(p/'canary-integrity.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
