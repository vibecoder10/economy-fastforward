---
name: eff-thumbnail-prompt
description: Model winning YouTube thumbnails into Economy FastForward style. Send a YouTube link of a video that's performing well, and get a thumbnail prompt that replicates what's working in the EFF bright editorial style. The source video is winning — this skill reverse-engineers why and applies it to your brand.
---

# Economy FastForward Thumbnail Generator

Model winning competitor thumbnails into Economy FastForward style.

## The Core Insight

**The user is sending you a YouTube link because that video is WINNING.** It has high CTR, strong views, proven performance. Your job is to:
1. Reverse-engineer WHY that thumbnail works
2. MODEL those winning elements into the EFF brand style
3. Preserve what makes it click-worthy while translating to EFF's visual identity

This is not loose inspiration — this is strategic modeling of proven winners.

## Input

**Required:**
- YouTube URL of a **winning video** (the user selected it because it's performing)

**Optional:**
- Title or theme for the EFF version (if adapting the topic)
- Any specific direction ("make it about China instead of Russia")

## Your Task

### Step 1: Analyze the Winning Thumbnail

Fetch the YouTube thumbnail and reverse-engineer what makes it WIN:
- **Composition** — What's the layout? (map, character, split scene, action shot)
- **Visual Hook** — What grabs attention in the first 0.5 seconds?
- **Color Psychology** — What emotions do the dominant colors trigger?
- **Text Strategy** — What words are on it? What's the curiosity trigger?
- **Metaphor/Symbol** — What visual shorthand tells the story instantly?
- **Why It Wins** — What specific elements make this click-worthy?

### Step 2: Model Into EFF Style

Take the WINNING ELEMENTS and translate them into Economy FastForward brand:
- Keep the composition strategy that works
- Keep the visual hook concept
- Keep the emotional trigger
- Apply EFF's bright editorial illustration style (NOT cinematic)
- Apply EFF's yellow text with black outline
- Apply EFF's 3-4 color palette system
- Ensure readable at 160x90px phone size

### Step 3: Generate the Complete Package

Output:
1. **Why It Wins** - Specific elements that make the source thumbnail perform (3-4 bullet points)
2. **What We're Modeling** - Which winning elements we're replicating
3. **EFF Title** - YouTube title with ONE CAPS word
4. **Thumbnail Text** - line_1 + line_2 (max 5 words total)
5. **Template Used** - Which of the 4 EFF templates fits best
6. **Final Prompt** - Complete Nano Banana Pro prompt, ready to paste

---

## The Economy FastForward Brand

### Channel Identity
Economy FastForward is a finance/geopolitics YouTube channel that uses:
- **Past → Present → Future** narrative framing
- Machiavellian/strategic analysis lens
- Topics: global economy, trade wars, sanctions, oil, tech, power plays
- Tone: revealing hidden truths, exposing traps, explaining complex systems

### Visual Brand
- BRIGHT editorial illustration style (never cinematic/photorealistic)
- High saturation, bright lighting, NO shadows or atmospheric effects
- Simple, instantly recognizable visuals at phone size (160x90px)
- Yellow (#FFD700) text with thick black outline and heavy drop shadow
- Text is the SINGLE LARGEST element (60-70% of frame width)
- Maximum 3-4 dominant colors per thumbnail
- 16:9 landscape, 1280x720

---

## The 4 EFF Templates

### Template A: Map + Barrier (35% usage)
**Best for:** geopolitical, oil, trade routes, chokepoints, sanctions, regional conflict

```
Bright colorful editorial illustration of the {region} from satellite view, vivid blue ocean and golden tan desert landmasses, {country_labels}, {barrier_description}, {consequence_elements}, bright saturated colors with high contrast, no dark areas, clean editorial map style, {palette_suffix}. In the exact center of the image, enormous bold yellow text reading '{line_1}' on the first line and '{line_2}' on the second line, the text is the single largest and most dominant element in the entire image filling 70 percent of frame width, thick black outline on every letter with heavy drop shadow, the text must be absolutely massive and impossible to miss at any size. Bright but not oversaturated, clean editorial style, 16:9 aspect ratio
```

### Template B: Character + Bold Text (25% usage)
**Best for:** leaders, companies, tech moguls, institutional power, figure-focused stories

```
Bright colorful editorial illustration of {character_description} standing {pose} in center of frame, surrounded by {thematic_elements}, {brand_elements}, bright blue sky or colorful background, {floating_elements} floating around them, bright saturated colors, high energy composition, {palette_suffix}. In the {text_position}, enormous bold yellow text reading '{line_1}' on the first line and '{line_2}' on the second line, the text is the single largest element filling 65 percent of frame width, thick black outline, heavy drop shadow, massive and impossible to miss. Bright lighting, high saturation, editorial illustration style, 16:9 aspect ratio
```

### Template C: Split Winner/Loser (20% usage)
**Best for:** sanctions, trade wars, bans, winners vs losers, before/after comparisons

```
Bright colorful editorial illustration showing a split scene, on the left side {loser_element}, on the right side {winner_element}, {connecting_element} between them, {scattered_elements} scattered around, bright saturated colors with high contrast, no dark areas, editorial illustration style, {palette_suffix}. In the {text_position} of the image, enormous bold yellow text reading '{line_1}' on the first line and '{line_2}' on the second line, the text is the single largest element filling 65-70 percent of frame width, thick black outline on every letter, heavy drop shadow, massive and readable at any size. Bright lighting, high saturation, 16:9 aspect ratio
```

### Template D: Symbolic Action (20% usage)
**Best for:** traps, power moves, economic mechanisms, metaphors, abstract concepts

```
Bright editorial illustration showing a map of {region}, countries in muted tan and sand tones, {highlight_country}. {metaphor_description}, {consequence_elements}, {geographic_labels}. Clean editorial map style with {palette_suffix}. In the exact center, enormous bold yellow text reading '{line_1}' on the first line and '{line_2}' on the second line, the text is the single largest element filling 70 percent of frame width, thick black outline, heavy drop shadow, absolutely massive. Bright but not oversaturated, editorial illustration style, 16:9 aspect ratio
```

---

## Title Formula Patterns

Pick the formula that best fits the topic:

1. **The [Noun] TRAP Nobody Sees Coming** - `"The {noun} {CAPS} Nobody Sees Coming ({parenthetical})"`
2. **[Country]'s $[Amount] [Mistake]** - `"{country}'s {amount} {CAPS} ({parenthetical})"`
3. **The Slow DEATH of [System]** - `"The Slow {CAPS} of {system} ({parenthetical})"`
4. **Why [Country] is [ADJECTIVE]er Than You Think** - `"Why {country} is {CAPS} Than You Think ({parenthetical})"`
5. **[Number] [Noun] [Warning]** - `"{number} {noun} {CAPS} ({parenthetical})"`
6. **How [Entity] SWALLOWED [Target]** - `"How {entity} {CAPS} {target} ({parenthetical})"`

**CAPS Word Rules:**
- BEST (emotional gut-punch): PURGE, TRAP, KILLED, CRUSHED, WEAPONIZED, BLACKLISTED, BANNED, BETRAYED, RIGGED, DOOMED, BROKE, DEAD, SWALLOWED, COLLAPSE, DEATH, DYING
- AVOID (generic/structural): STAGE, STEP, PHASE, PATTERN, LAWS, RULES, SYSTEM, PLAN

---

## Color Palettes

| Palette | Keywords | Prompt Suffix |
|---------|----------|---------------|
| **middle_east** | iran, iraq, saudi, oil, opec, hormuz | "only three dominant colors red blue and tan, no rainbow no neon, high contrast but restrained color scheme" |
| **finance** | economy, market, stock, bubble, debt, dollar | "dominant colors gold blue and green with red accent arrows, no rainbow no neon, bright saturated financial editorial style" |
| **tech** | ai, tech, silicon valley, google, nvidia, chip | "dominant colors blue green and orange, bright tech editorial style, no rainbow no neon, clean high contrast" |
| **military** | military, army, navy, pentagon, nato, weapon | "dominant colors red blue and white with military authority feel, no rainbow no neon, clean high contrast editorial style" |
| **global** | empire, world order, hegemony, superpower, brics | "dominant colors deep blue red and gold, no rainbow no neon, geopolitical editorial map style" |

---

## STYLE RULES (MANDATORY)

**ALWAYS:**
- BRIGHT editorial illustration style
- High saturation, bright lighting, NO shadows
- Simple, instantly recognizable visuals
- Maximum 3-4 dominant colors from palette
- Text is YELLOW (#FFD700), bold, black outline, heavy drop shadow
- Text is the SINGLE LARGEST element (60-70% of frame width)
- 16:9 landscape, 1280x720

**NEVER include these words:**
- "cinematic", "photorealistic", "film grain", "shallow depth of field"
- "dark", "moody", "atmospheric", "shadows", "chiaroscuro"
- Any film/camera references (Sicario, ARRI, RED, ISO)
- Any lighting suggesting darkness or moodiness

---

## Visual Metaphor Bank

**OBJECT metaphors:** bear trap, chess piece, domino chain, noose, vault door, ticking bomb, puppet strings, house of cards, guillotine, sinking ship, steel wall, chain with padlocks, giant hand

**MAP compositions:** geography with arrows, barriers, zones, chokepoints, blocked straits, highlighted countries, piled-up ships/vehicles

**SYMBOLIC ACTIONS:** hand grabbing/crushing, scale tipping, door slamming, rope pulling, wall cracking, cage closing, valve shutting

**Be SPECIFIC, not generic:**
- BAD: "map showing conflict in the region"
- GOOD: "the narrow Strait of Hormuz completely blocked by a massive red steel wall with giant X marks and CLOSED stamps, dozens of oil tankers piled up on the Arabian Sea side"

---

## Example Workflow

**User says:** "Hey I found this video, really interesting: https://youtube.com/watch?v=xyz - I want to do something similar about Iran's oil strategy"

**You do:**

### 1. Analyze Why It's Winning

**Why This Thumbnail Wins:**
- **Composition:** Split scene creates instant conflict/stakes
- **Visual Hook:** Crumbling buildings = visceral threat imagery
- **Color Psychology:** Red dominance triggers urgency/danger
- **Text Strategy:** Single word "COLLAPSE" in huge text = fear trigger + curiosity gap
- **Metaphor:** Economic destruction visualized as physical destruction

**What We're Modeling:**
- The split composition showing cause → effect
- The visceral threat imagery (destruction, damage)
- The single power word as the emotional hook
- The red/urgency color dominance

### 2. Generate EFF Version

**EFF Title:** The Oil TRAP Nobody Sees Coming (Why Iran Holds All the Cards)

**Thumbnail Text:**
- line_1: OIL TRAP
- line_2: COMING

**Template:** A (Map + Barrier) — models the "cause → effect" composition from the source

**Palette:** middle_east — models the urgency/danger color psychology

**Final Prompt:**
```
Bright colorful editorial illustration of the Persian Gulf and Strait of Hormuz from satellite view, vivid blue ocean and golden tan desert landmasses, small white labels for Iran Iraq Saudi Arabia Kuwait UAE Oman, the narrow Strait of Hormuz completely blocked by a massive red steel wall with giant X marks and CLOSED stamps, dozens of oil tankers piled up on the Arabian Sea side with dollar bills and red warning lights, bright saturated colors with high contrast, no dark areas, clean editorial map style, only three dominant colors red blue and tan, no rainbow no neon, high contrast but restrained color scheme. In the exact center of the image, enormous bold yellow text reading 'OIL TRAP' on the first line and 'COMING' on the second line, the text is the single largest and most dominant element in the entire image filling 70 percent of frame width, thick black outline on every letter with heavy drop shadow, the text must be absolutely massive and impossible to miss at any size. Bright but not oversaturated, clean editorial style, 16:9 aspect ratio
```

---

## Output Format

Always return:

```
## Why This Thumbnail Wins
- [Composition strategy that works]
- [Visual hook that grabs attention]
- [Color psychology being used]
- [Text/word strategy]
- [Visual metaphor or symbol]

## What We're Modeling
[2-3 sentences on which winning elements we're replicating and why]

## EFF Version

**Title:** [Full YouTube title with ONE CAPS word]

**Thumbnail Text:**
- line_1: [3-4 words, ALL CAPS]
- line_2: [2-3 words, ALL CAPS]

**Template:** [A/B/C/D] ([Template name]) — [why this template models the source]

**Palette:** [palette name] — [why this palette models the source]

**Final Prompt:**
[Complete prompt ready to paste into Nano Banana Pro]
```
