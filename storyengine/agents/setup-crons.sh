#!/bin/bash
# StoryEngine Agent Cron Setup
# Every agent cron checks team_enabled BEFORE launching Claude.
# Run: bash storyengine/agents/setup-crons.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/tmp/storyengine-agents"
CONTROLS="$PROJECT_ROOT/rubric/scaffold/data/controls.json"

# Guard command — exits if team is OFF. Prepended to every agent cron.
GUARD="python3 -c \"import json; exit(0 if json.load(open('$CONTROLS')).get('team_enabled',True) else 1)\" 2>/dev/null &&"

mkdir -p "$LOG_DIR"

# Remove existing agent crons
crontab -l 2>/dev/null | grep -v "storyengine-agents" | grep -v "run-agent.sh" > /tmp/cron-clean.txt || true

cat >> /tmp/cron-clean.txt << EOF
# === StoryEngine Agents ===
# Every agent cron checks team_enabled before launching.

# Orchestrator — grand audit at 5 AM
0 5 * * * $GUARD cd $SCRIPT_DIR && ORCHESTRATOR_MODE=grand bash run-agent.sh orchestrator >> $LOG_DIR/orchestrator.log 2>&1 # storyengine-agents

# Backend Dev — every 4 hours at :00
0 0,4,8,12,16,20 * * * $GUARD cd $SCRIPT_DIR && bash run-agent.sh backend-dev >> $LOG_DIR/backend-dev.log 2>&1 # storyengine-agents

# Frontend Dev — every 4 hours at :02
2 0,4,8,12,16,20 * * * $GUARD cd $SCRIPT_DIR && bash run-agent.sh frontend-dev >> $LOG_DIR/frontend-dev.log 2>&1 # storyengine-agents

# QA Engineer — every 4 hours at :04
4 0,4,8,12,16,20 * * * $GUARD cd $SCRIPT_DIR && bash run-agent.sh qa-engineer >> $LOG_DIR/qa-engineer.log 2>&1 # storyengine-agents

# Orchestrator micro — every 4 hours at :25
25 0,4,8,12,16,20 * * * $GUARD cd $SCRIPT_DIR && ORCHESTRATOR_MODE=micro bash run-agent.sh orchestrator >> $LOG_DIR/orchestrator-micro.log 2>&1 # storyengine-agents

# Pipeline Tester — every 4 hours at :20
20 0,4,8,12,16,20 * * * $GUARD cd $SCRIPT_DIR && bash run-agent.sh pipeline-tester >> $LOG_DIR/pipeline-tester.log 2>&1 # storyengine-agents

# Planning session — 6 AM
0 6 * * * $GUARD cd $SCRIPT_DIR && bash planning-session.sh >> $LOG_DIR/planning-session.log 2>&1 # storyengine-agents

# Morning briefing — 7 AM
0 7 * * * $GUARD cd $SCRIPT_DIR && bash morning-briefing.sh >> $LOG_DIR/morning-briefing.log 2>&1 # storyengine-agents

# Daily report — 11 PM
0 23 * * * $GUARD cd $SCRIPT_DIR && bash daily-report.sh >> $LOG_DIR/daily-report.log 2>&1 # storyengine-agents

# Calculate skills — 11:05 PM
5 23 * * * $GUARD cd $SCRIPT_DIR && bash calculate-skills.sh >> $LOG_DIR/calculate-skills.log 2>&1 # storyengine-agents

# Retro — 11:10 PM
10 23 * * * $GUARD cd $SCRIPT_DIR && bash retro.sh >> $LOG_DIR/retro.log 2>&1 # storyengine-agents

# RUBRIC server healthcheck — every 5 min (always runs, not guarded by team toggle)
# Uses node (not 'rubric.*server') to match the actual process name reliably
*/5 * * * * pgrep -f 'node.*server.js' > /dev/null || (cd $PROJECT_ROOT/rubric/scaffold && nohup node server.js > $LOG_DIR/rubric.log 2>&1 &) # storyengine-agents

# Telegram healthcheck — every 10 min (always runs, not guarded by team toggle)
# Reduced from 15min to 10min to minimize downtime gap after crashes
*/10 * * * * bash $PROJECT_ROOT/rubric/scaffold/telegram-healthcheck.sh >> $LOG_DIR/telegram-healthcheck.log 2>&1 # storyengine-agents
EOF

crontab /tmp/cron-clean.txt
rm /tmp/cron-clean.txt

echo "Agent crons installed."
echo ""
echo "Kill switch: All agent crons check $CONTROLS"
echo "  team_enabled=true  → agents run"
echo "  team_enabled=false → crons exit immediately (zero cost)"
echo ""
echo "Always-on (not guarded):"
echo "  RUBRIC server healthcheck (every 5m)"
echo "  Telegram healthcheck (every 15m)"
echo ""
echo "Current crons:"
crontab -l | grep "storyengine-agents"
