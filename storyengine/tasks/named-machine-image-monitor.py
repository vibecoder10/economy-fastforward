import json,subprocess,time
from pathlib import Path
r=Path(__file__).resolve().parent
for poll in range(90):
 run=subprocess.run(['python3',str(r/'named-machine-image-live.py'),'compact'],capture_output=True,text=True)
 if run.returncode:
  print(json.dumps({'monitor_error':run.stderr[-700:]}),flush=True)
  break
 state=json.loads(run.stdout)
 print(json.dumps(state),flush=True)
 if state['task'] not in ('running','pending','queued'):
  break
 time.sleep(45)
