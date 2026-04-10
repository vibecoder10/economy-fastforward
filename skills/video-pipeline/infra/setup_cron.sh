#!/bin/bash
# Setup cron jobs for the Economy FastForward pipeline.
#
# Usage: bash infra/setup_cron.sh   (from skills/video-pipeline/)
#
# This installs ten cron jobs:
#   1. 5:00 AM  — Osiris competitor scraper (persists ALL competitor videos to training table)
#   2. 6:30 AM  — Autopilot decision cycle (score ideas, select best, notify Slack)
#   3. 7:00 AM  — Daily YouTube performance tracker (syncs analytics to Airtable)
#   4. 7:30 AM  — Osiris performance analyzer (48h/7d post-mortems + learnings)
#   5. 7:45 AM  — Autopilot CTR monitor (early warnings for underperforming videos)
#   6. 8:30 AM  — Autopilot learning extractor (extract patterns from 48h+ videos)
#   7. 9:00 AM  — Daily idea discovery scan (posts ideas to Slack for approval)
#   8. 12:00 PM — Daily pipeline queue run (processes all stages through to render)
#   9. Every 15 min — Bot health check (restarts Slack bot if it died)
#  10. Every 30 min — Approval watcher (catches manual Airtable approvals)
#  11. Every 30 min — StoryEngine auto-deploy (rebuild frontend + restart backend on code changes)
#
# Times are in US/Pacific (America/Los_Angeles).
# Logs are written to /tmp/pipeline-*.log
# All jobs use cron_wrapper.sh for: env setup, locking, Slack failure alerts.
#
# To view installed cron jobs: crontab -l
# To remove all cron jobs:    crontab -r

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PIPELINE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WRAPPER="$SCRIPT_DIR/cron_wrapper.sh"

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
    OSIRIS_HOUR=5
    DISCOVER_HOUR=9
    PERF_HOUR=7
    QUEUE_HOUR=12
elif echo "$SYS_TZ" | grep -qiE "UTC|Etc/UTC|Etc/GMT"; then
    TZ_MODE="utc"
    # Pacific to UTC: PST = UTC-8, PDT = UTC-7
    # Use PST offsets (conservative — jobs run 1h later in summer)
    OSIRIS_HOUR=13     # 5 AM PT = 1 PM UTC (PST)
    DISCOVER_HOUR=17   # 9 AM PT = 5 PM UTC (PST)
    PERF_HOUR=15       # 7 AM PT = 3 PM UTC (PST)
    QUEUE_HOUR=20      # 12 PM PT = 8 PM UTC (PST)
else
    # Unknown timezone — default to UTC offsets and warn
    TZ_MODE="other ($SYS_TZ)"
    OSIRIS_HOUR=13
    DISCOVER_HOUR=17
    PERF_HOUR=15
    QUEUE_HOUR=20
fi

