# Autopilot Brain Design Spec

**Date:** 2026-03-18
**Status:** Approved
**Author:** Claude + Ryan
**Inspired by:** [karpathy/autoresearch](https://github.com/karpathy/autoresearch)

---

## Executive Summary

The Autopilot Brain is an autonomous orchestration layer that sits above the existing video production pipeline. It transforms the pipeline from a manually-triggered tool into a self-learning content production system.

**Mission:** Maximize click-through rate for this YouTube channel.

**Core Principle:** Every video is an experiment. Every CTR measurement is data. The system compounds learnings over time.

**Key Insight from AutoResearch:** The human programs agent behavior via markdown (`autopilot_program.md`), not code. The autopilot writes instructions (data/overrides), not code modifications.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [The Experiment Loop](#2-the-experiment-loop)
3. [Control Surface](#3-control-surface)
4. [CTR Monitoring & Early Warning](#4-ctr-monitoring--early-warning)
5. [Thumbnail Analysis System](#5-thumbnail-analysis-system)
6. [File Structure & Implementation](#6-file-structure--implementation)
7. [V1 Scope & Phases](#7-v1-scope--phases)

---

## 1. System Overview

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTOPILOT BRAIN                           │
│                                                              │
│   "Your mission: Maximize CTR for this YouTube channel"      │
│                                                              │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│   │   DECIDE    │  │   LEARN     │  │   CONTROL   │         │
│   │             │  │             │  │             │         │
│   │ • Score     │  │ • CTR loop  │  │ • ON/OFF    │         │
│   │   ideas     │  │ • Script    │  │ • Cadence   │         │
│   │ • Pick best │  │   forensics │  │ • Notify    │         │
│   │ • Analyze   │  │ • Pattern   │  │             │         │
│   │   thumbs    │  │   library   │  │             │         │
│   └─────────────┘  └─────────────┘  └─────────────┘         │
│          │                │                │                 │
│          └────────────────┼────────────────┘                 │
│                           ↓                                  │
│              autopilot_program.md                            │
│              (human-editable config)                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    MEMORY LAYER                              │
│                                                              │
│   autopilot/memory/                                          │
│   ├── LEARNINGS.md         ← Master file (always read)      │
│   ├── thumbnail_patterns.md ← What thumbnail elements work  │
│   ├── title_patterns.md     ← What title formulas work      │
│   ├── topic_performance.md  ← Which topics perform for US   │
│   ├── script_forensics.md   ← Retention drop patterns (V2)  │
│   ├── competitor_models.md  ← Which competitors to trust    │
│   └── experiments_log.md    ← Every video as an experiment  │
│                                                              │
│   BEFORE each production cycle:                              │
│     → Read LEARNINGS.md (always)                             │
│     → Read relevant topic files                              │
│                                                              │
│   AFTER each video's performance measured:                   │
│     → Extract learnings                                      │
│     → Append to relevant files                               │
│     → Update LEARNINGS.md summary                            │
└─────────────────────────────────────────────────────────────┘
                            ↓ orchestrates
┌─────────────────────────────────────────────────────────────┐
│              EXISTING PIPELINE (unchanged)                   │
│   discovery → research → script → voice → images →          │
│   thumbnail → render → upload (as draft)                    │
└─────────────────────────────────────────────────────────────┘
                            ↓ you publish manually
                       [ YOUTUBE ]
                            ↓ metrics flow back
┌─────────────────────────────────────────────────────────────┐
│              PERFORMANCE DATA (existing)                     │
│   • YouTube Analytics (CTR, retention, views)               │
│   • Competitor Videos table (VPH, titles, thumbnails)       │
│   • Osiris Learnings table (patterns)                       │
└─────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **Layer on top** — Autopilot orchestrates WHEN and WHAT, pipeline handles HOW
2. **Data not code** — Autopilot writes Airtable overrides, not pipeline modifications
3. **Memory compounds** — Every video adds to the knowledge base
4. **Human in loop** — You publish manually, autopilot handles everything else

---

## 2. The Experiment Loop

Modeled directly on [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

### The Compounding Loop

```
┌─────────────────────────────────────────────────────────────┐
│                  THE COMPOUNDING LOOP                        │
│                                                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                                                      │   │
│   │    ┌──────────┐     ┌──────────┐     ┌──────────┐   │   │
│   │    │  READ    │────▶│  DECIDE  │────▶│  PRODUCE │   │   │
│   │    │  MEMORY  │     │  + WRITE │     │  VIDEO   │   │   │
│   │    └──────────┘     │ OVERRIDES│     └────┬─────┘   │   │
│   │         ▲           └──────────┘          │         │   │
│   │         │                                 ▼         │   │
│   │    ┌────┴─────┐     ┌──────────┐     ┌──────────┐   │   │
│   │    │  UPDATE  │◀────│  ANALYZE │◀────│  MEASURE │   │   │
│   │    │  MEMORY  │     │  RESULTS │     │  CTR     │   │   │
│   │    └──────────┘     └──────────┘     └──────────┘   │   │
│   │                                                      │   │
│   │              LOOP FOREVER (until OFF)                │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### AutoResearch → Video Autopilot Mapping

| AutoResearch | Video Autopilot |
|--------------|-----------------|
| `git checkout -b autoresearch/mar5` | Production cycle starts |
| Read `program.md` + in-scope files | Read `autopilot_program.md` + `LEARNINGS.md` |
| Modify `train.py` (hyperparams) | Write style overrides to Airtable |
| `uv run train.py` (5 min experiment) | Execute pipeline → YouTube draft |
| `grep "^val_bpb:" run.log` | Measure CTR at 6h, 24h, 48h |
| Log to `results.tsv` | Log to `experiments_log.md` |
| If improved → keep commit | If CTR beat competitor → KEEP pattern |
| If worse → git reset | If CTR failed → DISCARD pattern |
| Update learnings, GOTO 1 | Update memory files, GOTO 1 |
| **NEVER STOP** | **NEVER STOP** (until OFF switch) |

### Loop Steps (Detailed)

1. **CHECK CADENCE** — Is it time for next video? (30 days / videos_per_month)
2. **LOAD MEMORY** — Read LEARNINGS.md + relevant pattern files
3. **GATHER CANDIDATES** — Pull from Competitor Videos + Discovery ideas
4. **SCORE CANDIDATES** — Apply weighted signals, cross-ref with memory
5. **SELECT BEST IDEA** — Pick highest confidence, skip if below threshold
6. **ANALYZE COMPETITOR THUMBNAIL** — Vision extraction of winning elements
7. **SELECT TITLE** — Pick title matching proven patterns
8. **NOTIFY** — Slack message with full reasoning
9. **EXECUTE PIPELINE** — Write overrides, trigger pipeline
10. **NOTIFY DRAFT READY** — Alert human to publish
11. **WAIT FOR PUBLISH** — Monitor for status change
12. **MEASURE PERFORMANCE** — CTR at 6h, 24h, 48h, 7d
13. **ANALYZE RESULTS** — KEEP or DISCARD pattern
14. **UPDATE MEMORY** — Log experiment, update pattern files
15. **GOTO 1** — Never stop

---

## 3. Control Surface

### autopilot_program.md

```markdown
# Autopilot Program

## Mission

Your mission: **Maximize click-through rate for this YouTube channel.**

You have access to the full video production pipeline. Your job is to:
1. Find winning videos from competitors (high VPH = proven appeal)
2. Understand WHY they're winning (thumbnail, title, topic timing)
3. Model the winning elements for OUR channel
4. Produce the video (pipeline handles execution)
5. Measure YOUR results vs the competitor you modeled
6. Learn what works for THIS channel, not just what worked for them

You are not a passive scheduler. You are an active learner.
Every video is an experiment. Every CTR measurement is data.

The pipeline is your hands. You are the brain.

---

## State

autopilot: ON          # ON or OFF — the master switch
last_cycle: 2026-03-18
videos_produced: 0
channel_avg_ctr: 0.0

---

## Cadence

videos_per_month: 15        # Target production rate
production_interval_days: 2  # Calculated: 30 / videos_per_month

---

## Confidence Scoring Weights

weights:
  competitor_vph: 0.30       # How fast is source video growing?
  topic_channel_fit: 0.25    # Has this topic worked for OUR channel?
  timing_freshness: 0.20     # Is this topic hot right now?
  channel_momentum: 0.10     # Is this competitor on an uptrend?
  retention_patterns: 0.08   # Do we retain viewers on this type?
  title_formula: 0.07        # Which title patterns work for us?

---

## Thresholds

thresholds:
  min_confidence_score: 60     # Don't produce if best idea < this
  min_competitor_vph: 50       # Ignore competitors below this VPH
  max_idea_age_days: 7         # Ignore stale ideas
  ctr_success_threshold: 4.0   # CTR >= this = KEEP pattern
  ctr_failure_threshold: 2.5   # CTR <= this = DISCARD pattern
  early_warning_hours: 6       # When to first check CTR

---

## Scope Boundaries

**What the autopilot CAN do:**
- Score and select ideas from candidates
- Analyze competitor thumbnails (vision)
- Write style overrides to Airtable fields
- Select titles from generated options
- Trigger pipeline execution
- Read scripts for forensic analysis
- Update memory files with learnings

**What the autopilot CANNOT do:**
- Modify pipeline code (bots, clients, Remotion)
- Publish videos to YouTube (human does this)
- Delete Airtable records
- Change this config file (human does this)
- Spend money beyond normal pipeline costs
```

---

## 4. CTR Monitoring & Early Warning

### Monitoring Timeline

```
PUBLISH
   │
   ▼
┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
│  0h  │───▶│  6h  │───▶│ 24h  │───▶│ 48h  │───▶│  7d  │
│      │    │EARLY │    │FIRST │    │FULL  │    │FINAL │
│ Live │    │WARN  │    │READ  │    │DATA  │    │VERDICT
└──────┘    └──────┘    └──────┘    └──────┘    └──────┘
               │            │           │           │
               ▼            ▼           ▼           ▼
           CTR check    CTR + views  Retention   Learning
           Impressions  Avg duration  curve      extracted
```

### 6-Hour Early Warning

First actionable signal. YouTube shows impressions and CTR within 4-6 hours.

**Alert Levels:**
- `🚨 CRITICAL` — CTR < 2.5% → Consider thumbnail/title swap
- `⚠️ WARNING` — CTR < 3.5% → Monitor closely
- `📊 NORMAL` — CTR 3.5-5.0% → On track
- `✅ STRONG` — CTR >= 5.0% → Pattern working

### 48-Hour Analysis

Retention curve becomes available. Script forensics kicks in (V2).

**CTR Verdict:**
- `KEEP` — CTR >= 4.0%, pattern confirmed
- `DISCARD` — CTR <= 2.5%, pattern failed
- `NEUTRAL` — In between, need more data

---

## 5. Thumbnail Analysis System

### Pipeline

```
Competitor Video (VPH: 150, CTR: 5.8%)
         │
         ▼
┌──────────────┐
│ Fetch thumb  │ ← YouTube API
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Vision       │ ← Claude vision analysis
│ Analysis     │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│ Extracted Elements:                          │
│ • Colors: red background, yellow text        │
│ • Composition: face left, text right         │
│ • Text: 2 lines, 70% frame width, caps       │
│ • Subject: leader portrait, stern expression │
└──────────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ Cross-ref    │ ← Read thumbnail_patterns.md
│ with memory  │   What works for OUR channel?
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│ Adaptation Logic:                            │
│ • KEEP: red + yellow (proven for us)         │
│ • ADJUST: text 65% → 70% (our optimal)       │
│ • ADD: subtle map overlay (brand element)    │
│ • AVOID: blue tones (anti-pattern)           │
└──────────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ Write to     │ → Airtable: Thumbnail Style Override
│ Airtable     │
└──────────────┘
```

### Vision Analysis Output

```json
{
  "colors": {
    "background": "deep red gradient",
    "text": "bright yellow with black outline",
    "accents": "white, gold"
  },
  "composition": "face_left_text_right",
  "text": {
    "lines": 2,
    "size_pct": 65,
    "style": "bold caps"
  },
  "subject": {
    "face": true,
    "expression": "stern/serious"
  },
  "style": "editorial illustration, high saturation"
}
```

### Adaptation Rules

The autopilot doesn't just copy — it adapts based on channel memory:
- Cross-reference with proven patterns
- Apply channel-optimal sizing (e.g., 70% text width)
- Add brand signature elements
- Avoid known anti-patterns

---

## 6. File Structure & Implementation

### Directory Structure

```
skills/video-pipeline/
├── autopilot/                          # NEW: The brain layer
│   │
│   ├── autopilot.py                    # Main orchestrator (the loop)
│   ├── autopilot_program.md            # Human-editable config
│   │
│   ├── core/
│   │   ├── confidence_scorer.py        # Weighted idea ranking
│   │   ├── cadence_manager.py          # Videos/month → schedule
│   │   ├── state_manager.py            # ON/OFF, persistence
│   │   └── notifier.py                 # Slack notifications
│   │
│   ├── analysis/
│   │   ├── thumbnail_analyzer.py       # Vision analysis
│   │   ├── thumbnail_adapter.py        # Generate overrides
│   │   ├── title_selector.py           # Pick best title
│   │   └── script_forensics.py         # Retention mapping (V2)
│   │
│   ├── monitoring/
│   │   ├── ctr_monitor.py              # 6h, 24h, 48h checks
│   │   ├── early_warning.py            # Alert logic
│   │   └── performance_comparator.py   # Us vs competitor
│   │
│   ├── learning/
│   │   ├── learning_extractor.py       # Extract patterns
│   │   ├── memory_writer.py            # Update memory files
│   │   └── pattern_library.py          # Read/query patterns
│   │
│   └── memory/                         # Persistent learnings
│       ├── LEARNINGS.md
│       ├── thumbnail_patterns.md
│       ├── title_patterns.md
│       ├── topic_performance.md
│       ├── script_forensics.md
│       ├── competitor_models.md
│       └── experiments_log.md
│
├── pipeline.py                         # UNCHANGED
├── pipeline_control.py                 # MODIFIED: Add commands
├── setup_cron.sh                       # MODIFIED: Add cron jobs
└── ...                                 # All existing unchanged
```

### Module Responsibilities

| Module | Single Responsibility |
|--------|----------------------|
| `autopilot.py` | Main loop. Reads config, orchestrates, never stops. |
| `confidence_scorer.py` | Score ideas using weighted signals. |
| `cadence_manager.py` | Check if time to produce. |
| `thumbnail_analyzer.py` | Vision API extraction. |
| `thumbnail_adapter.py` | Generate style override. |
| `ctr_monitor.py` | Poll YouTube API at intervals. |
| `learning_extractor.py` | Extract patterns from results. |
| `memory_writer.py` | Update markdown memory files. |

### Cron Schedule (Additions)

| Time | Job | What It Does |
|------|-----|--------------|
| Every 4h | `autopilot --check-cycle` | Check if production slot available |
| Every 2h | `ctr_monitor --check-active` | Monitor CTR for recent videos |
| 8:30 AM | `learning_extractor --daily` | Extract learnings from 48h+ videos |

### Slack Commands (New)

```
autopilot on/off        # Toggle autopilot
autopilot status        # Show state, next production
autopilot force         # Force production now
autopilot config        # Show weights/thresholds
learnings               # Show LEARNINGS.md summary
patterns thumbnail      # Show thumbnail patterns
ctr check [title]       # Force CTR check
```

---

## 7. V1 Scope & Phases

### Scope Boundaries

**V1: Nail CTR First**
- ON/OFF switch
- Cadence management
- Confidence scoring
- Thumbnail analysis + override generation
- Title selection
- Memory system
- CTR monitoring (6h, 24h, 48h)
- Early warning alerts
- Learning extraction
- Experiment logging

**V2: Optimize Retention** (later)
- Script forensics
- Retention → script mapping
- Hook timing recommendations

**V3: Full Autonomy** (later)
- Auto-publish with safety window
- A/B thumbnail testing
- Dynamic weight adjustment

### Implementation Phases

| Phase | Deliverable | Test |
|-------|-------------|------|
| 1. Foundation | Loop + config | ON/OFF works, cadence checked |
| 2. Decision Engine | Scoring + selection | Ideas ranked, Slack notified |
| 3. Thumbnail Intel | Analysis + adaptation | Override written to Airtable |
| 4. Memory System | Persistence | Learnings survive restarts |
| 5. CTR Monitoring | Performance tracking | 6h/24h/48h checks fire |
| 6. Learning Loop | Pattern extraction | Memory updated after 48h |
| 7. Integration | Cron + Slack | Full autonomous operation |

### Success Criteria

| Metric | Target |
|--------|--------|
| ON/OFF works | Toggle via config or Slack |
| Cadence respected | Produces at configured rate |
| Ideas scored with reasoning | Slack shows breakdown |
| Thumbnails analyzed | Vision extracts correctly |
| Overrides generated | Airtable populated |
| Memory persists | Survives restarts |
| CTR monitored | Checks fire on schedule |
| Learnings extracted | Pattern files updated |
| Full cycle completes | Idea → Draft autonomously |

---

## Memory File Templates

### LEARNINGS.md

```markdown
# Autopilot Learnings

Last updated: {date}
Videos produced: {count}
Avg CTR: {avg}%
Best CTR: {best}% ("{best_title}")

## Top 5 Proven Patterns

1. {pattern_1} (n={sample_size})
2. {pattern_2}
...

## Current Hypotheses (Testing)

- [ ] {hypothesis_1} — testing on next {n} videos

## Anti-Patterns (Stop Doing)

- {anti_pattern_1} ({n} failures)
```

### experiments_log.md

```markdown
# Experiment Log

## Video #{n}: "{title}"
- Date: {date}
- Modeled: {competitor_title}
- Predicted CTR: {predicted}% | Actual: {actual}%
- Status: {KEEP/DISCARD}
- Thumbnail override: {override}
- Title formula: {formula}
- Learnings: {extracted}
```

---

## Appendix: The Tagline

```
The pipeline is your hands. You are the brain.

Every video is an experiment.
Every CTR measurement is data.
Compound what works. Discard what doesn't.
Never stop learning.
```

---

*Design inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — autonomous experimentation, single metric focus, never-stopping loops, human-editable program files.*
