#!/bin/bash
# StoryEngine Agent Cron Setup — OPS MODE
# Pipeline tester is the priority agent (every hour). Dev agents run every 2h.
# Orchestrator pushes health reports twice daily. Telegram healthcheck every 15 min.
# Run: bash storyengine/agents/setup-crons.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/tmp/storyengine-agents"

mkdir -p "$LOG_DIR"

# Remove existing agent crons
crontab -l 2>/dev/null | grep -v "storyengine-agents" | grep -v "run-agent.sh" > /tmp/cron-clean.txt || true

cat >> /tmp/cron-clean.txt << EOF
# === StoryEngine Agents — Ops Mode (launch-readiness focus) ===

# Pipeline Tester — every hour at :10 (THE priority agent — finds bugs for everyone else)
10 * * * * cd $SCRIPT_DIR && bash run-agent.sh pipeline-tester >> $LOG_DIR/pipeline-tester.log 2>&1 # storyengine-agents

# Backend Dev — every 2 hours at :00 (fixes backend bugs filed by tester/QA)
0 */2 * * * cd $SCRIPT_DIR && bash run-agent.sh backend-dev >> $LOG_DIR/backend-dev.log 2>&1 # storyengine-agents

# Frontend Dev — every 2 hours at :02 (fixes frontend bugs filed by tester/QA)
2 */2 * * * cd $SCRIPT_DIR && bash run-agent.sh frontend-dev >> $LOG_DIR/frontend-dev.log 2>&1 # storyengine-agents

# QA Engineer — every 2 hours at :04 (verifies bug fixes)
4 */2 * * * cd $SCRIPT_DIR && bash run-agent.sh qa-engineer >> $LOG_DIR/qa-engineer.log 2>&1 # storyengine-agents

# Orchestrator — health report at 8 AM + 8 PM (push to Telegram)
0 8,20 * * * cd $SCRIPT_DIR && ORCHESTRATOR_MODE=grand bash run-agent.sh orchestrator >> $LOG_DIR/orchestrator.log 2>&1 # storyengine-agents

# Security Auditor — every 6 hours (4 sessions/day)
0 */6 * * * cd $SCRIPT_DIR && bash run-agent.sh security-auditor >> $LOG_DIR/security-auditor.log 2>&1 # storyengine-agents

# Telegram Healthcheck — every 15 minutes (auto-restart if dead)
*/15 * * * * bash $SCRIPT_DIR/../../rubric/scaffold/telegram-healthcheck.sh >> $LOG_DIR/telegram-healthcheck.log 2>&1 # storyengine-agents

# PRD Watcher — every minute, spawns agents when PRD tasks become unblocked
* * * * * bash $SCRIPT_DIR/../../agents/prd-watcher.sh >> $LOG_DIR/prd-watcher.log 2>&1 # storyengine-agents

# Daily Report — 11:00 PM (plain-English summary for Ryan + Telegram push)
0 23 * * * cd $SCRIPT_DIR && bash daily-report.sh >> $LOG_DIR/daily-report.log 2>&1 # storyengine-agents
EOF

crontab /tmp/cron-clean.txt
rm /tmp/cron-clean.txt

echo "Agent crons installed (OPS MODE)."
echo ""
echo "Schedule:"
echo "  :10      — Pipeline Tester (24 sessions/day — THE priority)"
echo "  :00      — Backend Dev     (12 sessions/day)"
echo "  :02      — Frontend Dev    (12 sessions/day)"
echo "  :04      — QA Engineer     (12 sessions/day)"
echo "  8AM+8PM  — Orchestrator    (health report to Telegram)"
echo "  Every 6h — Security Auditor"
echo "  Every 15m— Telegram Healthcheck"
echo "  Every 1m — PRD Watcher"
echo "  11 PM    — Daily Report"
echo ""
echo "  = ~42 agent sessions/day (tester-first, focused on launch readiness)"
echo ""
echo "Logs: $LOG_DIR/"
echo ""
echo "Current agent crons:"
crontab -l | grep "storyengine-agents"
