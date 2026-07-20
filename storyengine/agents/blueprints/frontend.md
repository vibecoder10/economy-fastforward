# Frontend Blueprint

## Design System

### Stack
Next.js 16 (App Router) | React 19 | TypeScript | TailwindCSS 4 | Framer Motion | React Query (TanStack) | Lucide Icons | Recharts (analytics)

### Fonts (loaded via Google Fonts in layout.tsx)
- **Outfit** (body, `font-body`): weights 300-700
- **Playfair Display** (display, `font-display`): weights 700-800
- **JetBrains Mono** (mono, `font-mono`): weights 400-500

### Color Tokens (CSS variables in globals.css)
Backgrounds: `--bg-void: #05080D` | `--bg-deep: #0A0E16` | `--bg-surface: #0F1420` | `--bg-elevated: #141A28`
Accents: `--turquoise: #00D4AA` (primary) | `--gold: #D4A852` (cost/warnings) | `--orange: #FF7849` (current step) | `--red: #FF4D6A` (errors) | `--green: #00E68A` (success) | `--purple: #8B5CF6` (generation) | `--yellow: #FFD058` (steady)
Text: `--text-primary: #F0F2F8` | `--text-secondary: #7A8199` | `--text-tertiary: #4A5068`
Borders: `--border: rgba(0,212,170,0.12)` | `--border-subtle: rgba(255,255,255,0.06)`
Each color has a `-dim` variant at 15% opacity for pill/badge backgrounds.
Aliases: `--accent` = turquoise, `--success` = green, `--error` = red, `--warning` = orange.

### Glass Card Effect
`.glass-card` — `background: rgba(15,22,38,0.65)`, `border: 1px solid rgba(0,212,170,0.12)`, `border-radius: 16px`, `backdrop-filter: blur(24px)`. Top gradient line via `::before`.

### Animations
`animate-pulse-dot` (opacity 2s), `animate-pulse-glow` (box-shadow 3s). Framer Motion stagger: `container = { staggerChildren: 0.08 }`, `item = { y: 16 -> 0, opacity: 0 -> 1 }`.

### Spacing
`--space-xs: 4px` | `sm: 8px` | `md: 16px` | `lg: 24px` | `xl: 32px` | `2xl: 48px`. Card radius: `16px`.

---

## Pages & Routes

| Route | File | Purpose |
|-------|------|---------|
| `/` | `app/page.tsx` | Production overview — stat cards, pipeline bar chart, activity feed, recent videos |
| `/dashboard` | `app/dashboard/page.tsx` | Dashboard — stats, pipeline distribution, approval queue, recent videos |
| `/pipeline` | `app/pipeline/page.tsx` | Video list with filters + create video modal + discovery ideas panel |
| `/pipeline/[videoId]` | `app/pipeline/[videoId]/page.tsx` | Video detail — 8-tab production view (Research, Script, Storyboard, Clips, Thumbnail, Render, Upload, Performance) |
| `/review` | `app/review/page.tsx` | Pending review queue — scripts, storyboards, thumbnails, images |
| `/activity` | `app/activity/page.tsx` | Activity feed with filters (all/running/errors/completed) + bot stats |
| `/analytics` | `app/analytics/page.tsx` | Performance analytics — CTR/views charts (Recharts), video table, learnings, YouTube sync |
| `/autopilot` | `app/autopilot/page.tsx` | Autopilot control — toggle on/off, config, candidates, learnings |
| `/competitors` | `app/competitors/page.tsx` | Competitor channels + candidate cards + niche setup + scraping |
| `/profile` | `app/profile/page.tsx` | Visual style manager — create/activate/delete styles, character references, image analysis |
| `/settings` | `app/settings/page.tsx` | Project settings — name, niche, audience, frameworks, accent color, visual style |
| `/settings/keys` | `app/settings/keys/page.tsx` | API key management — configure, test, reveal keys |
| `/storyboard` | `app/storyboard/page.tsx` | Storyboard overview — all videos at storyboard stage |
| `/visuals` | `app/visuals/page.tsx` | Visuals overview — all videos at image stage with progress rings |
| `/render` | `app/render/page.tsx` | Render overview — all videos at render stage with asset counts |

### Layout (`app/layout.tsx`)
`Providers` (QueryClient) > `AmbientBackground` + `Sidebar` (fixed left 60/240px) + `<main class="flex-1 md:ml-60 max-w-[1400px]">` + `BottomTabs` (mobile).

