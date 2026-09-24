#!/bin/bash
# step.sh <request_id> [video_id]: post ans/<id>.json (or ans/<id>.txt), then wait for the next pending
# request and print it. No video_id = every pending request in this workspace.
cd "$(dirname "$0")"
VID="${2:-}"
f="ans/$1.json"; [ -f "$f" ] || f="ans/$1.txt"
python3 mcp.py answer "$1" "$f" | head -c 200; echo
echo "$1" >> answered.txt
for i in $(seq 1 30); do
  sleep 3
  out=$(python3 mcp.py pending $VID)
  next=$(echo "$out" | grep -v "^pending_total" | while read id rest; do grep -qx "$id" answered.txt || echo "$id $rest"; done)
  [ -n "$next" ] && { echo "$next"; exit 0; }
done
echo "NONE_PENDING"
