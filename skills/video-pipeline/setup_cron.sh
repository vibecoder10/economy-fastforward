#!/bin/bash
# Setup cron jobs for the Economy FastForward pipeline.
#
# Usage: bash setup_cron.sh
#
# This installs five cron jobs:
#   1. 5:00 AM  — Daily idea discovery scan (posts ideas to Slack for approval)
#   2. 7:00 AM  — Daily YouTube performance tracker (syncs analytics to Airtable)
#   3. 8:00 AM  — Daily pipeline queue run (processes all stages through to Ready To Render)
#   4. Every 15 min — Bot health check (restarts Slack bot if it died, notifies you)
#   5. Every 30 min — Approval watcher (catches manual Airtable approvals)
#
# Times are in US/Pacific (America/Los_Angeles) via TZ env var.
# Logs are written to /tmp/pipeline-*.log
# All jobs use cron_wrapper.sh for: env setup, locking, Slack failure alerts.
#
# To view installed cron jobs: crontab -l
# To remove all cron jobs:    crontab -r

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PIPELINE_DIR="$SCRIPT_DIR"
WRAPPER="$PIPELINE_DIR/cron_wrapper.sh"

# Detect Python — prefer the pipeline venv, fall back to repo venv, then system
detect_python() {
    local candidates=(
        "/home/clawd/pipeline-bot/venv/bin/python"
        "$REPO_DIR/venv/bin/python"
        "$PIPELINE_DIR/venv/bin/python"
    )
    for candidate in "${candidates[@]}"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    echo "python3"
}

PYTHON3=$(detect_python)

# Detect system timezone to determine correct cron schedule hours
# CRON_TZ is NOT supported on Debian/Ubuntu (vixie-cron), so we must
# convert Pacific times to system-local times.
SYS_TZ=$(cat /etc/timezone 2>/dev/null || timedatectl show --property=Timezone --value 2>/dev/null || echo "unknown")

# Check if system timezone is Pacific — if so, use times as-is
if echo "$SYS_TZ" | grep -qiE "america/los_angeles|US/Pacific"; then
    TZ_MODE="pacific"
    DISCOVER_HOUR=5
    PERF_HOUR=7
    QUEUE_HOUR=8
elif echo "$SYS_TZ" | grep -qiE "UTC|Etc/UTC|Etc/GMT"; then
    TZ_MODE="utc"
    # Pacific to UTC: PST = UTC-8, PDT = UTC-7
    # Use PST offsets (conservative — jobs run 1h later in summer)
    DISCOVER_HOUR=13   # 5 AM PT = 1 PM UTC (PST)
    PERF_HOUR=15       # 7 AM PT = 3 PM UTC (PST)
    QUEUE_HOUR=16      # 8 AM PT = 4 PM UTC (PST)
else
    # Unknown timezone — default to UTC offsets and warn
    TZ_MODE="other ($SYS_TZ)"
    DISCOVER_HOUR=13
    PERF_HOUR=15
    QUEUE_HOUR=16
fi

echo "=================================================="
echo "  Pipeline Cron Job Setup"
echo "=================================================="
echo ""
echo "  Repo dir:     $REPO_DIR"
echo "  Pipeline dir: $PIPELINE_DIR"
echo "  Python:       $PYTHON3"
echo "  Wrapper:      $WRAPPER"
echo "  System TZ:    $SYS_TZ (mode: $TZ_MODE)"
echo "  Schedule:     discover=$DISCOVER_HOUR:00, perf=$PERF_HOUR:00, queue=$QUEUE_HOUR:00"
echo ""

# Verify wrapper exists
if [ ! -f "$WRAPPER" ]; then
    echo "ERROR: cron_wrapper.sh not found at $WRAPPER"
    echo "This file is required for cron jobs to work properly."
    exit 1
fi
chmod +x "$WRAPPER"

