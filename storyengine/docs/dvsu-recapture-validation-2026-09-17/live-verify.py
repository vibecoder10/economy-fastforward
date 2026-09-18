import json, subprocess, urllib.request
from pathlib import Path
OUT=Path(__file__).parent
VIDEO="44dbf2b2-a27a-47ea-a608-4c31c906be9a"
TENANT="561b872d-7b73-45e3-9c44-7f30c3566eda"
token=subprocess.check_output(["./scripts/se.sh","token"],text=True).strip()
request=urllib.request.Request("https://storyengine.dev/api/pipeline/machine-script-preview-readiness/"+VIDEO, data=json.dumps({"machine":"SS-105 USS S-1"}).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","X-Active-Tenant":TENANT},method="POST")
with urllib.request.urlopen(request,timeout=90) as response:
    result=json.load(response)
(OUT/"live-readiness.json").write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k not in ["payload","research_payload"]},indent=2))
sql="SELECT json_build_object('id',v.id,'video_title',v.video_title,'headline',v.headline,'status',v.status,'render_mode',v.render_mode,'script',v.script,'script_validation',v.script_validation,'research_payload',v.research_payload,'max_spend',v.max_spend,'total_cost',v.total_cost,'updated_at',v.updated_at) AS snapshot FROM videos v WHERE v.id='"+VIDEO+"' AND v.tenant_id='"+TENANT+"';"
raw=subprocess.check_output(["./scripts/se.sh","db",sql],text=True)
(OUT/"live-after.jsonl").write_text(raw)
row=next(json.loads(line) for line in raw.splitlines() if line.lstrip().startswith("{"))
after=row["snapshot"]
if isinstance(after,str):after=json.loads(after)
if isinstance(after.get("research_payload"),str):after["research_payload"]=json.loads(after["research_payload"])
(OUT/"live-after-flat.json").write_text(json.dumps(after,indent=2))
before=json.loads((OUT/"live-before-flat.json").read_text())
bp,ap=before["research_payload"],after["research_payload"]
checks={"production_script_unchanged":before["script"]==after["script"],"all20_source_packages_unchanged":bp.get("machine_raw_source_packages")==ap.get("machine_raw_source_packages"),"roster_unchanged":bp.get("unit_roster")==ap.get("unit_roster"),"all_saved_previews_unchanged":bp.get("machine_script_previews")==ap.get("machine_script_previews"),"total_cost_unchanged":before["total_cost"]==after["total_cost"]}
report={"checks":checks,"passed":all(checks.values()),"scope":"single no-spend readiness POST; no script or research job"}
(OUT/"live-preservation.json").write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
assert report["passed"],"protected state changed"
assert result.get("preparable") or result.get("ready"),"SS105 is still blocked"