---

## API Functions (api.ts)

Base: `fetchApi<T>(path, options?)` — prepends `NEXT_PUBLIC_API_URL` (default `http://localhost:8001`), adds Bearer token from localStorage.

| Function | Return | Endpoint |
|----------|--------|----------|
| **Dashboard** | | |
| `getDashboardSummary()` | `DashboardSummary` | `GET /api/dashboard/summary` |
| **Videos** | | |
| `getVideos(status?)` | `VideoSummary[]` | `GET /api/videos?status=` |
| `getVideo(id)` | `VideoDetail` | `GET /api/videos/{id}` |
| `createVideo({title, source_url?, framework_angle?, video_length_minutes?})` | `VideoSummary` | `POST /api/videos` |
| `advanceVideo(id)` | `{status}` | `PATCH /api/videos/{id}/advance` |
| `updateVideo(id, data)` | `{status}` | `PATCH /api/videos/{id}` |
| `rejectVideo(id, reason?)` | `{status}` | `PATCH /api/videos/{id}/reject` |
| `getVideoAssets(id)` | `Asset[]` | `GET /api/videos/{id}/assets` |
| `getImageVariants(videoId, scene, index)` | `ImageVariant[]` | `GET /api/videos/{id}/assets/variants?scene=&index=` |
| `getVideoScript(id)` | `ScriptScene[]` | `GET /api/videos/{id}/script` |
| `updateVideoStyles(id, {visual_style?, accent_color?, image_model_override?, video_model?})` | `StyleUpdateResponse` | `PATCH /api/videos/{id}/styles?...` |
| **Assets** | | |
| `approveAsset(id)` | `{status}` | `PATCH /api/assets/{id}/approve` |
| `rejectAsset(id)` | `{status}` | `PATCH /api/assets/{id}/reject` |
| `batchApproveAssets(assetIds, status)` | `{updated}` | `POST /api/assets/batch-approve` |
| **Review** | | |
| `getPendingReview()` | `PendingReview` | `GET /api/review/pending` |
| **Activity** | | |
| `getActivity(status?)` | `ActivityEntry[]` | `GET /api/activity?status=` |
| `getActivityStats()` | `ActivityStats` | `GET /api/activity/stats` |
| **Pipeline** | | |
| `createIdea(topic, source?)` | `PipelineResponse` | `POST /api/pipeline/create-idea` |
| `runPipelineStage(videoId, stage, params?)` | `PipelineResponse` | `POST /api/pipeline/{stage}/{videoId}?...` |
| `runNextStep(videoId)` | `PipelineResponse` | `POST /api/pipeline/run-next/{videoId}` |
| `getPipelineStatus(videoId)` | `PipelineStatus` | `GET /api/pipeline/status/{videoId}` |
| `getPipelineTaskStatus(videoId)` | `TaskStatus` | `GET /api/pipeline/task/{videoId}` |
| `clearStaleTask(videoId)` | `{status}` | `DELETE /api/pipeline/task/{videoId}/clear` |
| `resetPipeline(videoId, resetTo)` | `{status, deleted}` | `POST /api/pipeline/reset/{videoId}` |
| `runSplit(videoId)` | `SplitResult` | `POST /api/pipeline/split/{videoId}` |
| `runPromptsForScene(videoId, scene)` | `PipelineResponse` | `POST /api/pipeline/prompts/{videoId}?scene=` |
| `runPromptsForSegment(videoId, scene, index)` | `PipelineResponse` | `POST /api/pipeline/prompts/{videoId}?scene=&index=` |
| `runVoiceForScene(videoId, scene)` | `PipelineResponse` | `POST /api/pipeline/voice/{videoId}?scene=` |
| `runImageForSegment(videoId, scene, index)` | `PipelineResponse` | `POST /api/pipeline/images/{videoId}?scene=&index=` |
| `runImageVariants(videoId, scene, index, count=3)` | `PipelineResponse` | `POST /api/pipeline/images/{videoId}?...&variants=` |
| **Scene Editing** | | |
| `updateSceneText(videoId, scene, text)` | `{status}` | `PATCH /api/videos/{id}/scenes/{scene}/text` |
| `updateSceneTone(videoId, scene, tone)` | `{status}` | `PATCH /api/videos/{id}/scenes/{scene}/tone` |
| `getSceneSegments(videoId, scene)` | `SegmentResponse` | `GET /api/videos/{id}/scenes/{scene}/segments` |
| `updateSceneSegments(videoId, scene, segments[])` | `{status}` | `PUT /api/videos/{id}/scenes/{scene}/segments` |
| `updateStoryboardMode(videoId, enabled)` | `{status}` | `PATCH /api/videos/{id}/storyboard-mode` |
| `clearSceneStoryboard(videoId, scene)` | `{status}` | `DELETE /api/videos/{id}/storyboards/{scene}` |
| `clearAllStoryboards(videoId)` | `{status}` | `DELETE /api/videos/{id}/storyboards` |
| **Suggestions** | | |
| `acceptSuggestion(videoId, fields[])` | `{status, accepted}` | `POST /api/videos/{id}/accept-suggestion` |
| `rejectSuggestion(videoId)` | `{status}` | `POST /api/videos/{id}/reject-suggestion` |
| **Autopilot** | | |
| `getAutopilotSummary()` | `AutopilotSummary` | `GET /api/autopilot/summary` |
| `getAutopilotCandidates(limit?, minVph?)` | `CompetitorCandidate[]` | `GET /api/autopilot/candidates?limit=&min_vph=` |
| `getAutopilotLearnings(category?, limit?)` | `Learning[]` | `GET /api/autopilot/learnings?limit=&category=` |
| `toggleAutopilot(enabled)` | `{status, enabled}` | `POST /api/autopilot/toggle` |
| `updateAutopilotConfig({videos_per_month?, videos_per_scrape?})` | `{status, config}` | `POST /api/autopilot/config` |
| `launchCandidate(candidateId)` | `{status, video_id, video_title}` | `POST /api/autopilot/launch/{id}` |
| **Agents** | | |
| `getAgentStats()` | `AgentStats` | `GET /api/agents/stats` |
| `getAgentVideos()` | `AgentVideoResult[]` | `GET /api/agents/videos` |
| `getAgentResults(videoId)` | `AgentVideoResult` | `GET /api/agents/videos/{id}` |
| `runAgentPipeline(videoId, tier?)` | `{status, message}` | `POST /api/agents/videos/{id}/run` |
| `getAgentTaskStatus(videoId)` | `{status, message}` | `GET /api/agents/videos/{id}/task` |
| **Discovery** | | |
| `getDiscoveryIdeas(status?, limit?)` | `DiscoveryIdea[]` | `GET /api/discovery/ideas?status=&limit=` |
| `getDiscoveryStatus()` | `DiscoveryStatus` | `GET /api/discovery/status` |
| `refreshDiscoveryIdeas()` | `{status, batch_id}` | `POST /api/discovery/refresh` |
| `launchIdea(ideaId, titleIndex, videoLengthMinutes?)` | `{status, video_id, video_title}` | `POST /api/discovery/ideas/{id}/launch` |
| `dismissIdea(ideaId)` | `{status}` | `POST /api/discovery/ideas/{id}/dismiss` |
| **Learnings** | | |
| `getLearnings(category?, activeOnly?)` | `LearningRecord[]` | `GET /api/learnings?active_only=&category=` |
| `extractLearnings()` | `ExtractionResult` | `POST /api/learnings/extract` |
| `extractLearningsForVideo(videoId)` | `ExtractionResult` | `POST /api/learnings/extract/{id}` |
| `analyzeCompetitorTitles()` | `{status, patterns_found}` | `POST /api/learnings/analyze-titles` |
| **Niche / Competitors** | | |
| `getNicheConfig()` | `NicheConfig` | `GET /api/niche/config` |
| `setupNiche(niche_category, sub_niche)` | `{status}` | `POST /api/niche/setup` |
| `getNicheChannels()` | `CompetitorChannel[]` | `GET /api/niche/channels` |
| `addNicheChannel(channel_name, channel_url)` | `{status}` | `POST /api/niche/channels` |
| `removeNicheChannel(channelId)` | `{status}` | `DELETE /api/niche/channels/{id}` |
| `scrapeCompetitorChannels()` | `{status, message}` | `POST /api/niche/scrape` |
| `getScrapeStatus()` | `ScrapeStatus` | `GET /api/niche/scrape/status` |
| **Settings / Keys** | | |
| `getApiKeys()` | `ApiKeyList` | `GET /api/settings/keys` |
| `getApiKeyStatus(name)` | `ApiKeyStatus` | `GET /api/settings/keys/{name}` |
| `setApiKey(name, value)` | `{status, message}` | `POST /api/settings/keys/{name}` |
| `deleteApiKey(name)` | `{status, message}` | `DELETE /api/settings/keys/{name}` |
| `testApiKey(name)` | `TestKeyResponse` | `POST /api/settings/keys/{name}/test` |
| `revealApiKey(name)` | `{value}` | `GET /api/settings/keys/{name}/reveal` |
| **Projects / Channel Profile** | | |
| `getCurrentProject()` | `Project` | `GET /api/projects/current` |
| `updateProject(data)` | `Project` | `PUT /api/projects/current` |
| `getChannelProfile()` | `ChannelProfile` | `GET /api/channel-profile` |
| `updateChannelProfile(data)` | `ChannelProfile` | `PUT /api/channel-profile` |
| `getIntegrationStatuses()` | `IntegrationStatusItem[]` | `GET /api/channel-profile/integrations` |
| **Visual Styles** | | |
| `getVisualStyles()` | `VisualStyle[]` | `GET /api/visual-styles` |
| `createVisualStyle({name, style_profile, reference_image_url?})` | `VisualStyle` | `POST /api/visual-styles` |
| `activateVisualStyle(styleId)` | `VisualStyle[]` | `PUT /api/visual-styles/{id}/activate` |
| `deleteVisualStyle(styleId)` | `{status}` | `DELETE /api/visual-styles/{id}` |
| `createStyleCharacter(styleId, {name, image_url})` | `StyleCharacter` | `POST /api/visual-styles/{id}/characters` |
| `deleteStyleCharacter(styleId, characterId)` | `{status}` | `DELETE /api/visual-styles/{id}/characters/{cId}` |
| `generateCharacterImage(prompt, styleId)` | `{status, image_url}` | `POST /api/visual-styles/characters/generate` |
| `analyzeStyleImage(imageData)` | `{status, profile}` | `POST /api/visual-styles/analyze-image` |
| **YouTube Sync** | | |
| `syncYouTubeMetrics()` | `{status, message}` | `POST /api/youtube/sync` |
| `getYouTubeSyncStatus()` | `YouTubeSyncStatus` | `GET /api/youtube/sync/status` |

