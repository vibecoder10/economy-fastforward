# Orchestrator & Sonnet-Worker Playbook

**What this is:** the operating manual for running the StoryEngine build loop as an
**orchestrator (premium model) + Sonnet workers** system. It codifies how the loop
was run across chunks C01–C10 so a **fresh session can pick it up cold**. Pair it with
`tasks/storyengine-wiring-fix-checklist.md` (the work queue + per-chunk layer detail)
and `tasks/todo.md` (the live 2-line handoff).

---

## 0. Bootstrap a new session (paste this as the opener)

> You are the ORCHESTRATOR for the StoryEngine build loop. Read `tasks/orchestrator-and-worker-playbook.md`, then the `## ⟳ LOOP PROGRESS` handoff at the top of `tasks/todo.md`, then the "LOOP EXECUTION PLAN" + iteration protocol at the bottom of `tasks/storyengine-wiring-fix-checklist.md`. Follow the playbook exactly: you orchestrate and do NOT write code or open large source files yourself; dispatch ONE Sonnet subagent per chunk to implement it end-to-end; skeptically review its evidence; ff-merge to main only if deploy-safe; update the 2-line handoff. Do the next unchecked chunk now.

Start the session on the **premium model** (Opus/Fable tier). The orchestrator must be
the strong model so its skeptical review actually catches bad work. Workers are Sonnet.

If the operator just says **"continue"** (or a loop fires): read the handoff, do the next
unchecked chunk per this playbook, end. Nothing else needs to be said.

---

## 1. Model discipline (this is what keeps the loop cheap and correct)

- **Orchestrator = premium model (Fable/Opus), main loop only.** It does NOT write code
  and does NOT open large source files — that is the entire token sink. If you catch
  yourself Reading `chat.py` / `pipeline_executor.py` / `ScenesWorkspaceTab.tsx` etc. in
  the main loop to *implement*, STOP and dispatch a worker. (Small, decisive **verification**
  reads — one migration file, one INSERT statement, one changed condition — are allowed and
  encouraged; see §4.)
- **Workers = Sonnet, always.** Every `Agent` call gets `model: "sonnet"`,
  `subagent_type: general-purpose`. All fan-out (implementation, search, web research,
  mechanical edits) runs on Sonnet. Never escalate a worker to premium for wiring chunks.
- **Second-opinion verifier = Sonnet too.** If a worker's evidence looks thin on a
  high-blast-radius change, dispatch a SECOND Sonnet agent (read-only `Explore` is ideal)
  to independently re-verify — cheaper than the orchestrator reading the code itself.

---

## 2. The iteration loop (one chunk per turn)

1. **Pick the topmost unchecked chunk** in the checklist's chunk queue. Never skip an
   unchecked SWEEP gate. Product-decision chunks flagged "Ryan" → skip, leave the question
   in the handoff, take the next build chunk.
2. **Dispatch ONE Sonnet worker** to implement the WHOLE chunk end-to-end (§3).
3. **Skeptically review** its report + evidence (§4). Dispatch a second Sonnet verifier if
   warranted.
4. **ff-merge to main** only if deploy-safe (§5). Otherwise leave on branch and note it.
5. **Update the 2-line handoff** in `tasks/todo.md` (§6) so an interrupted loop resumes cold.
6. **Stop.** One chunk per iteration, even if context is fresh — the handoff makes the next
   "continue" near-free.

---

## 3. Dispatching a Sonnet worker — the brief template

Every worker brief MUST contain these sections. Keep it tight but complete; the worker reads
the files, you don't.

```
You are the Sonnet worker for chunk **Cxx · <title>**. <1-sentence what+why>.

Repo root: /home/user/economy-fastforward. Working branch:
`claude/story-engine-build-loop-tfdg8n` (already checked out; do NOT switch/create
branches, do NOT push, do NOT ff-merge — the orchestrator merges). Branch == main; keep clean.

## Parent spec — checklist §X.Y
<paste the [D]/[B]/[U] layer bullets; name the specific files/functions/line hints>

## Two doors (if user-facing)
<the clickable control AND the conversational/copilot path, per tasks/storyengine-copilot-ux-map.md §N>

## Cost cap
No paid generation in the sandbox (no keys). Cheapest path; NEVER a real YouTube publish.

## Verify [V]
<the checklist's [V]. State: do the strongest in-sandbox verification (unit test that's
NON-VACUOUS via `git stash`, + code trace with quoted before/after), and DEFER any
paid/live/browser step to tasks/live-verification-queue.md under a new §Cxx. Be honest which
level you reached. Run `python -m py_compile` on touched .py; `cd storyengine/frontend &&
npx tsc --noEmit` if frontend touched. Full backend suite: no NEW failures vs the pre-existing
set (stash-compare). Backend tests use the venv: `cd storyengine/backend && ./venv/bin/python
-m pytest tests/ -q -k <sel>`.>

## Deliverables
1. Ship ALL listed layers.
2. Update SYSTEM_STATE.md if files/tables/routes moved or were created.
3. Tick `- [ ] Cxx` → `- [x] Cxx` in the checklist ONLY if [V] genuinely passes (note any deferral).
4. Commit to the branch, message starting `Cxx: <summary>`. Run
   `git config user.email noreply@anthropic.com && git config user.name Claude` FIRST so the
   commit isn't flagged unverified. End the body with the two trailer lines exactly as on the
   last commit (`git log -1 --format=%B`). Do NOT push.

## Report back to the orchestrator ONLY (tight):
- Files touched (+ any migration/column/endpoint added, confirmed-live y/n).
- The key evidence: quote the resolver/condition/write; prove the DEFAULT/existing path is
  unchanged; paste test result or curl output.
- [V] level reached; what was deferred to the live queue.
- py_compile + tsc status. Commit SHA.
- **Deploy-safe assessment (explicit):** does this change existing behavior? auto-deploy safe?
  ff-merge vs hold?
- Blockers.
```

