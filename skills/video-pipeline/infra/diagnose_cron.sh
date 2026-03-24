#!/bin/bash
# Diagnose why cron jobs are not firing on the production VPS.
#
# Run this on the VPS to identify which of the 5 common failure modes
# is preventing cron from working:
#   1. Cron daemon not running
#   2. Stale lock files blocking execution
#   3. Timezone misconfiguration
#   4. Python venv issues
#   5. Git/repo state issues
#
# Usage: bash diagnose_cron.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=================================================="
echo "  Pipeline Cron Diagnostics"
echo "=================================================="
echo "  Time: $(date)"
echo "  Host: $(hostname)"
echo ""

ISSUES=0

# ── Check 1: Is the cron daemon running? ─────────────────────────────
echo "--- Check 1: Cron Daemon ---"
CRON_RUNNING=false
if pgrep -x "cron" > /dev/null 2>&1; then
    echo "  OK: cron daemon is running (PID: $(pgrep -x cron))"
    CRON_RUNNING=true
elif pgrep -x "crond" > /dev/null 2>&1; then
    echo "  OK: crond daemon is running (PID: $(pgrep -x crond))"
    CRON_RUNNING=true
else
    echo "  FAIL: No cron daemon (cron or crond) is running!"
    echo "  FIX:  sudo systemctl start cron"
    echo "        sudo systemctl enable cron"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# ── Check 2: Crontab entries exist? ──────────────────────────────────
echo "--- Check 2: Crontab Entries ---"
CRON_COUNT=$(crontab -l 2>/dev/null | grep -c "pipeline\|cron_wrapper\|bot_healthcheck\|performance_tracker\|approval_watcher" || true)
if [ "$CRON_COUNT" -gt 0 ]; then
    echo "  OK: Found $CRON_COUNT pipeline-related cron entries"
    # Show them
    crontab -l 2>/dev/null | grep -E "pipeline|cron_wrapper|bot_healthcheck|performance_tracker|approval_watcher" | while read -r line; do
        echo "    $line"
    done
else
    echo "  FAIL: No pipeline cron entries found!"
    echo "  FIX:  Run: bash setup_cron.sh"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# ── Check 3: Stale lock files ────────────────────────────────────────
echo "--- Check 3: Lock Files ---"
LOCK_FOUND=false
for lockfile in /tmp/pipeline-*.lock; do
    [ -f "$lockfile" ] || continue
    LOCK_FOUND=true
    LOCK_PID=$(cat "$lockfile" 2>/dev/null)
    LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$lockfile" 2>/dev/null || echo 0) ))
    LOCK_AGE_MIN=$((LOCK_AGE / 60))

    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        PROC_NAME=$(ps -p "$LOCK_PID" -o comm= 2>/dev/null || echo "unknown")
        if echo "$PROC_NAME" | grep -qE "python|pipeline|bash"; then
            echo "  WARN: $lockfile — PID $LOCK_PID ($PROC_NAME) alive, age: ${LOCK_AGE_MIN}m"
        else
            echo "  FAIL: $lockfile — PID $LOCK_PID is '$PROC_NAME' (NOT a pipeline process!)"
            echo "        This is a reused PID. Lock is stale but looks alive."
            echo "  FIX:  rm $lockfile"
            ISSUES=$((ISSUES + 1))
        fi
    else
        echo "  FAIL: $lockfile — PID $LOCK_PID is DEAD, age: ${LOCK_AGE_MIN}m"
        echo "        Stale lock blocking new runs."
        echo "  FIX:  rm $lockfile"
        ISSUES=$((ISSUES + 1))
    fi
done
if [ "$LOCK_FOUND" = false ]; then
    echo "  OK: No lock files found"
fi
echo ""

# ── Check 4: System timezone ─────────────────────────────────────────
echo "--- Check 4: Timezone ---"
SYS_TZ=$(cat /etc/timezone 2>/dev/null || timedatectl show --property=Timezone --value 2>/dev/null || echo "unknown")
echo "  System timezone: $SYS_TZ"
echo "  Current time:    $(date)"
echo "  UTC time:        $(date -u)"

if echo "$SYS_TZ" | grep -qi "america/los_angeles\|US/Pacific"; then
    echo "  OK: System is Pacific time — cron schedule times match"
else
    echo "  WARN: System is NOT Pacific time"
    echo "        CRON_TZ=America/Los_Angeles in crontab is IGNORED on Debian/Ubuntu (vixie-cron)"
    echo "        Jobs fire at system-local times, not Pacific times"
    echo "  FIX:  Re-run setup_cron.sh (updated version converts to UTC times)"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# ── Check 5: Python venv ─────────────────────────────────────────────