# Build the crontab entries
# Hours are computed above based on system timezone (Pacific direct or UTC-converted)
# MAX_LOCK_AGE prevents stale locks from blocking jobs forever
CRON_ENTRIES=$(cat <<EOF
# Economy FastForward Pipeline Cron Jobs
# Installed by setup_cron.sh — $(date)
# System timezone: $SYS_TZ (mode: $TZ_MODE)

# Force bash shell (cron defaults to /bin/sh which may not handle our syntax)
SHELL=/bin/bash

# Ensure standard tools (timeout, git, curl, jq) are on PATH
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# TZ for log timestamps — shows Pacific time in logs regardless of system tz
TZ=America/Los_Angeles

# $DISCOVER_HOUR:00 (~5 AM PT) — Daily idea discovery scan
# Finds new video ideas and posts interactive Slack message for approval
# Timeout: 10 min max | Lock expires after 15 min
0 $DISCOVER_HOUR * * * MAX_LOCK_AGE=900 $WRAPPER discovery /tmp/pipeline-discover.log timeout 600 python pipeline.py --discover

# $PERF_HOUR:00 (~7 AM PT) — Daily YouTube performance tracker
# Syncs YouTube metrics (views, CTR, retention, snapshots) to Airtable
# Timeout: 10 min max | Lock expires after 15 min
0 $PERF_HOUR * * * MAX_LOCK_AGE=900 $WRAPPER performance /tmp/performance-tracker.log timeout 600 python performance_tracker.py --recent

# $QUEUE_HOUR:00 (~8 AM PT) — Daily pipeline queue run
# Processes all stages: Script → Voice → Image Prompts → Images → Thumbnail → Render → Upload
# Timeout: 4 hours max | Lock expires after 5 hours
0 $QUEUE_HOUR * * * MAX_LOCK_AGE=18000 $WRAPPER pipeline-queue /tmp/pipeline-queue.log timeout 14400 python pipeline.py --run-queue

# Every 15 min — Slack bot health check
# Verifies pipeline_control.py is running. If it died, restarts it and sends alert.
*/15 * * * * cd $PIPELINE_DIR && bash bot_healthcheck.sh >> /tmp/pipeline-bot-health.log 2>&1

# Every 30 min — Approval watcher
# Catches ideas manually approved in Airtable (status set to "Approved")
# Lock expires after 15 min
*/30 * * * * MAX_LOCK_AGE=900 $WRAPPER approvals /tmp/pipeline-approval.log timeout 600 python approval_watcher.py
EOF
)

# Preserve any existing cron entries not from this script
EXISTING=$(crontab -l 2>/dev/null | grep -v "pipeline-discover\|pipeline-queue\|pipeline-bot-health\|pipeline-approval\|performance-tracker\|pipeline\.log\|Pipeline Cron\|setup_cron\|Daily idea\|Daily pipeline\|performance tracker\|bot health\|Approval watcher\|run-queue\|--discover\|performance_tracker\|cron_wrapper" || true)

# Install combined crontab
if [ -n "$EXISTING" ]; then
    echo "$EXISTING"$'\n'"$CRON_ENTRIES" | crontab -
else
    echo "$CRON_ENTRIES" | crontab -
fi

echo "  Cron jobs installed!"
echo ""
echo "  Scheduled (system time $SYS_TZ → ~Pacific equivalent):"
echo "    $DISCOVER_HOUR:00 daily (~5 AM PT) ->  Discovery scan (post ideas to Slack)"
echo "    $PERF_HOUR:00 daily (~7 AM PT)     ->  YouTube performance tracker (sync analytics)"
echo "    $QUEUE_HOUR:00 daily (~8 AM PT)    ->  Pipeline queue (process all stages to render)"
echo "    Every 15 min            ->  Bot health check (auto-restart if down)"
echo "    Every 30 min            ->  Approval watcher (catch manual approvals)"
echo ""
echo "  Failure alerts:"
echo "    All jobs (except healthcheck) send Slack notifications on failure."
echo "    Check your Slack channel if you don't see morning activity."
echo ""
echo "  Timeouts:"
echo "    Discovery:    10 min max"
echo "    Performance:  10 min max"
echo "    Pipeline:     4 hours max"
echo "    Approval:     10 min max"
echo ""
echo "  Logs:"
echo "    /tmp/pipeline-discover.log"
echo "    /tmp/performance-tracker.log"
echo "    /tmp/pipeline-queue.log"
echo "    /tmp/pipeline-bot-health.log"
echo "    /tmp/pipeline-approval.log"
echo ""
# ── Verify cron daemon is running ─────────────────────────────────────
if pgrep -x "cron" > /dev/null 2>&1 || pgrep -x "crond" > /dev/null 2>&1; then
    echo "  Cron daemon: RUNNING"
else
    echo "  ⚠️  WARNING: Cron daemon is NOT running!"
    echo "     Jobs are installed but will NOT fire until cron is started."
    echo "     Start it with:"
    echo "       sudo systemctl start cron && sudo systemctl enable cron"
    echo ""
fi

echo "  Verify with: crontab -l"
echo "  Diagnose:    bash diagnose_cron.sh"
echo "=================================================="
