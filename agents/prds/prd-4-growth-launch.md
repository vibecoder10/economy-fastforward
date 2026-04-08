# PRD 4: Growth & Launch — Learning Insights, Analytics, Docs, Demo, Beta Prep

**Priority:** Phase 4 (Growth + Launch Preparation)
**Estimated effort:** 10-12 tasks across frontend-dev, backend-dev, qa-engineer, security-auditor
**Depends on:** PRD 1 (auth/billing), PRD 2 (pipeline wiring), PRD 3 (critical bug fixes)
**Goal:** Ship the features that make users say "wow" and prepare for paying customers

---

## Context

StoryEngine has a working pipeline, auth, billing, and core UI. What's missing is the intelligence layer that makes users stick — the ability to see what the AI has learned about their audience, rich analytics that show improvement over time, and the polish needed for a public launch (docs, demo, legal pages).

The learning insights dashboard is the single most important feature in this PRD. It surfaces the competitive moat: "the AI knows my audience better every video." Everything else supports a credible beta launch.

---

## What EXISTS (do not rebuild)

- **Learnings page** (`/learnings`) — shows pattern cards with confidence bars, category filters, action buttons (extract/analyze). Uses `GET /api/learnings`, `POST /api/learnings/extract`, `POST /api/learnings/analyze-titles`, `POST /api/learnings/analyze-transcripts`.
- **Analytics page** (`/analytics`) — has overview stats (total videos, views, avg CTR, avg retention), CTR timeline line chart, framework effectiveness bar chart, video performance table. Uses `GET /api/analytics/overview`, `GET /api/analytics/ctr-timeline`, `GET /api/analytics/framework-performance`.
- **Learning extraction backend** (`routes/learning_extraction.py`) — 766 lines. Pattern detection for titles (10 patterns), hooks (4 patterns), scripts (8 patterns), competitor hooks (3 patterns). Upsert logic with weighted averaging.
- **Analytics backend** (`routes/analytics.py`) — 85 lines. Overview, CTR timeline, framework performance endpoints.
- **Learnings table** in Supabase — id, tenant_id, category, pattern, confidence, sample_size, avg_ctr, avg_retention, source_videos, active, created_date, last_updated.
- **Title insights table** — analysis_date, pattern_type, pattern_name, description, example_titles, avg_vph, count, confidence, videos_analyzed, vph_threshold.
- **Videos table** — has ctr, views, impressions, avg_retention, ctr_48h, retention_48h, views_24h/48h/7d/30d, performance_verdict, framework_angle, final_video_url.
- **Channel profiles table** — tenant_id, channel_name, niche, target_audience, frameworks.
- **Settings pages** — `/settings` and `/settings/keys` exist.
- **RenderTab component** — exists at `storyengine/frontend/src/components/production/RenderTab.tsx`.
- **Design system** — dark theme (charcoal bg), GlassCard, StatCard, ActionButton, FilterSelect, VerdictBadge, StatusPill, SegmentBadge, Spinner. CSS vars: `--turquoise`, `--gold`, `--purple`, `--green`, `--red`, `--amber`, `--bg-deep`, `--bg-elevated`, `--border`, `--text-primary/secondary/tertiary`.
- **Libraries** — Recharts, Framer Motion, Lucide icons, React Query, Tailwind CSS 4.

---

## Tasks

### T1: Learning Insights Dashboard — Redesign with Recommendations

**Role:** frontend-dev
**Priority:** CRITICAL — this is the moat feature

**Description:**
Redesign the `/learnings` page to transform it from a flat list of pattern cards into an intelligence dashboard that tells the user *what they should do differently*. The current page shows raw patterns — it needs to show actionable insights.

**Changes to `storyengine/frontend/src/app/learnings/page.tsx`:**

1. **Hero summary section** (top of page, replaces current header):
   - Large stat: "Your AI has analyzed X videos and discovered Y patterns"
   - Three mini stat cards in a row:
     - "Proven Patterns" (count, green) — confidence >= 60
     - "Being Tested" (count, amber) — confidence 40-60
     - "Anti-Patterns" (count, red) — confidence <= 40
   - Trend indicator: "3 new patterns discovered this week" (compare created_date)

2. **Top Recommendations section** (new, below hero):
   - Header: "What to Do Next" with Brain icon
   - Show up to 3 recommendation cards derived from proven + anti-patterns:
     - Example: "Use question-format titles — they get 5.2% CTR vs your 3.8% average" (from proven title patterns with avg_ctr > channel avg)
     - Example: "Avoid ALL CAPS emphasis — your videos with this pattern average 2.1% CTR" (from anti-patterns)
     - Example: "The counter-narrative hook is your best opener — 4 of 5 videos with it beat 5% CTR" (from proven hook patterns)
   - Each card: pattern name, comparison stat (pattern CTR vs channel avg), confidence bar, sample size
   - Derive recommendations client-side by comparing pattern avg_ctr against the overall channel avg CTR (fetch from `/api/analytics/overview`)
   - Use green/red backgrounds matching proven/avoid status

