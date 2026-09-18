#!/usr/bin/env bash
# Parent-GO-only transport. The reviewed harness must first exist at the same
# canonical path on the VPS; it performs one referee call and no DB update.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec "$ROOT/scripts/se.sh" run '$HOME/projects/economy-fastforward/storyengine/backend/venv/bin/python3 $HOME/projects/economy-fastforward/storyengine/docs/plunger-purpose-2026-09-17/ss2-copyedit-referee.py --run'
