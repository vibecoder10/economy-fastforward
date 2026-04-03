#!/usr/bin/env bash
# dispatch.sh — Thin wrapper that routes to run-agent.sh (the unified agent runner)
#
# Usage: ./agents/dispatch.sh <agent-name>
#   agent-name: backend-dev, frontend-dev, qa-engineer, pipeline-tester, orchestrator
#
# run-agent.sh now handles both PRD tasks and task-queue work automatically:
#   - If agents/prd.json exists with pending tasks → agent works on PRD first
#   - After PRD tasks done (or no PRD) → agent works on task-queue.json
#
# This script exists so cron entries and the Command Center can call a single entry point.

set -euo pipefail

AGENT="${1:?Usage: dispatch.sh <agent-name>}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_ROOT/storyengine/agents" && exec bash run-agent.sh "$AGENT"