---

## TypeScript Types (api.ts)

### Core Video Types
- `VideoSummary` { id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr, created_at, updated_at }
- `VideoDetail extends VideoSummary` { airtable_record_id, headline, source, framework_angle, thematic_framework, hook_script, past_context, present_parallel, future_prediction, writer_guidance, thesis, executive_hook, research_payload, original_dna, script, story_bible, thumbnail_prompt, thumbnail_style_override, visual_style, image_style_override, image_model_override, video_model, video_length_minutes, youtube_url, avg_retention, impressions, likes, comments, performance_verdict, avg_view_duration_seconds, views_24h/48h/7d/30d, ctr_12h/24h/48h, retention_48h, post_mortem_48h/7d, total_cost, agent_paper_trail/hook_score/body_score/tier/cost, suggested_script/title/thumbnail_prompt/thumbnail_urls, suggestion_source/scores/status }
- `Asset` { id, video_id, scene, image_index, image_url, image_prompt, status, shot_type, hero_shot, sentence_text, video_clip_url, sound_prompt, sound_effect_url, sound_volume, created_at }
- `ImageVariant` { id, video_id, scene, image_index, image_url, drive_image_url, image_prompt, status, shot_type, hero_shot, sentence_text, panel_position, generation_method, created_at }
- `ScriptScene` { id, video_id, scene, scene_text, voice_over_url, voice_status, script_status, sources, storyboard_on_off, storyboard_1_url..5_url, storyboard_prompts, storyboard_beat_count, storyboard_status, tone }

