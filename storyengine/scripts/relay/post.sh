#!/bin/bash
# post.sh <request_id>: check candidate ids match the request, then post the answer file.
cd "$(dirname "$0")"
python3 -c "
import json,re,sys
r=json.load(open('req/$1.json'));a=json.load(open('ans/$1.json'))
want=sorted(set(re.findall(r'\{\"id\": \"(c\d+)\"',r['prompt'])));got=sorted(c['id'] for c in a['candidates'])
sys.exit(0 if want==got else 'ID MISMATCH %s vs %s'%(want,got))" && python3 mcp.py answer "$1" "ans/$1.json"
