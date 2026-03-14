# Airtable Schema

## Idea Concepts Table (Source of Truth for NEW ideas)

Core fields (always written):
- `Status`, `Video Title`, `Hook Script`, `Past Context`, `Present Parallel`, `Future Prediction`
- `Thumbnail Prompt`, `Writer Guidance`, `Original DNA` (JSON backup), `Source`

Rich fields (written by research):
- `Framework Angle`, `Headline`, `Timeliness Score`, `Audience Fit Score`, `Content Gap Score`
- `Source URLs`, `Executive Hook`, `Thesis`, `Date Surfaced`
- `Research Payload` (JSON), `Thematic Framework`

Style override fields (set via Slack `!style` commands):
- `Image Style Override` (Long Text) — custom instructions for image prompt prefix. Supports `REPLACE:`, `APPEND:`, or `+` prefixes.
- `Thumbnail Style Override` (Long Text) — custom instructions for thumbnail template. Supports `REPLACE:`, `APPEND:`, or `+` prefixes.
- `Accent Color` (Single Line Text) — per-video accent color override. If set, used directly instead of topic category mapping. Valid values: `cold teal`, `muted crimson`, `warm amber`, `muted green`.
- `Image Model Override` (Multiple Select) — hot-swap scene image model. Options: `z-image`, `Nano Banana`. Set via Slack `!model` command.
- `Visual Style` (Single Select) — visual profile override. Options: `mannequin_storytelling`, `holographic_hud`, `cinematic_dossier`, `clay_mannequin`. Default: `mannequin_storytelling`. Set via Slack `!visualstyle` command.

Visual consistency fields (auto-generated):
- `Story Bible` (Long Text) — JSON containing character bible, location bible, visual arc, and recurring props for consistent visuals across the video. Generated automatically before image prompts when using mannequin profiles. Structure: `{"characters": [...], "locations": [...], "visual_arc": [...], "recurring_props": [...]}`

Optional fields:
- `Reference URL`, `Idea Reasoning`, `Source Views`, `Source Channel`
- `Google Drive Folder ID`, `Thumbnail`, `Pipeline Mode`, `Notes`
- `Upload Status`, `YouTube Video ID`, `YouTube URL`

Performance fields (written by `performance_tracker.py`, daily cron):
- Lifetime: `Views`, `Likes`, `Comments`, `Subscribers Gained`
- Analytics (YouTube Analytics API): `Avg View Duration (s)`, `Avg Retention (%)`, `Watch Time (hours)`
- Reporting (YouTube Reporting API bulk CSV): `Impressions`, `CTR (%)`
- Snapshots (written once): `Views 24h`, `Views 48h`, `Views 7d`, `Views 30d`, `CTR 48h (%)`, `Retention 48h (%)`
- Metadata: `Last Analytics Sync`, `Upload Date`

Osiris analysis fields (written by `osiris/performance_analyzer.py`):
- `Post-Mortem 48h` (Long Text) — JSON of 48h analysis (CTR/retention verdict, recommendations)
- `Post-Mortem 7d` (Long Text) — JSON of 7d final analysis + learnings extracted
- `Performance Verdict` (Single Select) — Overall performance: `strong`, `average`, `weak`

## Scripts Table

- `Scene`, `Scene text`, `Title`, `Voice ID`
- `Script Status`: "Create" → "Finished"
- `Voice Status`, `Voice Over` (attachment URL)
- `Sources` (show notes for YouTube description)

## Images Table

- `Scene`, `Image Index`, `Sentence Text`, `Image Prompt`, `Shot Type`
- `Video Title`, `Aspect Ratio`, `Status`: "Pending" → "Done"
- `Image` (attachment), `Video`, `Video Prompt`
- Animation: `Hero Shot`, `Video Clip URL`, `Animation Status`, `Video Duration`

## Competitor Channels Table

Used by the discovery scanner to scrape competitor YouTube videos and generate ideas from top performers.

Required fields:
- `Channel Name` (Single Line Text) — Name of the competitor channel
- `Channel URL` (URL) — YouTube channel URL (e.g., `https://www.youtube.com/@CaspianReport`)
- `Category` (Single Select) — Channel category. Options: `Geopolitics`, `Finance`, `Economy`, `Tech`
- `Active` (Checkbox) — Include in discovery scraping (only active channels are scraped)
- `Last Scraped` (Date) — Auto-updated when channel is scraped by the discovery scanner
- `Notes` (Long Text) — Optional notes about the channel