3. **Topic Performance section** (new):
   - Header: "Topic Performance" with Target icon
   - Use framework_performance data from `/api/analytics/framework-performance`
   - Small horizontal bar chart (Recharts BarChart, layout="vertical") showing avg CTR per framework
   - Color bars green (>5%), amber (3-5%), red (<3%)
   - Below chart: "Best topic: [framework] at X% CTR" callout

4. **Keep existing sections below:**
   - Action bar (extract/analyze buttons) — move below recommendations
   - Category filter tabs
   - Pattern cards grid (existing PatternCard component)
   - Competitor title patterns section

5. **Add trend arrows to PatternCard:**
   - Compare current avg_ctr to a baseline (channel avg from overview endpoint)
   - Show TrendingUp (green) if pattern CTR > channel avg, TrendingDown (red) if below
   - Add these as small indicators next to the CTR stat in the card

**Files to modify:**
- `storyengine/frontend/src/app/learnings/page.tsx` — main redesign
- `storyengine/frontend/src/lib/api.ts` — ensure `getAnalyticsOverview` and `getFrameworkPerformance` are importable (they already exist)

**Acceptance criteria:**
- [ ] Hero section shows video count, pattern counts by confidence tier
- [ ] "What to Do Next" shows 1-3 actionable recommendations derived from patterns vs channel avg
- [ ] Topic performance bar chart renders with framework data
- [ ] Trend arrows appear on pattern cards (up/down vs channel avg CTR)
- [ ] Page gracefully handles empty state (no learnings yet)
- [ ] All data sourced from existing endpoints (no new backend work needed)
- [ ] TypeScript compiles: `cd storyengine/frontend && npx tsc --noEmit`

---

### T2: Analytics 2.0 — Topic Heatmap & Competitor Benchmarking

**Role:** backend-dev + frontend-dev (backend first, then frontend)

