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
