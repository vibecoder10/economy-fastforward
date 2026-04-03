#!/bin/bash
# calculate-skills.sh — Compute per-agent skill metrics from task queue + PRD history
# Reads task-queue.json + agents/prd.json + memory files, outputs agent-skills.json

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TASK_QUEUE="$PROJECT_ROOT/storyengine/agents/task-queue.json"
PRD_FILE="$PROJECT_ROOT/agents/prd.json"
MEMORY_DIR="$PROJECT_ROOT/storyengine/agents/memory"
OUTPUT="$PROJECT_ROOT/rubric/scaffold/data/agent-skills.json"

if [ ! -f "$TASK_QUEUE" ]; then
  echo "ERROR: task-queue.json not found at $TASK_QUEUE"
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

python3 -c "
import json
import sys
import os
from datetime import datetime, timezone

AGENTS = ['orchestrator', 'backend-dev', 'frontend-dev', 'qa-engineer', 'pipeline-tester']

# Map PRD roles to agent names
PRD_ROLE_MAP = {
    'backend': 'backend-dev',
    'frontend': 'frontend-dev',
    'qa': 'qa-engineer',
    'pipeline-tester': 'pipeline-tester',
    'lead': 'orchestrator',
    'security': 'orchestrator',
}

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

def count_memory_entries(agent):
    path = os.path.join('$MEMORY_DIR', agent + '.md')
    try:
        with open(path) as f:
            return sum(1 for line in f if line.strip().startswith('- '))
    except FileNotFoundError:
        return 0

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

# Load PRD tasks (current + historical)
prd_tasks = []
try:
    with open('$PRD_FILE', 'r') as f:
        prd = json.load(f)
        for t in prd.get('tasks', []):
            agent = PRD_ROLE_MAP.get(t.get('role', ''), '')
            if agent:
                prd_tasks.append({**t, '_agent': agent})
except (json.JSONDecodeError, FileNotFoundError):
    pass

# Also check progress.md for completed PRD tasks
prd_done_count = {}
try:
    with open('$PROJECT_ROOT/agents/progress.md', 'r') as f:
        for line in f:
            if '[x]' in line.lower():
                # Extract role from line like '- [x] T1: ... (backend) ✅'
                for role, agent in PRD_ROLE_MAP.items():
                    if f'({role})' in line.lower():
                        prd_done_count[agent] = prd_done_count.get(agent, 0) + 1
                        break
except FileNotFoundError:
    pass

# Compute metrics per agent
agents_output = {}
for agent in AGENTS:
    # --- Task Queue metrics ---
    agent_tasks = [t for t in all_tasks if t.get('assigned_to') == agent]
    done_tasks = [t for t in agent_tasks if t.get('status') == 'done']
    tq_completed = len(done_tasks)

    blocked_tasks = [t for t in agent_tasks if t.get('status') == 'blocked']
    tasks_failed = len(blocked_tasks)

    # Average completion minutes
    durations = []
    for t in done_tasks:
        started = parse_ts(t.get('started_at'))
        completed = parse_ts(t.get('completed_at'))
        if started and completed and completed > started:
            delta_minutes = (completed - started).total_seconds() / 60.0
            durations.append(delta_minutes)
    avg_completion_minutes = round(sum(durations) / len(durations), 1) if durations else 0

    # QA pass rate
    verified_count = sum(1 for t in done_tasks if t.get('verified') is True)
    qa_pass_rate = round(verified_count / tq_completed, 2) if tq_completed > 0 else 0

    # Current streak
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

    reset_count_total = sum(t.get('reset_count', 0) for t in agent_tasks)

    # --- PRD metrics (add to task queue count) ---
    prd_completed = prd_done_count.get(agent, 0)

    # --- Memory metrics ---
    memory_entries = count_memory_entries(agent)

    # --- Combined totals ---
    total_completed = tq_completed + prd_completed
    level, title = get_level(total_completed)

    # Add PRD tasks to streak
    total_streak = current_streak + prd_completed

    agents_output[agent] = {
        'tasks_completed': total_completed,
        'tasks_from_queue': tq_completed,
        'tasks_from_prd': prd_completed,
        'tasks_failed': tasks_failed,
        'avg_completion_minutes': avg_completion_minutes,
        'qa_pass_rate': qa_pass_rate,
        'current_streak': total_streak,
        'reset_count_total': reset_count_total,
        'memory_entries': memory_entries,
        'level': level,
        'xp': total_completed,
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
