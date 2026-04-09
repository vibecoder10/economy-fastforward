# Dev Team Configuration

## Project
- Name: (set by human — e.g., "StoryEngine", "TodoApp", "SaaS Dashboard")
- Stack: (set by human — e.g., "Next.js 16, FastAPI, Supabase PostgreSQL")
- Frontend dev: `cd frontend && npm run dev`
- Backend dev: `cd backend && python -m uvicorn main:app --reload --port 8001`
- Test command: `npm test` / `python -m pytest`
- Type check: `cd frontend && npx tsc --noEmit`
- Build: `cd frontend && npm run build`

## Roles
- **lead**: Decomposes PRDs into tasks. Reviews completed work. Coordinates blocked tasks.
- **backend**: Python/FastAPI, database migrations, API endpoints, business logic.
- **frontend**: React/Next.js, TypeScript, TailwindCSS, components, pages.
- **qa**: Playwright browser testing, acceptance criteria verification, bug filing.
- **security**: Auth flows, input validation, dependency audits, OWASP checks.

## Rules

### Task Rules
- Every task MUST have machine-verifiable acceptance criteria
- Acceptance criteria are shell commands that exit 0 on success
- No task can be marked done without ALL criteria passing
- Never combine "find the problem" with "fix the problem" in one task
- Each task addresses exactly ONE concern

### The "Done" Standard (read this before marking anything done)

**Two levels — both required:**

| Level | Who sets it | What it means |
|-------|-------------|---------------|
| `done` | Implementing agent self-reports | Code committed, acceptance criteria run locally |
| `verified` | QA/Verifier independently confirms | Playwright clicked the UI, screenshots taken, state changes observed |

**`done` ≠ `verified`.** A PRD is only complete when the final QA task reaches `verified`.

**The "buttons work" rule:** For any frontend task, the implementing agent MUST verify that every interactive element (buttons, forms, dropdowns) triggers a visible state change before marking `done`. If you added a button, click it yourself before committing. If it does nothing: it's not done.

**QA is not optional.** Every PRD ends with a mandatory qa-engineer task. It runs Playwright, takes screenshots, and writes a smoke test file. The PRD cannot advance until this task is `verified`.

### Quality Gates (enforced by hooks — agents cannot bypass)
- TypeScript must compile: `npx tsc --noEmit`
- Tests must pass: `npm test` / `pytest`
- No lint errors: `npx eslint . --max-warnings 0`
- Playwright smoke test passes: `npx playwright test tests/prd-N-smoke.spec.ts` (written by QA task)

### Git Rules
- Every completed task gets its own commit with a descriptive message
- Commit message format: `feat/fix/chore: what changed and why`
- Pull before starting, push after each commit
- Never force push. Never amend published commits.

### Coordination Rules
- Agents read `progress.md` to know what's done and what's next
- After completing a task, update `progress.md` immediately
- If blocked, mark the task as "blocked" with the reason and move on
- The lead agent resolves blocked tasks and reassigns work

### Autonomy Rules
- You do NOT need permission to fix bugs you discover while working
- You do NOT need permission to run tests or type checks
- You DO need to follow the acceptance criteria — they are the spec
- If acceptance criteria are ambiguous, implement the simplest interpretation
- If you're stuck after 3 attempts, mark as blocked and move on
