#!/bin/bash
# StoryEngine Agent VPS Setup
# Run this ON the VPS after cloning. Sets up the agent workspace + crons + RUBRIC.

set -e

WORKSPACE="/home/clawd/agent-workspace"
REPO_URL="https://github.com/robonuggets/economy-fastforward.git"  # adjust if different
CLAUDE_BIN="/home/clawd/.npm-global/bin/claude"
LOG_DIR="/tmp/storyengine-agents"
RUBRIC_PORT=5050

echo "=== StoryEngine Agent VPS Setup ==="

# 1. Clone agent workspace (separate from production)
if [ -d "$WORKSPACE" ]; then
  echo "Agent workspace already exists at $WORKSPACE"
  cd "$WORKSPACE"
  git fetch origin
  git checkout main 2>/dev/null || git checkout -b main origin/main
  git pull --rebase origin main || true
else
  echo "Cloning agent workspace..."
  git clone "$REPO_URL" "$WORKSPACE"
  cd "$WORKSPACE"
  git checkout main 2>/dev/null || git checkout -b main origin/main
fi

# 2. Create log directory
mkdir -p "$LOG_DIR"

# 3. Install RUBRIC dependencies
cd "$WORKSPACE/rubric/scaffold"
npm install 2>/dev/null || true

# 4. Start RUBRIC dashboard (accessible from phone)
pkill -f "node.*rubric.*server" 2>/dev/null || true
sleep 1
nohup node server.js > "$LOG_DIR/rubric.log" 2>&1 &
echo "RUBRIC dashboard started on port $RUBRIC_PORT"
echo "Access from phone: http://$(hostname -I | awk '{print $1}'):$RUBRIC_PORT"

# 5. Install crons
echo "Installing agent crons..."

# Remove existing agent crons
crontab -l 2>/dev/null | grep -v "storyengine-agents" | grep -v "run-agent.sh" | grep -v "daily-report.sh" > /tmp/cron-clean.txt || true

AGENTS_DIR="$WORKSPACE/storyengine/agents"

cat >> /tmp/cron-clean.txt << EOF
# === StoryEngine Agents — VPS, 3 parallel every hour, 24/7 ===

# Environment for all agent crons
AGENT_PROJECT_ROOT=$WORKSPACE
CLAUDE_BIN=$CLAUDE_BIN
RUBRIC_URL=http://localhost:$RUBRIC_PORT
PATH=/home/clawd/.npm-global/bin:/usr/local/bin:/usr/bin:/bin

# Orchestrator — daily audit at 5:00 AM
0 5 * * * cd $AGENTS_DIR && bash run-agent.sh orchestrator >> $LOG_DIR/orchestrator.log 2>&1 # storyengine-agents

# Backend Dev — every hour at :00
0 * * * * cd $AGENTS_DIR && bash run-agent.sh backend-dev >> $LOG_DIR/backend-dev.log 2>&1 # storyengine-agents

# Frontend Dev — every hour at :02
2 * * * * cd $AGENTS_DIR && bash run-agent.sh frontend-dev >> $LOG_DIR/frontend-dev.log 2>&1 # storyengine-agents

# QA Engineer — every hour at :04
4 * * * * cd $AGENTS_DIR && bash run-agent.sh qa-engineer >> $LOG_DIR/qa-engineer.log 2>&1 # storyengine-agents

# Daily Report + PR — 11:00 PM
0 23 * * * cd $AGENTS_DIR && bash daily-report.sh >> $LOG_DIR/daily-report.log 2>&1 # storyengine-agents

# Keep RUBRIC dashboard alive (restart if dead)
*/5 * * * * pgrep -f "rubric.*server" > /dev/null || (cd $WORKSPACE/rubric/scaffold && nohup node server.js > $LOG_DIR/rubric.log 2>&1 &) # storyengine-agents
EOF

crontab /tmp/cron-clean.txt
rm /tmp/cron-clean.txt

# 6. Verify gh CLI is available for PR creation
if ! command -v gh &>/dev/null; then
  echo ""
  echo "WARNING: GitHub CLI (gh) not installed. Daily PRs won't work."
  echo "Install with: sudo apt install gh && gh auth login"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Schedule:"
echo "  5:00 AM  — Orchestrator (daily task planning)"
echo "  :00      — Backend Dev  (24 sessions/day)"
echo "  :02      — Frontend Dev (24 sessions/day)"
echo "  :04      — QA Engineer  (24 sessions/day)"
echo "  11:00 PM — Daily Report + GitHub PR"
echo "  */5 min  — RUBRIC healthcheck"
echo ""
echo "Agent workspace: $WORKSPACE (separate from production)"
echo "Production:      /home/clawd/projects/economy-fastforward/ (untouched)"
echo "RUBRIC:          http://$(hostname -I | awk '{print $1}'):$RUBRIC_PORT"
echo "Logs:            $LOG_DIR/"
echo ""
echo "To check status:  crontab -l | grep storyengine-agents"
echo "To view logs:     tail -f $LOG_DIR/backend-dev.log"
echo "To stop agents:   crontab -l | grep -v storyengine-agents | crontab -"
