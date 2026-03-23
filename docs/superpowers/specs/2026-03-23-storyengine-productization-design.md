# StoryEngine Productization Design Spec

**Date:** 2026-03-23
**Status:** Draft - Awaiting Approval
**Author:** Claude + Ryan

---

## Executive Summary

StoryEngine is an automated YouTube video production pipeline being productized as a SaaS platform. Users sign up, bring their own API keys (BYOK model), and run multiple YouTube channels with an AI autopilot that recommends what to produce next.

**Core Value Proposition:**
- "We've built the orchestration logic. You bring your own AI keys."
- Transparent pricing — users see exactly what AI costs vs platform costs
- ~$25-30/mo base tier for system access
- Premium tier for autopilot, multi-channel, advanced features

---

## Table of Contents

1. [Target User](#1-target-user)
2. [Three-Layer Architecture](#2-three-layer-architecture)
3. [Page Structure](#3-page-structure)
4. [Key Features](#4-key-features)
5. [Mobile-First Design Principles](#5-mobile-first-design-principles)
6. [Visual System Management](#6-visual-system-management)
7. [Storyboard Review Flow](#7-storyboard-review-flow)
8. [Implementation Priority](#8-implementation-priority)

---

## 1. Target User

**Primary:** Solo YouTubers looking to automate their video production pipeline.

**Characteristics:**
- Wants to produce more content without more effort
- Comfortable with SaaS tools (not necessarily technical)
- Willing to pay $25-50/mo for automation
- May not know what an API key is (needs guided setup)

**Future Expansion:**
- Content agencies (multi-tenant)
- Other platforms: TikTok, Instagram Reels, podcasts
- YouTube is the flagship module built first

---

## 2. Three-Layer Architecture

The UI surfaces three distinct system layers:

```
┌─────────────────────────────────────────────────────────────┐
│  INTELLIGENCE (Autopilot Brain)                             │
│  • Recommends next video (with confidence + reasoning)      │
│  • Monitors CTR at 6h/24h/48h                               │
│  • Learns from performance → updates memory                 │
│  • Tells you what to do next                                │
└─────────────────────────────────────────────────────────────┘
                              ↓ orchestrates
┌─────────────────────────────────────────────────────────────┐
│  PRODUCTION (18-Stage Pipeline)                             │
│  Idea → Script → Voice → Prompts → Storyboards → Images →   │
│  Sound → Video Gen → Thumbnail → Render → Upload Draft      │
└─────────────────────────────────────────────────────────────┘
                              ↓ feeds back
┌─────────────────────────────────────────────────────────────┐
│  PERFORMANCE (YouTube + Analytics)                          │
│  • Views, CTR, Retention per video                          │
│  • Competitor VPH comparison                                │
│  • Pattern learnings (what works/doesn't)                   │
└─────────────────────────────────────────────────────────────┘
```

**Dashboard shows all three at once:**
- Autopilot card with next recommendation
- Production queue with progress
- CTR alerts for recent videos

---

## 3. Page Structure

### Navigation

**Mobile (Bottom Tabs):**
- Home, Pipeline, Review, Analytics, More
- "More" drawer contains: Autopilot, Styles, Learnings, Settings, Activity

**Desktop (Sidebar):**
- All pages visible in sidebar at 768px+
- Channel switcher at top of sidebar

### Pages

| Page | Route | Status | Description |
|------|-------|--------|-------------|
| **Dashboard** | `/` | Enhanced | Command center: autopilot + queue + alerts |
| **Pipeline** | `/pipeline` | Exists | Video list, filters, detail panel |
| **Review** | `/review` | Exists | Script approval queue |
| **Analytics** | `/analytics` | New | YouTube metrics, CTR trends, per-video |
| **Activity** | `/activity` | Exists | Bot activity log |
| **Autopilot** | `/autopilot` | New | ON/OFF, candidates, weights, reasoning |
| **Learnings** | `/learnings` | New | Patterns, anti-patterns, experiments |
| **Styles** | `/styles` | New | Visual system library, clone tool |
| **Settings** | `/settings` | Enhanced | API keys (guided), channel config |

---

## 4. Key Features

### 4.1 Channel Switcher
- Located in sidebar header (desktop) or page header (mobile)
- Dropdown to switch between channels
- Premium tier unlocks multiple channels
- Each channel has independent:
  - Visual system default
  - Autopilot settings
  - Production queue

### 4.2 Autopilot Integration
- **Dashboard banner** when autopilot is active:
  - Green pulsing dot
  - Next recommended video title
  - Confidence score bar
  - "Launch Now" / "See Why" buttons
- **Autopilot page** for configuration:
  - ON/OFF toggle
  - Cadence settings (videos per month)
  - Candidate queue with scores
  - Weight sliders (VPH, freshness, topic fit, etc.)

### 4.3 CTR Monitoring
- **Performance alerts** on dashboard:
  - Color-coded by status (success=green, warning=amber)
  - Shows video title, time since publish, CTR value
- **Deep dive** in Analytics page:
  - CTR trend chart (7d/30d/90d)
  - Per-video breakdown table
  - Compare to competitor VPH

### 4.4 BYOK (Bring Your Own Keys)
- **Guided setup** in Settings:
  - Step-by-step with screenshots for each service
  - Detect missing keys, prompt to configure
  - Test button to verify key works
- **Supported services:**
  - Anthropic (Claude)
  - ElevenLabs (Voice)
  - Kie.ai (Images/Video)
  - OpenAI (Whisper)
  - Google (Drive/Docs)

---

## 5. Mobile-First Design Principles

### Touch Targets
- All tappable areas minimum 44px
- Primary actions at thumb-reach (bottom of screen)
- "Run Next Step" is the hero button in video detail

### Information Hierarchy
- Autopilot recommendation = top of dashboard
- Production status = always visible
- CTR alerts = prominent, color-coded
- Detail sheets slide up (not new pages)

### Navigation
- Bottom tabs on mobile (5 max)
- "More" opens drawer for additional pages
- Channel switcher in header (always accessible)
- Desktop sidebar appears at 768px+

### Gestures
- Swipe down to refresh
- Swipe left/right on Review for approve/reject
- Tap cell in storyboard to enlarge
- Swipe between storyboard panels

---

## 6. Visual System Management

### Location
- `/styles` page in "More" drawer (mobile) or sidebar (desktop)
- Quick access via "Change" link on channel card

### Features

**Preset Library:**
- Cinematic Illustration (default)
- Holographic HUD
- Cinematic Dossier
- Clay Mannequin

**Clone from Screenshot:**
- Upload image of any video's visual style
- AI extracts: colors, composition, lighting, text treatment
- Creates new custom style profile
- Can be applied to channel or individual videos

**Character References:**
- Upload character reference images
- Maintains visual consistency across storyboards
- Story Bible integration

**Per-Channel Defaults:**
- Each channel has a default visual system
- Individual videos can override

---

## 7. Storyboard Review Flow

### Comic Book View (`/pipeline/{videoId}/storyboards`)

**Layout:**
- Vertical scroll through all storyboards
- Each scene is a card containing:
  - Header: Scene number + title + status badge
  - 3x3 grid of panels (9 per scene)
  - Narration text below grid
  - Approve/Regenerate buttons

**Status Badges:**
- Approved (green)
- Pending Review (accent)
- Generating... (dimmed)

**Progress:**
- Bar at top showing scenes reviewed / total
- Can review while generation continues

### Panel Detail View

**Trigger:** Tap any cell in the 3x3 grid

**Features:**
- Full panel view
- Swipe left/right between 9 panels
- Associated narration text
- X/Y extraction preview overlay
- Regenerate individual panel button

### Extraction

**Batch:** "Extract All" FAB extracts all approved scenes
**Manual:** Tap panel → select region → "Use This"

### Post-Extraction View

- Shows final images in sequence
- Shot type + estimated duration per image
- "Continue to Scene N" button

---

## 8. Implementation Priority

### Phase 1: Foundation (Current Sprint)
Already done:
- [x] Backend pipeline executor with all 15 stages
- [x] API key vault integration
- [x] Basic Pipeline page with detail panel

To do:
- [ ] Channel switcher (UI only, single-channel backend)
- [ ] Enhanced Dashboard with autopilot banner (static mock)
- [ ] CTR alerts section on Dashboard

### Phase 2: Storyboard Review
- [ ] Storyboard list view (comic book scroll)
- [ ] Panel detail slide-up sheet
- [ ] Approve/Regenerate per scene
- [ ] Extract All action

### Phase 3: Analytics & Intelligence
- [ ] Analytics page with CTR chart
- [ ] Per-video performance table
- [ ] Autopilot page with controls
- [ ] Learnings page (read from memory files)

### Phase 4: Visual Systems
- [ ] Styles page with preset library
- [ ] Clone from screenshot feature
- [ ] Character reference upload
- [ ] Per-channel defaults

### Phase 5: Multi-Channel & Premium
- [ ] Multi-channel support in backend
- [ ] Subscription tier logic
- [ ] Usage tracking
- [ ] Billing integration

---

## Appendix: Mockups

Visual mockups created during design session are available at:
`/Users/ryanayler/economy-fastforward/.superpowers/brainstorm/91813-1774308105/screen.html`

Open in browser to view:
- Mobile-first Dashboard
- Pipeline list view
- Video detail sheet
- Storyboard comic book review
- Panel detail view
- Extracted images view

---

## Approval

Please review this spec and confirm:
1. Does the three-layer architecture match your vision?
2. Is the page structure and navigation correct?
3. Is the storyboard review flow complete?
4. Is the implementation priority order acceptable?

Once approved, we'll create the implementation plan.