### Supporting Types
- `DashboardSummary` { active_bots, pending_review, pipeline_distribution: Record<string,number>, cost_today, cost_week[], errors, latest_video, total_videos }
- `ActivityEntry` { id, bot_name, video_id, video_title, status, message, cost, created_at }
- `ActivityStats` { bots_running, errors_today, cost_today }
- `PendingReview` { scripts, storyboards, thumbnails, images: ReviewItem[] }
- `ReviewItem` { asset_id?, script_id?, video_id, title, url?, storyboard_1/2/3_url?, word_count?, scene?, image_index?, prompt?, type }
- `PipelineResponse` { video_id, status, message, error? }
- `PipelineStatus` { video_id, current_status, next_action, airtable_synced }
- `TaskStatus` { status: "pending"|"running"|"completed"|"failed", message, error? }
- `StyleUpdateResponse` { status, video_id, updated_fields }
- `SplitResult` { status, video_id, total_segments, scenes[] }
- `Segment` { id, image_index, sentence_text, shot_type, status, word_count, duration_seconds, cumulative_start, image_prompt }
- `SegmentResponse` { scene, segments: Segment[] }
- `AutopilotSummary` { state: AutopilotState, config: AutopilotConfig, candidates[], learnings[] }
- `AutopilotState` { enabled, last_cycle, videos_produced, channel_avg_ctr, next_production_date, days_until_next }
- `AutopilotConfig` { videos_per_month, production_interval_days, videos_per_scrape, weights, thresholds }
- `CompetitorCandidate` { id, title, source, url, vph, hours_old, confidence, confidence_breakdown?, published_date, modeled }
- `Learning` { id, pattern, category, effect, confidence, sample_size, avg_ctr }
- `AgentStats` { total_scripts, avg_hook_score, avg_body_score, avg_cost, total_cost }
- `AgentVideoResult` { video_id, video_title, tier, hook_score, body_score, cost, paper_trail }
- `NicheConfig` { niche_category, sub_niche, has_channels }
- `CompetitorChannel` { id, channel_name, channel_url, category, active, last_scraped }
- `DiscoveryIdea` { id, source_type, competitor_title/channel/url/vph/thumbnail_url, our_angle, hook, framework, estimated_appeal, appeal_breakdown, title_options: TitleOption[], status, batch_date, created_at }
- `TitleOption` { title, formula_id, thumbnail_text, score }
- `DiscoveryStatus` { is_refreshing, last_batch_date, idea_count, fresh_count, learnings_applied }
- `ApiKeyStatus` { name, configured, source: "vault"|"env"|null, masked_value }
- `ApiKeyList` { keys: ApiKeyStatus[] }
- `TestKeyResponse` { success: boolean|null, message }
- `Project` { id, name, niche, target_audience, visual_style, visual_profile_json, accent_color, custom_accent_color, frameworks[], character_references[] }
- `ProjectUpdate` — partial of Project fields
- `CharacterReference` { name, description, image_url? }
- `ChannelProfile` { channel_name, niche, target_audience, frameworks[] }
- `VisualStyle` { id, name, style_profile: {mood?, lighting?, composition?, texture?, color_palette?, keywords?}, reference_image_url, is_active, is_default, characters[] }
- `StyleCharacter` { id, name, image_url, sort_order }
- `LearningRecord` { id, category, pattern, confidence, sample_size, avg_ctr, avg_retention, source_videos, active }
- `ExtractionResult` { videos_analyzed, patterns_extracted, patterns_new, patterns_updated }
- `ScrapeStatus` { is_running, videos_found, videos_saved, error, last_run }
- `YouTubeSyncStatus` { is_running, videos_synced, videos_total, error, last_run }

