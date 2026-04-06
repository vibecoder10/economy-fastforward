# Architectural Decisions

> Append-only log of significant choices and WHY they were made.
> Future sessions: read this before re-litigating settled questions.
> Format: Date, Decision, Context, Alternatives Considered, Why This Won.

---

## 2026-04-06 — Thinking Partner + Structured Workflow over GSD installation

**Decision:** Cherry-pick GSD patterns into custom Claude Code skills rather than installing GSD as a dependency.

**Context:** GSD (v1 and v2) offers structured dev workflows. Our repo already has a 6-agent autonomous team, CLAUDE.md session protocol, and custom skills. GSD's file conventions (PROJECT.md, ROADMAP.md, STATE.md) would clash with our existing tasks/todo.md, tasks/lessons.md, SYSTEM_STATE.md.

**Alternatives:**
1. Install GSD globally — conflicts with existing agent system and file conventions
2. Install GSD locally for solo sessions only — still creates duplicate state files
3. Cherry-pick the best patterns into our own skills — fits our existing system

**Why this won:** We get the core value (discuss before plan, verify before done, proactive thinking) without the overhead of a second state management system. Our agent team is already beyond what GSD offers for multi-agent execution.

---

## 2026-04-06 — decisions.md as append-only log (inspired by GSD 2)

**Decision:** Add `tasks/decisions.md` for architectural choices, separate from `tasks/lessons.md`.

**Context:** GSD 2 introduced DECISIONS.md as an append-only architectural register. Our lessons.md captures mistakes and patterns. But *choices* (why we picked approach A over B) were scattered in todo.md handoffs and lost between sessions, causing future sessions to re-debate settled questions.

**Alternatives:**
1. Keep decisions in lessons.md — muddies the purpose (mistakes vs choices)
2. Keep decisions in todo.md handoffs — gets buried under task tracking
3. Separate decisions.md — clear purpose, easy to scan

**Why this won:** Different purpose = different file. Lessons = "don't do X." Decisions = "we chose Y because Z." Both are read at session start but serve different needs.

---

## 2026-04-06 — Markdown reorganization into typed folders

**Decision:** Move scattered root-level MDs into `docs/reports/`, `docs/reviews/`, `docs/reference/`, and rename `dailyjournal.md` → `tasks/roadmap.md`.

**Context:** 9 markdown files at root level with no organization. Completion reports mixed with config. Daily journal was actually a product roadmap.

**Alternatives:**
1. Leave them — works but cluttered, hard to find things
2. Move everything into docs/ flat — better but still no semantic grouping
3. Typed subfolders (reports, reviews, reference) — clear intent per folder

**Why this won:** Folder name tells you what kind of doc it is. Reports are historical artifacts. Reviews are analysis docs. Reference is outdated-but-preserved. Plans and specs already had this structure under docs/superpowers/.

---

## 2026-03-26 — Supabase as source of truth, Airtable as legacy

**Decision:** StoryEngine SaaS uses Supabase PostgreSQL as the single source of truth. Airtable remains for the VPS cron pipeline only.

**Context:** The VPS pipeline was built on Airtable (string-matched joins, no real relations). StoryEngine needs proper relational data, multi-tenancy, RLS.

**Alternatives:**
1. Migrate everything to Supabase — breaks VPS pipeline that works
2. Keep Airtable as source of truth — can't do multi-tenancy, RLS, proper joins
3. Dual-write (Airtable + Supabase) — complexity nightmare
4. Supabase for SaaS, Airtable for VPS pipeline — clean separation

**Why this won:** Don't break what works (VPS pipeline). Build new things right (Supabase). SupabaseAdapter bridges the gap for pipeline_executor.

---

## 2026-04-03 — Single agent runner, not two parallel systems

**Decision:** `run-agent.sh` is the ONE runner. It checks PRD tasks (priority) then falls through to task-queue. No separate `run-team.sh`.

**Context:** Two agent systems were built independently: `run-agent.sh` (StoryEngine-specific, cron-driven) and `run-team.sh` (portable, PRD-driven). They didn't share memory, skills, or activity feeds.

**Alternatives:**
1. Keep both systems with a dispatcher — more code, split context
2. Merge into run-agent.sh with priority routing — single system, shared everything

**Why this won:** Two disconnected systems = nobody learns, nothing is shared. One runner with priority routing (PRD > focus directive > task queue > standing orders) keeps everything unified.
