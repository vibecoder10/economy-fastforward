#!/bin/bash
# Morning Briefing — sends daily Telegram digest to the boss
# Runs at 7:00 AM, after planning-session.sh (6:00 AM)

PROJECT_ROOT="${AGENT_PROJECT_ROOT:-/home/clawd/projects/economy-fastforward}"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
RUBRIC_DATA="$PROJECT_ROOT/rubric/scaffold/data"

echo "=== Morning Briefing ==="

# Source Telegram helper
source "$AGENTS_DIR/notify-telegram.sh"

if [ -z "$_TG_TOKEN" ] || [ -z "$_TG_CHAT_ID" ]; then
  echo "Telegram not configured — skipping briefing"
  exit 0
fi

# Gather all data and format the briefing
BRIEFING=$(python3 -c "
import json
from datetime import datetime, timedelta

today = datetime.now().strftime('%b %-d')
today_iso = datetime.now().strftime('%Y-%m-%d')

# Activity log — overnight completions and errors
try:
    activity = json.load(open('$RUBRIC_DATA/activity-log.json'))
except:
    activity = []

# Filter to last 24 hours
cutoff = (datetime.now() - timedelta(hours=24)).timestamp() * 1000
recent = [a for a in activity if a.get('timestamp', 0) > cutoff]
completed = [a for a in recent if a.get('status') == 'completed']
errors = [a for a in recent if a.get('status') == 'error']

# Agent completion counts
agent_counts = {}
for a in completed:
    agent = a.get('agent', 'unknown')
    name_map = {'backend-dev': 'Backend Dev', 'frontend-dev': 'Frontend Dev', 'qa-engineer': 'QA Engineer', 'orchestrator': 'Orchestrator', 'pipeline-tester': 'Pipeline Tester'}
    display = name_map.get(agent, agent)
    agent_counts[display] = agent_counts.get(display, 0) + 1

# Task queue progress
try:
    queue = json.load(open('$AGENTS_DIR/task-queue.json'))
    current_tab = queue.get('current_tab', 1)
    total_tabs = len(queue.get('tabs', []))
    all_tasks = [t for tab in queue.get('tabs', []) for t in tab.get('tasks', [])]
    done = sum(1 for t in all_tasks if t.get('status') == 'done')
    total = len(all_tasks)
    pct = round(done / total * 100) if total else 0

    # Current tab name
    tab_name = ''
    for tab in queue.get('tabs', []):
        if tab.get('id') == current_tab:
            tab_name = tab.get('name', '')
            break
except:
    current_tab = 1
    total_tabs = 0
    done = 0
    total = 0
    pct = 0
    tab_name = 'Unknown'

# Today's plan
try:
    plan = json.load(open('$RUBRIC_DATA/daily-plan.json'))
    plan_summary = plan.get('summary', 'No plan created')
    assignments = plan.get('assignments', {})
    blockers = plan.get('blockers', [])
    decisions = plan.get('decisions_needed', [])
    est = plan.get('estimated_completion', '')
except:
    plan_summary = 'No plan created yet'
    assignments = {}
    blockers = []
    decisions = []
    est = ''

# Pending proposals
try:
    proposals = json.load(open('$RUBRIC_DATA/proposals.json'))
    pending_proposals = [p for p in proposals if p.get('status') == 'pending']
except:
    pending_proposals = []

# Build the message
lines = []
lines.append(f'*Morning Update — {today}*')
lines.append('')

# Overnight section
if completed or errors:
    lines.append(f'*Overnight:* {len(completed)} tasks done' + (f', {len(errors)} failed' if errors else ''))
else:
    lines.append('*Overnight:* No activity')

# Progress
lines.append(f'*Progress:* {pct}% done with {tab_name} (Tab {current_tab}/{total_tabs})')

# Top agents
if agent_counts:
    top = sorted(agent_counts.items(), key=lambda x: -x[1])[:3]
    top_str = ', '.join(f'{name} ({count})' for name, count in top)
    lines.append(f'*Stars:* {top_str}')

lines.append('')

# Today's plan
lines.append(\"*Today's Plan:*\")
name_map = {'backend-dev': 'Backend Dev', 'frontend-dev': 'Frontend Dev', 'qa-engineer': 'QA', 'orchestrator': 'Orchestrator', 'pipeline-tester': 'Tester'}
for agent_id, info in assignments.items():
    display = name_map.get(agent_id, agent_id)
    tasks_str = ', '.join(info.get('tasks', [])[:2])
    if tasks_str:
        lines.append(f'  {display} → {tasks_str}')

# Blockers
if blockers:
    lines.append('')
    lines.append('*Heads up:* ' + blockers[0])

# Decisions needed
if decisions:
    lines.append('')
    lines.append('*Need from you:*')
    for d in decisions[:2]:
        lines.append(f'  {d}')
else:
    lines.append('')
    lines.append('*Need from you:* Nothing — team is self-sufficient')

# Proposals
if pending_proposals:
    lines.append('')
    lines.append(f'*{len(pending_proposals)} idea(s) from your team* — message me to review')

# Completion estimate
if est:
    lines.append('')
    lines.append(f'_{est}_')

print(chr(10).join(lines))
" 2>&1)

if [ -z "$BRIEFING" ]; then
  echo "ERROR: Failed to generate briefing"
  exit 1
fi

# Send via Telegram
notify_telegram "$BRIEFING"

echo "Morning briefing sent to Telegram"
echo "---"
echo "$BRIEFING"