**Sizing:** if a chunk is too big to finish in one worker pass, tell the worker to STOP and
split it in the checklist first, then do part 1. Sweeps run as ONE Sonnet `Explore` agent;
append findings to the audit report + add any new fixes as chunks in the same iteration.

---

## 4. Skeptical review (the anti-stub guard — this is the orchestrator's real job)

Do NOT rubber-stamp. For each report, judge whether the evidence actually proves the chunk
works and doesn't break anything:

- **"Ticked the box" ≠ done.** The point of the checklist is to kill stubs. If the worker
  wired a secondary path but left the *primary* user-facing path broken (this happened on
  C02 — the redraw paths were fixed but the bulk "Generate Pictures" button still ignored the
  setting), send it back. Verify the chunk achieves its *goal*, not just its literal bullets.
- **Trust-but-verify the decisive fact yourself.** When a change has high blast radius (a hot
  path every video hits, a money write, a migration that auto-deploys), do ONE small targeted
  read to confirm the single load-bearing claim — e.g.:
  - "the refactored function has exactly one caller and it's tested" → `grep` the callers.
  - "the money write is fail-soft" → read the ~15-line helper's try/except.
  - "the migration is idempotent" → read the `CREATE ... IF NOT EXISTS` lines.
  - "the default path is unchanged" → read the condition (`plan is not None and X in plan`
    can't catch a NULL-plan default).
  These are cheap and decisive; they are NOT "implementing in the main loop."
- **Non-vacuous tests.** A passing test only counts if it FAILS without the fix (the worker
  should prove this via `git stash`). "Full suite: same N pre-existing failures before and
  after" is the regression proof.
- **Thin evidence → second Sonnet verifier.** Especially for refactors of hot paths: have an
  `Explore` agent hunt specifically for the failure mode a mock test can't catch (stale
  callers, off-by-one INSERT placeholders, etc.).
- **Honesty is a good sign.** Workers that flag what they *couldn't* verify, or a pre-existing
  bug they found but didn't fix, are doing it right — capture those as new chunks / live-queue
  items rather than losing them.

---

## 5. Deploy-safety & the git/merge flow

**main auto-deploys hourly to the VPS (`git pull --ff-only`), so main must ALWAYS be
deployable.** Decide ff-merge vs hold from the worker's deploy-safe assessment + your review:

- **Deploy-safe (ff-merge):** additive (new table/column/endpoint/module), the DEFAULT/existing
  path is provably unchanged, fail-soft on paid paths, frontend fails safe (never renders empty),
  and backend leads frontend (a new API field ships before the frontend that reads it, since the
  frontend needs a separate `--with-frontend` build). Migrations must be idempotent (see §7).
- **Hold on branch:** anything that changes existing behavior on a hot path without a proven-safe
  argument, or where you're unsure. Note it in the handoff for a deliberate deploy.
- **Docs-only chunks** (sweeps, handoff, queue edits) are deploy-safe — ff-merge freely.

**The merge sequence (every deploy-safe chunk):**
```
git config user.email noreply@anthropic.com && git config user.name Claude
git push -u origin claude/story-engine-build-loop-tfdg8n
git checkout main && git merge --ff-only claude/story-engine-build-loop-tfdg8n
git push origin main
git checkout claude/story-engine-build-loop-tfdg8n
```
⚠ **ff-merge drags along EVERY commit beneath the tip.** Never fold a docs commit to main while
unapproved code commits sit beneath it on the branch — merge each approved chunk promptly so
branch tip == main (this bit us once in C02). Keep branch and main in sync after every chunk.

**Branch reality:** the working branch is `claude/story-engine-build-loop-tfdg8n` (exists local +
remote). The `claude/story-engine-repo-sgnm8l` name in some loop docs is stale — that branch does
not exist; do not use it.

---

## 6. The handoff (2 lines, resume-cold)

Keep `## ⟳ LOOP PROGRESS` at the very top of `tasks/todo.md` current:
- **Last done:** Cxx — what shipped, the commit SHA on main, the VERIFIED evidence in one line,
  and any ⚠ deferred-to-live-queue or ⚠ noted-risk.