### Frontend-Only Types (types.ts)
- `Verdict` — `"hit" | "steady" | "underperformed"`
- `Video` { id, title, status, framework?, videoLengthMin?, wordCount?, sceneCount?, estimatedCost?, views?, ctr?, retention?, verdict?, thumbnailUrl?, progress?, updatedAt? }
- `SceneVisualGroup` { sceneNumber, actNumber, narrationText, visualStyle, composition, duration, segments: VisualSegment[], storyboardPanels? }
- `RenderState` { progress, resolution, fps, duration, musicTrack, exportFormat, ramUsage, cpuLoad, timeRemaining, scenes[] }
- `SettingsData` { channelName, niche, targetAudience, visualStyle, accentColor, frameworks[], integrations[] }

---

## Components

### ui/
| Component | Props | Description |
|-----------|-------|-------------|
| `GlassCard` | `children, className?, hover?, onClick?, style?` | Frosted glass container with top gradient line. `hover` enables scale-up on hover. |
| `StatCard` | `label, value, detail?, color, icon?, trend?, ringValue?` | Metric card with colored top accent. Optional trend arrow or SVG progress ring. |
| `StatusPill` | `label, color?, pulse?, size?` | Colored badge. Colors: turquoise/gold/orange/red/green/purple/yellow. Sizes: sm/md. |
| `ActionButton` | `children, variant?, onClick?, disabled?, icon?, className?` | Variants: filled (turquoise), outline (orange), warning (red). Accepts Lucide icon. |
| `Spinner` | `size?` | Lucide Loader2 with spin animation. Sizes: sm(14)/md(20)/lg(28). |
| `Modal` | `open, onClose, title?, children, size?` | AnimatePresence overlay + centered panel. Sizes: sm/md/lg. ESC to close. |
| `Tabs` | `tabs: {id,label}[], activeTab, onChange` | Horizontal tab bar with active highlight. |
| `TabPanel` | `children, active` | Conditional render wrapper for tab content. |
| `Accordion` | `title, children, defaultOpen?, className?` | Collapsible section with ChevronDown rotation. AnimatePresence height animation. |
| `Card` | `children, className?` | Simple bordered card (legacy). Sub-components: `CardHeader`, `CardBody`. |
| `ProgressStepper` | `steps, currentStep, completedSteps?, labels?` | Horizontal step circles with connector lines. Completed=turquoise, current=orange pulsing. |
| `ProgressRing` | `value, size?, color?, label?, strokeWidth?, children?` | SVG circular progress indicator with animated stroke. |
| `FilterSelect` | `options: {value,label}[], value, onChange, label?, disabled?` | Styled native `<select>` dropdown with turquoise focus ring. |
| `VerdictBadge` | `verdict: "hit"|"steady"|"underperformed"` | Performance verdict pill (green/yellow/red). |
| `SegmentBadge` | `label, color?, className?` | Monospace inline badge for scene/segment labels. |
| `MiniWaveform` | `color?, width?, height?, bars?` | Decorative SVG waveform for audio preview. |

