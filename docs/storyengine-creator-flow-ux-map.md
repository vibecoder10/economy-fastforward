# StoryEngine Creator Flow UX Map

Date: 2026-06-09

## Product Goal

Make first-run video generation feel like one guided creator workflow:

1. Creator connects their own YouTube channel.
2. Creator provides 1-3 competitor channels.
3. StoryEngine recommends titles from recent/top-performing competitor videos.
4. StoryEngine analyzes competitor title, thumbnail, hook, script, and visual patterns.
5. Creator chooses how closely to model the reference style.
6. StoryEngine creates the video and routes the creator to the next production action.

## Current UI State

### Dashboard

`storyengine/frontend/src/app/dashboard/page.tsx`

- Has a Create From Competitors launchpad card.
- Shows YouTube, competitors, title ideas, style modeling, and create video as a compact path.
- Launchpad actions now deep-link into exact onboarding steps with `?step=youtube`, `?step=competitors`, and `?step=video` instead of dropping creators into broad settings/pipeline pages.
- Dashboard primary action now opens `Ideas From Competitors` instead of generic new-video creation.
- Recent videos now preserve modeled-reference context when a video came from competitor inspiration.
- Dashboard now has a dedicated Modeled References section when paired competitor videos exist, showing source video -> StoryEngine video with direct Source and Open Pair actions.
- Pipeline distribution bars now route into the actual filtered production list instead of a dead query parameter.
- Authenticated `/` traffic now redirects to `/dashboard` so there is one dashboard surface instead of an older duplicate dashboard with stale generic creation copy.
- Dashboard onboarding status now returns a single backend-owned `next_step`, `next_action`, `next_href`, and `next_reason` for the creator flow.
- The setup banner and launchpad now point to the same backend next step instead of inferring different actions in React.
- Completion now represents the real first-run creator workflow: YouTube connected, channel configured, Kie key ready, style generated, competitors added, recommendations generated, and a first video created.

### Onboarding

`storyengine/frontend/src/app/onboarding/page.tsx`

- Now includes a competitor intelligence step between YouTube and first video.
- The new step uses backend onboarding competitor analysis and intelligence-report routes.
- Onboarding now starts with YouTube OAuth so a connected channel can prefill channel identity before manual details are requested.
- Title recommendations can now be selected inside onboarding and carried into first-video creation.
- Recommendation cards now expose the selected title reasoning, quick-win/opportunity notes, and a clear next-step prompt to choose modeling style.
- Recommendation cards now expose a concrete creation plan when available: script structure, visual prompt direction, hook direction, and modeling notes.
- Competitor onboarding now enriches and attempts to distill the strongest two references per competitor channel so first-run recommendations can use real hook/script/thumbnail DNA instead of only raw titles.
- The first-video form starts from the selected title, shows the hook/thumbnail rationale, and saves the modeling mode plus recommendation context into `videos.writer_guidance`.
- First-video creation now saves the richer creation plan into `videos.writer_guidance` so downstream research/script/visual bots inherit the competitor modeling instructions.
- First-video creation exposes GPT Image 2 plus the Seedance/Veo video tier selector with visible per-image/per-video price labels.
- Onboarding still uses a local auto-advance calculation, but it now consumes the same dashboard status contract and lands on the correct explicit `?step=` when deep-linked.

### Competitors

`storyengine/frontend/src/app/competitors/page.tsx`

- Adds/removes competitor channels and scrapes videos.
- Shows distilled DNA badges where available.
- Model This now creates a paired StoryEngine video through the niche model endpoint.
- Paired competitor videos now show an Open Pair path when `our_video_id` exists.

### Pipeline / Ideas From Competitors

`storyengine/frontend/src/app/pipeline/page.tsx`

- Ideas From Competitors can launch competitor-backed video ideas.
- The ideas tab now has a Competitor-to-Video strip: add competitors, refresh ideas, create from a winner.
- Scratch creation is still available but labeled as secondary `Create From Scratch`.
- Create-from-scratch and idea launch now expose image/video model selection and pricing.
- In Production and Published video cards now show competitor-modeled/reference context, source channel/views where available, and selected image/video model tiers.
- Remaining issue: Competitors still has its own deeper analysis page, but the primary dashboard and pipeline entry points now share the same competitor-to-video flow language.

