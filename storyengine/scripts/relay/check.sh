#!/bin/bash
# check.sh [video_id]: list machines whose research verdict is no longer pending.
cd "$(dirname "$0")/../.."
VID="${1:-09debd56-6be0-4eb5-ad68-9cead8ba07f5}"
scripts/se.sh db "select e->>'machine' m, e->>'passed' p, e->>'warnings' w from videos, jsonb_array_elements(research_payload->'unit_research_hold_validation'->'units') e where id='$VID' and e->>'warnings' not like '%pending%'"