### production/ (Video Detail Tabs — all take `video: any` or `video: VideoDetail`)
| Component | Description |
|-----------|-------------|
| `ResearchTab` | Research payload, thesis, hook. Run research / approve. Props: `video, onApproved?` |
| `ScriptVoiceTab` | Combined script + voice. Editable scenes, voice player, segments, split/merge. |
| `StoryboardVisualsTab` | Storyboard grids + images. Mode toggle, style selectors, prompt expander. Props: `video, onGoToScriptVoice?` |
| `VideoClipsTab` | Video clip gen status per asset. Progress ring, model selector, generate/regen. |
| `ThumbnailTab` | Thumbnail gen with accent color picker, style overrides, advance. |
| `RenderTab` | Asset counts (images/voice/clips/sound), duration, render trigger. |
| `UploadTab` | YouTube draft upload. Shows URL when uploaded. SEO metadata. |
| `PerformanceTab` | Post-publish stats — views, CTR, retention, verdict badge. |
| `ScriptTab` | Legacy script-only tab (superseded by ScriptVoiceTab). |
| `VoiceReviewTab` | Voice playback review per scene. |
| `SoundTab` | Sound prompts per scene, generation trigger, audio preview. |

### video-detail/
| Component | Props | Description |
|-----------|-------|-------------|
| `PromptExpander` | `prompt, onSave?, label?, previewLength?` | Collapsible prompt viewer with inline editing support. |
| `VoicePlayer` | `audioUrl, onRedo?, redoLoading?` | Audio player with play/pause, progress bar, redo button. |
| `StageAdvancer` | `videoId, stage, label, nextLabel?, disabled?, disabledReason?, cost?` | One-click pipeline stage trigger button with task polling. |
| `PipelineActionBar` | `videoId, status` | Maps current status to appropriate stage action button via `STAGE_ACTIONS` lookup. |
| `SceneEditor` | `scene: ScriptScene, sceneIndex, videoId, videoStatus, onRefresh` | Editable scene text + tone selector. Contains SegmentList. |
| `SegmentList` | `videoId, scene` | Expandable list of image segments for a scene with word counts and durations. |
| `ImageSegmentCard` | `asset: Asset, videoId, onRefresh` | Single image segment — shows image, prompt, regenerate/variants buttons. |
| `StoryboardViewer` | `scene: ScriptScene, ...` | Scene-level storyboard grid viewer with approve/reject/regenerate per grid. |
| `PanelMagnifier` | `gridUrl, panelIndex, size?, className?` | Crops and magnifies a single panel from a 3x3 storyboard grid using CSS background-position. |
| `VisualsTab` (video-detail) | `videoId, ...` | Legacy per-video visuals display (storyboard viewer + image segments). |

