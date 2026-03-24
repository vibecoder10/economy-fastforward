# Module 5: Niche Selection + Topic Discovery — Design Spec

**Date:** 2026-03-24
**Status:** Draft
**Author:** Ryan + Claude

---

## Summary

Transform the existing Autopilot page into a full **Niche Intelligence + Topic Discovery** system. Users set up their niche (YouTube category + sub-niche), add competitor channels, and see ranked "playing card" style competitor video cards. Each card can be flipped to reveal a side-by-side comparison (theirs vs yours) with an inline thumbnail workshop featuring a prompt iteration carousel.

**Key principle:** The agent sits BEFORE research. It recommends WHAT to produce based on competitor data and proven patterns, not just HOW to produce it.

---

## 1. Niche Setup Flow (One-Time Onboarding)

When a tenant has no competitor channels configured, the autopilot page shows a setup wizard:

### Step 1: Pick YouTube Category
Dropdown of YouTube's top-level categories:
- Education, News & Politics, Science & Technology, Entertainment, People & Blogs, Film & Animation, Gaming, Music, Sports, How-to & Style, Comedy, Autos & Vehicles

Stored in: `tenants` table or `autopilot_config` → new `niche_category` field.

### Step 2: Define Sub-Niche
Freeform text input: "What's your specific focus within this category?"
Examples: "Geopolitics", "Personal Finance for Millennials", "AI Explained", "True Crime Cold Cases"

Stored in: `autopilot_config` → new `sub_niche` field.

### Step 3: Add Competitor Channels
Paste 3-5 YouTube channel URLs. System validates they exist and scrapes initial data.

```
┌────────────────────────────────────┐
│  Add Competitor Channels           │
│                                    │
│  Paste YouTube channel URLs:       │
│  ┌──────────────────────────────┐  │
│  │ https://youtube.com/@CaspianR│  │
│  │ https://youtube.com/@AiTelly │  │
│  │ https://youtube.com/@TLDR    │  │
│  │ + Add another                │  │
│  └──────────────────────────────┘  │
│                                    │
│  [Start Scanning →]                │
└────────────────────────────────────┘
```

After setup, the system scrapes competitor channels and populates the competitor_videos table.

---

## 2. Playing Card UI (Ranked Topic Cards)

The existing autopilot candidates section is replaced with playing cards. Each card represents a competitor video worth modeling.

### Card Front (Default)

```
┌─────────────────────────┐
│  [competitor thumbnail]  │
│  ████████████████████████ │
│  ████████████████████████ │
│                          │
│  "How an F-35 Got Hit    │
│   by Iranian Missile"    │
│                          │
│  ┌──────┐ ┌──────┐      │
│  │46,326│ │ 14h  │      │
│  │ VPH  │ │fresh │      │
│  └──────┘ └──────┘      │
│                          │
│  AiTelly  ●━━━━━━━ 95.8 │
│           confidence     │
│                          │
│  [Model This →]          │
└─────────────────────────┘
```

**Data displayed:**
- Competitor thumbnail image (fetched from YouTube)
- Video title
- VPH (views per hour) — the key performance signal
- Freshness (hours old)
- Channel name
- Confidence score (0-100) with progress bar
- "Model This" action button

**Card styling:**
- Dark card bg (`--bg-card`), subtle border
- Thumbnail fills top 40% of card
- VPH and freshness as stat badges
- Confidence bar uses amber fill
- Framer Motion hover: subtle scale(1.02) + shadow lift

### Card Back (Expanded — After "Model This")

Clicking "Model This" expands the card into a side-by-side comparison + thumbnail workshop:

```
┌──────────────┬──────────────┐
│  THEIRS      │  YOURS       │
│              │              │
│  [their      │  [generated  │
│   thumbnail] │   OR empty]  │
│              │              │
│  "How an     │  "The $2K    │
│   F-35 Got   │   Drone That │
│   Hit..."    │   Changed    │
│              │   Naval..."  │
│              │              │
│  VPH: 46,326│  Structure:  │
│  Channel:    │  time_bomb   │
│  AiTelly     │  (5.2% CTR) │
│              │              │
│              │  Pattern:    │
│              │  "Asymmetric │
│              │   cost hook" │
│──────────────┴──────────────│
│                              │
│  THUMBNAIL WORKSHOP          │
│                              │
│  ◀  [generated thumb v2]  ▶  │
│                              │
│     Version 2 of 3           │
│     ● ○ ○                    │
│                              │
│  ┌────────────────────────┐  │
│  │ "Bold red editorial,   │  │
│  │  stern leader portrait, │  │
│  │  '$2K CHECKMATE'..."    │  │
│  │                 [Edit]  │  │
│  └────────────────────────┘  │
│                              │
│  [Generate New $0.075]       │
│                              │
│  [Cancel]  [Lock & Produce →]│
└─────────────────────────────┘
```

### Thumbnail Workshop — Prompt Iteration Carousel

