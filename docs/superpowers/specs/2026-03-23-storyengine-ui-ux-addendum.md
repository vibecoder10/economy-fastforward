# StoryEngine v4 — UI/UX Addendum
## Screen-by-Screen Interface Specification
**Version:** 1.0 | **Date:** March 23, 2026
**Design philosophy:** Mobile-first production cockpit. Every screen must be fully usable on phone with thumb-reach interactions. Laptop expands the experience with side-by-side panels but never adds features phone can't access.

**Design language:** Dark editorial — deep charcoal (#0A0A0B) base, amber/gold (#D4A844) primary actions, teal (#1a8a7a) secondary indicators, red (#C44545) for destructive/alert. Generous spacing. Cards with subtle borders, not heavy shadows. Typography: distinctive display font for headers, clean sans-serif for body. No generic SaaS aesthetic.

---

## Global Navigation

### Mobile (Primary)
```
+----------------------------------+
| M  StoryEngine    B  P           |
+----------------------------------+
|                                  |
|         [Current Screen]         |
|                                  |
+----------------------------------+
| H  Pi  Sc  Bo  St  Se           |
| Home Pipe Script Board Stats Set |
+----------------------------------+
```
- Bottom tab bar: 6 tabs, always visible
- Current tab highlighted with amber accent
- Notification bell shows pending approvals count

### Desktop (Expanded)
```
+---------+--------------------------------------------+
|         |                                            |
|  Logo   |           [Current Screen]                 |
|         |                                            |
| H Home  |                                            |
| Pi Pipe |                                            |
| Sc Scrpt|                                            |
| Bo Board|                                            |
| St Stats|                                            |
| Au Auto |                                            |
| Se Sett |                                            |
|         |                                            |
|         |                                            |
| Sign Out|                                            |
+---------+--------------------------------------------+
```
- Left sidebar, collapsible to icons only
- Desktop adds Autopilot tab (hidden on mobile behind menu)

---

## Screen 1: Home Dashboard

**Purpose:** At-a-glance status of everything. "What needs my attention right now?"

### Mobile Layout
```
+----------------------------------+
|  Good morning, Ryan              |
|  2 videos need approval          |
|                                  |
| +------------------------------+ |
| | Y Hormuz $2K Drone            | |
| | Storyboard ready for review  | |
| | [Review ->]                  | |
| +------------------------------+ |
| +------------------------------+ |
| | Y Taiwan Chip Shortage       | |
| | Script ready for approval    | |
| | [Review ->]                  | |
| +------------------------------+ |
|                                  |
| -- Recent Activity --            |
| G Iran Trap rendered (2h ago)   |
| G FDR 1933 uploaded (5h ago)   |
| R AI Purge thumbnail failed    |
|                                  |
| -- Quick Stats --                |
| This week: 3 videos published   |
| Avg CTR: 3.2%  |  Avg Ret: 42% |
| Pipeline: 5 in progress         |
| Spend: $47.20 this month        |
+----------------------------------+
```

### Desktop Layout
Same content but in a 3-column grid:
- Left: Action items (approvals needed)
- Center: Recent activity feed
- Right: Quick stats cards

### Interactions
- Tap any action item -> jumps directly to that video's approval screen
- Tap any activity item -> opens that video's detail view
- Pull-to-refresh on mobile

---

## Screen 2: Pipeline View

**Purpose:** See every video and where it sits in the production process. This is the control room.

### Mobile Layout -- List View with Progress Dots
```
+----------------------------------+
|  Pipeline            [+ New] Q   |
|  Filter: [All v] [Status v]     |
|                                  |
| +------------------------------+ |
| | Hormuz $2K Drone             | |
| | * * * * o o o o o o          | |
| | Y Ready For Storyboards      | |
| | Created 2d ago  |  $4.20     | |
| +------------------------------+ |
| +------------------------------+ |
| | Taiwan Chip Shortage         | |
| | * * * o o o o o o o          | |
| | Y Ready For Voice            | |
| | Created 3d ago  |  $1.80     | |
| +------------------------------+ |
| +------------------------------+ |
| | Iran Fell For The Trap       | |
| | * * * * * * * * * *          | |
| | G Done                       | |
| | Published 1d ago | 2.4K views| |
| +------------------------------+ |
|                                  |
|       [Load More]                |
+----------------------------------+
```

**Progress dots:** 10 dots = 10 major stages. Each dot:
- Filled (green) = complete
- Filled (amber) = current / needs attention
- Empty = pending
- Filled (red) = failed

**Filters:**
- Status: All, In Progress, Needs Approval, Done, Failed
- Sort: Newest, Oldest, Most Views, Highest CTR

### Desktop Layout
Same list but wider cards showing more info per row:
```
| Title              | Status          | Progress    | CTR  | Views | Cost  |
| Hormuz $2K Drone   | Y Storyboards   | ****oooooo  | --   | --    | $4.20 |
```

### Interactions
- Tap video card -> opens Video Detail View (Screen 3)
- [+ New] -> opens Idea Input form
- Long-press (mobile) or right-click (desktop) -> quick actions: Delete, Force Advance, Reset Stage
- Search bar: type to filter by title

---

## Screen 3: Video Detail View

**Purpose:** Everything about one video. The master view. This is where all review and approval happens.

### Mobile Layout -- Tabbed Sections
```
+----------------------------------+
| <- Back                          |
|                                  |
|  Hormuz $2K Drone                |
|  Y Ready For Storyboards        |
|  * * * * o o o o o o            |
|                                  |
| +----+----+----+----+----+----+  |
| |Info|Scrp|Viz |Stry|Thum|Perf|  |
| +----+----+----+----+----+----+  |
|                                  |
|   [Tab content below]            |
|                                  |
+----------------------------------+
```

**6 tabs, swipeable on mobile:**

#### Tab: Info
```
Title: Hormuz $2K Drone
Status: Ready For Storyboards
Framework: Sun Tzu (Asymmetric Warfare)
Tone: Analytical with moments of urgency

-- Story DNA --
Angle: A $2,000 drone can disable a $2B destroyer
Thesis: Asymmetric warfare has inverted naval power
Past Context: Historical naval chokepoints...
Future Prediction: Drone swarms will...
Opening Hook: "The most expensive warship..."

-- Story Bible --  [Edit]
Characters:
  * The Family (Civilian archetype) -- Scene 1
  * The Captain (Operative archetype) -- Scene 2
  * The Admiral (Authority archetype) -- Scene 4

Locations:
  * Gas station, suburban America
  * USS destroyer bridge, Strait of Hormuz
  * Pentagon war room

Visual Arc:
  Act 1: Warm domestic -> cold military transition
  Act 2: Clinical naval blue
  ...

-- Research --  [Expand]
[Collapsed by default -- tap to see full research payload]

-- Actions --
[Approve & Advance ->]     [Reject & Regenerate]
[Force to Stage: v]        [Delete Video]
```

**Story Bible section is KEY.** This is the first time the user sees the characters, locations, and visual arc that will drive all downstream generation. It must be editable:
- Tap any character -> edit name, archetype, description
- [+ Add Character] button
- Tap any location -> edit description, lighting notes
- Visual Arc is auto-generated from script but editable

**Character reference images** show inline when they exist:
```
Characters:
+------+
| img  | The Captain (Operative)
|      | "Navy dress blues, weathered face,
+------+  salt-and-pepper hair, commanding stance"
         [Change Reference] [Remove]

+------+
| img  | The Family (Civilian)
|      | "Suburban parents, casual clothes,
+------+  two kids in back seat"
         [Generate Reference] [Upload]
```

#### Tab: Script
```
+----------------------------------+
| Script  | 2,505 words | ~16.7 min|
|                                  |
| Scene 1 of 20  [INTRO]  143w    |
| +------------------------------+ |
| | March 2023. A fire breaks    | |
| | out at a Taiwan Semi...      | |
| |                              | |
| | [full narration text,        | |
| |  editable on tap]            | |
| +------------------------------+ |
| [Regenerate] [Tone: v] [Edit]   |
|                                  |
| -- Visual Direction --           |
| "Split screen: AI advancement    |
|  headlines contrasted with       |
|  images of Taiwan's vulner..."   |
| [Edit Visual Direction]          |
|                                  |
| < Prev  |  Scene 1/20  | Next > |
|                                  |
| [Approve Script -> Generate Voice]|
+----------------------------------+
```

**Mobile: one scene at a time** with prev/next swipe navigation.
**Desktop: scrollable list** of all scenes visible simultaneously.

**Per-scene controls:**
- Tap text to edit inline (auto-save on blur)
- Regenerate: re-calls Claude for this scene only
- Tone dropdown: serious / conversational / urgent / concise / detailed -> regenerates with modifier
- Visual direction editable separately (feeds into image prompts)

**Script-level controls (bottom bar):**
- [Approve Script ->] advances to next pipeline stage
- [Export PDF] / [Export TXT]
- Stats: total words, estimated duration, scene count

#### Tab: Visuals (Image Prompts + Generated Images)
```
+----------------------------------+
| Visuals  | Scene 1 of 20        |
|                                  |
| -- Concept Segments --           |
| [Segment into Shots] (if not     |
|  already segmented)              |
|                                  |
| After segmentation:              |
|                                  |
| Segment 1/5  ESTABLISHING       |
| +------------------------------+ |
| | "A fire breaks out at a      | |
| |  Taiwan Semiconductor..."    | |
| |                              | |
| | -- Prompt --  [Edit] [Regen] | |
| | "3D editorial clay render,   | |
| |  wide establishing shot..."  | |
| |                              | |
| | -- Image --                  | |
| | +------------------------+   | |
| | |                        |   | |
| | |    [Generate $0.045]   |   | |
| | |                        |   | |
| | +------------------------+   | |
| |                              | |
| | [Split] [Merge] [Star Hero] | |
| +------------------------------+ |
|                                  |
| Segment 2/5  DETAIL              |
| +------------------------------+ |
| | "Two trillion dollars in     | |
| | market cap--gone in a..."    | |
| | ...                          | |
| +------------------------------+ |
|                                  |
| < Prev Scene | 1/20 | Next >    |
|                                  |
| [Generate All Scene 1 -- $0.23]  |
| [Generate ALL 108 images -- $4.86]|
+----------------------------------+
```

**Mobile: vertical scroll through segments within a scene,** swipe for scene navigation.

**Desktop: three-column layout per segment:**
```
+-----------------+------------------+-----------------+
| SCRIPT SEGMENT  | IMAGE PROMPT     | GENERATED IMAGE  |
| (editable)      | (editable)       | (or placeholder) |
|                 | + shot type badge| + generate btn   |
+-----------------+------------------+-----------------+
```

**Per-segment actions:**
- Edit script segment text (auto-save)
- Edit prompt text (auto-save, shows "Warning: Image may be outdated" if prompt changed after generation)
- Regenerate prompt only (re-call Claude for this segment)
- Generate image (call Seed Dream / Nano Banana)
- Regenerate image (new seed, same prompt)
- Try 3 Variants ($0.135 -- shows 3 options in a horizontal picker)
- Split segment into two
- Merge with adjacent segment
- Reorder (drag on desktop, long-press + move on mobile)
- Shot type override (tap badge to cycle: establishing -> detail -> reaction -> transition)
- Mark as hero shot (candidate for animation)
- Download image

**After image is generated, the placeholder becomes:**
```
+------------------------+
|                        |
|    [actual image]      |
|                        |
+------------------------+
| Regen | 3 Var          |
| Hero  | Save           |
| Del   | Zoom           |
+------------------------+
```

**Cost display:**
- Per segment: "$0.045" next to generate button
- Per scene: "5 images * $0.23" at scene level
- Global: "108 images * $4.86 estimated" at bottom

#### Tab: Storyboard
```
+----------------------------------+
| Storyboards  | 12 grids         |
|                                  |
| Grid 1 (Scenes 1-2, 9 panels)   |
| +------------------------------+ |
| | +----+----+----+             | |
| | | 1  | 2  | 3  |             | |
| | +----+----+----+             | |
| | | 4  | 5  | 6  |  [3x3 grid | |
| | +----+----+----+   image]    | |
| | | 7  | 8  | 9  |             | |
| | +----+----+----+             | |
| +------------------------------+ |
| Status: Approved                 |
|                                  |
| -- Panels --                     |
| Tap any panel to expand:         |
|                                  |
| Panel 1 -> Scene 1, Beat 1      |
| +--------------------+           |
| |                    |           |
| | [extracted panel,  |           |
| |  full resolution]  |           |
| |                    |           |
| +--------------------+           |
| Script: "A fire breaks out..."   |
| Prompt: "3D clay render, wide...".|
|                                  |
| [Approve] [Reject]              |
| [Regenerate Panel]               |
| [Upscale] <- triggers Nano      |
|                     Banana 2     |
|                                  |
| -- Upscaled Result --            |
| +--------------------+           |
| |                    |           |
| | [upscaled 16:9     |           |
| |  production image] |           |
| |                    |           |
| +--------------------+           |
| [Use This] [Re-upscale]         |
|                                  |
| Grid 2 (Scenes 3-4, 9 panels)   |
| ...                              |
|                                  |
| [Generate All Grids -- $0.90]    |
| [Upscale All Approved -- $4.50]  |
+----------------------------------+
```

**Storyboard workflow (3 steps visible in UI):**
1. **Grid view** -- see the full 3x3 contact sheet. Tap to expand individual panels.
2. **Panel review** -- approve or reject each panel. See the script segment and prompt that generated it.
3. **Upscale** -- approved panels get upscaled via Nano Banana 2 with image_input reference. The upscaled result becomes the production image.

**Desktop: side-by-side layout:**
```
+--------------+--------------+--------------+
|  3x3 Grid    | Selected     | Upscaled     |
|  (clickable  | Panel        | Result       |
|   panels)    | (full res)   | (production) |
|              |              |              |
|  [1][2][3]   | Script text  | [Use This]   |
|  [4][5][6]   | Prompt text  | [Re-upscale] |
|  [7][8][9]   | [Approve]    | [Download]   |
|              | [Reject]     |              |
+--------------+--------------+--------------+
```

**Character Reference in Storyboard:**
When a character reference image exists, it's shown as a small thumbnail in the grid generation UI with the label "Character locked -- reference will be passed to all grids." The user can change the reference image here, which triggers regeneration of affected grids.

#### Tab: Thumbnail
```
+----------------------------------+
| Thumbnail                        |
|                                  |
| -- Current --                    |
| +----------------------------+   |
| |                            |   |
| |   [current thumbnail       |   |
| |    at 16:9 preview]        |   |
| |                            |   |
| +----------------------------+   |
| Title: "HORMUZ $2K DRONE"       |
| CTR: 2.8% (below 3% threshold)  |
|                                  |
| -- Variants --                   |
| +------+ +------+ +------+      |
| | V1   | | V2   | | V3   |      |
| |      | |      | |      |      |
| +------+ +------+ +------+      |
| [Use V1] [Use V2] [Use V3]      |
|                                  |
| -- Prompt --  [Edit]             |
| "Comic editorial illustration,  |
|  bold yellow text 'CHECKMATE'..."|
|                                  |
| [Regenerate 3 New Variants]      |
| [Swap Live Thumbnail]            |
|                                  |
| -- Swap History --               |
| Mar 20: Changed -> +0.4% CTR    |
| Mar 18: Original -> 1.9% CTR    |
+----------------------------------+
```

**Yin-Yang system visible:** Title and thumbnail text shown side by side:
```
Title: "Hormuz $2K Drone That Changed Naval Warfare"
       (intellectual framework -- HOW)
Thumb: "$9 GAS IS COMING"
       (emotional gut punch -- WHAT)
```

If they're too similar, show warning: "Warning: Title and thumbnail text overlap -- yin-yang system recommends different angles."

#### Tab: Performance
```
+----------------------------------+
| Performance                      |
|                                  |
| Views: 2,400  |  CTR: 2.8%      |
| Retention: 44% | Watch: 6.2 min |
| Subs gained: 12                  |
|                                  |
| -- Timeline --                   |
| 24h: 800 views  |  CTR: 3.1%    |
| 48h: 1,400      |  CTR: 2.9%    |
| 7d:  2,200      |  CTR: 2.8%    |
| 30d: 2,400      |  CTR: 2.8%    |
|                                  |
| -- Post-Mortem --                |
| 48h verdict: Warning Below threshold |
| "CTR dropped after initial push. |
|  Thumbnail may not be standing   |
|  out in Suggested feed. Consider |
|  swap to brighter composition."  |
|                                  |
| 7d verdict: [pending]            |
|                                  |
| -- Autopilot Actions --          |
| Mar 20: Thumbnail swapped        |
| Mar 21: Title A/B test started   |
|                                  |
| -- Production Cost --            |
| Research: $0.50  | Script: $0.40 |
| Images: $4.50    | Voice: $1.20  |
| Thumbnail: $0.23 | Animation: -- |
| Total: $6.83     | ROI: -$6.83  |
| (Revenue estimate at $12 RPM:    |
|  $0.03 -- needs 570 more views  |
|  to break even)                  |
+----------------------------------+
```

---

## Screen 4: Create New Video (Content Creation Flow)

**Purpose:** Input a new idea and kick off the pipeline.

### Mobile Layout
```
+----------------------------------+
| <- Back                          |
|                                  |
|  What's Your Story?              |
|  Every great video starts with   |
|  a compelling idea.              |
|                                  |
| Title *                          |
| +------------------------------+ |
| | The AI Chip Shortage That    | |
| | Could Crash the Economy      | |
| +------------------------------+ |
|                                  |
| Angle *                          |
| +------------------------------+ |
| | Most people think AI is      | |
| | just software, but the real  | |
| | bottleneck is hardware       | |
| +------------------------------+ |
|                                  |
| Thesis *                         |
| +------------------------------+ |
| | The global AI boom depends   | |
| | on a handful of chip fabs... | |
| +------------------------------+ |
|                                  |
| +------------------------------+ |
| | v Advanced Options           | |
| |                              | |
| | Past Context                 | |
| | [textarea]                   | |
| |                              | |
| | Future Prediction            | |
| | [textarea]                   | |
| |                              | |
| | Opening Hook                 | |
| | [textarea]                   | |
| |                              | |
| | Tone: [Custom v]            | |
| | [custom tone input]          | |
| |                              | |
| | Target Length                 | |
| | [5] [10] [15] [20] min      | |
| |                              | |
| | Character Slots              | |
| | +------+ +------+ +------+  | |
| | |+ Add | |+ Add | |+ Add |  | |
| | |Char 1| |Char 2| |Char 3|  | |
| | +------+ +------+ +------+  | |
| | (tap to upload ref image     | |
| |  or select from roster)      | |
| |                              | |
| | Visual Profile               | |
| | [Holographic HUD v]         | |
| | (or: Cinematic Dossier,      | |
| |  Clay Mannequin,             | |
| |  Cinematic Illustration)     | |
| +------------------------------+ |
|                                  |
| +------------------------------+ |
| |    Generate Story ->         | |
| |    (creates Airtable record, | |
| |     pipeline picks it up)    | |
| +------------------------------+ |
+----------------------------------+
```

**Character Slots:** Expandable section. Each slot is a circular avatar placeholder:
- Tap empty slot -> options: Upload Image, Generate with Nano Banana, Select from Channel Profile roster
- If uploading: Claude Vision analyzes -> generates Character Block -> shows preview description
- If selecting from roster: shows existing archetypes with reference images
- Slot shows character name + small reference image when filled
- Characters are tagged to scenes later in the script stage

**Visual Profile selector:** Dropdown showing the 4 template presets (holographic, dossier, clay, illustration) plus "Custom" which uses the Channel Profile's custom style prefix/suffix. Each option shows a small preview thumbnail.

---

## Screen 5: Settings

### Channel Profile
(Matches the screenshots from the old app -- rebuild exactly)

### API Keys (BYOK)
(Matches the old app -- Anthropic, Kie.ai, ElevenLabs with validation)

### Pipeline Config (NEW)
```
+----------------------------------+
| Pipeline Configuration           |
|                                  |
| -- Cron Schedule (read-only) --  |
| Discovery: 5:00 AM PT           |
| Queue Runner: 8:00 AM PT        |
| Performance: 7:00 AM PT         |
| Approval Watch: every 30 min    |
|                                  |
| -- Stage Toggles --              |
| Video Generation: [OFF]  (manual)|
| Storyboard Mode: [ON]           |
| Auto-upload: [ON] (as draft)    |
|                                  |
| -- Cost Alerts --                |
| Monthly budget: [$200]           |
| Alert at: [80%]                  |
| Current spend: $47.20            |
|                                  |
| -- Default Models --             |
| Scene images: [Nano Banana 2 v] |
| Thumbnails: [Nano Banana Pro v] |
| Animation: [Grok Imagine v]     |
| Voice: [ElevenLabs v]           |
+----------------------------------+
```

---

## Screen 6: Autopilot Monitor

**Purpose:** See what the autonomous brain is doing. Review its decisions. Override when needed.

### Mobile Layout
```
+----------------------------------+
| Autopilot  [G Active]  [OFF]    |
|                                  |
| -- Active Tests --               |
| +------------------------------+ |
| | Taiwan Chip Shortage         | |
| | Testing: "hidden_flaw" (78%) | |
| | Title A: "The AI Chip..."    | |
| | Title B: "Why TSMC Is..."    | |
| | Poll: A winning (62%)        | |
| | [Override] [Close Test]      | |
| +------------------------------+ |
|                                  |
| -- Recent Actions --             |
| Swap Swapped thumbnail: Hormuz  |
|    Old CTR: 1.9% -> New: 2.8%  |
| Chart Analyzed 12 competitor vids|
| Tag New pattern: "time_bomb"    |
|    works at 5.2% avg CTR        |
|                                  |
| -- Structure Performance --      |
| hidden_flaw:    ####o 4.8%      |
| asymmetric_dg:  ###oo 3.9%      |
| time_bomb:      ##### 5.2%      |
| paradigm_shift: ##ooo 2.1%      |
| illusion_ctrl:  ###oo 3.6%      |
|                                  |
| -- Pattern Library --            |
| 86 competitor videos analyzed    |
| 6 curiosity gap structures       |
| Top performer: time_bomb (5.2%) |
| [View Full Library ->]           |
|                                  |
| -- Learnings --                  |
| "Dark thumbnails consistently    |
|  underperform (0.7-1.9% CTR).   |
|  Bright editorial with massive   |
|  text outperforms (4.2-7.4%)."  |
| [View All Learnings ->]          |
+----------------------------------+
```

**Kill switch:** The [OFF] toggle at the top immediately sets `CURIOSITY_GAP_ENABLED = false` and pauses all autopilot actions. Shows confirmation dialog first.

---

## Screen 7: Analytics Dashboard

### Mobile Layout
```
+----------------------------------+
| Analytics                        |
| Last 30 days                     |
|                                  |
| +----------+  +----------+      |
| |  12,400  |  |   3.2%   |      |
| |  views   |  |   CTR    |      |
| |  +22%    |  |   +0.4%  |      |
| +----------+  +----------+      |
| +----------+  +----------+      |
| |   42%    |  |   $47    |      |
| | retention|  |  spend   |      |
| |  +3%     |  |  5 vids  |      |
| +----------+  +----------+      |
|                                  |
| -- CTR by Video --               |
| (horizontal bar chart)           |
| Iran Trap:       ######## 7.4%  |
| FDR 1933:        ##oooooo 2.4%  |
| Hormuz Drone:    ###oooo 2.8%   |
| AI Purge:        ##ooooo 1.9%   |
| --- 3% threshold ---             |
|                                  |
| -- Revenue Estimate --           |
| Est. monthly: $148 (at $12 RPM) |
| Production cost: $47.20          |
| Net margin: $100.80              |
|                                  |
| -- Video Performance Cards --    |
| (scrollable list of all videos   |
|  with views, CTR, retention,     |
|  cost, and ROI per video)        |
+----------------------------------+
```

---

## Interaction Patterns (Global)

### Mobile Gestures
- **Swipe left/right** on scene cards -> navigate between scenes
- **Pull down** -> refresh data
- **Long press** any card -> context menu (delete, force advance, etc.)
- **Pinch to zoom** on images and storyboard grids
- **Double tap** image -> fullscreen preview

### Loading States
- Skeleton cards while data loads (not spinners)
- Generation progress: "Generating scene 3 of 20..." with animated progress bar
- Image generation: placeholder with pulsing border, cost shown, then image fades in

### Toast Notifications
- "Script saved" (auto-save confirmation)
- "Image generated -- $0.045" (cost feedback)
- "Thumbnail swapped -- monitoring CTR" (autopilot action)
- "Warning: Generation failed -- [Retry]" (error with action)

### Offline / Slow Connection
- Cache last-viewed project locally
- Show "Last updated 5 min ago" timestamp
- Queue edits when offline, sync when connection returns

---

## Design Tokens

```css
:root {
  /* Base */
  --bg-primary: #0A0A0B;
  --bg-card: #141416;
  --bg-card-hover: #1A1A1E;
  --border: #2A2A2E;

  /* Text */
  --text-primary: #E8E8EA;
  --text-secondary: #8A8A8E;
  --text-muted: #5A5A5E;

  /* Accent */
  --amber: #D4A844;
  --amber-hover: #E0B850;
  --teal: #1A8A7A;
  --red: #C44545;
  --green: #3A9A5A;

  /* Status dots */
  --dot-complete: var(--green);
  --dot-current: var(--amber);
  --dot-pending: var(--text-muted);
  --dot-failed: var(--red);

  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 48px;

  /* Cards */
  --card-radius: 12px;
  --card-padding: var(--space-lg);
}
```

---

*End of UI/UX Addendum -- StoryEngine v4*