## Backend Surfaces Now Used

- `POST /api/onboarding/competitors/analyze`
- `GET /api/onboarding/competitors/status/{job_id}`
- `POST /api/onboarding/intelligence-report`
- `GET /api/onboarding/intelligence-report`
- `POST /api/niche/videos/{competitor_video_id}/model`
- `POST /api/discovery/ideas/{idea_id}/launch`
- `POST /api/videos`
- `GET /api/dashboard/onboarding/status`
- `GET /api/dashboard/summary` now includes `modeled_pairs` for source/reference visibility on the dashboard.
- `POST /api/onboarding/intelligence-report` now feeds recent/top competitor metrics plus distilled title/hook/thumbnail/content DNA into the recommendation prompt when available.
- `POST /api/onboarding/competitors/analyze` now performs a lightweight top-reference enrichment/distillation pass after scraping each channel.

## Required UX Changes

### P0: First-Run Flow

- Keep the onboarding path linear: YouTube, competitors, recommendations, first video. Implemented for the step order and first-video recommendation handoff.
- Show competitor analysis progress inside onboarding.
- Show generated title/hook/thumbnail recommendations before first video creation. Implemented for onboarding first-video handoff.
- If competitor analysis fails, show a direct retry and a clear skip path.

### P0: Paired Video Visibility

- Competitor cards must show when a reference has already been modeled.
- Competitor cards must link to the paired StoryEngine video.
- Dashboard must show recent modeled pairs without requiring the creator to find them in Competitors. Implemented with the Modeled References section.
- Pipeline detail should show the competitor source/reference when the video was modeled from one. Implemented with a top-level modeled-reference banner on the video workspace.
- Pipeline list cards should show modeled/reference context so paired videos are visible while scanning. Implemented with a compact reference strip on main video cards.

### P1: Recommendation Hub

- Merge the conceptual purpose of Competitors, Daily Ideas, and Discovery into one clear "Ideas From Competitors" entry point.
- Implemented for Dashboard and Pipeline primary entry points with `Ideas From Competitors` naming and a visible Competitor-to-Video strip.
- Dashboard should deep-link users to the exact next step, not just a broad page. Implemented for both the first-run launchpad and persistent setup banner through the backend `next_step` contract.
- Ideas From Competitors should show why a title was recommended: source video, VPH/views, hook pattern, title pattern, thumbnail pattern.
- Ideas should explain how to create the video with the available tools: research plan, script plan, visual prompt direction, thumbnail plan, and modeling mode. Implemented for onboarding intelligence reports and first-video handoff.

### P1: Style Modeling

- Add an explicit modeling choice before generation:
  - loose inspiration
  - match structure
  - match visual rhythm
  - close reference model
- Persist that choice into the video's prompt/context fields. Implemented for onboarding first-video handoff via `writer_guidance`.

### P2: Pipeline Next Action

- Each pipeline detail status should present one obvious primary button.
- Secondary controls should remain available but visually de-emphasized.
- Generated assets should always show where they were stored and what model generated them.

## Implementation Notes

- Supabase remains the source of truth.
- Competitor pairing uses `competitor_videos.our_video_id`.
- Kie.ai is the single required generation key; model selectors write `image_model_override` and `video_model` to `videos`.
- Google Drive remains required for production asset storage, but this UX map focuses on reducing creator confusion before generation starts.

## Latest Deployment Check

- Local frontend build passed.
- VPS frontend build passed.
- `backend/routes/dashboard.py` compiled locally and on the VPS.
- `storyengine.dev/api/health` returned `database:true`.
- `/dashboard` and `/onboarding?step=competitors` returned `200`.

## Remaining Verification Gap

- Need a logged-in browser pass with real competitor input to prove the full sequence: YouTube status, competitor analysis, title recommendation, modeling choice, created paired video, and visible paired reference in Dashboard/Pipeline/Competitors.