**Description:**
Enhance the analytics page with two new sections: a topic performance breakdown (which topics get the best CTR for this user) and competitor benchmarking (how does this user's avg CTR compare to their niche competitors).

**Backend changes (`storyengine/backend/routes/analytics.py`):**

1. **New endpoint: `GET /api/analytics/topic-performance`**
   - Query: Group videos by a topic category derived from `framework_angle` or `thematic_framework`
   - Return: `[{ topic, video_count, avg_ctr, avg_views, avg_retention, best_video_title }]`
   - Sort by avg_ctr DESC
   - Only include topics with 2+ videos (statistical minimum)

2. **New endpoint: `GET /api/analytics/competitor-benchmark`**
   - Query: Calculate user's channel avg CTR from videos table, competitor niche avg VPH from competitor_videos table
   - Return: `{ channel_avg_ctr, channel_avg_retention, niche_avg_vph, competitor_count, top_competitor_vph, comparison_text }`
   - comparison_text: e.g., "Your avg CTR of 4.2% is above the niche average" or "below" based on a VPH-to-CTR heuristic (VPH > 100 suggests strong CTR)

**Frontend changes (`storyengine/frontend/src/app/analytics/page.tsx`):**

3. **Topic Performance section** (new, after framework effectiveness):
   - Horizontal bar chart showing avg CTR per topic
   - Color-coded: green (>5%), amber (3-5%), red (<3%)
   - Table below with: topic, video count, avg CTR, avg views, best video title (clickable to pipeline page)

4. **Competitor Benchmarking section** (new, after topic performance):
   - Comparison card: "Your Channel vs Niche"
   - Show: channel avg CTR (large number), niche competitor count, top competitor VPH
   - Visual comparison bar (your CTR position on a scale)
   - Text summary from comparison_text field

**Frontend changes (`storyengine/frontend/src/lib/api.ts`):**

5. Add `getTopicPerformance()` and `getCompetitorBenchmark()` API functions

**Files to modify:**
- `storyengine/backend/routes/analytics.py` — add 2 new endpoints
- `storyengine/frontend/src/app/analytics/page.tsx` — add 2 new sections
- `storyengine/frontend/src/lib/api.ts` — add 2 new fetch functions

**Acceptance criteria:**
- [ ] `GET /api/analytics/topic-performance` returns topic breakdown with CTR data
- [ ] `GET /api/analytics/competitor-benchmark` returns channel vs niche comparison
- [ ] Topic performance chart renders on analytics page
- [ ] Competitor benchmark card shows comparison data
- [ ] Both sections handle empty state gracefully (no videos / no competitors)
- [ ] Backend returns empty arrays/defaults when no data (never 500)
- [ ] curl tests pass for both new endpoints
- [ ] TypeScript compiles

---

### T3: Video Preview Player on Render Tab

**Role:** frontend-dev

**Description:**
After a video is rendered, show an in-app video player on the Render tab. Currently, users have to navigate to Google Drive to watch their rendered video. The `final_video_url` field on the videos table stores the Google Drive URL of the rendered MP4.

**Changes to `storyengine/frontend/src/components/production/RenderTab.tsx`:**

1. **Video player section** (appears when `video.final_video_url` exists):
   - HTML5 `<video>` element with native controls (play/pause, seek, volume, fullscreen)
   - Poster: use `video.thumbnail_url` if available
   - Source: `video.final_video_url` — note this is a Google Drive URL. If it's a Drive link (contains `drive.google.com`), convert to direct download format: replace `/file/d/FILE_ID/view` with `https://drive.google.com/uc?export=download&id=FILE_ID`
   - Fallback: if video can't play (CORS, expired URL), show message "Video available on Google Drive" with a link button
   - Style: full-width, 16:9 aspect ratio container, rounded corners, dark background

2. **Video metadata bar** (below player):
   - Duration: from `video.video_length_minutes` (format as M:SS)
   - Status badge: "Rendered" (green) or "Uploaded" (blue) based on video status
   - Download button: links to `video.final_video_url` with `target="_blank"`
   - Open in Drive button: links to `video.drive_folder_link` if available

3. **Placement:** Above the existing render controls/timeline. Only show the player section if `final_video_url` is non-null.

**Files to modify:**
- `storyengine/frontend/src/components/production/RenderTab.tsx`

**Acceptance criteria:**
- [ ] Video player appears when `final_video_url` exists on the video
- [ ] Player uses HTML5 video element with native controls
- [ ] Google Drive URLs are converted to playable format
- [ ] Fallback message shown when video can't be played inline
- [ ] Download button opens video URL in new tab
- [ ] Thumbnail poster displayed before play
- [ ] Metadata bar shows duration and status
- [ ] Player section hidden when no `final_video_url`
- [ ] TypeScript compiles

---

### T4: Brand Kit — Per-Channel Visual Identity

**Role:** backend-dev + frontend-dev (backend first)

**Description:**
Add a brand kit section to the settings page where users configure their channel's visual identity: accent color, logo, and intro/outro text. These values are stored in `channel_profiles` and passed to the render pipeline.

**Backend changes:**

1. **Extend `channel_profiles` table** — add columns via migration (`storyengine/backend/migrations/029_brand_kit.sql`):
   ```sql
   ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS logo_url TEXT;
   ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS accent_color TEXT DEFAULT '#00D4AA';
   ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS intro_text TEXT DEFAULT '';
   ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS outro_text TEXT DEFAULT '';
   ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS watermark_url TEXT;
   ```

2. **Extend `ChannelProfileUpdate` model** in `routes/channel_profile.py`:
   - Add optional fields: `logo_url`, `accent_color`, `intro_text`, `outro_text`, `watermark_url`
   - The existing PATCH endpoint already does dynamic updates — just add the fields to the model and the SQL update builder

3. **Extend GET response** to include the new fields

**Frontend changes (`storyengine/frontend/src/app/settings/page.tsx`):**

4. **Brand Kit section** (new section on settings page):
   - Section header: "Brand Kit" with Palette icon
   - Accent color picker: show 4 preset swatches (teal `#00D4AA`, amber `#FFB800`, crimson `#C44545`, purple `#8B5CF6`) + custom hex input
   - Logo URL: text input (paste URL) with preview thumbnail. Full upload to Supabase Storage is a future enhancement — URL input for v1.
   - Intro text: text input, placeholder "Economy FastForward presents..."
   - Outro text: text input, placeholder "Subscribe for more analysis"
   - Watermark URL: text input with preview
   - Save button calls PATCH `/api/channel-profile` with the brand fields
   - Load current values from GET `/api/channel-profile`

**Files to modify:**
- `storyengine/backend/migrations/029_brand_kit.sql` — new migration
- `storyengine/backend/routes/channel_profile.py` — extend model + ensure new columns in table creation
- `storyengine/frontend/src/app/settings/page.tsx` — add Brand Kit section

**Acceptance criteria:**
- [ ] Migration adds 5 new columns to `channel_profiles`
- [ ] PATCH `/api/channel-profile` accepts and persists brand kit fields
- [ ] GET `/api/channel-profile` returns brand kit fields
- [ ] Settings page shows Brand Kit section with color picker, text inputs, URL inputs
- [ ] Color picker has 4 preset swatches + custom hex input
- [ ] Logo/watermark URL inputs show image preview when URL is provided
- [ ] Save persists values and shows success toast
- [ ] curl test: PATCH with accent_color → GET returns it
- [ ] TypeScript compiles

---

### T5: Getting Started Guide & Help Page

**Role:** frontend-dev

**Description:**
Add a `/docs` page with a getting started guide, FAQ, and troubleshooting tips. Use a simple tabbed layout with markdown-style content rendered as JSX (no external docs platform for v1). Add a help button in the sidebar navigation that links to this page.

**Create `storyengine/frontend/src/app/docs/page.tsx`:**

1. **Tab layout** with 3 tabs: "Getting Started", "FAQ", "Troubleshooting"

2. **Getting Started tab:**
   - Step 1: Connect Your YouTube Channel — go to Settings > Keys, enter YouTube API credentials, connect OAuth
   - Step 2: Create Your First Video — go to Create, enter a topic or paste a competitor URL, pick a title from AI suggestions, click "Start Pipeline"
   - Step 3: Review & Publish — the pipeline runs 8 stages automatically. Review the script, visuals, and thumbnail on the Pipeline page. When satisfied, download the rendered video and upload to YouTube.
   - Each step: numbered card with icon, title, description, link button to relevant page

3. **FAQ tab** (10 items, collapsible accordion):
   - "How long does it take to produce a video?" — 30-60 minutes depending on length and pipeline stages enabled
   - "What visual styles are available?" — Cinematic Illustration (default), Holographic HUD, Cinematic Dossier, Clay Mannequin
   - "Can I edit the script before rendering?" — Yes, edit on the Script tab in the Pipeline page
   - "How does the AI learn from my videos?" — After publishing, sync YouTube metrics. The system extracts patterns from CTR/retention data. See the Learnings page.
   - "What if a pipeline stage fails?" — Check the Activity log. Most stages can be retried. Contact support if persistent.
   - "How do I change the voice?" — Go to Settings > Keys and update your ElevenLabs voice ID
   - "Can I use my own images?" — Upload character references on the Pipeline page visuals tab
   - "What's the Autopilot?" — Autonomous mode that picks ideas, generates videos, and learns from performance. Enable on the Autopilot page.
   - "How is my data stored?" — All data is stored in your private tenant. Videos and assets are stored on secure cloud storage.
   - "How do I cancel my subscription?" — Go to Settings > Billing and click "Manage Subscription" to access the Stripe customer portal.

4. **Troubleshooting tab:**
   - "Pipeline stuck on a stage" — check the Activity log, try "Skip Stage" or re-run the step
   - "YouTube sync fails" — re-connect YouTube OAuth on Settings > Keys. Ensure the YouTube Data API is enabled in Google Cloud Console.
   - "Images look wrong" — try changing the visual style or adding an image style override on the Pipeline page
   - "Video won't render" — ensure all scenes have voice audio and at least one image. Check the Render tab for error messages.
   - "API key not working" — verify the key on the provider's dashboard. Keys are stored encrypted and never exposed after saving.
   - Each item: collapsible card with problem and solution

5. **Sidebar link:** Add a HelpCircle icon link to `/docs` in the sidebar navigation component

**Files to create/modify:**
- `storyengine/frontend/src/app/docs/page.tsx` — new page
- `storyengine/frontend/src/components/nav/` — add `/docs` link to sidebar (find the sidebar/nav component and add entry)

**Acceptance criteria:**
- [ ] `/docs` page renders with 3 tabs
- [ ] Getting Started shows 3 steps with links to relevant pages
- [ ] FAQ shows 10 collapsible items
- [ ] Troubleshooting shows 5 collapsible items
- [ ] Sidebar navigation includes "Help" link with HelpCircle icon
- [ ] Page uses existing design system (GlassCard, dark theme, CSS variables)
- [ ] No external dependencies added (pure JSX, no markdown parser)
- [ ] TypeScript compiles

---

### T6: Demo Mode — Browse Without Signup

**Role:** backend-dev + frontend-dev (backend first)

**Description:**
Add a public demo at `/demo` with pre-loaded sample data so potential users can see StoryEngine in action before signing up. The demo shows read-only versions of the dashboard, pipeline, and analytics with realistic sample data.

**Backend changes:**

1. **Create `storyengine/backend/routes/demo.py`** with 3 endpoints (no auth required):

   - `GET /api/demo/dashboard` — returns static demo data:
     ```json
     {
       "active_videos": 3,
       "completed_videos": 12,
       "avg_ctr": 4.8,
       "total_views": 245000,
       "recent_videos": [
         { "title": "Why China's $3T Dollar Trap Changes Everything", "status": "done", "views": 52000, "ctr": 5.2 },
         { "title": "The Hidden War for Semiconductor Supply Chains", "status": "rendered", "views": 0, "ctr": null },
         { "title": "Russia's Arctic Gambit: $500B Under the Ice", "status": "ready_for_images", "views": 0, "ctr": null }
       ]
     }
     ```

   - `GET /api/demo/analytics` — returns static analytics:
     ```json
     {
       "overview": { "total_videos": 15, "published_videos": 12, "total_views": 245000, "avg_ctr": 4.8, "avg_retention": 42.3 },
       "ctr_timeline": [
         { "date": "2026-03-01", "video_title": "...", "ctr": 3.2, "views": 12000 },
         ...
       ],
       "top_patterns": [
         { "pattern": "Question-format titles", "avg_ctr": 5.4, "sample_size": 6, "confidence": 78 },
         { "pattern": "Counter-narrative hooks", "avg_ctr": 5.1, "sample_size": 4, "confidence": 65 }
       ]
     }
     ```

   - `GET /api/demo/pipeline` — returns a single video mid-pipeline:
     ```json
     {
       "video_title": "The Hidden War for Semiconductor Supply Chains",
       "status": "ready_for_images",
       "scenes": 6,
       "stages_complete": ["script", "voice", "image_prompts"],
       "stages_remaining": ["images", "video_clips", "thumbnail", "sound", "render"],
       "script_preview": "In the shadow of every smartphone, every electric car, every military drone..."
     }
     ```

2. **Register in `main.py`** — import and include the demo router (no auth prefix)

**Frontend changes:**

3. **Create `storyengine/frontend/src/app/demo/page.tsx`** — demo landing page:
   - Header: "See StoryEngine in Action" with Sparkles icon
   - Three demo section cards linking to sub-pages:
     - "Dashboard" — see video production overview
     - "Analytics" — see AI learning insights
     - "Pipeline" — see a video being produced
   - CTA banner at bottom: "Ready to create your own videos? Start your free trial" → link to `/login`

4. **Create `storyengine/frontend/src/app/demo/dashboard/page.tsx`**:
   - Simplified dashboard using demo data from `GET /api/demo/dashboard`
   - Show recent videos list, stats cards (videos, views, CTR, retention)
   - "DEMO" badge in top-right corner
   - CTA: "Start your free trial to create videos"

5. **Create `storyengine/frontend/src/app/demo/analytics/page.tsx`**:
   - CTR timeline chart, top patterns list, overview stats
   - Uses demo data from `GET /api/demo/analytics`
   - "DEMO" badge, CTA

6. **Create `storyengine/frontend/src/app/demo/pipeline/page.tsx`**:
   - Show pipeline stages with a video mid-progress
   - Completed stages green, current stage amber, remaining stages gray
   - Script preview text
   - "DEMO" badge, CTA

**Files to create/modify:**
- `storyengine/backend/routes/demo.py` — new file, 3 endpoints
- `storyengine/backend/main.py` — register demo router
- `storyengine/frontend/src/app/demo/page.tsx` — demo landing
- `storyengine/frontend/src/app/demo/dashboard/page.tsx` — demo dashboard
- `storyengine/frontend/src/app/demo/analytics/page.tsx` — demo analytics
- `storyengine/frontend/src/app/demo/pipeline/page.tsx` — demo pipeline

**Acceptance criteria:**
- [ ] All 3 demo API endpoints return static data without auth
- [ ] Demo landing page links to 3 sub-pages
- [ ] Each demo page shows realistic sample data
- [ ] "DEMO" badge visible on all demo pages
- [ ] CTA on every demo page links to `/login`
- [ ] No auth required for any `/demo/*` route
- [ ] Demo router registered in `main.py`
- [ ] TypeScript compiles

---

### T7: Legal Pages — Terms of Service & Privacy Policy

**Role:** frontend-dev

**Description:**
Add `/terms` and `/privacy` pages with standard SaaS legal content. These are required before accepting paying users. Link from the signup page footer and the main app footer/sidebar.

**Create pages:**

1. **`storyengine/frontend/src/app/(public)/terms/page.tsx`** — Terms of Service:
   - Sections: Acceptance, Account Terms, API Usage, Content Ownership, AI-Generated Content, Billing & Refunds, Acceptable Use, Termination, Limitation of Liability, Changes to Terms
   - Key clause: "Content generated by StoryEngine using your inputs belongs to you. StoryEngine retains no ownership of your generated videos, scripts, images, or other creative output."
   - Key clause: "AI-generated content may contain inaccuracies. You are responsible for reviewing all output before publishing."
   - Key clause: "Subscription fees are billed monthly. You may cancel at any time through the billing portal. No refunds for partial months."
   - Date: "Last updated: April 2026"

2. **`storyengine/frontend/src/app/(public)/privacy/page.tsx`** — Privacy Policy:
   - Sections: Information We Collect, How We Use It, Data Storage, Third-Party Services, Data Retention, Your Rights, Cookies, Changes, Contact
   - Key clause: "We store your channel data, API keys (encrypted), and generated content in secure cloud infrastructure (Supabase PostgreSQL). Your data is isolated by tenant — no other user can access your content."
   - Key clause: "We use third-party AI services (Anthropic Claude, ElevenLabs, Kie.ai) to generate content. Prompts and outputs may be processed by these services according to their privacy policies."
   - Key clause: "You may request deletion of all your data at any time by contacting support."

3. **Footer links:** Add "Terms" and "Privacy" links to the login page and any existing footer component

**Files to create/modify:**
- `storyengine/frontend/src/app/(public)/terms/page.tsx` — new page
- `storyengine/frontend/src/app/(public)/privacy/page.tsx` — new page
- Login page (`storyengine/frontend/src/app/login/page.tsx`) — add footer links

**Acceptance criteria:**
- [ ] `/terms` page renders with all required legal sections
- [ ] `/privacy` page renders with all required privacy sections
- [ ] Both pages are accessible without authentication
- [ ] Login page has footer links to terms and privacy
- [ ] Content ownership clause clearly states user owns generated content
- [ ] AI content disclaimer is present
- [ ] Pages use consistent styling (dark theme, readable text, proper headings)
- [ ] TypeScript compiles

---

### T8: Export & Download — Video Assets Package

**Role:** backend-dev + frontend-dev

**Description:**
Add the ability to download all assets for a video: the rendered MP4, script text, thumbnail image, and a metadata JSON. This gives users a complete deliverable they can take to other platforms.

**Backend changes (`storyengine/backend/routes/videos.py` or new `routes/export.py`):**

1. **New endpoint: `GET /api/videos/{video_id}/export-manifest`**
   - Returns a JSON manifest of all downloadable assets:
     ```json
     {
       "video_title": "...",
       "files": [
         { "type": "video", "label": "Final Video (MP4)", "url": "...", "size_hint": null },
         { "type": "script", "label": "Script (text)", "content": "...", "format": "text" },
         { "type": "thumbnail", "label": "Thumbnail (PNG)", "url": "..." },
         { "type": "metadata", "label": "Video Metadata (JSON)", "content": { "title": "...", "seo_description": "...", "seo_tags": "...", "seo_hashtags": "...", "sources": "..." } }
       ]
     }
     ```
   - Pull from: `final_video_url`, `script`, `thumbnail_url`, `seo_description`, `seo_tags`, `seo_hashtags`, `sources` on the videos table
   - Auth required (tenant_id check)

**Frontend changes:**

2. **Export button on video detail page:**
   - Add a "Download All" or "Export" button (Download icon) in the video detail header area
   - On click: fetch export manifest → show modal with file list → each file has a download link/button
   - Script and metadata: generate as blob URLs for direct download (create text/json files client-side)
   - Video and thumbnail: open URL in new tab (Google Drive)
   - Use existing GlassCard styling for the modal

**Files to create/modify:**
- `storyengine/backend/routes/videos.py` — add export-manifest endpoint (or create `routes/export.py`)
- `storyengine/backend/main.py` — register export router if new file
- `storyengine/frontend/src/components/production/` or `storyengine/frontend/src/components/video-detail/` — add export button + modal
- `storyengine/frontend/src/lib/api.ts` — add `getExportManifest(videoId)` function

**Acceptance criteria:**
- [ ] `GET /api/videos/{video_id}/export-manifest` returns all available assets
- [ ] Endpoint enforces tenant_id auth
- [ ] Export button appears on video detail page
- [ ] Modal shows list of available files with download actions
- [ ] Script downloads as .txt file
- [ ] Metadata downloads as .json file
- [ ] Video/thumbnail open in new tab
- [ ] Handles missing assets gracefully (video not rendered yet = no video file in manifest)
- [ ] TypeScript compiles

---

### T9: Notification Preferences — Email Digest Opt-in

**Role:** backend-dev

**Description:**
Add a notification preferences system so users can opt-in to email notifications. This is the backend foundation for future email digests (weekly performance summary, pipeline completion alerts). No email sending in this task — just the preference storage and API.

**Backend changes:**

1. **Extend `user_preferences` table** — migration `storyengine/backend/migrations/030_notification_prefs.sql`:
   ```sql
   ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS email_pipeline_complete BOOLEAN DEFAULT true;
   ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS email_weekly_digest BOOLEAN DEFAULT true;
   ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS email_performance_alerts BOOLEAN DEFAULT true;
   ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS email_marketing BOOLEAN DEFAULT false;
   ```

2. **New endpoint: `GET /api/preferences/notifications`** in `routes/preferences.py`:
   - Returns current notification preference booleans
   - Default all to true (except marketing = false) if no row exists

3. **New endpoint: `PATCH /api/preferences/notifications`** in `routes/preferences.py`:
   - Accept partial update of notification booleans
   - Upsert into user_preferences

4. **Frontend: add Notifications section to settings page**
   - Toggle switches for each notification type
   - Labels: "Pipeline Complete" (when a video finishes rendering), "Weekly Digest" (performance summary), "Performance Alerts" (CTR drops), "Marketing" (product updates)
   - Save on toggle (optimistic update with React Query mutation)

**Files to create/modify:**
- `storyengine/backend/migrations/030_notification_prefs.sql` — new migration
- `storyengine/backend/routes/preferences.py` — add 2 notification endpoints
- `storyengine/frontend/src/app/settings/page.tsx` — add Notifications section with toggles

**Acceptance criteria:**
- [ ] Migration adds 4 boolean columns to user_preferences
- [ ] GET endpoint returns notification preferences with defaults
- [ ] PATCH endpoint persists preference changes
- [ ] Settings page shows notification toggles
- [ ] Toggles reflect current state from API
- [ ] Toggling a switch calls PATCH immediately (optimistic update)
- [ ] curl test: PATCH email_weekly_digest=false → GET returns false
- [ ] TypeScript compiles

---

### T10: Beta Launch Regression & E2E Verification

**Role:** qa-engineer

**Description:**
Run a comprehensive regression sweep across all pages and API endpoints, including all features from PRDs 1-4. This is the final QA gate before accepting beta users. Test the complete user journey: signup → onboarding → create video → pipeline → render → analytics → learnings → export → billing.

**Test Plan:**

1. **Page load sweep** (all pages load without console errors):
   - `/login`, `/onboarding`, `/` (dashboard), `/create`, `/pipeline`, `/pipeline/{id}` (all 7+ tabs)
   - `/analytics`, `/learnings`, `/competitors`, `/autopilot`, `/calendar`, `/discovery`
   - `/settings`, `/settings/keys`, `/billing`, `/review`, `/activity`
   - `/docs`, `/demo`, `/demo/dashboard`, `/demo/analytics`, `/demo/pipeline`
   - `/terms`, `/privacy`
   - Total: 25+ pages

2. **API endpoint verification** (all return 200/expected status):
   - Auth: POST login, POST register, GET /api/profile
   - Videos: GET list, GET detail, POST create, PATCH update
   - Pipeline: POST run-stage for each stage, GET task-status
   - Analytics: GET overview, GET ctr-timeline, GET framework-performance, GET topic-performance, GET competitor-benchmark
   - Learnings: GET list, POST extract, POST analyze-titles, POST analyze-transcripts, PATCH toggle
   - Settings: GET/PATCH channel-profile, GET/PATCH preferences/notifications
   - Export: GET /api/videos/{id}/export-manifest
   - Demo: GET dashboard, GET analytics, GET pipeline (no auth)
   - Billing: GET subscription-status, POST create-checkout
   - Total: 30+ endpoints

3. **User journey E2E test:**
   - Signup with email/password → onboarding wizard completes → dashboard loads
   - Create a video (enter topic) → pipeline page shows new video
   - Navigate through pipeline tabs: script, voice, visuals, video clips, thumbnail, sound, render
   - Check analytics page loads with charts
   - Check learnings page shows recommendations section
   - Check demo pages load without auth
   - Check export manifest returns data for a video
   - Check settings page shows brand kit and notification preferences

4. **Empty state verification:**
   - New user with no videos: dashboard, analytics, learnings, competitors, calendar all show helpful empty states (not blank/broken)

5. **Mobile responsiveness:**
   - Check all new pages (docs, demo, terms, privacy, learnings redesign) at 375px width
   - Verify no horizontal scroll, no overlapping elements

**Files to reference:**
- Use Playwright (`webapp-testing` skill) for browser-based verification
- Check browser console for errors on each page

**Acceptance criteria:**
- [ ] All 25+ pages load without JavaScript errors
- [ ] All 30+ API endpoints return expected status codes
- [ ] Signup → onboarding → dashboard E2E flow works
- [ ] Empty states show on all pages for new users
- [ ] Mobile layout works on all new pages
- [ ] No console errors or warnings on any page
- [ ] Create launch-blockers list documenting any remaining issues
- [ ] All issues categorized: P0 (blocks launch), P1 (fix first week), P2 (fix later)

---

### T11: Security Audit — Pre-Launch Hardening

**Role:** security-auditor

**Description:**
Comprehensive security review of all code from PRDs 1-4 before accepting beta users. Focus on auth bypass vectors, data isolation, and exposed secrets.

**Audit Checklist:**

1. **Auth verification:**
   - Verify ALL route files use `Depends(get_tenant_id)` — grep for any routes missing auth
   - Confirm demo routes (`/api/demo/*`) are the ONLY unauthenticated endpoints (besides login/register)
   - Verify JWT token validation rejects expired/malformed tokens
   - Check that dev-token bypass is documented and flagged for removal

2. **Data isolation:**
   - Verify all SQL queries include `WHERE tenant_id = $1` — grep all `fetch_all`/`fetch_one`/`execute` calls
   - Check new endpoints (topic-performance, competitor-benchmark, export-manifest, notifications) all enforce tenant isolation
   - Verify demo endpoints return only static data (no database queries that could leak tenant data)

3. **Input validation:**
   - Check all PATCH/POST endpoints validate input (Pydantic models)
   - Verify no SQL injection vectors (all queries use parameterized `$1, $2` syntax, no f-strings)
   - Check export manifest doesn't expose internal URLs or file paths

4. **Sensitive data:**
   - Verify API keys in settings are never returned in full (masked/redacted)
   - Check that brand kit URLs don't expose internal storage paths
   - Verify no secrets in demo static data

5. **CORS/headers:**
   - Verify CORS allowlist is appropriate for production
   - Check Content-Security-Policy headers if any

**Files to audit:**
- All files in `storyengine/backend/routes/` — auth check on every endpoint
- `storyengine/backend/auth.py` — JWT validation logic
- `storyengine/backend/routes/demo.py` — verify no DB queries
- `storyengine/backend/routes/analytics.py` — tenant isolation on new endpoints
- `storyengine/backend/routes/preferences.py` — tenant isolation on notification prefs
- `storyengine/backend/main.py` — CORS configuration

**Acceptance criteria:**
- [ ] All routes (except demo/login/register) require valid JWT
- [ ] All database queries enforce tenant_id isolation
- [ ] No SQL injection vectors found (all parameterized)
- [ ] Demo endpoints return only hardcoded static data
- [ ] API keys are never returned unmasked
- [ ] No secrets or internal paths exposed in any response
- [ ] Security report written with findings categorized: CRITICAL, HIGH, MEDIUM, LOW
- [ ] All CRITICAL and HIGH findings have fix recommendations

---

### T12: Performance & Load Readiness Check

**Role:** qa-engineer

**Description:**
Before accepting beta users, verify the app performs acceptably under normal usage. This is not a full load test — it's a sanity check that pages load fast and the API responds quickly.

**Test Plan:**

1. **Page load times** (using Playwright or browser dev tools):
   - Target: every page loads in under 3 seconds on localhost
   - Check: dashboard, analytics (with charts), learnings, pipeline detail, demo pages
   - Flag any page taking over 5 seconds

2. **API response times** (using curl with timing):
   - Target: all API endpoints respond in under 500ms
   - Check: analytics overview (aggregation query), learnings list, video list, export manifest
   - Flag any endpoint taking over 1 second

3. **Frontend build health:**
   - `npm run build` completes without errors
   - `npx tsc --noEmit` passes
   - Bundle size check: note the output of `npm run build` (page sizes)
   - Flag any page bundle over 500KB

4. **Backend health:**
   - `/api/health` endpoint responds (or create one if missing)
   - Database connection pool works under concurrent requests (5 simultaneous curls)
   - No memory leaks in background tasks (check process memory after 10 minutes)

5. **Lighthouse audit** (optional, if Playwright supports it):
   - Run Lighthouse on demo landing page
   - Target: Performance > 70, Accessibility > 80

**Files to check:**
- `storyengine/frontend/` — build output, bundle sizes
- `storyengine/backend/main.py` — health endpoint
- All new pages from this PRD

**Acceptance criteria:**
- [ ] All pages load in under 3 seconds
- [ ] All API endpoints respond in under 500ms
- [ ] Frontend build succeeds with no errors
- [ ] TypeScript compilation passes
- [ ] No page bundle exceeds 500KB
- [ ] Performance report with timings for all pages and critical endpoints
- [ ] Any P0 performance issues documented with fix recommendations

---

## Execution Order

The tasks should be executed in this order to minimize blocking:

1. **T2** (Analytics backend) — backend-dev ships new endpoints first
2. **T4** (Brand Kit backend) — backend-dev ships migration + endpoint extensions
3. **T9** (Notification Prefs backend) — backend-dev ships preference endpoints
4. **T6** (Demo Mode backend) — backend-dev ships demo endpoints
5. **T8** (Export backend) — backend-dev ships export manifest
6. **T1** (Learning Insights redesign) — frontend-dev, depends on T2 being available
7. **T3** (Video Preview Player) — frontend-dev, independent
8. **T5** (Docs page) — frontend-dev, independent
9. **T7** (Legal pages) — frontend-dev, independent
10. **T6** (Demo Mode frontend) — frontend-dev, depends on demo backend
11. **T8** (Export frontend) — frontend-dev, depends on export backend
12. **T4** (Brand Kit frontend) — frontend-dev, depends on brand kit backend
13. **T9** (Notification Prefs frontend) — frontend-dev, depends on prefs backend
14. **T10** (Regression sweep) — qa-engineer, after all features shipped
15. **T11** (Security audit) — security-auditor, after all features shipped
16. **T12** (Performance check) — qa-engineer, after all features shipped

Backend tasks (T2, T4, T6, T8, T9 backend) can run in parallel.
Frontend tasks (T1, T3, T5, T7) can run in parallel.
QA + Security (T10, T11, T12) run last, in parallel with each other.

---

## Success Criteria (PRD Complete)

- [ ] Learning insights page shows actionable recommendations derived from AI patterns
- [ ] Analytics page has topic performance and competitor benchmarking sections
- [ ] Video preview player works on rendered videos
- [ ] Brand kit settings allow accent color, logo URL, intro/outro text
- [ ] Getting started guide helps new users onboard
- [ ] Demo mode lets prospects explore without signup
- [ ] Terms of Service and Privacy Policy pages exist
- [ ] Export manifest provides all video assets for download
- [ ] Notification preferences are configurable
- [ ] Full regression sweep passes with 0 P0 blockers
- [ ] Security audit passes with 0 CRITICAL findings
- [ ] Performance check shows acceptable load times
- [ ] Product is ready for beta users
