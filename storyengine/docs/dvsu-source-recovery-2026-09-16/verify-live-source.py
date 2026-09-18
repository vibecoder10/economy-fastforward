import json,subprocess,shlex
from pathlib import Path
code='''import asyncio,json,httpx
from pipeline_executor import PipelineExecutor,_sentence_candidates_from_source
from factual_machine_research import candidate_mentions_machine
from factual_source_search import guard_public_request
async def main():
 ex=PipelineExecutor.__new__(PipelineExecutor)
 url="https://navalunderseamuseum.org/undersea-pioneers2/"
 async with httpx.AsyncClient(timeout=30,follow_redirects=True,event_hooks={"request":[guard_public_request]}) as client:
  text=await ex._fetch_source_text(client,url)
  excerpts=_sentence_candidates_from_source(text,"SS-1 USS Holland",matcher=candidate_mentions_machine)
 result={"source_url":url,"capture_chars":len(text),"excerpt_count":len(excerpts),"training_recovered":any("as a training submarine" in e for e in excerpts),"all_exact_text":all(e in " ".join(text.split()) for e in excerpts),"excerpt_lengths":[len(e) for e in excerpts],"paid_provider_calls":0,"data_writes":0}
 print(json.dumps(result))
 assert result["training_recovered"] and result["all_exact_text"]
asyncio.run(main())'''
cmd='cd "$HOME/projects/economy-fastforward/storyengine/backend" && ./venv/bin/python -c '+shlex.quote(code)
r=subprocess.run(['./scripts/se.sh','run',cmd],capture_output=True,text=True)
Path('docs/dvsu-source-recovery-2026-09-16/live-source.json').write_text(r.stdout)
Path('docs/dvsu-source-recovery-2026-09-16/live-source.stderr').write_text(r.stderr)
print(r.stdout)
raise SystemExit(r.returncode)