The thumbnail workshop allows iterative prompt refinement:

1. **Initial state:** Auto-generated thumbnail prompt based on competitor analysis + proven patterns. No image yet.
2. **User clicks "Generate":** Calls Nano Banana Pro ($0.075), image appears in carousel as Version 1.
3. **User edits prompt:** Modifies the text, clicks "Generate New" again → Version 2 added to carousel.
4. **Arrow navigation:** Left/right arrows cycle through all versions. Each version shows its paired prompt + image.
5. **Dot indicators:** Show which version is active and how many exist.
6. **"Lock & Produce":** Selects the current version and sends everything into the pipeline.

**Carousel data model:**
```typescript
interface ThumbnailVersion {
  prompt: string;
  image_url: string | null;  // null = not yet generated
  created_at: string;
}

// Stored in suggested_thumbnail_urls as JSONB array
// [{url, prompt, approach}]
```

**Cost display:** Each "Generate" button shows the cost ($0.075). Running total visible: "3 versions · $0.225 spent"

---

## 3. "Yours" Side — Agent Suggestions

When the card expands, the right side ("YOURS") shows what the agent would produce:

- **Suggested title:** Generated by curiosity gap engine, using the competitor's topic but our proven structures
- **Structure:** Which curiosity structure fits (hidden_flaw, time_bomb, etc.) with historical CTR for that structure
- **Pattern:** Which learned pattern is being applied (from learnings table)
- **Thumbnail prompt:** Auto-generated based on competitor thumbnail analysis + our proven visual patterns

These come from existing systems:
- Title: `curiosity_gap/gap_title_engine.py` structures + `title_selector.py` scoring
- Thumbnail: `autopilot/analysis/thumbnail_analyzer.py` + `thumbnail_adapter.py`
- Pattern data: `learnings` table in Supabase

---

## 4. "Lock & Produce" Action

When user clicks "Lock & Produce":

1. Create a new `videos` record in Supabase with:
   - `video_title` = suggested title (or user-edited)
   - `suggested_thumbnail_prompt` = locked prompt from carousel
   - `suggested_thumbnail_urls` = all generated versions
   - `suggestion_source` = competitor video ID + structure used
   - `status` = "idea_logged"
2. Mark competitor video as `modeled = true`, `modeled_at = NOW()`
3. Navigate to the new video's detail page (`/pipeline/{videoId}`)
4. The pipeline picks it up from here (research → script → etc.)

---

## 5. Niche Settings (Persistent Config)

Below the playing cards, a collapsible "Niche Settings" section shows:

```
┌──────────────────────────────┐
│  Niche Settings              │
│                              │
│  Category: Education         │
│  Sub-niche: Geopolitics      │
│  [Edit]                      │
│                              │
│  Competitor Channels (5)     │
│  ● CaspianReport  [Remove]  │
│  ● AiTelly         [Remove]  │
│  ● TLDR News       [Remove]  │
│  [+ Add Channel]             │
│                              │
│  Last scraped: 2h ago        │
│  [Scrape Now]                │
└──────────────────────────────┘
```

---

## 6. Database Changes

### New columns on `autopilot_config`:
```sql
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS niche_category TEXT;
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS sub_niche TEXT;
```

### Existing tables used:
- `competitor_channels` — already has channel_name, channel_url, category, active
- `competitor_videos` — already has all needed fields (title, vph, hours_old, thumbnail data)
- `videos` — suggestion columns from migration 005 used for the "produce" action

### No new tables needed.

---

## 7. API Endpoints

### New:
- `POST /api/niche/setup` — Save category + sub_niche to autopilot_config
- `POST /api/niche/channels` — Add competitor channel (validates YouTube URL)
- `DELETE /api/niche/channels/{id}` — Remove competitor channel
- `POST /api/niche/scrape` — Trigger manual competitor scrape

### Existing (already work):
- `GET /api/autopilot/candidates` — Returns ranked competitor videos
- `POST /api/autopilot/launch/{id}` — Mark as modeled + create idea
- `GET /api/autopilot/learnings` — Pattern data for "YOURS" side

### Thumbnail generation:
- Uses existing Kie.ai image generation endpoint (Nano Banana Pro)
- New: `POST /api/thumbnails/generate` — Generate thumbnail from prompt, return URL

---

## 8. Mobile Experience

**Phone layout:** Cards stack vertically, one per row. Card back expands inline (pushes content down, doesn't overlay). Thumbnail workshop is full-width. Arrow navigation becomes swipe gestures.

**Desktop:** Cards in 2-3 column grid. Card back expands as a modal overlay with the side-by-side comparison.

---

## 9. What's NOT in V1

- Auto-discover competitors (user adds manually)
- Batch topic selection / "Queue All"
- Calendar production view
- Channel onboarding / baseline learning import
- Topic cluster auto-classification
- VPH trend charts over time

These are deferred to future modules.
