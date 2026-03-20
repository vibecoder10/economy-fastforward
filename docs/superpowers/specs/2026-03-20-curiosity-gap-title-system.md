# Curiosity Gap Title System

**Date:** 2026-03-20
**Status:** Approved
**Author:** Claude + Ryan

---

## Executive Summary

Upgrade Power Doctrine's title generation to use curiosity gap structures that create cognitive dissonance, forcing viewers to click. The system analyzes competitor titles/thumbnails to extract winning patterns, generates titles using 5 proven structures, creates yin/yang thumbnail text (complementary, not repetitive), and learns from CTR performance at 12h/24h/48h.

**Core Insight:** Current titles are descriptive ("How Iran Weaponized Geography"). Curiosity gap titles create tension ("The $100B Mistake Saudi Arabia Is Hiding"). The thumbnail doesn't repeat the title — it shows the surprising answer or consequence.

---

## Table of Contents

1. [The 5 Curiosity Gap Structures](#1-the-5-curiosity-gap-structures)
2. [Module Architecture](#2-module-architecture)
3. [Autopilot Integration](#3-autopilot-integration)
4. [Data Storage](#4-data-storage)
5. [Competitor Analyzer](#5-competitor-analyzer)
6. [Title & Thumbnail Generation](#6-title--thumbnail-generation)
7. [Traceability](#7-traceability)
8. [Guardrails & Edge Cases](#8-guardrails--edge-cases)
9. [Slack Commands](#9-slack-commands)
10. [Implementation Phases](#10-implementation-phases)

---

## 1. The 5 Curiosity Gap Structures

Each structure creates a different type of cognitive dissonance:

| ID | Structure | Gap Mechanism | When to Use | Example |
|----|-----------|---------------|-------------|---------|
| `hidden_flaw` | Hidden Flaw | "What's the mistake they're hiding?" | Financial waste, failed strategies, cover-ups | "The $100B Mistake Saudi Arabia Is Hiding" |
| `asymmetric_dg` | Asymmetric David/Goliath | "How does small beat big?" | Power imbalances, unexpected advantages | "Why the Navy Is Terrified of $500 Plastic" |
| `time_bomb` | Time-Bomb | "What trap was set? When does it trigger?" | Long-term strategies, delayed consequences | "The 40-Year Trap America Walked Into" |
| `paradigm_shift` | Paradigm Shift | "What reality am I missing?" | Reframing events, hidden truths | "The Map That Proves WWIII Already Begun" |
| `illusion_control` | Illusion of Control | "How does this affect ME personally?" | Personal stakes, economic impacts | "The Chokepoint That Controls Your Bank Account" |
| `other` | Unclassified | Novel pattern — flag for review | Doesn't fit above structures | Logged for weekly digest |

### Selection Logic

Claude analyzes story content (hook, thesis, key facts) and scores each structure 0-100 for fit:

- Does the story have a "waste" or "mistake" angle? → `hidden_flaw` +score
- Is there a power asymmetry? → `asymmetric_dg` +score
- Is there a long-term setup/trap? → `time_bomb` +score
- Does it reframe common understanding? → `paradigm_shift` +score
- Does it have direct viewer financial impact? → `illusion_control` +score

Top 3 scoring structures (above confidence floor) become title variants.

---

## 2. Module Architecture

### New Module: `curiosity_gap/`

```
skills/video-pipeline/
├── curiosity_gap/                    # NEW MODULE
│   ├── __init__.py
│   ├── structures.py                 # 5 structure definitions + CuriosityStructure enum
│   ├── gap_title_engine.py           # generate_titles(story) → 3 titles (NOT title_generator.py to avoid collision)
│   ├── thumbnail_generator.py        # yin/yang text generation (approach A or B)
│   └── competitor_analyzer.py        # analyze competitor title + thumbnail
```

**Naming Note:** The file is `gap_title_engine.py` NOT `title_generator.py` to avoid confusion with `thumbnail_title/title_generator.py`. Two files with similar names in one codebase causes wiring bugs.

### Integration with Existing Autopilot

```
skills/video-pipeline/autopilot/
├── learning/
│   ├── learning_extractor.py     # EXTEND: add curiosity_structure category
│   ├── pattern_library.py        # EXTEND: read curiosity gap patterns
│   └── memory_writer.py          # EXTEND: write curiosity gap learnings
│
├── memory/
│   ├── title_patterns.md         # EXTEND: add curiosity gap section
│   ├── thumbnail_patterns.md     # EXTEND: add yin/yang approach tracking
│   └── competitor_patterns.md    # NEW: extracted competitor patterns
│
└── analysis/
    └── thumbnail_analyzer.py     # EXTEND: extract yin/yang relationship
```

### Data Flow

```
                    ┌─────────────────────────────────┐
                    │     COMPETITOR ANALYSIS         │
                    │  (daily scrape + manual Slack)  │
                    └────────────────┬────────────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          ▼                          ▼                          ▼
   Quick title analysis      Deep thumbnail analysis     Store to Airtable
   (all >50 VPH videos)      (top 20% per channel)       + memory files
          │                          │                          │
          └──────────────────────────┴──────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │     PATTERN LIBRARY             │
                    │  (competitor + our learnings)   │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │     TITLE GENERATION            │
                    │  curiosity_gap.generate_titles()│
                    │  → selects top 3 structures     │
                    │  → generates yin/yang thumbnails│
                    └────────────────┬────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │     SLACK POLL (2h timeout)     │
                    │  Human selects or auto-select   │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │     OUR VIDEO PUBLISHES         │
                    │  Track: structure + approach    │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
                  12h CTR         24h CTR          48h CTR
                    │                │                │
                    └────────────────┴────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │     LEARNING EXTRACTION         │
                    │  learning_extractor.extract()   │
                    │  → logs structure performance   │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
                              Pattern Library
                              (loop closes)
```

---

## 3. Autopilot Integration

### Daily Schedule (Automatic)

| Time | Job | Curiosity Gap Integration |
|------|-----|---------------------------|
| 5:00 AM | `competitor_scraper` | **NEW:** Quick title analysis on all scraped videos (>50 VPH) |
| 5:30 AM | — | **NEW:** Deep thumbnail analysis on top 20% per channel |
| 6:30 AM | `autopilot --check-cycle` | Reads pattern library → selects idea → generates titles with curiosity gap → posts Slack poll |
| 7:00 AM | `performance_tracker` | Gets CTR data for our videos |
| 7:30 AM | `ctr_monitor` | Checks 12h/24h/48h CTR |
| 8:00 AM | `pipeline --run-queue` | Produces video with selected title + thumbnail |
| 8:30 AM | `learning_extractor` | **EXTENDED:** Extracts curiosity structure + yin/yang approach performance |
| Monday 9:00 AM | `other_digest` | **NEW:** Weekly digest of unclassified titles for pattern discovery |

### Manual Slack Commands (Feed Same System)

| Command | What It Does | Writes To |
|---------|--------------|-----------|
| `analyze [video URL]` | Deep analysis of single competitor video | Airtable + `competitor_patterns.md` |
| `analyze @ChannelName` | Batch analyze channel's top 10 videos | Airtable + `competitor_patterns.md` |
| `analyze competitors` | Analyze all active channels | Airtable + `competitor_patterns.md` |
| `patterns titles` | Show current title pattern library | (read only) |
| `patterns thumbnails` | Show current thumbnail pattern library | (read only) |

**Key Principle:** Manual and automatic both write to the same stores. No parallel systems.

---

## 4. Data Storage

### Airtable: Competitor Videos Table — New Fields

| Field | Type | Purpose |
|-------|------|---------|
| `Curiosity Structure` | Single Select | `hidden_flaw`, `asymmetric_dg`, `time_bomb`, `paradigm_shift`, `illusion_control`, `other` |
| `Structure Confidence` | Number | 0-100 how well title fits the structure |
| `Thumbnail Style JSON` | Long Text | `{"colors": [...], "composition": "...", "text": "..."}` |
| `Yin Yang Approach` | Single Select | `from_hook`, `from_gap` |
| `Yin Yang Text` | Single Line | The actual thumbnail text extracted |
| `Analysis Date` | Date | When we analyzed this video |
| `Modeled By Us` | Checkbox | Whether we've used this pattern |
| `Our CTR Result` | Number | CTR when we modeled this pattern |

### Airtable: Ideas Table — New Fields

| Field | Type | Purpose |
|-------|------|---------|
| `Curiosity Structure` | Single Select | Which structure was used |
| `Structure Confidence` | Number | Confidence score at generation time |
| `Structure Source` | Long Text | JSON: `{"competitor_refs": ["rec123"], "our_refs": ["rec456"]}` |
| `Thumbnail Approach` | Single Select | `from_hook` or `from_gap` |
| `Thumbnail Text` | Single Line | The yin/yang text generated |
| `Pattern Library Snapshot` | Long Text | Which patterns informed this decision |
| `Title Poll Result` | Single Select | `human_selected`, `auto_selected` |
| `Poll Closed` | Checkbox | Whether poll auto-selected (prevents late vote changes) |
| `CTR 12h` | Number | CTR at 12 hours |
| `CTR 24h` | Number | CTR at 24 hours |
| `CTR 48h` | Number | CTR at 48 hours |

**JSON Field Note:** `Structure Source`, `Pattern Library Snapshot`, and `Thumbnail Style JSON` are **stringified JSON in Long Text fields**, NOT native Airtable JSON (which doesn't exist). Read with `json.loads()`, write with `json.dumps()`. This follows the existing pattern used by `Original DNA` and `Research Payload` fields.

### Memory Files

**`autopilot/memory/title_patterns.md`** (extended):

```markdown
# Title Patterns

Last updated: 2026-03-20
Sample size: 12 videos (ours) + 47 competitors

## Curiosity Gap Structures (USE)

### hidden_flaw
- Avg CTR: 5.1% (n=3 ours)
- Competitor avg VPH: 165 (n=12)
- Best: "The $100B Mistake..." → 5.8% CTR
- Gap mechanism: "What's the mistake they're hiding?"

### asymmetric_dg
- Avg CTR: 4.2% (n=2 ours)
- Competitor avg VPH: 142 (n=8)
- Gap mechanism: "How does that math work?"

## Anti-Patterns (AVOID)
- descriptive_no_gap: Avg CTR 2.1% (n=4)
  - "How Iran Weaponized Geography" → no curiosity gap

## Notes
- hidden_flaw: CTR 5.8% (keep) - "The $100B Mistake..."
- asymmetric_dg: CTR 4.2% (keep) - "Why Navy Terrified..."
```

**`autopilot/memory/competitor_patterns.md`** (new):

```markdown
# Competitor Patterns

Last updated: 2026-03-20
Videos analyzed: 47

## Top Performing Structures (by VPH)

### hidden_flaw (n=12, avg VPH: 165)
- CaspianReport: "The Pipeline Trap Nobody..." (VPH: 210)
- Economics Explained: "The $2T Mistake..." (VPH: 180)

### time_bomb (n=8, avg VPH: 148)
- PolyMatter: "The 30-Year Trap China..." (VPH: 175)

## Thumbnail Styles (by channel)

### CaspianReport
- Dominant: red/yellow, face-left, 2-line text
- Yin/yang: Title = problem → Thumbnail = consequence

### Economics Explained
- Dominant: blue/white, data overlay, single line
- Yin/yang: Title = mystery → Thumbnail = hint

## Unclassified (other) — Pending Review
- "5 Days Until China's Dollar Deadline" (countdown pattern?)
- "The Leaked Memo That Changes Everything" (leaked_truth pattern?)
```

---

## 5. Competitor Analyzer

### Two-Phase Analysis

**Phase 1: Quick Title Analysis (All >50 VPH videos)**

Runs during daily scrape. Fast, cheap, text-only.

```python
# curiosity_gap/competitor_analyzer.py

@dataclass
class TitleAnalysis:
    structure: str              # "hidden_flaw" or "other"
    confidence: int             # 0-100
    gap_mechanism: str          # "What's the mistake?"
    variables: Dict[str, str]   # {"amount": "$100B", "entity": "Saudi Arabia"}

async def analyze_title(title: str) -> TitleAnalysis:
    """Claude analyzes title structure (no vision needed)."""
```

**Claude Prompt:**
```
Analyze this competitor title and identify which curiosity gap structure it uses:

TITLE: "{title}"

STRUCTURES:
1. hidden_flaw - "What mistake/failure are they hiding?"
2. asymmetric_dg - "How does small beat big?"
3. time_bomb - "What trap was set long ago?"
4. paradigm_shift - "What reality am I missing?"
5. illusion_control - "How does this affect ME personally?"
6. other - Doesn't fit above (describe the pattern)

Return: structure_id, confidence (0-100), gap_mechanism, extracted_variables
```

**Phase 2: Deep Thumbnail Analysis (Top 20% per channel)**

Vision API call — more expensive, only for top performers.

```python
@dataclass
class ThumbnailAnalysis:
    colors: List[str]
    composition: str
    text_extracted: str
    yin_yang_relationship: str
    yin_yang_approach: str      # "from_hook" or "from_gap"

async def analyze_thumbnail(
    video_id: str,
    title: str,
    use_gemini: bool = True
) -> ThumbnailAnalysis:
    """
    Gemini Vision (default) or Claude Vision analyzes thumbnail.
    Extracts visual style + yin/yang relationship to title.
    """
```

### VPH Normalization with Cold Start Handling

```python
import bisect

MIN_CHANNEL_SAMPLE = 5
COLD_START_VPH_THRESHOLD = 100

async def should_deep_analyze(video: CompetitorVideo) -> bool:
    channel_videos = await get_recent_videos(video.channel_id, limit=20)

    if len(channel_videos) < MIN_CHANNEL_SAMPLE:
        # Cold start: fall back to absolute threshold
        return video.vph >= COLD_START_VPH_THRESHOLD

    vphs = sorted([v.vph for v in channel_videos])
    # Use bisect for correct percentile (handles duplicate VPH values)
    percentile = bisect.bisect_left(vphs, video.vph) / len(vphs) * 100
    return percentile >= 80  # Top 20% of channel's recent videos
```

### Cost Management

- Phase 1 (title only): ~$0.002 per video
- Phase 2 (thumbnail): ~$0.01 per video (Gemini Vision)
- Daily budget: ~50 Phase 1 + ~10 Phase 2 = ~$0.20/day

---

## 6. Title & Thumbnail Generation

### Yin/Yang Thumbnail Concept

**Bad (repetitive):**
- Title: "How Iran TRAPPED the US Navy"
- Thumbnail: "IRAN TRAPPED"

**Good (complementary):**
- Title: "Why The US Navy Can't Open Hormuz"
- Thumbnail: "FISHING BOATS WIN"

The thumbnail shows the *tension* or *surprising element* that the title doesn't reveal.

### Two Thumbnail Approaches

| Approach | Source | Example |
|----------|--------|---------|
| `from_hook` | Surprising detail from the hook script | If hook mentions "fishing boats with missiles duct-taped" → thumbnail: "FISHING BOATS WIN" |
| `from_gap` | Answer hint that title withholds | Title: "The $100B Mistake" → thumbnail: "PIPELINES USELESS" |

Claude selects approach per title based on which creates stronger yin/yang.

### Generation Flow

```python
# curiosity_gap/gap_title_engine.py

@dataclass
class GeneratedTitle:
    text: str                        # "The $100B Mistake Saudi Arabia Is Hiding"
    structure: str                   # "hidden_flaw"
    structure_confidence: int        # 78
    thumbnail_text: str              # "WORTHLESS PIPELINES"
    thumbnail_approach: str          # "from_gap"
    reasoning: str                   # "Story has clear financial waste angle..."

    # Traceability
    source_patterns: List[str]       # ["competitor:rec123", "ours:rec456"]
    competitor_video_ids: List[str]  # Airtable record IDs that informed this

async def generate_titles(
    hook: str,
    thesis: str,
    facts: List[str],
    pattern_library: PatternLibrary
) -> List[GeneratedTitle]:
    """
    1. Load proven patterns from library (ours + competitor)
    2. Claude analyzes story content
    3. Claude scores each structure 0-100 for fit
    4. Filter to structures above CONFIDENCE_FLOOR (60)
    5. Generate top 3 titles (one per best-fit structure)
    6. For each title, generate yin/yang thumbnail text
    7. If <3 viable structures, fill with MF fallback formulas
    """
```

### Claude Prompt for Generation

```
You are generating titles for Power Doctrine YouTube channel.

STORY CONTEXT:
Hook: {hook}
Thesis: {thesis}
Key facts: {facts}

PROVEN PATTERNS (from our CTR data):
{patterns_from_our_videos}

COMPETITOR PATTERNS (high VPH):
{patterns_from_competitors}

TASK:
1. Score each of the 5 structures (0-100) for fit with this story
2. For top 3 structures with score >= 60:
   - Generate a title using that structure
   - Generate yin/yang thumbnail text (2-4 words, ALL CAPS)
   - Select thumbnail approach: from_hook or from_gap
3. Explain reasoning for each

STRUCTURES:
- hidden_flaw: "What mistake are they hiding?"
- asymmetric_dg: "How does small beat big?"
- time_bomb: "What trap was set?"
- paradigm_shift: "What am I missing?"
- illusion_control: "How does this affect ME?"
```

---

## 7. Traceability

Every decision traces back to source data.

### Full Audit Trail Example

```
Video: "The $100B Pipeline Trap"
├── Structure: hidden_flaw (confidence: 78)
├── Source: Modeled from competitor rec_abc123 (CaspianReport, VPH 210)
├── Thumbnail: "WORTHLESS" (from_gap approach)
├── Poll Result: human_selected (beat auto-select candidate)
├── Generated: 2026-03-20 06:32 AM
│
├── CTR 12h: 4.8%
├── CTR 24h: 5.1%
├── CTR 48h: 5.2% → KEEP verdict
│
└── Learning written:
    ├── title_patterns.md: "hidden_flaw: CTR 5.2% (keep) - The $100B Pipeline Trap"
    ├── Ideas table: all fields populated
    └── Competitor Videos rec_abc123: Our CTR Result = 5.2%
```

### What Gets Logged

| Event | Airtable | Memory File |
|-------|----------|-------------|
| Competitor analyzed | Competitor Videos table | competitor_patterns.md |
| Title generated | Ideas table (Structure Source field) | — |
| Poll completed | Ideas table (Title Poll Result) | — |
| CTR measured | Ideas table (CTR 12h/24h/48h) | — |
| Learning extracted | — | title_patterns.md, thumbnail_patterns.md |

---

## 8. Guardrails & Edge Cases

### 8.1 "Other" Bucket — Weekly Digest

The `other` category will be noisy initially (60-70% of competitor titles). Instead of per-video notifications, aggregate weekly:

```
Every Monday 9:00 AM:

📊 *UNCLASSIFIED TITLES DIGEST*

This week: 23 competitor titles landed in "other"

*Cluster A (8 titles) — "Countdown" pattern:*
- "5 Days Until China's Dollar Deadline"
- "72 Hours Before the Crash"
- "The 30-Day Window Nobody Sees"
→ Possible new structure: deadline_countdown?

*Cluster B (6 titles) — "Secret Document" pattern:*
- "The Leaked Memo That Changes Everything"
- "CIA Document Reveals..."
→ Possible new structure: leaked_truth?

*Unclustered (9 titles):* [View in Airtable]

Reply with structure name to promote a cluster.
```

### 8.2 Confidence Floor — Fallback to MF Formulas

```python
CONFIDENCE_FLOOR = 60

async def generate_titles(story_context, pattern_library):
    scores = await score_structures(story_context)
    viable = [s for s in scores if s.confidence >= CONFIDENCE_FLOOR]

    if len(viable) < 3:
        # Not enough strong fits — fill remaining with MF formulas
        return await fallback_to_mf_formulas(
            story_context,
            viable_structures=viable,
            fill_with_mf=True  # MF-0, MF-1, MF-2 as backup
        )

    return await generate_from_structures(viable[:3], story_context)
```

Slack notification when fallback triggers:
```
⚠️ *LOW STRUCTURE FIT*

Story: "Iran's New Naval Doctrine"
Best structure: time_bomb (confidence: 52)

Falling back to MF formulas for 2 of 3 title slots.
Consider: Does this story need a different angle?
```

### 8.3 Title A/B Poll — 2-Hour Timeout

Before locking a title, Slack poll for human signal:

```
🗳️ *TITLE VOTE* (auto-selects highest confidence in 2h)

Story: Iran's Hormuz Strategy

*A* (hidden_flaw, 78 conf): ⭐ AUTO-SELECT IF NO VOTE
"The $100B Pipeline Mistake Iran Exposed"
Thumbnail: "WORTHLESS"

*B* (asymmetric_dg, 71 conf):
"Why Iran's Fishing Boats Beat the US Navy"
Thumbnail: "$500 DRONES"

*C* (time_bomb, 65 conf):
"The 40-Year Trap Iran Set in Hormuz"
Thumbnail: "CHECKMATE"

React: 🅰️ 🅱️ 🅲
```

**Auto-select logic:**
- After 2 hours with no vote → select highest confidence option
- Track auto-select rate weekly
- >80% auto-select → poll isn't adding value, consider tightening loop
- <50% auto-select → humans actively curating, keep it

**Late vote handling:**
When auto-select fires, set `poll_closed=True` in the poll state. The reaction handler checks this flag:
```python
async def handle_poll_reaction(reaction, poll_id):
    poll = await get_poll_state(poll_id)

    if poll.closed:
        # Late vote after auto-select - ignore and notify
        await slack.reply_in_thread(
            poll.thread_ts,
            f"⏰ Poll already closed. Title '{poll.selected_title}' is locked."
        )
        return

    # Process valid vote...
```
This prevents late votes from triggering title changes mid-pipeline.

### 8.4 Kill Switch — Global Rollback

If curiosity gap titles underperform MF formulas in early weeks, instant rollback without code deploy:

**Toggle:** `CURIOSITY_GAP_ENABLED` (env var OR Airtable Settings table checkbox)

```python
# At start of title generation
async def generate_titles_for_idea(idea_record, story_context):
    if not is_curiosity_gap_enabled():
        # Fallback to pure MF formulas
        return await generate_mf_titles(story_context)

    # Normal curiosity gap flow...
```

**Airtable Settings table:**
| Field | Value |
|-------|-------|
| `Curiosity Gap Enabled` | ✅ (checkbox) |

The cron auto-pulls code, so toggling the Airtable checkbox = instant rollback.

---

## 9. Slack Commands

### Competitor Analysis

| Command | Action |
|---------|--------|
| `analyze https://youtube.com/watch?v=xyz` | Deep analyze single video |
| `analyze @CaspianReport` | Batch analyze channel's top 10 |
| `analyze competitors` | Analyze all active competitor channels |

### Pattern Library

| Command | Action |
|---------|--------|
| `patterns titles` | Show title structure performance |
| `patterns thumbnails` | Show thumbnail style performance |
| `patterns competitors` | Show competitor pattern summary |

### Autopilot

| Command | Action |
|---------|--------|
| `autopilot status` | Show current state including curiosity gap stats |
| `autopilot force` | Force production cycle now |

---

## 10. Implementation Phases

**IMPORTANT:** Build competitor analyzer FIRST to seed pattern library. The title generator needs real data from day one — empty patterns produce blind outputs.

### Phase 1: Competitor Analysis + Data Seeding (Week 1)

- [ ] Create `curiosity_gap/` module structure
- [ ] Implement `structures.py` with 5 structures + `other` + CuriosityStructure enum
- [ ] Implement `competitor_analyzer.py` Phase 1 (title analysis)
- [ ] Implement `competitor_analyzer.py` Phase 2 (thumbnail vision)
- [ ] Add VPH normalization with cold start handling (bisect)
- [ ] Add Airtable fields to Competitor Videos table
- [ ] Create `competitor_patterns.md` memory file
- [ ] **Seed library with ~50 competitor titles** before moving to Phase 2
- [ ] Tests for analyzer components

### Phase 2: Core Generation Module (Week 2)

- [ ] Implement `gap_title_engine.py` with Claude integration
- [ ] Implement `thumbnail_generator.py` with yin/yang logic
- [ ] Add confidence floor + MF fallback
- [ ] Add `CURIOSITY_GAP_ENABLED` kill switch (env var + Airtable checkbox)
- [ ] Extend `pattern_library.py` to read curiosity gap patterns
- [ ] Tests for generation components

### Phase 3: Learning Integration (Week 3)

- [ ] Extend `learning_extractor.py` for `"structure"` category
- [ ] Extend `memory_writer.py` to write curiosity gap learnings
- [ ] Add Airtable fields to Ideas table
- [ ] Wire CTR 12h/24h/48h tracking
- [ ] Integrate with daily `competitor_scraper` run

### Phase 4: Autopilot + Slack (Week 4)

- [ ] Add Slack poll for title selection (2h timeout)
- [ ] Add `poll_closed` flag + late vote handling
- [ ] Add `analyze` Slack commands
- [ ] Add `patterns` Slack commands
- [ ] Implement weekly "other" digest
- [ ] Update cron schedule with new jobs
- [ ] End-to-end testing with real competitor data

### Phase 5: Bot Integration (Week 5)

- [ ] Integrate with `idea_bot.py`
- [ ] Integrate with `trending_idea_bot.py`
- [ ] Integrate with `thumbnail_title/title_generator.py` (receives yin/yang text)
- [ ] Full pipeline test: competitor → pattern → generation → publish → CTR → learning
- [ ] Rollback testing: verify kill switch works

---

## Appendix A: Technical Clarifications

### A.1 Learning Extractor Category Definition

The `learning_extractor.py` currently supports these categories:
```python
category: str  # "thumbnail", "title", "topic", "theme", "angle", "formula"
```

We add a NEW category `"structure"` (not replacing `"title"`):

```python
# NEW: Add to ExtractedLearning categories
category: str  # existing + "structure" for curiosity gap structures

# Example extraction
ExtractedLearning(
    category="structure",           # NEW category
    pattern="hidden_flaw",          # The structure ID
    verdict=CTRVerdict.KEEP,
    confidence=75.0,
    evidence="hidden_flaw structure. CTR: 5.2%",
    video_title="The $100B Pipeline Trap",
    ctr=5.2,
)
```

The existing `"title"` category continues to track surface patterns (question, number, caps). The new `"structure"` category tracks the curiosity gap taxonomy.

### A.2 CTR Tracking Timeline

The existing system tracks CTR at 6h/24h/48h via `ctr_monitor.py`. We ADD 12h tracking:

**How it works:** The `performance_tracker.py` runs at 7:00 AM daily and pulls YouTube Analytics data. CTR snapshots are written to Airtable when the video crosses each milestone:

| Milestone | When Written | Source |
|-----------|--------------|--------|
| CTR 6h | First ctr_monitor run after 6h | Existing early warning |
| CTR 12h | **NEW:** First performance_tracker run after 12h | performance_tracker.py |
| CTR 24h | First performance_tracker run after 24h | Existing |
| CTR 48h | First performance_tracker run after 48h | Existing |

**Implementation:** Add to `performance_tracker.py`:
```python
# Check if 12h has passed and CTR 12h not yet written
if hours_since_publish >= 12 and not record.get("CTR 12h"):
    await update_record(record_id, {"CTR 12h": current_ctr})
```

### A.3 MF Fallback Formulas Definition

MF formulas are the EXISTING title formulas from the user's current system (visible in the example ideas they provided):

| ID | Formula | Example |
|----|---------|---------|
| MF-0 | CHOKE POINT — geographic/strategic control | "How Iran Turned the Gulf Into a Hostage" |
| MF-1 | GEOGRAPHIC TRAP — terrain as weapon | "How Iran Quietly Weaponized Geography" |
| MF-2 | EXITS LOCKED — no escape framing | "Why Saudi Arabia Can't Escape Hormuz" |

These exist in `bots/trending_idea_bot.py` and are used when curiosity gap structures don't fit well. The fallback function:

```python
async def fallback_to_mf_formulas(
    story_context: dict,
    viable_structures: List[ScoredStructure],
    fill_with_mf: bool = True
) -> List[GeneratedTitle]:
    """
    Fill remaining title slots with MF formulas when <3 curiosity gap structures
    score above CONFIDENCE_FLOOR.

    Example: If only hidden_flaw scores 65, we generate:
    - Slot 1: hidden_flaw title (from curiosity gap)
    - Slot 2: MF-0 title (from existing formulas)
    - Slot 3: MF-1 title (from existing formulas)
    """
```

### A.4 Module Relationship: New vs Existing Title Generators

**⚠️ CRITICAL — READ THIS FIRST**

This is the #1 source of confusion. There are TWO modules with "title" and "generator" in different parts of the codebase. They do DIFFERENT things:

| Module | File | Responsibility | When Called |
|--------|------|----------------|-------------|
| **Curiosity Gap Engine** | `curiosity_gap/gap_title_engine.py` | Generate TITLE text using curiosity gap structures | During idea creation (idea_bot, trending_idea_bot) |
| **Thumbnail Title Module** | `thumbnail_title/title_generator.py` | Format THUMBNAIL text (line breaks, CAPS positioning) | During thumbnail image generation |

**The relationship:**
1. `curiosity_gap/gap_title_engine.py` generates title + raw yin/yang thumbnail text together
2. `thumbnail_title/title_generator.py` is NOT replaced — it handles thumbnail RENDERING (text layout, line breaks)
3. The yin/yang text flows FROM curiosity_gap TO thumbnail_title as input

```python
# Step 1: Curiosity gap engine generates title + thumbnail text
from curiosity_gap.gap_title_engine import generate_titles

result = await generate_titles(story)[0]
# result.text = "The $100B Mistake Saudi Arabia Is Hiding"
# result.thumbnail_text = "WORTHLESS PIPELINES"

# Step 2: Thumbnail title module formats for rendering
from thumbnail_title.title_generator import format_thumbnail

thumbnail_spec = await format_thumbnail(
    title=result.text,
    thumbnail_text=result.thumbnail_text,  # FROM curiosity_gap
    # ... other params
)
# thumbnail_spec.line_1 = "WORTHLESS"
# thumbnail_spec.line_2 = "PIPELINES"
```

**Why the naming matters:** The new file is `gap_title_engine.py` (not `title_generator.py`) specifically to prevent wiring confusion. If you see `title_generator.py` in code, it's the EXISTING thumbnail module.

### A.5 Pattern Library API Extensions

Add these methods to `pattern_library.py`:

```python
from enum import Enum
from typing import Optional, List, Dict

class CuriosityStructure(str, Enum):
    """Valid curiosity gap structure IDs."""
    HIDDEN_FLAW = "hidden_flaw"
    ASYMMETRIC_DG = "asymmetric_dg"
    TIME_BOMB = "time_bomb"
    PARADIGM_SHIFT = "paradigm_shift"
    ILLUSION_CONTROL = "illusion_control"
    OTHER = "other"

@dataclass
class CuriosityGapPattern:
    """Performance data for a curiosity gap structure."""
    structure: CuriosityStructure
    avg_ctr_ours: Optional[float]      # Our videos using this
    sample_size_ours: int
    avg_vph_competitors: Optional[float]  # Competitor videos
    sample_size_competitors: int
    status: str  # "proven", "testing", "anti"

@dataclass
class CompetitorPattern:
    """Extracted pattern from competitor video."""
    video_id: str
    channel: str
    title: str
    structure: CuriosityStructure
    confidence: int
    vph: float
    thumbnail_style: Dict
    yin_yang_approach: str

# NEW METHODS
class PatternLibrary:

    def get_curiosity_gap_patterns(
        self,
        structure: Optional[CuriosityStructure] = None
    ) -> List[CuriosityGapPattern]:
        """Get curiosity gap structure performance from title_patterns.md."""

    def get_competitor_patterns(
        self,
        channel: Optional[str] = None,
        structure: Optional[CuriosityStructure] = None,
        min_vph: float = 0
    ) -> List[CompetitorPattern]:
        """Get competitor patterns from competitor_patterns.md."""

    def get_best_structures_for_topic(
        self,
        topic_category: str
    ) -> List[CuriosityStructure]:
        """Get structures that perform best for a topic category."""
```

### A.6 Airtable Pre-Implementation Requirements

**CRITICAL:** Create these fields in Airtable BEFORE deploying code.

**Competitor Videos Table:**
1. Create Single Select field `Curiosity Structure` with options: `hidden_flaw`, `asymmetric_dg`, `time_bomb`, `paradigm_shift`, `illusion_control`, `other`
2. Create Number field `Structure Confidence`
3. Create Long Text field `Thumbnail Style JSON`
4. Create Single Select field `Yin Yang Approach` with options: `from_hook`, `from_gap`
5. Create Single Line field `Yin Yang Text`
6. Create Date field `Analysis Date`
7. Create Checkbox field `Modeled By Us`
8. Create Number field `Our CTR Result`

**Ideas Table:**
1. Create Single Select field `Curiosity Structure` (same options)
2. Create Number field `Structure Confidence`
3. Create Long Text field `Structure Source`
4. Create Single Select field `Thumbnail Approach` with options: `from_hook`, `from_gap`
5. Create Single Line field `Thumbnail Text`
6. Create Long Text field `Pattern Library Snapshot`
7. Create Single Select field `Title Poll Result` with options: `human_selected`, `auto_selected`
8. Create Number field `CTR 12h`

**Graceful Degradation:** Code should use the existing error recovery pattern (try with all fields, drop unknown fields, retry). Fields missing in Airtable should not crash the pipeline.

### A.7 Vision API Selection

**Default: Gemini Vision** (via existing `gemini_client.py`)

Reasons:
- Already integrated in codebase
- Cost-effective for high-volume analysis
- Sufficient quality for thumbnail element extraction

**Fallback: Claude Vision** (via `anthropic_client.py`)

When to use Claude:
- Gemini rate limited
- Need higher accuracy for specific analysis
- Yin/yang relationship detection (more nuanced)

```python
# competitor_analyzer.py

async def analyze_thumbnail(
    video_id: str,
    title: str,
    use_gemini: bool = True
) -> ThumbnailAnalysis:
    """
    Analyze thumbnail using vision API.

    Args:
        video_id: YouTube video ID
        title: Video title (for yin/yang comparison)
        use_gemini: Use Gemini (default) or Claude Vision
    """
    thumbnail_url = await get_thumbnail_url(video_id)

    if use_gemini:
        # Extend existing gemini_client.generate_thumbnail_spec()
        return await gemini_client.analyze_competitor_thumbnail(
            thumbnail_url,
            title
        )
    else:
        return await anthropic_client.analyze_thumbnail_vision(
            thumbnail_url,
            title
        )
```

### A.8 Cost Estimation (Complete)

| Operation | Cost | Volume/Day | Daily Cost |
|-----------|------|------------|------------|
| Phase 1 title analysis | $0.002 | ~50 videos | $0.10 |
| Phase 2 thumbnail (Gemini) | $0.01 | ~10 videos | $0.10 |
| Title generation (Claude) | $0.02 | ~3 ideas | $0.06 |
| Weekly digest clustering | $0.05 | 1/week | $0.007 |
| **Total** | | | **~$0.27/day** |

---

## Appendix B: Existing Code References

Files to extend:
- `autopilot/learning/learning_extractor.py` — add `"structure"` category
- `autopilot/learning/pattern_library.py` — add methods from A.5
- `autopilot/learning/memory_writer.py` — write curiosity gap learnings
- `autopilot/analysis/thumbnail_analyzer.py` — extract yin/yang relationship
- `autopilot/core/confidence_scorer.py` — boost/penalize based on structure performance
- `clients/gemini_client.py` — add `analyze_competitor_thumbnail()` method
- `performance_tracker.py` — add 12h CTR snapshot

Files to integrate with:
- `bots/idea_bot.py` — call `curiosity_gap.gap_title_engine.generate_titles()`
- `bots/trending_idea_bot.py` — call `curiosity_gap.gap_title_engine.generate_titles()`
- `thumbnail_title/title_generator.py` — receive yin/yang thumbnail text as input (NOT replaced)
- `pipeline_control.py` — add new Slack commands + poll reaction handler

New files to create:
- `curiosity_gap/structures.py` — CuriosityStructure enum + structure definitions
- `curiosity_gap/gap_title_engine.py` — title generation with curiosity gap scoring
- `curiosity_gap/thumbnail_generator.py` — yin/yang text generation
- `curiosity_gap/competitor_analyzer.py` — two-phase competitor analysis
- `autopilot/memory/competitor_patterns.md` — competitor pattern storage

Related commit: `78ecabe` (feat: Add learning system and pattern-based scoring)
