import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from research_claim_assessment import current_assessment
from machine_research_summary import research_summary_ready
p=json.loads((ROOT/'tasks/submarine-research-live-latest.json').read_text());payload=p['payload'];title='Every US Submarine Class Ever Built (2026)'
rows=[]
for name in p['names']:
 package=next((x for x in payload.get('machine_raw_source_packages',{}).values() if x.get('machine')==name),{})
 card=next((x for x in payload.get('unit_research_cards',[]) if x.get('unit')==name),{})
 assessment=current_assessment(name,package,title)
 summary=card.get('research_summary')or{}
 rows.append({'machine':name,'assessment_current':bool(assessment),'summary_current':research_summary_ready(name,package,summary,title),'warnings':summary.get('warnings')or package.get('claim_assessment',{}).get('warnings',[])})
result={'at':p['at'],'task':p['task'],'names_preserved':payload['recommended_final_roster']==p['names'],'images_verified':p['images']['verified'],'assessments_current':sum(x['assessment_current'] for x in rows),'summaries_current':sum(x['summary_current'] for x in rows),'rows':rows}
(ROOT/'tasks/submarine-research-live-validation.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