echo "=================================================="
echo "  Pipeline Cron Job Setup"
echo "=================================================="
echo ""
echo "  Repo dir:     $REPO_DIR"
echo "  Pipeline dir: $PIPELINE_DIR"
echo "  Infra dir:    $SCRIPT_DIR"
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
#
# NOTE: All python commands run from PIPELINE_DIR (skills/video-pipeline/).
# Module paths use the reorganized structure (March 2026):
#   orchestrator/pipeline.py    — main pipeline router
#   analytics/                  — performance_tracker, osiris
#   autopilot/                  — autonomous brain
#   orchestrator/               — approval_watcher
CRON_ENTRIES=$(cat <<EOF
# Economy FastForward Pipeline Cron Jobs
# Installed by infra/setup_cron.sh — $(date)
# System timezone: $SYS_TZ (mode: $TZ_MODE)

# Force bash shell (cron defaults to /bin/sh which may not handle our syntax)
SHELL=/bin/bash

# Ensure standard tools (timeout, git, curl, jq) are on PATH
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# TZ for log timestamps — shows Pacific time in logs regardless of system tz
TZ=America/Los_Angeles

# $OSIRIS_HOUR:00 (~5 AM PT) — Osiris competitor video scraper
# Scrapes ALL competitor videos and persists to Competitor Videos table
# Builds training data for topic/title performance analysis over time
# Timeout: 10 min max | Lock expires after 15 min
0 $OSIRIS_HOUR * * * MAX_LOCK_AGE=900 $WRAPPER osiris /tmp/osiris-scraper.log timeout 600 python -m analytics.osiris.competitor_scraper

# $(($OSIRIS_HOUR + 1)):30 (~6:30 AM PT) — Autopilot decision cycle
# Checks cadence, scores candidates, selects best idea, notifies Slack
# Runs BEFORE pipeline queue so overrides are set before production
# Timeout: 15 min max | Lock expires after 20 min
30 $(($OSIRIS_HOUR + 1)) * * * MAX_LOCK_AGE=1200 $WRAPPER autopilot-cycle /tmp/autopilot-cycle.log timeout 900 python -m autopilot.autopilot --check-cycle

# $PERF_HOUR:00 (~7 AM PT) — Daily YouTube performance tracker
# Syncs YouTube metrics (views, CTR, retention, snapshots) to Airtable
# Timeout: 10 min max | Lock expires after 15 min
0 $PERF_HOUR * * * MAX_LOCK_AGE=900 $WRAPPER performance /tmp/performance-tracker.log timeout 600 python analytics/performance_tracker.py --recent

# $PERF_HOUR:30 (~7:30 AM PT) — Osiris performance analyzer (post-mortems)
# Runs AFTER performance_tracker so metrics are fresh
# Analyzes videos at 48h/7d milestones, extracts learnings for prompt injection
# Timeout: 10 min max | Lock expires after 15 min
30 $PERF_HOUR * * * MAX_LOCK_AGE=900 $WRAPPER osiris-analyze /tmp/osiris-analyze.log timeout 600 python -m analytics.osiris analyze

# $PERF_HOUR:45 (~7:45 AM PT) — Autopilot CTR monitor
# Monitors CTR at 6h/24h/48h milestones for videos in "monitoring" state
# Sends early warning alerts to Slack for underperforming videos
# Timeout: 10 min max | Lock expires after 15 min
45 $PERF_HOUR * * * MAX_LOCK_AGE=900 $WRAPPER autopilot-ctr /tmp/autopilot-ctr.log timeout 600 python -m autopilot.monitoring.ctr_monitor --check-active

# $(($PERF_HOUR + 1)):30 (~8:30 AM PT) — Autopilot learning extractor
# Extracts patterns from 48h+ videos and updates memory files
# Runs AFTER performance metrics are fresh
# Timeout: 10 min max | Lock expires after 15 min
30 $(($PERF_HOUR + 1)) * * * MAX_LOCK_AGE=900 $WRAPPER autopilot-learn /tmp/autopilot-learn.log timeout 600 python -m autopilot.learning.learning_extractor --daily

# $DISCOVER_HOUR:00 (~9 AM PT) — Daily idea discovery scan
# Scans world news headlines + competitor top performers (50/50 split)
# Posts interactive Slack message with both idea types for approval
# Timeout: 15 min max | Lock expires after 20 min (includes competitor scrape)
0 $DISCOVER_HOUR * * * MAX_LOCK_AGE=1200 $WRAPPER discovery /tmp/pipeline-discover.log timeout 900 python orchestrator/pipeline.py --discover

# $QUEUE_HOUR:00 (~12 PM PT) — Daily pipeline queue run
# Processes all stages: Script → Voice → Image Prompts → Images → Thumbnail → Render → Upload
# Timeout: 4 hours max | Lock expires after 5 hours
0 $QUEUE_HOUR * * * MAX_LOCK_AGE=18000 $WRAPPER pipeline-queue /tmp/pipeline-queue.log timeout 14400 python orchestrator/pipeline.py --run-queue

# Every 15 min — Slack bot health check
# Verifies pipeline_control.py is running. If it died, restarts it and sends alert.
*/15 * * * * cd $PIPELINE_DIR && bash infra/bot_healthcheck.sh >> /tmp/pipeline-bot-health.log 2>&1

# Every 30 min — Approval watcher
# Catches ideas manually approved in Airtable (status set to "Approved")
# Lock expires after 15 min
*/30 * * * * MAX_LOCK_AGE=900 $WRAPPER approvals /tmp/pipeline-approval.log timeout 600 python orchestrator/approval_watcher.py

# Every 30 min — StoryEngine auto-deploy (frontend + backend)
# Detects code changes after git pull: rebuilds + restarts Next.js, restarts uvicorn
# Prevents the "stale build" issue where server serves old JS chunks
*/30 * * * * cd $REPO_DIR && bash skills/video-pipeline/infra/storyengine_deploy.sh >> /tmp/storyengine-deploy.log 2>&1
EOF
)

