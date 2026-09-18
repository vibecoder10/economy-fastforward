"""Offline, human-reviewed source brief; never creates a provider assessment."""
import hashlib,json,sys,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from dvsu_script_brief import build_dvsu_brief,brief_warnings
OUT=Path(__file__).resolve().parent
museum=json.loads((ROOT/'docs/dvsu-source-recovery-2026-09-16/recovered-source-receipt.json').read_text())
congress=(OUT/'congress-page-77-raw.txt').read_text()
q1='I consider her dura-\nble, habitable, and reliable as a. vessel of war for coast and harbor defense.'
assert q1 in congress
facts=[
 {'fact_id':'F1','claim':'Holland’s commander advocated her use as a war vessel for coast and harbor defense.','scope':'Contemporary operational promise, not proof of the original procurement requirement or combat success.','narrative_roles':['intended_role']},
 {'fact_id':'F2','claim':'Holland combined dual propulsion, separate main and auxiliary ballast systems, and a hydrodynamic hull shape.','scope':'Documented design features of USS Holland.','narrative_roles':['design']},
 {'fact_id':'F3','claim':'Holland served at the U.S. Naval Academy as a training submarine.','scope':'Actual service; omit disputed duration.','narrative_roles':['actual_use']},
 {'fact_id':'F4','claim':'Improved Holland-type submarines became the Navy’s A-class.','scope':'Design successors; omit disputed boat count.','narrative_roles':['outcome']},
]
evidence={
 'status':'local human-reviewed evidence; not a production claim assessment',
 'machine':'SS-1 USS Holland',
 'sources':[
  {'id':'C1','url':'https://www.govinfo.gov/content/pkg/GPO-CRECB-1901-pt4-v34/pdf/GPO-CRECB-1901-pt4-v34-2.pdf','local_file':'congress-1901.pdf','sha256':hashlib.sha256((OUT/'congress-1901.pdf').read_bytes()).hexdigest(),'locator':'PDF page77 / printed Congressional Record House3089, lower left column; continuation upper right','attribution':'Extract from Lieutenant Caldwell letter dated January12,1901 to R.B.Hawley, read by Mr.Cummings','visual_review':'Original full page inspected; OCR errors preserved in extracted quote. Visual text reads durable and as a vessel, not dura-/a.'},
  {'id':'M1','url':museum['source_url'],'local_file':'../dvsu-source-recovery-2026-09-16/undersea.html','locator':'John Philip Holland heading; exact section preserved by deployed extractor'}
 ],
 'facts':[
  {**facts[0],'source_id':'C1','source_quote':q1,'quote_type':'exact PDF extraction, including OCR and line breaks','visual_reading':'I consider her durable, habitable, and reliable as a vessel of war for coast and harbor defense.'},
  {**facts[1],'source_id':'M1','source_quote':museum['design_quote'],'quote_type':'exact normalized visible HTML'},
  {**facts[2],'source_id':'M1','source_quote':museum['actual_use_quote'],'quote_type':'exact normalized visible HTML'},
  {**facts[3],'source_id':'M1','source_quote':museum['outcome_quote'],'quote_type':'exact normalized visible HTML'},
 ],
 'exclusions':['No claim that Holland failed in combat or was reassigned because of a failure.','No purchase price, service duration, successor count or Roosevelt ride; conflicting or misattributed source details excluded.','Smithsonian403 and Navy TLS failure bodies are not evidence.','Promoted role substitutes for unsupported original procurement intent; keep this wording in any later assessment.']}