### storyboard/
| Component | Props | Description |
|-----------|-------|-------------|
| `SceneGrid` | `scene: SceneData, onPanelClick, onApprove, onRegenerate, isApproving?` | Displays a scene's storyboard panels with status badges and action buttons. |
| `PanelDetail` | `panels, initialIndex, sceneNumber, narration?, open, onClose, onRegenerate?, onUseThis?` | Full-screen panel viewer with swipe navigation (Framer Motion drag). |
| `StoryboardProgressBar` | `current, total, className?` | Animated progress bar showing review completion (X/Y scenes). |

Barrel export: `@/components/storyboard` re-exports `SceneGrid`, `PanelDetail`, `StoryboardProgressBar`, `SceneData`.

### autopilot/
| Component | Props | Description |
|-----------|-------|-------------|
| `NicheSetup` | (internal state) | Category/sub-niche picker + add competitor channel form. Uses `setupNiche`, `addNicheChannel`. |
| `PlayingCard` | `candidate: CompetitorCandidate, onModel` | Competitor video card with YouTube thumbnail, VPH badge, confidence score, "Model" button. |
| `CardExpanded` | `candidate, onClose, onProduce` | Expanded candidate view with ThumbnailWorkshop for iterating on thumbnail designs. |
| `ThumbnailWorkshop` | `initialPrompt, versions[], onGenerate, onLock, isGenerating?` | Thumbnail iteration UI — prompt editor, version carousel, lock button. |

### dashboard/
| Component | Props | Description |
|-----------|-------|-------------|
| `AutopilotCard` | (needs `AutopilotStatus` prop) | Dashboard widget showing autopilot state, next recommendation, days until next production. |
| `CTRAlerts` | `alerts: CTRAlert[], className?` | List of CTR alert cards with severity coloring (critical/warning/normal/strong). |

### nav/
| Component | Props | Description |
|-----------|-------|-------------|
| `Sidebar` | (none) | Desktop: fixed left sidebar (60px collapsed / 240px expanded). Mobile: hamburger overlay. Nav items: Dashboard, Videos, Autopilot, Competitors, Visual Profile, Analytics, Settings, API Keys. |
| `BottomTabs` | (none) | Mobile-only fixed bottom tab bar. 5 tabs: Home, Videos, Profile, Stats, Settings. |

### layout/
| Component | Props | Description |
|-----------|-------|-------------|
| `AmbientBackground` | (none) | Noise overlay + two gradient blobs for atmospheric background effect. |

### forms/
| Component | Props | Description |
|-----------|-------|-------------|
| `TextInput` | `label?, error?, helperText?, ...InputHTMLAttributes` | Styled text input with label and error display. |
| `PasswordInput` | `label?, error?, helperText?, ...InputHTMLAttributes` | Password input with show/hide toggle (Eye/EyeOff icons). |
| `Select` | `label?, options: {value,label}[], error?, ...SelectHTMLAttributes` | Styled native select with label. |
| `Toggle` | `label?, checked, onChange, disabled?, helperText?` | Boolean toggle switch. |
| `Textarea` | `label?, error?, helperText?, ...TextareaHTMLAttributes` | Styled textarea with label and error. |

### Root-level components
| Component | Props | Description |
|-----------|-------|-------------|
| `ActivityFeed` | `entries: ActivityEntry[]` | Scrollable activity list with bot-colored dots. |
| `VideoCard` | `video: VideoSummary` | Pipeline list card — title, status pill, progress dots. Links to `/pipeline/{id}`. |
| `ActionCard` | `title, message, href, status?` | Alert-style card linking to action (warning/error/info). |
| `DetailPanel` | `open, onClose, title?, children` | Slide-in right panel (AnimatePresence). |
| `ProgressDots` | `status, size?, showLabel?` | Compact pipeline progress dots using PIPELINE_STAGES. |

---

## Hooks