# Preserve any existing cron entries not from this script
EXISTING=$(crontab -l 2>/dev/null | grep -v "pipeline-discover\|pipeline-queue\|pipeline-bot-health\|pipeline-approval\|performance-tracker\|osiris-scraper\|osiris-analyze\|autopilot-cycle\|autopilot-ctr\|autopilot-learn\|storyengine_deploy\|pipeline\.log\|Pipeline Cron\|setup_cron\|Daily idea\|Daily pipeline\|performance tracker\|bot health\|Approval watcher\|run-queue\|--discover\|performance_tracker\|cron_wrapper\|osiris\.competitor\|osiris analyze\|autopilot\.autopilot\|autopilot\.monitoring\|autopilot\.learning\|analytics\.osiris\|StoryEngine frontend" || true)

# Install combined crontab
if [ -n "$EXISTING" ]; then
    echo "$EXISTING"$'\n'"$CRON_ENTRIES" | crontab -
else
    echo "$CRON_ENTRIES" | crontab -
fi

echo "  Cron jobs installed!"
echo ""
echo "  Scheduled (system time $SYS_TZ → ~Pacific equivalent):"
echo "    $OSIRIS_HOUR:00 daily (~5 AM PT)    ->  Osiris scraper (persist competitor videos)"
echo "    $(($OSIRIS_HOUR + 1)):30 daily (~6:30 AM PT)  ->  Autopilot cycle (score ideas, select best)"
echo "    $PERF_HOUR:00 daily (~7 AM PT)      ->  YouTube performance tracker (sync analytics)"
echo "    $PERF_HOUR:30 daily (~7:30 AM PT)   ->  Osiris analyzer (post-mortems + learnings)"
echo "    $PERF_HOUR:45 daily (~7:45 AM PT)   ->  Autopilot CTR monitor (early warnings)"
echo "    $(($PERF_HOUR + 1)):30 daily (~8:30 AM PT)  ->  Autopilot learning (extract patterns)"
echo "    $DISCOVER_HOUR:00 daily (~9 AM PT)  ->  Discovery scan (news + competitors → Slack)"
echo "    $QUEUE_HOUR:00 daily (~12 PM PT)    ->  Pipeline queue (process all stages to render)"
echo "    Every 15 min             ->  Bot health check (auto-restart if down)"
echo "    Every 30 min             ->  Approval watcher (catch manual approvals)"
echo "    Every 30 min             ->  StoryEngine deploy (frontend rebuild + backend restart)"
echo ""
echo "  Failure alerts:"
echo "    All jobs (except healthcheck) send Slack notifications on failure."
echo "    Check your Slack channel if you don't see morning activity."
echo ""
echo "  Timeouts:"
echo "    Osiris Scraper:    10 min max"
echo "    Autopilot Cycle:   15 min max"
echo "    Performance:       10 min max"
echo "    Osiris Analyzer:   10 min max"
echo "    Autopilot CTR:     10 min max"
echo "    Autopilot Learn:   10 min max"
echo "    Discovery:         15 min max (includes competitor scrape)"
echo "    Pipeline:          4 hours max"
echo "    Approval:          10 min max"
echo ""
echo "  Logs:"
echo "    /tmp/osiris-scraper.log"
echo "    /tmp/autopilot-cycle.log"
echo "    /tmp/performance-tracker.log"
echo "    /tmp/osiris-analyze.log"
echo "    /tmp/autopilot-ctr.log"
echo "    /tmp/autopilot-learn.log"
echo "    /tmp/pipeline-discover.log"
echo "    /tmp/pipeline-queue.log"
echo "    /tmp/pipeline-bot-health.log"
echo "    /tmp/pipeline-approval.log"
echo "    /tmp/storyengine-deploy.log"
echo ""
# ── Verify cron daemon is running ─────────────────────────────────────
if pgrep -x "cron" > /dev/null 2>&1 || pgrep -x "crond" > /dev/null 2>&1; then
    echo "  Cron daemon: RUNNING"
else
    echo "  WARNING: Cron daemon is NOT running!"
    echo "     Jobs are installed but will NOT fire until cron is started."
    echo "     Start it with:"
    echo "       sudo systemctl start cron && sudo systemctl enable cron"
    echo ""
fi

echo "  Verify with: crontab -l"
echo "  Diagnose:    bash infra/diagnose_cron.sh"
echo "=================================================="
