#!/bin/bash
# step.sh <request_id> [video_id]: post ans/<id>.json, then wait for the next pending request and print it.
cd "$(dirname "$0")"
VID="${2:-09debd56-6be0-4eb5-ad68-9cead8ba07f5}"
python3 mcp.py answer "$1" "ans/$1.json" | head -c 200; echo
for i in $(seq 1 15); do
  sleep 3
  out=$(python3 mcp.py pending "$VID")
  echo "$out" | grep -v "^pending_total" | grep -qv "$1" && { echo "$out"; exit 0; }
done
echo "NONE_PENDING"; echo "$out"