### useTaskPoller
```typescript
function useTaskPoller({
  videoId: string,
  enabled: boolean,
  interval?: number,       // default 3000ms
  onComplete?: (message?) => void,
  onFailed?: (error) => void,
}): {
  status: "idle" | "pending" | "running" | "completed" | "failed",
  message: string | null,
  error: string | null,
  reset: () => void,
  isPolling: boolean,
}
```
Polls `GET /api/pipeline/task/{videoId}` at interval. Stops on completed/failed. Swallows network errors to keep polling.

---

## Constants

### PIPELINE_STAGES (10 stages, dot 1-10)
`idea_logged` (Idea) > `ready_for_scripting` (Script) > `ready_for_voice` (Voice) > `ready_for_storyboards` (Storyboard) > `ready_for_images` (Images) > `ready_for_thumbnail` (Thumbnail) > `ready_to_render` (Render) > `rendered` (Rendered) > `uploaded_draft` (Draft) > `done` (Published)

### SUB_STAGE_MAP (maps to parent dot index)
`approved->1`, `ready_for_image_prompts->3`, `ready_for_storyboard_images->3`, `ready_for_storyboard_extraction->3`, `ready_for_sound_design->4`, `ready_for_sound_effects->4`, `ready_for_video_scripts->5`, `ready_for_video_generation->5`, `needs_script_review->1`, `uploaded->9`

### FILTER_OPTIONS
`all | in_production | ready_for_scripting | ready_for_voice | ready_for_storyboards | ready_for_images | ready_to_render | uploaded | done`

### COMPLETED_STATUSES — `Set(["uploaded_draft", "uploaded", "done", "rendered"])`

### Helper Functions (constants.ts)
`getStageIndex(status)` returns 0-9 | `getStageLabel(status)` returns display label | `getStageColor(status)` returns color

### Utility Functions (lib/utils.ts)
`cn(...inputs)` — twMerge(clsx) | `formatCost(n)` — `$X.XX` | `formatNumber(n)` — `1.2K`/`3.4M` | `timeAgo(dateStr)` — `5m ago`/`3h ago`

---

## Patterns

### React Query (providers.tsx)
`staleTime: 30_000`, `refetchInterval: 60_000`. Video detail polls every 5s while pipeline active.

### Data Fetching
```typescript
const { data, isLoading, error } = useQuery({ queryKey: ["videos"], queryFn: () => getVideos() });
```

### Mutations
```typescript
const mutation = useMutation({
  mutationFn: (id: string) => approveAsset(id),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pending-review"] }),
});
// mutation.mutate(id) to trigger, mutation.isPending for loading
```

### Task Polling
```typescript
const [taskRunning, setTaskRunning] = useState(false);
const { status, message } = useTaskPoller({ videoId, enabled: taskRunning,
  onComplete: () => { setTaskRunning(false); queryClient.invalidateQueries({ queryKey: ["video", videoId] }); },
  onFailed: (error) => { setTaskRunning(false); alert(error); },
});
// Start: await runPipelineStage(videoId, "script"); setTaskRunning(true);
// 409 retry: catch 409 -> clearStaleTask(videoId) -> retry
```

### Animation
```typescript
const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.08 } } };
const item = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0, transition: { duration: 0.5 } } };
// <motion.div variants={container} initial="hidden" animate="show"><motion.div variants={item}>
```

### fetchApi Wrapper
Token from `localStorage.getItem("token")` or `"dev-token"`. Throws on non-2xx. ENV: `NEXT_PUBLIC_API_URL` (default `http://localhost:8001`).

### Common Query Keys
`["videos"]` | `["video", videoId]` | `["video-script", videoId]` | `["video-assets", videoId]` | `["dashboard-summary"]` | `["pending-review"]` | `["activity"]` | `["autopilot-summary"]` | `["segments", videoId, scene]`

### Styling Conventions
- CSS variables via `style={{ color: "var(--turquoise)" }}` — NOT Tailwind color classes
- Glass backgrounds: `rgba(15,22,38,0.65)` or `rgba(255,255,255,0.02-0.05)` for nested surfaces
- All components are `"use client"` — no RSC
- Hover via `onMouseEnter/onMouseLeave` modifying `style` inline
- Font classes: `font-body` (Outfit), `font-display` (Playfair), `font-mono` (JetBrains)
- Text sizes: headings `text-4xl font-display`, labels `text-[11px] uppercase tracking-wider`, body `text-sm`, timestamps `text-[10px] font-mono`
