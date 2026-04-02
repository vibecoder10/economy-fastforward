#!/bin/bash
# calculate-skills.sh — Compute per-agent skill metrics from the task queue
# Reads task-queue.json, outputs agent-skills.json

PROJECT_ROOT="${AGENT_PROJECT_ROOT:-/Users/ryanayler/economy-fastforward}"
TASK_QUEUE="$PROJECT_ROOT/storyengine/agents/task-queue.json"
OUTPUT="$PROJECT_ROOT/rubric/scaffold/data/agent-skills.json"

if [ ! -f "$TASK_QUEUE" ]; then
  echo "ERROR: task-queue.json not found at $TASK_QUEUE"
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

python3 -c "
import json
import sys
from datetime import datetime, timezone

AGENTS = ['orchestrator', 'backend-dev', 'frontend-dev', 'qa-engineer', 'pipeline-tester']

LEVEL_THRESHOLDS = [
    (100, 8, 'Mythic'),
    (75,  7, 'Legend'),
    (50,  6, 'Grandmaster'),
    (35,  5, 'Master'),
    (20,  4, 'Expert'),
    (10,  3, 'Journeyman'),
    (5,   2, 'Apprentice'),
    (0,   1, 'Novice'),
]

def get_level(tasks_completed):
    for threshold, level, title in LEVEL_THRESHOLDS:
        if tasks_completed >= threshold:
            return level, title
    return 1, 'Novice'

def parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None

# Load task queue
try:
    with open('$TASK_QUEUE', 'r') as f:
        data = json.load(f)
except (json.JSONDecodeError, FileNotFoundError) as e:
    print(f'ERROR: Failed to read task queue: {e}', file=sys.stderr)
    sys.exit(1)

# Flatten all tasks from all tabs
all_tasks = []
for tab in data.get('tabs', []):
    for task in tab.get('tasks', []):
        all_tasks.append(task)

# Compute metrics per agent
agents_output = {}
for agent in AGENTS:
    # Filter tasks assigned to this agent
    agent_tasks = [t for t in all_tasks if t.get('assigned_to') == agent]

    # Tasks completed (status=done AND assigned_to matches)
    done_tasks = [t for t in agent_tasks if t.get('status') == 'done']
    tasks_completed = len(done_tasks)

    # Tasks failed (status=blocked AND assigned_to matches)
    blocked_tasks = [t for t in agent_tasks if t.get('status') == 'blocked']
    tasks_failed = len(blocked_tasks)

    # Average completion minutes (from started_at to completed_at for done tasks)
    durations = []
    for t in done_tasks:
        started = parse_ts(t.get('started_at'))
        completed = parse_ts(t.get('completed_at'))
        if started and completed and completed > started:
            delta_minutes = (completed - started).total_seconds() / 60.0
            durations.append(delta_minutes)
    avg_completion_minutes = round(sum(durations) / len(durations), 1) if durations else 0

    # QA pass rate (verified=true / done tasks)
    verified_count = sum(1 for t in done_tasks if t.get('verified') is True)
    qa_pass_rate = round(verified_count / tasks_completed, 2) if tasks_completed > 0 else 0

    # Current streak (consecutive done tasks from most recent backward)
    # Sort by completed_at descending, then walk backward counting done
    sorted_tasks = sorted(
        agent_tasks,
        key=lambda t: t.get('completed_at') or t.get('started_at') or '',
        reverse=True,
    )
    current_streak = 0
    for t in sorted_tasks:
        if t.get('status') == 'done':
            current_streak += 1
        else:
            break

    # Reset count total
    reset_count_total = sum(t.get('reset_count', 0) for t in agent_tasks)

    # Level and title
    level, title = get_level(tasks_completed)

    agents_output[agent] = {
        'tasks_completed': tasks_completed,
        'tasks_failed': tasks_failed,
        'avg_completion_minutes': avg_completion_minutes,
        'qa_pass_rate': qa_pass_rate,
        'current_streak': current_streak,
        'reset_count_total': reset_count_total,
        'level': level,
        'xp': tasks_completed,
        'title': title,
    }

output = {
    'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'agents': agents_output,
}

with open('$OUTPUT', 'w') as f:
    json.dump(output, f, indent=2)
    f.write('\n')
" 2>&1

echo "Agent skills written to $OUTPUT"
