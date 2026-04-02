# StoryEngine Product Vision

> This is the North Star. Every task, every line of code must push toward this vision.

## What We're Building

**StoryEngine** is a SaaS platform for automated YouTube video production. Users sign up, bring their own API keys (BYOK), and get an AI-powered pipeline that takes a video idea and produces a complete video — research, script, voice, images, storyboards, thumbnails, rendering, and upload.

**The upsell:** Smart analytics and an Autopilot brain that learns what works, recommends what to make next, and compounds performance over time.

## Target User

Solo YouTubers who want to produce more content without more effort. Not necessarily technical. Willing to pay $25-50/mo. May not know what an API key is (needs guided setup).

## Three Layers

```
INTELLIGENCE (Autopilot) — Recommends what to make, monitors CTR, learns from results
     ↓
PRODUCTION (Pipeline)    — 18 stages: Idea → Script → Voice → Images → Thumbnail → Render → Upload
     ↓
PERFORMANCE (Analytics)  — CTR, retention, views, competitor comparison, pattern learnings
```

## Pricing Tiers

| Tier | Price | Features |
|------|-------|---------|
| **Starter** | ~$25/mo | Pipeline access, 1 channel, manual mode |
| **Pro** | ~$40/mo | Autopilot, analytics, competitor scraping, learnings |
| **Agency** | ~$75/mo | Multi-channel, team management, priority rendering |

Users bring their own API keys (Anthropic, ElevenLabs, Kie.ai, Google). Platform cost is separate from AI cost — transparent pricing.

## Complete Feature Map

### Core (must work end-to-end)
- [ ] **Channel Onboarding** — Sign up → YouTube URL → guided API key setup → baseline import
- [ ] **Create Video** — "What's Your Story?" form: title, angle, thesis, tone, length, visual style
- [ ] **Pipeline Execution** — One-click "Run Next Step" OR full auto-run from idea to upload
- [ ] **Review Queue** — Approve/reject scripts, storyboards, thumbnails, images inline
- [ ] **Video Detail** — Tabbed view: Research, Script, Voice, Storyboard, Visuals, Thumbnail, Render, Upload, Performance
- [ ] **Settings** — API keys (guided setup with test buttons), channel config, pipeline preferences

### Intelligence (the upsell)
- [ ] **Autopilot** — ON/OFF toggle, candidate scoring, one-tap "Launch Now", cadence settings
- [ ] **Discovery Ideas** — AI-generated video ideas from competitor analysis, 3 title options each
- [ ] **Learnings Dashboard** — Pattern library: what titles/hooks/frameworks produce best CTR
- [ ] **Competitor Analysis** — Scrape channels, VPH scoring, transcript preview, confidence breakdown
- [ ] **CTR Monitoring** — 6h/24h/48h alerts, early warning system, post-mortem analysis

### Analytics
- [ ] **Performance Dashboard** — CTR timeline, framework effectiveness, revenue estimates
- [ ] **Per-Video Metrics** — Views, CTR, retention, impressions snapshots (24h/48h/7d/30d)
- [ ] **Post-Mortems** — 48h and 7d automated analysis with actionable recommendations
- [ ] **Agent Quality Scores** — Hook score, body score, tier rating per video

### Visual System
- [ ] **Style Library** — Presets (Cinematic Illustration, Holographic HUD, Dossier, Clay Mannequin)
- [ ] **Clone from Screenshot** — Upload image → AI extracts style → create custom profile
- [ ] **Character References** — Upload reference images for visual consistency
- [ ] **Per-Channel Defaults** — Each channel has its own visual identity

### Auth & Billing (CRITICAL — blocks paying customers)
- [ ] **Google OAuth Sign-In** — Sign up / log in with Google. No email+password. Google is the auth provider.
- [ ] **User Profiles** — Each user has their own account, channels, API keys, production queue
- [ ] **Multi-Channel** — Channel switcher in sidebar, independent settings per channel
- [ ] **Stripe Billing** — Subscription management, plan selection, usage tracking, payment processing
- [ ] **Plan Gating** — Free users see limited features, Pro unlocks autopilot/analytics, Agency unlocks multi-channel
- [ ] **Tenant Isolation** — Each user's data is completely separate (already have tenant_id in schema, needs enforcement)

### Platform
- [ ] **Mobile UX** — Bottom tabs, swipe gestures, thumb-reach actions, responsive everything
- [ ] **Calendar View** — Weekly/monthly production calendar showing video pipeline status

## User Flows (the experience)

### Flow 1: New User Setup
```
"Sign in with Google" button → Google OAuth → Create account → Enter YouTube channel URL → Guided API key setup (one at a time, with screenshots and test buttons) → Select pricing plan (Starter/Pro/Agency) → Import existing videos as baseline → Dashboard shows "Ready to create your first video"
```

### Flow 2: Create & Produce a Video
```
Tap "New Video" → Fill in: title, angle, thesis, target length → Pipeline auto-runs: Research → Script → Voice → Images → Storyboard → Thumbnail → Render → Upload as draft → Notification: "Your video is ready for review"
```

### Flow 3: Review & Approve
```
Dashboard shows "2 videos pending review" → Tap → Jump to video detail → Review script (inline edit) → Review storyboards (swipe through panels) → Approve thumbnail → Hit "Upload" → Video goes to YouTube as unlisted draft
```

### Flow 4: Autopilot Mode
```
Toggle Autopilot ON → Autopilot scrapes competitors → Scores candidates → Recommends top 3 ideas with confidence scores → You tap "Launch Now" → Full pipeline runs automatically → After publish: CTR monitored at 6h/24h/48h → Learnings extracted → Next recommendation is smarter
```

### Flow 5: Analyze & Learn
```
Check Analytics → See CTR trend across all videos → Drill into per-video performance → Read post-mortem ("thumbnail outperformed but hook was weak") → Check Learnings page ("Question format titles: avg 5.2% CTR") → System applies these learnings to next video automatically
```

## Design Language

- Dark editorial production cockpit
- Charcoal base (#0A0A0B), amber actions (#D4A844), teal indicators (#1A8A7A)
- Mobile-first: 44px touch targets, thumb-reach primary actions
- Glass-morphism cards, Framer Motion stagger animations
- Fonts: Playfair Display (display), Outfit (body), JetBrains Mono (data)

## What "Done" Looks Like

StoryEngine is DONE when a user can:
1. Sign up and set up their channel in under 5 minutes
2. Create a video idea and have it fully produced (script → render) without touching anything
3. Review and approve each stage with inline editing
4. See their YouTube performance data with actionable insights
5. Turn on Autopilot and have the system recommend + produce videos automatically
6. See the system get SMARTER over time (learnings compound, recommendations improve)

If a user has to ask "how do I..." for any core flow, we're not done.
