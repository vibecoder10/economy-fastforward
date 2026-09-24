#!/bin/bash
# watch.sh: runs forever; prints one line per NEW pending relay request in this workspace
# (not yet answered or announced). Meant for the Monitor tool.
cd "$(dirname "$0")"
touch answered.txt announced.txt
while true; do
  out=$(python3 mcp.py pending 2>/dev/null)
  echo "$out" | grep -v "^pending_total" | while read id stage rest; do
    [ -z "$id" ] && continue
    grep -qx "$id" answered.txt announced.txt 2>/dev/null && continue
    echo "$id" >> announced.txt
    echo "NEW $id $stage $rest"
  done
  sleep 20
done