echo "--- Check 5: Python Environment ---"
PYTHON_FOUND=""
candidates=(
    "/home/clawd/pipeline-bot/venv/bin/python"
    "$REPO_DIR/venv/bin/python"
    "$SCRIPT_DIR/venv/bin/python"
)
for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ]; then
        PYTHON_FOUND="$candidate"
        echo "  OK: Found Python at $candidate"
        echo "      Version: $($candidate --version 2>&1)"
        break
    fi
done
if [ -z "$PYTHON_FOUND" ]; then
    PYTHON_FOUND="python3"
    echo "  WARN: No venv found, falling back to system python3"
    echo "        Version: $(python3 --version 2>&1 || echo 'NOT INSTALLED')"
fi

# Check key packages
echo "  Checking key packages..."
for pkg in httpx anthropic pyairtable dotenv; do
    if $PYTHON_FOUND -c "import $pkg" 2>/dev/null; then
        echo "    OK: $pkg"
    else
        echo "    FAIL: $pkg — not installed"
        ISSUES=$((ISSUES + 1))
    fi
done
echo ""

# ── Check 6: Repo state ──────────────────────────────────────────────
echo "--- Check 6: Git Repository ---"
cd "$REPO_DIR" 2>/dev/null || { echo "  FAIL: Cannot cd to $REPO_DIR"; ISSUES=$((ISSUES + 1)); }
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
echo "  Branch: $BRANCH"
DIRTY=$(git status --porcelain 2>/dev/null | head -5)
if [ -n "$DIRTY" ]; then
    echo "  WARN: Repo has uncommitted changes (git pull --ff-only may fail):"
    echo "$DIRTY" | head -5 | sed 's/^/    /'
    UNCOMMITTED=$(git status --porcelain 2>/dev/null | wc -l)
    if [ "$UNCOMMITTED" -gt 5 ]; then
        echo "    ... and $((UNCOMMITTED - 5)) more"
    fi
else
    echo "  OK: Working tree is clean"
fi
echo ""

# ── Check 7: .env file ───────────────────────────────────────────────
echo "--- Check 7: Environment Variables (.env) ---"
if [ -f "$REPO_DIR/.env" ]; then
    echo "  OK: .env file exists"
    for var in ANTHROPIC_API_KEY AIRTABLE_API_KEY KIE_AI_API_KEY SLACK_BOT_TOKEN; do
        if grep -q "^${var}=" "$REPO_DIR/.env" 2>/dev/null; then
            echo "    OK: $var is set"
        else
            echo "    FAIL: $var is MISSING"
            ISSUES=$((ISSUES + 1))
        fi
    done
else
    echo "  FAIL: .env file not found at $REPO_DIR/.env"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# ── Check 8: Log files writable ──────────────────────────────────────
echo "--- Check 8: Log Files ---"
for logfile in /tmp/pipeline-discover.log /tmp/pipeline-queue.log /tmp/pipeline-bot-health.log /tmp/pipeline-approval.log /tmp/performance-tracker.log; do
    if [ -f "$logfile" ]; then
        LAST_MOD=$(stat -c %Y "$logfile" 2>/dev/null || echo 0)
        AGE_HOURS=$(( ($(date +%s) - LAST_MOD) / 3600 ))
        echo "  $logfile — last modified ${AGE_HOURS}h ago"
    else
        echo "  $logfile — does not exist (never ran?)"
    fi
done
echo ""

# ── Check 9: cron_wrapper.sh executable ──────────────────────────────
echo "--- Check 9: Wrapper Script ---"
WRAPPER="$SCRIPT_DIR/cron_wrapper.sh"
if [ -x "$WRAPPER" ]; then
    echo "  OK: $WRAPPER is executable"
else
    echo "  FAIL: $WRAPPER is not executable"
    echo "  FIX:  chmod +x $WRAPPER"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# ── Check 10: cron log (syslog) ──────────────────────────────────────
echo "--- Check 10: Cron Syslog (last 10 pipeline entries) ---"
if [ -f /var/log/syslog ]; then
    grep -i "CRON\|cron" /var/log/syslog 2>/dev/null | grep -i "pipeline\|cron_wrapper\|clawd" | tail -10 | sed 's/^/  /'
    if [ $? -ne 0 ]; then
        echo "  No pipeline-related cron entries in syslog"
    fi
elif [ -f /var/log/cron.log ]; then
    grep -i "pipeline\|cron_wrapper\|clawd" /var/log/cron.log 2>/dev/null | tail -10 | sed 's/^/  /'
else
    echo "  No syslog or cron.log found — check: journalctl -u cron --since '1 hour ago'"
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────
echo "=================================================="
if [ $ISSUES -eq 0 ]; then
    echo "  All checks passed! Cron should be working."
    echo "  If jobs still don't fire, check: journalctl -u cron -f"
else
    echo "  Found $ISSUES issue(s) — fix them and re-run this script."
fi
echo "=================================================="
