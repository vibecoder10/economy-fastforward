#!/bin/bash
# undispatched.sh: pending requests not yet handed to a helper (dispatched.txt); saves each to req/.
cd "$(dirname "$0")"
touch dispatched.txt
python3 mcp.py pending | grep -v pending_total | while read id stage rest; do grep -q "$id" dispatched.txt || echo "$id $stage $rest"; done
