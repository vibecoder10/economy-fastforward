#!/bin/bash
# Setup cron jobs for the Economy FastForward pipeline.
#
# Usage: bash setup_cron.sh
#
# This installs four cron jobs:
#   1. 5:00 AM  — Daily idea discovery scan (posts ideas to Slack for approval)
#   2. 8:00 AM  — Daily pipeline queue run (processes all stages through to Ready To Render)
#   3. Every 15 min — Bot health check (restarts Slack bot if it died, notifies you)
#   4. Every 30 min — Approval watcher (catches manual Airtable approvals)
#
# Times are in the system's local timezone.
# Logs are written to /tmp/pipeline-*.log
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
# Timeout: 10 minutes max (discovery should take <2 min)
0 5 * * * cd $REPO_DIR && git pull origin main --ff-only >> /tmp/pipeline-discover.log 2>&1; cd $PIPELINE_DIR && timeout 600 $PYTHON3 pipeline.py --discover >> /tmp/pipeline-discover.log 2>&1

# 8:00 AM — Daily pipeline queue run
# First processes any pending approvals, then runs all stages:
# Ready For Scripting → Script → Voice → Image Prompts → Images → Thumbnail → Ready To Render
# Timeout: 4 hours max (image generation can be slow)
0 8 * * * cd $REPO_DIR && git pull origin main --ff-only >> /tmp/pipeline-queue.log 2>&1; cd $PIPELINE_DIR && timeout 14400 $PYTHON3 pipeline.py --run-queue >> /tmp/pipeline-queue.log 2>&1

# Every 15 min — Slack bot health check
# Verifies pipeline_control.py is running. If it died, restarts it and sends alert.
# Without the bot, emoji reactions on discovery messages won't work.
*/15 * * * * cd $PIPELINE_DIR && bash bot_healthcheck.sh >> /tmp/pipeline-bot-health.log 2>&1

# Every 30 min — Approval watcher
# Catches ideas manually approved in Airtable (status set to "Approved")
# Runs research and advances to "Ready For Scripting" automatically
*/30 * * * * cd $PIPELINE_DIR && timeout 600 $PYTHON3 approval_watcher.py >> /tmp/pipeline-approval.log 2>&1
EOF
)

# Preserve any existing cron entries not from this script
EXISTING=$(crontab -l 2>/dev/null | grep -v "pipeline-discover\|pipeline-queue\|pipeline-bot-health\|pipeline-approval\|Pipeline Cron\|setup_cron\|Daily idea\|Daily pipeline\|bot health\|Approval watcher" || true)

# Install combined crontab
if [ -n "$EXISTING" ]; then
    echo "$EXISTING"$'\n'"$CRON_ENTRIES" | crontab -
else
    echo "$CRON_ENTRIES" | crontab -
fi

echo "  ✅ Cron jobs installed!"
echo ""
echo "  Scheduled:"
echo "    • 5:00 AM daily    → Discovery scan (post ideas to Slack)"
echo "    • 8:00 AM daily    → Pipeline queue (process all stages to render)"
echo "    • Every 15 min     → Bot health check (auto-restart if down)"
echo "    • Every 30 min     → Approval watcher (catch manual approvals)"
echo ""
echo "  Timeouts:"
echo "    • Discovery: 10 min max"
echo "    • Pipeline:  4 hours max"
echo "    • Approval:  10 min max"
echo ""
echo "  Logs:"
echo "    • /tmp/pipeline-discover.log"
echo "    • /tmp/pipeline-queue.log"
echo "    • /tmp/pipeline-bot-health.log"
echo "    • /tmp/pipeline-approval.log"
echo ""
echo "  Verify with: crontab -l"
echo "=================================================="
