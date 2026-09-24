#!/bin/bash
# start.sh "<machine>" [video_id]: start research_machine, then wait for its first pending request.
cd "$(dirname "$0")"
VID="${2:-09debd56-6be0-4eb5-ad68-9cead8ba07f5}"
python3 -c "import mcp,sys;print(mcp.call('research_machine',{'video_id':sys.argv[1],'machine':sys.argv[2]}))" "$VID" "$1"
for i in $(seq 1 15); do sleep 3; out=$(python3 mcp.py pending "$VID"); echo "$out" | grep -q "pending_total 0" || { echo "$out"; exit 0; }; done
echo NONE_PENDING