Setup:
1. Create the table in Airtable with name "Competitor Channels"
2. Add the fields above
3. Set `AIRTABLE_COMPETITOR_CHANNELS_TABLE_ID` in `.env` to the table ID
4. Run `python setup_competitor_channels.py` to verify setup
5. Add competitor channels and check the `Active` checkbox

Example channels to add:
- CaspianReport (1.8M subs) — Geopolitics
- AiTelly (2M subs) — Geopolitics/Finance
- Economics Explained (2.5M subs) — Economy
- PolyMatter (2M subs) — Economy

## Competitor Videos Table (Osiris Training Data)

Stores ALL scraped competitor videos (not just winners) for long-term performance analysis. This is Osiris's training data — after 3 months you'll have thousands of videos with VPH scores showing which topics/titles perform best in your niche.

Required fields:
- `Video ID` (Single Line Text) — YouTube video ID (used for deduplication)
- `Title` (Single Line Text) — Video title
- `URL` (URL) — Full YouTube video URL
- `Channel` (Single Line Text) — Channel name
- `Channel URL` (URL) — Channel URL
- `Views` (Number) — View count at scrape time
- `VPH` (Number, decimal) — Views per hour at scrape time
- `Hours Old` (Number, decimal) — Age in hours when scraped
- `Published Date` (Date) — Video publish date
- `Scrape Date` (Date) — When we scraped this video
- `Modeled` (Checkbox) — Whether we've created an idea from this video
- `Our Video` (Single Line Text) — Title of our video if we modeled it (optional)
- `Topic Cluster` (Single Select) — Auto-categorized topic (Phase 2, optional)

Setup:
1. Create the table in Airtable with name "Competitor Videos"
2. Add the fields above
3. Set `AIRTABLE_COMPETITOR_VIDEOS_TABLE_ID` in `.env` to the table ID
4. Run `python -m osiris.competitor_scraper --dry-run` to verify setup

## Osiris Learnings Table (Performance Learning Data)

Persists learned patterns from performance analysis. After analyzing your videos at 48h and 7d milestones, Osiris extracts reusable learnings that get injected into generation prompts (titles, hooks, thumbnails).

Required fields:
- `Category` (Single Select) — Learning category: `title`, `hook`, `thumbnail`, `retention`, `framework`
- `Pattern` (Long Text) — The learned pattern description (e.g., "Question format title: strong CTR (5.2%)")
- `Confidence` (Number) — 0-100 confidence score based on sample size and consistency
- `Sample Size` (Number) — How many videos this pattern is based on
- `Avg CTR` (Number, decimal) — Average CTR for videos matching this pattern (optional)
- `Avg Retention` (Number, decimal) — Average retention for videos matching this pattern (optional)
- `Source Videos` (Long Text) — JSON array of video titles that inform this learning (optional)
- `Created` (Date) — When this learning was first identified
- `Last Updated` (Date) — When this learning was last recalculated
- `Active` (Checkbox) — Whether to include in prompt injection (default true)

Setup:
1. Create the table in Airtable with name "Osiris Learnings"
2. Add the fields above
3. Set `AIRTABLE_OSIRIS_LEARNINGS_TABLE_ID` in `.env` to the table ID
4. Run `python -m osiris analyze --dry-run` to verify setup

The analyzer runs daily at 7:30 AM PT (after performance_tracker), analyzing videos at 48h/7d milestones.

## Known Schema Issues (See ANIMATION_SYSTEM_REVIEW.md Feature 4)

- **CRITICAL**: Tables joined by string matching (`Title` = `Video Title`), NOT linked records. Typos break relationships.
- Images table has 3 overlapping status fields (`Status`, `Video Status`, `Animation Status`). Update ALL relevant ones.
- `Sentence Index` and `Image Index` are the same value with different names.
- Thumbnail field format is inconsistent - code tries 3 field name/format combos as fallbacks.

## Airtable Error Recovery Pattern (Used Everywhere)

The codebase uses graceful field degradation when writing to Airtable:
```
Try: Create with all fields
Catch UnknownField → extract bad field from error → retry without it (loop)
Finally: If still failing → create with core fields only → update rich fields individually
```
**Follow this pattern** when adding new Airtable writes. Never let a single bad field kill the whole record creation.
