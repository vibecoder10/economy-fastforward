# Task Tracking

## Completed: Pipeline Reorganization (2026-03-24)

Full codebase reorganization of `skills/video-pipeline/`. Each tool is now a standalone folder with its own manifest.json. Agent quality pipeline added (hook/body/CTA with iterative scoring).

## StoryEngine SaaS UI — Current State (2026-03-24)

### Completed Modules

**Module 0: Supabase Migration Verification** ✅
- 51 columns added across 5 tables, 5 schema bugs fixed
- Migrations: 004 (schema parity), 005 (agent + suggestion columns), 006 (niche columns)
- All migrations applied to live Supabase

**Module 1: Design System + Dashboard + Pipeline** ✅
- Dark editorial design tokens (charcoal #0A0A0B, amber #D4A844, teal #1A8A7A)
- 6-tab mobile bottom bar, 7-item collapsible desktop sidebar
- Dashboard: action-first (approvals, activity, stats)
- Pipeline: dropdown filters, search, progress dot cards

**Module 2: Video Detail (5 tabs) + Create** ✅
- `/pipeline/[videoId]` — Info, Script, Visuals, Thumbnail, Performance tabs (Board merged into Visuals)
- `/create` — New video form (title, angle, thesis + advanced options)

**Module 4: Autopilot + Analytics + Agent Suggestions** ✅
- `/analytics` — CTR bar chart (Recharts), revenue estimates, per-video cards
- `/autopilot` — Restyled, agent quality stats, top 3 recommendations
- Suggestion system: suggested_script/title/thumbnail with accept/reject
- Script diff UI, thumbnail variant visual UI

**Module 5: Niche Selection + Topic Discovery** ✅
- `/competitors` — Playing card grid with YouTube thumbnails, VPH, confidence
- Channel filter pills + dropdown
- Card expanded modal (theirs vs yours + thumbnail workshop)
- Thumbnail workshop with prompt iteration carousel
- Niche setup wizard (category → sub-niche → channels)
- `/autopilot` simplified to top 3 decision maker with "View All →" link

**Module 3: Interactive Features** ✅
- Script tab: inline text editing, tone dropdown, per-scene voice generation, collapsible sentence segments
- Visuals tab: storyboard mode toggle (ON: grids side-by-side with magnified CSS panel viewer + VO, OFF: direct image generation cards)
- Per-tab pipeline advancement via StageAdvancer (calls specific stage endpoints, not generic advance)
- Background task polling (useTaskPoller hook)
- Tab consolidation: 6→5 tabs (storyboard merged into visuals)
- Thumbnail tab: "Approve → Render" advancement
- Competitor channel URL input bar on `/competitors`
- Backend: 5 new scene endpoints, expanded script query, targeted voice/image regen with status gate bypass
- Migration 007: tone column on scripts

### Not Yet Built

**Future Modules:**
- Channel onboarding + baseline learning (import existing YouTube data)
- Batch topic selection / "Queue All"
- Calendar production view
- Settings page (Channel Profile, API keys, pipeline config)
- Multi-tenant architecture
- Billing & subscriptions

---

## Handoff Notes

**VPS Info:**
- SSH: `ssh clawd@76.13.119.181` (password: Economyfastforward)
- Frontend: `http://76.13.119.181:3001` (Next.js, port 3001)
- Backend: `http://76.13.119.181:8001` (FastAPI, port 8001)
- Auto-deploy cron: every 5 min pulls git + rebuilds frontend

**Key specs:**
- UI/UX spec: `docs/superpowers/specs/2026-03-23-storyengine-ui-ux-addendum.md`
- Module 5 spec: `docs/superpowers/specs/2026-03-24-module5-niche-discovery-design.md`

**Architecture decisions:**
- Agent pipeline is the PRIMARY script generation path (not a polish layer)
- Brief translator is legacy (VPS cron pipeline)
- Supabase is single source of truth, Airtable data imported
- Suggestions stored as proposed overwrites (human approves inline)
- Autopilot = decision maker (top 3), Competitors = research/browse (all cards)

**What to start next session with:**
1. Apply migration 007 to live Supabase (tone column on scripts)
2. Module 3 needs visual QA — check all tabs render correctly with real data
3. Future modules: Settings page, channel onboarding, calendar view, multi-tenant
