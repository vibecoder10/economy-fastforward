#!/bin/bash
# Setup cron jobs for the Economy FastForward pipeline.
#
# Usage: bash setup_cron.sh
#
# This installs two cron jobs:
#   1. 5:00 AM — Daily idea discovery scan (finds new video ideas from headlines)
#              Sends interactive Slack message with emoji reactions for idea selection
#   2. 8:00 AM — Daily pipeline queue run (processes all queued videos to completion)
#              Scans all tables, runs every stage from scripting through to Ready To Render
#
# Times are in the system's local timezone.
# Logs are written to /tmp/pipeline-discover.log and /tmp/pipeline-queue.log
#
# To view installed cron jobs: crontab -l
# To remove all cron jobs:    crontab -r

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PIPELINE_DIR="$SCRIPT_DIR"
PYTHON3="$(which python3)"

echo "=================================================="
echo "  Pipeline Cron Job Setup"
echo "=================================================="
echo ""
echo "  Repo dir:     $REPO_DIR"
echo "  Pipeline dir: $PIPELINE_DIR"
echo "  Python:       $PYTHON3"
echo ""

# Build the crontab entries
CRON_ENTRIES=$(cat <<EOF
# Economy FastForward Pipeline Cron Jobs
# Installed by setup_cron.sh — $(date)

# 5:00 AM — Daily idea discovery scan
# Pulls latest code, then runs discovery scanner to find new video ideas
# Posts interactive Slack message with emoji reactions so you wake up and choose an idea
0 5 * * * cd $REPO_DIR && git pull origin main --ff-only >> /tmp/pipeline-discover.log 2>&1; cd $PIPELINE_DIR && $PYTHON3 pipeline.py --discover >> /tmp/pipeline-discover.log 2>&1

# 8:00 AM — Daily pipeline queue run
# Scans all Airtable tables and processes every video through ALL stages:
# Ready For Scripting → Script → Voice → Image Prompts → Images → Thumbnail → Ready To Render
# Continues until all queued work is complete
0 8 * * * cd $REPO_DIR && git pull origin main --ff-only >> /tmp/pipeline-queue.log 2>&1; cd $PIPELINE_DIR && $PYTHON3 pipeline.py --run-queue >> /tmp/pipeline-queue.log 2>&1
EOF
)

# Preserve any existing cron entries not from this script
EXISTING=$(crontab -l 2>/dev/null | grep -v "pipeline-discover\|pipeline-queue\|Pipeline Cron\|setup_cron\|Daily idea discovery\|Daily pipeline queue" || true)

# Install combined crontab
if [ -n "$EXISTING" ]; then
    echo "$EXISTING"$'\n'"$CRON_ENTRIES" | crontab -
else
    echo "$CRON_ENTRIES" | crontab -
fi

echo "  ✅ Cron jobs installed!"
echo ""
echo "  Scheduled:"
echo "    • 5:00 AM daily → python3 pipeline.py --discover"
echo "    • 8:00 AM daily → python3 pipeline.py --run-queue"
echo ""
echo "  Logs:"
echo "    • /tmp/pipeline-discover.log"
echo "    • /tmp/pipeline-queue.log"
echo ""
echo "  Verify with: crontab -l"
echo "=================================================="
