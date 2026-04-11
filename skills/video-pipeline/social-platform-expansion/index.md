# Social Platform Expansion — Command Center

> STATUS: Future build. This folder is the complete playbook for expanding
> Economy FastForward from YouTube-only to multi-platform social promotion.
> When activated, this system takes video pipeline artifacts (research,
> script, hooks, SEO data, performance learnings) and generates
> platform-native promotional content.

## 1. Identity

Social promotion system for Economy FastForward / Power Doctrine.
Extends the YouTube video pipeline to 3 high-impact social platforms.

Brand: Power Doctrine (Economy FastForward)
Niche: Geopolitics, global economics, and how power and money actually move
Voice: Investigative analyst who followed the money and found what the public isn't being told
Mission: Turn each video's research and narrative into 3 platform-native
social posts that each RETHINK the topic for their platform — not reformat

## 2. Pipeline Integration

Unlike a standalone skill graph, this system is FED by pipeline artifacts:

### Input Sources (from existing pipeline)
- **Research payload** — deep-dive facts, sources, data points from `research/agent.py`
- **Script** — 6-act narrative with hooks, cliffhangers, frameworks from `script/run.py`
- **Video hook** — 15-second opener from `HookAgent` (optimized for retention)
- **SEO data** — keywords, hashtags, hook line, summary from `upload/seo_generator.py`
- **Title + curiosity gap structure** — from `title_idea/curiosity_gap/`
- **Performance learnings** — CTR, VPH, AVD patterns from `analytics/osiris/`
- **Autopilot memory** — what hooks, thumbnails, topics worked from `autopilot/learning/`

### What This System Adds
- Platform-native social copywriting (not video scripts)
- Per-platform hook adaptation (video hooks ≠ social hooks)
- Repurposing chain that rethinks the angle per platform
- Scheduling and posting cadence

## 3. Node Map

### Platforms (3 high-impact channels that drive YouTube views)
- [[x]] — short-form, hook-driven, 280-2000 chars, casual lowercase.
  post 5-7x/week. contrarian takes, proof posts, thread breakdowns.
  PRIMARY discovery engine — drives new viewer acquisition
- [[linkedin]] — long-form narrative, professional but human, 1300-2000 chars.
  post 3x/week. personal investigation stories with geopolitical insight.
  PROFESSIONAL reach — drives high-value subscribers
- [[newsletter]] — deep-dive format, 1000-2000 words, weekly.
  behind-the-scenes research, exclusive analysis, subscriber relationship.
  OWNED audience — no algorithm dependency

### Voice (extends power_doctrine_v2 for social copywriting)
- [[brand-voice]] — the investigative analyst personality adapted from
  video scripts to social text. same DNA, different medium
- [[platform-tone]] — how the core voice adapts per platform.
  same person, different room. X = bar conversation, LinkedIn = conference
  panel, Newsletter = private briefing

### Engine (operational backbone)
- [[hooks]] — social hook formulas mapped to the 5 curiosity gap structures.
  references Osiris learnings for what CTR patterns actually work.
  updated by performance data, not guesswork
- [[repurpose]] — the promotion chain: video artifacts → 3 platform outputs.
  defines which platform gets written first, adaptation order, and what
  changes between each version
- [[scheduling]] — posting calendar, frequency rules, batch workflow
  timed around video publish schedule
- [[content-types]] — format definitions for social: threads, takes,
  proof posts, investigation teasers, newsletter deep-dives

### Audience
- [[geopolitics-enthusiasts]] — primary audience. skeptics of mainstream
  narrative, want to understand how power actually works. they follow
  the money. they want specifics, not opinions
- [[casual-observers]] — secondary audience. curious about world events
  but not deep in geopolitics. want accessible explanations of complex
  power dynamics. "wait, that affects MY money?" moments

## 4. Execution Instructions

When given a video to promote (post-upload or pre-launch):

1. Ingest pipeline artifacts: research payload, script, hook, SEO data, title
2. Read [[brand-voice]] for core social personality
3. Read [[hooks]] and select the best social hook formula for this topic
   — cross-reference with Osiris learnings on what CTR patterns worked
4. Read [[repurpose]] for the promotion chain order
5. Write for the FIRST platform in the chain ([[x]])
6. For each subsequent platform, read that platform's node and
   [[platform-tone]] to adapt. RETHINK the angle, not just reformat
7. Apply [[scheduling]] rules for timing relative to video publish
8. Output one native post per platform, each ready to publish

CRITICAL RULE: The output is NOT the video description copy-pasted
to 3 platforms. It's 3 pieces that each approach the topic from a
different angle — the investigation angle, the personal stakes angle,
the deep analysis angle — using the research as raw material.

## 5. Future Wiring

When this system gets built into the pipeline:

```
Pipeline Integration Points:
├── After upload/seo_generator.py completes
│   └── social_promotion/generate.py reads video artifacts
│       ├── Generates X post (discovery hook)
│       ├── Generates LinkedIn post (investigation narrative)
│       └── Generates newsletter section (deep analysis)
│
├── Osiris performance feedback loop
│   └── Track which social hooks drove YouTube clicks
│   └── Feed back into hooks.md and autopilot learnings
│
└── Scheduling
    └── X: publish day-of (pre-launch teaser + post-publish)
    └── LinkedIn: publish day-of or day-after
    └── Newsletter: weekly digest of best videos
```