- **Next chunk:** the next unchecked Cxx + its parent §, files, [V], and any trap to watch.

Commit the handoff (docs-only) and ff-merge it too. Workers may self-update the handoff; if so,
confirm it points at the right next chunk and reflects YOUR merge verdict, not just their claim.

---

## 7. Hard conventions & gotchas (learned C01–C10 — don't relearn these)

- **Commit identity:** always `git config user.email noreply@anthropic.com && user.name Claude`
  before committing, or the stop-hook flags commits "Unverified." (The remaining `N` = missing
  GPG signature, which reset-author can't fix and no signing key is configured — cosmetic, ignore.)
- **Migrations:** the app's runner tracks applied migrations by FILENAME in `_migrations` and
  skips already-applied names (`main.py` `_run_pending_migrations`). MCP `apply_migration` records
  in Supabase's OWN tracking, NOT the app's — so a migration applied via MCP will STILL run via the
  app runner on restart. Therefore **every migration must be idempotent** (`CREATE TABLE IF NOT
  EXISTS`, `ADD COLUMN IF NOT EXISTS`, `ENABLE ROW LEVEL SECURITY` is safe to re-run, `DROP POLICY
  IF EXISTS` before `CREATE POLICY`). Apply new tables/columns live via MCP against project
  `wrromlupsmyzrrcqlucn` AND commit the .sql file; confirm via `information_schema`.
- **RLS on new tables:** enable it (no policies) — the backend connects as `postgres`
  (`rolbypassrls=true`) so it's unaffected; this only closes the public PostgREST path. Proven safe
  (migration 083 pattern; `secrets` already runs RLS-on/0-policies live and works).
- **Money paths are sacred:** any ledger/cost write must be FAIL-SOFT (try/except INSIDE the helper,
  logs on failure, never raises) so it can't break a paid generation that already cost real money.
  Roll up `total_cost` by RECOMPUTE (`SET total_cost = SUM(actual_cost)`), never `+=` (retries would
  double-bill). No new spend path without a quote+confirm gate.
- **Single source of truth:** prices live ONCE in `skills/video-pipeline/shared/channel_profile.py`;
  `actions.py` re-exports (imports/aliases, not copies); the frontend reads prices from the API
  (`/api/models`, `/api/pipeline/actions`), never a local constant. When you fix a duplicate, END
  with one source + derived consumers.
- **Prices are real, from Kie:** Kie bills **$0.005/credit**; per-model prices are on `kie.ai/<model>`
  pages (image tiers by resolution, clips per-second). StoryEngine requests images at **2K**, clips
  default **720p** with per-duration Grok tiers. Kie/ElevenLabs API responses do NOT return a per-call
  cost — the ledger uses the researched unit price × real unit count. Genuinely-unconfirmed prices
  (Veo 3.1 fast/quality, ElevenLabs $/char, Kling Pro, Runway) are FLAGGED for a dashboard drain-check,
  never guessed. See `docs/cost-awareness.md` + live-verification-queue §C09.
- **Verification reality:** the sandbox has NO Kie/ElevenLabs key and NO route to the VPS (HTTPS-proxy
  only, no SSH). So paid/live/browser `[V]` steps CAN'T run here — verify at test+trace level and DEFER
  the live step to `tasks/live-verification-queue.md` with an exact recipe. Never fabricate a live result.
- **VPS coordination (if a session ever does reach the VPS):** deploy ONLY via `scripts/se.sh deploy`;
  never `pkill -f uvicorn` (self-matches); honor `~/deploy.lock`; ask Ryan before deploying (live system).
  Money rule: cost quote + explicit yes before any paid generation, even a test.
- **StoryEngine SaaS (`storyengine/backend`) is canonical**; `skills/video-pipeline/` is the legacy
  Airtable side but the SaaS backend CALLS into it (e.g. image gen runs through
  `skills/.../storyboard/coverage.py`). Fix the path that actually runs; wire-or-delete legacy stubs,
  never silent parallel maintenance.

---

## 8. Where things live (doc map)

| Doc | Role |
|---|---|
| `tasks/orchestrator-and-worker-playbook.md` | THIS — how to run the loop |
| `tasks/todo.md` (`## ⟳ LOOP PROGRESS`) | Live 2-line handoff / resume point |
| `tasks/storyengine-wiring-fix-checklist.md` | Work queue + per-chunk layer detail + chunk order |
| `tasks/storyengine-copilot-ux-map.md` | Two-doors interaction spec (clickable + conversational) |
| `tasks/storyengine-knowledge-map.md` | Routing + the sweep queue (S5–S10) |
| `tasks/live-verification-queue.md` | Paid/live/VPS `[V]` steps deferred from the sandbox (VPS-run priorities at top) |
| `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` | Audit evidence (append sweep results) |
| `docs/cost-awareness.md` | Per-stage prices + Kie $0.005/credit basis + dashboard-pending flags |
| `SYSTEM_STATE.md` | Structural-change log (update when files/tables/routes move) |
| `storyengine/CLAUDE.md` | StoryEngine operating card (se.sh ladder, hard rules, map) |
```
