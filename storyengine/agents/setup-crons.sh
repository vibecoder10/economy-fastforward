#!/bin/bash
# StoryEngine Agent Cron Setup
# All 3 agents run every hour in parallel. Staggered by 2 min for git safety.
# Run: bash storyengine/agents/setup-crons.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/tmp/storyengine-agents"

mkdir -p "$LOG_DIR"

# Remove existing agent crons
crontab -l 2>/dev/null | grep -v "storyengine-agents" | grep -v "run-agent.sh" > /tmp/cron-clean.txt || true

cat >> /tmp/cron-clean.txt << EOF
# === StoryEngine Agents — 3 parallel every hour, 24/7 ===

# Orchestrator — daily audit at 5:00 AM (creates today's task list)
0 5 * * * cd $SCRIPT_DIR && bash run-agent.sh orchestrator >> $LOG_DIR/orchestrator.log 2>&1 # storyengine-agents

# Backend Dev — every hour at :00 (24 sessions/day)
0 * * * * cd $SCRIPT_DIR && bash run-agent.sh backend-dev >> $LOG_DIR/backend-dev.log 2>&1 # storyengine-agents

# Frontend Dev — every hour at :02 (24 sessions/day)
2 * * * * cd $SCRIPT_DIR && bash run-agent.sh frontend-dev >> $LOG_DIR/frontend-dev.log 2>&1 # storyengine-agents

# QA Engineer — every hour at :04 (24 sessions/day)
4 * * * * cd $SCRIPT_DIR && bash run-agent.sh qa-engineer >> $LOG_DIR/qa-engineer.log 2>&1 # storyengine-agents

# Security Auditor — every 6 hours (4 sessions/day)
0 */6 * * * cd $SCRIPT_DIR && bash run-agent.sh security-auditor >> $LOG_DIR/security-auditor.log 2>&1 # storyengine-agents

# Pipeline Tester — every 3 hours (8 sessions/day)
0 */3 * * * cd $SCRIPT_DIR && bash run-agent.sh pipeline-tester >> $LOG_DIR/pipeline-tester.log 2>&1 # storyengine-agents

# PRD Watcher — every minute, spawns agents when PRD tasks become unblocked
* * * * * bash $SCRIPT_DIR/../../agents/prd-watcher.sh >> $LOG_DIR/prd-watcher.log 2>&1 # storyengine-agents

# Daily Report — 11:00 PM (plain-English summary for Ryan)
0 23 * * * cd $SCRIPT_DIR && bash daily-report.sh >> $LOG_DIR/daily-report.log 2>&1 # storyengine-agents
EOF

crontab /tmp/cron-clean.txt
rm /tmp/cron-clean.txt

echo "Agent crons installed."
echo ""
echo "Schedule:"
echo "  5:00 AM  — Orchestrator (daily task planning)"
echo "  :00      — Backend Dev  (24 sessions/day)"
echo "  :02      — Frontend Dev (24 sessions/day)"
echo "  :04      — QA Engineer  (24 sessions/day)"
echo ""
echo "  = 73 sessions/day (1 orchestrator + 24×3 build agents)"
echo "  = All 3 agents run in parallel every hour"
echo "  = 2-minute stagger to avoid git pull/push collisions"
echo ""
echo "Logs: $LOG_DIR/"
echo ""
echo "Current agent crons:"
crontab -l | grep "storyengine-agents"