for row in evidence['facts'][1:]: assert row['source_quote'] in museum['excerpts'][0]
packet={'machine':'SS-1 USS Holland','subject_context':'Every US Submarine Class Ever Built','facts':facts}
brief=build_dvsu_brief(packet)
encode=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
assert brief['ready'] and not brief_warnings(brief)
permuted=copy.deepcopy(packet);permuted['facts'].reverse()
assert encode(brief)==encode(build_dvsu_brief(permuted))==encode(build_dvsu_brief(packet))
assert all(word not in encode(brief) for word in ['source_quote','source_url','govinfo','navalunderseamuseum'])
script=("USS Holland was promoted as a weapon for coast and harbor defense. "
"Dual propulsion, separate ballast systems and a hydrodynamic hull brought the design together. "
"But in service, that underwater weapon also became a classroom. "
"At the U.S. Naval Academy, Holland served as a training submarine. "
"Improved Holland-type boats followed as the A-class. "
"The payoff was larger than one boat defending one harbor: Holland gave the Navy a working submarine to learn from, and a design to improve. "
"Her importance lay in what came next—training people to operate underwater and helping establish the pattern for the boats that followed.")
count=len(script.split());assert 80<=count<=110
receipt={'human_review':'PASS for local four-field example','writer_claim_words':sum(len(f['claim'].split()) for f in facts),'writer_brief_bytes':len(encode(brief).encode()),'writer_brief_words':len(encode(brief).split()),'script_words':count,'repeated_and_reordered_output_identical':True,'four_fields_present':True,'brief_sha256':hashlib.sha256(encode(brief).encode()).hexdigest(),'live_data_writes':0,'paid_provider_calls':0,'production_assessment_pass_created':False,'production_preview_created':False,'sentence_fact_map':[['F1'],['F2'],['F1','F3'],['F3'],['F4'],['F1','F3','F4'],['F3','F4']],'editorial_interpretations':['Classroom is a metaphor for documented training.','Final contribution verdict synthesizes training and design succession; it does not assert combat failure.'],'remaining_app_gap':'Only the pure brief builder was exercised with human-reviewed local facts. Normal source ingestion, current assessment and factual/editorial provider preview were not run. PDF evidence is page77, beyond current first8page source fetch. No production-ready claim.'}
for filename,value in [('evidence.json',evidence),('local-fact-packet.json',packet),('writer-brief.json',brief),('verification.json',receipt)]: (OUT/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
(OUT/'script-example.txt').write_text(script+'\n')
(OUT/'BRIEF.md').write_text('''# Holland: source-backed local brief

Status: human-reviewed local research/example. Not saved to StoryEngine or passed through its provider review.

| Field | Writer fact |
|---|---|
'''+''.join('| '+f['narrative_roles'][0]+' | '+f['claim']+' |\n' for f in facts)+'''
The first field is explicitly the operational role advocated by Holland’s commander; it is not proof of the original procurement requirement. This supported framing avoids inventing intent or a combat failure.

Sources: [Congressional Record, printed page3089 / PDF page77](https://www.govinfo.gov/content/pkg/GPO-CRECB-1901-pt4-v34/pdf/GPO-CRECB-1901-pt4-v34-2.pdf#page=77), [Naval Undersea Museum](https://navalunderseamuseum.org/undersea-pioneers2/). Exact extracted quotations, attribution and limits are in evidence.json. Original congressional page visually verified; OCR errors retained separately from the visual reading. Failed Smithsonian403/Navy TLS captures excluded.

## Manual editorial example ('''+str(count)+''' words)

'''+script+'''

## Deterministic check and limits

Four claims contain '''+str(receipt['writer_claim_words'])+''' words. The real build_dvsu_brief function produces all four fields in '''+str(receipt['writer_brief_bytes'])+''' UTF-8 bytes, with identical output on repeat and reversed fact order. Sources and quotations stay in evidence.json, outside the writer payload. This demonstrates that 2,000 research words are unnecessary for this example.

This is local research and an editorial example, not a generated production preview. No paid calls, live card updates, code changes or deployment occurred. The next app step is explicit page-targeted ingestion and normal source assessment before preview: the Congressional evidence is on page77, beyond the current first8page PDF extractor. Do not silently truncate the PDF, forge an assessment, or call this end-to-end verification.
''')
print(json.dumps(receipt,indent=2))
