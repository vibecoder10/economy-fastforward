# Shared Agent Protocols

These protocols apply to ALL agents. They are injected automatically by run-agent.sh.

## Task Selection Rules

When picking your next task, follow these rules IN ORDER:

1. **Check controls**: Read the Operator Controls section above.
   - Skip any task whose ID is in the SKIPPED TASKS list
   - If PRIORITY OVERRIDES exist for tasks matching your role, pick the highest-priority one first (lowest number = highest priority)

2. **Check dependencies**: If a task has a `"depends_on"` field:
   - Find the dependency task by its ID
   - Only pick this task if the dependency has `"status": "done"` AND `"verified": true`
   - If not met, skip to the next task

3. **Check handoffs**: If there's a handoff note addressed to you for a specific task, prefer that task

4. **Default**: Pick the first task matching your role with `"status": "pending"` that passes all checks

5. **Nothing to do**: If no tasks pass checks, report idle and exit

## Timestamp Conventions

When marking a task `"in_progress"`, also set:
- `"started_at": "YYYY-MM-DDTHH:MM:SSZ"` (current ISO timestamp)
- `"assigned_to": "YOUR_AGENT_ID"`

When marking a task `"done"`, also set:
- `"completed_at": "YYYY-MM-DDTHH:MM:SSZ"` (current ISO timestamp)

## Scheduling Context

- Backend Dev runs at :00 each hour
- Frontend Dev runs at :02 each hour
- QA Engineer runs at :04 each hour
- Within a single hour: backend finishes first, frontend picks up, QA verifies

## Messaging the Boss

If you need input, are stuck, or found something important, include at the END of your response:

MESSAGE_BOSS: [Your message in plain English. No code, no jargon. Write like you are texting your manager.]

Rules:
- Only message if it is genuinely important or you cannot proceed without an answer
- Max 1 message per session
- Keep it under 2 sentences
- Do not message just to give a status update (that is what SUMMARY is for)

## Proposals (Optional — After Your Main Task)

After completing your assigned task, if you notice something worth improving, you MAY include a proposal. This is OPTIONAL — only propose if you genuinely see an improvement opportunity.

Include at the end of your response (after DETAIL):

PROPOSAL_JSON:
{"agent": "YOUR_AGENT_ID", "type": "refactor", "title": "Short title", "description": "What and why in plain English", "impact": "Expected benefit", "cost": "low"}
END_PROPOSAL

Types: refactor, optimization, bug_fix, new_feature, process_improvement
Cost: low (1 session), medium (2-3 sessions), high (4+ sessions)

Rules:
- Complete your assigned task FIRST. Proposals are bonus.
- Max 1 proposal per session.
- Only propose things you have seen evidence for (not theoretical).
- Write all text in plain English — the boss is non-technical.
