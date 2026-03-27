# Task Tracking

## Current Sprint

_Reference `ANIMATION_SYSTEM_REVIEW.md` for detailed feature specs before starting any roadmap item._

### StoryEngine Wiring Checklist

- [ ] Replace StoryEngine's remaining local Prisma/SQLite assumptions with the intended Supabase data path
- [ ] Add a single source of truth doc for StoryEngine data flow: UI -> Next API/service layer -> Supabase -> generation providers
- [ ] Remove or clearly demote the unused Express backend path if Next.js routes remain the active control plane
- [ ] Confirm auth/session ownership on all project routes; eliminate dev-user fallbacks
- [ ] Confirm how channel profiles are selected for project generation and persist the chosen profile on each project
- [ ] Make saved API keys actually drive generation calls instead of using env-only fallbacks
- [ ] Verify script generation wiring in the current UI against the live code path
- [ ] Verify voice-over wiring in the current UI against the live code path
- [ ] Verify sentence-splitting wiring in the current UI against the live code path
- [ ] Separate sentence splitting from image prompt generation if those are intended to be distinct stages in the UI
- [ ] Persist image prompt results into project scene data so prompts survive refresh/reload
- [ ] Add a project-level image prompt generation route that uses project data + selected profile + saved key
- [ ] Wire per-scene and/or batch image prompt actions in the project UI to the persisted route
- [ ] Wire image generation after prompts: prompt -> provider call -> permanent asset URL -> project scene update
- [x] Decide whether generated assets should proxy through Google Drive or an updated Supabase storage path
- [ ] Add status transitions for StoryEngine project stages so the UI reflects actual progress
- [ ] Add usage/cost tracking on live generation routes once the call paths are real
- [ ] Verify Remotion/export/render handoff after scenes/prompts/images are persisted
- [ ] Add a shared Google Drive asset storage layer for voice, image, video, sound, thumbnail, and storyboard files
- [ ] Ensure each video gets a dedicated Drive folder and subfolders for asset types

### Active Task

- [ ] Wire StoryEngine image prompts to persist on the project record and survive reload
- [ ] Reuse profile/key-aware generation logic where possible instead of hardcoded prompts
- [ ] Verify the current codebase location of script/voice/sentence-splitting wiring and document any missing links
- [ ] Replace the local `Project` persistence path with a Supabase `VideoDetail` read model over `videos/scripts/assets/stage_transitions`
- [ ] Add stage-transition logging for every pipeline step that the UI triggers
- [ ] Route all generated binary assets through the shared Drive asset service before writing URLs into Supabase

## Backlog (from Roadmap)

### Phase 2: Character Consistency
- [ ] Feature 1: Character Reference System (BYOC) — HIGH
- [ ] Feature 5: Style Locking via Golden Frame — HIGH
- [ ] Feature 10: Quality Scoring via Gemini Vision — MEDIUM

### Phase 3: Product Mode
- [ ] Feature 3: One-Shot `!create` Pipeline — HIGH
- [ ] Feature 4: Airtable Schema Optimization — MEDIUM
- [ ] Feature 7: Health Dashboard & Self-Healing — MEDIUM

### Phase 4: Animation Quality
- [ ] Feature 8: Start/End Frame Bridging — MEDIUM
- [ ] Feature 9: Multi-Voice & Sound Design — LOW

## Completed

- [x] Feature 2: Auto-Pull from GitHub on Cron — DONE
- [x] Feature 6: Veo 3.1 Fast Integration — DONE
- [x] Workflow orchestration rules (CLAUDE.md) — DONE

## Review Notes

_Add review summaries here after completing tasks. Include: what changed, what was tested, what the user should verify._
