# Structured Workflow (GSD-Inspired)

## When to Invoke

**AUTO-TRIGGER on ANY of these:**
- User describes a feature with 3+ implementation steps
- User says "build", "implement", "add", "create" + a non-trivial feature
- Task touches 3+ files across different layers (DB, backend, frontend)
- User pastes rough notes, voice transcripts, or unstructured requirements
- User says "let's build..." or "I want to add..."
- Beginning of any session where todo.md has a multi-step handoff

**DO NOT trigger for:**
- Single-file bug fixes
- Questions / research / exploration
- Simple renames, moves, or config changes
- Tasks the user has already fully specified with exact steps

---

## The Workflow

### Phase 1: DISCUSS (Before writing any code)

Surface what's unclear. Don't assume — ask.

**Do this:**
1. Restate what you think the user wants in 2-3 sentences
2. List 3-5 **clarifying questions** that would change the implementation:
   - Edge cases ("What happens when X is empty?")
   - Scope boundaries ("Should this also handle Y?")
   - UX decisions ("Modal or inline? Toast or redirect?")
   - Data shape ("Does this need a new DB column or can we reuse Z?")
3. Flag any **architectural tensions** you see:
   - "This could be done in the frontend or backend — there's a tradeoff"
   - "The existing pattern in X does it differently than what you're describing"
   - "This overlaps with the existing Y system — should they share logic?"
4. If the user's approach has a simpler alternative, **propose it** with reasoning

**Output format:**
```
## Understanding
[2-3 sentence restatement]

## Clarifications Needed
1. [Question that would change the implementation]
2. [Question about scope]
3. [Question about UX/data shape]

## Tensions I See
- [Architectural tradeoff or overlap]

## Simpler Alternative? (if applicable)
[Propose if one exists, with tradeoff explanation]
```

**Wait for user response before proceeding to Phase 2.**

If the user says "just do it" or "you decide" — make the decisions explicitly, state them, and proceed. Don't ask twice.

---

### Phase 2: PLAN (Map the full wiring chain)

Trace every layer the feature touches. No code yet.

**Do this:**
1. List every file that will be created or modified
2. For each file, write a 1-line description of the change
3. Identify the **dependency order** (what must exist before what)
4. Write **verification criteria** — how will we prove this works?
5. Estimate complexity: small (< 30 min), medium (30-90 min), large (90+ min)

**Output format:**
```
## Plan: [Feature Name]

### Changes (in dependency order)
1. `path/to/file.py` — [what changes and why]
2. `path/to/file.tsx` — [what changes and why]
...

### Verification
- [ ] [How to prove layer 1 works]
- [ ] [How to prove layer 2 works]
- [ ] [End-to-end proof]

### Complexity: [small/medium/large]
```

**For StoryEngine features, always trace the 4-layer chain:**
```
Database (schema.sql / migration)
    ↕
Backend (routes/*.py + models.py + main.py)
    ↕
Frontend API (lib/api.ts + lib/types.ts)
    ↕
Frontend UI (components/*.tsx + pages/*.tsx)
```

**Wait for user approval before proceeding to Phase 3** (unless they said "just do it").

---

### Phase 3: EXECUTE (Build bottom-up)

Build in the order from the plan. One layer at a time.

**Rules:**
- Mark each todo item in_progress as you start, completed when done
- After each layer, verify it works before moving up
- If something unexpected comes up, **stop and re-plan** — don't hack around it
- Commit at natural breakpoints (each layer, or each logical unit)

---

### Phase 4: VERIFY (Prove it works)

Before saying "done", prove every verification criteria from the plan passes.

**Do this:**
1. Run relevant tests (`pytest`, `tsc --noEmit`, `npm run build`)
2. For StoryEngine: use webapp-testing skill (Playwright) to verify the running app
3. For pipeline: run with `--dry-run` or on a test record
4. Check for regressions — did anything else break?
5. Show the user the proof (test output, curl response, screenshot)

**Never say "done" based on "the code looks right." Run it.**

---

## State Tracking

Use `tasks/todo.md` for persistent state (survives between sessions).
Use the TodoWrite tool for in-session progress tracking.

When a session ends mid-feature, write a `## Handoff` section to `tasks/todo.md` with:
- What's done
- What's next
- Any decisions made during the discuss phase
- Any gotchas discovered during execution
