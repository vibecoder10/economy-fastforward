#!/bin/bash
# Exit (printing new request lines) as soon as a pending request appears that is not in dispatched.txt.
cd "$(dirname "$0")"
for i in $(seq 1 120); do
  out=$(python3 mcp.py pending "${VIDEO_ID:?set VIDEO_ID}" 2>&1)
  new=$(echo "$out" | grep _judge_via_relay\\\|_call\\\|research | while read id rest; do grep -q "${id:0:8}" dispatched.txt || echo "$id $rest"; done)
  if [ -n "$new" ]; then echo "$new"; exit 0; fi
  echo "$out" | grep -q "pending_total 0" && [ "$i" -gt 60 ] && { echo "NONE_PENDING"; exit 0; }
  sleep 10
done
echo TIMEOUT
